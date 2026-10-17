"""90 günlük çıkış deseni çalışması — taker (emir akışı) özellikleri + çok-bölmeli doğrulama (2026-10-17, çevrimdışı).

`breakout_pattern_study.py` (21 gün, taker yok) çalışmasının genişletilmesi. Canlı koda bağlanmaz, DB'ye yazmaz.
Bu dosya VERİ aşamalarını içerir; sıralama / desen / arka test / rapor `pattern90_analysis.py` içindedir.

Aşamalar (`--stages`, virgüllü):
  data    DB → önbellek (.npy / sembol): 5m (tüm semboller) ve 1m (likit semboller); kolonlar: open_time, o, h, l, c, v, quote_v,
          taker_buy_base, taker_buy_quote
  grid    sembol başına 5m ızgarada TÜM özellikler (5m | 3m | 1m; taker dâhil) + vektörel ileri sonuçlar → .npy
  events  olay madenciliği (90 gün) + küme tespiti + kümesizleştirme → events.pkl / events.csv / events_weekly.md
  snap    olay (t0, t0+15 dk) ve taban (eşleşmiş + havuz) anlık görüntüleri → snap.npz

Kullanım (backend/):
  DATABASE_URL=... python scripts/pattern90_study.py --cache-dir <scratch> --stages data,grid,events,snap
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import pattern_study as P  # noqa: E402
from scripts.notification_outcomes_report import TZ  # noqa: E402

MIN_QUOTE = 5_000_000.0
WARM_BARS = 300            # 5m: EMA99 ısınması + 24 sa (288) pencere
OFFSETS = (0, 3)           # olay anlık görüntüsü: t0 ve t0 + 3 mum (15 dk)
DAY_MS = 86_400_000
TZ_MS = 3 * 3_600_000
CLUSTER_MIN = 8            # bir 5 dk kovada > 8 olay → piyasa geneli küme
TF_ORDER = ("5m", "3m", "1m")
OUT_SIG = ["valid", "hit1.5", "net1.5", "hit2.0", "net2.0", "hit4.0", "net4.0", "trail", "mfe", "mae"]
OUT_NULL = ["valid", "hit1.5", "hit4.0", "net1.5", "trail"]


def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + DAY_MS - 1 if end else ms


def fmt_t(ms: int | float, fmt: str = "%d/%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime(fmt)


def day_idx(ms) -> np.ndarray | int:
    """Yerel (İstanbul) gün numarası."""
    return (np.asarray(ms) + TZ_MS) // DAY_MS


def day_label(i: int) -> str:
    return datetime.fromtimestamp(int(i) * DAY_MS / 1000 - TZ_MS / 1000 + 12 * 3600, TZ).strftime("%Y-%m-%d")


# ------------------------------------------------------------------------------------------------ 1. veri
_SQL = ("SELECT open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
        "COALESCE(quote_volume, 0)::float8, taker_buy_base_volume::float8, taker_buy_quote_volume::float8 "
        "FROM historical_candles WHERE timeframe=%s AND symbol=%s ORDER BY open_time")


def _fetch(conn, tf: str, sym: str) -> np.ndarray:
    rows = conn.execute(_SQL, (tf, sym)).fetchall()
    return np.array(rows, dtype=float).reshape(-1, 9)       # None → nan


def stage_data(args) -> None:
    import psycopg
    cache = Path(args.cache_dir)
    (cache / "d5").mkdir(parents=True, exist_ok=True)
    (cache / "d1").mkdir(parents=True, exist_ok=True)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    tfs = [x.strip() for x in args.tfs.split(",")]
    t0 = time.time()
    with psycopg.connect(url, connect_timeout=10) as conn:
        if "5m" in tfs:
            syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY 1").fetchall()]
            kept = 0; liquid = []
            for k, s in enumerate(syms):
                a = _fetch(conn, "5m", s)
                if len(a) < WARM_BARS:
                    continue
                np.save(cache / "d5" / f"{s}.npy", a)
                kept += 1
                q = P.rolling_sum(np.nan_to_num(a[:, 6], nan=0.0), 288)
                ok = q[WARM_BARS:] >= MIN_QUOTE
                if len(ok) and float(ok.mean()) >= args.liquid_frac:
                    liquid.append(s)
                if (k + 1) % 50 == 0:
                    print(f"[data] 5m {k + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
            (cache / "liquid.json").write_text(json.dumps(liquid), encoding="utf-8")
            print(f"[data] 5m: {kept} sembol; likit (24s quote ≥ 5M payı ≥ %{100 * args.liquid_frac:.0f}): {len(liquid)} ({time.time() - t0:.0f} sn)", flush=True)
        if "1m" in tfs:
            liquid = json.loads((cache / "liquid.json").read_text(encoding="utf-8"))
            for k, s in enumerate(liquid):
                a = _fetch(conn, "1m", s)
                if len(a) >= 1600:
                    np.save(cache / "d1" / f"{s}.npy", a)
                if (k + 1) % 25 == 0:
                    print(f"[data] 1m {k + 1}/{len(liquid)} ({time.time() - t0:.0f} sn)", flush=True)
            print(f"[data] 1m bitti ({time.time() - t0:.0f} sn)", flush=True)


def list_syms(cache_dir: str, sub: str) -> list[str]:
    return sorted(p.stem for p in (Path(cache_dir) / sub).glob("*.npy"))


# ------------------------------------------------------------------------------------------------ 2. ızgara
def feature_names() -> list[str]:
    """Izgara sütun adları (5m | 3m | 1m); dummy 9 kolonlu dizi üzerinden."""
    n = 400
    arr = np.zeros((n, 9))
    arr[:, 0] = np.arange(n) * 60_000
    arr[:, 1:5] = 10.0
    arr[:, 5] = arr[:, 6] = arr[:, 7] = arr[:, 8] = 1.0
    names = list(P.features_matrix(arr, "5m")[0])
    for tf in ("3m", "1m"):
        names += P.features_matrix(arr, tf)[0]
    return names


def stage_grid(args) -> None:
    from multiprocessing import Pool
    cache = Path(args.cache_dir)
    gdir = cache / "grid"; gdir.mkdir(parents=True, exist_ok=True)
    names = feature_names()
    (cache / "grid_names.json").write_text(json.dumps(names), encoding="utf-8")
    syms = list_syms(args.cache_dir, "d5")
    t0 = time.time()
    with Pool(max(1, args.workers)) as pool:
        for k, res in enumerate(pool.imap_unordered(_grid_job, [(s, args.cache_dir) for s in syms], chunksize=1)):
            if (k + 1) % 25 == 0:
                print(f"[grid] {k + 1}/{len(syms)} ({time.time() - t0:.0f} sn)", flush=True)
    print(f"[grid] bitti: {len(names)} özellik ({time.time() - t0:.0f} sn)", flush=True)


def _grid_job(job):
    """Bir sembolün ızgarası + ileri sonuçlar; diske yazar."""
    sym, cache_dir = job
    cache = Path(cache_dir); gdir = cache / "grid"
    gdir.mkdir(parents=True, exist_ok=True)
    names = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    width = {tf: sum(1 for x in names if x.startswith(tf + ".")) for tf in TF_ORDER}
    a5 = np.load(cache / "d5" / f"{sym}.npy")
    p1 = cache / "d1" / f"{sym}.npy"
    f5 = P.fill_gaps(a5, P.BAR_5M_MS)
    real = P.real_mask(a5, P.BAR_5M_MS)
    _, X5 = P.features_matrix(f5, "5m")
    parts = [X5]
    ot5 = f5[:, P.COL_OT].astype(np.int64)
    t_dec = ot5 + P.BAR_5M_MS
    n = len(f5)
    if p1.exists():
        f1 = P.fill_gaps(np.load(p1), P.BAR_1M_MS)
        f3 = P.aggregate_bars(f1, 3)
        for tf, arr in (("3m", f3), ("1m", f1)):
            _, X = P.features_matrix(arr, tf)
            idx = P.snapshot_index(arr[:, P.COL_OT].astype(np.int64), P.TF_BAR_MS[tf], t_dec)
            parts.append(np.where((idx >= 0)[:, None], X[np.clip(idx, 0, len(X) - 1)], np.nan))
    else:
        for tf in ("3m", "1m"):
            parts.append(np.full((n, width[tf]), np.nan))
    M = np.concatenate(parts, axis=1).astype(np.float32)
    assert M.shape[1] == len(names), (sym, M.shape, len(names))
    h, l, c = f5[:, P.COL_H], f5[:, P.COL_L], f5[:, P.COL_C]
    o_sig = P.forward_outcomes(h, l, c, real, first=2, last=12)
    o_nul = P.forward_outcomes(h, l, c, real, tps=(1.5, 4.0), first=1, last=12)
    OS = np.column_stack([o_sig[k] for k in ("valid", "hit1.5", "net1.5", "hit2.0", "net2.0", "hit4.0", "net4.0", "trail_net", "mfe", "mae")])
    ON = np.column_stack([o_nul["valid"], o_nul["hit1.5"], o_nul["hit4.0"], o_nul["net1.5"], o_nul["trail_net"]])
    np.save(gdir / f"G_{sym}.npy", M)
    np.save(gdir / f"OT_{sym}.npy", ot5)
    np.save(gdir / f"F5_{sym}.npy", f5.astype(np.float64))
    np.save(gdir / f"RL_{sym}.npy", real)
    np.save(gdir / f"OS_{sym}.npy", OS.astype(np.float32))
    np.save(gdir / f"ON_{sym}.npy", ON.astype(np.float32))
    return sym


def load_sym(cache_dir: str, sym: str, *, mmap: bool = False):
    g = Path(cache_dir) / "grid"
    mm = "r" if mmap else None
    return (np.load(g / f"G_{sym}.npy", mmap_mode=mm), np.load(g / f"OT_{sym}.npy"), np.load(g / f"F5_{sym}.npy"))


# ------------------------------------------------------------------------------------------------ 3. olaylar
def ev_params(args) -> P.EventParams:
    return P.EventParams(win_bars=12, min_gain=args.ev_gain, green_min=args.ev_green, max_dd=args.ev_dd,
                         max_candle=args.ev_candle, min_q24=MIN_QUOTE, dedupe_hours=3.0)


def declusterize(events: list[dict], seed: int) -> dict:
    """Kümelenme: aynı 5 dk kovada (t0) CLUSTER_MIN'den çok olay = piyasa geneli küme. Birincil kümesiz küme:
    işaretli kovalarda tek (tohumlu rastgele — sonuca bakmadan) olay kalır. Duyarlılık: (b) HER kovada tek olay,
    (c) ±15 dk'lık kayan pencerede > CLUSTER_MIN olay bulunan kovalarda tek olay."""
    rng = np.random.default_rng(seed)
    by_t = collections.defaultdict(list)
    for k, e in enumerate(events):
        by_t[e["t0"]].append(k)
    keep_a = np.ones(len(events), dtype=bool)         # birincil
    keep_b = np.ones(len(events), dtype=bool)         # her kovada tek
    keep_c = np.ones(len(events), dtype=bool)         # ±15 dk pencere
    t_sorted = np.array(sorted(by_t))
    cnt_t = np.array([len(by_t[t]) for t in t_sorted])
    cum = np.concatenate([[0], np.cumsum(cnt_t)])
    for t in t_sorted:
        ks = by_t[t]
        pick = ks[int(rng.integers(len(ks)))]
        if len(ks) > CLUSTER_MIN:
            for k in ks:
                keep_a[k] = k == pick
        if len(ks) > 1:
            for k in ks:
                keep_b[k] = k == pick
        lo = np.searchsorted(t_sorted, t - 15 * 60_000, side="left"); hi = np.searchsorted(t_sorted, t + 15 * 60_000, side="right")
        if cum[hi] - cum[lo] > CLUSTER_MIN and len(ks) > 1:
            for k in ks:
                keep_c[k] = k == pick
    for k, e in enumerate(events):
        e["bucket_n"] = len(by_t[e["t0"]])
        e["cluster"] = e["bucket_n"] > CLUSTER_MIN
        e["keep"] = bool(keep_a[k])
        e["keep_b"] = bool(keep_b[k])
        e["keep_c"] = bool(keep_c[k])
    return {"keep_a": int(keep_a.sum()), "keep_b": int(keep_b.sum()), "keep_c": int(keep_c.sum()),
            "n_cluster_buckets": int(sum(1 for t in by_t if len(by_t[t]) > CLUSTER_MIN)),
            "cluster_buckets": sorted(((int(t), len(v)) for t, v in by_t.items() if len(v) > CLUSTER_MIN), key=lambda x: x[0])}


