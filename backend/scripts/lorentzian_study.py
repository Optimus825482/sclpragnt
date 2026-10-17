"""Lorentzian Classification (kNN) çalışması - çevrimdışı, DB'ye YAZMAZ, canlı koda bağlanmaz (2026-10-17).

Soru: jdehorty "Lorentzian Classification" ve "bizim etiketli Lorentzian kNN" (varyant B) güçlendirici bir tahmin motoru mu;
HistGradientBoosting'e, Hız Avcısı'na (HA) ve rastgele girişe göre?

Aşamalar (--stages, virgüllü):
  pred5   sembol başına 5 dk: orijinal (pine/future etiket) + varyant B kNN tahminleri + özellikler -> <cache>/pred5/<SYM>.npz   (havuz: --workers)
  hgb     yürüyen ileri HistGradientBoosting (B2 <- B1; B3 <- B1+B2) -> <cache>/hgb/<SYM>.npz
  eval5   sinyal kümeleri x bloklar: hit/lift/net (exit_sim), AUC, HA örtüşmesi/öncelik, HA filtresi -> OUT/results5.pkl
  engine  aynı saatlik örnekte motor karşılaştırması (AUC, ATR-içi AUC, üst-q isabet; havuzlanmış kNN-Lorentzian dâhil) -> OUT/results_engine.pkl
  m1pred  1 dk orijinal (60 likit sembol) -> <cache>/pred1/<SYM>.npz
  eval1   1 dk değerlendirme -> OUT/results1.pkl
  report  OUT/report.md

Kullanım (backend/): python scripts/lorentzian_study.py --stages pred5,hgb,eval5,report
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.rescan import exit_sim as X  # noqa: E402
from app.rescan import lorentzian as L  # noqa: E402

SCRATCH = Path(r"C:\Users\Erkan\AppData\Local\Temp\claude\D--PROJELLER-sclpragnt\bb25c086-ec89-43e9-a810-f345b61672ad\scratchpad")
P90 = SCRATCH / "p90cache"
CACHE = SCRATCH / "lorentzian"
OUT = _BACKEND / "work" / "lorentzian"
MIN_Q = 5_000_000.0
BAR5 = 300_000
BAR1 = 60_000
WARM = 100
DAY_MS = 86_400_000
TZ_MS = 3 * 3_600_000
COOLDOWN = 12                 # aynı sembolde 60 dk içinde tekrar sinyal sayılmaz (HA bölüm kuralı gibi)
MIN_HIST = 300
DELAY_S = 60
SLIP = 0.15
Q_GRID = (0.001, 0.0025, 0.01)   # üst dilim payı (likit bar-an başına)
Q_MAIN = 0.0025
HOLD_DAYS = 5


# ------------------------------------------------------------------------------------------------ ortak
def blocks() -> list[tuple[int, int]]:
    from scripts.indfilter_common import ha_blocks
    return ha_blocks()


BLOCK_NAMES = ("B1 20.07-18.08", "B2 19.08-17.09", "B3 18.09-16.10")


def block_days(b: tuple[int, int]) -> float:
    return (b[1] - b[0] + 1) / DAY_MS


def day_idx(ms) -> np.ndarray:
    return (np.asarray(ms, dtype=np.int64) + TZ_MS) // DAY_MS


def hour_idx(ms) -> np.ndarray:
    return ((np.asarray(ms, dtype=np.int64) + TZ_MS) // 3_600_000) % 24


def roll288(qv: np.ndarray, n: int = 288) -> np.ndarray:
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(qv))])
    out = np.zeros(len(qv))
    i = np.arange(len(qv))
    out = cs[i + 1] - cs[np.maximum(i + 1 - n, 0)]
    return out


def syms5() -> list[str]:
    return sorted(p.stem for p in (P90 / "d5").glob("*.npy"))


def load5(sym: str):
    F5 = np.load(P90 / "grid" / f"F5_{sym}.npy")
    real = np.load(P90 / "grid" / f"RL_{sym}.npy").astype(bool)
    return F5, real


def cooldown(idx: np.ndarray, gap: int = COOLDOWN) -> np.ndarray:
    """Sıralı indeks dizisinde, bir seçimden sonraki `gap` bar içindekileri at (açgözlü)."""
    out = []
    last = -10 ** 9
    for i in idx:
        if i - last > gap:
            out.append(i)
            last = i
    return np.array(out, dtype=np.int64)


# ------------------------------------------------------------------------------------------------ 1. pred5
def _pred5_job(job):
    sym, cache = job
    cache = Path(cache)
    dst = cache / "pred5" / f"{sym}.npz"
    if dst.exists():
        return sym, 0.0
    t0 = time.time()
    F5, real = load5(sym)
    ot = F5[:, 0].astype(np.int64)
    o, h, l, c, qv, tbq = F5[:, 1], F5[:, 2], F5[:, 3], F5[:, 4], F5[:, 6], F5[:, 8]
    n = len(c)
    liq = real & (roll288(qv) >= MIN_Q) & (np.arange(n) >= WARM)
    rf = L.lorentzian(o, h, l, c, label_mode="future", min_hist=MIN_HIST)
    rp = L.lorentzian(o, h, l, c, label_mode="pine", min_hist=MIN_HIST)
    F7 = L.our_features(o, h, l, c, qv, tbq)
    ev, mfe = L.event_label(o, h)
    kb = L.knn_event(F7, ev, min_hist=MIN_HIST)
    c4 = np.full(n, np.nan, dtype=np.float32)
    c4[:-4] = (c[4:] / c[:-4] - 1.0) * 100.0
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez(dst, ot=ot, liq=liq, real=real, pred_f=rf["pred"], pred_p=rp["pred"], sig_f=rf["sig"], sig_p=rp["sig"],
             ent_f=rf["entry_long"], ent_p=rp["entry_long"], filt=rf["filt"], bull=rf["bull"], knn=kb["pred"], knn_d=kb["meand"],
             F7=F7, ev=ev, mfe=mfe, c4=c4)
    return sym, time.time() - t0


def stage_pred5(args) -> None:
    from multiprocessing import Pool
    cache = Path(args.cache_dir)
    (cache / "pred5").mkdir(parents=True, exist_ok=True)
    syms = syms5()
    if args.limit:
        syms = syms[: args.limit]
    t0 = time.time()
    with Pool(max(1, args.workers)) as pool:
        for k, (s, dt) in enumerate(pool.imap_unordered(_pred5_job, [(s, str(cache)) for s in syms], chunksize=1)):
            if (k + 1) % 10 == 0:
                print(f"[pred5] {k + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    print(f"[pred5] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ 2. HistGradientBoosting (yürüyen ileri)
def _hgb_model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=500,
                                          l2_regularization=1.0, early_stopping=False, random_state=17)


def stage_hgb(args) -> None:
    """Test bloğu b (B2, B3): model YALNIZ önceki blok(lar)ın, son HOLD_DAYS gün hariç (+ 12 bar tecrit) satırlarıyla eğitilir;
    eşik, o son HOLD_DAYS günün (modelin hiç görmediği) skor dağılımından alınır. Çıktı: <cache>/hgb/<SYM>_b<2|3>.npy = [test skoru, bekletme skoru]."""
    cache = Path(args.cache_dir)
    (cache / "hgb").mkdir(parents=True, exist_ok=True)
    B = blocks()
    syms = sorted(p.stem for p in (cache / "pred5").glob("*.npz"))
    if args.limit:
        syms = syms[: args.limit]
    D = {}
    for s in syms:
        z = np.load(cache / "pred5" / f"{s}.npz")
        D[s] = (z["ot"], z["liq"], z["ev"], z["F7"])
    t0 = time.time()
    for bi in (1, 2):                                       # test blokları B2, B3
        hold_lo = B[bi - 1][1] + 1 - HOLD_DAYS * DAY_MS
        tr_hi = hold_lo - COOLDOWN * BAR5
        te_lo, te_hi = B[bi]
        Xs, ys = [], []
        for s in syms:
            ot, liq, ev, F = D[s]
            m = liq & (ev >= 0) & np.isfinite(F).all(axis=1) & (ot < tr_hi)
            Xs.append(F[m]); ys.append((ev[m] > 0).astype(np.int8))
        X = np.concatenate(Xs); y = np.concatenate(ys)
        del Xs, ys
        print(f"[hgb] blok {bi + 1}: eğitim {len(y)} satır, olay oranı {y.mean():.4f} ({time.time() - t0:.0f} sn)", flush=True)
        mdl = _hgb_model().fit(X, y)
        del X, y
        print(f"[hgb] blok {bi + 1}: model hazır ({time.time() - t0:.0f} sn)", flush=True)
        for s in syms:
            ot, liq, ev, F = D[s]
            ok = liq & np.isfinite(F).all(axis=1)
            res = np.full((2, len(ot)), np.nan, dtype=np.float32)
            for r, (lo, hi) in enumerate(((te_lo, te_hi), (hold_lo, B[bi - 1][1]))):
                m = ok & (ot >= lo) & (ot <= hi)
                if m.any():
                    res[r, m] = mdl.predict_proba(F[m])[:, 1]
            np.save(cache / "hgb" / f"{s}_b{bi + 1}.npy", res)
    print(f"[hgb] bitti ({time.time() - t0:.0f} sn)", flush=True)



# ------------------------------------------------------------------------------------------------ 3. değerlendirme (5 dk)
KEYS = 1 << 42
EXITS = {"tp": X.ExitSpec("TP1.5/SL3/T60", "fixed", sl=3.0, time_min=60, tp=1.5),
         "tr": X.ExitSpec("iz act1 gap0.8 SL3 T60", "trail", sl=3.0, time_min=60, act=1.0, gap=0.8)}
HIT_PCT = 1.5


def kscore(knn: np.ndarray, knn_d: np.ndarray) -> np.ndarray:
    """Tam sayı komşu sayısı + (aynı sayıda) daha yakın komşuları öne alan küçük ince ayar (0..0.5)."""
    return knn + 0.5 * (1.0 - np.clip(knn_d / 3.5, 0.0, 1.0))


def load_light(cache: Path, sym: str) -> dict:
    z = np.load(cache / "pred5" / f"{sym}.npz")
    d = {k: z[k] for k in ("ot", "liq", "ev", "c4", "pred_f", "pred_p", "sig_f", "sig_p", "ent_f", "ent_p", "knn", "knn_d")}
    d["ks"] = kscore(d["knn"], d["knn_d"]).astype(np.float32)
    d["atr"] = z["F7"][:, 0].astype(np.float32)
    n = len(d["ot"])
    p2, p3 = cache / "hgb" / f"{sym}_b2.npy", cache / "hgb" / f"{sym}_b3.npy"
    h2 = np.load(p2) if p2.exists() else np.full((2, n), np.nan, np.float32)
    h3 = np.load(p3) if p3.exists() else np.full((2, n), np.nan, np.float32)
    d["hgb"] = np.where(np.isfinite(h2[0]), h2[0], h3[0]).astype(np.float32)
    d["hold"] = [None, h2[1], h3[1]]
    return d


def block_mask(ot: np.ndarray, b: tuple[int, int]) -> np.ndarray:
    return (ot >= b[0]) & (ot <= b[1])


def pass1(cache: Path, syms: list[str], B) -> dict:
    """Bar düzeyi: AUC (olay + 4 bar yön), eşikler (önceki blok kNN dağılımı; bekletme HGB dağılımı), pred>0 yön doğruluğu."""
    from scripts.indfilter_common import auc_score
    names = ("pred_f", "pred_p", "ks", "hgb")
    acc = {bi: {k: [] for k in names + ("ev", "c4", "sig_f")} for bi in range(3)}
    ks_all = {bi: [] for bi in range(3)}
    hold_all = {1: [], 2: []}
    for s in syms:
        d = load_light(cache, s)
        ot, liq = d["ot"], d["liq"]
        for bi, b in enumerate(B):
            m = liq & block_mask(ot, b)
            if m.any():
                for k in names:
                    acc[bi][k].append(d[k][m])
                acc[bi]["ev"].append(d["ev"][m]); acc[bi]["c4"].append(d["c4"][m]); acc[bi]["sig_f"].append(d["sig_f"][m])
                ks_all[bi].append(d["ks"][m & np.isfinite(d["knn"])])
            if bi >= 1 and d["hold"][bi] is not None:
                hv = d["hold"][bi][liq & np.isfinite(d["hold"][bi])]
                if len(hv):
                    hold_all[bi].append(hv)
    res: dict = {"auc": {}, "bar": {}, "thr": {"ks": {}, "hgb": {}}}
    for bi in range(3):
        A = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in acc[bi].items()}
        evm = A["ev"] >= 0
        upm = np.isfinite(A["c4"]) & (A["c4"] != 0)
        res["bar"][bi] = {"n_liq": int(len(A["ev"])), "ev_rate": float((A["ev"][evm] > 0).mean()), "up_rate": float((A["c4"][upm] > 0).mean())}
        for k in names:
            sc = A[k]
            fin = np.isfinite(sc)
            r = {}
            m1 = fin & evm
            r["auc_ev"] = auc_score(sc[m1], A["ev"][m1] > 0) if m1.sum() > 1000 else float("nan")
            r["n_ev"] = int(m1.sum())
            m2 = fin & upm
            r["auc_up"] = auc_score(sc[m2], A["c4"][m2] > 0) if m2.sum() > 1000 else float("nan")
            if k in ("pred_f", "pred_p"):
                pos = fin & upm & (sc > 0)
                neg = fin & upm & (sc < 0)
                r["n_pos"] = int(pos.sum()); r["n_neg"] = int(neg.sum())
                r["acc_pos"] = float((A["c4"][pos] > 0).mean()) if pos.any() else float("nan")
                r["acc_neg"] = float((A["c4"][neg] < 0).mean()) if neg.any() else float("nan")
                e1 = fin & evm & (sc > 0)
                e0 = fin & evm & (sc <= 0)
                r["ev_pos"] = float((A["ev"][e1] > 0).mean()) if e1.any() else float("nan")
                r["ev_nonpos"] = float((A["ev"][e0] > 0).mean()) if e0.any() else float("nan")
            res["auc"][(bi, k)] = r
        if bi >= 1:
            v = np.concatenate(ks_all[bi - 1]) if ks_all[bi - 1] else np.zeros(0)
            res["thr"]["ks"][bi] = {q: float(np.quantile(v, 1 - q)) for q in Q_GRID + (0.2,)} if len(v) else {}
            h = np.concatenate(hold_all[bi]) if hold_all[bi] else np.zeros(0)
            res["thr"]["hgb"][bi] = {q: float(np.quantile(h, 1 - q)) for q in Q_GRID + (0.2,)} if len(h) else {}
    return res


def draw_random(cand_idx: np.ndarray, cand_hour: np.ndarray, sig_hour: np.ndarray, rng, mult: int = 2) -> np.ndarray:
    """Her sinyal için aynı sembolde, aynı saat diliminden `mult` rastgele aday indeksi (aday yoksa atlanır)."""
    out = []
    for h in np.unique(sig_hour):
        pool = cand_idx[cand_hour == h]
        k = int((sig_hour == h).sum()) * mult
        if len(pool) and k:
            out.append(rng.choice(pool, size=k, replace=len(pool) < k))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def draw_random_vm(cand_idx: np.ndarray, cand_hour: np.ndarray, cand_atr: np.ndarray, sig_hour: np.ndarray, sig_atr: np.ndarray,
                   rng, mult: int = 2, tol: float = 0.25, min_pool: int = 8) -> np.ndarray:
    """Hacim/oynaklık-eşleşmiş taban: aynı sembol + aynı blok + aynı saat + 5 dk ATR% (+-%25; < min_pool aday ise en yakın min_pool)."""
    out = []
    for h in np.unique(sig_hour):
        m = cand_hour == h
        pool, pa = cand_idx[m], cand_atr[m]
        okp = np.isfinite(pa) & (pa > 0)
        pool, pa = pool[okp], pa[okp]
        if len(pool) == 0:
            continue
        for a in sig_atr[sig_hour == h]:
            if not (np.isfinite(a) and a > 0):
                continue
            r = np.abs(pa / a - 1.0)
            ins = np.flatnonzero(r <= tol)
            if len(ins) < min_pool:
                ins = np.argsort(np.abs(np.log(pa / a)), kind="stable")[:min_pool]
            out.append(rng.choice(pool[ins], size=mult, replace=len(ins) < mult))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


SET_ORDER = ["OL-pine", "OL-future"] + [f"kNN-B q{q * 100:g}%" for q in Q_GRID] + [f"HGB q{q * 100:g}%" for q in Q_GRID] + ["HA"]


def make_sets(d: dict, B, thr: dict, ha_idx: np.ndarray) -> dict[str, np.ndarray]:
    """Sembol için küme -> 5 dk karar çubuğu indeksleri (60 dk soğuma uygulanmış). HA: kapanmış son çubuk indeksi (soğuma YOK)."""
    ot, liq = d["ot"], d["liq"]
    inblk = np.zeros(len(ot), dtype=bool)
    for b in B:
        inblk |= block_mask(ot, b)
    sets: dict[str, np.ndarray] = {}
    for nm, ent, pr in (("OL-pine", d["ent_p"], d["pred_p"]), ("OL-future", d["ent_f"], d["pred_f"])):
        m = ent.astype(bool) & liq & inblk & np.isfinite(pr)
        sets[nm] = cooldown(np.flatnonzero(m))
        sets[nm + "|raw"] = np.flatnonzero(m)
    for kind, key in (("kNN-B", "ks"), ("HGB", "hgb")):
        for q in Q_GRID:
            nm = f"{kind} q{q * 100:g}%"
            idx = []
            for bi, b in enumerate(B):
                if bi == 0 or q not in thr[key].get(bi, {}):
                    continue
                m = liq & block_mask(ot, b) & np.isfinite(d[key]) & (d[key] >= thr[key][bi][q])
                idx.append(cooldown(np.flatnonzero(m)))
            sets[nm] = np.concatenate(idx) if idx else np.zeros(0, dtype=np.int64)
    sets["HA"] = ha_idx
    return sets


def simulate_rows(ot1, o1, h1, l1, c1, t_dec: np.ndarray) -> dict:
    ei, ok = X.entry_index(ot1, t_dec, DELAY_S)
    O, H, L, C, ref, cov = X.gather_windows(ot1, o1, h1, l1, c1, ei, 60)
    use = ok & cov
    n = len(t_dec)
    out = {"use": use, "hit": np.full(n, np.nan), "tp": np.full(n, np.nan), "tr": np.full(n, np.nan)}
    if use.any():
        Ou, Hu, Lu, Cu = O[use], H[use], L[use], C[use]
        out["hit"][use] = ((Hu.max(axis=1).astype(float) - 1.0) * 100.0 >= HIT_PCT).astype(float)
        for k, sp in EXITS.items():
            out[k][use] = X.simulate(Ou, Hu, Lu, Cu, sp, slip_pct=SLIP)["net"]
    return out


def agg(R: dict, set_id: int, bi: int, days: float) -> dict:
    """Bir küme x blok için özet; R: satır dizileri (set, blk, kind, day, up, hit, tp, tr)."""
    m = (R["set"] == set_id) & (R["blk"] == bi)
    sg = m & (R["kind"] == 0)
    rn = m & (R["kind"] == 1)
    rv = m & (R["kind"] == 2)
    out = {"n": int(sg.sum()), "per_day": float(sg.sum()) / days, "n_rnd": int(rn.sum()), "n_rndv": int(rv.sum())}
    if sg.sum() < 5 or rn.sum() < 5:
        return out
    day = R["day"]

    def cs(x, msk):
        fin = np.isfinite(x[msk])
        v = x[msk][fin]
        return X.trade_stats(v, day[msk][fin]) if len(v) > 4 else {"n": len(v)}

    for key in ("up", "hit"):
        a, b = cs(R[key] * 100.0, sg), cs(R[key] * 100.0, rn)
        out[key] = a.get("mean"); out[key + "_rnd"] = b.get("mean")
        out[key + "_diff"] = X.diff_stats(a, b)
        if rv.sum() >= 5:
            c = cs(R[key] * 100.0, rv)
            out[key + "_rndv"] = c.get("mean")
            out[key + "_diffv"] = X.diff_stats(a, c)
    for key in ("tp", "tr"):
        a, b = cs(R[key], sg), cs(R[key], rn)
        out[key] = a; out[key + "_rnd"] = b
        out[key + "_diff"] = X.diff_stats(a, b)
        if rv.sum() >= 5:
            c = cs(R[key], rv)
            out[key + "_rndv"] = c
            out[key + "_diffv"] = X.diff_stats(a, c)
    return out


def near(keys: np.ndarray, sid: np.ndarray, t: np.ndarray, lo: int, hi: int) -> tuple[np.ndarray, np.ndarray]:
    """sid/t için [t+lo, t+hi] aralığında (aynı sembol) ilk anahtar var mı ve ilk anahtarın zamanı (yoksa -1)."""
    base = sid.astype(np.int64) * KEYS
    j = np.searchsorted(keys, base + t + lo, side="left")
    jc = np.minimum(j, len(keys) - 1)
    ok = (j < len(keys)) & (keys[jc] <= base + t + hi)
    return ok, np.where(ok, keys[jc] - base, -1)


def stage_eval5(args) -> None:
    cache = Path(args.cache_dir)
    B = blocks()
    syms = sorted(p.stem for p in (cache / "pred5").glob("*.npz"))
    if args.limit:
        syms = syms[: args.limit]
    sid_of = {s: i for i, s in enumerate(syms)}
    t0 = time.time()
    P1 = pass1(cache, syms, B)
    print(f"[eval5] bar düzeyi hazır ({time.time() - t0:.0f} sn)", flush=True)
    # --- HA olayları
    E = pickle.load(open(_BACKEND / "work" / "indfilter" / "events_ha.pkl", "rb"))
    ev_sym = np.asarray(E["sym"]); ev_t = np.asarray(E["t_ms"], dtype=np.int64)
    n_ev = len(ev_t)
    ha_feat = {k: np.full(n_ev, np.nan) for k in ("pred_f", "pred_p", "sig_f", "sig_p", "ks", "hgb", "liq")}
    rng = np.random.default_rng(args.seed)
    set_names = SET_ORDER
    rows: dict[str, list] = {k: [] for k in ("set", "blk", "kind", "sid", "t", "day", "up", "hit", "tp", "tr")}
    raw_counts: dict[tuple, int] = {}
    syms_with_1m = 0
    for si, s in enumerate(syms):
        d = load_light(cache, s)
        ot, liq = d["ot"], d["liq"]
        ei_s = np.flatnonzero(ev_sym == s)
        ha_idx_all = np.zeros(0, dtype=np.int64)
        ha_t = np.zeros(0, dtype=np.int64)
        if len(ei_s):
            ia = np.searchsorted(ot + BAR5, ev_t[ei_s], side="right") - 1
            okb = (ia >= 0) & (ia < len(ot))
            iac = np.clip(ia, 0, len(ot) - 1)
            for k in ("pred_f", "pred_p", "sig_f", "sig_p", "ks", "hgb"):
                ha_feat[k][ei_s[okb]] = d[k][iac[okb]]
            ha_feat["liq"][ei_s[okb]] = liq[iac[okb]]
            blk_e = np.full(len(ei_s), -1)
            for bi, b in enumerate(B):
                blk_e[(ev_t[ei_s] >= b[0]) & (ev_t[ei_s] <= b[1])] = bi
            sel = okb & liq[iac] & (blk_e >= 0)
            ha_idx_all = iac[sel]
            ha_t = ev_t[ei_s][sel]
        sets = make_sets(d, B, P1["thr"], ha_idx_all)
        for nm in ("OL-pine", "OL-future"):
            for bi, b in enumerate(B):
                raw_counts[(nm, bi)] = raw_counts.get((nm, bi), 0) + int(block_mask(ot[sets[nm + "|raw"]], b).sum())
        p1m = P90 / "d1" / f"{s}.npy"
        if not p1m.exists():
            continue
        syms_with_1m += 1
        a1 = np.load(p1m)
        ot1 = a1[:, 0].astype(np.int64); o1, h1, l1, c1 = a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4]
        del a1
        hour = hour_idx(ot + BAR5)
        for sj, nm in enumerate(set_names):
            idx = sets[nm]
            if len(idx) == 0:
                continue
            t_dec = ha_t if nm == "HA" else ot[idx] + BAR5
            blk = np.full(len(idx), -1)
            for bi, b in enumerate(B):
                blk[(t_dec >= b[0]) & (t_dec <= b[1])] = bi
            keep = blk >= 0
            idx, t_dec, blk = idx[keep], t_dec[keep], blk[keep]
            if len(idx) == 0:
                continue
            # rastgele: aynı sembol, aynı blok, aynı saat, likit, olay etiketi geçerli
            r_idx_l, r_blk_l, v_idx_l, v_blk_l = [], [], [], []
            for bi, b in enumerate(B):
                mb = blk == bi
                if not mb.any():
                    continue
                cand = np.flatnonzero(liq & block_mask(ot, b) & (d["ev"] >= 0) & np.isfinite(d["c4"]))
                if len(cand) == 0:
                    continue
                ri = draw_random(cand, hour[cand], hour[idx[mb]], rng, 2)
                r_idx_l.append(ri); r_blk_l.append(np.full(len(ri), bi))
                vi = draw_random_vm(cand, hour[cand], d["atr"][cand], hour[idx[mb]], d["atr"][idx[mb]], rng, 2)
                v_idx_l.append(vi); v_blk_l.append(np.full(len(vi), bi))
            r_idx = np.concatenate(r_idx_l) if r_idx_l else np.zeros(0, dtype=np.int64)
            r_blk = np.concatenate(r_blk_l) if r_blk_l else np.zeros(0, dtype=int)
            v_idx = np.concatenate(v_idx_l) if v_idx_l else np.zeros(0, dtype=np.int64)
            v_blk = np.concatenate(v_blk_l) if v_blk_l else np.zeros(0, dtype=int)
            all_idx = np.concatenate([idx, r_idx, v_idx])
            all_t = np.concatenate([t_dec, ot[r_idx] + BAR5, ot[v_idx] + BAR5])
            all_blk = np.concatenate([blk, r_blk, v_blk])
            kind = np.concatenate([np.zeros(len(idx), dtype=np.int8), np.ones(len(r_idx), dtype=np.int8), np.full(len(v_idx), 2, dtype=np.int8)])
            sim = simulate_rows(ot1, o1, h1, l1, c1, all_t)
            u = sim["use"]
            nu = int(u.sum())
            rows["set"].append(np.full(nu, sj, dtype=np.int8)); rows["blk"].append(all_blk[u].astype(np.int8))
            rows["kind"].append(kind[u]); rows["sid"].append(np.full(nu, sid_of[s], dtype=np.int32))
            rows["t"].append(all_t[u]); rows["day"].append(day_idx(all_t[u]).astype(np.int32))
            c4v = d["c4"][all_idx[u]]
            rows["up"].append(np.where(np.isfinite(c4v) & (c4v != 0), (c4v > 0).astype(float), np.nan))
            rows["hit"].append(sim["hit"][u]); rows["tp"].append(sim["tp"][u]); rows["tr"].append(sim["tr"][u])
        if (si + 1) % 25 == 0:
            print(f"[eval5] {si + 1}/{len(syms)} sembol ({time.time() - t0:.0f} sn)", flush=True)
    R = {k: np.concatenate(v) for k, v in rows.items()}
    print(f"[eval5] satır: {len(R['set'])} ({time.time() - t0:.0f} sn)", flush=True)
    res: dict = {"set_names": set_names, "stats": {}, "auc": P1["auc"], "bar": P1["bar"], "thr": P1["thr"], "raw_counts": raw_counts,
                 "blocks": [list(b) for b in B], "days": [block_days(b) for b in B], "syms_1m": syms_with_1m, "n_syms": len(syms)}
    for sj, nm in enumerate(set_names):
        for bi in range(3):
            res["stats"][(nm, bi)] = agg(R, sj, bi, res["days"][bi])
    # --- HA ile örtüşme / öncelik / HA'sız (eklenen) sinyaller
    ha_set = set_names.index("HA")
    hm = (R["set"] == ha_set) & (R["kind"] == 0)
    ha_keys = np.sort(R["sid"][hm].astype(np.int64) * KEYS + R["t"][hm])
    res["overlap"] = {}
    W60 = 3_600_000
    for sj, nm in enumerate(set_names):
        if nm == "HA":
            continue
        for bi in range(3):
            sg = (R["set"] == sj) & (R["kind"] == 0) & (R["blk"] == bi)
            if sg.sum() < 5:
                continue
            sid_, t_ = R["sid"][sg], R["t"][sg]
            any_ha, _ = near(ha_keys, sid_, t_, -W60, W60)
            ha_after, t_first = near(ha_keys, sid_, t_, 0, W60)
            ha_before, _ = near(ha_keys, sid_, t_, -W60, -1)
            lead = (t_first[ha_after] - t_[ha_after]) / 60_000.0
            keys_set = np.sort(sid_.astype(np.int64) * KEYS + t_)
            hb = hm & (R["blk"] == bi)
            hs, ht = R["sid"][hb], R["t"][hb]
            ha_cov, _ = near(keys_set, hs, ht, -W60, W60)
            ha_cov_early, tfirst = near(keys_set, hs, ht, -W60, 0)
            lag_min = (ht[ha_cov_early] - tfirst[ha_cov_early]) / 60_000.0
            only_mask = np.zeros(len(R["set"]), dtype=bool)
            only_mask[np.flatnonzero(sg)[~any_ha]] = True
            ov = {"n": int(sg.sum()), "frac_with_ha_pm60": float(any_ha.mean()), "frac_ha_later": float(ha_after.mean()),
                  "frac_ha_earlier": float(ha_before.mean()), "lead_med_min": float(np.median(lead)) if len(lead) else None,
                  "ha_covered": float(ha_cov.mean()) if len(ha_cov) else None, "n_ha": int(hb.sum()),
                  "ha_covered_by_earlier": float(ha_cov_early.mean()) if len(ha_cov) else None,
                  "ha_lag_med_min": float(np.median(lag_min)) if len(lag_min) else None}
            m_only = only_mask | ((R["set"] == sj) & (R["kind"] >= 1) & (R["blk"] == bi))
            Rsub = {k: v[m_only] for k, v in R.items()}
            ov["only_stats"] = agg(Rsub, sj, bi, res["days"][bi])
            res["overlap"][(nm, bi)] = ov
    pickle.dump(res, open(OUT / "results5.pkl", "wb"))
    print(f"[eval5] özetler yazıldı ({time.time() - t0:.0f} sn)", flush=True)
    del R
    _ha_filter(args, res, ha_feat, B, t0)


def _ha_filter(args, res: dict, hf: dict, B, t0: float) -> None:
    """HA'yı Lorentzian/kNN-B/HGB ile süz: tutulan - düşen, (net - hacim-eşleşmiş taban) üzerinden gün-kümeli SE."""
    from scripts import indfilter_common as C
    pop = C.Pop("ha")
    blk = pop.block
    sim = pop.sim(pop.tp)
    net, bnet, hit, bhit = sim["net"], sim["b_net"], sim["hit"], sim["b_hit"]
    day = pop.day
    valid = pop.valid & np.isfinite(net) & np.isfinite(bnet) & (hf["liq"] == 1)
    thr = res["thr"]
    out: dict = {"n_pop": int(len(blk))}

    def groups(bi):
        g = {}
        inb = valid & (blk == bi)
        for nm, key in (("OL-future pred>0", "pred_f"), ("OL-pine pred>0", "pred_p")):
            v = hf[key]
            g[nm] = (inb & (v > 0), inb & np.isfinite(v) & (v <= 0))
        for nm, key in (("OL-future durum=LONG", "sig_f"), ("OL-pine durum=LONG", "sig_p")):
            v = hf[key]
            g[nm] = (inb & (v == 1), inb & np.isfinite(v) & (v != 1))
        if bi >= 1:
            q = 0.2
            tk = thr["ks"].get(bi, {}).get(q)
            if tk is not None:
                v = hf["ks"]
                g["kNN-B skor >= onceki-blok 80. yuzdelik"] = (inb & (v >= tk), inb & np.isfinite(v) & (v < tk))
            th = thr["hgb"].get(bi, {}).get(q)
            if th is not None:
                v = hf["hgb"]
                g["HGB skor >= bekletme 80. yuzdelik"] = (inb & (v >= th), inb & np.isfinite(v) & (v < th))
        return g

    for bi in range(3):
        base_m = valid & (blk == bi)
        out[(bi, "tümü")] = {"n": int(base_m.sum()), "net": float(np.nanmean(net[base_m])), "excess": float(np.nanmean((net - bnet)[base_m])),
                             "hit": float(np.nanmean(hit[base_m])), "b_hit": float(np.nanmean(bhit[base_m]))}
        for nm, (keep, drop) in groups(bi).items():
            r = {}
            for lab, m in (("keep", keep), ("drop", drop)):
                if m.sum() < 5:
                    r[lab] = {"n": int(m.sum())}
                    continue
                st = X.trade_stats(net[m], day[m])
                ex = X.trade_stats((net - bnet)[m], day[m])
                r[lab] = {"n": int(m.sum()), "net": st["mean"], "net_se": st["se"], "excess": ex["mean"], "excess_se": ex["se"],
                          "hit": float(np.nanmean(hit[m])), "b_hit": float(np.nanmean(bhit[m])), "per_day": float(m.sum()) / block_days(B[bi])}
            if "excess" in r.get("keep", {}) and "excess" in r.get("drop", {}):
                a = {"mean": r["keep"]["excess"], "se": r["keep"]["excess_se"], "n": r["keep"]["n"]}
                b = {"mean": r["drop"]["excess"], "se": r["drop"]["excess_se"], "n": r["drop"]["n"]}
                r["diff_excess"] = X.diff_stats(a, b)
                a = {"mean": r["keep"]["net"], "se": r["keep"]["net_se"], "n": r["keep"]["n"]}
                b = {"mean": r["drop"]["net"], "se": r["drop"]["net_se"], "n": r["drop"]["n"]}
                r["diff_net"] = X.diff_stats(a, b)
            out[(bi, nm)] = r
    res["ha_filter"] = out
    pickle.dump(res, open(OUT / "results5.pkl", "wb"))
    print(f"[eval5] HA filtresi yazıldı ({time.time() - t0:.0f} sn)", flush=True)



