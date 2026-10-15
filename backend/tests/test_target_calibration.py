"""2026-10-15 (radar iyileştirme): ölçülmüş MFE hedef kalibrasyonu testleri.

Ağ/DB yok: DB çağrıları sahte (monkeypatch) fonksiyonlarla değiştirilir.
"""
import asyncio
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database, target_calibration  # noqa: E402
from app.config import config  # noqa: E402
from app.routers import velocity  # noqa: E402

DATA = {
    5: {"n": 40, "p50": 1.23, "p70": 2.0, "p30": 0.5},
    15: {"n": 50, "p50": 9.0, "p70": 9.5, "p30": 8.0},
    60: {"n": 33, "p50": 0.1, "p70": 0.2, "p30": 0.05},
}


@pytest.fixture(autouse=True)
def _restore_calibration_state(monkeypatch):
    """Her testten sonra önbellek ve bayraklar başlangıç durumuna döner."""
    monkeypatch.setattr(target_calibration, "TARGET_CALIBRATION_ENABLED", False)
    monkeypatch.setattr(target_calibration, "TARGET_CALIBRATION_QUANTILE", "p50")
    yield
    target_calibration.set_calibration_for_tests({}, 0.0)


def _enable(monkeypatch, quantile: str = "p50"):
    monkeypatch.setattr(target_calibration, "TARGET_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(target_calibration, "TARGET_CALIBRATION_QUANTILE", quantile)


def test_disabled_flag_returns_fallback(monkeypatch):
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(5, 2.0) == 2.0


def test_enabled_fresh_cache_uses_p50_rounded(monkeypatch):
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(5, 2.0) == 1.2


def test_enabled_fresh_cache_clamps_high_and_low(monkeypatch):
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(15, 2.0) == target_calibration.TARGET_MAX_PCT
    assert target_calibration.calibrated_target_pct(60, 2.0) == target_calibration.TARGET_MIN_PCT


def test_quantile_env_selects_other_percentile(monkeypatch):
    _enable(monkeypatch, quantile="p70")
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(5, 3.0) == 2.0


def test_invalid_quantile_falls_back_to_p50(monkeypatch):
    _enable(monkeypatch, quantile="p99")
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(5, 2.0) == 1.2


def test_stale_cache_returns_fallback(monkeypatch):
    _enable(monkeypatch)
    stale_at = time.time() - target_calibration.TARGET_CALIBRATION_TTL_SEC - 5
    target_calibration.set_calibration_for_tests(DATA, stale_at)
    assert target_calibration.calibrated_target_pct(5, 2.0) == 2.0


def test_empty_cache_returns_fallback(monkeypatch):
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests({}, time.time())
    assert target_calibration.calibrated_target_pct(5, 2.0) == 2.0


def test_missing_horizon_returns_fallback(monkeypatch):
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests(DATA, time.time())
    assert target_calibration.calibrated_target_pct(240, 2.0) == 2.0
    assert target_calibration.calibrated_target_pct(0, 2.0) == 2.0


def test_refresh_stores_database_result(monkeypatch):
    async def fake_quantiles(*_args, **_kwargs):
        return DATA

    monkeypatch.setattr(database, "get_unified_mfe_quantiles", fake_quantiles)
    _enable(monkeypatch)
    result = asyncio.run(target_calibration.refresh_target_calibration())
    assert result == DATA
    assert target_calibration.calibrated_target_pct(5, 2.0) == 1.2


def test_mfe_quantiles_db_error_returns_empty_dict(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(database, "_run_db", boom)
    assert asyncio.run(database.get_unified_mfe_quantiles()) == {}


def test_dynamic_target_pct_works_without_horizon_kwarg(monkeypatch):
    """Yeni kwarg varsayılanlı olduğu için mevcut çağrılar aynı sonucu vermeli."""
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests(DATA, time.time())
    # Mevcut testlerle aynı çağrı biçimi (tests/test_m2_velocity_fixes.py).
    base = velocity.dynamic_target_pct(60.0, 2.0)
    assert isinstance(base, float)
    assert base == velocity.dynamic_target_pct(60.0, 2.0, horizon_minutes=0)


def test_dynamic_target_pct_uses_calibration_when_horizon_known(monkeypatch):
    _enable(monkeypatch)
    target_calibration.set_calibration_for_tests(DATA, time.time())
    # p50=9.0 → 4.5'e kelepçelenir (config üst sınırı bunun altındaysa o geçerli).
    high = velocity.dynamic_target_pct(60.0, 2.0, horizon_minutes=15)
    assert high == round(max(config.MONITORING_TARGET_PCT_MIN,
                             min(config.MONITORING_TARGET_PCT_MAX, 4.5)), 3)
    # p50=0.1 → 0.6; net-kâr tabanı (komisyon+spread dahil) hâlâ uygulanır, yani
    # sonuç kalibrasyonsuz hesapla aynıdır.
    low = velocity.dynamic_target_pct(60.0, 2.0, horizon_minutes=60)
    monkeypatch.setattr(target_calibration, "TARGET_CALIBRATION_ENABLED", False)
    assert low == velocity.dynamic_target_pct(60.0, 2.0)
