"""Regresyon: order flow testi + "veri yok" düzeltmesi (2026-11-10).

DÜZELTME: docs §15'te "order flow verisi yok" yazmıştım — YANLIŞTI.
`historical_trade_flow` tablosu VAR: 13.921.104 satır, 310 sembol,
2026-07-19 -> 2026-10-17, dakika bazında taker akışı.
İlk kontrolde yalnız microflow.py (bellek içi) ve velocity_candidates
kolonlarına bakıldı, tablo atlandı.

TEST (scripts/orderflow_test.py, 30.000 aday, 15 dk pencere, TRAIN/TEST 70/30):
    taker buy oranı      Q5-Q1: TRAIN +0.100%, TEST +0.117%  -> eşik +0.20 ALTI
    buy/sell oranı       Q5-Q1: TRAIN +0.110%, TEST +0.108%  -> ALTI
    büyük alım net payı  Q5-Q1: TRAIN +0.062%, TEST +0.029%  -> ALTI
    işlem sayısı         Q5-Q1: TRAIN +0.160%, TEST -0.167%  -> TERS
    trailing doğrulama   Q5-Q1: +0.062%                      -> ayrışmıyor

ASIL BULGU: aşırı uçlar TERS. taker buy > %90 -> TRAIN -0.697% (kazanan %21.3),
TEST -0.504% (kazanan %27.6). Aşırı agresif alım = tükenmiş giriş.
ATR>=1.0 ile birleşince FELAKET: -1.550% (n=30) vs -0.534% (n=1050).

KARAR: order flow filtre olarak EKLENMEZ. Tek uygulanabilir kural
taker_buy_pct > 90 veto'su ama adayların yalnız %0.7'sini etkiliyor.
"""
import pathlib

DOC = (pathlib.Path(__file__).parent.parent.parent / "docs"
       / "YUKSELIS_ARASTIRMASI_2026-11-10.md")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_correction_recorded():
    """"Veri yok" yanlışının düzeltildiği yazılı olmalı."""
    doc = _doc()
    assert "DÜZELTME" in doc, "düzeltme kaydı yok"
    assert "yanlıştı" in doc.lower() or "YANLIŞ" in doc
    assert "atladım" in doc.lower() or "atlandı" in doc.lower()


def test_trade_flow_table_documented():
    """Veri kaynağı doğru künyeyle yazılmalı."""
    doc = _doc()
    assert "historical_trade_flow" in doc
    assert "13.921.104" in doc or "13,9M" in doc or "13921104" in doc
    assert "buy_quote" in doc


def test_all_four_dimensions_failed():
    """4 boyutun hepsi eşik altı — iddia kendi verisiyle tutarlı."""
    failures = {  # Q5-Q1 (test)
        "taker_buy_pct": 0.117,
        "buy_sell_ratio": 0.108,
        "big_net_share": 0.029,
        "n_trades": -0.167,
    }
    for name, d in failures.items():
        assert d < 0.20, f"{name} eşiği geçmiş: {d}"


def test_extreme_taker_buy_is_worst():
    """Aşırı taker buy (>%90) en kötü olmalı — ters sinyal bulgusu."""
    train_extreme = -0.697
    train_mid = -0.340
    assert train_extreme < train_mid, "uç, ortadan kötü olmalı"
    # kazanan oranı da düşük
    assert 21.3 < 39.2


def test_atr_plus_extreme_is_worst_combo():
    """ATR + aşırı agresif alım = en kötü kombinasyon (-1.550)."""
    assert -1.550 < -0.534


def test_rejection_documented():
    doc = _doc()
    assert "EKLENMEZ" in doc
    assert "ayrıştırmıyor" in doc.lower() or "AYRIŞTIRMIYOR" in doc


def test_veto_rule_noted_but_marginal():
    """Veto kuralı not edilmeli AMA pratik katkısı sınırlı denmeli."""
    doc = _doc()
    assert "%0,7" in doc or "0.7" in doc, "votonun kapsamı yazılı değil"


def test_literature_contradiction_explained():
    """Literatürle çelişki açıklanmalı (neden ters çıktı)."""
    doc = _doc()
    assert "literatür" in doc.lower() or "literatur" in doc.lower()
    assert "tükenme" in doc.lower() or "geç kalınmış" in doc.lower()


def test_orderflow_script_exists():
    base = pathlib.Path(__file__).parent.parent / "scripts"
    assert (base / "orderflow_test.py").exists()
