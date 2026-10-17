"""Bildirim HEDEFİ denetimi (2026-10-18, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye YAZMAZ).

Soru: radar bildirimlerinde gösterilen hedef (target_pct) nasıl üretiliyor, ne kadar kalibre ve nasıl iyileşir?

Veri (yalnız OKUMA):
  * velocity_candidates  : vel-* kimlikli, passes ve rank<=10 (canlıya benzer alt küme), (sembol, ufuk) başına 60 dk soğuma.
  * monitoring_notifications : mode dolu satırlar (test kirliliği: mode NULL olan BTC/ETH satırları dışarıda).
  * unified_candidate_outcomes : birleşik tarama journal'ı (yalnız kalibrasyon tablosu).
  * historical_candles 1m/5m : gerçekçi doluş yeniden simülasyonu (app.rescan.exit_sim).

Simülasyon kuralları (policy7d ile uyumlu): giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı x (1 + %0,15 kayma);
SL %3; zaman stopu = ufuk ya da 60 dk; aynı barda SL+TP -> SL; TP = BİLDİRİMDE GÖSTERİLEN fiyat (sinyal fiyatına göre hedef, dolan
girişe çevrilmiş: (1+T)/(1+kayma)-1), BEKLEYEN LİMİT -> maker %0,0675, çıkış kaymasız. Böylece TP çıkışı toplam maliyeti
%0,15 + %0,1125 + %0,0675 = %0,33; SL/zaman çıkışı %0,525'tir.

Kullanım (backend/): DATABASE_URL=... python scripts/target_audit.py [--refresh] [--out work/target_audit/report.md]
Önbellek: $TARGET_AUDIT_CACHE (varsayılan: scratchpad/target_audit). Python 3.11 uyumlu f-string.
"""
from __future__ import annotations

import argparse
import math
import os
import pickle
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.rescan import dyn_target as D  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402

TZ = timezone(timedelta(hours=3))
DAY_S = 86_400
W = 60
SLIP = 0.15
DELAY_S = 60.0
SL = 3.0
T0 = datetime(2026, 9, 17, 0, 0, tzinfo=TZ).timestamp()
B_EDGES = (datetime(2026, 10, 2, tzinfo=TZ).timestamp(), datetime(2026, 10, 10, tzinfo=TZ).timestamp())
BLOCK_NAMES = ("B1 09-17..10-01", "B2 10-02..10-09", "B3 10-10..10-17")
KS = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5)
FIXED = (0.75, 1.0, 1.5, 2.0, 2.5, 3.0)
ATR_K = (0.75, 1.0, 1.5, 2.0, 3.0)
QS = (0.5, 0.6, 0.7)
LEGACY_MODE = "global_lead_lag"
DEFAULT_CACHE = (r"C:\Users\Erkan\AppData\Local\Temp\claude\D--PROJELLER-sclpragnt\bb25c086-ec89-43e9-a810-f345b61672ad"
                 r"\scratchpad\target_audit")


def panel_score(raw: float) -> float:
    """velocity._panel_score ile aynı (log modu, REF=25000)."""
    if not raw or raw <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * math.log1p(raw) / math.log1p(25000.0))), 1)


# ------------------------------------------------------------------------------------------------ olay yükleme
def load_velocity(conn, t_hi: float, cooldown_s: float = 3600.0) -> list[dict]:
    cur = conn.execute(
        "SELECT candidate_id, created_at, symbol, price, target_pct, ml_target_pct, ml_hit_probability, velocity_score, "
        "atr_pct, touched_target, mfe_pct, exit_pct, net_pct, status FROM velocity_candidates "
        "WHERE candidate_id LIKE 'vel-%%' AND passes AND rank <= 10 AND target_pct IS NOT NULL "
        "AND created_at >= %s AND created_at < %s ORDER BY created_at", (T0, t_hi))
    last: dict[tuple, float] = {}
    out = []
    for (cid, ts, sym, price, tgt, mlt, mlp, vs, atr, touched, mfe, ex, net, st) in cur.fetchall():
        m = re.match(r"vel-(\d+)dk", cid or "")
        hz = int(m.group(1)) if m else 5
        key = (sym, hz)
        if key in last and ts - last[key] < cooldown_s:
            continue
        last[key] = ts
        out.append({"src": "V", "id": cid, "sym": sym, "t": float(ts), "hz": hz, "tgt": float(tgt),
                    "ml_tgt": float(mlt) if mlt is not None else np.nan, "ml_prob": float(mlp) if mlp is not None else np.nan,
                    "score": panel_score(float(vs or 0)), "atr_db": float(atr) if atr is not None else np.nan,
                    "db_touched": (1 if touched else 0) if st == "evaluated" else -1,
                    "db_mfe": float(mfe) if mfe is not None else np.nan,
                    "db_net": float(net) if net is not None else np.nan, "mode": "velocity", "app": -1, "app_mfe": np.nan})
    return out


def load_notifications(conn, t_hi: float) -> list[dict]:
    cur = conn.execute(
        "SELECT id, symbol, target_pct, horizon_minutes, mode, score, detected_at, outcome_status, mfe_pct, ml_target_pct, "
        "ml_hit_probability, sent_via_push FROM monitoring_notifications WHERE mode IS NOT NULL AND horizon_minutes IS NOT NULL "
        "AND target_pct IS NOT NULL AND detected_at >= %s AND detected_at < %s ORDER BY detected_at", (T0, t_hi))
    out = []
    for (i, sym, tgt, hz, mode, score, ts, st, mfe, mlt, mlp, push) in cur.fetchall():
        if st in (None, "BEKLIYOR"):
            app = -1
        else:
            app = 1 if st == "HEDEFE_ULTI" else 0
        out.append({"src": "N", "id": "n%d" % i, "sym": sym, "t": float(ts), "hz": int(hz), "tgt": float(tgt),
                    "ml_tgt": float(mlt) if mlt is not None else np.nan, "ml_prob": float(mlp) if mlp is not None else np.nan,
                    "score": float(score or 0), "atr_db": np.nan, "db_touched": -1, "db_mfe": np.nan, "db_net": np.nan,
                    "mode": mode, "app": app, "app_mfe": float(mfe) if mfe is not None else np.nan, "status": st or ""})
    return out


def load_unified(conn, t_hi: float) -> dict:
    cur = conn.execute(
        "SELECT horizon_minutes, scan_score, target_pct, ceiling_pct, detected_at, mfe_pct, mae_pct, hit, blocked_by "
        "FROM unified_candidate_outcomes WHERE outcome_filled_at IS NOT NULL AND mfe_pct IS NOT NULL AND detected_at < %s", (t_hi,))
    rows = cur.fetchall()
    cols = ("hz", "score", "tgt", "ceil", "t", "mfe", "mae", "hit")
    arr = {c: np.array([np.nan if r[i] is None else float(r[i]) for r in rows]) for i, c in enumerate(cols)}
    arr["blocked"] = np.array([bool(r[8]) for r in rows])
    return arr


def load_learned_state(conn) -> np.ndarray:
    rows = conn.execute("SELECT target_pct, total_count FROM symbol_target_state").fetchall()
    return np.array([[float(r[0] or 0), float(r[1] or 0)] for r in rows])


# ------------------------------------------------------------------------------------------------ mum / pencere
def load_candles(conn, sym: str, t_lo_ms: int, t_hi_ms: int):
    one = conn.execute(
        "SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe='1m' "
        "AND open_time >= %s AND open_time <= %s ORDER BY open_time", (sym, t_lo_ms, t_hi_ms)).fetchall()
    five = conn.execute(
        "SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe='5m' "
        "AND open_time >= %s AND open_time <= %s ORDER BY open_time", (sym, t_lo_ms - 15 * D.DAY_MS, t_hi_ms)).fetchall()
    if not one or not five:
        return None
    return np.array(one, dtype=float), np.array(five, dtype=float)


def process_symbol(a1: np.ndarray, a5: np.ndarray, t_ms: np.ndarray, hz: np.ndarray) -> dict:
    open1 = a1[:, 0].astype(np.int64)
    open5 = a5[:, 0].astype(np.int64)
    o1, h1, l1, c1 = a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4]
    h5, l5, c5 = a5[:, 2], a5[:, 3], a5[:, 4]
    n = len(t_ms)
    idx0, ok0 = X.entry_index(open1, t_ms, 0.0, 120_000)
    idx6, ok6 = X.entry_index(open1, t_ms, DELAY_S, 120_000)
    O0, H0, L0, C0, ref0, cov0 = X.gather_windows(open1, o1, h1, l1, c1, idx0, W)
    Os, Hs, Ls, Cs, refs, covs = X.gather_windows(open1, o1, h1, l1, c1, idx6, W)
    cm = np.maximum.accumulate(H0, axis=1)
    ar = np.arange(n)
    hzc = np.clip(hz, 1, W)
    mfe_h = (cm[ar, hzc - 1].astype(float) - 1.0) * 100.0
    mfe60 = (cm[:, W - 1].astype(float) - 1.0) * 100.0
    mae_h = (np.minimum.accumulate(L0, axis=1)[ar, hzc - 1].astype(float) - 1.0) * 100.0
    drift_h = (C0[ar, hzc - 1].astype(float) - 1.0) * 100.0
    atr = X.atr_pct_at(open5, h5, l5, c5, t_ms, 14)
    sc = D.SymbolCandles(open1=open1, h1=h1, open5=open5, h5=h5, l5=l5, c5=c5)
    out = {"valid": ok0 & ok6 & cov0 & covs & np.isfinite(atr), "mfe_h": mfe_h, "mfe60": mfe60, "mae_h": mae_h, "drift_h": drift_h,
           "atr": atr, "Os": Os, "Hs": Hs, "Ls": Ls, "Cs": Cs}
    for q in QS:
        out["emp60_%d" % int(q * 100)] = D.empirical_upside_pct(sc, t_ms, 60, 14, q)
        out["emph_%d" % int(q * 100)] = D.empirical_upside_pct(sc, t_ms, hz, 14, q)
    return out


def build_base(conn, events: list[dict], log) -> dict:
    n = len(events)
    keys = ["valid", "mfe_h", "mfe60", "mae_h", "drift_h", "atr"] + ["emp60_%d" % int(q * 100) for q in QS] + \
           ["emph_%d" % int(q * 100) for q in QS]
    res = {k: (np.zeros(n, dtype=bool) if k == "valid" else np.full(n, np.nan)) for k in keys}
    for k in ("Os", "Hs", "Ls", "Cs"):
        res[k] = np.ones((n, W), dtype=np.float32)
    by_sym: dict[str, list[int]] = {}
    for i, e in enumerate(events):
        by_sym.setdefault(e["sym"], []).append(i)
    done = 0
    for sym, idxs in by_sym.items():
        ts = np.array([events[i]["t"] for i in idxs])
        c = load_candles(conn, sym, int(ts.min() * 1000) - D.DAY_MS, int(ts.max() * 1000) + 3 * 3600 * 1000)
        done += 1
        if c is None:
            continue
        t_ms = (ts * 1000).astype(np.int64)
        hz = np.array([events[i]["hz"] for i in idxs], dtype=int)
        r = process_symbol(c[0], c[1], t_ms, hz)
        ii = np.array(idxs)
        for k in keys:
            res[k][ii] = r[k]
        for k in ("Os", "Hs", "Ls", "Cs"):
            res[k][ii] = r[k]
        if done % 50 == 0:
            log("  mum işlendi: %d/%d sembol" % (done, len(by_sym)))
    return res


