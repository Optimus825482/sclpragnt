"""validation90_report saf yardımcıları + radar_shield_rescan_analysis.merge_klines testleri."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validation90_report as V  # noqa: E402
from scripts.radar_shield_rescan_analysis import merge_klines  # noqa: E402


def _row(sym, tick, score, ratio=None, confirm=None, h=15, rank=None):
    rad = {}
    if ratio is not None:
        rad["taker_buy_ratio"] = ratio
    if confirm:
        rad["taker_confirm"] = confirm
    return {"symbol": sym, "tick_ms": tick, "velocity_score": score, "horizon_minutes": h, "radar": rad, "rank": rank}


class TestPureHelpers(unittest.TestCase):
    def test_parse_blocks(self):
        self.assertEqual(V.parse_blocks("2026-07-20:2026-08-18, 2026-08-19:2026-09-17"),
                         [("2026-07-20", "2026-08-18"), ("2026-08-19", "2026-09-17")])

    def test_taker_bucket(self):
        self.assertEqual(V.taker_bucket(_row("A", 1, 1, 0.7, "strong")), "strong")
        self.assertEqual(V.taker_bucket(_row("A", 1, 1, 0.3, "weak")), "weak")
        self.assertEqual(V.taker_bucket(_row("A", 1, 1, 0.5)), "neutral")
        self.assertEqual(V.taker_bucket({"radar": {"taker_unavailable": True}}), "unavailable")
        self.assertEqual(V.taker_bucket({}), "unavailable")

    def test_two_prop_z(self):
        self.assertAlmostEqual(V.two_prop_z(50, 100, 50, 100), 0.0)
        self.assertGreater(V.two_prop_z(60, 100, 40, 100), 2.0)
        self.assertIsNone(V.two_prop_z(0, 0, 1, 2))

    def test_taker_rule(self):
        self.assertEqual(V.taker_rule([4.0, 5.0, 1.0], 3.5, 2.5), "TAKER_DOGRULANDI")
        self.assertEqual(V.taker_rule([4.0, 1.0, 1.0], 2.0, 1.0), "TAKER_BELIRSIZ")
        self.assertEqual(V.taker_rule([-1.0, 0.5, 4.0], -0.5, -0.4), "TAKER_ANLAMSIZ_YA_DA_TERS")
        self.assertEqual(V.taker_rule([None, None], None, None), "YETERSIZ_VERI")

    def test_ob_verdict(self):
        p = {"n": 100, "hit60": 0.20}
        self.assertEqual(V.ob_verdict(p, {"n": 100, "hit60": 0.19}, 30), "KAPI_DEGER_KATMIYOR")
        self.assertEqual(V.ob_verdict(p, {"n": 100, "hit60": 0.05}, 30), "KAPI_ISE_YARIYOR")
        self.assertEqual(V.ob_verdict(p, {"n": 100, "hit60": 0.12}, 30), "BELIRSIZ")
        self.assertEqual(V.ob_verdict(p, {"n": 5, "hit60": 0.12}, 30), "YETERSIZ_VERI")

    def test_quantile_edges_and_bucket(self):
        edges = V.quantile_edges(list(range(100)), 10)
        self.assertEqual(len(edges), 9)
        self.assertEqual(V.bucket_index(-5, edges), 0)
        self.assertEqual(V.bucket_index(1000, edges), 9)
        idx = [V.bucket_index(v, edges) for v in range(100)]
        self.assertEqual(sorted(set(idx)), list(range(10)))

    def test_cluster_bootstrap(self):
        day = 86_400_000
        a = [{"tick_ms": i * day, "v": 1.0} for i in range(10)]
        b = [{"tick_ms": i * day, "v": 0.0} for i in range(10)]
        pt, lo, hi = V.cluster_bootstrap_diff(a, b, lambda r: r["v"], n_boot=200)
        self.assertAlmostEqual(pt, 1.0)
        self.assertAlmostEqual(lo, 1.0)
        self.assertAlmostEqual(hi, 1.0)
        self.assertIsNone(V.cluster_bootstrap_diff([], b, lambda r: r["v"]))

    def test_counterfactual_ranks_undo_multiplier(self):
        # strong x1.05 ile 10.5 -> ham 10.0; weak x0.95 ile 9.6 -> ham ~10.1; nötr 10.2
        rows = [_row("S", 1, 10.5, 0.7, "strong"), _row("W", 1, 9.6, 0.3, "weak"), _row("N", 1, 10.2, 0.5)]
        cf = V.counterfactual_ranks(rows)
        # çarpanlı sıra: S(10.5) > N(10.2) > W(9.6); ham: W(10.105) < N? ham N=10.2 > W=10.105 > S=10.0
        self.assertEqual(cf[(1, "N", 15)], 1)
        self.assertEqual(cf[(1, "W", 15)], 2)
        self.assertEqual(cf[(1, "S", 15)], 3)

    def test_counterfactual_ranks_separate_ticks_and_horizons(self):
        rows = [_row("A", 1, 5.0, h=5), _row("B", 1, 7.0, h=15), _row("A", 2, 1.0, h=5)]
        cf = V.counterfactual_ranks(rows)
        self.assertEqual(cf[(1, "A", 5)], 1)
        self.assertEqual(cf[(1, "B", 15)], 1)
        self.assertEqual(cf[(2, "A", 5)], 1)


class TestMergeKlines(unittest.TestCase):
    def test_merge_dedupes_and_sorts(self):
        a = [[3000, "c"], [1000, "a"]]
        b = [[2000, "b"], [3000, "C"]]
        out = merge_klines(a, b)
        self.assertEqual([k[0] for k in out], [1000, 2000, 3000])
        self.assertEqual(out[2][1], "C")  # sonraki liste kazanır
        self.assertEqual(merge_klines([], None), [])


if __name__ == "__main__":
    unittest.main()


class TestPenalizedTopShare(unittest.TestCase):
    def test_penalty_pushes_overbought_out_of_top(self):
        regime = {1: {"shield": False}}
        rows = []
        for i in range(3):
            rows.append({"symbol": "S" + str(i), "tick_ms": 1, "velocity_score": 100.0 - i, "mode": "trend_devam",
                         "rank": i + 1, "mfi": 50.0, "rsi": 50.0})
        # aşırı alım, ham skor 101 (rank 1) -> x0.85 = 85.85 (sıra 4); top=3
        rows.append({"symbol": "OB", "tick_ms": 1, "velocity_score": 101.0, "mode": "trend_devam", "rank": 1, "mfi": 95.0, "rsi": 60.0})
        out = V.penalized_top_share(rows, regime, mult=0.85, top=3)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["still_top"], 0)
        out2 = V.penalized_top_share(rows, {1: {"shield": True}}, mult=0.85, top=3)
        self.assertEqual(out2["n"], 0)
