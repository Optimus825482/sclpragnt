"""A+B+C+D çıkış/giriş politikası değişiklikleri (2026-11-25).

Kanıt: son 100 otonom işlemde %57 stop, stop aşımları -%7,8'e kadar, kazananlar
+%1-2'de trailing ile kesiliyordu.
"""
import inspect

import pytest

from app.config import config
from app.routers import auto_paper


def test_atr_stop_uses_15m_not_only_5m(monkeypatch):
    """Stop tabanı 15m ATR'yi de dikkate almalı (5m gürültüsü stopu dar tutuyordu)."""
    def fake_atr_pct(symbol, price, timeframe):
        return {"5m": 0.010, "1m": 0.010, "15m": 0.030}.get(timeframe)

    monkeypatch.setattr(auto_paper, "_atr_pct_for", fake_atr_pct)
    out = auto_paper._exit_volatility_sl("ABCTRY", 100.0, 0.0175, True)
    # max(1.2*1.0%, 0.9*3.0%) = 2.7% (tavan 3.2% altında)
    assert out == pytest.approx(0.027, rel=1e-6)


def test_atr_stop_never_tightens():
    """ATR hesabı stopu DARALTMAZ; mevcut stop daha genişse o korunur."""
    assert auto_paper._effective_sl_pct(0.05, 0.01) == 0.05


def test_vol_size_multiplier_shrinks_only():
    assert auto_paper._vol_size_multiplier(0.018) == 1.0
    assert auto_paper._vol_size_multiplier(0.036) == pytest.approx(0.5)  # alt sınır
    assert auto_paper._vol_size_multiplier(0.027) < 1.0
    assert auto_paper._vol_size_multiplier(0.0) == 1.0


def test_trailing_defaults_kept_by_measurement():
    """2026-11-25: B denemesi GERİ ALINDI — ölçüm (4 tarama, 90 gün) 2,0/1,0'ı
    "KORUNDU" işaretledi. ATR tavanı (A) ise yürürlükte kalır."""
    assert config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT == 1.0
    assert config.AUTO_PAPER_TRAILING_TRIGGER_PCT == 2.0
    assert config.AUTO_PAPER_TRAILING_GAP_PCT == 1.0
    assert config.AUTO_PAPER_ATR_SL_CAP_PCT >= 3.0


def test_cluster_gate_present():
    src = inspect.getsource(auto_paper._cooldown_gate)
    assert "cluster_limit" in src
    assert "count_auto_paper_opened_since" in src


def test_cluster_defaults_sane():
    assert config.AUTO_PAPER_CLUSTER_WINDOW_MIN > 0
    assert config.AUTO_PAPER_CLUSTER_MAX_ENTRIES >= 1


def test_mae_mfe_columns_and_writer_exist():
    """MAE/MFE: stop aşımı teşhisi için alanlar ve yazıcı bulunmalı."""
    import inspect as _inspect

    from app import database

    src = _inspect.getsource(database.update_auto_paper_excursions)
    assert "max_adverse_pct" in src and "max_favorable_pct" in src
    assert "OR ? < max_adverse_pct" in src, "yalnız kötüleşince yazılmalı (benign no-op)"


def test_auto_paper_records_oi_change():
    """Giriş OI değişimi kaydedilmeli (sayaçlar ölçülebilsin)."""
    import inspect as _inspect

    src = _inspect.getsource(auto_paper)
    assert '"oi_change_pct": oi_change_val' in src
    assert "get_cached_squeeze_confirmation" in src