# ------------------------------------------------------------------------------------------------ tablo
class Tab:
    """Olay tablosu: sütunlar numpy dizisi."""

    def __init__(self, events: list[dict], base: dict):
        self.n = len(events)
        for k in ("src", "id", "sym", "mode"):
            setattr(self, k, np.array([e[k] for e in events]))
        for k in ("t", "hz", "tgt", "ml_tgt", "ml_prob", "score", "atr_db", "db_touched", "db_mfe", "db_net", "app", "app_mfe"):
            setattr(self, k, np.array([e[k] for e in events], dtype=float))
        self.hz = self.hz.astype(int)
        for k, v in base.items():
            setattr(self, k, v)
        self.day = ((self.t + 3 * 3600) // DAY_S).astype(int)
        self.block = np.where(self.t < B_EDGES[0], 0, np.where(self.t < B_EDGES[1], 1, 2))


# ------------------------------------------------------------------------------------------------ simülasyon
def tp_fill(tnotif: np.ndarray) -> np.ndarray:
    """Bildirimdeki (sinyal fiyatına göre) hedef -> dolan girişe göre TP% (giriş kayması düşülür)."""
    return ((1.0 + np.asarray(tnotif, dtype=float) / 100.0) / (1.0 + SLIP / 100.0) - 1.0) * 100.0


def simulate_tp(T: Tab, tnotif: np.ndarray, time_min: np.ndarray | int) -> dict:
    """Her olay için TP=tnotif, SL=%3, zaman stopu=time_min (dizi olabilir: ufuk). NaN hedef -> NaN sonuç."""
    n = T.n
    net = np.full(n, np.nan)
    hit = np.full(n, np.nan)
    reason = np.full(n, -1, dtype=np.int8)
    tn = np.asarray(tnotif, dtype=float)
    ok = T.valid & np.isfinite(tn) & (tn > 0)
    tm = np.broadcast_to(np.asarray(time_min, dtype=int), (n,))
    for m in np.unique(tm[ok]):
        sel = ok & (tm == m)
        spec = X.ExitSpec("x", "fixed", sl=SL, time_min=int(min(m, W)), tp_cand=True, tp_fallback=99.0)
        r = X.simulate(T.Os[sel], T.Hs[sel], T.Ls[sel], T.Cs[sel], spec, slip_pct=SLIP, tp_cand_pct=tp_fill(tn[sel]))
        net[sel] = r["net"]
        hit[sel] = (r["reason"] == X.R_TP).astype(float)
        reason[sel] = r["reason"]
    return {"net": net, "hit": hit, "reason": reason}


def calib_pooled(T: Tab, q: float, days: int = 14, min_rows: int = 30) -> np.ndarray:
    """target_calibration emülasyonu: ufuk başına, ÖNCEKİ `days` günün (sonucu t'den önce belli) V-olaylarının MFE yüzdeliği.
    Üretimdeki gibi [0,6; 4,5] kelepçe ve 1 ondalık; yeterli örnek yoksa NaN (çağıran yedeğe düşer)."""
    out = np.full(T.n, np.nan)
    isv = (T.src == "V") & T.valid & np.isfinite(T.mfe_h)
    for h in np.unique(T.hz):
        pool = np.where(isv & (T.hz == h))[0]
        if len(pool) == 0:
            continue
        order = pool[np.argsort(T.t[pool])]
        tt = T.t[order]
        done_t = tt + h * 60.0
        mf = T.mfe_h[order]
        targets = np.where((T.hz == h) & T.valid)[0]
        for i in targets:
            lo = np.searchsorted(tt, T.t[i] - days * DAY_S, side="left")
            hi = np.searchsorted(done_t, T.t[i], side="right")  # sonucu belli olanlar (done_t sıralı: tt sıralı + sabit h)
            if hi - lo >= min_rows:
                v = float(np.quantile(mf[lo:hi], q))
                out[i] = round(min(4.5, max(0.6, v)), 1)
    return out


def run_all(T: Tab, log) -> dict:
    """Tüm stratejiler x zaman stopu. Dönüş: name -> {net, hit, reason}; ayrıca meta."""
    R: dict[str, dict] = {}
    tms = {"H": np.minimum(T.hz, W), "60": 60}
    calib = {int(q * 100): calib_pooled(T, q) for q in (0.3, 0.5, 0.7)}
    T.calib = calib
    for tm, tmv in tms.items():
        for k in KS:
            R["cur_k%g_%s" % (k, tm)] = simulate_tp(T, k * T.tgt, tmv)
        for f in FIXED:
            R["fix%g_%s" % (f, tm)] = simulate_tp(T, np.full(T.n, f), tmv)
        for k in ATR_K:
            R["atr%g_%s" % (k, tm)] = simulate_tp(T, D.atr_target_pct(T.atr, T.hz, k), tmv)
        for q in QS:
            R["mfe60q%d_%s" % (int(q * 100), tm)] = simulate_tp(T, T.__dict__["emp60_%d" % int(q * 100)], tmv)
            R["mfehq%d_%s" % (int(q * 100), tm)] = simulate_tp(T, T.__dict__["emph_%d" % int(q * 100)], tmv)
        for qq, arr in calib.items():
            R["calibp%d_%s" % (qq, tm)] = simulate_tp(T, np.where(np.isfinite(arr), arr, T.tgt), tmv)
        R["ml_%s" % tm] = simulate_tp(T, np.where(np.isfinite(T.ml_tgt) & (T.ml_tgt > 0), np.maximum(T.ml_tgt, 0.4), np.nan), tmv)
        log("  simülasyon tamam: zaman stopu %s" % tm)
    return R


def ensure_data(args, log) -> tuple[Tab, dict, dict, np.ndarray]:
    cache = Path(os.environ.get("TARGET_AUDIT_CACHE", DEFAULT_CACHE))
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / "base_v1.pkl"
    if f.exists() and not args.refresh:
        with open(f, "rb") as fh:
            events, base, uni, learned, meta = pickle.load(fh)
        log("önbellekten yüklendi: %d olay (%s)" % (len(events), f))
    else:
        import psycopg
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            sys.exit("DATABASE_URL gerekli (yalnız okunur)")
        conn = psycopg.connect(url, connect_timeout=10)
        conn.read_only = True
        last_c = conn.execute("SELECT max(open_time) FROM historical_candles WHERE timeframe='1m'").fetchone()[0] / 1000.0
        t_hi = last_c - (W + 10) * 60
        log("son 1m mum: %s; olay kesiti: %s" % (datetime.fromtimestamp(last_c, TZ), datetime.fromtimestamp(t_hi, TZ)))
        ev = load_velocity(conn, t_hi) + load_notifications(conn, t_hi)
        ev = [e for e in ev if e["sym"]]
        log("olaylar: V=%d N=%d" % (sum(e["src"] == "V" for e in ev), sum(e["src"] == "N" for e in ev)))
        base = build_base(conn, ev, log)
        uni = load_unified(conn, t_hi)
        learned = load_learned_state(conn)
        meta = {"t_hi": t_hi, "last_candle": last_c}
        events = ev
        with open(f, "wb") as fh:
            pickle.dump((events, base, uni, learned, meta), fh, protocol=4)
    T = Tab(events, base)
    T.meta = meta
    return T, uni, learned, meta


# ------------------------------------------------------------------------------------------------ istatistik / biçim
def ms(x: np.ndarray, day: np.ndarray) -> tuple[float, float, int]:
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    n = int(m.sum())
    if n == 0:
        return float("nan"), float("nan"), 0
    se = X.cluster_se(x[m], day[m]) if n > 1 else float("nan")
    return float(x[m].mean()), se, n


def fnet(mean: float, se: float, n: int, d: int = 2) -> str:
    if n == 0 or not np.isfinite(mean):
        return "–"
    if not np.isfinite(se):
        return ("%+." + str(d) + "f (n=%d)") % (mean, n)
    return ("%+." + str(d) + "f ±%." + str(d) + "f") % (mean, 1.96 * se)


def frate(ind: np.ndarray, day: np.ndarray) -> str:
    """Oran (%) ± %95 gün-kümeli yarı genişlik."""
    m, se, n = ms(np.asarray(ind, dtype=float), day)
    if n == 0:
        return "–"
    if not np.isfinite(se):
        return "%.1f%%" % (100 * m)
    return "%.1f%% ±%.1f" % (100 * m, 196 * se)


def paired(a: np.ndarray, b: np.ndarray, day: np.ndarray) -> tuple[float, float, int]:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return ms(d, day)


def fdiff(a, b, day) -> str:
    m, se, n = paired(a, b, day)
    return fnet(m, se, n)


def md(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def auc(score: np.ndarray, label: np.ndarray) -> float:
    s = np.asarray(score, dtype=float)
    y = np.asarray(label, dtype=bool)
    m = np.isfinite(s)
    s, y = s[m], y[m]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    from scipy.stats import rankdata
    r = rankdata(s)
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return float("nan")
    from scipy.stats import spearmanr
    return float(spearmanr(a[m], b[m])[0])


def quant(x: np.ndarray, qs=(25, 50, 75)) -> list[float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, q)) for q in qs] if len(x) else [float("nan")] * len(qs)


def q3(x: np.ndarray) -> str:
    return "%.2f / %.2f / %.2f" % tuple(quant(x))


TBUCKETS = ((0, 2.0, "<2,0"), (2.0, 2.45, "2,0–2,4"), (2.45, 2.95, "2,5–2,9"), (2.95, 3.95, "3,0–3,9"), (3.95, 99, "≥4,0"))
SBUCKETS = ((0, 68.2, "<68,2"), (68.2, 74.0, "68,2–74"), (74.0, 80, "74–80"), (80, 90, "80–90"), (90, 101, "≥90"))


