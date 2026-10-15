"""Bildirimlerin KENDİ sonuç ölçümü (candidate_id'si olmayan bildirimler için).

Sorun (2026-10-16, canlı veritabanı kopyasında ölçüldü): 13 Ekim'den beri bildirimlerin ~%65-70'i
`candidate_id` olmadan yazılıyor (`global_lead_lag.py` bildirimi doğrudan kaydeder). Sonucu hiç
eşleşmediği için başarı KPI'ı bu bildirimleri sayamıyordu.

TASARIM (yan etkisiz):
  * Ölçüm `velocity_candidates`'a YAZMAZ. O tablo sembol kalite filtresini ve ML/kalibrasyonu besler;
    geri doldurma satırlarını oraya yazmak canlı bildirim davranışını değiştirirdi.
  * Sonuç bildirimin KENDİ sütunlarına (`outcome_status`, `mfe_pct`, `mae_pct`) yazılır
    (`database.update_monitoring_notification_outcome`; ilk sonuç korunur).
  * Hedef öğrenmeyi (`record_symbol_target_outcome`) ve `pending_targets` izleyicisini ETKİLEMEZ.
  * Yalnız RAPOR ucu bu sonucu okur (`get_monitoring_velocity_matches(include_own_outcomes=True)`).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("scalper.notification_outcomes")

STATUS_HIT = "HEDEFE_ULTI"
STATUS_TIMEOUT = "SURE_DOLDU"
STATUS_NO_DATA = "VERI_YOK"          # mum bulunamadı; tekrar tekrar denenmesin diye mühürlenir
_USABLE_STATUSES = {STATUS_HIT, STATUS_TIMEOUT, "STOP"}

LOOP_INTERVAL_SEC = 300.0
MAX_AGE_SEC = 48 * 3600.0
BATCH_LIMIT = 40
_KLINE_PAD_MS = 65_000


def outcome_from_window(window: list, entry: float, target_pct: float) -> dict | None:
    """1 dk mum penceresinden MFE/MAE ve durum. Pencere boş / giriş geçersizse None.

    Mum satırı: [açılış_zamanı, açılış, yüksek, düşük, kapanış, ...]. MAE hiçbir zaman pozitif olmaz.
    """
    if not window or not entry or entry <= 0:
        return None
    try:
        highs = [float(c[2]) for c in window if c and len(c) > 3]
        lows = [float(c[3]) for c in window if c and len(c) > 3]
    except (TypeError, ValueError):
        return None
    if not highs or not lows:
        return None
    mfe = (max(highs) - entry) / entry * 100.0
    mae = min(0.0, (min(lows) - entry) / entry * 100.0)
    target = float(target_pct or 0)
    status = STATUS_HIT if target > 0 and mfe >= target else STATUS_TIMEOUT
    return {"status": status, "mfe_pct": round(mfe, 4), "mae_pct": round(mae, 4)}


def apply_own_outcome(item: dict) -> bool:
    """Bildirim satırının KENDİ sonucunu rapor alanlarına uygula (yalnız aday ölçümü yoksa).

    Girdi anahtarları: `outcome_status`, `own_mfe_pct` (bildirimin kendi sütunları), `candidate_status`,
    `mfe_pct`, `target_pct`. Aday ölçümü varsa o KAZANIR. Uygulandıysa True.
    """
    if item.get("candidate_status") == "evaluated" and item.get("mfe_pct") is not None:
        return False
    status = item.get("outcome_status")
    mfe = item.get("own_mfe_pct")
    if status not in _USABLE_STATUSES or mfe is None:
        return False
    mfe = float(mfe)
    target = float(item.get("target_pct") or 0)
    item["candidate_status"] = "evaluated"
    item["mfe_pct"] = mfe
    item["touched_target"] = bool(status == STATUS_HIT or (target > 0 and mfe >= target))
    item["own_outcome"] = True
    return True


async def measure_pending_notifications(limit: int = BATCH_LIMIT, now: float | None = None) -> int:
    """candidate_id'si olmayan, penceresi kapanmış bildirimleri ölçüp kendi sütunlarına yazar. Ölçülen sayı."""
    from app import database
    from app.binance_tr_public import klines as fetch_klines
    from app.routers.velocity import _post_signal_window

    rows = await database.list_unmeasured_notifications(
        now if now is not None else time.time(), MAX_AGE_SEC, limit)
    done = 0
    for row in rows:
        try:
            symbol = str(row.get("symbol") or "").upper()
            detected = float(row.get("detected_at") or 0)
            horizon = int(row.get("horizon_minutes") or 5)
            entry = float(row.get("price") or 0)
            target = float(row.get("target_pct") or 0)
            if not symbol or detected <= 0:
                continue
            created_ms = int(detected * 1000)
            due_ms = created_ms + horizon * 60_000
            candles = await fetch_klines(symbol, "1m", horizon + 15, created_ms, due_ms + _KLINE_PAD_MS)
            window = _post_signal_window(candles, created_ms, due_ms) if candles else []
            if not window and candles:
                window = [c for c in candles if created_ms - 30_000 <= int(c[0]) <= due_ms + 60_000]
            if entry <= 0 and window:
                entry = float(window[0][1])
            out = outcome_from_window(window, entry, target)
            if out is None:
                await database.update_monitoring_notification_outcome(row["id"], STATUS_NO_DATA, None, None)
            else:
                await database.update_monitoring_notification_outcome(
                    row["id"], out["status"], out["mfe_pct"], out["mae_pct"])
                done += 1
        except Exception as exc:  # noqa: BLE001 — tek satır hatası döngüyü durdurmasın
            logger.debug("bildirim sonucu ölçülemedi (%s): %s", row.get("id"), exc)
        await asyncio.sleep(0.05)
    return done


async def notification_outcome_loop() -> None:
    """Her 5 dakikada bir ölçülmemiş bildirimleri ölçer. Hata döngüyü öldürmez."""
    await asyncio.sleep(30)
    while True:
        try:
            measured = await measure_pending_notifications()
            if measured:
                logger.info("bildirim sonucu ölçüldü: %d", measured)
        except Exception as exc:  # noqa: BLE001
            logger.debug("bildirim sonuç döngüsü atlandı: %s", exc)
        await asyncio.sleep(LOOP_INTERVAL_SEC)


__all__: list[Any] = [
    "STATUS_HIT", "STATUS_TIMEOUT", "STATUS_NO_DATA", "outcome_from_window",
    "apply_own_outcome", "measure_pending_notifications", "notification_outcome_loop",
]
