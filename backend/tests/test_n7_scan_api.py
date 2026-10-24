"""N7 TARAMA uçları (`/api/radar/n7-scan`): oturum kapısı, 409, ilerleme, bitiş ve hata yolu (2026-10-24).

Sahte oturum ve sahte `momentum_scan.scan` (ağ yok). Arka plan görevi gerçek `_start_background` ile açılır; TestClient
`with` bloğu içinde kullanılır ki istekler arası event loop yaşasın ve görev tamamlanabilsin.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import momentum_scan, n7_scan_job  # noqa: E402
from app.routers import n7_scan  # noqa: E402

PICKED = [{"sym": "AAATRY", "px": 10.0, "score": 7.5, "r1": 1.2, "r2": 2.0, "r4": 3.1, "r24": 5.0, "vr": 2.2,
           "vol_ratio": 2.2, "vwap_rel": 0.8, "room": 3.0, "base": 25.0, "hl": 2, "atr15": 0.5, "qv24": 9e6, "chg24": 5.0}]


def _result(top):
    return {"cutoff_ms": 1, "universe": 40, "candidates": 12, "picked": PICKED[:top], "scanned": 55, "elapsed_s": 0.1,
            "source": "rest", "top": top}


def _wait(client, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = client.get("/api/radar/n7-scan").json()
        if snap["status"] != "running":
            return snap
        time.sleep(0.01)
    raise AssertionError("tarama bitmedi")


@pytest.fixture
def env(monkeypatch):
    n7_scan_job.reset()
    st = types.SimpleNamespace(calls=[], logged=[], release=threading.Event(), fail=None)

    def require_user(request):
        if request.headers.get("x-user") != "ali":
            raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
        return {"username": "ali", "role": "user"}

    async def log_user_action(*a, **k):
        st.logged.append((a, k))

    async def fake_scan(cutoff_ms, top=3, bars_loader=None, concurrency=6, progress=None):
        st.calls.append({"cutoff_ms": cutoff_ms, "top": top})
        progress(1, 2)
        while not st.release.is_set():          # test serbest bırakınca biter → 409 deterministik sınanır
            await asyncio.sleep(0.005)
        progress(2, 2)
        if st.fail:
            raise st.fail
        return _result(top)

    monkeypatch.setattr(n7_scan, "require_user", require_user)
    monkeypatch.setattr(n7_scan, "log_user_action", log_user_action)
    monkeypatch.setattr(momentum_scan, "scan", fake_scan)

    app = FastAPI()
    app.include_router(n7_scan.router)
    with TestClient(app, headers={"x-user": "ali"}) as client:
        st.client, st.anon = client, TestClient(app)
        yield st
        st.release.set()
        if n7_scan_job.is_running():
            _wait(client)
    n7_scan_job.reset()


def test_requires_login(env):
    assert env.anon.get("/api/radar/n7-scan").status_code == 401
    assert env.anon.post("/api/radar/n7-scan/run", json={"top": 3}).status_code == 401
    assert env.calls == []


def test_idle_snapshot_shape(env):
    snap = env.client.get("/api/radar/n7-scan").json()
    assert snap == {"status": "idle", "started_at": None, "finished_at": None, "progress": {"done": 0, "total": 0},
                    "error": None, "top": 3, "result": None}


def test_run_then_409_then_done(env):
    before = int(time.time() * 1000)
    r = env.client.post("/api/radar/n7-scan/run", json={"top": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running" and body["top"] == 5 and body["started_at"] >= before

    dup = env.client.post("/api/radar/n7-scan/run")
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Tarama zaten çalışıyor"

    t0 = time.time()
    while env.client.get("/api/radar/n7-scan").json()["progress"] != {"done": 1, "total": 2}:
        assert time.time() - t0 < 5, "ilerleme gelmedi"
        time.sleep(0.005)
    running = env.client.get("/api/radar/n7-scan").json()
    assert running["status"] == "running" and running["result"] is None and running["finished_at"] is None

    env.release.set()
    snap = _wait(env.client)
    assert snap["status"] == "done" and snap["error"] is None
    assert snap["progress"] == {"done": 2, "total": 2}
    assert snap["finished_at"] >= snap["started_at"] == body["started_at"]
    assert snap["result"]["picked"][0]["sym"] == "AAATRY"
    assert snap["result"]["scanned"] == 55 and snap["top"] == 5
    assert len(env.calls) == 1 and env.calls[0]["top"] == 5 and env.calls[0]["cutoff_ms"] == body["started_at"]
    # denetim kaydı: kategori/aksiyon
    assert env.logged and env.logged[0][0][2:4] == ("monitoring", "n7_scan_run")


def test_top_default_and_clamp(env):
    env.release.set()
    assert env.client.post("/api/radar/n7-scan/run").json()["top"] == 3
    _wait(env.client)
    assert env.client.post("/api/radar/n7-scan/run", json={"top": 99}).json()["top"] == 10
    _wait(env.client)
    assert env.client.post("/api/radar/n7-scan/run", json={"top": 0}).json()["top"] == 1
    _wait(env.client)
    assert [c["top"] for c in env.calls] == [3, 10, 1]


def test_previous_result_kept_while_rerunning(env):
    env.release.set()
    env.client.post("/api/radar/n7-scan/run", json={"top": 1})
    first = _wait(env.client)
    assert first["status"] == "done"
    env.release.clear()
    env.client.post("/api/radar/n7-scan/run", json={"top": 2})
    snap = env.client.get("/api/radar/n7-scan").json()
    assert snap["status"] == "running"
    assert snap["result"] == first["result"]          # eski liste yeni sonuç gelene dek kalır
    env.release.set()
    assert _wait(env.client)["status"] == "done"


def test_error_sets_status_error(env):
    env.fail = RuntimeError("borsa yok")
    env.release.set()
    env.client.post("/api/radar/n7-scan/run")
    snap = _wait(env.client)
    assert snap["status"] == "error"
    assert snap["error"] == "RuntimeError: borsa yok"
    assert snap["result"] is None and snap["finished_at"] is not None
    # hata sonrası yeni tarama başlatılabilir
    env.fail = None
    assert env.client.post("/api/radar/n7-scan/run").status_code == 200
    assert _wait(env.client)["status"] == "done"


def test_route_registered():
    from app.main import app
    paths = app.openapi()["paths"]
    assert "/api/radar/n7-scan" in paths and "/api/radar/n7-scan/run" in paths
