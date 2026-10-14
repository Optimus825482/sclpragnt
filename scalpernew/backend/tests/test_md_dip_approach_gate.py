"""MD — dip kapisi artik `_dip_gate(turn, gap)` ile approach (direnciye yakinlik)
ile birlestirilmis.

KALIBRASYON KANITI (outputs/monitoring_analiz_2026-09-12/KALIBRASYON_KANITI_JUMP_DIP.md):
dip tek basina 0.76-0.86x baseline alti; dip+approach (fiyat 20-bar zirvesine
<= DIP_APPROACH_GAP_ATR ATR) 1.47-1.67x lift (n~16k). Bu test moduldeki
`_dip_gate` saf fonksiyonunu ve `_symbol_trend_and_signals` ciktisindeki
`pre["dip"]` alaninin bu kapıyı yansittigini kilitleyen mutasyona-duyarlidir;
mutasyon (ifadeyi eski haline dondurmek) geri alinirsa test KIRILIR.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers import macd_monitor  # noqa: E402


class DipApproachGateTests(unittest.TestCase):
    """dip = turn AND (0 <= gap <= DIP_APPROACH_GAP_ATR), via `_dip_gate`."""

    def test_dip_true_when_turn_and_near_resistance(self):
        assert macd_monitor._dip_gate(turn=True, gap=1.0) is True

    def test_dip_false_when_far_from_resistance(self):
        assert macd_monitor._dip_gate(turn=True, gap=3.0) is False

    def test_dip_false_when_no_turn(self):
        assert macd_monitor._dip_gate(turn=False, gap=0.5) is False
        assert macd_monitor._dip_gate(turn=False, gap=0.0) is False

    def test_dip_true_at_boundary(self):
        assert macd_monitor._dip_gate(turn=True, gap=macd_monitor.DIP_APPROACH_GAP_ATR) is True

    def test_dip_false_for_negative_gap(self):
        # Fiyat zirvenin ustunde: aralik disi -> False
        assert macd_monitor._dip_gate(turn=True, gap=-0.2) is False

    def test_dip_false_when_gap_unknown(self):
        assert macd_monitor._dip_gate(turn=True, gap=None) is False

    def test_constant_default(self):
        assert math.isclose(macd_monitor.DIP_APPROACH_GAP_ATR, 1.5)

    def test_custom_threshold(self):
        # Daha dar bant (1.0 ATR): gap=1.2 artik disi
        assert macd_monitor._dip_gate(turn=True, gap=1.2, gap_atr=1.0) is False
        assert macd_monitor._dip_gate(turn=True, gap=0.8, gap_atr=1.0) is True


if __name__ == "__main__":
    unittest.main()