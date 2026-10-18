"""Yönetici: Radar tarama günlüğü (`GET /api/admin/radar-scan-log`). Yalnız okuma; bellek içi tampondan döner.

2026-10-18 (kullanıcı isteği). Günlüğü `monitoring._run_scan` her tur sonunda `app/radar_scan_log.py` ile yazar.
Erişim: `require_admin` (eksik oturum 401, yönetici değil 403).
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app import radar_scan_log
from app.api_common import require_admin

router = APIRouter()


@router.get("/api/admin/radar-scan-log")
async def radar_scan_log_view(request: Request, limit: int = Query(10, ge=1, le=100), symbol: str = "", status: str = ""):
    require_admin(request)
    return radar_scan_log.get_log(limit=limit, symbol=symbol, status=status)
