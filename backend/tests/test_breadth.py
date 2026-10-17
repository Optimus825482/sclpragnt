"""app/rescan/breadth.py birim + NEDENSELLİK (kesme) testleri (2026-10-17)."""
import sys
import pathlib
import unittest
from datetime import datetime, timezone

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import breadth as B  # noqa: E402
from app.technical_analysis import _ema as live_ema  # noqa: E402


def _walk(rng, S, T, start_late=None):
    """Sentetik fiyat paneli: C, H, L, QV, TBQ (S,T); bazı sembollerin başı NaN (geç listeleme)."""
    r = rng.normal(0, 0.004, (S, T))
    C = 100.0 * np.exp(np.cumsum(r, axis=1))
    H = C * (1 + np.abs(rng.normal(0, 0.002, (S, T))))
    L = C * (1 - np.abs(rng.normal(0, 0.002, (S, T))))
    QV = rng.lognormal(10, 0.5, (S, T))
    TBQ = QV * rng.uniform(0.3, 0.7, (S, T))
    for s, k in (start_late or {}).items():
        for A in (C, H, L, QV, TBQ):
            A[s, :k] = np.nan
    return C, H, L, QV, TBQ


class TestBasics(unittest.TestCase):
    def test_ema_matches_live_sma_seeded(self):
        rng = np.random.default_rng(1)
        x = 100 + np.cumsum(rng.normal(0, 1, 300))
        e = B.ema(x, 20)
        self.assertTrue(np.isnan(e[:19]).all())
        for t in (19, 60, 299):
            self.assertAlmostEqual(e[t], live_ema(list(x[:t + 1]), 20), places=9)

    def test_ema_leading_nan_and_inner_nan(self):
        x = np.r_[np.full(5, np.nan), np.arange(1.0, 40.0)]
        x[20] = np.nan
        e = B.ema(x, 10)
        self.assertTrue(np.isnan(e[:14]).all())
        self.assertTrue(np.isfinite(e[14:]).all())

    def test_rolling_ext_and_sum_vs_naive(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(3, 80))
        mx, mn, sm = B.rolling_ext(x, 7, np.max), B.rolling_ext(x, 7, np.min), B.rolling_sum(x, 7)
        for t in range(6, 80):
            np.testing.assert_allclose(mx[:, t], x[:, t - 6:t + 1].max(axis=1))
            np.testing.assert_allclose(mn[:, t], x[:, t - 6:t + 1].min(axis=1))
            np.testing.assert_allclose(sm[:, t], x[:, t - 6:t + 1].sum(axis=1))
        self.assertTrue(np.isnan(mx[:, :6]).all())

    def test_adv_dec_counts_and_ratio(self):
        C = np.array([[1.0, 2.0, 2.0], [1.0, 0.5, 0.5], [1.0, 1.0, 1.1], [np.nan, np.nan, 5.0]])
        V = np.isfinite(C)
        a, d, n = B.adv_dec(C, V, 1)
        np.testing.assert_array_equal(a[1:], [1, 1])      # t=1: sembol0 ↑; t=2: sembol2 ↑
        np.testing.assert_array_equal(d[1:], [1, 0])
        self.assertTrue(np.isnan(B.ad_ratio(a, d, min_n=10)).all())
        np.testing.assert_allclose(B.ad_ratio(a, d, min_n=1)[1:], [0.5, 1.0])

    def test_pct_above(self):
        C = np.array([[2.0, 2.0], [1.0, 1.0], [3.0, 0.5]])
        E = np.ones_like(C) * 1.5
        V = np.ones(C.shape, bool)
        np.testing.assert_allclose(B.pct_above(C, E, V, min_n=1), [2 / 3, 1 / 3])

    def test_xs_rank_pct(self):
        X = np.array([[1.0, np.nan], [3.0, 5.0], [2.0, 4.0], [np.nan, np.nan]])
        r = B.xs_rank_pct(X)
        np.testing.assert_allclose(r[:3, 0], [0.0, 1.0, 0.5])
        np.testing.assert_allclose(r[1:3, 1], [1.0, 0.0])
        self.assertTrue(np.isnan(r[3]).all())

    def test_mcclellan_positive_when_advances_improve(self):
        T = 400
        adv = np.r_[np.full(200, 30.0), np.full(200, 70.0)]
        dec = 100.0 - adv
        m = B.mcclellan(adv, dec, 19, 39)
        self.assertGreater(m[250], 0)
        self.assertAlmostEqual(m[199], 0.0, places=6)

    def test_breadth_thrust_requires_low_then_high(self):
        r = np.r_[np.full(50, 0.5), np.full(30, 0.2), np.full(40, 0.8), np.full(200, 0.8)]
        s, th = B.breadth_thrust(r, 10, 0.40, 0.615, within=40)
        self.assertEqual(th[40], 0.0)                      # henüz düşük görülmedi, yüksek de değil
        self.assertEqual(th[100], 1.0)                     # düşüğün ardından sıçradı
        self.assertEqual(th[-1], 0.0)                      # within penceresi geçti
        _, th2 = B.breadth_thrust(np.full(300, 0.8), 10, 0.40, 0.615, within=40)
        self.assertEqual(th2[-1], 0.0)                     # düşük hiç görülmedi → itiş yok

    def test_net_highs_lows(self):
        T = 60
        H = np.vstack([np.arange(T) * 1.0 + 1, np.full(T, 5.0)])
        L = H - 0.5
        V = np.ones((2, T), bool)
        out = B.net_highs_lows(np.zeros((2, T)), H, L, V, window=10, min_n=1)
        self.assertAlmostEqual(out[30], 0.5)               # sembol0 yeni tepe, sembol1 değil (yeni dip yok)
        self.assertTrue(np.isnan(out[5]))

    def test_beta_corr(self):
        rng = np.random.default_rng(5)
        rb = rng.normal(0, 0.01, 600)
        r = np.vstack([2.0 * rb, -1.0 * rb, rng.normal(0, 0.01, 600)])
        beta, corr = B.rolling_beta_corr(r, rb, 288)
        self.assertAlmostEqual(beta[0, -1], 2.0, places=6)
        self.assertAlmostEqual(beta[1, -1], -1.0, places=6)
        self.assertAlmostEqual(corr[0, -1], 1.0, places=6)
        self.assertLess(abs(corr[2, -1]), 0.2)
        self.assertTrue(np.isnan(beta[0, 100]))


