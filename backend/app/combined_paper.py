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

from app import database, paper_ledger, price_service
from app.config import config

logger = logging.getLogger("scalper.combined_paper")

_LOOP_TASK = None


def _ticker_price(symbol: str) -> float | None:
    """Canlı WS ticker fiyatı (taze değilse None). Tazelik: price_service/paper_ledger."""
    quote = price_service.ws_quote(symbol)
    return quote[0] if quote else None


async def _price(symbol: str) -> float | None:
    """Anlık fiyat: önce WS ticker, yoksa REST yedeği (price_service.rest_quote).

    NEDEN (kullanıcı geri bildirimi 2026-10-11): pasife alınan sembol WS akışında
    DEĞİLDİR; WS-only fiyat okuma `None` döner ve pozisyon TP/trailing/süre
    yönetiminden tamamen kopar (sonsuza dek "izleniyor" kalır). REST yedeğiyle
    bu coinlerin de fiyatı gelir (kapanmasına GEREK YOK — pozisyon yönetilir).
    """
    p = _ticker_price(symbol)
    if p:
        return p
    quote = await price_service.rest_quote(symbol)
    return quote[0] if quote else None


def _plan_entry(candidate: dict, cash: float, price: float | None = None) -> dict | None:
    """Serbest bakiyenin %10'u kadar pozisyon planı üret (potansiyele göre TP).

    TP = potansiyelin anlamlı bir dilimi (yarısı), ama en az %3 — ve asla
    potansiyelin kendisini aşmaz. Stop = min(3×ATR?, taban SL) — taban SL
    `COMBINED_PAPER_SL_PCT`.

    2026-10-15 (denetim düzeltmesi, madde 6): `price` verilirse (çağıran taze
    ticker/REST fiyatını geçirir) WhatsApp listesindeki dakikalar eski
    `candidate["price"]` yerine o kullanılır. Giriş dolumuna çıkıştakiyle
    (`close_combined_paper_trade`) AYNI kayma (`ESTIMATED_SLIPPAGE_PCT`)
    uygulanır; TP/SL çapası bu dolumdan türetilir (auto_paper ile aynı model).
    """
    sym = str(candidate.get("symbol") or "").upper()
    price = float(price if price is not None else (candidate.get("price") or 0))
    if not sym or price <= 0 or cash <= 0:
        return None
    pos_pct = float(getattr(config, "COMBINED_PAPER_POSITION_PCT", 10.0)) / 100.0
    order_value = round(cash * pos_pct, 2)
    if order_value < 50.0:  # çok küçük kalan bakiye → anlamsız
        return None
    price = paper_ledger.entry_fill(price)   # giriş dolumu (kayma dahil)
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
            # 2026-10-15 (denetim düzeltmesi, madde 6): giriş için TAZE fiyat
            # (WS ticker, yoksa REST). Taze fiyat yoksa bayat liste fiyatıyla
            # AÇILMAZ (çıkışta tazelik vardı, girişte yoktu).
            fresh_price = await _price(sym)
            if not fresh_price or fresh_price <= 0:
                logger.warning("combined_paper %s: taze fiyat alınamadı — açılış atlandı", sym)
                continue
            cash = await database.get_combined_paper_wallet()
            plan = _plan_entry(c, cash, price=fresh_price)
            if not plan:
                continue
            plan["report_id"] = report_id
            plan["notification_key"] = f"combined-{report_id}-{sym}"
            row, status = await database.open_combined_paper_trade(plan)
            if status == "opened" and row:
                opened += 1
                logger.info("combined_paper AÇILDI: %s @ %.6f (%.2f TL, TP +%%%.1f)",
                            sym, plan["entry_price"], plan["order_value_try"], plan["tp_pct"])
        except Exception:
            # 2026-10-15 (denetim düzeltmesi, madde 5): para yolundaki hata
            # GÖRÜNÜR (traceback ile); WhatsApp gönderimi yine etkilenmez.
            logger.exception("combined_paper açılış denemesi başarısız (%s)", c.get("symbol"))
    return opened


async def _close(tid: int, sym: str, price: float, now: float, reason: str) -> dict | None:
    """Kapanışı DB'de yap; dönüşü KONTROL et, başarısızsa uyar ve BİR kez tekrar dene.

    2026-10-15 (denetim düzeltmesi, madde 5): `close_combined_paper_trade`
    hata/yarış durumunda None döner; eskiden kimse bakmıyor, pozisyon sessizce
    açık kalıyordu.
    """
    for attempt in (1, 2):
        try:
            out = await database.close_combined_paper_trade(tid, price, now, reason)
        except Exception:
            logger.exception("combined_paper %s: kapanış istisnası (id=%s, neden=%s, deneme %d/2)",
                             sym, tid, reason, attempt)
            out = None
        if out:
            return out
        logger.warning("combined_paper %s: kapanış BAŞARISIZ (id=%s, neden=%s, deneme %d/2)",
                       sym, tid, reason, attempt)
    return None


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
        await _close(tid, sym, paper_ledger.exit_fill("take_profit", price, tp), now, "take_profit")
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
        commission = paper_ledger.commission_pct()
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
    # 2026-10-15 (denetim düzeltmesi, madde 2): dolum iki fiyatın KÖTÜSÜ
    # `min(price, stop)` — eski `max(price, stop)` gap'te stop fiyatından
    # dolup zararı küçük/PnL'i iyimser yazıyordu (auto_paper ile aynı düzeltme).
    if effective_stop is not None and price <= effective_stop:
        reason = "trailing_stop" if fields.get("trailing_activated") or trade.get("trailing_activated") else "stop_loss"
        await _close(tid, sym, paper_ledger.exit_fill(reason, price, effective_stop), now, reason)
        logger.info("combined_paper %s: %s (%+.2f%%)", sym, reason, gain_pct)
        return

    # 4a) KÂRSIZ KAPANIŞ (kullanıcı kararı 2026-10-12): `no_profit_min` dk içinde
    # KÂRA GEÇMEDİYSE kapat. "Kâra geçmiş" = tepe (peak) girişin üstünde. Kâra
    # geçtiyse bu kural UYGULANMAZ (normal TP/trailing/max-hold işler); böylece
    # kazanan pozisyon erken kesilmez, ama yatay/zararda bekleyen ölü sermaye
    # serbest bırakılır.
    no_profit_min = float(getattr(config, "COMBINED_PAPER_NO_PROFIT_MIN", 30.0))
    if no_profit_min > 0 and hold_min >= no_profit_min and peak <= entry:
        await _close(tid, sym, paper_ledger.exit_fill("no_profit_timeout", price), now, "no_profit_timeout")
        logger.info("combined_paper %s: KÂRSIZ SÜRE DOLDU (%.0f dk, %+.2f%%)", sym, hold_min, gain_pct)
        return

    # 4) Süre doldu → kapanış.
    if max_hold_min > 0 and hold_min >= max_hold_min:
        await _close(tid, sym, paper_ledger.exit_fill("max_duration", price), now, "max_duration")
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
                    except Exception:
                        # 2026-10-15 (madde 5): yönetim hatası traceback ile görünür.
                        logger.exception("combined_paper yönetim hatası (%s, id=%s)",
                                         tr.get("symbol"), tr.get("id"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("kombine paper döngü turu: %s", exc)
        await asyncio.sleep(30)
