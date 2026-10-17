"""Bildirimde dürüst sayılar (2026-10-18): ölçülmüş hedef, kalibre isabet, başabaş, net hedef + bayraklar.

Kaynak: docs/HEDEF_SKOR_OLASILIK_OZET_2026-10-18.md. conftest paket varsayılanını ESKİ davranışa çeker
(`RADAR_TARGET_MODE=chain` vb.); bu dosya yeni davranışı bayrakları AÇIKÇA kurarak sınar.
"""
import asyncio
import math
import os
import sys
from unittest import mock
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database, notify_metrics as nm, unified_signals  # noqa: E402
from app.config import Config, config  # noqa: E402
from app.routers import monitoring, velocity  # noqa: E402


# --------------------------------------------------------------------------- measured_target_pct
class TestMeasuredTarget:
    def test_reference_value(self):
        # ATR 1 %, ufuk 5, skor 70 → exp(a) = exp(0,27)
        assert nm.measured_target_pct(1.0, 5, 70.0) == pytest.approx(math.exp(0.27), abs=1e-3)

    def test_monotone_in_atr(self):
        vals = [nm.measured_target_pct(a, 15, 75.0) for a in (0.1, 0.3, 0.6, 1.0, 2.0, 4.0)]
        assert vals == sorted(vals) and vals[0] < vals[-1]

    def test_monotone_in_horizon(self):
        vals = [nm.measured_target_pct(1.0, h, 75.0) for h in (5, 15, 30, 60)]
        assert vals == sorted(vals) and vals[0] < vals[-1]

    def test_monotone_in_score(self):
        vals = [nm.measured_target_pct(1.0, 5, s) for s in (30, 50, 70, 90, 100)]
        assert vals == sorted(vals) and vals[0] < vals[-1]

    def test_clamp_low_and_high(self):
        assert nm.measured_target_pct(0.05, 5, 30.0) == nm.TARGET_MIN_PCT
        assert nm.measured_target_pct(5.0, 60, 100.0) == nm.TARGET_MAX_PCT

    @pytest.mark.parametrize("atr", [None, float("nan"), float("inf"), -1.0, 0.0, "x"])
    def test_bad_atr_is_safe(self, atr):
        value = nm.measured_target_pct(atr, 5, 80.0)
        assert math.isfinite(value) and nm.TARGET_MIN_PCT <= value <= nm.TARGET_MAX_PCT

    @pytest.mark.parametrize("h,s", [(None, None), (float("nan"), float("nan")), (0, -5), ("x", "y")])
    def test_bad_horizon_score_is_safe(self, h, s):
        value = nm.measured_target_pct(1.0, h, s)
        assert math.isfinite(value) and nm.TARGET_MIN_PCT <= value <= nm.TARGET_MAX_PCT

    def test_coefs_string_and_bad_coefs_fallback(self):
        assert nm.measured_target_pct(1.0, 5, 70.0, "0.0,0.7,0.0,0.5") == pytest.approx(1.0, abs=1e-3)
        assert nm.measured_target_pct(1.0, 5, 70.0, "bozuk") == nm.measured_target_pct(1.0, 5, 70.0)
        assert nm.parse_coefs("1,2,3", (9, 9, 9, 9)) == (9, 9, 9, 9)


