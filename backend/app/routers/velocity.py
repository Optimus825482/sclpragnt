"""Velocity (fast-riser) candidate detection, tracking and autonomous paper entries."""
import asyncio
import json
import math
import time
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _fresh_public_price
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols, orderbook
from app.technical_analysis import calculate_snapshot, _atr, _bollinger, _cci, _ema, _mfi, _sma
from app.market_intelligence import microstructure_snapshot
from app.microflow import microflow
from app import calibration as calibration_service
from app.binance_tr_public import top_gainers, ticker_24h
from app.embedding_worker import worker as embedding_worker
from app.memory_service import build_document
from app.ws_runtime import ws_manager
from app.api_common import _llm_guard_block_reason

logger = logging.getLogger("scalper.velocity")
router = APIRouter()


VELOCITY_MIN_ATR_PCT = 0.30        # 1m ATR% ≥ 0.30 → yüksek salınım rejimi (her iki mod)
VELOCITY_MIN_BB_WIDTH_PCT = 2.5    # Bollinger(20,2) genişliği ≥ %2.5 (d=+0.73, en güçlü)
VELOCITY_TREND_RSI_MIN = 60.0      # trend-içi mod: RSI ≥ 60 (momentum devam)
VELOCITY_REVERSAL_RSI_MAX = 35.0   # V-dönüşü mod: RSI ≤ 35 (aşırı satımdan sıçrama)
VELOCITY_STRUCT_SLOPE_PCT = 0.20   # LinReg(20) eğimi ≥ %0.2/10bar VEYA Aroon ≥ +50
# Aşırı uç elme: MFI/RSI tükenmişlikte +%2 olasılığı bazın altına düşüyor
# (14.475 gözlem: MFI≥95 → %0.71, RSI≥80 → %0.65, sağlıklı bant %1.56-2.48).
# Zaten fırlamış sembol "gidecek yeri yok" — geri çekilme riski en yüksek.
VELOCITY_MFI_UPPER = 90.0          # MFI ≥ 90 → ele (M1, 14 periyot)
VELOCITY_MFI_LOWER = 10.0          # MFI ≤ 10 → ele (aşırı satım da aynı risk)
VELOCITY_RSI_UPPER = 80.0          # RSI ≥ 80 → ele (trend-devam modunun üst sınırı)
VELOCITY_BASE_RATE_PCT = 1.97
VELOCITY_CALIBRATED_HIT_PCT = 19.3


def _velocity_rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0: gains += d
        else: losses -= d
    return 100 - 100 / (1 + gains / losses) if losses else 100.0


