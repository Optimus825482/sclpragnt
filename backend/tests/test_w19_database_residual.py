"""W19 — `database.py` artık kalan DATABASE bulguları için LOCK testleri.

Kapsam (her test, ilgili düzeltme GERİ ALINIRSA KIRILACAK şekilde yazıldı):

- **F-03**: alarm ileri-getiri BAZI, evren tabanıyla aynı çapaya bağlanmalı
  (t0'a eşit/önce açılmış SON kapanmış mumun kapanışı). Eskiden alarm anındaki
  canlı tick kullanılıyordu → LIFT baz sürüklenmesinden sapıyordu. Kullanılan
  kaynak satıra `base_source` olarak yazılmalı; `price` (görüntüleme) DEĞİŞMEZ.
- **F-09**: `base <= 0` satırları pencere dolunca expire edilmeli (eskiden
  sonsuza dek `pending` kalıp partiyi bloke ediyordu); tek bozuk satır tüm
  doldurma partisini iptal ETMEMELİ (satır bazı try/except + `outcome_attempts`);
  `pending` sorgusu deneme sayacıyla sınırlanmalı.
- **V-14**: `pnl_pct` YÜZDE, `max_favorable_pct`/`max_adverse_pct` KESİR. Rapor
  sınırında açık birimli ikizler (`*_ratio` + `*_pct`) eklenir; depolanan değer
  DEĞİŞMEZ ve eski alan geriye dönük uyum için KORUNUR.
- **V-20**: gerçekten ölü (sıfır okuyucu) ve ürün-dışı fonksiyonlar silinir;
  sadece-test / araştırma okuyucusu olan semboller korunur.

Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/w19_mutations.py`.
Testler Postgres gerektirmez: `_run_db` gerçek bir in-memory SQLite bağlantısına
yönlendirilir; üretilen SQL ve yazılan satır durumu doğrulanır.
"""
import os
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database as db  # noqa: E402

_BAR_MS = 5 * 60_000

_ALERT_SCHEMA = """
CREATE TABLE macd_monitor_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL, symbol TEXT, kind TEXT, score INTEGER, jump_min INTEGER,
    price REAL, signals TEXT, early_score INTEGER,
    outcome_state TEXT DEFAULT 'pending',
    outcome_5m_pct REAL, outcome_15m_pct REAL, outcome_30m_pct REAL,
    mfe_pct REAL, mae_pct REAL, filled_at REAL,
    base_source TEXT, outcome_attempts INTEGER DEFAULT 0
);
CREATE TABLE historical_candles (
    symbol TEXT, timeframe TEXT, open_time REAL, high REAL, low REAL, close REAL
);
CREATE TABLE macd_market_baseline (
    bucket_ts INTEGER, horizon TEXT, avg_pct REAL, med_pct REAL,
    hit_rate REAL, n_symbols INTEGER, filled_at REAL,
    PRIMARY KEY (bucket_ts, horizon)
);
"""

_TRADES_SCHEMA = """
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, strategy TEXT, side TEXT,
    entry_price REAL, exit_price REAL, quantity REAL,
    pnl REAL, pnl_pct REAL, entry_time REAL, exit_time REAL,
    commission REAL, reason TEXT, entry_context TEXT,
    max_favorable_pct REAL, max_adverse_pct REAL, hold_seconds REAL, trade_id TEXT
);
"""


class _RecordingConn:
    """`_ensure_macd_evidence_schema` için DDL ifadelerini kaydeden sahte bağlantı."""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(" ".join(str(sql).split()))

    def commit(self):
        pass


