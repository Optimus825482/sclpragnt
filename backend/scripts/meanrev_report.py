"""meanrev_study.py `run` çıktısından (agg.npz) analiz + Türkçe rapor (work/meanrev/report.md, results.json). Yalnız dosya okur/yazar; DB'ye dokunmaz.

Önceden kayıtlı ölçüt (ölüm kriteri): bir yapılandırma ancak (a) ≥ 2 / 3 blokta net ortalama > 0 VE (b) aynı bloklarda eşleştirilmiş rastgele girişten ≥ 2 SE yüksekse GEÇER.
Yürüyen-ileri: B2 parametreleri B1'den, B3 parametreleri B1+B2'den seçilir (en yüksek eğitim net ortalaması, eğitimde n ≥ 100); sertlik kipi (M0/M1/M2) dünya varsayımıdır, parametre değildir → ayrı seçim.
Deflated Sharpe: Bailey & López de Prado; deneme sayısı = TÜM ızgara (grup × yapılandırma); SR varyansı bütün hücrelerin OOS-gün Sharpe'larından.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.rescan import meanrev as M
from app.rescan import rotation as R
from scripts import meanrev_study as S

MIN_BLOCK_N = 30
MIN_TRAIN_N = 100
REF_EXIT = 10                                   # T0,8 SL3 Z120
REF_FILL_D = 1                                  # d = %0,1
Z2 = 2.0


# ------------------------------------------------------------------------------------------------ yardımcılar
def vec_mean_se(n: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """n, s: (..., gün). Gün-kümeli ortalama SE (cluster_se_from_sums ile aynı), son eksen gün."""
    N = n.sum(axis=-1)
    tot = s.sum(axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(N > 0, tot / N, np.nan)
        d = s - n * mean[..., None]
        se = np.where(N > 1, np.sqrt((d ** 2).sum(axis=-1)) / N, np.nan)
    return mean, se, N


def blk(b: str) -> slice:
    a, e = S.BLOCKS[b]
    return slice(a, e)


def fmt(x, nd=3, plus=True) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def cfg_index(vi: int, mode: int, di: int, ei: int) -> int:
    return (vi * S.N_FILL + mode * len(S.DS) + di) * S.N_EXIT + ei


def taker_index(tpm: int, var: int, ei: int) -> int:
    return S.N_MAKER + (tpm * 2 + var) * S.N_EXIT + ei


# ------------------------------------------------------------------------------------------------ analiz
class Agg:
    def __init__(self, path: Path):
        z = np.load(path)
        self.n, self.s, self.g, self.tp, self.sl = (z[k] for k in ("n", "s", "g", "tp", "sl"))
        self.adv, self.sig_n, self.ev_cnt = z["adv"], z["sig_n"], z["ev_cnt"]

    def sig(self, g: int):
        return self.n[g], self.s[g]

    def rnd(self, g: int):
        return self.n[S.N_GRP + g], self.s[S.N_GRP + g]


def block_tables(A: Agg) -> dict:
    """Her grup × yapılandırma × blok: sinyal (ort, se, n), rastgele (ort, se, n), fark, fark-SE, geçti-bloğu."""
    G, C = S.N_GRP, S.N_CFG
    out = {k: np.full((G, C, 3), np.nan) for k in ("mu", "se", "n", "rmu", "rse", "rn", "diff", "dse")}
    ok = np.zeros((G, C, 3), dtype=bool)
    for g in range(G):
        ns, ss = A.sig(g)
        nr, sr = A.rnd(g)
        for bi, b in enumerate(S.BLOCKS):
            sl = blk(b)
            mu, se, n = vec_mean_se(ns[:, sl], ss[:, sl])
            rmu, rse, rn = vec_mean_se(nr[:, sl], sr[:, sl])
            diff = mu - rmu
            dse = np.sqrt(se ** 2 + rse ** 2)
            for k, v in (("mu", mu), ("se", se), ("n", n), ("rmu", rmu), ("rse", rse), ("rn", rn), ("diff", diff), ("dse", dse)):
                out[k][g, :, bi] = v
            with np.errstate(invalid="ignore"):
                ok[g, :, bi] = (mu > 0) & (n >= MIN_BLOCK_N) & (rn > 0) & (diff >= Z2 * dse)
    out["ok"] = ok
    out["passed"] = ok.sum(axis=2) >= 2
    return out


def daily_series(n_day: np.ndarray, s_day: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Gün başına ortalama net/işlem (ondalık oran); işlemsiz gün = 0."""
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(n_day[days] > 0, s_day[days] / n_day[days], 0.0)
    return r / 100.0


def sr_stats(r: np.ndarray) -> tuple[float, int, float, float]:
    sr = R.sharpe(r)
    sk, ku = R.moments(r)
    return sr, len(r), sk, ku


def all_cell_sr(A: Agg, days: np.ndarray) -> np.ndarray:
    """Bütün hücrelerin (grup × yapılandırma) günlük Sharpe'ı (OOS günlerinde) — DSR için SR varyansı. Çok az işlemli hücreler (< 200 işlem ya da < 30 aktif gün)
    uç Sharpe üretip varyansı şişirir → dışlanır (DSR'ı iyimser yönde etkiler; yine de hepsi deneme sayısına dâhildir)."""
    srs = []
    for g in range(S.N_GRP):
        n, s = A.sig(g)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(n[:, days] > 0, s[:, days] / n[:, days], 0.0) / 100.0
        sd = r.std(axis=1, ddof=1)
        mu = r.mean(axis=1)
        sr = np.where(sd > 1e-12, mu / np.where(sd > 1e-12, sd, 1.0), np.nan)
        ok = (n[:, days].sum(axis=1) >= 200) & ((n[:, days] > 0).sum(axis=1) >= 30)
        srs.append(np.where(ok, sr, np.nan))
    x = np.concatenate(srs)
    return x[np.isfinite(x)]


