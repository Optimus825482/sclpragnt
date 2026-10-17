"""İndikatör filtresi v2 — YENİ kütüphane (indicators_ext2) özellikleri, Hız Avcısı (HA) olay anında (2026-10-17, çevrimdışı; canlı koda BAĞLANMAZ, DB'ye yalnız OKUR).

`indfilter_feats.py` ile aynı mantık: her olay için yalnız sinyal anından ÖNCE kapanmış son 5 dk / 15 dk barının özellikleri (5m: gün/seans ailesi dâhil; 15m: hariç).
Çıktı: work/indfilter/feats2_ha.npz (names, X float32).  Nedensellik: `--verify N` (kesilmiş serilerle yeniden hesap).

Kullanım (backend/): DATABASE_URL=... python scripts/indfilter2_feats.py --pop ha [--verify 100]
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rescan import indicators_ext2 as I2  # noqa: E402
from app.rescan import pattern_study as PS  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402
from scripts.indfilter_feats import BAR15, BAR5, STALE_BARS, to_arr, truncate_series  # noqa: E402

DROP15 = ("x2_day",)


def symbol_feats(series: dict, t_ms: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for tf, bar, stale, drop in (("5m", BAR5, STALE_BARS, ()), ("15m", BAR15, 2, DROP15)):
        arr = PS.fill_gaps(to_arr(series[tf]), bar)
        idx = PS.snapshot_index(arr[:, 0].astype(np.int64), bar, t_ms, stale)
        ok = idx >= 0
        ii = np.clip(idx, 0, len(arr) - 1)
        names, X = I2.compute_all(arr, tf, drop)
        for j, nm in enumerate(names):
            out[nm] = np.where(ok, X[ii, j], np.nan)
    return out


def build(pop: str = "ha", log=print) -> Path:
    ev = pickle.load(open(K.OUT / ("events_%s.pkl" % pop), "rb"))
    P = K.load_prep(pop)
    n = len(ev["t_ms"])
    ok_ev = P["ev_ok"].astype(bool)
    conn = K.get_conn()
    cols: dict[str, np.ndarray] = {}
    syms = sorted(set(ev["sym"][ok_ev].tolist()))
    t0 = time.time()
    for si, s in enumerate(syms):
        series = {tf: K.load_series(conn, s, tf) for tf in ("5m", "15m")}
        if any(v is None or len(v["ot"]) < 60 for v in series.values()):
            continue
        idx = np.flatnonzero((ev["sym"] == s) & ok_ev)
        F = symbol_feats(series, ev["t_ms"][idx])
        for k, v in F.items():
            if k not in cols:
                cols[k] = np.full(n, np.nan, dtype=np.float32)
            cols[k][idx] = v.astype(np.float32)
        if (si + 1) % 25 == 0:
            log("[feats2 %s] %d/%d sembol (%.0f sn)" % (pop, si + 1, len(syms), time.time() - t0))
    conn.close()
    names = sorted(cols)
    X_ = np.column_stack([cols[k] for k in names])
    path = K.OUT / ("feats2_%s.npz" % pop)
    np.savez_compressed(path, names=np.array(names), X=X_)
    log("[feats2 %s] %d özellik x %d olay -> %s (%.0f sn)" % (pop, len(names), n, path.name, time.time() - t0))
    return path


def verify(pop: str, n: int, seed: int = 5, log=print) -> int:
    """Nedensellik testi: n rastgele olay için özellikleri (a) tam seri, (b) t anında kesilmiş seri ile hesapla; farklılar raporlanır."""
    ev = pickle.load(open(K.OUT / ("events_%s.pkl" % pop), "rb"))
    P = K.load_prep(pop)
    ok_ev = np.flatnonzero(P["ev_ok"].astype(bool))
    rng = np.random.default_rng(seed)
    pick = rng.choice(ok_ev, size=min(n, len(ok_ev)), replace=False)
    conn = K.get_conn()
    bad: dict[str, int] = {}
    tot = 0
    for i in pick:
        s = str(ev["sym"][i])
        t = int(ev["t_ms"][i])
        series = {tf: K.load_series(conn, s, tf) for tf in ("1m", "5m", "15m")}
        full = symbol_feats(series, np.array([t], dtype=np.int64))
        tr = symbol_feats(truncate_series(series, t), np.array([t], dtype=np.int64))
        for k, v in tr.items():
            a, b = float(full[k][0]), float(v[0])
            tot += 1
            same = (np.isnan(a) and np.isnan(b)) or abs(a - b) <= 1e-4 * max(1.0, abs(a))
            if not same:
                bad[k] = bad.get(k, 0) + 1
    conn.close()
    log("[verify2 %s] %d olay, %d karşılaştırma; farklı özellik sayısı %d" % (pop, len(pick), tot, len(bad)))
    for k, c in sorted(bad.items(), key=lambda kv: -kv[1])[:40]:
        log("   FARKLI: %s (%d/%d olay)" % (k, c, len(pick)))
    (K.OUT / ("verify2_%s.txt" % pop)).write_text("olay %d; karsilastirma %d; farkli ozellik %d" % (len(pick), tot, len(bad)) + chr(10) + chr(10).join("%s %d" % kv for kv in sorted(bad.items())), encoding="utf-8")
    return len(bad)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pop", default="ha")
    ap.add_argument("--verify", type=int, default=0)
    args = ap.parse_args(argv)
    if args.verify:
        verify(args.pop, args.verify, log=lambda m: print(m, flush=True))
        return 0
    build(args.pop, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
