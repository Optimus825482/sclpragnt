"""W11c-TAH kilit testleri — TAH-01 (`decided_at` çapası) ve TAH-03 (ε-keşif).

Testler Postgres gerektirmez: `_run_db` yamalanır ve op() sahte bir bağlantıyla
çalıştırılır; böylece hem ÜRETİLEN SQL hem de dönen sonuç doğrulanır.

Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/verify_w11c_tah_mutations.py`.
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database  # noqa: E402
from app.routers import llm_chat  # noqa: E402

BASE_MS = 1_700_000_000_000


def _async_value(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """SQL metnine göre satır döndüren sahte bağlantı; ifadeleri kaydeder."""

    def __init__(self, routes=(), default=()):
        self.routes = list(routes)
        self.default = list(default)
        self.statements = []
        self.calls = []
        self.conn = self

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        self.calls.append((text, params))
        for needle, rows in self.routes:
            if needle in text:
                return _FakeCursor(rows)
        return _FakeCursor(self.default)

    def commit(self):
        pass

    def rollback(self):
        pass


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


def _bars(count=60, spike_index=5, spike_high=110.0):
    timestamps = [BASE_MS + index * 60_000 for index in range(count)]
    highs = [100.0] * count
    highs[spike_index] = spike_high
    return {"timestamps": timestamps, "closes": [100.0] * count,
            "highs": highs, "lows": [99.0] * count}


class ForecastAnchorTests(unittest.TestCase):
    """TAH-01 — ölçüm penceresi fiyatın gözlemlendiği andan başlamalı."""

    def _compute_outcome(self, forecast):
        bars = _bars()

        async def scenario():
            with mock.patch.object(llm_chat.market, "get_ut_kline", lambda *a, **k: bars), \
                 mock.patch.object(llm_chat, "fetch_klines", _async_value([])):
                return await llm_chat._forecast_outcome_from_closed_m1("TESTUSDT", forecast)

        return asyncio.run(scenario())

    def test_window_starts_at_decided_at(self):
        # Fiyat T0'da okundu (`decided_at`), LLM 10 dakika sonra döndü
        # (`created_at`). Dokunuş yalnız T0+5. dakikada gerçekleşiyor.
        outcome = self._compute_outcome({
            "created_at": (BASE_MS + 600_000) / 1000.0,
            "decided_at": BASE_MS / 1000.0,
            "horizon_minutes": 5,
            "entry_price": 100.0,
            "min_move_pct": 0.005,
            "direction": "up",
        })
        assert outcome is not None, "ölçüm üretilmedi"
        assert outcome["first_hit_minutes"] == 5.0, outcome
        assert outcome["max_high"] == 110.0, outcome

    def test_legacy_rows_fall_back_to_created_at(self):
        # `decided_at` kolonu öncesi satırlar: çapa `created_at` olmalı.
        outcome = self._compute_outcome({
            "created_at": (BASE_MS + 600_000) / 1000.0,
            "horizon_minutes": 5,
            "entry_price": 100.0,
            "min_move_pct": 0.005,
            "direction": "up",
        })
        assert outcome is not None
        assert outcome["first_hit_minutes"] is None, outcome
        assert outcome["max_high"] == 100.0, outcome

    def test_anchor_is_read_from_the_persisted_row(self):
        # `_forecast_row` sözlüğü olduğu gibi geçirilir; `decided_at` kolonu
        # varsa kullanılmalı, yoksa `created_at`e düşülmeli.
        row = database._forecast_row({
            "created_at": 111.0, "decided_at": 42.0, "horizon_minutes": 5,
            "snapshot": "{}", "timeframe_context": "{}",
        })
        assert row["decided_at"] == 42.0


class DecidedAtPersistenceTests(unittest.TestCase):
    """TAH-01 — `decided_at` INSERT'e girmeli ve `created_at`e düşebilmeli."""

    def _save(self, rows):
        class _RecordingConn(_RoutedConn):
            def executemany(self, sql, values):
                self.sql = " ".join(str(sql).split())
                self.values = list(values)

        conn = _RecordingConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(database.save_llm_forecasts(rows))
        return conn

    def _row(self, created_at, decided_at=None):
        row = {
            "forecast_id": "f1", "forecast_group_id": "g1", "symbol": "BTCUSDT",
            "created_at": created_at, "horizon_minutes": 5, "entry_price": 100.0,
            "direction": "up", "confidence": 50.0, "min_move_pct": 0.02,
            "snapshot_hash": "h", "snapshot": {}, "timeframe_context": {},
        }
        if decided_at is not None:
            row["decided_at"] = decided_at
        return row

    def test_insert_lists_the_decided_at_column(self):
        conn = self._save([self._row(200.0, 100.0)])
        assert "decided_at" in conn.sql

    def test_decided_at_is_written_when_present(self):
        conn = self._save([self._row(200.0, 100.0)])
        assert conn.values[0][4] == 100.0

    def test_decided_at_falls_back_to_created_at(self):
        conn = self._save([self._row(200.0)])
        assert conn.values[0][4] == 200.0

    def test_parameter_count_matches_the_column_list(self):
        conn = self._save([self._row(200.0, 100.0)])
        columns = conn.sql.split("(", 1)[1].split(")", 1)[0].count(",") + 1
        assert columns == len(conn.values[0]), (columns, len(conn.values[0]))


