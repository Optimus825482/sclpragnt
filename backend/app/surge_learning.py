"""Surge Learning — Adaptif Skor Bias Modülü (2026-09-21)

Self-Learning sisteminden gelen kapanan paper trade ve radar sinyal MFE
verilerini kullanarak sembol bazlı bir 'öğrenilmiş bias' hesaplar.

Bu bias, Master Surge Engine'in composite_index skoruna eklenir / çıkarılır.
Böylece sistem, geçmişte sürekli başarılı olan sembollere avantaj,
sürekli başarısız olanlara ceza uygulayarak zamanla kendini iyileştirir.

SINIRLAR:
  - Maksimum bias: ±15 puan (composite_index 100/0 sınırı aşılamaz).
  - Minimum güven: confidence < 0.30 → bias sıfır uygulanır.
  - Minimum örnek: sample_size < 5 → bias hesaplanmaz.
  - confluence_4way zorunluluğu asla yumuşatılamaz.
  - LLM dokunuşu yoktur; tüm hesaplama deterministik ve denetlenebilir.

Önbellek: get_cached_surge_biases() → son hesaplanan bias dict'ini döner.
          refresh_biases() → yeni trade/sinyal verisiyle önbelleği günceller.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("scalper.surge_learning")

# ---------------------------------------------------------------------------
# RAM Önbelleği
# ---------------------------------------------------------------------------
_BIAS_CACHE: dict[str, dict] = {}          # {"BTCTRY": {bias_pct: +8.2, ...}}
_BIAS_CACHE_TS: float = 0.0                # Son güncelleme unix timestamp
_BIAS_CACHE_TTL: float = 600.0            # 10 dakika

MAX_BIAS_PCT: float = 15.0                 # Maksimum ±15 puan
MIN_CONFIDENCE: float = 0.30              # Bu altı → bias uygulanmaz
MIN_SAMPLES: int = 5                      # Bu altı → bias hesaplanmaz


# ---------------------------------------------------------------------------
# Sembol Bazlı Bias Hesaplama
# ---------------------------------------------------------------------------

def compute_symbol_bias(
    symbol: str,
    closed_trades: list[dict],
    radar_rows: list[dict],
) -> dict:
    """Tek sembol için adaptif skor bias'ı hesaplar.

    Args:
        symbol: Sembol adı (ör. "BTCTRY")
        closed_trades: AUTO_PAPER kapalı trade kayıtları (pnl, exit_reason içermeli)
        radar_rows: monitoring_notifications + MFE ölçüm satırları

    Returns:
        {
          "bias_pct": float,       # [-15, +15] → composite_index'e eklenir
          "confidence": float,     # [0, 1]
          "sample_size": int,      # Toplam baz alınan işlem sayısı
          "win_rate": float | None,
          "stop_rate": float | None,
          "tp1_hit_rate": float | None,
          "reason": str,           # İnsan okunur açıklama
        }
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return _zero_bias("empty_symbol")

    # --- Paper Trade Metrikleri ---
    sym_trades = [t for t in (closed_trades or []) if str(t.get("symbol") or "").upper() == sym]
    trade_count = len(sym_trades)
    win_rate: float | None = None
    stop_rate: float | None = None
    avg_pnl_pct: float | None = None

    if trade_count >= MIN_SAMPLES:
        winners = sum(1 for t in sym_trades if float(t.get("pnl") or 0) > 0)
        stopouts = sum(
            1 for t in sym_trades
            if "STOP" in str(t.get("exit_reason") or "").upper()
        )
        win_rate = winners / trade_count
        stop_rate = stopouts / trade_count
        pnl_pcts = [float(t.get("pnl_pct") or 0) for t in sym_trades]
        avg_pnl_pct = sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0

    # --- Radar Sinyal MFE Metrikleri ---
    sym_radar = [
        r for r in (radar_rows or [])
        if str(r.get("symbol") or "").upper() == sym
        and r.get("candidate_status") == "evaluated"
        and r.get("mfe_pct") is not None
    ]
    radar_count = len(sym_radar)
    tp1_hit_rate: float | None = None

    if radar_count >= MIN_SAMPLES:
        tp1_hits = sum(1 for r in sym_radar if float(r.get("mfe_pct") or 0) >= 1.2)
        tp1_hit_rate = tp1_hits / radar_count

    # --- Toplam Örnek ve Güven ---
    total_samples = trade_count + radar_count
    if total_samples < MIN_SAMPLES:
        return _zero_bias(f"insufficient_samples({total_samples})")

    confidence = min(1.0, total_samples / 30.0)   # 30 örnekte tam güven

    # --- Bias Hesaplama ---
    bias = 0.0
    reasons: list[str] = []

    # 1. Win Rate: %60+ ise ödül, %30- ise ceza
    if win_rate is not None:
        if win_rate >= 0.60:
            win_bonus = (win_rate - 0.50) * 30.0    # max +15 at 100%
            bias += win_bonus
            reasons.append(f"win_rate={win_rate:.0%}(+{win_bonus:.1f})")
        elif win_rate <= 0.30:
            win_penalty = (0.40 - win_rate) * 30.0  # max -12 at 0%
            bias -= win_penalty
            reasons.append(f"win_rate={win_rate:.0%}(-{win_penalty:.1f})")

    # 2. Stop Rate: %50+ ise ceza
    if stop_rate is not None and stop_rate >= 0.50:
        stop_penalty = (stop_rate - 0.40) * 30.0    # max -18 → sınırlanacak
        bias -= stop_penalty
        reasons.append(f"stop_rate={stop_rate:.0%}(-{stop_penalty:.1f})")

    # 3. TP1 Radar Başarısı: Güçlendirici / zayıflatıcı çarpan
    tp1_weight = 1.0
    if tp1_hit_rate is not None:
        if tp1_hit_rate >= 0.60:
            tp1_weight = 1.20
            reasons.append(f"tp1_hit={tp1_hit_rate:.0%}(x1.2)")
        elif tp1_hit_rate >= 0.40:
            tp1_weight = 1.00
        elif tp1_hit_rate <= 0.20:
            tp1_weight = 0.60
            reasons.append(f"tp1_hit={tp1_hit_rate:.0%}(x0.6)")
        else:
            tp1_weight = 0.80
    bias *= tp1_weight

    # 4. Güven çarpanı uygula
    bias *= confidence

    # 5. Kesin sınır
    bias = max(-MAX_BIAS_PCT, min(MAX_BIAS_PCT, bias))
    bias = round(bias, 2)

    reason_str = "; ".join(reasons) if reasons else "nötr"
    return {
        "bias_pct": bias,
        "confidence": round(confidence, 3),
        "sample_size": total_samples,
        "trade_count": trade_count,
        "radar_count": radar_count,
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "stop_rate": round(stop_rate, 3) if stop_rate is not None else None,
        "tp1_hit_rate": round(tp1_hit_rate, 3) if tp1_hit_rate is not None else None,
        "avg_pnl_pct": round(avg_pnl_pct, 3) if avg_pnl_pct is not None else None,
        "reason": reason_str,
    }


