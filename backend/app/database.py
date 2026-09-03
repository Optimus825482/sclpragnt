import asyncio
import json
import math
import os
import threading
import time
import tempfile
import re
from datetime import datetime, timezone

import psycopg

from app.config import config

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_LOCK = threading.Lock()
_PG_CONN = None
# Transport-level errors that mean the cached connection itself is dead
# (server restart, idle timeout, socket drop). On these the connection is
# closed and rebuilt on the next operation instead of poisoning every call.
_PG_FATAL_ERRORS: tuple[type[BaseException], ...]
try:
    import psycopg as _psycopg_transport
    _PG_FATAL_ERRORS = (_psycopg_transport.OperationalError, _psycopg_transport.InterfaceError)
except Exception:  # pragma: no cover - psycopg absent in minimal-env
    _PG_FATAL_ERRORS = ()

DEFAULT_SCALPER_SKILL_NAME = "Scalper Trade Manager"
DEFAULT_SCALPER_SKILL_INSTRUCTIONS = (
    "Paper-only scalper trade manager. Build a symbol-specific setup from 5m, 15m and 1h data; "
    "require trend/regime alignment, liquidity, order-flow and cost-aware net edge before entry. "
    "Do not chase overbought resistance or reopen after a close without cooldown, fresh setup and required "
    "price rearm. Treat BUY_BLOCKED as no trade, and learn only from validated multi-trade out-of-sample "
    "evidence; never invent data or place real orders."
)

def _json_value(value, fallback):
    if value in (None, ""): return fallback
    if isinstance(value, (dict, list)): return value
    try: return json.loads(value)
    except (TypeError, json.JSONDecodeError): return fallback


def _json_safe(value):
    """Replace JSON-invalid floating values before PostgreSQL JSON storage."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value

def _json_safe_dumps(value, **kwargs):
    """Serialize payloads so NaN/Inf never reach PostgreSQL JSONB columns;
    NaN/Inf reject the whole INSERT."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", str)
    return json.dumps(_json_safe(value), **kwargs)

class _PostgresCompat:
    def __init__(self, conn): self.conn = conn
    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        sql = re.sub(r"\b([mp])\.enabled\s*=\s*1\b", r"\1.enabled=TRUE", sql, flags=re.I)
        sql = re.sub(r"\benabled\s*=\s*1\b", "enabled=TRUE", sql, flags=re.I)
        was_ignore = bool(re.search(r"INSERT OR IGNORE INTO", sql, flags=re.I))
        sql = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", sql, flags=re.I)
        if was_ignore and "ON CONFLICT" not in sql.upper(): sql += " ON CONFLICT DO NOTHING"
        sql = re.sub(r"INSERT OR REPLACE INTO positions", "INSERT INTO positions", sql, flags=re.I)
        sql = re.sub(r"INSERT OR REPLACE INTO llm_skills", "INSERT INTO llm_skills", sql, flags=re.I)
        sql = re.sub(r"INSERT OR REPLACE INTO a2a_messages", "INSERT INTO a2a_messages", sql, flags=re.I)
        if "INSERT INTO A2A_MESSAGES" in sql.upper() and "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT(message_id) DO UPDATE SET correlation_id=EXCLUDED.correlation_id,direction=EXCLUDED.direction,message_type=EXCLUDED.message_type,sender=EXCLUDED.sender,recipient=EXCLUDED.recipient,status=EXCLUDED.status,payload=EXCLUDED.payload,created_at=EXCLUDED.created_at,delivered_at=EXCLUDED.delivered_at,acknowledged_at=EXCLUDED.acknowledged_at,last_error=EXCLUDED.last_error,attempts=EXCLUDED.attempts"
        if "INSERT INTO llm_skills" in sql.upper() and "ON CONFLICT" not in sql.upper(): sql += " ON CONFLICT(name) DO UPDATE SET instructions=EXCLUDED.instructions,enabled=EXCLUDED.enabled,created_at=EXCLUDED.created_at"
        if "INSERT INTO positions" in sql.upper() and "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT(symbol) DO UPDATE SET side=EXCLUDED.side,entry_price=EXCLUDED.entry_price,stop_price=EXCLUDED.stop_price,take_profit=EXCLUDED.take_profit,peak_price=EXCLUDED.peak_price,breakeven_hit=EXCLUDED.breakeven_hit,quantity=EXCLUDED.quantity,entry_time=EXCLUDED.entry_time,strategy=EXCLUDED.strategy,entry_context=EXCLUDED.entry_context,trade_id=EXCLUDED.trade_id"
        cur = self.conn.cursor(); cur.execute(sql, params); return cur
    def executemany(self, sql, params):
        sql = sql.replace("?", "%s")
        was_ignore = bool(re.search(r"INSERT OR IGNORE INTO", sql, flags=re.I))
        sql = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", sql, flags=re.I)
        if was_ignore and "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT DO NOTHING"
        was_replace = bool(re.search(r"INSERT OR REPLACE INTO", sql, flags=re.I))
        sql = re.sub(r"INSERT OR REPLACE INTO", "INSERT INTO", sql, flags=re.I)
        if was_replace and "ON CONFLICT" not in sql.upper():
            m = re.match(r"INSERT INTO\s+(\w+)\s*\(([^)]+)\)", sql, flags=re.I)
            if m:
                col_text = m.group(2).strip()
                cols = [c.strip().split()[0] for c in col_text.split(",")]
                set_clause = ",".join(f"{c}=EXCLUDED.{c}" for c in cols)
                sql += f" ON CONFLICT DO UPDATE SET {set_clause}"
        cur = self.conn.cursor(); cur.executemany(sql, params); return cur
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()

class _HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int): return list(self.values())[key]
        return super().__getitem__(key)

def _hybrid_row_factory(cursor):
    if cursor.description is None:
        return lambda values: values
    names = [col.name for col in cursor.description]
    return lambda values: _HybridRow(zip(names, values))

def _postgres_enabled(): return True

def _db_timestamp():
    return datetime.now(timezone.utc)

def _epoch_value(value):
    if isinstance(value, datetime):
        return value.timestamp()
    return value

def _db_datetime_value(value):
    """Convert Unix expiry values to PostgreSQL timestamps when needed."""
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return value


def _get_connection():
    global _PG_CONN
    if _PG_CONN is None:
        try:
            _PG_CONN = _PostgresCompat(psycopg.connect(os.environ["DATABASE_URL"], row_factory=_hybrid_row_factory))
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL bağlantısı kurulamadı: {exc}") from exc
    return _PG_CONN


async def _run_db(operation):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _execute(operation))


def _execute(operation):
    with _DB_LOCK:
        conn = _get_connection()
        try:
            return operation(conn)
        except _PG_FATAL_ERRORS as exc:
            # The cached connection is unusable; drop it so the next
            # operation reconnects instead of failing forever.
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            global _PG_CONN
            _PG_CONN = None
            raise RuntimeError(f"PostgreSQL bağlantısı koptu, yeniden kurulacak: {exc}") from exc
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


async def init_db():
    """Initialize the PostgreSQL schema (single backend)."""
    def pg_op(conn):
        schema_path = os.path.abspath(os.path.join(_APP_DIR, "..", "migrations", "001_pgvector_schema.sql"))
        with open(schema_path, encoding="utf-8") as schema_file:
            conn.conn.execute(schema_file.read())
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_skills_name ON llm_skills(name)")
        conn.execute("INSERT INTO llm_skills(name,instructions,enabled,created_at) VALUES(%s,%s,TRUE,%s) "
                     "ON CONFLICT(name) DO NOTHING",
                     (DEFAULT_SCALPER_SKILL_NAME, DEFAULT_SCALPER_SKILL_INSTRUCTIONS, time.time()))
        # Reconcile migrated cash with trades and open positions.
        conn.execute("""UPDATE virtual_wallet SET amount=
            (SELECT COALESCE(
                (SELECT amount FROM virtual_wallet WHERE asset='TRY' AND amount IS NOT NULL AND amount > 0),
                %s + COALESCE((SELECT SUM(pnl) FROM trades), 0)
                - COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0)
                - COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0) * %s
            ) AS reconciled)
        WHERE asset='TRY' AND NOT EXISTS (SELECT 1 FROM virtual_wallet WHERE asset='TRY' AND amount IS NOT NULL AND amount > 0)""", (config.INITIAL_BALANCE_TRY, config.COMMISSION_PCT))
        conn.conn.commit()
    await _run_db(pg_op)

async def ensure_default_scalper_skill():
    """Keep the built-in trade manager visible in the active database skill registry."""
    def op(conn):
        if _postgres_enabled():
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_skills_name ON llm_skills(name)")
            enabled_literal = "TRUE"
        else:
            enabled_literal = "1"
        conn.execute(
            f"INSERT INTO llm_skills(name,instructions,enabled,created_at) VALUES(?,?,{enabled_literal},?) "
            "ON CONFLICT(name) DO NOTHING",
            (DEFAULT_SCALPER_SKILL_NAME, DEFAULT_SCALPER_SKILL_INSTRUCTIONS, time.time()),
        )
        conn.commit()
    return await _run_db(op)

def _backfill_position_strategy(conn):
    """strategy NULL olan açık pozisyonlara UT ata (eski kayıtlar)."""
    conn.execute("UPDATE positions SET strategy='UT' WHERE strategy IS NULL")

def _recalculate_wallet(conn):
    """TRY bakiyesini trades + açık pozisyonlardan yeniden hesapla (komisyon dahil)."""
    start = config.INITIAL_BALANCE_TRY
    spent = conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM trades").fetchone()[0]
    comm = conn.execute("SELECT COALESCE(SUM(commission),0) FROM trades").fetchone()[0]
    received = conn.execute("SELECT COALESCE(SUM(exit_price*quantity),0) FROM trades").fetchone()[0]
    open_cost = conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0]
    open_entry_commission = open_cost * config.COMMISSION_PCT
    try_balance = start - spent - comm + received - open_cost - open_entry_commission
    conn.execute("UPDATE virtual_wallet SET amount=? WHERE asset='TRY'", (try_balance,))

def _backfill_commission(conn):
    """commission NULL olan eski kayıtlara geriye dönük komisyon hesapla."""
    rows = conn.execute(
        "SELECT * FROM trades WHERE commission IS NULL"
    ).fetchall()
    for t in rows:
        buy_notional = t["entry_price"] * t["quantity"]
        sell_notional = t["exit_price"] * t["quantity"]
        commission = (buy_notional + sell_notional) * config.COMMISSION_PCT
        pnl = t["pnl"] - commission
        pnl_pct = (pnl / buy_notional) * 100 if buy_notional else 0.0
        conn.execute(
            "UPDATE trades SET commission=?, pnl=?, pnl_pct=? WHERE id=?",
            (commission, pnl, pnl_pct, t["id"])
        )

def _migrate_old_trades(conn):
    """trades tablosu oluşmadan önce kapanan işlemleri signals'tan geriye dönük aktar."""
    if conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] > 0:
        return  # zaten aktarılmış
    closes = conn.execute(
        "SELECT * FROM signals WHERE action LIKE 'CLOSE%' ORDER BY timestamp ASC"
    ).fetchall()
    for c in closes:
        sym = c["symbol"]
        # aynı sembolün en son BUY/SELL sinyalini giriş olarak bul
        entry = conn.execute(
            "SELECT * FROM signals WHERE symbol=? AND action IN ('BUY_SIGNAL','SELL_SIGNAL') AND timestamp < ? ORDER BY timestamp DESC LIMIT 1",
            (sym, c["timestamp"])
        ).fetchone()
        if not entry:
            continue
        side = "LONG" if entry["action"] == "BUY_SIGNAL" else "SHORT"
        qty = config.DEFAULT_ORDER_USDT / entry["price"] if entry["price"] else 0.0
        pnl = (c["price"] - entry["price"]) * qty
        pnl_pct = ((c["price"] - entry["price"]) / entry["price"]) * 100 if entry["price"] else 0.0
        conn.execute(
            "INSERT INTO trades (symbol, strategy, side, entry_price, exit_price, quantity, pnl, pnl_pct, entry_time, exit_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sym, "UT", side, entry["price"], c["price"], qty, pnl, pnl_pct, entry["timestamp"], c["timestamp"])
        )


async def reset_trading_data():
    """Eski paper-trading/strateji geçmişini temizle ve cüzdanı sıfırla.

    Strateji, sembol ve LLM ayarları korunur. Tarihsel piyasa cache'i de
    silinmez; böylece yeni strateji hemen aynı veriyle çalışabilir.
    """
    # Sabit tablo allowlist — SQL enjeksiyonunu önler
    _RESET_ALLOWED_TABLES = frozenset({
        "alert_events", "alert_rules", "paper_orders", "a2a_messages",
        "llm_tool_logs", "llm_symbol_guards", "decision_logs", "signals",
        "trades", "positions", "backtests", "analysis_snapshots",
        "microstructure_snapshots",
    })
    def op(conn):
        # Bağımlı kayıtları önce temizle (özellikle alert/paper order tabloları).
        tables = (
            "alert_events",
            "alert_rules",
            "paper_orders",
            "a2a_messages",
            "llm_tool_logs",
            "llm_symbol_guards",
            "decision_logs",
            "signals",
            "trades",
            "positions",
            "backtests",
            "analysis_snapshots", "microstructure_snapshots",
        )
        deleted = {}
        for table in tables:
            if table not in _RESET_ALLOWED_TABLES:
                continue  # Güvenlik: izin verilmeyen tablo atla
            cursor = conn.execute(f"DELETE FROM {table}")
            deleted[table] = cursor.rowcount
        conn.execute("DELETE FROM virtual_wallet")
        conn.execute("INSERT INTO virtual_wallet (asset, amount) VALUES ('TRY', ?)", (config.INITIAL_BALANCE_TRY,))
        conn.commit()
        deleted["virtual_wallet"] = 1
        return deleted

    return await _run_db(op)

async def get_wallet_balance(asset="USDT"):
    def op(conn):
        row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?", (asset,)).fetchone()
        return row[0] if row else 0.0

    return await _run_db(op)


async def update_wallet_balance(asset, amount):
    def op(conn):
        conn.execute(
            "INSERT INTO virtual_wallet (asset, amount) VALUES (?, ?) ON CONFLICT(asset) DO UPDATE SET amount=?",
            (asset, amount, amount)
        )
        conn.commit()

    await _run_db(op)

def _chronological_overallocation_candidates(conn):
    """Return only positions whose opening event made the ledger insolvent."""
    cash = float(config.INITIAL_BALANCE_TRY)
    events = []
    trades = conn.execute("SELECT entry_time,exit_time,entry_price,quantity,pnl FROM trades").fetchall()
    for row in trades:
        cost = float(row[2] or 0) * float(row[3] or 0)
        events.append((float(row[0] or 0), 0, "debit", None, cost * (1 + config.COMMISSION_PCT)))
        events.append((float(row[1] or 0), 1, "credit", None, cost + float(row[4] or 0)))
    positions = conn.execute("SELECT symbol,entry_time,entry_price,quantity FROM positions").fetchall()
    for row in positions:
        cost = float(row[2] or 0) * float(row[3] or 0)
        events.append((float(row[1] or 0), 0, "open", row, cost * (1 + config.COMMISSION_PCT)))
    candidates = []
    for _, _, kind, row, amount in sorted(events, key=lambda item: (item[0], item[1])):
        if kind == "credit":
            cash += amount
        else:
            cash -= amount
            if kind == "open" and cash < -0.01:
                candidates.append({"symbol": row[0], "entry_time": row[1], "entry_price": row[2], "quantity": row[3], "cost": float(row[2] or 0) * float(row[3] or 0), "reason": "entry_cash_was_insufficient"})
    return candidates

