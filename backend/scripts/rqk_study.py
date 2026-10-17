"""RQK (Rational Quadratic Kernel) göstergesi çalışması — LUNA tipi erken yükselişlere destek verir mi? (2026-10-17, çevrimdışı)

Canlı koda bağlanmaz, DB'ye yazmaz (yalnız 15m mumları okur). Gösterge: `app/rescan/rqk.py` (grafik hesabının birebir portu).
90 günlük çıkış-deseni çalışmasının önbelleğini ve araçlarını kullanır (`pattern90_study`, `pattern90_analysis`: içe aktarılır, değiştirilmez).

Aşamalar (`--stages`, virgüllü):
  fetch15   DB → 15m (open_time, close) önbelleği
  sym       sembol başına: 24 kombinasyon için çekirdek durumları → olay/taban anları (zamanlama), HA adayı durumları, dönüş sinyalleri + sonuçlar
  agg       sembol dosyalarını birleştirir (sig/*.npz, ha_state.npz, mom.npz)
  analyze   tüm analizler → work/rqk/results.json
  report    results.json → work/rqk/report.md

Kullanım (backend/):
  PYTHONIOENCODING=utf-8 DATABASE_URL=... python scripts/rqk_study.py --p90-cache <p90cache> --stages fetch15,sym,agg,analyze,report
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import pattern_study as P  # noqa: E402
from app.rescan import rqk as K  # noqa: E402
from scripts.pattern90_study import MIN_QUOTE, WARM_BARS, fmt_t, list_syms, parse_day  # noqa: E402

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
DAY_MS = 86_400_000
OUT_DIR_DEFAULT = _BACKEND_DIR / "work" / "rqk"

# ------------------------------------------------------------------------------------------------ kombinasyonlar (24)
# 5m: varyant A ve B × h{8,16,25} × r{1,2,8} = 18; 1m ve 15m: yalnız varyant A, r=2, h{8,16,25} = 6  → toplam 24.
COMBOS: list[dict] = []
for _h in (8, 16, 25):
    COMBOS.append({"tf": "1m", "var": "A", "h": _h, "r": 2})
for _var in ("A", "B"):
    for _h in (8, 16, 25):
        for _r in (1, 2, 8):
            COMBOS.append({"tf": "5m", "var": _var, "h": _h, "r": _r})
for _h in (8, 16, 25):
    COMBOS.append({"tf": "15m", "var": "A", "h": _h, "r": 2})
for _c in COMBOS:
    _c["key"] = f"{_c['tf']}_{_c['var']}_h{_c['h']}_r{_c['r']}"
COMBO_KEYS = [c["key"] for c in COMBOS]
DEFAULT = {"1m": "1m_A_h8_r2", "5m": "5m_A_h8_r2", "15m": "15m_A_h8_r2"}
assert len(COMBOS) == 24

BLOCKS = {"B1": ("2026-07-20", "2026-08-18"), "B2": ("2026-08-19", "2026-09-17"), "B3": ("2026-09-18", "2026-10-16")}


def block_ivs() -> dict[str, list[tuple[int, int]]]:
    return {k: [(parse_day(a), parse_day(b, end=True))] for k, (a, b) in BLOCKS.items()}


# zamanlama özellikleri (her kombinasyon × an için)
FEATS = ["s_m15", "s_m10", "s_m5", "s_0", "s_p5", "s_p10", "s_p15", "s_p30", "age0", "stale0",
         "lastup", "lastdn", "nextup", "nextup_gain", "n_up_m15", "n_up_p15", "n_up_p30"]
FI = {n: i for i, n in enumerate(FEATS)}
OFFS = (("s_m15", -15), ("s_m10", -10), ("s_m5", -5), ("s_0", 0), ("s_p5", 5), ("s_p10", 10), ("s_p15", 15), ("s_p30", 30))


# ------------------------------------------------------------------------------------------------ yardımcılar
def cache_paths(args) -> dict[str, Path]:
    out = Path(args.out_dir)
    c = out / "cache"
    return {"out": out, "cache": c, "d15": c / "d15", "sym": c / "sym", "sig": c / "sig"}


def run_kernel(close: np.ndarray, combo: dict) -> dict:
    return K.rqk(close, combo["h"], combo["r"], variant=combo["var"])


class TfSeries:
    """Bir zaman diliminde HAM mumlar (uygulamadaki gibi sıralı, boşluk doldurulmamış) üzerinde çekirdek durumu."""

    def __init__(self, ot: np.ndarray, close: np.ndarray, combo: dict):
        self.tf_ms = TF_MS[combo["tf"]]
        self.ot = ot.astype(np.int64)
        self.close = close
        self.ct = self.ot + self.tf_ms                     # bar kapanış zamanı = karar zamanı
        r = run_kernel(close, combo)
        self.bull, self.valid = r["bull"], r["valid"]
        self.up, self.dn = r["flip_up"], r["flip_dn"]
        self.age = K.bars_since_flip(self.up, self.dn)
        self.up_pos = np.flatnonzero(self.up)
        self.dn_pos = np.flatnonzero(self.dn)
        self.up_t = self.ct[self.up_pos]
        self.dn_t = self.ct[self.dn_pos]

    def idx_at(self, t: np.ndarray) -> np.ndarray:
        """t anında KAPANMIŞ son barın indeksi (yoksa -1)."""
        return np.searchsorted(self.ct, t, side="right") - 1

    def state_at(self, t: np.ndarray) -> np.ndarray:
        """int8: 1 bullish, 0 bearish, -1 bilinmiyor."""
        i = self.idx_at(t)
        ok = (i >= 0)
        ic = np.clip(i, 0, max(len(self.ct) - 1, 0))
        ok &= self.valid[ic] if len(self.valid) else False
        if len(self.bull) == 0:
            return np.full(np.shape(t), -1, dtype=np.int8)
        return np.where(ok, self.bull[ic].astype(np.int8), -1).astype(np.int8)


def timing_features(ts: TfSeries, t: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """(n, len(FEATS)) float32. `ref`: anın referans fiyatı (5m ızgara kapanışı = olayda P0)."""
    n = len(t)
    M = np.full((n, len(FEATS)), np.nan, dtype=np.float32)
    if len(ts.ct) == 0:
        return M
    for name, off in OFFS:
        s = ts.state_at(t + off * 60_000)
        M[:, FI[name]] = np.where(s >= 0, s, np.nan)
    i0 = ts.idx_at(t)
    ic = np.clip(i0, 0, len(ts.ct) - 1)
    ok = (i0 >= 0) & ts.valid[ic]
    M[:, FI["age0"]] = np.where(ok, np.minimum(ts.age[ic], 10 ** 6), np.nan)
    M[:, FI["stale0"]] = np.where(i0 >= 0, (t - ts.ct[ic]) / 60_000.0, np.nan)
    if len(ts.up_t):
        j = np.searchsorted(ts.up_t, t, side="right")
        M[:, FI["lastup"]] = np.where(j > 0, (t - ts.up_t[np.maximum(j - 1, 0)]) / 60_000.0, np.nan)
        jc = np.minimum(j, len(ts.up_t) - 1)
        has = j < len(ts.up_t)
        M[:, FI["nextup"]] = np.where(has, (ts.up_t[jc] - t) / 60_000.0, np.nan)
        pf = ts.close[ts.up_pos[jc]]
        with np.errstate(divide="ignore", invalid="ignore"):
            M[:, FI["nextup_gain"]] = np.where(has, (pf / ref - 1.0) * 100.0, np.nan)
        for nm, lo, hi in (("n_up_m15", -15, 0), ("n_up_p15", 0, 15), ("n_up_p30", 0, 30)):
            a = np.searchsorted(ts.up_t, t + lo * 60_000, side="right")
            b = np.searchsorted(ts.up_t, t + hi * 60_000, side="right")
            M[:, FI[nm]] = b - a
    else:
        for nm in ("n_up_m15", "n_up_p15", "n_up_p30"):
            M[:, FI[nm]] = 0
    if len(ts.dn_t):
        j = np.searchsorted(ts.dn_t, t, side="right")
        M[:, FI["lastdn"]] = np.where(j > 0, (t - ts.dn_t[np.maximum(j - 1, 0)]) / 60_000.0, np.nan)
    return M


def outcomes_1m(f1: np.ndarray, real1: np.ndarray, chunk: int = 20_000) -> np.ndarray:
    """1 dk ızgarada ileri sonuçlar (n, 10) = [valid, hit1.5, net1.5, hit2.0, net2.0, hit4.0, net4.0, trail, mfe, mae].
    5 dk ölçüsüyle aynı pencere: karar barı kapanışından 5. dk … 60. dk (1 dk barlarda i+6 … i+60), ≥ 45/55 gerçek mum.
    Bellek için parçalı (parça sonu `last` bar taşar)."""
    n = len(f1)
    h, l, c = f1[:, P.COL_H], f1[:, P.COL_L], f1[:, P.COL_C]
    out = np.full((n, 10), np.nan, dtype=np.float32)
    first, last = 6, 60
    for a in range(0, n, chunk):
        b = min(n, a + chunk + last)
        seg = P.forward_outcomes(h[a:b], l[a:b], c[a:b], real1[a:b], first=first, last=last, min_bars=45)
        m = min(chunk, n - a)
        m = min(m, b - a - last) if b - a - last > 0 else 0
        if m <= 0:
            continue
        cols = [seg["valid"], seg["hit1.5"], seg["net1.5"], seg["hit2.0"], seg["net2.0"], seg["hit4.0"], seg["net4.0"],
                seg["trail_net"], seg["mfe"], seg["mae"]]
        for k, arr in enumerate(cols):
            out[a:a + m, k] = arr[:m]
    return out


def fetch15(args) -> None:
    import psycopg
    pth = cache_paths(args)
    pth["d15"].mkdir(parents=True, exist_ok=True)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    t0 = time.time()
    cur_sym = None
    buf: list = []

    def flush():
        if cur_sym is not None and buf:
            np.save(pth["d15"] / f"{cur_sym}.npy", np.array(buf, dtype=np.float64))

    n = 0
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor(name="c15") as cur:
            cur.itersize = 200_000
            cur.execute("SELECT symbol, open_time, close::float8 FROM historical_candles WHERE timeframe='15m' ORDER BY symbol, open_time")
            for sym, ot, cl in cur:
                if sym != cur_sym:
                    flush()
                    cur_sym, buf = sym, []
                buf.append((ot, cl))
                n += 1
    flush()
    print(f"[fetch15] {n} satır ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ sembol işçisi
_G: dict = {}


def _init_worker(args_dict):
    _G["a"] = argparse.Namespace(**args_dict)
    a = _G["a"]
    cache = Path(a.p90_cache)
    syms = list_syms(a.p90_cache, "d5")
    _G["syms"] = syms
    # HA satırları
    z = np.load(Path(a.p90_dir) / "ha.npz")
    _G["ha_sid"], _G["ha_t"] = z["sid"].astype(np.int64), z["t"].astype(np.int64)
    # olay / taban anları
    sn = np.load(cache / "snap.npz")
    ev = sn["ev_meta"]
    E = pickle.load(open(cache / "events.pkl", "rb"))["events"]
    keep = (ev[:, 6] == 1) & (ev[:, 7] == 1)
    kid = ev[keep, 0].astype(np.int64)
    mom_sid = [ev[keep, 1].astype(np.int64)]
    mom_t = [ev[keep, 2].astype(np.int64)]
    mom_kind = [np.ones(int(keep.sum()), dtype=np.int8)]
    mom_k = [kid]
    mm = sn["mm"]
    sel = np.isin(mm[:, 2], kid)
    mom_sid.append(mm[sel, 0]); mom_t.append(mm[sel, 1]); mom_kind.append(np.zeros(int(sel.sum()), dtype=np.int8)); mom_k.append(mm[sel, 2])
    _G["mom_sid"] = np.concatenate(mom_sid); _G["mom_t"] = np.concatenate(mom_t)
    _G["mom_kind"] = np.concatenate(mom_kind); _G["mom_k"] = np.concatenate(mom_k)
    _G["ev_p0"] = {int(k): float(E[int(k)]["p0"]) for k in kid}


def _sym_job(job):
    sid, sym = job
    a = _G["a"]
    pth = cache_paths(a)
    pc = Path(a.p90_cache)
    outp = pth["sym"] / f"{sym}.pkl"
    if outp.exists() and not a.force:
        return sym
    t0 = time.time()
    raw = {"5m": np.load(pc / "d5" / f"{sym}.npy"), "15m": np.load(pth["d15"] / f"{sym}.npy") if (pth["d15"] / f"{sym}.npy").exists() else None}
    p1 = pc / "d1" / f"{sym}.npy"
    raw["1m"] = np.load(p1) if p1.exists() else None
    g = pc / "grid"
    F5 = np.load(g / f"F5_{sym}.npy"); OT5 = np.load(g / f"OT_{sym}.npy"); OS = np.load(g / f"OS_{sym}.npy")
    c5 = F5[:, P.COL_C]
    q24 = P.rolling_sum(np.nan_to_num(F5[:, P.COL_QV], nan=0.0), 288)
    ema99 = P.ema_seeded(c5, 99)
    ct5 = OT5 + P.BAR_5M_MS
    # --- 1 dk sonuçlar
    OS1 = None; ot1_0 = None
    if raw["1m"] is not None and len(raw["1m"]) > 200:
        f1 = P.fill_gaps(raw["1m"], P.BAR_1M_MS)
        OS1 = outcomes_1m(f1, P.real_mask(raw["1m"], P.BAR_1M_MS))
        ot1_0 = int(f1[0, P.COL_OT])
        del f1
    # --- çekirdek serileri
    series: dict[str, TfSeries | None] = {}
    for cb in COMBOS:
        r = raw[cb["tf"]]
        series[cb["key"]] = TfSeries(r[:, 0], r[:, 4] if cb["tf"] != "15m" else r[:, 1], cb) if r is not None and len(r) > 40 else None
    # --- HA satırları
    hm = np.flatnonzero(_G["ha_sid"] == sid)
    ha_t = _G["ha_t"][hm]
    # --- olay/taban anları
    mm_ = np.flatnonzero(_G["mom_sid"] == sid)
    mt = _G["mom_t"][mm_]
    j5m = np.clip(np.searchsorted(ct5, mt, side="right") - 1, 0, len(c5) - 1)
    ref = c5[j5m]
    res: dict = {"sym": sym, "sid": sid, "ha_idx": hm, "mom_idx": mm_, "sig": {}, "ha": {}, "mom": {}, "n_flip_all": {}}
    for cb in COMBOS:
        key = cb["key"]; ts = series[key]
        if ts is None:
            continue
        # HA durumları
        if len(hm):
            st = ts.state_at(ha_t)
            i0 = ts.idx_at(ha_t); ic = np.clip(i0, 0, len(ts.ct) - 1)
            res["ha"][key] = (st, np.where(i0 >= 0, np.minimum(ts.age[ic], 10 ** 6), -1).astype(np.int32),
                              np.where(i0 >= 0, (ha_t - ts.ct[ic]) / 60_000.0, np.nan).astype(np.float32))
        # zamanlama
        if len(mm_):
            res["mom"][key] = timing_features(ts, mt, ref)
        # dönüş sinyalleri
        fu = ts.up_pos
        res["n_flip_all"][key] = int(len(fu))
        if len(fu) == 0:
            continue
        t_sig = ts.ct[fu]
        j5 = np.clip(np.searchsorted(ct5, t_sig, side="right") - 1, 0, len(c5) - 1)
        liq = (q24[j5] >= MIN_QUOTE) & (j5 >= WARM_BARS)
        price = ts.close[fu]
        above = np.isfinite(ema99[j5]) & (price > ema99[j5])
        if cb["tf"] == "1m":
            if OS1 is None:
                continue
            row = ((ts.ot[fu] - ot1_0) // P.BAR_1M_MS).astype(np.int64)
            row = np.clip(row, 0, len(OS1) - 1)
            outc = OS1[row]
        else:
            outc = OS[j5]            # 5m/15m: karar anı = bar kapanışı = j5. 5 dk ızgara barının kapanışı
        keepm = liq & (outc[:, 0] == 1)
        if not keepm.any():
            continue
        d15 = series[DEFAULT["15m"]]
        b15 = d15.state_at(t_sig[keepm]) if d15 is not None else np.full(int(keepm.sum()), -1, dtype=np.int8)
        res["sig"][key] = {"t": t_sig[keepm], "p": price[keepm].astype(np.float64), "above99": above[keepm], "bull15": b15,
                           "out": outc[keepm, 1:].astype(np.float32), "q24": q24[j5][keepm].astype(np.float32)}
    pth["sym"].mkdir(parents=True, exist_ok=True)
    with open(outp, "wb") as f:
        pickle.dump(res, f, protocol=4)
    return f"{sym} ({time.time() - t0:.1f} sn)"


def stage_sym(args) -> None:
    from multiprocessing import Pool
    pth = cache_paths(args)
    pth["sym"].mkdir(parents=True, exist_ok=True)
    syms = list_syms(args.p90_cache, "d5")
    jobs = [(k, s) for k, s in enumerate(syms) if (args.limit == 0 or k < args.limit)]
    t0 = time.time()
    with Pool(max(1, args.workers), initializer=_init_worker, initargs=(vars(args),)) as pool:
        for k, r in enumerate(pool.imap_unordered(_sym_job, jobs, chunksize=1)):
            if (k + 1) % 20 == 0:
                print(f"[sym] {k + 1}/{len(jobs)} ({time.time() - t0:.0f} sn) son: {r}", flush=True)
    print(f"[sym] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ birleştirme
def stage_agg(args) -> None:
    pth = cache_paths(args)
    pth["sig"].mkdir(parents=True, exist_ok=True)
    syms = list_syms(args.p90_cache, "d5")
    z = np.load(Path(args.p90_dir) / "ha.npz")
    n_ha = len(z["t"])
    sn = np.load(Path(args.p90_cache) / "snap.npz")
    ev = sn["ev_meta"]; mm = sn["mm"]
    keep = (ev[:, 6] == 1) & (ev[:, 7] == 1)
    kid = ev[keep, 0].astype(np.int64)
    sel = np.isin(mm[:, 2], kid)
    n_mom = int(keep.sum()) + int(sel.sum())
    ha = {k: (np.full(n_ha, -1, np.int8), np.full(n_ha, -1, np.int32), np.full(n_ha, np.nan, np.float32)) for k in COMBO_KEYS}
    mom = {k: np.full((n_mom, len(FEATS)), np.nan, np.float32) for k in COMBO_KEYS}
    sig_acc: dict[str, dict[str, list]] = {k: collections.defaultdict(list) for k in COMBO_KEYS}
    n_flip_all = collections.defaultdict(int)
    t0 = time.time()
    for sid, s in enumerate(syms):
        p = pth["sym"] / f"{s}.pkl"
        if not p.exists():
            continue
        r = pickle.load(open(p, "rb"))
        for key, (st, ag, sl) in r["ha"].items():
            ha[key][0][r["ha_idx"]] = st; ha[key][1][r["ha_idx"]] = ag; ha[key][2][r["ha_idx"]] = sl
        for key, M in r["mom"].items():
            mom[key][r["mom_idx"]] = M
        for key, d in r["sig"].items():
            acc = sig_acc[key]
            acc["sid"].append(np.full(len(d["t"]), sid, dtype=np.int16))
            for kk in ("t", "p", "above99", "bull15", "out", "q24"):
                acc[kk].append(d[kk])
        for key, v in r["n_flip_all"].items():
            n_flip_all[key] += v
    for key in COMBO_KEYS:
        acc = sig_acc[key]
        if not acc["sid"]:
            continue
        sid_a = np.concatenate(acc["sid"]); t_a = np.concatenate(acc["t"])
        o = np.lexsort((sid_a, t_a))
        np.savez(pth["sig"] / f"{key}.npz", sid=sid_a[o], t=t_a[o], p=np.concatenate(acc["p"])[o], above99=np.concatenate(acc["above99"])[o],
                 bull15=np.concatenate(acc["bull15"])[o], out=np.concatenate(acc["out"])[o], q24=np.concatenate(acc["q24"])[o])
    np.savez(pth["cache"] / "ha_state.npz", **{f"{k}__{i}": ha[k][i] for k in COMBO_KEYS for i in range(3)})
    # moment meta (sıra: önce olaylar, sonra taban — _init_worker ile aynı)
    msid = np.concatenate([ev[keep, 1].astype(np.int64), mm[sel, 0]]); mt = np.concatenate([ev[keep, 2].astype(np.int64), mm[sel, 1]])
    mkind = np.concatenate([np.ones(int(keep.sum()), np.int8), np.zeros(int(sel.sum()), np.int8)]); mk = np.concatenate([kid, mm[sel, 2]])
    np.savez(pth["cache"] / "mom.npz", sid=msid, t=mt, kind=mkind, k=mk, **{f"F__{k}": mom[k] for k in COMBO_KEYS})
    json.dump(dict(n_flip_all), open(pth["cache"] / "n_flip_all.json", "w"))
    print(f"[agg] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ analiz / rapor → ayrı dosya bölümü
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="fetch15,sym,agg,analyze,report")
    ap.add_argument("--p90-cache", required=True, help="pattern90_study --cache-dir (d1, d5, grid, snap.npz, events.pkl)")
    ap.add_argument("--p90-dir", default=str(_BACKEND_DIR / "work" / "pattern90"))
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--db-url", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="", help="analyze aşamasında yalnız bu analizler (timing,lunatry,filter,entry,params)")
    ap.add_argument("--rescan-jsonl", default=str(_BACKEND_DIR / "work" / "rescan_90g_nogate.jsonl"))
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        if st == "fetch15":
            fetch15(args)
        elif st in ("sym", "agg"):
            globals()[f"stage_{st}"](args)
        else:
            import scripts.rqk_analysis as RA  # noqa: E402  (analiz/rapor aşamaları ayrı dosyada)
            getattr(RA, f"stage_{st}")(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
