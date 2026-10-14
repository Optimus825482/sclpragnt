"""İşlem günlüğü (journal) — kullanıcıya özel scalping disiplin notları.

NEDEN: Scalp disiplini için pozisyona/sembole not almak ve strateji etiketi
tutmak gerekir. Notlar KULLANICIYA ÖZELDİR (username kapsamlı) ve salt-not
taşır: emir açmaz, pozisyon değiştirmez, bildirim göndermez.

DEPOLAMA: `trade_journal` tablosu (migration 012_trade_journal.sql).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app import database, security

logger = logging.getLogger("scalper.journal")

router = APIRouter()


def _current_username(request: Request | None) -> str | None:
    if request is None:
        return None
    user = security.request_user(request.headers, request.cookies,
                                 client_fingerprint=security.client_fingerprint(request))
    return (user or {}).get("username")


def _require_username(request: Request) -> str:
    username = _current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    return username


@router.get("/api/journal")
async def get_journal(request: Request, limit: int = 200):
    username = _require_username(request)
    try:
        notes = await database.get_trade_journal(username, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Günlük okunamadı: {exc}")
    return {"ok": True, "notes": notes, "count": len(notes)}


@router.post("/api/journal")
async def add_journal_note(payload: dict, request: Request):
    username = _require_username(request)
    body = payload or {}
    symbol = str(body.get("symbol") or "").upper().strip()
    note = str(body.get("note") or "").strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol zorunludur")
    if not note:
        raise HTTPException(status_code=422, detail="note zorunludur")
    try:
        saved = await database.add_trade_journal_note(
            username, symbol, note, body.get("strategy_tag"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Not kaydedilemedi: {exc}")
    return {"ok": True, "note": saved}


@router.delete("/api/journal/{note_id}")
async def delete_journal_note(note_id: int, request: Request):
    username = _require_username(request)
    try:
        deleted = await database.delete_trade_journal_note(username, note_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Not silinemedi: {exc}")
    if not deleted:
        raise HTTPException(status_code=404, detail="Not bulunamadı")
    return {"ok": True, "deleted": note_id}
