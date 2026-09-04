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
    "notified_symbols": {},       # symbol -> son bildirim zamanı (epoch)
    "watchlist_seen_at": {},      # symbol -> izlemeye alınma zamanı
    "history": [],                # son bildirim geçmişi (yeni -> eski)
    "pending_targets": {},        # symbol -> {"expected": float, "horizon_minutes": int, "set_at": epoch}
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
    """Eşikleri geçen adaylar için bildirim üret ve web push gönder.

    Aynı sembol için sonuçlanmamış (BEKLİYOR) bildirim varsa yeni bildirim
    oluşturulmaz; mevcut bildirim güncellenir (hedef, skor, fiyat).
    Sadece önceki bildirim sonuçlanmışsa (TAMAMEN/BASARISIZ) veya ufuk süresi
    dolmuşsa yeni bildirim oluşturulur.
    """
    if not settings.get("enabled", True):
        return []
    min_score = settings.get("min_score", 1.0)
    min_target_pct = settings.get("min_target_pct", 2.0)
    quiet = _in_quiet_hours(settings)
    now = time.time()
    notified = []
    update_entries = []  # Güncellenecek mevcut bildirimler
    new_entries = []     # Yeni bildirimler
    for c in candidates_list:
        sym = c.get("symbol", "")
        score = float(c.get("velocity_score", 0) or 0)
        target = float(c.get("target_pct") or 2.0)
        if not sym or score < min_score or target < min_target_pct:
            continue
        # Bu sembol için sonuçlanmamış bildirim var mı kontrol et
        existing_pending = await database.get_pending_monitoring_notification(sym)
        if existing_pending:
            # Mevcut BEKLİYOR bildirimi güncelle
            await database.update_monitoring_notification(
                existing_pending["id"],
                score=score,
                target_pct=target,
                price=float(c.get("price", 0) or 0),
                expected_price=float(c.get("price", 0) or 0) * (1 + target / 100),
                detected_at=now,
                horizon_minutes=int(c.get("horizon_minutes", 5) or 5),
                mode=c.get("mode"),
            )
            # Eski kayitlar kalir - sinyal tarihcesi icin
            # Bildirim olarak da ekle (push için)
            notif = _build_notification(sym, c, settings)
            notif["id"] = existing_pending["id"]
            notif["updated"] = True
            update_entries.append(notif)
            notified.append(notif)
            continue
        # Kısa vadeli soğama
        last_sent = _monitoring_state["notified_symbols"].get(sym)
        if last_sent and now - last_sent < NOTIFY_COOLDOWN_SEC:
            continue
        # Beklenen fiyata ulaşana kadar aynı sembolü tekrar bildirme
        pending = _monitoring_state["pending_targets"].get(sym)
        if pending:
            horizon_ms = int(pending.get("horizon_minutes", 5) + 2) * 60
            if now - float(pending.get("set_at", 0)) < horizon_ms:
                continue
            _monitoring_state["pending_targets"].pop(sym, None)
        notif = _build_notification(sym, c, settings)
        notif["updated"] = False
        new_entries.append(notif)
        notified.append(notif)
        _monitoring_state["notified_symbols"][sym] = now
        expected_price = float(notif.get("expected_price") or 0)
        horizon_minutes = int(c.get("horizon_minutes") or 5)
        if expected_price > 0:
            _monitoring_state["pending_targets"][sym] = {
                "expected": expected_price,
                "horizon_minutes": horizon_minutes,
                "set_at": now,
            }
        if len(_monitoring_state["notified_symbols"]) > 500:
            for k in sorted(_monitoring_state["notified_symbols"], key=_monitoring_state["notified_symbols"].get)[:-250]:
                _monitoring_state["notified_symbols"].pop(k, None)
    # Yeni bildirimleri DB'ye kaydet
    if new_entries:
        await database.save_monitoring_notifications(new_entries)
    # Push bildirimleri
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
        try:
            await ws_manager.broadcast({"type": "monitoring_alert", "data": notified[-1]})
        except Exception as exc:
            logger.warning("Monitoring WS broadcast hatasi: %s", exc)
        _monitoring_state["history"] = (notified + _monitoring_state["history"])[:HISTORY_LIMIT]
    return notified
