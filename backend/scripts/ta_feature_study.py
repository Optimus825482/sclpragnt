"""Sinyal mantığı yeniden kurma çalışması — kazanan/kaybeden analizi ve yeni kural sınaması (2026-10-22, kullanıcı isteği).

Soru: mevcut teknik tarama (yön puanı ≥ +3) hangi noktalarda yanıltıyor, hangi unsurlar doğru kararı destekliyor; BTC
düşerken de yükselen semboller var — sinyal mantığı buna göre nasıl yeniden kurulur?

Yöntem:
  1. Son N günde her 4 saatte bir kesit (ileriye bakma yok: yalnız kesitten önce kapanmış mumlar). Evren: bugün 24 sa
     hacmi ≥ 5M TL olan TRY çiftleri. Her sembol × kesit için gösterge özellikleri (trend, momentum, oynaklık, hacim,
     seviye uzaklıkları, BTC rejimi, BTC'ye göreli güç, piyasa genişliği) hesaplanır — `ta_symbol_report` ile aynı tanımlar.
  2. Sonuç: kesitten sonraki 24 saat, 15m mumlarla: MFE, MAE, 24 sa getiri; çıkış kuralları: iz süren 3/1,5 + %10 stop
     (geçen testin en iyisi) ve sabit +%3 + %10 stop; 10.000 TL, komisyon %0,1125/bacak.
  3. Analiz: mevcut sinyallerde (puan ≥ +3) kazanan (iz süren net > 0) ve kaybedenlerin özellik dağılımı; her özellik için
     üç dilim (alt/orta/üst) kazanma oranı ve ortalama net; BTC düşen kesitlerde aynı analiz.
  4. Yeni kural adayları (önceden tanımlı, veriden sonra eklenmedi) ilk yarı / ikinci yarı ayrımıyla sınanır.

Çıktı: docs/SINYAL_YENIDEN_KURMA_<tarih>.html + work/ta_feature_study_<tarih>.json. Yatırım tavsiyesi değildir.
KULLANIM: python backend/scripts/ta_feature_study.py [--days 14] [--step-hours 4]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ta_symbol_report as T                  # noqa: E402
from app import ma_buy_h4_scan as scan_mod    # noqa: E402
from app import ma_buy_signals as S           # noqa: E402
from app.binance_tr_public import klines      # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
FEE = 0.001125
STAKE = 10000.0
STOP_PCT = 10.0
M15 = 900_000
DOCS_DIR = T.DOCS_DIR
WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")


KEEP = {"15m": 1000, "1h": 400, "4h": 300, "1d": 420}


def cut(data: dict, cutoff_ms: int) -> dict:
    """Kesitten önce kapanmış mumlar (ikili arama; son KEEP[tf] mum)."""
    import bisect
    out = {}
    for tf in [k for k in data if not k.startswith("_")]:
        bars = data[tf]
        ts = data.get("_ts_" + tf)
        if ts is None:
            ts = [b["t"] for b in bars]
            data["_ts_" + tf] = ts
        i = bisect.bisect_right(ts, cutoff_ms - T.TF_MS[tf])
        out[tf] = bars[max(0, i - KEEP[tf]):i]
    return out


def aggregate(b15: list[dict], tf_ms: int) -> list[dict]:
    """15m → daha büyük mum (yalnız tam dolu kovalar)."""
    need = tf_ms // M15
    out, cur, key = [], [], None
    for b in b15:
        k = b["t"] // tf_ms
        if k != key:
            if len(cur) == need:
                out.append({"t": key * tf_ms, "o": cur[0]["o"], "h": max(x["h"] for x in cur), "l": min(x["l"] for x in cur),
                            "c": cur[-1]["c"], "v": sum(x["v"] for x in cur), "q": sum(x["q"] for x in cur)})
            cur, key = [], k
        cur.append(b)
    if len(cur) == need:
        out.append({"t": key * tf_ms, "o": cur[0]["o"], "h": max(x["h"] for x in cur), "l": min(x["l"] for x in cur),
                    "c": cur[-1]["c"], "v": sum(x["v"] for x in cur), "q": sum(x["q"] for x in cur)})
    return out


def _rows_to_bars(rows) -> list[dict]:
    out = []
    for r in rows:
        try:
            out.append({"t": int(r["open_time"]), "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                        "v": float(r["volume"] or 0), "q": float(r["quote_volume"] or 0) or float(r["volume"] or 0) * float(r["close"])})
        except (TypeError, ValueError, KeyError):
            continue
    return out


async def load_db(sym: str, start_ms: int, end_ms: int) -> dict | None:
    """Yerel historical_candles → {15m, 1h, 4h, 1d}. 2026-10-22: 1h/4h/1d arşivde varsa oradan (derin geçmiş: 4h 180 gün,
    1d 400 gün), yoksa 15m'den türetilir. Arşivdeki günlük mum borsa UTC gününe hizalıdır."""
    from app import database
    b15 = _rows_to_bars(await database.get_market_candles(sym, "15m", start_ms=start_ms, end_ms=end_ms))
    if len(b15) < 500:
        return None
    out = {"15m": b15}
    for tf, back_days in (("1h", 120), ("4h", 200), ("1d", 420)):
        rows = await database.get_market_candles(sym, tf, start_ms=end_ms - back_days * 86_400_000, end_ms=end_ms)
        bars = _rows_to_bars(rows)
        agg = aggregate(b15, T.TF_MS[tf])
        out[tf] = bars if len(bars) >= len(agg) else agg   # arşiv en az türetilen kadar doluysa arşiv
    return out


