"""Bildirim politikası çalışması: push-only + >=2 teyit + dinamik hedef + net>=%2 filtresi (2026-10-17, çevrimdışı araştırma).

Soru: "bildirim hedefine ulaştı" ölçütüyle başarı; kullanıcı önerisi (1) panel bildirimlerini kaldır, (2) yalnız >=2 farklı
kaynak teyidiyle push, (3) hedefi sembolün sinyal anındaki durumundan DİNAMİK belirle (tüm maliyetler dahil), (4) net hedef
%2'nin altındaysa gönderme. Öneri kârlılığı artırır mı, yoksa yalnız bildirim sayısını mı azaltır?

Veri: `monitoring_notifications` (DB), üretim Raporlar sayfasından kopyalanan 83 satır (`work/prod_notifications_1015_1017.tsv`),
`velocity_candidates` (Hız Avcısı adayları), `unified_candidate_outcomes` (birleşik tarama journal'ı), `historical_candles` 1m/5m.
Simülatör: `app/rescan/exit_sim.py` (gerçekçi doluş: giriş gecikmesi + kayma, stop-önce, ücret). Dinamik hedef:
`app/rescan/dyn_target.py` (yalnız sinyal anında bilinen veri). Rastgele giriş tabanı: aynı sembol, aynı İstanbul saati, başka
günler, tüm olaylardan >= 2 sa uzak; aynı hedef kuralı ve aynı çıkışlarla.

Kullanım (backend/): DATABASE_URL=... python scripts/policy7d_study.py --out work/policy7d/report.md
Çıktı salt rapordur; canlı koda bağlanmaz.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.rescan import dyn_target as D  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402

TZ = timezone(timedelta(hours=3))
DAY_S = 86_400
W = 60                                   # simülasyon / isabet penceresi (dk)
SLIP = 0.15                              # birincil kayma (% / bacak)
DELAY_S = 60.0                           # birincil giriş gecikmesi
COST = D.round_trip_cost_pct(SLIP, SLIP)  # 0,525
K_LIST = (1.0, 1.5, 2.0)
SRC_TR = {"Hız": "velocity", "Sıçrama": "jump", "Erken uyarı": "early", "Yükseliş eğilimi": "rising"}
SRC_ORDER = ("velocity", "jump", "early", "rising")
T7_START = datetime(2026, 10, 10, 0, 0, tzinfo=TZ).timestamp()
PROD_START = datetime(2026, 10, 15, 22, 30, tzinfo=TZ).timestamp()
P_START = datetime(2026, 9, 17, 15, 0, tzinfo=TZ).timestamp()          # notifications tablosu başlangıcı
HA_START = datetime(2026, 9, 21, 0, 0, tzinfo=TZ).timestamp()          # velocity_candidates yoğun kayıt başlangıcı
JR_START = datetime(2026, 10, 14, 5, 30, tzinfo=TZ).timestamp()
JR_END = datetime(2026, 10, 16, 1, 55, tzinfo=TZ).timestamp()
WEEKS = (("H0 10.10–17.10", datetime(2026, 10, 10, tzinfo=TZ).timestamp(), 9e18),
         ("H-1 03.10–09.10", datetime(2026, 10, 3, tzinfo=TZ).timestamp(), datetime(2026, 10, 10, tzinfo=TZ).timestamp()),
         ("H-2 26.09–02.10", datetime(2026, 9, 26, tzinfo=TZ).timestamp(), datetime(2026, 10, 3, tzinfo=TZ).timestamp()),
         ("H-3 17.09–25.09", datetime(2026, 9, 17, tzinfo=TZ).timestamp(), datetime(2026, 9, 26, tzinfo=TZ).timestamp()))


# ------------------------------------------------------------------------------------------------ istatistik
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def fmt_hit(k: int, n: int) -> str:
    if n == 0:
        return "–"
    lo, hi = wilson(k, n)
    return "%.1f%% [%.0f–%.0f] (%d/%d)" % (100.0 * k / n, lo, hi, k, n)


def mean_se(x: np.ndarray, day: np.ndarray) -> tuple[float, float, int]:
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    n = int(m.sum())
    if n == 0:
        return float("nan"), float("nan"), 0
    xx = x[m]
    se = X.cluster_se(xx, day[m]) if n > 1 else float("nan")
    return float(xx.mean()), se, n


def fmt_net(mean: float, se: float, n: int) -> str:
    if n == 0 or not np.isfinite(mean):
        return "–"
    if not np.isfinite(se):
        return "%+.2f" % mean
    return "%+.2f ±%.2f" % (mean, 1.96 * se)


def diff_str(a: tuple, b: tuple) -> str:
    (ma, sa, na), (mb, sb, nb) = a, b
    if not na or not nb or not np.isfinite(sa) or not np.isfinite(sb):
        return "–"
    d = ma - mb
    se = math.sqrt(sa * sa + sb * sb)
    return "%+.2f [%+.2f; %+.2f]" % (d, d - 1.96 * se, d + 1.96 * se)


# ------------------------------------------------------------------------------------------------ olay yükleme
def canon_sources(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return ()
    return tuple(s for s in SRC_ORDER if s in set(raw))


def n_family(srcs: tuple[str, ...]) -> int:
    """Bağımsız aile sayısı: velocity | (jump+early tek dedektör çifti) | rising."""
    return len({("jump_early" if x in ("jump", "early") else x) for x in srcs})


def load_db_notifications(conn, t0: float, t1: float) -> list[dict]:
    cur = conn.execute(
        "SELECT id, symbol, price, target_pct, horizon_minutes, mode, score, sources, sent_via_push, detected_at, outcome_status, "
        "title, mfe_pct FROM monitoring_notifications WHERE detected_at >= %s AND detected_at < %s ORDER BY detected_at", (t0, t1))
    out = []
    for (i, sym, price, tgt, hz, mode, score, srcs, push, ts, st, title, mfe) in cur.fetchall():
        out.append({"src": "db", "id": "db%d" % i, "sym": sym, "t": float(ts), "price": price, "tgt": tgt, "hz": int(hz or 0),
                    "mode": mode or "", "srcs": canon_sources(srcs), "push": bool(push),
                    "app_hit": (1 if st == "HEDEFE_ULTI" else 0) if st else -1,
                    "four": int("4'LÜ TEYİT" in (title or "")), "app_mfe": mfe})
    return out


def load_prod_tsv(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        next(fh)
        for ln, line in enumerate(fh):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 9:
                continue
            tl, sym, ch, srcs, price, tgt, hz, mfe, res = parts[:9]
            ts = datetime.strptime(tl, "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp() + 30.0  # dakika altı bilinmiyor → +30 sn
            s = tuple(x for x in SRC_ORDER if x in {SRC_TR.get(p.strip()) for p in srcs.split(",")})
            out.append({"src": "prod", "id": "pr%d" % ln, "sym": sym, "t": ts, "price": float(price), "tgt": float(tgt),
                        "hz": int(hz), "mode": "", "srcs": s, "push": ch.strip() == "Push",
                        "app_hit": 1 if res.strip() == "Hedefe ulaştı" else (-1 if res.strip() == "Bekliyor" else 0),
                        "four": 0, "app_mfe": float(mfe) if mfe.strip() else None})
    return out


def load_ha_candidates(conn, t0: float, t1: float, cooldown_s: float = 3600.0) -> list[dict]:
    cur = conn.execute(
        "SELECT candidate_id, created_at, symbol, price, target_pct FROM velocity_candidates "
        "WHERE passes AND rank <= 10 AND created_at >= %s AND created_at < %s ORDER BY created_at", (t0, t1))
    last: dict[str, float] = {}
    out = []
    for cid, ts, sym, price, tgt in cur.fetchall():
        if sym in last and ts - last[sym] < cooldown_s:
            continue
        last[sym] = ts
        m = re.match(r"vel-(\d+)dk", cid or "")
        hz = int(m.group(1)) if m else 5
        out.append({"src": "ha", "id": "ha%s" % cid, "sym": sym, "t": float(ts), "price": price, "tgt": tgt, "hz": hz,
                    "mode": "", "srcs": ("velocity",), "push": True, "app_hit": -1, "four": 0, "app_mfe": None})
    return out


def load_journal(conn, t0: float, t1: float) -> list[dict]:
    cur = conn.execute(
        "SELECT symbol, horizon_minutes, sources, scan_score, entry_price, ceiling_pct, target_pct, detected_at, hit, blocked_by "
        "FROM unified_candidate_outcomes WHERE sources <> '[]' AND detected_at >= %s AND detected_at < %s "
        "AND entry_price > 0 ORDER BY detected_at", (t0, t1))
    best: dict[tuple, dict] = {}
    for sym, hz, srcs, score, price, ceil, tgt, ts, hit, blocked in cur.fetchall():
        tg = ceil or tgt
        if not tg or not sym.endswith("TRY"):
            continue
        sources = tuple(x for x in json.loads(srcs))
        key = (sym, int(ts // 300))
        row = {"src": "jr", "id": "jr%s%d" % (sym, int(ts)), "sym": sym, "t": float(ts), "price": price, "tgt": float(tg),
               "hz": int(hz) if hz else 5, "mode": "", "srcs": sources, "push": True, "app_hit": -1, "four": 0, "app_mfe": None,
               "score": score, "blocked": blocked or ""}
        if key not in best or len(sources) > len(best[key]["srcs"]):
            best[key] = row
    return sorted(best.values(), key=lambda r: r["t"])


# ------------------------------------------------------------------------------------------------ mum yükleme
class Candles:
    def __init__(self, conn, start_ms: int):
        self.conn = conn
        self.start_ms = start_ms

    def load(self, sym: str):
        one = self.conn.execute(
            "SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe='1m' AND open_time >= %s "
            "ORDER BY open_time", (sym, self.start_ms)).fetchall()
        five = self.conn.execute(
            "SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe='5m' AND open_time >= %s "
            "ORDER BY open_time", (sym, self.start_ms - 15 * D.DAY_MS)).fetchall()
        if not one or not five:
            return None
        a1 = np.array(one, dtype=float)
        a5 = np.array(five, dtype=float)
        return a1, a5


def process_symbol(a1: np.ndarray, a5: np.ndarray, t_ms: np.ndarray, hz: np.ndarray) -> dict:
    """Tek sembol için tüm satırların pencereleri, özellikleri ve dinamik hedefleri."""
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
    mfe_h = (cm[ar, np.clip(hz, 1, W) - 1].astype(float) - 1.0) * 100.0
    mfe60 = (cm[:, W - 1].astype(float) - 1.0) * 100.0
    atr = X.atr_pct_at(open5, h5, l5, c5, t_ms, 14)
    last1 = D.last_closed_index(open1, t_ms, D.BAR1)
    ix = last1[:, None] - np.arange(30, dtype=np.int64)[None, :]
    okx = (ix >= 0) & (open1[np.clip(ix, 0, len(open1) - 1)] >= (t_ms[:, None] - 30 * D.BAR1)) & (last1 >= 0)[:, None]
    ixc = np.clip(ix, 0, len(open1) - 1)
    hh = np.where(okx, h1[ixc], -np.inf).max(axis=1)
    ll = np.where(okx, l1[ixc], np.inf).min(axis=1)
    rng30 = np.where(okx.sum(axis=1) >= 25, (hh / ll - 1.0) * 100.0, np.nan)
    sc = D.SymbolCandles(open1=open1, h1=h1, open5=open5, h5=h5, l5=l5, c5=c5)
    emp = D.empirical_upside_pct(sc, t_ms, hz, 14, 0.6)             # ufuk eşlemeli (ch)
    emp60 = D.empirical_upside_pct(sc, t_ms, 60, 14, 0.6)           # 60 dk MFE q60 (c) — görev tanımı
    drift60 = (Cs[:, W - 1].astype(float) / Os[:, 0].astype(float) - 1.0) * 100.0
    mae60 = (Ls.astype(float).min(axis=1) / Os[:, 0].astype(float) - 1.0) * 100.0
    px_ex = np.where(last1 >= 0, c1[np.clip(last1, 0, len(c1) - 1)], np.nan)
    out = {"valid": ok0 & ok6 & cov0 & covs & np.isfinite(atr), "ref0": ref0, "drift60": drift60, "mae60": mae60, "mfe_h": mfe_h, "mfe60": mfe60, "atr": atr,
           "ch": emp, "rng30": rng30, "Os": Os, "Hs": Hs, "Ls": Ls, "Cs": Cs}
    for k in K_LIST:
        r = D.compute_targets(sc, t_ms, px_ex, hz, atr, D.DynParams(k_atr=k), emp=emp60)
        out["a%g" % k] = r["a"]
        out["b%g" % k] = r["b"]
        out["room"] = r["room"]
    out["c"] = emp60
    return out


# ------------------------------------------------------------------------------------------------ taban (rastgele giriş)
def make_baseline(events: list[dict], all_times: dict[str, np.ndarray], t_lo: float, t_hi: float, k: int, seed: int,
                  windows: dict | None = None) -> list[dict]:
    """Her olay için k rastgele an: aynı sembol, aynı İstanbul saati dilimi, başka günler, o sembolün tüm olaylarından >= 2 sa uzak.
    `windows`: {olay_indeksi: (t_lo, t_hi)} ile olay başına özel aralık."""
    rng = np.random.default_rng(seed)
    out = []
    d0 = int((t_lo + 3 * 3600) // DAY_S)
    d1 = int((t_hi + 3 * 3600) // DAY_S)
    for pi, ev in enumerate(events):
        if windows is not None:
            t_lo, t_hi = windows[pi]
            d0 = int((t_lo + 3 * 3600) // DAY_S)
            d1 = int((t_hi + 3 * 3600) // DAY_S)
        tl = ev["t"] + 3 * 3600
        sec_of_day = tl % DAY_S
        hour_start = (sec_of_day // 3600) * 3600
        times = all_times.get(ev["sym"], np.array([]))
        got = 0
        tries = 0
        while got < k and tries < 60:
            tries += 1
            d = int(rng.integers(d0, d1 + 1))
            t = d * DAY_S + hour_start + float(rng.integers(0, 3600)) - 3 * 3600
            if t < t_lo or t > t_hi:
                continue
            if len(times) and np.min(np.abs(times - t)) < 7200:
                continue
            row = dict(ev)
            row.update({"t": t, "kind": 1, "parent": pi, "id": "b%d_%d" % (pi, got), "pool": got})
            out.append(row)
            got += 1
    return out


# ------------------------------------------------------------------------------------------------ tablo
class Table:
    """Gerçek olaylar (kind=0) ve taban satırları (kind=1) tek dizi kümesinde."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.n = len(rows)
        self.kind = np.array([r.get("kind", 0) for r in rows], dtype=np.int8)
        self.parent = np.array([r.get("parent", i) for i, r in enumerate(rows)], dtype=np.int64)
        self.t = np.array([r["t"] for r in rows], dtype=float)
        self.t_ms = np.round(self.t * 1000).astype(np.int64)
        self.day = ((self.t + 3 * 3600) // DAY_S).astype(np.int64)
        self.hz = np.array([r["hz"] for r in rows], dtype=np.int64)
        self.old_tgt = np.array([r["tgt"] if r["tgt"] else np.nan for r in rows], dtype=float)
        self.nsrc = np.array([len(r["srcs"]) for r in rows], dtype=np.int64)
        self.nfam = np.array([n_family(r["srcs"]) for r in rows], dtype=np.int64)
        self.nsrc4 = np.array([len([x for x in r["srcs"] if x in SRC_ORDER]) for r in rows], dtype=np.int64)
        self.push = np.array([r["push"] for r in rows], dtype=bool)
        self.four = np.array([r["four"] for r in rows], dtype=np.int64)
        self.app_hit = np.array([r["app_hit"] for r in rows], dtype=np.int64)
        self.src = np.array([r["src"] for r in rows])
        self.sym = np.array([r["sym"] for r in rows])
        self.srcs_key = np.array(["+".join(r["srcs"]) for r in rows])
        self.mode = np.array([r.get("mode", "") for r in rows])
        self.pool = np.array([r.get("pool", -1) for r in rows], dtype=np.int64)
        self.valid = np.zeros(self.n, dtype=bool)
        self.sel_rnd = np.zeros(self.n, dtype=bool)
        self.sel_vol = np.zeros(self.n, dtype=bool)
        self.need = np.ones(self.n, dtype=bool)
        self.feat: dict[str, np.ndarray] = {}
        self.win = {k: np.zeros((self.n, W), dtype=np.float32) for k in ("Os", "Hs", "Ls", "Cs")}

    def fill(self, cs: Candles, log=print) -> None:
        by_sym: dict[str, list[int]] = collections.defaultdict(list)
        for i, s in enumerate(self.sym):
            by_sym[s].append(i)
        names = ("ref0", "mfe_h", "mfe60", "atr", "ch", "room", "c", "rng30", "drift60", "mae60") + tuple("a%g" % k for k in K_LIST) + tuple("b%g" % k for k in K_LIST)
        for nm in names:
            self.feat[nm] = np.full(self.n, np.nan)
        t0 = time.time()
        for j, (sym, idxs) in enumerate(sorted(by_sym.items())):
            got = cs.load(sym)
            if got is None:
                continue
            a1, a5 = got
            ii = np.array(idxs)
            r = process_symbol(a1, a5, self.t_ms[ii], self.hz[ii])
            self.valid[ii] = r["valid"]
            for nm in names:
                self.feat[nm][ii] = r[nm]
            for k in ("Os", "Hs", "Ls", "Cs"):
                self.win[k][ii] = r[k]
            if (j + 1) % 25 == 0:
                log("[fill] %d/%d sembol, %.0f sn" % (j + 1, len(by_sym), time.time() - t0))

    def select_baselines(self, k: int, tol: float = 0.25, min_abs: float = 0.15) -> None:
        """sel_rnd: havuzdan ilk k geçerli satır; sel_vol: olayın 30 dk aralığına (±tol, en az min_abs puan) en yakın k geçerli satır."""
        by_parent: dict[int, list[int]] = collections.defaultdict(list)
        for i in np.where((self.kind == 1) & self.valid)[0]:
            by_parent[int(self.parent[i])].append(int(i))
        rng30 = self.feat["rng30"]
        for p, idxs in by_parent.items():
            idxs = sorted(idxs, key=lambda i: self.pool[i])
            self.sel_rnd[idxs[:k]] = True
            r0 = rng30[p]
            if not np.isfinite(r0):
                continue
            band = max(min_abs, tol * r0)
            cand = [i for i in idxs if np.isfinite(rng30[i]) and abs(rng30[i] - r0) <= band]
            cand.sort(key=lambda i: abs(rng30[i] - r0))
            self.sel_vol[cand[:max(3, k // 2)]] = True
        self.need = (self.kind == 0) | self.sel_rnd | self.sel_vol

    # -- simülasyon
    def sim(self, tgt: np.ndarray, sl_mode: str, t_mode: str, slip: float = SLIP, delay_ok: bool = True) -> np.ndarray:
        """TP = tgt (satır başına), SL = 3 % ya da 1,5×ATR (0,25'e yuvarlı, [0,75; 3]), zaman stopu = ufuk ya da 60 dk."""
        net = np.full(self.n, np.nan)
        ok = self.valid & np.isfinite(tgt) & self.need
        if sl_mode == "atr":
            sl = np.clip(np.round(1.5 * self.feat["atr"] * 4.0) / 4.0, 0.75, 3.0)
        else:
            sl = np.full(self.n, 3.0)
        tt = self.hz if t_mode == "hz" else np.full(self.n, 60)
        tt = np.clip(tt, 1, W)
        keys = sorted(set(zip(sl[ok].tolist(), tt[ok].tolist())))
        for (s, t) in keys:
            m = ok & (sl == s) & (tt == t)
            idx = np.where(m)[0]
            spec = X.ExitSpec("x", "fixed", sl=float(s), time_min=int(t), tp_cand=True)
            r = X.simulate(self.win["Os"][idx], self.win["Hs"][idx], self.win["Ls"][idx], self.win["Cs"][idx], spec,
                           slip_pct=slip, tp_cand_pct=tgt[idx])
            net[idx] = r["net"]
        return net


# ------------------------------------------------------------------------------------------------ hedef kuralları
def build_rules(T: Table) -> dict[str, np.ndarray]:
    f = T.feat
    rules = {"old": T.old_tgt.copy(), "c": f["c"].copy(), "ch": f["ch"].copy()}
    for k in K_LIST:
        rules["a%g" % k] = f["a%g" % k].copy()
        rules["b%g" % k] = f["b%g" % k].copy()
    for key, v in rules.items():
        v[~np.isfinite(v) | (v <= 0)] = np.nan
    return rules


EXITS = (("sl3_hz", "fix", "hz", "SL 3 %, süre=ufuk", SLIP), ("slatr_60", "atr", "60", "SL 1,5×ATR, süre=60 dk", SLIP),
         ("sl3_60", "fix", "60", "SL 3 %, süre=60 dk", SLIP), ("slatr_hz", "atr", "hz", "SL 1,5×ATR, süre=ufuk", SLIP),
         ("sl3_hz_opt", "fix", "hz", "SL 3 %, süre=ufuk, iyimser kayma %0,05", 0.05))


class Results:
    def __init__(self, T: Table, rules: dict[str, np.ndarray]):
        self.T = T
        self.rules = rules
        self.hit_h: dict[str, np.ndarray] = {}
        self.hit60: dict[str, np.ndarray] = {}
        self.net: dict[tuple[str, str], np.ndarray] = {}
        f = T.feat
        for rn, tg in rules.items():
            ok = T.valid & np.isfinite(tg)
            self.hit_h[rn] = np.where(ok, f["mfe_h"] >= tg, False)
            self.hit60[rn] = np.where(ok, f["mfe60"] >= tg, False)

    def ensure(self, rn: str, ex: str) -> np.ndarray:
        key = (rn, ex)
        if key not in self.net:
            spec = next(e for e in EXITS if e[0] == ex)
            self.net[key] = self.T.sim(self.rules[rn], spec[1], spec[2], slip=spec[4])
        return self.net[key]


def stage_stats(R: Results, mask: np.ndarray, rule: str, net_min: float | None, exits=("sl3_hz", "slatr_60", "sl3_hz_opt"),
                bkind: str = "rnd") -> dict:
    """mask: tüm satırlar (taban satırları ebeveynlerinin özelliklerini miras alır). Dönüş: gerçek + taban özetleri."""
    T = R.T
    tg = R.rules[rule]
    sel = mask & T.valid & np.isfinite(tg) & T.valid[T.parent]
    if net_min is not None:
        sel &= (tg - COST) >= net_min
    real = sel & (T.kind == 0)
    base = sel & (T.sel_rnd if bkind == "rnd" else T.sel_vol)
    out = {"n": int(real.sum()), "nb": int(base.sum()), "rule": rule}
    out["hit_h"] = (int(R.hit_h[rule][real].sum()), out["n"])
    out["hit60"] = (int(R.hit60[rule][real].sum()), out["n"])
    out["bhit_h"] = (int(R.hit_h[rule][base].sum()), out["nb"])
    out["bhit60"] = (int(R.hit60[rule][base].sum()), out["nb"])
    out["tgt_mean"] = float(np.nanmean(tg[real])) if out["n"] else float("nan")
    out["tgt_med"] = float(np.nanmedian(tg[real])) if out["n"] else float("nan")
    dr = T.feat["drift60"]
    out["drift"] = mean_se(dr[real], T.day[real])
    out["bdrift"] = mean_se(dr[base], T.day[base])
    for ex in exits:
        net = R.ensure(rule, ex)
        out["net_" + ex] = mean_se(net[real], T.day[real])
        out["bnet_" + ex] = mean_se(net[base], T.day[base])
        out["win_" + ex] = float(np.mean(net[real] > 0)) if out["n"] else float("nan")
    return out


def old_hit_share(R: Results, mask_stage: np.ndarray, rule: str, net_min: float | None, base_mask: np.ndarray) -> tuple[int, int]:
    """Eski sistemin 'hedefe ulaştı' (kendi hesabımız: eski hedef, ufuk içi MFE) sayılan bildirimlerinin kaçı bu aşamada kalıyor."""
    T = R.T
    old = R.hit_h["old"] & (T.kind == 0) & base_mask
    tg = R.rules[rule]
    sel = mask_stage & T.valid & np.isfinite(tg)
    if net_min is not None:
        sel &= (tg - COST) >= net_min
    return int((old & sel).sum()), int(old.sum())


# ------------------------------------------------------------------------------------------------ tablo kurucular
def last_candle_s(conn) -> float:
    return conn.execute("SELECT max(open_time) FROM historical_candles WHERE timeframe='1m'").fetchone()[0] / 1000.0


def finish_table(events: list[dict], conn, t_hi: float, k_base: int, pool: int, windows_fn, seed: int, cs: Candles, log=print) -> "Table":
    events = [e for e in events if e["t"] <= t_hi]
    for e in events:
        e["kind"] = 0
    times: dict[str, list[float]] = collections.defaultdict(list)
    for e in events:
        times[e["sym"]].append(e["t"])
    tarr = {k: np.array(v) for k, v in times.items()}
    wins = {i: windows_fn(e["t"]) for i, e in enumerate(events)}
    base = make_baseline(events, tarr, 0.0, t_hi, pool, seed, windows=wins)
    T = Table(events + base)
    log("[table] olay %d, taban havuzu %d" % (len(events), len(base)))
    T.fill(cs, log=log)
    T.select_baselines(k_base)
    log("[table] geçerli olay %d/%d, sel_rnd %d, sel_vol %d" % (int(T.valid[T.kind == 0].sum()), len(events), int(T.sel_rnd.sum()),
                                                              int(T.sel_vol.sum())))
    return T


def cooldown_mask(T: Table, mask: np.ndarray, minutes: float) -> np.ndarray:
    """Gerçek olaylar için sembol başına cooldown (maske içinde ilk olay geçer, sonrakiler `minutes` dk içinde düşer);
    taban satırları ebeveynlerinin kararını miras alır."""
    ev = np.where((T.kind == 0) & mask)[0]
    ev = ev[np.argsort(T.t[ev], kind="stable")]
    last: dict[str, float] = {}
    keep = np.zeros(T.n, dtype=bool)
    for i in ev:
        s = T.sym[i]
        if s in last and T.t[i] - last[s] < minutes * 60:
            continue
        last[s] = T.t[i]
        keep[i] = True
    return keep[T.parent] & mask


def pmask(T: Table, lo: float, hi: float) -> np.ndarray:
    pt = T.t[T.parent]
    return (pt >= lo) & (pt < hi)


# ------------------------------------------------------------------------------------------------ rapor yardımcıları
def row_hit(s: dict, key: str, bkey: str) -> tuple[str, str]:
    return fmt_hit(*s[key]), fmt_hit(*s[bkey])


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def fmt_pct(x: float) -> str:
    return "–" if not np.isfinite(x) else "%.2f" % x


def stage_list(T: Table, period: np.ndarray, kdef: float = 1.5) -> list[tuple[str, np.ndarray, str, float | None]]:
    """Kümülatif ve tekil aşamalar (etiket, maske, hedef kuralı, net_min)."""
    P = period
    push = P & T.push
    two = push & (T.nsrc >= 2)
    a, b = "a%g" % kdef, "b%g" % kdef
    out = [
        ("0. Mevcut: gönderilen tümü (push+panel)", P, "old", None),
        ("1. + yalnız push (panel kaldırıldı)", push, "old", None),
        ("2. + ≥2 farklı kaynak", two, "old", None),
        ("2b. + ≥3 kaynak", push & (T.nsrc >= 3), "old", None),
        ("2c. + ≥4 kaynak", push & (T.nsrc >= 4), "old", None),
        ("2d. + ≥2 aile (jump+early tek sayılır)", push & (T.nfam >= 2), "old", None),
        ("3a. 2 + dinamik hedef (a: ATR)", two, a, None),
        ("3b. 2 + dinamik hedef (b: direnç)", two, b, None),
        ("3c. 2 + dinamik hedef (c: ampirik)", two, "c", None),
        ("4a. 3a + net hedef ≥ %2", two, a, 2.0),
        ("4b. 3b + net hedef ≥ %2", two, b, 2.0),
        ("4c. 3c + net hedef ≥ %2", two, "c", 2.0),
        ("4o. 2 + net ≥ %2 (eski hedefle)", two, "old", 2.0),
        # ≥2 kaynak şartı olmadan (n büyük kalsın)
        ("P3a. push + dinamik (a)", push, a, None),
        ("P3b. push + dinamik (b)", push, b, None),
        ("P3c. push + dinamik (c)", push, "c", None),
        ("P4a. push + (a) + net ≥ %2", push, a, 2.0),
        ("P4b. push + (b) + net ≥ %2", push, b, 2.0),
        ("P4c. push + (c) + net ≥ %2", push, "c", 2.0),
        ("P4o. push + net ≥ %2 (eski hedefle)", push, "old", 2.0),
        # tekil
        ("T1. yalnız ≥2 kaynak (panel dahil)", P & (T.nsrc >= 2), "old", None),
        ("T2. yalnız net ≥ %2 (eski hedef, hepsi)", P, "old", 2.0),
    ]
    return out


def funnel_tables(R: Results, period: np.ndarray, days: float, stages) -> tuple[str, str, str, list]:
    """A: sayım + isabet; B: net PnL (H1 = SL 3 %, süre=ufuk); C: H2 (SL 1,5×ATR, süre=60 dk), iyimser kayma ve brüt 60 dk sürüklenme."""
    rowsA, rowsB, rowsC, raw = [], [], [], []
    for label, mask, rule, nm in stages:
        s = stage_stats(R, mask, rule, nm, bkind="rnd")
        sv = stage_stats(R, mask, rule, nm, bkind="vol")
        k_old, n_old = old_hit_share(R, mask, rule, nm, period)
        raw.append((label, s, sv, (k_old, n_old)))
        share = "%d/%d (%.0f%%)" % (k_old, n_old, 100.0 * k_old / max(1, n_old))
        if s["n"] == 0:
            rowsA.append([label, 0, "0.0", "–", "–", "–", "–", "–", share])
            continue
        rowsA.append([label, s["n"], "%.1f" % (s["n"] / days), "%.2f" % s["tgt_mean"], fmt_hit(*s["hit_h"]), fmt_hit(*sv["bhit_h"]),
                      fmt_hit(*s["hit60"]), fmt_hit(*sv["bhit60"]), share])
        perday = s["net_sl3_hz"][0] * s["n"] / days
        rowsB.append([label, s["n"], fmt_net(*s["net_sl3_hz"]), "%.0f%%" % (100 * s["win_sl3_hz"]),
                      fmt_net(*s["bnet_sl3_hz"]), diff_str(s["net_sl3_hz"], s["bnet_sl3_hz"]),
                      fmt_net(*sv["bnet_sl3_hz"]), diff_str(sv["net_sl3_hz"], sv["bnet_sl3_hz"]), "%+.1f" % perday])
        rowsC.append([label, s["n"], fmt_net(*s["net_slatr_60"]), fmt_net(*s["bnet_slatr_60"]), diff_str(s["net_slatr_60"], s["bnet_slatr_60"]),
                      fmt_net(*s["net_sl3_hz_opt"]), fmt_net(*s["bnet_sl3_hz_opt"]),
                      fmt_net(*s["drift"]), fmt_net(*s["bdrift"]), diff_str(s["drift"], s["bdrift"])])
    ha = ["Aşama", "n", "n/gün", "ort. hedef %", "hit (ufuk) [Wilson95]", "rastgele hit (oyn.-eşl.)", "hit 60 dk", "rastgele hit60 (oyn.-eşl.)",
          "eski 'ulaştı' payı"]
    hb = ["Aşama", "n", "net H1 [%95]", "kazanan %", "rastgele H1", "fark H1 (rast.) [%95]", "oyn.-eşl. H1", "fark H1 (oyn.) [%95]",
          "toplam net/gün (puan)"]
    hc = ["Aşama", "n", "net H2", "rastgele H2", "fark H2 (rast.)", "net H1, iyimser kayma %0,05", "rastgele (iyimser)",
          "brüt 60 dk getiri (ücretsiz)", "rastgele brüt 60 dk", "fark brüt 60 dk"]
    return md_table(ha, rowsA), md_table(hb, rowsB), md_table(hc, rowsC), raw


def confirm_table(R: Results, base: np.ndarray, groups: list[tuple[str, np.ndarray]]) -> str:
    rows = []
    for label, m in groups:
        s = stage_stats(R, base & m, "old", None, bkind="rnd")
        sv = stage_stats(R, base & m, "old", None, bkind="vol")
        if s["n"] == 0:
            rows.append([label, 0, "–", "–", "–", "–", "–"])
            continue
        rows.append([label, s["n"], fmt_hit(*s["hit_h"]), fmt_hit(*s["hit60"]), fmt_net(*s["net_sl3_hz"]),
                     diff_str(s["net_sl3_hz"], s["bnet_sl3_hz"]), diff_str(sv["net_sl3_hz"], sv["bnet_sl3_hz"])])
    return md_table(["Grup", "n", "hit (ufuk, eski hedef) [Wilson95]", "hit 60 dk", "net H1", "fark H1 (rastgele)", "fark H1 (oyn.-eşl.)"], rows)


def variant_table(R: Results, base: np.ndarray, label_base: str) -> str:
    rows = []
    T = R.T
    combos = [("eski hedef (sabit)", "old")] + [("(a) ATR k=%g" % k, "a%g" % k) for k in K_LIST] + \
             [("(b) direnç k=%g" % k, "b%g" % k) for k in K_LIST] + [("(c) ampirik q60 (60 dk MFE)", "c"), ("(c') ampirik q60 (ufuk MFE)", "ch")]
    for lab, rule in combos:
        for nm in (None, 2.0):
            s = stage_stats(R, base, rule, nm, bkind="rnd")
            sv = stage_stats(R, base, rule, nm, bkind="vol")
            if s["n"] == 0:
                rows.append([lab, "evet" if nm else "hayır", 0, "–", "–", "–", "–", "–", "–"])
                continue
            tg = R.rules[rule]
            sel = base & T.valid & np.isfinite(tg) & (T.kind == 0)
            if nm is not None:
                sel &= (tg - COST) >= nm
            rows.append([lab, "evet" if nm else "hayır", s["n"], "%.2f / %.2f" % (np.nanmean(tg[sel]), np.nanmean(tg[sel]) - COST),
                         fmt_hit(*s["hit_h"]), fmt_hit(*sv["bhit_h"]),
                         fmt_net(*s["net_sl3_hz"]) + " ; " + diff_str(s["net_sl3_hz"], s["bnet_sl3_hz"]),
                         fmt_net(*s["net_slatr_60"]) + " ; " + diff_str(s["net_slatr_60"], s["bnet_slatr_60"]),
                         diff_str(sv["net_sl3_hz"], sv["bnet_sl3_hz"])])
    return md_table(["Hedef kuralı (" + label_base + ")", "net≥2 filtre", "n", "ort. brüt / net hedef %", "hit (ufuk)", "rastgele hit (oyn.-eşl.)",
                     "net H1 ; fark (rast.)", "net H2 ; fark (rast.)", "fark H1 (oyn.-eşl.)"], rows)


def weekly_table(R: Results, stages, weeks=WEEKS, t_hi: float = 0.0) -> str:
    T = R.T
    rows = []
    for label, mk, rule, nm in stages:
        for wl, lo, hi in weeks:
            per = pmask(T, lo, min(hi, t_hi + 1))
            s = stage_stats(R, mk & per, rule, nm, bkind="rnd")
            if s["n"] == 0:
                rows.append([label, wl, 0, "–", "–", "–", "–"])
                continue
            rows.append([label, wl, s["n"], fmt_hit(*s["hit_h"]), fmt_net(*s["net_sl3_hz"]), fmt_net(*s["bnet_sl3_hz"]),
                         diff_str(s["net_sl3_hz"], s["bnet_sl3_hz"])])
    return md_table(["Aşama", "Hafta", "n", "hit (ufuk)", "net H1", "rastgele H1", "fark H1"], rows)


def info_table(T: Table, mask: np.ndarray) -> str:
    """Sinyal anında bilinen özellikler gerçekleşen getiriyi (yön) ya da yalnız aralığı (büyüklük) mü öngörüyor? Spearman (olay satırları)."""
    from scipy.stats import spearmanr
    sel = mask & T.valid & (T.kind == 0)
    f = T.feat
    cols = [("ATR14(5m) %", f["atr"]), ("hedef (a) k=1.5", f["a1.5"]), ("hedef (b) k=1.5", f["b1.5"]), ("hedef (c) ampirik", f["c"]),
            ("eski hedef (sabit)", T.old_tgt), ("direnç payı %", np.where(np.isfinite(f["room"]), f["room"], 50.0))]
    tg = [("MFE ufuk %", f["mfe_h"]), ("MFE 60 dk %", f["mfe60"]), ("|MAE| 60 dk %", -f["mae60"]), ("brüt 60 dk getiri % (yön)", f["drift60"])]
    rows = []
    for cn, cv in cols:
        r = [cn]
        for tn, tv in tg:
            m = sel & np.isfinite(cv) & np.isfinite(tv)
            if m.sum() < 30:
                r.append("–")
                continue
            rho = spearmanr(cv[m], tv[m])[0]
            r.append("%+.2f" % rho)
        rows.append(r)
    return md_table(["Sinyal anı özelliği (n=%d)" % int(sel.sum())] + [t[0] for t in tg], rows)


def breakeven_table() -> str:
    rows = []
    for tp in (2.0, 2.5, 3.0, 4.0):
        for sl in (1.5, 3.0):
            win = tp - 2 * D.FEE_LEG_PCT
            loss = sl + SLIP + 2 * D.FEE_LEG_PCT
            rows.append(["%.1f" % tp, "%.1f" % sl, "%+.2f" % win, "%.2f" % loss, "%.0f%%" % (100 * loss / (win + loss))])
    return md_table(["Hedef % (dolan girişe göre)", "SL %", "kazanç (net)", "kayıp (net, stop kaymalı)", "başabaş isabet (yalnız TP/SL, zaman stopu yok)"], rows)


def prod_table(T: Table, R: Results) -> str:
    """83 üretim satırı: uygulamanın kendi etiketi ('Hedefe ulaştı') + filtreler."""
    p = T.src == "prod"
    pe = p & (T.kind == 0)
    rows = []
    defs = [("tümü (push+panel)", p), ("yalnız push", p & T.push), ("panel", p & ~T.push),
            ("push, 1 kaynak", p & T.push & (T.nsrc == 1)), ("push, ≥2 kaynak", p & T.push & (T.nsrc >= 2)),
            ("push, ≥3 kaynak", p & T.push & (T.nsrc >= 3)), ("push, ≥2 aile", p & T.push & (T.nfam >= 2))]
    for lab, m in defs:
        known = m & pe & (T.app_hit >= 0)
        k = int((T.app_hit[known] == 1).sum())
        s = stage_stats(R, m, "old", None, bkind="vol")
        rows.append([lab, int((m & pe).sum()), int(known.sum()), fmt_hit(k, int(known.sum())), fmt_hit(*s["hit_h"]) if s["n"] else "–",
                     fmt_net(*s["net_sl3_hz"]) if s["n"] else "–", fmt_net(*s["bnet_sl3_hz"]) if s["n"] else "–"])
    t1 = md_table(["Üretim satırları (22:30 15.10 → 17.10)", "satır", "sonuçlanmış", "uygulama etiketi: 'Hedefe ulaştı' [Wilson95]",
                   "bizim hesap: hit (ufuk, eski hedef)", "net H1", "rastgele (oyn.-eşl.) H1"], rows)
    rows2 = []
    for lab, mk, rule, nm in (("push + (a) k=1.5", p & T.push, "a1.5", None), ("push + (b) k=1.5", p & T.push, "b1.5", None),
                              ("push + (c)", p & T.push, "c", None), ("push + (a) + net≥2", p & T.push, "a1.5", 2.0),
                              ("push + (b) + net≥2", p & T.push, "b1.5", 2.0), ("push + (c) + net≥2", p & T.push, "c", 2.0),
                              ("push + eski hedef + net≥2", p & T.push, "old", 2.0), ("push+≥2 kaynak + net≥2 (eski)", p & T.push & (T.nsrc >= 2), "old", 2.0)):
        s = stage_stats(R, mk, rule, nm, bkind="vol")
        rows2.append([lab, s["n"], fmt_hit(*s["hit_h"]) if s["n"] else "–", fmt_net(*s["net_sl3_hz"]) if s["n"] else "–",
                      fmt_net(*s["bnet_sl3_hz"]) if s["n"] else "–"])
    t2 = md_table(["Üretim satırlarında filtre", "n", "hit (ufuk)", "net H1", "rastgele (oyn.-eşl.) H1"], rows2)
    return t1 + "\n" + t2


def app_vs_mine(T: Table, R: Results) -> str:
    """Uygulamanın kendi 'hedefe ulaştı' etiketi ile bizim hesabın uyumu (DB + üretim)."""
    ev = (T.kind == 0) & T.valid & (T.app_hit >= 0) & np.isfinite(T.old_tgt)
    mine = R.hit_h["old"]
    both = int((ev & (T.app_hit == 1) & mine).sum())
    a_only = int((ev & (T.app_hit == 1) & ~mine).sum())
    m_only = int((ev & (T.app_hit == 0) & mine).sum())
    none = int((ev & (T.app_hit == 0) & ~mine).sum())
    return ("uygulama=ulaştı & bizim=ulaştı: %d; yalnız uygulama: %d; yalnız bizim: %d; ikisi de ulaşmadı: %d (n=%d, uyum %.1f%%)"
            % (both, a_only, m_only, none, both + a_only + m_only + none, 100.0 * (both + none) / max(1, both + a_only + m_only + none)))


# ------------------------------------------------------------------------------------------------ ana akış
def build_notif(conn, cs: Candles, t_hi: float, args, log) -> "Table":
    ev = load_db_notifications(conn, P_START, PROD_START) + load_prod_tsv(ROOT / "work" / "prod_notifications_1015_1017.tsv")
    ev = [e for e in ev if e["hz"] in (5, 15, 30, 60) and e["tgt"] and e["mode"] != "global_lead_lag"]

    def wfn(t):
        return (T7_START, t_hi) if t >= T7_START else (P_START + DAY_S, T7_START)
    return finish_table(ev, conn, t_hi, args.k_base, args.pool, wfn, args.seed, cs, log)


def build_ha(conn, cs: Candles, t_hi: float, args, log) -> "Table":
    ev = load_ha_candidates(conn, HA_START, t_hi)

    def wfn(t):
        return (T7_START, t_hi) if t >= T7_START else (HA_START + DAY_S, T7_START)
    return finish_table(ev, conn, t_hi, 3, 12, wfn, args.seed + 1, cs, log)


def build_journal(conn, cs: Candles, t_hi: float, args, log) -> "Table":
    ev = load_journal(conn, JR_START, JR_END)
    return finish_table(ev, conn, t_hi, 3, 12, lambda t: (JR_START, JR_END), args.seed + 2, cs, log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "work" / "policy7d" / "report.md"))
    ap.add_argument("--k-base", type=int, default=40)
    ap.add_argument("--pool", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--sets", default="notif,ha,jr")
    args = ap.parse_args(argv)
    import psycopg
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    conn = psycopg.connect(url, connect_timeout=10)

    def log(m):
        print(m, flush=True)

    t_last = last_candle_s(conn)
    t_hi = t_last - (W + 10) * 60
    cs = Candles(conn, int((P_START - 2 * DAY_S) * 1000))
    sets = set(args.sets.split(","))
    res: dict = {"parts": {"breakeven": breakeven_table()}}
    days7 = (t_hi - T7_START) / DAY_S
    days_prev = (T7_START - P_START) / DAY_S

    if "notif" in sets:
        T = build_notif(conn, cs, t_hi, args, log)
        R = Results(T, build_rules(T))
        per7 = pmask(T, T7_START, 9e18)
        perp = pmask(T, P_START, T7_START) & (T.nsrc > 0)      # önceki dönemde kaynak bilgisi olmayan satırlar (NULL) dışarıda
        allp = pmask(T, P_START, 9e18)
        A7, B7, C7, raw7 = funnel_tables(R, per7, days7, stage_list(T, per7))
        Ap, Bp, Cp, rawp = funnel_tables(R, perp, days_prev, stage_list(T, perp))
        res["parts"]["huni7C"], res["parts"]["hunipC"] = C7, Cp
        res["raw7"], res["rawp"] = raw7, rawp
        res["parts"]["huni7A"], res["parts"]["huni7B"] = A7, B7
        res["parts"]["hunipA"], res["parts"]["hunipB"] = Ap, Bp
        groups = [("kaynak sayısı = 0 (bilinmiyor)", T.nsrc == 0), ("1 kaynak", T.nsrc == 1), ("2 kaynak", T.nsrc == 2),
                  ("3 kaynak", T.nsrc == 3), ("4 kaynak", T.nsrc == 4), ("aile = 1", T.nfam == 1), ("aile = 2", T.nfam == 2),
                  ("aile = 3", T.nfam == 3)]
        for key in ("velocity", "jump+early", "jump+early+rising", "velocity+jump+early", "velocity+jump+early+rising", "velocity+rising"):
            groups.append(("kombinasyon: " + key, T.srcs_key == key))
        groups.append(("başlıkta 4'LÜ TEYİT (yalnız DB satırları)", T.four == 1))
        for md in ("trend_devam", "notr", "unified", "llm_ikinci_goz", "v_donusu"):
            groups.append(("mod: " + md, T.mode == md))
        groups += [("push", T.push), ("panel", ~T.push)]
        res["parts"]["confirm_all"] = confirm_table(R, allp, groups)
        res["parts"]["confirm_7"] = confirm_table(R, per7, groups)
        res["parts"]["variants_push"] = variant_table(R, per7 & T.push, "push, 7 gün")
        res["parts"]["variants_two"] = variant_table(R, per7 & T.push & (T.nsrc >= 2), "push+≥2 kaynak, 7 gün")
        res["parts"]["variants_push_prev"] = variant_table(R, perp & T.push, "push, önceki dönem")
        sl_all = stage_list(T, allp)
        keep = ("1", "2", "3b", "4a", "4b", "4c", "4o", "P3b", "P4a", "P4b", "P4c", "P4o", "T2")
        res["parts"]["weekly"] = weekly_table(R, [x for x in sl_all if x[0].split(".")[0] in keep], t_hi=t_hi)
        res["parts"]["prod"] = prod_table(T, R)
        res["parts"]["info7"] = info_table(T, per7 & T.push)
        res["parts"]["infop"] = info_table(T, perp & T.push)
        res["app_vs_mine"] = app_vs_mine(T, R)
        res["n_valid"] = (int(T.valid[T.kind == 0].sum()), int((T.kind == 0).sum()))
        res["T"], res["R"] = T, R
    if "ha" in sets:
        TH = build_ha(conn, cs, t_hi, args, log)
        RH = Results(TH, build_rules(TH))
        h7 = pmask(TH, T7_START, 9e18)
        hp = pmask(TH, HA_START, T7_START)

        def st(per):
            return [("0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma)", per, "old", None),
                    ("net≥2 (eski hedef)", per, "old", 2.0),
                    ("(a) ATR k=1.5", per, "a1.5", None), ("(b) direnç k=1.5", per, "b1.5", None), ("(c) ampirik", per, "c", None),
                    ("(a) + net≥2", per, "a1.5", 2.0), ("(b) + net≥2", per, "b1.5", 2.0), ("(c) + net≥2", per, "c", 2.0),
                    ("(a k=2) + net≥2", per, "a2", 2.0), ("(b k=2) + net≥2", per, "b2", 2.0)]
        A, B, C, rawh7 = funnel_tables(RH, h7, days7, st(h7))
        Ap_, Bp_, Cp_, rawhp = funnel_tables(RH, hp, (T7_START - HA_START) / DAY_S, st(hp))
        res["parts"]["ha7C"], res["parts"]["hapC"] = C, Cp_
        res["parts"]["ha7A"], res["parts"]["ha7B"] = A, B
        res["parts"]["hapA"], res["parts"]["hapB"] = Ap_, Bp_
        res["rawh7"], res["rawhp"] = rawh7, rawhp
        res["TH"], res["RH"] = TH, RH
    if "jr" in sets:
        TJ = build_journal(conn, cs, t_hi, args, log)
        RJ = Results(TJ, build_rules(TJ))
        base = np.ones(TJ.n, dtype=bool)

        def cd(m):
            return cooldown_mask(TJ, m & TJ.valid, 30)
        sj = [("0. tüm birleşik tarama adayları (30 dk soğuma)", cd(base), "old", None),
              ("≥2 kaynak", cd(TJ.nsrc >= 2), "old", None), ("≥3 kaynak", cd(TJ.nsrc >= 3), "old", None),
              ("≥2 aile", cd(TJ.nfam >= 2), "old", None),
              ("≥2 bildirim kaynağı (velocity/jump/early/rising)", cd(TJ.nsrc4 >= 2), "old", None),
              ("≥2 bildirim kaynağı + (b) + net≥2", cd(TJ.nsrc4 >= 2), "b1.5", 2.0),
              ("≥2 bildirim kaynağı + net≥2 (eski)", cd(TJ.nsrc4 >= 2), "old", 2.0),
              ("≥2 kaynak + (a)", cd(TJ.nsrc >= 2), "a1.5", None), ("≥2 kaynak + (b)", cd(TJ.nsrc >= 2), "b1.5", None),
              ("≥2 kaynak + (c)", cd(TJ.nsrc >= 2), "c", None),
              ("≥2 kaynak + (a) + net≥2", cd(TJ.nsrc >= 2), "a1.5", 2.0), ("≥2 kaynak + (b) + net≥2", cd(TJ.nsrc >= 2), "b1.5", 2.0),
              ("≥2 kaynak + (c) + net≥2", cd(TJ.nsrc >= 2), "c", 2.0), ("≥2 kaynak + net≥2 (eski)", cd(TJ.nsrc >= 2), "old", 2.0),
              ("hepsi + (b) + net≥2", cd(base), "b1.5", 2.0)]
        A, B, C, rawj = funnel_tables(RJ, base, (JR_END - JR_START) / DAY_S, sj)
        res["parts"]["jrC"] = C
        res["parts"]["jrA"], res["parts"]["jrB"] = A, B
        res["rawj"] = rawj
        res["TJ"], res["RJ"] = TJ, RJ
    res.update({"t_hi": t_hi, "t_last": t_last, "days7": days7, "days_prev": days_prev})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import pickle
    with open(out.parent / "parts.pkl", "wb") as fh:
        pickle.dump({k: v for k, v in res.items() if k in ("parts", "app_vs_mine", "n_valid", "days7", "days_prev", "t_hi", "t_last", "raw7", "rawp", "rawh7", "rawhp", "rawj")}, fh)
    from scripts import policy7d_report as REP
    out.write_text(REP.render(res, args), encoding="utf-8")
    log("rapor yazıldı: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
