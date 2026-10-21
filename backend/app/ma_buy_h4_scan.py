"""Radar > "H4 kesişimleri" sekmesi — son 24 saatte H4 MA kesişimi olan likit TRY çiftleri (2026-10-21, kullanıcı isteği).

Kural H4 izleyicisiyle BİREBİR aynıdır (`ma_buy_profiles.profile("4h")`: MA 7/20/99, iki kural, `signals_from_bars`);
fark yalnız evrendedir: izleyici AKTİF sembolleri izleyip bildirir, bu tarama ise 24 sa hacmi
`MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME` (1M TL) üstündeki TÜM işlem gören çiftlere bakar — kullanıcı piyasanın tamamını
görmek istiyor. Her satıra izleyicinin kaydı eklenir (`notified`, `paper_status`): bildirilen / bildirilmeyen ayrımı görünür.

Maliyet: ~300 sembol × 1 klines isteği (130 mum). Sonuç bellekte önbelleklenir (`MA_BUY_H4_SCAN_TTL_SEC`, 10 dk; H4 mumu
4 saatte bir kapanır) ve tazeleme ARKA PLANDA tek uçuştur: istek önbelleği hemen döndürür, bayatsa tazelemeyi başlatır
(`refreshing: true`). İlk istekte önbellek boşken `items: []` + `refreshing: true` döner; arayüz yeniden sorar.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import database, ma_buy_notify, ma_buy_profiles, ma_buy_tracker
from app.binance_tr_public import klines as fetch_klines, ticker_24h, trading_symbols
from app.config import config

logger = logging.getLogger("scalper.ma_buy")

TF = "4h"
TF_MS = ma_buy_tracker.SUPPORTED_TF_MS[TF]
DEFAULT_HOURS = 24
FETCH_LIMIT = 130                 # yavaş MA 99 + 24 sa (6 mum) + tohum payı
_FETCH_CONCURRENCY = 4

_cache: dict = {"snapshot": None, "task": None, "last_error": None}


# ------------------------------------------------------------------------------------------------------- saf hesap
def signal_settings() -> dict:
    """Taramada kullanılan kural (izleyiciyle aynı kaynak). Profil kapalıysa genel ayarlar."""
    prof = ma_buy_profiles.profile(TF)
    if prof:
        return {"periods": tuple(prof["periods"]), "rules": tuple(prof["rules"]), "ma_type": prof["ma_type"],
                "require_mid_above_slow": bool(prof["require_mid_above_slow"]),
                "min_body_pct": float(prof["min_body_pct"]), "stoch_max": prof["stoch_max"],
                "profile": prof["name"], "stop_loss_pct": float(prof["stop_loss_pct"]),
                "max_hold_minutes": float(prof["max_hold_minutes"])}
    use_sma = str(getattr(config, "MA_BUY_MA_TYPE", "sma")).strip().lower() == "sma"
    return {"periods": tuple(ma_buy_tracker.periods()), "rules": None, "ma_type": "sma" if use_sma else "ema",
            "require_mid_above_slow": True, "min_body_pct": 0.0, "stoch_max": ma_buy_tracker.stoch_max(TF), "profile": None,
            "stop_loss_pct": None, "max_hold_minutes": None}


def crosses_from_bars(symbol: str, bars: list[dict], now_ms: int, hours: int = DEFAULT_HOURS,
                      settings: dict | None = None) -> list[dict]:
    """Son `hours` saatte KAPANAN H4 mumlarında tetiklenen kesişimler (saf; `signals_from_bars` üstüne pencere)."""
    st = settings or signal_settings()
    since_close = int(now_ms) - int(hours) * 3_600_000
    lookback = sum(1 for b in bars if b["open_ms"] + TF_MS >= since_close)
    if lookback <= 0:
        return []
    rows = ma_buy_tracker.signals_from_bars(symbol, TF, bars, now_ms, lookback=lookback, per=st["periods"],
                                            use_sma=st["ma_type"] == "sma", stoch_max=st["stoch_max"],
                                            rules_allowed=st["rules"], min_body_pct=st["min_body_pct"],
                                            require_mid_above_slow=bool(st.get("require_mid_above_slow", True)))
    return [r for r in rows if r["bar_close_ms"] >= since_close]


PEAK_TF = "5m"
PEAK_TF_MS = 300_000
PEAK_FETCH_LIMIT = 400            # 24 sa = 288 mum; 72 sa penceresi için son kısım yeter


def peak_metrics(signal_price: float, signal_close_ms: int, bars_after: list[dict], now_ms: int) -> dict:
    """Sinyal mumu kapanışından bu yana (5 dk mumlarla) zirve / dip / şu an (saf).

    Dönüş: max_rise_pct, max_rise_price, max_rise_at_ms (zirve mumunun kapanışı), minutes_to_max (kapanıştan zirveye),
    max_drop_pct, max_drop_at_ms, last_close, now_pct, elapsed_minutes, bars_after. Mum yoksa alanlar None (sinyal yeni)."""
    price = float(signal_price)
    use = [b for b in bars_after or [] if int(b["open_ms"]) >= int(signal_close_ms)]
    out = {"max_rise_pct": None, "max_rise_price": None, "max_rise_at_ms": None, "minutes_to_max": None,
           "max_drop_pct": None, "max_drop_price": None, "max_drop_at_ms": None, "last_close": None, "now_pct": None,
           "elapsed_minutes": round(max(0, int(now_ms) - int(signal_close_ms)) / 60_000.0, 1), "bars_after": len(use)}
    if price <= 0 or not use:
        return out

    def pct(x: float) -> float:
        return round((float(x) / price - 1.0) * 100.0, 4)

    highs = [float(b["high"]) for b in use]
    lows = [float(b["low"]) for b in use]
    hi = max(range(len(use)), key=lambda k: (highs[k], -k))     # eşitte İLK zirve
    lo = min(range(len(use)), key=lambda k: (lows[k], k))
    hi_close_ms = int(use[hi]["open_ms"]) + PEAK_TF_MS
    out.update({
        "max_rise_pct": pct(highs[hi]), "max_rise_price": highs[hi], "max_rise_at_ms": hi_close_ms,
        "minutes_to_max": round((hi_close_ms - int(signal_close_ms)) / 60_000.0, 1),
        "max_drop_pct": pct(lows[lo]), "max_drop_price": lows[lo], "max_drop_at_ms": int(use[lo]["open_ms"]) + PEAK_TF_MS,
        "last_close": float(use[-1]["close"]), "now_pct": pct(use[-1]["close"]),
    })
    return out


async def _peak_for(item: dict, now_ms: int, sem: asyncio.Semaphore) -> dict:
    async with sem:
        raw = await fetch_klines(item["symbol"], PEAK_TF, limit=PEAK_FETCH_LIMIT, start_time_ms=int(item["bar_close_ms"]))
    bars = ma_buy_tracker.closed_bars(raw, PEAK_TF_MS, now_ms)
    return peak_metrics(item["signal_price"], item["bar_close_ms"], bars, now_ms)


async def attach_peaks(items: list[dict], now_ms: int) -> int:
    """Her kesişime zirve/dip/şu an ölçümünü ekler (sembol başına bir 5 dk klines isteği). Dönüş: hata sayısı."""
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
    results = await asyncio.gather(*(_peak_for(it, now_ms, sem) for it in items), return_exceptions=True)
    errors = 0
    for it, res in zip(items, results):
        if isinstance(res, BaseException):
            errors += 1
            res = peak_metrics(it["signal_price"], it["bar_close_ms"], [], now_ms)
            res["peak_error"] = True
        it.update(res)
    return errors


def merge_tracker_rows(items: list[dict], tracked: list[dict]) -> list[dict]:
    """Tarama satırlarına izleyici kaydını (bildirildi mi, paper açıldı mı) ekler (saf)."""
    by_key = {(str(t.get("symbol") or "").upper(), int(t.get("bar_open_ms") or 0)): t for t in tracked or []
              if t.get("timeframe") == TF}
    out = []
    for it in items:
        t = by_key.get((it["symbol"], int(it["bar_open_ms"])))
        it = dict(it)
        it["tracked"] = t is not None
        it["notified"] = bool(t and t.get("push_ok"))
        it["notified_at"] = t.get("notified_at") if t else None
        it["paper_status"] = t.get("paper_status") if t else None
        it["paper_trade_id"] = t.get("paper_trade_id") if t else None
        out.append(it)
    return out


def _public(row: dict, ticker: dict | None, st: dict) -> dict:
    fast, mid, slow = st["periods"]
    return {
        "symbol": row["symbol"], "timeframe": TF,
        "rules": [r for r in str(row.get("rules") or "").split(",") if r],
        "bar_open_ms": int(row["bar_open_ms"]), "bar_close_ms": int(row["bar_close_ms"]),
        "signal_price": float(row["signal_price"]), "body_pct": row.get("body_pct"),
        "ma_fast": row.get("ema_fast"), "ma_mid": row.get("ema_mid"), "ma_slow": row.get("ema_slow"),
        "ma_label": f"{st['ma_type'].upper()} {fast}/{mid}/{slow}",
        "change_24h_pct": ticker.get("priceChangePercent") if ticker else None,
        "quote_volume_24h": ticker.get("quoteVolume") if ticker else None,
        "last_price": ticker.get("lastPrice") if ticker else None,
        "target_pct": ma_buy_notify.target_pct(TF),
        "stop_loss_pct": st["stop_loss_pct"], "max_hold_minutes": st["max_hold_minutes"],
    }


# ------------------------------------------------------------------------------------------------------- evren + tarama
async def universe(quote_asset: str = "TRY") -> list[dict]:
    """24 sa hacmi eşiğin üstündeki işlem gören TRY çiftleri (ticker satırıyla)."""
    floor = float(getattr(config, "MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME", 1_000_000) or 0)
    rows = await ticker_24h()
    trading = set(await trading_symbols(quote_asset))
    out = []
    for row in rows or []:
        sym = str(row.get("symbol") or "").replace("_", "").upper()
        if sym not in trading:
            continue
        try:
            qv = float(row.get("quoteVolume") or 0)
            change = float(row.get("priceChangePercent") or 0)
            last = float(row.get("lastPrice") or 0)
        except (TypeError, ValueError):
            continue
        if qv < floor:
            continue
        out.append({"symbol": sym, "quoteVolume": qv, "priceChangePercent": change, "lastPrice": last})
    out.sort(key=lambda r: -r["quoteVolume"])
    return out


async def _scan_symbol(symbol: str, now_ms: int, hours: int, st: dict, sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        raw = await fetch_klines(symbol, TF, limit=FETCH_LIMIT)
    bars = ma_buy_tracker.closed_bars(raw, TF_MS, now_ms)
    return crosses_from_bars(symbol, bars, now_ms, hours, st)


async def scan(now_ms: int | None = None, hours: int = DEFAULT_HOURS) -> dict:
    """Tam tarama (ağ + DB). Dönüş: anlık görüntü sözlüğü (önbelleğe yazılır)."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    st = signal_settings()
    syms = await universe()
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
    results = await asyncio.gather(*(_scan_symbol(s["symbol"], now_ms, hours, st, sem) for s in syms),
                                   return_exceptions=True)
    by_sym = {s["symbol"]: s for s in syms}
    items: list[dict] = []
    errors = 0
    for s, res in zip(syms, results):
        if isinstance(res, BaseException):
            errors += 1
            continue
        items.extend(_public(r, by_sym.get(s["symbol"]), st) for r in res)
    errors += await attach_peaks(items, now_ms)      # zirve / zirveye süre / şu an (kullanıcı isteği 18:30)
    try:
        tracked = await database.list_ma_buy_signals(now_ms - hours * 3_600_000 - TF_MS, limit=5000)
    except Exception as exc:  # noqa: BLE001 — izleyici kaydı okunamazsa liste yine gösterilir
        logger.debug("H4 tarama: izleyici kaydı okunamadı: %s", exc)
        tracked = []
    items = merge_tracker_rows(items, tracked)
    items.sort(key=lambda r: (-r["bar_close_ms"], -(r.get("quote_volume_24h") or 0), r["symbol"]))
    fast, mid, slow = st["periods"]
    return {
        "scanned_at": now_ms / 1000.0, "hours": int(hours), "symbols_scanned": len(syms), "errors": errors,
        "min_quote_volume": float(getattr(config, "MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME", 1_000_000) or 0),
        "rule": {"ma_type": st["ma_type"], "periods": [fast, mid, slow], "rules": list(st["rules"] or ()),
                 "require_mid_above_slow": bool(st.get("require_mid_above_slow", True)), "profile": st["profile"]},
        "items": items,
    }


