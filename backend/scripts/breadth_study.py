"""Kesitsel (genişlik / göreli güç) ve ZAMAN boyutları çalışması (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye yazmaz).

Soru: Sembol-başı göstergelerin eklemediği bilgiyi (a) piyasa genişliği, (b) göreli güç / SMT / USDTTRY, (c) saat-gün-seans taşıyor mu? Olay öngörüsü (a),
Hız Avcısı (HA) filtresi / rejim kapısı (b), koşulsuz zamanlama (c), net-pozitif kural (d).

Veri: `pattern90_study.py` önbelleği (5m doldurulmuş ızgara `grid/F5_*.npy`, 1m ham `d1/*.npy`, olaylar, eşleşmiş taban `snap.npz`), HA nüfusu
`work/indfilter/{events_ha.pkl, prep_ha.npz}`, mevcut sembol özellikleri `indearly` anlık görüntüleri.

Aşamalar (`--stages`, virgüllü):
  panels   F5 → ortak (S,T) panel .npy (C,H,L,QV,TBQ)                      → <bdir>/panels
  feats    genişlik / göreli güç / zaman özellikleri (saf: app/rescan/breadth.py) → <bdir>/feat
  pops     olay+taban+havuz, HA ve rastgele giriş nüfuslarının özellik matrisleri (+ rastgele girişin 1 dk simülasyonu) → <bdir>/pops
  a        olay öngörüsü (grup-içi AUC, BH q, blok tutarlılığı, havuza karşı, HGB blok-dışı)       → <out>/a.pkl
  b        HA filtresi / rejim kapısı (kısmi Spearman, tersil/saat tabloları, kalkan karşılaştırması) → <out>/b.pkl
  c        koşulsuz zamanlama (rastgele giriş neti: rejim / saat / seans)                         → <out>/c.pkl
  d        kural araması + ön-tanımlı kurallar (2 blokta seç, 3.de test, döndür)                   → <out>/d.pkl
  report   Markdown → <out>/report.md

Kullanım (backend/):
  DATABASE_URL gerekmez (yalnız önbellek). python scripts/breadth_study.py --cache-dir <p90cache> --bdir <scratch>/breadth --out-dir work/breadth
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

from app.rescan import breadth as B  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402

BAR = 300_000
MIN_QUOTE = 5_000_000.0
WARM = 300
STABLE_STD = 0.0004                       # 1 sa getiri medyan |r| altında → "stabil / pegli" çift, genişlik evreninden çıkar
TIME_FEATURES = ["t_hour_f", "t_dow", "t_kz", "t_kz_asya", "t_kz_londra", "t_kz_ny", "t_weekend"]
EXTRA_MARKET = ["sh_dist", "sh_open"]
TEST_EXCLUDE = {"m_nvalid"}               # evren büyüklüğü: özellik analizine girmez


def sc_paths(args):
    b = Path(args.bdir)
    return b, b / "panels", b / "feat", b / "pops"


# ------------------------------------------------------------------------------------------------ 1. paneller
def stage_panels(args) -> None:
    cache = Path(args.cache_dir)
    b, pd_, _, _ = sc_paths(args)
    pd_.mkdir(parents=True, exist_ok=True)
    gdir = cache / "grid"
    syms = sorted(p.name[3:-4] for p in gdir.glob("F5_*.npy"))
    snap_syms = list(np.load(cache / "snap.npz")["syms"])
    assert syms == snap_syms, "sembol sırası snap.npz ile uyuşmuyor"
    first = np.array([np.load(gdir / f"OT_{s}.npy", mmap_mode="r")[0] for s in syms], dtype=np.int64)
    last = np.array([np.load(gdir / f"OT_{s}.npy", mmap_mode="r")[-1] for s in syms], dtype=np.int64)
    t0, t1 = int(first.min()), int(last.max())
    T = (t1 - t0) // BAR + 1
    assert ((first - t0) % BAR == 0).all()
    S = len(syms)
    names = ("C", "H", "L", "QV", "TBQ")
    cols = {"C": 4, "H": 2, "L": 3, "QV": 6, "TBQ": 8}
    P = {n: np.full((S, T), np.nan, dtype=np.float32) for n in names}
    nan_tk = 0
    for i, s in enumerate(syms):
        f = np.load(gdir / f"F5_{s}.npy", mmap_mode="r")
        k = ((np.asarray(f[:, 0]).astype(np.int64) - t0) // BAR)
        for n in names:
            P[n][i, k] = np.asarray(f[:, cols[n]], dtype=np.float32)
        nan_tk += int(np.isnan(np.asarray(f[:, 8])).sum())
    for n in names:
        np.save(pd_ / f"{n}.npy", P[n])
    (pd_ / "meta.json").write_text(json.dumps({"syms": syms, "t0": t0, "T": T}), encoding="utf-8")
    print(f"[panels] S={S} T={T} t0={t0} taker NaN bar={nan_tk}", flush=True)


class Panels:
    def __init__(self, bdir):
        pd_ = Path(bdir) / "panels"
        m = json.loads((pd_ / "meta.json").read_text(encoding="utf-8"))
        self.syms, self.t0, self.T = m["syms"], int(m["t0"]), int(m["T"])
        self.sid = {s: i for i, s in enumerate(self.syms)}
        self.dir = pd_

    def load(self, name, dtype=np.float64):
        return np.load(self.dir / f"{name}.npy").astype(dtype)

    def t_dec(self, k):
        return self.t0 + (np.asarray(k, dtype=np.int64) + 1) * BAR

    def k_of_tick(self, t_ms):
        """Karar anı t (ms): kapanışı ≤ t olan son 5 dk barın indeksi."""
        return (np.asarray(t_ms, dtype=np.int64) - self.t0) // BAR - 1


# ------------------------------------------------------------------------------------------------ 2. özellikler
def stage_feats(args) -> None:
    b, _, fd, _ = sc_paths(args)
    fd.mkdir(parents=True, exist_ok=True)
    pan = Panels(args.bdir)
    t0 = time.time()
    C, H, L = pan.load("C"), pan.load("H"), pan.load("L")
    QV, TBQ = pan.load("QV"), pan.load("TBQ")
    S, T = C.shape
    # stabil / pegli çiftleri evrenden çıkar
    c1h = C[:, 12::12] / C[:, :-12:12] - 1.0
    med = np.nanmedian(np.abs(c1h), axis=1)
    stable = np.isfinite(med) & (med < STABLE_STD)
    stable_names = [pan.syms[i] for i in np.flatnonzero(stable)]
    V = B.valid_universe(QV, MIN_QUOTE)
    V[stable] = False
    print(f"[feats] stabil çift (evrenden çıkarıldı): {stable_names}; geçerli sayısı medyan {int(np.median(V.sum(0)))} ({time.time() - t0:.0f} sn)", flush=True)
    btc, usd = pan.sid["BTCTRY"], pan.sid["USDTTRY"]
    mk = B.market_features(C, H, L, QV, TBQ, V)
    mk.update(B.btc_usd_features(C[btc], C[usd]))
    # BTC 1 sa EMA200 kalkanı (canlı tanım)
    raw = json.load(open(_BACKEND_DIR / "work" / "btc_1h_120d.json", encoding="utf-8"))
    hot = np.array([r[0] for r in raw], dtype=np.int64)
    hcl = np.array([float(r[4]) for r in raw])
    prior = hcl[hot + 3_600_000 <= pan.t0]
    assert len(prior) >= 209, len(prior)
    ema200 = B.btc_shield_ema(C[btc], prior)
    mk["sh_dist"] = ((C[btc] / ema200 - 1.0) * 100.0).astype(np.float32)
    mk["sh_open"] = np.where(np.isfinite(ema200), (C[btc] < ema200).astype(np.float32), np.nan).astype(np.float32)
    names = list(B.MARKET_FEATURES) + EXTRA_MARKET
    M = np.vstack([mk[n].astype(np.float32) for n in names])
    np.save(fd / "market.npy", M)
    np.save(fd / "V.npy", V)
    lvl = B.ew_index(C, V)
    np.save(fd / "mkt_level.npy", lvl.astype(np.float32))
    mret = {"15": mk["m_ret_15"].astype(float), "60": mk["m_ret_60"].astype(float), "240": mk["m_ret_240"].astype(float)}
    json.dump({"market": names, "symbol": list(B.SYMBOL_FEATURES), "stable": stable_names}, open(fd / "names.json", "w"))
    print(f"[feats] piyasa özellikleri {M.shape} ({time.time() - t0:.0f} sn)", flush=True)
    del mk
    n_done = 0
    usd60 = np.asarray(M[names.index("usd_ret_60")], dtype=float)
    for nm, a in B.symbol_feature_iter(C, H, L, QV, V, btc, lvl, mret, usd60):
        np.save(fd / f"s_{nm}.npy", a.astype(np.float32))
        n_done += 1
        print(f"[feats] {nm} ({time.time() - t0:.0f} sn)", flush=True)
    assert n_done == len(B.SYMBOL_FEATURES), (n_done, len(B.SYMBOL_FEATURES))
    print(f"[feats] bitti ({time.time() - t0:.0f} sn)", flush=True)


class FeatStore:
    """Hazır özellikleri (sid, k) çiftlerinden toplu okur. k = karar barı indeksi (kapanış = t0 + (k+1)·BAR)."""

    def __init__(self, bdir):
        self.pan = Panels(bdir)
        fd = Path(bdir) / "feat"
        nm = json.load(open(fd / "names.json", encoding="utf-8"))
        self.mnames, self.snames = nm["market"], nm["symbol"]
        self.M = np.load(fd / "market.npy")
        self.V = np.load(fd / "V.npy")
        self.fd = fd
        self.names = [n for n in self.mnames if n not in TEST_EXCLUDE] + self.snames + TIME_FEATURES
        self._cache: dict[str, np.ndarray] = {}

    def valid_at(self, sid, k) -> np.ndarray:
        sid, k = np.asarray(sid), np.asarray(k)
        ok = (k >= 0) & (k < self.pan.T)
        out = np.zeros(len(k), dtype=bool)
        out[ok] = self.V[sid[ok], k[ok]]
        return out

    def time_feats(self, k) -> dict[str, np.ndarray]:
        c = B.tr_clock(self.pan.t_dec(k))
        return {"t_hour_f": c["hour_f"], "t_dow": c["dow"].astype(float), "t_kz": c["kz"].astype(float), "t_kz_asya": (c["kz"] == 1).astype(float),
                "t_kz_londra": (c["kz"] == 2).astype(float), "t_kz_ny": (c["kz"] == 3).astype(float), "t_weekend": (c["dow"] >= 5).astype(float)}

    def gather(self, sid, k, names: list[str] | None = None) -> np.ndarray:
        names = self.names if names is None else names
        sid, k = np.asarray(sid), np.asarray(k, dtype=np.int64)
        n = len(k)
        ok = (k >= 0) & (k < self.pan.T)
        kc = np.clip(k, 0, self.pan.T - 1)
        out = np.full((n, len(names)), np.nan, dtype=np.float32)
        tf = None
        for j, nm in enumerate(names):
            if nm in self.mnames:
                v = self.M[self.mnames.index(nm)][kc]
            elif nm in self.snames:
                if nm not in self._cache:
                    self._cache = {nm: np.load(self.fd / f"s_{nm}.npy")}      # tek panel bellekte (32 MB)
                v = self._cache[nm][sid, kc]
            else:
                if tf is None:
                    tf = self.time_feats(kc)
                v = tf[nm]
            out[:, j] = np.where(ok, v, np.nan)
        return out

    def gather_by_panel(self, sid, k, names=None):
        """Sembol panelleri sırayla (önbellek taşmasını önlemek için aynı panelde birden çok çağrı yapılmaz): gather ile eşdeğer."""
        return self.gather(sid, k, names)


# ------------------------------------------------------------------------------------------------ 3. nüfuslar
def default_fx_dir(args) -> Path:
    return Path(args.fx_dir) if args.fx_dir else Path(args.bdir).parent / "indearly"


def stage_pops(args) -> None:
    """(i) olay + eşleşmiş taban + havuz, (ii) HA satırları, (iii) rastgele giriş (1 dk simülasyon) için özellik matrisleri."""
    b, _, _, pdir = sc_paths(args)
    pdir.mkdir(parents=True, exist_ok=True)
    fs = FeatStore(args.bdir)
    pan = fs.pan
    names = fs.names
    t0 = time.time()
    # ---- (i) olay / taban / havuz
    if "ev" not in args.skip:
        sd = default_fx_dir(args) / "snap"
        m = np.load(sd / "meta.npz", allow_pickle=False)
        z = np.load(Path(args.cache_dir) / "snap.npz")
        assert list(z["syms"]) == pan.syms
        ev_sid, ev_t0, b_sid, b_t, b_g = m["ev_sid"].astype(int), m["ev_t0"].astype(np.int64), m["b_sid"].astype(int), m["b_t"].astype(np.int64), m["b_g"]
        k0 = pan.k_of_tick(ev_t0)
        kb = pan.k_of_tick(b_t)
        out = {"ev_sid": ev_sid, "ev_t0": ev_t0, "b_sid": b_sid, "b_t": b_t, "b_g": b_g, "ev_gain": m["ev_k"]}
        for o in (0, 2):
            out[f"XE_{o}"] = fs.gather(ev_sid, k0 - o)
            out[f"XB_{o}"] = fs.gather(b_sid, kb - o)
        pm = z["pm"]
        out["P_sid"], out["P_t"] = pm[:, 0].astype(int), pm[:, 1].astype(np.int64)
        out["XP"] = fs.gather(out["P_sid"], pan.k_of_tick(out["P_t"]))
        np.savez(pdir / "ev.npz", names=np.array(names), **out)
        print(f"[pops] olay {len(ev_sid)} taban {len(b_sid)} havuz {len(out['P_sid'])} ({time.time() - t0:.0f} sn)", flush=True)
    # ---- (ii) HA
    if "ha" not in args.skip:
        P = K.Pop("ha")
        sid = np.array([pan.sid[s] for s in P.P["sym"]])
        tt = P.P["t"].astype(np.int64)
        k = pan.k_of_tick(tt)
        assert ((tt - pan.t0) % BAR == 0).mean() > 0.99
        X = fs.gather(sid, k)
        X1 = fs.gather(sid, k - 1)                      # dayanıklılık: bir bar GECİKMELİ özellikler (tick anında kapanan bar henüz yoksa)
        np.savez(pdir / "ha.npz", names=np.array(names), X=X, X1=X1, sid=sid, k=k, t=tt)
        print(f"[pops] HA satır {len(sid)} ({time.time() - t0:.0f} sn)", flush=True)
    # ---- (iii) rastgele giriş
    if "rnd" not in args.skip:
        rnd_population(args, fs, pdir)
        print(f"[pops] rastgele giriş bitti ({time.time() - t0:.0f} sn)", flush=True)


def rnd_population(args, fs: FeatStore, pdir: Path) -> None:
    """Her blokta geçerli (sembol, 5 dk karar barı) çiftlerinden tekdüze rastgele örnek; giriş = karar anı + 60 sn gecikme, TP 1,5 / SL 3 / T60,
    %0,15 kayma, bacak başı %0,1125 ücret (exit_sim). Özellikler karar barının kapanışında bilinen değerlerdir."""
    pan = fs.pan
    rng = np.random.default_rng(args.seed + 101)
    cache = Path(args.cache_dir)
    pieces = []
    for b, (lo, hi) in enumerate(K.ha_blocks()):
        ka = max(WARM, int(np.ceil((lo - pan.t0) / BAR)))
        kz = min(pan.T - 140, int((hi - pan.t0) // BAR) - 1)
        Vb = fs.V[:, ka:kz + 1]
        ss, kk = np.nonzero(Vb)
        pick = rng.choice(len(ss), size=min(args.rnd_per_block, len(ss)), replace=False)
        pieces.append((ss[pick], kk[pick] + ka, np.full(len(pick), b, dtype=np.int8)))
    sid = np.concatenate([p[0] for p in pieces])
    k = np.concatenate([p[1] for p in pieces]).astype(np.int64)
    blk = np.concatenate([p[2] for p in pieces])
    n = len(sid)
    res = {nm: np.full(n, np.nan) for nm in ("net", "net_b", "net_c", "mfe", "mae", "ret60", "atr")}
    reason = np.full(n, -1, dtype=np.int8)
    ok_all = np.zeros(n, dtype=bool)
    spec = X.ExitSpec("fixed", "fixed", sl=3.0, time_min=60, tp=1.5)                      # A (birincil)
    spec_b = X.ExitSpec("fixed", "fixed", sl=1.5, time_min=30, tp=1.0)                    # B: sıkı / kısa
    spec_c = X.ExitSpec("fixed", "fixed", sl=3.0, time_min=120, tp=3.0)                   # C: geniş / uzun
    t_ms = pan.t_dec(k)
    for si in np.unique(sid):
        s = pan.syms[si]
        p1 = cache / "d1" / f"{s}.npy"
        if not p1.exists():
            continue
        rows = np.flatnonzero(sid == si)
        a1 = np.load(p1)
        ot1 = a1[:, 0].astype(np.int64)
        idx, ok = X.entry_index(ot1, t_ms[rows], K.DELAY_S)
        O, H, L, C, ref, cov = X.gather_windows(ot1, a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4], idx, 120)
        ok &= cov
        if not ok.any():
            continue
        r = X.simulate(O[ok], H[ok], L[ok], C[ok], spec, slip_pct=K.SLIP)
        rr = rows[ok]
        res["net"][rr] = r["net"]
        res["net_b"][rr] = X.simulate(O[ok], H[ok], L[ok], C[ok], spec_b, slip_pct=K.SLIP)["net"]
        res["net_c"][rr] = X.simulate(O[ok], H[ok], L[ok], C[ok], spec_c, slip_pct=K.SLIP)["net"]
        res["mfe"][rr] = (H[ok][:, :60].max(axis=1).astype(float) - 1.0) * 100.0
        res["mae"][rr] = (L[ok][:, :60].min(axis=1).astype(float) - 1.0) * 100.0
        res["ret60"][rr] = (C[ok][:, 59].astype(float) - 1.0) * 100.0
        reason[rr] = r["reason"]
        ok_all[rr] = True
        f5 = np.load(cache / "grid" / f"F5_{s}.npy", mmap_mode="r")
        res["atr"][rr] = X.atr_pct_at(np.asarray(f5[:, 0]).astype(np.int64), np.asarray(f5[:, 2]), np.asarray(f5[:, 3]), np.asarray(f5[:, 4]), t_ms[rr])
    Xf = fs.gather(sid, k)
    keep = ok_all & np.isfinite(res["atr"])
    np.savez(pdir / "rnd.npz", names=np.array(fs.names), X=Xf[keep], sid=sid[keep], k=k[keep], t=t_ms[keep], block=blk[keep],
             day=K.day_idx(t_ms[keep]).astype(np.int32), reason=reason[keep], **{nm: v[keep] for nm, v in res.items()})
    print(f"[pops] rastgele: örnek {n}, geçerli {int(keep.sum())}; ort. net {np.nanmean(res['net'][keep]):.3f}", flush=True)


# ------------------------------------------------------------------------------------------------ 4. (a) olay öngörüsü
def bh_q(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg q (NaN p korunur)."""
    p = np.asarray(p, dtype=float)
    q = np.full(len(p), np.nan)
    ok = np.flatnonzero(np.isfinite(p))
    if len(ok) == 0:
        return q
    o = ok[np.argsort(p[ok])]
    m = len(o)
    r = p[o] * m / (np.arange(m) + 1.0)
    r = np.minimum.accumulate(r[::-1])[::-1]
    q[o] = np.minimum(r, 1.0)
    return q


