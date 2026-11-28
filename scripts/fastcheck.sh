#!/usr/bin/env bash
# Hızlı doğrulama kapısı — yalnız DEĞİŞEN alana bakar (tüm paket değil).
#
# Kullanım:
#   scripts/fastcheck.sh            # son kırık testler (pytest --lf), yoksa hızlı tur
#   scripts/fastcheck.sh backend    # yalnız ruff + son kırık testler
#   scripts/fastcheck.sh frontend   # yalnız eslint + tsc
#
# Neden: tam paket 2.000+ test sürüyor ve dakikalar + binlerce token yiyor.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
WHICH="${1:-all}"

venv_python() {
  if [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
    echo "$BACKEND/.venv/Scripts/python.exe"      # Windows (Git Bash)
  elif [ -x "$BACKEND/.venv/bin/python" ]; then
    echo "$BACKEND/.venv/bin/python"              # Linux / macOS
  else
    echo ""
  fi
}

PY="$(venv_python)"

run_backend() {
  if [ -z "$PY" ]; then
    echo "fastcheck: backend/.venv bulunamadı — ruff/pytest atlandı" >&2
    return 0
  fi
  echo "── ruff (backend) ───────────────────────────────────────────"
  ( cd "$BACKEND" && "$PY" -m ruff check app tests scripts )
  echo "── pytest --lf (son kırık testler, yoksa hepsi) ─────────────"
  ( cd "$BACKEND" && "$PY" -m pytest --lf -x -q --no-header )
}

run_frontend() {
  if [ ! -d "$FRONTEND/node_modules" ]; then
    echo "fastcheck: frontend/node_modules yok — eslint/tsc atlandı" >&2
    return 0
  fi
  echo "── eslint (frontend, sadece app/) ───────────────────────────"
  ( cd "$FRONTEND" && npx --no-install eslint app --max-warnings=999 )
  echo "── tsc --noEmit (frontend) ──────────────────────────────────"
  ( cd "$FRONTEND" && npx --no-install tsc --noEmit --incremental false )
}

case "$WHICH" in
  backend) run_backend ;;
  frontend) run_frontend ;;
  all) run_backend; run_frontend ;;
  *) echo "kullanım: scripts/fastcheck.sh [all|backend|frontend]" >&2; exit 2 ;;
esac

echo "✓ fastcheck bitti"
