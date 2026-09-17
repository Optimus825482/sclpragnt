"""Hedef öğrenme BESLEME kuralları (2026-09-17 denetimi).

NEDEN VAR: hedef öğrenmesi (``symbol_target_state`` MFE-EMA'sı) üç yoldan
besleniyordu ama üçü aynı kalitede ölçüm vermiyordu. Denetimde bulunan hata:
radar/pending yolu gerçekleşen hareketi ÖLÇEMİYOR, buna rağmen uydurma değer
gönderiyordu (isabet → hedefin kendisi, ıska → 0.0). Formül simülasyonu ile
ölçüldü: %100 isabet eden sembolün öğrenilen hedefi 30 sinyalde 3.20 → 2.55
düşüyordu ve tek bir erken ıska hedefi tabana (1.0) çiviyordu.

Kilitlenen kurallar:
  1. Hedef EMA'sı YALNIZ gerçek MFE ölçen iki yoldan beslenir
     (`fill_rising_alert_outcomes` 5m mumlarla, `velocity_learning_loop`
     `_mfe_from_window` ile). Radar/pending yolu `achieved_pct` GÖNDERMEZ;
     yalnız başarı sayaçlarını işler.
  2. EMA tabanı HER ZAMAN mevcut hedeftir (ilk örnekte de): eski kod ilk örnekte
     doğrudan ölçüme atlıyordu.
  3. `achieved_pct=None` → hedef DEĞİŞMEZ.
  4. Saklanan hedef, tüketicinin kelepçesiyle (MONITORING_TARGET_PCT_MIN/MAX)
     aynı aralıkta kalır → sessiz kırpma ve erişilemez tavan yok.
  5. Rising, PANEL ölçeğine bağlı kuralları (bant + zayıf-skor kelepçesi)
     KULLANMAZ: sentetik `strength × 10` skoru panel ölçeği değildir (§4/R3).
  6. auto_paper TP'si TEK kaynaktan gelir (`target_pct`); ham `ml_target_pct`
     ikinci kez uygulanmaz (ML zaten `dynamic_target_pct` harmanında).

Kilitler iki katmanlı: saf fonksiyon matematiği + AST. AST katmanı besleme
çağrılarının ŞEKLİNİ çiviler — yerel ad değiştirilerek (2026-09-17'de
`ml_hit_probability` → `ml_hit_prob` gibi) delinemez.
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402
from app.database import _next_target_pct  # noqa: E402

APP = ROOT / "app"
DATABASE_PY = APP / "database.py"
MONITORING_PY = APP / "routers" / "monitoring.py"
VELOCITY_PY = APP / "routers" / "velocity.py"
AUTO_PAPER_PY = APP / "routers" / "auto_paper.py"


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls_to(tree: ast.Module, func_name: str) -> list[ast.Call]:
    """`f(...)` ve `mod.f(...)` çağrılarının ikisini de yakalar."""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _call_name(n) == func_name]


def _string_constants(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


class NextTargetPctTests(unittest.TestCase):
    """Saf EMA matematiği — DB'siz, `config` kelepçeleriyle."""

    def test_missing_measurement_keeps_target(self):
        """Ölçüm yoksa hedef DEĞİŞMEZ (yalnız sayaç işler)."""
        self.assertEqual(2.0, _next_target_pct(2.0, None, 7))
        self.assertEqual(2.5, _next_target_pct(2.5, None, 1))

    def test_first_sample_uses_current_target_as_base(self):
        """İlk örnekte taban `current_target`tır (eski kod doğrudan ölçüme atlıyordu)."""
        # alpha = 0.5 → 2.0*0.5 + min(3.0, MAX)*0.8*0.5 = 1.0 + 1.2 = 2.2
        self.assertAlmostEqual(2.2, _next_target_pct(2.0, 3.0, 1), places=3)
        # Tek erken ıska hedefi TABANA çivileyemez (eski davranış max(1.0, 0)=1.0).
        self.assertEqual(2.0, _next_target_pct(4.0, 0.0, 1))

    def test_real_mfe_above_target_raises(self):
        """Gerçek MFE hedefin üzerindeyse hedef YUKARI gider (asıl öğrenme)."""
        # alpha = 3/10 = 0.3; conservative = 3.0*0.8 = 2.4 → 2.0*0.7 + 2.4*0.3 = 2.12
        self.assertAlmostEqual(2.12, _next_target_pct(2.0, 3.0, 10), places=3)
        self.assertGreater(_next_target_pct(2.0, 3.0, 10), 2.0)

    def test_measured_zero_mfe_lowers_to_floor(self):
        """Ölçülen 0 MFE hedefi aşağı çeker (tavan/taban dışına taşmaz)."""
        # alpha = 0.5 → 2.0*0.5 + 0 = 1.0 → MIN'e kırpılır
        self.assertEqual(config.MONITORING_TARGET_PCT_MIN, _next_target_pct(2.0, 0.0, 2))

    def test_target_stays_inside_consumer_clamp(self):
        """Saklanan değer tüketicinin kelepçesi içinde: sessiz kırpma yok."""
        for current in (0.5, 2.0, 6.0, 20.0):
            for achieved in (None, 0.0, 0.2, 3.0, 999.0):
                for count in (1, 2, 3, 12, 60):
                    value = _next_target_pct(current, achieved, count)
                    self.assertGreaterEqual(value, config.MONITORING_TARGET_PCT_MIN)
                    self.assertLessEqual(value, config.MONITORING_TARGET_PCT_MAX)

    def test_outlier_measurement_cannot_exceed_ceiling(self):
        """Aykırı ölçüm (99%) tek örnekte hedefi tavanın üstüne taşıyamaz."""
        self.assertLessEqual(_next_target_pct(6.0, 99.0, 1), config.MONITORING_TARGET_PCT_MAX)

    def test_alpha_decays_with_sample_count(self):
        """Örnek arttıkça öğrenme hızı düşer (aynı ölçüm daha az etki eder)."""
        early = _next_target_pct(2.0, 0.0, 3)
        late = _next_target_pct(2.0, 0.0, 60)
        self.assertLess(early, late)