class TestSwingsAndSmt(unittest.TestCase):
    def test_swing_confirmed_with_lag(self):
        h = np.array([1, 2, 3, 2, 1, 1, 2, 3, 4, 5, 4, 3, 2, 1, 1, 1], dtype=float)
        sw = B.fractal_swings(h, h, k=2)
        # tepe i=2 (3.0) t=4'te onaylanır; i=9 (5.0) t=11'de
        self.assertTrue(np.isnan(sw["sh"][3]))
        self.assertEqual(sw["sh"][4], 3.0)
        self.assertEqual(sw["sh_age"][4], 2.0)
        self.assertEqual(sw["sh"][11], 5.0)
        self.assertEqual(sw["sh_prev"][11], 3.0)
        self.assertEqual(sw["sh_age"][12], 3.0)

    def test_swing_truncation_causal(self):
        rng = np.random.default_rng(9)
        h = 100 + np.cumsum(rng.normal(0, 1, 400))
        l = h - np.abs(rng.normal(0, 0.3, 400))
        full = B.fractal_swings(h, l, 3)
        for cut in (120, 250, 399):
            part = B.fractal_swings(h[:cut], l[:cut], 3)
            for k in full:
                np.testing.assert_array_equal(full[k][:cut], part[k], err_msg=k)

    def test_smt_bull_and_bear(self):
        def lv(last, prev, age=5.0):
            n = 4
            return {k: np.full(n, v) for k, v in (("sl", last), ("sl_prev", prev), ("sl_age", age), ("sh", last), ("sh_prev", prev), ("sh_age", age))}
        sym, ref = lv(10.0, 9.0), lv(8.0, 9.0)
        low, high = B.smt_flags(sym, ref)
        self.assertEqual(low[0], 1.0)                      # sembol HL, ref LL
        self.assertEqual(high[0], 1.0)                     # sembol HH, ref LH
        low2, high2 = B.smt_flags(ref, sym)
        self.assertEqual(low2[0], -1.0)
        self.assertEqual(high2[0], -1.0)
        old = lv(10.0, 9.0, age=100.0)
        low3, _ = B.smt_flags(old, ref)
        self.assertTrue(np.isnan(low3[0]) or low3[0] == 0.0)
        self.assertEqual(B.smt_flags(sym, lv(10.0, 9.0))[0][0], 0.0)


