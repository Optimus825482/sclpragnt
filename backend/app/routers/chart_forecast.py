"""Chart-page ML price forecasts (no LLM).

Grafik üst paneli için sembolün güncel teknik snapshot'ından ML özellikleri
toplanır, ml_forecast.predict_target çağrılır (5/15 dk ufukları) ve sonuç
chart_forecasts tablosuna kaydedilir. Ufuk (5/15 dk) dolunca
chart_forecast_evaluation_loop kapanmış M1 mumlarla ölçüp status='evaluated'
yapar; değerlendirilen satırlar ML eğitimine journal olarak girer.

LLM yok: yalnız model çıktısı (target_pct -> hedef fiyat, hit_probability).
"""
from __future__ import annotations

import asyncio
import time
import logging

from fastapi import APIRouter, HTTPException

from app.config import config
from app import database
from app import ml_forecast
from app.binance_tr_public import klines as fetch_klines
from app.routers.velocity import (_velocity_bollinger_width, _velocity_rsi,
                                  _velocity_mfi, _velocity_linreg_slope, _velocity_aroon)

logger = logging.getLogger("scalper.chart_forecast")

router = APIRouter(prefix="/api/chart")

# Aynı 5dklik pencere -> paylaşılan/cache'li tahmin (plan: within_sec).
CACHE_WINDOW_SEC = 300
HORIZONS = (5, 15)
EVAL_INTERVAL_SEC = int(getattr(config, "CHART_FORECAST_EVAL_INTERVAL_SEC", 15))
# Ufuk kapanışı sonrası hedef dokunuşu için ek gözlem penceresi (dk).
HIT_GRACE_MINUTES = int(getattr(config, "LLM_FORECAST_HIT_GRACE_MINUTES", 0))


async def collect_forecast_features(symbol: str) -> dict | None:
    """Sembolün güncel 1m snapshot'ından ML tahmin özelliklerini toplar.

    predict_target'in beklediği feature isimlerini üretir (velocity taramasıyla
    aynı hesap). Veri yetersiz/çok eski -> None (tahmin yapılamaz).
    """
    now_ms = int(time.time() * 1000)
    try:
        rows = await fetch_klines(symbol, "1m", 60)
    except Exception:
        return None
    if len(rows) < 30:
        return None
    # Güncel mum şartı: ölü/sembol dışı sembollerde tahmin üretme.
    last_age_sec = (now_ms - (int(rows[-1][0]) + 59_999)) / 1000
    if last_age_sec > 180:
        return None
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    vols = [float(r[5]) for r in rows]
    price = closes[-1]
    if price <= 0:
        return None
    atr_pct = None
    trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
           for j in range(max(1, len(closes) - 14), len(closes))]
    if trs:
        atr_pct = (sum(trs) / len(trs)) / price * 100
    aroon = _velocity_aroon(highs, lows)
    return {
        "price": price,
        "ret3_pct": round((closes[-1] / closes[-4] - 1) * 100, 3) if len(closes) >= 4 else None,
        "atr_pct": round(atr_pct, 3) if atr_pct else None,
        "bb_width_pct": round(_velocity_bollinger_width(closes), 2) if _velocity_bollinger_width(closes) is not None else None,
        "rsi": round(_velocity_rsi(closes), 1) if _velocity_rsi(closes) is not None else None,
        "mfi": round(_velocity_mfi(highs, lows, closes, vols), 1) if _velocity_mfi(highs, lows, closes, vols) is not None else None,
        "linreg_slope10_pct": round(_velocity_linreg_slope(closes), 3) if _velocity_linreg_slope(closes) is not None else None,
        "aroon_up": round(aroon["up"], 0) if aroon else None,
        "aroon_down": round(aroon["down"], 0) if aroon else None,
    }


