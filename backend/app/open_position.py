"""Güvenli pozisyon açma: plan → idempotent piyasa alımı → gerçekleşen miktar → OCO (SL+TP).

Bu modül HTTP'den bağımsızdır; borsa `exchange` adaptörü enjekte edilir (üretimde `binance_tr_private`'i saran adaptör,
testlerde sahte). Böylece tüm akış GERÇEK EMİR GÖNDERMEDEN test edilir.

Güvenlik ilkeleri (docs/superpowers/specs/2026-10-16-binance-tr-kullanici-ticaret-design.md):
  * Tutar sınırı (serbest TRY × max_position_pct) SUNUCUDA zorlanır.
  * `client_order_id` ile idempotency: aynı id ikinci gerçek emir üretmez; belirsiz sonuç 202 UNKNOWN döner.
  * Plan (SL/TP) sunucuda yeniden hesaplanır; istemci yalnız sl_pct ve rr verir (kenetlenir).
  * OCO, gerçekleşen (adım yuvarlı) miktarla ve gerçekleşen ortalama fiyata göre kurulur; başarısızsa açıkça bildirilir.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any

from app import database
# Yoklama sabitleri TEK KAYNAK: binance_tr_private (MARKET SELL dolum doğrulaması da aynısını kullanır).
from app.binance_tr_private import DETAIL_RETRY_SLEEP_SEC, DETAIL_TRIES
from app.order_requests import DONE, FAILED, IN_PROGRESS, UNKNOWN, normalize_client_order_id
from app.trade_plan import RR_MAX, RR_MIN, SL_PCT_MAX, SL_PCT_MIN, compute_plan, round_down, round_to_tick

logger = logging.getLogger("scalper.open_position")

DEFAULT_TAKER_FEE_RATE = 0.001          # tahmini; Binance TR komisyon alanları doğrulanamadığı için sabit/ortam ayarı
BLOCKING_WARNINGS = {
    "min_tutar_alti": "Tutar bu coin için en düşük emir tutarının altında",
    "min_miktar_alti": "Alınacak miktar en düşük miktarın altında",
    "oco_desteklenmiyor": "Bu coin için otomatik zarar durdur/kâr al emri desteklenmiyor",
    "sl_fiyata_cok_yakin": "Zarar durdur fiyatı güncel fiyata çok yakın; daha geniş bir mesafe seçin",
    "tp_fiyata_cok_yakin": "Kâr al fiyatı güncel fiyata çok yakın; daha yüksek bir RR seçin",
    "limit_asildi": "Tutar Risk Merkezi'ndeki pozisyon limitini aşıyor",
    "bakiye_yetersiz": "Serbest TRY bakiyesi yetersiz",
}


class OrderError(Exception):
    """HTTP'ye çevrilecek iş kuralı hatası."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _fee_rate() -> float:
    try:
        value = float(os.getenv("BINANCE_TR_TAKER_FEE_RATE", DEFAULT_TAKER_FEE_RATE))
    except ValueError:
        return DEFAULT_TAKER_FEE_RATE
    return value if 0 <= value <= 0.05 else DEFAULT_TAKER_FEE_RATE


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _to_positive_float(name: str, raw: Any) -> float:
    try:
        value = float(str(raw).replace(",", ".")) if isinstance(raw, str) else float(raw)
    except (TypeError, ValueError):
        raise OrderError(422, f"Geçersiz {name}") from None
    if not (math.isfinite(value) and value > 0):
        raise OrderError(422, f"Geçersiz {name}")
    return value


