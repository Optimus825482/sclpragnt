import asyncio
import bisect
import hashlib
import json
import logging
import math
import os
import time
import tempfile
import re
import uuid
from datetime import datetime, timezone, timedelta

from app.config import config
from app.forecast_learning import outcome_window_seconds

logger = logging.getLogger("scalper.database")

# ---------------------------------------------------------------------------
# BİRİM SÖZLEŞMESİ (V-14) — `*_pct` alanları
#
# `trades` tablosu AYNI satırda iki farklı birim taşır (analyzer.py):
#   * `pnl_pct`           → YÜZDE  ((pnl/(entry*qty))*100)
#   * `max_favorable_pct` → KESİR  ((max_price-entry)/entry)
#   * `max_adverse_pct`   → KESİR
# Depolanan değerler KASITLI olarak yeniden ölçeklenmez: bu alanlar paylaşılan
# muhasebe matematiğinde ve replay'de kullanılır, sessiz bir ×100 kaydırma tüm
# yeniden-üretimi bozar. Bunun yerine birim, OKUMA/RAPOR sınırında açık hale
# getirilir: `get_report_trade_breakdown` eski alanı (geriye dönük uyum) KORUR
# ve yanında `*_ratio` (kesir) + `*_pct` (yüzde = kesir×100) ikizlerini döndürür.
# Kural: `*_ratio` = kesir; `*_pct` = yüzde.
# ---------------------------------------------------------------------------

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Bağlantı havuzu: tek global bağlantı + global lock yerine psycopg_pool.
# Pool eşzamanlı bağlantılar verir; transaction bütünlüğü çok-statement'lı
# op'larda (commit_open_position vb.) pg_advisory_xact_lock ile sağlanır.
# Lazy açılır (open=False); ilk _execute'te açılır. 2026-09-05 (K1).
_PG_POOL = None
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
    def raw_execute(self, sql, params=()):
        """V-19: ``?`` → ``%s`` dönüşümü YAPMADAN çalıştır.

        LLM'in ürettiği hazır SQL, string literal içinde ``?`` taşıyabilir;
        compat katmanının naif dönüşümü onu parametre yer tutucusuna çevirip
        hataya yol açıyordu. Yalnız izin listesi + yazma yasağı doğrulanmış
        salt-okunur sorgular için kullanılır.
        """
        cur = self.conn.cursor(); cur.execute(sql, params); return cur
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    # Pool bağlantılarını asla elle kapatma — `with pool.connection()` çıkınca
    # bağlantı otomatik pool'a döner. close() no-op'tur (eski tek-bağlantı
    # deseninden kalma çağrılar pool'u bozmasın diye). 2026-09-05.
    def close(self): pass

class _HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int): return list(self.values())[key]
        return super().__getitem__(key)

def _hybrid_row_factory(cursor):
    if cursor.description is None:
        return lambda values: values
    names = [col.name for col in cursor.description]
    return lambda values: _HybridRow(zip(names, values))

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


def _matches_within(index, target: float, tolerance: float) -> list:
    """V-09: zamanla SIRALI ``(zaman, değer)`` çiftlerinde ``|zaman-target|<=tol``.

    Eskiden onarım fonksiyonları her log için TÜM işlem listesini Python'da
    tarıyordu (O(N_trades × N_logs)). İkili arama aynı sonucu O(log N) verir.
    """
    if not index:
        return []
    times = [item[0] for item in index]
    start = bisect.bisect_left(times, target - tolerance)
    found = []
    for position in range(start, len(index)):
        if index[position][0] > target + tolerance:
            break
        found.append(index[position][1])
    return found


def _has_timestamp_within(index, target: float, tolerance: float) -> bool:
    """V-09: sıralı zaman listesinde ``target ± tolerance`` aralığında değer var mı."""
    if not index:
        return False
    start = bisect.bisect_left(index, target - tolerance)
    return start < len(index) and index[start] <= target + tolerance


def _escape_like(value: str) -> str:
    """V-18: LIKE/ILIKE desen jokerlerini kaçır (varsayılan ESCAPE '\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _configure_pool_connection(conn) -> None:
    """V-15: kilit beklemesini SINIRLA — sonsuz bekleme deploy hang'i üretiyordu.

    ``init_db`` 528 satırlık DDL'i çalıştırır. Canlı bir backend aynı nesneler
    üzerinde ACCESS EXCLUSIVE kilit tutarken yeni konteynerin ``init_db``'si
    süresiz bloklanıyordu (healthcheck timeout -> restart döngüsü). 5 sn'lik
    ``lock_timeout`` bunu görünür bir hataya çevirir.

    ``statement_timeout`` burada AYARLANMAZ: retention yıkaması ve backfill
    partileri gibi meşru uzun işler anahtarın dışında kalmalı. DDL'e özel sınır
    ``init_db`` içinde ``SET LOCAL`` ile verilir.
    """
    try:
        conn.execute("SET lock_timeout = '5s'")
        conn.commit()
    except Exception:
        pass


def _get_connection():
    """Pool'dan bir bağlantı al (context manager olarak kullanılır)."""
    global _PG_POOL
    if _PG_POOL is None:
        try:
            from psycopg_pool import ConnectionPool
            _PG_POOL = ConnectionPool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=8,
                open=False,
                kwargs={"row_factory": _hybrid_row_factory},
                configure=_configure_pool_connection,
            )
            _PG_POOL.open()
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL havuzu kurulamadı: {exc}") from exc
    return _PG_POOL


async def _run_db(operation):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _execute(operation))


def _execute(operation):
    """Pool'dan bağlantı al, _PostgresCompat ile sar, op'u çalıştır.

    Bağlantı context manager ile pool'a geri verilir (kapanmaz). Transaction
    bütünlüğü op içindeki manuel commit/rollback + advisory lock ile sağlanır.
    """
    pool = _get_connection()
    try:
        with pool.connection() as raw_conn:
            conn = _PostgresCompat(raw_conn)
            return operation(conn)
    except _PG_FATAL_ERRORS as exc:
        # Havuz bozuk bağlantıyı otomatik kapatıp yenisiyle devam eder; manuel
        # close pool'u bozabileceği için yapılmaz. Sadece hata yükseltilir.
        raise RuntimeError(f"PostgreSQL bağlantısı koptu, yeniden kurulacak: {exc}") from exc
    except Exception:
        raise


async def init_db():
    """Initialize the PostgreSQL schema (single backend)."""
    def pg_op(conn):
        # V-03: TÜM migration dosyaları uygulanır ve sha ikisinin birleşimidir.
        # Eskiden yalnız 001 okunuyordu → 002_macd_evidence_lift.sql ölüydü ve
        # MACD kanıt kolonları yalnız çalışma anındaki gecikmeli DDL ile var
        # oluyordu (şema sürümlemesi yanıltıcıydı).
        migrations_dir = os.path.abspath(os.path.join(_APP_DIR, "..", "migrations"))
        schema_sql = ""
        for filename in ("001_pgvector_schema.sql", "002_macd_evidence_lift.sql",
                         "003_rising_signals.sql", "004_bloat_prevention.sql",
                         "005_user_binance_keys.sql"):
            path = os.path.join(migrations_dir, filename)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as schema_file:
                    schema_sql += schema_file.read() + "\n"
        schema_sha = hashlib.sha256(schema_sql.encode("utf-8")).hexdigest()
        # Hızlı yol: entrypoint migration'ı aynı sha'yı uyguladıysa DDL'i
        # yeniden koşma (canlı sistemde gereksiz ACCESS EXCLUSIVE lock
        # yarışı doğuruyordu). to_regclass ile ilk kurulum ayrımı yapılır.
        marker = None
        if conn.execute("SELECT to_regclass('public.llm_settings')").fetchone()[0]:
            mrow = conn.execute("SELECT value FROM llm_settings WHERE key='schema_sha256'").fetchone()
            marker = mrow[0] if mrow else None
        if marker != schema_sha:
            # V-15: DDL'e işlem kapsamlı bir üst sınır (lock_timeout havuz
            # yapılandırmasından gelir). SET LOCAL dışında bir işlemde
            # çalıştırılırsa PostgreSQL uyarı verip yok sayar — zararsız.
            conn.conn.execute("SET LOCAL statement_timeout = '300s'")
            conn.conn.execute(schema_sql)
            conn.execute(
                "INSERT INTO llm_settings(key,value) VALUES('schema_sha256',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (schema_sha,))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_skills_name ON llm_skills(name)")
        # V-07: `signals.trade_id` üzerinde index yoktu; `reconcile_portfolio`
        # ve `purge_legacy_trade_records` bu kolonla DELETE atıyordu -> tam
        # tarama. V-08: `decision_logs.decision` da indexsizdi ve onarım uçları
        # `WHERE decision='CLOSE_LONG'` ile tam tarama yapıyordu. İkisi de
        # idempotent; her açılışta çalışır (şema sha'sına bağlı değildir).
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_trade_id ON signals(trade_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_logs_decision ON decision_logs(decision, timestamp DESC)")
        # TAH-01: tahmin satırının ölçüm çapası (fiyatın gözlendiği an). Şema
        # dosyası tek başına yeterli değil — koşan dağıtımlarda da idempotent eklenir.
        conn.execute("ALTER TABLE llm_forecasts ADD COLUMN IF NOT EXISTS decided_at DOUBLE PRECISION")
        # M4 (R2-03): bildirim skorunun normalize edildiği cap satır başına saklanır —
        # mutable `MONITORING_SCORE_NORM_CAP` değişse bile eski satır doğru ölçeklenir.
        conn.execute("ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS norm_cap DOUBLE PRECISION")
        # A3 (2026-09-14): panel ölçek sürümü (1=lineer, 2=log). SKOR
        # yorumlanırken hangi haritanın kullanılacağını belirler; etiket yoksa
        # kayıt A3 öncesi (lineer) kabul edilir.
        conn.execute("ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS norm_version INTEGER")
        # M4 (R3-05/R2-05/R4-07): bildirim <-> velocity adayını ±60 sn + hedef eşleşmesi
        # yerine KALICI `candidate_id` ile bağlamak için kolon (hedef değişse de ölçülebilir).
        conn.execute("ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS candidate_id TEXT")
        # BİRLEŞİK SİNYAL (2026-09-17): bildirimi üreten tespit kaynakları (JSON dizi,
        # ör. ["velocity","jump","early"]). Rapor/günlük takibi "hangi algoritma
        # yakaladı" sorusunu bu kolonla yanıtlar; NULL = eski kayıt (tek kaynak radar).
        conn.execute("ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS sources TEXT")
        # M4 (R3-09): koruma kapanışı sonrası aynı bildirimin yeniden açılışı için
        # kalıcı "reopen" anahtarı. `notification_id` (bigint) string id taşıyamaz;
        # bu TEXT kolon reopen churn korumasını taşır.
        conn.execute("ALTER TABLE auto_paper_trades ADD COLUMN IF NOT EXISTS notification_key TEXT")
        # MASTER SURGE ENGINE (2026-09-21): 4 katmanlı teyit ve uyarlanabilir hedefler (TP1/TP2)
        conn.execute("ALTER TABLE auto_paper_trades ADD COLUMN IF NOT EXISTS tp1_scalp_pct DOUBLE PRECISION")
        conn.execute("ALTER TABLE auto_paper_trades ADD COLUMN IF NOT EXISTS tp2_runner_pct DOUBLE PRECISION")
        conn.execute("ALTER TABLE auto_paper_trades ADD COLUMN IF NOT EXISTS confluence_4way BOOLEAN")
        # D-06 (2026-09-14): MFE ulasilamaz bir TEPE. `exit_pct` ufuk sonundaki
        # kapanis (gerceklestirilebilir), `net_pct` gidis/donus maliyeti dusulmus hali.
        conn.execute("ALTER TABLE velocity_candidates ADD COLUMN IF NOT EXISTS exit_pct DOUBLE PRECISION")
        conn.execute("ALTER TABLE velocity_candidates ADD COLUMN IF NOT EXISTS net_pct DOUBLE PRECISION")
        # ADMIN İŞLEM BİLDİRİMİ (2026-09-20): aboneliğin hangi kullanıcıya ait
        # olduğu. Eski kayıtlar NULL kalır; uygulama açılışındaki reconcile
        # bunları kullanıcı adıyla yeniden yazar. Seçili alıcılara hedefli
        # push bu kolonla filtrelenir.
        conn.execute("ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS username TEXT")
        # V-04: MACD kanıt şeması artık OKUMA yolunda değil, açılışta bir kez
        # hazırlanır (istatistik uçları DDL/INSERT/COMMIT yapmaz).
        _ensure_macd_evidence_schema(conn)
        # V-02/V-06: kırılgan UNIQUE kısıtlar tek tek ve HATA TOLERANSLI kurulur.
        # Şemaya (001) gömülü olsalardı mevcut veride ihlal varsa 528 satırlık
        # DDL'in TAMAMI rollback olur, `schema_sha256` yazılmaz ve her restart
        # aynı yerde patlardı (kalıcı açılış döngüsü). Ayrıca bu kısıtlar
        # `trade_id` kopya korumasını DB düzeyine taşır (V-06).
        for constraint_sql in (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_trades_trade_id "
            "ON trades(trade_id) WHERE trade_id IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_trade_id "
            "ON positions(trade_id) WHERE trade_id IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS auto_paper_trades_one_open_per_symbol "
            "ON auto_paper_trades(symbol) WHERE status='open'",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_auto_paper_notification_key "
            "ON auto_paper_trades(notification_key) WHERE notification_key IS NOT NULL",
        ):
            try:
                conn.execute(constraint_sql)
            except Exception:
                logger.warning(
                    "Kısıt kurulamadı (veri temizliği gerekli, açılış sürüyor): %s",
                    constraint_sql, exc_info=True)
        conn.execute("INSERT INTO llm_skills(name,instructions,enabled,created_at) VALUES(%s,%s,TRUE,%s) "
                     "ON CONFLICT(name) DO NOTHING",
                     (DEFAULT_SCALPER_SKILL_NAME, DEFAULT_SCALPER_SKILL_INSTRUCTIONS, time.time()))
        # Reconcile migrated cash with trades and open positions.
        # Portföy reseti sonrası yeniden init, reset ÖNCESİ PnL'i cüzdana
        # geri yüklememeli — reset cutoff'u burada da uygulanır.
        # V-13: `virtual_wallet` TRY satırı ana defter + auto_paper tarafından
        # PAYLAŞILIR; açılış mutabakatı da iki bacağı katmalı (reconcile_portfolio
        # ile aynı formül) — aksi halde açık auto-paper pozisyonu kadar FAZLA yazar.
        conn.execute("""UPDATE virtual_wallet SET amount=
            (SELECT COALESCE(
                (SELECT amount FROM virtual_wallet WHERE asset='TRY' AND amount IS NOT NULL AND amount > 0),
                %s
                + COALESCE((SELECT SUM(pnl) FROM trades WHERE (%s = 0) OR (exit_time > %s)), 0)
                + COALESCE((SELECT SUM(pnl) FROM auto_paper_trades WHERE status='closed' AND ((%s = 0) OR (exit_time > %s))), 0)
                - COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0)
                - COALESCE((SELECT SUM(order_value_try) FROM auto_paper_trades WHERE status='open'), 0)
                - (COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0)
                   + COALESCE((SELECT SUM(order_value_try) FROM auto_paper_trades WHERE status='open'), 0)) * %s
            ) AS reconciled)
        WHERE asset='TRY' AND NOT EXISTS (SELECT 1 FROM virtual_wallet WHERE asset='TRY' AND amount IS NOT NULL AND amount > 0)""",
            (config.INITIAL_BALANCE_TRY,
             _get_reset_cutoff_sync(conn), _get_reset_cutoff_sync(conn),
             _get_reset_cutoff_sync(conn), _get_reset_cutoff_sync(conn),
             config.COMMISSION_PCT))
        conn.conn.commit()
    await _run_db(pg_op)
    # Legacy pozisyonların eksik trade_id'leri açılışta BİR KEZ doldurulur;
    # okuma yolu (load_positions) artık veritabanına yazmaz (Madde 21).
    await backfill_position_trade_ids()

async def ensure_default_scalper_skill():
    """Keep the built-in trade manager visible in the active database skill registry."""
    def op(conn):
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_skills_name ON llm_skills(name)")
        enabled_literal = "TRUE"
        conn.execute(
            f"INSERT INTO llm_skills(name,instructions,enabled,created_at) VALUES(?,?,{enabled_literal},?) "
            "ON CONFLICT(name) DO NOTHING",
            (DEFAULT_SCALPER_SKILL_NAME, DEFAULT_SCALPER_SKILL_INSTRUCTIONS, time.time()),
        )
        conn.commit()
    return await _run_db(op)

async def reset_trading_data():
    """Paper cüzdanı 10.000 TL'ye sıfırla, tüm açık pozisyonları kapat ve reset_at damgası koy.

    - Açık auto_paper_trades'ler 'closed' yapılır (exit_reason='reset')
    - positions tablosu temizlenir
    - virtual_wallet 10.000 TL yapılır
    - portfolio_reset_at zaman damgası llm_settings'e yazılır
    - Eski kapanmış trade/sinyal/kayıtlar SİLİNMEZ — reset_at anından
      sonraki işlemler aggregasyon/rapor hesaplamalarına katılır.
    """
    now = time.time()
    def op(conn):
        # Açık otonom paper pozisyonlarını kapat
        conn.execute(
            "UPDATE auto_paper_trades SET status='closed', exit_time=?, exit_reason='reset', updated_at=? "
            "WHERE status='open'", (now, now))
        # Ana pozisyon tablosunu temizle
        conn.execute("DELETE FROM positions")
        # Sinyal/karar loglarını temizle (reset_at öncesi kullanılmasın)
        conn.execute("DELETE FROM signals WHERE strategy='AUTO_PAPER'")
        conn.execute("DELETE FROM decision_logs WHERE strategy='AUTO_PAPER'")
        # Cüzdanı sıfırla
        conn.execute("DELETE FROM virtual_wallet")
        conn.execute("INSERT INTO virtual_wallet (asset, amount) VALUES ('TRY', ?)", (config.INITIAL_BALANCE_TRY,))
        conn.execute("INSERT INTO llm_settings(key,value) VALUES('portfolio_reset_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
        conn.commit()
        return {"reset_at": now, "wallet": config.INITIAL_BALANCE_TRY}
    return await _run_db(op)


async def get_reset_cutoff() -> float:
    """Portföy sıfırlama zaman damgasını döndürür (yoksa 0 = filtre yok)."""
    def op(conn):
        return _get_reset_cutoff_sync(conn)
    return await _run_db(op)


def _get_reset_cutoff_sync(conn) -> float:
    """Senkron (conn ile) sürüm — _run_db içindeki op()'lardan çağrılır."""
    try:
        row = conn.execute("SELECT value FROM llm_settings WHERE key='portfolio_reset_at'").fetchone()
        if row:
            try:
                return float(row[0])
            except (TypeError, ValueError):
                return 0.0
    except Exception:
        pass
    return 0.0

async def get_wallet_balance(asset="TRY"):
    """Virtual wallet balance. Defaults to TRY — the only asset the wallet
    holds (legacy "USDT" default silently returned 0.0)."""
    def op(conn):
        row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?", (asset,)).fetchone()
        # V-17: `virtual_wallet.amount` şemada NOT NULL değil; eski kod NULL'u
        # olduğu gibi döndürüyordu ve `float(None)` çağıranlarda çöküyordu.
        # Sözleşme: bakiye her zaman bir sayıdır.
        if not row or row[0] is None:
            return 0.0
        return float(row[0])

    return await _run_db(op)


# NOT (V-20): `update_wallet_balance(asset, amount)` burada duruyordu. Repo
# genelinde (app/routers/scripts/tests/backend/work/work) HİÇBİR okuyucusu
# yoktu ve cüzdanı kilit/komisyon olmadan kör bir UPSERT ile yazıyordu — V-01
# para yolu için tehlikeli bir tuzaktı. Silindi. Cüzdan artık yalnız
# `reconcile_portfolio` / `commit_close_position` / açılış mutabakatı ile
# yazılır; `get_wallet_balance` yalnız okur.


def _chronological_overallocation_candidates(conn):
    """Return only positions whose opening event made the ledger insolvent.

    Models the shared TRY wallet across BOTH the main `trades`/`positions`
    ledger and the `auto_paper_trades` subsystem (they debit/credit the same
    `virtual_wallet` row). Credit events use the actual wallet credit
    (exit_notional * (1 - commission)), not `cost + pnl`, so the buy-side
    commission is not subtracted twice (K3).
    """
    c = config.COMMISSION_PCT
    cash = float(config.INITIAL_BALANCE_TRY)
    events = []
    cutoff = _get_reset_cutoff_sync(conn)
    trades = conn.execute(
        "SELECT entry_time,exit_time,entry_price,quantity,pnl,exit_price FROM trades"
        + (" WHERE exit_time>?" if cutoff else ""),
        (cutoff,) if cutoff else ()).fetchall()
    for row in trades:
        cost = float(row[2] or 0) * float(row[3] or 0)
        exit_notional = (float(row[5] or 0) * float(row[3] or 0)) if row[5] is not None else 0.0
        events.append((float(row[0] or 0), 0, "debit", None, cost * (1 + c)))
        events.append((float(row[1] or 0), 1, "credit", None, exit_notional * (1 - c)))
    # auto_paper_trades share the same TRY wallet.
    # V-10: açık (`status='open'`) satırların `exit_time` değeri NULL'dur, bu
    # yüzden `exit_time > cutoff` filtresi onları ELİYORDU. Reset sonrası açık
    # otonom pozisyonların borcu aşırı-tahsis modeline hiç girmiyor, model nakdi
    # gerçekte olandan yüksek gösteriyordu — oysa `reconcile_portfolio` aynı
    # maliyeti `open_cost`'a katıyor (çelişkili çıktı).
    ap_trades = conn.execute(
        "SELECT entry_time,exit_time,order_value_try,quantity,status,exit_price FROM auto_paper_trades"
        + (" WHERE status='open' OR exit_time>?" if cutoff else ""),
        (cutoff,) if cutoff else ()).fetchall()
    for row in ap_trades:
        order_value = float(row[2] or 0)
        qty = float(row[3] or 0)
        if row[4] == "open":
            events.append((float(row[0] or 0), 0, "open", None, order_value * (1 + c)))
        else:
            events.append((float(row[0] or 0), 0, "debit", None, order_value * (1 + c)))
            exit_notional = (float(row[5] or 0) * qty) if row[5] is not None else 0.0
            events.append((float(row[1] or 0), 1, "credit", None, exit_notional * (1 - c)))
    positions = conn.execute("SELECT symbol,entry_time,entry_price,quantity FROM positions").fetchall()
    for row in positions:
        cost = float(row[2] or 0) * float(row[3] or 0)
        events.append((float(row[1] or 0), 0, "open", row, cost * (1 + c)))
    candidates = []
    for _, _, kind, row, amount in sorted(events, key=lambda item: (item[0], item[1])):
        if kind == "credit":
            cash += amount
        else:
            cash -= amount
            if kind == "open" and cash < -0.01 and row is not None:
                candidates.append({"symbol": row[0], "entry_time": row[1], "entry_price": row[2], "quantity": row[3], "cost": float(row[2] or 0) * float(row[3] or 0), "reason": "entry_cash_was_insufficient"})
    return candidates

def _portfolio_reconcile_figures(conn, cutoff: float):
    """Mutabakat rakamlarının TEK kaynağı (V-01/V-13).

    `virtual_wallet` TRY satırı İKİ defter tarafından paylaşılır:
      * ana defter -> `trades` (kapanmış) + `positions` (açık)
      * otonom     -> `auto_paper_trades` (kapanmış PnL + açık `order_value_try`)
    Preview ve apply AYNI SQL'i kullanmak zorundadır; aksi halde iki adımlı onay
    akışında operatör yanlış bakiyeyi onaylar (V-01).

    Döner: (realized_pnl, main_open_cost, auto_open_cost) — hepsi TRY.
    """
    realized = float(conn.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE (?=0 OR exit_time>?)",
        (cutoff, cutoff)).fetchone()[0] or 0)
    realized += float(conn.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM auto_paper_trades WHERE status='closed' AND (?=0 OR exit_time>?)",
        (cutoff, cutoff)).fetchone()[0] or 0)
    main_open_cost = float(conn.execute(
        "SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0] or 0)
    auto_open_cost = float(conn.execute(
        "SELECT COALESCE(SUM(order_value_try),0) FROM auto_paper_trades WHERE status='open'").fetchone()[0] or 0)
    return realized, main_open_cost, auto_open_cost


async def reconcile_portfolio():
    """Rebuild TRY cash and remove only over-allocated newest open positions.

    The main `trades`/`positions` ledger and the `auto_paper_trades` subsystem
    share the same `virtual_wallet` TRY row, so reconciliation must account for
    both (C2). Including only the main ledger would corrupt capital whenever an
    auto_paper position is open.
    """
    def op(conn):
        before_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?", ("TRY",)).fetchone()
        before = float(before_row[0]) if before_row else 0.0
        # Reset cutoff'u uygula: reset öncesi kapanmış işlemler cüzdana
        # geri yüklenemez (reset_trading_data belgelendiği gibi).
        cutoff = _get_reset_cutoff_sync(conn)
        realized, main_open_cost, auto_open_cost = _portfolio_reconcile_figures(conn, cutoff)
        open_cost = main_open_cost + auto_open_cost
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
                main_open_cost -= position_cost
                open_cost = main_open_cost + auto_open_cost
                entry_commission = open_cost * config.COMMISSION_PCT
                after = config.INITIAL_BALANCE_TRY + realized - open_cost - entry_commission
            # A valid partial position opened from remaining cash must never be
            # removed merely because later mark-to-market PnL changed.
            if removed:
                main_open_cost = float(conn.execute("SELECT COALESCE(SUM(entry_price*quantity),0) FROM positions").fetchone()[0] or 0)
                open_cost = main_open_cost + auto_open_cost
                entry_commission = open_cost * config.COMMISSION_PCT
                after = config.INITIAL_BALANCE_TRY + realized - open_cost - entry_commission
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", after))
        conn.commit()
        trade_count = int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
        position_count = int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0])
        auto_count = int(conn.execute("SELECT COUNT(*) FROM auto_paper_trades WHERE status='open'").fetchone()[0])
        return {"before_try": before, "after_try": after, "realized_pnl": realized,
                "open_entry_cost": open_cost, "open_entry_commission": entry_commission,
                "trade_count": trade_count, "open_position_count": position_count,
                "auto_paper_open": auto_count,
                "difference": after - before, "removed_overallocated_positions": removed}
    return await _run_db(op)