def cluster_t(d: np.ndarray, cl: np.ndarray) -> tuple[float, float, float, int]:
    """Ortalama d, gün-kümeli SE, t (ortalama/SE) ve küme sayısı."""
    m = np.isfinite(d)
    d, cl = d[m], cl[m]
    if len(d) < 20:
        return float("nan"), float("nan"), float("nan"), 0
    mu = d.mean()
    _, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=d - mu)
    se = float(np.sqrt((sums ** 2).sum()) / len(d))
    return float(mu), se, float(mu / se) if se > 0 else float("nan"), int(inv.max() + 1)


def group_u(XE: np.ndarray, XB: np.ndarray, b_g: np.ndarray, min_b: int = 3) -> np.ndarray:
    """(G, F): grup-içi olay > taban payı u_g (eşitlik yarım); grupta min_b'den az geçerli taban varsa NaN."""
    G, F = XE.shape
    Ev = XE[b_g]
    ok = np.isfinite(Ev) & np.isfinite(XB)
    sc = np.where(ok, (Ev > XB).astype(np.float32) + 0.5 * (Ev == XB), 0.0)
    U = np.full((G, F), np.nan)
    for j in range(F):
        sm = np.bincount(b_g, weights=sc[:, j], minlength=G)
        ct = np.bincount(b_g, weights=ok[:, j].astype(float), minlength=G)
        U[:, j] = np.where(ct >= min_b, sm / np.maximum(ct, 1), np.nan)
    return U


def _group_auc(p: np.ndarray, y: np.ndarray, g: np.ndarray) -> float:
    """Grup-içi AUC (indearly_study ile aynı tanım): olay skoru, aynı gruptaki tabanlardan büyük olma payı."""
    ev = np.flatnonzero(y == 1)
    gi = g[ev]
    order = np.argsort(g[y == 0], kind="stable")
    pb = p[y == 0][order]
    gb = g[y == 0][order]
    st = np.searchsorted(gb, gi, side="left")
    en = np.searchsorted(gb, gi, side="right")
    vals = []
    for e, a_, b_ in zip(ev, st, en):
        if b_ - a_ >= 3:
            seg = pb[a_:b_]
            vals.append(((seg < p[e]).sum() + 0.5 * (seg == p[e]).sum()) / (b_ - a_))
    return float(np.mean(vals)) if vals else float("nan")


def _hgb():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                          class_weight="balanced", random_state=0)


