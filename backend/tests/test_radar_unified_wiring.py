"""BİRLEŞİK RADAR — Aşama 2 kablolama kilitleri (tek tip bildirim + otonom yönlendirme).

Kilitleen davranış:
  1. `radar_unified_notify=true` iken:
     - radar push'u `radar-{sym}` tag + `sources=["velocity"]` ile gider.
     - AYNI TURDA aynı sembol için yükseliş push'u BASTIRILIR (çift bildirim ölür).
     - Radar push'u yoksa yükseliş `radar-{sym}` + `sources=["rising"]` ile birincil olur.
     - `rising_alert` WS tipi YAYINLANMAZ (tek kanal: `monitoring_alert`).
  2. `radar_unified_notify=false` iken eski davranış BİREBİR korunur.
  3. `RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER=true` iken velocity otonom girişi
     auto_paper'a yönlendirilir; panel skor hamdan `_panel_score` ile türetilir.
"""
import asyncio
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import monitoring, velocity            # noqa: E402
from app.routers import auto_paper                      # noqa: E402


def _radar_notif(symbol="BTCTRY"):
    return {"symbol": symbol, "message": "radar", "title": "radar", "url": f"/charts?symbol={symbol}",
            "tag": f"monitoring-{symbol}", "score": 74.0, "target_pct": 2.0,
            "quiet_hours": False, "updated": False, "id": None}


def _rising_notif(symbol="ETHTRY"):
    return {"symbol": symbol, "message": "rising", "title": "rising", "url": f"/charts?symbol={symbol}",
            "tag": f"rising-{symbol}", "score": 72.0, "target_pct": 2.0,
            "quiet_hours": False, "updated": False, "alert_id": 1}


def _run(coro):
    return asyncio.run(coro)


class UnifiedNotifyTests(unittest.TestCase):
    def _ctx(self, unified: bool):
        settings = {"enabled": True, "radar_unified_notify": unified,
                    "radar_combined_enabled": False}
        send = AsyncMock(return_value=True)
        ws = MagicMock()
        ws.broadcast = AsyncMock(return_value=None)
        mark_rising = AsyncMock()
        mark_monitoring = AsyncMock()
        auto_paper_fn = AsyncMock(return_value=None)
        patches = [
            patch.object(monitoring, "get_user_notification_settings",
                         new=AsyncMock(return_value=settings)),
            patch.object(monitoring, "_send_push", new=send),
            patch.object(monitoring, "ws_manager", ws),
            patch.object(monitoring.database, "mark_rising_alert_notified", new=mark_rising),
            patch.object(monitoring.database, "mark_monitoring_push_sent", new=mark_monitoring),
            patch.object(auto_paper, "try_open_from_notification", new=auto_paper_fn),
            patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "dummy-key"}, clear=False),
        ]
        return {"send": send, "ws": ws, "mark_rising": mark_rising,
                "patches": patches}

    def _enter(self, ctx):
        for p in ctx["patches"]:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in ctx["patches"]])

    def test_radar_push_uses_unified_tag_when_enabled(self):
        ctx = self._ctx(True)
        self._enter(ctx)
        _run(monitoring._deliver_scan_notifications([_radar_notif("BTCTRY")]))
        pushed = ctx["send"].await_args.args[0]
        self.assertEqual("radar-BTCTRY", pushed["tag"])
        self.assertEqual(["velocity"], pushed["sources"])
        self.assertIn("BTCTRY", monitoring._unified_pushed_symbols)

    def test_rising_is_suppressed_when_radar_already_pushed(self):
        monitoring._unified_pushed_symbols.clear()
        monitoring._unified_pushed_symbols.add("BTCTRY")
        ctx = self._ctx(True)
        self._enter(ctx)
        _run(monitoring._rising_deliver([_rising_notif("BTCTRY")]))
        ctx["send"].assert_not_awaited()
        ctx["mark_rising"].assert_awaited()
        args = ctx["mark_rising"].await_args.args
        self.assertEqual(1, args[0])
        self.assertIs(False, args[1])

    def test_rising_is_primary_and_uses_unified_channel(self):
        monitoring._unified_pushed_symbols.clear()
        ctx = self._ctx(True)
        self._enter(ctx)
        _run(monitoring._rising_deliver([_rising_notif("ETHTRY")]))
        pushed = ctx["send"].await_args.args[0]
        self.assertEqual("radar-ETHTRY", pushed["tag"])
        self.assertEqual(["rising"], pushed["sources"])
        # Tek kanal: rising_alert YAYINLANMAMALI.
        for call in ctx["ws"].broadcast.await_args_list:
            self.assertNotEqual("rising_alert", call.args[0]["type"])

    def test_legacy_mode_is_unchanged(self):
        monitoring._unified_pushed_symbols.clear()
        ctx = self._ctx(False)
        self._enter(ctx)
        _run(monitoring._rising_deliver([_rising_notif("ETHTRY")]))
        pushed = ctx["send"].await_args.args[0]
        self.assertEqual("rising-ETHTRY", pushed["tag"])
        types = [call.args[0]["type"] for call in ctx["ws"].broadcast.await_args_list]
        self.assertIn("rising_alert", types)

    def test_radar_push_is_not_tagged_when_disabled(self):
        ctx = self._ctx(False)
        self._enter(ctx)
        _run(monitoring._deliver_scan_notifications([_radar_notif("BTCTRY")]))
        pushed = ctx["send"].await_args.args[0]
        self.assertEqual("monitoring-BTCTRY", pushed["tag"])
        self.assertNotIn("sources", pushed)


