"""Arka plan döngüsü kablolama (wiring) testleri.

Neden var
---------
2026-09-10: ``autonomous_velocity_loop`` tam olarak uygulanmıştı ama
``startup_services()`` içinde ``_start_background`` ile **başlatılmıyordu**.
Sonuç: ``VELOCITY_AUTO_ENABLED=true`` olmasına rağmen otonom hız avcısı hiç
tarama yapmıyordu ve durum ucu env'e bakıp "açık" raporluyordu (sessiz ölü
kanca). Bu sınıf hata — "döngü tanımlı ama başlatılmamış" — ne derleyici ne de
mevcut testler tarafından yakalanıyordu.

G-02 düzeltmesi (2026-09-12)
---------------------------
İlk sürüm, "başlatıldı" kanıtı olarak ``main.py`` içinde döngü adının
**herhangi bir yerde geçmesini** kabul ediyordu (``re.search(r"\\bname\\b")``).
``main.py`` döngüleri tepede import ettiği için bu koşul **her zaman** sağlanıyordu
→ 29 ``_start_background`` satırından biri silinse bile test geçiyordu
(mutasyonla kanıtlandı: 1/29 gerçek kapsam). Ayrıca ``^async def`` deseni
girintili tanımları (``MarketData._rest_refresh_loop``) hiç taramıyordu.

Şimdi kanıt YALNIZCA gerçek başlatma çağrısıdır:
``_start_background(<name>...)`` veya ``create_task(<name>(...))``.
Import/isim geçişi sayılmaz. ``test_detector_is_not_satisfied_by_imports``
bu özelliği mutasyonla çiviler.
"""
import pathlib
import re
import unittest

_APP = pathlib.Path(__file__).resolve().parents[1] / "app"
_MAIN = _APP / "main.py"

#: ``_loop`` ile bitmeyen ama döngü işlevi gören, bilinçli olarak başlatılmayan
#: kancalar. Boş olmalı — bir isim buraya eklenirse gerekçesi yazılmalıdır.
_ALLOWED_UNWIRED: set[str] = set()

#: Girintili (sınıf içi) tanımlar da yakalanır — G-02.
_LOOP_DEF_RE = re.compile(r"^[ \t]*async def ([a-zA-Z_]\w*loop)\s*\(", re.M)
#: Gerçek başlatma çağrıları.
_START_BG_RE = re.compile(r"_start_background\(\s*(?:lambda[^:]*:\s*)?([a-zA-Z_]\w*)")
_CREATE_TASK_RE = re.compile(r"create_task\(\s*(?:self\.)?([a-zA-Z_]\w*)\s*\(")


def _python_sources() -> list[pathlib.Path]:
    return [p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts]


def _loop_definitions() -> dict[str, pathlib.Path]:
    """``app/`` altındaki tüm ``async def <name>loop(...)`` tanımları."""
    found: dict[str, pathlib.Path] = {}
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _LOOP_DEF_RE.finditer(text):
            found.setdefault(match.group(1), path)
    return found


def _started_names_in(text: str) -> set[str]:
    """Bir kaynak metinde GERÇEKTEN başlatılan döngü adları."""
    started = set(_START_BG_RE.findall(text))
    started.update(_CREATE_TASK_RE.findall(text))
    return started


def _started_loops() -> set[str]:
    """Tüm ``app/`` kaynaklarında gerçekten başlatılan döngüler."""
    started: set[str] = set()
    for path in _python_sources():
        started |= _started_names_in(path.read_text(encoding="utf-8", errors="ignore"))
    return started


class BackgroundLoopWiringTests(unittest.TestCase):
    def test_every_loop_definition_is_actually_started(self):
        started = _started_loops()
        unwired: list[str] = []

        for name, path in sorted(_loop_definitions().items()):
            if name in _ALLOWED_UNWIRED:
                continue
            if name in started:
                continue
            unwired.append(f"{name} ({path.name})")

        self.assertEqual(
            [], unwired,
            "Şu arka plan döngüleri tanımlı ama HİÇBİR YERDE başlatılmıyor "
            "(main.py'ye _start_background ekleyin veya modülünde create_task "
            "ile başlatın): " + ", ".join(unwired),
        )

    def test_detector_is_not_satisfied_by_imports(self):
        """G-02: import/isim geçişi 'başlatıldı' sayılmamalı (mutasyon kanıtı)."""
        name = "radar_loop"
        main_src = _MAIN.read_text(encoding="utf-8")
        self.assertIn(name, _started_names_in(main_src), "Ön koşul: gerçekten başlatılıyor")

        mutated = re.sub(
            r"^.*_start_background\(\s*" + re.escape(name) + r"\b.*$\n?",
            "", main_src, flags=re.M)
        # Ad hâlâ import bloğunda geçiyor ama artık BAŞLATILMIŞ sayılmamalı.
        self.assertIn(name, mutated, "Ad import bloğunda kalmalı (mutasyon izole)")
        self.assertNotIn(
            name, _started_names_in(mutated),
            "Import/isim geçişi kablolama kanıtı olmamalı — G-02 regresyonu",
        )

    def test_detector_sees_indented_definitions(self):
        """G-02: sınıf içi (girintili) döngü tanımları da taranmalı."""
        self.assertIn("_rest_refresh_loop", _loop_definitions())

    def test_detector_is_not_vacuous(self):
        """Kapsam tabanı: algılanan başlatma sayısı gerçekçi olmalı (1/29 değil)."""
        started = _started_loops()
        definitions = _loop_definitions()
        self.assertGreaterEqual(len(definitions), 25)
        covered = [n for n in definitions if n in started or n in _ALLOWED_UNWIRED]
        self.assertGreaterEqual(
            len(covered), len(definitions),
            f"Kapsam düşük: {len(covered)}/{len(definitions)}",
        )

    def test_autonomous_velocity_loop_is_registered(self):
        """Kullanıcı kararıyla aktive edilen otonom hız avcısı bağlı olmalı."""
        main_src = _MAIN.read_text(encoding="utf-8")
        self.assertIn("autonomous_velocity_loop", main_src)
        self.assertRegex(
            main_src,
            r"_start_background\(\s*autonomous_velocity_loop\s*,",
            "autonomous_velocity_loop _start_background ile başlatılmalı",
        )


if __name__ == "__main__":
    unittest.main()