def stage_a(args) -> None:
    from scipy.stats import t as tdist
    from sklearn.metrics import roc_auc_score
    from threadpoolctl import threadpool_limits
    b, _, _, pdir = sc_paths(args)
    z = np.load(pdir / "ev.npz")
    names = list(z["names"])
    F = len(names)
    ev_t0, b_g = z["ev_t0"], z["b_g"]
    ev_blk = block_idx(ev_t0)
    ev_day = K.day_idx(ev_t0)
    G = len(ev_t0)
    Pblk = block_idx(z["P_t"])
    XP = z["XP"]
    res: dict = {"names": names, "n_ev": G, "ev_blk_n": [int((ev_blk == i).sum()) for i in range(3)]}
    t0 = time.time()
    for o in (0, 2):
        XE, XB = z[f"XE_{o}"], z[f"XB_{o}"]
        U = group_u(XE, XB, b_g)
        rows = []
        for j, nm in enumerate(names):
            u = U[:, j] - 0.5
            mu, se, t, ng = cluster_t(u, ev_day)
            p = float(2 * tdist.sf(abs(t), df=max(ng - 1, 1))) if np.isfinite(t) else float("nan")
            blk = []
            pool_auc = []
            for i in range(3):
                mi, mp = ev_blk == i, Pblk == i
                blk.append(cluster_t(u[mi], ev_day[mi])[0] + 0.5)
                pool_auc.append(K.auc_score(np.r_[XE[mi, j], XP[mp, j]], np.r_[np.ones(mi.sum()), np.zeros(mp.sum())]))
            rows.append({"name": nm, "auc": mu + 0.5, "se": se, "t": t, "p": p, "blocks": blk, "pool_auc": pool_auc, "n_valid": int(np.isfinite(u).sum())})
        q = bh_q(np.array([r["p"] for r in rows]))
        for r, qq in zip(rows, q):
            r["q"] = float(qq)
            d = np.array(r["blocks"]) - 0.5
            r["cons"] = bool(np.all(np.isfinite(d)) and (np.all(d > 0) or np.all(d < 0)))
            dp = np.array(r["pool_auc"]) - 0.5
            r["pool_cons"] = bool(np.all(np.isfinite(dp)) and (np.all(dp > 0) or np.all(dp < 0)))
        res[f"rows_{o}"] = rows
        print(f"[a] off={o}: BH q<0,05 {int(np.nansum(q < 0.05))}/{F}; blok-tutarlı & q<0,05 {sum(1 for r in rows if r['q'] < 0.05 and r['cons'])} ({time.time() - t0:.0f} sn)", flush=True)
    # ---- olay oranı artışı (lift): tersil kenarları DİĞER bloklardaki havuzdan
    lift = {}
    for j, nm in enumerate(names):
        per = []
        for i in range(3):
            sel = (Pblk != i) & (Pblk >= 0)
            v = XP[sel, j]
            v = v[np.isfinite(v)]
            if len(v) < 100 or np.ptp(v) == 0:
                per.append((np.nan, np.nan, np.nan))
                continue
            e1, e2 = np.quantile(v, [1 / 3, 2 / 3])
            ev_v = z["XE_0"][ev_blk == i, j]
            pv = XP[Pblk == i, j]
            ev_v, pv = ev_v[np.isfinite(ev_v)], pv[np.isfinite(pv)]

            def share(x, lo, hi):
                return float(((x > lo) & (x <= hi)).mean()) if len(x) else np.nan
            per.append(tuple(share(ev_v, a_, b_) / max(share(pv, a_, b_), 1e-9) for a_, b_ in ((-np.inf, e1), (e1, e2), (e2, np.inf))))
        lift[nm] = per
    res["lift"] = lift
    # ---- çok değişkenli (HGB, blok-dışı): eşleşmiş taban
    fx = default_fx_dir(args) / "snap"
    sets_idx = {
        "piyasa genişliği": [i for i, n in enumerate(names) if n.startswith(("b_", "m_ret", "btc_ret", "usd_ret", "sh_"))],
        "göreli güç/SMT/beta": [i for i, n in enumerate(names) if n.startswith(("rs_", "rk_", "beta_", "corr_", "smt_"))],
        "zaman/seans/gün-içi": [i for i, n in enumerate(names) if n.startswith(("t_", "orb_", "pd_", "rvol"))],
        "hepsi": list(range(F)),
    }
    rng = np.random.default_rng(args.seed)
    multi = {}
    with threadpool_limits(limits=2):
        for o in (0, 2):
            GE, GB = np.load(fx / f"GE_{o}.npy"), np.load(fx / f"GB_{o}.npy")
            XE, XB = z[f"XE_{o}"], z[f"XB_{o}"]
            keep = np.zeros(len(b_g), bool)
            order = rng.permutation(len(b_g))
            cnt = np.zeros(G, int)
            for i in order:
                if cnt[b_g[i]] < 12:
                    keep[i] = True
                    cnt[b_g[i]] += 1
            bi = np.flatnonzero(keep)
            y = np.r_[np.ones(G), np.zeros(len(bi))].astype(int)
            grp = np.r_[np.arange(G), b_g[bi]]
            blk = np.r_[ev_blk, ev_blk[b_g[bi]]]
            base = np.vstack([GE, GB[bi]])
            newall = np.vstack([XE, XB[bi]])
            sets = {"mevcut 154": base}
            for nm, ix in sets_idx.items():
                sets["mevcut + " + nm] = np.hstack([base, newall[:, ix]])
            sets["yalnız yeni"] = newall
            out_o = {}
            for nm, Xm in sets.items():
                r = []
                for k in range(3):
                    tr_, te_ = (blk != k) & (blk >= 0), blk == k
                    clf = _hgb()
                    clf.fit(Xm[tr_], y[tr_])
                    pr = clf.predict_proba(Xm[te_])[:, 1]
                    r.append({"auc": float(roc_auc_score(y[te_], pr)), "auc_group": _group_auc(pr, y[te_], grp[te_])})
                out_o[nm] = r
                print(f"[a-multi] off={o} {nm}: AUC " + ", ".join(f"{x['auc']:.3f}" for x in r) + " | grup-içi " + ", ".join(f"{x['auc_group']:.3f}" for x in r)
                      + f" ({time.time() - t0:.0f} sn)", flush=True)
            multi[o] = out_o
        res["multi"] = multi
        # ---- eşleşmemiş HGB: olay ↔ havuz (tüm geçerli anlar)
        XPex = np.load(Path(args.cache_dir) / "snap.npz")["Xp"]
        un = {}
        Pidx = np.flatnonzero(Pblk >= 0)
        sub = rng.choice(Pidx, size=min(60000, len(Pidx)), replace=False)
        for o in (0, 2):
            GE = np.load(fx / f"GE_{o}.npy")
            XE = z[f"XE_{o}"]
            y = np.r_[np.ones(G), np.zeros(len(sub))].astype(int)
            blk = np.r_[ev_blk, Pblk[sub]]
            ex = np.vstack([GE, XPex[sub]])
            nw = np.vstack([XE, XP[sub]])
            sets = {"mevcut 154": ex, "mevcut + yeni": np.hstack([ex, nw]), "yalnız yeni": nw}
            out_o = {}
            for nm, Xm in sets.items():
                r = []
                for k in range(3):
                    tr_, te_ = (blk != k) & (blk >= 0), blk == k
                    clf = _hgb()
                    clf.fit(Xm[tr_], y[tr_])
                    r.append(float(roc_auc_score(y[te_], clf.predict_proba(Xm[te_])[:, 1])))
                out_o[nm] = r
                print(f"[a-unmatched] off={o} {nm}: AUC " + ", ".join(f"{x:.3f}" for x in r) + f" ({time.time() - t0:.0f} sn)", flush=True)
            un[o] = out_o
        res["unmatched_multi"] = un
    pickle.dump(res, open(Path(args.out_dir) / "a.pkl", "wb"))


# ------------------------------------------------------------------------------------------------ 5. ortak: kovalar, hücreler, tarama
HEADLINE = ["b_pct_ema20_5m", "b_pct_ema50_5m", "b_pct_ema20_1h", "b_pct_ema50_1h", "b_adr_15", "b_adr_60", "b_adslope_48", "b_mcc_5m", "b_mcc_1h",
            "b_nhl_24h", "b_thrust", "b_tk55", "b_disp_15", "b_disp_60", "m_ret_60", "m_ret_240", "btc_ret_60", "usd_ret_60", "usd_ret_240", "usd_ret_1440",
            "sh_dist", "sh_open", "rs_btc_60", "rs_mkt_60", "rs_btc_240", "rk_15", "rk_60", "rk_240", "beta_btc_24h", "corr_btc_24h", "smt_low_btc",
            "smt_high_btc", "smt_low_mkt", "smt_high_mkt", "orb_tr_dist", "orb_utc_dist", "pd_dist_pdh", "pd_dist_pdl", "pd_sweep_pdl", "pd_sweep_pdh", "rvol_tod"]


