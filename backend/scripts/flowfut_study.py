"""İşlem akışı + vadeli (OI / L-S / fonlama / defter) özellikleri LUNA tipi yükselişi ve Hız Avcısı (HA) adaylarını ayırıyor mu? (2026-10-17, çevrimdışı)

Canlı koda bağlanmaz, DB'ye YAZMAZ (yalnız okur). Özellik kurucular: `app/rescan/flow_futures.py` (saf, nedensel, testli).
`indearly_study.py` (eşleşmiş grup-içi AUC, olay/taban anlık görüntüleri), `indearly_signals.py` (sinyal süpürme + exit_sim değerlendirme) ve `indfilter_study.py` (HA süzgeci) hatlarını YENİDEN KULLANIR.
Bloklar (TR günü): B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki (`indfilter_common.ha_blocks`). Seçim hiçbir zaman değerlendirilen blokta yapılmaz.

Aşamalar (`--stages`, virgüllü):
  feat    sembol başına tüm 5 dk ızgara özellikleri (tf.* + fu.*) -> <fx-dir>/FFX_<sym>.npy (float32) + COV_<sym>.npy (kapsam bayrakları)
  snap    olay (t0−15, −10, −5, t0) ve eşleşmiş taban anlık görüntüleri -> <fx-dir>/snap/*.npy
  rank    (a) olay <-> eşleşmiş taban grup-içi AUC, "düşüş+oynaklık" doğrusal kontrolünden sonra artık AUC, BH q, blok işaret tutarlılığı, blok-dışı seçim AUC -> rank.pkl
  multi   (a) HistGradientBoosting blok-dışı + ileri-yürüyen: mevcut 154 -> +tf -> +fu -> +ikisi (aynı alt kümede) -> multi.pkl
  hafeat  HA olay anı özellikleri -> <out-dir>/feats_ha.npz
  ha      (b) HA süzgeci: kısmi Spearman, blok-dışı seçilmiş en iyi özelliklerde tersil neti, kural arama rotasyonu -> ha.pkl
  sweep   (c) ÖNCEDEN BELİRLENMİŞ sinyallerin 5 dk süpürmesi (cooldown 12 bar) -> <fx-dir>/sig, <out-dir>/sig
  eval    (c) indearly_signals.stage_eval'ı yeniden kullanır -> eval.pkl
  report  Türkçe rapor -> <out-dir>/report.md

Kullanım (backend/): python scripts/flowfut_study.py --cache-dir <p90cache> --old-fx-dir <scratch>/indearly --fx-dir <scratch>/flowfut --out-dir work/flowfut --workers 2
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import flow_futures as FF  # noqa: E402
from app.rescan import pattern_study as P  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402
from scripts.pattern90_study import list_syms, parse_day, fmt_t, MIN_QUOTE, WARM_BARS  # noqa: E402

OFFS = (3, 2, 1, 0)
OFF_LABEL = {3: "t0-15", 2: "t0-10", 1: "t0-5", 0: "t0"}
BASE_PER_EVENT = 20
FLOW_START_MS = 1_784_419_200_000            # 2026-07-19 00:00 UTC (historical_trade_flow ilk dakika)
COL_C = P.COL_C
BLOCK_LABELS = ["B1 (20 Tem-18 Ağu)", "B2 (19 Ağu-17 Eyl)", "B3 (18 Eyl-16 Eki)"]
COV_COLS = ("tf_ok", "fu_ok", "bd_ok", "perp")

SQL_FLOW = ("SELECT minute_open_ms, " + ", ".join(FF.FLOW_COLS_DB[k] for k in FF.FLOW_KEYS) +
            " FROM historical_trade_flow WHERE symbol=%s ORDER BY minute_open_ms")
SQL_METRICS = ("SELECT ts_ms, sum_open_interest, sum_open_interest_value, sum_toptrader_long_short_ratio, count_toptrader_long_short_ratio, "
               "count_long_short_ratio, sum_taker_long_short_vol_ratio FROM hist_futures_metrics "
               "WHERE perp_symbol=%s AND sum_open_interest > 0 AND sum_open_interest_value > 0 ORDER BY ts_ms")
SQL_BOOK = ("SELECT ts_ms, bid_n1, bid_n2, bid_n5, ask_n1, ask_n2, ask_n5 FROM hist_futures_bookdepth WHERE perp_symbol=%s ORDER BY ts_ms")
SQL_FUND = "SELECT funding_time_ms, funding_rate FROM hist_funding_rate WHERE perp_symbol=%s ORDER BY funding_time_ms"


def blocks() -> list[tuple[int, int]]:
    return K.ha_blocks()


def block_idx(t_ms) -> np.ndarray:
    return K.block_of(t_ms, blocks()).astype(int)


def _arr(rows, ncol) -> np.ndarray:
    if not rows:
        return np.zeros((0, ncol))
    return np.array([[np.nan if v is None else float(v) for v in r] for r in rows], dtype=float)


# ------------------------------------------------------------------------------------------------ feat
_USD: dict = {}


def usdtry_close(conn, ot: np.ndarray) -> np.ndarray:
    """USDTTRY 5 dk kapanışı, sembol ızgarasına hizalı (açılış zamanı eşleşir; en çok 6 bar geriye taşınır)."""
    if "a" not in _USD:
        rows = conn.execute("SELECT open_time, close FROM historical_candles WHERE symbol='USDTTRY' AND timeframe='5m' ORDER BY open_time").fetchall()
        a = _arr(rows, 2)
        _USD["a"] = (a[:, 0].astype(np.int64), a[:, 1])
    uo, uc = _USD["a"]
    j = np.searchsorted(uo, ot, side="right") - 1
    ok = j >= 0
    jj = np.clip(j, 0, len(uo) - 1)
    stale = (ot - uo[jj]) > 6 * FF.BAR_MS
    return np.where(ok & ~stale, uc[jj], np.nan)


def build_symbol(conn, sym: str, ot: np.ndarray, c5: np.ndarray, *, extra_lag: int = 0):
    """(adlar, X float32 (n5, F), COV uint8 (n5, 4)). Yalnız DB'den OKUR."""
    n5 = len(ot)
    ot0 = int(ot[0])
    cov0 = max(0, int(math.ceil((FLOW_START_MS - ot0) / FF.BAR_MS)))
    rows = conn.execute(SQL_FLOW, (sym,)).fetchall()
    fl = _arr(rows, 1 + len(FF.FLOW_KEYS))
    has_flow = len(fl) > 0
    if has_flow:
        cols = {k: fl[:, 1 + i] for i, k in enumerate(FF.FLOW_KEYS)}
        bars = FF.minute_rows_to_bars(fl[:, 0].astype(np.int64), cols, ot0, n5)
    else:
        bars = {k: np.zeros(n5) for k in FF.FLOW_KEYS}
    names_tf, X_tf = FF.build_flow_features(bars, c5, cov0)
    if not has_flow:
        X_tf[:] = np.nan
    names_fu = FF.futures_feature_names()
    X_fu = np.full((n5, len(names_fu)), np.nan, dtype=np.float32)
    cov = np.zeros((n5, 4), dtype=np.uint8)
    cov[:, 0] = has_flow & (np.arange(n5) >= cov0 + 11)
    mp = conn.execute("SELECT perp_symbol, multiplier FROM futures_symbol_map WHERE try_symbol=%s", (sym,)).fetchone()
    if mp is not None:
        perp, mult = mp[0], float(mp[1])
        m = _arr(conn.execute(SQL_METRICS, (perp,)).fetchall(), 7)
        if len(m):
            vals, age = FF.align_metric_rows(m[:, 0].astype(np.int64), m[:, 1:7], ot0, n5, extra_lag=extra_lag, ffill=3)
            fut = {k: vals[:, i] for i, k in enumerate(FF.FUT_KEYS)}
            b = _arr(conn.execute(SQL_BOOK, (perp,)).fetchall(), 7)
            if len(b):
                bv, _ = FF.align_snapshot_rows(b[:, 0].astype(np.int64), b[:, 1:7], ot0, n5, extra_lag=extra_lag, ffill=3)
            else:
                bv = np.full((n5, 6), np.nan)
            bd = {k: bv[:, i] for i, k in enumerate(FF.BD_KEYS)}
            fr = _arr(conn.execute(SQL_FUND, (perp,)).fetchall(), 2)
            t_dec = ot + FF.BAR_MS
            if len(fr):
                fund = FF.funding_features(fr[:, 0].astype(np.int64), fr[:, 1], t_dec, extra_lag_ms=extra_lag * FF.BAR_MS)
            else:
                fund = {k: np.full(n5, np.nan) for k in ("fund_bps", "fund_z", "fund_chg", "fund_age_h")}
            usd = usdtry_close(conn, ot)
            names_fu, X_fu = FF.build_futures_features(fut, bd, fund, c5, usd, mult, age)
            cov[:, 1] = np.isfinite(fut["oi"])
            cov[:, 2] = np.isfinite(bd["bid_n2"])
            cov[:, 3] = 1
    return names_tf + names_fu, np.hstack([X_tf, X_fu]).astype(np.float32), cov


def _feat_job(job):
    sym, cache_dir, fx_dir, extra_lag = job
    conn = K.get_conn()
    try:
        cache = Path(cache_dir)
        ot = np.load(cache / "grid" / f"OT_{sym}.npy").astype(np.int64)
        f5 = np.load(cache / "grid" / f"F5_{sym}.npy")
        names, X, cov = build_symbol(conn, sym, ot, f5[:, COL_C], extra_lag=extra_lag)
    finally:
        conn.close()
    np.save(Path(fx_dir) / f"FFX_{sym}.npy", X)
    np.save(Path(fx_dir) / f"COV_{sym}.npy", cov)
    return sym, names


def all_names() -> list[str]:
    return FF.flow_feature_names() + FF.futures_feature_names()


def stage_feat(args) -> None:
    from multiprocessing import Pool
    fx = Path(args.fx_dir)
    fx.mkdir(parents=True, exist_ok=True)
    names = all_names()
    (fx / "fx_names.json").write_text(json.dumps(names), encoding="utf-8")
    syms = list_syms(args.cache_dir, "d5")
    done = {p.stem[4:] for p in fx.glob("FFX_*.npy")}
    todo = [s for s in syms if s not in done] if not args.refeat else syms
    t0 = time.time()
    print("[feat] %d özellik; %d sembol işlenecek (%d hazır)" % (len(names), len(todo), len(syms) - len(todo)), flush=True)
    with Pool(max(1, args.workers)) as pool:
        for k, (s, nm) in enumerate(pool.imap_unordered(_feat_job, [(s, args.cache_dir, args.fx_dir, args.extra_lag) for s in todo], chunksize=1)):
            if nm != names:
                raise SystemExit("özellik adı uyuşmazlığı: " + s)
            if (k + 1) % 20 == 0:
                print("[feat] %d/%d (%.0f sn)" % (k + 1, len(todo), time.time() - t0), flush=True)
    print("[feat] bitti (%.0f sn)" % (time.time() - t0), flush=True)


