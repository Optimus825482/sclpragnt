"""Paper-only market alert evaluation and notification delivery."""
import asyncio
import json
import os
import time

from app import database


def _matches(rule, value):
    op = str(rule.get("operator", "lte")).lower()
    try:
        threshold = float(rule.get("threshold"))
    except (TypeError, ValueError):
        # A malformed threshold must disable the rule, not kill the whole
        # alert loop every second.
        raise ValueError(f"Geçersiz alarm eşiği: {rule.get('threshold')!r}")
    return {"lt": value < threshold, "lte": value <= threshold, "gt": value > threshold,
            "gte": value >= threshold, "eq": abs(value - threshold) < 1e-9}.get(op, False)


def _rearmed(rule, value):
    rearm = rule.get("rearm_threshold")
    if rearm is None: return True
    op = str(rule.get("operator", "lte")).lower()
    return value >= float(rearm) if op in {"lt", "lte"} else value <= float(rearm)


def _rule_value(rule, market, ticker):
    """Return the configured observation instead of always treating alerts as prices."""
    last_price = float(ticker["last_price"])
    if str(rule.get("rule_type", "price")).lower() != "percent":
        return last_price
    kline = market.get_ut_kline(rule["symbol"], rule.get("timeframe", "5m")) or {}
    closes = [float(value) for value in (kline.get("closes") or [])]
    if len(closes) < 2 or closes[-2] == 0:
        return None
    return (last_price / closes[-2] - 1.0) * 100.0


async def deliver_web_push(message, *, title=None, url=None, tag=None, extra=None):
    vapid_private, subject = os.getenv("VAPID_PRIVATE_KEY", "").strip(), os.getenv("VAPID_SUBJECT", "mailto:alerts@example.com").strip()
    if not vapid_private: return {"ok": False, "skipped": True, "reason": "vapid_not_configured"}
    try:
        from pywebpush import webpush
        subscriptions = await database.list_push_subscriptions()
        payload_obj = {"title": title or "Scalper Agent alarmı", "body": message, "url": url or "/alerts"}
        if tag: payload_obj["tag"] = tag
        if extra: payload_obj.update(extra)
        payload = json.dumps(payload_obj)
        for subscription in subscriptions:
            await asyncio.to_thread(webpush, subscription_info=subscription, data=payload, vapid_private_key=vapid_private, vapid_claims={"sub": subject})
        return {"ok": True, "count": len(subscriptions)}
    except Exception as exc: return {"ok": False, "error": str(exc)}


async def evaluate_rules(market, on_paper_trigger=None):
    events = []
    rules = await database.list_alert_rules(active_only=True)
    now = time.time()
    for rule in rules:
        try:
            events.extend(await _evaluate_single_rule(market, rule, now, on_paper_trigger))
        except Exception as exc:
            print(f"[Alerts] Kural {rule.get('id')} değerlendirilemedi: {type(exc).__name__}: {exc}", flush=True)
            await database.update_alert_rule(rule["id"], {"enabled": 0})
    return events


async def _evaluate_single_rule(market, rule, now, on_paper_trigger):
    events = []
    if rule.get("expires_at") and now >= float(rule["expires_at"]):
        await database.update_alert_rule(rule["id"], {"enabled": 0}); return events
    ticker = market.get_ticker(rule["symbol"])
    if not ticker or not ticker.get("last_price"): return events
    value = _rule_value(rule, market, ticker)
    if value is None: return events
    armed = bool(rule.get("armed", True))
    if not armed:
        if _rearmed(rule, value):
            await database.update_alert_rule(rule["id"], {"armed": True, "last_value": value})
        return events
    if rule.get("last_triggered_at") and now - float(rule["last_triggered_at"]) < int(rule.get("cooldown_seconds") or 0): return events
    if not _matches(rule, value): return events
    event_key = f"{rule['id']}:{time.time_ns()}"
    unit = "%" if str(rule.get("rule_type", "price")).lower() == "percent" else "TRY"
    message = f"{rule['symbol']} alarmı: değer {value:g} {unit} ({rule['operator']} {rule['threshold']:g})"
    event = await database.record_alert_trigger(rule["id"], event_key, value, message, "warning")
    if not event: return events
    channels = rule.get("notify_channels") or ["websocket"]
    if "web_push" in channels: await deliver_web_push(message)
    auto_result = None
    if "auto_paper_trade" in channels and on_paper_trigger:
        try:
            auto_result = await on_paper_trigger(rule, event)
            message += f" | otomatik paper sonuç: {auto_result.get('status', 'unknown')}"
        except Exception as exc:
            auto_result = {"status": "error", "error": str(exc), "paper_only": True}
            message += f" | otomatik paper hata: {type(exc).__name__}"
    payload = {**event, "rule_id": rule["id"], "symbol": rule["symbol"], "message": message, "channels": channels, "paper_only": True}
    if auto_result is not None: payload["auto_paper_trade"] = auto_result
    events.append({"type": "alert", "data": payload})
    return events