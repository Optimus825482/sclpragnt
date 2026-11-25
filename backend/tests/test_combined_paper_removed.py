"""Kombine Paper kaldırıldı (2026-11-25, kullanıcı isteği).

Kural: varsayılan KAPALI → yönetim döngüsü başlamaz, liste gönderimi işlem
açmaz. Kodu tümden silmek yerine anahtar kullanıldı (geri açmak kolay).
"""
import inspect

from app.config import config
from app import main
from app.routers import monitoring


def test_combined_paper_disabled_by_default():
    assert config.COMBINED_PAPER_ENABLED is False


def test_loop_only_starts_when_enabled():
    src = inspect.getsource(main.startup_services)
    assert "COMBINED_PAPER_ENABLED" in src
    assert "_start_background(combined_paper_management_loop" in src


def test_list_send_hook_is_gated():
    """`on_combined_list_sent` yalnız anahtar açıkken çağrılmalı."""
    import app.routers.monitoring as m
    src = inspect.getsource(m)
    idx = src.index("on_combined_list_sent")
    window = src[max(0, idx - 400):idx]
    assert "COMBINED_PAPER_ENABLED" in window