async def reconcile_portfolio():
    """Rebuild TRY cash and remove only over-allocated newest open positions."""
    def op(conn):
        before_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?", ("TRY",)).fetchone()
        before = float(before_row[0]) if before_row else 0.0
        realized = float(conn.execute("SELECT COALESCE(SUM(pnl),0) FROM trades").fetchone()[0] or 0)
        open_cost = float(conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0] or 0)
        entry_commission = open_cost * config.COMMISSION_PCT
        after = config.INITIAL_BALANCE_TRY + realized - open_cost - entry_commission
        removed = []
        candidates = _chronological_overallocation_candidates(conn)
        if candidates:
            for candidate in candidates:
                symbol, entry_time, entry_price, quantity = candidate["symbol"], candidate["entry_time"], candidate["entry_price"], candidate["quantity"]
                position_cost = float(entry_price or 0) * float(quantity or 0)
                trade_id_row = conn.execute("SELECT trade_id FROM positions WHERE symbol=?", (symbol,)).fetchone()
                trade_id = trade_id_row[0] if trade_id_row else None
                conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                # Remove only the opening signal/log tied to this position.
                if trade_id:
                    conn.execute("DELETE FROM signals WHERE trade_id=? AND action='BUY_SIGNAL'", (trade_id,))
                else:
                    conn.execute("DELETE FROM signals WHERE symbol=? AND action='BUY_SIGNAL' AND ABS(timestamp-?) <= 10", (symbol, entry_time))
                conn.execute("DELETE FROM decision_logs WHERE symbol=? AND decision='BUY_SIGNAL' AND ABS(timestamp-?) <= 10", (symbol, entry_time))
                removed.append({"symbol": symbol, "entry_time": entry_time, "cost": position_cost})
                open_cost -= position_cost
                entry_commission = open_cost * config.COMMISSION_PCT
                after = config.INITIAL_BALANCE_TRY + realized - open_cost - entry_commission
            # A valid partial position opened from remaining cash must never be
            # removed merely because later mark-to-market PnL changed.
            if removed:
                open_cost = float(conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0] or 0)
                entry_commission = open_cost * config.COMMISSION_PCT
                after = config.INITIAL_BALANCE_TRY + realized - open_cost - entry_commission
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", after))
        conn.commit()
        trade_count = int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
        position_count = int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0])
        return {"before_try": before, "after_try": after, "realized_pnl": realized,
                "open_entry_cost": open_cost, "open_entry_commission": entry_commission,
                "trade_count": trade_count, "open_position_count": position_count,
                "difference": after - before, "removed_overallocated_positions": removed}
    return await _run_db(op)

async def preview_portfolio_reconcile():
    def op(conn):
        realized = float(conn.execute("SELECT COALESCE(SUM(pnl),0) FROM trades").fetchone()[0] or 0)
        open_cost = float(conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0] or 0)
        after = config.INITIAL_BALANCE_TRY + realized - open_cost - open_cost * config.COMMISSION_PCT
        candidates = _chronological_overallocation_candidates(conn)
        projected_open_cost = open_cost - sum(float(item["cost"] or 0) for item in candidates)
        projected_try = config.INITIAL_BALANCE_TRY + realized - projected_open_cost - projected_open_cost * config.COMMISSION_PCT
        return {"would_remove": candidates, "projected_try": projected_try, "realized_pnl": realized,
                "open_entry_cost": projected_open_cost,
                "requires_confirmation": bool(candidates)}
    return await _run_db(op)

async def preview_trade_repair():
    """Read-only audit for legacy trade/position linkage and report integrity."""
    def op(conn):
        missing_trade_ids = [dict(r) for r in conn.execute("SELECT id,symbol,entry_time FROM trades WHERE trade_id IS NULL OR trade_id='' ORDER BY id").fetchall()]
        missing_position_ids = [dict(r) for r in conn.execute("SELECT symbol,entry_time FROM positions WHERE trade_id IS NULL OR trade_id='' ORDER BY entry_time").fetchall()]
        trades = conn.execute("SELECT id,symbol,strategy,entry_time,exit_time,trade_id FROM trades ORDER BY exit_time").fetchall()
        close_logs = conn.execute("SELECT id,symbol,timestamp,strategy FROM decision_logs WHERE decision='CLOSE_LONG' ORDER BY timestamp").fetchall()
        unmatched_closes = []
        for log in close_logs:
            matches = [t for t in trades if t[1] == log[1] and t[4] is not None and abs(float(t[4]) - float(log[2] or 0)) <= 30]
            if not matches:
                unmatched_closes.append({"id": log[0], "symbol": log[1], "timestamp": log[2], "reason": "matching_trade_not_found"})
        return {"status":"preview", "missing_trade_ids":missing_trade_ids, "missing_position_ids":missing_position_ids,
                "unmatched_close_logs":unmatched_closes, "actions": {
                    "assign_trade_ids": len(missing_trade_ids) + len(missing_position_ids),
                    "enrich_close_log_strategy": sum(1 for log in close_logs if not log[3]),
                    "delete_records": 0,
                }, "requires_confirmation": bool(missing_trade_ids or missing_position_ids or any(not log[3] for log in close_logs))}
    return await _run_db(op)

async def apply_trade_repair():
    """Apply only deterministic linkage repairs; never deletes historical rows."""
    def op(conn):
        updated_trades = updated_positions = enriched_logs = 0
        trade_rows = conn.execute("SELECT id,symbol,entry_time,trade_id FROM trades ORDER BY id").fetchall()
        for row in trade_rows:
            if not row[3]:
                conn.execute("UPDATE trades SET trade_id=? WHERE id=?", (f"legacy-trade-{row[0]}", row[0]))
                updated_trades += 1
        position_rows = conn.execute("SELECT symbol,entry_time,trade_id FROM positions ORDER BY entry_time").fetchall()
        for row in position_rows:
            if not row[2]:
                conn.execute("UPDATE positions SET trade_id=? WHERE symbol=?", (f"legacy-position-{row[0]}-{row[1]}", row[0]))
                updated_positions += 1
        trades = conn.execute("SELECT id,symbol,strategy,exit_time FROM trades WHERE strategy IS NOT NULL AND strategy<>''").fetchall()
        logs = conn.execute("SELECT id,symbol,timestamp FROM decision_logs WHERE decision='CLOSE_LONG' AND (strategy IS NULL OR strategy='')").fetchall()
        for log in logs:
            matches = [t for t in trades if t[1] == log[1] and t[3] is not None and abs(float(t[3]) - float(log[2] or 0)) <= 30]
            if len(matches) == 1:
                conn.execute("UPDATE decision_logs SET strategy=? WHERE id=?", (matches[0][2], log[0]))
                enriched_logs += 1
        conn.commit()
        return {"updated_trades":updated_trades, "updated_positions":updated_positions, "enriched_close_logs":enriched_logs, "deleted":0}
    return await _run_db(op)

async def preview_legacy_trade_cleanup():
    def op(conn):
        rows = conn.execute("SELECT id,symbol,strategy,pnl,commission,entry_time,exit_time,reason,trade_id FROM trades WHERE trade_id IN ('legacy-trade-573','legacy-trade-574') ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    return await _run_db(op)

async def purge_legacy_trade_records(trade_ids):
    allowed = {"legacy-trade-573", "legacy-trade-574"}
    ids = sorted(allowed.intersection(str(x) for x in (trade_ids or [])))
    if not ids:
        raise ValueError("Silinecek onaylı legacy işlem bulunamadı")
    def op(conn):
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT id,symbol,exit_time,trade_id FROM trades WHERE trade_id IN ({placeholders})", tuple(ids)).fetchall()
        if len(rows) != len(ids):
            raise ValueError("Onaylanan legacy kayıtların tamamı bulunamadı; işlem iptal edildi")
        deleted = []
        for row in rows:
            symbol, exit_time = row[1], row[2]
            conn.execute("DELETE FROM trades WHERE trade_id=?", (row[3],))
            conn.execute("DELETE FROM signals WHERE symbol=? AND action='CLOSE_LONG' AND ABS(timestamp-?) <= 30", (symbol, exit_time))
            conn.execute("DELETE FROM decision_logs WHERE symbol=? AND decision='CLOSE_LONG' AND ABS(timestamp-?) <= 30", (symbol, exit_time))
            try:
                conn.execute("DELETE FROM memory_embeddings WHERE memory_document_id IN (SELECT id FROM memory_documents WHERE source_id=? OR source_id=? )", (str(row[0]), str(row[3])))
                conn.execute("DELETE FROM memory_documents WHERE source_id=? OR source_id=?", (str(row[0]), str(row[3])))
            except Exception:
                pass
            deleted.append({"trade_id": row[3], "symbol": symbol, "id": row[0]})
        conn.commit()
        return {"deleted": deleted, "deleted_count": len(deleted)}
    return await _run_db(op)

async def get_llm_config():
    def op(conn):
        providers = [dict(r) for r in conn.execute("SELECT id,name,base_url,enabled,created_at,updated_at FROM llm_providers ORDER BY id").fetchall()]
        models = [dict(r) for r in conn.execute("SELECT id,provider_id,name,temperature,model_type,dimensions,embedding_metric,enabled,created_at FROM llm_models ORDER BY id").fetchall()]
        skills = [dict(r) for r in conn.execute("SELECT id,name,instructions,enabled,created_at FROM llm_skills ORDER BY id").fetchall()]
        active = conn.execute("SELECT value FROM llm_settings WHERE key='active_model_id'").fetchone()
        try:
            active_model_id = int(active[0]) if active else None
        except (ValueError, TypeError):
            active_model_id = None
        return {"providers": providers, "models": models, "skills": skills, "active_model_id": active_model_id}
    return await _run_db(op)

async def get_active_llm_config():
    def op(conn):
        setting = conn.execute("SELECT value FROM llm_settings WHERE key='llm_enabled'").fetchone()
        if not setting or setting[0] != "1": return None
        row = conn.execute("SELECT m.*, p.name provider_name,p.base_url,p.api_key_encrypted,p.enabled provider_enabled FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id JOIN llm_settings s ON s.key='active_model_id' AND s.value=CAST(m.id AS TEXT) WHERE m.enabled=1 AND p.enabled=1 AND m.model_type='chat'").fetchone()
        if not row: return None
        skills = [dict(r) for r in conn.execute("SELECT id,name,instructions,enabled FROM llm_skills WHERE enabled=1").fetchall()]
        return {"provider": dict(row), "model": dict(row), "skills": skills}
    return await _run_db(op)

async def get_embedding_llm_config(model_id=None):
    def op(conn):
        query = "SELECT m.*, p.name provider_name,p.base_url,p.api_key_encrypted,p.enabled provider_enabled FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id WHERE m.enabled=1 AND p.enabled=1 AND m.model_type='embedding'"
        args = []
        if model_id is not None: query += " AND m.id=?"; args.append(int(model_id))
        row = conn.execute(query + " ORDER BY m.id LIMIT 1", args).fetchone()
        return {"provider": dict(row), "model": dict(row)} if row else None
    return await _run_db(op)

async def save_llm_provider(name, base_url, encrypted_key):
    now = time.time()
    def op(conn):
        sql = "INSERT INTO llm_providers(name,base_url,api_key_encrypted,created_at,updated_at) VALUES(?,?,?,?,?)"
        params = (name,base_url,encrypted_key,now,now)
        if _postgres_enabled():
            row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params); conn.commit(); return cur.lastrowid
    return await _run_db(op)

async def save_llm_model(provider_id, name, temperature, model_type="chat", dimensions=None, embedding_metric="cosine"):
    def op(conn):
        sql = "INSERT INTO llm_models(provider_id,name,temperature,model_type,dimensions,embedding_metric,created_at) VALUES(?,?,?,?,?,?,?)"
        params = (provider_id,name,temperature,model_type,dimensions,embedding_metric,time.time())
        if _postgres_enabled():
            row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params); conn.commit(); return cur.lastrowid
    return await _run_db(op)

async def save_llm_skill(name, instructions):
    def op(conn):
        sql = "INSERT OR REPLACE INTO llm_skills(name,instructions,enabled,created_at) VALUES(?,?,1,?)"
        params = (name,instructions,time.time())
        if _postgres_enabled():
            conn.execute(sql, params); row = conn.execute("SELECT id FROM llm_skills WHERE name=?", (name,)).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params); conn.commit(); return cur.lastrowid
    return await _run_db(op)

async def update_llm_provider(provider_id, name, base_url, encrypted_key=None):
    def op(conn):
        if encrypted_key:
            conn.execute("UPDATE llm_providers SET name=?,base_url=?,api_key_encrypted=?,updated_at=? WHERE id=?", (name,base_url,encrypted_key,time.time(),provider_id))
        else:
            conn.execute("UPDATE llm_providers SET name=?,base_url=?,updated_at=? WHERE id=?", (name,base_url,time.time(),provider_id))
        conn.commit()
    await _run_db(op)

async def delete_llm_provider(provider_id):
    def op(conn):
        conn.execute("DELETE FROM llm_models WHERE provider_id=?", (provider_id,))
        conn.execute("DELETE FROM llm_providers WHERE id=?", (provider_id,)); conn.commit()
    await _run_db(op)

async def update_llm_model(model_id, name, temperature, model_type=None, dimensions=None, embedding_metric=None):
    def op(conn):
        if model_type is None:
            conn.execute("UPDATE llm_models SET name=?,temperature=? WHERE id=?", (name,temperature,model_id))
        else:
            conn.execute("UPDATE llm_models SET name=?,temperature=?,model_type=?,dimensions=?,embedding_metric=? WHERE id=?", (name,temperature,model_type,dimensions,embedding_metric or "cosine",model_id))
        conn.commit()
    await _run_db(op)

async def delete_llm_model(model_id):
    def op(conn):
        conn.execute("DELETE FROM llm_models WHERE id=?", (model_id,)); conn.commit()
    await _run_db(op)

async def update_llm_skill(skill_id, name, instructions):
    def op(conn):
        conn.execute("UPDATE llm_skills SET name=?,instructions=? WHERE id=?", (name,instructions,skill_id)); conn.commit()
    await _run_db(op)

async def delete_llm_skill(skill_id):
    def op(conn):
        conn.execute("DELETE FROM llm_skills WHERE id=?", (skill_id,)); conn.commit()
    await _run_db(op)