async def preview_portfolio_reconcile():
    """Read-only preview of `reconcile_portfolio` — AYNI rakamları göstermek zorunda.

    V-01 (KRİTİK): preview daha önce `auto_paper_trades` alt sistemini tamamen yok
    sayıyordu (ne realize PnL ne açık pozisyon maliyeti). İki adımlı onay akışında
    operatör yanlış "mutabakat sonrası bakiye"yi onaylıyordu (tek açık 2.000 TRY'lik
    auto-paper pozisyonunda ölçülen sapma: +2.003,00 TRY). Artık ikisi de
    `_portfolio_reconcile_figures` kullanır.
    """
    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        realized, main_open_cost, auto_open_cost = _portfolio_reconcile_figures(conn, cutoff)
        open_cost = main_open_cost + auto_open_cost
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
        # AUTO_PAPER kapanışları bağımsız tabloda izlendiği için repair denetiminde
        # "eşleşmemiş kapanış" sayılmaz (sahte uyarı üretmesin).
        close_logs = conn.execute(
            "SELECT id,symbol,timestamp,strategy FROM decision_logs "
            "WHERE decision='CLOSE_LONG' AND (strategy IS NULL OR strategy='' OR strategy<>'AUTO_PAPER') "
            "ORDER BY timestamp"
        ).fetchall()
        # V-09: eskiden her log için TÜM trades listesi Python'da taranıyordu
        # (10.000 trade + 10.000 log -> ~100M karşılaştırma, tek istek içinde).
        # Sembol başına SIRALI çıkış zamanı listesi + ikili arama: aynı semantik.
        exit_index: dict[str, list[float]] = {}
        for trade in trades:
            if trade[4] is None:
                continue
            exit_index.setdefault(trade[1], []).append(float(trade[4]))
        for values in exit_index.values():
            values.sort()
        unmatched_closes = []
        for log in close_logs:
            if not _has_timestamp_within(exit_index.get(log[1]), float(log[2] or 0), 30.0):
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
        # V-09: aynı O(N²) desen burada da vardı. Sembol başına
        # (çıkış zamanı -> strateji) sıralı indeks; "tam olarak 1 eşleşme"
        # kuralı korunur.
        strategy_index: dict[str, list[tuple[float, str]]] = {}
        for trade in trades:
            if trade[3] is None:
                continue
            strategy_index.setdefault(trade[1], []).append((float(trade[3]), trade[2]))
        for values in strategy_index.values():
            values.sort(key=lambda item: item[0])
        for log in logs:
            matches = _matches_within(strategy_index.get(log[1]), float(log[2] or 0), 30.0)
            if len(matches) == 1:
                conn.execute("UPDATE decision_logs SET strategy=? WHERE id=?", (matches[0], log[0]))
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
        row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
    return await _run_db(op)

async def save_llm_model(provider_id, name, temperature, model_type="chat", dimensions=None, embedding_metric="cosine"):
    def op(conn):
        sql = "INSERT INTO llm_models(provider_id,name,temperature,model_type,dimensions,embedding_metric,created_at) VALUES(?,?,?,?,?,?,?)"
        params = (provider_id,name,temperature,model_type,dimensions,embedding_metric,time.time())
        row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
    return await _run_db(op)

async def save_llm_skill(name, instructions):
    def op(conn):
        sql = "INSERT OR REPLACE INTO llm_skills(name,instructions,enabled,created_at) VALUES(?,?,1,?)"
        params = (name,instructions,time.time())
        conn.execute(sql, params); row = conn.execute("SELECT id FROM llm_skills WHERE name=?", (name,)).fetchone(); conn.commit(); return row[0]
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


async def backfill_position_trade_ids():
    """Legacy ``positions`` satırlarındaki eksik ``trade_id`` alanını BİR KEZ doldurur.

    Bu yazma daha önce ``load_positions`` (okuma yolu) içindeydi: her okuma bir
    UPDATE tetikleyebiliyor, yani salt-okunur sanılan bir çağrı veritabanını
    değiştiriyordu. Açılış migration'ına taşındı (Madde 21); okuma yolu artık
    hiçbir koşulda yazmaz.

    Dönen değer: doldurulan satır sayısı.
    """
    def op(conn):
        rows = conn.execute(
            "SELECT symbol FROM positions WHERE trade_id IS NULL OR trade_id=''"
        ).fetchall()
        symbols = [r[0] for r in rows]
        for symbol in symbols:
            conn.execute("UPDATE positions SET trade_id=? WHERE symbol=?",
                         (uuid.uuid4().hex, symbol))
        if symbols:
            conn.commit()
        return len(symbols)

    return await _run_db(op)


# ---------------------------------------------------------------------------
# MACD MONITOR alarm kayıtları (2026-09-11) — paper-only kanıt katmanı.
#
# Amaç: `jump_min_score` ve `_TF_WEIGHTS` gibi sezgisel eşiklerin ampirik
# olarak ayarlanabilmesi. Her üretilen sinyal saklanır; sonra 5m/15m/30m
# ileri getirileri doldurulur. Sinyal DAVRANIŞINI değiştirmez, yalnızca ölçer.
# ---------------------------------------------------------------------------

# Alarmın sonucunun "kesinleşmesi" için gereken süre (sn) — 30 dk ufuk + pay.
_MACD_ALERT_OUTCOME_WINDOW_SEC = 32 * 60

# F-09: bir satır çözülemeden (fill/expire) en fazla bu kadar kez denenir; sayaç
# üst sınıra ulaşınca satır expire edilir ve `pending` sorgusundan düşer. Böylece
# tek bir bozuk satır sonucu doldurma partisini KALICI olarak bloke edemez.
# Pencere ~16 tur (32 dk / 120 sn) olduğundan sağlıklı satırlar sınıra takılmaz.
_MACD_OUTCOME_MAX_ATTEMPTS = 60

# Taban (baseline) kovası: alarmları 5m kovalarına yuvarlarız. Aynı kovadaki tüm
# alarmlar aynı evren tabanını paylaşır → taban hesabı kova başına BİR kez yapılır.
_MACD_BASELINE_BUCKET_SEC = 300
# Ufuk → (sütun, dakika). Taban ve olay çalışması bu listeyi kullanır.
_MACD_HORIZON_MINUTES = (("5m", 5), ("15m", 15), ("30m", 30))
# Şema bir kez doğrulanır (idempotent ALTER'lar her turda koşmasın).
_MACD_EVIDENCE_SCHEMA_READY = False


def _ensure_macd_evidence_schema(conn) -> None:
    """A2/A3 şema eklerini idempotent uygula (002 migration'ın kodu içi eşi).

    Koşan bir dağıtımda migration dosyası elle uygulanmamış olabilir; kanıt
    katmanı kendi kendini onarsın. Hata durumunda ölçüm fonksiyonları sessizce
    eski davranışa düşer (kanıt katmanı kritik yol değildir).
    """
    global _MACD_EVIDENCE_SCHEMA_READY
    if _MACD_EVIDENCE_SCHEMA_READY:
        return
    try:
        conn.execute("ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS mfe_pct DOUBLE PRECISION")
        conn.execute("ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS mae_pct DOUBLE PRECISION")
        conn.execute("ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS early_score INTEGER")
        # F-03: baz fiyatın hangi çapadan geldiğini (kapanmış mum / canlı tick /
        # ilk ileri mum) denetlenebilir kılar. F-09: satır bazı deneme sayacı —
        # bozuk satırlar `pending` sorgusunu sonsuza dek işgal etmesin.
        conn.execute("ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS base_source TEXT")
        conn.execute("ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS outcome_attempts INTEGER")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS macd_market_baseline ("
            "bucket_ts BIGINT NOT NULL, horizon TEXT NOT NULL, avg_pct DOUBLE PRECISION NOT NULL, "
            "med_pct DOUBLE PRECISION NOT NULL, hit_rate DOUBLE PRECISION NOT NULL, "
            "n_symbols INTEGER NOT NULL, filled_at DOUBLE PRECISION NOT NULL, "
            "PRIMARY KEY (bucket_ts, horizon))")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS macd_market_baseline_ts_idx "
            "ON macd_market_baseline(bucket_ts DESC)")
        conn.commit()
        _MACD_EVIDENCE_SCHEMA_READY = True
    except Exception:
        logging.getLogger("scalper.database").debug(
            "macd kanıt şeması hazırlanamadı", exc_info=True)


