"""Çevrimdışı Hız Avcısı yeniden tarama harness'ı (app/rescan + scripts/rescan_velocity_history.py).

Kapsam:
  1. PARİTE: aynı sentetik 1m/5m/15m serisiyle canlı `detect_velocity_candidates`
     (REST/WS/DB/ML yamalı) ve `scan_symbol_at_tick` AYNI skor/kapı/hedefi üretir.
  2. İLERİYE BAKMAMA: tick'te/sonrasında kapanan barlar çıktıyı değiştiremez.
  3. Ön-filtre `passes` için gerekli koşuldur (geçen hiçbir tick ön-filtreden düşmez).
  4. candidate_id / journal satır şekli / sıralama-kapak kuralı.
  5. 24s ticker aynası ve havuz matrisi.
  6. Doğrulama metrikleri (küçük fixture).
"""
from __future__ import annotations

import math
import pathlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402
from app.routers import velocity  # noqa: E402
from app.rescan import scan as S  # noqa: E402
from app.rescan import series as SE  # noqa: E402
from app.rescan import validate as VAL  # noqa: E402

SYM = "TESTTRY"
NOW_MS = 1_792_000_000_000  # sabit "şimdi" (ms) — 5 dk ızgarasında


def _series(n, base=100.0, slope=0.003, amp=1.5, seed=7):
    rng = np.random.default_rng(seed)
    c = np.array([base * (1 + slope * i) + amp * math.sin(i / 2.0) for i in range(n)])
    c = c + rng.normal(0, amp * 0.1, n)
    return c


def _rows(closes, step_ms, end_open_ms, vol_base=1000.0, taker=False, seed=3):
    """Son satırın open_time'ı `end_open_ms`; kline biçimi (9 sütun, opsiyonel taker 10.)."""
    rng = np.random.default_rng(seed)
    rows = []
    n = len(closes)
    for i, c in enumerate(closes):
        t = end_open_ms - (n - 1 - i) * step_ms
        o = closes[i - 1] if i else c
        h = max(o, c) * 1.004
        l = min(o, c) * 0.996
        v = vol_base + 50.0 * i + float(rng.uniform(0, 100))
        row = [t, float(o), float(h), float(l), float(c), v, t + step_ms - 1, v * c, 10 + i]
        if taker:
            row.append(v * 0.6)
        rows.append(row)
    return rows


def _fixture(forming=True):
    """1m×60, 5m×40, 15m×130 — son satır oluşmakta (open=NOW) -> canlı & rescan 59/39/129 kapanmış bar görür."""
    m1 = _rows(_series(60), 60_000, NOW_MS if forming else NOW_MS - 60_000)
    m5 = _rows(_series(40, base=500.0, slope=0.004, amp=4.0, seed=11), 300_000, NOW_MS if forming else NOW_MS - 300_000, seed=5)
    m15 = _rows(_series(130, base=50.0, slope=0.002, amp=0.6, seed=13), 900_000, NOW_MS if forming else NOW_MS - 900_000, seed=9)
    return m1, m5, m15


