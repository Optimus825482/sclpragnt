"""Radar tarama günlüğü testleri — saf, DB'siz (2026-10-18)."""
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import radar_scan_log as rsl  # noqa: E402


def _a(sym, passes, score, reason=None, **kw):
    return {"symbol": sym, "passes": passes, "velocity_score": score, "block_reason": reason, "price": 1.0, "atr_pct": 0.4,
            "rsi": 55.0, "mfi": 60.0, "ret3_pct": 0.5, "volume_ratio": 1.5, "mode": "trend", "target_pct": 1.7, **kw}


def _entry(**over):
    scans = {5: {"symbols_scanned": 9, "no_data_symbols": ["NODATATRY"], "scan_audit": [
        _a("NOTIFTRY", True, 2000), _a("DETTRY", True, 1900), _a("GATEDTRY", True, 1800), _a("LOWTRY", True, 900),
        _a("OPENTRY", True, 1700), _a("WATCHTRY", False, 500, "yapisal_teyit_yok"),
        _a("ATRTRY", False, 10, "atr_yetersiz:0.20%<0.25%"), _a("WICKTRY", False, 5, "ust_fitil_tuzagi:wick_0.70_z2.5")]},
        15: {"symbols_scanned": 9, "scan_audit": [_a("ATRTRY", True, 50)]}}
    cands = [{"symbol": "NOTIFTRY", "target_pct": 1.8}, {"symbol": "DETTRY"}, {"symbol": "GATEDTRY"}, {"symbol": "FUSIONTRY", "unified_score": 80}]
    gate = lambda c: "skor tabanı altı (65.0 < 70)" if c["symbol"] == "GATEDTRY" else None   # noqa: E731
    kw = dict(scan_no=7, scan_at=1000.0, scans=scans, candidates=cands, watchlist=[{"symbol": "WATCHTRY"}],
              notified_symbols=["NOTIFTRY"], open_symbols=["OPENTRY"], gate=gate, panel=lambda raw: raw / 25.0,
              min_panel_score=71.5, min_raw_score=1800.0)
    kw.update(over)
    return rsl.build_entry(**kw)


class ReasonTests(unittest.TestCase):
    def test_reason_codes(self):
        self.assertEqual(rsl.reason_code("atr_yetersiz:0.20%<0.25%"), "atr_yetersiz")
        self.assertEqual(rsl.reason_code("skor tabanı altı (65.0 < 70)"), "skor_tabani")
        self.assertEqual(rsl.reason_code("aile devre dışı: short_squeeze"), "aile_devre_disi")
        self.assertEqual(rsl.reason_code("mfi_asiri_alim:85"), "mfi_asiri_alim")
        self.assertIsNone(rsl.reason_code(""))
        self.assertIsNone(rsl.reason_code(None))

    def test_reason_info_known_and_unknown(self):
        info = rsl.reason_info("ust_fitil_tuzagi:wick_0.7")
        self.assertEqual((info["reason_label"], info["reason_tone"]), ("Üst fitil tuzağı", "danger"))
        unk = rsl.reason_info("yepyeni_neden:5")
        self.assertEqual((unk["reason_code"], unk["reason_tone"]), ("yepyeni_neden", "neutral"))


class BuildEntryTests(unittest.TestCase):
    def setUp(self):
        self.e = _entry()
        self.by = {r["symbol"]: r for r in self.e["rows"]}

    def test_statuses(self):
        expected = {"NOTIFTRY": "notified", "DETTRY": "detected", "GATEDTRY": "gated", "LOWTRY": "below_threshold",
                    "OPENTRY": "open_position", "WATCHTRY": "watch", "ATRTRY": "below_threshold", "WICKTRY": "rejected",
                    "NODATATRY": "no_data", "FUSIONTRY": "detected"}
        self.assertEqual({k: self.by[k]["status"] for k in expected}, expected)

    def test_reasons_and_tones(self):
        self.assertEqual(self.by["GATEDTRY"]["reason_code"], "skor_tabani")
        self.assertEqual(self.by["GATEDTRY"]["tone"], "warn")
        self.assertEqual(self.by["WICKTRY"]["reason_code"], "ust_fitil_tuzagi")
        self.assertIn("eşiği altı", self.by["LOWTRY"]["reason"])
        self.assertEqual(self.by["NOTIFTRY"]["tone"], "success")
        self.assertTrue(self.by["NOTIFTRY"]["notified"])

    def test_best_horizon_and_horizons_map(self):
        atr = self.by["ATRTRY"]
        self.assertEqual(atr["horizon"], 15)            # 15 dk profili geçti → en iyi ufuk o
        self.assertEqual(atr["horizons"]["5"]["reason_code"], "atr_yetersiz")
        self.assertTrue(atr["horizons"]["15"]["passes"])

    def test_counts_pool_and_order(self):
        self.assertEqual(sum(self.e["counts"].values()), len(self.e["rows"]))
        self.assertEqual(self.e["pool"], {"5": 9, "15": 9})
        order = [r["status"] for r in self.e["rows"]]
        self.assertEqual(order[0], "notified")
        self.assertEqual(order, sorted(order, key=lambda s: [x[0] for x in rsl.STATUS_CATALOG].index(s)))
        self.assertEqual(self.e["min_panel_score"], 71.5)

    def test_robust_to_bad_input(self):
        e = rsl.build_entry(scan_no=1, scan_at=1.0, scans={5: None, 15: {"scan_audit": [{"symbol": None}, {"symbol": "XTRY"}]}},
                            candidates=[None, {"symbol": "ZTRY"}], watchlist=[], notified_symbols=[None], open_symbols=[],
                            gate=lambda c: None, panel=lambda r: r, min_panel_score=None, min_raw_score=None)
        self.assertEqual({r["symbol"] for r in e["rows"]}, {"XTRY", "ZTRY"})


