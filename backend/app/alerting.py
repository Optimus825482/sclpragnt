"""Paper-only market alert evaluation and notification delivery."""
import asyncio
import json
import logging
import os
import time

from app import database

logger = logging.getLogger("scalper.alerting")


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


# ALERT-FLOOD (2026-09-16 denetimi): `alert_loop` kural setini SANİYEDE BİR
# değerlendirir. `cooldown_seconds` tek frendi; tetikleme `armed`'i YALNIZ
# `rearm_threshold` doluysa False yapar (`database.record_alert_trigger`), yani
# `rearm_threshold` yok + `cooldown_seconds=0` olan bir kural HER SANİYE yeni bir
# `alert_events` satırı + push üretir; kanalda `auto_paper_trade` varsa saniyede
# bir açılış denemesi olur. API `0`'ı kabul ediyor (`main.py`), şema varsayılanı
# 1800 sn olduğu için felaket şimdiye kadar görünmedi.
# Çözüm: motor tarafında TABAN uygula — depolanan değer ne olursa olsun bir kural
# saniyede bir ateşleyemez. `0` "kasıtlı ek cooldown yok" anlamını korur.
ALERT_MIN_COOLDOWN_SEC = 60


def _cooldown_blocks(rule, now) -> bool:
    """Cooldown penceresi kuralı bloke ediyor mu? (TABAN uygulanır)"""
    last = rule.get("last_triggered_at")
    if not last:
        return False
    try:
        elapsed = now - float(last)
    except (TypeError, ValueError):
        return False
    configured = int(rule.get("cooldown_seconds") or 0)
    return elapsed < max(configured, ALERT_MIN_COOLDOWN_SEC)


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
        payload_obj = {
            "title": title or "Scalper Agent alarmı",
            "body": message,
            "url": url or "/alerts",
            "sound": "/alarm.wav",
        }
        if tag: payload_obj["tag"] = tag
        if extra: payload_obj.update(extra)
        payload = json.dumps(payload_obj)
        success_count = 0
        dead_subscriptions = []
        for subscription in subscriptions:
            try:
                await asyncio.to_thread(webpush, subscription_info=subscription, data=payload,
                                        vapid_private_key=vapid_private,
                                        vapid_claims={"sub": subject})
                success_count += 1
            except Exception as sub_exc:
                err_str = str(sub_exc).lower()
                # 410 Gone, 404 Not Found,  expired endpoint → subscription ölü
                if "410" in err_str or "404" in err_str or "gone" in err_str or "expired" in err_str:
                    dead_subscriptions.append(subscription.get("endpoint", ""))
                    logger.warning("Push: ölü abonelik tespit edildi: %s", subscription.get("endpoint", "")[:60])
                else:
                    logger.warning("Push: abonelik gönderim hatası: %s", sub_exc)
        if dead_subscriptions:
            try:
                await database.remove_push_subscriptions(dead_subscriptions)
                logger.info("Push: %d ölü abonelik temizlendi", len(dead_subscriptions))
            except Exception as cleanup_exc:
                logger.warning("Push: abonelik temizleme hatası: %s", cleanup_exc)
        return {"ok": success_count > 0, "count": success_count, "total": len(subscriptions),
                "dead_count": len(dead_subscriptions)}
    except Exception as exc:
        logger.error("Push teslimat hatası: %s", exc)
        return {"ok": False, "error": str(exc)}


