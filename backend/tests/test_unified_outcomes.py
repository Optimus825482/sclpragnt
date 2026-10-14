"""BİRLEŞİK ADAY SONUÇ JOURNAL'I (Faz 2) testleri.

Kapsam:
- record_scan_rows alan eşlemesi: signal_sources → JSON sources, price → entry_price.
- fill_pending_outcomes: fake 1m kline penceresinden MFE/MAE/hit hesabı (yükselen
  pencere → hit True).
- /api/unified-scan/outcome-stats ucu router'a kayıtlı.
- daily_rising_combined_loop her turda kayıt + doldurma yardımcılarını çağırır.
"""
import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import unified_outcomes as uo  # noqa: E402


def test_record_and_stats(monkeypatch):
    """record_scan_rows: unified scan satırını journal adayına çevirir —
    signal_sources JSON'a serileştirilir, price → entry_price eşlenir."""
    saved = []

    async def _save(rows):
        saved.extend(rows)
        return len(rows)

    monkeypatch.setattr(uo.database, "save_unified_candidates", _save)

    row = {
        "symbol": "ogntry",
        "horizon_minutes": 15,
        "signal_sources": ["velocity", "pulse"],
        "scan_score": 74.3,
        "price": 0.102,
        "ceiling_pct": 4.0,
        "target_pct": 2.0,
        "detected_at": 1750000000.0,
    }
    n = asyncio.run(uo.record_scan_rows([row, {"symbol": "", "price": 1.0}]))

    assert n == 1 and len(saved) == 1
    c = saved[0]
    assert c["symbol"] == "OGNTRY"
    assert c["entry_price"] == 0.102                 # price → entry_price
    assert c["horizon_minutes"] == 15
    assert c["detected_at"] == 1750000000.0
    assert c["scan_score"] == 74.3 and c["ceiling_pct"] == 4.0
    assert isinstance(c["sources"], str)             # liste → JSON string
    assert json.loads(c["sources"]) == ["velocity", "pulse"]

    # quality_score + unified_sources alternatif alan adları da desteklenir.
    saved.clear()
    alt = {"symbol": "AAA", "price": 2.0, "horizon_minutes": 5,
           "quality_score": 55.0, "unified_sources": ["snapback"],
           "detected_at": 1750000100.0}
    asyncio.run(uo.record_scan_rows([alt]))
    assert saved[0]["scan_score"] == 55.0
    assert json.loads(saved[0]["sources"]) == ["snapback"]


def test_fill_computes_mfe_mae(monkeypatch):
    """fill_pending_outcomes: yükselen 1m pencere → MFE = +%3, hit True
    (ceiling %2). Mum formatı: [open_time, open, high, low, close, ...]."""
    pending = [{
        "id": 7, "symbol": "RISERTRY", "horizon_minutes": 5,
        "sources": '["velocity"]', "scan_score": 80.0,
        "entry_price": 100.0, "ceiling_pct": 2.0, "target_pct": None,
        "detected_at": 1750000000.0,
    }]

    async def _pending(older_than_sec, limit=200):
        assert older_than_sec >= 0
        return [dict(r) for r in pending]

    updates = []

    async def _update(row_id, mfe_pct, mae_pct, hit):
        updates.append((row_id, mfe_pct, mae_pct, hit))

    # Yükselen pencere: low 99.0 (MAE -%1), high 103.0 (MFE +%3 ≥ ceiling %2).
    candles = []
    for i in range(9):
        candles.append([1750000000_000 + i * 60_000, "100.0",
                        str(100.0 + i * 0.375), str(100.0 - 1.0), "100.5"])

    async def _klines(symbol, interval, limit=500, start_time_ms=None, end_time_ms=None):
        assert symbol == "RISERTRY" and interval == "1m"
        assert start_time_ms == 1750000000_000
        # pencere = (horizon + 5) dakika
        assert end_time_ms == start_time_ms + 10 * 60_000
        return candles

    monkeypatch.setattr(uo.database, "get_unified_pending_outcomes", _pending)
    monkeypatch.setattr(uo.database, "update_unified_outcome", _update)
    monkeypatch.setattr(uo, "klines", _klines)

    filled = asyncio.run(uo.fill_pending_outcomes(max_age_sec=0))

    assert filled == 1 and len(updates) == 1
    row_id, mfe, mae, hit = updates[0]
    assert row_id == 7
    assert abs(mfe - 3.0) < 0.01, f"MFE beklenen +%3, gelen {mfe}"
    assert abs(mae - (-1.0)) < 0.01, f"MAE beklenen -%1, gelen {mae}"
    assert hit is True

    # Düşen pencere → hit False (threshold fallback: ceiling yoksa target, o da
    # yoksa %2 taban).
    updates.clear()
    pending[0]["ceiling_pct"] = None
    pending[0]["target_pct"] = None
    falling = [[1750000000_000 + i * 60_000, "100.0",
                str(100.5 - i * 0.3), str(99.0 - i * 0.3), "100.0"] for i in range(10)]

    async def _klines_fall(*_a, **_k):
        return falling
    monkeypatch.setattr(uo, "klines", _klines_fall)
    asyncio.run(uo.fill_pending_outcomes(max_age_sec=0))
    assert len(updates) == 1 and updates[0][3] is False


def test_outcome_stats_endpoint_registered():
    """Router'a /api/unified-scan/outcome-stats GET ucu kayıtlı (salt-okunur)."""
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/unified-scan/outcome-stats" in paths


def test_combined_loop_calls_recorder():
    """Kombine döngü HER TURDA _record_unified_outcomes + _fill_unified_outcomes
    çağırır (kayıt + doldurma; hata yutar, döngüyü bozmaz)."""
    from app.routers import monitoring as mo
    loop_src = inspect.getsource(mo.daily_rising_combined_loop)
    assert "_record_unified_outcomes" in loop_src
    assert "_fill_unified_outcomes" in loop_src
