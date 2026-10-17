"""Rapor bölümü: Çalışma B (limit giriş + StochRSI desteği)."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402
import limitstoch_b as B  # noqa: E402

f2 = L.f2


def pct(x, nd=1):
    return "—" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f") % (100 * x)


WIN_DEF = {"B12": ("B1", "B2")}
SRC_WINS = {"HA": ["W30", "B1", "B2", "B3", "B12", "ALL"], "NOTIF_all": ["W30"], "NOTIF_trend": ["W30"], "LIVE": ["B3"]}
KINDS = (0, 1, 2, 3, 4)
KIND_NAMES = {0: "sinyal", 1: "rastgele-1 (saat, ≥2sa)", 2: "rastgele-2 (oyn., ≥2sa)", 3: "rastgele-3 (saat, dışlamasız)", 4: "rastgele-4 (oyn., dışlamasız)"}


class BRes:
    def __init__(self, name: str, scn: str):
        d = pickle.load(open(L.WORK / ("b_res_%s_%s.pkl" % (name, scn)), "rb"))
        self.name = name; self.scn = scn
        rows = d["rows"]
        self.kind = rows["kind"]; self.t = rows["t"]; self.day = rows["day"]; self.pair = rows["pair"]; self.sym = rows["sym"]; self.p0 = rows["p0"]
        self.specs = d["specs"]; self.res = d["res"]; self.extra = d["extra"]; self.fi = d["fi"]; self.cells = d["cells"]
        sig_t = self.t[self.kind == 0]
        self.win_t = np.where(self.kind == 0, self.t, sig_t[self.pair])
        self.n = len(self.kind)
        self._cache = {}

    def in_win(self, win: str) -> np.ndarray:
        if win in WIN_DEF:
            m = np.zeros(self.n, dtype=bool)
            for w in WIN_DEF[win]:
                m |= L.window_mask(self.win_t, w)
            return m
        return L.window_mask(self.win_t, win)

    def mat(self, cell: str):
        d = self.res[cell]
        V = np.zeros((self.n, len(self.specs)), dtype=np.float32)
        tr = np.zeros(self.n, dtype=bool)
        ok = np.isfinite(d["net"][:, 0])
        V[d["row"][ok]] = d["net"][ok]
        tr[d["row"][ok]] = True
        return V, tr

    def stats_from(self, V, tr, mask) -> dict:
        n = int(mask.sum())
        if n == 0:
            return {"n": 0}
        Vm = V[mask].astype(np.float64); trm = tr[mask]; dm = self.day[mask]
        mean = Vm.sum(0) / n
        ud, inv = np.unique(dm, return_inverse=True)
        S = np.zeros((len(ud), Vm.shape[1]))
        np.add.at(S, inv, Vm)
        cnt = np.bincount(inv).astype(float)
        se = np.sqrt(((S - cnt[:, None] * mean[None, :]) ** 2).sum(0)) / n
        ntr = int(trm.sum())
        if ntr > 1:
            Vt = Vm[trm]; it = inv[trm]
            mean_t = Vt.sum(0) / ntr
            St = np.zeros((len(ud), Vm.shape[1]))
            np.add.at(St, it, Vt)
            ct = np.bincount(it, minlength=len(ud)).astype(float)
            se_t = np.sqrt(((St - ct[:, None] * mean_t[None, :]) ** 2).sum(0)) / ntr
            win_t = (Vt > 0).mean(0)
        else:
            mean_t = np.full(Vm.shape[1], np.nan); se_t = np.full(Vm.shape[1], np.nan); win_t = np.full(Vm.shape[1], np.nan)
        return {"n": n, "ntr": ntr, "fill": ntr / n, "mean": mean, "se": se, "mean_t": mean_t, "se_t": se_t, "win_t": win_t}

    def cell_stats(self, cell: str, wins) -> dict:
        key = cell
        if key in self._cache:
            return self._cache[key]
        V, tr = self.mat(cell)
        out = {}
        for w in wins:
            wm = self.in_win(w)
            for k in KINDS:
                out[(w, k)] = self.stats_from(V, tr, wm & (self.kind == k))
        self._cache[key] = out
        return out

    def all_stats(self):
        wins = SRC_WINS[self.name]
        return {c: self.cell_stats(c, wins) for c in self.cells}


def ci1(m, se):
    return "%s [%s; %s]" % (f2(m), f2(m - 1.96 * se), f2(m + 1.96 * se))


def dci(a, b, j):
    """sinyal − taban (kişi başı sinyal) j. çıkış."""
    if not a.get("n") or not b.get("n"):
        return float("nan"), float("nan"), float("nan")
    d = a["mean"][j] - b["mean"][j]
    se = float(np.hypot(a["se"][j], b["se"][j]))
    return d, d - 1.96 * se, d + 1.96 * se


def dtxt(a, b, j):
    d, lo, hi = dci(a, b, j)
    return "%s [%s; %s]" % (f2(d), f2(lo), f2(hi))


def best_j(st: dict, min_ntr: int = 30):
    if not st.get("n") or st["ntr"] < min_ntr:
        return None
    return int(np.argmax(st["mean"]))


