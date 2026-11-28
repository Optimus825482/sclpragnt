"""2026-11-27: hedef ulaşılabilirliği testleri.

Ağ yok: `binance_tr_public.klines` sahte asenkron fonksiyonla değiştirilir.
Ölçülen kural: p99 ileri maksimum < hedef x 0,5 ise aday bloklanır; bayrak
kapalı, önbellek boş veya bayat ise fail-open (None).
"""

import asyncio
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import target_attainability as att  # noqa: E402
from app.routers import monitoring  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(att, "GATE_ENABLED", False)
    att.reset_for_tests()
    yield
    att.reset_for_tests()


def _candles(closes, highs):
    """kline satırı: [open_time, open, high, low, close, volume, ...] asgari alanlar."""
    return [[i * 900_000, str(c), str(h), str(c), str(c), "1"] for i, (c, h) in enumerate(zip(closes, highs))]


def _seed(symbol="TESTUSDT", p99=1.2, target=3.0, age=0.0, interval="15m"):
    att._CACHE[symbol] = {
        "symbol": symbol,
        "loaded_at": time.time() - age,
        "primary": {
            "interval": interval,
            "p99": p99,
            "p95": p99 * 0.7,
            "p50": p99 * 0.3,
            "max": p99 * 1.4,
            "ge_target": 0.0,
            "target_pct": target,
            "bars": 400,
        },
        "by_horizon": {"15m": {"interval": interval, "p99": p99, "target_pct": target, "bars": 400}},
        "verdict": "reachable" if p99 >= target else "unreachable",
    }


def test_forward_max_uses_next_candles_only():
    out = att.forward_max_ratios([100, 110, 105], [100, 100, 100], k=1)
    assert out[0] == pytest.approx(0.10)
    assert out[1] == pytest.approx(0.05)
    assert out[2] != out[2]  # son mum ileri veri yok → NaN


def test_forward_max_respects_k():
    highs = [100, 101, 102, 130, 100]
    closes = [100, 100, 100, 100, 100]
    out = att.forward_max_ratios(highs, closes, k=3)
    assert out[0] == pytest.approx(0.30)  # 1..3 aralığındaki 130
    assert out[1] == pytest.approx(0.30)
    assert out[2] == pytest.approx(0.30)


def test_stats_for_klines_needs_min_bars(monkeypatch):
    monkeypatch.setattr(att, "MIN_BARS", 200)
    rows = _candles([100] * 50, [101] * 50)
    assert att.stats_for_klines(rows, 3.0, "15m", 1) is None


def test_stats_for_klines_reports_distribution(monkeypatch):
    monkeypatch.setattr(att, "MIN_BARS", 100)
    closes = [100] * 300
    highs = [100 + (5 if i % 50 == 0 else 0) for i in range(300)]
    st = att.stats_for_klines(_candles(closes, highs), 3.0, "15m", 1)
    assert st is not None
    # 300 mum -> açık (son) mum atılır -> 299 kapalı mum; sonuncusunun ileri
    # penceresi olmadığı için dağılım 298 örnekle hesaplanır.
    assert st["bars"] == 298
    assert st["max"] >= st["p99"] >= st["p50"]
    assert 0.0 <= st["ge_target"] <= 100.0


def test_gate_off_is_fail_open(monkeypatch):
    _seed(p99=0.5, target=3.0)
    monkeypatch.setattr(att, "GATE_ENABLED", False)
    assert att.block_reason("TESTUSDT", 3.0, 15) is None


def test_gate_blocks_clearly_unreachable_target(monkeypatch):
    _seed(p99=1.0, target=3.0)  # 1.0 < 3.0
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    reason = att.block_reason("TESTUSDT", 3.0, 15)
    assert reason and reason.startswith("hedef_ulasilamaz:")


def test_gate_passes_reachable_target(monkeypatch):
    _seed(p99=3.4, target=3.0)  # 3.4 >= 3.0
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    assert att.block_reason("TESTUSDT", 3.0, 15) is None


def test_gate_boundary_exact_target_passes(monkeypatch):
    _seed(p99=3.0, target=3.0)  # tam eşit → geçer
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    assert att.block_reason("TESTUSDT", 3.0, 15) is None


def test_gate_blocks_just_below_target(monkeypatch):
    _seed(p99=2.9, target=3.0)  # 2,9 < 3,0 → blok
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    assert att.block_reason("TESTUSDT", 3.0, 15) is not None


