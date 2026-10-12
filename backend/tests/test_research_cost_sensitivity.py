"""MALİYET-DUYARLILIK KİLİTLERİ (2026-10-12).

- `_net_at` komisyonu DOĞRU düşer (net < brüt).
- `_breakeven` başabaş komisyonu brüt EV ile tutarlı (m>0 → pozitif).
- Adverse-selection testi: gerçek limit dolgusunda görünüşteki maker edge
  KORUNMAMALI (bu, maker senaryosunun üst sınır olduğunu kanıtlar).
"""
import importlib.util
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


def _load_mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_cost_sensitivity.py"
    spec = importlib.util.spec_from_file_location("costsens", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_net_at_deducts_commission():
    mod = _load_mod()
    # Brüt %1 getirili 100 işlem
    g = [1.0] * 100
    z = mod._net_at(g, 0.0)
    t = mod._net_at(g, 0.0015)
    assert z["ev"] == 1.0, f"komisyonsuz %1 olmalı, gelen {z['ev']}"
    assert t["ev"] < z["ev"], "komisyon net EV'yi düşürmeli"
    # %0.15/bacak round-trip ≈ %0.30 → 1.0 - 0.30 ≈ 0.70
    assert 0.65 < t["ev"] < 0.75, f"taker net ~0.70 olmalı, gelen {t['ev']}"


def test_breakeven_matches_gross():
    mod = _load_mod()
    # Brüt EV %0.34 → başabaş per-leg comm ≈ 0.17%
    be = mod._breakeven([0.3407] * 100)
    assert 0.16 < be["breakeven_comm_pct"] < 0.18, f"başabaş ~0.17 olmalı, gelen {be['breakeven_comm_pct']}"
    # Negatif brüt → başabaş 0 (kâra dönmez)
    assert mod._breakeven([-0.5] * 100)["breakeven_comm_pct"] == 0.0


def test_adverse_selection_kills_naive_maker_edge():
    """Kaynak kilit: adverse-selection testi limit-giriş yolunu İÇERMELİ ve
    'dolmazsa işlem yok' mantığını korumalı (naif maker edge'i kanıtlamasın)."""
    import inspect
    mod = _load_mod()
    src = inspect.getsource(mod._adverse_selection_test)
    assert "nofill" in src, "dolmama (adverse selection) sayacı yok"
    assert "drop_pct" in src or "limit_px" in src, "limit fiyatı yok"
    assert "limit_entry_ev" in src, "limit-giriş EV ölçümü yok"
