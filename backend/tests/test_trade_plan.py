"""Plan hesabı (SL/TP/komisyon/yuvarlama) ve RR önerisi yedek kuralı + LLM çıktısı doğrulama. Hepsi saf."""
import pytest

from app.trade_plan import (
    compute_plan, rule_suggestion, round_down, round_to_tick, validate_llm_suggestion,
)

FILTERS = {"step_size": 0.01, "tick_size": 0.01, "min_notional": 10.0, "min_qty": 0.01,
           "quote_asset": "TRY", "oco_enable": True}


def test_round_down_and_tick():
    assert round_down(9.999, 0.01) == pytest.approx(9.99)
    assert round_down(5, 0) == 5                       # adım yoksa dokunma
    assert round_to_tick(98.004, 0.01) == pytest.approx(98.0)
    assert round_to_tick(98.006, 0.01) == pytest.approx(98.01)


def test_plan_basic_numbers():
    p = compute_plan(price=100.0, amount_try=1000.0, sl_pct=2.0, rr=2.0, filters=FILTERS, fee_rate=0.001)
    assert p["qty"] == pytest.approx(9.99)            # 10 × (1-0,001), adıma aşağı
    assert p["sl_price"] == pytest.approx(98.0)
    assert p["tp_price"] == pytest.approx(104.0)      # %2 × RR 2 = %4
    assert p["loss_try"] == pytest.approx(9.99 * 98 * 0.999 - 1000, abs=0.01)    # ≈ -21,96
    assert p["gain_try"] == pytest.approx(9.99 * 104 * 0.999 - 1000, abs=0.01)   # ≈ +37,92
    assert p["loss_try"] < 0 < p["gain_try"]
    assert p["break_even_price"] == pytest.approx(1000 / (9.99 * 0.999), abs=0.01)
    assert p["warnings"] == []


def test_rr_scales_take_profit_only():
    a = compute_plan(100, 1000, 2.0, 1.5, FILTERS, 0.001)
    b = compute_plan(100, 1000, 2.0, 3.0, FILTERS, 0.001)
    assert a["sl_price"] == b["sl_price"]
    assert b["tp_price"] > a["tp_price"]
    assert a["tp_price"] == pytest.approx(103.0)      # %2 × 1,5 = %3


def test_below_min_notional_warns():
    p = compute_plan(100, 5.0, 2.0, 2.0, FILTERS, 0.001)
    assert "min_tutar_alti" in p["warnings"]


def test_qty_below_min_warns():
    p = compute_plan(100000, 10.0, 2.0, 2.0, FILTERS, 0.001)   # 0,0001 coin < min 0,01
    assert "min_miktar_alti" in p["warnings"]


def test_oco_disabled_warns():
    p = compute_plan(100, 1000, 2.0, 2.0, {**FILTERS, "oco_enable": False}, 0.001)
    assert "oco_desteklenmiyor" in p["warnings"]


def test_sl_must_be_below_price_after_rounding():
    p = compute_plan(0.01, 100.0, 0.5, 2.0, {**FILTERS, "tick_size": 0.01}, 0.001)
    assert "sl_fiyata_cok_yakin" in p["warnings"]    # tick yuvarlaması SL'yi fiyata eşitledi


@pytest.mark.parametrize("bad", [dict(price=0), dict(price=-1), dict(amount_try=0), dict(sl_pct=0), dict(rr=0)])
def test_invalid_inputs_raise(bad):
    args = dict(price=100.0, amount_try=1000.0, sl_pct=2.0, rr=2.0, filters=FILTERS, fee_rate=0.001)
    args.update(bad)
    with pytest.raises(ValueError):
        compute_plan(**args)


# ---------------------------------------------------------------- yedek kural

@pytest.mark.parametrize("atr,expected_sl", [(1.0, 1.5), (0.2, 0.8), (10.0, 6.0), (2.0, 3.0)])
def test_rule_suggestion_clamps(atr, expected_sl):
    out = rule_suggestion(atr, 2.0)
    assert out["sl_pct"] == pytest.approx(expected_sl)
    assert out["rr"] == 2.0 and out["source"] == "kural"


def test_rule_suggestion_handles_missing_atr():
    out = rule_suggestion(None, 2.5)
    assert out["sl_pct"] == 2.0 and out["rr"] == 2.5     # ATR yoksa sabit makul değer


# ---------------------------------------------------------------- LLM çıktısı doğrulama

def test_llm_valid_json():
    out = validate_llm_suggestion('{"sl_pct": 2.4, "rr": 2.2, "kisa_gerekce": "Trend güçlü, volatilite orta."}')
    assert out == {"sl_pct": 2.4, "rr": 2.2, "rationale": "Trend güçlü, volatilite orta."}


def test_llm_json_inside_text_and_fences():
    raw = 'İşte öneri:\n```json\n{"sl_pct": 1.8, "rr": 3, "kisa_gerekce": "ok"}\n```'
    assert validate_llm_suggestion(raw)["rr"] == 3.0


def test_llm_values_are_clamped():
    out = validate_llm_suggestion('{"sl_pct": 55, "rr": 99, "kisa_gerekce": "x"}')
    assert out["sl_pct"] == 10.0 and out["rr"] == 5.0
    out = validate_llm_suggestion('{"sl_pct": 0.01, "rr": 0.2, "kisa_gerekce": "x"}')
    assert out["sl_pct"] == 0.5 and out["rr"] == 1.0


@pytest.mark.parametrize("raw", [None, "", "yanıt yok", "{bozuk", '{"sl_pct": "abc", "rr": 2}',
                                 '{"rr": 2}', '{"sl_pct": 2}', '{"sl_pct": NaN, "rr": 2}', 123])
def test_llm_garbage_returns_none(raw):
    assert validate_llm_suggestion(raw) is None


def test_llm_rationale_is_truncated():
    out = validate_llm_suggestion('{"sl_pct": 2, "rr": 2, "kisa_gerekce": "' + "a" * 500 + '"}')
    assert len(out["rationale"]) <= 240
