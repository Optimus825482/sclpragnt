"""RQK çalışması — analiz aşamaları (zamanlama, giriş sinyali, HA filtresi, parametreler, LUNATRY) → results.json.

`rqk_study.py` çıktılarını (cache/sig, ha_state.npz, mom.npz) ve 90 günlük çalışmanın araçlarını (NullEngine / summarize / Ctx) kullanır.
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path

import numpy as np

from app.rescan import pattern_study as P
from app.rescan import rqk as K
from scripts.pattern90_analysis import KEY_SHIFT, Ctx, in_iv, iv_days, summarize
from scripts.pattern90_study import fmt_t, list_syms, load_events, parse_day
from scripts.rqk_study import (BLOCKS, COMBO_KEYS, COMBOS, DAY_MS, DEFAULT, FEATS, FI, TF_MS, block_ivs, cache_paths)

SEEDS3 = (11, 22, 33)
GAP_MIN = 60                    # sinyal soğuma süresi (dk) — 90 günlük çalışmadaki 12 bar
MIN_PER_DAY_SELECT = 20.0      # parametre seçiminde asgari sinyal/gün


# ------------------------------------------------------------------------------------------------ genel yardımcılar
def jdump(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, default=float), encoding="utf-8")


def auc(x_ev: np.ndarray, x_base: np.ndarray) -> float | None:
    """Mann-Whitney AUC: P(olay > taban) + 0,5·P(eşit). NaN'lar ayrı ayrı atılır."""
    from scipy.stats import rankdata
    a = x_ev[np.isfinite(x_ev)]; b = x_base[np.isfinite(x_base)]
    if len(a) < 20 or len(b) < 20:
        return None
    r = rankdata(np.concatenate([a, b]))
    u = r[: len(a)].sum() - len(a) * (len(a) + 1) / 2.0
    return float(u / (len(a) * len(b)))


def load_sig(args, key: str) -> dict:
    z = np.load(cache_paths(args)["sig"] / f"{key}.npz")
    return {k: z[k] for k in z.files}


def cooldown_mask(sid: np.ndarray, t: np.ndarray, gap_ms: int) -> np.ndarray:
    """Sembol başına: bir sinyalden sonra `gap_ms` dolmadan gelenler atılır (süzgeçten SONRA uygulanır). Dönüş: orijinal sırada bool."""
    n = len(t)
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    order = np.lexsort((t, sid))
    s = sid[order]; tt = t[order]
    last_s = -1; last_t = -(1 << 62)
    ks = np.zeros(n, dtype=bool)
    for i in range(n):
        si = s[i]; ti = tt[i]
        if si != last_s or ti - last_t >= gap_ms:
            ks[i] = True; last_s = si; last_t = ti
    keep[order] = ks
    return keep


def filt_mask(z: dict, filt: str) -> np.ndarray:
    m = np.ones(len(z["t"]), dtype=bool)
    if "ema99" in filt:
        m &= z["above99"]
    if "k15" in filt:
        m &= z["bull15"] == 1
    return m


def follow_setup(ctx: Ctx, events: list[dict]):
    sid_of = {s: k for k, s in enumerate(ctx.syms)}
    es = np.array([sid_of[e["sym"]] for e in events], dtype=np.int64)
    t0 = np.array([e["t0"] for e in events], dtype=np.int64)
    te = np.array([e["t_end"] for e in events], dtype=np.int64)
    o = np.argsort(es * KEY_SHIFT + t0)
    return {"start": (es * KEY_SHIFT + t0 - 10 * 60_000)[o], "t0": (es * KEY_SHIFT + t0)[o], "end": (es * KEY_SHIFT + te)[o]}


def follow_flags(fs: dict, sid: np.ndarray, t: np.ndarray):
    """Sinyal olay penceresinin içinde/öncesinde mi (t0−10dk … t_end) ve erken mi (t0−10dk … t0+15dk)."""
    key = sid.astype(np.int64) * KEY_SHIFT + t
    idx = np.searchsorted(fs["start"], key, side="right") - 1
    ic = np.clip(idx, 0, len(fs["start"]) - 1)
    inside = (idx >= 0) & (key <= fs["end"][ic])
    early = (idx >= 0) & (key <= fs["t0"][ic] + 15 * 60_000)
    return inside, early


def base_rates(ctx: Ctx, fs: dict, ivs) -> dict:
    """Rastgele geçerli anın olay penceresinde olma olasılığı (blok bazlı)."""
    ins = 0; ear = 0; tot = 0
    for sid, vt in ctx.valid_t.items():
        v = vt[in_iv(vt, ivs)]
        if len(v) == 0:
            continue
        a, b = follow_flags(fs, np.full(len(v), sid, dtype=np.int64), v)
        ins += int(a.sum()); ear += int(b.sum()); tot += len(v)
    return {"in": ins / tot if tot else None, "early": ear / tot if tot else None, "n": tot}


