#!/bin/sh
# 2026-10-15 (denetim düzeltmesi, §5 P1): günlük PostgreSQL yedeği.
#
# docker-compose.yaml'daki `db-backup` servisi bu betiği 24 saatte bir çağırır.
# Postgres ile AYNI imajda koşar (pgvector/pgvector:pg17-bookworm) → pg_dump
# sürümü sunucuyla birebir eşleşir. Bağlantı bilgisi libpq ortam değişkenleri
# ile gelir (PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD).
#
# Çıktı: $BACKUP_DIR/scalper_<YYYYMMDD_HHMMSS>.dump  (custom format, -Fc)
# Saklama: ad sırasına göre son $BACKUP_KEEP (varsayılan 14) dosya kalır.
#
# Geri yükleme (README'de de var):
#   docker compose exec -T postgres pg_restore -U scalper -d scalper --clean --if-exists --no-owner --no-acl /backups/<dosya>
# (db-backup konteynerinden: pg_restore --clean --if-exists --no-owner --no-acl -d "$PGDATABASE" "$BACKUP_DIR/<dosya>")
#
# Hata durumunda betik sıfır-dışı döner ama compose döngüsü (`while true`)
# bir sonraki güne devam eder; başarısız dosya `.partial` uzantısıyla
# silinir ki yarım dump "geçerli yedek" sanılmasın.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
PREFIX="${BACKUP_PREFIX:-scalper}"

mkdir -p "$BACKUP_DIR"

stamp="$(date +%Y%m%d_%H%M%S)"
target="$BACKUP_DIR/${PREFIX}_${stamp}.dump"
tmp="$target.partial"

echo "[pg_backup] $(date -Iseconds) başlıyor → $target"

if ! pg_dump --format=custom --no-owner --no-acl --file "$tmp"; then
    echo "[pg_backup] HATA: pg_dump başarısız; yarım dosya siliniyor." >&2
    rm -f "$tmp"
    exit 1
fi

# PGDMP imzası: custom-format dosyanın ilk 5 baytı. Boş/bozuk çıktıyı yakalar.
if [ "$(head -c 5 "$tmp" 2>/dev/null)" != "PGDMP" ]; then
    echo "[pg_backup] HATA: çıktı geçerli bir pg_dump custom-format dosyası değil." >&2
    rm -f "$tmp"
    exit 1
fi

mv "$tmp" "$target"
echo "[pg_backup] tamam: $(du -h "$target" | cut -f1) $target"

# Saklama: ad sırası = zaman sırası (zaman damgası sabit genişlikte).
# `ls -1` + `head` ile en eski olanlar silinir; POSIX sh, bash'e gerek yok.
count="$(ls -1 "$BACKUP_DIR"/"${PREFIX}"_*.dump 2>/dev/null | wc -l | tr -d ' ')"
if [ "$count" -gt "$BACKUP_KEEP" ]; then
    excess=$((count - BACKUP_KEEP))
    ls -1 "$BACKUP_DIR"/"${PREFIX}"_*.dump | sort | head -n "$excess" | while IFS= read -r old; do
        echo "[pg_backup] eski yedek siliniyor: $old"
        rm -f "$old"
    done
fi

echo "[pg_backup] saklanan yedek sayısı: $(ls -1 "$BACKUP_DIR"/"${PREFIX}"_*.dump 2>/dev/null | wc -l | tr -d ' ') (limit $BACKUP_KEEP)"
