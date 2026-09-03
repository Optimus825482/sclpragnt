"""Monitoring page API: continuous scan for high-potential symbols with push notifications."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request

from app.config import config
from app import database
from app.api_common import log_user_action
from app.state import market
from app.routers.velocity import detect_velocity_candidates
from app.alerting import deliver_web_push
from app.ws_runtime import ws_manager

logger = logging.getLogger("scalper.monitoring")
router = APIRouter()

# Monitoring state
_monitoring_state = {
    "last_scan_at": None,
    "last_candidates": [],
    "last_watchlist": [],
    "scan_count": 0,
    "notified_symbols": {},       # symbol -> ilk bildirim zamanı (epoch)
    "watchlist_seen_at": {},      # symbol -> izlemeye alınma zamanı
    "history": [],                # son bildirim geçmişi (yeni -> eski)
}

# Sunucu tarafı döngü aralıkları: genel tarama 60 sn; izleme listesindeki
# semboller her turda zorunlu havuza eklenip yeniden analiz edilir ve aday
# kümesi değiştiyse kısa aralıkla yeniden değerlendirilir. Böylece PWA kapalı
# olsa bile tarama ve bildirim sunucudan devam eder.
SCAN_INTERVAL_SEC = 60.0
WATCHLIST_RESCAN_SEC = 30.0
HISTORY_LIMIT = 60
NOTIFY_COOLDOWN_SEC = 300.0  # aynı sembol için tekrar bildirim engeli (5 dk)
_loop_task = None


def _in_quiet_hours(settings) -> bool:
    """Sessiz saat aralığı kontrolü; gece yarısı üzerinden sarmalı aralık destekler."""
    start, end = settings.get("quiet_hours_start"), settings.get("quiet_hours_end")
    if not start or not end:
        return False
    try:
        h1, m1 = int(str(start).split(":")[0]), int(str(start).split(":")[1])
        h2, m2 = int(str(end).split(":")[0]), int(str(end).split(":")[1])
    except (ValueError, IndexError):
        return False
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    a = h1 * 60 + m1
    b = h2 * 60 + m2
    if a == b:
        return False
    return (cur >= a and cur < b) if a < b else (cur >= a or cur < b)


async def get_user_notification_settings() -> dict:
    """Kullanıcı bildirim ayarlarını DB'den oku."""
    try:
        settings_json = await database.get_llm_setting("monitoring_notification_settings", "{}")
        settings = json.loads(settings_json or "{}")
        return {
            "enabled": settings.get("enabled", True),
            "min_score": float(settings.get("min_score", 1.0)),
            "min_target_pct": float(settings.get("min_target_pct", 2.0)),
            "quiet_hours_start": settings.get("quiet_hours_start", None),
            "quiet_hours_end": settings.get("quiet_hours_end", None),
        }
    except Exception:
        return {"enabled": True, "min_score": 1.0, "min_target_pct": 2.0, "quiet_hours_start": None, "quiet_hours_end": None}


@router.get("/api/monitoring/settings")
async def get_monitoring_settings():
    """Bildirim ayarlarını döndür."""
    settings = await get_user_notification_settings()
    return {"paper_only": True, **settings}


@router.put("/api/monitoring/settings")
async def update_monitoring_settings(payload: dict, request: Request):
    """Bildirim ayarlarını güncelle ve DB'ye kaydet."""
    settings = {
        "enabled": bool(payload.get("enabled", True)),
        "min_score": float(payload.get("min_score", 1.0)),
        "min_target_pct": float(payload.get("min_target_pct", 2.0)),
        "quiet_hours_start": payload.get("quiet_hours_start", None),
        "quiet_hours_end": payload.get("quiet_hours_end", None),
    }
    await database.set_llm_setting("monitoring_notification_settings", json.dumps(settings))
    await log_user_action(None, None, "monitoring", "MONITORING_SETTINGS_UPDATE",
                          details={"settings": {k: v for k, v in settings.items() if k != "enabled"}},
                          request=request)
    return {"paper_only": True, "ok": True, **settings}


