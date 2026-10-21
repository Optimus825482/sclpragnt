"""Giriş tetikleyicileri (app/entry_triggers.py, 2026-10-20): MA kesişimine alternatif saf dedektörler. Her biri
`[{index, rules}]` döner (detect_ma_buy ile aynı biçim) → aynı replay / çıkış simülatörüyle ölçülür."""
from app import entry_triggers as et


def _bars(closes, highs=None, lows=None, vols=None):
    highs = highs or closes
    lows = lows or closes
    vols = vols or [1.0] * len(closes)
    return [{"open_ms": i * 60_000, "open": c, "high": h, "low": l, "close": c, "volume": v}
            for i, (c, h, l, v) in enumerate(zip(closes, highs, lows, vols))]


def test_registry_lists_all_triggers_with_ma_cross_first():
    names = [t["id"] for t in et.TRIGGERS]
    assert names[0] == "ma_cross" and {"stoch_turn", "breakout_vol", "pullback_sma20", "rsi_cross30", "bb_reentry"} <= set(names)


def test_breakout_requires_new_20_bar_high_and_volume_surge():
    closes = [10.0] * 30 + [10.5]
    highs = [10.2] * 30 + [10.6]
    vols = [1.0] * 30 + [3.0]
    hits = et.detect_breakout_vol(_bars(closes, highs, None, vols), lookback=20, vol_mult=2.0)
    assert [h["index"] for h in hits] == [30]
    assert hits[0]["rules"] == ["breakout_vol"]
    # hacim yetersizse tetiklenmez
    assert et.detect_breakout_vol(_bars(closes, highs, None, [1.0] * 31), lookback=20, vol_mult=2.0) == []


def test_rsi_cross30_fires_when_rsi_crosses_up_through_30():
    closes = [100 - i for i in range(25)] + [75 + i * 2 for i in range(10)]   # 25 bar düşüş, sonra sert toparlanma
    hits = et.detect_rsi_cross30(_bars(closes), period=14, level=30.0)
    assert len(hits) == 1 and hits[0]["index"] > 25 and hits[0]["rules"] == ["rsi_cross30"]


def test_bb_reentry_fires_on_close_back_above_lower_band():
    closes = [100.0 + (i % 2) * 0.5 for i in range(30)] + [95.0, 99.0]   # bant dışına çık, geri gir
    hits = et.detect_bb_reentry(_bars(closes), period=20, mult=2.0)
    assert [h["index"] for h in hits] == [31]


def test_pullback_sma20_fires_on_touch_and_hold_in_uptrend():
    base = [100 + i * 0.5 for i in range(120)]             # SMA20 > SMA99 (yükseliş)
    closes = base[:]
    lows = base[:]
    # 119. mumda fiyat SMA20'ye değip üstünde kapanır
    hits = et.detect_pullback_sma20(_bars(closes, None, lows), fast=20, slow=99)
    assert hits == [] or all(h["rules"] == ["pullback_sma20"] for h in hits)
    sma20 = sum(closes[99:119]) / 20
    lows[118] = sma20 - 0.01                                 # önceki mum SMA20'ye değdi
    closes[119] = sma20 + 1.0
    hits = et.detect_pullback_sma20(_bars(closes, None, lows), fast=20, slow=99)
    assert 119 in [h["index"] for h in hits]


def test_stoch_turn_fires_when_k_crosses_above_d_from_below_20():
    closes = [100 - i * 0.5 for i in range(40)] + [80 + i * 0.6 for i in range(12)]
    hits = et.detect_stoch_turn(_bars(closes), level=20.0)
    assert hits and all(h["rules"] == ["stoch_turn"] for h in hits)


def test_detect_dispatches_by_id_and_ma_cross_matches_live_detector():
    from app import ma_buy_signals
    closes = [100.0 - i * 0.01 for i in range(100)] + [99.0 + i * 0.5 for i in range(30)]
    bars = _bars(closes)
    ours = et.detect("ma_cross", bars, use_sma=True, stoch_max=None)
    live = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), use_sma=True, slow_cross=True, stoch_max=None)
    assert [h["index"] for h in ours] == [h["index"] for h in live]
