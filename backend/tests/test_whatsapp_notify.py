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
    # 'both' en üstte olmalı (BBB), sonra potansiyele göre CCC, sonra AAA
    assert out.index("BBB") < out.index("CCC") < out.index("AAA")


def test_format_contains_values():
    out = wn.format_scan_report([
        {"symbol": "MINATRY", "price": 4.68, "ceiling_pct": 3.8, "potential_pct": 81, "strategy": "both"}])
    assert "MINA" in out            # TRY eki kaldırıldı
    assert "+%81" in out            # potansiyel
    assert "+%4" in out             # hedef (round 3.8 -> 4)
    assert "```" in out             # monospace tablo


def test_tracking_table_empty():
    out = wn.format_tracking_table([])
    assert "aday yok" in out.lower()


def test_tracking_table_sorted_desc():
    rows = [
        {"symbol": "AAA", "entry_price": 1.0, "current_price": 0.98, "change_pct": -2.0},
        {"symbol": "BBB", "entry_price": 1.0, "current_price": 1.10, "change_pct": 10.0},
        {"symbol": "CCC", "entry_price": 1.0, "current_price": 1.05, "change_pct": 5.0},
    ]
    out = wn.format_tracking_table(rows)
    # en iyi (BBB +%10) en üstte, sonra CCC, sonra AAA
    assert out.index("BBB") < out.index("CCC") < out.index("AAA")
    assert "```" in out  # monospace blok


def test_hourly_default_off():
    assert config.config.WHATSAPP_HOURLY_ENABLED is False


def test_hourly_interval_default_30():
    """Kullanıcı kararı (2026-10-10): gönderim aralığı 30 dk."""
    assert config.config.WHATSAPP_HOURLY_INTERVAL_MIN == 30


def test_tracking_table_has_summary_and_no_try_suffix():
    """Tablo: sembolden TRY eki kaldırılır + özet satırı olur."""
    out = wn.format_tracking_table([
        {"symbol": "MAGICTRY", "entry_price": 5.0, "current_price": 5.2, "change_pct": 4.0},
        {"symbol": "MINATRY", "entry_price": 4.0, "current_price": 3.9, "change_pct": -2.5},
    ])
    assert "MAGIC" in out and "MAGICTRY" not in out   # TRY eki kaldırıldı
    assert "yükselen" in out and "düşen" in out        # özet satırı
    assert "```" in out                                 # monospace blok
