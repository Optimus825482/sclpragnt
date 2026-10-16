"""Merdiven yükseliş dedektörü — çevrimdışı ızgara ölçümü (2026-10-17).

`app.rescan.ladder.ladder_signals` prototipini `historical_candles` 5m üzerinde tüm sembollerde
koşturur; her parametre hücresi için:
  * sinyal sayısı, gün başına; hit60 / net60 (TP 1.5 ve 2.0; SL −3; maliyet −0.225) ve MFE/MAE,
  * ÖNCÜLÜK: sinyalden sonraki 90 dk içinde Hız Avcısı (rescan, canlı-benzeri: rank ≤ 10, aşırı alım
    kapısı geçen) adayı geldi mi; geldiyse kaç dk ÖNCE yakalandı (medyan),
  * KAPSAMA: Hız Avcısı bölümlerinin (60 dk) yüzde kaçından önce merdiven sinyali vardı,
  * YENİ YAKALAMA: ±90 dk içinde Hız Avcısı adayı olmayan sinyaller ve sonuçları.
En iyi hücre için BTC rejim kalkanı kırılımı ve şans tabanı (null3) verilir.
Canlı koda bağlanmaz, DB'ye yazmaz.

Kullanım (backend/):
  DATABASE_URL=... python scripts/ladder_rescan.py --jsonl work/rescan_21g_nogate.jsonl \
      --start 2026-09-26 --end 2026-10-16 --out work/ladder_rescan.md
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import ladder as L  # noqa: E402
from scripts.notification_outcomes_report import CandleStore, TZ, compute_chance  # noqa: E402
from scripts.radar_lift_analysis import wilson_interval  # noqa: E402
from scripts.radar_shield_rescan_analysis import (  # noqa: E402
    btc_regime_table, dedupe_horizon, is_overbought, load_btc_1h, load_btc_5m, load_jsonl, mark_episodes, parse_day,
)

_SQL = ("SELECT symbol, open_time, open::float8, high::float8, low::float8, close::float8, volume::float8, "
        "COALESCE(quote_volume, 0)::float8 FROM historical_candles WHERE timeframe='5m' AND open_time >= %s "
        "ORDER BY symbol, open_time")
GRID = {"n_bars": (3, 4), "gain_min": (0.8, 1.5), "vol_min": (1.0, 1.5), "rsi_max": (70.0, 80.0)}
LOOKAHEAD_MS = 90 * 60_000


def load_series(conn, since_ms: int) -> dict[str, np.ndarray]:
    acc: dict[str, list] = collections.defaultdict(list)
    for r in conn.execute(_SQL, (since_ms,)).fetchall():
        acc[r[0]].append([float(x) for x in r[1:]])
    return {s: np.array(v, dtype=float) for s, v in acc.items() if len(v) >= 300}


def stats(evals: list[dict]) -> dict:
    n = len(evals)
    if n == 0:
        return {"n": 0}
    hits = sum(1 for e in evals if e["hit"])
    net = np.array([e["net"] for e in evals])
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "hit": hits / n, "ci": wilson_interval(hits, n), "net": float(net.mean()),
            "t": float(net.mean()) / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None,
            "mfe": float(np.mean([e["mfe"] for e in evals])), "mae": float(np.mean([e["mae"] for e in evals]))}


def run_cell(series: dict[str, np.ndarray], store: CandleStore, params: dict, *, start_ms: int, end_ms: int,
             base_ticks: dict[str, np.ndarray], tps: list[float], sl: float, cost: float, min_quote: float) -> dict:
    sigs: list[dict] = []
    for sym, arr in series.items():
        idx = L.ladder_signals(arr, min_quote_24h=min_quote, **params)
        for i in idx:
            t = L.signal_time_ms(arr, int(i))
            if t < start_ms or t > end_ms:
                continue
            det = t / 1000.0; entry = float(arr[i, L.COL_C])
            ev = {tp: store.eval(sym, det, entry, tp, 60, sl, cost) for tp in tps}
            if any(v is None for v in ev.values()):
                continue
            bt = base_ticks.get(sym)
            lead = None; near = False
            if bt is not None and len(bt):
                j = int(np.searchsorted(bt, t, side="right"))
                if j < len(bt) and bt[j] - t <= LOOKAHEAD_MS:
                    lead = (bt[j] - t) / 60_000.0
                near = (j < len(bt) and bt[j] - t <= LOOKAHEAD_MS) or (j > 0 and t - bt[j - 1] <= LOOKAHEAD_MS)
            sigs.append({"sym": sym, "t": t, "entry": entry, "ev": ev, "lead": lead, "near": near})
    return {"params": params, "signals": sigs}


def coverage(base_eps: list[tuple[str, int]], sig_by_sym: dict[str, np.ndarray]) -> tuple[float | None, float | None]:
    """Hız Avcısı bölümlerinin kaçının 90 dk öncesinde merdiven sinyali var; medyan öncülük."""
    if not base_eps:
        return None, None
    hits = []; leads = []
    for sym, t in base_eps:
        st = sig_by_sym.get(sym)
        ok = False
        if st is not None and len(st):
            j = int(np.searchsorted(st, t, side="left")) - 1
            if j >= 0 and t - st[j] <= LOOKAHEAD_MS:
                ok = True; leads.append((t - st[j]) / 60_000.0)
        hits.append(ok)
    return float(np.mean(hits)), (float(np.median(leads)) if leads else None)


def chance_lift(sigs: list[dict], store: CandleStore, *, tp: float, sample_n: int, seed: int, sl: float, cost: float) -> dict:
    rng = np.random.default_rng(seed)
    pool = [s for s in sigs if s["sym"] in store.d]
    idx = rng.permutation(len(pool))[:sample_n]
    recs = []
    for i in idx:
        s = pool[int(i)]; det = s["t"] / 1000.0
        recs.append({"id": int(i), "sym": s["sym"], "tp": tp, "det": det, "hour": int(((det + 3 * 3600) // 3600) % 24), 60: s["ev"][tp]})
    compute_chance(recs, store, rng, sl=sl, cost=cost)
    lifts = []; null_hits = []
    for r in recs:
        nb = r.get("null3") or r.get("null2") or r.get("null")
        if nb:
            lifts.append(float(r[60]["hit"]) - float(nb["hit"])); null_hits.append(float(nb["hit"]))
    return {"n": len(lifts), "lift": float(np.mean(lifts)) if lifts else None, "null_hit": float(np.mean(null_hits)) if null_hits else None}


def _pct(v): return "—" if v is None else f"%{100 * v:.1f}"
def _mins(v, suffix=""): return "—" if v is None else f"{v:.0f}{suffix}"
def _t(v): return "" if v is None else f" (t {v:+.1f})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True); ap.add_argument("--btc-1h", default="work/btc_1h.json")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--cost", type=float, default=0.225); ap.add_argument("--sl", type=float, default=3.0)
    ap.add_argument("--tps", default="1.5,2.0"); ap.add_argument("--min-quote", type=float, default=5_000_000.0)
    ap.add_argument("--rank-max", type=int, default=10); ap.add_argument("--chance-n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7); ap.add_argument("--out", default="work/ladder_rescan.md")
    ap.add_argument("--json", default=""); ap.add_argument("--db-url", default="")
    ap.add_argument("--best-by", choices=("net", "hit"), default="net", help="ayrıntı verilecek hücre: net60 ya da hit60 en yüksek")
    args = ap.parse_args(argv)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    import psycopg
    t0 = time.time()
    tps = [float(x) for x in args.tps.split(",") if x.strip()]
    start_ms, end_ms = parse_day(args.start), parse_day(args.end, end=True)
    with psycopg.connect(url, connect_timeout=10) as conn:
        series = load_series(conn, start_ms - 26 * 3_600_000)
        btc5m = load_btc_5m(conn)
    store = CandleStore({s: (a[:, 0], a[:, 2], a[:, 3], a[:, 4]) for s, a in series.items()})
    print(f"[ladder] {len(series)} sembol yüklendi ({time.time() - t0:.0f} sn)")
    base_all = dedupe_horizon(load_jsonl(args.jsonl, start_ms, end_ms))
    base = [r for r in base_all if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= args.rank_max]
    mark_episodes(base)
    base_ticks = {s: np.array(sorted(int(r["tick_ms"]) for r in rs), dtype=np.int64)
                  for s, rs in itertools.groupby(sorted(base, key=lambda r: r["symbol"]), key=lambda r: r["symbol"])}
    base_eps = [(r["symbol"], int(r["tick_ms"])) for r in base if r.get("ep")]
    print(f"[ladder] Hız Avcısı canlı-benzeri {len(base)} satır, {len(base_eps)} bölüm")
    days = (end_ms - start_ms) / 86_400_000

    cells = []
    for combo in itertools.product(*GRID.values()):
        params = dict(zip(GRID.keys(), combo))
        cell = run_cell(series, store, params, start_ms=start_ms, end_ms=end_ms, base_ticks=base_ticks,
                        tps=tps, sl=args.sl, cost=args.cost, min_quote=args.min_quote)
        sigs = cell["signals"]
        sig_by_sym = {s: np.array(sorted(x["t"] for x in g), dtype=np.int64)
                      for s, g in itertools.groupby(sorted(sigs, key=lambda x: x["sym"]), key=lambda x: x["sym"])}
        cov, cov_lead = coverage(base_eps, sig_by_sym)
        leads = [s["lead"] for s in sigs if s["lead"] is not None]
        new = [s for s in sigs if not s["near"]]
        cell.update({"stats": {tp: stats([s["ev"][tp] for s in sigs]) for tp in tps},
                     "per_day": len(sigs) / days if days else None,
                     "lead_share": (len(leads) / len(sigs)) if sigs else None,
                     "lead_median": float(np.median(leads)) if leads else None,
                     "coverage": cov, "coverage_lead": cov_lead,
                     "new_n": len(new), "new_stats": {tp: stats([s["ev"][tp] for s in new]) for tp in tps}})
        cells.append(cell)
        print(f"[ladder] {params} n={len(sigs)} hit60@{tps[0]}={_pct(cell['stats'][tps[0]].get('hit'))} ({time.time() - t0:.0f} sn)")

    tp0 = tps[0]
    md = [f"# Merdiven yükseliş dedektörü — ızgara ({args.start} .. {args.end})",
          f"5m mumlar, {len(series)} sembol; TP {', '.join(str(x) for x in tps)} / SL −{args.sl:g} / maliyet −{args.cost:g}; ufuk 60 dk. "
          f"Likidite: 24s quote ≥ {args.min_quote / 1e6:.0f}M TRY. Hız Avcısı karşılaştırma kümesi: rescan canlı-benzeri "
          f"(rank ≤ {args.rank_max}, aşırı alım kapısı geçen) {len(base)} satır / {len(base_eps)} bölüm. Sinyal soğuması 60 dk.",
          "", f"| n_bars | gain_min | vol_min | rsi_max | sinyal | /gün | hit60@{tp0} [W95] | net60@{tp0} | hit60@{tps[-1]} | net60@{tps[-1]} | MFE | MAE | HA sonra geldi | öncülük medyan dk | HA bölüm kapsama | yeni yakalama n · hit |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        p = c["params"]; s0 = c["stats"][tp0]; s1 = c["stats"][tps[-1]]
        ci = s0.get("ci"); ci_s = f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}]" if ci else ""
        nn = c["new_stats"][tp0]
        md.append(f"| {p['n_bars']} | {p['gain_min']} | {p['vol_min']} | {p['rsi_max']:.0f} | {s0.get('n', 0)} | {c['per_day'] or 0:.0f} | "
                  f"{_pct(s0.get('hit'))}{ci_s} | {s0.get('net', 0):+.2f}{_t(s0.get('t'))} | {_pct(s1.get('hit'))} | {s1.get('net', 0):+.2f}{_t(s1.get('t'))} | "
                  f"{s0.get('mfe', 0):+.2f} | {s0.get('mae', 0):+.2f} | {_pct(c['lead_share'])} | "
                  f"{_mins(c['lead_median'])} | {_pct(c['coverage'])} | {c['new_n']} · {_pct(nn.get('hit'))} |")

    scored = [c for c in cells if c["stats"][tp0].get("n", 0) >= 100]
    best = max(scored, key=lambda c: c["stats"][tp0][args.best_by]) if scored else None
    summary = {"cells": [{"params": c["params"], "n": c["stats"][tp0].get("n", 0), "hit": c["stats"][tp0].get("hit"),
                          "net": c["stats"][tp0].get("net"), "lead_share": c["lead_share"], "lead_median": c["lead_median"],
                          "coverage": c["coverage"], "new_n": c["new_n"]} for c in cells]}
    if best:
        sigs = best["signals"]
        klines = load_btc_1h(args.btc_1h)
        regime = btc_regime_table(klines, btc5m, [s["t"] for s in sigs])
        on = [s["ev"][tp0] for s in sigs if (regime.get(s["t"]) or {}).get("shield") is True]
        off = [s["ev"][tp0] for s in sigs if (regime.get(s["t"]) or {}).get("shield") is False]
        ch = chance_lift(sigs, store, tp=tp0, sample_n=args.chance_n, seed=args.seed, sl=args.sl, cost=args.cost)
        so, sf = stats(on), stats(off)
        md += ["", f"## En iyi hücre ({args.best_by}60@{tp0}, n ≥ 100): {best['params']}",
               f"- Şans tabanı (null3, n={ch['n']}): hit60 {_pct(best['stats'][tp0]['hit'])} vs şans {_pct(ch['null_hit'])} → "
               f"**{100 * (ch['lift'] or 0):+.1f} pp**.",
               f"- BTC kalkan KAPALI: n={sf.get('n', 0)} hit {_pct(sf.get('hit'))} net {sf.get('net', 0):+.2f}{_t(sf.get('t'))} · "
               f"kalkan AÇIK: n={so.get('n', 0)} hit {_pct(so.get('hit'))} net {so.get('net', 0):+.2f}{_t(so.get('t'))}.",
               f"- Hız Avcısı adayı sinyalden sonra 90 dk içinde geldi: {_pct(best['lead_share'])}; öncülük medyanı "
               f"{_mins(best['lead_median'], ' dk')}. Hız Avcısı bölümlerinin {_pct(best['coverage'])}'i "
               f"merdiven sinyaliyle önceden yakalanmış (medyan {_mins(best['coverage_lead'], ' dk')} önce).",
               f"- Yeni yakalama (±90 dk'da HA adayı yok): n={best['new_n']}, hit60 {_pct(best['new_stats'][tp0].get('hit'))}, "
               f"net {best['new_stats'][tp0].get('net', 0):+.2f}{_t(best['new_stats'][tp0].get('t'))}."]
        summary["best"] = {"params": best["params"], "chance": ch, "shield_on": so, "shield_off": sf}
    md += ["", "## Sınırlar", "- 5m mumla prototip; canlı 1m akışında sinyal 1-4 dk daha erken olabilir.",
           "- Giriş = sinyal barının kapanışı, gecikmesiz; hedef sabit (adaya özel hedef yok).",
           "- 16 hücre: en iyi hücre seçimi iyimserlik taşır; yarı-örnek doğrulaması yapılmadı.",
           "- Hız Avcısı kümesi rescan ile yeniden üretilmiş; canlı adayların ~%90'ı."]
    text = "\n".join(md) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