class ParityTests(unittest.IsolatedAsyncioTestCase):
    """Canlı dedektör ↔ rescan çekirdeği birebir parite."""

    async def _live(self, m1, m5, m15, horizon, change_24h=5.0, quote_vol=20_000_000.0, prof_atr=0.1):
        async def fake_fetch(symbol, interval, limit):
            return {"1m": m1, "5m": m5, "15m": m15}[interval]

        ticker_rows = [{"symbol": SYM, "priceChangePercent": str(change_24h), "quoteVolume": str(quote_vol)}]
        fake_time = types.SimpleNamespace(time=lambda: NOW_MS / 1000.0 + 0.002)
        with patch.object(velocity, "_velocity_rate_acquire", AsyncMock(return_value=None)), \
             patch.object(velocity, "time", fake_time), \
             patch.object(velocity, "ticker_24h", AsyncMock(return_value=ticker_rows)), \
             patch.object(velocity, "top_gainers", AsyncMock(return_value=[{"symbol": SYM}])), \
             patch.object(velocity, "active_movers_pool", AsyncMock(return_value=[])), \
             patch.object(velocity, "fetch_klines", fake_fetch), \
             patch.object(velocity, "market", types.SimpleNamespace(orderflow={})), \
             patch.object(velocity, "micro_structure_multiplier", MagicMock(return_value=1.0)), \
             patch.object(velocity.microflow, "get_snapshot", MagicMock(return_value={})), \
             patch.object(velocity.microflow, "start", AsyncMock(return_value=None)), \
             patch.object(velocity.ml_forecast, "predict_target", MagicMock(return_value=None)), \
             patch.object(velocity.database, "get_all_symbol_target_states", AsyncMock(return_value=[])), \
             patch.object(velocity.database, "save_velocity_candidates", AsyncMock(return_value=None)), \
             patch.object(velocity.database, "get_velocity_calibration_stats", AsyncMock(return_value={})), \
             patch.dict(velocity._velocity_profile_atr, {"5m": prof_atr, "15m": prof_atr}), \
             patch("app.early_discovery.top_candidates", MagicMock(return_value=[])), \
             patch.object(config, "SYMBOLS", []):
            res = await velocity.detect_velocity_candidates({"limit": 10}, horizon_minutes=horizon)
        rows = list(res["candidates"]) + list(res["watchlist"])
        return next((r for r in rows if r["symbol"] == SYM), None)

    def _rescan(self, m1, m5, m15, horizon, change_24h=5.0, quote_vol=20_000_000.0, prof_atr=0.1):
        return S.scan_symbol_at_tick(SYM, m1, m5, m15, horizon_minutes=horizon, tick_ms=NOW_MS,
                                     prof_atr=prof_atr, min_atr_pct=velocity.VELOCITY_MIN_ATR_PCT,
                                     change_24h=change_24h, quote_vol_24h=quote_vol)

    def _assert_same(self, live, mine):
        self.assertIsNotNone(live, "canlı fixture aday üretmedi")
        self.assertIsNotNone(mine, "rescan fixture aday üretmedi")
        for key in ("passes", "velocity_score", "target_pct", "atr_pct", "bb_width_pct", "rsi", "mfi",
                    "ret3_pct", "mode", "exhausted", "block_reason", "macd_bullish", "macd_rising",
                    "m5_macd_bullish", "m5_pattern_ok", "m5_pattern", "leading_ok", "m1_atr_prev",
                    "m3_atr_prev", "aroon_up", "adx_14", "ret_8h_pct", "last_closed_at", "volume_ratio"):
            self.assertEqual(live.get(key), mine.get(key), f"alan farklı: {key}")
        for key in ("choppiness_10", "regime_chop", "late_phase", "spread_unknown", "range_pos_60"):
            self.assertEqual((live.get("radar") or {}).get(key), mine["radar"].get(key), f"radar.{key}")

    async def test_parity_h5_passing_candidate(self):
        m1, m5, m15 = _fixture()
        live = await self._live(m1, m5, m15, 5)
        mine = self._rescan(m1, m5, m15, 5)
        self._assert_same(live, mine)
        self.assertTrue(mine["passes"], f"fixture kapıyı geçmeli: {mine['block_reason']}")
        self.assertGreater(mine["velocity_score"], 0)

    async def test_parity_h15_and_late_phase(self):
        m1, m5, m15 = _fixture()
        live = await self._live(m1, m5, m15, 15, change_24h=55.0)
        mine = self._rescan(m1, m5, m15, 15, change_24h=55.0)
        self._assert_same(live, mine)
        self.assertTrue(mine["radar"].get("late_phase"))

    async def test_parity_default_profile_atr(self):
        m1, m5, m15 = _fixture()
        live = await self._live(m1, m5, m15, 5, prof_atr=None)
        mine = self._rescan(m1, m5, m15, 5, prof_atr=None)
        self._assert_same(live, mine)

    async def test_parity_taker_column_applies_multiplier(self):
        m1 = _rows(_series(60), 60_000, NOW_MS, taker=True)
        _, m5, m15 = _fixture()
        live = await self._live(m1, m5, m15, 5)
        mine = self._rescan(m1, m5, m15, 5)
        self._assert_same(live, mine)
        self.assertEqual(mine["radar"].get("taker_confirm"), "strong")

    async def test_liquidity_floor_drops_symbol_like_live(self):
        m1, m5, m15 = _fixture()
        live = await self._live(m1, m5, m15, 5, quote_vol=500_000.0)
        mine = self._rescan(m1, m5, m15, 5, quote_vol=500_000.0)
        self.assertIsNone(live)
        self.assertIsNone(mine)


