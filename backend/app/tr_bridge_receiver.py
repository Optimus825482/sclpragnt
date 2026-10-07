"""Binance Global -> Binance TR Lead-Lag (Öncü-Artçı) Sinyal Alıcısı (Receiver).

Bu modül, Binance Global tarafından gönderilen öncü sinyalleri karşılar,
`X-Bridge-Secret` ile doğrular, gecikmeyi (latency) ölçer, sembolü TR karşılığına
dönüştürür ve yapılandırılan kurallara göre (auto_trade, min_score, cooldown)
otonom paper trade pozisyonu açar ya da sinyali kaydedip WebSocket ile arayüze iletir.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from app.config import config
from app import database
from app.state import market, analyzer, extend_stream_universe
from app.ws_runtime import ws_manager

logger = logging.getLogger("scalper.tr_bridge_receiver")

# In-memory dairesel tampon: Son 100 sinyal ve iletim geçmişi
_HISTORY_LIMIT = 100
_history: deque[Dict[str, Any]] = deque(maxlen=_HISTORY_LIMIT)

# Cooldown takibi: (tr_symbol, signal_type) -> son_kabul_zamani
_last_signal_times: Dict[tuple[str, str], float] = {}

# #36/P2-11 (A): event_id idempotent dedupe. Aynı köprü olayı ağ yeniden
# denemesi veya kötü niyetli tekrar nedeniyle yeniden gelebilir; event_id
# bazlı bu defter ikinci işlemeyi engeller. TTL'li ve üst sınırlıdır →
# bellekte sınırsız büyümez (persist edilmez; süreç yeniden başlarsa sıfırlanır,
# bu da normaldir çünkü ağ yeniden denemeleri kısa ömürlüdür).
_EVENT_DEDUP_TTL_SEC = 600.0
_EVENT_DEDUP_MAX_ENTRIES = 1000
_seen_events: Dict[str, float] = {}
_seen_events_lock = threading.Lock()

# #36/P2-11 (B): köprü olaylarının zaman damgası için makul saat kayması
# penceresi (sn). Bu pencerenin dışındaki olaylar reddedilir.
_MAX_TIMESTAMP_SKEW_SEC = float(os.getenv("BRIDGE_MAX_TIMESTAMP_SKEW_SEC", "300"))

# #36/P2-11 (C): `force` cooldown'u tamamen atlamaz; yalnızca bu minimum
# aralığa kısaltır (force kötüye kullanımına karşı).
_FORCE_MIN_INTERVAL_SEC = float(os.getenv("BRIDGE_FORCE_MIN_INTERVAL_SEC", "10"))

# İstatistik sayaçları
_stats = {
    "total_received": 0,
    "pings_received": 0,
    "signals_received": 0,
    "trades_opened": 0,
    "trades_blocked": 0,
    "cooldown_skips": 0,
    "auth_failures": 0,
    "replay_skipped": 0,
    "clock_skew_rejected": 0,
    "last_received_at": None,
    "total_latency_ms": 0.0,
    "latency_count": 0,
}


def _is_duplicate_event(event_id: str, now: float) -> bool:
    """event_id daha önce işlendi mi? Süresi geçmiş kayıtları budayarak sorar."""
    with _seen_events_lock:
        stale = [key for key, ts in _seen_events.items() if now - ts > _EVENT_DEDUP_TTL_SEC]
        for key in stale:
            _seen_events.pop(key, None)
        return event_id in _seen_events


def _remember_event(event_id: str, now: float) -> None:
    """Kabul edilen olayın event_id'sini kaydet (üst sınırda en eskisini düşür)."""
    with _seen_events_lock:
        if len(_seen_events) >= _EVENT_DEDUP_MAX_ENTRIES:
            oldest = min(_seen_events, key=_seen_events.get)
            _seen_events.pop(oldest, None)
        _seen_events[event_id] = now


def clear_replay_state() -> None:
    """Replay/de-dupe durumunu sıfırlar (testler ve bakım için)."""
    with _seen_events_lock:
        _seen_events.clear()

# main.py ve runtime_routes tarafından geç bağlanacak fonksiyonlar
_daily_loss_guard_fn: Optional[Callable[..., Any]] = None
_wallet_invalidator_fn: Optional[Callable[[], None]] = None


def set_daily_loss_guard_fn(fn: Callable[..., Any]) -> None:
    """main.py içindeki daily_loss_guard fonksiyonunu bağlar."""
    global _daily_loss_guard_fn
    _daily_loss_guard_fn = fn


