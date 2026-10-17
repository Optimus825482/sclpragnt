"""Tek sembol x tek tick için canlı `scan_one`'ın SAF yeniden üretimi.

Kaynak: `app/routers/velocity.py` -> `detect_velocity_candidates.scan_one`
(2026-10-16 sürümü). Gösterge yardımcıları, eşik sabitleri, `dynamic_target_pct`
ve `_panel_score` DOĞRUDAN canlı modülden içe aktarılır; burada yalnızca
çalışma-zamanı durumuna bağlı parçalar (REST/WS/DB/ML) parametreye veya
belgelenmiş nötr değere çevrilmiştir. Sapma listesi: docs/RESCAN_HARNESS.md.

Satır biçimi (Binance kline ile aynı): [open_ms, open, high, low, close, volume,
(close_ms, quote_volume, trade_count, taker_buy_base, ...)].
"""
from __future__ import annotations

import math

from app.config import config
from app.routers import velocity as V
from app.technical_analysis import _atr, _macd, _adx, _linreg_slope_pct, _wick_rejection_zscore

# Canlı: limit=60/40/130 çekilir, oluşmakta olan (forming) son bar düşürülür ->
# tick anında KAPANMIŞ bar sayısı bir eksiktir.
M1_BARS = 59
M5_BARS = 39
M15_BARS = 129
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}


def closed_before(rows, tf_ms: int, tick_ms: int, n: int | None = None) -> list:
    """`tick_ms` anında KAPANMIŞ barlar (open+tf <= tick); son `n` tanesi.

    Bu, canlı D-04 "forming mum düşürme" kuralının genelleştirilmiş hâlidir ve
    aynı zamanda ileriye bakmama (no look-ahead) garantisidir: tick'te veya
    sonrasında kapanan hiçbir bar pencereye giremez.
    """
    out = [r for r in rows if int(r[0]) + tf_ms <= tick_ms]
    return out[-n:] if n else out


def profile_atr_threshold(prof_atr: float | None, min_atr_pct: float | None = None) -> float:
    """Canlı: `_velocity_profile_atr.get(prof_key) or VELOCITY_MIN_ATR_PCT`."""
    base = float(min_atr_pct if min_atr_pct is not None else V.VELOCITY_MIN_ATR_PCT)
    return float(prof_atr) if prof_atr else base


def _grp_vals(grp):
    """Canlı `_grp_vals` birebir (M5 desen grup değerleri)."""
    cls = [float(r[4]) for r in grp]
    hs = [float(r[2]) for r in grp]
    ls = [float(r[3]) for r in grp]
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


