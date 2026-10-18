"""Idempotent emir kaydı sabitleri ve client_order_id doğrulaması.

`(user_id, client_order_id)` birincil anahtardır; `claim_order_request` INSERT … ON CONFLICT DO NOTHING ile
aynı id'li ikinci isteğin gerçek emir üretmesini engeller (yeniden başlatma ve çok işçi güvenli).
"""
from __future__ import annotations

import re

# binance_tr_private yalnız stdlib + trade_plan içe aktarır → döngüsel import yok.
from app.binance_tr_private import sanitize_client_order_id

IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"       # kesin başarısız (borsa reddetti): AYNI id ile yeniden denenemez, yeni id gerekir
UNKNOWN = "unknown"     # belirsiz (zaman aşımı/5xx): önce order-status ile sorgulanmalı

_CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def validate_client_order_id(value) -> str:
    """İstemcinin ürettiği tekil id: 8-64 karakter, yalnız harf/rakam/_/-. Aksi halde ValueError."""
    text = str(value or "").strip()
    if not _CID_RE.match(text):
        raise ValueError("client_order_id 8-64 karakter olmalı (harf, rakam, _ ve -)")
    return text


def normalize_client_order_id(value) -> str:
    """Doğrula + borsaya GİDEN biçime indir (yalnız harf/rakam, ≤36; bkz. sanitize_client_order_id).

    Kayıt (`order_requests`) borsaya gönderilen kimlikle AYNI olmalı: eskiden `web-…` saklanıp
    `web…` gönderiliyordu → order-status/mutabakat kaydı borsadaki emirle eşleşmiyordu.
    Temizlik sonrası boş kalırsa ValueError.
    """
    cid = sanitize_client_order_id(validate_client_order_id(value))
    if not cid:
        raise ValueError("client_order_id en az bir harf veya rakam içermeli")
    return cid


class Replay(Exception):
    """Aynı client_order_id ile gelen ikinci istek: gerçek emir GÖNDERİLMEZ. `stored` varsa önceki sonuçtur."""

    def __init__(self, status: str, stored: dict | None):
        super().__init__(status)
        self.status = status
        self.stored = stored


async def begin(user_id: int, client_order_id, symbol: str, summary: dict) -> str | None:
    """Basit al/sat uçları için idempotent koruma. id verilmemişse (eski istemci) None döner ve koruma yoktur.

    Geçersiz id → ValueError. Aynı (kullanıcı, id) daha önce alındıysa → Replay.
    """
    if client_order_id in (None, ""):
        return None
    from app import database  # tembel: döngüsel import yok, testlerde monkeypatch edilebilir
    cid = normalize_client_order_id(client_order_id)
    if await database.claim_order_request(user_id, cid, symbol, summary):
        return cid
    row = await database.get_order_request(user_id, cid) or {}
    stored = row.get("result") if row.get("status") == DONE else None
    raise Replay(str(row.get("status") or IN_PROGRESS), stored or None)


async def complete(user_id: int, cid: str | None, result: dict) -> None:
    if cid:
        from app import database
        await database.finish_order_request(user_id, cid, DONE, result)


async def fail(user_id: int, cid: str | None, error: str, ambiguous: bool) -> None:
    if cid:
        from app import database
        await database.finish_order_request(user_id, cid, UNKNOWN if ambiguous else FAILED, {"error": str(error)[:300]})