# ------------------------------------------------------------------------------------------------ snap
def load_old_meta(old_fx: str) -> dict:
    z = np.load(Path(old_fx) / "snap" / "meta.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


def stage_snap(args) -> None:
    fx = Path(args.fx_dir)
    (fx / "snap").mkdir(exist_ok=True)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    m = load_old_meta(args.old_fx_dir)
    G = len(m["ev_sid"])
    rng = np.random.default_rng(args.seed)
    keep = np.zeros(len(m["b_g"]), bool)
    cnt = np.zeros(G, int)
    for i in rng.permutation(len(m["b_g"])):
        if cnt[m["b_g"][i]] < BASE_PER_EVENT:
            keep[i] = True
            cnt[m["b_g"][i]] += 1
    bidx = np.flatnonzero(keep)
    pos_in_new = np.full(len(keep), -1, np.int64)
    pos_in_new[bidx] = np.arange(len(bidx))
    nb, F = len(bidx), len(names)
    syms = list_syms(args.cache_dir, "d5")
    XE = {o: np.full((G, F), np.nan, np.float32) for o in OFFS}
    XB = {o: np.full((nb, F), np.nan, np.float32) for o in OFFS}
    CVE = {o: np.zeros((G, 4), np.uint8) for o in OFFS}
    CVB = {o: np.zeros((nb, 4), np.uint8) for o in OFFS}
    b_sid = m["b_sid"][bidx]
    b_t = m["b_t"][bidx]
    b_g = m["b_g"][bidx]
    t0 = time.time()
    for sid, s in enumerate(syms):
        eg = np.flatnonzero(m["ev_sid"] == sid)
        bg = np.flatnonzero(b_sid == sid)
        if len(eg) == 0 and len(bg) == 0:
            continue
        X = np.load(fx / f"FFX_{s}.npy", mmap_mode="r")
        C = np.load(fx / f"COV_{s}.npy", mmap_mode="r")
        ot = np.load(Path(args.cache_dir) / "grid" / f"OT_{s}.npy")
        n = len(ot)
        ib = (b_t[bg] - FF.BAR_MS - ot[0]) // FF.BAR_MS
        for o in OFFS:
            ri = np.clip(m["ev_i0"][eg] - o, 0, n - 1)
            rb = np.clip(ib - o, 0, n - 1)
            if len(eg):
                XE[o][eg] = X[ri]
                CVE[o][eg] = C[ri]
            if len(bg):
                XB[o][bg] = X[rb]
                CVB[o][bg] = C[rb]
        if (sid + 1) % 60 == 0:
            print("[snap] %d/%d (%.0f sn)" % (sid + 1, len(syms), time.time() - t0), flush=True)
    for o in OFFS:
        np.save(fx / "snap" / f"XE_{o}.npy", XE[o])
        np.save(fx / "snap" / f"XB_{o}.npy", XB[o])
        np.save(fx / "snap" / f"CVE_{o}.npy", CVE[o])
        np.save(fx / "snap" / f"CVB_{o}.npy", CVB[o])
    np.savez(fx / "snap" / "meta2.npz", ev_t0=m["ev_t0"], ev_sid=m["ev_sid"], b_sid=b_sid, b_t=b_t, b_g=b_g, b_idx_old=bidx, names=np.array(names))
    same = float((m["ev_sid"][b_g] == b_sid).mean())
    print("[snap] olay %d, taban %d, özellik %d; tabanın olayla AYNI sembol payı %.3f (%.0f sn)" % (G, nb, F, same, time.time() - t0), flush=True)


# ------------------------------------------------------------------------------------------------ yardımcılar (istatistik)
def day_of(t_ms) -> np.ndarray:
    return K.day_idx(t_ms)


def boot_mean_ci(x: np.ndarray, cluster: np.ndarray, n_boot: int = 2000, seed: int = 3) -> tuple[float, float, float, float]:
    """Gün-kümeli bootstrap: (ortalama, SE, alt, üst %95). NaN atılır."""
    x = np.asarray(x, dtype=float)
    cl = np.asarray(cluster)
    m = np.isfinite(x)
    x, cl = x[m], cl[m]
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    _, inv = np.unique(cl, return_inverse=True)
    g = int(inv.max()) + 1
    mean = float(x.mean())
    if g < 3:
        return mean, float("nan"), float("nan"), float("nan")
    sm = np.bincount(inv, weights=x, minlength=g)
    ct = np.bincount(inv, minlength=g).astype(float)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(g, np.full(g, 1.0 / g), size=n_boot).astype(float)
    bm = (w @ sm) / np.maximum(w @ ct, 1.0)
    return mean, float(bm.std()), float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))