# --------------------------------------------------------------------------- hit prob / breakeven / net
class TestHitProb:
    def test_report_table_spot_checks(self):
        # SKOR_DENETIMI §6.1 örnek tablosu (SL %5): ATR 0,3 / hedef 1,5 ≈ %43; ATR 2 / hedef 2 ≈ %67
        assert nm.calibrated_hit_prob(0.3, 1.5, 5, model="logistic") == pytest.approx(0.43, abs=0.03)
        assert nm.calibrated_hit_prob(2.0, 2.0, 5, model="logistic") == pytest.approx(0.67, abs=0.03)
        assert nm.calibrated_hit_prob(1.2, 4.0, 5, model="logistic") == pytest.approx(0.34, abs=0.03)

    def test_default_coefs_match_report(self):
        assert nm.DEFAULT_HIT_PROB_COEFS == (1.106, -0.675, -1.402, 0.059)
        assert Config.RADAR_HIT_PROB_COEFS == "1.106,-0.675,-1.402,0.059"

    def test_higher_target_lowers_prob_and_horizon_term(self):
        low = nm.calibrated_hit_prob(1.0, 1.0, 5, model="logistic")
        high = nm.calibrated_hit_prob(1.0, 3.0, 5, model="logistic")
        assert low > high
        assert (nm.calibrated_hit_prob(1.0, 2.0, 15, model="logistic")
                > nm.calibrated_hit_prob(1.0, 2.0, 5, model="logistic"))

    def test_off_and_invalid_inputs_return_none(self):
        assert nm.calibrated_hit_prob(1.0, 2.0, 5, model="off") is None
        for atr, tgt in ((None, 2.0), (1.0, None), (0, 2.0), (1.0, 0), (float("nan"), 2.0), ("x", 2.0)):
            assert nm.calibrated_hit_prob(atr, tgt, 5, model="logistic") is None

    def test_model_flag_read_from_config(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_HIT_PROB_MODEL", "off", raising=False)
        assert nm.calibrated_hit_prob(1.0, 2.0, 5) is None
        monkeypatch.setattr(config, "RADAR_HIT_PROB_MODEL", "logistic", raising=False)
        assert 0.01 <= nm.calibrated_hit_prob(1.0, 2.0, 5) <= 0.99

    def test_clipped_range(self):
        assert nm.calibrated_hit_prob(5.0, 0.05, 5, model="logistic") == 0.99
        assert 0.01 <= nm.calibrated_hit_prob(0.05, 6.0, 5, model="logistic") <= 0.05


class TestBreakevenAndNet:
    def test_breakeven_formula(self):
        # kazanç = 2,0 − 0,205 = 1,795 ; kayıp = 5 + 0,275 = 5,275 → 5,275 / 7,07
        assert nm.breakeven_hit_prob(2.0, 5.0, 0.205, 0.275) == pytest.approx(5.275 / 7.07, abs=1e-3)

    def test_breakeven_in_reported_band(self):
        # rapor: başabaş isabet %61–73 (hedef ≈ 2–3, SL %5)
        assert 0.60 <= nm.breakeven_hit_prob(3.0, 5.0, 0.205, 0.275) <= 0.75
        assert 0.60 <= nm.breakeven_hit_prob(2.0, 5.0, 0.205, 0.275) <= 0.75

    def test_breakeven_monotone_and_degenerate(self):
        assert nm.breakeven_hit_prob(1.0, 5.0, 0.2, 0.3) > nm.breakeven_hit_prob(4.0, 5.0, 0.2, 0.3)
        assert nm.breakeven_hit_prob(0.1, 5.0, 0.2, 0.3) == 1.0   # hedef maliyeti karşılamıyor
        assert nm.breakeven_hit_prob(None) is None
        assert nm.breakeven_hit_prob(float("nan")) is None
        assert nm.breakeven_hit_prob(0) is None

    def test_breakeven_defaults_from_config(self):
        expected = nm.breakeven_hit_prob(
            2.0, config.AUTO_PAPER_SL_PCT_DEFAULT,
            config.round_trip_cost_tp() * 100, config.round_trip_cost() * 100)
        assert nm.breakeven_hit_prob(2.0) == expected

    def test_target_net(self):
        assert nm.target_net_pct(2.0, 0.205) == pytest.approx(1.795, abs=1e-3)
        assert nm.target_net_pct(2.0) == pytest.approx(2.0 - config.round_trip_cost_tp() * 100, abs=1e-3)
        assert nm.target_net_pct(None) is None
        assert nm.target_net_pct(float("nan")) is None

    def test_notification_metrics_contract_keys(self):
        out = nm.notification_metrics(2.0, 0.8, 5)
        assert set(out) == {"hit_prob_calibrated", "breakeven_hit_prob", "target_net_pct", "score_label"}
        assert out["score_label"] == "hareket_siddeti"
        assert 0.0 < out["hit_prob_calibrated"] < 1.0 and 0.0 < out["breakeven_hit_prob"] <= 1.0
        # ATR yoksa isabet yüzdesi None, diğerleri dolu
        no_atr = nm.notification_metrics(2.0, None, 5)
        assert no_atr["hit_prob_calibrated"] is None and no_atr["breakeven_hit_prob"] is not None


# --------------------------------------------------------------------------- varsayılanlar
class TestDefaults:
    def test_class_defaults(self):
        assert Config.RADAR_TARGET_MODE == "measured"
        assert Config.RADAR_TARGET_MEASURED_COEFS == "0.27,0.71,0.06,0.51"
        assert Config.RADAR_TARGET_ML_BLEND_ENABLED is False
        assert Config.RADAR_NOTIFY_SHOW_ML_PROB is False
        assert Config.RADAR_FUSION_TARGET_DYNAMIC is True
        assert Config.RADAR_HIT_PROB_MODEL == "logistic"
        assert Config.VELOCITY_LATE_PHASE_SCORE_MULT == 1.0
        assert Config.VELOCITY_LEADING_MULTIPLIER == 1.0


# --------------------------------------------------------------------------- dynamic_target_pct
class TestDynamicTargetModes:
    def test_measured_mode_bypasses_chain(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "measured", raising=False)
        # zincirde skor 95 + taban → ≥4,0; ölçülmüş modda yalnız ATR/ufuk/skor
        got = velocity.dynamic_target_pct(95.0, 2.0, atr_pct=0.4, horizon_minutes=5,
                                          learned_pct=5.0, learned_count=20,
                                          ml_pct=6.0, ml_prob=0.9)
        assert got == nm.measured_target_pct(0.4, 5, 95.0, config.RADAR_TARGET_MEASURED_COEFS)
        assert got < 2.0

    def test_measured_mode_allows_below_old_floor(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "measured", raising=False)
        assert velocity.dynamic_target_pct(60.0, 2.0, atr_pct=0.1, horizon_minutes=5) < float(
            config.MONITORING_TARGET_PCT_MIN)

    def test_chain_mode_unchanged_for_panel_false(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "measured", raising=False)
        # panel_score=False (yükseliş sinyali) eski zincirde kalır: net-kâr tabanı uygulanır
        measured_mode_value = velocity.dynamic_target_pct(50.0, 1.0, panel_score=False)
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "chain", raising=False)
        assert measured_mode_value == velocity.dynamic_target_pct(50.0, 1.0, panel_score=False) > 2.0

    def test_chain_mode_old_behaviour(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "chain", raising=False)
        assert velocity.dynamic_target_pct(95.0, 1.0) == 4.0

    def test_ml_blend_flag(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "chain", raising=False)
        monkeypatch.setattr(config, "RADAR_TARGET_ML_BLEND_ENABLED", True, raising=False)
        blended = velocity.dynamic_target_pct(95.0, 1.0, ml_pct=6.0, ml_prob=0.9)
        monkeypatch.setattr(config, "RADAR_TARGET_ML_BLEND_ENABLED", False, raising=False)
        off = velocity.dynamic_target_pct(95.0, 1.0, ml_pct=6.0, ml_prob=0.9)
        assert blended > off
        assert off == velocity.dynamic_target_pct(95.0, 1.0)