def test_gate_fail_open_when_stale(monkeypatch):
    _seed(p99=0.5, target=3.0, age=att.TTL_SEC + 10)
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    assert att.block_reason("TESTUSDT", 3.0, 15) is None


def test_gate_fail_open_without_measurement(monkeypatch):
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    assert att.block_reason("YOKUSDT", 3.0, 15) is None


def test_refresh_for_populates_cache_and_respects_ttl(monkeypatch):
    calls = {"15m": 0, "5m": 0}

    async def fake_klines(symbol, interval, limit=500, **_):
        calls[interval] += 1
        closes = [100] * 300
        highs = [101] * 300
        return _candles(closes, highs)

    monkeypatch.setattr(att.binance_tr_public, "klines", fake_klines)
    monkeypatch.setattr(att, "MIN_BARS", 100)

    started = asyncio.run(att.refresh_for(["TESTUSDT"]))
    assert started == 1
    first = att.stats("TESTUSDT")
    assert first is not None and first["primary"]["bars"] >= 100
    assert calls["15m"] == 1 and calls["5m"] == 1

    # TTL dolmadı → yeniden indirme yok
    assert asyncio.run(att.refresh_for(["TESTUSDT"])) == 0
    assert calls["15m"] == 1


def test_refresh_swallows_network_errors(monkeypatch):
    async def boom(*_, **__):
        raise RuntimeError("ağ yok")

    monkeypatch.setattr(att.binance_tr_public, "klines", boom)
    asyncio.run(att.refresh_for(["TESTUSDT"]))
    assert att.stats("TESTUSDT") is None


def test_gate_candidate_uses_attainability(monkeypatch):
    _seed(p99=0.8, target=3.0)
    monkeypatch.setattr(att, "GATE_ENABLED", True)
    candidate = {"symbol": "TESTUSDT", "target_pct": 3.0, "horizon_minutes": 15}
    reason = monitoring.gate_candidate(candidate)
    assert reason and reason.startswith("hedef_ulasilamaz:")

    monkeypatch.setattr(att, "GATE_ENABLED", False)
    assert monitoring.gate_candidate(candidate) is None


def test_stats_drop_the_unclosed_last_candle():
    """REST klines son satırda hâlâ oluşan mumu döndürür; ölçüme girmemeli."""
    rows = []
    for index in range(300):
        price = 100.0 + index * 0.01
        rows.append([index * 300_000, str(price), str(price * 1.005), str(price * 0.995), str(price), "10"])
    clean = att.stats_for_klines(rows, 3.0, "5m", 1)
    with_open_bar = rows[:-1] + [[9 * 10**9, "100", "999", "100", "100", "10"]]
    dirty = att.stats_for_klines(with_open_bar, 3.0, "5m", 1)
    # açık mumun fahiş high'ı dışlandığı için maksimum şişmiyor
    assert clean["max"] < 100 and dirty["max"] < 100
    # her iki durumda da açık mum dışlanır: 300 satır -> 299 kapalı mum -> 298 örnek
    assert clean["bars"] == dirty["bars"] == 298


def test_refresh_for_dedupes_repeated_symbols(monkeypatch):
    calls = []

    async def fake_fetch(symbol, target_pct, sem):
        calls.append(symbol)

    monkeypatch.setattr(att, "_fetch_one", fake_fetch)
    att.reset_for_tests()
    assert asyncio.run(att.refresh_for(["TESTUSDT", "testusdt", "TEST_USDT", ""])) == 1
    assert calls == ["TESTUSDT"]


def test_refresh_background_returns_task_without_blocking(monkeypatch):
    async def fake_refresh(symbols, target_pct=None):
        return len(list(symbols))

    monkeypatch.setattr(att, "refresh_for", fake_refresh)

    async def scenario():
        task = att.refresh_background(["TESTUSDT"])
        assert task is not None
        return await task

    assert asyncio.run(scenario()) == 1


def test_gate_candidate_warms_missing_stats_in_background(monkeypatch):
    scheduled = []
    monkeypatch.setattr(monitoring.target_attainability, "stats", lambda symbol: None)
    monkeypatch.setattr(
        monitoring.target_attainability, "refresh_background", lambda symbols: scheduled.append(list(symbols))
    )
    assert monitoring.gate_candidate({"symbol": "TESTUSDT", "target_pct": 3.0}) is None
    assert scheduled == [["TESTUSDT"]]
