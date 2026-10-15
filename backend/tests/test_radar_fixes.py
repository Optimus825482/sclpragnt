"""RADAR TARAMA DÜZELTMELERİ (docs/RADAR_TARAMA_ANALIZI_2026-10-15.md bölüm 3).

Her madde için kilit test; düzeltme geri alınırsa ilgili test KIRILIR.

  (1) database.evaluate_daily_rising_report — canlı fiyat yalnız AÇIK pencereye
      girer; MFE/hit girişi `notify_price`; anchor ayrı alan.
  (2) unified_outcomes — `detected_at` gerçek sinyal zamanı; dedup penceresi
      (symbol, horizon, floor(t/horizon)); boş mum dönen satır mühürlenir.
  (3) panel_score her kaynakta normalize_score(raw); rising/squeeze ham alanı
      `_raw_from_panel`; `_rank` yalnız panel.
  (4) Tek `gate_candidate()` hem `_notify` hem kombine listede; süzülen satır
      `blocked_by` ile UI çıktısında kalır.
  (5) Kombine yol velocity taramasını `journal_enabled=False` ile çağırır.
  (6) Kombine liste tekilleştirmesi SEMBOL bazında; ufuklar liste.
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import database  # noqa: E402


# ---------------------------------------------------------------------------
# Ortak sahte DB (test_m4_database_fixes.py deseni)
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """SQL metnine göre satır döndüren sahte bağlantı; çağrıları kaydeder."""

    def __init__(self, routes=(), default=()):
        self.routes = list(routes)
        self.default = list(default)
        self.calls = []
        self.commits = 0

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.calls.append((text, params))
        for needle, rows in self.routes:
            if needle in text:
                return _FakeCursor(rows, rowcount=1)
        return _FakeCursor(self.default, rowcount=1)

    def commit(self):
        self.commits += 1


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


def _candles_5m(since_s: float, highs: list[float], lows: list[float]):
    """`historical_candles` satırları: since_s'den sonra 5 dk aralıklı mumlar."""
    rows = []
    for i, (h, lo) in enumerate(zip(highs, lows)):
        rows.append({"open_time": (since_s + 300 * (i + 1)) * 1000.0,
                     "high": h, "low": lo, "close": (h + lo) / 2.0})
    return rows


# ---------------------------------------------------------------------------
# (1) MÜHÜRLÜ PENCERE + notify_price GİRİŞİ
# ---------------------------------------------------------------------------
def _evaluate(monkeypatch, candidates, since_s, max_sec, live, candles):
    conn = _RoutedConn(routes=[("FROM historical_candles", candles)])
    monkeypatch.setattr(database, "_run_db", _patched_run_db(conn))
    return asyncio.run(database.evaluate_daily_rising_report(
        candidates, since_s, live_prices=live, max_sec=max_sec))


def test_sealed_window_ignores_live_price(monkeypatch):
    """Ufku BİTMİŞ (mühürlü) listede şimdiki fiyat MFE/MAE penceresine GİRMEZ:
    mumlar +%2'ye çıkmışken canlı fiyat +%10 olsa da MFE %2 kalır."""
    since = 1_700_000_000.0
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "SEALTRY", "price": 100.0, "ceiling_pct": 5.0}],
        since, max_sec=600.0, live={"SEALTRY": 110.0},
        candles=_candles_5m(since, highs=[101.0, 102.0], lows=[99.5, 99.0]))
    assert len(rows) == 1
    r = rows[0]
    assert r["mfe_pct"] == pytest.approx(2.0), f"mühürlü MFE canlı fiyatla değişti: {r['mfe_pct']}"
    assert r["mae_pct"] == pytest.approx(-1.0)
    assert r["hit_ceiling"] is False, "tavan (%5) mum penceresinde vurulmadı"
    # Anlık fiyat yine raporlanır (değişim sütunu), ama pencereye katılmaz.
    assert r["current_price"] == 110.0


def test_open_window_includes_live_price(monkeypatch):
    """Ufku SÜREN (en yeni) listede canlı fiyat pencereye girer (eski davranış)."""
    since = time.time() - 120.0           # 2 dk önce gönderildi, 10 dk ömür
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "OPENTRY", "price": 100.0, "ceiling_pct": 5.0}],
        since, max_sec=600.0, live={"OPENTRY": 110.0},
        candles=_candles_5m(since, highs=[101.0], lows=[99.5]))
    assert rows[0]["mfe_pct"] == pytest.approx(10.0)
    assert rows[0]["hit_ceiling"] is True


def test_mfe_entry_is_notify_price_not_anchor(monkeypatch):
    """Taşınan (carried) sembolde MFE/hit girişi BU listenin fiyatı
    (`notify_price`); zincir başı `anchor_price` ayrı alanda raporlanır —
    sinyal öncesi kazanç MFE'ye karışmaz (sim ile aynı giriş)."""
    since = 1_700_000_000.0
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "CARRYTRY", "price": 80.0, "notify_price": 100.0,
          "anchor_price": 80.0, "ceiling_pct": 10.0}],
        since, max_sec=600.0, live=None,
        candles=_candles_5m(since, highs=[103.0], lows=[99.0]))
    r = rows[0]
    assert r["entry_price"] == 100.0
    assert r["mfe_pct"] == pytest.approx(3.0), "anchor (80) girişiyle MFE %28.75 olurdu"
    assert r["hit_ceiling"] is False
    assert r["anchor_price"] == 80.0
    assert r["anchor_mfe_pct"] == pytest.approx(28.75)


def test_report_summary_does_not_override_price_with_anchor():
    """monitoring.daily_rising_reports_summary: adayın `price`'ı anchor ile
    EZİLMEZ (DB fonksiyonu notify_price'ı kendisi seçer)."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_reports_summary)
    assert '"price": x.get("anchor_price")' not in src
