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
                     signal_ms: int | None = None, sl_pct: float | None = None,
                     be_gap_pct: float | None = None) -> dict:
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
    # STOP: varsayılan üretim değeri (%3) ama TARAMA için dışarıdan verilebilir.
    # Sabit %3, tipik harekete göre geniş kalıyordu (velocity ort.MFE %1.96) →
    # ters asimetri. Tarama, hangi SL'nin net'i pozitife çevirdiğini ölçer.
    sl_pct_eff = float(sl_pct) if sl_pct is not None else float(config.AUTO_PAPER_SL_PCT_DEFAULT)
    sl = entry * (1 - sl_pct_eff / 100.0)
    tp_gain_pct = (tp / entry - 1) * 100
    be_trigger = max(float(config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT), tp_gain_pct * 0.7)
    tr_trigger = max(float(config.AUTO_PAPER_TRAILING_TRIGGER_PCT), tp_gain_pct * 0.8)
    be_gap = float(be_gap_pct) if be_gap_pct is not None else 0.60   # auto_paper: BREAKEVEN_TRAIL_GAP_PCT
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
        # PARİTE: üretimde breakeven ratchet'i (be_gap) daha sıkı olduğu için
        # trailing ondan GEVŞEK olamaz; auto_paper aynı kırpmayı uygular. Eskiden
        # simülatör ayarlanan değeri (0.80) kullanırken üretim fiilen 0.60
        # uyguluyordu → replay BAŞKA bir merdiveni ölçüyordu.
        gap = min(float(config.AUTO_PAPER_TRAILING_GAP_PCT), be_gap)
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
    # MFE/MAE TEK TARAFLI olmalı (tanımları gereği): MFE "en iyi lehte hareket" ≥ 0,
    # MAE "en kötü aleyhte hareket" ≤ 0. `_mfe_from_window` ORTAK CANLI yardımcıdır
    # ve pencere sinyal barını hariç tuttuğu için ham tepe/dip farkı işaret
    # değiştirebilir; canlı davranışı değiştirmemek için kırpma REPLAY sınırında
    # yapılır. Kırpmasız hâli CSV'de imkânsız değerler üretiyordu (mfe −0.996,
    # mae +0.043) ve hedef/MFE teşhisini sistematik olarak aşağı çekiyordu.
    raw_mfe = _mfe_from_window(window, entry)
    mfe = max(0.0, raw_mfe) if raw_mfe is not None else None
    raw_mae = ((min(float(r[3]) for r in window) / entry - 1) * 100) if window else None
    mae = min(0.0, raw_mae) if raw_mae is not None else None
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
    # ZAMAN KAPSAMASI: iki akış AYNI dönemi kapsamıyorsa akış-ötesi her kıyas
    # (LIFT, kazanma oranı karşılaştırması) geçersizdir. Bu yüzden ilk/son
    # tespit anı raporlanır ve rapor kapsama çakışmasını KENDİ kontrol eder.
    seen_times = [float(s["detected_at"]) for s in signals
                  if s.get("detected_at") is not None]
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
        # KESİŞİM getirisi: birleştirmenin TEK savunulabilir gerekçesi budur —
        # iki kaynağın aynı pencerede hemfikir olduğu alt küme. Sayı ve kazanma
        # oranı tek başına yetmez; ortalamayı MEDYANLA birlikte yazıyoruz çünkü
        # TP isabetleri kuyruk oluşturup ortalamayı şişirir.
        "confluence_avg_net_pct": round(statistics.mean(
            float(s["net_pct"]) for s in confluence), 4) if confluence else None,
        "confluence_median_net_pct": round(statistics.median(
            float(s["net_pct"]) for s in confluence), 4) if confluence else None,
        "first_seen_at": min(seen_times) if seen_times else None,
        "last_seen_at": max(seen_times) if seen_times else None,
        "exit_reasons": dict(sorted(reasons.items())),
    }


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def _enable_utf8_console() -> None:
    """Windows konsolu (cp1254) rapordaki → ★ × ✗ karakterlerini basamıyordu.

    Gerçek olay (2026-09-16): yerel `python scripts/combined_radar_replay_24h.py`
    koşumu `UnicodeEncodeError: 'charmap' codec can't encode character '\\u2192'`
    ile ÇÖKÜYORDU — raporda ok/çarpı/çarpı-kutusu ve Türkçe karakterler var.
    Linux/sunucu (UTF-8) etkilenmiyordu ama yerel doğrulama imkânsız hale
    geliyordu. Çözüm: stdout'u UTF-8'e al, eşlenemeyen karakteri '?' yap
    (çökmek yerine okunur çıktı).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _emit(log, message: str) -> None:
    """İlerleme çıktısı: CLI'da print, uygulama içi işte log callback."""
    if log is None:
        try:
            print(message)
        except UnicodeEncodeError:
            # Konsol UTF-8'e alınamadıysa son çare: eşlenemeyeni düşür.
            print(message.encode("utf-8", "replace").decode("utf-8", "replace"))
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


