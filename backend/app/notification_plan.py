"""Bildirim işlem planı: güvenli tutar, hedef, süre, çıkış zamanı, stop (2026-10-27)."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app import binance_tr_public, signal_eta
from app.config import config
from app.trade_size import gross_target_pct, max_safe_amount, parse_levels

logger = logging.getLogger(__name__)

TARGET_NET_PCT = 3.0
STOP_MIN_PCT = 2.0
STOP_MAX_PCT = 10.0
UNREALISTIC_GROSS_PCT = 8.0
BUILD_TIMEOUT_SEC = 2.0
SAVE_TIMEOUT_SEC = 1.0
_TZ = ZoneInfo("Europe/Istanbul")


def compose_plan(*, symbol, bucket, price, signal_target_pct, book, quote_volume_try, stats,
                 fee_frac, now, profile=None) -> dict:
    price = float(price)
    asks = parse_levels(book.get("asks") or [])
    bids = parse_levels(book.get("bids") or [])
    safe = max_safe_amount(asks, bids, quote_volume_try)
    book_gross = gross_target_pct(TARGET_NET_PCT, safe["entry_slip_pct"], safe["exit_slip_pct"], fee_frac)
    gross = book_gross
    sig = float(signal_target_pct or 0.0)
    if sig > book_gross:
        # sinyal hedefi kazanır: metin "net %3" değil BRÜT hedefi gösterir (target_source="signal")
        profile_exit = bool(profile)
        gross = sig
        target_source = "signal"
    else:
        profile_exit = False
        target_source = "book"
    amount = float(safe["amount_try"])
    warnings: list[str] = []

    eta = exit_at = grace = stop_pct = stop_price = hit_rate = sample_n = None
    if stats:
        hit_rate, sample_n = stats.get("hit_rate"), stats.get("n")
        eta = stats.get("p50_min")
        p75 = stats.get("p75_min")
        if p75 is not None:
            exit_at = now + float(p75) * 60
            grace = float(p75)
        mae = stats.get("mae_p80_pct")
        if mae is not None:
            stop_pct = min(max(float(mae), STOP_MIN_PCT), STOP_MAX_PCT)
    if profile_exit:
        stop_pct = float(profile["stop_loss_pct"])
        exit_at = now + float(profile["max_hold_minutes"]) * 60
        grace = 0
    if stop_pct is not None:
        stop_price = price * (1 - stop_pct / 100)
    if not stats or (not profile_exit and (exit_at is None or stop_pct is None)):
        warnings.append("veri_yetersiz")
    # gerçekçilik DEFTERDEN türeyen brüt hedefe bakar (sinyal hedefi geçersiz kılmadan önce)
    if book_gross > UNREALISTIC_GROSS_PCT or amount < float(config.MIN_PARTIAL_ORDER_TRY):
        warnings.append("hedef_gercekci_degil")

    return {
        "symbol": symbol, "bucket": bucket, "entry_ref_price": price,
        "max_amount_try": amount, "max_amount_binding": safe["binding"],
        "target_net_pct": TARGET_NET_PCT, "target_gross_pct": gross, "target_source": target_source,
        "target_price": price * (1 + gross / 100),
        "stop_pct": stop_pct, "stop_price": stop_price,
        "eta_minutes": eta, "exit_at": exit_at, "grace_minutes": grace,
        "hit_rate": hit_rate, "sample_n": sample_n,
        "profile_exit": profile_exit, "warnings": warnings, "created_at": now,
    }


async def _build(symbol, bucket, price, signal_target_pct, profile, now) -> dict:
    book = await binance_tr_public.depth(symbol, limit=100)
    rows = await binance_tr_public.ticker_24h([symbol])
    qv = float((rows[0] or {}).get("quoteVolume") or 0) if rows else 0.0
    fee = float(config.effective_commission_pct())  # bacak başı KESİR (0.001125)
    # brüt hedef istatistik eşiği için gerekli: önce stats'siz kaba hesap
    base = compose_plan(symbol=symbol, bucket=bucket, price=price, signal_target_pct=signal_target_pct,
                        book=book, quote_volume_try=qv, stats=None, fee_frac=fee, now=now, profile=profile)
    stats = await signal_eta.get_stats(bucket, base["target_gross_pct"])
    return compose_plan(symbol=symbol, bucket=bucket, price=price, signal_target_pct=signal_target_pct,
                        book=book, quote_volume_try=qv, stats=stats, fee_frac=fee, now=now, profile=profile)


async def build_plan(symbol, bucket, price, signal_target_pct, profile=None, now=None) -> dict | None:
    now = float(now if now is not None else time.time())
    try:
        return await asyncio.wait_for(
            _build(symbol, bucket, price, signal_target_pct, profile, now), BUILD_TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 — her hata (zaman aşımı dahil) → None
        logger.warning("notification_plan: %s plan kurulamadı: %r", symbol, exc)
        return None


def exit_advice(plan: dict, entry_price: float, last_price: float, now: float, fee_frac: float) -> str | None:
    exit_at = plan.get("exit_at")
    if exit_at is None or now < float(exit_at):
        return None
    grace = float(plan.get("grace_minutes") or 0)
    if now >= float(exit_at) + grace * 60:
        return "cik"
    net = (float(last_price) * (1 - fee_frac)) / (float(entry_price) * (1 + fee_frac)) - 1.0
    return "cik" if net >= 0 else "bekle_stop"


def _fmt_price(x: float) -> str:
    x = float(x)
    if x == 0:
        return "0"
    decimals = max(3 - math.floor(math.log10(abs(x))), 0)
    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _fmt_amount(x: float) -> str:
    return f"{int(float(x) // 1000 * 1000):,}".replace(",", ".") + " TL"


def _fmt_eta(minutes: float) -> str:
    m = int(round(float(minutes)))
    return f"~{m} dk" if m < 60 else f"~{m // 60} sa {m % 60} dk"


def plan_shows_gross(plan: dict) -> bool:
    """Hedef etiketi brüt mü? Profil çıkışı ya da sinyal hedefi defter hedefini geçtiyse (target_source="signal")."""
    return bool(plan.get("profile_exit")) or plan.get("target_source") == "signal"


def plan_text(plan: dict) -> str:
    warnings = plan.get("warnings") or []
    if plan_shows_gross(plan):
        tag = f"(+%{plan['target_gross_pct']:g} brüt)"
    else:
        tag = f"(+%{plan['target_net_pct']:g} net)"
    parts = [f"Maks: {_fmt_amount(plan['max_amount_try'])}",
             f"Hedef {_fmt_price(plan['target_price'])} {tag}"]
    lacking = "veri_yetersiz" in warnings
    if lacking:
        parts.append("Süre: veri yetersiz")
    elif plan.get("eta_minutes") is not None:
        eta = _fmt_eta(plan["eta_minutes"])
        if plan.get("hit_rate") is not None:
            eta += f" (geçmişte %{round(float(plan['hit_rate']) * 100)})"
        parts.append(eta)
    # Profil çıkışında istatistik yoksa yalnız SÜRE bilinmez; profilin çıkış saati / stop'u
    # (alım penceresi ve hatırlatıcının kullandığı) yine gösterilir. Profilsiz plan: eskisi gibi gizli.
    if not lacking or plan.get("profile_exit"):
        if plan.get("exit_at") is not None:
            ex = datetime.fromtimestamp(float(plan["exit_at"]), _TZ)
            cr = datetime.fromtimestamp(float(plan.get("created_at") or time.time()), _TZ)
            prefix = "" if ex.date() == cr.date() else ex.strftime("%d.%m ")
            parts.append(f"Çıkış {prefix}{ex.strftime('%H:%M')}'e kadar")
        if plan.get("stop_price") is not None:
            parts.append(f"Stop {_fmt_price(plan['stop_price'])}")
    text = " | ".join(parts)
    if "hedef_gercekci_degil" in warnings:
        text = f"⚠ %{plan['target_net_pct']:g} net bu defterde zor · " + text
    return text


def plan_key_for(notif: dict) -> str:
    key = notif.get("notification_key")
    if key:
        return str(key)
    return f"{notif.get('tag')}-{int(float(notif.get('detected_at') or 0))}"


async def attach_plan(notif: dict, bucket: str, profile: dict | None = None, *,
                      stored: dict | None = None) -> dict:
    """Planı kurar, mesaja ekler, anahtarla dondurur. Bildirim yoluna ASLA hata sızdırmaz.

    `stored` (aynı anahtarla önceden dondurulmuş plan) verilirse defter/ticker REST çağrısı YAPILMAZ.
    `plan_key` yalnız plan varsa (saklı ya da kurulan) dolar; aksi halde None (var olmayan plana işaret etmez).
    """
    key = plan_key_for(notif)
    notif["plan_key"] = None
    notif["trade_plan"] = None
    try:
        plan = stored if isinstance(stored, dict) else None
        if plan is None:
            plan = await build_plan(notif.get("symbol"), bucket, notif.get("price"),
                                    notif.get("target_pct"), profile=profile)
            if plan is None:
                return notif
            try:
                from app import database
                plan = await asyncio.wait_for(
                    database.save_trade_plan(key, str(notif.get("symbol")), bucket, plan),
                    SAVE_TIMEOUT_SEC) or plan
            except Exception as exc:  # noqa: BLE001 (zaman aşımı dahil)
                logger.warning("notification_plan: plan kaydedilemedi (%s): %r", key, exc)
        notif["plan_key"] = key
        notif["trade_plan"] = plan
        notif["message"] = f"{notif.get('message', '')} | {plan_text(plan)}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification_plan: attach_plan hata: %r", exc)
    return notif


async def attach_plans(notifs: list[dict], bucket: str) -> None:
    """Toplu ekleme. GÜNCELLENEN bildirimler (`updated`) için saklı planlar TEK sorguyla okunur;
    saklı planı olan bildirimde build_plan (defter + ticker REST) çağrılmaz. Asla fırlatmaz."""
    stored: dict[str, dict] = {}
    upd_keys = [plan_key_for(n) for n in notifs if n.get("updated")]
    if upd_keys:
        try:
            from app import database
            stored = await asyncio.wait_for(database.get_trade_plans(upd_keys), SAVE_TIMEOUT_SEC) or {}
        except Exception as exc:  # noqa: BLE001 (zaman aşımı dahil) → plan yeniden kurulur, ilk yazan yine kazanır
            logger.warning("notification_plan: saklı planlar okunamadı: %r", exc)
            stored = {}
    await asyncio.gather(*(
        attach_plan(n, bucket, stored=stored.get(plan_key_for(n)) if n.get("updated") else None)
        for n in notifs))


def radar_row_plan_key(row: dict) -> str | None:
    """DB'deki radar bildirim satırı için attach anındaki anahtar (tag=`monitoring-{sym}`, `{tag}-{int(detected_at)}`)."""
    sym, ts = row.get("symbol"), row.get("detected_at")
    if not sym or ts is None:
        return None
    try:
        return f"monitoring-{sym}-{int(float(ts))}"
    except (TypeError, ValueError):
        return None


