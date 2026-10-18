"""MA şerit BUY sinyal izleyici: tara → kaydet → 15 dk sonra ölç (yalnız yönetici sayfası için; emir/karar YOK).

2026-10-18 (kullanıcı isteği). Her taramada (varsayılan 30 sn) AKTİF sembollerin (`symbol_activity_status` = ACTIVE; yoksa
izlenen semboller) yeni kapanmış 5 dk mumu için kural `app/ma_buy_signals.py` ile (grafikteki BUY rozetiyle BİREBİR) değerlendirilir.
Tetiklenen sinyal `ma_buy_signals` tablosuna yazılır (tekrar yazılmaz); sinyal mumu kapanışından 15 dk sonra sonraki 3 mumdan
en yüksek yükseliş / en büyük düşüş / 15. dk kapanışı ölçülüp aynı satıra işlenir.

Veri kaynağı grafikle aynıdır (`binance_tr_public.klines`): son 250 mum çekilir (EMA(99) tohum etkisi grafikteki 200 mumla
örtüşsün), açık (kapanmamış) mum atılır. Mum başına bir kez çağrılır (sembol/zaman dilimi başına son işlenen mum hatırlanır).
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time

from app import database, ma_buy_signals, notify_metrics
from app.binance_tr_public import klines as fetch_klines
from app.config import config

logger = logging.getLogger("scalper.ma_buy")

SUPPORTED_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
HORIZON_MIN = 15
FETCH_LIMIT = 250
CLOSE_SKEW_MS = 1_500          # sunucu saati ileride olsa da kapanmamış mum alınmasın
DUE_GRACE_MS = 2_000           # mum kapanışından sonra borsanın mumu sonlandırması için bekleme
NO_DATA_AFTER_MS = 6 * 3_600_000
_FETCH_CONCURRENCY = 4

_state: dict = {"last_scan_at": None, "last_scan_symbols": 0, "last_error": None, "seen": {}, "last_prune": 0.0,
                "last_evaluated": 0, "last_inserted": 0}


# ---------------------------------------------------------------------------------------------------------- config
def timeframes() -> list[str]:
    raw = str(getattr(config, "MA_BUY_TIMEFRAMES", "5m") or "5m")
    out = [t.strip() for t in raw.split(",") if t.strip() in SUPPORTED_TF_MS]
    return list(dict.fromkeys(out)) or ["5m"]


def periods() -> tuple:
    raw = str(getattr(config, "MA_BUY_PERIODS", "7,20,99") or "")
    try:
        vals = [int(float(x)) for x in raw.split(",") if x.strip()]
    except ValueError:
        vals = []
    return tuple(vals) if len(vals) == 3 and all(v >= 1 for v in vals) else ma_buy_signals.DEFAULT_PERIODS


def stoch_max(tf: str = "5m") -> float | None:
    """2. kural StochRSI K üst sınırı (varsayılan 80). `MA_BUY_STOCH_OFF_TIMEFRAMES` (varsayılan "1m") zaman dilimlerinde,
    ya da değer 100+/geçersizse sınır yok (None)."""
    off = {t.strip() for t in str(getattr(config, "MA_BUY_STOCH_OFF_TIMEFRAMES", "1m") or "").split(",") if t.strip()}
    if tf in off:
        return None
    try:
        v = float(getattr(config, "MA_BUY_STOCH_MAX", 80.0))
    except (TypeError, ValueError):
        return 80.0
    return v if v < 100 else None


def enabled() -> bool:
    return bool(getattr(config, "MA_BUY_TRACKER_ENABLED", True))


# ---------------------------------------------------------------------------------------------------------- saf yardımcılar
def due_bar_open(now_ms: int, tf_ms: int) -> int:
    """Şu an işlenebilecek son KAPANMIŞ mumun açılış zamanı (kapanıştan DUE_GRACE_MS sonra)."""
    return ((int(now_ms) - DUE_GRACE_MS) // tf_ms) * tf_ms - tf_ms


def closed_bars(rows, tf_ms: int, now_ms: int) -> list[dict]:
    """Ham kline satırları → yalnız kapanmış mumlar [{open_ms, close_ms, open, high, low, close}], açılışa göre artan, tekil."""
    out: dict = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            open_ms = int(row[0])
            close_ms = int(row[6]) if len(row) > 6 else open_ms + tf_ms - 1
            bar = {"open_ms": open_ms, "close_ms": close_ms, "open": float(row[1]), "high": float(row[2]),
                   "low": float(row[3]), "close": float(row[4])}
        except (TypeError, ValueError, IndexError):
            continue
        if close_ms > int(now_ms) - CLOSE_SKEW_MS:
            continue
        out[open_ms] = bar
    return [out[k] for k in sorted(out)]


def signals_from_bars(symbol: str, tf: str, bars: list[dict], now_ms: int, *, lookback: int, per: tuple,
                      use_sma: bool = False, slow_cross: bool = True, stoch_max: float | None = None) -> list[dict]:
    """Son `lookback` kapanmış mumda tetiklenen sinyaller → DB satırları (saf)."""
    if len(bars) < max(per) + 2:
        return []
    closes = [b["close"] for b in bars]
    first_index = len(bars) - max(1, int(lookback))
    rows = []
    for hit in ma_buy_signals.detect_ma_buy(closes, per, use_sma=use_sma, slow_cross=slow_cross,
                                               stoch_max=stoch_max):
        if hit["index"] < first_index:
            continue
        bar = bars[hit["index"]]
        rows.append({
            "symbol": symbol.upper(), "timeframe": tf, "bar_open_ms": bar["open_ms"],
            "bar_close_ms": bar["open_ms"] + SUPPORTED_TF_MS[tf],
            "detected_at": now_ms / 1000.0, "rules": ",".join(hit["rules"]), "signal_price": bar["close"],
            "ema_fast": hit["fast"], "ema_mid": hit["mid"], "ema_slow": hit["slow"],
        })
    return rows


def summarize(items: list[dict]) -> dict:
    """Yönetici sayfası özeti (saf): sayılar, 15 dk en yüksek yükseliş ortalama/medyan, eşik payları, kural kırılımı."""
    done = [i for i in items if i.get("status") == "done" and i.get("max_rise_15m_pct") is not None]
    rises = [float(i["max_rise_15m_pct"]) for i in done]
    gross_floor = notify_metrics.min_gross_target_pct(min_net_pct=1.5) or 1.705

    def avg(vals):
        return round(sum(vals) / len(vals), 4) if vals else None

    def med(vals):
        return round(statistics.median(vals), 4) if vals else None

    thresholds = []
    for t in (1.0, gross_floor, 2.0):
        n = sum(1 for r in rises if r >= t)
        thresholds.append({"min_pct": round(t, 3), "n": n, "share": round(n / len(rises), 4) if rises else None})
    by_rule: dict = {}
    for rule in ma_buy_signals.ALL_RULES:
        subset = [i for i in items if rule in str(i.get("rules") or "").split(",")]
        sub_done = [float(i["max_rise_15m_pct"]) for i in subset
                    if i.get("status") == "done" and i.get("max_rise_15m_pct") is not None]
        by_rule[rule] = {"count": len(subset), "evaluated": len(sub_done),
                         "avg_max_rise_15m_pct": avg(sub_done), "median_max_rise_15m_pct": med(sub_done)}
    return {
        "count": len(items), "evaluated": len(done),
        "pending": sum(1 for i in items if i.get("status") == "open"),
        "avg_max_rise_15m_pct": avg(rises), "median_max_rise_15m_pct": med(rises),
        "avg_max_drop_15m_pct": avg([float(i["max_drop_15m_pct"]) for i in done if i.get("max_drop_15m_pct") is not None]),
        "avg_close_15m_pct": avg([float(i["close_15m_pct"]) for i in done if i.get("close_15m_pct") is not None]),
        "gross_floor_pct": round(gross_floor, 3), "thresholds": thresholds, "by_rule": by_rule,
    }


def public_item(row: dict) -> dict:
    """DB satırı → API öğesi (`rules` listeye çevrilir)."""
    out = dict(row)
    out["rules"] = [r for r in str(row.get("rules") or "").split(",") if r]
    out.pop("eval_attempts", None)
    return out


def status_snapshot() -> dict:
    return {"enabled": enabled(), "timeframes": timeframes(), "scope": str(getattr(config, "MA_BUY_SYMBOL_SCOPE", "active")),
            "last_scan_at": _state["last_scan_at"], "last_scan_symbols": _state["last_scan_symbols"],
            "last_inserted": _state["last_inserted"], "last_evaluated": _state["last_evaluated"],
            "last_error": _state["last_error"]}


# ---------------------------------------------------------------------------------------------------------- tarama
async def active_symbols() -> list[str]:
    tracked = sorted({str(s).upper() for s in (config.SYMBOLS or []) if s})
    if str(getattr(config, "MA_BUY_SYMBOL_SCOPE", "active")).strip().lower() == "tracked":
        return tracked
    try:
        raw = await database.get_llm_setting("symbol_activity_status", "{}")
        statuses = json.loads(raw or "{}")
    except Exception:  # noqa: BLE001
        statuses = {}
    active = sorted(str(sym).upper() for sym, item in (statuses or {}).items()
                    if isinstance(item, dict) and str(item.get("status")).upper() == "ACTIVE")
    return active or tracked


async def _scan_symbol(symbol: str, tf: str, now_ms: int, sem: asyncio.Semaphore) -> int:
    tf_ms = SUPPORTED_TF_MS[tf]
    due = due_bar_open(now_ms, tf_ms)
    key = (symbol, tf)
    if _state["seen"].get(key, 0) >= due:
        return 0
    async with sem:
        rows = await fetch_klines(symbol, tf, limit=FETCH_LIMIT)
    bars = closed_bars(rows, tf_ms, now_ms)
    if not bars:
        return 0
    use_sma = str(getattr(config, "MA_BUY_MA_TYPE", "ema")).strip().lower() == "sma"
    found = signals_from_bars(symbol, tf, bars, now_ms, lookback=int(getattr(config, "MA_BUY_LOOKBACK_BARS", 3) or 3),
                              per=periods(), use_sma=use_sma, stoch_max=stoch_max(tf))
    inserted = await database.insert_ma_buy_signals(found) if found else 0
    _state["seen"][key] = bars[-1]["open_ms"]
    if inserted:
        logger.info("MA BUY sinyali kaydedildi: %s %s %s (%d yeni)", symbol, tf,
                    ",".join(sorted({r["rules"] for r in found})), inserted)
    return int(inserted or 0)


async def scan_once(now_ms: int | None = None) -> dict:
    """Aktif sembollerde yeni kapanan mumları değerlendirir; yeni kaydedilen sinyal sayısını döndürür."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    symbols = await active_symbols()
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
    inserted = 0
    errors: list[str] = []
    for tf in timeframes():
        results = await asyncio.gather(*(_scan_symbol(s, tf, now_ms, sem) for s in symbols), return_exceptions=True)
        for sym, res in zip(symbols, results):
            if isinstance(res, BaseException):
                errors.append(f"{sym}/{tf}: {type(res).__name__}")
            else:
                inserted += res
    _state["last_scan_at"] = now_ms / 1000.0
    _state["last_scan_symbols"] = len(symbols)
    _state["last_inserted"] = inserted
    _state["last_error"] = ("; ".join(errors[:3]) + (f" (+{len(errors) - 3})" if len(errors) > 3 else "")) if errors else None
    return {"symbols": len(symbols), "inserted": inserted, "errors": len(errors)}