class _SqliteAlertHarness(unittest.IsolatedAsyncioTestCase):
    """`fill_macd_monitor_alert_outcomes`'u gerçek SQLite üzerinde koşturur."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_ALERT_SCHEMA)
        self._orig_run_db = db._run_db
        self._orig_ensure = db._ensure_macd_evidence_schema

        async def runner(operation):
            return operation(self.conn)

        # SQLite `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` desteklemez; şemayı
        # zaten tüm kolonlarla kurduğumuz için ensure'i devre dışı bırakıyoruz.
        db._run_db = runner
        db._ensure_macd_evidence_schema = lambda _conn: None
        self.now = time.time()

    def tearDown(self):
        db._run_db = self._orig_run_db
        db._ensure_macd_evidence_schema = self._orig_ensure
        self.conn.close()

    # -- yardımcılar --------------------------------------------------------
    def _alert(self, created, symbol, price, state="pending", attempts=0):
        cur = self.conn.execute(
            "INSERT INTO macd_monitor_alerts"
            "(created_at, symbol, kind, price, outcome_state, outcome_attempts) "
            "VALUES(?,?,?,?,?,?)",
            (float(created), symbol, "jump", price, state, attempts))
        self.conn.commit()
        return int(cur.lastrowid)

    def _candle(self, symbol, open_time, close, high=None, low=None):
        self.conn.execute(
            "INSERT INTO historical_candles(symbol, timeframe, open_time, high, low, close) "
            "VALUES(?,?,?,?,?,?)",
            (symbol, "5m", float(open_time),
             close if high is None else high,
             close if low is None else low,
             close))

    def _forward_series(self, symbol, t0_ms, closes, high=None, low=None):
        """t0'dan itibaren 5m'lik kapanmış mum serisi (t0, t0+5dk, ...)."""
        for step, close in enumerate(closes):
            self._candle(symbol, t0_ms + step * _BAR_MS, close, high=high, low=low)

    def _row(self, alert_id):
        row = self.conn.execute(
            "SELECT * FROM macd_monitor_alerts WHERE id=?", (alert_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# F-03 — alarm bazı = son kapanmış mum kapanışı (+ base_source)
# ---------------------------------------------------------------------------
class AlarmBaseAnchorTests(_SqliteAlertHarness):

    def _t0(self, past_seconds=40 * 60):
        """t0 (ms) = şu andan `past_seconds` önce; 5m kovasına hizalı."""
        created = self.now - past_seconds
        created = round(created / 300.0) * 300.0  # 5m kova hizası
        return created, created * 1000.0

    async def test_base_uses_last_closed_candle_not_live_tick(self):
        created, t0_ms = self._t0()
        alert = self._alert(created, "AAAUSDT", price=999.0)  # canlı tick ÇOK farklı
        # t0 anında açılan (yani t0'da kapanan) baz mumu + ileri mumlar.
        self._forward_series("AAAUSDT", t0_ms, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])

        filled = await db.fill_macd_monitor_alert_outcomes(limit=50)
        self.assertGreaterEqual(filled, 1)

        row = self._row(alert)
        self.assertEqual("filled", row["outcome_state"])
        # Baz 100 → 5m=+1.0%, 15m=+3.0%, 30m=+6.0%. Eğer canlı tick (999)
        # kullanılsaydı ~-89.9% çıkardı.
        self.assertAlmostEqual(1.0, row["outcome_5m_pct"], places=4)
        self.assertAlmostEqual(3.0, row["outcome_15m_pct"], places=4)
        self.assertAlmostEqual(6.0, row["outcome_30m_pct"], places=4)
        self.assertEqual("closed_candle", row["base_source"])
        # Görüntüleme kolonu DEĞİŞMEMELİ.
        self.assertEqual(999.0, row["price"])

    async def test_base_falls_back_to_live_tick_when_no_candle_at_or_before_t0(self):
        created, t0_ms = self._t0()
        alert = self._alert(created, "BBBUSDT", price=100.0)
        # Yalnız İLERİ mumlar (t0+5dk'dan başlar) → t0'a eşit/önce mum yok.
        for step, close in enumerate([101.0, 102.0, 103.0, 104.0, 105.0, 106.0], start=1):
            self._candle("BBBUSDT", t0_ms + step * _BAR_MS, close)

        await db.fill_macd_monitor_alert_outcomes(limit=50)
        row = self._row(alert)
        self.assertEqual("filled", row["outcome_state"])
        self.assertEqual("live_tick", row["base_source"])
        self.assertAlmostEqual(1.0, row["outcome_5m_pct"], places=4)  # 101/100

    async def test_base_falls_back_to_first_candle_when_no_tick(self):
        created, t0_ms = self._t0()
        alert = self._alert(created, "CCCUSDT", price=None)
        for step, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], start=1):
            self._candle("CCCUSDT", t0_ms + step * _BAR_MS, close)

        await db.fill_macd_monitor_alert_outcomes(limit=50)
        row = self._row(alert)
        self.assertEqual("filled", row["outcome_state"])
        self.assertEqual("first_candle", row["base_source"])


# ---------------------------------------------------------------------------
# F-09 — satır izolasyonu, base<=0 expire, deneme sınırı
# ---------------------------------------------------------------------------
class StuckPendingRowTests(_SqliteAlertHarness):

    async def test_base_zero_row_expires_after_window(self):
        created = self.now - 40 * 60  # pencere çoktan doldu
        t0_ms = created * 1000.0
        alert = self._alert(created, "ZEROUSDT", price=0.0)
        # Mum VAR ama close 0 → base <= 0 (eski kod burada koşulsuz `continue`
        # yapıp satırı sonsuza dek `pending` bırakıyordu).
        self._candle("ZEROUSDT", t0_ms, 0.0)

        await db.fill_macd_monitor_alert_outcomes(limit=50)
        row = self._row(alert)
        self.assertEqual("expired", row["outcome_state"],
                         "base<=0 satırı pencere dolunca expire edilmeli")
        self.assertIsNotNone(row["filled_at"])

    async def test_broken_row_does_not_abort_the_pass(self):
        created = self.now - 40 * 60
        t0_ms = created * 1000.0
        good = self._alert(created, "GOODUSDT", price=None)
        self._forward_series("GOODUSDT", t0_ms, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
        bad = self._alert(created, "BADUSDT", price=None)
        # close NULL → satır işlenirken TypeError (bozuk satır).
        self._candle("BADUSDT", t0_ms, None, high=1.0, low=1.0)

        filled = await db.fill_macd_monitor_alert_outcomes(limit=50)

        good_row = self._row(good)
        self.assertEqual("filled", good_row["outcome_state"],
                         "bozuk satır yüzünden SAĞLAM satır da doldurulmamalı")
        self.assertGreaterEqual(filled, 1)
        bad_row = self._row(bad)
        self.assertIsNotNone(bad_row)
        self.assertNotEqual("pending", bad_row["outcome_state"],
                            "pencere dolmuş bozuk satır expire edilmeli")
        self.assertGreaterEqual(int(bad_row["outcome_attempts"] or 0), 1)

    async def test_broken_row_increments_attempts_while_fresh(self):
        created = self.now - 30.0  # pencere dolmadı
        t0_ms = created * 1000.0
        bad = self._alert(created, "BADUSDT", price=None)
        self._candle("BADUSDT", t0_ms, None, high=1.0, low=1.0)

        await db.fill_macd_monitor_alert_outcomes(limit=50)
        row = self._row(bad)
        self.assertEqual("pending", row["outcome_state"],
                         "pencere dolmadan bozuk satır expire EDİLMEMELİ")
        self.assertEqual(1, int(row["outcome_attempts"]))

    async def test_pending_query_is_bounded_by_attempts(self):
        created = self.now - 40 * 60
        t0_ms = created * 1000.0
        limit = db._MACD_OUTCOME_MAX_ATTEMPTS
        # Sınırı aşmış satır: doldurulabilir olsa bile İŞLENMEMELİ.
        exhausted = self._alert(created, "BOUNDUSDT", price=None,
                                state="pending", attempts=limit)
        self._forward_series("BOUNDUSDT", t0_ms, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
        free = self._alert(created, "FREEUSDT", price=None)
        self._forward_series("FREEUSDT", t0_ms, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])

        await db.fill_macd_monitor_alert_outcomes(limit=50)

        bound_row = self._row(exhausted)
        self.assertEqual("pending", bound_row["outcome_state"],
                         "deneme sınırını aşan satır pending sorgusuna girmemeli")
        self.assertEqual(limit, int(bound_row["outcome_attempts"]))
        self.assertIsNone(bound_row["outcome_5m_pct"])
        self.assertEqual("filled", self._row(free)["outcome_state"])


class EvidenceSchemaDDLTests(unittest.TestCase):
    """F-03/F-09 — yeni kolonlar idempotent ALTER'lar ile eklenmeli."""

    def test_ensure_schema_adds_base_source_and_attempts(self):
        saved = db._MACD_EVIDENCE_SCHEMA_READY
        db._MACD_EVIDENCE_SCHEMA_READY = False
        conn = _RecordingConn()
        try:
            db._ensure_macd_evidence_schema(conn)
        finally:
            db._MACD_EVIDENCE_SCHEMA_READY = saved
        joined = " ".join(conn.statements)
        self.assertIn("ADD COLUMN IF NOT EXISTS base_source", joined)
        self.assertIn("ADD COLUMN IF NOT EXISTS outcome_attempts", joined)


