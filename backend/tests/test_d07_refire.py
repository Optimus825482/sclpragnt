"""D-07 (2026-09-14): yeniden tetikleme kapisi — fiyat DEGISTI mi?

Kanit: ARKTRY 13.09.2026'da 33 bildirim; 10/32 ardisik ciftte fiyat AYNEN ayni
(9,45). 03:01..06:18 arasinda 10 bildirimin 9'u ayni fiyattan. Zaman kapilari
(cooldown 300 sn + pending ufuk+2dk = 420 sn) bunu GORMEZ — yalnizca "sure doldu
mu" diye bakar. Donmus/likit olmayan sembolde ayni sinyal tekrar tekrar uretilir.

Esik taramasi (104 tespit / 88 ardisik cift):
    0.10% -> 20 bastirilan / 0 TAMAMEN kaybi
    0.35% -> 26 bastirilan / 0 TAMAMEN kaybi   <-- gidis/donus maliyeti, secilen
    0.50% -> 31 bastirilan / 1 TAMAMEN kaybi
    0.75% -> 41 bastirilan / 2 TAMAMEN kaybi
TAMAMEN orani %8.0 -> %11.3 (0.35% ile), hicbir gercek basari kaybetmeden.

Additive: BEKLIYOR bildirimin guncellenme yolu DEGISMEZ.
"""
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
            "quiet_hours_start": None, "quiet_hours_end": None}


class RefireGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.routers import monitoring
        self.m = monitoring
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        monitoring._monitoring_state["candidate_streak"] = {}
        monitoring._monitoring_state["notified_prices"] = {}
        monitoring._monitoring_state["refire_blocked"] = 0
        monitoring._monitoring_state["risk_off"] = False

    def _cand(self, symbol="FLATTRY", price=9.45, score=15.0, target=5.0):
        return {"symbol": symbol, "velocity_score": score,
                "target_pct": target, "price": price, "horizon_minutes": 5}

    async def _notify(self, candidates, ticker_price=None):
        """Zaman kapilarini (cooldown/pending) her cagri oncesi temizler;
        boyunca YALNIZCA fiyat kapisi olculur.

        `ticker_price`: D-05 taze-ticker tabani. None -> adayin kendi fiyati.
        """
        self.m._monitoring_state["notified_symbols"] = {}
        self.m._monitoring_state["pending_targets"] = {}
        with patch.object(self.m.database, "save_monitoring_notifications",
                          new_callable=AsyncMock, return_value=0), \
             patch.object(self.m.database, "get_pending_monitoring_notifications",
                          new_callable=AsyncMock, return_value={}), \
             patch.object(self.m, "deliver_web_push", return_value={"ok": True}), \
             patch.object(self.m, "_record_history", return_value=None), \
             patch.object(self.m, "_ticker_price", return_value=ticker_price), \
             patch.object(self.m.config, "MONITORING_DEBOUNCE_SCANS", 0):
            return await self.m._notify(candidates, SETTINGS)

    async def test_second_signal_blocked_when_price_unchanged(self):
        """Ayni fiyat -> ikinci bildirim URETILMEZ (ARKTRY 9,45 vakasi)."""
        first = await self._notify([self._cand(price=9.45)])
        second = await self._notify([self._cand(price=9.45)])
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [], "fiyat degismedigi halde yeniden tetiklendi")

    async def test_allowed_when_price_moved_enough(self):
        """+%0.5 hareket (esik %0.35 ustu) -> yeni bildirim GECER."""
        await self._notify([self._cand(price=9.45)])
        second = await self._notify([self._cand(price=9.45 * 1.005)])
        self.assertEqual(len(second), 1, "gercek hareket bastirildi")

    async def test_small_move_below_threshold_blocked(self):
        """+%0.10 hareket esik altinda -> bastirilir."""
        await self._notify([self._cand(price=9.45)])
        second = await self._notify([self._cand(price=9.45 * 1.001)])
        self.assertEqual(second, [])

    async def test_boundary_exactly_at_threshold_passes(self):
        """Esik KATI KUCUKTUR (`<`): hareket TAM esikteyse gecer.

        Esik/parite 1.0 / 100 -> 101 olarak secildi: bu degerler IEEE-754'te
        TAM temsil edilir (move == 1.0). 0.35/100->100.35'te float gurultusu
        `move == thr` üretmezdi ve `<` ile `<=` ayirt edilemezdi.
        """
        with patch.object(self.m, "MONITORING_REFIRE_MIN_MOVE_PCT", 1.0):
            await self._notify([self._cand(price=100.0)])
            # tam esikte: gecer
            at = await self._notify([self._cand(price=101.0)])
            self.assertEqual(len(at), 1, "esik degerinde hareket gecmeli (`<`)")

    async def test_boundary_just_below_threshold_blocked(self):
        with patch.object(self.m, "MONITORING_REFIRE_MIN_MOVE_PCT", 1.0):
            await self._notify([self._cand(price=100.0)])
            below = await self._notify([self._cand(price=100.5)])
            self.assertEqual(below, [], "esik alti hareket bastirilmali")

    async def test_threshold_defaults_to_round_trip_cost(self):
        """Varsayilan esik = gidis/donus maliyeti (%0.35), sabit degil."""
        from app.config import config
        self.assertAlmostEqual(config.round_trip_cost() * 100,
                               self.m.MONITORING_REFIRE_MIN_MOVE_PCT, places=9)
        self.assertAlmostEqual(0.35, self.m.MONITORING_REFIRE_MIN_MOVE_PCT, places=9)

    async def test_frozen_price_produces_single_notification(self):
        """10 tarama boyunca fiyat donmus -> TEK bildirim (vaka: 9 x 9,45)."""
        fired = 0
        for _ in range(10):
            res = await self._notify([self._cand(price=9.45)])
            fired += len(res)
        self.assertEqual(1, fired, f"donmus fiyatta {fired} bildirim uretildi")

    async def test_counter_records_suppressed_refires(self):
        await self._notify([self._cand(price=9.45)])
        for _ in range(4):
            await self._notify([self._cand(price=9.45)])
        self.assertEqual(4, self.m._monitoring_state["refire_blocked"])

    async def test_price_records_and_updates_after_real_move(self):
        await self._notify([self._cand(price=9.45)])
        self.assertAlmostEqual(9.45, self.m._monitoring_state["notified_prices"]["FLATTRY"], places=9)
        await self._notify([self._cand(price=9.60)])
        # Hareketten sonra yeni taban kaydedilir; bir sonraki kapi buna bakar.
        self.assertAlmostEqual(9.60, self.m._monitoring_state["notified_prices"]["FLATTRY"], places=9)

    async def test_missing_or_zero_price_never_blocks(self):
        """Fiyat yoksa kapisiz: veri eksikligi sinyali BASTIRMAMALI (fail-open)."""
        await self._notify([self._cand(price=9.45)])
        self.m._monitoring_state["notified_prices"]["FLATTRY"] = 9.45
        res = await self._notify([self._cand(price=0)])
        self.assertEqual(len(res), 1, "fiyat 0 -> kapisiz gecmeli (yanlis bastirma)")

    async def test_fresh_ticker_price_is_the_gate_base(self):
        """D-05 ile ayni tek taban: taze ticker varsa kapisi O belirler."""
        await self._notify([self._cand(price=9.45)])
        res = await self._notify([self._cand(price=9.45)], ticker_price=9.45 * 1.02)
        self.assertEqual(len(res), 1, "ticker %2 yukari gitmis; aday fiyati ayni olsa da gecmeli")

    async def test_ticker_gate_does_not_disable_candidate_price_path(self):
        """Ticker YOKSA adayin kendi fiyati kullanilir (D-05 fail-open)."""
        await self._notify([self._cand(price=9.45)])
        res = await self._notify([self._cand(price=9.45 * 1.01)], ticker_price=None)
        self.assertEqual(len(res), 1)

    async def test_different_symbols_are_independent(self):
        """Kapi sembol bazlidir; birinin bastirilmasi digerini etkilemez."""
        await self._notify([self._cand(symbol="AATRY", price=9.45)])
        blocked = await self._notify([self._cand(symbol="AATRY", price=9.45)])
        other = await self._notify([self._cand(symbol="BBTRY", price=9.45)])
        self.assertEqual(blocked, [])
        self.assertEqual(len(other), 1)


# --------------------------------------------------------------------------
# Mutasyon notlari (dogrulandi):
#  1) Kapinin kosulunu silmek (her zaman gec)          -> 8 test kirilir.
#  2) `<` yerine `<=` (esikte bastir)                  -> test_boundary_... kirilir.
#  3) `notified_prices` hic yazilmasa (kapi devre disi) -> frozen/unchanged testleri kirilir.
#  4) Esigi 0 yapmak                                    -> hicbir sey bastirilmaz, testler kirilir.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
