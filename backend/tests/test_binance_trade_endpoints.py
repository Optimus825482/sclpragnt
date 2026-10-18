"""Binance TR işlem uçları (HTTP). Sahte oturum/borsa/DB; GERÇEK EMİR YOK."""
import math
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import database, open_position, rr_service
from app.routers import binance_trade as bt

FILTERS = {"step_size": 0.01, "tick_size": 0.01, "min_notional": 10.0, "min_qty": 0.01,
           "quote_asset": "TRY", "oco_enable": True, "status": "TRADING"}


class Amb(Exception):
    pass


class FakeEx:
    AmbiguousError = Amb

    def __init__(self):
        self.free_try, self.px = 1000.0, 100.0
        self.buys, self.ocos = [], []
        self.buy_error = None

    async def symbol_to_underscore(self, s):
        s = s.upper().replace("_", "")
        return f"{s[:-3]}_TRY"

    async def filters(self, su):
        return dict(FILTERS)

    async def free_balance(self, asset, force=False):
        return self.free_try

    async def price(self, su):
        return self.px

    async def buy(self, su, q, cid):
        self.buys.append((su, q, cid))
        if self.buy_error:
            raise self.buy_error
        return {"order_id": "1"}

    async def order_detail(self, su, cid):
        qty = math.floor(self.buys[-1][1] / self.px * 0.999 * 100) / 100
        return {"status": 2, "executedQty": str(qty), "executedQuoteQty": str(round(qty * self.px, 2))}

    async def oco(self, su, qty, tp, sl):
        self.ocos.append((su, qty, tp, sl))
        return {"order_list_id": "9"}


class State:
    def __init__(self):
        self.live = True
        self.risk = {"max_position_pct": 50.0, "default_rr": 2.0}
        self.rows = {}
        self.logged = []
        self.keys_deleted = []
        self.user = {"id": 7, "username": "ali"}


@pytest.fixture
def env(monkeypatch):
    st, ex = State(), FakeEx()

    def require_user(request):
        if request.headers.get("x-user") != "ali":
            raise HTTPException(status_code=401, detail="Giriş gerekli")
        return {"username": "ali", "role": "user"}

    async def real_state(uid):
        return (st.live, "panel")

    async def creds(request, user=None):
        return ("k", "s")

    async def log_user_action(*a, **k):
        st.logged.append(a)

    async def analysis(symbol, tf):
        return {"price": 100.0, "volatility": {"atr_pct": 0.01}}

    fake_main = types.SimpleNamespace(
        _require_user=require_user, _real_sell_state_for=real_state, _decrypt_binance_creds=creds,
        symbol_analysis=analysis, _invalidate_binance_cost_cache=lambda uid: None,
        _session_identity=lambda request: ("ali", "user"), log_user_action=log_user_action,
        _ensure_binance_user_stream=lambda uid, k, s: _async({"started": True}),
    )
    monkeypatch.setattr(bt, "_main", lambda: fake_main)
    monkeypatch.setattr(bt, "_exchange_for", lambda k, s: ex)

    async def get_user(name):
        return st.user

    async def get_risk(uid):
        return dict(st.risk)

    async def set_risk(uid, values):
        st.risk.update(values)
        return dict(st.risk)

    async def claim(uid, cid, symbol, request):
        if (uid, cid) in st.rows:
            return False
        st.rows[(uid, cid)] = {"status": "in_progress", "symbol": symbol, "result": {}, "created_at": 0.0}
        return True

    async def finish(uid, cid, status, result):
        st.rows[(uid, cid)].update(status=status, result=result)

    async def get_req(uid, cid):
        return st.rows.get((uid, cid))

    async def delete_keys(uid):
        st.keys_deleted.append(uid)
        return True

    monkeypatch.setattr(database, "get_user_by_username", get_user)
    monkeypatch.setattr(database, "get_user_risk_settings", get_risk)
    monkeypatch.setattr(database, "set_user_risk_settings", set_risk)
    monkeypatch.setattr(database, "claim_order_request", claim)
    monkeypatch.setattr(database, "finish_order_request", finish)
    monkeypatch.setattr(database, "get_order_request", get_req)
    monkeypatch.setattr(database, "delete_user_binance_keys", delete_keys)
    monkeypatch.setattr(open_position, "DETAIL_RETRY_SLEEP_SEC", 0.0)

    async def no_llm(*a, **k):
        return None
    monkeypatch.setattr(rr_service, "_CACHE", {}, raising=False)
    monkeypatch.setattr("app.llm_analysis.chat", no_llm, raising=False)

    app = FastAPI()
    app.include_router(bt.router)
    client = TestClient(app, headers={"x-user": "ali"})
    return types.SimpleNamespace(client=client, st=st, ex=ex, anon=TestClient(app))


async def _async(v):
    return v


def _open_body(**kw):
    b = {"symbol": "ADATRY", "amount_try": 400.0, "sl_pct": 2.0, "rr": 2.0,
         "client_order_id": "cid-0000001", "confirmation": "REAL_OPEN"}
    b.update(kw)
    return b


