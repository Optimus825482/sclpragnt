"""Yeni erken-giriş dedektörleri — çevrimdışı ızgara ölçümü (2026-10-17).

`app.rescan.strategies` içindeki 4 dedektörü (ema_fan_5m, breakout_compress_5m, rs_vs_btc_5m, persist_1m)
`historical_candles` üzerinde koşturur; `scripts/ladder_rescan.py` ile AYNI ölçüt takımı:
  * sinyal sayısı, /gün; hit60 ve net60 (TP 1.5 / 2.0, SL −3, maliyet −0.225, ufuk 60 dk) + TRAILING çıkış
    (tetik %1.0, iz %0.8, SL −3, 60 dk) ve MFE/MAE,
  * şans tabanı (null3, ≥1000 örnek) → hit60 − şans (pp) HER hücre için,
  * Hız Avcısı (rescan canlı-benzeri: rank ≤ 10, aşırı alım kapısı geçen) karşılaştırması: sinyalden sonra 90 dk
    içinde HA adayı geldi mi, öncülük medyanı, HA bölümlerinin kapsaması, "yeni yakalama" kümesi,
  * en iyi hücreler (net ve şans-farkı) için BTC kalkan kırılımı ve yarı-örnek (ilk yarı / ikinci yarı) kontrolü,
  * LUNATRY 2026-10-17 01:05–01:55 sağlama: her dedektör bu yükselişte ateşledi mi, saat, giriş fiyatı.
Canlı koda bağlanmaz, DB'ye yazmaz.

Kullanım (backend/):
  DATABASE_URL=... python scripts/strategy_rescan.py --jsonl work/rescan_21g_nogate.jsonl \
      --start 2026-09-26 --end 2026-10-16 --out work/strategy_rescan.md --json work/strategy_rescan.json
"""
from __future__ import annotations

import argparse
import functools
import itertools
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import strategies as S  # noqa: E402
from app.rescan.ladder import COL_C, COL_H, COL_OT, rolling_sum  # noqa: E402
from scripts.ladder_rescan import LOOKAHEAD_MS, chance_lift, coverage, stats  # noqa: E402
from scripts.notification_outcomes_report import CandleStore, TZ  # noqa: E402
from scripts.radar_shield_rescan_analysis import (  # noqa: E402
    btc_regime_table, dedupe_horizon, is_overbought, load_btc_1h, load_btc_5m, load_jsonl, mark_episodes, parse_day,
)

DETECTORS = [
    {"name": "ema_fan_5m", "tf": "5m", "fn": S.ema_fan_5m, "grid": {"k": (2, 3), "g_min": (0.8, 1.5)}, "warm_ms": 25 * 3_600_000},
    {"name": "breakout_compress_5m", "tf": "5m", "fn": S.breakout_compress_5m,
     "grid": {"vol_min": (1.5, 2.5), "hi_lb": (24, 48)}, "warm_ms": 25 * 3_600_000},
    {"name": "rs_vs_btc_5m", "tf": "5m", "fn": S.rs_vs_btc_5m, "grid": {"x": (1.0, 1.5), "vol_min": (1.0, 1.5)}, "warm_ms": 25 * 3_600_000},
    {"name": "persist_1m", "tf": "1m", "fn": S.persist_1m, "grid": {"m": (8, 12), "g_min": (0.6, 1.0)}, "warm_ms": 26 * 3_600_000},
    # duyarlılık: aynı kural yalnız 5 dk sınırında değerlendirilir → giriş/şans tabanı 5m deposuyla birebir hizalı
    {"name": "persist_1m_5mgrid", "tf": "1m", "fn": functools.partial(S.persist_1m, align_5m=True),
     "grid": {"m": (8, 12), "g_min": (0.6, 1.0)}, "warm_ms": 26 * 3_600_000},
]
TRAIL_TRIGGER, TRAIL_GAP = 1.0, 0.8
SPLIT_DAY = "2026-10-06"  # ilk ~10 gün / son ~11 gün


