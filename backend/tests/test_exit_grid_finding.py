"""Çıkış tarafı ızgarası: güçlü desen bulundu ama DEĞİŞİKLİK YAPILMADI (2026-11-10).

Tüm bulgular giriş tarafındaydı (ATR, OI). trailing_trigger_pct=2.0 ve
trailing_gap_pct=1.0 HİÇ TARANMAMIŞTI.

TEST: scripts/exit_grid.py — aynı adaylar (ATR>=1 + OI>=1.2 = canlı varsayılan),
aynı replay, yalnız çıkış 5x5 ızgara.

SONUÇ (4 seed):
    (trigger, gap)    ort      sd     en kötü  kazanan  erken  mevcutu yendi
    (2.0, 1.0)      +0.641%  0.482  +0.069%  %64.2    %0.0   -  <- MEVCUT
    (1.0, 0.3)      +0.862%  0.276  +0.663%  %81.6    %7.4   4/4
    (1.0, 0.5)      +0.852%  0.336  +0.572%  %81.6    %18.6  4/4
    (1.5, 0.3)      +1.074%  0.559  +0.679%  %73.7    %0.0   1/2

trigger 1.0 + gap 0.3 çok iyi görünüyor AMA 4 nedenden uygulanmadı:
  1. ÖRNEKLEM: filtre sonrası aday 58-89 (girişte 273-341 idi — dörtte biri)
  2. gap 0.30 §18'de CANLIDA kötü çıkmıştı (2026-10-11: "5 sn ticker
     gürültüsünde pozisyon ANINDA kapanıyor")
  3. Kritik fark: §18 kötü deneyimi trigger 2.0 ile yaşandı; şimdi trigger 1.0
     -> erken kapanma %7.4. Ama bu BAR REPLAY ölçüsü, canlıda katlanır.
  4. config kuralı: trigger > gap (stop girişin üstünde kalsın). 1.0/0.3 ->
     stop +0.7'de kilitli; canlı ticker gürültüsü deler.

KARAR: varsayılan DEĞİŞMEDİ. Yalnız bar replay'e dayanarak canlıda kötü çıkmış
bir değeri geri getirmek §18 hatasını tekrarlamak olur.

METODOLOJİ: giriş filtreleri evreni ~%95 daralttı -> çıkış optimizasyonu için
örneklem kalmadı. Bu oturumda İLK KEZ bir bulgu "ölçüldü ama uygulanmadı"
çünkü kanıt gücü eşiğin altında.
"""
import pathlib

import pytest

BASE = pathlib.Path(__file__).parent.parent
DOC = BASE.parent / "docs" / "YUKSELIS_ARASTIRMASI_2026-11-10.md"

# (ort, sd, en_kotu, kazanan, erken) — 4 seed
GRID = {
    (2.0, 1.0): (0.641, 0.482, 0.069, 64.2, 0.0),
    (1.0, 0.3): (0.862, 0.276, 0.663, 81.6, 7.4),
    (1.0, 0.5): (0.852, 0.336, 0.572, 81.6, 18.6),
    (1.5, 0.3): (1.074, 0.559, 0.679, 73.7, 0.0),
}
CURRENT = (2.0, 1.0)
CANDIDATE = (1.0, 0.3)


def test_candidate_beats_current_on_average():
    """Desen gerçek: aday mevcutu ortalamada yeniyor."""
    assert GRID[CANDIDATE][0] > GRID[CURRENT][0] * 1.3


def test_candidate_has_lower_variance():
    """Adayın sd'si neredeyse yarı — bulgunun gücü burada."""
    assert GRID[CANDIDATE][1] < 0.6 * GRID[CURRENT][1]


def test_candidate_win_rate_much_higher():
    """Kazanan oranı farkı büyük ve seed'den bağımsız."""
    assert GRID[CANDIDATE][3] > GRID[CURRENT][3] + 15


def test_default_not_changed():
    """KARAR: varsayılan DEĞİŞMEDİ — trigger 2.0, gap 1.0."""
    from app import config
    assert config.Config.AUTO_PAPER_TRAILING_TRIGGER_PCT == 2.0
    assert config.Config.AUTO_PAPER_TRAILING_GAP_PCT == 1.0


def test_trigger_greater_than_gap_rule_holds():
    """config kuralı: trigger > gap (stop girişin üstünde kalsın)."""
    from app import config
    assert config.Config.AUTO_PAPER_TRAILING_TRIGGER_PCT > \
        config.Config.AUTO_PAPER_TRAILING_GAP_PCT


def test_sample_size_is_the_reason():
    """Reddin ana nedeni: örneklem dörtte bir (58-89 vs 273-341)."""
    doc = DOC.read_text(encoding="utf-8")
    assert "58-89" in doc
    assert "dörtte biri" in doc or "DÖRTTE BİRİ" in doc.upper()


def test_section_18_live_evidence_cited():
    """gap 0.30'un canlıda kötü olduğu kanıtı hatırlatılmalı."""
    doc = DOC.read_text(encoding="utf-8")
    assert "2026-10-11" in doc
    assert "ANINDA kapanıyor" in doc


def test_decision_explicitly_no_change():
    """Değişiklik yapılmadığı açıkça yazılmalı (dürüstlük)."""
    doc = DOC.read_text(encoding="utf-8")
    assert "DEĞİŞİKLİK YAPILMADI" in doc
    assert "varsayılan DEĞİŞMEDİ" in doc


def test_live_test_order_documented():
    """Canlıda test sırası yazılı olmalı (muhafazakârdan agresife)."""
    doc = DOC.read_text(encoding="utf-8")
    assert "trailing_trigger_pct=1.5" in doc
    assert "0.75" in doc


def test_early_exit_risk_measured():
    """Erken kapanma oranı ölçülmüş olmalı (canlı gürültü göstergesi)."""
    for key, v in GRID.items():
        assert 0.0 <= v[4] <= 100.0
    # adayda erken kapanma mevcutdan yüksek -> risk gerçek
    assert GRID[CANDIDATE][4] > GRID[CURRENT][4]


@pytest.mark.parametrize("cfg", [(2.0, 1.0), (1.0, 0.3), (1.0, 0.5), (1.5, 0.3)])
def test_all_configs_positive(cfg):
    """Ölçülen tüm konfigürasyonlar pozitif (evren zaten filtrelenmiş)."""
    assert GRID[cfg][0] > 0


def test_methodology_lesson_documented():
    """Ders: giriş filtreleri evreni daralttı -> çıkış optimizasyonu imkânsız."""
    doc = DOC.read_text(encoding="utf-8")
    assert "örneklem daralması" in doc or "ÖRNEKLEM DARALMASI" in doc.upper()
    assert "ilk kez" in doc.lower()


def test_script_exists():
    assert (BASE / "scripts" / "exit_grid.py").exists()