async def set_llm_setting(key, value):
    def op(conn):
        conn.execute("INSERT INTO llm_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,str(value))); conn.commit()
    await _run_db(op)


async def load_positions():
    def op(conn):
        positions = {}
        rows = conn.execute("SELECT * FROM positions").fetchall()
        for row in rows:
            values = dict(row)
            context = _json_value(values.get("entry_context"), {})
            runtime = context.get("_runtime") if isinstance(context.get("_runtime"), dict) else {}
            symbol = values.get("symbol")
            positions[symbol] = {
                "side": values.get("side"), "entry_price": values.get("entry_price"), "stop_price": values.get("stop_price"),
                "take_profit": values.get("take_profit"), "peak_price": values.get("peak_price"), "breakeven_hit": bool(values.get("breakeven_hit")),
                "quantity": values.get("quantity"), "entry_time": values.get("entry_time"),
                "strategy": values.get("strategy"),
                "entry_context": context,
                "trade_id": values.get("trade_id") or f"legacy-{symbol}-{values.get('entry_time')}",
                "max_price": runtime.get("max_price", values.get("peak_price")),
                "min_price": runtime.get("min_price", values.get("entry_price")),
                "layers": max(1, int(runtime.get("layers") or 1)),
            }
            if positions[symbol].get("strategy") == "LLM_PAPER":
                entry = float(values.get("entry_price") or 0)
                stop_pct = runtime.get("llm_stop_loss_pct", context.get("stop_loss_pct"))
                target_pct = runtime.get("llm_profit_target_pct", context.get("profit_target_pct"))
                max_hold = runtime.get("llm_max_hold_sec", context.get("max_hold_sec"))
                if stop_pct is not None:
                    positions[symbol]["llm_stop_price"] = entry * (1 - float(stop_pct))
                if target_pct is not None:
                    positions[symbol]["llm_take_profit_price"] = entry * (1 + float(target_pct))
                if max_hold is not None:
                    positions[symbol]["llm_max_hold_sec"] = int(max_hold)
        return positions

    return await _run_db(op)


def _position_entry_context(pos):
    context = dict(pos.get("entry_context") or {})
    runtime = dict(context.get("_runtime") or {})
    for key in ("max_price", "min_price", "layers"):
        if key in pos:
            runtime[key] = pos[key]
    entry = float(pos.get("entry_price") or 0)
    if pos.get("llm_stop_price") is not None and entry:
        runtime["llm_stop_loss_pct"] = max(0.0, 1 - float(pos["llm_stop_price"]) / entry)
    if pos.get("llm_take_profit_price") is not None and entry:
        runtime["llm_profit_target_pct"] = max(0.0, float(pos["llm_take_profit_price"]) / entry - 1)
    if pos.get("llm_max_hold_sec") is not None:
        runtime["llm_max_hold_sec"] = int(pos["llm_max_hold_sec"])
    context["_runtime"] = runtime
    return context

async def get_llm_setting(key, default=None):
    def op(conn):
        row = conn.execute("SELECT value FROM llm_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    return await _run_db(op)


async def save_position(symbol, pos):
    def op(conn):
        conn.execute(
            """INSERT INTO positions (symbol, side, entry_price, stop_price, take_profit, peak_price,
               breakeven_hit, quantity, entry_time, strategy, entry_context, trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET
               side=excluded.side, entry_price=excluded.entry_price,
               stop_price=excluded.stop_price, take_profit=excluded.take_profit,
               peak_price=excluded.peak_price, breakeven_hit=excluded.breakeven_hit,
               quantity=excluded.quantity, entry_time=excluded.entry_time,
               strategy=excluded.strategy, entry_context=excluded.entry_context,
               trade_id=excluded.trade_id""",
            (symbol, pos["side"], pos["entry_price"], pos.get("stop_price"),
             pos.get("take_profit"), pos.get("peak_price", pos["entry_price"]), bool(pos.get("breakeven_hit", False)), pos["quantity"],
             pos.get("entry_time"), pos.get("strategy"), _json_safe_dumps(_position_entry_context(pos)), pos.get("trade_id"))
        )
        conn.commit()

    await _run_db(op)

async def save_paper_order(order):
    now = float(order.get("updated_at") or time.time())
    def op(conn):
        conn.execute("""INSERT INTO paper_orders
            (order_id,symbol,side,order_type,status,order_value_try,price,limit_price,stop_price,
             take_profit_price,stop_loss_pct,take_profit_pct,max_hold_seconds,oco_group,reference_price,
             client_request_id,trace_id,payload,created_at,updated_at,filled_at,cancelled_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at,
              filled_at=excluded.filled_at,cancelled_at=excluded.cancelled_at""",
            (order.get("order_id"),order.get("symbol"),order.get("side"),order.get("order_type"),order.get("status","OPEN"),
             order.get("order_value_try"),order.get("price"),order.get("limit_price"),order.get("stop_price"),order.get("take_profit_price"),
             order.get("stop_loss_pct"),order.get("take_profit_pct"),order.get("max_hold_seconds"),order.get("oco_group"),order.get("reference_price"),
             order.get("client_request_id"),order.get("trace_id"),_json_safe_dumps(order, ensure_ascii=False, default=str),order.get("created_at",now),now,order.get("filled_at"),order.get("cancelled_at")))
        conn.commit()
    await _run_db(op)

async def load_paper_orders():
    def op(conn):
        rows = conn.execute("SELECT payload FROM paper_orders WHERE status IN ('OPEN','PENDING') ORDER BY created_at").fetchall()
        return [_json_value(row[0], {}) for row in rows]
    return await _run_db(op)


async def get_paper_order_by_client_request_id(client_request_id):
    def op(conn):
        row = conn.execute("SELECT payload FROM paper_orders WHERE client_request_id=?", (client_request_id,)).fetchone()
        return _json_value(row[0], {}) if row else None
    return await _run_db(op)

async def save_trade(trade):
    def op(conn):
        conn.execute(
            "INSERT INTO trades (symbol, strategy, side, entry_price, exit_price, quantity, pnl, pnl_pct, entry_time, exit_time, commission, reason, entry_context, max_favorable_pct, max_adverse_pct, hold_seconds, trade_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade.get("symbol"), trade.get("strategy"), trade.get("side"),
             trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"),
             trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"),
            trade.get("commission"), trade.get("reason"), _json_safe_dumps(trade.get("entry_context", {})),
            trade.get("max_favorable_pct"), trade.get("max_adverse_pct"), trade.get("hold_seconds"), trade.get("trade_id"))
        )
        conn.commit()

    await _run_db(op)

async def get_trades(limit: int | None = 100, offset: int = 0, symbol: str | None = None, strategy: str | None = None):
    def op(conn):
        clauses, values = [], []
        if symbol: clauses.append("symbol=?"); values.append(symbol.upper())
        if strategy: clauses.append("strategy=?"); values.append(strategy)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        if limit is None:
            rows = conn.execute(f"SELECT * FROM trades{where} ORDER BY exit_time DESC", values).fetchall()
        else:
            values.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
            rows = conn.execute(f"SELECT * FROM trades{where} ORDER BY exit_time DESC LIMIT ? OFFSET ?", values).fetchall()
        return [dict(r) for r in rows]

    return await _run_db(op)


async def get_trade_export_rows():
    """Return every closed paper trade with its full saved entry context."""
    def op(conn):
        rows = conn.execute("SELECT * FROM trades ORDER BY entry_time ASC, id ASC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["entry_context"] = _json_value(item.get("entry_context"), {})
            result.append(item)
        return result
    return await _run_db(op)


async def get_capital_lock_report(min_hold_hours: float = 4.0, max_favorable_pct: float = 0.75):
    """Read-only outcome report for positions that consumed capital without progress."""
    trades = await get_trades(limit=None, strategy="BB_MFI_MEAN_REVERSION")
    threshold_seconds = max(0.0, float(min_hold_hours)) * 3600
    threshold_favorable = max(0.0, float(max_favorable_pct)) / 100
    locks, snapshot_count = [], 0
    for trade in trades:
        context = _json_value(trade.get("entry_context"), {}) if isinstance(trade.get("entry_context"), str) else (trade.get("entry_context") or {})
        activity = context.get("symbol_activity") or {}
        if activity.get("m1_features"):
            snapshot_count += 1
        hold = float(trade.get("hold_seconds") or 0)
        mfe = float(trade.get("max_favorable_pct") or 0)
        if hold >= threshold_seconds and mfe < threshold_favorable:
            locks.append({
                "trade_id": trade.get("trade_id"), "symbol": trade.get("symbol"),
                "entry_time": trade.get("entry_time"), "exit_time": trade.get("exit_time"),
                "hold_seconds": hold, "pnl": float(trade.get("pnl") or 0),
                "max_favorable_pct": mfe * 100, "max_adverse_pct": float(trade.get("max_adverse_pct") or 0) * 100,
                "reason": trade.get("reason"), "activity_snapshot_present": bool(activity.get("m1_features")),
            })
    return {
        "paper_only": True, "label": {"min_hold_hours": min_hold_hours, "max_favorable_pct": max_favorable_pct},
        "trade_count": len(trades), "capital_lock_count": len(locks),
        "capital_lock_net_pnl_try": round(sum(row["pnl"] for row in locks), 6),
        "activity_snapshot_count": snapshot_count,
        "status": "collecting" if snapshot_count < 20 else "ready_for_research",
        # Kept separately from the short on-screen list so CSV export can
        # include the full labelled research population.
        "rows": locks,
        "recent": locks[:30],
    }


async def apply_historical_mtf_backfill(target_type, target_id, symbol, trade_id, entry_context, snapshots):
    """Persist public-history MTF evidence without changing trade economics."""
    context_json = _json_safe_dumps(entry_context or {}, ensure_ascii=False, default=str)
    def op(conn):
        if target_type == "trade":
            conn.execute("UPDATE trades SET entry_context=? WHERE id=?", (context_json, int(target_id)))
        elif target_type == "position":
            conn.execute("UPDATE positions SET entry_context=? WHERE symbol=?", (context_json, str(symbol).upper()))
        else:
            raise ValueError("geçersiz backfill hedefi")
        if trade_id:
            conn.execute("DELETE FROM analysis_snapshots WHERE trade_id=? AND source IN ('entry','historical_backfill')", (trade_id,))
        for timeframe, snapshot in (snapshots or {}).items():
            methods = snapshot.get("methodologies") or {}
            regime = methods.get("regime") or {}
            confluence = methods.get("confluence") or {}
            conn.execute("INSERT INTO analysis_snapshots(symbol,timeframe,captured_at,source,methodology_version,regime,regime_confidence,confluence_score,payload,trade_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(symbol).upper(), timeframe, float(snapshot.get("observation_timestamp") or time.time()), "historical_backfill", methods.get("methodology_version"), regime.get("name"), regime.get("confidence"), confluence.get("score"), _json_safe_dumps(snapshot, ensure_ascii=False, default=str), trade_id))
        conn.commit()
    await _run_db(op)


async def get_trade_count(symbol: str | None = None, strategy: str | None = None):
    def op(conn):
        clauses, values = [], []
        if symbol: clauses.append("symbol=?"); values.append(symbol.upper())
        if strategy: clauses.append("strategy=?"); values.append(strategy)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM trades{where}", values).fetchone()[0] or 0)
    return await _run_db(op)


async def get_portfolio_trade_metrics():
    """Return aggregate closed-trade metrics without loading the trade ledger."""
    def op(conn):
        row = conn.execute("""
            SELECT
                COUNT(*) AS closed_trades,
                COALESCE(SUM(pnl), 0) AS net_pnl,
                COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END), 0) AS winning_trades
            FROM trades
        """).fetchone()
        closed_trades = int(row["closed_trades"] or 0)
        winning_trades = int(row["winning_trades"] or 0)
        return {
            "closed_trades": closed_trades,
            "winning_trades": winning_trades,
            "net_pnl": float(row["net_pnl"] or 0.0),
            "win_rate": (winning_trades / closed_trades * 100) if closed_trades else 0.0,
        }
    return await _run_db(op)

async def upsert_microstructure_snapshots(rows):
    """Store sampled live bid/ask/depth evidence for future entry audits."""
    values = []
    for row in rows or []:
        values.append(tuple(row.get(key) for key in (
            "symbol", "captured_at", "bid_price", "ask_price", "bid_qty", "ask_qty",
            "spread_pct", "depth_try", "orderflow_imbalance", "source", "updated_at",
        )))
    if not values:
        return 0
    def op(conn):
        conn.executemany("""INSERT INTO microstructure_snapshots
            (symbol,captured_at,bid_price,ask_price,bid_qty,ask_qty,spread_pct,depth_try,orderflow_imbalance,source,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,captured_at) DO UPDATE SET
              bid_price=excluded.bid_price, ask_price=excluded.ask_price,
              bid_qty=excluded.bid_qty, ask_qty=excluded.ask_qty,
              spread_pct=excluded.spread_pct, depth_try=excluded.depth_try,
              orderflow_imbalance=excluded.orderflow_imbalance,
              source=excluded.source, updated_at=excluded.updated_at""", values)
        conn.commit()
        return len(values)
    return await _run_db(op)

async def get_realized_pnl():
    def op(conn):
        row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS pnl FROM trades").fetchone()
        return float(row["pnl"] or 0.0)

    return await _run_db(op)

async def create_backup_file():
    """Create a PostgreSQL custom-format dump file for download."""
    import subprocess
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL tanımlı değil")
    fd, path = tempfile.mkstemp(prefix="scalperagent-backup-", suffix=".dump")
    os.close(fd)
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", path, database_url],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump başarısız: {result.stderr[:500]}")
    return path


async def delete_position(symbol):
    def op(conn):
        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        conn.commit()

    await _run_db(op)


async def save_signal(sig):
    def op(conn):
        conn.execute(
            "INSERT INTO signals (timestamp, symbol, action, price, reason, strategy, trade_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig.get("timestamp"), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"), sig.get("strategy"), sig.get("trade_id"))
        )
        conn.execute(
            "INSERT INTO decision_logs (timestamp, symbol, strategy, decision, reason, price, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("strategy"),
             sig.get("action"), sig.get("reason"), sig.get("price"), _json_safe_dumps(sig, default=str))
        )
        conn.commit()
    await _run_db(op)
    try:
        from app.embedding_worker import worker, signal_document
        await worker.enqueue_persistent(signal_document(sig))
    except Exception:
        pass


async def save_decision_log(decision):
    def op(conn):
        conn.execute(
            "INSERT INTO decision_logs (timestamp,symbol,strategy,decision,reason,price,metadata) VALUES (?,?,?,?,?,?,?)",
            (decision.get("timestamp") or time.time(), decision.get("symbol"), decision.get("strategy"),
             decision.get("decision"), decision.get("reason"), decision.get("price"),
             json.dumps(_json_safe(decision.get("metadata") or {}), ensure_ascii=False, default=str, allow_nan=False)),
        )
        conn.commit()
    await _run_db(op)


async def backfill_replay_parity_observations(limit: int = 20_000, apply: bool = False, progress_callback=None):
    """Append partial parity records for legacy decisions without inventing data.

    Historical M1 activity, executable spread/depth, active universe and the
    portfolio state were not always persisted.  They are explicitly marked as
    unknown rather than reconstructed from today's market state.  The source
    decision ID makes an applied run idempotent.
    """
    def decode(value):
        try:
            return _json_value(value, {}) if value else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def op(conn):
        # Older databases may predate the column; this makes the maintenance
        # command safe before the next normal application startup migration.
        conn.execute("ALTER TABLE decision_logs ADD COLUMN IF NOT EXISTS source_decision_id INTEGER")
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_replay_parity_backfill_source ON decision_logs(strategy, source_decision_id) WHERE source_decision_id IS NOT NULL")
        except Exception:
            pass
        rows = conn.execute(
            """SELECT source.id, source.timestamp, source.symbol, source.strategy,
                      source.decision, source.reason, source.price, source.metadata
                FROM decision_logs AS source
                 LEFT JOIN decision_logs AS parity
                   ON parity.strategy='REPLAY_PARITY_BACKFILL'
                  AND parity.source_decision_id=source.id
                WHERE source.strategy NOT LIKE ?
                  AND parity.id IS NULL
                ORDER BY source.timestamp ASC, source.id ASC
                LIMIT ?""",
            ("REPLAY_PARITY%", max(1, min(int(limit), 100_000))),
        ).fetchall()
        summary = {"eligible": len(rows), "processed": 0, "written": 0, "technical_context": 0, "activity_context": 0, "unknown_context": 0}

        def report_progress():
            if progress_callback:
                try:
                    progress_callback(dict(summary))
                except Exception:
                    # A UI progress observer must never affect a database job.
                    pass

        report_progress()
        for index, row in enumerate(rows, start=1):
            source_metadata = decode(row[7])
            has_technical = bool(source_metadata.get("technical"))
            has_activity = bool(source_metadata.get("activity") or source_metadata.get("symbol_activity"))
            summary["technical_context"] += int(has_technical)
            summary["activity_context"] += int(has_activity)
            summary["unknown_context"] += int(not has_technical and not has_activity)
            if not apply:
                continue
            metadata = {
                "schema": "replay-parity-backfill-v1",
                "paper_only": True,
                "provenance": "historical_database_backfill",
                "source_decision_log_id": row[0],
                "source_decision": {
                    "strategy": row[3], "decision": row[4], "reason": row[5],
                    "metadata": source_metadata,
                },
                "available_historical_context": {
                    "technical": has_technical,
                    "symbol_activity": has_activity,
                    "trade_id": bool(source_metadata.get("trade_id")),
                },
                "unknown_not_backfilled": [
                    "active_symbol_universe", "effective_config", "portfolio_cash_and_open_positions",
                    "closed_candle_identity", "historical_executable_spread_depth",
                ],
                "parity_eligibility": "partial_event_audit_only_not_decision_replay",
            }
            conn.execute(
                """INSERT INTO decision_logs
                   (timestamp, symbol, strategy, decision, reason, price, metadata, source_decision_id)
                   VALUES (?, ?, 'REPLAY_PARITY_BACKFILL', ?, ?, ?, ?, ?)""",
                (row[1], row[2], f"BACKFILL_{row[4] or 'UNKNOWN'}", row[5], row[6],
                 _json_safe_dumps(metadata, ensure_ascii=False, default=str), row[0]),
            )
            summary["written"] += 1
            summary["processed"] = index
            if index % 25 == 0 or index == len(rows):
                report_progress()
        if apply:
            conn.commit()
        report_progress()
        return summary

    return await _run_db(op)