def bsel(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (x >= lo) & (x < hi)


# ------------------------------------------------------------------------------------------------ (a) kalibrasyon
def sec_calibration(T: Tab, uni: dict, learned: np.ndarray) -> tuple[str, dict]:
    out: list[str] = []
    info: dict = {}
    V = (T.src == "V") & T.valid
    hit_h = (T.mfe_h >= T.tgt - 1e-9).astype(float)
    hit_60 = (T.mfe60 >= T.tgt - 1e-9).astype(float)

    rows = []
    for name, m in [("tümü", V)] + [(BLOCK_NAMES[b], V & (T.block == b)) for b in range(3)]:
        rows.append([name, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), "%.2f" % np.median(T.tgt[m]),
                     frate(hit_h[m], T.day[m]), frate(hit_60[m], T.day[m]), q3(T.mfe_h[m]),
                     "%.2f" % (np.median(T.mfe_h[m]) / np.median(T.tgt[m]))])
    info["overall_hit"] = float(np.mean(hit_h[V]))
    info["overall_hit60"] = float(np.mean(hit_60[V]))
    info["overall_med_mfe"] = float(np.median(T.mfe_h[V]))
    info["overall_med_tgt"] = float(np.median(T.tgt[V]))
    info["overall_mfe_q"] = quant(T.mfe_h[V])
    info["n_v"] = int(V.sum())
    out.append("### a1. Hız Avcısı adayları (passes, rank≤10, (sembol,ufuk) başına 60 dk soğuma): genel kalibrasyon\n")
    out.append("isabet(ufuk) = ufuk içinde en yüksek >= gösterilen hedef (referans: sinyal sonrası ilk tam 1 dk barın açılışı); "
               "isabet(60) = 60 dk içinde. ± = %95 (gün-kümeli SE). MFE yüzdelikleri ufuk içindir.\n")
    out.append(md(["küme", "n", "ort. hedef", "medyan hedef", "isabet(ufuk)", "isabet(60 dk)", "MFE(ufuk) p25/p50/p75", "medyan MFE / medyan hedef"], rows))

    rows = []
    for h in (5, 15, 30, 60):
        m = V & (T.hz == h)
        if m.sum() == 0:
            continue
        rows.append([h, int(m.sum()), "%.2f" % np.median(T.tgt[m]), frate(hit_h[m], T.day[m]),
                     " / ".join(frate(hit_h[m & (T.block == b)], T.day[m & (T.block == b)]) for b in range(3)),
                     q3(T.mfe_h[m]), "%.2f" % (np.median(T.mfe_h[m]) / np.median(T.tgt[m]))])
    out.append("\n### a2. Ufuk bazında\n")
    out.append(md(["ufuk dk", "n", "medyan hedef", "isabet(ufuk)", "isabet B1 / B2 / B3", "MFE p25/p50/p75", "medyan MFE / medyan hedef"], rows))

    rows = []
    for lo, hi, nm in TBUCKETS:
        for h in (5, 15):
            m = V & (T.hz == h) & bsel(T.tgt, lo, hi)
            if m.sum() < 20:
                continue
            rows.append([nm, h, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), frate(hit_h[m], T.day[m]),
                         " / ".join(("%.0f%% (n=%d)" % (100 * hit_h[m & (T.block == b)].mean(), (m & (T.block == b)).sum()))
                                    if (m & (T.block == b)).sum() else "–" for b in range(3)),
                         q3(T.mfe_h[m])])
    out.append("\n### a3. Hedef kovası x ufuk (n≥20)\n")
    out.append(md(["hedef kovası", "ufuk", "n", "ort. hedef", "isabet(ufuk)", "isabet B1 / B2 / B3", "MFE p25/p50/p75"], rows))

    rows = []
    for lo, hi, nm in SBUCKETS:
        m = V & bsel(T.score, lo, hi)
        if m.sum() < 20:
            continue
        rows.append([nm, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), frate(hit_h[m], T.day[m]), q3(T.mfe_h[m]),
                     "%.2f" % (np.median(T.mfe_h[m]) / np.median(T.tgt[m]))])
    out.append("\n### a4. Panel skoru kovası (tüm ufuklar)\n")
    out.append(md(["skor (panel)", "n", "ort. hedef", "isabet(ufuk)", "MFE p25/p50/p75", "medyan MFE / medyan hedef"], rows))

    dbm = V & (T.db_touched >= 0)
    out.append("\n### a5. Karşılaştırma: yeniden hesap vs DB `touched_target` (60 dk pencere, SL %5, belirsiz bar = stop)\n")
    out.append(md(["ölçüt", "n", "oran / değer"],
                  [["DB touched_target (60 dk)", int(dbm.sum()), frate(T.db_touched[dbm], T.day[dbm])],
                   ["yeniden hesap isabet(60 dk)", int(dbm.sum()), frate(hit_60[dbm], T.day[dbm])],
                   ["yeniden hesap isabet(ufuk)", int(dbm.sum()), frate(hit_h[dbm], T.day[dbm])],
                   ["DB net_pct ortalaması (%)", int(np.isfinite(T.db_net[dbm]).sum()), fnet(*ms(T.db_net[dbm], T.day[dbm]))]]))

    Nn = (T.src == "N") & (T.mode != LEGACY_MODE)
    appm = Nn & (T.app >= 0)
    rows = []
    for md_ in sorted(set(T.mode[appm])):
        for lo, hi, nm in TBUCKETS:
            m = appm & (T.mode == md_) & bsel(T.tgt, lo, hi)
            if m.sum() < 8:
                continue
            rows.append([md_, nm, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), frate(T.app[m], T.day[m]),
                         frate(hit_h[m], T.day[m]), q3(T.app_mfe[m])])
    out.append("\n### a6. Gönderilen bildirimler (monitoring_notifications, sonucu ölçülmüş; legacy global_lead_lag hariç)\n")
    out.append("uygulama isabeti = outcome_status=HEDEFE_ULTI; 'yeniden isabet' = 1 dk mumlardan ufuk içi MFE >= hedef. "
               "Toplam sonucu ölçülmüş: %d.\n" % int(appm.sum()))
    out.append(md(["mod", "hedef kovası", "n", "ort. hedef", "uygulama isabeti", "yeniden isabet(ufuk)", "uygulama MFE p25/p50/p75"], rows))
    top = []
    for tv in (2.0, 2.5, 3.0, 4.0):
        m = appm & (np.abs(T.tgt - tv) < 0.005)
        if m.sum():
            top.append([("%.1f" % tv), int(m.sum()), frate(T.app[m], T.day[m]), "%.2f" % np.median(T.app_mfe[m])])
    m = appm & (T.tgt >= 2.05) & (T.tgt < 2.45)
    top.append(["2,1–2,4", int(m.sum()), frate(T.app[m], T.day[m]), "%.2f" % np.median(T.app_mfe[m])])
    out.append("\nSabit hedef değerleri (tüm modlar, sonucu olan bildirimler):\n")
    out.append(md(["hedef", "n", "uygulama isabeti", "medyan MFE (uygulama)"], top))
    out.append("\nNot: 2,1–2,4 grubu 10-08..10-15 arasında yoğunlaşır (n=153, 10-08'de 34); hedef arttıkça isabetin tek yönlü düşmesi kısmen dönem ve skor karışımıdır (bkz. c6).")
    info["n_app"] = int(appm.sum())

    ok = np.isfinite(uni["mfe"]) & np.isfinite(uni["tgt"])
    rows = []
    for lo, hi, nm in TBUCKETS:
        m = ok & bsel(uni["tgt"], lo, hi)
        if m.sum() < 20:
            continue
        mm = uni["mfe"][m]
        okc = m & np.isfinite(uni["ceil"])
        rows.append([nm, int(m.sum()), "%.2f" % uni["tgt"][m].mean(), "%.1f%%" % (100 * np.mean(mm >= uni["tgt"][m])),
                     "%.1f%%" % (100 * np.mean(uni["mfe"][okc] >= uni["ceil"][okc])) if okc.sum() else "–", q3(mm)])
    out.append("\n### a7. Birleşik tarama journal'ı (unified_candidate_outcomes, 10-14 sonrası; yalnız B3 ile örtüşür)\n")
    out.append(md(["target_pct kovası", "n", "ort. hedef", "P(MFE>=target)", "P(MFE>=tavan)", "MFE p25/p50/p75"], rows))
    info["uni_n"] = int(ok.sum())

    out.append("\n### a8. Gösterilen hedef değerlerinin yapısı\n")
    rows = []
    mlb = np.isfinite(T.ml_prob) & (T.ml_prob >= 0.65)
    for v in (1.5, 1.9, 2.0, 2.1, 2.2, 2.5, 3.0, 4.0):
        m = V & (np.abs(T.tgt - v) < 0.05)
        rows.append(["%.1f" % v, int(m.sum()), "%.1f%%" % (100 * m.sum() / max(1, V.sum())),
                     "%.0f%%" % (100 * mlb[m].mean() if m.sum() else 0), "%.1f" % (np.mean(T.score[m]) if m.sum() else 0),
                     "%.2f" % ((v - 0.9) / 0.4)])
    out.append("Hız Avcısı adayları (V): hedef değeri -> pay; ML karışımı (ml_prob>=0,65) payı; ort. skor; 'öğrenilmiş=1,5 / ağırlık 0,6' "
               "varsayımıyla ima edilen karışım-öncesi hedef X=(t-0,9)/0,4.\n")
    out.append(md(["gösterilen hedef", "n", "pay", "ML karışımı payı", "ort. panel skor", "ima edilen X"], rows))
    if len(learned):
        pin = float(np.mean(learned[:, 0] <= 1.5 + 1e-6))
        w06 = float(np.mean(learned[:, 1] >= 12))
        out.append("\n`symbol_target_state` (öğrenilmiş sembol hedefi): %d sembol; hedefi tabana (%%1,5) yapışık olan %%%.0f; "
                   "toplam_sayı>=12 (ağırlık 0,6 tavanı) olan %%%.0f; medyan öğrenilmiş hedef %.2f." %
                   (len(learned), 100 * pin, 100 * w06, float(np.median(learned[:, 0]))))
        info["learned_pin"] = pin
        info["learned_w06"] = w06
    rows = []
    for md_ in sorted(set(T.mode[Nn])):
        m = (T.src == "N") & (T.mode == md_)
        vals, cnts = np.unique(np.round(T.tgt[m], 1), return_counts=True)
        o = np.argsort(-cnts)[:5]
        rows.append([md_, int(m.sum()), ", ".join("%.1f(%d)" % (vals[i], cnts[i]) for i in o), "%.2f" % np.median(T.tgt[m])])
    out.append("\nBildirim tablosunda mod başına en sık hedef değerleri (n):\n")
    out.append(md(["mod", "n", "en sık hedefler", "medyan"], rows))
    return "\n".join(out), info


# ------------------------------------------------------------------------------------------------ (b) net / hedef çarpanı / alternatifler
FAMILIES = (("cur_k", "mevcut hedef x k"), ("fix", "sabit"), ("atr", "ATR-k"), ("mfe60q", "sembol 60 dk MFE yüzdeliği"),
            ("mfehq", "sembol ufuk-MFE yüzdeliği"), ("calibp", "havuz MFE yüzdeliği (target_calibration)"))
PROTOCOLS = (("B1→B2", (0,), 1), ("B1→B3", (0,), 2), ("B1+B2→B3", (0, 1), 2))


def pretty(name: str) -> str:
    base, tm = name.rsplit("_", 1)
    tms = "zaman=ufuk" if tm == "H" else "zaman=60 dk"
    m = re.match(r"cur_k([\d.]+)", base)
    if m:
        return "k=%s x hedef (%s)" % (m.group(1), tms)
    m = re.match(r"fix([\d.]+)", base)
    if m:
        return "sabit %%%s (%s)" % (m.group(1), tms)
    m = re.match(r"atr([\d.]+)", base)
    if m:
        return "ATR k=%s (%s)" % (m.group(1), tms)
    m = re.match(r"mfe60q(\d+)", base)
    if m:
        return "sembol 60dk-MFE q%s (%s)" % (m.group(1), tms)
    m = re.match(r"mfehq(\d+)", base)
    if m:
        return "sembol ufuk-MFE q%s (%s)" % (m.group(1), tms)
    m = re.match(r"calibp(\d+)", base)
    if m:
        return "havuz-MFE p%s (%s)" % (m.group(1), tms)
    return name


def sec_net(T: Tab, R: dict) -> tuple[str, dict]:
    out: list[str] = []
    info: dict = {}
    V = (T.src == "V") & T.valid
    d = T.day
    out.append("Maliyet: giriş taker %%0,1125 + %%0,15 kayma; TP çıkışı maker %%0,0675 (toplam %%0,33); SL/zaman çıkışı taker + %%0,15 kayma "
               "(toplam %%0,525). SL %%3. Net = işlem başına yüzde puan (kasa değil). n = %d (V, canlıya benzer)." % int(V.sum()))

    for tm, tmname in (("H", "zaman stopu = ufuk"), ("60", "zaman stopu = 60 dk")):
        out.append("\n### b1-%s. Hedef çarpanı k x mevcut hedef (%s)\n" % (tm, tmname))
        rows = []
        for k in KS:
            r = R["cur_k%g_%s" % (k, tm)]
            m = V & np.isfinite(r["net"])
            cells = [m & (T.block == b) for b in range(3)]
            rows.append(["%g" % k, "%.2f" % np.mean(k * T.tgt[m]), "%.1f%%" % (100 * np.mean(r["hit"][m])),
                         fnet(*ms(r["net"][m], d[m])), fnet(*ms(r["net"][cells[0]], d[cells[0]])),
                         fnet(*ms(r["net"][cells[1]], d[cells[1]])), fnet(*ms(r["net"][cells[2]], d[cells[2]])),
                         "%.0f%% / %.0f%% / %.0f%%" % tuple(100 * np.mean(r["reason"][m] == c) for c in (X.R_TP, X.R_SL, X.R_TIME))])
        out.append(md(["k", "ort. TP%", "TP isabeti", "net (tümü)", "net B1", "net B2", "net B3", "çıkış: TP / SL / zaman"], rows))

        out.append("\n### b2-%s. Alternatif hedef kuralları (%s)\n" % (tm, tmname))
        rows = []
        for fam, famname in FAMILIES[1:]:
            names = [n for n in R if n.startswith(fam) and n.endswith("_" + tm)]
            for n in sorted(names):
                r = R[n]
                m = V & np.isfinite(r["net"])
                if m.sum() == 0:
                    continue
                cells = [m & (T.block == b) for b in range(3)]
                rows.append([pretty(n), int(m.sum()), "%.1f%%" % (100 * np.mean(r["hit"][m])), fnet(*ms(r["net"][m], d[m])),
                             fnet(*ms(r["net"][cells[0]], d[cells[0]])), fnet(*ms(r["net"][cells[1]], d[cells[1]])),
                             fnet(*ms(r["net"][cells[2]], d[cells[2]]))])
        out.append(md(["kural", "n", "TP isabeti", "net (tümü)", "net B1", "net B2", "net B3"], rows))

    # --- walk-forward seçim
    out.append("\n### b3. İleriye dönük (walk-forward) seçim: eğitim bloğunda en iyi kural -> sonraki blokta değerlendirme\n")
    out.append("Havuz: o zaman stopundaki TÜM kurallar (k x hedef, sabit, ATR, MFE yüzdeliği, havuz-MFE). Karşılaştırma: aynı satırlarda "
               "k=1 (mevcut hedef). 'fark' = seçilen − mevcut (eşleştirilmiş, gün-kümeli).\n")
    rows = []
    best_info = {}
    for tm in ("H", "60"):
        pool = [n for n in R if n.endswith("_" + tm) and not n.startswith("ml_")]
        base = R["cur_k1_%s" % tm]
        for pname, trb, teb in PROTOCOLS:
            trm = V & np.isin(T.block, trb)
            tem = V & (T.block == teb)
            scores = {}
            for n in pool:
                r = R[n]["net"]
                mm = trm & np.isfinite(r)
                if mm.sum() >= 200:
                    scores[n] = float(np.mean(r[mm]))
            if not scores:
                continue
            ch = max(scores, key=scores.get)
            rt = R[ch]["net"]
            mt = tem & np.isfinite(rt) & np.isfinite(base["net"])
            rows.append([tm, pname, pretty(ch), "%+.2f" % scores[ch], fnet(*ms(rt[mt], d[mt])),
                         fnet(*ms(base["net"][mt], d[mt])), fdiff(rt[mt], base["net"][mt], d[mt]),
                         "%.1f%% vs %.1f%%" % (100 * np.mean(R[ch]["hit"][mt]), 100 * np.mean(base["hit"][mt]))])
            best_info[(tm, pname)] = (ch, ms(rt[mt], d[mt]), ms(base["net"][mt], d[mt]), paired(rt[mt], base["net"][mt], d[mt]))
    out.append(md(["zaman", "protokol", "seçilen kural", "eğitim neti", "test neti", "test neti: mevcut (k=1)", "fark [seçilen−mevcut]", "TP isabeti sec. vs mevcut"], rows))
    info["wf"] = best_info

    # --- aile içi en iyi
    out.append("\n### b4. Aile içi en iyi kural (B1+B2'de seçilir, B3'te değerlendirilir; zaman stopu iki seçenek de)\n")
    rows = []
    for tm in ("H", "60"):
        base = R["cur_k1_%s" % tm]
        for fam, famname in FAMILIES:
            names = [n for n in R if n.startswith(fam) and n.endswith("_" + tm)]
            trm = V & np.isin(T.block, (0, 1))
            tem = V & (T.block == 2)
            sc = {n: float(np.mean(R[n]["net"][trm & np.isfinite(R[n]["net"])])) for n in names if (trm & np.isfinite(R[n]["net"])).sum() >= 200}
            if not sc:
                continue
            ch = max(sc, key=sc.get)
            rt = R[ch]["net"]
            mt = tem & np.isfinite(rt) & np.isfinite(base["net"])
            rows.append([tm, famname, pretty(ch), "%+.2f" % sc[ch], fnet(*ms(rt[mt], d[mt])), fdiff(rt[mt], base["net"][mt], d[mt]),
                         "%.1f%%" % (100 * np.mean(R[ch]["hit"][mt]))])
    out.append(md(["zaman", "aile", "seçilen", "eğitim neti (B1+B2)", "test neti (B3)", "fark vs mevcut k=1", "TP isabeti (B3)"], rows))

    # --- ufuk bazında
    out.append("\n### b5. Ufuk bazında k eğrisi (tüm bloklar; zaman stopu = ufuk | 60 dk)\n")
    rows = []
    for h in (5, 15):
        for k in (0.4, 0.6, 0.8, 1.0, 1.25, 1.5):
            cells = []
            for tm in ("H", "60"):
                r = R["cur_k%g_%s" % (k, tm)]
                m = V & (T.hz == h) & np.isfinite(r["net"])
                cells += [fnet(*ms(r["net"][m], d[m])), "%.1f%%" % (100 * np.mean(r["hit"][m]))]
            m = V & (T.hz == h)
            rows.append([h, "%g" % k, "%.2f" % np.mean(k * T.tgt[m])] + cells)
    out.append(md(["ufuk", "k", "ort. TP%", "net (ufuk)", "TP isabeti", "net (60 dk)", "TP isabeti"], rows))

    # --- referans: rastgele giriş değil ama "hiçbir şey" net
    sl = R["cur_k1_60"]
    out.append("\n### b6. Referans: stop/zaman çıkışlarının maliyet tabanı\n")
    m = V & np.isfinite(sl["net"])
    ex = m & (sl["reason"] != X.R_TP)
    out.append("k=1, zaman=60 dk: TP olmayan çıkışlarda ortalama net %s (n=%d) ve TP çıkışlarında %s (n=%d). Yani tüm farkı TP isabeti ile TP "
               "büyüklüğü arasındaki takas belirler; sinyal sonrası serbest 60 dk sürüklenme ortalaması %s." %
               (fnet(*ms(sl["net"][ex], d[ex])), int(ex.sum()),
                fnet(*ms(sl["net"][m & ~ex], d[m & ~ex])), int((m & ~ex).sum()),
                fnet(*ms(T.drift_h[V], d[V]))))
    return "\n".join(out), info