# ------------------------------------------------------------------------------------------------------ özellikler
def features(sym: str, pit: dict) -> dict | None:
    b15, b1, b4 = pit["15m"], pit["1h"], pit["4h"]
    if len(b15) < 120 or len(b1) < 60 or len(b4) < 40:
        return None
    c1 = [x["c"] for x in b1]
    c4 = [x["c"] for x in b4]
    px = b15[-1]["c"]
    s7, s20, s50, s99 = (T.last(T.sma(c4, n)) for n in (7, 20, 50, 99))
    e20_1, e50_1 = T.last(T.ema(c1, 20)), T.last(T.ema(c1, 50))
    h4h, l4h = T.swings(b4[-60:], 2)
    hh = len(h4h) >= 2 and h4h[-1][1] > h4h[-2][1]
    hl = len(l4h) >= 2 and l4h[-1][1] > l4h[-2][1]
    above = sum(1 for m in (s7, s20, s50, s99) if m is not None and px > m)
    trend4 = "up" if above >= 3 and hl else "down" if above <= 1 and not hh and len(h4h) >= 2 else "neutral"
    rsi1, rsi4 = T.last(S.rsi_series(c1, 14)), T.last(S.rsi_series(c4, 14))
    _, _, mh1 = T.macd(c1)
    _, _, mh4 = T.macd(c4)
    mh1_up = mh1[-1] is not None and mh1[-2] is not None and mh1[-1] > mh1[-2]
    mh4_up = mh4[-1] is not None and mh4[-2] is not None and mh4[-1] > mh4[-2]
    st1 = T.last(S.stoch_rsi_k(c1))
    adx4, dip4, dim4 = T.adx_di(b4)
    a1, a4 = T.atr(b1), T.atr(b4)
    bb = T.bollinger(c1)
    vw = T.vwap(b15[-96:])
    obv = T.obv_slope(b1, 24)
    q12 = sum(x["q"] for x in b15[-48:])
    qavg = sum(x["q"] for x in b15[-672:]) / 14 if len(b15) >= 672 else (sum(x["q"] for x in b15) / (len(b15) / 48))
    hi24, lo24 = max(x["h"] for x in b15[-96:]), min(x["l"] for x in b15[-96:])
    hi7 = max(x["h"] for x in b15[-672:])
    chg24 = (px / b15[-97]["c"] - 1) * 100 if len(b15) > 97 else None
    chg4 = (px / b15[-17]["c"] - 1) * 100 if len(b15) > 17 else None
    last4 = b4[-1]
    body4 = (last4["c"] - last4["o"]) / last4["o"] * 100 if last4["o"] else 0.0
    score = 0
    score += 1 if trend4 == "up" else -1 if trend4 == "down" else 0
    score += 1 if (e20_1 and e50_1 and e20_1 > e50_1 and px > e20_1) else -1 if (e20_1 and px < e20_1) else 0
    score += 1 if (mh1[-1] is not None and mh1[-1] > 0 and mh1_up) else -1 if (mh1[-1] is not None and mh1[-1] < 0) else 0
    score += 1 if (dip4 and dim4 and dip4 > dim4 and adx4 and adx4 >= 20) else 0
    score += 1 if (obv and obv > 0.1) else -1 if (obv and obv < -0.1) else 0
    score -= 1 if (rsi1 and rsi1 >= 75) else 0
    qv24 = sum(x["q"] for x in b15[-96:])
    # --- günlük trend bağlamı (2026-10-22): D1 arşivi; yetersizse None
    b1d = pit.get("1d") or []
    daily = {"d_dist_sma50": None, "d_dist_sma200": None, "d_above50": None, "d_above200": None, "d_rsi": None, "d_adx": None,
             "d_macd_up": None, "d_dist_hi30": None, "d_dist_hi90": None, "d_chg7": None, "d_range20": None}
    if len(b1d) >= 60:
        cd = [x["c"] for x in b1d]
        s50 = T.last(T.sma(cd, 50))
        s200 = T.last(T.sma(cd, 200)) if len(cd) >= 200 else None
        _, _, mhd = T.macd(cd)
        adx_d, _, _ = T.adx_di(b1d)
        hi30 = max(x["h"] for x in b1d[-30:]); hi90 = max(x["h"] for x in b1d[-90:])
        lo20 = min(x["l"] for x in b1d[-20:]); hi20 = max(x["h"] for x in b1d[-20:])
        daily.update({
            "d_dist_sma50": (px / s50 - 1) * 100 if s50 else None, "d_above50": bool(s50 and px > s50),
            "d_dist_sma200": (px / s200 - 1) * 100 if s200 else None, "d_above200": (bool(px > s200) if s200 else None),
            "d_rsi": T.last(S.rsi_series(cd, 14)), "d_adx": adx_d,
            "d_macd_up": bool(mhd[-1] is not None and mhd[-2] is not None and mhd[-1] > mhd[-2]),
            "d_dist_hi30": (px / hi30 - 1) * 100, "d_dist_hi90": (px / hi90 - 1) * 100,
            "d_chg7": (px / cd[-8] - 1) * 100 if len(cd) >= 8 else None, "d_range20": (hi20 - lo20) / lo20 * 100 if lo20 else None,
        })
    return {
        "qv24": qv24, **daily,
        "score": score, "trend4": trend4, "above4": above, "hh": hh, "hl": hl,
        "ema_up": bool(e20_1 and e50_1 and e20_1 > e50_1 and px > e20_1),
        "rsi1": rsi1, "rsi4": rsi4, "macd1_pos": bool(mh1[-1] is not None and mh1[-1] > 0), "macd1_up": mh1_up,
        "macd4_pos": bool(mh4[-1] is not None and mh4[-1] > 0), "macd4_up": mh4_up, "stoch1": st1,
        "adx4": adx4, "di_diff": (dip4 - dim4) if (dip4 is not None and dim4 is not None) else None,
        "atr1p": a1 / px * 100 if a1 else None, "atr4p": a4 / px * 100 if a4 else None,
        "bb_pos": bb["pos"] if bb else None, "bb_width": bb["width_pct"] if bb else None,
        "vwap_rel": (px / vw - 1) * 100 if vw else None, "obv": obv, "vol_ratio": q12 / qavg if qavg else None,
        "chg24": chg24, "chg4": chg4, "dist_hi24": (px / hi24 - 1) * 100, "dist_lo24": (px / lo24 - 1) * 100,
        "dist_hi7": (px / hi7 - 1) * 100, "dist_s20_4": (px / s20 - 1) * 100 if s20 else None,
        "dist_s99_4": (px / s99 - 1) * 100 if s99 else None, "body4": body4, "px": px,
    }


