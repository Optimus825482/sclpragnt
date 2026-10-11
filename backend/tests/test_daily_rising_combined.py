"""KOMBİNE yükseliş döngüsü testleri (2026-10-11 kullanıcı kararı).

Kapsam:
- Config varsayılanları: kombine açık, TOP-3, eşik.
- DB yardımcıları mevcut (save/list/last/evaluate daily_rising_report).
- WhatsApp formatlayıcıları: format_combined_list / format_combined_status.
- Kombine motor: TÜM radar stratejileri tek taramada birleşir (velocity,
  günlük momentum, short-squeeze, jump/early/rising füzyon, Master Surge).
- Kalite eşiği: en iyi puan eşiğin altındaysa gönderilmez.
- Eski gönderim yolları KALDIRILDI (11:30 raporu / 30 dk takip / slot döngüsü).
- main.py yalnız `daily_rising_combined_loop` kaydeder (tek kanal).
- Yeni özet ucu kaynak (strateji) kırılımı döndürür.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import database  # noqa: E402


def test_combined_config_defaults():
    c = config.config
    assert c.COMBINED_RISING_ENABLED is True
    assert c.COMBINED_RISING_TOP_N == 3
    assert c.COMBINED_RISING_MIN_SCORE == 10.0
    # Eski slot ayarları KALDIRILDI.
    assert not hasattr(c, "DAILY_RISING_SLOT_ENABLED")
    assert not hasattr(c, "DAILY_RISING_SLOT_MIN_SCORE")


def test_combined_settings_from_db_not_env():
    """Kullanıcı isteği (2026-10-11): kombine ayarlar env DEĞİL Ayarlar sayfasından
    (DB) yönetilir. `get_user_notification_settings` kombine alanları okur,
    PUT yazabilir ve döngü `combined_rising_settings()` ile okur."""
    import inspect
    from app.routers import monitoring
    get_src = inspect.getsource(monitoring.get_user_notification_settings)
    put_src = inspect.getsource(monitoring.update_monitoring_settings)
    for key in ("combined_rising_enabled", "combined_rising_top_n",
                "combined_rising_min_score", "combined_rising_start_hour",
                "combined_rising_end_hour", "combined_rising_list_min",
                "combined_rising_track_min"):
        assert key in get_src, f"okuma alanı eksik: {key}"
        assert key in put_src, f"yazma alanı eksik: {key}"
    assert hasattr(monitoring, "combined_rising_settings")
    loop_src = inspect.getsource(monitoring.daily_rising_combined_loop)
    assert "combined_rising_settings" in loop_src
    assert "config.COMBINED_RISING" not in loop_src  # env değil, ayar okunur


def test_combined_settings_read_floats_validate():
    """YAZMA yolu geçersiz girdi → 422; OKUMA yolu bozuk değeri kırpar (fırlatmaz)."""
    from app.routers import monitoring
    assert monitoring._clamp_int("abc", 1, 10) == 1
    assert monitoring._clamp_int(99, 1, 10) == 10
    assert monitoring._clamp_float("x", 0.0, 100.0) == 0.0
    assert monitoring._coerce_setting_bool("acik") is True
    assert monitoring._coerce_setting_bool("kapali") is False


def test_report_db_helpers_exist():
    for name in ("save_daily_rising_report", "list_daily_rising_reports",
                 "last_daily_rising_report", "evaluate_daily_rising_report"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_format_combined_list_fields():
    """Kombine liste: coin · fiyat · ihtimal · miktar · potansiyel · puan."""
    from app.whatsapp_notify import format_combined_list
    rows = [
        {"symbol": "OGNTRY", "price": 0.102, "target_probability": 62.0,
         "ceiling_pct": 4.0, "potential_pct": 18.0, "scan_score": 74.3,
         "strategy": "combined"},
    ]
    out = format_combined_list(rows, n=3)
    assert "OGN" in out
    assert "%62" in out            # ihtimal
    assert "+%4" in out            # miktar (ceiling)
    assert "+%18" in out           # potansiyel
    assert "74" in out             # puan
    assert "İHTİMAL" in out and "PUAN" in out


def test_format_combined_list_limits_top_n_and_empty():
    from app.whatsapp_notify import format_combined_list
    rows = [{"symbol": f"S{i}TRY", "price": i + 1, "scan_score": 50 - i} for i in range(6)]
    out = format_combined_list(rows, n=3)
    assert "S0" in out and "S2" in out
    assert "S3" not in out
    assert "aday bulunamadı" in format_combined_list([])


def test_format_combined_status_avg_and_sort():
    from app.whatsapp_notify import format_combined_status
    rows = [
        {"symbol": "AAATRY", "entry_price": 1.0, "current_price": 1.02, "change_pct": 2.0},
        {"symbol": "BBBTRY", "entry_price": 1.0, "current_price": 0.96, "change_pct": -4.0},
        {"symbol": "CCCTRY", "entry_price": 1.0, "current_price": 1.0, "change_pct": 0.0},
    ]
    out = format_combined_status(rows, title="T", baseline_label="12:00")
    assert "ORT. DEĞİŞİMİ" in out
    # (2.0 - 4.0 + 0.0) / 3 = -0.67
    assert "-0.67%" in out
    # En çok yükselen üstte
    assert out.index("AAA") < out.index("BBB")


def test_combined_scan_merges_all_strategies():
    """Kombine motor kaynağı: velocity + günlük momentum + short-squeeze + füzyon
    (jump/early/rising) + Master Surge hepsini TEK taramada birleştirir."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._combined_scan_rows)
    assert "detect_velocity_candidates" in src
    assert "_daily_momentum_candidates" in src
    assert "_short_squeeze_candidates" in src
    assert "enrich_candidates" in src          # jump/early/rising füzyonu + Master Surge
    assert "_compute_potential" in src
    assert "scan_score" in src
    assert "calculate_adaptive_targets" in src  # hedef/miktar