class LearningFeedShapeTests(unittest.TestCase):
    """Besleme çağrılarının ŞEKLİ kaynak düzeyinde kilitli (AST)."""

    def test_radar_pending_feed_sends_no_achieved_pct(self):
        """Radar/pending yolu uydurma MFE GÖNDERMEZ (ölçemiyor)."""
        calls = _calls_to(_tree(MONITORING_PY), "record_symbol_target_outcome")
        self.assertGreaterEqual(len(calls), 1, "monitoring.py'de öğrenme beslemesi yok")
        for call in calls:
            self.assertNotIn(
                "achieved_pct", {kw.arg for kw in call.keywords},
                f"monitoring.py:{call.lineno} radar yolu uydurma achieved_pct gönderiyor")

    def test_real_mfe_feeds_still_send_measured_achieved(self):
        """Ölçüm üreten iki yol ölçümü göndermeye DEVAM etmeli (kilit kör değil)."""
        db_calls = _calls_to(_tree(DATABASE_PY), "record_symbol_target_outcome")
        self.assertEqual(1, len(db_calls), "database.py'de rising beslemesi tek çağrı olmalı")
        self.assertIn("achieved_pct", {kw.arg for kw in db_calls[0].keywords})

        vel_calls = _calls_to(_tree(VELOCITY_PY), "record_symbol_target_outcome")
        self.assertGreaterEqual(len(vel_calls), 1, "velocity.py'de ölçüm beslemesi yok")
        for call in vel_calls:
            self.assertIn("achieved_pct", {kw.arg for kw in call.keywords})

    def test_rising_dynamic_target_disables_panel_scale(self):
        """Rising çağrısı `panel_score=False` olmalı — sentetik skor panel ölçeği değildir."""
        calls = _calls_to(_tree(MONITORING_PY), "dynamic_target_pct")
        self.assertGreaterEqual(len(calls), 1, "monitoring.py'de dynamic_target_pct çağrısı yok")
        for call in calls:
            values = {kw.arg: kw.value for kw in call.keywords}
            self.assertIn("panel_score", values,
                          f"monitoring.py:{call.lineno} panel_score bayrağı yok")
            node = values["panel_score"]
            self.assertIsInstance(node, ast.Constant)
            self.assertIs(node.value, False,
                          f"monitoring.py:{call.lineno} panel_score False olmalı")

    def test_velocity_dynamic_target_keeps_panel_scale(self):
        """Velocity çağrısı panel ölçeğini KORUMALI (bantlar o ölçekte kalibre)."""
        calls = _calls_to(_tree(VELOCITY_PY), "dynamic_target_pct")
        self.assertGreaterEqual(len(calls), 1)
        for call in calls:
            values = {kw.arg: kw.value for kw in call.keywords}
            if "panel_score" in values:
                self.assertIsNot(values["panel_score"], False,
                                 "velocity panel skoru ile çağırmalı (panel_score=True)")

    def test_auto_paper_target_single_source(self):
        """`_effective_target_pct` ham ML alanlarını OKUMAZ (ML iki kez uygulanmaz)."""
        tree = _tree(AUTO_PAPER_PY)
        func = next((n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "_effective_target_pct"), None)
        self.assertIsNotNone(func, "auto_paper._effective_target_pct bulunamadı")
        literals = _string_constants(func)
        self.assertIn("target_pct", literals)
        self.assertNotIn("ml_target_pct", literals,
                         "auto_paper ham ml_target_pct'i tekrar uyguluyor (çift sayım)")
        self.assertNotIn("ml_hit_probability", literals)


# --------------------------------------------------------------------------
# Mutasyon notu: monitoring.py'de `achieved_pct=target_pct if hit else 0.0`
# geri konursa test_radar_pending_feed_sends_no_achieved_pct KIRILIR; rising
# çağrısından `panel_score=False` kaldırılırsa panel ölçeği kilidi KIRILIR.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
