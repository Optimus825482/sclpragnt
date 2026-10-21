"""Replay için canlı sembol seçimi (app/ma_buy_replay_universe.py, 2026-10-20): 24 sa yükselenler ilk N →
saatlik aktivite filtresi → MA izleyicinin taradığı küme. Saf; ağ/DB yok."""
from app import ma_buy_replay_universe as uni
from app.config import config

M5 = 300_000
M1 = 60_000


def _rows(start_ms, n, step_ms, price=10.0, vol=1000.0, quote=10_000.0, wiggle=0.01):
    """Binance kline satırı: [open_ms, o, h, l, c, v, close_ms, quote_vol]. `wiggle` ile her mum gerçek (H>L)."""
    out = []
    for i in range(n):
        p = price * (1 + 0.0001 * i)
        o = start_ms + i * step_ms
        out.append([o, p, p * (1 + wiggle), p * (1 - wiggle), p, vol, o + step_ms - 1, quote])
    return out


def test_closed_history_drops_open_bar_and_keeps_last_n():
    rows = _rows(0, 10, M5)
    h = uni.closed_history(rows, upto_ms=9 * M5 + 2_000, limit=5)   # 10. mum (açılış 9*M5) henüz kapanmadı; 1,5 sn saat payı
    assert len(h["closes"]) == 5
    assert h["timestamps"][-1] == 8 * M5


def test_ticker_stats_24h_change_and_quote_volume():
    rows = _rows(0, 300, M5, quote=1_000.0)   # 288 mum = 24 sa
    t = 299 * M5 + M5                          # 300. mum kapanmış
    stats = uni.ticker_stats(rows, t)
    assert stats["quote_volume"] == 288 * 1_000.0
    # 24 sa önceki kapanış = 12. mumun kapanışı (indeks 11) → fiyat 10*(1+0.0001*11); son = indeks 299
    expected = (10 * (1 + 0.0001 * 299)) / (10 * (1 + 0.0001 * 11)) * 100 - 100
    assert abs(stats["change_pct"] - expected) < 1e-9


def test_rank_top_gainers_by_change_then_volume():
    stats = {"A": {"change_pct": 5.0, "quote_volume": 1.0}, "B": {"change_pct": 5.0, "quote_volume": 9.0},
             "C": {"change_pct": 1.0, "quote_volume": 99.0}, "D": {"change_pct": -2.0, "quote_volume": 999.0}}
    assert uni.rank_top_gainers(stats, limit=3) == ["B", "A", "C"]


def _lively(n5=80, n1=150, end_ms=10 * 3_600_000):
    m5 = uni.closed_history(_rows(end_ms - n5 * M5, n5, M5, vol=100.0, wiggle=0.004), end_ms, 80)
    m1 = uni.closed_history(_rows(end_ms - n1 * M1, n1, M1, vol=20.0, wiggle=0.002), end_ms, 150)
    return m5, m1


def test_activity_warming_without_enough_5m_bars():
    m5 = uni.closed_history(_rows(0, 5, M5), 6 * M5, 80)
    assert uni.activity_status(m5, {}, quote_volume=5e6, now_ms=6 * M5)["status"] == "WARMING"


def test_activity_active_on_lively_symbol(monkeypatch):
    monkeypatch.setattr(config, "SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT", 0.0, raising=False)
    m5, m1 = _lively()
    st = uni.activity_status(m5, m1, quote_volume=5e6, now_ms=10 * 3_600_000)
    assert st["status"] == "ACTIVE", st


def test_activity_passive_when_quote_volume_below_threshold():
    m5, m1 = _lively()
    st = uni.activity_status(m5, m1, quote_volume=999_999.0, now_ms=10 * 3_600_000)
    assert st["status"] == "PASSIVE" and st["checks"]["quote_volume"] is False


def test_activity_passive_when_m1_candles_are_flat(monkeypatch):
    monkeypatch.setattr(config, "SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT", 0.0, raising=False)
    monkeypatch.setattr(config, "SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT", 4, raising=False)
    end = 10 * 3_600_000
    m5, _ = _lively(end_ms=end)
    flat_m1 = uni.closed_history(_rows(end - 150 * M1, 150, M1, wiggle=0.0), end, 150)   # H == L
    st = uni.activity_status(m5, flat_m1, quote_volume=5e6, now_ms=end)
    assert st["status"] == "PASSIVE" and st["checks"]["m1_flat_candles"] is False


