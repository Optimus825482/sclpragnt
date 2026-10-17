"""90 günlük çıkış deseni çalışması — sıralama, aday desenler, çok-bölmeli arka test (2026-10-17, çevrimdışı).

`pattern90_study.py` veri aşamalarının (data, grid, events, snap) çıktılarını kullanır. Canlı koda bağlanmaz.

Aşamalar (`--stages`):
  analyze   her eğitim bölmesi (A son 5 gün, B son 15 gün, C1–C3 30 günlük bloklar) × {t0, t0+15} × {eşleşmiş, havuz} için
            özellik sıralaması (AUC, d, IQR oranı, FWER) taker'lı / taker'sız → analysis.json; aday desenler → patterns.json
  sweep     her desenin TÜM zaman çizelgesindeki sinyalleri (cooldown 12 bar) + vektörel sonuçları → sig/*.npz
  ha        Hız Avcısı (canlı-benzeri) bölümleri + sonuçları → ha.npz (work/rescan_90g_nogate.jsonl)
  eval      desen × dönem (eğitim / test / 30 günlük bloklar) ölçüleri → backtest.json
  report    markdown tabloları → work/pattern90/tables/*.md (rapor `report.md` elle derlenir)
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import pattern_study as P  # noqa: E402
from scripts.pattern90_study import (DAY_MS, MIN_QUOTE, WARM_BARS, day_idx, day_label, fmt_t, list_syms, load_events,  # noqa: E402
                                     load_sym, parse_day)

TAKER = ".tk_"
LOOK_MS = 90 * 60_000
EV_COLS = {"k": 0, "sid": 1, "t0": 2, "gain": 3, "dur": 4, "bucket_n": 5, "keep": 6, "complete": 7, "keep_b": 8, "keep_c": 9, "t_end": 10}
KEY_SHIFT = 1 << 42
DATA_START = "2026-07-19"
FIRST_DAY = "2026-07-20"          # özellik ısınması (300 bar) sonrası ilk güvenilir gün


def tk_mask(names) -> np.ndarray:
    return np.array([TAKER in nm for nm in names])


# ------------------------------------------------------------------------------------------------ bölmeler
def make_sets(end_ms: int) -> dict:
    D = parse_day
    b = [(D(DATA_START), D("2026-08-17", end=True)), (D("2026-08-18"), D("2026-09-16", end=True)), (D("2026-09-17"), end_ms)]
    return {
        "A": {"label": "A: eğitim son 5 gün (12 Eki →), test 29 Tem – 11 Eki", "train": [(D("2026-10-12"), end_ms)],
              "test": [(D("2026-07-29"), D("2026-10-11", end=True))]},
        "B": {"label": "B (birincil): eğitim son 15 gün (2 Eki →), test 29 Tem – 1 Eki", "train": [(D("2026-10-02"), end_ms)],
              "test": [(D("2026-07-29"), D("2026-10-01", end=True))]},
        "C1": {"label": "C1: eğitim 19 Tem – 17 Ağu, test diğer iki blok", "train": [b[0]], "test": [b[1], b[2]]},
        "C2": {"label": "C2: eğitim 18 Ağu – 16 Eyl, test diğer iki blok", "train": [b[1]], "test": [b[0], b[2]]},
        "C3": {"label": "C3: eğitim 17 Eyl – 17 Eki, test diğer iki blok", "train": [b[2]], "test": [b[0], b[1]]},
    }, {"blk1": [b[0]], "blk2": [b[1]], "blk3": [b[2]]}


def in_iv(t, ivs) -> np.ndarray:
    t = np.asarray(t)
    m = np.zeros(t.shape, dtype=bool)
    for lo, hi in ivs:
        m |= (t >= lo) & (t <= hi)
    return m


def iv_days(ivs, d0: int, d1: int) -> float:
    return sum(max(0, min(hi, d1) - max(lo, d0)) for lo, hi in ivs) / DAY_MS


# ------------------------------------------------------------------------------------------------ anlık görüntü yükleme
def load_snap(cache_dir: str) -> dict:
    z = np.load(Path(cache_dir) / "snap.npz")
    return {"names": [str(x) for x in z["names"]], "syms": [str(x) for x in z["syms"]], "ev": z["ev_meta"], "X0": z["X0"], "X3": z["X3"],
            "Xm": z["Xm"], "mm": z["mm"], "Xp": z["Xp"], "pm": z["pm"], "n_valid": int(z["n_valid_total"])}


def build_train(S: dict, snap: dict, off: int, base: str, *, mult: int = 40, keep_col: str = "keep", seed: int = 0):
    """Eğitim bölmesi için (X, y, strata, ev_ids): kümesiz olaylar + (eşleşmiş | havuz) taban. Eksik özellikli satırlar atılmadan döner."""
    ev = snap["ev"]
    sel = in_iv(ev[:, EV_COLS["t0"]], S["train"]) & (ev[:, EV_COLS["complete"]] == 1) & (ev[:, EV_COLS[keep_col]] == 1)
    ids = np.flatnonzero(sel)
    Xe = (snap["X0"] if off == 0 else snap["X3"])[ids]
    if base == "matched":
        selb = np.isin(snap["mm"][:, 2], ids)
        Xb = snap["Xm"][selb]; sb = snap["mm"][selb, 0]
    else:
        idx = np.flatnonzero(in_iv(snap["pm"][:, 1], S["train"]))
        rng = np.random.default_rng(seed)
        if len(idx) > mult * len(ids):
            idx = rng.choice(idx, size=mult * len(ids), replace=False)
        Xb = snap["Xp"][idx]; sb = snap["pm"][idx, 0]
    X = np.vstack([Xe, Xb]).astype(np.float64)
    y = np.r_[np.ones(len(Xe)), np.zeros(len(Xb))]
    strata = np.r_[ev[ids, EV_COLS["sid"]].astype(int), sb]
    return X, y, strata, ids


# ------------------------------------------------------------------------------------------------ sıralama
def rank_cell(X, y, strata, names, *, n_perm: int, seed: int, stratified: bool) -> tuple[list[dict], dict]:
    ok = np.isfinite(X).all(axis=1)
    X, y, strata = X[ok], y[ok], strata[ok]
    tk = tk_mask(names)
    auc = P.auc_matrix(X, y); d = P.smd(X, y)
    ev, ba = X[y == 1], X[y == 0]
    qe = np.quantile(ev, [.25, .5, .75], axis=0); qb = np.quantile(ba, [.25, .5, .75], axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where((qb[2] - qb[0]) > 0, (qe[2] - qe[0]) / (qb[2] - qb[0]), np.nan)
    # FWER: aynı permütasyonlardan iki aile (tümü | taker'sız)
    rng = np.random.default_rng(seed)
    n1 = int(y.sum()); n0 = len(y) - n1
    R = P._rank_cols(X)
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)] if stratified else [np.arange(len(y))]
    mx_all = np.empty(n_perm); mx_base = np.empty(n_perm)
    for b in range(n_perm):
        yp = np.zeros(len(y))
        for g in groups:
            k = int(y[g].sum())
            if k:
                yp[rng.choice(g, size=k, replace=False)] = 1.0
        dev = np.abs((yp @ R - n1 * (n1 + 1) / 2.0) / (n1 * n0) - 0.5)
        mx_all[b] = dev.max(); mx_base[b] = dev[~tk].max()
    thr_all = float(np.quantile(mx_all, 0.95)); thr_base = float(np.quantile(mx_base, 0.95))
    dev = np.abs(auc - 0.5)
    order_all = np.argsort(-dev)
    rank_all = np.empty(len(names), dtype=int); rank_all[order_all] = np.arange(1, len(names) + 1)
    order_base = [j for j in order_all if not tk[j]]
    rank_base = np.full(len(names), -1); rank_base[order_base] = np.arange(1, len(order_base) + 1)
    recs = []
    for j, nm in enumerate(names):
        recs.append({"feature": nm, "tk": bool(tk[j]), "auc": float(auc[j]), "d": float(d[j]), "ev": [float(x) for x in qe[:, j]],
                     "ba": [float(x) for x in qb[:, j]], "iqr_ratio": float(ratio[j]), "rank_all": int(rank_all[j]),
                     "rank_base": int(rank_base[j]), "sig_all": bool(dev[j] > thr_all), "sig_base": bool(dev[j] > thr_base) if not tk[j] else None})
    recs.sort(key=lambda r: r["rank_all"])
    return recs, {"n_events": n1, "n_base": n0, "thr_all": thr_all, "thr_base": thr_base, "n_features": len(names),
                  "n_taker": int(tk.sum()), "n_incomplete_dropped": int((~ok).sum())}


# ------------------------------------------------------------------------------------------------ desen üretimi
def _top_k(Xo, yo, K):
    auc = P.auc_matrix(Xo, yo)
    return np.argsort(-np.abs(auc - 0.5))[:K]


def tree_maker(names, *, depth, K, seed, precise=None):
    def maker(Xtr, ytr):
        ok = np.isfinite(Xtr).all(axis=1); Xo, yo = Xtr[ok], ytr[ok]
        if yo.sum() < 20:
            return []
        top = _top_k(Xo, yo, K)
        if precise is None:
            tp = P.fit_pattern_tree(Xo[:, top], yo, [names[j] for j in top], depth=depth,
                                    min_leaf_events=max(8, int(0.06 * yo.sum())), seed=seed)
        else:
            tp = P.fit_pattern_tree(Xo[:, top], yo, [names[j] for j in top], depth=depth, min_recall=0.03,
                                    min_leaf_events=max(6, int(0.03 * yo.sum())), seed=seed, max_fpr=precise, pos_share=0.05)
        return tp.conditions if tp else []
    return maker


def hand_pattern(Xo, yo, names, *, k_feat=3, keep=0.80, tight=0.6, corr_max=0.85):
    """Elle seçim (eski çalışmayla aynı kural): sıralamanın en üstünden, aile tekrarı / yüksek korelasyonu olmayan özellikler;
    eşik olay dağılımının `keep` oranını koruyan kuantilde (tek taraflı) ya da küme sıkıysa [q10, q90] bandı."""
    auc = P.auc_matrix(Xo, yo)
    ev, ba = Xo[yo == 1], Xo[yo == 0]
    e_i, b_i = P.iqr(ev), P.iqr(ba)
    idx = {nm: i for i, nm in enumerate(names)}
    chosen: list[str] = []; fams = set(); conds: list[P.Condition] = []
    for j in np.argsort(-np.abs(auc - 0.5)):
        nm = names[j]; fam = nm.split(".", 1)[1]
        if fam in fams or nm.endswith(".hour"):
            continue
        if any(abs(np.corrcoef(Xo[:, j], Xo[:, idx[c]])[0, 1]) > corr_max for c in chosen):
            continue
        chosen.append(nm); fams.add(fam)
        ratio = e_i[j] / b_i[j] if b_i[j] > 0 else np.nan
        if np.isfinite(ratio) and ratio <= tight:
            lo, hi = np.quantile(ev[:, j], [0.10, 0.90])
            conds += [P.Condition(nm, ">", float(lo)), P.Condition(nm, "<=", float(hi))]
        elif auc[j] > 0.5:
            conds.append(P.Condition(nm, ">", float(np.quantile(ev[:, j], 1 - keep))))
        else:
            conds.append(P.Condition(nm, "<=", float(np.quantile(ev[:, j], keep))))
        if len(chosen) >= k_feat:
            break
    return conds


def hand_maker(names):
    def maker(Xtr, ytr):
        ok = np.isfinite(Xtr).all(axis=1); Xo, yo = Xtr[ok], ytr[ok]
        return hand_pattern(Xo, yo, names) if yo.sum() >= 20 else []
    return maker


def taker_addon(X, y, names, base_conds, *, max_add=2, min_ev=15, min_gain=1.05):
    """C deseninin üstüne en fazla `max_add` TAKER koşulu ekler (eğitimde açgözlü): her adımda taker özelliği × yön × olay-dağılımı
    kuantili eşiği üzerinden, kalan olay sayısı ≥ min_ev ve ≥ mevcut olayların %40'ı koşuluyla dengeli-kesinliği
    (olay / (olay + taban × n1/n0)) en yüksek olan eklenir; kesinlik ≥ 1,05× artmıyorsa durur."""
    idx = {nm: i for i, nm in enumerate(names)}
    tk_cols = [i for i, nm in enumerate(names) if TAKER in nm]
    ok = np.isfinite(X).all(axis=1)
    X, y = X[ok], y[ok]
    n1, n0 = int(y.sum()), int((y == 0).sum())
    cur = P.eval_conditions({c.feature: X[:, idx[c.feature]] for c in base_conds}, base_conds)
    conds = list(base_conds)
    ev = X[y == 1]

    def prec(m):
        e = int((m & (y == 1)).sum()); b = int((m & (y == 0)).sum())
        return e / (e + b * n1 / n0 + 1e-12), e
    p_cur, e_cur = prec(cur)
    for _ in range(max_add):
        best = None
        for j in tk_cols:
            for op, q in ((">", 0.2), (">", 0.35), (">", 0.5), ("<=", 0.5), ("<=", 0.65), ("<=", 0.8)):
                th = float(np.quantile(ev[:, j], q))
                m = cur & ((X[:, j] > th) if op == ">" else (X[:, j] <= th))
                p, e = prec(m)
                if e < min_ev or e < 0.4 * e_cur:
                    continue
                if best is None or p > best[0]:
                    best = (p, e, m, P.Condition(names[j], op, th))
        if best is None or best[0] < min_gain * p_cur:
            break
        p_cur, e_cur, cur = best[0], best[1], best[2]
        conds.append(best[3])
    return conds[len(base_conds):]


def rates(conds, X, y, names):
    idx = {nm: i for i, nm in enumerate(names)}
    ok = np.isfinite(X).all(axis=1)
    X, y = X[ok], y[ok]
    m = P.eval_conditions({c.feature: X[:, idx[c.feature]] for c in conds}, conds)
    return {"recall": float(m[y == 1].mean()), "fpr": float(m[y == 0].mean()), "n_ev": int(y.sum())}


PATTERN_PLAN = [("A", "ağaç d=2 @t0", 0), ("B", "elle seçim @t0", 0), ("C", "ağaç d=3 @t0", 0), ("D", "ağaç d=3 @t0+15dk", 3),
                ("E", "seçici ağaç d=4 @t0 (havuz YA≤%0,5)", 0), ("F", "seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5)", 3)]


def derive_patterns(snap, S, set_id: str, pool: str, seed: int, K: int) -> list[dict]:
    names_all = snap["names"]
    cols = [j for j, nm in enumerate(names_all) if pool == "all" or TAKER not in nm]
    names = [names_all[j] for j in cols]
    data = {}
    for off in (0, 3):
        for base in ("matched", "pooled"):
            X, y, st, ids = build_train(S, snap, off, base, seed=seed)
            data[(off, base)] = (X[:, cols], y)
    out = []
    for pid, label, off in PATTERN_PLAN:
        if pid in ("A", "C", "D"):
            Xm_, ym_ = data[(off, "matched")]
            maker = tree_maker(names, depth=2 if pid == "A" else 3, K=K, seed=seed)
        elif pid == "B":
            Xm_, ym_ = data[(0, "matched")]
            maker = hand_maker(names)
        else:
            Xm_, ym_ = data[(off, "pooled")]
            maker = tree_maker(names, depth=4, K=K, seed=seed, precise=0.005)
        conds = maker(Xm_, ym_)
        if not conds:
            continue
        out.append(_pat_record(set_id, pool, pid, label, off, conds, data, names))
    if pool == "all":
        c = next((p for p in out if p["pid"] == "C"), None)
        if c is not None:
            Xm_, ym_ = data[(0, "matched")]
            bc = [P.Condition(**d) for d in c["conditions"]]
            add = taker_addon(Xm_, ym_, names, bc)
            label = "C + taker ek koşul(lar)ı @t0"
            if not add:   # açgözlü ekleme kesinliği artırmadı → yine de en iyi TEK taker koşulunu zorla (taker'ın katkısını görmek için)
                add = taker_addon(Xm_, ym_, names, bc, max_add=1, min_gain=0.0)
                label = "C + en iyi tek taker koşulu (zorunlu) @t0"
            if add:
                out.append(_pat_record(set_id, pool, "G", label, 0, bc + add, data, names))
        # yalnız-taker ağaçları: emir akışı tek başına bir desen veriyor mu?
        tcols = [j for j, nm in enumerate(names) if TAKER in nm]
        tnames = [names[j] for j in tcols]
        for pid, label, off in (("H", "yalnız-taker ağaç d=3 @t0", 0), ("I", "yalnız-taker ağaç d=3 @t0+15dk", 3)):
            Xm_, ym_ = data[(off, "matched")]
            conds = tree_maker(tnames, depth=3, K=15, seed=seed)(Xm_[:, tcols], ym_)
            if conds:
                out.append(_pat_record(set_id, pool, pid, label, off, conds, data, names))
    return out


def _pat_record(set_id, pool, pid, label, off, conds, data, names) -> dict:
    Xm_, ym_ = data[(off, "matched")]
    Xp_, yp_ = data[(off, "pooled")]
    return {"key": f"{set_id}|{pool}|{pid}", "set": set_id, "pool": pool, "pid": pid, "label": label, "offset": off,
            "conditions": [{"feature": c.feature, "op": c.op, "value": float(c.value)} for c in conds],
            "uses_taker": any(TAKER in c.feature for c in conds),
            "train_matched": rates(conds, Xm_, ym_, names), "train_pooled": rates(conds, Xp_, yp_, names)}


def stage_analyze(args) -> None:
    snap = load_snap(args.cache_dir)
    names = snap["names"]
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    end_ms = parse_day("2026-10-17", end=True)
    sets, _ = make_sets(end_ms)
    t0 = time.time()
    res = {"names": names, "rank": {}, "meta": {}, "sets": {k: {"label": v["label"]} for k, v in sets.items()}}
    for sk, S in sets.items():
        for off in (0, 3):
            for base in ("matched", "pooled"):
                X, y, st, ids = build_train(S, snap, off, base, seed=args.seed)
                recs, mt = rank_cell(X, y, st, names, n_perm=args.n_perm, seed=args.seed, stratified=(base == "matched"))
                key = f"{sk}|t{15 if off else 0}|{base}"
                res["rank"][key] = recs; res["meta"][key] = mt
                print(f"[analyze] {key}: olay {mt['n_events']}, taban {mt['n_base']}, eşik(tümü) {mt['thr_all']:.3f} (taker'sız {mt['thr_base']:.3f}) "
                      f"({time.time() - t0:.0f} sn)", flush=True)
    # sağlamlık: kümesizleştirme varyantları (B bölmesi): birincil ↔ her-kovada-tek ↔ kümesiz-değil
    from scipy.stats import spearmanr
    rob = {}
    for sk in ("B", "A"):
        S = sets[sk]
        aucs = {}
        for var in ("keep", "keep_b", "keep_c"):
            X, y, st, ids = build_train(S, snap, 0, "matched", keep_col=var, seed=args.seed)
            ok = np.isfinite(X).all(axis=1)
            aucs[var] = (P.auc_matrix(X[ok], y[ok]), int(y[ok].sum()))
        # kümesiz değil: tüm olaylar
        S2 = dict(S)
        ev = snap["ev"]; sel = in_iv(ev[:, EV_COLS["t0"]], S["train"]) & (ev[:, EV_COLS["complete"]] == 1)
        ids = np.flatnonzero(sel)
        selb = np.isin(snap["mm"][:, 2], ids)
        X = np.vstack([snap["X0"][ids], snap["Xm"][selb]]).astype(np.float64); y = np.r_[np.ones(len(ids)), np.zeros(int(selb.sum()))]
        ok = np.isfinite(X).all(axis=1)
        aucs["none"] = (P.auc_matrix(X[ok], y[ok]), int(y[ok].sum()))
        rob[sk] = {v: {"n_events": aucs[v][1], "spearman_vs_primary": float(spearmanr(aucs["keep"][0], aucs[v][0])[0]),
                       "top15_overlap": len(set(np.argsort(-np.abs(aucs["keep"][0] - .5))[:15]) & set(np.argsort(-np.abs(aucs[v][0] - .5))[:15]))}
                   for v in aucs}
    res["robust_decluster"] = rob
    (out / "analysis.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    # desenler
    pats = []
    for sk, S in sets.items():
        for pool in ("base", "all"):
            ps = derive_patterns(snap, S, sk, pool, args.seed, args.top_k)
            pats += ps
            print(f"[analyze] {sk}/{pool}: {len(ps)} desen: " + ", ".join(p['pid'] for p in ps) + f" ({time.time() - t0:.0f} sn)", flush=True)
    (out / "patterns.json").write_text(json.dumps(pats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[analyze] bitti: {len(pats)} desen ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ süpürme (sinyaller)
def cooldown_idx(idx: np.ndarray, bars: int) -> np.ndarray:
    if len(idx) == 0:
        return idx.astype(np.int64)
    kept = []; last = -10 ** 9
    for i in idx:
        if i - last >= bars:
            kept.append(int(i)); last = int(i)
    return np.array(kept, dtype=np.int64)


def stage_sweep(args) -> None:
    cache = Path(args.cache_dir); out = Path(args.out_dir)
    (out / "sig").mkdir(parents=True, exist_ok=True)
    names = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    col = {nm: i for i, nm in enumerate(names)}
    pats = json.loads((out / "patterns.json").read_text(encoding="utf-8"))
    syms = list_syms(args.cache_dir, "d5")
    thr = np.log10(MIN_QUOTE)
    need = [col["5m.qv24_log10"], col["5m.rsi14"], col["1m.rsi14"], col["5m.tk_share3"], col["1m.tk_share_z3"], col["1m.tk_net12"]]
    acc = {p["key"]: {"sid": [], "row": [], "t": [], "out": []} for p in pats}
    lun = {p["key"]: [] for p in pats}
    valid_t = {}
    t0 = time.time()
    lun_w = (parse_day("2026-10-17"), parse_day("2026-10-17") + 4 * 3_600_000)
    for sid, s in enumerate(syms):
        M, ot, _ = load_sym(args.cache_dir, s)
        OS = np.load(cache / "grid" / f"OS_{s}.npy")
        n = len(ot); t_dec = ot + P.BAR_5M_MS
        sub = M[:, need]
        v = (np.arange(n) >= WARM_BARS) & (sub[:, 0] >= thr) & np.isfinite(sub[:, 1:]).all(axis=1)
        valid_t[sid] = t_dec[v]
        for p in pats:
            conds = [P.Condition(**d) for d in p["conditions"]]
            m = P.eval_conditions({c.feature: M[:, col[c.feature]] for c in conds}, conds) & v
            idx = np.flatnonzero(m)
            if s == "LUNATRY":
                lun[p["key"]] = [fmt_t(int(t_dec[i]), "%H:%M") for i in idx if lun_w[0] <= t_dec[i] <= lun_w[1]]
            idx = cooldown_idx(idx, 12)
            if len(idx) == 0:
                continue
            idx = idx[OS[idx, 0] == 1]
            if len(idx) == 0:
                continue
            a = acc[p["key"]]
            a["sid"].append(np.full(len(idx), sid, dtype=np.int16)); a["row"].append(idx.astype(np.int32))
            a["t"].append(t_dec[idx]); a["out"].append(OS[idx, 1:])
        if (sid + 1) % 50 == 0:
            print(f"[sweep] {sid + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    for p in pats:
        a = acc[p["key"]]
        if a["sid"]:
            sidv = np.concatenate(a["sid"]); tv = np.concatenate(a["t"]); ov = np.concatenate(a["out"]); rv = np.concatenate(a["row"])
            o = np.argsort(tv, kind="stable")
            sidv, tv, ov, rv = sidv[o], tv[o], ov[o], rv[o]
        else:
            sidv = np.zeros(0, np.int16); tv = np.zeros(0, np.int64); ov = np.zeros((0, 9), np.float32); rv = np.zeros(0, np.int32)
        np.savez(out / "sig" / (p["key"].replace("|", "_") + ".npz"), sid=sidv, t=tv, out=ov, row=rv)
    pickle.dump({"valid_t": valid_t, "lunatry": lun, "syms": syms}, open(cache / "sweep_extra.pkl", "wb"))
    print(f"[sweep] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ şans tabanı (vektörel null3)
class NullEngine:
    """`notification_outcomes_report.compute_chance` null / null2 / null3 mantığının vektörel yeniden yazımı: aynı sembol, bildirimden
    ≥ 2 sa uzak; null = ±1 saat dilimi, null2 = + son 30 dk high-low aralığı benzer (±%25, en az 0,4 pt), null3 = + son 30 dk getirisi
    benzer. Rastgele anlar için sonuç, anın kapanışından SONRAKİ 12 bar (eval_window(det = ot+299,999 sn)). En az 8 an yoksa taban yok;
    en çok 30 an. (Ham mum yerine boşlukları düz mumla doldurulmuş ızgara kullanılır; ileri sonuç geçerliliği gerçek-mum kuralıyla.)"""

    def __init__(self, cache_dir: str, syms: list[str], k: int = 30):
        self.cache = Path(cache_dir) / "grid"; self.syms = syms; self.k = k; self.c: dict[int, tuple] = {}

    def get(self, sid: int):
        r = self.c.get(sid)
        if r is None:
            s = self.syms[sid]
            f5 = np.load(self.cache / f"F5_{s}.npy"); ot = np.load(self.cache / f"OT_{s}.npy"); ON = np.load(self.cache / f"ON_{s}.npy")
            h, l, c = f5[:, P.COL_H], f5[:, P.COL_L], f5[:, P.COL_C]
            n = len(ot)
            rg = np.full(n, np.nan); rt = np.full(n, np.nan)
            if n > 7:
                sw = np.lib.stride_tricks.sliding_window_view
                rg[5:] = sw(h, 6).max(axis=1) / sw(l, 6).min(axis=1) - 1
                rt[6:] = c[6:] / c[:-6] - 1
            hrs = ((ot / 1000 + 3 * 3600) // 3600 % 24).astype(int)
            valid = np.zeros(n, bool); valid[6:n - 30] = True
            valid &= ON[:, 0] == 1       # sonucu ölçülemeyen an aday olamaz (orijinalde store.eval None → atlanır)
            r = (ot, rg, rt, hrs, valid, ON[:, 1].astype(float), ON[:, 2].astype(float), ON[:, 3].astype(float), ON[:, 4].astype(float))
            self.c[sid] = r
        return r

    def _null(self, cand, rng, hit):
        js = rng.permutation(np.flatnonzero(cand))[: self.k]
        return None if len(js) < 8 else float(hit[js].mean())

    def lift(self, sid, t, hit15, hit4, *, n_sample: int, seed: int, net15=None, trail=None) -> dict:
        rng = np.random.default_rng(seed)
        N = len(t)
        if N < 30:
            return {"n": 0}
        pick = rng.permutation(N)[:n_sample]
        l15 = []; l4 = []; n15 = []; n4 = []; days = []; ln = []; lt = []; nn = []; nt = []
        for q in pick:
            ot, rg, rt, hrs, valid, h15, h4, nt15, ntr = self.get(int(sid[q]))
            tq = int(t[q]); det = tq / 1000.0
            hour = int(((det + 3 * 3600) // 3600) % 24)
            v = valid & (np.abs(ot / 1000 - det) >= 7200)
            j0 = int(np.searchsorted(ot + 300000, tq, side="right")) - 1
            cands = []
            if j0 >= 6 and np.isfinite(rg[j0]):
                rgn, rtn = rg[j0], rt[j0]
                c2 = v & (np.abs(rg - rgn) <= max(0.004, 0.25 * rgn))
                c3 = c2 & (np.abs(rt - rtn) <= max(0.004, 0.25 * abs(rtn)))
                cands += [c3, c2]
            dh = np.abs(hrs - hour); dh = np.minimum(dh, 24 - dh)
            cands.append(v & (dh <= 1))
            for cand in cands:
                js = rng.permutation(np.flatnonzero(cand))[: self.k]
                if len(js) >= 8:
                    a, b = float(h15[js].mean()), float(h4[js].mean())
                    l15.append(hit15[q] - a); l4.append(hit4[q] - b); n15.append(a); n4.append(b); days.append(int(day_idx(tq)))
                    if net15 is not None:
                        c_, d_ = float(nt15[js].mean()), float(ntr[js].mean())
                        ln.append(net15[q] - c_); nn.append(c_); lt.append(trail[q] - d_); nt.append(d_)
                    break
        if not l15:
            return {"n": 0}
        days = np.array(days)

        def se_cl(x):
            x = np.array(x)
            g = [x[days == d].sum() for d in np.unique(days)]
            return float(np.sqrt(np.sum((np.array(g) - x.mean() * np.array([np.sum(days == d) for d in np.unique(days)])) ** 2)) / len(x))
        r = {"n": len(l15), "lift15": float(np.mean(l15)), "null15": float(np.mean(n15)), "lift4": float(np.mean(l4)), "null4": float(np.mean(n4)),
             "se15": se_cl(l15), "se4": se_cl(l4)}
        if ln:
            r.update({"liftnet": float(np.mean(ln)), "nullnet": float(np.mean(nn)), "se_net": se_cl(ln),
                      "lifttr": float(np.mean(lt)), "nulltr": float(np.mean(nt)), "se_tr": se_cl(lt)})
        return r


# ------------------------------------------------------------------------------------------------ Hız Avcısı referansı
def stage_ha(args) -> None:
    from scripts.notification_outcomes_report import CandleStore
    from scripts.radar_shield_rescan_analysis import dedupe_horizon, is_overbought, load_jsonl, mark_episodes
    from scripts.strategy_rescan import trail_window
    cache = Path(args.cache_dir); out = Path(args.out_dir)
    syms = list_syms(args.cache_dir, "d5"); sid_of = {s: k for k, s in enumerate(syms)}
    d5 = {s: np.load(cache / "d5" / f"{s}.npy") for s in syms}
    store = CandleStore({s: (a[:, 0], a[:, 2], a[:, 3], a[:, 4]) for s, a in d5.items()})
    lo, hi = parse_day(DATA_START), parse_day("2026-10-17", end=True)
    t0 = time.time()
    rows = dedupe_horizon(load_jsonl(args.jsonl, lo, hi))
    base = [r for r in rows if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= 10]
    mark_episodes(base)
    ticks = collections.defaultdict(list)
    for r in base:
        if r["symbol"] in sid_of:
            ticks[sid_of[r["symbol"]]].append(int(r["tick_ms"]))
    eps = [(r["symbol"], int(r["tick_ms"]), float(r["price"])) for r in base if r.get("ep") and r["symbol"] in sid_of]
    sid, tt, oo = [], [], []
    for s, t, price in eps:
        ev = {tp: store.eval(s, t / 1000.0, price, tp, 60, 3.0, 0.225) for tp in (1.5, 2.0, 4.0)}
        if any(v is None for v in ev.values()):
            continue
        tr = trail_window(store, s, t / 1000.0, price, trigger=1.0, gap=0.8, sl=3.0, cost=0.225)
        sid.append(sid_of[s]); tt.append(t)
        oo.append([float(ev[1.5]["hit"]), ev[1.5]["net"], float(ev[2.0]["hit"]), ev[2.0]["net"], float(ev[4.0]["hit"]), ev[4.0]["net"],
                   tr["net"] if tr else np.nan, ev[1.5]["mfe"], ev[1.5]["mae"]])
    o = np.argsort(tt, kind="stable")
    np.savez(out / "ha.npz", sid=np.array(sid, np.int16)[o], t=np.array(tt, np.int64)[o], out=np.array(oo, np.float32)[o])
    pickle.dump({k: np.array(sorted(v), dtype=np.int64) for k, v in ticks.items()}, open(cache / "ha_ticks.pkl", "wb"))
    ts = np.array(tt)
    print(f"[ha] canlı-benzeri satır {len(base)}; bölüm {len(eps)}; ölçülen {len(sid)}; aralık {fmt_t(ts.min())} → {fmt_t(ts.max())} ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ değerlendirme
def _stats(v: np.ndarray) -> dict:
    v = v[np.isfinite(v)]
    n = len(v)
    if n == 0:
        return {"n": 0}
    sd = float(v.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "mean": float(v.mean()), "t": float(v.mean() / (sd / np.sqrt(n))) if sd > 0 and n > 1 else None}


class Ctx:
    """Eval için ortak veri: olaylar, HA işaretleri, geçerli an dizileri, null motoru."""

    def __init__(self, args):
        cache = Path(args.cache_dir)
        self.syms = list_syms(args.cache_dir, "d5")
        E = load_events(args.cache_dir)
        sid_of = {s: k for k, s in enumerate(self.syms)}
        evs = [e for e in E["events"] if e["keep"]]
        self.ev_sid = np.array([sid_of[e["sym"]] for e in evs]); self.ev_t0 = np.array([e["t0"] for e in evs]); self.ev_end = np.array([e["t_end"] for e in evs])
        ex = pickle.load(open(cache / "sweep_extra.pkl", "rb"))
        self.valid_t = ex["valid_t"]
        self.ha_ticks = pickle.load(open(cache / "ha_ticks.pkl", "rb")) if (cache / "ha_ticks.pkl").exists() else {}
        kk = [(np.full(len(v), k, dtype=np.int64) * KEY_SHIFT + v) for k, v in self.ha_ticks.items()]
        self.ha_keys = np.sort(np.concatenate(kk)) if kk else np.zeros(0, np.int64)
        self.null = NullEngine(args.cache_dir, self.syms)
        self.d0 = parse_day(FIRST_DAY); self.d1 = parse_day("2026-10-17") + 6 * 3_600_000


def summarize(ctx: Ctx, sid, t, out, ivs, *, seeds, n_sample, is_ha=False, ha_eps=None) -> dict:
    m = in_iv(t, ivs)
    sid, t, out = sid[m], t[m], out[m]
    days = iv_days(ivs, ctx.d0, ctx.d1)
    r: dict = {"n": int(len(t)), "per_day": len(t) / days if days else None, "days": days}
    r["hit15"] = _stats(out[:, 0]); r["net15"] = _stats(out[:, 1]); r["hit2"] = _stats(out[:, 2]); r["net2"] = _stats(out[:, 3])
    r["hit4"] = _stats(out[:, 4]); r["trail"] = _stats(out[:, 6])
    if len(t) >= 30:
        ls = [ctx.null.lift(sid, t, out[:, 0].astype(float), out[:, 4].astype(float), n_sample=n_sample, seed=sd, net15=out[:, 1].astype(float), trail=out[:, 6].astype(float)) for sd in seeds]
        ls = [x for x in ls if x.get("n")]
        if ls:
            r["lift15"] = float(np.mean([x["lift15"] for x in ls])); r["null15"] = float(np.mean([x["null15"] for x in ls]))
            r["lift4"] = float(np.mean([x["lift4"] for x in ls])); r["null4"] = float(np.mean([x["null4"] for x in ls]))
            r["lift15_seed_sd"] = float(np.std([x["lift15"] for x in ls], ddof=1)) if len(ls) > 1 else None
            r["lift15_se"] = float(np.mean([x["se15"] for x in ls])); r["lift4_se"] = float(np.mean([x["se4"] for x in ls]))
            for k in ("liftnet", "nullnet", "se_net", "lifttr", "nulltr", "se_tr"):
                r[k] = float(np.mean([x[k] for x in ls]))
    # --- olay yakalama / Hız Avcısı ile öncelik
    key = sid.astype(np.int64) * KEY_SHIFT + t
    o = np.argsort(key); key = key[o]
    msk = in_iv(ctx.ev_t0, ivs)
    es, e0, e1 = ctx.ev_sid[msk], ctx.ev_t0[msk], ctx.ev_end[msk]
    r["events_n"] = int(msk.sum())
    if msk.sum() and len(key):
        k0 = es.astype(np.int64) * KEY_SHIFT + e0; k1 = es.astype(np.int64) * KEY_SHIFT + e1
        j = np.searchsorted(key, k0, side="left")
        got = (j < len(key)) & (key[np.minimum(j, len(key) - 1)] <= k1)
        r["events_caught"] = float(got.mean())
        # null: aynı sembolde aynı sayıda rastgele geçerli an
        rng = np.random.default_rng(5)
        cnt = collections.Counter(sid.tolist())
        tot = []
        for _ in range(5):
            hit = 0
            for s_ in np.unique(es):
                k_ = cnt.get(int(s_), 0); vt = ctx.valid_t.get(int(s_))
                if not k_ or vt is None or len(vt) == 0:
                    continue
                vt = vt[in_iv(vt, ivs)]
                if len(vt) == 0:
                    continue
                ts = np.sort(rng.choice(vt, size=min(k_, len(vt)), replace=False))
                mm = es == s_
                jj = np.searchsorted(ts, e0[mm], side="left")
                hit += int(((jj < len(ts)) & (ts[np.minimum(jj, len(ts) - 1)] <= e1[mm])).sum())
            tot.append(hit / msk.sum())
        r["events_caught_null"] = float(np.mean(tot))
        if len(ctx.ha_keys):
            hj = np.searchsorted(ctx.ha_keys, k0, side="left")
            hd = np.where(hj < len(ctx.ha_keys), ctx.ha_keys[np.minimum(hj, len(ctx.ha_keys) - 1)] - k0, 10 ** 18)
            ha_got = hd <= LOOK_MS
            both = got & ha_got
            r["events_ha_caught"] = float(ha_got.mean())
            r["events_both_n"] = int(both.sum())
            if both.any():
                lead = (ctx.ha_keys[hj[both]] - key[j[both]]) / 60_000.0
                r["events_lead_med"] = float(np.median(lead)); r["events_lead_earlier"] = float(np.mean(lead > 0))
    if len(ctx.ha_keys) and len(key) and not is_ha:
        hj = np.searchsorted(ctx.ha_keys, key, side="right")
        d = np.where(hj < len(ctx.ha_keys), ctx.ha_keys[np.minimum(hj, len(ctx.ha_keys) - 1)] - key, 10 ** 18)
        ok = d <= LOOK_MS
        r["ha_after_share"] = float(ok.mean()); r["ha_lead_med"] = float(np.median(d[ok]) / 60_000.0) if ok.any() else None
    return r


def _eval_pattern(job):
    args, p, periods, ha_periods = job
    ctx = _CTX_CACHE.get("ctx") or _CTX_CACHE.setdefault("ctx", Ctx(args))
    z = np.load(Path(args.out_dir) / "sig" / (p["key"].replace("|", "_") + ".npz"))
    res = {}
    for name, (ivs, seeds, ns) in periods.items():
        res[name] = summarize(ctx, z["sid"], z["t"], z["out"], ivs, seeds=seeds, n_sample=ns)
    return p["key"], res


_CTX_CACHE: dict = {}


def stage_eval(args) -> None:
    from multiprocessing import Pool
    out = Path(args.out_dir)
    end_ms = parse_day("2026-10-17", end=True)
    sets, blocks = make_sets(end_ms)
    pats = json.loads((out / "patterns.json").read_text(encoding="utf-8"))
    seeds3 = (11, 22, 33); seeds1 = (11,)
    t0 = time.time()
    # HA (ana süreçte)
    ctx = Ctx(args)
    zh = np.load(out / "ha.npz")
    ha = {}
    for sk, S in sets.items():
        ha[f"{sk}_train"] = summarize(ctx, zh["sid"], zh["t"], zh["out"], S["train"], seeds=seeds3, n_sample=3000, is_ha=True)
        ha[f"{sk}_test"] = summarize(ctx, zh["sid"], zh["t"], zh["out"], S["test"], seeds=seeds3, n_sample=3000, is_ha=True)
    for bk, ivs in blocks.items():
        ha[bk] = summarize(ctx, zh["sid"], zh["t"], zh["out"], ivs, seeds=seeds1, n_sample=2000, is_ha=True)
    print(f"[eval] HA hazır ({time.time() - t0:.0f} sn)", flush=True)
    jobs = []
    for p in pats:
        S = sets[p["set"]]
        periods = {"train": (S["train"], seeds3, 3000), "test": (S["test"], seeds3, 3000)}
        for bk, ivs in blocks.items():
            periods[bk] = (ivs, seeds1, 2000)
        jobs.append((args, p, periods, None))
    res = {}
    with Pool(max(1, args.workers)) as pool:
        for k, (key, r) in enumerate(pool.imap_unordered(_eval_pattern, jobs, chunksize=1)):
            res[key] = r
            if (k + 1) % 5 == 0:
                print(f"[eval] {k + 1}/{len(jobs)} ({time.time() - t0:.0f} sn)", flush=True)
    ex = pickle.load(open(Path(args.cache_dir) / "sweep_extra.pkl", "rb"))
    (out / "backtest.json").write_text(json.dumps({"ha": ha, "patterns": res, "lunatry": ex["lunatry"]}, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"[eval] yazıldı ({time.time() - t0:.0f} sn)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="analyze,sweep,ha,eval")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", default="work/pattern90")
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-perm", type=int, default=500)
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