# ---------------------------------------------------------------- kimlik

def test_endpoints_require_login(env):
    assert env.anon.get("/api/binance/risk").status_code == 401
    assert env.anon.post("/api/binance/open-position", json=_open_body()).status_code == 401
    assert env.anon.delete("/api/binance/keys").status_code == 401


# ---------------------------------------------------------------- risk

def test_risk_get_put_roundtrip_and_validation(env):
    assert env.client.get("/api/binance/risk").json()["max_position_pct"] == 50.0
    r = env.client.put("/api/binance/risk", json={"max_position_pct": 12.5, "default_rr": 3})
    assert r.status_code == 200 and r.json()["max_position_pct"] == 12.5
    assert env.client.put("/api/binance/risk", json={"max_position_pct": 500}).status_code == 422
    assert env.client.put("/api/binance/risk", json={"default_rr": "abc"}).status_code == 422


# ---------------------------------------------------------------- plan

def test_trade_plan_returns_scenarios_and_never_orders(env):
    r = env.client.post("/api/binance/trade-plan", json={"symbol": "ADATRY", "amount_try": 400})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["loss_try"] < 0 < body["plan"]["gain_try"]
    assert body["suggestion"]["source"] in ("llm", "kural")
    assert body["cap_try"] == pytest.approx(500.0)
    assert env.ex.buys == [] and env.ex.ocos == []


def test_trade_plan_manual_overrides_suggestion(env):
    r = env.client.post("/api/binance/trade-plan",
                        json={"symbol": "ADATRY", "amount_try": 400, "rr_mode": "manual", "sl_pct": 3, "rr": 1.5})
    body = r.json()
    assert body["mode"] == "manual" and body["plan"]["sl_pct"] == 3 and body["plan"]["rr"] == 1.5
    assert body["suggestion"]["rr"] != 1.5 or body["suggestion"]["sl_pct"] != 3


def test_trade_plan_defaults_amount_to_cap(env):
    r = env.client.post("/api/binance/trade-plan", json={"symbol": "ADATRY"})
    assert r.json()["amount_try"] == pytest.approx(500.0)


def test_trade_plan_flags_over_cap(env):
    r = env.client.post("/api/binance/trade-plan", json={"symbol": "ADATRY", "amount_try": 900})
    assert "limit_asildi" in r.json()["warnings"] and r.json()["warning_texts"]


def test_trade_plan_requires_symbol(env):
    assert env.client.post("/api/binance/trade-plan", json={}).status_code == 422


# ---------------------------------------------------------------- open-position

def test_open_position_happy_path(env):
    r = env.client.post("/api/binance/open-position", json=_open_body())
    assert r.status_code == 200
    body = r.json()
    assert body["protection"]["status"] == "placed" and "emir_ms" in body
    assert len(env.ex.buys) == 1 and len(env.ex.ocos) == 1
    assert env.st.logged                                    # denetim kaydı


def test_open_position_blocked_when_live_off(env):
    env.st.live = False
    r = env.client.post("/api/binance/open-position", json=_open_body())
    assert r.status_code == 403 and env.ex.buys == []


def test_open_position_requires_confirmation(env):
    r = env.client.post("/api/binance/open-position", json=_open_body(confirmation=""))
    assert r.status_code == 422 and env.ex.buys == []


def test_open_position_duplicate_id_buys_once(env):
    env.client.post("/api/binance/open-position", json=_open_body())
    r = env.client.post("/api/binance/open-position", json=_open_body())
    assert r.status_code == 200 and r.json()["idempotent_replay"] is True
    assert len(env.ex.buys) == 1


def test_open_position_over_cap_rejected(env):
    r = env.client.post("/api/binance/open-position", json=_open_body(amount_try=900.0))
    assert r.status_code == 422 and env.ex.buys == []


def test_open_position_ambiguous_returns_202(env):
    env.ex.buy_error = Amb("zaman asimi")
    r = env.client.post("/api/binance/open-position", json=_open_body())
    assert r.status_code == 202 and r.json()["status"] == "UNKNOWN"


def test_protect_retries_only_unprotected(env):
    env.client.post("/api/binance/open-position", json=_open_body())
    r = env.client.post("/api/binance/protect", json={"client_order_id": "cid-0000001"})
    assert r.status_code in (200, 409)
    assert len(env.ex.ocos) == 1                            # zaten korumalı: ikinci OCO yok


def test_protect_unknown_request_404(env):
    assert env.client.post("/api/binance/protect", json={"client_order_id": "cid-unknown1"}).status_code == 404


# ---------------------------------------------------------------- anahtarlar

def test_delete_keys_removes_user_keys(env):
    r = env.client.delete("/api/binance/keys")
    assert r.status_code == 200 and env.st.keys_deleted == [7]


def test_user_stream_start(env):
    r = env.client.post("/api/binance/user-stream/start")
    assert r.status_code == 200 and r.json()["ok"] is True
