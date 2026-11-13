"""Regresyon: `min_atr_pct` volatilite tabanı (2026-11-10 backtest bulgusu).

KANIT (docs/RADAR_BACKTEST_ANALIZI_2026-11-10.md):
411.375 gerçekleşmiş velocity adayı + gerçek 1m mum replay:

    filtre yok   ort net +0.005%  medyan -0.263%  kazanan %34.6
    atr >= 1.0   ort net +0.344%  medyan -0.004%  kazanan %49.7
    atr >= 1.5   ort net +0.549%  medyan +0.059%  kazanan %53.0

Ayar VARSAYILAN KAPALI (0.0) — üretim davranışı değişmez, kullanıcı
panelden (PUT /api/auto-paper/settings) açar.
"""
import asyncio

import pytest

from app.routers import auto_paper as ap


def _run(coro):
    return asyncio.run(coro)


def _notif(**kw):
    base = {"symbol": "BTCTRY", "score": 80.0, "mode": "trend_devam",
            "source": "velocity", "atr_pct": 2.0}
    base.update(kw)
    return base


# ── varsayılan: KAPALI ───────────────────────────────────────────────────────

def test_default_is_disabled():
    """Varsayılan 0.0 olmalı — üretim davranışı sessizce değişmesin."""
    d = _run(ap.get_default_settings())
    assert d["min_atr_pct"] == 0.0


def test_disabled_lets_low_atr_through(monkeypatch):
    """0 iken düşük ATR'li aday geçmeli (eski davranış)."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 0.0
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    _s, block, sym, _rule = _run(ap._entry_context(_notif(atr_pct=0.2)))
    assert block is None, f"kapalıyken engelledi: {block}"
    assert sym == "BTCTRY"


# ── açıkken davranış ─────────────────────────────────────────────────────────

def test_low_atr_blocked_when_enabled(monkeypatch):
    """min_atr_pct=1.0 iken atr_pct=0.5 engellenmeli."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 1.0
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(atr_pct=0.5)))
    assert block is not None, "düşük ATR engellenmedi"
    assert block["reason"] == "atr_below_min"
    # `_blocked` ek alanları doğrudan bloğa yayar (detail sarmalayıcısı yok).
    assert block["atr_pct"] == 0.5
    assert block["min_atr_pct"] == 1.0


def test_high_atr_passes_when_enabled(monkeypatch):
    """min_atr_pct=1.0 iken atr_pct=2.0 geçmeli."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 1.0
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(atr_pct=2.0)))
    assert block is None, f"yüksek ATR engellendi: {block}"


def test_exact_threshold_passes(monkeypatch):
    """Sınır değerin KENDİSİ geçmeli (`<` karşılaştırması, `<=` değil)."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 1.5
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(atr_pct=1.5)))
    assert block is None, f"tam sınır değer engellendi: {block}"


def test_missing_atr_fails_open(monkeypatch):
    """`atr_pct` yoksa/0 ise filtre UYGULANMAZ (fail-open).

    Ölçülemeyen adayı 'düşük volatilite' sayıp reddetmek, veri eksikliği
    yüzünden sinyal kaybettirir. Filtre yalnız ÖLÇÜLMÜŞ değere uygulanır.
    """
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 1.5
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    for missing in ({}, {"atr_pct": None}, {"atr_pct": 0}, {"atr_pct": 0.0}):
        n = _notif(**missing)
        if "atr_pct" not in missing:
            n.pop("atr_pct", None)
        _s, block, _sym, _rule = _run(ap._entry_context(n))
        assert block is None, f"atr yokken engelledi ({missing}): {block}"


def test_rule_signals_exempt(monkeypatch):
    """Kural sinyalleri muaf — kendi rejim kapılarını taşırlar."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 5.0
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    src = next(iter(ap._RULE_SIGNAL_SOURCES))
    for s in ap._RULE_SIGNAL_SOURCES:
        monkeypatch.setitem(getattr(ap.config, ap._RULE_SIGNAL_SWITCHES[s], None) or {}, s, True) \
            if False else None
    _s, block, _sym, rule = _run(ap._entry_context(_notif(source=src, atr_pct=0.1)))
    assert rule is True
    assert block is None, f"kural sinyali ATR yüzünden engellendi: {block}"


def test_bad_atr_value_fails_open(monkeypatch):
    """Bozuk atr değeri (metin) filtreyi patlatmamalı, fail-open davranmalı."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 1.5
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(atr_pct="bozuk")))
    assert block is None


# ── ayar kaydı ──────────────────────────────────────────────────────────────

def test_setting_is_editable_via_api():
    """Panelden güncellenebilmeli: editable listesinde olmalı."""
    import inspect
    src = inspect.getsource(ap.update_settings_endpoint)
    assert "min_atr_pct" in src, "min_atr_pct editable listesinde değil"


def test_setting_is_clamped():
    """Kayıt sırasında 0..20 aralığına sıkıştırılmalı."""
    import inspect
    src = inspect.getsource(ap.update_settings_endpoint)
    assert '"min_atr_pct"' in src
    assert "min(20.0" in src, "üst sınır yok — sessiz kapanma riski"


def test_block_reason_is_human_readable():
    """Engel nedeni panelde okunur olmalı (reason_tr_map içinde).

    `_blocked` içindeki `reason_tr_map` YEREL bir sözlük; kaynağını o
    fonksiyondan okuyoruz.
    """
    import pathlib as _pl
    src = _pl.Path(ap.__file__).read_text(encoding="utf-8")
    assert '"atr_below_min":' in src, "reason_tr_map'te atr_below_min anahtarı yok"
    assert "Volatilite tabanının altında" in src, "okunur engel metni yok"
