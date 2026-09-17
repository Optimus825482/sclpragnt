"""Gorev #3 KILIT: `ml_hit_probability` skoru ETKILEMEZ; hedefe yalnizca guven kapisi.

Kanit (2026-09-14, iki bagimsiz orneklem):
  * 104 tespit tablosu (13-14.09)  : olasilik vs MFE            r=-0.050 t=-0.50
  * 370 kayit DB orneklemi         : olasilik vs MFE            r=+0.095 t=+1.83
                                     olasilik vs "hedefe dokundu" r=+0.111 t=+2.13
  |t| < 2.07 -> anlamsiz. Ikinci orneklemdeki sinirdaki deger coklu
  karsilastirmada saglam degil; iki orneklem ISARET olarak bile uyusmuyor.

Karar: olculebilir bir ayirt edicilik yok -> SKORA agirlik yok. Olasilik skor
hesabina hicbir sekilde GIRMEZ.

BILINCLI AYRIM: `ml_target_pct` (ML'nin beklenen hareket tahmini) HALA
`dynamic_target_pct`'e girer — cunku onun kaniti VAR:
`ml_target_pct` vs gerceklesen MFE r=+0.344, t=+6.91 (ANLAMLI, n=359).
Bu dosya o kanali KORUR.

GUNCELLEME (2026-09-17) — dar kapsamli revizyon:
  * Hedef harmanlama IKI YONLU oldu: `ml_target_pct` banttan dusukse hedefi
    ASAGI da cekebilir (onceki sozlesme: yalnizca yukari).
  * Olasilik, ml_target kanalinin GUVEN KAPISI olarak hedefe girer:
    `ml_prob < config.ML_TARGET_MIN_PROB` ise ML hedefe hic uygulanmaz.
    Bu, yukaridaki "hedefe GIRMEZ" ifadesini olasilik icin DAR KAPSAMDA
    gunceller: olasilik hedef DEGERINI agirliklandirmaz (ml_pct argumanina
    sizmaz) ve skora hic girmez. Asagidaki kilitler bunu zorlar.
  * Kilit AD-BAGIMSIZ: olasilik degeri `.get("hit_probability")` atamasindan
    izlenir. 2026-09-17'de yerel ad `ml_hit_prob` oldugu icin eski ad-tabanli
    kilit (yalniz `ml_hit_probability` arıyordu) sessizce delinmisti.
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402
from app.routers import velocity  # noqa: E402
from app.routers.velocity import dynamic_target_pct  # noqa: E402

VEL_SRC = pathlib.Path(velocity.__file__).read_text(encoding="utf-8")
VEL_TREE = ast.parse(VEL_SRC)


def _name_ids(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _probability_value_names(tree: ast.AST) -> set[str]:
    """`...get("hit_probability")` ile beslenen yerel adlar.

    Kilidin AD-BAGIMSIZ olmasi icin: `ml_hit_probability` yerine `ml_hit_prob`
    gibi bir ad secilse bile olasilik degeri izlenir (2026-09-17 delinmesi).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        fed_by_probability = any(
            isinstance(sub, ast.Call)
            and getattr(sub.func, "attr", None) == "get"
            and any(isinstance(a, ast.Constant) and a.value == "hit_probability"
                    for a in sub.args)
            for sub in ast.walk(value)
        )
        if not fed_by_probability:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


