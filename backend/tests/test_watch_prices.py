import unittest

from app.watch_prices import collect_watch_symbols


class CollectTests(unittest.TestCase):
    def test_union_dedup_upper(self):
        out = collect_watch_symbols([{"symbol": "btctry"}, {"symbol": "ETHTRY"}],
                                    [{"symbol": "BTCTRY"}, {"symbol": "XRPTRY"}])
        self.assertEqual(["BTCTRY", "ETHTRY", "XRPTRY"], out)

    def test_cap_50(self):
        rows = [{"symbol": f"S{i:03d}TRY"} for i in range(80)]
        self.assertEqual(50, len(collect_watch_symbols(rows, [])))

    def test_skips_blank_and_bad(self):
        self.assertEqual(["AAATRY"], collect_watch_symbols(
            [{"symbol": ""}, {}, {"symbol": "x y"}, {"symbol": "AAATRY"}], []))
