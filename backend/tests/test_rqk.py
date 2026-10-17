"""RQK (Rational Quadratic Kernel) portu — grafik hesabı (IndicatorPicker.tsx SLING_SHOT_ENTRY) ile parite testleri.

Parite fixture'ı: `work/rqk/rqk_calc.js` (TS mantığının birebir JS kopyası) Node ile çalıştırılıp
`tests/fixtures/rqk_parity.json` olarak kaydedildi. Node varsa test ayrıca fixture'ı yeniden üretip karşılaştırır.
"""
import json
import math
import pathlib
import shutil
import subprocess
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import rqk  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "rqk_parity.json"
JS = ROOT / "work" / "rqk" / "rqk_calc.js"


def js_port_reference(closes, h=8, r=2, smooth=False):
    """TS `calculate` mantığının düz Python döngüsü (karşılaştırma referansı; NaN kapanış atlama dâhil)."""
    h = max(3.0, float(h))
    r = max(0.25, float(r))
    n = len(closes)

    def yh(end):
        if end < 1:
            return None
        cw = 0.0
        cum = 0.0
        look = min(h, end + 1)
        i = 0
        while i < look:
            p = closes[end - i]
            if p is not None and math.isfinite(p):
                w = (1 + (i ** 2 / (h ** 2 * 2 * r))) ** (-r)
                cw += p * w
                cum += w
            i += 1
        return None if cum == 0 else cw / cum

    y1 = [yh(i) for i in range(n)]
    y2 = [yh(max(0, i - 2)) for i in range(n)]
    out_y = []
    out_b = []
    for i in range(n):
        v = y1[i]
        if v is None or not math.isfinite(v):
            out_y.append(None)
            out_b.append(None)
            continue
        p1 = y1[i - 1] if i >= 1 else None
        p2 = y1[i - 2] if i >= 2 else None
        if smooth:
            b = y2[i] is not None and y2[i] > v
        elif p1 is not None and p2 is not None:
            b = (p1 < v) or ((p2 > p1) and not (p1 > v))
        elif p1 is not None:
            b = p1 < v
        else:
            b = True
        out_y.append(v)
        out_b.append(bool(b))
    return out_y, out_b


def _compare(tc, closes, h, r, smooth, label):
    y = rqk.yhat_app(np.array(closes, dtype=float), h, r)
    bull, valid = rqk.colors_app(y, smooth)
    ref_y, ref_b = js_port_reference(closes, h, r, smooth)
    for i, (ry, rb) in enumerate(zip(ref_y, ref_b)):
        if ry is None:
            tc.assertFalse(valid[i], f"{label} i={i}: null beklenirdi")
            continue
        tc.assertTrue(valid[i], f"{label} i={i}: dolu beklenirdi")
        tc.assertAlmostEqual(y[i], ry, delta=1e-9 * max(1.0, abs(ry)), msg=f"{label} yhat i={i}")
        tc.assertEqual(bool(bull[i]), rb, f"{label} renk i={i}")


class NodeParityTest(unittest.TestCase):
    def _check_payload(self, payload):
        n_cmp = 0
        for case in payload["cases"]:
            closes = np.array(case["closes"], dtype=float)
            for run in case["runs"]:
                p = run["params"]
                y = rqk.yhat_app(closes, p["h"], p["r"])
                bull, valid = rqk.colors_app(y, p["smoothColors"])
                for i, (jy, jb) in enumerate(zip(run["yhat"], run["bull"])):
                    tag = f"{case['name']} h={p['h']} r={p['r']} smooth={p['smoothColors']} i={i}"
                    if jy is None:
                        self.assertFalse(valid[i], tag)
                        self.assertIsNone(jb, tag)
                        continue
                    self.assertTrue(valid[i], tag)
                    self.assertAlmostEqual(y[i], jy, delta=1e-9 * max(1.0, abs(jy)), msg=tag)
                    self.assertEqual(bool(bull[i]), jb, tag)
                    n_cmp += 1
        self.assertGreater(n_cmp, 500)

    def test_fixture_from_node(self):
        self._check_payload(json.loads(FIXTURE.read_text(encoding="utf-8")))

    @unittest.skipUnless(shutil.which("node") and JS.exists(), "node yok")
    def test_live_node_run_matches_fixture_and_port(self):
        out = subprocess.run(["node", str(JS)], capture_output=True, text=True, check=True, timeout=60).stdout
        self._check_payload(json.loads(out))


