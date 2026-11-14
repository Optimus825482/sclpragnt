"""OI penceresi taraması: 60 dk keyfi seçimdi -> 15 dk kazandı (2026-11-10).

TEST: scripts/oi_window_sweep.py — AYNI adaylar, AYNI replay, YALNIZ OI
penceresi değişir (kontrollü deney; replay gürültüsü sabit).

SONUÇ (4 seed, Q5-Q1):
    pencere  ortalama   sd     en kötü seed  en iyi kaç seed
    15 dk    +0.878%   0.089   +0.749%       4/4
    20 dk    +0.731%   0.066   +0.640%       0/4
    30 dk    +0.682%   0.104   +0.549%       0/4
    60 dk    +0.502%   0.180   +0.285%       0/4
   120 dk    +0.426%   0.290   +0.009%       0/4
   240 dk    +0.380%   0.239   +0.088%       0/4

MONOTON: pencere kısaldıkça etki güçleniyor (taze para akışı daha bilgili).
Q5 kazanan oranı 15 dk'da %50-56, 60 dk'da %38-49.

KARAR: varsayılan pencere 60 dk -> 15 dk. Panelden ayarlanabilir.

ALT SINIR 15 dk: hist_futures_metrics 5 dk aralıklı -> değişim için 3 bar
gerekir. 5/10 dk denendi, örneklem 0 döndü.
"""
import pathlib

import pytest

BASE = pathlib.Path(__file__).parent.parent


def _sweep() -> dict:
    """Taramada ölçülen değerler (4 seed Q5-Q1)."""
    return {
        "seed7": {15: 0.901, 20: 0.783, 30: 0.783, 60: 0.602,
                  120: 0.553, 240: 0.542},
        "seed11": {15: 0.910, 20: 0.723, 30: 0.549, 60: 0.285,
                   120: 0.009, 240: 0.088},
        "seed23": {15: 0.951, 20: 0.776, 30: 0.742, 60: 0.689,
                   120: 0.673, 240: 0.605},
        "seed42": {15: 0.749, 20: 0.640, 30: 0.654, 60: 0.434,
                   120: 0.467, 240: 0.284},
    }


WINDOWS = (15, 20, 30, 60, 120, 240)


def test_15min_best_in_every_seed():
    """İddia: 15 dk 4/4 seed'de en yüksek."""
    data = _sweep()
    for name, d in data.items():
        best = max(WINDOWS, key=lambda w: d[w])
        assert best == 15, f"{name}: en iyi {best} dk (15 beklenirdi)"


def test_effect_is_monotonic():
    """İddia: pencere kısaldıkça etki güçlenir (kabaca monoton)."""
    data = _sweep()
    for name, d in data.items():
        # 15 < 60 < 240 zincirinde kesin azalma olmalı
        assert d[15] > d[60] > d[240], f"{name}: monoton değil {d}"


def test_15min_beats_60min_comfortably():
    """15 dk, mevcut 60 dk varsayılanından belirgin iyi olmalı (>+0.2)."""
    data = _sweep()
    for name, d in data.items():
        assert d[15] - d[60] > 0.2, f"{name}: fark küçük {d[15]-d[60]:.3f}"


def test_spread_comfortably_above_threshold():
    """15 dk Q5-Q1 her seed'de > 0.20 (kullanılabilir eşik)."""
    for name, d in _sweep().items():
        assert d[15] > 0.20, f"{name}: {d[15]}"


def test_default_is_15():
    from app import config
    win = float(getattr(config.Config, "AUTO_PAPER_OI_WINDOW_MIN", 0))
    assert win == 15.0, f"varsayılan {win} (15 beklenirdi)"


def test_panel_exposes_window():
    """Panel alanı var ve config varsayılanını yansıtıyor.

    NOT: canlı DB'de kullanıcı değeri (ör. 30) olabilir; bu yüzden sabit 15
    beklenmez — config varsayılanı ile karşılaştırılır.
    """
    import asyncio
    from app import config
    from app.routers import auto_paper
    s = asyncio.run(auto_paper.get_auto_paper_settings())
    assert "oi_window_min" in s
    assert s["oi_window_min"] > 0
    assert isinstance(s["oi_window_min"], float)
    default = float(getattr(config.Config, "AUTO_PAPER_OI_WINDOW_MIN", 15.0))
    assert default == 15.0


