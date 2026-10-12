"""Global→TR residual lead-lag sinyali testleri (2026-10-12).

- `compute_residual`: β eğimi + residual matematiği doğru mu (saf fonksiyon).
- Look-ahead: yalnız kapanmış barlar (`_closed`) kullanılmalı.
- `detect_leadlag_candidates`: TR'de listeli olmayan sembol atlanır; TR eşlemesi.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import lead_lag_signal as ll  # noqa: E402


def test_compute_residual_beta_and_residual():
    # r_gl = 2*r_tr  → beta≈2, residual = r_gl - 2*r_tr ≈ 0
    tr = [0.1, -0.2, 0.3, -0.1, 0.4, -0.3, 0.2, -0.2, 0.1, -0.15] * 5
    gl = [x * 2 for x in tr]
    out = ll.compute_residual(gl, tr)
    assert out is not None
    assert abs(out["beta"] - 2.0) < 0.01, f"beta ~2 olmalı, gelen {out['beta']}"
    assert abs(out["residual"]) < 0.5, "residual sıfıra yakın olmalı"


def test_compute_residual_detects_unpriced_move():
    # Gerçekçi: TR gerçek varyansa sahip; GL = TR kopyası AMA son barda TR'de
    # olmayan +2 sıçrama → beta≈1, residual ≈ +2 (lead-lag görünür).
    tr = [(((-1) ** k) * 0.5) + (k % 3) * 0.1 for k in range(59)] + [0.2]
    gl = list(tr[:-1]) + [tr[-1] + 2.0]
    out = ll.compute_residual(gl, tr)
    assert out is not None
    assert abs(out["beta"] - 1.0) < 0.1, f"beta ~1 olmalı, gelen {out['beta']}"
    assert out["residual"] > 1.5, f"GL öncü sıçrama residual'da görünmeli, gelen {out['residual']}"


def test_compute_residual_zero_variance_tr_returns_none():
    # TR tamamen sabit → beta tanımsız (0'a bölme) → None (koruma)
    assert ll.compute_residual([0.0] * 60, [0.0] * 60) is None


def test_compute_residual_insufficient_data():
    assert ll.compute_residual([0.1] * 10, [0.1] * 10) is None


def test_closed_bars_exclude_open_bar():
    # bar_ms=300000; now = 10. barın açılış anı → 10. bar KAPANMAMIŞ.
    now = 10 * 300_000
    bars = [[i * 300_000, 0, 0, 0, 100.0 + i] for i in range(12)]
    closed = ll._closed(bars, now, 300_000)
    # open_time+300000 <= now → i=10 → 10*300000+300000 > now → hariç
    assert len(closed) == 10, f"10 kapanmış bar beklenir, gelen {len(closed)}"


def test_detect_skips_non_tr_symbols():
    class _A:
        async def klines(self, sym, iv, limit):
            return [[i * 300_000, 0, 0, 0, 100.0 + (i if "USDT" in sym else 0)]
                    for i in range(200)]

    class _TA:
        klines = _A.klines

    out = asyncio.run(ll.detect_leadlag_candidates(
        now_ms=300_000 * 201, symbols=["NOTONTRXYZUSDT"], adapter=_A(), tr_adapter=_TA()))
    assert out == [], "TR'de listeli olmayan sembol atlanmalı"


def test_leadlag_signal_module_documents_no_alpha_claim():
    """Kaynak kilit: modül dürüst uyarı taşımalı (kârlılık iddiası YOK)."""
    import inspect
    src = inspect.getsource(ll)
    assert "kârlılık iddiası YOKTUR" in src or "karlilik iddiasi YOKTUR" in src, \
        "modül 'kârlılık iddiası yok' uyarısı taşımalı"
