"""USD LEAD-LAG SQLITE ANALİZİ — KİLİTLER (2026-10-12).

- `_corr` doğru Pearson; `_beta` eğitim kümesinde fit edilir (test sızıntısı yok).
- Eşik eğitimden; `_net` mantığı maliyet dahil.
- Geniş pencere kritik: dar pencere (6 gün) yanıltıcı "ilk fold pozitif" üretti;
  bu testin veri yükleyicisi zaman-hizalı (open_time) GL↔TR eşleştirmeli olmalı.
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_usd_leadlag_sqlite.py"
    spec = importlib.util.spec_from_file_location("usdllsq", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_corr_and_beta_math():
    mod = _load_mod()
    assert abs(mod._corr([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9
    assert abs(mod._corr([1, 2, 3, 4], [-2, -4, -6, -8]) + 1.0) < 1e-9
    # beta: g1 = 0.8*t_same
    rows = [{"g1": 0.8 * t, "t_same": t} for t in (-2, -1, 0.5, 1, 2)]
    b, _, _ = mod._beta(rows)
    assert abs(b - 0.8) < 1e-6, f"beta ~0.8 olmalı, gelen {b}"


def test_load_pairs_aligns_by_open_time():
    """Kaynak kilit: yükleyici TR ve GL'i open_time ile hizalamalı; farklı zaman
    eksenlerini index bazlı birleştirmemeli (sessiz yanlış hizalama riski)."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod.load_pairs)
    assert "open_time" in src, "open_time ile hizalama yok"
    assert "set(tmap) & set(gmap)" in src or "& set(gmap)" in src, \
        "ortak zaman kesişimi yok — hizalama güvensiz"
    assert "sorted(set" in src, "zaman sıralaması yok"


def test_verdict_requires_stable_folds():
    """Kaynak kilit: karar 'REAL_AND_STABLE' yalnız tüm fold'lar pozitifse verilmeli
    (dar penceredeki yanıltıcı 'ilk fold pozitif' tuzağını engeller)."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod.main)
    assert "REAL_AND_STABLE" in src
    assert "all(" in src, "fold stabilite kapısı yok"