# ---------------------------------------------------------------------------
# V-14 — birim sözleşmesi: `*_ratio` (kesir) + `*_pct` (yüzde) ikizleri
# ---------------------------------------------------------------------------
class ReportUnitContractTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_TRADES_SCHEMA)
        for symbol, mfe, mae in (("AUSDT", 0.01, -0.01), ("AUSDT", 0.02, -0.03)):
            self.conn.execute(
                "INSERT INTO trades(symbol, strategy, side, entry_price, exit_price, quantity, "
                "pnl, pnl_pct, entry_time, exit_time, commission, max_favorable_pct, max_adverse_pct) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, "MOMENTUM", "LONG", 100.0, 101.0, 10.0, 9.5, 0.95, 1.0, 2.0, 0.15, mfe, mae))
        self.conn.commit()
        self._orig_run_db = db._run_db

        async def runner(operation):
            return operation(self.conn)

        db._run_db = runner

    def tearDown(self):
        db._run_db = self._orig_run_db
        self.conn.close()

    async def test_twins_expose_ratio_and_percent(self):
        out = await db.get_report_trade_breakdown()
        overall = out["overall"]
        # AVG(mfe) = (0.01+0.02)/2 = 0.015 (KESİR); eski alan korunur.
        self.assertAlmostEqual(0.015, float(overall["avg_max_favorable"]), places=6)
        self.assertAlmostEqual(0.015, float(overall["avg_max_favorable_ratio"]), places=6)
        # Açık yüzde ikizi ×100.
        self.assertAlmostEqual(1.5, float(overall["avg_max_favorable_pct"]), places=4)
        self.assertAlmostEqual(-0.02, float(overall["avg_max_adverse_ratio"]), places=6)
        self.assertAlmostEqual(-2.0, float(overall["avg_max_adverse_pct"]), places=4)

    async def test_twin_relationship_holds_on_every_row(self):
        out = await db.get_report_trade_breakdown()
        rows = list(out["strategies"]) + list(out["symbols"])
        self.assertTrue(rows)
        for row in rows:
            ratio = float(row["avg_max_favorable_ratio"])
            self.assertAlmostEqual(ratio * 100.0, float(row["avg_max_favorable_pct"]), places=4)
            ratio_a = float(row["avg_max_adverse_ratio"])
            self.assertAlmostEqual(ratio_a * 100.0, float(row["avg_max_adverse_pct"]), places=4)
        symbol_row = out["symbols"][0]
        # Eski (kesir) alan korunur ve yeni ratio ile aynıdır.
        self.assertAlmostEqual(float(symbol_row["avg_mfe_pct"]),
                               float(symbol_row["avg_max_favorable_ratio"]), places=6)


# ---------------------------------------------------------------------------
# V-20 — ölü kod tasfiyesi (sıfır okuyucu + ürün-dışı TEK semboller)
# ---------------------------------------------------------------------------
class DeadCodeRemovalTests(unittest.TestCase):

    def test_dangerous_and_superseded_functions_are_removed(self):
        # update_wallet_balance: kilitsiz kör UPSERT; V-01 para yolu için tehlikeli.
        self.assertFalse(hasattr(db, "update_wallet_balance"),
                         "update_wallet_balance sıfır okuyucu → silinmeli")
        # save_auto_paper_trade: atomik olmayan salt INSERT; open_auto_paper_trade
        # onun yerini aldı (I-11: 'kablolamayın — silin').
        self.assertFalse(hasattr(db, "save_auto_paper_trade"),
                         "save_auto_paper_trade sıfır okuyucu → silinmeli")

    def test_unwired_product_hooks_are_kept(self):
        # Bu fonksiyonların da okuyucusu yoktu; ancak meşru ürün yetenekleri
        # (yedek/disk, admin silme, salt-okunur rapor erişimcileri). I-11 bunları
        # "eksik kablolama / kullanıcı kararı" olarak sınıflar → KORUNUR.
        for name in ("create_backup_file", "delete_position", "get_reset_cutoff",
                     "get_all_symbol_target_states"):
            self.assertTrue(callable(getattr(db, name, None)),
                            f"{name} kaldırılmamalı (ürün-tipi kablolanmamış kanca)")


if __name__ == "__main__":
    unittest.main()
