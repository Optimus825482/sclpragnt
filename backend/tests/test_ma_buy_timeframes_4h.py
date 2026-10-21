"""2026-10-21: MA kesişim BUY sinyali H4'te de üretilir, bildirilir ve otonom paper açar; kayıtlı ayarlara tek seferlik eklenir."""
import pytest

from app import ma_buy_notify as notify, ma_buy_tracker as tracker
from app.config import config


def test_tracker_supports_4h_bar_length_and_fetch_limit_covers_slow_ma():
    assert tracker.SUPPORTED_TF_MS["4h"] == 14_400_000
    assert tracker.FETCH_LIMIT >= 99 + int(getattr(config, "MA_BUY_LOOKBACK_BARS", 3)) + 2


def test_default_scan_and_notify_timeframes_include_4h():
    for attr in ("MA_BUY_TIMEFRAMES", "MA_BUY_NOTIFY_TIMEFRAMES"):
        assert "4h" in {t.strip() for t in str(getattr(config, attr)).split(",")}, attr
    assert tracker.timeframes()[-1] == "4h"


def test_signals_from_bars_on_4h_closes_bar_four_hours_after_open():
    closes = [100.0 - i * 0.01 for i in range(100)] + [99.0 + i * 0.5 for i in range(30)]
    bars = [{"open_ms": i * 14_400_000, "close_ms": (i + 1) * 14_400_000 - 1, "open": c, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]
    rows = tracker.signals_from_bars("BTCTRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(7, 20, 99),
                                     use_sma=True, stoch_max=None)
    assert rows, "sentetik seride en az bir BUY kesişimi beklenir"
    assert all(r["timeframe"] == "4h" and r["bar_close_ms"] - r["bar_open_ms"] == 14_400_000 for r in rows)


def test_notify_settings_accept_4h():
    assert notify.normalize_setting("ma_buy_notify_timeframes", "4h,1h,5m") == "5m,1h,4h"
    assert notify.normalize_setting("ma_buy_target_pct", "4h:4") == "4h:4"
    with pytest.raises(ValueError):
        notify.normalize_setting("ma_buy_notify_timeframes", "8h")


def test_default_target_minutes_and_label_for_4h():
    assert notify.target_pct("4h") == 10.0
    assert notify._tf_minutes("4h") == 240
    assert notify.tf_label("4h") == "H4"


def test_enable_timeframe_once_adds_4h_to_saved_settings_only_once():
    persisted = {"ma_buy_notify_timeframes": "5m,15m,30m,1h", "ma_buy_target_pct": "5m:1.5,1h:3"}
    assert notify.enable_timeframe_once(persisted) is True
    assert persisted["ma_buy_notify_timeframes"] == "5m,15m,30m,1h,4h"
    assert persisted["ma_buy_target_pct"] == "5m:1.5,1h:3,4h:10"
    assert persisted[notify.H4_MIGRATION_MARK] is True
    persisted["ma_buy_notify_timeframes"] = "5m,15m"          # kullanıcı sonradan bilerek kaldırdı
    assert notify.enable_timeframe_once(persisted) is False   # işaret var → dokunma
    assert persisted["ma_buy_notify_timeframes"] == "5m,15m"


def test_enable_timeframe_once_without_saved_timeframes_only_marks():
    persisted = {"top_gainers_limit": 50}
    assert notify.enable_timeframe_once(persisted) is True    # işaret yazılır, varsayılan (4h dahil) zaten geçerli
    assert "ma_buy_notify_timeframes" not in persisted and persisted[notify.H4_MIGRATION_MARK] is True
