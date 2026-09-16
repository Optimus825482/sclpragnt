"""BİRLEŞİK RADAR 24 SAATLİK REPLAY — entegrasyondan ÖNCE başarı ölçümü.

AMAÇ (plan: combined-radar-unification.md, Aşama 1):
    Hız Avcısı + Yükseliş + Radar tespitleri birleşik motorunun (app/combined_radar.py)
    NE KADAR BAŞARILI olduğunu, üretim davranışına DOKUNMADAN ölçmek. Karar
    entegrasyona (Aşama 2) bu ölçüm onaylandıktan SONRA açılır.

NASIL ÇALIŞIR:
    1. Journal'lardan son N saatlik olay zaman çizelgesi kurulur:
         * `velocity_candidates`  → radarın GÖRDÜĞÜ adaylar (bildirim gönderilmeyen
           watchlist satırları dahil; yazım bildirimden bağımsızdır).
         * `rising_alerts`        → yükseliş motorunun ateşlediği sinyaller.
    2. Üç akış üretilir ve aynı ölçümle karşılaştırılır:
         * velocity-only : `passes=True` VE ham skor ≥ MONITORING_MIN_RAW_SCORE
         * rising-only   : kayıtlı yükseliş sinyalleri
         * combined      : ikisinin birleşimi (confluence işaretli) — build_combined_events
    3. Her sanal giriş için 1m kline penceresi çekilir (historical_klines) ve
       **auto_paper B1-B4 merdiveni simüle edilir** (TP önce → peak/MFE → SL →
       breakeven → trailing). Böylece metrik "hedefe dokundu mu" değil,
       "GERÇEKTEN NE KADAR KAZANDIRDI" olur.
    4. Metrikler: sinyal sayısı, hedef-dokunma oranı, kazanma oranı, ort/medyan
       net % (round-trip maliyeti düşülmüş), toplam net %, ort. MFE/MAE, tutma süresi.

DÜRÜST SINIRLAR (rapora da yazılır — sonuçları okurken bil):
    * MACD snapshot'ı tarihsel olarak yeniden üretİLEMEZ (canlı `_SNAPSHOT`; pure
      fonksiyon yok). Yükseliş ayağı yalnız KAYITLI kanıtla oynanır → eski kapıdan
      geçmemiş yükseliş sinyalleri kayıptır (seçim yanlılığı).
    * velocity journal hunisi kısmîdir: tarama başına top-10 geçen + 5 watchlist.
    * `volume_ratio` journal'da her zaman 0.0'dır; ML tahmini bugünkü modelle
      "gölge"dir; mikro yapı/whale/CVD yalnız journal'lanan adaylar için vardır.
    * Mum içi sıra belirsizdir: bir barın hem TP hem SL aralığına girmesi hâlinde
      SL ÖNCE varsayılır (kötümser). Üç akış da aynı simülatörle ölçüldüğü için
      KARŞILAŞTIRMA adildir; mutlak sayılar yaklaşiktir.

KULLANIM:
    python backend/scripts/combined_radar_replay_24h.py --hours 24
    python backend/scripts/combined_radar_replay_24h.py --hours 24 --skip-fetch
    python backend/scripts/combined_radar_replay_24h.py --hours 48 --out ../work/radar.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database                                   # noqa: E402
from app.combined_radar import build_combined_events       # noqa: E402
from app.config import config                              # noqa: E402
from app.binance_tr_public import historical_klines        # noqa: E402
from app.routers.velocity import (                         # noqa: E402
    _post_signal_window, _mfe_from_window, round_trip_cost_pct, _panel_score,
    _velocity_horizon_from_candidate_id,
)


# ---------------------------------------------------------------------------
# B1-B4 merdiven simülasyonu (auto_paper._manage_single_trade ile aynı sıra)
# ---------------------------------------------------------------------------
def _simulate_ladder(rows, entry_price: float, target_pct: float, horizon_minutes: float,
                     signal_ms: int | None = None) -> dict:
    """auto_paper çıkış merdivenini 1m kline penceresi üzerinde oynatır.

    Sıra üretimle birebir: (1) TP kontrolü, (2) peak/MFE güncelle, (3) SL,
    (4) breakeven kur+breach, (5) trailing kur+breach. Dönen sözlükte
    `exit_reason`, `exit_price`, `mfe_pct`, `mae_pct`, `hold_minutes` vardır.
    """
    slippage = float(config.ESTIMATED_SLIPPAGE_PCT)
    commission = float(config.COMMISSION_PCT)
    entry = float(entry_price) * (1 + slippage)
    if entry <= 0 or not rows:
        return {"exit_reason": "no_data", "exit_price": None, "mfe_pct": None,
                "mae_pct": None, "hold_minutes": 0.0, "net_pct": None}

    tp = entry * (1 + float(target_pct) / 100.0)
    sl = entry * (1 - float(config.AUTO_PAPER_SL_PCT_DEFAULT) / 100.0)
    tp_gain_pct = (tp / entry - 1) * 100
    be_trigger = max(float(config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT), tp_gain_pct * 0.7)
    tr_trigger = max(float(config.AUTO_PAPER_TRAILING_TRIGGER_PCT), tp_gain_pct * 0.8)
    be_gap = 0.60                       # auto_paper: BREAKEVEN_TRAIL_GAP_PCT
    be_buffer = float(config.AUTO_PAPER_BREAKEVEN_BUFFER_PCT)
    net_floor = entry * (1 + 2 * commission + be_buffer / 100)

    peak = entry
    breakeven_stop = None
    trailing_stop = None
    # Ufuk SİNYAL ANINDAN ölçülür (ilk bardan değil): sinyal 12:00:30'da geldiyse
    # ve ufuk 5 dk ise kapanış 12:05:30'dur. İlk bara göre hesaplamak ufku 1 dakikaya
    # kadar uzatıp ölçümü kaydırıyordu.
    base_ms = int(signal_ms) if signal_ms is not None else int(rows[0][0])
    first_ms = base_ms
    due_ms = base_ms + int(horizon_minutes * 60_000)

    exit_reason = "horizon_end"
    exit_price = None
    exit_ms = None
    bar_ms = 60_000
    for bar in rows:
        opened_ms = int(bar[0])
        # Pencere tanımı `_post_signal_window` ile BİREBİR: yalnız due_ms'ten önce
        # KAPANMIŞ barlar işlenir (sinyal anını içeren parsiyel mum hariç, R5-C4.4).
        if opened_ms + bar_ms - 1 > due_ms:
            break
        high, low, close = float(bar[2]), float(bar[3]), float(bar[4])

        # (1) TP ÖNCE — B1
        if high >= tp:
            exit_reason, exit_price, exit_ms = "take_profit", min(high, tp), opened_ms
            break

        # (2) peak / MFE
        peak = max(peak, high)

        # (3) SL
        if low <= sl:
            exit_reason, exit_price, exit_ms = "stop_loss", max(low, sl), opened_ms
            break

        gross_pct = (peak / entry - 1) * 100

        # (4) breakeven zeminini kur + breach
        if gross_pct >= be_trigger:
            candidate = max(net_floor, peak * (1 - be_gap / 100))
            breakeven_stop = candidate if breakeven_stop is None else max(breakeven_stop, candidate)
        if breakeven_stop is not None and low <= breakeven_stop:
            exit_reason, exit_price, exit_ms = "breakeven_stop", max(low, breakeven_stop), opened_ms
            break

        # (5) trailing zeminini kur + breach (B3: TP'ye yakın aralık yarıya iner)
        gap = float(config.AUTO_PAPER_TRAILING_GAP_PCT)
        if gross_pct >= tp_gain_pct * 0.9:
            gap = max(0.2, gap * 0.5)
        if gross_pct >= tr_trigger:
            candidate = peak * (1 - gap / 100)
            trailing_stop = candidate if trailing_stop is None else max(trailing_stop, candidate)
        if trailing_stop is not None and low <= trailing_stop:
            exit_reason, exit_price, exit_ms = "trailing_stop", max(low, trailing_stop), opened_ms
            break
        exit_price, exit_ms = close, opened_ms

    if exit_price is None:
        exit_price, exit_ms = float(rows[-1][4]), int(rows[-1][0])

    window = _post_signal_window(rows, first_ms, due_ms)
    mfe = _mfe_from_window(window, entry)
    mae = ((min(float(r[3]) for r in window) / entry - 1) * 100) if window else None
    hold_minutes = max(0.0, (exit_ms - first_ms) / 60_000)
    gross_pct_exit = (exit_price / entry - 1) * 100
    net_pct = gross_pct_exit - round_trip_cost_pct()
    return {"exit_reason": exit_reason, "exit_price": exit_price, "mfe_pct": mfe,
            "mae_pct": mae, "hold_minutes": hold_minutes, "gross_pct": gross_pct_exit,
            "net_pct": net_pct}


# ---------------------------------------------------------------------------
# Veri yükleme
# ---------------------------------------------------------------------------
async def _load_klines(symbol: str, start_s: float, end_s: float, cache: dict) -> list:
    """Sembol için 1m kline'ları bir kez çeker, pencereyi keser (REST tasarrufu)."""
    if symbol not in cache:
        span_days = max(1, math.ceil((end_s - start_s) / 86400.0))
        try:
            cache[symbol] = await historical_klines(symbol, "1m", span_days,
                                                    int(end_s * 1000))
        except Exception as exc:
            print(f"  ! {symbol} kline alınamadı: {type(exc).__name__}: {exc}")
            cache[symbol] = []
        await asyncio.sleep(0.05)          # Binance'e nazik ol (maintenance.py deseni)
    rows = cache.get(symbol) or []
    return [r for r in rows if start_s * 1000 <= int(r[0]) <= end_s * 1000]


