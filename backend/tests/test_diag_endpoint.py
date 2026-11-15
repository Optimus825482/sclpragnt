"""AUTH'suz teşhis ucu (/_diag/paper) — GÜVENLİK testleri.

Bu uç auth'suz olduğu için en kritik özellik: veri sızdırmamak.
"""
import inspect
import pathlib
import os

import pytest

BASE = pathlib.Path(__file__).parent.parent
DIAG = BASE / "app" / "routers" / "_diag.py"
MAIN = BASE / "app" / "main.py"


def test_diag_is_public_path():
    src = MAIN.read_text(encoding="utf-8")
    assert '"/_diag/paper"' in src
    assert "app.include_router(_diag.router)" in src


def test_closed_when_env_missing(monkeypatch):
    """Token env YOKSA uç 404 — varlığını bile sızdırmaz."""
    from fastapi import HTTPException
    from app.routers import _diag

    monkeypatch.delenv("SCALPER_DIAG_TOKEN", raising=False)
    with pytest.raises(HTTPException) as e:
        _diag._check("herhangi")
    assert e.value.status_code == 404


def test_wrong_token_404(monkeypatch):
    from fastapi import HTTPException
    from app.routers import _diag

    monkeypatch.setenv("SCALPER_DIAG_TOKEN", "dogru-token")
    for bad in ("", "yanlis", "dogru-toke", "dogru-token "):
        with pytest.raises(HTTPException) as e:
            _diag._check(bad)
        assert e.value.status_code == 404


def test_correct_token_passes(monkeypatch):
    from app.routers import _diag

    monkeypatch.setenv("SCALPER_DIAG_TOKEN", "dogru-token")
    _diag._check("dogru-token")  # istisna ATMAMALI


def test_token_compared_constant_time():
    """Sabit zamanlı karşılaştırma (timing saldırısı engeli)."""
    src = DIAG.read_text(encoding="utf-8")
    assert "hmac.compare_digest" in src
    assert "==" not in src.split("def _check")[1].split("def ")[1]


def test_no_sensitive_columns_in_output():
    """Sembol, fiyat, kullanıcı adı, hash DÖNMEMELİ (toplulaştırma zorunlu)."""
    src = DIAG.read_text(encoding="utf-8")
    for bad in ("symbol,", "password_hash", "username,", "entry_price,", "exit_price,"):
        assert bad not in src, f"sizinti riski: {bad}"


def test_read_only_queries():
    """Yalnız select — hiçbir yazma yok."""
    src = DIAG.read_text(encoding="utf-8").lower()
    for bad in ("insert ", "update ", "delete ", "drop ", "alter "):
        assert bad not in src, f"yazma sorgusu bulundu: {bad}"


def test_output_is_aggregated_only():
    """Dönen yapıda tekil işlem listesi YOK — yalnız histogram/dağılım."""
    src = DIAG.read_text(encoding="utf-8")
    for agg in ("by_reason", "sl_pct_histogram", "by_profile", "daily"):
        assert agg in src


def test_atr_column_not_used():
    """auto_paper_trades'te atr_pct KOLONU YOK (canlı DB'de dogrulandi)."""
    src = DIAG.read_text(encoding="utf-8")
    assert "atr_pct" not in src


def test_days_clamped():
    """days 1..365 aralığında kırpılmalı."""
    src = DIAG.read_text(encoding="utf-8")
    assert "max(1, min(int(days), 365))" in src


def test_fail_open_on_db_error():
    """DB hatası olsa bile uç 200 döner, error alanı dolar."""
    src = DIAG.read_text(encoding="utf-8")
    assert 'out["error"] =' in src


def test_diag_returns_aggregated_payload(monkeypatch):
    """Uc yapisi: tekil islem degil toplulastirilmis alanlar doner.

    DB'ye BAGIMLI DEGIL: _run_db sahte veri doner. Testin amaci yapi
    sozlesmesi (baska testler DB'yi kapatabiliyor).
    """
    import asyncio
    from app.routers import _diag

    monkeypatch.setattr(_diag, "_check", lambda t: None)

    class FakeCur:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return self._rows

    async def fake_run_db(op):
        return op(FakeCurConn())

    class FakeCurConn:
        def execute(self, sql, params=None):
            s = " ".join(sql.split())
            if "count(*) c" in s and "status = 'open'" in s:
                return FakeCur([{"c": 10, "open_c": 1, "mn": 1.0, "mx": 2.0}])
            if "coalesce(exit_reason" in s:
                return FakeCur([{"reason": "stop_loss", "c": 4, "m": -5.5,
                                 "lo": -8.0, "hi": -2.0, "winr": 0.0}])
            if "stop_loss = 'stop_loss'" in s or "exit_reason = 'stop_loss'" in s:
                return FakeCur([{"b": -4.0, "c": 3}])
            if "to_char" in s:
                return FakeCur([{"d": "2026-11-01", "c": 5, "m": -0.3}])
            if "exit_profile" in s:
                return FakeCur([{"p": "(yok)", "c": 5, "m": -1.0, "slp": -3.9}])
            return FakeCur([])

    monkeypatch.setattr(_diag.database, "_run_db", fake_run_db)

    class R:
        pass

    r = asyncio.run(_diag.paper_diag(R(), t="t", days=30))
    assert r["ok"] is True
    assert r["error"] is None
    for k in ("by_reason", "sl_pct_histogram", "by_profile", "daily", "summary"):
        assert k in r, f"eksik alan: {k}"
    assert r["by_reason"][0]["reason"] == "stop_loss"
    assert r["by_reason"][0]["n"] == 4
