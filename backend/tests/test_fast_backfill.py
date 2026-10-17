"""2026-10-17: hızlı kline geri doldurma — saf yardımcılar ve taker satır eşlemesi."""
from scripts.backfill_historical_candles import kline_to_row
from scripts.fast_backfill_klines import WeightGate, pages


def test_pages_cover_window_in_1000_bar_chunks():
    bar = 60_000
    ps = pages(0, 2499 * bar, bar)
    assert ps[0] == (0, 999 * bar) and ps[1][0] == 1000 * bar and ps[-1][1] == 2499 * bar
    assert sum((b - a) // bar + 1 for a, b in ps) == 2500
    assert pages(10, 5, bar) == []


def test_kline_row_carries_taker_columns_and_skips_open_bar():
    k = [0, "1", "2", "0.5", "1.5", "100", 59_999, "150", 7, "40", "60", "0"]
    row = kline_to_row("ADATRY", "1m", k, "backfill", 1.0, now_ms=10 ** 12)
    assert row[-2:] == (40.0, 60.0) and row[9] == 150.0
    assert kline_to_row("ADATRY", "1m", k, "backfill", 1.0, now_ms=59_999) is None  # kapanmamış
    old = k[:9]  # 9 kolonlu eski yanıt
    assert kline_to_row("ADATRY", "1m", old, "backfill", 1.0, now_ms=10 ** 12)[-2:] == (None, None)


def test_weight_gate_pauses_over_limit():
    g = WeightGate(100)
    g.observe(50)
    assert g.pause_until == 0.0
    g.observe(120)
    assert g.pause_until > 0
