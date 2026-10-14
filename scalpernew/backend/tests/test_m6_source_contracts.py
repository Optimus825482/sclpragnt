"""M6 — auto_paper giriş kapıları için kaynak-sözleşme kilitleri (R3-06/07/08/09).

Her test ilgili düzeltme geri alınırsa KIRILIR. Davranış kilitleri (DB tarafı)
`test_m4_database_fixes.py` içindedir; bu dosya kablolama sözleşmesini doğrular.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import analyzer  # noqa: E402
from app.routers import auto_paper  # noqa: E402
from app.routers import monitoring  # noqa: E402

RUTERS = os.path.dirname(os.path.abspath(auto_paper.__file__))


class ReopenKeyContractTests(unittest.TestCase):
    """R3-09 — reopen kararlı notification_key ile churn korumasına girmeli."""

    def test_reopen_builds_a_string_notification_key(self):
        src = inspect.getsource(auto_paper)
        assert "notification_key" in src, "reopen notification_key yok"
        assert "get_recent_auto_paper_trade_by_notification_key" in src
        # String key bigint'e yazılmamalı; kararlı TEXT anahtar üretimi var.
        assert "f\"reopen:" in src or "reopen:{str(symbol).upper()}:{bucket}" in src

    def test_open_path_consults_the_key_first(self):
        src = inspect.getsource(auto_paper.try_open_from_notification)
        assert "get_recent_auto_paper_trade_by_notification_key" in src
        assert "notification_key" in src


class QuietHoursHaltContractTests(unittest.TestCase):
    """R3-07 — sessiz saatler otonom açılışı durdurmalı."""

    def test_quiet_hours_gate_is_wired(self):
        src = inspect.getsource(auto_paper)
        assert "_monitoring_mod.quiet_hours_active" in src or "quiet_hours_active" in src
        assert 'return _blocked(symbol, "quiet_hours")' in src

    def test_monitoring_exports_quiet_hours_active(self):
        assert callable(getattr(monitoring, "quiet_hours_active", None))


class EntryGateContractTests(unittest.TestCase):
    """R3-06 — likidite + korelasyon + passes kapısı kablolu olmalı."""

    def test_auto_paper_has_a_liquidity_cluster_gate(self):
        src = inspect.getsource(auto_paper)
        assert "entry_liquidity_preflight" in src
        assert "_blocked(symbol, \"liquidity\")" in src
        assert "cluster_entry_blocked" in src

    def test_analyzer_exposes_cluster_entry_blocked(self):
        method = getattr(analyzer.ScalpAnalyzer, "cluster_entry_blocked", None)
        assert callable(method), "ScalpAnalyzer.cluster_entry_blocked yok"
        src = inspect.getsource(method)
        assert "cluster_exposure" in src
        assert "MAX_CLUSTER_EXPOSURE_PCT" in src

    def test_passes_guard_blocks_false_candidates(self):
        src = inspect.getsource(auto_paper.try_open_from_notification)
        assert "passes" in src
        assert '"not_passing"' in src


if __name__ == "__main__":
    unittest.main()