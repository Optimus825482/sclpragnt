"""Monitoring page API: continuous scan for high-potential symbols with push notifications."""
import asyncio
import json
import logging
import os
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database
from app.api_common import log_user_action, _background_tasks
from app.state import market, analyzer
from app.routers.velocity import (detect_velocity_candidates, upside_rank_score,
                                  _journal_touch_rates)
from app.alerting import deliver_web_push
from app.ws_runtime import ws_manager
from contextlib import asynccontextmanager

logger = logging.getLogger("scalper.monitoring")
router = APIRouter()

# Monitoring state
_monitoring_state = {
    "last_scan_at": None,
    "last_candidates": [],
    "last_watchlist": [],
    "scan_count": 0,
    "notified_symbols": {},       # symbol -> son bildirim zamanı (epoch)
    "watchlist_seen_at": {},      # symbol -> izlemeye alınma zamanı
    "history": [],                # son bildirim geçmişi (yeni -> eski)
    "pending_targets": {},        # symbol -> {"expected": float, "horizon_minutes": int, "set_at": epoch}
    "candidate_streak": {},       # symbol -> ardışık aday tarama sayısı (debounce)
    "risk_off": False,            # piyasa rejimi RISK_OFF
    "_db_latencies": [],              # notify query gecikmeleri (diagnostics icin, 2026-09-07) (gözlem bayrağı, eşiği etkilemez — 2026-09-04)
}

# Sunucu tarafı döngü aralıkları: genel tarama 60 sn; izleme listesindeki
# semboller her turda zorunlu havuza eklenip yeniden analiz edilir. Böylece
# PWA kapalı olsa bile tarama ve bildirim sunucudan devam eder.
SCAN_INTERVAL_SEC = 60.0
HISTORY_LIMIT = 60
NOTIFY_COOLDOWN_SEC = 300.0  # aynı sembol için tekrar bildirim engeli (5 dk)
_loop_task = None
# Manuel (/api/monitoring/scan) ile arka plan döngüsü aynı anda taramasın diye
# ortak kilit — çift tarama/çift journal/state yarışını önler (2026-09-04).
_scan_lock = asyncio.Lock()

# State lock: _monitoring_state ve _deferred_push concurrent okuma/yazma
# yarisini onler (2026-09-07).
_state_lock = asyncio.Lock()

@asynccontextmanager
async def _locked_state():
    """_monitoring_state ve _deferred_push guvenli erisim icin."""
    async with _state_lock:
        yield

# Runtime state DB kalıcılığı: restart sonrası pending_targets / debounce
# sayacı / bildirim cooldown kaybolmasın diye her tarama sonunda JSON olarak
# yazılır, loop başlarken geri yüklenir (2026-09-04, hibrit sistem).
_STATE_SETTING_KEY = "monitoring_runtime_state"


def normalize_score(raw_score: float) -> float:
    """velocity_score 0-400+ bandina cikabilir; MONITORING_SCORE_NORM_CAP ile
    0-100 panel olcegine haritalanir. Cap astiysa 100, astiysa dogrusal (2026-09-07).
    """
    try:
        raw = float(raw_score or 0)
    except (TypeError, ValueError):
        return 0.0
    cap = config.MONITORING_SCORE_NORM_CAP
    return round(max(0.0, min(100.0, raw / cap * 100)), 1)



async def _persist_runtime_state() -> None:
    try:
        # Deferred push kuyruğunu da kaydet (restart sonrası ertelenen push kaybolmasın)
        deferred = []
        for n in list(_deferred_push):
            deferred.append({
                "symbol": n.get("symbol"), "message": n.get("message"),
                "title": n.get("title"), "url": n.get("url"), "tag": n.get("tag"),
                "score": n.get("score"), "target_pct": n.get("target_pct"),
                "price": n.get("price"), "expected_price": n.get("expected_price"),
                "detected_at": n.get("detected_at"), "horizon_minutes": n.get("horizon_minutes"),
                "mode": n.get("mode"), "id": n.get("id"),
                "ml_hit_probability": n.get("ml_hit_probability"),
                "ml_target_pct": n.get("ml_target_pct"),
            })
        payload = {
            "pending_targets": _monitoring_state["pending_targets"],
            "notified_symbols": _monitoring_state["notified_symbols"],
            "watchlist_seen_at": _monitoring_state["watchlist_seen_at"],
            "candidate_streak": _monitoring_state["candidate_streak"],
            "risk_off": bool(_monitoring_state["risk_off"]),
            "history": _monitoring_state["history"][:100],
            "deferred_push": deferred,
        }
        await database.set_llm_setting(_STATE_SETTING_KEY, json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("monitoring state kalıcılaştırılamadı: %s", exc)


async def restore_runtime_state() -> None:
    """DBden runtime statei geri yukler."""
    try:
        raw = await database.get_llm_setting(_STATE_SETTING_KEY, "{}")
        async with _locked_state():
            payload = json.loads(raw or "{}")
            if isinstance(payload, dict):
                _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}
                _monitoring_state["notified_symbols"] = payload.get("notified_symbols") or {}
                _monitoring_state["watchlist_seen_at"] = payload.get("watchlist_seen_at") or {}
                _monitoring_state["candidate_streak"] = payload.get("candidate_streak") or {}
                _monitoring_state["risk_off"] = bool(payload.get("risk_off", False))
                _monitoring_state["history"] = (payload.get("history") or [])[:HISTORY_LIMIT]
                deferred = payload.get("deferred_push") or []
                _deferred_push.clear()
                for n in deferred:
                    _deferred_push.append(n)
                _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}
    except Exception as exc:
        logger.debug("monitoring state geri yuklenemedi: %s", exc)


def _in_quiet_hours(settings) -> bool:
    """Sessiz saat aralığı kontrolü; gece yarısı üzerinden sarmalı aralık destekler."""
    start, end = settings.get("quiet_hours_start"), settings.get("quiet_hours_end")
    if not start or not end:
        return False
    try:
        h1, m1 = int(str(start).split(":")[0]), int(str(start).split(":")[1])
        h2, m2 = int(str(end).split(":")[0]), int(str(end).split(":")[1])
    except (ValueError, IndexError):
        return False
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    a = h1 * 60 + m1
    b = h2 * 60 + m2
    if a == b:
        return False
    return (cur >= a and cur < b) if a < b else (cur >= a or cur < b)


def _effective_min_score(settings) -> float:
    """O an gercekten uygulanan esik: admin min_score.
    Piyasa RISK_OFF rejimdeyse esik otomatik yukseltilir (2026-09-07).
    """
    base = float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))
    if _monitoring_state.get("risk_off", False):
        base = max(base + 20.0, 50.0)
    return round(min(100.0, base), 1)


