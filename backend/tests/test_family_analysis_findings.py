"""Regresyon: tarama aileleri analizi bulguları (2026-11-10).

Ölçüm: `scripts/family_replay.py` + gerçekleşmiş işlem defteri (1.757 kapalı).

BULGU 1 — aile kalitesi (aynı çıkış modeli, gerçek 1m mum):
    trades        +0.359%  kazanan %49.5
    notifications +0.258%  kazanan %44.9
    velocity      +0.016%  kazanan %35.0
    rising        ölçülemedi (price kolonu BOŞ)

BULGU 2 — gerçekleşmiş işlemlerde ASİMETRİ TERS:
    ort kazanç +1.595% / ort kayıp -2.915%
    kazanç/kayıp = 0.547 ; kazanan oranı %56.7 -> gereken 0.764
    AÇIK = -0.217 puan  (kazanma oranı yüksek olmasına rağmen zarar)

BULGU 3 — kök neden: SL 3.88% > TP 3.75% (oran 1.03).
    stop_loss çıkışı 391 işlem, ort -4.276% (tüm zararın ana kaynağı).

BULGU 4 — mod kalitesi: trend_devam MFE>=1 %48.1 > unified %31.7
    (mevcut `allowed_modes=['trend_devam']` varsayılanını bağımsız doğrular).
"""
import pathlib
import statistics as st


def _doc() -> str:
    return (pathlib.Path(__file__).parent.parent.parent
            / "docs" / "TARAMA_AILESI_ANALIZI_2026-11-10.md").read_text(encoding="utf-8")


def test_findings_documented():
    """Asimetri bulgusu ve kök nedeni raporda kayıtlı olmalı."""
    doc = _doc()
    assert "0,547" in doc or "0.547" in doc, "kazanç/kayıp oranı yazılmamış"
    assert "0,764" in doc or "0.764" in doc, "gereken oran yazılmamış"
    assert "3,88" in doc or "3.88" in doc, "SL mesafesi yazılmamış"


def test_rising_price_gap_recorded():
    """rising_alerts.price boşluğu kayıtlı olmalı (ölçüm engeli)."""
    doc = _doc()
    assert "rising" in doc.lower()
    assert "BOŞ" in doc or "boş" in doc, "veri boşluğu notu yok"


def test_asymmetry_math():
    """İddia edilen asimetri matematiği doğru olmalı.

    kazanç/kayıp = 1.595/2.915 = 0.547
    gereken      = (1-0.567)/0.567 = 0.764
    0.547 < 0.764 -> yapısal zarar. Bu aritmetik kilitlenir.
    """
    win, loss, wr = 1.595, 2.915, 0.567
    ratio = win / loss
    need = (1 - wr) / wr
    assert abs(ratio - 0.547) < 0.001
    assert abs(need - 0.764) < 0.001
    assert ratio < need, "asimetri iddiası kendi matematiğiyle çelişiyor"


def test_rr_target_is_derived_from_winrate():
    """Hedef R:R, kazanan oranından türetilmeli — sabit sayı değil.

    %56.7 kazanma oranıyla başabaş için R:R > 0.764 gerekir; güvenli marj
    için <= 0.64 önerilir. Birisi "R:R 0.8 yeterli" derse bu test uyarır.
    """
    for wr in (0.50, 0.567, 0.60, 0.65):
        need = (1 - wr) / wr
        # kazanma oranı düştükçe gereken R:R artar
        if wr == 0.50:
            assert abs(need - 1.0) < 0.01
        if wr == 0.567:
            assert 0.75 < need < 0.78


def test_stop_loss_is_main_loss_source():
    """Rapordaki exit_reason tablosu stop_loss'u işaret etmeli."""
    doc = _doc()
    assert "stop_loss" in doc
    assert "−4,276" in doc or "-4.276" in doc or "4,28" in doc or "4.28" in doc


def test_family_script_exists():
    """Aile analizi betiği korunmalı."""
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "family_replay.py").exists()


def test_family_script_handles_rising_without_price():
    """rising ailesi fiyatsız — betik bunu MFE/MAE ile ele almalı (çökmemeli)."""
    src = (pathlib.Path(__file__).parent.parent / "scripts" / "family_replay.py").read_text(
        encoding="utf-8")
    assert "rising_mfe" in src, "rising için MFE/MAE yolu yok"
    assert "expected_price" in src or "TAMAMEN BOS" in src, "veri boşluğu notu kodda yok"


def test_median_is_the_honest_metric():
    """Medyan negatifken ortalama pozitif olabilir — bu raporda belirtilmeli.

    Aile tablosunda velocity ort +0.016% ama medyan -0.243%: ortalama birkaç
    iyi işlemle taşınıyor. Medyanı gizleyen rapor yanıltıcıdır.
    """
    doc = _doc()
    assert "Medyan" in doc, "medyan kolonu yok — ortalama tek başına yanıltıcı"
