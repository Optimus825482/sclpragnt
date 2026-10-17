"""Erken uyarı çalışması v2 — rehberin YENİ (★) göstergeleri (app/rescan/indicators_ext2.py), 2026-10-17, çevrimdışı.

`indearly_study.py` / `indearly_signals.py` hatlarını YENİDEN KULLANIR (aynı olaylar, eşleşmiş taban, ızgara, exit_sim, null3); yalnız özellik kümesi değişir.
Canlı koda bağlanmaz, DB'ye yazmaz.

Aşamalar (`--stages`):
  feat   sembol başına yeni kütüphane özellikleri (5m tam; 1m ve 15m gün-aile hariç) -> olay/taban anlık görüntüleri + ÖNCEDEN BELİRLENMİŞ 20 sinyalin 5m süpürmesi
         (<fx-dir>/part/<sym>.npz). Tam ızgara DİSKE YAZILMAZ (bellek/disk).
  snap   parçaları birleştirir -> <fx-dir>/snap/{XE,XB}_<off>.npy, meta2.npz, sig/G_*.npz
  rank   olay <-> eşleşmiş taban: ham grup-içi AUC + "düşüş+oynaklık" doğrusal kontrolünden SONRA artık AUC (permütasyon p, BH q, blok işaret tutarlılığı) -> rank2.pkl
  multi  HistGradientBoosting blok-dışı bırakma: mevcut154 -> +eski kütüphane -> +yeni kütüphane (t0 ve t0-10) -> multi2.pkl
  eval   önceden belirlenmiş sinyallerin dönem ölçüleri (indearly_signals.stage_eval'ı yeniden kullanır) -> eval.pkl

Kullanım (backend/):
  python scripts/indearly2_study.py --cache-dir <p90cache> --old-fx-dir <scratch>/indearly --fx-dir <scratch>/indearly2 --out-dir work/indearly2 --workers 2
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import indicators_ext as I1  # noqa: E402
from app.rescan import indicators_ext2 as I2  # noqa: E402
from app.rescan import pattern_study as P  # noqa: E402
from scripts import indearly_signals as S2  # noqa: E402
from scripts import indearly_study as S1  # noqa: E402
from scripts.pattern90_analysis import cooldown_idx  # noqa: E402
from scripts.pattern90_study import list_syms, parse_day, fmt_t, MIN_QUOTE, WARM_BARS  # noqa: E402

OFFS = (3, 2, 1, 0)
DROP_LT = ("x2_day",)                      # 1m / 15m'de gün-aile atlanır (5m'de var)
BASE_PER_EVENT = 20
# Önceden belirlenmiş sinyaller (standart varsayılan eşikler; veri madenciliği YOK): ad -> (5m sütunu, açıklama)
SIGNALS = {
    "sqz_rel_up": ("5m.x2.sqzm_rel_up", "Squeeze Momentum (LazyBear) yukarı salım"),
    "wt_os53": ("5m.x2.wt_cross_up_os53", "WaveTrend WT1>WT2 kesişimi, WT2 <= -53"),
    "qqe_mod": ("5m.x2.qqe_blue_on", "QQE MOD mavi çubuk başlangıcı"),
    "wae_up": ("5m.x2.wae_expl_up_on", "Waddah Attar patlama yukarı başlangıcı"),
    "utbot_buy": ("5m.x2.utb_buy", "UT Bot AL (a=1, ATR10)"),
    "ssl_flip_up": ("5m.x2.ssl_flip_up", "SSL kanalı yukarı dönüş (SMA10)"),
    "rf_buy": ("5m.x2.rf_buy", "Range Filter AL (100, 3)"),
    "lrsi_up20": ("5m.x2.lrsi_cross_up20", "Laguerre RSI 0,2 yukarı kesişim"),
    "stc_up25": ("5m.x2.stc_cross_up25", "Schaff Trend Cycle 25 yukarı kesişim"),
    "ce_flip_up": ("5m.x2.ce_flip_up", "Chandelier Exit yön -> long"),
    "ts_long": ("5m.x2.ts20_long", "Turtle Soup long (20 bar alçak süpürme + geri kapanış)"),
    "spring": ("5m.x2.spring", "Wyckoff spring (dar aralık alçak süpürme + hacimli geri alma)"),
    "dbot_break": ("5m.x2.dbot_break", "Çift dip yaka çizgisi kırılımı"),
    "ifvg_bull": ("5m.x2.ifvg_bull_new", "Inversion FVG (yükseliş) oluştu"),
    "brk_bull": ("5m.x2.brk_bull_tap", "Yükseliş Breaker Block teması"),
    "ote_tap": ("5m.x2.ote_long_tap", "OTE bölgesine (62-79%) ilk giriş (yükseliş bacağı)"),
    "orb_utc": ("5m.x2.orb30_utc_up_first", "ORB 30 dk yukarı kırılım (UTC günü)"),
    "orb_tr": ("5m.x2.orb30_tr_up_first", "ORB 30 dk yukarı kırılım (TR günü)"),
    "rvol_green": ("5m.x2.rvol_tod_green3", "RVOL(günün saati) > 3 ve yeşil mum"),
    "vmc_green": ("5m.x2.vmc_green_mf", "Cipher B yeşil nokta (WT dip kesişimi + para akışı yukarı)"),
}


def sig_guide() -> list[str]:
    return ["%s (%s)" % (k, v[1]) for k, v in SIGNALS.items()]


def fx2_names() -> list[str]:
    return I2.feature_names("5m") + I2.feature_names("1m", DROP_LT) + I2.feature_names("15m", DROP_LT)


# ------------------------------------------------------------------------------------------------ feat
def _sym_job(job):
    sym, cache_dir, fx_dir, ev_g, ev_i0, b_g_rows, b_t = job
    cache = Path(cache_dir)
    fx = Path(fx_dir)
    f5 = np.load(cache / "grid" / f"F5_{sym}.npy")
    ot = np.load(cache / "grid" / f"OT_{sym}.npy")
    OS = np.load(cache / "grid" / f"OS_{sym}.npy")
    n5 = len(f5)
    t_dec = f5[:, P.COL_OT].astype(np.int64) + P.BAR_5M_MS
    _, X5 = I2.compute_all(f5, "5m")
    # satır dizinleri (5m ızgara)
    ib = (b_t - P.BAR_5M_MS - ot[0]) // P.BAR_5M_MS
    rows_e = {o: np.clip(ev_i0 - o, 0, n5 - 1) for o in OFFS}
    rows_b = {o: np.clip(ib - o, 0, n5 - 1) for o in OFFS}
    F5 = X5.shape[1]
    ne, nb = len(ev_i0), len(b_t)
    names_lt = [len(I2.feature_names(tf, DROP_LT)) for tf in ("1m", "15m")]
    Ftot = F5 + sum(names_lt)
    XE = np.full((len(OFFS), ne, Ftot), np.nan, dtype=np.float32)
    XB = np.full((len(OFFS), nb, Ftot), np.nan, dtype=np.float32)
    for q, o in enumerate(OFFS):
        XE[q, :, :F5] = X5[rows_e[o]]
        XB[q, :, :F5] = X5[rows_b[o]]
    # --- 15m ve 1m: karar anına göre son kapanmış bar
    for tf, off0, wid in (("15m", F5 + names_lt[0], names_lt[1]), ("1m", F5, names_lt[0])):
        if tf == "1m":
            p1 = cache / "d1" / f"{sym}.npy"
            arr = P.fill_gaps(np.load(p1), P.BAR_1M_MS) if p1.exists() else np.zeros((0, 9))
            bar = P.BAR_1M_MS
        else:
            arr = P.aggregate_bars(f5, 3, P.BAR_5M_MS)
            bar = 3 * P.BAR_5M_MS
        if len(arr) <= 400:
            continue
        _, X = I2.compute_all(arr, tf, DROP_LT)
        aot = arr[:, P.COL_OT].astype(np.int64)
        for q, o in enumerate(OFFS):
            for dst, rows in ((XE, rows_e[o]), (XB, rows_b[o])):
                idx = P.snapshot_index(aot, bar, t_dec[rows])
                dst[q, :, off0: off0 + wid] = np.where((idx >= 0)[:, None], X[np.clip(idx, 0, len(X) - 1)], np.float32(np.nan))
        del X, arr
    # --- önceden belirlenmiş sinyaller (5m, tüm ızgara; stage_sweep ile aynı geçerlilik/cooldown/OS süzgeci)
    names5 = I2.feature_names("5m")
    col5 = {nm: j for j, nm in enumerate(names5)}
    gn = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    Gm = np.load(cache / "grid" / f"G_{sym}.npy", mmap_mode="r")
    sub = np.asarray(Gm[:, [gn.index(x) for x in S2.NEED]])
    thr = np.log10(MIN_QUOTE)
    valid = (np.arange(n5) >= WARM_BARS) & (sub[:, 0] >= thr) & np.isfinite(sub[:, 1:]).all(axis=1)
    res = {"ev_g": ev_g, "b_rows": b_g_rows, "XE": XE, "XB": XB, "valid_t": t_dec[valid]}
    lw = (parse_day("2026-10-17"), parse_day("2026-10-17") + 4 * 3_600_000)
    for key, (cn, _d) in SIGNALS.items():
        m = valid & (X5[:, col5[cn]] == 1.0)
        idx = np.flatnonzero(m)
        if sym == "LUNATRY":
            res["lun_" + key] = np.array([fmt_t(int(t_dec[i]), "%H:%M") for i in idx if lw[0] <= t_dec[i] <= lw[1]])
        idx = cooldown_idx(idx, S2.SIG_COOLDOWN)
        if len(idx):
            idx = idx[OS[idx, 0] == 1]
        res["sig_" + key + "_row"] = idx.astype(np.int32)
        res["sig_" + key + "_out"] = OS[idx, 1:].astype(np.float32)
        res["sig_" + key + "_t"] = t_dec[idx]
    np.savez(fx / "part" / f"{sym}.npz", **res)
    return sym


def load_old_meta(old_fx: str) -> dict:
    z = np.load(Path(old_fx) / "snap" / "meta.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


def stage_feat(args) -> None:
    from multiprocessing import Pool
    fx = Path(args.fx_dir)
    (fx / "part").mkdir(parents=True, exist_ok=True)
    (fx / "snap").mkdir(exist_ok=True)
    names = fx2_names()
    (fx / "fx_names.json").write_text(json.dumps(names), encoding="utf-8")
    m = load_old_meta(args.old_fx_dir)
    G = len(m["ev_sid"])
    rng = np.random.default_rng(args.seed)
    # taban alt kümesi: olay başına <= BASE_PER_EVENT
    keep = np.zeros(len(m["b_g"]), bool)
    order = rng.permutation(len(m["b_g"]))
    cnt = np.zeros(G, int)
    for i in order:
        if cnt[m["b_g"][i]] < BASE_PER_EVENT:
            keep[i] = True
            cnt[m["b_g"][i]] += 1
    np.save(fx / "snap" / "b_keep.npy", keep)
    syms = list_syms(args.cache_dir, "d5")
    jobs = []
    for sid, s in enumerate(syms):
        eg = np.flatnonzero(m["ev_sid"] == sid)
        bg = np.flatnonzero((m["b_sid"] == sid) & keep)
        jobs.append((s, args.cache_dir, args.fx_dir, eg, m["ev_i0"][eg].astype(np.int64), bg, m["b_t"][bg].astype(np.int64)))
    done = {p.stem for p in (fx / "part").glob("*.npz")}
    jobs = [j for j in jobs if j[0] not in done]
    t0 = time.time()
    print(f"[feat] {len(names)} özellik; {len(jobs)} sembol işlenecek ({len(done)} hazır)", flush=True)
    with Pool(max(1, args.workers)) as pool:
        for k, _ in enumerate(pool.imap_unordered(_sym_job, jobs, chunksize=1)):
            if (k + 1) % 10 == 0:
                print(f"[feat] {k + 1}/{len(jobs)} ({time.time() - t0:.0f} sn)", flush=True)
    print(f"[feat] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ snap (birleştirme)
def stage_snap(args) -> None:
    fx = Path(args.fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    m = load_old_meta(args.old_fx_dir)
    keep = np.load(fx / "snap" / "b_keep.npy")
    bidx = np.flatnonzero(keep)                       # eski taban satırı indeksleri
    pos_in_new = np.full(len(keep), -1, np.int64)
    pos_in_new[bidx] = np.arange(len(bidx))
    G, nb, F = len(m["ev_sid"]), len(bidx), len(names)
    syms = list_syms(args.cache_dir, "d5")
    XE = {o: np.lib.format.open_memmap(fx / "snap" / f"XE_{o}.npy", mode="w+", dtype=np.float32, shape=(G, F)) for o in OFFS}
    XB = {o: np.lib.format.open_memmap(fx / "snap" / f"XB_{o}.npy", mode="w+", dtype=np.float32, shape=(nb, F)) for o in OFFS}
    sig_acc = {k: {"sid": [], "row": [], "t": [], "out": []} for k in SIGNALS}
    valid_t = {}
    lun = {k: [] for k in SIGNALS}
    for sid, s in enumerate(syms):
        z = np.load(fx / "part" / f"{s}.npz")
        eg, bg = z["ev_g"], z["b_rows"]
        for q, o in enumerate(OFFS):
            if len(eg):
                XE[o][eg] = z["XE"][q]
            if len(bg):
                XB[o][pos_in_new[bg]] = z["XB"][q]
        valid_t[sid] = z["valid_t"]
        for k in SIGNALS:
            r = z["sig_" + k + "_row"]
            if len(r):
                a = sig_acc[k]
                a["sid"].append(np.full(len(r), sid, np.int16)); a["row"].append(r); a["t"].append(z["sig_" + k + "_t"]); a["out"].append(z["sig_" + k + "_out"])
            if s == "LUNATRY":
                lun[k] = [str(x) for x in z["lun_" + k]]
    for o in OFFS:
        XE[o].flush(); XB[o].flush()
    (fx / "sig").mkdir(exist_ok=True)
    for k, a in sig_acc.items():
        if a["sid"]:
            sidv = np.concatenate(a["sid"]); tv = np.concatenate(a["t"]); ov = np.concatenate(a["out"]); rv = np.concatenate(a["row"])
            od = np.argsort(tv, kind="stable")
            sidv, tv, ov, rv = sidv[od], tv[od], ov[od], rv[od]
        else:
            sidv = np.zeros(0, np.int16); tv = np.zeros(0, np.int64); ov = np.zeros((0, 9), np.float32); rv = np.zeros(0, np.int32)
        np.savez(fx / "sig" / f"G_{k}.npz", sid=sidv, t=tv, out=ov, row=rv)
    pickle.dump({"valid_t": valid_t, "lunatry": {"G:" + k: v for k, v in lun.items()}}, open(fx / "sweep_extra.pkl", "wb"))
    b_g_new = m["b_g"][bidx]
    np.savez(fx / "snap" / "meta2.npz", ev_t0=m["ev_t0"], ev_sid=m["ev_sid"], b_sid=m["b_sid"][bidx], b_t=m["b_t"][bidx], b_g=b_g_new, b_idx_old=bidx, names=np.array(names))
    print(f"[snap] olay {G}, taban {nb}, özellik {F}; sinyal sayıları: " + ", ".join(f"{k}={sum(len(x) for x in a['sid'])}" for k, a in sig_acc.items()), flush=True)


# ------------------------------------------------------------------------------------------------ rank
def _family(nm: str) -> str:
    base = nm.split(".", 1)[1] if "." in nm else nm
    return I2.FAMILY.get(base, "?")


def partial_r_stats(XE, XB, gid, Call, order, starts, counts, *, B: int, seed: int, blkmask_g, ch: int = 200, bb: int = 40):
    """Eşleşmiş grup-içi (sabit etkili) KISMİ korelasyon: r_j = corr(olay göstergesi, x_j | kontroller), tümü grup-içi ortalamadan arındırılmış.
    Yalnız sıralı AUC'nin tersine seyrek 0/1 bayraklarda da yanlı değildir (artık-AUC bağlarını kontrol terimiyle bozar). Permütasyon: her grupta rastgele bir üye 'olay' seçilir.
    Dönüş: r_obs (F), r_perm (B,F), blok r (3,F)."""
    G = XE.shape[0]
    F = XE.shape[1]
    n = G + len(XB)
    med = np.nanmedian(XB, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)

    def dm(Z):
        Zs = Z[order]
        mean = np.add.reduceat(Zs, starts, axis=0) / counts[:, None]
        res_ = np.empty_like(Zs)
        res_[order] = Zs - np.repeat(mean, counts, axis=0)
        return res_
    Cdm = dm(Call)
    CtC_inv = np.linalg.pinv(Cdm.T @ Cdm)
    ng = len(counts)
    rng = np.random.default_rng(seed)
    U = np.floor(rng.random((B, ng)) * counts[None, :]).astype(np.int64)
    chosen = order[starts[None, :] + U]                            # (B, ng) seçilen satır
    ydm2 = float((1.0 - 1.0 / counts).sum())                       # ||y_dm||^2 (her permütasyonda aynı)
    Cy_obs = Cdm[np.arange(G)].sum(axis=0)                         # olay satırları 0..G-1
    w_obs = CtC_inv @ Cy_obs
    v2_obs = ydm2 - Cy_obs @ w_obs
    r_obs = np.empty(F)
    r_perm = np.empty((B, F), np.float32)
    r_blk = np.full((len(blkmask_g), F), np.nan)
    Cy_p = np.stack([Cdm[chosen[b]].sum(axis=0) for b in range(B)])           # (B, K)
    W_p = Cy_p @ CtC_inv                                                     # (B, K)  (simetrik)
    v2_p = ydm2 - np.einsum("bk,bk->b", Cy_p, W_p)
    ev_rows = np.arange(G)
    for a in range(0, F, ch):
        sl = slice(a, min(a + ch, F))
        Yb = np.where(np.isfinite(XB[:, sl]), XB[:, sl], med[sl]).astype(np.float32)
        Ye = np.where(np.isfinite(XE[:, sl]), XE[:, sl], med[sl]).astype(np.float32)
        Xdm = dm(np.vstack([Ye, Yb]).astype(np.float64)).astype(np.float32)
        XtC = Xdm.T.astype(np.float64) @ Cdm                                   # (k, K)
        xx = (Xdm.astype(np.float64) ** 2).sum(axis=0)
        xt2 = xx - np.einsum("jk,kl,jl->j", XtC, CtC_inv, XtC)                  # ||x_tilde||^2
        den_x = np.sqrt(np.maximum(xt2, 1e-30))
        S_obs = Xdm[ev_rows].astype(np.float64).sum(axis=0) - XtC @ w_obs
        r_obs[sl] = S_obs / (np.sqrt(max(v2_obs, 1e-30)) * den_x)
        for b0 in range(0, B, bb):
            idx = chosen[b0: b0 + bb]                                           # (bb, ng)
            Sx = Xdm[idx.reshape(-1)].reshape(idx.shape[0], idx.shape[1], -1).sum(axis=1, dtype=np.float64)   # (bb, k)
            S = Sx - W_p[b0: b0 + bb] @ XtC.T
            r_perm[b0: b0 + bb, sl] = (S / (np.sqrt(np.maximum(v2_p[b0: b0 + bb], 1e-30))[:, None] * den_x[None, :])).astype(np.float32)
        # blok bazlı gözlenen r: yalnız o bloktaki gruplar
        for q, bm in enumerate(blkmask_g):
            if bm.sum() < 20:
                continue
            row_in = bm[gid]                                                     # tüm satırlar için grup blokta mı
            Xs, Cs = Xdm[row_in].astype(np.float64), Cdm[row_in]
            evs = np.flatnonzero(bm)                                             # olay satırları = grup indeksleri
            Cinv = np.linalg.pinv(Cs.T @ Cs)
            cy = Cdm[evs].sum(axis=0)
            w_ = Cinv @ cy
            gsel = bm
            y2 = float((1.0 - 1.0 / counts[gsel]).sum())
            v2_ = y2 - cy @ w_
            XtCs = Xs.T @ Cs
            xt2s = (Xs ** 2).sum(axis=0) - np.einsum("jk,kl,jl->j", XtCs, Cinv, XtCs)
            Sb = Xdm[evs].astype(np.float64).sum(axis=0) - XtCs @ w_
            r_blk[q, sl] = Sb / (np.sqrt(max(v2_, 1e-30)) * np.sqrt(np.maximum(xt2s, 1e-30)))
        del Xdm
    return r_obs, r_perm, r_blk


def stage_rank(args) -> None:
    fx = Path(args.fx_dir)
    old = Path(args.old_fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    I2.feature_names("5m")
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx = mt["b_idx_old"]
    per = S1.periods()
    G = len(mt["ev_t0"])
    gidx, nv = S1.build_groups(mt["b_g"], G)
    res = {"names": names, "family": {nm: _family(nm) for nm in names}, "rank": {}, "meta": {}}
    t0 = time.time()
    for off in args.offsets:
        XE = np.load(fx / "snap" / f"XE_{off}.npy")
        XB = np.load(fx / "snap" / f"XB_{off}.npy")
        CE = np.load(old / "snap" / f"CE_{off}.npy")
        CB = np.load(old / "snap" / f"CB_{off}.npy", mmap_mode="r")[keep_idx]
        cols = np.arange(len(names))
        obs, perm, pg, gi = S1.matched_stats(XE, XB, gidx, nv, cols, B=args.n_perm, seed=args.seed + off)
        p, pf = S1.pvals_from_perm(obs, perm)
        q = S1.bh_q(p)
        t0g = mt["ev_t0"][gi]
        blkm = {bk: S1.in_iv(t0g, per[bk]) for bk in ("blk1", "blk2", "blk3")}
        blk = {bk: (pg[mk].mean(axis=0) if mk.sum() >= 20 else np.full(len(cols), np.nan)) for bk, mk in blkm.items()}
        print(f"[rank] {S1.OFF_LABEL[off]} ham: FWER<0,05 {(pf < 0.05).sum()}, q<0,10 {(q < 0.10).sum()} ({time.time() - t0:.0f} sn)", flush=True)
        # --- "düşüş + oynaklık" doğrusal kontrolünden sonra artık AUC. Kontrol katsayıları GRUP-İÇİ (eşleşmiş küme sabit etkili) regresyondan,
        #     olay göstergesi de modelde: x_dm = C_dm b + g*y_dm. Artık = x - C b (olay kayması KORUNUR; seyrek bayraklarda b≈0 -> artık≈x).
        Cb = np.nan_to_num(np.asarray(CB, dtype=np.float32), nan=0.0)
        mu, sd = Cb.mean(axis=0), Cb.std(axis=0) + 1e-9
        Call = np.vstack([(np.nan_to_num(CE, nan=0.0) - mu) / sd, (Cb - mu) / sd]).astype(np.float64)
        yall = np.r_[np.ones(G), np.zeros(len(Cb))]
        gid = np.r_[np.arange(G), mt["b_g"]]
        order = np.argsort(gid, kind="stable")
        gs = gid[order]
        starts = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1]])
        counts = np.diff(np.r_[starts, len(gs)])

        def dm(Z):
            Zs = Z[order]
            mean = np.add.reduceat(Zs, starts, axis=0) / counts[:, None]
            res_ = np.empty_like(Zs)
            res_[order] = Zs - np.repeat(mean, counts, axis=0)
            return res_
        Ddm = dm(np.column_stack([Call, yall]))
        med = np.nanmedian(XB, axis=0)
        med = np.where(np.isfinite(med), med, 0.0)
        obs_r = np.empty(len(cols)); perm_r = np.empty((args.n_perm, len(cols)), np.float32); pg_r = np.empty((len(gi), len(cols)), np.float32)
        CH = 48
        for a in range(0, len(cols), CH):
            cc = cols[a: a + CH]
            Yb = np.where(np.isfinite(XB[:, cc]), XB[:, cc], med[cc]).astype(np.float64)
            Ye = np.where(np.isfinite(XE[:, cc]), XE[:, cc], med[cc]).astype(np.float64)
            Yall = np.vstack([Ye, Yb])
            coef, *_ = np.linalg.lstsq(Ddm, dm(Yall), rcond=None)
            Rall = Yall - Call @ coef[:-1]
            Re, Rb = Rall[:G].astype(np.float32), Rall[G:].astype(np.float32)
            o_, pm_, pg_, _ = S1.matched_stats(Re, Rb, gidx, nv, np.arange(len(cc)), B=args.n_perm, seed=args.seed + off)
            obs_r[a: a + len(cc)] = o_; perm_r[:, a: a + len(cc)] = pm_; pg_r[:, a: a + len(cc)] = pg_
        # --- kısmi korelasyon (primer artık istatistik): grup-içi, kontroller sabit
        blk_all = [S1.in_iv(mt["ev_t0"], per[bk]) for bk in ("blk1", "blk2", "blk3")]
        r_obs, r_perm, r_blk = partial_r_stats(XE, XB, gid, Call, order, starts, counts, B=args.n_perm, seed=args.seed + off, blkmask_g=blk_all)
        dev_o, dev_p = np.abs(r_obs), np.abs(r_perm)
        ppr = (1.0 + (dev_p >= dev_o[None, :]).sum(axis=0)) / (args.n_perm + 1.0)
        pfpr = (1.0 + (dev_p.max(axis=1)[None, :] >= dev_o[:, None]).sum(axis=1)) / (args.n_perm + 1.0)
        qpr = S1.bh_q(ppr)
        # sürekli (seyrek olmayan) özellik mi? (artık-AUC yalnız bunlarda yorumlanır)
        cont = np.zeros(len(cols), bool)
        for j in range(len(cols)):
            col_ = XB[:, j]
            col_ = col_[np.isfinite(col_)]
            if len(col_) > 100:
                u_, c_ = np.unique(col_[:: max(1, len(col_) // 20000)], return_counts=True)
                cont[j] = (len(u_) >= 30) and (c_.max() / c_.sum() < 0.30)
        print(f"[rank] {S1.OFF_LABEL[off]} kısmi r: FWER<0,05 {(pfpr < 0.05).sum()}, q<0,10 {(qpr < 0.10).sum()} ({time.time() - t0:.0f} sn)", flush=True)
        pr, prf = S1.pvals_from_perm(obs_r, perm_r)
        qr = S1.bh_q(pr)
        blk_r = {bk: (pg_r[mk].mean(axis=0) if mk.sum() >= 20 else np.full(len(cols), np.nan)) for bk, mk in blkm.items()}
        print(f"[rank] {S1.OFF_LABEL[off]} artık: FWER<0,05 {(prf < 0.05).sum()}, q<0,10 {(qr < 0.10).sum()} ({time.time() - t0:.0f} sn)", flush=True)
        nan_share = np.isnan(XE).mean(axis=0)
        recs = []
        for j, nm in enumerate(names):
            dev = obs_r[j] - 0.5
            cons = sum(1 for bk in blk_r if np.isfinite(blk_r[bk][j]) and np.sign(blk_r[bk][j] - 0.5) == np.sign(dev) and dev != 0)
            dev0 = obs[j] - 0.5
            cons0 = sum(1 for bk in blk if np.isfinite(blk[bk][j]) and np.sign(blk[bk][j] - 0.5) == np.sign(dev0) and dev0 != 0)
            recs.append({"feature": nm, "family": res["family"][nm], "auc": float(obs[j]), "p": float(p[j]), "p_fwer": float(pf[j]), "q": float(q[j]),
                         "auc_resid": float(obs_r[j]), "p_resid": float(pr[j]), "p_fwer_resid": float(prf[j]), "q_resid": float(qr[j]),
                         "blk": [float(blk[b][j]) for b in ("blk1", "blk2", "blk3")], "blk_resid": [float(blk_r[b][j]) for b in ("blk1", "blk2", "blk3")],
                         "consist": cons0, "consist_resid": cons, "nan_share": float(nan_share[j]), "cont": bool(cont[j]),
                         "pr": float(r_obs[j]), "p_pr": float(ppr[j]), "p_fwer_pr": float(pfpr[j]), "q_pr": float(qpr[j]), "blk_pr": [float(r_blk[q][j]) for q in range(3)],
                         "consist_pr": sum(1 for q in range(3) if np.isfinite(r_blk[q][j]) and np.sign(r_blk[q][j]) == np.sign(r_obs[j]) and r_obs[j] != 0)})
        res["rank"][off] = recs
        res["meta"][off] = {"n_events": int(G), "n_base": int(len(XB)), "n_perm": args.n_perm, "n_groups_used": int(len(gi)),
                            "fwer_thr": float(np.quantile(np.abs(perm - 0.5).max(axis=1), 0.95)), "fwer_thr_resid": float(np.quantile(np.abs(perm_r - 0.5).max(axis=1), 0.95)),
                            "n_sig_fwer": int((pf < 0.05).sum()), "n_sig_q10": int((q < 0.10).sum()), "n_sig_fwer_resid": int((prf < 0.05).sum()), "n_sig_q10_resid": int((qr < 0.10).sum()),
                            "n_sig_fwer_pr": int((pfpr < 0.05).sum()), "n_sig_q05_pr": int((qpr < 0.05).sum()), "n_sig_q10_pr": int((qpr < 0.10).sum()),
                            "fwer_thr_pr": float(np.quantile(np.abs(r_perm).max(axis=1), 0.95)), "n_cont": int(cont.sum())}
        del XE, XB, perm, perm_r, pg, pg_r, r_perm
    pickle.dump(res, open(Path(args.out_dir) / "rank2.pkl", "wb"))
    print(f"[rank] bitti ({time.time() - t0:.0f} sn)", flush=True)


def stage_rank_old(args) -> None:
    """Aynı kısmi-korelasyon yöntemiyle ESKİ kütüphane (401 özellik) — yeni ile adil karşılaştırma için."""
    fx = Path(args.fx_dir)
    old = Path(args.old_fx_dir)
    names = json.loads((old / "fx_names.json").read_text(encoding="utf-8"))
    I1.feature_names("5m")
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx = mt["b_idx_old"]
    per = S1.periods()
    G = len(mt["ev_t0"])
    res = {"names": names, "family": {nm: I1.FAMILY.get(nm.split(".", 1)[1], "?") for nm in names}, "rank": {}}
    t0 = time.time()
    for off in args.offsets:
        XE = np.load(old / "snap" / f"XE_{off}.npy")
        XB = np.asarray(np.load(old / "snap" / f"XB_{off}.npy", mmap_mode="r")[keep_idx])
        CE = np.load(old / "snap" / f"CE_{off}.npy")
        CB = np.asarray(np.load(old / "snap" / f"CB_{off}.npy", mmap_mode="r")[keep_idx])
        Cb = np.nan_to_num(CB, nan=0.0)
        mu, sd = Cb.mean(axis=0), Cb.std(axis=0) + 1e-9
        Call = np.vstack([(np.nan_to_num(CE, nan=0.0) - mu) / sd, (Cb - mu) / sd]).astype(np.float64)
        gid = np.r_[np.arange(G), mt["b_g"]]
        order = np.argsort(gid, kind="stable")
        gs = gid[order]
        starts = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1]])
        counts = np.diff(np.r_[starts, len(gs)])
        blk_all = [S1.in_iv(mt["ev_t0"], per[bk]) for bk in ("blk1", "blk2", "blk3")]
        r_obs, r_perm, r_blk = partial_r_stats(XE, XB, gid, Call, order, starts, counts, B=args.n_perm, seed=args.seed + off, blkmask_g=blk_all)
        dev_o, dev_p = np.abs(r_obs), np.abs(r_perm)
        ppr = (1.0 + (dev_p >= dev_o[None, :]).sum(axis=0)) / (args.n_perm + 1.0)
        pfpr = (1.0 + (dev_p.max(axis=1)[None, :] >= dev_o[:, None]).sum(axis=1)) / (args.n_perm + 1.0)
        qpr = S1.bh_q(ppr)
        res["rank"][off] = [{"feature": nm, "family": res["family"][nm], "pr": float(r_obs[j]), "p_pr": float(ppr[j]), "p_fwer_pr": float(pfpr[j]), "q_pr": float(qpr[j]),
                             "blk_pr": [float(r_blk[q][j]) for q in range(3)]} for j, nm in enumerate(names)]
        print(f"[rank_old] {S1.OFF_LABEL[off]}: FWER<0,05 {(pfpr < 0.05).sum()}, q<0,10 {(qpr < 0.10).sum()}, FWER eşiği |r|>{np.quantile(np.abs(r_perm).max(axis=1), 0.95):.4f} ({time.time() - t0:.0f} sn)", flush=True)
        del XE, XB
    pickle.dump(res, open(Path(args.out_dir) / "rank2_old.pkl", "wb"))


# ------------------------------------------------------------------------------------------------ multi
def stage_multi(args) -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    per = S1.periods()
    fx = Path(args.fx_dir)
    old = Path(args.old_fx_dir)
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx = mt["b_idx_old"]
    rng = np.random.default_rng(args.seed)
    b_g = mt["b_g"]
    t0g = mt["ev_t0"]
    G = len(t0g)
    blk_ev = np.full(G, -1)
    for k, bk in enumerate(("blk1", "blk2", "blk3")):
        blk_ev[S1.in_iv(t0g, per[bk])] = k
    keep = np.zeros(len(b_g), bool)
    cnt = np.zeros(G, int)
    for i in rng.permutation(len(b_g)):
        if cnt[b_g[i]] < 12:
            keep[i] = True
            cnt[b_g[i]] += 1
    bi = np.flatnonzero(keep)
    out = {}
    t0 = time.time()
    for off in args.offsets_multi:
        GE = np.load(old / "snap" / f"GE_{off}.npy")
        GB = np.load(old / "snap" / f"GB_{off}.npy", mmap_mode="r")[keep_idx][bi]
        OE = np.load(old / "snap" / f"XE_{off}.npy")
        OB = np.load(old / "snap" / f"XB_{off}.npy", mmap_mode="r")[keep_idx][bi]
        NE = np.load(fx / "snap" / f"XE_{off}.npy")
        NB = np.load(fx / "snap" / f"XB_{off}.npy", mmap_mode="r")[bi]
        y = np.r_[np.ones(G), np.zeros(len(bi))].astype(int)
        grp = np.r_[np.arange(G), b_g[bi]]
        blk = np.r_[blk_ev, blk_ev[b_g[bi]]]
        blocks = {"mevcut 154": [np.vstack([GE, GB])], "+ eski kütüphane": [np.vstack([GE, GB]), np.vstack([OE, OB])],
                  "+ yeni kütüphane": [np.vstack([GE, GB]), np.vstack([NE, NB])],
                  "+ eski + yeni": [np.vstack([GE, GB]), np.vstack([OE, OB]), np.vstack([NE, NB])],
                  "yalnız yeni": [np.vstack([NE, NB])], "yalnız eski": [np.vstack([OE, OB])]}
        res = {}
        for nm, parts in blocks.items():
            Xm = np.hstack(parts).astype(np.float32)
            r = []
            for k in range(3):
                tr_, te_ = (blk != k) & (blk >= 0), blk == k
                clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                                    class_weight="balanced", random_state=0)
                clf.fit(Xm[tr_], y[tr_])
                p = clf.predict_proba(Xm[te_])[:, 1]
                r.append({"auc": float(roc_auc_score(y[te_], p)), "auc_group": S2.S1._group_auc(p, y[te_], grp[te_])})
            res[nm] = r
            print(f"[multi] {S1.OFF_LABEL[off]} {nm}: AUC " + ", ".join(f"{x['auc']:.3f}" for x in r) + " | grup-içi " + ", ".join(f"{x['auc_group']:.3f}" for x in r)
                  + f" ({time.time() - t0:.0f} sn)", flush=True)
            del Xm
        out[off] = res
        del GE, GB, OE, OB, NE, NB
    pickle.dump(out, open(Path(args.out_dir) / "multi2.pkl", "wb"))


def stage_multi_abl(args) -> None:
    """Kesit: yeni kütüphanenin çok değişkenli kazancı saat/seans (zaman) özelliklerinden mi? mevcut154 + yeni(zaman hariç) ve + yalnız zaman/seans özellikleri."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    per = S1.periods()
    fx = Path(args.fx_dir)
    old = Path(args.old_fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    tcols = [j for j, nm in enumerate(names) if any(k in nm for k in (".x2.hour_", ".x2.kz_", ".x2.tr_hour"))]
    dcols = [j for j, nm in enumerate(names) if I2.FAMILY.get(nm.split(".", 1)[1], "") == "x2_day"] if I2.FAMILY else []
    I2.feature_names("5m")
    dcols = [j for j, nm in enumerate(names) if I2.FAMILY.get(nm.split(".", 1)[1], "") == "x2_day"]
    notime = [j for j in range(len(names)) if j not in set(tcols)]
    noday = [j for j in range(len(names)) if j not in set(dcols)]
    mt = np.load(fx / "snap" / "meta2.npz")
    keep_idx = mt["b_idx_old"]
    rng = np.random.default_rng(args.seed)
    b_g = mt["b_g"]
    t0g = mt["ev_t0"]
    G = len(t0g)
    blk_ev = np.full(G, -1)
    for k, bk in enumerate(("blk1", "blk2", "blk3")):
        blk_ev[S1.in_iv(t0g, per[bk])] = k
    keep = np.zeros(len(b_g), bool)
    cnt = np.zeros(G, int)
    for i in rng.permutation(len(b_g)):
        if cnt[b_g[i]] < 12:
            keep[i] = True
            cnt[b_g[i]] += 1
    bi = np.flatnonzero(keep)
    out = {}
    t0 = time.time()
    for off in args.offsets_multi:
        GE = np.load(old / "snap" / f"GE_{off}.npy")
        GB = np.load(old / "snap" / f"GB_{off}.npy", mmap_mode="r")[keep_idx][bi]
        NE = np.load(fx / "snap" / f"XE_{off}.npy")
        NB = np.load(fx / "snap" / f"XB_{off}.npy", mmap_mode="r")[bi]
        base = np.vstack([GE, GB])
        new = np.vstack([NE, NB])
        y = np.r_[np.ones(G), np.zeros(len(bi))].astype(int)
        blk = np.r_[blk_ev, blk_ev[b_g[bi]]]
        sets = {"mevcut 154": base, "+ yeni (saat/seans-zaman özellikleri HARİÇ)": np.hstack([base, new[:, notime]]), "+ yeni (gün/seans ailesi HARİÇ)": np.hstack([base, new[:, noday]]),
                "+ yalnız saat/seans-zaman özellikleri": np.hstack([base, new[:, tcols]]), "+ yeni (hepsi)": np.hstack([base, new])}
        res = {}
        for nm, Xm in sets.items():
            r = []
            for k in range(3):
                tr_, te_ = (blk != k) & (blk >= 0), blk == k
                clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                                    class_weight="balanced", random_state=0)
                clf.fit(Xm[tr_], y[tr_])
                r.append(float(roc_auc_score(y[te_], clf.predict_proba(Xm[te_])[:, 1])))
            res[nm] = r
            print(f"[multi_abl] {S1.OFF_LABEL[off]} {nm}: AUC " + ", ".join(f"{x:.3f}" for x in r) + f" ort {np.mean(r):.4f} ({time.time() - t0:.0f} sn)", flush=True)
        out[off] = res
    pickle.dump(out, open(Path(args.out_dir) / "multi_abl.pkl", "wb"))


# ------------------------------------------------------------------------------------------------ eval
def stage_eval(args) -> None:
    out = Path(args.out_dir)
    (out / "sig").mkdir(exist_ok=True)
    fx = Path(args.fx_dir)
    for k in SIGNALS:
        (out / "sig" / f"G_{k}.npz").write_bytes((fx / "sig" / f"G_{k}.npz").read_bytes())
    if not (out / "cands.json").exists():
        (out / "cands.json").write_text(json.dumps({"summary": {}, "cands": []}), encoding="utf-8")
    S2.GUIDE = sig_guide()
    S2.stage_eval(args)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="feat,snap,rank,multi,eval")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--old-fx-dir", required=True)
    ap.add_argument("--fx-dir", required=True)
    ap.add_argument("--out-dir", default="work/indearly2")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--offsets", type=lambda s: [int(x) for x in s.split(",")], default=[2, 0])
    ap.add_argument("--offsets-multi", type=lambda s: [int(x) for x in s.split(",")], default=[0, 2])
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    args = ap.parse_args(argv)
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
