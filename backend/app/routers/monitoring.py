"""Monitoring page API: continuous scan for high-potential symbols with push notifications."""
import asyncio
import time
import logging
from fastapi import APIRouter

from app.config import config
from app import database
from app.state import market
from app.binance_tr_public import klines as fetch_klines, top_gainers
from app.routers.velocity import detect_velocity_candidates
from app.alerting import deliver_web_push

logger = logging.getLogger("scalper.monitoring")
router = APIRouter()

# Monitoring state
_monitoring_state = {
    "last_scan_at": None,
    "last_candidates": [],
    "last_watchlist": [],
    "scan_count": 0,
    "notified_symbols": set(),
}


async def get_user_notification_settings() -> dict:
    """Kullanıcı bildirim ayarlarını DB'den oku."""
    try:
        settings_json = await database.get_llm_setting("monitoring_notification_settings", "{}")
        import json
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
async def update_monitoring_settings(payload: dict):
    """Bildirim ayarlarını güncelle ve DB'ye kaydet."""
    import json
    settings = {
        "enabled": bool(payload.get("enabled", True)),
        "min_score": float(payload.get("min_score", 1.0)),
        "min_target_pct": float(payload.get("min_target_pct", 2.0)),
        "quiet_hours_start": payload.get("quiet_hours_start", None),
        "quiet_hours_end": payload.get("quiet_hours_end", None),
    }
    await database.set_llm_setting("monitoring_notification_settings", json.dumps(settings))
    return {"paper_only": True, "ok": True, **settings}


@router.get("/api/monitoring/scan")
async def monitoring_scan():
    """Run a fresh scan for 5m and 15m velocity candidates."""
    try:
        # Bildirim ayarlarını kontrol et
        settings = await get_user_notification_settings()
        notifications_enabled = settings.get("enabled", True)
        min_score = settings.get("min_score", 1.0)
        min_target_pct = settings.get("min_target_pct", 2.0)
        
        scan5 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=5)
        scan15 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=15)
        
        candidates5 = scan5.get("candidates", [])
        candidates15 = scan15.get("candidates", [])
        watchlist5 = scan5.get("watchlist", [])
        watchlist15 = scan15.get("watchlist", [])
        
        # Merge candidates from both horizons, deduplicate by symbol
        all_candidates = {}
        for c in candidates5 + candidates15:
            sym = c.get("symbol", "")
            if sym not in all_candidates or c.get("velocity_score", 0) > all_candidates[sym].get("velocity_score", 0):
                all_candidates[sym] = c
        
        all_watchlist = {}
        for w in watchlist5 + watchlist15:
            sym = w.get("symbol", "")
            if sym not in all_watchlist or w.get("velocity_score", 0) > all_watchlist[sym].get("velocity_score", 0):
                all_watchlist[sym] = w
        
        # Remove candidates from watchlist (they already passed)
        for sym in all_candidates:
            all_watchlist.pop(sym, None)
        
        candidates_list = sorted(all_candidates.values(), key=lambda x: x.get("velocity_score", 0), reverse=True)
        watchlist_list = sorted(all_watchlist.values(), key=lambda x: x.get("velocity_score", 0), reverse=True)
        
        # Ayarlara göre filtrele ve bildirim gönder
        new_notifications = []
        if notifications_enabled:
            for c in candidates_list:
                sym = c.get("symbol", "")
                score = c.get("velocity_score", 0)
                target = c.get("target_pct", 2.0)
                
                # Skor ve hedef eşiğini kontrol et
                if score < min_score or target < min_target_pct:
                    continue
                
                # Sadece yeni semboller için bildirim gönder
                if sym not in _monitoring_state["notified_symbols"]:
                    _monitoring_state["notified_symbols"].add(sym)
                    new_notifications.append(c)
            
            # Push notification gönder
            if new_notifications:
                for notif in new_notifications:
                    sym = notif.get("symbol", "")
                    score = notif.get("velocity_score", 0)
                    target = notif.get("target_pct", 2.0)
                    price = notif.get("price", 0)
                    expected_price = price * (1 + target / 100) if price > 0 else 0
                    ticker = market.get_ticker(sym)
                    current_price = float(ticker.get("last_price", price)) if ticker else price
                    message = (
                        f"🎯 {sym} | Skor: {score:.1f} | "
                        f"Hedef: +{target}% | "
                        f"Anlık: {current_price:.6f} TRY | "
                        f"Beklenen: {expected_price:.6f} TRY"
                    )
                    try:
                        await deliver_web_push(message)
                    except Exception as exc:
                        logger.warning("Monitoring push failed for %s: %s", sym, exc)
        
        _monitoring_state["last_scan_at"] = time.time()
        _monitoring_state["last_candidates"] = candidates_list
        _monitoring_state["last_watchlist"] = watchlist_list
        _monitoring_state["scan_count"] += 1
        
        return {
            "paper_only": True,
            "scan_at": _monitoring_state["last_scan_at"],
            "scan_count": _monitoring_state["scan_count"],
            "candidates": candidates_list,
            "watchlist": watchlist_list,
            "new_notifications": len(new_notifications),
            "settings": settings,
        }
    except Exception as exc:
        logger.exception("Monitoring scan failed: %s", exc)
        return {"paper_only": True, "error": str(exc), "candidates": [], "watchlist": []}


@router.get("/api/monitoring/state")
async def monitoring_state():
    """Get current monitoring state (last scan results)."""
    return {
        "paper_only": True,
        "last_scan_at": _monitoring_state["last_scan_at"],
        "scan_count": _monitoring_state["scan_count"],
        "candidates": _monitoring_state["last_candidates"],
        "watchlist": _monitoring_state["last_watchlist"],
    }


@router.post("/api/monitoring/reset-notifications")
async def reset_monitoring_notifications():
    """Clear notified symbols list (allows re-notification)."""
    _monitoring_state["notified_symbols"].clear()
    return {"ok": True, "message": "Bildirim sıfırlandı"}
