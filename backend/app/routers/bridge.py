"""Binance TR Lead-Lag (Öncü-Artçı) Sinyal Köprüsü API Router.

Binance Global tarafından gönderilen öncü sinyalleri karşılar (/api/bridge/global-signal)
ve köprü yapılandırması ile durum izleme uç noktalarını sunar.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.api_common import require_admin as _require_admin
from app import security
from app import tr_bridge_receiver

logger = logging.getLogger("scalper.routers.bridge")
router = APIRouter(prefix="/api/bridge", tags=["bridge"])


async def _authorize_bridge_request(
    request: Request,
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
) -> None:
    """X-Bridge-Secret başlığıyla veya geçerli oturumla yetkilendirme yapar."""
    # 1. Header üzerinden gizli anahtar kontrolü
    if x_bridge_secret and await tr_bridge_receiver.verify_bridge_secret(x_bridge_secret):
        return

    # 2. Alternatif: Admin oturumu doğrulaması (web arayüzü kullanıcıları için)
    if security.request_authenticated(request.headers, request.cookies):
        user = security.request_user(request.headers, request.cookies) or {}
        if str(user.get("role") or "").lower() == "admin":
            return

    # İki yöntem de başarısız ise 401 reddi
    raise HTTPException(
        status_code=401,
        detail="Yetkisiz istek: Geçersiz veya eksik X-Bridge-Secret anahtarı ya da oturum yetkisi.",
    )


@router.post("/global-signal")
async def receive_global_signal(
    request: Request,
    payload: Dict[str, Any],
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
):
    """Binance Global'den gelen sinyali alan ana webhook uç noktası."""
    # Güvenlik başlığı doğrulaması
    if not x_bridge_secret or not await tr_bridge_receiver.verify_bridge_secret(x_bridge_secret):
        raise HTTPException(
            status_code=401,
            detail="Yetkisiz köprü isteği: Geçersiz veya eksik X-Bridge-Secret anahtarı.",
        )

    client_ip = request.client.host if request.client else None
    result = await tr_bridge_receiver.process_global_signal(payload, client_ip=client_ip)
    return result


@router.get("/status")
async def bridge_status(
    request: Request,
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
):
    """Köprü alıcısının çalışma durumu, istatistikleri ve ayarlarını döner."""
    await _authorize_bridge_request(request, x_bridge_secret)

    settings = await tr_bridge_receiver.get_receiver_settings()
    stats = tr_bridge_receiver.get_bridge_status()

    return {
        "status": "active" if settings.get("enabled") else "disabled",
        "settings": settings,
        "statistics": stats,
    }


@router.get("/history")
async def bridge_history(
    request: Request,
    limit: int = 50,
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
):
    """Son alınan sinyallerin listesini döner."""
    await _authorize_bridge_request(request, x_bridge_secret)
    clamped_limit = max(1, min(100, int(limit)))
    return {
        "ok": True,
        "history": tr_bridge_receiver.get_bridge_history(clamped_limit),
    }


@router.post("/config")
async def update_bridge_config(
    request: Request,
    payload: Dict[str, Any],
):
    """Köprü alıcı ayarlarını günceller (Yalnızca Yönetici Oturumu)."""
    _require_admin(request)
    updated = await tr_bridge_receiver.update_receiver_settings(payload)
    return {
        "ok": True,
        "settings": updated,
    }


@router.post("/test-ping")
async def test_ping(
    request: Request,
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
):
    """Yerel tanı veya entegrasyon testi için alıcıya ping paketi simüle eder."""
    await _authorize_bridge_request(request, x_bridge_secret)

    import time
    now = time.time()
    payload = {
        "source": "manual_test_ping",
        "version": "1.0",
        "timestamp": now,
        "signal_type": "ping",
        "action": "PING",
    }
    client_ip = request.client.host if request.client else None
    return await tr_bridge_receiver.process_global_signal(payload, client_ip=client_ip)


@router.get("/performance")
async def bridge_performance(
    request: Request,
    day: str = "all",
    x_bridge_secret: Optional[str] = Header(None, alias="X-Bridge-Secret"),
):
    """Global Lead-Lag işlemlerinin ve sinyallerinin başarı ve performans analizini döner."""
    await _authorize_bridge_request(request, x_bridge_secret)
    return await tr_bridge_receiver.get_bridge_performance(day=day)