def set_wallet_invalidator_fn(fn: Callable[[], None]) -> None:
    """runtime_routes.invalidate_wallet_caches fonksiyonunu bağlar."""
    global _wallet_invalidator_fn
    _wallet_invalidator_fn = fn


def mask_secret(secret: str) -> str:
    """Gizli anahtarın yalnızca ilk ve son 3 karakterini gösterir."""
    sec = str(secret or "").strip()
    if not sec:
        return ""
    if len(sec) <= 6:
        return "***"
    return f"{sec[:3]}***{sec[-3:]}"


async def get_receiver_settings() -> Dict[str, Any]:
    """Aktif alıcı ayarlarını döner. DB ayarları env varsayılanlarını ezer."""
    db_enabled = await database.get_llm_setting("bridge_receiver_enabled")
    if db_enabled is not None:
        enabled = str(db_enabled).strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(getattr(config, "BINANCE_TR_RECEIVER_ENABLED", True))

    db_secret = await database.get_llm_setting("bridge_secret")
    if db_secret is not None and str(db_secret).strip():
        secret = str(db_secret).strip()
    else:
        secret = str(getattr(config, "BINANCE_TR_BRIDGE_SECRET", "")).strip()

    db_auto_trade = await database.get_llm_setting("bridge_auto_trade")
    if db_auto_trade is not None:
        auto_trade = str(db_auto_trade).strip().lower() in {"1", "true", "yes", "on"}
    else:
        auto_trade = bool(getattr(config, "BINANCE_TR_BRIDGE_AUTO_TRADE", True))

    db_min_score = await database.get_llm_setting("bridge_min_score")
    if db_min_score is not None:
        try:
            min_score = float(db_min_score)
        except (ValueError, TypeError):
            min_score = float(getattr(config, "BINANCE_TR_BRIDGE_MIN_SCORE", 0.0))
    else:
        min_score = float(getattr(config, "BINANCE_TR_BRIDGE_MIN_SCORE", 0.0))

    db_cooldown = await database.get_llm_setting("bridge_cooldown_sec")
    if db_cooldown is not None:
        try:
            cooldown_sec = float(db_cooldown)
            if cooldown_sec <= 10.0:
                cooldown_sec = 60.0
        except (ValueError, TypeError):
            cooldown_sec = float(getattr(config, "BINANCE_TR_BRIDGE_COOLDOWN_SEC", 60.0))
    else:
        cooldown_sec = float(getattr(config, "BINANCE_TR_BRIDGE_COOLDOWN_SEC", 60.0))

    return {
        "enabled": enabled,
        "secret": secret,
        "masked_secret": mask_secret(secret),
        "auto_trade": auto_trade,
        "min_score": min_score,
        "cooldown_sec": cooldown_sec,
    }


async def update_receiver_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Alıcı ayarlarını çalışma anında günceller ve DB'ye yazar."""
    if "enabled" in updates:
        val = "1" if bool(updates["enabled"]) else "0"
        await database.set_llm_setting("bridge_receiver_enabled", val)

    if "secret" in updates and updates["secret"] is not None:
        sec = str(updates["secret"]).strip()
        await database.set_llm_setting("bridge_secret", sec)

    if "auto_trade" in updates:
        val = "1" if bool(updates["auto_trade"]) else "0"
        await database.set_llm_setting("bridge_auto_trade", val)

    if "min_score" in updates:
        try:
            val = float(updates["min_score"])
            await database.set_llm_setting("bridge_min_score", str(val))
        except (ValueError, TypeError):
            pass

    if "cooldown_sec" in updates:
        try:
            val = max(1.0, float(updates["cooldown_sec"]))
            await database.set_llm_setting("bridge_cooldown_sec", str(val))
        except (ValueError, TypeError):
            pass

    return await get_receiver_settings()


async def verify_bridge_secret(header_secret: Optional[str]) -> bool:
    """X-Bridge-Secret başlığını zamanlama analizi saldırılarına dayanıklı karşılaştırır."""
    settings = await get_receiver_settings()
    configured_secret = settings.get("secret", "")
    if not configured_secret:
        logger.warning("[BridgeReceiver] BINANCE_TR_BRIDGE_SECRET yapılandırılmamış, istek reddedildi.")
        _stats["auth_failures"] += 1
        return False

    if not header_secret:
        _stats["auth_failures"] += 1
        return False

    is_valid = hmac.compare_digest(header_secret.strip(), configured_secret.strip())
    if not is_valid:
        _stats["auth_failures"] += 1
        logger.warning("[BridgeReceiver] Geçersiz X-Bridge-Secret başlığı.")
    return is_valid