def ma_buy_row_plan_key(row: dict) -> str | None:
    """MA BUY sinyal satırı için bildirim anahtarı (`ma_buy_notify.build_notification` ile aynı)."""
    sym, tf, bar = row.get("symbol"), row.get("timeframe") or "5m", row.get("bar_open_ms")
    if not sym or bar is None:
        return None
    try:
        return f"ma-{tf}-{str(sym).upper()}-{int(bar)}"
    except (TypeError, ValueError):
        return None


async def enrich_rows_with_plans(rows: list[dict], key_fn) -> None:
    """Satırlara `plan_key` ve `trade_plan` ekler (TEK toplu sorgu). Asla fırlatmaz.

    Satırın kendi `plan_key`'i varsa o, yoksa `key_fn(row)` kullanılır. Saklı planı OLMAYAN satırda
    `trade_plan` ve `plan_key` ikisi de None olur (var olmayan plana işaret eden anahtar dönmez).
    Zaten `trade_plan` taşıyan satıra (oturum geçmişi) dokunulmaz.
    """
    pending = [r for r in rows if not r.get("trade_plan")]
    try:
        keys = {id(r): (r.get("plan_key") or key_fn(r)) for r in pending}
        from app import database
        plans = await database.get_trade_plans([k for k in keys.values() if k])
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification_plan: satır planları okunamadı: %r", exc)
        keys, plans = {}, {}
    for r in pending:
        k = keys.get(id(r))
        plan = plans.get(k) if k else None
        r["trade_plan"] = plan
        r["plan_key"] = k if plan is not None else None
