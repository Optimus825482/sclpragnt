"""W14 — kalan teknik-analiz bulguları için kilit (lock) testleri.

Kapsam: C-11, C-15, C-16, C-17, C-18, C-19, C-20, C-21, C-22, C-23.
Her test, bulgunun yeniden sokulması durumunda KIRILACAK şekilde yazıldı
(mutasyon doğrulanabilir). Sayısal "önce" değerleri yorumlarda kayıtlıdır.
"""
import ast
import inspect
import math
import textwrap
import unittest
from unittest.mock import patch

from app.correlation import (
    CorrelationMonitor, _pearson, _returns, cluster_exposure,
)
from app.market_intelligence import (
    LOCAL_REGIME_SCORE_SCALE, estimate_local_regime, walk_forward_assessment,
)
from app.technical_analysis import (
    _fisher_transform, _linear_regression, _linreg_slope_pct,
    _methodology_analysis, _rolling_vwma, calculate_snapshot,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _manual_pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy)


def _ramp_closes(n=60, start=100.0, step=0.5):
    return [start + step * i for i in range(n)]


def _bars(closes, spread=0.5, volumes=None):
    return {
        "opens": [c - spread / 2 for c in closes],
        "highs": [c + spread for c in closes],
        "lows": [c - spread for c in closes],
        "closes": list(closes),
        "volumes": list(volumes) if volumes is not None else [1.0] * len(closes),
    }


# ---------------------------------------------------------------------------
# C-11 — analyzer ATR kopyası: tek kanonik kaynak
# ---------------------------------------------------------------------------
class AnalyzerAtrSingleSourceTests(unittest.TestCase):
    """C-11 — `ScalpAnalyzer.calculate_atr` gövdesi kanonik `_atr`'a devretmeli."""

    def test_analyzer_atr_is_the_canonical_object(self):
        from app import analyzer as analyzer_module
        from app import technical_analysis as ta

        # Kopya gövdeye dönülürse import kaldırılır -> AttributeError ile kırılır.
        self.assertIs(analyzer_module._atr, ta._atr)

    def test_patching_canonical_atr_changes_analyzer_output(self):
        from app import analyzer as analyzer_module
        from app.analyzer import ScalpAnalyzer

        kline = _bars([100.0] * 40, spread=1.0)
        with patch.object(analyzer_module, "_atr", return_value=7.5) as mocked:
            got = ScalpAnalyzer.calculate_atr(None, kline, 14)
        # Kanonik yardımcı yamalanınca çıktı değişmiyorsa gövde yine kopyadır.
        self.assertEqual(got, 7.5)
        mocked.assert_called_once()


# ---------------------------------------------------------------------------
# C-15 — aynı modülde iki farklı regresyon eğimi yüzdesi
# ---------------------------------------------------------------------------
class LinearRegressionSlopeTests(unittest.TestCase):
    """C-15 — `_linear_regression.slope_pct` kanonik (ortalamaya böl) olmalı."""

    def test_slope_pct_matches_canonical_mean_basis(self):
        closes = [100.0 + i for i in range(25)]      # 20-bar rampa (eğim 1.0)
        lr = _linear_regression(closes, 20)
        # Eski (son kapanışa bölen) değer 0.806452 idi; kanonik 0.873362.
        self.assertAlmostEqual(lr["slope_pct"], _linreg_slope_pct(closes, 20), places=6)
        self.assertAlmostEqual(lr["slope_pct"], 0.873362, places=6)

    def test_legacy_last_close_basis_is_preserved_separately(self):
        closes = [100.0 + i for i in range(25)]
        lr = _linear_regression(closes, 20)
        self.assertAlmostEqual(lr["slope_pct_vs_last"], 0.806452, places=6)
        self.assertNotAlmostEqual(lr["slope_pct"], lr["slope_pct_vs_last"], places=3)


# ---------------------------------------------------------------------------
# C-16 — adr/day-range/remaining: kesir değerler, açık `*_ratio` ikizleri
# ---------------------------------------------------------------------------
class VolatilityRatioContractTests(unittest.TestCase):
    """C-16 — `*_pct` alanları KESİR; yanlarında açık `*_ratio` ikizleri olmalı."""

    def _volatility(self):
        closes = _ramp_closes(60)
        snap = calculate_snapshot("TESTTRY", closes[-1], {"5m": _bars(closes, volumes=[10.0] * 60),
                                                          "1d": _bars(closes, volumes=[10.0] * 60)})
        return snap["volatility"]

    def test_ratio_twins_exist_and_equal_the_fractional_pct_fields(self):
        vol = self._volatility()
        self.assertEqual(vol["adr_14_ratio"], vol["adr_14_pct"])
        self.assertEqual(vol["day_range_used_ratio"], vol["day_range_used_pct"])
        self.assertEqual(vol["remaining_capacity_ratio"], vol["remaining_capacity_pct"])

    def test_values_are_fractions_not_percent(self):
        vol = self._volatility()
        # Kesir (ör. 0.0079), yüzde (0.79) değil: |değer| < 1 olmalı.
        self.assertLess(abs(vol["adr_14_ratio"]), 1.0)
        self.assertLess(abs(vol["remaining_capacity_ratio"]), 1.0)


