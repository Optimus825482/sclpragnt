"""Global arka plan tarama döngüsü — GÖRÜNMEZ erken-tespit katmanı (2026-10-07).

NE YAPAR:
    Binance Global (USDT) spot piyasasını, TR taramasıyla AYNI dedektör
    (`velocity.detect_velocity_candidates`) üzerinden tarar. Global daha likit
    olduğu için TR'de de listeli bir sembolün yükselişini BİRKAÇ SANİYE/DAKİKA
    ERKEN gösterir. Yakalanan her hareket `app/global_lead_lag.py`'ye verilir;
    orada normal bir **TR bildirimi** ve **TR otonom paper işlemi**ne dönüşür.

NE YAPMAZ (kullanıcı direktifi — bağlayıcı):
    * İkinci bir venue DEĞİLDİR. Arayüzde Global'e dair hiçbir şey görünmez;
      bu döngü hiçbir UI/API ucu yayınlamaz, durumu yalnız `logger.info` ile
      bırakır (teşhis) ve `get_status()` içsel denetim içindir.
    * Emir yolu YOKTUR. Global tarama salt-okunurdur; gerçek emir yalnız TR
      tarafında ve yalnız TR özel anahtarlarıyla verilir.
    * Global gözlemleri TR kalibrasyon tablolarına YAZMAZ (`journal_enabled=
      False`) — TR kalibrasyon popülasyonu TR (TRY) gözlemlerinden oluşmalıdır.

BAYRAK:
    Yalnız `config.GLOBAL_SCAN_ENABLED` açıkken başlar (varsayılan kapalı) →
    açılmadan üretim davranışı birebir aynı kalır, hiçbir Global bağlantısı
    kurulmaz.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import config

logger = logging.getLogger("scalper.global_radar")

# Döngü sağlığı — UI'ya YAYINLANMAZ, yalnız günlük/teşhis.
_status: dict = {
    "started_at": None,
    "last_scan_at": None,
    "scan_count": 0,
    "detections": 0,
    "last_error": None,
    "last_candidates": 0,
}


def get_status() -> dict:
    """İçsel durum (teşhis). Arayüzde gösterilmez."""
    return dict(_status)


async def _scan_once() -> int:
    """Tek Global tarama turu; işlenen tespit sayısını döndürür."""
    from app.state import global_market
    from app import binance_public as global_adapter
    from app.routers.velocity import detect_velocity_candidates
    from app import global_lead_lag

    if global_market is None:
        return 0

    # TR taramasıyla AYNI dedektör. Borsa parametreleri açıkça geçilir:
    # `adapter` Global public modülü, evren Global USDT sembolleri, quote USDT.
    # `journal_enabled=False` → TR velocity journal'ına ve microflow akışına
    # YAZMAZ (TR kalibrasyonu kirlenmesin).
    cache: dict = {}
    try:
        scan5 = await detect_velocity_candidates(
            {"limit": 10}, horizon_minutes=5,
            market=global_market, adapter=global_adapter, quote_asset="USDT",
            universe_symbols=config.GLOBAL_SYMBOLS, journal_enabled=False,
            kline_cache=cache)
        scan15 = await detect_velocity_candidates(
            {"limit": 10}, horizon_minutes=15,
            market=global_market, adapter=global_adapter, quote_asset="USDT",
            universe_symbols=config.GLOBAL_SYMBOLS, journal_enabled=False,
            kline_cache=cache)
    except Exception as exc:
        _status["last_error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("global_radar: tarama hatası: %s", exc)
        return 0

    # 15dk profili daha geniş ufuk taşır; 5dk önce işlenir ki erken tespit
    # avantajı korunsun, aynı sembol iki profilde de varsa cooldown ikinciyi
    # (aynı signal_type) bastırır.
    detections_seen: set[str] = set()
    processed = 0
    rows = list(scan5.get("candidates") or []) + list(scan15.get("candidates") or [])
    _status["last_candidates"] = len(rows)
    for cand in rows:
        symbol = str(cand.get("symbol") or "").upper()
        if not symbol or symbol in detections_seen:
            continue
        detections_seen.add(symbol)
        try:
            res = await global_lead_lag.handle_global_detection({
                "global_symbol": symbol,
                "signal_type": "velocity",
                "score": cand.get("velocity_score") or cand.get("score") or 0.0,
                "target_pct": cand.get("target_pct") or 2.0,
                "horizon_minutes": int(cand.get("horizon_minutes") or 5),
                "mode": cand.get("mode"),
                "price": cand.get("price"),
                "atr_pct": cand.get("atr_pct"),
            })
            if res.get("status") == "processed":
                processed += 1
            elif res.get("status") in ("rejected", "cooldown"):
                logger.debug("global_radar: tespit işlenmedi (%s): %s",
                             symbol, res.get("reason") or res.get("status"))
        except Exception as exc:
            logger.warning("global_radar: tespit işleme hatası (%s): %s", symbol, exc)
    _status["detections"] += processed
    return processed


async def global_radar_loop() -> None:
    """Sürekli Global tarama döngüsü (yalnız bayrak açıkken başlatılır)."""
    interval = max(15, int(getattr(config, "GLOBAL_SCAN_INTERVAL_SEC", 30) or 30))
    _status["started_at"] = time.time()
    logger.info("Global erken-tespit tarama döngüsü başladı (aralık %ds)", interval)

    # Bağlantı ve ilk mumların dolması için kısa bir ısınma beklemesi.
    await asyncio.sleep(20)
    while True:
        try:
            processed = await _scan_once()
            _status["scan_count"] += 1
            _status["last_scan_at"] = time.time()
            if processed:
                logger.info("global_radar: %d erken tespit → TR bildirimi/işlemine "
                            "dönüştürüldü", processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _status["last_error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("global_radar döngü hatası: %s", exc)
        await asyncio.sleep(interval)


async def connect_global_market() -> None:
    """Global akışını bağla (geçmiş mumlar + WS). Hata fırlatmaz.

    ÖNEMLİ: ``MarketData.connect`` SONSUZ bir WS süpervizör döngüsüdür; onu
    burada await etmek çağrıyı asla döndürmez (TR tarafında da ayrı bir arka
    plan görevi olarak başlatılır). Bu yüzden connect ayrı bir göreve verilir;
    geçmiş mum yüklemesi (sonlu) burada await edilir ki ilk tarama boş
    serilerle başlamasın.
    """
    from app.state import global_market

    if global_market is None:
        return
    try:
        await global_market.ensure_history(list(config.PRIORITY_TIMEFRAMES)[:3])
    except Exception as exc:
        logger.warning("global_radar: geçmiş mum yüklemesi: %s", exc)
    try:
        asyncio.create_task(global_market.connect(skip_history=True))
    except Exception as exc:
        logger.warning("global_radar: WS görevi başlatılamadı: %s", exc)
