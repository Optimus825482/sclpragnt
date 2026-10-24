"""Günün ilk bildirimi izleyicisi (2026-10-25): MFE/MAE katlama, kayıt, izleme ve rapor ucu.

Kilitler:
  * `fold_excursions`: yükselip düşen mumlarda tepe/dip ve zamanları; gün sonundan sonraki mum sayılmaz;
    bildirim anını içeren yarım mum sayılmaz; artımlı güncelleme önceki tepeyi korur; MAE <= 0, MFE >= 0
  * `register_today`: sembol başına EN ERKEN push denenmiş bildirim; panel-only satır sayılmaz; sembol normalize;
    ikinci koşu var olan satırı ezmez
  * `track`: mumlar DB satırına yazılır; gün geçince finalized; bir sembolün mum hatası diğerini durdurmaz
  * uç nokta: satır alanları + gün özeti (adet, ort. MFE/MAE, MFE >= %1 payı)
"""
import asyncio
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app import daily_first_notification as dfn
from app import database, push_daily_counter
from app.routers import reports

# 2026-10-24 00:00 Europe/Istanbul (UTC+3) = 2026-10-23 21:00 UTC
DAY_KEY = "2026-10-24"
DAY_START = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc).timestamp()
DAY_END = DAY_START + 86400 - 1
FIRST_TS = DAY_START + 10 * 3600 + 30  # 10:00:30 İstanbul (10:00 mumunun ortası)
FIRST_MS = int(FIRST_TS * 1000)


def _candle(open_ts: float, o: float, h: float, l: float, c: float) -> list:
    return [int(open_ts * 1000), str(o), str(h), str(l), str(c), "0", int(open_ts * 1000) + 59_999]


def _memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE monitoring_notifications("
        "id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, detected_at REAL NOT NULL, price REAL,"
        "sent_via_push INTEGER NOT NULL DEFAULT 0, push_attempted INTEGER)")
    conn.execute(
        "CREATE TABLE daily_first_notification("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, day_key TEXT NOT NULL,"
        "first_notification_id INTEGER, first_ts REAL NOT NULL, first_price REAL,"
        "mfe_pct REAL, mfe_ts REAL, mae_pct REAL, mae_ts REAL, last_tracked_ts REAL,"
        "finalized INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL,"
        "UNIQUE(symbol, day_key))")
    conn.commit()
    return conn


class DayBoundsTests(unittest.TestCase):
    def test_day_bounds_are_istanbul_midnight_to_23_59_59(self):
        start, end = dfn.day_bounds(DAY_KEY)
        self.assertEqual(DAY_START, start)
        self.assertEqual(DAY_END, end)
        self.assertEqual(DAY_KEY, push_daily_counter.day_key(end))
        self.assertEqual("2026-10-25", push_daily_counter.day_key(end + 1))

    def test_previous_day_key(self):
        self.assertEqual("2026-10-23", dfn.previous_day_key(DAY_START + 5))
        self.assertEqual("2026-10-23", dfn.previous_day_key(DAY_END))