class TestTime(unittest.TestCase):
    def _ms(self, y, m, d, hh, mm):
        return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)

    def test_clock_and_killzone(self):
        # 2026-10-17 Cumartesi 12:30 UTC = 15:30 TR → NY killzone başlangıcı
        c = B.tr_clock(np.array([self._ms(2026, 10, 17, 12, 30), self._ms(2026, 10, 17, 12, 25), self._ms(2026, 10, 19, 0, 5),
                                 self._ms(2026, 10, 19, 0, 0), self._ms(2026, 10, 19, 7, 0)]))
        self.assertEqual(list(c["kz"]), [3, 0, 1, 1, 2])    # 15:30 NY; 15:25 yok; 03:05 Asya; 03:00 Asya (dâhil); 10:00 Londra
        self.assertEqual(list(c["hour"]), [15, 15, 3, 3, 10])
        self.assertEqual(list(c["dow"]), [5, 5, 0, 0, 0])   # Cumartesi=5, Pazartesi=0

    def test_day_boundary_tr(self):
        # TR gece yarısı = 21:00 UTC bir önceki gün
        c = B.tr_clock(np.array([self._ms(2026, 10, 16, 21, 0)]))
        self.assertEqual((c["hour"][0], c["dow"][0]), (0, 5))

    def test_opening_range_breakout(self):
        T = 288 * 3
        c = np.full(T, 100.0)
        h, l = c + 1.0, c - 1.0
        c[288 + 40:288 + 60] = 105.0                       # gün 2'de OR (ilk 6 bar: 99–101) üstüne kırılım
        h[288 + 40:288 + 60] = 105.5
        r = B.opening_range(h, l, c, 0, or_bars=6, fresh=12)
        self.assertTrue(np.isnan(r["state"][288 + 3]))      # aralık henüz bitmedi
        self.assertEqual(r["state"][288 + 30], 0.0)
        self.assertEqual(r["state"][288 + 45], 1.0)
        self.assertAlmostEqual(r["dist"][288 + 45], (105.0 / 101.0 - 1) * 100, places=6)
        self.assertEqual(r["fresh"][288 + 41], 1.0)
        self.assertEqual(r["fresh"][288 + 58], 0.0)         # ilk kırılımdan > 12 bar sonra
        # NEDENSEL: kırılım barından önceki değerler, kırılım verisi olmadan da aynı
        r2 = B.opening_range(h[:288 + 40], l[:288 + 40], c[:288 + 40], 0)
        np.testing.assert_array_equal(r["state"][:288 + 40], r2["state"])

    def test_opening_range_utc_offset(self):
        T = 288 * 3
        c = np.full(T, 100.0)
        h, l = c + 1.0, c - 1.0
        r = B.opening_range(h, l, c, 36, or_bars=6)
        self.assertTrue(np.isnan(r["state"][36 + 3]))       # UTC gününün OR'si 36'dan başlar
        self.assertEqual(r["state"][36 + 10], 0.0)
        self.assertTrue(np.isnan(r["state"][10]))           # ilk (yarım) UTC günü → NaN

    def test_prev_day_sweep(self):
        T = 288 * 3
        c = np.full(T, 100.0)
        h, l = c + 1.0, c - 1.0                              # PDH 101, PDL 99
        l[288 + 100] = 98.0                                  # gün 2'de PDL süpürüldü
        r = B.prev_day_levels(h, l, c, 0, sweep_bars=12)
        self.assertEqual(r["sweep_pdl"][288 + 105], 1.0)    # süpürme sonrası fiyat PDL üstünde
        self.assertEqual(r["sweep_pdl"][288 + 120], 0.0)
        self.assertTrue(np.isnan(r["sweep_pdl"][100]))      # ilk günün önceki günü yok
        self.assertAlmostEqual(r["dist_pdh"][288 + 5], (100 / 101 - 1) * 100)

    def test_rvol_tod_constant_and_spike(self):
        T = 288 * 6
        qv = np.full(T, 10.0)
        qv[288 * 5 + 100] = 100.0
        r = B.rvol_tod(qv, smooth=1, days=7, min_days=3)
        self.assertTrue(np.isnan(r[288 * 2 + 5]))           # < 3 önceki gün
        self.assertAlmostEqual(r[288 * 4 + 50], 1.0)
        self.assertAlmostEqual(r[288 * 5 + 100], 10.0)


