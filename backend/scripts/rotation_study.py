"""Altcoin rotasyonu / göreli güç çalışması — UZUN VADE (4 sa, 1 g, 3 g tutma) (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye YAZMAZ).

Soru: 5–60 dk ufkunda net-pozitif kenar bulunamadı (maliyet ≈ %0,53 gidiş-dönüş). ALTCOIN_REHBERI'nin fikirleri — BTC'ye göre göreli güç, genişlik,
altseason-benzeri sepet gücü, 2–4 hafta momentum→dönüş — hareketlerin maliyete göre büyük olduğu UZUN ufuklarda (4 sa / 1 g / 3 g) uzun-yönlü spot
TRY stratejisi olarak net pozitif mi?

Veri: `historical_candles` 15m (salt-okunur) → önbellek → saatlik paneller. Karar saat barının KAPANIŞINDA (yalnız geçmiş), dolum karar anından
`--delay` (varsayılan 1) 15 dk bar SONRAKİ açılış; bacak başına ücret %0,1125 + kayma %0,15 (exit_sim.py ile aynı), maliyet devir (|Δw|) temelli.
Genişlik / göreli güç / EW endeks: `app/rescan/breadth.py`; sepet, portföy, DSR: `app/rescan/rotation.py` (testli, saf).

Aşamalar (`--stages`): data (DB → önbellek npz), run (stratejiler + yürüyen ileri + DSR → work/rotation/*.json,csv), report (→ report.md)
Kullanım (backend/):  DATABASE_URL=postgresql://... python scripts/rotation_study.py --stages data,run,report
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import breadth as B  # noqa: E402
from app.rescan import rotation as R  # noqa: E402
from app.rescan.exit_sim import FEE_LEG_PCT  # noqa: E402
from app.rescan import exit_sim as _XS  # noqa: E402

SLIP_PCT = 0.15                               # exit_sim sözleşmesi: giriş ve çıkışta ayrı ayrı
COST_LEG = (FEE_LEG_PCT + SLIP_PCT) / 100.0   # (a) taker: 0,002625 / bacak → gidiş-dönüş %0,525
FEE_MAKER = float(getattr(_XS, "FEE_MAKER_PCT", 0.0675))
COST_LEG_MAKER = FEE_MAKER / 100.0            # (b) bekleyen LİMİT: maker %0,0675 / bacak, kayma YOK → gidiş-dönüş %0,135 (dolum riski modellenmez)
MIN_QUOTE_24H = 5_000_000.0                   # TRY, breadth_study ile aynı likidite eşiği
STABLE_STD = 0.0004                           # 1 sa getiri medyan |r| altında → pegli çift, evrenden çıkar
HOURS = 24
N_DAYS = 90
BLOCKS = {"B1": (1, 31), "B2": (31, 61), "B3": (61, 90)}      # gün indeksleri [a, b); gün 0 = 2026-07-19 (TR, ısınma), gün 1 = 07-20
BLOCK_LABEL = {"B1": "07-20..08-18", "B2": "08-19..09-17", "B3": "09-18..10-16"}
LOOKBACKS_SHORT = (1, 3, 7)
LOOKBACKS_LONG = (14, 21, 28)
KS = (5, 10)
HOLDS = {"4s": (4, 1), "1g": (24, 1), "3g": (72, 3)}          # ad → (yeniden denge saati, kol sayısı); kollar 24 sa arayla kayık
MIN_TRAIN_DAYS = 15


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
    t0 = time.time()
    with psycopg.connect(url, connect_timeout=10) as conn:
        conn.read_only = True
        rows = conn.execute(
            "SELECT symbol, open_time, open, high, low, close, quote_volume FROM historical_candles "
            "WHERE timeframe='15m' ORDER BY symbol, open_time").fetchall()
    print(f"[data] {len(rows)} satır ({time.time() - t0:.0f} sn)", flush=True)
    syms = sorted({r[0] for r in rows})
    sid = {s: i for i, s in enumerate(syms)}
    arr = np.array([(sid[r[0]], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows], dtype=float)
    del rows
    BAR = 900_000
    t0_ms = int(arr[:, 1].min())
    T = int((arr[:, 1].max() - t0_ms) // BAR) + 1
    names = ("O", "H", "L", "C", "QV")
    P = {n: np.full((len(syms), T), np.nan) for n in names}
    si = arr[:, 0].astype(int)
    ti = ((arr[:, 1] - t0_ms) // BAR).astype(int)
    for c, n in enumerate(names):
        P[n][si, ti] = arr[:, 2 + c]
    Path(args.cache).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.cache, syms=np.array(syms), t0_ms=t0_ms, **P)
    print(f"[data] S={len(syms)} T15={T} t0={datetime.fromtimestamp(t0_ms / 1000, timezone.utc)} → {args.cache} ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ 2. paneller
class Hourly:
    """Saatlik paneller (S, T). Saat barı k = 15 dk barlar 4k..4k+3; kapanış C1[:, k]; karar k kapanışında; dolum PX[:, k] =
    15 dk bar 4(k+1)+delay açılışı. Sütun ekseni zaman (breadth.py sözleşmesi: son eksen zaman)."""

    def __init__(self, cache: str, delay: int):
        z = np.load(cache, allow_pickle=False)
        self.syms = [str(s) for s in z["syms"]]
        self.t0_ms = int(z["t0_ms"])
        O, C, QV = (z[n] for n in ("O", "C", "QV"))
        S, T15 = C.shape
        T = (T15 - delay - 4) // 4                                   # PX[T−1] için 4T+delay < T15
        n4 = 4 * T
        self.T = T
        self.C1 = C[:, 3:n4:4].copy()                                # (S,T) saat kapanışı
        self.QV1 = np.where(np.isfinite(QV[:, :n4]).reshape(S, T, 4).any(axis=2), np.nansum(QV[:, :n4].reshape(S, T, 4), axis=2), np.nan)
        self.PX = O[:, 4 + delay: 4 * T + delay + 1: 4].copy()       # (S,T) dolum fiyatı
        self.delay = delay

    def day_of(self, k):
        return np.asarray(k) // HOURS


def ffill_limit(x: np.ndarray, limit: int) -> np.ndarray:
    """Son eksende ileri doldur (en çok `limit` ardışık eksik bar)."""
    out = x.copy()
    S, T = x.shape
    last = np.full(S, np.nan)
    gap = np.zeros(S, dtype=int)
    for j in range(T):
        col = x[:, j]
        fin = np.isfinite(col)
        last = np.where(fin, col, last)
        gap = np.where(fin, 0, gap + 1)
        out[:, j] = np.where(fin, col, np.where(gap <= limit, last, np.nan))
    return out


def build_market(hp: Hourly, min_quote: float = MIN_QUOTE_24H) -> dict:
    """Ortak saatlik hazırlık: geçerli evren V, fiyat/getiri, BTC, EW endeks, genişlik."""
    syms = hp.syms
    btc = syms.index("BTCTRY")
    C1 = ffill_limit(hp.C1, 6)
    PX = ffill_limit(hp.PX, 6)
    V = B.valid_universe(hp.QV1, min_quote, bars_24h=HOURS) & np.isfinite(C1) & np.isfinite(PX)
    c1h = C1[:, 1:] / C1[:, :-1] - 1.0
    med = np.nanmedian(np.abs(c1h), axis=1)
    stable = np.isfinite(med) & (med < STABLE_STD)
    V[stable] = False
    if "USDTTRY" in syms:
        V[syms.index("USDTTRY")] = False
    with np.errstate(invalid="ignore", divide="ignore"):
        r = PX[:, 1:] / PX[:, :-1] - 1.0
    r = np.concatenate([np.full((len(syms), 1), np.nan), r], axis=1)
    mu, sd = B.xs_mean_std(r * 100.0, V, clip=30.0)
    ewi = B.ew_index(C1, V)
    ema24 = B.ema(C1, HOURS)
    return {"btc": btc, "C1": C1, "PX": PX, "V": V, "r": r, "stable": [syms[i] for i in np.flatnonzero(stable)],
            "mkt_r": mu / 100.0, "ewi": ewi, "pct_above": B.pct_above(C1, ema24, V)}


# ------------------------------------------------------------------------------------------------ 3. skorlar / kapılar
def lag_ret(C1: np.ndarray, hours: int) -> np.ndarray:
    return B.lag_return(C1, hours) / 100.0


def score_rs(M: dict, L: int, kind: str) -> np.ndarray:
    """(T,S) skor. rs: L günlük getiri − BTCTRY getirisi (kesitte sıralama = ham momentumla AYNI — kasıtlı kontrol); resid: beta-ayarlı kalıntı
    (getiri − β·BTC getirisi, β = 7 g saatlik log-getiri betası)."""
    C1 = M["C1"]
    R_ = lag_ret(C1, HOURS * L)
    btc = R_[M["btc"]][None, :]
    if kind == "rs":
        return (R_ - btc).T
    r1 = np.log(C1 / B.shift(C1, 1))
    beta, _ = B.rolling_beta_corr(r1, r1[M["btc"]], 168)
    return (R_ - beta * btc).T


def gate_series(M: dict, name: str) -> np.ndarray:
    """(T,) bool kapı. breadth: %24 sa EMA üstü > 0,5; altseason: EW alt sepet 7 g getirisi − BTC 7 g getirisi > 0. NaN → kapalı."""
    if name == "none":
        return np.ones(len(M["ewi"]), dtype=bool)
    if name == "breadth":
        x = M["pct_above"]
        return np.isfinite(x) & (x > 0.5)
    if name == "alt":
        ew = lag_ret(M["ewi"][None, :], HOURS * 7)[0]
        bt = lag_ret(M["C1"][M["btc"]][None, :], HOURS * 7)[0]
        return np.isfinite(ew) & np.isfinite(bt) & (ew > bt)
    raise ValueError(name)


def make_configs() -> list[dict]:
    cfgs = []

    def add(fam, sel, L, k, hold, gate="none", largest=True, kind="rs"):
        warm = HOURS * max(L, 7 if gate == "alt" else 0, 7 if kind == "resid" else 0, 1)
        cfgs.append({"id": f"{fam}|{kind}|L{L}|k{k}|{hold}|{gate}|{'top' if largest else 'bot'}", "fam": fam, "L": L, "k": k, "hold": hold,
                     "gate": gate, "largest": largest, "kind": kind, "warm_h": warm})
    for L, k, h in itertools.product(LOOKBACKS_SHORT, KS, HOLDS):
        add("A_rs_top", "rs", L, k, h)
    for L, k, h in itertools.product(LOOKBACKS_SHORT, KS, ("1g", "3g")):
        add("A2_resid_top", "resid", L, k, h, kind="resid")
    for gate, (L, k, h) in itertools.product(("breadth", "alt"), itertools.product(LOOKBACKS_SHORT, KS, HOLDS)):
        add(f"B_{gate}_gate", "rs", L, k, h, gate=gate)
    for L, k, h in itertools.product(LOOKBACKS_SHORT, KS, HOLDS):
        add("C_rev_bot", "rs", L, k, h, largest=False)
    for L, h, lg in itertools.product(LOOKBACKS_LONG, ("1g", "3g"), (True, False)):
        add("D_long_top" if lg else "D_long_bot", "rs", L, 10, h, largest=lg)
    return cfgs


# ------------------------------------------------------------------------------------------------ 4. simülasyon
def make_null_configs(n_seeds: int = 5) -> list[dict]:
    """Sıfır-beceri kontrolü (rastgele k sembol, aynı evren / tutma / maliyet) — seçime ve DSR denemelerine GİRMEZ."""
    out = []
    for k, h, sd in itertools.product(KS, HOLDS, range(n_seeds)):
        out.append({"id": f"N_rand|k{k}|{h}|s{sd}", "fam": "N_rand", "L": 1, "k": k, "hold": h, "gate": "none", "largest": True, "kind": "rand",
                    "seed": sd, "warm_h": HOURS})
    return out


def rebal_masks(T: int, hold: str, warm_h: int) -> list[np.ndarray]:
    step, nsl = HOLDS[hold]
    out = []
    j = np.arange(T)
    for s in range(nsl):
        off = (24 * s) % step if step > 24 else 0
        # karar saat k'nın KAPANIŞINDA; (k+1) % 24 == 0 → TR gece yarısı kararı
        m = ((j + 1 - off) % step == 0) & (j >= warm_h) & (j + 1 - off >= step)
        out.append(m)
    return out


def run_config(cfg: dict, M: dict, score_cache: dict, gate_cache: dict, cost_leg: float = COST_LEG) -> dict:
    T = M["C1"].shape[1]
    sc_key = (cfg["kind"], cfg["L"], cfg.get("seed"))
    if sc_key not in score_cache:
        if cfg["kind"] == "rand":                       # sıfır-beceri kontrolü: rastgele k sembol
            score_cache[sc_key] = np.random.default_rng(cfg["seed"]).random((T, M["C1"].shape[0]))
        else:
            score_cache[sc_key] = score_rs(M, cfg["L"], cfg["kind"])
    gate = gate_cache[cfg["gate"]]
    Wt = R.topk_weights(score_cache[sc_key], M["V"].T, cfg["k"], largest=cfg["largest"])
    Wt = Wt * gate[:, None]
    r = M["r"].T
    masks = rebal_masks(T, cfg["hold"], cfg["warm_h"])
    net = np.zeros(T)
    gross = np.zeros(T)
    turn = np.zeros(T)
    for m in masks:
        n_, g_, t_ = R.simulate_sleeve(r, Wt, m, cost_leg)
        net += n_ / len(masks)
        gross += g_ / len(masks)
        turn += t_ / len(masks)
    return {"net": net, "gross": gross, "turn": turn}


def block_stats(res: dict, M: dict, cfg: dict, day_a: int, day_b: int) -> dict | None:
    """Blok [day_a, day_b) istatistikleri; yalnız özelliklerin hazır olduğu günler (gün başı saat ≥ warm_h)."""
    d0 = max(day_a, math.ceil(cfg["warm_h"] / HOURS))
    if d0 >= day_b:
        return None
    sl = slice(d0 * HOURS, day_b * HOURS)
    net, gross, turn = res["net"][sl], res["gross"][sl], res["turn"][sl]
    nd = day_b - d0
    daily = R.daily_compound(net)
    return {"days": nd, "net": R.total_return(net), "gross": R.total_return(gross), "dd": R.max_drawdown(net),
            "turn_day": float(turn.sum() / nd), "sharpe_d": R.sharpe(daily), "daily": daily,
            "mean_daily": float(daily.mean()), "d0": d0}


def bench_stats(M: dict, hp: Hourly, cost_leg: float = COST_LEG) -> dict:
    """Blok başına benchmark: BTCTRY al-tut, EW (blok başı geçerli evren) al-tut — her ikisi 1 gidiş-dönüş maliyetle; EW günlük yeniden dengeli (brüt)."""
    out = {}
    PX, V = M["PX"], M["V"]
    btc = M["btc"]
    rt = 2 * cost_leg
    for b, (da, db) in BLOCKS.items():
        ja = da * HOURS                       # blok başı: PX[ja]
        jb = db * HOURS - 1
        v0 = V[:, ja]
        ratio = PX[:, jb] / PX[:, ja]
        good = v0 & np.isfinite(ratio)
        ew_bh = float(np.mean(ratio[good]) - 1.0)
        med = float(np.median(ratio[good]) - 1.0)
        btc_bh = float(ratio[btc] - 1.0)
        mk = np.nan_to_num(M["mkt_r"][ja + 1: jb + 1], nan=0.0)
        out[b] = {"btc": btc_bh, "btc_net": (1 + btc_bh) * (1 - rt) - 1, "ew_bh": ew_bh, "ew_bh_net": (1 + ew_bh) * (1 - rt) - 1, "ew_med": med,
                  "ew_daily_gross": R.total_return(mk), "n_universe": int(good.sum()),
                  "ew_dd": R.max_drawdown(np.nan_to_num(M["mkt_r"][ja + 1: jb + 1], nan=0.0)),
                  "btc_dd": R.max_drawdown(np.nan_to_num(M["r"][btc][ja + 1: jb + 1], nan=0.0))}
    return out


def pick(table: dict, cfgs: list[dict], blocks_train: list[str], fam: str | None) -> dict | None:
    """Eğitim bloklarında günlük Sharpe'ı en yüksek konfig (≥ MIN_TRAIN_DAYS gün); eşitlikte ilk."""
    best, best_sr = None, -1e9
    for c in cfgs:
        if fam and not c["fam"].startswith(fam):
            continue
        ds = [table[c["id"]][b]["daily"] for b in blocks_train if table[c["id"]].get(b)]
        if not ds:
            continue
        d = np.concatenate(ds)
        if len(d) < MIN_TRAIN_DAYS:
            continue
        sr = R.sharpe(d)
        if np.isfinite(sr) and sr > best_sr:
            best, best_sr = c, sr
    return best