def scan_symbol_at_tick(symbol: str, rows1m, rows5m, rows15m, *, horizon_minutes: int,
                        tick_ms: int, prof_atr: float | None = None,
                        min_atr_pct: float | None = None,
                        change_24h: float | None = None,
                        quote_vol_24h: float | None = None,
                        spread_mode: str = "unknown",
                        learned_target: float | None = None,
                        learned_count: int = 0,
                        pool_source: str = "rescan") -> dict | None:
    """Canlı `scan_one`'ın tick anındaki saf karşılığı. None -> canlıda satır üretilmezdi.

    Nötr/parametrik kabuller (sapma listesi belgede):
      * spread: `spread_mode="unknown"` -> canlıdaki "orderflow anlık görüntüsü yok"
        yolu (x VELOCITY_SPREAD_UNKNOWN_SCORE_MULT, spread kapısı yok, hedefte
        DEFAULT_ESTIMATED_SPREAD_PCT). `"known"` -> ceza yok (spread biliniyor ve
        kapı altında varsayımı).
      * taker oranı: satırda 10. sütun (taker_buy_base) varsa canlıyla aynı; yoksa
        canlının 9-sütun yolu gibi teyit atlanır (fail-open).
      * ML tahmini: yok (ml_pct/ml_prob None) -> hedef yalnız panel bandı+ATR+maliyet.
      * emir defteri dengesizliği: yok (radar.book_imbalance yazılmaz).
      * mikro-yapı çarpanı: 1.0 (sıralama ham skorla).
    """
    symbol = str(symbol).upper()
    profile = V.VELOCITY_PROFILES.get(horizon_minutes) or V.VELOCITY_PROFILES[5]
    base_target_pct = float(profile["target_pct"])
    now_ms = int(tick_ms)

    # Faz 1.4 likidite tabanı (veri yoksa fail-open -- canlıyla aynı).
    if quote_vol_24h is not None and quote_vol_24h < config.VELOCITY_MIN_QUOTE_VOL_24H:
        return None
    rows = closed_before(rows1m, TF_MS["1m"], now_ms, M1_BARS)
    if len(rows) < 30:
        return None
    last_age_sec = (now_ms - (int(rows[-1][0]) + 59_999)) / 1000
    if last_age_sec > 180:
        return None
    opens = [float(r[1]) for r in rows]
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    vols = [float(r[5]) for r in rows]
    _macd_res = _macd(closes)
    _macd_prev = _macd(closes[:-1]) if len(closes) > 1 else None
    macd_hist = _macd_res.get("histogram") if _macd_res else None
    macd_hist_prev = _macd_prev.get("histogram") if _macd_prev else None
    macd_bullish = bool(macd_hist is not None and macd_hist > 0)
    macd_rising = bool(macd_hist is not None and macd_hist_prev is not None and macd_hist > macd_hist_prev)
    i = len(rows) - 1
    price = closes[-1]
    if price <= 0:
        return None
    atr_value = _atr(highs, lows, closes, 14)
    atr_pct = (atr_value / price * 100) if (atr_value and price) else 0.0
    bb_width = V._velocity_bollinger_width(closes)
    rsi = V._velocity_rsi(closes)
    mfi = V._velocity_mfi(highs, lows, closes, vols)
    slope = V._velocity_struct_slope(closes)
    ml_slope = _linreg_slope_pct(closes, 10)
    aroon = V._velocity_aroon(highs, lows)
    aroon_up = aroon["up"] if aroon else None
    aroon_down = aroon["down"] if aroon else None
    ret3 = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 else 0.0
    ret5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0.0
    short_atr_val = _atr(highs, lows, closes, 3)
    short_atr_pct = (short_atr_val / price * 100) if (short_atr_val and price) else 0.0
    if rsi is None:
        return None
    mode = "trend_devam" if rsi >= V.VELOCITY_TREND_RSI_MIN else \
           "v_donusu" if rsi <= V.VELOCITY_REVERSAL_RSI_MAX else "notr"
    struct_ok = (slope is not None and slope >= V.VELOCITY_STRUCT_SLOPE_PCT) or \
                (aroon_up is not None and aroon_up >= 50)
    exhausted = None
    if mfi is not None and mfi >= V.VELOCITY_MFI_UPPER:
        exhausted = f"mfi_asiri_alim:{mfi:.0f}"
    elif mfi is not None and mfi <= V.VELOCITY_MFI_LOWER:
        exhausted = f"mfi_asiri_satim:{mfi:.0f}"
    elif rsi >= V.VELOCITY_RSI_UPPER:
        exhausted = f"rsi_asiri_alim:{rsi:.0f}"
    # 2026-10-17: canlı ile aynı karar (parite); çevrimdışı rejim kalkanı bilinmez → kapalı sayılır
    # (analiz betiği kalkanı mumlardan ayrıca kurar).
    exhausted_block, exhaustion_penalty = V.exhaustion_decision(exhausted, mode, False)
    min_atr = float(min_atr_pct if min_atr_pct is not None else V.VELOCITY_MIN_ATR_PCT)
    prof_atr_eff = profile_atr_threshold(prof_atr, min_atr)
    wick_info = _wick_rejection_zscore(opens, highs, lows, closes) if len(closes) >= 21 else {}
    upper_wick_ratio = float(wick_info.get("upper_wick_ratio", 0.0)) if isinstance(wick_info, dict) else 0.0
    upper_zscore = float(wick_info.get("upper_zscore", 0.0)) if isinstance(wick_info, dict) else 0.0
    rejection_wick = bool(wick_info.get("signal") == "bearish_rejection" or
                          (closes[-1] <= opens[-1] and upper_wick_ratio >= 0.60 and upper_zscore >= 2.0))
    is_breakout = bool(ret3 >= 1.0 or ret5 >= 1.8 or short_atr_pct >= 0.45)
    breakout_floor = min(prof_atr_eff, max(min_atr, prof_atr_eff * 0.6))
    atr_passes = bool(atr_pct >= prof_atr_eff or (is_breakout and atr_pct >= breakout_floor))
    passes = (exhausted_block is None and
              not rejection_wick and
              atr_passes and
              bb_width is not None and bb_width >= V.VELOCITY_MIN_BB_WIDTH_PCT and
              mode is not None and
              (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)))
    block_reason = None
    if not passes:
        if exhausted_block:
            block_reason = exhausted_block
        elif rejection_wick:
            block_reason = f"ust_fitil_tuzagi:wick_{upper_wick_ratio:.2f}_z{upper_zscore:.1f}"
        elif not atr_passes:
            block_reason = f"atr_yetersiz:{atr_pct:.2f}%<{prof_atr_eff:.2f}%"
        elif bb_width is None or bb_width < V.VELOCITY_MIN_BB_WIDTH_PCT:
            block_reason = f"bb_genisligi_yetersiz:{bb_width:.2f}%" if bb_width else "bb_verisi_yok"
        elif not (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)):
            block_reason = "yapisal_teyit_yok"
        else:
            block_reason = "diger"
    bb_ratio = (bb_width / V.VELOCITY_MIN_BB_WIDTH_PCT) if bb_width else 0.0
    struct_ratio = max(0.0, (slope or 0) / V.VELOCITY_STRUCT_SLOPE_PCT, (aroon_up or 0) / 50.0)
    atr_ratio = (atr_pct / prof_atr_eff) if prof_atr_eff else 0.0
    momentum = max(0.0, ret3, ret5)
    if len(vols) >= 20:
        _avg_vol = sum(vols[-20:]) / 20.0
        _vol_ratio = vols[-1] / _avg_vol if _avg_vol > 0 else 0.0
    else:
        _vol_ratio = 0.0
    volume_ratio = _vol_ratio
    _mom_ref = max(prof_atr_eff, 0.4)
    momentum_ratio = min(2.5, max(0.0, momentum / _mom_ref))
    velocity_score = round(100.0 * atr_ratio * bb_ratio
                           * (0.2 + 0.8 * struct_ratio)
                           * (0.5 + 0.5 * momentum_ratio)
                           * (0.5 + 0.5 * min(1.0, volume_ratio / 2.0)), 2)
    if config.VELOCITY_MACD_CONFIRMATION_ENABLED:
        if macd_bullish and macd_rising:
            velocity_score = round(velocity_score * 1.15, 2)
        elif macd_bullish:
            velocity_score = round(velocity_score * 1.05, 2)
        elif macd_hist is not None and macd_hist < -config.VELOCITY_MACD_DIP_GATE_ATR * atr_pct and not macd_rising:
            velocity_score = round(velocity_score * 0.85, 2)
    # ---- M5 desen ----
    m5_pattern = None
    m5_pattern_ok = None
    m5_macd_bullish = None
    m5_ml_features = None
    m5_rows = closed_before(rows5m or [], TF_MS["5m"], now_ms, M5_BARS)
    if len(m5_rows) >= 35:
        m5_closes = [float(r[4]) for r in m5_rows]
        m5_highs = [float(r[2]) for r in m5_rows]
        m5_lows = [float(r[3]) for r in m5_rows]
        m5_vols = [float(r[5]) for r in m5_rows]
        try:
            m5_ml_features = V._velocity_ml_feature_dict(m5_closes, m5_highs, m5_lows, m5_vols)
        except Exception:
            m5_ml_features = None
        k = len(m5_rows) - 1
        g1 = m5_rows[:k]
        g2 = m5_rows[:k - 2] if k > 3 else m5_rows[:k]
        g0 = m5_rows
        v0, v1, v2 = _grp_vals(g0), _grp_vals(g1), _grp_vals(g2)
        conds = {
            "g0_chg5": v0["chg5"] is not None and v0["chg5"] >= config.VELOCITY_PATTERN_G0_CHG5,
            "g0_chg3": v0["chg3"] is not None and v0["chg3"] >= config.VELOCITY_PATTERN_G0_CHG3,
            "g0_roc": v0["roc"] is not None and v0["roc"] >= config.VELOCITY_PATTERN_G0_ROC,
            "g0_atr": v0["atr_pct"] is not None and v0["atr_pct"] >= config.VELOCITY_PATTERN_G0_ATR,
            "g1_atr": v1["atr_pct"] is not None and v1["atr_pct"] >= config.VELOCITY_PATTERN_G1_ATR,
            "g2_atr": v2["atr_pct"] is not None and v2["atr_pct"] >= config.VELOCITY_PATTERN_G2_ATR,
        }
        m5_pattern = {kk: bool(vv) for kk, vv in conds.items()}
        m5_pattern_ok = all(conds.values())
        _m5_macd = _macd(m5_closes)
        m5_macd_hist = _m5_macd.get("histogram") if _m5_macd else None
        m5_macd_bullish = bool(m5_macd_hist is not None and m5_macd_hist > 0)
        if m5_macd_bullish and macd_rising:
            velocity_score = round(velocity_score * 1.10, 2)
    # ---- M1/M3 öncü ATR ----
    m1_atr_prev = m3_atr_prev = None
    if len(closes) >= 16:
        def _atr_pct_at(idx):
            if idx < 13:
                return None
            trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
                   for j in range(idx - 13, idx + 1)]
            return (sum(trs) / len(trs)) / closes[idx] * 100 if trs else None
        m1_atr_prev = _atr_pct_at(i - 1)
        m3_atr_prev = _atr_pct_at(i - 3)
    leading_ok = bool(m1_atr_prev is not None and m3_atr_prev is not None
                      and m1_atr_prev > 1.0 and m3_atr_prev > 1.0)
    if leading_ok:
        velocity_score = round(velocity_score * float(getattr(config, "VELOCITY_LEADING_MULTIPLIER", 1.15)), 2)
    # ---- Günlük momentum (15m) -- yalnız adx_14 rejim kapısına girer ----
    ret_8h = adx_14 = plus_di_14 = atr_pct_15m = slope_15m = None
    daily_momentum_ok = None
    if config.DAILY_MOMENTUM_ENABLED:
        rows15 = closed_before(rows15m or [], TF_MS["15m"], now_ms, M15_BARS)
        if len(rows15) >= 60:
            c15 = [float(r[4]) for r in rows15]
            h15 = [float(r[2]) for r in rows15]
            l15 = [float(r[3]) for r in rows15]
            px15 = c15[-1]
            if len(c15) >= 33 and c15[-33]:
                ret_8h = (c15[-1] / c15[-33] - 1) * 100
            _adx15 = _adx(h15, l15, c15, 14)
            if _adx15:
                adx_14 = _adx15.get("adx")
                plus_di_14 = _adx15.get("plus_di")
            _atr15 = _atr(h15, l15, c15, 14)
            if _atr15 and px15:
                atr_pct_15m = _atr15 / px15 * 100
            slope_15m = _linreg_slope_pct(c15, 10)
            conds15 = {
                "ret_8h": ret_8h is not None and ret_8h >= config.DAILY_MOMENTUM_RET_8H_MIN,
                "atr": atr_pct_15m is not None and atr_pct_15m >= config.DAILY_MOMENTUM_ATR_MIN,
                "adx": adx_14 is not None and adx_14 >= config.DAILY_MOMENTUM_ADX_MIN,
                "plus_di": plus_di_14 is not None and plus_di_14 > 20.0,
                "slope": slope_15m is not None and slope_15m >= config.DAILY_MOMENTUM_SLOPE_MIN,
                "spread": True,  # spread bilinmiyor -> canlıda `spread_v is None` -> True
            }
            daily_momentum_ok = all(conds15.values())
    # ---- Hedef (ML yok; spread bilinmiyor) ----
    spread_pct = None
    effective_target = V.dynamic_target_pct(
        V._panel_score(velocity_score), base_target_pct,
        learned_pct=learned_target if (learned_target and learned_target > 0) else None,
        learned_count=int(learned_count or 0),
        ml_pct=None, ml_prob=None, spread_pct=spread_pct, atr_pct=atr_pct,
        horizon_minutes=horizon_minutes)
    if config.VELOCITY_TARGET_REALISM_ENABLED:
        macd_strong = bool(macd_bullish or macd_rising)
        if not macd_strong and 0.0 < config.VELOCITY_TARGET_REALISM_MIN_ML_PROB:
            effective_target = min(effective_target, config.VELOCITY_TARGET_REALISM_MAX_PCT)
    velocity_score = round(velocity_score, 2)
    if exhaustion_penalty:
        velocity_score = round(velocity_score * float(getattr(config, "VELOCITY_EXHAUSTION_PENALTY_MULT", 0.85)), 2)
    # ---- Radar güçlendirme çarpanları ----
    _radar: dict = {}
    if exhaustion_penalty:
        _radar["exhaustion_penalty"] = exhausted
    if config.VELOCITY_TAKER_CONFIRM_ENABLED and len(rows) >= 10:
        _win = rows[-10:]
        _vol_sum = sum(float(r[5]) for r in _win)
        # 2026-10-17: historical_candles taker kolonu (migration 020) → kanonik kline [9]; boş satır NaN gelir.
        if _vol_sum > 0 and all(len(r) > 9 and r[9] is not None and math.isfinite(float(r[9])) for r in _win):
            _taker_ratio = sum(float(r[9]) for r in _win) / _vol_sum
            _radar["taker_buy_ratio"] = round(_taker_ratio, 3)
            if _taker_ratio >= config.VELOCITY_TAKER_STRONG_RATIO:
                velocity_score = round(velocity_score * config.VELOCITY_TAKER_STRONG_MULT, 2)
                _radar["taker_confirm"] = "strong"
            elif _taker_ratio <= config.VELOCITY_TAKER_WEAK_RATIO:
                velocity_score = round(velocity_score * config.VELOCITY_TAKER_WEAK_MULT, 2)
                _radar["taker_confirm"] = "weak"
        else:
            _radar["taker_unavailable"] = True
    if config.VELOCITY_REGIME_GATE_ENABLED and len(closes) >= 10:
        _n = 10
        _hs = highs[-_n:]
        _ls = lows[-_n:]
        _cs = closes[-_n:]
        _tr_sum = sum(max(_hs[k] - _ls[k], abs(_hs[k] - _cs[k - 1]), abs(_ls[k] - _cs[k - 1]))
                      for k in range(1, _n))
        _rng = max(_hs) - min(_ls)
        if _tr_sum > 0 and _rng > 0:
            _choppy = 100.0 * math.log10(_tr_sum / _rng) / math.log10(_n)
            _radar["choppiness_10"] = round(_choppy, 1)
            _adx_strong = adx_14 is not None and adx_14 >= config.VELOCITY_REGIME_CHOP_ADX_MAX
            if _choppy > config.VELOCITY_REGIME_CHOPPINESS_MAX and not _adx_strong:
                velocity_score = round(velocity_score * config.VELOCITY_REGIME_CHOP_SCORE_MULT, 2)
                _radar["regime_chop"] = True
    if change_24h is not None and change_24h >= config.VELOCITY_LATE_PHASE_CHANGE_PCT:
        velocity_score = round(velocity_score * config.VELOCITY_LATE_PHASE_SCORE_MULT, 2)
        _radar["late_phase"] = True
    if config.VELOCITY_SPREAD_FAIL_CLOSED and spread_mode == "unknown":
        velocity_score = round(velocity_score * config.VELOCITY_SPREAD_UNKNOWN_SCORE_MULT, 2)
        _radar["spread_unknown"] = True
    _hi = max(highs[-60:])
    _lo = min(lows[-60:])
    if _hi - _lo > 0:
        _radar["range_pos_60"] = round((price - _lo) / (_hi - _lo), 3)

    return {"symbol": symbol, "price": price, "volume_ratio": round(volume_ratio, 2),
            "atr_pct": round(atr_pct, 3),
            "bb_width_pct": round(bb_width, 2) if bb_width else None,
            "rsi": round(rsi, 1) if rsi else None, "mfi": round(mfi, 1) if mfi else None,
            "mode": mode, "exhausted": exhausted,
            "linreg_slope10_pct": round(ml_slope, 3) if ml_slope is not None else None,
            "aroon_up": round(aroon_up, 0) if aroon_up is not None else None,
            "aroon_down": round(aroon_down, 0) if aroon_down is not None else None,
            "horizon_minutes": horizon_minutes,
            "target_pct": round(effective_target, 3),
            "ret3_pct": round(ret3, 3),
            "pool_source": pool_source,
            "change_24h": change_24h,
            "quote_vol_24h": quote_vol_24h,
            "velocity_score": velocity_score, "passes": passes,
            "block_reason": block_reason,
            "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
            "macd_bullish": macd_bullish, "macd_rising": macd_rising,
            "m5_macd_bullish": m5_macd_bullish,
            "m5_pattern": m5_pattern, "m5_pattern_ok": m5_pattern_ok,
            "ml_features_5m": m5_ml_features,
            "m1_atr_prev": round(m1_atr_prev, 3) if m1_atr_prev is not None else None,
            "m3_atr_prev": round(m3_atr_prev, 3) if m3_atr_prev is not None else None,
            "leading_ok": leading_ok,
            "daily_momentum_ok": daily_momentum_ok,
            "ret_8h_pct": round(ret_8h, 3) if ret_8h is not None else None,
            "adx_14": round(adx_14, 1) if adx_14 is not None else None,
            "atr_pct_15m": round(atr_pct_15m, 3) if atr_pct_15m is not None else None,
            "radar": _radar,
            "last_closed_at": int(rows[-1][0]),
            "tick_ms": now_ms}