def _metrics(name: str, signals: list[dict]) -> dict:
    """Akış metrikleri: sayım, isabet, kazanma, net getiri, MFE/MAE."""
    measured = [s for s in signals if s.get("net_pct") is not None]
    touched = [s for s in measured if s.get("exit_reason") == "take_profit"]
    wins = [s for s in measured if (s.get("net_pct") or 0) > 0]
    nets = [float(s["net_pct"]) for s in measured]
    mfes = [float(s["mfe_pct"]) for s in measured if s.get("mfe_pct") is not None]
    maes = [float(s["mae_pct"]) for s in measured if s.get("mae_pct") is not None]
    targets = [float(s["target_pct"]) for s in measured if s.get("target_pct")]
    confluence = [s for s in measured if s.get("confluence")]
    conf_wins = [s for s in confluence if (s.get("net_pct") or 0) > 0]
    reasons: dict[str, int] = defaultdict(int)
    for s in measured:
        reasons[str(s.get("exit_reason"))] += 1
    avg_mfe = round(statistics.mean(mfes), 4) if mfes else None
    avg_target = round(statistics.mean(targets), 4) if targets else None
    # HEDEF/GEOMETRİ TEŞHİSİ: ortalama hedef, ortalama MFE'yi çok aşıyorsa TP
    # ulaşılamaz demektir → sinyal gelir, fiyat hedefe gitmez, maliyet ödenir.
    reach = round(avg_target / avg_mfe, 2) if (avg_target and avg_mfe) else None
    return {
        "stream": name,
        "signals": len(signals),
        "measured": len(measured),
        "target_hit_rate": round(len(touched) / len(measured) * 100, 2) if measured else None,
        "win_rate": round(len(wins) / len(measured) * 100, 2) if measured else None,
        "avg_net_pct": round(statistics.mean(nets), 4) if nets else None,
        "median_net_pct": round(statistics.median(nets), 4) if nets else None,
        "total_net_pct": round(sum(nets), 3) if nets else None,
        "avg_target_pct": avg_target,
        "avg_mfe_pct": avg_mfe,
        "target_to_mfe_ratio": reach,
        "avg_mae_pct": round(statistics.mean(maes), 4) if maes else None,
        "avg_hold_minutes": round(statistics.mean(float(s["hold_minutes"]) for s in measured), 2)
            if measured else None,
        "confluence_count": len(confluence),
        "confluence_win_rate": round(len(conf_wins) / len(confluence) * 100, 2)
            if confluence else None,
        "exit_reasons": dict(sorted(reasons.items())),
    }


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def _emit(log, message: str) -> None:
    """İlerleme çıktısı: CLI'da print, uygulama içi işte log callback."""
    if log is None:
        print(message)
    else:
        log(message)


