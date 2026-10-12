"""BİRLEŞİK YÜKSELİŞ HAVUZU testleri (2026-10-13).

Kapsam:
- `is_genuinely_rising` ortak karar kapısı: fiyat yukarı + composite + confluence
  üçü birlikte; eksik/bayat alan fail-closed (geçirmez).
- TTL önbellek davranışı (taze → cache, bayat → None).
- `genuinely_rising_rows` süzgeci.
- `rising_pool` canlı yolu DEĞİŞTİRMEMELİ (UNIFIED_POOL_ENABLED varsayılan false).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import rising_pool as rp  # noqa: E402
from app.config import config  # noqa: E402


def _row(ret3=1.0, passes=True, comp=75.0, conf=3, block=None):
    r = {"ret3_pct": ret3, "passes": passes,
         "master_surge": {"composite_index": comp, "confluence_count": conf}}
    if block:
        r["block_reason"] = block
    return r


def test_gate_passes_when_all_three():
    assert rp.is_genuinely_rising(_row()) is True


def test_gate_fails_without_price_up():
    assert rp.is_genuinely_rising(_row(ret3=-1.0, passes=False)) is False


def test_gate_fails_low_composite():
    assert rp.is_genuinely_rising(_row(comp=40.0)) is False


def test_gate_fails_low_confluence():
    assert rp.is_genuinely_rising(_row(conf=1)) is False


def test_gate_fails_on_block_reason():
    assert rp.is_genuinely_rising(_row(block="EXTREME_LONG")) is False


def test_gate_fail_closed_on_missing_fields():
    # master_surge yoksa → geçirmez (fail-closed).
    assert rp.is_genuinely_rising({"ret3_pct": 1.0, "passes": True}) is False
    # ret3 yok ve passes yok → fiyat yukarı sayılmaz.
    assert rp.is_genuinely_rising({"master_surge": {"composite_index": 90, "confluence_count": 4}}) is False


def test_passes_flag_alone_counts_as_price_up():
    # ret3 negatif olsa da passes=True ise fiyat-yukarı koşulu sağlanır.
    assert rp.is_genuinely_rising(_row(ret3=-0.2, passes=True)) is True


def test_explicit_thresholds_override():
    # min_composite/min_confluence açıkça verilince onlar kullanılır.
    r = _row(comp=55.0, conf=2)
    assert rp.is_genuinely_rising(r, min_composite=50, min_confluence=2) is True
    assert rp.is_genuinely_rising(r, min_composite=60, min_confluence=2) is False


def test_ttl_cache_roundtrip():
    rp.reset_cache()
    assert rp.cached(now=1000.0) is None
    rp.store([{"symbol": "AAA", "pool_genuinely_rising": True}], now=1000.0)
    hit = rp.cached(now=1000.0 + rp.ttl_seconds() - 1)
    assert hit and hit[0]["symbol"] == "AAA"
    # TTL sonrası bayat → None
    assert rp.cached(now=1000.0 + rp.ttl_seconds() + 1) is None
    rp.reset_cache()


def test_genuinely_rising_rows_filter():
    rows = [{"symbol": "A", "pool_genuinely_rising": True},
            {"symbol": "B", "pool_genuinely_rising": False},
            {"symbol": "C"}]
    out = rp.genuinely_rising_rows(rows)
    assert [r["symbol"] for r in out] == ["A"]


def test_pool_disabled_by_default_no_live_change():
    """Aşama C'ye kadar canlı yol değişmemeli: bayrak varsayılan KAPALI."""
    assert config.UNIFIED_POOL_ENABLED is False