async def commit_open_position(symbol, asset, cash_amount, asset_amount, pos, sig):
    """Atomically persist wallet balances, position and opening decision."""
    def op(conn):
        if _postgres_enabled():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("paper_portfolio_open",))
        row_lock = " FOR UPDATE" if _postgres_enabled() else ""
        existing = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + row_lock, (symbol,)).fetchone()
        if not existing:
            open_count = int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] or 0)
            if int(config.MAX_OPEN_POSITIONS) > 0 and open_count >= int(config.MAX_OPEN_POSITIONS):
                raise RuntimeError("max_open_positions_reached")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + row_lock, ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else config.INITIAL_BALANCE_TRY)
        debit = float(asset_amount or 0) * float(sig.get("price") or pos.get("entry_price") or 0) * (1 + config.COMMISSION_PCT)
        if debit <= 0 or current_cash + 1e-9 < debit:
            raise RuntimeError("insufficient_paper_balance")
        next_cash = current_cash - debit
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", next_cash))
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=virtual_wallet.amount+excluded.amount", (asset, asset_amount))
        conn.execute("INSERT OR REPLACE INTO positions (symbol,side,entry_price,stop_price,take_profit,peak_price,breakeven_hit,quantity,entry_time,strategy,entry_context,trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (symbol, pos.get("side"), pos.get("entry_price"), pos.get("stop_price"), pos.get("take_profit"), pos.get("max_price", pos.get("entry_price")), bool(pos.get("breakeven_hit", False)), pos.get("quantity"), pos.get("entry_time"), pos.get("strategy"), _json_safe_dumps(_position_entry_context(pos)), pos.get("trade_id")))
        persisted = conn.execute("SELECT quantity,entry_time FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if not persisted or float(persisted[0] or 0) != float(pos.get("quantity") or 0) or float(persisted[1] or 0) != float(pos.get("entry_time") or 0):
            raise RuntimeError("Açılan pozisyon kaydı doğrulanamadı; transaction geri alınacak")
        conn.execute("INSERT INTO signals(timestamp,symbol,action,price,reason,strategy,trade_id) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"), sig.get("strategy"), sig.get("trade_id")))
        conn.execute("INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("strategy"), sig.get("action"), sig.get("reason"), sig.get("price"), _json_safe_dumps(sig, default=str)))
        technical = (pos.get("entry_context") or {}).get("technical") or {}
        snapshots = dict(technical.get("mtf_snapshots") or {})
        primary_timeframe = technical.get("timeframe") or "5m"
        snapshots.setdefault(primary_timeframe, technical)
        for timeframe, snapshot in snapshots.items():
            methods = snapshot.get("methodologies") or {}
            regime = methods.get("regime") or {}
            confluence = methods.get("confluence") or {}
            conn.execute("INSERT INTO analysis_snapshots(symbol,timeframe,captured_at,source,methodology_version,regime,regime_confidence,confluence_score,payload,trade_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (symbol, timeframe, pos.get("entry_time") or time.time(), "entry", methods.get("methodology_version"), regime.get("name"), regime.get("confidence"), confluence.get("score"), _json_safe_dumps(snapshot, default=str), pos.get("trade_id")))
        conn.commit()
    await _run_db(op)
    try:
        from app.embedding_worker import worker, trade_document
        await worker.enqueue_persistent(trade_document("entry", symbol, pos, sig))
    except Exception: pass

async def commit_close_position(symbol, asset, cash_amount, trade, sig):
    """Atomically persist close proceeds, trade, position deletion and signal."""
    def op(conn):
        if _postgres_enabled():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("paper_portfolio_open",))
        row_lock = " FOR UPDATE" if _postgres_enabled() else ""
        position_row = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + row_lock, (symbol,)).fetchone()
        if not position_row:
            raise RuntimeError("paper_position_not_found")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + row_lock, ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else 0.0)
        exit_notional = float(trade.get("exit_price") or 0) * float(trade.get("quantity") or 0)
        next_cash = current_cash + exit_notional * (1 - config.COMMISSION_PCT)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", next_cash))
        position_qty = float(position_row[0] or 0)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,0.0) ON CONFLICT(asset) DO NOTHING", (asset,))
        conn.execute("UPDATE virtual_wallet SET amount=amount-? WHERE asset=?", (position_qty, asset))
        conn.execute("INSERT INTO trades (symbol,strategy,side,entry_price,exit_price,quantity,pnl,pnl_pct,entry_time,exit_time,commission,reason,entry_context,max_favorable_pct,max_adverse_pct,hold_seconds,trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (trade.get("symbol"), trade.get("strategy"), trade.get("side"), trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"), trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"), trade.get("commission"), trade.get("reason"), _json_safe_dumps(trade.get("entry_context", {})), trade.get("max_favorable_pct"), trade.get("max_adverse_pct"), trade.get("hold_seconds"), trade.get("trade_id")))
        persisted = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE trade_id=?",
            (trade.get("trade_id"),),
        ).fetchone()[0]
        if int(persisted or 0) != 1:
            raise RuntimeError("Kapanan işlem kaydı doğrulanamadı; transaction geri alınacak")
        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        if int(conn.execute("SELECT COUNT(*) FROM positions WHERE symbol=?", (symbol,)).fetchone()[0] or 0) != 0:
            raise RuntimeError("Kapanan pozisyon silinemedi; transaction geri alınacak")
        conn.execute("INSERT INTO signals(timestamp,symbol,action,price,reason,strategy,trade_id) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"), trade.get("strategy"), trade.get("trade_id")))
        conn.execute("INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), trade.get("strategy"), sig.get("action"), sig.get("reason"), sig.get("price"), _json_safe_dumps(sig, default=str)))
        conn.commit()
    await _run_db(op)
    try:
        from app.embedding_worker import worker, trade_document
        await worker.enqueue_persistent(trade_document("exit", symbol, trade, sig))
    except Exception: pass


async def get_signals(limit: int = 100, offset: int = 0, symbol: str | None = None, action: str | None = None, strategy: str | None = None):
    def op(conn):
        clauses, values = [], []
        if symbol: clauses.append("symbol=?"); values.append(symbol.upper())
        if action: clauses.append("action=?"); values.append(action)
        if strategy: clauses.append("strategy=?"); values.append(strategy)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = conn.execute(f"SELECT id, timestamp, symbol, action, price, reason, strategy, trade_id FROM signals{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", values).fetchall()
        return [dict(r) for r in rows]

    return await _run_db(op)

async def get_signal_count(symbol: str | None = None, action: str | None = None):
    def op(conn):
        clauses, values = [], []
        if symbol: clauses.append("symbol=?"); values.append(symbol.upper())
        if action: clauses.append("action=?"); values.append(action)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM signals{where}", values).fetchone()[0] or 0)
    return await _run_db(op)


async def get_decision_logs(limit=500, symbol=None, strategy=None, offset=0):
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=?"); values.append(symbol.upper())
        if strategy:
            clauses.append("strategy=?"); values.append(strategy)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        values.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = conn.execute(f"SELECT * FROM decision_logs{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", values).fetchall()
        result = [dict(r) for r in rows]
        for row in result:
            try: row["metadata"] = _json_value(row.get("metadata"), {})
            except (TypeError, json.JSONDecodeError): pass
        return result
    return await _run_db(op)


async def save_llm_forecasts(rows):
    """Persist an auditable forecast journal; this has no trading side effect."""
    rows = list(rows or [])
    if not rows:
        return 0
    def op(conn):
        sql = """INSERT INTO llm_forecasts
            (forecast_id,forecast_group_id,symbol,created_at,horizon_minutes,entry_price,direction,confidence,
             invalidation_price,min_move_pct,regime,timeframe_context,scenario,counter_scenario,summary,
             model,prompt_version,snapshot_hash,snapshot,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(forecast_id) DO NOTHING"""
        values = []
        for row in rows:
            values.append((row["forecast_id"], row["forecast_group_id"], str(row["symbol"]).upper(),
                float(row["created_at"]), int(row["horizon_minutes"]), float(row["entry_price"]),
                row["direction"], float(row["confidence"]), row.get("invalidation_price"),
                float(row["min_move_pct"]), row.get("regime"),
                _json_safe_dumps(row.get("timeframe_context") or {}, ensure_ascii=False, default=str),
                row.get("scenario") or "", row.get("counter_scenario"), row.get("summary"), row.get("model"),
                row.get("prompt_version") or "forecast-v1", row["snapshot_hash"],
                _json_safe_dumps(row.get("snapshot") or {}, ensure_ascii=False, default=str), "pending"))
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)


async def get_pending_llm_forecasts(now=None, limit=200):
    now = float(now if now is not None else time.time())
    def op(conn):
        rows = conn.execute("""SELECT * FROM llm_forecasts
            WHERE status='pending' AND created_at + horizon_minutes * 60 <= ?
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        return [_forecast_row(row) for row in rows]
    return await _run_db(op)


async def mark_llm_forecast_evaluated(forecast_id, outcome):
    def op(conn):
        cur = conn.execute("""UPDATE llm_forecasts SET status='evaluated', evaluated_at=?, outcome_price=?,
            outcome_return_pct=?, outcome_direction=?, direction_correct=?, max_favorable_pct=?,
            max_adverse_pct=?, outcome_details=? WHERE forecast_id=? AND status='pending'""",
            (float(outcome["evaluated_at"]), outcome.get("outcome_price"), outcome.get("outcome_return_pct"),
             outcome.get("outcome_direction"), bool(outcome.get("direction_correct")),
             outcome.get("max_favorable_pct"), outcome.get("max_adverse_pct"),
             _json_safe_dumps(outcome.get("details") or {}, ensure_ascii=False, default=str), forecast_id))
        changed = cur.rowcount
        conn.commit(); return changed > 0
    return await _run_db(op)


def _forecast_row(row):
    item = dict(row)
    for key in ("timeframe_context", "snapshot", "outcome_details", "evidence"):
        if key in item:
            item[key] = _json_value(item.get(key), {})
    if "direction_correct" in item and item["direction_correct"] is not None:
        item["direction_correct"] = bool(item["direction_correct"])
    return item


async def get_llm_forecasts(symbol=None, status=None, limit=100, source=None):
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=?"); values.append(str(symbol).upper())
        if status:
            clauses.append("status=?"); values.append(status)
        if source == "chat":
            clauses.append("prompt_version LIKE ?"); values.append("upside-candidate-%")
        elif source == "upside_scout":
            clauses.append("prompt_version LIKE ?"); values.append("upside-scout-%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        # 5000: ML journal eğitimi tüm ölçülmüş canlı tahminleri ister;
        # diğer çağrılar kendi limitiyle kalır.
        values.append(max(1, min(int(limit), 5000)))
        rows = conn.execute(f"SELECT * FROM llm_forecasts{where} ORDER BY created_at DESC LIMIT ?", values).fetchall()
        return [_forecast_row(row) for row in rows]
    return await _run_db(op)


async def get_llm_forecast_report(source=None):
    """Aggregate only journaled forecast outcomes; no trading side effects."""
    def op(conn):
        if source == "chat":
            source_clause = " AND prompt_version LIKE ?"
            params = ("upside-candidate-%",)
        elif source == "upside_scout":
            source_clause = " AND prompt_version LIKE ?"
            params = ("upside-scout-%",)
        else:
            source_clause = ""
            params = ()
        rows = conn.execute(f"""SELECT horizon_minutes,
            COUNT(*) AS total_count,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
            SUM(CASE WHEN status='evaluated' AND direction_correct THEN 1 ELSE 0 END) AS correct_count,
            SUM(CASE WHEN status='evaluated' AND direction='up' AND max_favorable_pct IS NOT NULL
                     AND max_favorable_pct >= min_move_pct THEN 1 ELSE 0 END) AS target_hit_count,
            SUM(CASE WHEN status='evaluated' AND outcome_details->>'first_hit_minutes' IS NOT NULL
                     THEN 1 ELSE 0 END) AS eventual_hit_count,
            AVG(CASE WHEN status='evaluated' THEN confidence END) AS average_confidence,
            AVG(CASE WHEN status='evaluated' THEN ABS((confidence / 100.0) - CASE WHEN direction_correct THEN 1.0 ELSE 0.0 END) END) AS calibration_error,
            AVG(CASE WHEN status='evaluated' THEN outcome_return_pct END) AS average_return_pct
            FROM llm_forecasts WHERE 1=1{source_clause} GROUP BY horizon_minutes ORDER BY horizon_minutes""", params).fetchall()
        return [dict(row) for row in rows]
    return await _run_db(op)


async def fix_upside_scout_units():
    """One-shot repair for upside-scout rows saved with percent-unit targets.

    İlk upside-scout kayıtları min_move_pct'i yüzde (2.0) tutuyordu;
    değerlendirme kesir (0.02) beklediği için tüm satırlar 'hedefe ulaşılmadı'
    ölçüldü. Deploy'da idempotent çalışır: kesir birimine çevirir, eski
    (eventual_hit anahtarı olmayan) değerlendirmeleri yeniden ölçüm için
    pending'e döndürür. Düzeltme sonrası ikinci çalıştırmada 0 satır etkilenir.
    """
    def op(conn):
        converted = conn.execute(
            "UPDATE llm_forecasts SET min_move_pct = min_move_pct / 100.0 "
            "WHERE prompt_version LIKE ? AND min_move_pct > 0.5", ("upside-scout-%",)).rowcount
        requeued = conn.execute(
            "UPDATE llm_forecasts SET status='pending', evaluated_at=NULL, outcome_price=NULL, "
            "outcome_return_pct=NULL, outcome_direction=NULL, direction_correct=NULL, "
            "max_favorable_pct=NULL, max_adverse_pct=NULL, outcome_details='{}' "
            "WHERE prompt_version LIKE ? AND status='evaluated' "
            "AND (outcome_details IS NULL OR outcome_details->>'eventual_hit' IS NULL)",
            ("upside-scout-%",)).rowcount
        conn.commit()
        return {"unit_converted": converted or 0, "requeued": requeued or 0}
    return await _run_db(op)


async def get_ml_training_candles(cutoff_ms: int, max_bars_per_symbol: int = 3000):
    """M5 candle'ları sembol başına son N bar olacak şekilde dict döndürür.

    historical_candles'a yalnızca 5m mumlar yazılır (backfill + backtest);
    1m veri toplanmadığından ML eğitimi 5m bar üzerinden çalışır
    (5dk ufuk = 1 bar, 15dk ufuk = 3 bar).
    """
    def op(conn):
        data: dict[str, dict[str, list]] = {}
        rows = conn.execute(
            """SELECT symbol, open_time, high, low, close, volume
               FROM historical_candles WHERE timeframe='5m' AND open_time >= ?
               ORDER BY symbol, open_time DESC""", (int(cutoff_ms),)).fetchall()
        for row in rows:
            # Postgres (asyncpg) satırları dict döner; tuple-unpack anahtar
            # stringlerini değişkene atadığı için dict erişimi kullanılır.
            symbol = str(row["symbol"]).upper()
            bucket = data.setdefault(symbol, {"open_time": [], "high": [], "low": [], "close": [], "volume": []})
            if len(bucket["open_time"]) >= max_bars_per_symbol:
                continue
            bucket["open_time"].append(int(row["open_time"]))
            bucket["high"].append(float(row["high"]))
            bucket["low"].append(float(row["low"]))
            bucket["close"].append(float(row["close"]))
            bucket["volume"].append(float(row["volume"]))
        return {sym: {k: list(reversed(v)) for k, v in bucket.items()} for sym, bucket in data.items()}
    return await _run_db(op)


async def save_ml_model_artifact(meta: dict):
    def op(conn):
        conn.execute("""INSERT INTO ml_model_artifacts
            (created_at, horizons, sample_count, journal_sample_count, symbol_count,
             metrics, artifact_path, feature_version, status)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (float(meta["created_at"]), json.dumps(meta.get("horizons") or []),
             int(meta.get("sample_count") or 0), int(meta.get("journal_sample_count") or 0),
             int(meta.get("symbol_count") or 0), json.dumps(meta.get("metrics") or {},
             ensure_ascii=False, default=str), meta["artifact_path"],
             meta.get("feature_version") or "v1", meta.get("status") or "ready"))
        conn.commit()
    return await _run_db(op)


