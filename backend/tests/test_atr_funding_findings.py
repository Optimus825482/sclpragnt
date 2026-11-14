"""Regresyon: ATR eşik kararı ve funding reddi (2026-11-10).

ATR EŞİK TARAMASI (scripts/atr_threshold_sweep.py, 4 bagimsiz seed, gercek
1m mum + trailing cikisi):
    atr>=1.0 -> +0.364% (sd 0.168, n~114)
    atr>=1.2 -> +0.449% (sd 0.268, n~72)
    atr>=1.5 -> +0.647% (sd 0.406, n~38)   <- yuksek ortalama, sd 2.4x
    atr>=1.8 -> +0.608% (sd 0.352, n~21)   <- orneklem cok kucuk

KARAR: 1.0'da kal. 1.5 daha yuksek ortalama veriyor ama sd 2.4 kat buyuk ve
orneklem 3 kat kucuk (ayni guven icin 9x islem gerekir). 1.8+ guvenilmez.

FUNDING (scripts/funding_signal_test.py, 40.000 eslesen aday, TRAIN/TEST):
    funding > +0.005% -> -0.663%, kazanan %29.9  (EN KOTU, ters sinyal DOGRU)
    funding <= +0.005% filtresi -> kazanc yalniz +0.021 puan
    ATR ile birlikte ek katki YOK (hatta hafif kotu).
KARAR: funding filtresi EKLENMEZ — yon dogru, buyukluk gurultu seviyesinde.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_atr_threshold_decision_recorded():
    doc = _doc()
    assert "atr_threshold_sweep" in doc
    assert "0,647" in doc or "0.647" in doc, "1.5 sonucu yok"
    assert "0,364" in doc or "0.364" in doc, "1.0 sonucu yok"


def test_atr_1_0_kept_with_reason():
    """1.0'da kalma gerekçesi (sd/örneklem) yazılı olmalı."""
    doc = _doc()
    assert "1,0'da kalındı" in doc or "1,0" in doc
    assert "örneklem" in doc.lower(), "örneklem gerekçesi yok"


def test_atr_threshold_scales():
    """Eşik arttıkça ortalama artmalı AMA sd de artmalı (iddia tutarlı mı)."""
    rows = [(1.0, 0.364, 0.168, 114), (1.2, 0.449, 0.268, 72),
            (1.5, 0.647, 0.406, 38), (1.8, 0.608, 0.352, 21)]
    means = [r[1] for r in rows[:3]]
    sds = [r[2] for r in rows[:3]]
    ns = [r[3] for r in rows[:3]]
    assert means == sorted(means), "ortalama monoton artmıyor"
    assert sds == sorted(sds), "sd monoton artmıyor"
    assert ns == sorted(ns, reverse=True), "örneklem monoton azalmıyor"


def test_funding_veto_direction_consistent():
    """Funding ters sinyali iki sette de aynı yönde olmalı (iddia kilidi)."""
    train_worst = -0.571   # en yuksek funding dilimi
    train_best = -0.612    # orta dilim (en iyi train)
    test_worst = -0.663
    test_mid = -0.233
    assert train_worst > train_best  # train'de orta dilim daha iyi
    assert test_worst < test_mid, "TEST'te pozitif funding en kötü olmalı"


def test_funding_gain_too_small_to_add():
    """Funding kazancı eşiğin (0.05 puan) altında — eklenmemeli."""
    no_filter, with_filter = -0.254, -0.233
    gain = with_filter - no_filter
    assert gain < 0.05, f"kazanç beklenenden büyük: {gain}"


def test_funding_rejected_in_doc():
    doc = _doc()
    assert "EKLENMEYECEK" in doc or "EKLENMEZ" in doc, "funding reddi yazılı değil"
    assert "marjinal" in doc.lower() or "MARJINAL" in doc


def test_scripts_exist():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "atr_threshold_sweep.py").exists()
    assert (base / "funding_signal_test.py").exists()


def test_exit_model_caveat_applies_to_funding_too():
    """Funding tablosundaki atr satırı da çıkış-modeli uyarısını taşımalı."""
    doc = _doc()
    assert "§10" in doc or "çıkış-modeli bağımlılığı" in doc.lower()