def bucket_codes(x: np.ndarray, blk: np.ndarray, pool_x: np.ndarray, pool_blk: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """x'i kovalara ayırır. Havuzda ≤ 5 farklı değer varsa kategorik (değer = koda sırayla); aksi halde TERSİL — kenarlar, değerlendirilen bloğun DIŞINDAki
    bloklardaki havuz değerlerinden (blok i için havuz[blk != i]). Dönüş (kod ∈ {0,1,2…}, −1 = NaN), etiketler."""
    x = np.asarray(x, dtype=float)
    pv = pool_x[np.isfinite(pool_x)]
    codes = np.full(len(x), -1, dtype=int)
    uniq = np.unique(pv)
    if len(uniq) <= 5:
        for c, u in enumerate(uniq):
            codes[np.isfinite(x) & (x == u)] = c
        return codes, [("%g" % u) for u in uniq]
    for i in range(3):
        sel = (pool_blk != i) & (pool_blk >= 0) & np.isfinite(pool_x)
        e1, e2 = np.quantile(pool_x[sel], [1 / 3, 2 / 3])
        m = (blk == i) & np.isfinite(x)
        codes[m] = (x[m] > e1).astype(int) + (x[m] > e2).astype(int)
    return codes, ["T1 (düşük)", "T2", "T3 (yüksek)"]


def cell_stats(ys: dict[str, np.ndarray], mask: np.ndarray, day: np.ndarray) -> dict:
    out = {"n": int(mask.sum())}
    for k, y in ys.items():
        v = y[mask]
        v_ok = np.isfinite(v)
        if v_ok.sum() < 2:
            out[k] = (float("nan"), float("nan"))
            continue
        out[k] = (float(v[v_ok].mean()), float(X.cluster_se(v[v_ok], day[mask][v_ok])))
    return out


def bucket_table(ys: dict[str, np.ndarray], codes: np.ndarray, labels: list[str], blk: np.ndarray, day: np.ndarray) -> dict:
    """{label: {'all': cell, 'b': [cell_b1, cell_b2, cell_b3]}}."""
    res = {}
    for c, lab in enumerate(labels):
        m = codes == c
        res[lab] = {"all": cell_stats(ys, m, day), "b": [cell_stats(ys, m & (blk == i), day) for i in range(3)]}
    return res


def scan_features(Xm: np.ndarray, names: list[str], ys: dict[str, np.ndarray], atr: np.ndarray, day: np.ndarray, blk: np.ndarray,
                  extra_ctrl: np.ndarray | None = None) -> list[dict]:
    """Her özellik × her sonuç için kısmi Spearman (ATR sabit; extra_ctrl varsa onu da) — blok başına ve birleşik; BH q (birleşik t, df = gün sayısı−1)."""
    rows = []
    ctrl = atr if extra_ctrl is None else np.column_stack([atr, extra_ctrl])
    for j, nm in enumerate(names):
        x = Xm[:, j]
        ok = K.support_ok(x[np.isfinite(x)], day[np.isfinite(x)]) if np.isfinite(x).sum() > 100 else False
        row = {"name": nm, "support": bool(ok)}
        for yn, y in ys.items():
            if not ok:
                row[yn] = None
                continue
            allr = K.partial_spearman(x, y, ctrl, day)
            bl = [K.partial_spearman(x[blk == i], y[blk == i], ctrl[blk == i], day[blk == i]) for i in range(3)]
            row[yn] = {"r": allr["r"], "t": allr["t"], "g": allr["g"], "p": K.t_pvalue(allr["t"], allr["g"]),
                       "rb": [b_["r"] for b_ in bl], "tb": [b_["t"] for b_ in bl]}
            d = np.array(row[yn]["rb"])
            row[yn]["cons"] = bool(np.all(np.isfinite(d)) and (np.all(d > 0) or np.all(d < 0)))
        rows.append(row)
    for yn in ys:
        idx = [i for i, r in enumerate(rows) if r.get(yn)]
        q = bh_q(np.array([rows[i][yn]["p"] for i in idx]))
        for i, qq in zip(idx, q):
            rows[i][yn]["q"] = float(qq)
    return rows


# ------------------------------------------------------------------------------------------------ 6. (b) HA filtresi / rejim kapısı
def load_ha_pop(args):
    b, _, _, pdir = sc_paths(args)
    z = np.load(pdir / "ha.npz")
    P = K.Pop("ha")
    names = list(z["names"])
    Xr = z["X"]
    Xev = np.full((P.n, len(names)), np.nan, dtype=np.float32)
    m = P.row_of >= 0
    Xev[m] = Xr[P.row_of[m]]
    r = P.sim(P.tp)
    net, bnet = r["net"], r["b_net"]
    ok = P.valid & np.isfinite(net) & np.isfinite(bnet)
    return P, names, Xev, net, bnet, ok, r


def stage_b(args) -> None:
    b, _, _, pdir = sc_paths(args)
    t0 = time.time()
    P, names, Xev, net, bnet, ok, r = load_ha_pop(args)
    rn = np.load(pdir / "rnd.npz")
    assert list(rn["names"]) == names
    exc = np.where(ok, net - bnet, np.nan)
    netv = np.where(ok, net, np.nan)
    blk = np.where(ok, P.block, -1)
    day = P.day
    atr = P.atr
    res: dict = {"names": names, "n": int(ok.sum()), "blk_n": [int((blk == i).sum()) for i in range(3)],
                 "base": {"net": [float(np.nanmean(netv[blk == i])) for i in range(3)], "bnet": [float(np.nanmean(bnet[ok & (blk == i)])) for i in range(3)],
                          "exc": [float(np.nanmean(exc[blk == i])) for i in range(3)]}}
    sel = ok
    ys = {"exc": exc[sel], "net": netv[sel]}
    j_sh = names.index("sh_dist")
    res["scan"] = scan_features(Xev[sel], names, ys, atr[sel], day[sel], blk[sel])
    res["scan_shield"] = scan_features(Xev[sel], names, {"exc": exc[sel]}, atr[sel], day[sel], blk[sel], extra_ctrl=Xev[sel, j_sh])
    zz = np.load(pdir / "ha.npz")
    if "X1" in zz.files:
        X1 = np.full((P.n, len(names)), np.nan, dtype=np.float32)
        mm_ = P.row_of >= 0
        X1[mm_] = zz["X1"][P.row_of[mm_]]
        res["scan_lag1"] = scan_features(X1[sel], names, ys, atr[sel], day[sel], blk[sel])
    print(f"[b] tarama bitti ({time.time() - t0:.0f} sn); q<0,05 exc: {sum(1 for x in res['scan'] if x.get('exc') and x['exc']['q'] < 0.05)}, net: {sum(1 for x in res['scan'] if x.get('net') and x['net']['q'] < 0.05)}", flush=True)
    # tersil / kategori tabloları
    ysd = {"net": netv, "exc": exc, "hit": np.where(ok, r["hit"], np.nan)}
    terc = {}
    for nm in names:
        j = names.index(nm)
        if not K.support_ok(Xev[ok, j][np.isfinite(Xev[ok, j])], day[ok][np.isfinite(Xev[ok, j])]):
            continue
        codes, labs = bucket_codes(Xev[:, j], blk, rn["X"][:, j], rn["block"])
        codes = np.where(ok, codes, -1)
        terc[nm] = {"labels": labs, "tab": bucket_table(ysd, codes, labs, blk, day)}
    res["terc"] = terc
    # saat / seans / gün tabloları
    hf = Xev[:, names.index("t_hour_f")]
    tabs = {}
    hour = np.where(np.isfinite(hf), np.floor(hf), -1).astype(int)
    tabs["saat (TR)"] = (np.where(ok, hour, -1), [f"{h:02d}" for h in range(24)])
    tabs["4 saatlik dilim (TR)"] = (np.where(ok & (hour >= 0), hour // 4, -1), ["00-04", "04-08", "08-12", "12-16", "16-20", "20-24"])
    kz = Xev[:, names.index("t_kz")]
    tabs["seans (killzone)"] = (np.where(ok & np.isfinite(kz), kz, -1).astype(int), ["dışı", "Asya 03-07", "Londra 10-13", "NY 15:30-18"])
    dw = Xev[:, names.index("t_dow")]
    tabs["haftanın günü"] = (np.where(ok & np.isfinite(dw), dw, -1).astype(int), ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"])
    sh = Xev[:, names.index("sh_open")]
    tabs["BTC kalkanı (1=açık)"] = (np.where(ok & np.isfinite(sh), sh, -1).astype(int), ["kapalı (geçer)", "AÇIK (keser)"])
    res["time"] = {k: {"labels": labs, "tab": bucket_table(ysd, codes, labs, blk, day)} for k, (codes, labs) in tabs.items()}
    # kalkan ↔ genişlik ilişkisi (ayrı bilgi mi?)
    cm = {}
    for nm in ("b_pct_ema50_5m", "b_adr_60", "b_mcc_1h", "m_ret_240"):
        x = Xev[ok, names.index(nm)]
        cm[nm] = float(K.partial_spearman(x, Xev[ok, j_sh], None, day[ok])["r"])
    res["shield_corr"] = cm
    pickle.dump(res, open(Path(args.out_dir) / "b.pkl", "wb"))
    print(f"[b] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ 7. (c) koşulsuz zamanlama
def stage_c(args) -> None:
    b, _, _, pdir = sc_paths(args)
    t0 = time.time()
    rn = np.load(pdir / "rnd.npz")
    names = list(rn["names"])
    Xm, net, blk, day, atr = rn["X"], rn["net"], rn["block"].astype(int), rn["day"], rn["atr"]
    ret60 = rn["ret60"]
    res: dict = {"names": names, "n": len(net), "blk_n": [int((blk == i).sum()) for i in range(3)],
                 "base": {"net": [float(net[blk == i].mean()) for i in range(3)], "ret60": [float(ret60[blk == i].mean()) for i in range(3)],
                          "tp_rate": [float((rn["reason"][blk == i] == X.R_TP).mean()) for i in range(3)]}}
    res["scan"] = scan_features(Xm, names, {"net": net, "ret60": ret60}, atr, day, blk)
    print(f"[c] tarama ({time.time() - t0:.0f} sn); q<0,05 net: {sum(1 for x in res['scan'] if x.get('net') and x['net']['q'] < 0.05)}", flush=True)
    ysd = {"net": net, "ret60": ret60, "net_b": rn["net_b"], "net_c": rn["net_c"]}
    terc = {}
    for j, nm in enumerate(names):
        if not K.support_ok(Xm[:, j], day):
            continue
        codes, labs = bucket_codes(Xm[:, j], blk, Xm[:, j], blk)
        terc[nm] = {"labels": labs, "tab": bucket_table(ysd, codes, labs, blk, day)}
    res["terc"] = terc
    # sabit (veriden seçilmemiş) onluk dilimler: kesitsel sıra yüzdeliği; ters yönlü (geri dönüş) etki araştırması
    dec = {}
    for nm in ("rk_15", "rk_60", "rk_240"):
        x = Xm[:, names.index(nm)]
        dec[nm] = {"labels": [f"D{i + 1}" for i in range(10)], "tab": bucket_table(ysd, np.minimum((x * 10).astype(int), 9), [f"D{i + 1}" for i in range(10)], blk, day)}
    res["dec"] = dec
    wash = Xm[:, names.index("b_pct_ema20_5m")]
    rk15 = Xm[:, names.index("rk_15")]
    st = np.where(wash <= 0.2, 0, np.where(wash >= 0.8, 2, 1))
    lg = np.where(rk15 <= 0.1, 0, np.where(rk15 >= 0.9, 2, 1))
    labs9 = [f"{a} | {b_}" for a in ("piyasa tükeniş (%EMA20 ≤ 0,2)", "piyasa orta", "piyasa güçlü (≥ 0,8)") for b_ in ("rk15 en alt %10", "rk15 orta", "rk15 en üst %10")]
    res["grid9"] = {"labels": labs9, "tab": bucket_table(ysd, np.where(np.isfinite(wash) & np.isfinite(rk15), st * 3 + lg, -1), labs9, blk, day)}
    hf = Xm[:, names.index("t_hour_f")]
    hour = np.floor(hf).astype(int)
    tabs = {"saat (TR)": (hour, [f"{h:02d}" for h in range(24)]), "4 saatlik dilim (TR)": (hour // 4, ["00-04", "04-08", "08-12", "12-16", "16-20", "20-24"]),
            "seans (killzone)": (Xm[:, names.index("t_kz")].astype(int), ["dışı", "Asya 03-07", "Londra 10-13", "NY 15:30-18"]),
            "haftanın günü": (Xm[:, names.index("t_dow")].astype(int), ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]),
            "BTC kalkanı (1=açık)": (Xm[:, names.index("sh_open")].astype(int), ["kapalı", "AÇIK"])}
    res["time"] = {k: {"labels": labs, "tab": bucket_table(ysd, codes, labs, blk, day)} for k, (codes, labs) in tabs.items()}
    # en az negatif hücreler (blok başına n ≥ 2000): min-over-blocks ortalama net
    cells = []
    for src in (res["terc"], res["time"]):
        for fn, d in src.items():
            for lab, c in d["tab"].items():
                nb = [c["b"][i]["n"] for i in range(3)]
                if min(nb) < 2000:
                    continue
                mb = [c["b"][i]["net"][0] for i in range(3)]
                cells.append({"feat": fn, "label": lab, "n": nb, "net_b": mb, "worst": min(mb), "all": c["all"]["net"]})
    cells.sort(key=lambda z_: -z_["worst"])
    res["best_cells"] = cells[:25]
    res["n_cells"] = len(cells)
    pickle.dump(res, open(Path(args.out_dir) / "c.pkl", "wb"))
    print(f"[c] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ 8. (d) kural araması
# Ön-tanımlı kurallar (eşikler VERİ GÖRÜLMEDEN, rehberin fikirlerinden; ayarlanmaz). Atom = (özellik, işlem, eşik).
PRESPEC = [
    ("R1 BTC kalkanı kapalı", [("sh_open", "==", 0.0)]),
    ("R2 geniş katılım: %EMA50(5m) üstü ≥ 0,60", [("b_pct_ema50_5m", ">=", 0.60)]),
    ("R3 genişlik itişi ∧ RS lideri (rk60 ≥ 0,8)", [("b_thrust_recent", "==", 1.0), ("rk_60", ">=", 0.8)]),
    ("R4 RS lideri (rk60 ≥ 0,9, BTC'den güçlü) ∧ %EMA20(5m) üstü ≥ 0,5", [("rk_60", ">=", 0.9), ("rs_btc_60", ">=", 0.0), ("b_pct_ema20_5m", ">=", 0.5)]),
    ("R5 dip süpürme+geri alma (PDL) ∧ SMT boğa (piyasa)", [("pd_sweep_pdl", "==", 1.0), ("smt_low_mkt", "==", 1.0)]),
    ("R6 tükeniş sonrası: %EMA20 üstü ≤ 0,15 ∧ rk15 ≥ 0,8", [("b_pct_ema20_5m", "<=", 0.15), ("rk_15", ">=", 0.8)]),
    ("R7 NY seansı ∧ RVOL ≥ 2 ∧ rk60 ≥ 0,8", [("t_kz", "==", 3.0), ("rvol_tod", ">=", 2.0), ("rk_60", ">=", 0.8)]),
    ("R8 TR-günü açılış aralığı ilk kırılım ∧ RVOL ≥ 2 ∧ %EMA50 ≥ 0,5", [("orb_tr_fresh", "==", 1.0), ("rvol_tod", ">=", 2.0), ("b_pct_ema50_5m", ">=", 0.5)]),
    ("R9 Londra seansı ∧ kalkan kapalı", [("t_kz", "==", 2.0), ("sh_open", "==", 0.0)]),
    ("R10 TRY zayıflığı: USDTTRY 4 sa ≥ +%0,10", [("usd_ret_240", ">=", 0.10)]),
    ("R11 taker alışı geniş (≥ %50 sembol) ∧ rk15 ≥ 0,7", [("b_tk55", ">=", 0.50), ("rk_15", ">=", 0.7)]),
    ("R12 piyasa 4 sa getirisi ≥ 0 ∧ BTC'den güçlü (rs_btc_240 ≥ 1)", [("m_ret_240", ">=", 0.0), ("rs_btc_240", ">=", 1.0)]),
]


def atom_mask(Xm: np.ndarray, j: int, op: str, thr: float) -> np.ndarray:
    v = Xm[:, j]
    with np.errstate(invalid="ignore"):
        if op == ">=":
            return v >= thr
        if op == "<=":
            return v <= thr
        return v == thr


def rule_mask(Xm: np.ndarray, names: list[str], rule: list[tuple]) -> np.ndarray:
    m = np.ones(len(Xm), dtype=bool)
    for nm, op, thr in rule:
        m &= atom_mask(Xm, names.index(nm), op, thr)
    return m


def rule_text(rule: list[tuple]) -> str:
    return " ∧ ".join(f"{nm} {op} {thr:.4g}" for nm, op, thr in rule)


def make_atoms(Xtr: np.ndarray, names: list[str], skip: set[str], qs=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9), rng=None) -> list[tuple]:
    atoms = []
    sub = Xtr if len(Xtr) <= 60000 else Xtr[rng.choice(len(Xtr), 60000, replace=False)]
    for j, nm in enumerate(names):
        if nm in skip:
            continue
        v = sub[:, j]
        v = v[np.isfinite(v)]
        if len(v) < 100:
            continue
        u = np.unique(v)
        if len(u) <= 5:
            atoms += [(nm, "==", float(x)) for x in u]
        else:
            for t in np.unique(np.quantile(v, qs)):
                atoms += [(nm, ">=", float(t)), (nm, "<=", float(t))]
    return atoms


def search_rule(Xm, names, y, blk, day, train_blocks, n_min, rng, max_k=3, top_atoms=40, skip=frozenset({"t_weekend"})) -> dict:
    """Eğitim bloklarında (yalnız onlarda) kural seç: skor = min_b (ortalama_b − SE_b), her eğitim bloğunda n ≥ n_min. Tek atom → çift → üçlü (açgözlü genişletme).
    Dönüş: seçilen kural, eğitim istatistikleri, denenen kural sayısı."""
    tr = np.isin(blk, train_blocks)
    Xt, yt, bt, dt = Xm[tr], y[tr], blk[tr], day[tr]
    atoms = make_atoms(Xt, names, set(skip), rng=rng)
    col = {nm: i for i, nm in enumerate(names)}

    def score(mask: np.ndarray, with_se: bool) -> tuple[float, list]:
        per = []
        for b_ in train_blocks:
            m = mask & (bt == b_)
            n = int(m.sum())
            if n < n_min:
                return -9.0, []
            v = yt[m]
            v = v[np.isfinite(v)]
            if len(v) < n_min:
                return -9.0, []
            mu = float(v.mean())
            se = float(X.cluster_se(v, dt[m][np.isfinite(yt[m])])) if with_se else 0.0
            per.append((n, mu, se))
        return min(p[1] - p[2] for p in per), per

    n_tried = 0
    sc1 = []
    for a in atoms:
        m = atom_mask(Xt, col[a[0]], a[1], a[2])
        s, _ = score(m, False)
        n_tried += 1
        if s > -9:
            sc1.append((s, a))
    sc1.sort(key=lambda z_: -z_[0])
    top = [a for _, a in sc1[:top_atoms]]
    cand = [([a], s) for s, a in sc1[:top_atoms]]
    masks = {a: atom_mask(Xt, col[a[0]], a[1], a[2]) for a in top}
    pairs = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            if top[i][0] == top[j][0]:
                continue
            m = masks[top[i]] & masks[top[j]]
            s, _ = score(m, False)
            n_tried += 1
            if s > -9:
                pairs.append(([top[i], top[j]], s))
    pairs.sort(key=lambda z_: -z_[1])
    cand += pairs[:20]
    if max_k >= 3:
        for r, _ in pairs[:5]:
            base = masks[r[0]] & masks[r[1]]
            for a in top:
                if any(a[0] == q[0] for q in r):
                    continue
                s, _ = score(base & masks[a], False)
                n_tried += 1
                if s > -9:
                    cand.append((r + [a], s))
    cand.sort(key=lambda z_: -z_[1])
    best, best_s, best_per = None, -9.0, []
    for r, _ in cand[:40]:                                  # SE'li son sıralama (en iyi 40 aday)
        m = np.ones(len(Xt), dtype=bool)
        for a in r:
            m &= masks[a] if a in masks else atom_mask(Xt, col[a[0]], a[1], a[2])
        s, per = score(m, True)
        if s > best_s:
            best, best_s, best_per = r, s, per
    return {"rule": best, "score": best_s, "train": best_per, "n_tried": n_tried, "n_atoms": len(atoms)}


def eval_rule(Xm, names, rule, y, blk, day, extra=None, mask_base=None) -> dict:
    """Blok başına: n, gün başına sinyal, ort. net, SE, t (+ extra: {ad: dizi} için ortalama/SE). Kural boş → tüm satırlar."""
    m_rule = rule_mask(Xm, names, rule) if rule else np.ones(len(Xm), dtype=bool)
    out = {"all": None, "b": []}
    for sel, key in [(None, "all")] + [(i, "b") for i in range(3)]:
        m = m_rule if sel is None else m_rule & (blk == sel)
        ys = {"net": y}
        if extra:
            ys.update(extra)
        c = cell_stats(ys, m, day)
        ndays = max(len(np.unique(day[m])), 1) if m.any() else 1
        c["per_day"] = c["n"] / (len(np.unique(day[blk == sel])) if sel is not None else len(np.unique(day[blk >= 0])))
        mu, se = c["net"]
        c["t"] = mu / se if se and np.isfinite(se) and se > 0 else float("nan")
        if key == "all":
            out["all"] = c
        else:
            out["b"].append(c)
    return out


def stage_d(args) -> None:
    b, _, _, pdir = sc_paths(args)
    t0 = time.time()
    rng = np.random.default_rng(args.seed + 5)
    rn = np.load(pdir / "rnd.npz")
    names = list(rn["names"])
    P, hnames, Xev, net_h, bnet_h, ok_h, _ = load_ha_pop(args)
    assert hnames == names
    rb_ = rn["block"].astype(int)
    tg = {"A: TP1,5/SL3/T60": rn["net"], "B: TP1/SL1,5/T30": rn["net_b"], "C: TP3/SL3/T120": rn["net_c"]}
    pops = {}
    for tn, yv in tg.items():
        others = {"net_" + k[0]: v for k, v in tg.items() if k != tn}
        pops["rastgele " + tn] = {"X": rn["X"], "y": yv, "blk": rb_, "day": rn["day"], "extra": others, "n_min": 1500}
    pops["HA adayları"] = {"X": Xev[ok_h], "y": net_h[ok_h], "blk": P.block[ok_h], "day": P.day[ok_h], "extra": {"exc": (net_h - bnet_h)[ok_h]}, "n_min": 200}
    res: dict = {"names": names, "prespec": {}, "search": {}, "pop_n": {}}
    for pn, d in pops.items():
        res["pop_n"][pn] = [int((d["blk"] == i).sum()) for i in range(3)]
        res["prespec"][pn] = {"hepsi": eval_rule(d["X"], names, [], d["y"], d["blk"], d["day"], d["extra"])}
        for nm, rule in PRESPEC:
            res["prespec"][pn][nm] = eval_rule(d["X"], names, rule, d["y"], d["blk"], d["day"], d["extra"])
        # döndürmeli seçim: 2 blokta seç, 3.de test
        rots = []
        for test_b in range(3):
            tr = [i for i in range(3) if i != test_b]
            s = search_rule(d["X"], names, d["y"], d["blk"], d["day"], tr, d["n_min"], rng)
            ev = eval_rule(d["X"], names, s["rule"], d["y"], d["blk"], d["day"], d["extra"])
            base = eval_rule(d["X"], names, [], d["y"], d["blk"], d["day"], d["extra"])
            rots.append({"test_block": test_b, "rule": s["rule"], "text": rule_text(s["rule"]) if s["rule"] else "-", "train": s["train"], "n_tried": s["n_tried"],
                         "n_atoms": s["n_atoms"], "test": ev["b"][test_b], "test_base": base["b"][test_b], "all": ev})
            t_ = ev["b"][test_b]
            print(f"[d] {pn} test=B{test_b + 1}: {rots[-1]['text']} | eğitim " + ", ".join(f"n={x[0]} net={x[1]:+.3f}" for x in s["train"])
                  + f" | TEST n={t_['n']} net={t_['net'][0]:+.3f}±{t_['net'][1]:.3f} (taban {base['b'][test_b]['net'][0]:+.3f}) ({time.time() - t0:.0f} sn)", flush=True)
        res["search"][pn] = rots
    pickle.dump(res, open(Path(args.out_dir) / "d.pkl", "wb"))
    print(f"[d] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ 9. rapor
def fx(x, d: int = 2, plus: bool = False) -> str:
    if x is None or not np.isfinite(x):
        return "-"
    s = f"{x:+.{d}f}" if plus else f"{x:.{d}f}"
    return s.replace(".", ",")


def pm(c, d: int = 2, key: str = "net") -> str:
    """hücre (ortalama, SE) → '−0,41±0,05'."""
    mu, se = c[key]
    if not np.isfinite(mu):
        return "-"
    return fx(mu, d, True) + ("±" + fx(se, d) if np.isfinite(se) else "")


def md(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def stage_report(args) -> None:
    od = Path(args.out_dir)
    A = pickle.load(open(od / "a.pkl", "rb"))
    Bb = pickle.load(open(od / "b.pkl", "rb"))
    Cc = pickle.load(open(od / "c.pkl", "rb"))
    Dd = pickle.load(open(od / "d.pkl", "rb"))
    names = A["names"]
    L: list[str] = []
    bl = ["B1", "B2", "B3"]
    verdict = verdict_text(A, Bb, Cc, Dd)
    L += ["# Piyasa genişliği, göreli güç ve zaman boyutları — çevrimdışı ölçüm (2026-10-17)", ""]
    L += verdict
    # ------------------------------------------------------------------ yöntem
    L += ["", "## 1. Veri ve yöntem", ""]
    L += [
        "- **Evren / ızgara.** 306 TRY çifti × 25.994 adet 5 dk karar barı (19 Tem 00:00 TR → 16 Eki), ortak zaman ızgarası (`panels`). Karar anı = barın KAPANIŞI; tüm özellikler o ana kadarki",
        "  veriyle hesaplanır (`app/rescan/breadth.py`, saf + nedensel; `tests/test_breadth.py` dizileri keserek yeniden hesaplar ve [:t] kısmının değişmediğini doğrular).",
        "- **Genişlik evreni (V).** Son 24 saat quote hacmi ≥ 5 M TRY (botun evreniyle aynı eşik) ∧ 24 saatlik geçmişi dolmuş ∧ pegli/stabil çift değil (USDTTRY, USDCTRY, MAVTRY, UTRY, ZAMATRY çıkarıldı). Medyan ~202 sembol.",
        "- **Genişlik özellikleri (piyasa düzeyi, her sembole aynı değer).** `b_pct_ema{20,50}_5m` (kapanış > EMA yüzdesi), `b_pct_ema{20,50}_1h` (1 saatlik EMA ≈ 5 dk kapanışlarında EMA(240)/EMA(600)), `b_adr_{5,15,60}` (1/3/12 barda yükselen/(yükselen+düşen)),",
        "  `b_adslope_{12,48}` (A/D çizgisi eğimi, geçerli sayısına bölünmüş), `b_mcc_5m` / `b_mcc_1h` (McClellan: oran-ayarlı net ilerleyenlerin EMA19−EMA39'u; 5 dk ve saatlik ölçek), `b_nhl_24h` (yeni 24 sa tepe − dip)/N,",
        "  `b_thrust` (Zweig-benzeri: 1-bar adv/(adv+dec) EMA10'u ≤ 0,40 görüldükten sonra ≤ 12 bar içinde > 0,615; `b_thrust_recent`: son 36 barda), `b_tk55` (3 barlık taker-alış payı > 0,55 olan sembol oranı), `b_disp_{5,15,60}` (kesitsel getiri standart sapması),",
        "  `m_ret_{15,60,240}` (EW piyasa getirisi, ±%20 kırpılmış), `btc_ret_*`, `usd_ret_{15,60,240,1440}` (USDTTRY getirisi = TRY zayıflığı; veride var, 5 dk'da %49 düz bar), `sh_dist` / `sh_open` (BTC 1 sa EMA200 kalkanı, canlı `_ema(closes[-210:],200)` tanımıyla, forming bar = 5 dk BTC kapanışı; `work/btc_1h_120d.json` ısınma).",
        "- **Göreli güç / karşılaştırma (sembol düzeyi).** `rs_btc_*`, `rs_mkt_*` (15/60/240 dk getiri farkı), `rk_*` (kesitsel yüzdelik sıra), `beta_btc_24h`, `corr_btc_24h` (288 bar), `rs_usd_60` (USD cinsinden 60 dk getiri), `smt_{low,high}_{btc,mkt}`",
        "  (fraktal k=3, **3 bar gecikmeyle onaylı** salınımlar; sembolün son iki dibi/tepesi ile referansın (BTCTRY ya da EW endeks) son iki dibi/tepesi ters yönlü ise ±1, salınımlar ≤ 36 bar yaşında), diğerleri 0.",
        "- **Zaman.** TR saati (UTC+3 sabit): `t_hour_f`, `t_dow`, killzone: **Asya 03:00–07:00, Londra 10:00–13:00, New York 15:30–18:00 TR [başlangıç, bitiş)** (karar anına göre; ICT seanslarının yaklaşık TR karşılığı), `t_kz`/`t_kz_*`;",
        "  `orb_tr_*` (TR günü ilk 30 dk açılış aralığı: durum ±1/0, aralık dışı % uzaklık, günün İLK kırılımı son 12 barda), `orb_utc_*` (UTC günü = 03:00 TR), `pd_*` (önceki gün tepe/dip uzaklığı, dip süpürme+geri alma / tepe süpürme+ret, son 12 bar), `rvol_tod` (3 barlık quote / önceki ≤ 7 günün aynı bar-saatindeki ortalaması, ≥ 3 gün, tavan 100).",
        "- **Bloklar (yürüyen).** B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki. Eşikler/kenarlar/kural seçimi HİÇBİR ZAMAN değerlendirilen blokta yapılmaz: tersil kenarları DİĞER iki bloktaki rastgele-an havuzundan, kural araması iki blokta yapılıp üçüncüde test edilir ve döndürülür.",
        "- **(a) olay nüfusu.** pattern90 yükseliş olayları (kümesizleştirilmiş birincil küme, 4.552 olay), t0 ve t0−10 dk; eşleşmiş taban = aynı sembol + aynı gün (olay başına ≤ 40; `snap.npz`). Grup-içi AUC = olay değerinin aynı gruptaki taban değerlerinden büyük olma payı (eşitlik ½); gün-kümeli SE, t-dağılımı (df = gün−1), BH q (62 özellik). 'Havuza karşı' = olay ↔ 250 bin tekdüze geçerli an (eşleşmemiş; günlük rejim etkisi iptal OLMAZ).",
        "  Çok değişkenli: HistGradientBoosting (150 ağaç), blok-dışı bırakma, mevcut 154 sembol özelliği (indearly anlık görüntüsü) ↔ + yeni özellik grupları.",
        "- **(b) HA nüfusu.** `work/indfilter` HA bölümleri (20.343 geçerli, 60 sn gecikme, %0,15 kayma, %0,1125/bacak; TP = adayın hedefi, SL %3, T60); sonuç = net ve **net − oynaklık-eşleşmiş rastgele giriş tabanı** (excess). Özellikler tick anında kapanan 5 dk barda ölçülür (dayanıklılık: bir bar GECİKMELİ de tarandı).",
        "  Kısmi Spearman (ATR sabit; gün-kümeli t) blok başına ve birleşik; BH q. Tersil tabloları: kenarlar diğer bloklardan.",
        "- **(c)/(d) rastgele giriş evreni.** Her blokta geçerli (sembol, 5 dk karar anı) çiftlerinden tekdüze 150 bin örnek (toplam 450 bin), giriş = karar + 60 sn gecikmeli 1 dk açılışı; **A: TP 1,5 / SL 3 / T60** (birincil), B: TP 1 / SL 1,5 / T30, C: TP 3 / SL 3 / T120; aynı maliyet modeli (`exit_sim`).",
        "  (d) kural araması: atom = özellik × (≥/≤ eşik: onluk dilimler; ≤ 5 değerli özelliklerde ==), eğitim bloklarında skor = min_b (ort. net_b − SE_b), blok başına n ≥ 1500 (HA: 200); tek atom → 40 en iyi atomdan çift → en iyi 5 çiftten üçlü; en iyi 40 aday SE'li sıralanır. Test: kalan blok.",
        "  Tüm SE'ler gün kümelidir (`exit_sim.cluster_se`).",
    ]
    # ------------------------------------------------------------------ (a)
    L += ["", "## 2. (a) Olay öngörüsü", ""]
    for o, lab in ((2, "t0−10 dk"), (0, "t0")):
        rows = A[f"rows_{o}"]
        nsig = sum(1 for r in rows if r["q"] < 0.05)
        ncons = sum(1 for r in rows if r["q"] < 0.05 and r["cons"])
        L += [f"### 2.{1 if o == 2 else 2} Tek özellik — {lab}", "",
              f"{len(rows)} özellikten BH q < 0,05: **{nsig}**, bunların 3 blokta aynı işaretli olanı: **{ncons}**. En güçlü 14 (|AUC−½| sırasıyla; AUC > ½: olayda DAHA YÜKSEK):", ""]
        top = sorted(rows, key=lambda r: -abs(r["auc"] - 0.5))[:14]
        L += md(["özellik", "grup-içi AUC", "t", "q", "AUC B1/B2/B3", "havuza karşı AUC B1/B2/B3"],
                [[r["name"], fx(r["auc"], 3), fx(r["t"], 1), fx(r["q"], 4), "/".join(fx(x, 3) for x in r["blocks"]), "/".join(fx(x, 3) for x in r["pool_auc"])] for r in top])
        L.append("")
    L += ["### 2.3 Olay oranı artışı (eşleşmemiş): havuz tersillerinde olay payı / havuz payı (t0; kenarlar diğer bloklardan)", ""]
    keyf = ["b_pct_ema50_5m", "b_pct_ema20_1h", "b_adr_60", "b_mcc_5m", "b_tk55", "b_disp_60", "m_ret_60", "usd_ret_240", "rk_15", "rk_60", "rs_btc_60", "rvol_tod", "t_hour_f", "sh_dist"]
    rows_ = []
    for k in keyf:
        if k in A["lift"]:
            rows_.append([k] + [" / ".join(fx(v, 2) for v in A["lift"][k][i]) for i in range(3)])
    L += md(["özellik", "B1 (T1/T2/T3)", "B2", "B3"], rows_)
    L += ["", "T3 = yüksek değer. Örn. `b_disp_60` T3'te ×1,2–1,5 (yüksek kesitsel dağılım = oynak piyasa), `rvol_tod` T3 ×1,7–1,9, `rk_15` T1 (son 15 dkda geride kalanlar) ×1,8–2,0: olaylar küçük bir gerilemeden sonra başlıyor (önceki çalışmalarla uyumlu).", ""]
    L += ["### 2.4 Çok değişkenli (HGB, blok-dışı) — eşleşmiş taban (grup-içi AUC: B1/B2/B3 ve ortalama)", ""]
    rows_ = []
    for nm in A["multi"][2]:
        r2, r0 = A["multi"][2][nm], A["multi"][0][nm]
        rows_.append([nm, "/".join(fx(x["auc_group"], 3) for x in r2), fx(np.mean([x["auc_group"] for x in r2]), 3),
                      "/".join(fx(x["auc_group"], 3) for x in r0), fx(np.mean([x["auc_group"] for x in r0]), 3)])
    L += md(["özellik kümesi", "t0−10 B1/B2/B3", "ort.", "t0 B1/B2/B3", "ort."], rows_)
    L += ["", "**Eşleşmemiş** (olay ↔ tüm geçerli anlar; AUC B1/B2/B3 ve ortalama):", ""]
    rows_ = []
    for nm in A["unmatched_multi"][2]:
        r2, r0 = A["unmatched_multi"][2][nm], A["unmatched_multi"][0][nm]
        rows_.append([nm, "/".join(fx(x, 3) for x in r2), fx(np.mean(r2), 3), "/".join(fx(x, 3) for x in r0), fx(np.mean(r0), 3)])
    L += md(["özellik kümesi", "t0−10", "ort.", "t0", "ort."], rows_)
    # ------------------------------------------------------------------ (b)
    L += ["", "## 3. (b) Hız Avcısı filtresi / rejim kapısı", ""]
    L += [f"HA geçerli olay: {Bb['n']} (B1/B2/B3: {'/'.join(str(x) for x in Bb['blk_n'])}). Mutlak net (blok): {'/'.join(fx(x, 3, True) for x in Bb['base']['net'])}; oynaklık-eşleşmiş rastgele taban: "
          f"{'/'.join(fx(x, 3, True) for x in Bb['base']['bnet'])}; excess (net − taban): {'/'.join(fx(x, 3, True) for x in Bb['base']['exc'])}.", ""]
    L += ["### 3.1 Kısmi Spearman taraması (ATR sabit; gün-kümeli)", ""]
    sc = [r for r in Bb["scan"] if r.get("exc")]
    nq = sum(1 for r in sc if r["exc"]["q"] < 0.05)
    nqc = sum(1 for r in sc if r["exc"]["q"] < 0.05 and r["exc"]["cons"])
    nqn = sum(1 for r in sc if r["net"]["q"] < 0.05)
    L += [f"{len(sc)} özellik (destek koşulunu sağlayan). excess için BH q < 0,05: **{nq}** (3 blokta aynı işaret: {nqc}); mutlak net için q < 0,05: {nqn}. En küçük p'li 14 (excess):", ""]
    top = sorted(sc, key=lambda r: r["exc"]["p"])[:14]
    fam_lists: dict[str, list[str]] = {}
    for r in sorted([r for r in sc if r["exc"]["q"] < 0.05], key=lambda r: r["exc"]["p"]):
        fam_lists.setdefault(_fam(r["name"]), []).append(r["name"])
    L += ["Anlamlı özellikler (excess, q<0,05) aileye göre: " + "; ".join(f"**{k}**: " + ", ".join(v_) for k, v_ in fam_lists.items()) + ".", ""]
    lag = {r["name"]: r for r in Bb.get("scan_lag1", [])}
    shd = {r["name"]: r for r in Bb["scan_shield"]}
    L += md(["özellik", "r(excess)", "t", "q", "r B1/B2/B3", "r (1 bar gecikmeli)", "r (kalkan sabit)", "r(net)", "q(net)"],
            [[r["name"], fx(r["exc"]["r"], 3, True), fx(r["exc"]["t"], 1), fx(r["exc"]["q"], 4), "/".join(fx(x, 3, True) for x in r["exc"]["rb"]),
              fx(lag[r["name"]]["exc"]["r"], 3, True) if lag.get(r["name"]) and lag[r["name"]].get("exc") else "-",
              fx(shd[r["name"]]["exc"]["r"], 3, True) if shd.get(r["name"]) and shd[r["name"]].get("exc") else "-",
              fx(r["net"]["r"], 3, True), fx(r["net"]["q"], 4)] for r in top])
    L += ["", "Negatif r: özellik yükseldikçe HA'nın taban üstü kazancı AZALIYOR (en güçlü etki: aday BTC'ye/piyasaya göre geçmiş 60 dkda ne kadar ÖNDEYSE o kadar kötü — geri dönüş/yorgunluk).", ""]
    L += ["### 3.2 Başlıca özellikler — tersil tabloları (HA; net ve excess, ortalama±SE; kenarlar diğer bloklardan)", ""]
    rows_ = []
    for k in ["b_pct_ema20_5m", "b_pct_ema50_5m", "b_pct_ema20_1h", "b_adr_15", "b_adr_60", "b_mcc_1h", "b_tk55", "b_disp_60", "m_ret_60", "usd_ret_240", "sh_dist",
              "rs_btc_60", "rk_60", "rvol_tod", "beta_btc_24h", "orb_tr_dist"]:
        v = Bb["terc"].get(k)
        if not v:
            continue
        for lab, cc in v["tab"].items():
            rows_.append([k if lab == v["labels"][0] else "", lab, cc["all"]["n"], pm(cc["all"], 2, "net"), pm(cc["all"], 2, "exc"),
                          "/".join(fx(x["exc"][0], 2, True) for x in cc["b"]), "/".join(fx(x["net"][0], 2, True) for x in cc["b"])])
    L += md(["özellik", "kova", "n", "net", "excess", "excess B1/B2/B3", "net B1/B2/B3"], rows_)
    L += ["", "### 3.3 Saat / seans / gün / kalkan (HA)", ""]
    for tn, v in Bb["time"].items():
        if tn == "saat (TR)":
            continue
        L += [f"**{tn}**", ""]
        L += md(["kova", "n", "net", "excess", "net B1/B2/B3", "excess B1/B2/B3"],
                [[lab, cc["all"]["n"], pm(cc["all"], 2, "net"), pm(cc["all"], 2, "exc"), "/".join(fx(x["net"][0], 2, True) for x in cc["b"]),
                  "/".join(fx(x["exc"][0], 2, True) for x in cc["b"])] for lab, cc in v["tab"].items()])
        L.append("")
    v = Bb["time"]["saat (TR)"]
    L += ["**Saat (TR, karar anı)**", ""]
    L += md(["saat", "n", "net", "excess", "net B1/B2/B3"], [[lab, cc["all"]["n"], pm(cc["all"], 2, "net"), pm(cc["all"], 2, "exc"), "/".join(fx(x["net"][0], 2, True) for x in cc["b"])]
                                                           for lab, cc in v["tab"].items()])
    sc_ = Bb["shield_corr"]
    L += ["", f"Kalkan ↔ genişlik: kalkan uzaklığı (`sh_dist`) ile Spearman — %EMA50(5m) {fx(sc_['b_pct_ema50_5m'], 2, True)}, adr60 {fx(sc_['b_adr_60'], 2, True)}, McClellan(1h) {fx(sc_['b_mcc_1h'], 2, True)}, EW 4 sa getiri {fx(sc_['m_ret_240'], 2, True)} (ilişkili ama özdeş değil).", ""]
    # ------------------------------------------------------------------ (c)
    L += ["## 4. (c) Koşulsuz zamanlama — rastgele uzun girişler", ""]
    L += [f"450 bin rastgele giriş (B1/B2/B3 150'şer bin). **A (TP 1,5/SL 3/T60) ortalama net:** {'/'.join(fx(x, 3, True) for x in Cc['base']['net'])}; brüt 60 dk getiri (maliyetsiz, kapanıştan kapanışa): "
          f"{'/'.join(fx(x, 3, True) for x in Cc['base']['ret60'])}; TP isabeti {'/'.join(fx(100 * x, 1) for x in Cc['base']['tp_rate'])} %.", ""]
    sc = [r for r in Cc["scan"] if r.get("net")]
    L += [f"Kısmi Spearman (ATR sabit) net için q < 0,05: **{sum(1 for r in sc if r['net']['q'] < 0.05)}/{len(sc)}**, bunların blok-tutarlı olanı {sum(1 for r in sc if r['net']['q'] < 0.05 and r['net']['cons'])}. En güçlü 10:", ""]
    top = sorted(sc, key=lambda r: r["net"]["p"])[:10]
    L += md(["özellik", "r(net)", "t", "q", "r B1/B2/B3", "r(brüt ret60)", "t"], [[r["name"], fx(r["net"]["r"], 3, True), fx(r["net"]["t"], 1), fx(r["net"]["q"], 4),
                                                                          "/".join(fx(x, 3, True) for x in r["net"]["rb"]), fx(r["ret60"]["r"], 3, True), fx(r["ret60"]["t"], 1)] for r in top])
    L += ["", "### 4.1 Rejim tersilleri (kenarlar diğer bloklardan) ve zaman", ""]
    rows_ = []
    for k in ["b_pct_ema20_5m", "b_pct_ema50_5m", "b_pct_ema50_1h", "b_adr_60", "b_mcc_1h", "b_nhl_24h", "b_tk55", "b_disp_60", "m_ret_60", "usd_ret_240", "sh_dist", "rk_60", "rvol_tod"]:
        v = Cc["terc"].get(k)
        if not v:
            continue
        for lab, cc in v["tab"].items():
            rows_.append([k if lab == v["labels"][0] else "", lab, cc["all"]["n"], pm(cc["all"], 2, "net"), fx(cc["all"]["ret60"][0], 3, True),
                          "/".join(fx(x["net"][0], 2, True) for x in cc["b"])])
    L += md(["özellik", "kova", "n", "net (A)", "brüt ret60", "net B1/B2/B3"], rows_)
    for tn in ("4 saatlik dilim (TR)", "seans (killzone)", "BTC kalkanı (1=açık)", "haftanın günü"):
        v = Cc["time"][tn]
        L += ["", f"**{tn}**", ""]
        L += md(["kova", "n", "net (A)", "brüt ret60", "net B1/B2/B3"], [[lab, cc["all"]["n"], pm(cc["all"], 2, "net"), fx(cc["all"]["ret60"][0], 3, True), "/".join(fx(x["net"][0], 2, True) for x in cc["b"])]
                                                                            for lab, cc in v["tab"].items()])
    v = Cc["time"]["saat (TR)"]
    L += ["", "**Saat (TR)**", ""]
    L += md(["saat", "n", "net (A)", "net B1/B2/B3"], [[lab, cc["all"]["n"], pm(cc["all"], 2, "net"), "/".join(fx(x["net"][0], 2, True) for x in cc["b"])] for lab, cc in v["tab"].items()])
    L += ["", f"### 4.2 En az negatif hücreler (blok başına n ≥ 2000; {Cc['n_cells']} hücre içinde en kötü bloğa göre sıralı — bu bir 'en iyisini seçme' listesidir, kazananın laneti geçerli; hiçbiri pozitif değil)", ""]
    L += md(["özellik", "kova", "n (B1/B2/B3)", "net B1/B2/B3", "tümü"], [[x["feat"], x["label"], "/".join(str(n) for n in x["n"]), "/".join(fx(m, 2, True) for m in x["net_b"]), fx(x["all"][0], 3, True)] for x in Cc["best_cells"][:12]])
    L += ["", "### 4.3 Kesitsel geri dönüş: rk_15 / rk_60 onluk dilimleri (sabit sınırlar; D1 = en geride kalan)", ""]
    for nm in ("rk_15", "rk_60"):
        L += [f"**{nm}**", ""]
        L += md(["dilim", "n", "net A", "net B", "net C", "brüt ret60", "net A B1/B2/B3"],
                [[lab, cc["all"]["n"], fx(cc["all"]["net"][0], 3, True), fx(cc["all"]["net_b"][0], 3, True), fx(cc["all"]["net_c"][0], 3, True), fx(cc["all"]["ret60"][0], 3, True),
                  "/".join(fx(x["net"][0], 2, True) for x in cc["b"])] for lab, cc in Cc["dec"][nm]["tab"].items()])
        L.append("")
    L += ["**Piyasa durumu × rk15 (sabit eşikler)**", ""]
    L += md(["hücre", "n", "net A", "net B", "net C", "brüt ret60", "net A B1/B2/B3"],
            [[lab.replace(" | ", " / "), cc["all"]["n"], fx(cc["all"]["net"][0], 3, True), fx(cc["all"]["net_b"][0], 3, True), fx(cc["all"]["net_c"][0], 3, True), fx(cc["all"]["ret60"][0], 3, True),
              "/".join(fx(x["net"][0], 2, True) for x in cc["b"])] for lab, cc in Cc["grid9"]["tab"].items()])
    # ------------------------------------------------------------------ (d)
    L += ["", "## 5. (d) Kural arayışı — net pozitif örneklem-dışı kural var mı?", ""]
    L += ["### 5.1 Ön-tanımlı kurallar (eşikler veri görülmeden sabit)", ""]
    for pn in Dd["prespec"]:
        if not (pn.startswith("rastgele A") or pn == "HA adayları"):
            continue
        L += [f"**{pn}** (blok n: {'/'.join(str(x) for x in Dd['pop_n'][pn])})", ""]
        hdr = ["kural", ("pay % (~sinyal/gün, tüm evren)" if pn != "HA adayları" else "sinyal/gün"), "net B1", "net B2", "net B3", "net tümü", "t"] + (["excess tümü"] if pn == "HA adayları" else ["net B tümü", "net C tümü"])
        rows_ = []
        for nm, ev in Dd["prespec"][pn].items():
            r = [nm, (fx(100 * ev["all"]["n"] / sum(Dd["pop_n"][pn]), 1) + " (" + fx(ev["all"]["n"] / sum(Dd["pop_n"][pn]) * 57000, 0) + ")") if pn != "HA adayları" else fx(ev["all"]["per_day"], 1)] + [pm(ev["b"][i], 2) for i in range(3)] + [pm(ev["all"], 2), fx(ev["all"]["t"], 1)]
            if pn == "HA adayları":
                r += [pm(ev["all"], 2, "exc")]
            else:
                r += [pm(ev["all"], 2, "net_B"), pm(ev["all"], 2, "net_C")]
            rows_.append(r)
        L += md(hdr, rows_)
        L.append("")
    L += ["### 5.2 Döndürmeli seçim (2 blokta seç, 3.de test)", ""]
    for pn, rots in Dd["search"].items():
        L += [f"**{pn}**", ""]
        rows_ = []
        for r in rots:
            tr_s = "; ".join(f"n={n_} net {fx(mu, 2, True)}" for n_, mu, se in r["train"]) if r["train"] else "-"
            t_ = r["test"]
            rows_.append([f"B{r['test_block'] + 1}", r["text"], tr_s, t_["n"], pm(t_, 2), fx(r["test_base"]["net"][0], 2, True), fx(t_["net"][0] - r["test_base"]["net"][0], 2, True)])
        L += md(["test bloğu", "seçilen kural (eğitimde)", "eğitim (blok başına)", "test n", "test net±SE", "test bloğu tabanı", "Δ taban"], rows_)
        L.append(f"(denenen kural sayısı ~ {rots[0]['n_tried']} / rotasyon, atom {rots[0]['n_atoms']})")
        L.append("")
    L += ["## 6. Sınırlamalar", "",
          "- Her sonuç 90 günlük tek bir rejim dizisine (Tem–Eki 2026, BTC EMA200 kalkanı ~%44 açık) ve 3 bloğa dayanır; blok sayısı küçüktür, 'tutarlı' = 3/3 işaret.",
          "- Genişlik piyasa düzeyinde tek seri olduğu için etkin bağımsız örnek sayısı gün sayısına (~90) yakındır; bu yüzden SE'ler gün kümelidir ve eşleşmiş tabanlı (a)'da günlük rejim etkisi kısmen iptal olur.",
          "- Fraktal/SMT özellikleri 3 bar gecikmeyle onaylanır; 'canlıda tam o anda bilinir' varsayımı HA tick anında kapanan bar için de yapılmıştır (bir bar gecikmeli tarama sonuçları tabloda).",
          "- Kesin killzone sınırları ve TR/UTC günü tanımı keyfidir; saat ızgarası bu yüzden 24 saatlik tabloyla da verilmiştir. Çoklu karşılaştırma: ~60 özellik × birçok kova; q değerleri yalnız tarama içindir, kova tablolarında düzeltme YOKTUR.",
          "- Rastgele giriş evreni 5 dk karar anlarından örneklenir (HA'ya benzer tick yapısı); 1 dk verisi eksik semboller/anlar düşer. Maliyet: giriş+çıkış kayması %0,15, bacak başı %0,1125 (BNB taker).",
          ]
    # tam tablolar CSV (rapordaki 'en güçlü N' listelerinin tamamı)
    import csv
    with open(od / "a_features.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["offset", "feature", "group_auc", "t", "q", "auc_B1", "auc_B2", "auc_B3", "block_consistent", "pool_auc_B1", "pool_auc_B2", "pool_auc_B3"])
        for o in (2, 0):
            for r in A[f"rows_{o}"]:
                w.writerow([o, r["name"], f"{r['auc']:.4f}", f"{r['t']:.2f}", f"{r['q']:.5f}", *[f"{x:.4f}" for x in r["blocks"]], int(r["cons"]), *[f"{x:.4f}" for x in r["pool_auc"]]])
    for nm, src, keys in (("b_scan.csv", Bb["scan"], ("exc", "net")), ("c_scan.csv", Cc["scan"], ("net", "ret60"))):
        with open(od / nm, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["feature"] + [f"{k}_{c_}" for k in keys for c_ in ("r", "t", "q", "r_B1", "r_B2", "r_B3", "consistent")])
            for r in src:
                row = [r["name"]]
                for k in keys:
                    v_ = r.get(k)
                    row += [f"{v_['r']:.4f}", f"{v_['t']:.2f}", f"{v_.get('q', float('nan')):.5f}", *[f"{x:.4f}" for x in v_["rb"]], int(v_["cons"])] if v_ else [""] * 7
                w.writerow(row)
    (od / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[report] yazıldı: {od / 'report.md'} ({len(L)} satır)", flush=True)


def _fam(n: str) -> str:
    if n.startswith(("b_", "m_ret", "btc_ret", "usd_ret", "sh_")):
        return "genişlik/piyasa"
    if n.startswith(("rs_", "rk_", "beta_", "corr_", "smt_")):
        return "göreli güç/SMT"
    return "zaman/seans/gün-içi"


def verdict_text(A, Bb, Cc, Dd) -> list[str]:
    """Hüküm paragrafı + özet tablo (sayılardan üretilir)."""
    mean_g = lambda rs: float(np.mean([x["auc_group"] for x in rs]))
    m2, m0 = A["multi"][2], A["multi"][0]
    base2, base0 = mean_g(m2["mevcut 154"]), mean_g(m0["mevcut 154"])
    d2 = {k: mean_g(v) - base2 for k, v in m2.items() if k.startswith("mevcut +")}
    d0 = {k: mean_g(v) - base0 for k, v in m0.items() if k.startswith("mevcut +")}
    un2 = A["unmatched_multi"][2]
    r2 = A["rows_2"]
    nsig2 = sum(1 for r in r2 if r["q"] < 0.05)
    ncons2 = sum(1 for r in r2 if r["q"] < 0.05 and r["cons"])
    # (b)
    sc = [r for r in Bb["scan"] if r.get("exc")]
    sig = sorted([r for r in sc if r["exc"]["q"] < 0.05], key=lambda r: r["exc"]["p"])
    fam_n = {}
    for r in sig:
        fam_n[_fam(r["name"])] = fam_n.get(_fam(r["name"]), 0) + 1
    fam_s = ", ".join(f"{k} {v}" for k, v in fam_n.items())
    top_b = sig[0] if sig else None
    sh = Bb["time"]["BTC kalkanı (1=açık)"]["tab"]
    sh_c, sh_o = sh["kapalı (geçer)"]["all"], sh["AÇIK (keser)"]["all"]
    best_gate = []
    for k, v in Bb["terc"].items():
        labs = v["labels"]
        if len(labs) != 3:
            continue
        ex = [v["tab"][l]["all"]["exc"][0] for l in labs]
        nt = [v["tab"][l]["all"]["net"][0] for l in labs]
        exb = [[v["tab"][l]["b"][i]["exc"][0] for i in range(3)] for l in labs]
        best_gate.append((k, max(nt) - min(nt), max(ex) - min(ex), max(nt)))
    max_net_cell = max(x[3] for x in best_gate)
    # tüm HA kovalarında en yüksek net
    all_ha_nets = [v["tab"][l]["all"]["net"][0] for v in list(Bb["terc"].values()) + list(Bb["time"].values()) for l in v["labels"] if v["tab"][l]["all"]["n"] >= 300]
    # (c)
    base_c = Cc["base"]["net"]
    cells_c = [v["tab"][l]["all"]["net"][0] for src in (Cc["terc"], Cc["time"]) for v in src.values() for l in v["labels"] if v["tab"][l]["all"]["n"] >= 5000]
    bc = Cc["best_cells"][0]
    dec = Cc["dec"]["rk_15"]["tab"]
    d1, d10 = dec["D1"]["all"], dec["D10"]["all"]
    # (d)
    pre_pos = {}
    for pn in Dd["prespec"]:
        pre_pos[pn] = [nm for nm, ev in Dd["prespec"][pn].items() if nm != "hepsi" and all(ev["b"][i]["net"][0] > 0 for i in range(3))]
    rot = {pn: [(r["test"]["net"][0], r["test_base"]["net"][0], r["test"]["n"]) for r in rs] for pn, rs in Dd["search"].items()}
    best_delta = max(t - b for rs in rot.values() for t, b, n in rs)
    best_test = max(t for rs in rot.values() for t, b, n in rs)
    tr_all = [mu for rs in Dd["search"].values() for r in rs for n_, mu, se in r["train"]]
    tr_min, tr_max = min(tr_all), max(tr_all)
    max_dev = max(abs(r['auc'] - 0.5) for r in r2)
    ha_delta = '/'.join(fx(t - b, 2, True) for t, b, n in rot['HA adayları'])
    L = []
    L.append(f"**Hüküm: HAYIR — kesitsel (genişlik / göreli güç / USDTTRY) ve zaman (saat, killzone, açılış aralığı, önceki gün) boyutları hiçbir örneklem-dışı blokta net-pozitif bir kural üretmedi, "
             f"Hız Avcısı'nı kâra geçirmedi ve mevcut BTC EMA200 kalkanına anlamlı bir şey eklemedi.** Bilgi var ama küçük ve maliyetin çok altında:")
    L.append("")
    L.append(f"1. **(a) Olay öngörüsü.** {len(r2)} yeni özelliğin t0−10'da {nsig2} tanesi BH q<0,05, {ncons2} tanesi 3 blokta aynı işaretli; ama etkiler 'oynak piyasa / yüksek RVOL / kesitsel dağılım yüksek' ve 'aday son 15–60 dkda piyasanın GERİSİNDE' "
             f"ailesinde (en büyük |AUC−½| = {fx(max_dev, 3)}). Çok değişkenli modelde mevcut 154 sembol özelliğine eklenince t0−10 grup-içi AUC {fx(base2, 3)} → "
             + ", ".join(f"{k.replace('mevcut + ', '')} {fx(d2[k], 3, True)}" for k in d2) + f"; t0'da {fx(base0, 3)} → " + ", ".join(f"{k.replace('mevcut + ', '')} {fx(d0[k], 3, True)}" for k in d0)
             + f". Eşleşmemiş (tüm geçerli anlara karşı) yeni özellikler TEK BAŞINA t0−10'da AUC {fx(np.mean(un2['yalnız yeni']), 3)} (mevcut 154: {fx(np.mean(un2['mevcut 154']), 3)}) veriyor — olaylar oynak/yüksek hacimli rejimlerde ve saatlerde kümeleniyor — "
             f"ama mevcut özelliklere ekleyince yalnız {fx(np.mean(un2['mevcut + yeni']) - np.mean(un2['mevcut 154']), 3, True)}.")
    L.append(f"2. **(b) HA filtresi.** {len(sc)} özellikten excess için q<0,05: {len(sig)} ({fam_s}); en güçlü `{top_b['name']}` kısmi r {fx(top_b['exc']['r'], 3, True)} (t {fx(top_b['exc']['t'], 1)}), "
             f"yani HA adayı BTC'ye/piyasaya göre geçmiş 60 dkda ne kadar öndeyse taban üstü kazanç o kadar küçük. Piyasa genişliği özelliklerinin (%EMA, A/D, McClellan, taker payı, itiş) HA'yı ayırması zayıf/tutarsız. "
             f"Tersil/saat/seans kovalarının HİÇBİRİNDE HA neti pozitif değil (en iyi kova {fx(max(all_ha_nets), 2, True)}, n≥300; mutlak net aralığı {fx(min(all_ha_nets), 2, True)} … {fx(max(all_ha_nets), 2, True)}). "
             f"**BTC kalkanıyla karşılaştırma:** kalkan KAPALI (bildirim giden) net {pm(sh_c, 2)} / excess {pm(sh_c, 2, 'exc')}; AÇIK (kesilen) {pm(sh_o, 2)} / {pm(sh_o, 2, 'exc')} — kalkan yine ayırt etmiyor (önceki çalışmayla uyumlu); "
             f"kalkan sabit tutulunca göreli güç etkileri değişmiyor (taramada `r (kalkan sabit)`).")
    L.append(f"3. **(c) Koşulsuz zamanlama.** Rastgele uzun giriş (TP 1,5/SL 3/T60) ortalama net {'/'.join(fx(x, 2, True) for x in base_c)} (B1/B2/B3); brüt 60 dk getiri ≈ 0 ({'/'.join(fx(x, 2, True) for x in Cc['base']['ret60'])}). "
             f"Hiçbir rejim tersili / saat / seans / gün hücresi pozitif değil: hücre aralığı {fx(min(cells_c), 2, True)} … {fx(max(cells_c), 2, True)}; en az negatif tutarlı hücre `{bc['feat']} {bc['label']}` "
             f"({'/'.join(fx(x, 2, True) for x in bc['net_b'])}). Tek tutarlı yapı kesitsel GERİ DÖNÜŞ: son 15 dkda en geride kalan %10 (D1) brüt ret60 {fx(d1['ret60'][0], 2, True)} / net {fx(d1['net'][0], 2, True)} "
             f"vs en öndeki %10 (D10) {fx(d10['ret60'][0], 2, True)} / {fx(d10['net'][0], 2, True)}: ~%0,15 brüt fark, ~%0,5 maliyet duvarının çok altında.")
    L.append(f"4. **(d) Kural.** 12 ön-tanımlı kuralın 3 blokta birden net>0 olanı: rastgele evrende {len(pre_pos[next(k for k in pre_pos if k.startswith('rastgele A'))])}, HA'da {len(pre_pos['HA adayları'])}. "
             f"Döndürmeli seçimde (2 blokta ~1.800 aday/rotasyon, 3.de test; 3 çıkış yapısı + HA = 12 rotasyon) örneklem-dışı net en iyi {fx(best_test, 2, True)}, tabana göre en iyi iyileşme {fx(best_delta, 2, True)} (tipik: geri kalanlar + dipten süpürme/tükeniş koşulları); "
             f"hiçbiri pozitif değil; eğitimdeki net ({fx(tr_min, 2, True)} … {fx(tr_max, 2, True)}) test bloğunda kayboluyor (aşırı uyum). HA için seçilen kuralların tabana Δ'sı: {ha_delta}.")
    L.append("")
    L.append("**Öneri:** canlıya alınacak kesitsel/zaman kapısı YOK. Yalnızca betimleyici not: HA adayı kendi grubunun 'zaten öne geçmişi' (rk60 yüksek) ise taban üstü kazanç belirgin biçimde daha küçük; fakat bu da neti pozitife taşımıyor.")
    L.append("")
    L += md(["soru", "ana ölçüt", "sonuç"], [
        ["(a) olay öngörüsü (t0−10)", "HGB blok-dışı grup-içi AUC, mevcut 154 → + yeni", f"{fx(base2, 3)} → {fx(base2 + d2['mevcut + hepsi'], 3)} (hepsi); en iyi alt küme {fx(max(d2.values()), 3, True)} ({max(d2, key=d2.get).replace('mevcut + ', '')})"],
        ["(a) eşleşmemiş", "olay ↔ tüm geçerli an AUC", f"yalnız yeni {fx(np.mean(un2['yalnız yeni']), 3)}; mevcut {fx(np.mean(un2['mevcut 154']), 3)}; ikisi {fx(np.mean(un2['mevcut + yeni']), 3)}"],
        ["(b) HA filtresi", "excess, kısmi Spearman, BH q", f"{len(sig)}/{len(sc)} anlamlı ({fam_s}); en güçlü {top_b['name']} r {fx(top_b['exc']['r'], 3, True)}"],
        ["(b) kalkan karşılaştırması", "net / excess (kapalı vs açık)", f"{fx(sh_c['net'][0], 2, True)}/{fx(sh_c['exc'][0], 2, True)} vs {fx(sh_o['net'][0], 2, True)}/{fx(sh_o['exc'][0], 2, True)} — ayırmıyor"],
        ["(c) koşulsuz zamanlama", "rastgele giriş net (A)", f"taban {'/'.join(fx(x, 2, True) for x in base_c)}; en iyi hücre {fx(bc['all'][0], 2, True)} (`{bc['feat']} {bc['label']}`)"],
        ["(d) ön-tanımlı kurallar", "3 blokta net>0 olan kural", f"{len(pre_pos[next(k for k in pre_pos if k.startswith('rastgele A'))])} (rastgele) / {len(pre_pos['HA adayları'])} (HA)"],
        ["(d) seçilen kurallar", "test bloğu net (tabana Δ)", f"en iyi test net {fx(best_test, 2, True)}; en iyi Δ {fx(best_delta, 2, True)}; hiç pozitif yok"],
    ])
    return L


def block_idx(t_ms) -> np.ndarray:
    return K.block_of(t_ms, K.ha_blocks())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="panels,feats,pops,a,b,c,d,report")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--bdir", required=True)
    ap.add_argument("--out-dir", default="work/breadth")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rnd-per-block", type=int, default=150_000)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--skip", default="", help="pops: atlanacak parçalar (ev,ha,rnd)")
    ap.add_argument("--fx-dir", default="", help="indearly anlık görüntü klasörü (mevcut 154 özellik için)")
    args = ap.parse_args(argv)
    args.skip = {x for x in args.skip.split(',') if x}
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