def _velocity_mfi(highs, lows, closes, vols, n=14):
    if len(closes) < n + 1:
        return None
    pos = neg = 0.0
    for i in range(len(closes) - n, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        ptp = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        flow = tp * vols[i]
        if tp > ptp: pos += flow
        elif tp < ptp: neg += flow
    return 100 - 100 / (1 + pos / neg) if neg else 100.0


def _velocity_bollinger_width(closes, n=20, mult=2.0):
    if len(closes) < n:
        return None
    m = sum(closes[-n:]) / n
    sd = (sum((c - m) ** 2 for c in closes[-n:]) / n) ** 0.5
    return (4 * sd) / m * 100 if m else None


def _velocity_linreg_slope(closes, n=20):
    if len(closes) < n:
        return None
    xs = list(range(n))
    ys = closes[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0
    return slope / my * 100 * 10 if my else None


def _velocity_aroon(highs, lows=None, n=25):
    if len(highs) < n + 1:
        return None
    win = highs[-(n + 1):]
    up = (n - (len(win) - 1 - win.index(max(win)))) / n * 100
    down = None
    if lows is not None and len(lows) >= n + 1:
        lwin = lows[-(n + 1):]
        down = (n - (len(lwin) - 1 - lwin.index(min(lwin)))) / n * 100
    return {"up": up, "down": down}


VELOCITY_PROFILES = {
    # horizon_minutes: {target_pct, ölçüm penceresi, journal profile etiketi}
    5: {"target_pct": 2.0, "label": "5dk-%2"},
    15: {"target_pct": 3.0, "label": "15dk-%3"},
}


async def detect_velocity_candidates(args: dict | None = None, *, horizon_minutes: int = 5):
    """Belirli ufukta (5dk/15dk) en az hedef % (2/3) yükselme potansiyeli taşıyan en hızlı 3 aday.

    v2 — forensics kalibrasyonu: Bollinger genişliği + ATR + (RSI iki ucu) +
    yapısal teyit (LinReg/Aroon) + aşırı uç elme (MFI/RSI). Her aday
    'trend_devam' veya 'v_donusu' moduyla etiketlenir.
    Yalnızca kapanmış 1m mumlar; tahmin/garanti değildir, paper-only.
    """
    profile = VELOCITY_PROFILES.get(horizon_minutes) or VELOCITY_PROFILES[5]
    target_pct = float(profile["target_pct"])
    now_ms = int(time.time() * 1000)
    try:
        gainer_rows = await top_gainers(config.VELOCITY_POOL_SIZE)
    except Exception as exc:
        logger.warning("velocity scan: top_gainers hatası: %s", exc)
        gainer_rows = []
    pool = [item["symbol"] for item in gainer_rows]
    if not pool:
        pool = [str(s).replace("_", "").upper() for s in config.SYMBOLS][:20]
    sem = asyncio.Semaphore(6)

    async def scan_one(symbol: str) -> dict | None:
        async with sem:
            try:
                rows = await fetch_klines(symbol, "1m", 60)
            except Exception:
                return None
            if len(rows) < 30:
                return None
            # Ölü/borsa dışı semboller 24h ticker'da eski kapanış verisiyle
            # listelenmeye devam edebiliyor; güncel mum şart.
            last_age_sec = (now_ms - (int(rows[-1][0]) + 59_999)) / 1000
            if last_age_sec > 180:
                return None
            closes = [float(r[4]) for r in rows]
            highs = [float(r[2]) for r in rows]
            lows = [float(r[3]) for r in rows]
            vols = [float(r[5]) for r in rows]
            i = len(rows) - 1
            price = closes[-1]
            if price <= 0:
                return None
            trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
                   for j in range(max(1, i - 14), i + 1)]
            atr_pct = (sum(trs) / len(trs)) / price * 100 if trs else 0.0
            bb_width = _velocity_bollinger_width(closes)
            rsi = _velocity_rsi(closes)
            mfi = _velocity_mfi(highs, lows, closes, vols)
            slope = _velocity_linreg_slope(closes)
            aroon = _velocity_aroon(highs, lows)
            aroon_up = aroon["up"] if aroon else None
            aroon_down = aroon["down"] if aroon else None
            ret3 = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 else 0.0
            # Mod tespiti: RSI iki ucundan biri
            if rsi is None:
                return None
            mode = "trend_devam" if rsi >= VELOCITY_TREND_RSI_MIN else \
                   "v_donusu" if rsi <= VELOCITY_REVERSAL_RSI_MAX else None
            struct_ok = (slope is not None and slope >= VELOCITY_STRUCT_SLOPE_PCT) or \
                        (aroon_up is not None and aroon_up >= 50)
            # Aşırı uç elme: zaten fırlamış/tükenmiş semboller geri çekilme
            # riski taşır; +%2 olasılığı bazın altına düşüyor (forensics 14.475 gözlem).
            exhausted = None
            if mfi is not None and mfi >= VELOCITY_MFI_UPPER:
                exhausted = f"mfi_asiri_alim:{mfi:.0f}"
            elif mfi is not None and mfi <= VELOCITY_MFI_LOWER:
                exhausted = f"mfi_asiri_satim:{mfi:.0f}"
            elif rsi >= VELOCITY_RSI_UPPER:
                exhausted = f"rsi_asiri_alim:{rsi:.0f}"
            # Profil bazlı ATR eşiği: kalibrasyon 5dk/15dk için ayrı kaydeder;
            # yoksa global varsayılan kullanılır.
            prof_key = "5m" if horizon_minutes == 5 else "15m"
            prof_atr = _velocity_profile_atr.get(prof_key) or VELOCITY_MIN_ATR_PCT
            passes = (exhausted is None and
                      atr_pct >= prof_atr and
                      bb_width is not None and bb_width >= VELOCITY_MIN_BB_WIDTH_PCT and
                      mode is not None and
                      (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)))
            # velocity skoru: bileşen oranlarının geometrik ortalaması benzeri çarpım
            bb_ratio = (bb_width / VELOCITY_MIN_BB_WIDTH_PCT) if bb_width else 0.0
            struct_ratio = max(0.0, (slope or 0) / VELOCITY_STRUCT_SLOPE_PCT,
                               (aroon_up or 0) / 50.0)
            velocity_score = round((atr_pct / prof_atr) *
                                    bb_ratio *
                                    max(0.2, min(3.0, struct_ratio)) *
                                    (1.0 + max(0.0, ret3) / 2.0), 2)
            # ---- M5 momentum+volatilite deseni (7g replay: %66.8 başarı) ----
            # g0: en son kapanan M5 mumu; g1: ondan önceki; g2: iki önceki aralık.
            # Eşikler config.VELOCITY_PATTERN_* (24s/72s/7g doğrulandı).
            m5_pattern = None
            m5_pattern_ok = None
            try:
                m5_rows = await fetch_klines(symbol, "5m", 40)  # ~3.3 saat warmup
                if len(m5_rows) >= 35:
                    m5_closes = [float(r[4]) for r in m5_rows]
                    m5_highs = [float(r[2]) for r in m5_rows]
                    m5_lows = [float(r[3]) for r in m5_rows]
                    m5_vols = [float(r[5]) for r in m5_rows]
                    k = len(m5_rows) - 1  # son kapanmiş M5
                    def _m5_groups():
                        # g1: k-1'e kadar tam seri; g2: son 2 çıkar; g0: k dahil tam seri
                        g1 = m5_rows[:k]
                        g2 = m5_rows[:k - 2] if k > 3 else m5_rows[:k]
                        g0 = m5_rows  # son kapanan dahil
                        return g0, g1, g2
                    def _grp_vals(grp):
                        cls = [float(r[4]) for r in grp]
                        hs = [float(r[2]) for r in grp]
                        ls = [float(r[3]) for r in grp]
                        vs = [float(r[5]) for r in grp]
                        atr_v = None
                        if len(cls) >= 15:
                            trs = [max(hs[j] - ls[j], abs(hs[j] - cls[j - 1]), abs(ls[j] - cls[j - 1]))
                                   for j in range(len(cls) - 14, len(cls))]
                            atr_v = sum(trs) / len(trs)
                        atr_pct = (atr_v / cls[-1] * 100) if atr_v and cls[-1] else None
                        chg5 = (cls[-1] / cls[-6] - 1) * 100 if len(cls) >= 6 else None
                        chg3 = (cls[-1] / cls[-4] - 1) * 100 if len(cls) >= 4 else None
                        roc10 = (cls[-1] / cls[-11] - 1) * 100 if len(cls) >= 11 else None
                        return {"atr_pct": atr_pct, "chg5": chg5, "chg3": chg3, "roc": roc10}
                    g0, g1, g2 = _m5_groups()
                    v0, v1, v2 = _grp_vals(g0), _grp_vals(g1), _grp_vals(g2)
                    conds = {
                        "g0_chg5": v0["chg5"] is not None and v0["chg5"] >= config.VELOCITY_PATTERN_G0_CHG5,
                        "g0_chg3": v0["chg3"] is not None and v0["chg3"] >= config.VELOCITY_PATTERN_G0_CHG3,
                        "g0_roc": v0["roc"] is not None and v0["roc"] >= config.VELOCITY_PATTERN_G0_ROC,
                        "g0_atr": v0["atr_pct"] is not None and v0["atr_pct"] >= config.VELOCITY_PATTERN_G0_ATR,
                        "g1_atr": v1["atr_pct"] is not None and v1["atr_pct"] >= config.VELOCITY_PATTERN_G1_ATR,
                        "g2_atr": v2["atr_pct"] is not None and v2["atr_pct"] >= config.VELOCITY_PATTERN_G2_ATR,
                    }
                    m5_pattern = {k: bool(v) for k, v in conds.items()}
                    m5_pattern_ok = all(conds.values())
            except Exception as exc:
                logger.warning("velocity m5 pattern hesabı: %s", exc)
            # ---- M1/M3 öncü ATR deseni (araştırma: v2×M1/M3 kesişimi dokunuşu 2.5× artırıyor) ----
            # M1 öncü ATR: son kapanmış 1m'den ÖNCEKİ barın ATR%'si; M3 öncü: 3 dk öncesi.
            # Yüksekse (M1>1.0 VE M3>1.0) aday "kesişim deseni" taşır — skorlamada önceliklendirilir.
            try:
                m1_atr_prev = m3_atr_prev = None
                if len(closes) >= 16:
                    def _atr_pct_at(idx):
                        if idx < 15:
                            return None
                        trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]),
                                   abs(lows[j] - closes[j - 1]))
                               for j in range(idx - 14, idx + 1)]
                        return (sum(trs) / len(trs)) / closes[idx] * 100 if trs else None
                    m1_atr_prev = _atr_pct_at(i - 1)
                    m3_atr_prev = _atr_pct_at(i - 3)
                leading_ok = bool(m1_atr_prev is not None and m3_atr_prev is not None
                                  and m1_atr_prev > 1.0 and m3_atr_prev > 1.0)
                # Kesişim deseni dokunuşu ~2.5× artırıyor (araştırma run 14); skor
                # çarpanı aday sıralamasında önceliklendirir.
                if leading_ok:
                    velocity_score = round(velocity_score * 1.5, 2)
            except Exception as exc:
                logger.warning("velocity m1/m3 leading hesabı: %s", exc)
                m1_atr_prev = m3_atr_prev = None
                leading_ok = False
            return {"symbol": symbol, "price": price, "atr_pct": round(atr_pct, 3),
                    "bb_width_pct": round(bb_width, 2) if bb_width else None,
                    "rsi": round(rsi, 1) if rsi else None, "mfi": round(mfi, 1) if mfi else None,
                    "mode": mode, "exhausted": exhausted,
                    "linreg_slope10_pct": round(slope, 3) if slope is not None else None,
                    "aroon_up": round(aroon_up, 0) if aroon_up is not None else None,
                    "aroon_down": round(aroon_down, 0) if aroon_down is not None else None,
                    "horizon_minutes": horizon_minutes,
                    "ret3_pct": round(ret3, 3),
                    "velocity_score": velocity_score, "passes": passes,
                    "m5_pattern": m5_pattern, "m5_pattern_ok": m5_pattern_ok,
                    "m1_atr_prev": round(m1_atr_prev, 3) if m1_atr_prev is not None else None,
                    "m3_atr_prev": round(m3_atr_prev, 3) if m3_atr_prev is not None else None,
                    "leading_ok": leading_ok,
                    "base_hit_pct": VELOCITY_BASE_RATE_PCT,
                    "calibrated_hit_pct": VELOCITY_CALIBRATED_HIT_PCT if passes else None,
                    "last_closed_at": rows[-1][0]}

    results = await asyncio.gather(*(scan_one(s) for s in pool))
    limit = max(1, min(int((args or {}).get("limit", 3)), 10))
    candidates = [r for r in results if r and r["passes"]]
    candidates.sort(key=lambda r: r["velocity_score"], reverse=True)
    for rank, candidate in enumerate(candidates[:limit], 1):
        candidate["rank"] = rank
    watchlist = [r for r in results if r and not r["passes"] and r["velocity_score"] >= 0.8]
    watchlist.sort(key=lambda r: r["velocity_score"], reverse=True)
    # Journal: geçenler + izleme listesi kaydedilir; ufuk süresi dolunca
    # kapanmış M1 mumlarla gerçek dokunuş ölçülüp eşikler kalibre edilir.
    candidate_id_prefix = f"vel-{profile['label']}-{int(now_ms)}"
    # Adaylar için tekil WS mikro yapı akışını başlat; 1s/5s bar ve agresif
    # akış, aday izleme sırasında LLM/panelin gerçek zamanlı görüntü almasını
    # sağlar. En fazla 3 aday, sembol sayısı sınırlı olduğu için bağlantı
    # maliyeti düşüktür. Başarısızlık taramayı düşürmez.
    try:
        for cand in candidates[:limit]:
            await microflow.start(cand["symbol"])
    except Exception as exc:
        logger.warning("velocity microflow aday başlatma: %s", exc)
    try:
        journal_rows = [{
            "candidate_id": f"{candidate_id_prefix}-{r['symbol']}",
            "created_at": now_ms / 1000, "symbol": r["symbol"], "price": r["price"],
            "target_pct": target_pct, "atr_pct": r["atr_pct"], "volume_ratio": 0.0,
            "ret3_pct": r["ret3_pct"], "velocity_score": r["velocity_score"],
            "passes": r["passes"], "rank": r.get("rank"),
            "m5_pattern": r.get("m5_pattern"), "m5_pattern_ok": r.get("m5_pattern_ok"),
            "leading_ok": r.get("leading_ok"),
        } for r in (candidates[:limit] + watchlist[:5])]
        # Adaylar için mikro yapı (whale dağıtım sinyali, CVD) journal'a eklenir;
        # filtreler kapalıyken dahi ileride canlı istatistik üretmek için kaydedilir.
        for row in journal_rows:
            try:
                micro = microflow.get_snapshot(price=row["price"])
                flow = (micro.get("trade_flow") or {})
                activity = (flow.get("whale_activity") or {})
                row["microstructure"] = {
                    "whale_verdict": activity.get("verdict"),
                    "whale_count": activity.get("whale_count"),
                    "cvd_try": flow.get("cvd_try"),
                    "trade_rate_per_min": flow.get("trade_rate_per_min"),
                }
            except Exception:
                pass
        await database.save_velocity_candidates(journal_rows)
    except Exception as exc:
        logger.warning("velocity journal hatası: %s", exc)
    live_stats = await database.get_velocity_calibration_stats()
    live_hit_pct = (float(live_stats.get("passing_touched_count") or 0) /
                    float(live_stats.get("passing_count") or 0) * 100) if live_stats.get("passing_count") else None
    return {"generated_at": now_ms / 1000, "target": f"min %{target_pct:g} move in {horizon_minutes} minutes",
            "horizon_minutes": horizon_minutes, "target_pct": target_pct,
            "pool_source": "binance_tr_top_gaining_tab", "symbols_scanned": len(pool),
            "version": "v2-forensics-2026-08-29",
            "filter": {"min_atr_pct": VELOCITY_MIN_ATR_PCT,
                        "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                        "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                        "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                        "mfi_upper": VELOCITY_MFI_UPPER, "mfi_lower": VELOCITY_MFI_LOWER,
                        "rsi_upper": VELOCITY_RSI_UPPER,
                        "struct_slope_pct": VELOCITY_STRUCT_SLOPE_PCT},
            "calibration": {"base_rate_pct": VELOCITY_BASE_RATE_PCT,
                             "conditional_hit_pct": VELOCITY_CALIBRATED_HIT_PCT,
                             "live_hit_pct": live_hit_pct,
                             "live_evaluated": int(live_stats.get("evaluated_count") or 0),
                             "live_passing_touched": int(live_stats.get("passing_touched_count") or 0),
                             "live_passing_count": int(live_stats.get("passing_count") or 0),
                             "note": "v2: hacim şartı kaldırıldı; BB genişliği + RSI/MFI uç elmesi + LinReg/Aroon teyidi. live_hit_pct canlı journal'dan gelir."},
            "candidates": candidates[:limit], "watchlist": watchlist[:5],
            "leading_summary": {
                "scanned": len(results),
                "leading_ok_count": sum(1 for r in results if r and r.get("leading_ok")),
                "note": "M1/M3 öncü ATR kesişimi (M1>1.0 VE M3>1.0) dokunuşu ~2.5x artırır; skorda 1.5x öncelik.",
            },
            "data_policy": "kapanmış 1m mumlar; tahmin/garanti değil, paper-only"}


