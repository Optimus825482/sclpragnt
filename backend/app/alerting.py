"""Paper-only market alert evaluation and notification delivery."""
import asyncio
import json
import os
import time

from app import database


def _matches(rule, value):
    op = str(rule.get("operator", "lte")).lower()
    threshold = float(rule.get("threshold"))
    return {"lt": value < threshold, "lte": value <= threshold, "gt": value > threshold,
            "gte": value >= threshold, "eq": abs(value - threshold) < 1e-9}.get(op, False)


def _rearmed(rule, value):
    rearm = rule.get("rearm_threshold")
    if rearm is None: return True
    op = str(rule.get("operator", "lte")).lower()
    return value >= float(rearm) if op in {"lt", "lte"} else value <= float(rearm)


async def deliver_web_push(message):
    vapid_private, subject = os.getenv("VAPID_PRIVATE_KEY", "").strip(), os.getenv("VAPID_SUBJECT", "mailto:alerts@example.com").strip()
    if not vapid_private: return {"ok": False, "skipped": True, "reason": "vapid_not_configured"}
    try:
        from pywebpush import webpush
        subscriptions = await database.list_push_subscriptions()
        payload = json.dumps({"title": "Scalper Agent alarmı", "body": message, "url": "/alerts"})
        for subscription in subscriptions:
            await asyncio.to_thread(webpush, subscription_info=subscription, data=payload, vapid_private_key=vapid_private, vapid_claims={"sub": subject})
        return {"ok": True, "count": len(subscriptions)}
    except Exception as exc: return {"ok": False, "error": str(exc)}


async def evaluate_rules(market):
    events = []
    rules = await database.list_alert_rules(active_only=True)
    now = time.time()
    for rule in rules:
        if rule.get("expires_at") and now >= float(rule["expires_at"]):
            await database.update_alert_rule(rule["id"], {"enabled": 0}); continue
        ticker = market.get_ticker(rule["symbol"])
        if not ticker or not ticker.get("last_price"): continue
        value = float(ticker["last_price"])
        if rule.get("last_triggered_at") and now - float(rule["last_triggered_at"]) < int(rule.get("cooldown_seconds") or 0): continue
        if not _rearmed(rule, value) and rule.get("last_value") is not None: continue
        if not _matches(rule, value): continue
        event_key = f"{rule['id']}:{int(value * 1000000)}"
        message = f"{rule['symbol']} alarmı: fiyat {value:g} TRY ({rule['operator']} {rule['threshold']:g})"
        event = await database.record_alert_trigger(rule["id"], event_key, value, message, "warning")
        if not event: continue
        channels = rule.get("notify_channels") or ["websocket"]
        if "web_push" in channels: await deliver_web_push(message)
        events.append({"type": "alert", "data": {**event, "rule_id": rule["id"], "symbol": rule["symbol"], "message": message, "channels": channels, "paper_only": True}})
    return events