# ---------------------------------------------------------------------------
# C-17 — `vwap` yanıltıcı adı + `vwma_20` kopyası
# ---------------------------------------------------------------------------
class VwapNameAndSingleSourceTests(unittest.TestCase):
    """C-17 — `vwap_rolling_20` alanı olmalı; iki VW ortalama tek kaynaktan."""

    def _bars(self):
        closes = [100.0 + 3.0 * math.sin(i / 4.0) for i in range(60)]
        volumes = [10.0 + (i % 5) for i in range(60)]
        return _bars(closes, spread=0.7, volumes=volumes)

    def test_vwap_rolling_20_key_exists_and_matches_legacy_alias(self):
        bars = self._bars()
        snap = calculate_snapshot("TESTTRY", bars["closes"][-1], {"5m": bars})
        self.assertEqual(snap["volume"]["vwap_rolling_20"], snap["volume"]["vwap"])

    def test_both_vw_averages_come_from_the_single_helper(self):
        bars = self._bars()
        with patch("app.technical_analysis._rolling_vwma", return_value=123.456) as mocked:
            snap = calculate_snapshot("TESTTRY", bars["closes"][-1], {"5m": bars})
        self.assertEqual(snap["moving_averages"]["vwma_20"], 123.456)
        self.assertEqual(snap["volume"]["vwap_rolling_20"], 123.456)
        self.assertEqual(snap["volume"]["vwap"], 123.456)
        self.assertEqual(mocked.call_count, 2)

    def test_rolling_vwma_matches_a_textbook_last_n_average(self):
        self.assertAlmostEqual(_rolling_vwma([10.0, 20.0, 30.0], [1.0, 1.0, 2.0], 3),
                               (10 + 20 + 60) / 4.0, places=9)


# ---------------------------------------------------------------------------
# C-18 — confluence elliott bileşeni 0.7'ye kırpılmamalı
# ---------------------------------------------------------------------------
class ConfluenceElliottWeightTests(unittest.TestCase):
    """C-18 — elliott bileşeni [0,1] sinyal olmalı; 0.10 ağırlık gerçekleşmeli."""

    def _methodology(self):
        b = _bars(_ramp_closes(60), spread=0.5)
        return _methodology_analysis(b["opens"], b["highs"], b["lows"], b["closes"], b["volumes"])

    def test_elliott_component_is_a_unit_signal(self):
        m = self._methodology()
        # Ham güven 0.7 olarak korunur; bileşen normalize edilir (eski değer 0.7 idi).
        self.assertEqual(m["elliott"]["confidence"], 0.7)
        self.assertAlmostEqual(m["confluence"]["components"]["elliott"], 1.0, places=9)

    def test_conflict_weight_is_fully_realisable(self):
        # Eski katkı 0.10 * 0.7 = 0.07 idi; düzeltilmiş toplam skor 0.475 (eski 0.445).
        self.assertAlmostEqual(self._methodology()["confluence"]["score"], 0.475, places=4)


# ---------------------------------------------------------------------------
# C-19 — korelasyon getirisi: sıfır kapanışta eleman düşürmemeli
# ---------------------------------------------------------------------------
class CorrelationReturnsAlignmentTests(unittest.TestCase):
    """C-19 — `_returns` her bitişik çift için bir çıktı üretmeli (kayma yok)."""

    def test_returns_keep_one_entry_per_adjacent_pair(self):
        closes = [100.0 + math.sin(i / 5.0) for i in range(60)]
        closes[30] = 0.0
        rets = _returns(closes)
        # Eski kod sıfırın çıkış çiftini ATIYORDU -> len(len)-2.
        self.assertEqual(len(rets), len(closes) - 1)
        self.assertTrue(math.isnan(rets[30]))     # 0 -> sonraki çift geçersiz
        self.assertFalse(math.isnan(rets[29]))    # 0'a giriş çifti gerçek

    def test_pearson_aligns_nan_pairs_instead_of_shifting(self):
        a = [100.0 + math.sin(i / 5.0) for i in range(60)]
        b = [200.0 + math.cos(i / 7.0) for i in range(60)]
        a[30] = 0.0
        ra, rb = _returns(a), _returns(b)
        pairs = [(x, y) for x, y in zip(ra, rb) if not (math.isnan(x) or math.isnan(y))]
        reference = _manual_pearson([p[0] for p in pairs], [p[1] for p in pairs])
        self.assertAlmostEqual(_pearson(ra, rb), reference, places=9)
        # Eski, kaydıran yol farklı bir sayı üretiyordu (ölçülen sapma > 0.003).
        shifted = [x for x in ra if not math.isnan(x)]
        self.assertGreater(abs(_pearson(shifted, rb) - _pearson(ra, rb)), 0.001)


