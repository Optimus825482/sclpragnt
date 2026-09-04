"""Monitoring page API: continuous scan for high-potential symbols with push notifications."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request

from app.config import config
from app import database
from app.api_common import log_user_action
from app.state import market, analyzer
from app.routers.velocity import (detect_velocity_candidates, upside_rank_score,
                                  _journal_touch_rates)
from app.alerting import deliver_web_push
from app.ws_runtime import ws_manager

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
    "risk_off": False,            # piyasa rejimi RISK_OFF bayrağı (etkin eşiği yükseltir)
}

# Sunucu tarafı döngü aralıkları: genel tarama 60 sn; izleme listesindeki
# semboller her turda zorunlu havuza eklenip yeniden analiz edilir ve aday
# kümesi değiştiyse kısa aralıkla yeniden değerlendirilir. Böylece PWA kapalı
# olsa bile tarama ve bildirim sunucudan devam eder.
SCAN_INTERVAL_SEC = 60.0
WATCHLIST_RESCAN_SEC = 30.0
HISTORY_LIMIT = 60
NOTIFY_COOLDOWN_SEC = 300.0  # aynı sembol için tekrar bildirim engeli (5 dk)
_loop_task = None

# Runtime state DB kalıcılığı: restart sonrası pending_targets / debounce
# sayacı / bildirim cooldown kaybolmasın diye her tarama sonunda JSON olarak
# yazılır, loop başlarken geri yüklenir (2026-09-04, hibrit sistem).
_STATE_SETTING_KEY = "monitoring_runtime_state"


def normalize_score(raw_score: float) -> float:
    """Ham velocity_score'u 0-100 panel ölçeğine çevirir.

    velocity_score çarpım (ATR×BB×struct×ML×leading) olduğundan 0-200+ aralığında
    değişir (üretim: çoğu 0-30). Admin bildirim eşikleri (min_score=50, fast-lane=70)
    0-100 paneline göre kurgulanmış; doğrudan ham skorla karşılaştırmak sistemi pratikte
    devre dışı bırakıyordu (2026-09-04 teşhis). MONITORING_SCORE_NORM_CAP üstü doyurulur.
    """
    try:
        raw = float(raw_score or 0)
    except (TypeError, ValueError):
        return 0.0
    cap = float(config.MONITORING_SCORE_NORM_CAP)
    if cap <= 0:
        return round(raw, 1)
    return round(100.0 * min(1.0, raw / cap), 1)


async def _persist_runtime_state() -> None:
    try:
        payload = {
            "pending_targets": _monitoring_state["pending_targets"],
            "notified_symbols": _monitoring_state["notified_symbols"],
            "watchlist_seen_at": _monitoring_state["watchlist_seen_at"],
            "candidate_streak": _monitoring_state["candidate_streak"],
        }
        await database.set_llm_setting(_STATE_SETTING_KEY, json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("monitoring state kalıcılaştırılamadı: %s", exc)


async def restore_runtime_state() -> None:
    """DB'den runtime state'i geri yükler (monitoring_background_loop başlangıcında)."""
    try:
        raw = await database.get_llm_setting(_STATE_SETTING_KEY, "{}")
        payload = json.loads(raw or "{}")
        if isinstance(payload, dict):
            _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}
            _monitoring_state["notified_symbols"] = payload.get("notified_symbols") or {}
            _monitoring_state["watchlist_seen_at"] = payload.get("watchlist_seen_at") or {}
            _monitoring_state["candidate_streak"] = payload.get("candidate_streak") or {}
    except Exception as exc:
        logger.debug("monitoring state geri yüklenemedi: %s", exc)


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


async def get_user_notification_settings() -> dict:
    """Global bildirim ayarlarını DB'den oku (admin ayarı — tüm kullanıcıları etkiler).

    min_score varsayılanı config.MONITORING_MIN_SCORE_DEFAULT (50): radar verisi
    04.09.2026 — skor >=50 altı kovalar gürültü, üstü nitelikli.
    """
    try:
        settings_json = await database.get_llm_setting("monitoring_notification_settings", "{}")
        settings = json.loads(settings_json or "{}")
        return {
            "enabled": settings.get("enabled", True),
            "min_score": float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT)),
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
    return {"paper_only": True, "scope": "global_admin", **settings}


@router.put("/api/monitoring/settings")
async def update_monitoring_settings(payload: dict, request: Request):
    """Global bildirim ayarlarını güncelle — YALNIZ admin.

    Admin tarafından yapılan değişiklik tüm kullanıcıları ve arka plan
    döngüsünü anında etkiler (kullanıcı-başı ayar kaldırıldı, 2026-09-04).
    """
    from app.main import _require_admin
    _require_admin(request)
    settings = {
        "enabled": bool(payload.get("enabled", True)),
        "min_score": float(payload.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT)),
        "min_target_pct": float(payload.get("min_target_pct", 2.0)),
        "quiet_hours_start": payload.get("quiet_hours_start", None),
        "quiet_hours_end": payload.get("quiet_hours_end", None),
    }
    await database.set_llm_setting("monitoring_notification_settings", json.dumps(settings))
    await log_user_action(None, None, "monitoring", "MONITORING_SETTINGS_UPDATE",
                          details={"settings": {k: v for k, v in settings.items() if k != "enabled"},
                                   "scope": "global_admin"},
                          request=request)
    return {"paper_only": True, "ok": True, "scope": "global_admin", **settings}


def _build_notification(sym, c, settings) -> dict:
    """Zengin bildirim içeriği: sembol, tespit zamanı, %potansiyel, anlık ve beklenen fiyat."""
    score = normalize_score(c.get("velocity_score", 0))
    target = float(c.get("target_pct", 2.0) or 0)
    price = float(c.get("price", 0) or 0)
    ticker = market.get_ticker(sym)
    current_price = float(ticker.get("last_price", price)) if ticker else price
    if current_price <= 0:
        current_price = price
    expected_price = current_price * (1 + target / 100) if current_price > 0 else 0.0
    detected_at = time.time()
    horizon = int(c.get("horizon_minutes", 5) or 5)
    ml_prob = c.get("ml_hit_probability")
    ml_pct_str = f" | ML %{ml_prob * 100:.0f}" if ml_prob is not None else ""
    message = (
        f"🎯 {sym} | Skor: {score:.1f} | Potansiyel: +%{target:g} ({horizon}dk){ml_pct_str} | "
        f"Anlık: {current_price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"
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
        "price": current_price,
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
    # Etkin eşik: admin min_score + RISK_OFF rejim çarpanı (ayarı bozmadan
    # riskli piyasada daha seçici davranır).
    min_score = float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))
    if _monitoring_state.get("risk_off"):
        min_score *= float(config.MONITORING_RISK_OFF_SCORE_MULT)
    quiet = _in_quiet_hours(settings)
    now = time.time()
    notified = []
    update_entries = []  # Güncellenecek mevcut bildirimler
    new_entries = []     # Yeni bildirimler
    for c in candidates_list:
        sym = str(c.get("symbol", "") or "").upper()
        # Eşik ve fast-lane PANEL (0-100) skoru üzerinden: admin min_score/fast_lane
        # 0-100 ölçekte kurgulanmış. Ham velocity_score 0-200+ aralığında olduğundan
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
        existing_pending = await database.get_pending_monitoring_notification(sym)
        if existing_pending and (
            now - float(existing_pending.get("detected_at") or 0)
            < (int(existing_pending.get("horizon_minutes") or horizon_min) + 2) * 60
        ):
            # Mevcut BEKLIYOR bildirimi guncelle (detected_at korunur); ML alanlari
            # da guncellenir (aksi halde guncelleme yolunda kaybolurdu, 2026-09-04).
            await database.update_monitoring_notification(
                existing_pending["id"],
                score=score,
                target_pct=target,
                price=float(c.get("price", 0) or 0),
                expected_price=float(c.get("price", 0) or 0) * (1 + target / 100),
                horizon_minutes=horizon_min,
                mode=c.get("mode"),
                ml_target_pct=c.get("ml_target_pct"),
                ml_hit_probability=c.get("ml_hit_probability"),
            )
            # Eski kayitlar kalir - sinyal tarihcesi icin
            # Bildirim olarak da ekle (push için)
            notif = _build_notification(sym, c, settings)
            notif["id"] = existing_pending["id"]
            notif["updated"] = True
            update_entries.append(notif)
            notified.append(notif)
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
    # Yeni bildirimleri DB'ye kaydet
    if new_entries:
        await database.save_monitoring_notifications(new_entries)
    # Sessiz saat bilgisi bildirim nesnesine işaretlenir (UI geçmişte görür).
    for n in notified:
        n["quiet_hours"] = bool(quiet)
    # Push bildirimleri — sadece YENI bildirimler (guncellemeler her turda
    # tetiklenmesin diye spam korumasi)
    new_notifs = [n for n in notified if not n.get("updated")]
    if new_notifs and not quiet:
        for notif in new_notifs:
            try:
                await deliver_web_push(
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
            except Exception as exc:
                logger.warning("Monitoring push failed for %s: %s", notif["symbol"], exc)
    elif new_notifs and quiet:
        logger.info("Monitoring: sessiz saatlerde %d bildirim ertelendi (push yok)", len(new_notifs))
    if new_notifs:
        try:
            await ws_manager.broadcast({"type": "monitoring_alert", "data": new_notifs[-1]})
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
                     "rsi": r.get("rsi"), "mfi": r.get("mfi"), "atr_pct": r.get("atr_pct"),
                     "m5_pattern_ok": r.get("m5_pattern_ok"), "leading_ok": r.get("leading_ok")}
            for h, r in profs.items()
        }
        row["upside_rank"] = round(upside_rank_score(row, touch_rates), 2)
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
    # Pahalı snapshot taraması çağrılmaz; fail-open: hesaplanamazsa normal eşik.
    # Yorum (2026-09-04): risk_off=True => piyasa riskli kabul edilir ve _notify
    # etkin eşiği RISK_OFF_SCORE_MULT ile yükseltir (riskliyken daha seçici).
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

    candidates_list = sorted(filtered_candidates.values(), key=lambda x: x.get("upside_rank", 0), reverse=True)
    watchlist_list = sorted(all_watchlist.values(), key=lambda x: x.get("upside_rank", 0), reverse=True)

    # Bu turdaki aday kümesi: eşik altında kalan sembollerin debounce sayacı sıfırlanır
    current_candidate_syms = set(filtered_candidates)
    for sym in list(_monitoring_state["candidate_streak"]):
        if sym not in current_candidate_syms:
            _monitoring_state["candidate_streak"].pop(sym, None)

    # Beklenen fiyata ulaşan veya süresi dolan sembolleri serbest bırak
    _check_pending_targets()

    settings = await get_user_notification_settings()
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
async def monitoring_scan():
    """Run a fresh scan for 5m and 15m velocity candidates (manual/UI tetiklemeli)."""
    try:
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
            "loop_active": _loop_task is not None and not _loop_task.done(),
        }
    except Exception as exc:
        logger.exception("Monitoring scan failed: %s", exc)
        return {"paper_only": True, "error": str(exc), "candidates": [], "watchlist": []}


@router.get("/api/monitoring/state")
async def monitoring_state():
    """Get current monitoring state (last scan results + notification history)."""
    settings = await get_user_notification_settings()
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
        "loop_active": _loop_task is not None and not _loop_task.done(),
        "next_scan_in_sec": None,
    }


@router.get("/api/reports/notifications")
async def report_notifications(limit: int = 200, day: str = None):
    """Radar bildirim raporu - gercek kapannis M1 olcmueye dayali basari.
    day: YYYY-MM-DD formatinda gun filtresi (opsiyonel).

    Global admin eşiği (min_score) altındaki bildirimler NE gösterilir NE
    başarı hesabına katılır (2026-09-04 kullanıcı kararı) — düşük skorlu
    gürültü başarı oranını yanıltmasın.
    """
    limit = max(1, min(int(limit), 500))
    settings = await get_user_notification_settings()
    min_score = float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))
    rows = await database.get_monitoring_velocity_matches(limit=limit, day=day)
    # Eşik filtresi: skor alanı bildirim anındaki panel (0-100) skorudur.
    # 2026-09-04 teşhisi öncesi eski kayıtlar ham velocity_score ile yazılmıştı
    # (çok daha düşük); normalize_score her iki ölçeği aynı panele oturtur —
    # aksi halde eski gürültü/eşik tutarsızlığı oluşur.
    rows = [r for r in rows
            if normalize_score(r.get("score")) >= min_score]
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
            "score": row.get("score"),
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
    # eski kayıtlar için normalize_score uygulanır (bkz. günlük filtre).
    all_rows = [r for r in all_rows if normalize_score(r.get("score")) >= min_score]
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

@router.post("/api/monitoring/reset-notifications")
async def reset_monitoring_notifications(request: Request):
    """Clear notified symbols list (allows re-notification) — YALNIZ admin.

    Reset sonrasi ayni semboller yeniden bildirilebilir; spam korumasini
    atlatabilmek isteyen her kimlik yetkili olmamalidir (2026-09-04).
    """
    from app.main import _require_admin
    _require_admin(request)
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
    logger.info("Monitoring arka plan taraması başladı (tur=%ss, izleme=%ss)", SCAN_INTERVAL_SEC, WATCHLIST_RESCAN_SEC)
    await restore_runtime_state()
    # Başlangıçta market verisi hazır olsun diye ilk tura küçük gecikme
    await asyncio.sleep(20)
    while True:
        try:
            await _run_scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring loop turu başarısız: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL_SEC)
            continue
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def start_monitoring_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat (idempotent)."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(monitoring_background_loop(), name="monitoring-scan-loop")
    return True


def stop_monitoring_loop():
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _loop_task = None