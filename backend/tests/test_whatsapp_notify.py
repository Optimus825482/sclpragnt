"""WhatsApp bildirim modülü testleri (2026-10-10).

Kapsam:
- Yapılandırma yoksa `send_whatsapp` fail-safe (False, hata fırlatmaz).
- `format_scan_report` boş liste + sıralama (both üstte, potansiyel'e göre).
- Config varsayılanı KAPALI.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import whatsapp_notify as wn  # noqa: E402


def test_whatsapp_default_off():
    assert config.config.WHATSAPP_NOTIFY_ENABLED is False


def test_whatsapp_disabled_is_noop():
    """Yapılandırma yoksa gönderim sessizce başarısız olmalı (hata fırlatmaz)."""
    import asyncio
    assert wn.whatsapp_enabled() is False
    assert asyncio.run(wn.send_whatsapp("test")) is False


def test_format_empty():
    out = wn.format_scan_report([])
    assert "aday bulunamadı" in out.lower()


def test_format_orders_both_first():
    rows = [
        {"symbol": "AAATRY", "price": 1.0, "ceiling_pct": 5, "potential_pct": 10, "strategy": "short_squeeze"},
        {"symbol": "BBBTRY", "price": 2.0, "ceiling_pct": 5, "potential_pct": 20, "strategy": "both"},
        {"symbol": "CCCTRY", "price": 3.0, "ceiling_pct": 5, "potential_pct": 90, "strategy": "daily_momentum"},
    ]
    out = wn.format_scan_report(rows)
    # 'both' en üstte olmalı (BBBTRY), sonra potansiyele göre CCCTRY, sonra AAATRY
    assert out.index("BBBTRY") < out.index("CCCTRY") < out.index("AAATRY")


def test_format_contains_values():
    out = wn.format_scan_report([
        {"symbol": "MINATRY", "price": 4.68, "ceiling_pct": 3.8, "potential_pct": 81, "strategy": "both"}])
    assert "MINATRY" in out
    assert "potansiyel +%81" in out
    assert "hedef +%4" in out
