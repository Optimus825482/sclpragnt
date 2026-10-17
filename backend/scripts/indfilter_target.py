"""B. Hedef boyutlandırma çalışması — hangi özellikler 60 dk hareketin BÜYÜKLÜĞÜNÜ (MFE) ve ters hareketi (MAE) önceden söylüyor? (2026-10-17, çevrimdışı)

Girdi : work/indfilter/{events,prep,feats}_<pop>.*; Çıktı: work/indfilter/section_B.md
Modeller (eğitim = ilk blok, test = sonraki bloklar, DOKUNULMADAN; parametreler yalnız eğitimde seçilir):
  M0 sabit hedef (sinyalin kendi hedefi) + sabit sabitler (1,5 / 2 / 3)
  M1 ATR ölçekli      : tp = clip(k · ATR14(5m)% · sqrt(60/5), lo, hi)                  (k eğitimde)
  M2 ATR + direnç payı: tp = clip(min(M1, pay · direnç_mesafesi), lo, hi)              (direnç kaynağı, pay, k eğitimde)
  M3 ampirik          : sembolün önceki 14 gün 60 dk MFE q'luk yüzdeliği (dyn_target (c))  (q eğitimde)
  M4 doğrusal kuantil regresyonu (az sayıda özellik; eğitimde seçilen) → q'luk MFE tahmini = hedef
  M5 gradyan artırmalı kuantil regresyonu (tüm özellikler)
Ölçütler: hit, net (exit_sim, TP = model hedefi, SL 3, zaman 60), net − oynaklık-eşleşmiş taban (taban da AYNI model hedefiyle), kuantil kalibrasyonu,
pinball kaybı (ATR-yalnız kuantil modeline göre), kısmi Spearman(tahmin, MFE | ATR).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rescan import confirm_elems as C  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402
from scripts.indfilter_study import Study, fp, f2, md, norm_p  # noqa: E402

TP_LO, TP_HI = 1.0, 8.0
SQ = float(np.sqrt(60.0 / 5.0))
K_GRID = (0.25, 0.35, 0.5, 0.7, 0.9, 1.2)
PAY_GRID = (0.5, 0.7, 0.9)
Q_GRID = (0.4, 0.5, 0.6, 0.7)
FIXED = "M0 sabit (sinyalin hedefi)"
KEEP_MIN_TP = 2.5            # "net hedef ≥ ~%2" politikası: model hedefi bu eşiğin altındaysa bildirim yok


def clip_tp(x):
    return np.clip(np.asarray(x, dtype=float), TP_LO, TP_HI)


# ------------------------------------------------------------------------------------------------ B1. öngörülebilirlik
def predictors(st: Study, scope: np.ndarray, top: int = 15) -> tuple[str, dict]:
    p = st.pop
    m0 = scope & st.valid
    mfe, mae = p.mfe, -p.mae
    ys = (("MFE60", mfe), ("MFE60/ATR", mfe / np.maximum(st.atr, 1e-6)), ("|MAE60|", mae), ("|MAE60|/ATR", mae / np.maximum(st.atr, 1e-6)))
    nb = len(st.blocks_labels)
    rows = []
    for j, nm in enumerate(st.names):
        if nm.startswith("idea:") and False:
            continue
        x = st.X[:, j].astype(float)
        xm = x[m0]
        if not K.support_ok(xm, p.day[m0]):
            continue
        r = {"name": nm}
        for key, y in ys:
            r["raw_" + key] = K.partial_spearman(x[m0], y[m0], None, p.day[m0])
            r["par_" + key] = K.partial_spearman(x[m0], y[m0], st.atr[m0], p.day[m0])
        sgn = np.sign(r["par_MFE60"]["r"]) if np.isfinite(r["par_MFE60"]["r"]) else 0.0
        agree = 0
        for b in range(nb):
            mb = m0 & (p.block == b)
            pb = K.partial_spearman(x[mb], mfe[mb], st.atr[mb], p.day[mb])
            agree += int(np.isfinite(pb["r"]) and np.sign(pb["r"]) == sgn and sgn != 0)
        r["agree"] = agree
        rows.append(r)
    for key, _ in ys:
        for pre in ("raw_", "par_"):
            q = C.bh_adjust([norm_p(r[pre + key]) for r in rows])
            for r, qq in zip(rows, q):
                r["q_" + pre + key] = float(qq)
    out = []
    cnt = [[key.replace("|", ""), len(rows), sum(1 for r in rows if r["q_raw_" + key] < 0.05), sum(1 for r in rows if r["q_par_" + key] < 0.05)] for key, _ in ys]
    out.append("Anlamlı (BH q<0,05) özellik sayısı — ham vs ATR-kontrollü:\n\n" + md(["sonuç", "özellik", "ham", "ATR-kontrollü"], cnt))
    atr_r = K.partial_spearman(st.atr[m0], mfe[m0], None, p.day[m0])
    atr_r2 = K.partial_spearman(st.atr[m0], mae[m0], None, p.day[m0])
    out.append("Referans: ATR'nin kendisi ile Spearman(ATR, MFE60) = %+.3f [t %+.1f]; Spearman(ATR, MAE60 mutlak) = %+.3f [t %+.1f].\n"
               % (atr_r["r"], atr_r["t"], atr_r2["r"], atr_r2["t"]))
    hdr = ["özellik", "ham r(MFE) [t]", "ATR-kont. r(MFE) [t]", "q", "blok işaret uyumu", "ATR-kont. r(MFE/ATR) [t]", "ATR-kont. r(MAE mutlak) [t]", "q(MAE)"]

    def row(r):
        return [r["name"], "%+.3f [%+.1f]" % (r["raw_MFE60"]["r"], r["raw_MFE60"]["t"]), "%+.3f [%+.1f]" % (r["par_MFE60"]["r"], r["par_MFE60"]["t"]),
                "%.3f" % r["q_par_MFE60"], "%d/%d" % (r["agree"], nb), "%+.3f [%+.1f]" % (r["par_MFE60/ATR"]["r"], r["par_MFE60/ATR"]["t"]),
                "%+.3f [%+.1f]" % (r["par_|MAE60|"]["r"], r["par_|MAE60|"]["t"]), "%.3f" % r["q_par_|MAE60|"]]
    for key, lab in (("par_MFE60", "MFE60 (ATR-kontrollü)"), ("raw_MFE60", "MFE60 (ham)"), ("par_|MAE60|", "MAE60 mutlak (ATR-kontrollü)")):
        srt = sorted(rows, key=lambda r: -abs(r[key]["t"]) if np.isfinite(r[key]["t"]) else 0)
        out.append("En iyi %d özellik — %s:\n\n" % (top, lab) + md(hdr, [row(r) for r in srt[:top]]))
    best = sorted(rows, key=lambda r: -abs(r["par_MFE60"]["t"]) if np.isfinite(r["par_MFE60"]["t"]) else 0)[:5]
    return "\n".join(out), {"rows": rows, "n_sig_ctrl": cnt[0][3], "best": [(r["name"], r["par_MFE60"]["r"], r["par_MFE60"]["t"], r["agree"]) for r in best],
                            "atr_r": atr_r["r"]}


# ------------------------------------------------------------------------------------------------ model yardımcıları
class Ctx:
    def __init__(self, st: Study, train: np.ndarray, select: str = "excess"):
        self.st, self.train = st, train
        self.select = select            # parametre seçim ölçütü (YALNIZ eğitim bloğunda): 'excess' (net−taban) | 'net' (ham net)
        self.p = st.pop
        self.j = {n: i for i, n in enumerate(st.names)}
        self.cache: dict = {}

    def col(self, name: str) -> np.ndarray:
        i = self.j.get(name)
        return np.full(self.p.n, np.nan) if i is None else self.st.X[:, i].astype(float)

    def train_excess(self, tp: np.ndarray) -> float:
        """Eğitim bloğunda seçim ölçütü: 'excess' = TP=tp ile net − eşleşmiş taban (taban aynı hedefle); 'net' = ham net."""
        if self.select == "net":
            return self.train_net(tp)
        sim = self.p.sim(tp, ev_mask=self.train)
        m = self.train & np.isfinite(sim["net"]) & np.isfinite(sim["b_net"])
        return float(np.mean(sim["net"][m] - sim["b_net"][m])) if m.any() else float("-inf")

    def train_net(self, tp: np.ndarray) -> float:
        sim = self.p.sim(tp, ev_mask=self.train)
        m = self.train & np.isfinite(sim["net"])
        return float(np.mean(sim["net"][m])) if m.any() else float("-inf")


def fit_quantile_linear(Xtr: np.ndarray, ytr: np.ndarray, q: float):
    from sklearn.linear_model import QuantileRegressor
    mdl = QuantileRegressor(quantile=q, alpha=0.0, solver="highs")
    mdl.fit(Xtr, ytr)
    return mdl


def qt_frozen(x: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """x'i ref (eğitim) dağılımının ECDF'sine göre [0,1] aralığına eşler (NaN → 0,5). Eğitimden donmuş."""
    r = np.sort(ref[np.isfinite(ref)])
    if len(r) == 0:
        return np.full(len(x), 0.5)
    u = np.searchsorted(r, x, side="right") / len(r)
    return np.where(np.isfinite(x), u, 0.5)


def select_features(ctx: Ctx, k: int, names: list[str]) -> list[str]:
    """Eğitim bloğunda MFE60/ATR ile |ATR-kontrollü kısmi Spearman| en büyük k özellik (idea:/res: dahil, kapsam > %80)."""
    st, p = ctx.st, ctx.p
    m = ctx.train & st.valid
    y = p.mfe / np.maximum(st.atr, 1e-6)
    sc = []
    for nm in names:
        x = ctx.col(nm)
        if np.isfinite(x[m]).mean() < 0.8 or not K.support_ok(x[m], p.day[m]):
            continue
        r = K.partial_spearman(x[m], y[m], st.atr[m], p.day[m])
        if np.isfinite(r["t"]):
            sc.append((abs(r["t"]), nm))
    sc.sort(reverse=True)
    return [nm for _, nm in sc[:k]]


def design(ctx: Ctx, names: list[str], ref_mask: np.ndarray) -> np.ndarray:
    st = ctx.st
    cols = [np.log(np.maximum(st.atr, 1e-3)), np.log(np.maximum(st.atr, 1e-3)) ** 2]
    for nm in names:
        x = ctx.col(nm)
        cols.append(qt_frozen(x, x[ref_mask & np.isfinite(x)]))
    X = np.column_stack(cols)
    return np.where(np.isfinite(X), X, 0.0)


# ------------------------------------------------------------------------------------------------ modeller
def model_fixed(ctx: Ctx):
    return {"M0 sabit (sinyalin hedefi)": ctx.st.pop.tp.copy(), "sabit 1,5": np.full(ctx.p.n, 1.5), "sabit 2,0": np.full(ctx.p.n, 2.0),
            "sabit 3,0": np.full(ctx.p.n, 3.0)}


def model_atr(ctx: Ctx):
    best = max(K_GRID, key=lambda k: ctx.train_excess(clip_tp(k * ctx.st.atr * SQ)))
    return {"M1 ATR (k=%.2f)" % best: clip_tp(best * ctx.st.atr * SQ)}, best


def res_sources(ctx: Ctx) -> list[str]:
    return [n for n in ctx.st.names if n.startswith("res:")]


def model_res(ctx: Ctx, k0: float):
    srcs = res_sources(ctx)
    if not srcs:
        return {}, None
    best, best_v = None, -1e9
    for sname in srcs:
        d = ctx.col(sname)
        for pay in PAY_GRID:
            for k in (k0, 2 * k0, 4 * k0):
                tp = clip_tp(np.fmin(k * ctx.st.atr * SQ, np.where(np.isfinite(d), pay * d, np.inf)))
                v = ctx.train_excess(tp)
                if v > best_v:
                    best_v, best = v, (sname, pay, k)
    sname, pay, k = best
    d = ctx.col(sname)
    tp = clip_tp(np.fmin(k * ctx.st.atr * SQ, np.where(np.isfinite(d), pay * d, np.inf)))
    return {"M2 ATR+direnç (%s, pay %.1f, k %.2f)" % (sname[4:], pay, k): tp}, best


def model_emp(ctx: Ctx):
    cols = [(n, ctx.col(n)) for n in ctx.st.names if n.startswith("dyn:emp")]
    if not cols:
        return {}, None
    best = max(cols, key=lambda nc: ctx.train_excess(clip_tp(nc[1])))
    return {"M3 ampirik (%s)" % best[0][4:]: clip_tp(best[1])}, best[0]


def model_qr(ctx: Ctx, k_feats: int = 5):
    st, p = ctx.st, ctx.p
    names = [n for n in st.names if not n.startswith("dyn:")]
    sel = select_features(ctx, k_feats, names)
    X = design(ctx, sel, ctx.train)
    m = ctx.train & st.valid & np.isfinite(p.mfe)
    out, info = {}, {"feats": sel, "q": {}}
    best_q, best_v = None, -1e9
    preds = {}
    for q in Q_GRID:
        mdl = fit_quantile_linear(X[m], p.mfe[m], q)
        tp = clip_tp(mdl.predict(X))
        preds[q] = (tp, mdl)
        v = ctx.train_excess(tp)
        info["q"][q] = v
        if v > best_v:
            best_v, best_q = v, q
    out["M4 doğrusal kuantil (q=%.1f, %d özellik)" % (best_q, len(sel))] = preds[best_q][0]
    info["best_q"] = best_q
    info["raw_pred"] = {q: preds[q][0] for q in Q_GRID}
    # ATR-yalnız referans (aynı q)
    X0 = design(ctx, [], ctx.train)
    mdl0 = fit_quantile_linear(X0[m], p.mfe[m], best_q)
    info["atr_only_pred"] = clip_tp(mdl0.predict(X0))
    return out, info


def model_gbm(ctx: Ctx):
    from sklearn.ensemble import HistGradientBoostingRegressor
    st, p = ctx.st, ctx.p
    cols = [i for i, n in enumerate(st.names) if not n.startswith("dyn:") and np.isfinite(st.X[ctx.train & st.valid, i]).mean() > 0.8]
    X = np.column_stack([np.log(np.maximum(st.atr, 1e-3))] + [st.X[:, i].astype(float) for i in cols])
    m = ctx.train & st.valid & np.isfinite(p.mfe)
    best_q, best_v, best_tp = None, -1e9, None
    for q in Q_GRID:
        g = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=3, max_iter=120, learning_rate=0.05,
                                          min_samples_leaf=max(50, int(0.01 * m.sum())), l2_regularization=1.0, random_state=0)
        g.fit(X[m], p.mfe[m])
        tp = clip_tp(g.predict(X))
        v = ctx.train_excess(tp)
        if v > best_v:
            best_v, best_q, best_tp = v, q, tp
    return {"M5 GBM kuantil (q=%.1f, %d özellik)" % (best_q, len(cols)): best_tp}, best_q


# ------------------------------------------------------------------------------------------------ değerlendirme
def eval_models(st: Study, models: dict[str, np.ndarray], blocks, labels, scope: np.ndarray) -> tuple[str, list[dict]]:
    p = st.pop
    nb = len(labels)
    rows, res = [], []
    days = [(b - a + 1) / K.DAY_MS for a, b in blocks]
    sim0 = p.sim(models[FIXED])
    ex0 = sim0["net"] - sim0["b_net"]
    for name, tp in models.items():
        sim = p.sim(tp)
        exm = sim["net"] - sim["b_net"]
        for b, lab in list(enumerate(labels)) + [(-1, "OOS (ilk blok dışı)")]:
            hide = (b == -1 and nb == 2)
            if b >= 0:
                per = p.block == b
                d = days[b]
            else:
                per = np.zeros(p.n, dtype=bool)
                for bb in range(1, nb):
                    per |= p.block == bb
                d = sum(days[1:])
            m = scope & st.valid & per & np.isfinite(sim["net"]) & np.isfinite(tp)
            if m.sum() < 20:
                continue
            ex = C.paired_diff_stats(sim["net"][m], sim["b_net"][m], p.day[m])
            net = C.cluster_bootstrap_mean(sim["net"][m], p.day[m], 300, 1)
            hit = float(np.nanmean(sim["hit"][m]))
            bh = float(np.nanmean(sim["b_hit"][m]))
            # "bildirim yalnız model hedefi ≥ KEEP_MIN_TP" politikası
            kp = m & (tp >= KEEP_MIN_TP)
            ex_k = C.paired_diff_stats(sim["net"][kp], sim["b_net"][kp], p.day[kp]) if kp.sum() >= 20 else {"n": 0, "mean": float("nan")}
            tp_mean = float(np.mean(tp[m]))
            dn = C.paired_diff_stats(sim["net"][m], sim0["net"][m], p.day[m]) if name != FIXED else {"mean": 0.0, "lo": 0.0, "hi": 0.0}
            de = C.paired_diff_stats(exm[m], ex0[m], p.day[m]) if name != FIXED else {"mean": 0.0, "lo": 0.0, "hi": 0.0}
            if not hide:
                rows.append([name, lab, int(m.sum()), "%.2f" % tp_mean, fp(hit), fp(bh), f2(net[0]), f2(float(np.nanmean(sim["b_net"][m]))),
                             "%s [%s; %s]" % (f2(ex["mean"]), f2(ex["lo"]), f2(ex["hi"])),
                             "–" if name == FIXED else "%s [%s; %s]" % (f2(dn["mean"]), f2(dn["lo"]), f2(dn["hi"])),
                             "–" if name == FIXED else "%s [%s; %s]" % (f2(de["mean"]), f2(de["lo"]), f2(de["hi"])),
                             ("%.0f%% / %s (n=%d)" % (100 * kp.sum() / m.sum(), f2(ex_k["mean"]), int(kp.sum()))) if kp.sum() >= 20 else "–"])
            res.append({"name": name, "block": b, "n": int(m.sum()), "tp": tp_mean, "hit": hit, "net": net[0], "ex": ex["mean"], "lo": ex["lo"], "hi": ex["hi"],
                        "b_net": float(np.nanmean(sim["b_net"][m])),
                        "dnet": dn["mean"], "dnet_lo": dn["lo"], "dnet_hi": dn["hi"], "dex": de["mean"], "dex_lo": de["lo"], "dex_hi": de["hi"]})
    hdr = ["model", "dilim", "n", "ort. hedef %", "hit", "taban hit", "net", "taban net", "net−taban [95]", "Δnet vs M0 [95]", "Δ(net−taban) vs M0 [95]",
           "hedef≥%.1f: pay / net−taban" % KEEP_MIN_TP]
    return md(hdr, rows), res


def attrib_table(st: Study, models: dict[str, np.ndarray], blocks, labels, scope: np.ndarray) -> tuple[str, list[dict]]:
    """İNDİKATÖR KATKISI: M4/M5 (özellikli kuantil modeller) − aynı ölçütle seçilmiş ATR-yalnız kuantil referansı; aynı olaylarda eşleştirilmiş fark."""
    p = st.pop
    nb = len(labels)
    rows, res = [], []
    for tag in ("[net]", "[net−taban]"):
        refs = [k for k in models if k.startswith("ref:") and k.endswith(tag)]
        if not refs:
            continue
        sr = p.sim(models[refs[0]])
        exr = sr["net"] - sr["b_net"]
        for name in [k for k in models if k.startswith(("M4", "M5")) and k.endswith(tag)]:
            sm = p.sim(models[name])
            exm = sm["net"] - sm["b_net"]
            for b in list(range(nb)) + [-1]:
                if b == -1 and nb == 2:
                    continue
                per = (p.block == b) if b >= 0 else (p.block >= 1)
                m = scope & st.valid & per & np.isfinite(sm["net"]) & np.isfinite(sr["net"])
                if m.sum() < 20:
                    continue
                dn = C.paired_diff_stats(sm["net"][m], sr["net"][m], p.day[m])
                de = C.paired_diff_stats(exm[m], exr[m], p.day[m])
                lab = labels[b] if b >= 0 else "OOS (ilk blok dışı)"
                rows.append([name, lab, int(m.sum()), "%s [%s; %s]" % (f2(dn["mean"]), f2(dn["lo"]), f2(dn["hi"])),
                             "%s [%s; %s]" % (f2(de["mean"]), f2(de["lo"]), f2(de["hi"]))])
                res.append({"name": name, "block": b, "dnet": dn["mean"], "dnet_lo": dn["lo"], "dex": de["mean"], "dex_lo": de["lo"]})
    return md(["model (özellikli)", "dilim", "n", "Δnet vs ATR-yalnız ref [95]", "Δ(net−taban) vs ATR-yalnız ref [95]"], rows), res


def accuracy_table(st: Study, qmap: dict, models: dict, blocks_labels, scope: np.ndarray) -> tuple[str, list[dict]]:
    """Kuantil modellerinin hedef doğruluğu: kalibrasyon P(MFE ≥ hedef), pinball (kendi q'sunda; aynı q'lu ATR-yalnız referansa göre % iyileşme),
    kısmi Spearman(hedef, MFE | ATR)."""
    p = st.pop
    rows, res = [], []
    pin: dict = {}
    for name, tp in models.items():
        q = qmap.get(name, 0.5)
        for b in range(len(blocks_labels)):
            m = scope & st.valid & (p.block == b) & np.isfinite(p.mfe) & np.isfinite(tp)
            if m.sum() < 30:
                continue
            pin[(name, b)] = K.pinball(p.mfe[m], tp[m], q)
    for name, tp in models.items():
        q = qmap.get(name, 0.5)
        tag = name[name.rindex("["):] if "[" in name else ""
        refs = [k for k in models if k.startswith("ref:") and k.endswith(tag)]
        for b in range(len(blocks_labels)):
            m = scope & st.valid & (p.block == b) & np.isfinite(p.mfe) & np.isfinite(tp)
            if m.sum() < 30:
                continue
            cov = float(np.mean(p.mfe[m] >= tp[m]))
            pr = K.partial_spearman(tp[m], p.mfe[m], st.atr[m], p.day[m])
            rr = K.partial_spearman(tp[m], p.mfe[m], None, p.day[m])
            imp = float("nan")
            if refs and not name.startswith("ref:") and abs(qmap.get(refs[0], -1) - q) < 1e-9 and (refs[0], b) in pin:
                imp = 100.0 * (pin[(refs[0], b)] - pin[(name, b)]) / pin[(refs[0], b)]
            rows.append([name, blocks_labels[b], int(m.sum()), "%.2f" % q, "%.1f%% (hedef %.0f%%)" % (100 * cov, 100 * (1 - q)), "%+.3f" % rr["r"],
                         "%+.3f [t %+.1f]" % (pr["r"], pr["t"]), "%.3f" % pin[(name, b)], ("%+.1f%%" % imp) if np.isfinite(imp) else "–"])
            res.append({"name": name, "block": b, "cov": cov, "q": q, "pin": pin[(name, b)], "pin_imp_pct": imp, "partial": pr["r"]})
    return md(["model", "dilim", "n", "q", "P(MFE ≥ hedef) (kalibrasyon)", "Spearman(hedef, MFE)", "kısmi (ATR sabit) [t]", "pinball",
               "pinball iyileşme vs ATR-yalnız (aynı q)"], rows), res


def run_pop(name: str, blocks, labels, log=print) -> tuple[str, dict]:
    st = Study(name, labels)
    p = st.pop
    train = st.blk(0)
    lines = ["### %s" % {"ha": "Nüfus 1 — Hız Avcısı canlı-benzeri bölümler", "notif": "Nüfus 2 — push bildirimleri"}[name]]
    lines.append("Eğitim: %s (n=%d); test: %s." % (labels[0], int(train.sum()), ", ".join(labels[1:])))
    summ = {"name": name}
    scopes = [("tümü", st.valid)]
    if st.confirm.any():
        scopes.append(("teyit kuralı (yeni canlı)", st.valid & st.confirm))
    for sn, sm in scopes:
        t0 = time.time()
        txt, info = predictors(st, sm)
        lines.append("\n#### B1. MFE / MAE öngörücüleri — kapsam: %s (n=%d)\n\n" % (sn, int((sm & st.valid).sum())) + txt)
        summ["pred_" + sn] = info["best"], info["n_sig_ctrl"], info["atr_r"]
        log("[%s/%s] öngörücüler %.0f sn" % (name, sn, time.time() - t0))
    # modeller: parametre seçimi iki ölçütle (eğitim bloğunda): 'net' (ham net) ve 'excess' (net−taban); sabitler bir kez
    models: dict[str, np.ndarray] = {}
    qmap: dict[str, float] = {}
    infos = {}
    for crit, tag in (("net", "[net]"), ("excess", "[net−taban]")):
        ctx = Ctx(st, train, select=crit)
        if crit == "net":
            models.update(model_fixed(ctx))
        m1, k0 = model_atr(ctx)
        m2, info2 = model_res(ctx, k0)
        m3, info3 = model_emp(ctx)
        m4, info4 = model_qr(ctx)
        m5, info5 = model_gbm(ctx)
        ref = {"ref: ATR-yalnız kuantil (q=%.1f)" % info4["best_q"]: info4["atr_only_pred"]}
        for d in (m1, m2, m3, m4, m5, ref):
            for k, v in d.items():
                models[k + " " + tag] = v
        for k in m4:
            qmap[k + " " + tag] = info4["best_q"]
        for k in ref:
            qmap[k + " " + tag] = info4["best_q"]
        for k in m5:
            qmap[k + " " + tag] = info5
        infos[crit] = {"k_atr": k0, "res": info2, "emp": info3, "qr_feats": info4["feats"], "qr_q": info4["best_q"], "gbm_q": info5}
        log("[%s] seçim ölçütü %s: ATR k=%s res=%s emp=%s qr_q=%s gbm_q=%s" % (name, crit, k0, info2, info3, info4["best_q"], info5))
    lines.append("\n#### B2. Hedef modelleri\n")
    for crit, inf in infos.items():
        lines.append("- Seçim ölçütü `%s` (yalnız eğitim bloğu %s): ATR k=%s; direnç=%s; ampirik=%s; QR özellikleri=%s, q=%s; GBM q=%s"
                     % (crit, labels[0], inf["k_atr"], inf["res"], inf["emp"], inf["qr_feats"], inf["qr_q"], inf["gbm_q"]))
    lines.append("\nDönem `%s` = SEÇİM dönemi (örneklem içi); diğerleri örneklem DIŞI. `net−taban`: aynı model hedefiyle oynaklık-eşleşmiş rastgele giriş. "
                 "[net] / [net−taban] etiketi: parametrelerin hangi ölçütle seçildiği.\n" % labels[0])
    summ["res"] = {}
    for sn, sm in scopes:
        tbl, res = eval_models(st, models, blocks, labels, sm)
        lines.append("\nKapsam: %s\n\n" % sn + tbl)
        summ["res"][sn] = res
        at, ares = attrib_table(st, models, blocks, labels, sm)
        lines.append("\nİndikatör katkısı (özellikli kuantil model − ATR-yalnız kuantil referansı):\n\n" + at)
        summ.setdefault("attr", {})[sn] = ares
        if sn == "tümü":
            at2, ares2 = accuracy_table(st, qmap, {k: v for k, v in models.items() if k.startswith(("M4", "M5", "ref"))}, labels, sm)
            lines.append("\nHedef doğruluğu (kuantil modelleri):\n\n" + at2)
            summ["acc"] = ares2
    summ["models"] = list(models)
    summ["info"] = infos
    return "\n".join(lines), summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pop", default="ha,notif")
    args = ap.parse_args(argv)
    import pickle
    sections, summ = [], {}
    for pop in args.pop.split(","):
        blocks = K.ha_blocks() if pop == "ha" else K.notif_blocks()
        labels = ["B1 (20 Tem–18 Ağu)", "B2 (19 Ağu–17 Eyl)", "B3 (18 Eyl–16 Eki)"] if pop == "ha" else ["seçim 17.09–09.10", "değerlendirme 10.10–17.10"]
        t0 = time.time()
        text, s = run_pop(pop, blocks, labels, log=lambda m: print(m, flush=True))
        sections.append(text)
        summ[pop] = s
        print("[%s] bitti %.0f sn" % (pop, time.time() - t0), flush=True)
    (K.OUT / "section_B.md").write_text("\n\n".join(sections), encoding="utf-8")
    pickle.dump(summ, open(K.OUT / "summary_B.pkl", "wb"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
