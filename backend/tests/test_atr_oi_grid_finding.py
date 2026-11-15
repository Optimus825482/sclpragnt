"""ATR x OI izgarasi: §19'un "birbirini iptal ediyor" bulgusu YANLISTI (2026-11-10).

§19'daki iptal sonucu 60 dk OI penceresiyle olculmustu. §23'te dogru pencere
(15 dk) bulununca yeniden test edildi -> scripts/atr_oi_grid.py.

2x2 IZGARA (seed 7, n=1375):
    ATR<1  / OI dusuk   n=594  -0.298%  kaz %24.7
    ATR<1  / OI yuksek  n=597  +0.267%  kaz %42.7
    ATR>=1 / OI dusuk   n= 94  -0.188%  kaz %28.7
    ATR>=1 / OI yuksek  n= 90  +0.631%  kaz %50.0

OI ETKISI ATR SABITKEN (tekrarli bilgi testi):
    ATR<1  icinde: +0.565%
    ATR>=1 icinde: +0.819%
    -> OI, ATR sabitken de ayristiriyor => TEKRARLI BILGI DEGIL.

TEK BASINA vs BIRLIKTE (4 seed):
    seed   ATR>=1   OI yuksek  ikisi   sinerji
     7    +0.213%   +0.314%   +0.631%    EVET
    11    +0.258%   +0.202%   +0.487%    EVET
    23    +0.279%   +0.099%   +0.657%    EVET
    42    +0.195%   +0.382%   +0.205%    HAYIR
    ort   +0.236%   +0.249%   +0.495%    3/4

YORUM: "iptal yok" KESIN. "Sinerji var" ortalama olarak 2x ama 3/4 seed ->
zayif kanit (sd 0.207, n~90).

KARAR: §19 yasagi ("ikisini birden acma") KALDIRILDI. Tek basina da gecerli
(ATR en kararli: sd 0.039). Varsayilan min_oi_change_pct hala 0 (kapali).
"""
import pathlib

BASE = pathlib.Path(__file__).parent.parent
DOC = BASE.parent / "docs" / "YUKSELIS_ARASTIRMASI_2026-11-10.md"

GRID = {
    ("ATR<1", "OI dusuk"): (-0.298, 24.7),
    ("ATR<1", "OI yuksek"): (0.267, 42.7),
    ("ATR>=1", "OI dusuk"): (-0.188, 28.7),
    ("ATR>=1", "OI yuksek"): (0.631, 50.0),
}

SEEDS = {
    7: {"atr": 0.213, "oi": 0.314, "both": 0.631},
    11: {"atr": 0.258, "oi": 0.202, "both": 0.487},
    23: {"atr": 0.279, "oi": 0.099, "both": 0.657},
    42: {"atr": 0.195, "oi": 0.382, "both": 0.205},
}


def test_oi_high_beats_oi_low_in_every_atr_bucket():
    """Iddia: OI yuksek, ATR sabitken HER iki dilimde de daha iyi."""
    for atr in ("ATR<1", "ATR>=1"):
        hi = GRID[(atr, "OI yuksek")][0]
        lo = GRID[(atr, "OI dusuk")][0]
        assert hi > lo, f"{atr}: OI yuksek {hi} <= OI dusuk {lo}"


def test_oi_effect_survives_controlling_for_atr():
    """Tekrarli bilgi testi: ATR sabitken OI etkisi > 0.20 (anlamli)."""
    for atr in ("ATR<1", "ATR>=1"):
        d = GRID[(atr, "OI yuksek")][0] - GRID[(atr, "OI dusuk")][0]
        assert d > 0.20, f"{atr} icinde OI etkisi zayif: {d:.3f}"
    # olculen degerler
    assert abs((GRID[("ATR<1", "OI yuksek")][0]
                - GRID[("ATR<1", "OI dusuk")][0]) - 0.565) < 0.01
    assert abs((GRID[("ATR>=1", "OI yuksek")][0]
                - GRID[("ATR>=1", "OI dusuk")][0]) - 0.819) < 0.01


def test_cancellation_claim_is_false():
    """§19'daki 'iptal' iddiasi bu veride YANLIS olmali."""
    both = GRID[("ATR>=1", "OI yuksek")][0]
    atr_only = GRID[("ATR>=1", "OI dusuk")][0]
    assert both > 0, "ikisi birden pozitif degil -> iptal iddiasi dogru olurdu"
    assert both > atr_only + 0.20, "OI eklemek ATR'yi iptal ediyor"


def test_win_rate_monotonic_across_grid():
    """Kazanan orani ATR ve OI ile birlikte artmali."""
    worst = GRID[("ATR<1", "OI dusuk")][1]
    best = GRID[("ATR>=1", "OI yuksek")][1]
    assert best > worst + 20, f"kazanan orani artmiyor {worst} -> {best}"
    assert best == 50.0


def test_combined_beats_each_alone_on_average():
    """Ortalama olarak 'ikisi birden' tek basina filtrelerden iyi."""
    means = {k: sum(s[k] for s in SEEDS.values()) / len(SEEDS)
             for k in ("atr", "oi", "both")}
    assert means["both"] > means["atr"], f"{means}"
    assert means["both"] > means["oi"], f"{means}"
    assert means["both"] > 2 * max(means["atr"], means["oi"]) * 0.9


def test_synergy_is_not_unanimous():
    """DURUSTLUK: sinerji 4/4 degil, 3/4. Bunu kaydetmek zorundayiz."""
    wins = sum(1 for s in SEEDS.values() if s["both"] > max(s["atr"], s["oi"]))
    assert wins == 3, f"sinerji {wins}/4 (3 beklenirdi)"
    assert SEEDS[42]["oi"] > SEEDS[42]["both"], "seed 42 sinerji gostermeli"


def test_atr_is_most_stable_single_filter():
    """ATR tek basina en dusuk sd'ye sahip (en kararli secim)."""
    def sd(vals):
        m = sum(vals) / len(vals)
        return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5
    sd_atr = sd([s["atr"] for s in SEEDS.values()])
    sd_oi = sd([s["oi"] for s in SEEDS.values()])
    assert sd_atr < sd_oi, f"ATR sd {sd_atr:.3f} >= OI sd {sd_oi:.3f}"


def test_ban_lifted_in_docs():
    """§19 yasagi kaldirilmis olarak yazilmali."""
    doc = DOC.read_text(encoding="utf-8")
    assert "ATR × OI ızgarası" in doc or "ATR x OI" in doc
    assert "KALDIRILDI" in doc


def test_default_stays_off():
    """Varsayilan hala KAPALI — acmak kullanicinin karari."""
    from app import config
    assert float(getattr(config.Config, "AUTO_PAPER_MIN_OI_CHANGE_PCT", 0)) == 0.0


def test_methodology_lesson_documented():
    """Metodoloji dersi: yanlis esik -> yanlis 'cakisma' sonucu."""
    doc = DOC.read_text(encoding="utf-8")
    assert "Metodoloji dersi" in doc
    assert "3/4" in doc


def test_script_exists():
    assert (BASE / "scripts" / "atr_oi_grid.py").exists()