class VelocityRoutingTests(unittest.TestCase):
    def test_envelope_maps_raw_score_to_panel(self):
        candidate = {"symbol": "BTCTRY", "velocity_score": 1400.0, "target_pct": 2.0,
                     "horizon_minutes": 5, "price": 100.0}
        env = velocity._velocity_to_auto_paper_envelope(candidate)
        self.assertEqual(velocity._panel_score(1400.0), env["score"])
        self.assertEqual("BTCTRY", env["symbol"])
        self.assertEqual(2.0, env["target_pct"])
        self.assertTrue(env["notification_key"].startswith("velocity-auto-BTCTRY-"))
        self.assertEqual("velocity_auto", env["source"])

    def test_route_opens_via_auto_paper(self):
        candidate = {"symbol": "BTCTRY", "velocity_score": 1400.0, "target_pct": 2.0,
                     "horizon_minutes": 5, "price": 100.0}
        with patch.object(auto_paper, "try_open_from_notification",
                          new=AsyncMock(return_value={"status": "opened", "trade_id": 7,
                                                      "symbol": "BTCTRY"})):
            outcome = _run(velocity._route_velocity_through_auto_paper(candidate))
        self.assertEqual("PAPER_OPENED", outcome["status"])
        self.assertEqual("auto_paper", outcome["via"])
        self.assertEqual(7, outcome["trade_id"])

    def test_route_skips_when_auto_paper_blocks(self):
        candidate = {"symbol": "BTCTRY", "velocity_score": 1400.0, "target_pct": 2.0}
        with patch.object(auto_paper, "try_open_from_notification",
                          new=AsyncMock(return_value={"status": "blocked", "reason": "max_open"})):
            outcome = _run(velocity._route_velocity_through_auto_paper(candidate))
        self.assertEqual("SKIPPED", outcome["status"])
        self.assertIn("auto_paper:max_open", outcome["reason"])

    def test_route_handles_auto_paper_exception(self):
        candidate = {"symbol": "BTCTRY", "velocity_score": 1400.0, "target_pct": 2.0}
        with patch.object(auto_paper, "try_open_from_notification",
                          new=AsyncMock(side_effect=RuntimeError("db down"))):
            outcome = _run(velocity._route_velocity_through_auto_paper(candidate))
        self.assertEqual("SKIPPED", outcome["status"])
        self.assertIn("auto_paper_hata", outcome["reason"])