def quick(ctx: Ctx, sid, t, out, ivs, *, n_sample: int = 2500, seeds=(11,), fs=None, br=None) -> dict:
    """Hafif ölçü: n, /gün, hit1.5, net60 (TP1.5), trailing, şans farkı (null3), olay izleme kesinliği."""
    m = in_iv(t, ivs)
    sid, t, out = sid[m], t[m], out[m]
    days = iv_days(ivs, ctx.d0, ctx.d1)
    r: dict = {"n": int(len(t)), "per_day": len(t) / days if days else None}
    if len(t) == 0:
        return r
    def mean_se(v):
        v = v[np.isfinite(v)]
        if len(v) < 2:
            return None, None
        return float(v.mean()), float(v.std(ddof=1) / np.sqrt(len(v)))
    r["hit15"], r["hit15_se"] = mean_se(out[:, 0].astype(float))
    r["hit2"], _ = mean_se(out[:, 2].astype(float))
    r["net15"], r["net15_se"] = mean_se(out[:, 1].astype(float))
    r["trail"], r["trail_se"] = mean_se(out[:, 6].astype(float))
    if len(t) >= 30:
        ls = [ctx.null.lift(sid, t, out[:, 0].astype(float), out[:, 4].astype(float), n_sample=n_sample, seed=sd,
                            net15=out[:, 1].astype(float), trail=out[:, 6].astype(float)) for sd in seeds]
        ls = [x for x in ls if x.get("n")]
        if ls:
            for k in ("lift15", "null15", "se15", "liftnet", "nullnet", "se_net", "lifttr", "nulltr", "se_tr", "lift4", "null4"):
                r[k] = float(np.mean([x[k] for x in ls]))
    if fs is not None:
        a, b = follow_flags(fs, sid, t)
        r["p_in"] = float(a.mean()); r["p_early"] = float(b.mean())
        if br:
            r["p_in_lift"] = r["p_in"] / br["in"] if br["in"] else None
            r["p_early_lift"] = r["p_early"] / br["early"] if br["early"] else None
    return r


def day_boot_diff(day: np.ndarray, y: np.ndarray, mask: np.ndarray, *, n_boot: int = 1000, seed: int = 3) -> dict:
    """mask altkümesi ile tümleyeni arasında ortalama farkı (y: 0/1 ya da net) — gün-kümeli bootstrap %95 aralık."""
    ok = np.isfinite(y)
    day, y, mask = day[ok], y[ok], mask[ok]
    if mask.sum() < 20 or (~mask).sum() < 20:
        return {"diff": None}
    ud, inv = np.unique(day, return_inverse=True)
    D = len(ud)
    s1 = np.bincount(inv, weights=y * mask, minlength=D); n1 = np.bincount(inv, weights=mask.astype(float), minlength=D)
    s0 = np.bincount(inv, weights=y * ~mask, minlength=D); n0 = np.bincount(inv, weights=(~mask).astype(float), minlength=D)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, D, size=(n_boot, D))
    a1 = s1[pick].sum(axis=1) / np.maximum(n1[pick].sum(axis=1), 1); a0 = s0[pick].sum(axis=1) / np.maximum(n0[pick].sum(axis=1), 1)
    d = a1 - a0
    return {"diff": float(s1.sum() / n1.sum() - s0.sum() / n0.sum()), "lo": float(np.percentile(d, 2.5)), "hi": float(np.percentile(d, 97.5)),
            "n1": int(mask.sum()), "n0": int((~mask).sum())}


def load_ha(args) -> dict:
    z = np.load(Path(args.p90_dir) / "ha.npz")
    return {"sid": z["sid"].astype(np.int64), "t": z["t"].astype(np.int64), "out": z["out"]}


def ha_state(args, key: str):
    z = np.load(cache_paths(args)["cache"] / "ha_state.npz")
    return z[f"{key}__0"], z[f"{key}__1"], z[f"{key}__2"]