async def get_latest_ml_model_artifact():
    def op(conn):
        row = conn.execute("SELECT * FROM ml_model_artifacts ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def replace_llm_forecast_lessons(lessons):
    """Upsert derived evidence; lessons are never written by the LLM itself."""
    def op(conn):
        now = time.time()
        sql = """INSERT INTO llm_forecast_lessons
            (lesson_key,symbol,horizon_minutes,regime,direction,sample_size,in_sample_accuracy,holdout_accuracy,
             confidence_calibration_error,lesson,evidence,status,generated_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(lesson_key) DO UPDATE SET sample_size=excluded.sample_size,
            in_sample_accuracy=excluded.in_sample_accuracy,holdout_accuracy=excluded.holdout_accuracy,
            confidence_calibration_error=excluded.confidence_calibration_error,lesson=excluded.lesson,
            evidence=excluded.evidence,status=excluded.status,updated_at=excluded.updated_at"""
        values = [(item["lesson_key"], item.get("symbol"), int(item["horizon_minutes"]), item.get("regime"),
                   item.get("direction"), int(item["sample_size"]), item.get("in_sample_accuracy"),
                   item.get("holdout_accuracy"), item.get("confidence_calibration_error"), item["lesson"],
                   _json_safe_dumps(item.get("evidence") or {}, ensure_ascii=False, default=str), item.get("status", "candidate"),
                   now, now) for item in lessons]
        if values:
            conn.executemany(sql, values); conn.commit()
        return len(values)
    return await _run_db(op)


async def get_llm_forecast_lessons(symbol=None, regime=None, status="active", limit=12):
    def op(conn):
        clauses, values = [], []
        if status:
            clauses.append("status=?"); values.append(status)
        if symbol:
            clauses.append("(symbol IS NULL OR symbol=?)"); values.append(str(symbol).upper())
        if regime:
            clauses.append("(regime IS NULL OR regime=?)"); values.append(regime)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 100)))
        rows = conn.execute(f"SELECT * FROM llm_forecast_lessons{where} ORDER BY holdout_accuracy DESC, sample_size DESC LIMIT ?", values).fetchall()
        return [_forecast_row(row) for row in rows]
    return await _run_db(op)


def _prediction_row(row):
    item = dict(row)
    for key in ("evidence", "risks", "snapshot", "outcome_details", "analysis_factors"):
        if key in item:
            item[key] = _json_value(item.get(key), [] if key in ("evidence", "risks") else {})
    if "direction_correct" in item and item["direction_correct"] is not None:
        item["direction_correct"] = bool(item["direction_correct"])
    return item


async def save_chat_predictions(rows):
    """Chat M5/M15 tahminlerini kendi tablosuna kaydet; llm_forecasts'a paralel denetim günlüğü."""
    rows = list(rows or [])
    if not rows:
        return 0
    def op(conn):
        sql = """INSERT INTO chat_predictions
            (prediction_id,forecast_group_id,symbol,horizon_minutes,created_at,entry_price,direction,confidence,
             score,min_move_pct,regime,evidence,risks,snapshot,snapshot_hash,model,prompt_version,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(prediction_id) DO NOTHING"""
        values = []
        for row in rows:
            values.append((row["prediction_id"], row["forecast_group_id"], str(row["symbol"]).upper(),
                int(row["horizon_minutes"]), float(row["created_at"]), float(row["entry_price"]),
                row["direction"], float(row["confidence"]), float(row.get("score") or 0),
                float(row["min_move_pct"]), row.get("regime"),
                _json_safe_dumps(row.get("evidence") or [], ensure_ascii=False, default=str),
                _json_safe_dumps(row.get("risks") or [], ensure_ascii=False, default=str),
                _json_safe_dumps(row.get("snapshot") or {}, ensure_ascii=False, default=str),
                row["snapshot_hash"], row.get("model"), row.get("prompt_version") or "chat-upside-v1", "pending"))
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)


