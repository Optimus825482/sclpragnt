"""Yönetici: MA şerit BUY sinyal kaydı (`GET /api/admin/ma-buy-signals`). Yalnız okuma; emir/karar YOK.

2026-10-18 (kullanıcı isteği). Sinyaller `app/ma_buy_tracker.py` tarafından yazılır; bu uç listeyi ve özeti döndürür.
Erişim: `require_admin` (eksik oturum 401, yönetici değil 403).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query, Request

from app import database, ma_buy_signals, ma_buy_tracker
from app.api_common import require_admin

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
