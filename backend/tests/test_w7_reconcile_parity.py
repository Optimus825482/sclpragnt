"""V-01 / V-13 — cüzdan mutabakat PARİTESİ (preview ↔ apply ↔ açılış).

Kök hata (V-01, KRİTİK)
------------------------
`virtual_wallet` TRY satırı İKİ defter tarafından paylaşılır:
  * ana defter → `trades` (kapanmış) + `positions` (açık)
  * otonom     → `auto_paper_trades` (kapanmış PnL + açık `order_value_try`)

`reconcile_portfolio` (apply) iki bacağı da katıyordu; `preview_portfolio_reconcile`
ise `auto_paper_trades`'i **tamamen yok sayıyordu**. `POST /api/portfolio/reconcile`
iki adımlı onay akışı olduğu için (confirm=false → preview, confirm=true → apply)
operatör YANLIŞ "mutabakat sonrası bakiye"yi onaylıyordu.

Ölçülen sapma: açık 1 adet 2.000 TRY'lik auto-paper pozisyonunda preview
10.050,00 TRY ↔ apply 8.047,00 TRY → **+2.003,00 TRY**.

V-13: aynı bacak `init_db` açılış mutabakatında da eksikti.

Bu testler iki şeyi kilitler:
  1. Rakamlar TEK kaynaktan (`_portfolio_reconcile_figures`) üretilir.
  2. Preview ve apply'ın kendi ayrı SQL'i YOKTUR (V-01'in tam olarak tekrarı).
"""
import inspect
import unittest

from app import database
from app.config import config


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _ReconcileConn:
    """SQL'e göre cevap veren sahte bağlantı.

    Yalnızca mutabakat yolu için yeterli: SUM sorguları ayırt edici alt dizeyle
    eşlenir; liste/aday sorguları boş döner (aday yok → `requires_confirmation=False`).
    """

    def __init__(self, *, main_realized=0.0, auto_realized=0.0,
                 main_open=0.0, auto_open=0.0, cutoff=0.0):
        self.main_realized = main_realized
        self.auto_realized = auto_realized
        self.main_open = main_open
        self.auto_open = auto_open
        self.cutoff = cutoff
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split()).upper()
        self.statements.append(s)
        if "PORTFOLIO_RESET_AT" in s:
            return _Cursor([(self.cutoff,)] if self.cutoff else [])
        if "COALESCE(SUM(PNL),0) FROM AUTO_PAPER_TRADES" in s:
            return _Cursor([(self.auto_realized,)])
        if "COALESCE(SUM(ORDER_VALUE_TRY),0) FROM AUTO_PAPER_TRADES" in s:
            return _Cursor([(self.auto_open,)])
        if "COALESCE(SUM(PNL),0) FROM TRADES" in s:
            return _Cursor([(self.main_realized,)])
        if "COALESCE(SUM(ENTRY_PRICE*QUANTITY),0) FROM POSITIONS" in s:
            return _Cursor([(self.main_open,)])
        if s.startswith("SELECT COUNT("):
            return _Cursor([(0,)])
        # Aday taraması / liste sorguları → boş
        return _Cursor([])

    def commit(self):
        pass


