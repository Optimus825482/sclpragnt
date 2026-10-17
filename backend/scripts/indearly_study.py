"""Erken uyarı çalışması — rehberdeki göstergeler (klasik + SMC) LUNA tipi bir yükselişten ÖNCE ayırt edici mi? (2026-10-17, çevrimdışı)

Canlı koda bağlanmaz, DB'ye yazmaz. Gösterge kütüphanesi: `app/rescan/indicators_ext.py` (nedensel, testli).
Veri: `pattern90_study.py` önbelleği (5m doldurulmuş ızgara `grid/F5_*.npy`, 1m ham `d1/*.npy`, olaylar `events.pkl`, eşleşmiş taban `snap.npz`).

Aşamalar (`--stages`, virgüllü; varsayılan hepsi):
  feat    sembol başına kütüphane özellikleri 5m (+1m, +15m'den 5m karar ızgarasına) → <fx-dir>/FX_<sym>.npy  (float32, satır = 5m karar anı)
  snap    olay (t0−15, −10, −5, t0) ve eşleşmiş taban anlarının özellikleri → <fx-dir>/snap/*.npy
  rank    olay ↔ eşleşmiş taban sıralaması: grup-içi AUC, standartlaştırılmış fark, grup-içi permütasyon p / FWER (max-|AUC−½|), BH q;
          rehber "öncü fikirleri" (süpürme+geri alma, FVG/OB teması, birikim ıraksaması, sıkışma …) → rank.pkl
  select  fold-B EĞİTİM dönemi (2–17 Ekim) üzerinde ≤ 6 aday erken-uyarı sinyali seçimi (etiket = 60 dk içinde olay başlıyor) → cands.json
  sweep   adayların (+ rehber fikirleri) TÜM zaman çizelgesindeki sinyalleri (cooldown 12 bar) + sonuçlar → sig/*.npz
  eval    dönem bazlı ölçüler (isabet, şans farkı, exit_sim net, olay yakalama, HA'ya göre öncelik) → eval.pkl
  report  Markdown → <out-dir>/report.md

Kullanım (backend/):
  python scripts/indearly_study.py --cache-dir <p90cache> --fx-dir <scratch>/indearly --out-dir work/indearly --workers 3
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

from app.rescan import indicators_ext as I  # noqa: E402
from app.rescan import pattern_study as P  # noqa: E402
from scripts.pattern90_study import WARM_BARS, MIN_QUOTE, fmt_t, list_syms, parse_day, DAY_MS  # noqa: E402

TFS = ("5m", "1m", "15m")
OFFSETS = (3, 2, 1, 0)                     # t0−15, −10, −5, t0 (5 dk karar barı sayısı)
OFF_LABEL = {3: "t0−15", 2: "t0−10", 1: "t0−5", 0: "t0"}
CTRL_COLS = ["5m.ret1", "5m.ret3", "5m.ret5", "5m.ret10", "5m.ret20", "5m.atr14_pct", "5m.bb_pctb", "5m.px_ema7", "5m.px_ema20", "5m.rsi14",
             "1m.ret3", "1m.ret5", "1m.ret10", "1m.rsi14", "1m.atr14_pct", "5m.tk_share3", "1m.tk_net6", "5m.vol_ratio3", "5m.drawdown12_pct"]
EV_COLS = {"k": 0, "sid": 1, "t0": 2, "gain": 3, "dur": 4, "bucket_n": 5, "keep": 6, "complete": 7, "keep_b": 8, "keep_c": 9, "t_end": 10}


def end_ms() -> int:
    return parse_day("2026-10-17", end=True)


def periods() -> dict:
    """Dönemler (t0/sinyal zamanına göre). B-eğitim = seçimin yapıldığı dönem; geri kalanı örneklem dışı."""
    D = parse_day
    e = end_ms()
    return {
        "train": [(D("2026-10-02"), e)],                           # fold B eğitim (seçim burada)
        "test": [(D("2026-07-29"), D("2026-10-01", end=True))],    # fold B test (örneklem dışı)
        "blk1": [(D("2026-07-19"), D("2026-08-17", end=True))],
        "blk2": [(D("2026-08-18"), D("2026-09-16", end=True))],
        "blk3": [(D("2026-09-17"), e)],                            # son 15 günü eğitimle örtüşür
        "blk3o": [(D("2026-09-17"), D("2026-10-01", end=True))],   # blk3'ün örneklem dışı kısmı
    }


def in_iv(t, ivs) -> np.ndarray:
    t = np.asarray(t)
    m = np.zeros(t.shape, dtype=bool)
    for lo, hi in ivs:
        m |= (t >= lo) & (t <= hi)
    return m


# ------------------------------------------------------------------------------------------------ 1. özellikler
def fx_names() -> list[str]:
    return I.feature_names("5m") + I.feature_names("1m") + I.feature_names("15m")


def _feat_job(job):
    sym, cache_dir, fx_dir = job
    cache = Path(cache_dir)
    f5 = np.load(cache / "grid" / f"F5_{sym}.npy")
    t_dec = f5[:, P.COL_OT].astype(np.int64) + P.BAR_5M_MS
    n5 = len(f5)
    _, X5 = I.compute_all(f5, "5m")
    parts = [X5]
    for tf in ("1m", "15m"):
        width = len(I.feature_names(tf))
        if tf == "1m":
            p1 = cache / "d1" / f"{sym}.npy"
            arr = P.fill_gaps(np.load(p1), P.BAR_1M_MS) if p1.exists() else np.zeros((0, 9))
            bar = P.BAR_1M_MS
        else:
            arr = P.aggregate_bars(f5, 3, P.BAR_5M_MS)
            bar = 3 * P.BAR_5M_MS
        if len(arr) > 400:
            _, X = I.compute_all(arr, tf)
            idx = P.snapshot_index(arr[:, P.COL_OT].astype(np.int64), bar, t_dec)
            parts.append(np.where((idx >= 0)[:, None], X[np.clip(idx, 0, len(X) - 1)], np.float32(np.nan)).astype(np.float32))
        else:
            parts.append(np.full((n5, width), np.nan, dtype=np.float32))
    FX = np.concatenate(parts, axis=1)
    np.save(Path(fx_dir) / f"FX_{sym}.npy", FX)
    return sym


def stage_feat(args) -> None:
    from multiprocessing import Pool
    fx = Path(args.fx_dir)
    fx.mkdir(parents=True, exist_ok=True)
    names = fx_names()
    (fx / "fx_names.json").write_text(json.dumps(names), encoding="utf-8")
    syms = list_syms(args.cache_dir, "d5")
    t0 = time.time()
    with Pool(max(1, args.workers)) as pool:
        for k, _ in enumerate(pool.imap_unordered(_feat_job, [(s, args.cache_dir, args.fx_dir) for s in syms], chunksize=1)):
            if (k + 1) % 25 == 0:
                print(f"[feat] {k + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    print(f"[feat] bitti: {len(names)} özellik × {len(syms)} sembol ({time.time() - t0:.0f} sn)", flush=True)


def load_fx(fx_dir, sym: str, mmap: bool = True) -> np.ndarray:
    return np.load(Path(fx_dir) / f"FX_{sym}.npy", mmap_mode="r" if mmap else None)


# ------------------------------------------------------------------------------------------------ 2. anlık görüntüler
def stage_snap(args) -> None:
    fx = Path(args.fx_dir)
    cache = Path(args.cache_dir)
    sd = fx / "snap"
    sd.mkdir(parents=True, exist_ok=True)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    gnames = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    gcol = [gnames.index(c) for c in CTRL_COLS]
    syms = list_syms(args.cache_dir, "d5")
    E = pickle.load(open(cache / "events.pkl", "rb"))["events"]
    z = np.load(cache / "snap.npz")
    ev = z["ev_meta"]
    mm = z["mm"]
    keep = (ev[:, EV_COLS["keep"]] == 1) & (ev[:, EV_COLS["complete"]] == 1)
    kk = ev[keep, EV_COLS["k"]].astype(int)                         # olay indeksi (events listesi)
    G = len(kk)
    pos_of = {int(k): g for g, k in enumerate(kk)}
    ev_sid = ev[keep, EV_COLS["sid"]].astype(int)
    ev_t0 = ev[keep, EV_COLS["t0"]].astype(np.int64)
    ev_end = ev[keep, EV_COLS["t_end"]].astype(np.int64)
    ev_i0 = np.array([E[k]["s"] - 1 for k in kk], dtype=np.int64)
    # taban: yalnız tutulan olaylara ait
    bsel = np.array([int(k) in pos_of for k in mm[:, 2]])
    mmk = mm[bsel]
    b_sid = mmk[:, 0].astype(int)
    b_t = mmk[:, 1].astype(np.int64)
    b_g = np.array([pos_of[int(k)] for k in mmk[:, 2]], dtype=np.int64)
    nb = len(b_sid)
    F = len(names)
    XE = {o: np.full((G, F), np.nan, dtype=np.float32) for o in OFFSETS}
    XB = {o: np.full((nb, F), np.nan, dtype=np.float32) for o in OFFSETS}
    CE = {o: np.full((G, len(gcol)), np.nan, dtype=np.float32) for o in OFFSETS}
    CB = {o: np.full((nb, len(gcol)), np.nan, dtype=np.float32) for o in OFFSETS}
    NG = len(gnames)
    GE = {o: np.full((G, NG), np.nan, dtype=np.float32) for o in (0, 2)}      # tüm MEVCUT 154 özellik (çok değişkenli karşılaştırma için)
    GB = {o: np.full((nb, NG), np.nan, dtype=np.float32) for o in (0, 2)}
    t0 = time.time()
    n_bad = 0
    for sid, s in enumerate(syms):
        eg = np.flatnonzero(ev_sid == sid)
        bg = np.flatnonzero(b_sid == sid)
        if len(eg) == 0 and len(bg) == 0:
            continue
        FX = load_fx(fx, s)
        Gm = np.load(cache / "grid" / f"G_{s}.npy", mmap_mode="r")
        ot = np.load(cache / "grid" / f"OT_{s}.npy")
        n = len(ot)
        # olay t0 kontrolü: karar barı kapanışı = t0
        chk = ot[ev_i0[eg]] + P.BAR_5M_MS - ev_t0[eg]
        n_bad += int((chk != 0).sum())
        ib = (b_t[bg] - P.BAR_5M_MS - ot[0]) // P.BAR_5M_MS
        for o in OFFSETS:
            ri = np.clip(ev_i0[eg] - o, 0, n - 1)
            XE[o][eg] = FX[ri]
            CE[o][eg] = Gm[ri][:, gcol]
            rb = np.clip(ib - o, 0, n - 1)
            XB[o][bg] = FX[rb]
            CB[o][bg] = Gm[rb][:, gcol]
            if o in GE:
                GE[o][eg] = Gm[ri]
                GB[o][bg] = Gm[rb]
        if (sid + 1) % 50 == 0:
            print(f"[snap] {sid + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    for o in OFFSETS:
        np.save(sd / f"XE_{o}.npy", XE[o])
        np.save(sd / f"XB_{o}.npy", XB[o])
        np.save(sd / f"CE_{o}.npy", CE[o])
        np.save(sd / f"CB_{o}.npy", CB[o])
        if o in GE:
            np.save(sd / f"GE_{o}.npy", GE[o])
            np.save(sd / f"GB_{o}.npy", GB[o])
    np.savez(sd / "meta.npz", ev_k=kk, ev_sid=ev_sid, ev_t0=ev_t0, ev_end=ev_end, ev_i0=ev_i0, b_sid=b_sid, b_t=b_t, b_g=b_g,
             names=np.array(names), ctrl=np.array(CTRL_COLS), gnames=np.array(gnames))
    print(f"[snap] olay {G}, taban {nb}, t0 uyuşmazlığı {n_bad} ({time.time() - t0:.0f} sn)", flush=True)


def load_snap(fx_dir, off: int) -> dict:
    sd = Path(fx_dir) / "snap"
    m = np.load(sd / "meta.npz", allow_pickle=False)
    return {"XE": np.load(sd / f"XE_{off}.npy"), "XB": np.load(sd / f"XB_{off}.npy"), "CE": np.load(sd / f"CE_{off}.npy"),
            "CB": np.load(sd / f"CB_{off}.npy"), "meta": {k: m[k] for k in m.files}}


# ------------------------------------------------------------------------------------------------ 3. grup-içi (eşleşmiş) istatistik
M_MAX = 41      # 1 olay + ≤ 40 taban


def build_groups(b_g: np.ndarray, G: int) -> tuple[np.ndarray, np.ndarray]:
    """Taban satırlarını olay gruplarına yerleştirir: idx (G, 40) satır indeksi (−1 = boş), nv (G,) = 1 + geçerli taban sayısı."""
    order = np.argsort(b_g, kind="stable")
    gs = b_g[order]
    start = np.searchsorted(gs, np.arange(G), side="left")
    end = np.searchsorted(gs, np.arange(G), side="right")
    idx = np.full((G, M_MAX - 1), -1, dtype=np.int64)
    for g in range(G):
        c = min(end[g] - start[g], M_MAX - 1)
        idx[g, :c] = order[start[g]: start[g] + c]
    nv = 1 + (idx >= 0).sum(axis=1)
    return idx, nv


def group_tensor(XE: np.ndarray, XB: np.ndarray, gidx: np.ndarray, cols: np.ndarray, med: np.ndarray) -> np.ndarray:
    """(G, M, k) tensör: üye 0 = olay, 1.. = taban; NaN medyanla doldurulur; boş üyeler NaN."""
    G = XE.shape[0]
    T = np.full((G, M_MAX, len(cols)), np.nan, dtype=np.float32)
    T[:, 0, :] = XE[:, cols]
    ok = gidx >= 0
    rows = np.where(ok, gidx, 0)
    Bv = XB[:, cols][rows]                      # (G, 40, k)
    T[:, 1:, :] = np.where(ok[:, :, None], Bv, np.nan)
    # NaN doldurma (yalnız geçerli üyelerde)
    valid = np.concatenate([np.ones((G, 1), bool), ok], axis=1)
    bad = np.isnan(T) & valid[:, :, None]
    if bad.any():
        T = np.where(bad, med[None, None, :], T)
    return T


def group_ranks(T: np.ndarray, nv: np.ndarray) -> np.ndarray:
    """R[g, m, j] = (üye m'nin değeri, gruptaki DİĞER geçerli üyelerden büyük olma payı; eşitlik ½) ∈ [0,1]."""
    G, M, k = T.shape
    valid = np.arange(M)[None, :] < nv[:, None]                      # üyeler 0..nv-1 geçerli (olay + bitişik taban)
    # taban satırları idx>=0 bitişik doldurulur → geçerli üyeler 0..nv-1
    lt = (T[:, None, :, :] < T[:, :, None, :]) & valid[:, None, :, None]       # [g, m, j, k]: j < m
    eq = (T[:, None, :, :] == T[:, :, None, :]) & valid[:, None, :, None]
    cnt = lt.sum(axis=2) + 0.5 * (eq.sum(axis=2) - 1.0)
    R = cnt / np.maximum(nv[:, None, None] - 1.0, 1.0)
    return R.astype(np.float32)


def matched_stats(XE, XB, gidx, nv, cols, *, B: int, seed: int, chunk: int = 12, groups_ok=None, block_masks=None):
    """cols için: obs (eşleşmiş AUC), perm istatistik matrisi (B, len(cols)), blok AUC'leri. Gruplar nv ≥ 6 olanlardır."""
    G = XE.shape[0]
    ok_g = (nv >= 6) if groups_ok is None else (groups_ok & (nv >= 6))
    gi = np.flatnonzero(ok_g)
    rng = np.random.default_rng(seed)
    u = np.floor(rng.random((B, len(gi))) * nv[gi][None, :]).astype(np.int64)        # (B, G') seçilen üye
    flat_idx = (np.arange(len(gi))[None, :] * M_MAX + u)                              # R2 (G'*M, k) içinde
    med = np.nanmedian(XB, axis=0).astype(np.float32)
    med = np.where(np.isfinite(med), med, 0.0)
    obs = np.empty(len(cols)); blk = None
    perm = np.empty((B, len(cols)), dtype=np.float32)
    per_group = np.empty((len(gi), len(cols)), dtype=np.float32)
    for a in range(0, len(cols), chunk):
        cc = cols[a: a + chunk]
        T = group_tensor(XE[gi], XB, gidx[gi], cc, med[cc])
        R = group_ranks(T, nv[gi])
        per_group[:, a: a + len(cc)] = R[:, 0, :]
        obs[a: a + len(cc)] = R[:, 0, :].mean(axis=0)
        R2 = R.reshape(len(gi) * M_MAX, len(cc))
        for b0 in range(0, B, 250):
            sel = flat_idx[b0: b0 + 250]
            perm[b0: b0 + 250, a: a + len(cc)] = np.take(R2, sel, axis=0).mean(axis=1)
    return obs, perm, per_group, gi


def pvals_from_perm(obs: np.ndarray, perm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Çift taraflı permütasyon p ve FWER-düzeltilmiş (max-|AUC−½|) p."""
    dev_o = np.abs(obs - 0.5)
    dev_p = np.abs(perm - 0.5)
    B = len(perm)
    p = (1.0 + (dev_p >= dev_o[None, :]).sum(axis=0)) / (B + 1.0)
    mx = dev_p.max(axis=1)
    pf = (1.0 + (mx[None, :] >= dev_o[:, None]).sum(axis=1)) / (B + 1.0)
    return p, pf


def bh_q(p: np.ndarray) -> np.ndarray:
    m = len(p)
    o = np.argsort(p)
    ranked = p[o] * m / (np.arange(m) + 1.0)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[o] = np.minimum(q, 1.0)
    return out


def std_diff(XE, XB, cols, winsor=0.01) -> np.ndarray:
    d = np.empty(len(cols))
    for a, j in enumerate(cols):
        e = XE[:, j].astype(np.float64)
        b = XB[:, j].astype(np.float64)
        e = e[np.isfinite(e)]
        b = b[np.isfinite(b)]
        if len(e) < 5 or len(b) < 5:
            d[a] = np.nan
            continue
        allv = np.concatenate([e, b])
        lo, hi = np.quantile(allv, [winsor, 1 - winsor])
        e, b = np.clip(e, lo, hi), np.clip(b, lo, hi)
        sd = np.sqrt((e.var(ddof=1) * (len(e) - 1) + b.var(ddof=1) * (len(b) - 1)) / (len(e) + len(b) - 2))
        d[a] = (e.mean() - b.mean()) / sd if sd > 0 else 0.0
    return d


# ------------------------------------------------------------------------------------------------ öncü fikirler (rehber)
def idea_defs(tf: str) -> dict:
    """Fikir adı → (kısa kolon sözlüğü, taban kuantilleri) → bool/float dizi. Kolonlar `<tf>.<ad>`."""
    def c(n):
        return f"{tf}.{n}"
    return {
        "sweep_reclaim (düşük süpürme + geri alma ≤3 bar)": lambda g, q: g(c("ms_sweep_low_recent3")) == 1,
        "sweep_eql (eşit diplerin süpürülmesi)": lambda g, q: (g(c("ms_sweep_low_recent3")) == 1) & (g(c("ms_eql")) == 1),
        "choch_up (yapı dönüşü ≤6 bar)": lambda g, q: g(c("ms_since_choch_up")) <= 6,
        "fvg_bull_tap (yükseliş FVG teması)": lambda g, q: g(c("fvg_bull_tap")) == 1,
        "fvg_bull_open (açık yükseliş FVG var)": lambda g, q: g(c("fvg_bull_open")) >= 1,
        "ob_tap (yükseliş OB teması)": lambda g, q: g(c("ob_tap")) == 1,
        "ob_active (aktif yükseliş OB var)": lambda g, q: g(c("ob_active")) >= 1,
        "disp_up (son 5 barda yukarı yer değiştirme)": lambda g, q: g(c("disp_up_cnt5")) >= 1,
        "acc_div_obv (OBV↑, fiyat yatay)": lambda g, q: (g(c("obv_slope12")) > q(c("obv_slope12"), 0.70)) & (np.abs(g(c("slope_wma"))) < q(c("slope_wma"), None, absmed=True)),
        "acc_div_cmf (CMF↑, fiyat yatay)": lambda g, q: (g(c("cmf20")) > q(c("cmf20"), 0.70)) & (np.abs(g(c("slope_wma"))) < q(c("slope_wma"), None, absmed=True)),
        "acc_div_cvd (CVD↑, fiyat yatay)": lambda g, q: (g(c("cvd_slope12")) > q(c("cvd_slope12"), 0.70)) & (np.abs(g(c("slope_wma"))) < q(c("slope_wma"), None, absmed=True)),
        "squeeze_on (BB, KC içinde)": lambda g, q: g(c("squeeze_on")) == 1,
        "squeeze_release (sıkışma son 6 barda bitti)": lambda g, q: g(c("squeeze_release")) == 1,
        "chop_drop (choppiness yüksekten düşüyor)": lambda g, q: (g(c("chop_drop12")) < -8.0) & (g(c("chop14")) > 38.2),
        "st_cluster_flip (3 SuperTrend kümesi yukarı döndü)": lambda g, q: g(c("st_cluster_flip_all_up")) == 1,
        "st_flip_up3 (SuperTrend yukarı ≤3 bar)": lambda g, q: g(c("st_flip_up3")) == 1,
        "vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar)": lambda g, q: g(c("vortex_cross_up3")) == 1,
        "fisher_turn (Fisher < −1 ve yukarı dönüyor)": lambda g, q: (g(c("fisher")) < -1.0) & (g(c("fisher_chg")) > 0),
        "tsi_turn (TSI düşük bölgede sinyali yukarı kesti)": lambda g, q: (g(c("tsi")) < q(c("tsi"), 0.20)) & (g(c("tsi_sig_diff")) > 0),
        "stoch_cross_os (Stoch K>D, K<25)": lambda g, q: (g(c("stoch_kd")) > 0) & (g(c("stoch_k")) < 25),
        "stochrsi_cross_os (StochRSI K>D, K<20)": lambda g, q: (g(c("stochrsi_kd")) > 0) & (g(c("stochrsi_k")) < 20),
        "willr_os (Williams %R < −85)": lambda g, q: g(c("willr14")) < -85,
        "cci_os (CCI < −100)": lambda g, q: g(c("cci20")) < -100,
        "ao_turn (AO<0 ve artıyor)": lambda g, q: (g(c("ao_pct")) < 0) & (g(c("ao_chg")) > 0),
        "psar_flip_up3 (PSAR yukarı ≤3 bar)": lambda g, q: g(c("psar_flip_up3")) == 1,
        "ichi_tk_cross_up (Tenkan/Kijun yukarı kesişim)": lambda g, q: g(c("ichi_tk_cross_up")) == 1,
        "td_buy9 (TD 9 alış kurulumu tamam)": lambda g, q: g(c("td_buy9")) == 1,
        "td_buy7 (TD alış sayacı ≥7)": lambda g, q: g(c("td_buy")) >= 7,
        "below_vwap (VWAP altı, alt %10)": lambda g, q: g(c("vwap_dist")) < q(c("vwap_dist"), 0.10),
        "below_avwap (çapalı VWAP altı)": lambda g, q: g(c("avwap_dist")) < 0,
        "cvd_ofi (CVD↑ ve OFI z>1)": lambda g, q: (g(c("cvd_slope12")) > 0) & (g(c("ofi_z")) > 1.0),
        "ofi_sell (OFI z<−1: taker satış baskın)": lambda g, q: g(c("ofi_z")) < -1.0,
        "hv_expand (ATR(7)/ATR(50) > 1,3)": lambda g, q: g(c("atr_ratio")) > 1.3,
    }


def eval_idea(fn, X: np.ndarray, colidx: dict, qbase: dict) -> np.ndarray:
    def g(col):
        return X[:, colidx[col]]

    def q(col, p=None, absmed=False):
        key = (col, p, absmed)
        if key not in qbase:
            raise KeyError(key)
        return qbase[key]
    with np.errstate(invalid="ignore"):
        return fn(g, q)


def idea_quantiles(XB: np.ndarray, colidx: dict, tf: str) -> dict:
    out = {}
    for col, p in ((f"{tf}.obv_slope12", 0.70), (f"{tf}.cmf20", 0.70), (f"{tf}.cvd_slope12", 0.70), (f"{tf}.tsi", 0.20), (f"{tf}.vwap_dist", 0.10)):
        v = XB[:, colidx[col]]
        out[(col, p, False)] = float(np.nanquantile(v, p)) if np.isfinite(v).any() else np.nan
    v = np.abs(XB[:, colidx[f"{tf}.slope_wma"]])
    out[(f"{tf}.slope_wma", None, True)] = float(np.nanmedian(v))
    return out


# ------------------------------------------------------------------------------------------------ 4. sıralama aşaması
def stage_rank(args) -> None:
    fx = Path(args.fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    fam = {}
    I.feature_names("5m")
    for nm in names:
        fam[nm] = I.FAMILY.get(nm.split(".", 1)[1], "?")
    per = periods()
    res = {"names": names, "family": fam, "rank": {}, "ideas": {}, "ctrl": {}, "meta": {}}
    t0 = time.time()
    for off in OFFSETS:
        S = load_snap(args.fx_dir, off)
        XE, XB, CE, CB, m = S["XE"], S["XB"], S["CE"], S["CB"], S["meta"]
        G = XE.shape[0]
        gidx, nv = build_groups(m["b_g"], G)
        colidx = {nm: j for j, nm in enumerate(names)}
        nan_share = np.isnan(XE).mean(axis=0)
        cols = np.arange(len(names))
        obs, perm, pg, gi = matched_stats(XE, XB, gidx, nv, cols, B=args.n_perm, seed=args.seed + off)
        p, pf = pvals_from_perm(obs, perm)
        q = bh_q(p)
        d = std_diff(XE, XB, cols)
        # blok AUC (grup-içi payların blok ortalaması)
        t0g = m["ev_t0"][gi]
        blk = {}
        for bk in ("blk1", "blk2", "blk3"):
            mk = in_iv(t0g, per[bk])
            blk[bk] = pg[mk].mean(axis=0) if mk.sum() >= 20 else np.full(len(cols), np.nan)
        for tag in ("train", "test"):
            mk = in_iv(t0g, per[tag])
            blk[tag] = pg[mk].mean(axis=0) if mk.sum() >= 20 else np.full(len(cols), np.nan)
        # kontrol (mevcut) özelliklerin AUC'si ve dip-kontrollü artık AUC (ilk 60 özellik için)
        ccols = np.arange(CE.shape[1])
        obs_c, _, _, _ = matched_stats(CE, CB, gidx, nv, ccols, B=10, seed=1)
        res["ctrl"][off] = {CTRL_COLS[i]: float(obs_c[i]) for i in range(len(CTRL_COLS))}
        top = np.argsort(-np.abs(obs - 0.5))[:60]
        Cb = np.nan_to_num(CB, nan=0.0)
        mu, sd = Cb.mean(axis=0), Cb.std(axis=0) + 1e-9
        Z_b = (Cb - mu) / sd
        Z_e = (np.nan_to_num(CE, nan=0.0) - mu) / sd
        A_b = np.column_stack([np.ones(len(Z_b)), Z_b])
        A_e = np.column_stack([np.ones(len(Z_e)), Z_e])
        resid_auc = {}
        for j in top:
            y = np.nan_to_num(XB[:, j], nan=float(np.nanmedian(XB[:, j])) if np.isfinite(XB[:, j]).any() else 0.0)
            ye = np.nan_to_num(XE[:, j], nan=float(np.nanmedian(XB[:, j])) if np.isfinite(XB[:, j]).any() else 0.0)
            w, *_ = np.linalg.lstsq(A_b, y, rcond=None)
            rb, re_ = y - A_b @ w, ye - A_e @ w
            XEr = XE[:, :1].copy(); XBr = XB[:, :1].copy()
            XEr[:, 0], XBr[:, 0] = re_, rb
            o_, _, _, _ = matched_stats(XEr, XBr, gidx, nv, np.array([0]), B=10, seed=2)
            resid_auc[int(j)] = float(o_[0])
        recs = []
        for j, nm in enumerate(names):
            recs.append({"feature": nm, "family": fam[nm], "auc": float(obs[j]), "d": float(d[j]), "p": float(p[j]), "p_fwer": float(pf[j]), "q": float(q[j]),
                         "nan_share": float(nan_share[j]), "auc_blk1": float(blk["blk1"][j]), "auc_blk2": float(blk["blk2"][j]), "auc_blk3": float(blk["blk3"][j]),
                         "auc_train": float(blk["train"][j]), "auc_test": float(blk["test"][j]), "auc_resid": resid_auc.get(j)})
        recs.sort(key=lambda r: -abs(r["auc"] - 0.5))
        res["rank"][off] = recs
        res["meta"][off] = {"n_events": int(G), "n_base": int(len(XB)), "n_perm": args.n_perm, "n_groups_used": int(len(gi)),
                            "fwer_thr": float(np.quantile(np.abs(perm - 0.5).max(axis=1), 0.95)),
                            "n_sig_fwer": int((pf < 0.05).sum()), "n_sig_q10": int((q < 0.10).sum())}
        print(f"[rank] {OFF_LABEL[off]}: olay {G}, taban {len(XB)}, FWER eşiği {res['meta'][off]['fwer_thr']:.3f}, FWER<0,05: {res['meta'][off]['n_sig_fwer']}, "
              f"q<0,10: {res['meta'][off]['n_sig_q10']} ({time.time() - t0:.0f} sn)", flush=True)
        # --- öncü fikirler (her zaman dilimi)
        ideas = []
        for tf in TFS:
            qb = idea_quantiles(XB, colidx, tf)
            defs = idea_defs(tf)
            for nm, fn in defs.items():
                try:
                    ve = eval_idea(fn, XE, colidx, qb).astype(np.float32)
                    vb = eval_idea(fn, XB, colidx, qb).astype(np.float32)
                except KeyError:
                    continue
                if np.isnan(ve).all():
                    continue
                ideas.append((tf, nm, ve, vb))
        XEi = np.column_stack([a[2] for a in ideas])
        XBi = np.column_stack([a[3] for a in ideas])
        # NaN → 0 (koşul sağlanmıyor)
        XEi = np.nan_to_num(XEi, nan=0.0); XBi = np.nan_to_num(XBi, nan=0.0)
        oi, pi_, pgi, gii = matched_stats(XEi, XBi, gidx, nv, np.arange(XEi.shape[1]), B=args.n_perm, seed=args.seed + 100 + off)
        pp, ppf = pvals_from_perm(oi, pi_)
        qq = bh_q(pp)
        irecs = []
        for a, (tf, nm, ve, vb) in enumerate(ideas):
            e_share = float(np.nanmean(XEi[:, a] > 0)); b_share = float(np.nanmean(XBi[:, a] > 0))
            irecs.append({"tf": tf, "idea": nm, "event_share": e_share, "base_share": b_share, "lift": (e_share / b_share) if b_share > 0 else None,
                          "auc": float(oi[a]), "p": float(pp[a]), "p_fwer": float(ppf[a]), "q": float(qq[a])})
        res["ideas"][off] = irecs
    pickle.dump(res, open(Path(args.out_dir) / "rank.pkl", "wb"))
    print(f"[rank] bitti ({time.time() - t0:.0f} sn)", flush=True)


def _group_auc(p: np.ndarray, y: np.ndarray, g: np.ndarray) -> float:
    """Grup-içi AUC: her grupta olay skorunun, aynı gruptaki tabanlardan büyük olma payı (eşitlik ½), gruplar üzerinde ortalama."""
    ev = np.flatnonzero(y == 1)
    gi = g[ev]
    order = np.argsort(g[y == 0], kind="stable")
    pb = p[y == 0][order]
    gb = g[y == 0][order]
    st = np.searchsorted(gb, gi, side="left")
    en = np.searchsorted(gb, gi, side="right")
    vals = []
    for e, a, b in zip(ev, st, en):
        if b - a >= 3:
            seg = pb[a:b]
            vals.append(((seg < p[e]).sum() + 0.5 * (seg == p[e]).sum()) / (b - a))
    return float(np.mean(vals)) if vals else float("nan")


def stage_multi(args) -> None:
    """Çok değişkenli karşılaştırma: mevcut 154 özellik ↔ mevcut + kütüphane ↔ yalnız kütüphane (HistGradientBoosting, blok-dışı bırakma)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    per = periods()
    fx = Path(args.fx_dir)
    names = json.loads((fx / "fx_names.json").read_text(encoding="utf-8"))
    out = {}
    t0 = time.time()
    rng = np.random.default_rng(args.seed)
    for off in (0, 2):
        sd = fx / "snap"
        m = np.load(sd / "meta.npz")
        XE, XB = np.load(sd / f"XE_{off}.npy"), np.load(sd / f"XB_{off}.npy")
        GE, GB = np.load(sd / f"GE_{off}.npy"), np.load(sd / f"GB_{off}.npy")
        b_g = m["b_g"]
        t0g = m["ev_t0"]
        blk_ev = np.full(len(t0g), -1)
        for k, bk in enumerate(("blk1", "blk2", "blk3")):
            blk_ev[in_iv(t0g, per[bk])] = k
        # taban altörneklemi: olay başına en çok 12
        keep = np.zeros(len(b_g), bool)
        order = rng.permutation(len(b_g))
        cnt = np.zeros(len(t0g), int)
        for i in order:
            if cnt[b_g[i]] < 12:
                keep[i] = True
                cnt[b_g[i]] += 1
        bi = np.flatnonzero(keep)
        y = np.r_[np.ones(len(XE)), np.zeros(len(bi))].astype(int)
        grp = np.r_[np.arange(len(XE)), b_g[bi]]
        blk = np.r_[blk_ev, blk_ev[b_g[bi]]]
        sets = {"mevcut 154": np.vstack([GE, GB[bi]]), "mevcut + kütüphane": np.hstack([np.vstack([GE, GB[bi]]), np.vstack([XE, XB[bi]])]),
                "yalnız kütüphane": np.vstack([XE, XB[bi]])}
        res = {}
        for nm, X in sets.items():
            r = []
            for k in range(3):
                tr_, te_ = (blk != k) & (blk >= 0), blk == k
                clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                                    class_weight="balanced", random_state=0)
                clf.fit(X[tr_], y[tr_])
                p = clf.predict_proba(X[te_])[:, 1]
                r.append({"auc": float(roc_auc_score(y[te_], p)), "auc_group": _group_auc(p, y[te_], grp[te_])})
            res[nm] = r
            print(f"[multi] {S1_OFF[off]} {nm}: AUC " + ", ".join(f"{x['auc']:.3f}" for x in r) + " | grup-içi " + ", ".join(f"{x['auc_group']:.3f}" for x in r)
                  + f" ({time.time() - t0:.0f} sn)", flush=True)
        out[off] = res
    pickle.dump(out, open(Path(args.out_dir) / "multi.pkl", "wb"))


S1_OFF = OFF_LABEL


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="feat,snap,rank,select,sweep,eval,report")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--fx-dir", required=True)
    ap.add_argument("--out-dir", default="work/indearly")
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--spd-max", type=float, default=1500.0, help="seçim: tahmini bar-başı sinyal/gün üst sınırı (cooldown öncesi)")
    args = ap.parse_args(argv)
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            from scripts import indearly_signals as S2
            fn = getattr(S2, f"stage_{st}", None)
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
