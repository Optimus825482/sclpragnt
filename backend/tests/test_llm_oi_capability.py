"""Regresyon: LLM'i ölçülmüş bulgularla donatmak (2026-11-10).

PROBLEM: LLM ikinci gözü 20+ araca ve 9 skill'e sahipti ama bu oturumda ölçülen
TEK gerçek öncü göstergeyi (OI değişimi) GÖREMİYORDU. `oi_change_1h_pct` zaten
`derivatives_service.squeeze_confirmation` içinde hesaplanıyordu ama LLM'e
aktarılmıyordu (0 geçiş). LLM "yükseliş yeni parayla mı yoksa short covering ile
mi besleniyor" ayrımını yapamıyordu.

ÜÇ KATMAN EKLENDİ:
1. KANIT: `derivatives_evidence` artık `oi_change_1h_pct`, `funding_trend`,
   `squeeze_confirmed` alanlarını paketliyor (önbellekten, ağ beklemez).
2. SKILL: "Açık Pozisyon (OI) Öncü Göstergesi" + "Ölçülmüş Sinyal Ağırlıkları"
   (ölü sinyaller, ATR/OI etkileşimi, çıkış modeli bağımlılığı).
3. ARAÇ: `get_open_interest_lead` — LLM canlı OI sorgulayabilir.

ÖLÇÜM (docs/YUKSELIS_ARASTIRMASI §19): OI yüksek dilim kazanan %40-51,
düşük dilim %18-30; Q5-Q1 +0.92pp (ATR'nin 2.5 katı).
"""
import asyncio
import pathlib

import pytest

from app.ai_trading_suite import chat_tools
from app import database, derivatives_service, llm_second_eye


def _run(coro):
    return asyncio.run(coro)


# ── Katman 1: kanıt paketi ──────────────────────────────────────────────────

def test_squeeze_cache_reader_exists():
    """Önbellek okuyucusu olmalı — LLM yolu ağ bekleyemez."""
    assert hasattr(derivatives_service, "get_cached_squeeze_confirmation")
    # soğuk önbellekte None (fail-open), patlamaz
    assert derivatives_service.get_cached_squeeze_confirmation("ZZZTRY") is None


def test_oi_fields_flow_into_evidence(monkeypatch):
    """OI alanları kanıt paketine girmeli."""
    monkeypatch.setattr(
        derivatives_service, "get_cached_derivatives_intel",
        lambda s, max_age_sec=None: {"funding_rate_pct": 0.01,
                                    "open_interest_usd": 1e9})
    monkeypatch.setattr(
        derivatives_service, "get_cached_squeeze_confirmation",
        lambda s, max_age_sec=None: {"oi_change_1h_pct": 8.5,
                                     "funding_trend": "easing",
                                     "squeeze_confirmed": True})
    ev = _run(llm_second_eye.derivatives_evidence("BTCTRY"))
    assert ev["oi_change_1h_pct"] == 8.5
    assert ev["funding_trend"] == "easing"
    assert ev["squeeze_confirmed"] is True


def test_evidence_survives_cold_oi_cache(monkeypatch):
    """OI önbelleği soğuksa kanıt yine dönmeli (fail-open)."""
    monkeypatch.setattr(
        derivatives_service, "get_cached_derivatives_intel",
        lambda s, max_age_sec=None: {"funding_rate_pct": 0.02})
    monkeypatch.setattr(
        derivatives_service, "get_cached_squeeze_confirmation",
        lambda s, max_age_sec=None: None)
    ev = _run(llm_second_eye.derivatives_evidence("BTCTRY"))
    assert ev["funding_rate_pct"] == 0.02
    assert "oi_change_1h_pct" not in ev


def test_evidence_never_raises(monkeypatch):
    """Hata durumunda exception değil, temiz dönüş."""
    def _boom(*a, **k):
        raise RuntimeError("cache patladı")
    monkeypatch.setattr(derivatives_service, "get_cached_derivatives_intel", _boom)
    assert _run(llm_second_eye.derivatives_evidence("BTCTRY")) is None


# ── Katman 2: skill'ler ─────────────────────────────────────────────────────

def test_oi_skill_constant_exists():
    assert database.OI_SKILL_NAME
    txt = database.OI_SKILL_INSTRUCTIONS
    assert "oi_change_1h_pct" in txt
    assert "NEW MONEY" in txt and "SHORT COVERING" in txt