def _run_predict(symbol: str, features: dict, horizon: int) -> dict | None:
    ml = ml_forecast.predict_target(symbol, {
        "ret3_pct": features.get("ret3_pct"), "atr_pct": features.get("atr_pct"),
        "bb_width_pct": features.get("bb_width_pct"), "rsi": features.get("rsi"),
        "mfi": features.get("mfi"), "linreg_slope10_pct": features.get("linreg_slope10_pct"),
        "aroon_up": features.get("aroon_up"), "aroon_down": features.get("aroon_down"),
    }, horizon)
    return ml


@router.post("/{symbol}/forecast")
async def create_chart_forecast(symbol: str, payload: dict | None = None):
    """Tahmin üret (cache'li): fresh=1 -> yeni tahmin + yeni kayıt."""
    fresh = bool((payload or {}).get("fresh") or (payload or {}).get("fresh") == 1)
    timeframe = (payload or {}).get("timeframe") or "5m"
    sym = str(symbol).upper()
    forecast_rows = []
    cache = {"hit": False, "age_sec": None}

    if not fresh:
        cached = await database.get_recent_chart_forecast(sym, timeframe, within_sec=CACHE_WINDOW_SEC)
        if cached:
            age_sec = int(time.time() - float(cached["created_at"]))
            # 5/15 dk ufuklarının ikisi de aynı pencere içinde üretilmişse cache dön
            cache = {"hit": True, "age_sec": age_sec}
            row = {"horizon_minutes": cached["horizon_minutes"], "target_pct": cached["target_pct"],
                   "target_price": cached["target_price"], "hit_probability": cached["hit_probability"]}
            return {"symbol": sym, "timeframe": timeframe,
                    "generated_at": cached["created_at"], "forecasts": [row], "cache": cache}

    features = await collect_forecast_features(sym)
    if not features:
        raise HTTPException(status_code=503, detail="sembol için güncel veri yok (tahmin yapılamadı)")

    entry_price = float(features["price"])
    for horizon in HORIZONS:
        ml = _run_predict(sym, features, horizon)
        if not ml:
            continue
        target_pct = float(ml["target_pct"])
        target_price = round(entry_price * (1 + target_pct / 100), 8)
        saved = await database.save_chart_forecast(
            sym, timeframe, horizon, entry_price, target_pct, target_price,
            hit_probability=ml.get("hit_probability"), model=ml.get("trained_at"))
        if saved:
            forecast_rows.append({
                "horizon_minutes": horizon, "target_pct": target_pct,
                "target_price": target_price, "hit_probability": ml.get("hit_probability"),
            })

    if not forecast_rows:
        raise HTTPException(status_code=503, detail="model tahmini üretemedi (eğitimli model yok?)")

    return {"symbol": sym, "timeframe": timeframe,
            "generated_at": time.time(), "forecasts": forecast_rows, "cache": cache}


@router.get("/{symbol}/forecast-history")
async def chart_forecast_history(symbol: str):
    """Sembolün değerlendirilmiş tahminlerinin başarı özeti + son kayıtlar."""
    sym = str(symbol).upper()
    rows = await database.list_chart_forecasts(sym, limit=200)
    evaluated = [r for r in rows if r["status"] == "evaluated" and r["direction_correct"] is not None]
    total = len(rows)
    correct = sum(1 for r in evaluated if r["direction_correct"])
    hit = sum(1 for r in evaluated
              if r.get("max_favorable_pct") is not None and r.get("target_pct")
              and r["max_favorable_pct"] >= r["target_pct"])
    recent = [
        {"id": r["id"], "horizon_minutes": r["horizon_minutes"], "target_pct": r["target_pct"],
         "entry_price": r["entry_price"], "direction_correct": r["direction_correct"],
         "max_favorable_pct": r.get("max_favorable_pct"), "created_at": r["created_at"],
         "status": r["status"], "hit_probability": r.get("hit_probability")}
        for r in rows[:20]
    ]
    return {
        "symbol": sym, "total": total, "evaluated": len(evaluated),
        "direction_correct_rate": round(correct / len(evaluated), 4) if evaluated else None,
        "target_hit_rate": round(hit / len(evaluated), 4) if evaluated else None,
        "recent": recent,
    }