async def get_user_notification_settings() -> dict:
    """Global bildirim ayarlarını DB'den oku (admin ayarı — tüm kullanıcıları etkiler).

    min_score varsayılanı config.MONITORING_MIN_SCORE_DEFAULT (70): yalnızca
    yüksek güvenli adaylar bildirilir. Admin PUT ile düşürüp daha fazla
    bildirim alabilir — değişiklik tüm kullanıcıları anında etkiler.
    """
    try:
        settings_json = await database.get_llm_setting("monitoring_notification_settings", "{}")
        settings = json.loads(settings_json or "{}")
        min_score = float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))
        return {
            "enabled": settings.get("enabled", True),
            "min_score": min_score,
            "min_target_pct": float(settings.get("min_target_pct", 2.0)),
            "quiet_hours_start": settings.get("quiet_hours_start", None),
            "quiet_hours_end": settings.get("quiet_hours_end", None),
        }
    except Exception:
        return {"enabled": True, "min_score": config.MONITORING_MIN_SCORE_DEFAULT,
                "min_target_pct": 2.0, "quiet_hours_start": None, "quiet_hours_end": None}


@router.get("/api/monitoring/settings")
async def get_monitoring_settings():
    """Global bildirim ayarlarını döndür (okuma tüm kullanıcıya açık)."""
    settings = await get_user_notification_settings()
    return {"paper_only": True, "scope": "global_admin",
            "risk_off": bool(_monitoring_state["risk_off"]),
            "effective_min_score": _effective_min_score(settings),
            **settings}


@router.put("/api/monitoring/settings")
async def update_monitoring_settings(payload: dict, request: Request):
    """Global bildirim ayarlarını güncelle — YALNIZ admin.

    Admin tarafından yapılan değişiklik tüm kullanıcıları ve arka plan
    döngüsünü anında etkiler (kullanıcı-başı ayar kaldırıldı, 2026-09-04).
    Merge semantiği: yalnızca gönderilen alanlar güncellenir; diğer alanlar
    (min_target_pct, quiet_hours, enabled) korunur — aksi halde eşiği kaydeden
    her istek diğer ayarları varsayılana sıfırlıyordu (2026-09-04 teşhis).
    """
    from app.main import _require_admin
    _require_admin(request)
    existing = await get_user_notification_settings()
    editable = ("enabled", "min_score", "min_target_pct",
                "quiet_hours_start", "quiet_hours_end")
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}
    settings = {
        "enabled": bool(merged.get("enabled", True)),
        "min_score": max(0.0, min(100.0, float(merged.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT)))),
        "min_target_pct": max(0.0, float(merged.get("min_target_pct", 2.0))),
        "quiet_hours_start": merged.get("quiet_hours_start", None),
        "quiet_hours_end": merged.get("quiet_hours_end", None),
    }
    await database.set_llm_setting("monitoring_notification_settings", json.dumps(settings))
    await log_user_action(None, None, "monitoring", "MONITORING_SETTINGS_UPDATE",
                          details={"settings": {k: v for k, v in settings.items() if k != "enabled"},
                                   "scope": "global_admin"},
                          request=request)
    return {"paper_only": True, "ok": True, "scope": "global_admin",
            "risk_off": bool(_monitoring_state["risk_off"]),
            "effective_min_score": _effective_min_score(settings),
            **settings}


# Otonom paper trade (monitoring bildiriminden tetiklenen, 2026-09-04)
# NOT: Sessiz saatte ertelenen push'lar bu kuyrukta tutulur; sessiz saat
# bitince monitoring_background_loop tarafından boşaltılıp gerçek push gönderilir.
# (Öncesinde "ertelenen" bildirim asla push edilmiyordu ve DB'ye yanlışlıkla
# sent_via_push=True yazılıyordu — 2026-09-05 düzeltmesi.)
_deferred_push = deque(maxlen=100)

async def _send_push(notif: dict) -> bool:
    """Tek bildirimi web push ile gönder; gerçek başarı durumunu döndür."""
    try:
        result = await deliver_web_push(
            notif["message"],
            title=notif["title"],
            url=notif["url"],
            tag=notif["tag"],
            extra={
                "symbol": notif["symbol"],
                "score": notif["score"],
                "target_pct": notif["target_pct"],
                "price": notif["price"],
                "expected_price": notif["expected_price"],
                "detected_at": notif["detected_at"],
                "horizon_minutes": notif["horizon_minutes"],
                "source": "monitoring",
            },
        )
        ok = bool(result.get("ok", False))
        if not ok:
            reason = result.get("reason", result.get("error", "unknown"))
            logger.warning("Monitoring push failed for %s: %s", notif["symbol"], reason)
        return ok
    except Exception as exc:
        logger.warning("Monitoring push exception for %s: %s", notif["symbol"], exc)
        return False


async def _flush_deferred_push():
    """Sessiz saat bittiyse ertelenen push kuyruğunu boşalt."""
    if not _deferred_push:
        return
    settings = await get_user_notification_settings()
    if _in_quiet_hours(settings):
        return  # hâlâ sessiz saatteyiz
    sent = 0
    while _deferred_push:
        notif = _deferred_push.popleft()
        ok = await _send_push(notif)
        if ok:
            sent += 1
            # Ertelenen push gerçekten gönderildi → DB etiketini düzelt
            nid = notif.get("id")
            if nid:
                try:
                    await database.mark_monitoring_push_sent(nid)
                except Exception as exc:
                    logger.warning("push etiketi güncellenemedi %s: %s", nid, exc)
        else:
            # Gönderilemedi; bir sonraki fırsatta tekrar dene (kuyruk sonuna ekle)
            _deferred_push.append(notif)
            break
    if sent:
        logger.info("Monitoring: sessiz saat bitti, %d ertelenen push gönderildi", sent)


def _build_notification(sym, c, settings, first_price: float | None = None) -> dict:
    """Zengin bildirim içeriği: sembol, tespit zamanı, %potansiyel, anlık ve beklenen fiyat.

    first_price: mevcut BEKLİYOR bildirimin ilk tespit fiyatı (güncelleme yolunda).
    Yoksa güncel fiyat kullanılır (yeni bildirim) — böylece API yanıtı ile DB'deki
    expected_price her zaman tutarlı olur (2026-09-06).
    """
    score = normalize_score(c.get("velocity_score", 0))
    target = float(c.get("target_pct", 2.0) or 0)
    price = float(c.get("price", 0) or 0)
    if first_price is not None:
        base_price = first_price
    else:
        ticker = market.get_ticker(sym)
        base_price = float(ticker.get("last_price", price)) if ticker else price
    if base_price <= 0:
        base_price = price
    expected_price = base_price * (1 + target / 100) if base_price > 0 else 0.0
    detected_at = time.time()
    horizon = int(c.get("horizon_minutes", 5) or 5)
    ml_prob = c.get("ml_hit_probability")
    ml_pct_str = f" | ML %{ml_prob * 100:.0f}" if ml_prob is not None else ""
    message = (
        f"🎯 {sym} | Skor: {score:.1f} | Potansiyel: +%{target:g} ({horizon}dk){ml_pct_str} | "
        f"Anlık: {base_price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"
    )
    return {
        "symbol": sym,
        "message": message,
        "title": f"🎯 {sym} +%{target:g} potansiyel{ml_pct_str}",
        "url": f"/charts?symbol={sym}",
        "tag": f"monitoring-{sym}",
        "detected_at": detected_at,
        "score": score,
        "target_pct": target,
        "price": base_price,
        "expected_price": expected_price,
        "horizon_minutes": horizon,
        "mode": c.get("mode"),
        "horizon": horizon,
        "ml_hit_probability": ml_prob,
        "ml_target_pct": c.get("ml_target_pct"),
        "settings_applied": {
            "min_score": settings.get("min_score"),
            "min_target_pct": settings.get("min_target_pct"),
        },
    }