# ------------------------------------------------------------------------------------------------ 1. olay zamanlaması
def analysis_timing(args, ctx: Ctx) -> dict:
    pth = cache_paths(args)
    m = np.load(pth["cache"] / "mom.npz")
    sid, t, kind, k = m["sid"], m["t"], m["kind"], m["k"]
    ev = kind == 1
    t0_of = {int(kk): int(tt) for kk, tt in zip(k[ev], t[ev])}
    ev_t0_for_row = np.array([t0_of[int(kk)] for kk in k])           # taban satırı için kendi olayının t0'ı
    bl = block_ivs()
    blk_row = np.full(len(k), "", dtype=object)
    for name, ivs in bl.items():
        blk_row[in_iv(ev_t0_for_row, ivs)] = name
    ticks = pickle.load(open(Path(args.p90_cache) / "ha_ticks.pkl", "rb"))

    def ha_in(window_lo: int, window_hi: int) -> np.ndarray:
        """Her an için (t+lo, t+hi] içinde HA adayı var mı + ilk HA adayının gecikmesi (dk)."""
        has = np.zeros(len(t), dtype=bool); first = np.full(len(t), np.nan)
        for s in np.unique(sid):
            tk = ticks.get(int(s))
            if tk is None or len(tk) == 0:
                continue
            ix = np.flatnonzero(sid == s)
            j = np.searchsorted(tk, t[ix] + window_lo, side="right")
            jc = np.minimum(j, len(tk) - 1)
            ok = (j < len(tk)) & (tk[jc] <= t[ix] + window_hi)
            has[ix] = ok
            first[ix] = np.where(ok, (tk[jc] - t[ix]) / 60_000.0, np.nan)
        return has, first

    ha15, ha15_first = ha_in(0, 15 * 60_000)
    ha30, ha30_first = ha_in(0, 30 * 60_000)
    res: dict = {"n_events": int(ev.sum()), "n_base": int((~ev).sum()), "tf": {}, "ha": {}}

    def pct(x):
        return float(np.nanmean(x)) if len(x) else None

    def table_for(key: str) -> dict:
        F = m[f"F__{key}"]
        out: dict = {}
        for grp, msk in (("event", ev), ("base", ~ev)):
            G = F[msk]
            row = {}
            for nm in ("s_m15", "s_m10", "s_m5", "s_0", "s_p5", "s_p10", "s_p15", "s_p30"):
                v = G[:, FI[nm]]
                row[nm] = pct(v)
            for nm in ("n_up_m15", "n_up_p15", "n_up_p30"):
                row["p_" + nm] = float(np.mean(G[:, FI[nm]] > 0))
            for nm in ("lastup", "nextup", "nextup_gain", "age0"):
                v = G[:, FI[nm]]
                v = v[np.isfinite(v)]
                row[nm + "_med"] = float(np.median(v)) if len(v) else None
                row[nm + "_n"] = int(len(v))
            nu = G[:, FI["nextup"]]
            row["nextup_le15"] = float(np.mean(np.isfinite(nu) & (nu <= 15)))
            row["nextup_le30"] = float(np.mean(np.isfinite(nu) & (nu <= 30)))
            row["nextup_le60"] = float(np.mean(np.isfinite(nu) & (nu <= 60)))
            out[grp] = row
        # AUC'ler (havuzlanmış + blok bazlı)
        bull0 = F[:, FI["s_0"]]; age = F[:, FI["age0"]]
        signed = np.where(bull0 == 1, age + 1.0, np.where(bull0 == 0, -(age + 1.0), np.nan))
        fresh = np.where(np.isfinite(bull0), ((bull0 == 1) & (age <= 2)).astype(float), np.nan)
        feats = {"bull_t0": bull0, "signed_age_t0": signed, "fresh_bull_t0": fresh, "flip_last15": (F[:, FI["n_up_m15"]] > 0).astype(float),
                 "bull_p15": F[:, FI["s_p15"]], "flip_next15": (F[:, FI["n_up_p15"]] > 0).astype(float), "flip_next30": (F[:, FI["n_up_p30"]] > 0).astype(float)}
        out["auc"] = {}
        for fn, x in feats.items():
            row = {"all": auc(x[ev], x[~ev])}
            for b in bl:
                bm = blk_row == b
                row[b] = auc(x[ev & bm], x[~ev & bm])
            out["auc"][fn] = row
        # kovalı gecikme histogramı (son AL dönüşü / sonraki AL dönüşü)
        bins_prev = [(0, 5), (5, 10), (10, 15), (15, 30), (30, 60), (60, 1e9)]
        out["hist_prev"] = {}; out["hist_next"] = {}
        for grp, msk in (("event", ev), ("base", ~ev)):
            lu = F[msk, FI["lastup"]]; nu = F[msk, FI["nextup"]]
            out["hist_prev"][grp] = [float(np.mean(np.isfinite(lu) & (lu >= a) & (lu < b_))) for a, b_ in bins_prev] + [float(np.mean(~np.isfinite(lu)))]
            out["hist_next"][grp] = [float(np.mean(np.isfinite(nu) & (nu > a) & (nu <= b_))) for a, b_ in ((0, 5), (5, 10), (10, 15), (15, 30), (30, 60), (60, 1e9))] + [float(np.mean(~np.isfinite(nu)))]
        return out

    for tf, key in DEFAULT.items():
        res["tf"][tf] = table_for(key)
    res["all_combos"] = {}
    for key in COMBO_KEYS:
        F = m[f"F__{key}"]
        bull0 = F[:, FI["s_0"]]
        res["all_combos"][key] = {"auc_bull_t0": auc(bull0[ev], bull0[~ev]), "auc_flip_last15": auc((F[ev, FI["n_up_m15"]] > 0).astype(float), (F[~ev, FI["n_up_m15"]] > 0).astype(float)),
                                  "auc_flip_next15": auc((F[ev, FI["n_up_p15"]] > 0).astype(float), (F[~ev, FI["n_up_p15"]] > 0).astype(float)),
                                  "p_flip_next15_ev": float(np.mean(F[ev, FI["n_up_p15"]] > 0)), "p_flip_next15_base": float(np.mean(F[~ev, FI["n_up_p15"]] > 0)),
                                  "p_bull_t0_ev": pct(bull0[ev]), "p_bull_t0_base": pct(bull0[~ev])}
    # HA ile karşılaştırma: 15/30 dk içinde sinyal yakalama (olay vs taban)
    res["ha"] = {"ev_15": float(ha15[ev].mean()), "base_15": float(ha15[~ev].mean()), "ev_30": float(ha30[ev].mean()), "base_30": float(ha30[~ev].mean()),
                 "ev_first_med_15": float(np.nanmedian(ha15_first[ev])) if np.isfinite(ha15_first[ev]).any() else None,
                 "ev_first_med_30": float(np.nanmedian(ha30_first[ev])) if np.isfinite(ha30_first[ev]).any() else None}
    # HA ilk adayının (30 dk içinde) fiyatı P0'a göre: 5m ızgara kapanışı / P0 - 1
    ref_gain = np.full(len(t), np.nan)
    gdir = Path(args.p90_cache) / "grid"
    syms = list_syms(args.p90_cache, "d5")
    for s_ in np.unique(sid[ev & ha30]):
        ix = np.flatnonzero((sid == s_) & ha30)
        f5 = np.load(gdir / f"F5_{syms[int(s_)]}.npy", mmap_mode="r")
        ot5 = np.load(gdir / f"OT_{syms[int(s_)]}.npy")
        tk = t[ix] + (ha30_first[ix] * 60_000).astype(np.int64)
        j = np.clip(np.searchsorted(ot5 + 300_000, tk, side="right") - 1, 0, len(ot5) - 1)
        jr = np.clip(np.searchsorted(ot5 + 300_000, t[ix], side="right") - 1, 0, len(ot5) - 1)
        ref_gain[ix] = (np.asarray(f5[j, P.COL_C]) / np.asarray(f5[jr, P.COL_C]) - 1.0) * 100.0
    res["ha"]["ev_gain_med_30"] = float(np.nanmedian(ref_gain[ev])) if np.isfinite(ref_gain[ev]).any() else None
    res["ha"]["base_gain_med_30"] = float(np.nanmedian(ref_gain[~ev])) if np.isfinite(ref_gain[~ev]).any() else None
    # RQK ve HA ilk-sinyal sırası (aynı olayda 30 dk içinde ikisi de varsa kim önce)
    res["order"] = {}
    for tf, key in DEFAULT.items():
        nu = m[f"F__{key}"][:, FI["nextup"]]
        both = ev & np.isfinite(nu) & (nu <= 30) & np.isfinite(ha30_first)
        d = (ha30_first - nu)[both]
        res["order"][tf] = {"n_both": int(both.sum()), "rqk_first_share": float(np.mean(d > 0)) if both.any() else None,
                            "tie_share": float(np.mean(d == 0)) if both.any() else None,
                            "med_ha_minus_rqk_min": float(np.median(d)) if both.any() else None,
                            "ev_rqk_le30": float(np.mean(np.isfinite(nu[ev]) & (nu[ev] <= 30))), "ev_union_30": float(np.mean(((np.isfinite(nu) & (nu <= 30)) | ha30)[ev])),
                            "base_union_30": float(np.mean(((np.isfinite(nu) & (nu <= 30)) | ha30)[~ev]))}
    return res