def map_to_tr_symbol(global_symbol: str = "", base_asset: str = "", tr_symbol: str = "") -> str:
    """Binance Global sembolünü veya taban varlığını Binance TR karşılığına çevirir."""
    # 1. Açıkça tr_symbol verilmişse
    raw_tr = str(tr_symbol or "").strip().upper()
    if raw_tr:
        if not raw_tr.endswith("TRY"):
            return f"{raw_tr}TRY"
        return raw_tr

    # 2. base_asset verilmişse (örn: SOL -> SOLTRY)
    raw_base = str(base_asset or "").strip().upper()
    if raw_base:
        return f"{raw_base}TRY"

    # 3. global_symbol verilmişse (örn: SOLUSDT -> SOLTRY)
    raw_global = str(global_symbol or "").strip().upper()
    if raw_global.endswith("USDT"):
        return f"{raw_global[:-4]}TRY"
    if raw_global.endswith("TRY"):
        return raw_global
    if raw_global:
        return f"{raw_global}TRY"

    return ""


def get_bridge_status() -> Dict[str, Any]:
    """Alıcının durum, sayaç, ortalama gecikme ve son olay özetini döner."""
    avg_latency = 0.0
    if _stats["latency_count"] > 0:
        avg_latency = round(_stats["total_latency_ms"] / _stats["latency_count"], 2)

    return {
        "ok": True,
        "total_received": _stats["total_received"],
        "pings_received": _stats["pings_received"],
        "signals_received": _stats["signals_received"],
        "trades_opened": _stats["trades_opened"],
        "trades_blocked": _stats["trades_blocked"],
        "cooldown_skips": _stats["cooldown_skips"],
        "auth_failures": _stats["auth_failures"],
        "replay_skipped": _stats["replay_skipped"],
        "clock_skew_rejected": _stats["clock_skew_rejected"],
        "last_received_at": _stats["last_received_at"],
        "avg_latency_ms": avg_latency,
        "history_count": len(_history),
    }


