"""Güvenli pozisyon açma: alım → gerçekleşen miktar → OCO. Sahte borsa; GERÇEK EMİR YOK."""
import asyncio
import math

import pytest

from app import database, open_position
from app.open_position import OrderError, build_plan, execute_open_position

RISK = {"max_position_pct": 50.0, "default_rr": 2.0}
FILTERS = {"step_size": 0.01, "tick_size": 0.01, "min_notional": 10.0, "min_qty": 0.01,
           "quote_asset": "TRY", "oco_enable": True, "status": "TRADING"}


class Ambiguous(Exception):
    pass


class FakeExchange:
    AmbiguousError = Ambiguous

    def __init__(self, free_try=1000.0, price=100.0, filters=FILTERS):
        self.free_try, self.px, self.filters_ = free_try, price, filters
        self.buy_calls, self.oco_calls = [], []
        self.buy_error = None
        self.oco_error = None
        self.detail_result = None            # None → tam dolum varsayılan
        self.detail_calls = 0

    async def symbol_to_underscore(self, symbol):
        s = symbol.upper().replace("_", "")
        return f"{s[:-3]}_TRY" if s.endswith("TRY") else f"{s}_TRY"

    async def filters(self, symbol_u):
        return dict(self.filters_) if self.filters_ else None

    async def free_balance(self, asset, force=False):
        return self.free_try if asset == "TRY" else 0.0

    async def price(self, symbol_u):
        return self.px

    async def buy(self, symbol_u, quote_qty, client_order_id):
        self.buy_calls.append((symbol_u, quote_qty, client_order_id))
        if self.buy_error:
            raise self.buy_error
        return {"order_id": "555", "symbol": symbol_u, "quote_qty": f"{quote_qty:.2f}", "client_order_id": client_order_id}

    async def order_detail(self, symbol_u, client_id):
        self.detail_calls += 1
        if self.detail_result is not None:
            return self.detail_result
        qty = math.floor(self.last_quote() / self.px * 0.999 * 100) / 100      # borsa adıma AŞAĞI yuvarlar
        return {"status": 2, "executedQty": str(qty), "executedQuoteQty": str(round(qty * self.px, 2))}

    def last_quote(self):
        return self.buy_calls[-1][1]

    async def oco(self, symbol_u, qty, tp_price, sl_price):
        self.oco_calls.append((symbol_u, qty, tp_price, sl_price))
        if self.oco_error:
            raise self.oco_error
        return {"order_list_id": "900"}


class FakeDB:
    """order_requests için bellek içi sahte (database.claim/finish/get yerine)."""
    def __init__(self):
        self.rows = {}

    async def claim(self, user_id, cid, symbol, request):
        key = (user_id, cid)
        if key in self.rows:
            return False
        self.rows[key] = {"status": "in_progress", "symbol": symbol, "result": {}, "created_at": 0.0}
        return True

    async def finish(self, user_id, cid, status, result):
        self.rows[(user_id, cid)].update(status=status, result=result)

    async def get(self, user_id, cid):
        return self.rows.get((user_id, cid))