def _as_signal_row(item: dict, detected_at, confluence: bool = False,
                   default_source: str | None = None,
                   default_horizon: float = 5.0) -> dict:
    """Bir olayı ölçüm satırına çevir.

    DİKKAT — `sources` HER ZAMAN dolu string listesi olmalıdır. Journal satırlarında
    (`velocity_candidates`) ne `sources` ne `source` alanı vardır; eski kod
    `item.get("sources") or [item.get("source")]` ile `[None]` üretiyordu ve CSV
    üretimindeki `",".join(...)` **TypeError → HTTP 500** veriyordu.

    `horizon_minutes` de taşınır: ölçüm penceresi sinyalin KENDİ ufku olmalıdır
    (yoksa 5dk sinyal 30dk ölçülür ve isabet oranı şişer).
    """
    sources = item.get("sources")
    if not sources:
        sources = [item.get("source") or default_source]
    sources = [str(s) for s in sources if s]
    if not sources:
        sources = [default_source or "unknown"]
    horizon = item.get("horizon_minutes")
    try:
        horizon = float(horizon) if horizon is not None else float(default_horizon)
    except (TypeError, ValueError):
        horizon = float(default_horizon)
    return {"symbol": item.get("symbol"), "detected_at": detected_at,
            "price": item.get("price"), "target_pct": item.get("target_pct"),
            "score": item.get("score"), "confluence": bool(confluence),
            "sources": sources, "horizon_minutes": horizon}