def _build_notification(sym, c, settings) -> dict:
    """Zengin bildirim içeriği: sembol, tespit zamanı, %potansiyel, anlık ve beklenen fiyat."""
    score = float(c.get("velocity_score", 0) or 0)
    target = float(c.get("target_pct", 2.0) or 0)
    price = float(c.get("price", 0) or 0)
    ticker = market.get_ticker(sym)
    current_price = float(ticker.get("last_price", price)) if ticker else price
    if current_price <= 0:
        current_price = price
    expected_price = current_price * (1 + target / 100) if current_price > 0 else 0.0
    detected_at = time.time()
    horizon = int(c.get("horizon_minutes", 5) or 5)
    message = (
        f"🎯 {sym} | Skor: {score:.1f} | Potansiyel: +%{target:g} ({horizon}dk) | "
        f"Anlık: {current_price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"
    )
    return {
        "symbol": sym,
        "message": message,
        "title": f"🎯 {sym} +%{target:g} potansiyel",
        "url": f"/charts?symbol={sym}",
        "tag": f"monitoring-{sym}",
        "detected_at": detected_at,
        "score": score,
        "target_pct": target,
        "price": current_price,
        "expected_price": expected_price,
        "horizon_minutes": horizon,
        "mode": c.get("mode"),
        "horizon": horizon,
        "settings_applied": {
            "min_score": settings.get("min_score"),
            "min_target_pct": settings.get("min_target_pct"),
        },
    }


async def _record_history(entries):
    """Bildirim geçmişini DB'ye kaydet (uygulama kapalıyken gönderilenler dahil)."""
    try:
        await database.save_monitoring_notifications(entries)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi kaydedilemedi: %s", exc)


async def _notify(candidates_list, settings) -> list:
    """Eşikleri geçen YENİ adaylar için bildirim üret ve web push gönder.

    Aynı sembol için 5 dk soğuma uygulanır; sessiz saatlerde push gönderilmez
    ama aday yine kayda alınır.
    """
    if not settings.get("enabled", True):
        return []
    min_score = settings.get("min_score", 1.0)
    min_target_pct = settings.get("min_target_pct", 2.0)
    quiet = _in_quiet_hours(settings)
    now = time.time()
    notified = []
    for c in candidates_list:
        sym = c.get("symbol", "")
        score = float(c.get("velocity_score", 0) or 0)
        target = float(c.get("target_pct", 2.0) or 0)
        if not sym or score < min_score or target < min_target_pct:
            continue
        last_sent = _monitoring_state["notified_symbols"].get(sym)
        if last_sent and now - last_sent < NOTIFY_COOLDOWN_SEC:
            continue
        notif = _build_notification(sym, c, settings)
        notif["quiet_hours"] = quiet
        notified.append(notif)
        _monitoring_state["notified_symbols"][sym] = now
        if len(_monitoring_state["notified_symbols"]) > 500:
            # Eski kayıtları kırp (sözlük büyümesin)
            for k in sorted(_monitoring_state["notified_symbols"], key=_monitoring_state["notified_symbols"].get)[:-250]:
                _monitoring_state["notified_symbols"].pop(k, None)
    if notified and not quiet:
        for notif in notified:
            try:
                await deliver_web_push(
                    notif["message"],
                    title=notif["title"],
                    url=notif["url"],
                    tag=notif["tag"],
                    extra={
                        "symbol": notif["symbol"],
                        "score": notif["score"],
                        "target_pct": notif["target_pct"],
                        "price": notif["price"],
                        "expected_price": notif["expected_price"],
                        "detected_at": notif["detected_at"],
                        "horizon_minutes": notif["horizon_minutes"],
                        "source": "monitoring",
                    },
                )
            except Exception as exc:
                logger.warning("Monitoring push failed for %s: %s", notif["symbol"], exc)
    elif notified and quiet:
        logger.info("Monitoring: sessiz saatlerde %d bildirim ertelendi (push yok)", len(notified))
    if notified:
        # Uygulama açıkken radar bildirimini uygulama içi onay modalı + ses ile
        # göster: sessiz saatlerde push atlanır ama WS mesajı yine de iletilir.
        try:
            await ws_manager.broadcast({"type": "monitoring_alert", "data": notified[-1]})
        except Exception as exc:
            logger.warning("Monitoring WS broadcast hatası: %s", exc)
        _monitoring_state["history"] = (notified + _monitoring_state["history"])[:HISTORY_LIMIT]
        await _record_history(notified)
    return notified