# ------------------------------------------------------------------------------------------------ 2. giriş sinyali
def analysis_entry(args, ctx: Ctx, fs, brs) -> dict:
    bl = block_ivs()
    ha = load_ha(args)
    res: dict = {"configs": {}, "ha_ref": {}}
    # HA referansı (blok bazlı)
    for b, ivs in bl.items():
        res["ha_ref"][b] = quick(ctx, ha["sid"], ha["t"], ha["out"], ivs, n_sample=3000, seeds=SEEDS3, fs=fs, br=brs[b])
    nf = json.load(open(cache_paths(args)["cache"] / "n_flip_all.json"))
    for tf in ("5m", "1m"):
        key = DEFAULT[tf]
        z = load_sig(args, key)
        for filt in ("liq", "liq+ema99", "liq+k15", "liq+ema99+k15"):
            if filt == "liq+k15" and tf == "15m":
                continue
            msk = filt_mask(z, filt)
            sid, t, out = z["sid"][msk].astype(np.int64), z["t"][msk], z["out"][msk]
            cm = cooldown_mask(sid, t, GAP_MIN * 60_000)
            cfg = {"raw": {}, "cd": {}}
            for b, ivs in bl.items():
                cfg["raw"][b] = {"per_day": float(in_iv(t, ivs).sum() / iv_days(ivs, ctx.d0, ctx.d1))}
                cfg["cd"][b] = quick(ctx, sid[cm], t[cm], out[cm], ivs, n_sample=3000, seeds=SEEDS3, fs=fs, br=brs[b])
            res["configs"][f"{tf}|{filt}"] = cfg
            print(f"[entry] {tf} {filt} bitti", flush=True)
        # tüm zamanlarda sinyal payı: her bar çifti dönüş sayısı / likit bar
    res["n_flip_all"] = {k: nf[k] for k in nf}
    return res


