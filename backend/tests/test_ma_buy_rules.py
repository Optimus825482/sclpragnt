"""TF'ye göre ek giriş kuralları (app/ma_buy_rules.py, 2026-10-21, kullanıcı tablosu):
M15: mum boyu ≥ %1 ve RSI 45–65 · M30: MACD histogram artıyor ve ADX > 20 · H1: son 3 mum yükselişte, dalga geniş, RSI 45–65, ADX > 20."""
from app import ma_buy_rules as rules


def _bars(closes, opens=None, highs=None, lows=None):
    opens = opens or closes
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    return [{"open_ms": i * 60_000, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))]


def test_adx_is_high_in_a_steady_trend_and_low_in_chop():
    trend = _bars([100 + i for i in range(60)], highs=[101 + i for i in range(60)], lows=[99 + i for i in range(60)])
    chop = _bars([100 + (i % 2) for i in range(60)], highs=[101 + (i % 2) for i in range(60)], lows=[99 + (i % 2) for i in range(60)])
    a_t = rules.adx_series(trend, 14)
    a_c = rules.adx_series(chop, 14)
    assert a_t[-1] is not None and a_t[-1] > 40
    assert a_c[-1] is not None and a_c[-1] < 20
    assert a_t[10] is None                                   # ısınma


def test_macd_histogram_rises_when_momentum_accelerates():
    closes = [100.0] * 40 + [100 + i * i * 0.05 for i in range(1, 15)]   # ivmelenen yükseliş
    h = rules.macd_hist_series(closes, 12, 26, 9)
    assert h[-1] is not None and h[-2] is not None and h[-1] > h[-2]


def test_m15_rule_needs_bullish_body_and_rsi_band():
    closes = [100 + i * 0.3 for i in range(40)]
    bars = _bars(closes)
    bars[-1]["open"], bars[-1]["close"] = 110.0, 111.5          # gövde +%1,36
    ok, why = rules.passes_rules("15m", bars, len(bars) - 1, {"rsi": 55.0})
    assert ok, why
    bars[-1]["close"] = 110.5                                    # gövde %0,45 → eleme
    ok, why = rules.passes_rules("15m", bars, len(bars) - 1, {"rsi": 55.0})
    assert not ok and "mum" in why
    bars[-1]["close"] = 111.5
    ok, why = rules.passes_rules("15m", bars, len(bars) - 1, {"rsi": 72.0})
    assert not ok and "rsi" in why


def test_m30_rule_needs_rising_macd_hist_and_adx_over_20():
    ok, why = rules.passes_rules("30m", [], 0, {"macd_hist": 0.5, "macd_hist_prev": 0.2, "adx": 25.0})
    assert ok
    assert not rules.passes_rules("30m", [], 0, {"macd_hist": 0.1, "macd_hist_prev": 0.2, "adx": 25.0})[0]
    assert not rules.passes_rules("30m", [], 0, {"macd_hist": 0.5, "macd_hist_prev": 0.2, "adx": 15.0})[0]


def test_h1_rule_needs_three_rising_closes_wide_wave_rsi_and_adx():
    closes = [100.0] * 20 + [101.0, 102.0, 103.5]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    bars = _bars(closes, highs=highs, lows=lows)
    feats = {"rsi": 55.0, "adx": 25.0}
    ok, why = rules.passes_rules("1h", bars, len(bars) - 1, feats, wave_min_pct=2.0)
    assert ok, why                                             # 3 mum aralığı: 103.7/100.8 → %2,9
    bars[-2]["close"] = 100.5                                  # orta mum düşüş → eleme
    assert not rules.passes_rules("1h", bars, len(bars) - 1, feats, wave_min_pct=2.0)[0]
    bars[-2]["close"] = 102.0
    assert not rules.passes_rules("1h", bars, len(bars) - 1, feats, wave_min_pct=5.0)[0]   # dalga dar


def test_apply_rules_keeps_only_passing_signals_and_annotates_reason():
    closes = [100 + i * 0.3 for i in range(40)]
    bars = _bars(closes)
    signals = [{"index": 38, "rules": ["fast_cross_mid"]}, {"index": 39, "rules": ["fast_cross_mid"]}]
    bars[39]["open"], bars[39]["close"] = 110.0, 111.5
    kept, dropped = rules.apply_rules("15m", bars, signals, feature_fn=lambda i: {"rsi": 50.0})
    assert [s["index"] for s in kept] == [39] and len(dropped) == 1 and "mum" in dropped[0]["reason"]
    assert rules.apply_rules("5m", bars, signals, feature_fn=lambda i: {})[0] == signals   # M5: ek kural yok
