"""`app.rescan.stochrsi` — Wilder RSI, StochRSI K/D, ön sinyal."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import stochrsi as S


def _ref_rsi(c, p):
    """Saf Python referans (döngü)."""
    out = [float("nan")] * len(c)
    d = [c[i + 1] - c[i] for i in range(len(c) - 1)]
    g = [max(x, 0.0) for x in d]
    l = [max(-x, 0.0) for x in d]
    ag = sum(g[:p]) / p
    al = sum(l[:p]) / p

    def f(ag, al):
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[p] = f(ag, al)
    for i in range(p, len(d)):
        ag = (ag * (p - 1) + g[i]) / p
        al = (al * (p - 1) + l[i]) / p
        out[i + 1] = f(ag, al)
    return np.array(out)


def test_constant_series_gives_zero_stoch():
    r = S.stoch_rsi(np.full(80, 5.0))
    assert np.all(r["rsi"][14:] == 50.0)
    assert np.all(r["stoch"][27:] == 0.0)
    assert np.all(r["k"][29:] == 0.0) and np.all(r["d"][31:] == 0.0)
    assert np.isnan(r["rsi"][:14]).all() and np.isnan(r["stoch"][:27]).all()
    assert np.isnan(r["k"][:29]).all() and np.isnan(r["d"][:31]).all()
    assert not S.pre_signal(r["k"], r["d"], np.ones(80, bool), 20).any()


def test_hand_fixture_small_periods():
    # rsi_len=2: farklar +1,+1,-1,+1 → RSI[2]=100, RSI[3]=50, RSI[4]=75 (elle)
    c = np.array([10.0, 11.0, 12.0, 11.0, 12.0])
    r = S.stoch_rsi(c, rsi_len=2, stoch_len=2, k_len=1, d_len=1)
    assert r["rsi"][2] == pytest.approx(100.0)
    assert r["rsi"][3] == pytest.approx(50.0)
    assert r["rsi"][4] == pytest.approx(75.0)
    assert np.isnan(r["stoch"][2])
    assert r["stoch"][3] == pytest.approx(0.0)       # (50-50)/(100-50)
    assert r["stoch"][4] == pytest.approx(100.0)     # (75-50)/(75-50)
    r2 = S.stoch_rsi(c, rsi_len=2, stoch_len=2, k_len=2, d_len=1)
    assert r2["k"][4] == pytest.approx(50.0) and r2["d"][4] == pytest.approx(50.0)


def test_matches_python_reference_on_random_walk():
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600)))
    rsi = _ref_rsi(list(c), 14)
    assert np.allclose(S.rsi_wilder(c, 14), rsi, equal_nan=True, atol=1e-9)
    r = S.stoch_rsi(c)
    i = 400

    def stoch_at(j):
        w = rsi[j - 13:j + 1]
        return 100 * (rsi[j] - w.min()) / (w.max() - w.min())

    assert r["stoch"][i] == pytest.approx(stoch_at(i))
    assert r["k"][i] == pytest.approx(np.mean([stoch_at(j) for j in (i - 2, i - 1, i)]))
    ks = [np.mean([stoch_at(j) for j in (m - 2, m - 1, m)]) for m in (i - 2, i - 1, i)]
    assert r["d"][i] == pytest.approx(np.mean(ks))
    assert 0.0 <= np.nanmin(r["k"]) and np.nanmax(r["k"]) <= 100.0


def test_causal_prefix_invariance():
    rng = np.random.default_rng(5)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    a = S.stoch_rsi(c)
    b = S.stoch_rsi(c[:200])
    for key in ("rsi", "stoch", "k", "d"):
        assert np.allclose(a[key][:200], b[key], equal_nan=True, atol=1e-9)


def test_pre_signal_rules():
    k = np.array([np.nan, 10, 15, 25, 19, 18, 40, 41.0])
    d = np.array([np.nan, 12, 14, 24, 20, 20, 39, 41.5])
    # i=2: K[1]=10 <= D[1]=12 ve K[2]=15 > D[2]=14 → kesişim; K[1] < 20.
    # i=3: K[2]=15 > D[2]=14 → önceki barda zaten üstte, kesişim yok.
    # i=6: K[5]=18 <= D[5]=20 ve K[6]=40 > D[6]=39 → kesişim; K[5]=18 < 20.
    bear = np.ones(8, bool)
    assert list(np.flatnonzero(S.pre_signal(k, d, bear, 20))) == [2, 6]
    # seviye 10: K[1]=10 < 10 değil, K[5]=18 de değil
    assert not S.pre_signal(k, d, bear, 10).any()
    # çekirdek yeşilse ön sinyal yok
    bear2 = bear.copy()
    bear2[6] = False
    assert list(np.flatnonzero(S.pre_signal(k, d, bear2, 20))) == [2]
    # seviye 15: i=6 için K[5]=18 elenir; i=2 için K[1]=10 kalır
    assert list(np.flatnonzero(S.pre_signal(k, d, bear, 15))) == [2]
    # eşitlik: K[i-1] == D[i-1] sayılır (≤)
    k2 = np.array([np.nan, 10.0, 11.0])
    d2 = np.array([np.nan, 10.0, 10.5])
    assert list(np.flatnonzero(S.pre_signal(k2, d2, np.ones(3, bool), 20))) == [2]


def test_matches_frontend_chart_fixture():
    # 2026-10-17: grafikteki stochRsi (frontend/app/charts/signals.test.ts) ile birebir aynı değerler.
    import numpy as np
    from app.rescan.stochrsi import stoch_rsi
    r = stoch_rsi(np.array([10, 11, 10, 11, 12, 11], float), 2, 2, 2, 2)
    assert np.allclose(r["rsi"][2:], [50, 75, 87.5, 43.75])
    assert np.isnan(r["stoch"][:3]).all() and np.allclose(r["stoch"][3:], [100, 100, 0])
    assert np.isnan(r["k"][:4]).all() and np.allclose(r["k"][4:], [100, 50])
    assert np.isnan(r["d"][:5]).all() and np.isclose(r["d"][5], 75)