# ------------------------------------------------------------------ yükleme
_SQL_5M = ("SELECT symbol, open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
           "COALESCE(quote_volume, 0)::float8 FROM historical_candles WHERE timeframe='5m' AND open_time >= %s "
           "ORDER BY symbol, open_time")
_SQL_1M_SYM = ("SELECT open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
               "COALESCE(quote_volume, 0)::float8 FROM historical_candles WHERE timeframe='1m' AND symbol=%s "
               "AND open_time >= %s ORDER BY open_time")


def load_5m(conn, since_ms: int) -> dict[str, np.ndarray]:
    import collections
    acc: dict[str, list] = collections.defaultdict(list)
    for r in conn.execute(_SQL_5M, (since_ms,)).fetchall():
        acc[r[0]].append([float(x) for x in r[1:]])
    return {s: np.array(v, dtype=float) for s, v in acc.items() if len(v) >= 300}



def _pp(v, suffix="pp"):
    """3.11 uyumu: iç içe f-string yerine — None → '—', aksi halde +x.x pp."""
    return "—" if v is None else f"{100 * v:+.1f}{suffix}"


def _mins(v):
    return "—" if v is None else f"{v:.0f}"

def liquid_symbols(series5: dict[str, np.ndarray], min_quote: float, min_frac: float = 0.10) -> list[str]:
    """24 sa quote ≥ min_quote olan bar payı ≥ min_frac olan semboller (1 dk yükleme listesi)."""
    out = []
    for s, a in series5.items():
        q = rolling_sum(np.nan_to_num(a[:, 6], nan=0.0), 288)
        ok = q[300:] >= min_quote
        if len(ok) and float(ok.mean()) >= min_frac:
            out.append(s)
    return out


def load_1m(conn, syms: list[str], since_ms: int) -> dict[str, np.ndarray]:
    out = {}
    for s in syms:
        rows = conn.execute(_SQL_1M_SYM, (s, since_ms)).fetchall()
        if len(rows) >= 1600:
            out[s] = np.array(rows, dtype=float)
    return out


# ------------------------------------------------------------------ trailing çıkış
def trail_window(store: CandleStore, sym: str, det: float, entry: float, *, trigger: float, gap: float,
                 sl: float, cost: float, H: int = 60) -> dict | None:
    """Tetik %trigger görülene dek SL; sonra izleyen stop = zirve × (1 − gap%) (zirve ÖNCEKİ barlardan, kötümser).
    Ufuk sonunda kapanışla çıkış. eval_window ile aynı kapsama kuralları."""
    if sym not in store.d:
        return None
    ot, hi, lo, cl = store.d[sym]
    det_ms = det * 1000
    i0 = int(np.searchsorted(ot, det_ms, side="right"))
    end_ms = det_ms + H * 60000
    i1 = int(np.searchsorted(ot, end_ms, side="left"))
    if i0 >= len(ot) or ot[i0] - det_ms > 600000 or i1 - i0 < max(1, int(H / 5) - 3) or ot[i1 - 1] < end_ms - 600000:
        return None
    slp = entry * (1 - sl / 100); trp = entry * (1 + trigger / 100)
    active = False; peak = entry; exit_p = None
    for k in range(i0, i1):
        h, l = hi[k], lo[k]
        if active:
            stop = peak * (1 - gap / 100)
            if l <= stop:
                exit_p = stop; break
            if h > peak:
                peak = h
        else:
            if l <= slp:
                exit_p = slp; break
            if h >= trp:
                active = True; peak = h
    if exit_p is None:
        exit_p = cl[i1 - 1]
    return {"net": float((exit_p / entry - 1) * 100 - cost)}


def trail_stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    a = np.array(vals)
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    return {"n": len(a), "net": float(a.mean()), "win": float((a > 0).mean()),
            "t": float(a.mean()) / (sd / np.sqrt(len(a))) if sd > 0 and len(a) > 1 else None}