# ------------------------------------------------------------------------------------------------ 4. 1 dk orijinal (60 likit sembol)
N1_SYMS = 60


def pick_m1_syms(cache: Path) -> list[str]:
    """1 dk verisi olan semboller içinden 90 günlük toplam quote hacmi en yüksek 60 sembol."""
    f = cache / "m1_syms.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    have = {p.stem for p in (P90 / "d1").glob("*.npy")}
    tot = []
    for s in syms5():
        if s in have:
            F5 = np.load(P90 / "grid" / f"F5_{s}.npy", mmap_mode="r")
            tot.append((float(np.nansum(F5[:, 6])), s))
    tot.sort(reverse=True)
    out = [s for _, s in tot[:N1_SYMS]]
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def _pred1_job(job):
    sym, cache = job
    from app.rescan import pattern_study as P
    cache = Path(cache)
    dst = cache / "pred1" / f"{sym}.npz"
    if dst.exists():
        return sym, 0.0
    t0 = time.time()
    a = P.fill_gaps(np.load(P90 / "d1" / f"{sym}.npy"), BAR1)
    real = P.real_mask(np.load(P90 / "d1" / f"{sym}.npy"), BAR1)
    ot = a[:, 0].astype(np.int64)
    o, h, l, c, qv = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 6]
    n = len(c)
    liq = real & (roll288(qv, 1440) >= MIN_Q) & (np.arange(n) >= 300)
    rf = L.lorentzian(o, h, l, c, label_mode="future", min_hist=MIN_HIST)
    rp = L.lorentzian(o, h, l, c, label_mode="pine", min_hist=MIN_HIST)
    c4 = np.full(n, np.nan, dtype=np.float32)
    c4[:-4] = (c[4:] / c[:-4] - 1.0) * 100.0
    dst.parent.mkdir(parents=True, exist_ok=True)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = (L.sma(tr, 14) / c * 100.0).astype(np.float32)
    np.savez(dst, ot=ot, liq=liq, pred_f=rf["pred"], pred_p=rp["pred"], ent_f=rf["entry_long"], ent_p=rp["entry_long"], c4=c4, atr=atr)
    return sym, time.time() - t0


