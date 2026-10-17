"""Çalışma A (1)+(2): StochRSI ön sinyali çekirdek (RQK) AL dönüşünü önceden haber veriyor mu? + LUNA tipi olayların zamanlaması.

Çıktı: work/limitstoch/a1_results.pkl (rapor betiği okur). DB gerekmez (önbellek)."""
from __future__ import annotations

import csv
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402

NS = (1, 3, 6, 12)
WINS = ("W30", "B1", "B2", "B3")
CATS = ("pre", "base_red", "base_low")         # ön sinyal / kırmızı çekirdekteki tüm barlar / kırmızı + K[i-1] < seviye (kesişim şartı yok)
BIG = 10 ** 9


def first_bull_dist(bull: np.ndarray) -> np.ndarray:
    """dist[i] = i'den SONRAKİ ilk bull barın uzaklığı (i+1'den başlar); yoksa BIG."""
    n = len(bull)
    arr = np.full(n + 1, BIG, dtype=np.int64)
    pos = np.flatnonzero(bull)
    arr[pos] = pos
    nxt = np.minimum.accumulate(arr[::-1])[::-1]
    j = nxt[np.minimum(np.arange(n) + 1, n)]
    return np.where(j >= BIG, BIG, j - np.arange(n))


def acc_days(store: dict, key, day_off: np.ndarray, ndays: int, n_flags: np.ndarray, flags: list[np.ndarray]) -> None:
    """store[key] (ndays, 1+len(flags)) üzerine gün başına toplam: [n, k1, k2, ...]."""
    if key not in store:
        store[key] = np.zeros((ndays, 1 + len(flags)))
    a = store[key]
    ok = (day_off >= 0) & (day_off < ndays) & n_flags
    if not ok.any():
        return
    d = day_off[ok]
    a[:, 0] += np.bincount(d, minlength=ndays)
    for q, f in enumerate(flags):
        a[:, 1 + q] += np.bincount(d, weights=f[ok].astype(float), minlength=ndays)


def run_a1() -> dict:
    t0 = time.time()
    syms = L.symbols("5m")
    day0 = {w: int(L.day_idx(L.WINDOWS[w][0])) for w in WINS}
    nd = {w: int(L.day_idx(L.WINDOWS[w][1])) - day0[w] + 1 for w in WINS}
    turn: dict = {}          # (tf, win, level, cat) → (ndays, 1+len(NS))
    prec: dict = {}          # (tf, win, level, "flip"/"base") → (ndays, 2)  [n, has pre within 12]
    lead_hist: dict = {}     # (tf, win, level, "pre") → hist[0..12] (ön sinyalden dönüşe bar)  ;  ("flip") → ön sinyalden dönüşe (dönüş barı - son ön sinyal)
    for si, sym in enumerate(syms):
        liq = L.Liq(sym)
        for tf in ("5m", "1m", "15m"):
            ind = L.get_ind(tf, sym)
            ot = ind["ot"]; n = len(ot)
            ct = ot + L.TF_MS[tf]
            valid = ind["valid"]; bull = ind["bull"] & valid
            bear = valid & ~bull
            lq = liq.liquid(ct)
            dist = first_bull_dist(bull)
            k = ind["k"].astype(float)
            kprev = np.concatenate([[np.nan], k[:-1]])
            dayc = L.day_idx(ct)
            flip = bull & np.concatenate([[False], bear[:-1]])           # kırmızı → yeşil dönüş barı
            for lv in L.LEVELS:
                ps = ind["ps%d" % lv] & lq
                cps = np.concatenate([[0], np.cumsum(ind["ps%d" % lv])])    # ön sinyal sayısı (sıvı filtresiz; dönüşten önce)
                base_red = bear & lq
                base_low = base_red & (kprev < lv)
                masks = {"pre": ps, "base_red": base_red, "base_low": base_low}
                flags = [(dist <= m) for m in NS]
                # dönüşten ÖNCEKİ 12 barda ön sinyal var mı (bar j için: [j-12, j-1])
                lo = np.maximum(np.arange(n) - 12, 0)
                has12 = np.zeros(n, dtype=bool)
                has12[1:] = (cps[np.arange(1, n)] - cps[lo[1:]]) > 0
                prev_bear = np.concatenate([[False], bear[:-1]])
                last_ps = np.maximum.accumulate(np.where(ind["ps%d" % lv], np.arange(n), -BIG))
                lead_prev = np.arange(n) - np.concatenate([[-BIG], last_ps[:-1]])       # j - (j'den önceki son ön sinyal)
                for w in WINS:
                    d_off = dayc - day0[w]
                    inw = (ct >= L.WINDOWS[w][0]) & (ct <= L.WINDOWS[w][1])
                    for cat, mk in masks.items():
                        acc_days(turn, (tf, w, lv, cat), d_off, nd[w], mk & inw, flags)
                    acc_days(prec, (tf, w, lv, "flip"), d_off, nd[w], flip & lq & inw, [has12])
                    acc_days(prec, (tf, w, lv, "base"), d_off, nd[w], prev_bear & valid & lq & inw & (np.arange(n) >= 1), [has12])
                    sel = ps & inw & (dist <= 12)
                    h = np.bincount(dist[sel], minlength=13)[:13]
                    lead_hist[(tf, w, lv, "pre")] = lead_hist.get((tf, w, lv, "pre"), 0) + h
                    sel2 = flip & lq & inw & has12 & (lead_prev <= 12)
                    h2 = np.bincount(lead_prev[sel2], minlength=13)[:13]
                    lead_hist[(tf, w, lv, "flip")] = lead_hist.get((tf, w, lv, "flip"), 0) + h2
        if si % 50 == 0:
            print("[a1] %d/%d (%.0f sn)" % (si, len(syms), time.time() - t0), flush=True)
    return {"turn": turn, "prec": prec, "lead_hist": lead_hist, "nd": nd}


