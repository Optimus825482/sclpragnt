"""Bucketed win-rate calibration: turn closed-trade history into entry
confidence multipliers.

The 2026-08-25 audit found the expected-net model predicted +10.34 TRY per
trade while reality averaged -5.75 TRY — the model had no feedback loop. This
module closes that loop deterministically:

1. ``build_buckets`` groups closed trades by coarse, robust context buckets
   (strategy × hour-band × volume-ratio band) and computes win rate / sample
   count per bucket.
2. ``confidence_multiplier`` maps a new entry's context to [0.5 .. 1.0]:
   buckets with proven bad expectancy scale size down. A bucket whose volume
   ratio could not be read is treated as *unproven*, not as *proven good*,
   and gets a fail-safe mid value (``UNKNOWN_VOLUME_MULTIPLIER``).
3. A weekly refresh job re-reads trades from the database. Buckets need
   >= min samples before they are allowed to influence sizing.

Bucket labels (hour bands) use a single fixed UTC+3 timezone (``BUCKET_TZ``)
on BOTH the build and the lookup side, so a live entry always lands in the
same bucket as the historical trades that taught it.

No machine learning, no parameter fitting — plain counting with
walk-forward-safe semantics (only *past* trades feed today's multiplier).
"""
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MIN_BUCKET_SAMPLES = 8
GOOD_WIN_RATE = 0.55     # >= this wins -> full size (multiplier 1.0)
BAD_WIN_RATE = 0.35      # <= this wins -> minimum multiplier
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 1.0
#: ``unknown`` hacim bandı çarpanı.
#: D-11 (2026-09-26 denetimi, YÜKSEK): eski davranış nötr 1.0 idi, yani
#: hacim oranı okunamayan bir giriş TAM boyutla açılıyordu. "Veri yok"
#: kanıtlanmış bir kalite değildir; nötr 1.0 fail-OPEN (riskli) yöndeyken
#: fail-SAFE yön orta değer (0.85) ile temsil edilir: kanıtlanmış kötü
#: kova MIN_MULTIPLIER'a iner, kanıtlanmış iyi kova 1.0'a çıkar, veri
#: yoksa boyut bir miktar kısılır ama durmaz.
UNKNOWN_VOLUME_MULTIPLIER = 0.85

#: Kova saat dilimi. Denetim (2026-09-26): `multiplier_for` UTC, `build_buckets`
#: de UTC okurken `monitoring.py:2545` rapor/UI kovaları sabit UTC+3 ile
#: üretiyordu → canlı giriş ile geçmiş işlem farklı saat bandına düşüyor,
#: kova anahtarı tutmuyordu. TEK doğruluk kaynağı: sabit UTC+3 (Türkiye
#: saati, yaz saati uygulaması olmayan ülke).
BUCKET_TZ = timezone(timedelta(hours=3))

# Shared bucket state. Refreshed weekly by the main.py calibration loop and
# read by the analyzer at entry time; kept here so both sides share one
# source of truth without a circular import.
_bucket_state = {"buckets": {}, "updated_at": 0.0}


def store_buckets(buckets: dict) -> None:
    """Publish a freshly built bucket table (weekly refresh path)."""
    _bucket_state["buckets"] = buckets or {}
    _bucket_state["updated_at"] = time.time()


def bucket_state() -> dict:
    """Read-only view for UI/report surfaces."""
    return dict(_bucket_state)


def multiplier_for(strategy: str, *, volume_ratio: float | None = None) -> float:
    """Current confidence multiplier for one entry; neutral before first build.

    D-11 (2026-09-26): saat dilimi UTC+3'e (`BUCKET_TZ`) çevrildi — kova
    etiketleri `build_buckets` ile aynı zaman tabanını paylaşmalıdır, yoksa
    canlı giriş hiçbir zaman geçmiş işlem kovasıyla eşleşmez.
    """
    hour = datetime.now(BUCKET_TZ).hour
    return confidence_multiplier(
        _bucket_state.get("buckets") or {},
        strategy=strategy, hour=hour, volume_ratio=volume_ratio)