class ReplayJobWiringTests(unittest.TestCase):
    """Ayarlar > Radar sekmesindeki replay butonunun arka uç kablolaması."""

    def test_replay_module_loads_from_scripts(self):
        """scripts/... yolu packaged (Docker) düzende de çözülmeli — en kırılgan nokta."""
        from app.routers import maintenance
        mod = maintenance._load_replay_module()
        self.assertTrue(callable(mod.build_report), "build_report yüklenmedi")
        self.assertTrue(callable(mod._simulate_ladder), "_simulate_ladder yüklenmedi")

    def test_status_endpoint_shape(self):
        from app.routers import maintenance
        data = asyncio.run(maintenance.combined_radar_replay_status())
        self.assertTrue(data["ok"])
        self.assertTrue(data["paper_only"])
        self.assertIn("status", data)
        self.assertIn("progress", data)
        self.assertIn("logs", data)
        self.assertIn("result", data)

    def test_start_endpoint_requires_admin(self):
        """Replay tüm journal'ı okuyup ~140 REST isteği atar → admin kapısı ŞART."""
        from app.routers import maintenance

        class _Anon:
            headers = {}
            cookies = {}

        with self.assertRaises(Exception) as ctx:
            asyncio.run(maintenance.start_combined_radar_replay({}, _Anon()))
        self.assertEqual(401, getattr(ctx.exception, "status_code", None))