def _sweep_geometry(sim_inputs: list[dict], targets: list[float],
                    sls: list[float], gaps: list[float] | None = None) -> list[dict]:
    """Sabit (TP, SL, ratchet gap) ızgarasını AYNI kline pencereleri üzerinde dener.

    AMAÇ: "hangi hedef/stop kombinasyonu net'i pozitife çevirir" sorusunu ölçüyle
    cevaplamak. Per-sinyal MFE'ye göre hedef seçmek İLERİYE BAKIŞ (lookahead)
    olurdu; bu yüzden TÜM sinyallere AYNI sabit oran uygulanır — dürüst politika.

    3. boyut `gaps` = breakeven ratchet açıklığı (üretimde 0.60). Bu parametre
    MFE'nin ne kadarının KORUNDUĞUNU belirler: velocity ort.MFE %1.96 iken ort.net
    −0.16 → lehine hareketin neredeyse tamamı geri veriliyor. Ratchet çok sıkıysa
    işlem erken kapanır, çok gevşekse kâr sıfıra döner.

    `sim_inputs`: her sinyal için {stream, rows, entry, horizon, signal_ms}.
    Dönen: her hücre için n / ort.net% / medyan / toplam / kazanma%.
    """
    grid_gaps = [float(g) for g in (gaps or [0.60])]
    out: list[dict] = []
    for target in targets:
        for sl in sls:
            for gap in grid_gaps:
                per_stream: dict[str, list[float]] = defaultdict(list)
                for item in sim_inputs:
                    outcome = _simulate_ladder(
                        item["rows"], item["entry"], target, item["horizon"],
                        signal_ms=item["signal_ms"], sl_pct=sl, be_gap_pct=gap)
                    net = outcome.get("net_pct")
                    if net is not None:
                        per_stream[item["stream"]].append(float(net))
                for stream, nets in per_stream.items():
                    if not nets:
                        continue
                    out.append({
                        "target_pct": target,
                        "sl_pct": sl,
                        "gap_pct": gap,
                        "stream": stream,
                        "n": len(nets),
                        "avg_net_pct": round(statistics.mean(nets), 4),
                        "median_net_pct": round(statistics.median(nets), 4),
                        "total_net_pct": round(sum(nets), 3),
                        "win_rate": round(sum(1 for n in nets if n > 0) / len(nets) * 100, 2),
                    })
    return out


def _pct(value, fmt: str = "{:+.3f}%") -> str:
    """None-güvenli yüzde biçimleyici (rapor satırları için)."""
    return fmt.format(value) if value is not None else "—"


def _sweep_best(sweep: list[dict], stream: str) -> str:
    """Tek satırlık "en iyi nokta" özeti (referans akışlar için)."""
    rows = [r for r in sweep if r["stream"] == stream]
    if not rows:
        return "yok"
    best = max(rows, key=lambda r: r["avg_net_pct"])
    return (f"hedef %{best['target_pct']:.2f} / stop %{best['sl_pct']:.2f} / "
            f"ratchet %{best.get('gap_pct', 0.6):.2f} → "
            f"{best['avg_net_pct']:+.3f}% (kazanma %{best['win_rate']:.1f}, n={best['n']})")


# Geçmiş mumlarla koşan geometri ızgarası. Bu değerler çağıran (buton paneli)
# tarafın varsayılanlarıyla AYNI olmalıdır; ikisi de aynı soruyu ("hangi TP/SL
# net pozitife dönüyor") sorduğu için tek kaynak burada tutulur.
DEFAULT_SWEEP_TARGETS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
DEFAULT_SWEEP_SLS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
DEFAULT_SWEEP_GAPS = [0.3, 0.6, 1.0, 1.5]


def _sweep_region_lines(sweep: list[dict], stream: str) -> list[str]:
    """En iyi hücrenin DAYANIKLILIĞINI ölç (tek hücre maksimumu İYİMSER YANLIDIR).

    192 hücrenin maksimumunu seçmek her zaman "pozitif bir şey" bulur; asıl soru
    pozitif bölgenin YAPISAL olup olmadığıdır. Pozitifler stop ekseninde bir
    tavana kadar kümeleniyorsa ders "stop daraltmak"tır ve taşınabilir; tek bir
    hücreyse gürültüdür ve başka bir dönemde doğrulanmadan kullanılamaz.
    """
    rows = [r for r in sweep if r["stream"] == stream]
    if not rows:
        return []
    positive = [r for r in rows if r["avg_net_pct"] > 0]
    if not positive:
        return [f"  DAYANIKLILIK: 0/{len(rows)} hücre pozitif → bu akışta geometri çözüm "
                f"DEĞİL (hangi TP/SL seçilirse seçilsin maliyet ödeniyor)."]
    all_sls = sorted({r["sl_pct"] for r in rows})
    pos_sls = sorted({r["sl_pct"] for r in positive})
    lines = [f"  DAYANIKLILIK: {len(positive)}/{len(rows)} hücre pozitif; pozitiflerin "
             f"stop aralığı {pos_sls[0]:.2f}–{pos_sls[-1]:.2f} "
             f"(tüm eksen {all_sls[0]:.2f}–{all_sls[-1]:.2f})"]
    if pos_sls[-1] < all_sls[-1]:
        lines.append(f"    → {pos_sls[-1]:.2f} üstündeki TÜM stoplar negatif: bölge stop "
                     f"ekseninde YAPISAL (kazananları değil KAYBEDENLERİ kesmek işe yarıyor).")
    else:
        lines.append("    → pozitifler stop ekseninin tamamına yayılıyor: bölge ZAYIF, "
                     "stop tek başına belirleyici değil.")
    if len(positive) <= 3:
        lines.append(f"  ⚠ yalnız {len(positive)} hücre pozitif → ızgara maksimumu GÜRÜLTÜ "
                     f"olabilir; BAŞKA bir dönemde doğrulanmadan KULLANMA.")
    return lines