def _stored_panel_score(row: dict) -> float:
    """DB'deki score değerini panel (0-100) ölçeğine getirir.

    MONITORING_SCORE_NORM_SINCE sonrası kayıtlar zaten panel skorudur ve
    aynen kullanılır; öncesindeki kayıtlar ham velocity_score olduğundan tek
    kez normalize edilir. Kayda kaydı geçen skora tekrar normalize uygulamak
    (çift dönüşüm) eşiği fiilen 0.4×min_score'a indirdiği için düzeltildi
    (2026-09-04 teşhis).
    """
    try:
        detected = float(row.get("detected_at") or 0)
    except (TypeError, ValueError):
        detected = 0.0
    if detected and detected < float(config.MONITORING_SCORE_NORM_SINCE):
        # Eski (yeni 0-100 formülü öncesi) ham skorları cap'e göre bir kez
        # panel ölçeğine çevir. Yeni kayıtlarda skor zaten 0-100'dür.
        try:
            raw = float(row.get("score") or 0)
        except (TypeError, ValueError):
            raw = 0.0
        cap = float(config.MONITORING_SCORE_NORM_CAP)
        return round(max(0.0, min(100.0, 100.0 * raw / cap)), 1) if cap > 0 else round(max(0.0, min(100.0, raw)), 1)
    try:
        return float(row.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


async def _record_history(entries):
    """Bildirim geçmişini DB'ye kaydet (uygulama kapalıyken gönderilenler dahil)."""
    try:
        await database.save_monitoring_notifications(entries)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi kaydedilemedi: %s", exc)


async def _notify(candidates_list, settings) -> list:
    """Eşikleri geçen adaylar için bildirim üret ve web push gönder.

    Aynı sembol için sonuçlanmamış (BEKLİYOR) bildirim varsa yeni bildirim
    oluşturulmaz; mevcut bildirim güncellenir (hedef, skor, fiyat).
    Sadece önceki bildirim sonuçlanmışsa (TAMAMEN/BASARISIZ) veya ufuk süresi
    dolmuşsa yeni bildirim oluşturulur.
    """
    if not settings.get("enabled", True):
        return []
    # Tek eşik: admin min_score aynen uygulanır (RISK_OFF çarpanı kaldırıldı,
    # 2026-09-04 kullanıcı kararı — tek kaynak _effective_min_score).
    min_score = _effective_min_score(settings)
    quiet = _in_quiet_hours(settings)
    now = time.time()
    notified = []
    new_entries = []     # Yeni bildirimler
    # N+1 önlemi: aday sembollerinin BEKLİYOR kayıtlarını tek toplu sorguyla çek
    # (2026-09-05). Eşik altı adaylar pending kontrolüne girmez; yine de tüm
    # aday setini sorgulamak tek DB round-trip'idir.
    # N+1 onlemi: aday sembollerinin BEKLIYOR kayitlarini tek toplu sorguyla cek
    # (2026-09-05). Esik alti adaylar pending kontrolune girmez; yine de tum
    # aday setini sorgulamak tek DB round-tripidir.
    try:
        _t0 = time.time()
        pending_by_symbol = await database.get_pending_monitoring_notifications(
            [str(c.get("symbol", "") or "").upper() for c in candidates_list])
        _t1 = time.time()
        _db_lat = (_t1 - _t0) * 1000
        _monitoring_state.setdefault("_db_latencies", []).append(_db_lat)
        _monitoring_state["_db_latencies"] = _monitoring_state["_db_latencies"][-20:]
    except Exception as exc:
        logger.warning("monitoring pending toplu sorgu hatasi: %s", exc)
        pending_by_symbol = {}
    for c in candidates_list:
        sym = str(c.get("symbol", "") or "").upper()
        # normalize_score'a geçilir (2026-09-04 teşhis). upside_rank yalnızca
        # SIRALAMA anahtarıdır (dk-başı yükseliş × kalite × mikro-yapı).
        score = normalize_score(c.get("velocity_score", 0))
        target = float(c.get("target_pct") or 2.0)
        min_target = float(settings.get("min_target_pct") or 0)
        if not sym or score < min_score or (min_target > 0 and target < min_target):
            continue
        # Bu sembol icin ufku dolmamis (sonucu bekleyen) bildirim var mi kontrol et.
        # Ufuk + 2 dk tolerans dolmussa bildirim sonuclanmis sayilir; aksi halde
        # ayni kayit guncellenir. (monitoring_notifications'ta status kolonu yok;
        # bekliyor tanimi okuma tarafindaki window_closed ile ayni olmalidir.)
        horizon_min = int(c.get("horizon_minutes", 5) or 5)
        existing_pending = pending_by_symbol.get(sym)
        if existing_pending and (
            now - float(existing_pending.get("detected_at") or 0)
            < (int(existing_pending.get("horizon_minutes") or horizon_min) + 2) * 60
        ):
            # Mevcut BEKLIYOR bildirimi guncelle (detected_at korunur); ML alanlari
            # da guncellenir (aksi halde guncelleme yolunda kaybolurdu, 2026-09-04).
            # Giris fiyati ILK bildirim anindaki fiyat olarak SABIT kalir (2026-09-04
            # kullanici karari): hedef fiyati son taramanin hedef yuzdesiyle ILK
            # giris fiyatindan yeniden hesaplanir — kullanici ilk giris + guncel
            # hedefi aynen takip edebilir (grafik cizgileri de bu iki seviyeyi
            # gosterir).
            first_price = float(existing_pending.get("price") or 0) or float(c.get("price", 0) or 0)
            # Ufuk daralmasın: bildirim SON ufuk süresi dolana kadar takipte kalır;
            # 5dk taraması 15dk bildirimin penceresini kısaltamaz (2026-09-04).
            horizon_keep = max(int(existing_pending.get("horizon_minutes") or 0), horizon_min)
            await database.update_monitoring_notification(
                existing_pending["id"],
                score=score,
                target_pct=target,
                price=first_price,
                expected_price=first_price * (1 + target / 100),
                horizon_minutes=horizon_keep,
                mode=c.get("mode"),
                ml_target_pct=c.get("ml_target_pct"),
                ml_hit_probability=c.get("ml_hit_probability"),
            )
            # Eski kayitlar kalir - sinyal tarihcesi icin
            # Bildirim olarak da ekle (push için)
            notif = _build_notification(sym, c, settings, first_price=first_price)
            notif["id"] = existing_pending["id"]
            notif["updated"] = True
            notified.append(notif)
            # Güncellenen bildirimin streak'i temizlenir (bildirim zaten aktif)
            _monitoring_state["candidate_streak"].pop(sym, None)
            continue
        # Debounce: fast-lane altındaki adaylar N ardışık taramada aday kalmalı
        # (tek-tarama gürültüsünü keser). Yüksek skor hızlı pump'ta gelir —
        # fast-lane (>= MONITORING_FAST_LANE_SCORE) beklemeden geçer.
        streak = int(_monitoring_state["candidate_streak"].get(sym, 0)) + 1
        fast_lane = score >= float(config.MONITORING_FAST_LANE_SCORE)
        if not fast_lane and streak < config.MONITORING_DEBOUNCE_SCANS:
            _monitoring_state["candidate_streak"][sym] = streak
            continue
        _monitoring_state["candidate_streak"][sym] = streak
        # Kısa vadeli soğama
        last_sent = _monitoring_state["notified_symbols"].get(sym)
        if last_sent and now - last_sent < NOTIFY_COOLDOWN_SEC:
            continue
        # Beklenen fiyata ulaşana kadar aynı sembolü tekrar bildirme
        pending = _monitoring_state["pending_targets"].get(sym)
        if pending:
            horizon_ms = int(pending.get("horizon_minutes", 5) + 2) * 60
            if now - float(pending.get("set_at", 0)) < horizon_ms:
                continue
            _monitoring_state["pending_targets"].pop(sym, None)
        notif = _build_notification(sym, c, settings)
        notif["updated"] = False
        new_entries.append(notif)
        notified.append(notif)
        _monitoring_state["notified_symbols"][sym] = now
        _monitoring_state["candidate_streak"].pop(sym, None)
        expected_price = float(notif.get("expected_price") or 0)
        horizon_minutes = int(c.get("horizon_minutes") or 5)
        if expected_price > 0:
            _monitoring_state["pending_targets"][sym] = {
                "expected": expected_price,
                "horizon_minutes": horizon_minutes,
                "set_at": now,
            }
        if len(_monitoring_state["notified_symbols"]) > 500:
            for k in sorted(_monitoring_state["notified_symbols"], key=_monitoring_state["notified_symbols"].get)[:-250]:
                _monitoring_state["notified_symbols"].pop(k, None)
    # Yeni bildirimleri DB'ye kaydet — sessiz saatte push GÖNDERİLMEYECEK
    # bildirimler için sent_via_push=False yazılır (yanlış etiket düzeltmesi).
    if new_entries:
        for n in new_entries:
            n["sent_via_push"] = not quiet
        _s_t0 = time.time()
        await database.save_monitoring_notifications(new_entries)
        _s_t1 = time.time()
        _db_lat = (_s_t1 - _s_t0) * 1000
        _monitoring_state.setdefault("_db_latencies", []).append(_db_lat)
        _monitoring_state["_db_latencies"] = _monitoring_state["_db_latencies"][-20:]
    # Sessiz saat bilgisi bildirim nesnesine işaretlenir (UI geçmişte görür).
    for n in notified:
        n["quiet_hours"] = bool(quiet)
    # Push bildirimleri — sadece YENI bildirimler (guncellemeler her turda
    # tetiklenmesin diye spam korumasi).
    # VAPID anahtarı yoksa push hiç denenmez ve bildirim kaydına işlenir
    # (kullanıcı push gelmediğini anlayabilir).
    vapid_configured = bool(os.getenv("VAPID_PRIVATE_KEY", "").strip())
    new_notifs = [n for n in notified if not n.get("updated")]
    if new_notifs and not quiet and vapid_configured:
        for notif in new_notifs:
            ok = await _send_push(notif)
            notif["push_success"] = ok
            if not ok:
                logger.warning("Monitoring push gönderilemedi (VAPID yapılandırılmamış olabilir): %s", notif.get("symbol"))
    elif new_notifs and not quiet:
        # VAPID yok: push atlanır, bildirim kaydına işlenir
        logger.info("Monitoring push atlandı: VAPID_PRIVATE_KEY yapılandırılmamış (%d bildirim)", len(new_notifs))
        for notif in new_notifs:
            notif["push_success"] = False
    elif new_notifs and quiet:
        # Sessiz saat: push'u ertele — saat bitince _flush_deferred_push gönderir.
        logger.info("Monitoring: sessiz saatlerde %d bildirim push kuyruğuna alındı", len(new_notifs))
        for notif in new_notifs:
            _deferred_push.append(notif)
    # Otonom Paper Trade: sadece YENI bildirimlerde (güncellemelerde pozisyon
    # zaten açık veya hiç açılmamış; güncelleme her turda tetiklenir — gereksiz
    # sorgu + hesaplamayı önlemek için yok sayılır, 2026-09-06).
    try:
        from app.routers.auto_paper import try_open_from_notification
        for notif in new_entries:
            try:
                await try_open_from_notification(notif)
            except Exception as exc:
                logger.debug("auto_paper %s denemesi: %s", notif.get("symbol"), exc)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("auto_paper toplu deneme hatası: %s", exc)
    if new_notifs:
        try:
            await ws_manager.broadcast({"type": "monitoring_alert", "data": new_notifs})
        except Exception as exc:
            logger.warning("Monitoring WS broadcast hatasi: %s", exc)
        _monitoring_state["history"] = (notified + _monitoring_state["history"])[:HISTORY_LIMIT]
    return notified
def _check_pending_targets():
    """Beklenen fiyata ulaşan sembolleri tespit et ve pending listesinden çıkar.

    Her tarama turunda çağrılır: aday listesindeki sembollerin anlık fiyatı,
    kayıtlı expected_price'a eşit veya üstüyse hedefe ulaşılmış sayılır.
    Ufuk süresi + 2 mk tolerans dolduysa da temizlenir (timeout).
    """
    pending = _monitoring_state.get("pending_targets")
    if not pending:
        return
    now = time.time()
    resolved = []
    for sym, info in list(pending.items()):
        horizon_ms = int(info.get("horizon_minutes", 5) + 2) * 60
        set_at = float(info.get("set_at", 0))
        expired = now - set_at >= horizon_ms
        price = None
        try:
            ticker = market.get_ticker(sym) if market else None
            price = float(ticker.get("last_price") or 0) if ticker else None
        except Exception:
            price = None
        expected = float(info.get("expected") or 0)
        hit = price is not None and price > 0 and expected > 0 and price >= expected
        if expired or hit:
            resolved.append(sym)
    for sym in resolved:
        _monitoring_state["pending_targets"].pop(sym, None)


async def _run_scan() -> dict:
    """Tek tarama turu: 5dk + 15dk velocity taramalarını hibrit sıralamayla birleştirir.

    İzleme listesindeki semboller her turda top-gainer havuzuna zorunlu olarak
    eklenir (extra_symbols) — böylece izleme listesi "daha sık analiz edilen"
    listede kalır ve terfi/düşme kararı her turda tazelenir.

    Hibrit (2026-09-04): sembol başına chat upside-scout ile AYNI sıralama
    anahtarı (upside_rank = dk-başı hedef × hız skoru × kalite × mikro-yapı)
    kullanılır; açık pozisyonlu semboller aday listesinden elenir; her adayın
    5dk+15dk çift profili saklanır. RISK_OFF rejimde etkin eşik yükseltilir.
    """
    watch_symbols = sorted({w.get("symbol") for w in (_monitoring_state["last_watchlist"] or []) if w.get("symbol")})
    scan5 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=5, extra_symbols=watch_symbols)
    scan15 = await detect_velocity_candidates({"limit": 10}, horizon_minutes=15, extra_symbols=watch_symbols)

    candidates5 = scan5.get("candidates", [])
    candidates15 = scan15.get("candidates", [])
    watchlist5 = scan5.get("watchlist", [])
    watchlist15 = scan15.get("watchlist", [])

    # Sıralama anahtarı: chat upside-scout ile ortak (journal touch oranları +
    # mikro-yapı çarpanı satırların içinde hazır: upside_rank_score hesaplar).
    touch_rates = await _journal_touch_rates()

    # Çift profil: sembol -> {"5": satır, "15": satır} (aday + izleme havuzundan)
    profiles_by_symbol: dict[str, dict[int, dict]] = {}
    for row in candidates5 + watchlist5:
        profiles_by_symbol.setdefault(str(row.get("symbol") or "").upper(), {})[5] = row
    for row in candidates15 + watchlist15:
        profiles_by_symbol.setdefault(str(row.get("symbol") or "").upper(), {})[15] = row

    def _with_profiles(row: dict) -> dict:
        sym = str(row.get("symbol") or "").upper()
        profs = profiles_by_symbol.get(sym) or {}
        row["profiles"] = {
            str(h): {"horizon_minutes": h,
                     "target_pct": r.get("target_pct"),
                     "velocity_score": r.get("velocity_score"),
                     "upside_rank": round(upside_rank_score(r, touch_rates), 2),
                     "passes": bool(r.get("passes")),
                     "block_reason": r.get("block_reason"),
                     "rsi": r.get("rsi"), "mfi": r.get("mfi"), "atr_pct": r.get("atr_pct"),
                     "m5_pattern_ok": r.get("m5_pattern_ok"), "leading_ok": r.get("leading_ok"), "volume_ratio": r.get("volume_ratio")}
            for h, r in profs.items()
        }
        row["upside_rank"] = round(upside_rank_score(row, touch_rates), 2)
        # Panel (0-100) skoru: arayüz ve liste filtresi ham velocity_score yerine
        # bunu gösterir; admin eşiği bu ölçekte kurgulanmış (2026-09-04).
        row["panel_score"] = normalize_score(row.get("velocity_score", 0))
        return row

    # Birleştir: sembol başına en yüksek upside_rank'li kayıt kalır
    all_candidates = {}
    for c in candidates5 + candidates15:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        _with_profiles(c)
        if sym not in all_candidates or c.get("upside_rank", 0) > all_candidates[sym].get("upside_rank", 0):
            all_candidates[sym] = c

    all_watchlist = {}
    for w in watchlist5 + watchlist15:
        sym = str(w.get("symbol") or "").upper()
        if not sym:
            continue
        _with_profiles(w)
        if sym in all_candidates:  # aday olan izleme listesinde kalmasın
            continue
        if sym not in all_watchlist or w.get("upside_rank", 0) > all_watchlist[sym].get("upside_rank", 0):
            all_watchlist[sym] = w

    # Açık pozisyonlu semboller bildirim adayı olmaz (bot zaten yönetiyor;
    # izleme listesinde görüntülenmeye devam edebilir).
    open_symbols = {str(s or "").upper() for s in (analyzer.positions or {})}
    filtered_candidates = {sym: c for sym, c in all_candidates.items() if sym not in open_symbols}

    # Aday olanlar izleme listesinden çıkar (zaten geçti)
    for sym in all_candidates:
        all_watchlist.pop(sym, None)
        _monitoring_state["watchlist_seen_at"].pop(sym, None)

    # İzlemeye alınanları işaretle
    now = time.time()
    for sym in all_watchlist:
        _monitoring_state["watchlist_seen_at"].setdefault(sym, now)

    # Rejim: RISK_OFF bayrağı — hafif yerel ölçüm (BTC/ETH 1h trend + 5m katılımı).
    # 2026-09-04: bayrağın eşikle ilişkisi kaldırıldı (çarpan yok); yalnızca
    # gözlem amaçlı API'de raporlanmaya devam eder.
    try:
        risk_score = 0
        for ref in ("BTC_TRY", "ETH_TRY"):
            bars = market.get_ut_kline(ref.lower().replace("_", ""), "1h")
            closes = bars.get("closes") or []
            if len(closes) >= 25:
                ema25 = sum(closes[-25:]) / 25
                # Fiyat EMA25 üstündeyse yapıcı/pozitif rejim katkısı; altındaysa zayıflık.
                if closes[-1] >= ema25:
                    risk_score += 1
        _monitoring_state["risk_off"] = risk_score == 0  # hicbir referans EMA25 ustunde degilse riskli
    except Exception:
        pass  # rejim hesaplanamazsa normal eşik (fail-open)

    settings = await get_user_notification_settings()
    effective_min_score = _effective_min_score(settings)
    # Admin eşiği altındaki adaylar listede GÖSTERILMEZ (2026-09-04 kullanıcı
    # kararı; RISK_OFF çarpanı kaldırıldı — _effective_min_score aynen uygulanır).
    # _notify aynı eşiği zaten uyguladığından bildirim davranışı değişmez; yalnız
    # radar listesi temiz kalır.
    candidates_list = sorted(
        (c for c in filtered_candidates.values()
         if float(c.get("panel_score", 0) or 0) >= effective_min_score),
        key=lambda x: x.get("upside_rank", 0), reverse=True)
    watchlist_list = sorted(all_watchlist.values(), key=lambda x: x.get("upside_rank", 0), reverse=True)

    # Bu turdaki aday kümesi: eşik altında kalan sembollerin debounce sayacı sıfırlanır
    current_candidate_syms = set(filtered_candidates)
    for sym in list(_monitoring_state["candidate_streak"]):
        if sym not in current_candidate_syms:
            _monitoring_state["candidate_streak"].pop(sym, None)

    # Beklenen fiyata ulaşan veya süresi dolan sembolleri serbest bırak
    _check_pending_targets()

    new_notifications = await _notify(candidates_list, settings)

    _monitoring_state["last_scan_at"] = now
    _monitoring_state["last_candidates"] = candidates_list
    _monitoring_state["last_watchlist"] = watchlist_list
    _monitoring_state["scan_count"] += 1
    await _persist_runtime_state()
    return {
        "settings": settings,
        "candidates": candidates_list,
        "watchlist": watchlist_list,
        "new_notifications": new_notifications,
    }