class TestShield(unittest.TestCase):
    def test_matches_live_ema_on_window(self):
        rng = np.random.default_rng(4)
        hourly = 3_000_000 * np.exp(np.cumsum(rng.normal(0, 0.004, 400)))
        prior = hourly[:300]
        fut_h = hourly[300:]
        # 5 dk fiyat: saat içinde 12 bar, saatin son barı saat kapanışı
        price5 = np.repeat(fut_h, 12) * (1 + rng.normal(0, 0.0005, len(fut_h) * 12))
        price5[11::12] = fut_h
        sh = B.btc_shield_ema(price5, prior)
        for k in (5, 11, 12 + 3, 60 + 7, 95):
            hours_done = k // 12
            closes = list(prior) + list(fut_h[:hours_done])
            if k % 12 == 11:                                # saat kapanışı: bu saat "forming" sayılır
                pass
            window = closes[-209:] + [price5[k]]
            self.assertAlmostEqual(sh[k] / live_ema(window, 200), 1.0, places=9, msg=str(k))


class TestCausality(unittest.TestCase):
    def test_all_features_truncation(self):
        rng = np.random.default_rng(11)
        S, T = 14, 1200
        C, H, L, QV, TBQ = _walk(rng, S, T, start_late={5: 400, 9: 700})
        usd = 40.0 * np.exp(np.cumsum(rng.normal(0, 0.0003, T)))
        thr = float(np.nanpercentile(QV, 10) * 288 * 0.9)

        def run(cut):
            c, h, l, q, tb = (a[:, :cut] for a in (C, H, L, QV, TBQ))
            V = B.valid_universe(q, thr)
            out = dict(B.market_features(c, h, l, q, tb, V))
            out.update(B.btc_usd_features(c[0], usd[:cut]))
            mk = {nm: out[f"m_ret_{nm}"] for nm in ("15", "60", "240")}
            lvl = B.ew_index(c, V)
            out["_lvl"] = lvl
            for nm, a in B.symbol_feature_iter(c, h, l, q, V, 0, lvl, mk, out["usd_ret_60"]):
                out[nm] = a
            out["_V"] = V
            return out

        full = run(T)
        for cut in (500, 900):
            part = run(cut)
            for k, v in part.items():
                a, b = np.asarray(full[k])[..., :cut], np.asarray(v)
                np.testing.assert_allclose(a, b, rtol=1e-4, atol=1e-5, equal_nan=True, err_msg=f"{k} cut={cut}")
        # sembol özelliklerinin gerçekten üretildiğini ve sonlu değer taşıdığını doğrula
        for nm in B.SYMBOL_FEATURES:
            self.assertIn(nm, full)
        self.assertTrue(np.isfinite(full["rk_60"]).any())
        self.assertTrue(np.isfinite(full["b_pct_ema50_5m"]).any())

    def test_future_change_does_not_move_past(self):
        rng = np.random.default_rng(12)
        S, T = 10, 800
        C, H, L, QV, TBQ = _walk(rng, S, T)
        V = np.ones((S, T), bool)
        V[:, :50] = False
        base = B.market_features(C, H, L, QV, TBQ, V)
        C2, H2 = C.copy(), H.copy()
        C2[:, 600:] *= 1.5
        H2[:, 600:] *= 1.5
        alt = B.market_features(C2, H2, L, QV, TBQ, V)
        for k in base:
            np.testing.assert_allclose(base[k][:600], alt[k][:600], rtol=1e-5, atol=1e-6, equal_nan=True, err_msg=k)