def _resolve_horizon(signal: dict, cap_minutes: float) -> float:
    """Sinyalin KENDİ ufkunu döndür (yoksa 5 dk); [1, cap] aralığına kırp.

    NEDEN: eski kod `min(60, max(5.0, 30.0))` yazıyordu — bu ifade DAİMA 30.0 eder
    ve sinyalin ufkunu tamamen yok sayardı. 5 dakikalık bir sinyali 30 dakika
    ölçmek TP/SL'ye 6× fazla süre tanır; isabet oranını şişirir, MFE'yi yapay
    büyütür ve "ufuk sonunda çık" kapanışını yanlış ana taşır.
    """
    try:
        horizon = float(signal.get("horizon_minutes") or 5.0)
    except (TypeError, ValueError):
        horizon = 5.0
    return min(float(cap_minutes), max(1.0, horizon))


def _dedupe_signals(signals: list[dict]) -> list[dict]:
    """Aynı (sembol, saniye, hedef) üçlüsünü TEK say.

    Journal `velocity_candidates` aynı satırı iki kez taşıyabiliyor (5dk ve 15dk
    profilleri aynı hedefe kalibre olduğunda birebir aynı sembol/zaman/hedef
    oluşuyor). Ölçümde bu, örneklemi ~2× şişirip ortalamaları saptırıyordu;
    üretimde aynı sembol için TEK bildirim gittiği için ölçüm de tek saymalı.
    """
    seen: set = set()
    out: list[dict] = []
    for signal in signals:
        try:
            key = (signal.get("symbol"), round(float(signal.get("detected_at") or 0), 0),
                   round(float(signal.get("target_pct") or 0), 4))
        except (TypeError, ValueError):
            out.append(signal)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(signal)
    return out


