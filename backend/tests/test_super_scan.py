"""Süper Tarama (2026-11-25): tüm tarayıcılar tek skorlu listede.

Kural: blocked satırlar elenir, skor eşiği uygulanır, teyit eden kaynak sayısı
skoru yükseltir, CMC bayrakları bonus/ceza verir. Önbellek 30 sn.
"""
import asyncio
from unittest.mock import AsyncMock, patch

from app.routers import monitoring


def _rows():
    return [
        {"symbol": "AAA_TRY", "price": 10.0, "unified_score": 70.0, "scan_score": 70.0,
         "unified_sources": ["velocity", "rising"], "signal_sources": ["velocity"],
         "confluence_4way": True, "atr_pct_15m": 1.8, "target_pct": 3.0, "horizon_minutes": 15,
         "cmc": {"tags": ["AI"], "rank": 120}, "cmc_flags": ["HACIM_PATLAMASI"]},
        {"symbol": "BBB_TRY", "price": 5.0, "unified_score": 55.0,
         "unified_sources": ["velocity"], "atr_pct_15m": 1.2, "cmc_flags": [],
         "cmc": {}},
        {"symbol": "CCC_TRY", "price": 1.0, "unified_score": 90.0, "unified_sources": ["velocity"],
         "blocked_by": "score_gate", "cmc": {}, "cmc_flags": []},
        {"symbol": "DDD_TRY", "price": 1.0, "unified_score": 20.0, "unified_sources": [], "cmc": {}},
    ]


def test_super_scan_ranks_and_filters():
    with patch.object(monitoring, "_combined_scan_rows", AsyncMock(return_value=_rows())):
        monitoring._SUPER_SCAN_CACHE.update({"generated_at": 0.0, "payload": None})
        out = asyncio.run(monitoring.radar_super_scan(limit=12, min_score=50.0, force=True))

    symbols = [x["symbol"] for x in out["items"]]
    assert symbols == ["AAA_TRY", "BBB_TRY"], "engelli ve düşük skorlu elenmeli"
    top = out["items"][0]
    # skor = 70 + 6*(2-1) + 5 = 81
    assert top["super_score"] == 81.0
    assert top["source_count"] == 2
    assert top["confluence"] is True
    assert out["scanned"] == 4 and out["eligible"] == 2


def test_super_scan_uses_cache():
    rows = _rows()
    calls = {"n": 0}

    async def fake_rows():
        calls["n"] += 1
        return rows

    with patch.object(monitoring, "_combined_scan_rows", fake_rows):
        monitoring._SUPER_SCAN_CACHE.update({"generated_at": 0.0, "payload": None})
        asyncio.run(monitoring.radar_super_scan(limit=5, force=True))
        asyncio.run(monitoring.radar_super_scan(limit=5))  # önbellek

    assert calls["n"] == 1, "30 sn içinde ikinci tarama yapılmamalı"


def test_shallow_liquidity_is_excluded():
    """24s TL hacmi eşiğin altındaki semboller listeden ELENİR."""
    rows = [
        {"symbol": "BIG_TRY", "price": 10.0, "unified_score": 70.0, "unified_sources": ["velocity"]},
        {"symbol": "THIN_TRY", "price": 1.0, "unified_score": 90.0, "unified_sources": ["velocity"]},
    ]

    async def fake_ticker(symbols=None):
        return [
            {"symbol": "BIG_TRY", "quoteVolume": "90000000", "priceChangePercent": "5"},
            {"symbol": "THIN_TRY", "quoteVolume": "120000", "priceChangePercent": "40"},
        ]

    from app import binance_tr_public
    with patch.object(monitoring, "_combined_scan_rows", AsyncMock(return_value=rows)), \
         patch.object(binance_tr_public, "ticker_24h", fake_ticker):
        monitoring._SUPER_SCAN_CACHE.update({"generated_at": 0.0, "payload": None})
        out = asyncio.run(monitoring.radar_super_scan(limit=12, min_score=10.0,
                                                      min_volume_try=5_000_000, force=True))

    symbols = [x["symbol"] for x in out["items"]]
    assert symbols == ["BIG_TRY"], "sığ hacimli sembol elenmeli"
    assert out["items"][0]["volume_24h_try"] == 90_000_000.0


def test_super_scan_returns_pending_on_slow_scan(monkeypatch):
    """Soğuk tarama 20 sn'yi aşarsa istek zaman aşımına düşmemeli (pending)."""
    import asyncio as _asyncio

    async def slow_rows():
        await _asyncio.sleep(5)
        return []

    monkeypatch.setattr(monitoring, "_combined_scan_rows", slow_rows)
    monitoring._SUPER_SCAN_CACHE.update({"generated_at": 0.0, "payload": None})
    # wait_for süresini test için kısalt
    orig_wait_for = _asyncio.wait_for

    async def fake_wait_for(coro, timeout):
        return await orig_wait_for(coro, timeout=0.05)

    monkeypatch.setattr(monitoring.asyncio, "wait_for", fake_wait_for)
    out = _asyncio.run(monitoring.radar_super_scan(limit=5, force=True))
    assert out.get("pending") is True
    assert out["items"] == []
    assert "hazırlanıyor" in (out.get("message") or "").lower()
