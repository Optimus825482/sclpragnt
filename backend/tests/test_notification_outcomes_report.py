"""notification_outcomes_report / horizon_grid_report / radar_periodic_review testleri.

Sentetik bildirim satırları ve sentetik 5m mumlarla: hit / MFE / net hesabı, şans tabanı
aralığı, karşı-olgusal senaryo süzgeci, signals kaynağı ayrıştırması ve betiklerin
DATABASE_URL olmadan import edilebilmesi doğrulanır. DB gerekmez.
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import horizon_grid_report as hgr  # noqa: E402
from scripts import notification_outcomes_report as nor  # noqa: E402
from scripts import radar_periodic_review as rpr  # noqa: E402

T0 = 1_790_000_000.0  # sn; ilk mum bu andan 1 sn SONRA açılır (det = T0 - 1 ... )


def _candle_rows(sym, closes, *, start=T0, hi_mult=1.0005, lo_mult=0.9995, overrides=None):
    """(sym, open_time_ms, high, low, close, open) satırları; override: {i: (high, low, close)}."""
    rows = []
    for i, c in enumerate(closes):
        h, l, cl = c * hi_mult, c * lo_mult, c
        if overrides and i in overrides:
            h, l, cl = overrides[i]
        rows.append((sym, (start + i * 300) * 1000, h, l, cl, c))
    return rows


def _flat_store(n=30, price=100.0, overrides=None, sym="AAA"):
    return nor.CandleStore.from_rows(_candle_rows(sym, [price] * n, overrides=overrides))


def _arrays(store, sym="AAA"):
    return store.d[sym]


# ----------------------------------------------------------------- eval_window
def test_eval_window_hit_mfe_net():
    store = _flat_store(overrides={2: (102.5, 99.9, 101.0)})
    ot, hi, lo, cl = _arrays(store)
    e = nor.eval_window(ot, hi, lo, cl, T0 - 1, 100.0, 2.0, 30)
    assert e is not None
    assert e["hit"] is True
    assert e["mfe"] == pytest.approx(2.5)
    assert e["net"] == pytest.approx(2.0 - nor.COST)  # TP vuruldu
    assert e["mae"] == pytest.approx((99.9 / 100 - 1) * 100)


def test_eval_window_stop_wins_same_bar_and_costs():
    # Aynı mumda hem TP hem SL: SL önce (kötümser).
    store = _flat_store(overrides={1: (103.0, 96.0, 100.0)})
    ot, hi, lo, cl = _arrays(store)
    e = nor.eval_window(ot, hi, lo, cl, T0 - 1, 100.0, 2.0, 30, sl=3.0, cost=0.35)
    assert e["hit"] is True  # MFE hedefi aştı (hit tanımı)
    assert e["net"] == pytest.approx(-3.0 - 0.35)


def test_eval_window_timeout_uses_last_close():
    closes = [100.0] * 6
    rows = _candle_rows("AAA", closes, hi_mult=1.001, lo_mult=0.999, overrides={5: (100.4, 99.9, 100.3)})
    store = nor.CandleStore.from_rows(rows)
    ot, hi, lo, cl = _arrays(store)
    e = nor.eval_window(ot, hi, lo, cl, T0 - 1, 100.0, 2.0, 30)
    assert e["hit"] is False
    assert e["net"] == pytest.approx(0.3 - nor.COST)


def test_eval_window_no_lookahead_excludes_candles_at_or_before_detection():
    # Bildirimden ÖNCE açılan mum (i=0) devasa high taşır; ölçüme girmemeli.
    store = _flat_store(overrides={0: (150.0, 99.9, 100.0)})
    ot, hi, lo, cl = _arrays(store)
    e = nor.eval_window(ot, hi, lo, cl, T0 + 1, 100.0, 2.0, 30)  # det mum 0 açıldıktan sonra
    assert e is not None
    assert e["mfe"] < 1.0 and e["hit"] is False


def test_eval_window_insufficient_coverage_returns_none():
    store = _flat_store(n=3)
    ot, hi, lo, cl = _arrays(store)
    assert nor.eval_window(ot, hi, lo, cl, T0 - 1, 100.0, 2.0, 60) is None
    # ilk mum bildirimden >10 dk sonra
    store2 = _flat_store(n=30)
    ot, hi, lo, cl = _arrays(store2)
    assert nor.eval_window(ot, hi, lo, cl, T0 - 1200, 100.0, 2.0, 30) is None


# -------------------------------------------------------------------- istatistik
def test_wilson_bounds():
    lo, hi = nor.wilson(50, 100)
    assert 0 <= lo < 50 < hi <= 100
    assert math.isnan(nor.wilson(0, 0)[0])
    lo0, hi0 = nor.wilson(0, 10)
    assert lo0 == 0.0 and hi0 > 0


def test_spearman_and_fisher_known_values():
    rho, p = nor.spearman([1, 2, 3, 4, 5, 6], [2, 1, 4, 3, 6, 5])
    assert rho == pytest.approx(0.8286, abs=1e-3)
    assert nor.spearman([1, 2, 3, 4], [4, 3, 2, 1])[0] == pytest.approx(-1.0)
    assert math.isnan(nor.spearman([1, 1, 1], [1, 2, 3])[0])
    # [[3,1],[1,3]] iki yönlü Fisher p = 0.4857
    assert nor.fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857, abs=1e-3)
    assert nor.fisher_exact(10, 0, 0, 10) < 1e-4


def test_statistics_match_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(3)
    x, y = rng.normal(size=60), rng.normal(size=60)
    y[::5] = y[::5] + 1
    assert nor.spearman(x, y)[0] == pytest.approx(scipy_stats.spearmanr(x, y)[0], abs=1e-9)
    assert nor.fisher_exact(12, 8, 5, 15) == pytest.approx(scipy_stats.fisher_exact([[12, 8], [5, 15]])[1], rel=1e-6)


def test_parse_sources_variants():
    assert nor.parse_sources('["velocity","jump"]') == ["jump", "velocity"]
    assert nor.parse_sources("velocity, jump") == ["jump", "velocity"]
    assert nor.parse_sources("") == []
    assert nor.parse_sources(None) == []
    assert nor.score_bucket(99.95) == "4 95-99.9" and nor.score_bucket(120) == "5 100+"


# -------------------------------------------------------------------- şans tabanı
def _periodic_store(sym="AAA", n=1200):
    closes = [100.0 * (1 + 0.002 * math.sin(i / 3.0)) for i in range(n)]
    return nor.CandleStore.from_rows(_candle_rows(sym, closes, hi_mult=1.001, lo_mult=0.999))


def test_chance_baseline_within_unit_interval():
    store = _periodic_store()
    ot = store.d["AAA"][0]
    det = ot[600] / 1000 + 300 + 1  # idx 601 ve sonrası mumlar "sonra"
    row = nor.normalize_notification_row((1, "AAA", 90.0, 1.0, 100.0, 60, "trend_devam", det, '["velocity"]', None,
                                          None, None, None, None, None))
    N, _ = nor.build_records([row], store)
    nor.mark_dedup(N)
    nor.compute_chance(N, store, np.random.default_rng(7))
    assert N[0][60] is not None
    base = N[0]["null"]
    assert base is not None and base["k"] >= 8
    for key in ("null", "null2", "null3"):
        b = N[0][key]
        if b is not None:
            assert 0.0 <= b["hit"] <= 1.0
            assert math.isfinite(b["net"])


# ------------------------------------------------------------ karşı-olgusal senaryo
def _rec(mode, score, src=()):
    return dict(mode=mode, score=score, src=list(src))


def test_counterfactual_current_policy_keeps_right_rows():
    scen = dict(nor.build_scenarios(["notr", "v_donusu", "llm_ikinci_goz"], 95.0))
    pol = next(f for k, f in scen.items() if k.startswith("c "))
    assert pol(_rec("trend_devam", 70)) is True
    assert pol(_rec("global_lead_lag", 60)) is True
    assert pol(_rec("notr", 99)) is False
    assert pol(_rec("llm_ikinci_goz", 99)) is False
    assert pol(_rec("unified", 94.9)) is False
    assert pol(_rec("unified", 95.0)) is True
    sq = next(f for k, f in scen.items() if k.startswith("a "))
    assert sq(_rec("unified", 90, ["short_squeeze", "snapback"])) is False
    assert sq(_rec("unified", 90, ["short_squeeze", "velocity"])) is True
    only_td = next(f for k, f in scen.items() if k.startswith("e "))
    assert only_td(_rec("trend_devam", 50)) and not only_td(_rec("unified", 99))


# ------------------------------------------------------------------ signals kaynağı
def test_signals_source_parses_and_reports_strategy_ranges():
    rowt = nor.normalize_signal_row((7, T0 - 1, "AAA", "BUY_SIGNAL", 100.0, "GLOBAL_LEAD_LAG"))
    assert rowt["mode"] == "GLOBAL_LEAD_LAG" and rowt["score"] is None and rowt["target_pct"] is None
    assert rowt["detected_at"] == T0 - 1 and rowt["price"] == 100.0
    assert nor.normalize_signal_row((8, T0, "AAA", "BUY_SIGNAL", 100.0, None))["mode"] == "(bos)"

    store = _flat_store(n=30, overrides={2: (101.7, 99.9, 100.5)})
    rows = [rowt, nor.normalize_signal_row((9, T0 - 2, "AAA", "BUY_SIGNAL", 100.0, "OLD_STRAT"))]
    md, summary = nor.generate_report(rows, store, source="signals", since_ts=T0 - 86400, min_n=1)
    assert "GLOBAL_LEAD_LAG" in md and "OLD_STRAT" in md
    assert "Sabit hedef %1.5" in md and "Sabit hedef %3" in md
    assert set(summary["targets"]) == {"1.5", "2", "3"}
    # MFE 1.7 %: %1.5 hedefi vuruldu, %2 ve %3 vurulmadı
    assert summary["targets"]["1.5"]["n60"] == 2
    assert summary["targets"]["1.5"]["hit60"] == pytest.approx(100.0)
    assert summary["targets"]["2"]["hit60"] == pytest.approx(0.0)
    assert summary["targets"]["3"]["hit60"] == pytest.approx(0.0)
    assert summary["strategies"]["GLOBAL_LEAD_LAG"]["n"] == 1


def test_notification_report_end_to_end_synthetic():
    store = _periodic_store()
    ot = store.d["AAA"][0]
    rows = []
    for k, (mode, score) in enumerate([("trend_devam", 98.0), ("unified", 80.0), ("notr", 90.0), ("unified", 96.0)]):
        det = ot[100 + 150 * k] / 1000 + 301
        rows.append(nor.normalize_notification_row((k + 1, "AAA", score, 0.5, 100.0, 60, mode, det,
                                                    '["velocity"]', None, None, None, None, None, None)))
    md, summary = nor.generate_report(rows, store, source="notifications", since_ts=float(ot[0] / 1000), min_n=1)
    assert "Karsi-olgusal" in md and "GUNCEL POLITIKA" in md
    assert summary["n60"] == 4
    assert 0 <= summary["hit60"] <= 100
    assert nor._clean({"a": float("nan"), "b": np.float64(1.5)}) == {"a": None, "b": 1.5}


# ------------------------------------------------------------- import / DATABASE_URL
@pytest.mark.parametrize("name", ["notification_outcomes_report", "horizon_grid_report", "radar_periodic_review"])
def test_scripts_import_without_database_url(monkeypatch, name):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    mod = importlib.reload(importlib.import_module(f"scripts.{name}"))
    assert hasattr(mod, "main")


def test_db_url_exits_without_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        nor._db_url()
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    assert nor._db_url() == "postgresql://x/y"


# --------------------------------------------------------------- horizon çıkış kuralları
def test_horizon_stop_fills_at_open_when_gapped():
    # Mum 1: açılış -6 % (stop -3 altında), low -7. Dolum açılışta (-6), -3 değil.
    hp = np.array([[0.5, 0.2, 0.1]])
    lp = np.array([[-0.5, -7.0, -7.0]])
    op = np.array([[0.0, -6.0, -6.5]])
    for fn in (hgr.ev_tpsl, hgr.ev_trail):
        idx, ret = fn(hp, lp, op, 4.0, 3.0)
        assert idx[0] == 1
        assert ret[0] == pytest.approx(-6.0)
    # Gap yoksa stop seviyesinde dolum
    op2 = np.array([[0.0, -1.0, -1.0]])
    idx, ret = hgr.ev_tpsl(hp, lp, op2, 4.0, 3.0)
    assert ret[0] == pytest.approx(-3.0)


def test_horizon_tp_and_gross_of():
    hp = np.array([[1.0, 5.0, 5.0], [0.5, 0.5, 0.5]])
    lp = np.array([[-1.0, -1.0, -1.0], [-1.0, -1.0, -1.0]])
    op = np.zeros((2, 3))
    idx, ret = hgr.ev_tpsl(hp, lp, op, 4.0, 3.0)
    assert idx[0] == 1 and ret[0] == pytest.approx(4.0)
    assert idx[1] >= hgr.BIG
    cend = np.array([0.1, -0.2])
    g = hgr.gross_of(idx, ret, np.array([3, 3]), cend)
    assert g[0] == pytest.approx(4.0) and g[1] == pytest.approx(-0.2)


def test_horizon_report_runs_on_synthetic_data():
    n = 2000
    closes = [100.0 * (1 + 0.003 * math.sin(i / 5.0)) for i in range(n)]
    store = nor.CandleStore.from_rows(_candle_rows("AAA", closes, hi_mult=1.002, lo_mult=0.998))
    ot = store.d["AAA"][0]
    rows = [dict(id=i, symbol="AAA", score=96.0, target_pct=1.0, price=closes[200 + 40 * i],
                 mode="trend_devam", detected_at=ot[200 + 40 * i] / 1000 + 301) for i in range(12)]
    md, summary = hgr.generate_report(rows, store, since_ts=float(ot[0] / 1000))
    assert summary["n"] == 12
    assert "## 2. Net getiri proxy" in md and "## 4. Sans tabani" in md


# ------------------------------------------------------------ radar_periodic_review
def test_parse_config_flags_and_values():
    text = '''
    A = os.getenv("RADAR_ONE", "abc").strip()
    B = max(0.0, float(os.getenv("RADAR_TWO", "").strip() or "95.0"))
    C = os.getenv("AUTO_PAPER_THREE", "5")
    D = os.getenv("OTHER_FLAG", "x")
    E = os.getenv("RADAR_ONE", "zzz")
    '''
    flags = dict(rpr.parse_config_flags(text))
    assert flags == {"AUTO_PAPER_THREE": "5", "RADAR_ONE": "abc", "RADAR_TWO": "95.0"}
    vals = {n: (v, s) for n, v, s in rpr.flag_values(sorted(flags.items()), {"RADAR_ONE": "q"})}
    assert vals["RADAR_ONE"] == ("q", "env") and vals["RADAR_TWO"] == ("95.0", "varsayilan")


def test_parse_real_config_has_known_flags():
    flags = dict(rpr.parse_config_flags(rpr.CONFIG_PATH.read_text(encoding="utf-8")))
    assert "RADAR_NOTIFY_UNIFIED_MIN_SCORE" in flags
    assert flags["RADAR_NOTIFY_UNIFIED_MIN_SCORE"] == "95.0"


def test_build_karar_flags_modes_and_families():
    summary = dict(
        n60=500, net60=-0.4, chance_net60=-0.5,
        by_family={"jump": dict(n=100, hit60=20.0, chance_hit60=30.0, lift_pp=-10.0),
                   "velocity": dict(n=100, hit60=40.0, chance_hit60=30.0, lift_pp=10.0)},
        by_mode={"notr": dict(n=120, hit60=30.0, chance_hit60=40.0, lift_pp=-10.0),
                 "unified": dict(n=90, hit60=10.0, chance_hit60=12.0, lift_pp=-2.0),
                 "trend_devam": dict(n=200, hit60=50.0, chance_hit60=35.0, lift_pp=15.0)},
        by_score_bucket={"3 85-95": dict(n=100, hit60=30.0, chance_hit60=28.0, lift_pp=2.0),
                         "5 100+": dict(n=100, hit60=50.0, chance_hit60=35.0, lift_pp=15.0)},
        scenarios={})
    lift_text = "KARAR: lift<1.0 olan aileler: ['short_squeeze', 'fusion']"
    karar = "\n".join(rpr.build_karar(summary, lift_text, min_n=30, unified_min_score=95.0, modes_disabled=["notr"]))
    assert "short_squeeze, fusion" in karar
    assert "jump" in karar  # sans altı aile
    assert "notr" in karar and "zaten kapali" in karar
    assert "unified (n=90" in karar and "KAPATMA ADAYI" in karar
    assert "Taban gerekceli" in karar
    assert rpr.parse_lift_karar(lift_text) == ["short_squeeze", "fusion"]
