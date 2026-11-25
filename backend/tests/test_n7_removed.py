"""N7 saatlik taraması kaldırıldı (2026-11-25, kullanıcı isteği).

Kural: varsayılan kapalı; döngü başlamaz, push/otonom paper üretmez.
"""
import inspect

from app.config import config
from app import main


def test_n7_disabled_by_default():
    assert config.N7_HOURLY_ENABLED is False
    assert config.N7_AUTO_PAPER_ENABLED is False


def test_n7_loop_only_starts_when_enabled():
    src = inspect.getsource(main.startup_services)
    assert "N7_HOURLY_ENABLED" in src
    assert "_start_background(n7_hourly_loop" in src
