"""WhatsApp gönderimi kaldırıldı (2026-11-25, kullanıcı isteği).

Kural: hiçbir kanal mesaj göndermez; kod silinmedi (geri açmak kolay).
"""
import inspect

from app import whatsapp_notify
from app.routers import monitoring


def test_whatsapp_disabled_even_with_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NOTIFY_ENABLED", "true")
    assert whatsapp_notify.whatsapp_enabled() is False


def test_broadcast_is_noop():
    src = inspect.getsource(monitoring._broadcast_user_whatsapp)
    assert "return" in src
    # gövdede hiç gönderim çağrısı olmamalı (erken dönüş)
    body = src.split('"""', 2)[-1] if '"""' in src else src
    assert "send_whatsapp" not in body
