"""W4 düzeltme kilitleri: kanıt katmanı bütünlüğü (F-02, F-01, TAH-02).

Üç ölçüm hatası burada sabitlenir; üçü de "yanlış ama makul görünen sayı"
üretiyordu ve bu yüzden eşik/ağırlık kararlarını zehirliyordu:

- **F-02** (`database._macd_forward_outcomes`): MACD alarmının 5m/15m/30m ileri
  getirisi, hedef ana ulaşılmadan yazılıyordu → üç ufka AYNI ~4,5 dk'lık getiri
  düşüyor ve satır `filled` olarak mühürleniyordu. Tüm LIFT/isabet ölçümü çöp.
- **F-01** (`macd_monitor`): `jump` skoru evren min-max normalizasyonuyla
  beslendiği için, evrenden güçlü bir sembol düşünce HİÇ DEĞİŞMEYEN sembollerin
  skoru yükseliyor → hayalet alarm.
- **TAH-02** (`forecast_learning` + `llm_chat` + `database`): hedef-dokunuş
  penceresi ufuktan bağımsız 120 dk idi ve satır ufuk kapanır kapanmaz
  mühürlendiği için ölçüm süpürücü gecikmesine bağlıydı.
"""
import unittest

from app import database as db
from app import forecast_learning as fl
from app.routers import macd_monitor as mm


# ---------------------------------------------------------------------------
# F-02 — MACD kanıt ileri-getirisi
# ---------------------------------------------------------------------------

class MacdForwardOutcomeTests(unittest.TestCase):
    BAR = 5 * 60_000

    def _rows(self, n_bars, base_close=100.0, step=1.0):
        return [(i * self.BAR, base_close + i * step + 1.0, base_close + i * step - 1.0,
                 base_close + i * step) for i in range(n_bars)]

    def test_partial_window_is_not_sealed(self):
        """F-02: 4,5 dk geçmişken HİÇBİR ufuk yazılmamalı (eskiden üçü de yazılırdı)."""
        t0 = 0.0
        rows = [(0.0, 101.0, 99.0, 100.5)]
        updates, mfe, mae = db._macd_forward_outcomes(rows, 100.0, t0, now_ms=4.5 * 60_000)
        self.assertEqual({}, updates, "Pencere dolmadan ufuk mühürlenmemeli")

    def test_15m_and_30m_not_filled_when_target_not_reached(self):
        """F-02: yalnız hedefi KAPSAYAN ufuklar doldurulur."""
        t0 = 0.0
        rows = self._rows(3)  # 0, 5, 10 dk barları
        updates, _mfe, _mae = db._macd_forward_outcomes(rows, 100.0, t0, now_ms=13 * 60_000)
        self.assertEqual({"outcome_5m_pct"}, set(updates),
                         f"13 dk'da yalnız 5m dolmalı, gelen: {sorted(updates)}")

    def test_full_window_fills_three_distinct_horizons(self):
        """F-02: tam pencere dolunca üç ufuk BİRBİRİNDEN FARKLI değer almalı."""
        t0 = 0.0
        rows = self._rows(7)  # 0..30 dk barları (30 dk barı 35. dk'da kapanır)
        updates, _mfe, _mae = db._macd_forward_outcomes(rows, 100.0, t0, now_ms=36 * 60_000)
        self.assertEqual({"outcome_5m_pct", "outcome_15m_pct", "outcome_30m_pct"}, set(updates))
        # Kapanışlar 100,101,...,106 → 5m=+1%, 15m=+3%, 30m=+6%
        self.assertAlmostEqual(1.0, updates["outcome_5m_pct"], places=6)
        self.assertAlmostEqual(3.0, updates["outcome_15m_pct"], places=6)
        self.assertAlmostEqual(6.0, updates["outcome_30m_pct"], places=6)

    def test_identical_values_across_horizons_no_longer_possible_early(self):
        """F-02 regresyon: erken pencerede üç ufka AYNI değer yazılmamalı."""
        t0 = 0.0
        rows = [(0.0, 101.0, 99.0, 100.5)]
        updates, _mfe, _mae = db._macd_forward_outcomes(rows, 100.0, t0, now_ms=4.5 * 60_000)
        self.assertNotEqual(3, len(updates))

    def test_mfe_mae_only_after_alert_bar(self):
        """MFE/MAE alarm anını içeren kısmi barı saymamalı (yapay şişme yok)."""
        t0 = 0.0
        rows = [
            (0.0, 200.0, 50.0, 100.0),      # alarm anı barı — uçları geriye dönük
            (self.BAR, 120.0, 95.0, 110.0),
            (2 * self.BAR, 130.0, 90.0, 125.0),
        ]
        _updates, mfe, mae = db._macd_forward_outcomes(rows, 100.0, t0, now_ms=16 * 60_000)
        self.assertAlmostEqual(30.0, mfe, places=6)
        self.assertAlmostEqual(-10.0, mae, places=6)


# ---------------------------------------------------------------------------
# F-01 — hayalet sıçrama alarmı
# ---------------------------------------------------------------------------