# ------------------------------------------------------------------------------------------------ (c) ML / kalibrasyon
def sec_ml_calib(T: Tab, R: dict) -> tuple[str, dict]:
    out: list[str] = []
    info: dict = {}
    V = (T.src == "V") & T.valid
    d = T.day
    mlv = np.isfinite(T.ml_tgt) & np.isfinite(T.ml_prob)
    hit_h = (T.mfe_h >= T.tgt - 1e-9)

    out.append("### c1. ML hedefi/olasılığı ne öngörüyor? (V, ml alanları dolu satırlar: n=%d)\n" % int((V & mlv).sum()))
    rows = []
    for name, m in [("tümü", V & mlv)] + [(BLOCK_NAMES[b], V & mlv & (T.block == b)) for b in range(3)]:
        rows.append([name, int(m.sum()), "%.2f" % np.nanmedian(T.ml_tgt[m]), "%+.3f" % spearman(T.ml_tgt[m], T.mfe_h[m]),
                     "%+.3f" % spearman(T.ml_tgt[m], T.mfe60[m]), "%.3f" % auc(T.ml_prob[m], hit_h[m]),
                     "%.3f" % auc(T.ml_prob[m], T.mfe60[m] >= 1.0), "%+.3f" % spearman(D.atr_target_pct(T.atr_db, T.hz, 1.0)[m], T.mfe_h[m])])
    out.append("Spearman(ml_target_pct, MFE) ; AUC(ml_hit_probability -> MFE(ufuk) >= gösterilen hedef) ; AUC(prob -> MFE60 >= %1) ; "
               "karşılaştırma için Spearman(atr_pct·sqrt(ufuk/5), MFE(ufuk)).\n")
    out.append(md(["küme", "n", "medyan ml_target", "ρ(ml_tgt, MFE ufuk)", "ρ(ml_tgt, MFE60)", "AUC prob→isabet", "AUC prob→MFE60≥1", "ρ(atr_pct·√(h/5), MFE ufuk)"], rows))
    info["ml_auc"] = auc(T.ml_prob[V & mlv], hit_h[V & mlv])
    info["ml_rho"] = spearman(T.ml_tgt[V & mlv], T.mfe_h[V & mlv])
    info["atr_rho"] = spearman(D.atr_target_pct(T.atr_db, T.hz, 1.0)[V & mlv], T.mfe_h[V & mlv])

    # --- karışımsız yeniden kurulum
    w = np.where(T.ml_prob >= 0.8, 0.5, np.where(T.ml_prob >= 0.65, 0.25, 0.0))
    sub = V & mlv & (w > 0) & (T.tgt > 1.5005) & (T.tgt < 5.995)
    pre = np.where(sub, (T.tgt - w * T.ml_tgt) / (1.0 - w), np.nan)
    pre = np.where(np.isfinite(pre) & (pre > 0.3), pre, np.nan)
    sub = sub & np.isfinite(pre)
    out.append("\n### c2. ML karışımı etkisi: gösterilen hedef vs karışım-öncesi hedef (aynı satırlar)\n")
    out.append("Karışım: hedef = X(1-w) + ml_target x w ; w=0,5 (prob>=0,8), 0,25 (prob>=0,65). Karışım-öncesi X geri kurulur: X=(hedef−w·ml)/(1−w); "
               "yalnız kelepçeye (1,5/6,0) değmeyen satırlar (n=%d / ML karışımı alan %d). ML hedefi çoğunlukla düşük (medyan %.2f), bu yüzden karışım "
               "hedefi AŞAĞI çeker." % (int(sub.sum()), int((V & mlv & (w > 0)).sum()), float(np.nanmedian(T.ml_tgt[V & mlv]))))
    rows = []
    for tm in ("H", "60"):
        tmv = np.minimum(T.hz, W) if tm == "H" else 60
        rs = simulate_tp(T, np.where(sub, T.tgt, np.nan), tmv)
        rp = simulate_tp(T, np.where(sub, pre, np.nan), tmv)
        rm = simulate_tp(T, np.where(sub, np.maximum(T.ml_tgt, 0.4), np.nan), tmv)
        for lab, mm in [("tümü", sub), ("w=0,5", sub & (w == 0.5)), ("w=0,25", sub & (w == 0.25))] + \
                       [(BLOCK_NAMES[b], sub & (T.block == b)) for b in range(3)]:
            if mm.sum() < 30:
                continue
            rows.append([tm, lab, int(mm.sum()), "%.2f" % np.mean(T.tgt[mm]), "%.2f" % np.mean(pre[mm]),
                         frate((T.mfe_h >= T.tgt)[mm], d[mm]), frate((T.mfe_h >= pre)[mm], d[mm]),
                         fnet(*ms(rs["net"][mm], d[mm])), fnet(*ms(rp["net"][mm], d[mm])), fdiff(rs["net"][mm], rp["net"][mm], d[mm]),
                         fnet(*ms(rm["net"][mm], d[mm]))])
    out.append(md(["zaman", "küme", "n", "ort. gösterilen", "ort. karışım-öncesi", "isabet(gösterilen)", "isabet(öncesi)", "net(gösterilen)",
                   "net(öncesi)", "fark [gösterilen−öncesi]", "net(TP=ml_target)"], rows))
    rsH = simulate_tp(T, np.where(sub, T.tgt, np.nan), np.minimum(T.hz, W))
    rpH = simulate_tp(T, np.where(sub, pre, np.nan), np.minimum(T.hz, W))
    info["ml_blend"] = (int(sub.sum()), paired(rsH["net"][sub], rpH["net"][sub], d[sub]), ms(rsH["net"][sub], d[sub]), ms(rpH["net"][sub], d[sub]))
    rs60 = simulate_tp(T, np.where(sub, T.tgt, np.nan), 60)
    rp60 = simulate_tp(T, np.where(sub, pre, np.nan), 60)
    info["ml_blend60"] = paired(rs60["net"][sub], rp60["net"][sub], d[sub])
    info["ml_hit"] = (float(np.mean((T.mfe_h >= T.tgt)[sub])), float(np.mean((T.mfe_h >= pre)[sub])))

    out.append("\n### c3. ML-karışımlı vs karışımsız satırlar: hedef ve isabet\n")
    rows = []
    for lab, m in [("ML karışımı yok (prob<0,65 / ML yok)", V & ~(mlv & (w > 0))), ("ML karışımı var (prob>=0,65)", V & mlv & (w > 0))]:
        r = R["cur_k1_H"]
        mm = m & np.isfinite(r["net"])
        rows.append([lab, int(mm.sum()), "%.2f" % np.mean(T.tgt[mm]), frate(hit_h[mm], d[mm]), "%.2f" % np.median(T.mfe_h[mm]),
                     fnet(*ms(r["net"][mm], d[mm])), fnet(*ms(R["cur_k1_60"]["net"][mm], d[mm]))])
    out.append(md(["küme", "n", "ort. hedef", "isabet(ufuk)", "medyan MFE", "net (zaman=ufuk)", "net (zaman=60)"], rows))

    # --- c6: 2,1-2,4 grubu
    Nn = (T.src == "N") & (T.mode != LEGACY_MODE) & (T.app >= 0)
    g21 = Nn & (T.tgt >= 2.05) & (T.tgt < 2.45)
    mlN = np.isfinite(T.ml_prob) & (T.ml_prob >= 0.65)
    out.append("\n### c6. Bildirimlerde 'kalibre' görünen 2,1–2,4 hedef grubu nedir?\n")
    rows = []
    for lab, m in [("hedef 2,05–2,45", g21), ("diğer hedefler", Nn & ~g21), ("diğer hedefler, skor>=90", Nn & ~g21 & (T.score >= 90))]:
        rows.append([lab, int(m.sum()), "%.0f%%" % (100 * mlN[m].mean()), "%.2f" % np.nanmean(T.ml_prob[m]), "%.1f" % np.mean(T.score[m]),
                     "%.2f" % np.mean(T.tgt[m]), frate(T.app[m], d[m]), frate((T.mfe_h >= T.tgt)[m], d[m])])
    out.append(md(["grup", "n", "ML karışımı (prob>=0,65) payı", "ort. ml_prob", "ort. skor", "ort. hedef", "uygulama isabeti", "yeniden isabet(ufuk)"], rows))
    rows = []
    for h in (5, 15):
        m = V & (T.hz == h) & (T.score >= 90)
        rows.append(["V, skor>=90, ufuk %d" % h, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), frate((T.mfe_h >= T.tgt)[m], d[m]), "%.2f" % np.median(T.mfe_h[m])])
        m = V & (T.hz == h) & (T.score < 90)
        rows.append(["V, skor<90, ufuk %d" % h, int(m.sum()), "%.2f" % np.mean(T.tgt[m]), frate((T.mfe_h >= T.tgt)[m], d[m]), "%.2f" % np.median(T.mfe_h[m])])
    out.append("\nAynı eksenin V karşılığı (ML karışımından bağımsız, skora göre):\n")
    out.append(md(["küme", "n", "ort. hedef", "isabet(ufuk)", "medyan MFE"], rows))
    out.append("\nOkuma: 2,1–2,4 grubunun tamamı ML-karışımlı ve yüksek skorludur; V'de yüksek skor zaten 15 dk'da ~%44 isabet veriyor. ML olasılığı yüksek kovada medyan MFE "
               "düşük kovadan yalnız %12-17 yüksek (tablo c5: 5 dk 0,49 vs 0,42; 15 dk 1,05 vs 0,94); isabet farkının büyük kısmı hedefin ML ile aşağı çekilmesinden ve yüksek skordan gelir (ML seçimi ile hedef düşüşü bu veriyle tam ayrıştırılamaz); yani bu grup 'iyi kalibrasyon' kanıtı değil, 'daha düşük hedef + yüksek skor' kanıtıdır.")
    info["g21"] = (int(g21.sum()), float(np.mean(mlN[g21])), float(np.mean(T.score[g21])))

    # --- target_calibration
    out.append("\n### c4. `target_calibration` (RADAR_TARGET_CALIBRATION_ENABLED): ölçülmüş MFE yüzdeliği hedef olsaydı\n")
    out.append("Emülasyon: ufuk başına önceki 14 günün V-olaylarının MFE(ufuk) yüzdeliği (>=30 örnek), [0,6; 4,5] kelepçe, 1 ondalık; yeterli "
               "örnek yoksa mevcut hedefe düşer. (Üretimde veri kaynağı unified_candidate_outcomes'tır; aşağıdaki tablo aynı hesabın V karşılığı.)\n")
    cut = float(T.meta["t_hi"])
    rows = []
    for h in (5, 15, 30, 60):
        m = (T.src == "V") & (T.hz == h) & (T.t >= cut - 14 * DAY_S) & np.isfinite(T.mfe_h)
        if m.sum() < 5:
            continue
        rows.append([h, int(m.sum())] + ["%.1f" % min(4.5, max(0.6, np.quantile(T.mfe_h[m], q))) for q in (0.3, 0.5, 0.7)] +
                    ["%.2f" % np.median(T.tgt[m])])
    out.append(md(["ufuk", "n (son 14 gün)", "p30", "p50 (varsayılan)", "p70", "mevcut medyan hedef"], rows))
    rows = []
    for tm in ("H", "60"):
        for qq in (30, 50, 70):
            arr = T.calib[qq]
            mm = V & np.isfinite(arr)
            r = R["calibp%d_%s" % (qq, tm)]
            b = R["cur_k1_%s" % tm]
            rows.append([tm, "p%d" % qq, int(mm.sum()), "%.2f" % np.mean(arr[mm]), "%.2f" % np.mean(T.tgt[mm]),
                         "%.1f%% vs %.1f%%" % (100 * np.mean(r["hit"][mm]), 100 * np.mean(b["hit"][mm])),
                         fnet(*ms(r["net"][mm], d[mm])), fnet(*ms(b["net"][mm], d[mm])), fdiff(r["net"][mm], b["net"][mm], d[mm])])
    out.append("\nKalibre hedef TP olarak (yalnız emülasyon verisi olan satırlar):\n")
    out.append(md(["zaman", "yüzdelik", "n", "ort. kalibre hedef", "ort. mevcut hedef", "TP isabeti kalibre vs mevcut", "net kalibre", "net mevcut", "fark"], rows))
    floor_lo = 2.0 + 0.275
    sh = np.mean(T.calib[50][V & np.isfinite(T.calib[50])] < floor_lo)
    out.append("\nKod notu: `dynamic_target_pct` kalibre hedefi hesapladıktan SONRA `max(hedef, net_profit_floor)` uygular (floor = 2,0 + gidiş-dönüş maliyet %%0,275 + "
               "spread; spread bilinmiyorsa 0,65 → ~%%2,9). Emülasyondaki p50 değerlerinin %%%.0f'i %.2f'nin altındadır → bayrak açılsa bile "
               "hedef çoğunlukla net-kâr tabanına (floor) geri döner; kalibrasyon yalnız skor kademesinin yukarı itişini (4,0) siler. "
               "Birleşik (fusion) yolu `horizon_minutes` geçmediği için kalibrasyondan hiç etkilenmez." % (100 * sh, floor_lo))
    info["calib_below_floor"] = float(sh)
    return "\n".join(out), info


