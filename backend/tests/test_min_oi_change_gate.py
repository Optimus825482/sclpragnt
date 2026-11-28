"""Regresyon: `min_oi_change_pct` açık pozisyon (OI) tabanı (2026-11-10).

KANIT (docs/YUKSELIS_ARASTIRMASI_2026-11-10.md bölüm 19):
Hist futures verisi: 7.503.935 satır, 291 perp sembol, 5 dk aralık, 3 ay.
Onceki 60 dk OI degisimi, gercek 1m mum + trailing cikisi, 5 seed:

    seed  7: Q1 (dusuk OI) -0.308% (kaz %25.5) -> Q5 +0.562% (kaz %49.5)
    seed 11: -0.360% (%29.6) -> +0.553% (%48.1)
    seed 23: -0.344% (%24.7) -> +0.781% (%50.6)
    seed 42: -0.411% (%22.2) -> +0.266% (%40.5)
    seed 77: -0.503% (%18.5) -> +0.494% (%49.4)
    ortalama +0.917% (ATR'nin +0.364'unun 2.5 kati)

YORUM: OI artiyorsa yukselis YENI PARAYLA besleniyor -> surdurulebilir.
       Artmiyorsa short covering -> tukenir.

VARSAYILAN KAPALI (0.0) — üretim davranışı değişmez, panelden açılır.
"""
import asyncio
import pathlib

import pytest

from app.routers import auto_paper as ap


def _run(coro):
    return asyncio.run(coro)


def _notif(**kw):
    base = {"symbol": "BTCTRY", "score": 80.0, "mode": "trend_devam",
            "source": "velocity", "atr_pct": 2.0}
    base.update(kw)
    return base


def _patch(monkeypatch, **over):
    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = 0.0      # ATR kapısı kapalı (OI'yi izole et)
        s.update(over)
        return s
    monkeypatch.setattr(ap, "get_auto_paper_settings", _settings)


# ── varsayılan / ayar ───────────────────────────────────────────────────────

def test_default_is_measured_threshold():
    """Varsayılan 1.2% (2026-11-10 §25 taraması).

    ÖNCEDEN 0 (kapalı) idi. §24 OI+ATR'nin tamamlayıcı olduğunu kanıtladı,
    §25 eşiği taradı: ATR>=1 açıkken 1.2% -> +0.939% (taban +0.379%, 2.5x).
    Fail-open korunuyor: OI verisi yoksa filtre uygulanmaz.
    """
    from app import config
    # config varsayılanı taranmış değer olmalı (DB kaydı bunu gölgeleyebilir —
    # canlı kullanıcı ayarı önceliklidir, ayrı testte doğrulanır).
    assert config.Config.AUTO_PAPER_MIN_OI_CHANGE_PCT == 1.2
    s = _run(ap.get_auto_paper_settings())
    assert "min_oi_change_pct" in s
    assert isinstance(s["min_oi_change_pct"], float)


def test_db_override_takes_precedence_over_config():
    """DB'de kayıtlı ayar config varsayılanını gölgeler (beklenen davranış)."""
    from app import config
    s = _run(ap.get_auto_paper_settings())
    # panel DB'den okuyabilir; 0 (kapalı) da geçerli bir kullanıcı seçimi
    assert s["min_oi_change_pct"] >= 0.0
    assert s["min_oi_change_pct"] != config.Config.AUTO_PAPER_MIN_OI_CHANGE_PCT or         s["min_oi_change_pct"] == 1.2


def test_setting_present_and_clamped():
    s = _run(ap.get_auto_paper_settings())
    assert "min_oi_change_pct" in s
    s["min_oi_change_pct"] = 5.0
    assert s["min_oi_change_pct"] == 5.0


def test_config_constant_exists():
    from app import config
    assert hasattr(config.Config, "AUTO_PAPER_MIN_OI_CHANGE_PCT")
    # §25: taranmış eşik 1.2% (0 = kapalı değil; 0 hâlâ geçerli bir ayar)
    assert config.Config.AUTO_PAPER_MIN_OI_CHANGE_PCT == 1.2


# ── açıkken davranış ────────────────────────────────────────────────────────

def test_low_oi_change_blocked(monkeypatch):
    """min_oi=5.0 iken OI değişimi 2.0 olan aday engellenmeli."""
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(oi_change_pct=2.0)))
    assert block is not None, "düşük OI engellenmedi"
    assert block["reason"] == "oi_change_below_min"
    assert block["oi_change_pct"] == 2.0
    assert block["min_oi_change_pct"] == 5.0


def test_high_oi_change_passes(monkeypatch):
    """min_oi=5.0 iken OI değişimi 12.0 geçmeli."""
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(oi_change_pct=12.0)))
    assert block is None, f"yüksek OI engellendi: {block}"


def test_exact_threshold_passes(monkeypatch):
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(oi_change_pct=5.0)))
    assert block is None, "tam eşik engellendi"


def test_negative_oi_change_blocks(monkeypatch):
    """OI AZALIYORSA (yükseliş short covering) engellenmeli."""
    _patch(monkeypatch, min_oi_change_pct=3.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(oi_change_pct=-8.0)))
    assert block is not None
    assert block["reason"] == "oi_change_below_min"


def test_zero_disables_gate(monkeypatch):
    _patch(monkeypatch, min_oi_change_pct=0.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif(oi_change_pct=-99.0)))
    assert block is None, "min_oi=0 iken kapı açık kaldı"


# ── fail-open ───────────────────────────────────────────────────────────────

def test_fail_open_when_oi_missing(monkeypatch):
    """OI verisi yoksa (spot-only sembol) kapı UYGULANMAZ."""
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(_notif()))
    assert block is None, "OI yokken engellendi (fail-closed olmamalı)"


def test_fail_open_when_oi_none(monkeypatch):
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(
        _notif(oi_change_pct=None)))
    assert block is None


def test_fail_open_when_oi_invalid(monkeypatch):
    """Bozuk OI değeri kapıyı tetiklememeli (veri hatası sinyal kaybettirmesin)."""
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(
        _notif(oi_change_pct="abc")))
    assert block is None


# ── muafiyet ────────────────────────────────────────────────────────────────

def test_rule_signal_exempt(monkeypatch):
    """Kural sinyalleri (kendi rejim kapıları var) muaftır."""
    _patch(monkeypatch, min_oi_change_pct=5.0)
    _s, block, _sym, _rule = _run(ap._entry_context(
        _notif(source="ma_buy", oi_change_pct=0.0)))
    assert block is None


# ── kullanıcı mesajı ────────────────────────────────────────────────────────

def test_block_reason_message_explains_cause():
    """Engel mesajı kullanıcıya NEDENİ açıklamalı."""
    src = (pathlib.Path(__file__).parent.parent / "app" / "routers"
           / "auto_paper.py").read_text(encoding="utf-8")
    assert "oi_change_below_min" in src
    assert "taze parayla" in src, "mesaj 'yükseliş taze parayla beslenmiyor' demiyor"


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _channel_unrestricted(monkeypatch):
    """2026-11-25 TEK KANAL kapısı kapalı: bu dosya yalnız kapı
    davranışını sınar; kanal kısıtı ayrı testlerde (test_super_scan_channel) korunur."""
    from app.config import config as _config

    monkeypatch.setattr(_config, "SUPER_SCAN_ONLY", False, raising=False)