def get_bridge_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Son alınan sinyallerin geçmişini döner."""
    return list(_history)[-limit:]


async def process_global_signal(payload: Dict[str, Any], client_ip: Optional[str] = None) -> Dict[str, Any]:
    """Binance Global'den gelen sinyali işler, doğrular ve aksiyon alır."""
    now = time.time()
    _stats["total_received"] += 1
    _stats["last_received_at"] = now

    event_id = str(payload.get("event_id") or uuid.uuid4())
    global_ts = float(payload.get("timestamp") or now)
    lead_lag_latency_ms = max(0.0, (now - global_ts) * 1000.0)

    # #36/P2-11 (A): replay koruması — aynı event_id ikinci kez İŞLENMEZ.
    # Ağ yeniden denemesi veya tekrar oynatma aynı sinyali iki kez açmasın.
    if _is_duplicate_event(event_id, now):
        _stats["replay_skipped"] += 1
        logger.warning("[BridgeReceiver] Yinelendiği için atlandı: event_id=%s", event_id)
        _history.append({
            "event_id": event_id,
            "received_at": now,
            "status": "replay_skipped",
            "client_ip": client_ip,
        })
        return {
            "ok": True,
            "status": "replay_skipped",
            "event_id": event_id,
            "message": "Bu event_id daha önce işlendi (replay koruması).",
        }

    # #36/P2-11 (B): saat kayması denetimi. Yalnızca AÇIKÇA verilen pozitif
    # `timestamp` denetlenir; timestamp yoksa `now` kullanılır ve denetim
    # anlamsız olur (ping'ler de böyle çalışır).
    _raw_ts = payload.get("timestamp")
    try:
        _have_ts = _raw_ts is not None and float(_raw_ts) > 0
    except (TypeError, ValueError):
        _have_ts = False
    if _have_ts and abs(now - global_ts) > _MAX_TIMESTAMP_SKEW_SEC:
        _stats["clock_skew_rejected"] += 1
        logger.warning("[BridgeReceiver] Saat kayması reddi: event_id=%s skew=%.1fs",
                       event_id, now - global_ts)
        _history.append({
            "event_id": event_id,
            "received_at": now,
            "global_timestamp": global_ts,
            "clock_skew_sec": round(now - global_ts, 2),
            "status": "clock_skew_rejected",
            "client_ip": client_ip,
        })
        return {
            "ok": False,
            "status": "clock_skew_rejected",
            "event_id": event_id,
            "message": f"Olay zaman damgası makul saat penceresinin dışında "
                       f"({abs(now - global_ts):.0f} sn > {_MAX_TIMESTAMP_SKEW_SEC:.0f} sn).",
        }

    _remember_event(event_id, now)

    # İstatistik ortalamasını güncelle
    _stats["total_latency_ms"] += lead_lag_latency_ms
    _stats["latency_count"] += 1

    signal_type = str(payload.get("signal_type") or "signal").lower()
    action = str(payload.get("action") or "BUY_SIGNAL").upper()

    # 1. PING isteği kontrolü
    if signal_type == "ping" or action == "PING":
        _stats["pings_received"] += 1
        record = {
            "event_id": event_id,
            "received_at": now,
            "global_timestamp": global_ts,
            "latency_ms": round(lead_lag_latency_ms, 2),
            "signal_type": "ping",
            "action": "PING",
            "status": "pong",
            "client_ip": client_ip,
        }
        _history.append(record)
        return {
            "ok": True,
            "status": "pong",
            "event_id": event_id,
            "lead_lag_latency_ms": round(lead_lag_latency_ms, 2),
            "server_time": now,
        }

    _stats["signals_received"] += 1
    settings = await get_receiver_settings()

    # 2. Alıcı aktiflik denetimi
    if not settings.get("enabled", True):
        record = {
            "event_id": event_id,
            "received_at": now,
            "global_timestamp": global_ts,
            "latency_ms": round(lead_lag_latency_ms, 2),
            "signal_type": signal_type,
            "action": action,
            "status": "receiver_disabled",
            "client_ip": client_ip,
        }
        _history.append(record)
        return {
            "ok": False,
            "status": "disabled",
            "event_id": event_id,
            "message": "Binance TR sinyal alıcısı ayarlardan devre dışı bırakılmış.",
        }

    # 3. Yalnızca BUY_SIGNAL işlem açılışıdır (scalper-trade-manager sözleşmesi)
    if action != "BUY_SIGNAL":
        record = {
            "event_id": event_id,
            "received_at": now,
            "signal_type": signal_type,
            "action": action,
            "status": "action_ignored",
        }
        _history.append(record)
        return {
            "ok": False,
            "status": "action_ignored",
            "event_id": event_id,
            "message": f"Desteklenmeyen eylem: {action}. Yalnızca BUY_SIGNAL işlenir.",
        }

    # 4. Sembol çözümleme ve normalizasyon
    global_symbol = str(payload.get("global_symbol") or "").upper()
    base_asset = str(payload.get("base_asset") or "").upper()
    tr_symbol = map_to_tr_symbol(global_symbol, base_asset, payload.get("tr_symbol"))

    if not tr_symbol:
        record = {
            "event_id": event_id,
            "received_at": now,
            "signal_type": signal_type,
            "status": "invalid_symbol",
        }
        _history.append(record)
        return {"ok": False, "status": "invalid_symbol", "event_id": event_id, "message": "TR sembolü çözümlenemedi."}

    # 5. Skor filtre denetimi (varsayılan 0.0, Global'den gelen sinyaller filtrelenmez)
    score = float(payload.get("score") or 0.0)
    min_score = float(settings.get("min_score", 0.0))
    if min_score > 0 and score < min_score:
        record = {
            "event_id": event_id,
            "received_at": now,
            "global_symbol": global_symbol,
            "tr_symbol": tr_symbol,
            "signal_type": signal_type,
            "score": score,
            "min_score": min_score,
            "status": "score_below_minimum",
        }
        _history.append(record)
        return {
            "ok": True,
            "status": "score_below_minimum",
            "event_id": event_id,
            "symbol": tr_symbol,
            "score": score,
            "min_score": min_score,
        }

    # 6. Cooldown (Deduplikasyon) koruması: sembol bazlı 60 sn
    cooldown_sec = float(settings.get("cooldown_sec", 60.0))
    force = bool(payload.get("force", False))
    cooldown_key = tr_symbol  # Sembol bazlı: radar, llm_second_eye, monitoring fark etmeksizin 60sn uygulanır
    last_accepted = _last_signal_times.get(cooldown_key, 0.0)

    # #36/P2-11 (C): `force` artık cooldown'u TAMAMEN atlamaz. Eskiden force=True
    # 60 sn'lik sembol cooldown'unu tümüyle bypass ediyordu; bu, tek bir
    # bayrakla sinyal bombardımanına (ve emir/pozisyon spam'ine) kapı açıyordu.
    # Artık force yalnızca bekleme süresini _FORCE_MIN_INTERVAL_SEC'e (varsayılan
    # 10 sn) kısaltır; bu minimum aralık da uygulanır.
    effective_cooldown = min(cooldown_sec, _FORCE_MIN_INTERVAL_SEC) if force else cooldown_sec

    if (now - last_accepted) < effective_cooldown:
        _stats["cooldown_skips"] += 1
        remaining = round(effective_cooldown - (now - last_accepted), 2)
        record = {
            "event_id": event_id,
            "received_at": now,
            "global_symbol": global_symbol,
            "tr_symbol": tr_symbol,
            "signal_type": signal_type,
            "score": score,
            "latency_ms": round(lead_lag_latency_ms, 2),
            "status": "cooldown_skipped",
            "remaining_sec": remaining,
            "cooldown_sec": effective_cooldown,
            "forced": force,
        }
        _history.append(record)
        return {
            "ok": True,
            "status": "cooldown_skipped",
            "event_id": event_id,
            "symbol": tr_symbol,
            "remaining_sec": remaining,
            "message": f"{tr_symbol} için son sinyalden bu yana henüz {effective_cooldown} sn dolmadı ({remaining} sn kaldı).",
        }

    _last_signal_times[cooldown_key] = now

    # 7. Binance TR Ticker ve anlık fiyat tespiti
    tr_price = 0.0
    if market:
        ticker = market.get_ticker(tr_symbol)
        if ticker and ticker.get("last_price"):
            tr_price = float(ticker["last_price"])

    # Ticker hafızada yoksa REST üzerinden anında tek seferlik sorgula
    if tr_price <= 0:
        try:
            from app.binance_tr_public import ticker_price as _fetch_tr_price
            price_res = await _fetch_tr_price(tr_symbol)
            if price_res and float(price_res.get("price") or 0) > 0:
                tr_price = float(price_res["price"])
                if isinstance(getattr(market, "tickers", None), dict):
                    market.tickers[tr_symbol] = {
                        "symbol": tr_symbol,
                        "last_price": tr_price,
                        "timestamp": int(now * 1000),
                        "source": "tr_bridge_rest_hydrate",
                    }
        except Exception as exc:
            logger.warning("[BridgeReceiver] %s fiyat hydration hatası: %s", tr_symbol, exc)

    if tr_price <= 0:
        record = {
            "event_id": event_id,
            "received_at": now,
            "global_symbol": global_symbol,
            "tr_symbol": tr_symbol,
            "status": "price_unavailable",
        }
        _history.append(record)
        return {
            "ok": False,
            "status": "price_unavailable",
            "event_id": event_id,
            "symbol": tr_symbol,
            "message": f"{tr_symbol} için Binance TR fiyatı alınamadı.",
        }

    # Fiyat teyit edildi: sembolü anında akış evrenine dahil et (WS mum ve derinlik için)
    try:
        extend_stream_universe([tr_symbol], source="global_bridge")
    except Exception as exc:
        logger.debug("[BridgeReceiver] extend_stream_universe atlandı %s: %s", tr_symbol, exc)

    # 8. Sinyali kalıcı DB'ye kaydet (signals + decision_logs)
    title = str(payload.get("title") or "Global Lead-Lag Sinyali")
    message = str(payload.get("message") or "")
    global_price = float(payload.get("price") or 0.0)

    sig_record = {
        "timestamp": now,
        "symbol": tr_symbol,
        "action": "BUY_SIGNAL",
        "price": tr_price,
        "reason": f"GLOBAL_BRIDGE:{signal_type}:{title}",
        "strategy": "GLOBAL_LEAD_LAG",
        "trade_id": None,
        "score": score,
        "global_symbol": global_symbol,
        "global_price": global_price,
        "lead_lag_latency_ms": round(lead_lag_latency_ms, 2),
        "event_id": event_id,
    }
    try:
        await database.save_signal(sig_record)
    except Exception as exc:
        logger.error("[BridgeReceiver] Sinyal DB kaydı başarısız: %s", exc)

    # 9. TR BİLDİRİM SİSTEMİNE (MONITORING NOTIFICATIONS) KAYDET VE TÜM KANALLARA YAYINLA
    p_data = payload.get("data") or {}
    target_pct = float(p_data.get("target_pct") or 2.0)
    horizon_minutes = float(p_data.get("horizon_minutes") or 15.0)
    take_profit_pct = max(0.005, target_pct / 100.0)
    stop_loss_pct = config.HARD_STOP_LOSS_PCT
    max_hold_sec = max(180, int(horizon_minutes * 60))
    expected_price = round(tr_price * (1.0 + target_pct / 100.0), 6) if tr_price > 0 else 0.0

    notif_title = f"🌐 [GLOBAL] {tr_symbol}"
    notif_message = (
        f"Binance Global öncü sinyali ({global_symbol or tr_symbol}) | "
        f"Tür: {signal_type.upper()} | Skor: {score:.1f} | Hedef: +%{target_pct:.1f}"
    )

    notif_entry = {
        "symbol": tr_symbol,
        "title": notif_title,
        "message": notif_message,
        "score": score,
        "target_pct": target_pct,
        "price": tr_price,
        "expected_price": expected_price,
        "horizon_minutes": int(horizon_minutes),
        "mode": "global_lead_lag",
        "detected_at": now,
        "sent_via_push": False,
        "sources": ["global"],
        "url": f"/monitoring?symbol={tr_symbol}",
        "tag": f"global-{tr_symbol}",
    }
    try:
        await database.save_monitoring_notifications([notif_entry])
    except Exception as exc:
        logger.error("[BridgeReceiver] monitoring_notifications DB kaydı hatası: %s", exc)

    # WebSocket üzerinden canlı arayüze yayınla (RadarAlertModal ve Monitoring)
    ws_notif = dict(notif_entry)
    ws_notif["alertKind"] = "global"
    ws_notif["kind"] = "global"
    ws_notif["source"] = "global"
    ws_notif["sources"] = ["global"]
    ws_notif["unified_sources"] = ["global"]
    ws_notif["global_symbol"] = global_symbol
    ws_notif["lead_lag_latency_ms"] = round(lead_lag_latency_ms, 2)

    try:
        await ws_manager.broadcast({
            "type": "monitoring_alert",
            "data": [ws_notif],
        })
    except Exception as exc:
        logger.debug("[BridgeReceiver] WebSocket monitoring_alert yayını hatası: %s", exc)

    try:
        await ws_manager.broadcast({
            "type": "global_bridge_signal",
            "data": {
                "event_id": event_id,
                "global_symbol": global_symbol,
                "base_asset": base_asset,
                "tr_symbol": tr_symbol,
                "signal_type": signal_type,
                "action": action,
                "score": score,
                "global_price": global_price,
                "tr_price": tr_price,
                "lead_lag_latency_ms": round(lead_lag_latency_ms, 2),
                "title": notif_title,
                "message": notif_message,
                "payload_data": payload.get("data") or {},
                "timestamp": now,
            }
        })
    except Exception as exc:
        logger.debug("[BridgeReceiver] WebSocket global_bridge_signal yayını hatası: %s", exc)

    # Web Push gönderimi (cihaza push bildirim)
    try:
        from app.routers.monitoring import _send_push
        push_ok = await _send_push(notif_entry)
        if push_ok and notif_entry.get("id"):
            await database.mark_monitoring_push_sent(notif_entry["id"])
    except Exception as exc:
        logger.debug("[BridgeReceiver] Web push gönderim hatası: %s", exc)

    # 10. Otonom Paper Trade Tetikleyici
    auto_trade = settings.get("auto_trade", True)
    trade_outcome: Dict[str, Any] = {"status": "disabled", "reason": "auto_trade_disabled"}

    if auto_trade:
        # 10.1 Global risk ve günlük zarar kapısı (daily_loss_guard)
        if _daily_loss_guard_fn:
            try:
                guard = await _daily_loss_guard_fn()
                if guard and guard.get("halt"):
                    _stats["trades_blocked"] += 1
                    trade_outcome = {"status": "blocked", "reason": f"daily_loss_guard:{guard.get('reason')}"}
            except Exception as exc:
                logger.warning("[BridgeReceiver] Risk kapısı kontrolü hatası: %s", exc)

        # 10.2 Çift pozisyon (already_open) kontrolü: Bildirim verildi, ancak tekrar pozisyon açılmaz
        if trade_outcome.get("status") != "blocked" and analyzer and tr_symbol in analyzer.positions:
            trade_outcome = {
                "status": "already_open",
                "reason": f"{tr_symbol} için zaten açık bir pozisyon mevcut.",
            }

        # 10.3 Maksimum açık pozisyon sayısı kontrolü
        max_positions = int(getattr(config, "MAX_OPEN_POSITIONS", 5) or 5)
        if trade_outcome.get("status") not in ("blocked", "already_open") and analyzer and max_positions > 0 and len(analyzer.positions) >= max_positions:
            _stats["trades_blocked"] += 1
            trade_outcome = {"status": "blocked", "reason": "max_open_positions_reached"}

        # 10.4 Pozisyon Açılışı
        if trade_outcome.get("status") not in ("blocked", "already_open"):
            entry_context_extra = {
                "source": "global_bridge",
                "global_symbol": global_symbol,
                "global_price": global_price,
                "signal_type": signal_type,
                "score": score,
                "lead_lag_latency_ms": round(lead_lag_latency_ms, 2),
                "target_pct": target_pct,
                "horizon_minutes": horizon_minutes,
                "event_id": event_id,
                "signal_context": {
                    "no_initial_stop": False,
                }
            }

            try:
                trade_res = await analyzer.open_position(
                    symbol=tr_symbol,
                    entry_price=tr_price,
                    side="LONG",
                    strat_name="GLOBAL_LEAD_LAG",
                    order_value=None,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    max_hold_sec=max_hold_sec,
                    entry_context_extra=entry_context_extra,
                )

                if trade_res and str(trade_res.get("action") or "").upper() == "BUY_SIGNAL":
                    trade_id = trade_res.get("trade_id")
                    _stats["trades_opened"] += 1
                    trade_outcome = {
                        "status": "opened",
                        "trade_id": trade_id,
                        "entry_price": tr_price,
                        "target_pct": target_pct,
                        "horizon_minutes": horizon_minutes,
                    }
                    if _wallet_invalidator_fn:
                        try:
                            _wallet_invalidator_fn()
                        except Exception:
                            pass
                    logger.info(
                        "[BridgeReceiver] %s için GLOBAL_LEAD_LAG pozisyonu açıldı (trade_id=%s, fiyat=%.4f)",
                        tr_symbol, trade_id, tr_price
                    )
                else:
                    _stats["trades_blocked"] += 1
                    trade_outcome = {
                        "status": "blocked",
                        "reason": (trade_res or {}).get("reason", "risk_or_liquidity_gate"),
                    }
            except Exception as exc:
                _stats["trades_blocked"] += 1
                trade_outcome = {"status": "error", "reason": str(exc)}
                logger.error("[BridgeReceiver] open_position hatası (%s): %s", tr_symbol, exc)

    status_str = "executed" if trade_outcome.get("status") == "opened" else trade_outcome.get("status", "processed")
    record = {
        "event_id": event_id,
        "received_at": now,
        "global_symbol": global_symbol,
        "tr_symbol": tr_symbol,
        "signal_type": signal_type,
        "action": action,
        "score": score,
        "global_price": global_price,
        "tr_price": tr_price,
        "latency_ms": round(lead_lag_latency_ms, 2),
        "status": status_str,
        "trade": trade_outcome,
        "client_ip": client_ip,
    }
    _history.append(record)

    return {
        "ok": True,
        "status": status_str,
        "event_id": event_id,
        "global_symbol": global_symbol,
        "tr_symbol": tr_symbol,
        "tr_price": tr_price,
        "lead_lag_latency_ms": round(lead_lag_latency_ms, 2),
        "trade": trade_outcome,
    }


