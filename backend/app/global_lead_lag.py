"""Global erken-tespit → TR bildirimi + TR otonom paper işlem (2026-10-07).

NEDEN BU MODÜL VAR:
    v4 (Binance TR) öncü sinyalleri eskiden AYRI bir dağıtımdan
    (`D:\\scalperagent_global`) HTTP köprüsüyle alıyordu. Global piyasa TR'den
    daha likit olduğu için aynı hareket orada DAHA ERKEN belirir; köprü ağ
    atlaması ve harici bağımlılık getiriyordu. Artık Global taraması v4'ün
    İÇİNDE (`app/routers/global_radar.py` + `state.global_market`) çalışır ve
    bu modül onun çıktısını eskisiyle AYNI TR hattına bağlar:
    TR bildirimi (`monitoring_notifications`) + TR otonom paper pozisyonu
    (`analyzer.open_position(strat_name="GLOBAL_LEAD_LAG")`).

KULLANICI DİREKTİFİ (bağlayıcı):
    * Bu bir İKİNCİ VENUE DEĞİLDİR. Terminal fiyat ve sembol HER ZAMAN TR'dir
      (`BTCUSDT` → `BTCTRY`); PnL TRY cinsindendir.
    * Arayüzde Global'e dair HİÇBİR şey görünmez. Bildirim başlığı/mesajı sıradan
      bir TR bildirimi gibidir; `alertKind`/`source` TR varsayılanıdır.
    * Global tarama SALT OKUNUR. Gerçek emir yolu açılmaz; bu modül yalnız
      paper pozisyon açar (`analyzer`), gerçek emir göndermez.

İÇSEL İZ:
    Öğrenme/kalite analizi ve çift-tetikleme denetimi için kaynak işareti
    `strategy = "GLOBAL_LEAD_LAG"` ve `entry_context.source = "global_scan"`
    olarak saklanır. Bu DB alanlarıdır; UI'da gösterilmez (bkz. plan aşama 4).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from app.config import config
from app.binance_tr_symbols import is_binance_tr_symbol, map_to_tr_symbol

logger = logging.getLogger("scalper.global_lead_lag")

# Günlük zarar kapısı `app/main.py`'de tanımlı; buradan import etmek döngüsel
# import yaratır. Köprüyle (`tr_bridge_receiver.set_daily_loss_guard_fn`) AYNI
# desen: fonksiyon açılışta enjekte edilir. Enjekte edilmezse kapı uygulanmaz
# (yalnız paper işlem; gerçek emir yolu zaten yok).
_daily_loss_guard_fn: Callable[[], Any] | None = None


def set_daily_loss_guard_fn(fn: Callable[[], Any] | None) -> None:
    global _daily_loss_guard_fn
    _daily_loss_guard_fn = fn

# Strateji etiketi mevcut köprüyle AYNI tutulur: eski köprü kayıtları ve yeni
# yerel tarama aynı kalite/öğrenme raporunda toplanır.
GLOBAL_SIGNAL_STRATEGY = "GLOBAL_LEAD_LAG"

# (tr_symbol, signal_type) → son işlendiği epoch. Global taraması TR'nin kendi
# taramasıyla AYNI sembolü işaret edebilir; cooldown çift bildirimi engeller.
_recent: dict[tuple[str, str], float] = {}
_COOLDOWN_SEC = 900.0  # 15 dk — ufuk ile aynı ölçek
# TR taramasının kendi bildirimiyle çakışma penceresi. TR turu 60 sn'de bir
# döner; 5 dk, aynı sembolün iki kez bildirilmesini güvenle bastırır, gerçek bir
# yeni hareketi (5 dk sonra) engellemez.
_TR_NOTIFICATION_DEDUP_SEC = 300.0


def _cooldown_ok(tr_symbol: str, signal_type: str, now: float) -> bool:
    key = (str(tr_symbol or "").upper(), str(signal_type or ""))
    last = _recent.get(key)
    if last is not None and (now - last) < _COOLDOWN_SEC:
        return False
    _recent[key] = now
    # Sözlük sınırsız büyümesin: cooldown'ı geçmiş anahtarları buda.
    if len(_recent) > 2000:
        for old_key in [k for k, ts in _recent.items() if (now - ts) > _COOLDOWN_SEC]:
            _recent.pop(old_key, None)
    return True


def reset_cooldowns() -> None:
    """Test/teşhis için cooldown durumunu temizle."""
    _recent.clear()


async def handle_global_detection(detection: dict[str, Any]) -> dict[str, Any]:
    """Global tespitini TR bildirimi + TR otonom paper işlemine çevir.

    ``detection`` alanları (global_radar üretir):
        global_symbol: "BTCUSDT"
        signal_type:   "velocity" | "rising" | ...
        score:         float (0-100 panel skoru)
        target_pct:    float (yüzde; ör. 2.0)
        horizon_minutes: int
        mode / atr_pct / price: teşhis alanları (opsiyonel)

    Dönüş: ``{"status": ..., ...}`` — sessizce yutmaz, nedeni taşır.
    """
    from app.state import market, analyzer
    from app import database

    global_symbol = str(detection.get("global_symbol") or "").strip().upper()
    if not global_symbol:
        return {"status": "rejected", "reason": "missing_global_symbol"}

    # 1) TR'de listeli mi? Değilse TR'de fiyat/işlem yok → sinyal üretilmez.
    if not is_binance_tr_symbol(global_symbol):
        return {"status": "rejected", "reason": "not_listed_on_tr",
                "global_symbol": global_symbol}

    tr_symbol = map_to_tr_symbol(global_symbol)
    signal_type = str(detection.get("signal_type") or "velocity")
    now = time.time()

    # 2) Çift tetikleme: TR taraması da aynı sembolü görebilir.
    if not _cooldown_ok(tr_symbol, signal_type, now):
        return {"status": "cooldown", "tr_symbol": tr_symbol,
                "signal_type": signal_type}

    # 3) TR fiyatı — terminal fiyat DAİMA TR'dir (lead-lag).
    tr_price = 0.0
    try:
        ticker = market.get_ticker(tr_symbol) or {}
        tr_price = float(ticker.get("last_price") or 0)
    except Exception as exc:
        logger.debug("global_lead_lag: TR ticker okunamadı (%s): %s", tr_symbol, exc)
    if tr_price <= 0:
        try:
            rows = await market.adapter.ticker_price([tr_symbol])
            row = next((r for r in rows if str(r.get("symbol", "")).upper() == tr_symbol), None)
            tr_price = float((row or {}).get("price") or 0)
        except Exception as exc:
            logger.debug("global_lead_lag: TR REST fiyat hatası (%s): %s", tr_symbol, exc)
    if tr_price <= 0:
        return {"status": "rejected", "reason": "no_tr_price", "tr_symbol": tr_symbol}

    score = float(detection.get("score") or 0.0)
    target_pct = float(detection.get("target_pct") or 2.0)
    horizon_minutes = int(detection.get("horizon_minutes") or 15)
    expected_price = round(tr_price * (1.0 + target_pct / 100.0), 6)

    # 3b) TR az önce AYNI sembol için bildirim ürettiyse Global tespiti bildirim
    #     ÜRETMEZ (origin ne olursa olsun kullanıcı TEK bildirim görmeli).
    #     Otonom işlem yine de denenir — `analyzer.positions` zaten açık
    #     pozisyonu reddeder, yani aynı harekete İKİ pozisyon açılmaz.
    try:
        if await database.has_recent_monitoring_notification(tr_symbol, _TR_NOTIFICATION_DEDUP_SEC):
            logger.debug("global_lead_lag: %s için taze TR bildirimi var → "
                         "bildirim atlandı (otonom işlem denenir)", tr_symbol)
            trade = await _open_tr_paper_trade(
                analyzer, tr_symbol, tr_price, target_pct, horizon_minutes, detection, score)
            return {"status": "dedup_tr_notification", "tr_symbol": tr_symbol,
                    "trade": trade}
    except Exception as exc:
        logger.debug("global_lead_lag: TR bildirim dedup kontrolü hatası (%s): %s",
                     tr_symbol, exc)

    # 4) TR bildirimi — görünümü sıradan TR sinyalinden FARKSIZ (kullanıcı
    #    direktifi). `sources` normal TR etiketi taşır; Global izi yalnız
    #    içsel `strategy` alanında tutulur.
    notif_entry = {
        "symbol": tr_symbol,
        "title": f"🎯 {tr_symbol} +%{target_pct:g} potansiyel",
        "message": (f"🎯 {tr_symbol} | Skor: {score:.1f} | "
                    f"Potansiyel: +%{target_pct:g} ({horizon_minutes}dk) | "
                    f"Anlık: {tr_price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"),
        "score": score,
        "target_pct": target_pct,
        "price": tr_price,
        "expected_price": expected_price,
        "horizon_minutes": horizon_minutes,
        "mode": detection.get("mode"),
        "detected_at": now,
        "sent_via_push": False,
        "sources": ["velocity"],
        "unified": True,
        "url": f"/charts?symbol={tr_symbol}",
        "tag": f"monitoring-{tr_symbol}",
    }
    try:
        await database.save_monitoring_notifications([notif_entry])
    except Exception as exc:
        logger.error("global_lead_lag: bildirim kaydı başarısız (%s): %s", tr_symbol, exc)

    # 5) Arayüze yayın — TR bildirimi zarfı, Global alanı YOK.
    try:
        from app.ws_runtime import ws_manager
        await ws_manager.broadcast({
            "type": "monitoring_alert",
            "data": [dict(notif_entry)],
        })
    except Exception as exc:
        logger.debug("global_lead_lag: WS yayını hatası: %s", exc)

    # 6) Web push — mevcut TR hattının aynı yardımcısı.
    try:
        from app.routers.monitoring import _send_push
        push_ok = await _send_push(notif_entry)
        if push_ok and notif_entry.get("id"):
            await database.mark_monitoring_push_sent(notif_entry["id"])
    except Exception as exc:
        logger.debug("global_lead_lag: web push hatası: %s", exc)

    # 7) Otonom paper işlem — TR sembolü, TR fiyatı, TRY.
    trade_outcome = await _open_tr_paper_trade(
        analyzer, tr_symbol, tr_price, target_pct, horizon_minutes, detection, score)
    return {"status": "processed", "tr_symbol": tr_symbol,
            "global_symbol": global_symbol, "trade": trade_outcome}


async def _open_tr_paper_trade(analyzer, tr_symbol: str, tr_price: float,
                               target_pct: float, horizon_minutes: int,
                               detection: dict, score: float) -> dict:
    """TR otonom paper pozisyonu aç (analzer.positions defteri).

    Kapılar köprüyle aynıdır: günlük zarar koruması, zaten açık pozisyon,
    maksimum açık pozisyon. Gerçek emir YOLU YOKTUR — yalnız paper.
    """
    if analyzer is None:
        return {"status": "skipped", "reason": "no_analyzer"}
    if tr_symbol in analyzer.positions:
        return {"status": "already_open"}

    # Günlük zarar koruması (enjekte edilmişse) — köprü de aynı kapıyı uygular.
    if _daily_loss_guard_fn is not None:
        try:
            guard = await _daily_loss_guard_fn()
            if guard and guard.get("halt"):
                return {"status": "blocked",
                        "reason": f"daily_loss_guard:{guard.get('reason')}"}
        except Exception as exc:
            logger.warning("global_lead_lag: risk kapısı hatası: %s", exc)

    max_positions = int(getattr(config, "MAX_OPEN_POSITIONS", 5) or 5)
    if max_positions > 0 and len(analyzer.positions) >= max_positions:
        return {"status": "blocked", "reason": "max_open_positions_reached"}

    stop_loss_pct = float(getattr(config, "HARD_STOP_LOSS_PCT", 3.0) or 3.0)
    take_profit_pct = max(0.005, target_pct / 100.0)
    max_hold_sec = max(180, int(horizon_minutes * 60))

    entry_context_extra = {
        "source": "global_scan",
        "global_symbol": detection.get("global_symbol"),
        "signal_type": detection.get("signal_type"),
        "score": score,
        "target_pct": target_pct,
        "horizon_minutes": horizon_minutes,
        "signal_context": {"no_initial_stop": False},
    }
    try:
        res = await analyzer.open_position(
            symbol=tr_symbol,
            entry_price=tr_price,
            side="LONG",
            strat_name=GLOBAL_SIGNAL_STRATEGY,
            order_value=None,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            max_hold_sec=max_hold_sec,
            entry_context_extra=entry_context_extra,
        )
    except Exception as exc:
        logger.error("global_lead_lag: open_position hatası (%s): %s", tr_symbol, exc)
        return {"status": "error", "reason": str(exc)}

    if res and str(res.get("action") or "").upper() == "BUY_SIGNAL":
        logger.info("global_lead_lag: %s için TR paper pozisyonu açıldı "
                    "(trade_id=%s, fiyat=%.4f, kaynak=%s)",
                    tr_symbol, res.get("trade_id"), tr_price, detection.get("global_symbol"))
        return {"status": "opened", "trade_id": res.get("trade_id"),
                "entry_price": tr_price, "target_pct": target_pct}
    return {"status": "blocked",
            "reason": (res or {}).get("reason", "risk_or_liquidity_gate")}
