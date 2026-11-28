"""CVD onay katmanı (`app/confirmed_flow`) birim testleri.

Ağ yok: canlı kline yerine enjekte edilen `store` ve saf fonksiyonlar test edilir.
Kapsam:
  - JSONL yükleme: aynı saat için son kayıt geçerli, bozuk satır atlanır
  - akış puanı: güçlü alım/satım, akışın saatler arası dönüşü
  - hüküm: fiyat yükselirken CVD negatif -> BOGA_TUZAGI; düşerken CVD pozitif
    -> AYI_TUZAGI; aksi halde puan eşikleri
"""

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import confirmed_flow as cf


def _hour(hour, cvd_pct, open_=1.00, close=1.00, vwap=1.00, volume=10_000_000):
    return {
        "symbol": "TLMTRY",
        "hour": hour,
        "symbol_volume": volume,
        "quote_volume": volume,
        "cvd_pct_of_volume": cvd_pct,
        "open": open_,
        "close": close,
        "vwap": vwap,
        "fetched_at_epoch": 1_000_000.0,
    }


class LoadConfirmedTest(unittest.TestCase):
    def test_last_record_per_hour_wins_and_bad_lines_skipped(self):
        tmp = pathlib.Path(self._tmpfile())
        try:
            tmp.write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "TLMTRY", "hour": "2026-11-28T06:00:00", "cvd_pct_of_volume": 1.0}),
                        "{bozuk json",
                        json.dumps({"symbol": "TLMTRY", "hour": "2026-11-28T06:00:00", "cvd_pct_of_volume": 5.0}),
                        json.dumps({"symbol": "TLMTRY", "hour": "2026-11-28T07:00:00", "cvd_pct_of_volume": -11.9}),
                        json.dumps({"hour": "2026-11-28T07:00:00"}),  # sembolsüz satır atlanır
                    ]
                ),
                encoding="utf-8",
            )
            data = cf.load_confirmed(tmp)
            hours = data["TLMTRY"]
            self.assertEqual([h["hour"] for h in hours], ["2026-11-28T06:00:00", "2026-11-28T07:00:00"])
            self.assertEqual(hours[0]["cvd_pct_of_volume"], 5.0)
        finally:
            tmp.unlink(missing_ok=True)

    def test_missing_file_returns_empty(self):
        self.assertEqual(cf.load_confirmed(pathlib.Path("olmayan-dosya.jsonl")), {})

    def _tmpfile(self):
        import tempfile

        fd, name = tempfile.mkstemp(suffix=".jsonl")
        pathlib.Path(name).write_text("", encoding="utf-8")
        import os

        os.close(fd)
        return name


class ScoreTest(unittest.TestCase):
    def test_strong_buy_and_sell(self):
        buy, _ = cf.score_confirmed([_hour("2026-11-28T06:00:00", 5.2)])
        sell, _ = cf.score_confirmed([_hour("2026-11-28T07:00:00", -11.9)])
        self.assertEqual(buy, 2)
        self.assertEqual(sell, -2)

    def test_reversal_penalty(self):
        score, reasons = cf.score_confirmed([_hour("2026-11-28T06:00:00", 5.2), _hour("2026-11-28T07:00:00", -11.9)])
        # -2 (satış) -1 (akış döndü)  => -3
        self.assertEqual(score, -3)
        self.assertTrue(any("tam tersine döndü" in r for r in reasons))

    def test_neutral_flow_scores_zero(self):
        score, _ = cf.score_confirmed([_hour("2026-11-28T06:00:00", 0.2)])
        self.assertEqual(score, 0)


class VerdictTest(unittest.TestCase):
    def test_bull_trap_needs_rising_price(self):
        hours = [_hour("2026-11-28T07:00:00", -11.9, open_=0.0578, close=0.0509, vwap=0.0532)]
        live = {"price": 0.0577, "change_15m_pct": 8.5, "taker_buy_pct_15m": 44.0}
        self.assertEqual(cf._verdict(-3, [], live, hours), "BOGA_TUZAGI")

    def test_falling_price_with_negative_flow_is_confirmed_sell(self):
        hours = [_hour("2026-11-28T07:00:00", -11.9, open_=0.0578, close=0.0509, vwap=0.0532)]
        live = {"price": 0.0500, "change_15m_pct": -3.0, "taker_buy_pct_15m": 40.0}
        self.assertEqual(cf._verdict(-3, [], live, hours), "ONAYLI_SATIS")

    def test_bear_trap_on_positive_flow_while_price_falls(self):
        hours = [_hour("2026-11-28T07:00:00", 6.0, open_=0.0600, close=0.0570, vwap=0.0580)]
        live = {"price": 0.0540, "change_15m_pct": -2.0, "taker_buy_pct_15m": 58.0}
        self.assertEqual(cf._verdict(2, [], live, hours), "AYI_TUZAGI")

    def test_no_confirmed_data_is_neutral_or_live_only(self):
        live = {"price": 1.0, "change_15m_pct": 0.2, "taker_buy_pct_15m": 50.0}
        self.assertEqual(cf._verdict(0, [], live, []), "NOTR")


