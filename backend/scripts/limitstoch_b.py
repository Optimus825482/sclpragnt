"""Çalışma B: bildirim fiyatının ALTINDA limit giriş (+ StochRSI desteği) — gerçekçi doluşlu geriye dönük test.

Aşamalar (--stages):
  rows   kaynaklar (HA / NOTIF_all / NOTIF_trend / LIVE) → sinyal + rastgele anlar → work/limitstoch/b_rows_<kaynak>.pkl
  sim    her giriş kuralı hücresi × 24 çıkış → work/limitstoch/b_res_<kaynak>_<senaryo>.pkl

Giriş kuralları (hücreler):
  M            piyasa: sinyal + gecikme sonrası ilk 1 dk açılışı (taker, kayma)           [referans]
  L d V        limit = fiyat × (1 − d%), V dk geçerli; 1 dk düşüğü KESİNLİKLE altına inerse dolar (maker, kayma yok, dolum = limit fiyatı)
  LK d V       L + 5 dk StochRSI K < 50 (sinyal anında, son kapanmış 5 dk barı)
  C lv d V     V dk içinde 1 dk ya da 5 dk StochRSI ön sinyali (seviye lv) → ÖNCEKİ 1 dk'dan sonraki ilk 1 dk açılışında piyasa girişi
               (gecikme + kayma); d > 0 ise giriş açılışı ≤ fiyat × (1 − d%) olmalı
  LC lv d V    L dolumu VE dolumdan sonraki 5 dk içinde ön sinyal → girişi dolumda değil ön sinyalde (piyasa) yap
Çıkışlar: `limitstoch_lib.exit_set()` (24 hücre). Limit dolumunda dolum barının YALNIZ düşüğü kullanılır (yüksek = limit; kötümser)."""
from __future__ import annotations

import argparse
import collections
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402

SRC_NAMES = ("HA", "NOTIF_all", "NOTIF_trend", "LIVE")
M_GRID = 61
N_RND = 2
GAPS = (2 * 3_600_000, 3_600_000, 1_800_000)
D_LIST = (0.3, 0.6, 1.0, 1.5)
V_LIST = (15, 30, 60)
D_GATE = (0.0, 0.3, 0.6, 1.0)


def cell_list() -> list[tuple]:
    cells: list[tuple] = [("M",)]
    for d in D_LIST:
        for v in V_LIST:
            cells.append(("L", d, v))
    for d in D_LIST:
        for v in V_LIST:
            cells.append(("LK", d, v))
    for lv in L.LEVELS:
        for d in D_GATE:
            for v in V_LIST:
                cells.append(("C", lv, d, v))
    for lv in L.LEVELS:
        for d in D_LIST:
            for v in V_LIST:
                cells.append(("LC", lv, d, v))
    return cells


def cname(c: tuple) -> str:
    if c[0] == "M":
        return "M"
    if c[0] in ("L", "LK"):
        return "%s d%g V%d" % c
    return "%s lv%d d%g V%d" % c


LIMIT_KINDS = ("L", "LK")


# ------------------------------------------------------------------------------------------------ kaynaklar
def get_conn():
    import psycopg
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def episodes(rows: list[dict], gap_min: int = 60) -> list[dict]:
    last: dict[str, int] = {}
    out = []
    for r in sorted(rows, key=lambda r: r["t"]):
        if r["sym"] not in last or r["t"] - last[r["sym"]] >= gap_min * 60_000:
            out.append(r)
            last[r["sym"]] = r["t"]
    return out