# ---------------------------------------------------------------------------------------------------------- ölçüm
async def evaluate_once(now_ms: int | None = None) -> int:
    """15 dk dolan açık sinyallerin sonucunu yazar; yazılan sinyal sayısını döndürür."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    pending = await database.list_ma_buy_open(limit=300)
    done = 0
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
    for row in pending:
        tf = row.get("timeframe") or "5m"
        tf_ms = SUPPORTED_TF_MS.get(tf)
        if not tf_ms:
            await database.update_ma_buy_outcome(row["id"], None, status="no_data")
            continue
        horizon_end = int(row["bar_close_ms"]) + HORIZON_MIN * 60_000
        if now_ms < horizon_end + DUE_GRACE_MS:
            continue
        try:
            async with sem:
                rows = await fetch_klines(row["symbol"], tf, limit=HORIZON_MIN * 60_000 // tf_ms + 4,
                                         start_time_ms=int(row["bar_open_ms"]) + tf_ms)
            bars = [b for b in closed_bars(rows, tf_ms, now_ms) if b["open_ms"] >= int(row["bar_open_ms"]) + tf_ms]
            metrics = ma_buy_signals.outcome_metrics(float(row["signal_price"]), bars, tf_ms // 60_000, HORIZON_MIN)
        except Exception as exc:  # noqa: BLE001
            logger.debug("MA BUY ölçüm hatası %s: %s", row.get("symbol"), exc)
            metrics = None
        if metrics:
            await database.update_ma_buy_outcome(row["id"], metrics, status="done", attempts_inc=True)
            done += 1
        elif now_ms - horizon_end > NO_DATA_AFTER_MS:
            await database.update_ma_buy_outcome(row["id"], None, status="no_data", attempts_inc=True)
        else:
            await database.update_ma_buy_outcome(row["id"], None, status="open", attempts_inc=True)
    _state["last_evaluated"] = done
    return done


async def run_once(now_ms: int | None = None) -> dict:
    scan = await scan_once(now_ms)
    evaluated = await evaluate_once(now_ms)
    retention_days = int(getattr(config, "MA_BUY_RETENTION_DAYS", 120) or 0)
    if retention_days > 0 and time.time() - _state["last_prune"] > 3600:
        _state["last_prune"] = time.time()
        await database.prune_ma_buy_signals(int((time.time() - retention_days * 86400) * 1000))
    return {**scan, "evaluated": evaluated}


async def ma_buy_loop() -> None:
    """Arka plan döngüsü (supervisor `main._start_background` altında). Hata döngüyü öldürmez."""
    await asyncio.sleep(90)  # açılış patlaması bitsin
    while True:
        try:
            if enabled():
                await run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _state["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("MA BUY izleyici turu başarısız: %s", exc)
        await asyncio.sleep(max(10.0, float(getattr(config, "MA_BUY_SCAN_INTERVAL_SEC", 30) or 30)))
