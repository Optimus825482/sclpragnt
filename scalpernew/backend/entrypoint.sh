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

# ---------------------------------------------------------------------------
# P1-11 follow-up (2026-10-07): non-root konteyner + eski root-sahipli volume.
#
# Konteyner artık uid 10001 (scalper) olarak çalışır. Ancak `scalper_data`
# volume'u ÖNCEKİ root konteyner tarafından doldurulmuşsa dosyalar root
# sahipliğindedir ve uid 10001 yazamaz. Belirti: ML eğitimi
# "PermissionError: /data/ml_models/upside_v4.joblib" ile düşer → grafik
# tahmini 503. Yeni bir volume bu sorunu yaşamaz (Dockerfile /data'yı
# 10001'e chown eder); yalnız YÜKSELTME yolunda görülür.
#
# Kalıcı/kalıcı-olmayan düzeltme sırası:
#   1) Eğer root isek (bazı kurulumlar `user:` override eder) sahipliği al.
#   2) Değilsek ve hedef dizin yazılamıyorsa, yazılabilir bir yedek dizine
#      düş ve GÜRÜLTÜLÜ uyar — ölümcül hata yerine bozulmuş ama çalışan servis.
#   Asıl düzeltme host'ta tek seferliktir (README/Dockerfile notu):
#     docker run --rm -v scalper_data:/data alpine chown -R 10001:10001 /data
# ---------------------------------------------------------------------------
ensure_writable_dir() {
  target="$1"
  if mkdir -p "$target" 2>/dev/null && touch "$target/.write_probe" 2>/dev/null; then
    rm -f "$target/.write_probe"
    return 0
  fi
  # Root isek sahipliği devral (kurtarma yolu).
  if [ "$(id -u)" = "0" ]; then
    chown -R 10001:10001 "$target" 2>/dev/null || true
    if touch "$target/.write_probe" 2>/dev/null; then
      rm -f "$target/.write_probe"
      return 0
    fi
  fi
  return 1
}

ml_dir="${ML_MODELS_DIR:-/data/ml_models}"
if ! ensure_writable_dir "$ml_dir"; then
  fallback="/tmp/ml_models"
  echo "UYARI: '$ml_dir' yazılamıyor (volume sahipliği root olabilir)." >&2
  echo "        Geçici olarak '$fallback' kullanılacak — MODEL RESTART'TA KAYBOLUR." >&2
  echo "        Kalıcı düzeltme (host'ta bir kez):" >&2
  echo "          docker run --rm -v scalper_data:/data alpine chown -R 10001:10001 /data" >&2
  mkdir -p "$fallback"
  export ML_MODELS_DIR="$fallback"
fi

echo "PostgreSQL schema migration başlatılıyor..."
python scripts/run_postgres_migration.py
echo "PostgreSQL schema migration tamamlandı."

exec "$@"