def build_sources(jsonl: str) -> dict:
    from scripts.exit_sim_study import ha_events
    lo, hi = L.WINDOWS["ALL"]
    src: dict = {}
    ev, ticks = ha_events(jsonl, lo, hi)
    ev = [{"sym": e["sym"], "t": e["t"], "price": e["price"]} for e in ev]
    src["HA"] = {"ev": ev, "ticks": {s: np.sort(np.array(v, dtype=np.int64)) for s, v in ticks.items()}}
    conn = get_conn()
    w30 = L.WINDOWS["W30"]
    rows = conn.execute("SELECT symbol, detected_at, price, mode FROM monitoring_notifications WHERE detected_at >= %s AND detected_at <= %s ORDER BY detected_at",
                        (w30[0] / 1000, w30[1] / 1000)).fetchall()
    all_t: dict[str, list[int]] = collections.defaultdict(list)
    raw = []
    for s, da, pr, mode in rows:
        t = int(da * 1000)
        all_t[s].append(t)
        raw.append({"sym": s, "t": t, "price": float(pr) if pr is not None else float("nan"), "mode": mode or ""})
    ticks_n = {s: np.sort(np.array(v, dtype=np.int64)) for s, v in all_t.items()}
    src["NOTIF_all"] = {"ev": episodes(raw), "ticks": ticks_n}
    src["NOTIF_trend"] = {"ev": episodes([r for r in raw if r["mode"] == "trend_devam"]), "ticks": ticks_n}
    b3 = L.WINDOWS["B3"]
    cand = conn.execute("SELECT symbol, created_at, price FROM velocity_candidates WHERE candidate_id NOT LIKE 'rescan:%%' AND passes AND rank <= 10 "
                        "AND created_at >= %s AND created_at <= %s ORDER BY created_at", (b3[0] / 1000, b3[1] / 1000)).fetchall()
    t_c: dict[str, list[int]] = collections.defaultdict(list)
    raw = []
    for s, ca, pr in cand:
        t = int(ca * 1000)
        t_c[s].append(t)
        raw.append({"sym": s, "t": t, "price": float(pr) if pr is not None else float("nan")})
    src["LIVE"] = {"ev": episodes(raw), "ticks": {s: np.sort(np.array(v, dtype=np.int64)) for s, v in t_c.items()}}
    conn.close()
    return src


def frame_of(name: str, t: np.ndarray) -> np.ndarray:
    """0/1/2 = B1/B2/B3 çerçevesi; 3 = W30 çerçevesi."""
    if name == "HA":
        return L.block_of(t).astype(np.int8)
    if name == "LIVE":
        return np.where(L.window_mask(t, "B3"), 2, -1).astype(np.int8)
    return np.where(L.window_mask(t, "W30"), 3, -1).astype(np.int8)


FRAME_RANGE = {0: L.WINDOWS["B1"], 1: L.WINDOWS["B2"], 2: L.WINDOWS["B3"], 3: L.WINDOWS["W30"]}