_velocity_learning_state = {"last_run_at": None, "measured": 0, "last_error": None,
                             "last_calibrated_at": None, "active_filters": None}

# Kalibrasyon parametreleri — profil bazlı.
# 5dk-%2 ve 15dk-%3 farklı hedefler; ayrı ATR eşiği + ayrı hedef bant.
# Hedef bant backtest/forensics'ten: tüm-sembol 5dk-%2 ~%11-15, canlı (top-gainer
# + rank seçimi) ~%20-28. Bant histerezisli: eşik, isabet hedefin dışına
# çıkınca ±0.05 kayar; bant içinde kalırsa dokunulmaz (salınım önlenir).
VELOCITY_PROFILE_CALIB = {
    "5m": {"target_low": 0.12, "target_high": 0.30, "step": 0.05,
           "min_atr": 0.10, "max_atr": 1.00, "min_samples": 30},
    "15m": {"target_low": 0.15, "target_high": 0.38, "step": 0.05,
            "min_atr": 0.10, "max_atr": 1.00, "min_samples": 30},
}
_velocity_profile_atr = {"5m": None, "15m": None}  # lazy-loaded per-profile thresholds


def _profile_prefix(profile):
    return {"5m": "vel-5dk-%", "15m": "vel-15dk-%"}.get(profile)


async def velocity_calibrate():
    """Profil bazlı ATR eşiği kalibrasyonu; her döngüde değerlendirilir.

    Döndürür: (değişiklik_yapıldı_mı, durum_sözlüğü). Eşikler
    ``llm_settings``'e kalıcı yazılır (restart'ta geri yüklenir).
    """
    global VELOCITY_MIN_ATR_PCT
    changed = False
    by_profile = {}
    hit_rates = []
    for profile, cal in VELOCITY_PROFILE_CALIB.items():
        stats = await database.get_velocity_calibration_stats(profile=profile)
        passing = int(stats.get("passing_count") or 0)
        touched = int(stats.get("passing_touched_count") or 0)
        hit = (touched / passing) if passing else None
        by_profile[profile] = {"passing_count": passing, "passing_touched": touched,
                               "hit_pct": round(hit * 100, 1) if hit is not None else None}
        if passing < cal["min_samples"] or hit is None:
            continue
        hit_rates.append(hit)
        # Profil eşiği: global VELOCITY_MIN_ATR_PCT'e çarpan olarak sakla.
        # (Modül global'i tek kalır; profil çarpanı ayrı kaydedilir.)
        key = f"velocity_min_atr_pct_{profile}"
        saved = await database.get_llm_setting(key, None)
        if saved:
            _velocity_profile_atr[profile] = round(float(saved), 2)
        else:
            _velocity_profile_atr[profile] = VELOCITY_MIN_ATR_PCT
        cur = _velocity_profile_atr[profile]
        if hit < cal["target_low"] and cur < cal["max_atr"]:
            new_v = round(min(cal["max_atr"], cur + cal["step"]), 2)
            _velocity_profile_atr[profile] = new_v
            await database.set_llm_setting(key, str(new_v))
            changed = True
            logger.info("velocity: %s isabet %s%% hedef altı (%s%%) → ATR %s→%s",
                        profile, round(hit * 100, 1), round(cal["target_low"] * 100),
                        cur, new_v)
        elif hit > cal["target_high"] and cur > cal["min_atr"]:
            new_v = round(max(cal["min_atr"], cur - cal["step"]), 2)
            _velocity_profile_atr[profile] = new_v
            await database.set_llm_setting(key, str(new_v))
            changed = True
            logger.info("velocity: %s isabet %s%% hedef üstü (%s%%) → ATR %s→%s",
                        profile, round(hit * 100, 1), round(cal["target_high"] * 100),
                        cur, new_v)
        by_profile[profile]["atr_threshold"] = _velocity_profile_atr[profile]
    if hit_rates:
        # Genel (global) eşik: profil ortalaması; UI'ın tek göstergesi için.
        mean_hit = sum(hit_rates) / len(hit_rates)
        by_profile["_meta"] = {"mean_hit_pct": round(mean_hit * 100, 1)}
    if changed:
        _velocity_learning_state["last_calibrated_at"] = time.time()
    return changed, by_profile


