"""Süper Tarama → push + otonom paper (TEK KANAL).

2026-11-25 (kullanıcı): radar bildirimleri ve otonom paper yalnız süper
taramadan beslenir. Bu döngü her `SUPER_SCAN_INTERVAL_SEC` saniyede:

  1. süper taramayı çalıştırır (tüm tarayıcıların birleşik, tek skorlu listesi),
  2. eşiği (`SUPER_SCAN_PUSH_MIN_SCORE`) geçen ilk `SUPER_SCAN_PUSH_TOP_N` adayı
     alır; aynı sembol için `SUPER_SCAN_PUSH_COOLDOWN_MIN` içinde tekrar bildirmez,
  3. her aday için zarf üretip push gönderir (`monitoring._send_push`),
  4. aynı zarfı `auto_paper.try_open_from_notification`'a verir
     (source="super_scan"; diğer kapılar — skor/ATR/OI/küme/açık pozisyon —
     aynen uygulanır).

Salt okunur tarama + mevcut bildirim/işlem yollarının yeniden kullanımı.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import logging
import math
import time

from app.config import config
from app import database

logger = logging.getLogger("scalper.super_scan")


def _cooldown_key(symbol: str) -> str:
    return f"super_push:{str(symbol).upper()}"


async def _recently_pushed(symbol: str, cooldown_min: float) -> bool:
    if cooldown_min <= 0:
        return False
    try:
        raw = await database.get_llm_setting(_cooldown_key(symbol))
        last = float(raw) if raw else 0.0
    except Exception:
        return False
    return (time.time() - last) < cooldown_min * 60.0


async def _mark_pushed(symbol: str) -> None:
    try:
        await database.set_llm_setting(_cooldown_key(symbol), str(int(time.time())))
    except Exception as exc:
        logger.debug("süper tarama cooldown yazılamadı: %s", exc)


def _envelope(item: dict) -> dict:
    """Süper tarama satırını bildirim/işlem zarfına çevirir."""
    symbol = str(item.get("symbol") or "").upper()
    rank_score = float(item.get("super_score") or 0)
    score = float(item.get("score") if item.get("score") is not None else rank_score)
    target = item.get("target_pct")
    detected_at = item.get("detected_at")
    notification_key = f"super:{symbol}"
    if isinstance(detected_at, (float, int)) and math.isfinite(detected_at) and detected_at > 0:
        # Sinyal tekrar okunduğunda anahtarı sabittir. Yeni bir tespit,
        # önceki pozisyon aynı beş dakikada kapanmış olsa bile ayrı anahtar alır.
        notification_key = f"super:{symbol.replace('_', '')}:{int(detected_at * 1000)}"
    horizon = item.get("horizon_minutes") or 15
    sources = ", ".join(item.get("sources") or []) or "süper tarama"
    tags = ", ".join(item.get("tags") or []) or ""
    flags = ", ".join(item.get("cmc_flags") or []) or ""
    extra = " · ".join(x for x in (tags, flags) if x)
    try:
        target_txt = f"%{float(target):.1f}" if target is not None else "—"
    except (TypeError, ValueError):
        target_txt = "—"
    head = f"Sıralama {rank_score:.1f} · taban {score:.1f} · hedef {target_txt} · {horizon} dk"
    message = head + "\n" + f"Kaynaklar: {sources}" + (("\n" + extra) if extra else "")
    return {
        "symbol": symbol,
        "title": f"⚡ Süper Tarama · {symbol.replace('_', '')}",
        "message": message,
        "tag": f"super-{symbol}",
        # `_send_push` bu alanı ZORUNLU okuyor; eksikse "KeyError: 'url'" ile
        # tüm bildirim düşüyordu (canlı log 2026-11-25).
        "url": f"/symbol-analysis?symbol={symbol}",
        "score": score,
        "super_score": rank_score,
        "scan_evidence": {
            key: item.get(key) for key in (
                "sources", "source_families", "source_bonus", "cmc_bonus",
                "cmc_flags", "score", "super_score", "detected_at",
                "price", "target_pct", "horizon_minutes", "atr_pct_15m",
                "oi_change_pct", "volume_24h_try", "confluence",
            )
        },
        "target_pct": target,
        "horizon_minutes": horizon,
        "price": item.get("price"),
        "source": "super_scan",
        # Sinyal İzleme yalnız süper tarama işlemlerini sayar (LIKE 'super:%').
        "notification_key": notification_key,
        "detected_at": detected_at,
        "sent_via_push": True,
        "super_scan": True,
        "atr_pct": item.get("atr_pct_15m"),
        "oi_change_pct": item.get("oi_change_pct"),
        "mode": "super_scan",
    }


async def run_once() -> dict:
    """Tek tur: tara → en iyi N adayı bildir/işle. Hata fırlatmaz."""
    from app.routers import monitoring, auto_paper

    try:
        payload = await monitoring.super_scan_for_paper(limit=50)
    except Exception as exc:
        logger.warning("süper tarama çalıştırılamadı: %s", exc)
        return {"scanned": 0, "pushed": 0, "opened": 0, "error": str(exc)}

    min_score = float(getattr(config, "SUPER_SCAN_PUSH_MIN_SCORE", 65))
    top_n = int(getattr(config, "SUPER_SCAN_PUSH_TOP_N", 2))
    cooldown = float(getattr(config, "SUPER_SCAN_PUSH_COOLDOWN_MIN", 30))
    # 2026-11-25 (kullanıcı): PUSH kapalı olabilir; işlem açılışı devam eder.
    push_enabled = bool(getattr(config, "SUPER_SCAN_PUSH_ENABLED", False))

    items_all = payload.get("items") or []
    candidates = sorted((item.get("paper_candidate") or item for item in items_all),
                        key=lambda item: float(item.get("super_score") or 0), reverse=True)
    pushed = opened = attempted = 0
    blocked = Counter()
    for rank, item in enumerate(candidates, start=1):
        if attempted >= top_n:
            break
        if float(item.get("super_score") or 0) < min_score:
            continue
        if item.get("paper_block_reason"):
            blocked[item["paper_block_reason"]] += 1
            continue
        symbol = str(item.get("symbol") or "")
        notif = _envelope(item)
        notif["scan_evidence"].update({"rank": rank, "minimum_rank_score": min_score, "top_n": top_n})
        in_cooldown = await _recently_pushed(symbol, cooldown)
        if in_cooldown and (
            getattr(config, "AUTO_PAPER_ONLY_ON_PUSH", False)
            or not await auto_paper.profitable_super_scan_reentry(notif)
        ):
            continue
        send_push = push_enabled and not in_cooldown
        notif["sent_via_push"] = False
        if not send_push:
            # Açık pozisyonu olan sembol deneme hakkını tüketmesin; aksi halde
            # ilk TOP_N aday her turda takılıp alt sıradaki fırsatlar hiç
            # denenmez (2026-11-25 denetimi).
            try:
                if await database.get_open_auto_paper_trade(symbol):
                    blocked["already_open"] += 1
                    continue
            except Exception:
                pass  # okunamazsa normal yola bırak; gerçek kapı tekrar bakar
            # Ucuz ayar/skor/mod kapısı kota tüketmeden eler. İşlem motoru
            # açmadan önce güncel ayarları ve tüm giriş kurallarını tekrar okur.
            _, rejection, _, _ = await auto_paper._entry_context(notif)
            if rejection:
                blocked[rejection["reason"]] += 1
                if rejection["reason"] == "auto_paper_disabled":
                    break
                continue
        if send_push:
            ok = False
            try:
                ok = bool(await monitoring._send_push(notif))
            except Exception as exc:
                logger.debug("süper tarama push hatası (%s): %s", symbol, exc)
            if not ok:
                # Push açıkken teslim başarısızsa işlem AÇILMAZ (eski davranış).
                continue
            pushed += 1
            notif["sent_via_push"] = True
        else:
            # Push kapalı: zarf "push gönderilmedi" olarak işaretlenir; otonom
            # paper yine de denenir (AUTO_PAPER_ONLY_ON_PUSH varsayılan kapalı).
            notif["sent_via_push"] = False
            notif["push_skipped_reason"] = "super_scan_push_disabled"
        attempted += 1
        if send_push:
            await _mark_pushed(symbol)
        try:
            result = await auto_paper.try_open_from_notification(notif)
            if isinstance(result, dict) and result.get("status") == "opened":
                opened += 1
                if not send_push:
                    await _mark_pushed(symbol)
            else:
                blocked[(result or {}).get("reason") or "paper_not_opened"] += 1
        except Exception as exc:
            blocked["paper_error"] += 1
            logger.debug("süper tarama paper açılışı hatası (%s): %s", symbol, exc)
    top_score = float(items_all[0].get("super_score") or 0) if items_all else 0.0
    return {"scanned": payload.get("scanned") or 0, "eligible": payload.get("eligible") or 0,
            "pushed": pushed, "attempted": attempted, "opened": opened, "blocked": dict(blocked),
            "top_score": round(top_score, 1),
            "push_enabled": push_enabled}


async def super_scan_loop() -> None:
    """Arka plan döngüsü. Hata döngüyü öldürmez."""
    if not getattr(config, "SUPER_SCAN_ONLY", False):
        logger.info("süper tarama döngüsü kapalı (SUPER_SCAN_ONLY=0)")
        return
    await asyncio.sleep(45)  # açılış patlaması bitsin
    interval = int(getattr(config, "SUPER_SCAN_INTERVAL_SEC", 60))
    rounds = 0
    while True:
        try:
            stats = await run_once()
            rounds += 1
            # 2026-11-25: yalnız push olunca log atmak "sistem çalışıyor mu?"
            # sorusunu bırakıyordu. Her tur DEBUG, 10 turda bir (≈15 dk) INFO.
            if stats.get("pushed") or stats.get("opened"):
                logger.info("süper tarama: %s", stats)
            elif rounds % 10 == 0:
                logger.info("süper tarama nabız: %s", stats)
            else:
                logger.debug("süper tarama turu: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("süper tarama turu hatası: %s", exc)
        await asyncio.sleep(interval)
