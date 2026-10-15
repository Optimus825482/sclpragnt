"""Run the ScalperAgent PostgreSQL migrations during a maintenance window.

Canlı deploy'da eski backend konteyneri hâlâ çalışıyor olabilir ve tablo
kilitlerini tutuyor olabilir (saniyede bir koşan tarama/temizlik döngüleri).
Bu yüzden script:

1. Session-level ``pg_advisory_lock`` alır — eşzamanlı ikinci bir migration
   koşucusu varsa sıraya girer (çakışan DDL yarışı olmaz).
2. ``schema_migrations`` tablosunu okuyup YALNIZ uygulanmamış dosyaları numara
   sırasıyla koşar. Her dosya kendi transaction'ında: DDL + kayıt birlikte
   commit olur ya da birlikte geri alınır. Uygulanmış dosya tekrar koşmaz;
   içeriği değişmiş uygulanmış dosya açık hatadır (sessiz yeniden koşma yok).
3. Geçici kilit / bağlantı hatalarında (``LockNotAvailableError`` vb.) sabırlı
   retry yapar: eski konteyner durana kadar toplam ~10+ dakika boyunca her
   denemede kilidi yeniden bekler. Kalıcı hatalar (SQL hatası, sha uyuşmazlığı)
   retry edilmeden hemen düşer.

Karar mantığı (dosya keşfi, sha, eski marker geçişi) ``app/migration_plan.py``
içindedir ve ``database.init_db()`` ile aynıdır. Uygulama tarafı da aynı dosya
kümesini aynı sırayla değerlendirir; ikisinden hangisi önce koşarsa koşsun
sonuç aynıdır.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# `app` paketi bu betiğin üst dizininde (backend/). `python scripts/…` ile
# koşulunca sys.path'te yoktur; ortak modülü bulabilmesi için eklenir.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.migration_plan import (  # noqa: E402
    MIGRATION_ADVISORY_KEY,
    MIGRATIONS_DIR_DEFAULT,
    SCHEMA_MIGRATIONS_DDL,
    LegacyMarkerError,
    MigrationDriftError,
    aggregate_sha256,
    discover_migrations,
    legacy_bootstrap_rows,
    plan_pending,
)

_MAX_ATTEMPTS = 20
# 2026-10-07 (P1-11 #5): 30 sn -> 60 sn. Canlı backend'in kilitleri (ACCESS
# EXCLUSIVE, saniyede bir koşan tarama/temizlik döngüleri) rastgele aralıklarla
# açılır. Tek bir denemede bekleme penceresini genişletmek, retry döngüsünün
# toplam süresini (~20 deneme × (60+10 sn) ≈ 23 dk) artırır.
#
# NOT: Uygulama tarafı `database.init_db()` DDL'i `SET LOCAL lock_timeout = '30s'`
# ile çalıştırır ve geçici hatada yeniden dener (bkz. database._apply_migration).
_LOCK_TIMEOUT_MS = 60_000
_RETRY_SLEEP_SEC = 10.0
# Eski tek-sha marker'ı (llm_settings). Yalnız schema_migrations boşken, bir kerelik
# geçiş için okunur; her uygulamadan sonra birleşik sha geriye dönük uyum için yazılır.
_SHA_MARKER_KEY = "schema_sha256"
# Geçici (retry edilebilir) PostgreSQL SQLSTATE'leri. İsim tabanlı küme asyncpg'nin
# sınıf adına bağlıdır; SQLSTATE daha dayanıklıdır (alt sınıf veya farklı bir hata
# yolu aynı kodu üretse de yakalanır).
#   55P03 lock_not_available · 40P01 deadlock_detected · 57P03 cannot_connect_now ·
#   53300 too_many_connections · 08006/08003 connection failure/does_not_exist
_TRANSIENT_SQLSTATES = {"55P03", "40P01", "57P03", "53300", "08006", "08003"}
_TRANSIENT_EXC_NAMES = {
    "LockNotAvailableError", "DeadlockDetectedError",
    "ConnectionDoesNotExistError", "InterfaceError", "PostgresConnectionError",
    "CannotConnectNowError", "TooManyConnectionsError",
}


def _is_transient(exc: BaseException) -> bool:
    """Yeniden denenmeye değer mi? Ağ/bağlantı hataları ve geçici kilit hataları evet."""
    if getattr(exc, "sqlstate", None) in _TRANSIENT_SQLSTATES:
        return True
    if isinstance(exc, (OSError, asyncio.TimeoutError)):
        return True
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


async def _apply(conn, migrations) -> int:
    """Bağlantı üzerinde bekleyen migration'ları uygular; uygulanan sayıyı döndürür.

    Çağıran advisory lock'u dışarıda tutar. Her dosya kendi transaction'ında koşar;
    yarıda kalan bir denemeden sonra yeniden plan çıkarıldığında kaldığı yerden devam eder.
    """
    await conn.execute(SCHEMA_MIGRATIONS_DDL)
    applied = {
        row["version"]: row["sha256"]
        for row in await conn.fetch("SELECT version, sha256 FROM schema_migrations")
    }
    bootstrapped = False
    if not applied and await conn.fetchval("SELECT to_regclass('public.llm_settings')") is not None:
        marker = await conn.fetchval("SELECT value FROM llm_settings WHERE key=$1", _SHA_MARKER_KEY)
        if marker:
            applied = legacy_bootstrap_rows(migrations, marker)
            async with conn.transaction():
                for version, sha in applied.items():
                    await conn.execute(
                        "INSERT INTO schema_migrations(version,sha256,applied_at) VALUES($1,$2,now())",
                        version, sha)
            bootstrapped = True
            print(f"Eski schema_sha256 marker'ı: {len(applied)} dosya uygulanmış sayıldı.", flush=True)

    pending = plan_pending(migrations, applied)
    for migration in pending:
        async with conn.transaction():
            await conn.execute(migration.sql)
            await conn.execute(
                "INSERT INTO schema_migrations(version,sha256,applied_at) VALUES($1,$2,now())",
                migration.version, migration.sha256)
        print(f"Uygulandı: {migration.version}", flush=True)

    if pending or bootstrapped:
        # Geriye dönük uyum: eski binary'ler birleşik marker'ı okur (yeni kod okumaz).
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO llm_settings(key,value) VALUES($1,$2) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                _SHA_MARKER_KEY, aggregate_sha256(migrations))
    return len(pending)


async def _run_once(url: str, migrations) -> int:
    conn = await asyncpg.connect(
        url,
        timeout=10,
        server_settings={
            "statement_timeout": "120000",
            # Canlı backend'in kilitleri rastgele aralıklarda açılır; tek sorgu
            # penceresi yetsin, kalanını retry döngüsü karşılasın.
            "lock_timeout": str(_LOCK_TIMEOUT_MS),
        },
    )
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_ADVISORY_KEY)
        try:
            return await _apply(conn, migrations)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_KEY)
    finally:
        await conn.close()


async def main(migrations_dir: Path | None = None):
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    # Dosya listesi tek kaynaktan (backend/migrations, numara sırası) okunur;
    # database.init_db() ile aynı modül kullanıldığı için iki yol aynı kararı verir.
    if migrations_dir is None:
        migrations_dir = MIGRATIONS_DIR_DEFAULT
    migrations = discover_migrations(migrations_dir)
    print(
        f"Migration dosyaları: {len(migrations)} "
        f"(birleşik sha256={aggregate_sha256(migrations)[:12]}…)",
        flush=True,
    )

    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            applied_count = await _run_once(url, migrations)
        except (LegacyMarkerError, MigrationDriftError) as exc:
            # Veri bütünlüğü sorunu: retry bunu çözmez, operatör karar vermeli.
            raise SystemExit(f"PostgreSQL migration durduruldu: {exc}")
        except Exception as exc:
            if not _is_transient(exc):
                raise SystemExit(
                    f"PostgreSQL migration başarısız (kalıcı hata, yeniden denenmedi): "
                    f"{type(exc).__name__}: {exc}")
            last_error = exc
            print(
                f"PostgreSQL migration denemesi {attempt}/{_MAX_ATTEMPTS} başarısız "
                f"({type(exc).__name__}: {exc}). Eski konteyner kilitleri bırakana kadar bekleniyor...",
                file=sys.stderr,
                flush=True,
            )
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_SLEEP_SEC)
        else:
            if applied_count:
                print(f"PostgreSQL migration tamamlandı ({applied_count} dosya uygulandı).", flush=True)
            else:
                print("PostgreSQL şeması güncel; uygulanacak migration yok.", flush=True)
            return
    raise SystemExit(f"PostgreSQL migration bağlantı/kilit beklemesi tükendi: {last_error}")


if __name__ == "__main__":
    asyncio.run(main())