class NoLookAheadTests(unittest.TestCase):
    def test_future_bars_do_not_change_output(self):
        m1, m5, m15 = _fixture()
        base = S.scan_symbol_at_tick(SYM, m1, m5, m15, horizon_minutes=5, tick_ms=NOW_MS, prof_atr=0.1)
        # Tick'te açılan (forming) ve sonrasındaki barlara ÇILGIN değerler ver
        m1x = [list(r) for r in m1] + [[NOW_MS + 60_000 * k, 1e6, 2e6, 1.0, 1e6, 1e9, 0, 0, 0] for k in range(1, 4)]
        m1x[-4][4] = 9e5  # tick'te açılan forming bar
        m5x = [list(r) for r in m5]; m5x[-1][4] = 1e6
        m15x = [list(r) for r in m15]; m15x[-1][2] = 1e7
        after = S.scan_symbol_at_tick(SYM, m1x, m5x, m15x, horizon_minutes=5, tick_ms=NOW_MS, prof_atr=0.1)
        self.assertEqual(base, after)

    def test_closed_before_boundary(self):
        rows = [[NOW_MS - 120_000, 1, 1, 1, 1, 1], [NOW_MS - 60_000, 1, 1, 1, 1, 1], [NOW_MS, 1, 1, 1, 1, 1]]
        got = S.closed_before(rows, 60_000, NOW_MS)
        self.assertEqual([r[0] for r in got], [NOW_MS - 120_000, NOW_MS - 60_000])
        self.assertEqual(len(S.closed_before(rows, 60_000, NOW_MS, 1)), 1)

    def test_stale_series_returns_none(self):
        m1, m5, m15 = _fixture()
        self.assertIsNone(S.scan_symbol_at_tick(SYM, m1, m5, m15, horizon_minutes=5, tick_ms=NOW_MS + 10 * 60_000))


class PrefilterTests(unittest.TestCase):
    def test_bar_features_shapes_and_prefilter_is_necessary(self):
        n = 600
        closes = _series(n, slope=0.0, amp=0.8, seed=21)
        # Birkaç patlama ekle ki bazı tick'ler gerçekten geçsin
        for k in (200, 350, 480):
            closes[k:k + 25] *= np.linspace(1.0, 1.06, 25)
        rows = _rows(closes, 60_000, NOW_MS)
        arr = np.asarray(rows, dtype=np.float64)
        feats = SE.bar_features(arr)
        for key in ("atr_pct", "bb_width", "mfi"):
            self.assertEqual(feats[key].shape, (n,))
        mask = SE.prefilter_mask(feats, prof_atr=0.1, min_atr_pct=0.25)
        self.assertEqual(mask.shape, (n,))
        passes_n = 0
        for j in range(60, n):
            tick = int(arr[j, 0]) + 60_000
            win = rows[max(0, j - S.M1_BARS + 1):j + 1]
            c = S.scan_symbol_at_tick(SYM, win, [], [], horizon_minutes=5, tick_ms=tick, prof_atr=0.1, min_atr_pct=0.25)
            if c and c["passes"]:
                passes_n += 1
                self.assertTrue(mask[j], f"geçen tick ön-filtreden düşmüş j={j}")
            # Ön-filtre, pencereden bağımsız göstergelerle birebir: bb/atr/mfi karşılaştır
            if c and j >= 29:
                self.assertAlmostEqual(c["atr_pct"], round(float(feats["atr_pct"][j]), 3), places=2)
                self.assertAlmostEqual(c["bb_width_pct"], round(float(feats["bb_width"][j]), 2), places=1)
                self.assertAlmostEqual(c["mfi"], round(float(feats["mfi"][j]), 1), places=0)
        self.assertGreater(passes_n, 0, "fixture hiç geçen üretmedi")
        self.assertLess(mask.sum(), n, "ön-filtre hiçbir şeyi elememeli değil")