# ------------------------------------------------------------------------------------------------ 3. HA filtresi
def ha_groups(args) -> dict[str, np.ndarray]:
    """HA satırları için çekirdek durumu grupları (varsayılan A/h8/r2; 5m ve 15m)."""
    s5, a5, _ = ha_state(args, DEFAULT["5m"])
    s15, a15, _ = ha_state(args, DEFAULT["15m"])
    g = {
        "TÜM (HA)": np.ones(len(s5), dtype=bool),
        "5m yeşil": s5 == 1, "5m kırmızı": s5 == 0,
        "5m yeşil, yeni (≤3 bar)": (s5 == 1) & (a5 <= 3), "5m yeşil, olgun (>3 bar)": (s5 == 1) & (a5 > 3),
        "5m kırmızı, yeni (≤3 bar)": (s5 == 0) & (a5 <= 3), "5m kırmızı, olgun (>3 bar)": (s5 == 0) & (a5 > 3),
        "15m yeşil": s15 == 1, "15m kırmızı": s15 == 0,
        "15m yeşil, yeni (≤3 bar)": (s15 == 1) & (a15 <= 3), "15m yeşil, olgun (>3 bar)": (s15 == 1) & (a15 > 3),
        "5m yeşil + 15m yeşil": (s5 == 1) & (s15 == 1), "5m yeşil + 15m kırmızı": (s5 == 1) & (s15 == 0),
        "5m kırmızı + 15m yeşil": (s5 == 0) & (s15 == 1), "5m kırmızı + 15m kırmızı": (s5 == 0) & (s15 == 0),
    }
    return g


def analysis_filter(args, ctx: Ctx, fs, brs) -> dict:
    bl = block_ivs()
    ha = load_ha(args)
    groups = ha_groups(args)
    res: dict = {"groups": {}, "n_ha": int(len(ha["t"]))}
    day = (ha["t"] + 3 * 3600_000) // DAY_MS
    for name, msk in groups.items():
        row = {}
        for b, ivs in bl.items():
            mb = in_iv(ha["t"], ivs) & msk
            r = quick(ctx, ha["sid"][mb], ha["t"][mb], ha["out"][mb], ivs, n_sample=3000, seeds=SEEDS3, fs=fs, br=brs[b])
            allb = in_iv(ha["t"], ivs)
            r["share"] = float(mb.sum() / max(allb.sum(), 1))
            sub = allb
            for mname, col in (("hit15", 0), ("net15", 1), ("trail", 6)):
                y = ha["out"][:, col].astype(float)
                d = day_boot_diff(day[sub], y[sub], msk[sub])
                r[f"d_{mname}"] = d
            row[b] = r
        res["groups"][name] = row
        print(f"[filter] {name}", flush=True)
    return res


# ------------------------------------------------------------------------------------------------ 4. parametreler (yürüyen-ileri)
def analysis_params(args, ctx: Ctx, fs, brs) -> dict:
    bl = block_ivs()
    ha = load_ha(args)
    day = (ha["t"] + 3 * 3600_000) // DAY_MS
    res: dict = {"entry": {}, "filter": {}}
    # --- (E) giriş: sade dönüş + likidite + 60 dk soğuma, 24 kombinasyon
    for key in COMBO_KEYS:
        z = load_sig(args, key)
        sid, t, out = z["sid"].astype(np.int64), z["t"], z["out"]
        cm = cooldown_mask(sid, t, GAP_MIN * 60_000)
        res["entry"][key] = {b: quick(ctx, sid[cm], t[cm], out[cm], ivs, n_sample=3000, seeds=SEEDS3, fs=fs, br=brs[b]) for b, ivs in bl.items()}
        print(f"[params-E] {key}", flush=True)
    # --- (F) HA filtresi: 5m ve 15m kombinasyonları, yeşil / kırmızı
    for key in [c for c in COMBO_KEYS if c.startswith("5m") or c.startswith("15m")]:
        st, age, _ = ha_state(args, key)
        row = {}
        for gname, msk in (("yeşil", st == 1), ("kırmızı", st == 0), ("yeşil yeni≤3", (st == 1) & (age <= 3))):
            row[gname] = {}
            for b, ivs in bl.items():
                allb = in_iv(ha["t"], ivs)
                mb = allb & msk
                r = quick(ctx, ha["sid"][mb], ha["t"][mb], ha["out"][mb], ivs, n_sample=3000, seeds=SEEDS3)
                r["d_hit15"] = day_boot_diff(day[allb], ha["out"][allb, 0].astype(float), msk[allb])
                r["d_net15"] = day_boot_diff(day[allb], ha["out"][allb, 1].astype(float), msk[allb])
                row[gname][b] = r
        # tüm HA (her anahtar için aynı) blok referansı
        res["filter"][key] = row
        print(f"[params-F] {key}", flush=True)
    res["ha_all"] = {b: quick(ctx, ha["sid"][in_iv(ha["t"], ivs)], ha["t"][in_iv(ha["t"], ivs)], ha["out"][in_iv(ha["t"], ivs)], ivs, n_sample=3000, seeds=SEEDS3)
                     for b, ivs in bl.items()}
    return res


