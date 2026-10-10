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


def test_whatsapp_send_endpoints_registered():
    """WhatsApp elle-gönderim + durum uçları kayıtlı olmalı."""
    from app.routers import monitoring
    paths = {getattr(r, "path", "") for r in monitoring.router.routes}
    assert "/api/daily-rising/send-report" in paths
    assert "/api/daily-rising/send-tracking" in paths
    assert "/api/daily-rising/whatsapp-status" in paths


def test_send_report_reads_1130_snapshot_not_fresh_scan():
    """Kullanıcı kararı: '11:30 Raporu' butonu TAZE tarama yapmaz; bugün 11:30'da
    kaydedilen anlık görüntüyü (DB) gönderir. Kaynak kodda yeni velzi taraması
    (detect_velocity_candidates / _short_squeeze_candidates) OLMAMALI."""
    import inspect
    from app.routers import monitoring
    src = inspect.getsource(monitoring.daily_rising_send_report)
    assert "detect_velocity_candidates" not in src
    assert "_short_squeeze_candidates" not in src
    assert "_today_scan_rows" in src        # DB anlık görüntüsünden okur


def test_today_rising_rows_helper_exists():
    """Rapor ve takip ucu AYNI bugün penceresini kullanmalı (aynı ilk 5)."""
    from app.routers import monitoring
    assert hasattr(monitoring, "_today_rising_rows")
    assert hasattr(monitoring, "_today_scan_rows")
    import inspect
    assert inspect.iscoroutinefunction(monitoring._today_rising_rows)


def test_today_rising_rows_filters_previous_day(monkeypatch):
    """`days=1.0` penceresi dünü de kapsayabilir; yardımcı yalnız BUGÜNÜ döndürmeli."""
    import asyncio
    import time
    from app.routers import monitoring

    now = time.time()
    rows = [
        {"symbol": "TODAYTRY", "created_at": now, "atr_pct": 1.0, "ceiling_pct": 3.0},
        {"symbol": "OLDTRY", "created_at": now - 2 * 86400, "atr_pct": 1.0, "ceiling_pct": 3.0},
    ]

    async def _fake_list(limit=100, days=7.0):
        return list(rows)
    monkeypatch.setattr(monitoring.database, "list_daily_rising", _fake_list)

    today = asyncio.run(monitoring._today_rising_rows(limit=100))
    syms = [r["symbol"] for r in today]
    assert "TODAYTRY" in syms
    assert "OLDTRY" not in syms        # dün/önceki gün süzüldü
    scan = asyncio.run(monitoring._today_scan_rows())
    assert [c["symbol"] for c in scan] == ["TODAYTRY"]
    assert scan[0]["target_probability"] is not None   # ihtimal yeniden üretildi


def test_short_squeeze_scan_exists_and_classifies():
    """Toplu squeeze taraması + sınıflandırma mevcut olmalı."""
    from app import derivatives_service as ds
    assert hasattr(ds, "scan_short_squeeze")
    # negatif funding -> squeeze; pozitif -> değil (sınıflandırma mantığı)
    # (ağ çağrısı olmadan yalnız imza/varlık kontrolü)


def test_merge_candidates_dedupe_both():
    """Aynı sembol iki stratejide varsa strategy='both' olmalı."""
    from app.routers.monitoring import _merge_candidates
    mom = [{"symbol": "MINATRY", "velocity_score": 50, "strategy": "daily_momentum"}]
    sq = [{"symbol": "MINATRY", "velocity_score": 80, "strategy": "short_squeeze"},
          {"symbol": "XAITRY", "velocity_score": 60, "strategy": "short_squeeze"}]
    merged = _merge_candidates(mom, sq)
    by = {c["symbol"]: c for c in merged}
    assert by["MINATRY"]["strategy"] == "both"
    assert by["XAITRY"]["strategy"] == "short_squeeze"
    assert len(merged) == 2  # dedupe


def test_strategy_column_persisted():
    """save_daily_rising ve watchlist fonksiyonları strategy alanını taşımalı."""
    import inspect
    src = inspect.getsource(database.save_daily_rising)
    assert "strategy" in src
    src2 = inspect.getsource(database.add_to_user_daily_watchlist)
    assert "strategy" in src2


def test_potential_helper_exists():
    """Potansiyel üst sınır (fib/30g zirve) yardımcısı mevcut olmalı."""
    from app.routers import monitoring
    assert hasattr(monitoring, "_compute_potential")
    import inspect
    assert inspect.iscoroutinefunction(monitoring._compute_potential)


def test_potential_column_persisted():
    """potential_pct DB fonksiyonlarında taşınmalı (migration 009)."""
    import inspect
    assert "potential_pct" in inspect.getsource(database.save_daily_rising)
    assert "potential_pct" in inspect.getsource(database.add_to_user_daily_watchlist)


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
