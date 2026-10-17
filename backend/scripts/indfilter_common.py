"""İndikatör filtresi / hedef boyutu çalışması — ortak yardımcılar (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ).

İçerik
  * SAF yardımcılar (testli: tests/test_indfilter.py): kısmi Spearman (küme-dayanıklı t), AUC, ATR-tersil içi fark, eşleşmiş taban havuzu,
    teyit kuralı maskesi, pinball kaybı, blok ataması.
  * Olay kurucular: Hız Avcısı (HA) canlı-benzeri bölümler (work/rescan_90g_nogate.jsonl) ve push bildirimleri (work/confirm_elems/events.pkl).
  * `prep_population`: olay başına 1 dk yol penceresi (60 sn gecikmeli giriş) + oynaklık-eşleşmiş rastgele giriş tabanı → work/indfilter/prep_<pop>.npz.

Başarı tanımları: (A) hit = 60 dk içinde 1 dk yüksekler hedef (giriş-barı açılışına göre) seviyeyi görür; (B) net = exit_sim (60 sn gecikme,
%0,15 kayma, %0,1125/bacak ücret; TP = hedef, SL %3, zaman stopu 60 dk). Taban: aynı sembol + aynı blok + sinyalden ≥ 2 sa uzak + 5 dk ATR%'si ±%25
(en az 8 aday; yoksa en yakın 8) rastgele anlar; olay başına N_RND çekiliş, aynı TP/SL/zaman.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import exit_sim as X  # noqa: E402

OUT = ROOT / "work" / "indfilter"
TZ = timezone(timedelta(hours=3))
DAY_MS = 86_400_000
TZ_MS = 3 * 3_600_000
W = 60                       # pencere (dk) = zaman stopu
DELAY_S = 60
SLIP = 0.15
N_RND = 3
MIN_GAP_MS = 2 * 3_600_000
MIN_POOL = 8
ATR_TOL = 0.25
SL = 3.0


# ------------------------------------------------------------------------------------------------ zaman / blok
def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + DAY_MS - 1 if end else ms


def day_idx(ms) -> np.ndarray:
    return (np.asarray(ms, dtype=np.int64) + TZ_MS) // DAY_MS


def ha_blocks() -> list[tuple[int, int]]:
    return [(parse_day("2026-07-20"), parse_day("2026-08-18", end=True)),
            (parse_day("2026-08-19"), parse_day("2026-09-17", end=True)),
            (parse_day("2026-09-18"), parse_day("2026-10-16", end=True))]


def notif_blocks() -> list[tuple[int, int]]:
    """Seçim: 17.09 → 09.10; değerlendirme: 10.10 → 17.10 (önceki çalışmayla aynı bölme)."""
    return [(parse_day("2026-09-17"), parse_day("2026-10-09", end=True)),
            (parse_day("2026-10-10"), parse_day("2026-10-17", end=True))]


def block_of(t_ms, blocks: list[tuple[int, int]]) -> np.ndarray:
    """Her zaman için blok indeksi; hiçbirine girmeyen → -1."""
    t = np.asarray(t_ms, dtype=np.int64)
    out = np.full(t.shape, -1, dtype=np.int8)
    for i, (a, b) in enumerate(blocks):
        out[(t >= a) & (t <= b)] = i
    return out


# ------------------------------------------------------------------------------------------------ saf istatistik
def rank_avg(x) -> np.ndarray:
    from scipy.stats import rankdata
    return rankdata(np.asarray(x, dtype=float), method="average")


def _resid(y: np.ndarray, Z: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
    return y - Z @ beta


def partial_spearman(x, y, ctrl, cluster) -> dict:
    """x ile y arasında `ctrl` (ATR vb.; tek sütun ya da (n,k)) sabitlenerek kısmi Spearman. Sıralar alınır, ctrl sıralarının
    1. ve 2. derece terimleriyle doğrusal olarak arındırılır; eğim için küme-dayanıklı (gün) SE.
    Dönüş: r (kısmi korelasyon), t (küme-dayanıklı), n. ctrl=None → ham Spearman (yine küme-dayanıklı t)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    cl = np.asarray(cluster)
    m = np.isfinite(x) & np.isfinite(y)
    C = None
    if ctrl is not None:
        C = np.asarray(ctrl, dtype=float)
        C = C.reshape(len(x), -1)
        m &= np.isfinite(C).all(axis=1)
    n = int(m.sum())
    if n < 30 or np.ptp(x[m]) == 0 or np.ptp(y[m]) == 0:
        return {"r": float("nan"), "t": float("nan"), "n": n, "g": 0}
    rx, ry = rank_avg(x[m]), rank_avg(y[m])
    cols = [np.ones(n)]
    if C is not None:
        for j in range(C.shape[1]):
            rc = rank_avg(C[m, j])
            rc = (rc - rc.mean()) / (rc.std() or 1.0)
            cols += [rc, rc ** 2]
    Z = np.column_stack(cols)
    ex, ey = _resid(rx, Z), _resid(ry, Z)
    sx, sy = ex.std(), ey.std()
    if sx == 0 or sy == 0:
        return {"r": float("nan"), "t": float("nan"), "n": n, "g": 0}
    r = float((ex * ey).mean() / (sx * sy))
    # eğim ve küme-dayanıklı SE (ex üzerine ey)
    b = (ex * ey).sum() / (ex ** 2).sum()
    e = ey - b * ex
    _, inv = np.unique(cl[m], return_inverse=True)
    s = np.bincount(inv, weights=ex * e)
    se = float(np.sqrt((s ** 2).sum()) / (ex ** 2).sum())
    return {"r": r, "t": float(b / se) if se > 0 else float("nan"), "n": n, "g": int(inv.max() + 1)}


