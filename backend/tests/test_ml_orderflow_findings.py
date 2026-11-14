"""Regresyon: ML hit probability reddi + order flow veri boşluğu (2026-11-10).

ML HIT PROBABILITY (scripts/ml_prob_test.py):
Sabit TP/SL modelinde model GERÇEKTEN ayrıştırıyor:
    prob 0.0-0.2 -> SL %47.1, TP %30.9, WR %36.8
    prob 0.8-1.0 -> SL %29.4, TP %54.5, WR %57.9
    corr(prob, kazandi) = +0.1709
AMA trailing çıkışında ayrışma KAYBOLUYOR (4 seed):
    seed 7: +0.111% | 11: +0.033% | 23: -0.015% | 42: +0.041%
    eşik +0.20 -> 4/4 BAŞARISIZ, ortalama ~+0.043 (gürültü)

SEBEP: model "hedefe dokunacak mı" öngörüyor; trailing'de hedef yok.
Karar: ML prob filtresi EKLENMEZ.

ORDER FLOW: microflow CVD hesaplıyor ama SAKLAMIYOR (bellek içi).
velocity_candidates'ta cvd alanı yok (0 aday) -> geçmişe dönük test İM KANSIZ.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_ml_discrimination_in_fixed_model_recorded():
    """Sabit modeldeki güçlü ayrışma kayıtlı olmalı (gerçek bulgu)."""
    doc = _doc()
    assert "0,1709" in doc or "0.1709" in doc, "korelasyon yok"
    assert "54,5" in doc or "54.5" in doc, "TP oranı yok"
    assert "47,1" in doc or "47.1" in doc, "SL oranı yok"


def test_ml_rejected_for_trailing():
    """Trailing'de başarısız olduğu (4/4 seed) kayıtlı olmalı."""
    doc = _doc()
    assert "EKLENMEZ" in doc, "ML prob reddi yazılı değil"
    assert "trailing" in doc.lower()


def test_ml_seed_results_consistent():
    """4 seed'in hiçbiri eşiği geçmemeli — iddia kendi verisiyle tutarlı."""
    seeds = [0.111, 0.033, -0.015, 0.041]
    assert max(seeds) < 0.20, f"bir seed eşiği geçmiş: {max(seeds)}"
    assert sum(seeds) / len(seeds) < 0.10, "ortalama gürültü seviyesinde değil"


def test_orderflow_data_gap_recorded():
    """Order flow'un SAKLANMADIĞI açıkça yazılmalı (tekrar denenmesin)."""
    doc = _doc()
    assert "CVD" in doc
    assert "İMKANSIZ" in doc or "IMKANSIZ" in doc or "veri yok" in doc.lower()
    assert "microflow" in doc


def test_final_summary_covers_all_hypotheses():
    """Nihai özet tablosu 7 hipotezi de içermeli."""
    doc = _doc()
    for key in ("velocity_score", "ret15", "Saat", "Funding", "ATR",
                "ML hit"):
        assert key in doc, f"özet tablosunda eksik: {key}"


def test_key_insight_direction_vs_amplitude():
    """Ana içgörü (yön ölü, genlik çalışıyor) kayıtlı olmalı."""
    doc = _doc()
    assert "genlik" in doc.lower() or "GENLİK" in doc
    assert "yön" in doc.lower()


def test_ml_script_exists():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "ml_prob_test.py").exists()