async def build_plan(exchange, *, symbol: str, amount_try: float, sl_pct: float, rr: float, risk: dict,
                     fee_rate: float | None = None) -> dict:
    """Plan hesabı (emir GÖNDERMEZ). Limit/bakiye aşımı uyarı olarak döner; geçersiz sembol/fiyat OrderError."""
    amount = _to_positive_float("tutar", amount_try)
    sl = _clamp(_to_positive_float("zarar durdur yüzdesi", sl_pct), SL_PCT_MIN, SL_PCT_MAX)
    ratio = _clamp(_to_positive_float("RR", rr), RR_MIN, RR_MAX)
    symbol_u = await exchange.symbol_to_underscore(symbol)
    filters = await exchange.filters(symbol_u)
    if not filters:
        raise OrderError(422, "Bu sembol Binance TR'de bulunamadı")
    if str(filters.get("quote_asset") or "").upper() != "TRY":
        raise OrderError(422, "Yalnız TRY çiftleri destekleniyor")
    if str(filters.get("status") or "TRADING").upper() != "TRADING":
        raise OrderError(422, "Bu sembolde şu an işlem yapılamıyor")
    price = await exchange.price(symbol_u)
    if not price or price <= 0:
        raise OrderError(503, "Güncel fiyat alınamadı, birazdan tekrar deneyin")
    free_try = float(await exchange.free_balance("TRY", force=True))
    cap_try = free_try * float(risk.get("max_position_pct", 20.0)) / 100.0
    try:
        plan = compute_plan(price, amount, sl, ratio, filters, fee_rate if fee_rate is not None else _fee_rate())
    except ValueError as exc:
        raise OrderError(422, str(exc)) from None
    warnings = list(plan["warnings"])
    if amount > cap_try + 1e-9:
        warnings.append("limit_asildi")
    if amount > free_try + 1e-9:
        warnings.append("bakiye_yetersiz")
    return {"symbol": symbol_u, "price": price, "free_try": free_try, "cap_try": cap_try, "amount_try": amount,
            "plan": plan, "warnings": warnings, "filters": filters, "sl_pct": sl, "rr": ratio}


def _first_blocking(warnings: list[str]) -> str | None:
    for key in BLOCKING_WARNINGS:
        if key in warnings:
            return BLOCKING_WARNINGS[key]
    return None


async def _fetch_fill(exchange, symbol_u: str, client_id: str, buy_result: dict, fallback_price: float) -> tuple[float, float | None]:
    """(gerçekleşen miktar, ortalama fiyat). Emir detayını sınırlı sayıda yoklar; bulunamazsa alım yanıtına düşer."""
    for attempt in range(DETAIL_TRIES):
        try:
            detail = await exchange.order_detail(symbol_u, client_id)
            executed = float(detail.get("executedQty") or 0)
            if executed > 0:
                quote = float(detail.get("executedQuoteQty") or detail.get("cummulativeQuoteQty") or 0)
                return executed, (quote / executed if quote > 0 else fallback_price)
        except Exception as exc:  # noqa: BLE001 — yoklama hatası emri bozmamalı
            logger.debug("emir detayı okunamadı (%s): %s", client_id, exc)
        if attempt < DETAIL_TRIES - 1 and DETAIL_RETRY_SLEEP_SEC > 0:
            await asyncio.sleep(DETAIL_RETRY_SLEEP_SEC)
    try:
        executed = float(buy_result.get("executed_qty") or 0)
        if executed > 0:
            return executed, float(buy_result.get("avg_price") or fallback_price)
    except (TypeError, ValueError):
        pass
    return 0.0, None


async def _protect(exchange, symbol_u: str, qty: float, avg_price: float | None, sl_pct: float, rr: float,
                   filters: dict) -> dict:
    """OCO (TP + SL) kurar. Dönüş: {status: placed|failed|skipped, ...}. Asla istisna fırlatmaz."""
    step = float(filters.get("step_size") or 0)
    tick = float(filters.get("tick_size") or 0)
    min_qty = float(filters.get("min_qty") or 0)
    use_qty = round_down(qty, step)
    if not avg_price or avg_price <= 0 or use_qty <= 0 or (min_qty and use_qty < min_qty):
        return {"status": "skipped", "reason": "Gerçekleşen miktar belirlenemedi veya çok küçük; koruma emri kurulmadı"}
    sl_price = round_to_tick(avg_price * (1 - sl_pct / 100.0), tick)
    tp_price = round_to_tick(avg_price * (1 + sl_pct * rr / 100.0), tick)
    try:
        res = await exchange.oco(symbol_u, use_qty, tp_price, sl_price)
    except Exception as exc:  # noqa: BLE001
        logger.error("OCO kurulamadı (%s, qty=%s): %s", symbol_u, use_qty, exc)
        return {"status": "failed", "error": str(exc), "qty": use_qty, "sl_price": sl_price, "tp_price": tp_price}
    return {"status": "placed", "order_list_id": (res or {}).get("order_list_id"), "qty": use_qty,
            "sl_price": sl_price, "tp_price": tp_price}


