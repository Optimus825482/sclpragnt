"""MA kesişim BUY sinyali — geriye dönük replay ölçümü (saf hesap; ağ/DB yok).

2026-10-20 (kullanıcı isteği): canlı motorla (ma_buy_signals.detect_ma_buy) birebir aynı kuralla üretilen sinyallerin
ardından fiyat EN FAZLA ne kadar yükseldi? Birincil ölçüt: sinyal mumunun kapanışından BİR SONRAKİ sinyale kadar
(aynı sembol + zaman dilimi) görülen en yüksek `high` (MFE). Sabit ufuklar (15 dk / 1 sa / 4 sa / 24 sa) ek sütundur
ve bir sonraki sinyalle SINIRLANMAZ. Son sinyalin "sonraki sinyali" yoktur → veri sonuna kadar ölçülür ve
`open_ended=True` ile işaretlenir (rapor bunları ayrı sayar).

Veri çekme / önbellek / rapor dosyası: `scripts/ma_buy_replay_7d.py`.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Sequence

from app import ma_buy_signals
from app.ma_buy_notify import tf_label
from app.ma_buy_tracker import SUPPORTED_TF_MS

HORIZONS_MIN = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
MFE_THRESHOLDS = (1.0, 2.0, 3.0)


def _pct(value: float, base: float) -> float:
    return round((float(value) / base - 1.0) * 100.0, 4)


def outcomes_for_signals(bars: Sequence[dict], signals: Sequence[dict], *, tf: str, target_pct: float,
                         symbol: str = "") -> list[dict]:
    """Her sinyal için sonuç satırı. `bars`: kapanmış mumlar (artan), `signals`: detect_ma_buy çıktısı (artan indeks)."""
    tf_ms = SUPPORTED_TF_MS[tf]
    bar_min = max(1, tf_ms // 60_000)
    out: list[dict] = []
    for n, sig in enumerate(signals):
        i = int(sig["index"])
        price = float(bars[i]["close"])
        if price <= 0:
            continue
        open_ended = n + 1 >= len(signals)
        j = len(bars) - 1 if open_ended else int(signals[n + 1]["index"])
        window = list(bars[i + 1:j + 1])
        if window:
            highs = [float(b["high"]) for b in window]
            peak_idx = max(range(len(highs)), key=lambda k: (highs[k], -k))   # eşitte ilk zirve
            mfe = _pct(highs[peak_idx], price)
            mae = _pct(min(float(b["low"]) for b in window), price)
            minutes_to_peak = (peak_idx + 1) * bar_min
        else:
            mfe, mae, minutes_to_peak = 0.0, 0.0, 0
        horizons: dict = {}
        for name, minutes in HORIZONS_MIN.items():
            need = minutes // bar_min if minutes % bar_min == 0 else 0
            after = list(bars[i + 1:i + 1 + need]) if need >= 1 else []
            horizons[name] = (_pct(max(float(b["high"]) for b in after), price)
                              if need >= 1 and len(after) >= need else None)
        out.append({
            "symbol": symbol, "timeframe": tf, "rules": list(sig.get("rules") or []), "index": i,
            "signal_time_ms": int(bars[i].get("open_ms") or 0), "signal_price": price,
            "mfe_pct": mfe, "mae_pct": mae, "minutes_to_peak": minutes_to_peak,
            "bars_to_next": j - i, "minutes_to_next": (j - i) * bar_min,
            "close_at_next_pct": _pct(float(bars[j]["close"]), price),
            "open_ended": open_ended, "target_hit": mfe >= float(target_pct), "horizons": horizons,
        })
    return out


def _stats(rows: list[dict]) -> dict:
    mfe = [float(r["mfe_pct"]) for r in rows]
    peaks = [int(r.get("minutes_to_peak") or 0) for r in rows]
    nexts = [int(r.get("minutes_to_next") or 0) for r in rows]
    q = statistics.quantiles(mfe, n=4) if len(mfe) >= 2 else None
    stats = {
        "n": len(rows),
        "median_mfe_pct": round(statistics.median(mfe), 4) if mfe else None,
        "mean_mfe_pct": round(statistics.fmean(mfe), 4) if mfe else None,
        "p25_mfe_pct": round(q[0], 4) if q else None,
        "p75_mfe_pct": round(q[2], 4) if q else None,
        "max_mfe_pct": round(max(mfe), 4) if mfe else None,
        "target_hit_rate": round(sum(1 for r in rows if r.get("target_hit")) / len(rows), 4) if rows else None,
        "open_ended": sum(1 for r in rows if r.get("open_ended")),
        "median_minutes_to_peak": statistics.median(peaks) if peaks else None,
        "median_minutes_to_next": statistics.median(nexts) if nexts else None,
    }
    for t in MFE_THRESHOLDS:
        stats[f"share_ge_{int(t)}pct"] = round(sum(1 for v in mfe if v >= t) / len(mfe), 4) if mfe else None
    return stats


def aggregate(rows: Sequence[dict]) -> dict:
    """{tf: {"all": stats, rule: stats, ...}} — kural kırılımı sinyalin içerdiği her kural için ayrı sayılır."""
    by_tf: dict = defaultdict(list)
    for r in rows:
        by_tf[str(r["timeframe"])].append(r)
    out: dict = {}
    for tf in sorted(by_tf, key=lambda t: SUPPORTED_TF_MS.get(t, 0)):
        items = by_tf[tf]
        section = {"all": _stats(items)}
        for rule in ma_buy_signals.ALL_RULES:
            subset = [r for r in items if rule in (r.get("rules") or [])]
            if subset:
                section[rule] = _stats(subset)
        out[tf] = section
    return out


def _f(v, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}{suffix}"
    return f"{v}{suffix}"


def _ms_to_text(ms: int) -> str:
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone(_dt.timedelta(hours=3))).strftime("%d.%m %H:%M")
    except (OverflowError, OSError, ValueError):
        return str(ms)


def render_markdown(rows: Sequence[dict], agg: dict, meta: dict) -> str:
    lines = [
        f"# MA BUY 7 günlük replay — sinyal sonrası en yüksek yükseliş ({meta.get('generated_at', '')})",
        "",
        f"Kapsam: son {meta.get('days', 7)} gün, {meta.get('symbols', '?')} sembol, zaman dilimleri "
        f"{', '.join(tf_label(t) for t in agg) or '—'}. Kural ve parametreler canlı motorla aynı "
        f"({meta.get('rules_text', 'SMA 7/20/99, StochRSI K ≤ 80 (M1 hariç)')}).",
        "",
        "**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` "
        "(MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. "
        "15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.",
        "",
        "## Özet (TF bazında)",
        "",
        "| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tf, section in agg.items():
        for rule, s in section.items():
            lines.append(
                f"| {tf_label(tf)} | {rule} | {s['n']} | {_f(s['median_mfe_pct'], '%')} | {_f(s['mean_mfe_pct'], '%')} | "
                f"{_f(s['p25_mfe_pct'], '%')} | {_f(s['p75_mfe_pct'], '%')} | {_f(s['share_ge_1pct'])} | {_f(s['share_ge_2pct'])} | "
                f"{_f(s['share_ge_3pct'])} | {_f(s['target_hit_rate'])} | {_f(s['median_minutes_to_peak'])} | "
                f"{_f(s['median_minutes_to_next'])} | {s['open_ended']} |")
    lines += ["", "## Sabit ufuklarda medyan en yüksek yükseliş", "",
              "| TF | 15 dk | 1 sa | 4 sa | 24 sa |", "|---|---:|---:|---:|---:|"]
    for tf in agg:
        items = [r for r in rows if r["timeframe"] == tf]
        cells = []
        for h in HORIZONS_MIN:
            vals = [float(r["horizons"][h]) for r in items if (r.get("horizons") or {}).get(h) is not None]
            cells.append(f"{statistics.median(vals):.2f}% (n={len(vals)})" if vals else "—")
        lines.append(f"| {tf_label(tf)} | " + " | ".join(cells) + " |")
    lines += ["", "## Sembol bazında sinyal sayısı", ""]
    counts = Counter((r["symbol"], r["timeframe"]) for r in rows)
    per_symbol: dict = defaultdict(dict)
    for (sym, tf), n in counts.items():
        per_symbol[sym][tf] = n
    tfs = list(agg)
    lines.append("| Sembol | " + " | ".join(tf_label(t) for t in tfs) + " | Toplam |")
    lines.append("|---|" + "---:|" * (len(tfs) + 1))
    for sym in sorted(per_symbol):
        row = per_symbol[sym]
        lines.append(f"| {sym} | " + " | ".join(str(row.get(t, 0)) for t in tfs) + f" | {sum(row.values())} |")
    best = sorted(rows, key=lambda r: -float(r["mfe_pct"]))[:10]
    worst = sorted(rows, key=lambda r: float(r["mfe_pct"]))[:10]
    for title, subset in (("En yüksek 10 yükseliş", best), ("En zayıf 10 sinyal", worst)):
        lines += ["", f"## {title}", "", "| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |",
                  "|---|---|---|---|---:|---:|---:|---:|---|"]
        for r in subset:
            lines.append(f"| {r['symbol']} | {tf_label(r['timeframe'])} | {','.join(r['rules'])} | {_ms_to_text(int(r['signal_time_ms']))} | "
                         f"{float(r['signal_price']):.6g} | {float(r['mfe_pct']):.2f}% | {r['minutes_to_peak']} | {r['minutes_to_next']} | "
                         f"{'evet' if r['open_ended'] else 'hayır'} |")
    lines += ["", "## Dürüst sınırlar", "",
              "- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).",
              "- MFE \"en yüksek görülen fiyat\"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.",
              "- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.",
              "- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.",
              ""]
    return "\n".join(lines)