# ------------------------------------------------------------------------------------------------ moda göre (bildirim tablosu)
def sec_mode(T: Tab, R: dict) -> str:
    out: list[str] = []
    N = (T.src == "N") & T.valid & (T.mode != LEGACY_MODE)
    d = T.day
    rows = []
    for md_ in sorted(set(T.mode[N])):
        m = N & (T.mode == md_)
        if m.sum() < 30:
            continue
        cells = [md_, int(m.sum()), "%.2f" % np.median(T.tgt[m]), frate((T.mfe_h >= T.tgt)[m], d[m]), q3(T.mfe_h[m])]
        for key in ("cur_k0.5_60", "cur_k0.7_60", "cur_k1_60", "cur_k1_H"):
            r = R[key]
            mm = m & np.isfinite(r["net"])
            cells.append(fnet(*ms(r["net"][mm], d[mm])))
        rows.append(cells)
    out.append(md(["mod", "n", "medyan hedef", "isabet(ufuk)", "MFE(ufuk) p25/p50/p75", "net k=0,5 (60)", "net k=0,7 (60)", "net k=1 (60)", "net k=1 (ufuk)"], rows))
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ ek bölümler
def sec_extra(T: Tab, R: dict) -> tuple[str, dict]:
    out: list[str] = []
    info: dict = {}
    V = (T.src == "V") & T.valid
    d = T.day
    hit_h = (T.mfe_h >= T.tgt - 1e-9)

    # --- ρ: hedefin MFE ile ilişkisi
    out.append("### a9. Hangi hedef bilgisi gerçekleşen MFE'yi sıralıyor? (V; Spearman ρ, tüm satırlar | blok başına)\n")
    cands = [("gösterilen hedef (target_pct)", T.tgt), ("panel skoru", T.score), ("ATR14(5m) x sqrt(ufuk/5)", D.atr_target_pct(T.atr, T.hz, 1.0)),
             ("üretim atr_pct (M1 ATR14) x sqrt(ufuk/5)", D.atr_target_pct(T.atr_db, T.hz, 1.0)),
             ("sembol 60 dk MFE q50 (önceki 14 g)", T.emp60_50), ("sembol ufuk-MFE q60 (önceki 14 g)", T.emph_60),
             ("ml_target_pct", T.ml_tgt), ("ufuk (dk)", T.hz.astype(float))]
    rows = []
    for nm, a in cands:
        cells = [nm, "%+.3f" % spearman(a[V], T.mfe_h[V])]
        for b in range(3):
            m = V & (T.block == b)
            cells.append("%+.3f" % spearman(a[m], T.mfe_h[m]))
        rows.append(cells)
    out.append(md(["bilgi", "ρ(tümü)", "ρ B1", "ρ B2", "ρ B3"], rows))
    info["rho_tgt"] = spearman(T.tgt[V], T.mfe_h[V])

    # --- ML olasılığı güvenilirliği
    out.append("\n### c5. ML isabet olasılığı güvenilirliği (V)\n")
    out.append("ML sınıflandırıcısı ufuk 5 için %2, ufuk 15 için %3 hedefe dokunma olasılığını tahmin eder (config.ML_HIT_TARGET_PCT). "
               "Tabloda tahmin kovası başına gerçekleşen P(MFE(ufuk) >= o ufkun ML hedefi) ve P(MFE >= gösterilen hedef).\n")
    rows = []
    for h, mt in ((5, 2.0), (15, 3.0)):
        mh = V & (T.hz == h) & np.isfinite(T.ml_prob)
        for lo, hi in ((0, 0.3), (0.3, 0.5), (0.5, 0.65), (0.65, 0.8), (0.8, 1.01)):
            m = mh & (T.ml_prob >= lo) & (T.ml_prob < hi)
            if m.sum() < 30:
                continue
            rows.append([h, "%.2f–%.2f" % (lo, hi), int(m.sum()), "%.2f" % np.mean(T.ml_prob[m]),
                         frate((T.mfe_h >= mt)[m], d[m]), frate(hit_h[m], d[m]), "%.2f" % np.median(T.mfe_h[m])])
    out.append(md(["ufuk", "ml_hit_probability", "n", "ort. tahmin", "gerçekleşen P(MFE>=ML hedefi %2/%3)", "gerçekleşen P(MFE>=gösterilen hedef)", "medyan MFE"], rows))

    # --- OOS ampirik hedef tablosu (ufuk x skor)
    out.append("\n### e1. Öneri adayı: ufuk x skor tablosundan 'ölçülmüş yüzdelik' hedef — B1+B2'de kurulur, B3'te sınanır\n")
    out.append("Hedef = ilgili hücrede eğitim bloklarının MFE(ufuk) dağılımının (1 − nominal isabet) yüzdeliği (0,05'e yuvarlı). "
               "Gerçekleşen isabet, net (zaman=ufuk | zaman=60) yalnız B3 satırlarında ölçülür. 'mevcut' = aynı B3 satırlarında gösterilen hedef.\n")
    groups = (("<74", 0, 74.0), ("74–90", 74.0, 90.0), (">=90", 90.0, 101.0))
    rows = []
    tabinfo = []
    for h in (5, 15):
        for gname, glo, ghi in groups:
            gm = V & (T.hz == h) & bsel(T.score, glo, ghi)
            tr = gm & np.isin(T.block, (0, 1))
            te = gm & (T.block == 2)
            if tr.sum() < 100 or te.sum() < 50:
                continue
            for nom in (0.5, 0.3, 0.2):
                tv = round(float(np.quantile(T.mfe_h[tr], 1 - nom)) / 0.05) * 0.05
                tv = max(tv, 0.2)
                arr = np.where(te, tv, np.nan)
                rH = simulate_tp(T, arr, np.minimum(T.hz, W))
                r60 = simulate_tp(T, arr, 60)
                rc = (T.mfe_h >= T.tgt)[te]
                rows.append([h, gname, "%d%%" % int(100 * nom), "%.2f" % tv, int(te.sum()), frate((T.mfe_h >= tv)[te], d[te]),
                             fnet(*ms(rH["net"][te], d[te])), fnet(*ms(r60["net"][te], d[te])),
                             "%.2f / %.1f%%" % (np.mean(T.tgt[te]), 100 * rc.mean())])
                tabinfo.append((h, gname, nom, tv, float(np.mean((T.mfe_h >= tv)[te]))))
    out.append(md(["ufuk", "skor", "nominal isabet", "hedef %", "n (B3)", "gerçekleşen isabet (B3)", "net B3 (zaman=ufuk)", "net B3 (zaman=60)",
                   "mevcut: ort. hedef / isabet"], rows))
    info["tab"] = tabinfo

    # --- tekdüzelik: ATR üçlüsü başına isabet
    out.append("\n### e3. Kalibrasyonun tekdüzeliği: ATR14(5m)·sqrt(ufuk/5) üçlüleri başına gerçekleşen isabet(ufuk)\n")
    out.append("İyi kalibre bir hedef, oynaklık ne olursa olsun benzer isabet vermeli. Üçlü eşikleri V satırlarının ATR·sqrt(h/5) dağılımından. "
               "Hücre: tümü / yalnız B3.\n")
    av = D.atr_target_pct(T.atr, T.hz, 1.0)
    edges = np.nanpercentile(av[V], [33.3, 66.7])
    terc = np.where(av < edges[0], 0, np.where(av < edges[1], 1, 2))
    rules = (("gösterilen hedef", T.tgt), ("ATR·sqrt(h/5) x 0,75", D.atr_target_pct(T.atr, T.hz, 0.75)),
             ("ATR·sqrt(h/5) x 1,5", D.atr_target_pct(T.atr, T.hz, 1.5)),
             ("sembol ufuk-MFE q60", T.emph_60), ("havuz-MFE p50 (emülasyon)", T.calib[50]))
    rows = []
    for nm, arr in rules:
        cells = [nm]
        for g in range(3):
            m = V & (terc == g) & np.isfinite(arr)
            m3 = m & (T.block == 2)
            cells.append("%.1f%% / %.1f%% (ort. hedef %.2f)" % (100 * np.mean((T.mfe_h >= arr)[m]), 100 * np.mean((T.mfe_h >= arr)[m3]), np.mean(arr[m])))
        rows.append(cells)
    out.append(md(["hedef kuralı", "düşük oynaklık (ATR üçlü 1)", "orta", "yüksek"], rows))
    info["terc_edges"] = [float(e) for e in edges]

    # --- başabaş isabet
    out.append("\n### e2. TP çıkışı için başabaş isabet (SL %3, k=1 mevcut hedef; ortalama kayıp, TP-dışı çıkışların ortalama netidir)\n")
    rows = []
    for tm in ("H", "60"):
        r = R["cur_k1_%s" % tm]
        m = V & np.isfinite(r["net"])
        tp_ = m & (r["reason"] == X.R_TP)
        ot = m & (r["reason"] != X.R_TP)
        gain = float(np.mean(r["net"][tp_]))
        loss = -float(np.mean(r["net"][ot]))
        be = loss / (loss + gain)
        rows.append([tm, int(m.sum()), "%.2f" % gain, "%.2f" % loss, "%.1f%%" % (100 * be), "%.1f%%" % (100 * np.mean(r["hit"][m]))])
    out.append(md(["zaman stopu", "n", "TP çıkışı ort. net", "TP-dışı çıkış ort. net (mutlak)", "başabaş isabet", "gerçekleşen TP isabeti"], rows))
    info["be"] = rows
    return "\n".join(out), info


