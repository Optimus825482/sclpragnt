"""OFFLINE olasılık denetimi: radar bildirimindeki `ml_hit_probability` kalibrasyonu,
yeniden kalibrasyon, yedek model ve EV (beklenen değer) testi.

Salt-okunur (DB'ye YAZMAZ). Canlı kod değişmez. Çıktı:
  backend/work/prob_audit/tables.md  (tüm sayısal tablolar)
Önbellek: SCRATCH/prob_audit/vc.npz  (yeniden çekmek için --refetch)

Çalıştırma:  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/prob_audit.py
Python 3.11 uyumlu (f-string içinde aynı tür tırnak yok).
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

DSN = os.getenv("PROB_AUDIT_DSN", "postgresql://postgres:518518Erkan@localhost:5432/scalper")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "work", "prob_audit")
CACHE_DIR = os.getenv(
    "PROB_AUDIT_CACHE",
    r"C:\Users\Erkan\AppData\Local\Temp\claude\D--PROJELLER-sclpragnt\bb25c086-ec89-43e9-a810-f345b61672ad\scratchpad\prob_audit")
TZ_OFF = 3 * 3600  # Europe/Istanbul (UTC+3, DST yok)

# Maliyet modeli (%): giriş taker 0.1125 + giriş kayma 0.15 ; TP çıkışı maker 0.0675 ;
# stop / süre çıkışı taker 0.1125 + çıkış kayması 0.15
COST_TP = 0.1125 + 0.15 + 0.0675          # 0.33
COST_NT = 0.1125 + 0.15 + 0.1125 + 0.15   # 0.525

D0 = dt.date(1970, 1, 1)


def dnum(y, m, d):
    return (dt.date(y, m, d) - D0).days


BLOCKS = {"B1": (dnum(2026, 9, 17), dnum(2026, 10, 1)),
          "B2": (dnum(2026, 10, 2), dnum(2026, 10, 9)),
          "B3": (dnum(2026, 10, 10), dnum(2026, 10, 31))}
BLOCK_LABEL = {"B1": "B1 09-17..10-01", "B2": "B2 10-02..10-09", "B3": "B3 10-10..10-18"}

OUT_LINES: list[str] = []


def emit(s: str = "") -> None:
    print(s, flush=True)
    OUT_LINES.append(s)


def table(headers, rows):
    emit("| " + " | ".join(headers) + " |")
    emit("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        emit("| " + " | ".join(str(x) for x in r) + " |")
    emit("")


def f3(x, nd=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    return f"{x:.{nd}f}"


def pm(v, se, nd=3):
    if v is None or not math.isfinite(v):
        return "-"
    if se is None or not math.isfinite(se):
        return f"{v:.{nd}f}"
    return f"{v:.{nd}f}±{se:.{nd}f}"


# ----------------------------------------------------------------------------- veri
def fetch(refetch: bool = False) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "vc.npz")
    if os.path.exists(path) and not refetch:
        z = np.load(path, allow_pickle=True)
        return {k: z[k] for k in z.files}
    import psycopg
    t0 = time.time()
    sql = """
    SELECT created_at, symbol,
           COALESCE(NULLIF(substring(candidate_id from 'vel-(\\d+)dk'), '')::int, 0) AS horizon,
           target_pct, atr_pct, volume_ratio, ret3_pct, velocity_score, passes, rank, mfe_pct,
           touched_target::int, exit_pct, net_pct, ml_hit_probability, ml_target_pct,
           outcome_details->>'status_reason',
           NULLIF(outcome_details->'features'->>'taker_buy_ratio','')::float8,
           NULLIF(outcome_details->'features'->>'book_imbalance','')::float8,
           outcome_details->'features'->>'mode'
    FROM velocity_candidates
    WHERE status='evaluated' AND touched_target IS NOT NULL
      AND created_at >= %s AND created_at < %s
    ORDER BY created_at"""
    rows = []
    with psycopg.connect(DSN) as con:
        con.read_only = True
        cur = con.cursor()
        cur.execute("SELECT min(created_at), max(created_at) FROM velocity_candidates")
        lo, hi = cur.fetchone()
        d_lo, d_hi = int((lo + TZ_OFF) // 86400), int((hi + TZ_OFF) // 86400)
        for d in range(d_lo, d_hi + 1):
            a, b = d * 86400 - TZ_OFF, (d + 1) * 86400 - TZ_OFF
            cur.execute(sql, (a, b))
            chunk = cur.fetchall()
            rows.extend(chunk)
            print(f"  fetch gün {D0 + dt.timedelta(days=d)} n={len(chunk)}", flush=True)
    print(f"fetch tamam n={len(rows)} {time.time() - t0:.0f}s", flush=True)

    def col(i):
        out = np.empty(len(rows), dtype=float)
        for k, r in enumerate(rows):
            v = r[i]
            out[k] = np.nan if v is None else v
        return out

    data = {
        "created_at": col(0), "symbol": np.array([r[1] for r in rows], dtype=object),
        "horizon": col(2), "target_pct": col(3), "atr_pct": col(4), "volume_ratio": col(5),
        "ret3_pct": col(6), "velocity_score": col(7),
        "passes": np.array([bool(r[8]) for r in rows]), "rank": col(9), "mfe_pct": col(10),
        "touched": col(11), "exit_pct": col(12), "net_stored": col(13), "ml_p": col(14),
        "ml_target": col(15), "reason": np.array([r[16] or "" for r in rows], dtype=object),
        "taker": col(17), "book": col(18), "mode": np.array([r[19] or "" for r in rows], dtype=object),
    }
    np.savez_compressed(path, **data)
    return data


def prep(raw: dict) -> dict:
    d = dict(raw)
    d["day"] = np.floor((d["created_at"] + TZ_OFF) / 86400).astype(np.int64)
    d["hour"] = (np.floor(((d["created_at"] + TZ_OFF) % 86400) / 3600)).astype(np.int64)
    blk = np.full(len(d["day"]), "", dtype=object)
    for name, (a, b) in BLOCKS.items():
        blk[(d["day"] >= a) & (d["day"] <= b)] = name
    d["block"] = blk
    d["hit"] = np.where(np.isfinite(d["touched"]), d["touched"], 0.0).astype(float)
    exit_ = d["exit_pct"].copy()
    fill = (d["hit"] > 0.5) & ~np.isfinite(exit_)
    exit_[fill] = d["target_pct"][fill]
    d["exit_pct"] = exit_
    cost = np.where(d["hit"] > 0.5, COST_TP, COST_NT)
    d["net"] = exit_ - cost                    # yeniden hesaplanan net (kullanıcı maliyet modeli)
    d["net_ok"] = np.isfinite(d["net"])
    d["ypos"] = np.where(d["net_ok"], (d["net"] > 0).astype(float), np.nan)
    d["live"] = d["passes"] & np.isfinite(d["rank"]) & (d["rank"] <= 10)
    d["has_p"] = np.isfinite(d["ml_p"])
    return d


def sel(d, mask):
    return {k: v[mask] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(mask)}


# ----------------------------------------------------------------------------- gün-kümeli metrikler
NB_ECE = 10
K_AUC = 1000


class Clustered:
    """Satır kümesi + kümeler (gün); tahmin vektörleri için Brier/ECE/AUC + cluster-bootstrap SE."""

    def __init__(self, y, cluster, B=400, seed=11):
        self.y = np.asarray(y, float)
        self.u, self.inv = np.unique(cluster, return_inverse=True)
        self.D = len(self.u)
        self.n = len(self.y)
        rng = np.random.default_rng(seed)
        self.W = rng.multinomial(self.D, np.ones(self.D) / self.D, size=B).astype(float)  # (B,D)

    def _stats(self, p):
        p = np.clip(np.asarray(p, float), 0, 1)
        D, y, inv = self.D, self.y, self.inv
        n_d = np.bincount(inv, minlength=D).astype(float)
        sse_d = np.bincount(inv, weights=(p - y) ** 2, minlength=D)
        eb = np.minimum((p * NB_ECE).astype(int), NB_ECE - 1)
        cols = [n_d, sse_d]
        for b in range(NB_ECE):
            m = (eb == b)
            cols.append(np.bincount(inv[m], minlength=D).astype(float))
            cols.append(np.bincount(inv[m], weights=p[m], minlength=D))
            cols.append(np.bincount(inv[m], weights=y[m], minlength=D))
        edges = np.unique(np.quantile(p, np.linspace(0, 1, K_AUC + 1)))
        ab = np.searchsorted(edges[1:-1], p, side="right")
        K = max(len(edges) - 1, 1)
        pos = np.zeros((D, K))
        neg = np.zeros((D, K))
        ip = y > 0.5
        np.add.at(pos, (inv[ip], ab[ip]), 1.0)
        np.add.at(neg, (inv[~ip], ab[~ip]), 1.0)
        base = np.stack(cols, axis=1)
        return base, pos, neg

    @staticmethod
    def _metrics(base, pos, neg):
        n = base[..., 0]
        brier = base[..., 1] / n
        ece = 0
        for b in range(NB_ECE):
            ece = ece + np.abs(base[..., 2 + 3 * b + 2] - base[..., 2 + 3 * b + 1])
        ece = ece / n
        P, N = pos.sum(-1), neg.sum(-1)
        negcum = np.cumsum(neg, axis=-1) - neg
        auc = (pos * (negcum + 0.5 * neg)).sum(-1) / np.maximum(P * N, 1e-12)
        auc = np.where((P > 0) & (N > 0), auc, np.nan)
        return brier, ece, auc

    def evaluate(self, preds: dict, ref=None):
        res = {}
        boots = {}
        for name, p in preds.items():
            base, pos, neg = self._stats(p)
            pt = self._metrics(base.sum(0), pos.sum(0), neg.sum(0))
            Bb = np.tensordot(self.W, base, axes=(1, 0))
            Bp = np.tensordot(self.W, pos, axes=(1, 0))
            Bn = np.tensordot(self.W, neg, axes=(1, 0))
            bt = self._metrics(Bb, Bp, Bn)
            boots[name] = bt
            res[name] = {"brier": float(pt[0]), "ece": float(pt[1]), "auc": float(pt[2]),
                         "se_brier": float(np.nanstd(bt[0], ddof=1)),
                         "se_ece": float(np.nanstd(bt[1], ddof=1)),
                         "se_auc": float(np.nanstd(bt[2], ddof=1)),
                         "mean_p": float(np.mean(p))}
        if ref and ref in preds:
            for name in preds:
                if name == ref:
                    continue
                res[name]["d_brier"] = res[name]["brier"] - res[ref]["brier"]
                res[name]["se_d_brier"] = float(np.nanstd(boots[name][0] - boots[ref][0], ddof=1))
                res[name]["d_auc"] = res[name]["auc"] - res[ref]["auc"]
                res[name]["se_d_auc"] = float(np.nanstd(boots[name][2] - boots[ref][2], ddof=1))
                res[name]["d_ece"] = res[name]["ece"] - res[ref]["ece"]
                res[name]["se_d_ece"] = float(np.nanstd(boots[name][1] - boots[ref][1], ddof=1))
        return res

    def ratio_by_group(self, g, values, ngroups):
        """Her grup için küme-sağlam ortalama (Σv/Σn) ve bootstrap SE."""
        out = []
        v = np.asarray(values, float)
        for k in range(ngroups):
            ok = (g == k) & np.isfinite(v)
            n_d = np.bincount(self.inv[ok], minlength=self.D).astype(float)
            s_d = np.bincount(self.inv[ok], weights=v[ok], minlength=self.D)
            N, S = n_d.sum(), s_d.sum()
            if N == 0:
                out.append((0, np.nan, np.nan))
                continue
            with np.errstate(invalid="ignore", divide="ignore"):
                bm = (self.W @ s_d) / (self.W @ n_d)
            out.append((int(N), S / N, float(np.nanstd(bm, ddof=1))))
        return out


def cluster_mean(values, cluster):
    """Seçili satırlarda küme-sağlam ortalama ± SE (oran tahmincisi doğrusallaştırması). (n, mean, se)."""
    values = np.asarray(values, float)
    ok = np.isfinite(values)
    if ok.sum() == 0:
        return 0, np.nan, np.nan
    u, inv = np.unique(cluster[ok], return_inverse=True)
    D = len(u)
    n_d = np.bincount(inv, minlength=D).astype(float)
    s_d = np.bincount(inv, weights=values[ok], minlength=D)
    N, S = n_d.sum(), s_d.sum()
    R = S / N
    if D < 2:
        return int(N), float(R), np.nan
    se = math.sqrt(D / (D - 1) * np.sum((s_d - R * n_d) ** 2)) / N
    return int(N), float(R), float(se)


def wd_auc(preds: dict, y, day, ref=None, B=400, seed=3):
    """Gün-içi AUC: her günün AUC'si P*N ile ağırlıklı havuzlanır. Küme=gün bootstrap.
    Döner ad -> [auc, se, d_vs_ref, se_d]. Gün düzeyi seviye kaymasından (rejim) arındırılmış ayırt edicilik."""
    from scipy.stats import rankdata
    y = np.asarray(y, float)
    u, inv = np.unique(day, return_inverse=True)
    D = len(u)
    rng = np.random.default_rng(seed)
    W = rng.multinomial(D, np.ones(D) / D, size=B).astype(float)
    out, boots = {}, {}
    for name, p in preds.items():
        p = np.asarray(p, float)
        num = np.zeros(D)
        den = np.zeros(D)
        for k in range(D):
            m = inv == k
            yy = y[m]
            P = float((yy > 0.5).sum())
            N = float(len(yy) - P)
            if P == 0 or N == 0:
                continue
            r = rankdata(p[m])
            auc = (r[yy > 0.5].sum() - P * (P + 1) / 2) / (P * N)
            num[k], den[k] = auc * P * N, P * N
        pt = num.sum() / den.sum()
        with np.errstate(invalid="ignore", divide="ignore"):
            bt = (W @ num) / (W @ den)
        boots[name] = bt
        out[name] = [pt, float(np.nanstd(bt, ddof=1)), None, None]
    if ref in preds:
        for name in preds:
            if name != ref:
                out[name][2] = out[name][0] - out[ref][0]
                out[name][3] = float(np.nanstd(boots[name] - boots[ref], ddof=1))
    return out


# ----------------------------------------------------------------------------- modeller
def logit(p, eps=1e-4):
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def fit_iso(p, y):
    from sklearn.isotonic import IsotonicRegression
    m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    m.fit(p, y)
    return lambda q: m.predict(np.asarray(q, float))


def fit_platt(p, y):
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression(C=1e4, max_iter=500)
    m.fit(logit(p).reshape(-1, 1), y)

    def f(q):
        return m.predict_proba(logit(np.asarray(q, float)).reshape(-1, 1))[:, 1]
    f.params = (float(m.coef_[0][0]), float(m.intercept_[0]))
    return f


def base_features(d, extra=False):
    atr = d["atr_pct"]
    cols = [atr, d["ret3_pct"], np.log1p(np.clip(d["volume_ratio"], 0, None)),
            np.log1p(np.clip(d["velocity_score"], 0, None)), d["target_pct"],
            d["target_pct"] / np.where(atr > 0, atr, np.nan), d["horizon"],
            d["hour"].astype(float), d["passes"].astype(float)]
    names = ["atr", "ret3", "logvol", "logscore", "target", "target/atr", "horizon", "hour", "passes"]
    if extra:
        cols += [d["taker"], d["book"]]
        names += ["taker", "book"]
    return np.stack(cols, axis=1).astype(float), names


class LRModel:
    def __init__(self):
        from sklearn.linear_model import LogisticRegression
        self.lr = LogisticRegression(C=0.5, max_iter=500)

    def _t(self, X, fit=False):
        X = X.copy()
        if fit:
            self.lo = np.nanpercentile(X, 0.5, axis=0)
            self.hi = np.nanpercentile(X, 99.5, axis=0)
            self.med = np.nanmedian(np.clip(X, self.lo, self.hi), axis=0)
        X = np.clip(X, self.lo, self.hi)
        bad = ~np.isfinite(X)
        X[bad] = np.take(self.med, np.where(bad)[1])
        if fit:
            self.mu = X.mean(0)
            self.sd = X.std(0) + 1e-9
        return (X - self.mu) / self.sd

    def fit(self, X, y):
        self.lr.fit(self._t(X, True), y)
        return self

    def predict(self, X):
        return self.lr.predict_proba(self._t(X))[:, 1]


def hgb_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_depth=5,
                                          min_samples_leaf=400, l2_regularization=1.0,
                                          early_stopping=False, random_state=0)


def hgb_reg():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06, max_depth=5,
                                         min_samples_leaf=400, l2_regularization=1.0,
                                         early_stopping=False, random_state=0)


FOLDS = [("B2", ["B1"]), ("B3", ["B1", "B2"])]


def prior_rate(d, train_blocks, label="hit", mask=None):
    m = np.isin(d["block"], train_blocks)
    if mask is not None:
        m = m & mask
    return float(np.nanmean(d[label][m]))


# ----------------------------------------------------------------------------- bölümler
def section_cover(d):
    emit("## 0. Veri kapsamı")
    rows = []
    for b in list(BLOCKS) + ["ALL"]:
        m = np.ones(len(d["day"]), bool) if b == "ALL" else (d["block"] == b)
        rows.append([BLOCK_LABEL.get(b, "TÜMÜ"), int(m.sum()), int((m & d["has_p"]).sum()),
                     int((m & d["has_p"] & d["live"]).sum()),
                     len(np.unique(d["day"][m & d["has_p"]])),
                     f3(float(np.mean(d["hit"][m])), 3),
                     f3(float(np.nanmean(d["net"][m & d["net_ok"]])), 3)])
    table(["blok", "değerlendirilmiş satır", "p dolu", "p dolu + canlı-benzeri (passes, rank<=10)", "gün (p dolu)", "touched oranı", "ort. net% (yeniden hesap)"], rows)
    nonp = ~d["has_p"]
    suf = np.array([str(s)[-3:] for s in d["symbol"]])
    emit(f"p BOŞ satırlar: {int(nonp.sum())} ({nonp.mean():.1%}); p boşların TRY oranı: "
         f"{float(np.mean(suf[nonp] == 'TRY')) if nonp.any() else float('nan'):.1%}; "
         f"p dolu satırların TRY oranı: {float(np.mean(suf[~nonp] == 'TRY')):.1%}")
    tk = np.isfinite(d["taker"])
    first = (D0 + dt.timedelta(days=int(d["day"][tk].min()))) if tk.any() else "-"
    emit(f"outcome_details.features (taker/book/mode) dolu satır: {int(tk.sum())} (ilk gün: {first})")
    emit("Etiket rejimleri (tanım zamanla değişti — blok karşılaştırmasında karıştırıcı):")
    reg_rows = []
    for nm, (a_, b_) in (("R0 09-17..09-21 (TP/SL yarışı YOK; eski etiket)", (dnum(2026, 9, 17), dnum(2026, 9, 21))),
                         ("R1 09-22..10-07 (SL ~%1.5)", (dnum(2026, 9, 22), dnum(2026, 10, 7))),
                         ("R2 10-08..10-18 (SL %5)", (dnum(2026, 10, 8), dnum(2026, 10, 31)))):
        m = (d["day"] >= a_) & (d["day"] <= b_)
        stp = m & (d["reason"] == "STOPPED_OUT")
        ex = m & (d["reason"] == "MAX_HORIZON_EXPIRED")
        reg_rows.append([nm, int(m.sum()), f3(float(d["hit"][m].mean())),
                         f3(float(stp.sum() / m.sum()), 3), f3(float(ex.sum() / m.sum()), 3),
                         f3(float(np.nanmedian(d["exit_pct"][stp])), 2) if stp.any() else "-",
                         f3(float(np.nanmean(d["net"][m & d["net_ok"]])), 3)])
    table(["rejim", "n", "touched oranı", "stop payı", "süre-doldu payı", "stop çıkış medyanı%", "ort. net%"], reg_rows)
    ok = d["net_ok"] & np.isfinite(d["net_stored"])
    emit(f"DB `net_pct` − yeniden hesaplanan net (ort.): {float(np.mean(d['net_stored'][ok] - d['net'][ok])):+.3f} pp "
         "(DB'deki maliyet modeli dönemsel farklı; analiz yeniden hesaplananı kullanır)")
    emit("")


def section_a(d):
    emit("## A. Kalibrasyon (ham `ml_hit_probability` -> touched_target)")
    emit("touched_target = TP(target_pct) 60 dk içinde stop öncesi dokundu mu (stop mesafesi zamanla değişti: bkz. rejim tablosu). ML'in eğitim etiketinden (5/15 dk MFE>=%2/%3) FARKLIDIR.")
    emit("")
    m0 = d["has_p"]
    h, _ = np.histogram(d["ml_p"][m0], bins=10, range=(0, 1))
    emit("Ham p dağılımı (10 kutu, p-dolu değerlendirilmiş satırlar, n=%d): %s" % (m0.sum(), " ".join(f"{x / m0.sum():.1%}" for x in h)))
    pp = d["ml_p"][m0]
    emit(f"p<0.10: {np.mean(pp < 0.1):.1%}; p>=0.90: {np.mean(pp >= 0.9):.1%}; 0.2<=p<0.8: {np.mean((pp >= .2) & (pp < .8)):.1%}")
    emit("")
    summary = []
    allrows = np.ones(len(m0), bool)
    for subset_name, subset_mask in (("tüm adaylar", allrows), ("canlı-benzeri", d["live"])):
        for b in list(BLOCKS) + ["ALL"]:
            mb = (allrows if b == "ALL" else d["block"] == b) & m0 & subset_mask
            if mb.sum() < 200:
                continue
            S = sel(d, mb)
            cl = Clustered(S["hit"], S["day"])
            preds = {"ml_p": S["ml_p"], "oracle": np.full(mb.sum(), S["hit"].mean())}
            if b in ("B2", "B3"):
                tr = ["B1"] if b == "B2" else ["B1", "B2"]
                preds["onceki"] = np.full(mb.sum(), prior_rate(d, tr, mask=subset_mask & m0))
                mtr = np.isin(d["block"], tr) & subset_mask & m0
                f = fit_iso(np.log1p(d["velocity_score"][mtr]), d["hit"][mtr])
                preds["skor-iso"] = f(np.log1p(S["velocity_score"]))
            preds["_skor"] = np.log1p(S["velocity_score"]) / 20.0  # yalnız AUC için
            res = cl.evaluate(preds, ref="oracle")
            r = res["ml_p"]
            ra = res["_skor"]
            wd = wd_auc({"p": S["ml_p"], "skor": S["velocity_score"]}, S["hit"], S["day"])
            g = lambda k: pm(res[k]["brier"], res[k]["se_brier"], 4) if k in res else "-"
            summary.append([subset_name, BLOCK_LABEL.get(b, "TÜMÜ"), int(mb.sum()), len(np.unique(S["day"])),
                            f3(S["hit"].mean()), f3(r["mean_p"]), g("ml_p"), g("oracle"), g("onceki"), g("skor-iso"),
                            pm(r["ece"], r["se_ece"]), pm(r["auc"], r["se_auc"]), pm(ra["auc"], ra["se_auc"]),
                            pm(wd["p"][0], wd["p"][1]), pm(wd["skor"][0], wd["skor"][1])])
    table(["altküme", "blok", "n", "gün", "gerçek oran", "ort. p", "Brier(p)", "Brier(oracle blok taban)", "Brier(önceki taban)", "Brier(skor-iso)", "ECE(p)", "AUC(p)", "AUC(skor)", "gün-içi AUC(p)", "gün-içi AUC(skor)"], summary)

    for subset_name, subset_mask in (("tüm adaylar", allrows), ("canlı-benzeri", d["live"])):
        for b in list(BLOCKS) + ["ALL"]:
            mb = (allrows if b == "ALL" else d["block"] == b) & m0 & subset_mask
            if mb.sum() < 500:
                continue
            S = sel(d, mb)
            cl = Clustered(S["hit"], S["day"])
            g = np.minimum((S["ml_p"] * 10).astype(int), 9)
            hit_r = cl.ratio_by_group(g, S["hit"], 10)
            mp = cl.ratio_by_group(g, S["ml_p"], 10)
            tg = cl.ratio_by_group(g, S["target_pct"], 10)
            nt = cl.ratio_by_group(g, np.where(S["net_ok"], S["net"], np.nan), 10)
            sc = cl.ratio_by_group(g, np.log1p(S["velocity_score"]), 10)
            rows = []
            for k in range(10):
                if hit_r[k][0] == 0:
                    continue
                rows.append([f"{k / 10:.1f}-{(k + 1) / 10:.1f}", hit_r[k][0], f3(mp[k][1]), pm(hit_r[k][1], hit_r[k][2]),
                             f3(tg[k][1], 2), f3(sc[k][1], 2), pm(nt[k][1], nt[k][2])])
            emit(f"### Güvenilirlik diyagramı — {subset_name} — {BLOCK_LABEL.get(b, 'TÜMÜ')} (n={mb.sum()})")
            table(["p kutusu", "n", "ort. p", "gerçek touched (±SE gün-küme)", "ort. target%", "ort. ln(1+skor)", "ort. net% (±SE)"], rows)

    emit("### A.x ML olasılığı hedefi ve etiketi nasıl etkiliyor (karıştırıcı testi)")
    r2 = d["day"] >= dnum(2026, 10, 8)
    emit("(A.x ve katman-içi AUC yalnız 10-08+ : class_weight=balanced modeli + SL %5 dönemi)")
    mm = d["has_p"] & d["passes"] & r2
    sc = np.log1p(d["velocity_score"])
    qs = np.nanquantile(sc[mm], np.linspace(0, 1, 11))
    band = np.clip(np.searchsorted(qs[1:-1], sc, side="right"), 0, 9)
    diffs, wts = [], []
    for bnd in range(10):
        a = mm & (band == bnd) & (d["ml_p"] >= 0.65)
        b = mm & (band == bnd) & (d["ml_p"] < 0.65)
        if a.sum() > 50 and b.sum() > 50:
            diffs.append(d["target_pct"][a].mean() - d["target_pct"][b].mean())
            wts.append(min(a.sum(), b.sum()))
    emit(f"passes=true, skor-bandı (decile) içinde (p>=0.65) − (p<0.65) ort. target_pct farkı (ağırlıklı): "
         f"{np.average(diffs, weights=wts):+.3f} pp; bant farkları: {[round(x, 2) for x in diffs]}")
    a, b = mm & (d["ml_p"] >= 0.65), mm & (d["ml_p"] < 0.65)
    emit(f"passes=true: p>=0.65 n={a.sum()} ort.target={d['target_pct'][a].mean():.2f} touched={d['hit'][a].mean():.3f} net={np.nanmean(d['net'][a]):+.3f}; "
         f"p<0.65 n={b.sum()} ort.target={d['target_pct'][b].mean():.2f} touched={d['hit'][b].mean():.3f} net={np.nanmean(d['net'][b]):+.3f}")
    emit("")
    emit("p'nin AUC'si, target_pct ve ufuk sabitlenerek (katman içi) — hedef karıştırıcısından arındırılmış ayırt edicilik:")
    rows = []
    for hz in (5, 15):
        for lo, hi in ((0, 2.0), (2.0, 3.0), (3.0, 4.01), (4.01, 99)):
            mk = r2 & d["has_p"] & (d["horizon"] == hz) & (d["target_pct"] >= lo) & (d["target_pct"] < hi)
            if mk.sum() < 2000:
                continue
            S = sel(d, mk)
            cl = Clustered(S["hit"], S["day"], B=200)
            r = cl.evaluate({"p": S["ml_p"]})["p"]
            rows.append([hz, f"[{lo},{hi})", int(mk.sum()), f3(S["hit"].mean()), pm(r["auc"], r["se_auc"])])
    table(["ufuk", "target_pct", "n", "touched oranı", "AUC(p)"], rows)


def section_notifs():
    emit("## A2. Gerçek bildirimler (monitoring_notifications; sonuç dolu ve ml_hit_probability dolu)")
    import psycopg
    with psycopg.connect(DSN) as con:
        con.read_only = True
        cur = con.cursor()
        cur.execute("""SELECT n.created_at, n.ml_hit_probability, n.outcome_status, n.target_pct,
                              v.ml_hit_probability, v.touched_target::int
                       FROM monitoring_notifications n LEFT JOIN velocity_candidates v ON v.candidate_id=n.candidate_id
                       WHERE n.ml_hit_probability IS NOT NULL AND n.outcome_status IS NOT NULL""")
        rows = cur.fetchall()
    if not rows:
        emit("(satır yok)")
        return
    ca = np.array([r[0] for r in rows], float)
    p = np.array([r[1] for r in rows], float)
    st = np.array([r[2] for r in rows], dtype=object)
    tgt = np.array([r[3] if r[3] is not None else np.nan for r in rows], float)
    pc = np.array([r[4] if r[4] is not None else np.nan for r in rows], float)
    day = np.floor((ca + TZ_OFF) / 86400).astype(np.int64)
    y = (st == "HEDEFE_ULTI").astype(float)
    n = len(y)
    emit(f"n={n}; HEDEFE_ULTI={int(y.sum())} ({y.mean():.1%}); STOP={int((st == 'STOP').sum())}; SURE_DOLDU={int((st == 'SURE_DOLDU').sum())}; gün={len(np.unique(day))}")
    cl = Clustered(y, day)
    res = cl.evaluate({"p": p, "taban": np.full(n, y.mean())}, ref="taban")
    r = res["p"]
    emit(f"Brier(p)={pm(r['brier'], r['se_brier'], 4)} vs Brier(oracle taban)={res['taban']['brier']:.4f} (Δ={r['d_brier']:+.4f}±{r['se_d_brier']:.4f}); "
         f"ECE={pm(r['ece'], r['se_ece'])}; AUC={pm(r['auc'], r['se_auc'])}; ort. p={r['mean_p']:.3f}")
    g = np.minimum((p * 10).astype(int), 9)
    hr = cl.ratio_by_group(g, y, 10)
    mp = cl.ratio_by_group(g, p, 10)
    tg = cl.ratio_by_group(g, tgt, 10)
    rr = []
    for k in range(10):
        if hr[k][0]:
            rr.append([f"{k / 10:.1f}-{(k + 1) / 10:.1f}", hr[k][0], f3(mp[k][1]), pm(hr[k][1], hr[k][2]), f3(tg[k][1], 2)])
    table(["p kutusu", "n", "ort. p", "HEDEFE_ULTI oranı (±SE gün-küme)", "ort. target%"], rr)
    era_rows = []
    for nm, mk in (("10-08 öncesi (class_weight yok, p çöküyor)", day < dnum(2026, 10, 8)),
                   ("10-08 ve sonrası (balanced model)", day >= dnum(2026, 10, 8))):
        if mk.sum() < 20:
            continue
        cl2 = Clustered(y[mk], day[mk])
        r2_ = cl2.evaluate({"p": p[mk], "taban": np.full(int(mk.sum()), y[mk].mean())}, ref="taban")
        era_rows.append([nm, int(mk.sum()), f3(float(y[mk].mean())), f3(float(p[mk].mean())),
                         pm(r2_["p"]["brier"], r2_["p"]["se_brier"], 4), f3(r2_["taban"]["brier"], 4),
                         pm(r2_["p"]["ece"], r2_["p"]["se_ece"]), pm(r2_["p"]["auc"], r2_["p"]["se_auc"]),
                         f3(float(np.mean(p[mk] >= 0.9)), 2), f3(float(np.mean(p[mk] < 0.1)), 2)])
    table(["dönem", "n", "HEDEFE_ULTI oranı", "ort. p", "Brier(p)", "Brier(oracle taban)", "ECE", "AUC", "p>=0.9 payı", "p<0.1 payı"], era_rows)
    ok = np.isfinite(pc)
    emit(f"Bildirimdeki p ile aday satırındaki p farklı olan oran: {np.mean(np.abs(p[ok] - pc[ok]) > 1e-3):.1%} (bildirimden sonra güncellenen p)")
    emit("")


def section_b(d):
    emit("## B. Yeniden kalibrasyon (walk-forward; önceki bloklarda fit, sonraki blokta test)")
    rows = []
    rel_rows = []
    allrows = np.ones(len(d["day"]), bool)
    for subset_name, subset_mask in (("tüm adaylar", allrows), ("canlı-benzeri", d["live"])):
        for test, tr in FOLDS:
            mte = (d["block"] == test) & d["has_p"] & subset_mask
            mtr = np.isin(d["block"], tr) & d["has_p"] & subset_mask
            S, T = sel(d, mte), sel(d, mtr)
            iso = fit_iso(T["ml_p"], T["hit"])
            platt = fit_platt(T["ml_p"], T["hit"])
            hz_iso = {h: fit_iso(T["ml_p"][T["horizon"] == h], T["hit"][T["horizon"] == h]) for h in (5, 15)}
            p_hz = np.where(S["horizon"] == 5, hz_iso[5](S["ml_p"]), hz_iso[15](S["ml_p"]))
            base_rate = float(T["hit"].mean())
            cl = Clustered(S["hit"], S["day"])
            preds = {"ham": S["ml_p"], "Platt": platt(S["ml_p"]), "izotonik": iso(S["ml_p"]),
                     "izotonik(ufuk-bazlı)": p_hz, "önceki taban oranı": np.full(len(S["hit"]), base_rate)}
            res = cl.evaluate(preds, ref="ham")
            a, b = platt.params
            for nm in preds:
                r = res[nm]
                rows.append([subset_name, f"{test} (fit {'+'.join(tr)})", int(mte.sum()), nm,
                             pm(r["brier"], r["se_brier"], 4), pm(r["ece"], r["se_ece"]), pm(r["auc"], r["se_auc"]),
                             ("-" if nm == "ham" else f"{r['d_brier']:+.4f}±{r['se_d_brier']:.4f}"),
                             ("-" if nm == "ham" else f"{r['d_auc']:+.4f}±{r['se_d_auc']:.4f}")])
            emit(f"Platt ({subset_name}, fit {'+'.join(tr)}): logit(p_kal) = {a:.3f}·logit(p_ham) + {b:.3f}")
            pi = iso(S["ml_p"])
            g = np.minimum((pi * 10).astype(int), 9)
            hr = cl.ratio_by_group(g, S["hit"], 10)
            mp = cl.ratio_by_group(g, pi, 10)
            for k in range(10):
                if hr[k][0] >= 200:
                    rel_rows.append([subset_name, test, f"{k / 10:.1f}-{(k + 1) / 10:.1f}", hr[k][0], f3(mp[k][1]), pm(hr[k][1], hr[k][2])])
    emit("")
    table(["altküme", "test bloğu", "n", "tahmin", "Brier", "ECE", "AUC", "ΔBrier vs ham", "ΔAUC vs ham"], rows)
    emit("İzotonik çıktısının test bloğundaki güvenilirliği (kutular çıktı-p'ye göre):")
    table(["altküme", "test", "izo-p kutusu", "n", "ort. izo-p", "gerçek touched ±SE"], rel_rows)


def run_models(d, test, tr, label):
    mtr = np.isin(d["block"], tr)
    mte = d["block"] == test
    if label == "ypos":
        mtr = mtr & d["net_ok"]
    Xtr, _ = base_features(sel(d, mtr))
    Xte, _ = base_features(sel(d, mte))
    ytr = d[label][mtr]
    out = {}
    out["LR"] = LRModel().fit(Xtr, ytr).predict(Xte)
    out["HGB"] = hgb_clf().fit(Xtr, ytr).predict_proba(Xte)[:, 1]
    Xtr2 = np.column_stack([Xtr, d["ml_p"][mtr]])
    Xte2 = np.column_stack([Xte, d["ml_p"][mte]])
    out["HGB+ml_p"] = hgb_clf().fit(Xtr2, ytr).predict_proba(Xte2)[:, 1]
    return out, mte


def section_c(d):
    emit("## C. Yedek model (saklanan özelliklerle, walk-forward) — ml_p ile karşılaştırma")
    emit("Özellikler: ATR%, ret3, ln(1+hacim oranı), ln(1+skor), target%, target/ATR, ufuk, saat(İstanbul), passes. "
         "(taker payı / defter dengesi / mod yalnız 10-17'den beri saklı: C.x'te küçük ek deney.) "
         "Test kümesi: p dolu satırlar (ml_p ile aynı satırlar).")
    rows = []
    allrows = np.ones(len(d["day"]), bool)
    for label, lname in (("hit", "touched_target"), ("ypos", "net>0")):
        for test, tr in FOLDS:
            preds_all, mte = run_models(d, test, tr, label)
            for subset_name, subset_mask in (("tüm adaylar", allrows), ("canlı-benzeri", d["live"])):
                keep = d["has_p"][mte] & subset_mask[mte]
                if label == "ypos":
                    keep &= d["net_ok"][mte]
                S = sel(d, mte)
                S = {k: v[keep] for k, v in S.items()}
                y = S[label]
                cl = Clustered(y, S["day"])
                mtr = np.isin(d["block"], tr) & d["has_p"]
                if label == "ypos":
                    mtr = mtr & d["net_ok"]
                prior = float(np.nanmean(d[label][mtr & subset_mask]))
                preds = {"ml_p ham": S["ml_p"], "önceki taban oranı": np.full(len(y), prior)}
                preds["ml_p izotonik"] = fit_iso(d["ml_p"][mtr], d[label][mtr])(S["ml_p"])
                preds["skor izotonik"] = fit_iso(np.log1p(d["velocity_score"][mtr]), d[label][mtr])(np.log1p(S["velocity_score"]))
                for nm, pv in preds_all.items():
                    preds[nm] = pv[keep]
                res = cl.evaluate(preds, ref="ml_p ham")
                wdp = {k: v for k, v in preds.items() if k != "önceki taban oranı"}
                wdp["skor"] = S["velocity_score"]
                wd = wd_auc(wdp, y, S["day"], ref="ml_p ham")
                for nm in preds:
                    r = res[nm]
                    rows.append([lname, subset_name, test, len(y), nm, pm(r["brier"], r["se_brier"], 4), pm(r["ece"], r["se_ece"]),
                                 pm(r["auc"], r["se_auc"]),
                                 ("-" if nm not in wd else pm(wd[nm][0], wd[nm][1]) + ("" if wd[nm][2] is None else " (Δ%+.3f±%.3f)" % (wd[nm][2], wd[nm][3]))),
                                 ("-" if nm == "ml_p ham" else f"{r['d_brier']:+.4f}±{r['se_d_brier']:.4f}"),
                                 ("-" if nm == "ml_p ham" else f"{r['d_auc']:+.4f}±{r['se_d_auc']:.4f}")])
    table(["etiket", "altküme", "test", "n", "tahmin", "Brier", "ECE", "AUC", "gün-içi AUC", "ΔBrier vs ml_p", "ΔAUC vs ml_p"], rows)

    emit("### C.x Ek deney: taker payı + defter dengesi (yalnız 10-17/18, zaman bölmeli 60/40 + 60 dk boşluk, küme=saat)")
    m = np.isfinite(d["taker"]) & np.isfinite(d["book"]) & d["has_p"]
    if m.sum() > 2000:
        S = sel(d, m)
        order = np.argsort(S["created_at"])
        S = {k: v[order] for k, v in S.items()}
        cut = int(len(order) * 0.6)
        tr_ = {k: v[:cut] for k, v in S.items()}
        te_ = {k: v[cut:] for k, v in S.items()}
        keep = te_["created_at"] >= tr_["created_at"].max() + 3600
        te_ = {k: v[keep] for k, v in te_.items()}
        out = []
        for lab in ("hit", "ypos"):
            mtr_ = np.ones(len(tr_["hit"]), bool) if lab == "hit" else tr_["net_ok"]
            mte_ = np.ones(len(te_["hit"]), bool) if lab == "hit" else te_["net_ok"]
            trs = {k: v[mtr_] for k, v in tr_.items()}
            tes = {k: v[mte_] for k, v in te_.items()}
            Xa, _ = base_features(trs, False)
            Xb, _ = base_features(trs, True)
            Ta, _ = base_features(tes, False)
            Tb, _ = base_features(tes, True)
            ytr, yte = trs[lab], tes[lab]
            cl = Clustered(yte, (tes["created_at"] // 3600).astype(np.int64))
            preds = {"ml_p ham": tes["ml_p"],
                     "LR temel": LRModel().fit(Xa, ytr).predict(Ta),
                     "LR + taker/book": LRModel().fit(Xb, ytr).predict(Tb),
                     "HGB temel": hgb_clf().fit(Xa, ytr).predict_proba(Ta)[:, 1],
                     "HGB + taker/book": hgb_clf().fit(Xb, ytr).predict_proba(Tb)[:, 1]}
            res = cl.evaluate(preds, ref="ml_p ham")
            for nm in preds:
                r = res[nm]
                out.append([lab, len(yte), nm, pm(r["brier"], r["se_brier"], 4), pm(r["auc"], r["se_auc"]),
                            ("-" if nm == "ml_p ham" else f"{r['d_auc']:+.4f}±{r['se_d_auc']:.4f}")])
        table(["etiket", "n test", "tahmin", "Brier", "AUC", "ΔAUC vs ml_p"], out)
    else:
        emit("(yeterli satır yok)")


def dedup_mask(d, mask, window_min=60):
    """Aynı sembolde 60 dk içinde zaten alınmış satır varsa atla (tek pozisyon / sembol)."""
    idx = np.where(mask)[0]
    idx = idx[np.argsort(d["created_at"][idx])]
    last = {}
    keep = np.zeros(len(mask), bool)
    for i in idx:
        s = d["symbol"][i]
        t = d["created_at"][i]
        if s in last and t - last[s] < window_min * 60:
            continue
        last[s] = t
        keep[i] = True
    return keep


def section_d(d):
    emit("## D. Beklenen değer (EV) — sıralama / filtre testi")
    emit(f"EV_i = p_i·(target_i − {COST_TP:.3f}) + (1 − p_i)·L_h ;  L_h = eğitim bloklarında E[net | dokunmadı] (ufuk bazlı; stop/süre çıkış maliyeti {COST_NT:.3f} dahil). "
         "Gerçekleşen net = exit_pct − maliyet (TP: 0.33, diğer: 0.525). Modeller önceki bloklarda eğitilir, sonraki blokta test edilir.")
    emit("")
    emit("Başabaş touched oranı = −L/(W − L); W = TP'de ort. net, L = dokunmayanda ort. net (canlı-benzeri):")
    be = []
    for b in BLOCKS:
        m = (d["block"] == b) & d["has_p"] & d["live"] & d["net_ok"]
        W_ = float(np.mean(d["net"][m & (d["hit"] > 0.5)]))
        L_ = float(np.mean(d["net"][m & (d["hit"] < 0.5)]))
        be.append([BLOCK_LABEL[b], int(m.sum()), f3(W_, 2), f3(L_, 2), f3(-L_ / (W_ - L_)), f3(float(d["hit"][m].mean()))])
    table(["blok", "n", "W (TP net%)", "L (dokunmayan net%)", "başabaş touched", "gerçek touched"], be)
    sweeps = {}
    for dd_name in ("tüm satırlar", "tekilleştirilmiş (sembol başına 60 dk)"):
        emit(f"### D — canlı-benzeri (passes, rank<=10) — {dd_name}")
        rows_rank, rows_ev_cal = [], []
        for test, tr in FOLDS:
            mte = (d["block"] == test) & d["has_p"] & d["live"] & d["net_ok"]
            if dd_name.startswith("tekil"):
                mte = dedup_mask(d, mte)
            mtr = np.isin(d["block"], tr) & d["net_ok"]
            Xtr, _ = base_features(sel(d, mtr))
            Xte, _ = base_features(sel(d, mte))
            ytr = d["hit"][mtr]
            p_hgb = hgb_clf().fit(Xtr, ytr).predict_proba(Xte)[:, 1]
            p_lr = LRModel().fit(Xtr, ytr).predict(Xte)
            mtrp = mtr & d["has_p"]
            p_isoml = fit_iso(d["ml_p"][mtrp], d["hit"][mtrp])(d["ml_p"][mte])
            ev_direct = hgb_reg().fit(Xtr, d["net"][mtr]).predict(Xte)
            L = {h: float(np.mean(d["net"][mtr & (d["hit"] < 0.5) & (d["horizon"] == h)])) for h in (5, 15)}
            S = sel(d, mte)
            Lv = np.where(S["horizon"] == 5, L[5], L[15])
            tg = S["target_pct"]

            def ev(p):
                return p * (tg - COST_TP) + (1 - p) * Lv

            scores = {"skor": np.log1p(S["velocity_score"]), "ml_p ham": S["ml_p"],
                      "EV(ml_p ham)": ev(S["ml_p"]), "EV(ml_p izotonik)": ev(p_isoml),
                      "EV(HGB p)": ev(p_hgb), "EV(LR p)": ev(p_lr), "EV(doğrudan HGB net)": ev_direct}
            net, day = S["net"], S["day"]
            n0, m0, s0 = cluster_mean(net, day)
            rows_rank.append([test, "hepsi (filtre yok)", "100%", n0, pm(m0, s0), f3(float(S["hit"].mean())), f"L5={L[5]:+.2f} L15={L[15]:+.2f}"])
            for nm, sc in scores.items():
                for q in (0.5, 0.2, 0.1, 0.05):
                    thr = np.quantile(sc, 1 - q)
                    mk = sc >= thr
                    n_, m_, s_ = cluster_mean(net[mk], day[mk])
                    rows_rank.append([test, nm, f"üst {int(q * 100)}%", n_, pm(m_, s_), f3(float(S["hit"][mk].mean())),
                                      ("" if not nm.startswith("EV(HGB") else f"EV>={thr:+.2f}")])
            for nm in ("EV(HGB p)", "EV(ml_p ham)", "EV(ml_p izotonik)", "EV(doğrudan HGB net)"):
                sc = scores[nm]
                qs = np.unique(np.quantile(sc, np.linspace(0, 1, 6)))
                gi = np.clip(np.searchsorted(qs[1:-1], sc, side="right"), 0, len(qs) - 2)
                for k in range(len(qs) - 1):
                    mk = gi == k
                    if mk.sum() < 100:
                        continue
                    n_, m_, s_ = cluster_mean(net[mk], day[mk])
                    rows_ev_cal.append([test, nm, f"{k + 1}/5", n_, f3(float(sc[mk].mean())), pm(m_, s_)])
            sweeps[(dd_name, test)] = (scores["EV(HGB p)"], scores["EV(doğrudan HGB net)"], net, day)
        table(["test", "sıralama anahtarı", "seçim", "n", "gerçek net% ±SE", "touched oranı", "not"], rows_rank)
        emit("Tahmini EV beşte-birlikleri vs gerçekleşen net (kalibrasyon):")
        table(["test", "EV türü", "dilim", "n", "ort. tahmini EV", "gerçek net% ±SE"], rows_ev_cal)

        emit("EV eşik taraması (gerçekleşen net ≥ 0 olan en düşük eşik):")
        grid = [-1.0, -0.8, -0.6, -0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
        for which, idx in (("EV(HGB p)", 0), ("EV(doğrudan HGB net)", 1)):
            sw = []
            tstar = None
            for test, _ in FOLDS:
                v = sweeps[(dd_name, test)]
                sc, net, day = v[idx], v[2], v[3]
                for t in grid:
                    mk = sc >= t
                    if mk.sum() < 50:
                        continue
                    n_, m_, s_ = cluster_mean(net[mk], day[mk])
                    sw.append([test, f"{t:+.2f}", n_, pm(m_, s_)])
                    if test == "B2" and tstar is None and mk.sum() >= 300 and m_ >= 0:
                        tstar = t
            emit(f"{which}:")
            table(["test", "eşik (tahmini EV)", "n", "gerçek net% ±SE"], sw)
            if tstar is None:
                emit(f"{which}: B2'de n>=300 ve gerçek net>=0 sağlayan EV eşiği YOK.")
            else:
                v = sweeps[(dd_name, "B3")]
                mk = v[idx] >= tstar
                n_, m_, s_ = cluster_mean(v[2][mk], v[3][mk])
                emit(f"{which}: B2'de seçilen eşik t*={tstar:+.2f} -> B3'te n={n_}, gerçek net={pm(m_, s_)}")
            emit("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--skip", default="", help="virgüllü: a,a2,b,c,d")
    ap.add_argument("--mode", default="std", choices=["std", "sl5"],
                    help="std: kullanıcı blokları; sl5: yalnız SL %5 rejimi (10-08+), 3 ardışık blok")
    args = ap.parse_args()
    if args.mode == "sl5":
        BLOCKS.clear()
        BLOCKS.update({"B1": (dnum(2026, 10, 8), dnum(2026, 10, 11)), "B2": (dnum(2026, 10, 12), dnum(2026, 10, 14)),
                       "B3": (dnum(2026, 10, 15), dnum(2026, 10, 31))})
        BLOCK_LABEL.update({"B1": "B1 10-08..10-11", "B2": "B2 10-12..10-14", "B3": "B3 10-15..10-18"})
    skip = set(args.skip.split(",")) if args.skip else set()
    os.makedirs(OUT_DIR, exist_ok=True)
    d = prep(fetch(args.refetch))
    emit("# prob_audit tablolar (otomatik üretim) — mod: %s" % args.mode)
    emit(f"Üretim zamanı: {dt.datetime.now():%Y-%m-%d %H:%M}; maliyet: TP {COST_TP:.3f}%, diğer {COST_NT:.3f}%.")
    emit("")
    section_cover(d)
    for key, fn in (("a", lambda: section_a(d)), ("a2", section_notifs), ("b", lambda: section_b(d)),
                    ("c", lambda: section_c(d)), ("d", lambda: section_d(d))):
        if key not in skip:
            t0 = time.time()
            fn()
            print(f"[{key}] {time.time() - t0:.0f}s", flush=True)
    fn = "tables.md" if args.mode == "std" else "tables_sl5.md"
    with open(os.path.join(OUT_DIR, fn), "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT_LINES))
    print("yazıldı:", os.path.join(OUT_DIR, fn))


if __name__ == "__main__":
    main()
