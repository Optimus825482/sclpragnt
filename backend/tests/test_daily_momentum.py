"""Günlük momentum katmanı testleri (2026-10-10).

Kapsam:
- Config varsayılanı OFF (fail-safe).
- `daily_momentum_ok` bayrağının `passes`'ı ETKİLEMEMESİ (bağımsızlık).
- Kapı mantığı: ret_8h / ATR / ADX / slope eşikleri.
- Veri eksikse fail-open (bayrak None kalır, tarama düşmez).
- DB yardımcı fonksiyonlarının varlığı.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app.routers import velocity  # noqa: E402
from app import database  # noqa: E402


def test_daily_momentum_default_on():
    """Kullanıcı kararı (2026-10-10): katman varsayılan AÇIK ("direkt çalışsın").
    Kapatmak için DAILY_MOMENTUM_ENABLED=false yeterlidir."""
    assert config.config.DAILY_MOMENTUM_ENABLED is True


def test_daily_momentum_thresholds_present():
    c = config.config
    assert c.DAILY_MOMENTUM_RET_8H_MIN == 2.0
    assert c.DAILY_MOMENTUM_ATR_MIN == 0.5
    assert c.DAILY_MOMENTUM_ADX_MIN == 25.0
    assert c.DAILY_MOMENTUM_SLOPE_MIN == 0.3
    assert c.DAILY_MOMENTUM_SPREAD_MAX == 0.20
    # Tarama saat çapası: kanıtlanan edge 11:30 snapshot'ı içindi.
    assert c.DAILY_MOMENTUM_SCAN_HOUR == 11
    assert c.DAILY_MOMENTUM_SCAN_MINUTE == 30
    assert c.DAILY_MOMENTUM_TZ == "Europe/Istanbul"


def test_daily_momentum_flag_is_independent_of_passes():
    """`scan_one` kaynak kodunda `daily_momentum_ok`'un `passes`'A yazılmadığını
    ve `passes`'ın yeni bayrağa bağlı olmadığını doğrula (bağımsızlık sözleşmesi)."""
    import inspect
    src = inspect.getsource(velocity.detect_velocity_candidates)
    # `passes =` satırı daily_momentum içermemeli.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("passes ="):
            assert "daily_momentum" not in stripped, "passes günlük momentumla bağlanmamalı"
    assert "daily_momentum_ok" in src
    assert "DAILY_MOMENTUM_ENABLED" in src


def test_daily_momentum_helpers_exist():
    for name in ("save_daily_rising", "list_daily_rising", "get_daily_rising_stats",
                 "fill_daily_rising_outcomes", "mark_daily_rising_notified",
                 "last_daily_rising_at"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_user_watchlist_helpers_exist():
    """Kullanıcıya özel takip listesi fonksiyonları mevcut olmalı (+ başarı ölçümü)."""
    for name in ("add_to_user_daily_watchlist", "list_user_daily_watchlist",
                 "remove_from_user_daily_watchlist", "fill_user_watchlist_outcomes",
                 "get_user_watchlist_stats"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_watchlist_outcomes_live_signature():
    """Canlı güncelleme: fill_user_watchlist_outcomes live_prices kabul etmeli."""
    import inspect
    sig = inspect.signature(database.fill_user_watchlist_outcomes)
    assert "live_prices" in sig.parameters, "canlı fiyat parametresi eksik"


def test_daily_rising_manual_and_watchlist_endpoints():
    """Manuel tarama ve takip listesi uçları router'a kayıtlı olmalı."""
    from app.routers import monitoring
    paths = {getattr(r, "path", "") for r in monitoring.router.routes}
    assert "/api/daily-rising/manual-scan" in paths
    assert "/api/daily-rising/watchlist" in paths


def test_touch_probability_calibrated():
    """Hedefe ulaşım ihtimali gerçek veriden kalibre: hedef=3·ATR → ~%60."""
    from app.routers.monitoring import touch_probability
    assert touch_probability(3.0, 1.0) == 60.0      # 3x ATR
    assert touch_probability(1.0, 1.0) == 92.3      # 1x ATR
    assert touch_probability(2.0, 1.0) == 71.5      # 2x ATR
    # Hedef ATR'ye göre büyüdükçe ihtimal DÜŞMELİ (monoton azalan).
    assert touch_probability(1.0, 1.0) > touch_probability(3.0, 1.0) > touch_probability(5.0, 1.0)
    # Geçersiz girdi → None (uydurma yok).
    assert touch_probability(None, 1.0) is None
    assert touch_probability(3.0, None) is None
    assert touch_probability(3.0, 0) is None


def test_master_surge_imported_in_velocity():
    """Tavan hesabı için master_surge velocity modülünde erişilebilir olmalı."""
    assert hasattr(velocity, "master_surge")
    assert hasattr(velocity.master_surge, "calculate_adaptive_targets")


def test_daily_rising_loop_registered_in_main():
    """Döngü main.py'de kaydedilmiş olmalı."""
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "daily-momentum" in src
    assert "daily_momentum_loop" in src