@router.get("/api/monitoring/scan")
async def monitoring_scan(request: Request = None):
    """Run a fresh scan for 5m and 15m velocity candidates (admin-only).

    Admin çağrısı: yeni scan başlatır. Normal kullanıcı /api/monitoring/state
    endpoint'inden son tarama sonuçlarını okur.
    """
    from app.main import _require_admin
    try:
        _require_admin(request)
    except HTTPException:
        # Yetkisiz kullanıcılar son tarama önbelleğini döndürür
        settings = await get_user_notification_settings()
        return {
            "paper_only": True,
            "cached": True,
            "scan_at": _monitoring_state["last_scan_at"],
            "scan_count": _monitoring_state["scan_count"],
            "candidates": _monitoring_state["last_candidates"],
            "watchlist": _monitoring_state["last_watchlist"],
            "settings": settings,
            "risk_off": bool(_monitoring_state["risk_off"]),
            "effective_min_score": _effective_min_score(settings),
            "loop_active": _loop_task is not None and not _loop_task.done(),
        }
    try:
        async with _scan_lock:
            result = await _run_scan()
        return {
            "paper_only": True,
            "scan_at": _monitoring_state["last_scan_at"],
            "scan_count": _monitoring_state["scan_count"],
            "candidates": result["candidates"],
            "watchlist": result["watchlist"],
            "new_notifications": len(result["new_notifications"]),
            "notifications": result["new_notifications"],
            "history": _monitoring_state["history"][:20],
            "settings": result["settings"],
            "risk_off": bool(_monitoring_state["risk_off"]),
            "effective_min_score": _effective_min_score(result["settings"]),
            "loop_active": _loop_task is not None and not _loop_task.done(),
        }
    except Exception as exc:
        logger.exception("Monitoring scan failed: %s", exc)
        return {"paper_only": True, "error": str(exc), "candidates": [], "watchlist": []}