def candidate_id(symbol: str, tick_ms: int, horizon_minutes: int) -> str:
    return f"rescan:{str(symbol).upper()}:{int(tick_ms)}:{int(horizon_minutes)}"


def to_journal_row(cand: dict, *, rank: int | None) -> dict:
    """`velocity_candidates` şekline indirge (canlı journal satırı + rescan ekleri)."""
    tick_ms = int(cand["tick_ms"])
    h = int(cand["horizon_minutes"])
    return {
        "candidate_id": candidate_id(cand["symbol"], tick_ms, h),
        "created_at": tick_ms / 1000.0,
        "tick_ms": tick_ms,
        "symbol": cand["symbol"],
        "horizon_minutes": h,
        "price": float(cand["price"]),
        "target_pct": float(cand["target_pct"]),
        "atr_pct": float(cand["atr_pct"] or 0.0),
        # Canlı journal bu kolona SABİT 0.0 yazar; rescan gerçek oranı yazar.
        "volume_ratio": float(cand["volume_ratio"] or 0.0),
        "ret3_pct": float(cand["ret3_pct"] or 0.0),
        "velocity_score": float(cand["velocity_score"] or 0.0),
        "passes": bool(cand["passes"]),
        "rank": rank,
        "mode": cand.get("mode"),
        "block_reason": cand.get("block_reason"),
        # 2026-10-17 (rejim kalkanı analizi): aşırı alım kapısı KAPALI koşuda hangi adayın
        # canlıda `mfi/rsi_asiri_alim` ile eleneceğini etiketlemek için (JSONL'de düz alan).
        "exhausted": cand.get("exhausted"),
        "rsi": cand.get("rsi"),
        "mfi": cand.get("mfi"),
        "pool_source": cand.get("pool_source"),
        "change_24h": cand.get("change_24h"),
        "m5_pattern": cand.get("m5_pattern"),
        "m5_pattern_ok": cand.get("m5_pattern_ok"),
        "leading_ok": cand.get("leading_ok"),
        "m1_atr_prev": cand.get("m1_atr_prev"),
        "m3_atr_prev": cand.get("m3_atr_prev"),
        "radar": cand.get("radar") or {},
        "source": "rescan",
    }


def rank_tick(cands: list[dict], *, rank_limit: int = 10, journal_cap: int = 20) -> list[dict]:
    """Bir tick+ufuk için canlı sıralama/journal kuralı.

    Canlı: `candidates.sort(score x micro_mult)`; ilk `limit` (monitoring: 10) rank
    alır; journal `candidates[:max(limit, 20)]` passes=true satır yazar. Rescan'de
    micro_mult=1.0. `journal_cap=0` -> tüm geçenler yazılır.
    """
    passing = [c for c in cands if c.get("passes")]
    passing.sort(key=lambda c: float(c.get("velocity_score") or 0.0), reverse=True)
    out = []
    cap = len(passing) if not journal_cap else max(rank_limit, journal_cap)
    for idx, c in enumerate(passing[:cap], 1):
        out.append(to_journal_row(c, rank=idx if idx <= rank_limit else None))
    return out