class RowShapeTests(unittest.TestCase):
    def test_candidate_id_and_journal_row(self):
        m1, m5, m15 = _fixture()
        c = S.scan_symbol_at_tick(SYM, m1, m5, m15, horizon_minutes=15, tick_ms=NOW_MS, prof_atr=0.1)
        row = S.to_journal_row(c, rank=2)
        self.assertEqual(row["candidate_id"], f"rescan:{SYM}:{NOW_MS}:15")
        self.assertEqual(row["created_at"], NOW_MS / 1000.0)
        for col in ("candidate_id", "created_at", "symbol", "price", "target_pct", "atr_pct", "volume_ratio",
                    "ret3_pct", "velocity_score", "passes", "rank"):
            self.assertIn(col, row)
        self.assertEqual(row["rank"], 2)
        self.assertEqual(row["source"], "rescan")
        self.assertTrue(row["candidate_id"].startswith("rescan:"))

    def test_rank_tick_rule(self):
        cands = [{"symbol": f"S{i}", "tick_ms": NOW_MS, "horizon_minutes": 5, "price": 1.0, "target_pct": 2.0,
                  "atr_pct": 0.5, "volume_ratio": 1.0, "ret3_pct": 0.1, "velocity_score": float(i), "passes": i % 2 == 0}
                 for i in range(30)]
        out = S.rank_tick(cands, rank_limit=3, journal_cap=5)
        self.assertEqual(len(out), 5)  # 15 geçen -> kapak 5
        self.assertEqual([r["rank"] for r in out], [1, 2, 3, None, None])
        self.assertEqual(out[0]["symbol"], "S28")
        self.assertEqual(len(S.rank_tick(cands, rank_limit=3, journal_cap=0)), 15)