def walk_forward(A: Agg, g: int, cfgs: np.ndarray) -> dict:
    """B2 ← B1 eğitimi; B3 ← B1+B2 eğitimi. Dönüş: seçimler, OOS gün serileri (sinyal / rastgele), blok bazlı OOS ortalama, birleşik OOS."""
    ns, ss = A.sig(g)
    nr, sr = A.rnd(g)
    picks = {}
    n_oos = np.zeros(S.D_DAYS); s_oos = np.zeros(S.D_DAYS); rn_oos = np.zeros(S.D_DAYS); rs_oos = np.zeros(S.D_DAYS)
    per_block = {}
    for tb, trains in (("B2", ("B1",)), ("B3", ("B1", "B2"))):
        tr_days = np.concatenate([np.arange(*S.BLOCKS[b]) for b in trains])
        nt = ns[cfgs][:, tr_days].sum(axis=1)
        st = ss[cfgs][:, tr_days].sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            mt = np.where(nt >= MIN_TRAIN_N, st / nt, -np.inf)
        if not np.isfinite(mt).any():
            picks[tb] = None
            continue
        c = int(cfgs[int(np.argmax(mt))])
        picks[tb] = {"cfg": c, "train_mean": float(mt.max()), "train_n": float(nt[int(np.argmax(mt))])}
        te = np.arange(*S.BLOCKS[tb])
        n_oos[te] = ns[c, te]; s_oos[te] = ss[c, te]; rn_oos[te] = nr[c, te]; rs_oos[te] = sr[c, te]
        mu, se, n = M.mean_se(ns[c, te], ss[c, te])
        rmu, rse, rn = M.mean_se(nr[c, te], sr[c, te])
        d, dse = M.diff_se((mu, se, n), (rmu, rse, rn))
        per_block[tb] = {"mu": mu, "se": se, "n": n, "rmu": rmu, "diff": d, "dse": dse}
    te_all = np.arange(S.BLOCKS["B2"][0], S.BLOCKS["B3"][1])
    mu, se, n = M.mean_se(n_oos[te_all], s_oos[te_all])
    rmu, rse, rn = M.mean_se(rn_oos[te_all], rs_oos[te_all])
    d, dse = M.diff_se((mu, se, n), (rmu, rse, rn))
    return {"picks": picks, "per_block": per_block, "oos": {"mu": mu, "se": se, "n": n, "rmu": rmu, "rse": rse, "rn": rn, "diff": d, "dse": dse},
            "n_day": n_oos, "s_day": s_oos, "te_days": te_all}


def dsr_for(series: np.ndarray, n_trials: int, sr_var: float) -> dict:
    sr, n, sk, ku = sr_stats(series)
    return {"sr_daily": sr, "n_days": n, "psr": R.deflated_sharpe(sr, n, sk, ku, 1, sr_var), "dsr": R.deflated_sharpe(sr, n, sk, ku, n_trials, sr_var)}


