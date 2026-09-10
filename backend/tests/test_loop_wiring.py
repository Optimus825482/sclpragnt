"""Arka plan döngüsü kablolama (wiring) testleri.

Neden var
---------
2026-09-10: ``autonomous_velocity_loop`` tam olarak uygulanmıştı ama
``startup_services()`` içinde ``_start_background`` ile **başlatılmıyordu**.
Sonuç: ``VELOCITY_AUTO_ENABLED=true`` olmasına rağmen otonom hız avcısı hiç
tarama yapmıyordu ve durum ucu env'e bakıp "açık" raporluyordu (sessiz ölü
kanca). Bu sınıf hata — "döngü tanımlı ama başlatılmamış" — ne derleyici ne de
mevcut testler tarafından yakalanıyordu.

Bu test, ``app/`` içindeki her ``*_loop`` tanımının gerçekten erişilebilir
olduğunu doğrular. Erişilebilirlik iki yoldan biri olabilir:

1. ``main.py`` içinde adı geçiyor (doğrudan ``_start_background(X_loop, ...)``
   veya bir ``*_start_loop`` süpervizörü üzerinden), **veya**
2. kendi modülünde ``create_task(X_loop(...))`` ile başlatılıyor
   (süpervizör deseni: monitoring/auto_paper/macd).

Aksi hâlde test kırılır ve yeni döngünün başlatılmadığını söyler.
"""
import pathlib
import re
import unittest

_APP = pathlib.Path(__file__).resolve().parents[1] / "app"
_MAIN = _APP / "main.py"

#: ``_loop`` ile bitmeyen ama döngü işlevi gören, bilinçli olarak başlatılmayan
#: kancalar. Boş olmalı — bir isim buraya eklenirse gerekçesi yazılmalıdır.
_ALLOWED_UNWIRED: set[str] = set()


def _loop_definitions() -> dict[str, pathlib.Path]:
    """``app/`` altındaki tüm ``async def <name>loop(...)`` tanımları."""
    found: dict[str, pathlib.Path] = {}
    for path in _APP.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"^async def ([a-zA-Z_]\w*loop)\s*\(", text, re.M):
            found.setdefault(match.group(1), path)
    return found


class BackgroundLoopWiringTests(unittest.TestCase):
    def test_every_loop_definition_is_actually_started(self):
        main_src = _MAIN.read_text(encoding="utf-8")
        unwired: list[str] = []

        for name, path in sorted(_loop_definitions().items()):
            if name in _ALLOWED_UNWIRED:
                continue
            # Yol 1: main.py içinde adı geçiyor (doğrudan ya da süpervizör aracılığıyla)
            if re.search(r"\b" + re.escape(name) + r"\b", main_src):
                continue
            # Yol 2: kendi modülünde create_task(<name>(...)) ile başlatılıyor
            own_src = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"create_task\(\s*" + re.escape(name) + r"\s*\(", own_src):
                continue
            unwired.append(f"{name} ({path.name})")

        self.assertEqual(
            [], unwired,
            "Şu arka plan döngüleri tanımlı ama HİÇBİR YERDE başlatılmıyor "
            "(main.py'ye _start_background ekleyin veya modülünde create_task "
            "ile başlatın): " + ", ".join(unwired),
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
