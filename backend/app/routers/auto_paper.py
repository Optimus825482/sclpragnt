"""Otonom Paper Trade Sistemi — monitoring bildirimlerinden tetiklenen pozisyonlar.

Mimari:
  monitoring.py _notify() → auto_paper.py try_open_from_notification()
  
Her bildirim oluştuğunda monitoring.py'deki _notify() fonksiyonunun sonunda bu
modül çağrılır. Açılan pozisyonlar yalnızca auto_paper_trades tablosunda
izlenir; SL/TP/breakeven yönetimi ayrı bir background loop'la yapılır.
positions/trades tablosuna DOKUNULMAZ (signals/decision_logs'a gözlem amaçlı
yazılır).

Muhasebe: açılışta wallet'tan order_value*(1+komisyon) düşülür; kapanışta
exit_notional*(1-komisyon) iade edilir. Kaydedilen pnl = round-trip net =
gross - (entry+exit) komisyon; pnl_pct aynı tabandan türetilir. Açılış ve
kapanış database.open_auto_paper_trade / close_auto_paper_trade içinde tek
transaction'dır (advisory lock ile yarış koruması).
"""
import asyncio
import json
import logging
import time
import math

from fastapi import APIRouter, Request

from app.config import config
from app import database
from app.api_common import log_user_action, _background_tasks
from app.state import market
from app.ws_runtime import ws_manager

logger = logging.getLogger("scalper.auto_paper")
router = APIRouter()

# ---------------------------------------------------------------------------
# Background loop state
# ---------------------------------------------------------------------------
_loop_task = None
_AUTO_PAPER_STATE = {
    "total_opened": 0,
    "total_closed": 0,
    "total_pnl": 0.0,
    "winning_trades": 0,
    "losing_trades": 0,
    "last_check_at": None,
}


# ---------------------------------------------------------------------------
# Core: bildirim → pozisyon açılışı
# ---------------------------------------------------------------------------
async def try_open_from_notification(notification: dict) -> dict | None:
    """Bir monitoring bildirimi geldiğinde otonom paper pozisyonu aç.
    
    Kurallar:
      - Sembolde açık pozisyon yoksa serbest TL bakiyesinin %balance_pct'i ile pozisyon aç.
      - SL: settings'teki stop_loss_pct (varsayılan %3)
      - TP: bildirimdeki hedef (notification_target_pct üzerinden)
      - Sembolde zaten açık auto_paper pozisyonu varsa TP güncelle (hedef takibi)
      - Aynı bildirim daha önce işlendiyse (kapanış sonrası yeniden açma) açma
    """
    try:
        settings = await get_auto_paper_settings()
        if not settings.get("enabled", True):
            return None

        symbol = str(notification.get("symbol") or "").upper()
        if not symbol:
            return None

        score = float(notification.get("score") or 0)
        min_score = float(settings.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT))
        if score < min_score:
            logger.info("auto_paper %s: skor %.1f < min_score %.1f — açılmadı",
                        symbol, score, min_score)
            return None

        # Mevcut fiyat
        ticker = market.get_ticker(symbol)
        current_price = float(ticker.get("last_price") or 0) if ticker else 0
        if current_price <= 0:
            current_price = float(notification.get("price") or 0)
        if current_price <= 0:
            return None

        notification_id = notification.get("id")
        # Aynı bildirim daha önce bir trade'e dönüştüyse (kapanmış olsa bile) açma.
        if notification_id is not None:
            prior_trade = await database.get_recent_auto_paper_trade_by_notification(notification_id)
            if prior_trade:
                return None

        # Mevcut açık auto_paper pozisyonunu kontrol et
        open_trade = await database.get_open_auto_paper_trade(symbol)

        if open_trade:
            # Açık pozisyon var → TP güncelle (bildirim hedefini takip et)
            return await _update_existing_trade(open_trade, notification, current_price)
        else:
            # Yeni pozisyon aç (atomik; DB tarafında çift-açılış kontrolü de var)
            return await _open_new_trade(symbol, notification, current_price, settings)
    except Exception as exc:
        logger.exception("auto_paper try_open: %s", exc)
        return None


