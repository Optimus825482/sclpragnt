"""Cüzdan komisyonu = PnL komisyonu (2026-10-17).

Kök sorun
---------
PnL 2026-10-16'dan beri EFEKTİF oranlarla hesaplanıyordu (taker
`paper_ledger.commission_pct()`, kâr al çıkışında maker
`paper_ledger.exit_commission_pct(reason)`), ama paper cüzdanlar hâlâ ham
`config.COMMISSION_PCT` (0.0015) ile debit/credit ediyordu. Her tam turda
cüzdan nakdi işlem kayıtlarının ima ettiği değerin ALTINA kayıyordu.

Bu testler iki şeyi kilitler:
  1. Düz fiyatlı bir tam tur cüzdanı TAM OLARAK giriş ücreti + çıkış ücreti
     kadar azaltır (otonom paper, ana defter, kombine paper).
  2. Eski (ham oranla düşülmüş, oranı saklanmamış) ve yeni (oranı saklı)
     satırların karışık olduğu bir defterde `reconcile_portfolio` ve
     `preview_portfolio_reconcile` no-op'tur — geçmiş cüzdan yanlış "onarılmaz".

Gerçek veritabanı fonksiyonları bellek-içi sqlite üzerinde koşar
(`_SqliteCompat`, Postgres'e özgü `FOR UPDATE`/advisory lock'u nötrler).
"""
import asyncio
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from app import database, paper_ledger
from app.config import config

_SCHEMA = """
CREATE TABLE virtual_wallet (asset TEXT PRIMARY KEY, amount REAL);
CREATE TABLE llm_settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE positions (symbol TEXT PRIMARY KEY, side TEXT, entry_price REAL, stop_price REAL,
  take_profit REAL, peak_price REAL, breakeven_hit BOOLEAN, quantity REAL, entry_time REAL,
  strategy TEXT, entry_context TEXT, trade_id TEXT, entry_commission_pct REAL);
CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, strategy TEXT, side TEXT,
  entry_price REAL, exit_price REAL, quantity REAL, pnl REAL, pnl_pct REAL, entry_time REAL,
  exit_time REAL, commission REAL, reason TEXT, entry_context TEXT, max_favorable_pct REAL,
  max_adverse_pct REAL, hold_seconds REAL, trade_id TEXT,
  entry_commission_pct REAL, exit_commission_pct REAL);
CREATE TABLE auto_paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
  side TEXT NOT NULL DEFAULT 'LONG', status TEXT NOT NULL DEFAULT 'open', notification_id INTEGER,
  notification_key TEXT, entry_price REAL NOT NULL, quantity REAL NOT NULL,
  order_value_try REAL NOT NULL, stop_loss REAL, take_profit REAL, peak_price REAL,
  entry_time REAL NOT NULL, exit_price REAL, exit_time REAL, pnl REAL, pnl_pct REAL,
  commission REAL, exit_reason TEXT, notification_score REAL, notification_target_pct REAL,
  notification_expected_price REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  entry_commission_pct REAL, exit_commission_pct REAL);
CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, symbol TEXT,
  action TEXT, price REAL, reason TEXT, strategy TEXT, trade_id TEXT);
CREATE TABLE decision_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, symbol TEXT,
  strategy TEXT, decision TEXT, reason TEXT, price REAL, metadata TEXT);
CREATE TABLE analysis_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT,
  timeframe TEXT, captured_at REAL, source TEXT, methodology_version TEXT, regime TEXT,
  regime_confidence REAL, confluence_score REAL, payload TEXT, trade_id TEXT);
CREATE TABLE combined_paper_wallet (asset TEXT PRIMARY KEY, amount REAL);
CREATE TABLE combined_paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT,
  status TEXT, entry_price REAL, quantity REAL, order_value_try REAL, take_profit REAL,
  stop_loss REAL, tp_pct REAL, potential_pct REAL, score REAL, peak_price REAL,
  trailing_activated BOOLEAN, breakeven_activated BOOLEAN, report_id INTEGER,
  notification_key TEXT, entry_time REAL, last_checked_at REAL, created_at REAL,
  updated_at REAL, commission REAL, exit_price REAL, exit_time REAL, exit_reason TEXT,
  pnl REAL, pnl_pct REAL);
"""

CASH = config.CASH_ASSET
INITIAL = float(config.INITIAL_BALANCE_TRY)
RAW = float(config.COMMISSION_PCT)


