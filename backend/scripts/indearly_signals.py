"""Erken uyarı çalışması — 2. yarı: aday sinyal seçimi (yalnız fold-B EĞİTİM), süpürme, değerlendirme, rapor (2026-10-17, çevrimdışı).

`indearly_study.py` aşamalarının (feat, snap, rank) çıktılarını kullanır. Canlı koda bağlanmaz.
"""
from __future__ import annotations

import collections
import json
import pickle
import time
from pathlib import Path

import numpy as np

from app.rescan import exit_sim as XS
from app.rescan import pattern_study as P
from scripts import indearly_study as S1
from scripts.pattern90_analysis import NullEngine, cooldown_idx
from scripts.pattern90_study import DAY_MS, MIN_QUOTE, WARM_BARS, day_idx, fmt_t, list_syms, parse_day

NEED = ["5m.qv24_log10", "5m.rsi14", "1m.rsi14", "5m.tk_share3", "1m.tk_share_z3", "1m.tk_net12"]
AHEAD_MS = 3_600_000                         # "60 dk içinde olay başlıyor"
POS_BARS = 13                                # t0−60 dk … t0 (13 karar barı)
SIG_COOLDOWN = 12
FIRST_DAY = "2026-07-20"
LUNA_T0 = 1792188000000                      # LUNATRY 2026-10-17 01:00 olayı
SPECS = [XS.ExitSpec("TP1.5 SL3 T60", "fixed", sl=3.0, time_min=60, tp=1.5),
         XS.ExitSpec("TP2.0 SL3 T60", "fixed", sl=3.0, time_min=60, tp=2.0),
         XS.ExitSpec("iz act1.0 gap0.8 SL3 T60", "trail", sl=3.0, time_min=60, act=1.0, gap=0.8)]
DELAY_S = 60
SLIP = 0.15
GUIDE = ["sweep_reclaim (düşük süpürme + geri alma ≤3 bar)", "sweep_eql (eşit diplerin süpürülmesi)", "fvg_bull_tap (yükseliş FVG teması)",
         "ob_tap (yükseliş OB teması)", "acc_div_obv (OBV↑, fiyat yatay)", "acc_div_cmf (CMF↑, fiyat yatay)", "acc_div_cvd (CVD↑, fiyat yatay)",
         "squeeze_release (sıkışma son 6 barda bitti)", "chop_drop (choppiness yüksekten düşüyor)", "st_cluster_flip (3 SuperTrend kümesi yukarı döndü)",
         "vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar)", "fisher_turn (Fisher < −1 ve yukarı dönüyor)", "tsi_turn (TSI düşük bölgede sinyali yukarı kesti)"]


def short(nm: str) -> str:
    return nm.split(" ")[0]


# ------------------------------------------------------------------------------------------------ ortak yükleme
class Env:
    """Sembol listesi, özellik adları, olaylar, geçerli an maskesi yardımcıları."""

    def __init__(self, args):
        self.args = args
        self.cache = Path(args.cache_dir)
        self.fx = Path(args.fx_dir)
        self.syms = list_syms(args.cache_dir, "d5")
        self.sid_of = {s: k for k, s in enumerate(self.syms)}
        self.names = json.loads((self.fx / "fx_names.json").read_text(encoding="utf-8"))
        self.col = {nm: i for i, nm in enumerate(self.names)}
        gn = json.loads((self.cache / "grid_names.json").read_text(encoding="utf-8"))
        self.gn = gn
        self.gneed = [gn.index(x) for x in NEED]
        E = pickle.load(open(self.cache / "events.pkl", "rb"))
        self.events = E["events"]
        self.masks = E["masks"]
        self.ev_by_sym: dict[int, list[dict]] = collections.defaultdict(list)
        for e in self.events:
            self.ev_by_sym[self.sid_of[e["sym"]]].append(e)
        self.thr = np.log10(MIN_QUOTE)

    def valid(self, s: str):
        """(ot, t_dec, v): pattern90 süpürmesiyle aynı geçerlilik (ısınma, likidite, 1 dk/5 dk özellikleri sonlu)."""
        Gm = np.load(self.cache / "grid" / f"G_{s}.npy", mmap_mode="r")
        ot = np.load(self.cache / "grid" / f"OT_{s}.npy")
        sub = np.asarray(Gm[:, self.gneed])
        n = len(ot)
        v = (np.arange(n) >= WARM_BARS) & (sub[:, 0] >= self.thr) & np.isfinite(sub[:, 1:]).all(axis=1)
        return ot, ot + P.BAR_5M_MS, v

    def cov(self, sid: int, n: int) -> np.ndarray:
        cov = np.zeros(n, dtype=bool)
        idx, es = self.masks[self.syms[sid]]
        for st, e in zip(idx, es):
            cov[max(st - 1, 0): min(n, st + int(e) + 1)] = True
        return cov


