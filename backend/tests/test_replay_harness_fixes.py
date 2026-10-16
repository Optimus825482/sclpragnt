"""2026-10-16 (harness onarımı): replay/backtest betiklerinin altyapı düzeltmeleri.

Üç kusur: (1) `unified_pool_replay` yalnız sqlite önbelleği okuyordu; (2)
`combined_radar_replay_24h` journal'ı sabit 20000 satırda sessizce kesiyordu;
(3) `run_portfolio_backtest` kaldırılmış canlı stratejiyi ("current") istiyordu.
Testler DB'siz ve ağsızdır; sahte bağlantılar ve geçici sqlite kullanır.
"""
import importlib
import os
import sqlite3
import sys
import types

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("SCALPER_ADMIN_PASSWORD", "test-admin-password-1234")


# ---------------------------------------------------------------- (1) unified_pool_replay
@pytest.fixture
def upr():
    return importlib.import_module("unified_pool_replay")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeConn:
    """psycopg.connect(...) yerine: `execute` çağrılarını kaydeder, sabit satır döner."""
    calls: list = []

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        _FakeConn.calls.append((sql, params))
        return _FakeCursor(self._rows)


def _bar(ts_ms, h, l, c):
    return (ts_ms / 1000.0, float(h), float(l), float(c))


def test_sqlite_missing_file_returns_empty_instead_of_crashing(upr, tmp_path, monkeypatch):
    monkeypatch.setattr(upr, "_DB", str(tmp_path / "yok.sqlite"))
    assert upr._load_prices_sqlite({"AAATRY"}) == {}


def test_sqlite_reads_only_requested_symbols(upr, tmp_path, monkeypatch):
    db = tmp_path / "market_cache.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE klines(symbol TEXT, interval TEXT, open_time INTEGER, "
                 "high REAL, low REAL, close REAL)")
    conn.executemany("INSERT INTO klines VALUES (?,?,?,?,?,?)", [
        ("AAATRY", "5m", 1_000_000, 11, 9, 10),
        ("BBBTRY", "5m", 1_000_000, 21, 19, 20),
        ("AAATRY", "1m", 1_000_000, 99, 1, 50),   # farklı interval → yok sayılır
    ])
    conn.commit(); conn.close()
    monkeypatch.setattr(upr, "_DB", str(db))
    out = upr._load_prices_sqlite({"AAATRY"})
    assert set(out) == {"AAATRY"}
    assert out["AAATRY"] == [_bar(1_000_000, 11, 9, 10)]


def test_postgres_source_queries_historical_candles_5m(upr, monkeypatch):
    rows = [("aaatry", 2_000_000, 12.0, 8.0, 10.0), ("AAATRY", 2_300_000, 13.0, 9.0, 0.0)]
    fake = types.SimpleNamespace(connect=lambda *a, **k: _FakeConn(rows))
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    _FakeConn.calls.clear()
    out = upr._load_prices_postgres({"AAATRY"}, "postgresql://x")
    sql, params = _FakeConn.calls[0]
    assert "historical_candles" in sql and "timeframe='5m'" in sql
    assert params == (["AAATRY"],)
    # close=0 satırı atılır, sembol büyük harfe çevrilir, ms → sn
    assert out == {"AAATRY": [_bar(2_000_000, 12, 8, 10)]}


def test_postgres_source_without_db_url_is_empty(upr):
    assert upr._load_prices_postgres({"AAATRY"}, "") == {}


def test_auto_source_fills_only_missing_symbols_in_order(upr, monkeypatch):
    seen = []
    monkeypatch.setattr(upr, "_load_prices_sqlite",
                        lambda syms: seen.append(("sqlite", set(syms))) or {"AAATRY": [_bar(1, 1, 1, 1)]})
    monkeypatch.setattr(upr, "_load_prices_postgres",
                        lambda syms, url: seen.append(("postgres", set(syms))) or {"BBBTRY": [_bar(1, 2, 2, 2)]})
    monkeypatch.setattr(upr, "_load_prices_rest",
                        lambda syms, days: seen.append(("rest", set(syms))) or {})
    out = upr._load_prices({"AAATRY", "BBBTRY", "CCCTRY"}, source="auto", db_url="u", days=7)
    assert set(out) == {"AAATRY", "BBBTRY"}
    assert [s[0] for s in seen] == ["sqlite", "postgres", "rest"]
    assert seen[1][1] == {"BBBTRY", "CCCTRY"}     # sqlite'ın bulduğu AAATRY tekrar istenmez
    assert seen[2][1] == {"CCCTRY"}


def test_explicit_source_uses_only_that_source_and_survives_failure(upr, monkeypatch):
    monkeypatch.setattr(upr, "_load_prices_sqlite", lambda syms: pytest.fail("sqlite çağrılmamalı"))
    monkeypatch.setattr(upr, "_load_prices_rest", lambda syms, days: pytest.fail("rest çağrılmamalı"))

    def boom(syms, url):
        raise RuntimeError("bağlantı yok")
    monkeypatch.setattr(upr, "_load_prices_postgres", boom)
    assert upr._load_prices({"AAATRY"}, source="postgres", db_url="u") == {}
    with pytest.raises(ValueError):
        upr._load_prices({"AAATRY"}, source="csv")