def stage_m1pred(args) -> None:
    from multiprocessing import Pool
    cache = Path(args.cache_dir)
    (cache / "pred1").mkdir(parents=True, exist_ok=True)
    syms = pick_m1_syms(cache)
    if args.limit:
        syms = syms[: args.limit]
    if getattr(args, "reverse", False):
        syms = syms[::-1]
    t0 = time.time()
    with Pool(max(1, args.workers)) as pool:
        for k, (s, dt) in enumerate(pool.imap_unordered(_pred1_job, [(s, str(cache)) for s in syms], chunksize=1)):
            if (k + 1) % 5 == 0:
                print(f"[m1pred] {k + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    print(f"[m1pred] bitti ({time.time() - t0:.0f} sn)", flush=True)


def stage_eval1(args) -> None:
    cache = Path(args.cache_dir)
    B = blocks()
    syms = sorted(p.stem for p in (cache / "pred1").glob("*.npz"))
    rng = np.random.default_rng(args.seed)
    names = ["OL1-pine", "OL1-future"]
    rows: dict[str, list] = {k: [] for k in ("set", "blk", "kind", "sid", "t", "day", "up", "hit", "tp", "tr")}
    t0 = time.time()
    raw = {}
    for si, s in enumerate(syms):
        z = np.load(cache / "pred1" / f"{s}.npz")
        ot, liq, c4 = z["ot"], z["liq"], z["c4"]
        a1 = np.load(P90 / "d1" / f"{s}.npy")
        from app.rescan import pattern_study as P
        a = P.fill_gaps(a1, BAR1)
        o1, h1, l1, c1 = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        hour = hour_idx(ot + BAR1)
        inblk = np.zeros(len(ot), dtype=bool)
        for b in B:
            inblk |= block_mask(ot, b)
        for sj, (nm, ent, pr) in enumerate((("OL1-pine", z["ent_p"], z["pred_p"]), ("OL1-future", z["ent_f"], z["pred_f"]))):
            m = ent.astype(bool) & liq & inblk & np.isfinite(pr)
            raw[(nm, s)] = int(m.sum())
            idx = cooldown(np.flatnonzero(m), 60)
            if len(idx) == 0:
                continue
            t_dec = ot[idx] + BAR1
            blk = np.full(len(idx), -1)
            for bi, b in enumerate(B):
                blk[(t_dec >= b[0]) & (t_dec <= b[1])] = bi
            r_idx_l, r_blk_l, v_idx_l, v_blk_l = [], [], [], []
            atr1 = z["atr"]
            for bi, b in enumerate(B):
                mb = blk == bi
                if not mb.any():
                    continue
                cand = np.flatnonzero(liq & block_mask(ot, b) & np.isfinite(c4) & (np.arange(len(ot)) < len(ot) - 120))
                if len(cand) == 0:
                    continue
                ri = draw_random(cand, hour[cand], hour[idx[mb]], rng, 2)
                r_idx_l.append(ri); r_blk_l.append(np.full(len(ri), bi))
                vi = draw_random_vm(cand, hour[cand], atr1[cand], hour[idx[mb]], atr1[idx[mb]], rng, 2)
                v_idx_l.append(vi); v_blk_l.append(np.full(len(vi), bi))
            r_idx = np.concatenate(r_idx_l) if r_idx_l else np.zeros(0, dtype=np.int64)
            r_blk = np.concatenate(r_blk_l) if r_blk_l else np.zeros(0, dtype=int)
            v_idx = np.concatenate(v_idx_l) if v_idx_l else np.zeros(0, dtype=np.int64)
            v_blk = np.concatenate(v_blk_l) if v_blk_l else np.zeros(0, dtype=int)
            all_idx = np.concatenate([idx, r_idx, v_idx])
            all_t = np.concatenate([t_dec, ot[r_idx] + BAR1, ot[v_idx] + BAR1])
            all_blk = np.concatenate([blk, r_blk, v_blk])
            kind = np.concatenate([np.zeros(len(idx), dtype=np.int8), np.ones(len(r_idx), dtype=np.int8), np.full(len(v_idx), 2, dtype=np.int8)])
            keep = all_blk >= 0
            sim = simulate_rows(ot, o1, h1, l1, c1, all_t)
            u = sim["use"] & keep
            nu = int(u.sum())
            rows["set"].append(np.full(nu, sj, dtype=np.int8)); rows["blk"].append(all_blk[u].astype(np.int8))
            rows["kind"].append(kind[u]); rows["sid"].append(np.full(nu, si, dtype=np.int32))
            rows["t"].append(all_t[u]); rows["day"].append(day_idx(all_t[u]).astype(np.int32))
            c4v = c4[all_idx[u]]
            rows["up"].append(np.where(np.isfinite(c4v) & (c4v != 0), (c4v > 0).astype(float), np.nan))
            rows["hit"].append(sim["hit"][u]); rows["tp"].append(sim["tp"][u]); rows["tr"].append(sim["tr"][u])
        if (si + 1) % 10 == 0:
            print(f"[eval1] {si + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    R = {k: np.concatenate(v) for k, v in rows.items()}
    res = {"set_names": names, "stats": {}, "n_syms": len(syms), "days": [block_days(b) for b in B],
           "raw": {nm: sum(v for (n_, _), v in raw.items() if n_ == nm) for nm in names}}
    for sj, nm in enumerate(names):
        for bi in range(3):
            res["stats"][(nm, bi)] = agg(R, sj, bi, res["days"][bi])
    pickle.dump(res, open(OUT / "results1.pkl", "wb"))
    print(f"[eval1] bitti ({time.time() - t0:.0f} sn)", flush=True)



# ------------------------------------------------------------------------------------------------ 5. rapor
def _f(x, nd: int = 2, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    fmt = "{:+." + str(nd) + "f}" if sign else "{:." + str(nd) + "f}"
    return fmt.format(x)


def _dd(d: dict | None, nd: int = 2) -> str:
    """fark (SE) gösterimi: +0,05 (0,07)"""
    if not d or "diff" not in d:
        return "–"
    return "{} ({})".format(_f(d["diff"], nd, True), _f(d["se"], nd))


def _net(st: dict | None) -> str:
    if not st or "mean" not in st:
        return "–"
    return _f(st["mean"], 2, True)


def _ci_flag(d: dict | None) -> str:
    """%95 aralık 0'ı içermiyorsa işaret."""
    if not d or "lo" not in d:
        return ""
    if d["lo"] > 0:
        return " ▲"
    if d["hi"] < 0:
        return " ▼"
    return ""


def table_main(res: dict, bi: int, sets: list[str], rand_rows: bool = False) -> list[str]:
    hdr = ("| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | "
           "Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |")
    lines = [hdr, "|" + "---|" * 11]
    for nm in sets:
        st = res["stats"].get((nm, bi), {})
        if not st or st.get("n", 0) < 5 or "hit" not in st:
            lines.append("| {} | {} | – | – | – | – | – | – | – | – | – |".format(nm, _f(st.get("per_day") if st else None, 1)))
            continue
        lines.append("| {} | {} | {} ({}) | {} ({}) | {}{} | {}{} | {} | {}{} | {}{} | {} | {}{} |".format(
            nm, _f(st["per_day"], 1), _f(st.get("up"), 1), _f(st.get("up_rnd"), 1), _f(st.get("hit"), 1), _f(st.get("hit_rnd"), 1),
            _dd(st.get("hit_diff"), 1), _ci_flag(st.get("hit_diff")), _dd(st.get("hit_diffv"), 1), _ci_flag(st.get("hit_diffv")),
            _net(st.get("tp")), _dd(st.get("tp_diff")), _ci_flag(st.get("tp_diff")),
            _dd(st.get("tp_diffv")), _ci_flag(st.get("tp_diffv")), _net(st.get("tr")), _dd(st.get("tr_diffv")), _ci_flag(st.get("tr_diffv"))))
    if rand_rows:
        ha = res["stats"].get(("HA", bi), {})
        if ha and "hit" in ha:
            lines.append("| Rastgele (saat-eşl., HA örneği) | – | {} | {} | – | – | {} | – | – | {} | – |".format(
                _f(ha.get("up_rnd"), 1), _f(ha.get("hit_rnd"), 1), _net(ha.get("tp_rnd")), _net(ha.get("tr_rnd"))))
            lines.append("| Rastgele (saat+oynaklık-eşl., HA örneği) | – | – | {} | – | – | {} | – | – | {} | – |".format(
                _f(ha.get("hit_rndv"), 1), _net(ha.get("tp_rndv")), _net(ha.get("tr_rndv"))))
    return lines


def stage_report(args) -> None:
    res = pickle.load(open(OUT / "results5.pkl", "rb"))
    r1p = OUT / "results1.pkl"
    res1 = pickle.load(open(r1p, "rb")) if r1p.exists() else None
    names = res["set_names"]
    L_: list[str] = []
    L_.append("# Lorentzian Classification (kNN) — tahmin motoru çalışması (2026-10-17)")
    L_.append("")
    L_.append("Çevrimdışı araştırma (`scripts/lorentzian_study.py`, `app/rescan/lorentzian.py`, `tests/test_lorentzian.py`); canlı koda bağlanmaz, DB'ye yazmaz.")
    L_.append("")
    vf = OUT / "verdict.md"
    L_.append("## 0. Hüküm")
    L_.append("")
    L_.append(vf.read_text(encoding="utf-8").strip() if vf.exists() else "_(hüküm metni henüz yazılmadı)_")
    L_.append("")
    L_.append("### 0a. Özet tablo (blok başına; yürüyen ileri; yalnız 24 sa quote hacmi ≥ 5M TRY anları)")
    L_.append("")
    L_.append("Sütunlar: yükseliş % = sinyalden 4 bar (20 dk) sonra kapanış > sinyal kapanışı oranı (parantez: aynı sembol+saat rastgele). hit60@1,5 = 1 dk yolda "
              "giriş (sinyal+60 sn → sonraki 1 dk açılışı) sonrası 60 dk içinde yüksek ≥ +%1,5. lift = sinyal − saat-eşleşmiş rastgele (pp). net = exit_sim "
              "(0,15% kayma, 0,1125%/bacak): TP1,5/SL3/T60 ve iz (act1,0/gap0,8/SL3/T60); Δnet = sinyal − rastgele (SE: gün-kümeli, bağımsız kabul). ▲/▼ = %95 aralık 0'ı dışlıyor.")
    L_.append("")
    main_sets = ["OL-pine", "OL-future", "kNN-B q0.25%", "HGB q0.25%", "HA"]
    for bi in range(3):
        L_.append("**{}** ({} gün)".format(BLOCK_NAMES[bi], _f(res["days"][bi], 0)))
        L_.append("")
        L_.extend(table_main(res, bi, [x for x in main_sets if x in names], rand_rows=True))
        L_.append("")
    L_.append("### 0b. Bar düzeyi ayrım gücü (ROC-AUC; tüm likit barlar)")
    L_.append("")
    L_.append("| Blok | skor | AUC (60 dk olay ≥%1,5) | AUC (4 bar yükseliş) | pred>0: yükseliş doğruluğu | pred<0: düşüş doğruluğu | olay oranı pred>0 / pred≤0 |")
    L_.append("|---|---|---|---|---|---|---|")
    nice = {"pred_f": "Orijinal (future etiket)", "pred_p": "Orijinal (pine etiket)", "ks": "kNN-B (olay etiketi)", "hgb": "HGB (olay etiketi)"}
    for bi in range(3):
        bar = res["bar"][bi]
        for k in ("pred_f", "pred_p", "ks", "hgb"):
            a = res["auc"].get((bi, k), {})
            if not a or not np.isfinite(a.get("auc_ev", float("nan"))):
                continue
            ex = ""
            if k in ("pred_f", "pred_p"):
                ex = "{} / {}".format(_f(100 * a.get("ev_pos", float("nan")), 1), _f(100 * a.get("ev_nonpos", float("nan")), 1))
            L_.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                BLOCK_NAMES[bi][:2], nice[k], _f(a["auc_ev"], 3), _f(a["auc_up"], 3),
                _f(100 * a["acc_pos"], 1) if "acc_pos" in a else "–", _f(100 * a["acc_neg"], 1) if "acc_neg" in a else "–", ex or "–"))
        L_.append("| {} | (taban) | olay oranı {} % | yükseliş oranı {} % | | | |".format(BLOCK_NAMES[bi][:2], _f(100 * bar["ev_rate"], 1), _f(100 * bar["up_rate"], 1)))
    L_.append("")
    eng_p = OUT / "results_engine.pkl"
    if eng_p.exists():
        eg = pickle.load(open(eng_p, "rb"))
        L_.append("### 0c. Motor karşılaştırması: kNN-Lorentzian mı HistGradientBoosting mı? (aynı saatlik örnek, 60 dk olay etiketi)")
        L_.append("")
        L_.append("Yalnız olay etiketi için sıralama gücü. 'ATR içi AUC' = ATR14% üçte birlikleri içinde AUC'lerin ortalaması (oynaklık etkisi arındırılmış). "
                  "Üst-q isabet = skoru en yüksek q payındaki olay oranı (taban olay oranı ile kıyasla).")
        L_.append("")
        L_.append("| Blok | Skor | AUC | ATR içi AUC (düşük/orta/yüksek) | isabet üst %0,25 | üst %1 | üst %5 |")
        L_.append("|---|---|---|---|---|---|---|")
        for bi, o in eg["blocks"].items():
            for nm, v in o.items():
                if not (isinstance(v, dict) and "auc" in v):
                    continue
                L_.append("| B{} | {} | {} | {} ({}) | {} | {} | {} |".format(
                    bi + 1, nm, _f(v["auc"], 3), _f(v["auc_within_mean"], 3), " / ".join(_f(x, 3) for x in v["auc_within_atr"]),
                    _f(100 * v.get("prec_q0.25", float("nan")), 1), _f(100 * v.get("prec_q1", float("nan")), 1), _f(100 * v.get("prec_q5", float("nan")), 1)))
            L_.append("| B{} | taban olay oranı {} % (yalnız-ATR üst %0,25/%1/%5: {} / {} / {}) | | | | | |".format(
                bi + 1, _f(100 * o["base"], 1), _f(100 * o["atr_prec"]["q0.25"], 1), _f(100 * o["atr_prec"]["q1"], 1), _f(100 * o["atr_prec"]["q5"], 1)))
        L_.append("")
    L_.append("## 1. Yöntem")
    L_.append("")
    L_.append("""- **Orijinal betik (OL)**: jdehorty `Lorentzian Classification` (MLExtensions/KernelFunctions kaynak okundu). Özellikler RSI(14,1), WT(10,11), CCI(20,1), ADX(20,2), RSI(9,1); Lorentzian mesafe Σlog(1+|xi−yi|); ANN döngüsü birebir (`d ≥ lastDistance ∧ i%4≠0`, k=8, `lastDistance = distances[round(k·3/4)]`, en eskiyi at), pencere 2000 bar (kayan), tahmin = komşu etiket toplamı; filtreler: volatilite (ATR1 > ATR10) + rejim (KLMF eğim ≥ −0,1); ADX/EMA/SMA filtreleri kapalı; çekirdek RQK (h=8, r=8, x=25) boğa; giriş = sinyalin LONG'a DÖNDÜĞÜ bar ∧ çekirdek boğa. Nedensellik: kesme-değişmezliği testle doğrulandı.
- **Etiket bulgusu (önemli)**: betik kodunda `y_train_series = src[4] < src[0] ? SHORT : src[4] > src[0] ? LONG` ve etiket AYNI barın özellikleriyle saklanır → etiket GEÇMİŞ 4 barlık hareketin TERSİDİR (gecikmesiz; "4 bar sonrası" niyetine rağmen). İki kip de ölçüldü: **OL-pine** = betiğin gerçekte yaptığı (y[j]=sign(c[j−4]−c[j]), geçmiş j≤t); **OL-future** = belgelenen niyet (y[j]=sign(c[j+4]−c[j]), etiketi bilinen j≤t−4).
- **Varyant B (kNN-B)**: aynı ANN/Lorentzian makinesi; etiket = bizim olay (t+1 açılışından 60 dk içinde yüksek ≥ +%1,5; t+12'de bilinir → gecikme 12 bar); 7 özellik (5m ATR14%, ret1, ret10, EMA50/99 farkı, taker alış payı 3 bar, hacim oranı, range_pos24) — geçmiş 2000 barlık z-skoruyla [0,1]'e nedensel ölçeklenir. Skor = komşuların olay sayısı (0–8), eşit skorlarda daha yakın komşular öne.
- **HGB**: sklearn HistGradientBoosting (150 iterasyon, 31 yaprak), AYNI 7 özellik (ham), havuzlanmış tüm semboller; B2 ← B1, B3 ← B1+B2 (her seferinde önceki bloğun SON 5 günü + 12 bar tecrit eğitimden çıkarılır; eşik o 5 günün skorlarından seçilir). B1 için eğitim verisi yok → HGB B1'de YOK.
- **Eşik (kNN-B, HGB)**: "üst q" = likit bar-anların en yüksek skorlu %q'su; kNN-B için eşik ÖNCEKİ bloğun skor dağılımından, HGB için bekletme günlerinden; B1'de kNN-B için önceki blok olmadığından yok. Ana satır q=%0,25 (≈ HA sıklığı), %0,1 ve %1 detayda. Sinyal sonrası aynı sembolde 60 dk soğuma (tüm kümelere; OL'nin ham giriş sayısı ayrıca verilir).
- **Rastgele taban**: sinyal başına 2 rastgele giriş: aynı sembol, aynı blok, aynı yerel saat, likit (ve oynaklık-eşleşmiş sürüm: ayrıca 5m ATR14% ±%25). Net: exit_sim, 60 sn gecikme, %0,15 kayma, %0,1125/bacak; gün-kümeli SE.
- **HA**: `work/indfilter/events_ha.pkl` (rank ≤ 10, aşırı alımda değil, 60 dk bölüm) → likit olanlar; aynı exit_sim (HA'nın kendi hedefiyle değil, tüm kümeler için aynı TP1,5/SL3/T60 ve iz). HA filtresi bölümü HA'nın KENDİ hedefini ve indfilter oynaklık-eşleşmiş tabanını kullanır.""")
    L_.append("")
    L_.append("## 2. Ayrıntı — tüm kümeler")
    L_.append("")
    for bi in range(3):
        L_.append("**{}**".format(BLOCK_NAMES[bi]))
        L_.append("")
        L_.extend(table_main(res, bi, names))
        L_.append("")
    L_.append("OL ham (soğumasız) giriş sayısı: " + "; ".join("{} {}: {}".format(nm, BLOCK_NAMES[bi][:2], res["raw_counts"].get((nm, bi), 0)) for nm in ("OL-pine", "OL-future") for bi in range(3)))
    L_.append("")
    L_.append("## 3. HA ile örtüşme ve öncelik (±60 dk)")
    L_.append("")
    L_.append("| Küme | Blok | sinyal | HA ±60 dk içinde % | HA SONRA geldi % (medyan öncelik dk) | HA'nın bu kümece ±60 dk kapsanması % | HA'sız sinyal: Δnet TP vs oynaklık-eşl. | HA'sız: lift pp |")
    L_.append("|---|---|---|---|---|---|---|---|")
    for nm in names:
        if nm == "HA":
            continue
        for bi in range(3):
            ov = res["overlap"].get((nm, bi))
            if not ov:
                continue
            os_ = ov.get("only_stats", {})
            L_.append("| {} | {} | {} | {} | {} ({}) | {} | {}{} | {} |".format(
                nm, BLOCK_NAMES[bi][:2], ov["n"], _f(100 * ov["frac_with_ha_pm60"], 1), _f(100 * ov["frac_ha_later"], 1), _f(ov["lead_med_min"], 0),
                _f(100 * ov["ha_covered"], 1) if ov["ha_covered"] is not None else "–", _dd(os_.get("tp_diffv")), _ci_flag(os_.get("tp_diffv")),
                _dd(os_.get("hit_diff"), 1)))
    L_.append("")
    hf = res.get("ha_filter", {})
    L_.append("## 4. HA filtresi olarak (HA'nın kendi hedefi; net − oynaklık-eşleşmiş taban; tutulan − düşen)")
    L_.append("")
    L_.append("| Blok | Filtre | tutulan n (gün) | tutulan net | tutulan fazlası | düşen net | düşen fazlası | Δ fazla (tut−düş) | Δ net (tut−düş) |")
    L_.append("|---|---|---|---|---|---|---|---|---|")
    for bi in range(3):
        a = hf.get((bi, "tümü"))
        if a:
            L_.append("| {} | HA tümü | {} | {} | {} | | | | |".format(BLOCK_NAMES[bi][:2], a["n"], _f(a["net"], 2, True), _f(a["excess"], 2, True)))
        for key, r in hf.items():
            if not (isinstance(key, tuple) and key[0] == bi and key[1] != "tümü"):
                continue
            kp, dr = r.get("keep", {}), r.get("drop", {})
            L_.append("| {} | {} | {} ({}) | {} | {} | {} | {} | {}{} | {}{} |".format(
                BLOCK_NAMES[bi][:2], key[1], kp.get("n", 0), _f(kp.get("per_day"), 1), _f(kp.get("net"), 2, True), _f(kp.get("excess"), 2, True),
                _f(dr.get("net"), 2, True), _f(dr.get("excess"), 2, True), _dd(r.get("diff_excess")), _ci_flag(r.get("diff_excess")),
                _dd(r.get("diff_net")), _ci_flag(r.get("diff_net"))))
    L_.append("")
    if res1:
        L_.append("## 5. 1 dakikalık orijinal (60 likit sembol)")
        L_.append("")
        L_.append("Aynı kod 1 dk mumlarda (pencere 2000 dk, etiket 4 dk); karar 1 dk kapanışında, giriş +60 sn sonraki 1 dk açılışı; 60 dk soğuma. Ham (soğumasız) giriş: pine {}, future {}.".format(res1["raw"]["OL1-pine"], res1["raw"]["OL1-future"]))
        L_.append("")
        for bi in range(3):
            L_.append("**{}**".format(BLOCK_NAMES[bi]))
            L_.append("")
            L_.extend(table_main(res1, bi, res1["set_names"]))
            L_.append("")
    L_.append("## 6. Sınırlar")
    L_.append("")
    L_.append("""- Betikteki `var predictions/distances` dizilerinin barlar arası taşınması ve büyüyen dizi (yalnız son 2000 grafik barı) yerine kayan 2000 barlık pencere kullanıldı; i%4 eşlemesi mutlak bar indeksine göre.
- ADX özelliğinde ortalama `sma` (MLExtensions n_adx), RQK penceresi x+2 = 27 örnek (KernelFunctions döngüsü `0..size+x`); küçük sapmalar sonucu değiştirmez (kesin Pine çıktısıyla bit düzeyinde karşılaştırma yapılamadı).
- Normalleştirme (WT/CCI) tarihsel (genişleyen) min/max — veri 19.07'de başladığından ilk günlerde dar aralık; kNN için geçmiş ≥ 300 bar şartı → B1'in ilk ~1-2 günü sinyal üretmez.
- Rastgele tabanın bağımsız kabulü ve sinyallerin kümelenmesi: SE'ler gün-kümeli ama sembol/zaman çakışması tamamen modellenmedi.
- HGB B1'de değerlendirilemez (öncesi yok); kNN-B B1'de eşiksiz.
- 90 gün tek rejim; sonuçlar yalnızca bu örnek için.""")
    (OUT / "report.md").write_text("\n".join(L_) + "\n", encoding="utf-8")
    print("[report] yazıldı:", OUT / "report.md", flush=True)



# ------------------------------------------------------------------------------------------------ 3b. motor karşılaştırması (aynı örnek: saatlik ızgara)
POOL_N = 30_000
POOL_K = 60
ENGINE_STEP = 12              # her 12. 5 dk bar (saatlik ızgara)


def _pool_transform(F: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Havuzlanmış kNN için sabit (sembolden bağımsız) ölçek: atr ve hacim oranı log; ref (eğitim örneği) 1.-99. yüzdelikle [0,1]."""
    def t(M):
        M = np.array(M, dtype=np.float64)
        M[:, 0] = np.log(np.maximum(M[:, 0], 1e-3))
        M[:, 5] = np.log(np.maximum(M[:, 5], 1e-2))
        return M
    R = t(ref); G = t(F)
    lo = np.percentile(R, 1, axis=0); hi = np.percentile(R, 99, axis=0)
    return np.clip((G - lo) / np.maximum(hi - lo, 1e-9), 0.0, 1.0).astype(np.float32)


def pool_knn_scores(Ptr: np.ndarray, ytr: np.ndarray, Q: np.ndarray, k: int = POOL_K, chunk: int = 256) -> np.ndarray:
    """Havuzlanmış kNN: sorgu başına Lorentzian mesafe (Σ log(1+|Δ|)) ile k en yakın eğitim noktasının olay oranı."""
    out = np.empty(len(Q), dtype=np.float32)
    nf = Q.shape[1]
    for i in range(0, len(Q), chunk):
        q = Q[i:i + chunk]
        d = np.zeros((len(q), len(Ptr)), dtype=np.float32)
        for f in range(nf):
            d += np.log1p(np.abs(q[:, f:f + 1] - Ptr[None, :, f]))
        nn = np.argpartition(d, k, axis=1)[:, :k]
        out[i:i + chunk] = ytr[nn].mean(axis=1)
    return out


def stage_engine(args) -> None:
    from scripts.indfilter_common import auc_score
    cache = Path(args.cache_dir)
    B = blocks()
    syms = sorted(p.stem for p in (cache / "pred5").glob("*.npz"))
    if args.limit:
        syms = syms[: args.limit]
    rng = np.random.default_rng(args.seed)
    D = {}
    for s in syms:
        z = np.load(cache / "pred5" / f"{s}.npz")
        d = load_light(cache, s)
        d["F7"] = z["F7"]
        D[s] = d
    res: dict = {"blocks": {}}
    t0 = time.time()
    for bi in (1, 2):
        hold_lo = B[bi - 1][1] + 1 - HOLD_DAYS * DAY_MS
        tr_hi = hold_lo - COOLDOWN * BAR5
        Xtr, ytr = [], []
        for s in syms:
            d = D[s]
            m = d["liq"] & (d["ev"] >= 0) & np.isfinite(d["F7"]).all(axis=1) & (d["ot"] < tr_hi)
            Xtr.append(d["F7"][m]); ytr.append((d["ev"][m] > 0).astype(np.float32))
        Xtr = np.concatenate(Xtr); ytr = np.concatenate(ytr)
        pick = rng.choice(len(ytr), size=min(POOL_N, len(ytr)), replace=False)
        Xs, ys = Xtr[pick], ytr[pick]
        del Xtr, ytr
        Ptr = _pool_transform(Xs, Xs)
        cols = {k: [] for k in ("atr", "ev", "ks", "hgb", "pred_f", "pred_p", "F7")}
        for s in syms:
            d = D[s]
            idx = np.flatnonzero(d["liq"] & (d["ev"] >= 0) & np.isfinite(d["F7"]).all(axis=1) & block_mask(d["ot"], B[bi]) & (np.arange(len(d["ot"])) % ENGINE_STEP == 0))
            if len(idx) == 0:
                continue
            for k in ("atr", "ev", "ks", "hgb", "pred_f", "pred_p"):
                cols[k].append(d[k][idx])
            cols["F7"].append(d["F7"][idx])
        C = {k: np.concatenate(v) for k, v in cols.items()}
        Q = _pool_transform(C["F7"], Xs)
        C["pool"] = pool_knn_scores(Ptr, ys, Q)
        y = C["ev"] > 0
        print(f"[engine] blok {bi + 1}: örnek {len(y)}, olay oranı {y.mean():.4f} ({time.time() - t0:.0f} sn)", flush=True)
        tert = np.digitize(C["atr"], np.quantile(C["atr"], [1 / 3, 2 / 3]))
        out = {"n": int(len(y)), "base": float(y.mean())}
        scores = {"ATR14% (tek özellik)": C["atr"], "HGB (7 özellik, havuz)": C["hgb"], "kNN-Lorentzian havuz (7 özellik)": C["pool"],
                  "kNN-B (sembol başına 2000 bar)": C["ks"], "Orijinal (future etiket)": C["pred_f"], "Orijinal (pine etiket)": C["pred_p"]}
        for nm, sc in scores.items():
            fin = np.isfinite(sc)
            r = {"auc": auc_score(sc[fin], y[fin]) if fin.sum() > 1000 else float("nan"), "n": int(fin.sum())}
            ws = []
            for tq in range(3):
                m = fin & (tert == tq)
                ws.append(auc_score(sc[m], y[m]) if m.sum() > 500 else float("nan"))
            r["auc_within_atr"] = ws
            r["auc_within_mean"] = float(np.nanmean(ws))
            for q in (0.0025, 0.01, 0.05):
                if fin.sum() > 2000:
                    thr = np.quantile(sc[fin], 1 - q)
                    top = fin & (sc >= thr)
                    r["prec_q%g" % (q * 100)] = float(y[top].mean())
                    r["n_q%g" % (q * 100)] = int(top.sum())
                    # aynı sayıda en yüksek ATR'li bar (oynaklık-yalnız referansı)
            out[nm] = r
        # referans: aynı üst-q payı için "yalnız ATR" kesimi
        for q in (0.0025, 0.01, 0.05):
            thr = np.quantile(C["atr"], 1 - q)
            out.setdefault("atr_prec", {})["q%g" % (q * 100)] = float(y[C["atr"] >= thr].mean())
        res["blocks"][bi] = out
    pickle.dump(res, open(OUT / "results_engine.pkl", "wb"))
    print(f"[engine] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="pred5")
    ap.add_argument("--cache-dir", default=str(CACHE))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--reverse", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get("stage_" + st)
        if fn is None:
            sys.exit("bilinmeyen aşama: " + st)
        fn(args)


if __name__ == "__main__":
    main()