class MlProbabilityDoesNotAffectScore(unittest.TestCase):
    """Olasilik SKORA giremez; hedefe yalnizca `ml_prob` guven kapisi olarak girer."""

    def test_probability_gate_is_actually_wired(self):
        """Kilit kor gecmesin: olasilik degeri izlenebilmeli ve kapi bagli olmali."""
        prob_names = _probability_value_names(VEL_TREE)
        self.assertTrue(prob_names, "olasilik degeri atamasi izlenemedi (kilit kor)")

        wired = False
        for node in ast.walk(VEL_TREE):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "dynamic_target_pct"):
                continue
            for kw in node.keywords:
                if kw.arg == "ml_prob" and _name_ids(kw.value) & prob_names:
                    wired = True
        self.assertTrue(wired, "olasilik guven kapisi dynamic_target_pct'e bagli degil")

    def test_velocity_score_never_reads_probability(self):
        """`velocity_score` atamalarinin hicbiri olasiliktan beslenmez."""
        prob_names = _probability_value_names(VEL_TREE)
        offenders = []
        for node in ast.walk(VEL_TREE):
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AugAssign):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            else:
                continue
            for tgt in targets:
                if (isinstance(tgt, ast.Name) and tgt.id == "velocity_score"
                        and _name_ids(value) & prob_names):
                    offenders.append(node.lineno)
        self.assertEqual([], offenders,
                         f"velocity_score olasiliktan besleniyor (satir {offenders})")

    def test_probability_only_enters_target_as_gate(self):
        """Hedef cagrisinda olasilik YALNIZCA `ml_prob` kapisi olarak gecebilir.

        `ml_pct` (hedef DEGERINI olceklendiren arguman) olasiliktan turemez —
        olasiligin ayirt ediciligi olculemedi, bu yuzden hedef degeri degil,
        yalnizca "uygula/uygulama" karari ondan alinir.
        """
        prob_names = _probability_value_names(VEL_TREE)
        calls = 0
        offenders = []
        for node in ast.walk(VEL_TREE):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "dynamic_target_pct"):
                continue
            calls += 1
            for kw in node.keywords:
                if kw.arg == "ml_prob":
                    continue
                if _name_ids(kw.value) & prob_names:
                    offenders.append((node.lineno, kw.arg))
        self.assertGreaterEqual(calls, 1, "dynamic_target_pct cagrisi bulunamadi")
        self.assertEqual([], offenders,
                         f"olasilik hedef argumanina sizmis: {offenders}")


class MlTargetChannelPreserved(unittest.TestCase):
    """Kanitli kanal KORUNUR: `ml_target_pct` hedefi iki yonlu etkiler (guven sarti ile)."""

    def test_dynamic_target_pct_still_accepts_ml_pct(self):
        import inspect
        params = inspect.signature(dynamic_target_pct).parameters
        self.assertIn("ml_pct", params)

    def test_ml_pct_requires_confidence_gate(self):
        """Esigin altinda (veya olasilik hic yoksa) ML hedefe GIRMEZ."""
        self.assertEqual(4.0, dynamic_target_pct(
            95.0, 2.0, ml_pct=6.0, ml_prob=config.ML_TARGET_MIN_PROB - 0.1))
        self.assertEqual(4.0, dynamic_target_pct(95.0, 2.0, ml_pct=6.0))

    def test_ml_pct_can_raise_target_with_confidence(self):
        """Kanit: ml_target_pct vs MFE r=+0.344, t=+6.91 -> bilgi tasiyor."""
        base = dynamic_target_pct(95.0, 2.0)                    # ust bant 4.0
        raised = dynamic_target_pct(95.0, 2.0, ml_pct=6.0, ml_prob=0.9)
        self.assertGreater(raised, base)

    def test_ml_pct_can_lower_target_with_confidence(self):
        """2026-09-17: harmanlama iki yonlu — banttan dusuk ML tahmini ASAGI ceker."""
        base = dynamic_target_pct(95.0, 2.0)                    # 4.0
        lowered = dynamic_target_pct(95.0, 2.0, ml_pct=1.6, ml_prob=0.9)
        self.assertLess(lowered, base)

    def test_ml_pct_must_be_positive(self):
        """Negatif/dusus tahmini hedefe girmez (kanal yalniz pozitif tahmin)."""
        self.assertEqual(4.0, dynamic_target_pct(95.0, 2.0, ml_pct=-3.0, ml_prob=0.9))


# --------------------------------------------------------------------------
# Mutasyon notu: velocity.py icinde `velocity_score += ml_hit_prob * 100`
# gibi bir satir eklenirse test_velocity_score_never_reads_probability KIRILIR
# (ad-bagimsiz izleme sayesinde `ml_hit_prob` adiyla da yakalanir).
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