def stage_events(args) -> None:
    import csv
    cache = Path(args.cache_dir); out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    syms = list_syms(args.cache_dir, "d5")
    ep = ev_params(args)
    events: list[dict] = []; masks = {}
    t0 = time.time()
    for s in syms:
        f5 = P.fill_gaps(np.load(cache / "d5" / f"{s}.npy"), P.BAR_5M_MS)
        mask, det = P.event_mask(f5, ep, warm_bars=WARM_BARS)
        masks[s] = (np.flatnonzero(mask).astype(np.int32), det["e_star"][mask].astype(np.int16))
        events += P.find_events(s, f5, ep, warm_bars=WARM_BARS)
    events.sort(key=lambda e: (e["t0"], e["sym"]))
    dc = declusterize(events, args.seed)
    pickle.dump({"events": events, "masks": masks, "params": ep.__dict__, "decluster": dc}, open(cache / "events.pkl", "wb"))
    with open(out / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "t0_local", "t0_ms", "gain_pct", "dur_min", "green_share", "max_dd_pct", "max_candle_pct", "bucket_n", "cluster", "kept_primary"])
        for e in events:
            w.writerow([e["sym"], fmt_t(e["t0"], "%Y-%m-%d %H:%M"), e["t0"], f"{e['gain']:.2f}", e["dur_min"], f"{e['green']:.2f}",
                        f"{e['dd']:.2f}", f"{e['maxc']:.2f}", e["bucket_n"], int(e["cluster"]), int(e["keep"])])
    print(f"[events] toplam {len(events)}; birincil kümesiz {dc['keep_a']}; her-kovada-tek {dc['keep_b']}; ±15dk-pencere {dc['keep_c']}; "
          f"küme kovası {dc['n_cluster_buckets']} ({time.time() - t0:.0f} sn)", flush=True)


