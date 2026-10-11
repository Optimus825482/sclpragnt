"""KOMBİNE PAPER PORTFÖY testleri (2026-10-11 kullanıcı kararı).

Kapsam:
- Config varsayılanları: 5000 TL başlangıç, %10 pozisyon, max 5 açık.
- DB yardımcıları mevcut (open/close/list/stats/wallet).
- `_plan_entry`: serbest bakiyenin %10'u; TP potansiyele göre; SL tabanı.
- API uçları kayıtlı (state/reset/close).
- Motor: main.py döngüsü + kombine liste gönderiminde otonom açılış çağrısı.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import database  # noqa: E402
from app import combined_paper  # noqa: E402


def test_combined_paper_config_defaults():
    c = config.config
    assert c.COMBINED_PAPER_ENABLED is True
    assert c.COMBINED_PAPER_INITIAL_BALANCE_TRY == 5000.0
    assert c.COMBINED_PAPER_POSITION_PCT == 10.0
    assert c.COMBINED_PAPER_MAX_OPEN == 5


def test_combined_paper_db_helpers_exist():
    for name in ("open_combined_paper_trade", "close_combined_paper_trade",
                 "list_combined_paper_trades", "get_combined_paper_stats",
                 "get_combined_paper_wallet", "reset_combined_paper_portfolio",
                 "update_combined_paper_trade"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_plan_entry_position_is_10pct_and_tp_from_potential():
    """Pozisyon = serbest bakiyenin %10'u; TP potansiyele göre; SL tabanı uygulanır."""
    plan = combined_paper._plan_entry(
        {"symbol": "WTEST", "price": 100.0, "potential_pct": 20.0, "quality_score": 88},
        cash=5000.0)
    assert plan is not None
    assert plan["order_value_try"] == 500.0          # 5000 * %10
    assert abs(plan["quantity"] - 5.0) < 1e-9        # 500 / 100
    # TP potansiyele göre anlamlı (taban %3, potansiyelin altında)
    assert 3.0 <= plan["tp_pct"] <= 20.0
    assert plan["take_profit"] > plan["entry_price"]
    assert plan["stop_loss"] < plan["entry_price"]


def test_plan_entry_skips_tiny_balance():
    """Çok küçük kalan bakiye (< 50 TL pozisyon) → plan yok (anlamsız işlem açılmaz)."""
    assert combined_paper._plan_entry({"symbol": "X", "price": 1.0}, cash=100.0) is None


def test_plan_entry_tp_min_floor():
    """Potansiyel düşük/yoksa TP en az %3 tabanında kalır (uydurma yok)."""
    plan = combined_paper._plan_entry({"symbol": "Y", "price": 10.0, "potential_pct": None}, 5000.0)
    assert plan is not None and plan["tp_pct"] == 3.0


def test_combined_paper_endpoints_registered():
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/combined-paper/state" in paths
    assert "/api/combined-paper/reset" in paths
    assert "/api/combined-paper/close/{trade_id}" in paths


def test_combined_list_send_triggers_autopaper():
    """Kombine liste gönderildiğinde ayrı portföyde otonom açılış TETİKLENİR."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._send_combined_list)
    assert "combined_paper" in src and "on_combined_list_sent" in src


def test_manager_loop_registered_in_main():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "combined_paper_management_loop" in src
    assert "combined-paper" in src