class RadarEndpointRobustnessTests(unittest.TestCase):
    """422/500 regresyon kilidi (Ayarlar > Radar sekmesinin uçları).

    Gerçek olay: `/api/monitoring/settings` 422, `/api/combined-radar-replay/report.csv`
    500 dönüyordu.
    """

    # ---- 500: CSV `sources` boş/None olduğunda patlamamalı -----------------
    def test_signal_row_always_has_string_sources(self):
        """Journal satırında `source`/`sources` YOK → yine de dolu string liste."""
        script = _replay_module()
        row = script._as_signal_row(
            {"symbol": "BTCTRY", "price": 100.0, "target_pct": 2.0, "velocity_score": 1500.0},
            1700000000.0, default_source="velocity")
        self.assertEqual(["velocity"], row["sources"])
        self.assertTrue(all(isinstance(s, str) and s for s in row["sources"]))

    def test_signal_row_filters_none_and_empty_sources(self):
        script = _replay_module()
        row = script._as_signal_row({"symbol": "BTCTRY", "sources": [None, "", "rising"]}, None)
        self.assertEqual(["rising"], row["sources"])
        row2 = script._as_signal_row({"symbol": "BTCTRY", "sources": [None]}, None,
                                     default_source="combined")
        self.assertEqual(["combined"], row2["sources"])

    def test_csv_endpoint_survives_none_sources(self):
        """CSV üretimi `sources=[None]` ile 500 VERMEMELİ (TypeError kaynağı)."""
        from app.routers import maintenance
        maintenance._combined_radar_replay["result"] = {
            "signals": [
                {"stream": "velocity_only", "symbol": "BTCTRY", "detected_at": 1.0,
                 "price": 100.0, "target_pct": 2.0, "score": 74.0, "confluence": False,
                 "sources": [None], "exit_reason": "take_profit", "exit_price": 102.0,
                 "gross_pct": 2.0, "net_pct": 1.65, "mfe_pct": 2.1, "mae_pct": -0.3,
                 "hold_minutes": 12.0},
                {"stream": "rising_only", "symbol": "ETHTRY", "sources": None},
                "bozuk-satır",
            ],
        }
        with patch("app.api_common.require_admin",
                   return_value={"username": "admin", "role": "admin"}):
            response = asyncio.run(maintenance.download_combined_radar_replay_csv(object()))
        self.assertEqual(200, response.status_code)
        body = response.body.decode("utf-8")
        self.assertIn("BTCTRY", body)
        self.assertIn("velocity_only", body)

    def test_csv_endpoint_handles_missing_result(self):
        from app.routers import maintenance
        maintenance._combined_radar_replay["result"] = None
        with patch("app.api_common.require_admin",
                   return_value={"username": "admin", "role": "admin"}):
            response = asyncio.run(maintenance.download_combined_radar_replay_csv(object()))
        self.assertEqual(200, response.status_code)

    # ---- 422: OKUMA yolu doğrulama yüzünden patlamamalı -------------------
    def test_reader_clamps_invalid_confluence_instead_of_raising(self):
        """DB'de bozuk değer olsa bile GET ayarları okunabilmeli (422 YOK)."""
        from app.routers import monitoring
        for bad in (None, 0, -5, 999999, "abc", {}):
            with patch.object(monitoring.database, "get_llm_setting",
                              new=AsyncMock(return_value=json.dumps(
                                  {"radar_confluence_window_sec": bad}))):
                settings = asyncio.run(monitoring.get_monitoring_settings())
            self.assertEqual(int(monitoring.config.RADAR_CONFLUENCE_WINDOW_SEC),
                             settings["radar_confluence_window_sec"],
                             f"bozuk değer ({bad!r}) kırpılmadı")

    def test_writer_still_rejects_invalid_confluence(self):
        from fastapi import HTTPException
        from app.routers import monitoring
        with self.assertRaises(HTTPException) as ctx:
            monitoring._radar_confluence_window(None)
        self.assertEqual(422, ctx.exception.status_code)

    def test_clamp_never_raises(self):
        from app.routers import monitoring
        default = int(monitoring.config.RADAR_CONFLUENCE_WINDOW_SEC)
        self.assertEqual(default, monitoring._clamp_confluence_window(None))
        self.assertEqual(default, monitoring._clamp_confluence_window("abc"))
        self.assertEqual(1800, monitoring._clamp_confluence_window(1800))
        self.assertEqual(60, monitoring._clamp_confluence_window(60))

    def test_threshold_fields_publish_target_range(self):
        """İstemci doğrulaması sunucuyla AYNI aralığı kullanabilsin (422 önlenir)."""
        from app.routers import monitoring
        fields = monitoring._threshold_fields({"min_score": 71.5, "min_target_pct": 2.0})
        self.assertIn("min_target_pct_min", fields)
        self.assertIn("min_target_pct_max", fields)
        self.assertLess(fields["min_target_pct_min"], fields["min_target_pct_max"])
        # Varsayılan değer aralığın İÇİNDE olmalı — yoksa hiçbir kayıt geçemezdi.
        self.assertLessEqual(fields["min_target_pct_min"], 2.0)
        self.assertGreaterEqual(fields["min_target_pct_max"], 2.0)


