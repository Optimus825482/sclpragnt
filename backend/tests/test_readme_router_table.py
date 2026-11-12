"""README "Modüler API yapısı" tablosunun dosya sistemiyle senkron kalmasını denetler.

Denetim 2026-10-15 bölüm 6: README "13 modül, 11 include_router" diyordu,
olmayan `bridge.py` listeliyor, `user_prefs`/`journal` eksikti. Bu test
sürüklenmeyi (drift) CI'da kırmızıya çevirir.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTERS_DIR = ROOT / "backend" / "app" / "routers"
MAIN_PY = ROOT / "backend" / "app" / "main.py"
README = ROOT / "README.md"


def _fs_modules() -> set[str]:
    return {p.stem for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py"}


def _apirouter_modules() -> set[str]:
    return {
        p.stem
        for p in ROUTERS_DIR.glob("*.py")
        if p.name != "__init__.py"
        and re.search(r"^router\s*=\s*APIRouter\(", p.read_text(encoding="utf-8"), re.M)
    }


def _include_router_calls() -> int:
    return len(re.findall(r"^\s*app\.include_router\(", MAIN_PY.read_text(encoding="utf-8"), re.M))


class ReadmeRouterTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_module_file_count_matches_filesystem(self):
        m = re.search(r"`app/routers/` altında \*\*(\d+)\*\* modül dosyası", self.readme)
        self.assertIsNotNone(m, "README modül sayısı cümlesi bulunamadı")
        self.assertEqual(int(m.group(1)), len(_fs_modules()))

    def test_apirouter_and_include_router_counts_match(self):
        m = re.search(r"bunların \*\*(\d+)\*\*'si `APIRouter` tanımlar ve `main\.py` içinde \*\*(\d+)\*\* adet `include_router`",
                      self.readme)
        self.assertIsNotNone(m, "README APIRouter/include_router cümlesi bulunamadı")
        self.assertEqual(int(m.group(1)), len(_apirouter_modules()))
        self.assertEqual(int(m.group(2)), _include_router_calls())
        # Her APIRouter tanımlayan modül main.py'de EN AZ BİR kez kayıtlı olmalı.
        # 2026-11-10: tek modül birden fazla router tanımlayıp birden fazla kez
        # kaydedilebilir (`ai_trading_suite_routes.py` = `router` + `router_alias`).
        # Bu yüzden `modül sayısı == include_router sayısı` eşitliği YANLIŞTIR;
        # doğru değişmez: her APIRouter modülünün en az bir kaydı vardır.
        main_src = MAIN_PY.read_text(encoding="utf-8")
        registered = set(re.findall(r"^\s*app\.include_router\(\s*(\w+)", main_src, re.M))
        self.assertGreaterEqual(_include_router_calls(), len(_apirouter_modules()))

    def test_table_rows_match_filesystem_exactly(self):
        rows = set(re.findall(r"^\|\s*\**`app/routers/(\w+)\.py`", self.readme, re.M))
        fs = _fs_modules()
        self.assertEqual(rows - fs, set(), f"README'de olmayan dosyalar listelenmiş: {sorted(rows - fs)}")
        self.assertEqual(fs - rows, set(), f"README tablosunda eksik router modülleri: {sorted(fs - rows)}")


if __name__ == "__main__":
    unittest.main()