async def _run_scan() -> dict:
    """Tek tarama turu: 5dk + 15dk velocity taramalarını birleştirir.

    İzleme listesindeki semboller her turda top-gainer havuzuna zorunlu olarak
    eklenir (extra_symbols) — böylece izleme listesi "daha sık analiz edilen"
    listede kalır ve terfi/düşme kararı her turda tazelenir.
    """
    watch_symbols = sorted({w.get("symbol") for w in (_monitoring_state["last_watchlist"] or []) if w.get("symbol")})
    scan5 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=5, extra_symbols=watch_symbols)
    scan15 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=15, extra_symbols=watch_symbols)

    candidates5 = scan5.get("candidates", [])
    candidates15 = scan15.get("candidates", [])
    watchlist5 = scan5.get("watchlist", [])
    watchlist15 = scan15.get("watchlist", [])

    # Birleştir: sembol başına en yüksek skorlu kayıt kalır
    all_candidates = {}
    for c in candidates5 + candidates15:
        sym = c.get("symbol", "")
        if sym and (sym not in all_candidates or c.get("velocity_score", 0) > all_candidates[sym].get("velocity_score", 0)):
            all_candidates[sym] = c

    all_watchlist = {}
    for w in watchlist5 + watchlist15:
        sym = w.get("symbol", "")
        if sym and (sym not in all_watchlist or w.get("velocity_score", 0) > all_watchlist[sym].get("velocity_score", 0)):
            all_watchlist[sym] = w

    # Aday olanlar izleme listesinden çıkar (zaten geçti)
    for sym in all_candidates:
        all_watchlist.pop(sym, None)
        _monitoring_state["watchlist_seen_at"].pop(sym, None)

    # İzlemeye alınanları işaretle
    now = time.time()
    for sym in all_watchlist:
        _monitoring_state["watchlist_seen_at"].setdefault(sym, now)

    candidates_list = sorted(all_candidates.values(), key=lambda x: x.get("velocity_score", 0), reverse=True)
    watchlist_list = sorted(all_watchlist.values(), key=lambda x: x.get("velocity_score", 0), reverse=True)

    settings = await get_user_notification_settings()
    new_notifications = await _notify(candidates_list, settings)

    _monitoring_state["last_scan_at"] = now
    _monitoring_state["last_candidates"] = candidates_list
    _monitoring_state["last_watchlist"] = watchlist_list
    _monitoring_state["scan_count"] += 1
    return {
        "settings": settings,
        "candidates": candidates_list,
        "watchlist": watchlist_list,
        "new_notifications": new_notifications,
    }


@router.get("/api/monitoring/scan")
async def monitoring_scan():
    """Run a fresh scan for 5m and 15m velocity candidates (manual/UI tetiklemeli)."""
    try:
        result = await _run_scan()
        return {
            "paper_only": True,
            "scan_at": _monitoring_state["last_scan_at"],
            "scan_count": _monitoring_state["scan_count"],
            "candidates": result["candidates"],
            "watchlist": result["watchlist"],
            "new_notifications": len(result["new_notifications"]),
            "notifications": result["new_notifications"],
            "history": _monitoring_state["history"][:20],
            "settings": result["settings"],
            "loop_active": _loop_task is not None and not _loop_task.done(),
        }
    except Exception as exc:
        logger.exception("Monitoring scan failed: %s", exc)
        return {"paper_only": True, "error": str(exc), "candidates": [], "watchlist": []}


@router.get("/api/monitoring/state")
async def monitoring_state():
    """Get current monitoring state (last scan results + notification history)."""
    settings = await get_user_notification_settings()
    return {
        "paper_only": True,
        "last_scan_at": _monitoring_state["last_scan_at"],
        "scan_count": _monitoring_state["scan_count"],
        "candidates": _monitoring_state["last_candidates"],
        "watchlist": _monitoring_state["last_watchlist"],
        "history": _monitoring_state["history"][:20],
        "settings": settings,
        "loop_active": _loop_task is not None and not _loop_task.done(),
        "next_scan_in_sec": None,
    }


@router.post("/api/monitoring/reset-notifications")
async def reset_monitoring_notifications(request: Request):
    """Clear notified symbols list (allows re-notification)."""
    _monitoring_state["notified_symbols"].clear()
    await log_user_action(None, None, "monitoring", "MONITORING_NOTIFICATIONS_RESET",
                          details={}, request=request)
    return {"ok": True, "message": "Bildirim sıfırlandı"}


@router.get("/api/monitoring/notifications")
async def monitoring_notification_history():
    """Son bildirim geçmişi: kalıcı DB kaydı + oturum içi liste."""
    try:
        persisted = await database.list_monitoring_notifications(limit=50)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi okunamadı: %s", exc)
        persisted = []
    return {"paper_only": True, "history": persisted, "session": _monitoring_state["history"][:20]}


async def monitoring_background_loop():
    """Sunucu tarafı sürekli tarama: PWA kapalıyken bile taramayı ve push
    bildirimlerini sürdürür. İzleme listesi her turda yeniden analiz edilir;
    yeni aday çıktığında kısa aralıkla tekrar değerlendirilir."""
    logger.info("Monitoring arka plan taraması başladı (tur=%ss, izleme=%ss)", SCAN_INTERVAL_SEC, WATCHLIST_RESCAN_SEC)
    # Başlangıçta market verisi hazır olsun diye ilk tura küçük gecikme
    await asyncio.sleep(20)
    while True:
        try:
            await _run_scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring loop turu başarısız: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL_SEC)
            continue
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def start_monitoring_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat (idempotent)."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(monitoring_background_loop(), name="monitoring-scan-loop")
    return True


def stop_monitoring_loop():
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _loop_task = None
