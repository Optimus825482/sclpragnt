"""MA BUY — zaman dilimine göre EK giriş kuralları (2026-10-21, kullanıcı tablosu).

    M15 : sinyal mumu yükseliş gövdeli ve gövde ≥ %1, RSI14 45–65
    M30 : MACD(12,26,9) histogramı bir önceki muma göre artıyor, ADX14 > 20
    H1  : son 3 mum art arda yükseliş (kapanışlar artan), dalga geniş (son 3 mumun toplam aralığı ≥ %2), RSI14 45–65, ADX14 > 20
    Diğer dilimler: ek kural yok.

Saf hesap; tüm göstergeler nedensel (yalnız geçmiş mumlar) olduğu için seri bir kez hesaplanıp sinyal indeksinde okunur.
Belirsiz ifadelerin yorumu (raporda da yazılır): "mum boyu" = gövde (kapanış−açılış)/açılış; "dalga geniş" = 3 mumluk aralık.
"""
from __future__ import annotations

from typing import Callable, Sequence

from app import ma_buy_signals

DEFAULTS = {"body_min_pct": 1.0, "rsi_lo": 45.0, "rsi_hi": 65.0, "adx_min": 20.0, "wave_min_pct": 2.0,
            "rsi_len": 14, "adx_len": 14, "macd": (12, 26, 9)}


def _rma(values: list, period: int) -> list:
    """Wilder yumuşatması: ilk değer ilk `period` toplamının ortalaması, sonra (prev*(n-1)+x)/n."""
    out: list = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def adx_series(bars: Sequence[dict], period: int = 14) -> list:
    """Wilder ADX; ısınma boyunca None. bars: {high, low, close}."""
    n = len(bars)
    out: list = [None] * n
    if n < 2 * period:
        return out
    tr, pdm, mdm = [], [], []
    for i in range(1, n):
        h, l, c0 = float(bars[i]["high"]), float(bars[i]["low"]), float(bars[i - 1]["close"])
        ph, pl = float(bars[i - 1]["high"]), float(bars[i - 1]["low"])
        tr.append(max(h - l, abs(h - c0), abs(l - c0)))
        up, down = h - ph, pl - l
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    tr_s, p_s, m_s = _rma(tr, period), _rma(pdm, period), _rma(mdm, period)
    dx: list = []
    dx_idx: list = []
    for j in range(len(tr)):
        if tr_s[j] is None or not tr_s[j]:
            continue
        di_p, di_m = 100.0 * p_s[j] / tr_s[j], 100.0 * m_s[j] / tr_s[j]
        s = di_p + di_m
        dx.append(100.0 * abs(di_p - di_m) / s if s else 0.0)
        dx_idx.append(j + 1)          # bars indeksine çevir (tr[j] = bar j+1)
    adx = _rma(dx, period)
    for k, i in enumerate(dx_idx):
        if adx[k] is not None:
            out[i] = adx[k]
    return out


def macd_hist_series(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> list:
    ef = ma_buy_signals.ema_series(closes, fast)
    es = ma_buy_signals.ema_series(closes, slow)
    macd_vals, idx = [], []
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            macd_vals.append(ef[i] - es[i])
            idx.append(i)
    sig = ma_buy_signals.ema_series(macd_vals, signal)
    out: list = [None] * len(closes)
    for k, i in enumerate(idx):
        if sig[k] is not None:
            out[i] = macd_vals[k] - sig[k]
    return out


def feature_series(bars: Sequence[dict], cfg: dict | None = None) -> Callable[[int], dict]:
    """Sinyal indeksine göre özellik sözlüğü üreten fonksiyon döner (seriler bir kez hesaplanır)."""
    c = {**DEFAULTS, **(cfg or {})}
    closes = [float(b["close"]) for b in bars]
    rsi = ma_buy_signals.rsi_series(closes, int(c["rsi_len"]))
    adx = adx_series(bars, int(c["adx_len"]))
    hist = macd_hist_series(closes, *c["macd"])

    def at(i: int) -> dict:
        return {"rsi": rsi[i], "adx": adx[i], "macd_hist": hist[i], "macd_hist_prev": hist[i - 1] if i > 0 else None}
    return at


def passes_rules(tf: str, bars: Sequence[dict], i: int, feats: dict, **overrides) -> tuple[bool, str]:
    """(geçti mi, elenme nedeni). Bilinmeyen dilim → (True, "")."""
    c = {**DEFAULTS, **overrides}
    rsi, adx = feats.get("rsi"), feats.get("adx")

    def rsi_ok() -> tuple[bool, str]:
        if rsi is None or not (c["rsi_lo"] <= rsi <= c["rsi_hi"]):
            return False, f"rsi aralık dışı ({'yok' if rsi is None else f'{rsi:.1f}'})"
        return True, ""

    def adx_ok() -> tuple[bool, str]:
        if adx is None or adx <= c["adx_min"]:
            return False, f"adx ≤ {c['adx_min']:g} ({'yok' if adx is None else f'{adx:.1f}'})"
        return True, ""

    if tf == "15m":
        b = bars[i]
        o, cl = float(b["open"]), float(b["close"])
        body = (cl - o) / o * 100.0 if o else 0.0
        if body < c["body_min_pct"]:
            return False, f"mum gövdesi < %{c['body_min_pct']:g} ({body:+.2f}%)"
        return rsi_ok()
    if tf == "30m":
        h, hp = feats.get("macd_hist"), feats.get("macd_hist_prev")
        if h is None or hp is None or not h > hp:
            return False, "macd histogram artmıyor"
        return adx_ok()
    if tf == "1h":
        if i < 2:
            return False, "yetersiz mum"
        c0, c1, c2 = (float(bars[j]["close"]) for j in (i - 2, i - 1, i))
        if not (c2 > c1 > c0):
            return False, "son 3 mum yükseliş değil"
        hi = max(float(bars[j]["high"]) for j in (i - 2, i - 1, i))
        lo = min(float(bars[j]["low"]) for j in (i - 2, i - 1, i))
        wave = (hi - lo) / lo * 100.0 if lo else 0.0
        if wave < c["wave_min_pct"]:
            return False, f"dalga dar ({wave:.2f}% < %{c['wave_min_pct']:g})"
        ok, why = rsi_ok()
        if not ok:
            return False, why
        return adx_ok()
    return True, ""


def apply_rules(tf: str, bars: Sequence[dict], signals: Sequence[dict], feature_fn: Callable[[int], dict], **overrides):
    """Sinyalleri ek kuraldan geçirir → (kalanlar, elenenler[{index, reason}]). Kuralı olmayan dilimde liste aynen döner."""
    if tf not in ("15m", "30m", "1h"):
        return list(signals), []
    kept, dropped = [], []
    for sig in signals:
        ok, why = passes_rules(tf, bars, int(sig["index"]), feature_fn(int(sig["index"])) or {}, **overrides)
        (kept if ok else dropped).append(sig if ok else {"index": sig["index"], "reason": why})
    return kept, dropped
