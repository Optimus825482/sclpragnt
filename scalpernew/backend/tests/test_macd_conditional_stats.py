"""Aşama 4 — REJİM / SEANS koşullu isabet için etiket yardımcıları (AAM 4).

Roadmap: `outputs/macd_monitor_erken_sinyal_yol_haritasi.md` Aşama 4.
Bu testler YALNIZCA tanı lazıcı etiketleme yardımcılarını kilitler; sinyal
davranışını değiştirmezler (ölçüm katmanı).
"""
import time
import unittest

from app.routers import macd_monitor as mm


class RegimeTagTests(unittest.TestCase):
    def test_trend_up_highvol(self):
        row = {"r2": 0.72, "dir": 0.9, "sigs": {"5m": {"state": "expand"}}}
        self.assertEqual("trend_up:highvol", mm._regime_tag(row))

    def test_trend_down_lowvol(self):
        row = {"r2": 0.60, "dir": -0.4, "sigs": {"15m": {"state": "squeeze"}}}
        self.assertEqual("trend_down:lowvol", mm._regime_tag(row))

    def test_sideways_normal_vol(self):
        row = {"r2": 0.10, "dir": 0.1, "sigs": {}}
        self.assertEqual("sideways:normalvol", mm._regime_tag(row))

    def test_mixed_vol_expand_wins(self):
        row = {"r2": 0.30, "dir": 0.5, "sigs": {"5m": {"state": "expand"}}}
        self.assertEqual("mixed:highvol", mm._regime_tag(row))

    def test_undef_when_no_r2(self):
        row = {"r2": None, "sigs": {}}
        self.assertEqual("undef:normalvol", mm._regime_tag(row))

    def test_empty_row(self):
        self.assertEqual("undef:normalvol", mm._regime_tag({}))


class SessionTagTests(unittest.TestCase):
    """Saat kovası UTC+3 sabit: İstanbul saati baz alınır."""

    def _ts(self, ist_hour: int) -> float:
        # UTC+3: local = utc+3 → utc = ist_hour - 3 günü taşabilir.
        from datetime import datetime, timezone
        dt = datetime(2026, 9, 1, ist_hour, 0, tzinfo=timezone.utc)
        return dt.timestamp() - 3 * 3600

    def test_buckets(self):
        self.assertEqual("gece", mm._session_tag(self._ts(2)))
        self.assertEqual("sabah", mm._session_tag(self._ts(8)))
        self.assertEqual("oglen", mm._session_tag(self._ts(12)))
        self.assertEqual("ogleden_sonra", mm._session_tag(self._ts(16)))
        self.assertEqual("aksam", mm._session_tag(self._ts(20)))
        self.assertEqual("gece_gec", mm._session_tag(self._ts(23)))

    def test_defensive_float_input(self):
        self.assertIsInstance(mm._session_tag(time.time()), str)


if __name__ == "__main__":
    unittest.main()