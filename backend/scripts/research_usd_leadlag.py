"""USD LEAD-LAG SİNYAL ARAŞTIRMASI (2026-10-12).

KULLANICI ÖNERİSİ: "Binance Global'deki aynı sembolün USD varyasyonunu kullanalım;
TRY ile USD grafikleri aynı şekilde hareket ediyor." Fikir: sinyali DERİN/likit USD
piyasasından üret, işlemi TRY çiftiyle yap. TRY verisi ince; USD derin ve 730 gün geçmişli.

BU SCRIPT üç soruyu sırayla test eder:
  1. TR ve USD gerçekten birlikte mi hareket ediyor? (getiri korelasyonu)
  2. USD, TRY'nin GELECEĞİNİ öngörüyor mu? AMA "eşzamanlı hareket" ile "gerçek öncülük"
     ayrılmalı: GL[i]'yi AYNI-bar TRY[i] hareketine regres edip RESIDUAL'ini kullanırız.
     Residual → TRY[i+1..] korelasyonu > 0 ise GERÇEK lead-lag var.
  3. Bu öncülük MALİYET SONRASI kâra dönüyor mu? taker / maker(naif) / maker+GERÇEK limit
     dolgu senaryoları + gün-gün stabilite + sembol yoğunlaşma.

LOOK-AHEAD KORUMASI: feature'lar yalnız KAPANMIŞ barlardan (bar open_time'dan itibaren
kapanış = [i]); beta SADECE eğitim kümesinde fit edilir; eşik eğitimden.

KULLANIM:
    python backend/scripts/research_usd_leadlag.py            # channel_cache ile
    python backend/scripts/research_usd_leadlag.py --refresh  # TR+Global yeniden çek
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORK = os.path.join(_HERE, "..", "work")
_CACHE = os.path.join(_WORK, "channel_cache.json")


def _load_cache() -> dict:
    """channel_cache.json (research_data_channels üretir): {tr:{}, gl:{}, global_map:{}}."""
    if not os.path.exists(_CACHE):
        raise SystemExit("channel_cache.json yok — önce: research_data_channels.py --fetch")
    with open(_CACHE, encoding="utf-8") as f:
        return json.load(f)


def _corr(a, b):
    if len(a) < 3:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
    sd = statistics.pstdev(a) * statistics.pstdev(b)
    return cov / sd if sd else 0.0


def build_records(cache: dict) -> list[dict]:
    """Her (sembol, bar) için: GL getirisi, aynı-bar TRY getirisi, ileri TRY getirileri."""
    trb = cache["tr"]; glb = cache["gl"]
    rows = []
    for s, tr in trb.items():
        gl = glb.get(s)
        if not tr or not gl:
            continue
        n = min(len(tr["c"]), len(gl["c"]))
        tc = tr["c"]; gc = gl["c"]
        for i in range(30, n - 13):
            if tc[i] <= 0 or tc[i - 1] <= 0 or gc[i] <= 0 or gc[i - 1] <= 0:
                continue
            g1 = (gc[i] / gc[i - 1] - 1) * 100
            t_same = (tc[i] / tc[i - 1] - 1) * 100
            fwd = {}
            for h in (1, 3, 6, 12):
                if i + h < n and tc[i] > 0:
                    fwd[h] = (tc[i + h] / tc[i] - 1) * 100
            rows.append({"s": s, "ts": tr["t"][i], "g1": g1, "t_same": t_same,
                         "c": tc[i], "fwd": fwd,
                         "lo1": tr["l"][i + 1] if i + 1 < n else None,
                         "lo3": min(tr["l"][i + 1:i + 4]) if i + 3 < n else None})
    rows.sort(key=lambda r: r["ts"])
    return rows


def _beta(rows) -> tuple[float, float, float]:
    mg = statistics.mean([r["g1"] for r in rows])
    mt = statistics.mean([r["t_same"] for r in rows])
    cov = sum((r["g1"] - mg) * (r["t_same"] - mt) for r in rows) / len(rows)
    var = statistics.pvariance([r["t_same"] for r in rows])
    return (cov / var if var else 0.0), mg, mt


def _net(gross: float, comm: float, slip: float) -> float:
    return gross - (2 * comm + 2 * slip) * 100


def analyze(rows: list[dict], comm_taker=0.0015, comm_maker=0.0002) -> dict:
    n = len(rows); split = int(n * 0.6)
    tr_rows, te_rows = rows[:split], rows[split:]
    b, mg, mt = _beta(tr_rows)
    for rs in (tr_rows, te_rows):
        for r in rs:
            r["res"] = r["g1"] - b * (r["t_same"] - mt)

    # (2) gerçek öncülük: residual korelasyonu (look-ahead'siz)
    res_te = [r["res"] for r in te_rows]
    out = {"beta": round(b, 3),
           "contemporaneous_corr": round(_corr([r["g1"] for r in rows], [r["t_same"] for r in rows]), 3),
           "residual_to_fwd": {h: round(_corr(res_te, [r["fwd"][h] for r in te_rows if h in r["fwd"]]), 3)
                               for h in (1, 3, 6, 12)},
           "scenarios": {}}

    # (3) maliyet senaryoları, her eşik için
    for q in (0.9, 0.85, 0.8):
        thr = sorted(r["res"] for r in tr_rows)[int(len(tr_rows) * q)]
        sig = [r for r in te_rows if r["res"] >= thr and 3 in r["fwd"]]
        # aynı sembol + 30dk kovada tek sinyal (üst üste binmeyi azalt)
        seen = set(); uniq = []
        for r in sig:
            k = (r["s"], int(r["ts"] // 1800))
            if k in seen:
                continue
            seen.add(k); uniq.append(r)
        if not uniq:
            continue
        key = f"p{int(q*100)}"
        base_win = sum(1 for r in uniq if r["fwd"][3] > 0)
        taker = [_net(r["fwd"][3], comm_taker, 0.00025) for r in uniq]
        maker = [_net(r["fwd"][3], comm_maker, 0.0) for r in uniq]
        # maker + GERÇEK limit dolgu: limit = sinyal fiyatının %0.3 altı; sonraki 3 barda dolarsa gir
        filled = [r for r in uniq if r["lo1"] is not None and r["lo3"] is not None
                  and min(r["lo1"], r["lo3"]) <= r["c"] * 0.997]
        limit_net = [_net(r["fwd"][3], comm_maker, 0.0) for r in filled]
        out["scenarios"][key] = {
            "n": len(uniq),
            "gross_fwd3": round(statistics.mean([r["fwd"][3] for r in uniq]), 4),
            "net_taker": round(statistics.mean(taker), 3),
            "net_maker": round(statistics.mean(maker), 3),
            "maker_win": round(100 * sum(1 for x in maker if x > 0) / len(maker), 1),
            "limit_filled": len(filled), "limit_nofill": len(uniq) - len(filled),
            "net_maker_limit": round(statistics.mean(limit_net), 3) if limit_net else None,
        }

    # gün-gün stabilite (p85)
    thr = sorted(r["res"] for r in tr_rows)[int(len(tr_rows) * 0.85)]
    byday = {}
    for r in te_rows:
        if r["res"] >= thr and 3 in r["fwd"]:
            d = int(r["ts"] // 86400)
            byday.setdefault(d, []).append(_net(r["fwd"][3], comm_taker, 0.00025))
    out["daily_taker"] = {d: round(statistics.mean(v), 3) for d, v in sorted(byday.items())}
    out["daily_positive"] = f"{sum(1 for v in byday.values() if statistics.mean(v) > 0)}/{len(byday)}"

    # sembol yoğunlaşma (p85)
    from collections import Counter
    cc = Counter(r["s"] for r in te_rows if r["res"] >= thr)
    tot = sum(cc.values()) or 1
    out["concentration"] = {"symbols": len(cc),
                            "top_share_pct": round(100 * cc.most_common(1)[0][1] / tot, 1) if cc else None}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/usd_leadlag_research.json")
    args = ap.parse_args()
    print("=== USD LEAD-LAG SİNYAL ARAŞTIRMASI ===")
    cache = _load_cache()
    rows = build_records(cache)
    print(f"  kayıt: {len(rows)} (sembol {len({r['s'] for r in rows})})")
    if len(rows) < 1000:
        print("YETERSİZ VERİ"); return 1
    res = analyze(rows)
    print(f"  aynı-bar korelasyon (GL, TRY): {res['contemporaneous_corr']}")
    print(f"  beta: {res['beta']}")
    print(f"  RESIDUAL→fwd korelasyon (gerçek öncülük): {res['residual_to_fwd']}")
    print(f"\n  {'eşik':5s}{'n':>7}{'brüt':>8}{'taker':>9}{'maker':>9}{'makerLimit':>12}{'win(maker)':>11}")
    for k, v in res["scenarios"].items():
        print(f"  {k:5s}{v['n']:>7}{v['gross_fwd3']:>8}{v['net_taker']:>9}{v['net_maker']:>9}"
              f"{str(v['net_maker_limit']):>12}{v['maker_win']:>11}")
    print(f"\n  gün-gün (taker, p85): {res['daily_taker']} → pozitif {res['daily_positive']}")
    print(f"  yoğunlaşma: {res['concentration']}")
    # verdict
    lim = res["scenarios"].get("p85", {}).get("net_maker_limit")
    verdict = ("USD_LEADLAG_REAL_BUT_COST_BOUND" if (res["residual_to_fwd"].get(3, 0) > 0.05)
               else "NO_LEADLAG")
    res["verdict"] = verdict
    print(f"\n  KARAR: {verdict}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
