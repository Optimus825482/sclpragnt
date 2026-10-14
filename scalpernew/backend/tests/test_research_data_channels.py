"""YENİ VERİ KANALI ARAŞTIRMASI — LOOK-AHEAD + PARSE KİLİTLERİ (2026-10-12).

İki şeyi garanti eder:
1. `_idx_closed` yalnız KAPANMIŞ barı kullanır (bar open+300 <= ts). Önceki
   turda bu sınıf bir hata (bisect_left) sahte "edge" üretmişti; tekrar etmesin.
2. `_to_bars` klines'ın 9. alanını (taker_buy_base) DOĞRU indekse eşler;
   kayarsa order-flow kanalı sessizce yanlış veri ölçer.
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_data_channels.py"
    spec = importlib.util.spec_from_file_location("chan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_idx_closed_excludes_open_bar():
    mod = _load_mod()
    base = 1_000_000.0
    bars = {"t": [base + i * 300 for i in range(60)]}
    # ts = son barın açılış anı → o bar HENÜZ KAPANMADI.
    ts = bars["t"][55]
    i = mod._idx_closed(bars, ts)
    assert bars["t"][i] + 300 <= ts, "açık bar kullanıldı (look-ahead)"
    assert i == 54, f"beklenen 54, gelen {i}"


def test_to_bars_maps_taker_buy_index9():
    mod = _load_mod()
    # Binance klines 12 alan: [..., 5]=volume, [9]=taker_buy_base
    row = [1000, "1.0", "2.0", "0.5", "1.5", "100.0", 1999, "150.0",
           7, "60.0", "90.0", "0"]
    b = mod._to_bars([row])
    assert b["v"] == [100.0], "volume alan 5 olmalı"
    assert b["tb"] == [60.0], "taker_buy_base alan 9 olmalı"


def test_tr_features_use_closed_bars_only():
    """Kaynak kilit: `_tr_features` kapalı-bar indeksi kullanmalı."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod._tr_features)
    assert "_idx_closed" in src
    idx_src = inspect.getsource(mod._idx_closed)
    assert "ts - 300" in idx_src and "bisect_right" in idx_src


def test_fetch_uses_correct_tr_base():
    """TR REST tabanı `api.binance.me` olmalı (www.binance.tr 12-alan vermez)."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod._build_cache)
    assert "api.binance.me" in src, "TR taban URL yanlış"
    assert "api.binance.com" in src, "Global taban URL eksik"
