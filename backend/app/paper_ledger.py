"""Ortak paper defter modeli: dolum, tazelik kapısı ve komisyon sözleşmesi.

Üç paper defteri (auto_paper, combined_paper, velocity/analyzer) aynı fiyat ve
muhasebe kurallarını kullanır; kurallar buradan okunur ki birbirinden sapmasın.
Sayısal davranış değişmedi — bkz. backend/tests/test_paper_ledger.py.

Sözleşme:
  * Giriş dolumu  = fiyat × (1 + kayma)                               -> entry_fill
  * Tetik çıkışı  = min(anlık, tetik)  [stop/breakeven/trailing/TP]   -> exit_fill
    Piyasa çıkışı = anlık fiyat        [süre, pasif sembol, zorla]     -> exit_fill
  * Satış dolumu  = çıkış fiyatı × (1 − kayma)  (kapanışta uygulanır)  -> sell_fill
  * Komisyon      = her bacakta notional × COMMISSION_PCT           -> settle_close
  * Tazelik       = ticker yaşı ≤ MAX_TICKER_AGE_SEC                  -> is_fresh

`exit_fill` KAYMA ÖNCESİ tetik fiyatı döndürür; satış kaymasını `settle_close`
(veya `sell_fill`) kapanış anında uygular. Böylece aynı kayma iki kez
uygulanmaz.
"""
from __future__ import annotations

import time

from app.config import config

#: Tetikle çıkan kapanışlar: dolum tetik fiyatıyla anlık fiyatın KÖTÜSÜ (min).
TRIGGER_EXITS = frozenset({"take_profit", "stop_loss", "breakeven_stop", "trailing_stop"})
#: Piyasa çıkışları: anlık (son bilinen) fiyattan dolar.
MARKET_EXITS = frozenset({"max_duration", "no_profit_timeout", "symbol_deactivated",
                          "stale_force_close", "time_stop"})


def slippage_pct() -> float:
    """Tek kaynak: `config.ESTIMATED_SLIPPAGE_PCT` (kesir, ör. 0.00025)."""
    return float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)


def commission_pct() -> float:
    """Tek kaynak: `config.COMMISSION_PCT` (bacak başına kesir, ör. 0.0015)."""
    return float(getattr(config, "COMMISSION_PCT", 0.0015))


def max_ticker_age_sec() -> float:
    return float(config.MAX_TICKER_AGE_SEC)


def is_fresh(ticker_ts_ms, now_sec: float | None = None, max_age_sec: float | None = None) -> bool:
    """Ticker zaman damgası (ms) taze mi? Zaman damgası yoksa/0 ise BAYAT sayılır."""
    ts = float(ticker_ts_ms or 0)
    if ts <= 0:
        return False
    now = time.time() if now_sec is None else float(now_sec)
    limit = max_ticker_age_sec() if max_age_sec is None else float(max_age_sec)
    return (now * 1000.0 - ts) <= limit * 1000.0


def entry_fill(price: float, slippage: float | None = None) -> float:
    """Alış dolumu: fiyat × (1 + kayma)."""
    s = slippage_pct() if slippage is None else float(slippage)
    return float(price) * (1.0 + s)


def exit_fill(kind: str, current: float, trigger: float | None = None) -> float:
    """Kayma ÖNCESİ çıkış fiyatı.

    * Tetik çıkışları (stop/breakeven/trailing/TP): ``min(current, trigger)`` —
      gap'te tetik fiyatının altına düşen piyasa, stop'tan değil piyasadan dolar.
    * Piyasa çıkışları: ``current``.
    """
    if kind in TRIGGER_EXITS:
        if trigger is None:
            raise ValueError(f"tetik çıkışı için trigger gerekli: {kind}")
        return min(float(current), float(trigger))
    if kind in MARKET_EXITS:
        return float(current)
    raise ValueError(f"bilinmeyen çıkış türü: {kind}")


def sell_fill(price: float, slippage: float | None = None) -> float:
    """Satış dolumu: çıkış fiyatı × (1 − kayma)."""
    s = slippage_pct() if slippage is None else float(slippage)
    return float(price) * (1.0 - s)


def round_trip_markup(commission: float | None = None, slippage: float | None = None) -> float:
    """Gidiş-dönüş maliyet payı (kesir): 2 × komisyon + kayma.

    TP çapasına ve breakeven taban fiyatına eklenir ki bildirimdeki hedef NET
    gerçekleşsin.
    """
    c = commission_pct() if commission is None else float(commission)
    s = slippage_pct() if slippage is None else float(slippage)
    return 2.0 * c + s


def settle_close(entry_price: float, exit_price: float, quantity: float,
                 commission: float | None = None, slippage: float | None = None) -> dict:
    """Kapanış muhasebesi: satış dolumu, iki bacak komisyonu, net PnL.

    ``exit_price`` kayma ÖNCESİ çıkış fiyatıdır (bkz. `exit_fill`). Dönen
    ``pnl`` round-trip NET değerdir; ``pnl_pct`` aynı tabandan (giriş notional)
    türetilir.
    """
    c = commission_pct() if commission is None else float(commission)
    fill = sell_fill(exit_price, slippage)
    entry_commission = float(entry_price) * float(quantity) * c
    exit_commission = fill * float(quantity) * c
    total_commission = entry_commission + exit_commission
    gross_pnl = (fill - float(entry_price)) * float(quantity)
    pnl = gross_pnl - total_commission
    invested = float(entry_price) * float(quantity)
    pnl_pct = (pnl / invested * 100.0) if invested else 0.0
    return {
        "fill_price": fill,
        "gross_pnl": gross_pnl,
        "commission": total_commission,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }
