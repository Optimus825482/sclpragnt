"""Şema migration'larının DOSYA BAŞINA takibi — runner ve init_db ortak mantığı.

Bu modül veritabanı sürücüsüne bağlı DEĞİL. Burada yalnızca karar verilir:

* hangi dosyalar var, hangi sırayla, sha'ları ne (``discover_migrations``),
* veritabanında kayıtlı uygulanmış dosyalara göre ne bekliyor (``plan_pending``),
* uygulanmış bir dosyanın içeriği değişmişse (``MigrationDriftError``),
* eski tek-sha marker'ından (``schema_sha256``) geçiş (``legacy_bootstrap_rows``).

SQL'in çalıştırılması, transaction ve kilit ise çağıranda kalır:
``scripts/run_postgres_migration.py`` (asyncpg) ve ``app/database.py`` (psycopg).
İkisi de bu modülü kullanır; böylece "hangi dosya uygulandı" kararı tek yerde.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# Yalnız sıra numarası + `_` ile başlayan dosyalar şemaya girer (`001_…sql`).
MIGRATION_FILE_RE = re.compile(r"^(\d+)_.+\.sql$")
# Tek kaynak: backend/migrations (bu dosya backend/app/ altında).
MIGRATIONS_DIR_DEFAULT = Path(__file__).resolve().parents[1] / "migrations"
# Eski tek-sha marker'ının llm_settings içindeki anahtarı. Yeni kod bunu YALNIZCA
# `schema_migrations` boşken, bir kerelik geçiş için okur; geriye dönük uyum için
# de her uygulama sonunda tüm dosyaların birleşik sha'sını yazar.
LEGACY_MARKER_KEY = "schema_sha256"
# Migration koşucularını sıraya sokan sabit session-level advisory lock anahtarı.
MIGRATION_ADVISORY_KEY = 0x5343414C  # 'SCAL'
# Uygulanmış dosyaların kaydı. Her dosya kendi transaction'ında koşar; DDL ile bu
# satırın yazımı aynı transaction'dadır (yarım uygulanmış dosya "uygulandı" sayılmaz).
SCHEMA_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    " version TEXT PRIMARY KEY,"
    " sha256 TEXT NOT NULL,"
    " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


class MigrationDriftError(RuntimeError):
    """Uygulanmış bir migration dosyasının içeriği değişmiş."""


class LegacyMarkerError(RuntimeError):
    """Eski marker hiçbir migration önekiyle eşleşmiyor; geçiş güvenle yapılamaz."""


@dataclass(frozen=True)
class Migration:
    version: str  # dosya adı, ör. "001_pgvector_schema.sql"
    number: int
    sql: str
    sha256: str


def aggregate_sha256(migrations) -> str:
    """Migration dizisinin birleşik sha'sı (eski `schema_sha256` ile birebir aynı formül)."""
    text = "".join(m.sql + "\n" for m in migrations)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_migrations(migrations_dir) -> list[Migration]:
    """Migration dosyalarını numara sırasıyla okur.

    Aynı numarayı taşıyan iki dosya (ör. iki dalın ikisi de `014_…`) açık hatadır:
    sıra belirsizleşir ve hangisinin önce koşacağı kimsenin kararı olmaz.
    """
    entries = []
    for path in Path(migrations_dir).iterdir():
        match = MIGRATION_FILE_RE.match(path.name)
        if match and path.is_file():
            entries.append((int(match.group(1)), path))
    if not entries:
        raise FileNotFoundError(f"Migration bulunamadı: {migrations_dir}")
    entries.sort(key=lambda item: (item[0], item[1].name))

    seen: dict[int, str] = {}
    migrations = []
    for number, path in entries:
        if number in seen:
            raise ValueError(
                f"Migration numarası çakışıyor: {seen[number]} ve {path.name} "
                f"(aynı {number:03d} öneki)")
        seen[number] = path.name
        # Universal newline + utf-8: init_db ve koşucu eskiden de böyle okuyordu;
        # sha'nın iki yolda aynı çıkması ve eski marker ile karşılaştırılabilmesi için şart.
        sql = path.read_text(encoding="utf-8")
        migrations.append(Migration(
            version=path.name,
            number=number,
            sql=sql,
            sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        ))
    return migrations


def plan_pending(migrations, applied: dict) -> list[Migration]:
    """Uygulanmamış dosyaları numara sırasıyla döndürür.

    ``applied`` = ``{version: sha256}`` (schema_migrations tablosundan). Uygulanmış
    bir dosyanın sha'sı değiştiyse SESSİZCE yeniden koşulmaz; açık hata verilir.
    Diskte olmayan ama kayıtlı bir dosya (silinmiş) hata değildir: koşacak bir şey yoktur.
    """
    by_version = {m.version: m for m in migrations}
    for version, recorded_sha in applied.items():
        current = by_version.get(version)
        if current is not None and current.sha256 != recorded_sha:
            raise MigrationDriftError(
                f"{version} daha önce uygulandı ama içeriği değişmiş "
                f"(kayıtlı sha256={recorded_sha[:12]}…, dosya sha256={current.sha256[:12]}…). "
                "Uygulanmış migration düzenlenmez: yeni bir numaralı dosya ekleyin "
                "(bkz. backend/migrations/README.md).")
    return [m for m in migrations if m.version not in applied]


def legacy_bootstrap_rows(migrations, marker: str) -> dict:
    """Eski tek-sha marker'ından ``{version: sha256}`` üretir.

    Marker, o zaman diskte olan dosyaların ``ilk k`` tanesinin birleşik sha'sıdır.
    Eşleşen EN BÜYÜK k seçilir: marker 001..013'e aitse 014 (sonradan eklenmişse)
    bekleyen sayılır ve koşar. Hiçbir önek eşleşmezse (uygulandıktan sonra bir
    dosya düzenlenmiş olabilir) tahmin yürütülmez; hata verilir.
    """
    for k in range(len(migrations), 0, -1):
        if aggregate_sha256(migrations[:k]) == marker:
            return {m.version: m.sha256 for m in migrations[:k]}
    raise LegacyMarkerError(
        "Eski schema_sha256 marker'ı hiçbir migration önekiyle eşleşmiyor; uygulanmış "
        "dosyalardan biri sonradan değiştirilmiş olabilir. Hangi dosyaların gerçekten "
        "uygulandığını doğrulayıp schema_migrations tablosunu elle doldurun "
        "(bkz. backend/migrations/README.md).")