def _replay(existing: dict, cid: str) -> tuple[int, dict]:
    status = existing.get("status")
    result = existing.get("result") or {}
    if status == DONE:
        return 200, {**result, "idempotent_replay": True}
    if status == FAILED:
        raise OrderError(409, "Bu emir kimliğiyle gönderilen emir reddedilmişti; yeni bir emir için yeni kimlik kullanın")
    label = "UNKNOWN" if status == UNKNOWN else "IN_PROGRESS"
    return 202, {"ok": False, "status": label, "client_order_id": cid, "idempotent_replay": True,
                 "detail": "Emir sonucu henüz netleşmedi; Açık emirler ve geçmişi kontrol edin, tekrar göndermeyin"}


async def execute_open_position(exchange, user_id: int, payload: dict, risk: dict, *,
                                fee_rate: float | None = None) -> tuple[int, dict]:
    """Piyasa alımı + OCO. Döner: (http_status, gövde). İş kuralı ihlali OrderError ile yükselir."""
    try:
        cid = normalize_client_order_id(payload.get("client_order_id"))
    except ValueError as exc:
        raise OrderError(422, str(exc)) from None

    existing = await database.get_order_request(user_id, cid)
    if existing:
        return _replay(existing, cid)

    built = await build_plan(exchange, symbol=str(payload.get("symbol") or ""), amount_try=payload.get("amount_try"),
                             sl_pct=payload.get("sl_pct"), rr=payload.get("rr"), risk=risk, fee_rate=fee_rate)
    blocked = _first_blocking(built["warnings"])
    if blocked:
        raise OrderError(422, blocked)

    symbol_u, amount, plan = built["symbol"], built["amount_try"], built["plan"]
    if not await database.claim_order_request(user_id, cid, symbol_u, {"amount_try": amount, "sl_pct": built["sl_pct"], "rr": built["rr"]}):
        existing = await database.get_order_request(user_id, cid)
        return _replay(existing or {"status": IN_PROGRESS}, cid)

    try:
        buy_result = await exchange.buy(symbol_u, amount, cid)
    except exchange.AmbiguousError as exc:
        await database.finish_order_request(user_id, cid, UNKNOWN, {"error": str(exc)})
        return 202, {"ok": False, "status": "UNKNOWN", "client_order_id": cid,
                     "detail": "Emir sonucu belirsiz (zaman aşımı). Tekrar göndermeyin; Açık emirler ve geçmişi kontrol edin"}
    except Exception as exc:  # noqa: BLE001
        await database.finish_order_request(user_id, cid, FAILED, {"error": str(exc)})
        raise OrderError(502, f"Alım emri gönderilemedi: {exc}") from None

    executed, avg_price = await _fetch_fill(exchange, symbol_u, cid, buy_result or {}, built["price"])
    protection = await _protect(exchange, symbol_u, executed, avg_price, built["sl_pct"], built["rr"], built["filters"])
    body = {
        "ok": True, "symbol": symbol_u, "client_order_id": cid, "order_id": (buy_result or {}).get("order_id"),
        "executed_qty": executed, "avg_price": avg_price, "amount_try": amount,
        "sl_pct": built["sl_pct"], "rr": built["rr"],
        "plan": {"sl_price": plan["sl_price"], "tp_price": plan["tp_price"],
                 "loss_try": plan["loss_try"], "gain_try": plan["gain_try"]},
        "protection": protection,
    }
    await database.finish_order_request(user_id, cid, DONE, body)
    return 200, body


async def protect_position(exchange, user_id: int, client_order_id: str) -> tuple[int, dict]:
    """Koruma emri kurulamamış (veya atlanmış) pozisyon için OCO'yu yeniden dener. Başarıyla kurulmuşsa tekrar kurmaz."""
    try:
        cid = normalize_client_order_id(client_order_id)
    except ValueError as exc:
        raise OrderError(422, str(exc)) from None
    row = await database.get_order_request(user_id, cid)
    if not row or row.get("status") != DONE:
        raise OrderError(404, "Bu kimlikle tamamlanmış bir pozisyon bulunamadı")
    result = dict(row.get("result") or {})
    if (result.get("protection") or {}).get("status") == "placed":
        return 200, {**result, "idempotent_replay": True}
    symbol_u = str(result.get("symbol") or row.get("symbol") or "")
    filters = await exchange.filters(symbol_u) or {}
    protection = await _protect(exchange, symbol_u, float(result.get("executed_qty") or 0),
                                result.get("avg_price"), float(result.get("sl_pct") or 2.0),
                                float(result.get("rr") or 2.0), filters)
    result["protection"] = protection
    await database.finish_order_request(user_id, cid, DONE, result)
    return 200, result
