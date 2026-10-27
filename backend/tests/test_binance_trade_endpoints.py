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

    async def real_state(uid, role=None):
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


# ---------------------------------------------------------------- Task 6: açık tp_pct + plan_key kaydı

from app import trade_plan  # noqa: E402


def test_compute_plan_explicit_tp_pct():
    p = trade_plan.compute_plan(100.0, 1000.0, 5.0, 1.0, FILTERS, 0.001, tp_pct=3.6)
    assert p["tp_price"] == pytest.approx(103.6)
    assert p["sl_price"] == pytest.approx(95.0)


def test_compute_plan_tp_pct_ignores_rr_even_when_missing():
    p = trade_plan.compute_plan(100.0, 1000.0, 5.0, None, FILTERS, 0.001, tp_pct=3.6)
    assert p["tp_price"] == pytest.approx(103.6)


def _plan_store(monkeypatch, plans, calls=None):
    async def get_plan(key):
        if calls is not None:
            calls.append(key)
        return plans.get(key)
    monkeypatch.setattr(database, "get_trade_plan", get_plan)


def test_open_position_tp_pct_drives_oco_and_rr_optional(env, monkeypatch):
    _plan_store(monkeypatch, {})
    body = _open_body(sl_pct=4.0, tp_pct=3.6)
    body.pop("rr")
    r = env.client.post("/api/binance/open-position", json=body)
    assert r.status_code == 200, r.text
    _, qty, tp, sl = env.ex.ocos[0]
    assert tp == pytest.approx(103.6) and sl == pytest.approx(96.0)       # ort. dolum 100
    assert r.json()["tp_pct"] == pytest.approx(3.6)
    assert r.json()["plan"]["tp_price"] == pytest.approx(103.6)


@pytest.mark.parametrize("bad", [0, -1, 50.01, 1000, "abc", "nan", "inf"])
def test_open_position_invalid_tp_pct_422_without_buying(env, monkeypatch, bad):
    _plan_store(monkeypatch, {})
    r = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=bad))
    assert r.status_code == 422 and env.ex.buys == []


@pytest.mark.parametrize("low", [0.1, 0.49])
def test_open_position_tp_pct_below_floor_422_before_claim(env, monkeypatch, low):
    _plan_store(monkeypatch, {})
    claims = []
    real_claim = database.claim_order_request

    async def spy_claim(*a, **k):
        claims.append(a)
        return await real_claim(*a, **k)
    monkeypatch.setattr(database, "claim_order_request", spy_claim)
    r = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=low))
    assert r.status_code == 422 and env.ex.buys == [] and claims == []
    assert "en az %0,50" in r.json()["detail"]


def test_tp_pct_floor_follows_commission(monkeypatch):
    from app import open_position
    from app.config import config
    monkeypatch.setattr(config, "effective_commission_pct", lambda: 0.001125)
    assert open_position.tp_pct_floor() == pytest.approx(0.5)            # 2×0.1125+0.1=0.325 < 0.5
    monkeypatch.setattr(config, "effective_commission_pct", lambda: 0.003)
    assert open_position.tp_pct_floor() == pytest.approx(0.7)            # 2×0.3+0.1
    assert open_position._tp_pct_or_none(0.7) == pytest.approx(0.7)
    with pytest.raises(open_position.OrderError) as exc:
        open_position._tp_pct_or_none(0.69)
    assert exc.value.status_code == 422


def test_open_position_tp_pct_at_floor_allowed(env, monkeypatch):
    _plan_store(monkeypatch, {})
    r = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=0.5))
    assert r.status_code == 200, r.text


def test_open_position_tp_pct_50_is_allowed(env, monkeypatch):
    _plan_store(monkeypatch, {})
    r = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=50))
    assert r.status_code == 200 and env.ex.ocos[0][2] == pytest.approx(150.0)


def test_open_position_without_tp_pct_unchanged(env, monkeypatch):
    calls = []
    _plan_store(monkeypatch, {}, calls)
    r = env.client.post("/api/binance/open-position", json=_open_body())
    body = r.json()
    assert r.status_code == 200 and env.ex.ocos[0][2] == pytest.approx(104.0)   # sl 2 × rr 2
    for k in ("tp_pct", "plan_key", "exit_at", "grace_minutes"):
        assert k not in body
    assert calls == []                                                  # plan_key yok → plan okunmaz


def test_open_position_without_tp_pct_still_requires_rr(env, monkeypatch):
    _plan_store(monkeypatch, {})
    body = _open_body()
    body.pop("rr")
    r = env.client.post("/api/binance/open-position", json=body)
    assert r.status_code == 422 and env.ex.buys == []


