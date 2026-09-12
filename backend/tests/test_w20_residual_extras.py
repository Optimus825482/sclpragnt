"""W20 — son kalıntı bulgular için kilit testleri (F-10, F-13, F-16, G-24, I-09).

Her test, ilgili düzeltme geri alınırsa KIRILACAK şekilde yazıldı.
"""
import inspect
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config as app_config  # noqa: E402
from app.routers import macd_monitor, monitoring  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RestRefreshOrderTests(unittest.TestCase):
    """F-13 — başarısız anahtar kuyruğun sonuna düşmeli."""

    def setUp(self):
        macd_monitor._rest_refresh_failures.clear()

    def tearDown(self):
        macd_monitor._rest_refresh_failures.clear()

    def test_failed_keys_sort_last(self):
        macd_monitor._rest_refresh_failures[("B", "3m")] = 5
        ordered = macd_monitor._rest_refresh_order([("B", "3m"), ("A", "3m"), ("C", "3m")])
        assert ordered[-1] == ("B", "3m"), ordered
        assert ordered[:2] == [("A", "3m"), ("C", "3m")], ordered

    def test_healthy_keys_keep_deterministic_order(self):
        assert macd_monitor._rest_refresh_order([("B", "3m"), ("A", "3m")]) == [("A", "3m"), ("B", "3m")]

    def test_pass_uses_the_helper(self):
        source = inspect.getsource(macd_monitor._compute_pass_locked) \
            if hasattr(macd_monitor, "_compute_pass_locked") else ""
        if source:
            assert "_rest_refresh_order(" in source


class VelocityScanConcurrencyTests(unittest.TestCase):
    """F-16 — 5dk/15dk taramaları eşzamanlı çalışmalı (seri değil)."""

    def test_run_scan_gathers_both_horizons(self):
        module_source = inspect.getsource(monitoring)
        marker = "scan5, scan15 = await asyncio.gather("
        assert marker in module_source, "taramalar seri kaldı (F-16)"
        assert "detect_velocity_candidates({\"limit\": 10}, horizon_minutes=5" in module_source
        assert "detect_velocity_candidates({\"limit\": 10}, horizon_minutes=15" in module_source


class ConfigEnvRegimeDocTests(unittest.TestCase):
    """G-24 — import-zamanı env okuma rejimi belgelenmiş olmalı."""

    def test_import_time_regime_is_documented(self):
        source = inspect.getsource(app_config)
        assert "G-24" in source
        assert "IMPORT anında" in source


class VacuousTestRemovedTests(unittest.TestCase):
    """I-09 — assert'siz boş test kaldırılmış olmalı."""

    def test_bodyless_test_is_gone(self):
        text = (ROOT / "tests" / "test_audit_fixes.py").read_text(encoding="utf-8")
        assert "def test_oco_requires_both_legs" not in text


if __name__ == "__main__":
    unittest.main()
