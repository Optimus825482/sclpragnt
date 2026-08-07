#!/bin/sh
set -eu

if [ "${DB_BACKEND:-postgres}" != "postgres" ]; then
  echo "HATA: Scalper Agent yalnızca PostgreSQL ile çalışır (DB_BACKEND=postgres gerekli)." >&2
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "HATA: PostgreSQL için DATABASE_URL tanımlı değil." >&2
  exit 1
fi

echo "PostgreSQL schema migration başlatılıyor..."
python scripts/run_postgres_migration.py
echo "PostgreSQL schema migration tamamlandı."

exec "$@"
