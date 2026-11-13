"""Regresyon: `gate_replay.py` GERÇEK kapıyı mı kullanıyor?

Tuzak: `filt_replay.py` filtreyi SQL'de (`atr_pct >= X`) yeniden yazar. Bu,
üretim kodundaki kapının (sıralama, fail-open, kural muafiyeti) test
EDİLMEDİĞİ anlamına gelir — replay yeşil olsa bile canlı farklı davranır.

Bu test, gate_replay'in `auto_paper._entry_context` fonksiyonunu ÇAĞIRDIĞINI
ve ATR kararının üretim koduyla birebir aynı olduğunu kilitler.
"""
import asyncio
import inspect
import pathlib

import pytest

from app.routers import auto_paper as ap


def _gate_src() -> str:
    return pathlib.Path(ap.__file__).read_text(encoding="utf-8")


def test_replay_calls_production_gate():
    """gate_replay `_entry_context`'i import edip çağırmalı (kopya değil)."""
    src = pathlib.Path(__file__).parent.parent / "scripts" / "gate_replay.py"
    text = src.read_text(encoding="utf-8")
    assert "_entry_context" in text, "replay üretim kapısını çağırmıyor"
    assert "from app.routers import auto_paper" in text


def test_replay_matches_production_decision():
    """Replay'in kapı kararı, üretim kapısının kararıyla aynı olmalı."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
    from gate_replay import decide

    async def production(notif: dict, min_atr: float):
        async def _s():
            s = await ap.get_default_settings()
            s["min_atr_pct"] = min_atr
            s["min_score"] = 0.0
            s["allowed_modes"] = []
            return s
        orig = ap.get_auto_paper_settings
        ap.get_auto_paper_settings = _s
        try:
            return await ap._entry_context(notif)
        finally:
            ap.get_auto_paper_settings = orig

    cases = [
        ({"atr_pct": 0.4}, 1.0),   # düşük -> engel
        ({"atr_pct": 2.0}, 1.0),   # yüksek -> geçer
        ({"atr_pct": 1.0}, 1.0),   # tam sınır -> geçer
        ({"atr_pct": None}, 1.5),  # yok -> fail-open
        ({"atr_pct": 0.1}, 0.0),   # kapalı -> geçer
    ]
    for extra, min_atr in cases:
        notif = {"symbol": "BTCTRY", "score": 80.0, "mode": "trend_devam",
                 "source": "velocity", "price": 1.0, "target_pct": 2.0, **extra}
        ok_replay, _r = asyncio.run(decide(notif, min_atr))
        _s, block, _sym, _rule = asyncio.run(production(notif, min_atr))
        ok_prod = block is None
        assert ok_replay == ok_prod, f"karar uyuşmuyor {extra} min_atr={min_atr}"


def test_gate_order_is_score_then_mode_then_atr():
    """Kapı sırası korunmalı: skor -> mod -> ATR.

    Sıra bozulursa ATR, skor/mod engelini maskeleyebilir ve raporlanan engel
    nedeni yanlış olur.
    """
    src = inspect.getsource(ap._entry_context)
    i_score = src.find("score_below_min")
    i_mode = src.find("mode_not_allowed")
    i_atr = src.find("atr_below_min")
    assert -1 < i_score < i_mode < i_atr, (
        f"sıra bozuk: score={i_score} mode={i_mode} atr={i_atr}")


def test_evidence_documented():
    """Ölçüm sonuçları kod yorumunda ve raporda kayıtlı olmalı."""
    gate = _gate_src()
    assert "atr>=1.5" in gate or "atr>=1.0" in gate, "kanıt özeti kodda yok"
    doc = pathlib.Path(__file__).parent.parent.parent / "docs" / "RADAR_BACKTEST_ANALIZI_2026-11-10.md"
    assert doc.exists(), "backtest raporu yok"
    text = doc.read_text(encoding="utf-8")
    assert "atr_pct" in text and "+0,549%" in text.replace(".", ","), "rapor kanıtı eksik"


@pytest.mark.parametrize("min_atr,should_pass,atr", [
    (1.0, False, 0.9),
    (1.0, True, 1.0),
    (1.0, True, 1.1),
    (1.5, True, 1.5),
    (1.5, False, 1.49),
])
def test_threshold_boundary(monkeypatch, min_atr, should_pass, atr):
    """Eşik davranışı: `<` karşılaştırması, tam değer geçer."""
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = min_atr
        s["min_score"] = 0.0
        s["allowed_modes"] = []
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)
    notif = {"symbol": "XTRY", "score": 90.0, "mode": "trend_devam",
             "source": "velocity", "atr_pct": atr}
    _s, block, _sym, _rule = asyncio.run(ap._entry_context(notif))
    assert (block is None) is should_pass, f"atr={atr} min={min_atr} beklenen={should_pass}"