async def _open_new_trade(symbol: str, notification: dict, current_price: float, settings: dict) -> dict | None:
    """Yeni otonom paper pozisyonu aç — atomik DB işlemi (open_auto_paper_trade)."""
    try:
        balance_pct = float(settings.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)) / 100.0
        min_order = float(settings.get("min_order_try", config.AUTO_PAPER_MIN_ORDER_TRY))

        # Bakiye kontrolü
        balance = await database.get_wallet_balance("TRY")
        order_value = balance * balance_pct
        if order_value < min_order:
            order_value = balance
            if order_value < min_order:
                logger.info("auto_paper %s: bakiye yetersiz %.2f TRY", symbol, balance)
                return None

        sl_pct = float(settings.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)) / 100.0
        target_pct = float(notification.get("target_pct") or 0)
        if target_pct <= 0:
            target_pct = float(settings.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT))

        commission_pct = config.COMMISSION_PCT
        max_cost = order_value / (1 + commission_pct)
        quantity = max_cost / current_price if current_price > 0 else 0
        if quantity <= 0:
            return None

        net_order_value = current_price * quantity
        take_profit_price = current_price * (1 + target_pct / 100)
        stop_loss_price = current_price * (1 - sl_pct)
        now = time.time()
        notification_id = notification.get("id")

        trade_data = {
            "symbol": symbol,
            "side": "LONG",
            "status": "open",
            "notification_id": notification_id,
            "entry_price": current_price,
            "quantity": quantity,
            "order_value_try": net_order_value,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "peak_price": current_price,
            "entry_time": now,
            "notification_score": notification.get("score"),
            "notification_target_pct": target_pct,
            "notification_expected_price": notification.get("expected_price"),
            "created_at": now,
            "updated_at": now,
        }
        signal = {
            "timestamp": now,
            "symbol": symbol,
            "action": "BUY_SIGNAL",
            "price": current_price,
            "reason": f"AUTO_PAPER skor {notification.get('score', 0):.1f} hedef +%{target_pct:.1f} TP={take_profit_price:.6f} SL={stop_loss_price:.6f}",
            "strategy": "AUTO_PAPER",
            "trade_id": None,  # insert sonrası id bilinir; DB'de dolduramayız, reason yeterli
        }
        trade, status = await database.open_auto_paper_trade(trade_data, signal)

        if status == "already_open":
            # Arada başka bir çağrı açmış — onu güncellemeyi dene
            open_trade = await database.get_open_auto_paper_trade(symbol)
            if open_trade:
                return await _update_existing_trade(open_trade, notification, current_price)
            return None
        if status == "already_traded":
            logger.info("auto_paper %s: bildirim %s zaten işlendi — açılmadı", symbol, notification_id)
            return None
        if status == "insufficient_balance":
            logger.info("auto_paper %s: transaction'da bakiye yetersiz", symbol)
            return None
        if not trade or status != "opened":
            return None

        trade_id = trade["id"]
        # trade_id'yi sinyale geri yazamayız (transaction kapandı); id'yi state'te tut
        _AUTO_PAPER_STATE["total_opened"] += 1

        await _broadcast_trade({
            "action": "OPENED", "symbol": symbol,
            "entry": current_price, "take_profit": take_profit_price,
            "stop_loss": stop_loss_price, "quantity": quantity,
            "order_value": net_order_value, "score": notification.get("score"),
            "target_pct": target_pct, "trade_id": trade_id,
        })

        logger.info("auto_paper %s: AÇILDI miktar=%.4f giriş=%.6f TP=%.6f SL=%.6f değer=%.2fTRY skor=%.1f",
                    symbol, quantity, current_price, take_profit_price, stop_loss_price,
                    net_order_value, notification.get("score"))

        return {"status": "opened", "trade_id": trade_id, "symbol": symbol}

    except Exception as exc:
        logger.exception("auto_paper %s açılış hatası: %s", symbol, exc)
        return None


