"""BAĞIMSIZ ÖNGÖRÜCÜ TARAMASI — LOOK-AHEAD KİLİDİ (2026-10-12).

NEDEN KRİTİK: İlk sürüm `_features` içinde index'i `bisect_left(t, ts)-1` ile
alıyordu. Bir bar `open_time`'da açılıp `+300 sn`'de kapanır; `ts` anında o bar
HÂLÂ AÇIK olabilir → kapanışı (gelecek bilgi) okunur. Bu sızıntı sahte bir
"momentum edge"i üretti (r1/r3/r12 t>6). Doğru indeks `bisect_right(t, ts-300)-1`
(yalnız kapanmış barlar). Bu test sızıntının geri gelmesini engeller.
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "scan_entry_features.py"
    spec = importlib.util.spec_from_file_location("featscan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_features_never_use_unclosed_bar():
    mod = _load_mod()
    # Basit seri: 5 dk aralıklı, bilinen fiyatlar. ts, 11. barın AÇILIŞ anında.
    base = 1_000_000.0
    n = 60
    t = [base + i * 300 for i in range(n)]
    bars = {
        "t": t,
        "h": [10.0 + i for i in range(n)],
        "l": [9.0 + i for i in range(n)],
        "c": [9.5 + i for i in range(n)],
        "v": [100.0] * n,
    }
    # ts = 55. barın açılış anı → 55. bar HENÜZ KAPANMADI (kapanışı ts+300).
    ts = t[55]
    f = mod._features(bars, ts)
    assert f is not None
    # En son GÜVENLİ bar t[54] (kapanışı t[54]+300 = t[55] = ts).
    expected_r1 = (bars["c"][54] / bars["c"][53] - 1) * 100
    assert abs(f["r1"] - expected_r1) < 1e-9, \
        "r1 açık barı (gelecek) kullanıyor — look-ahead sızıntısı"
    # Açık barın (t[55]) değerini YANSITMAMALI.
    leak_r1 = (bars["c"][55] / bars["c"][54] - 1) * 100
    assert abs(f["r1"] - leak_r1) > 1e-9, "açık bar değeri sızmış"


def test_feature_scan_uses_closed_bar_index():
    """Kaynak kilit: `_features` doğru bisect kullanmalı."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod._features)
    assert "ts - _BAR_SEC" in src, "kapanmış-bar offseti (ts - _BAR_SEC) yok"
    assert "bisect_right" in src, "bisect_right kullanılmalı (kapanmış bar)"