async def _outcome_from_closed_m1(symbol: str, forecast: dict):
    """Ufuk kapanınca M1 mumlarla kazancı ölçer (llm_forecast pattern'i)."""
    created_at_ms = int(float(forecast["created_at"]) * 1000)
    horizon_minutes = int(forecast["horizon_minutes"])
    due_at_ms = created_at_ms + horizon_minutes * 60_000
    grace_end_ms = due_at_ms + HIT_GRACE_MINUTES * 60_000
    # Sıcak WS cache yok — chart sembolleri, REST'ten kapanmış mumları al.
    try:
        rows = await fetch_klines(symbol, "1m", horizon_minutes + HIT_GRACE_MINUTES + 12,
                                  start_time_ms=created_at_ms, end_time_ms=grace_end_ms + 65_000)
    except Exception:
        rows = []
    if len(rows) < 2:
        return None
    timestamps = [int(r[0]) for r in rows]
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    close_times = [t + 59_999 for t in timestamps]
    end_index = next((i for i, c in enumerate(close_times) if c >= due_at_ms), None)
    start_index = next((i for i, c in enumerate(close_times) if c >= created_at_ms), None)
    if start_index is None or end_index is None or end_index < start_index:
        return None
    entry = float(forecast["entry_price"])
    target_pct = float(forecast["target_pct"] or 0)
    target_price = (forecast.get("target_price")
                    or (entry * (1 + target_pct / 100) if entry else None))
    # Hedef dokunuşu: up varsayım (scalper yükseliş hedefi).
    hit_index = None
    if entry > 0 and target_price:
        for index in range(start_index, min(end_index + 1, len(highs))):
            if float(highs[index]) >= float(target_price):
                hit_index = index
                break
    return {
        "outcome_price": float(closes[end_index]),
        "max_high": max(float(v) for v in highs[start_index:end_index + 1]),
        "min_low": min(float(v) for v in lows[start_index:end_index + 1]),
        "first_hit_minutes": (round((int(timestamps[hit_index]) - created_at_ms) / 60_000.0, 1)
                              if hit_index is not None else None),
    }


async def chart_forecast_evaluation_loop():
    """pending tahminlerin ufku (5/15 dk) dolunca M1 ile ölç, evaluated yap."""
    await asyncio.sleep(20)
    while True:
        evaluated = 0
        try:
            pending = await database.get_pending_chart_forecasts(limit=200)
            for forecast in pending:
                observed = await _outcome_from_closed_m1(forecast["symbol"], forecast)
                if not observed:
                    continue
                entry = float(forecast["entry_price"])
                return_pct = observed["outcome_price"] / entry - 1 if entry else 0.0
                max_fav = observed["max_high"] / entry - 1 if entry else None
                max_adv = observed["min_low"] / entry - 1 if entry else None
                # Scalper yükseliş hedefi: yön her zaman up.
                direction_correct = bool(max_fav is not None and max_fav >= 0)
                outcome = {
                    "evaluated_at": time.time(),
                    "outcome_price": observed["outcome_price"],
                    "outcome_return_pct": return_pct,
                    "outcome_direction": "up" if return_pct >= 0 else "down" if return_pct < 0 else "range",
                    "direction_correct": direction_correct,
                    "max_favorable_pct": max_fav,
                    "max_adverse_pct": max_adv,
                    "outcome_details": {
                        "first_hit_minutes": observed["first_hit_minutes"],
                        "eventual_hit": observed["first_hit_minutes"] is not None,
                    },
                }
                if await database.mark_chart_forecast_evaluated(forecast["id"], outcome):
                    evaluated += 1
        except Exception as exc:
            logger.warning("chart_forecast eval hatası: %s", exc)
        if evaluated:
            logger.info("chart_forecast değerlendirildi: %s", evaluated)
        await asyncio.sleep(EVAL_INTERVAL_SEC)
