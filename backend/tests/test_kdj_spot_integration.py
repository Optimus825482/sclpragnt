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


def test_kdj_rising_candidate_and_notification():
    import time
    from unittest.mock import patch
    from app import rising_signals
    from app.routers import macd_monitor as _macd
    from app.routers.monitoring import _build_rising_notification, RISING_LABEL
    
    # Verify RISING_LABEL contains kdj_dip
    assert "kdj_dip" in RISING_LABEL
    
    # Mock symbols in rising_signals via fresh snapshot
    mock_row = {
        "strength": 7.5,
        "kdj": {"j": 11.2, "cross_up": True, "dip_buy": True},
        "pre": {"dip": False},
        "m5": {"green": True, "break": True},
        "m15": {"green": True, "break": False},
        "cvd": {"buy_dominant": True},
        "tier": "A",
    }
    
    snap = {
        "universe": ["AVAXTRY"],
        "symbols": {"AVAXTRY": mock_row},
        "generated_at": time.time() - 1.0,
    }
    
    # Detect candidate
    with patch.object(_macd, "_SNAPSHOT", snap):
        candidates = rising_signals.detect_rising_candidates()
    
    kdj_cands = [c for c in candidates if c["symbol"] == "AVAXTRY" and c["kind"] == "kdj_dip"]
    assert len(kdj_cands) == 1
    cand = kdj_cands[0]
    assert cand["score"] >= 82.0
    assert cand["target_pct"] == 1.50
    assert cand["kdj"]["dip_buy"] is True
    
    # Build notification
    notif = _build_rising_notification(cand, price=30.0)
    assert "[KDJ DİP] AVAXTRY" in notif["title"]
    assert "KDJ J-Çizgisi Dip Dönüşü" in notif["message"]
    assert notif["source"] == "kdj_dip"
    assert notif["tp1_scalp_pct"] == 1.50
    assert notif["tp2_runner_pct"] == 2.80
    assert notif["sl_pct"] == 1.0
    assert notif["confluence_4way"] is True


def test_kdj_in_macd_mtf_summary():
    from app.macd_mtf import _summarize
    
    # 2 mock cells: 5m has kdj_dip=True, 15m is neutral
    cell_5m = {
        "tf": "5m", "green": False, "parallel_up": False, "expanding": False,
        "fresh_bull_cross": False, "hist_trough": False, "hist_turn_up": False,
        "squeeze": False, "zl_green": False, "zl_fresh_cross": False,
        "wt_bullish": False, "wt_oversold_cross": False,
        "kdj_dip": True, "kdj_j": 12.4, "kdj_bullish": True,
    }
    cell_15m = {
        "tf": "15m", "green": False, "parallel_up": False, "expanding": False,
        "fresh_bull_cross": False, "hist_trough": False, "hist_turn_up": False,
        "squeeze": False, "zl_green": False, "zl_fresh_cross": False,
        "wt_bullish": False, "wt_oversold_cross": False,
        "kdj_dip": False, "kdj_j": 45.0, "kdj_bullish": False,
    }
    
    res = _summarize("AVAXTRY", [cell_5m, cell_15m], tfs=("5m", "15m"))
    assert "kdj_dip_cross" in res
    assert res["kdj_dip_cross"] == ["5m"]
    assert res["early_spark"] is True
    assert res["confluence"] >= 15.0


def test_kdj_in_velocity_warm_gate():
    from app.routers.velocity import _warm_gate
    
    # Test warm gate with kdj_dip_buy
    warm, reason, prox = _warm_gate(
        prof_atr=0.5, atr_pct=0.4, bb_width=0.8, slope=0.1, aroon_up=20.0,
        macd_bullish=False, macd_rising=False, ret3=0.0, volume_ratio=1.0,
        leading_ok=False, kdj_dip_buy=True
    )
    assert warm is True
    assert reason == "kdj_dip_yaklas"
    assert prox == 0.80


