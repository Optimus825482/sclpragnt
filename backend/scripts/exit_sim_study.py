"""Çıkış yapısı çalışması — gerçekçi doluşla (gecikme + kayma) çıkış yapısı sinyali kârlı yapabilir mi? (2026-10-17, çevrimdışı)

Canlı koda bağlanmaz, DB'ye YAZMAZ. Simülatör: `app/rescan/exit_sim.py` (testli). Ayrıntılı yöntem üretilen raporun başındadır.

Aşamalar (`--stages`, virgüllü; varsayılan build,sim,report):
  build   olaylar (sinyal + rastgele giriş tabanları) → 1 dk pencereler (3 gecikme) → <cache-dir>/<tag>_*.npy
  sim     60 hücrelik çıkış ızgarası × 6 senaryo (gecikme 0/60/120 sn × kayma %0,05/%0,15) → <out-dir>/<tag>_results.pkl
  report  walk-forward, duyarlılık, rapor → <out-dir>/report.md (backtest) / report_live_<since>.md (live)

KAYNAKLAR
  --source backtest   90 gün (07-20 → 10-16): Hız Avcısı canlı-benzeri bölümler (work/rescan_90g_nogate.jsonl; rank ≤ 10, aşırı alımda değil,
                      bağımsız 60 dk bölümler) + "oynak dip" E / G desen sinyalleri (work/pattern90/sig/*.npz; her desen yalnız KENDİ test
                      aralığında → örneklem dışı; desenler arası 60 dk tekilleştirme). Üç 30 günlük blok B1/B2/B3.
  --source live       Canlı sinyaller: velocity_candidates (non-rescan, passes, rank ≤ 10; 60 dk bölümler) ve monitoring_notifications
                      (gerçek bildirimler; mod bazında). `--since` günü (İstanbul) → 1 dk mum verisinin sonu. Hücreler `chosen_cells.json`'dan
                      (backtest koşusunun donmuş seçimleri) okunur; tüm ızgara da ek olarak raporlanır.

31 Ekim'de yeniden koşmak için (backend/ içinden):
  python scripts/fast_backfill_klines.py --days 20 --timeframe 1m          # yeni 1 dk mumları çek (5m de gerekir: --timeframe 5m)
  python scripts/exit_sim_study.py --source live --since 2026-09-18 --cache-dir <scratch>/exitsim_live --stages build,sim,report
(ATR için 5 dk mum da güncel olmalı: fast_backfill_klines.py --days 20 --timeframe 5m.)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import exit_sim as X  # noqa: E402

TZ = timezone(timedelta(hours=3))        # İstanbul (DST yok)
DAY_MS = 86_400_000
TZ_MS = 3 * 3_600_000
W = 120                                  # pencere (dk) = en uzun zaman stopu
TAIL_MS = (W + 5) * 60_000
DELAYS = (0, 60, 120)
SLIPS = (0.05, 0.15)
SCENARIOS = [(d, s) for d in DELAYS for s in SLIPS]
PRIMARY = (60, 0.15)                     # "gerçekçi" senaryo: 60 sn gecikme, %0,15 kayma (giriş ve stop/zaman çıkışı)
OPTIMISTIC = (0, 0.05)
PESSIMISTIC = (120, 0.15)
BLOCK_NAMES = ["B1 (20 Tem–18 Ağu)", "B2 (19 Ağu–17 Eyl)", "B3 (18 Eyl–16 Eki)"]
BLK_B23, BLK_ALL = 3, 4
KIND_NAMES = ["sig", "rnd", "rndv"]       # sinyal / rastgele giriş / oynaklığı eşleşmiş rastgele giriş
N_RANDOM = 2                             # sinyal başına rastgele çekiliş sayısı
MIN_GAP_MS = 2 * 3_600_000               # rastgele giriş, herhangi bir sinyalden ≥ 2 sa uzak
MIN_N_SELECT = 100
DRIFT_BARS = (4, 14, 29, 59, 119)       # giriş barı açılışından +5/+15/+30/+60/+120 dk (bar kapanışı)
E_KEYS = ["A|base|E", "A|all|E", "B|base|E", "B|all|E", "C3|base|E", "C3|all|E"]
G_KEYS = ["B|all|G"]       # diğer G desenleri günde 500-1800 sinyal (seçici değil; docs: seçici ≤ 300/gün) → hariç
FAMILY_TR = {"fixed": "sabit TP/SL", "trail": "izleyen stop", "atr": "ATR-izleyen", "be": "başabaş", "be_trail": "başabaş+izleyen"}


# ------------------------------------------------------------------------------------------------ yardımcılar
def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + DAY_MS - 1 if end else ms


def fmt_t(ms: int | float, fmt: str = "%d/%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime(fmt)


def day_idx(ms) -> np.ndarray:
    return (np.asarray(ms, dtype=np.int64) + TZ_MS) // DAY_MS


def hour_idx(ms) -> np.ndarray:
    return ((np.asarray(ms, dtype=np.int64) + TZ_MS) // 3_600_000) % 24


def backtest_blocks() -> list[tuple[int, int]]:
    return [(parse_day("2026-07-20"), parse_day("2026-08-18", end=True)),
            (parse_day("2026-08-19"), parse_day("2026-09-17", end=True)),
            (parse_day("2026-09-18"), parse_day("2026-10-16", end=True))]


def get_conn():
    import psycopg
    url = os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    return psycopg.connect(url, connect_timeout=10)


def load_series(conn, tf: str, sym: str, lo_ms: int | None = None, cache: Path | None = None) -> np.ndarray:
    """(n, 5): open_time, open, high, low, close. `cache` doluysa .npy önbelleği (yalnız backtest)."""
    if cache is not None:
        f = cache / tf / (sym + ".npy")
        if f.exists():
            return np.load(f)
    sql = "SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe=%s"
    args: list = [sym, tf]
    if lo_ms is not None:
        sql += " AND open_time >= %s"
        args.append(int(lo_ms))
    rows = conn.execute(sql + " ORDER BY open_time", args).fetchall()
    a = np.array(rows, dtype=float).reshape(-1, 5)
    a[:, 0] = np.round(a[:, 0])
    if cache is not None:
        (cache / tf).mkdir(parents=True, exist_ok=True)
        np.save(cache / tf / (sym + ".npy"), a)
    return a


# ------------------------------------------------------------------------------------------------ olay kuruculari
def episodes_by_gap(rows: list[dict], gap_min: int = 60) -> list[dict]:
    """tick sıralı satırlarda aynı sembol için 60 dk içindeki tekrarları at (ilk satır kalır); tüm satır zamanları da döner."""
    last: dict[str, int] = {}
    out = []
    for r in sorted(rows, key=lambda r: r["t"]):
        s = r["sym"]; t = r["t"]
        if s not in last or t - last[s] >= gap_min * 60_000:
            out.append(r); last[s] = t
    return out


def ha_events(jsonl: str, lo: int, hi: int) -> tuple[list[dict], dict[str, list[int]]]:
    from scripts.radar_shield_rescan_analysis import dedupe_horizon, is_overbought, load_jsonl, mark_episodes
    rows = dedupe_horizon(load_jsonl(jsonl, lo, hi))
    base = [r for r in rows if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= 10]
    mark_episodes(base)
    ticks: dict[str, list[int]] = collections.defaultdict(list)
    ev = []
    for r in base:
        ticks[r["symbol"]].append(int(r["tick_ms"]))
        if r.get("ep"):
            tp = r.get("target_pct")
            ev.append({"src": "HA", "sym": r["symbol"], "t": int(r["tick_ms"]), "price": float(r["price"]),
                       "tp": float(tp) if tp is not None else float("nan")})
    return ev, ticks


def pattern_symbols(conn) -> list[str]:
    rows = conn.execute("SELECT symbol FROM historical_candles WHERE timeframe='5m' GROUP BY symbol HAVING count(*) >= 300").fetchall()
    return sorted(r[0] for r in rows)


def pattern_events(conn, p90_dir: Path, keys: list[str], src: str, lo: int, hi: int) -> tuple[list[dict], dict[str, list[int]]]:
    """Desen sinyalleri: her desen yalnız KENDİ test aralığında (örneklem dışı); desenler arası (sembol, 60 dk) tekilleştirme."""
    from scripts.pattern90_analysis import make_sets
    syms = pattern_symbols(conn)
    sets, _ = make_sets(parse_day("2026-10-17", end=True))
    rows = []
    ticks: dict[str, list[int]] = collections.defaultdict(list)
    for key in keys:
        f = p90_dir / "sig" / (key.replace("|", "_") + ".npz")
        if not f.exists():
            continue
        z = np.load(f)
        t = z["t"].astype(np.int64); sid = z["sid"].astype(int)
        m = (t >= lo) & (t <= hi)
        iv = sets[key.split("|")[0]]["test"]
        mi = np.zeros(len(t), dtype=bool)
        for a, b in iv:
            mi |= (t >= a) & (t <= b)
        for s_i, tt in zip(sid[m], t[m]):
            ticks[syms[s_i]].append(int(tt))                    # dışlama için TÜM sinyaller
        for s_i, tt in zip(sid[m & mi], t[m & mi]):
            rows.append({"src": src, "sym": syms[s_i], "t": int(tt), "price": float("nan"), "tp": float("nan")})
    return episodes_by_gap(rows), ticks


def live_events(conn, since_ms: int, end_ms: int) -> tuple[list[dict], dict[str, list[int]]]:
    """Canlı journal adayları (60 dk bölüm) + gerçek bildirimler (hepsi; mod bazında kaynaklar)."""
    cand = conn.execute(
        "SELECT symbol, created_at, price, target_pct FROM velocity_candidates WHERE candidate_id NOT LIKE 'rescan:%%' AND passes "
        "AND rank <= 10 AND created_at >= %s AND created_at <= %s ORDER BY created_at", (since_ms / 1000, end_ms / 1000)).fetchall()
    ticks: dict[str, list[int]] = collections.defaultdict(list)
    rows = []
    for s, ca, pr, tp in cand:
        t = int(ca * 1000)
        ticks[s].append(t)
        rows.append({"src": "CANLI_ADAY", "sym": s, "t": t, "price": float(pr), "tp": float(tp) if tp is not None else float("nan")})
    ev = episodes_by_gap(rows)
    notif = conn.execute(
        "SELECT symbol, detected_at, price, target_pct, mode FROM monitoring_notifications WHERE detected_at >= %s AND detected_at <= %s "
        "ORDER BY detected_at", (since_ms / 1000, end_ms / 1000)).fetchall()
    for s, da, pr, tp, mode in notif:
        t = int(da * 1000)
        ticks[s].append(t)
        base = {"sym": s, "t": t, "price": float(pr) if pr is not None else float("nan"), "tp": float(tp) if tp is not None else float("nan")}
        ev.append({**base, "src": "BILDIRIM_hepsi"})
        ev.append({**base, "src": "BILDIRIM_" + (mode or "bilinmiyor")})
    return ev, ticks


# ------------------------------------------------------------------------------------------------ rastgele giriş tabanları
class SymGrid:
    """Bir sembol için 5 dk ızgarasında rastgele giriş adayları: sinyallerden ≥ 2 sa uzak, 1 dk verisi var, saat dilimi, son 30 dk aralığı."""

    def __init__(self, ot, h, l, c, sig_times: np.ndarray):
        self.ot, self.h, self.l, self.c = ot, h, l, c
        self.sig = np.sort(np.asarray(sig_times, dtype=np.int64))
        n = len(ot)
        if n >= 30:
            from numpy.lib.stride_tricks import sliding_window_view
            self.rmax = sliding_window_view(h, 30).max(axis=1)
            self.rmin = sliding_window_view(l, 30).min(axis=1)
        else:
            self.rmax = self.rmin = np.zeros(0)

    def range30(self, t: np.ndarray) -> np.ndarray:
        """t'den ÖNCEKİ 30 dk yüksek-düşük aralığı (% , son kapanışa göre); eksik/boşluklu veri → NaN."""
        t = np.asarray(t, dtype=np.int64)
        j = np.searchsorted(self.ot, t, side="left")
        out = np.full(len(t), np.nan)
        ok = (j >= 30) & (j <= len(self.ot))
        jj = j[ok]
        good = (self.ot[jj - 1] >= t[ok] - 2 * 60_000) & (self.ot[jj - 30] >= t[ok] - 32 * 60_000)
        idx = np.flatnonzero(ok)[good]
        jg = jj[good]
        out[idx] = (self.rmax[jg - 30] - self.rmin[jg - 30]) / self.c[jg - 1] * 100.0
        return out

    def candidates(self, lo: int, hi: int):
        g = np.arange(-(-lo // 300_000) * 300_000, hi + 1, 300_000, dtype=np.int64)
        g = g[g + TAIL_MS <= self.ot[-1]]
        if len(g) == 0:
            return g, np.zeros(0, bool), np.zeros(0), np.zeros(0, int)
        ok = np.ones(len(g), dtype=bool)
        if len(self.sig):
            k = np.searchsorted(self.sig, g)
            d1 = np.abs(g - self.sig[np.minimum(k, len(self.sig) - 1)])
            d0 = np.abs(g - self.sig[np.maximum(k - 1, 0)])
            ok &= np.minimum(d0, d1) >= MIN_GAP_MS
        j = np.searchsorted(self.ot, g, side="left")
        jc = np.minimum(j, len(self.ot) - 1)
        ok &= (j < len(self.ot)) & ((self.ot[jc] - g) <= 5 * 60_000)
        return g, ok, self.range30(g), hour_idx(g)


# ------------------------------------------------------------------------------------------------ build
def build(args) -> None:
    out_dir = Path(args.out_dir); cache = Path(args.cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True); cache.mkdir(parents=True, exist_ok=True)
    tag = args.source
    t_start = time.time()
    conn = get_conn()
    if args.source == "backtest":
        blocks = backtest_blocks()
        lo, hi = blocks[0][0], blocks[-1][1]
        ev, ticks = ha_events(args.jsonl, lo, hi)
        e_ev, e_ticks = pattern_events(conn, Path(args.p90_dir), E_KEYS, "E", lo, hi)
        g_ev, g_ticks = pattern_events(conn, Path(args.p90_dir), G_KEYS, "G", lo, hi)
        ev += e_ev + g_ev
        for tk in (e_ticks, g_ticks):
            for s, v in tk.items():
                ticks[s].extend(v)
        sources = ["HA", "E", "G"]
        series_cache = Path(args.cache_dir) / "series"
        lo_ms = None
    else:
        since = parse_day(args.since)
        end_row = conn.execute("SELECT max(open_time) FROM historical_candles WHERE timeframe='1m' AND symbol='BTCTRY'").fetchone()[0]
        end_ms = int(end_row)
        blocks = [(since, end_ms - TAIL_MS)]
        ev, ticks = live_events(conn, since, end_ms)
        ev = [e for e in ev if since <= e["t"] <= end_ms - TAIL_MS]
        sources = sorted({e["src"] for e in ev}, key=lambda s: (s != "CANLI_ADAY", s != "BILDIRIM_hepsi", s))
        series_cache = None
        lo_ms = since - 8 * 3_600_000
        print(f"[build] canlı: {fmt_t(since)} → {fmt_t(end_ms)}; 1 dk veri sonu; olay {len(ev)}", flush=True)
    src_id = {s: i for i, s in enumerate(sources)}
    by_sym: dict[str, list[dict]] = collections.defaultdict(list)
    for e in ev:
        by_sym[e["sym"]].append(e)
    print(f"[build] kaynaklar {sources}; sinyal {len(ev)}; sembol {len(by_sym)}", flush=True)

    # blok atama
    def block_of(t: int) -> int:
        for i, (a, b) in enumerate(blocks):
            if a <= t <= b:
                return i
        return -1

    meta = {k: [] for k in ("src", "kind", "block", "day", "sym", "t", "price", "tp", "atr", "pair")}
    win = {d: {k: [] for k in ("O", "H", "L", "C", "ref", "ok")} for d in DELAYS}
    rng_master = np.random.default_rng(args.seed)
    miss_sym = 0
    n_rnd_fail = collections.Counter()
    for k_sym, (sym, evs) in enumerate(sorted(by_sym.items())):
        a1 = load_series(conn, "1m", sym, lo_ms, series_cache)
        a5 = load_series(conn, "5m", sym, None if lo_ms is None else lo_ms - 24 * 3_600_000, series_cache)
        if len(a1) < 400 or len(a5) < 30:
            miss_sym += 1
            continue
        ot = a1[:, 0].astype(np.int64); o1, h1, l1, c1 = a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4]
        grid = SymGrid(ot, h1, l1, c1, np.array(ticks.get(sym, []), dtype=np.int64))
        rng = np.random.default_rng(rng_master.integers(1 << 31))
        rows = []                                  # (src, kind, block, t, price, tp, pair)
        sig_t = np.array([e["t"] for e in evs], dtype=np.int64)
        sig_r = grid.range30(sig_t)
        gcache: dict[int, tuple] = {}
        for i, e in enumerate(evs):
            b = block_of(e["t"])
            if b < 0:
                continue
            rows.append((src_id[e["src"]], 0, b, e["t"], e["price"], e["tp"], -1))
            if b not in gcache:
                gcache[b] = grid.candidates(*blocks[b])
            g, ok, r30, hrs = gcache[b]
            if len(g) == 0:
                n_rnd_fail["rnd"] += 1; n_rnd_fail["rndv"] += 1
                continue
            c_rnd = np.flatnonzero(ok & (hrs == hour_idx(e["t"])))
            if len(c_rnd):
                pick = rng.choice(c_rnd, size=N_RANDOM, replace=len(c_rnd) < N_RANDOM)
                for p in pick:
                    rows.append((src_id[e["src"]], 1, b, int(g[p]), float("nan"), e["tp"], i))
            else:
                n_rnd_fail["rnd"] += 1
            r = sig_r[i]
            if np.isfinite(r):
                tol = max(0.25 * r, 0.4)
                c_v = np.flatnonzero(ok & np.isfinite(r30) & (np.abs(r30 - r) <= tol))
                if len(c_v) >= 8:
                    pick = rng.choice(c_v, size=N_RANDOM, replace=False)
                    for p in pick:
                        rows.append((src_id[e["src"]], 2, b, int(g[p]), float("nan"), e["tp"], i))
                else:
                    n_rnd_fail["rndv"] += 1
            else:
                n_rnd_fail["rndv"] += 1
        if not rows:
            continue
        r_src = np.array([r[0] for r in rows], dtype=np.int8); r_kind = np.array([r[1] for r in rows], dtype=np.int8)
        r_blk = np.array([r[2] for r in rows], dtype=np.int8); r_t = np.array([r[3] for r in rows], dtype=np.int64)
        r_price = np.array([r[4] for r in rows]); r_tp = np.array([r[5] for r in rows])
        atr = X.atr_pct_at(a5[:, 0].astype(np.int64), a5[:, 2], a5[:, 3], a5[:, 4], r_t)
        okall = np.ones(len(rows), dtype=bool)
        chunk = {}
        for d in DELAYS:
            idx, ok = X.entry_index(ot, r_t, d)
            O, H, L, C, ref, cov = X.gather_windows(ot, o1, h1, l1, c1, idx, W)
            chunk[d] = (O, H, L, C, ref, ok & cov)
            okall &= ok & cov
        for d in DELAYS:
            O, H, L, C, ref, ok = chunk[d]
            win[d]["O"].append(O[okall]); win[d]["H"].append(H[okall]); win[d]["L"].append(L[okall]); win[d]["C"].append(C[okall])
            win[d]["ref"].append(ref[okall])
        meta["src"].append(r_src[okall]); meta["kind"].append(r_kind[okall]); meta["block"].append(r_blk[okall])
        meta["day"].append(day_idx(r_t[okall]).astype(np.int32)); meta["t"].append(r_t[okall])
        meta["sym"].append(np.array([sym] * int(okall.sum())))
        meta["price"].append(r_price[okall]); meta["tp"].append(r_tp[okall]); meta["atr"].append(atr[okall])
        meta["pair"].append(np.full(int(okall.sum()), k_sym, dtype=np.int32))
        if (k_sym + 1) % 25 == 0:
            print(f"[build] {k_sym + 1}/{len(by_sym)} sembol ({time.time() - t_start:.0f} sn)", flush=True)
    conn.close()
    M = {k: np.concatenate(v) for k, v in meta.items()}
    med = float(np.nanmedian(M["atr"]))
    M["atr_missing"] = ~np.isfinite(M["atr"])
    M["atr"] = np.where(np.isfinite(M["atr"]), M["atr"], med)
    np.savez(cache / (tag + "_meta.npz"), **M, sources=np.array(sources), blocks=np.array(blocks, dtype=np.int64))
    for d in DELAYS:
        np.savez(cache / (tag + "_win%d.npz" % d), **{k: np.concatenate(v) for k, v in win[d].items() if v})
        win[d] = None
    cnt = collections.Counter(zip(M["src"].tolist(), M["kind"].tolist(), M["block"].tolist()))
    print(f"[build] bitti: {len(M['t'])} işlem; sembol atlanan {miss_sym}; rastgele bulunamayan {dict(n_rnd_fail)}; ATR yok {int(M['atr_missing'].sum())} "
          f"({time.time() - t_start:.0f} sn)", flush=True)
    print("[build] sayılar (kaynak, tür, blok): " + str(sorted(cnt.items())), flush=True)


# ------------------------------------------------------------------------------------------------ sim
def groups_of(M: dict, sources: list[str]) -> dict:
    """(src_ad, kind, blok) → indeks dizisi; blok: 0..2, 3 = blok 2+3, 4 = tümü."""
    out = {}
    nb = int(M["block"].max()) + 1 if len(M["block"]) else 0
    for si, s in enumerate(sources):
        for k in range(3):
            base = (M["src"] == si) & (M["kind"] == k)
            for b in range(nb):
                ix = np.flatnonzero(base & (M["block"] == b))
                if len(ix):
                    out[(s, k, b)] = ix
            if nb >= 3:
                ix = np.flatnonzero(base & (M["block"] >= 1))
                if len(ix):
                    out[(s, k, BLK_B23)] = ix
            ix = np.flatnonzero(base)
            if len(ix):
                out[(s, k, BLK_ALL)] = ix
    return out


def sim(args) -> None:
    cache = Path(args.cache_dir); out_dir = Path(args.out_dir)
    tag = args.source
    z = np.load(cache / (tag + "_meta.npz"), allow_pickle=False)
    M = {k: z[k] for k in z.files}
    sources = [str(s) for s in M["sources"]]
    grid = X.default_grid()
    groups = groups_of(M, sources)
    tp_cand = M["tp"].copy()
    # desen kaynakları (E, G) için aday hedefi yok → yedek %4,0 (spec.tp_fallback)
    results: dict = {}
    t0 = time.time()
    for d in DELAYS:
        w = np.load(cache / (tag + "_win%d.npz" % d))
        O, H, L, C = (np.ascontiguousarray(w[k].T) for k in ("O", "H", "L", "C"))
        for slip in SLIPS:
            for ci, spec in enumerate(grid):
                r = X.simulate(O, H, L, C, spec, slip_pct=slip, tp_cand_pct=tp_cand, atr_pct=M["atr"], time_major=True)
                for key, ix in groups.items():
                    results[(d, slip, ci, key[0], key[1], key[2])] = X.trade_stats(
                        r["net"][ix], M["day"][ix], r["reason"][ix], r["hold"][ix], r["mfe"][ix], r["mae"][ix])
            print(f"[sim] gecikme {d} sn, kayma %{slip}: {len(grid)} hücre ({time.time() - t0:.0f} sn)", flush=True)
    # giriş sapması: fiyat → giriş barı açılışı (yalnız fiyatı olan sinyaller)
    dev = {}
    for d in DELAYS:
        w = np.load(cache / (tag + "_win%d.npz" % d))
        m = (M["kind"] == 0) & np.isfinite(M["price"])
        if m.any():
            for si, s in enumerate(sources):
                mm = m & (M["src"] == si)
                if mm.any():
                    dev[(d, s)] = (float(np.mean(w["ref"][mm] / M["price"][mm] - 1) * 100), float(np.median(w["ref"][mm] / M["price"][mm] - 1) * 100))
    # brüt sürüklenme (ücret / kayma / çıkış kuralı YOK): giriş barı açılışından k dk sonraki barın kapanışı, gecikme 60 sn
    w = np.load(cache / (tag + "_win60.npz"))
    drift = {}
    for key, ix in groups.items():
        row = {}
        for k in DRIFT_BARS:
            x = (w["C"][ix, k].astype(float) - 1.0) * 100.0
            row[k + 1] = (float(x.mean()), X.cluster_se(x, M["day"][ix]), float(np.median(x)))
        drift[key] = row
    flat = {"atr_median": float(np.median(M["atr"])), "atr_missing": int(M["atr_missing"].sum())}
    pickle.dump({"results": results, "grid": [(s.name, s.family, s.time_min) for s in grid], "sources": sources,
                 "counts": {k: len(v) for k, v in groups.items()}, "dev": dev, "flat": flat, "drift": drift,
                 "blocks": [tuple(int(x) for x in b) for b in M["blocks"]]}, open(out_dir / (tag + "_results.pkl"), "wb"))
    print(f"[sim] bitti ({time.time() - t0:.0f} sn)", flush=True)


# ------------------------------------------------------------------------------------------------ rapor
def f2(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else ("%+." + str(nd) + "f") % x


def p1(x):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else "%.1f" % (100 * x)


def stat_row(st: dict) -> str:
    if not st or not st.get("n"):
        return "| — | — | — | — | — | — |"
    mix = " / ".join("%d" % round(100 * v) for v in st["mix"])
    return "| %d | %s | %s | %s | %s/%s | %s |" % (st["n"], f2(st["mean"]), f2(st["t"], 1), p1(st["win"]), f2(st["avg_win"]), f2(st["avg_loss"]), mix)


class Res:
    def __init__(self, path: Path):
        d = pickle.load(open(path, "rb"))
        self.r = d["results"]; self.grid = d["grid"]; self.sources = d["sources"]; self.counts = d["counts"]
        self.dev = d["dev"]; self.flat = d["flat"]; self.blocks = d["blocks"]; self.drift = d.get("drift", {})

    def g(self, sc, ci, src, kind, blk):
        return self.r.get((sc[0], sc[1], ci, src, kind, blk), {})

    def cells(self):
        return range(len(self.grid))

    def best(self, sc, src, blk, family=None, kind=0, key="mean", min_n=MIN_N_SELECT, exclude=()):
        best = None
        for ci in self.cells():
            if family and self.grid[ci][1] != family:
                continue
            if ci in exclude:
                continue
            st = self.g(sc, ci, src, kind, blk)
            if not st or st.get("n", 0) < min_n:
                continue
            v = st[key] if key != "diff" else self.diff(sc, ci, src, blk, "rnd")["diff"]
            if not np.isfinite(v):
                continue
            if best is None or v > best[0]:
                best = (v, ci)
        return best[1] if best else None

    def diff(self, sc, ci, src, blk, which="rnd"):
        a = self.g(sc, ci, src, 0, blk)
        b = self.g(sc, ci, src, 1 if which == "rnd" else 2, blk)
        return X.diff_stats(a, b) or {"diff": float("nan"), "se": float("nan"), "t": float("nan"), "lo": float("nan"), "hi": float("nan")}


def ci_txt(st: dict) -> str:
    if not st or not st.get("n") or not np.isfinite(st.get("se", float("nan"))):
        return "—"
    return "%s [%s; %s]" % (f2(st["mean"]), f2(st["mean"] - 1.96 * st["se"]), f2(st["mean"] + 1.96 * st["se"]))


def dci_txt(d: dict) -> str:
    if not d or not np.isfinite(d.get("diff", float("nan"))):
        return "—"
    return "%s [%s; %s]" % (f2(d["diff"]), f2(d["lo"]), f2(d["hi"]))


def sc_name(sc) -> str:
    return "%d sn / %%%.2f" % (sc[0], sc[1])


def report_backtest(args) -> None:
    out_dir = Path(args.out_dir)
    R = Res(out_dir / "backtest_results.pkl")
    sources = R.sources
    L: list[str] = []
    A = L.append
    names = [g[0] for g in R.grid]
    fam = [g[1] for g in R.grid]
    A("# Çıkış Yapısı Çalışması — gerçekçi doluşla (gecikme + kayma) çıkış sinyali kârlı yapar mı? (2026-10-17)")
    A("")
    A("Bu rapor `backend/scripts/exit_sim_study.py` tarafından üretilmiştir (simülatör: `app/rescan/exit_sim.py`, testli: `tests/test_exit_sim.py`). "
      "Çalışma çevrimdışıdır; canlı koda bağlanmaz.")
    A("")
    # ---- yöntem
    A("## 1. Yöntem")
    A("- **Soru:** Dört önceki çalışma (docs/DOGRULAMA_90G_2026-10-17.md, docs/CIKIS_DESEN_ANALIZI_90G_2026-10-17.md) Hız Avcısı'nın (HA) sinyalinin gerçek olduğunu "
      "(şansın +4–6 pp üstünde) ama sabit TP / SL −3 / maliyet 0,225 ve **iyimser doluşla** (sinyal fiyatından giriş, gecikme yok, kayma yok) her yapılandırmada net negatif "
      "olduğunu gösterdi. Burada **çıkış yapısı** gerçekçi doluşla ölçülür.")
    A("- **Giriş:** sinyal anı + gecikme (0 / 60 / 120 sn) sonrasındaki ilk 1 dk barın AÇILIŞI × (1 + kayma %0,05 / %0,15). Yüzdeler (TP, SL, tetik, iz) dolan giriş fiyatına göredir. "
      "Bacak başına ücret %0,1125 (iki bacak). Birincil senaryo: **60 sn / %0,15** (gerçekçi); iyimser 0 sn / %0,05; kötümser 120 sn / %0,15.")
    A("- **Çıkış (1 dk yolunda, kötümser bar-içi sıra):** bir barda önce STOP kontrolü (önceki barlardan gelen seviye), sonra TP, en son en-yüksek (HWM) güncellemesi; yeni izleyen "
      "stop bir sonraki bardan geçerli. Stop doluşu min(stop, bar açılışı) × (1 − kayma) (boşluk → açılıştan); TP doluşu tam TP fiyatı (pozitif kayma yok); zaman stopu son barın "
      "kapanışı × (1 − kayma). Aynı barda stop ve TP görülürse stop kazanır.")
    A("- **Izgara (%d hücre):** (a) sabit TP {aday hedefi, 1,5} × SL {1,5; 3} × zaman {30, 60, 120} dk = 12; (b) izleyen stop: tetik {0,5; 1,0; 1,5} × iz {0,4; 0,8; 1,2} × SL {1,5; 3} (60 dk) "
      "+ SL 3 için 30 / 120 dk = 36; (c) ATR-izleyen: iz = k × ATR14(5m)%% , k {1; 1,5; 2}, tetik 1,0, SL {1,5; 3}, 60 dk = 6; (d) başabaş (+%%0,6'da stop = giriş) × TP {aday, 1,5} × SL {1,5; 3} = 4; "
      "(e) başabaş+izleyen (tetik 1,0, iz 0,8) × SL {1,5; 3} = 2. Zaman stopu tüm hücrelerde var. Aday hedefi E/G desenlerinde yok → yedek %%4,0 (HA'da aday `target_pct`)." % len(names))
    A("- **Sinyal kümeleri (90 gün, üç 30 günlük blok: B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki, İstanbul günü):** "
      "**HA** = rescan canlı-benzeri alt küme (rank ≤ 10, aşırı alımda değil, bağımsız 60 dk bölümler; `work/rescan_90g_nogate.jsonl`). "
      "**E / G** = 'oynak dip' desen aileleri (`work/pattern90/patterns.json`, sinyaller `work/pattern90/sig/*.npz`; E: 6 desen, hepsi ≤ 163 sinyal/gün; G: yalnız B|all|G, 110 sinyal/gün — diğer dört G deseni günde 500–1 800 sinyal verdiği için 'seçici' değil, hariç); her desen yalnız **kendi test aralığında** "
      "(eğitim penceresi dışı, yani örneklem dışı) alınır, desenler arası (sembol, 60 dk) tekilleştirilir. Karar anı = 5 dk barın kapanışı.")
    A("- **Rastgele-giriş tabanı (aynı çıkışlar):** her sinyal için aynı sembol, aynı blok, aynı İstanbul saati diliminde, herhangi bir sinyalden (HA'nın TÜM satırları + E/G sinyalleri) "
      "≥ 2 sa uzak, %d rastgele 5 dk-hizalı an (kind=rnd). Ek olarak **oynaklığı eşleşmiş** taban (kind=rndv): aynı sembol/blok, ≥ 2 sa uzak, son 30 dk yüksek-düşük aralığı ±%%25 "
      "(en az 0,4 pt) içinde (en az 8 aday yoksa atlanır). Fark = sinyal ortalaması − taban ortalaması. Rastgele girişte aday hedefi, eşleştiği sinyalinkini miras alır." % N_RANDOM)
    A("- **İstatistik:** ortalama net %'si; t ve %95 aralık **gün-kümeli** standart hata ile (aynı gün içindeki işlemler ilişkili); fark SE'si iki grubun SE'lerinin karekökü (muhafazakâr). "
      "Kazanç/kayıp = kazanan/kaybeden işlemlerin ortalaması. Çıkış payları: TP / SL / iz / başabaş / zaman (%).")
    A("- **Walk-forward:** en iyi hücre eğitim bloğunda (n ≥ %d, ortalama net) seçilir, sonraki bloklarda DOKUNULMADAN ölçülür." % MIN_N_SELECT)
    A("")
    # ---- örneklem
    A("## 2. Örneklem")
    A("| kaynak | tür | B1 | B2 | B3 | toplam |")
    A("|---|---|---|---|---|---|")
    for s in sources:
        for k, kn in enumerate(["sinyal", "rastgele", "rastgele (oynaklık eşl.)"]):
            A("| %s | %s | %s |" % (s, kn, " | ".join(str(R.counts.get((s, k, b), 0)) for b in (0, 1, 2, BLK_ALL))))
    A("")
    A("Giriş sapması (dolan bar açılışı / sinyal fiyatı − 1, yüzde; ortalama / medyan; yalnız fiyatı olan sinyaller): " +
      "; ".join("%s %d sn: %s / %s" % (s, d, f2(v[0], 3), f2(v[1], 3)) for (d, s), v in sorted(R.dev.items())))
    A("")
    # ---- ızgara geneli
    A("## 3. Izgara geneli (birincil senaryo %s)" % sc_name(PRIMARY))
    A("| kaynak | blok | hücre sayısı | net>0 hücre | ortalama hücre neti | en iyi hücre neti (iç-örneklem) | rastgele ort. (aynı hücreler) | sinyal−rastgele ort. |")
    A("|---|---|---|---|---|---|---|---|")
    for s in sources:
        for b in (0, 1, 2, BLK_ALL):
            vs = [R.g(PRIMARY, ci, s, 0, b).get("mean") for ci in R.cells()]
            vr = [R.g(PRIMARY, ci, s, 1, b).get("mean") for ci in R.cells()]
            ok = [i for i, (a, c) in enumerate(zip(vs, vr)) if a is not None and c is not None]
            if not ok:
                continue
            a = np.array([vs[i] for i in ok]); c = np.array([vr[i] for i in ok])
            A("| %s | %s | %d | %d | %s | %s | %s | %s |" % (s, ("B%d" % (b + 1)) if b < 3 else "90 gün", len(ok), int((a > 0).sum()), f2(a.mean()), f2(a.max()), f2(c.mean()), f2((a - c).mean())))
    A("")
    # ---- brüt sürüklenme
    if R.drift:
        A("### 3b. Brüt sürüklenme (ücret, kayma, çıkış kuralı YOK; giriş = 60 sn gecikmeli bar açılışı; ortalama % [medyan]; t = gün-kümeli)")
        A("")
        A("| kaynak | blok | tür | " + " | ".join("+%d dk" % h for h in [k + 1 for k in DRIFT_BARS]) + " |")
        A("|---|---|---|" + "---|" * len(DRIFT_BARS))
        for s in sources:
            for b in (0, 1, 2, BLK_ALL):
                for k, kn in ((0, "sinyal"), (1, "rastgele"), (2, "rastgele-oyn.")):
                    row = R.drift.get((s, k, b))
                    if not row:
                        continue
                    cells = []
                    for h in [kk + 1 for kk in DRIFT_BARS]:
                        m, se, med = row[h]
                        cells.append("%s (t %s) [%s]" % (f2(m, 3), f2(m / se if se else float("nan"), 1), f2(med, 3)))
                    A("| %s | %s | %s | %s |" % (s, ("B%d" % (b + 1)) if b < 3 else "90 gün", kn, " | ".join(cells)))
        A("")
        A("Fark (sinyal − rastgele) ortalama sürüklenme, 90 gün:")
        A("")
        A("| kaynak | " + " | ".join("+%d dk" % h for h in [k + 1 for k in DRIFT_BARS]) + " |")
        A("|---|" + "---|" * len(DRIFT_BARS))
        for s in sources:
            r0 = R.drift.get((s, 0, BLK_ALL)); r1 = R.drift.get((s, 1, BLK_ALL)); r2 = R.drift.get((s, 2, BLK_ALL))
            if not (r0 and r1):
                continue
            cells = []
            for h in [kk + 1 for kk in DRIFT_BARS]:
                d1 = r0[h][0] - r1[h][0]; se1 = (r0[h][1] ** 2 + r1[h][1] ** 2) ** 0.5
                d2 = (r0[h][0] - r2[h][0]) if r2 else float("nan"); se2 = ((r0[h][1] ** 2 + r2[h][1] ** 2) ** 0.5) if r2 else float("nan")
                cells.append("rastgele %s ±%.3f; oyn. %s ±%.3f" % (f2(d1, 3), 1.96 * se1, f2(d2, 3), 1.96 * se2))
            A("| %s | %s |" % (s, " | ".join(cells)))
        A("")
    # ---- en iyi hücreler (aile bazında) — tüm 90 gün iç-örneklem
    A("## 4. Aile bazında en iyi hücreler — blok tabloları (birincil senaryo; **iç-örneklem**: hücre 90 günün tamamında ortalama neti en yüksek olandan seçildi, yani iyimser)")
    A("Sütunlar: n | net ort. % | t (gün-kümeli) | kazanma % | ort. kazanç/kayıp | çıkış payı TP/SL/iz/başabaş/zaman %.")
    for s in sources:
        A("")
        A("### %s" % s)
        for fm in ("fixed", "trail", "atr", "be"):
            ci = R.best(PRIMARY, s, BLK_ALL, family=fm)
            if ci is None:
                continue
            A("")
            A("**%s — %s**" % (FAMILY_TR[fm], names[ci]))
            A("")
            A("| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |")
            A("|---|---|---|---|---|---|---|---|")
            for b in (0, 1, 2, BLK_ALL):
                bn = ("B%d" % (b + 1)) if b < 3 else "90 gün"
                for k, kn in ((0, "sinyal"), (1, "rastgele"), (2, "rastgele-oynaklık")):
                    st = R.g(PRIMARY, ci, s, k, b)
                    A("| %s | %s %s" % (bn, kn, stat_row(st)))
                d1 = R.diff(PRIMARY, ci, s, b, "rnd"); d2 = R.diff(PRIMARY, ci, s, b, "rndv")
                A("| %s | **fark: sinyal−rastgele** | | %s | | | | |" % (bn, dci_txt(d1)))
                A("| %s | **fark: sinyal−rastgele(oynaklık)** | | %s | | | | |" % (bn, dci_txt(d2)))
    A("")
    # ---- walk-forward
    A("## 5. Walk-forward (eğitim bloğunda seç → sonraki blokta dokunmadan ölç)")
    A("Seçim ölçütü: eğitim bloğunda sinyal ortalama neti (n ≥ %d). 'Sinyal−rastgele' aynı hücrede, aynı blokta; aralıklar %%95 (gün-kümeli SE). "
      "Son sütun: aynı OOS blokta hücrelerin kaçı net>0 (seçimsiz kıyas)." % MIN_N_SELECT)
    wf_pass = []
    for sc in (PRIMARY, OPTIMISTIC, PESSIMISTIC):
        A("")
        A("### Senaryo %s" % sc_name(sc))
        A("")
        A("| kaynak | seçim | seçilen hücre | eğitim n / net | OOS blok | OOS n | OOS net [%95] | t | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oynaklık) [%95] | OOS'ta net>0 hücre |")
        A("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in sources:
            for tr_b, te_list in ((0, (1, 2, BLK_B23)), (1, (2,))):
                ci = R.best(sc, s, tr_b)
                if ci is None:
                    continue
                trs = R.g(sc, ci, s, 0, tr_b)
                for te in te_list:
                    st = R.g(sc, ci, s, 0, te)
                    if not st:
                        continue
                    rnd = R.g(sc, ci, s, 1, te)
                    d1 = R.diff(sc, ci, s, te, "rnd"); d2 = R.diff(sc, ci, s, te, "rndv")
                    npos = sum(1 for cj in R.cells() if R.g(sc, cj, s, 0, te).get("mean", -9) > 0)
                    tn = ("B%d" % (te + 1)) if te < 3 else "B2+B3"
                    A("| %s | B%d → | %s | %d / %s | %s | %d | %s | %s | %s | %s | %s | %d/%d |" % (
                        s, tr_b + 1, names[ci], trs["n"], f2(trs["mean"]), tn, st["n"], ci_txt(st), f2(st["t"], 1), f2(rnd.get("mean")),
                        dci_txt(d1), dci_txt(d2), npos, len(R.grid)))
                    if sc == PRIMARY and np.isfinite(st.get("se", float("nan"))):
                        wf_pass.append((s, tr_b, te, ci, st["mean"] - 1.96 * st["se"], d1.get("lo"), d2.get("lo"), st["mean"], d1.get("diff")))
    A("")
    # aile içi walk-forward (birincil)
    A("### Aile bazında walk-forward (birincil senaryo; her ailenin B1-en-iyisi → B2, B3)")
    A("")
    A("| kaynak | aile | seçilen hücre (B1) | B1 net | B2 net [%95] | B3 net [%95] | B2 sinyal−rastgele | B3 sinyal−rastgele |")
    A("|---|---|---|---|---|---|---|---|")
    for s in sources:
        for fm in ("fixed", "trail", "atr", "be"):
            ci = R.best(PRIMARY, s, 0, family=fm)
            if ci is None:
                continue
            A("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                s, FAMILY_TR[fm], names[ci], f2(R.g(PRIMARY, ci, s, 0, 0).get("mean")), ci_txt(R.g(PRIMARY, ci, s, 0, 1)), ci_txt(R.g(PRIMARY, ci, s, 0, 2)),
                dci_txt(R.diff(PRIMARY, ci, s, 1, "rnd")), dci_txt(R.diff(PRIMARY, ci, s, 2, "rnd"))))
    A("")
    # seçim ölçütü: fark
    A("### Alternatif seçim: eğitimde 'sinyal−rastgele' farkı en büyük hücre (birincil senaryo)")
    A("")
    A("| kaynak | seçim | hücre | eğitim fark | OOS blok | OOS net [%95] | OOS sinyal−rastgele [%95] |")
    A("|---|---|---|---|---|---|---|")
    for s in sources:
        for tr_b, te_list in ((0, (1, 2, BLK_B23)), (1, (2,))):
            ci = R.best(PRIMARY, s, tr_b, key="diff")
            if ci is None:
                continue
            for te in te_list:
                tn = ("B%d" % (te + 1)) if te < 3 else "B2+B3"
                A("| %s | B%d → | %s | %s | %s | %s | %s |" % (
                    s, tr_b + 1, names[ci], f2(R.diff(PRIMARY, ci, s, tr_b, "rnd").get("diff")), tn, ci_txt(R.g(PRIMARY, ci, s, 0, te)),
                    dci_txt(R.diff(PRIMARY, ci, s, te, "rnd"))))
    A("")
    # ---- duyarlılık
    A("## 6. Gecikme / kayma duyarlılığı (seçilen hücreler)")
    chosen = freeze_cells(R, sources)
    A("Not: gecikmeyi 0 → 120 sn artırmak net'i bozmuyor, HA ve G'de hafif iyileştiriyor (HA'da dolan açılış, sinyal fiyatının ortalama %0,04 altında: fiyat sinyal barından sonra biraz geri çekiliyor); kayma %0,05 → %0,15 ise net'i her hücrede ≈ 0,2 puan düşürüyor (giriş + stop/zaman çıkışı).")
    A("")
    A("Seçilen hücreler = HA'da B1+B2 üzerinde (birincil senaryo) aile başına en iyi hücre + B1-en-iyi (walk-forward) + her kaynak için B1-en-iyi. "
      "Bu hücreler `chosen_cells.json`'a DONDURULUR ve canlı ileri testte (rapor 8) aynen kullanılır.")
    for s in sources:
        for c in chosen.get(s, []):
            ci = c["idx"]
            A("")
            A("**%s — %s** (%s)" % (s, names[ci], c["why"]))
            A("")
            A("| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |")
            A("|---|---|---|---|---|---|---|")
            for sc in SCENARIOS:
                A("| %s | %s | %s | %s | %s | %s | %s |" % (
                    sc_name(sc), f2(R.g(sc, ci, s, 0, 0).get("mean")), f2(R.g(sc, ci, s, 0, 1).get("mean")), f2(R.g(sc, ci, s, 0, 2).get("mean")),
                    ci_txt(R.g(sc, ci, s, 0, BLK_ALL)), f2(R.g(sc, ci, s, 1, BLK_ALL).get("mean")), dci_txt(R.diff(sc, ci, s, BLK_ALL, "rnd"))))
    A("")
    # ---- karar
    A("## 7. Karar (otomatik kural)")
    A("Kural: bir (kaynak, seçim) OOS'ta **net>0** sayılması için birincil senaryoda OOS net %95 alt sınırı > 0 olmalı; **şansı geçmesi** için de sinyal−rastgele(aynı çıkış) alt sınırı > 0.")
    passes = [w for w in wf_pass if w[4] > 0]
    both = [w for w in passes if w[5] is not None and np.isfinite(w[5]) and w[5] > 0]
    pos_mean = [w for w in wf_pass if w[7] > 0]
    A("- Birincil senaryoda walk-forward satırı: %d; OOS ortalaması > 0 olan: %d; OOS net alt sınırı > 0 olan: %d; ayrıca şansı da geçen: %d." % (len(wf_pass), len(pos_mean), len(passes), len(both)))
    for w in both:
        A("  - GEÇEN: %s, B%d seçim → %s, hücre `%s`, OOS net %s" % (w[0], w[1] + 1, ("B%d" % (w[2] + 1)) if w[2] < 3 else "B2+B3", names[w[3]], f2(w[7])))
    if not both:
        A("- **Hiçbir (kaynak, seçim, OOS blok) kombinasyonu hem net-pozitif (alt sınır > 0) hem de aynı çıkışlı rastgele girişten anlamlı biçimde iyi değil.**")
    A("")
    A("## 8. Canlı ileri test")
    A("Canlı sinyaller (journal + gerçek bildirimler) için komut (backend/ içinden): `python scripts/exit_sim_study.py --source live --since 2026-09-18 --cache-dir <scratch>/exitsim_live` "
      "→ `work/exitsim/report_live_2026-09-18.md`; donmuş hücreler `work/exitsim/chosen_cells.json`. **31 Ekim'de yeniden koşmak için:** önce yeni mumları çekin "
      "(`python scripts/fast_backfill_klines.py --days 20 --timeframe 1m`, sonra `--timeframe 5m`), sonra `python scripts/exit_sim_study.py --source live --since 2026-10-17 "
      "--cache-dir <yeni-boş-klasör>` (since = bu çalışmanın veri sonu; böylece 18 Eyl–17 Eki bölümüyle çakışmayan SAF ileri dönem ölçülür; hücreler aynen donmuş listeden okunur).")
    A("")
    live_pkl = out_dir / "live_results.pkl"
    live_md = out_dir / ("report_live_%s.md" % args.since)
    if live_pkl.exists():
        RL = Res(live_pkl)
        big = [s for s in RL.sources if RL.counts.get((s, 0, BLK_ALL), 0) >= 50]
        A("Otomatik özet (birincil senaryo, HA'dan donmuş %d hücre): " % len(chosen.get("HA", [])))
        A("")
        A("| canlı kaynak | n | donmuş hücrede net>0 | en iyi donmuş hücre neti [%95] | sinyal−rastgele aralığı (donmuş hücreler) | tüm ızgarada net>0 |")
        A("|---|---|---|---|---|---|")
        for s in big:
            cs = [c["idx"] for c in chosen.get("HA", []) if RL.g(PRIMARY, c["idx"], s, 0, BLK_ALL)]
            if not cs:
                continue
            means = [RL.g(PRIMARY, ci, s, 0, BLK_ALL)["mean"] for ci in cs]
            bi = cs[int(np.argmax(means))]
            ds = [RL.diff(PRIMARY, ci, s, BLK_ALL, "rnd")["diff"] for ci in cs]
            npos = sum(1 for ci in RL.cells() if RL.g(PRIMARY, ci, s, 0, BLK_ALL).get("mean", -9) > 0)
            A("| %s | %d | %d/%d | %s: %s | %s … %s | %d/%d |" % (s, RL.counts.get((s, 0, BLK_ALL), 0), sum(1 for m in means if m > 0), len(cs), names[bi],
                                                                ci_txt(RL.g(PRIMARY, bi, s, 0, BLK_ALL)), f2(min(ds)), f2(max(ds)), npos, len(RL.grid)))
        A("")
    if live_md.exists():
        for ln in live_md.read_text(encoding="utf-8").splitlines()[1:]:
            A(("#" + ln) if ln.startswith("#") else ln)
        A("")
    # ---- ek: tam ızgara
    A("## Ek A — Tam ızgara (birincil senaryo; net ort. / t; B1 B2 B3; 90 gün sinyal−rastgele)")
    for s in sources:
        A("")
        A("### %s" % s)
        A("")
        A("| hücre | aile | n (90 gün) | net 90g | t | B1 | B2 | B3 | rastgele 90g | sinyal−rastgele 90g [%95] | sinyal−rastgele(oyn.) 90g |")
        A("|---|---|---|---|---|---|---|---|---|---|---|")
        for ci in R.cells():
            st = R.g(PRIMARY, ci, s, 0, BLK_ALL)
            if not st:
                continue
            A("| %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                names[ci], fam[ci], st["n"], f2(st["mean"]), f2(st["t"], 1), f2(R.g(PRIMARY, ci, s, 0, 0).get("mean")), f2(R.g(PRIMARY, ci, s, 0, 1).get("mean")),
                f2(R.g(PRIMARY, ci, s, 0, 2).get("mean")), f2(R.g(PRIMARY, ci, s, 1, BLK_ALL).get("mean")), dci_txt(R.diff(PRIMARY, ci, s, BLK_ALL, "rnd")),
                f2(R.diff(PRIMARY, ci, s, BLK_ALL, "rndv").get("diff"))))
    # ---- özet (başa eklenir)
    S: list[str] = []
    B = S.append
    B("## 0. Özet ve karar")
    for sc in (PRIMARY, OPTIMISTIC):
        parts = []
        for src in sources:
            vs = [(R.g(sc, ci, src, 0, BLK_ALL).get("mean", -9), ci) for ci in R.cells() if R.g(sc, ci, src, 0, BLK_ALL)]
            if not vs:
                continue
            bm, bci = max(vs)
            parts.append("%s: net>0 hücre %d/%d, en iyi 90 gün neti %s (`%s`)" % (src, sum(1 for v, _ in vs if v > 0), len(vs), f2(bm), names[bci]))
        B("- Senaryo %s — 90 günde sinyal ortalaması: %s." % (sc_name(sc), "; ".join(parts)))
    rn = [R.g(PRIMARY, ci, src, 1, BLK_ALL).get("mean") for src in sources for ci in R.cells() if R.g(PRIMARY, ci, src, 1, BLK_ALL)]
    B("- Aynı çıkışlı rastgele girişlerde (birincil senaryo) ortalama net %s: yani sinyal yokken bile kayıp ≈ maliyet tabanı (ücret 0,225 + kayma; kaymalı bacaklar için ≈ 0,3'e kadar)." % f2(float(np.mean(rn))))
    dr = R.drift.get(("HA", 0, BLK_ALL)); dr1 = R.drift.get(("HA", 1, BLK_ALL)); dr2 = R.drift.get(("HA", 2, BLK_ALL))
    if dr and dr1 and dr2:
        B("- HA brüt sürüklenme (ücretsiz, çıkış kuralsız): +60 dk ortalama %s%% (t %s), rastgele %s%%, oynaklık-eşl. %s%%; +120 dk %s%% — sinyalden sonra fiyat ORTALAMA OLARAK DÜŞÜYOR (medyan %s%%). "
          "Hız Avcısı'nın 'şansın +4–6 pp üstü' isabeti büyük olasılıkla yüksek dağılımdan (sağ kuyruk) geliyor, yönlü kazançtan değil; ızgaradaki hiçbir uzun-yön çıkış yapısı bu negatif sürüklenmeyi kâra çeviremedi." % (
              f2(dr[60][0], 3), f2(dr[60][0] / dr[60][1], 1), f2(dr1[60][0], 3), f2(dr2[60][0], 3), f2(dr[120][0], 3), f2(dr[60][2], 2)))
    ge = R.drift.get(("G", 0, BLK_ALL)); ge1 = R.drift.get(("G", 2, BLK_ALL))
    if ge and ge1:
        gb = [R.drift.get(("G", 0, b), {}).get(60, (float("nan"),))[0] for b in (0, 1, 2)]
        B("- G (tek desen B|all|G, 71 desenden sonradan seçilmiş) +60 dk sürüklenme %s%% (t %s; oynaklık-eşl. rastgele %s%%); bloklara göre B1 %s%%, B2 %s%%, B3 %s%% — tutarsız; "
          "ortalama kenar maliyet tabanının (ücret 0,225 + kayma) altında kalıyor." % (f2(ge[60][0], 3), f2(ge[60][0] / ge[60][1], 1), f2(ge1[60][0], 3), f2(gb[0], 3), f2(gb[1], 3), f2(gb[2], 3)))
    B("- Walk-forward (birincil senaryo, %d kaynak×seçim×OOS satırı): OOS ortalaması > 0: %d; OOS net %%95 alt sınırı > 0: %d; ayrıca aynı çıkışlı rastgele girişi anlamlı geçen: %d." % (len(wf_pass), len(pos_mean), len(passes), len(both)))
    rngs = []
    for src in sources:
        dv = [w[8] for w in wf_pass if w[0] == src and w[8] is not None and np.isfinite(w[8])]
        if dv:
            rngs.append("%s %s…%s" % (src, f2(min(dv)), f2(max(dv))))
    opt_best = [max(R.g(OPTIMISTIC, ci, src, 0, BLK_ALL).get("mean", -9) for ci in R.cells()) for src in sources]
    if both:
        B("- **Karar: bazı kombinasyonlar ölçütü geçti (bkz. bölüm 7); parametreleri orada.**")
    else:
        B("- **Karar: HAYIR.** Gerçekçi doluşla (60 sn gecikme + %%0,15 kayma + %%0,1125/bacak ücret) hiçbir çıkış yapısı, hiçbir kaynakta (HA, E, G) örneklem dışında net-pozitif değil; "
          "%s. Walk-forward OOS satırlarında sinyal−rastgele (aynı çıkış) farkı: %s (E/G sonradan seçilmiş desenler → iyimser) — "
          "HA'da çıkış yapısı sinyale değer katmıyor; E/G'de rastgeleye göre küçük bir üstünlük var ama net-pozitife yetmiyor. Ortak sorun: brüt kenar (≈ 0 / negatif sürüklenme, G'de küçük pozitif) maliyet tabanının altında." % (
              "iyimser doluşta (0 sn / %0,05) bile 90 günlük en iyi hücre negatif" if max(opt_best) < 0 else "iyimser doluşta (0 sn / %0,05) bazı hücreler 90 günde pozitif (bkz. bölüm 3, 5)", "; ".join(rngs)))
    B("")
    S_LIMITS = [
        "## Sınırlar",
        "- Mum çözünürlüğü 1 dk: bar-içi sıra bilinmiyor → stop-önce kuralı (kötümser); gerçek tick sırası bazı izleyen-stop çıkışlarını iyileştirebilir ya da kötüleştirebilir.",
        "- Kayma sabit (%0,05 / %0,15), sembole/likiditeye bağlı değil; emir defteri derinliği, pozisyon büyüklüğü, kısmi doluş modellenmedi. Sıfır hacimli (düz) 1 dk barlar eksik veri değil gerçek 'işlem yok'tur; likit olmayan sembollerde doluş varsayımı iyimser olabilir.",
        "- HA rescan canlıyı birebir üretmez (docs/RESCAN_HARNESS.md); canlı journal'da aşırı-alım etiketi yok (kapı `block` modunda zaten eleniyor varsayıldı). Canlı dönem 18 Eyl–17 Eki, B3 ile ÇAKIŞIR: 'ileri' yalnız hücrelerin B1+B2'de donmasından sonraki dönem anlamında; bağımsız saf ileri dönem için 31 Ekim yeniden koşusu (bölüm 8).",
        "- E ve G desenleri 71 desenden sonradan, geçmiş performansa bakılarak seçildi (çoklu karşılaştırma / seçilim yanlılığı); her biri yalnız kendi test aralığında ölçüldü, ama G'nin olumlu farkı hâlâ iyimser sayılmalı. 90 gün tek piyasa dönemi; bloklar bağımsız değil (gün-kümeli SE kullanıldı).",
        "- 'Sinyal−rastgele' SE'leri bağımsız varsayımla birleştirildi (muhafazakâr). Oynaklık-eşleşmiş tabanda adaylar yetersizse sinyal atlandı (kapsam bölüm 2'de).",
        "- Hücre ızgarası 60; en iyi hücre seçimi iç-örneklemde iyimserdir — kanıt walk-forward (bölüm 5) ve canlı ileri test (bölüm 8) satırlarıdır.",
        "",
    ]
    L[3:3] = S
    L.extend(S_LIMITS)
    (out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out_dir / "chosen_cells.json").write_text(json.dumps({"primary": list(PRIMARY), "cells": chosen, "names": names}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[report] yazıldı: " + str(out_dir / "report.md"), flush=True)


def freeze_cells(R: Res, sources: list[str]) -> dict:
    """Canlı ileri test için donmuş hücreler: kaynak başına B1+B2 (sinyal ort. net, birincil) aile-en-iyileri + B1-en-iyisi (walk-forward)."""
    out: dict = {}
    for s in sources:
        lst = []
        seen = set()
        pooled_key = None
        for fm in ("fixed", "trail", "atr", "be"):
            best = None
            for ci in R.cells():
                if R.grid[ci][1] != fm:
                    continue
                a = R.g(PRIMARY, ci, s, 0, 0); b = R.g(PRIMARY, ci, s, 0, 1)
                if not a or not b or a["n"] + b["n"] < MIN_N_SELECT:
                    continue
                m = (a["mean"] * a["n"] + b["mean"] * b["n"]) / (a["n"] + b["n"])
                if best is None or m > best[0]:
                    best = (m, ci)
            if best and best[1] not in seen:
                seen.add(best[1]); lst.append({"idx": best[1], "name": R.grid[best[1]][0], "why": "B1+B2 en iyi %s (net %s)" % (FAMILY_TR[fm], f2(best[0]))})
        ci = R.best(PRIMARY, s, 0)
        if ci is not None and ci not in seen:
            seen.add(ci); lst.append({"idx": ci, "name": R.grid[ci][0], "why": "B1 en iyi (walk-forward seçimi)"})
        out[s] = lst
    return out


def report_live(args) -> None:
    out_dir = Path(args.out_dir)
    R = Res(out_dir / "live_results.pkl")
    ch = json.loads((Path(args.chosen)).read_text(encoding="utf-8"))
    names = ch["names"]
    assert names == [g[0] for g in R.grid], "ızgara chosen_cells.json ile uyuşmuyor"
    frozen: dict[int, dict] = {}
    for c in ch["cells"].get("HA", []):          # canlı sinyaller HA benzeri → HA'da B1+B2'den donmuş hücreler (E/G desenleri canlıda üretilmiyor)
        frozen.setdefault(c["idx"], c)
    big = [s for s in R.sources if R.counts.get((s, 0, BLK_ALL), 0) >= 50]
    L: list[str] = []
    A = L.append
    A("# Çıkış yapısı — CANLI ileri test (since %s)" % args.since)
    A("")
    A("Kaynak: canlı `velocity_candidates` (non-rescan, passes, rank ≤ 10; 60 dk bölümler) ve gerçek `monitoring_notifications` (hepsi; mod bazında). 1 dk mumlar DB'den. "
      "Hücreler `chosen_cells.json`'dan (backtest koşusunun B1+B2 / B1 seçimleri; donmuş). Senaryolar: 0/60/120 sn × %%0,05 / %%0,15; birincil %s." % sc_name(PRIMARY))
    A("Rastgele taban: aynı sembol, aynı İstanbul saati, herhangi bir canlı sinyalden ≥ 2 sa uzak (rnd) ve oynaklığı eşleşmiş (rndv); canlı dönem boyunca. Veri sonu nedeniyle %d dk'dan yakın sinyaller atılır (sonuçtan bağımsız)." % (W + 5))
    A("")
    A("## Örneklem")
    A("| kaynak | sinyal n | rastgele n | rastgele(oyn.) n |")
    A("|---|---|---|---|")
    for s in R.sources:
        A("| %s | %d | %d | %d |" % (s, R.counts.get((s, 0, BLK_ALL), 0), R.counts.get((s, 1, BLK_ALL), 0), R.counts.get((s, 2, BLK_ALL), 0)))
    A("")
    A("n < 50 olan kaynaklar (%s) aşağıdaki tablolardan çıkarıldı." % ", ".join(s for s in R.sources if s not in big))
    A("")
    A("## Donmuş hücreler (HA'da B1+B2'den seçilmiş; birincil senaryo)")
    A("| kaynak | hücre | n | net ort. [%95] | t | kazanma % | kazanç/kayıp | çıkış payı TP/SL/iz/başabaş/zaman | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oyn.) [%95] |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in big:
        for ci in sorted(frozen):
            st = R.g(PRIMARY, ci, s, 0, BLK_ALL)
            if not st:
                continue
            mix = " / ".join("%d" % round(100 * v) for v in st["mix"])
            A("| %s | %s | %d | %s | %s | %s | %s/%s | %s | %s | %s | %s |" % (
                s, names[ci], st["n"], ci_txt(st), f2(st["t"], 1), p1(st["win"]), f2(st["avg_win"]), f2(st["avg_loss"]), mix,
                f2(R.g(PRIMARY, ci, s, 1, BLK_ALL).get("mean")), dci_txt(R.diff(PRIMARY, ci, s, BLK_ALL, "rnd")), dci_txt(R.diff(PRIMARY, ci, s, BLK_ALL, "rndv"))))
    A("")
    A("## Donmuş hücreler — senaryo duyarlılığı (net ort.)")
    for s in big:
        A("")
        A("**%s**" % s)
        A("")
        A("| hücre | " + " | ".join(sc_name(sc) for sc in SCENARIOS) + " |")
        A("|---|" + "---|" * len(SCENARIOS))
        for ci in sorted(frozen):
            if not R.g(PRIMARY, ci, s, 0, BLK_ALL):
                continue
            A("| %s | " % names[ci] + " | ".join(f2(R.g(sc, ci, s, 0, BLK_ALL).get("mean")) for sc in SCENARIOS) + " |")
    A("")
    A("## Tüm ızgara özeti (birincil senaryo)")
    A("| kaynak | hücre sayısı | net>0 hücre | ortalama hücre neti | en iyi hücre | en iyi net [%95] | rastgele ort. | sinyal−rastgele ort. |")
    A("|---|---|---|---|---|---|---|---|")
    for s in big:
        vs = []; vr = []
        for ci in R.cells():
            a = R.g(PRIMARY, ci, s, 0, BLK_ALL); b = R.g(PRIMARY, ci, s, 1, BLK_ALL)
            if a and b:
                vs.append(a["mean"]); vr.append(b["mean"])
        if not vs:
            continue
        a = np.array(vs); c = np.array(vr)
        bi = R.best(PRIMARY, s, BLK_ALL, min_n=30)
        A("| %s | %d | %d | %s | %s | %s | %s | %s |" % (s, len(a), int((a > 0).sum()), f2(a.mean()), names[bi] if bi is not None else "—",
                                                       ci_txt(R.g(PRIMARY, bi, s, 0, BLK_ALL)) if bi is not None else "—", f2(c.mean()), f2((a - c).mean())))
    A("")
    A("Not: bu bölümdeki 'en iyi hücre' iç-örneklemdir; yalnız donmuş hücreler ileri testtir.")
    name = "report_live_%s.md" % args.since
    (out_dir / name).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("[report] yazıldı: " + str(out_dir / name), flush=True)


def report(args) -> None:
    if args.source == "backtest":
        report_backtest(args)
    else:
        report_live(args)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("backtest", "live"), default="backtest")
    ap.add_argument("--since", default="2026-09-18", help="live: ilk gün (İstanbul, YYYY-MM-DD)")
    ap.add_argument("--stages", default="build,sim,report")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", default="work/exitsim")
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    ap.add_argument("--p90-dir", default="work/pattern90")
    ap.add_argument("--chosen", default="work/exitsim/chosen_cells.json")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    for st in [x.strip() for x in args.stages.split(",") if x.strip()]:
        fn = {"build": build, "sim": sim, "report": report}.get(st)
        if fn is None:
            sys.exit("bilinmeyen aşama: " + st)
        fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
