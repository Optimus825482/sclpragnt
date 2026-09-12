"""W11a — gösterge düzeltmeleri için kilit testleri (C-07, C-08, C-10, C-13, C-14).

Her test, bulgunun yeniden sokulması durumunda KIRILACAK şekilde yazıldı.
Mutasyon doğrulaması: `outputs/denetim_2026-09-12/scratch/verify_w11a_mutations.py`.
"""
import math
import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.market_intelligence import symbol_outcome_profile  # noqa: E402
from app.technical_analysis import (  # noqa: E402
    _hma,
    _methodology_analysis,
    _price_action_setup,
    _sma,
    calculate_snapshot,
)


def _flat_bars(count, value=100.0):
    return {
        "opens": [value] * count,
        "highs": [value] * count,
        "lows": [value] * count,
        "closes": [value] * count,
        "volumes": [1.0] * count,
    }


def _trend_bars(count, start=100.0, step=0.5):
    closes = [start + index * step for index in range(count)]
    return {
        "opens": [value - step / 2 for value in closes],
        "highs": [value + step for value in closes],
        "lows": [value - step for value in closes],
        "closes": closes,
        "volumes": [1.0] * count,
    }


class LongestLossStreakTests(unittest.TestCase):
    """C-07 — `longest_loss_streak` kuyruktaki seriyi değil MAKSİMUM seriyi ölçmeli."""

    def _profile(self, pnls):
        trades = [{"symbol": "TESTUSDT", "pnl": pnl, "strategy": "LLM_PAPER"} for pnl in pnls]
        return symbol_outcome_profile(trades, "TESTUSDT")

    def test_longest_run_wins_even_when_series_ends_positive(self):
        # Kuyruk kazancı: eski kod 0 döndürüyordu, gerçek en uzun seri 3.
        profile = self._profile([-1, -1, +5, -1, -1, -1, +2])
        assert profile["longest_loss_streak"] == 3
        assert profile["current_loss_streak"] == 0

    def test_longest_run_wins_when_series_ends_negative(self):
        profile = self._profile([-1, -1, -1, +9])
        assert profile["longest_loss_streak"] == 3

    def test_longest_run_is_maximum_not_total(self):
        # İki ayrı 2'lik seri -> 2 (eski kod son seride kaldığı için 2 verirdi;
        # 3'lük + 2'lik karışımda eski kod 2, doğru cevap 3).
        profile = self._profile([-1, -1, -1, +5, -1, -1, +5])
        assert profile["longest_loss_streak"] == 3

    def test_all_wins_has_no_loss_streak(self):
        profile = self._profile([+1, +2, +3])
        assert profile["longest_loss_streak"] == 0
        assert profile["current_loss_streak"] == 0

    def test_all_losses_counts_the_whole_series(self):
        profile = self._profile([-1, -2, -3])
        assert profile["longest_loss_streak"] == 3
        assert profile["current_loss_streak"] == 3


class PriceActionSetupTests(unittest.TestCase):
    """C-08 — son bar (kapanmış) taranmalı; `_candlestick_patterns` ile aynı indeks."""

    def _pin_bar_series(self):
        opens = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        highs = [100.5, 100.5, 100.5, 100.5, 100.5, 101.0]
        lows = [99.5, 99.5, 99.5, 99.5, 99.5, 95.0]
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.6]
        return opens, highs, lows, closes

    def test_last_closed_bar_is_the_one_evaluated(self):
        opens, highs, lows, closes = self._pin_bar_series()
        setup = _price_action_setup(opens, highs, lows, closes)
        assert setup["candle_index"] == len(closes) - 1
        assert setup["setup"] == "bullish_pin_bar"

    def test_index_matches_candlestick_patterns_convention(self):
        # Aynı modüldeki `_candlestick_patterns` `size - 1` kullanır.
        for count in (4, 6, 12):
            bars = _trend_bars(count)
            setup = _price_action_setup(bars["opens"], bars["highs"], bars["lows"], bars["closes"])
            assert setup["candle_index"] == count - 1

    def test_insufficient_data_is_still_rejected(self):
        setup = _price_action_setup([1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3])
        assert setup["reason"] == "insufficient_data"


class ElliottFlatSeriesTests(unittest.TestCase):
    """C-10 — tamamen yatay seri 'impulse_candidate' + maksimum güven üretmemeli."""

    def test_flat_series_is_not_an_impulse(self):
        bars = _flat_bars(60)
        elliott = _methodology_analysis(
            bars["opens"], bars["highs"], bars["lows"], bars["closes"], bars["volumes"]
        )["elliott"]
        assert elliott["structure"] == "correction_or_range"
        assert elliott["confidence"] < 0.7

    def test_flat_series_confidence_is_the_floor(self):
        bars = _flat_bars(60)
        elliott = _methodology_analysis(
            bars["opens"], bars["highs"], bars["lows"], bars["closes"], bars["volumes"]
        )["elliott"]
        assert elliott["confidence"] == pytest.approx(0.35)

    def test_real_uptrend_is_still_an_impulse(self):
        # Non-vacuity: düzeltme gerçek tespiti kapatmamalı.
        bars = _trend_bars(60)
        elliott = _methodology_analysis(
            bars["opens"], bars["highs"], bars["lows"], bars["closes"], bars["volumes"]
        )["elliott"]
        assert elliott["structure"] == "impulse_candidate"
        assert elliott["wave_hint"] == "possible_wave_3"

    def test_real_downtrend_is_still_an_impulse(self):
        bars = _trend_bars(60, start=200.0, step=-0.5)
        elliott = _methodology_analysis(
            bars["opens"], bars["highs"], bars["lows"], bars["closes"], bars["volumes"]
        )["elliott"]
        assert elliott["structure"] == "impulse_candidate"
        assert elliott["wave_hint"] == "possible_wave_c"