class InitDbDecidedAtColumnTests(unittest.TestCase):
    """TAH-01 — kolon her açılışta idempotent olarak eklenmeli."""

    def _run_init_db(self):
        conn = _RoutedConn(routes=[("to_regclass", [[None]])])

        async def _noop_backfill():
            return 0

        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "backfill_position_trade_ids", _noop_backfill):
            asyncio.run(database.init_db())
        return conn

    def test_decided_at_column_is_added(self):
        conn = self._run_init_db()
        assert any("llm_forecasts ADD COLUMN IF NOT EXISTS decided_at" in s
                   for s in conn.statements), conn.statements[-12:]


class ExplorationUniverseTests(unittest.TestCase):
    """TAH-03 — ε-keşif satırları AYRI ailede journal'lanmalı."""

    def _candidate(self, symbol, velocity_score, price=100.0, horizon=5):
        return {
            "symbol": symbol, "price": price, "horizon_minutes": horizon,
            "target_pct": 2.0 if horizon <= 5 else 3.0,
            "velocity_score": velocity_score, "passes": True,
            "rsi": 55.0, "mfi": 50.0, "atr_pct": 0.8, "bb_width_pct": 1.2,
            "ret3_pct": 0.4, "linreg_slope10_pct": 0.1,
            "aroon_up": 70.0, "aroon_down": 30.0,
            "m5_pattern_ok": True, "leading_ok": True,
            "ml_features_5m": {"atr_pct": 0.8, "ret3_pct": 0.4, "rsi": 55.0},
            "last_closed_at": BASE_MS,
        }

    def _scout(self):
        saved = []

        async def fake_scan(_payload, horizon_minutes=5):
            if horizon_minutes != 5:
                return {"candidates": [], "watchlist": []}
            return {"candidates": [
                self._candidate("AAAUSDT", 40.0), self._candidate("BBBUSDT", 35.0),
                self._candidate("CCCUSDT", 30.0), self._candidate("DDDUSDT", 25.0),
                self._candidate("EEEUSDT", 20.0), self._candidate("FFFUSDT", 15.0),
            ], "watchlist": []}

        async def fake_save(rows):
            saved.extend(rows)
            return len(rows)

        async def scenario():
            with mock.patch.object(llm_chat, "detect_velocity_candidates", fake_scan), \
                 mock.patch.object(llm_chat, "_journal_touch_rates", _async_value({})), \
                 mock.patch.object(llm_chat, "_velocity_journal_quality", _async_value(None)), \
                 mock.patch.object(llm_chat.ml_forecast, "predict_target", lambda *a, **k: None), \
                 mock.patch.object(llm_chat.database, "get_llm_forecast_lessons", _async_value([])), \
                 mock.patch.object(llm_chat.database, "save_llm_forecasts", fake_save), \
                 mock.patch.object(llm_chat.llm_analysis, "analyze",
                                   _async_value({"enabled": True, "status": "ok",
                                                 "text": "", "model": "stub"})), \
                 mock.patch.object(llm_chat.embedding_worker, "enqueue_persistent",
                                   _async_value(True)):
                return await llm_chat._upside_scout_impl()

        return asyncio.run(scenario()), saved

    def test_exploration_rows_use_a_separate_prompt_family(self):
        result, saved = self._scout()
        assert result["status"] == "ok", result
        versions = {row["prompt_version"] for row in saved}
        assert "upside-scout-v2-blend" in versions, versions
        assert "upside-explore-v1" in versions, versions
        # Başlık metriği ailesi (`upside-scout-%`) kirletilmemeli.
        assert not any(v.startswith("upside-scout-") and "explore" in v for v in versions)

    def test_headline_metric_covers_only_the_top_three(self):
        result, saved = self._scout()
        headline = [r for r in saved if r["prompt_version"].startswith("upside-scout-")]
        assert len(headline) == 3, [r["symbol"] for r in headline]
        assert result["journal_saved"] == 3, result
        assert result["journal_saved_exploration"] == 2, result

    def test_coverage_reports_both_universes(self):
        result, _ = self._scout()
        coverage = result["coverage"]
        assert coverage["ranked_pool"] == 6, coverage
        assert coverage["journaled_top"] == 3, coverage
        assert coverage["exploration_journaled"] == 2, coverage

    def test_exploration_rows_carry_the_observation_anchor(self):
        _, saved = self._scout()
        explore = [r for r in saved if r["prompt_version"] == "upside-explore-v1"]
        assert explore, "ε-keşif satırı yok"
        for row in explore:
            assert row["decided_at"] <= row["created_at"], row
            assert row["snapshot"]["price_observed_at"] == row["decided_at"]

    def test_top_rows_carry_the_scan_anchor(self):
        _, saved = self._scout()
        headline = [r for r in saved if r["prompt_version"].startswith("upside-scout-")]
        for row in headline:
            assert row["decided_at"] <= row["created_at"], row
            assert row["snapshot"]["price_observed_at"] == row["decided_at"]


class ExplorationReportTests(unittest.TestCase):
    """TAH-03 — keşif evreni başlık metriğinden ayrı sorgulanabilmeli."""

    def _report(self, source):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(database.get_llm_forecast_report(source))
        return conn

    def test_exploration_source_uses_its_own_family(self):
        conn = self._report("upside_explore")
        assert conn.calls, "sorgu üretilmedi"
        assert conn.calls[0][1] == ("upside-explore-%",), conn.calls[0][1]

    def test_headline_source_is_unchanged(self):
        conn = self._report("upside_scout")
        assert conn.calls[0][1] == ("upside-scout-%",), conn.calls[0][1]


if __name__ == "__main__":
    unittest.main()