@router.get("/api/monitoring/state")
async def monitoring_state():
    """Get current monitoring state (last scan results + notification history)."""
    settings = await get_user_notification_settings()
    last_scan = _monitoring_state.get("last_scan_at")
    next_in = None
    if last_scan:
        next_in = max(0, int(SCAN_INTERVAL_SEC - (time.time() - float(last_scan))))
    return {
        "paper_only": True,
        "last_scan_at": _monitoring_state["last_scan_at"],
        "scan_count": _monitoring_state["scan_count"],
        "candidates": _monitoring_state["last_candidates"],
        "watchlist": _monitoring_state["last_watchlist"],
        "history": _monitoring_state["history"][:20],
        "settings": settings,
        "scope": "global_admin",
        "risk_off": _monitoring_state["risk_off"],
        "effective_min_score": _effective_min_score(settings),
        "loop_active": _loop_task is not None and not _loop_task.done(),
        "next_scan_in_sec": next_in,
    }


@router.get("/api/monitoring/active-notification/{symbol}")
async def monitoring_active_notification(symbol: str):
    """Sembol için ufku dolmamış (BEKLIYOR) son radar bildirimi — grafik sayfası paneli.

    Bildirim anındaki fiyat, hedef fiyat, hedef artış, skor ve ufuk bilgisini
    geri sayım için expires_at ile birlikte döndürür. Panel SON ufuk süresi
    dolana kadar görünür kalır (sembol adaylıktan düşse bile); canlı fiyat ve
    target_hit ile "HEDEFE ULAŞILDI" durumu da döner.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"symbol": sym, "active": False}
    try:
        row = await database.get_pending_monitoring_notification(sym)
    except Exception as exc:
        logger.warning("aktif bildirim okunamadı %s: %s", sym, exc)
        row = None
    if not row:
        return {"symbol": sym, "active": False}
    detected_at = float(row.get("detected_at") or 0)
    horizon = int(row.get("horizon_minutes") or 0)
    expires_at = detected_at + (horizon + 2) * 60
    now = time.time()
    if not detected_at or now >= expires_at:
        return {"symbol": sym, "active": False}
    price = float(row.get("price") or 0)
    expected = float(row.get("expected_price") or 0)
    target_pct = float(row.get("target_pct") or 0)
    # Canlı fiyat (ticker): hedef kontrolü _check_pending_targets ile aynı
    # ölçütle — panel ufuk dolana kadar kalır, hedefe ulaşıldıysa durum döner.
    current_price = None
    try:
        ticker = market.get_ticker(sym) if market else None
        current_price = float(ticker.get("last_price") or 0) if ticker else None
        if not current_price or current_price <= 0:
            current_price = None
    except Exception:
        current_price = None
    target_hit = bool(current_price and expected > 0 and current_price >= expected)
    return {
        "symbol": sym,
        "active": True,
        "score": row.get("score"),
        "target_pct": target_pct,
        "price": price,
        "expected_price": expected,
        "target_gain_pct": round((expected / price - 1) * 100, 3) if price > 0 and expected > 0 else target_pct,
        "detected_at": detected_at,
        "horizon_minutes": horizon,
        "expires_at": expires_at,
        "remaining_sec": max(0, int(expires_at - now)),
        "mode": row.get("mode"),
        "current_price": current_price,
        "target_hit": target_hit,
    }


@router.get("/api/reports/notifications")
async def report_notifications(limit: int = 200, day: str = None):
    """Radar bildirim raporu - gercek kapannis M1 olcmueye dayali basari.
    day: YYYY-MM-DD formatinda gun filtresi (opsiyonel).

    Global admin eşiği altındaki bildirimler NE gösterilir NE başarı hesabına
    katılır (2026-09-04 kullanıcı kararı; RISK_OFF çarpanı kaldırıldı) — düşük
    skorlu gürültü başarı oranını yanıltmasın.
    """
    limit = max(1, min(int(limit), 1000))
    settings = await get_user_notification_settings()
    # Tek eşik ilkesi (2026-09-04 kullanıcı kararı): raporlar da radar/bildirim/
    # otonom taramayla AYNI etkin eşiği kullanır (admin min_score — RISK_OFF
    # çarpanı kaldırıldı) — ekranda gösterilen sayı fiilen uygulananla aynıdır.
    min_score = _effective_min_score(settings)
    rows = await database.get_monitoring_velocity_matches(limit=limit, day=day)
    # Eşik filtresi panel (0-100) skoru üzerinden; eski ham kayıtlar tek kez
    # normalize edilir (bkz. _stored_panel_score).
    rows = [r for r in rows
            if _stored_panel_score(r) >= min_score]
    now = time.time()
    result = []
    for row in rows:
        symbol = row.get("symbol")
        price = float(row.get("price") or 0)
        target_pct = float(row.get("target_pct") or 0)
        detected_at = float(row.get("detected_at") or 0)
        mfe = row.get("mfe_pct")
        mfe_pct = float(mfe) if mfe is not None else None
        touched = row.get("touched_target")
        candidate_status = str(row.get("candidate_status") or "")
        horizon = int(row.get("horizon_minutes") or 0)
        window_closed = bool(detected_at and horizon and (now - detected_at) >= (horizon + 2) * 60)
        if candidate_status == "evaluated" and mfe_pct is not None:
            if touched:
                status = "TAMAMEN BAŞARILI"
            elif target_pct > 0 and mfe_pct >= target_pct * 0.5:
                status = "BAŞARILI"
            elif mfe_pct > 0:
                status = "KISMİ"
            else:
                status = "BAŞARISIZ"
        elif candidate_status == "pending" and not window_closed:
            status = "BEKLİYOR"
        else:
            status = "ÖLÇÜLEMEDİ" if window_closed else "BEKLİYOR"
        result.append({
            "id": row.get("id"),
            "symbol": symbol,
            "message": row.get("message"),
            "title": row.get("title"),
            # Panel (0-100) skoru: eski ham kayıtlar da aynı ölçeğe çevrilerek
            # tabloda tek ölçek gösterilir (2026-09-04).
            "score": _stored_panel_score(row),
            "target_pct": target_pct,
            "price": price,
            "expected_price": row.get("expected_price"),
            "mfe_pct": mfe_pct,
            "touched_target": touched,
            "status": status,
            "mode": row.get("mode"),
            "horizon_minutes": horizon,
            "detected_at": detected_at,
            "sent_via_push": row.get("sent_via_push"),
            "candidate_id": row.get("candidate_id"),
            "ml_hit_probability": row.get("ml_hit_probability"),
        })
    counts = {"TAMAMEN BAŞARILI": 0, "BAŞARILI": 0, "KISMİ": 0,
              "BAŞARISIZ": 0, "BEKLİYOR": 0, "ÖLÇÜLEMEDİ": 0}
    for item in result:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    evaluated = sum(counts[k] for k in ("TAMAMEN BAŞARILI", "BAŞARILI", "KISMİ", "BAŞARISIZ"))
    success = counts["TAMAMEN BAŞARILI"] + counts["BAŞARILI"]
    day_breakdown = {"counts": counts, "evaluated": evaluated,
                    "success_count": success,
                    "success_rate": (success / evaluated * 100) if evaluated else None}
    all_rows = await database.get_monitoring_velocity_matches(limit=1000, day=None)
    # Genel başarı da aynı global eşiğe tabi (gürültü oranları dışarıda kalır);
    # eski kayıtlar için tek kez normalize uygulanır (bkz. _stored_panel_score).
    all_rows = [r for r in all_rows if _stored_panel_score(r) >= min_score]
    all_evaluated = 0
    all_success = 0
    for r in all_rows:
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tch = r.get("touched_target")
        cand_st = str(r.get("candidate_status") or "")
        tgt = float(r.get("target_pct") or 0)
        if cand_st == "evaluated" and mfe_f is not None:
            all_evaluated += 1
            if tch or mfe_f >= tgt * 0.5:
                all_success += 1
    overall_breakdown = {
        "evaluated": all_evaluated,
        "success_count": all_success,
        "success_rate": (all_success / all_evaluated * 100) if all_evaluated else None,
    }
    return {"paper_only": True, "notifications": result, "total": len(result),
            "breakdown": day_breakdown, "overall": overall_breakdown}

@router.get("/api/monitoring/diagnostics")
async def monitoring_diagnostics():
    """Diagnostic deep-dive: compare target_pct vs actual MFE across all records.
    
    Returns per-symbol breakout so user can spot where the success rate is lost.
    """
    settings = await get_user_notification_settings()
    min_score = _effective_min_score(settings)
    rows = await database.get_monitoring_velocity_matches(limit=1000, day=None)
    rows = [r for r in rows if _stored_panel_score(r) >= min_score]
    profile_buckets: dict[str, list] = {"all": []}
    for r in rows:
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tgt = float(r.get("target_pct") or 0)
        cand_st = str(r.get("candidate_status") or "")
        if cand_st != "evaluated" or mfe_f is None:
            continue
        score = _stored_panel_score(r)
        bucket = "all"
        # Score buckets
        if score >= 90:
            bucket = "90-100"
        elif score >= 80:
            bucket = "80-90"
        elif score >= 70:
            bucket = "70-80"
        elif score >= 60:
            bucket = "60-70"
        elif score >= 50:
            bucket = "50-60"
        else:
            bucket = "0-50"
        tch = bool(r.get("touched_target"))
        label = "TAMAMEN" if tch else ("BASARILI" if mfe_f >= tgt * 0.5 else
                                        ("KISMİ" if mfe_f > 0 else "BASARISIZ"))
        entry = {"symbol": r.get("symbol"), "score": score, "target_pct": tgt,
                 "mfe_pct": round(mfe_f, 3), "status": label, "horizon": r.get("horizon_minutes")}
        profile_buckets.setdefault(bucket, []).append(entry)
        profile_buckets["all"].append(entry)
    summary = {}
    for bk, items in profile_buckets.items():
        n = len(items)
        s = sum(1 for i in items if i["status"] in ("TAMAMEN", "BASARILI"))
        avg_target = sum(i["target_pct"] for i in items) / n if n else 0
        avg_mfe = sum(i["mfe_pct"] for i in items) / n if n else 0
        summary[bk] = {"count": n, "success": s, "success_rate": round(s/n*100,1) if n else 0,
                       "avg_target_pct": round(avg_target,2), "avg_mfe_pct": round(avg_mfe,2)}
    # Per-symbol top losers
    by_symbol = {}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tgt = float(r.get("target_pct") or 0)
        cand_st = str(r.get("candidate_status") or "")
        if cand_st != "evaluated" or mfe_f is None:
            continue
        tch = bool(r.get("touched_target"))
        by_symbol.setdefault(sym, {"count": 0, "success": 0, "total_mfe": 0.0, "total_target": 0.0})
        by_symbol[sym]["count"] += 1
        if tch or mfe_f >= tgt * 0.5:
            by_symbol[sym]["success"] += 1
        by_symbol[sym]["total_mfe"] += mfe_f
        by_symbol[sym]["total_target"] += tgt
    sym_summary = {}
    for sym, d in sorted(by_symbol.items(), key=lambda x: x[1]["success"]/max(x[1]["count"],1)):
        sym_summary[sym] = {"count": d["count"], "success": d["success"],
                            "rate": round(d["success"]/d["count"]*100, 1) if d["count"] else 0,
                            "avg_mfe": round(d["total_mfe"]/d["count"], 3) if d["count"] else 0,
                            "avg_target": round(d["total_target"]/d["count"], 2) if d["count"] else 0}
    # WS and rate limit metrics (2026-09-07)
    ws_metrics = {}
    try:
        from app.ws_runtime import ws_manager
        ws_metrics["active_connections"] = len(ws_manager.active_connections)
    except Exception:
        ws_metrics["active_connections"] = None
    try:
        md = market
        ws_metrics["ws_last_event_at"] = getattr(md, "ws_last_event_at", None)
        ws_metrics["rest_last_event_at"] = getattr(md, "rest_last_event_at", None)
        ws_metrics["ws_last_error"] = str(getattr(md, "ws_last_error", None))[:200] if getattr(md, "ws_last_error", None) else None
        ws_metrics["rest_last_error"] = str(getattr(md, "rest_last_error", None))[:200] if getattr(md, "rest_last_error", None) else None
        ws_metrics["ws_connected_at"] = getattr(md, "ws_connected_at", None)
        ws_metrics["connection_generation"] = getattr(md, "connection_generation", 0)
        ws_metrics["reconnect_requested"] = getattr(md, "reconnect_requested", False)
        ws_metrics["subscribed_symbols"] = len(getattr(md, "symbols", []))
    except Exception as exc:
        ws_metrics["error"] = str(exc)
    rate_stats = {}
    try:
        from app.routers import velocity
        rate_stats = velocity._rate_limit_stats()
    except Exception as exc:
        rate_stats["error"] = str(exc)
    freshness_sample = {}
    try:
        for sym_item in list(_monitoring_state.get("last_candidates") or [])[:3]:
            sym_name = str(sym_item.get("symbol", "") or "")
            if sym_name:
                fd = market.data_freshness(sym_name, "5m") if hasattr(market, "data_freshness") else {}
                freshness_sample[sym_name] = fd
    except Exception:
        pass
    # Memory usage: obezite tespiti (2026-09-07)
    memory_metrics = {}
    try:
        import sys as _sys
        # Klines cache boyutu: tum timeframelerdeki tum semboller icin toplam deger
        total_klines = 0
        total_volumes = 0
        md = market
        if hasattr(md, "klines"):
            for tf_kv in md.klines.values():
                for sym_kv in tf_kv.values():
                    if isinstance(sym_kv, dict):
                        klines_len = len(sym_kv.get("timestamps") or [])
                        total_klines += klines_len
                        total_volumes += len(sym_kv.get("volumes") or [])
        memory_metrics["total_cached_klines"] = total_klines
        memory_metrics["total_cached_volumes"] = total_volumes
        if hasattr(md, "tickers"):
            memory_metrics["ticker_count"] = len(md.tickers)
        if hasattr(md, "ticker_24h"):
            memory_metrics["ticker_24h_count"] = len(md.ticker_24h)
        if hasattr(md, "orderflow"):
            memory_metrics["orderflow_count"] = len(md.orderflow)
        if hasattr(md, "trade_flow"):
            memory_metrics["trade_flow_count"] = len(md.trade_flow)
        if hasattr(md, "symbols"):
            memory_metrics["subscribed_symbols"] = len(md.symbols)
    except Exception as exc:
        memory_metrics["error"] = str(exc)
    # DB query latency: son 3 notify sorgusunun gecikmesi (2026-09-07)
    db_latency = {}
    try:
        _db_latencies = _monitoring_state.get("_db_latencies", [])
        # Her notify turu sonunda _notify latency kaydeder; burada son 3'un ortalamasi
        recent = list(_db_latencies)[-3:] if _db_latencies else []
        if recent:
            db_latency["avg_notify_ms"] = round(sum(recent) / len(recent), 1)
            db_latency["max_notify_ms"] = round(max(recent), 1)
            db_latency["sample_count"] = len(recent)
        else:
            db_latency["avg_notify_ms"] = None
            db_latency["max_notify_ms"] = None
            db_latency["sample_count"] = 0
    except Exception:
        pass
    return {
        "paper_only": True,
        "effective_min_score": min_score,
        "overall": summary,
        "per_symbol_worst": dict(list(sym_summary.items())[:30]),
        "settings": settings,
        "ws_health": ws_metrics,
        "rate_limiter": rate_stats,
        "freshness_sample": freshness_sample,
        "memory_metrics": memory_metrics,
        "db_latency": db_latency,
    }


@router.post("/api/monitoring/reset-notifications")
async def reset_monitoring_notifications(request: Request):
    """Clear notified symbols list (allows re-notification) — YALNIZ admin.

    Reset sonrasi ayni semboller yeniden bildirilebilir; spam korumasini
    atlatabilmek isteyen her kimlik yetkili olmamalidir (2026-09-04).
    """
    from app.main import _require_admin
    _require_admin(request)
    async with _locked_state():
        _monitoring_state["notified_symbols"].clear()
    await log_user_action(None, None, "monitoring", "MONITORING_NOTIFICATIONS_RESET",
                          details={}, request=request)
    return {"ok": True, "message": "Bildirim sıfırlandı"}


@router.get("/api/monitoring/notifications")
async def monitoring_notification_history():
    """Son bildirim geçmişi: kalıcı DB kaydı + oturum içi liste."""
    try:
        persisted = await database.list_monitoring_notifications(limit=50)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi okunamadı: %s", exc)
        persisted = []
    return {"paper_only": True, "history": persisted, "session": _monitoring_state["history"][:20]}


async def monitoring_background_loop():
    """Sunucu tarafı sürekli tarama: PWA kapalıyken bile taramayı ve push
    bildirimlerini sürdürür. İzleme listesi her turda yeniden analiz edilir;
    yeni aday çıktığında kısa aralıkla tekrar değerlendirilir."""
    logger.info("Monitoring arka plan taraması başladı (tur=%ss)", SCAN_INTERVAL_SEC)
    await restore_runtime_state()
    # Başlangıçta market verisi hazır olsun diye ilk tura küçük gecikme
    await asyncio.sleep(20)
    while True:
        try:
            async with _scan_lock:
                async with _locked_state():
                    await _run_scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring loop turu başarısız: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL_SEC)
            continue
        # Sessiz saat bittiyse ertelenen push'ları gönder (scan kilidinden bağımsız)
        try:
            await _flush_deferred_push()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring ertelenen push gönderimi: %s", exc)
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def start_monitoring_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat (idempotent)."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(monitoring_background_loop(), name="monitoring-scan-loop")
    _background_tasks.add(_loop_task)
    return True


def stop_monitoring_loop():
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _background_tasks.discard(_loop_task)
        _loop_task = None