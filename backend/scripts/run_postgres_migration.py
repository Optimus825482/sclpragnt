"""Run the ScalperAgent PostgreSQL schema during a maintenance window.

Canlı deploy'da eski backend konteyneri hâlâ çalışıyor olabilir ve tablo
kilitlerini tutuyor olabilir (saniyede bir koşan tarama/temizlik döngüleri).
Bu yüzden script:

1. Önce session-level ``pg_advisory_lock`` alır — eşzamanlı ikinci bir
   migration koşucusu varsa sıraya girer (çakışan DDL yarışı olmaz).
2. Şemayı tek idempotent transaction'da uygular (tüm ifadeler
   ``IF NOT EXISTS``; yarım kalan transaction rollback'te temiz bırakır).
3. ``LockNotAvailableError``'a karşı sabırlı retry yapar: eski konteyner
   durana kadar toplam ~10+ dakika boyunca her denemede kilidi yeniden
   bekler. Böylece deploy overlap'i restart-loop'a dönüşmez.

Uygulama tarafındaki ``database.init_db()`` aynı şemayı lock_timeout'suz
(sonsuz bekleme) çalıştırır; bu script'in kısa lock_timeout'u yalnızca
fail-fast olmak içindi ve canlı overlap senaryosunda ters tekiyordu.
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg

# Migration koşucularını sıraya sokan sabit advisory lock anahtarı.
_MIGRATION_ADVISORY_KEY = 0x5343414C  # 'SCAL'
_MAX_ATTEMPTS = 20
_LOCK_TIMEOUT_MS = 30_000
_RETRY_SLEEP_SEC = 10.0
_SHA_MARKER_KEY = "schema_sha256"


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "001_pgvector_schema.sql").read_text(encoding="utf-8")
    schema_sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        conn = None
        try:
            conn = await asyncpg.connect(
                url,
                timeout=10,
                server_settings={
                    "statement_timeout": "120000",
                    # Canlı backend'in kilitleri rastgele aralıklarda açılır;
                    # 5 saniye yerine 30 saniye bekle ki tek sorgu penceresi
                    # yetsin, kalanını retry döngüsü karşılasın.
                    "lock_timeout": str(_LOCK_TIMEOUT_MS),
                },
            )
            # Hızlı yol: şema zaten bu dosyanın sha'sı kadar uygulanmışsa
            # HİÇ DDL koşma. Bu olmayan durumda her restart, canlı sistemle
            # DDL lock yarışı riskini yeniden alıyordu.
            marker = None
            if await conn.fetchval("SELECT to_regclass('public.llm_settings')") is not None:
                marker = await conn.fetchval(
                    "SELECT value FROM llm_settings WHERE key=$1", _SHA_MARKER_KEY)
            if marker == schema_sha:
                print("PostgreSQL şeması güncel (sha eşleşti); migration atlandı.", flush=True)
                await conn.close()
                return
            # Başka bir migration koşucusu (örn. paralel konteyner) varsa
            # bekleyip sıraya gir; session-level lock, transaction'lardan bağımsız.
            await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_ADVISORY_KEY)
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO llm_settings(key,value) VALUES($1,$2) "
                        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                        _SHA_MARKER_KEY, schema_sha)
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_ADVISORY_KEY)
            print("PostgreSQL migration tamamlandı.", flush=True)
            await conn.close()
            return
        except Exception as exc:
            last_error = exc
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
            transient = type(exc).__name__ in {
                "LockNotAvailableError", "DeadlockDetectedError",
                "ConnectionDoesNotExistError", "InterfaceError", "PostgresConnectionError",
                "CannotConnectNowError", "TooManyConnectionsError",
            }
            print(
                f"PostgreSQL migration denemesi {attempt}/{_MAX_ATTEMPTS} başarısız "
                f"({type(exc).__name__}: {exc})."
                + (" Eski konteyner kilitleri bırakana kadar bekleniyor..." if transient else ""),
                file=sys.stderr,
                flush=True,
            )
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_SLEEP_SEC)
    raise SystemExit(f"PostgreSQL migration bağlantı/kilit beklemesi tükendi: {last_error}")


if __name__ == "__main__":
    asyncio.run(main())