def random_trail_baseline(series: dict[str, np.ndarray], store: CandleStore, *, n: int, seed: int, start_ms: int,
                          end_ms: int, min_quote: float, sl: float, cost: float) -> dict:
    """Koşulsuz referans: likit sembollerde rastgele 5m kapanışlarında trailing çıkış neti."""
    rng = np.random.default_rng(seed)
    syms = [s for s in series]
    vals = []; tries = 0
    q24 = {s: rolling_sum(np.nan_to_num(a[:, 6], nan=0.0), 288) for s, a in series.items()}
    while len(vals) < n and tries < n * 6:
        tries += 1
        s = syms[int(rng.integers(len(syms)))]; a = series[s]
        i = int(rng.integers(300, len(a) - 14))
        t = int(a[i, COL_OT]) + S.BAR_5M_MS
        if t < start_ms or t > end_ms or q24[s][i] < min_quote:
            continue
        r = trail_window(store, s, t / 1000.0, float(a[i, COL_C]), trigger=TRAIL_TRIGGER, gap=TRAIL_GAP, sl=sl, cost=cost)
        if r:
            vals.append(r["net"])
    return trail_stats(vals)


# ------------------------------------------------------------------ hücre koşusu
def run_cell(det: dict, params: dict, series_tf: dict[str, np.ndarray], btc: tuple[np.ndarray, np.ndarray],
             store: CandleStore, *, eff_start: int, eff_end: int, base_ticks: dict[str, np.ndarray], tps: list[float],
             sl: float, cost: float, min_quote: float) -> dict:
    bar_ms = S.BAR_1M_MS if det["tf"] == "1m" else S.BAR_5M_MS
    sigs: list[dict] = []
    for sym, arr in series_tf.items():
        if det["name"] == "rs_vs_btc_5m":
            if sym == "BTCTRY":
                continue
            idx = det["fn"](arr, btc[0], btc[1], min_quote_24h=min_quote, **params)
        else:
            idx = det["fn"](arr, min_quote_24h=min_quote, **params)
        for i in idx:
            t = S.signal_time_ms(arr, int(i), bar_ms)
            if t < eff_start or t > eff_end:
                continue
            d_s = t / 1000.0; entry = float(arr[i, COL_C])
            ev = {tp: store.eval(sym, d_s, entry, tp, 60, sl, cost) for tp in tps}
            if any(v is None for v in ev.values()):
                continue
            tr = trail_window(store, sym, d_s, entry, trigger=TRAIL_TRIGGER, gap=TRAIL_GAP, sl=sl, cost=cost)
            bt = base_ticks.get(sym); lead = None; near = False
            if bt is not None and len(bt):
                j = int(np.searchsorted(bt, t, side="right"))
                if j < len(bt) and bt[j] - t <= LOOKAHEAD_MS:
                    lead = (bt[j] - t) / 60_000.0
                near = (j < len(bt) and bt[j] - t <= LOOKAHEAD_MS) or (j > 0 and t - bt[j - 1] <= LOOKAHEAD_MS)
            sigs.append({"sym": sym, "t": t, "entry": entry, "ev": ev, "trail": tr["net"] if tr else None,
                         "lead": lead, "near": near})
    return {"params": params, "signals": sigs}


def summarize_cell(cell: dict, tps: list[float], days: float, base_eps: list[tuple[str, int]]) -> None:
    import itertools as it
    sigs = cell["signals"]
    sig_by_sym = {s: np.array(sorted(x["t"] for x in g), dtype=np.int64)
                  for s, g in it.groupby(sorted(sigs, key=lambda x: x["sym"]), key=lambda x: x["sym"])}
    cov, cov_lead = coverage(base_eps, sig_by_sym)
    leads = [s["lead"] for s in sigs if s["lead"] is not None]
    new = [s for s in sigs if not s["near"]]
    cell.update({"stats": {tp: stats([s["ev"][tp] for s in sigs]) for tp in tps},
                 "trail": trail_stats([s["trail"] for s in sigs if s["trail"] is not None]),
                 "per_day": len(sigs) / days if days else None,
                 "lead_share": (len(leads) / len(sigs)) if sigs else None,
                 "lead_median": float(np.median(leads)) if leads else None,
                 "coverage": cov, "coverage_lead": cov_lead, "new_n": len(new),
                 "new_stats": {tp: stats([s["ev"][tp] for s in new]) for tp in tps},
                 "new_trail": trail_stats([s["trail"] for s in new if s["trail"] is not None])})