def group_auc_vec(p: np.ndarray, y: np.ndarray, g: np.ndarray, min_base: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Grup-içi AUC (olay skoru aynı gruptaki tabanlardan büyük payı; eşitlik ½) -> (grup kimliği, AUC); yalnız >= min_base tabanı olan gruplar."""
    ev = np.flatnonzero(y == 1)
    bmask = y == 0
    order = np.argsort(g[bmask], kind="stable")
    pb = p[bmask][order]
    gb = g[bmask][order]
    st = np.searchsorted(gb, g[ev], side="left")
    en = np.searchsorted(gb, g[ev], side="right")
    ids, vals = [], []
    for e, a, b in zip(ev, st, en):
        if b - a >= min_base:
            seg = pb[a:b]
            ids.append(g[e])
            vals.append(float((seg < p[e]).mean() + 0.5 * (seg == p[e]).mean()))
    return np.array(ids, dtype=np.int64), np.array(vals, dtype=float)


# ------------------------------------------------------------------------------------------------ rank
def _family_cols(names: list[str], prefix: str) -> np.ndarray:
    return np.array([j for j, nm in enumerate(names) if nm.startswith(prefix)], dtype=np.int64)


def stage_rank(args) -> None:
    from scripts import indearly_study as S1
    from app.rescan.confirm_elems import bh_adjust
    fx, old = Path(args.fx_dir), Path(args.old_fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx, b_g, t0g = mt["b_idx_old"], mt["b_g"], mt["ev_t0"]
    G = len(t0g)
    blk_ev = block_idx(t0g)
    day_ev = day_of(t0g)
    res = {"names": names, "family": {nm: FF.family_of(nm) for nm in names}, "rank": {}, "meta": {}, "wf": {}}
    t0 = time.time()
    for off in args.offsets:
        XE = np.load(fx / "snap" / f"XE_{off}.npy")
        XB = np.load(fx / "snap" / f"XB_{off}.npy")
        CVE = np.load(fx / "snap" / f"CVE_{off}.npy")
        CVB = np.load(fx / "snap" / f"CVB_{off}.npy")
        CE = np.load(old / "snap" / f"CE_{off}.npy")
        CB = np.load(old / "snap" / f"CB_{off}.npy", mmap_mode="r")[keep_idx]
        Cb = np.nan_to_num(np.asarray(CB, dtype=np.float32), nan=0.0)
        mu, sd = Cb.mean(axis=0), Cb.std(axis=0) + 1e-9
        Call = np.vstack([(np.nan_to_num(CE, nan=0.0) - mu) / sd, (Cb - mu) / sd]).astype(np.float64)
        yall = np.r_[np.ones(G), np.zeros(len(Cb))]
        gid = np.r_[np.arange(G), b_g]
        order = np.argsort(gid, kind="stable")
        gs = gid[order]
        starts = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1]])
        counts = np.diff(np.r_[starts, len(gs)])

        def dm(Z):
            Zs = Z[order]
            mean = np.add.reduceat(Zs, starts, axis=0) / counts[:, None]
            out_ = np.empty_like(Zs)
            out_[order] = Zs - np.repeat(mean, counts, axis=0)
            return out_
        Ddm = dm(np.column_stack([Call, yall]))
        med_all = np.nanmedian(XB, axis=0)
        med_all = np.where(np.isfinite(med_all), med_all, 0.0)
        recs: dict[str, dict] = {}
        meta_off = {"n_events": int(G), "fam": {}}
        pl_p, pl_pr, pl_nm = [], [], []
        for fam, ci in (("tf.", 0), ("fu.", 1)):
            cols = _family_cols(names, fam)
            ok_ev = CVE[:, ci] == 1
            b_ok = CVB[:, ci] == 1
            gidx, nv = S1.build_groups(np.where(b_ok, b_g, -1), G)
            obs, perm, pg, gi = S1.matched_stats(XE, XB, gidx, nv, cols, B=args.n_perm, seed=args.seed + off, groups_ok=ok_ev)
            blk_g = blk_ev[gi]
            blk = {b: (pg[blk_g == b].mean(axis=0) if (blk_g == b).sum() >= 20 else np.full(len(cols), np.nan)) for b in range(3)}
            obs_r = np.empty(len(cols))
            perm_r = np.empty((args.n_perm, len(cols)), np.float32)
            pg_r = np.empty((len(gi), len(cols)), np.float32)
            CH = 48
            for a in range(0, len(cols), CH):
                cc = cols[a: a + CH]
                Yb = np.where(np.isfinite(XB[:, cc]), XB[:, cc], med_all[cc]).astype(np.float64)
                Ye = np.where(np.isfinite(XE[:, cc]), XE[:, cc], med_all[cc]).astype(np.float64)
                Yall = np.vstack([Ye, Yb])
                coef, *_ = np.linalg.lstsq(Ddm, dm(Yall), rcond=None)
                Rall = Yall - Call @ coef[:-1]
                Re, Rb = Rall[:G].astype(np.float32), Rall[G:].astype(np.float32)
                o_, pm_, pg_, _ = S1.matched_stats(Re, Rb, gidx, nv, np.arange(len(cc)), B=args.n_perm, seed=args.seed + off, groups_ok=ok_ev)
                obs_r[a: a + len(cc)] = o_
                perm_r[:, a: a + len(cc)] = pm_
                pg_r[:, a: a + len(cc)] = pg_
            blk_r = {b: (pg_r[blk_g == b].mean(axis=0) if (blk_g == b).sum() >= 20 else np.full(len(cols), np.nan)) for b in range(3)}
            p, pf = S1.pvals_from_perm(obs, perm)
            pr, prf = S1.pvals_from_perm(obs_r, perm_r)
            nan_share = np.isnan(XE[ok_ev][:, cols]).mean(axis=0)
            for a, j in enumerate(cols):
                nm = names[j]
                dev, dev_r = obs[a] - 0.5, obs_r[a] - 0.5
                cons = sum(1 for b in range(3) if np.isfinite(blk[b][a]) and dev != 0 and np.sign(blk[b][a] - 0.5) == np.sign(dev))
                cons_r = sum(1 for b in range(3) if np.isfinite(blk_r[b][a]) and dev_r != 0 and np.sign(blk_r[b][a] - 0.5) == np.sign(dev_r))
                recs[nm] = {"feature": nm, "family": FF.family_of(nm), "auc": float(obs[a]), "p": float(p[a]), "p_fwer": float(pf[a]),
                            "auc_resid": float(obs_r[a]), "p_resid": float(pr[a]), "p_fwer_resid": float(prf[a]),
                            "blk": [float(blk[b][a]) for b in range(3)], "blk_resid": [float(blk_r[b][a]) for b in range(3)],
                            "consist": cons, "consist_resid": cons_r, "nan_share": float(nan_share[a])}
            # blok-dışı seçim: diğer iki blokta artık-AUC sapması en büyük 10 özellik (işaret oradan), değerlendirme kalan blokta
            wf = []
            for k in range(3):
                oth = (blk_g >= 0) & (blk_g != k)
                tk = blk_g == k
                if oth.sum() < 100 or tk.sum() < 30:
                    continue
                dev_o = pg_r[oth].mean(axis=0) - 0.5
                top = np.argsort(-np.abs(dev_o))[:10]
                sg = np.sign(dev_o[top])
                adj = np.where(sg[None, :] > 0, pg_r[tk][:, top], 1.0 - pg_r[tk][:, top])
                mean, se, lo, hi = boot_mean_ci(adj.mean(axis=1), day_ev[gi][tk])
                wf.append({"block": k, "n_groups": int(tk.sum()), "top": [names[cols[t]] for t in top], "sign": sg.tolist(), "sel_dev": dev_o[top].tolist(),
                           "auc_mean": mean, "se": se, "lo": lo, "hi": hi, "n_pos": int((adj.mean(axis=0) > 0.5).sum()), "best1": float(adj.mean(axis=0).max())})
            res["wf"].setdefault(off, {})[fam] = wf
            meta_off["fam"][fam] = {"n_cols": int(len(cols)), "events_ok": int(ok_ev.sum()), "groups_used": int(len(gi)), "baseline_ok": float(b_ok.mean()),
                                    "fwer_thr": float(np.quantile(np.abs(perm - 0.5).max(axis=1), 0.95)), "fwer_thr_resid": float(np.quantile(np.abs(perm_r - 0.5).max(axis=1), 0.95)),
                                    "n_sig_fwer": int((pf < 0.05).sum()), "n_sig_fwer_resid": int((prf < 0.05).sum())}
            pl_p.append(p)
            pl_pr.append(pr)
            pl_nm += [names[j] for j in cols]
            print("[rank] %s %s: grup %d; ham FWER<0,05 %d; artık FWER<0,05 %d (%.0f sn)" % (OFF_LABEL[off], fam, len(gi), (pf < 0.05).sum(), (prf < 0.05).sum(), time.time() - t0), flush=True)
            del perm, perm_r, pg, pg_r
        q = bh_adjust(np.concatenate(pl_p))
        qr = bh_adjust(np.concatenate(pl_pr))
        for nm, a, b in zip(pl_nm, q, qr):
            recs[nm]["q"] = float(a)
            recs[nm]["q_resid"] = float(b)
        res["rank"][off] = [recs[nm] for nm in names]
        meta_off["n_sig_q05"] = int((q < 0.05).sum())
        meta_off["n_sig_q05_resid"] = int((qr < 0.05).sum())
        res["meta"][off] = meta_off
        del XE, XB
    pickle.dump(res, open(Path(args.out_dir) / "rank.pkl", "wb"))
    print("[rank] bitti (%.0f sn)" % (time.time() - t0), flush=True)


# ------------------------------------------------------------------------------------------------ multi
VARIANTS = ["mevcut 154", "+ tf", "+ fu", "+ tf + fu", "yalnız tf+fu"]


def stage_multi(args) -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    fx, old = Path(args.fx_dir), Path(args.old_fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx, b_g, t0g = mt["b_idx_old"], mt["b_g"], mt["ev_t0"]
    G = len(t0g)
    blk_ev = block_idx(t0g)
    day_ev = day_of(t0g)
    tfc, fuc = _family_cols(names, "tf."), _family_cols(names, "fu.")
    rng = np.random.default_rng(args.seed)
    sel = np.zeros(len(b_g), bool)
    cnt = np.zeros(G, int)
    for i in rng.permutation(len(b_g)):
        if cnt[b_g[i]] < 12:
            sel[i] = True
            cnt[b_g[i]] += 1
    bi = np.flatnonzero(sel)
    out = {}
    t0 = time.time()
    for off in args.offsets_multi:
        GE = np.load(old / "snap" / f"GE_{off}.npy")
        GB = np.load(old / "snap" / f"GB_{off}.npy", mmap_mode="r")[keep_idx][bi]
        XE = np.load(fx / "snap" / f"XE_{off}.npy")
        XB = np.load(fx / "snap" / f"XB_{off}.npy", mmap_mode="r")[bi]
        CVE = np.load(fx / "snap" / f"CVE_{off}.npy")
        CVB = np.load(fx / "snap" / f"CVB_{off}.npy")[bi]
        y = np.r_[np.ones(G), np.zeros(len(bi))].astype(int)
        grp = np.r_[np.arange(G), b_g[bi]]
        blk = np.r_[blk_ev, blk_ev[b_g[bi]]]
        cv = np.vstack([CVE, CVB])
        G154 = np.vstack([GE, GB]).astype(np.float32)
        XA = np.vstack([XE, XB]).astype(np.float32)
        mats = {"mevcut 154": G154, "+ tf": np.hstack([G154, XA[:, tfc]]), "+ fu": np.hstack([G154, XA[:, fuc]]),
                "+ tf + fu": np.hstack([G154, XA[:, tfc], XA[:, fuc]]), "yalnız tf+fu": np.hstack([XA[:, tfc], XA[:, fuc]])}
        subsets = {"aynı alt küme (tf+fu var)": (cv[:, 0] == 1) & (cv[:, 1] == 1) & (blk >= 0), "tüm (tf var)": (cv[:, 0] == 1) & (blk >= 0)}
        res = {}
        for sn, sm in subsets.items():
            rows = np.flatnonzero(sm)
            r_sub = {"n_events": int((sm & (y == 1)).sum()), "n_rows": int(len(rows)), "variants": {}}
            vlist = VARIANTS if sn.startswith("aynı") else ["mevcut 154", "+ tf"]
            raw: dict[str, dict] = {}
            for vn in vlist:
                Xm = mats[vn][rows]
                ys, gs_, bs_ = y[rows], grp[rows], blk[rows]
                folds = {}
                for scheme in ("blok-dışı", "ileri"):
                    fl = []
                    for k in range(3):
                        if scheme == "ileri" and k == 0:
                            continue
                        tr_ = (bs_ >= 0) & ((bs_ != k) if scheme == "blok-dışı" else (bs_ < k))
                        te_ = bs_ == k
                        if te_.sum() < 50 or tr_.sum() < 200 or len(np.unique(ys[tr_])) < 2:
                            continue
                        clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                                            class_weight="balanced", random_state=0)
                        clf.fit(Xm[tr_], ys[tr_])
                        pp = clf.predict_proba(Xm[te_])[:, 1]
                        gi_, av = group_auc_vec(pp, ys[te_], gs_[te_])
                        fl.append({"block": k, "auc": float(roc_auc_score(ys[te_], pp)), "auc_group": float(av.mean()), "groups": gi_, "g_auc": av, "g_day": day_ev[gi_]})
                    folds[scheme] = fl
                raw[vn] = folds
                r_sub["variants"][vn] = {sc: [{"block": f["block"], "auc": f["auc"], "auc_group": f["auc_group"]} for f in fl] for sc, fl in folds.items()}
                print("[multi] %s %s %s: " % (OFF_LABEL[off], sn, vn) + " | ".join("%s %s" % (sc, ", ".join("%.3f" % f["auc_group"] for f in fl)) for sc, fl in folds.items()) + " (%.0f sn)" % (time.time() - t0), flush=True)
                del Xm
            diffs = {}
            base = raw["mevcut 154"]
            for vn in raw:
                if vn == "mevcut 154":
                    continue
                dv = {}
                for scheme in ("blok-dışı", "ileri"):
                    per_blk, allg, alld = [], [], []
                    for fb, fv in zip(base[scheme], raw[vn][scheme]):
                        common, ia, ib = np.intersect1d(fb["groups"], fv["groups"], return_indices=True)
                        d = fv["g_auc"][ib] - fb["g_auc"][ia]
                        m_, se_, lo_, hi_ = boot_mean_ci(d, fb["g_day"][ia])
                        per_blk.append({"block": fb["block"], "diff": float(d.mean()), "n": int(len(d)), "se": se_, "lo": lo_, "hi": hi_})
                        allg.append(d)
                        alld.append(fb["g_day"][ia])
                    if allg:
                        m_, se_, lo_, hi_ = boot_mean_ci(np.concatenate(allg), np.concatenate(alld))
                        dv[scheme] = {"per_block": per_blk, "pooled": {"diff": m_, "se": se_, "lo": lo_, "hi": hi_, "n": int(sum(len(a) for a in allg))}}
                diffs[vn] = dv
            r_sub["diffs"] = diffs
            res[sn] = r_sub
            del raw
        out[off] = res
        del GE, GB, XE, XB, mats
    pickle.dump(out, open(Path(args.out_dir) / "multi.pkl", "wb"))
    print("[multi] bitti (%.0f sn)" % (time.time() - t0), flush=True)


# ------------------------------------------------------------------------------------------------ HA özellikleri
def stage_hafeat(args) -> None:
    fx = Path(args.fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    ev = pickle.load(open(K.OUT / "events_ha.pkl", "rb"))
    Pp = K.load_prep("ha")
    ok_ev = Pp["ev_ok"].astype(bool)
    n = len(ev["t_ms"])
    X = np.full((n, len(names)), np.nan, np.float32)
    CV = np.zeros((n, 4), np.uint8)
    have = {p.stem[4:] for p in fx.glob("FFX_*.npy")}
    miss = set()
    t0 = time.time()
    for s in sorted(set(ev["sym"][ok_ev].tolist())):
        if s not in have:
            miss.add(s)
            continue
        idx = np.flatnonzero((ev["sym"] == s) & ok_ev)
        ot = np.load(Path(args.cache_dir) / "grid" / f"OT_{s}.npy").astype(np.int64)
        i = P.snapshot_index(ot, FF.BAR_MS, ev["t_ms"][idx])
        good = i >= 0
        FX = np.load(fx / f"FFX_{s}.npy", mmap_mode="r")
        C = np.load(fx / f"COV_{s}.npy", mmap_mode="r")
        X[idx[good]] = FX[i[good]]
        CV[idx[good]] = C[i[good]]
    np.savez_compressed(Path(args.out_dir) / "feats_ha.npz", names=np.array(names), X=X, CV=CV)
    print("[hafeat] olay %d (pencereli %d); kapsam tf %.3f fu %.3f bd %.3f; ızgarada olmayan sembol %d (%.0f sn)" %
          (n, int(ok_ev.sum()), CV[ok_ev, 0].mean(), CV[ok_ev, 1].mean(), CV[ok_ev, 2].mean(), len(miss), time.time() - t0), flush=True)


# ------------------------------------------------------------------------------------------------ HA süzgeci (b)
def _blk_row(st, mask: np.ndarray, b: int) -> dict:
    """Blok b'de `mask` alt kümesi: n, net, net-taban, isabet (gün-kümeli SE)."""
    from app.rescan import exit_sim as XS
    m = mask & st.valid & (st.pop.block == b)
    n = int(m.sum())
    if n < 5:
        return {"n": n}
    day = st.pop.day[m]
    net = st.net[m]
    ex = st.ex_net[m]
    exm = np.isfinite(ex)
    return {"n": n, "net": float(net.mean()), "se": float(XS.cluster_se(net, day)), "ex": float(ex[exm].mean()) if exm.any() else float("nan"),
            "ex_se": float(XS.cluster_se(ex[exm], day[exm])) if exm.sum() > 3 else float("nan"), "hit": float(st.hit[m].mean())}


def stage_ha(args) -> None:
    from scripts import indfilter_study as S
    t0 = time.time()
    z = np.load(Path(args.out_dir) / "feats_ha.npz", allow_pickle=False)
    names = [str(s) for s in z["names"]]
    X = z["X"].astype(np.float32)
    X[~np.isfinite(X)] = np.nan
    st = S.Study("ha", BLOCK_LABELS)
    st.names = names
    st.X = X
    p = st.pop
    nb = 3
    res = {"names": names, "n_events": int(p.n), "n_valid": int(st.valid.sum()), "labels": BLOCK_LABELS}
    allm = np.ones(p.n, bool)
    res["pop"] = [_blk_row(st, allm, b) for b in range(nb)]
    cov_ok = z["CV"]
    res["cover"] = {"tf": float(cov_ok[st.valid, 0].mean()), "fu": float(cov_ok[st.valid, 1].mean()), "bd": float(cov_ok[st.valid, 2].mean())}
    # --- 1. kısmi Spearman sıralaması (ATR + hedef/ATR kontrollü), BH q, blok tutarlılığı
    rows = S.rank_features(st, st.valid)
    for r in rows:
        r["family"] = FF.family_of(r["name"])
    res["rank"] = rows
    for key in ("par_exn", "par_net", "par_hit", "raw_net"):
        k5 = sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.05)
        print("[ha] q<0,05 %s: %d / %d" % (key, k5, len(rows)), flush=True)
    # --- 2. blok-dışı seçilmiş en iyi özelliklerde tersil analizi (yön + kenarlar yalnız seçim bloklarından)
    valid = st.valid
    day = p.day
    sel_rows = []
    pr = {}
    for b in range(nb):
        selm = valid & (p.block != b) & (p.block >= 0)
        for j, nm in enumerate(names):
            x = X[:, j].astype(float)
            if not K.support_ok(x[selm], day[selm]):
                continue
            r = K.partial_spearman(x[selm], st.ex_net[selm], st.ctrl[selm], day[selm])
            pr[(b, j)] = r
    tert = {}
    for j, nm in enumerate(names):
        rec = {"name": nm, "family": FF.family_of(nm), "blocks": []}
        ok_all = True
        for b in range(nb):
            r = pr.get((b, j))
            if r is None or not np.isfinite(r["r"]):
                ok_all = False
                rec["blocks"].append(None)
                continue
            selm = valid & (p.block != b) & (p.block >= 0)
            x = X[:, j].astype(float)
            lo_e, hi_e = np.nanquantile(x[selm], [1 / 3, 2 / 3])
            fav = (x >= hi_e) if r["r"] > 0 else (x <= lo_e)
            unf = (x <= lo_e) if r["r"] > 0 else (x >= hi_e)
            if lo_e == hi_e:
                fav = np.isfinite(x) & (x > hi_e) if r["r"] > 0 else np.isfinite(x) & (x < lo_e)
                unf = np.isfinite(x) & (x < lo_e) if r["r"] > 0 else np.isfinite(x) & (x > hi_e)
            rec["blocks"].append({"sel_r": r["r"], "sel_t": r["t"], "fav": _blk_row(st, fav, b), "unf": _blk_row(st, unf, b), "all": res["pop"][b]})
        rec["ok"] = ok_all
        tert[nm] = rec
    res["tercile"] = tert
    # --- 3. her dönüşümde en iyi 10 seçilmiş özellik: değerlendirme bloğunda favori tersil neti
    top10 = []
    for b in range(nb):
        cand = [(abs(pr[(b, j)]["t"]), j) for j in range(len(names)) if (b, j) in pr and np.isfinite(pr[(b, j)]["t"])]
        cand.sort(reverse=True)
        top10.append([names[j] for _, j in cand[:10]])
    res["top10"] = top10
    # --- 4. kural arama rotasyonu: seçim bloğunda seç, diğer iki blokta DOKUNMADAN değerlendir
    rules = []
    for s_blk in range(nb):
        rs = S.RuleSearch(st, st.blk(s_blk))
        min_n = max(150, int(0.1 * st.blk(s_blk).sum()))
        for tag, y in (("net", st.net), ("ex", st.ex_net)):
            sc = rs.score_all(y, min_n)
            used: set = set()
            for i, (t, n_, mean, c) in enumerate(S.pick_rules(rs, sc, 6, used)):
                keep = rs.mask(c)
                rules.append({"sel_block": s_blk, "target": tag, "id": "%s%d_%d" % (tag, s_blk + 1, i + 1), "text": S.rule_text(st, c), "sel_t": t, "sel_n": n_, "sel_mean": mean,
                              "blocks": [_blk_row(st, keep, b) for b in range(nb)]})
            # seçim sonrası: ilk 300 aday için tüm blok netleri (aşırı-uyum tanısı)
            allc = []
            for t, n_, mean, c in sc[:300]:
                keep = rs.mask(c)
                bl = [_blk_row(st, keep, b) for b in range(nb)]
                if all(x.get("n", 0) >= 30 for x in bl):
                    allc.append({"text": S.rule_text(st, c), "sel_t": t, "net": [x["net"] for x in bl], "ex": [x["ex"] for x in bl], "n": [x["n"] for x in bl]})
            res.setdefault("cands", {})[(s_blk, tag)] = allc
        res["n_cand"] = len(rs.cands)
    res["rules"] = rules
    pickle.dump(res, open(Path(args.out_dir) / "ha.pkl", "wb"))
    print("[ha] bitti (%.0f sn); kural adayı %d" % (time.time() - t0, res["n_cand"]), flush=True)


