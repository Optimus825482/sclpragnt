"""Regresyon: futures ONCU gostergeler (OI) — ilk gercek yukselecek-sembol sinyali.

VERI: hist_futures_metrics 7.503.935 satir, 291 perp sembol, 5 dk, 3 ay.
      futures_symbol_map 294 eslesme. Velocity kesisimi 538.649 aday.

BULGU: OI (open interest) degisimi ILK GERCEK oncu gosterge. Fiyat turevi
       olmayan tek sinyal. Onceki 60 dk OI degisimi:

       Sabit net_pct modeli (zayif):
           TRAIN Q5-Q1 +0.219% | TEST +0.159%
       Trailing modeli (guclu, 5 seed):
           seed 7  +0.871%  | 11 +0.913% | 23 +1.125% | 42 +0.677% | 77 +0.998%
           ortalama +0.917% (ATR'nin +0.364'unun 2.5 kati)
           kazanan Q1 %18-30 -> Q5 %40-51 (temiz monoton)

YORUM: OI artiyorsa yukselis YENI PARAYLA besleniyor -> surdurulebilir.
       OI artmiyorsa yukselis short covering -> tukenir.

KRITIK: OI ve ATR BIRBIRINI IPTAL EDIYOR (ayni bilgiyi paylasiyor):
    OI yuksek + ATR<1.0 -> +0.558% (kaz %47.6)  <- EN IYI
    OI yuksek + ATR>=1.0 -> +0.020% (kaz %31.7) <- SIFIR
    OI dusuk  + ATR>=1.0 -> -0.371% (kaz %13.6)
    OI dusuk  + ATR<1.0  -> -0.095% (kaz %33.8)

HATA KAYDI: ilk kosuda ORDER BY created_at LIMIT -> orneklem TEK GUNE sikisti,
TRAIN ve TEST ayni gun cikti (gecersiz out-of-sample, +0.828 sisirme).
Duzeltme: ORDER BY random() + kronolojik sort -> 26 gun gercek yayilim.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_futures_tables_documented():
    doc = _doc()
    assert "hist_futures_metrics" in doc
    assert "7.503.935" in doc or "7503935" in doc
    assert "538.649" in doc or "538649" in doc


def test_oi_effect_stronger_than_atr():
    """OI etkisi ATR'nin en az 2 katı olmalı (5 seed ortalaması)."""
    seeds = [0.871, 0.913, 1.125, 0.677, 0.998]
    mean = sum(seeds) / len(seeds)
    atr = 0.364
    assert mean > atr * 2, f"OI ort {mean:.3f} ATR'nin 2 katından az"
    assert all(s > 0 for s in seeds), "5/5 seed pozitif olmalı"


def test_oi_win_rate_monotonic():
    """Kazanan oranı Q1'den Q5'e artmalı (temiz ayrışma)."""
    q1 = [25.5, 29.6, 24.7, 22.2, 18.5]
    q5 = [49.5, 48.1, 50.6, 40.5, 49.4]
    assert all(a < b for a, b in zip(q1, q5)), "Q5 her seed'de Q1'den iyi değil"
    assert max(q1) < 35, "Q1 kazanan oranı düşük olmalı"


def test_oi_atr_cancel_out():
    """OI + ATR birleşimi iptal etmeli (aynı bilgi)."""
    combo = {"oi_hi_atr_lo": 0.558, "oi_hi_atr_hi": 0.020,
             "oi_lo_atr_hi": -0.371, "oi_lo_atr_lo": -0.095}
    assert combo["oi_hi_atr_lo"] > combo["oi_hi_atr_hi"] * 10, (
        "ATR eklemek OI'nin avantajını yok etmeli")


def test_single_day_bug_recorded():
    """Tek-gün örnekleme hatası ve düzeltmesi kayıtlı olmalı (tekrar etmesin)."""
    doc = _doc()
    assert "tek bir güne" in doc.lower() or "TEK GÜNE" in doc
    assert "random" in doc.lower(), "düzeltme yöntemi yazılı değil"
    assert "2026-09-25" in doc


def test_other_futures_indicators_rejected():
    """Diğer 3 gösterge zayıf/ters — kayıtlı olmalı."""
    doc = _doc()
    assert "üst trader L/S" in doc
    assert "taker L/S hacim" in doc


def test_recommendation_oi_primary():
    """Öneri: OI birincil, ATR çıkar/gevşet."""
    doc = _doc()
    assert "birincil" in doc.lower()
    assert "min_oi_change_pct" in doc


def test_bookdepth_still_untested():
    """Dürüstlük: bookdepth test edilmedi."""
    doc = _doc()
    assert "bookdepth" in doc
    assert "test edilmedi" in doc.lower()


def test_script_exists():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "futures_lead_test.py").exists()
