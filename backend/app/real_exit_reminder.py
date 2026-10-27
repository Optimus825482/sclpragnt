"""Gerçek Binance TR pozisyonu için "çıkış zamanı geldi" push hatırlatıcısı (2026-10-27, Task 7).

Bildirim planından açılmış (order_requests DONE, result.exit_at dolu) pozisyonlar için:
  aşama 1: now >= exit_at            → "→ çık" (net ≥ 0) ya da "→ stop'a kadar bekle"
  aşama 2: now >= exit_at + grace dk → her zaman "→ çık" (grace 0/None ise aşama 2 yok)
Her aşama bir kez (`database.mark_exit_reminder` atomik). OCO tetiklendiyse veya coin bakiyesi
< executed_qty × 0.5 ise push yok, satır "kapali" işaretlenir. Kapanış YALNIZ bakiyeden anlaşılır (koordinatör
kararı): OCO'yu iptal edip coini tutan kullanıcı yine hatırlatılır; açık emir listesinde orderListId olmasa da
korumalı pozisyonlar susturulmaz.

GÜVENLİK: bu modül HİÇBİR EMİR göndermez / iptal etmez / değiştirmez. Borsaya yalnız SALT OKUNUR
çağrılar (bakiye, fiyat) yapılır; tek yan etki push ve hatırlatma işaretidir.

Push yolu: `alerting.deliver_web_push(..., usernames=[sahip])` — `monitoring._send_push` TÜM abonelere
yayın yapar ve günlük "sembol başına 1 push" sayacına takılır; gerçek pozisyon bilgisi yalnız sahibine gider.
Global bildirim ayarı (`enabled`) ve sessiz saat diğer push yollarıyla aynı şekilde uygulanır: kapalıysa
veya sessiz saatteyse tur atlanır, aşama İŞARETLENMEZ (sessiz saat bitince gönderilir; o arada ek süre de
dolduysa yalnız aşama 2 gider).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import alerting, database, notification_plan

logger = logging.getLogger(__name__)

LOOP_INTERVAL_SEC = 60
STARTUP_DELAY_SEC = 90
SOLD_FRACTION = 0.5
STAGE_KEYS = database.EXIT_REMINDER_STAGE_KEYS
WARN_DEBOUNCE_SEC = 3600
# Kalıcı push başarısızlıkları: yeniden denemek anlamsız (aşama geri bırakılmaz).
PERMANENT_PUSH_REASONS = {"vapid_not_configured", "no_subscriptions"}
_last_warn: dict[tuple[int, str], float] = {}
_no_keys_logged: set[int] = set()


def _fee_frac() -> float:
    from app.config import config
    return float(config.effective_commission_pct())


async def _exchange_for_user(user_id: int):
    """(borsa adaptörü, kullanıcı adı) ya da None. Anahtar çözümü `_user_binance_creds_quiet` ile aynı yol."""
    from app import main
    from app.routers.binance_trade import _exchange_for
    user = await database.get_user_by_id(int(user_id))
    if not user:
        return None
    creds = await main._user_binance_creds_quiet(user)
    if not creds:
        return None
    return _exchange_for(*creds), str(user.get("username") or "").strip()


async def _position_closed(ex, symbol_u: str, result: dict) -> bool:
    """True: coin elden çıkmış (free+locked < executed_qty × 0.5; OCO dolduysa da bakiye düşer).
    Borsa okuma hatası yükselir (çağıran atlar)."""
    free, locked = await ex.asset_balance(symbol_u.split("_")[0])
    return float(free) + float(locked) < float(result.get("executed_qty") or 0) * SOLD_FRACTION


def _warn_debounced(user_id: int, cid: str, now: float, msg: str, *args) -> None:
    """Satır başına saatte en fazla bir uyarı (borsa kesintisinde her dakika log basmasın)."""
    key = (user_id, cid)
    if now - _last_warn.get(key, 0.0) >= WARN_DEBOUNCE_SEC:
        _last_warn[key] = now
        logger.warning(msg, *args)


def _push_failure_permanent(res: dict) -> bool:
    reason = res.get("reason")
    if reason in PERMANENT_PUSH_REASONS:
        return True
    return "error" not in res and int(res.get("total") or 0) == 0   # alıcının aboneliği yok


def _due_stage(result: dict, now: float) -> str | None:
    rem = result.get("exit_reminder") or {}
    exit_at = float(result["exit_at"])
    grace = float(result.get("grace_minutes") or 0)
    if rem.get("closed") or rem.get("stage2_at") or now < exit_at:
        return None
    if grace > 0 and now >= exit_at + grace * 60:
        return "stage2"
    if not rem.get("stage1_at"):
        return "stage1"
    return None


def _message(sym: str, net_pct: float, advice: str | None) -> str:
    tail = "çık" if advice == "cik" else "stop'a kadar bekle"
    return f"{sym} çıkış zamanı geldi: şu an {net_pct:+.1f}% net → {tail}"


async def _notifications_allowed() -> bool:
    from app.routers import monitoring
    settings = await monitoring.get_user_notification_settings()
    if not settings.get("enabled", True):
        return False
    if monitoring._in_quiet_hours(settings):
        logger.info("çıkış hatırlatıcısı: sessiz saat — tur ertelendi")
        return False
    return bool(monitoring._vapid_configured())


async def _handle_row(row: dict, now: float, fee: float, exchanges: dict) -> int:
    result = row.get("result") or {}
    user_id, cid = int(row["user_id"]), str(row["client_order_id"])
    try:
        stage = _due_stage(result, now)
    except (KeyError, TypeError, ValueError):
        return 0
    if stage is None:
        return 0
    symbol_u = str(result.get("symbol") or row.get("symbol") or "").upper()
    try:
        entry = float(result.get("avg_price") or 0)
    except (TypeError, ValueError):
        entry = 0.0
    if not symbol_u or "_" not in symbol_u or entry <= 0:
        return 0

    if user_id not in exchanges:
        exchanges[user_id] = await _exchange_for_user(user_id)
    found = exchanges[user_id]
    if not found or not found[1]:
        # anahtar/kullanıcı adı yok: hedefsiz push asla (usernames boşsa herkese giderdi)
        if user_id not in _no_keys_logged:
            _no_keys_logged.add(user_id)
            logger.debug("çıkış hatırlatıcısı: kullanıcı %s için anahtar/kullanıcı adı yok", user_id)
        return 0
    ex, username = found
    try:
        if await _position_closed(ex, symbol_u, result):
            await database.mark_exit_reminder(user_id, cid, "kapali")
            return 0
        last = await ex.price(symbol_u)
    except Exception as exc:  # noqa: BLE001 — borsa okuma hatası: bu tur atla, işaretleme
        _warn_debounced(user_id, cid, now, "çıkış hatırlatıcısı: borsa okunamadı (%s %s): %s",
                        symbol_u, cid, type(exc).__name__)
        return 0
    if not last or float(last) <= 0:
        _warn_debounced(user_id, cid, now, "çıkış hatırlatıcısı: fiyat yok (%s %s)", symbol_u, cid)
        return 0
    _last_warn.pop((user_id, cid), None)

    last = float(last)
    net_pct = (last * (1 - fee) / (entry * (1 + fee)) - 1) * 100
    if stage == "stage2":
        advice = "cik"
    else:
        plan_like = {"exit_at": result["exit_at"], "grace_minutes": result.get("grace_minutes") or 0}
        advice = notification_plan.exit_advice(plan_like, entry, last, now, fee)

    if not await database.mark_exit_reminder(user_id, cid, stage):
        return 0          # başka işçi bu aşamayı zaten aldı
    if stage == "stage2" and not (result.get("exit_reminder") or {}).get("stage1_at"):
        await database.mark_exit_reminder(user_id, cid, "stage1")   # kaçırılan aşama 1 ayrıca gönderilmez

    sym = symbol_u.replace("_", "")
    res = await alerting.deliver_web_push(
        _message(sym, net_pct, advice), title="Çıkış zamanı", url="/binance-tr", tag=f"exit-{sym}-{cid}",
        # plan_key YOK: SW bu kaynakta "Alım yap" göstermez (hatırlatıcı alım değil, çıkış uyarısıdır).
        extra={"source": "real_exit_reminder", "symbol": symbol_u, "stage": stage},
        usernames=[username])
    res = res or {}
    if not res.get("ok"):
        permanent = _push_failure_permanent(res)
        logger.warning("çıkış hatırlatıcısı push gönderilemedi (%s %s, %s): %s", symbol_u, stage,
                       "kalıcı" if permanent else "yeniden denenecek", res.get("reason") or res.get("error"))
        if not permanent:
            await database.unmark_exit_reminder(user_id, cid, stage)   # sonraki tur tekrar dener
        return 0
    return 1


async def reminder_tick(now: float) -> int:
    """Bir tur: çıkış zamanı gelmiş tüm kullanıcı satırlarını işler. Dönüş: gönderilen push sayısı."""
    rows = await database.list_plan_order_requests_due(now)
    if not rows or not await _notifications_allowed():
        return 0
    fee = _fee_frac()
    exchanges: dict = {}
    sent = 0
    for row in rows:
        try:
            sent += await _handle_row(row, now, fee, exchanges)
        except Exception as exc:  # noqa: BLE001 — bir satır diğerlerini durdurmaz
            logger.warning("çıkış hatırlatıcısı satır hatası (%s): %s", row.get("client_order_id"), exc)
    return sent


async def reminder_loop() -> None:
    """60 sn'de bir `reminder_tick`. Hata döngüyü öldürmez."""
    await asyncio.sleep(STARTUP_DELAY_SEC)
    while True:
        try:
            n = await reminder_tick(time.time())
            if n:
                logger.info("çıkış hatırlatıcısı: %d push", n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("çıkış hatırlatıcısı turu atlandı: %s", exc)
        await asyncio.sleep(LOOP_INTERVAL_SEC)


__all__ = ["reminder_tick", "reminder_loop", "STAGE_KEYS"]
