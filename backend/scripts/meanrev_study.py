"""Ortalamaya dönüş + PASİF (limit) icra çalışması — Binance TR TRY spot, uzun-yönlü (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye YAZMAZ).

Tez: 90 günlük araştırmada momentum/patlama takibinin brüt yönsel kenarı yok; tek negatif-olmayan aileler ters yön (reversal) ve vadeli baz önceliği.
Zayıflığı BEKLEYEN limit alışla almak doğal icra (maker %0,0675, kayma yok) → net pozitif mi? Bu betik tetik × icra × çıkış ızgarasını simüle eder.

Tetikler (önceden belirlenmiş; 5 dk kapanışında karar, t_dec = ot+5 dk, 12 bar (1 sa) soğuma):
  A  15 dk getirisi kesitte en alt %10 ∧ 60 dk piyasa (eşit ağırlık) getirisi ≥ 0
  B  5m kapanış < Bollinger(20,2) alt bant ∧ MFI14 < 20
  D  vadeli baz z-skoru (fu.basis_z, flow_futures ile aynı hizalama ts+5 dk) kesitte en üst %20
  C  likidite süpürmesi: yeni 24 sa dip, 3 bar içinde önceki dibin üstünde kapanış
  AD/BD/CD  A/B/C ∧ D (baz kapısı)
Evren: 24 sa TRY hacmi ≥ 5M ve ≥ 50M (tetik kesitleri ve rastgele havuz o evrende).
İcra: LİMİT alış = tetik kapanışı × (1 − d), d ∈ {0, %0,1, %0,3}, geçerlilik V ∈ {5, 15} dk; dolum: sonraki 1 dk LOW ≤ limit (M0) / VWAP ≤ limit (M1, M2);
kâr al LİMİT satış entry×(1+T), T ∈ {0,4; 0,8; 1,2}: HIGH ≥ seviye (M0, M1) / VWAP ≥ seviye (M2); stop %2/%3 ve zaman stopu 60/120/240 dk piyasa (taker+%0,15 kayma).
Karşılaştırma: aynı sinyallerle piyasa girişi (taker+%0,15 kayma; TP maker "TK1" ya da TP de piyasa "TK2") ve ATR'si eşleşmiş rastgele girişler (aynı icra).

Aşamalar (`--stages`): data (DB → önbellek), run (simülasyon → agg.npz), report (→ report.md; ayrı betik bölümü)
Kullanım (backend/): DATABASE_URL=postgresql://... python scripts/meanrev_study.py --stages data,run,report
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import meanrev as M  # noqa: E402
from app.rescan.exit_sim import FEE_MAKER_PCT, FEE_TAKER_PCT  # noqa: E402

P90_DEFAULT = (r"C:\Users\Erkan\AppData\Local\Temp\claude\D--PROJELLER-sclpragnt\bb25c086-ec89-43e9-a810-f345b61672ad\scratchpad\p90cache")
SLIP = 0.15
MIN_QUOTE = {5: 5_000_000.0, 50: 50_000_000.0}
UNIVS = (5, 50)
TRIGS = ("A", "B", "C", "D", "AD", "BD", "CD")
DS = (0.0, 0.1, 0.3)
VS = (5, 15)
MODES = (("low", "high"), ("vwap", "high"), ("vwap", "vwap"))      # (dolum kuralı, TP kuralı): M0 iyimser, M1 katı giriş, M2 katı giriş+çıkış
MODE_NAMES = ("M0 dokunma", "M1 vwap-giriş", "M2 vwap-giriş+çıkış")
TPS = (0.4, 0.8, 1.2)
SLS = (2.0, 3.0)
TMS = (60, 120, 240)
N_EXIT = len(TPS) * len(SLS) * len(TMS)                          # 18
N_FILL = len(MODES) * len(DS)                                     # 9
N_MAKER = len(VS) * N_FILL * N_EXIT                               # 324
N_TAKER = 2 * 2 * N_EXIT                                          # 72 (TP kuralı {high,vwap} × maliyet {TK1,TK2})
N_CFG = N_MAKER + N_TAKER                                         # 396
N_GRP = len(TRIGS) * len(UNIVS)                                   # 14 sinyal grubu (+14 rastgele)
D_DAYS = 90
BLOCKS = {"B1": (1, 31), "B2": (31, 61), "B3": (61, 90)}
BLOCK_LABEL = {"B1": "07-20..08-18", "B2": "08-19..09-17", "B3": "09-18..10-16"}
COOL = 12
W_FILL = 15
W_EXIT = 240
W_BIG = W_FILL + W_EXIT + 1
STABLE_STD = 0.0004
R_DRAW = 2


def exit_specs() -> list[tuple[float, float, int]]:
    return [(t, s, m) for t in TPS for s in SLS for m in TMS]


def cfg_name(c: int) -> str:
    ex = exit_specs()[c % N_EXIT]
    base = f"T{ex[0]:g} SL{ex[1]:g} Z{ex[2]}"
    if c < N_MAKER:
        v = c // (N_FILL * N_EXIT)
        fc = (c // N_EXIT) % N_FILL
        mode, di = divmod(fc, len(DS))
        return f"maker d{DS[di]:g} V{VS[v]} {MODE_NAMES[mode].split()[0]} {base}"
    k = (c - N_MAKER) // N_EXIT
    return f"taker {('TK1', 'TK2')[k % 2]} tp-{('high', 'vwap')[k // 2]} {base}"


def grp_name(g: int) -> str:
    return f"{TRIGS[g // len(UNIVS)]}|{UNIVS[g % len(UNIVS)]}M"


def out_dir(args) -> Path:
    p = Path(args.out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------------------------------------ 1. veri
def stage_data(args) -> None:
    import psycopg
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    p90 = Path(args.p90)
    out = out_dir(args)
    (out / "m1").mkdir(exist_ok=True)
    syms = sorted(set(p.stem for p in (p90 / "d1").glob("*.npy")) & set(p.stem for p in (p90 / "d5").glob("*.npy")))
    if "USDTTRY" not in syms:
        syms = sorted(set(syms) | {"USDTTRY"})
    t0 = time.time()
    first = np.load(p90 / "d5" / "BTCTRY.npy", mmap_mode="r")
    T0 = int(first[0, 0])
    last = 0
    for s in syms:
        a = np.load(p90 / "d5" / f"{s}.npy", mmap_mode="r")
        last = max(last, int(a[-1, 0]))
    T5 = (last - T0) // M.BAR5_MS + 1
    T1 = 5 * T5
    S = len(syms)
    P = {k: np.full((S, T5), np.nan) for k in ("O", "H", "L", "C", "V")}
    QV = np.full((S, T5), np.nan, dtype=np.float32)
    for si, s in enumerate(syms):
        a = np.load(p90 / "d5" / f"{s}.npy")
        idx = ((a[:, 0] - T0) // M.BAR5_MS).astype(int)
        ok = (idx >= 0) & (idx < T5)
        for k, col in (("O", 1), ("H", 2), ("L", 3), ("C", 4), ("V", 5)):
            P[k][si, idx[ok]] = a[ok, col]
        QV[si, idx[ok]] = a[ok, 6]
    print(f"[data] 5m paneller S={S} T5={T5} ({time.time() - t0:.0f} sn)", flush=True)
    usd_i = syms.index("USDTTRY")
    usd = P["C"][usd_i].copy()
    last_v, gap = np.nan, 0                                           # USDTTRY ≤ 6 bar ileri doldur (flowfut_study ile aynı)
    for j in range(T5):
        if np.isfinite(usd[j]):
            last_v, gap = usd[j], 0
        else:
            gap += 1
            if gap <= 6:
                usd[j] = last_v
    BZ = np.full((S, T5), np.nan, dtype=np.float32)
    BAS = np.full((S, T5), np.nan, dtype=np.float32)
    with psycopg.connect(url, connect_timeout=10) as conn:
        conn.read_only = True
        for si, s in enumerate(syms):
            # 1 dk yoğun ızgara (O,H,L,C,VWAP); eksik dakika = önceki kapanışta düz mum, VWAP NaN (işlem yok)
            p1 = p90 / "d1" / f"{s}.npy"
            if p1.exists():
                a = np.load(p1)
                idx = ((a[:, 0] - T0) // M.BAR1_MS).astype(int)
                ok = (idx >= 0) & (idx < T1)
                dense = np.full((T1, 5), np.nan)
                for k, col in enumerate((1, 2, 3, 4)):
                    dense[idx[ok], k] = a[ok, col]
                c = dense[:, 3]
                fin = np.isfinite(c)
                pos = np.maximum.accumulate(np.where(fin, np.arange(T1), -1))
                cf = np.where(pos >= 0, c[np.maximum(pos, 0)], np.nan)
                for k in range(4):
                    dense[:, k] = np.where(np.isfinite(dense[:, k]), dense[:, k], cf)
                rows = conn.execute("SELECT minute_open_ms, vwap::float8 FROM historical_trade_flow WHERE symbol=%s", (s,)).fetchall()
                if rows:
                    r = np.array(rows, dtype=float)
                    vi = ((r[:, 0] - T0) // M.BAR1_MS).astype(int)
                    okv = (vi >= 0) & (vi < T1) & (r[:, 1] > 0)
                    dense[vi[okv], 4] = r[okv, 1]
                np.save(out / "m1" / f"{s}.npy", dense.astype(np.float32))
            mp = conn.execute("SELECT perp_symbol, multiplier FROM futures_symbol_map WHERE try_symbol=%s", (s,)).fetchone()
            if mp is not None and s != "USDTTRY":
                m = conn.execute("SELECT ts_ms, sum_open_interest, sum_open_interest_value FROM hist_futures_metrics WHERE perp_symbol=%s "
                                 "AND sum_open_interest > 0 AND sum_open_interest_value > 0 ORDER BY ts_ms", (mp[0],)).fetchall()
                if m:
                    m = np.array(m, dtype=float)
                    bas, z = M.basis_z_series(T0, T5, P["C"][si], usd, m[:, 0].astype(np.int64), m[:, 1], m[:, 2], float(mp[1]))
                    BZ[si], BAS[si] = z, bas
            if (si + 1) % 25 == 0:
                print(f"[data] {si + 1}/{S} ({time.time() - t0:.0f} sn)", flush=True)
    np.savez_compressed(out / "p5.npz", syms=np.array(syms), T0=T0, QV=QV, BZ=BZ, BAS=BAS, **P)
    print(f"[data] bitti T0={T0} T5={T5} ({time.time() - t0:.0f} sn) → {out}", flush=True)


# ------------------------------------------------------------------------------------------------ 2. tetik panelleri
def load_p5(out: Path) -> dict:
    z = np.load(out / "p5.npz", allow_pickle=False)
    d = {k: z[k] for k in ("O", "H", "L", "C", "V", "QV", "BZ", "BAS")}
    d["syms"] = [str(s) for s in z["syms"]]
    d["T0"] = int(z["T0"])
    return d


def build_panels(d: dict) -> dict:
    S, T5 = d["C"].shape
    ret3 = np.full((S, T5), np.nan, dtype=np.float32)
    ret12 = np.full((S, T5), np.nan, dtype=np.float32)
    atr = np.full((S, T5), np.nan, dtype=np.float32)
    bb = np.zeros((S, T5), dtype=bool)
    sw = np.zeros((S, T5), dtype=bool)
    q24 = np.zeros((S, T5), dtype=np.float32)
    med = np.zeros(S)
    for s in range(S):
        h, l, c, v = d["H"][s], d["L"][s], d["C"][s], d["V"][s]
        ret3[s] = M.simple_ret(c, 3)
        r12 = M.simple_ret(c, 12)
        ret12[s] = r12
        atr[s] = M.atr_pct(h, l, c, 14)
        lo = M.bollinger_lower(c, 20, 2.0)
        mf = M.mfi(h, l, c, v, 14)
        with np.errstate(invalid="ignore"):
            bb[s] = (c < lo) & (mf < 20.0)
        sw[s] = M.sweep_trigger(l, c, 288, 3)
        q24[s] = M.roll_sum(np.nan_to_num(d["QV"][s].astype(float), nan=0.0), 288).astype(np.float32)
        x = np.abs(r12[np.isfinite(r12)])
        med[s] = np.median(x) if len(x) else 0.0
    stable = med < STABLE_STD
    excl = stable | np.array([s == "USDTTRY" for s in d["syms"]])
    return {"ret3": ret3, "ret12": ret12, "atr": atr, "bb": bb, "sw": sw, "q24": q24, "excl": excl, "stable": [d["syms"][i] for i in np.flatnonzero(stable)]}


def day_of_bar(T5: int) -> np.ndarray:
    return ((np.arange(T5) + 1) * 5) // 1440


def build_trigger_masks(d: dict, pn: dict) -> tuple[np.ndarray, list[np.ndarray]]:
    """(valid[u] (S,T), masks[g] (S,T) bool) — g = trig_idx * 2 + univ_idx. Gün/örtüşme/soğuma uygulanmış."""
    S, T5 = d["C"].shape
    day = day_of_bar(T5)
    in_range = (day >= 1) & (day < D_DAYS)
    covered = (np.arange(T5) + 1) * 5 + W_BIG < 5 * T5
    base_ok = in_range & covered
    fin_c = np.isfinite(d["C"])
    valid = {}
    flags: dict = {}
    for u in UNIVS:
        V = (pn["q24"] >= MIN_QUOTE[u]) & fin_c & ~pn["excl"][:, None]
        valid[u] = V
        mkt = M.xs_mean(pn["ret12"], V)
        A = M.xs_flag(pn["ret3"], V, 0.10, "low") & (np.nan_to_num(mkt, nan=-1.0) >= 0.0)[None, :]
        Bm = pn["bb"] & V
        Cm = pn["sw"] & V
        bz = d["BZ"]
        Dm = M.xs_flag(bz, V & np.isfinite(bz), 0.20, "high")
        flags[u] = {"A": A, "B": Bm, "C": Cm, "D": Dm, "AD": A & Dm, "BD": Bm & Dm, "CD": Cm & Dm}
    masks = []
    for t in TRIGS:
        for u in UNIVS:
            m = flags[u][t] & valid[u] & base_ok[None, :]
            masks.append(M.cooldown(m, COOL))
    return np.stack([valid[5], valid[50]]), masks


# ------------------------------------------------------------------------------------------------ 3. simülasyon çekirdeği
def gather(m1: np.ndarray, base: np.ndarray, width: int) -> np.ndarray:
    """(N, width, 5) float64 — O,H,L,C,VWAP; satır = base + 0..width−1 dakika."""
    idx = base[:, None] + np.arange(width)[None, :]
    return m1[idx].astype(np.float64)


def sim_chunk(m1: np.ndarray, bar: np.ndarray, P0: np.ndarray) -> dict:
    """Bir sembolün olay satırları (bar = 5 dk karar barı indeksi, P0 = tetik kapanışı) için tüm yapılandırmaları hesaplar.
    Dönüş: net/gross (N, N_CFG) float32 (dolmadı = NaN), reason (N, N_CFG) int8 (−1 = yok), kf (N, N_FILL) dolum gecikmesi (W_FILL = dolmadı), r60, rV (N, 2)."""
    N = len(bar)
    base = (bar + 1) * 5                                           # karar anında AÇILAN 1 dk bar
    W = gather(m1, base, W_BIG)
    O, H, L, C, VW = (W[:, :, k] for k in range(5))
    net = np.full((N, N_CFG), np.nan, dtype=np.float32)
    gross = np.full((N, N_CFG), np.nan, dtype=np.float32)
    rsn = np.full((N, N_CFG), -1, dtype=np.int8)
    kf = np.full((N, N_FILL), W_FILL, dtype=np.int16)
    ex = exit_specs()
    f_m, f_t = FEE_MAKER_PCT, FEE_TAKER_PCT
    ar = np.arange(W_EXIT)
    for mode_i, (fill_mode, tp_mode) in enumerate(MODES):
        for di, dpct in enumerate(DS):
            fc = mode_i * len(DS) + di
            limit = P0 * (1.0 - dpct / 100.0)
            k = M.limit_buy_fill(L[:, :W_FILL], VW[:, :W_FILL], limit, W_FILL, fill_mode)
            kf[:, fc] = k
            sel = np.flatnonzero(k < W_FILL)
            if len(sel) == 0:
                continue
            kk = k[sel]
            cols = kk[:, None] + ar[None, :]
            Ow = np.take_along_axis(O[sel], cols, axis=1); Hw = np.take_along_axis(H[sel], cols, axis=1)
            Lw = np.take_along_axis(L[sel], cols, axis=1); Cw = np.take_along_axis(C[sel], cols, axis=1); Vw = np.take_along_axis(VW[sel], cols, axis=1)
            entry = limit[sel]
            tpi, sli = M.first_hits(Hw, Lw, Vw, entry, TPS, SLS, tp_mode, W_EXIT, skip_first_tp=True)
            for ei, (T, sl, nb) in enumerate(ex):
                # zaman stopu nb için: nb'den sonraki vuruşlar yok sayılır (resolve_exit indeks ≥ nb = yok)
                res = M.resolve_exit(tpi[T], sli[sl], nb, entry, Ow, Cw, T, sl, slip_pct=SLIP, fee_entry_pct=f_m, fee_tp_pct=f_m, fee_stop_pct=f_t, o0=entry)
                for vi, v in enumerate(VS):
                    c = (vi * N_FILL + fc) * N_EXIT + ei
                    m = kk < v
                    rows = sel[m]
                    net[rows, c] = res["net"][m]; gross[rows, c] = res["gross"][m]; rsn[rows, c] = res["reason"][m]
    # piyasa girişi (taker): bir sonraki 1 dk barın açılışı × (1 + kayma); TP kuralı {high, vwap}; TK1 = TP maker, TK2 = TP de piyasa (kayma + taker)
    entry = O[:, 0] * (1.0 + SLIP / 100.0)
    Ow, Hw, Lw, Cw, Vw = O[:, :W_EXIT], H[:, :W_EXIT], L[:, :W_EXIT], C[:, :W_EXIT], VW[:, :W_EXIT]
    for tpm_i, tpm in enumerate(("high", "vwap")):
        tpi, sli = M.first_hits(Hw, Lw, Vw, entry, TPS, SLS, tpm, W_EXIT, skip_first_tp=False)
        for var in range(2):
            kidx = tpm_i * 2 + var
            for ei, (T, sl, nb) in enumerate(ex):
                res = M.resolve_exit(tpi[T], sli[sl], nb, entry, Ow, Cw, T, sl, slip_pct=SLIP, fee_entry_pct=f_t, fee_tp_pct=(f_m if var == 0 else f_t),
                                     fee_stop_pct=f_t, tp_slip_pct=(0.0 if var == 0 else SLIP), o0=O[:, 0])
                c = N_MAKER + kidx * N_EXIT + ei
                net[:, c] = res["net"]; gross[:, c] = res["gross"]; rsn[:, c] = res["reason"]
    r60 = C[:, 59] / P0 - 1.0
    rv = np.stack([C[:, v - 1] / P0 - 1.0 for v in VS], axis=1)
    return {"net": net, "gross": gross, "rsn": rsn, "kf": kf, "r60": r60, "rv": rv}


class Acc:
    """Grup × yapılandırma × gün toplamları (adet, net, brüt, TP adedi, SL adedi) + dolum/ters-seçilim istatistikleri."""

    def __init__(self):
        G = 2 * N_GRP
        self.n = np.zeros((G, N_CFG, D_DAYS)); self.s = np.zeros((G, N_CFG, D_DAYS)); self.g = np.zeros((G, N_CFG, D_DAYS))
        self.tp = np.zeros((G, N_CFG, D_DAYS)); self.sl = np.zeros((G, N_CFG, D_DAYS))
        # adv[g, hücre(vi*N_FILL+fc), dolu(0)/dolmadı(1), gün, {adet, Σ r60, Σ rV}]
        self.adv = np.zeros((G, len(VS) * N_FILL, 2, D_DAYS, 3))
        self.sig_n = np.zeros((G, D_DAYS))

    def add(self, mem: np.ndarray, day: np.ndarray, r: dict) -> None:
        net, gross, rsn, kf = r["net"], r["gross"], r["rsn"], r["kf"]
        fin = np.isfinite(net)
        netz = np.where(fin, net, 0.0); grz = np.where(fin, gross, 0.0)
        tpi = (rsn == M.R_TP).astype(np.float32); sli = (rsn == M.R_SL).astype(np.float32)
        # hücre dolu maskesi (N, vi*N_FILL+fc)
        cell_filled = np.concatenate([(kf < v) for v in VS], axis=1)
        rv_cell = np.concatenate([np.repeat(r["rv"][:, [vi]], N_FILL, axis=1) for vi in range(len(VS))], axis=1)
        r60 = np.repeat(r["r60"][:, None], cell_filled.shape[1], axis=1)
        for g in range(mem.shape[1]):
            sel = np.flatnonzero(mem[:, g])
            if len(sel) == 0:
                continue
            o = np.argsort(day[sel], kind="stable")
            sel = sel[o]
            ud, starts = np.unique(day[sel], return_index=True)
            self.n[g][:, ud] += np.add.reduceat(fin[sel].astype(np.float64), starts, axis=0).T
            self.s[g][:, ud] += np.add.reduceat(netz[sel].astype(np.float64), starts, axis=0).T
            self.g[g][:, ud] += np.add.reduceat(grz[sel].astype(np.float64), starts, axis=0).T
            self.tp[g][:, ud] += np.add.reduceat(tpi[sel].astype(np.float64), starts, axis=0).T
            self.sl[g][:, ud] += np.add.reduceat(sli[sel].astype(np.float64), starts, axis=0).T
            self.sig_n[g, ud] += np.diff(np.append(starts, len(sel)))
            f = cell_filled[sel]
            for flag, idx in ((f, 0), (~f, 1)):
                fl = flag.astype(np.float64)
                cnt = np.add.reduceat(fl, starts, axis=0)
                s60 = np.add.reduceat(fl * np.nan_to_num(r60[sel]), starts, axis=0)
                srv = np.add.reduceat(fl * np.nan_to_num(rv_cell[sel]), starts, axis=0)
                tmp = self.adv[g, :, idx]                      # (hücre, gün, 3) görünüm
                tmp[:, ud, 0] += cnt.T
                tmp[:, ud, 1] += s60.T
                tmp[:, ud, 2] += srv.T


def stage_run(args) -> None:
    out = out_dir(args)
    t0 = time.time()
    d = load_p5(out)
    S, T5 = d["C"].shape
    pn = build_panels(d)
    print(f"[run] paneller hazır ({time.time() - t0:.0f} sn); pegli dışlanan: {pn['stable']}", flush=True)
    valid, masks = build_trigger_masks(d, pn)
    day = day_of_bar(T5)
    ev_cnt = [int(m.sum()) for m in masks]
    print("[run] olay sayıları (sinyal): " + ", ".join(f"{grp_name(g)}={c}" for g, c in enumerate(ev_cnt)), flush=True)
    if args.count_only:
        return
    block_of_day = np.full(D_DAYS, -1)
    for bi, (a, b) in enumerate(BLOCKS.values()):
        block_of_day[a:b] = bi
    rng = np.random.default_rng(args.seed)
    acc = Acc()
    base_ok = (day >= 1) & (day < D_DAYS) & ((np.arange(T5) + 1) * 5 + W_BIG < 5 * T5)
    tot_rows = 0
    done_syms = 0
    for si, s in enumerate(d["syms"]):
        if not (out / "m1" / f"{s}.npy").exists() or pn["excl"][si]:
            continue
        if args.max_syms and done_syms >= args.max_syms:
            break
        sig_bars = [np.flatnonzero(masks[g][si]) for g in range(N_GRP)]
        if not any(len(b) for b in sig_bars):
            continue
        # sinyal satırları: bar birleşimi + üyelik
        ub = np.unique(np.concatenate(sig_bars))
        mem_sig = np.zeros((len(ub), 2 * N_GRP), dtype=bool)
        for g in range(N_GRP):
            mem_sig[np.searchsorted(ub, sig_bars[g]), g] = True
        # eşleştirilmiş rastgele satırlar (grup başına, R_DRAW çekiliş, ATR benzer, aynı blok/evren)
        rbars, rgrp = [], []
        for g in range(N_GRP):
            eb = sig_bars[g]
            if len(eb) == 0:
                continue
            u = UNIVS[g % len(UNIVS)]
            pool_mask = valid[0 if u == 5 else 1][si] & base_ok & np.isfinite(pn["atr"][si])
            pool_bars = np.flatnonzero(pool_mask)
            for bi in range(len(BLOCKS)):
                pb = pool_bars[block_of_day[day[pool_bars]] == bi]
                ebb = eb[block_of_day[day[eb]] == bi]
                if len(ebb) == 0 or len(pb) == 0:
                    continue
                pick = M.match_random(pn["atr"][si][ebb].astype(float), pn["atr"][si][pb].astype(float), pb, R_DRAW, rng, width=0.05)
                pk = pick[pick >= 0]
                rbars.append(pk); rgrp.append(np.full(len(pk), g))
        rb = np.concatenate(rbars) if rbars else np.zeros(0, dtype=np.int64)
        rg = np.concatenate(rgrp) if rgrp else np.zeros(0, dtype=np.int64)
        bars = np.concatenate([ub, rb])
        mem = np.concatenate([mem_sig, np.zeros((len(rb), 2 * N_GRP), dtype=bool)], axis=0)
        mem[len(ub) + np.arange(len(rb)), N_GRP + rg] = True
        P0 = d["C"][si][bars].astype(float)
        good = np.isfinite(P0)
        bars, mem, P0 = bars[good], mem[good], P0[good]
        m1 = np.load(out / "m1" / f"{s}.npy", mmap_mode="r")
        m1 = np.asarray(m1)
        CH = 3000
        for a in range(0, len(bars), CH):
            sl = slice(a, a + CH)
            r = sim_chunk(m1, bars[sl], P0[sl])
            acc.add(mem[sl], day[bars[sl]], r)
        tot_rows += len(bars)
        done_syms += 1
        if done_syms % 20 == 0 or args.max_syms:
            print(f"[run] {si + 1}/{S} {s} satır={tot_rows} ({time.time() - t0:.0f} sn)", flush=True)
    np.savez_compressed(out / ("agg_test.npz" if args.max_syms else "agg.npz"), n=acc.n, s=acc.s, g=acc.g, tp=acc.tp, sl=acc.sl, adv=acc.adv, sig_n=acc.sig_n, ev_cnt=np.array(ev_cnt))
    print(f"[run] bitti, toplam simüle satır={tot_rows} ({time.time() - t0:.0f} sn)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="data,run,report")
    ap.add_argument("--p90", default=P90_DEFAULT)
    ap.add_argument("--out-dir", default=str(_BACKEND_DIR / "work" / "meanrev"))
    ap.add_argument("--db-url", default="")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--max-syms", type=int, default=0, help="yalnız ilk N sembol (zamanlama / duman testi)")
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        if st == "data":
            stage_data(args)
        elif st == "run":
            stage_run(args)
        elif st == "report":
            from scripts import meanrev_report
            meanrev_report.stage_report(args)
        else:
            sys.exit(f"bilinmeyen aşama: {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