# ------------------------------------------------------------------------------------------------ öneri formülü (nicel regresyon)
def _feats(T: Tab) -> np.ndarray:
    atr = np.clip(T.atr_db, 0.05, 5.0)   # üretimdeki atr_pct (M1 ATR14 %, velocity.py:685); yalnız V satırlarında dolu
    return np.column_stack([np.ones(T.n), np.log(atr), np.log(np.maximum(T.hz, 1) / 5.0), (np.clip(T.score, 30, 100) - 70.0) / 10.0])


def fit_quantile_target(T: Tab, train: np.ndarray, tau: float) -> np.ndarray:
    """log T = a + b·log(ATR) + d·log(h/5) + c·(skor−70)/10 ; MFE(ufuk)'in tau-yüzdeliği (pinball kayıp, Nelder–Mead)."""
    from scipy.optimize import minimize
    F = _feats(T)
    y = T.mfe_h[train]
    Ft = F[train]

    def loss(beta):
        pred = np.exp(np.clip(Ft @ beta, -4.0, 3.0))
        r = y - pred
        return float(np.mean(np.maximum(tau * r, (tau - 1.0) * r)))
    best = None
    for init in (np.array([-0.3, 0.7, 0.5, 0.1]), np.array([-0.8, 0.5, 0.7, 0.0]), np.array([0.0, 1.0, 0.5, 0.2])):
        r = minimize(loss, init, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-7, "maxiter": 2000})
        if best is None or r.fun < best.fun:
            best = r
    return best.x


def formula_target(T: Tab, beta: np.ndarray, lo: float = 0.5, hi: float = 6.0) -> np.ndarray:
    return np.clip(np.exp(np.clip(_feats(T) @ beta, -4.0, 3.0)), lo, hi)


def sec_formula(T: Tab, R: dict) -> tuple[str, dict]:
    out: list[str] = []
    info: dict = {}
    V = (T.src == "V") & T.valid
    d = T.day
    out.append("Model: T = exp(a) · atr_pct^b · (ufuk/5)^d · exp(c·(skor−70)/10), [0,5; 6,0] kelepçe; katsayılar MFE(ufuk)'in (1−nominal isabet) "
               "yüzdeliği için pinball kaybını küçültür. Eğitim: B1+B2 (ve ayrıca B1→B2 sınaması); test: B3 / B2. Girdi yalnız sinyal anında bilinenler.\n")
    rows = []
    det = []
    for nom in (0.5, 0.3):
        tau = 1.0 - nom
        for trb, teb, lab in (((0,), 1, "B1→B2"), ((0, 1), 2, "B1+B2→B3")):
            trm = V & np.isin(T.block, trb)
            beta = fit_quantile_target(T, trm, tau)
            tg = formula_target(T, beta)
            te = V & (T.block == teb)
            for tm, tmv in (("H", np.minimum(T.hz, W)), ("60", 60)):
                rr = simulate_tp(T, np.where(te, tg, np.nan), tmv)
                if tm == "H":
                    rH = rr
                else:
                    r60 = rr
            base_H = R["cur_k1_H"]
            base_60 = R["cur_k1_60"]
            rows.append(["%d%%" % int(100 * nom), lab, "a=%.2f b=%.2f d=%.2f c=%.2f" % tuple(beta), int(te.sum()),
                         "%.2f" % np.mean(tg[te]), frate((T.mfe_h >= tg)[te], d[te]), fnet(*ms(rH["net"][te], d[te])),
                         fnet(*ms(r60["net"][te], d[te])), fdiff(rH["net"][te], base_H["net"][te], d[te]),
                         fdiff(r60["net"][te], base_60["net"][te], d[te])])
            det.append((nom, lab, beta, tg, te))
    out.append(md(["nominal isabet", "protokol", "katsayılar", "n (test)", "ort. hedef", "gerçekleşen isabet", "net (zaman=ufuk)", "net (zaman=60)",
                   "fark vs mevcut (ufuk)", "fark vs mevcut (60)"], rows))
    info["rows"] = rows

    # tekdüzelik + ufuk/skor dilimleri (B1+B2→B3)
    out.append("\nB1+B2 → B3: formül hedefinin gerçekleşen isabeti, dilim başına (mevcut gösterilen hedef karşılaştırması ile):\n")
    rows = []
    av = D.atr_target_pct(T.atr, T.hz, 1.0)
    edges = np.nanpercentile(av[V], [33.3, 66.7])
    terc = np.where(av < edges[0], 0, np.where(av < edges[1], 1, 2))
    for nom, lab, beta, tg, te in det:
        if lab != "B1+B2→B3":
            continue
        slices = [("tümü", te), ("ufuk 5", te & (T.hz == 5)), ("ufuk 15", te & (T.hz == 15)),
                  ("ATR düşük", te & (terc == 0)), ("ATR orta", te & (terc == 1)), ("ATR yüksek", te & (terc == 2)),
                  ("skor<74", te & (T.score < 74)), ("skor 74–90", te & (T.score >= 74) & (T.score < 90)), ("skor>=90", te & (T.score >= 90))]
        for nm, m in slices:
            if m.sum() < 30:
                continue
            rows.append(["%d%%" % int(100 * nom), nm, int(m.sum()), "%.2f" % np.mean(tg[m]), frate((T.mfe_h >= tg)[m], d[m]),
                         "%.2f" % np.mean(T.tgt[m]), frate((T.mfe_h >= T.tgt)[m], d[m])])
    out.append(md(["nominal", "dilim", "n", "formül: ort. hedef", "formül: isabet", "mevcut: ort. hedef", "mevcut: isabet"], rows))
    # nihai katsayılar (tüm veri) — öneri için
    allm = V
    final = {}
    for nom in (0.5, 0.3):
        final[nom] = fit_quantile_target(T, allm, 1.0 - nom)
    info["final_beta"] = final
    out.append("\nTüm veriyle (B1+B2+B3) uyarlanmış katsayılar (uygulama önerisi için): " +
               "; ".join("nominal %d%%: a=%.2f b=%.2f d=%.2f c=%.2f" % ((int(100 * k),) + tuple(v)) for k, v in final.items()))
    return "\n".join(out), info


# ------------------------------------------------------------------------------------------------ kod zinciri (statik özet)
CODE_CHAIN = """\
Bildirimde görünen `target_pct` = `velocity.dynamic_target_pct(...)` çıktısıdır (velocity.py:2621-2688); bildirim `expected_price = fiyat x (1 + hedef/100)`
(monitoring.py:1521) ve mesajda `Potansiyel: +%{hedef}` (monitoring.py:1546) olarak gösterir. Zincir (sıra önemlidir; her adım bir öncekinin ÇIKTISINA uygulanır):

| # | adım | formül / bayrak | yer |
|---|---|---|---|
| 0 | profil tabanı | 5 dk 2,0; 15 dk 3,0; 30 dk 1,0; 60 dk 1,5 (`VELOCITY_PROFILES`) | velocity.py:276-287, kullanım :502-503 |
| 1 | skor kademesi | panel skor = 100·ln(1+ham)/ln(25001); `MONITORING_TARGET_SCORE_TIERS` = 74,0→4,0 ; 71,5→2,5 ; 68,2→2,0; `hedef = max(taban, en yüksek geçilen kademe)` | velocity.py:303-330, 2504-2530, 2641-2649; config.py:425-426 |
| 2 | ölçülmüş MFE kalibrasyonu (BAYRAKLI, varsayılan KAPALI) | `RADAR_TARGET_CALIBRATION_ENABLED=0`; açıksa `hedef = klamp(p50 MFE(ufuk), 0,6…4,5)` (son 14 gün, `unified_candidate_outcomes`, TTL 600 sn); kapalı/boş/ufuk=0 → değişmez | target_calibration.py:24-27, 54-83; velocity.py:2654; database.py:8333; main.py:1273,1316 |
| 3 | net-kâr tabanı | `taban = SCALPING_NET_TARGET_PCT (2,0) + gidiş-dönüş maliyet (0,275) + spread (bilinmiyorsa DEFAULT_ESTIMATED_SPREAD_PCT 0,65)` ≈ 2,3…2,9; `hedef = max(hedef, taban)` | velocity.py:2657-2661; config.py:859-860 |
| 4 | ATR potansiyeli | `hedef = max(hedef, 1,35·ATR%)` | velocity.py:2664-2666 |
| 5 | öğrenilmiş sembol hedefi | `w = min(0,6; sayı/20)`; `hedef = hedef·(1−w) + öğrenilmiş·w` (sayı ≥ 3). Öğrenilmiş = `symbol_target_state.target_pct`, 0,8·MFE EMA'sı, [1,5; 6,0] kelepçeli | velocity.py:2669-2672; database.py:6858-6883, 6886-6935 |
| 6 | ML karışımı | `ml_prob ≥ 0,65` ise `w = 0,25` (`≥ 0,80` ise 0,5); `hedef = hedef·(1−w) + ml_target_pct·w`. `ml_target_pct` = regresör çıktısı: ufuk sonu kapanışından çıkışın `ML_TARGET_QUANTILE`=0,65 yüzdeliği (MFE DEĞİL) | velocity.py:2675-2678, 987-1008; ml_forecast.py:698-760; config.py:216-220 |
| 7 | zayıf skor kelepçesi | `min(hedef, max(0,3·skor, 0,75·taban))` (panel skorlarda fiilen etkisiz); `panel_score=False` (rising) dalında `max(hedef, taban)` | velocity.py:2681-2684 |
| 8 | sınır | `[MONITORING_TARGET_PCT_MIN=1,5 ; MAX=6,0]`, 3 ondalık | velocity.py:2686-2688; config.py:434-435 |
| 9 | gerçekçilik sınırı | MACD güçlü değil ve `ml_prob < 0,5` ise `min(hedef, 3,0)` (`VELOCITY_TARGET_REALISM_*`, açık) | velocity.py:1129-1133; config.py:668-670 |
| 10 | aday/bildirim | `effective_target` → adayın `target_pct`'i (:1232) ve `ml_target_pct`'i (:1233); spread kapısı `spread > 0,35·hedef` ise aday elenir; bildirim zarfı `target_pct`, `expected_price`, `ml_target_pct`, `rr` | velocity.py:1047-1056, 1078, 1232-1233; monitoring.py:1488-1585, 1820-1887 |

Diğer yollar:

* **Yükseliş (rising) sinyali**: `dynamic_target_pct(skor, RISING_TARGET_PCT=2,2, learned, panel_score=False)`; ATR/ML/ufuk geçmez (monitoring.py:3058-3080; config.py:771).
* **Birleşik (fusion) yol**: `unified_signals.py:361-367, 464-470` `dynamic_target_pct(skor=füzyon skoru, taban=2,2, panel_score=True)` çağırır; öğrenilmiş/ML/ATR/ufuk
  GEÇMEZ → skor ≥ 74 ise kademe (**4,0**), değilse taban (~2,9). Hız adayıyla eşleşirse adayın hedefi aynen devralınır (unified_signals.py:461-462). Bu yüzden
  `unified` modunda hedef 4,0 (n=651/1111) ya da 1,5 (hız adayından, ML-kelepçeli; n=371).
* **Birleşik tarama `ceiling_pct`** (liste/rapor 'tavan', bildirim hedefi DEĞİL): `max(calculate_adaptive_targets(70, ATR, 3,0).tp2_runner, 3·ATR)`; skor sabiti 70
  olduğundan pratikte 3,0 ya da 4,4 sabitidir (unified_scan.py:462-470, 525; master_surge.py:383-436). Ölçüm: P(MFE ≥ tavan) ≈ %0,1 (tablo a7).
* **Kapalı modlar**: `notr`, `v_donusu`, `llm_ikinci_goz` varsayılan olarak bildirilmez (`RADAR_NOTIFY_DISABLED_MODES`, config.py:574); canlı modlar `trend_devam` ve `unified`.

**Zincirin davranışsal sonucu (ölçümle bağlı):** 5. adımdaki öğrenilmiş sembol hedefi, sembollerin %89'unda tabana (1,5) yapışıktır ve %97'sinde ağırlık tavanındadır (0,6). Sonuç
`gösterilen ≈ 0,4·X + 0,9` (X = 0-4. adımların çıktısı): tavan kademesi X=4,0 → **2,5**; net-kâr tabanı X≈2,9–3,0 → **~2,1**; kademe 2,5 → **~1,9**; ML karışımı → **1,5-2,3**. Yani (i) 4. ve
3. adımlar ve olası kalibrasyon, 5. adımda ×0,4'e sıkıştırılır; (ii) 'net %2 + maliyet' güvencesi (3. adım) pratikte tutmaz — V satırlarının medyan hedefi 2,06 < taban (~2,3–2,9);
(iii) hedef ufka kördür (medyan 5 dk 1,93 / 15 dk 2,10 / 60 dk 2,11) ve ATR'ye zayıf bağlıdır; (iv) sabit 4,0 yalnızca öğrenme/ML karışımı uygulanmayan fusion yolundan çıkar.
"""


