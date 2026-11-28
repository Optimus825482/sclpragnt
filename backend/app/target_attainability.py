"""Sembol hedef ulaşılabilirliği: "%3 hedefi bu sembolde gerçekten oluşur mu?"

# 2026-11-27 (araştırma sonucu): 1 sn'lik Binance verisinde 60 sn'de +%3 hiç
# oluşmadı; 15 dk'da majörlerde (BTC/ETH/SOL/LINK, p99 %0,7-1,5) yine hiç
# oluşmadı, küçük cap'lerde (p99 %3-9) oluşuyor. Yani hedef yüzdesini sabit
# tutmak, sembolün kendi oynaklığından bağımsız bir varsayım. Bu modül her
# sembol için KENDİ 5m/15m kline'ından ileri maksimum hareket dağılımını ölçer:
#   p50/p95/p99 ileri maksimum, ve hedefe ulaşan mum oranı (`ge_target`).
#
# İki ayrı kullanım:
#   * `stats(symbol)` — SENKRON, yalnız önbellek okur; taranan satıra ölçüm
#     alanı eklemek için (davranışı değiştirmez).
#   * `block_reason(symbol, target_pct)` — SENKRON kapı. 2026-11-27'de ürün
#     sahibi kararıyla AÇIK (varsayılan "1"); kapatmak için
#     `RADAR_TARGET_ATTAINABILITY_GATE=0`. Kural: sembolün p99 ileri maksimumu
#     hedefin altındaysa (p99 < hedef x 1,0) hedef "piyango" sayılır ve aday
#     engellenir. Veri yoksa/bayatsa fail-open (None) — kapı asla ölçüm
#     yokluğunda aday düşürmez.
#
# Ağ çağrısı yalnız `refresh_for` içindedir (asenkron, TTL'li, sembol başına
# önbellek); aynı sembol TTL dolmadan yeniden indirilmez.
"""

import asyncio
import logging
import os
import time

import numpy as np

from app import binance_tr_public

logger = logging.getLogger("scalper.target_attainability")

GATE_ENABLED = os.getenv("RADAR_TARGET_ATTAINABILITY_GATE", "1").strip().lower() in {"1", "true", "yes", "on"}
TTL_SEC = max(300, int(os.getenv("RADAR_TARGET_ATTAINABILITY_TTL_SEC", "1800")))
MIN_BARS = max(120, int(os.getenv("RADAR_TARGET_ATTAINABILITY_MIN_BARS", "200")))
# Kapı eşiği: hedefin bu katının altındaki p99 ulaşılamaz sayılır.
# 2026-11-27 ölçümü: 0,5 çarpanı fazla gevşekti (ETH p99 1,54 iken %3'ü
# saniyelerin yalnız %0,1'inde görüyor ve sınırda geçiyordu) → 1,0.
BLOCK_FACTOR = float(os.getenv("RADAR_TARGET_ATTAINABILITY_BLOCK_FACTOR", "1.0"))
MAX_WORKERS = max(1, int(os.getenv("RADAR_TARGET_ATTAINABILITY_WORKERS", "4")))
DEFAULT_TARGET_PCT = 3.0

# (interval, ileri mum sayısı) — ufuk eşlemesi
_HORIZON_BARS = {"5m": ("5m", 1), "15m": ("15m", 1), "45m": ("15m", 3)}
_CACHE: dict[str, dict] = {}
_INFLIGHT: dict[str, float] = {}


