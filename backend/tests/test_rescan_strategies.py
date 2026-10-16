"""Yeni dedektör prototipleri (app/rescan/strategies.py) — sentetik seri birim testleri."""
import numpy as np

from app.rescan import strategies as S


def _arr(closes, vols=None, qv=None, bar_ms=S.BAR_5M_MS, lows=None, highs=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    lows = np.asarray(lows if lows is not None else closes * 0.998, dtype=float)
    highs = np.asarray(highs if highs is not None else closes * 1.002, dtype=float)
    vols = np.asarray(vols if vols is not None else np.ones(n), dtype=float)
    qv = np.asarray(qv if qv is not None else np.full(n, 1e6), dtype=float)
    ot = np.arange(n, dtype=float) * bar_ms
    return np.column_stack([ot, closes, highs, lows, closes, vols, qv])


def _wavy(n, base=100.0, amp=0.05):
    return base + amp * np.sin(np.arange(n) * 0.9)


def test_ema_matches_recursion():
    x = np.random.default_rng(1).normal(100, 1, 200)
    out = np.empty(200); out[0] = x[0]
    a = 2 / (9 + 1)
    for i in range(1, 200):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    assert np.allclose(S.ema(x, 9), out)


def test_run_length_and_cooldown():
    r = S.run_length(np.array([1, 1, 0, 1, 1, 1, 0], dtype=bool))
    assert list(r) == [1, 2, 0, 1, 2, 3, 0]
    assert list(S.cooldown(np.array([5, 6, 20, 21, 40]), 12)) == [5, 20, 40]


# ---------------------------------------------------------------- 1. ema_fan_5m
def _fan_series():
    # yavaş düşüş (EMA7 < EMA20 < EMA99), sonra düzgün yükseliş: yelpaze açılır, 6 bar kazancı ~%2
    down = np.linspace(110, 100, 350)
    up = 100 * (1 + 0.004) ** np.arange(1, 12)
    return np.concatenate([down, up])


def test_ema_fan_fires_on_fresh_fan_not_on_flat_or_exploded():
    arr = _arr(_fan_series())
    idx = S.ema_fan_5m(arr, k=2, g_min=0.8, rsi_max=101.0, min_quote_24h=0.0)
    assert len(idx) == 1 and idx[0] >= 350
    assert len(S.ema_fan_5m(_arr(_wavy(400)), k=2, g_min=0.8, rsi_max=101.0, min_quote_24h=0.0)) == 0
    down = np.linspace(110, 100, 350)
    exploded = np.concatenate([down, 100 * 1.05 ** np.arange(1, 12)])  # her bar %5: 6 bar kazancı > %4
    assert len(S.ema_fan_5m(_arr(exploded), k=2, g_min=0.8, rsi_max=101.0, min_quote_24h=0.0)) == 0
    assert len(S.ema_fan_5m(arr, k=2, g_min=0.8, rsi_max=101.0, min_quote_24h=1e18)) == 0
    assert len(S.ema_fan_5m(arr, k=2, g_min=0.8, rsi_max=10.0, min_quote_24h=0.0)) == 0


# ---------------------------------------------------------------- 2. breakout_compress_5m
def test_breakout_fires_after_squeeze_with_volume():
    rng = np.random.default_rng(3)
    wide = 100 + np.cumsum(rng.normal(0, 0.35, 300))       # geniş oynak dönem
    tight = wide[-1] + rng.normal(0, 0.02, 60)               # sıkışma
    brk = np.array([tight.mean() + 1.2])                    # zirve kırılımı (~%1.2)
    closes = np.concatenate([wide, tight, brk])
    vols = np.ones(len(closes)); vols[-1] = 5.0
    arr = _arr(closes, vols=vols, highs=closes + 0.0, lows=closes - 0.0)
    arr[:-1, 2] = np.concatenate([wide, tight]) + 0.01
    idx = S.breakout_compress_5m(arr, vol_min=1.5, rsi_max=101.0, min_quote_24h=0.0)
    assert len(idx) == 1 and idx[0] == len(closes) - 1
    # hacim yok -> sinyal yok
    arr2 = arr.copy(); arr2[:, 5] = 1.0
    assert len(S.breakout_compress_5m(arr2, vol_min=1.5, rsi_max=101.0, min_quote_24h=0.0)) == 0
    # sıkışma yok (hep geniş) -> sinyal yok
    c3 = np.concatenate([wide, wide[-1] + np.cumsum(rng.normal(0, 0.35, 60)), [wide[-1] + 400]])
    v3 = np.ones(len(c3)); v3[-1] = 5.0
    arr3 = _arr(c3, vols=v3)
    assert len(S.breakout_compress_5m(arr3, vol_min=1.5, rsi_max=101.0, min_quote_24h=0.0, gain3_max=1e9)) == 0
    # patlamış (3 bar kazancı büyük) -> gain3 kapısı
    closes4 = closes.copy(); closes4[-1] = closes4[-4] * 1.06
    arr4 = _arr(closes4, vols=vols, highs=closes4 + 0.0)
    arr4[:-1, 2] = np.concatenate([wide, tight]) + 0.01
    assert len(S.breakout_compress_5m(arr4, vol_min=1.5, rsi_max=101.0, min_quote_24h=0.0, gain3_max=4.0)) == 0
    assert len(S.breakout_compress_5m(_arr(_wavy(400)), rsi_max=101.0, min_quote_24h=0.0)) == 0


# ---------------------------------------------------------------- 3. rs_vs_btc_5m
def _rs_series(n_flat=330, ups=7, step=0.4):
    sym = np.concatenate([_wavy(n_flat), _wavy(n_flat)[-1] * (1 + step / 100) ** np.arange(1, ups + 1)])
    return sym


def test_rs_vs_btc_fires_when_btc_flat_and_not_when_btc_pumps():
    sym = _rs_series()
    n = len(sym)
    arr = _arr(sym, lows=sym * 0.999 + np.arange(n) * 0.0)
    arr[:, 3] = sym * 0.999  # düşükler kapanışla birlikte yükselir
    ot = arr[:, 0]
    btc_flat = np.full(n, 1000.0)
    idx = S.rs_vs_btc_5m(arr, ot, btc_flat, x=1.0, vol_min=0.0, min_quote_24h=0.0)
    assert len(idx) == 1 and idx[0] >= 330
    btc_up = 1000.0 * (1 + 0.004) ** np.maximum(np.arange(n) - 329, 0)  # BTC aynı hızda yükseliyor
    assert len(S.rs_vs_btc_5m(arr, ot, btc_up, x=1.0, vol_min=0.0, min_quote_24h=0.0)) == 0
    assert len(S.rs_vs_btc_5m(_arr(_wavy(400)), np.arange(400) * 300000.0, np.full(400, 1000.0), x=1.0,
                              vol_min=0.0, min_quote_24h=0.0)) == 0
    # BTC verisi yok -> sinyal yok
    assert len(S.rs_vs_btc_5m(arr, np.zeros(0), np.zeros(0), x=1.0, vol_min=0.0, min_quote_24h=0.0)) == 0


# ---------------------------------------------------------------- 4. persist_1m
def test_persist_1m_fires_on_steady_climb_not_on_flat_or_exploded():
    rng = np.random.default_rng(5)
    flat = 100 + 0.02 * np.sin(np.arange(1700) * 0.7)
    climb = flat[-1] * (1 + 0.0009) ** np.arange(1, 21)       # 20 dk, dakikada %0.09 -> ~%1.8
    closes = np.concatenate([flat, climb])
    vols = np.ones(len(closes)); vols[1700:] = 3.0
    arr = _arr(closes, vols=vols, bar_ms=S.BAR_1M_MS)
    idx = S.persist_1m(arr, m=8, g_min=0.6, vol_min=1.2, rsi_max=101.0, min_quote_24h=0.0)
    assert len(idx) == 1 and idx[0] >= 1700
    assert len(S.persist_1m(_arr(flat, bar_ms=S.BAR_1M_MS), m=8, rsi_max=101.0, min_quote_24h=0.0)) == 0
    exploded = np.concatenate([flat, flat[-1] * 1.02 ** np.arange(1, 21)])  # dakikada %2 -> 8 dk >%3
    assert len(S.persist_1m(_arr(exploded, vols=vols, bar_ms=S.BAR_1M_MS), m=8, rsi_max=101.0, min_quote_24h=0.0)) == 0
    arr_novol = _arr(closes, bar_ms=S.BAR_1M_MS)
    assert len(S.persist_1m(arr_novol, m=8, vol_min=1.2, rsi_max=101.0, min_quote_24h=0.0)) == 0
    assert len(S.persist_1m(arr, m=8, rsi_max=101.0, min_quote_24h=1e18)) == 0


def test_persist_1m_align_5m_only_on_5m_boundaries():
    flat = 100 + 0.02 * np.sin(np.arange(1700) * 0.7)
    climb = flat[-1] * (1 + 0.0009) ** np.arange(1, 41)
    closes = np.concatenate([flat, climb])
    vols = np.ones(len(closes)); vols[1700:] = 3.0
    arr = _arr(closes, vols=vols, bar_ms=S.BAR_1M_MS)
    idx = S.persist_1m(arr, m=8, g_min=0.6, vol_min=1.2, rsi_max=101.0, min_quote_24h=0.0, align_5m=True)
    assert len(idx) >= 1
    assert all((S.signal_time_ms(arr, int(i), S.BAR_1M_MS) % S.BAR_5M_MS) == 0 for i in idx)


def test_signal_time_is_bar_close():
    arr = _arr(_wavy(30))
    assert S.signal_time_ms(arr, 3) == 4 * S.BAR_5M_MS
    arr1 = _arr(_wavy(30), bar_ms=S.BAR_1M_MS)
    assert S.signal_time_ms(arr1, 3, S.BAR_1M_MS) == 4 * S.BAR_1M_MS