# ------------------------------------------------------------------------------------------------ aday seçimi (yalnız eğitim)
FAM_SETS = {"all": None, "osc+ma": {"osc", "ma"}, "flow+loc": {"flow", "loc"}, "smc+trend+vol": {"smc", "trend", "vol"}}


def build_train(env: Env, seed: int, p_neg: float = 0.12):
    per = S1.periods()
    lo, hi = per["train"][0]
    rng = np.random.default_rng(seed)
    Xs, ys, evid, tms, sids, Gs = [], [], [], [], [], []
    n_valid = 0
    n_ev_pos = 0
    for sid, s in enumerate(env.syms):
        ot, t_dec, v = env.valid(s)
        n = len(ot)
        cand = v & (t_dec >= lo) & (t_dec <= hi)
        if not cand.any():
            continue
        pos = np.zeros(n, dtype=bool)
        eid = np.full(n, -1, dtype=np.int64)
        for e in env.ev_by_sym.get(sid, []):
            a, b = max(e["s"] - POS_BARS, 0), e["s"]            # i ∈ [s−13, s−1]
            pos[a:b] = True
            eid[a:b] = id(e) % (1 << 40)
        cov = env.cov(sid, n)
        neg = cand & ~pos & ~cov
        pos &= cand
        n_valid += int(cand.sum())
        take = pos | (neg & (rng.random(n) < p_neg))
        ii = np.flatnonzero(take)
        if len(ii) == 0:
            continue
        FX = np.load(env.fx / f"FX_{s}.npy", mmap_mode="r")
        Xs.append(np.asarray(FX[ii]))
        Gs.append(np.asarray(np.load(env.cache / "grid" / f"G_{s}.npy", mmap_mode="r")[ii]))
        ys.append(pos[ii])
        evid.append(np.where(pos[ii], eid[ii], -1))
        tms.append(t_dec[ii])
        sids.append(np.full(len(ii), sid))
    X = np.vstack(Xs)
    y = np.concatenate(ys)
    ev = np.concatenate(evid)
    days = (hi - lo) / DAY_MS
    return {"X": X, "G": np.vstack(Gs), "y": y, "evid": ev, "t": np.concatenate(tms), "sid": np.concatenate(sids), "n_valid": n_valid, "p_neg": p_neg,
            "valid_per_day": n_valid / days, "days": days}


def make_conds(X: np.ndarray, y: np.ndarray, cols: list[int], qs=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)):
    """Her özellik için pozitif-dağılım kuantillerinde (iki yön) eşik koşulları; Boolean matris (n, C)."""
    conds = []
    pos = X[y]
    for j in cols:
        pv = pos[:, j]
        pv = pv[np.isfinite(pv)]
        if len(pv) < 30:
            continue
        ths = np.unique(np.quantile(pv, qs))
        for th in ths:
            conds.append((j, ">", float(th)))
            conds.append((j, "<=", float(th)))
    M = np.zeros((len(X), len(conds)), dtype=bool)
    for c, (j, op, th) in enumerate(conds):
        x = X[:, j]
        with np.errstate(invalid="ignore"):
            M[:, c] = (x > th) if op == ">" else (x <= th)
    return conds, M


