"""Araştırma kaydı: `ret3_pct` ölü bölgesi (2026-11-10).

BULGU (gerçek 1m mum replay, 4 seed × 2000 = 8.000 aday, fee %0.30):

    bölge            n      ort_net    sd      medyan    kazanan
    < -2% (dip)     168    +0.550%   0.216   +0.220%     59.9%
    -2..-1%         459    +0.099%   0.060   -0.104%     42.9%
    -1..0%         2196    -0.036%   0.028   -0.240%     33.2%
    0..1% (ÖLÜ)    3975    -0.064%   0.017   -0.312%     29.7%
    1..2%           882    +0.058%   0.041   -0.301%     34.3%
    > +2% (momentum)296    +0.662%   0.104   +0.069%     52.2%

U-şekli GERÇEK: hem dip hem momentum iyi, 0..1% en kalabalık ve en kötü.

KARAR: `ret3` FİLTRESİ EKLENMEDİ. Gerekçe — ATR'nin üstüne katkısı marjinal:
    ATR>=1.0                     n=260  +0.247%  sd=0.056  kazanan %47.5
    ATR>=1.0 + ret3 DISLA(0..1)  n=190  +0.290%  sd=0.101  kazanan %49.1
    ATR>=1.0 + sadece momentum   n= 32  +0.622%  sd=0.317  kazanan %51.3
    ATR>=1.0 + uçlar(dip|mom)    n= 59  +0.596%  sd=0.239  kazanan %55.7

+0.043 puanlık kazanç, standart sapmanın 2 KAT artmasıyla geliyor (0.056 ->
0.101) ve örneklem 261 -> 191'e düşüyor. Uç filtrelerin görünen üstünlüğü
32-59 işleme dayanıyor (sd 0.317) — istatistiksel olarak anlamsız.

Bu test dosyası sonucu KİLİTLER: biri "ret3 ekleyelim" derse kanıt burada.
"""
import pathlib


def _doc() -> str:
    return (pathlib.Path(__file__).parent.parent.parent
            / "docs" / "RADAR_BACKTEST_ANALIZI_2026-11-10.md").read_text(encoding="utf-8")


def test_ret3_finding_is_recorded():
    """Bölge tablosu ve karar raporda kayıtlı olmalı."""
    doc = _doc()
    assert "ret3" in doc, "ret3 araştırması raporda yok"
    assert "Ölü bölge" in doc or "ölü bölge" in doc, "ölü bölge bulgusu yazılmamış"


def test_ret3_not_added_to_gate():
    """KARAR: `ret3` kapısı EKLENMEDİ — kapıda ret3 kontrolü olmamalı."""
    from app.routers import auto_paper as ap
    src = pathlib.Path(ap.__file__).read_text(encoding="utf-8")
    assert "ret3_below" not in src, "ret3 kapısı eklenmiş — kanıt marjinaldi"
    assert "ret3_pct" not in src.split("def _entry_context")[1].split("return settings, None")[0], (
        "giriş kapısında ret3 filtresi var")


def test_only_min_atr_is_enforced():
    """Giriş kapısında volatilite dışında fiyat-pattern filtresi yok."""
    from app.routers import auto_paper as ap
    import inspect
    src = inspect.getsource(ap._entry_context)
    assert "atr_below_min" in src
    assert "ret3" not in src


def test_scripts_exist_for_future_research():
    """Araştırma betikleri korunmalı (yeniden ölçüm için)."""
    base = pathlib.Path(__file__).parent.parent / "scripts"
    for name in ("trail_replay.py", "filt_replay.py", "gate_replay.py", "ret3_replay.py"):
        assert (base / name).exists(), f"{name} yok"