def load_events(cache_dir: str) -> dict:
    return pickle.load(open(Path(cache_dir) / "events.pkl", "rb"))


# ------------------------------------------------------------------------------------------------ 4. anlık görüntüler
def stage_snap(args) -> None:
    cache = Path(args.cache_dir)
    names = json.loads((cache / "grid_names.json").read_text(encoding="utf-8"))
    col = {nm: i for i, nm in enumerate(names)}
    E = load_events(args.cache_dir)
    events = E["events"]
    syms = list_syms(args.cache_dir, "d5")
    sid = {s: k for k, s in enumerate(syms)}
    rng = np.random.default_rng(args.seed)
    thr = np.log10(MIN_QUOTE)
    need = [col["5m.qv24_log10"], col["5m.rsi14"], col["1m.rsi14"], col["5m.tk_share3"], col["1m.tk_share_z3"], col["1m.tk_net12"]]
    t0 = time.time()
    # --- geçerli (taban) anlar
    valid: dict[str, np.ndarray] = {}
    day_of: dict[str, np.ndarray] = {}
    n_valid_total = 0
    for s in syms:
        M, ot, _ = load_sym(args.cache_dir, s, mmap=True)
        sub = np.asarray(M[:, need])
        n = len(ot)
        v = (np.arange(n) >= WARM_BARS) & (sub[:, 0] >= thr) & np.isfinite(sub[:, 1:]).all(axis=1)
        idx, es = E["masks"][s]
        cov = np.zeros(n, dtype=bool)
        for st, e in zip(idx, es):
            cov[max(st - 1, 0): min(n, st + int(e) + 1)] = True
        v &= ~cov
        vi = np.flatnonzero(v)
        valid[s] = vi
        day_of[s] = day_idx(ot[vi] + P.BAR_5M_MS)
        n_valid_total += len(vi)
    print(f"[snap] geçerli taban anı: {n_valid_total} ({time.time() - t0:.0f} sn)", flush=True)

    F = len(names)
    ev_rows = {0: [], 3: []}
    ev_meta = []
    mat_rows = []; mat_meta = []
    by_sym_ev = collections.defaultdict(list)
    for k, e in enumerate(events):
        by_sym_ev[e["sym"]].append(k)
    n_incomplete = 0
    for s, ks in by_sym_ev.items():
        M, ot, _ = load_sym(args.cache_dir, s, mmap=True)
        vi = valid[s]; dv = day_of[s]
        for k in ks:
            e = events[k]
            i0 = e["s"] - 1
            rows = []
            for off in OFFSETS:
                i = i0 + off
                rows.append(np.asarray(M[i]) if i < len(ot) else None)
            if any(r is None for r in rows) or not all(np.isfinite(r[need[1:]]).all() for r in rows):
                n_incomplete += 1
                complete = False
            else:
                complete = True
            # eşleşmiş taban (aynı sembol + aynı gün; ≥ 10 an yoksa sembolün tüm anları)
            sel = vi[dv == day_idx(e["t0"])] if len(vi) else vi
            pool = sel if len(sel) >= 10 else vi
            if complete and len(pool):
                kk = min(args.baseline_mult, len(pool))
                for i in rng.choice(pool, size=kk, replace=False):
                    mat_rows.append(np.asarray(M[i]))
                    mat_meta.append((sid[s], int(ot[i] + P.BAR_5M_MS), k))
            for off, r in zip(OFFSETS, rows):
                ev_rows[off].append(r if complete else np.full(F, np.nan, dtype=np.float32))
            ev_meta.append((k, sid[s], e["t0"], e["gain"], e["dur_min"], e["bucket_n"], int(e["keep"]), int(complete),
                            int(e["keep_b"]), int(e["keep_c"]), e["t_end"]))
    order = np.argsort([m[0] for m in ev_meta])
    ev_meta = np.array(ev_meta, dtype=float)[order]
    X0 = np.array(ev_rows[0], dtype=np.float32)[order]; X3 = np.array(ev_rows[3], dtype=np.float32)[order]
    Xm = np.array(mat_rows, dtype=np.float32); mm = np.array(mat_meta, dtype=np.int64)
    print(f"[snap] olay {len(ev_meta)} (eksik/taker-yok {n_incomplete}); eşleşmiş taban {len(Xm)} ({time.time() - t0:.0f} sn)", flush=True)

    # --- havuz örneği (tekdüze, tüm geçerli anlar)
    N = min(args.pool_n, n_valid_total)
    counts = np.array([len(valid[s]) for s in syms])
    cum = np.concatenate([[0], np.cumsum(counts)])
    glob = np.sort(rng.choice(n_valid_total, size=N, replace=False))
    sym_of = np.searchsorted(cum, glob, side="right") - 1
    Xp = np.empty((N, F), dtype=np.float32); pm = np.empty((N, 2), dtype=np.int64)
    for k in np.unique(sym_of):
        s = syms[k]
        M, ot, _ = load_sym(args.cache_dir, s, mmap=True)
        sel = np.flatnonzero(sym_of == k)
        rows = valid[s][glob[sel] - cum[k]]
        Xp[sel] = np.asarray(M[rows])
        pm[sel, 0] = k
        pm[sel, 1] = ot[rows] + P.BAR_5M_MS
    np.savez(cache / "snap.npz", names=np.array(names), syms=np.array(syms), ev_meta=ev_meta, X0=X0, X3=X3, Xm=Xm, mm=mm, Xp=Xp, pm=pm,
             n_valid_total=n_valid_total)
    print(f"[snap] havuz {N}; yazıldı ({time.time() - t0:.0f} sn)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="data,grid,events,snap")
    ap.add_argument("--tfs", default="5m,1m")
    ap.add_argument("--db-url", default="")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", default="work/pattern90")
    ap.add_argument("--liquid-frac", type=float, default=0.02)
    ap.add_argument("--baseline-mult", type=int, default=40)
    ap.add_argument("--pool-n", type=int, default=250_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--ev-gain", type=float, default=4.0)
    ap.add_argument("--ev-green", type=float, default=0.70)
    ap.add_argument("--ev-dd", type=float, default=1.5)
    ap.add_argument("--ev-candle", type=float, default=2.5)
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = globals().get(f"stage_{st}")
        if fn is None:
            sys.exit(f"bilinmeyen aşama: {st}")
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
