"""`_resolve_live_price` SENKRON olmalı (2026-11-25 canlı log).

Hata: async `ticker_price` await edilmeden çağrılıyordu →
"coroutine was never awaited" + fiyat daima None → toz kapısı ölüydü.
"""
import inspect

from app import binance_tr_private


def test_resolver_does_not_call_async_ticker_price():
    src = inspect.getsource(binance_tr_private._resolve_live_price)
    assert "ticker_price(" not in src, "async fonksiyon senkron bağlamda çağrılmamalı"
    assert "_get_json" in src


def test_resolver_reads_sync_payload(monkeypatch):
    from app import binance_tr_public

    class Market:
        @staticmethod
        def get_ticker(symbol):
            return None

    monkeypatch.setattr("app.state.market", Market, raising=False)
    monkeypatch.setattr(binance_tr_public, "_get_json",
                        lambda path, params: {"symbol": params["symbol"], "price": "12.5"})
    assert binance_tr_private._resolve_live_price("ABC_TRY") == 12.5