def _macd_bucket(ts: float) -> int:
    """Zaman damgasını 5m taban kovasına yuvarla (tam sayı saniye)."""
    return int(ts // _MACD_BASELINE_BUCKET_SEC) * _MACD_BASELINE_BUCKET_SEC


def _baseline_rows_for_bucket(conn, bucket_ts: int) -> list[dict]:
    """Bir kovanın 5m/15m/30m evren tabanı; yoksa historical_candles'tan üretir.

    Taban = aynı zaman penceresinde (t → t+ufuk) evrendeki TÜM sembollerin
    getirisinin eşit ağırlıklı ortalaması. Kapanmış 5m mumlarından hesaplanır,
    canlı fiyat kullanılmaz (sızıntı yok). Tabanı olmayan kova (ör. veri yoksa)
    sessizce boş döner — alarm kaydı yine de geçerlidir, yalnız lift görünmez.
    """
    existing = conn.execute(
        "SELECT horizon, avg_pct, med_pct, hit_rate, n_symbols FROM macd_market_baseline "
        "WHERE bucket_ts=?", (int(bucket_ts),)).fetchall()
    have = {str(dict(r)["horizon"]): dict(r) for r in existing}
    missing = [h for h, _minutes in _MACD_HORIZON_MINUTES if h not in have]
    if missing:
        t0_ms = int(bucket_ts) * 1000
        max_ms = t0_ms + 30 * 60_000 + 5 * 60_000
        rows = conn.execute(
            "SELECT symbol, open_time, close FROM historical_candles "
            "WHERE timeframe='5m' AND open_time >= ? AND open_time <= ? ORDER BY symbol, open_time",
            (t0_ms - 5 * 60_000, max_ms)).fetchall()
        per_symbol: dict[str, list[tuple[float, float]]] = {}
        for row in rows:
            item = dict(row)
            per_symbol.setdefault(str(item["symbol"]), []).append(
                (float(item["open_time"]), float(item["close"] or 0)))
        for horizon, minutes in _MACD_HORIZON_MINUTES:
            if horizon not in missing:
                continue
            target = t0_ms + minutes * 60_000
            returns: list[float] = []
            for _symbol, candles in per_symbol.items():
                base_rows = [close for stamp, close in candles if stamp <= t0_ms]
                ahead_rows = [close for stamp, close in candles if stamp <= target]
                if not base_rows or not ahead_rows:
                    continue
                base = base_rows[-1]
                if base <= 0:
                    continue
                returns.append((ahead_rows[-1] / base - 1.0) * 100.0)
            if len(returns) < 5:
                continue
            ordered = sorted(returns)
            mid = len(ordered) // 2
            median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
            entry = {
                "horizon": horizon,
                "avg_pct": sum(returns) / len(returns),
                "med_pct": median,
                "hit_rate": sum(1 for value in returns if value > 0) / len(returns),
                "n_symbols": len(returns),
            }
            conn.execute(
                "INSERT INTO macd_market_baseline"
                "(bucket_ts, horizon, avg_pct, med_pct, hit_rate, n_symbols, filled_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT (bucket_ts, horizon) DO UPDATE SET "
                "avg_pct=EXCLUDED.avg_pct, med_pct=EXCLUDED.med_pct, "
                "hit_rate=EXCLUDED.hit_rate, n_symbols=EXCLUDED.n_symbols, "
                "filled_at=EXCLUDED.filled_at",
                (int(bucket_ts), horizon, entry["avg_pct"], entry["med_pct"],
                 entry["hit_rate"], int(entry["n_symbols"]), time.time()))
            have[horizon] = entry
        conn.commit()
    return list(have.values())


async def record_macd_monitor_alert(created_at: float, symbol: str, kind: str,
                                    score: int | None = None, jump_min: int | None = None,
                                    price: float | None = None,
                                    signals: dict | list | None = None,
                                    early_score: int | None = None) -> int | None:
    """Bir MACD alarmını kaydet. Dönen değer satır id'si.

    `early_score` (B3) yalnız ERKEN alarmlarda dolan TANIMLAYICI 0-100 skordur;
    eşik olarak kullanılmaz, replay'de karşılaştırma ekseni olsun diye saklanır.
    """
    payload = json.dumps(signals) if signals is not None else None

    def op(conn):
        _ensure_macd_evidence_schema(conn)
        row = conn.execute(
            "INSERT INTO macd_monitor_alerts"
            "(created_at, symbol, kind, score, jump_min, price, signals, early_score) "
            "VALUES(?,?,?,?,?,?,?,?) RETURNING id",
            (float(created_at), str(symbol).upper(), str(kind), score, jump_min,
             price, payload, early_score),
        ).fetchone()
        conn.commit()
        return int(row[0]) if row else None

    try:
        return await _run_db(op)
    except Exception:
        # Kanıt katmanı kritik yol DEĞİL: kayıt başarısız olsa da alarm akışı
        # bozulmamalı (uyarı yalnızca loglanır).
        logging.getLogger("scalper.database").debug(
            "macd_monitor_alerts kaydı başarısız: %s", symbol, exc_info=True)
        return None


async def list_macd_monitor_alerts(limit: int = 100, symbol: str | None = None) -> list[dict]:
    """Son alarmlar (en yeni önce)."""
    limit = max(1, min(1000, int(limit)))
    def op(conn):
        if symbol:
            rows = conn.execute(
                "SELECT * FROM macd_monitor_alerts WHERE symbol=? "
                "ORDER BY created_at DESC LIMIT ?", (str(symbol).upper(), limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM macd_monitor_alerts ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["signals"] = _json_value(item.get("signals"), None)
            out.append(item)
        return out

    return await _run_db(op)


async def list_macd_monitor_alerts_since(since: float, until: float,
                                         limit: int = 20000) -> list[dict]:
    """Zaman pencereli MACD alarm kanıtı (ARTAN sırada — replay/parity için).

    `list_macd_monitor_alerts` en-yeni-ilk sıralar ve pencere parametresi
    almaz; birleşik sinyal replay'i (2026-09-17) üç journal'ı AYNI okuma
    semantiğiyle (zaman pencereli + artan) okumak zorundadır — aksi halde
    akışlar farklı dönemleri kapsar ve füzyon karşılaştırması geçersiz olur.
    """
    def op(conn):
        rows = conn.execute(
            "SELECT * FROM macd_monitor_alerts "
            "WHERE created_at >= %s AND created_at <= %s "
            "ORDER BY created_at ASC LIMIT %s",
            (float(since), float(until), int(limit))).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["signals"] = _json_value(item.get("signals"), None)
            out.append(item)
        return out

    return await _run_db(op)


# ---------------------------------------------------------------------------
# Yükseliş sinyalleri kanıt katmanı (R2, 2026-09-14) — `rising_alerts`
# ---------------------------------------------------------------------------
def _ensure_rising_evidence_schema(conn) -> None:
    """Koşan dağıtımda tabloyu idempotent hazırla (migration sha'sına bağımlı kalma)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rising_alerts (
          id BIGSERIAL PRIMARY KEY,
          created_at DOUBLE PRECISION NOT NULL,
          symbol TEXT NOT NULL,
          kind TEXT NOT NULL,
          score DOUBLE PRECISION,
          early_score INTEGER,
          strength DOUBLE PRECISION,
          green INTEGER,
          proximity DOUBLE PRECISION,
          gap_atr DOUBLE PRECISION,
          signals JSONB,
          price DOUBLE PRECISION,
          expected_price DOUBLE PRECISION,
          target_pct DOUBLE PRECISION,
          tf TEXT,
          source TEXT,
          notified BOOLEAN NOT NULL DEFAULT FALSE,
          sent_via_push BOOLEAN NOT NULL DEFAULT FALSE,
          auto_paper_trade_id INTEGER,
          outcome_state TEXT NOT NULL DEFAULT 'pending',
          mfe_pct DOUBLE PRECISION,
          mae_pct DOUBLE PRECISION,
          peak_at DOUBLE PRECISION
        )""")


async def record_rising_alert(item: dict) -> int | None:
    """Bir yükseliş sinyalini kanıt tablosuna yaz; satır id'si döner.

    Kanıt katmanı KRİTİK YOL DEĞİL (MACD muadili ile aynı ilke): yazma başarısız
    olsa bile bildirim/otonom akışı bozulmaz, yalnız debug loglanır.
    """
    def op(conn):
        _ensure_rising_evidence_schema(conn)
        row = conn.execute(
            "INSERT INTO rising_alerts"
            "(created_at, symbol, kind, score, early_score, strength, green,"
            " proximity, gap_atr, signals, price, expected_price, target_pct, tf, source,"
            " notified, sent_via_push, outcome_state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending') RETURNING id",
            (
                float(item.get("created_at") or time.time()),
                str(item.get("symbol") or "?").upper(),
                str(item.get("kind") or "erken"),
                item.get("score"),
                (int(item["early_score"]) if item.get("early_score") is not None else None),
                item.get("strength"),
                (int(item["green"]) if item.get("green") is not None else None),
                (item.get("signals") or {}).get("proximity") if isinstance(item.get("signals"), dict) else None,
                (item.get("signals") or {}).get("gap_atr") if isinstance(item.get("signals"), dict) else None,
                json.dumps(item.get("signals"), default=str) if item.get("signals") is not None else None,
                item.get("price"),
                item.get("expected_price"),
                item.get("target_pct"),
                item.get("tf"),
                item.get("source"),
                bool(item.get("notified", False)),
                bool(item.get("sent_via_push", False)),
            ),
        ).fetchone()
        conn.commit()
        return int(row[0]) if row else None

    try:
        return await _run_db(op)
    except Exception:
        logging.getLogger("scalper.database").debug(
            "rising_alerts kaydı başarısız: %s", item.get("symbol"), exc_info=True)
        return None


async def mark_rising_alert_notified(alert_id: int, sent_via_push: bool = False) -> None:
    """Bildirim durumunu işaretle (push teslimi DÜRÜST yansıtılır)."""
    if not alert_id:
        return
    def op(conn):
        conn.execute(
            "UPDATE rising_alerts SET notified=TRUE, sent_via_push=? WHERE id=?",
            (bool(sent_via_push), int(alert_id)))
        conn.commit()
    try:
        await _run_db(op)
    except Exception:
        logging.getLogger("scalper.database").debug(
            "rising_alerts bildirim etiketi güncellenemedi: %s", alert_id, exc_info=True)


async def mark_rising_alert_trade(alert_id: int, trade_id: int) -> None:
    """Sinyalin açtığı otonom paper işlemini bağla (kanıt ↔ işlem izlenebilirliği)."""
    if not alert_id or not trade_id:
        return
    def op(conn):
        conn.execute("UPDATE rising_alerts SET auto_paper_trade_id=? WHERE id=?",
                     (int(trade_id), int(alert_id)))
        conn.commit()
    try:
        await _run_db(op)
    except Exception:
        logging.getLogger("scalper.database").debug(
            "rising_alerts işlem bağı güncellenemedi: %s", alert_id, exc_info=True)


async def list_rising_alerts(limit: int = 100, kind: str | None = None,
                             symbol: str | None = None) -> list[dict]:
    """Son yükseliş sinyalleri (en yeni önce)."""
    limit = max(1, min(1000, int(limit)))
    def op(conn):
        _ensure_rising_evidence_schema(conn)
        sql = "SELECT * FROM rising_alerts"
        params: list = []
        where = []
        if kind:
            where.append("kind=?")
            params.append(str(kind))
        if symbol:
            where.append("symbol=?")
            params.append(str(symbol).upper())
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["signals"] = _json_value(item.get("signals"), None)
            out.append(item)
        return out

    return await _run_db(op)


async def list_rising_alerts_since(since_epoch, until_epoch=None, limit: int = 20000):
    """Zaman penceresine göre yükseliş sinyalleri (BİRLEŞİK RADAR replay).

    NEDEN AYRI FONKSİYON: `list_rising_alerts` **EN YENİ** satırları döndürür
    (`ORDER BY created_at DESC LIMIT ?`). Replay onu 1000 satırla çağırınca
    akış pencerenin SONUNDAN doluyordu; velocity okuyucusu ise ARTAN sırada
    ilk 20000'i aldığı için pencerenin BAŞINDAN doluyordu. İki akış böylece
    AYRI dönemleri kapsıyordu (ölçüldü: aralarında ~25 saat boşluk) →
    `confluence` yapısal olarak 0 çıkıyor ve raporun LIFT satırı iki FARKLI
    dönemi kıyaslıyordu.

    Dönüş: `created_at` ARTAN sırada (velocity okuyucusuyla AYNI semantik).
    """
    def op(conn):
        _ensure_rising_evidence_schema(conn)
        clauses = ["created_at >= ?"]
        values: list = [float(since_epoch)]
        if until_epoch is not None:
            clauses.append("created_at <= ?")
            values.append(float(until_epoch))
        values.append(max(1, min(int(limit), 200000)))
        rows = conn.execute(
            f"SELECT * FROM rising_alerts WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at ASC LIMIT ?", values).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["signals"] = _json_value(item.get("signals"), None)
            out.append(item)
        return out

    return await _run_db(op)


async def journal_coverage() -> dict:
    """İki journal'ın GERÇEK zaman aralığı (pencere bağımsız).

    NEDEN: replay "0 sinyal" ürettiğinde tek soru şudur — pencere mi veriyi
    kaçırıyor, yoksa journal gerçekten boş mu? Bunu anlamak için penceresiz
    min/max/count gerekir. Gerçek olay (2026-09-17): 24 saatlik koşum BOŞ CSV
    üretti (yalnız başlık); journal'ın son satırı pencereden eskiyse bu tamamen
    normaldir ve raporda açıkça yazmalıdır.
    """
    def op(conn):
        out: dict = {}
        for key, table in (("velocity", "velocity_candidates"), ("rising", "rising_alerts")):
            try:
                if table == "rising_alerts":
                    _ensure_rising_evidence_schema(conn)
                row = conn.execute(
                    f"SELECT MIN(created_at) AS a, MAX(created_at) AS b, COUNT(*) AS n "
                    f"FROM {table}").fetchone()
                item = dict(row) if row is not None else {}
                out[f"{key}_earliest"] = item.get("a")
                out[f"{key}_latest"] = item.get("b")
                out[f"{key}_count"] = int(item.get("n") or 0)
            except Exception as exc:
                out[f"{key}_error"] = f"{type(exc).__name__}: {exc}"
        return out

    return await _run_db(op)


async def get_rising_stats(days: float = 7.0) -> dict:
    """Yükseliş sinyali kalibrasyon özeti — Raporlar sekmesi için.

    Dönen alanlar: toplam sinyal, sınıf dağılımı, ölçülen (evaluate edilmiş)
    sayısı, **isabet oranı** (`touched` = MFE hedefi aştı), ortalama MFE/MAE.
    İsabet, sinyalin `target_pct`ine göre değerlendirilir; henüz ölçülmemiş
    satırlar orana GİRMEZ (uydurma başarı yok).
    """
    since = time.time() - max(0.0, float(days)) * 86400.0
    def op(conn):
        _ensure_rising_evidence_schema(conn)
        rows = conn.execute(
            "SELECT kind, target_pct, mfe_pct, mae_pct, outcome_state, created_at, peak_at "
            "FROM rising_alerts WHERE created_at >= ?", (since,)).fetchall()
        total = 0
        by_kind: dict[str, int] = {}
        measured = 0
        hits = 0
        mfe_values: list[float] = []
        mae_values: list[float] = []
        for row in rows:
            item = dict(row)
            total += 1
            kind = str(item.get("kind") or "?")
            by_kind[kind] = by_kind.get(kind, 0) + 1
            mfe = item.get("mfe_pct")
            if mfe is None:
                continue
            measured += 1
            mfe_values.append(float(mfe))
            if item.get("mae_pct") is not None:
                mae_values.append(float(item["mae_pct"]))
            target = item.get("target_pct")
            if target is not None and float(mfe) >= float(target):
                hits += 1
        def _avg(values):
            return round(sum(values) / len(values), 3) if values else None
        return {
            "days": float(days),
            "total": total,
            "by_kind": by_kind,
            "measured": measured,
            "hits": hits,
            "hit_rate_pct": round(100.0 * hits / measured, 2) if measured else None,
            "avg_mfe_pct": _avg(mfe_values),
            "avg_mae_pct": _avg(mae_values),
        }

    return await _run_db(op)


# Yükseliş sinyali sonuç ölçümü (2026-09-17). Ufuk: 30 dk (MACD kanıtı ile
# AYNI pencere). Mum yoksa satır hemen expire EDİLMEZ — backfill mumları
# getirene dek bekler; ömür sınırı dolduğunda 'expired' yazılır.
_RISING_OUTCOME_WINDOW_SEC = 30 * 60.0
_RISING_OUTCOME_EXPIRE_SEC = 6 * 3600.0


async def fill_rising_alert_outcomes(limit: int = 200) -> tuple[int, list[dict]]:
    """Bekleyen yükseliş sinyallerinin MFE/MAE sonucunu 5m mumlarla doldur.

    NEDEN VAR: `rising_alerts` tablosuna `mfe_pct`/`mae_pct`/`outcome_state`
    kolonları eklendi ama bunları dolduran HİÇBİR döngü yoktu → Raporlar >
    YÜKSELİŞ EĞİLİMİ sekmesindeki Sonuç sütunu her satırda sonsuza dek
    BEKLİYOR gösteriyordu (2026-09-17 teşhisi; kullanıcı raporu).

    Ölçüm semantiği MACD kanıt döngüsüyle AYNI (bkz. `fill_macd_monitor_alert_
    outcomes`): yalnız t0'dan SONRA açılan kapanmış 5m mumlar ölçüye girer
    (sinyal anının parsiyel mumu hariç), pencere t0+30dk'dır. Taban = sinyalin
    KENDİ fiyatı (bildirim anı); yoksa t0'a eşit/önce açılmış son kapanmış mum.

    Pencere tamamını kapsayan mum gelmeden satır MÜHÜRLENMEZ (erken MFE yalnız
    alt sınır olurdu). Sinyal DAVRANIŞINI değiştirmez; yalnız kanıt zenginleştirir.

    DÖNÜŞ: (doldurulan satır sayısı, öğrenme kayıtları listesi).
    Her kayıt: {"symbol": str, "success": bool, "achieved_pct": float}.
    Çağıran `record_symbol_target_outcome` ile sembol hedef durumunu günceller.
    """
    def op(conn):
        _ensure_rising_evidence_schema(conn)
        now = time.time()
        # Yalnız ufku (30 dk) dolmuş satırlar adaydır — erken ölçüm yok.
        pending = conn.execute(
            "SELECT id, created_at, symbol, price, target_pct FROM rising_alerts "
            "WHERE outcome_state='pending' AND created_at <= ? "
            "ORDER BY created_at ASC LIMIT ?",
            (now - _RISING_OUTCOME_WINDOW_SEC,
             max(1, min(2000, int(limit))))).fetchall()
        filled = 0
        touched = False
        learn_entries: list[dict] = []
        for row in pending:
            values = dict(row)
            alert_id = values["id"]
            created = float(values.get("created_at") or 0)
            try:
                symbol = values["symbol"]
                target_pct = float(values.get("target_pct") or 0.0)
                t0_ms = created * 1000.0
                window_end_ms = t0_ms + _RISING_OUTCOME_WINDOW_SEC * 1000.0
                candles = conn.execute(
                    "SELECT open_time, high, low, close FROM historical_candles "
                    "WHERE symbol=? AND timeframe='5m' AND open_time >= ? AND open_time <= ? "
                    "ORDER BY open_time",
                    (symbol, t0_ms - _MACD_BAR_MS, window_end_ms + _MACD_BAR_MS)).fetchall()
                rows = [(float(dict(c)["open_time"]), float(dict(c)["high"] or 0),
                         float(dict(c)["low"] or 0), float(dict(c)["close"])) for c in candles]
                expired = now - created > _RISING_OUTCOME_EXPIRE_SEC
                if not rows:
                    if expired:
                        conn.execute(
                            "UPDATE rising_alerts SET outcome_state='expired', peak_at=? WHERE id=?",
                            (now, alert_id))
                        filled += 1
                        touched = True
                    continue
                # Taban: sinyalin kendi fiyatı; yoksa t0 öncesi son kapanmış mum.
                base = values.get("price")
                try:
                    base = float(base) if base is not None else None
                except (TypeError, ValueError):
                    base = None
                if base is None or base <= 0:
                    prior = [close for stamp, _h, _l, close in rows
                             if stamp <= t0_ms and close > 0]
                    base = prior[-1] if prior else None
                if base is None or base <= 0:
                    if expired:
                        conn.execute(
                            "UPDATE rising_alerts SET outcome_state='expired', peak_at=? WHERE id=?",
                            (now, alert_id))
                        filled += 1
                        touched = True
                    continue
                # Pencere tamamını kapsayan KAPANMIŞ mum yoksa mühürleme —
                # parsiyel serinin MFE'si alt sınır olurdu, kesin sonuç değil.
                if rows[-1][0] + _MACD_BAR_MS < window_end_ms:
                    continue
                after = [(high, low) for stamp, high, low, _close in rows
                         if t0_ms < stamp <= window_end_ms]
                highs = [high for high, _low in after if high > 0]
                lows = [low for _high, low in after if low > 0]
                if not highs:
                    continue
                mfe = (max(highs) / base - 1.0) * 100.0
                mae = (min(lows) / base - 1.0) * 100.0 if lows else None
                conn.execute(
                    "UPDATE rising_alerts SET mfe_pct=?, mae_pct=?, "
                    "outcome_state='filled', peak_at=? WHERE id=?",
                    (round(mfe, 4), round(mae, 4) if mae is not None else None,
                     now, alert_id))
                filled += 1
                touched = True
                # SELF-LEARNING: sembol hedef durumunu gerçekleşen MFE ile güncelle.
                success = target_pct > 0 and mfe >= target_pct
                learn_entries.append({
                    "symbol": symbol,
                    "success": success,
                    "achieved_pct": round(mfe, 3),
                })
            except Exception:
                # Tek bozuk satır partiyi iptal etmemeli (MACD muadili F-09 ilkesi).
                logger.debug("yükseliş sonucu doldurulamadı (id=%s)",
                             alert_id, exc_info=True)
        if touched:
            conn.commit()
        return filled, learn_entries

    filled, learn_entries = await _run_db(op)
    for entry in learn_entries:
        try:
            await record_symbol_target_outcome(
                entry["symbol"], success=entry["success"], achieved_pct=entry["achieved_pct"])
        except Exception:
            logger.debug("rising sonucu hedef öğrenme kaydedilemedi %s", entry["symbol"], exc_info=True)
    return filled, learn_entries


_MACD_BAR_MS = 5 * 60_000  # historical_candles yalnız kapanmış 5m bar tutar


def _macd_forward_outcomes(rows, base: float, t0_ms: float, now_ms: float):
    """F-02: alarmın 5m/15m/30m ileri getirisi + MFE/MAE (saf fonksiyon).

    `rows`: [(open_time_ms, high, low, close)] — 5m kapanmış mumlar.
    Dönüş: (updates, mfe, mae) — `updates` YALNIZ hedef ana gerçekten
    ulaşılmış ufukları içerir.

    Eski hata: `candidates = [close for ... if stamp <= target]` hedef ana
    ulaşılıp ulaşılmadığını kontrol etmiyordu. Pencere henüz dolmamışken
    (ör. 4,5 dk geçmiş) 5m/15m/30m hepsi SON mumun AYNI kapanışını alıyor ve
    satır 'filled' olarak mühürleniyordu → tüm LIFT/isabet ölçümü çöp.

    Yeni kural: bir ufuk ancak kapanışı hedefi KAPSAYAN (open_time + bar_ms >=
    target) ve o bar KAPANMIŞ (open_time + bar_ms <= now) ise yazılır.
    """
    updates: dict[str, float] = {}
    for name, minutes in _MACD_HORIZON_MINUTES:
        column = f"outcome_{name}_pct"
        target = t0_ms + minutes * 60_000
        covered = [r for r in rows if r[0] <= target]
        if not covered:
            continue
        stamp, _high, _low, close = covered[-1]
        if stamp + _MACD_BAR_MS < target:
            continue
        if stamp + _MACD_BAR_MS > now_ms:
            continue
        updates[column] = (close / base - 1.0) * 100.0
    # MFE/MAE: yalnız alarm SONRASI barlar (t0'dan sonra açılanlar) — alarm
    # anını içeren kısmi barın uçları geriye dönük olduğundan ölçüye katılmaz.
    window_end_ms = t0_ms + 30 * 60_000
    after = [(high, low) for stamp, high, low, _close in rows
             if t0_ms < stamp <= window_end_ms]
    mfe = mae = None
    highs_after = [high for high, _low in after if high > 0]
    lows_after = [low for _high, low in after if low > 0]
    if highs_after:
        mfe = (max(highs_after) / base - 1.0) * 100.0
    if lows_after:
        mae = (min(lows_after) / base - 1.0) * 100.0
    return updates, mfe, mae


async def fill_macd_monitor_alert_outcomes(limit: int = 500) -> int:
    """Bekleyen alarmların 5m/15m/30m ileri getirilerini + MFE/MAE'yi doldur.

    Fiyat kaynağı: `historical_candles` (5m). Taban artık evren tabanıyla AYNI
    çapaya bağlanır: t0'a eşit/önce açılmış **son kapanmış** mumun kapanışı
    (F-03). Yalnız hiç mum yoksa canlı tick'e, o da yoksa ilk ileri mumun
    kapanışına düşülür. Hangi kaynağın kullanıldığı `base_source` sütununa
    yazılır (`closed_candle` / `live_tick` / `first_candle`). `price` sütunu
    (görüntüleme) DEĞİŞTİRİLMEZ. Pencere tamamen geçmiş ve veri yoksa kayıt
    'expired' işaretlenir.

    A3: ayrıca alarm sonrası 30 dk içindeki **MFE** (en yüksek lehte hareket) ve
    **MAE** (en düşük aleyhte hareket) yüzde olarak yazılır; bunlar "kâr
    potansiyeli vs maksimum ters hareket" ölçüsüdür.

    A2: alarmın 5m kovası için evren tabanı (baseline) üretilir; lift hesabı
    `macd_monitor_alert_stats` içinde bu tabana göre yapılır.

    F-09: her satır kendi try/except'inde işlenir ve deneysel `outcome_attempts`
    sayacı ile sınırlanır. `base <= 0` satırları pencere dolunca expire edilir;
    tek bir bozuk satır ne tüm partiyi iptal eder ne de sonsuza dek `pending`
    kalır.
    """
    max_attempts = _MACD_OUTCOME_MAX_ATTEMPTS

    def op(conn):
        _ensure_macd_evidence_schema(conn)
        pending = conn.execute(
            "SELECT id, created_at, symbol, kind, price, "
            "COALESCE(outcome_attempts, 0) AS outcome_attempts "
            "FROM macd_monitor_alerts "
            "WHERE outcome_state='pending' AND COALESCE(outcome_attempts, 0) < ? "
            "ORDER BY created_at ASC LIMIT ?",
            (max_attempts, max(1, min(5000, int(limit))))).fetchall()
        filled = 0
        touched = False
        now = time.time()
        baseline_buckets: set[int] = set()
        for row in pending:
            values = dict(row)
            alert_id = values["id"]
            created = float(values["created_at"] or 0)
            attempts = int(values.get("outcome_attempts") or 0)
            try:
                symbol = values["symbol"]
                base_price = values.get("price")
                t0_ms = created * 1000.0
                window_end_ms = t0_ms + 30 * 60_000

                candles = conn.execute(
                    "SELECT open_time, high, low, close FROM historical_candles "
                    "WHERE symbol=? AND timeframe='5m' AND open_time >= ? AND open_time <= ? "
                    "ORDER BY open_time",
                    (symbol, t0_ms - 5 * 60_000, window_end_ms + 5 * 60_000)).fetchall()
                rows = [(float(dict(c)["open_time"]), float(dict(c)["high"] or 0),
                         float(dict(c)["low"] or 0), float(dict(c)["close"])) for c in candles]

                if not rows:
                    if now - created > _MACD_ALERT_OUTCOME_WINDOW_SEC:
                        conn.execute(
                            "UPDATE macd_monitor_alerts SET outcome_state='expired', filled_at=? WHERE id=?",
                            (now, alert_id))
                        filled += 1
                        touched = True
                    continue

                # F-03: evren tabanı `_baseline_rows_for_bucket` içindeki
                # `base_rows[-1]` (stamp <= t0 olan son kapanmış mum) ile AYNI
                # çapayı kullanır; böylece LIFT baz sürüklenmesinden arınır.
                prior_closes = [close for stamp, _high, _low, close in rows if stamp <= t0_ms]
                if prior_closes:
                    base = prior_closes[-1]
                    base_source = "closed_candle"
                elif base_price:
                    base = float(base_price)
                    base_source = "live_tick"
                else:
                    base = rows[0][3]
                    base_source = "first_candle"

                if base <= 0:
                    # F-09: ESKİDEN koşulsuz `continue` idi → sonsuza dek
                    # `pending` kalıp partiyi bloke ediyordu. Artık pencere
                    # dolunca (veya deneme sınırında) expire edilir.
                    if now - created > _MACD_ALERT_OUTCOME_WINDOW_SEC or attempts + 1 >= max_attempts:
                        conn.execute(
                            "UPDATE macd_monitor_alerts SET outcome_state='expired', "
                            "base_source=?, outcome_attempts=?, filled_at=? WHERE id=?",
                            (base_source, attempts + 1, now, alert_id))
                        filled += 1
                    else:
                        conn.execute(
                            "UPDATE macd_monitor_alerts SET outcome_attempts=? WHERE id=?",
                            (attempts + 1, alert_id))
                    touched = True
                    continue

                # F-02: saf yardımcı — yalnız hedef ana ulaşılmış ufukları üretir.
                updates, mfe, mae = _macd_forward_outcomes(rows, base, t0_ms, now * 1000.0)
                if len(updates) == len(_MACD_HORIZON_MINUTES):
                    conn.execute(
                        "UPDATE macd_monitor_alerts SET outcome_5m_pct=?, outcome_15m_pct=?, "
                        "outcome_30m_pct=?, mfe_pct=?, mae_pct=?, outcome_state='filled', "
                        "base_source=?, filled_at=? WHERE id=?",
                        (updates["outcome_5m_pct"], updates["outcome_15m_pct"],
                         updates["outcome_30m_pct"], mfe, mae, base_source, now, alert_id))
                    filled += 1
                    touched = True
                    baseline_buckets.add(_macd_bucket(created))
                elif now - created > _MACD_ALERT_OUTCOME_WINDOW_SEC or attempts + 1 >= max_attempts:
                    conn.execute(
                        "UPDATE macd_monitor_alerts SET outcome_state='expired', "
                        "base_source=?, outcome_attempts=?, filled_at=? WHERE id=?",
                        (base_source, attempts + 1, now, alert_id))
                    filled += 1
                    touched = True
                else:
                    conn.execute(
                        "UPDATE macd_monitor_alerts SET outcome_attempts=? WHERE id=?",
                        (attempts + 1, alert_id))
                    touched = True
            except Exception:
                # F-09: tek bozuk satırlık hata TÜM doldurma partisini iptal
                # etmemeli. Satırı atla, sayacı artır; sınırda veya pencere
                # dolduğunda expire et.
                attempts += 1
                logger.debug("macd alarm sonucu doldurulamadı (id=%s)", alert_id, exc_info=True)
                try:
                    if now - created > _MACD_ALERT_OUTCOME_WINDOW_SEC or attempts >= max_attempts:
                        conn.execute(
                            "UPDATE macd_monitor_alerts SET outcome_state='expired', "
                            "outcome_attempts=?, filled_at=? WHERE id=?",
                            (attempts, now, alert_id))
                        filled += 1
                    else:
                        conn.execute(
                            "UPDATE macd_monitor_alerts SET outcome_attempts=? WHERE id=?",
                            (attempts, alert_id))
                    touched = True
                except Exception:
                    logger.debug("macd alarm deneme sayacı güncellenemedi (id=%s)",
                                 alert_id, exc_info=True)
        # A2: sonucu kesinleşen alarmların kovaları için evren tabanını hazırla
        # (üretim anında değil, doldurma anında — alarm akışını yavaşlatmaz).
        for bucket in sorted(baseline_buckets)[:50]:
            try:
                _baseline_rows_for_bucket(conn, bucket)
            except Exception:
                logger.debug(
                    "macd taban hesabı başarısız (kova %s)", bucket, exc_info=True)
        if touched:
            conn.commit()
        return filled

    return await _run_db(op)


_ALERT_HORIZONS = (("outcome_5m_pct", "5m"), ("outcome_15m_pct", "15m"),
                   ("outcome_30m_pct", "30m"))


def _new_alert_bucket() -> dict:
    """Boş alarm kovası — n / skor / ufuk bazında getiri + lift + MFE-MAE."""
    return {"n": 0, "score_sum": 0.0, "score_n": 0,
            "esc_sum": 0.0, "esc_n": 0,
            "mfe_sum": 0.0, "mfe_n": 0, "mae_sum": 0.0, "mae_n": 0}


def _alert_bucket_add(bucket: dict, values: dict, baselines: dict | None = None) -> None:
    """Tek alarm satırını bir kovaya işle (n / skor / ufuk bazında isabet + lift).

    `baselines`: {"5m": {"avg_pct":…, "hit_rate":…}, …} — alarmın 5m kovasına ait
    evren tabanı. Varsa her ufuk için `lift` (= alarm getirisi − evren ortalaması)
    ve `hit_lift` (= isabet − evren pozitif oranı) biriktirilir.
    """
    bucket["n"] += 1
    if values.get("score") is not None:
        bucket["score_sum"] += float(values["score"])
        bucket["score_n"] += 1
    if values.get("early_score") is not None:
        bucket["esc_sum"] += float(values["early_score"])
        bucket["esc_n"] += 1
    mfe = values.get("mfe_pct")
    if mfe is not None:
        bucket["mfe_sum"] += float(mfe)
        bucket["mfe_n"] += 1
    mae = values.get("mae_pct")
    if mae is not None:
        bucket["mae_sum"] += float(mae)
        bucket["mae_n"] += 1
    for column, label in _ALERT_HORIZONS:
        value = values.get(column)
        if value is None:
            continue
        slot = bucket.setdefault(label, {"n": 0, "sum": 0.0, "wins": 0,
                                         "lift_sum": 0.0, "lift_n": 0,
                                         "base_hit_sum": 0.0, "base_hit_n": 0})
        slot["n"] += 1
        slot["sum"] += float(value)
        if float(value) > 0:
            slot["wins"] += 1
        base = (baselines or {}).get(label)
        if base and base.get("avg_pct") is not None:
            slot["lift_sum"] += float(value) - float(base["avg_pct"])
            slot["lift_n"] += 1
        if base and base.get("hit_rate") is not None:
            slot["base_hit_sum"] += float(base["hit_rate"])
            slot["base_hit_n"] += 1


def _alert_bucket_out(bucket: dict) -> dict:
    """İç kovayı dışa verilecek özete çevir."""
    entry: dict = {"n": bucket["n"]}
    if bucket.get("score_n"):
        entry["avg_score"] = round(bucket["score_sum"] / bucket["score_n"], 1)
    if bucket.get("esc_n"):
        entry["avg_early_score"] = round(bucket["esc_sum"] / bucket["esc_n"], 1)
    if bucket.get("mfe_n"):
        entry["avg_mfe"] = round(bucket["mfe_sum"] / bucket["mfe_n"], 3)
    if bucket.get("mae_n"):
        entry["avg_mae"] = round(bucket["mae_sum"] / bucket["mae_n"], 3)
    for _column, label in _ALERT_HORIZONS:
        slot = bucket.get(label)
        if not slot or not slot["n"]:
            continue
        horizon = {
            "n": slot["n"],
            "avg_pct": round(slot["sum"] / slot["n"], 3),
            "hit_rate": round(slot["wins"] / slot["n"], 3),
        }
        if slot.get("lift_n"):
            horizon["avg_lift"] = round(slot["lift_sum"] / slot["lift_n"], 3)
        if slot.get("base_hit_n"):
            horizon["base_hit_rate"] = round(slot["base_hit_sum"] / slot["base_hit_n"], 3)
            horizon["hit_lift"] = round(horizon["hit_rate"] - horizon["base_hit_rate"], 3)
        entry[label] = horizon
    return entry


def _baseline_map(conn, buckets: set[int]) -> dict[int, dict]:
    """Verilen kovalar için {bucket: {"5m": {...}, …}} haritası — SALT OKUMA.

    V-04: eskiden eksik kovalar burada tembel ÜRETİLİR ve `COMMIT` edilirdi;
    yani bir istatistik GET'i DDL/INSERT/COMMIT yapıyor, `ALTER TABLE` ile
    ACCESS EXCLUSIVE lock alıp alarm yazma yolunu bloke ediyor ve okuma yolu
    saflığı kuralını ihlal ediyordu. Tabanlar artık yalnız yazma yolunda
    (`fill_macd_monitor_alert_outcomes`) üretilir; burada sadece depodan okunur.
    Eksik kova liftsiz görünür (uydurulmaz).
    """
    if not buckets:
        return {}
    wanted = sorted(int(b) for b in buckets)
    stored: dict[int, dict] = {}
    for chunk_start in range(0, len(wanted), 200):
        chunk = wanted[chunk_start:chunk_start + 200]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT bucket_ts, horizon, avg_pct, med_pct, hit_rate, n_symbols "
            f"FROM macd_market_baseline WHERE bucket_ts IN ({placeholders})",
            tuple(chunk)).fetchall()
        for row in rows:
            item = dict(row)
            stored.setdefault(int(item["bucket_ts"]), {})[str(item["horizon"])] = {
                "avg_pct": float(item["avg_pct"]),
                "med_pct": float(item["med_pct"]),
                "hit_rate": float(item["hit_rate"]),
                "n_symbols": int(item["n_symbols"]),
            }
    return stored


async def macd_monitor_alert_stats(days: int = 30) -> dict:
    """Alarm isabet özeti: tür + ÖNCÜ bazında getiri, LİFT, isabet ve MFE/MAE.

    Yalnızca sonucu kesinleşmiş ('filled') kayıtlar sayılır.

    `kinds`  → alarm türü bazında (jump / early).
    `precursors` → **erken alarmın hangi öncüsü** işe yarıyor? Kayıtlı
      `signals.early_signals` listesindeki her etiket için ayrı kova; bir alarm
      birden fazla öncüyle geldiyse her birine sayılır (kotalar toplanabilir,
      bu yüzden `n` toplamı alarm sayısından büyük olabilir).
    `baseline` → son `days` gün için evren tabanı özeti (kova ortalaması).

    Her ufukta `avg_lift` = alarm ortalama getirisi − aynı 5m kovasındaki evren
    ortalama getirisi; `hit_lift` = isabet − evren pozitif oranı. **Karar
    metriği lift'tir**, `avg_pct` tek başına iyi/kötü demez (A2).
    """
    since = time.time() - max(1, int(days)) * 86400.0

    def op(conn):
        # V-04: okuma yolu DDL/INSERT/COMMIT yapmaz; şema açılışta hazırlanır.
        try:
            rows = conn.execute(
                "SELECT created_at, kind, score, early_score, signals, outcome_5m_pct, "
                "outcome_15m_pct, outcome_30m_pct, mfe_pct, mae_pct FROM macd_monitor_alerts "
                "WHERE created_at >= ? AND outcome_state='filled'",
                (since,)).fetchall()
        except Exception:
            # Şema henüz genişlememişse eski sütun kümesiyle devam et.
            rows = conn.execute(
                "SELECT created_at, kind, score, signals, outcome_5m_pct, outcome_15m_pct, "
                "outcome_30m_pct FROM macd_monitor_alerts "
                "WHERE created_at >= ? AND outcome_state='filled'",
                (since,)).fetchall()
        buckets: dict[str, dict] = {}
        precursors: dict[str, dict] = {}
        entries = []
        for row in rows:
            values = dict(row)
            entry = {**values, "signals": _json_value(values.get("signals"), None)}
            entries.append(entry)
        baselines = _baseline_map(conn, {_macd_bucket(float(e["created_at"] or 0))
                                         for e in entries})
        for entry in entries:
            base = baselines.get(_macd_bucket(float(entry["created_at"] or 0)))
            kind = entry.get("kind") or "unknown"
            _alert_bucket_add(buckets.setdefault(kind, _new_alert_bucket()), entry, base)
            # Öncü kırılımı: yalnız erken alarmlar (jump'ta öncü yoktur).
            if kind != "early":
                continue
            signals = entry.get("signals")
            labels = signals.get("early_signals") if isinstance(signals, dict) else None
            for label in labels or []:
                _alert_bucket_add(
                    precursors.setdefault(str(label), _new_alert_bucket()), entry, base)
        pending = conn.execute(
            "SELECT COUNT(*) FROM macd_monitor_alerts WHERE outcome_state='pending'"
        ).fetchone()
        summary = {
            "days": int(days),
            "kinds": {k: _alert_bucket_out(b) for k, b in buckets.items()},
            "precursors": {k: _alert_bucket_out(b) for k, b in precursors.items()},
            "pending": int(pending[0]) if pending else 0,
            "baseline": _baseline_summary(baselines),
        }
        return summary

    return await _run_db(op)


async def macd_monitor_alert_conditional_stats(days: int = 30,
                                               dimension: str = "regime",
                                               min_n: int = 5) -> dict:
    """Aşama 4 — REJİM / SEANS bazında KOŞULLU istatistik (yalnızca ölçüm).

    Erken alarmların başarısı rejim (trend vs yatay; volatilite) ve seanstan
    (Binance TR likidite saatleri) etkilenebilir. Tek bir global isabet eşiği
    yerine rejime/seansa göre koşullu isabet-LİFT ölçmek, kanıtı çok daha
    ayrıştırıcı verir.

    `dimension` ∈ {"regime", "session"}: hücre etiketi `signals[dimension]`'dan
    okunur. Her gruba bir kova; her grup `n < min_n` ise global tabloyu
    kalabalık etmek yerine taşaya alınmaz — küçük gruplar UI'da boş durum
    gösterir. Sinyal davranışını DEĞİŞTİRMEZ (yalnız okurama).

    Dönüş: {"days", "dimension", "min_n", "groups": {etiket: bucket_out},
    "baseline": ...}.
    """
    since = time.time() - max(1, int(days)) * 86400.0
    dimension = str(dimension or "regime").lower()
    min_n = max(1, int(min_n))

    def op(conn):
        # V-04: okuma yolu DDL/INSERT/COMMIT yapmaz; şema açılışta hazırlanır.
        try:
            rows = conn.execute(
                "SELECT created_at, kind, signals, outcome_5m_pct, outcome_15m_pct, "
                "outcome_30m_pct, mfe_pct, mae_pct FROM macd_monitor_alerts "
                "WHERE created_at >= ? AND outcome_state='filled'",
                (since,)).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT created_at, kind, signals, outcome_5m_pct, outcome_15m_pct, "
                "outcome_30m_pct FROM macd_monitor_alerts "
                "WHERE created_at>= ? AND outcome_state='filled'",
                (since,)).fetchall()
        entries = []
        for row in rows:
            values = dict(row)
            signals = _json_value(values.get("signals"), None)
            values["signals"] = signals
            entries.append(values)
        baselines = _baseline_map(conn, {_macd_bucket(float(e["created_at"] or 0))
                                         for e in entries})
        groups: dict[str, dict] = {}
        addr = _alert_bucket_add
        for entry in entries:
            # Rejim/seç grupları yalnız ERKEN alarmları için anlamlıdır.
            if (entry.get("kind") or "unknown") != "early":
                continue
            signals = entry.get("signals")
            if not isinstance(signals, dict):
                continue
            label = signals.get(dimension) or "undef"
            base = baselines.get(_macd_bucket(float(entry["created_at"] or 0)))
            addr(groups.setdefault(str(label), _new_alert_bucket()), entry, base)
        out = {}
        for k, v in groups.items():
            entry = _alert_bucket_out(v)
            entry["low_sample"] = int(v["n"]) < min_n  # UI gri gösterir
            out[k] = entry
        return {
            "days": int(days),
            "dimension": dimension,
            "min_n": min_n,
            "groups": out,
            "baseline": _baseline_summary(baselines),
        }

    return await _run_db(op)


