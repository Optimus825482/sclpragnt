"""Idempotent emir kaydı sabitleri ve client_order_id doğrulaması.

`(user_id, client_order_id)` birincil anahtardır; `claim_order_request` INSERT … ON CONFLICT DO NOTHING ile
aynı id'li ikinci isteğin gerçek emir üretmesini engeller (yeniden başlatma ve çok işçi güvenli).
"""
from __future__ import annotations

import re

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