def make_rows(name: str, s: dict, syms: list[str], seed: int = 31) -> dict:
    """Sinyal satırları + rastgele satırlar (aynı sembol, aynı saat dilimi, aynı çerçeve, herhangi bir tick'ten ≥ gap uzak, likit)."""
    rng = np.random.default_rng(seed)
    by_sym: dict[str, list[dict]] = collections.defaultdict(list)
    for e in s["ev"]:
        by_sym[e["sym"]].append(e)
    cols = {k: [] for k in ("sym", "kind", "t", "p0", "frame", "pair")}
    n_sig = 0
    miss = collections.Counter()
    tier_used = collections.Counter()
    for sym, evs in sorted(by_sym.items()):
        if sym not in syms:
            miss["sembol_yok"] += len(evs)
            continue
        a1 = L.load_arr("1m", sym)
        if len(a1) < 400:
            continue
        ot = a1[:, 0].astype(np.int64); c = a1[:, 4]
        t = np.array([e["t"] for e in evs], dtype=np.int64)
        pr = np.array([e["price"] for e in evs], dtype=float)
        fr = frame_of(name, t)
        # varsayılan fiyat: t'den önceki son KAPANMIŞ 1 dk barının kapanışı
        j = np.searchsorted(ot, t, side="left") - 1
        jc = np.maximum(j, 0)
        px_bar = np.where((j >= 0) & (t - (ot[jc] + 60_000) <= 120_000), c[jc], np.nan)
        p0 = np.where(np.isfinite(pr) & (pr > 0), pr, px_bar)
        okr = (fr >= 0) & np.isfinite(p0) & (t + (M_GRID + L.W + 15) * 60_000 <= ot[-1])
        miss["sinyal_atlanan"] += int((~okr).sum())
        t, p0, fr = t[okr], p0[okr], fr[okr]
        base_i = n_sig + np.arange(len(t))
        n_sig += len(t)
        for k, v in (("sym", np.full(len(t), syms.index(sym), dtype=np.int16)), ("kind", np.zeros(len(t), dtype=np.int8)), ("t", t),
                     ("p0", p0), ("frame", fr), ("pair", base_i)):
            cols[k].append(v)
        if len(t) == 0:
            continue
        # rastgele adaylar
        ticks = s["ticks"].get(sym, np.zeros(0, dtype=np.int64))
        from scripts.exit_sim_study import SymGrid
        sgrid = SymGrid(ot, a1[:, 2], a1[:, 3], c, ticks)
        r_sig = sgrid.range30(t)
        for f in sorted(set(fr.tolist())):
            lo, hi = FRAME_RANGE[f]
            g = np.arange(-(-lo // 300_000) * 300_000, hi + 1, 300_000, dtype=np.int64)
            jj = np.searchsorted(ot, g, side="left")
            jjc = np.minimum(jj, len(ot) - 1)
            okg = (jj < len(ot)) & ((ot[jjc] - g) <= 5 * 60_000) & (g + (M_GRID + L.W + 15) * 60_000 <= ot[-1])
            if len(ticks):
                k = np.searchsorted(ticks, g)
                dmin = np.minimum(np.abs(g - ticks[np.minimum(k, len(ticks) - 1)]), np.abs(g - ticks[np.maximum(k - 1, 0)]))
            else:
                dmin = np.full(len(g), 10 ** 12)
            hrs = L.hour_idx(g)
            sel = np.flatnonzero(fr == f)
            sig_h = L.hour_idx(t[sel])
            for ii, hh in zip(sel, sig_h):
                got = None
                for gp in GAPS:
                    cand = np.flatnonzero(okg & (dmin >= gp) & (hrs == hh))
                    if len(cand) >= 1:
                        got = rng.choice(cand, size=N_RND, replace=len(cand) < N_RND)
                        tier_used[gp] += 1
                        break
                if got is None:
                    miss["rastgele_bulunamadi"] += 1
                    continue
                tr = g[got]
                jr = np.searchsorted(ot, tr, side="left") - 1
                pxr = c[np.maximum(jr, 0)]
                for k2, v2 in (("sym", np.full(N_RND, syms.index(sym), dtype=np.int16)), ("kind", np.ones(N_RND, dtype=np.int8)), ("t", tr),
                               ("p0", pxr), ("frame", np.full(N_RND, f, dtype=np.int8)), ("pair", np.full(N_RND, base_i[ii]))):
                    cols[k2].append(v2)
            # dışlamasız, aynı saat dilimi (kind=3): koşulsuz an
            for ii, hh in zip(sel, sig_h):
                cand = np.flatnonzero(okg & (hrs == hh))
                if len(cand) < 1:
                    miss["rnd3_bulunamadi"] += 1
                    continue
                got = rng.choice(cand, size=N_RND, replace=len(cand) < N_RND)
                tr = g[got]
                jr = np.searchsorted(ot, tr, side="left") - 1
                pxr = c[np.maximum(jr, 0)]
                for k2, v2 in (("sym", np.full(N_RND, syms.index(sym), dtype=np.int16)), ("kind", np.full(N_RND, 3, dtype=np.int8)), ("t", tr),
                               ("p0", pxr), ("frame", np.full(N_RND, f, dtype=np.int8)), ("pair", np.full(N_RND, base_i[ii]))):
                    cols[k2].append(v2)
            # oynaklığı eşleşmiş rastgele: kind=2 (≥ gap uzak) ve kind=4 (dışlamasız): aynı sembol, herhangi bir saat, son 30 dk aralığı ±%25 (en az 0,4 pt)
            r30g = sgrid.range30(g)
            fin = np.isfinite(r30g)
            for ii in sel:
                r = r_sig[ii]
                if not np.isfinite(r):
                    miss["rndv_oynaklik_yok"] += 1
                    continue
                tol = max(0.25 * r, 0.4)
                near = okg & fin & (np.abs(r30g - r) <= tol)
                got = None
                for gp in GAPS:
                    cand = np.flatnonzero(near & (dmin >= gp))
                    if len(cand) >= 8:
                        got = rng.choice(cand, size=N_RND, replace=False)
                        break
                picks = [(2, got)]
                cand4 = np.flatnonzero(near)
                picks.append((4, rng.choice(cand4, size=N_RND, replace=False) if len(cand4) >= 8 else None))
                for kd, gt in picks:
                    if gt is None:
                        miss["rndv%d_bulunamadi" % kd] += 1
                        continue
                    tr = g[gt]
                    jr = np.searchsorted(ot, tr, side="left") - 1
                    pxr = c[np.maximum(jr, 0)]
                    for k2, v2 in (("sym", np.full(N_RND, syms.index(sym), dtype=np.int16)), ("kind", np.full(N_RND, kd, dtype=np.int8)), ("t", tr),
                                   ("p0", pxr), ("frame", np.full(N_RND, f, dtype=np.int8)), ("pair", np.full(N_RND, base_i[ii]))):
                        cols[k2].append(v2)
    R = {k: np.concatenate(v) for k, v in cols.items()}
    R["day"] = L.day_idx(R["t"]).astype(np.int32)
    R["syms"] = np.array(syms)
    R["miss"] = dict(miss)
    R["tier_used"] = {int(k): int(v) for k, v in tier_used.items()}
    return R


# ------------------------------------------------------------------------------------------------ giriş belirtimleri
def first_in(times: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    out = np.full(len(lo), -1, dtype=np.int64)
    if len(times) == 0:
        return out
    i = np.searchsorted(times, lo, side="left")
    ic = np.minimum(i, len(times) - 1)
    ok = (i < len(times)) & (times[ic] <= hi)
    out[ok] = times[ic][ok]
    return out


def entry_specs(R: dict, cells: list[tuple], delay: float, mm: dict) -> tuple[dict, dict]:
    """Her hücre için (satır_indeksi, 1 dk bar indeksi (sembol dizisinde), limit_fiyat_mutlak|nan, sembol_no). Ayrıca satır ekstraları."""
    syms = [str(s) for s in R["syms"]]
    n = len(R["t"])
    order = np.argsort(R["sym"], kind="stable")
    ent = {c: {"row": [], "ie": [], "lim": [], "sym": []} for c in cells}
    extra = {"ret60": np.full(n, np.nan), "c59": np.full(n, np.nan), "k5": np.full(n, np.nan), "ok": np.zeros(n, dtype=bool)}
    fi_store = {c: np.full(n, -1, dtype=np.int16) for c in cells if c[0] in LIMIT_KINDS or c[0] == "LC"}
    sym_sorted = R["sym"][order]
    cuts = np.flatnonzero(np.diff(sym_sorted)) + 1
    groups = np.split(order, cuts)
    for gi, rows in enumerate(groups):
        if len(rows) == 0:
            continue
        sno = int(R["sym"][rows[0]]); sym = syms[sno]
        ot, o, h, l, c = mm[sym]
        t = R["t"][rows]; p0 = R["p0"][rows]
        i0, ok0 = X.entry_index(ot, t, delay)
        ok0 &= (t + (M_GRID + L.W + 10) * 60_000 <= ot[-1])
        low, close, present = L.gather_grid(ot, l, c, i0, M_GRID)
        ref = o[i0]
        extra["ok"][rows] = ok0
        extra["c59"][rows] = close[:, 59]
        extra["ret60"][rows] = (close[:, 59] / p0 - 1.0) * 100.0
        ind5 = L.get_ind("5m", sym)
        close5 = ind5["ot"] + 300_000
        j5 = np.searchsorted(close5, t, side="right") - 1
        k5 = np.where(j5 >= 0, ind5["k"][np.maximum(j5, 0)].astype(float), np.nan)
        extra["k5"][rows] = k5
        ind1 = L.get_ind("1m", sym)
        ps = {lv: L.union_sorted(L.pre_times(ind1, "1m", lv), L.pre_times(ind5, "5m", lv)) for lv in L.LEVELS}
        for cell in cells:
            kind = cell[0]
            if kind == "M":
                m = ok0
                ent[cell]["row"].append(rows[m]); ent[cell]["ie"].append(i0[m]); ent[cell]["lim"].append(np.full(int(m.sum()), np.nan))
                ent[cell]["sym"].append(np.full(int(m.sum()), sno))
                continue
            if kind in ("L", "LK", "LC"):
                d, V = (cell[1], cell[2]) if kind != "LC" else (cell[2], cell[3])
                lim = p0 * (1.0 - d / 100.0)
                cond = present[:, :V] & (low[:, :V] < lim[:, None])
                fill = ok0 & cond.any(axis=1)
                fi = cond.argmax(axis=1)
                if cell in fi_store:
                    fi_store[cell][rows] = np.where(fill, fi, -1)
                fill_t = ot[i0] + 60_000 * fi
                if kind == "L" or kind == "LK":
                    m = fill & ((k5 < 50.0) if kind == "LK" else True)
                    ie = np.searchsorted(ot, fill_t[m])
                    ent[cell]["row"].append(rows[m]); ent[cell]["ie"].append(ie); ent[cell]["lim"].append(lim[m])
                    ent[cell]["sym"].append(np.full(int(m.sum()), sno))
                else:
                    lv = cell[1]
                    lo_c = fill_t + 60_000
                    tc = first_in(ps[lv], lo_c, lo_c + 300_000)
                    m = fill & (tc >= 0)
                    ie2, ok2 = X.entry_index(ot, tc[m], delay)
                    m2 = np.zeros(len(m), dtype=bool)
                    m2[np.flatnonzero(m)[ok2]] = True
                    ie3 = ie2[ok2]
                    ok3 = ot[ie3] + (L.W + 2) * 60_000 <= ot[-1]
                    m2[np.flatnonzero(m2)[~ok3]] = False
                    ent[cell]["row"].append(rows[m2]); ent[cell]["ie"].append(ie3[ok3]); ent[cell]["lim"].append(np.full(int(m2.sum()), np.nan))
                    ent[cell]["sym"].append(np.full(int(m2.sum()), sno))
                continue
            if kind == "C":
                lv, d, V = cell[1], cell[2], cell[3]
                tc = first_in(ps[lv], t, t + V * 60_000)
                m = ok0 & (tc >= 0)
                ie2, ok2 = X.entry_index(ot, tc[m], delay)
                idx_m = np.flatnonzero(m)[ok2]
                ie3 = ie2[ok2]
                keep = ot[ie3] + (L.W + 2) * 60_000 <= ot[-1]
                if d > 0:
                    keep &= o[ie3] <= p0[idx_m] * (1.0 - d / 100.0)
                ent[cell]["row"].append(rows[idx_m[keep]]); ent[cell]["ie"].append(ie3[keep]); ent[cell]["lim"].append(np.full(int(keep.sum()), np.nan))
                ent[cell]["sym"].append(np.full(int(keep.sum()), sno))
    for c in cells:
        for k in ("row", "ie", "lim", "sym"):
            ent[c][k] = np.concatenate(ent[c][k]) if ent[c][k] else np.zeros(0)
        for k in ("row", "ie", "sym"):
            ent[c][k] = ent[c][k].astype(np.int64)
    return ent, {"extra": extra, "fi": fi_store}


def sim_entries(e: dict, syms: list[str], mm: dict, specs, slip: float, limit: bool) -> np.ndarray:
    """e: row/ie/lim/sym → net (n, len(specs)) float32. Satır sırası e'dekiyle aynı."""
    n = len(e["row"])
    out = np.full((n, len(specs)), np.nan, dtype=np.float32)
    if n == 0:
        return out
    order = np.argsort(e["sym"], kind="stable")
    ss = e["sym"][order]
    cuts = np.flatnonzero(np.diff(ss)) + 1
    parts = np.split(order, cuts)
    Os, Hs, Ls, Cs, idxs = [], [], [], [], []
    for p in parts:
        sno = int(e["sym"][p[0]])
        ot, o, h, l, c = mm[syms[sno]]
        O, H, Lw, C, ref, cov = X.gather_windows(ot, o, h, l, c, e["ie"][p], L.W)
        if limit:
            lr = (e["lim"][p] / ref).astype(np.float32)
            O[:, 0] = lr
            H[:, 0] = lr
            Lw[:, 0] = np.minimum(Lw[:, 0], lr)
        Os.append(O[cov]); Hs.append(H[cov]); Ls.append(Lw[cov]); Cs.append(C[cov]); idxs.append(p[cov])
    if not idxs:
        return out
    idx = np.concatenate(idxs)
    W4 = tuple(np.ascontiguousarray(np.concatenate(x).T) for x in (Os, Hs, Ls, Cs))
    net = L.sim_all(W4, specs, slip, entry_slip=0.0 if limit else None)
    out[idx] = net
    return out


def load_mm(syms: list[str], need: set[str]) -> dict:
    mm = {}
    for s in need:
        a = np.load(L.CACHE / "1m" / (s + ".npy"), mmap_mode="r")
        mm[s] = (np.round(np.asarray(a[:, 0])).astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])
    return mm


# ------------------------------------------------------------------------------------------------ aşamalar
def stage_rows(args):
    syms = L.symbols("1m")
    src = build_sources(args.jsonl)
    for name in SRC_NAMES:
        t0 = time.time()
        R = make_rows(name, src[name], syms)
        n_sig = int((R["kind"] == 0).sum()); n_rnd = int((R["kind"] == 1).sum()); n_rv = "/".join(str(int((R["kind"] == k).sum())) for k in (2, 3, 4))
        print("[rows] %s: sinyal %d, rastgele %d, rastgele-oyn/dışlamasız/oyn-dışlamasız %s, kayıp %s, gap kademeleri %s (%.0f sn)" % (name, n_sig, n_rnd, n_rv, R["miss"], R["tier_used"], time.time() - t0), flush=True)
        pickle.dump(R, open(L.WORK / ("b_rows_%s.pkl" % name), "wb"))


def stage_sim(args):
    specs = L.exit_set()
    cells_all = cell_list()
    if args.cells:
        wanted = set(args.cells.split("|"))
        cells_all = [c for c in cells_all if cname(c) in wanted]
    scn = args.scenario
    delay, slip = L.SCENARIOS[scn]
    for name in args.sources.split(","):
        t0 = time.time()
        R = pickle.load(open(L.WORK / ("b_rows_%s.pkl" % name), "rb"))
        syms = [str(s) for s in R["syms"]]
        need = {syms[i] for i in np.unique(R["sym"])}
        mm = load_mm(syms, need)
        ent, ex = entry_specs(R, cells_all, delay, mm)
        print("[sim] %s %s: giriş belirtimleri hazır (%.0f sn), hücre %d" % (name, scn, time.time() - t0, len(cells_all)), flush=True)
        res = {}
        for ci, c in enumerate(cells_all):
            e = ent[c]
            net = sim_entries(e, syms, mm, specs, slip, limit=c[0] in LIMIT_KINDS)
            res[cname(c)] = {"row": e["row"].astype(np.int32), "net": net}
            if (ci + 1) % 10 == 0:
                print("[sim] %s %s: %d/%d hücre (%.0f sn)" % (name, scn, ci + 1, len(cells_all), time.time() - t0), flush=True)
        out = {"res": res, "extra": ex["extra"], "fi": {cname(c): v for c, v in ex["fi"].items()}, "specs": [s.name for s in specs],
               "rows": {k: R[k] for k in ("sym", "kind", "t", "p0", "frame", "pair", "day")}, "scenario": scn, "delay": delay, "slip": slip,
               "cells": [cname(c) for c in cells_all]}
        pickle.dump(out, open(L.WORK / ("b_res_%s_%s.pkl" % (name, scn)), "wb"))
        print("[sim] %s %s bitti (%.0f sn)" % (name, scn, time.time() - t0), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="rows,sim")
    ap.add_argument("--sources", default=",".join(SRC_NAMES))
    ap.add_argument("--scenario", default="P")
    ap.add_argument("--cells", default="")
    ap.add_argument("--jsonl", default=str(L._BACKEND_DIR / "work" / "rescan_90g_nogate.jsonl"))
    args = ap.parse_args()
    for st in args.stages.split(","):
        {"rows": stage_rows, "sim": stage_sim}[st](args)


if __name__ == "__main__":
    main()
