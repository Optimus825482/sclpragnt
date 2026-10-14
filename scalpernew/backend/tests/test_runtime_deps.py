"""Geç bağlama (runtime_deps) davranış testleri.

2026-09-10 (Madde 14): main.py, handler'ları router global'lerine monkeypatch
ediyordu ve atama öncesi çağrı sessiz ``NameError`` veriyordu. Artık
``pending_dep`` yer tutucusu açıklayıcı hata verir ve ``assert_ready`` açılışta
eksik bağımlılığı yakalar.
"""
import unittest

from app import runtime_deps


class RuntimeDepsTests(unittest.TestCase):
    def setUp(self):
        runtime_deps.reset()

    def tearDown(self):
        runtime_deps.reset()

    def test_unbound_dependency_raises_clear_error(self):
        dep = runtime_deps.pending_dep("ornek_handl")
        with self.assertRaises(RuntimeError) as ctx:
            import asyncio
            asyncio.run(dep())
        message = str(ctx.exception)
        self.assertIn("ornek_handl", message)
        self.assertIn("bağlanmadı", message)

    def test_assert_ready_lists_missing(self):
        runtime_deps.pending_dep("eksik_bagimlilik")
        self.assertIn("eksik_bagimlilik", runtime_deps.missing())
        with self.assertRaises(RuntimeError) as ctx:
            runtime_deps.assert_ready()
        self.assertIn("eksik_bagimlilik", str(ctx.exception))
        # strict=False hata fırlatmaz, yalnız listeler
        self.assertEqual(["eksik_bagimlilik"], runtime_deps.assert_ready(strict=False))

    def test_bind_clears_missing_and_sets_real_handler(self):
        class _Module:
            pass

        module = _Module()
        dep = runtime_deps.pending_dep("ornek_handl")
        module.ornek_handl = dep
        self.assertEqual(["ornek_handl"], runtime_deps.missing())

        async def real_handler():
            return "gercek"

        runtime_deps.bind(module, "ornek_handl", real_handler)
        self.assertEqual([], runtime_deps.missing())
        self.assertIs(module.ornek_handl, real_handler)
        self.assertEqual([], runtime_deps.assert_ready())

    def test_optional_dependency_does_not_block_readiness(self):
        runtime_deps.pending_dep("istege_bagli_handl", required=False)
        self.assertNotIn("istege_bagli_handl", runtime_deps.missing())
        self.assertEqual([], runtime_deps.assert_ready())

    def test_production_bindings_are_real_handlers(self):
        """main.py import edildiğinde her bağımlılık GERÇEK handler'a bağlı olmalı.

        Not: yer tutucu ile gerçek handler ``__module__`` ile ayırt edilir —
        yer tutucular ``app.runtime_deps``, gerçekler ``app.main`` üretir. Bu
        kontrol registry durumundan bağımsızdır (modüller önbellekli olsa da
        doğrudur), böylece boş yere geçemez.
        """
        import app.main  # noqa: F401  (geç bağlama bloğunu çalıştırır)
        import app.routers.llm_chat as llm_chat
        import app.routers.runtime as runtime_routes

        expected = (
            (runtime_routes, ("llm_open_paper_trade", "gainers_radar")),
            (llm_chat, ("llm_open_paper_trade", "symbol_analysis",
                        "get_config", "get_strategy_stats")),
        )
        for module, names in expected:
            for name in names:
                fn = getattr(module, name)
                self.assertEqual(
                    "app.main", getattr(fn, "__module__", None),
                    f"{module.__name__}.{name} gerçek handler'a bağlı değil "
                    f"(geç bağlama unutulmuş)")

    def test_assert_ready_passes_on_fresh_registry_after_binding(self):
        """Taze registry üzerinde: eksik bildirilir, bağlanınca temizlenir.

        Not: hedef modül olarak ``object()`` KULLANILMAZ — düz ``object``
        örneğine setattr yapılamaz (``no __dict__``). Gerçek router modülleri
        sınıf gibi davranır, o yüzden basit bir namespace sınıfı kullanılır.
        """
        runtime_deps.reset()
        runtime_deps.pending_dep("llm_open_paper_trade")
        self.assertEqual(["llm_open_paper_trade"], runtime_deps.missing())

        async def real_handler():
            return None

        class _Module:
            pass

        module = _Module()
        runtime_deps.bind(module, "llm_open_paper_trade", real_handler)
        self.assertEqual([], runtime_deps.missing())
        self.assertIs(module.llm_open_paper_trade, real_handler)
        self.assertEqual([], runtime_deps.assert_ready())


if __name__ == "__main__":
    unittest.main()
