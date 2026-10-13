"""KESİTSEL MOMENTUM ÇOK-REJİM — DOĞRULAMA KONTROLLERİ (2026-10-13).

NEDEN: research_cs_multi_regime.py "KARARLI | pozitif 4/4" dedi (spread net EV +2.044,
long_exc +1.736) AMA üç şüphe var:
  (1) RASTGELE KONTROL YOK — 90 günlük testte sonucu inandırıcı kılan şey "aynı gün
      rastgele sepet ≈0" idi. Bu koşuda o test eksik → +2.04 alfa mı, artefakt mı belirsiz.
  (2) ÖRTÜŞEN PENCERELER — j her 1 bar ilerlerken hold=6 ileri getiri 5/6 örtüşür →
      561 nokta BAĞIMSIZ değil; anlamlılık şişer. Bağımsız n için adım=hold şart.
  (3) SURVIVORSHIP — semboller BUGÜNÜN top-60 hacmi; 600 gün geriye bu listeyle bakmak
      "hayatta kalan kazananları" seçer → momentum sonucuna yanlılık.

Bu script aynı önbelleği (work/cs_fut_cache) kullanır, İNDİRME YAPMAZ:
  A. Rastgele sepet kontrolü (aynı gün, 2*topN rastgele) → gerçek − rastgele
  B. Bağımsız (örtüşmesiz) koşu: adım=hold → dürüst n ve t-istatistiği
  C. Sembol başlangıç dağılımı (survivorship görünümü)
  D. Blok-bootstrap (Newey-West benzeri) t-istatistiği

KULLANIM:
    python backend/scripts/research_cs_verify.py --tf 1d --months 20 --top-syms 60
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import random
import statistics
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_CACHE = os.path.join(_WORK, "cs_fut_cache")
_TAKER = 0.35


def _load_minimal(sym: str, tf: str) -> list[tuple[int, float]]:
    """Önbellekten TÜM mevcut ayları oku (indirme YOK)."""
    out = []
    if not os.path.isdir(_CACHE):
        return out
    prefix = f"{sym}-{tf}-"
    for fn in sorted(os.listdir(_CACHE)):
        if not fn.startswith(prefix) or not fn.endswith(".zip"):
            continue
        try:
            z = zipfile.ZipFile(os.path.join(_CACHE, fn))
            rows = list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))
        except Exception:
            continue
        for r in rows[1:]:
            if len(r) > 4:
                try:
                    out.append((int(r[0]), float(r[4])))
                except (ValueError, IndexError):
                    pass
    out.sort()
    return out


def _top_symbols(n: int) -> list[str]:
    """Bugünün top-N hacim sembolleri (script1 ile aynı; survivorship kaynağı)."""
    import ssl
    import urllib.request
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/24hr",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return []
    rows = [(d["symbol"], float(d.get("quoteVolume") or 0)) for d in data if d["symbol"].endswith("USDT")]
    rows.sort(key=lambda x: -x[1])
    return [s for s, v in rows[:n * 3] if v > 0][:n]


def _mom_table(series: dict):
    """Zaman-hizalı kapanış tablosu."""
    by_t: dict = {}
    for sym, s in series.items():
        for ot, c in s:
            by_t.setdefault(ot, {})[sym] = c
    times = sorted(by_t)
    idx = {sym: {ot: i for i, (ot, _) in enumerate(s)} for sym, s in series.items()}
    return by_t, times, idx


def _spreads(series, lookback, hold, topn, step=1, control=False, seed=7):
    """Kesitsel spread satırları. control=True → aynı gün rastgele 2*topN sepet."""
    by_t, times, idx = _mom_table(series)
    rnd = random.Random(seed)
    rows = []
    for j in range(lookback, len(times) - hold, step):
        t = times[j]; t0 = times[j - lookback]; t1 = times[j + hold]
        mom = {}
        for sym, s in series.items():
            im = idx[sym]
            if t in im and t0 in im and s[im[t0]][1] > 0:
                mom[sym] = (s[im[t]][1] / s[im[t0]][1] - 1) * 100
        if len(mom) < 2 * topn:
            continue
        rank = sorted(mom.items(), key=lambda kv: kv[1])
        if control:
            pool = [x for x, _ in rank]
            pick = rnd.sample(pool, 2 * topn)
            shorts, longs = pick[:topn], pick[topn:]
        else:
            shorts = [x for x, _ in rank[:topn]]; longs = [x for x, _ in rank[-topn:]]

        def fwd(sym):
            s = series[sym]; im = idx[sym]
            if t in im and t1 in im and s[im[t]][1] > 0:
                return (s[im[t1]][1] / s[im[t]][1] - 1) * 100
            return None
        lf = [x for x in (fwd(s) for s in longs) if x is not None]
        sf = [x for x in (fwd(s) for s in shorts) if x is not None]
        af = [x for x in (fwd(s) for s in mom) if x is not None]
        if lf and sf and af:
            ml, ms, ma = statistics.mean(lf), statistics.mean(sf), statistics.mean(af)
            rows.append({"t": t, "spread": ml - ms, "long_exc": ml - ma})
    return rows


def _tstat(xs):
    if len(xs) < 3:
        return 0.0
    sd = statistics.pstdev(xs) if len(xs) < 2 else statistics.stdev(xs)
    return statistics.mean(xs) / (sd / (len(xs) ** 0.5)) if sd > 0 else 0.0


def _block_tstat(xs, block):
    """Blok-bootstrap t: otokorelasyona dayanıklı. Adım=hold bağımsız için block=1 yeterli."""
    if len(xs) < 5:
        return 0.0
    rnd = random.Random(11)
    n = len(xs)
    boots = []
    for _ in range(1000):
        samp = []
        while len(samp) < n:
            i = rnd.randrange(n)
            samp.extend(xs[i:i + block] if i + block <= n else xs[i:])
        samp = samp[:n]
        boots.append(statistics.mean(samp))
    return statistics.mean(xs) / (statistics.pstdev(boots) or 1e-9)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--months", type=int, default=20)
    ap.add_argument("--top-syms", type=int, default=60)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--out", default="work/cs_verify.json")
    args = ap.parse_args()
    print(f"=== KESİTSEL DOĞRULAMA KONTROLLERİ ({args.tf}, top{args.topn}, lb{args.lookback}, hold{args.hold}) ===")
    syms = _top_symbols(args.top_syms)
    series = {}
    for s in syms:
        rows = _load_minimal(s, args.tf)
        if len(rows) >= args.lookback + args.hold + 10:
            series[s] = rows
    print(f"  sembol: {len(series)}")
    c2 = 2 * _TAKER
    res: dict = {"tf": args.tf, "topn": args.topn, "lookback": args.lookback, "hold": args.hold,
                 "symbols": len(series)}

    # --- A. RASTGELE KONTROL (örtüşen, 1=1) ---
    real = _spreads(series, args.lookback, args.hold, args.topn, step=1, control=False)
    ctrl = _spreads(series, args.lookback, args.hold, args.topn, step=1, control=True)
    real_net = [r["spread"] - c2 for r in real]
    ctrl_net = [r["spread"] - c2 for r in ctrl]
    ml = min(len(real_net), len(ctrl_net))
    diff = [real_net[i] - ctrl_net[i] for i in range(ml)]
    print("\n  == A. RASTGELE SEPET KONTROLÜ (eşleşmiş gün) ==")
    print(f"     gerçek   net EV {round(statistics.mean(real_net),3)} (n{len(real_net)})")
    print(f"     rastgele net EV {round(statistics.mean(ctrl_net),3)} (n{len(ctrl_net)})")
    print(f"     FARK (gerçek-rastgele) {round(statistics.mean(diff),3)}  t={round(_tstat(diff),2)}")
    res["real_net"] = round(statistics.mean(real_net), 3)
    res["ctrl_net"] = round(statistics.mean(ctrl_net), 3)
    res["diff_net"] = round(statistics.mean(diff), 3)
    res["diff_t"] = round(_tstat(diff), 2)

    # --- B. BAĞIMSIZ (ÖRTÜŞMESİZ) KOŞU: adım = hold ---
    ind = _spreads(series, args.lookback, args.hold, args.topn, step=args.hold, control=False)
    ind_net = [r["spread"] - c2 for r in ind]
    ind_lx = [r["long_exc"] - _TAKER for r in ind]
    print("\n  == B. BAĞIMSIZ KOŞU (adım=hold, dürüst n) ==")
    print(f"     spread net EV {round(statistics.mean(ind_net),3)} win {round(100*sum(1 for x in ind_net if x>0)/len(ind_net),1)} n {len(ind_net)}")
    print(f"     t (düz) {round(_tstat(ind_net),2)} | t (blok-boot) {round(_block_tstat(ind_net,args.hold),2)}")
    print(f"     long_exc net EV {round(statistics.mean(ind_lx),3)} win {round(100*sum(1 for x in ind_lx if x>0)/len(ind_lx),1)}")
    print(f"     long_exc t (düz) {round(_tstat(ind_lx),2)} | t (blok) {round(_block_tstat(ind_lx,args.hold),2)}")
    res["ind_spread_net"] = round(statistics.mean(ind_net), 3)
    res["ind_spread_t"] = round(_tstat(ind_net), 2)
    res["ind_spread_blockt"] = round(_block_tstat(ind_net, args.hold), 2)
    res["ind_lx_net"] = round(statistics.mean(ind_lx), 3)
    res["ind_lx_t"] = round(_tstat(ind_lx), 2)
    res["ind_lx_blockt"] = round(_block_tstat(ind_lx, args.hold), 2)
    res["ind_n"] = len(ind_net)

    # bağımsız 4-fold
    print("     -- bağımsız 4-fold spread --")
    nfold = 4
    folds = []
    for k in range(nfold):
        seg = ind_net[int(len(ind_net)*k/nfold):int(len(ind_net)*(k+1)/nfold)]
        if seg:
            folds.append(round(statistics.mean(seg), 3))
    print(f"     foldlar: {folds} | pozitif {sum(1 for f in folds if f>0)}/{len(folds)}")
    res["ind_folds"] = folds

    # --- C. SURVIVORSHIP: sembol başlangıç dağılımı ---
    starts = {}
    for sym, s in series.items():
        if s:
            starts[sym] = dt.datetime.utcfromtimestamp(s[0][0] / 1000).strftime("%Y-%m-%d")
    from collections import Counter
    cnt = Counter(starts.values())
    early = sum(1 for v in starts.values() if v <= "2025-04-15")
    print("\n  == C. SURVIVORSHIP GÖRÜNÜMÜ ==")
    print(f"     ilk veri ≤2025-04-15 olan sembol: {early}/{len(starts)}")
    print(f"     en eski: {min(starts.values())} | en yeni: {max(starts.values())}")
    print(f"     başlangıç ayı dağılımı: {dict(sorted(cnt.items()))}")
    res["survivor_early"] = f"{early}/{len(starts)}"
    res["survivor_earliest"] = min(starts.values())
    res["survivor_latest"] = max(starts.values())

    verdict = ("GERÇEK ALFA" if res["diff_t"] > 2 and statistics.mean(ind_net) > c2
               else "ARTEFAKT/ŞÜPHELİ" if res["diff_t"] < 1
               else "BELİRSİZ")
    print(f"\n  KARAR (kontrol sonrası): {verdict}")
    res["verdict"] = verdict

    with open(os.path.join(_WORK, os.path.basename(args.out)), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
