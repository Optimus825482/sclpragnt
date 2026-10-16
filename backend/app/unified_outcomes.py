"""BİRLEŞİK ADAY SONUÇ JOURNAL'I (Faz 2).

Amaç: pulse / snapback / short-squeeze / master-surge ve birleşik `scan_score`
adaylarının GERÇEK isabetini ölçmek. `app.unified_scan.combined_scan_rows`
çıktısı `record_scan_rows` ile `unified_candidate_outcomes` tablosuna yazılır;
ufuk penceresi dolan satırlar `fill_pending_outcomes` ile 1m mum penceresinden
MFE/MAE/hit değerlerini alır.

Tüm genel fonksiyonlar HATA DÜŞÜRMEZ (try/except + logger.debug): journal
ölçümü canlı tarama/bildirim davranışını ASLA etkilememelidir.
"""
import json
import logging
import time

from app import database
from app.binance_tr_public import klines

logger = logging.getLogger("scalper.unified_outcomes")

# hit eşiği: ceiling_pct yoksa target_pct, o da yoksa %2 taban.
_DEFAULT_HIT_THRESHOLD_PCT = 2.0


def _float_or_none(value):
    """Bozuk/NaN değerleri None'a çevir (tek satır tüm batch'i düşürmesin)."""
    try:
        if value is None:
            return None
        number = float(value)
        return number if number == number else None  # NaN koruması
    except (TypeError, ValueError):
        return None


def _candidate_row(row: dict) -> dict | None:
    """Birleşik tarama satırını journal adayına çevir; geçersizse None."""
    symbol = str(row.get("symbol") or "").upper().strip()
    if not symbol:
        return None
    entry = _float_or_none(
        row.get("price") if row.get("price") is not None else row.get("entry_price"))
    if entry is None or entry <= 0:
        return None
    try:
        horizon = int(row.get("horizon_minutes") or 0)
    except (TypeError, ValueError):
        horizon = 0
    sources = row.get("signal_sources") or row.get("unified_sources") or []
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except (TypeError, ValueError):
            sources = []
    score = _float_or_none(
        row.get("scan_score") if row.get("scan_score") is not None
        else row.get("quality_score"))
    # 2026-10-15 (radar düzeltmesi): GERÇEK sinyal zamanı — satırın kendi
    # `detected_at`'i, yoksa `created_at`; yalnız ikisi de yoksa şimdi.
    detected = (_float_or_none(row.get("detected_at"))
                or _float_or_none(row.get("created_at"))
                or time.time())
    return {
        "symbol": symbol,
        "horizon_minutes": max(0, horizon),
        "sources": json.dumps([str(s) for s in (sources or []) if s]),
        "scan_score": score,
        "entry_price": float(entry),
        "ceiling_pct": _float_or_none(row.get("ceiling_pct")),
        "target_pct": _float_or_none(row.get("target_pct")),
        "detected_at": float(detected),
        # '' = kapıdan geçti; dolu = engel nedeni (BTC_BEAR_REGIME_SHIELD vb.). NULL yalnız eski satır.
        "blocked_by": str(row.get("blocked_by") or "")[:80],
        # 2026-10-17: kalkan rozeti (RADAR_SHIELD_MODE=badge) — geçti ama BTC < EMA200 idi.
        "regime_badge": (str(row.get("regime_badge") or "")[:40] or None),
    }


async def record_scan_rows(rows: list[dict]) -> int:
    """Birleşik tarama satırlarını (combined_scan_rows çıktısı) journal'a yaz.

    Alan eşlemesi: `signal_sources`/`unified_sources` → sources (JSON dizi),
    `price` → entry_price, `scan_score`/`quality_score` → scan_score.
    Duplicate koruması (symbol, horizon_minutes, ufuk kovası) DB tarafındadır
    (`database.unified_dedup_window`).
    """
    try:
        candidates = [c for c in (_candidate_row(r) for r in (rows or [])) if c]
        if not candidates:
            return 0
        return await database.save_unified_candidates(candidates)
    except Exception as exc:
        logger.debug("birleşik aday journal kaydı başarısız: %s", exc)
        return 0


async def fill_pending_outcomes(max_age_sec: float = 7200, batch_limit: int = 200) -> int:
    """Ufku dolmuş bekleyen satırların MFE/MAE/hit sonucunu 1m mumlarla doldur.

    `max_age_sec`: satır en az bu kadar ESKİ olmalı (2h > en uzun ufuk 60dk);
    pencere tamamlanmadan erken ölçüm yalnız alt sınır olurdu. Sembol aynen
    geçirilir (TRY çifti zaten olduğu gibi sorgulanır). Satır bazında hata →
    o satır atlanır, sayaç bozulmaz. Dönen değer: doldurulan satır sayısı.
    """
    try:
        pending = await database.get_unified_pending_outcomes(
            older_than_sec=max(0.0, float(max_age_sec)),
            limit=max(1, min(2000, int(batch_limit))))
    except Exception as exc:
        logger.debug("birleşik aday pending okuması başarısız: %s", exc)
        return 0
    filled = 0
    for row in pending:
        try:
            symbol = str(row.get("symbol") or "")
            entry = float(row.get("entry_price") or 0)
            if not symbol or entry <= 0:
                continue
            try:
                horizon = int(row.get("horizon_minutes") or 0)
            except (TypeError, ValueError):
                horizon = 0
            detected = float(row.get("detected_at") or 0)
            start_ms = int(detected * 1000)
            end_ms = start_ms + (horizon + 5) * 60_000
            candles = await klines(symbol, "1m", limit=1500,
                                   start_time_ms=start_ms, end_time_ms=end_ms)
            highs = [float(c[2]) for c in (candles or []) if c and len(c) > 2]
            lows = [float(c[3]) for c in (candles or []) if c and len(c) > 3]
            if not highs or not lows:
                # 2026-10-15 (radar düzeltmesi): boş mum dönen satır (sembol
                # delist / veri yok) MÜHÜRLENİR (mfe/mae/hit NULL) → `LIMIT 200`
                # kuyruğunu süresiz tıkamaz; `filled` sayacına girmez.
                await database.update_unified_outcome(int(row["id"]), None, None, None)
                continue
            mfe = (max(highs) - entry) / entry * 100.0
            mae = (min(lows) - entry) / entry * 100.0
            ceiling = _float_or_none(row.get("ceiling_pct"))
            target = _float_or_none(row.get("target_pct"))
            threshold = ceiling or target or _DEFAULT_HIT_THRESHOLD_PCT
            hit = mfe >= threshold
            await database.update_unified_outcome(
                int(row["id"]), round(mfe, 4), round(mae, 4), bool(hit))
            filled += 1
        except Exception as exc:
            logger.debug("outcome doldurma satırı atlandı (%s): %s",
                         row.get("symbol"), exc)
            continue
    return filled


async def outcome_stats(days: int = 14) -> dict:
    """Journal özeti (genel + kaynak bazında) + `generated_at` damgası."""
    stats = await database.get_unified_outcome_stats(days=days)
    return {**stats, "generated_at": time.time()}