# ------------------------------------------------------------------ LUNATRY sağlama
def fetch_lunatry_1m(cache: str, start_ms: int, end_ms: int) -> np.ndarray | None:
    p = Path(cache)
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = []; cur = start_ms
        try:
            while cur < end_ms:
                u = f"https://api.binance.me/api/v3/klines?symbol=LUNATRY&interval=1m&startTime={cur}&limit=1000"
                with urllib.request.urlopen(u, timeout=30) as resp:  # noqa: S310 — public, sabit URL
                    chunk = json.loads(resp.read().decode("utf-8"))
                if not chunk:
                    break
                data.extend(chunk); cur = int(chunk[-1][0]) + 60_000
        except Exception as e:  # ağ yok → 1 dk sağlama atlanır
            print(f"[strategy] LUNATRY 1m API alınamadı: {e}")
            return None
        p.write_text(json.dumps(data), encoding="utf-8")
    rows = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7])] for k in data]
    return np.array(rows, dtype=float)


def hhmm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%d.%m %H:%M")


def lunatry_check(det: dict, params: dict, arr: np.ndarray | None, btc: tuple[np.ndarray, np.ndarray],
                  w0: int, w1: int, wend: int, min_quote: float) -> dict:
    if arr is None:
        return {"ok": None}
    bar_ms = S.BAR_1M_MS if det["tf"] == "1m" else S.BAR_5M_MS
    res = {}
    for label, mq in (("5M filtreli", min_quote), ("filtresiz", 0.0)):
        if det["name"] == "rs_vs_btc_5m":
            idx = det["fn"](arr, btc[0], btc[1], min_quote_24h=mq, **params)
        else:
            idx = det["fn"](arr, min_quote_24h=mq, **params)
        ts = [(S.signal_time_ms(arr, int(i), bar_ms), float(arr[int(i), COL_C]), int(i)) for i in idx]
        inw = [x for x in ts if w0 <= x[0] <= w1]
        late = [x for x in ts if w1 < x[0] <= wend]
        if inw:
            t, ep, i = inw[0]
            fut = arr[i + 1:, COL_H]; fut = fut[arr[i + 1:, COL_OT] <= wend]
            res[label] = {"fired": True, "t": t, "entry": ep, "peak_gain": float((fut.max() / ep - 1) * 100) if len(fut) else None}
        elif late:
            res[label] = {"fired": False, "late": late[0][0], "entry": late[0][1]}
        else:
            res[label] = {"fired": False}
    return {"ok": True, "res": res}


# ------------------------------------------------------------------ biçim
def _pct(v): return "—" if v is None else f"%{100 * v:.1f}"
def _t(v): return "" if v is None else f" (t {v:+.1f})"