def test_oi_skill_has_measured_numbers():
    """Skill ölçüm rakamlarını taşımalı (uydurma değil, kanıt)."""
    txt = database.OI_SKILL_INSTRUCTIONS
    assert "0.92" in txt, "ölçülen Q5-Q1 farkı yok"
    assert "2.5x" in txt, "ATR'ye göre kat yok"
    assert "18-30" in txt and "40-51" in txt, "kazanan oranları yok"


def test_oi_skill_warns_against_double_counting():
    """ATR + OI birlikte kullanım uyarısı olmalı (ölçülmüş iptal)."""
    txt = database.OI_SKILL_INSTRUCTIONS
    assert "ATR" in txt
    assert "do not also demand" in txt.lower() or "Do NOT double-count" in txt


def test_oi_skill_handles_missing_data():
    """OI yokken tahmin etmemeli — 'veri eksik' demeli."""
    txt = database.OI_SKILL_INSTRUCTIONS
    assert "null or absent" in txt or "missing" in txt.lower()
    assert "do not infer" in txt.lower()


def test_oi_skill_seeded_in_both_paths():
    """Postgres ve SQLite seed yollarına da eklenmeli."""
    src = (pathlib.Path(__file__).parent.parent / "app" / "database.py").read_text(
        encoding="utf-8")
    assert src.count("OI_SKILL_NAME, OI_SKILL_INSTRUCTIONS") == 2, (
        "her iki seed yolunda olmalı")


# ── Katman 3: araç ─────────────────────────────────────────────────────────

def test_tool_registered():
    names = [t["function"]["name"] for t in chat_tools.AI_TRADING_SUITE_TOOLS]
    assert "get_open_interest_lead" in names


def test_tool_schema_valid():
    tool = next(t for t in chat_tools.AI_TRADING_SUITE_TOOLS
                if t["function"]["name"] == "get_open_interest_lead")
    fn = tool["function"]
    assert fn["parameters"]["required"] == ["symbol"]
    assert "oi_change_1h_pct" in fn["description"]


def test_tool_executes_and_returns_verdict(monkeypatch):
    monkeypatch.setattr(derivatives_service, "get_cached_squeeze_confirmation",
                        lambda s, max_age_sec=None: {"oi_change_1h_pct": 12.0,
                                                     "funding_trend": "easing",
                                                     "squeeze_confirmed": True})
    r = _run(chat_tools.execute_open_interest_lead({"symbol": "BTCTRY"}))
    assert r["ok"] is True
    assert r["oi_change_1h_pct"] == 12.0
    assert "new_money" in r["verdict"], r["verdict"]


def test_tool_flags_oi_unwinding(monkeypatch):
    """OI eriyorsa 'short covering, tükenir' demeli."""
    monkeypatch.setattr(derivatives_service, "get_cached_squeeze_confirmation",
                        lambda s, max_age_sec=None: {"oi_change_1h_pct": -9.0})
    r = _run(chat_tools.execute_open_interest_lead({"symbol": "BTCTRY"}))
    assert "unwinding" in r["verdict"]


def test_tool_fail_open_on_missing_data(monkeypatch):
    """Veri yoksa ok=True + oi=None + 'tahmin etme' notu."""
    monkeypatch.setattr(derivatives_service, "get_cached_squeeze_confirmation",
                        lambda s, max_age_sec=None: None)
    async def _empty(sym):
        return {}
    monkeypatch.setattr(derivatives_service, "squeeze_confirmation", _empty)
    r = _run(chat_tools.execute_open_interest_lead({"symbol": "ZZZTRY"}))
    assert r["ok"] is True
    assert r["oi_change_1h_pct"] is None
    assert "tahmin etme" in r["note"]


def test_tool_never_raises(monkeypatch):
    """Araç asla exception fırlatmamalı (LLM akışı kırılmamalı)."""
    def _boom(*a, **k):
        raise RuntimeError("ağ hatası")
    monkeypatch.setattr(derivatives_service, "get_cached_squeeze_confirmation", _boom)
    r = _run(chat_tools.execute_open_interest_lead({"symbol": "BTCTRY"}))
    assert r["ok"] is True
    assert r["oi_change_1h_pct"] is None


def test_tool_requires_symbol():
    r = _run(chat_tools.execute_open_interest_lead({}))
    assert r["ok"] is False


def test_tool_dispatched_in_chat_router():
    """Kayıtlı ama çağrılamaz olmamalı — dispatcher'da olmalı."""
    src = (pathlib.Path(__file__).parent.parent / "app" / "routers"
           / "llm_chat.py").read_text(encoding="utf-8")
    assert "execute_open_interest_lead" in src
    assert '"get_open_interest_lead"' in src