# --------------------------------------------------------------------------- füzyon hedefi
class TestFusionTarget:
    def test_fixed_four_removed_when_dynamic(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "measured", raising=False)
        monkeypatch.setattr(config, "RADAR_FUSION_TARGET_DYNAMIC", True, raising=False)
        with patch.object(unified_signals, "_fusion_atr_pct", return_value=0.5):
            target, atr = unified_signals._fusion_target_pct("ABCTRY", 95.0)
        assert atr == 0.5
        assert target == nm.measured_target_pct(0.5, 5, 95.0, config.RADAR_TARGET_MEASURED_COEFS)
        assert target != 4.0

    def test_flag_off_keeps_old_fixed_target(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "chain", raising=False)
        monkeypatch.setattr(config, "RADAR_FUSION_TARGET_DYNAMIC", False, raising=False)
        target, atr = unified_signals._fusion_target_pct("ABCTRY", 95.0)
        assert target == 4.0 and atr is None

    def test_missing_atr_uses_measured_fallback(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_TARGET_MODE", "measured", raising=False)
        monkeypatch.setattr(config, "RADAR_FUSION_TARGET_DYNAMIC", True, raising=False)
        with patch.object(unified_signals, "_fusion_atr_pct", return_value=None):
            target, atr = unified_signals._fusion_target_pct("ABCTRY", 95.0)
        assert atr is None and nm.TARGET_MIN_PCT <= target <= nm.TARGET_MAX_PCT

    def test_atr_from_velocity_candidate(self):
        assert unified_signals._fusion_atr_pct("ABCTRY", {"atr_pct": 0.7}) == 0.7


# --------------------------------------------------------------------------- _build_notification
class _FakeMarket:
    def get_ticker(self, sym):
        return {"last_price": "12.5"}

    def ticker_freshness(self, sym, max_age_sec=None):
        return {"fresh": True, "age_sec": 0.0, "max_age_sec": max_age_sec}


def _build(candidate=None):
    from app.state import market
    cand = {"velocity_score": 3.1, "target_pct": 2.0, "price": 12.0, "horizon_minutes": 5,
            "atr_pct": 0.8, "ml_hit_probability": 0.93, "ml_target_pct": 3.0}
    cand.update(candidate or {})
    with patch.object(market, "get_ticker", _FakeMarket().get_ticker), \
         patch.object(market, "ticker_freshness", _FakeMarket().ticker_freshness), \
         patch.object(monitoring.macd_mtf, "cached_compact", return_value=None):
        return monitoring._build_notification("XYZTRY", cand, {"min_score": 1.0, "min_target_pct": 2.0})


class TestBuildNotification:
    def test_ml_pct_hidden_by_default_but_kept_in_payload(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_NOTIFY_SHOW_ML_PROB", False, raising=False)
        n = _build()
        assert "ML %" not in n["title"] and "ML %" not in n["message"]
        assert n["ml_hit_probability"] == 0.93

    def test_ml_pct_shown_when_flag_on(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_NOTIFY_SHOW_ML_PROB", True, raising=False)
        n = _build()
        assert "ML %93" in n["title"] and "ML %93" in n["message"]

    def test_honest_fields_attached(self, monkeypatch):
        monkeypatch.setattr(config, "RADAR_HIT_PROB_MODEL", "logistic", raising=False)
        n = _build()
        assert n["score_label"] == "hareket_siddeti"
        assert n["hit_prob_calibrated"] == nm.calibrated_hit_prob(0.8, 2.0, 5, model="logistic")
        assert n["breakeven_hit_prob"] == nm.breakeven_hit_prob(2.0)
        assert n["target_net_pct"] == nm.target_net_pct(2.0)

    def test_unified_candidate_without_atr_has_null_prob(self):
        n = _build({"atr_pct": None, "unified_pass": True, "unified_score": 90.0,
                    "unified_sources": ["velocity", "jump"]})
        assert n["hit_prob_calibrated"] is None
        assert n["breakeven_hit_prob"] is not None and n["target_net_pct"] is not None


# --------------------------------------------------------------------------- DB sözleşmesi (sahte bağlantı)
class _Cur:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = 0

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.calls = []
        self.conn = self

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), params))
        return _Cur([(1,)])

    def commit(self):
        pass


