"""SL/TP/OCO fiyat ilişkisi kuralları."""
import pytest

from app.sl_tp_rules import validate_sl_tp


def test_valid_oco():
    assert validate_sl_tp("OCO", 100, 110, 95) is None


@pytest.mark.parametrize("tp,sl", [(0, 95), (110, 0), (None, 95)])
def test_oco_needs_both(tp, sl):
    assert "hem" in validate_sl_tp("OCO", 100, tp, sl)


def test_oco_tp_must_exceed_sl():
    assert "büyük" in validate_sl_tp("OCO", 100, 90, 95)


def test_sl_must_be_below_last_price():
    assert "altında" in validate_sl_tp("SL_ONLY", 100, None, 100)
    assert "altında" in validate_sl_tp("OCO", 100, 120, 105)
    assert validate_sl_tp("SL_ONLY", 100, None, 99.9) is None


def test_tp_must_be_above_last_price():
    assert "üstünde" in validate_sl_tp("TP_ONLY", 100, 100, None)
    assert "üstünde" in validate_sl_tp("OCO", 100, 99, 90)
    assert validate_sl_tp("TP_ONLY", 100, 100.1, None) is None


def test_single_modes_require_their_price():
    assert "SL" in validate_sl_tp("SL_ONLY", 100, 110, None)
    assert "TP" in validate_sl_tp("TP_ONLY", 100, None, 90)


def test_unknown_last_price_skips_market_relation():
    assert validate_sl_tp("OCO", None, 110, 95) is None
    assert validate_sl_tp("TP_ONLY", None, 50, None) is None


def test_bad_mode():
    assert "Geçersiz mod" in validate_sl_tp("XX", 100, 110, 95)