async def get_bridge_performance(day: str = "all") -> Dict[str, Any]:
    """Global Lead-Lag sinyalleri ve işlemlerinin detaylı performans ve başarı raporunu üretir."""
    # 1. Kapanmış işlemleri çek
    raw_trades = await database.get_trades(limit=500, strategy="GLOBAL_LEAD_LAG")

    # 2. Tarih filtresi
    target_day = str(day or "all").strip()
    trades = []
    for t in raw_trades:
        exit_ts = float(t.get("exit_time") or 0.0)
        if target_day != "all" and exit_ts > 0:
            trade_day = time.strftime("%Y-%m-%d", time.localtime(exit_ts))
            if trade_day != target_day:
                continue
        trades.append(t)

    # 3. Açık pozisyonları tespit et
    open_positions = []
    if analyzer and getattr(analyzer, "positions", None):
        for sym, pos in list(analyzer.positions.items()):
            if str(pos.get("strategy") or "").upper() == "GLOBAL_LEAD_LAG":
                ticker = market.get_ticker(sym) if market else {}
                current_price = float((ticker or {}).get("last_price") or pos.get("entry_price") or 0.0)
                entry_price = float(pos.get("entry_price") or current_price or 1.0)
                qty = float(pos.get("quantity") or 0.0)
                unrealized_pnl = (current_price - entry_price) * qty
                unrealized_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

                open_positions.append({
                    "symbol": sym,
                    "side": pos.get("side", "LONG"),
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "quantity": qty,
                    "unrealized_pnl_try": round(unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                    "stop_price": pos.get("system_stop_price") or pos.get("stop_price"),
                    "take_profit_price": pos.get("system_take_profit_price") or pos.get("take_profit"),
                    "entry_time": pos.get("entry_time"),
                    "trade_id": pos.get("trade_id"),
                    "entry_context": pos.get("entry_context") or {},
                })

    # 4. Sinyalleri çek (signals tablosundan ve in-memory tamponundan)
    raw_signals = await database.get_signals(limit=200, strategy="GLOBAL_LEAD_LAG")
    filtered_signals = []
    for s in raw_signals:
        sig_ts = float(s.get("timestamp") or 0.0)
        if target_day != "all" and sig_ts > 0:
            sig_day = time.strftime("%Y-%m-%d", time.localtime(sig_ts))
            if sig_day != target_day:
                continue
        filtered_signals.append(s)

    # In-memory geçmişteki son olayları da eşleştir
    recent_events = list(_history)
    if target_day != "all":
        recent_events = [
            e for e in recent_events
            if time.strftime("%Y-%m-%d", time.localtime(float(e.get("received_at") or 0))) == target_day
        ]

    # 5. İstatistik hesaplamaları
    closed_count = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
    losses = sum(1 for t in trades if float(t.get("pnl") or 0) <= 0)
    win_rate = round((wins / closed_count * 100), 1) if closed_count > 0 else 0.0
    net_pnl = sum(float(t.get("pnl") or 0) for t in trades)
    total_commission = sum(float(t.get("commission") or 0) for t in trades)

    # Çıkış nedenleri dağılımı
    reasons: Dict[str, int] = {}
    for t in trades:
        r = str(t.get("reason") or "diger")
        reasons[r] = reasons.get(r, 0) + 1

    target_hits = reasons.get("lead_lag_take_profit", 0) + reasons.get("chat_plan_take_profit", 0)
    target_touch_rate = round((target_hits / closed_count * 100), 1) if closed_count > 0 else 0.0

    # Ortalama tutma süresi (dakika)
    durations = [
        (float(t.get("exit_time") or 0) - float(t.get("entry_time") or 0)) / 60.0
        for t in trades
        if t.get("exit_time") and t.get("entry_time") and float(t.get("exit_time")) > float(t.get("entry_time"))
    ]
    avg_hold_min = round(sum(durations) / len(durations), 1) if durations else 0.0

    avg_pnl_pct = round(sum(float(t.get("pnl_pct") or 0) for t in trades) / closed_count, 2) if closed_count > 0 else 0.0

    # Ortalama gecikme (lead-lag latency)
    avg_lat = 0.0
    if _stats["latency_count"] > 0:
        avg_lat = round(_stats["total_latency_ms"] / _stats["latency_count"], 1)

    summary = {
        "day": target_day,
        "total_signals": len(filtered_signals) or len(recent_events),
        "total_trades": closed_count + len(open_positions),
        "open_trades_count": len(open_positions),
        "closed_trades_count": closed_count,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "target_touch_rate": target_touch_rate,
        "net_pnl_try": round(net_pnl, 2),
        "total_commission_try": round(total_commission, 2),
        "avg_pnl_pct": avg_pnl_pct,
        "avg_hold_minutes": avg_hold_min,
        "avg_latency_ms": avg_lat,
        "exit_reasons": reasons,
    }

    return {
        "ok": True,
        "day": target_day,
        "summary": summary,
        "open_positions": open_positions,
        "closed_trades": trades[:100],
        "recent_signals": recent_events[-50:],
    }

