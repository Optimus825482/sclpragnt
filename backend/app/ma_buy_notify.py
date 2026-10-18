"""MA şerit BUY sinyali → kullanıcıya push (TF etiketli) + otonom paper (2026-10-18, kullanıcı isteği).

`ma_buy_tracker` yeni kapanan M1/M5 mumunda grafikteki BUY rozetiyle aynı kuralı (EMA7/20/99 kesişimi) bulunca
`deliver()` çağrılır. Akış radar bildirimiyle aynı kanallardan geçer:
  * push (`monitoring._send_push`): başlıkta "MA BUY (M1)" / "(M5)"; service worker'daki "Alım yap" aksiyonu da çalışır.
  * WS `monitoring_alert`: uygulama açıksa radar modalı aynı şekilde gösterir.
  * otonom paper (`auto_paper.try_open_from_notification`): zarf `sent_via_push` taşır; push GİTMEDİYSE paper açılmaz
    (AUTO_PAPER_ONLY_ON_PUSH kararı). Skor/mod kapısı yerine `MA_BUY_AUTO_PAPER_ENABLED` geçerlidir
    (`auto_paper._rule_signal_gate`); likidite, korelasyon, sessiz saat, dedup vb. tüm diğer kapılar aynen uygulanır.

Kayıt `monitoring_notifications`'a YAZILMAZ: o tablo radar skor/hedef raporlarını besler. Kanıt `ma_buy_signals`
satırındadır (`notified_at`, `push_ok`, `paper_status`, `paper_trade_id`; migration 027).
Bildirim politikası (≥2 kaynak teyit kuralı) MA push'unu KESMEZ — kullanıcı bu sinyali açıkça istedi; genel bildirim
anahtarı ve sessiz saat ise uygulanır. Aynı sembolde `MA_BUY_NOTIFY_COOLDOWN_MIN` içinde ikinci push yok (TF'ler ortak).
"""
from __future__ import annotations

import logging
import time

from app import database, ma_buy_signals
from app.config import config

logger = logging.getLogger("scalper.ma_buy")

SOURCE = "ma_buy"
HORIZON_MIN = 15
_last_push: dict[str, float] = {}   # sembol → son başarılı MA push zamanı (cooldown)


def enabled() -> bool:
    return bool(getattr(config, "MA_BUY_NOTIFY_ENABLED", True))


