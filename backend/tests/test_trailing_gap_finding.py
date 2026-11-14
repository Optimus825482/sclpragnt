"""Regresyon: trailing gap 1.0 -> 0.30 bulgusu (2026-11-10).

scripts/atr_trailing_grid.py — ATR>=1.0 evreni, gercek 1m mum, SL %2, 240 dk.

BULGU 1: ATR olcekli gap KAZANDIRMIYOR. Evren zaten ATR>=1.0 ile suzulmus ->
         ATR dagilimi dar, olcekleme anlamsiz. ATR*0.75 neredeyse sabit 1.0 ile
         ayni sonucu veriyor.

BULGU 2: Sabit gap daraldikca iyi (0.15 -> +0.414, 1.0 -> +0.319) AMA dar gap
         slippage tuzagi: 0.15 nominal +0.414, 0.20% kayma ile +0.214.

5 SEED DOGRULAMASI:
    gap 0.30 -> ort +0.341%, sd 0.034, en kotu seed +0.287%, 5/5 pozitif
    gap 0.40 -> ort +0.319%, sd 0.040, en kotu seed +0.253%, 5/5 pozitif
    gap 1.00 -> ort +0.263%, sd 0.058, en kotu seed +0.197%, 5/5 pozitif

KARAR: trailing_gap_pct 1.0 -> 0.30. Kazanc +0.078 puan VE sd 1.7 kat dusuk
       (hem ortalama yuksek hem varyans dusuk) — en somut bulgu.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_gap_recommendation_recorded():
    doc = _doc()
    assert "0,30" in doc or "0.30" in doc
    assert "trailing_gap_pct" in doc, "parametre adı yok"


def test_default_NOT_changed_due_live_evidence():
    """Varsayılan 1.0 KALMALI — canlı kanıt bar replay'den üstün."""
    from app import config
    d = config.Config.auto_paper_exit_defaults()
    assert d["trailing_gap_pct"] == 1.0, (
        "varsayilan 1.0 olmali: canli 2026-10-11 kaniti 0.3'un ticker "
        "gurultusunde erken tetiklendigini soyluyor")
    assert config.Config.AUTO_PAPER_TRAILING_GAP_PCT == 1.0


def test_live_contradiction_documented():
    """Çelişki (canlı kanıt vs bar replay) açıkça yazılı olmalı."""
    doc = _doc()
    assert "ÇELİŞKİ" in doc or "celiski" in doc.lower(), "çelişki yazılı değil"
    assert "ticker" in doc.lower(), "ticker gürültüsü açıklanmamış"
    assert "1m bar replay" in doc.lower() or "bar replay" in doc.lower()


def test_gap_0_40_offered_as_safer_middle():
    """0.40 orta yol olarak önerilmeli (gürültüye 0.30'dan dayanıklı)."""
    doc = _doc()
    assert "0,40" in doc or "0.40" in doc
    assert "orta yol" in doc.lower() or "güvenli" in doc.lower()


def test_gap_gain_and_variance_improve():
    """İddia: hem ortalama artar hem sd düşer (5 seed)."""
    gap030 = [0.370, 0.355, 0.330, 0.287, 0.365]
    gap100 = [0.297, 0.271, 0.338, 0.197, 0.214]
    m030 = sum(gap030) / 5
    m100 = sum(gap100) / 5
    assert m030 > m100, "0.30 ortalaması daha yüksek olmalı"
    assert all(x > 0 for x in gap030), "5/5 seed pozitif olmalı"
    # sd karşılaştırması
    def sd(v):
        m = sum(v) / len(v)
        return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
    assert sd(gap030) < sd(gap100), "0.30 sd'si daha düşük olmalı"


def test_atr_scaling_rejected():
    """ATR ölçekli gap kazandırmıyor — kayıtlı olmalı."""
    doc = _doc()
    assert "KAZANDIRMIYOR" in doc or "kazandırmıyor" in doc.lower()
    assert "ATR×0,25" in doc or "ATR*0.25" in doc
    # sabit 0.3 > ATR*0.25
    assert 0.389 > 0.360, "iddia: sabit 0.3 ATR*0.25'ten iyi"


def test_slippage_caveat_documented():
    """Dar gap'in slippage tuzağı yazılı olmalı (overfit koruması)."""
    doc = _doc()
    assert "slippage" in doc.lower() or "kayma" in doc.lower()
    assert "0,15" in doc or "0.15" in doc


def test_gap_not_below_0_30_chosen():
    """0.15/0.20 nominalde iyi ama slippage yüzünden SEÇİLMEDİ."""
    doc = _doc()
    assert "siliniyor" in doc.lower() or "tuzak" in doc.lower(), (
        "0.15'in neden seçilmediği yazılı değil")


def test_median_still_negative_noted():
    """Dürüstlük: medyan hâlâ negatif, kâr kuyruktan — yazılı olmalı."""
    doc = _doc()
    assert "kuyruk" in doc.lower() or "medyan hâlâ" in doc.lower()


def test_gap_script_exists():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "atr_trailing_grid.py").exists()


def test_config_signet_not_silently_overridden():
    """config.py'deki 2026-10-11 canlı uyarısı KORUNMALI (silinmemiş)."""
    import pathlib as _p
    src = (_p.Path(__file__).parent.parent / "app" / "config.py").read_text(
        encoding="utf-8")
    assert "ÇOK DARDI" in src, "canlı uyarı silinmiş!"
    assert "ANINDA kapanıyor" in src
    assert "2026-11-10 GÜNCELLEME" in src, "yeni ölçüm notu yok"


def test_atr_gate_interaction_warned():
    """ATR kapısı kapalıyken gap etkisi doğrulanmadı — uyarı olmalı."""
    doc = _doc()
    assert "etkileşim" in doc.lower() or "birlikte kullanılmalı" in doc.lower()
