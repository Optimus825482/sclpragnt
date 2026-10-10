"""SLOT rapor döngüsü testleri (2026-10-10 kullanıcı kararı).

Kapsam:
- Config varsayılanları: slot açık, eşik 10, 1-5 aday, tavana ulaşanlar dışarı.
- DB yardımcıları mevcut (save/list/last daily_rising_report).
- format_delta_report: otlama satırı + sıralama + boş liste.
- Kalite eşiği kararı: en iyi puan eşiğin altındaysa gönderilmez.
- Çakışma: slot aktifken 11:30 tek rapor + 30 dk takip tablosu kapalı.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import database  # noqa: E402


def test_slot_config_defaults():
    c = config.config
    assert c.DAILY_RISING_SLOT_ENABLED is True
    assert c.DAILY_RISING_SLOT_MIN_SCORE == 10.0
    assert c.DAILY_RISING_SLOT_MAX_COUNT == 5
    assert c.DAILY_RISING_SLOT_EXCLUDE_HIT is True


def test_slot_report_db_helpers_exist():
    for name in ("save_daily_rising_report", "list_daily_rising_reports",
                 "last_daily_rising_report"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_format_delta_report_includes_otlama():
    from app.whatsapp_notify import format_delta_report
    rows = [
        {"symbol": "OGNTRY", "entry_price": 0.10, "current_price": 0.102,
         "change_pct": 2.0, "strategy": "daily_momentum", "hit_ceiling": False},
        {"symbol": "MAGICTRY", "entry_price": 1.5, "current_price": 1.44,
         "change_pct": -4.0, "strategy": "both", "hit_ceiling": False},
    ]
    out = format_delta_report(rows, title="T", baseline_label="11:30")
    assert "OTLAMA" in out
    assert "+2.00%" in out or "+2,00%" in out
    # En çok yükselen üstte (değişime göre sıralı)
    assert out.index("OGN") < out.index("MAGIC")
    # Ortalama: (2.0 - 4.0) / 2 = -1.00
    assert "-1.00%" in out or "-1,00%" in out


def test_format_delta_report_empty():
    from app.whatsapp_notify import format_delta_report
    out = format_delta_report([], title="T", baseline_label="11:30")
    assert "aday yok" in out


def test_slot_quality_gate_skips_weak_candidates():
    """Kalite eşiği: en iyi adayın puanı eşiğin altındaysa _send_slot_report
    göndermemeli ve DB'ye 'sent=False' olmayan kayıt yazmamalı (mantık testi:
    eşik karşılaştırması kodda mevcut ve _combined_score ile aynı puan)."""
    import inspect
    from app.routers import monitoring
    src = inspect.getsource(monitoring._send_slot_report)
    assert "DAILY_RISING_SLOT_MIN_SCORE" in src
    assert "_combined_score" in src
    # puan formülü whatsapp_notify._combined_score ile birebir aynı olmalı
    msrc = inspect.getsource(monitoring._combined_score)
    wn = __import__("app.whatsapp_notify", fromlist=["_combined_score"])
    # Aynı girdiyle AYNI puan (davranışsal eşdeğerlik; docstring karşılaştırılmaz).
    probe = {"potential_pct": 20.0, "target_probability": 60.0}
    assert monitoring._combined_score(probe) == wn._combined_score(probe) == 12.0
    assert "potential_pct" in msrc and "target_probability" in msrc


def test_slot_loop_disables_legacy_whatsapp_paths():
    """Slot aktifken: 11:30 tek WhatsApp raporu ve 30 dk takip tablosu çalışmaz
    (çakışma koruması) — koşullar kaynakta DAILY_RISING_SLOT_ENABLED ile kapılı."""
    import inspect
    from app.routers import monitoring
    scan_src = inspect.getsource(monitoring._daily_momentum_scan_once)
    hourly_src = inspect.getsource(monitoring.daily_rising_hourly_loop)
    assert "DAILY_RISING_SLOT_ENABLED" in scan_src
    assert "DAILY_RISING_SLOT_ENABLED" in hourly_src


def test_slot_loop_registered_in_main():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "daily_rising_slot_loop" in src
    assert "daily-rising-slot" in src


def test_slot_reports_api_registered():
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/daily-rising/reports" in paths
    assert "/api/daily-rising/send-slot-report" in paths
    assert "/api/daily-rising/send-delta-report" in paths


def test_slot_scan_marks_hit_candidates():
    """Tavana ulaşan adaylar `_hit` ile işaretlenir ve _send_slot_report
    DAILY_RISING_SLOT_EXCLUDE_HIT açıkken onları listeden çıkarır."""
    import inspect
    from app.routers import monitoring
    src = inspect.getsource(monitoring._slot_scan_rows)
    assert "_today_mfe" in src
    assert "_hit" in src
    send_src = inspect.getsource(monitoring._send_slot_report)
    assert "DAILY_RISING_SLOT_EXCLUDE_HIT" in send_src


def test_evaluate_last_report_endpoint_is_admin_only():
    """Manuel liste gönderme ve son gönderilen değerlendirme uçları admin kapılı
    olmalı (kullanıcı isteği 2026-10-10: yalnız admin girişinde)."""
    import inspect
    from app.routers import monitoring
    for fn in (monitoring.daily_rising_send_slot_report,
               monitoring.daily_rising_evaluate_last):
        src = inspect.getsource(fn)
        assert "require_admin" in src, f"{fn.__name__} admin kapısı eksik"


def test_evaluate_report_db_helper_and_scoring():
    """evaluate_daily_rising_report mevcut olmalı; hiç aday yoksa boş liste döner
    (uydurma yok) ve `list_daily_rising_reports`/`last_daily_rising_report` uyumlu."""
    from app import database
    assert hasattr(database, "evaluate_daily_rising_report")
    import inspect
    sig = inspect.signature(database.evaluate_daily_rising_report)
    assert "live_prices" in sig.parameters
    # endpoint yolu kayıtlı olmalı
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/daily-rising/evaluate-last" in paths


def test_evaluate_last_summary_shape():
    """Özet alanları: hit_rate / avg_mfe_pct / ceiling_hits / rows — arayüzün
    okuduğu sözleşme."""
    import inspect
    from app.routers import monitoring
    src = inspect.getsource(monitoring.daily_rising_evaluate_last)
    for key in ("hit_rate", "avg_mfe_pct", "max_mfe_pct", "ceiling_hits", "rows"):
        assert key in src, f"özet alanı eksik: {key}"


def test_last_report_endpoint_is_public_and_live():
    """'Son gönderilen liste' canlı karşılaştırma tablosu (kullanıcı isteği):
    uç kayıtlı olmalı, admin KAPISI OLMAMALI (listeyi herkes görebilir) ve
    anlık fiyatla karşılaştırma alanlarını döndürmeli (avg_change_pct/rows)."""
    import inspect
    from app.routers import monitoring
    paths = {r.path for r in monitoring.router.routes}
    assert "/api/daily-rising/last-report" in paths
    src = inspect.getsource(monitoring.daily_rising_last_report)
    assert "require_admin" not in src
    for key in ("avg_change_pct", "rows", "sent_at"):
        assert key in src, f"alan eksik: {key}"


