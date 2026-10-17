"""scripts/indfilter_common.py saf yardımcılarının birim testleri (2026-10-17)."""
import sys
import pathlib
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import indfilter_common as K  # noqa: E402


class TestStats(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(3)

    def test_partial_spearman_removes_confounder(self):
        n = 4000
        atr = self.rng.lognormal(0, 0.5, n)
        f = atr * self.rng.lognormal(0, 0.3, n)          # özellik ATR'ye bağlı
        y = atr + self.rng.normal(0, 0.2, n)             # sonuç yalnız ATR'ye bağlı
        day = self.rng.integers(0, 90, n)
        raw = K.partial_spearman(f, y, None, day)
        par = K.partial_spearman(f, y, atr, day)
        self.assertGreater(raw["r"], 0.3)
        self.assertLess(abs(par["r"]), 0.08)
        self.assertLess(abs(par["t"]), 3.0)

    def test_partial_spearman_detects_real_effect(self):
        n = 4000
        atr = self.rng.lognormal(0, 0.5, n)
        f = self.rng.normal(size=n)
        y = 0.5 * f + atr * 0.1 + self.rng.normal(0, 1, n)
        day = self.rng.integers(0, 90, n)
        par = K.partial_spearman(f, y, atr, day)
        self.assertGreater(par["r"], 0.2)
        self.assertGreater(par["t"], 5)

    def test_partial_spearman_handles_nan_and_small(self):
        x = np.array([1.0, np.nan, 3.0])
        r = K.partial_spearman(x, x, None, np.array([0, 0, 1]))
        self.assertTrue(np.isnan(r["r"]))
        self.assertEqual(r["n"], 2)

    def test_auc(self):
        s = np.array([1, 2, 3, 4, 5.0])
        self.assertAlmostEqual(K.auc_score(s, np.array([0, 0, 0, 1, 1])), 1.0)
        self.assertAlmostEqual(K.auc_score(s, np.array([1, 1, 0, 0, 0])), 0.0)
        self.assertAlmostEqual(K.auc_score(np.zeros(6), np.array([1, 0, 1, 0, 1, 0])), 0.5)
        self.assertTrue(np.isnan(K.auc_score(s, np.zeros(5, dtype=bool))))

    def test_terciles_frozen_edges(self):
        x = np.arange(90.0)
        b, ed = K.terciles(x)
        self.assertEqual([int((b == k).sum()) for k in range(3)], [30, 30, 30])
        b2, _ = K.terciles(np.array([-5.0, 45.0, 200.0, np.nan]), ed)
        self.assertEqual(b2.tolist(), [0, 1, 2, -1])

    def test_strat_diff_zero_when_only_confounded(self):
        n = 6000
        atr = self.rng.lognormal(0, 0.6, n)
        strat, _ = K.terciles(atr)
        f = atr + self.rng.normal(0, 0.05, n)
        y = atr * 2
        d = K.strat_diff(f, y, strat, self.rng.integers(0, 60, n))
        # tabaka içinde y, atr ile artıyor ama tabaka daraldığı için fark küçük kalmalı
        full = y[f > np.median(f)].mean() - y[f <= np.median(f)].mean()
        self.assertLess(abs(d["diff"]), 0.5 * abs(full))

    def test_strat_diff_detects_effect(self):
        n = 6000
        atr = self.rng.lognormal(0, 0.6, n)
        strat, _ = K.terciles(atr)
        f = self.rng.normal(size=n)
        y = 0.8 * (f > 0) + self.rng.normal(0, 0.5, n)
        d = K.strat_diff(f, y, strat, self.rng.integers(0, 60, n))
        self.assertAlmostEqual(d["diff"], 0.8, delta=0.15)
        self.assertGreater(d["t"], 5)

    def test_pinball(self):
        self.assertAlmostEqual(K.pinball([1, 2, 3], [2, 2, 2], 0.5), (0.5 + 0 + 0.5) / 3)
        self.assertGreater(K.pinball([1, 1, 1], [3, 3, 3], 0.9), 0)
        # q=0.9: eksik tahmin (y>pred) pahalı
        self.assertGreater(K.pinball([5.0], [1.0], 0.9), K.pinball([5.0], [9.0], 0.9))


class TestRules(unittest.TestCase):
    def test_confirm_rule_mask(self):
        srcs = [("velocity", "jump"), ("jump", "early"), ("velocity",), ("velocity", "early", "rising"), ("velocity", "jump")]
        modes = ["trend_devam", "trend_devam", "notr", "unified", "notr"]
        self.assertEqual(K.confirm_rule_mask(srcs, modes).tolist(), [True, False, False, False, True])

    def test_confirm_rule_duplicate_sources_not_distinct(self):
        self.assertEqual(K.confirm_rule_mask([("velocity", "velocity")], ["notr"]).tolist(), [False])

    def test_match_pool_tolerance_and_fallback(self):
        atr = np.array([1.0, 1.1, 0.9, 1.2, 0.8, 1.05, 0.95, 1.02, 1.5, 3.0, np.nan])
        pool = K.match_pool(atr, 1.0, tol=0.25, min_pool=8)
        self.assertTrue(set(pool.tolist()) == {0, 1, 2, 3, 4, 5, 6, 7})
        # yetersiz havuz → en yakın 8
        pool2 = K.match_pool(atr, 2.0, tol=0.25, min_pool=3)
        self.assertEqual(len(pool2), 3)
        self.assertTrue(np.isnan(atr[pool2]).sum() == 0)
        self.assertEqual(len(K.match_pool(atr, np.nan)), 0)

    def test_block_of(self):
        blocks = [(0, 99), (100, 199)]
        self.assertEqual(K.block_of(np.array([-1, 0, 99, 100, 199, 200]), blocks).tolist(), [-1, 0, 0, 1, 1, -1])

    def test_blocks_cover_expected_range(self):
        b = K.ha_blocks()
        self.assertEqual(len(b), 3)
        self.assertTrue(b[0][1] < b[1][0] < b[1][1] < b[2][0])
        nb = K.notif_blocks()
        self.assertLess(nb[0][1], nb[1][0])

    def test_candidate_grid_excludes_near_ticks(self):
        ot = np.arange(0, 20 * 3_600_000, 60_000, dtype=np.int64)
        tick = np.array([5 * 3_600_000], dtype=np.int64)
        g = K.candidate_grid(ot, 0, 20 * 3_600_000, tick)
        self.assertTrue((np.abs(g - tick[0]) >= K.MIN_GAP_MS).all())
        self.assertTrue((g % 300_000 == 0).all())
        self.assertTrue(g.max() + (K.W + 5) * 60_000 <= ot[-1])


class TestNet(unittest.TestCase):
    def test_net_for_tp_hit_and_flat(self):
        n, w = 3, K.W
        O = np.ones((n, w), dtype=np.float32); H = O.copy(); L = O.copy(); C = O.copy()
        H[0, 5] = 1.03                      # satır 0: +%3 → TP %2 görülür
        L[1, 3] = 0.95                      # satır 1: SL %3 görülür
        win = {"O": O, "H": H, "L": L, "C": C}
        r = K.net_for(win, np.array([2.0, 2.0, 2.0]))
        self.assertGreater(r["net"][0], 1.0)
        self.assertLess(r["net"][1], -3.0)
        self.assertAlmostEqual(r["net"][2], -(0.15 + 0.15 + 0.225), delta=0.05)
        mfe, mae = K.mfe_mae(win)
        self.assertAlmostEqual(mfe[0], 3.0, places=4)
        self.assertAlmostEqual(mae[1], -5.0, places=4)

    def test_paired_baseline(self):
        net = np.array([1.0, 2.0, 4.0, np.nan, 7.0])
        kind = np.array([0, 1, 1, 1, 0])
        ev = np.array([0, 0, 0, 0, 1])
        b, c = K.paired_baseline(net, kind, ev, 3)
        self.assertAlmostEqual(b[0], 3.0)
        self.assertEqual(c.tolist(), [2, 0, 0])
        self.assertTrue(np.isnan(b[1]))


class TestFeats(unittest.TestCase):
    def _series(self, n, bar, seed=1):
        rng = np.random.default_rng(seed)
        c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + rng.random(n) * 0.002)
        l = np.minimum(o, c) * (1 - rng.random(n) * 0.002)
        v = 100 + rng.random(n) * 50
        return {"ot": (np.arange(n) * bar + 1_700_000_000_000).astype(np.int64), "o": o, "h": h, "l": l, "c": c, "v": v,
                "qv": v * c, "tbv": v * 0.5, "tqv": v * c * (0.4 + 0.2 * rng.random(n))}

    def test_derive_ideas_logic(self):
        from scripts import indfilter_feats as F
        n = 4
        cols = {"5m.adx14": np.array([30, 20, 30, np.nan]), "5m.plus_di14": np.array([25, 25, 10, 25]), "5m.minus_di14": np.array([10, 10, 25, 10]),
                "5m.st_cluster_sum": np.array([3, 3, 1, 3]), "res:eqh_5m": np.array([99, 1.0, 5.0, 99]),
                "res:swing_5m": np.array([99, 99, 99, 99]), "5m.chop14": np.array([30, 50, 30, 30])}
        cols = {k: np.asarray(v, dtype=np.float32) for k, v in cols.items()}
        out = F.derive_ideas(cols, np.array([2.0, 2.0, 2.0, 2.0]))
        self.assertEqual(out["idea:adx25_di_up"][:3].tolist(), [1.0, 0.0, 0.0])
        self.assertTrue(np.isnan(out["idea:adx25_di_up"][3]))
        self.assertEqual(out["idea:supertrend_all_green"].tolist(), [1.0, 1.0, 0.0, 1.0])
        # eşit tepe hedefin (2,0) içinde mi: [yok, 1,0 ≤ 2 → var, 5,0 > 2 → yok, yok]
        self.assertEqual(out["idea:no_equal_highs_in_target"].tolist(), [1.0, 0.0, 1.0, 1.0])
        self.assertEqual(out["idea:chop_trending"].tolist(), [1.0, 0.0, 1.0, 1.0])

    def test_truncate_series_keeps_only_closed(self):
        from scripts import indfilter_feats as F
        s5 = self._series(50, 300_000)
        series = {"1m": self._series(250, 60_000), "5m": s5, "15m": self._series(20, 900_000)}
        t = int(s5["ot"][30] + 300_000)             # 30. bar tam bu anda kapanır
        tr = F.truncate_series(series, t)
        self.assertEqual(len(tr["5m"]["ot"]), 31)
        self.assertTrue((tr["5m"]["ot"] + 300_000 <= t).all())
        self.assertTrue((tr["1m"]["ot"] + 60_000 <= t).all())

    def test_tf_block_causal_on_synthetic(self):
        """Gelecek barları değiştirmek sinyal anındaki özellikleri DEĞİŞTİRMEZ (kütüphane + pattern_study özellikleri)."""
        from app.rescan import pattern_study as PS
        from scripts import indfilter_feats as F
        lib = F.lib_module()
        self.assertIsNotNone(lib)
        PS.TF_BARS_PER_DAY.setdefault("15m", 96)
        n = 900
        a = self._series(n, 300_000)
        t = int(a["ot"][700] + 300_000 + 10_000)    # 700. bar kapandıktan 10 sn sonra
        out1 = F.tf_block(lib, PS, a, "5m", F.BAR5, np.array([t], dtype=np.int64), 3)
        b = {k: v.copy() for k, v in a.items()}
        rng = np.random.default_rng(9)
        for k in ("o", "h", "l", "c", "v", "qv", "tbv", "tqv"):
            b[k][701:] = b[k][701:] * (1 + rng.random(n - 701))        # gelecek bozulur
        out2 = F.tf_block(lib, PS, b, "5m", F.BAR5, np.array([t], dtype=np.int64), 3)
        self.assertEqual(set(out1), set(out2))
        diff = [k for k in out1 if not ((np.isnan(out1[k][0]) and np.isnan(out2[k][0])) or abs(float(out1[k][0]) - float(out2[k][0])) <= 1e-5 * max(1.0, abs(float(out1[k][0]))))]
        self.assertEqual(diff, [])
        self.assertGreater(len(out1), 150)


