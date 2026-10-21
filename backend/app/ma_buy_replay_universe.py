"""MA BUY replay — CANLI sembol seçiminin tarihsel yeniden üretimi (saf hesap; ağ/DB yok).

2026-10-20 (kullanıcı isteği): replay sabit bir sembol listesiyle değil, sistemin kendi seçim zinciriyle koşmalı:

  1. Her TOP_GAINERS_REFRESH_SEC (canlı: 600 sn): tüm TRY çiftleri 24 saatlik değişime (eşitlikte 24 sa hacme) göre
     sıralanır, ilk TOP_GAINERS_LIMIT (canlı: 50) izlenen evren olur  → `routers.runtime.refresh_top_gainer_symbols`.
     Canlı kod borsanın 24 sa ticker'ını kullanır; geçmişte o tablo yok → aynı iki büyüklük 5 dakikalık mumlardan
     türetilir: değişim = son kapanış / 24 sa önceki kapanış, hacim = son 24 saatin quote hacim toplamı.
  2. Her SYMBOL_ACTIVITY_REFRESH_SEC (canlı: 3600 sn): izlenen sembollerin aktivite kararı (hacim, 15 dk aralık, ATR,
     hacim oranı, M1 düz mum sayacı, kapsamlı pasiflik analizi) → `routers.runtime.refresh_symbol_activity`.
     Karar fonksiyonları canlı modülden AYNEN çağrılır (`_m1_flat_candle_activity`, `_comprehensive_passive_analysis`,
     `_atr`). İzlenmeyen sembolün canlıda 5m serisi olmadığı için WARMING kalır → burada da yalnız izlenenler değerlendirilir.
  3. MA izleyici (ma_buy_tracker.active_symbols): AKTİF küme; boşsa izlenen küme. Sinyal, mumu KAPANDIĞI anda sembol bu
     kümedeyse sayılır.

Bilinçli sadeleştirmeler (raporda yazılır): açık paper pozisyonlarının evrene eklenmesi yok; `_m1_activity_features`
yalnız gözlem alanı (karara girmez) → hesaplanmaz; canlı ticker'ın `priceChangePercent`'i yerine 5m kapanış oranı.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from app.config import config

DAY_MS = 86_400_000
CLOSE_SKEW_MS = 1_500            # market_data._closed_history ile aynı: kapanışı şu andan ilerideki mum alınmaz
M5_HISTORY_BARS = 80             # bootstrap/hydrate_m5 limit=80
M1_HISTORY_BARS = 150            # hydrate_m1 limit=150


def closed_history(rows: Sequence, upto_ms: int, limit: int) -> dict:
    """Ham kline satırları → canlı `market.get_ut_kline` biçimi (yalnız `upto_ms` itibarıyla kapanmış son `limit` mum)."""
    cutoff = int(upto_ms) - CLOSE_SKEW_MS
    picked: dict = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            open_ms = int(row[0])
            close_ms = int(row[6]) if len(row) > 6 and row[6] is not None else None
            vals = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
        except (TypeError, ValueError):
            continue
        if close_ms is None or close_ms > cutoff:
            continue
        picked[open_ms] = vals
    keys = sorted(picked)[-int(limit):]
    hist = {"timestamps": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}
    for k in keys:
        o, h, l, c, v = picked[k]
        hist["timestamps"].append(k)
        hist["opens"].append(o)
        hist["highs"].append(h)
        hist["lows"].append(l)
        hist["closes"].append(c)
        hist["volumes"].append(v)
    return hist


def ticker_stats(rows_5m: Sequence, t_ms: int) -> dict | None:
    """24 sa ticker karşılığı: {change_pct, quote_volume, last} — `t_ms` itibarıyla kapanmış 5m mumlardan.

    quote_volume: son 24 saatte (close_ms ∈ (t-24h, t]) kapanan mumların quote hacmi (satır[7]).
    change_pct: son kapanış / (24 sa önce kapanmış son mumun kapanışı) − 1. Yetersiz geçmişte None.
    """
    t = int(t_ms)
    last = None
    ref = None
    quote = 0.0
    lo = t - DAY_MS
    for row in rows_5m or []:
        try:
            close_ms = int(row[6])
            close = float(row[4])
        except (TypeError, ValueError, IndexError):
            continue
        if close_ms > t:
            continue
        if close_ms > lo:
            try:
                quote += float(row[7]) if len(row) > 7 else 0.0
            except (TypeError, ValueError):
                pass
        if last is None or close_ms > last[0]:
            last = (close_ms, close)
        if close_ms <= lo and (ref is None or close_ms > ref[0]):
            ref = (close_ms, close)
    if last is None or ref is None or ref[1] <= 0:
        return None
    return {"change_pct": (last[1] / ref[1] - 1.0) * 100.0, "quote_volume": quote, "last": last[1]}


def rank_top_gainers(stats: dict, limit: int) -> list[str]:
    """`refresh_top_gainer_symbols` sıralaması: (change_pct, quote_volume) azalan; ilk `limit`."""
    ranked = sorted(((s, v) for s, v in stats.items() if v),
                    key=lambda kv: (float(kv[1]["change_pct"]), float(kv[1]["quote_volume"])), reverse=True)
    return [s for s, _ in ranked[:max(1, int(limit))]]


def activity_status(m5: dict, m1: dict, *, quote_volume: float, now_ms: int) -> dict:
    """`refresh_symbol_activity` karar çekirdeği — canlı kodla AYNI eşikler ve yardımcılar (config'ten okunur)."""
    from app.routers.runtime import _comprehensive_passive_analysis, _m1_flat_candle_activity
    from app.technical_analysis import _atr

    closes = list((m5 or {}).get("closes") or [])
    highs = list((m5 or {}).get("highs") or [])
    lows = list((m5 or {}).get("lows") or [])
    volumes = list((m5 or {}).get("volumes") or [])
    if len(closes) < 7 or len(highs) < 7 or len(lows) < 7:
        return {"status": "WARMING", "reason": "market_data_warming", "checks": {}}
    m1_activity = _m1_flat_candle_activity(m1 or {}, int(now_ms))
    comprehensive = _comprehensive_passive_analysis(m1 or {}, m5 or {}, int(now_ms))
    low, high = min(lows[-3:]), max(highs[-3:])
    range_pct = ((high - low) / low * 100) if low else 0.0
    volume_ok = float(quote_volume) >= float(config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY)
    movement_ok = range_pct >= float(config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT)
    atr = None
    if len(closes) >= 15:
        try:
            atr = _atr(highs, lows, closes, 14)
        except (ValueError, TypeError, IndexError):
            atr = None
    atr_pct = (atr / closes[-1]) if atr and closes[-1] else 0.0
    prev = volumes[-21:-1]
    avg_volume = sum(prev) / max(1, len(prev)) if len(volumes) >= 21 else 0.0
    volume_ratio = (volumes[-1] / avg_volume) if avg_volume else 0.0
    atr_ok = atr_pct >= float(config.SYMBOL_ACTIVITY_MIN_ATR_PCT)
    volume_ratio_ok = volume_ratio >= float(config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO)
    movement_gate_ok = True if config.SYMBOL_ACTIVITY_VOLUME_ONLY else (movement_ok and atr_ok)
    flat_5m_blocked = m1_activity["flat_5m_count"] >= int(config.SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT)
    flat_30m_blocked = m1_activity["flat_30m_count"] >= int(config.SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT)
    m1_flat_ok = (not config.SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED or not m1_activity["ready"]
                  or not (flat_5m_blocked or flat_30m_blocked))
    truly_passive = bool(comprehensive.get("is_passive", False))
    active = bool(volume_ok and movement_gate_ok and volume_ratio_ok and m1_flat_ok and not truly_passive)
    checks = {"quote_volume": volume_ok, "range_15m": movement_ok, "atr": atr_ok, "volume_ratio": volume_ratio_ok,
              "m1_flat_candles": m1_flat_ok, "comprehensive_passive": not truly_passive}
    reason = "active" if active else (comprehensive.get("combined_reason") if truly_passive else
                                      ("m1_flat_candles" if not m1_flat_ok else "volume_or_liquidity_below_threshold"))
    return {"status": "ACTIVE" if active else "PASSIVE", "reason": reason, "checks": checks,
            "range_15m_pct": round(range_pct, 4), "atr_pct": round(atr_pct * 100, 4),
            "volume_ratio": round(volume_ratio, 4), "quote_volume": float(quote_volume)}


def membership_at(timeline: Sequence[dict], t_ms: int) -> set:
    """`t_ms` anında MA izleyicinin taradığı küme: en son aktivite anlık görüntüsünün AKTİF kümesi; boşsa izlenen küme.
    Hiç anlık görüntü yoksa boş küme (izleyici henüz çalışmamış)."""
    latest = None
    for snap in timeline:
        if int(snap["at_ms"]) <= int(t_ms) and (latest is None or int(snap["at_ms"]) > int(latest["at_ms"])):
            latest = snap
    if latest is None:
        return set()
    active = set(latest.get("active") or ())
    return active if active else set(latest.get("tracked") or ())


def refresh_marks(start_ms: int, end_ms: int, period_ms: int, offset_ms: int = 0) -> list[int]:
    """[start, end] içinde `period_ms` ızgarasındaki yenileme anları (+offset)."""
    first = (int(start_ms) // int(period_ms)) * int(period_ms) + int(offset_ms)
    out = []
    t = first
    while t <= int(end_ms):
        if t >= int(start_ms):
            out.append(t)
        t += int(period_ms)
    return out


def apply_runtime_overrides(runtime: dict) -> dict:
    """Canlı `runtime_config` içindeki seçim ayarlarını config'e uygular; uygulananları döndürür (rapor için)."""
    keys = {
        "symbol_activity_m1_flat_filter_enabled": ("SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED", bool),
        "symbol_activity_m1_flat_max_range_pct": ("SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT", float),
        "symbol_activity_m1_flat_5m_max_count": ("SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT", int),
        "symbol_activity_m1_flat_30m_max_count": ("SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT", int),
        "top_gainers_limit": ("TOP_GAINERS_LIMIT", int),
        "top_gainers_refresh_sec": ("TOP_GAINERS_REFRESH_SEC", int),
    }
    applied = {}
    for key, (attr, cast) in keys.items():
        if key in (runtime or {}):
            try:
                value = cast(runtime[key])
            except (TypeError, ValueError):
                continue
            setattr(config, attr, value)
            applied[attr] = value
    return applied


def selection_settings() -> dict:
    """Raporda gösterilecek seçim parametreleri (config'in o anki değerleri)."""
    names = ("TOP_GAINERS_LIMIT", "TOP_GAINERS_REFRESH_SEC", "SYMBOL_ACTIVITY_REFRESH_SEC",
             "SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY", "SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT", "SYMBOL_ACTIVITY_MIN_ATR_PCT",
             "SYMBOL_ACTIVITY_MIN_VOLUME_RATIO", "SYMBOL_ACTIVITY_VOLUME_ONLY", "SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED",
             "SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT", "SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT",
             "SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT")
    return {n: getattr(config, n, None) for n in names}


def symbols_ever(sets: Iterable[Iterable[str]]) -> set:
    out: set = set()
    for s in sets:
        out |= set(s)
    return out


# ------------------------------------------------------------------------------------------ veritabanı arşivi
def db_rows_to_klines(db_rows: Sequence[dict]) -> list:
    """`historical_candles` satırları → Binance kline satırı [open_ms, o, h, l, c, v, close_ms, quote_vol] (açılışa göre artan)."""
    out = []
    for r in db_rows or []:
        try:
            out.append([int(r["open_time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                        float(r["volume"]), int(r["close_time"]), float(r.get("quote_volume") or 0.0)])
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda row: row[0])
    return out


def aggregate_klines(rows: Sequence, src_ms: int, dst_ms: int) -> list:
    """Küçük zaman dilimi mumlarından büyüğünü kurar (ör. 15m → 30m / 1h). Kova = açılış // dst_ms; yalnız TÜM alt
    mumları mevcut (dst_ms / src_ms adet) olan kovalar üretilir — eksik kova atlanır (borsa mumuyla birebir)."""
    need = int(dst_ms) // int(src_ms)
    if need < 1 or int(dst_ms) % int(src_ms):
        raise ValueError("dst_ms, src_ms'in tam katı olmalı")
    buckets: dict = {}
    for row in sorted((r for r in rows or [] if isinstance(r, (list, tuple)) and len(r) >= 8), key=lambda r: int(r[0])):
        key = (int(row[0]) // int(dst_ms)) * int(dst_ms)
        buckets.setdefault(key, []).append(row)
    out = []
    for key in sorted(buckets):
        parts = buckets[key]
        if len(parts) != need:
            continue
        out.append([key, float(parts[0][1]), max(float(p[2]) for p in parts), min(float(p[3]) for p in parts),
                    float(parts[-1][4]), sum(float(p[5]) for p in parts), key + int(dst_ms) - 1,
                    sum(float(p[7]) for p in parts)])
    return out


# ------------------------------------------------------------------------------------------ hızlı yol (uzun replay)
def parse_rows(rows: Sequence) -> dict:
    """Ham kline satırlarını BİR kez ayrıştırır: açılışa göre sıralı paralel listeler + quote hacim ön toplamı.

    `closed_history` / `ticker_stats` ile aynı sonucu verir; saatlik anlık görüntü × yüzlerce sembol × on binlerce
    mumda her çağrıda satırları yeniden ayrıştırmak yerine ikili aramayla dilimlenir (bkz. history_upto, ticker_stats_series).
    """
    picked: dict = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            open_ms = int(row[0])
            close_ms = int(row[6]) if len(row) > 6 and row[6] is not None else None
            vals = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            quote = float(row[7]) if len(row) > 7 and row[7] not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
        if close_ms is None:
            continue
        picked[open_ms] = (close_ms, vals, quote)
    out = {"open_ms": [], "close_ms": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "quote_cum": []}
    cum = 0.0
    for k in sorted(picked):
        close_ms, (o, h, l, c, v), q = picked[k]
        out["open_ms"].append(k)
        out["close_ms"].append(close_ms)
        out["opens"].append(o)
        out["highs"].append(h)
        out["lows"].append(l)
        out["closes"].append(c)
        out["volumes"].append(v)
        cum += q
        out["quote_cum"].append(cum)
    return out


def _closed_index(parsed: dict, upto_close_ms: int) -> int:
    """`close_ms <= upto_close_ms` olan son mumun indeksi + 1 (yani dilim sonu); yoksa 0. close_ms artan varsayılır."""
    from bisect import bisect_right
    return bisect_right(parsed["close_ms"], int(upto_close_ms))


def history_upto(parsed: dict, upto_ms: int, limit: int) -> dict:
    """`closed_history(rows, upto_ms, limit)` ile birebir aynı sonuç, ayrıştırılmış seriden."""
    end = _closed_index(parsed, int(upto_ms) - CLOSE_SKEW_MS)
    start = max(0, end - int(limit))
    return {"timestamps": parsed["open_ms"][start:end], "opens": parsed["opens"][start:end],
            "highs": parsed["highs"][start:end], "lows": parsed["lows"][start:end],
            "closes": parsed["closes"][start:end], "volumes": parsed["volumes"][start:end]}


def ticker_stats_series(parsed: dict, marks: Sequence[int]) -> list:
    """Her `mark` için `ticker_stats` karşılığı (None: 24 sa geçmiş yok). Ön toplam + ikili arama ile O(log n)/mark."""
    out = []
    for t in marks:
        t = int(t)
        end = _closed_index(parsed, t)                 # close_ms <= t
        ref_end = _closed_index(parsed, t - DAY_MS)    # close_ms <= t - 24h
        if end == 0 or ref_end == 0:
            out.append(None)
            continue
        last_close = parsed["closes"][end - 1]
        ref_close = parsed["closes"][ref_end - 1]
        if ref_close <= 0:
            out.append(None)
            continue
        quote = parsed["quote_cum"][end - 1] - (parsed["quote_cum"][ref_end - 1] if ref_end > 0 else 0.0)
        out.append({"change_pct": (last_close / ref_close - 1.0) * 100.0, "quote_volume": quote, "last": last_close})
    return out