class MovingAverageNamingTests(unittest.TestCase):
    """C-13 — `hma_9` gerçekten Hull MA olmalı, SMA değil."""

    def _snapshot(self, bars):
        return calculate_snapshot(
            "TESTUSDT",
            float(bars["closes"][-1]),
            {"5m": bars},
        )

    def test_hma_9_equals_the_canonical_hma(self):
        bars = _trend_bars(60)
        snapshot = self._snapshot(bars)
        assert snapshot["moving_averages"]["hma_9"] == pytest.approx(_hma(bars["closes"], 9))

    def test_hma_9_is_not_a_plain_sma(self):
        bars = _trend_bars(60)
        snapshot = self._snapshot(bars)
        assert snapshot["moving_averages"]["hma_9"] != pytest.approx(_sma(bars["closes"], 9))

    def test_hma_9_differs_from_sma_on_a_curved_series(self):
        closes = [100.0 + math.sin(index / 3.0) * 4 + index * 0.2 for index in range(60)]
        bars = {
            "opens": closes,
            "highs": [value + 0.4 for value in closes],
            "lows": [value - 0.4 for value in closes],
            "closes": closes,
            "volumes": [1.0] * 60,
        }
        snapshot = self._snapshot(bars)
        assert snapshot["moving_averages"]["hma_9"] != pytest.approx(_sma(closes, 9))


class MethodologyKeyTests(unittest.TestCase):
    """C-14 — tüketiciler `methodologies` anahtarını okumalı (`methodology` değil)."""

    def _snapshot(self, regime_name):
        return {
            "symbol": "TESTUSDT",
            "data_ready": True,
            "price": 100.0,
            "trend": {"alignment": "bullish", "adx": 30.0},
            "momentum": {"return_5m": 1.0, "return_15m": 1.0, "return_1h": 1.0, "rsi_14": 55.0},
            "volume": {"volume_ratio_20": 1.4},
            "liquidity": {"spread_pct": 0.05, "orderbook_depth_try": 50000.0},
            "methodologies": {"regime": {"name": regime_name, "confidence": 0.6}},
        }

    def test_bull_regime_bonus_is_applied(self):
        from app.routers.llm_chat import _market_candidate_score

        score, evidence, _ = _market_candidate_score(self._snapshot("bull_quiet"))
        assert any("rejim bull_quiet" in item for item in evidence)

    def test_non_bull_regime_gets_no_bonus(self):
        from app.routers.llm_chat import _market_candidate_score

        bull_score, _, _ = _market_candidate_score(self._snapshot("bull_quiet"))
        range_score, range_evidence, _ = _market_candidate_score(self._snapshot("range_transition"))
        assert range_score == pytest.approx(bull_score - 0.8)
        assert not any("rejim" in item for item in range_evidence)

    def test_legacy_singular_key_is_no_longer_read(self):
        # Bulgunun tam şekli: eski anahtar adı sessizce bonusu düşürüyordu.
        from app.routers.llm_chat import _market_candidate_score

        snapshot = self._snapshot("bull_quiet")
        snapshot["methodology"] = snapshot.pop("methodologies")
        _, evidence, _ = _market_candidate_score(snapshot)
        assert not any("rejim" in item for item in evidence)

    def test_gainer_row_exposes_the_regime_from_the_plural_key(self):
        from app.routers.llm_chat import _gainer_row_to_candidate

        regime = {"name": "bull_quiet", "confidence": 0.6}
        row = {
            "symbol": "TESTUSDT",
            "score": 1.0,
            "snapshot": {"methodologies": {"regime": regime}},
            "timeframes": {},
        }
        candidate = _gainer_row_to_candidate(row, {"metrics": {}}, 5, set())
        assert candidate["regime"] == regime

    def test_gainer_row_regime_is_empty_with_the_legacy_key(self):
        from app.routers.llm_chat import _gainer_row_to_candidate

        row = {
            "symbol": "TESTUSDT",
            "score": 1.0,
            "snapshot": {"methodology": {"regime": {"name": "bull_quiet"}}},
            "timeframes": {},
        }
        candidate = _gainer_row_to_candidate(row, {"metrics": {}}, 5, set())
        assert candidate["regime"] is None

    def test_snapshot_publishes_the_plural_key(self):
        bars = _trend_bars(60)
        snapshot = calculate_snapshot("TESTUSDT", float(bars["closes"][-1]), {"5m": bars})
        assert "methodologies" in snapshot
        assert "methodology" not in snapshot
