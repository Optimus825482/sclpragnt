"""A1/A2 (2026-09-14) — MACD teyidi velocity skoruna nasıl giriyor.

Kanıtlanmış güç: MACD MONITOR'ün kapanmış-mum disiplini + çoklu-TF uyumu. İki çarpan:

  A1 (`velocity.py:445-452`): kapanmış M1 histogram teyidi
      bullish AND rising  → ×1.15
      bullish             → ×1.05
      derin negatif + düşüşte (dip-gate, `VELOCITY_MACD_DIP_GATE_ATR`) → ×0.85
  A2 (`velocity.py:511-516`): M5 yeşil + M1 yükselen → ×1.10

Testler çarpanları **izole** eder: aynı klines ile tarama iki kez koşturulur —
`VELOCITY_MACD_CONFIRMATION_ENABLED` açık ve kapalı — ve **oran** karşılaştırılır.
Mutlak skor formülüne bağlı olmadığı için formül kalibrasyonu değişse de kırılmaz;
yalnızca çarpan sözleşmesi bozulursa kırılır.

`_macd` monkeypatch edilir (seri uzunluğuna göre dağıtılır) → MACD değerleri
deterministik, uydurma fiyat serisiyle dalgalanma yok.
"""
from __future__ import annotations

import math
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from app.routers import velocity

SYMBOL = "BTCTRY"


def _kline_rows(closes, step_ms, now_ms):
    """[open_time, open, high, low, close, volume, ...] — kapanmış mum varsayımı."""
    rows = []
    n = len(closes)
    for i, c in enumerate(closes):
        t = now_ms - (n - i) * step_ms
        rows.append([t, c, c * 1.004, c * 0.996, c, 1000.0 + i])
    return rows


def _uptrend(n, base=100.0):
    """Volatil yükseliş: ATR/BB sıfırdan farklı olsun (skor kapıya takılmasın)."""
    return [base * (1 + 0.003 * i) + 1.5 * math.sin(i / 2.0) for i in range(n)]


class _FakeMacd:
    """Seri uzunluğuna göre M1 / M1-prev / M5 histogramı döndürür.

    Tarama sırası: `_macd(closes)` → `_macd(closes[:-1])` → `_macd(m5_closes)`.
    Forming mum düşerse uzunluklar bir azalır; eşikler her iki durumu da kapsar.
    """

    def __init__(self, m1_hist, m1_prev, m5_hist=0.0):
        self.m1_hist = m1_hist
        self.m1_prev = m1_prev
        self.m5_hist = m5_hist

    def __call__(self, closes):
        n = len(closes)
        if n >= 60:  # M1 tam seri
            return {"histogram": self.m1_hist}
        if n >= 58:  # M1 "bir önceki bar" serisi
            return {"histogram": self.m1_prev}
        return {"histogram": self.m5_hist}


class VelocityMacdConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def _score(self, fake_macd, confirmation_enabled=True):
        """Tek sembollük tarama; adayın `velocity_score`'unu ve MACD bayraklarını döndür."""
        now_ms = int(time.time() * 1000)
        m1 = _kline_rows(_uptrend(60), 60_000, now_ms)
        m5 = _kline_rows(_uptrend(40, base=500.0), 300_000, now_ms)

        async def fake_fetch(symbol, interval, limit):
            return m1 if interval == "1m" else m5

        with patch.object(velocity, "_velocity_rate_acquire", AsyncMock(return_value=None)), \
             patch.object(velocity, "top_gainers", AsyncMock(return_value=[{"symbol": SYMBOL}])), \
             patch.object(velocity, "fetch_klines", fake_fetch), \
             patch.object(velocity, "_macd", fake_macd), \
             patch.object(velocity, "micro_structure_multiplier", MagicMock(return_value=1.0)), \
             patch.object(velocity.microflow, "get_snapshot", MagicMock(return_value={})), \
             patch.object(velocity.microflow, "start", AsyncMock(return_value=None)), \
             patch.object(velocity.ml_forecast, "predict_target", MagicMock(return_value=None)), \
             patch.object(velocity.database, "get_symbol_target_state", AsyncMock(return_value=None)), \
             patch.object(velocity.database, "save_velocity_candidates", AsyncMock(return_value=None)), \
             patch.object(velocity.database, "get_velocity_calibration_stats", AsyncMock(return_value={})), \
             patch.object(config, "SYMBOLS", []), \
             patch.object(config, "MONITORING_TARGET_ADAPTIVE", False), \
             patch.object(config, "VELOCITY_MACD_CONFIRMATION_ENABLED", confirmation_enabled):
            res = await velocity.detect_velocity_candidates({}, horizon_minutes=5)
        row = next((r for r in (res["candidates"] + res["watchlist"]) if r["symbol"] == SYMBOL), None)
        self.assertIsNotNone(row, "aday üretilemedi — fixture kapıya takıldı")
        return row

    async def _ratio(self, fake_macd):
        """Aynı klines ile açık/kapalı oranı → saf çarpan."""
        on = await self._score(fake_macd, True)
        off = await self._score(fake_macd, False)
        self.assertGreater(off["velocity_score"], 0)
        return on["velocity_score"] / off["velocity_score"], on

    # ---- A1 ---------------------------------------------------------------
    async def test_bullish_and_rising_gives_1_15(self):
        row = None
        ratio, row = await self._ratio(_FakeMacd(2.0, 1.0))
        self.assertTrue(row["macd_bullish"] and row["macd_rising"],
                        "fixture bullish+rising üretmeli")
        self.assertAlmostEqual(1.15, ratio, places=4)

    async def test_bullish_but_falling_gives_1_05(self):
        ratio, row = await self._ratio(_FakeMacd(2.0, 3.0))
        self.assertTrue(row["macd_bullish"])
        self.assertFalse(row["macd_rising"], "azalan histogram rising SAYILMAMALI")
        self.assertAlmostEqual(1.05, ratio, places=4)

    async def test_deep_negative_and_falling_applies_dip_gate_0_85(self):
        """Dip-gate: histogram ATR-tabanlı eşiğin altında VE düşüşte → ×0.85."""
        ratio, row = await self._ratio(_FakeMacd(-50.0, -40.0))
        self.assertFalse(row["macd_bullish"])
        self.assertFalse(row["macd_rising"])
        self.assertAlmostEqual(0.85, ratio, places=4)

    async def test_shallow_negative_falling_is_not_penalised(self):
        """Eşik üstü negatif histogram cezalanmamalı (yalnız DİP cezalanır)."""
        ratio, row = await self._ratio(_FakeMacd(0.0, -1.0))
        self.assertFalse(row["macd_bullish"])
        self.assertAlmostEqual(1.0, ratio, places=4)

    async def test_disabled_leaves_score_untouched_by_a1(self):
        """Kapalıyken MACD histogramı skora HİÇ dokunmamalı.

        Farklı histogramlar (güçlü bullish vs dip) kapalı modda AYNI skoru
        vermeli — çarpan bayrağın dışına sızarsa test kırılır.
        """
        bullish = await self._score(_FakeMacd(2.0, 1.0), False)
        dip = await self._score(_FakeMacd(-50.0, -40.0), False)
        self.assertAlmostEqual(bullish["velocity_score"], dip["velocity_score"], places=6)

    # ---- A2 ---------------------------------------------------------------
    # NOT: A2 çarpanı `VELOCITY_MACD_CONFIRMATION_ENABLED`e BAĞLI DEĞİL
    # (yalnız A1 bağlı, `velocity.py:446` vs `:515`). Bu yüzden izolasyon
    # açık/kapalı değil, M5 yeşil ↔ M5 kırmızı karşıtlığıyla yapılır.
    async def _a2_ratio(self, m1_hist, m1_prev):
        green = await self._score(_FakeMacd(m1_hist, m1_prev, m5_hist=5.0), True)
        red = await self._score(_FakeMacd(m1_hist, m1_prev, m5_hist=-5.0), True)
        self.assertTrue(green["m5_macd_bullish"])
        self.assertFalse(red["m5_macd_bullish"])
        return green["velocity_score"] / red["velocity_score"], green

    async def test_m5_green_with_m1_rising_adds_1_10(self):
        """M5 yeşil + M1 yükselen → ×1.10 (çoklu-TF uyumu)."""
        ratio, green = await self._a2_ratio(2.0, 1.0)
        self.assertTrue(green["macd_rising"])
        self.assertAlmostEqual(1.10, ratio, places=4)

    async def test_m5_green_without_m1_rising_adds_nothing(self):
        """Uyum yoksa (M1 yükselmiyor) M5 bonusu VERİLMEZ.

        MACD MONITOR felsefesi: tek TF kırılganlığından çıkış ancak UYUM ile
        olur; M5 yeşil tek başına yeterli değil.
        """
        ratio, green = await self._a2_ratio(2.0, 3.0)
        self.assertFalse(green["macd_rising"])
        self.assertAlmostEqual(1.0, ratio, places=4)


if __name__ == "__main__":
    unittest.main()
