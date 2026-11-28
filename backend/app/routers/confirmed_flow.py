"""CVD onay katmanı router'ı.

Endpoints:
- GET /api/confirmed-flow               : izlenen sembollerin özet listesi
- GET /api/confirmed-flow/{symbol}      : tek sembol canlı + kesin birleşik okuma
- GET /api/confirmed-flow/{symbol}/hours: son N kesinleşmiş saat (ham)
"""

from fastapi import APIRouter, Query

from app.confirmed_flow import confirm_flow_snapshot, load_confirmed, scan_confirmed_flow

router = APIRouter(prefix="/api/confirmed-flow", tags=["confirmed-flow"])


@router.get("")
async def get_scan():
    """Tüm izlenen sembolleri hükme göre sıralı döner."""
    return await scan_confirmed_flow()


@router.get("/{symbol}")
async def get_symbol(symbol: str, hours: int = Query(3, ge=1, le=24)):
    """Tek sembol: canlı tape okuması + son kesin saatler + hüküm/gerekçeler."""
    snap = await confirm_flow_snapshot(symbol.upper())
    snap["confirmed_hours"] = snap["confirmed_hours"][-hours:]
    return snap


@router.get("/{symbol}/hours")
async def get_hours(symbol: str, limit: int = Query(24, ge=1, le=200)):
    """Sembolün kesinleşmiş saat kayıtları (eskiden yeniye)."""
    data = load_confirmed()
    rows = data.get(symbol.upper(), [])
    return {
        "symbol": symbol.upper(),
        "count": len(rows),
        "hours": rows[-limit:],
    }