def forward_max_ratios(highs, closes, k: int) -> np.ndarray:
    """Her mum kapanışından sonraki k mumun en yükseğine oran (yüzde değil)."""
    highs = np.asarray(highs, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    out = np.full(n, np.nan)
    if n < 2 or k < 1:
        return out
    for i in range(n - 1):
        end = min(i + k, n - 1)
        if end <= i:
            continue
        window = highs[i + 1 : end + 1]
        if np.isfinite(window).any() and closes[i] > 0:
            out[i] = np.nanmax(window) / closes[i] - 1
    return out


def stats_for_klines(rows, target_pct: float, interval_label: str, k: int) -> dict | None:
    """Ham kline listesinden dağılım özeti. Yetersiz/geçersiz veride None.

    REST `klines` son satırda HÂLÂ OLUŞAN mumu döndürür; onun high'ı eksik
    olduğu için ileri maksimum dağılımını aşağı çeker. Bu yüzden son satır
    atılır (kapalı mumlarla ölçüm yapılır).
    """
    if not rows:
        return None
    if len(rows) > MIN_BARS:
        rows = rows[:-1]
    try:
        highs = [float(r[2]) for r in rows]
        closes = [float(r[4]) for r in rows]
    except (TypeError, ValueError, IndexError):
        return None
    ratios = forward_max_ratios(highs, closes, k)
    ratios = ratios[np.isfinite(ratios)]
    if len(ratios) < MIN_BARS:
        return None
    target = float(target_pct) / 100.0 if target_pct and target_pct > 0 else DEFAULT_TARGET_PCT / 100.0
    return {
        "interval": interval_label,
        "bars": int(len(ratios)),
        "p50": round(100 * float(np.quantile(ratios, 0.50)), 3),
        "p95": round(100 * float(np.quantile(ratios, 0.95)), 3),
        "p99": round(100 * float(np.quantile(ratios, 0.99)), 3),
        "max": round(100 * float(ratios.max()), 3),
        "ge_target": round(100 * float((ratios >= target).mean()), 3),
        "target_pct": round(target * 100, 2),
    }


async def _fetch_one(symbol: str, target_pct: float, sem: asyncio.Semaphore) -> None:
    """Bir sembolün 5m/15m dağılımını indirip önbelleğe yazar (fail-open)."""
    sym = str(symbol or "").replace("_", "").upper()
    if not sym:
        return
    entry: dict = {"symbol": sym, "loaded_at": time.time()}
    try:
        async with sem:
            rows15 = await binance_tr_public.klines(sym, "15m", 400)
            rows5 = await binance_tr_public.klines(sym, "5m", 400)
        s15 = stats_for_klines(rows15, target_pct, "15m", 1)
        s45 = stats_for_klines(rows15, target_pct, "45m", 3)
        s5 = stats_for_klines(rows5, target_pct, "5m", 1)
        if not s15:
            return
        entry.update({"by_horizon": {"5m": s5, "15m": s15, "45m": s45}, "primary": s15})
        pm = s15["p99"]
        entry["verdict"] = "reachable" if pm >= s15["target_pct"] else "unreachable"
        _CACHE[sym] = entry
    except Exception as exc:  # noqa: BLE001 - tarama yolunu asla düşürmemeli
        logger.debug("ulaşılabilirlik alınamadı %s: %s", sym, exc)
    finally:
        _INFLIGHT.pop(sym, None)


def _stale(sym: str) -> bool:
    entry = _CACHE.get(sym)
    if not entry:
        return True
    return (time.time() - float(entry.get("loaded_at") or 0)) > TTL_SEC


async def refresh_for(symbols, target_pct: float | None = None) -> int:
    """Verilen semboller için TTL'i geçmişleri yeniler. Döner: indirilen sayısı.

    Sembol listesi TEKİLLEŞTİRİLİR: aynı sembol iki kez verilirse eskiden iki
    paralel indirme başlıyordu (çift kota, çift gecikme).
    """
    target = float(target_pct or DEFAULT_TARGET_PCT)
    seen: set[str] = set()
    todo: list[str] = []
    for raw in symbols or []:
        sym = str(raw or "").replace("_", "").upper()
        if sym and sym not in seen and _stale(sym) and sym not in _INFLIGHT:
            seen.add(sym)
            todo.append(sym)
    now = time.time()
    for sym in todo:
        _INFLIGHT[sym] = now
    if not todo:
        return 0
    sem = asyncio.Semaphore(MAX_WORKERS)
    await asyncio.gather(*[_fetch_one(s, target, sem) for s in todo], return_exceptions=True)
    return len(todo)


def refresh_background(symbols, target_pct: float | None = None) -> asyncio.Task | None:
    """Taramayı BLOKLAMADAN yenileme başlat (fire-and-forget).

    Kapı fail-open olduğu için ölçümün aynı turda hazır olması gerekmez;
    ölçüm bir sonraki turda kullanılır. Olay döngüsü yoksa None.
    """
    try:
        return asyncio.get_running_loop().create_task(refresh_for(symbols, target_pct))
    except RuntimeError:
        return None


def stats(symbol: str) -> dict | None:
    """SENKRON: önbellekteki ölçüm (yoksa None). Ağ çağrısı yapmaz."""
    return _CACHE.get(str(symbol or "").replace("_", "").upper())


def _horizon_stats(entry: dict, horizon_minutes) -> dict:
    try:
        h = int(horizon_minutes or 15)
    except (TypeError, ValueError):
        h = 15
    key = "5m" if h <= 5 else "15m" if h <= 15 else "45m"
    return (entry.get("by_horizon") or {}).get(key) or entry.get("primary") or {}


def block_reason(symbol: str, target_pct=None, horizon_minutes=None) -> str | None:
    """2026-11-27: hedef bu sembolde ulaşılamazsa blok nedeni döner.

    Fail-open: bayrak kapalı, önbellek boş/bayat veya örnek yetersizse None.
    Kural: `p99 < hedef x BLOCK_FACTOR` (varsayılan 1,0) → "hedef_ulasilamaz:...".
    Ufuk, `horizon_minutes` ile seçilir (≤5 dk → 5m, ≤15 → 15m, üstü → 45m);
    ilgili ufuk ölçümü yoksa `primary` (15m) dağılımı kullanılır.
    """
    if not GATE_ENABLED:
        return None
    sym = str(symbol or "").replace("_", "").upper()
    entry = _CACHE.get(sym)
    if not entry or (time.time() - float(entry.get("loaded_at") or 0)) > TTL_SEC:
        return None
    st = _horizon_stats(entry, horizon_minutes)
    if not st:
        return None
    try:
        target = float(target_pct) if target_pct is not None else float(st.get("target_pct") or DEFAULT_TARGET_PCT)
    except (TypeError, ValueError):
        return None
    if target <= 0:
        return None
    floor = target * BLOCK_FACTOR
    if float(st.get("p99") or 0.0) < floor:
        return (
            f"hedef_ulasilamaz:p99_{st.get('interval')}={float(st.get('p99') or 0):.2f}<{floor:.2f} hedef={target:.2f}"
        )
    return None


def reset_for_tests() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()