def hour_band(hour: int | None) -> str:
    if hour is None:
        return "unknown"
    if 5 <= hour < 9:
        return "early_eu"
    if 9 <= hour < 14:
        return "eu_day"
    if 14 <= hour < 18:
        return "us_overlap"
    if 18 <= hour < 23:
        return "evening"
    return "late_night"


def volume_band(volume_ratio: float | None) -> str:
    if volume_ratio is None:
        return "unknown"
    if volume_ratio < 0.5:
        return "very_low"
    if volume_ratio < 1.0:
        return "low"
    if volume_ratio <= 2.0:
        return "normal"      # healthy pump band per the trade audit
    return "chasing"         # VR > 2.0: the worst historical cluster


def bucket_key(*, strategy: str | None, hour: int | None,
               volume_ratio: float | None) -> tuple:
    return (str(strategy or "unknown"), hour_band(hour), volume_band(volume_ratio))


def _trade_volume_ratio(ctx: dict) -> float | None:
    """Bir işlemin `entry_context`'indeki hacim oranı — GERÇEK şema.

    D-11 (2026-09-26): `build_buckets` önce `ctx["candles"]["volumes"]`
    diye bir anahtar arıyordu; bu anahtar `analyzer._open_position_unlocked`
    tarafından HİÇ yazılmıyor. Gerçek şema sırasıyla:
      1. ``ctx["volume_ratio"]``  → giriş anında hesaplanan kalıcı alan
         (5m cache: ``vols[-1] / mean(vols[-21:-1])``) — canlı yolun BİREBİR
         kendisi, `analyzer._entry_volume_ratio` tarafından yazılır.
      2. ``ctx["candles"]["volumes"]`` → geçmiş/geri-uyum yolu (yoksa atlanır).
      3. ``ctx["liquidity"]["volume_ratio"]`` → `liquidity_status` çıktısı.
    Hepsi yoksa ``None`` döner → kova "unknown" bandına düşer.
    """
    if not isinstance(ctx, dict):
        return None
    for value in (ctx.get("volume_ratio"),):
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    candles = ctx.get("candles")
    if isinstance(candles, dict):
        vols = candles.get("volumes")
        if isinstance(vols, (list, tuple)) and len(vols) >= 21:
            base = float(sum(vols[-21:-1]) / 20)
            if base > 0:
                try:
                    return float(vols[-1]) / base
                except (TypeError, ValueError):
                    return None
    liquidity = ctx.get("liquidity")
    if isinstance(liquidity, dict) and liquidity.get("volume_ratio") is not None:
        try:
            return float(liquidity["volume_ratio"])
        except (TypeError, ValueError):
            return None
    return None


def build_buckets(trades: list[dict]) -> dict[tuple, dict]:
    """Group closed trades into buckets with win-rate statistics."""
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for trade in trades or []:
        pnl = float(trade.get("pnl") or 0)
        try:
            hour = None
            ts = float(trade.get("entry_time") or 0)
            if ts > 0:
                hour = datetime.fromtimestamp(ts, tz=BUCKET_TZ).hour
        except (TypeError, ValueError):
            hour = None
        # H4/D-11: bucket key, canlı yolun (`analyzer._open_position_unlocked`
        # → `calib_volume_ratio`) BİREBİR aynı hacim oranı tanımını kullanır.
        vr = _trade_volume_ratio(trade.get("entry_context") or {})
        key = bucket_key(strategy=trade.get("strategy"), hour=hour, volume_ratio=vr)
        grouped[key].append(pnl)
    buckets = {}
    for key, pnls in grouped.items():
        wins = sum(1 for p in pnls if p > 0)
        buckets[key] = {
            "samples": len(pnls),
            "win_rate": wins / len(pnls),
            "net_pnl": round(sum(pnls), 2),
            "expectancy": round(sum(pnls) / len(pnls), 4),
        }
    return buckets