def greedy_select(conds, M, y, evid, *, max_terms, ev_recall_min, valid_per_day, p_neg, spd_max=400.0, spd_min=15.0):
    """Açgözlü AND: her adımda olasılık-oranı (LR = TPR/FPR) en yüksek koşul; kısıtlar: olay-düzeyi geri çağırma ≥ ev_recall_min,
    tahmini sinyal/gün ∈ [spd_min, spd_max]. Dönüş: seçilen koşul indeksleri + eğitim ölçüleri."""
    n_pos = int(y.sum())
    n_neg = int((~y).sum())
    ev_ids = np.unique(evid[y])
    ev_pos_map = {e: k for k, e in enumerate(ev_ids)}
    ev_idx = np.array([ev_pos_map[e] for e in evid[y]])
    pos_rows = np.flatnonzero(y)
    cur = np.ones(len(y), dtype=bool)
    chosen: list[int] = []
    hist = []
    for step in range(max_terms):
        rows = np.flatnonzero(cur)
        Mc = M[rows]
        yc = y[rows]
        tp = Mc[yc].sum(axis=0)
        fp = Mc[~yc].sum(axis=0)
        tpr = tp / n_pos
        fpr = (fp + 1.0) / (n_neg + 1.0)
        spd = fpr * valid_per_day                           # tahmini sinyal/gün (cooldown öncesi üst sınır)
        # olay-düzeyi geri çağırma (pozitif satırlar olay başına bitişik): olay başına herhangi bir bar tetiklediyse sayılır
        pr_ev = ev_idx[np.searchsorted(pos_rows, rows[yc])]
        if len(pr_ev):
            bounds = np.flatnonzero(np.r_[True, pr_ev[1:] != pr_ev[:-1]])
            evrec = np.maximum.reduceat(Mc[yc].astype(np.uint8), bounds, axis=0).sum(axis=0) / len(ev_ids)
        else:
            evrec = np.zeros(M.shape[1])
        ok = (evrec >= ev_recall_min) & (spd <= spd_max) & (spd >= spd_min) & (tp >= 15)
        if step > 0:
            ok &= ~np.isin(np.arange(M.shape[1]), chosen)
        if not ok.any():
            break
        lr = np.where(ok, tpr / fpr, -1.0)
        b = int(np.argmax(lr))
        chosen.append(b)
        cur = cur & M[:, b]
        hist.append({"cond": conds[b], "lr": float(lr[b]), "tpr": float(tpr[b]), "ev_recall": float(evrec[b]), "spd": float(spd[b])})
    return chosen, hist