# ------------------------------------------------------------------------------------------------ rapor
def top_table(T: Tab, R: dict, tg_formula: dict) -> str:
    V = (T.src == "V") & T.valid
    m3 = V & (T.block == 2)
    d = T.day
    rows = []

    def add(label, arr_tgt, rH, r60):
        m = m3 & np.isfinite(arr_tgt) & np.isfinite(rH["net"]) & np.isfinite(r60["net"])
        rows.append([label, int(m.sum()), "%.2f" % np.mean(arr_tgt[m]), frate((T.mfe_h >= arr_tgt)[m], d[m]), frate(rH["hit"][m], d[m]),
                     fnet(*ms(rH["net"][m], d[m])), frate(r60["hit"][m], d[m]), fnet(*ms(r60["net"][m], d[m]))])

    add("**mevcut hedef (k=1)**", T.tgt, R["cur_k1_H"], R["cur_k1_60"])
    add("k=0,5 x hedef", 0.5 * T.tgt, R["cur_k0.5_H"], R["cur_k0.5_60"])
    add("sabit %0,75", np.full(T.n, 0.75), R["fix0.75_H"], R["fix0.75_60"])
    add("sabit %1,5", np.full(T.n, 1.5), R["fix1.5_H"], R["fix1.5_60"])
    add("sabit %2,0", np.full(T.n, 2.0), R["fix2_H"], R["fix2_60"])
    add("ATR k=0,75", D.atr_target_pct(T.atr, T.hz, 0.75), R["atr0.75_H"], R["atr0.75_60"])
    add("ATR k=1,5", D.atr_target_pct(T.atr, T.hz, 1.5), R["atr1.5_H"], R["atr1.5_60"])
    add("sembol 60 dk MFE q50 (dyn_target c)", T.emp60_50, R["mfe60q50_H"], R["mfe60q50_60"])
    add("havuz MFE p50 (target_calibration emülasyonu)", np.where(np.isfinite(T.calib[50]), T.calib[50], T.tgt), R["calibp50_H"], R["calibp50_60"])
    for nom, (tg, rH, r60) in tg_formula.items():
        add("formül (ATR·ufuk·skor, nominal %%%d; B1+B2'de kurulu)" % int(100 * nom), tg, rH, r60)
    return md(["hedef kuralı (B3, test bloğu)", "n", "ort. hedef", "MFE>=hedef (ufuk)", "TP isabeti (zaman=ufuk)", "net (zaman=ufuk)",
               "TP isabeti (zaman=60)", "net (zaman=60)"], rows)




RECS = """\
### Öneri özeti (d)

1. **Bu çalışmanın ana bulgusu hedefin DEĞİL giriş sinyalinin net getirisi olmadığıdır**: hedef kuralı ne olursa olsun B3 neti −0,50…−0,55 bandında (mevcut −0,52/−0,53). Hedef formülü
   değiştirmek 'bildirim kârlı olur' iddiasını DESTEKLEMEZ; yalnız **gösterilen sayının doğruluğunu** (ulaşılabilirlik) ve tekdüzeliğini iyileştirir.
2. **Önerilen formül** (yalnız sinyal anı bilgisi; panel skor 30-100 aralığına kısılır, atr_pct yüzde olarak [0,05; 5]):
   `T = clamp( exp(a) · atr_pct^b · (ufuk/5)^d · exp(c·(skor−70)/10) , 0,5 ; 6,0 )`.
   * Nominal %%50 isabet: a=%(a50).2f, b=%(b50).2f, d=%(d50).2f, c=%(c50).2f (tüm veriyle); B1+B2'de kurulup B3'te sınanan sürüm: gerçekleşen isabet ≈ %%39 (ATR/ufuk/skor dilimlerinde %%33–45), ort. hedef 0,90,
     net −0,51 (zaman=ufuk) / −0,50 (zaman=60).
   * Nominal %%30 isabet: a=%(a30).2f, b=%(b30).2f, d=%(d30).2f, c=%(c30).2f; B3 gerçekleşen isabet ≈ %%24 (dilimler %%23–26; mevcut hedefte %%5–32), ort. hedef 1,45, net −0,54 / −0,54.
   * Gerçekleşen isabetin nominalden düşük olması iki kaynaktan gelir: [0,5] alt kelepçesi (maliyet tabanı) hedefi yüzdeliğin üstüne iter; B3 MFE'si B1'den düşüktür (gözlenen dönem kayması).
   * Alternatif (formülsüz, tablo): 'e1' tablosu — ufuk x skor hücresinden eğitim bloklarının MFE yüzdeliği; 5 dk için nominal %%30'da hedef ≈ 0,70 (skor<74) / 1,00 (74–90) / 1,70 (≥90) ve 15 dk için
     1,70 / 3,10 / 4,75; B3 gerçekleşen isabet nominalin altında (dönem kayması). 15 dk skor>=90'da MEVCUT hedef (≈1,8) B3'te %%42 tutuyor; tablo yöntemi (nominal %%50) orada hedefi 2,9'a çıkarıp isabeti %%22'ye düşürüyor — tabloyu
     canlıya almadan önce rolling pencereyle (14 gün) yeniden kurmak gerekir.
3. **Net hedef gösterimi**: evet, ama bilgi olarak: `net hedef = brüt − 0,33` (giriş kayması %%0,15 + taker %%0,1125 + maker TP %%0,0675; stop/zaman çıkışında 0,525). Yanında hücrenin geçmiş isabeti
   (örn. 'son 14 gün bu ufuk/skor/oynaklıkta isabet %%X') ve başabaş isabet gösterilmeli: k=1, zaman=60 dk için başabaş isabet %%54, gerçekleşen %%39 (tablo e2); 'Beklenen fiyat' bu yüzden kâr vaadi gibi okunmamalı.
4. **Kod düzeltmeleri (öncelik sırası, canlı koda bu çalışmada dokunulmadı)**:
   * (i) `unified_signals.py:361-367, 464-470` fusion yolu: sabit 4,0 (n=126 sonuçta %%4 isabet) yerine ufuk/ATR'li formül; ufuk=5 sabit yazılı.
   * (ii) `velocity.py:2669-2672` öğrenilmiş hedef: EMA 0,8·MFE ile beslendiği için sembollerin %%89'unda tabana (1,5) yapışık ve ağırlık 0,6 ⇒ kademe/taban/kalibrasyon ×0,4'e sıkışıyor. Ya EMA'yı
     anlamlı bir yüzdelikle besleyin ya da bu adımı hedeften çıkarın; şimdiki hali sabit bir doğrusal dönüşümdür.
   * (iii) `RADAR_TARGET_CALIBRATION_ENABLED` bayrağını açmak fayda sağlamaz: ölçülmüş p50 (0,6–0,8; 60 dk 1,5) net-kâr tabanının (2,3–2,9) altında kaldığı için `max(hedef, taban)` hedefi geri alır
     (emülasyonda %%99) ve fusion yolu ufuk geçmediği için hiç kalibre olmaz. Kalibrasyon ancak taban kaldırılırsa/ayrı 'net hedef' olarak ele alınırsa etkili olur.
   * (iv) Net-kâr tabanı 'net %%2 güvencesi' vaat ediyor ama 5. ve 6. adımlarda (öğrenilmiş + ML karışımı) çiğneniyor (V hedeflerinin %%%(below).0f'i 2,275'in altında). Ya vaat kaldırılmalı ya adım sırası düzeltilmeli.
   * (v) Test kirliliği: `monitoring_notifications`'ta mode NULL / BTCTRY-ETHTRY / hedef 2,0 satırları (56+) raporları bozuyor; testlerin üretim DB'sine yazması engellenmeli ve satırlar silinmeli (bu çalışmada silinmedi).
5. **Yapılmaması gerekenler**: hedefi 'daha gerçekçi' diye düşürüp isabet artışını başarı olarak sunmak (k=0,4 → zaman=60'ta %%65 TP isabeti ama net −0,51); ML karışımını 'ML iyileştirdi' diye yorumlamak (etki hedefi düşürmekten ibaret).
"""


def _parts(ex_md: str) -> dict:
    out = {}
    for chunk in ex_md.split("### ")[1:]:
        key = chunk.split(".")[0].strip()
        out[key] = "### " + chunk
    return out


VERDICT = """\
**Kısa cevap.** Gösterilen hedef, *ulaşılabilirlik beyanı* olarak sistematik şişkindir ve oynaklığa/ufka kördür; ama hedefi değiştirmek bildirimleri **kârlı yapmaz** — hiçbir kural test
bloğunda net pozitif değil; en iyi kural bile mevcuttan en fazla %(wf_lo)s … %(wf_hi)s puan farklı ve bu fark çoğunlukla sıfırdan ayırt edilemiyor.

* **(a) Kalibrasyon.** Hız Avcısı adaylarında (n=%(n_v)d, canlıya benzer) medyan MFE(ufuk) %(med_mfe).2f %% iken medyan hedef %(med_tgt).2f %% (hedef ≈ %(ratio).1f x medyan MFE;
  p75 MFE %(p75).2f %% bile hedefin altında). P(MFE ≥ hedef) = %%%(hit).1f (5 dk %%%(hit5).1f, 15 dk %%%(hit15).1f; 60 dk içinde %%%(hit60).1f). Hedef ufka (medyan 5 dk %(t5).2f / 15 dk %(t15).2f / 60 dk %(t60).2f)
  ve oynaklığa kördür: ATR üçlülerinde isabet %%%(ter_lo).0f → %%%(ter_hi).0f; gösterilen hedefin MFE ile Spearman ρ'su %(rho_tgt)+.2f (B3'te %(rho_tgt3)+.2f), ATR·√(ufuk/5)'in %(rho_atr)+.2f.
  Gönderilen bildirimlerde (uygulamanın kendi sonucu): sabit 4,0 hedefi %%%(a40).1f (n=%(n40)d), 2,5 hedefi %%%(a25).1f (n=%(n25)d); %%46 görünen 2,1-2,4 grubu (n=%(n21)d) 'iyi kalibrasyon' değil,
  tamamı ML-karışımlı (prob>=0,65) ve yüksek skorlu (ort. %(s21).0f) satırlardır: düşük hedef + yüksek skor etkisi (c6). Yapı: 5. adım öğrenilmiş sembol hedefi sembollerin %%%(pin).0f'unda 1,5'a yapışık ve ağırlık 0,6 ⇒ gösterilen ≈ 0,4·X + 0,9
  (X = kademe/taban); 'net %%2 güvencesi' (net-kâr tabanı) tutmuyor (V hedeflerinin %%%(below).0f'i en düşük taban olan 2,275'in altında).
* **(b) Net.** Gerçekçi dolumla (giriş taker+kayma, TP maker, SL %%3) bütün hücreler −0,50…−0,63: mevcut k=1 → %(net_h)s (zaman=ufuk), %(net_60)s (zaman=60 dk). k=0,4…1,5, sabit %%0,75…3, ATR-k,
  MFE yüzdeliği, havuz-MFE hepsi aynı bantta. Önceki blokta seçilen en iyi kural sonraki blokta mevcuttan yalnız %(wf_lo)s … %(wf_hi)s farklı (eşleştirilmiş; 6 protokolün %(wf_sig)d'sında %%95 aralığı sıfırı dışlıyor). Neden: giriş sinyalinin
  yönsüz olması (serbest ufuk sürüklenmesi %(drift)s) ve maliyet; TP-dışı çıkışlar ort. −%(loss).2f, başabaş TP isabeti %%%(be).0f iken gerçekleşen %%%(tphit).0f. Küçük hedef yalnız isabeti şişirir
  (k=0,4 → zaman=60'ta %%%(tp04).0f TP isabeti), neti değiştirmez.
* **(c) ML ve kalibrasyon.** ML karışımı hedefi ort. %(mlt0).2f → %(mlt1).2f çeker ve isabeti %%%(mlh_pre).0f → %%%(mlh_shown).0f yapar; net farkı küçük (%(ml_d_h)s ufuk / %(ml_d_60)s 60 dk; 60 dk sınırda anlamlı ve ML bilgisinden değil hedefin düşmesinden: TP=ml_target ile net de −0,45).
  ml_target_pct MFE ile ρ=%(ml_rho)+.2f (ATR ρ=%(atr_rho)+.2f); ml_hit_probability AUC=%(ml_auc).2f. `target_calibration` açılsa bile emülasyon p50 değerlerinin %%%(cb).0f'i net-kâr tabanının altında
  ⇒ 3. adım hedefi tabana geri alır (bayrak fiilen yalnız kademe uçlarını siler); birleşik (fusion) yol ufuk geçmediği için hiç etkilenmez. Kalibre p50'nin TP olarak neti mevcuttan +0,03…+0,05 daha iyi, aralıklar sıfırı kapsıyor (c4).
* **(d) Öneri.** Hedefi kâr vaadi olarak değil, **ölçülmüş ulaşılabilirlik** olarak tanımla: aşağıdaki nicel-regresyon formülü (yalnız sinyal anı bilgisi: üretimdeki `atr_pct` = M1 ATR14 %%, ufuk, panel skor) OOS'ta isabeti
  oynaklık/ufuk/skor dilimlerinde tekdüze yapar (B3 ATR üçlülerinde nominal %%50 formülü %%%(f50_lo).0f–%%%(f50_hi).0f, mevcut hedef %%%(c_lo).0f–%%%(c_hi).0f); net mevcutla aynı (fark ≈ 0). Bildirimde **net hedef = brüt −
  0,33** (maker TP) ve hücrenin geçmiş isabeti gösterilsin; net pozitiflik iddia edilmesin. Birleşik yoldaki sabit 4,0 (%%4 isabet) ve `ceiling_pct` (%%0,1) bu formülle değiştirilmeye en çok değer olan iki yerdir.
"""