class GhostJumpAlarmTests(unittest.TestCase):
    def test_stable_range_resists_single_symbol_churn(self):
        """F-01: tek güçlü sembol düşünce referans aralığı neredeyse oynamamalı."""
        raws = [0.1 + 0.004 * i for i in range(99)] + [5.0]  # 99 normal + 1 uç sembol
        full_lo, full_hi = mm._stable_range(raws)
        trimmed = raws[:-1]  # en güçlü sembol evrenden düştü
        cut_lo, cut_hi = mm._stable_range(trimmed)
        self.assertLess(abs(cut_hi - full_hi), 0.05,
                        "Dayanıklı üst sınır tek sembol churn'ünde oynamamalı")
        # min/max ise 4,5 birim oynar — hayalet alarmın kaynağı buydu.
        self.assertGreater(abs(max(trimmed) - max(raws)), 1.0)

    def test_stable_range_falls_back_for_tiny_universe(self):
        """Küçük evrende yüzdelik gürültülü → min/max'a düşer (kapı devralır)."""
        self.assertEqual((0.0, 3.0), mm._stable_range([3.0, 1.0, 0.0, 2.0]))

    def test_own_activity_changed_flags_frozen_symbol(self):
        """F-01: raw+sigs+cvd aynıysa 'değişmedi' (hayalet aday)."""
        row = {"raw": 0.42, "sigs": {"5m": {"break": True}}, "cvd": {"buy_dominant": False}}
        self.assertFalse(mm._own_activity_changed(
            row, 0.42, {"5m": {"break": True}}, {"buy_dominant": False}))
        self.assertTrue(mm._own_activity_changed(
            row, 0.55, {"5m": {"break": True}}, {"buy_dominant": False}))
        self.assertTrue(mm._own_activity_changed(
            row, 0.42, {"5m": {"break": True, "vol": True}}, {"buy_dominant": False}))

    def test_update_jump_arm_blocks_churn_driven_alarm(self):
        """F-01 çekirdek: verisi değişmeyen sembol eşiği geçse de alarm basmamalı."""
        row = {"jump_armed": False}
        fired = mm._update_jump_arm(row, jump=65, jump_min=60, prev_jump=42,
                                    activity_changed=False)
        self.assertFalse(fired, "Normalizasyon kayması alarm üretmemeli")
        self.assertFalse(row["jump_armed"], "Bayrak da kurulmamalı (gerçek olayda tetiklenebilsin)")

    def test_update_jump_arm_fires_on_real_activity(self):
        """Gerçek veri değişiminde normal eşik geçişi alarm üretmeli."""
        row = {"jump_armed": False}
        fired = mm._update_jump_arm(row, jump=65, jump_min=60, prev_jump=42,
                                    activity_changed=True)
        self.assertTrue(fired)
        self.assertTrue(row["jump_armed"])


# ---------------------------------------------------------------------------
# TAH-02 — deterministik hedef-dokunuş penceresi
# ---------------------------------------------------------------------------

class HitWindowTests(unittest.TestCase):
    def test_grace_bounded_by_horizon(self):
        """TAH-02: grace ufku aşamaz → 5 dk tahmin en fazla 10 dk izlenir."""
        self.assertEqual(5, fl.effective_hit_grace_minutes(5, 120))
        self.assertEqual(60, fl.effective_hit_grace_minutes(60, 120))
        self.assertEqual(120, fl.effective_hit_grace_minutes(240, 120))
        self.assertEqual(0, fl.effective_hit_grace_minutes(5, 0))

    def test_outcome_window_seconds(self):
        self.assertEqual(600.0, fl.outcome_window_seconds(5, 120))
        self.assertEqual(7200.0, fl.outcome_window_seconds(60, 120))
        self.assertEqual(240 * 60.0 + 120 * 60.0, fl.outcome_window_seconds(240, 120))


class _Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = [_Row(r) for r in rows]

    def fetchall(self):
        return self._rows


class _RecordingConn:
    def __init__(self, select_rows):
        self._select_rows = select_rows
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return _FakeCursor(self._select_rows)

    def commit(self):
        self.statements.append("COMMIT")


class PendingWindowTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with(self, conn, coro):
        async def fake_run_db(operation):
            return operation(conn)
        original = db._run_db
        db._run_db = fake_run_db
        try:
            return await coro()
        finally:
            db._run_db = original

    async def test_pending_waits_for_full_window(self):
        """TAH-02: ufuk kapanmış ama grace penceresi dolmamış satır DEĞERLENDİRİLMEZ."""
        now = 1000.0
        rows = [
            {"forecast_id": "a", "created_at": now - 6 * 60, "horizon_minutes": 5},   # pencere=10dk → bekle
            {"forecast_id": "b", "created_at": now - 11 * 60, "horizon_minutes": 5},  # pencere doldu → hazır
        ]
        conn = _RecordingConn(rows)
        out = await self._run_with(conn, lambda: db.get_pending_llm_forecasts(now=now))
        self.assertEqual(["b"], [r["forecast_id"] for r in out])

    async def test_pending_window_is_sweep_delay_independent(self):
        """TAH-02: aynı satır, hangi gecikmeyle sorulursa sorulsun aynı kararı verir."""
        created = 1000.0
        rows = [{"forecast_id": "x", "created_at": created, "horizon_minutes": 5}]
        early = await self._run_with(_RecordingConn(rows),
                                     lambda: db.get_pending_llm_forecasts(now=created + 6 * 60))
        late = await self._run_with(_RecordingConn(rows),
                                    lambda: db.get_pending_llm_forecasts(now=created + 9 * 60))
        ready = await self._run_with(_RecordingConn(rows),
                                     lambda: db.get_pending_llm_forecasts(now=created + 10 * 60))
        self.assertEqual([], early)
        self.assertEqual([], late)
        self.assertEqual(["x"], [r["forecast_id"] for r in ready])


if __name__ == "__main__":
    unittest.main()