# ------------------------------------------------------------------------------------------------ olay zamanlaması
def load_events(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({"sym": r["symbol"], "t0": int(r["t0_ms"]), "dur": int(float(r["dur_min"])) * 60_000, "gain": float(r["gain_pct"]),
                        "kept": r["kept_primary"] == "1", "local": r["t0_local"]})
    return out


PRE_WIN = (-30 * 60_000, 5 * 60_000)             # [t0 − 30 dk, t0 + 5 dk]
PRE_WIN_B = (-30 * 60_000, 0)                    # yalnız t0'dan ÖNCE (nedensel)
PRE_WIN_C = (-15 * 60_000, 5 * 60_000)
N_RAND = 40


def has_in(times: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """times sıralı; lo ≤ time ≤ hi olan var mı."""
    if len(times) == 0:
        return np.zeros(len(lo), dtype=bool)
    i = np.searchsorted(times, lo, side="left")
    j = np.searchsorted(times, hi, side="right")
    return j > i


def first_in(times: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """lo ≤ time ≤ hi içindeki İLK zaman; yoksa -1."""
    out = np.full(len(lo), -1, dtype=np.int64)
    if len(times) == 0:
        return out
    i = np.searchsorted(times, lo, side="left")
    ic = np.minimum(i, len(times) - 1)
    ok = (i < len(times)) & (times[ic] <= hi)
    out[ok] = times[ic][ok]
    return out


def last_in(times: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    out = np.full(len(lo), -1, dtype=np.int64)
    if len(times) == 0:
        return out
    j = np.searchsorted(times, hi, side="right") - 1
    jc = np.maximum(j, 0)
    ok = (j >= 0) & (times[jc] >= lo)
    out[ok] = times[jc][ok]
    return out


def run_events(events_csv: Path, seed: int = 7) -> dict:
    ev = [e for e in load_events(events_csv) if e["kept"]]
    by_sym: dict[str, list[int]] = {}
    for i, e in enumerate(ev):
        by_sym.setdefault(e["sym"], []).append(i)
    # tüm olaylar (kept olmayanlar dâhil) — rastgele an dışlaması için
    all_ev = load_events(events_csv)
    all_by_sym: dict[str, list[dict]] = {}
    for e in all_ev:
        all_by_sym.setdefault(e["sym"], []).append(e)
    rng = np.random.default_rng(seed)
    store = []
    for sym, idxs in sorted(by_sym.items()):
        try:
            inds = {tf: L.get_ind(tf, sym) for tf in ("5m", "1m", "15m")}
        except FileNotFoundError:
            continue
        ot5 = inds["5m"]["ot"]
        sig = {}
        for tf in ("5m", "1m", "15m"):
            for lv in L.LEVELS:
                sig[(tf, lv, "pre")] = L.pre_times(inds[tf], tf, lv)
                sig[(tf, lv, "conf")] = L.conf_times(inds[tf], tf, lv)
            ind = inds[tf]
            flip = ind["bull"] & ind["valid"] & np.concatenate([[False], (ind["valid"] & ~ind["bull"])[:-1]])
            sig[(tf, 0, "flip")] = ind["ot"][flip] + L.TF_MS[tf]
        excl = [(e["t0"] - 3_600_000, e["t0"] + e["dur"] + 3_600_000) for e in all_by_sym.get(sym, [])]
        ex_lo = np.array([a for a, _ in excl]); ex_hi = np.array([b for _, b in excl])
        kinds, evi, tt, dur, gain, day_l = [], [], [], [], [], []
        for i in idxs:
            e = ev[i]
            day = int(L.day_idx(e["t0"]))
            d_lo = day * L.DAY_MS - L.TZ_MS; d_hi = d_lo + L.DAY_MS
            g = np.arange(-(-d_lo // 300_000) * 300_000, d_hi, 300_000, dtype=np.int64)
            g = g[(g >= ot5[0] + 30 * 60_000) & (g <= ot5[-1])]
            if len(g):
                bad = ((g[:, None] >= ex_lo[None, :]) & (g[:, None] <= ex_hi[None, :])).any(axis=1)
                g = g[~bad]
            rr = rng.choice(g, size=min(N_RAND, len(g)), replace=False) if len(g) else np.zeros(0, dtype=np.int64)
            kinds.append(0); evi.append(i); tt.append(e["t0"]); dur.append(e["dur"]); gain.append(e["gain"]); day_l.append(day)
            for t in rr:
                kinds.append(1); evi.append(i); tt.append(int(t)); dur.append(0); gain.append(0.0); day_l.append(day)
        t_arr = np.array(tt, dtype=np.int64)
        res = {}
        for key, times in sig.items():
            tms = np.sort(times)
            res[(key, "a")] = has_in(tms, t_arr + PRE_WIN[0], t_arr + PRE_WIN[1])
            res[(key, "b")] = has_in(tms, t_arr + PRE_WIN_B[0], t_arr + PRE_WIN_B[1])
            res[(key, "c")] = has_in(tms, t_arr + PRE_WIN_C[0], t_arr + PRE_WIN_C[1])
            res[(key, "first")] = first_in(tms, t_arr + PRE_WIN[0], t_arr + PRE_WIN[1])
            res[(key, "last_before")] = last_in(tms, t_arr + PRE_WIN[0], t_arr)         # t0 veya öncesindeki SON
            res[(key, "next_after")] = first_in(tms, t_arr - 5 * 60_000, t_arr + 120 * 60_000)    # t0-5dk … t0+2sa içindeki ilk
        store.append({"sym": sym, "kind": np.array(kinds), "ev": np.array(evi), "t": t_arr, "dur": np.array(dur), "gain": np.array(gain),
                      "day": np.array(day_l), "res": res})
    return {"store": store, "n_events": len(ev), "events": ev}


def main():
    t0 = time.time()
    out_dir = L.WORK
    a1 = run_a1()
    print("[a1] bitti %.0f sn" % (time.time() - t0), flush=True)
    ev = run_events(L._BACKEND_DIR / "work" / "pattern90" / "events.csv")
    print("[ev] bitti %.0f sn, olay %d" % (time.time() - t0, ev["n_events"]), flush=True)
    pickle.dump({"a1": a1, "ev": ev}, open(out_dir / "a1_results.pkl", "wb"))


if __name__ == "__main__":
    main()
