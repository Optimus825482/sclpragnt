from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security
from app.routers import auto_paper_diagnostics as diagnostics


def test_closed_diagnostics_requires_admin_and_bounds_the_day(monkeypatch):
    app = FastAPI()
    app.include_router(diagnostics.router)
    client = TestClient(app)
    path = "/api/auto-paper/diagnostics"
    rows = AsyncMock(return_value={"trades": [], "reset_at": None, "has_more": False})
    monkeypatch.setattr(diagnostics, "_closed_trades", rows)

    monkeypatch.setattr(security, "request_user", lambda *args, **kwargs: None)
    assert client.get(path, params={"day": "2026-11-25"}).status_code == 401
    monkeypatch.setattr(security, "request_user", lambda *args, **kwargs: {"role": "viewer"})
    assert client.get(path, params={"day": "2026-11-25"}).status_code == 403
    monkeypatch.setattr(security, "request_user", lambda *args, **kwargs: {"role": "admin"})
    assert client.get(path, params={"day": "all"}).status_code == 422
    assert client.get(path, params={"day": "2026-11-25", "limit": 251}).status_code == 422
    rows.assert_not_awaited()

    response = client.get(path, params={"day": "2026-11-25"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["trades"] == []
    rows.assert_awaited_once_with(1795554000.0, 1795640400.0, 100, 0, False)


def test_market_context_returns_404_for_missing_closed_trade(monkeypatch):
    app = FastAPI()
    app.include_router(diagnostics.router)
    client = TestClient(app)
    monkeypatch.setattr(security, "request_user", lambda *args, **kwargs: {"role": "admin"})
    detail = AsyncMock(return_value=None)
    monkeypatch.setattr(diagnostics, "_market_context", detail)

    assert client.get("/api/auto-paper/diagnostics/42/market").status_code == 404
    detail.assert_awaited_once_with(42)