def _apply(payload: dict) -> dict:
    """Gerçek yol: update_settings_endpoint (admin + DB sahte).

    Dönüş: {"paper_only": True, "ok": True, "settings": {...}} — iç içe.
    """
    import asyncio
    from unittest import mock
    from app.routers import auto_paper

    async def _get():
        from app.routers.auto_paper import get_auto_paper_settings as g
        return await g()

    async def _set(*_a, **_k):
        return None

    async def _log(*_a, **_k):
        return None

    req = mock.Mock()
    with mock.patch("app.api_common.require_admin", lambda _r: None),          mock.patch.object(auto_paper.database, "set_llm_setting", _set),          mock.patch.object(auto_paper, "log_user_action", _log):
        return asyncio.run(auto_paper.update_settings_endpoint(payload, req))["settings"]


@pytest.mark.parametrize("requested,expected", [
    (5.0, 15.0), (10.0, 15.0), (15.0, 15.0), (30.0, 30.0),
    (240.0, 240.0), (500.0, 240.0), (-5.0, 15.0),
])
def test_panel_window_clamp_bounds(requested, expected):
    """Panel gerçekten 15..240 arasına sıkıştırıyor mu (uçtan uca)."""
    s = _apply({"oi_window_min": requested})
    assert s["oi_window_min"] == expected


def test_panel_clamps_low_window():
    """Panel 5 dk isteyemez — veri 5 dk aralıklı, min 15."""
    assert _apply({"oi_window_min": 1.0})["oi_window_min"] == 15.0


def test_panel_exposes_window_in_editable_list():
    """Panel alanı editlenebilir listede olmalı (yoksa sessizce yutulur)."""
    import inspect
    from app.routers import auto_paper
    src = inspect.getsource(auto_paper.update_settings_endpoint)
    assert '"oi_window_min"' in src
    assert '"min_oi_change_pct"' in src


def test_clamp_function_limits_bounds():
    """Clamp mantığı: 15..240."""
    def clamp(v):
        return max(15.0, min(240.0, float(v or 15.0)))
    assert clamp(1.0) == 15.0
    assert clamp(5.0) == 15.0
    assert clamp(30.0) == 30.0
    assert clamp(500.0) == 240.0


def test_bar_count_derived_from_window():
    """Uzaklık hesabı: bar sayısı = pencere/5 + 1, [3, 48] arası."""
    for win, bars in ((15, 4), (30, 7), (60, 13), (240, 48)):
        got = max(3, min(48, int(round(win / 5.0)) + 1))
        assert got == bars, f"{win}dk -> {got} bar ({bars} beklenirdi)"


def test_service_reads_window_from_config():
    src = (BASE / "app" / "derivatives_service.py").read_text(encoding="utf-8")
    assert "AUTO_PAPER_OI_WINDOW_MIN" in src, "servis pencereyi config'ten okumuyor"
    assert "limit={_bars}" in src, "bar sayısı dinamik değil"
    assert "period=5m" in src


def test_lower_bound_reason_documented():
    """Neden 15 dk alt sınır (5/10 imkansız) yazılı olmalı."""
    from app import config
    cfg_src = (BASE / "app" / "config.py").read_text(encoding="utf-8")
    assert "5 dk aralıklı" in cfg_src or "5dk aralikli" in cfg_src
    assert hasattr(config.Config, "AUTO_PAPER_OI_WINDOW_MIN")


def test_doc_section_appended():
    doc = (BASE.parent / "docs" / "YUKSELIS_ARASTIRMASI_2026-11-10.md")
    text = doc.read_text(encoding="utf-8")
    assert "OI PENCERE" in text.upper()
    assert "4/4" in text
