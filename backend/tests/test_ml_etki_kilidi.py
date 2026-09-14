"""Gorev #3 KILIT: `ml_hit_probability` skoru/hedefi ETKILEMEZ.

Kanit (2026-09-14, iki bagimsiz orneklem):
  * 104 tespit tablosu (13-14.09)  : olasilik vs MFE            r=-0.050 t=-0.50
  * 370 kayit DB orneklemi         : olasilik vs MFE            r=+0.095 t=+1.83
                                     olasilik vs "hedefe dokundu" r=+0.111 t=+2.13
  |t| < 2.07 -> anlamsiz. Ikinci orneklemdeki sinirdaki deger coklu
  karsilastirmada saglam degil; iki orneklem ISARET olarak bile uyusmuyor.

Karar: olculebilir bir ayirt edicilik yok -> agirlik yok. Olasilik yalnizca
GOZLEM olarak kaydedilir ve gosterilir; skor/hedef hesabina GIRMEZ.

BILINCLI AYRIM: `ml_target_pct` (ML'nin beklenen hareket tahmini) HALA
`dynamic_target_pct`'e girer — cunku onun kaniti VAR:
`ml_target_pct` vs gerceklesen MFE r=+0.344, t=+6.91 (ANLAMLI, n=359).
Bu dosya o kanali KORUR, yalnizca olasilik kanalini kilitler.

Not: `ml_target_pct` su an pratikte etkisiz (ort. %0.47, radar bantlari %2-4;
"baglayici" kayit 0/359) ama kanitli oldugu icin kaldirilmadi.
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import velocity  # noqa: E402
from app.routers.velocity import dynamic_target_pct  # noqa: E402

VEL_SRC = pathlib.Path(velocity.__file__).read_text(encoding="utf-8")
VEL_TREE = ast.parse(VEL_SRC)


def _name_ids(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


class MlProbabilityDoesNotAffectScore(unittest.TestCase):
    """Olasilik skora giremez."""

    def test_no_bare_name_reference_in_velocity(self):
        """`ml_hit_probability` velocity.py'de YALNIZCA dict anahtari (string).

        Bir `ast.Name` olarak geciyorsa aritmetige/karsilastirmaya girmis demektir
        -> skora veya hedefe etki ediyor demektir. Bu test onu reddeder.
        """
        names = {n.id for n in ast.walk(VEL_TREE) if isinstance(n, ast.Name)}
        self.assertNotIn("ml_hit_probability", names,
                         "ml_hit_probability bir degisken olarak kullaniliyor; "
                         "skoru/hedefi etkileme kurali ihlal edildi")

    def test_velocity_score_never_reads_ml_probability(self):
        """`velocity_score` atamalarinin hicbiri olasiligi okumaz."""
        offenders = []
        for node in ast.walk(VEL_TREE):
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            value = value if isinstance(value, ast.AST) else None
            if value is None:
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == "velocity_score":
                    if "ml_hit_probability" in _name_ids(value):
                        offenders.append(node.lineno)
        self.assertEqual([], offenders,
                         f"velocity_score ML olasiligindan besleniyor (satir {offenders})")

    def test_effective_target_call_has_no_ml_probability(self):
        """`effective_target = dynamic_target_pct(...)` argumanlari olasilik icermez."""
        calls = 0
        for node in ast.walk(VEL_TREE):
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", None) == "dynamic_target_pct"):
                continue
            calls += 1
            arg_names = set()
            for arg in node.value.args:
                arg_names |= _name_ids(arg)
            for kw in node.value.keywords:
                arg_names |= _name_ids(kw.value)
            self.assertNotIn("ml_hit_probability", arg_names,
                             "hedef hesabi ML olasiligindan besleniyor")
        self.assertGreaterEqual(calls, 1, "dynamic_target_pct cagrisi bulunamadi")


class MlTargetChannelPreserved(unittest.TestCase):
    """Kanitli kanal KORUNUR: `ml_target_pct` hâlâ hedefi yukari cekebilir."""

    def test_dynamic_target_pct_still_accepts_ml_pct(self):
        import inspect
        params = inspect.signature(dynamic_target_pct).parameters
        self.assertIn("ml_pct", params)

    def test_ml_pct_can_raise_target(self):
        """Kanit: ml_target_pct vs MFE r=+0.344, t=+6.91 -> bilgi tasiyor."""
        base = dynamic_target_pct(95.0, 2.0)          # ust bant 4.0 -> 4.0
        raised = dynamic_target_pct(95.0, 2.0, ml_pct=6.0)
        self.assertGreater(raised, base)

    def test_ml_pct_never_lowers_target(self):
        """`target = max(bant, ml_pct)` — ML hedefi yalnizca YUKARI ceker."""
        for score in (0.0, 30.0, 55.0, 75.0, 95.0, 100.0):
            base = dynamic_target_pct(score, 2.0)
            self.assertGreaterEqual(dynamic_target_pct(score, 2.0, ml_pct=0.01), base)


# --------------------------------------------------------------------------
# Mutasyon notu: velocity.py icinde `velocity_score += ml_hit_probability * 100`
# gibi bir satir eklenirse test_no_bare_name_reference_in_velocity VE
# test_velocity_score_never_reads_ml_probability KIRILIR (dogrulandi).
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