def test_combined_scan_score_prefers_unified():
    from app.routers import monitoring as mo
    assert mo._combined_scan_score({"scan_score": 71.2}) == 71.2
    assert mo._combined_scan_score({"unified_score": 55.0}) == 55.0


def test_send_combined_list_quality_gate():
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._send_combined_list)
    assert 'cfg.get("min_score"' in src
    assert 'cfg.get("top_n"' in src
    assert "format_combined_list" in src
    assert "save_daily_rising_report" in src


def test_send_combined_status_uses_notify_price():
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._send_combined_status)
    assert "COMBINED_LIST_KIND" in src
    assert "notify_price" in src
    assert "format_combined_status" in src


def test_combined_loop_replaces_legacy_loops():
    """Eski döngüler modülden kaldırıldı; yalnız kombine döngü var."""
    from app.routers import monitoring as mo
    assert hasattr(mo, "daily_rising_combined_loop")
    for gone in ("daily_rising_slot_loop", "daily_rising_hourly_loop",
                 "_send_slot_report", "_send_delta_report", "_slot_scan_rows"):
        assert not hasattr(mo, gone), f"eski fonksiyon hâlâ var: {gone}"


def test_main_registers_only_combined_loop():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "daily_rising_combined_loop" in src
    assert "daily-rising-combined" in src
    assert "daily_rising_slot_loop" not in src
    assert "daily_rising_hourly_loop" not in src


def test_combined_send_endpoints_registered():
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/daily-rising/send-slot-report" in paths    # artık kombine liste
    assert "/api/daily-rising/send-delta-report" in paths   # artık kombine durum
    assert "/api/daily-rising/reports/summary" in paths
    assert "/api/daily-rising/last-report" in paths


def test_send_slot_endpoint_routes_to_combined_list():
    """Tek kanal: /send-slot-report artık `_send_combined_list`, /send-delta-report
    `_send_combined_status` çağırır (admin kapılı)."""
    import inspect
    from app.routers import monitoring as mo
    slot_src = inspect.getsource(mo.daily_rising_send_slot_report)
    delta_src = inspect.getsource(mo.daily_rising_send_delta_report)
    assert "_send_combined_list" in slot_src and "require_admin" in slot_src
    assert "_send_combined_status" in delta_src and "require_admin" in delta_src


def test_reports_summary_has_source_breakdown():
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_reports_summary)
    for key in ("hit_rate", "ceiling_hits", "avg_mfe_pct", "reports", "by_source"):
        assert key in src, f"özet alanı eksik: {key}"
    assert "COMBINED_LIST_KIND" in src
    assert "evaluate_daily_rising_report" in src


def test_last_report_defaults_to_combined():
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_last_report)
    assert "COMBINED_LIST_KIND" in src
    assert "notify_price" in src
    assert "require_admin" not in src   # salt okunur, herkese açık


def test_legacy_momentum_scan_no_whatsapp():
    """11:30 taraması artık gruba mesaj ATMAMALI (tek kanal kombine)."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._daily_momentum_scan_once)
    assert "send_whatsapp" not in src