async def velocity_learning_loop():
    """Ufku dolan hız adaylarını (5dk-%2 ve 15dk-%3) kapanmış M1 mumlarıyla
    ölç; eşikleri canlı dokunuş oranına göre ayarla; LLM'e postmortem bağlamı
    kaydet."""
    await asyncio.sleep(120)
    global VELOCITY_MIN_ATR_PCT
    # Kalibre edilmiş eşikleri kalıcı depodan geri yükle; aksi halde her restart
    # öğrenilen değeri fabrika ayarına (0.30) sıfırlıyordu. Hem global hem
    # profil bazlı (5m/15m) eşikler ayrı ayrı yüklenir.
    try:
        saved = await database.get_llm_setting("velocity_min_atr_pct", None)
        if saved:
            VELOCITY_MIN_ATR_PCT = round(float(saved), 2)
        for profile in ("5m", "15m"):
            key = f"velocity_min_atr_pct_{profile}"
            val = await database.get_llm_setting(key, None)
            if val:
                _velocity_profile_atr[profile] = round(float(val), 2)
        _velocity_learning_state["active_filters"] = {
            "min_atr_pct": VELOCITY_MIN_ATR_PCT,
            "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
        }
    except Exception as exc:
        logger.warning("velocity eşikleri geri yüklenemedi: %s", exc)
    while True:
        try:
            pending = await database.get_pending_velocity_candidates(limit=200)
            measured = 0
            for candidate in pending:
                symbol = candidate["symbol"]
                created_ms = int(float(candidate["created_at"]) * 1000)
                horizon = 15 if "15dk-%3" in str(candidate.get("candidate_id", "")) else 5
                due_ms = created_ms + horizon * 60_000
                try:
                    rows = await fetch_klines(symbol, "1m", horizon + 12, created_ms, due_ms + 65_000)
                except Exception:
                    continue
                # Tarama anı bir M1 mumun ortasına denk gelebilir; o mum atak
                # öncesi sayılır ve pencereye tam ufuk kadar mum sığmayabilir.
                # Pencere süresi dolduysa ufuk × %60 mum yeterli — aksi halde
                # kayıt sonsuza dek 'pending' kalıyordu.
                window = [r for r in rows if int(r[0]) + 59_999 > created_ms and int(r[0]) + 59_999 <= due_ms]
                if time.time() * 1000 < due_ms or len(window) < horizon * 3 // 5:
                    continue
                highs = [float(r[2]) for r in window]
                entry = float(candidate["price"])
                if entry <= 0:
                    continue
                mfe_pct = (max(highs) / entry - 1) * 100
                touched = mfe_pct >= float(candidate["target_pct"])
                ok = await database.mark_velocity_candidate_evaluated(
                    candidate["candidate_id"], mfe_pct=round(mfe_pct, 4),
                    touched_target=touched,
                    details={"window_bars": len(window), "entry": entry, "target_pct": candidate["target_pct"]})
                if ok:
                    measured += 1
                    # LLM hafıza katmanına kanıt olarak yaz (postmortem döngüsü okur)
                    await embedding_worker.enqueue_persistent(build_document(
                        layer="symbol", scope=f"velocity-outcome:{symbol}", symbol=symbol,
                        source_type="velocity_candidate_outcome", source_id=str(candidate["candidate_id"]),
                        content=json.dumps({
                            "candidate": {k: candidate.get(k) for k in ("atr_pct", "volume_ratio", "ret3_pct", "velocity_score", "passes")},
                            "outcome": {"mfe_pct": round(mfe_pct, 3), "touched_target": touched},
                        }, ensure_ascii=False, default=str),
                        metadata={"source_type": "velocity_candidate_outcome",
                                  "touched_target": touched, "passes": candidate.get("passes")},
                        observed_at=time.time()))
            if measured:
                _velocity_learning_state["measured"] = _velocity_learning_state.get("measured", 0) + measured
            # Kalibrasyon her döngüde değerlendirilir (yeni ölçüm olmasa bile
            # mevcut istatistikler zamanla değişebilir). Profil bazlıdır.
            try:
                cal_changed, by_profile = await velocity_calibrate()
            except Exception as exc:
                logger.warning("velocity kalibrasyon hatası: %s", exc)
                by_profile = {}
                cal_changed = False
            _velocity_learning_state["active_filters"] = {
                "min_atr_pct": VELOCITY_MIN_ATR_PCT,
                "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
                "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                "by_profile": by_profile,
            }
            # Ölü/sessiz sembollerde mum hiç gelmediği için sonsuza dek pending
            # kalan kayıtları temizle — istatistikleri şişirmesini önler.
            expired = await database.cleanup_stale_velocity_candidates()
            if expired:
                logger.info("velocity: %s ölü pending kayıt expired işaretlendi", expired)
            _velocity_learning_state.update({"last_run_at": time.time(), "last_error": None})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _velocity_learning_state.update({"last_run_at": time.time(), "last_error": str(exc)})
            logger.exception("velocity learning loop: %s", exc)
        await asyncio.sleep(60)


@router.get("/api/market-snapshot/velocity-5m")
async def market_snapshot_velocity_5m(limit: int = 3):
    return await detect_velocity_candidates({"limit": limit}, horizon_minutes=5)


@router.get("/api/market-snapshot/velocity-15m")
async def market_snapshot_velocity_15m(limit: int = 3):
    """15 dakikada +%3 hedefli hız avcısı; aynı v2 filtre seti, ayrı journal profili."""
    return await detect_velocity_candidates({"limit": limit}, horizon_minutes=15)


