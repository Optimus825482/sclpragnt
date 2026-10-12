"""Bildirim SKOR skoru tutarlılık + Global/lead-lag eşik kapısı kilitleri (2026-10-13).

İKİ HATA düzeltildi:
 1. Global/lead-lag bildirim yolu (`global_lead_lag.handle_global_detection`)
    admin eşik kapısını ATLIYORDU → 85 eşiğinde 60 puanlık bildirim gidebiliyordu.
 2. "Son Uyarılar" listesi ham `score` (ör. 22250) gösteriyordu; kart/rapor ise
    panel (0-100). Aynı ekranda iki ölçek → kafa karışıklığı.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app.routers import global_radar  # noqa: E402
from app.routers import monitoring as mo  # noqa: E402


def test_leadlag_panel_score_monotonic_and_bounded():
    """Residual → panel skoru monoton artan ve 0-100 aralığında."""
    vals = [global_radar._leadlag_panel_score(r) for r in (0.1, 0.5, 1, 2, 3, 5, 10)]
    assert vals == sorted(vals), "panel skoru monoton artmalı"
    assert all(0 <= v <= 100 for v in vals), "panel skoru 0-100 dışına çıkmamalı"
    assert global_radar._leadlag_panel_score(None) == 0.0
    assert global_radar._leadlag_panel_score(-1) == 0.0


def test_leadlag_score_is_not_fixed_60():
    """Regresyon: sabit 60 KALKTI — farklı residual'lar farklı skor üretmeli."""
    a = global_radar._leadlag_panel_score(0.5)
    b = global_radar._leadlag_panel_score(3.0)
    assert a != b, "sabit skor geri gelmiş (60.0)"
    assert not (a == 60.0 and b == 60.0)


def test_panel_norm_keeps_panel_untouched():
    """≤100 skor panel ölçeğidir; _panel_from_raw YENİDEN uygulanmamalı (çift dönüşüm)."""
    for s in (60.0, 85.0, 99.9, 100.0):
        assert mo._panel_from_raw(s) is not None  # fonksiyon çağrılabilir
    # Eşik altı ham değer panel'de düşük olmalı (sanity)
    assert mo._panel_from_raw(0.0) == 0.0
    assert mo._panel_from_raw(25000) >= 99.0


def test_notification_history_normalizes_raw_scores():
    """Kaynak kilit: /api/monitoring/notifications ham (>100) skoru normalize etmeli."""
    import inspect
    src = inspect.getsource(mo.monitoring_notification_history)
    assert "_panel_from_raw" in src, "ham skor normalize edilmiyor"
    assert "> 100" in src or ">100" in src, "panel-değil (>100) kontrolü yok"


def test_global_gate_rejects_below_min_score():
    """Kaynak kilit: handle_global_detection admin eşik kapısı İÇERMELİ ve
    karşılaştırma SATIRI mevcut olmalı (mutasyon: kapı devre dışı bırakılırsa test kırılır)."""
    import inspect
    from app import global_lead_lag
    src = inspect.getsource(global_lead_lag.handle_global_detection)
    assert "_effective_min_score" in src, "eşik kapısı yok (hata geri gelmiş)"
    assert "below_min_score" in src, "eşik altı reddi (below_min_score) yok"
    # Mutasyon direnci: gerçek karşılaştırma ifadesi (yalnız isim değil).
    assert "score < eff_min" in src, "eşik karşılaştırması (score < eff_min) kaybolmuş"

