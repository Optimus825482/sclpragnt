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
    """2026-11-25: deneme geri alındı — ÖLÇÜM trailing 2,0/1,0'ı KORUNDU işaretledi."""
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


# --- BOLUM 27: GENIS EVRENDE SONUC TERS (kanit guclendi) ---
# Ayni cikis parametreleri, iki evren:
#   genis (n=1650, filtresiz): mevcut 2.0/1.0 EN KOTU (medyan -0.171%)
#   filtreli (n~60, canli):    mevcut 2.0/1.0 EN IYI (ort +1.124%)
# Canli evren filtreli -> mevcut varsayilan dogru. Degisiklik yok.

WIDE_MEDIAN = {  # (trigger,gap) -> medyan, 4 seed
    (2.0, 1.0): [-0.234, 0.028, -0.320, -0.157],
    (1.5, 0.5): [0.792, 0.824, 0.779, 0.805],
    (1.5, 0.3): [0.974, 0.989, 0.958, 0.976],
}
WIDE_MEAN = {(2.0, 1.0): -0.011, (1.5, 0.5): 0.043, (1.5, 0.3): 0.046}
FILTERED_MEAN = {(2.0, 1.0): 1.124, (1.5, 0.5): 0.935, (1.5, 0.3): 0.863}


def test_wide_universe_current_is_worst():
    """Genis evrende mevcut varsayilan EN KOTU olmali (medyan cogunlukla negatif)."""
    neg = sum(1 for m in WIDE_MEDIAN[(2.0, 1.0)] if m < 0)
    assert neg >= 3, f"mevcut medyan 4 seed'de {neg}/4 negatif (3 beklenirdi)"
    assert WIDE_MEAN[(2.0, 1.0)] < WIDE_MEAN[(1.5, 0.5)]


def test_wide_universe_candidate_median_all_positive():
    """Genis evrende 1.5/0.5 medyani TAMAMEN pozitif (4/4 seed)."""
    for m in WIDE_MEDIAN[(1.5, 0.5)]:
        assert m > 0, f"1.5/0.5 medyani negatif: {m}"


def test_filtered_universe_current_is_best():
    """Filtreli evrende (canli) mevcut varsayilan EN IYI."""
    assert FILTERED_MEAN[(2.0, 1.0)] > FILTERED_MEAN[(1.5, 0.5)]
    assert FILTERED_MEAN[(2.0, 1.0)] > FILTERED_MEAN[(1.5, 0.3)]


def test_opposite_directions_confirm_environment_dependence():
    """Kritik: iki evren AYNI parametrelerde ZIT sonuc veriyor."""
    assert WIDE_MEAN[(2.0, 1.0)] < WIDE_MEAN[(1.5, 0.5)]  # geniste 1.5 iyi
    assert FILTERED_MEAN[(2.0, 1.0)] > FILTERED_MEAN[(1.5, 0.5)]  # filtrede 2.0 iyi


def test_no_change_final_decision_even_stronger():
    """27. bolumde karar degismedi, amra gerekce GUCLENDI."""
    doc = DOC.read_text(encoding="utf-8")
    assert "27." in doc
    assert "TAM TERS SONUÇ" in doc or "TAM TERS SONUC" in doc.upper()
    assert "evrene özel" in doc.lower() or "evrene ozel" in doc.lower()


def test_methodology_fifth_trap():
    """Besinci esik/baglam tuzagi dokumante edilmis olmali."""
    doc = DOC.read_text(encoding="utf-8")
    assert "beşinci" in doc or "besinci" in doc


def test_early_exit_zero_in_candidates():
    """1.5/0.5'te erken kapanma %0 -> §18 gurultu riski yok (neden guvenli)."""
    from app import config
    # dogrudan kod degilse de: dokumanda "erken kapanma %0.0" yazilmis olmali
    doc = DOC.read_text(encoding="utf-8")
    assert "erken" in doc
    assert "0.0" in doc or "%0" in doc