def stage_run(args) -> None:
    t0 = time.time()
    od = out_dir(args)
    cost_leg = COST_LEG_MAKER if args.scenario == "maker" else COST_LEG
    hp = Hourly(args.cache, args.delay)
    M = build_market(hp, args.min_quote)
    T = hp.T
    print(f"[run] S={len(hp.syms)} T={T} saat ({T / 24:.1f} gün); pegli çıkarılan: {M['stable']}; ortalama geçerli evren {M['V'].sum(axis=0).mean():.0f}", flush=True)
    assert T >= N_DAYS * HOURS, f"yetersiz veri T={T}"
    cfgs = make_configs()
    n_trials = len(cfgs) * args.trials_mult
    gate_cache = {g: gate_series(M, g) for g in ("none", "breadth", "alt")}
    score_cache: dict = {}
    table: dict = {}
    series: dict = {}
    for i, cfg in enumerate(cfgs):
        res = run_config(cfg, M, score_cache, gate_cache, cost_leg)
        series[cfg["id"]] = res
        table[cfg["id"]] = {b: block_stats(res, M, cfg, da, db) for b, (da, db) in BLOCKS.items()}
        if (i + 1) % 20 == 0:
            print(f"[run] {i + 1}/{len(cfgs)} ({time.time() - t0:.0f} sn)", flush=True)
    bench = bench_stats(M, hp, cost_leg)
    null = {}
    for cfg in make_null_configs():
        res = run_config(cfg, M, score_cache, gate_cache, cost_leg)
        d0 = 1
        sl = slice(d0 * HOURS, N_DAYS * HOURS)
        null.setdefault(f"k{cfg['k']}|{cfg['hold']}", []).append({"net": R.total_return(res["net"][sl]), "gross": R.total_return(res["gross"][sl]),
                                                                  "turn_day": float(res["turn"][sl].sum() / (N_DAYS - d0))})
    null = {k: {m: float(np.mean([x[m] for x in v])) for m in ("net", "gross", "turn_day")} | {"n": len(v)} for k, v in null.items()}

    # tüm 90 gün: konfig başına günlük net seri (kullanılabilir günler)
    full = {}
    for cfg in cfgs:
        res = series[cfg["id"]]
        d0 = max(1, math.ceil(cfg["warm_h"] / HOURS))
        net = res["net"][d0 * HOURS: N_DAYS * HOURS]
        daily = R.daily_compound(net)
        sk, ku = R.moments(daily)
        full[cfg["id"]] = {"days": len(daily), "net": R.total_return(net), "gross": R.total_return(res["gross"][d0 * HOURS: N_DAYS * HOURS]),
                           "dd": R.max_drawdown(net), "sharpe_d": R.sharpe(daily), "skew": sk, "kurt": ku, "mean_d": float(daily.mean()),
                           "turn_day": float(res["turn"][d0 * HOURS: N_DAYS * HOURS].sum() / max(len(daily), 1))}
    srs = np.array([v["sharpe_d"] for v in full.values() if np.isfinite(v["sharpe_d"])])
    sr_var = float(srs.var(ddof=1))
    for cfg in cfgs:
        f = full[cfg["id"]]
        f["dsr_is"] = R.deflated_sharpe(f["sharpe_d"], f["days"], f["skew"], f["kurt"], n_trials, sr_var)
        f["psr"] = R.deflated_sharpe(f["sharpe_d"], f["days"], f["skew"], f["kurt"], 1, 0.0)

    # yürüyen ileri: B2 ← B1 ile seç; B3 ← B1+B2 ile seç. Genel ve aile bazlı.
    wf = {}
    for label, fam in (("GENEL", None), ("A_rs_top", "A_rs_top"), ("A2_resid_top", "A2_resid_top"), ("B_breadth_gate", "B_breadth_gate"),
                       ("B_alt_gate", "B_alt_gate"), ("C_rev_bot", "C_rev_bot")):
        sel = {}
        for tb, train in (("B2", ["B1"]), ("B3", ["B1", "B2"])):
            c = pick(table, cfgs, train, fam)
            if c is None:
                sel[tb] = None
                continue
            st = table[c["id"]][tb]
            sel[tb] = {"cfg": c["id"], "stats": {k: v for k, v in st.items() if k != "daily"} if st else None,
                       "train_sharpe": R.sharpe(np.concatenate([table[c["id"]][b]["daily"] for b in train if table[c["id"]].get(b)]))}
        # OOS birleşik seri (B2 + B3) → DSR
        parts = [table[sel[b]["cfg"]][b]["daily"] for b in ("B2", "B3") if sel[b] and table[sel[b]["cfg"]][b]]
        if parts:
            d = np.concatenate(parts)
            sk, ku = R.moments(d)
            sr = R.sharpe(d)
            sel["oos"] = {"days": len(d), "net": float(np.prod(1 + d) - 1), "sharpe_d": sr, "skew": sk, "kurt": ku,
                          "dsr": R.deflated_sharpe(sr, len(d), sk, ku, n_trials, sr_var), "psr": R.deflated_sharpe(sr, len(d), sk, ku, 1, 0.0),
                          "dd": R.max_drawdown(d), "mean_d": float(d.mean())}
        wf[label] = sel

    # seçim becerisi: sabit konfig için brüt kenar (yatırımlı saatlerde sepet − EW evren), günlük, maliyetle karşılaştır
    edge = {}
    mk = np.nan_to_num(M["mkt_r"], nan=0.0)
    for cfg in cfgs:
        res = series[cfg["id"]]
        d0 = max(1, math.ceil(cfg["warm_h"] / HOURS))
        sl = slice(d0 * HOURS, N_DAYS * HOURS)
        g, n_, tr, m = res["gross"][sl], res["net"][sl], res["turn"][sl], mk[sl]
        inv = np.abs(g) > 0
        nd = (N_DAYS * HOURS - d0 * HOURS) / HOURS
        edge[cfg["id"]] = {"gross_day_pct": float(g.sum() * 100 / nd), "mkt_day_pct": float(m.sum() * 100 / nd),
                           "alpha_day_pct": float((g - m * inv).sum() * 100 / nd), "cost_day_pct": float((g - n_).sum() * 100 / nd),
                           "invested_frac": float(inv.mean()), "turn_day": float(tr.sum() / nd)}
    payload = {"meta": {"n_trials": n_trials, "sr_var": sr_var, "delay": args.delay, "cost_leg_pct": cost_leg * 100, "scenario": args.scenario,
                        "universe_mean": float(M["V"].sum(axis=0).mean()), "min_quote": args.min_quote, "trials_mult": args.trials_mult, "S": len(hp.syms), "stable_excluded": M["stable"],
                        "t0": datetime.fromtimestamp(hp.t0_ms / 1000, timezone.utc).isoformat(), "blocks": BLOCK_LABEL},
               "null": null, "configs": cfgs, "block": {cid: {b: ({k: v for k, v in st.items() if k != "daily"} if st else None) for b, st in bb.items()} for cid, bb in table.items()},
               "full": full, "wf": wf, "bench": bench, "edge": edge}
    (od / f"results{args.tag}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    import csv
    with open(od / f"configs{args.tag}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "days", "net_pct", "gross_pct", "dd_pct", "sharpe_d", "dsr_is", "alpha_day_pct", "cost_day_pct", "turn_day", "B1_net", "B2_net", "B3_net"])
        for cfg in cfgs:
            f, e, bb = full[cfg["id"]], edge[cfg["id"]], payload["block"][cfg["id"]]
            w.writerow([cfg["id"], f["days"], f"{100 * f['net']:.2f}", f"{100 * f['gross']:.2f}", f"{100 * f['dd']:.2f}", f"{f['sharpe_d']:.3f}", f"{f['dsr_is']:.3f}",
                        f"{e['alpha_day_pct']:.3f}", f"{e['cost_day_pct']:.3f}", f"{e['turn_day']:.2f}"] +
                       [f"{100 * bb[b]['net']:.2f}" if bb[b] else "" for b in BLOCKS])
    print(f"[run] bitti ({time.time() - t0:.0f} sn) → {od}", flush=True)


# ------------------------------------------------------------------------------------------------ 5. rapor
def _p(x, d=1, sign=False):
    """Oran → Türkçe yüzde metni (ondalık virgül)."""
    if x is None or not np.isfinite(x):
        return "—"
    t = f"{100 * x:+.{d}f}" if sign else f"{100 * x:.{d}f}"
    return t.replace(".", ",") + "%"


def _n(x, d=2):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{d}f}".replace(".", ",")


def _ann(sr_d):
    return sr_d * math.sqrt(365.0)


def _cell(st):
    if not st:
        return "—"
    return f"{_p(st['net'], 1, True)} · DD {_p(st['dd'], 0)} · devir {_n(st['turn_day'], 1)}"


def _wf_rows(res: dict, key: str) -> list[str]:
    sel = res["wf"][key]
    rows = []
    for b in ("B2", "B3"):
        x = sel.get(b)
        if not x:
            rows.append(f"| {b} | (eğitimde ≥ {MIN_TRAIN_DAYS} gün veri yok) | — | — | — | — | — |")
            continue
        st = x["stats"]
        rows.append(f"| {b} | `{x['cfg'].replace('|', '/')}` | {_n(_ann(x['train_sharpe']), 1)} | {_p(st['net'], 1, True)} | {_p(st['gross'], 1, True)} | "
                    f"{_n(st['turn_day'], 2)} | {_p(st['dd'], 0)} |")
    return rows


def family_summary(res: dict) -> list[str]:
    rows = ["| Aile | Tutma | Konfig | Net>0 | Medyan net (tüm dönem) | En iyi net | Medyan brüt kenar/gün | Medyan maliyet/gün | Medyan devir/gün |",
            "|---|---|---|---|---|---|---|---|---|"]
    groups: dict = {}
    for c in res["configs"]:
        fam = c["fam"] if not c["fam"].startswith("D_") else "D_long"
        groups.setdefault((fam, c["hold"]), []).append(c["id"])
    order = {"4s": 0, "1g": 1, "3g": 2}
    for (fam, hold), ids in sorted(groups.items(), key=lambda kv: (kv[0][0], order[kv[0][1]])):
        f = [res["full"][i] for i in ids]
        e = [res["edge"][i] for i in ids]
        rows.append(f"| {fam} | {hold} | {len(ids)} | {sum(x['net'] > 0 for x in f)} | {_p(float(np.median([x['net'] for x in f])), 1)} | "
                    f"{_p(max(x['net'] for x in f), 1)} | {_n(float(np.median([x['alpha_day_pct'] for x in e])))}% | "
                    f"{_n(float(np.median([x['cost_day_pct'] for x in e])))}% | {_n(float(np.median([x['turn_day'] for x in e])), 2)} |")
    return rows


def _top_rows(res: dict, n: int = 10) -> list[str]:
    rows = ["| Konfig | Gün | Net | Brüt | MaxDD | B1 | B2 | B3 | Günlük Sharpe | DSR(N) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for c in sorted(res["configs"], key=lambda c: -res["full"][c["id"]]["net"])[:n]:
        f = res["full"][c["id"]]
        bb = res["block"][c["id"]]
        rows.append(f"| `{c['id'].replace('|', '/')}` | {f['days']} | {_p(f['net'], 1, True)} | {_p(f['gross'], 1, True)} | {_p(f['dd'], 0)} | "
                    + " | ".join(_p(bb[b]["net"], 1, True) if bb[b] else "—" for b in BLOCKS)
                    + f" | {_n(f['sharpe_d'], 3)} | {_n(f['dsr_is'], 3)} |")
    return rows


def stage_report(args) -> None:
    od = out_dir(args)
    A = json.loads((od / "results.json").read_text(encoding="utf-8"))
    Lq = json.loads((od / "results_likit.json").read_text(encoding="utf-8"))
    mA, mL = A["meta"], Lq["meta"]
    n_tr = mA["n_trials"]
    n_cfg = len(A["configs"])

    any_dsr = max(max(v["dsr_is"] for v in r["full"].values() if np.isfinite(v["dsr_is"])) for r in (A, Lq))
    oosA, oosL = A["wf"]["GENEL"]["oos"], Lq["wf"]["GENEL"]["oos"]
    posA = sum(v["net"] > 0 for v in A["full"].values())
    posL = sum(v["net"] > 0 for v in Lq["full"].values())
    bA, bL = A["bench"], Lq["bench"]
    btc_tot = float(np.prod([1 + bA[b]["btc_net"] for b in BLOCKS]) - 1)
    ew_tot = float(np.prod([1 + bA[b]["ew_bh_net"] for b in BLOCKS]) - 1)
    a_top_1g = float(np.median([A["edge"][c["id"]]["alpha_day_pct"] for c in A["configs"] if c["fam"] == "A_rs_top" and c["hold"] == "1g"]))
    c_rev_3g_l = float(np.median([Lq["edge"][c["id"]]["alpha_day_pct"] for c in Lq["configs"] if c["fam"] == "C_rev_bot" and c["hold"] == "3g"]))
    best_sr = max(v["sharpe_d"] for r in (A, Lq) for v in r["full"].values() if np.isfinite(v["sharpe_d"]))
    sr0 = R.expected_max_sr(n_tr, mA["sr_var"])
    mtrl = R.min_track_record(best_sr, 0.0, 3.0, sr0, 0.95)
    verdict_pos = any_dsr >= 0.95
    best_net, best_days, best_univ = max(((v["net"], v["days"], nm) for nm, r in (("ana", A), ("likit", Lq)) for v in r["full"].values()))

    L: list[str] = []
    L.append("# Altcoin rotasyonu — uzun vadede (4 sa / 1 g / 3 g) net kenar var mı?")
    L.append("")
    L.append(f"*Çevrimdışı araştırma, {datetime.now().date()}; canlı koda ve DB'ye dokunmaz. Kod: `backend/scripts/rotation_study.py`, saf yardımcılar "
             "`backend/app/rescan/rotation.py` (+ `tests/test_rotation.py`). Ham çıktı: `work/rotation/results*.json`, `configs*.csv`.*")
    L.append("")
    L.append("## Karar")
    L.append("")
    a_k10_1g = float(np.median([A["full"][c["id"]]["gross"] for c in A["configs"] if c["fam"] == "A_rs_top" and c["hold"] == "1g" and c["k"] == 10]))
    null_k10_1g = A["null"]["k10|1g"]["gross"]
    btc_oos = float((1 + bA["B2"]["btc_net"]) * (1 + bA["B3"]["btc_net"]) - 1)
    ewl_oos = float((1 + bL["B2"]["ew_bh_net"]) * (1 + bL["B3"]["ew_bh_net"]) - 1)
    L.append(
        "**Rotasyon fikirleri (BTC'ye göre göreli güç, genişlik kapısı, altseason kapısı, 2–4 hafta momentum→dönüş) 4 sa–3 g ufkunda da net kenar üretmiyor; "
        "ufku uzatmak maliyet duvarını alçaltıyor ama seçim sinyalinin kenarını büyütmüyor.** "
        f"{n_cfg} konfigürasyon × 2 evren (24 sa quote ≥5 M ve ≥50 M TRY) × 2 maliyet senaryosu (taker / maker) denendi; aşağıdaki ana sayılar taker (piyasa emri) senaryosudur; tüm dönemde net pozitif olan konfig sayısı ana evrende {posA}/{n_cfg}, "
        f"likit evrende {posL}/{n_cfg}; hiçbiri BTCTRY al-tut'u ({_p(btc_tot, 0, True)}) geçmiyor "
        f"(en iyi tek konfig {_p(best_net, 1, True)}, {best_days} gün, {best_univ} evren, seçim önyargılı; EW al-tut {_p(ew_tot, 0, True)} ile aynı düzeyde — piyasa bu 89 günde zaten yükseldi, pozitif görünenler büyük olasılıkla piyasa betası). "
        f"Yürüyen-ileri seçim (parametreler yalnız önceki bloklarla seçildi) B2+B3'te ana evrende net {_p(oosA['net'], 1, True)} (DSR {_n(oosA['dsr'], 3)}); "
        f"likit evrende {_p(oosL['net'], 1, True)} (DSR {_n(oosL['dsr'], 3)}) — ama aynı iki blokta BTCTRY al-tut {_p(btc_oos, 0, True)}, EW(≥50 M) al-tut {_p(ewl_oos, 0, True)}. "
        f"Hiçbir konfig DSR 0,95'e yaklaşmıyor (en yüksek DSR {_n(any_dsr, 3)}, N={n_tr}); gözlenen en iyi günlük Sharpe {_n(best_sr, 3)} şansla beklenen en iyiden ({_n(sr0, 3)}) düşük. "
        f"Sinyalin yönü ters: en güçlü RS sepeti (A, k=10, 1 g) tüm dönemde brüt {_p(a_k10_1g, 0, True)} yaparken aynı evrende rastgele 10'lu sepet brüt {_p(null_k10_1g, 0, True)} yapıyor "
        f"(medyan EW'ye göre kenar günde {_n(a_top_1g)}%, maliyetten ÖNCE) → 'güçlüyü al' bu evrende negatif seçim; olası açıklama: pompalanmış ince TRY çiftleri geri veriyor (bu bir hipotez, ayrıca sınanmadı). "
        f"Dönüş (dip alma) sepetinin EW'ye göre kenarı likit evrende 3 g tutmada ≈ sıfır (medyan {_n(c_rev_3g_l)}%/gün); net artı veren birkaç konfig beta + şans ve ~%20'lik düşüşle geliyor, "
        "hayatta kalma yanlılığı da bu sepeti özellikle şişiriyor. "
        "**Sınır:** 89 gün yalnız 3 rejim bloğu (düşüş trendi yok) ve 3 g tutma için ≈30 bağımsız dönem demek; küçük bir kenar bu veriyle ne kanıtlanabilir ne çürütülebilir — "
        "ama canlıya taşınacak düzeyde bir kanıt yok. Maliyet tarafı: 4 sa'te rastgele sepet bile günde ≈%3 maliyet öder (devir ~11/gün), 3 g'de ≈%0,15 — yani ufuk uzayınca duvar düşüyor, fakat "
        "net sonuçlar 'BTC/EW al-tut'u geçemeyen piyasa betasına' benziyor."
        + (" (UYARI: en az bir konfig DSR ≥ 0,95 verdi — ayrıntıya bakın.)" if verdict_pos else ""))
    L.append("")
    L.append("## Özet tablo")
    L.append("")
    L.append("Net = ücret %0,1125 + kayma %0,15 / bacak sonrası. Hücre: net getiri · maks. düşüş · günlük devir (alış+satış toplamı, portföy payı). "
             f"Son sütun: B2+B3 OOS günlük Sharpe / DSR (N={n_tr}).")
    L.append("")
    L.append("| Strateji | B1 07-20..08-18 | B2 08-19..09-17 | B3 09-18..10-16 | OOS Sharpe / DSR |")
    L.append("|---|---|---|---|---|")
    L.append("| BTCTRY al-tut (1 gidiş-dönüş maliyetli) | " + " | ".join(f"{_p(bA[b]['btc_net'], 1, True)} · DD {_p(bA[b]['btc_dd'], 0)}" for b in BLOCKS) + " | — |")
    L.append("| EW evren al-tut, ≥5 M | " + " | ".join(f"{_p(bA[b]['ew_bh_net'], 1, True)} · DD {_p(bA[b]['ew_dd'], 0)}" for b in BLOCKS) + " | — |")
    L.append("| EW evren al-tut, ≥50 M | " + " | ".join(f"{_p(bL[b]['ew_bh_net'], 1, True)} · DD {_p(bL[b]['ew_dd'], 0)}" for b in BLOCKS) + " | — |")
    for nm, res in (("≥5 M", A), ("≥50 M", Lq)):
        for fam, lab in (("GENEL", "tüm konfiglerden"), ("A_rs_top", "yalnız A momentum"), ("A2_resid_top", "yalnız A2 kalıntı-RS"),
                         ("B_breadth_gate", "yalnız B breadth kapı"), ("B_alt_gate", "yalnız B altseason kapı"), ("C_rev_bot", "yalnız C dönüş")):
            s2, s3, o = res["wf"][fam]["B2"], res["wf"][fam]["B3"], res["wf"][fam]["oos"]
            L.append(f"| Yürüyen-ileri, {nm}, {lab} | (eğitim) | {_cell(s2 and s2['stats'])} | {_cell(s3 and s3['stats'])} | {_n(o['sharpe_d'], 3)} / {_n(o['dsr'], 3)} |")
    L.append("")
    L.append("B1: seçim için öncesinde veri olmadığından yalnız eğitimde kullanıldı. DSR: gözlem = günlük getiri, deneme sayısı N="
             f"{n_tr} ({n_cfg} konfig × 2 evren × 2 maliyet senaryosu), konfigler arası Sharpe varyansı {_n(mA['sr_var'], 4)} (ana) / {_n(mL['sr_var'], 4)} (likit). 0,5 ≈ şans; ≥0,95 güçlü kanıt.")
    L.append("")
    L.append("## Örneklem uyarısı")
    L.append("")
    L.append(f"* 89 değerlendirme günü (07-20..10-16; B3 yalnız 29 gün) ve yalnız 3 rejim: B1 yatay (EW {_p(bA['B1']['ew_bh'], 1, True)}), B2 güçlü yükseliş "
             f"(BTC {_p(bA['B2']['btc'], 0, True)}), B3 ılımlı yükseliş (BTC {_p(bA['B3']['btc'], 0, True)}). Düşüş trendi hiç yok.")
    L.append("* Bağımsız gözlem: 1 g tutmada ≈ 89 günlük getiri (kesitsel olarak piyasayla ortak), 3 g tutmada ≈ 30 çakışmayan dönem, 4 sa tutmada 500+ dönem ama güçlü otokorelasyonlu. "
             "3 g için 3 kayık kol çakışan getiriler üretir; günlük serideki gözlemler bağımsız değil → DSR iyimser.")
    L.append(f"* N={n_tr} deneme için şans eseri beklenen en iyi günlük Sharpe ≈ {_n(sr0, 3)}; gözlenen en yüksek günlük Sharpe {_n(best_sr, 3)} (yıllık {_n(_ann(best_sr), 1)}). "
             f"Gözlenen Sharpe'ın bu eşikten %95 güvenle ayrılması için gereken süre (MinTRL) ≈ "
             f"{'sonsuz (gözlenen Sharpe eşiğin altında)' if not np.isfinite(mtrl) else f'{mtrl:.0f} gün'}.")
    L.append("")
    L.append("## Yürüyen-ileri ayrıntı (B2 ← B1'de seç, B3 ← B1+B2'de seç; ölçüt günlük Sharpe, ≥15 gün)")
    L.append("")
    for nm, res in (("Ana evren (24 sa quote ≥5 M TRY)", A), ("Likit evren (≥50 M TRY)", Lq)):
        L.append(f"**{nm}** — ortalama {res['meta']['universe_mean']:.0f} geçerli sembol")
        L.append("")
        L.append("| Blok | Seçilen konfig (aile/skor/L/k/tutma/kapı/yön) | Eğitim Sharpe (yıllık) | Net | Brüt | Devir/gün | MaxDD |")
        L.append("|---|---|---|---|---|---|---|")
        L += _wf_rows(res, "GENEL")
        L.append("")
    L.append("## Aile × tutma özeti (tüm konfigler, tüm kullanılabilir dönem)")
    L.append("")
    L.append("Brüt kenar = sepet getirisi − aynı saatlerde EW evren getirisi (günlük, %); maliyet = devir × %0,2625 (günlük, %). Kenar < maliyet ise yapı net negatiftir.")
    L.append("")
    L.append("**Ana evren (≥5 M)**")
    L.append("")
    L += family_summary(A)
    L.append("")
    L.append("**Likit evren (≥50 M)**")
    L.append("")
    L += family_summary(Lq)
    L.append("")
    L.append("## Sıfır-beceri kontrolü (rastgele k sembol, aynı evren/tutma/maliyet; 5 tohum ortalaması, ~89 gün)")
    L.append("")
    L.append("| Sepet | Tutma | Ana: net | Ana: brüt | Ana: devir/gün | Likit: net | Likit: brüt | Likit: devir/gün |")
    L.append("|---|---|---|---|---|---|---|---|")
    for key in sorted(A["null"]):
        a, l_ = A["null"][key], Lq["null"][key]
        k_, h_ = key.split("|")
        L.append(f"| rastgele {k_} | {h_} | {_p(a['net'], 1, True)} | {_p(a['gross'], 1, True)} | {_n(a['turn_day'], 1)} | "
                 f"{_p(l_['net'], 1, True)} | {_p(l_['gross'], 1, True)} | {_n(l_['turn_day'], 1)} |")
    L.append("")
    L.append("Okuma: 4 sa tutmada rastgele sepet bile günde ~10 kat devirle (günde ≈%3 maliyet) %90+ kaybeder → 4 sa ufku maliyet yüzünden baştan ölü. "
             "Üst/alt-k sepetlerin brüt getirisini bu satırlarla kıyaslayın.")
    L.append("")
    L.append("## En iyi 10 konfig (tüm dönem net) — yalnız bilgi; seçim önyargısı nedeniyle güvenilmez")
    L.append("")
    L.append("**Ana evren**")
    L.append("")
    L += _top_rows(A)
    L.append("")
    L.append("**Likit evren**")
    L.append("")
    L += _top_rows(Lq)
    L.append("")
    mk = {}
    for key, fn in (("A", "results_maker.json"), ("L", "results_likit_maker.json")):
        fp = od / fn
        mk[key] = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
    if mk["A"] and mk["L"]:
        MA, ML = mk["A"], mk["L"]
        L.append("## İki maliyet senaryosu: (a) piyasa emri (taker) ve (b) bekleyen limit (maker)")
        L.append("")
        L.append(f"(a) bacak başına ücret %0,1125 + kayma %0,15 = %{_n(mA['cost_leg_pct'], 4)} (gidiş-dönüş %0,525). (b) bacak başına maker %0,0675, kayma YOK = %{_n(MA['meta']['cost_leg_pct'], 4)} (gidiş-dönüş %0,135). "
                 "(b) aynı dolum fiyatını ve aynı zamanlamayı varsayar: limit emrinin HER ZAMAN dolduğu kabul edilir.")
        L.append("")
        L.append("| Senaryo | Evren | Net>0 konfig | En yüksek DSR | Yürüyen-ileri OOS (B2+B3) net / DSR | Rastgele k10 3 g net | Rastgele k10 4 sa net |")
        L.append("|---|---|---|---|---|---|---|")
        for sc, ev, r in (("(a) taker", "≥5 M", A), ("(a) taker", "≥50 M", Lq), ("(b) maker", "≥5 M", MA), ("(b) maker", "≥50 M", ML)):
            o = r["wf"]["GENEL"]["oos"]
            md = max(v["dsr_is"] for v in r["full"].values() if np.isfinite(v["dsr_is"]))
            L.append(f"| {sc} | {ev} | {sum(v['net'] > 0 for v in r['full'].values())}/{len(r['full'])} | {_n(md, 3)} | {_p(o['net'], 1, True)} / {_n(o['dsr'], 3)} | "
                     f"{_p(r['null']['k10|3g']['net'], 1, True)} | {_p(r['null']['k10|4s']['net'], 1, True)} |")
        L.append("")
        bt = {k: (1 + bA[k]["btc"]) for k in BLOCKS}
        oos_b = float(bt["B2"] * bt["B3"] - 1)
        L.append(f"Okuma: maker maliyeti net sonuçları iyileştirir ama kenar yaratmaz — en yüksek DSR hâlâ ≤ {_n(max(max(v['dsr_is'] for v in r['full'].values() if np.isfinite(v['dsr_is'])) for r in (MA, ML)), 3)} (N={MA['meta']['n_trials']}), "
                 f"likit evrende yürüyen-ileri OOS {_p(ML['wf']['GENEL']['oos']['net'], 1, True)} iken aynı iki blokta BTCTRY al-tut (maliyetsiz) {_p(oos_b, 0, True)}. "
                 "Momentum (A) sepetleri maker'da da rastgele sepetin gerisinde. 4 sa tutma maker'da bile günde ~11 kat devirle ≈%0,75/gün öder ve rastgele sepet −%44..−%61 kaybeder.")
        L.append("")
        L.append("**Maker dolum riski (modellenmedi, sonucu aşağı çeker):** (1) Bekleyen limit, fiyat emre dokunmadan kaçarsa dolmaz; rotasyon yeniden dengesinde alınacak (yükselen) isimlerde dolmama olasılığı yüksek, satılacak (düşen) isimlerde dolum olasılığı yüksek → "
                 "seçilim: dolan emirler ortalamada kaybettiren taraf (adverse selection). (2) Dolmayan emir ya zincirleme gecikme (sinyal bayatlar) ya da piyasa emrine dönüş (taker maliyeti) demek. "
                 "(3) Yarı-dolum sepeti bozar. Dolayısıyla (b) sonuçları kenar üst sınırıdır; (b) bile pozitif DSR üretmediği için gerçek dolumla durum daha kötüdür.")
        L.append("")
    L.append("## Yöntem")
    L.append("")
    L.append(f"* **Veri:** `historical_candles` 15m (salt-okunur), {mA['S']} sembol; TR günü 07-19 ısınma, 07-20..10-16 değerlendirme; saatlik barlara toplandı. "
             "Karar saat barının kapanışında (yalnız geçmiş); dolum karardan sonra 1 adet 15 dk barın AÇILIŞI (≈15 dk gecikme), alışta ve satışta.")
    L.append(f"* **Maliyet:** bacak başına ücret %0,1125 + kayma %0,15 = %{_n(mA['cost_leg_pct'], 4)} (exit_sim.py sözleşmesi; gidiş-dönüş %0,525). Maliyet **devir temelli**: "
             "yeniden dengede yalnız |Δw| × bacak maliyeti ödenir (sepet devam ederse maliyet yok). Spot, long-only, kaldıraçsız; kapı kapalıyken nakit.")
    stable = ", ".join(mA["stable_excluded"])
    L.append(f"* **Evren:** karar anında son 24 sa quote hacmi ≥ {int(mA['min_quote']) // 1_000_000} M TRY (ana) veya ≥ {int(mL['min_quote']) // 1_000_000} M TRY (likit) olan semboller (nedensel); "
             f"pegli/durağan çiftler çıkarıldı ({stable}).")
    L.append("* **Skor:** `rs` = L günlük getiri − BTCTRY L günlük getirisi (L ∈ {1,3,7} g; kesitsel sıralaması ham momentumla AYNIDIR, çünkü BTC çıkarımı sabittir) · "
             "`resid` = getiri − β·BTC getirisi (β: 7 g saatlik log-getiri betası; gerçekten farklı sıralama) · uzun geri bakış L ∈ {14,21,28} g (momentum ve dönüş).")
    L.append("* **Kapılar:** `breadth` = 24 sa EMA üstündeki sembol payı > 0,5 (breadth.pct_above) · `alt` = EW alt-sepet 7 g getirisi > BTCTRY 7 g getirisi "
             "(altseason benzeri; breadth.ew_index). Kapı kapalıyken nakit.")
    L.append("* **Tutma / yeniden denge:** 4 sa (her 4 sa), 1 g (TR gece yarısı), 3 g (3 kayık kol, 24 sa arayla; her kol 3 günde bir yeniden dengelenir, sermayenin 1/3'ü). k ∈ {5,10}, eşit ağırlık.")
    L.append("* **EW evren getirisi (kenar hesabında):** karar anındaki geçerli evrenin saatlik eşit-ağırlıklı ortalaması; üyelik hacim eşiğine bağlı olduğundan dinamiktir (hacim patlayan çiftler girer). Bu yüzden al-tut EW (blok başı evren, sabit) ayrıca verilir; ikisi birbirinden sapabilir (özellikle ≥50 M).")
    L.append(f"* **Konfigürasyonlar ({n_cfg}):** A momentum top-k · A2 beta-ayarlı kalıntı · B breadth/alt kapılı · C kısa dönüş bottom-k · D 14–28 g momentum/dönüş.")
    L.append("* **Yürüyen-ileri:** B2 için B1'de, B3 için B1+B2'de günlük Sharpe'ı en yüksek konfig seçilir (≥15 gün veri şartı; 14–28 g geri bakışlar B1'de veri olmadığı için "
             "yalnız B3 seçiminde yarışabilir). Seçilen konfig sonraki blokta DEĞERLENDİRİLİR; B1 yalnız eğitimdir.")
    L.append(f"* **DSR:** Bailey & López de Prado (2014); günlük net getiri serisi, çarpıklık/basıklık dâhil; deneme sayısı N={n_tr}, Sharpe varyansı konfigler arası kesitten. "
             "Testli saf kod: `rotation.deflated_sharpe`, `rotation.min_track_record`.")
    L.append("* **Doğrulama:** `simulate_sleeve` / `topk_weights` birim testli; ayrıca bir konfigin (A, L3, k10, 1 g) brüt getirisi bağımsız bir döngüyle yeniden hesaplandı ve tam eşleşti (−%59,73).")
    L.append("")
    L.append("## Sınırlamalar (yorumu etkiler)")
    L.append("")
    L.append("1. **Hayatta kalma yanlılığı:** adaylar yalnız bugün işlem gören semboller; delist olan/çöken çiftler yok. Bu yanlılık **bottom-k (dönüş) sepetini ve genel olarak long-only sonuçlarını iyimser** yapar "
             "(bugün hâlâ var olan düşenler toparlananlardır). Negatif sonuç gerçekte daha da negatif olur; pozitif görünen sonuçlar daha az güvenilirdir.")
    L.append("2. **Kısa örneklem / rejim:** 89 gün, 3 blok, düşüş trendi yok; piyasa yukarı gitti (long-only için kolay dönem). 2–4 hafta momentum→dönüş yapısı ancak 2–3 bağımsız pencerede ölçülebildi (28 g geri bakışta 62 kullanılabilir gün).")
    L.append("3. **Çakışma:** 3 g tutma kolları ve günlük bileşik getiriler otokorelasyonlu; DSR'deki 'gözlem sayısı' bağımsız gözlemden fazla → DSR iyimser.")
    L.append("4. **İnce defter:** TRY çiftlerinde (özellikle ≥5 M eşiğinde) gerçek spread/derinlik %0,15 kaymadan kötü olabilir; momentum sepeti pompalanmış küçük çiftleri seçer. "
             "Simülasyon last-trade `open` fiyatından 15 dk gecikmeli dolum varsayar; gerçek dolum sonuçları aşağı çeker. 'Kenar yok' sonucu bu yüzden iyimser bir üst sınırdır.")
    L.append("5. **RS ≡ momentum:** BTC'ye göre göreli güç kesitte ham momentumla aynı sıralamayı verir; gerçek ayrım yalnız beta-ayarlı `resid` ve kapılarla gelir. "
             "'BTC dominansı düşerken alt seçimi' fikri `alt` kapısıyla yaklaşıldı (gerçek BTC.D yok).")
    L.append("6. **Fiyat gürültüsü:** saatlik getirilerin medyanı 0 (ince defterler); fiyat last-trade'tir, bid-ask sıçraması kısa ufuk getirilerini şişirir; 1 g–3 g tutmada azalır ama sıfır değildir.")
    L.append("7. **Blok uzunlukları:** veri 07-19 00:00 TR'de başlıyor; B1'de L=7 g için ilk 7 gün özellik yok (kullanılabilir gün sayıları tablolarda 'Gün' sütununda). B3 = 29 gün.")
    L.append("")
    L.append("## Yeniden üretim")
    L.append("")
    L.append("```")
    L.append("cd backend")
    L.append("DATABASE_URL=postgresql://... python scripts/rotation_study.py --stages data      # DB -> work/rotation/cache/candles15m.npz (salt-okunur)")
    L.append("python scripts/rotation_study.py --stages run --trials-mult 4                     # ana evren, taker  -> results.json, configs.csv")
    L.append("python scripts/rotation_study.py --stages run --trials-mult 4 --min-quote 50000000 --tag _likit   # likit evren -> results_likit.json")
    L.append("python scripts/rotation_study.py --stages run --trials-mult 4 --scenario maker --tag _maker   # (ve --min-quote 50000000 --tag _likit_maker)")
    L.append("python scripts/rotation_study.py --stages report                                  # -> report.md")
    L.append("```")
    (od / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[report] -> {od / 'report.md'}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="data,run,report")
    ap.add_argument("--db-url", default="")
    ap.add_argument("--cache", default=str(_BACKEND_DIR / "work" / "rotation" / "cache" / "candles15m.npz"))
    ap.add_argument("--out-dir", default=str(_BACKEND_DIR / "work" / "rotation"))
    ap.add_argument("--min-quote", type=float, default=MIN_QUOTE_24H, help="geçerli evren: 24 sa quote hacmi eşiği (TRY)")
    ap.add_argument("--tag", default="", help="çıktı dosya soneki (ör. _likit)")
    ap.add_argument("--trials-mult", type=int, default=1, help="DSR deneme sayısı çarpanı (aynı 96 konfig birden çok evren/senaryoda denendiyse)")
    ap.add_argument("--scenario", choices=("taker", "maker"), default="taker", help="taker: piyasa emri ücret+kayma; maker: bekleyen limit, maker ücreti, kayma yok")
    ap.add_argument("--delay", type=int, default=1, help="karar → dolum gecikmesi (15 dk bar sayısı)")
    args = ap.parse_args()
    for st in [s.strip() for s in args.stages.split(",") if s.strip()]:
        {"data": stage_data, "run": stage_run, "report": stage_report}[st](args)


if __name__ == "__main__":
    main()