async def build_report(hours: int, symbols: list[str] | None, max_signals: int,
                       confluence_window: int | None, skip_fetch: bool,
                       out_path: str | None = None, log=None, progress=None) -> dict:
    """Birleşik radar replay'inin ÇEKİRDEĞİ (DB bağlantısını AÇMAZ/KAPATMAZ).

    Uygulama içi arka plan işi bu fonksiyonu çağırır; CLI `run()` ise burayı
    `init_db`/`close_db` ile sarar. `log(message)` verilirse ilerleme satırları
    oraya akar (canlı log paneli için); verilmezse `print` kullanılır.
    """
    until = time.time()
    since = until - max(1, int(hours)) * 3600
    window = int(confluence_window or getattr(config, "RADAR_CONFLUENCE_WINDOW_SEC", 1800))

    _emit(log, f"[replay] pencere: son {hours} saat ({time.strftime('%Y-%m-%d %H:%M', time.localtime(since))} → şimdi)")
    velocity_rows = await database.list_velocity_candidates_since(since, until)
    rising_rows = await database.list_rising_alerts(limit=1000)

    rising_rows = [r for r in rising_rows
                   if r.get("created_at") is not None and since <= float(r["created_at"]) <= until]
    if symbols:
        wanted = {str(s).replace("_", "").upper() for s in symbols}
        velocity_rows = [r for r in velocity_rows if str(r.get("symbol", "")).upper() in wanted]
        rising_rows = [r for r in rising_rows if str(r.get("symbol", "")).upper() in wanted]

    _emit(log, f"[replay] journal: velocity={len(velocity_rows)} satır, rising={len(rising_rows)} satır")

    # --- Akış 1: velocity-only (üretim radar kapısının journal karşılığı) ---
    raw_gate = float(getattr(config, "MONITORING_MIN_RAW_SCORE", 1400))
    velocity_events = []
    for row in velocity_rows:
        if not row.get("passes") or row.get("velocity_score") is None:
            continue
        raw = float(row["velocity_score"])
        if raw < raw_gate:
            continue
        # ÖLÇEK DÜZELTMESİ (2026-09-16): journal satırı `score` DEĞİL `velocity_score`
        # (HAM) taşır. Ham değeri olduğu gibi bırakmak iki şeyi bozuyordu:
        #   (a) velocity satırlarının `score` kolonu BOŞ kalıyordu,
        #   (b) `combined` akışında ham (binler) ile yükseliş paneli (0-100) AYNI
        #       kolonda karışıyor, `primary` seçimi sayısal kıyasla yapıldığı için
        #       velocity neredeyse her zaman kazanıyordu.
        # Kanonik panel haritası (`velocity._panel_score`, tek kaynak) burada
        # uygulanır → tüm akışlar 0-100 panel ölçeğinde kıyaslanabilir olur.
        item = dict(row)
        item["score"] = _panel_score(raw)
        item["raw_score"] = raw
        # Ufuk journal'da KOLON DEĞİL, `candidate_id` ön ekinde gömülüdür
        # ("vel-5dk-..." / "vel-15dk-..."): kanonik çözücü kullanılır.
        item["horizon_minutes"] = float(
            _velocity_horizon_from_candidate_id(item.get("candidate_id")))
        velocity_events.append(item)
    # --- Akış 2: rising-only ---
    rising_events = list(rising_rows)

    # --- Akış 3: combined (birleşim + confluence) ---
    combined = build_combined_events(velocity_events, rising_events,
                                     confluence_window_sec=window)

    # Sanal giriş listeleri: ölçüm satırına çevir (kaynak etiketi AÇIKÇA verilir).
    velocity_signals = [_as_signal_row(v, v.get("created_at"), default_source="velocity",
                                       default_horizon=5.0)
                        for v in velocity_events]
    rising_signals = [_as_signal_row(r, r.get("created_at"), default_source="rising",
                                     default_horizon=5.0)
                      for r in rising_events]
    combined_signals = [_as_signal_row(c, c.get("detected_at"), c.get("confluence", False),
                                       default_source="combined", default_horizon=5.0)
                        for c in combined]

    # MÜKERRER SİNYAL TEMİZLİĞİ (2026-09-16): journal aynı (sembol, zaman, hedef)
    # üçlüsünü iki kez taşıyabiliyor (5dk/15dk profilleri aynı hedefe kalibre
    # olduğunda birebir aynı satırlar oluşuyor). Ölçümde bu örneklemi ~2× şişirip
    # metrikleri saptırıyordu. Üretimde aynı sembol için tek bildirim gider; ölçüm
    # de tek saymalıdır.
    velocity_signals = _dedupe_signals(velocity_signals)
    rising_signals = _dedupe_signals(rising_signals)
    combined_signals = _dedupe_signals(combined_signals)

    for stream in (velocity_signals, rising_signals, combined_signals):
        stream[:] = [s for s in stream
                     if s["price"] and float(s["price"]) > 0
                     and s["target_pct"] and float(s["target_pct"]) > 0
                     and s["detected_at"] is not None]
        stream.sort(key=lambda s: s["detected_at"])
        if max_signals and len(stream) > max_signals:
            stream[:] = stream[:max_signals]

    result: dict = {
        "window": {"since": since, "until": until, "hours": hours},
        "confluence_window_sec": window,
        "raw_score_gate": raw_gate,
        "journal_counts": {"velocity_rows": len(velocity_rows), "rising_rows": len(rising_rows)},
        "limits": {"yeni eşik icat edilmedi": "her akış kendi kalibre kapısını kullanır"},
        "limitations": [
            "MACD snapshot tarihsel olarak yeniden üretilemez → yükseliş ayağı yalnız kayıtlı kanıt",
            "velocity journal hunisi kısmî (tarama başına top-10 geçen + 5 watchlist)",
            "volume_ratio journal'da 0.0; ML tahmini bugünkü modelin gölgesi",
            "mum içi sıra belirsiz: TP ve SL aynı barda ise SL önce varsayılır (kötümser)",
        ],
    }

    if skip_fetch:
        result["streams"] = {
            "velocity_only": _metrics("velocity_only", velocity_signals),
            "rising_only": _metrics("rising_only", rising_signals),
            "combined": _metrics("combined", combined_signals),
        }
        result["note"] = "kline çekilmedi (--skip-fetch) → yalnız sayım/isabet yapısal alanları"
        result["signals"] = []
        result["report_text"] = _report_text(result)
        _emit(log, result["report_text"])
        return result

    # --- Kline pencereği + merdiven simülasyonu ---
    all_signals = [("velocity_only", s) for s in velocity_signals] \
        + [("rising_only", s) for s in rising_signals] \
        + [("combined", s) for s in combined_signals]
    if not all_signals:
        _emit(log, "[replay] pencerede sinyal yok — ölçülecek bir şey bulunamadı.")
        result["streams"] = {}
        result["signals"] = []
        result["report_text"] = _report_text(result)
        return result

    horizon_cap_min = 60.0     # tek ölçüm penceresi tavanı (radar ufkundan geniş)
    end_fetch = until
    cache: dict[str, list] = {}
    measured: dict[str, list[dict]] = defaultdict(list)
    symbols_seen = sorted({s["symbol"] for _, s in all_signals})
    _emit(log, f"[replay] {len(symbols_seen)} sembol için 1m kline çekilecek (REST)…")

    per_symbol_horizon: dict[str, float] = defaultdict(lambda: horizon_cap_min)
    for idx, (stream_name, signal) in enumerate(all_signals):
        symbol = signal["symbol"]
        detected = float(signal["detected_at"])
        target = float(signal["target_pct"])
        # UFUK: sinyalin KENDİ ufku (5dk/15dk), tavanla kırpılmış — sabit DEĞİL.
        horizon = _resolve_horizon(signal, horizon_cap_min)
        rows = await _load_klines(symbol, detected, end_fetch, cache)
        window_rows = _post_signal_window(rows, int(detected * 1000),
                                          int((detected + horizon * 60) * 1000))
        outcome = _simulate_ladder(window_rows, float(signal["price"]), target, horizon,
                                   signal_ms=int(detected * 1000))
        outcome.update({k: signal[k] for k in
                        ("symbol", "detected_at", "price", "target_pct", "score",
                         "confluence", "sources")})
        outcome["horizon_minutes"] = horizon
        outcome["stream"] = stream_name
        measured[stream_name].append(outcome)
        if progress:
            progress(idx + 1, len(all_signals))
        if (idx + 1) % 25 == 0:
            _emit(log, f"[replay] {idx + 1}/{len(all_signals)} sinyal ölçüldü…")

    result["streams"] = {
        "velocity_only": _metrics("velocity_only", measured["velocity_only"]),
        "rising_only": _metrics("rising_only", measured["rising_only"]),
        "combined": _metrics("combined", measured["combined"]),
    }
    result["samples"] = {
        name: sorted(stream, key=lambda s: -(s.get("net_pct") or 0))[:5]
        for name, stream in measured.items()
    }
    # CSV için TEK satırda her ölçülen sinyal (stream etiketi dahil).
    result["signals"] = [
        s for stream in measured.values() for s in stream
    ]
    result["measurement_horizon_minutes"] = horizon_cap_min
    result["symbols_fetched"] = symbols_seen
    result["report_text"] = _report_text(result)
    _emit(log, result["report_text"])
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, default=str, indent=2)
        _emit(log, f"[replay] JSON yazıldı: {out_path}")
    return result