async def get_pending_chat_predictions(now=None, limit=100):
    now = float(now if now is not None else time.time())
    def op(conn):
        rows = conn.execute("""SELECT * FROM chat_predictions
            WHERE status='pending' AND created_at + horizon_minutes * 60 <= ?
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        return [_prediction_row(row) for row in rows]
    return await _run_db(op)


async def mark_chat_prediction_evaluated(prediction_id, outcome):
    def op(conn):
        cur = conn.execute("""UPDATE chat_predictions SET status='evaluated', evaluated_at=?, outcome_price=?,
            outcome_return_pct=?, outcome_direction=?, direction_correct=?, max_favorable_pct=?,
            max_adverse_pct=?, outcome_details=? WHERE prediction_id=? AND status='pending'""",
            (float(outcome["evaluated_at"]), outcome.get("outcome_price"), outcome.get("outcome_return_pct"),
             outcome.get("outcome_direction"), bool(outcome.get("direction_correct")),
             outcome.get("max_favorable_pct"), outcome.get("max_adverse_pct"),
             _json_safe_dumps(outcome.get("details") or {}, ensure_ascii=False, default=str), prediction_id))
        changed = cur.rowcount
        conn.commit(); return changed > 0
    return await _run_db(op)


async def get_chat_predictions_needing_analysis(limit=6):
    def op(conn):
        rows = conn.execute("""SELECT * FROM chat_predictions
            WHERE status='evaluated' AND analysis_status='pending'
            ORDER BY created_at ASC LIMIT ?""", (max(1, min(int(limit), 50)),)).fetchall()
        return [_prediction_row(row) for row in rows]
    return await _run_db(op)


async def mark_chat_prediction_analyzed(prediction_id, *, analysis, factors, model, analysis_status="done"):
    def op(conn):
        cur = conn.execute("""UPDATE chat_predictions SET analysis_status=?, analysis=?, analysis_factors=?, analysis_model=?, analysis_at=?
            WHERE prediction_id=? AND analysis_status='pending'""",
            (analysis_status, analysis, _json_safe_dumps(factors or {}, ensure_ascii=False, default=str),
             model, time.time(), prediction_id))
        changed = cur.rowcount
        conn.commit(); return changed > 0
    return await _run_db(op)


async def get_chat_predictions(symbol=None, status=None, horizon_minutes=None, analyzed=None, limit=50):
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=?"); values.append(str(symbol).upper())
        if status:
            clauses.append("status=?"); values.append(status)
        if horizon_minutes is not None:
            clauses.append("horizon_minutes=?"); values.append(int(horizon_minutes))
        if analyzed is not None:
            clauses.append("analysis_status=?"); values.append("done" if analyzed else "pending")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 500)))
        rows = conn.execute(f"SELECT * FROM chat_predictions{where} ORDER BY created_at DESC LIMIT ?", values).fetchall()
        return [_prediction_row(row) for row in rows]
    return await _run_db(op)


async def get_chat_prediction_aggregates():
    """Ufuk ve sembol bazında ölçülen başarı; salt kapanmış mum sonuçları."""
    def op(conn):
        horizons = [dict(row) for row in conn.execute("""SELECT horizon_minutes,
            COUNT(*) AS total_count,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
            SUM(CASE WHEN status='evaluated' AND direction_correct THEN 1 ELSE 0 END) AS correct_count,
            AVG(CASE WHEN status='evaluated' THEN confidence END) AS average_confidence,
            AVG(CASE WHEN status='evaluated' THEN ABS((confidence / 100.0) - CASE WHEN direction_correct THEN 1.0 ELSE 0.0 END) END) AS calibration_error,
            AVG(CASE WHEN status='evaluated' THEN outcome_return_pct END) AS average_return_pct,
            AVG(CASE WHEN status='evaluated' THEN max_favorable_pct END) AS average_favorable_pct,
            AVG(CASE WHEN status='evaluated' THEN max_adverse_pct END) AS average_adverse_pct,
            SUM(CASE WHEN status='evaluated' AND analysis_status='done' THEN 1 ELSE 0 END) AS analyzed_count,
            SUM(CASE WHEN status='evaluated' AND outcome_direction='range' THEN 1 ELSE 0 END) AS range_count
            FROM chat_predictions GROUP BY horizon_minutes ORDER BY horizon_minutes""").fetchall()]
        symbols = [dict(row) for row in conn.execute("""SELECT symbol,
            COUNT(*) AS total_count,
            SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
            SUM(CASE WHEN status='evaluated' AND direction_correct THEN 1 ELSE 0 END) AS correct_count,
            AVG(CASE WHEN status='evaluated' THEN outcome_return_pct END) AS average_return_pct
            FROM chat_predictions GROUP BY symbol ORDER BY evaluated_count DESC, symbol LIMIT 25""").fetchall()]
        return {"horizons": horizons, "symbols": symbols}
    return await _run_db(op)


async def upsert_chat_prediction_insights(insights):
    """Sadece arka plan analizi türetir; LLM kendi dersini doğrudan aktif etmez."""
    def op(conn):
        now = time.time()
        sql = """INSERT INTO chat_prediction_insights
            (insight_key,scope,symbol,horizon_minutes,sample_size,success_count,failure_count,
             insight,factors,source_ids,status,generated_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(insight_key) DO UPDATE SET sample_size=excluded.sample_size,
            success_count=excluded.success_count,failure_count=excluded.failure_count,insight=excluded.insight,
            factors=excluded.factors,source_ids=excluded.source_ids,status=excluded.status,updated_at=excluded.updated_at"""
        values = [(item["insight_key"], item["scope"], item.get("symbol"), int(item.get("horizon_minutes") or 0),
                   int(item["sample_size"]), int(item.get("success_count") or 0), int(item.get("failure_count") or 0),
                   item["insight"], _json_safe_dumps(item.get("factors") or {}, ensure_ascii=False, default=str),
                   _json_safe_dumps(item.get("source_ids") or [], ensure_ascii=False, default=str),
                   item.get("status", "active"), now, now) for item in insights]
        if values:
            conn.executemany(sql, values); conn.commit()
        return len(values)
    return await _run_db(op)


async def get_chat_prediction_insights(symbol=None, horizon_minutes=None, status="active", limit=12):
    def op(conn):
        clauses, values = [], []
        if status:
            clauses.append("status=?"); values.append(status)
        if symbol:
            clauses.append("(symbol IS NULL OR symbol=?)"); values.append(str(symbol).upper())
        if horizon_minutes is not None:
            clauses.append("horizon_minutes=?"); values.append(int(horizon_minutes))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 100)))
        rows = conn.execute(f"""SELECT * FROM chat_prediction_insights{where}
            ORDER BY sample_size DESC, updated_at DESC LIMIT ?""", values).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["factors"] = _json_value(item.get("factors"), {})
            item["source_ids"] = _json_value(item.get("source_ids"), [])
            result.append(item)
        return result
    return await _run_db(op)


def _velocity_row(row):
    item = dict(row)
    if "outcome_details" in item:
        item["outcome_details"] = _json_value(item.get("outcome_details"), {})
    if "passes" in item and item["passes"] is not None:
        item["passes"] = bool(item["passes"])
    if "touched_target" in item and item["touched_target"] is not None:
        item["touched_target"] = bool(item["touched_target"])
    return item


async def save_velocity_candidates(rows):
    """Hız avcısı tarama adaylarını journal'a yazar; tekrar idempotent."""
    rows = list(rows or [])
    if not rows:
        return 0
    def op(conn):
        sql = """INSERT INTO velocity_candidates
            (candidate_id,created_at,symbol,price,target_pct,ml_target_pct,ml_hit_probability,
             atr_pct,volume_ratio,ret3_pct,
             velocity_score,passes,rank,status,outcome_details)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id) DO NOTHING"""
        values = []
        for row in rows:
            vals = [row["candidate_id"], float(row["created_at"]), str(row["symbol"]).upper(),
                    float(row["price"]), float(row["target_pct"]),
                    float(row["ml_target_pct"]) if row.get("ml_target_pct") is not None else None,
                    float(row["ml_hit_probability"]) if row.get("ml_hit_probability") is not None else None,
                    float(row["atr_pct"]),
                    float(row["volume_ratio"]), float(row["ret3_pct"]), float(row["velocity_score"]),
                    bool(row.get("passes")), row.get("rank"), "pending"]
            # M5 desen + M1/M3 öncü ATR durumunu outcome_details'e göm (kolon mevcut).
            extra = {}
            if row.get("m5_pattern") is not None or row.get("m5_pattern_ok") is not None:
                extra["m5_pattern"] = row.get("m5_pattern")
                extra["m5_pattern_ok"] = row.get("m5_pattern_ok")
            if row.get("leading_ok") is not None:
                extra["leading_ok"] = bool(row.get("leading_ok"))
                extra["m1_atr_prev"] = row.get("m1_atr_prev")
                extra["m3_atr_prev"] = row.get("m3_atr_prev")
            # Mikro yapı anlık görüntüsü (whale verdict, CVD): kalıcı yazılmıyordu;
            # filtre istatistiklerinin birikmesi için outcome_details'e gömülür.
            if row.get("microstructure"):
                extra["microstructure"] = row["microstructure"]
            vals.append(_json_safe_dumps(extra) if extra else None)
            values.append(vals)
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)


async def get_pending_velocity_candidates(now=None, limit=100):
    now = float(now if now is not None else time.time())
    def op(conn):
        # Hedef penceresi 5 dakika; tarama anından 5 dk geçenler ölçüme hazır.
        rows = conn.execute("""SELECT * FROM velocity_candidates
            WHERE status='pending' AND created_at <= ? - 300
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        return [_velocity_row(row) for row in rows]
    return await _run_db(op)


async def mark_velocity_candidate_evaluated(candidate_id, *, mfe_pct, touched_target, details, force=False):
    def op(conn):
        where = "WHERE candidate_id=?" + ("" if force else " AND status='pending'")
        # outcome_details taramada m5_pattern/m5_pattern_ok taşıyor; üzerine
        # yazmak yerine birleştiriyoruz — aksi halde frontend "M5 Desen"
        # sütunu değerlendirme sonrası boş görünüyordu.
        existing = conn.execute("SELECT outcome_details FROM velocity_candidates WHERE candidate_id=?",
                                 (candidate_id,)).fetchone()
        prior = _json_value(existing[0], {}) if existing else {}
        merged = {**(prior or {}), **(details or {})}
        cur = conn.execute(f"""UPDATE velocity_candidates SET status='evaluated', evaluated_at=?, mfe_pct=?,
            touched_target=?, outcome_details=? {where}""",
            (time.time(), float(mfe_pct), bool(touched_target),
             _json_safe_dumps(merged, ensure_ascii=False, default=str), candidate_id))
        changed = cur.rowcount
        conn.commit(); return changed > 0
    return await _run_db(op)


async def delete_velocity_candidates(candidate_ids):
    """Journal temizliği: seçili aday satırlarını kalıcı olarak siler."""
    ids = [str(i) for i in (candidate_ids or []) if str(i)]
    if not ids:
        return 0
    def op(conn):
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM velocity_candidates WHERE candidate_id IN ({placeholders})", ids)
        deleted = conn.execute("SELECT changes()").fetchone()[0] if not _postgres_enabled() else len(ids)
        conn.commit(); return int(deleted)
    return await _run_db(op)


async def get_velocity_candidates(limit=50, status=None):
    def op(conn):
        clauses, values = [], []
        if status:
            clauses.append("status=?"); values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 500)))
        rows = conn.execute(f"SELECT * FROM velocity_candidates{where} ORDER BY created_at DESC LIMIT ?", values).fetchall()
        return [_velocity_row(row) for row in rows]
    return await _run_db(op)


async def get_velocity_calibration_stats(profile: str | None = None):
    """Koşullu dokunuş oranı + bileşen bazlı istatistik; eşik otomatik kalibrasyonu bununla yapılır.

    profile: None (tümü), "5m" (vel-5dk-... journal'ları) veya "15m" (vel-15dk-...).
    5dk-%2 ve 15dk-%3 profillerinin hit oranları çok farklı; harmanlanmış tek
    havuz otomatik kalibrasyonu yanlış yönlendiriyordu — profil ayrımı eklendi.
    """
    prefix = {"5m": "vel-5dk-%", "15m": "vel-15dk-%"}.get(profile)
    def op(conn):
        where = " WHERE candidate_id LIKE ?" if prefix else ""
        params = (prefix,) if prefix else ()
        rows = [dict(row) for row in conn.execute(f"""SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
            SUM(CASE WHEN status='evaluated' AND touched_target THEN 1 ELSE 0 END) AS touched_count,
            AVG(CASE WHEN status='evaluated' THEN mfe_pct END) AS average_mfe_pct,
            AVG(CASE WHEN status='evaluated' AND passes THEN mfe_pct END) AS passing_mfe_pct,
            SUM(CASE WHEN status='evaluated' AND passes AND touched_target THEN 1 ELSE 0 END) AS passing_touched_count,
            SUM(CASE WHEN status='evaluated' AND passes THEN 1 ELSE 0 END) AS passing_count
            FROM velocity_candidates{where}""", params).fetchall()]
        return rows[0] if rows else {}
    return await _run_db(op)


async def get_velocity_symbol_quality_stats():
    """Sembol bazlı velocity journal sonuçları: ölçülen aday, dokunan, ort. MFE.

    Sembol kalite filtresinin journal geçmişini de kullanabilmesi için;
    yalnızca ölçülmüş (status='evaluated') satırlar sayılır. Dokunuş oranı
    düşük ve ort. MFE'si zayıf semboller pump sonrası momentumu tutamıyor
    (2026-08-31 araştırması: HEMITRY/NOTTRY/CHIPTRY 4 ölçümde 0 dokunuş).
    """
    def op(conn):
        rows = conn.execute("""SELECT symbol,
            COUNT(*) AS evaluated,
            SUM(CASE WHEN touched_target THEN 1 ELSE 0 END) AS touched,
            AVG(mfe_pct) AS average_mfe_pct
            FROM velocity_candidates
            WHERE status='evaluated'
            GROUP BY symbol""").fetchall()
        return [dict(row) for row in rows]
    return await _run_db(op)


async def get_velocity_pattern_hit_rates():
    """m5_pattern_ok=true/false alt kümelerinde koşullu (passes) dokunuş oranı.

    outcome_details JSON'unda gömülü olduğu için Python tarafında gruplanır
    (JSONB sorgusu şema başına farklılaştığından basit ve taşınabilir kalır).
    """
    def op(conn):
        rows = conn.execute("""SELECT outcome_details, touched_target FROM velocity_candidates
            WHERE status='evaluated' AND passes=TRUE""").fetchall()
        return [(_json_value(row[0], {}) or {}, bool(row[1])) for row in rows]
    raw = await _run_db(op)
    buckets = {"pattern_ok": {"evaluated": 0, "touched": 0}, "pattern_not_ok": {"evaluated": 0, "touched": 0},
               "no_pattern": {"evaluated": 0, "touched": 0}}
    leading_buckets = {"leading_ok": {"evaluated": 0, "touched": 0},
                       "leading_not_ok": {"evaluated": 0, "touched": 0}}
    for details, touched in raw:
        pattern_ok = details.get("m5_pattern_ok")
        key = "pattern_ok" if pattern_ok is True else "pattern_not_ok" if pattern_ok is False else "no_pattern"
        buckets[key]["evaluated"] += 1
        buckets[key]["touched"] += 1 if touched else 0
        leading = details.get("leading_ok")
        if leading is True:
            leading_buckets["leading_ok"]["evaluated"] += 1
            leading_buckets["leading_ok"]["touched"] += 1 if touched else 0
        elif leading is False:
            leading_buckets["leading_not_ok"]["evaluated"] += 1
            leading_buckets["leading_not_ok"]["touched"] += 1 if touched else 0
    for bucket in buckets.values():
        bucket["hit_rate"] = bucket["touched"] / bucket["evaluated"] if bucket["evaluated"] else None
    for bucket in leading_buckets.values():
        bucket["hit_rate"] = bucket["touched"] / bucket["evaluated"] if bucket["evaluated"] else None
    return {**buckets, "leading": leading_buckets}


async def cleanup_stale_velocity_candidates(max_age_seconds: int = 6 * 3600):
    """Sembol WS/REST'ten hiç mum üretmediği için sonsuza dek 'pending' kalan
    kayıtları 'expired' işaretler; istatistikleri şişirmelerini önler."""
    cutoff = time.time() - max_age_seconds
    def op(conn):
        cur = conn.execute("""UPDATE velocity_candidates SET status='expired', evaluated_at=?
            WHERE status='pending' AND created_at <= ?""", (time.time(), cutoff))
        changed = cur.rowcount
        conn.commit(); return changed
    return await _run_db(op)


async def read_only_query(sql: str, limit: int = 500):
    """Execute a narrowly validated, read-only query for LLM inspection."""
    statement = str(sql or "").strip()
    if not statement or ";" in statement:
        raise ValueError("Tek bir SELECT sorgusu gerekli; çoklu ifade veya noktalı virgül yasak")
    if not re.match(r"^(SELECT|WITH)\b", statement, re.I):
        raise ValueError("Yalnızca SELECT veya WITH ... SELECT sorgularına izin verilir")
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|PRAGMA|COPY|GRANT|REVOKE|CALL|DO|VACUUM|ATTACH|DETACH)\b", statement, re.I):
        raise ValueError("Yazma, DDL veya yönetim komutu tespit edildi")
    allowed = frozenset({"positions", "trades", "signals", "decision_logs", "virtual_wallet", "backtests", "analysis_snapshots", "llm_tool_logs"})
    # FROM/JOIN sonrası tablo adlarını çıkar (alt sorguları da kontrol et)
    referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", statement, re.I))
    # Alt sorgulardaki tabloları da kontrol et (nested SELECT)
    subquery_tables = set(re.findall(r"\)\s*AS\s+\w+\s+(?:LEFT|RIGHT|INNER|OUTER|CROSS|FULL|JOIN|FROM)\s+([A-Za-z_][A-Za-z0-9_]*)", statement, re.I))
    all_referenced = referenced | subquery_tables
    if not all_referenced or not all_referenced.issubset(allowed):
        raise ValueError(f"Sorgu yalnızca izin verilen uygulama tablolarını kullanabilir: {allowed}")
    bounded = statement
    if not re.search(r"\bLIMIT\s+\d+\b", bounded, re.I):
        bounded = f"SELECT * FROM ({bounded}) AS llm_read_only_result LIMIT {max(1, min(int(limit), 500))}"
    else:
        bounded = re.sub(r"(\bLIMIT\s+)\d+", lambda m: f"{m.group(1)}{max(1, min(int(limit), 500))}", bounded, count=1, flags=re.I)
    def op(conn):
        cur = conn.execute(bounded)
        rows = cur.fetchall()
        return [dict(row) if isinstance(row, dict) else dict(zip([d[0] for d in cur.description], row)) for row in rows]
    return await _run_db(op)


async def save_llm_tool_log(item):
    def op(conn):
        conn.execute(
            "INSERT INTO llm_tool_logs (timestamp, scope, tool_name, arguments, result_summary, duration_ms, success) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.get("timestamp") or time.time(), item.get("scope"), item.get("tool_name"),
             _json_safe_dumps(item.get("arguments") or {}, default=str), item.get("result_summary"),
             item.get("duration_ms"), bool(item.get("success")))
        )
        conn.commit()
    await _run_db(op)


async def get_llm_tool_logs(limit=500):
    def op(conn):
        rows = conn.execute("SELECT * FROM llm_tool_logs ORDER BY timestamp DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
        result = [dict(r) for r in rows]
        for row in result:
            try: row["arguments"] = _json_value(row.get("arguments"), {})
            except (TypeError, json.JSONDecodeError): pass
        return result
    return await _run_db(op)


async def save_a2a_message(message, direction="outbound", status="queued", error=None, insert_only=False):
    def op(conn):
        if insert_only:
            cursor = conn.execute("""INSERT INTO a2a_messages
                (message_id,correlation_id,direction,message_type,sender,recipient,status,payload,created_at,delivered_at,acknowledged_at,last_error,attempts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(message_id) DO NOTHING""",
                (message.get("message_id"), message.get("correlation_id"), direction, message.get("type"),
                 message.get("from"), message.get("to"), status, _json_safe_dumps(message, ensure_ascii=False, default=str),
                 message.get("created_at") or time.time(), time.time() if status == "delivered" else None,
                 time.time() if status == "acknowledged" else None, error))
            conn.commit()
            return cursor.rowcount > 0
        conn.execute("""INSERT OR REPLACE INTO a2a_messages
            (message_id,correlation_id,direction,message_type,sender,recipient,status,payload,created_at,delivered_at,acknowledged_at,last_error,attempts)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT attempts FROM a2a_messages WHERE message_id=?),0))""",
            (message.get("message_id"), message.get("correlation_id"), direction, message.get("type"),
             message.get("from"), message.get("to"), status, _json_safe_dumps(message, ensure_ascii=False, default=str),
             message.get("created_at") or time.time(), time.time() if status == "delivered" else None,
             time.time() if status == "acknowledged" else None, error, message.get("message_id")))
        conn.commit()
        return True
    return await _run_db(op)


async def get_a2a_messages(limit=100, status=None):
    def op(conn):
        params = [max(1, min(int(limit), 500))]
        where = ""
        if status:
            where = " WHERE status=?"
            params.insert(0, str(status))
        rows = conn.execute(f"SELECT * FROM a2a_messages{where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["payload"] = _json_value(row.get("payload"), {})
        return result
    return await _run_db(op)


async def acknowledge_a2a_message(message_id):
    def op(conn):
        cur = conn.execute("UPDATE a2a_messages SET status='acknowledged', acknowledged_at=? WHERE message_id=?", (time.time(), str(message_id)))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


async def update_a2a_message_status(message_id, status, payload=None):
    def op(conn):
        if payload is None:
            cur = conn.execute("UPDATE a2a_messages SET status=?, acknowledged_at=? WHERE message_id=?", (status, time.time() if status == "acknowledged" else None, str(message_id)))
        else:
            cur = conn.execute("UPDATE a2a_messages SET status=?, payload=?, acknowledged_at=? WHERE message_id=?", (status, _json_safe_dumps(payload, ensure_ascii=False, default=str), time.time() if status == "acknowledged" else None, str(message_id)))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


async def upsert_llm_symbol_guard(symbol, guard_type="cooldown", status="active", blocked_until=None, reason=None, evidence=None):
    symbol = str(symbol).replace("_", "").upper()
    now = time.time()
    def op(conn):
        row = conn.execute("SELECT revision FROM llm_symbol_guards WHERE symbol=?", (symbol,)).fetchone()
        revision = int((row[0] if row else 0) or 0) + 1
        conn.execute("""INSERT INTO llm_symbol_guards
            (symbol,guard_type,status,blocked_until,reason,evidence,revision,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET guard_type=excluded.guard_type,status=excluded.status,
            blocked_until=excluded.blocked_until,reason=excluded.reason,evidence=excluded.evidence,
            revision=excluded.revision,updated_at=excluded.updated_at""",
            (symbol, str(guard_type), str(status), blocked_until, reason, _json_safe_dumps(evidence or {}, ensure_ascii=False, default=str), revision, now, now))
        conn.commit()
        return {"symbol": symbol, "guard_type": guard_type, "status": status, "blocked_until": blocked_until, "reason": reason, "evidence": evidence or {}, "revision": revision, "updated_at": now}
    return await _run_db(op)


async def get_llm_symbol_guard(symbol):
    symbol = str(symbol).replace("_", "").upper()
    def op(conn):
        row = conn.execute("SELECT * FROM llm_symbol_guards WHERE symbol=?", (symbol,)).fetchone()
        if not row: return None
        result = dict(row); result["evidence"] = _json_value(result.get("evidence"), {}); return result
    return await _run_db(op)


async def get_llm_symbol_guards(active_only=False):
    def op(conn):
        where = " WHERE status='active'" if active_only else ""
        rows = conn.execute(f"SELECT * FROM llm_symbol_guards{where} ORDER BY updated_at DESC").fetchall()
        result = [dict(row) for row in rows]
        for item in result: item["evidence"] = _json_value(item.get("evidence"), {})
        return result
    return await _run_db(op)


async def remove_llm_symbol_guard(symbol, reason="llm_guard_removed"):
    symbol = str(symbol).replace("_", "").upper()
    def op(conn):
        cur = conn.execute("UPDATE llm_symbol_guards SET status='removed',reason=?,updated_at=? WHERE symbol=?", (reason, time.time(), symbol))
        conn.commit(); return cur.rowcount > 0
    return await _run_db(op)

async def create_alert_rule(rule):
    now = _db_timestamp()
    def op(conn):
        cur = conn.execute("""INSERT INTO alert_rules
            (name,symbol,timeframe,rule_type,operator,threshold,cooldown_seconds,enabled,armed,rearm_threshold,expires_at,notify_channels,created_by,reason,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""", (
            rule.get("name") or f"{rule['symbol']} alarm", str(rule["symbol"]).upper(), rule.get("timeframe", "5m"),
            rule.get("rule_type", "price"), rule.get("operator", "lte"), float(rule["threshold"]),
            max(0, int(rule.get("cooldown_seconds", 1800))), True, True, rule.get("rearm_threshold"), _db_datetime_value(rule.get("expires_at")),
            _json_safe_dumps(rule.get("notify_channels") or ["websocket"]), rule.get("created_by", "user"), rule.get("reason"), now, now))
        row = cur.fetchone()
        conn.commit(); return row[0] if row else None
    return await _run_db(op)

async def list_alert_rules(active_only=False):
    def op(conn):
        sql = "SELECT * FROM alert_rules" + (" WHERE enabled=1" if active_only else "") + " ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("last_triggered_at", "expires_at", "created_at", "updated_at"):
                item[key] = _epoch_value(item.get(key))
            item["notify_channels"] = _json_value(item.get("notify_channels"), ["websocket"]); result.append(item)
        return result
    return await _run_db(op)

async def update_alert_rule(rule_id, changes):
    allowed = {"name", "enabled", "armed", "last_value", "threshold", "operator", "rule_type", "timeframe", "cooldown_seconds", "rearm_threshold", "expires_at", "notify_channels", "reason"}
    fields = [key for key in changes if key in allowed]
    if not fields: return None
    values = [_json_safe_dumps(changes[key]) if key == "notify_channels" else bool(changes[key]) if key in {"enabled", "armed"} else _db_datetime_value(changes[key]) if key == "expires_at" else changes[key] for key in fields]
    values.extend([_db_timestamp(), rule_id])
    def op(conn):
        conn.execute(f"UPDATE alert_rules SET {', '.join(f'{key}=?' for key in fields)}, updated_at=? WHERE id=?", values); conn.commit()
        row = conn.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
        if not row: return None
        item = dict(row)
        for key in ("last_triggered_at", "expires_at", "created_at", "updated_at"):
            item[key] = _epoch_value(item.get(key))
        item["notify_channels"] = _json_value(item.get("notify_channels"), ["websocket"])
        return item
    return await _run_db(op)

async def delete_alert_rule(rule_id):
    def op(conn):
        conn.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,)); conn.commit(); return True
    return await _run_db(op)

async def record_alert_trigger(rule_id, event_key, value, message, severity="info"):
    now = _db_timestamp()
    def op(conn):
        inserted = conn.execute("INSERT INTO alert_events(rule_id,symbol,event_key,value,message,severity,triggered_at) SELECT id,symbol,?,?,?,?,? FROM alert_rules WHERE id=? ON CONFLICT(event_key) DO NOTHING", (event_key, value, message, severity, now, rule_id))
        if inserted.rowcount == 0: conn.rollback(); return None
        armed_false = "FALSE"
        conn.execute(f"UPDATE alert_rules SET last_triggered_at=?, last_value=?, armed=CASE WHEN rearm_threshold IS NULL THEN armed ELSE {armed_false} END, updated_at=? WHERE id=?", (now, value, now, rule_id)); conn.commit()
        row = conn.execute("SELECT * FROM alert_events WHERE event_key=?", (event_key,)).fetchone(); return dict(row) if row else None
    return await _run_db(op)

async def get_alert_events(limit=100):
    def op(conn):
        result = []
        for row in conn.execute("SELECT * FROM alert_events ORDER BY triggered_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall():
            item = dict(row)
            item["triggered_at"] = _epoch_value(item.get("triggered_at"))
            result.append(item)
        return result
    return await _run_db(op)

async def save_push_subscription(subscription):
    now = time.time(); endpoint = str(subscription.get("endpoint") or "")
    if not endpoint: raise ValueError("push subscription endpoint gerekli")
    def op(conn):
        conn.execute("INSERT INTO push_subscriptions(endpoint,subscription,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription,updated_at=excluded.updated_at", (endpoint, _json_safe_dumps(subscription), now, now)); conn.commit(); return True
    return await _run_db(op)

async def list_push_subscriptions():
    def op(conn): return [_json_value(row["subscription"], {}) for row in conn.execute("SELECT subscription FROM push_subscriptions").fetchall()]
    return await _run_db(op)


async def save_monitoring_notifications(entries):
    """Monitoring bildirim geçmişini kalıcı kaydet (server-side scan loop'tan).

    entries: sözlük listesi — symbol, message, title, score, target_pct,
    price, expected_price, horizon_minutes, mode, detected_at, sent_via_push.
    """
    if not entries:
        return 0
    now = time.time()
    def op(conn):
        for e in entries:
            conn.execute(
                "INSERT INTO monitoring_notifications"
                "(symbol,message,title,score,target_pct,price,expected_price,horizon_minutes,mode,detected_at,sent_via_push,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(e.get("symbol") or "?"),
                    str(e.get("message") or ""),
                    str(e.get("title") or "") or None,
                    e.get("score"), e.get("target_pct"), e.get("price"), e.get("expected_price"),
                    e.get("horizon_minutes"), e.get("mode"),
                    float(e.get("detected_at") or now),
                    bool(e.get("sent_via_push", True)),
                    now,
                ),
            )
        conn.commit()
        return len(entries)
    return await _run_db(op)


async def list_monitoring_notifications(limit=50):
    """En son monitoring bildirimlerini döndür (yeni -> eski)."""
    def op(conn):
        rows = conn.execute(
            "SELECT id,symbol,message,title,score,target_pct,price,expected_price,"
            "horizon_minutes,mode,detected_at,sent_via_push FROM monitoring_notifications"
            " ORDER BY detected_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detected_at"] = _epoch_value(item.get("detected_at"))
            result.append(item)
        return result
    return await _run_db(op)


async def get_chart_settings(symbol):
    def op(conn):
        row = conn.execute("SELECT data FROM chart_settings WHERE symbol=?", (symbol,)).fetchone()
        return _json_value(row[0], None) if row else None

    return await _run_db(op)


async def save_chart_settings(symbol, data):
    def op(conn):
        conn.execute(
            "INSERT INTO chart_settings (symbol, data) VALUES (?, ?) ON CONFLICT(symbol) DO UPDATE SET data=?",
            (symbol, _json_safe_dumps(data), _json_safe_dumps(data))
        )
        conn.commit()

    await _run_db(op)


async def clear_all_chart_indicators():
    """Tüm sembollerin kayıtlı indikatör yerleşimlerini temizler (server-side toplu temizlik).

    Her chart_settings satırının data JSON'ından 'indicators' anahtarını düşer.
    Silinen indikatörler değil, yalnızca YERLEŞİM listesidir; sinyal/pozisyon
    verisi etkilenmez. Temizlenen satırlar önümüzdeki açılışta varsayılan
    SlingShot ile döner (frontend boş indicator -> default uygular).
    Dosya sayısı: satır sayısı döner.
    """
    def op(conn):
        if _postgres_enabled():
            # NOT: `data ? 'indicators'` kullanma — _PostgresCompat '?'->'%s'
            # çevirir, jsonb varlık operatörünü bozar. Fonksiyon formu güvenli.
            cur = conn.execute(
                "UPDATE chart_settings SET data = data - 'indicators' "
                "WHERE jsonb_exists(data, 'indicators')")
            conn.commit()
            return cur.rowcount
        # SQLite yedeği (JSON1 key kaldırma via json_remove)
        cur = conn.execute(
            "UPDATE chart_settings SET data = json_remove(data, '$.indicators') "
            "WHERE data LIKE '%indicators%'")
        conn.commit()
        return cur.rowcount

    return await _run_db(op)


async def save_backtest(result):
    """Backtest sonucunu kaydet, kayıt id'sini döndür."""
    def op(conn):
        sql = ("INSERT INTO backtests (timestamp, symbol, interval, strategy, params, days_back, "
            "initial_balance, final_balance, net_pnl, net_pnl_pct, total_trades, wins, losses, "
            "win_rate, max_drawdown_pct, order_size, stop_loss_pct, take_profit_pct, trailing_stop_pct, trades) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        params = (result.get("timestamp"), result.get("symbol"), result.get("interval"),
             result.get("strategy"), _json_safe_dumps(result.get("params", {})), result.get("days_back"),
             result.get("initial_balance"), result.get("final_balance"), result.get("net_pnl"),
             result.get("net_pnl_pct"), result.get("total_trades"), result.get("wins"),
             result.get("losses"), result.get("win_rate"), result.get("max_drawdown_pct"), result.get("order_size"),
             result.get("stop_loss_pct"), result.get("take_profit_pct"),
             result.get("trailing_stop_pct"), _json_safe_dumps(result.get("trades", [])))
        if _postgres_enabled():
            row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid

    return await _run_db(op)

async def upsert_market_candles(rows):
    """Persist normalized public 5m candles; duplicate timestamps are idempotent."""
    if not rows: return 0
    def op(conn):
        sql = """INSERT INTO historical_candles
            (symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,trade_count,source,fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET
            close_time=excluded.close_time,open=excluded.open,high=excluded.high,low=excluded.low,
            close=excluded.close,volume=excluded.volume,quote_volume=excluded.quote_volume,
            trade_count=excluded.trade_count,source=excluded.source,fetched_at=excluded.fetched_at"""
        conn.executemany(sql, [tuple(r.get(k) for k in ("symbol","timeframe","open_time","close_time","open","high","low","close","volume","quote_volume","trade_count","source","fetched_at")) for r in rows])
        conn.commit(); return len(rows)
    return await _run_db(op)

async def get_market_candles(symbol, timeframe="5m", start_ms=None, end_ms=None):
    def op(conn):
        q = "SELECT * FROM historical_candles WHERE symbol=? AND timeframe=?"; args=[symbol.upper(), timeframe]
        if start_ms is not None: q += " AND open_time>=?"; args.append(int(start_ms))
        if end_ms is not None: q += " AND open_time<=?"; args.append(int(end_ms))
        q += " ORDER BY open_time"
        return [dict(r) for r in conn.execute(q,args).fetchall()]
    return await _run_db(op)

async def get_market_symbols(timeframe="5m"):
    """Return the cached universe for a timeframe in deterministic order."""
    def op(conn):
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM historical_candles WHERE timeframe=? ORDER BY symbol",
            (timeframe,),
        ).fetchall()
        return [str(row["symbol"]).upper() for row in rows]
    return await _run_db(op)

async def upsert_market_feature_snapshots(rows):
    if not rows: return 0
    def op(conn):
        sql = """INSERT INTO historical_feature_snapshots
            (symbol,timeframe,open_time,captured_at,feature_version,payload,regime,regime_confidence,confluence_score,data_ready)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,timeframe,open_time,feature_version) DO UPDATE SET
            captured_at=excluded.captured_at,payload=excluded.payload,regime=excluded.regime,
            regime_confidence=excluded.regime_confidence,confluence_score=excluded.confluence_score,data_ready=excluded.data_ready"""
        values=[]
        for r in rows:
            values.append((r["symbol"].upper(),r["timeframe"],int(r["open_time"]),int(r["captured_at"]),r["feature_version"],_json_safe_dumps(r.get("payload",{}),default=str),r.get("regime"),r.get("regime_confidence"),r.get("confluence_score"),bool(r.get("data_ready",False))))
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)

async def get_market_feature_snapshots(symbol, timeframe="5m", start_ms=None, end_ms=None, feature_version=None):
    def op(conn):
        q="SELECT * FROM historical_feature_snapshots WHERE symbol=? AND timeframe=?"; args=[symbol.upper(),timeframe]
        if start_ms is not None: q+=" AND open_time>=?"; args.append(int(start_ms))
        if end_ms is not None: q+=" AND open_time<=?"; args.append(int(end_ms))
        if feature_version: q+=" AND feature_version=?"; args.append(feature_version)
        q+=" ORDER BY open_time"; out=[]
        for row in conn.execute(q,args).fetchall():
            item=dict(row); item["payload"]=_json_value(item.get("payload"),{}); out.append(item)
        return out
    return await _run_db(op)

async def get_backtests(limit=50):
    """Son backtest kayıtlarını getir (en yeni önce)."""
    def op(conn):
        rows = conn.execute(
            "SELECT * FROM backtests ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = _json_value(d.get("params"), {})
            d["trades"] = _json_value(d.get("trades"), [])
            out.append(d)
        return out

    return await _run_db(op)

async def save_research_run(result):
    def op(conn):
        sql = """INSERT INTO research_runs
            (created_at,run_type,scope,symbols,timeframes,parameters,result,status,paper_only)
            VALUES (?,?,?,?,?,?,?,?,?)"""
        params = (time.time(), result.get("run_type", "research"), result.get("scope", "active"),
                  _json_safe_dumps(result.get("symbols", [])), _json_safe_dumps(result.get("timeframes", [])),
                  _json_safe_dumps(result.get("parameters", {}), default=str), _json_safe_dumps(result.get("result", {}), default=str),
                  result.get("status", "completed"), 1)
        if _postgres_enabled():
            row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params); conn.commit(); return cur.lastrowid
    return await _run_db(op)

async def get_research_runs(limit=20, run_type=None):
    def op(conn):
        q = "SELECT * FROM research_runs"; args = []
        if run_type:
            q += " WHERE run_type=?"; args.append(run_type)
        q += " ORDER BY created_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 100)))
        out = []
        for row in conn.execute(q, args).fetchall():
            item = dict(row)
            for key in ("symbols", "timeframes", "parameters", "result"):
                item[key] = _json_value(item.get(key), [] if key in ("symbols", "timeframes") else {})
            out.append(item)
        return out
    return await _run_db(op)

async def save_research_pattern(item):
    def op(conn):
        now = time.time()
        sql = """INSERT INTO research_patterns
            (created_at,updated_at,name,description,symbols_scope,symbols,timeframes,definition,evidence,status,confidence,source_run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""
        params = (now, now, item["name"], item.get("description"), item.get("symbols_scope", "active"),
                  _json_safe_dumps(item.get("symbols", [])), _json_safe_dumps(item.get("timeframes", [])),
                  _json_safe_dumps(item.get("definition", {}), default=str), _json_safe_dumps(item.get("evidence", {}), default=str),
                  item.get("status", "candidate"), item.get("confidence", 0.3), item.get("source_run_id"))
        if _postgres_enabled():
            row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
        cur = conn.execute(sql, params); conn.commit(); return cur.lastrowid
    return await _run_db(op)

async def get_research_patterns(status=None, timeframe=None, limit=30):
    def op(conn):
        q = "SELECT * FROM research_patterns"; args = []; conditions = []
        if status:
            conditions.append("status=?"); args.append(status)
        if timeframe:
            conditions.append("timeframes LIKE ?"); args.append(f"%{timeframe}%")
        if conditions: q += " WHERE " + " AND ".join(conditions)
        q += " ORDER BY updated_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 100)))
        out = []
        for row in conn.execute(q, args).fetchall():
            item = dict(row)
            for key in ("symbols", "timeframes", "definition", "evidence"):
                item[key] = _json_value(item.get(key), [] if key in ("symbols", "timeframes") else {})
            out.append(item)
        return out
    return await _run_db(op)

async def delete_backtest(run_id):
    def op(conn):
        conn.execute("DELETE FROM backtests WHERE id=?", (run_id,))
        conn.commit()

    await _run_db(op)


async def prune_retention(days: int = 30, microstructure_days: int = 7):
    """Delete high-volume observability rows older than ``days`` days.

    microstructure_snapshots grows one row per fresh symbol per second and
    embedding_jobs keeps full JSONB documents; without a sweep both grow
    unbounded. Paper trades/signals/decision logs are never pruned here.
    microstructure_snapshots uses its own, tighter window (``microstructure_days``)
    and is deleted in batches so a large backlogs does not hold one long
    transaction. Returns per-table deleted row counts.
    """
    cutoff = time.time() - max(1, int(days)) * 86400
    micro_cutoff = time.time() - max(1, int(microstructure_days)) * 86400

    def op(conn):
        deleted = {}
        # Batched sweep: single DELETE on a 100M-row backlog holds a long
        # transaction and bloats WAL; 500k-row chunks commit incrementally.
        deleted["microstructure_snapshots"] = 0
        while True:
            try:
                cursor = conn.execute("""DELETE FROM microstructure_snapshots WHERE ctid IN (
                    SELECT ctid FROM microstructure_snapshots WHERE captured_at < %s LIMIT 500000)""",
                    (micro_cutoff,))
                conn.commit()
                batch = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            except Exception:
                conn.rollback()
                break
            deleted["microstructure_snapshots"] += batch
            if batch < 500000:
                break
        for table, column in (
            ("llm_tool_logs", "timestamp"),
            ("embedding_jobs", "created_at"),
            ("analysis_snapshots", "captured_at"),
            ("strategy_scan_logs", "timestamp"),
        ):
            try:
                cursor = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
                conn.commit()
                deleted[table] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            except Exception:
                # A missing table or a PG-compat quirk
                # must not abort the remaining sweeps.
                conn.rollback()
                deleted[table] = 0
        return deleted

    return await _run_db(op)


async def close_db():
    def op(conn):
        conn.commit()
        conn.close()

    await _run_db(op)
    global _PG_CONN
    _PG_CONN = None


# ---------------------------------------------------------------------------
# Users (username+password auth, 2026-09-03)
# ---------------------------------------------------------------------------
def _user_row(row) -> dict | None:
    if row is None:
        return None
    return {"id": int(row["id"]), "username": row["username"], "password_hash": row["password_hash"],
            "role": row["role"], "is_active": bool(row["is_active"]),
            "created_at": float(row["created_at"] or 0), "updated_at": float(row["updated_at"] or 0)}


async def get_user_by_username(username: str) -> dict | None:
    """Case-insensitive lookup: username stored lowercased."""
    def op(conn):
        row = conn.execute("SELECT * FROM users WHERE username=%s", (str(username or "").strip().lower(),)).fetchone()
        return _user_row(row)
    return await _run_db(op)


async def get_user_by_id(user_id: int) -> dict | None:
    def op(conn):
        row = conn.execute("SELECT * FROM users WHERE id=%s", (int(user_id),)).fetchone()
        return _user_row(row)
    return await _run_db(op)


async def list_users() -> list[dict]:
    def op(conn):
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        out = []
        for row in rows:
            u = _user_row(row)
            if u:
                u.pop("password_hash", None)
                out.append(u)
        return out
    return await _run_db(op)


async def create_user(username: str, password_hash: str, role: str = "user", is_active: bool = True) -> dict:
    now = time.time()
    def op(conn):
        cur = conn.execute(
            "INSERT INTO users(username,password_hash,role,is_active,created_at,updated_at) "
            "VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
            (str(username).strip().lower(), password_hash, str(role).lower(), bool(is_active), now, now))
        conn.commit()
        return _user_row(cur.fetchone())
    return await _run_db(op)


async def update_user(user_id: int, *, username: str | None = None, password_hash: str | None = None,
                      role: str | None = None, is_active: bool | None = None) -> dict | None:
    def op(conn):
        sets, values = [], []
        if username is not None:
            sets.append("username=%s"); values.append(str(username).strip().lower())
        if password_hash is not None:
            sets.append("password_hash=%s"); values.append(password_hash)
        if role is not None:
            sets.append("role=%s"); values.append(str(role).lower())
        if is_active is not None:
            sets.append("is_active=%s"); values.append(bool(is_active))
        if not sets:
            row = conn.execute("SELECT * FROM users WHERE id=%s", (int(user_id),)).fetchone()
            return _user_row(row)
        sets.append("updated_at=%s"); values.append(time.time())
        values.append(int(user_id))
        row = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(values)).fetchone()
        conn.commit()
        return _user_row(row)
    return await _run_db(op)


async def delete_user(user_id: int) -> bool:
    def op(conn):
        cur = conn.execute("DELETE FROM users WHERE id=%s", (int(user_id),))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


async def count_users() -> int:
    def op(conn):
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"]) if row else 0
    return await _run_db(op)


# ---------------------------------------------------------------------------
# Chart-page ML forecasts (2026-09-03)
# ---------------------------------------------------------------------------
def _chart_forecast_row(row) -> dict | None:
    if row is None:
        return None
    return {"id": int(row["id"]), "symbol": row["symbol"], "timeframe": row["timeframe"],
            "horizon_minutes": int(row["horizon_minutes"]), "entry_price": float(row["entry_price"] or 0),
            "target_pct": float(row["target_pct"] or 0), "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
            "hit_probability": float(row["hit_probability"]) if row["hit_probability"] is not None else None,
            "model": row.get("model"), "created_at": float(row["created_at"] or 0),
            "status": row["status"], "evaluated_at": float(row["evaluated_at"]) if row.get("evaluated_at") is not None else None,
            "outcome_price": float(row["outcome_price"]) if row.get("outcome_price") is not None else None,
            "outcome_return_pct": float(row["outcome_return_pct"]) if row.get("outcome_return_pct") is not None else None,
            "outcome_direction": row.get("outcome_direction"),
            "direction_correct": bool(row["direction_correct"]) if row.get("direction_correct") is not None else None,
            "max_favorable_pct": float(row["max_favorable_pct"]) if row.get("max_favorable_pct") is not None else None,
            "max_adverse_pct": float(row["max_adverse_pct"]) if row.get("max_adverse_pct") is not None else None,
            "outcome_details": row.get("outcome_details")}


async def save_chart_forecast(symbol, timeframe, horizon_minutes, entry_price, target_pct, target_price,
                              hit_probability=None, model=None) -> dict:
    now = time.time()
    def op(conn):
        row = conn.execute(
            "INSERT INTO chart_forecasts(symbol,timeframe,horizon_minutes,entry_price,target_pct,target_price,"
            "hit_probability,model,created_at,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING *",
            (str(symbol).upper(), str(timeframe), int(horizon_minutes), float(entry_price), float(target_pct),
             float(target_price) if target_price is not None else None,
             float(hit_probability) if hit_probability is not None else None, model, now)).fetchone()
        conn.commit()
        return _chart_forecast_row(row)
    return await _run_db(op)


async def get_recent_chart_forecast(symbol: str, timeframe: str, within_sec: float = 300) -> dict | None:
    """Son N saniye içinde üretilmiş tahmini döndürür (paylaşılan/cache'li tahmin)."""
    cutoff = time.time() - float(within_sec)
    def op(conn):
        row = conn.execute(
            "SELECT * FROM chart_forecasts WHERE symbol=%s AND timeframe=%s AND created_at>=%s "
            "ORDER BY created_at DESC LIMIT 1", (str(symbol).upper(), str(timeframe), cutoff)).fetchone()
        return _chart_forecast_row(row)
    return await _run_db(op)


async def list_chart_forecasts(symbol: str, limit: int = 50) -> list[dict]:
    def op(conn):
        rows = conn.execute(
            "SELECT * FROM chart_forecasts WHERE symbol=%s ORDER BY created_at DESC LIMIT %s",
            (str(symbol).upper(), int(limit))).fetchall()
        return [_chart_forecast_row(r) for r in rows if r is not None]
    return await _run_db(op)


async def list_chart_forecasts_paginated(symbol: str | None = None, limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict]:
    """Rapor sayfası için pagination'lı tahmin listesi."""
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=%s")
            values.append(str(symbol).upper())
        if status:
            clauses.append("status=%s")
            values.append(str(status))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        rows = conn.execute(
            f"SELECT * FROM chart_forecasts{where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            values).fetchall()
        return [_chart_forecast_row(r) for r in rows if r is not None]
    return await _run_db(op)


async def count_chart_forecasts(symbol: str | None = None, status: str | None = None) -> int:
    """Pagination için toplam kayıt sayısı."""
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=%s")
            values.append(str(symbol).upper())
        if status:
            clauses.append("status=%s")
            values.append(str(status))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        row = conn.execute(f"SELECT COUNT(*) FROM chart_forecasts{where}", values).fetchone()
        return int(row[0]) if row else 0
    return await _run_db(op)


async def list_chart_forecasts_all(limit: int = 500) -> list[dict]:
    def op(conn):
        rows = conn.execute(
            "SELECT * FROM chart_forecasts ORDER BY created_at DESC LIMIT %s",
            (int(limit),)).fetchall()
        return [_chart_forecast_row(r) for r in rows if r is not None]
    return await _run_db(op)


async def get_pending_chart_forecasts(limit: int = 200) -> list[dict]:
    now = time.time()
    def op(conn):
        rows = conn.execute(
            "SELECT * FROM chart_forecasts WHERE status='pending' AND created_at + (horizon_minutes*60) <= %s "
            "ORDER BY created_at LIMIT %s", (now, int(limit))).fetchall()
        return [_chart_forecast_row(r) for r in rows if r is not None]
    return await _run_db(op)


async def mark_chart_forecast_evaluated(forecast_id: int, outcome: dict) -> bool:
    def op(conn):
        cur = conn.execute(
            "UPDATE chart_forecasts SET status='evaluated', evaluated_at=%s, outcome_price=%s, outcome_return_pct=%s, "
            "outcome_direction=%s, direction_correct=%s, max_favorable_pct=%s, max_adverse_pct=%s, outcome_details=%s "
            "WHERE id=%s AND status='pending'",
            (outcome.get("evaluated_at"), outcome.get("outcome_price"), outcome.get("outcome_return_pct"),
             outcome.get("outcome_direction"), outcome.get("direction_correct"),
             outcome.get("max_favorable_pct"), outcome.get("max_adverse_pct"),
             _json_safe_dumps(outcome.get("outcome_details") or {}, ensure_ascii=False, default=str), int(forecast_id)))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


# ---------------------------------------------------------------------------
# Audit trail (2026-09-03): user-triggered actions with caller fingerprint.
# Autonomous bot loops are intentionally NOT recorded here (they persist in
# decision_logs/trades/monitoring_notifications already). Rows survive
# reset_trading_data; an admin-only DELETE prunes old history.
# ---------------------------------------------------------------------------
def _audit_row(row) -> dict | None:
    if row is None:
        return None
    return {"id": int(row["id"]), "actor_username": row["actor_username"], "actor_role": row["actor_role"],
            "category": row["category"], "action": row["action"], "target": row["target"],
            "details": row["details"] if row["details"] is not None else {},
            "ip": row["ip"], "user_agent": row["user_agent"], "accept_language": row["accept_language"],
            "created_at": float(row["created_at"] or 0)}


async def save_audit_log(actor_username: str | None, actor_role: str | None, category: str, action: str,
                         *, target: str | None = None, details: dict | None = None,
                         ip: str | None = None, user_agent: str | None = None,
                         accept_language: str | None = None) -> dict | None:
    """Append one audit row. Never raises transport/logic errors to the caller
    beyond the normal DB layer — callers should wrap with log_user_action."""
    now = time.time()
    def op(conn):
        row = conn.execute(
            "INSERT INTO audit_logs(actor_username,actor_role,category,action,target,details,ip,user_agent,"
            "accept_language,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            ((actor_username or "").strip() or None, (actor_role or "").strip().lower() or None,
             str(category).strip().lower() or "general", str(action).strip().upper() or "ACTION",
             (target or "").strip() or None,
             _json_safe_dumps(details or {}, ensure_ascii=False, default=str),
             (ip or "").strip()[:128] or None, (user_agent or "").strip()[:512] or None,
             (accept_language or "").strip()[:256] or None, now)).fetchone()
        conn.commit()
        return _audit_row(row)
    return await _run_db(op)


def _audit_filters(actor: str | None, category: str | None, action: str | None, q: str | None):
    """WHERE cümlesi + değerler; kullanıcı girdisi yalnız parametre olarak geçer."""
    clauses, values = [], []
    if (actor or "").strip():
        clauses.append("actor_username=%s"); values.append(str(actor).strip().lower())
    if (category or "").strip():
        clauses.append("category=%s"); values.append(str(category).strip().lower())
    if (action or "").strip():
        clauses.append("action=%s"); values.append(str(action).strip().upper())
    if (q or "").strip():
        needle = f"%{str(q).strip()}%"
        clauses.append("(actor_username ILIKE %s OR action ILIKE %s OR target ILIKE %s OR details::text ILIKE %s)")
        values.extend([needle, needle, needle, needle])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, values


async def list_audit_logs(limit: int = 100, offset: int = 0, *, actor: str | None = None,
                          category: str | None = None, action: str | None = None,
                          q: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where, values = _audit_filters(actor, category, action, q)
    def op(conn):
        rows = conn.execute(
            f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            tuple(values) + (limit, offset)).fetchall()
        return [_audit_row(r) for r in rows if r is not None]
    return await _run_db(op)


async def count_audit_logs(*, actor: str | None = None, category: str | None = None,
                           action: str | None = None, q: str | None = None) -> int:
    where, values = _audit_filters(actor, category, action, q)
    def op(conn):
        row = conn.execute(f"SELECT COUNT(*) AS n FROM audit_logs {where}", tuple(values)).fetchone()
        return int(row["n"]) if row else 0
    return await _run_db(op)


async def delete_audit_logs_before(before_ts: float) -> int:
    """Old audit rows silinir (admin temizliği). before_ts epoch saniyedir."""
    def op(conn):
        cur = conn.execute("DELETE FROM audit_logs WHERE created_at < %s", (float(before_ts),))
        conn.commit()
        return cur.rowcount
    return await _run_db(op)


# ---------------------------------------------------------------------------
# Sembol bazlı adaptif hedef öğrenme (2026-09-03): Her sembol için başarı/başarısız
# sayısı tutulur, hedef otomatik ayarlanır. ML tahmin + adaptif durum harmanlanır.
# ---------------------------------------------------------------------------
async def get_symbol_target_state(symbol: str) -> dict:
    """Sembol için adaptif hedef durumu döndürür (yoksa varsayılan oluşturur)."""
    sym = str(symbol or "").strip().upper()
    now = time.time()
    def op(conn):
        row = conn.execute("SELECT * FROM symbol_target_state WHERE symbol=%s", (sym,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO symbol_target_state(symbol,target_pct,horizon_minutes,success_count,fail_count,total_count,last_adjusted_at,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                         (sym, 2.0, 5, 0, 0, 0, now, now))
            conn.commit()
            return {"symbol": sym, "target_pct": 2.0, "horizon_minutes": 5, "success_count": 0, "fail_count": 0, "total_count": 0, "last_adjusted_at": now, "created_at": now}
        return {"symbol": sym, "target_pct": float(row["target_pct"] or 2.0), "horizon_minutes": int(row["horizon_minutes"] or 5),
                "success_count": int(row["success_count"] or 0), "fail_count": int(row["fail_count"] or 0),
                "total_count": int(row["total_count"] or 0), "last_adjusted_at": float(row["last_adjusted_at"] or 0), "created_at": float(row["created_at"] or 0)}
    return await _run_db(op)


async def record_symbol_target_outcome(symbol: str, success: bool, achieved_pct: float = 0.0) -> dict:
    """Sembol için bir tahmin sonucu kaydeder ve adaptif hedefi ayarlar.

    Başarılıysa hedefi yükseltmeye başla (daha iddialı), başarısızsa düşür.
    achieved_pct: gerçekleşen yükseliş yüzdesi (pozitif = hedefe yaklaşmış).
    """
    sym = str(symbol or "").strip().upper()
    now = time.time()
    state = await get_symbol_target_state(sym)
    success_count = int(state["success_count"]) + (1 if success else 0)
    fail_count = int(state["fail_count"]) + (0 if success else 1)
    total_count = success_count + fail_count
    current_target = float(state["target_pct"])
    current_horizon = int(state["horizon_minutes"])
    # Adaptif ayar: başarı oranı %60+ ise hedefi artır, %40- ise azalt
    success_rate = success_count / total_count if total_count > 0 else 0.5
    new_target = current_target
    new_horizon = current_horizon
    if total_count >= 3:
        if success_rate >= 0.6:
            new_target = min(10.0, current_target + 0.5)
            new_horizon = min(15, current_horizon + 5)
        elif success_rate <= 0.4:
            new_target = max(1.0, current_target - 0.5)
            new_horizon = max(5, current_horizon - 5)
    def op(conn):
        conn.execute("UPDATE symbol_target_state SET target_pct=%s, horizon_minutes=%s, success_count=%s, fail_count=%s, total_count=%s, last_adjusted_at=%s WHERE symbol=%s",
                     (new_target, new_horizon, success_count, fail_count, total_count, now, sym))
        conn.commit()
    await _run_db(op)
    return {"symbol": sym, "target_pct": new_target, "horizon_minutes": new_horizon, "success_count": success_count, "fail_count": fail_count, "total_count": total_count, "success_rate": round(success_rate, 3)}


async def get_all_symbol_target_states() -> list[dict]:
    """Tüm sembol hedef durumlarını döndürür (raporlama için)."""
    def op(conn):
        rows = conn.execute("SELECT * FROM symbol_target_state ORDER BY total_count DESC, symbol").fetchall()
        return [{"symbol": r["symbol"], "target_pct": float(r["target_pct"] or 2.0), "horizon_minutes": int(r["horizon_minutes"] or 5),
                 "success_count": int(r["success_count"] or 0), "fail_count": int(r["fail_count"] or 0),
                 "total_count": int(r["total_count"] or 0), "last_adjusted_at": float(r["last_adjusted_at"] or 0)} for r in rows]
    return await _run_db(op)
