"""Binance TR kullanıcı işlem uçları: Risk Merkezi, işlem planı, güvenli pozisyon açma, koruma, anahtar yönetimi.

Mantık `app/open_position.py`, `app/trade_plan.py`, `app/rr_service.py`, `app/risk_settings.py` içindedir; burası HTTP
yapıştırıcısıdır. Oturum/anahtar/bayrak yardımcıları `main.py`'dedir ve TEMBEL içe aktarılır (döngüsel import yok);
testlerde `_main()` ve `_exchange_for()` sahtelenir.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from app import binance_tr_private as btp
from app import database
from app.open_position import BLOCKING_WARNINGS, OrderError, build_plan, execute_open_position, protect_position
from app.risk_settings import validate as validate_risk
from app.rr_service import suggest_rr

logger = logging.getLogger("scalper.binance_trade")
router = APIRouter()

_WARNING_LABELS = {**BLOCKING_WARNINGS}


def _main():
    from app import main
    return main


class BinanceExchange:
    """`binance_tr_private`'ı asyncio için saran borsa adaptörü (tek kullanıcının anahtarıyla)."""

    AmbiguousError = btp.BinanceTrAmbiguousOrderError

    def __init__(self, api_key: str, api_secret: str):
        self._k, self._s = api_key, api_secret

    async def symbol_to_underscore(self, symbol: str) -> str:
        await asyncio.to_thread(btp._load_symbol_list, self._k, self._s)
        return btp._to_underscore_symbol(symbol)

    async def filters(self, symbol_u: str):
        return await asyncio.to_thread(btp.get_symbol_filters, self._k, self._s, symbol_u)

    async def free_balance(self, asset: str, force: bool = False) -> float:
        rows = await asyncio.to_thread(btp.get_account_balance, self._k, self._s, force)
        row = next((b for b in rows if str(b.get("asset") or "").upper() == asset.upper()), None)
        return float(row.get("free", 0) or 0) if row else 0.0

    async def price(self, symbol_u: str):
        """Önce bellekteki ticker; yoksa public REST. (`btp._resolve_live_price` senkron sarmalı async `ticker_price`'ı
        beklemediği için bellek dışı coinlerde None dönüyordu.)"""
        try:
            from app.state import market
            ticker = market.get_ticker(symbol_u)
            if ticker and float(ticker.get("last_price") or 0) > 0:
                return float(ticker["last_price"])
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.binance_tr_public import ticker_price
            rows = await ticker_price([symbol_u])
            want = {symbol_u.upper(), symbol_u.upper().replace("_", "")}
            for row in rows if isinstance(rows, list) else []:
                if str(row.get("symbol") or "").upper() in want and float(row.get("price") or 0) > 0:
                    return float(row["price"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("canlı fiyat alınamadı (%s): %s", symbol_u, type(exc).__name__)
        return None

    async def buy(self, symbol_u: str, quote_qty: float, client_order_id: str) -> dict:
        return await asyncio.to_thread(btp.place_market_buy, self._k, self._s, symbol_u, quote_qty, None, client_order_id)

    async def order_detail(self, symbol_u: str, client_id: str) -> dict:
        return await asyncio.to_thread(btp.get_order_detail, self._k, self._s, symbol_u, client_id=client_id)

    async def oco(self, symbol_u: str, qty: float, tp_price: float, sl_price: float) -> dict:
        return await asyncio.to_thread(btp.place_oco_sell, self._k, self._s, symbol_u, qty, tp_price, sl_price)


def _exchange_for(api_key: str, api_secret: str):
    return BinanceExchange(api_key, api_secret)


async def _user(request: Request) -> dict:
    m = _main()
    principal = m._require_user(request)
    user = await database.get_user_by_username(str(principal.get("username") or "").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
    return user


async def _require_live(user: dict) -> None:
    ok, source = await _main()._real_sell_state_for(int(user["id"]))
    if not ok:
        if source == "panel":
            raise HTTPException(status_code=403, detail="Canlı işlem kapalı. Binance TR sayfasında 'Canlı işlem'i açın")
        raise HTTPException(status_code=403, detail="Gerçek işlemler sunucu tarafından kapatılmış")


def _to_http(exc: OrderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _warning_texts(warnings: list[str]) -> list[str]:
    return [_WARNING_LABELS.get(w, w) for w in warnings]


@router.get("/api/binance/risk")
async def get_risk(request: Request):
    user = await _user(request)
    return {"ok": True, **(await database.get_user_risk_settings(int(user["id"])))}


@router.put("/api/binance/risk")
async def put_risk(payload: dict, request: Request):
    user = await _user(request)
    try:
        values = validate_risk(payload or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    saved = await database.set_user_risk_settings(int(user["id"]), values)
    return {"ok": True, **saved}


@router.get("/api/binance/symbol-info")
async def symbol_info(symbol: str, request: Request):
    user = await _user(request)
    key, secret = await _main()._decrypt_binance_creds(request)
    ex = _exchange_for(key, secret)
    symbol_u = await ex.symbol_to_underscore(symbol)
    filters = await ex.filters(symbol_u)
    if not filters:
        raise HTTPException(status_code=404, detail="Sembol bulunamadı")
    return {"ok": True, "user_id": int(user["id"]), "symbol": symbol_u,
            "min_notional": filters.get("min_notional"), "step_size": filters.get("step_size"),
            "tick_size": filters.get("tick_size"), "min_qty": filters.get("min_qty"),
            "oco_enable": filters.get("oco_enable"), "quote_asset": filters.get("quote_asset")}


@router.post("/api/binance/trade-plan")
async def trade_plan(payload: dict, request: Request):
    """Emir GÖNDERMEZ: sembole özel RR önerisi + iyi/kötü senaryo TL sonucu."""
    user = await _user(request)
    m = _main()
    key, secret = await m._decrypt_binance_creds(request)
    ex = _exchange_for(key, secret)
    risk = await database.get_user_risk_settings(int(user["id"]))
    symbol = str(payload.get("symbol") or "").upper().strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="Sembol gerekli")

    snapshot = {}
    try:
        snap = await m.symbol_analysis(symbol, "5m")
        snapshot = snap if isinstance(snap, dict) else {}
    except Exception as exc:  # noqa: BLE001 — snapshot yoksa kural yedeği çalışır
        logger.debug("trade-plan snapshot alınamadı (%s): %s", symbol, type(exc).__name__)
    suggestion = await suggest_rr(symbol, snapshot, risk["default_rr"])

    manual = str(payload.get("rr_mode") or "auto").lower() == "manual"
    sl_pct = payload.get("sl_pct") if manual and payload.get("sl_pct") not in (None, "") else suggestion["sl_pct"]
    rr = payload.get("rr") if manual and payload.get("rr") not in (None, "") else suggestion["rr"]

    amount = payload.get("amount_try")
    if amount in (None, ""):
        try:
            free_try = float(await ex.free_balance("TRY", force=True))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=502, detail="Bakiye alınamadı, birazdan tekrar deneyin") from None
        pct = payload.get("amount_pct")
        try:
            frac = float(pct) / 100.0 if pct not in (None, "") else risk["max_position_pct"] / 100.0
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Geçersiz yüzde") from None
        amount = round(free_try * min(max(frac, 0.0), risk["max_position_pct"] / 100.0), 2)
    try:
        built = await build_plan(ex, symbol=symbol, amount_try=amount, sl_pct=sl_pct, rr=rr, risk=risk)
    except OrderError as exc:
        raise _to_http(exc) from None
    return {
        "ok": True, "symbol": built["symbol"], "price": built["price"], "amount_try": built["amount_try"],
        "free_try": built["free_try"], "cap_try": built["cap_try"], "max_position_pct": risk["max_position_pct"],
        "mode": "manual" if manual else "auto",
        "suggestion": {"sl_pct": suggestion["sl_pct"], "rr": suggestion["rr"], "source": suggestion["source"],
                       "rationale": suggestion.get("rationale", "")},
        "plan": {**built["plan"], "sl_pct": built["sl_pct"], "rr": built["rr"]},
        "warnings": built["warnings"], "warning_texts": _warning_texts(built["warnings"]),
        "disclaimer": "Bu bir öneridir, kâr garantisi değildir.",
    }


@router.post("/api/binance/open-position")
async def open_position_endpoint(payload: dict, request: Request):
    """Onaylı piyasa alımı + OCO. Aynı `client_order_id` ikinci gerçek emir üretmez."""
    started = time.perf_counter()
    user = await _user(request)
    m = _main()
    await _require_live(user)
    if str(payload.get("confirmation") or "").strip().upper() != "REAL_OPEN":
        raise HTTPException(status_code=422, detail="Onay gerekli")
    key, secret = await m._decrypt_binance_creds(request)
    ex = _exchange_for(key, secret)
    risk = await database.get_user_risk_settings(int(user["id"]))
    try:
        status, body = await execute_open_position(ex, int(user["id"]), payload, risk)
    except OrderError as exc:
        raise _to_http(exc) from None
    emir_ms = round((time.perf_counter() - started) * 1000)
    if status == 200 and not body.get("idempotent_replay"):
        try:
            m._invalidate_binance_cost_cache(int(user["id"]))
            actor, role = m._session_identity(request)
            await m.log_user_action(actor, role, "trade", "BINANCE_TR_OPEN_POSITION", target=body.get("symbol"),
                                    details={k: body.get(k) for k in ("symbol", "executed_qty", "avg_price", "amount_try", "protection")},
                                    request=request)
        except Exception as exc:  # noqa: BLE001 — yan işlem emri bozmamalı
            logger.warning("open-position yan işlemleri atlandı: %s", type(exc).__name__)
        logger.info("open-position tamam: emir_ms=%s symbol=%s", emir_ms, body.get("symbol"))
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={**body, "emir_ms": emir_ms})


@router.post("/api/binance/protect")
async def protect_endpoint(payload: dict, request: Request):
    """Koruma (OCO) kurulamamış pozisyon için yeniden dener; kurulmuşsa tekrar kurmaz."""
    user = await _user(request)
    await _require_live(user)
    key, secret = await _main()._decrypt_binance_creds(request)
    try:
        status, body = await protect_position(_exchange_for(key, secret), int(user["id"]), payload.get("client_order_id"))
    except OrderError as exc:
        raise _to_http(exc) from None
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=body)


@router.delete("/api/binance/keys")
async def delete_keys(request: Request):
    """Kullanıcının kayıtlı API anahtarlarını siler (canlı işlem bayrağı da gider) ve kullanıcı akışını durdurur."""
    user = await _user(request)
    deleted = await database.delete_user_binance_keys(int(user["id"]))
    try:
        from app import binance_tr_user_stream
        await binance_tr_user_stream.stop_user_stream(int(user["id"]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("kullanıcı akışı durdurulamadı: %s", type(exc).__name__)
    try:
        m = _main()
        actor, role = m._session_identity(request)
        await m.log_user_action(actor, role, "binance", "BINANCE_KEYS_DELETED", target="binance_tr",
                                details={"deleted": bool(deleted)}, request=request)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "deleted": bool(deleted)}


@router.post("/api/binance/user-stream/start")
async def start_user_stream(request: Request):
    """Dolum/bakiye olay akışını başlatır (Pozisyonlar sayfasına bağımlılığı kaldırır)."""
    user = await _user(request)
    m = _main()
    key, secret = await m._decrypt_binance_creds(request)
    state = await m._ensure_binance_user_stream(int(user["id"]), key, secret)
    return {"ok": True, "stream": state}
