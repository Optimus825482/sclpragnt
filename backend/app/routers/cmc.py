"""CoinMarketCap anahtar/kota ve radar bağlamı rotaları.

NEDEN: CMC anahtarı ayarlar ekranından girilir, aynı ekranda kalan kredi
görünür; radar katmanı piyasa geneli bağlamı bu rotadan okur.

GÜVENLİK
- Tüm rotalar varsayılan oturum kapısına tabidir (public_paths'e eklenmedi).
- Anahtar hiçbir yanıtta tam dönmez; yalnız maskeli son 4 hane.
- Kaydetmeden önce anahtar `/v1/key/info` ile doğrulanır; geçersiz anahtar
  kaydedilmez (Binance anahtar doğrulama deseniyle aynı).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app import cmc_client
from app.api_common import rate_limit

logger = logging.getLogger("scalper.cmc_routes")

router = APIRouter()


def _limit(name: str, rate: float = 0.2, burst: float = 3) -> None:
    if not rate_limit(name, rate_per_sec=rate, burst=burst):
        raise HTTPException(status_code=429, detail="Çok sık istek; biraz bekleyin.")


@router.get("/api/cmc/settings")
async def get_cmc_settings(request: Request):
    """Anahtar durumu + kota özeti (panel için)."""
    _limit("cmc_settings_get", rate=0.5, burst=5)
    status = await cmc_client.key_status()
    quota = await cmc_client.quota() if status["configured"] else None
    return {"ok": True, **status, "quota": quota}


@router.post("/api/cmc/settings")
async def save_cmc_settings(request: Request):
    """Anahtarı doğrula ve şifreli kaydet."""
    _limit("cmc_settings_post", rate=0.1, burst=2)
    body = await request.json()
    key = str((body or {}).get("api_key") or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail="API anahtarı boş olamaz.")

    probe = await cmc_client.validate_key(key)
    verified = bool(probe["ok"])
    if not verified:
        # Ağ hatası (status 0) ile GEÇERSİZ ANAHTARI ayır: konteyner dışa
        # çıkamıyorsa kullanıcı anahtarı hiç kaydedemiyordu. Ağ hatasında
        # kaydedip "doğrulanamadı" işaretliyoruz; 401/403 ise gerçekten kötü
        # anahtardır ve kaydedilmez.
        if int(probe.get("status") or 0) != 0:
            raise HTTPException(status_code=422, detail=f"Anahtar doğrulanamadı: {probe['error']}")

    try:
        await cmc_client.save_api_key(key, verified=verified)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    status = await cmc_client.key_status()
    return {
        "ok": True,
        **status,
        "verified": verified,
        "plan": probe.get("plan") or {},
        "warning": None if verified else ("Anahtar kaydedildi ama CMC'ye ulaşılamadı "
                                          f"({probe.get('error')}). Sunucu dışa çıkışını kontrol edin."),
    }


@router.delete("/api/cmc/settings")
async def delete_cmc_settings(request: Request):
    _limit("cmc_settings_delete", rate=0.1, burst=2)
    await cmc_client.delete_api_key()
    return {"ok": True, "configured": False}


@router.get("/api/cmc/quota")
async def cmc_quota(request: Request, force: bool = False):
    """Kalan kredi/plan bilgisi. `force=true` önbelleği atlar (elle yenileme)."""
    _limit("cmc_quota", rate=0.3, burst=4)
    if force:
        await cmc_client.key_info(force=True)
    return {"ok": True, **(await cmc_client.quota())}


@router.get("/api/cmc/brief")
async def cmc_brief(request: Request, force: bool = False):
    """Radar için piyasa geneli bağlam (5 dk önbellek)."""
    _limit("cmc_brief", rate=0.3, burst=4)
    payload = await cmc_client.brief(force=force)
    return {"ok": True, **payload}