def _zero_bias(reason: str) -> dict:
    return {
        "bias_pct": 0.0,
        "confidence": 0.0,
        "sample_size": 0,
        "trade_count": 0,
        "radar_count": 0,
        "win_rate": None,
        "stop_rate": None,
        "tp1_hit_rate": None,
        "avg_pnl_pct": None,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Toplu Bias Hesaplama
# ---------------------------------------------------------------------------

def build_surge_biases(
    closed_trades: list[dict],
    radar_rows: list[dict],
) -> dict[str, dict]:
    """Tüm semboller için bias dict'i oluşturur."""
    if not closed_trades and not radar_rows:
        return {}

    symbols: set[str] = set()
    for t in (closed_trades or []):
        sym = str(t.get("symbol") or "").upper()
        if sym:
            symbols.add(sym)
    for r in (radar_rows or []):
        sym = str(r.get("symbol") or "").upper()
        if sym:
            symbols.add(sym)

    biases: dict[str, dict] = {}
    for sym in symbols:
        b = compute_symbol_bias(sym, closed_trades, radar_rows)
        if b["sample_size"] > 0:
            if b["confidence"] < MIN_CONFIDENCE:
                b_safe = dict(b)
                b_safe["bias_pct"] = 0.0   # Güven yetersiz → sıfır bias
                biases[sym] = b_safe
            else:
                biases[sym] = b

    logger.debug(
        "surge_learning: %d sembol bias hesaplandı (trade=%d, radar=%d)",
        len(biases), len(closed_trades or []), len(radar_rows or [])
    )
    return biases


# ---------------------------------------------------------------------------
# RAM Önbelleği — Güncelleme ve Okuma
# ---------------------------------------------------------------------------

def refresh_biases(closed_trades: list[dict], radar_rows: list[dict]) -> dict[str, dict]:
    """Önbelleği yeni verilerle günceller ve sonucu döner."""
    global _BIAS_CACHE, _BIAS_CACHE_TS
    try:
        new_biases = build_surge_biases(closed_trades, radar_rows)
        _BIAS_CACHE = new_biases
        _BIAS_CACHE_TS = time.monotonic()
        logger.info("surge_learning: Bias önbelleği güncellendi — %d sembol.", len(new_biases))
        return new_biases
    except Exception as exc:
        logger.warning("surge_learning: Bias güncelleme hatası: %s", exc)
        return _BIAS_CACHE


def get_cached_surge_biases() -> dict[str, dict]:
    """RAM önbelleğindeki bias dict'ini döner (salt okunur)."""
    return _BIAS_CACHE


def cache_age_seconds() -> float:
    """Önbelleğin kaç saniye önce güncellendiğini döner."""
    if _BIAS_CACHE_TS == 0.0:
        return float("inf")
    return time.monotonic() - _BIAS_CACHE_TS


def is_cache_stale(ttl: float = _BIAS_CACHE_TTL) -> bool:
    """Önbellek TTL'i aştıysa True döner."""
    return cache_age_seconds() > ttl


# ---------------------------------------------------------------------------
# Bias Özeti (Raporlama için)
# ---------------------------------------------------------------------------

def bias_summary(biases: dict[str, dict] | None = None) -> dict:
    """API/frontend için okunabilir bias özeti üretir."""
    b = biases if biases is not None else _BIAS_CACHE
    if not b:
        return {
            "enabled": False,
            "symbol_count": 0,
            "symbols": [],
            "cache_age_s": cache_age_seconds(),
        }

    positive = [(sym, d) for sym, d in b.items() if d.get("bias_pct", 0) > 0.5]
    negative = [(sym, d) for sym, d in b.items() if d.get("bias_pct", 0) < -0.5]
    neutral = [(sym, d) for sym, d in b.items() if abs(d.get("bias_pct", 0)) <= 0.5]

    def _fmt(items: list[tuple[str, dict]]) -> list[dict]:
        return sorted(
            [
                {
                    "symbol": sym,
                    "bias_pct": round(d.get("bias_pct", 0), 2),
                    "confidence": round(d.get("confidence", 0), 2),
                    "sample_size": d.get("sample_size", 0),
                    "win_rate": d.get("win_rate"),
                    "tp1_hit_rate": d.get("tp1_hit_rate"),
                    "reason": d.get("reason", ""),
                }
                for sym, d in items
            ],
            key=lambda x: abs(x["bias_pct"]),
            reverse=True,
        )

    return {
        "enabled": True,
        "symbol_count": len(b),
        "positive_bias_count": len(positive),
        "negative_bias_count": len(negative),
        "neutral_count": len(neutral),
        "positive": _fmt(positive),
        "negative": _fmt(negative),
        "neutral": _fmt(neutral)[:10],
        "cache_age_s": round(cache_age_seconds(), 1),
        "last_updated": _BIAS_CACHE_TS,
        "max_bias_pct": MAX_BIAS_PCT,
        "min_confidence": MIN_CONFIDENCE,
        "policy": "descriptive_adaptive_score_adjustment_max_15pct_no_confluence_override",
    }
