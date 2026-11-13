"""Regresyon: canlı log bulguları (2026-11-10).

1. `notification_plan.BUILD_TIMEOUT_SEC` REST tavanının ALTINDA olamaz.
   Canlıda sürekli `plan kurulamadı: TimeoutError()` görülüyordu; `_build`
   iki gerçek REST çağrısı yapar ve her biri `REST_TIMEOUT_SEC` (15s) kadar
   bekleyebilir. 2 saniyelik bütçe plan üretimini fiilen öldürüyordu.

2. Push teslim edilemediğinde `reason` MUTLAKA dolu olmalı. Aksi halde
   çağıran taraf yalnız "gönderilemedi" yazar ve kök neden görünmez.
"""
import asyncio
import inspect

import pytest

from app import alerting, binance_tr_public, notification_plan


def test_plan_budget_above_rest_ceiling():
    """Plan bütçesi en az bir REST çağrısını tamamlayabilmeli.

    `_build` İKİ sıralı çağrı yapar (depth + ticker_24h), yani pratikte
    bütçe >= 2 * REST_TIMEOUT_SEC olmalı. En azından REST tavanının altına
    düşmemesi sert kuraldır.
    """
    assert notification_plan.BUILD_TIMEOUT_SEC >= binance_tr_public.REST_TIMEOUT_SEC, (
        f"plan bütçesi {notification_plan.BUILD_TIMEOUT_SEC}s < REST tavanı "
        f"{binance_tr_public.REST_TIMEOUT_SEC}s → plan üretimi hep zaman aşımına düşer"
    )


def _module_source() -> str:
    """Modülün GERÇEK kaynağı.

    `inspect.getsource(notification_plan.build_plan)` kullanılamaz: conftest bu
    fonksiyonu AsyncMock ile değiştiriyor (gerçek plan testleri işaretli).
    """
    import pathlib

    return pathlib.Path(notification_plan.__file__).read_text(encoding="utf-8")


def test_plan_timeout_logged_separately():
    """Zaman aşımı, genel hatadan AYRI ve anlaşılır loglanmalı (kaynak sözleşmesi)."""
    src = _module_source()
    assert "asyncio.TimeoutError" in src, "zaman aşımı özel yakalanmıyor"
    assert "bütçesi aşıldı" in src, "zaman aşımı için açıklayıcı mesaj yok"


def test_build_fetches_twice_justifying_budget():
    """Bütçe gerekçesi: `_build` gerçekten iki REST çağrısı yapıyor.

    Bu iddia kırılırsa (tek çağrıya inerse) bütçe yeniden gözden geçirilmeli.
    """
    src = inspect.getsource(notification_plan._build)
    assert "depth(" in src and "ticker_24h(" in src


def test_push_without_subscriptions_reports_reason(monkeypatch):
    """Abonelik yoksa `ok=False` VE `reason='no_subscriptions'` dönmeli."""
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "dummy-key")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")

    async def _no_subs(usernames=None):
        return []

    monkeypatch.setattr(alerting.database, "list_push_subscriptions", _no_subs)

    res = asyncio.run(alerting.deliver_web_push("mesaj", title="t", symbol="BTCTRY"))
    assert res["ok"] is False
    assert res.get("reason") == "no_subscriptions", f"reason eksik: {res}"
    assert res.get("skipped") is True


def test_push_result_always_has_reason_when_not_ok():
    """Kaynak sözleşmesi: `ok=False` yollarının TAMAMI reason yazmalı."""
    src = inspect.getsource(alerting.deliver_web_push)
    for reason in ("no_subscriptions", "all_subscriptions_dead", "delivery_failed",
                   "daily_symbol_limit", "vapid_not_configured"):
        assert reason in src, f"'{reason}' reason'ı üretilmiyor"


def test_send_push_logs_reason():
    """`_send_push` başarısızlıkta nedeni loglamalı (kör uyarı yasak)."""
    from app.routers import monitoring

    src = inspect.getsource(monitoring._send_push)
    assert "push_skip_reason" in src, "başarısız push'ta neden loglanmıyor"
