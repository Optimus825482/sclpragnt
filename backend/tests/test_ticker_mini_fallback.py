"""Ticker tazelik: `!miniTicker@arr` yedeğinin `get_ticker`'a yansıması.

REGRESYON (2026-11-10, canlıda "WS BAĞLI AMA FİYAT HEP BAYAT"):

    `!miniTicker@arr` dizisi TÜM semboller için saniyelik fiyat taşır ve
    `_ingest_mini_ticker_arr` bunu `mini_tickers`'a yazar. Ancak `tickers`
    sözlüğüne YALNIZCA `self.symbols` (WS kline aboneliği olan ~34 aktif
    sembol) için yazıyordu. Evrenin geri kalanı (warming/pasif, ~276 sembol)
    için fiyat `mini_tickers`'ta TAZE dururken `get_ticker` yalnız `tickers`'a
    baktığı için None/bayat dönüyordu.

    Sonuç: o sembollerde auto_paper her turda "ticker BAYAT" uyarısı üretip
    gereksiz REST fiyat yedeğine düşüyordu (sembol başına sürekli istek).

Beklenen davranış:
  * `mini_tickers` daha taze ise `get_ticker` onu döndürmeli (zengin alanlar korunur).
  * `tickers` daha taze/eşit ise `tickers` korunur (regresyon yok).
  * Hiç kayıt yoksa None.
"""
from __future__ import annotations

import time

from app.market_data import MarketData


def _market(symbols=("BTCTRY",)) -> MarketData:
    return MarketData(list(symbols))


def test_mini_ticker_serves_symbols_outside_kline_subscription():
    """Kline aboneliği olmayan sembol de taze fiyat alabilmeli."""
    market = _market(["BTCTRY"])  # ETHTRY WS abonesi değil
    assert "ETHTRY" not in market.symbols
    now_ms = int(time.time() * 1000)
    market._ingest_mini_ticker_arr([
        {"s": "ETHTRY", "c": "42.5", "q": "1000", "E": now_ms},
    ])
    ticker = market.get_ticker("ETHTRY")
    assert ticker is not None, "mini_tickers'taki taze fiyat görünmüyor"
    assert ticker["last_price"] == 42.5
    assert ticker["timestamp"] == now_ms


def test_freshness_gate_passes_for_mini_ticker_only_symbol():
    """Asıl şikâyet: tazelik kapısı bu sembollerde False dönüyordu."""
    from app import paper_ledger

    market = _market(["BTCTRY"])
    now_ms = int(time.time() * 1000)
    market._ingest_mini_ticker_arr([{"s": "ETHTRY", "c": "42.5", "q": "1", "E": now_ms}])
    ticker = market.get_ticker("ETHTRY")
    assert paper_ledger.is_fresh(ticker["timestamp"], time.time()) is True


def test_richer_tickers_record_wins_when_newer():
    """`tickers` daha yeniyse mini_tickers onu EZMEMELİ."""
    market = _market(["BTCTRY"])
    now_ms = int(time.time() * 1000)
    market.tickers["BTCTRY"] = {
        "symbol": "BTCTRY", "last_price": 100.0,
        "timestamp": now_ms, "source": "ws:kline",
    }
    # mini daha ESKİ
    market.mini_tickers["BTCTRY"] = {
        "last_price": 90.0, "timestamp": now_ms - 5000, "source": "ws:mini",
    }
    ticker = market.get_ticker("BTCTRY")
    assert ticker["last_price"] == 100.0
    assert ticker["source"] == "ws:kline"


def test_mini_ticker_overrides_when_newer_and_keeps_rich_fields():
    """mini daha yeniyse fiyat/zaman devralınır, diğer alanlar korunur."""
    market = _market(["BTCTRY"])
    now_ms = int(time.time() * 1000)
    market.tickers["BTCTRY"] = {
        "symbol": "BTCTRY", "last_price": 100.0, "timestamp": now_ms - 30_000,
        "source": "ws:kline", "bid": 99.5, "ask": 100.5,
    }
    market.mini_tickers["BTCTRY"] = {
        "last_price": 101.0, "timestamp": now_ms, "source": "ws:miniTicker@arr",
    }
    ticker = market.get_ticker("BTCTRY")
    assert ticker["last_price"] == 101.0
    assert ticker["timestamp"] == now_ms
    assert ticker["bid"] == 99.5 and ticker["ask"] == 100.5, "zengin alanlar korunmalı"


def test_unknown_symbol_returns_none():
    market = _market(["BTCTRY"])
    assert market.get_ticker("NOPE") is None


def test_get_ticker_normalizes_lowercase():
    market = _market(["BTCTRY"])
    now_ms = int(time.time() * 1000)
    market._ingest_mini_ticker_arr([{"s": "BTCTRY", "c": "7", "q": "1", "E": now_ms}])
    assert market.get_ticker("btctry")["last_price"] == 7.0