def _ci(s):
    ci = s.get("ci")
    return f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}]" if ci else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True); ap.add_argument("--btc-1h", default="work/btc_1h.json")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--cost", type=float, default=0.225); ap.add_argument("--sl", type=float, default=3.0)
    ap.add_argument("--tps", default="1.5,2.0"); ap.add_argument("--min-quote", type=float, default=5_000_000.0)
    ap.add_argument("--rank-max", type=int, default=10); ap.add_argument("--chance-n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7); ap.add_argument("--out", default="work/strategy_rescan.md")
    ap.add_argument("--json", default="work/strategy_rescan.json"); ap.add_argument("--db-url", default="")
    ap.add_argument("--only", default="", help="virgülle ayrılmış dedektör adları (varsayılan hepsi)")
    ap.add_argument("--lunatry-cache", default="work/lunatry_1m_1017.json")
    args = ap.parse_args(argv)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    import psycopg
    t0 = time.time()
    tps = [float(x) for x in args.tps.split(",") if x.strip()]; tp0 = tps[0]
    start_ms, end_ms = parse_day(args.start), parse_day(args.end, end=True)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    dets = [d for d in DETECTORS if not only or d["name"] in only]
    with psycopg.connect(url, connect_timeout=10) as conn:
        series5 = load_5m(conn, start_ms - 26 * 3_600_000)
        btc5m = load_btc_5m(conn)
        series1 = {}
        if any(d["tf"] == "1m" for d in dets):
            liq = liquid_symbols(series5, args.min_quote)
            series1 = load_1m(conn, liq, start_ms - 26 * 3_600_000)
            print(f"[strategy] 1m: {len(liq)} likit sembolden {len(series1)} yüklendi ({time.time() - t0:.0f} sn)")
    store = CandleStore({s: (a[:, 0], a[:, 2], a[:, 3], a[:, 4]) for s, a in series5.items()})
    print(f"[strategy] 5m: {len(series5)} sembol ({time.time() - t0:.0f} sn)")
    base_all = dedupe_horizon(load_jsonl(args.jsonl, start_ms, end_ms))
    base = [r for r in base_all if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= args.rank_max]
    mark_episodes(base)
    base_ticks = {s: np.array(sorted(int(r["tick_ms"]) for r in rs), dtype=np.int64)
                  for s, rs in itertools.groupby(sorted(base, key=lambda r: r["symbol"]), key=lambda r: r["symbol"])}
    base_eps_all = [(r["symbol"], int(r["tick_ms"])) for r in base if r.get("ep")]
    print(f"[strategy] Hız Avcısı canlı-benzeri {len(base)} satır, {len(base_eps_all)} bölüm")
    split_ms = parse_day(SPLIT_DAY)
    klines = load_btc_1h(args.btc_1h)

    # LUNATRY sağlama verisi
    lun_w0 = int(datetime(2026, 10, 17, 1, 5, tzinfo=TZ).timestamp() * 1000)
    lun_w1 = int(datetime(2026, 10, 17, 1, 55, tzinfo=TZ).timestamp() * 1000)
    lun_end = int(datetime(2026, 10, 17, 2, 20, tzinfo=TZ).timestamp() * 1000)
    lun5 = series5.get("LUNATRY")
    lun1 = None
    if any(d["tf"] == "1m" for d in dets):
        lun1 = fetch_lunatry_1m(args.lunatry_cache, lun_w0 - 27 * 3_600_000, lun_end)
    lun_info = {}
    if lun5 is not None:
        o = lun5[lun5[:, 0] + S.BAR_5M_MS <= lun_w0][-1:]
        pk = lun5[(lun5[:, 0] + S.BAR_5M_MS > lun_w0) & (lun5[:, 0] + S.BAR_5M_MS <= lun_end)]
        q24 = float(lun5[(lun5[:, 0] + S.BAR_5M_MS <= lun_w0)][-288:, 6].sum())
        lun_info = {"px0105": float(o[0, 4]) if len(o) else None, "peak": float(pk[:, 2].max()) if len(pk) else None,
                    "px_last": float(pk[-1, 4]) if len(pk) else None, "qv24_0105": q24}
    # kullanılmayan sembol sorunu: BTC dizisi
    btc = (btc5m[0].astype(float), btc5m[1])

    md_all: list[str] = []; summary: dict = {"detectors": {}}
    rb_cache = random_trail_baseline(series5, store, n=20000, seed=args.seed, start_ms=start_ms + 26 * 3_600_000, end_ms=end_ms,
                                     min_quote=args.min_quote, sl=args.sl, cost=args.cost)
    print(f"[strategy] rastgele trailing referansı: {rb_cache}")
    md_all.append(f"**Koşulsuz trailing referansı** (likit sembollerde rastgele 5m kapanışları, n={rb_cache['n']}): "
                  f"net {rb_cache['net']:+.2f}{_t(rb_cache.get('t'))}, kazanan payı {_pct(rb_cache.get('win'))}.")

    for det in dets:
        series_tf = series1 if det["tf"] == "1m" else series5
        firsts = [a[0, 0] for a in series_tf.values()]; lasts = [a[-1, 0] for a in series_tf.values()]
        eff_start = max(start_ms, int(min(firsts)) + det["warm_ms"])
        eff_end = min(end_ms, int(max(lasts)) + (S.BAR_1M_MS if det["tf"] == "1m" else S.BAR_5M_MS))
        days = (eff_end - eff_start) / 86_400_000
        base_eps = [(s, t) for s, t in base_eps_all if eff_start <= t <= eff_end]
        print(f"[strategy] === {det['name']} ({det['tf']}) etkin pencere {hhmm(eff_start)} .. {hhmm(eff_end)} ({days:.1f} gün), "
              f"HA bölüm {len(base_eps)}")
        cells = []
        for combo in itertools.product(*det["grid"].values()):
            params = dict(zip(det["grid"].keys(), combo))
            cell = run_cell(det, params, series_tf, btc, store, eff_start=eff_start, eff_end=eff_end,
                            base_ticks=base_ticks, tps=tps, sl=args.sl, cost=args.cost, min_quote=args.min_quote)
            summarize_cell(cell, tps, days, base_eps)
            n = len(cell["signals"])
            ch = chance_lift(cell["signals"], store, tp=tp0, sample_n=args.chance_n, seed=args.seed, sl=args.sl, cost=args.cost) if n >= 30 else {"n": 0, "lift": None, "null_hit": None}
            cell["chance"] = ch
            cells.append(cell)
            s0 = cell["stats"][tp0]
            print(f"[strategy]   {params} n={n} hit60@{tp0}={_pct(s0.get('hit'))} net={s0.get('net', 0):+.2f} "
                  f"lift={_pp(ch['lift'])} ({time.time() - t0:.0f} sn)")

        md = [f"## {det['name']} ({det['tf']})", "",
              f"Etkin pencere {hhmm(eff_start)} .. {hhmm(eff_end)} ({days:.1f} gün); Hız Avcısı bölümü bu pencerede {len(base_eps)}. "
              f"Trailing = tetik %{TRAIL_TRIGGER:g} / iz %{TRAIL_GAP:g} / SL −{args.sl:g}.", "",
              f"| parametre | sinyal | /gün | hit60@{tp0} [W95] | net60@{tp0} | hit60@{tps[-1]} | net60@{tps[-1]} | trailing net (kazanan) | MFE | MAE | şans (null3) | **hit−şans** | HA sonra geldi | öncülük medyan dk | HA kapsama | yeni yakalama n · hit · net |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in cells:
            s0 = c["stats"][tp0]; s1 = c["stats"][tps[-1]]; nn = c["new_stats"][tp0]; ch = c["chance"]; tr = c["trail"]
            pstr = ", ".join(f"{k}={v}" for k, v in c["params"].items())
            md.append(
                f"| {pstr} | {s0.get('n', 0)} | {c['per_day'] or 0:.0f} | {_pct(s0.get('hit'))}{_ci(s0)} | {s0.get('net', 0):+.2f}{_t(s0.get('t'))} | "
                f"{_pct(s1.get('hit'))} | {s1.get('net', 0):+.2f}{_t(s1.get('t'))} | "
                f"{tr.get('net', 0):+.2f}{_t(tr.get('t'))} ({_pct(tr.get('win'))}) | {s0.get('mfe', 0):+.2f} | {s0.get('mae', 0):+.2f} | "
                f"{_pct(ch.get('null_hit'))} | **{_pp(ch['lift'], ' pp')}** (n={ch['n']}) | "
                f"{_pct(c['lead_share'])} | {_mins(c['lead_median'])} | {_pct(c['coverage'])} | "
                f"{c['new_n']} · {_pct(nn.get('hit'))} · {nn.get('net', 0):+.2f} |")

        scored = [c for c in cells if c["stats"][tp0].get("n", 0) >= 100]
        picks: dict[str, dict] = {}
        if scored:
            picks["net"] = max(scored, key=lambda c: c["stats"][tp0]["net"])
            lifted = [c for c in scored if c["chance"]["lift"] is not None]
            if lifted:
                picks["lift"] = max(lifted, key=lambda c: c["chance"]["lift"])
        det_sum = {"tf": det["tf"], "days": days, "cells": []}
        for c in cells:
            s0 = c["stats"][tp0]
            det_sum["cells"].append({"params": c["params"], "n": s0.get("n", 0), "hit": s0.get("hit"), "net": s0.get("net"),
                                     "net_tp2": c["stats"][tps[-1]].get("net"), "trail": c["trail"],
                                     "lift": c["chance"]["lift"], "lead_share": c["lead_share"],
                                     "lead_median": c["lead_median"], "coverage": c["coverage"], "new_n": c["new_n"]})
        done = []
        for why, c in picks.items():
            key = json.dumps(c["params"], sort_keys=True)
            if key in done:
                continue
            done.append(key)
            sigs = c["signals"]
            regime = btc_regime_table(klines, btc5m, [s["t"] for s in sigs])
            on = [s for s in sigs if (regime.get(s["t"]) or {}).get("shield") is True]
            off = [s for s in sigs if (regime.get(s["t"]) or {}).get("shield") is False]
            so, sf = stats([s["ev"][tp0] for s in on]), stats([s["ev"][tp0] for s in off])
            to = trail_stats([s["trail"] for s in on if s["trail"] is not None]); tf_ = trail_stats([s["trail"] for s in off if s["trail"] is not None])
            ch2 = chance_lift(sigs, store, tp=tps[-1], sample_n=args.chance_n, seed=args.seed + 1, sl=args.sl, cost=args.cost)
            fh = [s for s in sigs if s["t"] < split_ms]; sh = [s for s in sigs if s["t"] >= split_ms]
            half = {}
            for nm, g in (("ilk yarı", fh), ("ikinci yarı", sh)):
                st = stats([s["ev"][tp0] for s in g]) if g else {"n": 0}
                tr = trail_stats([s["trail"] for s in g if s["trail"] is not None])
                chh = chance_lift(g, store, tp=tp0, sample_n=min(len(g), 1000), seed=args.seed + 2, sl=args.sl, cost=args.cost) if len(g) >= 30 else {"n": 0, "lift": None, "null_hit": None}
                half[nm] = {"stats": st, "trail": tr, "chance": chh}
            lab = "net60 en iyi" if why == "net" else "şans-farkı en iyi"
            md += ["", f"### En iyi hücre — {lab}: `{c['params']}`",
                   f"- BTC kalkan KAPALI: n={sf.get('n', 0)} hit {_pct(sf.get('hit'))} net {sf.get('net', 0):+.2f}{_t(sf.get('t'))}, trailing {tf_.get('net', 0):+.2f} · "
                   f"kalkan AÇIK: n={so.get('n', 0)} hit {_pct(so.get('hit'))} net {so.get('net', 0):+.2f}{_t(so.get('t'))}, trailing {to.get('net', 0):+.2f}.",
                   f"- TP {tps[-1]:g} için şans farkı (null3, n={ch2['n']}): {_pp(ch2['lift'], ' pp')}.",
                   f"- Yarı-örnek (böl: {SPLIT_DAY}):",
                   "", "  | yarı | n | hit60 | net60 | trailing net | hit−şans |", "  |---|---|---|---|---|---|"]
            for nm, h in half.items():
                st = h["stats"]; chh = h["chance"]
                md.append(f"  | {nm} | {st.get('n', 0)} | {_pct(st.get('hit'))} | {st.get('net', 0):+.2f}{_t(st.get('t'))} | "
                          f"{h['trail'].get('net', 0):+.2f} | {_pp(chh['lift'], ' pp')} (n={chh['n']}) |")
            det_sum.setdefault("best", []).append({"why": why, "params": c["params"], "shield_on": so, "shield_off": sf,
                                                   "chance_tp2": ch2, "half": half})

        # LUNATRY
        md += ["", f"### LUNATRY sağlama — 17.10 01:05–01:55 (bar kapanış zamanı)", ""]
        if lun_info:
            md.append(f"LUNATRY 01:05 kapanışı {lun_info['px0105']}, 01:05–02:20 zirvesi {lun_info['peak']} "
                      f"({100 * (lun_info['peak'] / lun_info['px0105'] - 1):+.1f}%), 02:20 kapanışı {lun_info['px_last']}; "
                      f"01:05'te son 24 sa quote hacmi {lun_info['qv24_0105'] / 1e6:.2f}M TRY (filtre eşiği {args.min_quote / 1e6:.0f}M).")
            md.append("")
        md += ["| parametre | 5M filtreli: ateşledi mi | filtresiz: ateşledi mi |", "|---|---|---|"]
        lun_arr = lun1 if det["tf"] == "1m" else lun5
        lun_rows = []
        for c in cells:
            chk = lunatry_check(det, c["params"], lun_arr, btc, lun_w0, lun_w1, lun_end, args.min_quote)
            pstr = ", ".join(f"{k}={v}" for k, v in c["params"].items())
            if chk.get("ok") is None:
                md.append(f"| {pstr} | veri yok | veri yok |"); continue
            cols = []
            for label in ("5M filtreli", "filtresiz"):
                r = chk["res"][label]
                if r["fired"]:
                    cols.append(f"EVET {hhmm(r['t'])[6:]} · giriş {r['entry']:.4f} · sonrası zirve {r['peak_gain']:+.1f}%")
                elif r.get("late"):
                    cols.append(f"hayır (pencere sonrası {hhmm(r['late'])[6:]})")
                else:
                    cols.append("hayır")
            md.append(f"| {pstr} | {cols[0]} | {cols[1]} |")
            lun_rows.append({"params": c["params"], "res": chk["res"]})
        if det["tf"] == "1m":
            md.append("")
            md.append("(1 dk verisi veritabanında 16.10 ~20:00'de bitiyor; bu satır Binance public kline API'den çekilen LUNATRY 1m mumlarıyla hesaplandı.)")
        det_sum["lunatry"] = lun_rows
        summary["detectors"][det["name"]] = det_sum
        md_all += [""] + md
        # ara kayıt (uzun koşu için)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    header = [f"# Yeni erken-giriş dedektörleri — ızgara ({args.start} .. {args.end})", "",
              f"TP {', '.join(str(x) for x in tps)} / SL −{args.sl:g} / maliyet −{args.cost:g}; ufuk 60 dk; likidite 24s quote ≥ {args.min_quote / 1e6:.0f}M TRY; "
              f"sinyal soğuması 60 dk. Hız Avcısı karşılaştırma kümesi: rescan canlı-benzeri (rank ≤ {args.rank_max}, aşırı alım kapısı geçen) "
              f"{len(base)} satır / {len(base_eps_all)} bölüm. Şans tabanı: null3, ≥{args.chance_n} örnek. "
              f"Değerlendirme 5m mum deposu ile (1 dk sinyaller de) yapılır."]
    text = "\n".join(header + [""] + md_all) + "\n"
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"[strategy] bitti ({time.time() - t0:.0f} sn)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
