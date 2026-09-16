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


if __name__ == "__main__":
    unittest.main()