# ------------------------------------------------------------------------------------------------ sinyaller (c)
SIGNALS = {
    "whale_flat_abs": "balina alım patlaması: 5 dk net balina alımı >= 100 bin TRY ve fiyat yatay (|getiri5| <= %0,3)",
    "whale_flat_rel": "balina alım patlaması (göreli): 5 dk net balina alımı >= sembolün tipik 5 dk hacmi ve fiyat yatay",
    "whale_15": "15 dk net balina alımı >= 200 bin TRY ve fiyat henüz <= %0,4 yükselmiş",
    "bigbuy_dom": "büyük işlem alım baskınlığı: 15 dk büyük-alım payı >= %80, >= 3 büyük işlem, alıcı payı >= %60",
    "absorb_buy": "emilim: 15 dk büyük-alım payı >= %70, >= 2 büyük işlem, fiyat düşmüyor/yatay (getiri15 <= 0)",
    "flow_surge": "akış ivmesi: alıcı payı15 >= %65, ivme >= 0,10 ve işlem sayısı z15 >= 1,5",
    "oi_px_up": "fiyat↑ + OI↑ (15 dk: getiri >= %0,5, OI >= +%0,5) ve fonlama aşırı değil (z <= 1,5, <= 5 bps)",
    "short_cover": "short kapatma sıkışması: getiri15 >= %0,5, OI15 <= -%0,3, taker L/S ivmesi > 0",
    "bid_imb": "defter alış dengesizliği ±%2 >= 0,3 ve yükseliyor (3 bar)",
    "crowded_short": "kalabalık short: fonlama <= -2 bps ve OI60 >= +%1",
    "basis_lead": "perp primi TRY spotun önünde: baz değişimi15 >= +15 bps ve baz z >= 1,5",
    "taker_surge": "vadeli taker L/S z >= 2",
    "big_oi": "büyük-alım payı15 >= %70 ve OI15 >= +%0,3",
}


def signal_masks(F: dict, c5: np.ndarray) -> dict[str, np.ndarray]:
    """Önceden belirlenmiş sinyal koşulları (eşikler SABİT, veriden ayarlanmadı). NaN -> False."""
    r1 = FF.log_ret(c5, 1)
    r3 = FF.log_ret(c5, 3)

    def ok(*conds):
        m = np.ones(len(c5), bool)
        for c in conds:
            with np.errstate(invalid="ignore"):
                m &= np.asarray(c, dtype=bool) & True
        return m
    g = lambda k: F[k].astype(float)  # noqa: E731
    with np.errstate(invalid="ignore"):
        return {
            "whale_flat_abs": ok(g("tf.whale_net_5") >= 5.0, np.abs(r1) <= 0.003),
            "whale_flat_rel": ok(g("tf.whale_net_rel_5") >= 1.0, np.abs(r1) <= 0.003),
            "whale_15": ok(g("tf.whale_net_15") >= np.log10(200_001.0), r3 <= 0.004),
            "bigbuy_dom": ok(g("tf.bigbuy_share_15") >= 0.8, g("tf.bigcnt_15") >= np.log1p(3) - 1e-9, g("tf.buy_share_15") >= 0.6),
            "absorb_buy": ok(g("tf.bigbuy_share_15") >= 0.7, g("tf.bigcnt_15") >= np.log1p(2) - 1e-9, r3 <= 0.0),
            "flow_surge": ok(g("tf.buy_share_15") >= 0.65, g("tf.flow_acc") >= 0.10, g("tf.ntr_z_15") >= 1.5),
            "oi_px_up": ok(r3 >= 0.005, g("fu.oi_chg_15") >= 0.5, g("fu.fund_z") <= 1.5, g("fu.fund_bps") <= 5.0),
            "short_cover": ok(r3 >= 0.005, g("fu.oi_chg_15") <= -0.3, g("fu.taker_ls_acc") > 0),
            "bid_imb": ok(g("fu.bd_imb2") >= 0.3, g("fu.bd_imb2_d3") > 0),
            "crowded_short": ok(g("fu.fund_bps") <= -2.0, g("fu.oi_chg_60") >= 1.0),
            "basis_lead": ok(g("fu.basis_d15") >= 15.0, g("fu.basis_z") >= 1.5),
            "taker_surge": ok(g("fu.taker_ls_z") >= 2.0),
            "big_oi": ok(g("tf.bigbuy_share_15") >= 0.7, g("fu.oi_chg_15") >= 0.3),
        }