async def _update_existing_trade(open_trade: dict, notification: dict, current_price: float) -> dict | None:
    """Açık pozisyon için TP'yi bildirimdeki yeni hedefle güncelle."""
    try:
        target_pct = float(notification.get("target_pct") or 0)
        if target_pct <= 0:
            return None

        entry_price = float(open_trade["entry_price"])
        new_tp = entry_price * (1 + target_pct / 100)
        old_tp = float(open_trade.get("take_profit") or 0)

        # TP sadece yükseliyorsa güncelle
        if new_tp > old_tp:
            await database.update_auto_paper_trade_tp(
                open_trade["id"], new_tp, notification.get("score"), target_pct)

            logger.info("auto_paper %s: TP güncellendi %.6f → %.6f",
                        open_trade["symbol"], old_tp, new_tp)

            return {"status": "tp_updated", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}
        return {"status": "no_change", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}
    except Exception as exc:
        logger.exception("auto_paper %s TP güncelleme hatası: %s", open_trade.get("symbol"), exc)
        return None


# ---------------------------------------------------------------------------
# Background loop: pozisyon yönetimi (SL/TP/breakeven)
# ---------------------------------------------------------------------------
async def auto_paper_management_loop():
    """Her ~5 saniyede bir açık auto_paper pozisyonlarını kontrol et.

    - TP'ye ulaşıldıysa kapat (kâr)
    - SL'ye ulaşıldıysa kapat (zarar)
    - +breakeven_trigger_pct kâra geçtiyse stop'u maliyet üstüne çek
    """
    logger.info("auto_paper yönetim döngüsü başladı")
    await asyncio.sleep(30)
    while True:
        try:
            await _check_open_positions()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("auto_paper yönetim turu: %s", exc)
        await asyncio.sleep(5.0)


async def _check_open_positions():
    """Tüm açık auto_paper pozisyonlarını tara ve yönet."""
    trades = await database.list_auto_paper_trades(status="open")
    if not trades:
        return

    now = time.time()
    # Breakeven eşiğini turlar arasında bir kez yükle (her trade için DB'ye gitme)
    settings = await get_auto_paper_settings()
    breakeven_trigger_pct = float(settings.get("breakeven_trigger_pct", config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT))

    for trade in trades:
        try:
            await _manage_single_trade(trade, now, breakeven_trigger_pct)
        except Exception as exc:
            logger.warning("auto_paper %s yönetim: %s", trade.get("symbol"), exc)

    _AUTO_PAPER_STATE["last_check_at"] = now


async def _manage_single_trade(trade: dict, now: float, breakeven_trigger_pct: float = 1.5):
    """Tek bir auto_paper pozisyonunu yönet: TP/SL/breakeven."""
    symbol = str(trade.get("symbol") or "").upper()
    trade_id = int(trade["id"])
    entry_price = float(trade["entry_price"])
    stop_loss = float(trade["stop_loss"]) if trade.get("stop_loss") else None
    take_profit = float(trade["take_profit"]) if trade.get("take_profit") else None
    quantity = float(trade["quantity"])
    commission_pct = config.COMMISSION_PCT

    # Güncel fiyat
    ticker = market.get_ticker(symbol)
    current_price = float(ticker.get("last_price") or 0) if ticker else 0
    if current_price <= 0:
        return

    # Peak güncelle
    peak_price = max(float(trade.get("peak_price") or entry_price), current_price)
    if peak_price > float(trade.get("peak_price") or entry_price):
        await database.update_auto_paper_peak(trade_id, peak_price)

    # TP kontrolü
    if take_profit is not None and current_price >= take_profit:
        await _close_trade(trade_id, symbol, current_price, now, "take_profit")
        return

    # SL kontrolü
    if stop_loss is not None and current_price <= stop_loss:
        await _close_trade(trade_id, symbol, current_price, now, "stop_loss")
        return

    # Breakeven kontrolü (trailing + dinamik komisyon + buffer).
    # Kullanıcı isteği: "breakeven stop'a dinamik komisyon ekle + fiyat yükseldikten
    # sonra devreye gir". Tasarım:
    #   - Net taban (floor): entry*(1 + 2*komisyon + buffer) → bu fiyattan satış,
    #     komisyonlar sonrası daima POZİTİF net verir (sıfırda değil).
    #   - Trailing: fiyat yükselirken stop, zirvenin BREAKEVEN_TRAIL_GAP_PCT
    #     gerisinden takip eder; zirveden sonra düşüşte kâr kilitlenir.
    #   - Stop, güncel fiyatın üstüne çıkarsa (trigger komisyondan küçükse)
    #     hemen kapanmasın: aktivasyon ertelenir, fiyat biraz daha yükselir.
    breakeven_activated = bool(trade.get("breakeven_activated", False))
    gross_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
    breakeven_buffer_pct = 0.05
    BREAKEVEN_TRAIL_GAP_PCT = 0.60
    # In-memory breakeven stop: DB'ye yazılan değerle aynı turdaki koruma
    # kontrolü arasında gecikme olmasın.
    current_breakeven_stop = float(trade.get("breakeven_stop") or 0)

    if gross_pnl_pct >= breakeven_trigger_pct:
        net_floor = entry_price * (1 + 2 * commission_pct + breakeven_buffer_pct / 100)
        trail_stop = peak_price * (1 - BREAKEVEN_TRAIL_GAP_PCT / 100)
        new_breakeven = max(net_floor, trail_stop)
        applied_breakeven = max(new_breakeven, current_breakeven_stop)
        if applied_breakeven < current_price:
            if not breakeven_activated or applied_breakeven > current_breakeven_stop:
                await database.update_auto_paper_breakeven(trade_id, True, applied_breakeven)
                current_breakeven_stop = applied_breakeven
                logger.info("auto_paper %s: breakeven stop=%.6f (gross=%+.2f%%)", symbol, applied_breakeven, gross_pnl_pct)
        breakeven_activated = True

    # Breakeven stop koruması (in-memory değer kullanılır, DB okuması değil)
    if breakeven_activated and current_breakeven_stop > 0 and current_price <= current_breakeven_stop:
        await _close_trade(trade_id, symbol, current_price, now, "breakeven_stop")