class TestReportLogic(unittest.TestCase):
    def test_rule_passes(self):
        from scripts import indfilter_report as R
        def row(b, delta, net, net_all, lo=0.1, n=200):
            return {"name": "r", "block": b, "n": n, "delta": delta, "net": net, "net_all": net_all, "lo": lo}
        good = [row(1, 0.2, -0.1, -0.3), row(2, 0.1, -0.2, -0.3), row(-1, 0.15, -0.15, -0.3, lo=0.05)]
        self.assertTrue(R.rule_passes(good, "r", 3)["ok"])
        bad_block = [row(1, 0.2, -0.1, -0.3), row(2, -0.1, -0.4, -0.3), row(-1, 0.05, -0.2, -0.3, lo=0.05)]
        self.assertFalse(R.rule_passes(bad_block, "r", 3)["ok"])
        bad_lcb = [row(1, 0.2, -0.1, -0.3), row(2, 0.1, -0.2, -0.3), row(-1, 0.15, -0.15, -0.3, lo=-0.05)]
        self.assertFalse(R.rule_passes(bad_lcb, "r", 3)["ok"])
        self.assertFalse(R.rule_passes(good[:1], "r", 3)["ok"])

    def test_model_vs_fixed(self):
        from scripts import indfilter_report as R
        def r(name, b, d, lo):
            return {"name": name, "block": b, "dnet": d, "dnet_lo": lo, "dex": d, "dex_lo": lo, "net": d}
        res = [r("M", 1, 0.3, 0.1), r("M", 2, 0.4, 0.2), r("M", -1, 0.35, 0.2)]
        self.assertTrue(R.model_vs_fixed(res, "M", "F", 3)["ok"])
        res2 = [r("M", 1, 0.3, 0.1), r("M", 2, -0.1, -0.3), r("M", -1, 0.1, 0.02)]
        self.assertFalse(R.model_vs_fixed(res2, "M", "F", 3)["ok"])
        res3 = [r("M", 1, 0.3, 0.1), r("M", 2, 0.1, -0.05), r("M", -1, 0.2, -0.01)]
        self.assertFalse(R.model_vs_fixed(res3, "M", "F", 3)["ok"])
        # 2 dilimli nüfus: tek seçim-dışı dilim hem blok hem birleşik
        self.assertTrue(R.model_vs_fixed([r("M", 1, 0.3, 0.1)], "M", "F", 2)["ok"])
        self.assertFalse(R.model_vs_fixed([], "M", "F", 2)["ok"])