def notify_timeframes() -> set[str]:
    raw = str(getattr(config, "MA_BUY_NOTIFY_TIMEFRAMES", "1m,5m") or "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def target_pct(tf: str) -> float:
    """TF'ye göre paper TP hedefi (`MA_BUY_TARGET_PCT` = "1m:1.0,5m:1.5"); tanımsızsa otonom varsayılan hedef."""
    for part in str(getattr(config, "MA_BUY_TARGET_PCT", "") or "").split(","):
        key, _, val = part.partition(":")
        if key.strip() == tf:
            try:
                v = float(val)
            except ValueError:
                break
            if v > 0:
                return v
    return float(getattr(config, "AUTO_PAPER_DEFAULT_TARGET_PCT", 1.5))


def _tf_minutes(tf) -> int:
    t = str(tf or "")
    return int(t[:-1]) if t.endswith("m") and t[:-1].isdigit() else 0


def tf_label(tf: str) -> str:
    return "M" + tf[:-1] if tf.endswith("m") else tf.upper()


def rules_text(rules: str, periods: tuple) -> str:
    fast, mid, slow = periods
    names = {
        ma_buy_signals.RULE_FAST_CROSS_MID: f"EMA{fast} ↗ EMA{mid}",
        ma_buy_signals.RULE_MID_CROSS_SLOW: f"EMA{mid} ↗ EMA{slow}",
    }
    parts = [names.get(r.strip(), r.strip()) for r in str(rules or "").split(",") if r.strip()]
    return " + ".join(parts) or "MA kesişimi"


def is_fresh(row: dict, now_ms: int) -> bool:
    """Yalnız az önce kapanan mumun sinyali bildirilir (geriye dönük `lookback` tekrarları ve bayat sinyal değil)."""
    max_age_ms = float(getattr(config, "MA_BUY_NOTIFY_MAX_AGE_SEC", 90)) * 1000
    return 0 <= now_ms - int(row.get("bar_close_ms") or 0) <= max_age_ms


def build_notification(row: dict, periods: tuple, now: float | None = None) -> dict:
    """Sinyal satırını push + otonom paper zarfına çevirir (radar zarfıyla aynı alan adları)."""
    now = time.time() if now is None else now
    sym = str(row["symbol"]).upper()
    tf = str(row.get("timeframe") or "5m")
    label = tf_label(tf)
    price = float(row["signal_price"])
    target = target_pct(tf)
    expected = price * (1 + target / 100)
    cross = rules_text(row.get("rules") or "", periods)
    return {
        "symbol": sym,
        "timeframe": tf,
        "rules": row.get("rules"),
        "title": f"📈 {sym} · MA BUY ({label})",
        "message": f"{sym} | {label} grafikte BUY sinyali: {cross} | Anlık: {price:.6f} TRY | Hedef: +%{target:g}",
        "url": f"/charts?symbol={sym}&timeframe={tf}",
        "tag": f"ma-buy-{sym}",
        "detected_at": now,
        "price": price,
        "target_pct": target,
        "expected_price": expected,
        "horizon_minutes": HORIZON_MIN,
        "mode": SOURCE,
        "source": SOURCE,
        # Otonom paper churn koruması: aynı sinyal mumu için TEK giriş.
        "notification_key": f"ma-{tf}-{sym}-{int(row['bar_open_ms'])}",
        "updated": False,
        "sent_via_push": False,
    }


def _in_cooldown(sym: str, now: float) -> bool:
    cd = float(getattr(config, "MA_BUY_NOTIFY_COOLDOWN_MIN", 15) or 0) * 60
    return cd > 0 and now - _last_push.get(sym, 0.0) < cd


async def _open_paper(notif: dict, signal_id: int) -> None:
    if not getattr(config, "MA_BUY_AUTO_PAPER_ENABLED", True) or not notif.get("sent_via_push"):
        return
    try:
        from app.routers.auto_paper import try_open_from_notification
        res = await try_open_from_notification(notif)
    except Exception as exc:  # noqa: BLE001 — paper hatası bildirimi bozmaz
        logger.warning("MA BUY otonom paper %s: %s", notif.get("symbol"), exc)
        await database.mark_ma_buy_delivery(signal_id, paper_status="hata")
        return
    res = res if isinstance(res, dict) else {}
    trade_id = res.get("trade_id")
    status = "acildi" if trade_id else str(res.get("reason") or res.get("status") or "denenmedi")
    await database.mark_ma_buy_delivery(signal_id, paper_status=status,
                                        paper_trade_id=int(trade_id) if trade_id else None)


async def deliver(rows: list[dict], periods: tuple, now_ms: int | None = None) -> int:
    """Yeni MA BUY sinyallerini push et ve otonom paper dene. Dönüş: başarılı push sayısı.

    MUTLAKA tarama semaforları DIŞINDA çağrılır (push ağ I/O'su + paper DB işi)."""
    if not enabled() or not rows:
        return 0
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    tfs = notify_timeframes()
    fresh = [r for r in rows if r.get("timeframe") in tfs and is_fresh(r, now_ms)]
    if not fresh:
        return 0
    from app.routers import monitoring  # geç import: monitoring büyük ve döngüsel bağımlı
    settings = await monitoring.get_user_notification_settings()
    if not settings.get("enabled", True):
        return 0
    if monitoring._in_quiet_hours(settings):
        logger.info("MA BUY: sessiz saat — %d sinyal push edilmedi (paper da sessiz saatte açılmaz)", len(fresh))
        return 0
    if not monitoring._vapid_configured():
        logger.info("MA BUY: VAPID yok — %d sinyal push edilmedi (paper push şartıyla açılmaz)", len(fresh))
        return 0
    pushed: list[dict] = []
    # Aynı turda aynı sembol M1 ve M5'te birlikte tetiklendiyse büyük TF önce (daha az gürültülü), tek push.
    for row in sorted(fresh, key=lambda r: -_tf_minutes(r.get("timeframe"))):
        sym = str(row["symbol"]).upper()
        now = time.time()
        if _in_cooldown(sym, now):
            continue
        signal_id = await database.claim_ma_buy_notify(sym, row["timeframe"], row["bar_open_ms"])
        if signal_id is None:
            continue  # bu mum zaten bildirildi (yeniden başlatma / çift tur)
        notif = build_notification(row, periods, now)
        ok = await monitoring._send_push(notif)
        notif["push_success"] = ok
        notif["push_attempted"] = True
        notif["sent_via_push"] = bool(ok)
        await database.mark_ma_buy_delivery(signal_id, push_ok=bool(ok))
        if ok:
            _last_push[sym] = now
            pushed.append(notif)
            logger.info("MA BUY push gönderildi: %s %s (%s)", sym, row["timeframe"], row.get("rules"))
        await _open_paper(notif, signal_id)
    if pushed:
        try:
            await monitoring.ws_manager.broadcast({"type": "monitoring_alert", "data": pushed})
        except Exception as exc:  # noqa: BLE001
            logger.warning("MA BUY WS yayını hatası: %s", exc)
    return len(pushed)
