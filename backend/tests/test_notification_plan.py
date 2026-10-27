"""notification_plan: plan kurucu, süre-dolarsa kuralı, mesaj metni."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from app import binance_tr_public, notification_plan, signal_eta

pytestmark = pytest.mark.real_plan

BOOK = {
    "asks": [["1.0000", "100000"], ["1.0010", "100000"], ["1.0020", "100000"]],
    "bids": [["0.9990", "100000"], ["0.9980", "100000"], ["0.9970", "100000"]],
}
STATS = {"n": 50, "hit_rate": 0.62, "p50_min": 35.0, "p75_min": 90.0, "mae_p80_pct": 4.0}
TZ = ZoneInfo("Europe/Istanbul")


def _compose(**kw):
    args = dict(symbol="X", bucket="ma_buy:4h", price=1.0, signal_target_pct=2.0, book=BOOK,
                quote_volume_try=1e9, stats=STATS, fee_frac=0.001125, now=1000.0, profile=None)
    args.update(kw)
    return notification_plan.compose_plan(**args)


def test_compose_basic():
    p = _compose()
    assert p["target_net_pct"] == 3.0
    assert p["target_gross_pct"] >= 3.0 + 0.225
    assert p["target_price"] == p["entry_ref_price"] * (1 + p["target_gross_pct"] / 100)
    assert p["eta_minutes"] == 35.0 and p["exit_at"] == 1000.0 + 90 * 60
    assert p["grace_minutes"] == 90.0 and p["hit_rate"] == 0.62 and p["sample_n"] == 50
    assert p["stop_pct"] == 4.0 and p["profile_exit"] is False
    assert isinstance(p["max_amount_try"], float) and p["max_amount_try"] > 0


def test_compose_signal_target_wins_and_profile_exit():
    p = _compose(signal_target_pct=10.0, profile={"stop_loss_pct": 8.0, "max_hold_minutes": 1440})
    assert p["target_gross_pct"] == 10.0 and p["profile_exit"] is True
    assert p["stop_pct"] == 8.0 and p["exit_at"] == 1000.0 + 1440 * 60
    assert p["grace_minutes"] == 0 and p["eta_minutes"] == 35.0


def test_compose_no_stats():
    p = _compose(stats=None)
    assert p["eta_minutes"] is None and p["exit_at"] is None and p["stop_pct"] is None
    assert p["stop_price"] is None and p["grace_minutes"] is None
    assert "veri_yetersiz" in p["warnings"]


def test_stop_clamped():
    assert _compose(stats={**STATS, "mae_p80_pct": 14.0})["stop_pct"] == 10.0
    assert _compose(stats={**STATS, "mae_p80_pct": 0.5})["stop_pct"] == 2.0


def test_unrealistic_warning():
    # pahalı defter (yüksek maliyet) → defter brüt hedefi > 8 → uyarı
    assert "hedef_gercekci_degil" in _compose(fee_frac=0.025)["warnings"]
    assert "hedef_gercekci_degil" not in _compose()["warnings"]


def test_unrealistic_check_uses_book_gross_not_signal_target():
    # sinyal hedefi %9 defter hedefini geçer ama defter hedefi gerçekçi → uyarı YOK
    p = _compose(signal_target_pct=9.0)
    assert p["target_gross_pct"] == 9.0 and p["target_source"] == "signal"
    assert "hedef_gercekci_degil" not in p["warnings"]
    assert _compose()["target_source"] == "book"


def test_exit_advice_rules():
    plan = {"exit_at": 100.0, "grace_minutes": 10}
    assert notification_plan.exit_advice(plan, 1.0, 1.05, 99.0, 0.001) is None
    assert notification_plan.exit_advice(plan, 1.0, 1.01, 100.0, 0.001) == "cik"
    assert notification_plan.exit_advice(plan, 1.0, 0.95, 100.0, 0.001) == "bekle_stop"
    assert notification_plan.exit_advice(plan, 1.0, 0.95, 100.0 + 600, 0.001) == "cik"
    assert notification_plan.exit_advice({"exit_at": None}, 1.0, 0.95, 1e12, 0.001) is None


def test_build_plan_timeout_returns_none():
    with patch.object(binance_tr_public, "depth", side_effect=asyncio.TimeoutError):
        assert asyncio.run(notification_plan.build_plan("XTRY", "radar", 1.0, 2.0)) is None


def test_build_plan_ok():
    with patch.object(binance_tr_public, "depth", AsyncMock(return_value=BOOK)), \
         patch.object(binance_tr_public, "ticker_24h", AsyncMock(return_value=[{"quoteVolume": "1000000000"}])), \
         patch.object(signal_eta, "get_stats", AsyncMock(return_value=STATS)):
        p = asyncio.run(notification_plan.build_plan("XTRY", "radar", 1.0, 2.0, now=1000.0))
    assert p["symbol"] == "XTRY" and p["eta_minutes"] == 35.0


SAMPLE_PLAN = {
    "max_amount_try": 40999.7, "target_net_pct": 3.0, "target_gross_pct": 3.4, "target_price": 6.2199,
    "eta_minutes": 35.0, "hit_rate": 0.62, "exit_at": datetime(2026, 10, 27, 20, 45, tzinfo=TZ).timestamp(),
    "created_at": datetime(2026, 10, 27, 19, 0, tzinfo=TZ).timestamp(),
    "stop_price": 5.82, "profile_exit": False, "warnings": [],
}


def test_plan_text_exact():
    assert notification_plan.plan_text(SAMPLE_PLAN) == (
        "Maks: 40.000 TL | Hedef 6,22 (+%3 net) | ~35 dk (geçmişte %62) | Çıkış 20:45'e kadar | Stop 5,82")


def test_plan_text_signal_target_shows_gross():
    t = notification_plan.plan_text({**SAMPLE_PLAN, "target_gross_pct": 9.0, "target_source": "signal"})
    assert "Hedef 6,22 (+%9 brüt)" in t and "net)" not in t
    # eski planlar (alan yok) ve defter kaynağı: net etiketi
    assert "(+%3 net)" in notification_plan.plan_text({**SAMPLE_PLAN, "target_source": "book"})


def test_plan_text_profile_exit_without_stats_keeps_exit_and_stop():
    t = notification_plan.plan_text({**SAMPLE_PLAN, "profile_exit": True, "eta_minutes": None, "hit_rate": None,
                                     "warnings": ["veri_yetersiz"]})
    assert t == ("Maks: 40.000 TL | Hedef 6,22 (+%3.4 brüt) | Süre: veri yetersiz | "
                 "Çıkış 20:45'e kadar | Stop 5,82")


def test_compose_profile_exit_no_stats_text():
    p = _compose(stats=None, signal_target_pct=10.0, profile={"stop_loss_pct": 8.0, "max_hold_minutes": 60})
    assert "veri_yetersiz" in p["warnings"] and p["stop_price"] is not None and p["exit_at"] is not None
    t = notification_plan.plan_text(p)
    assert "Süre: veri yetersiz" in t and "Çıkış" in t and "Stop" in t and "(+%10 brüt)" in t


def test_plan_text_variants():
    t = notification_plan.plan_text({**SAMPLE_PLAN, "eta_minutes": 135.0, "target_price": 0.02316,
                                     "exit_at": SAMPLE_PLAN["created_at"] + 86400 + 3600})
    assert "Hedef 0,02316" in t and "~2 sa 15 dk" in t and "Çıkış 28.10 20:00'e kadar" in t
    t = notification_plan.plan_text({**SAMPLE_PLAN, "profile_exit": True})
    assert "(+%3.4 brüt)" in t
    t = notification_plan.plan_text({**SAMPLE_PLAN, "eta_minutes": None, "exit_at": None, "stop_price": None,
                                     "warnings": ["veri_yetersiz", "hedef_gercekci_degil"]})
    assert t == "⚠ %3 net bu defterde zor · Maks: 40.000 TL | Hedef 6,22 (+%3 net) | Süre: veri yetersiz"
