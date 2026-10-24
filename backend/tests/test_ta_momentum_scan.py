"""`scripts/ta_momentum_scan.py` — M1H (1 saatlik potansiyel) taraması: ileriye bakma kilidi, puanlama, sıralama."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

M15 = 900_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % M15)


def _mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ta_momentum_scan.py"
    spec = importlib.util.spec_from_file_location("ta_momentum_scan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bars(closes, q=1_000_000.0, t0=T0, spread=0.002):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        qi = q[i] if isinstance(q, (list, tuple)) else q
        out.append({"t": t0 + i * M15, "o": o, "h": max(o, c) * (1 + spread), "l": min(o, c) * (1 - spread), "c": c, "q": qi})
    return out


def _flat(n=300, base=10.0):
    return [base] * n


def test_unclosed_bar_is_ignored():
    M = _mod()
    closes = _flat(299) + [20.0]            # son mum ikiye katlıyor
    bars = _bars(closes)
    cutoff_open = bars[-1]["t"]            # son mum tam açılırken kesit → o mum kapanmamış
    f_open = M.momentum_features(bars, cutoff_open)
    f_closed = M.momentum_features(bars, bars[-1]["t"] + M15)
    assert f_open["px"] == 10.0 and f_open["r1"] == 0.0
    assert f_closed["px"] == 20.0 and f_closed["r1"] > 0


def test_too_short_history_returns_none():
    M = _mod()
    assert M.momentum_features(_bars(_flat(M.MIN_BARS - 1))) is None


def test_base_rate_counts_two_percent_within_four_bars():
    M = _mod()
    # 10 → 10,3 sıçraması tek yerde: ondan önceki 4 mumun her biri 1 sa içinde +%2 görür, diğerleri görmez.
    closes = _flat(250) + [10.3] + _flat(50)
    f = M.momentum_features(_bars(closes, spread=0.0))
    assert f is not None
    expected = 4 / (len(closes) - 5) * 100
    assert abs(f["base"] - expected) < 1e-6


def test_rising_with_volume_outscores_flat_and_spike_is_penalised():
    M = _mod()
    flat = M.momentum_features(_bars(_flat(300)))
    rise = _flat(290) + [10.0 + 0.03 * i for i in range(1, 11)]          # 2,5 saatte +%3, hacim 3×
    rising = M.momentum_features(_bars(rise, q=[1e6] * 290 + [3e6] * 10))
    spike = _flat(296) + [10.0, 10.5, 11.0, 11.5]                        # son 1 saatte +%15
    spiky = M.momentum_features(_bars(spike, q=[1e6] * 296 + [3e6] * 4))
    assert M.momentum_score(rising) > M.momentum_score(flat)
    assert spiky["r1"] > M.WEIGHTS["spike_pct"]
    no_pen = dict(M.WEIGHTS, spike_pen=0.0)
    assert abs(M.momentum_score(spiky) - (M.momentum_score(spiky, no_pen) - M.WEIGHTS["spike_pen"])) < 1e-9
    assert M.momentum_score(rising) == M.momentum_score(rising, no_pen)     # ceza yalnız sıçrayana


def test_rank_filters_stables_and_thin_volume():
    M = _mod()
    good = M.momentum_features(_bars(_flat(290) + [10.0 + 0.02 * i for i in range(1, 11)]))
    thin = dict(good, qv24=1e6)
    picked, n = M.rank({"AAATRY": good, "USDTTRY": good, "BBBTRY": thin, "CCCTRY": None}, top=5)
    assert [r["sym"] for r in picked] == ["AAATRY"] and n == 1
    assert "score" in picked[0] and picked[0]["px"] == good["px"]


def test_rows_to_bars_uses_quote_volume_column():
    M = _mod()
    bars = M.rows_to_bars([[T0, "1", "2", "0.5", "1.5", "100", T0 + M15 - 1, "150", 5, "0", "0", "0"], ["bozuk"]])
    assert bars == [{"t": T0, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "q": 150.0}]