def stage_sweep(args) -> None:
    from scripts import indearly_signals as S2
    from scripts.pattern90_analysis import cooldown_idx
    fx = Path(args.fx_dir)
    cache = Path(args.cache_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    col = {nm: j for j, nm in enumerate(names)}
    need = sorted({nm for nm in names if nm in ("tf.whale_net_5", "tf.whale_net_rel_5", "tf.whale_net_15", "tf.bigbuy_share_15", "tf.bigcnt_15", "tf.buy_share_15", "tf.flow_acc", "tf.ntr_z_15",
                                                 "fu.oi_chg_15", "fu.oi_chg_60", "fu.fund_z", "fu.fund_bps", "fu.taker_ls_acc", "fu.bd_imb2", "fu.bd_imb2_d3", "fu.basis_d15", "fu.basis_z", "fu.taker_ls_z")})
    gn = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    gneed = [gn.index(x) for x in S2.NEED]
    syms = list_syms(args.cache_dir, "d5")
    (fx / "sig").mkdir(exist_ok=True)
    acc = {k: {"sid": [], "row": [], "t": [], "out": []} for k in SIGNALS}
    raw_cnt = {k: 0 for k in SIGNALS}
    valid_t = {}
    lun = {"G:" + k: [] for k in SIGNALS}
    lw = (parse_day("2026-10-17"), parse_day("2026-10-17") + 4 * 3_600_000)
    thr = np.log10(MIN_QUOTE)
    t0 = time.time()
    for sid, s in enumerate(syms):
        ot = np.load(cache / "grid" / f"OT_{s}.npy").astype(np.int64)
        t_dec = ot + P.BAR_5M_MS
        Gm = np.load(cache / "grid" / f"G_{s}.npy", mmap_mode="r")
        sub = np.asarray(Gm[:, gneed])
        n5 = len(ot)
        v = (np.arange(n5) >= WARM_BARS) & (sub[:, 0] >= thr) & np.isfinite(sub[:, 1:]).all(axis=1)
        valid_t[sid] = t_dec[v]
        FX = np.load(fx / f"FFX_{s}.npy", mmap_mode="r")
        F = {nm: np.asarray(FX[:, col[nm]]) for nm in need}
        c5 = np.load(cache / "grid" / f"F5_{s}.npy", mmap_mode="r")[:, COL_C].astype(float)
        OS = np.load(cache / "grid" / f"OS_{s}.npy")
        for key, m in signal_masks(F, c5).items():
            m = m & v
            idx = np.flatnonzero(m)
            raw_cnt[key] += len(idx)
            if s == "LUNATRY":
                lun["G:" + key] = [fmt_t(int(t_dec[i]), "%H:%M") for i in idx if lw[0] <= t_dec[i] <= lw[1]]
            idx = cooldown_idx(idx, S2.SIG_COOLDOWN)
            if len(idx):
                idx = idx[OS[idx, 0] == 1]
            if len(idx) == 0:
                continue
            a = acc[key]
            a["sid"].append(np.full(len(idx), sid, np.int16))
            a["row"].append(idx.astype(np.int32))
            a["t"].append(t_dec[idx])
            a["out"].append(OS[idx, 1:].astype(np.float32))
    for key, a in acc.items():
        if a["sid"]:
            sidv, tv, ov, rv = (np.concatenate(a[k]) for k in ("sid", "t", "out", "row"))
            od = np.argsort(tv, kind="stable")
            sidv, tv, ov, rv = sidv[od], tv[od], ov[od], rv[od]
        else:
            sidv = np.zeros(0, np.int16); tv = np.zeros(0, np.int64); ov = np.zeros((0, 9), np.float32); rv = np.zeros(0, np.int32)
        np.savez(fx / "sig" / f"G_{key}.npz", sid=sidv, t=tv, out=ov, row=rv)
    pickle.dump({"valid_t": valid_t, "lunatry": lun}, open(fx / "sweep_extra.pkl", "wb"))
    json.dump(raw_cnt, open(Path(args.out_dir) / "sweep_raw_counts.json", "w"))
    print("[sweep] bitti (%.0f sn); ham (cooldown öncesi) sayılar: %s" % (time.time() - t0, raw_cnt), flush=True)


def sig_guide() -> list[str]:
    return ["%s (%s)" % (k, v) for k, v in SIGNALS.items()]


def stage_eval(args) -> None:
    from scripts import indearly_signals as S2
    from scripts import indearly_study as S1
    out = Path(args.out_dir)
    (out / "sig").mkdir(exist_ok=True)
    fx = Path(args.fx_dir)
    for k in SIGNALS:
        (out / "sig" / f"G_{k}.npz").write_bytes((fx / "sig" / f"G_{k}.npz").read_bytes())
    if not (out / "cands.json").exists():
        (out / "cands.json").write_text(json.dumps({"summary": {}, "cands": []}), encoding="utf-8")
    orig = S1.periods

    def periods_ha():
        per = orig()
        bl = blocks()
        per["blk1"], per["blk2"], per["blk3"] = [bl[0]], [bl[1]], [bl[2]]
        return per
    S1.periods = periods_ha
    S2.GUIDE = sig_guide()
    try:
        S2.stage_eval(args)
    finally:
        S1.periods = orig


# ------------------------------------------------------------------------------------------------ koşulsuz zamanlama: tüm geçerli anlarda özellik uçları -> 60 dk brüt getiri
LEAD_FEATS = ["fu.basis_z", "fu.basis_d15", "fu.basis_d60", "fu.oi_chg_15", "fu.oi_chg_60", "fu.taker_ls_z", "fu.tt_ls_d12", "fu.fund_bps", "fu.bd_imb2", "fu.bd_imb2_d3",
              "tf.ntr_z_15", "tf.bigcnt_z_15", "tf.whale_net_rel_5", "tf.whale_net_rel_60", "tf.buy_share_15", "tf.bigbuy_share_15", "tf.absorb_buy_15", "tf.net_acc", "tf.cvd_slope_60"]
COST_PCT = 2 * 0.1125 + 2 * 0.15


def stage_lead(args) -> None:
    """Her geçerli 5 dk anında (15 dk'da bir örnek) özellik beşte-birlik uçları -> sonraki 60 dk BRÜT getiri (%). Maliyet duvarı ~%0,525 (ücret + kayma, 2 bacak)."""
    from app.rescan import exit_sim as XS
    from scripts import indearly_signals as S2
    fx, cache = Path(args.fx_dir), Path(args.cache_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    cols = [names.index(f) for f in LEAD_FEATS]
    gn = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    gneed = [gn.index(x) for x in S2.NEED]
    thr = np.log10(MIN_QUOTE)
    syms = list_syms(args.cache_dir, "d5")
    Xs, Rs, Ts, Ss = [], [], [], []
    for sid, s in enumerate(syms):
        ot = np.load(cache / "grid" / f"OT_{s}.npy").astype(np.int64)
        n5 = len(ot)
        Gm = np.load(cache / "grid" / f"G_{s}.npy", mmap_mode="r")
        sub = np.asarray(Gm[:, gneed])
        v = (np.arange(n5) >= WARM_BARS) & (sub[:, 0] >= thr) & np.isfinite(sub[:, 1:]).all(axis=1)
        v &= (np.arange(n5) % 3 == 0) & (np.arange(n5) + 12 < n5)
        idx = np.flatnonzero(v)
        if len(idx) == 0:
            continue
        c5 = np.load(cache / "grid" / f"F5_{s}.npy", mmap_mode="r")[:, COL_C].astype(float)
        r = (c5[idx + 12] / c5[idx] - 1.0) * 100.0
        FX = np.load(fx / f"FFX_{s}.npy", mmap_mode="r")
        Xs.append(np.asarray(FX[idx][:, cols]))
        Rs.append(r)
        Ts.append(ot[idx] + P.BAR_5M_MS)
        Ss.append(np.full(len(idx), sid, np.int16))
    X = np.vstack(Xs)
    R = np.concatenate(Rs)
    T = np.concatenate(Ts)
    np.savez(fx / "lead_samples.npz", X=X.astype(np.float32), R=R.astype(np.float32), T=T, S=np.concatenate(Ss), feats=np.array(LEAD_FEATS))
    blk = block_idx(T)
    day = day_of(T)
    out = {"n": int(len(R)), "feats": {}, "cost": COST_PCT, "labels": BLOCK_LABELS, "base": []}
    for b in range(3):
        m = blk == b
        out["base"].append({"n": int(m.sum()), "mean": float(R[m].mean()), "se": float(XS.cluster_se(R[m], day[m]))})
    for j, f in enumerate(LEAD_FEATS):
        x = X[:, j].astype(float)
        fin = np.isfinite(x)
        if fin.sum() < 1000 or np.ptp(x[fin]) == 0:
            continue
        q20, q80, q05, q95 = np.nanquantile(x, [0.2, 0.8, 0.05, 0.95])
        rec = {"cover": float(fin.mean()), "blocks": []}
        for b in range(3):
            m = blk == b
            row = {}
            for tag, mk in (("top20", x >= q80), ("bot20", x <= q20), ("top5", x >= q95), ("bot5", x <= q05)):
                k = m & mk & fin
                if k.sum() >= 50:
                    row[tag] = {"n": int(k.sum()), "mean": float(R[k].mean()), "se": float(XS.cluster_se(R[k], day[k]))}
            rec["blocks"].append(row)
        out["feats"][f] = rec
    pickle.dump(out, open(Path(args.out_dir) / "lead.pkl", "wb"))
    print("[lead] örnek %d; bitti" % len(R), flush=True)


def stage_timing(args) -> None:
    """NEDENSELLİK ÖLÇÜMÜ: vadeli satırlarından türetilen fiyatın (OI notional/OI; defter notional/derinlik) TRY spot/USDTTRY fiyatıyla getiri korelasyonu, dakika gecikmesine göre.
    metrics ts_ms satırı spotun ts+5 dk'daki fiyatıyla örtüşür (dilim SONUNDA ölçülür); bookdepth ts_ms gerçek anlık görüntü zamanıdır."""
    conn = K.get_conn()

    def cand(sym, tf):
        a = _arr(conn.execute("SELECT open_time, close FROM historical_candles WHERE symbol=%s AND timeframe=%s ORDER BY open_time", (sym, tf)).fetchall(), 2)
        return a
    usd = cand("USDTTRY", "1m")
    du = dict(zip(usd[:, 0].astype(np.int64), usd[:, 1]))
    out = {}
    for sym, perp in (("BTCTRY", "BTCUSDT"), ("ETHTRY", "ETHUSDT"), ("SOLTRY", "SOLUSDT"), ("BNBTRY", "BNBUSDT")):
        a = cand(sym, "1m")
        sp = {}
        for ot, cl in a:
            ot = int(ot)
            if ot in du:
                sp[ot + 60000] = cl / du[ot]
        for nm, q in (("metrics", "SELECT ts_ms, sum_open_interest_value/sum_open_interest FROM hist_futures_metrics WHERE perp_symbol=%s AND sum_open_interest>0 AND sum_open_interest_value>0 ORDER BY ts_ms"),
                      ("bookdepth", "SELECT ts_ms, (bid_n1/bid_d1+ask_n1/ask_d1)/2 FROM hist_futures_bookdepth WHERE perp_symbol=%s AND bid_d1>0 AND ask_d1>0 ORDER BY ts_ms")):
            m = _arr(conn.execute(q, (perp,)).fetchall(), 2)
            keys, pm = m[:, 0].astype(np.int64), m[:, 1]
            cors = {}
            for lag_min in range(-6, 12):
                x, y = [], []
                for i in range(1, len(pm)):
                    if keys[i] - keys[i - 1] > 330_000:
                        continue
                    t1 = int(round(keys[i] / 60000.0)) * 60000 + lag_min * 60000
                    t0_ = int(round(keys[i - 1] / 60000.0)) * 60000 + lag_min * 60000
                    if t1 in sp and t0_ in sp:
                        x.append(np.log(pm[i] / pm[i - 1]))
                        y.append(np.log(sp[t1] / sp[t0_]))
                if len(x) > 1000:
                    cors[lag_min] = float(np.corrcoef(x, y)[0, 1])
            best = max(cors, key=cors.get)
            out["%s|%s" % (sym, nm)] = {"best_lag_min": best, "corr_best": cors[best], "corr_0": cors.get(0), "corr_5": cors.get(5)}
    conn.close()
    json.dump(out, open(Path(args.out_dir) / "timing.json", "w"), indent=1)
    print("[timing] " + json.dumps(out), flush=True)


class _SimEnv:
    """indearly_signals.sim_many için asgari Env (yalnız cache_dir ve sembol listesi gerekir)."""

    def __init__(self, args):
        self.args = args
        self.syms = list_syms(args.cache_dir, "d5")


def stage_leadsim(args) -> None:
    """Baz / akış uçlarındaki anlara GERÇEKÇİ doluşlu (60 sn gecikme, %0,15 kayma, ücret) giriş: TP1,5/SL3/T60, TP2/SL3/T60, iz 1,0/0,8 ve saf 60 dk tut (SL3).
    Koşulsuz rastgele girişlerle (aynı örneklem havuzu) karşılaştırılır."""
    from app.rescan import exit_sim as XS
    from scripts import indearly_signals as S2
    fx = Path(args.fx_dir)
    z = np.load(fx / "lead_samples.npz")
    X, T, S, feats = z["X"], z["T"], z["S"].astype(np.int64), [str(f) for f in z["feats"]]
    blk = block_idx(T)
    day = day_of(T)
    rng = np.random.default_rng(args.seed + 99)
    CAP = 25_000
    spec_all = list(S2.SPECS) + [XS.ExitSpec("60 dk tut SL3", "fixed", sl=3.0, time_min=60)]
    sets = {}
    meta = {}

    def add(name, mask_fn):
        for b in range(3):
            idx = np.flatnonzero(mask_fn() & (blk == b))
            if len(idx) > CAP:
                idx = rng.choice(idx, CAP, replace=False)
            sets["%s|%d" % (name, b)] = (S[idx], T[idx])
            meta["%s|%d" % (name, b)] = idx
    add("rastgele", lambda: np.ones(len(T), bool))
    for f in ("fu.basis_z", "fu.basis_d15", "fu.basis_d60", "fu.taker_ls_z", "tf.ntr_z_15", "tf.buy_share_15"):
        x = X[:, feats.index(f)].astype(float)
        q05, q20, q80, q95 = np.nanquantile(x, [0.05, 0.2, 0.8, 0.95])
        for tag, fn in (("top5", lambda x=x, q95=q95: x >= q95), ("top20", lambda x=x, q80=q80: x >= q80), ("bot20", lambda x=x, q20=q20: x <= q20), ("bot5", lambda x=x, q05=q05: x <= q05)):
            add("%s %s" % (f, tag), fn)
    env = _SimEnv(args)
    sim = S2.sim_many(env, {k: (v[0], v[1]) for k, v in sets.items()}, specs=spec_all)
    res = {"specs": [sp.name for sp in spec_all], "cost": COST_PCT, "rows": {}}
    for k, net in sim.items():
        name, b = k.rsplit("|", 1)
        idx = meta[k]
        row = []
        for q in range(len(spec_all)):
            v = net[:, q].astype(float)
            m = np.isfinite(v)
            row.append({"n": int(m.sum()), "mean": float(v[m].mean()) if m.any() else float("nan"), "se": float(XS.cluster_se(v[m], day[idx][m])) if m.sum() > 5 else float("nan"),
                        "win": float((v[m] > 0).mean()) if m.any() else float("nan")})
        res["rows"].setdefault(name, {})[int(b)] = row
    pickle.dump(res, open(Path(args.out_dir) / "leadsim.pkl", "wb"))
    print("[leadsim] bitti: %d küme" % len(sets), flush=True)


# ------------------------------------------------------------------------------------------------ rapor
def _f(x, nd=2, plus=False) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return (("%+." + str(nd) + "f") % x if plus else ("%." + str(nd) + "f") % x).replace(".", ",")


def _pc(x, nd=1) -> str:
    return "-" if x is None or (isinstance(x, float) and not np.isfinite(x)) else (("%." + str(nd) + "f%%") % (100 * x)).replace(".", ",")


def _md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def stage_report(args) -> None:
    out = Path(args.out_dir)
    L: list[str] = []
    rk = pickle.load(open(out / "rank.pkl", "rb"))
    mu = pickle.load(open(out / "multi.pkl", "rb"))
    ha = pickle.load(open(out / "ha.pkl", "rb"))
    ev = pickle.load(open(out / "eval.pkl", "rb"))
    ld = pickle.load(open(out / "lead.pkl", "rb"))
    ls = pickle.load(open(out / "leadsim.pkl", "rb"))
    tm = json.load(open(out / "timing.json"))
    lag1 = None
    if (out / "lag1" / "leadsim.pkl").exists():
        lag1 = pickle.load(open(out / "lag1" / "leadsim.pkl", "rb"))
        lag1_lead = pickle.load(open(out / "lag1" / "lead.pkl", "rb"))
    raw_cnt = json.load(open(out / "sweep_raw_counts.json"))
    names = rk["names"]
    nb = 3
    BL = ["B1", "B2", "B3"]
    # ----------------------------------------------------------------- özet sayılar
    ranks = {off: rk["rank"][off] for off in rk["rank"]}

    def top_resid(off, k=1):
        return sorted(ranks[off], key=lambda r: -abs(r["auc_resid"] - 0.5))[:k]
    m10 = rk["meta"][2]
    m0 = rk["meta"][0]
    mm10 = mu[2]["aynı alt küme (tf+fu var)"]
    mm0 = mu[0]["aynı alt küme (tf+fu var)"]

    def dd(m, v, sc="blok-dışı"):
        p = m["diffs"][v][sc]["pooled"]
        return "%s [%s; %s]" % (_f(p["diff"], 4, True), _f(p["lo"], 4, True), _f(p["hi"], 4, True))
    ha_rows = sorted(ha["rank"], key=lambda r: -abs(r["par_exn"]["t"]) if np.isfinite(r["par_exn"]["t"]) else 0)
    n_exn = sum(1 for r in ha["rank"] if np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05)
    all_nets = [b["net"] for rr in ha["rules"] for b in rr["blocks"] if b.get("n", 0) >= 30]
    n_rule_pos2 = 0
    for rr in ha["rules"]:
        oos = [b for i, b in enumerate(rr["blocks"]) if i != rr["sel_block"]]
        if all(b.get("n", 0) >= 30 and b["net"] > 0 for b in oos):
            n_rule_pos2 += 1
    n_cand_pos3 = 0
    for key, lst in ha["cands"].items():
        for c in lst:
            if all(x > 0 for x in c["net"]):
                n_cand_pos3 += 1
    sig_keys = [k for k in ev["periods"] if k.startswith("G:")]
    best_sig = None
    for k in sig_keys:
        nets = [ev["periods"][k][pn]["sim0"].get("mean") for pn in ("blk1", "blk2", "blk3")]
        if all(x is not None for x in nets):
            if best_sig is None or min(nets) > best_sig[1]:
                best_sig = (k[2:], min(nets), nets)
    pos_sig = [k[2:] for k in sig_keys if all((ev["periods"][k][pn]["sim0"].get("mean") or -9) > 0 for pn in ("blk1", "blk2", "blk3"))]
    base_net = [ev["base"][pn]["sim0"].get("mean") for pn in ("blk1", "blk2", "blk3")]
    bz5 = ls["rows"]["fu.basis_z top5"]
    rnd = ls["rows"]["rastgele"]
    # ----------------------------------------------------------------- 0. hüküm
    L.append("# İşlem akışı + vadeli (OI / L-S / fonlama / defter) verisi — LUNA tipi yükseliş ve Hız Avcısı için çevrimdışı ölçüm (2026-10-17)\n")
    L.append("**Hüküm: HAYIR — maliyet sonrası net-pozitif, kullanılabilir bir kenar YOK; ana tahmin motorunu besleyecek ölçüde bilgi de yok.** "
             "Veri gerçek ve kısmen anlamlı bilgi taşıyor (olay öncesi işlem sayısı/büyük işlem patlaması ve vadeli primi), ama (i) olay öngörüsünde mevcut 154 özelliğe eklenen bilgi gün-kümeli "
             "%%95 aralığın sıfırı içinde ya da en çok AUC +0,004 (t0'da +fu) mertebesinde, (ii) HA süzgeci olarak hiçbir kural örneklem dışı üç blokta birden net-pozitif olmadı, "
             "(iii) önceden belirlenmiş 13 sinyalin hiçbiri üç blokta net-pozitif olmadı. "
             "Tek tutarlı yapı **vadeli primi (perp − TRY spot/USDTTRY)**: bu, daha önce ölçülen USD→TRY lead-lag'in aynısı; brüt kenar 60 dakikada ≈ +%%0,2 (uç %%5 ≈ +%%0,3-0,4), maliyet duvarı ≈ %%0,525. "
             "Gerçekçi doluşla en iyi uç %%5 net %s…%s (rastgele giriş %s…%s): rastgeleden her blokta ≈ +0,2 puan iyi ama hâlâ NEGATİF. Vadeli veri 5 dk geç bilinirse brüt avantaj `basis_z`'de yaklaşık yarıya, `basis_d15`'te dörtte bire iner; ts_ms yanlış (bar kapanışı) okunursa yapay şişer (bölüm 5).\n" %
             (_f(max(bz5[b][0]["mean"] for b in range(3)), 2), _f(min(bz5[b][0]["mean"] for b in range(3)), 2), _f(max(rnd[b][0]["mean"] for b in range(3)), 2), _f(min(rnd[b][0]["mean"] for b in range(3)), 2)))
    L.append(_md(["soru", "sonuç (örneklem dışı: B1, B2, B3; seçim hiçbir zaman değerlendirilen blokta yapılmadı)"], [
        ["(a) Olay öngörüsü, tek tek özellik (t0−10)",
         "94 özellikten BH q<0,05: ham %d, dip+oynaklık kontrollü artık %d (tf %d / fu %d FWER-artık); en güçlü artık AUC %s (`%s`), 3 blokta aynı işaret. En güçlüler **etkinlik/işlem-sayısı patlaması** (z-skorlu işlem sayısı, büyük işlem sayısı: 0,55-0,56); ardından OI z/büyüklüğü, top-trader L/S düzeyi, fonlama (0,52-0,54). Yönlü bir alım-akışı öncüsü yok: 15 dk alıcı payı artığı 0,465 (olay öncesi alıcı payı DAHA DÜŞÜK = satış baskısı/dip)." %
         (m10["n_sig_q05"], m10["n_sig_q05_resid"], m10["fam"]["tf."]["n_sig_fwer_resid"], m10["fam"]["fu."]["n_sig_fwer_resid"], _f(top_resid(2)[0]["auc_resid"], 3), top_resid(2)[0]["feature"])],
        ["(a) Blok-dışı seçilmiş en iyi 10 özelliğin ortalama AUC'si (t0−10)",
         "tf %s / %s / %s, fu %s / %s / %s (B1/B2/B3; ½ = bilgi yok)" % tuple(
             [_f(rk["wf"][2]["tf."][b]["auc_mean"], 3) for b in range(3)] + [_f(rk["wf"][2]["fu."][b]["auc_mean"], 3) for b in range(3)])],
        ["(a) Çok değişkenli HGB (t0−10, aynı alt küme), grup-içi AUC farkı vs mevcut 154",
         "+tf %s · +fu %s · +ikisi %s (blok-dışı, havuz, gün-kümeli %%95 aralık). t0'da: +tf %s · +fu %s · +ikisi %s. Mevcut 154: t0−10 %s, t0 %s." %
         (dd(mm10, "+ tf"), dd(mm10, "+ fu"), dd(mm10, "+ tf + fu"), dd(mm0, "+ tf"), dd(mm0, "+ fu"), dd(mm0, "+ tf + fu"),
          "/".join(_f(x["auc_group"], 3) for x in mm10["variants"]["mevcut 154"]["blok-dışı"]), "/".join(_f(x["auc_group"], 3) for x in mm0["variants"]["mevcut 154"]["blok-dışı"]))],
        ["(b) HA süzgeci", "ATR-kontrollü kısmi Spearman (net−taban): %d/94 özellik BH q<0,05; en güçlü `%s` r=%s (t=%s), 3/3 blok aynı işaret. Blok-dışı seçilen en iyi 10 özelliğin favori tersilinde HA neti her blokta NEGATİF (en iyi tek blok-hücre %s); "
                           "kural rotasyonunda iki OOS blokta birden net>0 olan kural: %d / %d; 548 aday içinde 3 blokta net>0: %d." % (
                               n_exn, ha_rows[0]["name"], _f(ha_rows[0]["par_exn"]["r"], 3), _f(ha_rows[0]["par_exn"]["t"], 1),
                               _f(max(max(b["fav"].get("net", -9) for b in v["blocks"] if b) for v in ha["tercile"].values() if v["ok"]), 2), n_rule_pos2, len(ha["rules"]), n_cand_pos3)],
        ["(c) 13 önceden belirlenmiş sinyal", "Günde 48-1800 tetik (çoğu doygun); 3 blokta da net>0 olan: **%s**. En az negatif (en kötü blok): `%s` (%s). Koşulsuz rastgele giriş %s. 'Kanıtlı erken uyarı' ölçütünü geçen tek sinyal `big_oi` (günde 400-625 tetik, kesinlik %%1,6-2,1, net -0,52…-0,48 / rastgele -0,56…-0,53): zayıf istatistiksel eğilim, kullanılamaz (bölüm 4)." % (
            ", ".join(pos_sig) if pos_sig else "yok", best_sig[0], " / ".join(_f(x, 2) for x in best_sig[2]), " / ".join(_f(x, 2) for x in base_net))],
        ["(d) Karar", "Ana tahmin motoruna ve canlı günlüğe EKLEMEYİN (kenar yok). Vadeli primi (basis) zaten canlıdaki GLOBAL_LEAD_LAG ile aynı mekanizma; yeni bilgi sayılmaz. Detay bölüm 6."],
    ]))
    L.append("")
    # ----------------------------------------------------------------- 1. nedensellik
    L.append("## 1. Nedensellik (ileriye bakış denetimi) ve veri\n")
    rows = []
    for k, v in sorted(tm.items()):
        rows.append([k.replace("|", " / "), v["best_lag_min"], _f(v["corr_best"], 3), _f(v["corr_0"], 3), _f(v["corr_5"], 3)])
    L.append("Vadeli satırlarından türetilen fiyat (OI notional/OI; defter notional/derinlik) ile TRY spot/USDTTRY getirilerinin korelasyonu, satırın `ts_ms` değerine göre dakika gecikmesinde (`stage_timing`, ham tablo `timing.json`):\n")
    L.append(_md(["sembol / tablo", "en iyi gecikme (dk)", "r (en iyi)", "r (gecikme 0)", "r (gecikme +5)"], rows))
    L.append("\n- **`hist_futures_metrics.ts_ms` dilimin BAŞLANGICIDIR; değer dilim SONUNDA (ts+5 dk) ölçülür** (4/4 sembolde en iyi gecikme +5 dk, r≈0,87-0,94; gecikme 0'da r≈0). "
             "Yani ts=T satırı T+5 dk'dan önce bilinmez: karar anı t_dec = mum kapanışı olduğundan mum i'ye T = açılış zamanı olan satır bağlandı (t_dec'te bilinen en yeni satır), "
             "`--extra-lag` ile 1 bar daha gecikmeli sürüm ayrıca ölçüldü (bölüm 6). Naif bağlama (ts'yi bar kapanışı sanmak) 5 dk ileriye bakış olurdu ve bazis/OI özelliklerini yapay güçlendirirdi.\n"
             "- `hist_futures_bookdepth.ts_ms` anlık görüntünün GERÇEK zamanıdır (en iyi gecikme 0 dk) -> ts ∈ [ot, ot+5dk) satırı mum i'ye bağlandı.\n"
             "- Fonlama: yalnız `funding_time_ms <= t_dec` olan son yerleşmiş oran; z-skoru önceki 21 yerleşimden.\n"
             "- İşlem akışı: dakika açılışı ot[i] ≤ dakika < ot[i]+5dk, t_dec'te tamam. `sum_open_interest>0` süzgeci uygulandı (15 Eki ~13:40 UTC toplu sıfırlar); en çok 3 bar ileri taşıma, taze olmayan satırda baz (basis) hesaplanmaz.\n"
             "- Kesme testi: `tests/test_flow_futures.py` her özellik için girdileri t anında kesip yeniden hesaplar, satır aynıdır; hizalama fonksiyonları gelecekteki satırlar değiştirilince geçmiş barları etkilemez.\n"
             "- Perp = Binance USDⓈ-M küresel kontrat; Binance TR TRY defteri DEĞİL (defter özellikleri küresel derinliktir). Baz = (OI notional/OI / çarpan) / (TRY spot/USDTTRY).\n")
    nf = len([n for n in names if n.startswith("tf.")])
    nu = len([n for n in names if n.startswith("fu.")])
    cv = m10["fam"]
    L.append("**Özellikler:** %d işlem akışı (`tf.`: alıcı payı, büyük/balina net akış ve sayı, z-skorlu işlem sayısı/ortalama/azami büyüklük, vwap uzaklığı, ivme, emilim, CVD eğimi; pencere 5/15/60 dk) + %d vadeli (`fu.`: OI değişim 5/15/60, OI z, dört kadran, "
             "top-trader ve hesap L/S, taker L/S, fonlama düzey/z/değişim, baz bps/z/değişim, defter dengesizliği ±1/2/5 %%, derinlik z). Kapsam: olayların %s'sinde işlem akışı, %s'sinde vadeli (perp'i olmayan 16 taban + eksik satırlar); "
             "eşleşmiş taban olayla AYNI sembolden olduğundan kapsam grup içinde aynıdır. Her karşılaştırma kapsamı olan alt kümede yapıldı (olay sayısı: %d/%d).\n" % (
                 nf, nu, _pc(cv["tf."]["events_ok"] / m10["n_events"]), _pc(cv["fu."]["events_ok"] / m10["n_events"]), mm10["n_events"], m10["n_events"]))
    # ----------------------------------------------------------------- 2. (a)
    L.append("## 2. (a) Olay öngörüsü — LUNA tipi 90 günlük yükseliş olayları (n=%d), eşleşmiş taban (olay başına ≤20)\n" % m10["n_events"])
    for off in (2, 0):
        lab = OFF_LABEL[off]
        rows = []
        for r in sorted(ranks[off], key=lambda r: -abs(r["auc_resid"] - 0.5))[:14]:
            rows.append(["`%s`" % r["feature"], r["family"], _f(r["auc"], 3), _f(r["auc_resid"], 3), _f(r["q_resid"], 3), " / ".join(_f(x, 3) for x in r["blk_resid"]), r["consist_resid"]])
        L.append("### %s: en güçlü 14 özellik (|artık AUC−½|)\n" % lab)
        L.append(_md(["özellik", "aile", "ham AUC", "artık AUC", "q (artık)", "B1/B2/B3 artık AUC", "işaret tutarlılığı"], rows))
        L.append("")
        fam = {}
        for r in ranks[off]:
            d = fam.setdefault(r["family"], [0, 0, 0.0])
            d[0] += 1
            d[1] += int(r["q_resid"] < 0.05)
            d[2] = max(d[2], abs(r["auc_resid"] - 0.5))
        L.append(_md(["aile", "özellik", "q<0,05 (artık)", "en büyük |AUC−½|"], [[k, v[0], v[1], _f(v[2], 3)] for k, v in sorted(fam.items())]))
        L.append("")
        if off == 0:
            L.append("Not: `fu.quad_*` bayrakları fiyat hareketinin işaretinden türetilir; dip kontrolü yalnız doğrusal olduğundan t0'daki yüksek artık AUC'ler (0,58 / 0,44) büyük ölçüde dipin kendisinin doğrusal olmayan kalıntısıdır; öncü bilgi sayılmamalı.\n")
        L.append("Blok-dışı seçim (her blokta, diğer iki bloktaki artık-AUC sapması en büyük 10 özellik; işaret oradan; değerlendirme kalan blokta):\n")
        rows = []
        for fm in ("tf.", "fu."):
            for e in rk["wf"][off][fm]:
                rows.append([fm, BL[e["block"]], e["n_groups"], "%s [%s; %s]" % (_f(e["auc_mean"], 3), _f(e["lo"], 3), _f(e["hi"], 3)), "%d/10" % e["n_pos"], _f(e["best1"], 3), ", ".join("`%s`" % x for x in e["top"][:3])])
        L.append(_md(["aile", "blok", "olay", "ort. AUC [gün-kümeli %95]", ">½", "en iyi tek", "seçilen (ilk 3)"], rows))
        L.append("")
    L.append("### Çok değişkenli (HistGradientBoosting, olay başına 12 taban; grup-içi AUC, her olay aynı olay grubunun tabanlarına karşı)\n")
    for off in (2, 0):
        for sn in ("aynı alt küme (tf+fu var)", "tüm (tf var)"):
            m = mu[off][sn]
            L.append("**%s — %s** (olay %d, satır %d)\n" % (OFF_LABEL[off], sn, m["n_events"], m["n_rows"]))
            rows = []
            for vn, folds in m["variants"].items():
                row = [vn]
                for sc in ("blok-dışı", "ileri"):
                    row.append(" / ".join(_f(x["auc_group"], 3) for x in folds[sc]))
                if vn != "mevcut 154":
                    row.append(dd(m, vn, "blok-dışı"))
                    row.append(dd(m, vn, "ileri") if "ileri" in m["diffs"][vn] else "-")
                else:
                    row += ["-", "-"]
                rows.append(row)
            L.append(_md(["değişken", "blok-dışı B1/B2/B3", "ileri-yürüyen B2/B3", "Δ vs 154 (blok-dışı) [%95]", "Δ vs 154 (ileri) [%95]"], rows))
            L.append("")
    # ----------------------------------------------------------------- 3. (b)
    L.append("## 3. (b) Hız Avcısı (HA) süzgeci — %d olay (geçerli %d), 3 blok\n" % (ha["n_events"], ha["n_valid"]))
    L.append("HA nüfusu (TP = HA'nın kendi hedefi, SL %3, T60, exit_sim gerçekçi doluş): " + "; ".join(
        "%s n=%d net %s±%s, net−taban %s" % (BL[b], ha["pop"][b]["n"], _f(ha["pop"][b]["net"]), _f(ha["pop"][b]["se"]), _f(ha["pop"][b]["ex"], 2, True)) for b in range(nb)) +
        ". Özellik kapsamı: tf %s, fu %s, defter %s.\n" % (_pc(ha["cover"]["tf"]), _pc(ha["cover"]["fu"]), _pc(ha["cover"]["bd"])))
    rows = []
    for r in ha_rows[:16]:
        rows.append(["`%s`" % r["name"], r["family"], _f(r["par_exn"]["r"], 3, True), _f(r["par_exn"]["t"], 1), _f(r["q_par_exn"], 3), " / ".join(_f(x, 3, True) for x in r["blk_r"]), r["agree"], _pc(r["cover"], 0)])
    L.append("### Kısmi Spearman (ATR + hedef/ATR kontrollü) — net−taban ile, |t| sırasıyla ilk 16\n")
    L.append(_md(["özellik", "aile", "r", "t (gün-kümeli)", "q", "B1/B2/B3 r", "uyum", "kapsam"], rows))
    fam = {}
    for r in ha["rank"]:
        d = fam.setdefault(r["family"], [0, 0, 0.0])
        d[0] += 1
        d[1] += int(np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05)
        d[2] = max(d[2], abs(r["par_exn"]["r"]) if np.isfinite(r["par_exn"]["r"]) else 0.0)
    L.append("")
    L.append(_md(["aile", "özellik", "q<0,05 (net−taban)", "en büyük |r|"], [[k, v[0], v[1], _f(v[2], 3)] for k, v in sorted(fam.items())]))
    L.append("\n### HA neti, blok-dışı seçilmiş en iyi 10 özelliğin favori tersilinde (yön ve tersil kenarları YALNIZ diğer iki bloktan)\n")
    for b in range(nb):
        rows = []
        for nm in ha["top10"][b]:
            e = ha["tercile"][nm]["blocks"][b]
            rows.append(["`%s`" % nm, _f(e["sel_r"], 3, True), e["fav"].get("n", 0), _f(e["fav"].get("net")), _f(e["fav"].get("ex"), 2, True), _f(e["unf"].get("net")), _f(e["all"]["net"])])
        L.append("**Değerlendirme bloğu %s**\n" % BL[b])
        L.append(_md(["özellik (seçim)", "seçim r", "n (favori)", "net favori", "net−taban favori", "net sakıncalı tersil", "net tüm HA"], rows))
        L.append("")
    nok = [nm for nm, v in ha["tercile"].items() if v["ok"] and all(bb["fav"].get("net", -9) > 0 for bb in v["blocks"])]
    best = sorted(((min(bb["fav"].get("net", -9) for bb in v["blocks"]), nm) for nm, v in ha["tercile"].items() if v["ok"]), reverse=True)[:6]
    L.append("Tüm özellikler için (blok-dışı yön/kenar): favori tersilde HA neti **3 blokta birden pozitif olan özellik sayısı: %d**. En az kötü 6 (en kötü blok neti): %s.\n" % (
        len(nok), "; ".join("`%s` %s" % (nm, _f(v)) for v, nm in best)))
    L.append("### Kural arama rotasyonu (seçim bloğunda seç, diğer iki blokta dokunmadan değerlendir; her seçim bloğu için net ve net−taban hedefli 6'şar kural)\n")
    rows = []
    for rr in sorted(ha["rules"], key=lambda r: -min([b.get("net", -9) for i, b in enumerate(r["blocks"]) if i != r["sel_block"]]))[:14]:
        oos = [(i, b) for i, b in enumerate(rr["blocks"]) if i != rr["sel_block"]]
        rows.append(["%s" % BL[rr["sel_block"]], rr["target"], "`%s`" % rr["text"], " / ".join("%s: n%d net %s (%s)" % (BL[i], b.get("n", 0), _f(b.get("net")), _f(b.get("ex"), 2, True)) for i, b in oos)])
    L.append(_md(["seçim", "hedef", "kural", "OOS blokları"], rows))
    L.append("\n(36 kuralın OOS'ta en iyi 14'ü; iki OOS blokta birden net>0: **%d**. 548 aday kuralın seçim-sonrası ilk 300'ünde 3 blokta net>0: **%d**.)\n" % (n_rule_pos2, n_cand_pos3))
    # ----------------------------------------------------------------- 4. (c)
    L.append("## 4. (c) Önceden belirlenmiş sinyaller (5 dk süpürme, 60 dk cooldown, TP1,5/SL3/T60 ve iz 1,0/0,8; gerçekçi doluş)\n")
    L.append("Eşikler SABİT (veriden ayarlanmadı); NaN = tetiklemez. Tanımlar:\n")
    for k, v in SIGNALS.items():
        L.append("- `%s`: %s (cooldown öncesi ham tetik %s)" % (k, v, "{:,}".format(raw_cnt[k]).replace(",", ".")))
    L.append("")
    L.append("Sütunlar: tetik/gün (60 dk cooldown sonrası); kesinlik60 = tetikten sonraki 60 dk içinde olay (t0) başlama oranı (rastgele giriş / koşulsuz); hit60@1,5 şans farkı (pp, oynaklık-eşleşmiş null); "
             "net = exit_sim ortalaması (sinyal / sayı-eşleşmiş rastgele giriş); izleyen = trailing 1,0/0,8. t0'dan ÖNCE yakalama = olayların t0−60..t0 arasında sinyal alan payı (sayı-eşleşmiş sıfır); HA'dan önce = ortak yakalanan olaylarda sinyalin HA'dan önce gelme payı.\n")
    keys = sig_keys + ["HA"]
    rows = []
    for k in keys:
        nm = k[2:] if k.startswith("G:") else "HA (canlı-benzeri)"
        for pn, bl in (("blk1", "B1"), ("blk2", "B2"), ("blk3", "B3")):
            r = ev["periods"][k][pn]
            if not r.get("n"):
                continue
            rows.append(["`%s`" % nm if bl == "B1" else "", bl, _f(r["per_day"], 0), "%s (%s / %s)" % (_pc(r["prec_ahead60"]), _pc(r.get("prec_ahead60_rnd")), _pc(ev["base"][pn]["prec_ahead60"])),
                         _f(100 * r["lift15"], 1, True) if r.get("lift15") is not None else "-",
                         "%s / %s" % (_f(r["sim0"].get("mean")), _f(r["simr0"].get("mean"))), "%s / %s" % (_f(r["sim2"].get("mean")), _f(r["simr2"].get("mean"))),
                         "%s (%s)" % (_pc(r.get("rec_early")), _pc(r.get("rec_early_rnd"))), _pc(r.get("earlier_than_ha"), 0) if k != "HA" else "-",
                         _f(r.get("lead_med_min"), 0)])
    L.append(_md(["sinyal", "blok", "tetik/gün", "kesinlik60 (rastg. / koşulsuz)", "hit şans farkı pp", "net TP1,5 (sinyal / rastgele)", "net izleyen (sinyal / rastgele)", "t0 öncesi yakalama (sıfır)", "HA'dan önce", "medyan öncelik dk"], rows))
    L.append("\nKoşulsuz rastgele giriş (TP1,5): %s (B1/B2/B3). Net-pozitif sinyal sayısı (3 blokta): **%d**.\n" % (" / ".join(_f(x) for x in base_net), len(pos_sig)))
    ew_pass, hi_prec = [], []
    for k in sig_keys:
        rs_ = [ev["periods"][k][pn] for pn in ("blk1", "blk2", "blk3")]
        if all(r.get("n") for r in rs_):
            cap_ok = all((r.get("rec_early") or 0) > 1.5 * (r.get("rec_early_rnd") or 1e-9) for r in rs_)
            ha_ok = all((r.get("earlier_than_ha") or 0) > 0.5 for r in rs_)
            if cap_ok and ha_ok:
                ew_pass.append(k[2:])
            pr_ = [(r["prec_ahead60"] / max(r.get("prec_ahead60_rnd") or 1e-9, 1e-9)) for r in rs_]
            if all(x >= 2.0 for x in pr_):
                hi_prec.append("`%s` (x%s)" % (k[2:], "/".join(_f(x, 1) for x in pr_)))
    L.append("Okuma: 60 dk önden kesinliği 3 blokta da rastgele girişin >= 2 katı olanlar: %s. HA ise kesinlik %s. "
             "'Kanıtlı erken uyarı' ölçütü (t0 öncesi yakalama > sayı-eşleşmiş sıfır x1,5 VE ortak olayların >%%50'sinde HA'dan önce, her blokta): **%s**. "
             "Doygun sinyallerde (`bigbuy_dom`, `absorb_buy`, `taker_surge`) 'HA'dan önce' %%67-77 görünür ama t0 öncesi yakalama sıfırla aynı: sinyal her yerde tetiklendiği için bilgi taşımaz.\n" % (
                 ", ".join(hi_prec) if hi_prec else "yok", "/".join(_pc(ev["periods"]["HA"][pn]["prec_ahead60"]) for pn in ("blk1", "blk2", "blk3")), ", ".join(ew_pass) if ew_pass else "hiçbiri"))
    # ----------------------------------------------------------------- 5. koşulsuz zamanlama
    L.append("## 5. Koşulsuz zamanlama — özellik uçları ve sonraki 60 dk (tüm geçerli anlar, 15 dk'da bir örnek, n=%s)\n" % "{:,}".format(ld["n"]).replace(",", "."))
    L.append("Brüt kapanıştan-kapanışa 60 dk getiri (%%) — uç beşte-birlik (üst/alt %%20 ve %%5) eksi blok ortalaması; blok ortalaması %s (B1/B2/B3). Maliyet duvarı ≈ %%%s (2×ücret %%0,1125 + 2×kayma %%0,15). "
             "Yön önceden seçilmedi: iki uç da gösterilir (yalnız long yapılabilir).\n" % (" / ".join(_f(b["mean"], 3, True) for b in ld["base"]), _f(ld["cost"], 3)))
    rows = []
    for f, v in ld["feats"].items():
        row = ["`%s`" % f]
        for tag in ("top5", "top20", "bot20", "bot5"):
            row.append(" / ".join(_f(v["blocks"][b][tag]["mean"] - ld["base"][b]["mean"], 2, True) if tag in v["blocks"][b] else "-" for b in range(3)))
        rows.append(row)
    L.append(_md(["özellik", "üst %5", "üst %20", "alt %20", "alt %5"], rows))
    L.append("\n**Baz (perp primi) uçlarında gerçekçi doluşlu net** (60 sn gecikme, %0,15 kayma, ücret; her hücre B1 / B2 / B3):\n")
    rows = []
    for nm in ("rastgele", "fu.basis_z top5", "fu.basis_z top20", "fu.basis_z bot20", "fu.basis_d15 top5", "fu.basis_d60 top5", "fu.taker_ls_z top5", "tf.ntr_z_15 top5", "tf.buy_share_15 top5", "tf.buy_share_15 bot5"):
        rows.append(["`%s`" % nm] + [" / ".join(_f(ls["rows"][nm][b][q]["mean"], 2, True) for b in range(3)) for q in range(len(ls["specs"]))])
    L.append(_md(["küme"] + ls["specs"], rows))
    L.append("\nGün-kümeli SE (TP1,5, `fu.basis_z top5`): " + ", ".join("%s ±%s (n=%d, kazanç %s)" % (BL[b], _f(bz5[b][0]["se"], 3), bz5[b][0]["n"], _pc(bz5[b][0]["win"])) for b in range(3)) + ".\n")
    if lag1 is not None:
        L.append("**Yayın gecikmesi duyarlılığı** (tüm vadeli özellikler +1 bar = 5 dk geç bilinirse), baz uçları, TP1,5 neti B1 / B2 / B3: " + "; ".join(
            "`%s`: %s → gecikmeli %s" % (nm, " / ".join(_f(ls["rows"][nm][b][0]["mean"], 2, True) for b in range(3)), " / ".join(_f(lag1["rows"][nm][b][0]["mean"], 2, True) for b in range(3)))
            for nm in ("fu.basis_z top5", "fu.basis_d15 top5")) + ". Brüt üst-%5 farkı (lead): " + "; ".join(
            "`%s` %s" % (f, " / ".join(_f(lag1_lead["feats"][f]["blocks"][b]["top5"]["mean"] - lag1_lead["base"][b]["mean"], 2, True) for b in range(3))) for f in ("fu.basis_z", "fu.basis_d15")) + ".\n")
    if (out / "lagm1" / "lead.pkl").exists():
        lm = pickle.load(open(out / "lagm1" / "lead.pkl", "rb"))
        L.append("**Yanlış hizalama kontrolü** (ts_ms'i bar KAPANIŞI sanıp satırı 1 bar erken bağlamak = 5 dk ileriye bakış): brüt uç-%5 farkı " + "; ".join(
            "`%s` doğru %s → yanlış %s" % (f, " / ".join(_f(ld["feats"][f]["blocks"][b]["top5"]["mean"] - ld["base"][b]["mean"], 2, True) for b in range(3)),
                                        " / ".join(_f(lm["feats"][f]["blocks"][b]["top5"]["mean"] - lm["base"][b]["mean"], 2, True) for b in range(3))) for f in ("fu.basis_z", "fu.basis_d15", "fu.oi_chg_15", "fu.taker_ls_z")) +
            ". Yani doğru hizalama zorunlu; naif bağlama baz/OI/taker özelliklerini yapay biçimde şişirirdi.\n")
    # ----------------------------------------------------------------- 6/7 karar
    L.append("## 6. Karar, anlam ve öneri\n")
    L.append("1. **Net-pozitif kenar yok.** Brüt kenarın en iyisi (vadeli primi, uç %%5) 60 dakikada ≈ +%%0,2…0,4; maliyet ≈ %%0,525. En iyi uçta bile TP1,5 neti %s…%s; rastgele %s…%s. Bu, `USD_LEADLAG_ARASTIRMASI` ve `GENIS_PENCERE` bulgularıyla aynı: gerçek mekanizma, maliyete mahkûm.\n" % (
        _f(min(bz5[b][0]["mean"] for b in range(3)), 2, True), _f(max(bz5[b][0]["mean"] for b in range(3)), 2, True), _f(min(rnd[b][0]["mean"] for b in range(3)), 2, True), _f(max(rnd[b][0]["mean"] for b in range(3)), 2, True)))
    L.append("2. **Ana tahmin motoruna beslemeye değer mi?** Hayır. Olay öngörüsünde mevcut 154 özelliğe eklenen bilgi t0−10'da +tf %s, +fu %s (aynı alt küme, havuz, %%95 aralık sıfırı içerir ya da ihmal edilebilir); t0'da yalnız +fu küçük pozitif (%s). "
             "Tek başına tf+fu özellikleri 154'ten ≈0,05 AUC düşük. Tek tek özelliklerde görünen en güçlü yapı (işlem-sayısı z-skoru) zaten mevcut oynaklık/hacim özelliklerinin başka bir ölçüsü.\n" % (dd(mm10, "+ tf"), dd(mm10, "+ fu"), dd(mm0, "+ fu")))
    L.append("3. **HA'yı güçlendirir mi?** Kısmen *sıralar* (baz/perp primi yüksekse HA'nın taban üstü kazancı büyük: kısmi r≈+0,05, 3/3 blok), ama mutlak net değişmez (en iyi favori tersil bile her blokta negatif). Aşırı-uyum tanısı için: 548 aday kuralda 3 blokta net>0 sayısı %d.\n" % n_cand_pos3)
    L.append("4. **Canlı günlüğe (journal) yazmak** ancak gelecekteki bir doğrulama için bilgi birikimi amacıyla anlamlı olur ve yalnız ucuz/hazır alanlar için: `fu.basis_*` (tek özellik, GLOBAL_LEAD_LAG zaten aynı bilgiyi taşır), `fonlama` ve `OI` (tek satır sorgusu, 5 dk) — ölçülen etkileri ihmal edilebilir olduğundan öncelik düşük. "
             "Defter/işlem-akışı özellikleri için canlı toplama maliyeti (REST ağırlığı, depolama) kazanımla orantısız. Önerilmez.\n")
    L.append("### Kısıtlar ve uyarılar\n")
    L.append("- Perp küresel USDⓈ-M; TRY defteri/gerçek TRY derinliği değil. Gerçek TRY defter geçmişi yalnız ücretli sağlayıcılardan (bkz. VADELI_GECMIS_VERI).")
    L.append("- 90 gün, 3 blok; olay sayısı 4552 (taban ≤20/olay). Blok-dışı HGB gelecekten de eğitim görür (ileri-yürüyen sürüm ayrıca verildi; sonuç aynı yönde).")
    L.append("- 'Aynı alt küme' = işlem akışı ve vadeli verisi olan olaylar (%s); perp'i olmayan tabanlar ayrı raporlandı (tam küme)." % _pc(mm10["n_events"] / m10["n_events"]))
    L.append("- Sinyal eşikleri bilinçli SABİT ve gevşek tutuldu; bu yüzden günde yüzlerce tetik (306 sembol × 60 dk cooldown) üretiyor. Daha sıkı eşikler tetik sayısını düşürür ama 3 blokta net-pozitif sinyal çıkması için gerekli brüt kenar (≥ +%0,53) hiçbir ucun brüt farkına (≤ +%0,4) yaklaşmıyor.")
    L.append("- BH düzeltmesi tf+fu ortak (94 özellik) / HA için 94; permütasyon p tabanı 1/1001 olduğundan q=0,004 tabanı 'çok anlamlı' demektir, etki büyüklüğü AUC sapması ile okunmalıdır.")
    L.append("\nKaynaklar: `backend/app/rescan/flow_futures.py` (kurucular), `backend/tests/test_flow_futures.py`, `backend/scripts/flowfut_study.py`, ham çıktılar `backend/work/flowfut/*.pkl`.")
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("[report] yazıldı: %s (%d satır)" % (out / "report.md", len(L)), flush=True)


# ------------------------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="feat,snap,rank,multi,hafeat,ha,sweep,eval,report")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--old-fx-dir", required=True)
    ap.add_argument("--fx-dir", required=True)
    ap.add_argument("--out-dir", default="work/flowfut")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--extra-lag", type=int, default=0, help="vadeli veri yayın gecikmesi duyarlılığı (bar)")
    ap.add_argument("--refeat", action="store_true")
    ap.add_argument("--offsets", type=lambda s: [int(x) for x in s.split(",")], default=[2, 0])
    ap.add_argument("--offsets-multi", type=lambda s: [int(x) for x in s.split(",")], default=[0, 2])
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    args = ap.parse_args(argv)
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get("stage_" + st)
        if fn is None:
            sys.exit("bilinmeyen aşama: " + st)
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
