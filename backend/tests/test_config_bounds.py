"""Kalıcı ayarların (llm_settings.runtime_config) açılışta geri yüklenmesi SINIR DIŞI değerleri düzeltir.

Hata (2026-10-16, canlı kopyada yeniden üretildi): DB'de `top_gainers_limit: 70` kayıtlıydı (limit eskiden
daha yüksekti). Açılış geri yükleme doğrulamadan `setattr` yapıyordu; ama `/api/config` güncelleme ucu
1-50 dışını REDDEDİYOR. Ayarlar sayfası tüm taslağı geri gönderdiğinden HİÇBİR ayar kaydedilemiyordu:
"top_gainers_limit 1 ile 50 arasında olmalıdır".
"""
import pytest

from app.config_bounds import INT_FIELD_BOUNDS, clamp_int_field, sanitize_persisted


@pytest.mark.parametrize("key,raw,expected", [
    ("top_gainers_limit", 70, 50),
    ("top_gainers_limit", 0, 1),
    ("top_gainers_limit", 25, 25),
    ("top_gainers_refresh_sec", 10, 60),
    ("top_gainers_refresh_sec", 99999, 3600),
    ("max_open_positions", -3, 0),
    ("max_open_positions", 600, 500),
    ("gainer_radar_min_score", 101, 100),
    ("symbol_activity_m1_flat_5m_max_count", 9, 5),
    ("symbol_activity_m1_flat_30m_max_count", 0, 1),
])
def test_clamp_int_field(key, raw, expected):
    assert clamp_int_field(key, raw) == expected


def test_unknown_key_is_returned_unchanged():
    assert clamp_int_field("baska_alan", 12345) == 12345


def test_non_numeric_value_is_left_for_caller():
    assert clamp_int_field("top_gainers_limit", "abc") == "abc"
    assert clamp_int_field("top_gainers_limit", None) is None


def test_sanitize_reports_changes_and_keeps_valid_values():
    cleaned, changes = sanitize_persisted({"top_gainers_limit": 70, "max_open_positions": 36,
                                           "symbols": ["BTCTRY"], "gainer_radar_min_score": 65})
    assert cleaned["top_gainers_limit"] == 50
    assert cleaned["max_open_positions"] == 36
    assert cleaned["gainer_radar_min_score"] == 65
    assert cleaned["symbols"] == ["BTCTRY"]
    assert changes == [("top_gainers_limit", 70, 50)]


def test_sanitize_does_not_mutate_input():
    src = {"top_gainers_limit": 70}
    sanitize_persisted(src)
    assert src == {"top_gainers_limit": 70}


def test_bounds_match_update_endpoint_messages():
    # Güncelleme ucundaki doğrulama ile AYNI sınırlar (tek doğruluk kaynağı bu modül)
    assert INT_FIELD_BOUNDS["top_gainers_limit"] == (1, 50)
    assert INT_FIELD_BOUNDS["top_gainers_refresh_sec"] == (60, 3600)