def stage_select(args) -> None:
    env = Env(args)
    t0 = time.time()
    tr = build_train(env, args.seed)
    y, evid = tr["y"], tr["evid"]
    X = np.hstack([tr["X"], tr["G"]])           # kütüphane (401) + MEVCUT özellikler (154, "g:" önekli) — kontrol adayları için
    del tr["X"], tr["G"]
    names = env.names + ["g:" + x for x in env.gn]
    S1.I.feature_names("5m")                    # FAMILY sözlüğünü doldurur
    fam = {nm: ("existing" if nm.startswith("g:") else S1.I.FAMILY.get(nm.split(".", 1)[1], "?")) for nm in names}
    LIB = {"ma", "flow", "osc", "trend", "vol", "loc", "smc"}
    print(f"[select] eğitim: {len(X)} satır, pozitif {int(y.sum())}, olay {len(np.unique(evid[y]))}, geçerli an/gün {tr['valid_per_day']:.0f} ({time.time() - t0:.0f} sn)", flush=True)
    nanfr = np.isnan(X).mean(axis=0)
    # tek özellik AUC (çubuk düzeyi)
    auc = np.concatenate([P.auc_matrix(np.nan_to_num(X[:, a: a + 40].astype(np.float64), nan=0.0), y.astype(float)) for a in range(0, X.shape[1], 40)])
    ok_feat = nanfr < 0.25
    top_all = [int(j) for j in np.argsort(-np.abs(auc - 0.5)) if ok_feat[j]]
    summary = {"top_auc": [(names[j], float(auc[j])) for j in top_all[:30]], "n_train_rows": int(len(X)), "n_pos": int(y.sum()),
               "n_events": int(len(np.unique(evid[y]))), "valid_per_day": tr["valid_per_day"], "p_neg": tr["p_neg"]}
    cands = []

    def run(label, fams, max_terms, evmin, K, idp="C"):
        fams = LIB if fams is None else fams
        cols = [j for j in top_all if fam[names[j]] in fams][:K]
        conds, M = make_conds(X, y, cols)
        ch, hist = greedy_select(conds, M, y, evid, max_terms=max_terms, ev_recall_min=evmin, valid_per_day=tr["valid_per_day"], p_neg=tr["p_neg"], spd_max=args.spd_max)
        if not ch:
            print(f"[select] {label}: aday yok", flush=True)
            return
        cl = [{"feature": names[conds[c][0]], "op": conds[c][1], "value": conds[c][2]} for c in ch]
        cands.append({"id": f"{idp}{sum(1 for c in cands if c['id'][0] == idp) + 1}", "label": label, "conditions": cl, "train": hist[-1], "steps": hist})
        print(f"[select] {label}: " + " & ".join(f"{c['feature']} {c['op']} {c['value']:.4g}" for c in cl)
              + f"  (LR {hist[-1]['lr']:.1f}, TPR {hist[-1]['tpr']:.3f}, olay geri çağ. {hist[-1]['ev_recall']:.2f}, ~{hist[-1]['spd']:.0f} sinyal/gün)", flush=True)

    run("tek koşul (tüm aileler)", None, 1, 0.10, 60)
    run("2 koşul (tüm aileler)", None, 2, 0.08, 60)
    run("3 koşul (tüm aileler)", None, 3, 0.06, 60)
    run("2 koşul: osilatör + hareketli ortalama", FAM_SETS["osc+ma"], 2, 0.08, 50)
    run("2 koşul: akış (hacim/CVD) + konum (VWAP/POC)", FAM_SETS["flow+loc"], 2, 0.08, 50)
    run("2 koşul: yapı (SMC) + trend + oynaklık", FAM_SETS["smc+trend+vol"], 2, 0.08, 50)
    run("KONTROL tek koşul (yalnız MEVCUT 154 özellik)", {"existing"}, 1, 0.10, 60, "X")
    run("KONTROL 2 koşul (yalnız MEVCUT 154 özellik)", {"existing"}, 2, 0.08, 60, "X")
    run("KONTROL 3 koşul (yalnız MEVCUT 154 özellik)", {"existing"}, 3, 0.06, 60, "X")
    out = {"summary": summary, "cands": cands}
    (Path(args.out_dir) / "cands.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[select] {len(cands)} aday yazıldı ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ süpürme
def guide_masks(env: Env, FX: np.ndarray, qb: dict, defs: dict) -> dict[str, np.ndarray]:
    out = {}
    for nm in GUIDE:
        fn = defs[nm]
        out[nm] = np.nan_to_num(S1.eval_idea(fn, FX, env.col, qb).astype(np.float32), nan=0.0) > 0
    return out


def stage_sweep(args) -> None:
    env = Env(args)
    out = Path(args.out_dir)
    (out / "sig").mkdir(parents=True, exist_ok=True)
    cd = json.loads((out / "cands.json").read_text(encoding="utf-8"))["cands"]
    snap0 = S1.load_snap(args.fx_dir, 0)
    qb = S1.idea_quantiles(snap0["XB"], env.col, "5m")
    defs = S1.idea_defs("5m")
    del snap0
    acc = {c["id"]: {"sid": [], "row": [], "t": [], "out": []} for c in cd}
    acc.update({"G:" + short(g): {"sid": [], "row": [], "t": [], "out": []} for g in GUIDE})
    lun: dict[str, list[str]] = {k: [] for k in acc}
    valid_t: dict[int, np.ndarray] = {}
    t0 = time.time()
    lw = (parse_day("2026-10-17"), parse_day("2026-10-17") + 4 * 3_600_000)
    for sid, s in enumerate(env.syms):
        ot, t_dec, v = env.valid(s)
        valid_t[sid] = t_dec[v]
        FX = np.load(env.fx / f"FX_{s}.npy")
        OS = np.load(env.cache / "grid" / f"OS_{s}.npy")
        masks = {}
        Gm = np.load(env.cache / "grid" / f"G_{s}.npy", mmap_mode="r")
        for c in cd:
            m = v.copy()
            for cd_ in c["conditions"]:
                fn_ = cd_["feature"]
                x = np.asarray(Gm[:, env.gn.index(fn_[2:])]) if fn_.startswith("g:") else FX[:, env.col[fn_]]
                with np.errstate(invalid="ignore"):
                    m &= (x > cd_["value"]) if cd_["op"] == ">" else (x <= cd_["value"])
            masks[c["id"]] = m
        for g, mk in guide_masks(env, FX, qb, defs).items():
            masks["G:" + short(g)] = mk & v
        for key, m in masks.items():
            idx = np.flatnonzero(m)
            if s == "LUNATRY":
                lun[key] = [fmt_t(int(t_dec[i]), "%H:%M") for i in idx if lw[0] <= t_dec[i] <= lw[1]]
            idx = cooldown_idx(idx, SIG_COOLDOWN)
            if len(idx) == 0:
                continue
            idx = idx[OS[idx, 0] == 1]
            if len(idx) == 0:
                continue
            a = acc[key]
            a["sid"].append(np.full(len(idx), sid, dtype=np.int16))
            a["row"].append(idx.astype(np.int32))
            a["t"].append(t_dec[idx])
            a["out"].append(OS[idx, 1:])
        if (sid + 1) % 50 == 0:
            print(f"[sweep] {sid + 1}/{len(env.syms)} ({time.time() - t0:.0f} sn)", flush=True)
    for key, a in acc.items():
        if a["sid"]:
            sidv = np.concatenate(a["sid"]); tv = np.concatenate(a["t"]); ov = np.concatenate(a["out"]); rv = np.concatenate(a["row"])
            o = np.argsort(tv, kind="stable")
            sidv, tv, ov, rv = sidv[o], tv[o], ov[o], rv[o]
        else:
            sidv = np.zeros(0, np.int16); tv = np.zeros(0, np.int64); ov = np.zeros((0, 9), np.float32); rv = np.zeros(0, np.int32)
        np.savez(out / "sig" / (key.replace(":", "_") + ".npz"), sid=sidv, t=tv, out=ov, row=rv)
    pickle.dump({"valid_t": valid_t, "lunatry": lun}, open(Path(args.fx_dir) / "sweep_extra.pkl", "wb"))
    print(f"[sweep] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ exit_sim
class SimData:
    """Sembol başına ham 1 dk (open_time, o, h, l, c) önbelleği (tek seferde bir sembol)."""

    def __init__(self, cache_dir: str):
        self.dir = Path(cache_dir) / "d1"

    def load(self, s: str):
        p = self.dir / f"{s}.npy"
        if not p.exists():
            return None
        a = np.load(p)
        return a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def sim_many(env: Env, sets: dict[str, tuple[np.ndarray, np.ndarray]], *, delay=DELAY_S, slip=SLIP, specs=SPECS) -> dict[str, np.ndarray]:
    """sets: ad → (sid, t_ms). Dönüş: ad → (N, len(specs)) net % (simüle edilemeyen NaN). Sembol başına 1 dk veri bir kez yüklenir."""
    sd = SimData(env.args.cache_dir)
    res = {k: np.full((len(v[0]), len(specs)), np.nan, dtype=np.float32) for k, v in sets.items()}
    # sembole göre grupla
    by_sym: dict[int, list] = collections.defaultdict(list)
    for k, (sid, t) in sets.items():
        for s_ in np.unique(sid):
            by_sym[int(s_)].append((k, np.flatnonzero(sid == s_)))
    for s_, lst in by_sym.items():
        d = sd.load(env.syms[s_])
        if d is None:
            continue
        ot1, o1, h1, l1, c1 = d
        for k, ii in lst:
            t = sets[k][1][ii]
            ei, ok = XS.entry_index(ot1, t, delay)
            O, H, L, C, ref, cov = XS.gather_windows(ot1, o1, h1, l1, c1, ei, 60)
            use = ok & cov
            if not use.any():
                continue
            for q, sp in enumerate(specs):
                r = XS.simulate(O[use], H[use], L[use], C[use], sp, slip_pct=slip)
                res[k][ii[use], q] = r["net"].astype(np.float32)
    return res


def draw_random(env: Env, sid: np.ndarray, t: np.ndarray, valid_t: dict, mult: int, seed: int, exclude: bool = True):
    """Her sinyal için aynı sembolde `mult` rastgele geçerli an (exclude=True: sinyalden ≥ 2 sa uzak; False: serbest yerleştirme = sayı-eşleşmiş sıfır)."""
    rng = np.random.default_rng(seed)
    rs, rt = [], []
    for s_ in np.unique(sid):
        vt = valid_t.get(int(s_))
        if vt is None or len(vt) == 0:
            continue
        ts = np.sort(t[sid == s_])
        k = int((sid == s_).sum()) * mult
        cand = rng.choice(vt, size=min(len(vt), k * 3 if exclude else k), replace=False)
        if exclude:
            j = np.searchsorted(ts, cand)
            d1 = np.where(j < len(ts), np.abs(ts[np.minimum(j, len(ts) - 1)] - cand), 10 ** 15)
            d2 = np.where(j > 0, np.abs(ts[np.maximum(j - 1, 0)] - cand), 10 ** 15)
            cand = cand[np.minimum(d1, d2) >= 7_200_000]
        cand = cand[:k]
        rs.append(np.full(len(cand), s_, dtype=np.int16)); rt.append(cand)
    if not rs:
        return np.zeros(0, np.int16), np.zeros(0, np.int64)
    return np.concatenate(rs), np.concatenate(rt)


# ------------------------------------------------------------------------------------------------ değerlendirme
def cl_stats(x: np.ndarray, t: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    if m.sum() < 5:
        return {"n": int(m.sum())}
    s = XS.trade_stats(x[m], day_idx(t[m]))
    return {"n": s["n"], "mean": s["mean"], "se": s["se"], "t": s["t"], "win": s["win"]}


def event_arrays(env: Env):
    """Tüm olaylar (kümesiz olmayan): sid, t0, t_end, keep."""
    sid = np.array([env.sid_of[e["sym"]] for e in env.events])
    t0 = np.array([e["t0"] for e in env.events], dtype=np.int64)
    te = np.array([e["t_end"] for e in env.events], dtype=np.int64)
    keep = np.array([bool(e["keep"]) for e in env.events])
    return sid, t0, te, keep


KEYS = 1 << 42


def followed(sid, t, ev_sid, ev_t0, ev_end, *, ahead=AHEAD_MS, active=False):
    """Her sinyal için: aynı sembolde t0 ∈ [t, t+ahead] olan olay var mı (active=True: t'den önce başlamış ama t'de sürmekte olan olay da sayılır:
    t0 ≤ t+ahead ve t_end ≥ t). Sembol başına olaylar ≥ 3 sa arayla olduğundan aday tek olaydır."""
    k = ev_sid.astype(np.int64) * KEYS + ev_t0
    o = np.argsort(k)
    k = k[o]
    te = ev_end[o]
    sid = np.asarray(sid, dtype=np.int64)
    j = np.searchsorted(k, sid * KEYS + t + ahead, side="right") - 1
    jc = np.maximum(j, 0)
    same = (j >= 0) & ((k[jc] // KEYS) == sid)
    if active:
        return same & (te[jc] >= t)
    return same & ((k[jc] % KEYS) >= t)


def first_in_window(keys_sorted, sid_e, lo, hi):
    """Olay başına, [lo, hi] penceresindeki (aynı sembol) ilk anahtar zamanı (yoksa −1)."""
    base = sid_e.astype(np.int64) * KEYS
    j = np.searchsorted(keys_sorted, base + lo, side="left")
    jj = np.minimum(j, len(keys_sorted) - 1)
    ok = (j < len(keys_sorted)) & (keys_sorted[jj] <= base + hi)
    return np.where(ok, keys_sorted[jj] - base, -1)


def stage_eval(args) -> None:
    from scripts.pattern90_analysis import Ctx
    env = Env(args)
    out = Path(args.out_dir)
    ctx = Ctx(args)
    per = S1.periods()
    cd = json.loads((out / "cands.json").read_text(encoding="utf-8"))["cands"]
    ex = pickle.load(open(Path(args.fx_dir) / "sweep_extra.pkl", "rb"))
    valid_t = ex["valid_t"]
    zh = np.load(Path("work/pattern90/ha.npz"))
    ticks = pickle.load(open(env.cache / "ha_ticks.pkl", "rb"))
    ha_keys = np.sort(np.concatenate([np.full(len(v), k, dtype=np.int64) * KEYS + v for k, v in ticks.items()]))
    ev_sid, ev_t0, ev_end, ev_keep = event_arrays(env)
    # --- sinyal kümeleri
    sets = {}
    meta = {}
    for c in cd:
        z = np.load(out / "sig" / f"{c['id']}.npz")
        sets[c["id"]] = (z["sid"].astype(np.int64), z["t"], z["out"])
        meta[c["id"]] = c["label"]
    for g in GUIDE:
        z = np.load(out / "sig" / f"G_{short(g)}.npz")
        sets["G:" + short(g)] = (z["sid"].astype(np.int64), z["t"], z["out"])
        meta["G:" + short(g)] = g
    sets["HA"] = (zh["sid"].astype(np.int64), zh["t"].astype(np.int64), zh["out"])
    meta["HA"] = "Hız Avcısı (canlı-benzeri, bölüm başı)"
    t0 = time.time()
    # --- rastgele girişler (sinyal başına 2) + exit_sim
    sim_in = {}
    rnd_of = {}
    free_of = {}
    for k, (sid, t, o) in sets.items():
        rs, rt = draw_random(env, sid, t, valid_t, 2, args.seed + 1)
        rnd_of[k] = (rs.astype(np.int64), rt)
        fs, ft = draw_random(env, sid, t, valid_t, 1, args.seed + 2, exclude=False)
        free_of[k] = (fs.astype(np.int64), ft)
        sim_in[k] = (sid, t)
        sim_in["R:" + k] = (rs.astype(np.int64), rt)
    # koşulsuz rastgele giriş havuzu (tüm geçerli anlardan tekdüze)
    rng0 = np.random.default_rng(args.seed + 5)
    cnts = np.array([len(valid_t[k]) for k in sorted(valid_t)])
    allsid = np.repeat(np.array(sorted(valid_t)), cnts)
    allt = np.concatenate([valid_t[k] for k in sorted(valid_t)])
    pick = rng0.choice(len(allt), size=min(150_000, len(allt)), replace=False)
    B_sid, B_t = allsid[pick].astype(np.int64), allt[pick]
    sim_in["B0"] = (B_sid, B_t)
    sims = sim_many(env, sim_in)
    print(f"[eval] exit_sim hazır ({time.time() - t0:.0f} sn)", flush=True)
    days_of = lambda ivs: sum(max(0, min(hi, ctx.d1) - max(lo, ctx.d0)) for lo, hi in ivs) / DAY_MS  # noqa: E731
    simB = sims["B0"]
    res = {"meta": meta, "periods": {}, "specs": [s.name for s in SPECS], "base": {}}
    for pn, ivs in per.items():
        mb = S1.in_iv(B_t, ivs)
        rb = {"n": int(mb.sum()), "prec_ahead60": float(followed(B_sid[mb], B_t[mb], ev_sid, ev_t0, ev_end).mean()),
              "prec_any": float(followed(B_sid[mb], B_t[mb], ev_sid, ev_t0, ev_end, active=True).mean())}
        for q in range(len(SPECS)):
            rb[f"sim{q}"] = cl_stats(simB[mb, q], B_t[mb])
        res["base"][pn] = rb
    for k, (sid, t, o) in sets.items():
        rs, rt = rnd_of[k]
        net_s = sims[k]
        net_r = sims["R:" + k]
        # olay yakalama için sıralı anahtarlar
        keys_sig = np.sort(sid * KEYS + t)
        fs, ft = free_of[k]
        r_keys = np.sort(fs * KEYS + ft) if len(fs) else np.zeros(0, np.int64)
        rk = {}
        for pn, ivs in per.items():
            m = S1.in_iv(t, ivs)
            mr = S1.in_iv(rt, ivs)
            n = int(m.sum())
            days = days_of(ivs)
            r = {"n": n, "per_day": n / days if days else None, "days": days}
            if n == 0:
                rk[pn] = r
                continue
            hit_ahead = followed(sid[m], t[m], ev_sid, ev_t0, ev_end)
            hit_any = followed(sid[m], t[m], ev_sid, ev_t0, ev_end, active=True)
            r["prec_ahead60"] = float(hit_ahead.mean())
            r["prec_any"] = float(hit_any.mean())
            if mr.any():
                r["prec_ahead60_rnd"] = float(followed(rs[mr], rt[mr], ev_sid, ev_t0, ev_end).mean())
                r["prec_any_rnd"] = float(followed(rs[mr], rt[mr], ev_sid, ev_t0, ev_end, active=True).mean())
            oo = o[m]
            r["hit15"] = float(np.nanmean(oo[:, 0])); r["net15_opt"] = float(np.nanmean(oo[:, 1])); r["trail_opt"] = float(np.nanmean(oo[:, 6]))
            if n >= 30:
                ls = [ctx.null.lift(sid[m], t[m], oo[:, 0].astype(float), oo[:, 4].astype(float), n_sample=3000, seed=sd, net15=oo[:, 1].astype(float),
                                    trail=oo[:, 6].astype(float)) for sd in (11, 22, 33)]
                ls = [x for x in ls if x.get("n")]
                if ls:
                    r["lift15"] = float(np.mean([x["lift15"] for x in ls])); r["null15"] = float(np.mean([x["null15"] for x in ls]))
                    r["lift15_se"] = float(np.mean([x["se15"] for x in ls]))
                    r["liftnet"] = float(np.mean([x["liftnet"] for x in ls])); r["lift_se_net"] = float(np.mean([x["se_net"] for x in ls]))
            for q, sp in enumerate(SPECS):
                r[f"sim{q}"] = cl_stats(net_s[m, q], t[m])
                r[f"simr{q}"] = cl_stats(net_r[mr, q], rt[mr]) if mr.any() else {"n": 0}
            # --- olay yakalama / öncelik
            msk = S1.in_iv(ev_t0, ivs) & ev_keep
            r["events_n"] = int(msk.sum())
            if msk.sum():
                es, e0, e1 = ev_sid[msk], ev_t0[msk], ev_end[msk]
                ts_early = first_in_window(keys_sig, es, e0 - AHEAD_MS, e0 - 1)          # t0'dan ÖNCE (t0−60 dk … t0−1 sn)
                ts_any = first_in_window(keys_sig, es, e0 - AHEAD_MS, e1)
                tr_early = first_in_window(r_keys, es, e0 - AHEAD_MS, e0 - 1) if len(r_keys) else np.full(len(es), -1)
                r["rec_early"] = float((ts_early >= 0).mean()); r["rec_any"] = float((ts_any >= 0).mean())
                r["rec_early_rnd"] = float((tr_early >= 0).mean()) if len(r_keys) else None
                lead_r = (e0 - tr_early)[tr_early >= 0] / 60_000.0 if len(r_keys) else np.array([])
                r["lead_med_rnd"] = float(np.median(lead_r)) if len(lead_r) else None
                lead = (e0 - ts_early)[ts_early >= 0] / 60_000.0
                r["lead_med_min"] = float(np.median(lead)) if len(lead) else None
                # HA ile karşılaştırma: [t0−60, t0+90 dk] penceresinde ilk HA tıkı
                th = first_in_window(ha_keys, es, e0 - AHEAD_MS, e0 + 90 * 60_000)
                tsw = first_in_window(keys_sig, es, e0 - AHEAD_MS, e0 + 90 * 60_000)
                both = (th >= 0) & (tsw >= 0)
                r["ha_rec_early"] = float((first_in_window(ha_keys, es, e0 - AHEAD_MS, e0 - 1) >= 0).mean())
                r["ha_rec_any"] = float((th >= 0).mean())
                r["both_n"] = int(both.sum())
                if both.any():
                    adv = (th - tsw)[both] / 60_000.0
                    r["adv_vs_ha_med"] = float(np.median(adv)); r["earlier_than_ha"] = float((adv > 0).mean())
                # HA'dan ÖNCE yakalanan ve HA'nın hiç yakalamadığı olaylar
                r["only_sig_n"] = int(((th < 0) & (tsw >= 0)).sum()); r["only_ha_n"] = int(((th >= 0) & (tsw < 0)).sum())
            rk[pn] = r
        res["periods"][k] = rk
    res["lunatry"] = ex["lunatry"]
    # LUNATRY: HA tıkları
    lid = env.sid_of.get("LUNATRY")
    if lid is not None:
        tk = ticks.get(lid, np.array([], dtype=np.int64))
        lo, hi = parse_day("2026-10-17"), parse_day("2026-10-17") + 4 * 3_600_000
        res["lunatry_ha"] = [fmt_t(int(x), "%H:%M") for x in tk if lo <= x <= hi][:12]
    pickle.dump(res, open(out / "eval.pkl", "wb"))
    print(f"[eval] yazıldı ({time.time() - t0:.0f} sn)", flush=True)


from scripts.indearly_report import stage_report  # noqa: E402,F401