async def _close_trade(trade_id: int, symbol: str, exit_price: float, now: float, reason: str):
    """Auto paper pozisyonunu kapat ve wallet'a iade et (atomik DB işlemi)."""
    try:
        trade = await database.get_auto_paper_trade(trade_id)
        if not trade or trade.get("status") != "open":
            return

        entry_price = float(trade["entry_price"])
        quantity = float(trade["quantity"])
        commission_pct = config.COMMISSION_PCT
        entry_commission = entry_price * quantity * commission_pct
        exit_commission = exit_price * quantity * commission_pct
        total_commission = entry_commission + exit_commission
        gross_pnl = (exit_price - entry_price) * quantity
        pnl = gross_pnl - total_commission
        invested = entry_price * quantity
        pnl_pct = (pnl / invested * 100) if invested else 0.0
        hold_seconds = now - float(trade["entry_time"])

        # DB güncelle + wallet iadesi + sinyal tek transaction'da
        closed = await database.close_auto_paper_trade(
            trade_id, exit_price, now, pnl, pnl_pct, total_commission, reason)
        if not closed:
            logger.warning("auto_paper %s: kapanış başarısız (zaten kapalı?)", symbol)
            return

        _AUTO_PAPER_STATE["total_closed"] += 1
        _AUTO_PAPER_STATE["total_pnl"] += pnl
        if pnl >= 0:
            _AUTO_PAPER_STATE["winning_trades"] += 1
        else:
            _AUTO_PAPER_STATE["losing_trades"] += 1

        await _broadcast_trade({
            "action": "CLOSED", "symbol": symbol,
            "exit": exit_price, "pnl": round(pnl, 2),
            "reason": reason, "trade_id": trade_id,
        })

        logger.info("auto_paper %s: KAPANDI (%s) çıkış=%.6f PnL=%.2fTRY (%+.2f%%) süre=%.0fs",
                    symbol, reason, exit_price, pnl, pnl_pct, hold_seconds)

    except Exception as exc:
        logger.exception("auto_paper %s kapatma: %s", symbol, exc)


async def _broadcast_trade(data: dict):
    """WS üzerinden auto_paper trade olayını yayınla."""
    try:
        await ws_manager.broadcast({"type": "auto_paper_trade", "data": data})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