def test_place_order_records_plan_key_and_exit_at(env, monkeypatch):
    import time
    _plan_store(monkeypatch, {"k1": {"created_at": 1000.0, "exit_at": 1000.0 + 5400, "grace_minutes": 15,
                                     "stop_pct": 4.0, "target_gross_pct": 3.6}})
    claimed = []
    orig_claim = database.claim_order_request

    async def claim(uid, cid, symbol, request):
        claimed.append(request)
        return await orig_claim(uid, cid, symbol, request)
    monkeypatch.setattr(database, "claim_order_request", claim)

    before = time.time()
    r = env.client.post("/api/binance/open-position",
                        json=_open_body(sl_pct=4.0, tp_pct=3.6, plan_key="k1", exit_at=1, grace_minutes=999))
    after = time.time()
    body = r.json()
    assert r.status_code == 200
    assert body["plan_key"] == "k1" and body["exit_at"] > time.time()
    assert before + 5400 <= body["exit_at"] <= after + 5400              # dolum anı + plan süresi (istemci exit_at yok sayılır)
    assert body["grace_minutes"] == 15
    stored = env.st.rows[(7, "cid0000001")]["result"]
    assert stored["plan_key"] == "k1" and stored["exit_at"] == body["exit_at"] and stored["grace_minutes"] == 15
    assert stored["symbol"] == "ADA_TRY" and stored["executed_qty"] > 0 and stored["avg_price"] > 0
    assert claimed[0]["plan_key"] == "k1" and claimed[0]["tp_pct"] == pytest.approx(3.6)


def test_plan_key_not_found_records_key_without_exit_at(env, monkeypatch):
    _plan_store(monkeypatch, {})
    r = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=3.0, plan_key="yok"))
    body = r.json()
    assert r.status_code == 200 and body["plan_key"] == "yok"
    assert "exit_at" not in body and "grace_minutes" not in body


def test_plan_without_exit_at_records_grace_only(env, monkeypatch):
    _plan_store(monkeypatch, {"k2": {"created_at": 1000.0, "exit_at": None, "grace_minutes": None}})
    r = env.client.post("/api/binance/open-position", json=_open_body(plan_key="k2"))
    body = r.json()
    assert r.status_code == 200 and body["plan_key"] == "k2" and "exit_at" not in body
    assert body["grace_minutes"] is None


def test_plan_lookup_error_does_not_block_order(env, monkeypatch):
    async def boom(key):
        raise RuntimeError("db")
    monkeypatch.setattr(database, "get_trade_plan", boom)
    r = env.client.post("/api/binance/open-position", json=_open_body(plan_key="k1"))
    assert r.status_code == 200 and r.json()["plan_key"] == "k1" and "exit_at" not in r.json()


def test_replay_keeps_plan_fields_and_buys_once(env, monkeypatch):
    _plan_store(monkeypatch, {"k1": {"created_at": 0.0, "exit_at": 600.0, "grace_minutes": 5}})
    first = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=3.6, plan_key="k1")).json()
    again = env.client.post("/api/binance/open-position", json=_open_body(tp_pct=3.6, plan_key="k1")).json()
    assert again["idempotent_replay"] is True and again["exit_at"] == first["exit_at"]
    assert len(env.ex.buys) == 1


def test_protect_retry_uses_stored_tp_pct(env, monkeypatch):
    _plan_store(monkeypatch, {})
    orig = env.ex.oco
    state = {"fail": True}

    async def flaky(su, qty, tp, sl):
        if state["fail"]:
            raise RuntimeError("oco down")
        return await orig(su, qty, tp, sl)
    monkeypatch.setattr(env.ex, "oco", flaky)
    r = env.client.post("/api/binance/open-position", json=_open_body(sl_pct=4.0, tp_pct=3.6))
    assert r.json()["protection"]["status"] == "failed"
    state["fail"] = False
    r = env.client.post("/api/binance/protect", json={"client_order_id": "cid-0000001"})
    assert r.status_code == 200 and env.ex.ocos[-1][2] == pytest.approx(103.6)


def test_trade_plan_preview_accepts_tp_pct(env):
    r = env.client.post("/api/binance/trade-plan", json={"symbol": "ADATRY", "amount_try": 400, "rr_mode": "manual",
                                                          "sl_pct": 4, "tp_pct": 3.6})
    assert r.status_code == 200
    assert r.json()["plan"]["tp_price"] == pytest.approx(103.6) and r.json()["plan"]["tp_pct"] == pytest.approx(3.6)
    assert env.ex.buys == []


def test_trade_plan_preview_invalid_tp_pct_422(env):
    r = env.client.post("/api/binance/trade-plan", json={"symbol": "ADATRY", "amount_try": 400, "tp_pct": 60})
    assert r.status_code == 422