async def run(hours: int, symbols: list[str] | None, max_signals: int,
              confluence_window: int | None, skip_fetch: bool, out_path: str | None) -> dict:
    """CLI sarmalayıcı: DB bağlantısını açar/kapatır, çekirdeği çağırır.

    Uygulama İÇİ arka plan işi bunu DEĞİL `build_report`'u kullanır — uygulama
    kendi paylaşımlı DB havuzunu kapatmamalıdır.
    """
    await database.init_db()
    try:
        return await build_report(hours, symbols, max_signals, confluence_window,
                                  skip_fetch, out_path=out_path)
    finally:
        await database.close_db()


def _report_text(result: dict) -> str:
    streams = result.get("streams") or {}
    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("BİRLEŞİK RADAR REPLAY RAPORU".center(88))
    lines.append("=" * 88)
    header = (f"{'akış':<14}{'sinyal':>8}{'ölçülen':>9}{'hedef%':>9}{'kazanma%':>10}"
              f"{'ort.net%':>10}{'top.net%':>10}{'ort.MFE%':>10}{'çakışma':>9}")
    lines.append(header)
    lines.append("-" * 88)
    for key in ("velocity_only", "rising_only", "combined"):
        m = streams.get(key)
        if not m:
            lines.append(f"{key:<14}{'—':>8}")
            continue
        def _v(v, fmt="{:.2f}"):
            return fmt.format(v) if v is not None else "—"
        lines.append(f"{key:<14}{m['signals']:>8}{m['measured']:>9}"
                     f"{_v(m['target_hit_rate']):>9}{_v(m['win_rate']):>10}"
                     f"{_v(m['avg_net_pct']):>10}{_v(m['total_net_pct']):>10}"
                     f"{_v(m['avg_mfe_pct']):>10}{m['confluence_count']:>9}")
    lines.append("-" * 88)
    base = streams.get("velocity_only") or {}
    comb = streams.get("combined") or {}
    if base.get("avg_net_pct") is not None and comb.get("avg_net_pct") is not None:
        lift = comb["avg_net_pct"] - base["avg_net_pct"]
        lines.append(f"LIFT (combined - velocity-only) ort. net %: {lift:+.4f} puan")
        # DÜRÜST KARAR (2026-09-16): pozitif lift TEK BAŞINA yetmez. Önceki kural
        # yalnız `lift >= 0` bakıyordu; taban negatifken bu, gürültü seviyesinde
        # bir farkı "ENTEGRE ET" diye yorumluyordu (gerçek koşumda velocity −0.16,
        # combined −0.14 → "+0.0175 puan" ile onay veriyordu; oysa ÜÇ AKIŞ DA
        # NEGATİFTİ ve combined'ın kazanma oranı belirgin biçimde DAHA KÖTÜYDÜ).
        blockers: list[str] = []
        if comb["avg_net_pct"] <= 0:
            blockers.append("combined ort. net POZİTİF DEĞİL")
        if base["avg_net_pct"] <= 0:
            blockers.append("TABAN (velocity-only) POZİTİF DEĞİL — negatif tabanı "
                            "birleştirmek onu pozitife çevirmez")
        if (comb.get("win_rate") or 0) < (base.get("win_rate") or 0) - 2.0:
            blockers.append(f"combined kazanma oranı DAHA KÖTÜ "
                            f"({comb.get('win_rate')} vs {base.get('win_rate')})")
        if blockers:
            lines.append("Ön karar: ENTEGRASYON İÇİN UYGUN DEĞİL")
            for item in blockers:
                lines.append(f"   ✗ {item}")
        else:
            lines.append("Ön karar: ENTEGRASYON İÇİN UYGUN")
    lines.append("")
    lines.append("HEDEF/MFE GEOMETRİSİ (hedef ortalamayı aşıyorsa TP ulaşılamaz → maliyet ödenir):")
    for key in ("velocity_only", "rising_only", "combined"):
        m = streams.get(key) or {}
        if m.get("target_to_mfe_ratio") is None:
            continue
        ratio = float(m["target_to_mfe_ratio"])
        flag = "   ← TP BÜYÜK ÖLÇÜDE ULAŞILAMAZ" if ratio >= 1.5 else ""
        lines.append(f"  {key:<14} hedef {m['avg_target_pct']:.2f}%  /  "
                     f"ort.MFE {m['avg_mfe_pct']:.2f}%  = {ratio:.2f}×{flag}")
    lines.append("")
    lines.append("SINIRLAR (sonuçları okurken bil):")
    for line in result.get("limitations", []):
        lines.append(f"  - {line}")
    lines.append("=" * 88)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Birleşik radar 24h replay/backtest")
    parser.add_argument("--hours", type=int, default=24, help="geriye dönük pencere (saat)")
    parser.add_argument("--symbols", type=str, default="", help="virgülle ayrılmış sembol filtresi")
    parser.add_argument("--max-signals", type=int, default=400, help="akış başına ölçülecek en fazla sinyal")
    parser.add_argument("--confluence-window", type=int, default=None, help="çakışma penceresi (sn)")
    parser.add_argument("--skip-fetch", action="store_true", help="kline çekmeden yalnız sayım")
    parser.add_argument("--out", type=str, default="", help="JSON çıktı yolu")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
    out_path = args.out or os.path.join("..", "work", f"combined_radar_replay_{args.hours}h.json")

    async def _main():
        try:
            await run(args.hours, symbols, args.max_signals, args.confluence_window,
                      args.skip_fetch, out_path)
        finally:
            await database.close_db()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
