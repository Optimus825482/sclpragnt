#!/bin/sh
set -eu

if [ "${DB_BACKEND:-sqlite}" = "postgres" ] && [ -n "${DATABASE_URL:-}" ]; then
  echo "PostgreSQL schema migration başlatılıyor..."
  python scripts/run_postgres_migration.py
  echo "PostgreSQL schema migration tamamlandı."
fi

exec "$@"