def build_report(T: Tab, uni: dict, learned: np.ndarray, R: dict, log) -> tuple:
    V = (T.src == "V") & T.valid
    d = T.day
    cal_md, cal = sec_calibration(T, uni, learned)
    net_md, net = sec_net(T, R)
    ml_md, ml = sec_ml_calib(T, R)
    ex_md, ex = sec_extra(T, R)
    fo_md, fo = sec_formula(T, R)
    mode_md = sec_mode(T, R)
    P = _parts(ex_md)

    tg_formula = {}
    trm = V & np.isin(T.block, (0, 1))
    m3 = V & (T.block == 2)
    for nom in (0.5, 0.3):
        beta = fit_quantile_target(T, trm, 1.0 - nom)
        tg = formula_target(T, beta)
        rH = simulate_tp(T, np.where(m3, tg, np.nan), np.minimum(T.hz, W))
        r60 = simulate_tp(T, np.where(m3, tg, np.nan), 60)
        tg_formula[nom] = (tg, rH, r60)
    top = top_table(T, R, tg_formula)

    hit_h = (T.mfe_h >= T.tgt)
    av = D.atr_target_pct(T.atr, T.hz, 1.0)
    edges = np.nanpercentile(av[V], [33.3, 66.7])
    terc = np.where(av < edges[0], 0, np.where(av < edges[1], 1, 2))
    tr_c = [float(np.mean(hit_h[V & (terc == g)])) for g in range(3)]
    f_c = [float(np.mean((T.mfe_h >= tg_formula[0.5][0])[m3 & (terc == g)])) for g in range(3)]
    c_c = [float(np.mean(hit_h[m3 & (terc == g)])) for g in range(3)]
    Nn = (T.src == "N") & (T.mode != LEGACY_MODE) & (T.app >= 0)
    m40 = Nn & (np.abs(T.tgt - 4.0) < 0.005)
    m25 = Nn & (np.abs(T.tgt - 2.5) < 0.005)
    m21 = Nn & (T.tgt >= 2.05) & (T.tgt < 2.45)
    wfd = [v[3] for v in net["wf"].values()]
    wf_lo = min(x[0] for x in wfd)
    wf_hi = max(x[0] for x in wfd)
    cur_h = R["cur_k1_H"]
    mlb = ml["ml_blend"]
    sub_hit = ml["ml_hit"]
    mlprob = np.isfinite(T.ml_prob) & (T.ml_prob >= 0.65)
    K = {
        "n_v": cal["n_v"], "med_mfe": cal["overall_med_mfe"], "med_tgt": cal["overall_med_tgt"],
        "ratio": cal["overall_med_tgt"] / cal["overall_med_mfe"], "p75": cal["overall_mfe_q"][2],
        "hit": 100 * cal["overall_hit"], "hit5": 100 * float(np.mean(hit_h[V & (T.hz == 5)])), "hit15": 100 * float(np.mean(hit_h[V & (T.hz == 15)])),
        "hit60": 100 * cal["overall_hit60"], "t5": float(np.median(T.tgt[V & (T.hz == 5)])), "t15": float(np.median(T.tgt[V & (T.hz == 15)])),
        "t60": float(np.median(T.tgt[V & (T.hz == 60)])), "ter_lo": 100 * tr_c[0], "ter_hi": 100 * tr_c[2],
        "rho_tgt": ex["rho_tgt"], "rho_tgt3": spearman(T.tgt[m3], T.mfe_h[m3]), "rho_atr": spearman(D.atr_target_pct(T.atr_db, T.hz, 1.0)[V], T.mfe_h[V]),
        "a40": 100 * float(np.mean(T.app[m40])), "n40": int(m40.sum()), "a25": 100 * float(np.mean(T.app[m25])), "n25": int(m25.sum()),
        "n21": int(m21.sum()), "s21": float(np.mean(T.score[m21])), "pin": 100 * cal.get("learned_pin", 0.0),
        "below": 100 * float(np.mean(T.tgt[V] < 2.275)),
        "net_h": fnet(*ms(cur_h["net"][V], d[V])), "net_60": fnet(*ms(R["cur_k1_60"]["net"][V], d[V])),
        "wf_lo": "%+.2f" % wf_lo, "wf_hi": "%+.2f" % wf_hi, "wf_sig": sum(1 for x in wfd if abs(x[0]) > 1.96 * x[1]), "drift": fnet(*ms(T.drift_h[V], d[V])),
        "loss": float(ex["be"][1][3]), "be": float(ex["be"][1][4].rstrip("%")), "tphit": float(ex["be"][1][5].rstrip("%")),
        "tp04": 100 * float(np.mean(R["cur_k0.4_60"]["hit"][V])),
        "mlt0": float(np.mean(T.tgt[V & ~mlprob])), "mlt1": float(np.mean(T.tgt[V & mlprob])),
        "mlh_pre": 100 * sub_hit[1], "mlh_shown": 100 * sub_hit[0],
        "ml_d_h": fnet(*mlb[1]), "ml_d_60": fnet(*ml["ml_blend60"]), "ml_rho": ml["ml_rho"], "atr_rho": ml["atr_rho"], "ml_auc": ml["ml_auc"],
        "cb": 100 * ml["calib_below_floor"],
        "f50_lo": 100 * min(f_c), "f50_hi": 100 * max(f_c), "c_lo": 100 * min(c_c), "c_hi": 100 * max(c_c),
    }
    verdict = VERDICT % K
    K['final_beta'] = fo['final_beta']
    return cal_md, net_md, ml_md, P, fo_md, mode_md, top, verdict, K


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "work" / "target_audit" / "report.md"))
    ap.add_argument("--refresh", action="store_true", help="DB'den yeniden çek ve mum önbelleğini yenile")
    args = ap.parse_args(argv)

    def log(m):
        print(m, flush=True)

    T, uni, learned, meta = ensure_data(args, log)
    R = run_all(T, log)
    cal_md, net_md, ml_md, P, fo_md, mode_md, top, verdict, K = build_report(T, uni, learned, R, log)
    t_last = datetime.fromtimestamp(meta["last_candle"], TZ).strftime("%d.%m.%Y %H:%M")
    t_hi = datetime.fromtimestamp(meta["t_hi"], TZ).strftime("%d.%m.%Y %H:%M")
    n_app = int(((T.src == "N") & (T.app >= 0) & (T.mode != LEGACY_MODE)).sum())
    out = ["# Bildirim hedefi (target_pct) denetimi: üretim zinciri, kalibrasyon, net ve öneri\n",
           "Üretim: `backend/scripts/target_audit.py` (çevrimdışı, DB'ye yazmaz, canlı koda bağlanmaz). Son 1 dk mum: %s (TRT); olay kesiti: %s. "
           "Veri: %d Hız Avcısı adayı (passes, rank≤10, (sembol,ufuk) başına 60 dk soğuma), %d bildirim satırı (mode dolu; sonucu ölçülmüş: %d), %d birleşik journal satırı. "
           "Bloklar: %s | %s | %s (TRT). Önceki çalışmalar: docs/BILDIRIM_POLITIKASI_7G_2026-10-17.md, app/rescan/dyn_target.py, exit_sim.py.\n"
           % (t_last, t_hi, K["n_v"], int((T.src == "N").sum()), n_app, int(len(uni["mfe"])), BLOCK_NAMES[0], BLOCK_NAMES[1], BLOCK_NAMES[2]),
           "## 0. Karar\n", verdict,
           "\n**Özet tablo** (B3 = 10-10..10-17, test bloğu; ± %95 gün-kümeli; net = işlem başına yüzde puan; maliyet: TP %0,33, SL/zaman %0,525; SL %3; hedef kuralları önceki bloklardan türetilmiş):\n",
           top,
           "\n**Veri uyarısı (ön ölçümle fark):** `monitoring_notifications`'ta 10-17 15:38'den itibaren `mode` NULL, `horizon_minutes` NULL, sembolü BTCTRY/ETHTRY, hedefi 2,0, MFE'si ≈ 0,02 olan "
           "test kirliliği satırları var (56 satırın sonucu 'doldu'). 'Hedef 2,0 → %17 (n=88)' ön ölçümü bu satırlar yüzünden aşağı çekilmiş; burada `mode IS NOT NULL` süzülür (hedef 2,0 → n=5, uygulama isabeti ≈ %40). "
           "Aynı tarihte `velocity_candidates`'ta da hedefi 1,5-2,3 olan 60 dk adayları artıyor (10-17 14:00 sonrası).\n",
           "## 1. Kod zinciri\n", CODE_CHAIN,
           "\n## 2. Yöntem\n",
           "* **Olay kümesi V**: `velocity_candidates` (candidate_id `vel-*`; rescan/uni/backfill dışarıda), `passes AND rank<=10`, 17.09 → kesit; aynı (sembol, ufuk) için 60 dk soğuma. "
           "Bildirim kapısının (skor eşiği, kaynak teyidi, mod süzgeci) tamamı değil, 'canlıya benzer' bir üst kümedir; bildirimlerle ayrıca karşılaştırılır (a6, a10).",
           "* **MFE** (yeniden hesaplandı; DB `mfe_pct` TP/SL anında kesildiği için kullanılmadı): ilk tam 1 dk bar sinyalden sonra açılır, referans = o barın açılışı; MFE(ufuk) = ufuk dakikası içinde en yüksek high; MFE60 = 60 dk içinde.",
           "* **Net simülasyonu** (`app/rescan/exit_sim.py`): giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı x 1,0015; TP = bildirimdeki fiyat (sinyale göre), dolan girişe göre (1+T)/1,0015−1; bekleyen LIMIT maker "
           "%0,0675, kaymasız ⇒ TP çıkışında toplam maliyet %0,33; SL %3 ve zaman çıkışı taker %0,1125 + %0,15 kayma ⇒ %0,525; aynı barda SL+TP ⇒ SL. Zaman stopu iki seçenek: ufuk ve 60 dk.",
           "* **İstatistik**: ± yarı genişlik = 1,96 x gün-kümeli SE (`exit_sim.cluster_se`); eşleştirilmiş farklar aynı satırlarda. Seçim yalnız önceki bloklarda yapıldı, sonraki blokta ölçüldü (B1→B2, B1→B3, B1+B2→B3). "
           "%d strateji hücresi (2 zaman stopu dâhil) denendi: en iyi hücrelerin 'kazanan laneti' riski vardır; fark sütunları bunu zaten sıfıra yakın gösterir." % len(R),
           "* **Sınırlar**: birleşik journal ve 30/60 dk ufuk yalnız son dönemde var (30/60 dk n=302/184, hepsi B3'te); hedef kovası tabloları 5/15 dk için güvenilir. Uygulamanın kendi 'Hedefe ulaştı' etiketi benim ölçümümden gevşektir "
           "(ör. trend_devam 2,0-2,4: uygulama %54 vs yeniden %41). Net ≠ kasa getirisi: işlem başına yüzde puan.",
           "\n## 3. (a) Mevcut hedefin kalibrasyonu\n", cal_md,
           "\n### a10. Moda göre net (bildirim tablosu satırları; legacy global_lead_lag hariç)\n", mode_md, "\n", P["a9"], P["e3"],
           "\n## 4. (b) Hedef çarpanı ve alternatiflerde gerçekçi net\n", net_md, "\n", P["e2"],
           "\n## 5. (c) ML hedefi ve target_calibration\n", ml_md, "\n", P["c5"],
           "\n## 6. (d) Öneri: formül, tablo, net hedef\n", RECS % dict(a50=K["final_beta"][0.5][0], b50=K["final_beta"][0.5][1], d50=K["final_beta"][0.5][2], c50=K["final_beta"][0.5][3], a30=K["final_beta"][0.3][0], b30=K["final_beta"][0.3][1], d30=K["final_beta"][0.3][2], c30=K["final_beta"][0.3][3], below=K["below"]), fo_md, "\n", P["e1"],
           ]
    out_txt = "\n".join(out)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(out_txt, encoding="utf-8")
    log("rapor yazıldı: %s (%d bayt)" % (outp, len(out_txt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
