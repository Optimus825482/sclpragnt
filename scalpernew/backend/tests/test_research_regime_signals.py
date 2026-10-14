"""REJİM-GÜDÜMLÜ YÜKSEK-TF SİNYAL ARAŞTIRMASI — LOOK-AHEAD + MALİYET KİLİTLERİ.

1. `_regime_and_signals` yalnız [0..i] verisini kullanır (look-ahead yok).
2. `_simulate` giriş+çıkış komisyonu ve çıkış kaymasını DÜŞER (maliyetsiz ölçüm
   5dk turunda brüt-pozitif ama net-negatif yanılgı yaratmıştı).
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_regime_signals.py"
    spec = importlib.util.spec_from_file_location("regsig", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _series(closes, highs=None, lows=None, n=None):
    n = n or len(closes)
    return {"t": [1_000_000.0 + i * 3600 for i in range(n)],
            "o": closes, "h": highs or closes, "l": lows or closes, "c": closes,
            "v": [1.0] * n}


def test_regime_uses_only_past_bars():
    """Gelecek barları zehirle: sinyal DEĞİŞMEMELİ (look-ahead yok)."""
    mod = _load_mod()
    import math
    # Düzenli yükselen seri + son bar düşüş
    base = [100.0 + math.sin(i / 5) * 2 + i * 0.01 for i in range(200)]
    h = [c + 0.5 for c in base]; l = [c - 0.5 for c in base]
    bars_ok = _series(base, h, l)
    r_ok = mod._regime_and_signals(bars_ok, 150)
    # 151. bardan sonrasını uçuk değerle boz (gelecek)
    base2 = base[:151] + [base[150] * 100 for _ in range(49)]
    bars_bad = _series(base2, [c + 0.5 for c in base2], [c - 0.5 for c in base2])
    r_bad = mod._regime_and_signals(bars_bad, 150)
    assert r_ok is not None and r_bad is not None
    assert r_ok["regime"] == r_bad["regime"], "gelecek veri rejimi değiştirdi (look-ahead)"
    assert r_ok["signals"] == r_bad["signals"], "gelecek veri sinyali değiştirdi (look-ahead)"


def test_simulate_deducts_costs():
    """Maliyetli net, brüt'ten KÜÇÜK olmalı (komisyon çift + kayma)."""
    mod = _load_mod()
    # ATR=1, entry=100; SL=%1.5 altına inmez, TP=%3 üstüne çıkar → TP ile kapanır.
    n = 30
    c = [100.0] * n
    h = [100.0] * n; l = [100.0] * n
    h[5] = 104.0   # 5. barda TP (%3 → 103) aşılır
    bars = {"t": [1e6 + i * 3600 for i in range(n)], "o": c, "h": h, "l": l, "c": c, "v": [1.0] * n}
    gross = mod._simulate(bars, 2, 1.0, k_sl=1.5, k_tp=3.0, max_hold=240,
                          commission_pct=0.0, slippage_pct=0.0)
    net = mod._simulate(bars, 2, 1.0, k_sl=1.5, k_tp=3.0, max_hold=240,
                        commission_pct=0.0015, slippage_pct=0.00025)
    assert gross is not None and net is not None
    assert abs(gross - 3.0) < 0.01, f"brüt TP %3 olmalı, gelen {gross}"
    assert net < gross, "net maliyet düşülmemiş"


def test_simulate_pessimistic_sl_first():
    """Aynı barda hem SL hem TP menzili → SL önce (kötümser)."""
    mod = _load_mod()
    n = 20
    c = [100.0] * n
    h = [100.0] * n; l = [100.0] * n
    h[3] = 106.0; l[3] = 94.0     # aynı bar TP(%3=103) ve SL(%1.5=98.5) ikisini de görür
    bars = {"t": [1e6 + i * 3600 for i in range(n)], "o": c, "h": h, "l": l, "c": c, "v": [1.0] * n}
    r = mod._simulate(bars, 2, 1.0, k_sl=1.5, k_tp=3.0, max_hold=240,
                      commission_pct=0.0, slippage_pct=0.0)
    assert r is not None and r < 0, "bar-içi belirsizlikte SL önce gelmeli (kötümser)"


def test_perf_window_limits_lookback():
    """Pencere parametresi geçmişi sınırlar (O(n²) koruması) — VE dilim üst sınırı
    tam `i + 1` olmalı (kapalı bar; geleceği dahil etmez)."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod._regime_and_signals)
    assert "window" in src and "lo" in src, "sabit pencere optimizasyonu yok"
    assert ":i + 1]" in src, "dilim üst sınırı `i + 1` olmalı (look-ahead sınırı)"
