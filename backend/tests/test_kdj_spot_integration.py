import pytest
import numpy as np
from app.technical_analysis import _kdj, calculate_snapshot
from app.master_surge import evaluate_layer2_volatility, calculate_adaptive_targets, evaluate_master_surge

def test_kdj_standalone_calculation():
    # 20 bars of synthetic data with oversold dip reversal at the end
    np.random.seed(42)
    closes = [100.0 - i * 2.0 for i in range(15)] + [71.0, 70.0, 70.5, 72.0, 74.0]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    
    res = _kdj(highs, lows, closes, period=9, signal=3)
    assert res is not None
    assert "k" in res
    assert "d" in res
    assert "j" in res
    assert "cross_up" in res
    assert "dip_buy" in res
    assert isinstance(res["dip_buy"], bool)

def test_kdj_in_snapshot():
    # 60 synthetic bars
    closes = [50.0 + np.sin(i * 0.2) * 5.0 for i in range(60)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    opens = [c - 0.2 for c in closes]
    volumes = [1000.0] * 60
    
    klines = {
        "5m": {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "opens": opens,
            "volumes": volumes,
            "timestamps": [1700000000 + i * 300 for i in range(60)],
        }
    }
    
    snap = calculate_snapshot(
        symbol="AVAXTRY",
        price=closes[-1],
        klines=klines,
        orderflow={"spread_pct": 0.05, "bid_qty": 10.0, "ask_qty": 10.0},
    )
    
    assert "kdj" in snap
    assert snap["kdj"] is not None
    assert "j" in snap["kdj"]
    assert "kdj" in snap["oscillators"]["values"]

def test_kdj_dip_buy_in_layer2():
    # Case 1: Row with kdj_dip_buy=True
    row = {
        "kdj": {"j": 8.5, "cross_up": True, "dip_buy": True},
        "pre": {"dip": False},
        "pre_detail": {"proximity": 0.2, "squeeze_now": False, "transition": False, "expand_now": False},
    }
    l2 = evaluate_layer2_volatility("AVAXTRY", macd_row=row)
    assert l2["kdj_dip_buy"] is True
    assert l2["passed"] is True
    assert l2["score"] >= 35.0
    assert any("kdj_dip_buy" in r for r in l2["reasons"])

def test_adaptive_targets_spot_altcoin():
    # Altcoin spot targets
    t_avax = calculate_adaptive_targets(score=75.0, symbol="AVAXTRY")
    assert t_avax["tp1_scalp_pct"] == 1.50
    assert t_avax["tp2_runner_pct"] == 2.80
    assert t_avax["breakeven_trigger_pct"] == 0.90
    assert t_avax["trailing_gap_pct"] == 0.40

    t_near = calculate_adaptive_targets(score=80.0, symbol="NEARUSDT")
    assert t_near["tp1_scalp_pct"] == 1.50

    # Non-altcoin fallback
    t_other = calculate_adaptive_targets(score=50.0, atr_pct=1.0, symbol="XYZ")
    assert t_other["tp1_scalp_pct"] != 1.50 or t_other["tp2_runner_pct"] != 2.80
