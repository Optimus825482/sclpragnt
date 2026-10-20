"""MA BUY 7 günlük replay (app/ma_buy_replay.py, 2026-10-20): sinyal sonrası en yüksek yükseliş, BİR SONRAKİ sinyale kadar.
Saf hesap; ağ/DB yok."""
from app import ma_buy_replay as rp


def _bars(closes, highs=None, lows=None, tf_ms=60_000):
    highs = highs or closes
    lows = lows or closes
    return [{"open_ms": i * tf_ms, "close_ms": (i + 1) * tf_ms - 1, "open": c, "high": h, "low": l, "close": c}
            for i, (c, h, l) in enumerate(zip(closes, highs, lows))]


def test_mfe_until_next_signal_uses_highs_between_the_two_signals_inclusive():
    bars = _bars([10.0] * 8, highs=[10, 10, 10, 12, 11, 15, 9, 9])
    # Sinyaller 2. ve 5. mumda: ölçüm 3..5 arası (5 dahil) → zirve 15 (+%50); 6. mumdaki 9 sayılmaz.
    out = rp.outcomes_for_signals(bars, [{"index": 2, "rules": ["fast_cross_mid"]}, {"index": 5, "rules": ["mid_cross_slow"]}],
                                  tf="1m", target_pct=1.0)
    first = out[0]
    assert first["mfe_pct"] == 50.0
    assert first["bars_to_next"] == 3 and first["minutes_to_next"] == 3
    assert first["minutes_to_peak"] == 3          # zirve 5. mum = sinyalden 3 mum sonra
    assert first["open_ended"] is False
    assert first["target_hit"] is True


def test_last_signal_is_open_ended_and_measured_to_end_of_data():
    bars = _bars([10.0] * 6, highs=[10, 10, 10, 10, 10.5, 10.2])
    out = rp.outcomes_for_signals(bars, [{"index": 3, "rules": ["fast_cross_mid"]}], tf="5m", target_pct=6.0)
    assert out[0]["open_ended"] is True
    assert out[0]["mfe_pct"] == 5.0
    assert out[0]["bars_to_next"] == 2 and out[0]["minutes_to_next"] == 10
    assert out[0]["target_hit"] is False


def test_fixed_horizons_report_none_when_data_is_short():
    bars = _bars([10.0] * 5, highs=[10, 11, 12, 13, 14])
    out = rp.outcomes_for_signals(bars, [{"index": 0, "rules": ["fast_cross_mid"]}], tf="1m", target_pct=1.0)
    h = out[0]["horizons"]
    assert h["15m"] is None and h["1h"] is None      # 4 mum var, 15 dk için 15 gerekir
    assert out[0]["mae_pct"] == 0.0


def test_fixed_horizon_mfe_on_one_hour_bars():
    bars = _bars([100.0] * 30, highs=[100 + i for i in range(30)], tf_ms=3_600_000)
    out = rp.outcomes_for_signals(bars, [{"index": 0, "rules": ["fast_cross_mid"]}], tf="1h", target_pct=3.0)
    h = out[0]["horizons"]
    assert h["1h"] == 1.0 and h["4h"] == 4.0 and h["24h"] == 24.0
    assert h["15m"] is None                          # 15 dk, 1 saatlik mumla ölçülemez


def test_aggregate_groups_by_timeframe_and_rule():
    rows = [
        {"symbol": "A", "timeframe": "5m", "rules": ["fast_cross_mid"], "mfe_pct": 1.0, "open_ended": False, "target_hit": False, "minutes_to_peak": 5, "minutes_to_next": 30},
        {"symbol": "B", "timeframe": "5m", "rules": ["fast_cross_mid", "mid_cross_slow"], "mfe_pct": 3.0, "open_ended": True, "target_hit": True, "minutes_to_peak": 15, "minutes_to_next": 60},
        {"symbol": "C", "timeframe": "1h", "rules": ["mid_cross_slow"], "mfe_pct": 2.0, "open_ended": False, "target_hit": False, "minutes_to_peak": 120, "minutes_to_next": 600},
    ]
    agg = rp.aggregate(rows)
    assert agg["5m"]["all"]["n"] == 2 and agg["5m"]["all"]["median_mfe_pct"] == 2.0
    assert agg["5m"]["all"]["share_ge_2pct"] == 0.5 and agg["5m"]["all"]["target_hit_rate"] == 0.5
    assert agg["5m"]["all"]["open_ended"] == 1
    assert agg["5m"]["fast_cross_mid"]["n"] == 2 and agg["5m"]["mid_cross_slow"]["n"] == 1
    assert agg["1h"]["all"]["n"] == 1 and agg["1h"]["all"]["median_minutes_to_peak"] == 120


def test_markdown_report_lists_every_timeframe_section():
    rows = [{"symbol": "A", "timeframe": "30m", "rules": ["fast_cross_mid"], "mfe_pct": 1.5, "open_ended": False,
             "target_hit": False, "minutes_to_peak": 30, "minutes_to_next": 90, "mae_pct": -0.5,
             "signal_time_ms": 0, "signal_price": 1.0, "horizons": {"15m": None, "1h": 1.0, "4h": 1.5, "24h": None}}]
    md = rp.render_markdown(rows, rp.aggregate(rows), {"days": 7, "symbols": 1, "generated_at": "2026-10-20 19:00"})
    assert "M30" in md and "fast_cross_mid" in md and "1.5" in md