class TestSupport(unittest.TestCase):
    def test_support_ok(self):
        n = 400
        day = np.arange(n) % 40
        dense = np.random.default_rng(1).normal(size=n)
        self.assertTrue(K.support_ok(dense, day))
        sparse = np.zeros(n); sparse[:5] = 1.0                    # 5 gözlem → yetersiz
        self.assertFalse(K.support_ok(sparse, day))
        one_day = np.zeros(n); one_day[day == 3] = 1.0           # 10 gözlem, 1 gün
        self.assertFalse(K.support_ok(one_day, day))
        self.assertFalse(K.support_ok(np.ones(n), day))
        ok_bin = np.zeros(n); ok_bin[::5] = 1.0                  # 80 gözlem, 40 gün
        self.assertTrue(K.support_ok(ok_bin, day))

    def test_t_pvalue_conservative(self):
        from scipy.stats import norm
        self.assertGreater(K.t_pvalue(2.0, 5), 2 * norm.sf(2.0))
        self.assertAlmostEqual(K.t_pvalue(2.0, 10000), 2 * norm.sf(2.0), places=3)
        self.assertTrue(np.isnan(K.t_pvalue(float("nan"), 30)))


class TestProse(unittest.TestCase):
    def _rows(self, deltas, nets, nets_all, comb_lo, n=200):
        rows = [{"name": "r", "block": b + 1, "n": n, "delta": d, "net": nt, "net_all": na, "lo": 0.0, "per_day": 10.0, "ex": 0.1}
                for b, (d, nt, na) in enumerate(zip(deltas, nets, nets_all))]
        rows.append({"name": "r", "block": -1, "n": n * 2, "delta": 0.1, "net": nets[0], "net_all": nets_all[0], "lo": comb_lo, "per_day": 10.0, "ex": 0.1})
        return rows

    def test_passes(self):
        from scripts import indfilter_prose as PR
        good = self._rows([0.1, 0.1], [-0.3, -0.4], [-0.5, -0.5], 0.02)
        self.assertTrue(PR.passes(good, "r", 3))
        self.assertFalse(PR.passes(self._rows([0.1, -0.1], [-0.3, -0.4], [-0.5, -0.5], 0.02), "r", 3))
        self.assertFalse(PR.passes(self._rows([0.1, 0.1], [-0.3, -0.6], [-0.5, -0.5], 0.02), "r", 3))
        self.assertFalse(PR.passes(self._rows([0.1, 0.1], [-0.3, -0.4], [-0.5, -0.5], -0.01), "r", 3))
        self.assertFalse(PR.passes(self._rows([0.1, 0.1], [-0.3, -0.4], [-0.5, -0.5], 0.02, n=10), "r", 3))

    def test_verdict_line_cases(self):
        from scripts import indfilter_prose as PR
        none = {"ha": {"rules_tümü": self._rows([-0.1, -0.1], [-0.6, -0.6], [-0.5, -0.5], -0.1)}}
        self.assertTrue(PR.verdict_line(none, {}, {"ha": 3, "notif": 2}).startswith("HAYIR"))
        part = {"ha": {"rules_tümü": self._rows([0.1, 0.1], [-0.3, -0.4], [-0.5, -0.5], 0.02)}}
        self.assertTrue(PR.verdict_line(part, {}, {"ha": 3, "notif": 2}).startswith("KISMEN"))
        yes = {"ha": {"rules_tümü": self._rows([0.1, 0.1], [0.3, 0.4], [-0.5, -0.5], 0.02)}}
        self.assertTrue(PR.verdict_line(yes, {}, {"ha": 3, "notif": 2}).startswith("EVET"))


if __name__ == "__main__":
    unittest.main()