def _sweep_lines(sweep: list[dict], stream: str = "combined", top: int = 8) -> list[str]:
    """Tarama sonucunu okunur tabloya çevir + dürüst karar satırı."""
    rows = [r for r in sweep if r["stream"] == stream]
    if not rows:
        return ["(tarama sonucu yok)"]
    rows.sort(key=lambda r: r["avg_net_pct"], reverse=True)
    lines = [f"  {'hedef%':>7}{'stop%':>7}{'ratchet%':>10}{'n':>6}"
             f"{'ort.net%':>10}{'medyan%':>10}{'kazanma%':>10}"]
    for row in rows[:top]:
        lines.append(f"  {row['target_pct']:>7.2f}{row['sl_pct']:>7.2f}"
                     f"{row.get('gap_pct', 0.6):>10.2f}{row['n']:>6}"
                     f"{row['avg_net_pct']:>10.3f}{row['median_net_pct']:>10.3f}"
                     f"{row['win_rate']:>10.2f}")
    best = rows[0]
    positives = [r for r in rows if r["avg_net_pct"] > 0]
    lines.append("")
    lines.append(f"  EN İYİ ({stream}): hedef %{best['target_pct']:.2f} / stop %{best['sl_pct']:.2f}"
                 f" / ratchet %{best.get('gap_pct', 0.6):.2f} → ort.net {best['avg_net_pct']:+.3f}%"
                 f" (kazanma %{best['win_rate']:.1f}, n={best['n']})")
    if positives:
        lines.append(f"  SONUÇ: {len(positives)}/{len(rows)} kombinasyon POZİTİF → geometri "
                     f"düzeltmesi bu sinyal sınıfını kâra çevirebilir (yeniden ölçerek doğrula).")
    else:
        lines.append("  SONUÇ: HİÇBİR TP/SL kombinasyonu pozitif DEĞİL → bu sinyal sınıfında "
                     "(bu ufukta) kenar YOK; geometri değil SEÇİCİLİK sorunu.")
    # Maksimumun kendisi kanıt değil: pozitif BÖLGENİN şekli kanıttır.
    lines.extend(_sweep_region_lines(sweep, stream))
    return lines


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
                       out_path: str | None = None, log=None, progress=None,
                       sweep: bool = False, sweep_targets: list[float] | None = None,
                       sweep_sls: list[float] | None = None,
                       sweep_gaps: list[float] | None = None,
                       offset_hours: float = 0) -> dict:
    """Birleşik radar replay'inin ÇEKİRDEĞİ (DB bağlantısını AÇMAZ/KAPATMAZ).

    Uygulama içi arka plan işi bu fonksiyonu çağırır; CLI `run()` ise burayı
    `init_db`/`close_db` ile sarar. `log(message)` verilirse ilerleme satırları
    oraya akar (canlı log paneli için); verilmezse `print` kullanılır.

    `offset_hours` > 0 ise pencere geçmişe kaydırılır (out-of-sample dönem).
    """
    # OUT-OF-SAMPLE (2026-09-17): pencere eskiden HER ZAMAN "şimdi"de bitiyordu;
    # bu yüzden aynı ızgarayı BAŞKA bir dönemde koşmak imkânsızdı. Tek dönemde 192
    # hücrenin MAKSİMUMUNU seçmek iyimser yanlıdır ve rapor bunu "tek dönem yeterli
    # kanıt değil" diye itiraf ediyordu ama düzeltemiyordu. `offset_hours` ile aynı
    # ızgara ayrı bir dönemde koşulur; asıl soru "en iyi hücre DAYANIYOR mu" olur.
    offset = max(0.0, float(offset_hours or 0))
    until = time.time() - offset * 3600
    since = until - max(1, int(hours)) * 3600
    window = int(confluence_window or getattr(config, "RADAR_CONFLUENCE_WINDOW_SEC", 1800))

    period_label = (f"son {hours} saat" if offset <= 0
                    else f"{hours} saat, {offset:g} saat ÖNCE (out-of-sample)")
    _emit(log, f"[replay] pencere: {period_label} "
               f"({time.strftime('%Y-%m-%d %H:%M', time.localtime(since))} → "
               f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(until))})")
    # KAPSAMA EŞLEŞMESİ (2026-09-16): iki akış AYNI okuma semantiğiyle ve AYNI
    # bütçeyle okunmalı. Eskiden rising `list_rising_alerts(limit=1000)` ile EN
    # YENİ, velocity ise ARTAN sırada İLK N satırla geliyordu → iki akış AYRI
    # dönemleri kapsıyordu (aralarında ~25 saat boşluk ölçüldü), `confluence`
    # yapısal olarak 0 çıkıyordu ve raporun LIFT satırı iki FARKLI dönemi
    # kıyaslıyordu. Artık ikisi de zaman pencereli + ARTAN sırada.
    journal_limit = 20000
    velocity_rows = await database.list_velocity_candidates_since(
        since, until, limit=journal_limit)
    rising_rows = await database.list_rising_alerts_since(
        since, until, limit=journal_limit)

    # KIRPILMA TESPİTİ: satır sayısı bütçeye dayandıysa akış EKSİKTİR (pencere
    # sonuna ulaşılamamış olabilir) → raporda açıkça bildirilir, sessizce
    # "tam veri" gibi sunulmaz.
    truncated = {
        "velocity": len(velocity_rows) >= journal_limit,
        "rising": len(rising_rows) >= journal_limit,
    }
    if any(truncated.values()):
        _emit(log, f"[replay] UYARI: journal bütçesi doldu (velocity="
                   f"{len(velocity_rows)}, rising={len(rising_rows)} / {journal_limit}) "
                   f"→ o akış pencerenin tamamını kapsamıyor olabilir.")

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
    # HUNİ SAYAÇLARI: "0 sinyal" bir hata mı, veri mi yok — tek bakışta
    # anlaşılsın. Gerçek olay (2026-09-17): 24 saatlik koşum BOŞ CSV üretti ve
    # huninin NERESİNDE düştüğü hiçbir yerde yazmıyordu.
    funnel: dict = {
        "journal_rows": {"velocity": len(velocity_rows), "rising": len(rising_rows)},
        "velocity_events_after_gate": len(velocity_events),
        "combined_events": len(combined),
        "confluence_events": sum(1 for c in combined if c.get("confluence")),
    }
    velocity_signals = _dedupe_signals(velocity_signals)
    rising_signals = _dedupe_signals(rising_signals)
    combined_signals = _dedupe_signals(combined_signals)
    funnel["after_dedupe"] = {"velocity": len(velocity_signals),
                              "rising": len(rising_signals),
                              "combined": len(combined_signals)}

    for stream in (velocity_signals, rising_signals, combined_signals):
        stream[:] = [s for s in stream
                     if s["price"] and float(s["price"]) > 0
                     and s["target_pct"] and float(s["target_pct"]) > 0
                     and s["detected_at"] is not None]
        stream.sort(key=lambda s: s["detected_at"])
        if max_signals and len(stream) > max_signals:
            stream[:] = stream[:max_signals]
    funnel["after_price_target_filter"] = {"velocity": len(velocity_signals),
                                           "rising": len(rising_signals),
                                           "combined": len(combined_signals)}

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

    # TANISAL ALANLAR ERKEN DÖNÜŞLERDEN ÖNCE KURULUR (2026-09-17): `if not
    # all_signals: return` yolu tam olarak "0 sinyal" durumudur — yani tanının EN
    # ÇOK gerektiği yol — ve bu alanlar orada ATLANIYORDU. Sonuç: boş koşumda huni
    # ve journal aralığı kayboluyor, kullanıcı sebebi olmayan BOŞ bir CSV ile
    # kalıyordu (yaşandı). Artık her dönüş yolu aynı tanıyı taşır.
    result["truncated"] = truncated
    result["sweep"] = []
    result["funnel"] = funnel
    # DÖNEM KİMLİĞİ burada da kurulur: out-of-sample koşumda hangi pencerenin
    # ölçüldüğü sonuçta taşınmalı. Aşağıda (uzun yolda) kurulsaydı `skip_fetch` ve
    # "0 sinyal" dönüşleri onu ATLARDI — tanıyı taşıyan alanlar her dönüş yolunda
    # bulunmalı (aynı hata bir kez yaşandı). `result["sweep"]` yukarıda
    # sıfırlandığı için tarama alanı da boş kalır; tarama yalnız uzun yolda dolar.
    result["period"] = {"hours": int(hours), "offset_hours": offset,
                        "since": since, "until": until, "label": period_label}
    # PENCERE BAĞIMSIZ journal aralığı: "0 sinyal" durumunda tek soru "pencere mi
    # veriyi kaçırıyor" olduğu için journal'ın GERÇEK son satır zamanı gerekir.
    try:
        result["journal_coverage"] = await database.journal_coverage()
    except Exception as exc:
        result["journal_coverage"] = {"error": f"{type(exc).__name__}: {exc}"}

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
    # GEOMETRİ TARAMASI için: her sinyalin penceresi + girişi saklanır; ızgara aynı
    # pencereler üzerinde koşar (yeniden REST çekimi YOK).
    sim_inputs: list[dict] = []
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
        sim_inputs.append({"stream": stream_name, "rows": window_rows,
                           "entry": float(signal["price"]), "horizon": horizon,
                           "signal_ms": int(detected * 1000)})
        outcome = _simulate_ladder(window_rows, float(signal["price"]), target, horizon,
                                   signal_ms=int(detected * 1000))
        outcome.update({k: signal[k] for k in
                        ("symbol", "detected_at", "price", "target_pct", "score",
                         "confluence", "sources")})
        outcome["horizon_minutes"] = horizon
        outcome["stream"] = stream_name
        measured[stream_name].append(outcome)
        # KESİŞİM AYNASI (2026-09-17): iki kaynak aynı pencerede hemfikirse AYNI
        # kline penceresi `confluence` akışı olarak da ölçülür. Gerçek koşumda tek
        # POZİTİF alt küme buydu (n=11, ort +0.468%, medyan +0.530%, kazanma %72.7)
        # ama geometri taramasında akış olarak YOKTU — yani "kesişim kârlı bir
        # geometriye sahip mi" sorusu cevaplanamıyordu. Ek REST çekimi YOK: pencere
        # ve giriş zaten bellekte.
        if stream_name == "combined" and signal.get("confluence"):
            sim_inputs.append({**sim_inputs[-1], "stream": "confluence"})
            measured["confluence"].append({**outcome, "stream": "confluence"})
        if progress:
            progress(idx + 1, len(all_signals))
        if (idx + 1) % 25 == 0:
            _emit(log, f"[replay] {idx + 1}/{len(all_signals)} sinyal ölçüldü…")

    result["streams"] = {
        "velocity_only": _metrics("velocity_only", measured["velocity_only"]),
        "rising_only": _metrics("rising_only", measured["rising_only"]),
        "combined": _metrics("combined", measured["combined"]),
        # Kesişim: birleşimin ALT KÜMESİ, ayrı akış olarak taşınır (tarama +
        # rapor bunu kullanır). CSV'ye YAZILMAZ (aşağıya bak) — aynı sinyali iki
        # kez saymak örneklemi şişirirdi.
        "confluence": _metrics("confluence", measured["confluence"]),
    }
    result["samples"] = {
        name: sorted(stream, key=lambda s: -(s.get("net_pct") or 0))[:5]
        for name, stream in measured.items() if name != "confluence"
    }
    # CSV için TEK satırda her ölçülen sinyal (stream etiketi dahil). `confluence`
    # HARİÇ: kesişim satırları `combined` satırlarının BİREBİR kopyasıdır (aynı
    # pencere, aynı giriş) → dahil etmek örneklemi ve net toplamı ikiye katlardı.
    # Kesişimi CSV'de görmek için mevcut `confluence` kolonu süzülür.
    result["signals"] = [
        s for name, stream in measured.items() if name != "confluence" for s in stream
    ]
    result["measurement_horizon_minutes"] = horizon_cap_min
    result["symbols_fetched"] = symbols_seen
    # GEOMETRİ TARAMASI: aynı pencereler, sabit TP/SL ızgarası.
    if sweep:
        # IZGARA VARSAYILANLARI: parametreler `None` gelebilir (doğrudan çağrı).
        # Eksikken `len(None)` ile ÇÖKÜYORDU (2026-09-17'de testte yakalandı) —
        # `sweep=True` verip ızgara vermemek makul bir çağrıdır.
        grid_targets = list(sweep_targets or DEFAULT_SWEEP_TARGETS)
        grid_sls = list(sweep_sls or DEFAULT_SWEEP_SLS)
        grid_gaps = list(sweep_gaps or DEFAULT_SWEEP_GAPS)
        _emit(log, f"[replay] geometri taraması: {len(grid_targets)}×{len(grid_sls)}"
                   f"×{len(grid_gaps)} kombinasyon × {len(sim_inputs)} sinyal…")
        result["sweep"] = _sweep_geometry(sim_inputs, grid_targets, grid_sls, grid_gaps)
    result["report_text"] = _report_text(result)
    _emit(log, result["report_text"])
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, default=str, indent=2)
        _emit(log, f"[replay] JSON yazıldı: {out_path}")
    return result