class HeldTests(unittest.TestCase):
    def test_detected_with_skip_reason_becomes_held(self):
        e = _entry(skip_reasons={"DETTRY": "teyit yetersiz (1 < 2 kaynak)", "FUSIONTRY": "mod devre dışı: unified"},
                   notify_context={"quiet_hours": False, "vapid": True, "minutes_since_push": 62.0})
        by = {r["symbol"]: r for r in e["rows"]}
        self.assertEqual(by["DETTRY"]["status"], "held")
        self.assertEqual(by["DETTRY"]["reason_code"], "teyit_yetersiz")
        self.assertEqual(by["FUSIONTRY"]["status"], "held")
        self.assertEqual(by["FUSIONTRY"]["reason_code"], "mod_devre_disi")
        self.assertEqual(e["counts"]["held"], 2)
        self.assertEqual(e["notify_context"]["minutes_since_push"], 62.0)

    def test_skip_reason_codes_map_to_known_labels(self):
        for text, code in [("sembol soğuma (5 dk)", "sembol_soguma"), ("günlük tavan (3)", "gunluk_tavan"),
                           ("bildirim zaten gönderildi (ufuk dolmadı; hedef/skor donduruldu)", "bildirim_zaten_gonderildi"),
                           ("beklenen fiyata ulaşılmadı (ufuk dolmadı; tekrar bildirim yok)", "beklenen_fiyata_ulasilmadi"),
                           ("risk/ödül kapısı", "risk_odul_kapisi"), ("MACD histerezisi: skor yükselmedi", "macd_histerezisi"),
                           ("fiyat son bildirimden beri yeterince değişmedi", "fiyat_son_bildirimden_beri_yeterince_degismedi"),
                           ("yalnız-hız adayı izleme listesine alındı", "yalniz_hiz_adayi_izleme_listesine_alindi"),
                           ("debounce: 1/2 ardışık tarama", "debounce")]:
            info = rsl.reason_info(text)
            self.assertEqual(info["reason_code"], code, text)
            self.assertIn(code, rsl.REASON_META, text)


class LogBufferTests(unittest.TestCase):
    def setUp(self):
        rsl.reset()

    def test_get_log_newest_first_and_filters(self):
        rsl.record(_entry(scan_no=1))
        rsl.record(_entry(scan_no=2))
        out = rsl.get_log(limit=1)
        self.assertEqual([s["scan_no"] for s in out["scans"]], [2])
        self.assertEqual(out["total_scans"], 2)
        only = rsl.get_log(limit=5, status="gated")
        self.assertTrue(all(r["status"] == "gated" for s in only["scans"] for r in s["rows"]))
        self.assertEqual(only["scans"][0]["counts"]["gated"], 1)          # sayaçlar süzmeden etkilenmez
        sym = rsl.get_log(limit=1, symbol="atrt")
        self.assertEqual([r["symbol"] for r in sym["scans"][0]["rows"]], ["ATRTRY"])
        self.assertEqual(len(out["status_catalog"]), 9)

    def test_ring_buffer_is_bounded(self):
        with patch.object(rsl, "_keep", return_value=5):
            for i in range(9):
                rsl.record({"scan_no": i, "rows": [], "counts": {}})
        self.assertEqual(rsl.get_log(limit=100)["total_scans"], 5)
        rsl.reset()


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_admin(self):
        from fastapi import HTTPException
        from app.routers import radar_log
        with patch("app.main._require_admin", side_effect=HTTPException(status_code=401, detail="x")):
            with self.assertRaises(HTTPException) as cm:
                await radar_log.radar_scan_log_view(MagicMock(), limit=5, symbol="", status="")
        self.assertEqual(cm.exception.status_code, 401)

    async def test_returns_log_for_admin(self):
        from app.routers import radar_log
        rsl.reset()
        rsl.record(_entry(scan_no=3))
        with patch("app.main._require_admin", return_value={"role": "admin"}):
            out = await radar_log.radar_scan_log_view(MagicMock(), limit=5, symbol="", status="")
        self.assertTrue(out["ok"])
        self.assertEqual(out["scans"][0]["scan_no"], 3)
        rsl.reset()

    def test_route_registered(self):
        from app.main import app
        self.assertIn("/api/admin/radar-scan-log", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