class ReferenceLoopTest(unittest.TestCase):
    def test_random_walks_all_params(self):
        rng = np.random.default_rng(3)
        for n in (2, 3, 7, 40, 200):
            c = 100 + np.cumsum(rng.normal(size=n))
            c = np.round(c, 1)                       # eşitlik dallarını tetikler
            for h, r in ((8, 2), (3, 0.25), (16, 1), (25, 8), (5.5, 2)):
                for smooth in (False, True):
                    _compare(self, [float(x) for x in c], h, r, smooth, f"n={n} h={h} r={r} s={smooth}")

    def test_nonfinite_closes_skipped_like_app(self):
        rng = np.random.default_rng(5)
        c = 50 + np.cumsum(rng.normal(size=60))
        c[[4, 5, 30]] = np.nan
        _compare(self, [float(x) for x in c], 8, 2, False, "nan")

    def test_first_bars(self):
        y = rqk.yhat_app(np.array([10.0, 11.0, 12.0, 13.0]), 8, 2)
        self.assertTrue(np.isnan(y[0]))
        w1 = (1 + 1 / (64 * 4)) ** -2
        self.assertAlmostEqual(y[1], (11.0 + 10.0 * w1) / (1 + w1), places=12)
        bull, valid = rqk.colors_app(y)
        self.assertFalse(valid[0])
        self.assertTrue(bull[1])                      # prev1 yok → True

    def test_hand_fixture_colors(self):
        # yhat dizisi elle: nan 2 3 3 2 1 1 2 → renk (p1/p2 kuralı)
        y = np.array([np.nan, 2.0, 3.0, 3.0, 2.0, 1.0, 1.0, 2.0])
        bull, valid = rqk.colors_app(y)
        # i=1: True (prev1 yok); i=2: p1=2<3 True; i=3: p1=3=v, p2=2>p1 değil → False; i=4: p1=3>2 → False;
        # i=5: False; i=6: p1=1=v, p2=2>1 (wasBearish) ve p1>v değil → True; i=7: p1=1<2 True
        self.assertEqual(bull.tolist(), [False, True, True, False, False, False, True, True])


class CausalityAndVariantsTest(unittest.TestCase):
    def test_causal(self):
        rng = np.random.default_rng(9)
        c = 100 + np.cumsum(rng.normal(size=120))
        full = rqk.rqk(c, 8, 2)
        cut = rqk.rqk(c[:70], 8, 2)
        np.testing.assert_allclose(full["yhat"][:70], cut["yhat"], equal_nan=True)
        np.testing.assert_array_equal(full["bull"][:70], cut["bull"])
        full = rqk.rqk(c, 16, 2, variant="B")
        cut = rqk.rqk(c[:70], 16, 2, variant="B")
        np.testing.assert_allclose(full["yhat"][:70], cut["yhat"], equal_nan=True)

    def test_variant_b_window_and_bandwidth(self):
        rng = np.random.default_rng(11)
        c = 100 + np.cumsum(rng.normal(size=80))
        y = rqk.yhat_canon(c, 8, 2, window=25)
        i = 60
        k = np.arange(25)
        w = (1 + k ** 2 / (8 ** 2 * 2 * 2)) ** -2.0
        ref = float(np.sum(c[i - k] * w) / np.sum(w))
        self.assertAlmostEqual(y[i], ref, places=10)
        self.assertNotAlmostEqual(rqk.yhat_app(c, 8, 2)[i], ref, places=6)   # varyant A pencere 8 bar → farklı
        bull, valid = rqk.colors_canon(y)
        j = 40
        self.assertEqual(bool(bull[j]), bool(y[j - 1] < y[j]))

    def test_flips_and_age(self):
        c = np.array([10, 9, 8, 7, 7.5, 8.5, 9.5, 10.5, 10, 9, 8], dtype=float)
        res = rqk.rqk(c, 3, 2)
        up = np.flatnonzero(res["flip_up"])
        dn = np.flatnonzero(res["flip_dn"])
        self.assertTrue(len(up) >= 1 and len(dn) >= 1)
        for i in up:
            self.assertTrue(res["bull"][i] and not res["bull"][i - 1])
        for i in dn:
            self.assertTrue((not res["bull"][i]) and res["bull"][i - 1])
        age = rqk.bars_since_flip(res["flip_up"], res["flip_dn"])
        self.assertEqual(int(age[up[0]]), 0)


if __name__ == "__main__":
    unittest.main()