async def run(hours: int, symbols: list[str] | None, max_signals: int,
              confluence_window: int | None, skip_fetch: bool, out_path: str | None,
              sweep: bool = False, sweep_targets: list[float] | None = None,
              sweep_sls: list[float] | None = None,
              sweep_gaps: list[float] | None = None,
              offset_hours: float = 0) -> dict:
    """CLI sarmalayıcı: DB bağlantısını açar/kapatır, çekirdeği çağırır.

    Uygulama İÇİ arka plan işi bunu DEĞİL `build_report`'u kullanır — uygulama
    kendi paylaşımlı DB havuzunu kapatmamalıdır.
    """
    await database.init_db()
    try:
        return await build_report(hours, symbols, max_signals, confluence_window,
                                  skip_fetch, out_path=out_path,
                                  sweep=sweep, sweep_targets=sweep_targets,
                                  sweep_sls=sweep_sls, sweep_gaps=sweep_gaps,
                                  offset_hours=offset_hours)
    finally:
        await database.close_db()


def _report_text(result: dict) -> str:
    streams = result.get("streams") or {}
    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("BİRLEŞİK RADAR REPLAY RAPORU".center(88))
    lines.append("=" * 88)
    # DÖNEM SATIRI: out-of-sample koşumda rapor "24 saat" derse iki farklı koşum
    # karıştırılır; hangi pencerenin ölçüldüğü raporun başında yazılı olmalı.
    period = result.get("period") or {}
    if period:
        lines.append(f"DÖNEM: {period.get('label') or ''}  "
                     f"({time.strftime('%d.%m %H:%M', time.localtime(period['since']))} → "
                     f"{time.strftime('%d.%m %H:%M', time.localtime(period['until']))})"
                     + ("   ← OUT-OF-SAMPLE" if (period.get("offset_hours") or 0) > 0 else ""))
        lines.append("")
    # Sütun adı DÜRÜST olmalı: buradaki değer `target_hit_rate` (TP'ye dokunma
    # oranı), ortalama hedef DEĞİL. Eskiden `hedef%` yazıyordu ve ortalama hedef
    # sanılıyordu; ort. hedef ayrı (`avg_target_pct`) ve HEDEF/MFE bölümünde.
    header = (f"{'akış':<14}{'sinyal':>8}{'ölçülen':>9}{'TP%':>9}{'kazanma%':>10}"
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

    # SIFIR SİNYAL UYARISI: boş bir rapor sessizce "başarılı indirme" olmasın.
    # Huninin neresinde düştüğü ve journal'ın GERÇEK son satır zamanı burada
    # yazılır; kullanıcı "saat sayısını artır" mı "veri yok" mu olduğunu görür.
    if not (result.get("signals") or []):
        f = result.get("funnel") or {}
        jr = f.get("journal_rows") or {}
        cov = result.get("journal_coverage") or {}
        lines.append("!! HİÇ SİNYAL YOK — indirilen CSV yalnız BAŞLIK satırı içerir.")
        lines.append(f"   pencere       : son {result.get('window', {}).get('hours')} saat")
        lines.append(f"   journal satırı: velocity={jr.get('velocity', 0)}, rising={jr.get('rising', 0)}")
        for key in ("velocity", "rising"):
            latest = cov.get(f"{key}_latest")
            if latest is not None:
                lines.append(f"   {key} journal son satır: "
                             f"{time.strftime('%d.%m %H:%M', time.localtime(float(latest)))}"
                             f"  (toplam {cov.get(f'{key}_count')} satır)")
            elif cov.get(f"{key}_count") == 0:
                lines.append(f"   {key} journal TAMAMEN BOŞ (0 satır) — replay için veri yok.")
            elif cov.get(f"{key}_error"):
                lines.append(f"   {key} journal okunamadı: {cov[f'{key}_error']}")
        lines.append(f"   süzgeç öncesi : velocity_events={f.get('velocity_events_after_gate', 0)}, "
                     f"combined_events={f.get('combined_events', 0)}, "
                     f"çakışma={f.get('confluence_events', 0)}")
        lines.append(f"   süzgeç sonrası: {f.get('after_price_target_filter')}")
        lines.append("   → journal'ın son satırı pencereden ESKİYSE saat sayısını ARTIR; "
                     "journal 0 satırsa veri hiç yazılmamıştır.")
        lines.append("")

    # KAPSAMA KONTROLÜ (2026-09-16): akış-ötesi her kıyas (LIFT, kazanma oranı)
    # yalnız iki akış AYNI dönemi kapsıyorsa anlamlıdır. Gerçek bir koşumda
    # velocity pencerenin BAŞINI, rising SONUNU kapsıyordu (aralarında ~25 saat
    # boşluk): `confluence` yapısal olarak 0 çıktı ve "+0.2763 puan LIFT" iki
    # FARKLI piyasa dönemini kıyaslıyordu. Rapor bunu kendi tespit edip kıyası
    # GEÇERSİZ ilan eder; aksi hâlde sayı doğru görünüp karar yanlış olur.
    def _span(m: dict) -> tuple[float | None, float | None]:
        return m.get("first_seen_at"), m.get("last_seen_at")

    cover_ok = True
    v_first, v_last = _span(base)
    r_first, r_last = _span(streams.get("rising_only") or {})
    if None not in (v_first, v_last, r_first, r_last):
        overlap = min(v_last, r_last) - max(v_first, r_first)
        cover_ok = overlap >= 0
    lines.append("KAPSAMA (her akışın gerçekten kapsadığı dönem):")
    for key in ("velocity_only", "rising_only", "combined"):
        m = streams.get(key) or {}
        first, last = _span(m)
        if first is None:
            continue
        lines.append(f"  {key:<14} {time.strftime('%d.%m %H:%M', time.localtime(first))}"
                     f" → {time.strftime('%d.%m %H:%M', time.localtime(last))}"
                     f"   ({(last - first) / 3600:.1f} saat)")
    for key, is_trunc in (result.get("truncated") or {}).items():
        if is_trunc:
            lines.append(f"  ⚠ {key} journal bütçesi DOLDU → bu akış pencerenin tamamını "
                         f"kapsamıyor olabilir (okuma sırası ilk N). Saat sayısını "
                         f"kısaltarak TAM kapsama al.")
    if not cover_ok:
        lines.append("  ✗ velocity ve rising AYNI dönemi kapsamiyor → akış-ötesi kıyas "
                     "(LIFT/kazanma) GEÇERSİZ; çakışma alt kümesi yapısal olarak 0.")
    lines.append("")

    if base.get("avg_net_pct") is not None and comb.get("avg_net_pct") is not None:
        lift = comb["avg_net_pct"] - base["avg_net_pct"]
        if cover_ok:
            lines.append(f"LIFT (combined - velocity-only) ort. net %: {lift:+.4f} puan")
        else:
            lines.append(f"LIFT (combined - velocity-only) ort. net %: {lift:+.4f} puan"
                         f"   ← GEÇERSİZ (kapsamalar örtüşmüyor)")
        # DÜRÜST KARAR (2026-09-16): pozitif lift TEK BAŞINA yetmez. Önceki kural
        # yalnız `lift >= 0` bakıyordu; taban negatifken bu, gürültü seviyesinde
        # bir farkı "ENTEGRE ET" diye yorumluyordu (gerçek koşumda velocity −0.16,
        # combined −0.14 → "+0.0175 puan" ile onay veriyordu; oysa ÜÇ AKIŞ DA
        # NEGATİFTİ ve combined'ın kazanma oranı belirgin biçimde DAHA KÖTÜYDÜ).
        blockers: list[str] = []
        if not cover_ok:
            blockers.append("KAPSAMA ÖRTÜŞMÜYOR — akışlar farklı dönemlerden; kıyas "
                            "geçersiz, düzeltip YENİDEN koş")
        if comb["avg_net_pct"] <= 0:
            blockers.append("combined ort. net POZİTİF DEĞİL")
        if base["avg_net_pct"] <= 0:
            blockers.append("TABAN (velocity-only) POZİTİF DEĞİL — negatif tabanı "
                            "birleştirmek onu pozitife çevirmez")
        if cover_ok and (comb.get("win_rate") or 0) < (base.get("win_rate") or 0) - 2.0:
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
    # Maliyet TEK yerde hesaplanır: hem kesişim bloğu hem MALİYET DUVARI kullanır
    # (kesişim bloğu sweep'ten sonra, eski `cost` tanımından ÖNCE gelir).
    cost = round_trip_cost_pct()
    if result.get("sweep"):
        lines.append("GEOMETRİ TARAMASI (sabit TP/SL ızgarası, AYNI pencereler — ileriye bakış YOK):")
        lines.extend(_sweep_lines(result["sweep"], stream="combined", top=8))
        lines.append("")
        lines.append(f"  (velocity_only referans: en iyi "
                     f"{_sweep_best(result['sweep'], 'velocity_only')})")
        if not cover_ok:
            lines.append("  ✗ KAPSAMA ÖRTÜŞMÜYOR → ızgaradaki akış-ötesi kıyaslar "
                         "(combined vs velocity referansı) GEÇERSİZ.")
        lines.append("")
        # KESİŞİM GEOMETRİSİ: birleştirmenin tek savunulabilir gerekçesi "iki
        # kaynak hemfikir" alt kümesidir. Akış ortalamaları negatifken bu alt küme
        # pozitif çıkabiliyor; o hâlde karar "birleştirme kötü" değil "birleştirmeyi
        # KESİŞİME daralt" olur. Bunun için kesişimin KENDİ ızgarası gerekir.
        conf_rows = [r for r in result["sweep"] if r["stream"] == "confluence"]
        if conf_rows:
            lines.append("KESİŞİM GEOMETRİSİ (iki kaynak aynı pencere — birleşimin kesişimi):")
            lines.extend(_sweep_lines(conf_rows, stream="confluence", top=8))
            best = max(conf_rows, key=lambda r: r["avg_net_pct"])
            bgross = best["avg_net_pct"] + cost
            lines.append(f"  → kesişim tavanı brüt {bgross:+.3f}% / maliyet {cost:.3f}%"
                         + ("  ⇒ MALİYETİ AŞIYOR: kesişime daraltılmış birleştirme "
                            "aday; n büyüdükçe doğrula." if bgross > cost else
                            "  ⇒ maliyetin ALTINDA: kesişim de kâra geçmiyor."))
            if best["n"] < 30:
                lines.append(f"  ⚠ n={best['n']} < 30 → ızgara maksimumu KÜÇÜK örneklemde "
                             f"seçildi; TP kuyruğuna duyarlı. MEDYANI ve daha uzun pencereyi oku.")
            lines.append("")

    # MALİYET DUVARI: verdict'i iddia değil ARİTMETİK yapar. net = brüt − maliyet
    # olduğu için brüt = net + maliyet; kâr için brüt > maliyet ŞART. Taramanın
    # tavanı (en iyi hücrenin brütü) bile maliyetin altındaysa, hiçbir TP/SL
    # geometrisi kâra geçemez → sorun geometri değil SEÇİCİLİK.
    lines.append("MALİYET DUVARI (net = brüt − gidiş-dönüş maliyet; kâr için brüt > maliyet):")
    lines.append(f"  gidiş-dönüş maliyet {cost:.3f}%  ({cost / 2:.3f}%/bacak × 2: "
                 f"komisyon + slipaj)")
    for key in ("velocity_only", "rising_only", "combined"):
        m = streams.get(key) or {}
        if m.get("avg_net_pct") is None:
            continue
        gross = m["avg_net_pct"] + cost
        lines.append(f"  {key:<14} net {m['avg_net_pct']:+.3f}%  →  brüt {gross:+.3f}%"
                     f"   açık {gross - cost:+.3f} puan")
    if result.get("sweep"):
        tops: list[tuple[str, dict]] = []
        for key in ("velocity_only", "rising_only", "combined"):
            rows = [r for r in result["sweep"] if r["stream"] == key]
            if rows:
                tops.append((key, max(rows, key=lambda r: r["avg_net_pct"])))
        if tops:
            tkey, tbest = max(tops, key=lambda kv: kv[1]["avg_net_pct"])
            tgross = tbest["avg_net_pct"] + cost
            lines.append(f"  TARAMA TAVANI: brüt {tgross:+.3f}%  ({tkey} hedef "
                         f"{tbest['target_pct']:.2f} / stop {tbest['sl_pct']:.2f} / "
                         f"ratchet {tbest.get('gap_pct', 0.6):.2f})")
            lines.append(
                f"  → tavan maliyetin {cost - tgross:.3f} puan ALTINDA: hiçbir geometri bu "
                f"açığı kapatamaz → sorun geometri değil SEÇİCİLİK."
                if tgross <= cost else
                f"  → tavan maliyeti {tgross - cost:.3f} puan AŞIYOR: geometri kâra "
                f"çevirebilir, ÖNCE üretimde doğrula (tek dönem yeterli kanıt değil).")
            if not cover_ok:
                lines.append("  ✗ KAPSAMA ÖRTÜŞMÜYOR → tavan akışlar arası maksimumdur ve "
                             "bu kıyas geçersizdir.")
    lines.append("")
    # KESİŞİM: birleştirmenin TEK savunulabilir gerekçesi "iki kaynak hemfikir"
    # alt kümesidir. Akış ortalamaları negatifken bu alt küme pozitif çıkabilir;
    # o zaman karar "birleştirme kötü" değil "birleştirmeyi KESİŞİME daralt"
    # olur. Küçük n'de ortalamayı medyanla birlikte okumak şarttır.
    conf_streams = [(k, streams.get(k) or {})
                    for k in ("velocity_only", "rising_only", "combined")]
    if any(m.get("confluence_count") for _k, m in conf_streams):
        lines.append("ÇAKIŞMA ALT KÜMESİ (iki kaynak AYNI pencerede — birleşimin kesişimi):")
        for key, m in conf_streams:
            if not m.get("confluence_count"):
                continue
            lines.append(f"  {key:<14} n={m['confluence_count']:<5}"
                         f"ort.net {_pct(m.get('confluence_avg_net_pct'))}  "
                         f"medyan {_pct(m.get('confluence_median_net_pct'))}  "
                         f"kazanma {_pct(m.get('confluence_win_rate'), '{:.2f}')}")
            if m["confluence_count"] < 30:
                lines.append(f"  ⚠ n={m['confluence_count']} < 30 → HİPOTEZ, karar verisi DEĞİL;"
                             f" ortalamayı şişiren TP kuyruğu olabilir, MEDYANI oku ve daha"
                             f" uzun pencereyle doğrula.")
        lines.append("")
    lines.append("SINIRLAR (sonuçları okurken bil):")
    for line in result.get("limitations", []):
        lines.append(f"  - {line}")
    lines.append("=" * 88)
    return "\n".join(lines)


def main() -> None:
    _enable_utf8_console()
    parser = argparse.ArgumentParser(description="Birleşik radar 24h replay/backtest")
    parser.add_argument("--hours", type=int, default=24, help="geriye dönük pencere (saat)")
    parser.add_argument("--offset-hours", type=float, default=0.0,
                        help="pencereyi geçmişe kaydır (saat) — out-of-sample doğrulama: "
                             "aynı ızgarayı BAŞKA bir dönemde koş")
    parser.add_argument("--symbols", type=str, default="", help="virgülle ayrılmış sembol filtresi")
    parser.add_argument("--max-signals", type=int, default=400, help="akış başına ölçülecek en fazla sinyal")
    parser.add_argument("--confluence-window", type=int, default=None, help="çakışma penceresi (sn)")
    parser.add_argument("--skip-fetch", action="store_true", help="kline çekmeden yalnız sayım")
    parser.add_argument("--out", type=str, default="", help="JSON çıktı yolu")
    parser.add_argument("--sweep", action="store_true",
                        help="sabit TP/SL ızgarasını aynı pencerelerde tara (kenar var mı?)")
    parser.add_argument("--sweep-targets", type=str, default="0.5,0.75,1,1.5,2,3,4,6",
                        help="tarama hedef% listesi (virgülle)")
    parser.add_argument("--sweep-sls", type=str, default="0.5,0.75,1,1.5,2,3",
                        help="tarama stop% listesi (virgülle)")
    parser.add_argument("--sweep-gaps", type=str, default="0.3,0.6,1.0,1.5",
                        help="tarama ratchet (breakeven gap) % listesi — MFE koruma boyutu")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
    # Varsayılan dosya adı DÖNEMİ içermeli: out-of-sample koşum aynı `24h.json`
    # üzerine yazarsa elimizdeki tek kanıtı (baz dönem) sessizce kaybederdik.
    _suffix = f"{args.hours}h" + (f"_oos{int(args.offset_hours)}h" if args.offset_hours else "")
    out_path = args.out or os.path.join("..", "work", f"combined_radar_replay_{_suffix}.json")
    sweep_targets = [float(x) for x in args.sweep_targets.split(",") if x.strip()]
    sweep_sls = [float(x) for x in args.sweep_sls.split(",") if x.strip()]
    sweep_gaps = [float(x) for x in args.sweep_gaps.split(",") if x.strip()]

    async def _main():
        try:
            await run(args.hours, symbols, args.max_signals, args.confluence_window,
                      args.skip_fetch, out_path, sweep=args.sweep,
                      sweep_targets=sweep_targets, sweep_sls=sweep_sls,
                      sweep_gaps=sweep_gaps, offset_hours=args.offset_hours)
        finally:
            await database.close_db()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
