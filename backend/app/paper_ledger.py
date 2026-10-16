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

import logging
import time

from app.config import config

logger = logging.getLogger("scalper.paper_ledger")

#: Tetikle çıkan kapanışlar: dolum tetik fiyatıyla anlık fiyatın KÖTÜSÜ (min).
TRIGGER_EXITS = frozenset({"take_profit", "stop_loss", "breakeven_stop", "trailing_stop"})
#: Piyasa çıkışları: anlık (son bilinen) fiyattan dolar.
MARKET_EXITS = frozenset({"max_duration", "no_profit_timeout", "symbol_deactivated",
                          "stale_force_close", "time_stop"})


def slippage_pct() -> float:
    """Tek kaynak: `config.ESTIMATED_SLIPPAGE_PCT` (kesir, ör. 0.00025)."""
    return float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)


def commission_pct() -> float:
    """Tek kaynak: EFEKTİF bacak başı komisyon (kesir).

    2026-10-16 (maliyet/çıkış): artık `config.COMMISSION_PCT` ham değeri DEĞİL,
    `config.effective_commission_pct()` — öncelik
    COMMISSION_PCT_OVERRIDE > BNB modu (taban × (1 − indirim/100)) > taban.
    Varsayılanlarla 0.0015 × 0.75 = 0.001125. auto_paper / combined_paper /
    analyzer hepsi buradan okur; `config.COMMISSION_PCT`'yi doğrudan okuyan
    yer kalırsa BNB indirimi oraya yansımaz (database.py raporlama satırları
    bilinçli olarak dokunulmadı — bkz. DENEY_KAYDI 2026-10-16).
    """
    eff = getattr(config, "effective_commission_pct", None)
    if callable(eff):
        try:
            return float(eff())
        except Exception:  # noqa: BLE001 — config bozuksa taban orana düş
            pass
    return float(getattr(config, "COMMISSION_PCT", 0.0015))


def commission_model() -> dict:
    """2026-10-16 (maliyet/çıkış): UI/log için komisyon modeli özeti.

    {base, bnb_mode, discount_pct, override, effective, round_trip} — hepsi
    KESİR (round_trip = 2×efektif + 2×kayma). Kaynak `commission_pct()`.
    """
    base = float(getattr(config, "COMMISSION_PCT", 0.0015))
    override = getattr(config, "COMMISSION_PCT_OVERRIDE", None)
    try:
        override = float(override) if override is not None else None
    except (TypeError, ValueError):
        override = None
    effective = commission_pct()
    return {
        "base": base,
        "bnb_mode": bool(getattr(config, "COMMISSION_BNB_MODE", False)),
        "discount_pct": float(getattr(config, "COMMISSION_BNB_DISCOUNT_PCT", 0.0) or 0.0),
        "override": override,
        "effective": effective,
        "round_trip": 2.0 * effective + 2.0 * slippage_pct(),
    }


def _log_commission_model_once() -> None:
    """Başlangıçta efektif komisyon modelini bir kez logla (import anında)."""
    try:
        m = commission_model()
        logger.info(
            "paper komisyon modeli: efektif %%%.4f/bacak (taban %%%.4f, BNB modu %s, indirim %%%.1f, override %s) | gidiş-dönüş %%%.4f",
            m["effective"] * 100, m["base"] * 100, "AÇIK" if m["bnb_mode"] else "KAPALI",
            m["discount_pct"], "yok" if m["override"] is None else f"{m['override'] * 100:.4f}%",
            m["round_trip"] * 100,
        )
    except Exception:  # noqa: BLE001 — log asla import'u düşürmesin
        logger.debug("paper komisyon modeli loglanamadı", exc_info=True)


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


# 2026-10-16 (maliyet/çıkış): efektif komisyon modeli başlangıçta bir kez loglanır.
_log_commission_model_once()