def _baseline_summary(baselines: dict[int, dict]) -> dict:
    """Kova tabanlarını ufuk bazında tek satıra indir (UI başlığı için)."""
    out: dict[str, dict] = {}
    for _bucket, mapped in baselines.items():
        for horizon, values in mapped.items():
            slot = out.setdefault(horizon, {"n_buckets": 0, "avg_sum": 0.0,
                                            "hit_sum": 0.0, "n_symbols": 0})
            slot["n_buckets"] += 1
            slot["avg_sum"] += float(values["avg_pct"])
            slot["hit_sum"] += float(values["hit_rate"])
            slot["n_symbols"] = max(slot["n_symbols"], int(values["n_symbols"]))
    return {
        horizon: {
            "buckets": slot["n_buckets"],
            "avg_pct": round(slot["avg_sum"] / slot["n_buckets"], 3),
            "hit_rate": round(slot["hit_sum"] / slot["n_buckets"], 3),
            "symbols": slot["n_symbols"],
        }
        for horizon, slot in out.items() if slot["n_buckets"]
    }


async def macd_monitor_alert_event_paths(days: int = 14, kind: str = "early",
                                        precursor: str | None = None,
                                        limit: int = 200) -> dict:
    """Olay çalışması (A3): alarm etrafında ortalama getiri YOLU + MFE/MAE.

    Her doldurulmuş alarm için t−10 … t+30 dk getiri yolu kapanmış 5m
    mumlarından yeniden hesaplanır (sızıntısız); sonra grup ortalaması alınır.
    `precursor` verilirse yalnız o erken öncüyle gelen alarmlar seçilir.

    Dönen: {"n", "offsets", "avg_path", "avg_mfe", "avg_mae", "rows"}.
    """
    offsets = (-10, -5, 0, 5, 10, 15, 20, 30)
    limit = max(1, min(1000, int(limit)))
    since = time.time() - max(1, int(days)) * 86400.0

    def op(conn):
        # V-04: okuma yolu DDL yapmaz; şema açılışta hazırlanır.
        rows = conn.execute(
            "SELECT id, created_at, symbol, kind, price, signals, mfe_pct, mae_pct "
            "FROM macd_monitor_alerts WHERE created_at >= ? AND outcome_state='filled' "
            "AND kind=? ORDER BY created_at DESC LIMIT ?",
            (since, str(kind), limit)).fetchall()

        # V-12: eskiden `path_for` her alarm için ayrı bir historical_candles
        # sorgusu atıyordu (1 + N, N<=1000). Sembol başına BİRLEŞİK zaman
        # aralığı tek sorguda çekilir; pencere dilimi Python'da alınır.
        windows: dict[str, list[float]] = {}
        for alert in rows:
            item = dict(alert)
            alert_symbol = str(item["symbol"])
            created_ms = float(item["created_at"] or 0) * 1000.0
            if alert_symbol and created_ms > 0:
                windows.setdefault(alert_symbol, []).append(created_ms)
        candle_index: dict[str, list[tuple[float, float]]] = {}
        if windows:
            symbols = list(windows)
            low = min(min(values) for values in windows.values()) - 15 * 60_000
            high = max(max(values) for values in windows.values()) + 35 * 60_000
            placeholders = ",".join(["%s"] * len(symbols))
            candle_rows = conn.execute(
                "SELECT symbol, open_time, close FROM historical_candles"
                f" WHERE symbol IN ({placeholders}) AND timeframe='5m'"
                " AND open_time >= %s AND open_time <= %s ORDER BY symbol, open_time",
                symbols + [low, high]).fetchall()
            for candle in candle_rows:
                item = dict(candle)
                candle_index.setdefault(str(item["symbol"]), []).append(
                    (float(item["open_time"]), float(item["close"] or 0)))

        def path_for(symbol: str, created: float, base_price):
            t0_ms = created * 1000.0
            series = [pair for pair in candle_index.get(symbol, [])
                      if t0_ms - 15 * 60_000 <= pair[0] <= t0_ms + 35 * 60_000]
            if not series:
                return None
            upto = [close for stamp, close in series if stamp <= t0_ms]
            base = float(base_price) if base_price else (upto[-1] if upto else None)
            if not base or base <= 0:
                return None
            path = []
            for offset in offsets:
                target = t0_ms + offset * 60_000
                candidates = [close for stamp, close in series if stamp <= target]
                if not candidates:
                    path.append(None)
                    continue
                path.append(round((candidates[-1] / base - 1.0) * 100.0, 3))
            return path

        collected: list[dict] = []
        for row in rows:
            item = dict(row)
            signals = _json_value(item.get("signals"), None)
            labels = signals.get("early_signals") if isinstance(signals, dict) else None
            if precursor and (not labels or precursor not in labels):
                continue
            path = path_for(str(item["symbol"]), float(item["created_at"] or 0),
                            item.get("price"))
            if not path:
                continue
            collected.append({
                "id": int(item["id"]),
                "symbol": str(item["symbol"]),
                "created_at": float(item["created_at"] or 0),
                "signals": labels or [],
                "mfe_pct": item.get("mfe_pct"),
                "mae_pct": item.get("mae_pct"),
                "path": path,
            })
        avg_path = []
        for position in range(len(offsets)):
            values = [row["path"][position] for row in collected
                      if row["path"][position] is not None]
            avg_path.append(round(sum(values) / len(values), 3) if values else None)
        mfes = [float(row["mfe_pct"]) for row in collected if row.get("mfe_pct") is not None]
        maes = [float(row["mae_pct"]) for row in collected if row.get("mae_pct") is not None]
        return {
            "kind": str(kind),
            "precursor": precursor,
            "n": len(collected),
            "offsets": list(offsets),
            "avg_path": avg_path,
            "avg_mfe": round(sum(mfes) / len(mfes), 3) if mfes else None,
            "avg_mae": round(sum(maes) / len(maes), 3) if maes else None,
            "rows": collected[:limit],
        }

    return await _run_db(op)


async def load_positions():
    def op(conn):
        positions = {}
        rows = conn.execute("SELECT * FROM positions").fetchall()
        for row in rows:
            values = dict(row)
            context = _json_value(values.get("entry_context"), {})
            runtime = context.get("_runtime") if isinstance(context.get("_runtime"), dict) else {}
            symbol = values.get("symbol")
            # trade_id normalde backfill_position_trade_ids() ile açılışta
            # doldurulur. Yine de eksikse burada yalnızca GEÇİCİ bir kimlik
            # üretilir; okuma yolu DB'ye yazmaz (disentanglement, Madde 21).
            trade_id = values.get("trade_id") or uuid.uuid4().hex
            positions[symbol] = {
                "side": values.get("side"), "entry_price": values.get("entry_price"), "stop_price": values.get("stop_price"),
                "take_profit": values.get("take_profit"), "peak_price": values.get("peak_price"), "breakeven_hit": bool(values.get("breakeven_hit")),
                "quantity": values.get("quantity"), "entry_time": values.get("entry_time"),
                "strategy": values.get("strategy"),
                "entry_context": context,
                "trade_id": trade_id,
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
        cutoff = _get_reset_cutoff_sync(conn)
        clauses, values = [], []
        if cutoff: clauses.append("exit_time > ?"); values.append(cutoff)
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
    trades = await get_trades(limit=None)
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
        cutoff = _get_reset_cutoff_sync(conn)
        clauses, values = [], []
        if cutoff: clauses.append("exit_time > ?"); values.append(cutoff)
        if symbol: clauses.append("symbol=?"); values.append(symbol.upper())
        if strategy: clauses.append("strategy=?"); values.append(strategy)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM trades{where}", values).fetchone()[0] or 0)
    return await _run_db(op)


async def get_portfolio_trade_metrics():
    """Return aggregate closed-trade metrics (reset_at sonrasi)."""
    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        where = ' WHERE exit_time > %s' if cutoff else ''
        params = (cutoff,) if cutoff else ()
        row = conn.execute("SELECT COUNT(*) AS closed_trades, COALESCE(SUM(pnl), 0) AS net_pnl, "
            "COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END), 0) AS winning_trades "
            "FROM trades" + where, params).fetchone()
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
        cutoff = _get_reset_cutoff_sync(conn)
        where = ' WHERE exit_time > %s' if cutoff else ''
        params = (cutoff,) if cutoff else ()
        row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS pnl FROM trades" + where, params).fetchone()
        return float(row["pnl"] or 0.0)
    return await _run_db(op)

def _add_unit_twins(item: dict, source_key: str, ratio_key: str, pct_key: str) -> None:
    """V-14: `*_pct` alanı aslında KESİR taşıyan rapor satırına birim ikizlerini ekler.

    Depolanan değer DEĞİŞTİRİLMEZ (paylaşılan matematik / replay riski); yalnız
    rapor çıktısında hem kesir (`*_ratio`) hem yüzde (`*_pct` = kesir×100) açık
    adlarla görünür kılınır. `source_key` eski (geriye dönük uyumlu) alandır ve
    korunur (bkz. modül başı birim sözleşmesi).
    """
    raw = item.get(source_key)
    try:
        ratio = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        ratio = 0.0
    item[ratio_key] = ratio
    item[pct_key] = round(ratio * 100.0, 4)


def _resolve_time_bounds(
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
    default_to_today: bool = True,
) -> tuple[float | None, float | None]:
    """Tarih parametrelerini (since, until, day) zaman damgalarına dönüştürür (UTC+3)."""
    if day == "all":
        return (None, None)
    if day:
        try:
            day_start = datetime.strptime(str(day), "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3)))
            return (day_start.timestamp(), (day_start + timedelta(days=1)).timestamp())
        except ValueError:
            pass
    if since is not None or until is not None:
        return (since, until)
    if default_to_today:
        today_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
        day_start = datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3)))
        return (day_start.timestamp(), None)
    return (None, None)


async def get_report_trade_breakdown(
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
):
    """Salt-okunur admin raporu: strateji/sembol bazlı kapanmış işlem özetleri (seçilen gün / reset_at sonrası).

    Birim sözleşmesi (V-14): `*_pct` alanları bu satırlarda KESİR taşır
    (`max_favorable_pct`/`max_adverse_pct` = analyzer'da ×100'süz). Eski alanlar
    geriye dönük uyum için korunur; yanlarına açık birimli ikizler eklenir:
    `avg_max_favorable_ratio` (kesir) + `avg_max_favorable_pct` (yüzde, ×100) ve
    aynı şekilde `avg_max_adverse_*`. `pnl_pct` (varsa) YÜZDE'dir.
    """
    eff_since, eff_until = _resolve_time_bounds(since=since, until=until, day=day, default_to_today=False)

    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        if eff_since is not None:
            cutoff = max(cutoff or 0.0, float(eff_since))
        where_clauses = []
        params = []
        if cutoff:
            where_clauses.append("exit_time >= ?")
            params.append(cutoff)
        if eff_until:
            where_clauses.append("exit_time < ?")
            params.append(eff_until)
        where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        strategies = conn.execute(
            "SELECT strategy, COUNT(*) AS trade_count, COALESCE(SUM(pnl), 0) AS net_pnl, "
            "COALESCE(SUM(commission), 0) AS commission, "
            "COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END), 0) AS winning, "
            "COALESCE(AVG(max_favorable_pct), 0) AS avg_max_favorable, "
            "COALESCE(AVG(max_adverse_pct), 0) AS avg_max_adverse "
            "FROM trades" + where + " GROUP BY strategy ORDER BY net_pnl DESC", params).fetchall()
        symbols = conn.execute(
            "SELECT symbol, COUNT(*) AS trade_count, COALESCE(SUM(pnl), 0) AS net_pnl, "
            "COALESCE(SUM(commission), 0) AS commission, "
            "COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END), 0) AS winning, "
            "COALESCE(AVG(max_favorable_pct), 0) AS avg_mfe_pct, "
            "COALESCE(AVG(max_adverse_pct), 0) AS avg_dd_pct, "
            "COALESCE(MIN(exit_time), 0) AS first_seen, "
            "COALESCE(MAX(exit_time), 0) AS last_seen "
            "FROM trades" + where + " GROUP BY symbol ORDER BY net_pnl DESC", params).fetchall()
        by_symbol = []
        for row in symbols:
            item = dict(row)
            total = int(item.get("trade_count") or 0)
            wins = int(item.get("winning") or 0)
            item["win_rate"] = round((wins / total) * 100, 2) if total else 0.0
            # V-14: `avg_mfe_pct`/`avg_dd_pct` eski alanlar KESİR taşır; açık
            # birimli ikizler ekle (eski alanlar korunur).
            _add_unit_twins(item, "avg_mfe_pct", "avg_max_favorable_ratio", "avg_max_favorable_pct")
            _add_unit_twins(item, "avg_dd_pct", "avg_max_adverse_ratio", "avg_max_adverse_pct")
            by_symbol.append(item)
        stats_row = conn.execute(
            "SELECT COUNT(*) AS trade_count, COALESCE(SUM(pnl), 0) AS net_pnl, "
            "COALESCE(SUM(commission), 0) AS commission, "
            "COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END), 0) AS winning, "
            "COALESCE(AVG(max_favorable_pct), 0) AS avg_max_favorable, "
            "COALESCE(AVG(max_adverse_pct), 0) AS avg_max_adverse "
            "FROM trades" + where, params).fetchone()
        overall = dict(stats_row)
        _add_unit_twins(overall, "avg_max_favorable", "avg_max_favorable_ratio", "avg_max_favorable_pct")
        _add_unit_twins(overall, "avg_max_adverse", "avg_max_adverse_ratio", "avg_max_adverse_pct")
        strategy_rows = []
        for row in strategies:
            item = dict(row)
            total = int(item.get("trade_count") or 0)
            wins = int(item.get("winning") or 0)
            item["win_rate"] = round((wins / total) * 100, 2) if total else 0.0
            _add_unit_twins(item, "avg_max_favorable", "avg_max_favorable_ratio", "avg_max_favorable_pct")
            _add_unit_twins(item, "avg_max_adverse", "avg_max_adverse_ratio", "avg_max_adverse_pct")
            strategy_rows.append(item)
        return {"strategies": strategy_rows, "symbols": by_symbol, "overall": overall}
    return await _run_db(op)


async def get_dashboard_summary() -> dict:
    """Ana sayfa dashboard özeti: bugünün sinyalleri, otonom işlem durumu, portföy.

    Tek fonksiyonda 3 veri grubu döner → frontend tek REST çağrısıyla dashboard'u
    doldurabilir.
    """
    def op(conn):
        day_start = _day_start_epoch()
        cutoff = _get_reset_cutoff_sync(conn)
        reset_where = " AND timestamp > %s" if cutoff else ""
        reset_params = (cutoff,) if cutoff else ()

        # Bugün üretilen sinyaller: BUY_SIGNAL (giriş) + CLOSE_* (çıkış) ayrımı
        sig_rows = conn.execute(
            "SELECT action FROM signals"
            " WHERE timestamp >= %s" + reset_where,
            (day_start,) + reset_params
        ).fetchall()
        buy_count = sum(1 for r in sig_rows if str(r[0] or "") == "BUY_SIGNAL")
        close_count = sum(1 for r in sig_rows if str(r[0] or "").startswith("CLOSE"))
        signals_today = {"total": len(sig_rows), "buy_signals": buy_count, "close_signals": close_count}

        # Bugün kapanan otonom işlemler
        ap_rows = conn.execute(
            "SELECT pnl FROM auto_paper_trades"
            " WHERE status='closed' AND exit_time >= %s",
            (day_start,)
        ).fetchall()
        ap_count = len(ap_rows)
        ap_pnl = sum(float(r[0] or 0) for r in ap_rows)
        auto_paper_today = {
            "trades": ap_count,
            "pnl": round(ap_pnl, 2),
            "winning": sum(1 for r in ap_rows if float(r[0] or 0) > 0),
            "losing": sum(1 for r in ap_rows if float(r[0] or 0) <= 0),
        }

        # Portföy: bakiye + açık pozisyon değerleri (ana + otonom paper).
        # NOT: dashboard giriş (entry) fiyatı bazlıdır; WS portföy anlık görüntüsü
        # mark-to-market'tir. İkisi de AYNI bileşimi (ana positions + açık
        # auto_paper_trades) kapsamalıdır; aksi halde panel ile canlı terminal
        # farklı "toplam değer" gösterir.
        cash_row = conn.execute(
            "SELECT amount FROM virtual_wallet WHERE asset='TRY'"
        ).fetchone()
        balance = float(cash_row[0]) if cash_row else 0.0
        pos_rows = conn.execute(
            "SELECT entry_price, quantity FROM positions"
        ).fetchall()
        open_count = len(pos_rows)
        pos_value = sum(float(r[0] or 0) * float(r[1] or 0) for r in pos_rows)
        ap_rows = conn.execute(
            "SELECT entry_price, quantity FROM auto_paper_trades WHERE status='open'"
        ).fetchall()
        ap_value = sum(float(r[0] or 0) * float(r[1] or 0) for r in ap_rows)
        total_value = balance + pos_value + ap_value
        portfolio = {
            "balance": round(balance, 2),
            "open_positions": open_count,
            "auto_paper_open": len(ap_rows),
            "positions_value": round(pos_value, 2),
            "auto_paper_value": round(ap_value, 2),
            "total_value": round(total_value, 2),
            # Panel entry-basis; canlı WS anlık görüntüsü mark-to-market.
            "basis": "entry",
        }

        return {
            "signals_today": signals_today,
            "auto_paper_today": auto_paper_today,
            "portfolio": portfolio,
        }
    return await _run_db(op)


