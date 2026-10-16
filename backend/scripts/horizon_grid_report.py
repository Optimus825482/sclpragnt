"""Uzun ufuk (60..1440 dk) bildirim kalitesi / maliyet-sonrası net getiri ızgarası.

SORU: Bildirimden sonra tutma süresi (H), hedef (T), stop (S) ve maliyet değiştikçe
net getiri pozitif bir hücre var mı; varsa şans tabanını ve haftalık kararlılığı aşıyor mu?

ÖLÇÜ (salt-okunur; `historical_candles` 5m, yalnız detected_at SONRASI açılan mumlar):
  * ızgara: H {60,120,240,480,720,1440} x T {1.5..8 %} x S {2,3,5 %} x maliyet {0.35,0.25,0.20 %}
    ve iki çıkış kuralı: TPSL (hedef/stop) ve TRAIL (T/2'de aktifleşen, tepe*(1-T/3 %) izleyen stop).
  * stop dolumu: mum açılışı stopun altındaysa (gap) dolum AÇILIŞTA olur; aynı mumda SL önce.
  * alt kümeler (mode, skor, güncel kapılar), seçilen hücrelerde A->B / B->A örneklem-dışı kontrol.
  * şans tabanı: aynı sembol, son 30dk aralığı ve getirisi eşleşmiş rastgele anlar
    ('own': kendi bildirimlerinden, 'all': sembolün HERHANGİ bir bildiriminden >=max(2sa,H) uzak).
  * haftalık kararlılık, sembol yoğunluğu, tekrarsız varyant, örtüşme.

Bu modül import anında DATABASE_URL okumaz. Konsol: PYTHONIOENCODING=utf-8 ayarlayın.

KULLANIM (backend klasöründen):
    python scripts/horizon_grid_report.py --days 30 --out ufuk_30g.md
"""
from __future__ import annotations

import argparse
import collections
import math
import os
import sys
import time
from datetime import datetime
from typing import Any

import numpy as np

try:  # python -m scripts.x  veya  python scripts/x.py
    from scripts.notification_outcomes_report import CandleStore, TZ, _db_url, load_candles, wilson
except ImportError:  # pragma: no cover - doğrudan çalıştırma
    from notification_outcomes_report import CandleStore, TZ, _db_url, load_candles, wilson

HS = [60, 120, 240, 480, 720, 1440]
TS = [1.5, 2, 3, 4, 6, 8]
SS = [2, 3, 5]
COSTS = [0.35, 0.25, 0.20]
NC = 288          # 1440 dk / 5 dk
BIG = 10 ** 9
K_NULL = 20


# ------------------------------------------------------------------ istatistik
def tstat(x) -> float:
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return float("nan")
    sd = x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else float("nan")


def tclust(x, g) -> float:
    """Küme-dayanıklı t (küme = g etiketi): SE = sqrt(sum_g (sum_i e_i)^2)/n."""
    x = np.asarray(x, float)
    n = len(x)
    e = x - x.mean()
    s: dict = collections.defaultdict(float)
    for ei, gi in zip(e, g):
        s[gi] += ei
    G = len(s)
    if G < 3:
        return float("nan")
    se = math.sqrt(sum(v * v for v in s.values()) * G / (G - 1)) / n
    return float(x.mean() / se) if se > 0 else float("nan")


