"""MA şerit BUY sinyalleri: yönetici kaydı (`GET /api/admin/ma-buy-signals`) + kullanıcı listesi (`GET /api/ma-buy/recent`).

2026-10-18 (kullanıcı isteği). Sinyaller `app/ma_buy_tracker.py` tarafından yazılır; bu uç listeyi ve özeti döndürür.
Erişim: `require_admin` (eksik oturum 401, yönetici değil 403).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query, Request

from app import notification_plan
from app import database, ma_buy_h4_scan, ma_buy_notify, ma_buy_signals, ma_buy_tracker
from app.api_common import require_admin, require_user

router = APIRouter()


@router.get("/api/admin/ma-buy-signals")
async def list_ma_buy_signals(request: Request, days: int = Query(7, ge=1, le=120), symbol: str = "", rule: str = "",
                              status: str = "", timeframe: str = "", limit: int = Query(500, ge=1, le=2000)):
    require_admin(request)
    since_ms = int((time.time() - days * 86400) * 1000)
    status_f = status if status in {"open", "done", "no_data"} else None
    rows = await database.list_ma_buy_signals(since_ms, symbol=symbol.strip() or None, status=status_f, limit=5000)
    if timeframe in ma_buy_tracker.SUPPORTED_TF_MS:
        rows = [r for r in rows if r.get("timeframe") == timeframe]
    if rule in ma_buy_signals.ALL_RULES:
        rows = [r for r in rows if rule in str(r.get("rules") or "").split(",")]
    items = [ma_buy_tracker.public_item(r) for r in rows]
    return {"ok": True, "days": days, "total": len(items), "items": items[:limit],
            "summary": ma_buy_tracker.summarize(rows),
            "tracker": ma_buy_tracker.status_snapshot()}


@router.get("/api/ma-buy/recent")
async def recent_ma_buy_notifications(request: Request, hours: int = Query(12, ge=1, le=72),
                                      limit: int = Query(30, ge=1, le=100)):
    """Push'u gönderilmiş son MA BUY sinyalleri (ana sayfa + radar "MA kesişim" listesi; Alım yap düğmesiyle).

    Oturum açmış her kullanıcı görür (bildirimler zaten herkese push edilir). Salt okuma."""
    require_user(request)
    rows = await database.list_ma_buy_notified(time.time() - hours * 3600, limit=limit)
    items = []
    for r in rows:
        item = ma_buy_tracker.public_item(r)
        # Kart (ana sayfa) durum satırı hedef + ufka göre hesaplanır: bildirimdeki/paper'daki aynı değerler.
        item["target_pct"] = ma_buy_notify.target_pct(str(r.get("timeframe") or ""))
        item["horizon_minutes"] = ma_buy_notify.HORIZON_MIN
        items.append(item)
    await notification_plan.enrich_rows_with_plans(items, notification_plan.ma_buy_row_plan_key)
    return {"ok": True, "hours": hours, "items": items}


@router.get("/api/ma-buy/h4-crosses")
async def h4_crosses(request: Request, hours: int = Query(24, ge=4, le=72), refresh: int = Query(0, ge=0, le=1)):
    """Radar > "H4 kesişimleri": son `hours` saatte H4'te MA 7/20/99 kesişimi olan likit TRY çiftleri (2026-10-21).

    Önbellekten döner; bayatsa (ya da `refresh=1`) tazeleme arka planda başlar ve `refreshing: true` işaretlenir —
    istemci kısa aralıkla yeniden sorar. Kural `ma_buy_profiles.profile("4h")` ile izleyiciyle aynıdır."""
    require_user(request)
    snap = await ma_buy_h4_scan.snapshot(hours=hours, force=bool(refresh))
    return {"ok": True, **snap}
