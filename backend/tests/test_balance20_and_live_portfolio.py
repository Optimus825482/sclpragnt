"""Serbest bakiyenin %20'si ile giriş + canlı (mark-to-market) portföy değeri.

2026-11-25 (kullanıcı):
  * Her otonom giriş SERBEST bakiyenin %20'siyle açılır (kilitli para sayılmaz).
  * Toplam portföy değeri açık işlemleri GÜNCEL fiyatla kapsar ve canlı güncellenir.
"""
import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database, main  # noqa: E402
from app.config import config  # noqa: E402
from app.routers import auto_paper, runtime  # noqa: E402


def test_default_balance_pct_is_twenty():
    assert config.AUTO_PAPER_BALANCE_PCT_DEFAULT == 20.0


def test_sizing_uses_twenty_percent_of_free_balance():
    """Serbest bakiye 1000 → emir 200 (açık pozisyonlara kilitli para düşülmüş hâli)."""
    async def run():
        with patch.object(database, "get_wallet_balance", AsyncMock(return_value=1000.0)), \
             patch.object(auto_paper, "_liquidity_cluster_gate", AsyncMock(return_value=None)):
            return await auto_paper._sizing_gate({"symbol": "AAA_TRY"}, "AAA_TRY",
                                                 {"balance_pct": 20.0})
    balance, order_value, block = asyncio.run(run())
    assert block is None
    assert balance == 1000.0
    assert order_value == pytest.approx(200.0)


def test_balance_pct_once_migrates_saved_setting():
    """Kayıtlı %50 ayarı BİR KEZ %20'ye çekilir; ikinci çağrı dokunmaz."""
    store = {"auto_paper_settings": json.dumps({"enabled": True, "balance_pct": 50.0})}

    async def get_llm_setting(key, default=None):
        return store.get(key, default)

    async def set_llm_setting(key, value):
        store[key] = value

    async def run():
        with patch.object(database, "get_llm_setting", get_llm_setting), \
             patch.object(database, "set_llm_setting", set_llm_setting):
            await main._auto_paper_balance_pct_once()

    asyncio.run(run())
    saved = json.loads(store["auto_paper_settings"])
    assert saved["balance_pct"] == 20.0
    assert saved["enabled"] is True, "diğer ayarlar korunmalı"
    assert store.get(main._AUTO_BALANCE20_KEY), "tek seferlik işaret yazılmalı"

    # Kullanıcı sonradan panelden 30 yaparsa tekrar 20'ye çekilmemeli.
    store["auto_paper_settings"] = json.dumps({"balance_pct": 30.0})
    asyncio.run(run())
    assert json.loads(store["auto_paper_settings"])["balance_pct"] == 30.0


def test_dashboard_overlay_uses_live_total_and_open_count():
    live = {
        "try": 800.0,
        "total_value": 1050.5,
        "unrealized_pnl": 12.3,
        "positions": [{"symbol": "AAA_TRY", "value": 150.5}],
        "auto_paper_positions": [{"symbol": "BBB_TRY", "value": 100.0}],
    }
    summary = {"portfolio": {"balance": 800.0, "open_positions": 0, "total_value": 800.0,
                             "basis": "entry"}}
    with patch.object(runtime, "live_portfolio_snapshot", lambda *a, **k: live):
        out = runtime.dashboard_live_overlay(summary)
    p = out["portfolio"]
    assert p["total_value"] == pytest.approx(1050.5)
    assert p["open_positions"] == 2
    assert p["auto_paper_open"] == 1
    assert p["auto_paper_value"] == pytest.approx(100.0)
    assert p["positions_value"] == pytest.approx(150.5)
    assert p["basis"] == "mark_to_market"


def test_dashboard_overlay_noop_without_live_snapshot():
    summary = {"portfolio": {"balance": 800.0, "open_positions": 0, "total_value": 800.0,
                             "basis": "entry"}}
    with patch.object(runtime, "live_portfolio_snapshot", lambda *a, **k: None):
        out = runtime.dashboard_live_overlay(summary)
    assert out["portfolio"]["total_value"] == 800.0
    assert out["portfolio"]["basis"] == "entry"


def test_live_snapshot_rejects_stale_cache(monkeypatch):
    monkeypatch.setitem(runtime._ws_snapshot_cache, "portfolio", {"try": 1.0, "total_value": 2.0})
    monkeypatch.setitem(runtime._ws_snapshot_cache, "generated_at", 0.0)
    assert runtime.live_portfolio_snapshot(max_age_sec=30.0) is None