def test_bars_from_klines_tolerates_bad_rows(upr):
    rows = [[1_000, "1", "3", "0.5", "2", "v"], ["x"], None, [2_000, 1, 4, 1, 3]]
    assert upr._bars_from_klines(rows) == [_bar(1_000, 3, 0.5, 2), _bar(2_000, 4, 1, 3)]


# ---------------------------------------------------------------- (2) combined_radar_replay_24h
@pytest.fixture
def crr():
    return importlib.import_module("combined_radar_replay_24h")


def test_journal_limit_zero_or_none_means_unlimited(crr):
    assert crr._journal_limit(0) == crr._UNLIMITED_JOURNAL_ROWS
    assert crr._journal_limit(None) == crr._UNLIMITED_JOURNAL_ROWS
    assert crr._journal_limit("abc") == crr._UNLIMITED_JOURNAL_ROWS
    assert crr._journal_limit(500) == 500


def test_truncation_flags_only_when_budget_is_finite(crr):
    counts = {"velocity": 20000, "rising": 10, "macd": 20000}
    assert crr._truncation_flags(counts, 20000) == {"velocity": True, "rising": False, "macd": True}
    assert crr._truncation_flags(counts, crr._journal_limit(0)) == {
        "velocity": False, "rising": False, "macd": False}


def test_build_report_and_run_accept_max_journal_rows(crr):
    import inspect
    assert "max_journal_rows" in inspect.signature(crr.build_report).parameters
    assert "max_journal_rows" in inspect.signature(crr.run).parameters


# ---------------------------------------------------------------- (3) run_portfolio_backtest
@pytest.fixture
def rpb():
    return importlib.import_module("run_portfolio_backtest")


def test_current_pine_version_fails_loudly_when_live_strategy_is_gone(rpb):
    assert not hasattr(rpb.ScalpAnalyzer, "strategy_bb_mfi_mean_reversion"), (
        "canlı BB-MFI geri geldiyse bu koruma gözden geçirilmeli")
    with pytest.raises(SystemExit) as exc:
        rpb._validate_pine_version("current")
    assert "HATA" in str(exc.value) and "pine-version v3" in str(exc.value)


def test_reference_profiles_pass_validation(rpb):
    for v in ("v1", "v2", "v3"):
        assert rpb._validate_pine_version(v) == v


def test_module_docstring_and_warning_mark_it_as_reference(rpb):
    assert "REFERANS" in (rpb.__doc__ or "")
    assert "ÖLÇMEZ" in rpb._REFERENCE_WARNING


# ---------------------------------------------------------------- (4) calibrate_combined_paper
@pytest.fixture
def ccp():
    return importlib.import_module("calibrate_combined_paper")


def test_calibrate_pg_bars_reads_historical_candles(ccp, monkeypatch):
    rows = [("aaatry", 2_000_000, 12.0, 8.0, 10.0), ("AAATRY", 2_300_000, 13.0, 9.0, 0.0)]

    class _Cur:
        def fetchall(self):
            return rows

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            _Conn.last = (sql, params)
            return _Cur()

    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=lambda *a, **k: _Conn()))
    out = ccp._load_pg_bars({"AAATRY"}, 1_000.0, 3_000.0)
    sql, params = _Conn.last
    assert "historical_candles" in sql and "timeframe='5m'" in sql
    assert params == (["AAATRY"], 1_000_000, 3_000_000)
    assert out == {"AAATRY": [{"open_time": 2_000.0, "high": 12.0, "low": 8.0, "close": 10.0}]}


def test_calibrate_pg_bars_without_url_or_symbols_is_empty(ccp, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert ccp._load_pg_bars({"AAATRY"}, 0.0, 1.0) == {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert ccp._load_pg_bars(set(), 0.0, 1.0) == {}



# ---------------------------------------------------------------- (5) rescan entegrasyonu
def test_horizon_parser_reads_rescan_ids():
    from app.routers.velocity import _velocity_horizon_from_candidate_id as h
    assert h("rescan:BTCTRY:1760000000000:15") == 15
    assert h("rescan:BTCTRY:1760000000000:5") == 5
    assert h("rescan:BTCTRY:1760000000000:999") == 5
    assert h("vel-15dk-%3-abc") == 15


def test_candidate_source_sql_filters(upr, ccp):
    for mod in (upr, ccp):
        assert "NOT LIKE 'rescan:%%'" in mod._candidate_source_sql("live")
        assert mod._candidate_source_sql("rescan").strip().startswith("AND candidate_id LIKE")
        assert mod._candidate_source_sql("all") == ""
        with pytest.raises(ValueError):
            mod._candidate_source_sql("x")
