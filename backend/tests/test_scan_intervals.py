"""Tarama aralıkları (2026-11-25, kullanıcı): süper tarama 90 sn, top-gainers 180 sn.

Neden: Binance TR ağırlığı acil seviyeye (1107/1200) çıkıyordu.
"""
from app.config import config


def test_super_scan_interval_is_90():
    assert config.SUPER_SCAN_INTERVAL_SEC == 90


def test_top_gainers_refresh_is_180():
    assert config.TOP_GAINERS_REFRESH_SEC == 180