class FoldExcursionsTests(unittest.TestCase):
    def test_rising_then_falling_candles(self):
        m = DAY_START + 10 * 3600  # 10:00 mumu (bildirim anını içerir → sayılmaz)
        candles = [
            _candle(m, 100, 130, 99, 101),          # yarım mum: 130 tepe SAYILMAZ
            _candle(m + 60, 101, 103, 100.5, 102),  # +3%
            _candle(m + 120, 102, 105, 101, 104),   # +5% tepe
            _candle(m + 180, 104, 104.5, 97, 98),   # -3% dip
            _candle(m + 240, 98, 99, 98, 98.5),
        ]
        out = dfn.fold_excursions(candles, 100.0, FIRST_TS, DAY_END)
        self.assertAlmostEqual(5.0, out["mfe_pct"], places=6)
        self.assertEqual(m + 120, out["mfe_ts"])
        self.assertAlmostEqual(-3.0, out["mae_pct"], places=6)
        self.assertEqual(m + 180, out["mae_ts"])
        self.assertEqual(m + 240, out["last_open_ts"])

    def test_candles_after_day_end_ignored(self):
        m = DAY_START + 23 * 3600 + 58 * 60  # 23:58
        candles = [
            _candle(m, 100, 101, 99.5, 100.5),
            _candle(m + 60, 100.5, 102, 100, 101),      # 23:59 → sayılır
            _candle(m + 120, 101, 150, 50, 120),        # ertesi gün 00:00 → SAYILMAZ
        ]
        out = dfn.fold_excursions(candles, 100.0, m - 3600, DAY_END)
        self.assertAlmostEqual(2.0, out["mfe_pct"], places=6)
        self.assertAlmostEqual(-0.5, out["mae_pct"], places=6)
        self.assertEqual(m + 60, out["last_open_ts"])

    def test_incremental_update_keeps_earlier_max_and_min(self):
        m = DAY_START + 11 * 3600
        state = {"mfe_pct": 5.0, "mfe_ts": m - 600, "mae_pct": -3.0, "mae_ts": m - 300, "last_open_ts": m - 60}
        candles = [
            _candle(m, 100, 104, 98, 103),      # +4 < 5, -2 > -3 → değişmez
            _candle(m + 60, 103, 105, 99, 104),  # +5 eşit → İLK tepe korunur
        ]
        out = dfn.fold_excursions(candles, 100.0, FIRST_TS, DAY_END, state=state)
        self.assertEqual(5.0, out["mfe_pct"])
        self.assertEqual(m - 600, out["mfe_ts"])
        self.assertEqual(-3.0, out["mae_pct"])
        self.assertEqual(m - 300, out["mae_ts"])
        self.assertEqual(m + 60, out["last_open_ts"])
        # Yeni tepe gelirse yazılır
        out2 = dfn.fold_excursions([_candle(m + 120, 104, 110, 103, 109)], 100.0, FIRST_TS, DAY_END, state=out)
        self.assertAlmostEqual(10.0, out2["mfe_pct"], places=6)
        self.assertEqual(m + 120, out2["mfe_ts"])
        self.assertEqual(-3.0, out2["mae_pct"])

    def test_sign_convention_mfe_non_negative_mae_non_positive(self):
        m = DAY_START + 12 * 3600
        # Yalnız düşen mumlar: MFE 0'a kırpılır, MAE negatif
        out = dfn.fold_excursions([_candle(m, 99, 99.5, 95, 96)], 100.0, FIRST_TS, DAY_END)
        self.assertEqual(0.0, out["mfe_pct"])
        self.assertAlmostEqual(-5.0, out["mae_pct"], places=6)
        # Yalnız yükselen mumlar: MAE 0'a kırpılır
        out = dfn.fold_excursions([_candle(m, 101, 106, 100.5, 105)], 100.0, FIRST_TS, DAY_END)
        self.assertAlmostEqual(6.0, out["mfe_pct"], places=6)
        self.assertEqual(0.0, out["mae_pct"])

    def test_no_usable_candles_and_no_state_returns_none(self):
        self.assertIsNone(dfn.fold_excursions([], 100.0, FIRST_TS, DAY_END))
        self.assertIsNone(dfn.fold_excursions([_candle(DAY_START, 1, 2, 0.5, 1)], 100.0, FIRST_TS, DAY_END))
        self.assertIsNone(dfn.fold_excursions([_candle(DAY_START + 3600, 1, 2, 0.5, 1)], 0.0, FIRST_TS, DAY_END))


class RegisterTodayTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_db()

        async def fake_run_db(operation):
            return operation(self.conn)

        self._patch = patch.object(database, "_run_db", fake_run_db)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.conn.close()

    def _insert_notifications(self, rows):
        self.conn.executemany(
            "INSERT INTO monitoring_notifications(id, symbol, detected_at, price, sent_via_push, push_attempted) "
            "VALUES(?,?,?,?,?,?)", rows)
        self.conn.commit()

    def _rows(self):
        cur = self.conn.execute(
            "SELECT symbol, day_key, first_notification_id, first_ts, first_price, finalized "
            "FROM daily_first_notification ORDER BY day_key, symbol")
        return [tuple(r) for r in cur.fetchall()]

    def test_earliest_push_row_per_symbol_panel_only_ignored(self):
        self._insert_notifications([
            # (id, symbol, detected_at, price, sent_via_push, push_attempted)
            (1, "TREETRY", DAY_START - 3600, 1.0, 1, 1),      # dün → bugüne girmez
            (2, "TREETRY", DAY_START + 60, 0.5, 0, None),     # yalnız panel → SAYILMAZ
            (3, "TREETRY", DAY_START + 120, 0.6, 1, 1),       # TREE ilk (push)
            (4, "BTC_TRY", DAY_START + 90, 100.0, 0, 1),      # push denenmiş (başarısız) → BTC ilk
            (5, "btctry", DAY_START + 100, 101.0, 1, 1),      # aynı coin, sonra
            (6, "TREETRY", DAY_START + 300, 0.7, 1, 1),
            (7, "ALERT", DAY_START + 10, None, 1, 1),         # coin değil → atlanır
        ])
        inserted = asyncio.run(dfn.register_today(now=DAY_START + 3600))
        self.assertEqual(2, inserted)
        self.assertEqual([
            ("BTCTRY", DAY_KEY, 4, DAY_START + 90, 100.0, 0),
            ("TREETRY", DAY_KEY, 3, DAY_START + 120, 0.6, 0),
        ], self._rows())

    def test_second_run_does_not_overwrite_existing_rows(self):
        self._insert_notifications([(3, "TREETRY", DAY_START + 120, 0.6, 1, 1)])
        self.assertEqual(1, asyncio.run(dfn.register_today(now=DAY_START + 3600)))
        # Daha erken bir satır sonradan "görünse" bile mevcut kayıt korunur (idempotent)
        self._insert_notifications([(2, "TREETRY", DAY_START + 30, 0.4, 1, 1)])
        self.assertEqual(0, asyncio.run(dfn.register_today(now=DAY_START + 7200)))
        self.assertEqual([("TREETRY", DAY_KEY, 3, DAY_START + 120, 0.6, 0)], self._rows())

    def test_include_previous_registers_yesterday_too(self):
        self._insert_notifications([
            (1, "SOLTRY", DAY_START - 7200, 10.0, 1, 1),   # dün
            (2, "SOLTRY", DAY_START + 60, 11.0, 1, 1),     # bugün
        ])
        self.assertEqual(2, asyncio.run(dfn.register_today(now=DAY_START + 3600, include_previous=True)))
        self.assertEqual([
            ("SOLTRY", "2026-10-23", 1, DAY_START - 7200, 10.0, 0),
            ("SOLTRY", DAY_KEY, 2, DAY_START + 60, 11.0, 0),
        ], self._rows())

    def test_missing_price_is_stored_as_null(self):
        self._insert_notifications([(1, "XRPTRY", DAY_START + 60, None, 1, 1)])
        asyncio.run(dfn.register_today(now=DAY_START + 3600))
        self.assertEqual([("XRPTRY", DAY_KEY, 1, DAY_START + 60, None, 0)], self._rows())


class TrackTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_db()

        async def fake_run_db(operation):
            return operation(self.conn)

        self._patch = patch.object(database, "_run_db", fake_run_db)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.conn.close()

    def _seed(self, symbol, first_ts=FIRST_TS, first_price=100.0, **extra):
        cols = {"symbol": symbol, "day_key": DAY_KEY, "first_notification_id": 1, "first_ts": first_ts,
                "first_price": first_price, "finalized": 0, "created_at": first_ts, "updated_at": first_ts}
        cols.update(extra)
        self.conn.execute(
            "INSERT INTO daily_first_notification(" + ",".join(cols) + ") VALUES(" + ",".join("?" * len(cols)) + ")",
            tuple(cols.values()))
        self.conn.commit()

    def _row(self, symbol):
        r = self.conn.execute("SELECT * FROM daily_first_notification WHERE symbol=?", (symbol,)).fetchone()
        return dict(r) if r else None

    def test_track_writes_mfe_mae_and_finalizes_after_day_end(self):
        self._seed("TREETRY")
        m = DAY_START + 10 * 3600
        candles = [
            _candle(m, 100, 130, 99, 101),           # yarım mum → sayılmaz
            _candle(m + 60, 101, 103, 100.5, 102),
            _candle(m + 120, 102, 105, 101, 104),    # +5
            _candle(m + 180, 104, 104.5, 97, 98),    # -3
        ]
        calls = []

        async def fake_klines(symbol, interval, limit=500, start_time_ms=None, end_time_ms=None):
            calls.append((symbol, interval, start_time_ms, end_time_ms))
            return [c for c in candles if start_time_ms <= c[0] <= end_time_ms]

        now1 = m + 300
        with patch("app.binance_tr_public.klines", new=fake_klines):
            stats = asyncio.run(dfn.track(now=now1))
        self.assertEqual({"updated": 1, "finalized": 0, "errors": 0}, stats)
        row = self._row("TREETRY")
        self.assertAlmostEqual(5.0, row["mfe_pct"], places=6)
        self.assertEqual(m + 120, row["mfe_ts"])
        self.assertAlmostEqual(-3.0, row["mae_pct"], places=6)
        self.assertEqual(m + 180, row["mae_ts"])
        self.assertEqual(m + 180, row["last_tracked_ts"])
        self.assertEqual(0, row["finalized"])
        self.assertEqual(("TREETRY", "1m", int(m * 1000), int(now1 * 1000)), calls[0])

        # İkinci tur: yalnız son mumdan itibaren çekilir; yeni tepe yazılır, eski dip korunur
        candles.append(_candle(m + 240, 98, 108, 98, 107))
        with patch("app.binance_tr_public.klines", new=fake_klines):
            asyncio.run(dfn.track(now=m + 360))
        self.assertEqual(int((m + 180) * 1000), calls[1][2])
        row = self._row("TREETRY")
        self.assertAlmostEqual(8.0, row["mfe_pct"], places=6)
        self.assertEqual(m + 240, row["mfe_ts"])
        self.assertAlmostEqual(-3.0, row["mae_pct"], places=6)

        # Gün sonu geçti → son tur ve finalized; sonraki günün mumu sayılmaz
        candles.append(_candle(DAY_END + 1, 107, 200, 10, 150))
        with patch("app.binance_tr_public.klines", new=fake_klines):
            stats = asyncio.run(dfn.track(now=DAY_END + 600))
        self.assertEqual({"updated": 0, "finalized": 1, "errors": 0}, stats)
        row = self._row("TREETRY")
        self.assertEqual(1, row["finalized"])
        self.assertAlmostEqual(8.0, row["mfe_pct"], places=6)
        self.assertLessEqual(calls[-1][3], int(DAY_END * 1000))

        # Kapanan satır bir daha izlenmez
        n_calls = len(calls)
        with patch("app.binance_tr_public.klines", new=fake_klines):
            asyncio.run(dfn.track(now=DAY_END + 1200))
        self.assertEqual(n_calls, len(calls))

    def test_one_symbol_error_does_not_stop_others(self):
        self._seed("BADTRY")
        self._seed("GOODTRY")
        m = DAY_START + 10 * 3600

        async def fake_klines(symbol, interval, limit=500, start_time_ms=None, end_time_ms=None):
            if symbol == "BADTRY":
                raise RuntimeError("binance yok")
            return [_candle(m + 60, 100, 102, 99, 101)]

        with patch("app.binance_tr_public.klines", new=fake_klines), \
             self.assertLogs("scalper.daily_first_notification", level="WARNING") as logs:
            stats = asyncio.run(dfn.track(now=m + 300))
        self.assertEqual({"updated": 1, "finalized": 0, "errors": 1}, stats)
        self.assertAlmostEqual(2.0, self._row("GOODTRY")["mfe_pct"], places=6)
        self.assertIsNone(self._row("BADTRY")["mfe_pct"])
        self.assertTrue(any("BADTRY" in line for line in logs.output))

    def test_missing_first_price_filled_from_first_candle_open(self):
        self._seed("XRPTRY", first_price=None)
        m = DAY_START + 10 * 3600

        async def fake_klines(symbol, interval, limit=500, start_time_ms=None, end_time_ms=None):
            return [_candle(m, 1.0, 1.5, 0.9, 1.1), _candle(m + 60, 2.0, 2.2, 1.9, 2.1)]

        with patch("app.binance_tr_public.klines", new=fake_klines):
            asyncio.run(dfn.track(now=m + 300))
        row = self._row("XRPTRY")
        self.assertEqual(2.0, row["first_price"])
        self.assertAlmostEqual(10.0, row["mfe_pct"], places=6)
        self.assertAlmostEqual(-5.0, row["mae_pct"], places=6)


class ReportEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_shape_and_daily_summary(self):
        rows = [
            {"id": 3, "symbol": "BTCTRY", "day_key": DAY_KEY, "first_notification_id": 9, "first_ts": DAY_START + 60,
             "first_price": 100.0, "mfe_pct": 2.5, "mfe_ts": DAY_START + 600, "mae_pct": -1.0, "mae_ts": DAY_START + 300,
             "last_tracked_ts": DAY_START + 900, "finalized": False, "created_at": 1.0, "updated_at": 2.0},
            {"id": 4, "symbol": "TREETRY", "day_key": DAY_KEY, "first_notification_id": 10, "first_ts": DAY_START + 120,
             "first_price": 0.5, "mfe_pct": 0.5, "mfe_ts": DAY_START + 700, "mae_pct": -3.0, "mae_ts": DAY_START + 400,
             "last_tracked_ts": DAY_START + 900, "finalized": False, "created_at": 1.0, "updated_at": 2.0},
            {"id": 5, "symbol": "SOLTRY", "day_key": DAY_KEY, "first_notification_id": 11, "first_ts": DAY_START + 130,
             "first_price": 5.0, "mfe_pct": None, "mfe_ts": None, "mae_pct": None, "mae_ts": None,
             "last_tracked_ts": None, "finalized": False, "created_at": 1.0, "updated_at": 2.0},
            {"id": 1, "symbol": "ETHTRY", "day_key": "2026-10-23", "first_notification_id": 2, "first_ts": DAY_START - 7200,
             "first_price": 50.0, "mfe_pct": 1.0, "mfe_ts": DAY_START - 7000, "mae_pct": 0.0, "mae_ts": DAY_START - 7100,
             "last_tracked_ts": DAY_START - 60, "finalized": True, "created_at": 1.0, "updated_at": 2.0},
        ]
        with patch.object(reports.database, "list_daily_first_notifications",
                          new_callable=AsyncMock, return_value=rows) as q, \
             patch.object(reports.time, "time", return_value=DAY_START + 3600):
            payload = await reports.get_daily_first_notification_report(days=7)
        q.assert_awaited_once()
        self.assertEqual("2026-10-18", q.await_args.args[0])  # 7 gün: 18..24 Ekim
        self.assertEqual(7, payload["days"])
        self.assertEqual("negative", payload["mae_sign"])
        self.assertEqual(DAY_KEY, payload["today_day_key"])
        self.assertEqual(4, payload["total"])
        self.assertEqual(
            {"id", "symbol", "day_key", "first_notification_id", "first_ts", "first_price",
             "mfe_pct", "mfe_ts", "mae_pct", "mae_ts", "last_tracked_ts", "finalized"},
            set(payload["rows"][0].keys()))
        self.assertEqual([DAY_KEY, "2026-10-23"], [s["day_key"] for s in payload["summary"]])
        today = payload["summary"][0]
        self.assertEqual(3, today["count"])
        self.assertEqual(2, today["measured"])
        self.assertEqual(0, today["finalized"])
        self.assertAlmostEqual(1.5, today["avg_mfe_pct"])
        self.assertAlmostEqual(-2.0, today["avg_mae_pct"])
        self.assertAlmostEqual(50.0, today["mfe_ge_1_share_pct"])
        yesterday = payload["summary"][1]
        self.assertEqual(1, yesterday["finalized"])
        self.assertAlmostEqual(100.0, yesterday["mfe_ge_1_share_pct"])

    async def test_days_clamped(self):
        with patch.object(reports.database, "list_daily_first_notifications",
                          new_callable=AsyncMock, return_value=[]):
            self.assertEqual(1, (await reports.get_daily_first_notification_report(days=0))["days"])
            self.assertEqual(60, (await reports.get_daily_first_notification_report(days=999))["days"])


if __name__ == "__main__":
    unittest.main()
