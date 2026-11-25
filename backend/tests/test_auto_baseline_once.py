"""Deploy sonrası TEK SEFERLİK portföy başlangıcı (2026-11-25).

Kural: ilk açılışta cüzdan 10.000 TL + rapor sınırı; sonraki açılışlarda
TEKRAR sıfırlama YOK (açık pozisyonlar korunur).
"""
import asyncio

from app import main


class _Store:
    def __init__(self):
        self.data = {}


def test_runs_once_and_sets_baseline(monkeypatch):
    store = _Store()
    calls = {"reset": 0, "baseline": None}

    async def fake_get(key, default=None):
        return store.data.get(key, default)

    async def fake_set(key, value):
        store.data[key] = str(value)

    async def fake_reset():
        calls["reset"] += 1
        return {"reset_at": 1_700_000_000.0, "wallet": 10000.0}

    async def fake_baseline(raw):
        calls["baseline"] = float(raw)
        return float(raw)

    monkeypatch.setattr(main.database, "get_llm_setting", fake_get)
    monkeypatch.setattr(main.database, "set_llm_setting", fake_set)
    monkeypatch.setattr(main.database, "reset_trading_data", fake_reset)
    monkeypatch.setattr(main.database, "set_reports_baseline", fake_baseline)

    asyncio.run(main._auto_portfolio_baseline_once())
    assert calls["reset"] == 1
    assert calls["baseline"] == 1_700_000_000.0
    assert store.data[main._AUTO_BASELINE_KEY] == "1700000000"

    # İkinci açılış: hiçbir şey değişmemeli
    asyncio.run(main._auto_portfolio_baseline_once())
    assert calls["reset"] == 1, "sıfırlama yalnız bir kez çalışmalı"
