"""/api/binance/set-sl-tp: geçersiz fiyat ilişkisi mevcut korumayı İPTAL ETMEDEN reddedilir. Sahte borsa."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main

FILTERS = {"quote_asset": "TRY", "min_notional": 10.0, "step_size": 0.01, "min_qty": 0.01, "tick_size": 0.01, "oco_enable": True}


@pytest.fixture
def env():
    calls = {"cancel": [], "oco": [], "limit": [], "stop": []}

    async def price(self, symbol_u):
        return 100.0

    patches = [
        patch("app.main._require_user", MagicMock(return_value={"username": "ali", "role": "user"})),
        patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 7})),
        patch("app.main._real_sell_state_for", new=AsyncMock(return_value=(True, "panel"))),
        patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))),
        patch("app.main.get_symbol_filters", MagicMock(return_value=FILTERS)),
        patch("app.routers.binance_trade.BinanceExchange.price", price),
        patch("app.main.get_open_orders", MagicMock(return_value=[{"side": "SELL", "orderId": 5, "stopPrice": "90", "origQty": "5"}])),
        patch("app.main.cancel_order", MagicMock(side_effect=lambda *a: calls["cancel"].append(a))),
        patch("app.main.get_account_balance", MagicMock(return_value=[{"asset": "ADA", "free": "5", "locked": "0"}])),
        patch("app.main.place_oco_sell", MagicMock(side_effect=lambda *a, **k: calls["oco"].append(a) or {"order_list_id": "1"})),
        patch("app.main.place_limit_sell", MagicMock(side_effect=lambda *a, **k: calls["limit"].append(a) or {"order_id": "2"})),
        patch("app.main.place_stop_loss_sell", MagicMock(side_effect=lambda *a, **k: calls["stop"].append(a) or {"order_id": "3"})),
        patch("app.main.log_user_action", new=AsyncMock()),
        patch("app.main._session_identity", MagicMock(return_value=("ali", "user"))),
        patch("app.main._SL_TP_SETTLE_SLEEP_SEC", 0.0),
    ]
    for p in patches:
        p.start()
    yield calls
    for p in patches:
        p.stop()


def call(payload):
    base = {"asset": "ADA", "quantity": 5, "cancel_existing": True}
    base.update(payload)
    return asyncio.run(main.binance_set_sl_tp(base, request=MagicMock()))


def test_tp_below_last_price_rejected_and_existing_protection_kept(env):
    with pytest.raises(HTTPException) as e:
        call({"mode": "TP_ONLY", "tp_price": 99})
    assert e.value.status_code == 422 and "üstünde" in e.value.detail
    assert env["cancel"] == [] and env["limit"] == []


def test_sl_above_last_price_rejected_without_cancelling(env):
    with pytest.raises(HTTPException) as e:
        call({"mode": "SL_ONLY", "sl_price": 101})
    assert e.value.status_code == 422 and env["cancel"] == []


def test_oco_with_both_prices_valid(env):
    res = call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert res["ok"] and len(env["oco"]) == 1 and len(env["cancel"]) == 1


def test_oco_missing_one_price_rejected_before_cancel(env):
    with pytest.raises(HTTPException):
        call({"mode": "OCO", "tp_price": 110})
    assert env["cancel"] == []


# --- 2026-10-16 (basit arayüz): iptalden SONRAKİ her hata eski stop emrini geri kurmalı --------------------------------

def _balance(free, locked=0.0):
    return patch("app.main.get_account_balance", MagicMock(return_value=[{"asset": "ADA", "free": str(free), "locked": str(locked)}]))


def test_insufficient_qty_rejected_before_cancel_when_unreachable(env):
    """İstenen miktar iptal edilse bile ulaşılamayacaksa (free+locked) hiçbir emir iptal edilmez."""
    with _balance(5, 0):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95, "quantity": 50})
    assert e.value.status_code == 422 and "yetersiz" in e.value.detail
    assert env["cancel"] == [] and env["stop"] == [] and env["oco"] == []


def test_insufficient_free_after_cancel_restores_old_stop(env):
    """Ön kontrolü geçer (kilitli miktar dahil) ama iptal sonrası bakiye hâlâ yetersizse: eski stop GERİ KURULUR, 422 döner."""
    calls = []

    def balances(*a, **k):
        calls.append(k)
        if len(calls) == 1:
            return [{"asset": "ADA", "free": "0", "locked": "5"}]   # ön kontrol: locked iptalle serbest kalacak sanılır
        return [{"asset": "ADA", "free": "1", "locked": "0"}]       # iptal sonrası gerçek durum: yetersiz (her okumada)

    with patch("app.main.get_account_balance", MagicMock(side_effect=balances)):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95, "quantity": 5})
    assert e.value.status_code == 422 and "yetersiz" in e.value.detail
    assert "geri kuruldu" in e.value.detail
    assert len(env["cancel"]) == 1 and env["oco"] == []
    assert len(env["stop"]) == 1 and env["stop"][0][4] == 90.0  # eski stopPrice


def test_place_failure_after_cancel_restores_old_stop(env):
    with patch("app.main.place_oco_sell", MagicMock(side_effect=RuntimeError("borsa reddetti"))):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert e.value.status_code == 502 and "geri kuruldu" in e.value.detail
    assert len(env["cancel"]) == 1 and len(env["stop"]) == 1


def test_restore_failure_is_reported_as_unprotected(env):
    with patch("app.main.place_oco_sell", MagicMock(side_effect=RuntimeError("x"))), \
         patch("app.main.place_stop_loss_sell", MagicMock(side_effect=RuntimeError("geri kurulamadı"))):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert e.value.status_code == 502 and "KORUMASIZ" in e.value.detail


def test_balance_fetch_failure_before_cancel_keeps_protection(env):
    with patch("app.main.get_account_balance", MagicMock(side_effect=RuntimeError("ağ"))):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert e.value.status_code == 502 and env["cancel"] == []


def test_422_without_cancel_existing_does_not_touch_orders(env):
    with _balance(1, 4):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95, "cancel_existing": False, "quantity": 5})
    assert e.value.status_code == 422 and env["cancel"] == [] and env["stop"] == []


def test_success_path_cancel_then_place_unchanged(env):
    res = call({"mode": "SL_ONLY", "sl_price": 95})
    assert res["ok"] and res["mode"] == "SL_ONLY"
    assert len(env["cancel"]) == 1 and len(env["stop"]) == 1 and env["stop"][0][4] == 95.0


# --- 2026-10-20 (canlı WLD): iptal cevabı döndükten sonra borsa kilitli bakiyeyi hemen serbest göstermeyebiliyor ----------

def test_locked_balance_released_late_after_cancel_is_polled_not_rejected(env):
    """İptalden sonra ilk bakiye okuması hâlâ kilitli görünüyor; kısa yoklamayla serbest kalınca emir TAM miktarla kurulur.
    Canlıda: 3481 WLD'lik pozisyon, eski stop iptal edildi, ilk okuma 1790 boşta dedi → 422 + stop geri kuruldu."""
    calls = []

    def balances(*a, **k):
        calls.append(k)
        if len(calls) <= 2:   # 1: ön kontrol, 2: iptal sonrası ilk okuma (borsa henüz serbest bırakmadı)
            return [{"asset": "ADA", "free": "1", "locked": "4"}]
        return [{"asset": "ADA", "free": "5", "locked": "0"}]

    with patch("app.main.get_account_balance", MagicMock(side_effect=balances)):
        res = call({"mode": "OCO", "tp_price": 110, "sl_price": 95, "quantity": 5})
    assert res["ok"] and len(env["cancel"]) == 1 and len(env["oco"]) == 1
    assert env["oco"][0][3] == 5.0            # tam miktar
    assert env["stop"] == []                   # eski stop geri kurulmadı (gerek yok)
    assert all(c.get("force_refresh") for c in calls[2:])   # iptal sonrası okumalar önbelleği atlar


def test_cancel_failure_of_one_order_does_not_count_it_as_cancelled(env):
    """İlk iptal hata verirse o emir 'iptal edildi' sayılmaz (geri kurulup ÇİFT stop oluşmaz) ve sonraki emir yine iptal edilir."""
    orders = [{"side": "SELL", "orderId": 5, "stopPrice": "90", "origQty": "5"},
              {"side": "SELL", "orderId": 6, "stopPrice": "0", "price": "120", "origQty": "5"}]

    def cancel(_k, _s, order_id, *_a):
        if order_id == 5:
            raise RuntimeError("borsa: iptal reddedildi")
        env["cancel"].append(order_id)

    with patch("app.main.get_open_orders", MagicMock(return_value=orders)),             patch("app.main.cancel_order", MagicMock(side_effect=cancel)),             patch("app.main.place_oco_sell", MagicMock(side_effect=RuntimeError("x"))):
        with pytest.raises(HTTPException) as e:
            call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert env["cancel"] == [6]
    assert env["stop"] == []                   # 5 iptal edilemedi → geri kurulmaz; 6 stop değil
    assert "geri kurulamadı" in e.value.detail or "KORUMASIZ" in e.value.detail
