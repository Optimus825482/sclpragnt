"""Geçmiş sinyallerden süre / stop istatistiği (2026-10-27, migration 030).

Push'u gitmiş sinyaller (radar, yükseliş, MA BUY) son 60 gün için 1 dk mumlarla yeniden oynatılır:
brüt eşiklere (3,6 / 5 / 8 / 10 %) ilk ulaşma dakikası ve o ana kadarki en büyük düşüş (MAE) örnek olarak
saklanır; kova başına özet (`signal_eta_stats`) günde bir yeniden hesaplanır. Bildirim anında yalnız okunur.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np

from app import binance_tr_public, database
from app.config import config

logger = logging.getLogger(__name__)

THRESHOLDS = (3.6, 5.0, 8.0, 10.0)
MIN_SAMPLES = 30
LOOKBACK_DAYS = 60
WINDOW_MIN = 1440
CACHE_TTL_SEC = 600
LOOP_INTERVAL_SEC = 86400
SOURCE_KINDS = ("radar", "rising", "ma_buy")

_CACHE: dict[tuple[str, float], tuple[float, dict | None]] = {}


def _key(th: float) -> str:
    return str(float(th))


def first_hits(candles: list, entry: float, thresholds=THRESHOLDS,
               start_ms: int | None = None) -> tuple[dict, dict]:
    """(hits, mae_before): eşik başına ilk ulaşma dakikası ve o muma kadar en kötü düşüş %.

    Dakika ZAMAN tabanlıdır: (mum_açılışı - start_ms)//60000 + 1 (Binance işlem olmayan dakikaların mumunu
    atlar, indeks kullanılamaz). start_ms varsayılanı ilk mumun açılışıdır. 24 saatlik pencere zamanla kesilir.

    Ulaşılan mumun kendi dibi de MAE'ye dahildir (muhafazakâr). Ulaşılmayan eşik: ikisi de None.
    """
    hits: dict[str, Any] = {_key(t): None for t in thresholds}
    mae: dict[str, Any] = {_key(t): None for t in thresholds}
    entry = float(entry)
    if entry <= 0:
        return hits, mae
    worst = 0.0
    if not candles:
        return hits, mae
    start = int(start_ms) if start_ms is not None else int(candles[0][0])
    end = start + WINDOW_MIN * 60_000
    for c in candles:
        open_ms = int(c[0])
        if open_ms >= end:
            break
        if open_ms < start:
            continue
        high, low = float(c[2]), float(c[3])
        worst = min(worst, (low / entry - 1.0) * 100.0)
        rise = (high / entry - 1.0) * 100.0
        for t in thresholds:
            k = _key(t)
            if hits[k] is None and rise >= t:
                hits[k] = (open_ms - start) // 60_000 + 1
                mae[k] = worst
        if all(v is not None for v in hits.values()):
            break
    return hits, mae


def bucket_stats(samples: list[dict], threshold: float) -> dict | None:
    """Kova özeti; n < MIN_SAMPLES → None. MAE yalnız kazananlardan, POZİTİF % olarak."""
    k = _key(threshold)
    samples = [s for s in samples if s.get("hits")]  # tombstone (hits={}) istatistiğe girmez
    n = len(samples)
    if n < MIN_SAMPLES:
        return None
    mins = [float(s["hits"][k]) for s in samples if (s.get("hits") or {}).get(k) is not None]
    maes = [abs(float(s["mae_before"][k])) for s in samples
            if (s.get("hits") or {}).get(k) is not None and (s.get("mae_before") or {}).get(k) is not None]
    out = {"n": n, "hit_rate": len(mins) / n, "p50_min": None, "p75_min": None, "mae_p80_pct": None}
    if mins:
        out["p50_min"] = float(np.percentile(mins, 50))
        out["p75_min"] = float(np.percentile(mins, 75))
    if maes:
        out["mae_p80_pct"] = float(np.percentile(maes, 80))
    return out


def bucket_for(source_kind: str, row: dict) -> str:
    if source_kind == "rising":
        return f"rising:{row.get('kind')}"
    if source_kind == "ma_buy":
        return f"ma_buy:{row.get('timeframe')}"
    return "radar"


def pick_threshold(gross_target_pct: float) -> float:
    """Brüt hedefe eşit/büyük en küçük eşik; en büyüğü aşarsa en büyük eşik."""
    for t in THRESHOLDS:
        if float(gross_target_pct) <= t + 1e-9:
            return t
    return THRESHOLDS[-1]


async def get_stats(bucket: str, gross_target_pct: float) -> dict | None:
    th = pick_threshold(gross_target_pct)
    ck = (str(bucket), th)
    now = time.time()
    hit = _CACHE.get(ck)
    if hit and now - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    row = await database.get_eta_stats(str(bucket), th)
    _CACHE[ck] = (now, row)
    return row


async def _fetch_window(symbol: str, signal_ts: float) -> tuple[list, int, bool]:
    """(mumlar, start_ms, tam_mı): sinyal dakikasından 24 saatlik 1m mum (en çok iki çağrı).

    Tamlık ZAMAN kapsamıyla yargılanır: son mum start+1440dk-5dk'ya ulaştıysa ya da API veri sonunu
    bildirdiyse (<1000 mum) tam sayılır; Binance işlem olmayan dakikaların mumunu atlar, sayıya bakılmaz.
    """
    start = int(signal_ts // 60) * 60_000
    end = start + WINDOW_MIN * 60_000
    cursor = start
    out: list = []
    complete = False
    for _ in range(2):
        batch = await binance_tr_public.klines(symbol, "1m", limit=1000, start_time_ms=cursor)
        if not batch:
            complete = bool(out)
            break
        out.extend(batch)
        last = int(batch[-1][0])
        if last >= end - 5 * 60_000:
            complete = True
            break
        if len(batch) < 1000:
            complete = True  # veri sonu
            break
        cursor = last + 60_000
    return [c for c in out if int(c[0]) < end], start, complete


def _tombstone(kind: str, r: dict) -> dict:
    # hits={} = ölçülemedi işareti: yeniden seçilmez, bucket_stats'e girmez.
    return {"source_kind": kind, "ref_id": r["ref_id"], "bucket": r["bucket"], "symbol": r["symbol"],
            "signal_ts": r["signal_ts"], "entry_price": r.get("entry_price"), "hits": {}, "mae_before": {}}


async def measure_batch(now: float | None = None) -> int:
    """Ölçülmemiş, penceresi dolmuş sinyallerden en çok SIGNAL_ETA_BATCH örnek yazar (kaynak başına eşit pay)."""
    now = float(now if now is not None else time.time())
    total = max(1, int(getattr(config, "SIGNAL_ETA_BATCH", 200)))
    share = max(1, total // len(SOURCE_KINDS))
    since = now - LOOKBACK_DAYS * 86400
    until = now - (WINDOW_MIN + 5) * 60
    written = 0
    for kind in SOURCE_KINDS:
        try:
            rows = await database.list_unmeasured_signals(kind, since, until, share)
        except Exception as exc:  # noqa: BLE001
            logger.warning("signal_eta: %s sinyalleri okunamadı: %s", kind, exc)
            continue
        samples = []
        for r in rows:
            try:
                candles, start_ms, complete = await _fetch_window(r["symbol"], r["signal_ts"])
                if not candles:
                    samples.append(_tombstone(kind, r))  # veri yok / delist
                elif complete:
                    entry = float(r.get("entry_price") or 0) or float(candles[0][1])
                    hits, mae = first_hits(candles, entry, start_ms=start_ms)
                    samples.append({"source_kind": kind, "ref_id": r["ref_id"], "bucket": r["bucket"],
                                    "symbol": r["symbol"], "signal_ts": r["signal_ts"], "entry_price": entry,
                                    "hits": hits, "mae_before": mae})
                # eksik kapsam (geçici): sonraki tura bırak
            except binance_tr_public.BinanceCooldownError as exc:
                logger.warning("signal_eta: soğuma penceresi, %s turu bırakıldı: %s", kind, exc)
                break
            except binance_tr_public.PermanentAPIError:
                samples.append(_tombstone(kind, r))  # geçersiz sembol: kalıcı
            except Exception as exc:  # noqa: BLE001 — tek sembol hatası döngüyü durdurmasın
                logger.warning("signal_eta: %s ölçülemedi: %s", r.get("symbol"), exc)
            await asyncio.sleep(0.2)
        if samples:
            written += await database.insert_eta_samples(samples, now=now)
    return written


async def recompute_stats(now: float | None = None) -> int:
    """Tüm kovaların eşik istatistiklerini son 60 günlük örneklerden yeniden yazar."""
    now = float(now if now is not None else time.time())
    since = now - LOOKBACK_DAYS * 86400
    buckets = await database.list_eta_buckets(since)
    done = 0
    for b in buckets:
        samples = await database.list_eta_samples(b, since)
        for t in THRESHOLDS:
            st = bucket_stats(samples, t)
            if st is not None:
                await database.upsert_eta_stats(b, t, st, now=now)
                done += 1
            else:
                await database.delete_eta_stats(b, t)  # bayat satır kalmasın
    _CACHE.clear()
    return done


async def eta_loop() -> None:
    """Günde bir: yeni örnekleri ölç, istatistikleri yeniden hesapla. Hata döngüyü öldürmez."""
    await asyncio.sleep(120)
    while True:
        try:
            n = await measure_batch()
            s = await recompute_stats()
            logger.info("signal_eta: %d yeni örnek, %d istatistik satırı", n, s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("signal_eta turu atlandı: %s", exc)
        await asyncio.sleep(LOOP_INTERVAL_SEC)


__all__ = ["THRESHOLDS", "MIN_SAMPLES", "LOOKBACK_DAYS", "WINDOW_MIN", "first_hits", "bucket_stats",
           "bucket_for", "pick_threshold", "get_stats", "measure_batch", "recompute_stats", "eta_loop"]