# ------------------------------------------------------------------------------------------------ 5. LUNATRY
def analysis_lunatry(args, ctx: Ctx) -> dict:
    pc = Path(args.p90_cache); pth = cache_paths(args)
    sym = "LUNATRY"
    t0 = parse_day("2026-10-17") + 1 * 3600_000                     # 01:00
    lo = parse_day("2026-10-17"); hi = t0 + 3 * 3600_000
    raw = {"1m": np.load(pc / "d1" / f"{sym}.npy")[:, [0, 4]], "5m": np.load(pc / "d5" / f"{sym}.npy")[:, [0, 4]]}
    r15 = np.load(pth["d15"] / f"{sym}.npy"); raw["15m"] = r15
    f5 = np.load(pc / "grid" / f"F5_{sym}.npy"); ot5 = np.load(pc / "grid" / f"OT_{sym}.npy")
    j0 = int(np.searchsorted(ot5 + 300_000, t0, side="right") - 1)
    p0 = float(f5[j0, P.COL_C])                                       # 00:55 5m kapanışı = olay referansı
    after = f5[(ot5 >= t0) & (ot5 < t0 + 3600_000)]
    peak_close = float(after[:, P.COL_C].max()); peak_high = float(after[:, P.COL_H].max())
    res: dict = {"t0": fmt_t(t0, "%Y-%m-%d %H:%M"), "p0": p0, "peak_close_60": peak_close, "gain_close_60": (peak_close / p0 - 1) * 100,
                 "peak_high_60": peak_high, "gain_high_60": (peak_high / p0 - 1) * 100, "tf": {}}
    # HA adayları
    ha_rows = []
    with open(Path(args.rescan_jsonl), encoding="utf-8") as f:
        for line in f:
            if '"LUNATRY"' not in line:
                continue
            r = json.loads(line)
            tm = int(r.get("tick_ms") or 0)
            if r.get("symbol") == "LUNATRY" and lo <= tm <= hi:
                ha_rows.append({"t": fmt_t(tm, "%H:%M"), "tick": tm, "price": r.get("price"), "passes": r.get("passes"), "rank": r.get("rank"),
                                "mfi": r.get("mfi"), "rsi": r.get("rsi"), "exhausted": r.get("exhausted"), "mode": r.get("mode"), "horizon": r.get("horizon_minutes")})
    res["ha_rows"] = ha_rows
    for combo_key in (DEFAULT["1m"], DEFAULT["5m"], DEFAULT["15m"], "5m_B_h8_r2", "5m_A_h16_r2"):
        cb = [c for c in COMBOS if c["key"] == combo_key][0]
        a = raw[cb["tf"]]
        ot = a[:, 0].astype(np.int64); cl = a[:, 1]
        r = K.rqk(cl, cb["h"], cb["r"], variant=cb["var"])
        ct = ot + TF_MS[cb["tf"]]
        sel = (ct >= lo) & (ct <= hi)
        fl = []
        for i in np.flatnonzero((r["flip_up"] | r["flip_dn"]) & sel):
            fl.append({"t": fmt_t(int(ct[i]), "%H:%M"), "dir": "AL(yeşil)" if r["flip_up"][i] else "SAT(kırmızı)", "price": float(cl[i]),
                       "vs_p0_pct": (float(cl[i]) / p0 - 1) * 100, "min_vs_t0": (int(ct[i]) - t0) / 60_000.0})
        # t0'daki durum ve ilk AL (t0'dan sonra)
        i0 = int(np.searchsorted(ct, t0, side="right") - 1)
        up_after = [x for x in fl if x["dir"].startswith("AL") and x["min_vs_t0"] > 0]
        up_before = [x for x in fl if x["dir"].startswith("AL") and x["min_vs_t0"] <= 0]
        ua = np.flatnonzero(r["flip_up"] & (ct <= t0))
        last_any = None
        if len(ua):
            q = int(ua[-1])
            last_any = {"t": fmt_t(int(ct[q]), "%d %H:%M"), "price": float(cl[q]), "min_before": (t0 - int(ct[q])) / 60_000.0, "vs_p0_pct": (float(cl[q]) / p0 - 1) * 100}
        res["tf"][combo_key] = {"state_t0": "yeşil" if bool(r["bull"][i0]) else "kırmızı", "flips": fl, "last_up_any": last_any,
                                "first_up_after": up_after[0] if up_after else None, "last_up_before": up_before[-1] if up_before else None}
    # 1 dk renk dizisi (00:50–01:30)
    cb = [c for c in COMBOS if c["key"] == DEFAULT["1m"]][0]
    a = raw["1m"]; ot = a[:, 0].astype(np.int64); cl = a[:, 1]
    r = K.rqk(cl, cb["h"], cb["r"])
    ct = ot + 60_000
    ser = []
    for i in np.flatnonzero((ct >= t0 - 10 * 60_000) & (ct <= t0 + 30 * 60_000)):
        ser.append({"t": fmt_t(int(ct[i]), "%H:%M"), "close": float(cl[i]), "yhat": float(r["yhat"][i]), "bull": bool(r["bull"][i])})
    res["series_1m"] = ser
    return res