async def get_default_settings() -> dict:
    return {
        "enabled": True,
        "min_score": config.AUTO_PAPER_MIN_SCORE_DEFAULT,
        "balance_pct": config.AUTO_PAPER_BALANCE_PCT_DEFAULT,
        "stop_loss_pct": config.AUTO_PAPER_SL_PCT_DEFAULT,
        "default_target_pct": config.AUTO_PAPER_DEFAULT_TARGET_PCT,
        "min_order_try": config.AUTO_PAPER_MIN_ORDER_TRY,
        "breakeven_trigger_pct": config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT,
    }


async def get_auto_paper_settings() -> dict:
    """DB'den auto_paper ayarlarını oku."""
    try:
        raw = await database.get_llm_setting("auto_paper_settings", "{}")
        settings = json.loads(raw or "{}")
        defaults = await get_default_settings()
        return {**defaults, **settings}
    except Exception:
        return await get_default_settings()


@router.get("/api/auto-paper/settings")
async def get_settings_endpoint():
    """Otonom paper trade ayarlarını döndür."""
    settings = await get_auto_paper_settings()
    state = dict(_AUTO_PAPER_STATE)
    return {"paper_only": True, "settings": settings, "state": state}


@router.put("/api/auto-paper/settings")
async def update_settings_endpoint(payload: dict, request: Request):
    """Otonom paper trade ayarlarını güncelle (admin)."""
    from app.main import _require_admin
    _require_admin(request)

    editable = ("enabled", "min_score", "balance_pct", "stop_loss_pct",
                "default_target_pct", "min_order_try", "breakeven_trigger_pct")
    existing = await get_auto_paper_settings()
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}

    settings = {
        "enabled": bool(merged.get("enabled", True)),
        "min_score": max(0.0, min(100.0, float(merged.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT)))),
        "balance_pct": max(1.0, min(100.0, float(merged.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)))),
        "stop_loss_pct": max(0.1, min(20.0, float(merged.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)))),
        "default_target_pct": max(0.5, min(20.0, float(merged.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT)))),
        "min_order_try": max(10.0, float(merged.get("min_order_try", config.AUTO_PAPER_MIN_ORDER_TRY))),
        "breakeven_trigger_pct": max(0.5, min(10.0, float(merged.get("breakeven_trigger_pct", config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT)))),
    }

    await database.set_llm_setting("auto_paper_settings", json.dumps(settings))
    await log_user_action(None, None, "auto_paper", "AUTO_PAPER_SETTINGS_UPDATE",
                          details={"settings": settings}, request=request)
    return {"paper_only": True, "ok": True, "settings": settings}


# ---------------------------------------------------------------------------
# Trades API
# ---------------------------------------------------------------------------
@router.get("/api/auto-paper/trades")
async def list_trades_endpoint(status: str | None = None, limit: int = 100, offset: int = 0):
    """Otonom paper trade kayıtlarını listele. Açık pozisyonlara güncel fiyat eklenir."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    trades = await database.list_auto_paper_trades(status=status or None, limit=limit, offset=offset)
    # Açık pozisyonlar için güncel ticker fiyatını ekle (frontend PnL hesabı için)
    for t in trades:
        if t.get("status") == "open":
            ticker = market.get_ticker(str(t.get("symbol") or "").upper())
            t["current_price"] = float(ticker.get("last_price") or 0) if ticker else None
    return {"paper_only": True, "trades": trades, "total": len(trades)}


@router.get("/api/auto-paper/stats")
async def get_stats_endpoint():
    """Otonom paper trade istatistikleri (reset_at sonrasi; reset kapanışları hariç)."""
    stats = await database.get_auto_paper_stats()
    return {
        "paper_only": True,
        "stats": stats,
        "state": dict(_AUTO_PAPER_STATE),
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def reset_state():
    """In-memory sayaçları sıfırla (admin reset sonrası restart beklemeden)."""
    _AUTO_PAPER_STATE.update({
        "total_opened": 0,
        "total_closed": 0,
        "total_pnl": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
        "last_check_at": None,
    })


def start_auto_paper_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(auto_paper_management_loop(), name="auto-paper-management")
    _background_tasks.add(_loop_task)
    return True


def stop_auto_paper_loop():
    """Döngüyü durdur (arka plan task havuzundan çıkar)."""
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _background_tasks.discard(_loop_task)
        _loop_task = None
