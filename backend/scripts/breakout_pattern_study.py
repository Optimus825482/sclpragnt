"""Çıkış deseni çalışması — VERİ-ÖNCE yaklaşım (2026-10-17, çevrimdışı).

Kullanıcı önerisi: el yapımı kural yerine, "LUNA tipi" yükselişleri nesnel tanımla bul → o ana (t0) kadarki
göstergeleri 5 dk / 3 dk / 1 dk için çıkar → rastgele anlarla kıyasla → ayırt eden desenleri çıkar → önceki
günlerde (örneklem dışı) arka testle sına. Canlı koda bağlanmaz, DB'ye yazmaz.

Aşamalar (`--stages`, virgüllü):
  data      DB → önbellek (5m tüm semboller; 1m likit semboller; LUNATRY 1m yaması work/lunatry_1m_1017.json)
  grid      her sembol için 5m ızgara üzerinde TÜM özellikler (5m | 3m | 1m) → önbellek (.npy, float32)
  events    olay madenciliği (tüm dönem; eğitim penceresi = --train-start sonrası) → work/pattern/events.csv
  snap      olay (t0, t0+15dk) ve taban (eşleşmiş + havuz) anlık görüntüleri → work/pattern/snap_*.csv
  analyze   özellik sıralaması (AUC, SMD, küme sıkılığı, FWER), aday desenler → work/pattern/analysis.json
  backtest  adayları önceki günlerde (OOS) ve eğitim penceresinde (in-sample) sına → work/pattern/backtest.json
  tables    rapor tabloları (markdown) → work/pattern/report_tables.md

Kullanım (backend/):
  DATABASE_URL=... python scripts/breakout_pattern_study.py --jsonl work/rescan_21g_nogate.jsonl \
      --cache-dir <önbellek> --stages data,grid,events,snap,analyze,backtest,tables
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import pattern_study as P  # noqa: E402
from scripts.notification_outcomes_report import TZ  # noqa: E402

MIN_QUOTE = 5_000_000.0
TF_ORDER = ("5m", "3m", "1m")
WARM_BARS = 300          # 5m: EMA99 ısınması + 24 sa (288) pencere
OFFSETS = (0, 3)         # olay anlık görüntüsü: t0 ve t0 + 3 mum (15 dk)
DAY_MS = 86_400_000


def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + DAY_MS - 1 if end else ms


def fmt_t(ms: int | float, fmt: str = "%d/%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime(fmt)


def day_key(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d")


# ------------------------------------------------------------------------------------------------ 1. veri
_SQL_5M = ("SELECT symbol, open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
           "COALESCE(quote_volume, 0)::float8 FROM historical_candles WHERE timeframe='5m' ORDER BY symbol, open_time")
_SQL_1M = ("SELECT open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
           "COALESCE(quote_volume, 0)::float8 FROM historical_candles WHERE timeframe='1m' AND symbol=%s ORDER BY open_time")


def stage_data(args) -> None:
    import psycopg
    cache = Path(args.cache_dir); cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    acc: dict[str, list] = collections.defaultdict(list)
    with psycopg.connect(url, connect_timeout=10) as conn:
        for r in conn.execute(_SQL_5M).fetchall():
            acc[r[0]].append(r[1:])
        d5 = {s: np.array(v, dtype=float) for s, v in acc.items() if len(v) >= 300}
        print(f"[data] 5m: {len(d5)} sembol ({time.time() - t0:.0f} sn)")
        # likit: 24 sa quote ≥ MIN_QUOTE olan bar payı ≥ %10 (ham satır penceresiyle, kaba)
        liquid = []
        for s, a in d5.items():
            q = P.rolling_sum(np.nan_to_num(a[:, 6], nan=0.0), 288)
            ok = q[300:] >= MIN_QUOTE
            if len(ok) and float(ok.mean()) >= 0.10:
                liquid.append(s)
        print(f"[data] likit sembol: {len(liquid)}")
        d1 = {}
        for k, s in enumerate(liquid):
            rows = conn.execute(_SQL_1M, (s,)).fetchall()
            if len(rows) >= 1600:
                d1[s] = np.array(rows, dtype=float)
            if (k + 1) % 50 == 0:
                print(f"[data] 1m {k + 1}/{len(liquid)} ({time.time() - t0:.0f} sn)")
    # LUNATRY 1m yaması (DB 16 Ekim ~20:00'de bitiyor; 17 Ekim 01:05 olayı için Binance public kline önbelleği)
    lp = Path(args.lunatry_cache)
    if lp.exists() and "LUNATRY" in d1:
        data = json.loads(lp.read_text(encoding="utf-8"))
        extra = np.array([[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7])] for k in data])
        last = d1["LUNATRY"][-1, 0]
        extra = extra[extra[:, 0] > last]
        if len(extra):
            d1["LUNATRY"] = np.vstack([d1["LUNATRY"], extra])
            print(f"[data] LUNATRY 1m yaması: +{len(extra)} mum (-> {fmt_t(extra[-1, 0])})")
    np.savez(cache / "d5.npz", **d5)
    np.savez(cache / "d1.npz", **d1)
    print(f"[data] bitti ({time.time() - t0:.0f} sn)")


def load_cached(cache_dir: str, name: str) -> dict[str, np.ndarray]:
    z = np.load(Path(cache_dir) / f"{name}.npz")
    return {k: z[k] for k in z.files}


# ------------------------------------------------------------------------------------------------ 2. ızgara
def _grid_one(job):
    sym, a5, a1, out_dir = job
    f5 = P.fill_gaps(a5, P.BAR_5M_MS)
    names5, X5 = P.features_matrix(f5, "5m")
    parts = [X5]; names = list(names5)
    ot5 = f5[:, P.COL_OT].astype(np.int64)
    t_dec = ot5 + P.BAR_5M_MS      # 5m bar i kapanış anı = karar anı
    n = len(f5)
    if a1 is not None:
        f1 = P.fill_gaps(a1, P.BAR_1M_MS)
        f3 = P.aggregate_bars(f1, 3)
        for tf, arr in (("3m", f3), ("1m", f1)):
            nm, X = P.features_matrix(arr, tf)
            idx = P.snapshot_index(arr[:, P.COL_OT].astype(np.int64), P.TF_BAR_MS[tf], t_dec)
            G = np.where((idx >= 0)[:, None], X[np.clip(idx, 0, len(X) - 1)], np.nan)
            parts.append(G); names += nm
    else:
        for tf in ("3m", "1m"):
            nm, _ = P.features_matrix(f5[:400], "5m")   # yalnız ad listesi için
            names += [f"{tf}.{x.split('.', 1)[1]}" for x in nm if not x.endswith(".hour")]
            parts.append(np.full((n, len(nm) - 1), np.nan))
    M = np.concatenate(parts, axis=1).astype(np.float32)
    np.save(Path(out_dir) / f"G_{sym}.npy", M)
    np.save(Path(out_dir) / f"OT_{sym}.npy", ot5)
    np.save(Path(out_dir) / f"F5_{sym}.npy", f5)
    return sym, names


def stage_grid(args) -> None:
    from multiprocessing import Pool
    cache = Path(args.cache_dir); gdir = cache / "grid"; gdir.mkdir(parents=True, exist_ok=True)
    d5 = load_cached(args.cache_dir, "d5"); d1 = load_cached(args.cache_dir, "d1")
    t0 = time.time()
    jobs = [(s, a, d1.get(s), str(gdir)) for s, a in d5.items()]
    names_ref = None
    with Pool(max(1, args.workers)) as pool:
        for k, (sym, names) in enumerate(pool.imap_unordered(_grid_one, jobs, chunksize=2)):
            if sym in d1 and names_ref is None:
                names_ref = names
            if (k + 1) % 50 == 0:
                print(f"[grid] {k + 1}/{len(jobs)} ({time.time() - t0:.0f} sn)")
    (cache / "grid_names.json").write_text(json.dumps(names_ref), encoding="utf-8")
    print(f"[grid] bitti: {len(names_ref)} özellik ({time.time() - t0:.0f} sn)")


def load_grid_sym(cache_dir: str, sym: str):
    g = Path(cache_dir) / "grid"
    return (np.load(g / f"G_{sym}.npy"), np.load(g / f"OT_{sym}.npy"), np.load(g / f"F5_{sym}.npy"))


# ------------------------------------------------------------------------------------------------ 3. olaylar
def ev_params(args) -> P.EventParams:
    return P.EventParams(win_bars=12, min_gain=args.ev_gain, green_min=args.ev_green, max_dd=args.ev_dd,
                         max_candle=args.ev_candle, min_q24=MIN_QUOTE, dedupe_hours=3.0)


def stage_events(args) -> None:
    cache = Path(args.cache_dir); out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    syms = sorted(p.name[3:-4] for p in (cache / "grid").glob("OT_*.npy"))
    ep = ev_params(args)
    events: list[dict] = []; masks = {}
    t0 = time.time()
    for s in syms:
        f5 = np.load(cache / "grid" / f"F5_{s}.npy")
        mask, det = P.event_mask(f5, ep, warm_bars=WARM_BARS)
        masks[s] = (np.flatnonzero(mask).astype(np.int32), det["e_star"][mask].astype(np.int16))
        events += P.find_events(s, f5, ep, warm_bars=WARM_BARS)
    events.sort(key=lambda e: (e["t0"], e["sym"]))
    train_ms = parse_day(args.train_start)
    for e in events:
        e["period"] = "train" if e["t0"] >= train_ms else "oos"
    import pickle
    pickle.dump({"events": events, "masks": masks, "params": ep.__dict__}, open(cache / "events.pkl", "wb"))
    import csv
    with open(out / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["period", "symbol", "t0_local", "t0_ms", "gain_pct", "dur_min", "green_share", "max_dd_pct", "max_candle_pct"])
        for e in events:
            w.writerow([e["period"], e["sym"], fmt_t(e["t0"], "%Y-%m-%d %H:%M"), e["t0"], f"{e['gain']:.2f}", e["dur_min"],
                        f"{e['green']:.2f}", f"{e['dd']:.2f}", f"{e['maxc']:.2f}"])
    tr = [e for e in events if e["period"] == "train"]
    print(f"[events] toplam {len(events)}; eğitim penceresi {len(tr)}; OOS {len(events) - len(tr)} ({time.time() - t0:.0f} sn)")
    byday = collections.Counter(day_key(e["t0"]) for e in events)
    print("[events] günlük:", sorted(byday.items()))


def load_events(cache_dir: str) -> dict:
    import pickle
    return pickle.load(open(Path(cache_dir) / "events.pkl", "rb"))


# ------------------------------------------------------------------------------------------------ 4. anlık görüntüler
def build_sets(args):
    """Olay (offset 0/+3 mum) ve taban (eşleşmiş B1, havuz B2) satırları. Dönüş: names, dict set -> (X, meta)."""
    cache = args.cache_dir
    names = json.loads((Path(cache) / "grid_names.json").read_text(encoding="utf-8"))
    E = load_events(cache)
    train_ms = parse_day(args.train_start)
    ev = [e for e in E["events"] if e["period"] == "train"]
    syms = sorted({e["sym"] for e in E["events"]} | set(E["masks"]))
    rng = np.random.default_rng(args.seed)
    qcol = names.index("5m.qv24_log10")
    thr = np.log10(MIN_QUOTE)
    # 1m verisi son anı (karar anı sınırı)
    d1_end = {}
    G_cache: dict[str, tuple] = {}

    def G(sym):
        if sym not in G_cache:
            G_cache[sym] = load_grid_sym(cache, sym)[:2]
        return G_cache[sym]

    # kapsanan (olay koşusu içindeki) karar indeksleri
    def covered(sym, n):
        cov = np.zeros(n, dtype=bool)
        idx, es = E["masks"][sym]
        for s, e in zip(idx, es):
            cov[max(s - 1, 0): min(n, s + int(e) + 1)] = True
        return cov

    rows = {k: [] for k in ("ev0", "ev15", "b_matched", "b_pooled")}
    meta = {k: [] for k in rows}
    pool_valid = 0
    t_hi = None
    # 1m son kapanış: yamalı LUNATRY dışındaki sembollerin ortak 1m sonu
    d1 = load_cached(cache, "d1")
    ends = sorted(int(a[-1, 0]) for s, a in d1.items() if s != "LUNATRY")
    t_hi = ends[len(ends) // 2] + 60_000 - 3 * 60_000     # medyan 1m sonu − 3 dk (bayat sınırı)
    print(f"[snap] taban karar anı üst sınırı (1m var): {fmt_t(t_hi)}")
    valid_by_sym: dict[str, np.ndarray] = {}
    for s in syms:
        M, ot = G(s)
        n = len(ot)
        t_dec = ot + P.BAR_5M_MS
        v = (np.arange(n) >= WARM_BARS) & (M[:, qcol] >= thr) & (t_dec >= train_ms) & (t_dec <= t_hi)
        v &= ~covered(s, n)
        v &= np.isfinite(M[:, names.index("5m.rsi14")]) & np.isfinite(M[:, names.index("1m.rsi14")])
        valid_by_sym[s] = np.flatnonzero(v)
        pool_valid += int(v.sum())
    ev_syms = sorted({e["sym"] for e in ev})
    # olaylar
    for e in ev:
        M, ot = G(e["sym"])
        i0 = e["s"] - 1
        for off, key in ((0, "ev0"), (3, "ev15")):
            i = i0 + off
            if i < len(ot):
                rows[key].append(M[i]); meta[key].append({"sym": e["sym"], "t": int(ot[i] + P.BAR_5M_MS), "t0": e["t0"], "gain": e["gain"],
                                                          "dur": e["dur_min"], "day": day_key(e["t0"])})
    # B1: aynı sembol + aynı gün, olay başına baseline_mult
    for e in ev:
        M, ot = G(e["sym"])
        vi = valid_by_sym[e["sym"]]
        if len(vi) == 0:
            continue
        td = ot[vi] + P.BAR_5M_MS
        same_day = vi[np.array([day_key(t) == day_key(e["t0"]) for t in td])] if len(vi) else vi
        pick_from = same_day if len(same_day) >= 10 else vi
        k = min(args.baseline_mult, len(pick_from))
        for i in rng.choice(pick_from, size=k, replace=False):
            rows["b_matched"].append(M[i]); meta["b_matched"].append({"sym": e["sym"], "t": int(ot[i] + P.BAR_5M_MS), "ev_t0": e["t0"],
                                                                      "day": day_key(ot[i] + P.BAR_5M_MS)})
    # B2: havuz — tüm likit semboller, eğitim penceresi, tekdüze
    all_pairs = np.concatenate([np.column_stack([np.full(len(v), k), v]) for k, (s, v) in enumerate(valid_by_sym.items()) if len(v)])
    sym_list = list(valid_by_sym)
    sel = rng.choice(len(all_pairs), size=min(len(all_pairs), args.baseline_mult * len(ev)), replace=False)
    for j in sel:
        k, i = int(all_pairs[j, 0]), int(all_pairs[j, 1])
        s = sym_list[k]
        M, ot = G(s)
        rows["b_pooled"].append(M[i]); meta["b_pooled"].append({"sym": s, "t": int(ot[i] + P.BAR_5M_MS), "day": day_key(ot[i] + P.BAR_5M_MS)})
    X = {k: (np.array(v, dtype=np.float64) if v else np.zeros((0, len(names)))) for k, v in rows.items()}
    return names, X, meta, {"pool_valid": pool_valid, "n_events": len(ev), "ev_syms": len(ev_syms)}


def stage_snap(args) -> None:
    import csv
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    names, X, meta, info = build_sets(args)
    import pickle
    pickle.dump({"names": names, "X": X, "meta": meta, "info": info}, open(Path(args.cache_dir) / "snap.pkl", "wb"))
    for key, M in X.items():
        for tf in TF_ORDER:
            cols = [i for i, nm in enumerate(names) if nm.startswith(tf + ".")]
            with open(out / f"snap_{key}_{tf}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["symbol", "decision_time", "t0" if key.startswith("ev") else "-", "gain_pct" if key.startswith("ev") else "-"]
                           + [names[i] for i in cols])
                for r, m in zip(M, meta[key]):
                    w.writerow([m["sym"], fmt_t(m["t"], "%Y-%m-%d %H:%M"), fmt_t(m["t0"], "%Y-%m-%d %H:%M") if "t0" in m else "",
                                f"{m['gain']:.2f}" if "gain" in m else ""] + [("" if not np.isfinite(r[i]) else f"{r[i]:.6g}") for i in cols])
    print(f"[snap] olay {len(X['ev0'])}; B1 {len(X['b_matched'])}; B2 {len(X['b_pooled'])}; havuz geçerli an {info['pool_valid']} "
          f"({time.time() - t0:.0f} sn)")


# ------------------------------------------------------------------------------------------------ 5. analiz
def _rows(X: dict, meta: dict, ev_key: str, base_key: str):
    """Olay + taban satırları, etiket, sembol tabakası, olay-grubu (CV için)."""
    E, B = X[ev_key], X[base_key]
    ym = meta[ev_key]; bm = meta[base_key]
    Xall = np.vstack([E, B]); y = np.r_[np.ones(len(E)), np.zeros(len(B))]
    syms = np.array([m["sym"] for m in ym] + [m["sym"] for m in bm])
    ev_id = {(m["sym"], m["t0"]): k for k, m in enumerate(ym)}
    grp = np.array(list(range(len(ym))) + [ev_id.get((m["sym"], m.get("ev_t0")), -1) for m in bm])
    return Xall, y, syms, grp


def rank_features(Xall, y, syms, names, *, n_perm: int, seed: int, stratified: bool):
    ok = np.isfinite(Xall).all(axis=1)
    X, yy, ss = Xall[ok], y[ok], syms[ok]
    auc = P.auc_matrix(X, yy); d = P.smd(X, yy)
    ev, ba = X[yy == 1], X[yy == 0]
    q = lambda M, p: np.quantile(M, p, axis=0)
    ev_iqr, ba_iqr = P.iqr(ev), P.iqr(ba)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(ba_iqr > 0, ev_iqr / ba_iqr, np.nan)
    thr, _ = P.fwer_threshold(X, yy, ss if stratified else np.zeros(len(yy), dtype=int), n_perm=n_perm, seed=seed)
    recs = []
    for j, nm in enumerate(names):
        recs.append({"feature": nm, "tf": nm.split(".", 1)[0], "auc": float(auc[j]), "d": float(d[j]),
                     "ev_med": float(q(ev, .5)[j]), "ev_q25": float(q(ev, .25)[j]), "ev_q75": float(q(ev, .75)[j]),
                     "b_med": float(q(ba, .5)[j]), "b_q25": float(q(ba, .25)[j]), "b_q75": float(q(ba, .75)[j]),
                     "iqr_ratio": float(ratio[j]), "sig": bool(abs(auc[j] - 0.5) > thr)})
    recs.sort(key=lambda r: -abs(r["auc"] - 0.5))
    return recs, {"n_events": int(yy.sum()), "n_base": int((yy == 0).sum()), "fwer_thr": thr, "n_features": len(names)}


def _hand_pattern(Xall, y, names, ranking, *, k_feat=3, keep=0.80, tight=0.6, corr_max=0.85):
    """Elle seçim: sıralamanın en üstünden, aile (ölçü adı) tekrarı ve yüksek korelasyonlu olmayan özellikler;
    eşik olay dağılımının `keep` oranını koruyacak kuantilde (tek taraflı) ya da küme sıkıysa [q10, q90] bandı."""
    ok = np.isfinite(Xall).all(axis=1)
    X, yy = Xall[ok], y[ok]
    ev = X[yy == 1]
    idx = {nm: i for i, nm in enumerate(names)}
    chosen: list[str] = []; fams = set(); conds: list[P.Condition] = []
    for r in ranking:
        nm = r["feature"]; fam = nm.split(".", 1)[1]
        if fam in fams or nm.endswith(".hour"):
            continue
        j = idx[nm]
        if any(abs(np.corrcoef(X[:, j], X[:, idx[c]])[0, 1]) > corr_max for c in chosen):
            continue
        chosen.append(nm); fams.add(fam)
        up = r["auc"] > 0.5
        if r["iqr_ratio"] <= tight:
            lo, hi = np.quantile(ev[:, j], [0.10, 0.90])
            conds += [P.Condition(nm, ">", float(lo)), P.Condition(nm, "<=", float(hi))]
        elif up:
            conds.append(P.Condition(nm, ">", float(np.quantile(ev[:, j], 1 - keep))))
        else:
            conds.append(P.Condition(nm, "<=", float(np.quantile(ev[:, j], keep))))
        if len(chosen) >= k_feat:
            break
    return conds


def _pattern_rates(conds, Xall, y, names):
    ok_cols = [names.index(c.feature) for c in conds]
    ok = np.isfinite(Xall[:, ok_cols]).all(axis=1)
    cols = {c.feature: Xall[:, names.index(c.feature)] for c in conds}
    m = P.eval_conditions(cols, conds) & ok
    ev, ba = (y == 1) & ok, (y == 0)
    return {"recall": float(m[y == 1].mean()), "fpr": float(m[y == 0].mean()), "n_ev_used": int(ev.sum()),
            "recall_complete": float(m[ev].mean()) if ev.any() else None}


def cv_pattern(maker, Xall, y, grp, names, *, folds=5, seed=0):
    """Çapraz doğrulama (olay-grubu bazlı): seçim + eşik her katlamada eğitim parçasından yeniden yapılır."""
    rng = np.random.default_rng(seed)
    ev_ids = np.unique(grp[grp >= 0]); fold_of = dict(zip(ev_ids, rng.integers(0, folds, size=len(ev_ids))))
    f = np.array([fold_of.get(g, -1) for g in grp])
    orphan = f < 0          # grubu olmayan (havuz) taban satırları: rastgele katlama
    f[orphan] = rng.integers(0, folds, size=int(orphan.sum()))
    rec, fpr, nn = [], [], 0
    for k in range(folds):
        te = f == k; tr = ~te
        if (te & (y == 1)).sum() < 3:
            continue
        conds = maker(Xall[tr], y[tr])
        if not conds:
            continue
        r = _pattern_rates(conds, Xall[te], y[te], names)
        rec.append(r["recall"]); fpr.append(r["fpr"]); nn += 1
    return {"folds": nn, "recall": float(np.mean(rec)) if rec else None, "fpr": float(np.mean(fpr)) if fpr else None}


def stage_analyze(args) -> None:
    import pickle
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    S = pickle.load(open(Path(args.cache_dir) / "snap.pkl", "rb"))
    names, X, meta, info = S["names"], S["X"], S["meta"], S["info"]
    res = {"info": info, "rank": {}, "meta": {}, "patterns": []}
    t0 = time.time()
    ranks = {}
    for ev_key in ("ev0", "ev15"):
        for b_key in ("b_matched", "b_pooled"):
            Xall, y, syms, grp = _rows(X, meta, ev_key, b_key)
            recs, mt = rank_features(Xall, y, syms, names, n_perm=args.n_perm, seed=args.seed, stratified=(b_key == "b_matched"))
            ranks[(ev_key, b_key)] = recs
            res["rank"][f"{ev_key}|{b_key}"] = recs; res["meta"][f"{ev_key}|{b_key}"] = mt
            print(f"[analyze] {ev_key} vs {b_key}: olay {mt['n_events']}, taban {mt['n_base']}, FWER eşiği |AUC-.5|>{mt['fwer_thr']:.3f} "
                  f"({time.time() - t0:.0f} sn)")
    # rank dayanıklılığı: matched vs pooled sıra korelasyonu
    from scipy.stats import spearmanr
    for ev_key in ("ev0", "ev15"):
        a = {r["feature"]: r["auc"] for r in ranks[(ev_key, "b_matched")]}
        b = {r["feature"]: r["auc"] for r in ranks[(ev_key, "b_pooled")]}
        common = sorted(set(a) & set(b))
        res["meta"][f"{ev_key}|spearman_auc"] = float(spearmanr([a[c] for c in common], [b[c] for c in common])[0])

    # ---- aday desenler (birincil: eşleşmiş taban)
    K = args.top_k
    def make_tree(depth, ev_key):
        Xall, y, syms, grp = _rows(X, meta, ev_key, "b_matched")

        def maker(Xtr, ytr):
            ok = np.isfinite(Xtr).all(axis=1); Xo, yo = Xtr[ok], ytr[ok]
            auc = P.auc_matrix(Xo, yo)
            top = np.argsort(-np.abs(auc - 0.5))[:K]
            tp = P.fit_pattern_tree(Xo[:, top], yo, [names[j] for j in top], depth=depth,
                                    min_leaf_events=max(8, int(0.06 * yo.sum())), seed=args.seed)
            return tp.conditions if tp else []
        return maker, Xall, y, grp

    def make_tree_precise(depth, ev_key, cap):
        Xall, y, syms, grp = _rows(X, meta, ev_key, "b_pooled")

        def maker(Xtr, ytr):
            ok = np.isfinite(Xtr).all(axis=1); Xo, yo = Xtr[ok], ytr[ok]
            auc = P.auc_matrix(Xo, yo)
            top = np.argsort(-np.abs(auc - 0.5))[:K]
            tp = P.fit_pattern_tree(Xo[:, top], yo, [names[j] for j in top], depth=depth, min_recall=0.03,
                                    min_leaf_events=max(6, int(0.03 * yo.sum())), seed=args.seed, max_fpr=cap, pos_share=0.05)
            return tp.conditions if tp else []
        return maker, Xall, y, grp

    def make_hand(ev_key):
        Xall, y, syms, grp = _rows(X, meta, ev_key, "b_matched")

        def maker(Xtr, ytr):
            ok = np.isfinite(Xtr).all(axis=1); Xo, yo = Xtr[ok], ytr[ok]
            auc = P.auc_matrix(Xo, yo); d = P.smd(Xo, yo)
            ev, ba = Xo[yo == 1], Xo[yo == 0]
            e_i, b_i = P.iqr(ev), P.iqr(ba)
            rk = [{"feature": names[j], "auc": float(auc[j]), "iqr_ratio": float(e_i[j] / b_i[j]) if b_i[j] > 0 else np.nan}
                  for j in np.argsort(-np.abs(auc - 0.5))]
            return _hand_pattern(Xo, yo, names, rk)
        return maker, Xall, y, grp

    plan = [("A", "ağaç d=2 @t0", make_tree(2, "ev0"), "ev0"),
            ("B", "elle seçim @t0", make_hand("ev0"), "ev0"),
            ("C", "ağaç d=3 @t0", make_tree(3, "ev0"), "ev0"),
            ("D", "ağaç d=3 @t0+15dk", make_tree(3, "ev15"), "ev15"),
            ("E", "seçici ağaç d=4 @t0 (havuz FPR≤%0,5)", make_tree_precise(4, "ev0", 0.005), "ev0"),
            ("F", "seçici ağaç d=4 @t0+15dk (havuz FPR≤%0,5)", make_tree_precise(4, "ev15", 0.005), "ev15")]
    pi = info["n_events"] / max(info["pool_valid"], 1)
    for key, label, (maker, Xall, y, grp), ev_key in plan:
        conds = maker(Xall, y)
        if not conds:
            print(f"[analyze] desen {key}: üretilemedi"); continue
        r_m = _pattern_rates(conds, Xall, y, names)
        Xp, yp, sp_, gp = _rows(X, meta, ev_key, "b_pooled")
        r_p = _pattern_rates(conds, Xp, yp, names)
        cv = cv_pattern(maker, Xall, y, grp, names, seed=args.seed)
        prec = lambda rec, fpr: (rec * pi) / (rec * pi + fpr * (1 - pi)) if (rec * pi + fpr * (1 - pi)) > 0 else None
        res["patterns"].append({"key": key, "label": label, "offset": 0 if ev_key == "ev0" else 3,
                                "conditions": [dataclasses_asdict(c) for c in conds],
                                "matched": r_m, "pooled": r_p, "cv": cv, "pi": pi,
                                "implied_precision_pooled": prec(r_p["recall"], r_p["fpr"])})
        print(f"[analyze] {key} {label}: " + " & ".join(c.text() for c in conds))
        print(f"          recall {r_m['recall']:.2f}  FPR(eşleşmiş) {r_m['fpr']:.3f}  FPR(havuz) {r_p['fpr']:.3f}  "
              f"CV recall {cv['recall']} FPR {cv['fpr']}  π={pi:.5f}")
    (out / "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[analyze] yazıldı: {out / 'analysis.json'} ({time.time() - t0:.0f} sn)")


# ------------------------------------------------------------------------------------------------ 6. arka test
TPS = [1.5, 2.0, 4.0]
LOOKAHEAD_MS = 90 * 60_000


def _wilson(k, n, z=1.96):
    if n == 0:
        return None
    ph = k / n; den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return [float(c - h), float(c + h)]


def period_bounds(args, t_hi: int) -> dict[str, tuple[int, int]]:
    return {"oos": (parse_day(args.oos_start), parse_day(args.oos_end, end=True)),
            "train": (parse_day(args.train_start), t_hi)}


def stage_backtest(args) -> None:
    import itertools
    import pickle
    from scripts.ladder_rescan import chance_lift, coverage, stats
    from scripts.notification_outcomes_report import CandleStore
    from scripts.radar_shield_rescan_analysis import dedupe_horizon, is_overbought, load_jsonl, mark_episodes
    from scripts.strategy_rescan import trail_stats, trail_window
    from app.rescan.strategies import cooldown

    t_start = time.time()
    out = Path(args.out_dir)
    A = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    names = json.loads((Path(args.cache_dir) / "grid_names.json").read_text(encoding="utf-8"))
    E = load_events(args.cache_dir)
    d5 = load_cached(args.cache_dir, "d5"); d1 = load_cached(args.cache_dir, "d1")
    ends = sorted(int(a[-1, 0]) for s, a in d1.items() if s != "LUNATRY")
    t_hi = ends[len(ends) // 2] + 60_000 - 3 * 60_000
    bounds = period_bounds(args, t_hi)
    store = CandleStore({s: (a[:, 0], a[:, 2], a[:, 3], a[:, 4]) for s, a in d5.items()})
    qcol = names.index("5m.qv24_log10"); thr = np.log10(MIN_QUOTE)
    col = {nm: i for i, nm in enumerate(names)}
    pats = [{"key": p["key"], "label": p["label"], "conds": conds_from_json(p["conditions"]), "off": int(p["offset"])}
            for p in A["patterns"]]

    # --- Hız Avcısı (rescan canlı-benzeri) kümesi
    lo_all, hi_all = min(b[0] for b in bounds.values()), max(b[1] for b in bounds.values())
    base_all = dedupe_horizon(load_jsonl(args.jsonl, lo_all, hi_all))
    base = [r for r in base_all if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= 10]
    mark_episodes(base)
    base_ticks = {s: np.array(sorted(int(r["tick_ms"]) for r in rs), dtype=np.int64)
                  for s, rs in itertools.groupby(sorted(base, key=lambda r: r["symbol"]), key=lambda r: r["symbol"])}
    base_eps_all = [(r["symbol"], int(r["tick_ms"]), float(r["price"])) for r in base if r.get("ep")]
    print(f"[backtest] HA canlı-benzeri {len(base)} satır / {len(base_eps_all)} bölüm ({time.time() - t_start:.0f} sn)")

    ev_all = E["events"]
    ev_starts = {s: set(int(x) for x in idx) for s, (idx, es) in E["masks"].items()}

    sigs = {p["key"]: [] for p in pats}                  # tüm dönem sinyalleri (cooldown'lu)
    moment = {p["key"]: {pn: {"valid": 0, "true": 0, "true_strict": 0} for pn in bounds} for p in pats}
    ev_snap = {p["key"]: {pn: {"n": 0, "hit": 0} for pn in bounds} for p in pats}
    lun = {}
    valid_t = {pn: {} for pn in bounds}      # dönem -> sembol -> geçerli karar anları (null yakalama için)
    syms = sorted(E["masks"])
    for k, s in enumerate(syms):
        M, ot, f5 = load_grid_sym(args.cache_dir, s)
        n = len(ot); t_dec = ot + P.BAR_5M_MS
        base_valid = (np.arange(n) >= WARM_BARS) & (M[:, qcol] >= thr) & np.isfinite(M[:, col["5m.rsi14"]])
        c5 = f5[:, P.COL_C]
        starts = ev_starts[s]
        s_ev = [e for e in ev_all if e["sym"] == s]
        has1_all = np.isfinite(M[:, col["1m.rsi14"]])
        for pn, (b0, b1) in bounds.items():
            vmask = base_valid & has1_all & (t_dec >= b0) & (t_dec <= b1)
            valid_t[pn][s] = t_dec[vmask]
        for p in pats:
            m = P.eval_conditions({c.feature: M[:, col[c.feature]] for c in p["conds"]}, p["conds"]) & base_valid
            # 1m şartlı desenlerde 1m verisi olmayan an geçersiz (NaN → False zaten); payda için 1m varlığı
            has1 = np.isfinite(M[:, col["1m.rsi14"]])
            for pn, (b0, b1) in bounds.items():
                inp = (t_dec >= b0) & (t_dec <= b1)
                vm = base_valid & has1 & inp
                moment[p["key"]][pn]["valid"] += int(vm.sum())
                tm = m & vm
                moment[p["key"]][pn]["true"] += int(tm.sum())
                st_idx = np.flatnonzero(tm)
                moment[p["key"]][pn]["true_strict"] += int(sum(1 for i in st_idx if (i + 1) in starts))
                for e in s_ev:
                    ie = e["s"] - 1 + p["off"]
                    if b0 <= e["t0"] <= b1 and ie < n and has1[ie]:
                        ev_snap[p["key"]][pn]["n"] += 1
                        ev_snap[p["key"]][pn]["hit"] += int(m[ie])
            idx = np.flatnonzero(m & has1 & (t_dec >= lo_all) & (t_dec <= hi_all))
            idx = cooldown(idx, 12)
            for i in idx:
                t = int(t_dec[i]); entry = float(c5[i])
                ev = {tp: store.eval(s, t / 1000.0, entry, tp, 60, 3.0, 0.225) for tp in TPS}
                if any(v is None for v in ev.values()):
                    continue
                tr = trail_window(store, s, t / 1000.0, entry, trigger=1.0, gap=0.8, sl=3.0, cost=0.225)
                bt = base_ticks.get(s); lead = None; near = False
                if bt is not None and len(bt):
                    j = int(np.searchsorted(bt, t, side="right"))
                    if j < len(bt) and bt[j] - t <= LOOKAHEAD_MS:
                        lead = (bt[j] - t) / 60_000.0
                    near = (j < len(bt) and bt[j] - t <= LOOKAHEAD_MS) or (j > 0 and t - bt[j - 1] <= LOOKAHEAD_MS)
                sigs[p["key"]].append({"sym": s, "t": t, "entry": entry, "ev": ev, "trail": tr["net"] if tr else None,
                                       "lead": lead, "near": near, "strict": (int(i) + 1) in starts})
            if s == "LUNATRY":
                w0 = int(datetime(2026, 10, 17, 0, 0, tzinfo=TZ).timestamp() * 1000)
                w1 = int(datetime(2026, 10, 17, 3, 0, tzinfo=TZ).timestamp() * 1000)
                sel = np.flatnonzero(m & (t_dec >= w0) & (t_dec <= w1))
                lun[p["key"]] = [fmt_t(int(t_dec[i]), "%H:%M") for i in sel]
        if (k + 1) % 50 == 0:
            print(f"[backtest] {k + 1}/{len(syms)} ({time.time() - t_start:.0f} sn) sinyal: "
                  + ", ".join(f"{kk}={len(v)}" for kk, v in sigs.items()))

    _ot: dict[str, np.ndarray] = {}

    def ot_cache(s):
        if s not in _ot:
            _ot[s] = np.load(Path(args.cache_dir) / "grid" / f"OT_{s}.npy")
        return _ot[s]

    def ha_sigs(b0, b1):
        out_l = []
        for s, t, price in base_eps_all:
            if not (b0 <= t <= b1):
                continue
            ev = {tp: store.eval(s, t / 1000.0, price, tp, 60, 3.0, 0.225) for tp in TPS}
            if any(v is None for v in ev.values()):
                continue
            tr = trail_window(store, s, t / 1000.0, price, trigger=1.0, gap=0.8, sl=3.0, cost=0.225)
            out_l.append({"sym": s, "t": t, "entry": price, "ev": ev, "trail": tr["net"] if tr else None,
                          "strict": (int(np.searchsorted(ot_cache(s), t - P.BAR_5M_MS)) + 1) in ev_starts.get(s, ())})
        return out_l

    def null_catch(sl, events_in, vt, reps=10, seed=0):
        """Aynı sembol başına aynı sayıda RASTGELE sinyal (geçerli anlardan) olay koşusunu yakalar mı — şans yakalama oranı."""
        rng = np.random.default_rng(seed)
        cnt = collections.Counter(x["sym"] for x in sl)
        by_ev = collections.defaultdict(list)
        for e in events_in:
            by_ev[e["sym"]].append(e)
        if not events_in:
            return None
        tot = []
        for _ in range(reps):
            hit = 0
            for s_, evs in by_ev.items():
                k = cnt.get(s_, 0); arr_ = vt.get(s_)
                if not k or arr_ is None or len(arr_) == 0:
                    continue
                ts = np.sort(rng.choice(arr_, size=min(k, len(arr_)), replace=False))
                for e in evs:
                    j = int(np.searchsorted(ts, e["t0"], side="left"))
                    hit += int(j < len(ts) and ts[j] <= e["t_end"])
            tot.append(hit / len(events_in))
        return float(np.mean(tot))

    def summarize(sl: list[dict], b0: int, b1: int, days: float, eps_in: list[tuple], events_in: list[dict], label: str,
                  vt=None) -> dict:
        r: dict = {"label": label, "n": len(sl), "per_day": len(sl) / days if days else None}
        for tp in TPS:
            r[f"s{tp}"] = stats([x["ev"][tp] for x in sl])
        r["trail"] = trail_stats([x["trail"] for x in sl if x.get("trail") is not None])
        r["strict_share"] = float(np.mean([x["strict"] for x in sl])) if sl else None
        r["hit4_share"] = r["s4.0"].get("hit")
        for tp in (1.5, 4.0):
            r[f"chance{tp}"] = (chance_lift(sl, store, tp=tp, sample_n=args.chance_n, seed=args.seed, sl=3.0, cost=0.225)
                                if len(sl) >= 30 else {"n": 0, "lift": None, "null_hit": None})
            if len(sl) >= 30:   # örnekleme gürültüsü: farklı tohumlarla tekrar
                ls = [r[f"chance{tp}"]["lift"]] + [chance_lift(sl, store, tp=tp, sample_n=args.chance_n, seed=args.seed + k, sl=3.0,
                                                               cost=0.225)["lift"] for k in (11, 22)]
                ls = [x for x in ls if x is not None]
                r[f"chance{tp}_sd"] = float(np.std(ls, ddof=1)) if len(ls) > 1 else None
        by = {s: np.array(sorted(x["t"] for x in g), dtype=np.int64)
              for s, g in itertools.groupby(sorted(sl, key=lambda x: x["sym"]), key=lambda x: x["sym"])}
        cov, cov_lead = coverage([(s, t) for s, t, _ in eps_in], by)
        r["ha_cov"], r["ha_cov_lead_med"] = cov, cov_lead
        leads = [x["lead"] for x in sl if x.get("lead") is not None]
        r["ha_after_share"] = (len(leads) / len(sl)) if sl and "lead" in sl[0] else None
        r["ha_lead_med"] = float(np.median(leads)) if leads else None
        new = [x for x in sl if "near" in x and not x["near"]]
        r["new_n"] = len(new)
        r["new_hit1.5"] = stats([x["ev"][1.5] for x in new]).get("hit") if new else None
        r["new_net1.5"] = stats([x["ev"][1.5] for x in new]).get("net") if new else None
        # olay yakalama (sinyal düzeyi): [t0, t_end] içinde sinyal; HA ilk aday [t0, t0+90dk]
        caught = []; both_lead = []; ha_caught = 0
        for e in events_in:
            ts = by.get(e["sym"])
            ps = None
            if ts is not None and len(ts):
                j = int(np.searchsorted(ts, e["t0"], side="left"))
                if j < len(ts) and ts[j] <= e["t_end"]:
                    ps = int(ts[j])
            caught.append(ps is not None)
            hb = base_ticks.get(e["sym"])
            hf = None
            if hb is not None and len(hb):
                j = int(np.searchsorted(hb, e["t0"], side="left"))
                if j < len(hb) and hb[j] - e["t0"] <= LOOKAHEAD_MS:
                    hf = int(hb[j])
            ha_caught += hf is not None
            if ps is not None and hf is not None:
                both_lead.append((hf - ps) / 60_000.0)
        r["events_n"] = len(events_in)
        r["events_caught"] = float(np.mean(caught)) if caught else None
        r["events_caught_null"] = null_catch(sl, events_in, vt) if vt is not None else None
        hd = []
        for e in events_in:
            hb = base_ticks.get(e["sym"])
            if hb is not None and len(hb):
                j = int(np.searchsorted(hb, e["t0"], side="left"))
                if j < len(hb) and hb[j] - e["t0"] <= LOOKAHEAD_MS:
                    hd.append((hb[j] - e["t0"]) / 60_000.0)
        r["ha_delay_med"] = float(np.median(hd)) if hd else None
        r["events_ha_caught"] = ha_caught / len(events_in) if events_in else None
        r["events_both_n"] = len(both_lead)
        r["events_lead_med"] = float(np.median(both_lead)) if both_lead else None
        r["events_lead_earlier_share"] = float(np.mean([x > 0 for x in both_lead])) if both_lead else None
        return r

    res = {"bounds": {k: [b[0], b[1]] for k, b in bounds.items()}, "patterns": {}, "ha": {}, "lunatry": lun,
           "t_hi": t_hi}
    for pn, (b0, b1) in bounds.items():
        eff0 = max(b0, parse_day("2026-09-27") + 3 * 3_600_000)
        days = (b1 - eff0) / DAY_MS
        eps_in = [x for x in base_eps_all if eff0 <= x[1] <= b1]
        events_in = [e for e in ev_all if eff0 <= e["t0"] <= b1]
        # HA
        hs = ha_sigs(eff0, b1)
        res["ha"][pn] = summarize(hs, eff0, b1, days, eps_in, events_in, "Hız Avcısı (canlı-benzeri)", vt=valid_t[pn])
        for p in pats:
            sl = [x for x in sigs[p["key"]] if eff0 <= x["t"] <= b1]
            r = summarize(sl, eff0, b1, days, eps_in, events_in, f"{p['key']} {p['label']}", vt=valid_t[pn])
            mm = moment[p["key"]][pn]; es = ev_snap[p["key"]][pn]
            r["moment_valid"] = mm["valid"]; r["moment_true"] = mm["true"]
            r["fpr_pop"] = mm["true"] / mm["valid"] if mm["valid"] else None
            r["precision_strict_pop"] = mm["true_strict"] / mm["true"] if mm["true"] else None
            r["event_rate_pop"] = es["n"] / mm["valid"] if mm["valid"] else None
            r["recall_t0"] = es["hit"] / es["n"] if es["n"] else None
            r["recall_t0_n"] = es["n"]
            r["days"] = days
            res["patterns"].setdefault(p["key"], {})[pn] = r
            print(f"[backtest] {p['key']} {pn}: n={r['n']} ({r['per_day']:.0f}/gün) hit1.5={r['s1.5'].get('hit', 0):.3f} "
                  f"net1.5={r['s1.5'].get('net', 0):+.2f} şans-farkı={r['chance1.5']['lift']} hit4={r['hit4_share']} "
                  f"recall_t0={r['recall_t0']} ({time.time() - t_start:.0f} sn)")
    (out / "backtest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"[backtest] yazıldı ({time.time() - t_start:.0f} sn)")


# ------------------------------------------------------------------------------------------------ 7. rapor tabloları
def dec(txt: str) -> str:
    """Ondalık nokta → virgül (yalnız rakam.rakam; `1m.px_ema20` gibi adlara dokunmaz)."""
    import re
    return re.sub(r"(?<=\d)\.(?=\d)", ",", txt)


def _g(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}g}"


def _pc(x, nd=1):
    return "—" if x is None else f"%{100 * x:.{nd}f}".replace(".", ",")


def _pp(x):
    return "—" if x is None else f"{100 * x:+.1f} pp".replace(".", ",")


def _nr(x, fmt="{:+.2f}"):
    return "—" if x is None else fmt.format(x).replace(".", ",")


def stage_tables(args) -> None:
    import pickle
    out = Path(args.out_dir); tdir = out / "tables"; tdir.mkdir(parents=True, exist_ok=True)
    A = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    B = json.loads((out / "backtest.json").read_text(encoding="utf-8"))
    S = pickle.load(open(Path(args.cache_dir) / "snap.pkl", "rb"))
    E = load_events(args.cache_dir)
    names = S["names"]
    T: dict[str, str] = {}

    # ---- olaylar
    evs = E["events"]; tr = [e for e in evs if e["period"] == "train"]; oo = [e for e in evs if e["period"] == "oos"]
    byday = collections.Counter(day_key(e["t0"]) for e in evs)
    rows = ["| gün | olay | dönem |", "|---|---|---|"]
    for d in sorted(byday):
        rows.append(f"| {d[5:]} | {byday[d]} | {'eğitim' if d >= args.train_start else 'OOS'} |")
    T["events_per_day"] = "\n".join(rows)
    gains = np.array([e["gain"] for e in tr]); durs = np.array([e["dur_min"] for e in tr])
    T["events_summary"] = (f"Eğitim penceresi ({args.train_start} →): **{len(tr)} olay**, {len({e['sym'] for e in tr})} sembol; "
                           f"kazanç medyan %{np.median(gains):.1f} (Ç1–Ç3 %{np.quantile(gains, .25):.1f}–%{np.quantile(gains, .75):.1f}, maks %{gains.max():.1f}); "
                           f"süre medyan {np.median(durs):.0f} dk (Ç1–Ç3 {np.quantile(durs, .25):.0f}–{np.quantile(durs, .75):.0f}). "
                           f"OOS ({args.oos_start} → {args.oos_end}): **{len(oo)} olay**, {len({e['sym'] for e in oo})} sembol.")
    # en iyi 30 + gün-gün tam liste
    top = sorted(tr, key=lambda e: -e["gain"])[:30]
    rows = ["| sembol | t0 | kazanç | süre (dk) | yeşil payı | maks. geri çekilme | maks. tek mum |", "|---|---|---|---|---|---|---|"]
    for e in top:
        rows.append(f"| {e['sym']} | {fmt_t(e['t0'])} | %{e['gain']:.1f} | {e['dur_min']} | {_pc(e['green'], 0)} | %{e['dd']:.2f} | %{e['maxc']:.2f} |")
    T["events_top"] = "\n".join(rows)
    lines = []
    for d in sorted({day_key(e["t0"]) for e in tr}):
        ds = [e for e in tr if day_key(e["t0"]) == d]
        lines.append(f"- **{d[5:]}** ({len(ds)}): " + "; ".join(f"{e['sym'].replace('TRY', '')} {fmt_t(e['t0'], '%H:%M')} +{e['gain']:.1f}%/{e['dur_min']}dk" for e in ds))
    T["events_full"] = "\n".join(lines)

    # ---- olay tanımı duyarlılığı
    variants = [("varsayılan (4 % / yeşil ≥ %70 / dd ≤ 1,5 / mum ≤ 2,5)", {}),
                ("yeşil ≥ %60", {"green_min": 0.60}), ("yeşil ≥ %50", {"green_min": 0.50}),
                ("dd high-low bazlı (daha sıkı)", {"dd_mode": "hl"}), ("kazanç ≥ %3", {"min_gain": 3.0}),
                ("kazanç ≥ %5", {"min_gain": 5.0}), ("tek mum ≤ %2,0", {"max_candle": 2.0}), ("geri çekilme ≤ %1,0", {"max_dd": 1.0})]
    syms = sorted(E["masks"])
    f5s = {s: np.load(Path(args.cache_dir) / "grid" / f"F5_{s}.npy") for s in syms}
    train_ms = parse_day(args.train_start)
    rows = ["| tanım | eğitim penceresi | OOS | toplam |", "|---|---|---|---|"]
    for lab, kw in variants:
        base_p = ev_params(args)
        pp_ = P.EventParams(**{**base_p.__dict__, **kw})
        ct = co = 0
        for s in syms:
            for e in P.find_events(s, f5s[s], pp_, warm_bars=WARM_BARS):
                if e["t0"] >= train_ms:
                    ct += 1
                else:
                    co += 1
        rows.append(f"| {lab} | {ct} | {co} | {ct + co} |")
    T["events_sensitivity"] = "\n".join(rows)

    # ---- sıralama tabloları
    def rank_table(key, n=15):
        recs = A["rank"][key]; mt = A["meta"][key]
        rows = ["| # | özellik | AUC | d | olay medyan [Ç1–Ç3] | taban medyan [Ç1–Ç3] | IQR oranı | FWER |", "|---|---|---|---|---|---|---|---|"]
        for k, r in enumerate(recs[:n], 1):
            rows.append(f"| {k} | `{r['feature']}` | {r['auc']:.3f} | {r['d']:+.2f} | {_g(r['ev_med'])} [{_g(r['ev_q25'])}; {_g(r['ev_q75'])}] | "
                        f"{_g(r['b_med'])} [{_g(r['b_q25'])}; {_g(r['b_q75'])}] | {r['iqr_ratio']:.2f} | {'✓' if r['sig'] else ''} |")
        nsig = sum(r["sig"] for r in recs)
        return "\n".join(rows), f"FWER eşiği |AUC−0,5| > {mt['fwer_thr']:.3f}; eşiği geçen özellik {nsig}/{mt['n_features']} (olay {mt['n_events']}, taban {mt['n_base']})."
    for key, nm in (("ev0|b_matched", "rank_t0_matched"), ("ev0|b_pooled", "rank_t0_pooled"),
                    ("ev15|b_matched", "rank_t15_matched"), ("ev15|b_pooled", "rank_t15_pooled")):
        tb, note = rank_table(key)
        T[nm] = tb; T[nm + "_note"] = note
    T["rank_stability"] = (f"Eşleşmiş ↔ havuz tabanı AUC sıra korelasyonu (Spearman): t0 {A['meta']['ev0|spearman_auc']:.2f}, "
                           f"t0+15 dk {A['meta']['ev15|spearman_auc']:.2f}.")

    # ---- küme sıkılığı
    recs = A["rank"]["ev0|b_matched"]
    tight = sorted([r for r in recs if abs(r["auc"] - 0.5) >= 0.10 and np.isfinite(r["iqr_ratio"])], key=lambda r: r["iqr_ratio"])[:10]
    rows = ["| özellik | IQR oranı (olay/taban) | AUC | olay medyan [Ç1–Ç3] | taban medyan [Ç1–Ç3] |", "|---|---|---|---|---|"]
    for r in tight:
        rows.append(f"| `{r['feature']}` | {r['iqr_ratio']:.2f} | {r['auc']:.3f} | {_g(r['ev_med'])} [{_g(r['ev_q25'])}; {_g(r['ev_q75'])}] | "
                    f"{_g(r['b_med'])} [{_g(r['b_q25'])}; {_g(r['b_q75'])}] |")
    T["tight_t0"] = "\n".join(rows)
    tight15 = sorted([r for r in A["rank"]["ev15|b_matched"] if abs(r["auc"] - 0.5) >= 0.10 and np.isfinite(r["iqr_ratio"])],
                     key=lambda r: r["iqr_ratio"])[:8]
    rows = ["| özellik | IQR oranı (olay/taban) | AUC | olay medyan [Ç1–Ç3] | taban medyan [Ç1–Ç3] |", "|---|---|---|---|---|"]
    for r in tight15:
        rows.append(f"| `{r['feature']}` | {r['iqr_ratio']:.2f} | {r['auc']:.3f} | {_g(r['ev_med'])} [{_g(r['ev_q25'])}; {_g(r['ev_q75'])}] | "
                    f"{_g(r['b_med'])} [{_g(r['b_q25'])}; {_g(r['b_q75'])}] |")
    T["tight_t15"] = "\n".join(rows)
    allr = sorted([r for r in recs if np.isfinite(r["iqr_ratio"])], key=lambda r: r["iqr_ratio"])
    T["tight_min_ratio"] = f"En düşük IQR oranı {allr[0]['iqr_ratio']:.2f} (`{allr[0]['feature']}`); IQR oranı < 0,8 olan özellik sayısı {sum(r['iqr_ratio'] < 0.8 for r in recs)}/{len(recs)}."
    recs15 = A["rank"]["ev15|b_matched"]
    T["tight_t15_note"] = f"t0+15 dk için en düşük IQR oranı {min(r['iqr_ratio'] for r in recs15 if np.isfinite(r['iqr_ratio'])):.2f}; IQR oranı < 0,8: {sum(r['iqr_ratio'] < 0.8 for r in recs15)}/{len(recs15)}."

    # ---- yığılmış özellik tabloları (t0, eşleşmiş taban)
    by = {r["feature"]: r for r in recs}
    for tf in TF_ORDER:
        rows = [f"| özellik ({tf}) | olay medyan [Ç1–Ç3] | taban medyan [Ç1–Ç3] | AUC | d | IQR oranı | FWER |", "|---|---|---|---|---|---|---|"]
        for nm in [n for n in names if n.startswith(tf + ".")]:
            r = by[nm]
            rows.append(f"| `{nm.split('.', 1)[1]}` | {_g(r['ev_med'])} [{_g(r['ev_q25'])}; {_g(r['ev_q75'])}] | {_g(r['b_med'])} [{_g(r['b_q25'])}; {_g(r['b_q75'])}] | "
                        f"{r['auc']:.2f} | {r['d']:+.2f} | {r['iqr_ratio']:.2f} | {'✓' if r['sig'] else ''} |")
        T[f"stack_{tf}"] = "\n".join(rows)
    # t0+15 kompakt: ilk 12
    # ---- gün dışlama dayanıklılığı (15 Ekim pompa günü)
    Xall, y, syms_, grp = _rows(S["X"], S["meta"], "ev0", "b_matched")
    days_arr = np.array([m["day"] for m in S["meta"]["ev0"]] + [m["day"] for m in S["meta"]["b_matched"]])
    ok = np.isfinite(Xall).all(axis=1)
    keep = ok & (days_arr != "2026-10-15")
    auc_all = P.auc_matrix(Xall[ok], y[ok]); auc_ex = P.auc_matrix(Xall[keep], y[keep])
    from scipy.stats import spearmanr
    top_all = set(np.argsort(-np.abs(auc_all - .5))[:15]); top_ex = set(np.argsort(-np.abs(auc_ex - .5))[:15])
    n15 = sum(1 for m in S["meta"]["ev0"] if m["day"] == "2026-10-15")
    T["day_robust"] = (f"15 Ekim tek başına {n15}/{len(S['meta']['ev0'])} olay (%{100 * n15 / len(S['meta']['ev0']):.0f}). 15 Ekim dışlanınca AUC sıra korelasyonu "
                       f"{spearmanr(auc_all, auc_ex)[0]:.2f}, ilk 15 özelliğin {len(top_all & top_ex)}'i ortak (olay {int(y[keep].sum())}).")

    # ---- desenler
    rows = ["| desen | koşullar (AND) | olay kapsama (recall) | YA oranı eşleşmiş | YA oranı havuz | CV recall / YA | zorunlu kesinlik (π ile) |", "|---|---|---|---|---|---|---|"]
    for p in A["patterns"]:
        cond = " & ".join(f"`{c['feature']} {c['op']} {c['value']:.4g}`" for c in p["conditions"])
        cvr = p["cv"]
        rows.append(
                    f"| **{p['key']}** {p['label']} | {cond} | {_pc(p['matched']['recall'])} | {_pc(p['matched']['fpr'], 2)} | {_pc(p['pooled']['fpr'], 2)} | "
                    f"{_pc(cvr['recall'])} / {_pc(cvr['fpr'], 2)} | {_pc(p['implied_precision_pooled'], 2)} |")
    T["patterns"] = "\n".join(rows)
    T["pi_note"] = f"π (olay başlangıç oranı) = {A['patterns'][0]['pi']:.5f} ≈ her {1 / A['patterns'][0]['pi']:.0f} geçerli karar anında 1 olay."

    # ---- arka test
    def row(label, r, show_pop=True):
        s15, s20, s4 = r["s1.5"], r["s2.0"], r["s4.0"]
        c15, c4 = r["chance1.5"], r["chance4.0"]
        sd, sd4 = r.get("chance1.5_sd"), r.get("chance4.0_sd")
        tr_ = r["trail"]
        sds = "" if sd is None else f" (±{100 * sd:.1f})"
        sd4s = "" if sd4 is None else f" (±{100 * sd4:.1f})"
        return (f"| {label} | {r['n']} ({r['per_day']:.0f}) | {_pc(s15.get('hit'))} | {_pc(c15.get('null_hit'))} | **{_pp(c15.get('lift'))}**{sds} | "
                f"{_nr(s15.get('net'))} ({_nr(s15.get('t'), '{:+.0f}')}) | {_nr(s20.get('net'))} | "
                f"{_nr(tr_.get('net'))} ({_nr(tr_.get('t'), '{:+.1f}')}) | "
                f"{_pc(s4.get('hit'))} / {_pc(c4.get('null_hit'))} | {_pp(c4.get('lift'))}{sd4s} | {_pc(r.get('strict_share'), 2)} |")
    hdr = ("| ölçüt | sinyal (/gün) | hit60@1,5 | şans (null3) | **hit−şans** (± tohum sd) | net60@1,5 (t) | net60@2,0 | trailing net (t) | "
           "≥+%4/60dk payı / şans | +%4 şans farkı | olay-başlangıcı payı |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for pn, lab in (("oos", "OOS"), ("train", "in-sample")):
        rows = [hdr, row(f"Hız Avcısı ({lab})", B["ha"][pn])]
        for p in A["patterns"]:
            rows.append(row(f"{p['key']} ({lab})", B["patterns"][p["key"]][pn]))
        d0 = B["patterns"][A["patterns"][0]["key"]][pn]
        T[f"bt_{pn}"] = "\n".join(rows)
        T[f"bt_{pn}_days"] = f"{lab}: {fmt_t(max(B['bounds'][pn][0], parse_day('2026-09-27') + 3 * 3_600_000), '%d/%m %H:%M')} → {fmt_t(B['bounds'][pn][1], '%d/%m %H:%M')} ({d0['days']:.1f} gün)"
    # nokta-zaman tablosu
    rows = ["| desen | dönem | geçerli an | desen doğru (YA) | olay oranı | **olay kapsama @karar anı** | lift (kapsama/YA) | desen doğru iken olay başlangıcı | olay yakalama (koşu içinde sinyal) / şans | HA ≥1 aday (90 dk) | HA gecikme medyan |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in A["patterns"]:
        for pn, lab in (("oos", "OOS"), ("train", "in-sample")):
            r = B["patterns"][p["key"]][pn]
            lift = (r["recall_t0"] / r["fpr_pop"]) if r.get("fpr_pop") and r.get("recall_t0") is not None else None
            rows.append(
                        f"| {p['key']} | {lab} | {r['moment_valid']} | {_pc(r['fpr_pop'], 2)} | {_pc(r['event_rate_pop'], 3)} | {_pc(r['recall_t0'])} | "
                        f"{_nr(lift, '{:.1f}')}× | {_pc(r['precision_strict_pop'], 2)} | {_pc(r['events_caught'])} / {_pc(r.get('events_caught_null'))} | "
                        f"{_pc(r['events_ha_caught'])} | {_nr(r.get('ha_delay_med'), '{:.0f}')} dk |")
    T["bt_point"] = "\n".join(rows)
    # HA ile öncülük
    rows = ["| desen | dönem | HA sonra geldi (sinyal payı) | öncülük medyan (dk) | HA bölüm kapsama | olay: ikisi de yakaladı (n) | desen HA'dan önce (pay) | medyan fark (dk) |",
            "|---|---|---|---|---|---|---|---|"]
    for p in A["patterns"]:
        for pn, lab in (("oos", "OOS"), ("train", "in-sample")):
            r = B["patterns"][p["key"]][pn]
            rows.append(f"| {p['key']} | {lab} | {_pc(r['ha_after_share'])} | {_nr(r['ha_lead_med'], '{:.0f}')} | {_pc(r['ha_cov'])} | {r['events_both_n']} | "
                        f"{_pc(r['events_lead_earlier_share'])} | {_nr(r['events_lead_med'], '{:.0f}')} |")
    T["bt_lead"] = "\n".join(rows)
    T["lunatry"] = "; ".join(f"**{k}**: " + (", ".join(v) if v else "ateşlemedi") for k, v in B["lunatry"].items())
    for k, v in T.items():
        (tdir / f"{k}.md").write_text(dec(v), encoding="utf-8")
    print(f"[tables] {len(T)} tablo yazıldı: {tdir}")


def dataclasses_asdict(c) -> dict:
    return {"feature": c.feature, "op": c.op, "value": c.value}


def conds_from_json(lst) -> list:
    return [P.Condition(d["feature"], d["op"], float(d["value"])) for d in lst]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="data,grid,events,snap,analyze,backtest,tables")
    ap.add_argument("--db-url", default="")
    ap.add_argument("--cache-dir", default="work/pattern/_cache")
    ap.add_argument("--out-dir", default="work/pattern")
    ap.add_argument("--lunatry-cache", default="work/lunatry_1m_1017.json")
    ap.add_argument("--jsonl", default="work/rescan_21g_nogate.jsonl")
    ap.add_argument("--btc-1h", default="work/btc_1h.json")
    ap.add_argument("--train-start", default="2026-10-12")
    ap.add_argument("--oos-start", default="2026-09-27")
    ap.add_argument("--oos-end", default="2026-10-11")
    ap.add_argument("--baseline-mult", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ev-gain", type=float, default=4.0)
    ap.add_argument("--ev-green", type=float, default=0.70)
    ap.add_argument("--ev-dd", type=float, default=1.5)
    ap.add_argument("--ev-candle", type=float, default=2.5)
    ap.add_argument("--chance-n", type=int, default=3000)
    ap.add_argument("--n-perm", type=int, default=500)
    ap.add_argument("--top-k", type=int, default=15)
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