def _check_pending_targets():
    """Beklenen fiyata ulaşan sembolleri tespit et ve pending listesinden çıkar.

    Her tarama turunda çağrılır: aday listesindeki sembollerin anlık fiyatı,
    kayıtlı expected_price'a eşit veya üstüyse hedefe ulaşılmış sayılır.
    Ufuk süresi + 2 mk tolerans dolduysa da temizlenir (timeout).
    """
    pending = _monitoring_state.get("pending_targets")
    if not pending:
        return
    now = time.time()
    resolved = []
    for sym, info in list(pending.items()):
        horizon_ms = int(info.get("horizon_minutes", 5) + 2) * 60
        set_at = float(info.get("set_at", 0))
        expired = now - set_at >= horizon_ms
        price = None
        try:
            ticker = market.get_ticker(sym) if market else None
            price = float(ticker.get("last_price") or 0) if ticker else None
        except Exception:
            price = None
        expected = float(info.get("expected") or 0)
        hit = price is not None and price > 0 and expected > 0 and price >= expected
        if expired or hit:
            resolved.append(sym)
    for sym in resolved:
        _monitoring_state["pending_targets"].pop(sym, None)


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

    # Beklenen fiyata ulaşan veya süresi dolan sembolleri serbest bırak
    _check_pending_targets()

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


@router.get("/api/reports/notifications")
async def report_notifications(limit: int = 200, day: str = None):
    """Radar bildirim raporu - gercek kapannis M1 olcmueye dayali basari.
    day: YYYY-MM-DD formatinda gun filtresi (opsiyonel).
    """
    limit = max(1, min(int(limit), 500))
    rows = await database.get_monitoring_velocity_matches(limit=limit, day=day)
    now = time.time()
    result = []
    for row in rows:
        symbol = row.get("symbol")
        price = float(row.get("price") or 0)
        target_pct = float(row.get("target_pct") or 0)
        detected_at = float(row.get("detected_at") or 0)
        mfe = row.get("mfe_pct")
        mfe_pct = float(mfe) if mfe is not None else None
        touched = row.get("touched_target")
        candidate_status = str(row.get("candidate_status") or "")
        horizon = int(row.get("horizon_minutes") or 0)
        window_closed = bool(detected_at and horizon and (now - detected_at) >= (horizon + 2) * 60)
        if candidate_status == "evaluated" and mfe_pct is not None:
            if touched:
                status = "TAMAMEN BASARILI"
            elif target_pct > 0 and mfe_pct >= target_pct * 0.5:
                status = "BASARILI"
            elif mfe_pct > 0:
                status = "KISMI"
            else:
                status = "BASARISIZ"
        elif candidate_status == "pending" and not window_closed:
            status = "BEKLIYOR"
        else:
            status = "OLCULEMEDI" if window_closed else "BEKLIYOR"
        result.append({
            "id": row.get("id"),
            "symbol": symbol,
            "message": row.get("message"),
            "title": row.get("title"),
            "score": row.get("score"),
            "target_pct": target_pct,
            "price": price,
            "expected_price": row.get("expected_price"),
            "mfe_pct": mfe_pct,
            "touched_target": touched,
            "status": status,
            "mode": row.get("mode"),
            "horizon_minutes": horizon,
            "detected_at": detected_at,
            "sent_via_push": row.get("sent_via_push"),
            "candidate_id": row.get("candidate_id"),
            "ml_hit_probability": row.get("ml_hit_probability"),
        })
    counts = {"TAMAMEN BASARILI": 0, "BASARILI": 0, "KISMI": 0,
              "BASARISIZ": 0, "BEKLIYOR": 0, "OLCULEMEDI": 0}
    for item in result:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    evaluated = sum(counts[k] for k in ("TAMAMEN BASARILI", "BASARILI", "KISMI", "BASARISIZ"))
    success = counts["TAMAMEN BASARILI"] + counts["BASARILI"]
    day_breakdown = {"counts": counts, "evaluated": evaluated,
                    "success_count": success,
                    "success_rate": (success / evaluated * 100) if evaluated else None}
    all_rows = await database.get_monitoring_velocity_matches(limit=1000, day=None)
    all_evaluated = 0
    all_success = 0
    for r in all_rows:
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tch = r.get("touched_target")
        cand_st = str(r.get("candidate_status") or "")
        tgt = float(r.get("target_pct") or 0)
        if cand_st == "evaluated" and mfe_f is not None:
            all_evaluated += 1
            if tch or mfe_f >= tgt * 0.5:
                all_success += 1
    overall_breakdown = {
        "evaluated": all_evaluated,
        "success_count": all_success,
        "success_rate": (all_success / all_evaluated * 100) if all_evaluated else None,
    }
    return {"paper_only": True, "notifications": result, "total": len(result),
            "breakdown": day_breakdown, "overall": overall_breakdown}

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