# ------------------------------------------------------------------------------------------------ 6. kontrol: durumun taban etkisi
def did_boot(day_a, y_a, m_a, day_b, y_b, m_b, *, n_boot: int = 1000, seed: int = 4) -> dict:
    """(A grubu: m_a altkümesi - tümleyeni) - (B grubu: aynısı) farkın farkı; günler birlikte yeniden örneklenir."""
    days = np.unique(np.concatenate([day_a, day_b]))
    D = len(days)
    ia = np.searchsorted(days, day_a)
    ib = np.searchsorted(days, day_b)

    def sums(i, y, m):
        ok = np.isfinite(y)
        i, y, m = i[ok], y[ok], m[ok]
        return (np.bincount(i, weights=y * m, minlength=D), np.bincount(i, weights=m.astype(float), minlength=D),
                np.bincount(i, weights=y * ~m, minlength=D), np.bincount(i, weights=(~m).astype(float), minlength=D))
    a1, an1, a0, an0 = sums(ia, y_a, m_a)
    b1, bn1, b0, bn0 = sums(ib, y_b, m_b)

    def stat(p):
        da = a1[p].sum() / max(an1[p].sum(), 1) - a0[p].sum() / max(an0[p].sum(), 1)
        db = b1[p].sum() / max(bn1[p].sum(), 1) - b0[p].sum() / max(bn0[p].sum(), 1)
        return da, db
    rng = np.random.default_rng(seed)
    res = np.array([list(stat(rng.integers(0, D, size=D))) for _ in range(n_boot)])
    da0, db0 = stat(np.arange(D))
    dd = res[:, 0] - res[:, 1]
    return {"d_ha": float(da0), "d_rand": float(db0), "did": float(da0 - db0), "lo": float(np.percentile(dd, 2.5)), "hi": float(np.percentile(dd, 97.5))}