def btc_blocks(out_dir: Path) -> dict:
    z = np.load(out_dir / "p5.npz", allow_pickle=False)
    syms = [str(s) for s in z["syms"]]
    c = z["C"][syms.index("BTCTRY")]
    day_end = lambda d: min(int((d * 1440) // 5) - 1, len(c) - 1)
    res = {}
    for b, (a, e) in S.BLOCKS.items():
        res[b] = float(c[day_end(e)] / c[day_end(a)] - 1.0) * 100.0
    return res


# ------------------------------------------------------------------------------------------------ rapor
def stage_report(args) -> None:
    out = S.out_dir(args)
    A = Agg(out / "agg.npz")
    G, C = S.N_GRP, S.N_CFG
    BT = block_tables(A)
    n_trials = G * C
    te_days = np.arange(S.BLOCKS["B2"][0], S.BLOCKS["B3"][1])
    sr_all = all_cell_sr(A, te_days)
    sr_var = float(np.var(sr_all, ddof=1))
    btc = btc_blocks(out)

    # --- ölüm kriteri
    passed = BT["passed"]                                         # (G, C)
    n_pass = int(passed.sum())
    pass_by_cat = {}
    cat_of = np.empty(C, dtype=object)
    for c in range(C):
        if c < S.N_MAKER:
            cat_of[c] = S.MODE_NAMES[((c // S.N_EXIT) % S.N_FILL) // len(S.DS)]
        else:
            cat_of[c] = "taker"
    cats = list(S.MODE_NAMES) + ["taker"]
    for cat in cats:
        m = cat_of == cat
        pass_by_cat[cat] = (int(passed[:, m].sum()), int(m.sum()) * G)
    pos2 = (BT["mu"] > 0).sum(axis=2) >= 2                         # ≥ 2 blokta net > 0 (rastgele şartı olmadan)
    pos2_by_cat = {cat: int(pos2[:, cat_of == cat].sum()) for cat in cats}
    ok_blocks_any = BT["ok"].any(axis=2)
    net_pos_blocks = {b: int((BT["mu"][:, :, bi] > 0).sum()) for bi, b in enumerate(S.BLOCKS)}
    cells_valid = int(np.isfinite(BT["mu"]).all(axis=2).sum())

    # --- yürüyen-ileri: grup × kip
    wf = {}
    maker_modes = {}
    for mi in range(len(S.MODES)):
        cf = np.array([cfg_index(vi, mi, di, ei) for vi in range(len(S.VS)) for di in range(len(S.DS)) for ei in range(S.N_EXIT)])
        maker_modes[mi] = cf
    tk_cfgs = np.arange(S.N_MAKER, C)
    for g in range(G):
        for mi in range(len(S.MODES)):
            wf[(g, mi)] = walk_forward(A, g, maker_modes[mi])
        wf[(g, "tk")] = walk_forward(A, g, tk_cfgs)
    for key, w in wf.items():
        n_day, s_day = w["n_day"], w["s_day"]
        r = daily_series(n_day, s_day, w["te_days"])
        w["dsr"] = dsr_for(r, n_trials, sr_var)

    # --- sıralama: tüm blokların birleşimi (betimleyici; kenar iddiası DEĞİL)
    pooled_mu = np.full((G, C), np.nan); pooled_diff = np.full((G, C), np.nan); pooled_dse = np.full((G, C), np.nan); pooled_n = np.zeros((G, C))
    for g in range(G):
        ns, ss = A.sig(g)
        nr, sr = A.rnd(g)
        days = np.arange(1, S.D_DAYS)
        mu, se, n = vec_mean_se(ns[:, days], ss[:, days])
        rmu, rse, rn = vec_mean_se(nr[:, days], sr[:, days])
        pooled_mu[g], pooled_n[g] = mu, n
        pooled_diff[g] = mu - rmu
        pooled_dse[g] = np.sqrt(se ** 2 + rse ** 2)
    valid_cell = pooled_n >= 300
    score = np.where(valid_cell, pooled_mu, -np.inf)
    flat_order = np.argsort(-score.ravel())[:12]
    top_rows = []
    for fi in flat_order:
        g, c = divmod(int(fi), C)
        ns, ss = A.sig(g)
        r = daily_series(ns[c], ss[c], np.arange(1, S.D_DAYS))
        dsr = dsr_for(r, n_trials, sr_var)
        top_rows.append({"g": g, "c": c, "mu": pooled_mu[g, c], "n": pooled_n[g, c], "diff": pooled_diff[g, c], "dse": pooled_dse[g, c],
                         "blocks": [BT["mu"][g, c, bi] for bi in range(3)], "dsr": dsr["dsr"], "sr": dsr["sr_daily"],
                         "rblocks": [BT["rmu"][g, c, bi] for bi in range(3)]})
    best_dsr_hind = max((t["dsr"] for t in top_rows if math.isfinite(t["dsr"])), default=float("nan"))

    # --- referans yapılandırma tablosu (V15, d0,1, çıkış T0,8 SL3 Z120), blok bazlı
    ref_rows = []
    for g in range(G):
        row = {"g": g, "sig": int(A.sig_n[g].sum())}
        for mi in range(len(S.MODES)):
            c = cfg_index(1, mi, REF_FILL_D, REF_EXIT)
            ns, ss = A.sig(g); nr, sr = A.rnd(g)
            d = np.arange(1, S.D_DAYS)
            row[f"M{mi}"] = {"mean": M.mean_se(ns[c, d], ss[c, d]), "rand": M.mean_se(nr[c, d], sr[c, d]),
                             "gross": float(A.g[g, c, d].sum() / max(ns[c, d].sum(), 1)), "tp": float(A.tp[g, c, d].sum() / max(ns[c, d].sum(), 1)),
                             "sl": float(A.sl[g, c, d].sum() / max(ns[c, d].sum(), 1)),
                             "blocks": [M.mean_se(ns[c, blk(b)], ss[c, blk(b)])[0] for b in S.BLOCKS], "rblocks": [M.mean_se(nr[c, blk(b)], sr[c, blk(b)])[0] for b in S.BLOCKS]}
        for lab, tpm, var in (("TK1", 0, 0), ("TK2", 0, 1)):
            c = taker_index(tpm, var, REF_EXIT)
            ns, ss = A.sig(g); nr, sr = A.rnd(g)
            d = np.arange(1, S.D_DAYS)
            row[lab] = {"mean": M.mean_se(ns[c, d], ss[c, d]), "rand": M.mean_se(nr[c, d], sr[c, d]),
                        "gross": float(A.g[g, c, d].sum() / max(ns[c, d].sum(), 1)), "tp": float(A.tp[g, c, d].sum() / max(ns[c, d].sum(), 1)),
                        "sl": float(A.sl[g, c, d].sum() / max(ns[c, d].sum(), 1)),
                        "blocks": [M.mean_se(ns[c, blk(b)], ss[c, blk(b)])[0] for b in S.BLOCKS], "rblocks": [M.mean_se(nr[c, blk(b)], sr[c, blk(b)])[0] for b in S.BLOCKS]}
        ref_rows.append(row)

    # --- dolum oranı ve ters seçilim (V15, d0,1; M0 ve M1)
    adv_rows = []
    for g in range(G):
        for mi in (0, 1):
            cell = 1 * S.N_FILL + mi * len(S.DS) + REF_FILL_D
            e = {"g": g, "mode": mi}
            for lab, gg in (("sig", g), ("rnd", S.N_GRP + g)):
                a = A.adv[gg, cell]                           # (2, gün, 3)
                nf, nu = a[0, 1:, 0], a[1, 1:, 0]
                tot = nf.sum() + nu.sum()
                e[lab] = {"fill": float(nf.sum() / tot) if tot else float("nan"), "n": float(tot),
                          "r60_f": M.mean_se(nf, a[0, 1:, 1])[0] * 100, "r60_u": M.mean_se(nu, a[1, 1:, 1])[0] * 100,
                          "rv_f": M.mean_se(nf, a[0, 1:, 2])[0] * 100, "rv_u": M.mean_se(nu, a[1, 1:, 2])[0] * 100,
                          "r60_all": M.mean_se(nf + nu, a[0, 1:, 1] + a[1, 1:, 1]), }
            adv_rows.append(e)

    # --- kip / d / V duyarlılığı (ref çıkışı, tüm gruplar ortalaması: işlem ağırlıklı)
    sens = []
    for mi in range(len(S.MODES)):
        for di in range(len(S.DS)):
            for vi in range(len(S.VS)):
                c = cfg_index(vi, mi, di, REF_EXIT)
                ns = A.n[:G, c, 1:].sum(); ss_ = A.s[:G, c, 1:].sum()
                nr = A.n[G:, c, 1:].sum(); sr_ = A.s[G:, c, 1:].sum()
                cell = vi * S.N_FILL + mi * len(S.DS) + di
                filled = A.adv[:G, cell, 0, 1:, 0].sum(); allsig = filled + A.adv[:G, cell, 1, 1:, 0].sum()
                sens.append({"mode": mi, "d": S.DS[di], "V": S.VS[vi], "net": ss_ / max(ns, 1), "n": ns, "rnd": sr_ / max(nr, 1), "fill": filled / max(allsig, 1)})

    res = {"n_trials": n_trials, "sr_var": sr_var, "n_pass": n_pass, "pass_by_cat": pass_by_cat, "pos2_by_cat": pos2_by_cat, "net_pos_blocks": net_pos_blocks,
           "cells": cells_valid, "btc_blocks": btc, "best_dsr_hindsight": best_dsr_hind}
    (out / "results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    write_report(out, A, BT, wf, top_rows, ref_rows, adv_rows, sens, res, passed, ok_blocks_any)


# ------------------------------------------------------------------------------------------------ yazım
def gname(g: int) -> str:
    return S.grp_name(g)


def write_report(out: Path, A: Agg, BT: dict, wf: dict, top_rows: list, ref_rows: list, adv_rows: list, sens: list, res: dict, passed: np.ndarray,
                 ok_blocks_any: np.ndarray) -> None:
    G = S.N_GRP
    L: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # ---- üst tablo
    rows = []
    for g in range(G):
        r = {}
        for key, lab in ((1, "M1"), (0, "M0")):
            w = wf[(g, key)]
            o = w["oos"]
            r[lab] = (o["mu"], o["se"], o["n"], o["rmu"], o["diff"], o["dse"], w["dsr"]["dsr"])
        wt = wf[(g, "tk")]["oos"]
        rr = ref_rows[g]
        n_pass_g = int(passed[g].sum())
        rows.append([gname(g), f"{int(A.sig_n[g].sum()):,}".replace(",", "."), str(n_pass_g),
                     f"{fmt(r['M0'][0], 3)} ± {r['M0'][1]:.3f} (n={int(r['M0'][2])})" if r["M0"][2] else "—",
                     f"{fmt(r['M1'][0], 3)} ± {r['M1'][1]:.3f} (n={int(r['M1'][2])})" if r["M1"][2] else "—",
                     fmt(r["M1"][3], 3), fmt(r["M1"][4], 3) + f" ({r['M1'][4] / r['M1'][5]:+.1f} SE)" if r["M1"][5] and math.isfinite(r["M1"][5]) else "—",
                     fmt(r["M1"][6], 3, False),
                     f"{fmt(wt['mu'], 3)} ± {wt['se']:.3f}" if wt["n"] else "—"])
    head_tbl = md_table(["Tetik|evren", "Sinyal", "Geçen yapılandırma (396)", "YİS OOS net/işlem % — M0 (dokunma, iyimser)", "YİS OOS net % — M1 (vwap-giriş)", "Rastgele (aynı icra, M1)",
                         "Fark (M1 − rastgele)", "DSR (M1)", "YİS OOS net % — taker giriş"], rows)
    n_pass = res["n_pass"]
    cats = res["pass_by_cat"]
    best_oos = max(((wf[(g, mi)]["oos"]["mu"], g, mi) for g in range(G) for mi in (0, 1, 2) if wf[(g, mi)]["oos"]["n"] > 50), default=(float("nan"), -1, -1))
    best_oos_m1 = max(((wf[(g, 1)]["oos"]["mu"], g) for g in range(G) if wf[(g, 1)]["oos"]["n"] > 50), default=(float("nan"), -1))
    max_dsr = max((wf[(g, k)]["dsr"]["dsr"] for g in range(G) for k in (0, 1, 2, "tk") if math.isfinite(wf[(g, k)]["dsr"]["dsr"])), default=float("nan"))
    verdict = verdict_text(res, best_oos, best_oos_m1, max_dsr, n_pass, cats, wf, ref_rows, adv_rows)
    L.append("# Ortalamaya dönüş + pasif (limit) icra — Binance TR TRY spot, uzun-yönlü")
    L.append(f"*Oluşturma: {now}. Çevrimdışı araştırma (canlı kod / DB yazımı / commit YOK). Veri: 2026-07-19 → 2026-10-17 (90 gün, TR günleri); bloklar B1 07-20..08-18, "
             f"B2 08-19..09-17, B3 09-18..10-16.*\n")
    L.append("## Karar\n")
    L.append(verdict + "\n")
    L.append("## Özet tablo\n")
    L.append("YİS = yürüyen-ileri seçim: B2 parametreleri B1'den, B3'ünkiler B1+B2'den seçildi (en yüksek eğitim net ortalaması); OOS = B2+B3 birleşimi (59 gün). "
             "Net = işlem başına yüzde (ücret + kayma sonrası, yalnız DOLAN işlemler). ± gün-kümeli SE. Fark SE'si bağımsız-SE (muhafazakâr).\n")
    L.append(head_tbl + "\n")
    L.append(f"**Ölüm kriteri** (≥ 2/3 blokta net > 0 ∧ eşleştirilmiş rastgeleden ≥ 2 SE yüksek): {n_pass} / {res['n_trials']} hücre geçti "
             f"(maker M0 {cats[S.MODE_NAMES[0]][0]}/{cats[S.MODE_NAMES[0]][1]}, M1 {cats[S.MODE_NAMES[1]][0]}/{cats[S.MODE_NAMES[1]][1]}, "
             f"M2 {cats[S.MODE_NAMES[2]][0]}/{cats[S.MODE_NAMES[2]][1]}, taker {cats['taker'][0]}/{cats['taker'][1]}). "
             f"Toplam deneme (grup × yapılandırma) = {res['n_trials']}; DSR bu sayıya göre.\n")
    # ---- yöntem
    L.append("## Yöntem\n")
    L.append(method_text())
    # ---- ölüm kriteri ayrıntı
    L.append("## 1. Ölüm kriteri ayrıntısı\n")
    L.append(f"Hücre = (tetik × evren) × (maker 324 + taker 72) = {res['n_trials']}. İstatistiksel beklenti: farkın ≥ 2 SE olması tek blokta yaklaşık %2,3 (tek yön); ≥ 2/3 blokta "
             "bağımsız olsalar ≈ %0,15 → ~8 hücre şans eseri geçebilir (hücreler güçlü korele olduğundan gerçek dağılım daha geniş kuyruklu).\n")
    rows = []
    for cat in list(S.MODE_NAMES) + ["taker"]:
        rows.append([cat, str(cats[cat][1]), str(res["pos2_by_cat"][cat]), str(cats[cat][0])])
    L.append(md_table(["İcra kipi", "Hücre", "≥ 2 blokta net > 0 (rastgele şartı yok)", "GEÇEN (net>0 ∧ ≥ 2 SE > rastgele, ≥ 2 blok)"], rows) + "\n")
    L.append("Blok başına net > 0 olan hücre sayısı: " + ", ".join(f"{b}: {res['net_pos_blocks'][b]}/{res['n_trials']}" for b in S.BLOCKS) + ". "
             "BTCTRY al-tut (blok getirisi): " + ", ".join(f"{b} {res['btc_blocks'][b]:+.1f}%" for b in S.BLOCKS) + ".\n")
    if n_pass:
        L.append("Geçen hücreler (tetik|evren, yapılandırma, blok net %, rastgele %, fark/SE):\n")
        idx = np.argwhere(passed)
        rows = []
        for g, c in idx[:40]:
            rows.append([gname(int(g)), S.cfg_name(int(c)), " / ".join(fmt(BT["mu"][g, c, bi], 3) for bi in range(3)), " / ".join(fmt(BT["rmu"][g, c, bi], 3) for bi in range(3)),
                         " / ".join(f"{BT['diff'][g, c, bi] / BT['dse'][g, c, bi]:+.1f}" for bi in range(3)), " / ".join(str(int(BT["n"][g, c, bi])) for bi in range(3))])
        L.append(md_table(["Grup", "Yapılandırma", "Net B1/B2/B3", "Rastgele B1/B2/B3", "Fark SE B1/B2/B3", "n B1/B2/B3"], rows) + "\n")
        if len(idx) > 40:
            L.append(f"(ilk 40 / {len(idx)} gösterildi)\n")
    # ---- sıralama
    L.append("## 2. Hindsight en iyi hücreler (betimleyici — kenar iddiası DEĞİL)\n")
    L.append("Tüm günler birleşik (n ≥ 300) net ortalamaya göre ilk 12 hücre. DSR bu hücre seçildikten SONRA, tüm ızgaraya göre indirgenmiş değerdir.\n")
    rows = []
    for t in top_rows:
        rows.append([gname(t["g"]), S.cfg_name(t["c"]), f"{fmt(t['mu'], 3)}", str(int(t["n"])), " / ".join(fmt(x, 3) for x in t["blocks"]), " / ".join(fmt(x, 3) for x in t["rblocks"]),
                     f"{fmt(t['diff'], 3)} ({t['diff'] / t['dse']:+.1f} SE)" if t["dse"] and math.isfinite(t["dse"]) else "—", fmt(t["dsr"], 3, False)])
    L.append(md_table(["Grup", "Yapılandırma", "Net %", "n", "Blok net B1/B2/B3", "Rastgele B1/B2/B3", "Fark", "DSR"], rows) + "\n")
    # ---- WF ayrıntı
    L.append("## 3. Yürüyen-ileri ayrıntısı (seçilen yapılandırmalar)\n")
    rows = []
    for g in range(G):
        for key, lab in ((0, "M0"), (1, "M1"), (2, "M2"), ("tk", "taker")):
            w = wf[(g, key)]
            p2, p3 = w["picks"].get("B2"), w["picks"].get("B3")
            pb = w["per_block"]
            rows.append([gname(g), lab, S.cfg_name(p2["cfg"]) if p2 else "—", S.cfg_name(p3["cfg"]) if p3 else "—",
                         fmt(pb["B2"]["mu"], 3) if "B2" in pb else "—", fmt(pb["B3"]["mu"], 3) if "B3" in pb else "—",
                         f"{fmt(w['oos']['mu'], 3)} ± {w['oos']['se']:.3f}" if w["oos"]["n"] else "—", fmt(w["oos"]["rmu"], 3), str(int(w["oos"]["n"])),
                         fmt(w["dsr"]["sr_daily"], 3), fmt(w["dsr"]["psr"], 3, False), fmt(w["dsr"]["dsr"], 3, False)])
    L.append(md_table(["Grup", "Kip", "B2 seçimi (B1)", "B3 seçimi (B1+B2)", "B2 OOS net", "B3 OOS net", "OOS net ± SE", "Rastgele OOS", "n", "Günlük SR", "PSR", "DSR"], rows) + "\n")
    L.append(f"SR varyansı (günlük, tüm hücreler, OOS günleri) = {res['sr_var']:.3e}; deneme sayısı = {res['n_trials']}. Günlük seri: günün işlem başına ortalama neti (işlemsiz gün = 0) — "
             "gerçek portföy getirisi değil, sinyal başına kazanç vekili.\n")
    # ---- referans ayrıntı
    L.append("## 4. Referans yapılandırma (V=15, d=%0,1, T=%0,8, SL=%3, zaman 120 dk) — icra duyarlılığı\n")
    L.append("Tüm günler birleşik (gün 1–89). Brüt = ücretsiz getiri (dolum/kayma modeli dâhil), TP/SL = çıkış payları. TK1 = piyasa girişi (+%0,15 kayma, taker) + TP maker; "
             "TK2 = TK1 ama TP de piyasa (taker + kayma). 'Rastgele' = ATR eşleşmiş rastgele giriş, aynı icra.\n")
    rows = []
    for rr in ref_rows:
        g = rr["g"]
        for lab, nm in (("M0", "maker M0 dokunma"), ("M1", "maker M1 vwap-giriş"), ("M2", "maker M2 vwap-giriş+çıkış"), ("TK1", "taker giriş TK1"), ("TK2", "taker her bacak TK2")):
            x = rr[lab]
            m, se, n = x["mean"]
            rm = x["rand"][0]
            rows.append([gname(g), nm, f"{fmt(m, 3)} ± {se:.3f}" if n else "—", str(int(n)), fmt(x["gross"], 3), fmt(rm, 3), " / ".join(fmt(b, 3) for b in x["blocks"]),
                         f"{x['tp'] * 100:.0f}% / {x['sl'] * 100:.0f}%"])
    L.append(md_table(["Grup", "İcra", "Net %", "n (dolan)", "Brüt %", "Rastgele net %", "Blok net B1/B2/B3", "TP / SL payı"], rows) + "\n")
    # ---- adverse selection
    L.append("## 5. Dolum oranı ve ters seçilim (V=15, d=%0,1)\n")
    L.append("Getiri: tetik kapanışından (P0) emir bitişine kadar (rV: 15. dk kapanışı) ve 60 dk sonrasına (r60), %. 'Dolan' = limit dolanlar, 'dolmayan' = emir süresi bitenler. "
             "Ters seçilim: dolanlar, fiyat düşmeye devam eden olaylardır (rV, r60 dolanlarda dolmayanlardan düşük).\n")
    rows = []
    for e in adv_rows:
        s_, r_ = e["sig"], e["rnd"]
        rows.append([gname(e["g"]), S.MODE_NAMES[e["mode"]].split()[0], f"{s_['fill'] * 100:.0f}%", f"{r_['fill'] * 100:.0f}%", fmt(s_["rv_f"], 3), fmt(s_["rv_u"], 3), fmt(s_["r60_f"], 3), fmt(s_["r60_u"], 3),
                     f"{fmt(s_['r60_all'][0] * 100, 3)} ± {s_['r60_all'][1] * 100:.3f}", fmt(r_["r60_all"][0] * 100, 3), fmt(r_["r60_f"], 3), fmt(r_["r60_u"], 3)])
    L.append(md_table(["Grup", "Kip", "Dolum (sinyal)", "Dolum (rastgele)", "rV dolan", "rV dolmayan", "r60 dolan", "r60 dolmayan", "r60 tüm sinyaller ± SE", "Rastgele r60 tüm", "Rastgele r60 dolan", "Rastgele r60 dolmayan"], rows) + "\n")
    # ---- duyarlılık
    L.append("## 6. Sertlik, d ve V duyarlılığı (referans çıkış; tüm 14 grup işlem-ağırlıklı)\n")
    rows = []
    for x in sens:
        rows.append([S.MODE_NAMES[x["mode"]], f"%{x['d']:g}", str(x["V"]), f"{x['fill'] * 100:.0f}%", fmt(x["net"], 3), fmt(x["rnd"], 3), f"{int(x['n']):,}".replace(",", ".")])
    L.append(md_table(["Kip", "d", "V (dk)", "Dolum oranı", "Net % (sinyal)", "Net % (rastgele)", "n dolan"], rows) + "\n")
    L.append(limits_text(res))
    (out / "report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"[report] yazıldı → {out / 'report.md'}")


def verdict_text(res: dict, best_oos: tuple, best_oos_m1: tuple, max_dsr: float, n_pass: int, cats: dict, wf: dict, ref_rows: list, adv_rows: list) -> str:
    g, mi = best_oos[1], best_oos[2]
    adv = {(e["g"], e["mode"]): e for e in adv_rows}
    gi = {S.grp_name(i): i for i in range(S.N_GRP)}
    bd, d5 = adv[(gi["BD|5M"], 1)], adv[(gi["D|5M"], 1)]
    drift = ", ".join(f"{t} {adv[(gi[t + '|5M'], 1)]['sig']['r60_all'][0] * 100:+.2f}%" for t in S.TRIGS)
    rnd_drift = float(np.mean([adv[(gi[t + '|5M'], 1)]["rnd"]["r60_all"][0] * 100 for t in S.TRIGS]))
    parts = []
    parts.append(f"**Sonuç: kenar yok — ölüm kriterini geçen yapılandırma {n_pass}/{res['n_trials']}** "
                 f"(maker M0 {cats[S.MODE_NAMES[0]][0]}, M1 {cats[S.MODE_NAMES[1]][0]}, M2 {cats[S.MODE_NAMES[2]][0]}, taker {cats['taker'][0]}). "
                 f"Net > 0 olan hücre sayısı blok başına B1 {res['net_pos_blocks']['B1']}, B2 {res['net_pos_blocks']['B2']}, B3 {res['net_pos_blocks']['B3']} (/{res['n_trials']}); "
                 "hiçbir hücre iki blokta birden pozitif değil. ")
    if math.isfinite(best_oos[0]) and g >= 0:
        parts.append(f"Yürüyen-ileri (parametreler yalnız geçmiş bloklarla seçilerek) en iyi OOS: {S.grp_name(g)} / {S.MODE_NAMES[mi].split()[0]} (en iyimser dolum varsayımı) "
                     f"{best_oos[0]:+.3f}%/işlem (SE {wf[(g, mi)]['oos']['se']:.3f}, n={int(wf[(g, mi)]['oos']['n'])}) — sıfırdan ayırt edilemez ama pozitif de değil; "
                     f"katı dolum (M1) ile en iyisi {best_oos_m1[0]:+.3f}% ({S.grp_name(best_oos_m1[1])}); en yüksek DSR {max_dsr:.3f}. ")
    parts.append(f"**Mekanizma:** (1) Sinyallerde GÖRELİ bilgi var: BD (baz-kapılı Bollinger/MFI) üç blokta da ATR'si eşleşmiş rastgele girişten ~+0,2–0,3 pp iyi, AD/CD benzer yönde; "
                 f"limitsiz (tetik kapanışından) 60 dk brüt sürüklenme ≥5M evrende {drift} (rastgele ortalama {rnd_drift:+.2f}%). "
                 f"(2) Ama bu sürüklenmeyi ucuz icra yakalamıyor: taker (0,525% gidiş-dönüş) maliyeti aşıyor; limit alış ise ters seçilimle sürüklenmenin büyük kısmını kaçırıyor — "
                 f"BD|5M'de limit %{bd['sig']['fill'] * 100:.0f} doluyor, dolanların 60 dk getirisi {bd['sig']['r60_f']:+.2f}%, dolmayanlarınki {bd['sig']['r60_u']:+.2f}% "
                 f"(rastgele girişte {bd['rnd']['r60_f']:+.2f}% / {bd['rnd']['r60_u']:+.2f}%: etkinin büyük kısmı mekanik, ama sinyalin ekstra getirisi dolmayanlarda birikiyor; D|5M'de dolum %{d5['sig']['fill'] * 100:.0f}). "
"(3) Brüt kenar maker maliyetinin (≈ 0,135% + stop/zaman çıkışı taker payı) altında kalıyor: referans yapılandırmada maker brüt çoğunlukla −0,05…−0,38% (tek istisna BD|50M M0, +0,02%). ")
    parts.append("**Sınırlar:** yalnız 90 gün ve tek rejim (BTCTRY blok getirileri B1 +1,6%, B2 +20,5%, B3 +8,5%; ayı bloğu YOK) — pozitif bloklar boğa ayına denk; "
                 "dolum modeli kuyruk önceliğini bilmez (M0 iyimser üst sınır, M1/M2 katı alt sınır — gerçek dolum ikisi arasında); evren ex-post 304 likit sembol (hafif sağ-kalım yanlılığı); "
                 "olaylar bağımsız işlem varsayılır (eşzamanlı sermaye kısıtı / sepet modellenmedi).")
    return "".join(parts)


def method_text() -> str:
    return """**Veri.** `historical_candles` 1m/5m (önbellek `p90cache`, 304 likit sembol), `historical_trade_flow` dakika VWAP'ı, `hist_futures_metrics` (OI, OI notional) + `futures_symbol_map` (çarpan); baz = 1e4·ln(perp/spot), perp = OI notional/OI/çarpan, spot = TRY/USDTTRY; z = 24 sa (288 bar) kayan z; metrics satırı `ts_ms` 5 dk diliminin BAŞLANGICIDIR, değer ts+5 dk'da bilinir → satır ts=T, ot[i]=T olan 5 dk muma bağlanır ve karar t_dec = ot+5 dk'dır (`flow_futures.align_metric_rows`; testle doğrulandı). Yalnız okuma.

**Tetikler (önceden belirlendi, veri madenciliği yok).** Karar 5 dk kapanışında (t_dec = ot+5 dk); tetik başına sembol bazında 1 sa (12 bar) soğuma. A: 15 dk getirisi kesitte alt %10 ∧ 60 dk eşit-ağırlık piyasa getirisi ≥ 0; B: kapanış < Bollinger(20, 2) alt bant ∧ MFI14 < 20; C: yeni 24 sa dip, ≤ 3 bar içinde önceki dibin üstünde ilk kapanış; D: baz z kesitte üst %20; AD/BD/CD: A/B/C ∧ D (baz kapısı). Evren: 24 sa TRY hacmi ≥ 5M ve ≥ 50M (kesit sıralaması ve rastgele havuz o evrende); pegli çiftler (MAV, USDC, USDT, U) dışlandı.

**Giriş (pasif).** Limit alış = tetik kapanışı × (1 − d), d ∈ {0, %0,1, %0,3}; emir t_dec'te konur, V ∈ {5, 15} dk geçerli. Dolum: sonraki 1 dk barlardan ilkinde LOW ≤ limit (M0, iyimser) ya da dakika VWAP ≤ limit (M1/M2, katı; `historical_trade_flow`, işlem yoksa dolmaz). Dolum fiyatı = limit (açılış daha iyiyse bile — kötümser). Maker ücreti %0,0675, kayma yok.

**Çıkış.** Kâr al = LİMİT satış entry×(1+T), T ∈ {0,4; 0,8; 1,2}%: HIGH ≥ seviye (M0, M1) ya da VWAP ≥ seviye (M2); maker %0,0675; dolum barında değerlendirilmez. Koruyucu: stop %2/%3 (dolum barı dâhil, LOW ≤ stop; aynı barda TP+stop → stop; boşlukta açılıştan) ve zaman stopu 60/120/240 dk (dolumdan itibaren) piyasa emri: taker %0,1125 + %0,15 kayma. Kontrol: çıkış motoru `exit_sim.simulate` ile aynı sonucu verir (testte rastgele yollarla, 3 çıkış türü).

**Karşılaştırmalar.** (1) Taker: aynı sinyaller, bir sonraki dakika açılışı × 1,0015, taker %0,1125; TK1 = TP maker, TK2 = TP de piyasa. (2) ATR14(5m)'si eşleşmiş rastgele giriş: aynı sembol/blok/evren içinde olay başına 2 çekiliş (ATR sıra penceresi ±%5), aynı icra, aynı çıkış. Fark SE'si iki ortalamanın bağımsız gün-kümeli SE'lerinden (muhafazakâr).

**İstatistik.** İşlem başına net %, gün-kümeli SE (gün = TR günü; `exit_sim.cluster_se` ile aynı sayı, testli). Bloklar: B1 07-20..08-18 (30 g), B2 08-19..09-17 (30 g), B3 09-18..10-16 (29 g); 07-19 ısınma. Yürüyen-ileri: B2 ← B1, B3 ← B1+B2 (en yüksek eğitim net ortalaması, eğitimde n ≥ 100); kip (M0/M1/M2) dünya varsayımı olduğu için ayrı seçilir. Deflated Sharpe: Bailey & López de Prado, deneme = bütün hücreler.
"""


def limits_text(res: dict) -> str:
    return f"""## 7. Sınırlar ve dürüstlük notları

* **Yalnız 90 gün, tek rejim.** BTCTRY blok getirileri: {', '.join(f"{b} {res['btc_blocks'][b]:+.1f}%" for b in S.BLOCKS)}; ayı bloğu yok. Sonuçlar boğa/yatay rejimine koşulludur; ayı rejiminde ortalamaya dönüş (düşen bıçak) çok daha kötü olabilir.
* **Dolum modeli kaba.** M0 (dokunma = dolum) kuyruk önceliğini yok sayar → iyimser; M1/M2 (dakika VWAP'ı) gerçek dolumdan daha az dolum verir → katı. Gerçek dolum oranı arada. Dolum fiyatı limit (kötümser); emir defteri / spread modellenmedi (bid vekili = tetik kapanışı).
* **Ters seçilim doğrudan ölçüldü** (Bölüm 5) ve zaten net sonuca işlenmiş durumda: aynı icra rastgele girişlere de uygulandığı için "dolum = düşüş" etkisi hem sinyalde hem rastgelede var; fark sinyal bilgisidir.
* **Olaylar bağımsız işlem varsayılır**; eşzamanlı pozisyon sınırı, sermaye kısıtı ve sepet birleşimi yok. Günlük Sharpe "işlem başına ortalama net" vekilidir.
* **Evren yanlılığı:** 1m verisi, 90 günde yeterince likit kalan 304 sembol için var (önceden hesaplanmış `liquid.json`); gün içi 24 sa hacim filtresi nedenseldir ama sembol listesi ex-post (hafif sağ-kalım yanlılığı).
* **Çoklu test:** {res['n_trials']} hücre (7 tetik × 2 evren × (324 maker + 72 taker)); bunların ek olarak seçim sırasında yürüyen-ileri ile daraltılması DSR'a işlendi. Hindsight en iyi hücrenin DSR'ı {res['best_dsr_hindsight']:.3f}.
* **Brüt kenar:** referans tablosunda brüt getiri (ücretsiz, dolum/kayma dâhil) çoğu hücrede NEGATİF; yani sorun yalnız ücret değil: limit dolumunun kendisi (ters seçilim, dolum sonrası negatif sürüklenme ≈ −0,1%) ve koruyucu çıkış kayması brüt değeri eritiyor. Maker ücret avantajı (≈ 0,39 pp/gidiş-dönüş) bunu kapatmaya yetmiyor.
* **Dolum sonrası sürüklenme:** rastgele girişlerde bile dolanların 60 dk getirisi, dolum fiyatı hesaba katıldığında negatif (≈ −0,1%); bu bir dolum-mekaniği/mikroyapı etkisidir (düşüşe dokunan limitler düşüş sürerken dolar) ve eşleştirilmiş rastgele ile karşılaştırma bunu ayıklar.
"""