# ------------------------------------------------------------------------------------------------------ sonuç
def outcome(entry: float, b15: list[dict], start_ms: int, end_ms: int) -> dict | None:
    win = [b for b in b15 if start_ms <= b["t"] < end_ms]
    if len(win) < 90:
        return None
    hi = max(b["h"] for b in win)
    lo = min(b["l"] for b in win)
    out = {"mfe": (hi / entry - 1) * 100, "mae": (lo / entry - 1) * 100, "ret24": (win[-1]["c"] / entry - 1) * 100}
    hi_i = max(range(len(win)), key=lambda k: (win[k]["h"], -k))
    out["mfe_min"] = (hi_i + 1) * 15
    # iz süren 3/1,5 + stop %10
    stop = entry * (1 - STOP_PCT / 100)
    peak = entry
    exit_px = None
    for b in win:
        if b["l"] <= stop:
            exit_px = stop
            break
        peak = max(peak, b["h"])
        if peak >= entry * 1.03:
            stop = max(stop, peak * (1 - 0.015))
    if exit_px is None:
        exit_px = win[-1]["c"]
    out["trail_net"] = STAKE * (1 - FEE) / entry * exit_px * (1 - FEE) - STAKE
    # sabit +3 + stop %10
    stop = entry * (1 - STOP_PCT / 100)
    exit_px = None
    for b in win:
        if b["l"] <= stop:
            exit_px = stop
            break
        if b["h"] >= entry * 1.03:
            exit_px = entry * 1.03
            break
    if exit_px is None:
        exit_px = win[-1]["c"]
    out["fix3_net"] = STAKE * (1 - FEE) / entry * exit_px * (1 - FEE) - STAKE
    return out


# ------------------------------------------------------------------------------------------------------ analiz
NUM_FEATS = ["rsi1", "rsi4", "stoch1", "adx4", "di_diff", "atr1p", "atr4p", "bb_pos", "bb_width", "vwap_rel", "obv", "vol_ratio",
             "chg24", "chg4", "dist_hi24", "dist_lo24", "dist_hi7", "dist_s20_4", "dist_s99_4", "body4", "rs24", "breadth", "btc_chg24", "above4",
             "d_dist_sma50", "d_dist_sma200", "d_rsi", "d_adx", "d_dist_hi30", "d_dist_hi90", "d_chg7", "d_range20"]
BOOL_FEATS = ["ema_up", "macd1_pos", "macd1_up", "macd4_pos", "macd4_up", "hh", "hl", "btc_up", "d_above50", "d_above200", "d_macd_up", "btc_d_up"]
FEAT_TR = {"rsi1": "RSI14 1h", "rsi4": "RSI14 4h", "stoch1": "StochRSI 1h", "adx4": "ADX14 4h", "di_diff": "+DI − −DI (4h)",
           "atr1p": "ATR 1h %", "atr4p": "ATR 4h %", "bb_pos": "Bollinger konumu (0–1)", "bb_width": "Bollinger genişliği %",
           "vwap_rel": "VWAP'a uzaklık %", "obv": "OBV eğimi", "vol_ratio": "Hacim 12 sa / 7 gün ort.", "chg24": "24 sa değişim %",
           "chg4": "4 sa değişim %", "dist_hi24": "24 sa tepeye uzaklık %", "dist_lo24": "24 sa dipten yükseklik %", "dist_hi7": "7 gün tepeye uzaklık %",
           "dist_s20_4": "4h SMA20'ye uzaklık %", "dist_s99_4": "4h SMA99'a uzaklık %", "body4": "Son 4h mum gövdesi %", "rs24": "BTC'ye göreli güç 24 sa (puan)",
           "breadth": "Genişlik (puan ≥ +1 payı)", "btc_chg24": "BTC 24 sa değişim %", "above4": "4h MA üstü sayısı (0–4)",
           "ema_up": "1h EMA20 > EMA50 ve fiyat üstte", "macd1_pos": "MACD 1h histogram > 0", "macd1_up": "MACD 1h histogram artıyor",
           "macd4_pos": "MACD 4h histogram > 0", "macd4_up": "MACD 4h histogram artıyor", "hh": "4h yüksek tepe", "hl": "4h yüksek dip",
           "btc_up": "BTC 4h kapanış > SMA20",
           "d_dist_sma50": "Günlük SMA50'ye uzaklık %", "d_dist_sma200": "Günlük SMA200'e uzaklık %", "d_rsi": "Günlük RSI14", "d_adx": "Günlük ADX14",
           "d_dist_hi30": "30 gün tepeye uzaklık %", "d_dist_hi90": "90 gün tepeye uzaklık %", "d_chg7": "7 gün değişim %", "d_range20": "20 gün aralık (tepe/dip) %",
           "d_above50": "Günlük SMA50 üstü", "d_above200": "Günlük SMA200 üstü", "d_macd_up": "Günlük MACD histogram artıyor", "btc_d_up": "BTC günlük kapanış > SMA50"}


