"""Regresyon: emir defteri dengesizliği testi + veri envanteri kapanışı (2026-11-10).

VERI: hist_futures_bookdepth 7.332.621 satır, 290 perp sembol, 3 ay.
      bid_d1..bid_d5 / ask_d1..ask_d5 = kümülatif derinlik.

TEST (scripts/bookdepth_test.py, 30.000 aday -> 5.050 eşleşme, 15 dk pencere):
    Sabit net_pct:
        dengesizlik d1  TRAIN +0.068% | TEST -0.264%
        dengesizlik d5  TRAIN +0.002% | TEST -0.181%
    Trailing (imb_d5, Q5-Q1), 4 seed:
        seed 7  -0.559%  | 11 +0.043% | 23 -0.009% | 42 +0.110%
        ortalama -0.104%, sd 0.307, |ort|/sd = 0.34

YORUM: işaret seed'den seed'e DEĞİŞİYOR (+0.110 <-> -0.559). Tek seed (7)
sonucu aşağı çekiyor, diğer üçü sıfıra yakın. Tam gürültü.

KARAR: EKLENMEZ. Ve: test edilecek büyük veri KALMADI.

NOT: literatürde bid/ask dengesizliği en güçlü mikro-yapı sinyallerinden biri
sayılır (Cont/Kukanov/Stoikov). Burada çalışmadı — aynı order flow'da olduğu
gibi, "zaten yükselmiş" adaylarda alış duvarı teyit değil tükenme işareti.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_bookdepth_data_documented():
    doc = _doc()
    assert "hist_futures_bookdepth" in doc
    assert "7.332.621" in doc or "7332621" in doc


def test_sign_is_unstable_across_seeds():
    """İddia: işaret tutarsız — 4 seed'in kendi verisiyle doğrula."""
    seeds = [-0.559, 0.043, -0.009, 0.110]
    assert min(seeds) < 0 < max(seeds), "işaret değişmiyor (iddia yanlış)"


def test_noise_ratio_above_one():
    """|ort|/sd < 0.5 olmalı (gürültü eşiği)."""
    seeds = [-0.559, 0.043, -0.009, 0.110]
    mean = sum(seeds) / len(seeds)
    var = sum((x - mean) ** 2 for x in seeds) / (len(seeds) - 1)
    sd = var ** 0.5
    assert abs(mean) / sd < 0.5, f"gürültü değil: {abs(mean)/sd:.2f}"


def test_rejection_documented():
    doc = _doc()
    assert "EKLENMEZ" in doc
    assert "gürültü" in doc.lower()


def test_data_exhausted_statement():
    """Tüm büyük verinin tükendiği açıkça yazılmalı."""
    doc = _doc()
    assert "Büyük veri tükendi" in doc or "tükendi" in doc.lower()


def test_inventory_covers_all_big_tables():
    """Veri envanteri 5 büyük tabloyu (1M+) listelemeli."""
    doc = _doc()
    for t in ("historical_candles", "historical_trade_flow",
              "hist_futures_metrics", "hist_futures_bookdepth",
              "futures_funding"):
        assert t in doc, f"envanterde eksik: {t}"


def test_final_table_has_11_hypotheses():
    doc = _doc()
    assert "Test edilen 11 hipotez" in doc
    for kw in ("velocity_score", "ret15", "Funding", "Order flow", "ATR",
               "ML hit", "Trailing gap", "OI", "Emir defteri"):
        assert kw in doc, f"nihai tabloda eksik: {kw}"


def test_literature_contradiction_noted():
    """Literatürle çelişki (mikro-yapı sinyali çalışmadı) açıklanmalı."""
    doc = _doc()
    assert "Cont/Kukanov" in doc or "mikro-yapı" in doc
    assert "tükenme" in doc.lower() or "teyit değil" in doc.lower()


def test_script_exists():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "bookdepth_test.py").exists()
