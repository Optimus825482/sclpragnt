"""`fill_rising_alert_outcomes` kilitleri (2026-09-17).

NEDEN VAR: `rising_alerts` tablosuna mfe/mae/outcome kolonları eklenmişti ama
bunları dolduran HİÇBİR döngü yoktu → Raporlar > YÜKSELİŞ EĞİLİMİ sekmesindeki
Sonuç sütunu her satırda sonsuza dek BEKLİYOR gösteriyordu (kullanıcı raporu).

Kilitlenen davranış:
  1. Ufku (30 dk) dolmuş + pencereyi kapsayan mumları olan satır MÜHÜRLENİR:
     mfe/mae yazılır, outcome_state='filled'.
  2. Sinyal anının PARsiyel mumu ölçüye GİRMEZ (yalnız t0'dan sonra açılanlar).
  3. Taban = sinyalin KENDİ fiyatı; yoksa t0 öncesi son kapanmış mum.
  4. Pencere kapsanmadıysa (mumlar henüz gelmedi) satır BEKLER — erken MFE
     alt sınır olurdu, mühürleme YOK.
  5. Ömür sınırı (6h) doldu ve mum hiç gelmedi → 'expired' (sonsuz pending yok).
  6. Ufku henüz dolmamış satır sorguya hiç GİRMEZ.
  7. Dönüş değeri (filled, learn_entries) İKİLİSİDİR (2026-09-17): ölçülen MFE
     satırları hedef öğrenmeye (record_symbol_target_outcome) girdi olur →
     "rising ölçüm döngüsünden hedef öğrenme beslemesi" burada kilitlenir.

Testler Postgres gerektirmez: `_run_db` in-memory SQLite'a yönlendirilir
(test_w19_database_residual.py deseni).
"""
import os
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database as db  # noqa: E402

_BAR_MS = 5 * 60_000
_WINDOW_SEC = db._RISING_OUTCOME_WINDOW_SEC          # 30 dk
_EXPIRE_SEC = db._RISING_OUTCOME_EXPIRE_SEC          # 6 saat

_RISING_SCHEMA = """
CREATE TABLE rising_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
    score REAL, early_score INTEGER, strength REAL, green INTEGER,
    proximity REAL, gap_atr REAL, signals TEXT,
    price REAL, expected_price REAL, target_pct REAL, tf TEXT, source TEXT,
    notified BOOLEAN DEFAULT FALSE, sent_via_push BOOLEAN DEFAULT FALSE,
    auto_paper_trade_id INTEGER,
    outcome_state TEXT NOT NULL DEFAULT 'pending',
    mfe_pct REAL, mae_pct REAL, peak_at REAL
);
CREATE TABLE historical_candles (
    symbol TEXT, timeframe TEXT, open_time REAL, high REAL, low REAL, close REAL
);
"""


class FillRisingOutcomesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_RISING_SCHEMA)
        self._orig_run_db = db._run_db
        self._orig_ensure = db._ensure_rising_evidence_schema

        async def runner(operation):
            return operation(self.conn)

        # SQLite ADD COLUMN IF NOT EXISTS desteklemez; şema zaten tam.
        db._run_db = runner
        db._ensure_rising_evidence_schema = lambda _conn: None
        self.now = time.time()

    def tearDown(self):
        db._run_db = self._orig_run_db
        db._ensure_rising_evidence_schema = self._orig_ensure
        self.conn.close()

    # -- yardımcılar --------------------------------------------------------
    def _alert(self, created, symbol="TLMTRY", price=100.0):
        cur = self.conn.execute(
            "INSERT INTO rising_alerts(created_at, symbol, kind, price) "
            "VALUES(?,?,?,?)", (float(created), symbol, "yukselis", price))
        self.conn.commit()
        return int(cur.lastrowid)

    def _candle(self, symbol, open_time_ms, high, low, close):
        self.conn.execute(
            "INSERT INTO historical_candles(symbol, timeframe, open_time, high, low, close) "
            "VALUES(?,?,?,?,?,?)", (symbol, "5m", float(open_time_ms),
                                    float(high), float(low), float(close)))

    def _row(self, alert_id):
        row = self.conn.execute(
            "SELECT * FROM rising_alerts WHERE id=?", (alert_id,)).fetchone()
        return dict(row) if row else None

    def _t0(self, past_seconds=40 * 60):
        """t0 = şu andan `past_seconds` önce, 5m kova hizasına yuvarlanmış."""
        created = self.now - past_seconds
        created = round(created / 300.0) * 300.0
        return created, created * 1000.0

    # -- testler ------------------------------------------------------------
    async def test_filled_row_writes_mfe_mae_and_seals(self):
        created, t0_ms = self._t0()
        alert_id = self._alert(created, price=100.0)
        # t0'dan sonra 6 kapanmış mum: 100 → 104'e çıkıp 99'a inen seri.
        for step in range(6):
            o = t0_ms + step * _BAR_MS
            self._candle("TLMTRY", o, high=104.0, low=99.0, close=102.0)
        # Pencereyi kapsayan son mum: t0+30dk'yı taşıyan bar.
        self._candle("TLMTRY", t0_ms + 6 * _BAR_MS, 102.0, 101.0, 101.5)
        self.conn.commit()

        filled, learned = await db.fill_rising_alert_outcomes(limit=50)
        self.assertGreaterEqual(filled, 1)
        row = self._row(alert_id)
        self.assertEqual("filled", row["outcome_state"])
        self.assertAlmostEqual(4.0, float(row["mfe_pct"]), places=3)   # 104/100-1
        self.assertAlmostEqual(-1.0, float(row["mae_pct"]), places=3)  # 99/100-1
        self.assertIsNotNone(row["peak_at"])
        # BESLEME KANITI (madde 4): MFE olcumu hedef ogrenmeye GIRDI olarak doner
        # (donus (filled, learn_entries) ikilisi — 2026-09-17).
        self.assertEqual(1, len(learned))
        self.assertEqual("TLMTRY", learned[0]["symbol"])
        self.assertAlmostEqual(4.0, float(learned[0]["achieved_pct"]), places=3)

    async def test_partial_candle_at_t0_excluded_from_measurement(self):
        """t0 ANINDA açılmış mum sinyal-öncesi sayılır — ölçüye GİRMEZ."""
        created, t0_ms = self._t0()
        alert_id = self._alert(created, price=100.0)
        # t0 anındaki mum: high 120 (sinyal-öncesi hareket) — HARİÇ olmalı.
        self._candle("TLMTRY", t0_ms, high=120.0, low=98.0, close=100.0)
        for step in range(1, 7):
            o = t0_ms + step * _BAR_MS
            self._candle("TLMTRY", o, 101.0, 100.5, 101.0)
        self.conn.commit()

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        # 120'lik tepe ölçüme katılmadı; MFE sonraki mumların tepe fiyatından.
        self.assertAlmostEqual(1.0, float(row["mfe_pct"]), places=3)

    async def test_base_falls_back_to_prior_closed_candle(self):
        created, t0_ms = self._t0()
        alert_id = self._alert(created, price=None)   # fiyat kaydı yok
        # t0'da KAPANAN mum (t0-BAR_MS'de açılmış): taban çapası bu (MACD F-03
        # kuralı — t0'a eşit/önce açılmış son kapanmış mum).
        self._candle("TLMTRY", t0_ms - _BAR_MS, 100.5, 99.5, 100.0)
        # t0'dan SONRA açılan seriler (t0 anındaki mum yok).
        for step in range(1, 7):
            o = t0_ms + step * _BAR_MS
            self._candle("TLMTRY", o, 103.0, 100.0, 102.0)
        self.conn.commit()

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        self.assertEqual("filled", row["outcome_state"])
        self.assertAlmostEqual(3.0, float(row["mfe_pct"]), places=3)   # 103/100-1

    async def test_uncovered_window_stays_pending(self):
        """Pencereyi kapsayan mumlar henüz yoksa satır MÜHÜRLENMEZ."""
        created, t0_ms = self._t0(past_seconds=35 * 60)   # ufuk dolmuş (35>30)
        alert_id = self._alert(created, price=100.0)
        # Yalnız İLK 2 mum var — 30 dk penceresini kapsamıyor.
        for step in range(2):
            self._candle("TLMTRY", t0_ms + step * _BAR_MS, 110.0, 100.0, 105.0)
        self.conn.commit()

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        self.assertEqual("pending", row["outcome_state"])
        self.assertIsNone(row["mfe_pct"])

    async def test_no_candles_expires_after_lifetime(self):
        created, _ = self._t0(past_seconds=_EXPIRE_SEC + 600)
        alert_id = self._alert(created, price=100.0)
        # hiç mum yok

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        self.assertEqual("expired", row["outcome_state"])

    async def test_no_candles_fresh_row_waits(self):
        """Ömür sınırı dolmadan mum gelmediyse bekle (backfill şansı)."""
        created, _ = self._t0(past_seconds=40 * 60)      # 40 dk — ufuk dolmuş
        alert_id = self._alert(created, price=100.0)

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        self.assertEqual("pending", row["outcome_state"])

    async def test_fresh_signal_not_queried(self):
        """Ufku (30 dk) henüz dolmamış satır ölçüm adayı bile DEĞİLDİR."""
        created, t0_ms = self._t0(past_seconds=10 * 60)  # 10 dk önce
        alert_id = self._alert(created, price=100.0)
        for step in range(7):
            self._candle("TLMTRY", t0_ms + step * _BAR_MS, 130.0, 100.0, 120.0)
        self.conn.commit()

        await db.fill_rising_alert_outcomes(limit=50)
        row = self._row(alert_id)
        self.assertEqual("pending", row["outcome_state"])
        self.assertIsNone(row["mfe_pct"])


if __name__ == "__main__":
    unittest.main()
