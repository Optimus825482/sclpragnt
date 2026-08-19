import asyncio
import json
import os
import sqlite3
import threading
import time
import tempfile
import re
from datetime import datetime, timezone

from app.config import config

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.abspath(os.path.join(_APP_DIR, "..", "scalper_db_v4.sqlite"))
_CONFIGURED_DB_PATH = os.getenv("SCALPER_DB_PATH", "").strip()
DB_NAME = os.path.abspath(_CONFIGURED_DB_PATH) if _CONFIGURED_DB_PATH else _DEFAULT_DB_PATH
_DB_LOCK = threading.Lock()
_DB_CONN: sqlite3.Connection | None = None
_PG_CONN = None

DEFAULT_SCALPER_SKILL_NAME = "Scalper Trade Manager"
DEFAULT_SCALPER_SKILL_INSTRUCTIONS = (
    "Paper-only scalper trade manager. Build a symbol-specific setup from 5m, 15m and 1h data; "
    "require trend/regime alignment, liquidity, spread/order-flow and cost-aware net edge before entry. "
    "Do not chase overbought resistance or reopen after a close without cooldown, fresh setup and required "
    "price rearm. Treat BUY_BLOCKED as no trade, and learn only from validated multi-trade out-of-sample "
    "evidence; never invent data or place real orders."
)

def _json_value(value, fallback):
    if value in (None, ""): return fallback
    if isinstance(value, (dict, list)): return value
    try: return json.loads(value)
    except (TypeError, json.JSONDecodeError): return fallback

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

def _postgres_enabled(): return os.getenv("DB_BACKEND", "postgres").lower() == "postgres"

def _db_timestamp():
    return datetime.now(timezone.utc) if _postgres_enabled() else time.time()

def _epoch_value(value):
    if isinstance(value, datetime):
        return value.timestamp()
    return value

def _db_datetime_value(value):
    """Convert Unix expiry values to PostgreSQL timestamps when needed."""
    if value in (None, "") or not _postgres_enabled():
        return value
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return value


def _get_connection() -> sqlite3.Connection:
    global _DB_CONN
    if _postgres_enabled():
        global _PG_CONN
        if _PG_CONN is None:
            try:
                import psycopg
                _PG_CONN = _PostgresCompat(psycopg.connect(os.environ["DATABASE_URL"], row_factory=_hybrid_row_factory))
            except Exception as exc:
                raise RuntimeError(f"PostgreSQL bağlantısı kurulamadı: {exc}") from exc
        return _PG_CONN
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
        try:
            return operation(conn)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


