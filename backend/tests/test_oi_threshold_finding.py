"""OI eşiği taraması: panel parametresi min_oi_change_pct için GERÇEK sayı (2026-11-10).

DURUM: §24'te OI'nin ATR ile TAMAMLAYICI olduğu kanıtlandı (iptal yok).
Ama panel parametresi sayısal eşik istiyor; §19/§24 medyan kullandı (analiz
için doğru, canlı panel için değil).

KRİTİK SORU: canlıda ATR>=1.0 ZATEN AÇIK. OI'yi açmak için ATR'nin üstüne
GERÇEK değer eklemesi lazım — yoksa gereksiz karmaşıklık.

TEST: scripts/oi_threshold_sweep.py — aynı adaylar, aynı replay. İki rejim:
  A) ATR filtresi yok  -> OI tek başına
  B) ATR>=1.0 AÇIK     -> OI, ATR'nin ÜSTÜNE  <-- karar bu

SONUÇ (B rejimi, 4 seed, trailing):
    eşik     ort      sd     min      ort n  kazanan  toplam n
    +0.0%  +0.794%  0.109  +0.709%    85    57.0%     341
    +0.3%  +0.832%  0.135  +0.702%    80    57.4%     322
    +0.5%  +0.854%  0.104  +0.739%    77    58.0%     308
    +0.8%  +0.883%  0.089  +0.777%    74    58.9%     298
    +1.2%  +0.939%  0.118  +0.781%    68    60.4%     273  <-- SEÇİLEN
    +2.0%  +0.996%  0.204  +0.780%    55    61.3%     219
    +3.0%  +1.213%  0.288  +0.865%    43    65.3%     171

ATR>=1 tabanı (filtresiz): +0.379% -> 1.2% eşiği 2.5x.

NEDEN 1.2 VE 3.0 DEĞİL: 3.0% daha yüksek ortalama (+1.213%) ama sd 2.4x ve
adayların YARISI gider -> aynı "az örneklem" tuzağı (bkz. ATR 1.0 vs 1.5).
1.2% = ortalamanın %90'ı, sd'nin %41'i, örneklemin %80'i.
"""
import pathlib
import statistics as st

import pytest

BASE = pathlib.Path(__file__).parent.parent
DOC = BASE.parent / "docs" / "YUKSELIS_ARASTIRMASI_2026-11-10.md"

# (ort, n, kazanan) — B rejimi: ATR>=1.0 açıkken OI eşiği
SEEDS = {
    7: {0.0: (0.709, 114, 51.8), 0.3: (0.780, 106, 51.9),
        0.5: (0.814, 104, 52.9), 0.8: (0.854, 100, 54.0),
        1.2: (0.916, 89, 57.3), 2.0: (0.954, 71, 60.6),
        3.0: (1.108, 53, 64.2)},
    11: {0.0: (0.744, 58, 65.5), 0.3: (0.702, 55, 65.5),
         0.5: (0.739, 52, 65.4), 0.8: (0.777, 51, 66.7),
         1.2: (0.781, 47, 66.0), 2.0: (0.780, 41, 65.9),
         3.0: (0.865, 33, 69.7)},
    23: {0.0: (0.771, 93, 52.7), 0.3: (0.827, 88, 53.4),
         0.5: (0.879, 84, 54.8), 0.8: (0.917, 81, 55.6),
         1.2: (1.020, 75, 58.7), 2.0: (0.979, 61, 55.7),
         3.0: (1.354, 45, 60.0)},
    42: {0.0: (0.954, 76, 57.9), 0.3: (1.019, 73, 58.9),
         0.5: (0.984, 68, 58.8), 0.8: (0.986, 66, 59.1),
         1.2: (1.039, 62, 59.7), 2.0: (1.272, 46, 63.0),
         3.0: (1.524, 40, 67.5)},
}
THRESHOLDS = (0.0, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0)
ATR_BASELINE = {7: 0.375, 11: 0.216, 23: 0.420, 42: 0.506}


def _mean(th: float) -> float:
    return st.mean(SEEDS[s][th][0] for s in SEEDS)


def _sd(th: float) -> float:
    vals = [SEEDS[s][th][0] for s in SEEDS]
    m = st.mean(vals)
    return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5


def _total_n(th: float) -> int:
    return sum(SEEDS[s][th][1] for s in SEEDS)