def test_membership_uses_latest_snapshot_and_falls_back_to_tracked():
    timeline = [
        {"at_ms": 1_000, "active": {"A"}, "tracked": {"A", "B"}},
        {"at_ms": 5_000, "active": set(), "tracked": {"C"}},
    ]
    assert uni.membership_at(timeline, 999) == set()
    assert uni.membership_at(timeline, 1_000) == {"A"}
    assert uni.membership_at(timeline, 4_999) == {"A"}
    assert uni.membership_at(timeline, 6_000) == {"C"}      # aktif boş → izlenen listeye düşer (canlı davranış)


# --- hızlı yol: bir kez ayrıştır, ikili aramayla dilimle (uzun replay'lerde O(n) tarama yerine) -------------------

def test_history_upto_matches_closed_history():
    rows = _rows(0, 400, M5)
    parsed = uni.parse_rows(rows)
    for upto in (7 * M5 + 2_000, 123 * M5 + 2_000, 399 * M5 + 2_000, 10 ** 15):
        assert uni.history_upto(parsed, upto, 80) == uni.closed_history(rows, upto, 80)


def test_ticker_stats_series_matches_ticker_stats():
    rows = _rows(0, 600, M5, quote=250.0)
    parsed = uni.parse_rows(rows)
    marks = [300 * M5 + 2_000, 400 * M5 + 2_000, 599 * M5 + 2_000]
    series = uni.ticker_stats_series(parsed, marks)
    for t, got in zip(marks, series):
        exp = uni.ticker_stats(rows, t)
        assert abs(got["change_pct"] - exp["change_pct"]) < 1e-9 and got["quote_volume"] == exp["quote_volume"]


def test_ticker_stats_series_is_none_before_24h_of_history():
    parsed = uni.parse_rows(_rows(0, 100, M5))
    assert uni.ticker_stats_series(parsed, [50 * M5 + 2_000]) == [None]


# --- veritabanı arşivi (historical_candles) → kline satırı; 30m / 1h mumları 15m'den türetme ---------------------

def test_db_rows_to_klines_keeps_kline_layout():
    db = [{"open_time": 0, "close_time": 899_999, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0,
           "quote_volume": 15.0, "trade_count": 3}]
    rows = uni.db_rows_to_klines(db)
    assert rows == [[0, 1.0, 2.0, 0.5, 1.5, 10.0, 899_999, 15.0]]


def test_aggregate_klines_builds_exact_30m_bars_from_15m():
    r15 = [[0, 10, 12, 9, 11, 5, 899_999, 50], [900_000, 11, 15, 10, 14, 7, 1_799_999, 70],
           [1_800_000, 14, 16, 13, 13, 1, 2_699_999, 10], [2_700_000, 13, 13.5, 12, 12.5, 2, 3_599_999, 20]]
    r30 = uni.aggregate_klines(r15, 900_000, 1_800_000)
    assert r30 == [[0, 10, 15, 9, 14, 12, 1_799_999, 120], [1_800_000, 14, 16, 12, 12.5, 3, 3_599_999, 30]]


def test_aggregate_klines_skips_incomplete_buckets():
    r15 = [[900_000, 11, 15, 10, 14, 7, 1_799_999, 70],                     # kova 0'ın ilk 15m'i yok
           [1_800_000, 14, 16, 13, 13, 1, 2_699_999, 10], [2_700_000, 13, 13.5, 12, 12.5, 2, 3_599_999, 20],
           [3_600_000, 1, 1, 1, 1, 1, 4_499_999, 1]]                            # son kova eksik
    assert uni.aggregate_klines(r15, 900_000, 1_800_000) == [[1_800_000, 14, 16, 12, 12.5, 3, 3_599_999, 30]]


def test_aggregate_klines_1h_from_15m_aligns_to_hour():
    r15 = [[i * 900_000, 1, 1, 1, 1, 1, (i + 1) * 900_000 - 1, 1] for i in range(1, 9)]   # 00:15 .. 02:00
    out = uni.aggregate_klines(r15, 900_000, 3_600_000)
    assert [r[0] for r in out] == [3_600_000]                                             # yalnız 01:00 kovası tam