def _day_start_epoch() -> float:
    """Bugünün başlangıcını (00:00:00 UTC) epoch float olarak döndür."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


async def get_report_autonomous_log(limit: int = 200, offset: int = 0, symbol: str = "", strategy: str = ""):
    """Geçmiş otonom işlem akışı: sinyaller + karar logları (reset_at sonrasi)."""
    limit = max(1, min(int(limit) or 200, 500))
    offset = max(0, int(offset) or 0)
    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        clauses, values = [], []
        if cutoff: clauses.append("timestamp > ?"); values.append(cutoff)
        if symbol: clauses.append("symbol=?"); values.append(str(symbol).upper())
        if strategy: clauses.append("strategy=?"); values.append(strategy)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        values.extend([limit, offset])
        rows = conn.execute(
            f"SELECT timestamp, symbol, action, price, reason, strategy, trade_id FROM signals{where}"
            " ORDER BY timestamp DESC LIMIT ? OFFSET ?", values).fetchall()
        return [dict(row) for row in rows]
    return await _run_db(op)


async def get_report_decision_summary(symbol: str = "", limit: int = 25):
    """Karar loglarından son durum özeti: strateji × karar dağılımı (salt okunur)."""
    limit = max(1, min(int(limit) or 25, 100))
    def op(conn):
        clauses, values = [], []
        if symbol: clauses.append("symbol=?"); values.append(str(symbol).upper())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"""SELECT strategy, decision, COUNT(*) AS count, MAX(timestamp) AS last_at
                FROM decision_logs{where}
                GROUP BY strategy, decision ORDER BY count DESC LIMIT ?""", values + [limit]).fetchall()
        return [dict(row) for row in rows]
    return await _run_db(op)


async def get_report_symbol_velocity_quality(
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
):
    """Hız avcısı sembol kalite istatistikleri (velocity_candidates, salt okunur)."""
    eff_since, eff_until = _resolve_time_bounds(since=since, until=until, day=day, default_to_today=True)
    def op(conn):
        where_clauses = ["status='evaluated'"]
        params = []
        if eff_since is not None:
            where_clauses.append("created_at >= ?")
            params.append(eff_since)
        if eff_until is not None:
            where_clauses.append("created_at < ?")
            params.append(eff_until)
        where = " WHERE " + " AND ".join(where_clauses)
        rows = conn.execute(
            f"""SELECT symbol,
                  COUNT(*) AS evaluated,
                  SUM(CASE WHEN touched_target THEN 1 ELSE 0 END) AS touched,
                  AVG(mfe_pct) AS average_mfe_pct
               FROM velocity_candidates {where}
               GROUP BY symbol ORDER BY evaluated DESC""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
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
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("paper_portfolio_open",))
        existing = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + " FOR UPDATE", (symbol,)).fetchone()
        if existing:
            raise RuntimeError("already_open")
        open_count = int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] or 0)
        if int(config.MAX_OPEN_POSITIONS) > 0 and open_count >= int(config.MAX_OPEN_POSITIONS):
            raise RuntimeError("max_open_positions_reached")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + " FOR UPDATE", ("TRY",)).fetchone()
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
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("paper_portfolio_open",))
        position_row = conn.execute("SELECT quantity FROM positions WHERE symbol=?" + " FOR UPDATE", (symbol,)).fetchone()
        if not position_row:
            raise RuntimeError("paper_position_not_found")
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=?" + " FOR UPDATE", ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else 0.0)
        exit_notional = float(trade.get("exit_price") or 0) * float(trade.get("quantity") or 0)
        next_cash = current_cash + exit_notional * (1 - config.COMMISSION_PCT)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", ("TRY", next_cash))
        position_qty = float(position_row[0] or 0)
        conn.execute("INSERT INTO virtual_wallet(asset,amount) VALUES(?,0.0) ON CONFLICT(asset) DO NOTHING", (asset,))
        conn.execute("UPDATE virtual_wallet SET amount=amount-? WHERE asset=?", (position_qty, asset))
        conn.execute("INSERT INTO trades (symbol,strategy,side,entry_price,exit_price,quantity,pnl,pnl_pct,entry_time,exit_time,commission,reason,entry_context,max_favorable_pct,max_adverse_pct,hold_seconds,trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (trade.get("symbol"), trade.get("strategy"), trade.get("side"), trade.get("entry_price"), trade.get("exit_price"), trade.get("quantity"), trade.get("pnl"), trade.get("pnl_pct"), trade.get("entry_time"), trade.get("exit_time"), trade.get("commission"), trade.get("reason"), _json_safe_dumps(trade.get("entry_context", {})), trade.get("max_favorable_pct"), trade.get("max_adverse_pct"), trade.get("hold_seconds"), trade.get("trade_id")))
        # V-06: `trade_id` NULL iken `WHERE trade_id=NULL` SQL'de hiçbir satır
        # döndürmez → eski guard her zaman başarısız oluyor ve pozisyon
        # KAPATILAMIYORDU (sermaye kilitleniyordu). NULL'da (sembol, giriş, çıkış)
        # üçlüsüyle doğrula; doluysa DB düzeyindeki UNIQUE kısıt zaten korur.
        trade_id = trade.get("trade_id")
        if trade_id:
            persisted = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE trade_id=?",
                (trade_id,)).fetchone()[0]
        else:
            persisted = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE symbol=? AND entry_time=? AND exit_time=?",
                (trade.get("symbol"), trade.get("entry_time"), trade.get("exit_time"))).fetchone()[0]
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
            (forecast_id,forecast_group_id,symbol,created_at,decided_at,horizon_minutes,entry_price,direction,confidence,
             invalidation_price,min_move_pct,regime,timeframe_context,scenario,counter_scenario,summary,
             model,prompt_version,snapshot_hash,snapshot,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(forecast_id) DO NOTHING"""
        values = []
        for row in rows:
            # TAH-01: fiyatın GÖZLEMLENDİĞİ an (`decided_at`) saklanır; yoksa
            # (kolon öncesi satırlar) kayıt anına (`created_at`) düşülür.
            decided_at = row.get("decided_at")
            decided_at = float(decided_at) if decided_at not in (None, "") else float(row["created_at"])
            values.append((row["forecast_id"], row["forecast_group_id"], str(row["symbol"]).upper(),
                float(row["created_at"]), decided_at, int(row["horizon_minutes"]), float(row["entry_price"]),
                row["direction"], float(row["confidence"]), row.get("invalidation_price"),
                float(row["min_move_pct"]), row.get("regime"),
                _json_safe_dumps(row.get("timeframe_context") or {}, ensure_ascii=False, default=str),
                row.get("scenario") or "", row.get("counter_scenario"), row.get("summary"), row.get("model"),
                row.get("prompt_version") or "forecast-v1", row["snapshot_hash"],
                _json_safe_dumps(row.get("snapshot") or {}, ensure_ascii=False, default=str), "pending"))
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)


async def get_pending_llm_forecasts(now=None, limit=200, grace_minutes=None):
    """Ufku VE gözlem penceresi dolmuş, henüz değerlendirilmemiş tahminler.

    TAH-02: satır, ufuk kapanır kapanmaz değil; `ufuk + effective_grace`
    dolduktan SONRA değerlendirmeye alınır. Böylece ölçüm süpürücünün ne zaman
    çalıştığına bağlı olmaktan çıkar (aynı tahmin her koşulda aynı sonucu verir).
    """
    now = float(now if now is not None else time.time())
    if grace_minutes is None:
        grace_minutes = getattr(config, "LLM_FORECAST_HIT_GRACE_MINUTES", 0)
    def op(conn):
        rows = conn.execute("""SELECT * FROM llm_forecasts
            WHERE status='pending' AND created_at + horizon_minutes * 60 <= ?
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        out = []
        for row in rows:
            item = _forecast_row(row)
            horizon = int(item.get("horizon_minutes") or 0)
            if float(item.get("created_at") or 0) + outcome_window_seconds(
                    horizon, grace_minutes) <= now:
                out.append(item)
        return out
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
        elif source == "upside_explore":
            clauses.append("prompt_version LIKE ?"); values.append("upside-explore-%")
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
        elif source == "upside_explore":
            # TAH-03: ε-keşif satırları başlık metriğinden AYRI raporlanır.
            source_clause = " AND prompt_version LIKE ?"
            params = ("upside-explore-%",)
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


async def get_pending_chat_predictions(now=None, limit=100, grace_minutes=None):
    """Sohbet tahminleri için bkz. `get_pending_llm_forecasts` (TAH-02 aynı kural)."""
    now = float(now if now is not None else time.time())
    if grace_minutes is None:
        grace_minutes = getattr(config, "LLM_FORECAST_HIT_GRACE_MINUTES", 0)
    def op(conn):
        rows = conn.execute("""SELECT * FROM chat_predictions
            WHERE status='pending' AND created_at + horizon_minutes * 60 <= ?
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        out = []
        for row in rows:
            item = _prediction_row(row)
            horizon = int(item.get("horizon_minutes") or 0)
            if float(item.get("created_at") or 0) + outcome_window_seconds(
                    horizon, grace_minutes) <= now:
                out.append(item)
        return out
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
            # outcome_details NOT NULL: extrasız satır '{}' alır; tek boş satır
            # tüm journal batch'ini düşürmesin.
            vals.append(_json_safe_dumps(extra) if extra else "{}")
            values.append(vals)
        conn.executemany(sql, values); conn.commit(); return len(values)
    return await _run_db(op)


async def get_pending_velocity_candidates(now=None, limit=100):
    now = float(now if now is not None else time.time())
    def op(conn):
        # Hedef penceresi en az 1 dakika; tarama anından 60 sn geçenler ölçüme hazır.
        rows = conn.execute("""SELECT * FROM velocity_candidates
            WHERE status='pending' AND created_at <= ? - 60
            ORDER BY created_at ASC LIMIT ?""", (now, max(1, min(int(limit), 500)))).fetchall()
        return [_velocity_row(row) for row in rows]
    return await _run_db(op)


async def mark_velocity_candidate_evaluated(candidate_id, *, mfe_pct, touched_target, details,
                                            force=False, exit_pct=None, net_pct=None):
    """D-06: `exit_pct` (ufuk sonu kapanis) ve `net_pct` (maliyet sonrasi) de yazar.

    Ikisi de opsiyonel: None gelirse kolon guncellenmez (geriye donuk uyumluluk).
    """
    def op(conn):
        where = "WHERE candidate_id=?" + ("" if force else " AND status='pending'")
        # outcome_details taramada m5_pattern/m5_pattern_ok taşıyor; üzerine
        # yazmak yerine birleştiriyoruz — aksi halde frontend "M5 Desen"
        # sütunu değerlendirme sonrası boş görünüyordu.
        existing = conn.execute("SELECT outcome_details FROM velocity_candidates WHERE candidate_id=?",
                                 (candidate_id,)).fetchone()
        prior = _json_value(existing[0], {}) if existing else {}
        merged = {**(prior or {}), **(details or {})}
        extra_sql, extra_vals = "", []
        if exit_pct is not None:
            extra_sql += ", exit_pct=?"
            extra_vals.append(float(exit_pct))
        if net_pct is not None:
            extra_sql += ", net_pct=?"
            extra_vals.append(float(net_pct))
        cur = conn.execute(f"""UPDATE velocity_candidates SET status='evaluated', evaluated_at=?, mfe_pct=?,
            touched_target=?, outcome_details=?{extra_sql} {where}""",
            (time.time(), float(mfe_pct), bool(touched_target),
             _json_safe_dumps(merged, ensure_ascii=False, default=str), *extra_vals, candidate_id))
        changed = cur.rowcount
        conn.commit(); return changed > 0
    return await _run_db(op)


async def upsert_evaluated_velocity_candidate(
    candidate_id: str, *, symbol: str, created_at: float, price: float,
    target_pct: float, mfe_pct: float, touched_target: bool,
    exit_pct: float | None = None, net_pct: float | None = None,
    details: dict | None = None, notification_id: int | None = None,
):
    """Backfill ve anlık ölçümler için değerlendirilmiş velocity adayı ekle/güncelle ve bildirime bağla."""
    now = time.time()
    def op(conn):
        details_json = _json_safe_dumps(details or {}, ensure_ascii=False, default=str)
        conn.execute("""
            INSERT INTO velocity_candidates (
                candidate_id, created_at, symbol, price, target_pct, atr_pct, volume_ratio,
                ret3_pct, velocity_score, passes, status, evaluated_at, mfe_pct,
                touched_target, exit_pct, net_pct, outcome_details
            ) VALUES (
                %s, %s, %s, %s, %s, 0.0, 0.0, 0.0, 0.0, FALSE, 'evaluated', %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (candidate_id) DO UPDATE SET
                status = 'evaluated',
                evaluated_at = EXCLUDED.evaluated_at,
                mfe_pct = EXCLUDED.mfe_pct,
                touched_target = EXCLUDED.touched_target,
                exit_pct = EXCLUDED.exit_pct,
                net_pct = EXCLUDED.net_pct,
                outcome_details = EXCLUDED.outcome_details
        """, (
            str(candidate_id), float(created_at), str(symbol).upper(), float(price), float(target_pct), now,
            float(mfe_pct), bool(touched_target),
            (float(exit_pct) if exit_pct is not None else None),
            (float(net_pct) if net_pct is not None else None),
            details_json
        ))
        if notification_id is not None:
            conn.execute(
                "UPDATE monitoring_notifications SET candidate_id=%s WHERE id=%s",
                (str(candidate_id), int(notification_id))
            )
        conn.commit()
        return True
    return await _run_db(op)


async def delete_velocity_candidates(candidate_ids):
    """Journal temizliği: seçili aday satırlarını kalıcı olarak siler."""
    ids = [str(i) for i in (candidate_ids or []) if str(i)]
    if not ids:
        return 0
    def op(conn):
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM velocity_candidates WHERE candidate_id IN ({placeholders})", ids)
        deleted = len(ids)
        conn.commit(); return int(deleted)
    return await _run_db(op)


async def get_velocity_candidates_missing_ml(limit: int = 200000):
    """ML kolonları boş velocity adayları — geriye dönük ML backfill için."""
    def op(conn):
        rows = conn.execute("""SELECT candidate_id, symbol, created_at FROM velocity_candidates
            WHERE ml_hit_probability IS NULL OR ml_target_pct IS NULL
            ORDER BY created_at ASC LIMIT ?""",
            (max(1, min(int(limit), 200000)),)).fetchall()
        return [dict(r) for r in rows]
    return await _run_db(op)


async def set_velocity_candidates_ml(updates):
    """Backfill: adayların ML kolonlarını doldurur; yalnız hâlâ boş olanlar güncellenir."""
    updates = [u for u in (updates or []) if u.get("candidate_id")]
    if not updates:
        return 0
    def op(conn):
        written = 0
        for u in updates:
            cur = conn.execute("""UPDATE velocity_candidates SET ml_target_pct=?, ml_hit_probability=?
                WHERE candidate_id=? AND ml_hit_probability IS NULL""",
                (float(u["ml_target_pct"]) if u.get("ml_target_pct") is not None else None,
                 float(u["ml_hit_probability"]) if u.get("ml_hit_probability") is not None else None,
                 u["candidate_id"]))
            written += int(getattr(cur, "rowcount", 0) or 0)
        conn.commit(); return written
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


async def list_velocity_candidates_since(since_epoch, until_epoch=None, limit: int = 20000):
    """Zaman penceresine göre velocity journal satırları (BİRLEŞİK RADAR replay).

    NEDEN AYRI FONKSİYON: `get_velocity_candidates` 500 satırla sınırlı ve yalnız
    EN YENİleri döndürür. Birleşik radar 24h replay'ı "radarın gördüğü" tam zaman
    çizelgesini kurmak zorunda — bildirim gönderilmeyen `watchlist` satırları DAHİL
    (yazım bildirimden bağımsızdır, velocity.py `_record_candidates`).

    Dönüş: `created_at` ARTAN sırada; `_velocity_row` ile aynı alanlar.
    """
    def op(conn):
        clauses = ["created_at >= ?"]
        values: list = [float(since_epoch)]
        if until_epoch is not None:
            clauses.append("created_at <= ?")
            values.append(float(until_epoch))
        values.append(max(1, min(int(limit), 200000)))
        rows = conn.execute(
            f"SELECT * FROM velocity_candidates WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at ASC LIMIT ?", values).fetchall()
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
    allowed = frozenset({"positions", "trades", "signals", "decision_logs", "virtual_wallet", "analysis_snapshots", "llm_tool_logs"})
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
        # V-19: hazır SQL `?` içerebilir; compat'ın yer tutucu dönüşümü atlanır.
        cur = conn.raw_execute(bounded)
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

async def save_push_subscription(subscription, username=None):
    """Web push aboneliğini kaydet/güncelle.

    `username` verilirse abonelik o kullanıcıya bağlanır (admin işlem
    bildiriminin seçili alıcılara hedeflenmesi bununla çalışır).

    NOT (2026-09-06): Postgres şeması TIMESTAMPTZ + JSONB kullanır; epoch float
    ve düz string yazımı psycopg'de hata veriyordu (push-subscription 500).
    Timestamp için now(), JSONB için ::jsonb cast kullanılır.

    MÜKERRER BİLDİRİM ÖNLEMİ (2026-09-17): AYNI tarayıcı profilinin p256dh
    anahtarı birden çok endpoint satırına düşerse (PWA yeniden kurulumu, SW
    rotasyonu, VAPID anahtarı değişimi sonrası eski endpoint 410 almadan
    kalırsa) her bildirim aynı cihaza N kez gider. Aynı `keys.p256dh` ile
    gelen yeni kayıt ESKİ satırın endpoint'ini DEĞİŞTİRİR — ikinci satır
    açılmaz. Farklı cihazların p256dh'si farklıdır → çoklu cihaz davranışı
    korunur.
    """
    endpoint = str(subscription.get("endpoint") or "")
    if not endpoint: raise ValueError("push subscription endpoint gerekli")
    p256dh = str(((subscription.get("keys") or {}).get("p256dh")) or "")
    # Oturumlu kayıtta abonelik kullanıcıya bağlanır (hedefli push için);
    # oturumsuz/None çağrılar mevcut username'i SİLMEMELİ (COALESCE).
    username = str(username or "").strip() or None
    def op(conn):
        replaced = 0
        if p256dh:
            rows = conn.execute("SELECT endpoint, subscription FROM push_subscriptions").fetchall()
            stale = []
            for row in rows:
                if str(row["endpoint"] or "") == endpoint:
                    continue
                keys = (_json_value(row["subscription"], {}) or {}).get("keys") or {}
                if str(keys.get("p256dh") or "") == p256dh:
                    stale.append(str(row["endpoint"] or ""))
            if stale:
                conn.executemany("DELETE FROM push_subscriptions WHERE endpoint = ?",
                                 [(ep,) for ep in stale])
                replaced = len(stale)
        conn.execute(
            "INSERT INTO push_subscriptions(endpoint,subscription,username,created_at,updated_at) "
            "VALUES(?::text,?::jsonb,?::text,now(),now()) "
            "ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription,"
            "username=COALESCE(excluded.username,push_subscriptions.username),updated_at=now()",
            (endpoint, _json_safe_dumps(subscription), username),
        ); conn.commit(); return {"ok": True, "replaced_duplicates": replaced}
    return await _run_db(op)

async def list_push_subscriptions(usernames=None):
    """Tüm push abonelikleri; `usernames` verilirse yalnız o kullanıcılarınkiler.

    `username` NULL olan (kullanıcı bağlaması öncesi) kayıtlar filtrede düşer —
    uygulama açılışındaki reconcile bunları oturum sahibiyle yeniden kaydeder.
    """
    wanted = sorted({str(u or "").strip() for u in (usernames or []) if str(u or "").strip()})
    def op(conn):
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            rows = conn.execute(
                f"SELECT subscription FROM push_subscriptions WHERE username IN ({placeholders})",
                tuple(wanted)).fetchall()
        else:
            rows = conn.execute("SELECT subscription FROM push_subscriptions").fetchall()
        return [_json_value(row["subscription"], {}) for row in rows]
    return await _run_db(op)


async def count_push_subscriptions() -> int:
    """Push abone sayısı — push SAĞLIĞINI görünür kılar (2026-09-16 denetimi).

    Ölçüm: 0 ise tarayıcı push'u hiç çalışmıyor demektir; backend `VAPID_PRIVATE_KEY`
    yapılandırılmış olsa bile "push çalışıyor" yanılsaması oluşur. Sayaç panele
    taşınır ki sessiz arıza görünür olsun.
    """
    def op(conn):
        row = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()
        return int(row[0]) if row else 0
    try:
        return await _run_db(op)
    except Exception:
        # Tablo yoksa/erişilemezse sağlık bloğu state yanıtını BOZMASIN.
        return 0

async def remove_push_subscriptions(endpoints: list[str]):
    """Ölü (410/404) push aboneliklerini endpoint URL'sine göre temizler."""
    if not endpoints:
        return 0
    def op(conn):
        cur = conn.executemany("DELETE FROM push_subscriptions WHERE endpoint = ?",
                                [(ep,) for ep in endpoints])
        conn.commit()
        return cur.rowcount
    return await _run_db(op)


async def save_monitoring_notifications(entries):
    """Monitoring bildirim geçmişini kalıcı kaydet (server-side scan loop'tan).

    entries: sözlük listesi — symbol, message, title, score, target_pct,
    price, expected_price, horizon_minutes, mode, detected_at, sent_via_push,
    ml_target_pct, ml_hit_probability (opsiyonel; 2026-09-04 eklendi).
    norm_cap (opsiyonel; R2-03) satırın normalize edildiği cap — varsa float,
    yoksa NULL. candidate_id (opsiyonel; R3-05) kaynak aday kimliği — varsa
    saklanır (ölçümde birebir eşleşme için).
    norm_version (opsiyonel; A3) satırın yazıldığı panel ölçek sürümü (1=lineer,
    2=log). Okuma tarafı (`monitoring._stored_panel_score`) sürüme göre doğru
    haritayı uygular; etiket yoksa kayıt A3 öncesi (lineer) sayılır.
    Girdilerde 'id' yoksa kaydedilen satırın id'si entry'e eklenir (ertelenen
    push'un sonradan etiketlenmesi için; 2026-09-05).
    """
    def _norm_cap_value(e):
        raw = e.get("norm_cap")
        if raw not in (None, ""):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        return None

    def _norm_version_value(e):
        raw = e.get("norm_version")
        if raw in (None, ""):
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    def _candidate_id_value(e):
        cid = e.get("candidate_id")
        return str(cid) if cid not in (None, "") else None

    def _sources_value(e):
        # BİRLEŞİK SİNYAL (2026-09-17): tespit kaynakları JSON dizi olarak saklanır.
        # Eski çağıranlar (rising vs.) alanı göndermez → NULL kalır, okuma tarafı
        # ["velocity"] varsayar (geriye dönük uyumluluk).
        sources = e.get("sources") or e.get("unified_sources")
        if not sources:
            return None
        if isinstance(sources, str):
            sources = [s for s in sources.split(",") if s]
        try:
            return json.dumps([str(s) for s in sources])
        except (TypeError, ValueError):
            return None
    if not entries:
        return 0
    now = time.time()
    def op(conn):
        saved = 0
        for e in entries:
            row = conn.execute(
                "INSERT INTO monitoring_notifications"
                "(symbol,message,title,score,target_pct,price,expected_price,horizon_minutes,mode,detected_at,sent_via_push,created_at,"
                "ml_target_pct,ml_hit_probability,candidate_id,norm_cap,norm_version,sources)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (
                    str(e.get("symbol") or "?"),
                    str(e.get("message") or ""),
                    str(e.get("title") or "") or None,
                    e.get("score"), e.get("target_pct"), e.get("price"), e.get("expected_price"),
                    e.get("horizon_minutes"), e.get("mode"),
                    float(e.get("detected_at") or now),
                    # M4 (R2-19): varsayılan False — alanı atlayan çağıran yanlış
                    # "gönderildi" etiketi yazmamalı; fiilî teslim mark_... ile yazılır.
                    bool(e.get("sent_via_push", False)),
                    now,
                    e.get("ml_target_pct"), e.get("ml_hit_probability"),
                    _candidate_id_value(e), _norm_cap_value(e), _norm_version_value(e),
                    _sources_value(e),
                ),
            ).fetchone()
            if row is not None and e.get("id") is None:
                e["id"] = row[0]
            saved += 1
        conn.commit()
        return saved
    return await _run_db(op)


async def mark_monitoring_push_sent(notification_id):
    """Ertelenen push gerçekten gönderildiğinde DB etiketini True'ya çevir.

    Sessiz saatte push kuyruğuna alınan bildirimler sent_via_push=False ile
    kaydedilir; saat bitip push ulaşınca bu fonksiyon etiketi düzeltir
    (2026-09-05: öncesinde 'ertelenen' bildirim DB'de yanlışlıkla
    sent_via_push=True görünüyordu).
    """
    def op(conn):
        conn.execute(
            "UPDATE monitoring_notifications SET sent_via_push=TRUE WHERE id=?",
            (notification_id,)
        )
        conn.commit()
        return True
    return await _run_db(op)



async def get_monitoring_velocity_matches(limit: int | None = 1000, day: str | None = None):
    """Bildirimleri ayni andaki velocity adayiyla karsilastir (salt okunur).

monitoring_notifications VE velocity_candidates ayni tarama turunda
    uretilir: bildirimin tespit ani (detected_at) ile velocity adayinin
    kayit ani (created_at) <= 60 saniye fark VE hedef % eslesmesi aranir.
    M4 (R3-05/R2-05/R4-07): bildirim `candidate_id` ile yazilmisa once KALICI
    `candidate_id` birebir eslesmesi denenir; bulunamazsa eski ~60 sn pencere
    + hedef eslesmesine (legacy) dusulur. Boylece guncelleme `target_pct`'i
    degistirse bile kaynak aday yine olcumu mumkun kalir. Sonuc bicimi aynidir.
    Velocity adayi degerlendirildiyse gercek M1 kapanis olcumu (mfe_pct,
    touched_target) kullanilir; degilse bekliyor sayilir.

    limit: ust sinir (varsayilan 1000). M4 (R4-04): ``limit=None`` = cap YOK,
    tumu getirilir (overall hesaplari icin). day: 'YYYY-MM-DD' gun filtresi.
    """
    from datetime import datetime, timezone, timedelta
    def op(conn):
        base_sql = (
            "SELECT id, symbol, mode, score, target_pct, price, expected_price,"
            " horizon_minutes, detected_at, sent_via_push, message, title,"
            " candidate_id, norm_cap, norm_version, sources"
            " FROM monitoring_notifications"
        )
        params: list = []
        if day:
            try:
                day_start = datetime.strptime(str(day), '%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=3)))
            except ValueError:
                raise ValueError(f"Geçersiz tarih: {day!r} (YYYY-MM-DD bekleniyor)") from None
            day_end = day_start + timedelta(days=1)
            base_sql += " WHERE detected_at >= %s AND detected_at < %s"
            params.extend([day_start.timestamp(), day_end.timestamp()])
        base_sql += " ORDER BY detected_at DESC"
        if limit is not None:
            base_sql += " LIMIT %s"
            params.append(max(1, min(int(limit), 1000)))
        notif_rows = conn.execute(base_sql, params).fetchall()
        # V-11: eskiden her bildirim için ayrı bir `velocity_candidates` sorgusu
        # atılıyordu (1 + N, N<=1000). Tek sorgu ile aynı semantik: bildirim
        # pencerelerinin BİRLEŞİMİ çekilir, ±60 sn kuralı ve "en yakın 4"
        # sıralaması Python'da uygulanır.
        # M4 / V-11: Bildirimleri velocity adaylarıyla eşleştir.
        # 1. Öncelik: Kalıcı `candidate_id` birebir eşleşmesi.
        # 2. Öncelik: ±120 sn zaman penceresi ve hedef % eşleşmesi.
        # 3. Öncelik: Hedef güncellemesi olmuşsa o penceredeki en yakın sembol adayı.
        explicit_cids = list({str(n["candidate_id"]).strip() for n in notif_rows if n.get("candidate_id")})
        candidates_by_id: dict[str, dict] = {}
        if explicit_cids:
            # Postgres IN parametreleri
            cid_placeholders = ",".join(["%s"] * len(explicit_cids))
            cid_rows = conn.execute(
                "SELECT candidate_id, symbol, target_pct, passes, status, mfe_pct,"
                " touched_target, created_at, ml_target_pct, ml_hit_probability,"
                " exit_pct, net_pct, velocity_score, outcome_details"
                f" FROM velocity_candidates WHERE candidate_id IN ({cid_placeholders})",
                explicit_cids).fetchall()
            for candidate in cid_rows:
                row_dict = dict(candidate)
                cid = str(row_dict.get("candidate_id") or "").strip()
                if cid:
                    candidates_by_id[cid] = row_dict

        windows: dict[str, list[float]] = {}
        for notif in notif_rows:
            item = dict(notif)
            sym = str(item.get('symbol') or '').upper()
            stamp = float(item.get('detected_at') or 0)
            if sym and stamp > 0:
                windows.setdefault(sym, []).append(stamp)
        candidate_index: dict[str, list[dict]] = {}
        if windows:
            symbols = list(windows)
            low = min(min(values) for values in windows.values()) - 60
            high = max(max(values) for values in windows.values()) + 60
            placeholders = ",".join(["%s"] * len(symbols))
            candidate_rows = conn.execute(
                "SELECT candidate_id, symbol, target_pct, passes, status, mfe_pct,"
                " touched_target, created_at, ml_target_pct, ml_hit_probability,"
                " exit_pct, net_pct, velocity_score, outcome_details"
                f" FROM velocity_candidates WHERE symbol IN ({placeholders})"
                " AND created_at >= %s AND created_at <= %s",
                symbols + [low, high]).fetchall()
            for candidate in candidate_rows:
                item = dict(candidate)
                candidate_index.setdefault(str(item.get('symbol') or '').upper(), []).append(item)
                cid = str(item.get("candidate_id") or "").strip()
                if cid and cid not in candidates_by_id:
                    candidates_by_id[cid] = item

        matches = []
        for n in notif_rows:
            item = dict(n)
            symbol = str(item.get('symbol') or '').upper()
            detected = float(item.get('detected_at') or 0)
            target = float(item.get('target_pct') or 0)
            cid = str(item.get('candidate_id') or '').strip()
            best = None
            # 1. Adım: candidate_id ile doğrudan eşleşme
            if cid and cid in candidates_by_id:
                best = candidates_by_id[cid]

            # 2. Adım: Zamana göre en yakın adaylar (±60s ve hedef eşleşmesi)
            if best is None and symbol and detected > 0:
                cands = [cand for cand in candidate_index.get(symbol, [])
                         if abs(float(cand.get('created_at') or 0) - detected) <= 60]
                cands.sort(key=lambda cand: abs(float(cand.get('created_at') or 0) - detected))
                for row in cands[:4]:
                    if target > 0 and abs(float(row.get('target_pct') or 0) - target) < 0.05:
                        best = row
                        break

            if best:
                item['candidate_id'] = best.get('candidate_id')
                item['candidate_status'] = best.get('status')
                item['mfe_pct'] = best.get('mfe_pct')
                cand_mfe = float(best['mfe_pct']) if best.get('mfe_pct') is not None else None
                # Dokunuş: adayın MFE'si bildirimin beklenen hedefine ulaştı mı?
                if cand_mfe is not None and target > 0:
                    item['touched_target'] = cand_mfe >= target
                else:
                    item['touched_target'] = bool(best.get('touched_target')) if best.get('touched_target') is not None else None
                item['raw_score'] = (float(best['velocity_score'])
                                     if best.get('velocity_score') is not None else None)
                item['exit_pct'] = float(best['exit_pct']) if best.get('exit_pct') is not None else None
                item['net_pct'] = float(best['net_pct']) if best.get('net_pct') is not None else None
                item['candidate_target_pct'] = best.get('target_pct')
                item['candidate_passes'] = bool(best.get('passes')) if best.get('passes') is not None else None
                item['target_match'] = True
                item['ml_hit_probability'] = float(best['ml_hit_probability']) if best.get('ml_hit_probability') is not None else None
                item['outcome_details'] = _json_value(best.get('outcome_details'), {})
            else:
                item['candidate_id'] = None
                item['candidate_status'] = None
                item['mfe_pct'] = None
                item['exit_pct'] = None
                item['net_pct'] = None
                item['raw_score'] = None
                item['touched_target'] = None
                item['outcome_details'] = {}
                item['candidate_target_pct'] = None
                item['candidate_passes'] = None
                item['target_match'] = False
                item['ml_hit_probability'] = None
            matches.append(item)
        return matches
    return await _run_db(op)


async def get_pending_monitoring_notification(symbol: str) -> dict | None:
    """Sembol icin sonuclanmamis (BEKLIYOR) bildirimlerini getir.
    
    En yeni bildirim ve toplam BEKLIYOR sayisi doner.
    Eski bildirimler icin ID'ler de doner (silinmek uzere).
    """
    def op(conn):
        rows = conn.execute(
            "SELECT id, symbol, score, target_pct, price, expected_price, "
            "horizon_minutes, detected_at, mode "
            "FROM monitoring_notifications "
            "WHERE symbol=%s "
            "ORDER BY detected_at DESC",
            (str(symbol).upper(),)
        ).fetchall()
        if not rows:
            return None
        latest = dict(rows[0])
        old_ids = [row[0] for row in rows[1:]]  # En yeni haric tum ID'ler
        latest["old_ids"] = old_ids
        latest["total_pending"] = len(rows)
        return latest
    return await _run_db(op)


async def get_monitoring_notification_by_id(notification_id: int) -> dict | None:
    """Bildirim ID'sine göre monitoring bildirim kaydını getir."""
    def op(conn):
        row = conn.execute(
            "SELECT id, symbol, score, target_pct, price, expected_price, "
            "horizon_minutes, detected_at, mode "
            "FROM monitoring_notifications "
            "WHERE id=%s",
            (int(notification_id),)
        ).fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def get_pending_monitoring_notifications(symbols: list[str]) -> dict[str, dict]:
    """Birden fazla sembol icin sonuclanmamis (BEKLIYOR) bildirimlerini tek
    sorguyla getir (N+1 onlemi; 2026-09-05). Her sembol icin en yeni kaydi
    sembol -> kayit seklinde dondurur.
    """
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    if not syms:
        return {}
    def op(conn):
        placeholders = ",".join(["%s"] * len(syms))
        rows = conn.execute(
            "SELECT id, symbol, score, target_pct, price, expected_price, "
            "horizon_minutes, detected_at, mode "
            "FROM monitoring_notifications "
            f"WHERE symbol IN ({placeholders}) "
            "ORDER BY detected_at DESC",
            syms
        ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            sym = str(row[1] or "").upper()
            if sym not in result:
                latest = dict(row)
                latest["old_ids"] = []
                latest["total_pending"] = 0
                result[sym] = latest
            else:
                result[sym]["old_ids"].append(row[0])
                result[sym]["total_pending"] += 1
        return result
    return await _run_db(op)



async def update_monitoring_notification(
    notif_id: int, score: float, target_pct: float, price: float,
    expected_price: float, horizon_minutes: int, mode: str | None,
    ml_target_pct: float | None = None, ml_hit_probability: float | None = None,
    candidate_id: str | None = None,
) -> bool:
    # detected_at bilerek guncellenmez: orijinal tespit ani korunmazsa
    # velocity adayiyla eslesme bozulur ve M1 olcumu yapilamaz.
    # ML alanlari ve candidate_id de guncellenir.
    def op(conn):
        if candidate_id:
            conn.execute(
                "UPDATE monitoring_notifications SET "
                "score=%s, target_pct=%s, price=%s, expected_price=%s, "
                "horizon_minutes=%s, mode=%s, ml_target_pct=%s, ml_hit_probability=%s, "
                "candidate_id=COALESCE(candidate_id, %s) "
                "WHERE id=%s",
                (score, target_pct, price, expected_price, horizon_minutes, mode,
                 ml_target_pct, ml_hit_probability, str(candidate_id), notif_id)
            )
        else:
            conn.execute(
                "UPDATE monitoring_notifications SET "
                "score=%s, target_pct=%s, price=%s, expected_price=%s, "
                "horizon_minutes=%s, mode=%s, ml_target_pct=%s, ml_hit_probability=%s "
                "WHERE id=%s",
                (score, target_pct, price, expected_price, horizon_minutes, mode,
                 ml_target_pct, ml_hit_probability, notif_id)
            )
        conn.commit()
        return True
    return await _run_db(op)

async def list_monitoring_notifications(limit=50):
    """En son monitoring bildirimlerini döndür (yeni -> eski)."""
    def op(conn):
        rows = conn.execute(
            "SELECT id,symbol,message,title,score,target_pct,price,expected_price,"
            "horizon_minutes,mode,detected_at,sent_via_push FROM monitoring_notifications"
            " ORDER BY detected_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)
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
        # NOT: `data ? 'indicators'` kullanma — _PostgresCompat '?'->'%s'
        # çevirir, jsonb varlık operatörünü bozar. Fonksiyon formu güvenli.
        cur = conn.execute(
            "UPDATE chart_settings SET data = data - 'indicators' "
            "WHERE jsonb_exists(data, 'indicators')")
        conn.commit()
        return cur.rowcount

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

async def save_research_run(result):
    def op(conn):
        sql = """INSERT INTO research_runs
            (created_at,run_type,scope,symbols,timeframes,parameters,result,status,paper_only)
            VALUES (?,?,?,?,?,?,?,?,?)"""
        params = (time.time(), result.get("run_type", "research"), result.get("scope", "active"),
                  _json_safe_dumps(result.get("symbols", [])), _json_safe_dumps(result.get("timeframes", [])),
                  _json_safe_dumps(result.get("parameters", {}), default=str), _json_safe_dumps(result.get("result", {}), default=str),
                  result.get("status", "completed"), 1)
        row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
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
        row = conn.execute(sql + " RETURNING id", params).fetchone(); conn.commit(); return row[0]
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

async def prune_retention(days: int = 30, microstructure_days: int = 7,
                         memory_days: int = 180, history_days: int = 21,
                         embedding_jobs_days: int = 14, decision_logs_days: int = 90):
    """Delete high-volume observability rows older than ``days`` days.

    microstructure_snapshots grows one row per fresh symbol per second and
    embedding_jobs keeps full JSONB documents; without a sweep both grow
    unbounded. Paper trades/signals/decision logs are never pruned here.
    microstructure_snapshots uses its own, tighter window (``microstructure_days``)
    and is deleted in batches so a large backlogs does not hold one long
    transaction. Returns per-table deleted row counts.

    2026-09-16 (disk denetimi) — EKLENENLER ve NEDENİ:
      * `historical_candles` + `historical_feature_snapshots` HİÇ budanmıyordu.
        ML eğitimi yalnız `ML_TRAIN_LOOKBACK_DAYS` (10) geriye bakar; 21 günlük
        pencere replay/parite payı bırakır. Bu ikisi sınırsız büyüyen asıl
        tablolardı. NOT: `open_time`/`captured_at` **MİLİSANİYE** (BIGINT) —
        cutoff ms'e çevrilir, aksi halde karşılaştırma anlamsız olur.
      * `macd_monitor_alerts`, `memory_retrieval_logs`, `chat_messages`,
        `alert_events`, `rising_alerts` de listede yoktu.
      * `agent_trace_events` EKLENMEDİ: `agent_traces(trace_id)` üzerinden
        `ON DELETE CASCADE` ile zaten temizleniyor.
      * Sonda `VACUUM (ANALYZE)`: DELETE alanı işletim sistemine GERİ VERMEZ;
        ölçümde 12 GB'lık `microstructure_snapshots` yalnız 2.4k satır taşıyordu
        (budanmış ama hiç vacuum edilmemiş). Bu adım ölü tuple birikimini
        sınırlar — TEK SEFERLİK geri kazanım için `VACUUM FULL` gerekir (elle).
      * `decision_logs` (2026-09-16, ikinci tur): budama listesinde DEĞİLDİ ve
        sınırsız büyüyordu (~8.5k satır/gün, `metadata` JSONB ~2.4 KB/satır =
        ölçümde 1.46 GB TOAST). Kendi, daha uzun penceresiyle (`decision_logs_days`,
        varsayılan 90) düşürülür.
        ÖNEMLİ — OTONOM SATIRLAR KORUNUR: `strategy='AUTO_PAPER'` satırları
        SİLİNMEZ. Otonom paper karar zinciri ve kalibrasyon onları okur; ayrıca
        `AUTO_PAPER` satırları insan kararı değil makine kanıtıdır ve yeniden
        üretilemez. Silinen tek şey ham gözlem telemetrisidir.
        NOT: `decision_logs.timestamp` **SANİYE (DOUBLE PRECISION)** — mum
        tablolarındaki gibi ms DEĞİL; birim karıştırılırsa budama sessiz no-op olur.
    """
    cutoff = time.time() - max(1, int(days)) * 86400
    micro_cutoff = time.time() - max(1, int(microstructure_days)) * 86400
    # MEM-01: sohbet belleği kendi, daha uzun penceresiyle düşürülür.
    memory_cutoff = time.time() - max(1, int(memory_days)) * 86400
    history_cutoff = time.time() - max(1, int(history_days)) * 86400
    embedding_cutoff = time.time() - max(1, int(embedding_jobs_days)) * 86400
    decision_logs_cutoff = time.time() - max(1, int(decision_logs_days)) * 86400
    # Mum tabloları BIGINT MİLİSANİYE tutar (epoch sn değil).
    history_cutoff_ms = int(history_cutoff * 1000)

    def op(conn):
        deleted = {}
        # Batched sweep: single DELETE on a 100M-row backlog holds a long
        # transaction and bloats WAL; 500k-row chunks commit incrementally.
        for table, column, window, is_ms in (
            ("microstructure_snapshots", "captured_at", micro_cutoff, False),
            # Mum geçmişi: satır sayısı 10^6-10^7 olabilir → o da partili gider.
            ("historical_candles", "open_time", history_cutoff_ms, True),
            ("historical_feature_snapshots", "captured_at", history_cutoff_ms, True),
        ):
            deleted[table] = 0
            while True:
                try:
                    cursor = conn.execute(
                        f"""DELETE FROM {table} WHERE ctid IN (
                            SELECT ctid FROM {table} WHERE {column} < %s LIMIT 500000)""",
                        (window,))
                    conn.commit()
                    batch = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                except Exception:
                    conn.rollback()
                    break
                deleted[table] += batch
                if batch < 500000:
                    break
        for table, column in (
            ("llm_tool_logs", "timestamp"),
            ("analysis_snapshots", "captured_at"),
            ("monitoring_notifications", "detected_at"),
            # 2026-09-16 eklendi (budama listesinde değillerdi):
            ("macd_monitor_alerts", "created_at"),
            ("rising_alerts", "created_at"),
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
        # embedding_jobs.created_at TIMESTAMPTZ'dir (epoch double değil); yıkama
        # sorgusu epoch cutoff ile karşılaştırmak için EXTRACT(EPOCH) kullanır.
        try:
            cursor = conn.execute("DELETE FROM embedding_jobs WHERE EXTRACT(EPOCH FROM created_at) < ?",
                                  (embedding_cutoff,))
            conn.commit()
            deleted["embedding_jobs"] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        except Exception:
            conn.rollback()
            deleted["embedding_jobs"] = 0
        # strategy_scan_logs şemada bulunmuyor; velocity_candidates'ı doğru
        # tablo adıyla ele al. Yoksa sessizce geç.
        try:
            cursor = conn.execute("DELETE FROM velocity_candidates WHERE created_at < ?", (cutoff,))
            conn.commit()
            deleted["velocity_candidates"] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        except Exception:
            conn.rollback()
            deleted["velocity_candidates"] = 0
        # DECISION-LOGS-01 (2026-09-16): karar günlüğü budama listesinde değildi ve
        # sınırsız büyüyordu (~8.5k satır/gün; `metadata` JSONB yüzünden ölçümde
        # 1.46 GB TOAST). `timestamp` SANİYE'dir (DOUBLE PRECISION) — mum
        # tablolarındaki gibi ms'e ÇEVRİLMEZ, aksi hâlde budama sessiz no-op olur.
        # `AUTO_PAPER` HARİÇ: otonom paper karar zinciri ve kalibrasyon o satırları
        # okur ve yeniden üretilemez (makine kanıtı). COALESCE, NULL `strategy`yi
        # de kapsar ve PG/SQLite ikisinde de aynı davranır.
        try:
            cursor = conn.execute(
                "DELETE FROM decision_logs WHERE timestamp < ? "
                "AND COALESCE(strategy, '') <> 'AUTO_PAPER'",
                (decision_logs_cutoff,))
            conn.commit()
            deleted["decision_logs"] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        except Exception:
            conn.rollback()
            deleted["decision_logs"] = 0
        # MEM-01: `_persist_chat_memory` HER sohbet isteğinde bir
        # `memory_documents` satırı (ve ON DELETE CASCADE ile
        # `memory_embeddings`) yazıyordu; bu tablolar hiç temizlenmiyordu ->
        # sohbet hacmiyle doğrusal, sınırsız büyüme (her satırda halfvec vektör).
        # Öğrenme artefaktları (`agent_experiences`, `trading_instincts`)
        # BİLİNÇLİ olarak temizlenmez — yalnızca ham telemetri ve yaşlı belgeler.
        for table, column, window in (
            ("agent_traces", "started_at", cutoff),
            ("memory_documents", "created_at", memory_cutoff),
            ("memory_retrieval_logs", "created_at", cutoff),
            ("chat_messages", "created_at", memory_cutoff),
            ("alert_events", "triggered_at", cutoff),
        ):
            try:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE EXTRACT(EPOCH FROM {column}) < ?", (window,))
                conn.commit()
                deleted[table] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            except Exception:
                conn.rollback()
                deleted[table] = 0
        # BLOATED-01: ölü tuple'ları geri kazan (FULL DEĞİL — kilit tutmaz).
        # `VACUUM` transaction bloğunda çalışamaz → autocommit'e geçici geçilir.
        try:
            raw = getattr(conn, "conn", None)
            previous = None
            if raw is not None:
                previous = raw.autocommit
                raw.autocommit = True
            try:
                conn.execute("VACUUM (ANALYZE) microstructure_snapshots, historical_candles,"
                             " historical_feature_snapshots, memory_documents, memory_embeddings,"
                             " velocity_candidates, embedding_jobs, agent_traces,"
                             " monitoring_notifications, macd_monitor_alerts, rising_alerts,"
                             " decision_logs")
            finally:
                if raw is not None and previous is not None:
                    raw.autocommit = previous
            deleted["_vacuum"] = 1
        except Exception as exc:
            logging.getLogger("scalper.database").debug("retention VACUUM atlandı: %s", exc)
            deleted["_vacuum"] = 0
        return deleted

    return await _run_db(op)


async def close_db():
    """Havuzu kapat (shutdown). Havuz None ise sorun değil."""
    global _PG_POOL
    pool = _PG_POOL
    _PG_POOL = None
    if pool is not None:
        try:
            await asyncio.get_running_loop().run_in_executor(None, pool.close)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Users (username+password auth, 2026-09-03)
# ---------------------------------------------------------------------------
def _user_row(row) -> dict | None:
    if row is None:
        return None
    return {"id": int(row["id"]), "username": row["username"], "password_hash": row["password_hash"],
            "role": row["role"], "is_active": bool(row["is_active"]),
            "session_version": int(row.get("session_version") or 0),
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
            "INSERT INTO users(username,password_hash,role,is_active,session_version,created_at,updated_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (str(username).strip().lower(), password_hash, str(role).lower(), bool(is_active), 0, now, now))
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
        sets.append("session_version=session_version+1")
        sets.append("updated_at=%s"); values.append(time.time())
        values.append(int(user_id))
        row = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(values)).fetchone()
        conn.commit()
        return _user_row(row)
    return await _run_db(op)


async def bump_user_session_version(user_id: int) -> dict | None:
    """Invalidate all existing session tokens for one user."""
    def op(conn):
        row = conn.execute(
            "UPDATE users SET session_version=session_version+1, updated_at=%s "
            "WHERE id=%s RETURNING *",
            (time.time(), int(user_id)),
        ).fetchone()
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
# Kullanıcı bazlı Binance API anahtarları (2026-09-19, migration 005)
# Her kullanıcı kendi Binance TR key/secret'ını Fernet şifreli saklar;
# admin için satır yoksa main.py eski global llm_settings anahtarına düşer.
# ---------------------------------------------------------------------------
def _user_binance_keys_row(row) -> dict | None:
    if row is None:
        return None
    return {"user_id": int(row["user_id"]),
            "api_key_encrypted": row["api_key_encrypted"],
            "api_secret_encrypted": row["api_secret_encrypted"],
            "real_sell_enabled": bool(row["real_sell_enabled"]),
            "created_at": float(row["created_at"] or 0),
            "updated_at": float(row["updated_at"] or 0)}


async def get_user_binance_keys(user_id: int) -> dict | None:
    def op(conn):
        row = conn.execute("SELECT * FROM user_binance_keys WHERE user_id=%s", (int(user_id),)).fetchone()
        return _user_binance_keys_row(row)
    return await _run_db(op)


async def get_user_binance_real_sell(user_id: int) -> bool:
    def op(conn):
        row = conn.execute("SELECT real_sell_enabled FROM user_binance_keys WHERE user_id=%s", (int(user_id),)).fetchone()
        return bool(row and row["real_sell_enabled"])
    return await _run_db(op)


async def save_user_binance_keys(user_id: int, enc_key: str, enc_secret: str,
                                 real_sell_enabled: bool | None = None) -> dict:
    now = time.time()

    def op(conn):
        if real_sell_enabled is None:
            # Yalnız anahtarları güncelle; mevcut satır yoksa varsayılanla oluştur.
            conn.execute(
                "INSERT INTO user_binance_keys(user_id,api_key_encrypted,api_secret_encrypted,real_sell_enabled,created_at,updated_at) "
                "VALUES(%s,%s,%s,FALSE,%s,%s) "
                "ON CONFLICT(user_id) DO UPDATE SET api_key_encrypted=excluded.api_key_encrypted, "
                "api_secret_encrypted=excluded.api_secret_encrypted, updated_at=excluded.updated_at",
                (int(user_id), enc_key, enc_secret, now, now))
        else:
            conn.execute(
                "INSERT INTO user_binance_keys(user_id,api_key_encrypted,api_secret_encrypted,real_sell_enabled,created_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(user_id) DO UPDATE SET api_key_encrypted=excluded.api_key_encrypted, "
                "api_secret_encrypted=excluded.api_secret_encrypted, real_sell_enabled=excluded.real_sell_enabled, "
                "updated_at=excluded.updated_at",
                (int(user_id), enc_key, enc_secret, bool(real_sell_enabled), now, now))
        conn.commit()
        row = conn.execute("SELECT * FROM user_binance_keys WHERE user_id=%s", (int(user_id),)).fetchone()
        return _user_binance_keys_row(row)

    return await _run_db(op)


async def set_user_binance_real_sell(user_id: int, enabled: bool) -> bool:
    """Yalnız real_sell bayrağını güncelle; anahtar satırı yoksa False döner."""
    def op(conn):
        cur = conn.execute(
            "UPDATE user_binance_keys SET real_sell_enabled=%s, updated_at=%s WHERE user_id=%s",
            (bool(enabled), time.time(), int(user_id)))
        conn.commit()
        return cur.rowcount > 0
    return await _run_db(op)


async def delete_user_binance_keys(user_id: int) -> bool:
    def op(conn):
        cur = conn.execute("DELETE FROM user_binance_keys WHERE user_id=%s", (int(user_id),))
        conn.commit()
        return cur.rowcount > 0
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
        # V-16: kullanıcı girdisi doğrudan LIMIT'e girmemeli.
        rows = conn.execute(
            "SELECT * FROM chart_forecasts WHERE symbol=%s ORDER BY created_at DESC LIMIT %s",
            (str(symbol).upper(), max(1, min(int(limit), 500)))).fetchall()
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
            "ORDER BY created_at LIMIT %s", (now, max(1, min(int(limit), 500)))).fetchall()
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
        # V-18: parametre olarak geçtiği için SQL enjeksiyonu zaten yoktu, ama
        # kullanıcının yazdığı `%` / `_` LIKE jokeri gibi davranıyordu
        # ("BUY_SIGNAL" araması herhangi bir karakteri eşliyordu). Artık harfi harfine.
        needle = f"%{_escape_like(str(q).strip())}%"
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
def _symbol_target_state_default(symbol: str, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    return {"symbol": symbol, "target_pct": 2.0, "horizon_minutes": 5, "success_count": 0,
            "fail_count": 0, "total_count": 0, "last_adjusted_at": now, "created_at": now}


def _symbol_target_state_dict(symbol: str, row) -> dict:
    return {"symbol": symbol, "target_pct": float(row["target_pct"] or 2.0),
            "horizon_minutes": int(row["horizon_minutes"] or 5),
            "success_count": int(row["success_count"] or 0), "fail_count": int(row["fail_count"] or 0),
            "total_count": int(row["total_count"] or 0),
            "last_adjusted_at": float(row["last_adjusted_at"] or 0),
            "created_at": float(row["created_at"] or 0)}


async def get_symbol_target_state(symbol: str) -> dict:
    """Sembol için adaptif hedef durumu DÖNDÜRÜR — V-05: SALT OKUMA.

    Eskiden satır yoksa burada INSERT + COMMIT yapılıyordu: adı `get_*` olan bir
    okuma yolu veritabanını değiştiriyor, `ON CONFLICT` olmadığı için eşzamanlı
    ilk isteklerde `UniqueViolation` üretebiliyordu. Artık yazma YOKTUR; satır
    yoksa varsayılan değer döner. Yazma, sonucu kaydeden
    `record_symbol_target_outcome` içinde tek transaction'da yapılır.
    """
    sym = str(symbol or "").strip().upper()
    def op(conn):
        row = conn.execute("SELECT * FROM symbol_target_state WHERE symbol=%s", (sym,)).fetchone()
        if row is None:
            return _symbol_target_state_default(sym)
        return _symbol_target_state_dict(sym, row)
    return await _run_db(op)


def _next_target_pct(current_target: float, achieved_pct: float | None, total_count: int) -> float:
    """EMA tabanlı sembol hedefi güncellemesi (SAF — DB'siz test edilebilir).

    ``achieved_pct=None`` → gerçekleşen hareket ÖLÇÜLEMEDİ; hedef DEĞİŞMEZ
    (yalnız sayaçlar işler). Radar/pending yolu gerçek MFE ölçemez, o yüzden
    oradan hedef beslenmez: eskiden isabet `hedef` ve ıska `0.0` olarak
    gönderiliyordu → uydurma değerler EMA'yı aşağı sürüklüyor, %100 isabet eden
    sembolün hedefi bile düşüyordu (2026-09-17 teşhisi).

    Taban HER ZAMAN mevcut hedeftir (ilk örnekte de): eski kod ilk örnekte
    doğrudan ölçüme atlıyordu, tek bir erken ıska hedefi tabana çiviyordu.
    Örnek arttıkça alfa düşer (1 örnek 0.5 → 10 örnek ~0.23 → 30+ 0.1).

    Dönüş değeri HER İKİ dalda da tüketicinin kelepçesine
    (``MONITORING_TARGET_PCT_MIN/MAX``) çekilir: eski sürüm [1.0, 10.0]
    aralığında yazdığı için devralınan satırlar aralık dışında olabilir
    (ör. 1.0) ve ölçüm gelmese bile kendini toparlar.
    """
    if achieved_pct is None:
        new_target = float(current_target)
    else:
        conservative = min(float(achieved_pct), config.MONITORING_TARGET_PCT_MAX) * 0.8
        alpha = max(0.1, min(0.5, 3.0 / max(1, int(total_count))))
        new_target = current_target * (1 - alpha) + conservative * alpha
    return max(config.MONITORING_TARGET_PCT_MIN,
               min(config.MONITORING_TARGET_PCT_MAX, new_target))


async def record_symbol_target_outcome(symbol: str, success: bool,
                                       achieved_pct: float | None = None) -> dict:
    """Sembol için bir tahmin sonucu kaydeder; ölçüm VARSA adaptif hedefi ayarlar.

    GELİŞTİRİLMİŞ (2026-09-17): artık sadece başarı/başarısız saymıyor; gerçekleşen
    MFE'nin (``achieved_pct``) üstel hareketli ortalamasını (EMA) tutuyor. Hedef,
    gerçekleşen potansiyelin %80'i olarak İKİ YÖNLÜ güncellenir.

    ``achieved_pct=None`` → ölçüm yok; hedefe dokunulmaz, yalnız sayaçlar işler.
    Ölçüm yalnızca gerçek MFE üretebilen iki yol tarafından verilir:
    ``fill_rising_alert_outcomes`` (kapanmış 5m mumlar) ve
    ``velocity_learning_loop`` (``_mfe_from_window``). Radar/pending yolu uydurma
    değer GÖNDERMEZ.

    Ufuk (``horizon_minutes``) ÖĞRENİLMEZ: okuyan tek iki tüketici
    (``velocity.detect_velocity_candidates``, ``monitoring._run_rising_scan``)
    yalnız ``target_pct`` + ``total_count`` kullanır; kullanılmayan ufuk ayarı
    yanıltıcı olduğu için kaldırıldı (2026-09-17 denetimi).
    """
    sym = str(symbol or "").strip().upper()
    now = time.time()

    def op(conn):
        conn.execute(
            "INSERT INTO symbol_target_state(symbol,target_pct,horizon_minutes,success_count,fail_count,total_count,last_adjusted_at,created_at) "
            "VALUES(%s,%s,%s,0,0,0,%s,%s) ON CONFLICT(symbol) DO NOTHING",
            (sym, 2.0, 5, now, now))
        row = conn.execute("SELECT * FROM symbol_target_state WHERE symbol=%s FOR UPDATE", (sym,)).fetchone()
        state = _symbol_target_state_dict(sym, row) if row is not None else _symbol_target_state_default(sym, now)
        success_count = int(state["success_count"]) + (1 if success else 0)
        fail_count = int(state["fail_count"]) + (0 if success else 1)
        total_count = success_count + fail_count
        current_target = float(state["target_pct"])
        horizon = int(state["horizon_minutes"])

        new_target = _next_target_pct(current_target, achieved_pct, total_count)
        success_rate = success_count / total_count if total_count > 0 else 0.5

        conn.execute("UPDATE symbol_target_state SET target_pct=%s, horizon_minutes=%s, success_count=%s, fail_count=%s, total_count=%s, last_adjusted_at=%s WHERE symbol=%s",
                     (round(new_target, 3), horizon, success_count, fail_count, total_count, now, sym))
        conn.commit()
        return {"symbol": sym, "target_pct": round(new_target, 3), "horizon_minutes": horizon,
                "success_count": success_count, "fail_count": fail_count, "total_count": total_count,
                "success_rate": round(success_rate, 3),
                "achieved_pct": (round(float(achieved_pct), 3) if achieved_pct is not None else None)}
    return await _run_db(op)


async def get_all_symbol_target_states() -> list[dict]:
    """Tüm sembol hedef durumlarını döndürür (raporlama için)."""
    def op(conn):
        rows = conn.execute("SELECT * FROM symbol_target_state ORDER BY total_count DESC, symbol").fetchall()
        return [{"symbol": r["symbol"], "target_pct": float(r["target_pct"] or 2.0), "horizon_minutes": int(r["horizon_minutes"] or 5),
                 "success_count": int(r["success_count"] or 0), "fail_count": int(r["fail_count"] or 0),
                 "total_count": int(r["total_count"] or 0), "last_adjusted_at": float(r["last_adjusted_at"] or 0)} for r in rows]
    return await _run_db(op)


# ---------------------------------------------------------------------------
# Otonom Paper Trade (2026-09-04): monitoring bildiriminden tetiklenen pozisyonlar
# ---------------------------------------------------------------------------
# NOT (V-20): `save_auto_paper_trade(trade)` burada duruyordu. Salt INSERT'ti
# (atomik değil) ve repoda HİÇBİR okuyucusu yoktu; I-11 onu "kablolamayın —
# silin" diye işaretlemişti çünkü kablolamak mutabakatsız işlem kaydı üretir.
# Yerini `open_auto_paper_trade` (kilit + churn kontrolü + cüzdan düşümü, tek
# transaction) aldı. Silindi.


async def open_auto_paper_trade(trade: dict, signal: dict) -> tuple[dict | None, str]:
    """Atomik otonom paper açılışı: kilit + churn/pozisyon kontrolü + wallet düşümü + sinyal.

    Tek transaction içinde:
      1. Sembol adına advisory lock alır (eşzamanlı açılış yarışını önler)
      2. Sembolde zaten açık auto_paper pozisyonu varsa işlemez (open_trade döner)
      3. notification_id daha önce işlendiyse (geçmişte aynı bildirimle trade kapandıysa)
         yeniden açılışı engeller (churn koruması)
      4. Yeterli bakiye kontrolü + wallet düşümü
      5. auto_paper_trades INSERT + signals/decision_logs kaydı tek commit'te

    Dönen tuple: (trade_row veya None, durum) — durum:
      "opened" | "already_open" | "already_traded" | "max_open" | "insufficient_balance" | "error"
    """
    symbol = str(trade["symbol"]).upper()
    notification_id = trade.get("notification_id")

    def op(conn):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"auto_paper_open_{symbol}",))
        # Açık pozisyon kontrolü
        open_row = conn.execute(
            "SELECT * FROM auto_paper_trades WHERE symbol=? AND status='open' ORDER BY entry_time DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        if open_row:
            return (dict(open_row), "already_open")
        # Denetim düzeltmesi (atomik global limit): uygulama katmanındaki sayım
        # ile bu insert arasında yarış penceresi vardı — eşzamanlı tarama
        # tetiklerinde AUTO_PAPER_MAX_OPEN_POSITIONS+1 pozisyon açılabilirdi.
        # Sayım artık advisory xact_lock'lu bu op içinde yapılır → atomik.
        # D-11/Erkan (2026-09-18): çalışma-anı sınırı signal'dan yeğlenir
        # (Ayarlar > Otonom Paper Trade > Max açık pozisyon); yoksa sınıf
        # varsayılanı. 0 = sınırsız.
        global_max = int(signal.get("max_open_positions")
                         if signal.get("max_open_positions") is not None
                         else getattr(config, "AUTO_PAPER_MAX_OPEN_POSITIONS", 0) or 0)
        if global_max > 0:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM auto_paper_trades WHERE status='open'"
            ).fetchone()
            if cnt and int(cnt[0] or 0) >= global_max:
                return (None, "max_open")
        # Ana positions tablosunda da aynı sembol açıksa çakışmayı önle
        main_pos = conn.execute(
            "SELECT 1 FROM positions WHERE symbol=?",
            (symbol,)
        ).fetchone()
        if main_pos:
            return (None, "already_open")
        # Aynı bildirim daha önce işlendi mi? (churn: SL/TP kapanışı sonrası yeniden açma)
        if notification_id is not None:
            prior = conn.execute(
                "SELECT COUNT(*) FROM auto_paper_trades WHERE notification_id=?",
                (notification_id,)
            ).fetchone()
            if prior and int(prior[0] or 0) > 0:
                return (None, "already_traded")
        # R3-09: kalıcı yeniden-açma anahtarı da churn korumasına girer (string id
        # bigint `notification_id`'ye yazılamaz; `notification_key TEXT` bunu taşır).
        notification_key = trade.get("notification_key")
        if notification_key:
            prior_key = conn.execute(
                "SELECT COUNT(*) FROM auto_paper_trades WHERE notification_key=?",
                (notification_key,)
            ).fetchone()
            if prior_key and int(prior_key[0] or 0) > 0:
                return (None, "already_traded")
        # Bakiye kontrolü + düşüm
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=? FOR UPDATE", ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else 0.0)
        order_value = float(trade.get("order_value_try") or 0)
        commission_pct = config.COMMISSION_PCT
        debit = order_value * (1 + commission_pct)
        if order_value <= 0 or current_cash + 1e-9 < debit:
            return (None, "insufficient_balance")
        next_cash = current_cash - debit
        conn.execute(
            "INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount",
            ("TRY", next_cash)
        )
        row = conn.execute(
"""INSERT INTO auto_paper_trades
               (symbol, side, status, notification_id, notification_key, entry_price, quantity, order_value_try,
                stop_loss, take_profit, peak_price, entry_time,
                notification_score, notification_target_pct, notification_expected_price,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING *""",
            (symbol, trade.get("side", "LONG"), "open",
             notification_id, notification_key, trade["entry_price"], trade["quantity"], order_value,
             trade.get("stop_loss"), trade.get("take_profit"),
             trade.get("peak_price", trade["entry_price"]), trade["entry_time"],
             trade.get("notification_score"), trade.get("notification_target_pct"),
             trade.get("notification_expected_price"), trade["created_at"], trade["updated_at"])
        ).fetchone()
        if signal:
            trade_id_val = row["id"] if row else None
            conn.execute(
                "INSERT INTO signals(timestamp,symbol,action,price,reason,strategy,trade_id) VALUES(?,?,?,?,?,?,?)",
                (signal.get("timestamp") or trade["entry_time"], symbol, signal.get("action"), signal.get("price"),
                 signal.get("reason"), signal.get("strategy"),
                 signal.get("trade_id") or (f"auto_paper-{trade_id_val}" if trade_id_val else None))
            )
            conn.execute(
                "INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)",
                (signal.get("timestamp") or trade["entry_time"], symbol, signal.get("strategy"), signal.get("action"),
                 signal.get("reason"), signal.get("price"), _json_safe_dumps(signal, default=str))
            )
        conn.commit()
        row_dict = dict(row) if row else None
        if row_dict is not None:
            for k in ("tp1_scalp_pct", "tp2_runner_pct", "confluence_4way", "trailing_gap_pct"):
                if k in trade and k not in row_dict:
                    row_dict[k] = trade[k]
        return (row_dict, "opened")

    try:
        return await _run_db(op)
    except Exception as exc:
        logger.exception("open_auto_paper_trade %s: %s", symbol, exc)
        return (None, "error")


async def get_open_auto_paper_trade(symbol: str) -> dict | None:
    """Sembol için açık otonom paper trade varsa döndür."""
    def op(conn):
        row = conn.execute(
            "SELECT * FROM auto_paper_trades WHERE symbol=? AND status='open' ORDER BY entry_time DESC LIMIT 1",
            (str(symbol).upper(),)
        ).fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def get_recent_auto_paper_trade_by_notification_key(notification_key: str) -> dict | None:
    """R3-09: kalıcı yeniden-açma anahtarına göre son auto paper trade'i döndür."""
    def op(conn):
        row = conn.execute(
            "SELECT * FROM auto_paper_trades WHERE notification_key=? ORDER BY entry_time DESC LIMIT 1",
            (str(notification_key),)
        ).fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def get_recent_auto_paper_trade_by_notification(notification_id) -> dict | None:
    """Belirli bir bildirim için daha önce açılmış auto paper trade varsa döndür."""
    def op(conn):
        row = conn.execute(
            "SELECT * FROM auto_paper_trades WHERE notification_id=? ORDER BY entry_time DESC LIMIT 1",
            (notification_id,)
        ).fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def get_auto_paper_trade(trade_id: int) -> dict | None:
    """ID ile otonom paper trade getir."""
    def op(conn):
        row = conn.execute("SELECT * FROM auto_paper_trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None
    return await _run_db(op)


async def list_auto_paper_trades(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
) -> list[dict]:
    """Otonom paper trade'leri listele (yeni -> eski). offset pagination ve gün filtresi destekler."""
    eff_since, eff_until = _resolve_time_bounds(since=since, until=until, day=day, default_to_today=False)
    def op(conn):
        where_clauses = []
        params = []
        if status:
            where_clauses.append("status=?")
            params.append(status)
        if eff_since is not None:
            if status == "closed":
                where_clauses.append("exit_time >= ?")
                params.append(eff_since)
            elif status == "open":
                where_clauses.append("entry_time >= ?")
                params.append(eff_since)
            else:
                where_clauses.append("((status='closed' AND exit_time >= ?) OR (status='open' AND entry_time >= ?))")
                params.extend([eff_since, eff_since])
        if eff_until is not None:
            if status == "closed":
                where_clauses.append("exit_time < ?")
                params.append(eff_until)
            elif status == "open":
                where_clauses.append("entry_time < ?")
                params.append(eff_until)
            else:
                where_clauses.append("((status='closed' AND exit_time < ?) OR (status='open' AND entry_time < ?))")
                params.extend([eff_until, eff_until])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT * FROM auto_paper_trades {where_sql} ORDER BY entry_time DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(int(limit), 10000)), max(0, int(offset))])
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    return await _run_db(op)


async def get_auto_paper_stats(
    confluence_4way_only: bool = False,
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
) -> dict:
    """Otonom paper trade istatistikleri (seçilen gün veya reset_at sonrası, SQL agregatı).

    Portföy reseti sırasında pnl'siz kapatılan 'reset' satırları hariçtir;
    böylece reset sonrasi win_rate/net PnL eski verilerle kirletilmez.
    ``confluence_4way_only=True`` ise yalnızca Master Surge (4'lü teyitli) işlemler sayılır.
    """
    eff_since, eff_until = _resolve_time_bounds(since=since, until=until, day=day, default_to_today=True)
    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        if eff_since is not None:
            cutoff = max(cutoff or 0.0, float(eff_since))

        closed_where = "WHERE status='closed' AND COALESCE(exit_reason,'') <> 'reset'"
        closed_params: list = []
        if cutoff:
            closed_where += " AND exit_time >= ?"
            closed_params.append(cutoff)
        if eff_until:
            closed_where += " AND exit_time < ?"
            closed_params.append(eff_until)
        if confluence_4way_only:
            closed_where += " AND confluence_4way = TRUE"

        row = conn.execute(
            f"""SELECT COUNT(*) AS closed,
                       COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS winning,
                       COALESCE(SUM(CASE WHEN COALESCE(pnl, 0) <= 0 THEN 1 ELSE 0 END), 0) AS losing,
                       COALESCE(SUM(COALESCE(pnl, 0)), 0) AS total_pnl,
                       COALESCE(SUM(COALESCE(order_value_try, 0)), 0) AS total_invested
                FROM auto_paper_trades {closed_where}""",
            closed_params,
        ).fetchone()

        open_where = "WHERE status='open'"
        open_params: list = []
        if cutoff:
            open_where += " AND entry_time >= ?"
            open_params.append(cutoff)
        if eff_until:
            open_where += " AND entry_time < ?"
            open_params.append(eff_until)
        if confluence_4way_only:
            open_where += " AND confluence_4way = TRUE"

        open_row = conn.execute(
            f"SELECT COUNT(*) AS open FROM auto_paper_trades {open_where}",
            open_params,
        ).fetchone()

        closed = int(row["closed"] or 0)
        winning = int(row["winning"] or 0)
        total_pnl = float(row["total_pnl"] or 0.0)
        return {
            "total": closed + int(open_row["open"] or 0),
            "open": int(open_row["open"] or 0),
            "closed": closed,
            "winning": winning,
            "losing": int(row["losing"] or 0),
            "win_rate": round(winning / closed * 100, 1) if closed else 0.0,
            "total_pnl_try": round(total_pnl, 2),
            "total_invested_try": round(float(row["total_invested"] or 0.0), 2),
            "avg_pnl_try": round(total_pnl / closed, 2) if closed else 0.0,
        }
    return await _run_db(op)


async def get_auto_paper_symbol_breakdown(
    since: float | None = None,
    until: float | None = None,
    day: str | None = None,
) -> list[dict]:
    """Otonom paper trade sembol bazlı özet (seçilen gün / reset_at sonrası, reset kapanışları hariç)."""
    eff_since, eff_until = _resolve_time_bounds(since=since, until=until, day=day, default_to_today=True)
    def op(conn):
        cutoff = _get_reset_cutoff_sync(conn)
        if eff_since is not None:
            cutoff = max(cutoff or 0.0, float(eff_since))

        where = "WHERE status='closed' AND COALESCE(exit_reason,'') <> 'reset'"
        params: list = []
        if cutoff:
            where += " AND exit_time >= ?"
            params.append(cutoff)
        if eff_until:
            where += " AND exit_time < ?"
            params.append(eff_until)

        rows = conn.execute(
            f"""SELECT symbol, COUNT(*) AS trade_count,
                       COALESCE(SUM(CASE WHEN COALESCE(pnl,0) > 0 THEN 1 ELSE 0 END),0) AS winning,
                       COALESCE(SUM(COALESCE(pnl,0)),0) AS net_pnl,
                       COALESCE(SUM(COALESCE(commission,0)),0) AS commission
                FROM auto_paper_trades {where}
                GROUP BY symbol ORDER BY net_pnl DESC""",
            params,
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            total = int(item.get("trade_count") or 0)
            wins = int(item.get("winning") or 0)
            item["win_rate"] = round(wins / total * 100, 1) if total else 0.0
            out.append(item)
        return out
    return await _run_db(op)


async def update_auto_paper_trade_tp(trade_id: int, new_tp: float, score: float | None = None, target_pct: float | None = None) -> bool:
    """Açık pozisyonun TP'sini güncelle (bildirim hedef takibi)."""
    def op(conn):
        if score is not None and target_pct is not None:
            conn.execute(
                "UPDATE auto_paper_trades SET take_profit=?, notification_score=?, notification_target_pct=?, updated_at=? WHERE id=? AND status='open'",
                (new_tp, score, target_pct, time.time(), trade_id)
            )
        else:
            conn.execute(
                "UPDATE auto_paper_trades SET take_profit=?, updated_at=? WHERE id=? AND status='open'",
                (new_tp, time.time(), trade_id)
            )
        conn.commit()
        return True
    return await _run_db(op)


async def update_auto_paper_breakeven(trade_id: int, activated: bool, breakeven_stop: float | None = None) -> bool:
    """Breakeven korumasını güncelle."""
    def op(conn):
        conn.execute(
            "UPDATE auto_paper_trades SET breakeven_activated=?, breakeven_stop=?, updated_at=? WHERE id=? AND status='open'",
            (activated, breakeven_stop, time.time(), trade_id)
        )
        conn.commit()
        return True
    return await _run_db(op)


async def update_auto_paper_peak(trade_id: int, peak_price: float) -> bool:
    """Peak fiyatı güncelle."""
    def op(conn):
        conn.execute(
            "UPDATE auto_paper_trades SET peak_price=?, updated_at=? WHERE id=? AND status='open' AND peak_price < ?",
            (peak_price, time.time(), trade_id, peak_price)
        )
        conn.commit()
        return True
    return await _run_db(op)


async def update_auto_paper_trailing(trade_id: int, activated: bool, trailing_stop: float | None = None) -> bool:
    """Trailing stop korumasını güncelle (sadece fiyat yukarı hareket edince yazılır)."""
    def op(conn):
        conn.execute(
            "UPDATE auto_paper_trades SET trailing_activated=?, trailing_stop=?, updated_at=? "
            "WHERE id=? AND status='open'",
            (activated, trailing_stop, time.time(), trade_id)
        )
        conn.commit()
        return True
    return await _run_db(op)


async def close_auto_paper_trade(trade_id: int, exit_price: float, exit_time: float,
                                 pnl: float, pnl_pct: float, commission: float, reason: str) -> bool:
    """Auto paper pozisyonunu kapat VE wallet'a iade et (atomik).

    Tek transaction içinde pozisyon 'closed' yapılır, çıkış notional'ı
    (exit*(1-commission)) wallet'a eklenir ve CLOSE sinyali yazılır.
    Arada hata olursa her şey geri alınır — para iadesiz 'closed' kayıt kalmaz.
    """
    def op(conn):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"auto_paper_close_{trade_id}",))
        row = conn.execute(
            "SELECT * FROM auto_paper_trades WHERE id=? AND status='open' FOR UPDATE",
            (trade_id,)
        ).fetchone()
        if not row:
            return False
        trade = dict(row)
        symbol = str(trade["symbol"]).upper()
        quantity = float(trade["quantity"])
        commission_pct = config.COMMISSION_PCT
        conn.execute(
            """UPDATE auto_paper_trades SET status='closed', exit_price=?, exit_time=?,
               pnl=?, pnl_pct=?, commission=?, exit_reason=?, updated_at=?
               WHERE id=? AND status='open'""",
            (exit_price, exit_time, pnl, pnl_pct, commission, reason, time.time(), trade_id)
        )
        # Wallet'a iade: pozisyon değeri + kar/zarar (çıkış komisyonu düşülür)
        exit_notional = exit_price * quantity
        proceed = exit_notional * (1 - commission_pct)
        cash_row = conn.execute("SELECT amount FROM virtual_wallet WHERE asset=? FOR UPDATE", ("TRY",)).fetchone()
        current_cash = float(cash_row[0] if cash_row else 0.0)
        conn.execute(
            "INSERT INTO virtual_wallet(asset,amount) VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount",
            ("TRY", current_cash + proceed)
        )
        now = exit_time or time.time()
        conn.execute(
            "INSERT INTO signals(timestamp,symbol,action,price,reason,strategy,trade_id) VALUES(?,?,?,?,?,?,?)",
            (now, symbol, "CLOSE_LONG", exit_price,
             f"AUTO_PAPER_{reason.upper()} | PnL={pnl:.2f}TRY", "AUTO_PAPER", f"auto_paper-{trade_id}")
        )
        conn.execute(
            "INSERT INTO decision_logs(timestamp,symbol,strategy,decision,reason,price,metadata) VALUES(?,?,?,?,?,?,?)",
            (now, symbol, "AUTO_PAPER", f"CLOSE_{reason.upper()}",
             f"AUTO_PAPER_{reason.upper()} | PnL={pnl:.2f}TRY", exit_price,
             _json_safe_dumps({"trade_id": trade_id, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason}, default=str))
        )
        conn.commit()
        return True
    return await _run_db(op)