def stats(net) -> dict:
    net = np.asarray(net, float)
    n = len(net)
    if n == 0:
        return dict(n=0, mean=np.nan, med=np.nan, win=np.nan, payoff=np.nan, t=np.nan)
    w, l = net[net > 0], net[net <= 0]
    payoff = (w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() != 0 else np.nan
    return dict(n=n, mean=net.mean(), med=float(np.median(net)), win=100 * len(w) / n, payoff=payoff, t=tstat(net))


# ------------------------------------------- çıkış kuralları (matris, yüzde birimi)
def ev_tpsl(hp: np.ndarray, lp: np.ndarray, op: np.ndarray, T, S: float):
    """Hedef/stop: (ilk çıkış mum indeksi, getiri %). SL aynı mumda önce; gap'te açılışta dolum."""
    R = hp.shape[0]
    Tv = np.broadcast_to(np.asarray(T, float).reshape(-1, 1) if np.ndim(T) else np.full((R, 1), T), (R, 1))
    tpm = hp >= Tv
    slm = lp <= -S
    itp = np.where(tpm.any(1), tpm.argmax(1), BIG)
    isl = np.where(slm.any(1), slm.argmax(1), BIG)
    idx = np.minimum(itp, isl)
    rows_ = np.arange(R)
    slret = np.minimum(-float(S), op[rows_, np.minimum(isl, hp.shape[1] - 1)])  # açılış stop altındaysa gap'li dolum
    ret = np.where(isl <= itp, slret, Tv[:, 0])
    return idx, ret


def ev_trail(hp: np.ndarray, lp: np.ndarray, op: np.ndarray, T, S: float):
    """İzleyen stop: high >= T/2 olunca aktif, stop = tepe*(1-T/3 %), önceki mumların tepesine göre."""
    R, n = hp.shape
    Tv = np.broadcast_to(np.asarray(T, float).reshape(-1, 1) if np.ndim(T) else np.full((R, 1), T), (R, 1))[:, 0]
    act = Tv / 2
    fac = 1 - Tv / 300
    active = np.zeros(R, bool)
    peak = np.full(R, -np.inf)
    done = np.zeros(R, bool)
    idx = np.full(R, BIG)
    ret = np.zeros(R)
    for k in range(n):
        stop = np.where(active, ((1 + peak / 100) * fac - 1) * 100, -float(S))
        hit = (~done) & (lp[:, k] <= stop)
        if hit.any():
            idx[hit] = k
            ret[hit] = np.minimum(stop[hit], op[hit, k])  # gap: açılış stoptan aşağıdaysa açılışta dolum
            done |= hit
        upd = ~done
        peak = np.where(upd, np.maximum(peak, hp[:, k]), peak)
        active |= upd & (peak >= act)
    return idx, ret


EV = {"TPSL": ev_tpsl, "TRAIL": ev_trail}


def cend_of(cp: np.ndarray, nH: np.ndarray) -> np.ndarray:
    return cp[np.arange(cp.shape[0]), nH - 1]


def gross_of(idx: np.ndarray, ret: np.ndarray, nH: np.ndarray, cend: np.ndarray) -> np.ndarray:
    """Ufuk içinde çıkış varsa onun getirisi, yoksa ufuk sonu kapanış (brüt, maliyetsiz)."""
    return np.where(idx < nH, ret, cend)


def mfe_mae(hp: np.ndarray, lp: np.ndarray, nH: np.ndarray):
    m = np.arange(hp.shape[1])[None, :] < nH[:, None]
    return np.where(m, hp, -np.inf).max(1), np.where(m, lp, np.inf).min(1)


# --------------------------------------------------------------- örneklem
def build_sample(rows: list[dict], store: CandleStore, *, hs: list[int] = HS, nc: int = NC,
                 entry_mode: str = "notif") -> dict:
    """Ortak örneklem: tüm ufuklar için tam pencereli bildirimler, giriş fiyatına göre % matrisler.

    rows: {id, symbol, score, target_pct, price, mode, detected_at} sözlükleri.
    entry_mode: 'notif' (bildirim fiyatı) | 'open' (bildirim sonrası ilk mumun açılışı).
    """
    drops: collections.Counter = collections.Counter()
    S_: list[dict] = []
    HP, LP, CP, OP = [], [], [], []
    NH: dict = {H: [] for H in hs}
    maxH = max(hs)
    for row in rows:
        sym, det = row["symbol"], row["detected_at"]
        tp = row["target_pct"] if row.get("target_pct") and row["target_pct"] > 0 else 2.0
        if sym not in store.d or sym not in store.op:
            drops["mum yok"] += 1
            continue
        ot, hi, lo, cl = store.d[sym]
        opn = store.op[sym]
        det_ms = det * 1000
        if det_ms + maxH * 60000 > store.tmax * 1000:
            drops[f"{maxH}dk penceresi veri sonunu asiyor"] += 1
            continue
        i0 = int(np.searchsorted(ot, det_ms, side="right"))
        if i0 >= len(ot) or ot[i0] - det_ms > 600000:
            drops["ilk mum >10dk uzakta (bosluk)"] += 1
            continue
        pr = row.get("price")
        entry = pr if pr and pr > 0 else cl[i0 - 1]
        if entry_mode == "open":
            entry = opn[i0]
        if abs(entry / cl[i0] - 1) > 0.2:
            drops["fiyat/mum olcek uyumsuz (>%20)"] += 1
            continue
        seg = slice(i0, min(i0 + nc, len(ot)))
        so = ot[seg]
        nh = {}
        okk = True
        for H in hs:
            end_ms = det_ms + H * 60000
            n = int(np.searchsorted(so, end_ms, side="left"))
            if n < max(1, H // 5 - 3) or so[n - 1] < end_ms - 600000:
                okk = False
                break
            nh[H] = n
        if not okk:
            drops["pencere bosluklu (mum eksik)"] += 1
            continue
        h = np.full(nc, -1e9)
        l = np.full(nc, 1e9)
        c = np.full(nc, np.nan)
        o = np.full(nc, np.nan)
        m = len(so)
        h[:m] = (hi[seg] / entry - 1) * 100
        l[:m] = (lo[seg] / entry - 1) * 100
        c[:m] = (cl[seg] / entry - 1) * 100
        o[:m] = (opn[seg] / entry - 1) * 100
        HP.append(h)
        LP.append(l)
        CP.append(c)
        OP.append(o)
        for H in hs:
            NH[H].append(nh[H])
        d = datetime.fromtimestamp(det, TZ)
        S_.append(dict(id=row["id"], sym=sym, score=row.get("score") or 0.0, tp=tp, mode=row.get("mode") or "(bos)",
                       det=det, entry=entry, day=d.strftime("%m-%d"), week=f"H{d.isocalendar()[1]}"))
    return dict(S=S_, HP=np.array(HP), LP=np.array(LP), CP=np.array(CP), OP=np.array(OP),
                NH={H: np.array(v) for H, v in NH.items()}, drops=drops, n_rows=len(rows), hs=list(hs))


def compute_grid(sample: dict, ts: list = TS, ss: list = SS, costs: list = COSTS) -> tuple[list[dict], dict]:
    """Izgara hücreleri: (liste[dict], gross_cache[(kural,H,T,S)] = brüt getiri dizisi)."""
    HP, LP, OP, CP, NH = sample["HP"], sample["LP"], sample["OP"], sample["CP"], sample["NH"]
    TPa = np.array([r["tp"] for r in sample["S"]])
    cend = {H: cend_of(CP, NH[H]) for H in sample["hs"]}
    grid: list[dict] = []
    gross_cache: dict = {}
    for rule, fn in EV.items():
        for T in list(ts) + ["nat"]:
            for S in ss:
                idx, ret = fn(HP, LP, OP, TPa if T == "nat" else T, S)
                for H in sample["hs"]:
                    g = gross_of(idx, ret, NH[H], cend[H])
                    gross_cache[(rule, H, T, S)] = g
                    for cst in costs:
                        st = stats(g - cst)
                        st.update(rule=rule, H=H, T=T, S=S, cost=cst)
                        grid.append(st)
    return grid, gross_cache


# --------------------------------------------------------------- şans tabanı
def chance_baseline(sample: dict, store: CandleStore, mode: str, H: int, cfgs: list[tuple],
                    rng: np.random.Generator, k_null: int = K_NULL) -> dict:
    """Her bildirim için aynı sembolde, son 30dk aralığı ve getirisi eşleşmiş <=k_null rastgele an.

    mode 'own'  : kendi bildirim zamanından |t| >= max(2sa, H) uzak
    mode 'all'  : sembolün HERHANGİ bir bildiriminden >= max(2sa, H) uzak
    Giriş = o anın kapanışı; ileri pencere kesintisiz H dk mum içermeli. >=8 an yoksa kapsam dışı.
    """
    S_ = sample["S"]
    n = len(S_)
    TPa = np.array([r["tp"] for r in S_])
    nn = H // 5
    cache: dict = {}

    def trail(sym: str):
        if sym in cache:
            return cache[sym]
        ot, hi, lo, cl = store.d[sym]
        m = len(ot)
        rg = np.full(m, np.nan)
        rt = np.full(m, np.nan)
        if m > 7:
            swh = np.lib.stride_tricks.sliding_window_view(hi, 6).max(axis=1)
            swl = np.lib.stride_tricks.sliding_window_view(lo, 6).min(axis=1)
            rg[5:] = swh / swl - 1
            rt[6:] = cl[6:] / cl[:-6] - 1
        cache[sym] = (rg, rt, ot / 1000 + 300)
        return cache[sym]

    sym_dets: dict = collections.defaultdict(list)
    for r in S_:
        sym_dets[r["sym"]].append(r["det"])
    for s in sym_dets:
        sym_dets[s] = np.array(sorted(sym_dets[s]))
    nd_all: dict = {}

    def nearest_all(sym: str, tt: np.ndarray) -> np.ndarray:
        if sym not in nd_all:
            D = sym_dets[sym]
            ix = np.searchsorted(D, tt)
            a = np.abs(tt - D[np.clip(ix - 1, 0, len(D) - 1)])
            b = np.abs(tt - D[np.clip(ix, 0, len(D) - 1)])
            nd_all[sym] = np.minimum(a, b)
        return nd_all[sym]

    def fwd_ok(sym: str) -> np.ndarray:
        ot = store.d[sym][0]
        ok = np.zeros(len(ot), bool)
        if len(ot) > nn:
            ok[: len(ot) - nn] = (ot[nn:] - ot[: len(ot) - nn]) == nn * 300000
        return ok

    res = dict(cov=np.zeros(n, bool), hit={T: np.full(n, np.nan) for T in TS}, hitnat=np.full(n, np.nan),
               hold=np.full(n, np.nan), gross={k: np.full(n, np.nan) for k in cfgs})
    pending = []
    for i, r in enumerate(S_):
        sym = r["sym"]
        ot, hi, lo, cl = store.d[sym]
        rg, rt, tt = trail(sym)
        j0 = int(np.searchsorted(ot + 300000, r["det"] * 1000, side="right")) - 1
        if j0 < 6 or np.isnan(rg[j0]):
            continue
        valid = fwd_ok(sym) & ~np.isnan(rg) & ~np.isnan(rt)
        ex = max(7200, H * 60)
        if mode == "own":
            valid &= np.abs(tt - r["det"]) >= ex
        else:
            valid &= nearest_all(sym, tt) >= ex
        rgn, rtn = rg[j0], rt[j0]
        c = valid & (np.abs(rg - rgn) <= max(0.004, 0.25 * rgn)) & (np.abs(rt - rtn) <= max(0.004, 0.25 * abs(rtn)))
        cand = np.where(c)[0]
        if len(cand) < 8:
            continue
        pending.append((i, sym, rng.choice(cand, size=min(k_null, len(cand)), replace=False)))
    CH = max(1, 6000 // k_null)
    for a in range(0, len(pending), CH):
        part = pending[a:a + CH]
        hps, lps, cps, ops, gid = [], [], [], [], []
        for (i, sym, js) in part:
            ot, hi, lo, cl = store.d[sym]
            ix = js[:, None] + 1 + np.arange(nn)[None, :]
            e = cl[js][:, None]
            hps.append((hi[ix] / e - 1) * 100)
            lps.append((lo[ix] / e - 1) * 100)
            cps.append((cl[ix] / e - 1) * 100)
            ops.append((store.op[sym][ix] / e - 1) * 100)
            gid += [i] * len(js)
        hp_, lp_, cp_, op_ = np.vstack(hps), np.vstack(lps), np.vstack(cps), np.vstack(ops)
        gid = np.array(gid)
        nh_ = np.full(len(gid), nn)
        ce = cp_[:, -1]
        mfe = hp_.max(1)
        ui, inv = np.unique(gid, return_inverse=True)
        cnt = np.bincount(inv)
        res["cov"][ui] = True
        res["hold"][ui] = np.bincount(inv, ce) / cnt
        for T in TS:
            res["hit"][T][ui] = np.bincount(inv, (mfe >= T).astype(float)) / cnt
        tpn = TPa[gid]
        res["hitnat"][ui] = np.bincount(inv, (mfe >= tpn).astype(float)) / cnt
        for kk in cfgs:
            rule, _, T, S = kk
            Tv = tpn if T == "nat" else T
            idx, ret = EV[rule](hp_, lp_, op_, Tv, S)
            res["gross"][kk][ui] = np.bincount(inv, gross_of(idx, ret, nh_, ce)) / cnt
    return res


# ------------------------------------------------------------------ rapor
def generate_report(rows: list[dict], store: CandleStore, *, since_ts: float, seed: int = 11,
                    entry_mode: str = "notif") -> tuple[str, dict]:
    """Saf: (satırlar, mum deposu) -> (markdown, özet). DB'ye dokunmaz."""
    t0 = time.time()
    out: list[str] = []
    summary: dict = {}
    rng = np.random.default_rng(seed)
    sample = build_sample(rows, store, entry_mode=entry_mode)
    S_ = sample["S"]
    n = len(S_)
    out.append(f"# Uzun ufuk testi - bildirimden sonra {HS[0]}..{HS[-1]} dk "
               f"({datetime.fromtimestamp(since_ts, TZ):%Y-%m-%d} .. "
               f"{datetime.fromtimestamp(max((r['detected_at'] for r in rows), default=since_ts), TZ):%m-%d %H:%M})")
    if not n:
        out.append("\nOlculen (tam pencereli) bildirim yok. Atlananlar: " + ", ".join(f"{k}={v}" for k, v in sample["drops"].items()))
        summary["n"] = 0
        return "\n".join(out) + "\n", summary
    out.append(f"Mum: historical_candles 5m, {len(store.d)} sembol, {datetime.fromtimestamp(store.tmin, TZ):%m-%d %H:%M} .. "
               f"{datetime.fromtimestamp(store.tmax, TZ):%m-%d %H:%M}. Yalniz detected_at SONRASI acilan mumlar; entry = "
               + ("bildirim price'i" if entry_mode == "notif" else "bildirimden sonraki ILK mumun acilisi (gecikmeli dolum)")
               + "; yuzde birimleri. Stop/SL gap'li dolumda mum acilisinda dolar (acilis stoptan asagidaysa). Ayni mumda SL once. "
               "Trailing: high >= T/2 olunca aktif, stop = tepe*(1-T/3 %), onceki mumlarin tepesine gore (mum ici lookahead yok). "
               "Maliyet = gidis-donus toplam.")
    out.append(f"\nToplam bildirim {sample['n_rows']}; **olculen (ortak ornek, tum ufuklar icin tam pencere) n={n}**; atlanan "
               f"{sample['n_rows'] - n}: " + ", ".join(f"{k}={v}" for k, v in sample["drops"].items()))
    out.append(f"Efektif bagimsiz birimler: farkli (sembol,gun)={len({(r['sym'], r['day']) for r in S_})}, "
               f"farkli sembol={len({r['sym'] for r in S_})}, gun={len({r['day'] for r in S_})}.")
    wk: dict = collections.defaultdict(list)
    for r in S_:
        wk[r["week"]].append(r["day"])
    out.append("ISO haftalar: " + "; ".join(f"{w} {min(d)}..{max(d)} (n={len(d)})" for w, d in sorted(wk.items())) + " (ilk/son hafta kismi)")

    HP, LP, CP, NH = sample["HP"], sample["LP"], sample["CP"], sample["NH"]
    TPa = np.array([r["tp"] for r in S_])
    sym_arr = np.array([r["sym"] for r in S_])
    day_arr = np.array([r["day"] for r in S_])
    week_arr = np.array([r["week"] for r in S_])
    mode_arr = np.array([r["mode"] for r in S_])
    score_arr = np.array([r["score"] for r in S_])
    symday = np.array([r["sym"] + "|" + r["day"] for r in S_])
    det_arr = np.array([r["det"] for r in S_])
    cend = {H: cend_of(CP, NH[H]) for H in HS}
    mm = {H: mfe_mae(HP, LP, NH[H]) for H in HS}

    # ---- 1. MFE/MAE ve hit
    out.append("\n## 1. MFE / MAE dagilimi ve hedefe ulasma (hit = MFE_H >= T)")
    out.append("| H (dk) | MFE p25 / p50 / p75 | MAE p25 / p50 / p75 | tutma getirisi (kapanis) ort / medyan |")
    out.append("|---|---|---|---|")
    q = lambda a: " / ".join(f"{np.percentile(a, p):.2f}" for p in (25, 50, 75))  # noqa: E731
    for H in HS:
        mfe, mae = mm[H]
        out.append(f"| {H} | {q(mfe)} | {q(mae)} | {cend[H].mean():+.2f} / {np.median(cend[H]):+.2f} |")
    out.append("\nHit orani % [Wilson95] (gercek bildirim):")
    out.append("| H \\ T | " + " | ".join(f"{t}%" for t in TS) + " |")
    out.append("|---|" + "---|" * len(TS))
    for H in HS:
        cells = []
        for T in TS:
            k = int((mm[H][0] >= T).sum())
            lo_, hi_ = wilson(k, n)
            cells.append(f"{100 * k / n:.1f} [{lo_:.0f},{hi_:.0f}]")
        out.append(f"| {H} | " + " | ".join(cells) + " |")

    # ---- 2. net ızgara
    grid, gross_cache = compute_grid(sample)
    G = {(g["rule"], g["H"], g["T"], g["S"], g["cost"]): g for g in grid}
    fixed = [g for g in grid if g["T"] != "nat"]
    out.append("\n## 2. Net getiri proxy (maliyet dusulmus)")
    out.append(f"Izgara: 2 kural x 6 H x 6 T x 3 S x 3 maliyet = {len(fixed)} hucre (+ bildirimin kendi target_pct'i ile 'nat' T: "
               f"{len(grid) - len(fixed)} hucre). Cok hucre denendigi icin t>2 tek basina yeterli degil (en az ~3.5 beklenmeli).")
    summary["cells"] = {}
    for cst in COSTS:
        pos = [g for g in fixed if g["cost"] == cst and g["mean"] > 0]
        sig = [g for g in pos if g["t"] > 2]
        tot = len([g for g in fixed if g["cost"] == cst])
        out.append(f"- maliyet {cst}%: mean>0 hucre {len(pos)}/{tot}, mean>0 & t>2: {len(sig)}")
        summary["cells"][f"{cst}"] = dict(pos=len(pos), sig=len(sig), total=tot)
    gpos = [(k, v) for k, v in gross_cache.items() if k[2] != "nat" and v.mean() > 0]
    out.append(f"- maliyetsiz (brut) ortalamasi >0 olan hucre: {len(gpos)}/{len([1 for k in gross_cache if k[2] != 'nat'])}")

    def tbl(rule: str, S: int, cst: float) -> None:
        out.append(f"\n{rule}, S={S}%, maliyet {cst}%: ortalama net % (t) - satir H, sutun T")
        out.append("| H \\ T | " + " | ".join(f"{t}%" for t in TS) + " | nat |")
        out.append("|---|" + "---|" * (len(TS) + 1))
        for H in HS:
            cells = []
            for T in TS + ["nat"]:
                g = G[(rule, H, T, S, cst)]
                star = "**" if (g["mean"] > 0 and g["t"] > 2) else ""
                cells.append(f"{star}{g['mean']:+.2f} ({g['t']:+.1f}){star}")
            out.append(f"| {H} | " + " | ".join(cells) + " |")
    for rule in ("TPSL", "TRAIL"):
        tbl(rule, 3, 0.35)
    tbl("TPSL", 3, 0.20)
    tbl("TRAIL", 3, 0.20)
    uniq = {(g["rule"], g["H"], g["T"], g["S"]): g for g in fixed if g["cost"] == 0.25}
    best = sorted(uniq.values(), key=lambda g: -(g["t"] if not math.isnan(g["t"]) else -1e9))
    out.append("\n### En iyi 8 hucre (0.25% maliyette t'ye gore; yanda 0.35 / 0.20)")
    out.append("| # | kural | H | T | S | n | net@0.35 ort (t) | net@0.25 ort / medyan / kazanma% / payoff (t) | net@0.20 ort (t) | brut ort |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for j, g in enumerate(best[:8], 1):
        k = (g["rule"], g["H"], g["T"], g["S"])
        a, b, c_ = G[k + (0.35,)], g, G[k + (0.20,)]
        out.append(f"| {j} | {k[0]} | {k[1]} | {k[2]} | {k[3]} | {b['n']} | {a['mean']:+.2f} ({a['t']:+.1f}) | "
                   f"{b['mean']:+.2f} / {b['med']:+.2f} / {b['win']:.0f} / {b['payoff']:.2f} ({b['t']:+.1f}) | "
                   f"{c_['mean']:+.2f} ({c_['t']:+.1f}) | {gross_cache[k].mean():+.2f} |")
    if best:
        g0 = best[0]
        summary["best_cell"] = dict(rule=g0["rule"], H=g0["H"], T=g0["T"], S=g0["S"], n=g0["n"],
                                    net25=float(g0["mean"]), t=float(g0["t"]))
    cur = G[("TPSL", 60, "nat", 3, 0.35)]
    summary["current_rule"] = dict(n=cur["n"], net35=float(cur["mean"]), gross=float(gross_cache[("TPSL", 60, "nat", 3)].mean()))
    out.append(f"\nReferans (mevcut 60 dk ayari: TP=bildirimin target_pct'i, SL=3, maliyet 0.35): n={cur['n']} net ort {cur['mean']:+.2f}, "
               f"medyan {cur['med']:+.2f}, kazanma {cur['win']:.0f}%, payoff {cur['payoff']:.2f}, t={cur['t']:+.1f}; "
               f"brut ort {gross_cache[('TPSL', 60, 'nat', 3)].mean():+.3f}")
    out.append("\n### Basa-bas komisyon (brut ortalama = maliyet esigi) - 60 dk, TPSL")
    out.append("| T | S=2 | S=3 | S=5 |")
    out.append("|---|---|---|---|")
    for T in TS + ["nat"]:
        out.append(f"| {T} | " + " | ".join(f"{gross_cache[('TPSL', 60, T, S)].mean():+.3f}" for S in SS) + " |")
    out.append("(Deger = brut ortalama getiri %; negatifse komisyon 0 olsa bile ortalama net <0.)")

    # ---- 3. alt kümeler
    subsets: "collections.OrderedDict[str, np.ndarray]" = collections.OrderedDict()
    subsets["TUMU"] = np.ones(n, bool)
    for m_ in ("trend_devam", "global_lead_lag", "unified", "notr", "llm_ikinci_goz"):
        subsets[f"mode={m_}"] = mode_arr == m_
    subsets["skor>=95"] = score_arr >= 95
    subsets["skor<95"] = score_arr < 95
    subsets["guncel kapilar (td+gll+llm)"] = np.isin(mode_arr, ["trend_devam", "global_lead_lag", "llm_ikinci_goz"])
    subsets["trend_devam & skor>=95"] = (mode_arr == "trend_devam") & (score_arr >= 95)
    CELLS = [(rule_, H_, T_, S_s) for rule_ in EV for H_ in HS for T_ in TS for S_s in SS]
    GM = np.array([gross_cache[c] for c in CELLS])
    cut = float(np.median(det_arr))  # A->B ayrimi: ornek medyani
    halfA, halfB = det_arr < cut, det_arr >= cut

    out.append("\n## 3. Alt kume x tum izgara (216 sabit-T hucre; en iyi hucre = 0.25 maliyette ortalamaya gore)")
    out.append(f"Secim yanliligi: en iyi hucrenin t'si sisiktir. 'A->B': hucre ilk yarida (<{datetime.fromtimestamp(cut, TZ):%m-%d %H:%M}, A) secilip "
               "ikinci yarida (B) olculur, 'B->A' tersi (gercek ornek-disi test). Sayilar: mean>0 & t>2 hucre sayisi (0.35 / 0.25 / 0.20).")
    out.append("| alt kume | n | #(mean>0 & t>2) @0.35 / 0.25 / 0.20 | en iyi hucre (kural H T S) | net@0.35 (t) | net@0.25 (t) | net@0.20 (t) | A->B net@0.25 (t, n) | B->A net@0.25 (t, n) |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    BESTC: dict = {}
    summary["subsets"] = {}
    for nm, msk in subsets.items():
        nn_ = int(msk.sum())
        if nn_ < 3:
            out.append(f"| {nm} (n<30) | {nn_} | - | - | - | - | - | - | - |")
            continue
        g_ = GM[:, msk]
        m_ = g_.mean(1)
        se = g_.std(1, ddof=1) / math.sqrt(nn_)
        se = np.where(se > 0, se, np.nan)
        cnt = [int(np.nansum(((m_ - c) > 0) & ((m_ - c) / se > 2))) for c in COSTS]
        j = int(np.argmax(m_))
        BESTC[nm] = CELLS[j]
        c = CELLS[j]
        tt = lambda cost: f"{m_[j] - cost:+.2f} ({(m_[j] - cost) / se[j]:+.1f})"  # noqa: E731
        xs = []
        for ma, mb in ((halfA, halfB), (halfB, halfA)):
            if (msk & ma).sum() < 3 or (msk & mb).sum() < 3:
                xs.append("-")
                continue
            ja = int(np.argmax(GM[:, msk & ma].mean(1)))
            gb = GM[ja, msk & mb] - 0.25
            xs.append(f"{CELLS[ja][0]} H{CELLS[ja][1]} T{CELLS[ja][2]} S{CELLS[ja][3]}: {gb.mean():+.2f} ({tstat(gb):+.1f}, n{len(gb)})")
        out.append(f"| {nm}{' (n<30)' if nn_ < 30 else ''} | {nn_} | {cnt[0]} / {cnt[1]} / {cnt[2]} | {c[0]} H{c[1]} T{c[2]} S{c[3]} | "
                   f"{tt(0.35)} | {tt(0.25)} | {tt(0.20)} | {xs[0]} | {xs[1]} |")
        summary["subsets"][nm] = dict(n=nn_, best=list(c), net25=float(m_[j] - 0.25), t25=float((m_[j] - 0.25) / se[j]))
    out.append("\nBrut ortalama (maliyetsiz) mevcut 60 dk kurali (TPSL H60 T=nat S=3) alt kumelere gore = basa-bas komisyon: " + "; ".join(
        f"{nm}: {gross_cache[('TPSL', 60, 'nat', 3)][msk].mean():+.2f}" for nm, msk in subsets.items() if msk.any()))

    sel: list = []
    for nm in ("TUMU", "trend_devam & skor>=95", "guncel kapilar (td+gll+llm)", "mode=trend_devam", "mode=unified", "skor>=95"):
        if nm in BESTC and BESTC[nm] not in sel:
            sel.append(BESTC[nm])
    for r_ in (("TPSL", 60, "nat", 3), ("TPSL", 60, 2, 3)):
        if r_ not in sel:
            sel.append(r_)
    FOCUS = [(nm, BESTC[nm], subsets[nm]) for nm in ("TUMU", "trend_devam & skor>=95", "guncel kapilar (td+gll+llm)", "mode=unified") if nm in BESTC]
    out.append(f"\nSecilen hucreler (sans / istikrar analizi): {sel}")
    out.append("\n### Secilen hucreler x alt kume (net@0.35 / net@0.25 / net@0.20)")
    for k in sel:
        rule, H, T, S = k
        g = gross_cache[k]
        hitv = mm[H][0] >= (TPa if T == "nat" else T)
        out.append(f"\n**{rule} H={H} T={T} S={S}**")
        out.append("| alt kume | n | hit% | brut ort | net@0.35 ort (t) | net@0.25 ort (t) | net@0.20 ort (t) | medyan@0.25 | kazanma%@0.25 | payoff@0.25 |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for nm, msk in subsets.items():
            if msk.sum() == 0:
                continue
            gg = g[msk]
            s35, s25, s20 = stats(gg - 0.35), stats(gg - 0.25), stats(gg - 0.20)
            flag = " (n<30)" if msk.sum() < 30 else ""
            out.append(f"| {nm}{flag} | {msk.sum()} | {100 * hitv[msk].mean():.1f} | {gg.mean():+.2f} | {s35['mean']:+.2f} ({s35['t']:+.1f}) | "
                       f"{s25['mean']:+.2f} ({s25['t']:+.1f}) | {s20['mean']:+.2f} ({s20['t']:+.1f}) | {s25['med']:+.2f} | {s25['win']:.0f} | {s25['payoff']:.2f} |")

    # ---- 4. şans tabanı
    out.append("\n## 4. Sans tabani (ayni sembol, rastgele anlar; son 30dk araligi ve getirisi eslestirilmis)")
    out.append(f"Her bildirim icin ayni sembolde <= {K_NULL} rastgele an: son 30dk high-low araligi (+-%25, en az 0.4pt) VE son 30dk getirisi (+-%25, en az 0.4pt) benzer; "
               "ileri pencere kesintisiz H dk mum icermeli; an, bildirim zamanindan |t|>=max(2sa, H) uzakta ('own') ya da sembolun HERHANGI bir bildiriminden "
               "uzakta ('all'). >=8 an bulunan bildirimler. Entry = o anin kapanisi. Karsilastirma esli: fark = gercek - sans.")
    cfgs_by_H: dict = collections.defaultdict(list)
    for k in sel:
        cfgs_by_H[k[1]].append(k)
    NULL: dict = {}
    for mode in ("own", "all"):
        for H in HS:
            NULL[(mode, H)] = chance_baseline(sample, store, mode, H, cfgs_by_H.get(H, []), rng)
    out.append("\nSans kapsami (esli satir sayisi / n):")
    out.append("| H | own | all |")
    out.append("|---|---|---|")
    for H in HS:
        out.append(f"| {H} | " + " | ".join(f"{NULL[(m_, H)]['cov'].sum()} ({100 * NULL[(m_, H)]['cov'].mean():.0f}%)" for m_ in ("own", "all")) + " |")
    out.append("\nHit tabani: gercek hit% / sans hit% (own) / fark (esli satirlar; fark t'si esli):")
    out.append("| H \\ T | " + " | ".join(f"{t}%" for t in TS) + " |")
    out.append("|---|" + "---|" * len(TS))
    summary["chance_hit"] = {}
    for H in HS:
        nl = NULL[("own", H)]
        cov = nl["cov"]
        cells = []
        for T in TS:
            if not cov.any():
                cells.append("-")
                continue
            real = (mm[H][0] >= T).astype(float)[cov]
            nu = nl["hit"][T][cov]
            d = real - nu
            cells.append(f"{100 * real.mean():.1f} / {100 * nu.mean():.1f} / {100 * d.mean():+.1f} (t{tstat(d):+.1f})")
            summary["chance_hit"][f"H{H}_T{T}"] = dict(real=100 * float(real.mean()), chance=100 * float(nu.mean()))
        out.append(f"| {H} | " + " | ".join(cells) + " |")
    out.append("\nTutma getirisi (H dk sonraki kapanis, maliyetsiz): gercek / sans(own) / fark, esli, ort % (t):")
    out.append("| H | gercek (tum n) | gercek (esli, own) | sans own | fark (t) | gercek (esli, all) | sans all | fark (t) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for H in HS:
        cells = []
        for m_ in ("own", "all"):
            nl = NULL[(m_, H)]
            cov = nl["cov"]
            if not cov.any():
                cells += ["-", "-", "-"]
                continue
            d = cend[H][cov] - nl["hold"][cov]
            cells += [f"{cend[H][cov].mean():+.2f}", f"{nl['hold'][cov].mean():+.2f}", f"{d.mean():+.2f} ({tstat(d):+.1f})"]
        out.append(f"| {H} | {cend[H].mean():+.2f} | " + " | ".join(cells) + " |")
    out.append("\nSecilen hucreler: gercek net@0.25 / sans net@0.25 / fark (esli t), 'own' ve 'all':")
    out.append("| hucre | kapsam | gercek ort | sans ort (own) | fark (t) | sans ort (all) | fark (t) | kume-dayanikli t fark (sembol-gun) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for k in sel:
        rule, H, T, S = k
        g = gross_cache[k] - 0.25
        cells = []
        real_m, tcl, cov_n = float("nan"), float("nan"), 0
        for m_ in ("own", "all"):
            nl = NULL[(m_, H)]
            cov = nl["cov"]
            if not cov.any():
                cells += ["-", "-"]
                continue
            nu = nl["gross"][k][cov] - 0.25
            d = g[cov] - nu
            cells += [f"{nu.mean():+.2f}", f"{d.mean():+.2f} ({tstat(d):+.1f})"]
            if m_ == "own":
                real_m = g[cov].mean()
                tcl = tclust(d, symday[cov])
                cov_n = int(cov.sum())
        out.append(f"| {rule} H{H} T{T} S{S} | {cov_n} | {real_m:+.2f} | " + " | ".join(cells) + f" | {tcl:+.1f} |")

    # ---- 5. istikrar
    def dedupH(H_: int, mask: np.ndarray | None = None) -> np.ndarray:
        keep, last = [], {}
        for ii in np.argsort(det_arr):
            if mask is not None and not mask[ii]:
                continue
            s = sym_arr[ii]
            if s in last and det_arr[ii] - last[s] < H_ * 60:
                continue
            last[s] = det_arr[ii]
            keep.append(ii)
        return np.array(keep, dtype=int)

    out.append("\n## 5. Istikrar (haftalik, sembol yogunlugu, tekrarsiz)")
    for lab, cell, msk in FOCUS:
        rule, H, T, S = cell
        g = gross_cache[cell]
        nl = NULL[("own", H)]
        out.append(f"\n### Odak: alt kume '{lab}' en iyi hucre {cell} (n={msk.sum()})")
        out.append("| hafta | n | net@0.35 ort (t) | net@0.25 ort (t) | kazanma%@0.25 | sans(own) net@0.25 | fark |")
        out.append("|---|---|---|---|---|---|---|")
        for w in sorted(set(week_arr)):
            m_ = msk & (week_arr == w)
            if m_.sum() < 5:
                continue
            s25, s35 = stats(g[m_] - 0.25), stats(g[m_] - 0.35)
            mc = m_ & nl["cov"]
            nu = (nl["gross"][cell][mc] - 0.25).mean() if mc.sum() >= 5 else np.nan
            d = (g[mc] - 0.25).mean() - nu if mc.sum() >= 5 else np.nan
            out.append(f"| {w}{' (n<30)' if m_.sum() < 30 else ''} | {s25['n']} | {s35['mean']:+.2f} ({s35['t']:+.1f}) | "
                       f"{s25['mean']:+.2f} ({s25['t']:+.1f}) | {s25['win']:.0f} | {nu:+.2f} | {d:+.2f} |")
        wm = [stats(g[msk & (week_arr == w)] - 0.25)["mean"] for w in sorted(set(week_arr)) if (msk & (week_arr == w)).sum() >= 30]
        out.append(f"n>=30 haftalarda net@0.25 pozitif olan: {sum(1 for x in wm if x > 0)}/{len(wm)}")
        dm = [(g[msk & (day_arr == d)] - 0.25).mean() for d in sorted(set(day_arr)) if (msk & (day_arr == d)).sum() >= 5]
        out.append(f"Gunluk (n>=5) ort net@0.25 pozitif gun: {sum(1 for x in dm if x > 0)}/{len(dm)}")
        net25 = (g - 0.25)[msk]
        sa = sym_arr[msk]
        sc_ = collections.Counter(sa)
        top5n = [str(s) for s, _ in sc_.most_common(5)]
        contrib: dict = collections.defaultdict(float)
        for s_, v in zip(sa, net25):
            contrib[str(s_)] += v
        top5c = [s_ for s_, _ in sorted(contrib.items(), key=lambda x: -x[1])[:5]]
        pos_total = sum(v for v in contrib.values() if v > 0)
        ex = ~np.isin(sa, top5c)
        pct = f"{100 * sum(contrib[s_] for s_ in top5c) / pos_total:.0f}" if pos_total > 0 else "-"
        out.append(f"Sembol yogunlugu: bildirim sayisina gore ilk-5 {top5n} = %{100 * sum(sc_[s_] for s_ in top5n) / msk.sum():.1f} bildirim. "
                   f"Net katkiya gore ilk-5 {top5c}: toplam net {sum(contrib[s_] for s_ in top5c):+.1f} (tum alt kume toplam net {net25.sum():+.1f}; "
                   f"pozitif katkilarin %{pct}'i). Bu 5 sembol DISLANINCA net@0.25 = "
                   f"{(net25[ex].mean() if ex.any() else float('nan')):+.2f} (t {tstat(net25[ex]):+.1f}, n={ex.sum()}); farkli sembol sayisi {len(sc_)}.")
        kp = dedupH(H, msk)
        if len(kp):
            gg = g[kp]
            a35, a25 = stats(gg - 0.35), stats(gg - 0.25)
            out.append(f"Tekrarsiz (ayni sembol >=H dk arayla): n={len(kp)}; net@0.35 {a35['mean']:+.2f} (t {a35['t']:+.1f}); "
                       f"net@0.25 {a25['mean']:+.2f} (t {a25['t']:+.1f}); kazanma {a25['win']:.0f}%")
        for cst in COSTS:
            x = (g - cst)[msk]
            out.append(f"  maliyet {cst}: naif t={tstat(x):+.2f}, (sembol,gun) kume t={tclust(x, symday[msk]):+.2f}, gun kume t={tclust(x, day_arr[msk]):+.2f}")
    out.append("\nTekrarsiz varyant - tum secilen hucreler (tum ornek):")
    out.append("| hucre | n tum | n tekrarsiz | tekrarsiz net@0.35 (t) | tekrarsiz net@0.25 (t) | tekrarsiz hit% | tum hit% |")
    out.append("|---|---|---|---|---|---|---|")
    for k in sel:
        rule_, H_, T_, S_s = k
        kp = dedupH(H_)
        gg = gross_cache[k][kp]
        hv = mm[H_][0] >= (TPa if T_ == "nat" else T_)
        a, b = stats(gg - 0.35), stats(gg - 0.25)
        out.append(f"| {rule_} H{H_} T{T_} S{S_s} | {n} | {len(kp)} | {a['mean']:+.2f} ({a['t']:+.1f}) | {b['mean']:+.2f} ({b['t']:+.1f}) | "
                   f"{100 * hv[kp].mean():.1f} | {100 * hv.mean():.1f} |")

    # ---- 6. örtüşme
    out.append("\n## 6. Ortusme (overlap)")
    out.append("| H | farkli (sembol,gun) | bildirim/(sembol,gun) ort | onceki H dk icinde ayni sembolde bildirimi olan satir % | tekrarsiz n | etkin bagimsiz tahmini |")
    out.append("|---|---|---|---|---|---|")
    npairs = len(set(symday))
    for H_ in HS:
        ov, lastd = 0, {}
        for ii in np.argsort(det_arr):
            s = sym_arr[ii]
            if s in lastd and det_arr[ii] - lastd[s] < H_ * 60:
                ov += 1
            lastd[s] = det_arr[ii]
        kp = dedupH(H_)
        out.append(f"| {H_} | {npairs} | {n / npairs:.2f} | {100 * ov / n:.0f} | {len(kp)} | ~{min(npairs, len(kp))} |")
    out.append("Not: farkli semboller ayni gun/saatte ortak faktorle birlikte hareket eder; gunluk kume-dayanikli t bunu yakalar.")
    out.append(f"\n(sure {time.time() - t0:.0f} sn)")
    summary["n"] = n
    return "\n".join(out) + "\n", summary


_ROWS_SQL = ("SELECT id, symbol, score, target_pct, price, mode, detected_at FROM monitoring_notifications "
             "WHERE detected_at >= %s ORDER BY detected_at")


def load_rows(conn, since_ts: float) -> list[dict]:
    keys = ("id", "symbol", "score", "target_pct", "price", "mode", "detected_at")
    return [dict(zip(keys, r)) for r in conn.execute(_ROWS_SQL, (since_ts,)).fetchall()]


def run_report(db_url: str, *, days: float = 30.0, since: str | None = None, entry_mode: str = "notif",
               seed: int = 11) -> tuple[str, dict]:
    import psycopg
    since_ts = (datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=TZ).timestamp()
                if since else time.time() - days * 86400.0)
    with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
        rows = load_rows(conn, since_ts)
        store = load_candles(conn, since_ts, with_open=True) if rows else CandleStore({})
    return generate_report(rows, store, since_ts=since_ts, seed=seed, entry_mode=entry_mode)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Uzun ufuk H x T x S x maliyet izgara raporu (bildirimler).")
    ap.add_argument("--days", type=float, default=30.0, help="Geriye donuk gun (varsayilan 30)")
    ap.add_argument("--since", default=None, help="Baslangic YYYY-MM-DD (Istanbul)")
    ap.add_argument("--out", default=None, help="Markdown rapor dosyasi")
    ap.add_argument("--entry", choices=("notif", "open"), default="notif",
                    help="notif: bildirim fiyati; open: bildirim sonrasi ilk mumun acilisi")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if args.days <= 0:
        print("HATA: --days pozitif olmali.", file=sys.stderr)
        return 2
    try:
        md, _ = run_report(_db_url(), days=args.days, since=args.since, entry_mode=args.entry, seed=args.seed)
    except Exception as exc:  # noqa: BLE001 - CLI sınırı
        print(f"HATA: rapor uretilemedi ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