def _runner(conn):
    async def run(operation):
        return operation(conn)
    return run


class TestDbContract:
    ENTRY = {"symbol": "XYZTRY", "created_at": 100.0, "target_pct": 2.0, "detected_at": 100.0, "score": 80.0,
             "mode": "trend_devam", "price": 100.0, "expected_price": 102.0, "message": "m", "title": "t",
             "horizon_minutes": 5, "sent_via_push": True, "sources": ["velocity", "jump"]}

    def test_insert_writes_new_columns(self):
        import re
        conn = _Conn()
        entry = dict(self.ENTRY, hit_prob_calibrated=0.42, breakeven_hit_prob=0.71)
        with mock.patch.object(database, "_run_db", _runner(conn)):
            asyncio.run(database.save_monitoring_notifications([entry]))
        sql, params = next(c for c in conn.calls if c[0].startswith("INSERT INTO monitoring_notifications"))
        cols = [c.strip() for c in re.search(r"\(([^)]+)\)", sql.split("monitoring_notifications", 1)[1]).group(1).split(",")]
        assert len(cols) == len(params)
        assert params[cols.index("hit_prob_calibrated")] == 0.42
        assert params[cols.index("breakeven_hit_prob")] == 0.71

    def test_insert_rejects_out_of_range_values(self):
        import re
        conn = _Conn()
        entry = dict(self.ENTRY, hit_prob_calibrated=71.0, breakeven_hit_prob="x")
        with mock.patch.object(database, "_run_db", _runner(conn)):
            asyncio.run(database.save_monitoring_notifications([entry]))
        sql, params = next(c for c in conn.calls if c[0].startswith("INSERT INTO monitoring_notifications"))
        cols = [c.strip() for c in re.search(r"\(([^)]+)\)", sql.split("monitoring_notifications", 1)[1]).group(1).split(",")]
        assert params[cols.index("hit_prob_calibrated")] is None
        assert params[cols.index("breakeven_hit_prob")] is None

    def test_list_selects_new_columns(self):
        conn = _Conn()
        with mock.patch.object(database, "_run_db", _runner(conn)):
            asyncio.run(database.list_monitoring_notifications(limit=5))
        sql = conn.calls[0][0]
        assert "hit_prob_calibrated" in sql and "breakeven_hit_prob" in sql

    def test_update_rewrites_metrics_when_given(self):
        conn = _Conn()
        with mock.patch.object(database, "_run_db", _runner(conn)):
            asyncio.run(database.update_monitoring_notification(
                7, 80.0, 2.0, 100.0, 102.0, 5, "m",
                metrics={"hit_prob_calibrated": 0.4, "breakeven_hit_prob": 0.7}))
        assert any("SET hit_prob_calibrated=%s, breakeven_hit_prob=%s" in c[0] for c in conn.calls)

    def test_migration_file_is_idempotent(self):
        path = os.path.join(os.path.dirname(__file__), "..", "migrations", "025_notify_metrics.sql")
        text = open(path, encoding="utf-8").read()
        assert text.count("ADD COLUMN IF NOT EXISTS") == 2
        assert "hit_prob_calibrated" in text and "breakeven_hit_prob" in text
