"""Radar hedef kalibrasyonu: bildirim hedefini ölçülmüş MFE medyanına dayandırır.

# 2026-10-15 (radar iyileştirme): skor kademesi (tier) yerine, ufuk başına son N
# günün ÖLÇÜLMÜŞ MFE yüzdeliklerinden (varsayılan p50) hedef üretilir.
Bayraklı ve varsayılan KAPALI: `RADAR_TARGET_CALIBRATION_ENABLED=1` ile açılır.
Kapalıyken, önbellek boşken/bayatken veya ufuk bilinmiyorken çağıran tarafın
verdiği yedek hedef (`fallback_pct`) aynen döner; davranış değişmez.

Çekirdek fonksiyon `calibrated_target_pct` SENKRON ve saf okumadır (önbellekten
okur); DB çağrısı yalnız `refresh_target_calibration` içindedir.
"""
import asyncio
import logging
import math
import os
import time

from app import database

logger = logging.getLogger("scalper.target_calibration")

# 2026-10-15 (radar iyileştirme): bayraklar ve sınırlar (config.py'ye dokunulmaz;
# doğrudan ortam değişkeninden okunur).
TARGET_CALIBRATION_ENABLED = os.getenv("RADAR_TARGET_CALIBRATION_ENABLED", "0") == "1"
TARGET_CALIBRATION_QUANTILE = os.getenv("RADAR_TARGET_CALIBRATION_QUANTILE", "p50")
TARGET_CALIBRATION_TTL_SEC = 600
TARGET_MIN_PCT = 0.6
TARGET_MAX_PCT = 4.5

_VALID_QUANTILES = ("p30", "p50", "p70")

# {"loaded_at": son yükleme zamanı (epoch sn), "data": {horizon: {"n", "p50", "p70", "p30"}}}
_CACHE: dict = {"loaded_at": 0.0, "data": {}}


async def refresh_target_calibration() -> dict:
    """Ufuk başına MFE yüzdeliklerini DB'den okuyup önbelleğe yazar.

    Bayrak kapalıyken DB'ye hiç gidilmez (boş önbellek → her çağrı yedek hedef).
    """
    if not TARGET_CALIBRATION_ENABLED:
        return {}
    data = await database.get_unified_mfe_quantiles()
    _CACHE["data"] = dict(data or {})
    _CACHE["loaded_at"] = time.time()
    return _CACHE["data"]


def calibrated_target_pct(horizon_minutes: int, fallback_pct: float) -> float:
    """Ufuk için ölçülmüş yüzdelik hedefi; yoksa `fallback_pct`.

    Kapalı bayrak, boş/bayat önbellek (> TTL) veya eksik ufuk → `fallback_pct`.
    Aksi halde seçilen yüzdelik [TARGET_MIN_PCT, TARGET_MAX_PCT] aralığına
    kelepçelenir ve 1 ondalığa yuvarlanır.
    """
    if not TARGET_CALIBRATION_ENABLED:
        return fallback_pct
    loaded_at = float(_CACHE.get("loaded_at") or 0.0)
    if loaded_at <= 0.0 or (time.time() - loaded_at) > TARGET_CALIBRATION_TTL_SEC:
        return fallback_pct
    try:
        entry = (_CACHE.get("data") or {}).get(int(horizon_minutes))
    except (TypeError, ValueError):
        return fallback_pct
    if not entry:
        return fallback_pct
    quantile = TARGET_CALIBRATION_QUANTILE
    if quantile not in _VALID_QUANTILES:
        quantile = "p50"
    try:
        value = float(entry[quantile])
    except (KeyError, TypeError, ValueError):
        return fallback_pct
    if not math.isfinite(value):
        return fallback_pct
    return round(min(TARGET_MAX_PCT, max(TARGET_MIN_PCT, value)), 1)


def set_calibration_for_tests(data: dict, loaded_at: float) -> None:
    """Yalnız testler için: önbelleği doğrudan doldurur (DB'ye gitmez)."""
    _CACHE["data"] = dict(data or {})
    _CACHE["loaded_at"] = float(loaded_at)


async def calibration_refresh_loop(interval_sec: int = 600) -> None:
    """Önbelleği periyodik yeniler. Hata döngüyü DÜŞÜRMEZ (yalnız loglanır).

    # 2026-10-15 (radar iyileştirme): main.py başlangıç görev listesine
    # `asyncio.create_task(target_calibration.calibration_refresh_loop())` olarak
    # eklenmeli (bu modül main.py / runtime.py'ye dokunmaz).
    """
    while True:
        try:
            await refresh_target_calibration()
        except Exception as exc:
            logger.warning("hedef kalibrasyonu yenilenemedi: %s", exc)
        await asyncio.sleep(max(30, int(interval_sec)))
