"""2026-10-20: MA kesişim BUY sinyali M30 ve H1'de de üretilir, bildirilir ve otonom paper açar."""
import pytest

from app import ma_buy_notify as notify, ma_buy_tracker as tracker
from app.config import config


def test_tracker_supports_30m_and_1h_bar_lengths():
    assert tracker.SUPPORTED_TF_MS["30m"] == 1_800_000
    assert tracker.SUPPORTED_TF_MS["1h"] == 3_600_000


def test_tracker_timeframes_keep_30m_and_1h(monkeypatch):
    monkeypatch.setattr(config, "MA_BUY_TIMEFRAMES", "1m,5m,15m,30m,1h", raising=False)
    assert tracker.timeframes() == ["1m", "5m", "15m", "30m", "1h"]


def test_default_scan_timeframes_include_30m_and_1h_and_notify_excludes_30m_1m():
    """Replay 2026-10-20: M1 medyan MFE %0,19 (komisyon alti) -> sinyal + paper kapali; M30 acik."""
    tfs = {t.strip() for t in str(getattr(config, "MA_BUY_TIMEFRAMES")).split(",")}
    assert {"30m", "1h"} <= tfs, "MA_BUY_TIMEFRAMES"
    assert "1m" not in tfs, "MA_BUY_TIMEFRAMES"
    # 2026-10-26: M30 push'u kaldirildi; bildirim listesinde 1h var, 30m yok ve 1m yok.
    notify_tfs = {t.strip() for t in str(getattr(config, "MA_BUY_NOTIFY_TIMEFRAMES")).split(",")}
    assert "1h" in notify_tfs, "MA_BUY_NOTIFY_TIMEFRAMES"
    assert "30m" not in notify_tfs and "1m" not in notify_tfs, "MA_BUY_NOTIFY_TIMEFRAMES"


def test_signals_from_bars_on_1h_closes_bar_one_hour_after_open():
    closes = [100.0 - i * 0.01 for i in range(100)] + [99.0 + i * 0.5 for i in range(30)]
    bars = [{"open_ms": i * 3_600_000, "close_ms": (i + 1) * 3_600_000 - 1, "open": c, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]
    rows = tracker.signals_from_bars("BTCTRY", "1h", bars, now_ms=10 ** 12, lookback=len(bars), per=(7, 20, 99),
                                     use_sma=True, stoch_max=None)
    assert rows, "sentetik seride en az bir BUY kesişimi beklenir"
    assert all(r["timeframe"] == "1h" and r["bar_close_ms"] - r["bar_open_ms"] == 3_600_000 for r in rows)


def test_notify_timeframe_setting_accepts_30m_and_1h_in_canonical_order():
    assert notify.normalize_setting("ma_buy_notify_timeframes", "1h,30m,5m") == "5m,30m,1h"


def test_target_setting_accepts_30m_and_1h():
    assert notify.normalize_setting("ma_buy_target_pct", "30m:2.5,1h:3") == "30m:2.5,1h:3"


def test_default_targets_for_30m_and_1h():
    assert notify.target_pct("30m") == 2.5
    assert notify.target_pct("1h") == 3.0


@pytest.mark.parametrize("tf,minutes,label", [("30m", 30, "M30"), ("1h", 60, "H1"), ("5m", 5, "M5")])
def test_tf_minutes_and_label(tf, minutes, label):
    assert notify._tf_minutes(tf) == minutes
    assert notify.tf_label(tf) == label