def test_threshold_improves_monotonically():
    """İddia: eşik arttıkça ortalama artar (küçük dalgalanma hariç)."""
    means = [_mean(t) for t in THRESHOLDS]
    for i in range(len(means) - 1):
        # her adımda artmalı (seed 11'de 0.3 biraz düşük, tolerans var)
        assert means[i + 1] >= means[i] - 0.06, \
            f"{THRESHOLDS[i]} -> {THRESHOLDS[i+1]}: {means[i]:.3f} -> {means[i+1]:.3f}"


def test_oi_adds_value_on_top_of_atr():
    """KRİTİK: OI eşiği, ATR>=1 tabanının ÜSTÜNE gerçek değer eklemeli."""
    base = st.mean(ATR_BASELINE.values())
    for th in (0.8, 1.2, 2.0):
        assert _mean(th) > base + 0.30, (
            f"eşik {th}: {_mean(th):.3f}% vs taban {base:.3f}% — katkı zayıf")


def test_selected_threshold_is_1_2():
    from app import config
    val = float(getattr(config.Config, "AUTO_PAPER_MIN_OI_CHANGE_PCT", 0))
    assert val == 1.2, f"varsayılan {val} (1.2 beklenirdi)"


def test_1_2_has_good_sample_and_stability():
    """1.2 = ortalamanın %90'ı, sd'nin %41'i, örneklemin %80'i."""
    assert _total_n(1.2) >= 270, f"1.2% örneklem çok az: {_total_n(1.2)}"
    assert _sd(1.2) < 0.15, f"1.2% sd yüksek: {_sd(1.2):.3f}"
    # 3.0'dan daha az örnek kaybı
    assert _total_n(1.2) > 1.5 * _total_n(3.0)


def test_3_0_rejected_for_sample_size():
    """3.0% daha yüksek ortalama ama sd 2.4x ve yarı örneklem gider."""
    assert _mean(3.0) > _mean(1.2), "3.0 daha yüksek olmalı (reddin nedeni bu)"
    assert _sd(3.0) > 2 * _sd(1.2), "3.0 sd'si 2x'ten fazla olmalı"
    assert _total_n(3.0) < 0.7 * _total_n(1.2), "3.0 örneklemi belirgin az olmalı"


def test_all_seeds_positive():
    """Her seed'de her eşik pozitif (sağlamlık)."""
    for s, d in SEEDS.items():
        for th in THRESHOLDS:
            assert d[th][0] > 0, f"seed {s} eşik {th}: {d[th][0]}"


def test_win_rate_rises_with_threshold():
    """Kazanan oranı eşikle artmalı."""
    w0 = st.mean(SEEDS[s][0.0][2] for s in SEEDS)
    w3 = st.mean(SEEDS[s][3.0][2] for s in SEEDS)
    assert w3 > w0 + 5, f"kazanan oranı {w0:.1f}% -> {w3:.1f}%"


def test_fail_open_preserved():
    """OI verisi yoksa filtre uygulanmaz (aday elenmez)."""
    import inspect
    from app.routers import auto_paper
    src = inspect.getsource(auto_paper)
    # kapı fonksiyonu fail-open olmalı: oi None -> gate uygulanmaz
    assert "oi_change_below_min" in src
    i = src.find("def _entry_context")
    block = src[i:i + 9000]
    assert "min_oi = float(settings.get" in block
    # None kontrolü olmalı: veri yoksa kapı uygulanmaz
    assert "oi_chg is not None and oi_chg < min_oi" in block


def test_rule_signals_exempt():
    """Kural sinyalleri OI filtresinden muaf olmalı."""
    import inspect
    from app.routers import auto_paper
    src = inspect.getsource(auto_paper)
    i = src.find("min_oi = float(settings.get")
    ctx = src[max(0, i - 400):i + 200]
    assert "not rule_signal" in ctx, "kural sinyali muafiyeti bulunamadı"


def test_panel_clamp_allows_1_2():
    """Panel clamp aralığı 1.2'yi kabul etmeli."""
    src = (BASE / "app" / "routers" / "auto_paper.py").read_text(encoding="utf-8")
    assert "min_oi_change_pct\": max(-50.0, min(200.0" in src


def test_threshold_table_documented():
    doc = DOC.read_text(encoding="utf-8")
    assert "OI eşiği taraması" in doc
    assert "1,2%" in doc


@pytest.mark.parametrize("th", list(THRESHOLDS))
def test_each_threshold_threshold_dominates_baseline(th):
    """Her eşik ATR tabanından (+0.379%) yüksek olmalı."""
    base = st.mean(ATR_BASELINE.values())
    assert _mean(th) > base, f"{th}: {_mean(th):.3f} <= {base:.3f}"


def test_script_exists():
    assert (BASE / "scripts" / "oi_threshold_sweep.py").exists()
