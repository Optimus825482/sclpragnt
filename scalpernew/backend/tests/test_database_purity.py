"""``load_positions`` okuma saflığı (Madde 21 disentanglement) testleri.

2026-09-10: ``load_positions`` legacy pozisyonlara eksik ``trade_id`` alanını
yazıyordu (UPDATE + COMMIT). Yani salt-okunur sanılan bir çağrı veritabanını
değiştiriyordu. Yazma, ``backfill_position_trade_ids()`` açılış migration'ına
taşındı; okuma yolu artık hiçbir koşulda yazmaz.
"""
import unittest

from app import database


class _Row(dict):
    """Gerçek psycopg satırı hem isimle hem indeksle erişilebilir; taklidi."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = [_Row(r) if isinstance(r, dict) else r for r in rows]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """Sentetik bağlantı: hangi SQL'lerin koştuğunu kaydeder."""

    def __init__(self, select_rows):
        self.statements: list[str] = []
        self._select_rows = select_rows
        self.commits = 0

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.strip().upper().startswith("SELECT"):
            return _FakeCursor(self._select_rows)
        return _FakeCursor([])

    def commit(self):
        self.commits += 1
        self.statements.append("COMMIT")


def _is_write(sql: str) -> bool:
    upper = sql.strip().upper()
    return any(upper.startswith(kw) for kw in ("UPDATE", "INSERT", "DELETE", "CREATE", "ALTER", "DROP"))


class LoadPositionsPurityTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with(self, conn):
        async def fake_run_db(operation):
            return operation(conn)

        original = database._run_db
        database._run_db = fake_run_db
        try:
            return await database.load_positions()
        finally:
            database._run_db = original

    async def test_load_positions_never_writes(self):
        """Okuma yolu UPDATE/INSERT/DELETE/COMMIT yapmamalı."""
        conn = _RecordingConn([
            {"symbol": "BTCTRY", "entry_price": 100.0, "quantity": 2.0,
             "strategy": "CHAT_PREDICTION", "entry_context": "{}", "trade_id": None},
        ])
        positions = await self._run_with(conn)

        self.assertIn("BTCTRY", positions)
        # Eksik trade_id yalnızca BELLEK-İÇİ geçici kimlik olarak üretilir.
        self.assertTrue(positions["BTCTRY"].get("trade_id"))
        writes = [s for s in conn.statements if _is_write(s)]
        self.assertEqual([], writes, f"load_positions yazma yaptı: {writes}")
        self.assertEqual(0, conn.commits, "load_positions commit yapmamalı")

    async def test_load_positions_preserves_existing_trade_id(self):
        conn = _RecordingConn([
            {"symbol": "ETHTRY", "entry_price": 50.0, "quantity": 1.0,
             "strategy": "LLM_PAPER", "entry_context": "{}", "trade_id": "abc123"},
        ])
        positions = await self._run_with(conn)
        self.assertEqual("abc123", positions["ETHTRY"]["trade_id"])


class BackfillPositionTradeIdsTests(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_updates_only_missing_rows(self):
        """Backfill yalnızca eksik trade_id'li satırlar için UPDATE atmalı."""
        conn = _RecordingConn([{"symbol": "SOLTRY"}, {"symbol": "ADATRY"}])

        async def fake_run_db(operation):
            return operation(conn)

        original = database._run_db
        database._run_db = fake_run_db
        try:
            updated = await database.backfill_position_trade_ids()
        finally:
            database._run_db = original

        self.assertEqual(2, updated)
        updates = [s for s in conn.statements if s.strip().upper().startswith("UPDATE")]
        self.assertEqual(2, len(updates))
        self.assertEqual(1, conn.commits)
        # Sorgu yalnızca eksik olanları hedeflemeli.
        self.assertIn("trade_id IS NULL", conn.statements[0])

    async def test_backfill_is_noop_when_nothing_missing(self):
        conn = _RecordingConn([])

        async def fake_run_db(operation):
            return operation(conn)

        original = database._run_db
        database._run_db = fake_run_db
        try:
            updated = await database.backfill_position_trade_ids()
        finally:
            database._run_db = original

        self.assertEqual(0, updated)
        self.assertEqual(0, conn.commits, "Hiç eksik yokken commit yapılmamalı")


if __name__ == "__main__":
    unittest.main()