def tercile_stats(rows: list[dict], feat: str) -> list[dict]:
    vals = [r for r in rows if r.get(feat) is not None and not (isinstance(r[feat], float) and math.isnan(r[feat]))]
    if len(vals) < 30:
        return []
    vals.sort(key=lambda r: r[feat])
    n = len(vals)
    out = []
    for name, part in (("alt", vals[: n // 3]), ("orta", vals[n // 3: 2 * n // 3]), ("üst", vals[2 * n // 3:])):
        if not part:
            continue
        out.append({"dilim": name, "n": len(part), "aralık": (part[0][feat], part[-1][feat]),
                    "kazanma": sum(1 for r in part if r["trail_net"] > 0) / len(part),
                    "net": st.mean(r["trail_net"] for r in part), "mfe": st.mean(r["mfe"] for r in part), "mae": st.mean(r["mae"] for r in part)})
    return out


def bool_stats(rows: list[dict], feat: str) -> list[dict]:
    out = []
    for val in (True, False):
        part = [r for r in rows if bool(r.get(feat)) == val]
        if len(part) < 15:
            continue
        out.append({"dilim": "evet" if val else "hayır", "n": len(part), "aralık": None,
                    "kazanma": sum(1 for r in part if r["trail_net"] > 0) / len(part),
                    "net": st.mean(r["trail_net"] for r in part), "mfe": st.mean(r["mfe"] for r in part), "mae": st.mean(r["mae"] for r in part)})
    return out


def g(r, k, default=-1e9):
    v = r.get(k)
    return default if v is None else v


def _m2(r) -> bool:
    return (g(r, "adx4") >= 25 and g(r, "di_diff") >= 10 and bool(r.get("macd4_up")) and g(r, "vol_ratio") >= 1.5
            and g(r, "rsi1", 100) < 72 and not (r.get("above4") == 4 and bool(r.get("hl"))))


# Yeni kural adayları — veriye bakmadan önce tanımlandı (betik içinde sabit).
RULES = {
    "A. Mevcut (puan ≥ 3)": lambda r: r["score"] >= 3,
    "B. Mevcut + ADX ≥ 25 ve DI farkı ≥ 10": lambda r: r["score"] >= 3 and g(r, "adx4") >= 25 and g(r, "di_diff") >= 10,
    "C. Mevcut + hacim ≥ 1,5× ve RSI1h < 72": lambda r: r["score"] >= 3 and g(r, "vol_ratio") >= 1.5 and g(r, "rsi1", 100) < 72,
    "D. Mevcut + Bollinger ≤ 0,9 (aşırı uzamamış)": lambda r: r["score"] >= 3 and g(r, "bb_pos", 1) <= 0.9,
    "E. Mevcut + 4h MACD hist artıyor ve SMA20 üstü": lambda r: r["score"] >= 3 and r.get("macd4_up") and g(r, "dist_s20_4") > 0,
    "F. Göreli güç: RS24 > 0, 24 sa > 0, ADX ≥ 20, hacim ≥ 1,3×": lambda r: g(r, "rs24") > 0 and g(r, "chg24") > 0 and g(r, "adx4") >= 20 and g(r, "vol_ratio") >= 1.3,
    "G. Kırılım: 24 sa tepeye ≤ 0,5%, hacim ≥ 2×, RSI1h < 75": lambda r: g(r, "dist_hi24") >= -0.5 and g(r, "vol_ratio") >= 2 and g(r, "rsi1", 100) < 75,
    "H. Geri çekilme: trend up, SMA20'ye ±2%, MACD4 artıyor, RSI1h 45–65": lambda r: r["trend4"] == "up" and -2 <= g(r, "dist_s20_4") <= 2 and r.get("macd4_up") and 45 <= g(r, "rsi1") <= 65,
    "I. Mevcut + BTC 4h > SMA20": lambda r: r["score"] >= 3 and r.get("btc_up"),
    "J. Mevcut + (BTC up VEYA RS24 > 3 puan)": lambda r: r["score"] >= 3 and (r.get("btc_up") or g(r, "rs24") > 3),
    "K. B + C birlikte": lambda r: r["score"] >= 3 and g(r, "adx4") >= 25 and g(r, "di_diff") >= 10 and g(r, "vol_ratio") >= 1.5 and g(r, "rsi1", 100) < 72,
    "L. K + (BTC up VEYA RS24 > 3)": lambda r: r["score"] >= 3 and g(r, "adx4") >= 25 and g(r, "di_diff") >= 10 and g(r, "vol_ratio") >= 1.5 and g(r, "rsi1", 100) < 72 and (r.get("btc_up") or g(r, "rs24") > 3),
    # 2026-10-22 02:20 — 90 günlük çalışmadan türetilen yeni mantık (puan şartı yok):
    #   kapı: ADX4h ≥ 25, +DI−−DI ≥ 10, 4h MACD histogramı artıyor · onay: hacim ≥ 1,5×, RSI1h < 72 · eleme: 4/4 MA üstü + 4h yüksek dip (olgun hareket)
    "M2. Yeni: kapı + onay + olgun eleme": lambda r: g(r, "adx4") >= 25 and g(r, "di_diff") >= 10 and bool(r.get("macd4_up")) and g(r, "vol_ratio") >= 1.5
    and g(r, "rsi1", 100) < 72 and not (r.get("above4") == 4 and bool(r.get("hl"))),
    "N1. Yeni (M2) + günlük SMA50 üstü": lambda r: _m2(r) and bool(r.get("d_above50")),
    "N2. Yeni (M2) + günlük SMA50 altı (karşıt)": lambda r: _m2(r) and r.get("d_above50") is False,
    "N3. Yeni (M2) + 90 gün tepeye uzak (≤ −15%)": lambda r: _m2(r) and g(r, "d_dist_hi90", 0) <= -15,
    "N4. Yeni (M2) + günlük MACD artıyor": lambda r: _m2(r) and bool(r.get("d_macd_up")),
    "N5. Yeni (M2) + BTC günlük SMA50 üstü": lambda r: _m2(r) and bool(r.get("btc_d_up")),
    "N6. Yeni (M2) + günlük RSI < 60": lambda r: _m2(r) and g(r, "d_rsi", 100) < 60,
    "M3. Yeni + puan ≥ 3": lambda r: g(r, "adx4") >= 25 and g(r, "di_diff") >= 10 and bool(r.get("macd4_up")) and g(r, "vol_ratio") >= 1.5
    and g(r, "rsi1", 100) < 72 and not (r.get("above4") == 4 and bool(r.get("hl"))) and r["score"] >= 3,
}


def rule_eval(rows: list[dict], split_ms: int) -> list[dict]:
    out = []
    for name, fn in RULES.items():
        sel = [r for r in rows if fn(r)]
        tr = [r for r in sel if r["t"] < split_ms]
        te = [r for r in sel if r["t"] >= split_ms]
        btc_dn = [r for r in sel if not r.get("btc_up")]

        def agg(part):
            if not part:
                return {"n": 0}
            return {"n": len(part), "win": sum(1 for r in part if r["trail_net"] > 0) / len(part),
                    "net": st.mean(r["trail_net"] for r in part), "fix3": st.mean(r["fix3_net"] for r in part),
                    "mfe": st.mean(r["mfe"] for r in part), "mae": st.mean(r["mae"] for r in part), "ret": st.mean(r["ret24"] for r in part)}
        out.append({"rule": name, "all": agg(sel), "train": agg(tr), "test": agg(te), "btc_down": agg(btc_dn),
                    "per_day": len(sel) / max(1, len({r["t"] for r in rows}) / 6)})
    return out


# ------------------------------------------------------------------------------------------------------ ana akış
async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step-hours", type=int, default=4)
    ap.add_argument("--source", choices=("rest", "db"), default="rest", help="db: yerel historical_candles (15m), evren kesit anındaki 24 sa hacim ≥ 5M")
    ap.add_argument("--min-qv", type=float, default=5e6)
    args = ap.parse_args()
    now_ms = int(time.time() * 1000)
    sem = asyncio.Semaphore(4)
    data: dict = {}
    t0 = time.time()
    if args.source == "db":
        from app import database
        from app.binance_tr_public import trading_symbols
        syms = sorted(await trading_symbols("TRY"))
        if "BTCTRY" not in syms:
            syms.append("BTCTRY")
        last = await database._run_db(lambda conn: conn.execute("SELECT MAX(open_time) AS mx FROM historical_candles WHERE timeframe='15m'").fetchone()["mx"])
        now_ms = int(last) + M15            # arşivin son mumu "şimdi"
        start_ms = now_ms - (args.days + 30) * 86_400_000
        for i, sym in enumerate(syms, 1):
            d = await load_db(sym, start_ms, now_ms)
            if d:
                data[sym] = d
            if i % 50 == 0 or i == len(syms):
                print(f"  DB: {i}/{len(syms)} ({time.time() - t0:.0f} sn)", file=sys.stderr)
        print(f"veri {len(data)} sembol (DB), arşiv sonu {dt.datetime.fromtimestamp(now_ms / 1000, TZ):%d.%m %H:%M}", file=sys.stderr)
    else:
        uni = await scan_mod.universe()
        syms = [u["symbol"] for u in uni]
        if "BTCTRY" not in syms:
            syms.append("BTCTRY")

    async def fetch(sym):
        try:
            async with sem:
                d = await T.fetch_all(sym, now_ms)
                for _ in range(2):   # 15m geçmişi ~ 28 güne uzat
                    if not d["15m"]:
                        break
                    older = T.bars(await klines(sym, "15m", limit=1000, end_time_ms=d["15m"][0]["t"] - 1), M15, now_ms)
                    seen = {b["t"] for b in d["15m"]}
                    older = [b for b in older if b["t"] not in seen]
                    if not older:
                        break
                    d["15m"] = older + d["15m"]
                if d["1h"]:
                    older = T.bars(await klines(sym, "1h", limit=500, end_time_ms=d["1h"][0]["t"] - 1), T.TF_MS["1h"], now_ms)
                    seen = {b["t"] for b in d["1h"]}
                    d["1h"] = [b for b in older if b["t"] not in seen] + d["1h"]
                data[sym] = d
        except Exception as exc:  # noqa: BLE001
            print(f"  {sym}: veri yok ({type(exc).__name__})", file=sys.stderr)
    if args.source == "rest":
        await asyncio.gather(*(fetch(s) for s in syms))
        print(f"veri {len(data)} sembol, {time.time() - t0:.0f} sn", file=sys.stderr)

    # kesitler: (now − days) → (now − 24 sa), step saat, tam saatte
    first = (now_ms - args.days * 86_400_000) // 3_600_000 * 3_600_000
    cutoffs = list(range(first, now_ms - 24 * 3_600_000, args.step_hours * 3_600_000))
    btc = data.get("BTCTRY")
    rows: list[dict] = []
    t0 = time.time()
    for ci, cms in enumerate(cutoffs, 1):
        # BTC rejimi
        bpit = cut(btc, cms) if btc else None
        btc_up = btc_chg = btc_d_up = None
        if bpit and len(bpit.get("1d") or []) >= 60:
            cdb = [b["c"] for b in bpit["1d"]]
            s50b = T.last(T.sma(cdb, 50))
            btc_d_up = bool(s50b and cdb[-1] > s50b)
        if bpit and len(bpit["4h"]) >= 25 and len(bpit["15m"]) > 97:
            c4 = [b["c"] for b in bpit["4h"]]
            s20 = T.last(T.sma(c4, 20))
            btc_up = bool(s20 and c4[-1] > s20)
            btc_chg = (bpit["15m"][-1]["c"] / bpit["15m"][-97]["c"] - 1) * 100
        feats_at = {}
        for sym, d in data.items():
            if sym == "BTCTRY":
                continue
            pit = cut(d, cms)
            f = features(sym, pit)
            if f is None or (args.source == "db" and f["qv24"] < args.min_qv):
                continue
            feats_at[sym] = f
        if not feats_at:
            continue
        breadth = sum(1 for f in feats_at.values() if f["score"] >= 1) / len(feats_at)
        for sym, f in feats_at.items():
            o = outcome(f["px"], data[sym]["15m"], cms, cms + 24 * 3_600_000)
            if o is None:
                continue
            rows.append({"sym": sym, "t": cms, **f, "btc_up": btc_up, "btc_chg24": btc_chg, "btc_d_up": btc_d_up,
                         "rs24": (f["chg24"] - btc_chg) if (f["chg24"] is not None and btc_chg is not None) else None,
                         "breadth": breadth, **o})
        if ci % 10 == 0 or ci == len(cutoffs):
            print(f"  kesit {ci}/{len(cutoffs)} ({dt.datetime.fromtimestamp(cms / 1000, TZ):%d.%m %H:%M}) satır {len(rows)} ({time.time() - t0:.0f} sn)", file=sys.stderr)

    split_ms = cutoffs[len(cutoffs) // 2]
    base = [r for r in rows if r["score"] >= 3]
    winners = [r for r in base if r["trail_net"] > 0]
    losers = [r for r in base if r["trail_net"] <= 0]
    btc_down_rows = [r for r in rows if r.get("btc_up") is False]
    base_btc_down = [r for r in base if r.get("btc_up") is False]
    univ_stats = {"n": len(rows), "win": sum(1 for r in rows if r["trail_net"] > 0) / len(rows), "net": st.mean(r["trail_net"] for r in rows)}

    feat_table = []
    for feat in NUM_FEATS + BOOL_FEATS:
        stats = bool_stats(base, feat) if feat in BOOL_FEATS else tercile_stats(base, feat)
        if len(stats) >= 2:
            spread = stats[-1]["net"] - stats[0]["net"] if feat in NUM_FEATS else stats[0]["net"] - stats[1]["net"]
            feat_table.append((feat, stats, spread))
    feat_table.sort(key=lambda x: -abs(x[2]))
    feat_table_dn = []
    for feat in NUM_FEATS + BOOL_FEATS:
        stats = bool_stats(base_btc_down, feat) if feat in BOOL_FEATS else tercile_stats(base_btc_down, feat)
        if len(stats) >= 2:
            spread = stats[-1]["net"] - stats[0]["net"] if feat in NUM_FEATS else stats[0]["net"] - stats[1]["net"]
            feat_table_dn.append((feat, stats, spread))
    feat_table_dn.sort(key=lambda x: -abs(x[2]))
    rules = rule_eval(rows, split_ms)

    def mean_f(part, k):
        v = [r[k] for r in part if r.get(k) is not None]
        return st.mean(v) if v else None

    wl = [(feat, mean_f(winners, feat), mean_f(losers, feat)) for feat in NUM_FEATS]

    # ---------------------------------------------------------------------------------------------- HTML
    gen = dt.datetime.now(TZ)
    css = """body{margin:0;padding:18px;background:#0f1131;color:#e8eaf6;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
    h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:26px 0 8px;color:#c7cbea}h3{font-size:14px;margin:18px 0 6px;color:#8f95bf}
    p.sub{color:#8f95bf;font-size:12px;max-width:1100px}.wrap{overflow-x:auto;border:1px solid #2a2e5c;border-radius:10px;background:#171a3f;margin-bottom:10px}
    table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:5px 9px;border-bottom:1px solid #2a2e5c;text-align:right;white-space:nowrap}
    th{color:#8f95bf;font-size:12px;position:sticky;top:0;background:#171a3f}td:first-child,th:first-child{text-align:left}
    .pos{color:#22c55e}.neg{color:#ef4444}.flat{color:#8f95bf}.b{font-weight:700}
    .kpi{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 12px}.kpi div{background:#171a3f;border:1px solid #2a2e5c;border-radius:8px;padding:8px 12px;min-width:150px}
    .kpi b{display:block;font-size:17px}.kpi span{color:#8f95bf;font-size:12px}"""

    def c(x):
        return "pos" if x is not None and x > 0 else "neg" if x is not None and x < 0 else "flat"

    def fp(x, d=2):
        return "—" if x is None else f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")

    def fpc(x):
        return "—" if x is None else f"{x * 100:.0f}%"

    def ftl(x):
        return "—" if x is None else (f"{x:+,.0f} TL").replace(",", ".")

    H = [f"<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Sinyal Yeniden Kurma</title><style>{css}</style></head><body>",
         f"<h1>Sinyal mantığını yeniden kurma — kazanan/kaybeden analizi ({gen:%d.%m.%Y %H:%M})</h1>",
         f"<p class='sub'>Kaynak: {'yerel arşiv (historical_candles 15m; evren kesit anında 24 sa hacim ≥ ' + f'{args.min_qv / 1e6:g}' + 'M TL)' if args.source == 'db' else 'Binance TR REST (evren bugünkü likit çiftler)'}. "
         f"{len(cutoffs)} kesit (son {args.days} gün, her {args.step_hours} saat, {dt.datetime.fromtimestamp(cutoffs[0] / 1000, TZ):%d.%m %H:%M} → "
         f"{dt.datetime.fromtimestamp(cutoffs[-1] / 1000, TZ):%d.%m %H:%M}) × {len(data) - 1} sembol = {len(rows)} gözlem. Her gözlemde kesitten önceki mumlarla özellikler, sonraki 24 saatte sonuç "
         f"(15m mumlar). 'Net' = iz süren 3/1,5 + %10 stop ile 10.000 TL'den komisyon sonrası; 'kazanma' = net > 0. Eğitim/test ayrımı kesitlerin ortası "
         f"({dt.datetime.fromtimestamp(split_ms / 1000, TZ):%d.%m %H:%M}). Kural adayları veriye bakılmadan önce yazıldı (betik içinde sabit). Yatırım tavsiyesi değildir.</p>"]
    H.append("<div class='kpi'>"
             f"<div><b>{len(base)}</b><span>mevcut sinyal (puan ≥ +3)</span></div>"
             f"<div><b>{fpc(len(winners) / len(base)) if base else '—'}</b><span>kazanma oranı</span></div>"
             f"<div><b class='{c(st.mean(r['trail_net'] for r in base) if base else None)}'>{ftl(st.mean(r['trail_net'] for r in base) if base else None)}</b><span>sinyal başı net</span></div>"
             f"<div><b>{fpc(univ_stats['win'])}</b><span>tüm evrende kazanma (taban)</span></div>"
             f"<div><b class='{c(univ_stats['net'])}'>{ftl(univ_stats['net'])}</b><span>tüm evrende sinyal başı net</span></div>"
             f"<div><b>{fpc(len(base_btc_down) / len(base)) if base else '—'}</b><span>sinyallerin BTC düşük rejimde payı</span></div>"
             f"<div><b>{fpc(sum(1 for r in rows if r.get('d_dist_sma50') is not None) / len(rows)) if rows else '—'}</b><span>günlük bağlamı olan gözlem</span></div>"
             "</div>")
    # kazanan vs kaybeden ortalamaları
    H += ["<h2>1. Kazanan ve kaybeden sinyallerde özellik ortalamaları (mevcut kural)</h2>",
          "<div class='wrap'><table><tr><th>Özellik</th><th>Kazananlar</th><th>Kaybedenler</th><th>Fark</th></tr>"]
    for feat, w, l in sorted(wl, key=lambda x: -abs((x[1] or 0) - (x[2] or 0)) / (abs(x[2]) + 1e-9) if x[1] is not None and x[2] is not None else 0):
        if w is None or l is None:
            continue
        H.append(f"<tr><td>{FEAT_TR.get(feat, feat)}</td><td>{fp(w)}</td><td>{fp(l)}</td><td class='{c(w - l)}'>{fp(w - l)}</td></tr>")
    H.append("</table></div>")
    # dilim tabloları
    for title, table in (("2. Hangi özellik ayırıyor — mevcut sinyallerde üç dilim (alt / orta / üst)", feat_table),
                         ("3. Aynı analiz, yalnız BTC 4h kapanış < SMA20 kesitlerinde (BTC düşerken)", feat_table_dn)):
        H += [f"<h2>{title}</h2>", "<p class='sub'>Fark = üst dilimin sinyal başı neti − alt dilimin neti (boolean'da evet − hayır). Mutlak farka göre sıralı; büyük fark = karar için güçlü unsur.</p>",
              "<div class='wrap'><table><tr><th>Özellik</th><th>Dilim</th><th>Aralık</th><th>n</th><th>Kazanma</th><th>Sinyal başı net</th><th>Ort. MFE</th><th>Ort. MAE</th><th>Fark (üst − alt)</th></tr>"]
        for feat, stats, spread in table[:22]:
            for i, s_ in enumerate(stats):
                rng = "—" if s_["aralık"] is None else f"{fp(s_['aralık'][0])} … {fp(s_['aralık'][1])}"
                H.append(f"<tr><td class='b'>{FEAT_TR.get(feat, feat) if i == 0 else ''}</td><td>{s_['dilim']}</td><td>{rng}</td><td>{s_['n']}</td><td>{fpc(s_['kazanma'])}</td>"
                         f"<td class='{c(s_['net'])}'>{ftl(s_['net'])}</td><td>{fp(s_['mfe'])}%</td><td class='neg'>{fp(s_['mae'])}%</td><td class='{c(spread) if i == 0 else ''}'>{ftl(spread) if i == 0 else ''}</td></tr>")
        H.append("</table></div>")
    # kurallar
    H += ["<h2>4. Kural adayları — eğitim (ilk yarı) / test (ikinci yarı) / BTC düşük rejim</h2>",
          "<p class='sub'>Her kural için sinyal sayısı, kazanma oranı ve sinyal başı net (iz süren 3/1,5 + %10 stop); 'sabit +3' aynı sinyallerde +%3 hedefle. "
          "'BTC düşük' sütunu yalnız BTC 4h < SMA20 kesitlerindeki sinyaller: BTC düşerken de çalışan kural orada artıda kalır. 'Gün başı' ≈ kuralın günde kaç sinyal verdiği.</p>",
          "<div class='wrap'><table><tr><th>Kural</th><th>n</th><th>Gün başı</th><th>Kazanma</th><th>Net / sinyal</th><th>Sabit +3 / sinyal</th><th>Ort. MFE</th><th>Ort. MAE</th>"
          "<th>Eğitim n</th><th>Eğitim net</th><th>Test n</th><th>Test net</th><th>BTC düşük n</th><th>BTC düşük net</th><th>BTC düşük kazanma</th></tr>"]
    for r in sorted(rules, key=lambda x: -(x["all"].get("net") or -1e9) if x["all"]["n"] >= 20 else 1e9):
        a, tr, te, dn = r["all"], r["train"], r["test"], r["btc_down"]
        H.append(f"<tr><td class='b'>{r['rule']}</td><td>{a['n']}</td><td>{r['per_day']:.1f}</td><td>{fpc(a.get('win'))}</td><td class='{c(a.get('net'))} b'>{ftl(a.get('net'))}</td>"
                 f"<td class='{c(a.get('fix3'))}'>{ftl(a.get('fix3'))}</td><td>{fp(a.get('mfe'))}%</td><td class='neg'>{fp(a.get('mae'))}%</td>"
                 f"<td>{tr['n']}</td><td class='{c(tr.get('net'))}'>{ftl(tr.get('net'))}</td><td>{te['n']}</td><td class='{c(te.get('net'))}'>{ftl(te.get('net'))}</td>"
                 f"<td>{dn['n']}</td><td class='{c(dn.get('net'))}'>{ftl(dn.get('net'))}</td><td>{fpc(dn.get('win'))}</td></tr>".replace("%", "%"))
    H.append("</table></div>")
    H += ["<h2>Okuma</h2><ul>",
          "<li>Bölüm 1–2 'mevcut kural neyi yanlış yapıyor' sorusuna cevap: kaybedenlerde yüksek olan özellik bir yanıltıcı, kazananlarda yüksek olan bir destekleyicidir.</li>",
          "<li>Bölüm 3, BTC düşerken yükselen sembolleri ayıran unsurlar içindir (göreli güç, hacim, trend gücü gibi).</li>",
          "<li>Bölüm 4'te bir kuralın hem eğitim hem test hem BTC-düşük sütununda artı olması gerekir; yalnız 'tümü' artıysa seçim gürültüsü olabilir. 14 gün kısa bir pencere; 90 günlük replay ile teyit edilmeli.</li></ul></body></html>"]
    path = os.path.join(DOCS_DIR, f"SINYAL_YENIDEN_KURMA_{args.days}gun_{args.source}_{gen:%Y-%m-%d_%H%M}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(H))
    with open(os.path.join(WORK_DIR, f"ta_feature_study_{gen:%Y-%m-%d_%H%M}.json"), "w", encoding="utf-8") as fh:
        json.dump({"cutoffs": cutoffs, "split_ms": split_ms, "rows": rows, "rules": rules, "feat_table": [(f, s_, sp) for f, s_, sp in feat_table],
                   "feat_table_btc_down": [(f, s_, sp) for f, s_, sp in feat_table_dn], "winners_vs_losers": wl}, fh, ensure_ascii=False, default=str)
    # stderr özet
    print(f"mevcut sinyal n={len(base)} kazanma={len(winners) / len(base) if base else 0:.0%} net/sinyal={st.mean(r['trail_net'] for r in base) if base else 0:+.0f} | evren kazanma={univ_stats['win']:.0%} net={univ_stats['net']:+.0f}", file=sys.stderr)
    for r in sorted(rules, key=lambda x: -(x["all"].get("net") or -1e9) if x["all"]["n"] >= 20 else 1e9):
        a, tr, te, dn = r["all"], r["train"], r["test"], r["btc_down"]
        print(f"  {r['rule'][:58]:58} n={a['n']:4} kaz={fpc(a.get('win')):>4} net={ftl(a.get('net')):>9} | eğit n={tr['n']:3} {ftl(tr.get('net')):>9} | test n={te['n']:3} {ftl(te.get('net')):>9} | BTCdüşük n={dn['n']:3} {ftl(dn.get('net')):>9} {fpc(dn.get('win'))}", file=sys.stderr)
    print("özellikler (mevcut sinyal, üst−alt dilim net farkı):", file=sys.stderr)
    for feat, stats, spread in feat_table[:14]:
        print(f"  {FEAT_TR.get(feat, feat):34} {ftl(spread):>9}  " + "  ".join(f"{s_['dilim']}:{fpc(s_['kazanma'])}/{ftl(s_['net'])}" for s_ in stats), file=sys.stderr)
    print("BTC düşük rejimde:", file=sys.stderr)
    for feat, stats, spread in feat_table_dn[:10]:
        print(f"  {FEAT_TR.get(feat, feat):34} {ftl(spread):>9}  " + "  ".join(f"{s_['dilim']}:{fpc(s_['kazanma'])}/{ftl(s_['net'])}" for s_ in stats), file=sys.stderr)
    print(f"Rapor: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