async def init_db():
    if _postgres_enabled():
        def pg_op(conn):
            schema_path = os.path.abspath(os.path.join(_APP_DIR, "..", "migrations", "001_pgvector_schema.sql"))
            with open(schema_path, encoding="utf-8") as schema_file:
                conn.conn.execute(schema_file.read())
            # Reconcile migrated cash with trades and open positions. The
            # SQLite wallet snapshot can predate the final position snapshot;
            # using it directly would double-count open position capital.
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
        return
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
        for col in ("entry_context TEXT", "max_favorable_pct REAL", "max_adverse_pct REAL", "hold_seconds REAL", "trade_id TEXT"):
            try:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col}")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        # Kapanış nedeni eski veritabanlarında bulunmayabilir.
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN reason TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # kolon zaten var
        try:
            conn.execute("ALTER TABLE positions ADD COLUMN trade_id TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, symbol TEXT, action TEXT,
                price REAL, reason TEXT, strategy TEXT, trade_id TEXT
            )
        """)
        for col in ("strategy TEXT", "trade_id TEXT"):
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                symbol TEXT, strategy TEXT, decision TEXT,
                reason TEXT, price REAL, metadata TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_tool_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                scope TEXT, tool_name TEXT, arguments TEXT,
                result_summary TEXT, duration_ms REAL, success INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS a2a_messages (
                message_id TEXT PRIMARY KEY, correlation_id TEXT, direction TEXT NOT NULL,
                message_type TEXT NOT NULL, sender TEXT, recipient TEXT, status TEXT NOT NULL DEFAULT 'queued',
                payload TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL, acknowledged_at REAL,
                last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_symbol_strategy ON trades(exit_time DESC, symbol, strategy)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_time_symbol_action ON signals(timestamp DESC, symbol, action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_time_symbol_strategy ON decision_logs(timestamp DESC, symbol, strategy)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_symbol_guards (
                symbol TEXT PRIMARY KEY, guard_type TEXT NOT NULL DEFAULT 'cooldown',
                status TEXT NOT NULL DEFAULT 'active', blocked_until REAL,
                reason TEXT, evidence TEXT, revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL DEFAULT '5m',
                rule_type TEXT NOT NULL DEFAULT 'price', operator TEXT NOT NULL,
                threshold REAL NOT NULL, cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
                enabled INTEGER NOT NULL DEFAULT 1, armed INTEGER NOT NULL DEFAULT 1, last_triggered_at REAL,
                last_value REAL, rearm_threshold REAL, expires_at REAL,
            notify_channels TEXT NOT NULL DEFAULT '["websocket"]',
                created_by TEXT NOT NULL DEFAULT 'user', reason TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id INTEGER NOT NULL,
                symbol TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE,
                value REAL, message TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'info',
                triggered_at REAL NOT NULL, acknowledged_at REAL,
                FOREIGN KEY(rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
            )
        """)
        try:
            conn.execute("ALTER TABLE alert_rules ADD COLUMN armed INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT, channel_type TEXT NOT NULL,
                destination TEXT NOT NULL, secret_ref TEXT, enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, UNIQUE(channel_type, destination)
            )
        """)
        conn.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT NOT NULL UNIQUE,
            subscription TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
                order_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
                order_value_try REAL, price REAL, limit_price REAL, stop_price REAL,
                take_profit_price REAL, stop_loss_pct REAL, take_profit_pct REAL,
                max_hold_seconds INTEGER, oco_group TEXT, reference_price REAL,
                client_request_id TEXT UNIQUE, trace_id TEXT, payload TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL, filled_at REAL, cancelled_at REAL
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
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, base_url TEXT NOT NULL,
            api_key_encrypted TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id INTEGER NOT NULL, name TEXT NOT NULL,
            temperature REAL NOT NULL DEFAULT 0.2, model_type TEXT NOT NULL DEFAULT 'chat',
            dimensions INTEGER, embedding_metric TEXT NOT NULL DEFAULT 'cosine',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, FOREIGN KEY(provider_id) REFERENCES llm_providers(id) ON DELETE CASCADE
        )""")
        for col in ("model_type TEXT NOT NULL DEFAULT 'chat'", "dimensions INTEGER", "embedding_metric TEXT NOT NULL DEFAULT 'cosine'"):
            try: conn.execute(f"ALTER TABLE llm_models ADD COLUMN {col}"); conn.commit()
            except sqlite3.OperationalError: pass
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, instructions TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")
        default_skills = [
            ("Scalping Teknik Analiz", "Evaluate trend, momentum, volatility, volume and liquidity as separate dimensions. Prefer confirmed multi-timeframe alignment over one indicator."),
            ("Maliyet ve Net PnL", "Always distinguish gross move, entry fee, exit fee, slippage and net PnL. Never call a trade profitable when supplied net PnL is non-positive."),
            ("Veri Güvenilirliği", "Treat null, zero or stale spread/depth/volume as missing data. Do not invent values; explicitly state confidence and data limitations."),
            ("Paper Trading Risk", "This is public-data paper trading. Never place orders, recommend bypassing risk filters, or override hard stop, liquidity, timeout or position-limit rules."),
            ("Trend ve Rejim", "Classify trend using EMA structure, ADX and multi-timeframe agreement. Separate trend, range and transition regimes; do not infer a trend from one indicator."),
            ("Osilatör ve Formasyon", "Interpret RSI, Stochastic, CCI, MACD, Williams %R, candle patterns and channels together. Treat overbought or oversold as context, not an automatic reversal signal."),
            ("Destek Direnç ve Pivot", "Use classic and Fibonacci pivots, Bollinger, Donchian and Keltner levels as context. Distinguish a level from a confirmed break and state timeframe."),
            ("Scalping Karar Raporu", "Return concise sections: market regime, bullish evidence, bearish evidence, liquidity and volatility risks, missing data, confidence, and paper-trading scenarios. Never invent a price target."),
            ("Canlı Sembol Tarama ve Trend Adayı", "Önce tüm etkin semboller için scan_market_snapshots aracını kullan. EMA hizalaması, ADX/DI, çoklu timeframe momentum, VWAP, hacim, spread, derinlik, ATR ve rejimi birlikte değerlendir. Yukarı adayları deep_analyze_symbol ile derinleştir; trend fazı ve süresini yalnızca mevcut mum zaman damgalarından çıkar, yoksa bilinmiyor de. Sonucu Türkçe ve paper_candidate=watch/candidate/avoid alanlarıyla ver; gerçek emir açma ve değer uydurma."),
            ("Desen Araştırma ve Doğrulama", "İstenen sembol evreni ve timeframe'lerde pattern research araçlarını kullan. Önce causal candle/features ile aday deseni tanımla; sonra kronolojik replay/backtest, walk-forward/OOS, holdout, forward ve maliyet stresini ayrı değerlendir. Tek bir geçmiş backtesti kanıt sayma. Yalnızca yeterli örneklem, ücret dahil net sonuç ve OOS/forward tutarlılığı varsa deseni validated olarak araştırma hafızasına kaydet; bu hafıza canlı stratejiyi otomatik değiştirmez. Pattern scan geleceği yalnızca etiket olarak kullanır, giriş özelliğine sızdırma yapma."),
            (DEFAULT_SCALPER_SKILL_NAME, DEFAULT_SCALPER_SKILL_INSTRUCTIONS),
        ]
        conn.executemany("INSERT OR IGNORE INTO llm_skills(name,instructions,enabled,created_at) VALUES(?,?,1,?)", [(n,i,time.time()) for n,i in default_skills])
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
        conn.execute("CREATE TABLE IF NOT EXISTS analysis_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, captured_at REAL NOT NULL, source TEXT NOT NULL DEFAULT 'entry', methodology_version TEXT, regime TEXT, regime_confidence REAL, confluence_score REAL, payload TEXT NOT NULL DEFAULT '{}', trade_id TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_symbol_time ON analysis_snapshots(symbol, captured_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_forecasts (
            forecast_id TEXT PRIMARY KEY, forecast_group_id TEXT NOT NULL,
            symbol TEXT NOT NULL, created_at REAL NOT NULL, horizon_minutes INTEGER NOT NULL,
            entry_price REAL NOT NULL, direction TEXT NOT NULL, confidence REAL NOT NULL,
            invalidation_price REAL, min_move_pct REAL NOT NULL,
            regime TEXT, timeframe_context TEXT NOT NULL DEFAULT '{}',
            scenario TEXT NOT NULL, counter_scenario TEXT, summary TEXT,
            model TEXT, prompt_version TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
            snapshot TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending',
            evaluated_at REAL, outcome_price REAL, outcome_return_pct REAL,
            outcome_direction TEXT, direction_correct INTEGER, max_favorable_pct REAL,
            max_adverse_pct REAL, outcome_details TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_forecasts_due ON llm_forecasts(status, created_at, horizon_minutes)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_forecasts_symbol_time ON llm_forecasts(symbol, created_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_forecast_lessons (
            lesson_key TEXT PRIMARY KEY, symbol TEXT, horizon_minutes INTEGER NOT NULL,
            regime TEXT, direction TEXT, sample_size INTEGER NOT NULL,
            in_sample_accuracy REAL, holdout_accuracy REAL, confidence_calibration_error REAL,
            lesson TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'candidate', generated_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_forecast_lessons_lookup ON llm_forecast_lessons(status, symbol, horizon_minutes)")
        conn.execute("CREATE TABLE IF NOT EXISTS microstructure_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, captured_at REAL NOT NULL, bid_price REAL, ask_price REAL, bid_qty REAL, ask_qty REAL, spread_pct REAL, depth_try REAL, orderflow_imbalance REAL, source TEXT NOT NULL DEFAULT 'binance_tr_public_ws', updated_at REAL, UNIQUE(symbol, captured_at))")
        conn.execute("CREATE INDEX IF NOT EXISTS microstructure_snapshots_lookup_idx ON microstructure_snapshots(symbol, captured_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS historical_candles (
            symbol TEXT NOT NULL, timeframe TEXT NOT NULL, open_time INTEGER NOT NULL,
            close_time INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
            close REAL NOT NULL, volume REAL NOT NULL, quote_volume REAL, trade_count INTEGER,
            source TEXT NOT NULL DEFAULT 'binance_tr_public', fetched_at REAL NOT NULL,
            PRIMARY KEY(symbol, timeframe, open_time))""")
        conn.execute("CREATE INDEX IF NOT EXISTS historical_candles_lookup_idx ON historical_candles(symbol, timeframe, open_time)")
        conn.execute("""CREATE TABLE IF NOT EXISTS historical_feature_snapshots (
            symbol TEXT NOT NULL, timeframe TEXT NOT NULL, open_time INTEGER NOT NULL,
            captured_at INTEGER NOT NULL, feature_version TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
            regime TEXT, regime_confidence REAL, confluence_score REAL, data_ready INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(symbol, timeframe, open_time, feature_version))""")
        conn.execute("CREATE INDEX IF NOT EXISTS historical_features_lookup_idx ON historical_feature_snapshots(symbol, timeframe, open_time)")
        conn.execute("""CREATE TABLE IF NOT EXISTS research_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, run_type TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'active', symbols TEXT NOT NULL DEFAULT '[]', timeframes TEXT NOT NULL DEFAULT '[]',
            parameters TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'completed', paper_only INTEGER NOT NULL DEFAULT 1
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS research_runs_recent_idx ON research_runs(created_at DESC, run_type)")
        conn.execute("""CREATE TABLE IF NOT EXISTS research_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            name TEXT NOT NULL, description TEXT, symbols_scope TEXT NOT NULL DEFAULT 'active', symbols TEXT NOT NULL DEFAULT '[]',
            timeframes TEXT NOT NULL DEFAULT '[]', definition TEXT NOT NULL DEFAULT '{}', evidence TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'candidate', confidence REAL NOT NULL DEFAULT 0.3, source_run_id INTEGER
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS research_patterns_status_idx ON research_patterns(status, updated_at DESC)")
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
        try:
            conn.execute("ALTER TABLE positions ADD COLUMN entry_context TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        _migrate_old_trades(conn)
        _backfill_commission(conn)
        _backfill_position_strategy(conn)
        _recalculate_wallet(conn)
        conn.commit()

    await _run_db(op)

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
    open_entry_commission = open_cost * config.COMMISSION_PCT
    try_balance = start - spent - comm + received - open_cost - open_entry_commission
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
    """Eski paper-trading/strateji geçmişini temizle ve cüzdanı sıfırla.

    Strateji, sembol ve LLM ayarları korunur. Tarihsel piyasa cache'i de
    silinmez; böylece yeni strateji hemen aynı veriyle çalışabilir.
    """
    def op(conn: sqlite3.Connection):
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
            cursor = conn.execute(f"DELETE FROM {table}")
            deleted[table] = cursor.rowcount
        conn.execute("DELETE FROM virtual_wallet")
        conn.execute("INSERT INTO virtual_wallet (asset, amount) VALUES ('TRY', ?)", (config.INITIAL_BALANCE_TRY,))
        conn.commit()
        deleted["virtual_wallet"] = 1
        return deleted

    return await _run_db(op)

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
    def op(conn: sqlite3.Connection):
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
    def op(conn: sqlite3.Connection):
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
             pos.get("entry_time"), pos.get("strategy"), json.dumps(_position_entry_context(pos)), pos.get("trade_id"))
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
             order.get("client_request_id"),order.get("trace_id"),json.dumps(order, ensure_ascii=False, default=str),order.get("created_at",now),now,order.get("filled_at"),order.get("cancelled_at")))
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
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO trades (symbol, strategy, side, entry_price, exit_price, quantity, pnl, pnl_pct, entry_time, exit_time, commission, reason, entry_context, max_favorable_pct, max_adverse_pct, hold_seconds, trade_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade.get("symbol"), trade.get("strategy"), trade.get("side"),
             trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"),
             trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"),
            trade.get("commission"), trade.get("reason"), json.dumps(trade.get("entry_context", {})),
            trade.get("max_favorable_pct"), trade.get("max_adverse_pct"), trade.get("hold_seconds"), trade.get("trade_id"))
        )
        conn.commit()

    await _run_db(op)

async def get_trades(limit: int | None = 100, offset: int = 0, symbol: str | None = None, strategy: str | None = None):
    def op(conn: sqlite3.Connection):
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
        "recent": locks[:30],
    }


async def apply_historical_mtf_backfill(target_type, target_id, symbol, trade_id, entry_context, snapshots):
    """Persist public-history MTF evidence without changing trade economics."""
    context_json = json.dumps(entry_context or {}, ensure_ascii=False, default=str)
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
            conn.execute("INSERT INTO analysis_snapshots(symbol,timeframe,captured_at,source,methodology_version,regime,regime_confidence,confluence_score,payload,trade_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(symbol).upper(), timeframe, float(snapshot.get("observation_timestamp") or time.time()), "historical_backfill", methods.get("methodology_version"), regime.get("name"), regime.get("confidence"), confluence.get("score"), json.dumps(snapshot, ensure_ascii=False, default=str), trade_id))
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
    def op(conn: sqlite3.Connection):
        row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS pnl FROM trades").fetchone()
        return float(row["pnl"] or 0.0)

    return await _run_db(op)

async def create_backup_file():
    """Create a consistent SQLite snapshot for download while the bot is running."""
    def op(conn: sqlite3.Connection):
        fd, path = tempfile.mkstemp(prefix="scalperagent-backup-", suffix=".sqlite")
        os.close(fd)
        backup_conn = sqlite3.connect(path)
        try:
            conn.backup(backup_conn)
            backup_conn.commit()
        finally:
            backup_conn.close()
        return path

    return await _run_db(op)


async def delete_position(symbol):
    def op(conn: sqlite3.Connection):
        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        conn.commit()

    await _run_db(op)


async def save_signal(sig):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO signals (timestamp, symbol, action, price, reason, strategy, trade_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig.get("timestamp"), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"), sig.get("strategy"), sig.get("trade_id"))
        )
        conn.execute(
            "INSERT INTO decision_logs (timestamp, symbol, strategy, decision, reason, price, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("strategy"),
             sig.get("action"), sig.get("reason"), sig.get("price"), json.dumps(sig, default=str))
        )
        conn.commit()
    await _run_db(op)
    try:
        from app.embedding_worker import worker, signal_document
        await worker.enqueue_persistent(signal_document(sig))
    except Exception:
        pass


async def save_decision_log(decision):
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO decision_logs (timestamp,symbol,strategy,decision,reason,price,metadata) VALUES (?,?,?,?,?,?,?)",
            (decision.get("timestamp") or time.time(), decision.get("symbol"), decision.get("strategy"),
             decision.get("decision"), decision.get("reason"), decision.get("price"),
             json.dumps(decision.get("metadata") or {}, ensure_ascii=False, default=str)),
        )
        conn.commit()
    await _run_db(op)

async def commit_open_position(symbol, asset, cash_amount, asset_amount, pos, sig):
    """Atomically persist wallet balances, position and opening decision."""
    def op(conn):
        if _postgres_enabled():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("paper_portfolio_open",))
        existing = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + (" FOR UPDATE" if _postgres_enabled() else ""), (symbol,)).fetchone()
        if not existing:
            open_count = int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] or 0)
            if int(config.MAX_OPEN_POSITIONS) > 0 and open_count >= int(config.MAX_OPEN_POSITIONS):
                raise RuntimeError("max_open_positions_reached")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + (" FOR UPDATE" if _postgres_enabled() else ""), ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else config.INITIAL_BALANCE_TRY)
        debit = float(asset_amount or 0) * float(sig.get("price") or pos.get("entry_price") or 0) * (1 + config.COMMISSION_PCT)
        if debit <= 0 or current_cash + 1e-9 < debit:
            raise RuntimeError("insufficient_paper_balance")
        next_cash = current_cash - debit
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", next_cash))
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=virtual_wallet.amount+excluded.amount", (asset, asset_amount))
        conn.execute("INSERT OR REPLACE INTO positions (symbol,side,entry_price,stop_price,take_profit,peak_price,breakeven_hit,quantity,entry_time,strategy,entry_context,trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (symbol, pos.get("side"), pos.get("entry_price"), pos.get("stop_price"), pos.get("take_profit"), pos.get("max_price", pos.get("entry_price")), bool(pos.get("breakeven_hit", False)), pos.get("quantity"), pos.get("entry_time"), pos.get("strategy"), json.dumps(_position_entry_context(pos)), pos.get("trade_id")))
        persisted = conn.execute("SELECT quantity,entry_time FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if not persisted or float(persisted[0] or 0) != float(pos.get("quantity") or 0) or float(persisted[1] or 0) != float(pos.get("entry_time") or 0):
            raise RuntimeError("Açılan pozisyon kaydı doğrulanamadı; transaction geri alınacak")
        conn.execute("INSERT INTO signals(timestamp,symbol,action,price,reason,strategy,trade_id) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("action"), sig.get("price"), sig.get("reason"), sig.get("strategy"), sig.get("trade_id")))
        conn.execute("INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), sig.get("strategy"), sig.get("action"), sig.get("reason"), sig.get("price"), json.dumps(sig, default=str)))
        technical = (pos.get("entry_context") or {}).get("technical") or {}
        snapshots = dict(technical.get("mtf_snapshots") or {})
        primary_timeframe = technical.get("timeframe") or "5m"
        snapshots.setdefault(primary_timeframe, technical)
        for timeframe, snapshot in snapshots.items():
            methods = snapshot.get("methodologies") or {}
            regime = methods.get("regime") or {}
            confluence = methods.get("confluence") or {}
            conn.execute("INSERT INTO analysis_snapshots(symbol,timeframe,captured_at,source,methodology_version,regime,regime_confidence,confluence_score,payload,trade_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (symbol, timeframe, pos.get("entry_time") or time.time(), "entry", methods.get("methodology_version"), regime.get("name"), regime.get("confidence"), confluence.get("score"), json.dumps(snapshot, default=str), pos.get("trade_id")))
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
        position_row = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + (" FOR UPDATE" if _postgres_enabled() else ""), (symbol,)).fetchone()
        if not position_row:
            raise RuntimeError("paper_position_not_found")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + (" FOR UPDATE" if _postgres_enabled() else ""), ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else 0.0)
        exit_notional = float(trade.get("exit_price") or 0) * float(trade.get("quantity") or 0)
        next_cash = current_cash + exit_notional * (1 - config.COMMISSION_PCT)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", next_cash))
        position_qty = float(position_row[0] or 0)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,0.0) ON CONFLICT(asset) DO NOTHING", (asset,))
        conn.execute("UPDATE virtual_wallet SET amount=amount-? WHERE asset=?", (position_qty, asset))
        conn.execute("INSERT INTO trades (symbol,strategy,side,entry_price,exit_price,quantity,pnl,pnl_pct,entry_time,exit_time,commission,reason,entry_context,max_favorable_pct,max_adverse_pct,hold_seconds,trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (trade.get("symbol"), trade.get("strategy"), trade.get("side"), trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"), trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"), trade.get("commission"), trade.get("reason"), json.dumps(trade.get("entry_context", {})), trade.get("max_favorable_pct"), trade.get("max_adverse_pct"), trade.get("hold_seconds"), trade.get("trade_id")))
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
        conn.execute("INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)", (sig.get("timestamp") or time.time(), sig.get("symbol"), trade.get("strategy"), sig.get("action"), sig.get("reason"), sig.get("price"), json.dumps(sig, default=str)))
        conn.commit()
    await _run_db(op)
    try:
        from app.embedding_worker import worker, trade_document
        await worker.enqueue_persistent(trade_document("exit", symbol, trade, sig))
    except Exception: pass


async def get_signals(limit: int = 100, offset: int = 0, symbol: str | None = None, action: str | None = None, strategy: str | None = None):
    def op(conn: sqlite3.Connection):
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
    def op(conn: sqlite3.Connection):
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
                json.dumps(row.get("timeframe_context") or {}, ensure_ascii=False, default=str),
                row.get("scenario") or "", row.get("counter_scenario"), row.get("summary"), row.get("model"),
                row.get("prompt_version") or "forecast-v1", row["snapshot_hash"],
                json.dumps(row.get("snapshot") or {}, ensure_ascii=False, default=str), "pending"))
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
        conn.execute("""UPDATE llm_forecasts SET status='evaluated', evaluated_at=?, outcome_price=?,
            outcome_return_pct=?, outcome_direction=?, direction_correct=?, max_favorable_pct=?,
            max_adverse_pct=?, outcome_details=? WHERE forecast_id=? AND status='pending'""",
            (float(outcome["evaluated_at"]), outcome.get("outcome_price"), outcome.get("outcome_return_pct"),
             outcome.get("outcome_direction"), bool(outcome.get("direction_correct")),
             outcome.get("max_favorable_pct"), outcome.get("max_adverse_pct"),
             json.dumps(outcome.get("details") or {}, ensure_ascii=False, default=str), forecast_id))
        changed = conn.execute("SELECT changes()").fetchone()[0] if not _postgres_enabled() else conn.execute("SELECT 1").fetchone()[0]
        conn.commit(); return bool(changed)
    return await _run_db(op)


def _forecast_row(row):
    item = dict(row)
    for key in ("timeframe_context", "snapshot", "outcome_details", "evidence"):
        if key in item:
            item[key] = _json_value(item.get(key), {})
    if "direction_correct" in item and item["direction_correct"] is not None:
        item["direction_correct"] = bool(item["direction_correct"])
    return item


async def get_llm_forecasts(symbol=None, status=None, limit=100):
    def op(conn):
        clauses, values = [], []
        if symbol:
            clauses.append("symbol=?"); values.append(str(symbol).upper())
        if status:
            clauses.append("status=?"); values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 500)))
        rows = conn.execute(f"SELECT * FROM llm_forecasts{where} ORDER BY created_at DESC LIMIT ?", values).fetchall()
        return [_forecast_row(row) for row in rows]
    return await _run_db(op)


async def get_llm_forecast_report():
    """Aggregate only journaled forecast outcomes; no trading side effects."""
    def op(conn):
        rows = conn.execute("""SELECT horizon_minutes,
            COUNT(*) AS total_count,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
            SUM(CASE WHEN status='evaluated' AND direction_correct THEN 1 ELSE 0 END) AS correct_count,
            AVG(CASE WHEN status='evaluated' THEN confidence END) AS average_confidence,
            AVG(CASE WHEN status='evaluated' THEN outcome_return_pct END) AS average_return_pct
            FROM llm_forecasts GROUP BY horizon_minutes ORDER BY horizon_minutes""").fetchall()
        return [dict(row) for row in rows]
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
                   json.dumps(item.get("evidence") or {}, ensure_ascii=False, default=str), item.get("status", "candidate"),
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

async def read_only_query(sql: str, limit: int = 500):
    """Execute a narrowly validated, read-only query for LLM inspection."""
    statement = str(sql or "").strip()
    if not statement or ";" in statement:
        raise ValueError("Tek bir SELECT sorgusu gerekli; çoklu ifade veya noktalı virgül yasak")
    if not re.match(r"^(SELECT|WITH)\b", statement, re.I):
        raise ValueError("Yalnızca SELECT veya WITH ... SELECT sorgularına izin verilir")
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|PRAGMA|COPY|GRANT|REVOKE|CALL|DO|VACUUM|ATTACH|DETACH)\b", statement, re.I):
        raise ValueError("Yazma, DDL veya yönetim komutu tespit edildi")
    allowed = {"positions", "trades", "signals", "decision_logs", "virtual_wallet", "backtests", "analysis_snapshots", "llm_tool_logs"}
    referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", statement, re.I))
    if not referenced or not referenced.issubset(allowed):
        raise ValueError("Sorgu yalnızca izin verilen uygulama tablolarını kullanabilir")
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
    def op(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO llm_tool_logs (timestamp, scope, tool_name, arguments, result_summary, duration_ms, success) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.get("timestamp") or time.time(), item.get("scope"), item.get("tool_name"),
             json.dumps(item.get("arguments") or {}, default=str), item.get("result_summary"),
             item.get("duration_ms"), bool(item.get("success")))
        )
        conn.commit()
    await _run_db(op)


async def get_llm_tool_logs(limit=500):
    def op(conn: sqlite3.Connection):
        rows = conn.execute("SELECT * FROM llm_tool_logs ORDER BY timestamp DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
        result = [dict(r) for r in rows]
        for row in result:
            try: row["arguments"] = _json_value(row.get("arguments"), {})
            except (TypeError, json.JSONDecodeError): pass
        return result
    return await _run_db(op)


async def save_a2a_message(message, direction="outbound", status="queued", error=None, insert_only=False):
    def op(conn: sqlite3.Connection):
        if insert_only:
            cursor = conn.execute("""INSERT INTO a2a_messages
                (message_id,correlation_id,direction,message_type,sender,recipient,status,payload,created_at,delivered_at,acknowledged_at,last_error,attempts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(message_id) DO NOTHING""",
                (message.get("message_id"), message.get("correlation_id"), direction, message.get("type"),
                 message.get("from"), message.get("to"), status, json.dumps(message, ensure_ascii=False, default=str),
                 message.get("created_at") or time.time(), time.time() if status == "delivered" else None,
                 time.time() if status == "acknowledged" else None, error))
            conn.commit()
            return cursor.rowcount > 0
        conn.execute("""INSERT OR REPLACE INTO a2a_messages
            (message_id,correlation_id,direction,message_type,sender,recipient,status,payload,created_at,delivered_at,acknowledged_at,last_error,attempts)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT attempts FROM a2a_messages WHERE message_id=?),0))""",
            (message.get("message_id"), message.get("correlation_id"), direction, message.get("type"),
             message.get("from"), message.get("to"), status, json.dumps(message, ensure_ascii=False, default=str),
             message.get("created_at") or time.time(), time.time() if status == "delivered" else None,
             time.time() if status == "acknowledged" else None, error, message.get("message_id")))
        conn.commit()
        return True
    return await _run_db(op)


async def get_a2a_messages(limit=100, status=None):
    def op(conn: sqlite3.Connection):
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
    def op(conn: sqlite3.Connection):
        cur = conn.execute("UPDATE a2a_messages SET status='acknowledged', acknowledged_at=? WHERE message_id=?", (time.time(), str(message_id)))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


async def update_a2a_message_status(message_id, status, payload=None):
    def op(conn: sqlite3.Connection):
        if payload is None:
            cur = conn.execute("UPDATE a2a_messages SET status=?, acknowledged_at=? WHERE message_id=?", (status, time.time() if status == "acknowledged" else None, str(message_id)))
        else:
            cur = conn.execute("UPDATE a2a_messages SET status=?, payload=?, acknowledged_at=? WHERE message_id=?", (status, json.dumps(payload, ensure_ascii=False, default=str), time.time() if status == "acknowledged" else None, str(message_id)))
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
            (symbol, str(guard_type), str(status), blocked_until, reason, json.dumps(evidence or {}, ensure_ascii=False, default=str), revision, now, now))
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
            json.dumps(rule.get("notify_channels") or ["websocket"]), rule.get("created_by", "user"), rule.get("reason"), now, now))
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
    values = [json.dumps(changes[key]) if key == "notify_channels" else bool(changes[key]) if key in {"enabled", "armed"} else _db_datetime_value(changes[key]) if key == "expires_at" else changes[key] for key in fields]
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
        armed_false = "FALSE" if _postgres_enabled() else "0"
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
        conn.execute("INSERT INTO push_subscriptions(endpoint,subscription,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription,updated_at=excluded.updated_at", (endpoint, json.dumps(subscription), now, now)); conn.commit(); return True
    return await _run_db(op)

async def list_push_subscriptions():
    def op(conn): return [_json_value(row["subscription"], {}) for row in conn.execute("SELECT subscription FROM push_subscriptions").fetchall()]
    return await _run_db(op)


async def get_chart_settings(symbol):
    def op(conn: sqlite3.Connection):
        row = conn.execute("SELECT data FROM chart_settings WHERE symbol=?", (symbol,)).fetchone()
        return _json_value(row[0], None) if row else None

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
        sql = ("INSERT INTO backtests (timestamp, symbol, interval, strategy, params, days_back, "
            "initial_balance, final_balance, net_pnl, net_pnl_pct, total_trades, wins, losses, "
            "win_rate, max_drawdown_pct, order_size, stop_loss_pct, take_profit_pct, trailing_stop_pct, trades) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        params = (result.get("timestamp"), result.get("symbol"), result.get("interval"),
             result.get("strategy"), json.dumps(result.get("params", {})), result.get("days_back"),
             result.get("initial_balance"), result.get("final_balance"), result.get("net_pnl"),
             result.get("net_pnl_pct"), result.get("total_trades"), result.get("wins"),
             result.get("losses"), result.get("win_rate"), result.get("max_drawdown_pct"), result.get("order_size"),
             result.get("stop_loss_pct"), result.get("take_profit_pct"),
             result.get("trailing_stop_pct"), json.dumps(result.get("trades", [])))
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
            values.append((r["symbol"].upper(),r["timeframe"],int(r["open_time"]),int(r["captured_at"]),r["feature_version"],json.dumps(r.get("payload",{}),default=str),r.get("regime"),r.get("regime_confidence"),r.get("confluence_score"),bool(r.get("data_ready",False))))
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
    def op(conn: sqlite3.Connection):
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
                  json.dumps(result.get("symbols", [])), json.dumps(result.get("timeframes", [])),
                  json.dumps(result.get("parameters", {}), default=str), json.dumps(result.get("result", {}), default=str),
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
                  json.dumps(item.get("symbols", [])), json.dumps(item.get("timeframes", [])),
                  json.dumps(item.get("definition", {}), default=str), json.dumps(item.get("evidence", {}), default=str),
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
    def op(conn: sqlite3.Connection):
        conn.execute("DELETE FROM backtests WHERE id=?", (run_id,))
        conn.commit()

    await _run_db(op)


async def close_db():
    def op(conn: sqlite3.Connection):
        conn.commit()
        conn.close()

    await _run_db(op)
    global _DB_CONN, _PG_CONN
    _DB_CONN = None
    _PG_CONN = None
