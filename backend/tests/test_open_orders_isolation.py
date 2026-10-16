"""Açık emir önbelleği KULLANICIYA (API anahtarına) özeldir.

Hata (2026-10-16, kod incelemesi): `_open_orders_cache` tek bir global sözlüktü. `symbol` verilmeden çağrılınca
önbellekte kimin emirleri varsa herkese dönüyordu: bir kullanıcı başkasının açık emirlerini
(sembol, fiyat, miktar, clientOrderId) görebiliyordu. `/api/binance/open-orders` ve `/positions` bu yolu kullanır.
"""
from unittest import mock

import pytest

from app import binance_tr_private as btp


def _row(order_id: str) -> dict:
    return {"orderId": order_id, "symbol": "ADA_TRY", "side": "SELL", "type": "LIMIT", "price": "1",
            "origQty": "5", "executedQty": "0", "status": "NEW", "createTime": "1"}


@pytest.fixture(autouse=True)
def _clean():
    btp._open_orders_caches.clear()
    yield
    btp._open_orders_caches.clear()


def _signed(method, path, params, api_key, api_secret, **kw):
    return {"list": [_row("111" if api_key == "keyA" else "222")]}


def _balance(*a, **k):
    return [{"asset": "ADA", "free": "0", "locked": "5"}]


def test_each_key_gets_its_own_orders():
    with mock.patch.object(btp, "get_account_balance", side_effect=_balance), \
         mock.patch.object(btp, "_signed_request", side_effect=_signed) as sr:
        a = btp.get_open_orders("keyA", "sA")
        b = btp.get_open_orders("keyB", "sB")
    assert [o["orderId"] for o in a] == [111]
    assert [o["orderId"] for o in b] == [222]          # A'nın önbelleği B'ye SIZMAMALI
    assert sr.call_count == 2                           # B kendi isteğini atmalı


def test_cache_still_works_for_same_key():
    with mock.patch.object(btp, "get_account_balance", side_effect=_balance), \
         mock.patch.object(btp, "_signed_request", side_effect=_signed) as sr:
        btp.get_open_orders("keyA", "sA")
        btp.get_open_orders("keyA", "sA")
    assert sr.call_count == 1                           # aynı kullanıcıda önbellek korunur


def test_invalidate_only_affects_that_key():
    with mock.patch.object(btp, "get_account_balance", side_effect=_balance), \
         mock.patch.object(btp, "_signed_request", side_effect=_signed) as sr:
        btp.get_open_orders("keyA", "sA")
        btp.get_open_orders("keyB", "sB")
        btp._invalidate_open_orders("keyA")
        btp.get_open_orders("keyA", "sA")               # A yeniden çeker
        btp.get_open_orders("keyB", "sB")               # B hâlâ önbellekte
    assert sr.call_count == 3


def test_partial_flag_is_per_key():
    btp._open_orders_cache_for("keyA").update({"partial": True})
    assert btp.get_open_orders_partial("keyA", "sA") is True
    assert btp.get_open_orders_partial("keyB", "sB") is False