class LiveReadTest(unittest.TestCase):
    def test_live_read_uses_closed_candles_only(self):
        rows = []
        for i in range(30):
            # [openTime, open, high, low, close, volume, closeTime, qv, trades, takerBase, takerQuote, ...]
            rows.append([i, "1.0", "1.0", "1.0", "1.0", "100", 0, "100", 5, "60", "60", "0"])
        # son (kapanmamış) mum uçuk değer taşısa bile okumaya girmemeli
        rows.append([99, "9.0", "9.0", "9.0", "9.0", "9999", 0, "9999", 5, "0", "0", "0"])
        live = cf.live_read(rows)
        self.assertAlmostEqual(live["price"], 1.0)
        self.assertAlmostEqual(live["taker_buy_pct_15m"], 60.0)
        self.assertAlmostEqual(live["volume_15m_try"], 1500.0)


if __name__ == "__main__":
    unittest.main()


class CacheTest(unittest.TestCase):
    """2026-11-28 performans: dosya ve canlı veri önbellekleri."""

    def test_load_confirmed_serves_from_cache_until_file_changes(self):
        import os as _os
        import tempfile

        fd, name = tempfile.mkstemp(suffix=".jsonl")
        _os.close(fd)  # Windows: açık handle dosya silmeyi engeller
        path = pathlib.Path(name)
        cf.reset_for_tests()
        try:
            path.write_text(
                json.dumps({"symbol": "AAA", "hour": "2026-11-28T06:00:00", "cvd_pct_of_volume": 1.0}) + "\n",
                encoding="utf-8",
            )
            first = cf.load_confirmed(path)
            second = cf.load_confirmed(path)
            self.assertIs(first, second)  # ayrıştırma tekrarlanmadı
            path.write_text(
                json.dumps({"symbol": "AAA", "hour": "2026-11-28T06:00:00", "cvd_pct_of_volume": 1.0})
                + "\n"
                + json.dumps({"symbol": "AAA", "hour": "2026-11-28T07:00:00", "cvd_pct_of_volume": -5.0})
                + "\n",
                encoding="utf-8",
            )
            third = cf.load_confirmed(path)
            self.assertIsNot(first, third)
            self.assertEqual(len(third["AAA"]), 2)
        finally:
            path.unlink(missing_ok=True)
            cf.reset_for_tests()

    def test_live_reads_are_cached_and_bad_symbols_are_skipped(self):
        import asyncio

        calls = {"ok": 0, "bad": 0}
        rows = [[i, "1.0", "1.0", "1.0", "1.0", "100", 0, "100", 5, "60", "60", "0"] for i in range(30)]

        async def fake_klines(symbol, interval, limit=60):
            if symbol == "BADTRY":
                calls["bad"] += 1
                raise RuntimeError("Invalid symbol")
            calls["ok"] += 1
            return rows

        original = cf.klines
        cf.klines = fake_klines
        cf.reset_for_tests()
        try:
            async def scenario():
                first = await cf._live_for("GOODTRY")
                second = await cf._live_for("GOODTRY")
                bad_first = await cf._live_for("BADTRY")
                bad_second = await cf._live_for("BADTRY")
                return first, second, bad_first, bad_second

            first, second, bad_first, bad_second = asyncio.run(scenario())
            self.assertEqual(first["price"], second["price"])
            self.assertEqual(calls["ok"], 1)  # TTL içinde tek çağrı
            self.assertEqual(bad_first, {})
            self.assertEqual(bad_second, {})
            self.assertEqual(calls["bad"], 1)  # negatif önbellek: tekrar denenmedi
        finally:
            cf.klines = original
            cf.reset_for_tests()
