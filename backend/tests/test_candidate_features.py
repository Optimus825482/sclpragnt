"""2026-10-17: aday özellik anlık görüntüsü (journal) — app/candidate_features.py."""
import json

from app.candidate_features import FEATURE_VERSION, candidate_features
from app.unified_outcomes import _candidate_row


def _cand():
    return {
        "symbol": "LUNATRY", "mode": "trend_devam", "rsi": 85.3, "mfi": 96.3, "volume_ratio": 0.76,
        "exhausted": "mfi_asiri_alim:96", "panel_score": 92.7, "velocity_score": 11975.74,
        "radar": {"taker_buy_ratio": 0.374, "taker_confirm": "weak", "book_imbalance": -0.165,
                  "choppiness_10": 30.8, "range_pos_60": 0.981, "unused": 1},
        "microstructure": {"whale_verdict": "accumulation", "whale_count": 72, "cvd_try": -237623.32,
                           "trade_rate_per_min": 90, "symbol": "LUNATRY"},
        "master_surge": {"composite_index": 71.4, "regime_badge": "BTC_BEAR_REGIME_SHIELD",
                         "layers": {"l1_liquidity": {"spread_pct": 0.1279, "bid_ask_ratio": 31.99, "depth_try": 672815.9},
                                    "l3_orderflow": {"buy_ratio": 0.282, "whale_net": -5}}},
    }


def test_extracts_non_candle_fields():
    f = candidate_features(_cand())
    assert f["v"] == FEATURE_VERSION
    assert f["taker_buy_ratio"] == 0.374 and f["book_imbalance"] == -0.165
    assert f["whale_verdict"] == "accumulation" and f["cvd_try"] == -237623.32
    assert f["spread_pct"] == 0.1279 and f["buy_ratio"] == 0.282 and f["surge_composite"] == 71.4
    assert f["mode"] == "trend_devam" and f["rsi"] == 85.3 and f["volume_ratio"] == 0.76
    assert f["regime_badge"] == "BTC_BEAR_REGIME_SHIELD"
    assert "unused" not in f and "symbol" not in f
    json.dumps(f)  # JSON'a yazılabilir


def test_empty_or_missing_inputs():
    assert candidate_features(None) == {}
    assert candidate_features({}) == {}
    assert candidate_features({"symbol": "X", "radar": None, "microstructure": "bozuk"}) == {}


def test_unified_journal_row_serializes_features():
    row = {"symbol": "LUNATRY", "price": 2.33, "horizon_minutes": 15, "scan_score": 90,
           "features": candidate_features(_cand())}
    out = _candidate_row(row)
    assert isinstance(out["features"], str) and json.loads(out["features"])["taker_buy_ratio"] == 0.374
    row.pop("features")
    assert _candidate_row(row)["features"] is None
