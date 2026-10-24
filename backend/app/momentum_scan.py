"""M1H — 1 saatlik yükseliş potansiyeli taraması (2026-10-24, kullanıcı isteği).

Soru: "Önümüzdeki 1 saatte yükselme ihtimali en yüksek coin hangisi?" Tek cevap momentumun devamıdır; bu modül onu ölçer.
Yalnız kesitten önce KAPANMIŞ 15 dk mumlar kullanılır (ileriye bakma yok). Her sembol için:
  r1/r2/r4/r24  : son 1 / 2 / 4 / 24 saat getirisi (%)
  vr            : son 1 saat TL hacmi / önceki 24 saatin saatlik ortalaması
  vwap_rel      : fiyatın 24 sa hacim ağırlıklı ortalamaya göre konumu (%)
  room          : 24 sa tepesine kalan yol (%)
  base          : sembolün kendi 7 günlük geçmişinde "15 dk kapanıştan sonraki 1 saatte +%2 görme" oranı (%)
  hl            : son 3 mumda yükselen dip sayısı (0–3)
  atr15         : son 16 mumun ortalama (yüksek − düşük) / kapanış (%)
Puan (WEIGHTS ile ayarlanır): momentum + hacim + VWAP üstü + yükselen dip + kendi oynaklık tabanı + tepeye "yer var ama
tavana yapışık değil"; son 1 saatte +%8'den fazla sıçrayan cezalandırılır (fitile alım yapmamak için).

Evren: Binance TR TRY pariteleri, 24 sa hacim ≥ MIN_QV, stabil/altın pariteleri hariç. Veri: Binance TR REST (672 × 15 dk);
`scan(..., bars_loader=...)` ile başka kaynak (yerel arşiv) verilebilir — scripts/ta_n6_tracker.py bunu kullanır.
Giriş fiyatı: kesitten önceki son 15 dk kapanışı (N6/N7 ile aynı). Saf fonksiyonlar (momentum_features, momentum_score,
rank) ağ gerektirmez; JS kopyası takip sayfasında (ta_n6_tracker.html_page) aynı ağırlıklarla çalışır.
"""
from __future__ import annotations

import asyncio
import logging
import statistics as st
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

M15 = 900_000
MIN_QV = 5e6                      # 24 sa TL hacmi tabanı (N6/N7 ile aynı)
MIN_BARS = 200                    # en az 50 saat geçmiş
KLINES_LIMIT = 672                # 7 gün × 96
BASE_TARGET_PCT = 2.0             # "kendi tabanı": 1 saatte +%2 görme oranı
STABLE = {"USDC", "FDUSD", "USDT", "XAUT", "PAXG", "EUR", "TRYB", "DAI", "TUSD", "EURI", "USD1", "USDE"}

# Puan ağırlıkları — tek yerde; sohbetteki (2026-10-24) elle koşulan sürümle aynı.
WEIGHTS = {
    "r1": 0.8, "r1_cap": 4.0,
    "r2": 0.4, "r2_cap": 6.0,
    "r4": 0.2, "r4_cap": 10.0,
    "vr": 1.0, "vr_cap": 4.0,
    "vwap": 1.0,                  # VWAP üstü +1, altı −1
    "hl": 0.5,                    # yükselen dip başına
    "base": 0.1, "base_cap": 40.0,  # taban oranı / 10 (en çok 4 puan)
    "room_ok": 1.0, "room_far": 0.3, "room_tight": -0.5,   # 1,5–8 % arası ideal; > 8 uzak; < 1,5 tavana yapışık
    "spike_pct": 8.0, "spike_pen": 2.0,
}

BarsLoader = Callable[[str], Awaitable[list[dict]]]


def momentum_features(b15: list[dict], cutoff_ms: int | None = None) -> dict | None:
    """Kapanmış 15 dk mumlardan (t, o, h, l, c, q) özellikler. cutoff_ms verilirse açık/sonraki mumlar atılır."""
    if cutoff_ms is not None:
        b15 = [b for b in b15 if b["t"] + M15 <= cutoff_ms]
    n = len(b15)
    if n < MIN_BARS:
        return None
    c = [b["c"] for b in b15]
    h = [b["h"] for b in b15]
    l_ = [b["l"] for b in b15]
    q = [b["q"] for b in b15]
    p = c[-1]
    if p <= 0:
        return None

    def ret(k: int) -> float:
        return (p / c[-1 - k] - 1) * 100 if n > k and c[-1 - k] > 0 else 0.0

    vol1 = sum(q[-4:])
    prev = q[max(0, n - 100):n - 4]
    volavg = sum(prev) / (len(prev) / 4) if prev else 0.0
    vr = vol1 / volavg if volavg > 0 else 0.0
    w = b15[-96:]
    qsum = sum(b["q"] for b in w)
    vwap = sum(b["c"] * b["q"] for b in w) / qsum if qsum > 0 else p
    hi24 = max(b["h"] for b in w)
    lo24 = min(b["l"] for b in w)
    hits = tot = 0
    tgt = 1 + BASE_TARGET_PCT / 100
    for i in range(0, n - 5):
        tot += 1
        if max(h[i + 1:i + 5]) >= c[i] * tgt:
            hits += 1
    base = hits / tot * 100 if tot else 0.0
    hl = sum(1 for i in range(-3, 0) if l_[i] > l_[i - 1])
    atr15 = st.mean((h[i] - l_[i]) / c[i] * 100 for i in range(-16, 0) if c[i] > 0)
    return {
        "px": p, "t": b15[-1]["t"], "r1": ret(4), "r2": ret(8), "r4": ret(16), "r24": ret(96), "vr": vr,
        "vwap": vwap, "vwap_rel": (p / vwap - 1) * 100 if vwap > 0 else 0.0,
        "hi24": hi24, "lo24": lo24, "room": (hi24 / p - 1) * 100, "base": base, "hl": hl, "atr15": atr15,
        "qv24": sum(q[-96:]),
    }


