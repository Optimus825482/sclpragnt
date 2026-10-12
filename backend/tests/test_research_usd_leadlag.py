"""USD LEAD-LAG ARAŞTIRMASI — LOOK-AHEAD + MALİYET KİLİTLERİ (2026-10-12).

1. Beta SADECE eğitim kümesinde fit edilir (test sızıntısı yok).
2. Residual = GL getirisi − beta·(aynı-bar TRY getirisi); "gerçek öncülük" bu
   residual ile ölçülür (eşzamanlı hareket arındırılır).
3. `_net` komisyon+kaymayı düşer; maker-limit senaryosu gerçek dolgu içerir.
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_usd_leadlag.py"
    spec = importlib.util.spec_from_file_location("usdll", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_net_deducts_costs():
    mod = _load_mod()
    assert mod._net(0.30, 0.0, 0.0) == 0.30
    assert mod._net(0.30, 0.0015, 0.00025) < 0.30
    # taker: 2*0.0015 + 2*0.00025 = 0.0035 → %0.35
    assert abs(mod._net(0.0, 0.0015, 0.00025) - (-0.35)) < 1e-9


def test_residual_removes_contemporaneous():
    """Beta doğru fit edilirse residual, aynı-bar TRY hareketinden arındırılmış olmalı:
    residual ile t_same korelasyonu ~0'a yakın olmalı (in-sample)."""
    mod = _load_mod()
    # yapay: g1 = 0.8*t_same + gürültü
    import random
    random.seed(1)
    rows = [{"g1": 0.8 * (ts := random.uniform(-1, 1)) + random.uniform(-0.05, 0.05),
             "t_same": ts} for _ in range(500)]
    b, mg, mt = mod._beta(rows)
    assert 0.7 < b < 0.9, f"beta ~0.8 olmalı, gelen {b}"
    resid = [r["g1"] - b * (r["t_same"] - mt) for r in rows]
    c = mod._corr(resid, [r["t_same"] for r in rows])
    assert abs(c) < 0.2, f"residual aynı-bar hareketten arındırılmalı, korelasyon {c}"


def test_beta_fit_on_train_only():
    """Kaynak kilit: beta eğitim kümesinde fit edilmeli; test sızıntısı olmamalı."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod.analyze)
    assert "tr_rows" in src and "_beta(tr_rows)" in src, "beta eğitimde fit edilmeli"
    assert "split" in src


def test_limit_fill_requires_actual_touch():
    """Kaynak kilit: maker-limit senaryosu gerçek dokunma (lo<=limit) içermeli;
    aksi halde naif maker yanılgısı (adverse selection) doğar."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod.analyze)
    assert "0.997" in src or "limit" in src, "limit fiyatı yok"
    assert "lo1" in src and "lo3" in src, "gerçek fiyat dokunuşu kontrolü yok"
