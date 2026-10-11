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
    # Kullanıcı kararı (2026-10-11): liste 20 dk, durum 5 dk.
    assert c.COMBINED_RISING_LIST_MIN == 20
    assert c.COMBINED_RISING_TRACK_MIN == 5
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
    assert "ORT. DEĞİŞİM" in out
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


def test_combined_quality_score_no_saturation():
    """Kullanıcı geri bildirimi (2026-10-11): güçlü adayların HEPSİ 100 puan
    görünüyordu. Yeni kalite puanı doygunluğa GİRMEZ (üst sınır 99) ve çok-kaynak
    teyidi + Master Surge katman sayısı ile AYRIŞIR."""
    from app.routers import monitoring as mo
    # Aynı velocity paneli, farklı teyit → farklı puan (ayırt edici).
    weak = {"velocity_score": 2000}
    strong = {"velocity_score": 2000,
              "unified_sources": ["velocity", "jump", "rising"],
              "master_surge": {"confluence_count": 4}}
    w_score, w_src, w_lyr = mo._combined_quality_score(weak)
    s_score, s_src, s_lyr = mo._combined_quality_score(strong)
    assert s_score > w_score
    assert w_src == 0 and w_lyr == 0
    assert s_src == 3 and s_lyr == 4
    # Tavan 99 — asla 100 değil (100 = "kesin" yanılgısı yok).
    extreme = {"velocity_score": 10_000_000,
               "unified_sources": ["velocity", "jump", "rising", "early"],
               "master_surge": {"confluence_count": 4}}
    assert mo._combined_quality_score(extreme)[0] <= 99.0
    assert mo._combined_quality_score(extreme)[0] != 100.0


def test_combined_quality_score_monotonic_in_confirmations():
    """Teyit arttıkça puan ARTAR (monoton) — sıralama bilgisi korunur."""
    from app.routers import monitoring as mo
    base = {"velocity_score": 5000}
    p0 = mo._combined_quality_score({**base})[0]
    p1 = mo._combined_quality_score({**base, "unified_sources": ["velocity"]})[0]
    p2 = mo._combined_quality_score({**base, "unified_sources": ["velocity", "jump"]})[0]
    assert p0 < p1 < p2


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


def test_combined_loop_first_attempt_db_cooldown_guarded():
    """Kullanıcı geri bildirimi (2026-10-11): restart spam'i — her deploy döngüyü
    'ilk çalıştırma' sanıp gruba liste atıyordu. Düzeltme: 'hemen ilk tarama'
    kararı BELLEĞE değil VERİTABANINA (son gönderim yaşı) dayanır. Döngü bir kez
    taze liste dener; gönderip göndermemeye `_send_combined_list` içindeki
    DB-cooldown karar verir (restart'ta zaten gönderilmişse atlar)."""
    import inspect
    from app.routers import monitoring as mo
    loop_src = inspect.getsource(mo.daily_rising_combined_loop)
    assert "startup_attempted" in loop_src
    assert "_send_combined_list" in loop_src
    send_src = inspect.getsource(mo._send_combined_list)
    # DB-temelli koruma: son gönderim yaşı periyotla karşılaştırılır.
    assert "last_daily_rising_report" in send_src
    assert "force" in send_src        # elle gönderim korumayı atlar
    assert "sent_at" in send_src


def test_status_send_has_restart_guard():
    """Durum takibi de DB-yaş kontrollü (restart'ta tekrar tekrar göndermez)."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._send_combined_status)
    assert "last_daily_rising_report" in src
    assert "COMBINED_STATUS_KIND" in src


def test_combined_loop_is_interval_based_not_clock_aligned():
    """Kullanıcı gözlemi (2026-10-11): '18:11'de gönderdi, bir daha göndermedi'.
    Kök neden takvim-hizalı slotlar + restart koruması çakışması. Düzeltme: döngü
    artık SAATE değil SON GÖNDERİM YAŞINA bakar (aralık bazlı)."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_combined_loop)
    # Aralık bazlı: son gönderim yaşı periyotla kıyaslanır.
    assert "list_age" in src and "status_age" in src
    assert "list_min * 60.0" in src and "track_min * 60.0" in src
    # Takvim-hizalı modulo slotları KALDIRILDI.
    assert "% list_min" not in src
    assert "combined_list_last" not in src