# ---------------------------------------------------------------------------
# C-20 — cluster_exposure detayları negatif korelasyonda kırpılmalı
# ---------------------------------------------------------------------------
class ClusterExposureDetailClampTests(unittest.TestCase):
    """C-20 — detay katkısı da `max(0, corr)` ile kırpılmalı."""

    def test_negative_correlation_detail_is_clamped(self):
        monitor = CorrelationMonitor()
        monitor._corr = {"NEGTRY": {"BTC": -0.6, "ETH": -0.4},
                         "NEWTRY": {"BTC": -0.6, "ETH": -0.4}}
        positions = {"NEGTRY": {"entry_price": 100.0, "quantity": 5.0}}
        out = cluster_exposure(positions, "NEWTRY", 300.0, monitor, "BTC", 2000.0)
        new_row = next(row for row in out["positions"] if row.get("new"))
        # Eski kod 300 * -0.6 = -180.0 yazıyordu.
        self.assertEqual(new_row["weighted"], 0.0)
        self.assertEqual(out["weighted_exposure"], 0.0)
        self.assertEqual(out["exposure_pct"], 0.0)


# ---------------------------------------------------------------------------
# C-21 — negatif tabanda haksız DEGRADED
# ---------------------------------------------------------------------------
class WalkForwardNegativeBaselineTests(unittest.TestCase):
    """C-21 — ilk pencere zarar iken iyileşme DEGRADED sayılmamalı."""

    def test_loss_to_profit_is_not_degraded(self):
        out = walk_forward_assessment([{"net_pnl": -100.0}, {"net_pnl": 50.0}])
        self.assertEqual(out["status"], "STABLE")

    def test_worsening_loss_is_degraded(self):
        out = walk_forward_assessment([{"net_pnl": -100.0}, {"net_pnl": -200.0}])
        self.assertEqual(out["status"], "DEGRADED")

    def test_positive_baseline_still_uses_the_ratio(self):
        self.assertEqual(walk_forward_assessment([{"net_pnl": 100.0}, {"net_pnl": 40.0}])["status"], "DEGRADED")
        self.assertEqual(walk_forward_assessment([{"net_pnl": 100.0}, {"net_pnl": 90.0}])["status"], "STABLE")


# ---------------------------------------------------------------------------
# C-22 — `_fisher_transform` içindeki ölü `prior` ataması
# ---------------------------------------------------------------------------
class FisherDeadVariableTests(unittest.TestCase):
    """C-22 — kullanılmayan `prior` ataması kaldırılmalı."""

    def test_no_dead_prior_assignment(self):
        source = textwrap.dedent(inspect.getsource(_fisher_transform))
        assigned = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
        self.assertNotIn("prior", assigned)


# ---------------------------------------------------------------------------
# C-23 — estimate_local_regime skor terimi doyumu
# ---------------------------------------------------------------------------
class LocalRegimeScoreTests(unittest.TestCase):
    """C-23 — radar skoru terimi |avg| >= 3'te ±15 tavanına çarpmamalı."""

    def _rows(self, score, count=4):
        return [{"data_ready": True, "snapshot": {}, "score": score,
                 "trend_direction": "bullish"} for _ in range(count)]

    def test_term_does_not_saturate_at_three(self):
        # Eski `avg_score*5`: avg=3.0 -> tavan (score 100.0).
        self.assertLess(estimate_local_regime(self._rows(3.0))["score"], 100.0)

    def test_score_is_strictly_monotonic_in_avg_score(self):
        s2 = estimate_local_regime(self._rows(2.0))["score"]
        s4 = estimate_local_regime(self._rows(4.0))["score"]
        s6 = estimate_local_regime(self._rows(6.0))["score"]
        self.assertLess(s2, s4)
        self.assertLess(s4, s6)

    def test_full_scale_still_reaches_one_hundred(self):
        out = estimate_local_regime(self._rows(LOCAL_REGIME_SCORE_SCALE))
        self.assertAlmostEqual(out["score"], 100.0, places=6)


if __name__ == "__main__":
    unittest.main()