# ------------------------------------------------------------------------------------------------------- önbellek
def ttl_sec() -> float:
    return float(getattr(config, "MA_BUY_H4_SCAN_TTL_SEC", 600) or 600)


def is_stale(snapshot: dict | None, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return snapshot is None or now - float(snapshot.get("scanned_at") or 0) > ttl_sec()


async def _refresh(hours: int) -> None:
    try:
        _cache["snapshot"] = await scan(hours=hours)
        _cache["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        _cache["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning("H4 kesişim taraması başarısız: %s", exc)
    finally:
        _cache["task"] = None


def _refreshing() -> bool:
    task = _cache.get("task")
    return task is not None and not task.done()


async def snapshot(hours: int = DEFAULT_HOURS, force: bool = False) -> dict:
    """Önbellekteki tarama; bayatsa/zorlanırsa arka planda tek uçuş tazeleme başlatır (bekletmez)."""
    snap = _cache.get("snapshot")
    if (force or is_stale(snap) or (snap and int(snap.get("hours") or 0) != int(hours))) and not _refreshing():
        _cache["task"] = asyncio.create_task(_refresh(int(hours)))
    out = dict(snap) if snap else {"scanned_at": None, "hours": int(hours), "symbols_scanned": 0, "errors": 0,
                                   "min_quote_volume": float(getattr(config, "MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME", 0) or 0),
                                   "rule": None, "items": []}
    out["refreshing"] = _refreshing()
    out["last_error"] = _cache.get("last_error")
    out["ttl_sec"] = ttl_sec()
    return out


def reset_cache() -> None:
    """Testler için."""
    _cache.update({"snapshot": None, "task": None, "last_error": None})


# ------------------------------------------------------------------------------------------------------- arka plan ısıtma
def seconds_until_next_bar_close(now_ms: int, grace_sec: float = 90.0) -> float:
    """Bir sonraki H4 mumu kapanışına (+ borsanın mumu sonlandırması için pay) kalan süre (saf)."""
    next_close = (int(now_ms) // TF_MS + 1) * TF_MS
    return max(1.0, (next_close - int(now_ms)) / 1000.0 + float(grace_sec))


async def h4_scan_warmup_loop() -> None:
    """Açılışta bir kez, sonra her H4 mumu kapanışında taramayı yeniler: sekme ilk açılışta boş kalmaz, 4 saatte bir
    taze kalır. Aradaki ziyaretlerde TTL (10 dk) dolmuşsa istek yolu zaten tazeler. Hata döngüyü öldürmez."""
    await asyncio.sleep(120)   # açılış patlaması (market warmup, izleyiciler) bitsin
    while True:
        try:
            if bool(getattr(config, "MA_BUY_TRACKER_ENABLED", True)):
                await snapshot(DEFAULT_HOURS, force=True)
                task = _cache.get("task")
                if task is not None:
                    await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("H4 kesişim ısıtma turu başarısız: %s", exc)
        await asyncio.sleep(seconds_until_next_bar_close(int(time.time() * 1000)))
