"""P1-10 — `microflow.get_snapshot` sembol-parametrik olmalı (LOCK testleri).

Denetim (2026-10-07): `MicroFlow.get_snapshot` imzasında `symbol` parametresi
YOKTU (yalnız `price`), ama `routers/velocity.py` `get_snapshot(symbol=target,
price=...)` çağırıyordu → `TypeError` fallback GLOBAL aktif sembolü okuyor ve
dönen `symbol != target` olduğu için çağrı fiilen `None` dönüyordu. Sonuç: aktif
olmayan hiçbir aday mikro-yapı verisiyle sıralanamıyordu.

Bu testler düzeltmeyi kilitler: `get_snapshot(symbol=...)` O sembolün
1s serisini ve trade-flow'unu döndürmeli; aktif sembole düşmemeli. Çağıran
taraf da sembolü geçmeye devam etmelidir (kaynak sözleşmesi).
"""
from __future__ import annotations

import inspect
import time
import unittest

from app.microflow import MicroFlow


class MicroflowSymbolSnapshotTests(unittest.TestCase):
    def _mf(self) -> MicroFlow:
        mf = MicroFlow()
        now = time.time()
        # İki sembol, AYIRT EDİLEBİLİR seri ve akış: yabancı/aktif veri
        # karışırsa test bunu yakalar.
        for sym, closes in (("AAATRY", [10.0, 11.0, 12.0]),
                            ("BBBTRY", [100.0, 200.0, 300.0])):
            mf.bars["1s"][sym].update({
                "timestamps": [i * 1000 for i in range(len(closes))],
                "opens": list(closes), "highs": list(closes),
                "lows": list(closes), "closes": list(closes),
                "volumes": [1.0] * len(closes),
            })
            mf.ws_updated_at_by_symbol[sym] = now
        mf.trade_flow["AAATRY"].update({"buy_notional": 1_000.0, "buy_count": 4})
        mf.trade_flow["BBBTRY"].update({"buy_notional": 7_777.0, "buy_count": 9})
        return mf

    def test_snapshot_returns_requested_symbol_not_active(self):
        """Aktif sembol A iken B istenir → B'nin verisi dönmeli (eski hâl: None)."""
        mf = self._mf()
        mf.symbol = "AAATRY"
        snap = mf.get_snapshot(symbol="BBBTRY")
        self.assertEqual("BBBTRY", snap["symbol"])
        self.assertEqual(300.0, snap["bars"]["1s"]["last_close"])
        self.assertEqual(7_777.0, snap["trade_flow"]["buy_notional_try"])
        # Sembol başına WS damgası B için de kayıtlı → veri "hazır" sayılır.
        self.assertTrue(snap["data_ready"])

    def test_price_argument_does_not_override_requested_symbols_bars(self):
        mf = self._mf()
        mf.symbol = "AAATRY"
        snap = mf.get_snapshot(price=999.0, symbol="BBBTRY")
        self.assertEqual("BBBTRY", snap["symbol"])
        # İstenen sembolün 1s kapanışı varsa son fiyat O olur; `price` yedektir.
        self.assertEqual(300.0, snap["price"])

    def test_default_symbol_is_active_symbol_backward_compatible(self):
        """Parametre verilmezse eski davranış (aktif sembol) korunur."""
        mf = self._mf()
        mf.symbol = "AAATRY"
        snap = mf.get_snapshot(price=12.0)
        self.assertEqual("AAATRY", snap["symbol"])
        self.assertEqual(1_000.0, snap["trade_flow"]["buy_notional_try"])

    def test_lowercase_symbol_is_normalized(self):
        mf = self._mf()
        mf.symbol = "AAATRY"
        snap = mf.get_snapshot(symbol="bbbtry")
        self.assertEqual("BBBTRY", snap["symbol"])

    def test_unknown_symbol_does_not_leak_active_symbol_data(self):
        """Bilinmeyen sembol isteği aktif sembolün verisini DÖNDÜRMEMELİ."""
        mf = self._mf()
        mf.symbol = "AAATRY"
        snap = mf.get_snapshot(symbol="CCCTRY")
        self.assertEqual("CCCTRY", snap["symbol"])
        # Aktif A'nın serisi C'ye atfedilmemeli.
        self.assertIsNone(snap["bars"]["1s"]["last_close"])
        self.assertEqual(0, snap["bars"]["1s"]["count"])
        self.assertFalse(snap["data_ready"])

    def test_no_active_symbol_and_no_arg_reports_no_symbol(self):
        mf = MicroFlow()
        snap = mf.get_snapshot()
        self.assertIsNone(snap["symbol"])
        self.assertFalse(snap["data_ready"])


class VelocityCallerContractTests(unittest.TestCase):
    """Çağıran (`velocity.detect_velocity_candidates`) sembolü GEÇMELİ.

    İç içe kapanış (`_micro_for`) bu yüzden davranışla doğrudan çağrılamaz;
    kaynak sözleşmesi kilidi, eski iç içe `TypeError` fallback zincirinin geri
    gelmesini ve parametrik çağrının kaybolmasını engeller.
    """

    def test_caller_passes_symbol_to_get_snapshot(self):
        from app.routers import velocity

        src = inspect.getsource(velocity.detect_velocity_candidates)
        self.assertIn("get_snapshot(symbol=target", src)
        # Eski, sessizce yutan iki kademeli fallback geri gelmemeli.
        self.assertNotIn("get_snapshot(price=r[\"price\"])", src)

    def test_get_snapshot_accepts_symbol_keyword(self):
        mf = MicroFlow()
        mf.symbol = "AAATRY"
        # Anahtar kelime hatasız kabul edilmeli (eski imza TypeError verirdi).
        snap = mf.get_snapshot(symbol="AAATRY", price=1.0)
        self.assertEqual("AAATRY", snap["symbol"])


if __name__ == "__main__":
    unittest.main()
