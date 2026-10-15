"""Deney kaydı (docs/DENEY_KAYDI.md) disiplin testleri.

Her eşik/flag değişikliği canlıya çıkmadan önce kayıt tablosuna bir satır
gerektirir. Bu test iki şeyi kilitler: tablo başlığı beklenen 8 sütuna sahip
ve listelenen flag'lerin her biri kayıtta geçiyor.
"""
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
DENEY_KAYDI = DOCS_DIR / "DENEY_KAYDI.md"

EXPECTED_HEADER = [
    "Tarih",
    "Değişiklik (flag/eşik)",
    "Eski → Yeni",
    "Hipotez",
    "Ölçüm komutu",
    "Sonuç (n, isabet, EV)",
    "Karar",
    "Commit",
]

FLAGS = [
    "RADAR_NOTIFY_SYMBOL_COOLDOWN_MIN",
    "RADAR_NOTIFY_DAILY_CAP_PER_SYMBOL",
    "RADAR_NOTIFY_LEADLAG_PRIORITY",
    "RADAR_TARGET_CALIBRATION_ENABLED",
    "AUTO_PAPER_TIME_STOP_MIN",
]


def _table_header_cells():
    """Dosyadaki ilk tablo başlığının hücrelerini döndürür (yoksa None)."""
    lines = DENEY_KAYDI.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == "Tarih":
            return cells
    return None


def test_deney_kaydi_exists():
    assert DENEY_KAYDI.is_file(), f"Bulunamadı: {DENEY_KAYDI}"


def test_table_header_has_eight_expected_columns():
    header = _table_header_cells()
    assert header is not None, "Deney tablosu başlığı (Tarih | ...) bulunamadı"
    assert len(header) == 8, f"8 sütun bekleniyordu, {len(header)} bulundu: {header}"
    assert header == EXPECTED_HEADER


def test_every_flag_is_logged():
    text = DENEY_KAYDI.read_text(encoding="utf-8")
    missing = [flag for flag in FLAGS if flag not in text]
    assert not missing, f"Kayıtta eksik flag'ler: {missing}"
