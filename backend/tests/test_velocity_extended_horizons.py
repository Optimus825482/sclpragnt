"""Uzun ufuklu velocity profilleri (30m/60m) regresyon kilitleri (2026-10-13).

Kullanıcı: "velocity'ye 30m ve 60m de eklesek nasıl olur?"
ÖLÇÜM (5909 gerçek aday, 15 gün): medyan MFE 15m +0.18% → 30m +0.53% → 60m +1.04%
(zirveye daha çok ulaşıyor) AMA ufuk SONU getirisi negatif (30m −0.31%, 60m −0.56%)
ve MAE>MFE → pump-and-fade. Bu yüzden hedefler DÜŞÜK ve çıkış peak-capture olmalı.

Kilitler: profil/calib sözlükleri 4 ufku kapsar; candidate_id prefix calib prefix ile
uyumlu; ufuk↔profil haritası doğru; bayrak kapalıyken yalnız 5/15.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app.routers import velocity as v  # noqa: E402


def test_profiles_include_30_and_60():
    assert set(v.VELOCITY_PROFILES) >= {5, 15, 30, 60}
    # Hedefler ufka göre: uzun ufukta DÜŞÜK hedef (pump-and-fade ölçümü gereği).
    assert v.VELOCITY_PROFILES[30]["target_pct"] == 1.0
    assert v.VELOCITY_PROFILES[60]["target_pct"] == 1.5


def test_calib_covers_all_profiles():
    assert set(v.VELOCITY_PROFILE_CALIB) == {"5m", "15m", "30m", "60m"}
    assert set(v._velocity_profile_atr) == {"5m", "15m", "30m", "60m"}


def test_candidate_id_prefix_matches_calib_prefix():
    """candidate_id `vel-<label>-...` ile üretilir; calib prefix `vel-<Ndk-%` ile eşleşmeli."""
    for h, prof in v.VELOCITY_PROFILES.items():
        cid = f"vel-{prof['label']}-{123}"
        assert v._velocity_horizon_from_candidate_id(cid) == h, f"{cid} → {h} olmalı"
    assert v._velocity_horizon_from_candidate_id("vel-30dk-%1-9") == 30
    assert v._velocity_horizon_from_candidate_id("vel-60dk-%1.5-9") == 60


def test_horizon_from_unknown_id_defaults_5():
    assert v._velocity_horizon_from_candidate_id("baska-bir-sey") == 5
    assert v._velocity_horizon_from_candidate_id("") == 5


def test_active_horizons_gated_by_flag(monkeypatch):
    # Bayrak açık → 4 ufuk; kapalı → yalnız 5/15.
    monkeypatch.setattr(config.config, "VELOCITY_EXTRA_HORIZONS_ENABLED", True)
    assert v._active_horizons() == (5, 15, 30, 60)
    monkeypatch.setattr(config.config, "VELOCITY_EXTRA_HORIZONS_ENABLED", False)
    assert v._active_horizons() == (5, 15)


def test_max_hold_by_horizon_scales():
    """60m ufuk 30 dk'da kesilmemeli (uzun ufuk daha uzun tutma)."""
    m = config.config.VELOCITY_MAX_HOLD_BY_HORIZON
    assert m[5] == config.config.VELOCITY_MAX_HOLD_MIN
    assert m[60] >= 60, "60m ufuk en az 60 dk tutulmalı"


def test_calib_stats_prefix_supports_30_60():
    """DB tarafındaki prefix haritası 30m/60m desteklemeli (yoksa kalibrasyon boş döner)."""
    import inspect
    from app import database as db
    src = inspect.getsource(db.get_velocity_calibration_stats)
    assert "vel-30dk-%" in src and "vel-60dk-%" in src