def support_ok(x, day, min_obs: int = 30, min_days: int = 8) -> bool:
    """Seyrek/sabit özellik tuzağı: modal değerden FARKLI gözlem en az `min_obs` ve en az `min_days` farklı günde olmalı
    (aksi halde küme-dayanıklı t anlamsız büyür)."""
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    if m.sum() < 100:
        return False
    vals, cnt = np.unique(x[m], return_counts=True)
    mode = vals[np.argmax(cnt)]
    non = m & (x != mode)
    return bool(non.sum() >= min_obs and len(np.unique(np.asarray(day)[non])) >= min_days)


def t_pvalue(t: float, g: int) -> float:
    """İki yönlü p, Student t (df = küme sayısı − 1): az sayıda gün kümesinde normal yaklaşımdan muhafazakâr."""
    from scipy.stats import t as tdist
    if not np.isfinite(t) or g < 2:
        return float("nan")
    return float(2.0 * tdist.sf(abs(t), df=g - 1))


def auc_score(score, label) -> float:
    """P(score_pozitif > score_negatif) (Mann-Whitney); bağlar yarım. Sınıflardan biri boşsa NaN."""
    s = np.asarray(score, dtype=float)
    y = np.asarray(label, dtype=bool)
    m = np.isfinite(s)
    s, y = s[m], y[m]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    rk = rank_avg(s)
    return float((rk[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def terciles(x, edges=None) -> tuple[np.ndarray, tuple[float, float]]:
    """Tersil kovası 0/1/2 (NaN → -1) ve kenarlar. `edges` verilirse onlar kullanılır (başka dönemden dondurulmuş)."""
    x = np.asarray(x, dtype=float)
    if edges is None:
        v = x[np.isfinite(x)]
        edges = (float(np.quantile(v, 1 / 3)), float(np.quantile(v, 2 / 3))) if len(v) else (np.nan, np.nan)
    b = np.where(np.isfinite(x), (x > edges[0]).astype(int) + (x > edges[1]).astype(int), -1)
    return b, edges


def strat_diff(f, y, strat, cluster, hi_q: float = 0.5) -> dict:
    """Tabaka (örn. ATR tersili) İÇİNDE özelliğin üst yarısı − alt yarısı ortalama y farkı; tabakalar n ile ağırlıklı.
    Dönüş: diff, se (küme-dayanıklı, gün kümeleri), t, n; ayrıca tabaka başına farklar `per`."""
    f = np.asarray(f, dtype=float)
    y = np.asarray(y, dtype=float)
    st = np.asarray(strat)
    cl = np.asarray(cluster)
    m = np.isfinite(f) & np.isfinite(y) & (st >= 0)
    per = {}
    contrib = np.zeros(len(f))
    wsum = 0.0
    tot = 0.0
    for s in np.unique(st[m]):
        ms = m & (st == s)
        thr = np.quantile(f[ms], hi_q)
        hi, lo = ms & (f > thr), ms & (f <= thr)
        if hi.sum() < 5 or lo.sum() < 5:
            continue
        d = y[hi].mean() - y[lo].mean()
        per[int(s)] = float(d)
        w = float(ms.sum())
        wsum += w
        tot += w * d
        # etki fonksiyonu: hi'de +(y-mean_hi)/n_hi, lo'da -(y-mean_lo)/n_lo (ağırlıklı)
        contrib[hi] += w * (y[hi] - y[hi].mean()) / hi.sum()
        contrib[lo] -= w * (y[lo] - y[lo].mean()) / lo.sum()
    if wsum == 0:
        return {"diff": float("nan"), "se": float("nan"), "t": float("nan"), "n": int(m.sum()), "per": per}
    diff = tot / wsum
    contrib /= wsum
    _, inv = np.unique(cl[m], return_inverse=True)
    sums = np.bincount(inv, weights=contrib[m])
    se = float(np.sqrt((sums ** 2).sum()))
    return {"diff": float(diff), "se": se, "t": float(diff / se) if se > 0 else float("nan"), "n": int(m.sum()), "per": per}


def pinball(y, pred, q: float) -> float:
    """Ortalama pinball (kuantil) kaybı."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(pred, dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    d = y[m] - p[m]
    return float(np.mean(np.maximum(q * d, (q - 1.0) * d))) if m.any() else float("nan")


def confirm_rule_mask(srcs, modes) -> np.ndarray:
    """CANLI teyit kuralı (2026-10-17): ≥ 2 FARKLI kaynak ∧ 'velocity' kaynaklar arasında ∧ mod ≠ 'unified'."""
    return np.array([len(set(s)) >= 2 and ("velocity" in s) and (m != "unified") for s, m in zip(srcs, modes)], dtype=bool)


def match_pool(atr_cand: np.ndarray, atr_ev: float, tol: float = ATR_TOL, min_pool: int = MIN_POOL) -> np.ndarray:
    """Aday ATR dizisinden olay ATR'sine ±tol içinde olanların indeksleri; < min_pool ise en yakın min_pool aday (log oranı)."""
    a = np.asarray(atr_cand, dtype=float)
    ok = np.flatnonzero(np.isfinite(a) & (a > 0))
    if len(ok) == 0 or not np.isfinite(atr_ev) or atr_ev <= 0:
        return np.zeros(0, dtype=int)
    d = np.abs(np.log(a[ok] / atr_ev))
    inside = ok[np.abs(a[ok] / atr_ev - 1.0) <= tol]
    if len(inside) >= min_pool:
        return inside
    return ok[np.argsort(d, kind="stable")[:min_pool]]


def excess_by_group(net, base, mask, cluster) -> dict:
    """Seçilen olaylar için (net − taban) ortalaması + küme SE; taban NaN olan olaylar atılır."""
    from app.rescan.confirm_elems import paired_diff_stats
    return paired_diff_stats(np.asarray(net)[mask], np.asarray(base)[mask], np.asarray(cluster)[mask])


# ------------------------------------------------------------------------------------------------ mum yükleme
SQL_SERIES = ("SELECT open_time, open, high, low, close, volume, quote_volume, taker_buy_base_volume, taker_buy_quote_volume "
              "FROM historical_candles WHERE symbol=%s AND timeframe=%s ORDER BY open_time")
COLS = ("ot", "o", "h", "l", "c", "v", "qv", "tbv", "tqv")


def get_conn():
    import psycopg
    url = os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    return psycopg.connect(url, connect_timeout=10)


def load_series(conn, sym: str, tf: str) -> dict | None:
    rows = conn.execute(SQL_SERIES, (sym, tf)).fetchall()
    if not rows:
        return None
    a = np.array(rows, dtype=float)          # None -> nan
    d = {k: a[:, i] for i, k in enumerate(COLS)}
    d["ot"] = np.round(d["ot"]).astype(np.int64)
    return d


# ------------------------------------------------------------------------------------------------ olay kurucular
def _f(v) -> float:
    try:
        return float(v) if v is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


HA_NUM = ("rsi", "mfi", "volume_ratio", "ret3_pct", "velocity_score", "rank", "atr_pct", "change_24h", "m1_atr_prev", "m3_atr_prev")


def load_ha_rows(path: str, lo: int, hi: int) -> list[dict]:
    """JSONL'i akıtarak okur, yalnız gerekli alanları tutar (bellek). `passes` olmayanlar atılır."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not r.get("passes"):
                continue
            t = int(r.get("tick_ms") or float(r["created_at"]) * 1000)
            if t < lo or t > hi:
                continue
            rad = r.get("radar") or {}
            s = {"symbol": r["symbol"], "tick_ms": t, "horizon_minutes": r.get("horizon_minutes"), "rank": r.get("rank"),
                 "exhausted": r.get("exhausted"), "mfi": r.get("mfi"), "rsi": r.get("rsi"), "mode": r.get("mode") or "",
                 "price": r.get("price"), "target_pct": r.get("target_pct"), "volume_ratio": r.get("volume_ratio"),
                 "ret3_pct": r.get("ret3_pct"), "velocity_score": r.get("velocity_score"), "atr_pct": r.get("atr_pct"),
                 "change_24h": r.get("change_24h"), "m1_atr_prev": r.get("m1_atr_prev"), "m3_atr_prev": r.get("m3_atr_prev"),
                 "m5_ok": 1.0 if r.get("m5_pattern_ok") else 0.0, "leading_ok": 1.0 if r.get("leading_ok") else 0.0,
                 "taker": rad.get("taker_buy_ratio"), "chop10": rad.get("choppiness_10"), "rangepos60": rad.get("range_pos_60"),
                 "late_phase": 1.0 if rad.get("late_phase") else 0.0}
            rows.append(s)
    return rows


def ha_events(path: str, lo: int, hi: int) -> tuple[dict, dict[str, list[int]]]:
    """Canlı-benzeri HA bölümleri: rank ≤ 10, aşırı alımda değil, aynı sembolde 60 dk içindeki tekrarlar tek bölüm.
    Dönüş: olay dict-of-arrays + sembol başına TÜM taban tick'leri (rastgele giriş dışlaması için)."""
    from scripts.radar_shield_rescan_analysis import dedupe_horizon, is_overbought, mark_episodes
    rows = dedupe_horizon(load_ha_rows(path, lo, hi))
    base = [r for r in rows if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= 10]
    mark_episodes(base)
    ticks: dict[str, list[int]] = {}
    ev = [r for r in base if r.get("ep")]
    for r in base:
        ticks.setdefault(r["symbol"], []).append(int(r["tick_ms"]))
    out = {"sym": np.array([r["symbol"] for r in ev]), "t_ms": np.array([r["tick_ms"] for r in ev], dtype=np.int64),
           "price": np.array([_f(r["price"]) for r in ev]), "tp": np.array([_f(r["target_pct"]) for r in ev]),
           "hz": np.array([int(r.get("horizon_minutes") or 0) for r in ev]), "mode": np.array([r["mode"] for r in ev])}
    for k in HA_NUM:
        out["x_" + k] = np.array([_f(r.get(k)) for r in ev])
    for k in ("m5_ok", "leading_ok", "taker", "chop10", "rangepos60", "late_phase"):
        out["x_" + k] = np.array([_f(r.get(k)) for r in ev])
    return out, ticks


def notif_events(pkl: str) -> tuple[dict, dict[str, list[int]]]:
    """events.pkl → olay dict (push bildirimleri; t sn → ms)."""
    import pickle
    E = pickle.load(open(pkl, "rb"))
    ok = np.asarray(E["valid"], dtype=bool) & np.isfinite(E["tgt"]) & (np.asarray(E["tgt"]) > 0)
    ix = np.flatnonzero(ok)
    srcs = [tuple(E["srcs"][i]) for i in ix]
    out = {"sym": np.asarray(E["sym"])[ix], "t_ms": np.round(np.asarray(E["t"])[ix] * 1000).astype(np.int64),
           "price": np.full(len(ix), np.nan), "tp": np.asarray(E["tgt"], dtype=float)[ix], "hz": np.asarray(E["hz"])[ix],
           "mode": np.asarray(E["mode"])[ix], "srcs": srcs, "confirm": confirm_rule_mask(srcs, np.asarray(E["mode"])[ix])}
    for k in ("score", "four", "rsi1", "mfi1", "rsi5", "mfi5", "taker3", "dist24", "pump30", "atr", "shield"):
        out["x_" + k] = np.asarray(E[k], dtype=float)[ix]
    for k in ("net1", "net2", "hit_h", "hit60", "b_net2", "bn_net2"):
        out["old_" + k] = np.asarray(E[k], dtype=float)[ix]
    ticks: dict[str, list[int]] = {}
    for s, t in zip(out["sym"], out["t_ms"]):
        ticks.setdefault(str(s), []).append(int(t))
    return out, ticks


# ------------------------------------------------------------------------------------------------ taban + pencere hazırlığı
def candidate_grid(ot1: np.ndarray, lo: int, hi: int, ticks: np.ndarray) -> np.ndarray:
    """5 dk ızgarasında rastgele giriş adayı zamanları: sinyallerden ≥ 2 sa uzak, 1 dk verisi var, pencere veri içinde."""
    g = np.arange(-(-lo // 300_000) * 300_000, hi + 1, 300_000, dtype=np.int64)
    g = g[g + (W + 5) * 60_000 <= ot1[-1]]
    if len(g) == 0:
        return g
    ok = np.ones(len(g), dtype=bool)
    if len(ticks):
        tk = np.sort(np.asarray(ticks, dtype=np.int64))
        k = np.searchsorted(tk, g)
        d1 = np.abs(g - tk[np.minimum(k, len(tk) - 1)])
        d0 = np.abs(g - tk[np.maximum(k - 1, 0)])
        ok &= np.minimum(d0, d1) >= MIN_GAP_MS
    j = np.searchsorted(ot1, g, side="left")
    jc = np.minimum(j, len(ot1) - 1)
    ok &= (j < len(ot1)) & ((ot1[jc] - g) <= 5 * 60_000)
    return g[ok]


def prep_population(name: str, ev: dict, ticks: dict[str, list[int]], blocks: list[tuple[int, int]], seed: int = 11, log=print) -> Path:
    """Olay başına pencere + taban pencereleri. Çıktı: OUT/prep_<name>.npz. Olay sırası korunur (ev_id = ev içindeki sıra)."""
    OUT.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    n_ev = len(ev["t_ms"])
    blk_ev = block_of(ev["t_ms"], blocks)
    syms = sorted(set(ev["sym"].tolist()))
    rng_master = np.random.default_rng(seed)
    lo_all = min(b[0] for b in blocks)
    hi_all = max(b[1] for b in blocks)
    M = {k: [] for k in ("kind", "ev", "t", "sym", "atr", "block", "day")}
    WIN = {k: [] for k in ("O", "H", "L", "C")}
    ev_ok = np.zeros(n_ev, dtype=bool)
    ev_atr = np.full(n_ev, np.nan)
    t0 = time.time()
    for si, s in enumerate(syms):
        a1 = load_series(conn, s, "1m")
        a5 = load_series(conn, s, "5m")
        if a1 is None or a5 is None or len(a1["ot"]) < 400 or len(a5["ot"]) < 30:
            continue
        ot1 = a1["ot"]
        idx_ev = np.flatnonzero((ev["sym"] == s) & (blk_ev >= 0))
        if len(idx_ev) == 0:
            continue
        rng = np.random.default_rng(rng_master.integers(1 << 31))
        t_ev = ev["t_ms"][idx_ev]
        atr_ev = X.atr_pct_at(a5["ot"], a5["h"], a5["l"], a5["c"], t_ev)
        # --- taban adayları (blok başına)
        rows_t, rows_kind, rows_ev, rows_atr, rows_blk = [t_ev], [np.zeros(len(idx_ev), dtype=np.int8)], [idx_ev], [atr_ev], [blk_ev[idx_ev]]
        tk = np.array(ticks.get(s, []), dtype=np.int64)
        for b, (blo, bhi) in enumerate(blocks):
            sel = np.flatnonzero(blk_ev[idx_ev] == b)
            if len(sel) == 0:
                continue
            g = candidate_grid(ot1, blo, bhi, tk)
            if len(g) == 0:
                continue
            atr_g = X.atr_pct_at(a5["ot"], a5["h"], a5["l"], a5["c"], g)
            for k in sel:
                pool = match_pool(atr_g, atr_ev[k])
                if len(pool) == 0:
                    continue
                pick = rng.choice(pool, size=N_RND, replace=len(pool) < N_RND)
                rows_t.append(g[pick]); rows_kind.append(np.ones(len(pick), dtype=np.int8))
                rows_ev.append(np.full(len(pick), idx_ev[k])); rows_atr.append(atr_g[pick]); rows_blk.append(np.full(len(pick), b, dtype=np.int8))
        t_all = np.concatenate(rows_t); kind = np.concatenate(rows_kind); evi = np.concatenate(rows_ev)
        atr_all = np.concatenate(rows_atr); blk_all = np.concatenate(rows_blk)
        idx, ok = X.entry_index(ot1, t_all, DELAY_S)
        O, H, L, C, ref, cov = X.gather_windows(ot1, a1["o"], a1["h"], a1["l"], a1["c"], idx, W)
        ok &= cov
        # olay (kind 0) geçerliyse yaz; taban satırı yalnız eşi geçerliyse anlamlı ama bağımsız tutulur
        e0 = kind == 0
        ev_ok[evi[e0 & ok]] = True
        ev_atr[evi[e0]] = atr_all[e0]
        M["kind"].append(kind[ok]); M["ev"].append(evi[ok]); M["t"].append(t_all[ok]); M["sym"].append(np.array([s] * int(ok.sum())))
        M["atr"].append(atr_all[ok]); M["block"].append(blk_all[ok]); M["day"].append(day_idx(t_all[ok]).astype(np.int32))
        for k_, A in zip(("O", "H", "L", "C"), (O, H, L, C)):
            WIN[k_].append(A[ok])
        if (si + 1) % 25 == 0:
            log("[prep %s] %d/%d sembol (%.0f sn)" % (name, si + 1, len(syms), time.time() - t0))
    conn.close()
    cat = {k: np.concatenate(v) for k, v in M.items()}
    win = {k: np.concatenate(v) for k, v in WIN.items()}
    path = OUT / ("prep_%s.npz" % name)
    np.savez_compressed(path, **cat, **win, ev_ok=ev_ok, ev_atr=ev_atr, ev_block=blk_ev)
    log("[prep %s] bitti: olay %d (pencereli %d), taban satırı %d (%.0f sn)" % (name, n_ev, int(ev_ok.sum()), int((cat["kind"] == 1).sum()), time.time() - t0))
    return path


# ------------------------------------------------------------------------------------------------ net hesabı
def net_for(win: dict, tp_pct: np.ndarray, sl: float = SL, time_min: int = 60, slip: float = SLIP) -> dict:
    """win: O,H,L,C (n, W) float32; tp_pct (n,) satır başına hedef (%). exit_sim ile net/MFE/MAE/neden."""
    spec = X.ExitSpec("fixed", "fixed", sl=sl, time_min=time_min, tp_cand=True)
    return X.simulate(win["O"], win["H"], win["L"], win["C"], spec, slip_pct=slip, tp_cand_pct=np.asarray(tp_pct, dtype=float))


def mfe_mae(win: dict, n_bars: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """Giriş-barı açılışına göre 60 dk MFE/MAE (%), kayma yok (ham yol)."""
    mfe = (win["H"][:, :n_bars].max(axis=1).astype(float) - 1.0) * 100.0
    mae = (win["L"][:, :n_bars].min(axis=1).astype(float) - 1.0) * 100.0
    return mfe, mae


def load_prep(name: str) -> dict:
    z = np.load(OUT / ("prep_%s.npz" % name), allow_pickle=False)
    return {k: z[k] for k in z.files}


def paired_baseline(net_rows: np.ndarray, kind: np.ndarray, ev_id: np.ndarray, n_ev: int) -> tuple[np.ndarray, np.ndarray]:
    """Taban satırlarının olay başına ortalaması (NaN: taban yok) ve çekiliş sayısı."""
    b = (kind == 1) & np.isfinite(net_rows)
    s = np.bincount(ev_id[b], weights=net_rows[b], minlength=n_ev)
    c = np.bincount(ev_id[b], minlength=n_ev)
    return np.where(c > 0, s / np.maximum(c, 1), np.nan), c


# ------------------------------------------------------------------------------------------------ nüfus (olay + taban) nesnesi
class Pop:
    """Bir nüfusun olayları ve tabanı: `sim(tp_ev)` herhangi bir hedef vektörüyle (olay başına %) net / hit / taban üretir.

    Öznitelikler (olay sırasıyla, n_ev): ev (olay sözlüğü), ok (pencere var), atr, block, day, mfe, mae (60 dk, %), sym, t_ms.
    """

    def __init__(self, name: str):
        import pickle
        self.name = name
        self.ev = pickle.load(open(OUT / ("events_%s.pkl" % name), "rb"))
        self.P = load_prep(name)
        self.n = len(self.ev["t_ms"])
        P = self.P
        self.ok = P["ev_ok"].astype(bool)
        self.atr = P["ev_atr"]
        self.block = P["ev_block"].astype(int)
        self.t_ms = self.ev["t_ms"]
        self.sym = self.ev["sym"]
        self.day = day_idx(self.t_ms)
        self.kind, self.evid = P["kind"], P["ev"]
        self.win = {k: P[k] for k in ("O", "H", "L", "C")}
        mfe_r, mae_r = mfe_mae(self.win)
        self.mfe_r, self.mae_r = mfe_r, mae_r
        r0 = np.flatnonzero(self.kind == 0)
        self.row_of = np.full(self.n, -1, dtype=np.int64)
        self.row_of[self.evid[r0]] = r0
        self.mfe = np.full(self.n, np.nan); self.mae = np.full(self.n, np.nan)
        self.mfe[self.evid[r0]] = mfe_r[r0]; self.mae[self.evid[r0]] = mae_r[r0]
        self.tp = np.asarray(self.ev["tp"], dtype=float)
        self.valid = self.ok & np.isfinite(self.tp) & (self.tp > 0) & np.isfinite(self.atr) & (self.block >= 0)

    def sim(self, tp_ev: np.ndarray, sl: float = SL, time_min: int = 60, ev_mask: np.ndarray | None = None) -> dict:
        """tp_ev: (n,) olay başına hedef %. NaN/≤0 hedef → o olay ve tabanı NaN. Dönüş (hepsi (n,)): net, hit, b_net (eşleşmiş taban ort.),
        b_hit (taban hit oranı), b_cnt; ayrıca reason (olay)."""
        tp_ev = np.asarray(tp_ev, dtype=float)
        tp_row = tp_ev[self.evid]
        good = np.isfinite(tp_row) & (tp_row > 0)
        if ev_mask is not None:
            good &= np.asarray(ev_mask, dtype=bool)[self.evid]          # yalnız bu olaylar (ve tabanları) simüle edilir
        net_row = np.full(len(self.kind), np.nan)
        reason_row = np.full(len(self.kind), -1, dtype=np.int8)
        if good.any():
            win = {k: v[good] for k, v in self.win.items()}
            r = net_for(win, tp_row[good], sl=sl, time_min=time_min)
            net_row[good] = r["net"]
            reason_row[good] = r["reason"]
        hit_row = np.where(good, (self.mfe_r >= tp_row).astype(float), np.nan)
        e0 = self.kind == 0
        net = np.full(self.n, np.nan); hit = np.full(self.n, np.nan); reason = np.full(self.n, -1, dtype=np.int8)
        net[self.evid[e0]] = net_row[e0]; hit[self.evid[e0]] = hit_row[e0]; reason[self.evid[e0]] = reason_row[e0]
        b_net, b_cnt = paired_baseline(net_row, self.kind, self.evid, self.n)
        b_hit, _ = paired_baseline(hit_row, self.kind, self.evid, self.n)
        return {"net": net, "hit": hit, "b_net": b_net, "b_hit": b_hit, "b_cnt": b_cnt, "reason": reason}