def momentum_score(f: dict, w: dict = WEIGHTS) -> float:
    def clamp(x: float, cap: float) -> float:
        return max(min(x, cap), -cap)

    sc = clamp(f["r1"], w["r1_cap"]) * w["r1"] + clamp(f["r2"], w["r2_cap"]) * w["r2"] + clamp(f["r4"], w["r4_cap"]) * w["r4"]
    sc += min(f["vr"], w["vr_cap"]) * w["vr"]
    sc += w["vwap"] if f["px"] > f["vwap"] else -w["vwap"]
    sc += f["hl"] * w["hl"]
    sc += min(f["base"], w["base_cap"]) * w["base"]
    room = f["room"]
    sc += w["room_ok"] if 1.5 <= room <= 8 else (w["room_far"] if room > 8 else w["room_tight"])
    if f["r1"] > w["spike_pct"]:
        sc -= w["spike_pen"]
    return sc


def is_stable(sym: str) -> bool:
    base = sym[:-3] if sym.endswith("TRY") else sym
    return base in STABLE


def rank(feats: dict[str, dict], top: int, min_qv: float = MIN_QV) -> tuple[list[dict], int]:
    """{sym: özellikler} → (puana göre ilk `top` satır, hacim/stabil filtresini geçen aday sayısı)."""
    rows = []
    for sym, f in feats.items():
        if f is None or is_stable(sym) or f["qv24"] < min_qv:
            continue
        r = dict(sym=sym, **f)
        r["score"] = momentum_score(f)
        rows.append(r)
    rows.sort(key=lambda r: -r["score"])
    return rows[:top], len(rows)


def rows_to_bars(raw) -> list[dict]:
    """Binance klines satırları → {t,o,h,l,c,q}."""
    out = []
    for k in raw or []:
        try:
            out.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "q": float(k[7])})
        except (TypeError, ValueError, IndexError):
            continue
    return out


async def bars_live(sym: str) -> list[dict]:
    """Binance TR REST'ten son 672 kapanmış/açık 15 dk mum (açık olan momentum_features'ta kesilir)."""
    from app.binance_tr_public import klines
    try:
        return rows_to_bars(await klines(sym, "15m", limit=KLINES_LIMIT))
    except Exception as exc:  # noqa: BLE001 — tek sembol hatası taramayı durdurmaz
        logger.warning("m1h klines alınamadı %s: %s", sym, exc)
        return []


async def scan(cutoff_ms: int, top: int = 3, bars_loader: BarsLoader | None = None, concurrency: int = 6,
               progress: Callable[[int, int], None] | None = None) -> dict:
    """Tüm TRY paritelerini tarar; scripts/ta_n6_tracker.build_list ile aynı şekilde sonuç sözlüğü döner.

    picked satırları: sym, px (giriş), score, r1/r2/r4/r24, vr (=vol_ratio), vwap_rel, room, base, hl, atr15, qv24, chg24.
    """
    from app.binance_tr_public import trading_symbols
    loader = bars_loader or bars_live
    syms = [s for s in sorted(await trading_symbols("TRY")) if not is_stable(s)]
    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()
    done = 0

    async def one(sym: str):
        nonlocal done
        async with sem:
            bars = await loader(sym)
        done += 1
        if progress:
            progress(done, len(syms))
        return sym, momentum_features(bars, cutoff_ms)

    feats = dict(await asyncio.gather(*(one(s) for s in syms)))
    universe = sum(1 for f in feats.values() if f is not None and f["qv24"] >= MIN_QV)
    picked, candidates = rank(feats, top)
    for r in picked:
        r["vol_ratio"] = r["vr"]
        r["chg24"] = r["r24"]
    return {"cutoff_ms": cutoff_ms, "breadth": 0.0, "universe": universe, "candidates": candidates, "picked": picked,
            "rule": "m1h", "n6_count": 0, "dropped": [], "force_top": True, "top": top, "manual": False,
            "depth_src": "", "depth_filter": False, "source": "rest" if bars_loader is None else "arşiv",
            "scanned": len(syms), "elapsed_s": round(time.time() - t0, 1)}
