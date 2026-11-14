"""Regresyon: `min_atr_pct` ÇIKIŞ MODELİNE BAĞIMLI (2026-11-10 bulgusu).

BULGU (docs/YUKSELIS_ARASTIRMASI_2026-11-10.md §10):
Aynı özellik (volatilite), farklı çıkış kuralında TERS sonuç veriyor.

  sabit TP1.5/SL5, 60dk (`velocity_candidates.net_pct`, 411.375 aday):
      ATR>=0 -> -0.465% | ATR>=1 -> -0.592% | ATR>=2 -> -0.769%   ZARAR
  trailing gap0.3, 240dk (gerçek 1m mum replay):
      ATR>=0 -> +0.046% | ATR>=1 -> +0.421%                        KÂR

SEBEP: oynak coin %5 sabit stopu 60 dk içinde daha sık deliyor
(SL oranı %39.4 -> %53.6), ama trailing'de daha çok tepe yapıyor.

SONUÇ: `min_atr_pct` kanıtı trailing'e dayanır. `trailing_enabled=False`
ise filtre SESSİZCE zarar verir -> kod onu devre dışı bırakıp uyarır.
"""
import asyncio
import inspect

import pytest

from app.routers import auto_paper as ap


async def _settings(**over):
    s = await ap.get_default_settings()
    s["min_score"] = 0.0
    s["min_atr_pct"] = 1.0
    s.update(over)
    return s


def _notif(atr=0.5, **over):
    n = {"symbol": "XTRY", "score": 90.0, "mode": "trend_devam",
         "source": "velocity", "atr_pct": atr, "price": 10.0}
    n.update(over)
    return n


def _gate(monkeypatch, settings, notif):
    ap._entry_context._atr_trail_warned = False

    async def _s():
        return settings

    monkeypatch.setattr(ap, "get_auto_paper_settings", _s)
    return asyncio.run(ap._entry_context(notif))


def test_atr_blocks_when_trailing_enabled(monkeypatch):
    """Trailing açıkken ATR düşükse GİRİŞ BLOKLANIR (kanıtlı yapılandırma)."""
    s = asyncio.run(_settings(trailing_enabled=True))
    _st, block, _sym, _rule = _gate(monkeypatch, s, _notif(atr=0.5))
    assert block is not None, "ATR filtresi çalışmadı"
    assert block.get("reason") == "atr_below_min"


def test_atr_disabled_when_trailing_off(monkeypatch):
    """Trailing KAPALIysa filtre devre dışı — sessizce zarar vermemeli."""
    s = asyncio.run(_settings(trailing_enabled=False))
    _st, block, _sym, _rule = _gate(monkeypatch, s, _notif(atr=0.5))
    assert block is None, "trailing kapalıyken ATR bloğu uygulandı (zararlı)"


def test_warning_logged_once(monkeypatch, caplog):
    """Devre dışı bırakılma bir kez loglanmalı (sessiz yanlış yapılandırma olmasın)."""
    s = asyncio.run(_settings(trailing_enabled=False))
    with caplog.at_level("WARNING"):
        _gate(monkeypatch, s, _notif(atr=0.5))
    assert any("trailing_enabled=False" in r.message for r in caplog.records), \
        "uyarı loglanmadı"


def test_dependency_is_documented_in_code():
    """Bağımlılık koddaki yorumda açıkça yazılmalı (birisi kaldırmasın)."""
    src = inspect.getsource(ap._entry_context)
    assert "ÇIKIŞ MODELİ BAĞIMLILIĞI" in src or "CIKIS MODELI BAGIMLILIGI" in src
    assert "trailing" in src


def test_opposite_signs_documented():
    """İki çıkış modelinin ZIT sonuç verdiği dokümanda yazılı olmalı."""
    import pathlib
    doc = (pathlib.Path(__file__).parent.parent.parent / "docs"
           / "YUKSELIS_ARASTIRMASI_2026-11-10.md").read_text(encoding="utf-8")
    assert "−0,592" in doc or "-0.592" in doc, "sabit model sonucu yok"
    assert "+0,421" in doc or "+0.421" in doc, "trailing sonucu yok"
    assert "BAĞIMLI" in doc or "BAGIMLI" in doc
