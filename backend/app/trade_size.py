"""Defter (order book) tabanlı maksimum güvenli işlem tutarı — saf fonksiyonlar.

Üç sınırın en küçüğü:
  * giriş: ask'ları süpürürken ortalama kayma eşiği aşılmasın,
  * çıkış: giriş bandındaki bid derinliği (haircut ile) satışı kaldırsın,
  * hacim: 24s TRY hacminin küçük bir payı.
"""
from __future__ import annotations


def parse_levels(raw: list) -> list[tuple[float, float]]:
    """Binance depth [[fiyat_str, miktar_str], ...] -> [(fiyat, miktar), ...]."""
    return [(float(p), float(q)) for p, q in raw]


def sweep(asks: list[tuple[float, float]], amount_try: float) -> dict:
    """`amount_try` TRY'lik alımı ask'lar üzerinde süpür.

    avg_slip_pct = (ortalama/en iyi - 1) * 100.
    """
    if not asks or amount_try <= 0:
        return {"filled_try": 0.0, "qty": 0.0, "avg_price": 0.0,
                "avg_slip_pct": 0.0, "last_price": 0.0}
    best = asks[0][0]
    remaining = amount_try
    filled = 0.0
    qty = 0.0
    last = best
    for price, size in asks:
        if remaining <= 0:
            break
        level_try = price * size
        take = min(level_try, remaining)
        filled += take
        qty += take / price
        remaining -= take
        last = price
    avg = filled / qty if qty > 0 else 0.0
    slip = (avg / best - 1.0) * 100.0 if avg > 0 else 0.0
    return {"filled_try": filled, "qty": qty, "avg_price": avg,
            "avg_slip_pct": slip, "last_price": last}


def _entry_limit(asks: list[tuple[float, float]], max_avg_slip_pct: float) -> float:
    """Ortalama kayma eşiğini aşmayan en büyük TRY tutarı (kitap bitmişse tamamı)."""
    if not asks:
        return 0.0
    best = asks[0][0]
    bound = best * (1.0 + max_avg_slip_pct / 100.0)
    cum_try = 0.0
    cum_qty = 0.0
    for price, size in asks:
        level_try = price * size
        if price > bound:
            # (cum_try + s) / (cum_qty + s/price) <= bound
            s_max = (bound * cum_qty - cum_try) / (1.0 - bound / price)
            if s_max < level_try:
                return cum_try + max(s_max, 0.0)
        cum_try += level_try
        cum_qty += size
    return cum_try


def _exit_limit(bids: list[tuple[float, float]], bid_band_pct: float,
                bid_haircut: float) -> float:
    if not bids:
        return 0.0
    floor = bids[0][0] * (1.0 - bid_band_pct / 100.0)
    return sum(p * q for p, q in bids if p >= floor) * bid_haircut


def _exit_slip_pct(bids: list[tuple[float, float]], amount_try: float) -> float:
    """`amount_try` TRY'lik satışın bid'ler üzerindeki ortalama kayması (pozitif)."""
    if not bids or amount_try <= 0:
        return 0.0
    best = bids[0][0]
    remaining = amount_try
    filled = 0.0
    qty = 0.0
    for price, size in bids:
        if remaining <= 0:
            break
        take = min(price * size, remaining)
        filled += take
        qty += take / price
        remaining -= take
    if qty <= 0:
        return 0.0
    return (1.0 - (filled / qty) / best) * 100.0


def max_safe_amount(
    asks: list[tuple[float, float]],
    bids: list[tuple[float, float]],
    quote_volume_try: float,
    *,
    max_avg_slip_pct: float = 0.2,
    bid_band_pct: float = 1.0,
    bid_haircut: float = 0.4,
    volume_share: float = 0.02,
) -> dict:
    limits = {
        "entry": _entry_limit(asks, max_avg_slip_pct),
        "exit": _exit_limit(bids, bid_band_pct, bid_haircut),
        "volume": max(float(quote_volume_try or 0.0), 0.0) * volume_share,
    }
    binding = min(limits, key=lambda k: limits[k])
    amount = limits[binding]
    if amount <= 0:
        return {"amount_try": 0, "limits": limits, "binding": binding,
                "entry_slip_pct": 0.0, "exit_slip_pct": 0.0}
    return {
        "amount_try": amount,
        "limits": limits,
        "binding": binding,
        "entry_slip_pct": sweep(asks, amount)["avg_slip_pct"],
        "exit_slip_pct": _exit_slip_pct(bids, amount),
    }


def gross_target_pct(net_pct: float, entry_slip_pct: float,
                     exit_slip_pct: float, fee_frac: float) -> float:
    """Net hedef + giriş/çıkış kayması + iki yön komisyon (yüzde puan)."""
    return net_pct + entry_slip_pct + exit_slip_pct + 2.0 * fee_frac * 100.0
