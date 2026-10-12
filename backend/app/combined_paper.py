"""KOMBİNE PAPER PORTFÖY MOTORU (2026-10-11 kullanıcı kararı).

AMAÇ: WhatsApp grubuna gönderilen KOMBİNE YÜKSELİŞ LİSTESİ adaylarını AYRI bir
5.000 TL sanal portföyde OTONOM paper işlemle açıp yönetmek. Mevcut `auto_paper`
defterinden BAĞIMSIZ (kendi cüzdanı `combined_paper_wallet`, kendi tablosu
`combined_paper_trades`).

KURALLAR (kullanıcı):
  * Pozisyon büyüklüğü: her sembol için SERBEST TL bakiyesinin %10'u.
  * Komisyon: Binance TR ile aynı (COMMISSION_PCT %0,15/bacak) + kayma.
  * TP: adayın YÜKSELME POTANSİYELİNE göre belirlenir (`potential_pct`).
  * İşlem kâra geçince TRAILING mantığıyla MAKSİMUM kâr alınmaya çalışılır.

Akış: `on_combined_list_sent(candidates, report_id)` kombine liste gruba
gönderildikten sonra çağrılır → her aday için pozisyon açmayı dener.
`combined_paper_management_loop()` açık pozisyonları yönetir (TP/trailing/süre).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import database
from app.config import config
from app.state import market

logger = logging.getLogger("scalper.combined_paper")

_LOOP_TASK = None


def _ticker_price(symbol: str) -> float | None:
    """Canlı WS ticker fiyatı (taze değilse None)."""
    try:
        t = market.get_ticker(symbol)
    except Exception:
        t = None
    if not t:
        return None
    price = float(t.get("last_price") or 0)
    ts = float(t.get("timestamp") or 0)
    if price <= 0:
        return None
    if ts and (time.time() * 1000 - ts) > config.MAX_TICKER_AGE_SEC * 1000:
        return None
    return price


async def _price(symbol: str) -> float | None:
    """Anlık fiyat: önce WS ticker, yoksa REST yedeği.

    NEDEN (kullanıcı geri bildirimi 2026-10-11): pasife alınan sembol WS akışında
    DEĞİLDİR; WS-only fiyat okuma `None` döner ve pozisyon TP/trailing/süre
    yönetiminden tamamen kopar (sonsuza dek "izleniyor" kalır). REST yedeğiyle
    bu coinlerin de fiyatı gelir (kapanmasına GEREK YOK — pozisyon yönetilir).
    """
    p = _ticker_price(symbol)
    if p:
        return p
    try:
        from app.binance_tr_public import ticker_price as _tp
        rows = await _tp([symbol])
        for r in rows or []:
            if str(r.get("symbol") or "").upper() == symbol.upper():
                px = float(r.get("price") or 0)
                if px > 0:
                    return px
    except Exception:
        pass
    return None


def _plan_entry(candidate: dict, cash: float) -> dict | None:
    """Serbest bakiyenin %10'u kadar pozisyon planı üret (potansiyele göre TP).

    TP = potansiyelin anlamlı bir dilimi (yarısı), ama en az %3 — ve asla
    potansiyelin kendisini aşmaz. Stop = min(3×ATR?, taban SL) — taban SL
    `COMBINED_PAPER_SL_PCT`.
    """
    sym = str(candidate.get("symbol") or "").upper()
    price = float(candidate.get("price") or 0)
    if not sym or price <= 0 or cash <= 0:
        return None
    pos_pct = float(getattr(config, "COMBINED_PAPER_POSITION_PCT", 10.0)) / 100.0
    order_value = round(cash * pos_pct, 2)
    if order_value < 50.0:  # çok küçük kalan bakiye → anlamsız
        return None
    qty = order_value / price
    potential = candidate.get("potential_pct")
    try:
        pot = float(potential) if potential is not None else None
    except (TypeError, ValueError):
        pot = None
    # TP geometrisi TEK KAYNAK: `paper_sim.tp_pct_for` (aynı formül rapordaki
    # "gerçekleşebilir %" simülasyonunda da kullanılır → canlı ile AYRIŞAMAZ).
    from app.paper_sim import tp_pct_for
    tp_pct = tp_pct_for(pot, 3.0)
    sl_pct = float(getattr(config, "COMBINED_PAPER_SL_PCT", 3.0))
    return {
        "symbol": sym, "entry_price": price, "quantity": qty,
        "order_value_try": order_value, "tp_pct": tp_pct,
        "potential_pct": pot, "score": candidate.get("quality_score") or candidate.get("scan_score"),
        "take_profit": round(price * (1 + tp_pct / 100.0), 8),
        "stop_loss": round(price * (1 - sl_pct / 100.0), 8),
        "entry_time": time.time(),
    }


async def on_combined_list_sent(candidates: list[dict], report_id: int | None = None) -> int:
    """Kombine liste gönderildikten sonra: her aday için otonom paper aç.

    Dönen: açılan pozisyon sayısı. WhatsApp gönderimini ETKİLEMEZ (hata yutar).
    """
    if not bool(getattr(config, "COMBINED_PAPER_ENABLED", True)):
        return 0
    opened = 0
    for c in (candidates or []):
        try:
            sym = str(c.get("symbol") or "").upper()
            if not sym:
                continue
            cash = await database.get_combined_paper_wallet()
            plan = _plan_entry(c, cash)
            if not plan:
                continue
            plan["report_id"] = report_id
            plan["notification_key"] = f"combined-{report_id}-{sym}"
            row, status = await database.open_combined_paper_trade(plan)
            if status == "opened" and row:
                opened += 1
                logger.info("combined_paper AÇILDI: %s @ %.6f (%.2f TL, TP +%%%.1f)",
                            sym, plan["entry_price"], plan["order_value_try"], plan["tp_pct"])
        except Exception as exc:
            logger.debug("combined_paper açılış denemesi (%s): %s", c.get("symbol"), exc)
    return opened


async def _manage_single(trade: dict, now: float) -> None:
    """Tek pozisyonu yönet: TP, kâr kilidi/trailing, süre."""
    sym = str(trade.get("symbol") or "").upper()
    tid = int(trade["id"])
    entry = float(trade["entry_price"])
    qty = float(trade["quantity"])
    tp = float(trade["take_profit"]) if trade.get("take_profit") else None
    price = await _price(sym)
    if not price:
        return
    # Peak güncelle
    peak = max(float(trade.get("peak_price") or entry), price)
    fields: dict = {}
    if peak > float(trade.get("peak_price") or entry):
        fields["peak_price"] = peak

    # Süre kontrolü (maks tutma)
    max_hold_min = float(getattr(config, "COMBINED_PAPER_MAX_HOLD_MIN", 120.0))
    entry_time = float(trade.get("entry_time") or 0)
    hold_min = (now - entry_time) / 60.0 if entry_time > 0 else 0.0

    gain_pct = (price / entry - 1) * 100 if entry else 0.0
    peak_gain_pct = (peak / entry - 1) * 100 if entry else 0.0
    trigger = float(getattr(config, "COMBINED_PAPER_TRAIL_TRIGGER_PCT", 2.0))
    gap = float(getattr(config, "COMBINED_PAPER_TRAIL_GAP_PCT", 1.0))
    tp_cancel_on_trail = bool(getattr(config, "COMBINED_PAPER_TP_CANCEL_ON_TRAIL", True))
    trailing_on = bool(fields.get("trailing_activated")) or bool(trade.get("trailing_activated"))

    # 1) TP (hedef fiyat) — ANCAK trailing AKTİF DEĞİLKEN. Trailing bağlandıysa
    # TP kaldırılır (kullanıcı kararı 2026-10-12): "%4'te TP'ye ulaştı ama sembol
    # %20 arttı; trailing ile daha fazla kâr alınabilirdi." Trend sürdükçe taşır.
    if tp is not None and price >= tp and not (tp_cancel_on_trail and trailing_on):
        await database.close_combined_paper_trade(tid, min(price, tp), now, "take_profit")
        logger.info("combined_paper %s: TP (+%%%.2f)", sym, gain_pct)
        return

    # 2) Kâra geçince (trigger) kâr kilidi + trailing.
    # TRAILING MESAFESİ (2026-10-11 GERİ BİLDİRİM DÜZELTMESİ): eskiden stop
    # yalnız `peak*(1-gap)` + komisyon tabanıydı; gap %0.3 ÇOK DARDI → fiyat
    # tepeden küçük bir geri çekilmede anında kapanıyordu. Artık:
    #   * gap varsayılanı %1.0 (tepeden anlamlı geri çekilme toleransı),
    #   * taban = gidiş-dönüş komisyon + pay (net pozitif kâr kilidi),
    #   * İLK aktivasyonda stop fiyatın ALTINDA kalır (saniyesinde kapanmasın).
    # Pozisyon kârı büyütmesine izin verilir; kâr korunur ama sıkıştırılmaz.
    effective_stop = float(trade["stop_loss"]) if trade.get("stop_loss") else None
    if peak_gain_pct >= trigger:
        commission = float(getattr(config, "COMMISSION_PCT", 0.0015))
        cost_floor = entry * (1 + 2 * commission + 0.002)   # net pozitif taban
        trail_price = max(peak * (1 - gap / 100.0), cost_floor)
        was_active = bool(trade.get("trailing_activated", False))
        # İlk devreye girişte stop fiyatın altında olmalı (anında kapanma yok).
        if not was_active and trail_price >= price:
            trail_price = price * (1 - min(gap, 1.0) / 100.0)
        new_trail = max(float(trade.get("trailing_stop") or 0.0), trail_price)
        fields["trailing_activated"] = True
        fields["trailing_stop"] = new_trail
        effective_stop = new_trail if effective_stop is None else max(effective_stop, new_trail)

    # 3) Stop kontrolü (orijinal SL ya da kâr kilidi).
    if effective_stop is not None and price <= effective_stop:
        reason = "trailing_stop" if fields.get("trailing_activated") or trade.get("trailing_activated") else "stop_loss"
        await database.close_combined_paper_trade(tid, max(price, effective_stop), now, reason)
        logger.info("combined_paper %s: %s (%+.2f%%)", sym, reason, gain_pct)
        return

    # 4a) KÂRSIZ KAPANIŞ (kullanıcı kararı 2026-10-12): `no_profit_min` dk içinde
    # KÂRA GEÇMEDİYSE kapat. "Kâra geçmiş" = tepe (peak) girişin üstünde. Kâra
    # geçtiyse bu kural UYGULANMAZ (normal TP/trailing/max-hold işler); böylece
    # kazanan pozisyon erken kesilmez, ama yatay/zararda bekleyen ölü sermaye
    # serbest bırakılır.
    no_profit_min = float(getattr(config, "COMBINED_PAPER_NO_PROFIT_MIN", 30.0))
    if no_profit_min > 0 and hold_min >= no_profit_min and peak <= entry:
        await database.close_combined_paper_trade(tid, price, now, "no_profit_timeout")
        logger.info("combined_paper %s: KÂRSIZ SÜRE DOLDU (%.0f dk, %+.2f%%)", sym, hold_min, gain_pct)
        return

    # 4) Süre doldu → kapanış.
    if max_hold_min > 0 and hold_min >= max_hold_min:
        await database.close_combined_paper_trade(tid, price, now, "max_duration")
        logger.info("combined_paper %s: SÜRE DOLDU (%.0f dk, %+.2f%%)", sym, hold_min, gain_pct)
        return

    fields["last_checked_at"] = now
    await database.update_combined_paper_trade(tid, fields)


async def combined_paper_management_loop():
    """Açık kombine paper pozisyonlarını periyodik yönet (TP/trailing/süre)."""
    logger.info("kombine paper yönetim döngüsü başladı (enabled=%s)",
                getattr(config, "COMBINED_PAPER_ENABLED", True))
    await asyncio.sleep(60)
    while True:
        try:
            if bool(getattr(config, "COMBINED_PAPER_ENABLED", True)):
                open_trades = await database.list_combined_paper_trades(status="open", limit=200)
                now = time.time()
                for tr in open_trades:
                    try:
                        await _manage_single(tr, now)
                    except Exception as exc:
                        logger.debug("combined_paper yönetim (%s): %s", tr.get("symbol"), exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("kombine paper döngü turu: %s", exc)
        await asyncio.sleep(30)
