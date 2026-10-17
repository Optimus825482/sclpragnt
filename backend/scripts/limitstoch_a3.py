"""Çalışma A (3): ön sinyal / onaylı sinyal GİRİŞ sinyali olarak (gerçekçi doluş) + aynı çıkışlı rastgele giriş tabanları.

Her sembol için: sinyal kümeleri (12) → 60 dk tekilleştirme → rastgele girişler → 1 dk pencereler → 24 çıkış × 2 senaryo net.
İşlem düzeyi saklanmaz; GÜN BAŞINA toplamlar tutulur (n, Σnet, kazanan sayısı/toplamı, hit60) → work/limitstoch/a3_daily.pkl.
Senaryo P = 60 sn gecikme / %0,15 kayma (birincil); O = 0 sn / %0,05 (iyimser).

Rastgele taban türleri (kind):
  0 sinyal
  1 aynı sembol + aynı saat dilimi + aynı blok, herhangi bir HAM sinyalden ≥ 2 sa uzak (istenen tanım; kademe: 2 sa → 1 sa → 30 dk)
  2 aynı sembol + aynı blok, son 30 dk aralığı ±%25 (en az 0,4 pt) içinde (oynaklık eşl.), ≥ 2 sa uzak
  3 aynı sembol + aynı saat dilimi + aynı blok, DIŞLAMASIZ (koşulsuz an)
  4 oynaklık eşl. + dışlamasız
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402
from scripts.exit_sim_study import SymGrid  # noqa: E402

SETS = [(tf, lv, typ) for tf in ("5m", "1m", "15m") for lv in L.LEVELS for typ in ("pre", "conf")]
NK = 5
N_PER = {1: 2, 2: 1, 3: 1, 4: 1}
GAPS = (2 * 3_600_000, 3_600_000, 1_800_000)
FLUSH = 40_000
NSPEC = 24
D0 = int(L.day_idx(L.WINDOWS["ALL"][0]))
ND = int(L.day_idx(L.WINDOWS["ALL"][1])) - D0 + 1


class Agg:
    """(set, kind) → gün başına toplamlar."""

    def __init__(self):
        self.d = {}

    def get(self, sid, kind):
        k = (sid, kind)
        if k not in self.d:
            self.d[k] = {"n": np.zeros(ND), "hit15": np.zeros(ND), "hit10": np.zeros(ND), "ret60": np.zeros(ND),
                         "sP": np.zeros((ND, NSPEC)), "sO": np.zeros((ND, NSPEC)), "cP": np.zeros((ND, NSPEC)), "cO": np.zeros((ND, NSPEC)),
                         "pP": np.zeros((ND, NSPEC)), "pO": np.zeros((ND, NSPEC)), "tier": np.zeros(3)}
        return self.d[k]

    def add(self, sid, kind, day, netP, netO, hit15, hit10, ret60):
        a = self.get(sid, kind)
        dd = day - D0
        a["n"] += np.bincount(dd, minlength=ND)
        a["hit15"] += np.bincount(dd, weights=hit15.astype(float), minlength=ND)
        a["hit10"] += np.bincount(dd, weights=hit10.astype(float), minlength=ND)
        a["ret60"] += np.bincount(dd, weights=ret60, minlength=ND)
        for key_s, key_c, key_p, net in (("sP", "cP", "pP", netP), ("sO", "cO", "pO", netO)):
            pos = net > 0
            posv = np.where(pos, net, 0.0)
            for j in range(NSPEC):
                a[key_s][:, j] += np.bincount(dd, weights=net[:, j], minlength=ND)
                a[key_c][:, j] += np.bincount(dd, weights=pos[:, j].astype(float), minlength=ND)
                a[key_p][:, j] += np.bincount(dd, weights=posv[:, j], minlength=ND)


class Buf:
    def __init__(self, specs, agg):
        self.specs = specs; self.agg = agg
        self.meta = {k: [] for k in ("set", "kind", "day")}
        self.w = {d: [[], [], [], []] for d in (60, 0)}
        self.n = 0
        self.sim_s = 0.0

    def add(self, meta: dict, wins: dict):
        for k in self.meta:
            self.meta[k].append(meta[k])
        for d in (60, 0):
            for i in range(4):
                self.w[d][i].append(wins[d][i])
        self.n += len(meta["day"])
        if self.n >= FLUSH:
            self.flush()

    def flush(self):
        if self.n == 0:
            return
        t0 = time.time()
        W = {d: tuple(np.ascontiguousarray(np.concatenate(self.w[d][i]).T) for i in range(4)) for d in (60, 0)}
        netP = L.sim_all(W[60], self.specs, L.SCENARIOS["P"][1]).astype(float)
        netO = L.sim_all(W[0], self.specs, L.SCENARIOS["O"][1]).astype(float)
        hit15 = L.hit_within(W[60][1], 60, 1.5); hit10 = L.hit_within(W[60][1], 60, 1.0)
        ret60 = (W[60][3][59].astype(float) - 1.0) * 100.0
        M = {k: np.concatenate(v) for k, v in self.meta.items()}
        for sid in np.unique(M["set"]):
            for kind in range(NK):
                m = (M["set"] == sid) & (M["kind"] == kind)
                if m.any():
                    self.agg.add(int(sid), kind, M["day"][m].astype(np.int64), netP[m], netO[m], hit15[m], hit10[m], ret60[m])
        self.sim_s += time.time() - t0
        self.meta = {k: [] for k in ("set", "kind", "day")}
        self.w = {d: [[], [], [], []] for d in (60, 0)}
        self.n = 0


def tier_pick(rng, bins_by_tier, key, n):
    for tier, d in enumerate(bins_by_tier):
        c = d.get(key)
        if c is not None and len(c) >= 1:
            return rng.choice(c, size=n, replace=len(c) < n), tier
    return None, -1


def make_bins(ok_masks, keys):
    out = []
    for ok in ok_masks:
        idx = np.flatnonzero(ok)
        kk = keys[idx]
        order = np.argsort(kk, kind="stable")
        idx = idx[order]; kk = kk[order]
        ub, st = np.unique(kk, return_index=True)
        en = np.append(st[1:], len(kk))
        out.append({int(u): idx[a:b] for u, a, b in zip(ub, st, en)})
    return out


def main():
    t_start = time.time()
    specs = L.exit_set()
    syms = L.symbols("5m")
    agg = Agg()
    buf = Buf(specs, agg)
    rng_master = np.random.default_rng(29)
    lo_all, hi_all = L.WINDOWS["ALL"]
    miss = {}
    for si, sym in enumerate(syms):
        a1 = L.load_arr("1m", sym)
        if len(a1) < 400:
            continue
        ot1 = a1[:, 0].astype(np.int64)
        o1, h1, l1, c1 = a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4]
        liq = L.Liq(sym)
        inds = {tf: L.get_ind(tf, sym) for tf in ("5m", "1m", "15m")}
        rng = np.random.default_rng(rng_master.integers(1 << 31))
        g = np.arange(-(-lo_all // 300_000) * 300_000, hi_all + 1, 300_000, dtype=np.int64)
        j = np.searchsorted(ot1, g, side="left")
        jc = np.minimum(j, len(ot1) - 1)
        okg = (j < len(ot1)) & ((ot1[jc] - g) <= 5 * 60_000) & (g + (L.W + 5) * 60_000 <= ot1[-1]) & liq.liquid(g)
        g_hour = L.hour_idx(g); g_blk = L.block_of(g).astype(np.int64)
        okg &= g_blk >= 0
        sgrid = SymGrid(ot1, h1, l1, c1, np.zeros(0, dtype=np.int64))
        r30g = sgrid.range30(g)
        key_hb = g_blk * 24 + g_hour
        bins_free = make_bins([okg], key_hb)[0]                  # kind 3 (dışlamasız, saat+blok)
        # kind 4: blok içinde r30'a göre sıralı adaylar
        vm = {}
        for b in range(3):
            ix = np.flatnonzero(okg & (g_blk == b) & np.isfinite(r30g))
            o = np.argsort(r30g[ix], kind="stable")
            vm[b] = (ix[o], r30g[ix][o])
        for sid, (tf, lv, typ) in enumerate(SETS):
            ind = inds[tf]
            raw = (L.pre_times(ind, tf, lv) if typ == "pre" else L.conf_times(ind, tf, lv))
            raw = np.sort(raw)
            t = raw[(raw >= lo_all) & (raw <= hi_all)]
            t = t[liq.liquid(t)]
            t = t[L.dedupe_gap(t)]
            t = t[L.block_of(t) >= 0]
            if len(t) == 0:
                continue
            sb = L.block_of(t).astype(np.int64); sh = L.hour_idx(t)
            if len(raw):
                k = np.searchsorted(raw, g)
                dmin = np.minimum(np.abs(g - raw[np.minimum(k, len(raw) - 1)]), np.abs(g - raw[np.maximum(k - 1, 0)]))
            else:
                dmin = np.full(len(g), 10 ** 12)
            bins1 = make_bins([okg & (dmin >= gp) for gp in GAPS], key_hb)
            r_sig = sgrid.range30(t)
            times = [t]; kinds = [np.zeros(len(t), dtype=np.int8)]
            for i in range(len(t)):
                key = int(sb[i]) * 24 + int(sh[i])
                pick, tier = tier_pick(rng, bins1, key, N_PER[1])
                if pick is not None:
                    times.append(g[pick]); kinds.append(np.full(N_PER[1], 1, dtype=np.int8))
                    agg.get(sid, 1)["tier"][tier] += N_PER[1]
                else:
                    miss[(sid, 1)] = miss.get((sid, 1), 0) + 1
                c3 = bins_free.get(key)
                if c3 is not None and len(c3):
                    times.append(g[rng.choice(c3, size=1)]); kinds.append(np.full(1, 3, dtype=np.int8))
                else:
                    miss[(sid, 3)] = miss.get((sid, 3), 0) + 1
                r = r_sig[i]
                if np.isfinite(r):
                    ix, rs = vm[int(sb[i])]
                    tol = max(0.25 * r, 0.4)
                    a = np.searchsorted(rs, r - tol, side="left"); b = np.searchsorted(rs, r + tol, side="right")
                    cand = ix[a:b]
                    if len(cand) >= 8:
                        times.append(g[rng.choice(cand, size=1)]); kinds.append(np.full(1, 4, dtype=np.int8))
                        cd = cand[dmin[cand] >= GAPS[0]]
                        tier2 = 0
                        if len(cd) < 8:
                            cd = cand[dmin[cand] >= GAPS[1]]; tier2 = 1
                            if len(cd) < 8:
                                cd = cand[dmin[cand] >= GAPS[2]]; tier2 = 2
                        if len(cd) >= 8:
                            times.append(g[rng.choice(cd, size=1)]); kinds.append(np.full(1, 2, dtype=np.int8))
                            agg.get(sid, 2)["tier"][tier2] += 1
                        else:
                            miss[(sid, 2)] = miss.get((sid, 2), 0) + 1
                    else:
                        miss[(sid, 4)] = miss.get((sid, 4), 0) + 1
                        miss[(sid, 2)] = miss.get((sid, 2), 0) + 1
                else:
                    miss[(sid, 4)] = miss.get((sid, 4), 0) + 1
                    miss[(sid, 2)] = miss.get((sid, 2), 0) + 1
            tt = np.concatenate(times); kind = np.concatenate(kinds)
            wins = {}
            okall = np.ones(len(tt), dtype=bool)
            for d in (60, 0):
                idx, ok = X.entry_index(ot1, tt, d)
                O, H, Lw, C, ref, cov = X.gather_windows(ot1, o1, h1, l1, c1, idx, L.W)
                wins[d] = (O, H, Lw, C)
                okall &= ok & cov
            meta = {"set": np.full(int(okall.sum()), sid, dtype=np.int16), "kind": kind[okall], "day": L.day_idx(tt[okall]).astype(np.int32)}
            wins = {d: tuple(x[okall] for x in wins[d]) for d in wins}
            buf.add(meta, wins)
        if si % 20 == 0:
            print("[a3] %d/%d sembol (%.0f sn; sim %.0f sn)" % (si, len(syms), time.time() - t_start, buf.sim_s), flush=True)
    buf.flush()
    pickle.dump({"agg": agg.d, "specs": [s.name for s in specs], "sets": ["%s|%d|%s" % s for s in SETS], "D0": D0, "ND": ND, "miss": miss},
                open(L.WORK / "a3_daily.pkl", "wb"))
    print("[a3] bitti %.0f sn; eksik %s" % (time.time() - t_start, miss), flush=True)


if __name__ == "__main__":
    main()
