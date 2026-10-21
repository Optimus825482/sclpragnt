"""Giriş tetikleyicileri — MA kesişimine alternatif saf dedektörler (2026-10-20).

NEDEN: 90 günlük canlı-evren replay + çıkış simülasyonu MA 7/20/99 kesişiminin beklentisini sıfıra yakın (net ≈ −maliyet)
buldu ve yedi basit filtre bunu değiştirmedi. Bu modül aynı replay / simülasyon aracıyla ölçülebilsin diye farklı giriş
tetikleyicilerini `detect_ma_buy` ile AYNI biçimde döndürür: `[{"index": i, "rules": [id]}]`, indeks artan.

Her dedektör yalnız sinyal mumunun KAPANIŞINA kadar bilinen veriyi kullanır (ileri bakış yok). Bar: {open, high, low,
close, volume}.
"""
from __future__ import annotations

import math
from typing import Sequence

from app import ma_buy_signals


def _closes(bars: Sequence[dict]) -> list[float]:
    return [float(b["close"]) for b in bars]


def detect_ma_cross(bars: Sequence[dict], *, periods=(7, 20, 99), use_sma: bool = True, stoch_max: float | None = 80.0) -> list:
    return [{"index": h["index"], "rules": ["ma_cross"]}
            for h in ma_buy_signals.detect_ma_buy(_closes(bars), periods, use_sma=use_sma, slow_cross=True, stoch_max=stoch_max)]


def detect_stoch_turn(bars: Sequence[dict], *, level: float = 20.0, rsi_len: int = 14, stoch_len: int = 14,
                      k_len: int = 3, d_len: int = 3) -> list:
    """StochRSI K, D'yi aşağıdan yukarı keser ve bir önceki K `level` altındadır (aşırı satımdan dönüş)."""
    closes = _closes(bars)
    k = ma_buy_signals.stoch_rsi_k(closes, rsi_len, stoch_len, k_len)
    d = ma_buy_signals._sma_opt(k, d_len)
    out = []
    for i in range(1, len(closes)):
        k0, d0, k1, d1 = k[i - 1], d[i - 1], k[i], d[i]
        if None in (k0, d0, k1, d1):
            continue
        if k0 <= d0 and k1 > d1 and k0 < level:
            out.append({"index": i, "rules": ["stoch_turn"]})
    return out


def detect_breakout_vol(bars: Sequence[dict], *, lookback: int = 20, vol_mult: float = 2.0) -> list:
    """Kapanış önceki `lookback` mumun en yüksek `high`'ını aşar VE hacim önceki `lookback` ortalamasının ≥ `vol_mult` katı."""
    out = []
    for i in range(lookback, len(bars)):
        window = bars[i - lookback:i]
        prior_high = max(float(b["high"]) for b in window)
        avg_vol = sum(float(b.get("volume") or 0.0) for b in window) / lookback
        vol = float(bars[i].get("volume") or 0.0)
        if float(bars[i]["close"]) > prior_high and avg_vol > 0 and vol >= vol_mult * avg_vol:
            out.append({"index": i, "rules": ["breakout_vol"]})
    return out


def detect_pullback_sma20(bars: Sequence[dict], *, fast: int = 20, slow: int = 99) -> list:
    """Yükseliş trendinde (SMA_fast > SMA_slow) önceki mumun `low`'u SMA_fast'a değer/altına iner, mevcut mum SMA_fast
    üstünde kapanır (geri çekilme + tutunma)."""
    closes = _closes(bars)
    s_fast = ma_buy_signals.sma_series(closes, fast)
    s_slow = ma_buy_signals.sma_series(closes, slow)
    out = []
    for i in range(1, len(bars)):
        f0, f1, sl1 = s_fast[i - 1], s_fast[i], s_slow[i]
        if f0 is None or f1 is None or sl1 is None:
            continue
        if f1 > sl1 and float(bars[i - 1]["low"]) <= f0 and closes[i] > f1:
            out.append({"index": i, "rules": ["pullback_sma20"]})
    return out


def detect_rsi_cross30(bars: Sequence[dict], *, period: int = 14, level: float = 30.0) -> list:
    closes = _closes(bars)
    r = ma_buy_signals.rsi_series(closes, period)
    out = []
    for i in range(1, len(closes)):
        r0, r1 = r[i - 1], r[i]
        if r0 is None or r1 is None:
            continue
        if r0 <= level < r1:
            out.append({"index": i, "rules": ["rsi_cross30"]})
    return out


def detect_bb_reentry(bars: Sequence[dict], *, period: int = 20, mult: float = 2.0) -> list:
    """Önceki mum alt Bollinger bandının altında kapanmış, mevcut mum bandın üstünde kapanır (bant içine dönüş)."""
    closes = _closes(bars)
    out = []
    for i in range(period, len(closes)):
        def lower(j: int) -> float | None:
            w = closes[j - period + 1:j + 1]
            if len(w) < period:
                return None
            m = sum(w) / period
            sd = math.sqrt(sum((x - m) ** 2 for x in w) / period)
            return m - mult * sd
        lo0, lo1 = lower(i - 1), lower(i)
        if lo0 is None or lo1 is None:
            continue
        if closes[i - 1] < lo0 and closes[i] > lo1:
            out.append({"index": i, "rules": ["bb_reentry"]})
    return out


TRIGGERS = [
    {"id": "ma_cross", "title": "MA 7/20/99 kesişimi (taban)", "fn": detect_ma_cross},
    {"id": "stoch_turn", "title": "StochRSI K>D yukarı kesişim, K<20'den", "fn": detect_stoch_turn},
    {"id": "breakout_vol", "title": "20 mum zirve kırılımı + hacim ≥2×", "fn": detect_breakout_vol},
    {"id": "pullback_sma20", "title": "Yükselişte SMA20'ye geri çekilme + tutunma", "fn": detect_pullback_sma20},
    {"id": "rsi_cross30", "title": "RSI14 30'u yukarı keser", "fn": detect_rsi_cross30},
    {"id": "bb_reentry", "title": "Alt Bollinger bandından içeri dönüş", "fn": detect_bb_reentry},
]


def detect(trigger_id: str, bars: Sequence[dict], **kwargs) -> list:
    for t in TRIGGERS:
        if t["id"] == trigger_id:
            return t["fn"](bars, **kwargs)
    raise KeyError(trigger_id)
