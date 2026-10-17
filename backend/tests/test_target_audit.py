"""scripts/target_audit.py saf yardımcıları: panel skor paritesi, TP dolum dönüşümü, simülatör maliyet kimliği."""
import importlib.util
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("target_audit", ROOT / "scripts" / "target_audit.py")
A = importlib.util.module_from_spec(_spec)
sys.modules["target_audit"] = A
_spec.loader.exec_module(A)


def test_panel_score_matches_velocity():
    from app.routers import velocity
    for raw in (0.0, 10.0, 500.0, 1800.0, 25000.0, 90000.0):
        assert math.isclose(A.panel_score(raw), velocity._panel_score(raw), abs_tol=1e-9)


def test_tp_fill_removes_entry_slip():
    out = A.tp_fill(np.array([2.0]))
    assert math.isclose(float(out[0]), ((1.02 / 1.0015) - 1.0) * 100.0, rel_tol=1e-12)


def test_tp_exit_total_cost_is_033():
    """Tek bar: giriş açılışı 100, high hedefi geçer -> TP; net = hedef - %0,33 (kayma+taker+maker)."""
    n, w = 1, 3
    O = np.ones((n, w), dtype=np.float32)
    H = np.full((n, w), 1.03, dtype=np.float32)
    L = np.ones((n, w), dtype=np.float32)
    C = np.ones((n, w), dtype=np.float32)
    T = type("T", (), {})()
    T.n = n
    T.valid = np.array([True])
    T.Os, T.Hs, T.Ls, T.Cs = O, H, L, C
    r = A.simulate_tp(T, np.array([2.0]), 2)
    assert r["hit"][0] == 1.0
    assert abs(r["net"][0] - (2.0 - 0.33)) < 0.01