@router.get("/api/reports/velocity")
async def get_velocity_report(limit: int = 60):
    """Hız avcısı journal'ı: koşullu dokunuş başarısı + öğrenme durumu."""
    stats = await database.get_velocity_calibration_stats()
    stats_5m = await database.get_velocity_calibration_stats(profile="5m")
    stats_15m = await database.get_velocity_calibration_stats(profile="15m")
    pattern_hit_rates = await database.get_velocity_pattern_hit_rates()
    recent = await database.get_velocity_candidates(limit=limit)
    evaluated = int(stats.get("evaluated_count") or 0)
    touched = int(stats.get("touched_count") or 0)
    passing = int(stats.get("passing_count") or 0)
    passing_touched = int(stats.get("passing_touched_count") or 0)

    def _profile_stats(raw):
        p = int(raw.get("passing_count") or 0)
        pt = int(raw.get("passing_touched_count") or 0)
        return {"passing_count": p, "passing_touched": pt,
                "passing_hit_rate": pt / p if p else None,
                "evaluated": int(raw.get("evaluated_count") or 0)}
    # Sembol bazında başarı
    symbol_rows = [row for row in recent if row.get("status") == "evaluated"]
    by_symbol: dict[str, dict] = {}
    for row in symbol_rows:
        bucket = by_symbol.setdefault(row["symbol"], {"evaluated": 0, "touched": 0, "sum_mfe": 0.0})
        bucket["evaluated"] += 1
        bucket["touched"] += 1 if row.get("touched_target") else 0
        bucket["sum_mfe"] += float(row.get("mfe_pct") or 0)
    symbols = [{"symbol": symbol, "evaluated": bucket["evaluated"],
                "touched": bucket["touched"],
                "touch_rate": bucket["touched"] / bucket["evaluated"] if bucket["evaluated"] else None,
                "average_mfe_pct": bucket["sum_mfe"] / bucket["evaluated"] if bucket["evaluated"] else None}
               for symbol, bucket in sorted(by_symbol.items(), key=lambda kv: -kv[1]["evaluated"])]
    return {"paper_only": True,
            "stats": {"total": int(stats.get("total") or 0), "pending": int(stats.get("pending_count") or 0),
                       "evaluated": evaluated, "touched": touched,
                       "touch_rate": touched / evaluated if evaluated else None,
                       "average_mfe_pct": stats.get("average_mfe_pct"),
                       "passing_count": passing, "passing_touched": passing_touched,
                       "passing_hit_rate": passing_touched / passing if passing else None,
                       "passing_average_mfe_pct": stats.get("passing_mfe_pct")},
            "stats_by_profile": {"5m": _profile_stats(stats_5m), "15m": _profile_stats(stats_15m)},
            "pattern_hit_rates": pattern_hit_rates,
            "filters": {"min_atr_pct": VELOCITY_MIN_ATR_PCT,
                         "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
                         "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                         "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                         "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                         "struct_slope_pct": VELOCITY_STRUCT_SLOPE_PCT},
            "learning_state": dict(_velocity_learning_state),
            "auto_trade": {"enabled": bool(config.VELOCITY_AUTO_ENABLED and (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"),
                            "interval_sec": config.VELOCITY_AUTO_INTERVAL_SEC,
                            "balance_pct": config.VELOCITY_AUTO_BALANCE_PCT,
                            "sl_pct": config.VELOCITY_AUTO_SL_PCT,
                            "trail_trigger_pct": config.VELOCITY_TRAIL_TRIGGER_PCT,
                            "state": {k: v for k, v in _velocity_auto_state.items() if k != "opened"},
                            "microstructure_filters": {
                                "whale_distribution_enabled": bool(config.VELOCITY_WHALE_DISTRIBUTION_FILTER),
                                "flow_confirmation_enabled": bool(config.VELOCITY_FLOW_CONFIRMATION_FILTER),
                                "skip_counts": dict(_velocity_auto_state["filters"]),
                                "note": "Filtreler varsayılan kapalı; istatistik toplanırken giriş kalitesi değişmez. Canlı istatistik sonrası açılabilir.",
                            },
                            "recent_opens": list(_velocity_auto_state["opened"][-5:])},
            "symbols": symbols[:20], "recent": recent}



@router.delete("/api/reports/velocity/{candidate_id}")
async def delete_velocity_candidate(candidate_id: str):
    """Journal temizliği: geçersiz/ölü sembol kaydını raporlardan kaldırır."""
    deleted = await database.delete_velocity_candidates([candidate_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    return {"ok": True, "deleted": deleted, "paper_only": True}


@router.post("/api/reports/velocity/{candidate_id}/remeasure")
async def remeasure_velocity_candidate(candidate_id: str):
    """Journal satırını kapanmış M1 mumlarla yeniden ölçer.

    Eski/yanlış ölçülmüş kayıtlar için: pencere (created → created+5dk)
    yeniden hesaplanır, MFE ve dokunuş journal'a tekrar yazılır.
    """
    rows = await database.get_velocity_candidates(limit=200)
    candidate = next((r for r in rows if r["candidate_id"] == candidate_id), None)
    if not candidate:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    symbol = candidate["symbol"]
    horizon = 15 if "15dk-%3" in str(candidate.get("candidate_id", "")) else 5
    created_ms = int(float(candidate["created_at"]) * 1000)
    due_ms = created_ms + horizon * 60_000
    try:
        rows1m = await fetch_klines(symbol, "1m", horizon + 12, created_ms, due_ms + 65_000)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mum verisi alınamadı: {exc}")
    window = [r for r in rows1m if int(r[0]) + 59_999 > created_ms and int(r[0]) + 59_999 <= due_ms]
    if len(window) < 3:
        raise HTTPException(status_code=409, detail=f"pencere mumları yetersiz: {len(window)}")
    entry = float(candidate["price"])
    highs = [float(r[2]) for r in window]
    mfe_pct = (max(highs) / entry - 1) * 100 if entry > 0 else 0.0
    touched = mfe_pct >= float(candidate["target_pct"])
    touch_bar = next((r for r in window if float(r[2]) == max(highs)), None)
    touch_sec = int((int(touch_bar[0]) + 59_999 - created_ms) / 1000) if touched and touch_bar else None
    await database.mark_velocity_candidate_evaluated(
        candidate_id, mfe_pct=round(mfe_pct, 4), touched_target=touched,
        details={"remeasured": True, "window_bars": len(window),
                  "window_first": datetime.fromtimestamp(int(window[0][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
                  "window_last": datetime.fromtimestamp(int(window[-1][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
                  "entry": entry, "target_pct": candidate["target_pct"], "touch_sec": touch_sec},
        force=True)
    return {"ok": True, "paper_only": True, "mfe_pct": round(mfe_pct, 3),
            "touched_target": touched, "window_bars": len(window),
            "window_first": datetime.fromtimestamp(int(window[0][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
            "window_last": datetime.fromtimestamp(int(window[-1][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
            "touch_sec": touch_sec}


@router.post("/api/reports/velocity/remeasure-all")
async def remeasure_all_velocity():
    """Journal'daki tüm ölçülmüş kayıtları yeniden ölçer (sunucu saati/veri
    tutarsızlıklarını topluca gidermek için)."""
    rows = await database.get_velocity_candidates(limit=300)
    remeasured, failed = 0, []
    for candidate in rows:
        if candidate["status"] != "evaluated":
            continue
        try:
            await remeasure_velocity_candidate(candidate["candidate_id"])
            remeasured += 1
        except HTTPException as exc:
            failed.append({"candidate_id": candidate["candidate_id"], "detail": exc.detail})
    return {"ok": True, "paper_only": True, "remeasured": remeasured, "failed": failed[:10]}


@router.get("/api/velocity/status")
async def velocity_status():
    """Hız Avcısı otonom tarama durumu: son tarama zamanı, M5 kapanış zamanı,
    aday havuzu boyutu, desen filtresi durumu."""
    return {
        "ok": True,
        "auto_enabled": bool(config.VELOCITY_AUTO_ENABLED and
                             (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"),
        "pool_size": config.VELOCITY_POOL_SIZE,
        "pattern_filter_enabled": config.VELOCITY_PATTERN_FILTER_ENABLED,
        "sl_pct": config.VELOCITY_AUTO_SL_PCT,
        "reentry_hard_stop_block_sec": config.VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC,
        "reentry_cooldown_bars": config.VELOCITY_REENTRY_COOLDOWN_BARS,
        "min_atr_capacity_ratio": config.VELOCITY_MIN_ATR_CAPACITY_RATIO,
        "last_scan_at": _velocity_auto_state.get("last_scan_at"),
        "last_m5_close_ms": _velocity_auto_state.get("last_m5_close_ms"),
        "total_opened": _velocity_auto_state.get("total_opened", 0),
        "last_error": _velocity_auto_state.get("last_error"),
        "last_open": _velocity_auto_state.get("last_open"),
        "recent_opens": list(_velocity_auto_state.get("opened", [])[-5:]),
        "server_time": time.time(),
    }


@router.post("/api/velocity/manual-scan")
async def manual_velocity_scan():
    """Manuel hız avcısı taraması: 5dk-%2 + 15dk-%3 profillerini tarar,
    en yüksek skorlu adaya (GEÇTİ veya İZLEME) paper pozisyon açar.

    Otonom döngüyle aynı kapılardan geçer; buton bunu anında tetikler.
    """
    scan5 = await detect_velocity_candidates({}, horizon_minutes=5)
    scan15 = await detect_velocity_candidates({}, horizon_minutes=15)
    pool = (list(scan5.get("candidates") or []) + list(scan5.get("watchlist") or [])
            + list(scan15.get("candidates") or []) + list(scan15.get("watchlist") or []))
    pool.sort(key=lambda c: -float(c.get("velocity_score") or 0))
    if not pool:
        return {"ok": True, "paper_only": True, "opened": False,
                "message": "Şu an koşulları geçen aday yok; yüksek salınım rejimi bekleniyor.",
                "scan5": {"candidates": scan5.get("candidates", []), "watchlist": scan5.get("watchlist", [])},
                "scan15": {"candidates": scan15.get("candidates", []), "watchlist": scan15.get("watchlist", [])}}
    best = pool[0]
    outcome = await _open_velocity_position(best)
    _velocity_auto_state["last_open"] = outcome
    if outcome.get("status") == "PAPER_OPENED":
        _velocity_auto_state["total_opened"] += 1
        _velocity_auto_state["opened"].append({**outcome, "at": time.time(),
                                                "score": best.get("velocity_score"),
                                                "horizon": best.get("horizon_minutes"),
                                                "manual": True})
        del _velocity_auto_state["opened"][:-20]
    return {"ok": True, "paper_only": True,
            "opened": outcome.get("status") == "PAPER_OPENED",
            "best_candidate": best, "outcome": outcome,
            "scan5": {"candidates": scan5.get("candidates", []), "watchlist": scan5.get("watchlist", [])},
            "scan15": {"candidates": scan15.get("candidates", []), "watchlist": scan15.get("watchlist", [])}}


@router.get("/api/reports/velocity/live")
async def get_velocity_live_tracking():
    """Canlı izleme: son taramaların adaylarını güncel fiyatla takip eder.

    Her aday için: analiz anındaki giriş fiyatı, güncel fiyat, +%2'ye ulaşıp
    ulaşılmadığı, ulaşıldıysa kaç saniyede ulaşıldığı. 5 dakikalık pencere
    kapanınca durum kesinleşir; öğrenme döngüsü nihai sonucu journal'a yazar.
    """
    import datetime as _dt
    tz_tr = _dt.timezone(_dt.timedelta(hours=3))  # GMT+3 sabit
    now_ms = int(time.time() * 1000)
    rows = await database.get_velocity_candidates(limit=25)
    # Canlı takip: penceresi hâlâ açık olanlar + kapanmış ama journal'a henüz
    # yazılmamışlar. Süresi dolup değerlendirilenler rapordan düşer (Son
    # Adaylar sekmesinde kalıcı olarak yaşar).
    rows = [r for r in rows
            if now_ms / 1000 - float(r["created_at"]) <= 300
            or r["status"] == "pending"]
    sem = asyncio.Semaphore(6)
    tracked = []

    async def track(row):
        symbol = row["symbol"]
        entry = float(row["price"])
        created_ms = int(float(row["created_at"]) * 1000)
        due_ms = created_ms + 5 * 60_000
        # Kapanmış M1 mumlardan pencere içi tepe + dokunuş anı (5 sn çözünürlük için mum üstü)
        best_high, touch_sec = None, None
        try:
            window_rows = await fetch_klines(symbol, "1m", 12, created_ms, due_ms + 65_000)
            window = [r for r in window_rows if int(r[0]) + 59_999 > created_ms and int(r[0]) + 59_999 <= due_ms]
            if entry > 0:
                touched_high = max((float(r[2]) for r in window if float(r[2]) / entry >= 1.02), default=None)
                best_high = max((float(r[2]) for r in window), default=None)
                if touched_high is not None:
                    touch_bar = next(r for r in window if float(r[2]) == touched_high)
                    touch_sec = max(0, int((int(touch_bar[0]) + 59_999 - created_ms) / 1000))
        except Exception:
            window = []
        # güncel fiyat: pencere içindeyse en son kapanmış mum, pencere bittiyse son fiyat
        try:
            fresh = await fetch_klines(symbol, "1m", 2)
            current_price = float(fresh[-1][4]) if fresh else None
        except Exception:
            current_price = None
        elapsed_sec = int((now_ms - created_ms) / 1000)
        window_closed = now_ms >= due_ms
        touched = touch_sec is not None
        if row["status"] == "evaluated":
            journal_touched = bool(row.get("touched_target"))
            journal_mfe = row.get("mfe_pct")
        else:
            journal_touched = None  # henüz öğrenme döngüsü yazmadı
            journal_mfe = None
        # Pencere içi en iyi hareket: kapanmış mumlardan (canlı) ve journal'dan
        # (ölçülmüşse) ikisinin büyüğü.
        live_mfe = ((best_high / entry - 1) * 100) if (best_high and entry) else None
        mfe_values = [v for v in (live_mfe, journal_mfe) if v is not None]
        effective_mfe = max(mfe_values) if mfe_values else None
        # Üçlü sınıflandırma (pencere kapandığında kesinleşir):
        #   success → +%2 hedefini geçti
        #   ok      → giriş fiyatının üzerine çıktı ama +%2'ye ulaşmadı
        #   failed  → pencere boyunca giriş fiyatının üzerine hiç çıkamadı
        if touched or journal_touched is True:
            outcome = "success"
        elif window_closed and journal_touched is False:
            outcome = "ok" if (effective_mfe is not None and effective_mfe > 0) else "failed"
        else:
            outcome = "pending"
        tracked.append({
            "candidate_id": row["candidate_id"], "symbol": symbol,
            "entry_price": entry, "current_price": current_price,
            "change_pct": round((current_price / entry - 1) * 100, 3) if current_price and entry else None,
            "target_pct": float(row["target_pct"]),
            "passes": bool(row.get("passes")),
            "velocity_score": row.get("velocity_score"),
            "status": row["status"],
            "touched": touched or (journal_touched is True),
            "journal_touched": journal_touched,
            "outcome": outcome,
            "touch_sec": touch_sec,
            "best_mfe_pct": round(effective_mfe, 3) if effective_mfe is not None else None,
            "elapsed_sec": elapsed_sec, "remaining_sec": max(0, int((due_ms - now_ms) / 1000)),
            "window_closed": window_closed,
            "window_time": _dt.datetime.fromtimestamp(created_ms / 1000, tz=tz_tr).strftime("%H:%M:%S"),
        })

    await asyncio.gather(*(track(r) for r in rows))
    rank_order = {"success": 0, "ok": 1, "pending": 2, "failed": 3}
    tracked.sort(key=lambda r: (rank_order.get(r["outcome"], 2), -r["elapsed_sec"]))
    counts = {"success": 0, "ok": 0, "failed": 0, "pending": 0}
    for r in tracked:
        counts[r["outcome"]] += 1
    return {"paper_only": True, "server_time": now_ms / 1000, "counts": counts, "tracking": tracked}


_velocity_auto_state = {"last_scan_at": None, "last_error": None, "opened": [],
                          "last_open": None, "total_opened": 0,
                          "filters": {"whale_dagilim_reddet": 0, "akis_aykiri_reddet": 0,
                                      "microflow_yok": 0}}


async def _velocity_rest_liquidity_ok(symbol: str, order_value: float) -> tuple[bool, str | None]:
    """Hız avcısı için REST tabanlı likidite kapısı.

    Geleneksel preflight, WebSocket orderbook/ticker tazeliğini şart koşar;
    Top-Gainer'dan yeni gelen sembollerin WS akışı dolana kadar 'stale' sayılıp
    her adayı ENTRY_INELIGIBLE yapabiliyordu. Burada yalnız taze REST verisiyle
    gerçek likidite koşullarını kontrol eder: emir defteri derinliği ve 24s
    quoteVolume. Spread koruması otonom ve manuel taramada tamamen kaldırıldı;
    düşük fiyatlı coinlerde geniş spread işlem açılışını engelliyordu. Tarama
    zaten kapanmış 1m mumlar üzerinden geçtiği için fiyat kalitesi bu kapıyı
    geçen adayda güvence altındadır.
    """
    try:
        book = await orderbook(symbol, 5)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return False, "emir_defteri_bos"
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if bid <= 0:
            return False, "gecersiz_fiyat"
        depth_try = (sum(float(q) for _, q in bids[:5]) + sum(float(q) for _, q in asks[:5])) * ((bid + ask) / 2)
        if depth_try < order_value * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER:
            return False, f"derinlik_yetersiz:{depth_try:.0f}TRY"
    except Exception as exc:
        return False, f"orderbook_hata:{type(exc).__name__}"
    try:
        gainers = await top_gainers(50)
        qv = next((float(g["quoteVolume"]) for g in gainers if g["symbol"] == symbol), None)
        if qv is not None and qv < config.MIN_24H_QUOTE_VOLUME_TRY:
            return False, f"24s_hacim_dusuk:{qv:.0f}TRY"
    except Exception:
        pass  # ticker erişilemezse spread+derinlik yeterli güvence
    return True, None


async def _hydrate_market_cache_for(symbol: str):
    """Top-Gainer adayının market önbelleğini REST'ten doldurur.

    market.ticker_24h / market.klines yalnız başlangıç sembol listesi için
    dolar; Top-Gainer'dan gelen yeni sembollerin recheck'i 0 hacim/derinlik
    üzerinden reddediliyordu. Bu fonksiyon tek sembolün 24s ticker'ını,
    1m kline geçmişini ve orderbook akışını önbelleğe işler.
    """
    try:
        rows = await ticker_24h()
        row = next((r for r in rows if str(r.get("symbol", "")).upper() == symbol), None)
        if row:
            qv = float(row.get("quoteVolume", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)
            market.ticker_24h[symbol] = qv
            if last_price > 0:
                now_ms = int(time.time() * 1000)
                market.tickers[symbol] = {**(market.tickers.get(symbol) or {}),
                                            "symbol": symbol, "last_price": last_price,
                                            "timestamp": now_ms, "source": "binance_tr_public_rest"}
    except Exception as exc:
        logger.warning("hydrate ticker %s: %s", symbol, exc)
    try:
        # 1m (ATR kapasite + hız hesapları) ve 5m (MOMENTUM_TIMEFRAME,
        # preflight/recheck) ikisini de doldur; aksi halde recheck 0 bar
        # üzerinden yanlış reddediyor.
        for tf in ("1m", config.MOMENTUM_TIMEFRAME):
            kline_rows = await fetch_klines(symbol, tf, 120)
            if kline_rows:
                market.klines.setdefault(tf, {})[symbol] = {
                    "timestamps": [int(r[0]) for r in kline_rows],
                    "opens": [float(r[1]) for r in kline_rows],
                    "highs": [float(r[2]) for r in kline_rows],
                    "lows": [float(r[3]) for r in kline_rows],
                    "closes": [float(r[4]) for r in kline_rows],
                    "volumes": [float(r[5]) for r in kline_rows],
                }
    except Exception as exc:
        logger.warning("hydrate klines %s: %s", symbol, exc)
    try:
        book = await orderbook(symbol, 5)
        bids, asks = book.get("bids") or [], book.get("asks") or []
        if bids and asks:
            bid_price, bid_qty = float(bids[0][0]), float(bids[0][1])
            ask_price, ask_qty = float(asks[0][0]), float(asks[0][1])
            mid = (bid_price + ask_price) / 2
            market.orderflow[symbol] = {**(market.orderflow.get(symbol) or {}),
                                          "bid_price": bid_price, "ask_price": ask_price,
                                          "bid_qty": bid_qty, "ask_qty": ask_qty,
                                          "spread_pct": ((ask_price - bid_price) / bid_price * 100) if bid_price else None,
                                          "source": "binance_tr_public_rest", "updated_at": time.time()}
    except Exception as exc:
        logger.warning("hydrate orderbook %s: %s", symbol, exc)


async def _symbol_quality(symbol: str, lookback_trades: int = 10) -> float | None:
    """Sembolün son işlemlerindeki ortalama getirisi (sinyal kalite skoru).

    Kapanmış CHAT_PREDICTION işlemlerinden pnl yüzdesini okur; pozitifse
    sembol pump sonrası momentumu koruyor demektir. Yetersiz örneklemde
    None döner (filtre uygulanmaz).
    """
    try:
        trades = await database.get_trades(limit=lookback_trades, strategy="CHAT_PREDICTION", symbol=symbol)
    except Exception:
        return None
    rets = []
    for t in trades or []:
        entry = float(t.get("entry_price") or 0)
        exit_px = float(t.get("exit_price") or 0)
        if entry > 0 and exit_px > 0:
            rets.append((exit_px / entry - 1) * 100)
    if len(rets) < 3:
        return None
    return sum(rets) / len(rets)


async def _open_velocity_position(candidate: dict) -> dict:
    """En iyi hız adayına serbest TL'nin %50'si ile paper pozisyon açar."""
    symbol = str(candidate["symbol"] or "").upper()
    # M5 momentum+volatilite deseni (7g replay: %66.8 başarı). Filtre açıkken
    # desen karşılanmayan adaylar açılmaz — yalnızca journal'da kalır.
    if config.VELOCITY_PATTERN_FILTER_ENABLED:
        if not candidate.get("m5_pattern_ok"):
            return {"symbol": symbol, "status": "SKIPPED",
                    "reason": "m5_pattern_reddet", "m5_pattern": candidate.get("m5_pattern")}
    # Sembol bazlı kalite filtresi (araştırma 2026-08-31): bazı semboller
    # pump sonrası momentumu koruyor, bazıları anında dönüyor. 7 günlük
    # backtest: iyi sembollerde sinyal-sonrası getiri +0.04% vs kötülerde
    # -0.74%. Kapanmış işlemlerden sembolün son N işleminin ort getirisine
    # bakar; negatifse adayı atlar.
    if config.VELOCITY_SYMBOL_QUALITY_FILTER:
        try:
            q = await _symbol_quality(symbol)
            if q is not None and q < 0:
                return {"symbol": symbol, "status": "SKIPPED",
                        "reason": f"sembol_kalite_negatif:{q:.2f}", "symbol_quality": q}
        except Exception as exc:
            logger.warning("velocity sembol kalite filtresi: %s", exc)
    if symbol in analyzer.positions:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "acik_pozisyon_var"}
    chat_max = int(config.CHAT_PREDICTION_MAX_OPEN_POSITIONS)
    if 0 < chat_max <= 9999:
        chat_open = sum(1 for pos in analyzer.positions.values() if pos.get("strategy") == "CHAT_PREDICTION")
        if chat_open >= chat_max:
            return {"symbol": symbol, "status": "SKIPPED", "reason": "pozisyon_limiti_dolu"}
    guard = await database.get_llm_symbol_guard(symbol)
    guard_reason = _llm_guard_block_reason(guard)
    if guard_reason:
        return {"symbol": symbol, "status": "SKIPPED", "reason": guard_reason}
    try:
        latest = await fetch_klines(symbol, "1m", 2)
        price = float(latest[-1][4]) if latest else None
    except Exception:
        price = None
    if not price:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "fiyat_alinamadi"}
    # Açılış öncesi sub-minute mikro yapı akışını başlat: 1s/5s bar, agresif
    # alış/satış akışı ve whale sayısı, pozisyon yönetiminin giriş anını
    # gerçek zamanlı görmesini sağlar. Başarısızlık açılışı engellemez.
    try:
        await microflow.start(symbol)
    except Exception as exc:
        logger.warning("velocity microflow başlatma: %s", exc)
    # Mikro-yapı giriş filtreleri (deterministik, LLM çağrısız): whale dağıtım
    # sinyali ve aykırı agresif satış akışı "sahte kırılım" riskini işaretler.
    # Yalnız gerçek veri varsa uygulanır; veri yoksa kapı açık kalır (fail-open:
    # mikro yapı akışı daha yeni başladığı için ilk turda veri eksik olabilir).
    try:
        micro_snapshot = microflow.get_snapshot(price=price)
        micro_activity = (micro_snapshot.get("trade_flow") or {}).get("whale_activity") or {}
        micro_flow = micro_snapshot.get("trade_flow") or {}
        if config.VELOCITY_WHALE_DISTRIBUTION_FILTER:
            if micro_activity.get("whale_count") and micro_activity.get("verdict") in {"distribution", "mixed"}:
                _velocity_auto_state["filters"]["whale_dagilim_reddet"] += 1
                return {"symbol": symbol, "status": "SKIPPED",
                        "reason": f"whale_dagilim:{micro_activity.get('verdict')}",
                        "whale_activity": {k: micro_activity.get(k) for k in
                                           ("verdict", "accumulation", "distribution", "whale_count")}}
        if config.VELOCITY_FLOW_CONFIRMATION_FILTER:
            cvd = micro_flow.get("cvd_try")
            if cvd is not None and cvd < 0:
                _velocity_auto_state["filters"]["akis_aykiri_reddet"] += 1
                return {"symbol": symbol, "status": "SKIPPED",
                        "reason": f"akis_aykiri:cvd={cvd:.0f}TRY",
                        "cvd_try": cvd}
        if not micro_snapshot.get("data_ready"):
            _velocity_auto_state["filters"]["microflow_yok"] += 1
    except Exception as exc:
        logger.warning("velocity mikro yapı filtresi: %s", exc)
    # Serbest TL'nin %50'si
    balance = await database.get_wallet_balance("TRY")
    order_value = round(balance * config.VELOCITY_AUTO_BALANCE_PCT / 100.0, 2)
    order_value = min(order_value, balance)
    if order_value < config.MIN_PARTIAL_ORDER_TRY:
        return {"symbol": symbol, "status": "SKIPPED", "reason": f"bakiye_yetersiz:{order_value}TRY"}
    # Likidite ön kontrolü: REST tabanlı (WS tazeliği beklemeyen) kapı.
    # Top-Gainer'dan yeni gelen sembollerin WS orderbook akışı dolmadan
    # geleneksel preflight 'stale' diyordu ve hiç işlem açılmıyordu.
    ok, reason = await _velocity_rest_liquidity_ok(symbol, order_value)
    if not ok:
        return {"symbol": symbol, "status": "ENTRY_INELIGIBLE", "reason": reason}
    # open_position içindeki son recheck market önbelleğini kullanır;
    # Top-Gainer adayının önbelleğini REST'ten doldur ki 0 hacim/derinlik
    # üzerinden reddedilmesin.
    await _hydrate_market_cache_for(symbol)
    # Kullanıcı kontratı: sinyal sonrası fiyat önce geri çekiliyor; açılışta sert
    # stop koymak geri çekilmede kapatıp yükselişi kaçırıyor. No-initial-stop
    # modunda stop'suz açılır (kâr koruma merdiveni +%1'de yine devreye girer).
    no_initial_stop = bool(config.VELOCITY_NO_INITIAL_STOP)
    stop_loss_pct = None if no_initial_stop else config.VELOCITY_AUTO_SL_PCT / 100.0
    context = {"signal_name": "Otonom Hız Avcısı · en iyi aday",
                "velocity_score": candidate.get("velocity_score"),
                "mode": candidate.get("mode"), "pattern_matches": candidate.get("m5_pattern"),
                "paper_only": True, "source": "velocity_auto",
                "atr_pct": candidate.get("atr_pct"),
                "velocity_relaxed_reentry": True,
                "no_initial_stop": no_initial_stop}
    result = await analyzer.open_position(symbol, price, "LONG", "CHAT_PREDICTION", order_value,
                                           stop_loss_pct=stop_loss_pct,
                                           entry_context_extra=context)
    if result and str(result.get("action", "")).upper() == "BUY_SIGNAL":
        await ws_manager.broadcast({"type": "signal", "data": result})
        return {"symbol": symbol, "status": "PAPER_OPENED", "order_value_try": order_value,
                 "entry": price,
                 "stop_loss_pct": (stop_loss_pct * 100) if stop_loss_pct is not None else None,
                 "no_initial_stop": no_initial_stop}
    return {"symbol": symbol, "status": "ENTRY_BLOCKED", "reason": str((result or {}).get("reason") or "kapı")}


async def autonomous_velocity_loop():
    """5 dk'da bir hız taraması; en iyi adaya (GEÇTİ veya İZLEME) pozisyon.

    Her turda önce 5dk-%2, sonra 15dk-%3 profili taranır; iki profilin
    adayları birleşik skorla sıralanır ve en iyi tek adaya pozisyon açılır.
    Açılış VELOCITY_AUTO_ENABLED + LLM paper anahtarıyla çift kilitli.
    Pozisyon yönetimi analyzer'ın genel döngüsünde: kâr → break-even,
    +%1 → ATR trailing, %1.5 sert stop.
    """
    await asyncio.sleep(60)
    # Restart sonrası mevcut M5 kapanışıyla senkron başla: ilk turda hazır
    # kapanışa bağlı kalıp yeni mum gelmeden taramayalım (0 ile başlarsak
    # açılışta anında, mum ortasından bir tarama yapılırdı).
    _last_m5_close_ms = 0
    try:
        m5_tick = await fetch_klines("BTCTRY", "5m", 2)
        if m5_tick:
            _last_m5_close_ms = int(m5_tick[-1][0])
    except Exception:
        pass
    while True:
        try:
            enabled = config.VELOCITY_AUTO_ENABLED and \
                (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
            if enabled:
                # M5 kapanış tetiklemesi: yeni kapanmış M5 mumu gelmeden tarama
                # yapma (replay'deki ile aynı senkron; her kapanışta 1 kez tara).
                try:
                    m5_tick = await fetch_klines("BTCTRY", "5m", 2)
                    if m5_tick:
                        latest_close_ms = int(m5_tick[-1][0])
                    else:
                        latest_close_ms = _last_m5_close_ms
                except Exception:
                    latest_close_ms = _last_m5_close_ms
                if latest_close_ms == _last_m5_close_ms:
                    # Yeni M5 kapanışı yok; kapanışa kadar bekle.
                    await asyncio.sleep(3)
                    continue
                _last_m5_close_ms = latest_close_ms
                scan5 = await detect_velocity_candidates({}, horizon_minutes=5)
                scan15 = await detect_velocity_candidates({}, horizon_minutes=15)
                _velocity_auto_state["last_scan_at"] = time.time()
                _velocity_auto_state["last_m5_close_ms"] = latest_close_ms
                # İki profilin adayları birleşik; skor üzerinden adil sıralama.
                # Zaten açık pozisyonu olan semboller atlanır (çoklu açılışı önler).
                pool = [c for c in (list(scan5.get("candidates") or []) + list(scan5.get("watchlist") or [])
                        + list(scan15.get("candidates") or []) + list(scan15.get("watchlist") or []))
                        if str(c.get("symbol") or "").upper() not in analyzer.positions]
                pool.sort(key=lambda c: -float(c.get("velocity_score") or 0))
                if pool:
                    best = pool[0]
                    outcome = await _open_velocity_position(best)
                    _velocity_auto_state["last_open"] = outcome
                    if outcome.get("status") == "PAPER_OPENED":
                        _velocity_auto_state["total_opened"] += 1
                        _velocity_auto_state["opened"].append({**outcome, "at": time.time(),
                                                                "score": best.get("velocity_score"),
                                                                "horizon": best.get("horizon_minutes")})
                        del _velocity_auto_state["opened"][:-20]
            _velocity_auto_state["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _velocity_auto_state["last_error"] = str(exc)
            logger.exception("autonomous velocity loop: %s", exc)
        # Kapanış senkronlu: bir sonraki kontrolü 5sn'de bir yap (interval'e bağlı değil)
        await asyncio.sleep(5)