async def deliver_alert_push(message, *, title=None, url=None, tag=None, extra=None):
    """Sessiz saatlere SAYGILI alarm push'u (radar ile aynı sözleşme).

    2026-09-16 denetimi: `_evaluate_single_rule` push'u DOĞRUDAN gönderiyordu, yani
    kullanıcının sessiz saat ayarı alarm kurallarında yok sayılıyordu — radar akışı
    ise ertelemeli (`monitoring._deferred_push`). İki yol artık aynı davranışta:
    sessiz saatte push ERTELENİR, event + WS yine üretilir (panelde görünür,
    bildirim sessizlik bitince gider).

    Döngü önlemi: `monitoring` GEC import edilir (`auto_paper.py:184` aynı desen).
    Sessizlik sorgusu hata verirse GÖNDERİLİR (fail-open): kullanıcı bu alarmı
    açıkça kurdu; sorgu arızası onu tümüyle sessizleştirmemeli.
    """
    payload = {"message": message, "title": title or "Scalper Agent alarmı",
               "url": url or "/alerts", "tag": tag or "scalper-alert"}
    try:
        from app.routers import monitoring as _monitoring
        if await _monitoring.quiet_hours_active():
            _monitoring._deferred_push.append({
                **payload,
                "symbol": "ALERT",
                # `_flush_deferred_push` bayatlığı detected_at+horizon ile ölçer;
                # alarm kuralı 24 saat anlamlı kalsın (radar ufku 5-15 dk).
                "detected_at": time.time(), "horizon_minutes": 24 * 60,
                "deferred_alert": True,
            })
            logger.info("Alarm push'u sessiz saat nedeniyle ertelendi: %s", message[:60])
            return {"ok": False, "deferred": True, "reason": "quiet_hours"}
    except Exception as exc:
        logger.warning("Alarm sessizlik sorgusu başarısız, push gönderiliyor: %s", exc)
    return await deliver_web_push(message, title=payload["title"], url=payload["url"],
                                  tag=payload["tag"], extra=extra)


# alert_loop her saniye çalışır; kural listesi saniyede bir DB'den okunmak
# yerine 3 sn TTL ile cache'lenir (~86k sorgu/gün tasarruf). Kural ekleme/
# silme en geç 3 sn sonra devreye girer — alert kullanımı için yeterli.
_alert_rules_cache = {"at": 0.0, "rules": []}


async def evaluate_rules(market, on_paper_trigger=None):
    events = []
    now = time.time()
    if now - _alert_rules_cache["at"] > 3.0:
        _alert_rules_cache["rules"] = await database.list_alert_rules(active_only=True)
        _alert_rules_cache["at"] = now
    rules = _alert_rules_cache["rules"]
    for rule in rules:
        try:
            events.extend(await _evaluate_single_rule(market, rule, now, on_paper_trigger))
        except Exception as exc:
            print(f"[Alerts] Kural {rule.get('id')} değerlendirilemedi: {type(exc).__name__}: {exc}", flush=True)
            # Geçici DB/parser hatası kalıcı devre dışı bırakmamalı; yalnızca logla.
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
    if _cooldown_blocks(rule, now): return events
    if not _matches(rule, value): return events
    event_key = f"{rule['id']}:{time.time_ns()}"
    unit = "%" if str(rule.get("rule_type", "price")).lower() == "percent" else "TRY"
    message = f"{rule['symbol']} alarmı: değer {value:g} {unit} ({rule['operator']} {rule['threshold']:g})"
    event = await database.record_alert_trigger(rule["id"], event_key, value, message, "warning")
    if not event: return events
    channels = rule.get("notify_channels") or ["websocket"]
    push_result = None
    if "web_push" in channels:
        # 2026-09-16: doğrudan `deliver_web_push` yerine sessiz-saat farkında yol.
        # Dönen sonuç olaya yazılır → alarm tarafında da push dürüstlüğü görünür
        # (radar akışındaki `sent_via_push` sözleşmesinin karşılığı).
        try:
            push_result = await deliver_alert_push(message, tag=f"alert-{rule['id']}")
        except Exception as push_exc:
            push_result = {"ok": False, "error": str(push_exc)}
            logger.warning("Alarm push hatası (rule=%s): %s", rule.get("id"), push_exc)
    auto_result = None
    if "auto_paper_trade" in channels and on_paper_trigger:
        try:
            auto_result = await on_paper_trigger(rule, event)
            message += f" | otomatik paper sonuç: {auto_result.get('status', 'unknown')}"
        except Exception as exc:
            auto_result = {"status": "error", "error": str(exc), "paper_only": True}
            message += f" | otomatik paper hata: {type(exc).__name__}"
    payload = {**event, "rule_id": rule["id"], "symbol": rule["symbol"], "message": message, "channels": channels, "paper_only": True}
    if push_result is not None: payload["push_result"] = push_result
    if auto_result is not None: payload["auto_paper_trade"] = auto_result
    events.append({"type": "alert", "data": payload})
    return events