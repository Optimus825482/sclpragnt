"""Radar bildirim SKORU denetimi (2026-10-18, ÇEVRİMDIŞI araştırma; canlı koda BAĞLANMAZ, DB'ye YAZMAZ).

Soru: bildirimlerde görünen skor (panel 0-100 = `100*ln(1+ham)/ln(25001)` kırpılmış) fırsatları iyi sıralıyor mu,
neyin üstüne kurulu, yeniden ağırlıklandırma / yeniden eşleme (re-map) yararlı mı?

Veri
  A) DB `velocity_candidates` (canlı günlük; status=evaluated, passes ∧ rank<=10) — 17 Eyl-17 Eki (İstanbul günü).
     ETİKET REJİMLERİ (ölçümle tespit): 09-17..09-21 eski mantık (status_reason yok) ATILIR; 09-23..10-06 SL %1,5 / maliyet %0,35;
     10-07 geçiş; 10-08.. SL %5; 10-16'dan sonra TP maliyeti %0,275. Bu yüzden hem istenen B1/B2/B3 blokları hem
     etiket-homojen R1a/R1b/R2a/R2b blokları raporlanır.
  B) work/indfilter/events_ha.pkl (90 g "canlı-benzeri" tekrar; tek tip exit_sim etiketi: hit = 60 dk içinde hedefe dokunuş,
     net = SL %3, 60 sn gecikme, %0,15 kayma, %0,1125/bacak) — mod/taker/choppiness özellikleri DB'de olmayan eski günler için.
  C) DB `monitoring_notifications` (outcome_status dolu) ve `unified_candidate_outcomes`.

Çalıştırma:  python scripts/score_audit.py [--refresh] [--only extract|report]
Çıktı: work/score_audit/report.md, results.json; önbellek: SCORE_AUDIT_CACHE (vars. scratchpad/score_audit).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import warnings
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DSN = os.getenv("SCORE_AUDIT_DSN", "postgresql://postgres:518518Erkan@localhost:5432/scalper")
CACHE = Path(os.getenv(
    "SCORE_AUDIT_CACHE",
    r"C:\Users\Erkan\AppData\Local\Temp\claude\D--PROJELLER-sclpragnt\bb25c086-ec89-43e9-a810-f345b61672ad\scratchpad\score_audit"))
OUT = ROOT / "work" / "score_audit"
REF = 25000.0                       # config.MONITORING_SCORE_NORM_LOG_REF
LN_REF = math.log1p(REF)
ISTANBUL = timezone(timedelta(hours=3))
DAY0 = datetime(2026, 9, 17, tzinfo=ISTANBUL)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# =============================================================================================== saf yardımcılar
def panel_from_raw(raw):
    """unified_scan._panel_from_raw (log modu) ile BİREBİR: round(clip(100*ln(1+raw)/ln(1+REF),0,100),1)."""
    r = np.asarray(raw, dtype=float)
    p = np.where(r > 0, 100.0 * np.log1p(np.maximum(r, 0.0)) / LN_REF, 0.0)
    return np.round(np.clip(p, 0.0, 100.0), 1)


def raw_from_panel(p):
    return math.expm1(float(p) / 100.0 * LN_REF)


def auc(score, y):
    s = np.asarray(score, dtype=float)
    y = np.asarray(y, dtype=bool)
    m = np.isfinite(s)
    s, y = s[m], y[m]
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(s)
    return float((r[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def strat_auc(score, y, strata, min_cls=15):
    """Strata içi AUC'lerin n1*n0 ağırlıklı ortalaması (Mantel-Haenszel benzeri) — karıştırıcıyı (ATR) kontrol eder."""
    score = np.asarray(score, float)
    y = np.asarray(y, bool)
    num = den = 0.0
    for s in np.unique(strata):
        m = (strata == s) & np.isfinite(score)
        n1 = int(y[m].sum())
        n0 = int(m.sum()) - n1
        if n1 < min_cls or n0 < min_cls:
            continue
        a = auc(score[m], y[m])
        w = float(n1) * n0
        num += w * a
        den += w
    return num / den if den > 0 else float("nan")