@pytest.fixture
def fdb(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(database, "claim_order_request", d.claim)
    monkeypatch.setattr(database, "finish_order_request", d.finish)
    monkeypatch.setattr(database, "get_order_request", d.get)
    monkeypatch.setattr(open_position, "DETAIL_RETRY_SLEEP_SEC", 0.0)
    return d


def run(coro):
    return asyncio.run(coro)


def payload(**kw):
    base = {"symbol": "ADATRY", "amount_try": 400.0, "sl_pct": 2.0, "rr": 2.0, "client_order_id": "cid-0000001"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- plan

def test_plan_shows_cap_and_numbers():
    ex = FakeExchange(free_try=1000.0)
    out = run(build_plan(ex, symbol="ADATRY", amount_try=400.0, sl_pct=2.0, rr=2.0, risk=RISK))
    assert out["cap_try"] == pytest.approx(500.0)             # 1000 × %50
    assert out["plan"]["sl_price"] == pytest.approx(98.0)
    assert out["plan"]["tp_price"] == pytest.approx(104.0)
    assert out["warnings"] == []


def test_plan_warns_instead_of_raising_for_cap_and_balance():
    ex = FakeExchange(free_try=1000.0)
    out = run(build_plan(ex, symbol="ADATRY", amount_try=600.0, sl_pct=2.0, rr=2.0, risk=RISK))
    assert "limit_asildi" in out["warnings"]
    out = run(build_plan(ex, symbol="ADATRY", amount_try=2000.0, sl_pct=2.0, rr=2.0, risk=RISK))
    assert "bakiye_yetersiz" in out["warnings"]


def test_plan_unknown_symbol_raises_422():
    ex = FakeExchange(filters=None)
    with pytest.raises(OrderError) as e:
        run(build_plan(ex, symbol="XXXTRY", amount_try=100.0, sl_pct=2.0, rr=2.0, risk=RISK))
    assert e.value.status_code == 422


def test_plan_non_tradable_symbol_raises():
    ex = FakeExchange(filters={**FILTERS, "status": "BREAK"})
    with pytest.raises(OrderError):
        run(build_plan(ex, symbol="ADATRY", amount_try=100.0, sl_pct=2.0, rr=2.0, risk=RISK))


# ---------------------------------------------------------------- başarılı akış

def test_happy_path_buys_then_places_oco(fdb):
    ex = FakeExchange()
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert status == 200 and body["ok"] is True
    assert len(ex.buy_calls) == 1 and ex.buy_calls[0][1] == pytest.approx(400.0)
    assert len(ex.oco_calls) == 1
    sym, qty, tp, sl = ex.oco_calls[0]
    assert sym == "ADA_TRY" and qty == pytest.approx(3.99) and tp == pytest.approx(104.0) and sl == pytest.approx(98.0)
    assert body["protection"]["status"] == "placed"
    assert body["executed_qty"] == pytest.approx(3.99)
    assert fdb.rows[(7, "cid0000001")]["status"] == "done"


# ---------------------------------------------------------------- idempotency

def test_duplicate_client_order_id_does_not_buy_twice(fdb):
    ex = FakeExchange()
    run(execute_open_position(ex, 7, payload(), RISK))
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert len(ex.buy_calls) == 1                      # ikinci GERÇEK alım YOK
    assert status == 200 and body["idempotent_replay"] is True


def test_concurrent_duplicates_buy_once(fdb):
    ex = FakeExchange()

    async def both():
        return await asyncio.gather(execute_open_position(ex, 7, payload(), RISK),
                                    execute_open_position(ex, 7, payload(), RISK))
    results = run(both())
    assert len(ex.buy_calls) == 1
    assert sorted(r[0] for r in results) in ([200, 200], [200, 202])


def test_same_id_for_different_users_is_independent(fdb):
    ex = FakeExchange()
    run(execute_open_position(ex, 7, payload(), RISK))
    run(execute_open_position(ex, 8, payload(), RISK))
    assert len(ex.buy_calls) == 2


def test_invalid_client_order_id_rejected(fdb):
    with pytest.raises(OrderError) as e:
        run(execute_open_position(FakeExchange(), 7, payload(client_order_id="x"), RISK))
    assert e.value.status_code == 422


# ---------------------------------------------------------------- sınırlar ve doğrulama

def test_cap_exceeded_is_rejected_without_buying(fdb):
    ex = FakeExchange(free_try=1000.0)
    with pytest.raises(OrderError) as e:
        run(execute_open_position(ex, 7, payload(amount_try=600.0), RISK))
    assert e.value.status_code == 422 and "limit" in e.value.detail.lower()
    assert ex.buy_calls == []
    assert (7, "cid0000001") not in fdb.rows          # reddedilen istek kayıt/emir üretmez


def test_insufficient_balance_rejected(fdb):
    ex = FakeExchange(free_try=100.0)
    with pytest.raises(OrderError):
        run(execute_open_position(ex, 7, payload(amount_try=400.0), {"max_position_pct": 100.0, "default_rr": 2.0}))
    assert ex.buy_calls == []


def test_below_min_notional_rejected(fdb):
    ex = FakeExchange()
    with pytest.raises(OrderError):
        run(execute_open_position(ex, 7, payload(amount_try=5.0), RISK))
    assert ex.buy_calls == []


def test_oco_not_supported_rejected_before_buying(fdb):
    ex = FakeExchange(filters={**FILTERS, "oco_enable": False})
    with pytest.raises(OrderError):
        run(execute_open_position(ex, 7, payload(), RISK))
    assert ex.buy_calls == []


# ---------------------------------------------------------------- belirsiz / başarısız alım

def test_ambiguous_buy_returns_202_and_marks_unknown(fdb):
    ex = FakeExchange()
    ex.buy_error = Ambiguous("zaman aşımı")
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert status == 202 and body["status"] == "UNKNOWN" and body["client_order_id"] == "cid0000001"
    assert fdb.rows[(7, "cid0000001")]["status"] == "unknown"
    # aynı id ile yeniden deneme YENİ alım üretmez
    status2, _ = run(execute_open_position(ex, 7, payload(), RISK))
    assert len(ex.buy_calls) == 1 and status2 == 202


def test_definite_buy_failure_marks_failed_and_502(fdb):
    ex = FakeExchange()
    ex.buy_error = RuntimeError("Binance TR API hatası 3210: yetersiz bakiye")
    with pytest.raises(OrderError) as e:
        run(execute_open_position(ex, 7, payload(), RISK))
    assert e.value.status_code == 502
    assert fdb.rows[(7, "cid0000001")]["status"] == "failed"


# ---------------------------------------------------------------- koruma (OCO)

def test_oco_failure_reports_unprotected_and_protect_retries(fdb):
    ex = FakeExchange()
    ex.oco_error = RuntimeError("oco reddedildi")
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert status == 200 and body["protection"]["status"] == "failed"
    assert "oco reddedildi" in body["protection"]["error"]
    # tek dokunuşla yeniden dene
    ex.oco_error = None
    status, body = run(open_position.protect_position(ex, 7, "cid-0000001"))
    assert status == 200 and body["protection"]["status"] == "placed"
    assert len(ex.oco_calls) == 2 and len(ex.buy_calls) == 1


def test_partial_fill_protects_only_executed_quantity(fdb):
    ex = FakeExchange()
    ex.detail_result = {"status": 1, "executedQty": "1.5", "executedQuoteQty": "150.0"}
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert ex.oco_calls[0][1] == pytest.approx(1.5)
    assert body["executed_qty"] == pytest.approx(1.5) and body["avg_price"] == pytest.approx(100.0)


def test_no_executed_quantity_skips_oco_with_warning(fdb):
    ex = FakeExchange()
    ex.detail_result = {"status": 0, "executedQty": "0", "executedQuoteQty": "0"}
    status, body = run(execute_open_position(ex, 7, payload(), RISK))
    assert ex.oco_calls == [] and body["protection"]["status"] == "skipped"
    assert ex.detail_calls == open_position.DETAIL_TRIES        # sınırlı sayıda yoklama


def test_oco_prices_follow_actual_average_fill_price(fdb):
    ex = FakeExchange()
    ex.detail_result = {"status": 2, "executedQty": "3.9", "executedQuoteQty": "403.65"}   # ort. 103,5
    run(execute_open_position(ex, 7, payload(), RISK))
    _, qty, tp, sl = ex.oco_calls[0]
    assert sl == pytest.approx(103.5 * 0.98, abs=0.01) and tp == pytest.approx(103.5 * 1.04, abs=0.01)


def test_protect_requires_known_done_request(fdb):
    with pytest.raises(OrderError) as e:
        run(open_position.protect_position(FakeExchange(), 7, "cid-unknown1"))
    assert e.value.status_code == 404


def test_stored_client_id_is_the_one_sent_to_exchange(fdb):
    """2026-10-18: kayıt anahtarı borsaya giden (temizlenmiş: yalnız harf/rakam) kimlikle AYNI."""
    ex = FakeExchange()
    run(execute_open_position(ex, 7, payload(client_order_id="web-ab_12345"), RISK))
    assert ex.buy_calls[0][2] == "webab12345"
    assert (7, "webab12345") in fdb.rows and (7, "web-ab_12345") not in fdb.rows


def test_detail_poll_constants_have_single_source():
    from app import binance_tr_private as btp
    assert open_position.DETAIL_TRIES == btp.DETAIL_TRIES
    assert open_position.DETAIL_RETRY_SLEEP_SEC == btp.DETAIL_RETRY_SLEEP_SEC