class TestShieldCausal(unittest.TestCase):
    def test_shield_truncation(self):
        rng = np.random.default_rng(21)
        hourly = 3_000_000 * np.exp(np.cumsum(rng.normal(0, 0.004, 330)))
        prior = hourly[:260]
        price5 = np.repeat(hourly[260:], 12) * (1 + rng.normal(0, 0.0005, 70 * 12))
        full = B.btc_shield_ema(price5, prior)
        for cut in (150, 301, 600):
            part = B.btc_shield_ema(price5[:cut], prior)
            np.testing.assert_allclose(full[:cut], part, rtol=1e-12, equal_nan=True)


class TestStudyHelpers(unittest.TestCase):
    def test_bh_q_monotone_and_nan(self):
        from scripts import breadth_study as S
        p = np.array([0.001, 0.04, 0.03, np.nan, 0.5])
        q = S.bh_q(p)
        self.assertTrue(np.isnan(q[3]))
        self.assertAlmostEqual(q[0], 0.004, places=6)       # 0.001 * 4 / 1
        self.assertLessEqual(q[2], q[1] + 1e-12)            # küçük p → küçük/eşit q
        self.assertTrue(np.all(q[[0, 1, 2, 4]] <= 1.0))

    def test_bucket_codes_edges_from_other_blocks(self):
        from scripts import breadth_study as S
        rng = np.random.default_rng(3)
        pool_blk = np.repeat([0, 1, 2], 3000)
        pool_x = np.r_[rng.normal(0, 1, 3000), rng.normal(10, 1, 3000), rng.normal(0, 1, 3000)]   # blok 1 kaymış
        x = np.array([0.0, 0.0, 10.0])
        blk = np.array([0, 2, 1])
        codes, labs = S.bucket_codes(x, blk, pool_x, pool_blk)
        self.assertEqual(len(labs), 3)
        # blok 0 için kenarlar blok 1+2 havuzundan (karışık) → 0.0 alt/orta; blok 1 için kenarlar blok 0+2'den (≈N(0,1)) → 10 en üst tersil
        self.assertEqual(codes[2], 2)
        self.assertLess(codes[0], 2)
        cat, labs2 = S.bucket_codes(np.array([0.0, 1.0, np.nan]), np.array([0, 1, 2]), np.array([0.0, 1.0] * 100), np.array([0, 1, 2, 0] * 50))
        self.assertEqual(list(cat), [0, 1, -1])
        self.assertEqual(labs2, ["0", "1"])

    def test_group_u_and_cluster_t(self):
        from scripts import breadth_study as S
        XE = np.array([[5.0], [1.0]])
        XB = np.array([[1.0], [2.0], [3.0], [4.0], [0.0], [1.0], [5.0], [2.0]])
        b_g = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        U = S.group_u(XE, XB, b_g, min_b=3)
        self.assertAlmostEqual(U[1, 0], 1.5 / 4)
        d = np.r_[np.full(50, 0.2), np.full(50, 0.2)]
        mu, se, t, g = S.cluster_t(d, np.arange(100) // 10)
        self.assertAlmostEqual(mu, 0.2)
        self.assertEqual(g, 10)


if __name__ == "__main__":
    unittest.main()