class _PatchedRunDb:
    """`database._run_db`'yi sahte bağlantıya yönlendiren bağlam yöneticisi."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self._original = database._run_db

        async def fake_run_db(operation):
            return operation(self.conn)

        database._run_db = fake_run_db
        return self.conn

    def __exit__(self, *exc):
        database._run_db = self._original
        return False


class ReconcileFigureTests(unittest.TestCase):
    """`_portfolio_reconcile_figures` iki defteri de katmalı."""

    def test_sums_both_ledgers(self):
        conn = _ReconcileConn(main_realized=50.0, auto_realized=30.0,
                              main_open=2000.0, auto_open=1000.0)
        realized, main_open, auto_open = database._portfolio_reconcile_figures(conn, 0.0)
        self.assertEqual(80.0, realized, "realize PnL iki defterin toplamı olmalı")
        self.assertEqual(2000.0, main_open)
        self.assertEqual(1000.0, auto_open)

    def test_auto_paper_realized_is_included_when_main_is_empty(self):
        """V-01 regresyonu: yalnız otonom kapanış varsa preview 0 DEMEMELİ."""
        conn = _ReconcileConn(main_realized=0.0, auto_realized=30.0)
        realized, _main, _auto = database._portfolio_reconcile_figures(conn, 0.0)
        self.assertEqual(30.0, realized)

    def test_auto_paper_open_cost_is_included(self):
        conn = _ReconcileConn(main_open=0.0, auto_open=2000.0)
        _realized, main_open, auto_open = database._portfolio_reconcile_figures(conn, 0.0)
        self.assertEqual(0.0, main_open)
        self.assertEqual(2000.0, auto_open, "açık auto-paper maliyeti atlanmamalı")


class PreviewParityTests(unittest.IsolatedAsyncioTestCase):
    """Preview, apply ile AYNI rakamları göstermeli."""

    async def test_preview_reports_auto_paper_legs(self):
        conn = _ReconcileConn(main_realized=50.0, auto_realized=30.0,
                              main_open=2000.0, auto_open=1000.0)
        with _PatchedRunDb(conn):
            preview = await database.preview_portfolio_reconcile()

        # realized = 50 (ana) + 30 (otonom)
        self.assertEqual(80.0, preview["realized_pnl"])
        # aday yok → projeksiyon = mevcut açık maliyet (ana + otonom)
        self.assertEqual(3000.0, preview["open_entry_cost"])
        expected = (config.INITIAL_BALANCE_TRY + 80.0 - 3000.0
                    - 3000.0 * config.COMMISSION_PCT)
        self.assertAlmostEqual(expected, preview["projected_try"], places=6)
        self.assertFalse(preview["requires_confirmation"])

    async def test_preview_projected_try_matches_apply_formula(self):
        """Aynı girdide preview.projected_try == apply.after_try (aday yoksa)."""
        conn = _ReconcileConn(main_realized=-120.0, auto_realized=45.0,
                              main_open=1500.0, auto_open=700.0)
        with _PatchedRunDb(conn):
            preview = await database.preview_portfolio_reconcile()
        conn2 = _ReconcileConn(main_realized=-120.0, auto_realized=45.0,
                               main_open=1500.0, auto_open=700.0)
        with _PatchedRunDb(conn2):
            applied = await database.reconcile_portfolio()

        self.assertAlmostEqual(preview["projected_try"], applied["after_try"], places=6,
                               msg="preview ve apply aynı bakiyeyi göstermeli (V-01)")
        self.assertAlmostEqual(preview["realized_pnl"], applied["realized_pnl"], places=6)


class SingleSourceGuardTests(unittest.TestCase):
    """Yapısal kilit: V-01'in tam olarak tekrarını engeller."""

    def test_both_paths_delegate_to_the_shared_helper(self):
        for fn in (database.reconcile_portfolio, database.preview_portfolio_reconcile):
            src = inspect.getsource(fn)
            self.assertIn("_portfolio_reconcile_figures", src,
                          f"{fn.__name__} ortak yardımcıyı kullanmalı")

    def test_preview_has_no_divergent_inline_queries(self):
        """Preview kendi `trades`/`positions` SQL'ini kurmamalı (V-01'in kökü)."""
        src = inspect.getsource(database.preview_portfolio_reconcile)
        self.assertNotIn("FROM trades WHERE", src,
                         "preview kendi realize PnL sorgusunu kurmamalı")
        self.assertNotIn("FROM positions", src,
                         "preview kendi açık maliyet sorgusunu kurmamalı")

    def test_helper_is_the_only_place_with_these_queries(self):
        """Bu SQL'ler yalnızca ortak yardımcıda bulunmalı."""
        helper = inspect.getsource(database._portfolio_reconcile_figures)
        self.assertIn("FROM trades WHERE", helper)
        self.assertIn("FROM positions", helper)
        self.assertIn("auto_paper_trades", helper)


class InitDbReconcileTests(unittest.TestCase):
    """V-13: açılış mutabakatı da otonom bacağı katmalı."""

    def test_init_db_reconciles_both_ledgers(self):
        src = inspect.getsource(database.init_db)
        self.assertIn("FROM auto_paper_trades WHERE status='closed'", src,
                      "açılış mutabakatı otonom realize PnL'i katmalı")
        self.assertIn("SUM(order_value_try) FROM auto_paper_trades WHERE status='open'", src,
                      "açılış mutabakatı açık otonom maliyeti katmalı")

    def test_init_db_placeholder_count_matches_params(self):
        """`%s` sayısı params demetiyle uyuşmalı (6 = INITIAL + 2×cutoff(trades)
        + 2×cutoff(auto) + COMMISSION_PCT) — uyuşmazsa psycopg çalışma anında patlar."""
        src = inspect.getsource(database.init_db)
        marker = "UPDATE virtual_wallet SET amount="
        start = src.index(marker)
        end = src.index('"""', start)
        sql = src[start:end]
        self.assertEqual(6, sql.count("%s"),
                         f"placeholder sayısı 6 olmalı, bulunan: {sql.count('%s')}")


if __name__ == "__main__":
    unittest.main()
