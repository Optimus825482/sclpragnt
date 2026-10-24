"""N7 TARAMA uçları: `POST /api/radar/n7-scan/run` (başlat) ve `GET /api/radar/n7-scan` (durum + son sonuç).

2026-10-24 (kullanıcı isteği). İş mantığı `app/n7_scan_job.py`; burada yalnız oturum kapısı, gövde ayrıştırma ve
HTTP kodları (çalışıyorken ikinci başlatma → 409). Erişim: `require_user` (oturum açmış her kullanıcı; eksik oturum 401).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import n7_scan_job
from app.api_common import log_user_action, require_user

router = APIRouter()


class RunBody(BaseModel):
    top: int = n7_scan_job.DEFAULT_TOP


@router.post("/api/radar/n7-scan/run")
async def n7_scan_run(request: Request, body: RunBody | None = None):
    user = require_user(request)
    top = n7_scan_job.clamp_top(body.top if body else n7_scan_job.DEFAULT_TOP)
    try:
        out = n7_scan_job.start(top)
    except n7_scan_job.AlreadyRunning:
        raise HTTPException(status_code=409, detail="Tarama zaten çalışıyor")
    await log_user_action(user.get("username"), user.get("role"), "monitoring", "n7_scan_run",
                          details={"top": top}, request=request)
    return out


@router.get("/api/radar/n7-scan")
async def n7_scan_status(request: Request):
    require_user(request)
    return n7_scan_job.snapshot()