class SeriesTests(unittest.TestCase):
    def test_ticker_24h_mirror(self):
        n = 288 * 2 + 10
        closes = np.linspace(100.0, 120.0, n)
        rows = _rows(closes, 300_000, NOW_MS - 300_000)
        s = SE.SymbolSeries(SYM, "5m", np.asarray(rows, dtype=np.float64))
        ticks = np.array([NOW_MS], dtype=np.int64)
        t = SE.ticker_24h_at_ticks(s, ticks)
        j = len(rows) - 1
        exp = (closes[j] / closes[j - 288] - 1) * 100
        self.assertAlmostEqual(float(t["change"][0]), exp, places=6)
        self.assertAlmostEqual(float(t["qvol"][0]), sum(r[7] for r in rows[j - 287:j + 1]), places=3)
        self.assertAlmostEqual(float(t["last"][0]), closes[j])
        # Veri yetersiz -> NaN
        s2 = SE.SymbolSeries(SYM, "5m", np.asarray(rows[:100], dtype=np.float64))
        self.assertTrue(np.isnan(SE.ticker_24h_at_ticks(s2, ticks)["change"][0]))

    def test_closed_index(self):
        rows = _rows(np.ones(5), 60_000, NOW_MS - 60_000)
        s = SE.SymbolSeries(SYM, "1m", np.asarray(rows, dtype=np.float64))
        self.assertEqual(s.closed_index(NOW_MS), 4)
        self.assertEqual(s.closed_index(NOW_MS - 1), 3)
        self.assertEqual(s.closed_index(rows[0][0]), -1)

    def test_pool_matrix_top_gainers_and_fixed_universe(self):
        syms = ["AAATRY", "BBBTRY", "CCCTRY", "DDDTRY", "BTCTRY"]
        T = 2
        def t24(change, qv):
            return {"change": np.array([change] * T, float), "qvol": np.array([qv] * T, float),
                    "high": np.full(T, 1.0), "low": np.full(T, 0.5), "count": np.full(T, 100.0), "last": np.full(T, 0.9)}
        tick24 = {"AAATRY": t24(10.0, 6e6), "BBBTRY": t24(20.0, 6e6), "CCCTRY": t24(30.0, 1e6),  # hacim düşük -> gainer değil
                  "DDDTRY": t24(1.0, 6e6), "BTCTRY": t24(-2.0, 9e8)}
        with patch.object(config, "SYMBOLS", ["BTCTRY"]):
            in_pool, src = SE.build_pool_matrix(syms, tick24, None, T, universe="top-gainers-daily",
                                                gainer_n=2, mover_n=0, discovery_n=0)
        self.assertEqual(SE.pool_source_name(src[1, 0]), "gainer")   # BBBTRY
        self.assertEqual(SE.pool_source_name(src[0, 0]), "gainer")   # AAATRY
        self.assertFalse(in_pool[2, 0])                                # CCCTRY hacim tabanı
        self.assertFalse(in_pool[3, 0])                                # DDDTRY 3. sırada, N=2
        self.assertEqual(SE.pool_source_name(src[4, 0]), "symbol")   # sabit evren
        allp, _ = SE.build_pool_matrix(syms, tick24, None, T, universe="all")
        self.assertTrue(allp.all())


class ValidateTests(unittest.TestCase):
    def test_metrics_on_tiny_fixture(self):
        t0 = 1_792_000_000.0
        live = [{"symbol": "A", "created_at": t0 + 100, "horizon_minutes": 5, "velocity_score": 100.0},
                {"symbol": "A", "created_at": t0 + 3000, "horizon_minutes": 5, "velocity_score": 300.0},
                {"symbol": "B", "created_at": t0 + 200, "horizon_minutes": 5, "velocity_score": 200.0},
                {"symbol": "C", "created_at": t0 + 200, "horizon_minutes": 15, "velocity_score": 50.0}]
        rescan = [{"symbol": "A", "created_at": t0, "horizon_minutes": 5, "velocity_score": 90.0},
                  {"symbol": "A", "created_at": t0 + 3300, "horizon_minutes": 5, "velocity_score": 310.0},
                  {"symbol": "B", "created_at": t0 + 240, "horizon_minutes": 5, "velocity_score": 210.0},
                  {"symbol": "D", "created_at": t0 + 240, "horizon_minutes": 5, "velocity_score": 999.0}]
        rep = VAL.validate(live, rescan, tol_s=300.0)
        tot = rep["total"]
        self.assertEqual(tot["live_n"], 4)
        self.assertEqual(tot["rescan_n"], 4)
        self.assertEqual(tot["matched"], 3)                  # C eşleşmez (15m yok)
        self.assertAlmostEqual(tot["reproduced"], 0.75)
        self.assertAlmostEqual(tot["precision"], 0.75)       # D eşleşmez
        self.assertAlmostEqual(tot["jaccard"], 2 / 4)        # {A,B} / {A,B,C,D}
        self.assertGreater(tot["pearson"], 0.99)
        self.assertAlmostEqual(tot["spearman"], 1.0)
        table = VAL.format_table(rep)
        self.assertIn("TOPLAM", table)
        self.assertIn("75.0%", table)


if __name__ == "__main__":
    unittest.main()
