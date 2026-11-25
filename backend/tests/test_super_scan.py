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