class ReplayMeasurementTests(unittest.TestCase):
    """Ölçüm doğruluğu kilitleri (2026-09-16) — kullanıcının CSV'sinden çıkan 3 hata.

    CSV kanıtı: (1) velocity satırlarında `score` BOŞ, combined'da 19893.9/28822.9
    gibi HAM değerler; (2) tüm satırlarda `hold_minutes` 28-30 → ufuk daima 30 dk;
    (3) birebir aynı satırlar iki kez.
    """

    @classmethod
    def setUpClass(cls):
        cls.script = _replay_module()

    # ---- (1) ufuk sinyalin KENDİ değeri olmalı ---------------------------
    def test_horizon_uses_signal_value_not_a_constant(self):
        self.assertEqual(5.0, self.script._resolve_horizon({}, 60.0))
        self.assertEqual(15.0, self.script._resolve_horizon({"horizon_minutes": 15}, 60.0))
        self.assertEqual(5.0, self.script._resolve_horizon({"horizon_minutes": 5}, 60.0))

    def test_horizon_is_clamped(self):
        self.assertEqual(60.0, self.script._resolve_horizon({"horizon_minutes": 999}, 60.0))
        self.assertEqual(5.0, self.script._resolve_horizon({"horizon_minutes": 0}, 60.0))
        self.assertEqual(5.0, self.script._resolve_horizon({"horizon_minutes": "abc"}, 60.0))

    def test_signal_row_carries_horizon(self):
        row = self.script._as_signal_row({"symbol": "BTCTRY", "horizon_minutes": 15},
                                         1700000000.0, default_source="velocity")
        self.assertEqual(15.0, row["horizon_minutes"])
        defaulted = self.script._as_signal_row({"symbol": "BTCTRY"}, 1700000000.0,
                                               default_source="rising", default_horizon=5.0)
        self.assertEqual(5.0, defaulted["horizon_minutes"])

    def test_ladder_horizon_is_measured_from_signal_time(self):
        """Ufuk sinyal ANINDAN ölçülür; ilk bardan ölçmek pencereyi kaydırıyordu."""
        t0 = 1_700_000_000_000
        rows = [[t0, 100.0, 100.0, 99.9, 100.0, 1.0],
                [t0 + 60_000, 100.2, 100.2, 100.1, 100.2, 1.0],
                [t0 + 120_000, 100.1, 100.1, 100.0, 100.1, 1.0]]
        # Sinyal t0+30s'te ve ufuk 1.5 dk → due t0+120s → İKİNCİ bar dahil.
        with_signal = self.script._simulate_ladder(rows, 100.0, 2.0, 1.5,
                                                   signal_ms=t0 + 30_000)
        self.assertEqual("horizon_end", with_signal["exit_reason"])
        self.assertAlmostEqual(100.2, with_signal["exit_price"], places=6)
        # Sinyal anı verilmezse taban ilk bar olur → due t0+90s → İKİNCİ bar hariç.
        without = self.script._simulate_ladder(rows, 100.0, 2.0, 1.5)
        self.assertAlmostEqual(100.0, without["exit_price"], places=6)

    # ---- (2) ölçek: velocity HAM → PANEL ---------------------------------
    def test_velocity_journal_row_gets_panel_score(self):
        """Journal satırı `score` değil `velocity_score` taşır; panel'e çevrilmeli."""
        from app.routers import velocity
        raw = 1400.0
        item = {"symbol": "BTCTRY", "velocity_score": raw}
        item["score"] = velocity._panel_score(raw)      # build_report'ın yaptığı
        row = self.script._as_signal_row(item, 1700000000.0, default_source="velocity")
        self.assertEqual(velocity._panel_score(raw), row["score"])
        self.assertLessEqual(row["score"], 100.0, "panel skoru 100'ü aşmamalı")
        self.assertGreater(row["score"], 0.0)

    # ---- (3) mükerrer sinyal temizliği -----------------------------------
    def test_dedupe_removes_exact_duplicates(self):
        signals = [
            {"symbol": "ACMTRY", "detected_at": 1789543660.085, "target_pct": 4.0},
            {"symbol": "ACMTRY", "detected_at": 1789543660.085, "target_pct": 4.0},
        ]
        self.assertEqual(1, len(self.script._dedupe_signals(signals)))

    def test_dedupe_keeps_distinct_targets_and_times(self):
        signals = [
            {"symbol": "SAGATRY", "detected_at": 1789512522.152, "target_pct": 3.0},
            {"symbol": "SAGATRY", "detected_at": 1789512522.152, "target_pct": 2.5},
            {"symbol": "ACMTRY", "detected_at": 1789543660.085, "target_pct": 4.0},
        ]
        self.assertEqual(3, len(self.script._dedupe_signals(signals)))

    def test_dedupe_tolerates_missing_fields(self):
        self.assertEqual(1, len(self.script._dedupe_signals([{}, {}])))


def _replay_module():
    from app.routers import maintenance
    return maintenance._load_replay_module()


if __name__ == "__main__":
    unittest.main()