def analysis_control(args, ctx: Ctx) -> dict:
    """Cekirdek durumu (yesil/kirmizi) HA'ya ozgu bir bilgi mi, yoksa her rastgele anda da hit60'i degistiren genel bir taban etkisi mi?
    Ayni sembol + ayni gun rastgele likit anlarda (HA satiri basina <= 20) 'yesil - tumleyeni' isabet farki ve HA'daki farkla fark-farki."""
    from scripts.rqk_study import TfSeries
    pc = Path(args.p90_cache)
    pth = cache_paths(args)
    syms = list_syms(args.p90_cache, "d5")
    keys = [DEFAULT["5m"], DEFAULT["15m"], "15m_A_h25_r2", "5m_A_h25_r2"]
    cb = {c["key"]: c for c in COMBOS}
    ha = load_ha(args)
    ha_days = (ha["t"] + 3 * 3600_000) // DAY_MS
    st_ha = {k: ha_state(args, k)[0] for k in keys}
    rng = np.random.default_rng(5)
    M = {"t": [], "y": [], "day": [], "st": {k: [] for k in keys}}
    U = {"t": [], "y": [], "day": [], "st": {k: [] for k in keys}}
    for sid, sym in enumerate(syms):
        OS = np.load(pc / "grid" / f"OS_{sym}.npy")
        ot5 = np.load(pc / "grid" / f"OT_{sym}.npy")
        f5 = np.load(pc / "grid" / f"F5_{sym}.npy", mmap_mode="r")
        q24 = P.rolling_sum(np.nan_to_num(np.asarray(f5[:, P.COL_QV]), nan=0.0), 288)
        n = len(ot5)
        ok = (OS[:, 0] == 1) & (q24 >= 5_000_000.0) & (np.arange(n) >= 300)
        idx = np.flatnonzero(ok)
        if len(idx) < 50:
            continue
        td = ot5[idx] + 300_000
        raw5 = np.load(pc / "d5" / f"{sym}.npy")
        p15 = pth["d15"] / f"{sym}.npy"
        if not p15.exists():
            continue
        raw15 = np.load(p15)
        st = {}
        for k in keys:
            c = cb[k]
            ts = TfSeries(raw5[:, 0], raw5[:, 4], c) if c["tf"] == "5m" else TfSeries(raw15[:, 0], raw15[:, 1], c)
            st[k] = ts.state_at(td)
        day = (td + 3 * 3600_000) // DAY_MS
        y = OS[idx, 1].astype(float)
        sel = np.arange(0, len(idx), 3)
        U["t"].append(td[sel])
        U["y"].append(y[sel])
        U["day"].append(day[sel])
        for k in keys:
            U["st"][k].append(st[k][sel])
        hm = np.flatnonzero(ha["sid"] == sid)
        if len(hm):
            hday = ha_days[hm]
            by_day = {}
            for d in np.unique(hday):
                pool = np.flatnonzero(day == d)
                if len(pool) >= 10:
                    by_day[int(d)] = pool
            pick = []
            for d in hday:
                pool = by_day.get(int(d))
                if pool is None:
                    continue
                pick.append(rng.choice(pool, size=min(20, len(pool)), replace=False))
            if pick:
                pk = np.concatenate(pick)
                M["t"].append(td[pk])
                M["y"].append(y[pk])
                M["day"].append(day[pk])
                for k in keys:
                    M["st"][k].append(st[k][pk])

    def cat(D):
        return {"t": np.concatenate(D["t"]), "y": np.concatenate(D["y"]), "day": np.concatenate(D["day"]), "st": {k: np.concatenate(D["st"][k]) for k in keys}}
    M = cat(M)
    U = cat(U)
    bl = block_ivs()
    res: dict = {}
    for k in keys:
        res[k] = {}
        for b, ivs in bl.items():
            row = {}
            mh = in_iv(ha["t"], ivs)
            mm = in_iv(M["t"], ivs)
            mu = in_iv(U["t"], ivs)
            gh = st_ha[k][mh] == 1
            gm = M["st"][k][mm] == 1
            gu = U["st"][k][mu] == 1
            row["share_green_ha"] = float(gh.mean())
            row["share_green_matched"] = float(gm.mean())
            row["share_green_all"] = float(gu.mean())
            row["hit_ha_green"] = float(np.nanmean(ha["out"][mh, 0][gh]))
            row["hit_ha_other"] = float(np.nanmean(ha["out"][mh, 0][~gh]))
            row["hit_m_green"] = float(np.nanmean(M["y"][mm][gm]))
            row["hit_m_other"] = float(np.nanmean(M["y"][mm][~gm]))
            row["hit_u_green"] = float(np.nanmean(U["y"][mu][gu]))
            row["hit_u_other"] = float(np.nanmean(U["y"][mu][~gu]))
            row["did"] = did_boot(ha_days[mh], ha["out"][mh, 0].astype(float), gh, M["day"][mm], M["y"][mm], gm)
            row["d_all"] = day_boot_diff(U["day"][mu], U["y"][mu], gu)
            res[k][b] = row
        print(f"[control] {k}", flush=True)
    res["n"] = {"matched": int(len(M["t"])), "all": int(len(U["t"]))}
    return res


# ------------------------------------------------------------------------------------------------ aşamalar
def stage_analyze(args) -> None:
    pth = cache_paths(args)
    t_start = time.time()
    ctx = Ctx(argparse.Namespace(cache_dir=args.p90_cache))
    E = load_events(args.p90_cache)["events"]
    fs = follow_setup(ctx, E)
    bl = block_ivs()
    brs = {b: base_rates(ctx, fs, ivs) for b, ivs in bl.items()}
    print(f"[analyze] taban oranları: {brs}", flush=True)
    only = [x for x in args.only.split(",") if x] if args.only else ["timing", "lunatry", "filter", "entry", "params", "control"]
    fnmap = {"timing": lambda: analysis_timing(args, ctx), "lunatry": lambda: analysis_lunatry(args, ctx),
             "filter": lambda: analysis_filter(args, ctx, fs, brs), "entry": lambda: analysis_entry(args, ctx, fs, brs),
             "params": lambda: analysis_params(args, ctx, fs, brs), "control": lambda: analysis_control(args, ctx)}
    for name in only:
        t1 = time.time()
        r = fnmap[name]()
        jdump(r, pth["out"] / f"res_{name}.json")
        print(f"[analyze] {name} bitti ({time.time() - t1:.0f} sn)", flush=True)
    jdump({"base_rates": brs, "n_events_all": len(E)}, pth["out"] / "res_meta.json")
    print(f"[analyze] toplam {time.time() - t_start:.0f} sn", flush=True)


def stage_report(args) -> None:
    from scripts.rqk_report import build
    build(args)