def jk(cl, fn):
    """Küme (gün) silmeli jackknife: (tam örneklem değeri, SE, küme sayısı). fn(mask)->float."""
    ucl = np.unique(cl)
    G = len(ucl)
    full = fn(np.ones(len(cl), bool))
    if G < 3:
        return full, float("nan"), G
    vals = np.array([fn(cl != g) for g in ucl], dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 3:
        return full, float("nan"), G
    se = math.sqrt((len(vals) - 1) / len(vals) * float(np.sum((vals - vals.mean()) ** 2)))
    return full, se, G


def cmean(x, cl):
    """Küme-dayanıklı ortalama ve SE (oran kestirimcisi). (ortalama, SE, n)."""
    x = np.asarray(x, float)
    m = np.isfinite(x)
    x, cl = x[m], np.asarray(cl)[m]
    N = len(x)
    if N == 0:
        return float("nan"), float("nan"), 0
    mu = x.mean()
    ucl, inv = np.unique(cl, return_inverse=True)
    G = len(ucl)
    if G < 2:
        return float(mu), float("nan"), N
    S = np.bincount(inv, weights=x - mu)
    se = math.sqrt(float(np.sum(S ** 2))) / N * math.sqrt(G / (G - 1))
    return float(mu), float(se), N


def wilson(k, n, z=1.96):
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def decile_codes(s, k=10):
    s = np.asarray(s, float)
    r = rankdata(np.where(np.isfinite(s), s, -np.inf))
    return np.minimum(((r - 1) / len(s) * k).astype(int), k - 1)


def fmt(x, d=3, pct=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    if pct:
        return f"{100 * x:.1f}%"
    return f"{x:.{d}f}"


def pm(v, se, d=3, pct=False):
    if v is None or not np.isfinite(v):
        return "–"
    if se is None or not np.isfinite(se):
        return fmt(v, d, pct)
    if pct:
        return f"{100 * v:.1f}%±{100 * se:.1f}"
    return f"{v:.{d}f}±{se:.{d}f}"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def logit_cluster(X, y, cl, C=1e6):
    """Standartlaştırılmış X için lojistik katsayı + küme-dayanıklı (sandwich) SE. X (n,p). Dönüş (coef[p], se[p])."""
    from sklearn.linear_model import LogisticRegression
    X = np.asarray(X, float)
    y = np.asarray(y, int)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    m = LogisticRegression(C=C, max_iter=500)
    m.fit(Z, y)
    Z1 = np.hstack([np.ones((len(Z), 1)), Z])
    b = np.concatenate([m.intercept_, m.coef_[0]])
    p = 1.0 / (1.0 + np.exp(-(Z1 @ b)))
    W = p * (1 - p)
    bread = np.linalg.pinv(Z1.T @ (Z1 * W[:, None]))
    ucl, inv = np.unique(cl, return_inverse=True)
    G = len(ucl)
    sc = Z1 * (y - p)[:, None]
    meat = np.zeros((Z1.shape[1], Z1.shape[1]))
    for g in range(G):
        v = sc[inv == g].sum(0)
        meat += np.outer(v, v)
    cov = bread @ meat @ bread * (G / max(G - 1, 1))
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    return b[1:], se[1:]


# =============================================================================================== DB çıkarımı (salt okunur)
DB_FEATS_NUM = ["rsi", "mfi", "bb_width_pct", "adx_14", "slope_15m", "aroon_up", "change_24h", "ret_8h_pct", "choppiness_10",
                "range_pos_60", "volume_ratio", "taker_buy_ratio", "book_imbalance", "linreg_slope10_pct"]
DB_FEATS_BOOL = ["macd_bullish", "macd_rising", "m5_macd_bullish"]
G0 = ["g0_chg5", "g0_chg3", "g0_roc", "g0_atr", "g1_atr", "g2_atr"]


def _sql():
    cols = ["candidate_id", "created_at", "symbol", "price", "target_pct", "atr_pct", "ret3_pct", "velocity_score", "passes",
            "coalesce(rank,0)", "mfe_pct", "touched_target::int", "net_pct", "exit_pct", "ml_target_pct", "ml_hit_probability",
            "(regexp_match(candidate_id,'^vel-([0-9]+)dk'))[1]",
            "outcome_details->>'status_reason'", "outcome_details->>'leading_ok'", "outcome_details->>'m1_atr_prev'",
            "outcome_details->>'m3_atr_prev'", "outcome_details->>'m5_pattern_ok'"]
    cols += [f"outcome_details->'m5_pattern'->>'{g}'" for g in G0]
    cols += ["outcome_details->'microstructure'->>'whale_verdict'", "outcome_details->'microstructure'->>'whale_count'",
             "outcome_details->'microstructure'->>'cvd_try'", "outcome_details->'microstructure'->>'trade_rate_per_min'",
             "outcome_details->'microstructure'->>'data_ready'", "outcome_details->>'touch_sec'", "outcome_details->>'stop_sec'",
             "outcome_details->'features'->>'mode'", "outcome_details->'features'->>'taker_confirm'"]
    cols += [f"outcome_details->'features'->>'{k}'" for k in DB_FEATS_NUM + DB_FEATS_BOOL]
    return ("select " + ", ".join(cols) +
            " from velocity_candidates where status='evaluated' and created_at >= %s and created_at < %s order by created_at")


def _f(v):
    if v is None:
        return np.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _b(v):
    if v is None:
        return np.nan
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return 1.0 if str(v).lower() in ("true", "t", "1") else 0.0


def extract_db(refresh=False):
    path = CACHE / "vc_eval.npz"
    if path.exists() and not refresh:
        z = np.load(path, allow_pickle=False)
        return {k: z[k] for k in z.files}
    import psycopg
    CACHE.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(DSN)
    conn.read_only = True
    cur = conn.cursor()
    sql = _sql()
    rows = []
    for i in range(0, 33):
        a = (DAY0 + timedelta(days=i)).timestamp()
        b = (DAY0 + timedelta(days=i + 1)).timestamp()
        cur.execute(sql, (a, b))
        chunk = cur.fetchall()
        rows.extend(chunk)
        log(f"  extract gün {i:02d}: {len(chunk)} satır (toplam {len(rows)})")
        del chunk
    conn.close()
    names = (["candidate_id", "created_at", "symbol", "price", "target_pct", "atr_pct", "ret3_pct", "velocity_score", "passes", "rank",
              "mfe_pct", "hit", "net_pct", "exit_pct", "ml_target_pct", "ml_hit_probability", "hz", "status_reason", "leading_ok",
              "m1_atr_prev", "m3_atr_prev", "m5_ok"] + G0 +
             ["whale_verdict", "whale_count", "cvd_try", "trade_rate", "data_ready", "touch_sec", "stop_sec", "f_mode", "f_taker_confirm"] +
             ["f_" + k for k in DB_FEATS_NUM + DB_FEATS_BOOL])
    out = {}
    cols = list(zip(*rows)) if rows else [[] for _ in names]
    strings = {"candidate_id", "symbol", "status_reason", "whale_verdict", "f_mode", "f_taker_confirm"}
    boolish = {"passes", "leading_ok", "m5_ok", "data_ready"} | set(G0) | {"f_macd_bullish", "f_macd_rising", "f_m5_macd_bullish"}
    for n, c in zip(names, cols):
        if n in strings:
            out[n] = np.array(["" if v is None else str(v) for v in c], dtype="U40")
        elif n in boolish:
            out[n] = np.array([_b(v) for v in c], dtype=float)
        else:
            out[n] = np.array([_f(v) for v in c], dtype=float)
    np.savez_compressed(path, **out)
    log(f"  önbellek yazıldı: {path} ({len(rows)} satır)")
    return out


def extract_notifs(refresh=False):
    path = CACHE / "notifs.npz"
    if path.exists() and not refresh:
        z = np.load(path, allow_pickle=False)
        return {k: z[k] for k in z.files}
    import psycopg
    CACHE.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(DSN)
    conn.read_only = True
    cur = conn.cursor()
    cur.execute("""select n.id, n.symbol, n.score, n.mode, n.sources, n.outcome_status, n.mfe_pct, n.mae_pct, n.target_pct,
                          n.horizon_minutes, n.detected_at, n.candidate_id, n.message,
                          v.velocity_score, v.atr_pct, v.ret3_pct, v.target_pct, v.touched_target::int, v.net_pct, v.status
                   from monitoring_notifications n left join velocity_candidates v on v.candidate_id=n.candidate_id
                   where n.outcome_status is not null order by n.detected_at""")
    rows = cur.fetchall()
    conn.close()
    names = ["id", "symbol", "score", "mode", "sources", "outcome", "mfe", "mae", "target", "horizon", "detected_at", "candidate_id",
             "message", "v_raw", "v_atr", "v_ret3", "v_target", "v_hit", "v_net", "v_status"]
    out = {}
    for n, c in zip(names, zip(*rows)):
        if n in ("symbol", "mode", "sources", "outcome", "candidate_id", "message", "v_status"):
            out[n] = np.array(["" if v is None else str(v)[:60] for v in c], dtype="U60")
        else:
            out[n] = np.array([_f(v) for v in c], dtype=float)
    np.savez_compressed(path, **out)
    return out


def extract_unified(refresh=False):
    path = CACHE / "unified.npz"
    if path.exists() and not refresh:
        z = np.load(path, allow_pickle=False)
        return {k: z[k] for k in z.files}
    import psycopg
    CACHE.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(DSN)
    conn.read_only = True
    cur = conn.cursor()
    cur.execute("""select symbol, horizon_minutes, sources, scan_score, hit::int, mfe_pct, mae_pct, ceiling_pct, target_pct, detected_at,
                          blocked_by, regime_badge
                   from unified_candidate_outcomes where outcome_filled_at is not null and hit is not null order by detected_at""")
    rows = cur.fetchall()
    conn.close()
    names = ["symbol", "horizon", "sources", "scan_score", "hit", "mfe", "mae", "ceiling", "target", "detected_at", "blocked_by", "badge"]
    out = {}
    for n, c in zip(names, zip(*rows)):
        if n in ("symbol", "sources", "blocked_by", "badge"):
            out[n] = np.array(["" if v is None else str(v)[:80] for v in c], dtype="U80")
        else:
            out[n] = np.array([_f(v) for v in c], dtype=float)
    np.savez_compressed(path, **out)
    return out


if __name__ == "__main__" and "--only" in sys.argv and sys.argv[sys.argv.index("--only") + 1] == "extract":
    t0 = time.time()
    d = extract_db("--refresh" in sys.argv)
    n = extract_notifs("--refresh" in sys.argv)
    u = extract_unified("--refresh" in sys.argv)
    log(f"extract bitti: vc={len(d['created_at'])} notif={len(n['score'])} unified={len(u['scan_score'])} ({time.time() - t0:.0f} sn)")
    sys.exit(0)


# =============================================================================================== veri kümeleri
class Ds:
    """Analiz veri kümesi: satır başına dizi alanları + özellik sözlüğü + blok maskeleri."""

    def __init__(self, name, **kw):
        self.name = name
        self.__dict__.update(kw)

    @property
    def n(self):
        return len(self.raw)


def _safe_log(x, lo=1e-6):
    return np.log(np.maximum(np.asarray(x, float), lo))


def build_db(d):
    created = d["created_at"]
    day = ((created + 3 * 3600) // 86400).astype(int)
    d0 = int((DAY0.timestamp() + 3 * 3600) // 86400)
    di = day - d0                                   # 0 = 17 Eyl
    main = ((d["passes"] == 1) & (d["rank"] > 0) & (d["status_reason"] != "") & (di <= 30)
            & (d["atr_pct"] > 0) & (d["velocity_score"] > 0) & np.isfinite(d["net_pct"]))
    ix = np.flatnonzero(main)
    g = lambda k: d[k][ix]
    raw, atr, ret3, tgt = g("velocity_score"), g("atr_pct"), g("ret3_pct"), g("target_pct")
    dd = di[ix]
    hz = g("hz")
    mom = 0.5 + 0.5 * np.minimum(2.5, np.maximum(0.0, ret3) / 0.4)
    F = OrderedDict()
    F["log_atr"] = np.log(atr)
    F["log_score"] = np.log(raw)
    F["log_rest"] = np.log(raw / (atr * mom))        # = ln(BB-oranı × yapı × hacim × çarpanlar): DB'de gözlenmeyen kısım
    F["ret3"] = ret3
    F["mom_term"] = mom
    F["log_tgt_atr"] = np.log(np.maximum(tgt, 0.1) / atr)
    F["target"] = tgt
    F["hz15"] = (hz >= 15).astype(float)
    F["leading_ok"] = g("leading_ok")
    F["m5_ok"] = g("m5_ok")
    for k in G0:
        F[k] = g(k)
    v = d["whale_verdict"][ix]
    nw = np.where(v == "", np.nan, (v == "no_whale").astype(float))
    F["no_whale"] = nw
    F["whale_cnt"] = np.log1p(np.maximum(g("whale_count"), 0))
    cvd = g("cvd_try")
    F["cvd_sgn"] = np.sign(cvd) * np.log1p(np.abs(cvd))
    F["trade_rate"] = np.log1p(np.maximum(g("trade_rate"), 0))
    F["ml_prob"] = g("ml_hit_probability")
    F["ml_tgt"] = g("ml_target_pct")
    hour = ((created[ix] + 3 * 3600) % 86400) / 3600.0
    F["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    F["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    blocks = OrderedDict()
    for lab, (a, b) in OrderedDict([("B1", (0, 14)), ("B2", (15, 22)), ("B3", (23, 30)),
                                    ("R1a", (6, 12)), ("R1b", (13, 19)), ("R2a", (21, 25)), ("R2b", (26, 30))]).items():
        blocks[lab] = (dd >= a) & (dd <= b)
    ds = Ds("DB canlı", raw=raw, panel=panel_from_raw(raw), hit=g("hit"), net=g("net_pct"), win=(g("net_pct") > 0).astype(float),
            hz=hz, target=tgt, atr=atr, ret3=ret3, day=dd, F=F, blocks=blocks,
            symbol=d["symbol"][ix], rank=g("rank"), created=created[ix],
            extra={k: d[k][ix] for k in d if k.startswith("f_")}, mom=mom)
    ds.folds = [("B1→B2", ["B1"], "B2"), ("B1+B2→B3", ["B1", "B2"], "B3"), ("R1a→R1b", ["R1a"], "R1b"), ("R2a→R2b", ["R2a"], "R2b")]
    ds.regime_note = {"B1": "SL1,5 (09-22/23..10-01)", "B2": "SL1,5 (10-02..06) + geçiş 10-07 + SL5 (10-08..09)", "B3": "SL5",
                      "R1a": "SL1,5", "R1b": "SL1,5", "R2a": "SL5", "R2b": "SL5 (+10-16/17 TP maliyeti 0,275)"}
    return ds


def build_replay():
    import indfilter_common as C
    P = C.Pop("ha")
    ev = P.ev
    v = P.valid & (np.asarray(ev["x_rank"], float) <= 10)
    tp = np.asarray(ev["tp"], float)
    r = P.sim(tp)
    ix = np.flatnonzero(v & np.isfinite(r["net"]) & np.isfinite(r["hit"]))
    A = lambda k: np.asarray(ev[k], float)[ix]
    raw = A("x_velocity_score")
    atr = A("x_atr_pct")
    ret3 = A("x_ret3_pct")
    vr = A("x_volume_ratio")
    mom = 0.5 + 0.5 * np.minimum(2.5, np.maximum(0.0, ret3) / 0.4)
    vol_term = 0.5 + 0.5 * np.minimum(1.0, vr / 2.0)
    mode = np.asarray(ev["mode"])[ix]
    F = OrderedDict()
    F["log_atr"] = np.log(np.maximum(atr, 1e-3))
    F["log_score"] = np.log(np.maximum(raw, 1e-3))
    F["log_rest"] = np.log(np.maximum(raw, 1e-3) / (np.maximum(atr, 1e-3) * mom))
    F["log_rest2"] = np.log(np.maximum(raw, 1e-3) / (np.maximum(atr, 1e-3) * mom * vol_term))   # BB × yapı × çarpanlar
    F["ret3"] = ret3
    F["mom_term"] = mom
    F["volume_ratio"] = vr
    F["vol_term"] = vol_term
    F["log_tgt_atr"] = np.log(tp[ix] / np.maximum(atr, 1e-3))
    F["target"] = tp[ix]
    F["rank"] = A("x_rank")
    F["mode_trend"] = (mode == "trend_devam").astype(float)
    F["mode_notr"] = (mode == "notr").astype(float)
    F["mode_vdon"] = (mode == "v_donusu").astype(float)
    for k, nm in [("x_rsi", "rsi"), ("x_mfi", "mfi"), ("x_change_24h", "change_24h"), ("x_taker", "taker_buy"),
                  ("x_chop10", "chop10"), ("x_rangepos60", "range_pos60"), ("x_m1_atr_prev", "m1_atr_prev"),
                  ("x_m3_atr_prev", "m3_atr_prev"), ("x_m5_ok", "m5_ok"), ("x_leading_ok", "leading_ok"), ("x_late_phase", "late_phase")]:
        F[nm] = A(k)
    hour = ((P.t_ms[ix] / 1000.0 + 3 * 3600) % 86400) / 3600.0
    F["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    F["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    blk = P.block[ix]
    blocks = OrderedDict((f"b{i}", blk == i) for i in range(3))
    ds = Ds("Replay 90g", raw=raw, panel=panel_from_raw(raw), hit=r["hit"][ix], net=r["net"][ix], win=(r["net"][ix] > 0).astype(float),
            hz=np.full(len(ix), 15.0), target=tp[ix], atr=atr, ret3=ret3, day=P.day[ix], F=F, blocks=blocks,
            symbol=np.asarray(ev["sym"])[ix], rank=A("x_rank"), created=P.t_ms[ix] / 1000.0, extra={}, mom=mom, mode=mode)
    ds.folds = [("b0→b1", ["b0"], "b1"), ("b0+b1→b2", ["b0", "b1"], "b2")]
    ds.regime_note = {"b0": "20 Tem–18 Ağu", "b1": "19 Ağu–17 Eyl", "b2": "18 Eyl–16 Eki"}
    return ds


# =============================================================================================== (a) ayrım gücü
def make_strata(ds, m):
    """hz × ATR beşlisi (blok-içi kenarlar) → tamsayı strata kodları (m maskesi içindeki satırlar için)."""
    atr = ds.atr[m]
    q = decile_codes(atr, 5)
    return (ds.hz[m].astype(int) * 10 + q).astype(int)


def make_strata2(ds, m):
    """hz × ATR beşlisi × hedef bandı (1 puanlık) — hedef büyüklüğü de sabitlenir."""
    tb = np.clip(np.floor(ds.target[m]), 1, 5).astype(int)
    return make_strata(ds, m) * 10 + tb


def auc_row(ds, m, score, label, strat=True):
    """(AUC, SE, G, n, taban oranı, ATR-strata AUC, SE, ATR×hedef-strata AUC, SE)."""
    y = label[m] > 0.5
    s = score[m]
    cl = ds.day[m]
    st = make_strata(ds, m)
    st2 = make_strata2(ds, m)
    a, se, G = jk(cl, lambda k: auc(s[k], y[k]))
    if strat:
        sa, sse, _ = jk(cl, lambda k: strat_auc(s[k], y[k], st[k]))
        sb, ssb, _ = jk(cl, lambda k: strat_auc(s[k], y[k], st2[k]))
    else:
        sa = sse = sb = ssb = float("nan")
    return a, se, G, int(m.sum()), float(y.mean()), sa, sse, sb, ssb


def discrimination(ds, res):
    out = []
    labs = [("hit", ds.hit), ("net>0", ds.win)]
    for bname, bm in ds.blocks.items():
        for lname, lab in labs:
            for sname, sc in [("ham", ds.raw), ("panel", ds.panel)]:
                a, se, G, n, base, sa, sse, sb, ssb = auc_row(ds, bm, sc, lab)
                out.append((bname, "tüm", lname, sname, n, G, base, a, se, sa, sse, sb, ssb))
        # ufuk bazında (yalnız 5/15 ve yeterli n)
        for h in sorted(set(ds.hz[bm].astype(int))):
            mm = bm & (ds.hz == h)
            if mm.sum() < 3000:
                continue
            for lname, lab in labs:
                a, se, G, n, base, sa, sse, sb, ssb = auc_row(ds, mm, ds.panel, lab, strat=True)
                out.append((bname, f"{h}dk", lname, "panel", n, G, base, a, se, sa, sse, sb, ssb))
        if hasattr(ds, "mode"):
            for md in ("trend_devam", "notr", "v_donusu"):
                mm = bm & (ds.mode == md)
                if mm.sum() < 1500:
                    continue
                for lname, lab in labs:
                    a, se, G, n, base, sa, sse, sb, ssb = auc_row(ds, mm, ds.panel, lab, strat=True)
                    out.append((bname, md, lname, "panel", n, G, base, a, se, sa, sse, sb, ssb))
    res["disc_" + ds.name] = out
    rows = [[b, s, l, sc, n, G, fmt(base, pct=True), pm(a, se), pm(sa, sse), pm(sb, ssb)] for (b, s, l, sc, n, G, base, a, se, sa, sse, sb, ssb) in out]
    return md_table(["blok", "alt küme", "etiket", "skor", "n", "gün", "taban", "AUC±SE", "ATR-strata AUC±SE", "ATR×hedef-strata AUC±SE"], rows)


def decile_table(ds, blocks, label_name="hit"):
    """Panel skoruna göre 10'luk dilim: hit oranı, net; monotonluk özeti."""
    res_rows = []
    summ = []
    for bname in blocks:
        m = ds.blocks[bname]
        codes = decile_codes(ds.panel[m])
        hit, net, cl = ds.hit[m], ds.net[m], ds.day[m]
        hs, ns, rr = [], [], []
        for q in range(10):
            k = codes == q
            h, hse, n = cmean(hit[k], cl[k])
            nt, nse, _ = cmean(net[k], cl[k])
            hs.append(h)
            ns.append(nt)
            rr.append([bname, q + 1, n, fmt(float(np.min(ds.panel[m][k])), 1), fmt(float(np.max(ds.panel[m][k])), 1),
                       pm(h, hse, pct=True), pm(nt, nse, 2)])
        rho_h = spearmanr(range(10), hs).correlation
        rho_n = spearmanr(range(10), ns).correlation
        drops = [q + 1 for q in range(9) if hs[q + 1] < hs[q] - 0.005]
        summ.append((bname, rho_h, rho_n, drops, hs, ns))
        res_rows += rr
    return res_rows, summ


def fixed_bins(ds, blocks):
    edges = [0, 60, 70, 80, 85, 90, 95, 99.95, 100.01]
    labels = ["<60", "60–70", "70–80", "80–85", "85–90", "90–95", "95–99.9", "=100"]
    rows = []
    for bname in blocks:
        m = ds.blocks[bname]
        for i in range(len(labels)):
            k = m & (ds.panel >= edges[i]) & (ds.panel < edges[i + 1])
            if k.sum() < 30:
                continue
            h, hse, n = cmean(ds.hit[k], ds.day[k])
            nt, nse, _ = cmean(ds.net[k], ds.day[k])
            rows.append([bname, labels[i], n, len(np.unique(ds.day[k])), pm(h, hse, pct=True), pm(nt, nse, 2),
                         fmt(float(np.mean(ds.atr[k])), 2), fmt(float(np.mean(ds.target[k])), 2)])
    return rows


# =============================================================================================== (b) bileşenler
def decomposition(ds, feat_names, blocks, res, label="hit"):
    """Özellik bazında: blok AUC'leri, ATR-strata AUC (tüm bloklar birlikte), lojistik katsayı (ATR + ufuk + rejim kontrollü, küme SE)."""
    lab = ds.hit if label == "hit" else ds.win
    allm = np.zeros(ds.n, bool)
    for b in blocks:
        allm |= ds.blocks[b]
    blk_id = np.full(ds.n, -1)
    for i, b in enumerate(blocks):
        blk_id[ds.blocks[b]] = i
    rows = []
    out = []
    # strata: blok × hz × ATR beşlisi (blok-içi)
    st_all = np.full(ds.n, -1)
    for i, b in enumerate(blocks):
        m = ds.blocks[b]
        st_all[m] = i * 1000 + make_strata(ds, m)
    ctrl_cols = [ds.F["log_atr"], ds.F["hz15"] if "hz15" in ds.F else (ds.hz >= 15).astype(float)]
    reg = np.zeros(ds.n)
    for b in blocks:
        if b.startswith("R2") or b == "B3":
            reg[ds.blocks[b]] = 1.0
    ctrl_cols.append(reg)
    for fname in feat_names:
        x = np.asarray(ds.F[fname], float)
        ok = allm & np.isfinite(x)
        if ok.sum() < 2000 or np.nanstd(x[ok]) == 0:
            continue
        per_blk = []
        for b in blocks:
            mb = ds.blocks[b] & np.isfinite(x)
            per_blk.append(auc(x[mb], lab[mb] > 0.5) if mb.sum() > 500 else float("nan"))
        y = lab[ok] > 0.5
        cl = ds.day[ok]
        sa, sse, G = jk(cl, lambda k: strat_auc(x[ok][k], y[k], st_all[ok][k]))
        try:
            X = np.column_stack([x[ok]] + [c[ok] for c in ctrl_cols])
            keep = np.isfinite(X).all(1)
            co, se = logit_cluster(X[keep], lab[ok][keep] > 0.5, cl[keep])
            coef, cse = float(co[0]), float(se[0])
        except Exception as exc:                                      # pragma: no cover
            coef = cse = float("nan")
        rows.append([fname, int(ok.sum())] + [fmt(a) for a in per_blk] + [pm(sa, sse), f"{coef:+.3f} (t={coef / cse:+.1f})" if np.isfinite(cse) and cse > 0 else "–"])
        out.append({"feature": fname, "n": int(ok.sum()), "auc_blocks": per_blk, "strat_auc": sa, "strat_se": sse, "coef": coef, "coef_se": cse})
    res[f"decomp_{ds.name}_{label}"] = out
    hdr = ["özellik", "n"] + [f"AUC {b}" for b in blocks] + ["ATR-strata AUC±SE", "lojistik β/SD (ATR+ufuk+rejim kontrollü)"]
    return md_table(hdr, rows)


# =============================================================================================== (c) yürüyen-ileri modeller
HGB_KW = dict(max_iter=150, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=300, l2_regularization=1.0, early_stopping=False, random_state=0)


def feat_matrix(ds, names, idx, med=None):
    X = np.column_stack([np.asarray(ds.F[n], float)[idx] for n in names])
    return X


def impute(X, med):
    X = X.copy()
    bad = ~np.isfinite(X)
    X[bad] = np.take(med, np.where(bad)[1])
    return X


def fit_models(ds, tr, te, names_full, res_log=None):
    """Eğitim maskesi `tr`, test maskesi `te`. Dönüş: {tahmin_adı: test_dizisi}."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    itr, ite = np.flatnonzero(tr), np.flatnonzero(te)
    preds = OrderedDict()
    preds["MEVCUT panel"] = ds.panel[ite]
    preds["MEVCUT ham (kırpmasız)"] = ds.raw[ite]
    if np.isfinite(ds.F.get("ml_prob", np.array([np.nan]))).any() if "ml_prob" in ds.F else False:
        mp = np.asarray(ds.F["ml_prob"], float)[ite]
        preds["ML olasılığı (mevcut)"] = np.where(np.isfinite(mp), mp, np.nanmedian(mp))
    ytr_h, ytr_w = ds.hit[itr] > 0.5, ds.win[itr] > 0.5
    # lojistik: sade / ATR+hedef / tam
    def lr(names, ytr, label):
        Xtr = feat_matrix(ds, names, itr)
        med = np.nanmedian(Xtr, 0)
        med = np.where(np.isfinite(med), med, 0.0)
        Xtr = impute(Xtr, med)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd == 0] = 1
        m = LogisticRegression(C=0.5, max_iter=400)
        m.fit((Xtr - mu) / sd, ytr)
        Xte = impute(feat_matrix(ds, names, ite), med)
        return m.predict_proba((Xte - mu) / sd)[:, 1]
    base_names = ["log_score"] + (["hz15"] if "hz15" in ds.F else [])
    geo_names = ["log_atr", "log_tgt_atr"] + (["hz15"] if "hz15" in ds.F else [])
    preds["LR sade (log_skor+ufuk) →hit"] = lr(base_names, ytr_h, "h")
    preds["LR ATR+hedef geometrisi →hit"] = lr(geo_names, ytr_h, "h")
    preds["LR tam →hit"] = lr(names_full, ytr_h, "h")
    preds["LR tam →net>0"] = lr(names_full, ytr_w, "w")
    # HGB
    Xtr_full = feat_matrix(ds, names_full, itr)
    Xte_full = feat_matrix(ds, names_full, ite)
    mh = HistGradientBoostingClassifier(**HGB_KW).fit(Xtr_full, ytr_h)
    ph = mh.predict_proba(Xte_full)[:, 1]
    preds["HGB tam →hit"] = ph
    mw = HistGradientBoostingClassifier(**HGB_KW).fit(Xtr_full, ytr_w)
    preds["HGB tam →net>0"] = mw.predict_proba(Xte_full)[:, 1]
    # net odaklı: E = p*(hedef−c_tp) + (1−p)*m_miss
    hit_tr = ds.hit[itr] > 0.5
    c_tp = float(np.median(ds.target[itr][hit_tr] - ds.net[itr][hit_tr])) if hit_tr.any() else 0.3
    miss = ~hit_tr
    mreg = HistGradientBoostingRegressor(**HGB_KW).fit(Xtr_full[miss], ds.net[itr][miss])
    m_miss = mreg.predict(Xte_full)
    tgt_te = ds.target[ite]
    preds["NET-E: HGB p×(hedef−c)+(1−p)×kayıp"] = ph * (tgt_te - c_tp) + (1 - ph) * m_miss
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(ds.panel[itr], ds.hit[itr])
    p_iso = iso.predict(ds.panel[ite])
    preds["NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp"] = p_iso * (tgt_te - c_tp) + (1 - p_iso) * float(np.mean(ds.net[itr][miss]))
    mnet = HistGradientBoostingRegressor(**HGB_KW).fit(Xtr_full, ds.net[itr])
    preds["NET-REG: HGB doğrudan net"] = mnet.predict(Xte_full)
    aux = {"p_iso": p_iso, "p_hgb": ph, "c_tp": c_tp, "base_rate_train": float(ds.hit[itr].mean())}
    return preds, aux


PROB_PREDS = ("ML olasılığı (mevcut)", "LR sade (log_skor+ufuk) →hit", "LR ATR+hedef geometrisi →hit", "LR tam →hit", "HGB tam →hit")


def eval_preds(ds, te, preds, top=0.10, p0=None):
    ite = np.flatnonzero(te)
    hit, win, net, cl = ds.hit[ite], ds.win[ite], ds.net[ite], ds.day[ite]
    base_net, base_net_se, _ = cmean(net, cl)
    rows = []
    out = []
    for name, p in preds.items():
        a_h, se_h, G = jk(cl, lambda k: auc(p[k], hit[k] > 0.5))
        a_w, se_w, _ = jk(cl, lambda k: auc(p[k], win[k] > 0.5))
        thr = np.quantile(p, 1 - top)
        sel = p >= thr
        h, hse, n = cmean(hit[sel], cl[sel])
        nt, nse, _ = cmean(net[sel], cl[sel])
        rho = spearmanr(p, net).correlation
        bs = float("nan")
        if p0 is not None and name in PROB_PREDS:
            b_m, b_c = brier(p, hit), brier(np.full(len(hit), p0), hit)
            bs = 1.0 - b_m / b_c
        out.append({"pred": name, "auc_hit": a_h, "auc_hit_se": se_h, "auc_win": a_w, "auc_win_se": se_w, "top_n": int(sel.sum()),
                    "top_hit": h, "top_hit_se": hse, "top_net": nt, "top_net_se": nse, "rho_net": float(rho), "brier_skill": bs})
        rows.append([name, pm(a_h, se_h), pm(a_w, se_w), int(sel.sum()), pm(h, hse, pct=True), pm(nt, nse, 2), f"{rho:+.3f}",
                     (f"{100 * bs:+.1f}%" if np.isfinite(bs) else "–")])
    return rows, out, (base_net, base_net_se, float(hit.mean()), len(ite), G)


def paired_top_diff(ds, te, p_new, p_old, top=0.10):
    """Üst dilim net farkı (yeni − eski), gün-jackknife SE."""
    ite = np.flatnonzero(te)
    net, cl = ds.net[ite], ds.day[ite]
    s_new = p_new >= np.quantile(p_new, 1 - top)
    s_old = p_old >= np.quantile(p_old, 1 - top)

    def fn(k):
        a = net[k & s_new]
        b = net[k & s_old]
        if len(a) < 5 or len(b) < 5:
            return float("nan")
        return float(a.mean() - b.mean())
    return jk(cl, fn)


def rule_rows(ds, te, thr_list=(70, 85, 95, 100)):
    ite = np.flatnonzero(te)
    cl = ds.day[ite]
    rows = []
    for t in thr_list:
        sel = ds.panel[ite] >= (99.95 if t == 100 else t)
        if sel.sum() < 30:
            continue
        h, hse, n = cmean(ds.hit[ite][sel], cl[sel])
        nt, nse, _ = cmean(ds.net[ite][sel], cl[sel])
        rows.append([f"panel ≥ {t}", n, f"{100 * n / len(ite):.1f}%", pm(h, hse, pct=True), pm(nt, nse, 2)])
    return rows


# =============================================================================================== kalibrasyon / yeniden eşleme
def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(ds, res):
    from sklearn.isotonic import IsotonicRegression
    rows = []
    out = []
    for fname, trb, teb in ds.folds:
        tr = np.zeros(ds.n, bool)
        for b in trb:
            tr |= ds.blocks[b]
        te = ds.blocks[teb]
        itr, ite = np.flatnonzero(tr), np.flatnonzero(te)
        y = ds.hit[ite]
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(ds.panel[itr], ds.hit[itr])
        p_iso = iso.predict(ds.panel[ite])
        p_const = np.full(len(ite), ds.hit[itr].mean())
        # test bloğunun KENDİ taban oranı (yalnız tanı: kayma ne kadar)
        p_oracle_const = np.full(len(ite), y.mean())
        rows.append([fname, fmt(float(ds.hit[itr].mean()), pct=True), fmt(float(y.mean()), pct=True),
                     fmt(brier(p_const, y), 4), fmt(brier(p_iso, y), 4), fmt(brier(p_oracle_const, y), 4),
                     fmt(logloss(p_const, y), 4), fmt(logloss(p_iso, y), 4)])
        out.append({"fold": fname, "train_rate": float(ds.hit[itr].mean()), "test_rate": float(y.mean()),
                    "brier_const": brier(p_const, y), "brier_iso": brier(p_iso, y), "brier_oracle_const": brier(p_oracle_const, y),
                    "ll_const": logloss(p_const, y), "ll_iso": logloss(p_iso, y)})
    res["calib_" + ds.name] = out
    return md_table(["katlama", "eğitim hit", "test hit", "Brier sabit", "Brier isotonic(skor)", "Brier test-sabiti (kayma tanısı)",
                     "LogLoss sabit", "LogLoss isotonic"], rows)


def rolling_calibration(ds, res, win_days=7, start_day=None):
    """Her gün için önceki `win_days` gün üzerinde isotonic(panel→hit) — yarın için kalibre olasılık."""
    from sklearn.isotonic import IsotonicRegression
    days = np.unique(ds.day)
    allm = np.zeros(ds.n, bool)
    for b in ds.blocks.values():
        allm |= b
    if hasattr(ds, "mode"):                                    # replay: bloklar 30 gün; pencere 14 gün
        win_days = 14
    preds_iso = np.full(ds.n, np.nan)
    preds_const = np.full(ds.n, np.nan)
    for dday in days:
        te = allm & (ds.day == dday)
        tr = allm & (ds.day < dday) & (ds.day >= dday - win_days)
        if te.sum() == 0 or tr.sum() < 3000:
            continue
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(ds.panel[tr], ds.hit[tr])
        preds_iso[te] = iso.predict(ds.panel[te])
        preds_const[te] = ds.hit[tr].mean()
    ok = np.isfinite(preds_iso)
    y = ds.hit[ok]
    cl = ds.day[ok]
    bi, bc = (preds_iso[ok] - y) ** 2, (preds_const[ok] - y) ** 2
    d_mean, d_se, _ = cmean(bc - bi, cl)
    ss = 1 - bi.mean() / bc.mean()
    # güvenilirlik: tahmin ondalıkları
    codes = decile_codes(preds_iso[ok])
    rel = []
    for q in range(10):
        k = codes == q
        rel.append([q + 1, int(k.sum()), fmt(float(preds_iso[ok][k].mean()), pct=True), fmt(float(y[k].mean()), pct=True)])
    res["rolling_" + ds.name] = {"n": int(ok.sum()), "brier_iso": float(bi.mean()), "brier_const": float(bc.mean()), "skill": float(ss),
                                 "gain": d_mean, "gain_se": d_se}
    txt = (f"Yürüyen {win_days} günlük isotonic(panel→hit) vs aynı pencerenin sabit taban oranı: n={int(ok.sum())}, "
           f"Brier {bi.mean():.4f} vs {bc.mean():.4f} (beceri {100 * ss:.1f}%, kazanç {d_mean:.4f}±{d_se:.4f}).")
    return txt, md_table(["tahmin ondalığı", "n", "ort. tahmin", "gerçekleşen hit"], rel)


# =============================================================================================== bildirimler
def notif_analysis(nt, res):
    score = nt["score"]
    outcome = nt["outcome"]
    mode = np.where(nt["mode"] == "", "(boş)", nt["mode"])
    test = (nt["message"] == "radar")
    hit = (outcome == "HEDEFE_ULTI").astype(float)
    n_all = len(score)
    res["notif_n"] = n_all
    res["notif_test_rows"] = int(test.sum())
    bins = [(0, 80, "<80"), (80, 85, "80–85"), (85, 90, "85–90"), (90, 95, "90–95"), (95, 99.95, "95–99.9"), (99.95, 100.1, "=100")]
    classes = OrderedDict([("velocity-tek (trend_devam)", (~test) & (mode == "trend_devam")), ("notr", (~test) & (mode == "notr")),
                           ("unified (füzyon)", (~test) & (mode == "unified")), ("TEST/duman satırı (message='radar')", test)])
    rows = []
    for cname, cm in classes.items():
        for lo, hi, lab in bins:
            k = cm & (score >= lo) & (score < hi)
            if k.sum() == 0:
                continue
            kk = int(hit[k].sum())
            l, u = wilson(kk, int(k.sum()))
            rows.append([cname, lab, int(k.sum()), kk, fmt(kk / k.sum(), pct=True), f"{100 * l:.0f}–{100 * u:.0f}%",
                         fmt(float(np.mean(nt["mfe"][k])), 2), fmt(float(np.mean(nt["target"][k])), 2)])
    t1 = md_table(["sınıf", "panel dilimi", "n", "hedefe ulaştı", "hit", "Wilson %95", "ort. MFE%", "ort. hedef%"], rows)
    # tüm test-dışı birlikte
    clean = ~test
    rows2 = []
    for lo, hi, lab in bins:
        k = clean & (score >= lo) & (score < hi)
        if k.sum():
            kk = int(hit[k].sum())
            l, u = wilson(kk, int(k.sum()))
            rows2.append([lab, int(k.sum()), fmt(kk / k.sum(), pct=True), f"{100 * l:.0f}–{100 * u:.0f}%"])
    t2 = md_table(["panel dilimi", "n", "hit", "Wilson %95"], rows2)
    # AUC (test dışı) — hepsi / yalnız velocity-tek trend_devam
    out = {}
    for nm, k in [("tüm (test-dışı)", clean), ("trend_devam", clean & (mode == "trend_devam")), ("unified", clean & (mode == "unified")),
                  ("notr", clean & (mode == "notr"))]:
        out[nm] = (auc(score[k], hit[k] > 0.5), int(k.sum()), int(hit[k].sum()))
    res["notif_auc"] = out
    # 100'ü ne yapıyor? (eşleşen velocity_candidates satırları)
    v = clean & np.isfinite(nt["v_raw"])
    comp = []
    for lab, k in [("=100 (ham ≥ 25000)", v & (score >= 99.95)), ("85–99.9", v & (score >= 85) & (score < 99.95)), ("<85", v & (score < 85))]:
        if k.sum() == 0:
            continue
        comp.append([lab, int(k.sum()), fmt(float(np.median(nt["v_raw"][k])), 0), fmt(float(np.median(nt["v_atr"][k])), 2),
                     fmt(float(np.median(nt["v_ret3"][k])), 2), fmt(float(np.median(nt["v_target"][k])), 2),
                     fmt(float(np.nanmean(nt["v_hit"][k])), pct=True)])
    t3 = md_table(["grup", "n", "medyan ham skor", "medyan ATR%", "medyan ret3%", "medyan hedef%", "journal hit (TP-önce-SL)"], comp)
    # 74.0 test satırları
    k74 = test
    note74 = (f"score=74.0 ∧ message='radar' ∧ mod boş satır sayısı: {int(k74.sum())} "
              f"(sembol: {', '.join(sorted(set(nt['symbol'][k74]))[:6])}; aynı dakikada 4'lü yinelenen satırlar) — gerçek sinyal DEĞİL, "
              f"'70 kovası %0' bulgusunun kaynağı bu duman/test satırlarıdır.")
    # ATR kontrollü: velocity-tek/notr, journal'a eşleşen satırlar
    vv = clean & np.isfinite(nt["v_atr"]) & np.isin(mode, ["trend_devam", "notr"])
    h = hit[vv] > 0.5
    atr_ = nt["v_atr"][vv]
    st = decile_codes(atr_, 3)
    res["notif_vol"] = {"n": int(vv.sum()), "auc_panel": auc(score[vv], h), "auc_atr": auc(atr_, h),
                        "strat_auc_panel_atr_terc": strat_auc(score[vv], h, st, min_cls=10)}
    return t1, t2, t3, note74


def unified_analysis(u, res):
    s = u["scan_score"]
    hit = u["hit"]
    ntot = len(s)
    day = ((u["detected_at"] + 3 * 3600) // 86400).astype(int)
    a, se, G = jk(day, lambda k: auc(s[k], hit[k] > 0.5))
    codes = decile_codes(s)
    rows = []
    for q in range(10):
        k = codes == q
        h, hse, n = cmean(hit[k], day[k])
        rows.append([q + 1, n, fmt(float(s[k].min()), 1), fmt(float(s[k].max()), 1), pm(h, hse, pct=True)])
    # kaynak sayısı
    import json as _j
    nsrc = np.array([len(_j.loads(x)) if x.startswith("[") else (len(x.split(",")) if x else 0) for x in u["sources"]])
    rows2 = []
    for c in sorted(set(nsrc)):
        k = nsrc == c
        if k.sum() < 50:
            continue
        h, hse, n = cmean(hit[k], day[k])
        rows2.append([int(c), n, pm(h, hse, pct=True), fmt(float(s[k].mean()), 1)])
    # kaynak sayısı kontrollü AUC
    sa, sse, _ = jk(day, lambda k: strat_auc(s[k], hit[k] > 0.5, nsrc[k]))
    res["unified"] = {"n": ntot, "days": int(len(np.unique(day))), "auc": a, "se": se, "auc_strat_nsrc": sa, "base": float(hit.mean())}
    txt = (f"n={ntot}, gün={len(np.unique(day))}, taban hit={100 * hit.mean():.1f}%, AUC(scan_score→hit)={a:.3f}±{se:.3f} "
           f"(kaynak-sayısı-strata AUC {sa:.3f}±{sse:.3f}).")
    return txt, md_table(["ondalık", "n", "min", "max", "hit±SE"], rows), md_table(["kaynak sayısı", "n", "hit±SE", "ort. scan_score"], rows2)


# =============================================================================================== ana akış
DB_DECOMP = ["log_atr", "log_score", "log_rest", "ret3", "mom_term", "log_tgt_atr", "target", "leading_ok", "m5_ok", "g0_chg5", "g0_chg3",
             "g0_roc", "g0_atr", "g1_atr", "g2_atr", "no_whale", "whale_cnt", "cvd_sgn", "trade_rate", "ml_prob", "hour_sin", "hour_cos"]
DB_FULL = ["log_atr", "log_score", "log_rest", "ret3", "mom_term", "log_tgt_atr", "target", "hz15", "leading_ok", "m5_ok", "g0_chg5",
           "g0_chg3", "g0_roc", "g0_atr", "g1_atr", "g2_atr", "no_whale", "whale_cnt", "cvd_sgn", "trade_rate", "ml_prob", "ml_tgt",
           "hour_sin", "hour_cos"]
RP_DECOMP = ["log_atr", "log_score", "log_rest", "log_rest2", "ret3", "mom_term", "volume_ratio", "vol_term", "log_tgt_atr", "rank",
             "mode_trend", "mode_notr", "mode_vdon", "rsi", "mfi", "change_24h", "taker_buy", "chop10", "range_pos60", "m1_atr_prev",
             "m3_atr_prev", "m5_ok", "leading_ok", "late_phase", "hour_sin", "hour_cos"]
RP_FULL = ["log_atr", "log_score", "log_rest", "ret3", "mom_term", "volume_ratio", "log_tgt_atr", "target", "rank", "mode_trend", "mode_notr",
           "mode_vdon", "rsi", "mfi", "change_24h", "taker_buy", "chop10", "range_pos60", "m1_atr_prev", "m3_atr_prev", "m5_ok", "leading_ok",
           "late_phase", "hour_sin", "hour_cos"]


def flag_effects(ds, flags, res, tag):
    """Skor çarpanı bayraklarının ATR-standartlaştırılmış etkisi: (bayraklı − bayraksız) hit ve net farkı; tasarım yönüyle karşılaştır."""
    rows = []
    out = []
    allm = np.zeros(ds.n, bool)
    for b in ds.blocks.values():
        allm |= b
    # rejim homojenliği için DB'de R1/R2 blokları, replay'de tümü
    use = np.zeros(ds.n, bool)
    for b, m in ds.blocks.items():
        if ds.name.startswith("DB") and b not in ("R1a", "R1b", "R2a", "R2b"):
            continue
        use |= m
    st_full = np.full(ds.n, -1)
    base = 0
    for b, m in ds.blocks.items():
        if ds.name.startswith("DB") and b not in ("R1a", "R1b", "R2a", "R2b"):
            continue
        st_full[m] = base + make_strata(ds, m)
        base += 1000
    for fname, (mask, design) in flags.items():
        ok = use & np.isfinite(mask.astype(float))
        f = mask[ok].astype(bool)
        if f.sum() < 100 or (~f).sum() < 100:
            continue
        st = st_full[ok]
        hit, net, cl = ds.hit[ok], ds.net[ok], ds.day[ok]

        def sdiff(y, k):
            num = den = 0.0
            for g in np.unique(st[k]):
                mm = k & (st == g)
                a = mm & f
                b = mm & ~f
                if a.sum() < 10 or b.sum() < 10:
                    continue
                w = 1.0 / (1.0 / a.sum() + 1.0 / b.sum())
                num += w * (y[a].mean() - y[b].mean())
                den += w
            return num / den if den > 0 else float("nan")
        dh, dhs, _ = jk(cl, lambda k: sdiff(hit, k))
        dn, dns, _ = jk(cl, lambda k: sdiff(net, k))
        rows.append([fname, design, int(f.sum()), int((~f).sum()), f"{100 * dh:+.1f}±{100 * dhs:.1f} puan", f"{dn:+.3f}±{dns:.3f}"])
        out.append({"flag": fname, "design": design, "n1": int(f.sum()), "n0": int((~f).sum()), "d_hit": dh, "d_hit_se": dhs, "d_net": dn, "d_net_se": dns})
    res["flags_" + tag] = out
    return md_table(["bayrak", "tasarım yönü (skor çarpanı)", "n bayraklı", "n bayraksız", "Δ hit (ATR-strata içi)±SE", "Δ net±SE"], rows)


def simple_logit_map(ds, blocks, res, tag):
    """p(hit) = σ(b0 + b1·ln ATR + b2·ln(hedef/ATR) + b3·[ufuk≥15]) — doğal birimlerde katsayılar + küme SE + örnek tablo."""
    from sklearn.linear_model import LogisticRegression
    m = np.zeros(ds.n, bool)
    for b in blocks:
        m |= ds.blocks[b]
    X = np.column_stack([ds.F["log_atr"][m], ds.F["log_tgt_atr"][m], (ds.hz[m] >= 15).astype(float)])
    keep = np.ones(X.shape[1], bool)
    if np.std(X[:, 2]) == 0:
        keep[2] = False
    X = X[:, keep]
    y = ds.hit[m] > 0.5
    cl = ds.day[m]
    co, se = logit_cluster(X, y, cl)
    sd = X.std(0)
    mdl = LogisticRegression(C=1e6, max_iter=500).fit(X, y)
    b = mdl.coef_[0]
    b0 = float(mdl.intercept_[0])
    names = ["ln(ATR%)", "ln(hedef%/ATR%)", "ufuk≥15dk"]
    names = [n for n, k in zip(names, keep) if k]
    se_nat = se / sd
    res["simple_logit_" + tag] = {"intercept": b0, "coef": dict(zip(names, map(float, b))), "se": dict(zip(names, map(float, se_nat))), "n": int(m.sum()),
                                  "auc_in_sample": float(auc(mdl.predict_proba(X)[:, 1], y))}
    rows = [["sabit", f"{b0:+.3f}", ""]] + [[n, f"{c:+.3f}", f"±{s_:.3f}"] for n, c, s_ in zip(names, b, se_nat)]
    tbl1 = md_table(["terim", "katsayı (doğal birim)", "SE (gün-küme)"], rows)
    grid = []
    for a in (0.3, 0.5, 0.8, 1.2, 2.0, 3.0):
        r_ = [f"{a:g}"]
        for t in (1.5, 2.0, 3.0, 4.0):
            x = [math.log(a), math.log(t / a)] + ([1.0] if keep[2] else [])
            z = b0 + float(np.dot(b, x))
            r_.append(f"{100 / (1 + math.exp(-z)):.0f}%")
        grid.append(r_)
    tbl2 = md_table(["ATR% / hedef%"] + ["1,5", "2", "3", "4"], grid)
    return tbl1, tbl2



def breakeven(ds, blocks, res, tag):
    """Başabaş isabet oranı: p* = −E[net|ıska] / (E[net|isabet] − E[net|ıska]); gözlenen hit ile kıyas (tüm blok ve panel≥85 / =100 alt kümeleri)."""
    rows = []
    out = []
    for b in blocks:
        for lab, extra in (("tümü", np.ones(ds.n, bool)), ("panel ≥ 85", ds.panel >= 85), ("panel = 100", ds.panel >= 99.95)):
            m = ds.blocks[b] & extra
            h = ds.hit[m] > 0.5
            if h.sum() < 50 or (~h).sum() < 50:
                continue
            W = float(ds.net[m][h].mean())
            L = float(ds.net[m][~h].mean())
            pbe = -L / (W - L)
            obs = float(h.mean())
            rows.append([b, lab, int(m.sum()), f"{W:+.2f}", f"{L:+.2f}", fmt(pbe, pct=True), fmt(obs, pct=True), f"{100 * (obs - pbe):+.1f} puan"])
            out.append({"block": b, "subset": lab, "n": int(m.sum()), "W": W, "L": L, "p_be": pbe, "hit": obs})
    res["breakeven_" + tag] = out
    return md_table(["blok", "alt küme", "n", "E[net|isabet]", "E[net|ıska]", "başabaş isabet", "gözlenen isabet", "fark"], rows)

def run_wf(ds, names_full, res, tag):
    sections = []
    summary = []
    for fname, trb, teb in ds.folds:
        tr = np.zeros(ds.n, bool)
        for b in trb:
            tr |= ds.blocks[b]
        te = ds.blocks[teb]
        log(f"  WF {ds.name} {fname}: eğitim n={int(tr.sum())}, test n={int(te.sum())}")
        preds, aux = fit_models(ds, tr, te, names_full)
        rows, out, (bnet, bnse, bhit, nte, G) = eval_preds(ds, te, preds, p0=aux["base_rate_train"])
        res[f"wf_{tag}_{fname}"] = out
        # panel'e göre üst-dilim net farkı + AUC farkı (eşleşmiş)
        diffs = []
        for name in preds:
            if name.startswith("MEVCUT"):
                continue
            dv, dse, _ = paired_top_diff(ds, te, preds[name], preds["MEVCUT panel"])
            diffs.append((name, dv, dse))
        sections.append((fname, rows, bnet, bnse, bhit, nte, G, diffs, rule_rows(ds, te)))
        summary.append((fname, out, diffs))
        res[f"wf_{tag}_{fname}_diffs"] = [(n, dv, dse) for n, dv, dse in diffs]
        res[f"wf_{tag}_{fname}_aux"] = {"c_tp": aux["c_tp"], "base_rate_train": aux["base_rate_train"], "test_hit": bhit, "test_net": bnet}
    md = []
    for fname, rows, bnet, bnse, bhit, nte, G, diffs, rr in sections:
        md.append(f"**{fname}** — test n={nte}, gün={G}, test taban: hit {100 * bhit:.1f}%, ort. net {bnet:+.3f}±{bnse:.3f}. Üst dilim = tahminin en yüksek %10'u.")
        md.append(md_table(["tahmin", "AUC hit±SE", "AUC net>0±SE", "üst %10 n", "üst %10 hit", "üst %10 ort. net", "ρ(tahmin,net)", "Brier becerisi (hit; eğitim taban oranına göre)"], rows))
        md.append("Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): " +
                  "; ".join(f"{n.split(':')[0] if n.startswith('NET') else n}: {dv:+.3f}±{dse:.3f}" for n, dv, dse in diffs))
        md.append("Mevcut kural kesitleri (aynı test bloğu): ")
        md.append(md_table(["kural", "n", "kapsam", "hit", "ort. net"], rr))
        md.append("")
    return "\n".join(md), summary



def _rng(vals, f=lambda x: f"{x:.3f}"):
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return f"{f(min(v))}–{f(max(v))}" if v else "–"


def build_verdict(res):
    """Sayılardan otomatik özet tablo (blok aralıkları)."""
    rows = []
    for key, blocks, nm in (("disc_DB canlı", ["R1a", "R1b", "R2a", "R2b"], "DB canlı (R1 SL1,5 / R2 SL5)"),
                            ("disc_Replay 90g", ["b0", "b1", "b2"], "Replay 90 g (hit=dokunuş, SL'siz)")):
        D = res[key]
        def pick(lname, idx):
            return [t[idx] for t in D if t[1] == "tüm" and t[3] == "panel" and t[2] == lname and t[0] in blocks]
        rows.append([nm, "AUC(panel→hit)", _rng(pick("hit", 7)), _rng(pick("hit", 9)), _rng(pick("hit", 11))])
        rows.append([nm, "AUC(panel→net>0)", _rng(pick("net>0", 7)), _rng(pick("net>0", 9)), _rng(pick("net>0", 11))])
    dec = res["dec_db"]
    rows.append(["DB canlı", "ρ(panel ondalığı, ort. net) R1a/R1b/R2a/R2b", ", ".join(f"{r[2]:+.2f}" for r in dec if r[0] in ("R1a", "R1b", "R2a", "R2b")), "", ""])
    dec = res["dec_rp"]
    rows.append(["Replay", "ρ(panel ondalığı, ort. net) b0/b1/b2", ", ".join(f"{r[2]:+.2f}" for r in dec), "", ""])
    tbl = md_table(["nüfus", "ölçüt", "ham AUC (blok aralığı)", "ATR-strata AUC", "ATR×hedef-strata AUC"], rows)
    # WF özet: en iyi model − panel
    wrows = []
    best_net = (-9.0, "", 0.0)
    any_pos_lb = False
    for k in res:
        if not (k.startswith("wf_db_") or k.startswith("wf_rp_")) or k.endswith("_diffs") or k.endswith("_aux"):
            continue
        out = res[k]
        pan = next(o for o in out if o["pred"] == "MEVCUT panel")
        lrg = next(o for o in out if o["pred"] == "LR ATR+hedef geometrisi →hit")
        lrf = next(o for o in out if o["pred"] == "LR tam →hit")
        hgb = next(o for o in out if o["pred"] == "HGB tam →hit")
        mlp = next((o for o in out if o["pred"] == "ML olasılığı (mevcut)"), None)
        for o in out:
            if o["top_net"] - 1.96 * (o["top_net_se"] if np.isfinite(o["top_net_se"]) else 0) > 0:
                any_pos_lb = True
            if o["top_net"] > best_net[0]:
                best_net = (o["top_net"], f"{k}: {o['pred']}", o["top_net_se"])
        wrows.append([k.replace("wf_db_", "DB ").replace("wf_rp_", "Replay "), f"{pan['auc_hit']:.3f}",
                      f"{mlp['auc_hit']:.3f}" if mlp else "–", f"{lrg['auc_hit']:.3f}", f"{lrf['auc_hit']:.3f}", f"{hgb['auc_hit']:.3f}",
                      f"{pan['top_net']:+.2f}", f"{lrf['top_net']:+.2f}", f"{hgb['top_net']:+.2f}"])
    wtbl = md_table(["katlama", "AUC panel", "AUC ML-olasılığı (mevcut)", "AUC LR ATR+hedef", "AUC LR tam", "AUC HGB tam",
                     "üst%10 net panel", "üst%10 net LR tam", "üst%10 net HGB tam"], wrows)
    res["wf_best_net"] = {"value": best_net[0], "where": best_net[1], "se": best_net[2], "any_positive_lb": any_pos_lb}
    return tbl, wtbl

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--fast", action="store_true", help="hızlı deneme: decomposition ve WF atlanır")
    args = ap.parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    res = {}
    R = {}                                                      # rapor parçaları

    log("veri çıkarımı / önbellek")
    d = extract_db(args.refresh)
    nt = extract_notifs(args.refresh)
    un = extract_unified(args.refresh)
    db = build_db(d)
    del d
    log(f"DB ana nüfus: n={db.n}, günler={len(np.unique(db.day))}")
    rp = build_replay()
    log(f"Replay nüfus: n={rp.n}")
    res["n_db"], res["n_replay"] = db.n, rp.n

    # --- S0: eşleme tablosu + temel istatistikler
    mp = [[p, f"{raw_from_panel(p):,.0f}"] for p in (50, 60, 70, 71.5, 74, 80, 85, 90, 95, 99.9, 100)]
    R["mapping"] = md_table(["panel", "ham velocity_score eşiği"], mp)
    allm = np.zeros(db.n, bool)
    for b in ("B1", "B2", "B3"):
        allm |= db.blocks[b]
    share100 = float(np.mean(db.panel[allm] >= 99.95))
    res["share_panel100"] = share100
    # log(skor) varyansının ATR payı
    r2 = []
    for bname, bm in db.blocks.items():
        x, y = db.F["log_atr"][bm], db.F["log_score"][bm]
        r2.append([bname, int(bm.sum()), fmt(float(np.corrcoef(x, y)[0, 1] ** 2), 3), fmt(float(np.std(y)), 2),
                   fmt(float(np.std(db.F["log_rest"][bm])), 2)])
    R["atr_share"] = md_table(["blok", "n", "R²(ln skor ~ ln ATR)", "SD(ln ham skor)", "SD(ln artık = BB×yapı×hacim×çarpan)"], r2)
    # çarpanların panel puanına etkisi (tasarım gereği)
    mult = []
    for nm, m in [("taker güçlü ×1.05", 1.05), ("taker zayıf ×0.95", 0.95), ("MACD ivmeli ×1.15", 1.15), ("MACD pozitif ×1.05", 1.05),
                  ("M5+MACD ×1.10", 1.10), ("öncü ATR (leading) ×1.15", 1.15), ("aşırı alım cezası ×0.85", 0.85), ("spread bilinmiyor ×0.85", 0.85),
                  ("geç faz ×0.6", 0.6), ("choppiness rejimi ×0.5", 0.5), ("whale var ×1.05 (yalnız SIRALAMA)", 1.05), ("no_whale ×0.9 (yalnız SIRALAMA)", 0.9)]:
        mult.append([nm, f"{100 * math.log(m) / LN_REF:+.2f}"])
    R["mult_effect"] = md_table(["çarpan", "panel puanına etkisi (sabit; log harita)"], mult)

    # --- (a) ayrım gücü
    log("(a) ayrım gücü")
    R["disc_db"] = discrimination(db, res)
    R["disc_rp"] = discrimination(rp, res)
    # monotonluk
    rows_db, summ_db = decile_table(db, ["B1", "B2", "B3", "R1a", "R1b", "R2a", "R2b"])
    R["dec_db"] = md_table(["blok", "ondalık", "n", "panel min", "panel max", "hit±SE", "ort. net±SE"], rows_db)
    R["dec_db_summ"] = md_table(["blok", "ρ(ondalık,hit)", "ρ(ondalık,net)", "hit'in düştüğü adımlar (k→k+1)", "hit ondalıkları"],
                                [[b, fmt(rh, 2), fmt(rn, 2), ",".join(f"{x}→{x + 1}" for x in dr) or "yok", " ".join(f"{100 * h:.0f}" for h in hs)]
                                 for b, rh, rn, dr, hs, ns in summ_db])
    rows_rp, summ_rp = decile_table(rp, ["b0", "b1", "b2"])
    R["dec_rp"] = md_table(["blok", "ondalık", "n", "panel min", "panel max", "hit±SE", "ort. net±SE"], rows_rp)
    R["dec_rp_summ"] = md_table(["blok", "ρ(ondalık,hit)", "ρ(ondalık,net)", "hit'in düştüğü adımlar", "hit ondalıkları"],
                                [[b, fmt(rh, 2), fmt(rn, 2), ",".join(f"{x}→{x + 1}" for x in dr) or "yok", " ".join(f"{100 * h:.0f}" for h in hs)]
                                 for b, rh, rn, dr, hs, ns in summ_rp])
    res["dec_db"] = [(b, rh, rn, dr, hs, ns) for b, rh, rn, dr, hs, ns in summ_db]
    res["dec_rp"] = [(b, rh, rn, dr, hs, ns) for b, rh, rn, dr, hs, ns in summ_rp]
    R["bins_db"] = md_table(["blok", "panel dilimi", "n", "gün", "hit±SE", "ort. net±SE", "ort. ATR%", "ort. hedef%"],
                            fixed_bins(db, ["B1", "B2", "B3", "R2a", "R2b"]))
    R["bins_rp"] = md_table(["blok", "panel dilimi", "n", "gün", "hit±SE", "ort. net±SE", "ort. ATR%", "ort. hedef%"], fixed_bins(rp, ["b0", "b1", "b2"]))

    # kırpma bilgi kaybı: panel=100 içinde ham skor
    cap_rows = []
    for bname, ds_ in (("DB R1+R2", db), ("Replay", rp)):
        if bname == "Replay":
            msk = np.ones(ds_.n, bool)
        else:
            msk = np.zeros(ds_.n, bool)
            for b in ("R1a", "R1b", "R2a", "R2b"):
                msk |= ds_.blocks[b]
        top = msk & (ds_.panel >= 99.95)
        if top.sum() < 200:
            continue
        qs = np.quantile(ds_.raw[top], [0, .25, .5, .75, 1.0])
        codes = np.searchsorted(qs[1:-1], ds_.raw[top], side="right")
        for q in range(4):
            k = codes == q
            h, hse, n = cmean(ds_.hit[top][k], ds_.day[top][k])
            nt_, nse, _ = cmean(ds_.net[top][k], ds_.day[top][k])
            cap_rows.append([bname, f"ham {qs[q]:,.0f}–{qs[q + 1]:,.0f}", n, pm(h, hse, pct=True), pm(nt_, nse, 2), fmt(float(np.mean(ds_.atr[top][k])), 2)])
        a_top, se_top, _ = jk(ds_.day[top], lambda k: auc(ds_.raw[top][k], ds_.hit[top][k] > 0.5))
        sa_top, sse_top, _ = jk(ds_.day[top], lambda k: strat_auc(ds_.raw[top][k], ds_.hit[top][k] > 0.5, make_strata(ds_, top)[k]))
        res["cap_" + bname] = {"n_top": int(top.sum()), "auc_raw_within_cap": a_top, "se": se_top, "strat": sa_top, "strat_se": sse_top}
        cap_rows.append([bname, "panel=100 İÇİNDE ham skor AUC(hit)", int(top.sum()), pm(a_top, se_top), f"ATR-strata {pm(sa_top, sse_top)}", ""])
    R["cap"] = md_table(["nüfus", "panel=100 içinde ham skor dilimi", "n", "hit±SE", "ort. net±SE", "ort. ATR%"], cap_rows)

    # --- (b) bileşenler
    if not args.fast:
        log("(b) bileşenler (DB)")
        R["dec_comp_db"] = decomposition(db, DB_DECOMP, ["R1a", "R1b", "R2a", "R2b"], res, "hit")
        log("(b) bileşenler (Replay)")
        R["dec_comp_rp"] = decomposition(rp, RP_DECOMP, ["b0", "b1", "b2"], res, "hit")
    # tek-gün zengin özellik alt kümesi (DB features JSON; 10-17 sonrası)
    ex = db.extra
    sub = np.isfinite(ex["f_taker_buy_ratio"])
    rows = []
    if sub.sum() > 500:
        for k in ["f_taker_buy_ratio", "f_book_imbalance", "f_volume_ratio", "f_bb_width_pct", "f_rsi", "f_mfi", "f_choppiness_10",
                  "f_range_pos_60", "f_adx_14", "f_change_24h", "f_ret_8h_pct", "f_slope_15m", "f_aroon_up", "f_linreg_slope10_pct"]:
            x = ex[k]
            ok = sub & np.isfinite(x)
            if ok.sum() < 500:
                continue
            st = (db.hz[ok].astype(int) * 10 + decile_codes(db.atr[ok], 5))
            rows.append([k[2:], int(ok.sum()), fmt(auc(x[ok], db.hit[ok] > 0.5)), fmt(strat_auc(x[ok], db.hit[ok] > 0.5, st)),
                         fmt(auc(x[ok], db.win[ok] > 0.5))])
        rows.append(["panel (karşılaştırma)", int(sub.sum()), fmt(auc(db.panel[sub], db.hit[sub] > 0.5)),
                     fmt(strat_auc(db.panel[sub], db.hit[sub] > 0.5, (db.hz[sub].astype(int) * 10 + decile_codes(db.atr[sub], 5)))),
                     fmt(auc(db.panel[sub], db.win[sub] > 0.5))])
    R["oneday"] = (f"n={int(sub.sum())}, günler={sorted(set(int(x) for x in db.day[sub]))} (17 Eki), tek gün → küme SE'si hesaplanamaz; KEŞİF amaçlı.\n" +
                   md_table(["özellik", "n", "AUC(hit)", "ATR-strata AUC(hit)", "AUC(net>0)"], rows))

    # çarpan bayrakları: tasarım yönü vs ölçülen
    log("bayrak etkileri")
    fl_rp = OrderedDict([
        ("geç faz (24s ≥ %40)", (rp.F["late_phase"] > 0.5, "×0,6 (ceza)")),
        ("taker güçlü (≥0,58)", (rp.F["taker_buy"] >= 0.58, "×1,05 (bonus)")),
        ("taker zayıf (≤0,45)", (rp.F["taker_buy"] <= 0.45, "×0,95 (ceza)")),
        ("choppiness>61,8 (ADX'siz yaklaşık)", (rp.F["chop10"] > 61.8, "×0,5 (ceza; yalnız ADX<20 iken)")),
        ("öncü ATR (leading_ok)", (rp.F["leading_ok"] > 0.5, "×1,15 (bonus)")),
        ("M5 deseni tam (m5_ok)", (rp.F["m5_ok"] > 0.5, "yalnız etiket/kapı; skora girmez")),
        ("hacim oranı ≥ 2 (hacim terimi tavanı)", (rp.F["volume_ratio"] >= 2.0, "terim 0,5→1,0")),
        ("mod = trend_devam", (rp.F["mode_trend"] > 0.5, "—")),
        ("mod = notr", (rp.F["mode_notr"] > 0.5, "—")),
    ])
    R["flags_rp"] = flag_effects(rp, fl_rp, res, "rp")
    wh = db.F["no_whale"]
    fl_db = OrderedDict([
        ("öncü ATR (leading_ok)", (db.F["leading_ok"] > 0.5, "×1,15 (bonus)")),
        ("no_whale (whale yok)", (np.where(np.isfinite(wh), wh > 0.5, np.nan), "×0,9 (yalnız SIRALAMA)")),
        ("CVD > 0 (CVD≠0 olanlar arasında; CVD<0'a karşı)", (np.where(np.isfinite(db.F["cvd_sgn"]) & (db.F["cvd_sgn"] != 0), db.F["cvd_sgn"] > 0, np.nan), "skora girmez (docstring: 'CVD ayırmıyor')")),
        ("trade_rate > 0 (mikro-yapı akışı var)", (np.where(np.isfinite(db.F["trade_rate"]), db.F["trade_rate"] > 0, np.nan), "skora girmez")),
        ("M5 deseni tam (m5_ok)", (db.F["m5_ok"] > 0.5, "yalnız etiket/kapı")),
    ])
    R["flags_db"] = flag_effects(db, fl_db, res, "db")
    R["be_db"] = breakeven(db, ["R1a", "R1b", "R2a", "R2b"], res, "db")
    R["be_rp"] = breakeven(rp, ["b0", "b1", "b2"], res, "rp")
    R["simple_rp"], R["simple_rp_grid"] = simple_logit_map(rp, ["b0", "b1", "b2"], res, "replay")
    R["simple_db2"], R["simple_db2_grid"] = simple_logit_map(db, ["R2a", "R2b"], res, "db_R2")
    R["simple_db1"], R["simple_db1_grid"] = simple_logit_map(db, ["R1a", "R1b"], res, "db_R1")

    # --- (c) yürüyen-ileri
    if not args.fast:
        log("(c) WF DB")
        R["wf_db"], sum_db = run_wf(db, DB_FULL, res, "db")
        log("(c) WF Replay")
        R["wf_rp"], sum_rp = run_wf(rp, RP_FULL, res, "rp")

    # --- (d) kalibrasyon / eşleme
    log("(d) kalibrasyon")
    R["calib_db"] = calibration(db, res)
    R["calib_rp"] = calibration(rp, res)
    txt, tbl = rolling_calibration(db, res)
    R["roll_db"] = txt + "\n\n" + tbl
    txt, tbl = rolling_calibration(rp, res)
    R["roll_rp"] = txt + "\n\n" + tbl
    # güncel eşleme önerisi: son rejim (R2a+R2b) için panel dilimi → hit
    edges = [0, 60, 70, 80, 85, 90, 95, 99.95, 100.1]
    labs = ["<60", "60–70", "70–80", "80–85", "85–90", "90–95", "95–99.9", "=100"]
    mp_rows = []
    m2 = db.blocks["R2a"] | db.blocks["R2b"]
    m1 = db.blocks["R1a"] | db.blocks["R1b"]
    for i, lab in enumerate(labs):
        r_ = [lab]
        for mm in (m1, m2, rp.blocks["b0"] | rp.blocks["b1"] | rp.blocks["b2"]):
            ds_ = rp if mm is not m1 and mm is not m2 else db
            k = mm & (ds_.panel >= edges[i]) & (ds_.panel < edges[i + 1])
            if k.sum() < 50:
                r_ += ["–", "–"]
            else:
                h, hse, n = cmean(ds_.hit[k], ds_.day[k])
                r_ += [pm(h, hse, pct=True), n]
        mp_rows.append(r_)
    R["remap"] = md_table(["panel dilimi", "R1 (SL1,5) hit", "n", "R2 (SL5) hit", "n", "Replay (touch) hit", "n"], mp_rows)

    # --- bildirimler ve unified
    log("bildirimler / unified")
    R["notif1"], R["notif2"], R["notif3"], R["note74"] = notif_analysis(nt, res)
    u_txt, u_dec, u_src = unified_analysis(un, res)
    R["uni_txt"], R["uni_dec"], R["uni_src"] = u_txt, u_dec, u_src

    if not args.fast:
        R["verdict_tbl"], R["verdict_wf"] = build_verdict(res)
        R["best_net"] = (f"Tüm katlama × tahmin arasında en yüksek üst-%10 ortalama net: {res['wf_best_net']['value']:+.3f} "
                         f"(±{res['wf_best_net']['se']:.3f}) — {res['wf_best_net']['where']}. Alt %95 sınırı > 0 olan hiçbir (katlama, tahmin) çifti "
                         + ("VAR." if res['wf_best_net']['any_positive_lb'] else "YOK."))
    json.dump(res, open(OUT / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    (CACHE / "R.json").write_text(json.dumps(R, ensure_ascii=False), encoding="utf-8")
    log(f"ham tablolar bitti ({time.time() - t0:.0f} sn)")
    if "report" in sys.argv or True:
        from_report(R, res)


def from_report(R, res):
    """Rapor şablonu (REPORT_TEMPLATE) ham tablolarla birleştirilir."""
    try:
        tpl_path = Path(__file__).with_name("score_audit_report_tpl.md")
        tpl = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else None
    except Exception:
        tpl = None
    if tpl is None:
        parts = [f"## {k}\n\n{v}\n" for k, v in R.items()]
        (OUT / "report_raw.md").write_text("\n".join(parts), encoding="utf-8")
        return
    rep = tpl
    for k, v in R.items():
        rep = rep.replace("{{" + k + "}}", str(v))
    (OUT / "report.md").write_text(rep, encoding="utf-8")


if __name__ == "__main__":
    main()