class _SqliteCompat:
    """`database` op'larının beklediği bağlantı yüzeyi, sqlite üzerinde."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def execute(self, sql, params=()):
        if "pg_advisory_xact_lock" in sql:
            return self.conn.execute("SELECT 1")
        return self.conn.execute(sql.replace(" FOR UPDATE", ""), params)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def cash(self, table="virtual_wallet") -> float:
        return float(self.conn.execute(f"SELECT amount FROM {table} WHERE asset=?", (CASH,)).fetchone()[0])

    def set_cash(self, amount, table="virtual_wallet"):
        self.conn.execute(f"INSERT OR REPLACE INTO {table}(asset,amount) VALUES(?,?)", (CASH, amount))
        self.conn.commit()


class _LedgerCase(unittest.TestCase):
    """Bellek-içi defter + `_run_db` yönlendirmesi + sabit komisyon modeli."""

    TAKER = 0.001125
    MAKER = 0.000675

    def setUp(self):
        self.db = _SqliteCompat()
        self.db.set_cash(INITIAL)

        async def run(op):
            return op(self.db)

        patches = [
            patch.object(database, "_run_db", run),
            patch.object(database, "_ensure_combined_paper_schema", lambda _conn: None),
            # Oranlar açıkça sabitlenir: test ortamın BNB/override ayarından bağımsız.
            patch.object(paper_ledger, "commission_pct", lambda: self.TAKER),
            patch.object(paper_ledger, "maker_commission_pct", lambda: self.MAKER),
            patch.object(config, "PAPER_TP_MAKER_FILL", True),
            patch("app.embedding_worker.worker.enqueue_persistent", AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # --- otonom paper yardımcıları -------------------------------------------------
    def open_auto(self, symbol, price, notional, entry_time):
        trade = {"symbol": symbol, "entry_price": price, "quantity": notional / price,
                 "order_value_try": notional, "entry_time": entry_time,
                 "created_at": entry_time, "updated_at": entry_time}
        row, status = asyncio.run(database.open_auto_paper_trade(trade, {}))
        self.assertEqual("opened", status)
        return row

    def close_auto(self, row, exit_price, reason, exit_time):
        """`auto_paper._close_trade` ile aynı zincir: settle_close → close_auto_paper_trade."""
        settled = paper_ledger.settle_close(row["entry_price"], exit_price, row["quantity"],
                                            slippage=0.0, exit_kind=reason)
        ok = asyncio.run(database.close_auto_paper_trade(
            row["id"], settled["fill_price"], exit_time, settled["pnl"], settled["pnl_pct"],
            settled["commission"], reason, exit_commission_pct=settled["exit_commission_pct"]))
        self.assertTrue(ok)
        return settled


class FlatRoundTripWalletTests(_LedgerCase):
    """Düz fiyatlı tam tur: cüzdan değişimi = −(giriş ücreti + çıkış ücreti)."""

    def test_auto_paper_taker_exit(self):
        notional = 1000.0
        row = self.open_auto("FLATTRY", 10.0, notional, 100.0)
        self.assertAlmostEqual(INITIAL - notional * (1 + self.TAKER), self.db.cash(), places=9)
        settled = self.close_auto(row, 10.0, "max_duration", 200.0)
        entry_fee, exit_fee = notional * self.TAKER, notional * self.TAKER
        self.assertAlmostEqual(-(entry_fee + exit_fee), self.db.cash() - INITIAL, places=9)
        self.assertAlmostEqual(settled["pnl"], self.db.cash() - INITIAL, places=9,
                               msg="cüzdan değişimi kayıtlı PnL'e eşit olmalı")

    def test_auto_paper_take_profit_exit_is_maker(self):
        notional = 1000.0
        row = self.open_auto("TPTRY", 10.0, notional, 100.0)
        settled = self.close_auto(row, 10.0, "take_profit", 200.0)
        self.assertAlmostEqual(self.MAKER, settled["exit_commission_pct"])
        entry_fee, exit_fee = notional * self.TAKER, notional * self.MAKER
        self.assertAlmostEqual(-(entry_fee + exit_fee), self.db.cash() - INITIAL, places=9)
        stored = self.db.conn.execute(
            "SELECT entry_commission_pct, exit_commission_pct FROM auto_paper_trades WHERE id=?",
            (row["id"],)).fetchone()
        self.assertEqual((self.TAKER, self.MAKER), tuple(stored), "bacak oranları satıra yazılmalı")

    def test_auto_paper_non_flat_wallet_equals_pnl(self):
        row = self.open_auto("WINTRY", 10.0, 1000.0, 100.0)
        settled = self.close_auto(row, 10.3, "trailing_stop", 200.0)
        self.assertAlmostEqual(settled["pnl"], self.db.cash() - INITIAL, places=9)

    def test_main_ledger_flat_round_trip(self):
        price, qty = 20.0, 50.0
        notional = price * qty
        pos = {"side": "LONG", "entry_price": price, "quantity": qty, "entry_time": 100.0,
               "strategy": "CHAT_PREDICTION", "trade_id": "t-flat", "entry_context": {}}
        sig = {"symbol": "MAINTRY", "action": "BUY_SIGNAL", "price": price, "timestamp": 100.0,
               "trade_id": "t-flat"}
        asyncio.run(database.commit_open_position("MAINTRY", "MAIN", 0.0, qty, pos, sig))
        self.assertAlmostEqual(INITIAL - notional * (1 + self.TAKER), self.db.cash(), places=9)
        reason = "take_profit"
        exit_fee = notional * paper_ledger.exit_commission_pct(reason)
        entry_fee = notional * self.TAKER
        trade = {"symbol": "MAINTRY", "strategy": "CHAT_PREDICTION", "side": "LONG",
                 "entry_price": price, "exit_price": price, "quantity": qty,
                 "pnl": -(entry_fee + exit_fee), "pnl_pct": 0.0, "entry_time": 100.0,
                 "exit_time": 200.0, "commission": entry_fee + exit_fee, "reason": reason,
                 "trade_id": "t-flat"}
        asyncio.run(database.commit_close_position(
            "MAINTRY", "MAIN", 0.0, trade, {"symbol": "MAINTRY", "action": "CLOSE_LONG"}))
        self.assertAlmostEqual(-(entry_fee + exit_fee), self.db.cash() - INITIAL, places=9)
        stored = self.db.conn.execute(
            "SELECT entry_commission_pct, exit_commission_pct FROM trades WHERE trade_id='t-flat'").fetchone()
        self.assertEqual((self.TAKER, self.MAKER), tuple(stored))

    def test_combined_paper_flat_round_trip(self):
        self.db.set_cash(5000.0, table="combined_paper_wallet")
        notional, price = 1000.0, 10.0
        row, status = asyncio.run(database.open_combined_paper_trade(
            {"symbol": "CMBTRY", "entry_price": price, "quantity": notional / price,
             "order_value_try": notional, "entry_time": 100.0}))
        self.assertEqual("opened", status)
        with patch.object(paper_ledger, "slippage_pct", lambda: 0.0):
            asyncio.run(database.close_combined_paper_trade(row["id"], price, 200.0, "stop_loss"))
        self.assertAlmostEqual(-2 * notional * self.TAKER,
                               self.db.cash("combined_paper_wallet") - 5000.0, places=9)


class MixedHistoryReconcileTests(_LedgerCase):
    """Eski + yeni satırlı defterde mutabakat no-op olmalı."""

    def _legacy_closed_auto(self, symbol, price, notional, exit_price, entry_time, exit_time,
                            pnl_rate, exit_pct=None):
        """Eski satır: cüzdan ham oranla (veya saklı çıkış oranıyla) oynatılır, PnL `pnl_rate` ile.

        ``exit_pct`` verilirse çıkış bacağı bu değişiklikten SONRA kapanmış demektir
        (oran saklı); giriş bacağı her durumda eski (NULL, ham oran).
        """
        qty = notional / price
        exit_rate = RAW if exit_pct is None else exit_pct
        commission = notional * pnl_rate + exit_price * qty * (pnl_rate if exit_pct is None else exit_pct)
        pnl = (exit_price - price) * qty - commission
        self.db.conn.execute(
            "INSERT INTO auto_paper_trades(symbol,status,entry_price,quantity,order_value_try,entry_time,"
            "exit_price,exit_time,pnl,pnl_pct,commission,exit_reason,created_at,updated_at,"
            "entry_commission_pct,exit_commission_pct) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)",
            (symbol, "closed", price, qty, notional, entry_time, exit_price, exit_time, pnl, 0.0,
             commission, "max_duration", entry_time, exit_time, exit_pct))
        wallet_delta = exit_price * qty * (1 - exit_rate) - notional * (1 + RAW)
        self.db.set_cash(self.db.cash() + wallet_delta)
        return pnl

    def _build_mixed_ledger(self):
        # 1) 2026-10-16 öncesi: PnL de cüzdan da ham oran.
        self._legacy_closed_auto("OLDATRY", 10.0, 800.0, 10.4, 10.0, 20.0, pnl_rate=RAW)
        # 2) 10-16..10-17 arası: PnL efektif, cüzdan ham (sürüklenmenin kaynağı).
        self._legacy_closed_auto("OLDBTRY", 5.0, 600.0, 4.9, 30.0, 40.0, pnl_rate=self.TAKER)
        # 3) Eski açılış (ham debit), yeni kapanış (çıkış oranı saklı, PnL girişi efektif).
        self._legacy_closed_auto("OLDCTRY", 2.0, 500.0, 2.1, 50.0, 60.0, pnl_rate=self.TAKER,
                                 exit_pct=self.MAKER)
        # 4) Eski AÇIK otonom pozisyon: ham oranla debit, oran NULL.
        self.db.conn.execute(
            "INSERT INTO auto_paper_trades(symbol,status,entry_price,quantity,order_value_try,entry_time,"
            "created_at,updated_at) VALUES('OLDOTRY','open',4.0,100.0,400.0,70.0,70.0,70.0)")
        self.db.set_cash(self.db.cash() - 400.0 * (1 + RAW))
        # 5) Eski AÇIK ana defter pozisyonu: ham oranla debit, oran NULL.
        self.db.conn.execute(
            "INSERT INTO positions(symbol,side,entry_price,quantity,entry_time,strategy,trade_id)"
            " VALUES('OLDPTRY','LONG',3.0,100.0,75.0,'CHAT_PREDICTION','legacy-p')")
        self.db.set_cash(self.db.cash() - 300.0 * (1 + RAW))
        # 6) Yeni satırlar — gerçek fonksiyonlarla.
        a = self.open_auto("NEWATRY", 10.0, 700.0, 80.0)
        self.close_auto(a, 10.2, "take_profit", 90.0)
        b = self.open_auto("NEWBTRY", 8.0, 400.0, 95.0)
        self.close_auto(b, 7.8, "stop_loss", 99.0)
        self.open_auto("NEWOTRY", 6.0, 600.0, 110.0)  # yeni AÇIK

    def test_reconcile_is_a_noop_on_mixed_rows(self):
        self._build_mixed_ledger()
        before = self.db.cash()
        result = asyncio.run(database.reconcile_portfolio())
        self.assertEqual([], result["removed_overallocated_positions"])
        self.assertAlmostEqual(before, result["after_try"], places=6,
                               msg=f"mutabakat cüzdanı değiştirmemeli (fark {result['difference']})")
        self.assertAlmostEqual(before, self.db.cash(), places=6)

    def test_preview_matches_and_is_a_noop(self):
        self._build_mixed_ledger()
        before = self.db.cash()
        preview = asyncio.run(database.preview_portfolio_reconcile())
        self.assertFalse(preview["requires_confirmation"])
        self.assertAlmostEqual(before, preview["projected_try"], places=6)

    def test_old_formula_would_have_repaired_wrongly(self):
        """Kanıt değeri: eski formül (SUM(pnl), açık bacak × ham oran) bu defterde sapar."""
        self._build_mixed_ledger()
        figures = database._portfolio_reconcile_figures(self.db, 0.0)
        naive = INITIAL + figures.realized - figures.open_cost * (1 + RAW)
        self.assertGreater(abs(naive - self.db.cash()), 0.01,
                           "eski formül karışık defterde nakdi yanlış yazardı")
        self.assertAlmostEqual(self.db.cash(), figures.cash(), places=6)

    def test_new_only_ledger_wallet_equals_realized_pnl(self):
        """Yalnız yeni satırlarda eski-bacak düzeltmesi 0; nakit = INITIAL + SUM(pnl) − açık yük."""
        a = self.open_auto("NEWATRY", 10.0, 700.0, 80.0)
        self.close_auto(a, 10.2, "take_profit", 90.0)
        self.open_auto("NEWOTRY", 6.0, 600.0, 110.0)
        figures = database._portfolio_reconcile_figures(self.db, 0.0)
        self.assertAlmostEqual(0.0, figures.wallet_adjustment, places=12)
        self.assertAlmostEqual(600.0 * self.TAKER, figures.open_commission, places=9)
        self.assertAlmostEqual(self.db.cash(), figures.cash(), places=9)


class OverallocationModelTests(_LedgerCase):
    def test_position_at_exact_budget_is_not_a_candidate(self):
        """Nakdin tamamını efektif oranla kullanan ana defter açılışı, aday taramasında
        ham oranla oynatılıp yanlışlıkla "yetersiz nakit" sayılmamalı (saklı oran)."""
        price = 10.0
        qty = INITIAL / (1 + self.TAKER) / price
        pos = {"side": "LONG", "entry_price": price, "quantity": qty, "entry_time": 100.0,
               "strategy": "CHAT_PREDICTION", "trade_id": "t-all", "entry_context": {}}
        sig = {"symbol": "ALLINTRY", "action": "BUY_SIGNAL", "price": price, "timestamp": 100.0}
        asyncio.run(database.commit_open_position("ALLINTRY", "ALLIN", 0.0, qty, pos, sig))
        self.assertAlmostEqual(0.0, self.db.cash(), places=6)
        self.assertEqual([], database._chronological_overallocation_candidates(self.db))
        result = asyncio.run(database.reconcile_portfolio())
        self.assertEqual([], result["removed_overallocated_positions"])
        self.assertAlmostEqual(0.0, result["after_try"], places=6)


if __name__ == "__main__":
    unittest.main()
