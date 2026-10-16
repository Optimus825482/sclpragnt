"""2026-10-17: rejim kalkanı rozet modu (RADAR_SHIELD_MODE) ve aşırı alım skor cezası (VELOCITY_EXHAUSTION_MODE).

Kanıt: docs/REJIM_KALKANI_ANALIZI_2026-10-17.md. Canlı dedektör ile rescan çekirdeği aynı
`exhaustion_decision` fonksiyonunu çağırır (parite).
"""
from unittest import mock

from app.config import config
from app.routers import monitoring as M
from app.routers import velocity as V


# ------------------------------------------------------------- aşırı alım kararı
def test_penalty_only_for_trend_devam_overbought_when_shield_off():
    assert V.exhaustion_decision("mfi_asiri_alim:96", "trend_devam", False, "penalty") == (None, True)
    assert V.exhaustion_decision("rsi_asiri_alim:85", "trend_devam", False, "penalty") == (None, True)
    # aşırı satım, diğer modlar, kalkan açık → eskisi gibi eleme
    assert V.exhaustion_decision("mfi_asiri_satim:8", "trend_devam", False, "penalty") == ("mfi_asiri_satim:8", False)
    assert V.exhaustion_decision("mfi_asiri_alim:96", "notr", False, "penalty") == ("mfi_asiri_alim:96", False)
    assert V.exhaustion_decision("mfi_asiri_alim:96", "trend_devam", True, "penalty") == ("mfi_asiri_alim:96", False)
    # block modu: her zaman eleme; bayrak yoksa hiçbir şey
    assert V.exhaustion_decision("mfi_asiri_alim:96", "trend_devam", False, "block") == ("mfi_asiri_alim:96", False)
    assert V.exhaustion_decision(None, "trend_devam", False, "penalty") == (None, False)


def test_decision_reads_config_default():
    with mock.patch.object(config, "VELOCITY_EXHAUSTION_MODE", "penalty"):
        assert V.exhaustion_decision("mfi_asiri_alim:91", "trend_devam", False) == (None, True)
    with mock.patch.object(config, "VELOCITY_EXHAUSTION_MODE", "block"):
        assert V.exhaustion_decision("mfi_asiri_alim:91", "trend_devam", False) == ("mfi_asiri_alim:91", False)


def test_btc_shield_active_reads_cached_compass_only():
    with mock.patch("app.macro_sentiment_service.get_cached_btc_compass", return_value={"regime_shield_active": True}):
        assert V.btc_shield_active() is True
    with mock.patch("app.macro_sentiment_service.get_cached_btc_compass", return_value=None):
        assert V.btc_shield_active() is False
    with mock.patch("app.macro_sentiment_service.get_cached_btc_compass", side_effect=RuntimeError("x")):
        assert V.btc_shield_active() is False


# ------------------------------------------------------------- yükseliş yolu kalkanı
def _compass_below():
    return {"is_btc_panic": False, "is_btc_above_ema200": False, "regime_shield_active": True}


def test_rising_shield_badge_mode_does_not_block_but_marks_evidence():
    with mock.patch.object(M, "_master_surge_gate_enabled", return_value=True), \
         mock.patch("app.macro_sentiment_service.get_cached_btc_compass", return_value=_compass_below()), \
         mock.patch("app.derivatives_service.get_cached_derivatives_intel", return_value=None), \
         mock.patch.object(config, "RADAR_SHIELD_MODE", "badge"), \
         mock.patch.object(config, "BTC_REGIME_SHIELD_ENABLED", True):
        reason, evidence = M._rising_risk_block_reason("LUNATRY")
    assert reason is None
    assert evidence.get("regime_badge") == "BTC_BEAR_REGIME_SHIELD"
    assert evidence.get("is_btc_above_ema200") is False


def test_rising_shield_block_mode_keeps_hard_block():
    with mock.patch.object(M, "_master_surge_gate_enabled", return_value=True), \
         mock.patch("app.macro_sentiment_service.get_cached_btc_compass", return_value=_compass_below()), \
         mock.patch("app.derivatives_service.get_cached_derivatives_intel", return_value=None), \
         mock.patch.object(config, "RADAR_SHIELD_MODE", "block"), \
         mock.patch.object(config, "BTC_REGIME_SHIELD_ENABLED", True):
        reason, _ = M._rising_risk_block_reason("LUNATRY")
    assert reason == "BTC_BEAR_REGIME_SHIELD"


def test_rising_shield_btc_itself_exempt_in_both_modes():
    for mode in ("badge", "block"):
        with mock.patch.object(M, "_master_surge_gate_enabled", return_value=True), \
             mock.patch("app.macro_sentiment_service.get_cached_btc_compass", return_value=_compass_below()), \
             mock.patch("app.derivatives_service.get_cached_derivatives_intel", return_value=None), \
             mock.patch.object(config, "RADAR_SHIELD_MODE", mode):
            reason, evidence = M._rising_risk_block_reason("BTCTRY")
        assert reason is None and "regime_badge" not in evidence
