"""scripts/scalpernew_ribbon_study.detect_ribbon, scalpernew'in select_recent_cross elemesiyle aynı mumları seçmeli.
scalpernew deposu bu makinede yoksa test atlanır (dosya yolu SCALPERNEW_RIBBON ile değiştirilebilir)."""
import importlib.util
import os
import random
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
study = pytest.importorskip("scalpernew_ribbon_study")
pytestmark = pytest.mark.skipif(not os.path.exists(study.SCALPERNEW_RIBBON), reason="scalpernew deposu yok")


def _bars(n=400, seed=23):
    rnd = random.Random(seed)
    price, out = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + rnd.gauss(0.0005, 0.012))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.004)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.004)))
        out.append({"open_ms": i * 300_000, "open": o, "high": h, "low": l, "close": c})
        price = c
    return out


@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h"])
def test_detect_ribbon_matches_select_recent_cross(tf):
    rb = study.load_ribbon()
    total = 0
    for seed in (23, 7, 11, 31, 42):          # dilime gore sinyal ureten tohum degisir; birkac tohumda paritesi + en az bir sinyal
        bars = _bars(seed=seed)
        closes = [b["close"] for b in bars]
        stamps = [b["open_ms"] for b in bars]
        expected = set()
        for i in range(1, len(bars)):         # her mumu "simdi" sayip pencereyi tek muma daraltarak canli secimi taklit et
            idx = rb.select_recent_cross(closes[: i + 1], stamps[: i + 1], stamps[i], window_ms=1,
                                         highs=[b["high"] for b in bars[: i + 1]], lows=[b["low"] for b in bars[: i + 1]],
                                         opens=[b["open"] for b in bars[: i + 1]], apply_stoch=tf not in {"1m", "15m"}, timeframe=tf)
            if idx is not None:
                expected.add(idx)
        got = {s["index"] for s in study.detect_ribbon(rb, bars, tf)}
        assert got == expected, f"seed {seed}"
        total += len(got)
    if tf != "15m":   # scalpernew 2026-10-21 04:30: M15 kurali hacim ve saatlik dizilim girdisi ister; girdisiz hic gecmez (parite yine de gecerli)
        assert total, "hicbir tohumda kurdele sinyali yok; test bos kumeleri karsilastiriyor olurdu"