def confidence_multiplier(buckets: dict[tuple, dict], *, strategy: str | None,
                          hour: int | None, volume_ratio: float | None) -> float:
    """Map a new entry's bucket to a size multiplier in [0.5 .. 1.0].

    D-11 (2026-09-26): "kanıt yok" durumu iki farklı fail yönüne ayrıldı.

      * ``volume_band == "unknown"`` (hacim oranı okunamadı) → ``UNKNOWN_VOLUME_MULTIPLIER``
        (0.85). Önceden 1.0 idi, yani veri Yok olan girişler TAM boyutla
        açılıyordu — kalibrasyon "kanıtlanmış riski" ölçemediği için
        sessizce hiçbir şey yapmıyordu. 0.85 fail-SAFE orta noktadır:
        kanıtlanmış kötü kova 0.5'e iner, iyi kova 1.0'a çıkar, veri
        yoksa bir miktar küçülür ama işlem durmaz.
      * ``samples < MIN_BUCKET_SAMPLES`` (kova var ama ince) → 1.0 korunur:
        kova mevcut, yalnızca az örnek var; bu bir veri EKSİKLİĞİ değil,
        düşük güven. Sıfırlamak da şişirmek de doğru değil.
    """
    key = bucket_key(strategy=strategy, hour=hour, volume_ratio=volume_ratio)
    stats = buckets.get(key)
    if not stats or stats["samples"] < MIN_BUCKET_SAMPLES:
        return UNKNOWN_VOLUME_MULTIPLIER if key[2] == "unknown" else MAX_MULTIPLIER
    wr = stats["win_rate"]
    if wr >= GOOD_WIN_RATE:
        return MAX_MULTIPLIER
    if wr <= BAD_WIN_RATE:
        return MIN_MULTIPLIER
    # Linear between the two anchors.
    span = GOOD_WIN_RATE - BAD_WIN_RATE
    ratio = (wr - BAD_WIN_RATE) / span
    return round(MIN_MULTIPLIER + ratio * (MAX_MULTIPLIER - MIN_MULTIPLIER), 3)


def summarize_for_ui(buckets: dict[tuple, dict], limit: int = 12) -> list[dict]:
    """Most decision-relevant buckets for the reports page."""
    rows = []
    for key, stats in buckets.items():
        if stats["samples"] < MIN_BUCKET_SAMPLES:
            continue
        rows.append({
            "strategy": key[0], "hour_band": key[1], "volume_band": key[2],
            **stats,
        })
    rows.sort(key=lambda r: r["expectancy"])
    return rows[:limit]


# ---------------------------------------------------------------------------
# S4: regime-gated sizing.
# Deterministic regimes already exist in technical_analysis; this maps them to
# size multipliers per strategy *style*. Mean-reversion entries fight the move
# in trending regimes, so they shrink there; continuation strategies (PUMP)
# are the opposite and shrink in dead ranges.

TRENDING_REGIMES = {"bull_quiet", "bull_volatile", "bear_quiet", "bear_volatile"}
RANGE_REGIMES = {"range_transition", "accumulation", "distribution"}


def regime_size_multiplier(strategy_style: str, regime: str | None,
                           regime_confidence: float | None = None) -> float:
    """Size multiplier from market regime vs strategy style.

    mean_reversion: full size in range regimes, half size in strong trends
      (the entry fights an ADX-confirmed directional move).
    trend_following / continuation: full size in trends or unknown; shrinks
      only inside a confirmed dead range when confidence is meaningful.
    Unknown regime or low confidence stays neutral at 1.0.
    """
    if not regime:
        return 1.0
    confidence_ok = (regime_confidence is None) or (regime_confidence >= 0.55)
    if strategy_style == "mean_reversion":
        if regime in TRENDING_REGIMES and confidence_ok:
            return 0.5
        return 1.0
    if strategy_style in {"trend_following", "continuation"}:
        if regime in RANGE_REGIMES and confidence_ok:
            return 0.7
        return 1.0
    return 1.0


def strategy_style_of(strategy_name: str | None) -> str:
    name = str(strategy_name or "").upper()
    if "MEAN_REVERSION" in name:
        return "mean_reversion"
    if "PUMP" in name or "BREAKOUT" in name or "MOMENTUM" in name:
        return "continuation"
    return "unknown"
