import asyncio
import json
import os
import sqlite3
import threading
import time

from app.config import config

DB_NAME = os.getenv("SCALPER_DB_PATH", "scalper_db_v4.sqlite")
_DB_LOCK = threading.Lock()
_DB_CONN: sqlite3.Connection | None = None


def _get_connection() -> sqlite3.Connection:
    global _DB_CONN
    if _DB_CONN is None:
        _DB_CONN = sqlite3.connect(DB_NAME, check_same_thread=False)
        _DB_CONN.row_factory = sqlite3.Row
        _DB_CONN.execute("PRAGMA journal_mode=WAL")
        _DB_CONN.execute("PRAGMA busy_timeout=5000")
    return _DB_CONN


async def _run_db(operation):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _execute(operation))


def _execute(operation):
    with _DB_LOCK:
        conn = _get_connection()
        return operation(conn)


async def init_db():
    def op(conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY, side TEXT, entry_price REAL,
                stop_price REAL, take_profit REAL, peak_price REAL,
                breakeven_hit INTEGER, quantity REAL, entry_time REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, strategy TEXT, side TEXT,
                entry_price REAL, exit_price REAL, quantity REAL,
                pnl REAL, pnl_pct REAL, entry_time REAL, exit_time REAL
            )
        """)
        # eski trades tablosuna commission kolonu ekle (yoksa)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN commission REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # kolon zaten var
        # Kapanış nedeni eski veritabanlarında bulunmayabilir.
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN reason TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # kolon zaten var
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, symbol TEXT, action TEXT,
                price REAL, reason TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS virtual_wallet (
                asset TEXT PRIMARY KEY,
                amount REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chart_settings (
                symbol TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, symbol TEXT, interval TEXT, strategy TEXT,
                params TEXT, days_back INTEGER, initial_balance REAL,
                final_balance REAL, net_pnl REAL, net_pnl_pct REAL,
                total_trades INTEGER, wins INTEGER, losses INTEGER,
                win_rate REAL, order_size REAL, stop_loss_pct REAL,
                take_profit_pct REAL, trailing_stop_pct REAL,
                trades TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE backtests ADD COLUMN max_drawdown_pct REAL")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.execute("INSERT OR IGNORE INTO virtual_wallet (asset, amount) VALUES ('TRY', ?)", (config.INITIAL_BALANCE_TRY,))
        conn.commit()
        # eski tabloya kolon ekle (yoksa)
        for col in ("entry_time REAL", "strategy TEXT"):
            try:
                conn.execute(f"ALTER TABLE positions ADD COLUMN {col}")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # kolon zaten var

        _migrate_old_trades(conn)
        _backfill_commission(conn)
        _backfill_position_strategy(conn)
        _recalculate_wallet(conn)
        conn.commit()

    await _run_db(op)

def _backfill_position_strategy(conn: sqlite3.Connection):
    """strategy NULL olan açık pozisyonlara UT ata (eski kayıtlar)."""
    conn.execute("UPDATE positions SET strategy='UT' WHERE strategy IS NULL")

def _recalculate_wallet(conn: sqlite3.Connection):
    """TRY bakiyesini trades + açık pozisyonlardan yeniden hesapla (komisyon dahil)."""
    start = config.INITIAL_BALANCE_TRY
    spent = conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM trades").fetchone()[0]
    comm = conn.execute("SELECT COALESCE(SUM(commission),0) FROM trades").fetchone()[0]
    received = conn.execute("SELECT COALESCE(SUM(exit_price*quantity),0) FROM trades").fetchone()[0]
    open_cost = conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0]
    try_balance = start - spent - comm + received - open_cost
    conn.execute("UPDATE virtual_wallet SET amount=? WHERE asset='TRY'", (try_balance,))

def _backfill_commission(conn: sqlite3.Connection):
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

def _migrate_old_trades(conn: sqlite3.Connection):
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
    """Tüm eski trade kayıtlarını sil, cüzdanı sıfırla (uygulama reseti)."""
    def op(conn: sqlite3.Connection):
        conn.execute("DELETE FROM positions")
        conn.execute("DELETE FROM signals")
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM virtual_wallet")
        conn.execute("INSERT INTO virtual_wallet (asset, amount) VALUES ('TRY', ?)", (config.INITIAL_BALANCE_TRY,))
        conn.commit()

    await _run_db(op)

async def get_wallet_balance(asset="USDT"):
    def op(conn: sqlite3.Connection):
        row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?", (asset,)).fetchone()
        return row[0] if row else 0.0

    return await _run_db(op)


async def update_wallet_balance(asset, amount):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO virtual_wallet (asset, amount) VALUES (?, ?) ON CONFLICT(asset) DO UPDATE SET amount=?",
            (asset, amount, amount)
        )
        conn.commit()

    await _run_db(op)


async def load_positions():
    def op(conn: sqlite3.Connection):
        positions = {}
        rows = conn.execute("SELECT * FROM positions").fetchall()
        for row in rows:
            positions[row[0]] = {
                "side": row[1], "entry_price": row[2], "stop_price": row[3],
                "take_profit": row[4], "peak_price": row[5], "breakeven_hit": bool(row[6]),
                "quantity": row[7], "entry_time": row[8] if len(row) > 8 else None,
                "strategy": row[9] if len(row) > 9 else None
            }
        return positions

    return await _run_db(op)


async def save_position(symbol, pos):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT OR REPLACE INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, pos["side"], pos["entry_price"], pos.get("stop_price"),
             pos.get("take_profit"), pos.get("peak_price", pos["entry_price"]), int(pos.get("breakeven_hit", False)), pos["quantity"],
             pos.get("entry_time"), pos.get("strategy"))
        )
        conn.commit()

    await _run_db(op)

async def save_trade(trade):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO trades (symbol, strategy, side, entry_price, exit_price, quantity, pnl, pnl_pct, entry_time, exit_time, commission, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade.get("symbol"), trade.get("strategy"), trade.get("side"),
             trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"),
             trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"),
            trade.get("commission"), trade.get("reason"))
        )
        conn.commit()

    await _run_db(op)

async def get_trades():
    def op(conn: sqlite3.Connection):
        rows = conn.execute("SELECT * FROM trades ORDER BY exit_time DESC").fetchall()
        return [dict(r) for r in rows]

    return await _run_db(op)


async def delete_position(symbol):
    def op(conn: sqlite3.Connection):
        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        conn.commit()

    await _run_db(op)


async def save_signal(sig):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO signals (timestamp, symbol, action, price, reason) VALUES (?, ?, ?, ?, ?)",
            (sig.get("timestamp"), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"))
        )
        conn.commit()

    await _run_db(op)


async def get_chart_settings(symbol):
    def op(conn: sqlite3.Connection):
        row = conn.execute("SELECT data FROM chart_settings WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row[0]) if row else None

    return await _run_db(op)


async def save_chart_settings(symbol, data):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO chart_settings (symbol, data) VALUES (?, ?) ON CONFLICT(symbol) DO UPDATE SET data=?",
            (symbol, json.dumps(data), json.dumps(data))
        )
        conn.commit()

    await _run_db(op)

async def save_backtest(result):
    """Backtest sonucunu kaydet, kayıt id'sini döndür."""
    def op(conn: sqlite3.Connection):
        cur = conn.execute(
            "INSERT INTO backtests (timestamp, symbol, interval, strategy, params, days_back, "
            "initial_balance, final_balance, net_pnl, net_pnl_pct, total_trades, wins, losses, "
            "win_rate, max_drawdown_pct, order_size, stop_loss_pct, take_profit_pct, trailing_stop_pct, trades) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result.get("timestamp"), result.get("symbol"), result.get("interval"),
             result.get("strategy"), json.dumps(result.get("params", {})), result.get("days_back"),
             result.get("initial_balance"), result.get("final_balance"), result.get("net_pnl"),
             result.get("net_pnl_pct"), result.get("total_trades"), result.get("wins"),
             result.get("losses"), result.get("win_rate"), result.get("max_drawdown_pct"), result.get("order_size"),
             result.get("stop_loss_pct"), result.get("take_profit_pct"),
             result.get("trailing_stop_pct"), json.dumps(result.get("trades", [])))
        )
        conn.commit()
        return cur.lastrowid

    return await _run_db(op)

async def get_backtests(limit=50):
    """Son backtest kayıtlarını getir (en yeni önce)."""
    def op(conn: sqlite3.Connection):
        rows = conn.execute(
            "SELECT * FROM backtests ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if d["params"] else {}
            d["trades"] = json.loads(d["trades"]) if d["trades"] else []
            out.append(d)
        return out

    return await _run_db(op)

async def delete_backtest(run_id):
    def op(conn: sqlite3.Connection):
        conn.execute("DELETE FROM backtests WHERE id=?", (run_id,))
        conn.commit()

    await _run_db(op)


async def close_db():
    def op(conn: sqlite3.Connection):
        conn.commit()
        conn.close()

    await _run_db(op)
    global _DB_CONN
    _DB_CONN = None