def test_status_last_before_next_shows_peak():
    """İstenen akış: bir SONRAKİ listeden önceki son durum bildiriminde adayların
    liste oluşturulduktan sonraki EN YÜKSEK değişimi (zirve) gösterilir."""
    import inspect
    from app.routers import monitoring as mo
    from app.whatsapp_notify import format_combined_status
    status_src = inspect.getsource(mo._send_combined_status)
    assert "is_last_before_next" in status_src
    assert "peak_pct" in status_src
    assert "show_peak" in status_src
    fmt_src = inspect.getsource(format_combined_status)
    assert "show_peak" in fmt_src and "ZİRVE" in fmt_src
    # Davranış: zirve verilince mesajda zirve sütunu/başlığı çıkar.
    rows = [{"symbol": "AAATRY", "entry_price": 1.0, "current_price": 1.01,
             "change_pct": 1.0, "peak_pct": 3.5}]
    out = format_combined_status(rows, title="T", baseline_label="12:00", show_peak=True)
    assert "ZİRVE" in out and "+3.50%" in out and "zirve" in out.lower()


def test_send_combined_list_skips_when_recent(monkeypatch):
    """GERÇEK davranış: son liste gönderimi tazeyse `_send_combined_list`
    tarama bile yapmadan False döner (restart spam'i ölür). force=True atlar."""
    import asyncio
    import time
    from app.routers import monitoring as mo

    async def _fresh(kind=mo.COMBINED_LIST_KIND):
        return {"id": 1, "kind": kind, "sent": True, "sent_at": time.time() - 30}

    monkeypatch.setattr(mo.database, "last_daily_rising_report", _fresh)
    # whatsapp_enabled True dönsün (köprü var sayılır).
    monkeypatch.setattr("app.whatsapp_notify.whatsapp_enabled", lambda: True)
    # Tarama çağrılırsa test patlar (erişilmemeli).
    async def _boom():
        raise AssertionError("tarama yapılmamalı — koruma önce devrede olmalı")
    monkeypatch.setattr(mo, "_combined_scan_rows", _boom)

    async def _cfg():
        return {"enabled": True, "top_n": 3, "min_score": 0.0, "list_min": 30,
                "track_min": 10, "start_hour": 0, "end_hour": 23}
    monkeypatch.setattr(mo, "combined_rising_settings", _cfg)

    # list_min=30 → eşik 30*60-60=1740 sn; 30 sn önce gönderim → ATLA.
    assert asyncio.run(mo._send_combined_list()) is False


def test_reports_summary_has_source_breakdown():
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_reports_summary)
    for key in ("hit_rate", "ceiling_hits", "avg_mfe_pct", "reports", "by_source"):
        assert key in src, f"özet alanı eksik: {key}"
    assert "COMBINED_LIST_KIND" in src
    assert "evaluate_daily_rising_report" in src


def test_reports_endpoints_exclude_legacy_slot():
    """Kullanıcı isteği (2026-10-11): raporlarda YALNIZ 3'lü sistem (combined_list
    + combined_status) görünsün; kaldırılan eski `slot`/`delta` kayıtları HARİÇ."""
    import inspect
    from app.routers import monitoring as mo
    summ = inspect.getsource(mo.daily_rising_reports_summary)
    # Varsayılan türler yalnız combined_list; eski "slot" varsayılana EKLENMEMELİ.
    assert '["slot"' not in summ and ", \"slot\"]" not in summ
    assert "COMBINED_LIST_KIND" in summ
    hist = inspect.getsource(mo.daily_rising_reports_list)
    assert "COMBINED_STATUS_KIND" in hist
    assert 'COMBINED_LIST_KIND, "slot"' not in hist


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
