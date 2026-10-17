"""Erken-giriş dedektörleri Hız Avcısı (HA) adayının ÖZELLİĞİ olarak + ATR'ye göre hedef/stop ızgarası (2026-10-17).

`docs/YENI_STRATEJILER_2026-10-17.md` §7'nin 1. ve 3. maddesi. İki soru:

  (1) BAYRAK: canlı-benzeri HA adayları (rescan, rank ≤ 10, aşırı alım kapısı geçen, 60 dk bölüm tekilleştirme)
      içinde, aday anından önceki 90 dk'da `persist_1m_5mgrid` (M=12, g=1.0) ya da `ema_fan_5m` (k=2, g=1.5)
      sinyali olanların sonucu olmayanlardan farklı mı? (hit60/net60 TP = adayın target_pct, SL −3; MFE/MAE;
      null3 şans farkı; Wilson; Welch t; trend_devam alt kümesi; yarı-örnek; skor üçte-birlikleri × bayrak.)
  (2) ÇIKIŞ YAPISI: aynı adaylarda hedef = k × ATR14(5m)% (k ∈ {1, 1.5, 2}), stop = m × ATR (m ∈ {1, 1.5}),
      ufuk {15, 60} dk; ayrıca trailing (tetik 1,0 / iz 0,8 / SL −3 sabit; ve ATR ölçekli varyant). Her hücrede
      net ortalama, t, kazanan payı — tüm adaylar ve bayraklı alt kümeler.

Değerlendirme kuralları `notification_outcomes_report.eval_window` ile AYNI (yalnız tick'ten SONRA açılan 5m barlar,
TP/SL aynı barda ise SL önce, ufuk sonu kapanış, maliyet düşülür); burada N×12 matris üzerinde vektörel yeniden
kurulur ve TP=target/SL −3/60 dk hücresi `CandleStore.eval` ile birebir doğrulanır (uyuşmazlık sayısı yazılır).

Dedektörler bayrak için SOĞUMASIZ (cooldown_bars=1) koşturulur: "önceki 90 dk'da ham sinyal var mı" sorusu.
Canlı koda bağlanmaz, DB'ye yazmaz.

Kullanım (backend/):
  DATABASE_URL=... python scripts/ha_feature_lift.py --jsonl work/rescan_21g_nogate.jsonl \
      --start 2026-09-26 --end 2026-10-16 --out work/ha_feature_lift.md --json work/ha_feature_lift.json
"""
from __future__ import annotations

import argparse
import functools
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

from app.rescan import strategies as S  # noqa: E402
from app.rescan.ladder import COL_C, COL_H, COL_L, COL_OT, rolling_sum  # noqa: E402
from scripts.notification_outcomes_report import CandleStore, TZ  # noqa: E402
from scripts.radar_lift_analysis import wilson_interval  # noqa: E402
from scripts.radar_shield_rescan_analysis import (  # noqa: E402
    HEADER, _row, dedupe_horizon, group_stats, is_overbought, load_jsonl, mark_episodes, parse_day, run_chance, welch_t,
)
from scripts.strategy_rescan import SPLIT_DAY, liquid_symbols, load_1m, load_5m  # noqa: E402

FEATURES: dict[str, dict] = {
    "persist": {"label": "persist_1m_5mgrid (M=12, g=1,0)", "tf": "1m", "bar_ms": S.BAR_1M_MS,
                "fn": functools.partial(S.persist_1m, m=12, g_min=1.0, align_5m=True, cooldown_bars=1)},
    "ema_fan": {"label": "ema_fan_5m (k=2, g=1,5)", "tf": "5m", "bar_ms": S.BAR_5M_MS,
                "fn": functools.partial(S.ema_fan_5m, k=2, g_min=1.5, cooldown_bars=1)},
}
WINDOW_MIN = 90          # bayrak penceresi (dk)
WINDOW_SENS_MIN = 30     # duyarlılık: daha taze sinyal
K_BARS = 12              # 60 dk ufuk için en çok 12 × 5m bar
ATR_K = (1.0, 1.5, 2.0)
ATR_M = (1.0, 1.5)
HORIZONS = (15, 60)
TRAIL_TRIGGER, TRAIL_GAP = 1.0, 0.8
WARM_MS = 26 * 3_600_000  # dedektör ısınması (EMA99/24s likidite/1500 dk)


# ================================================================== saf yardımcılar (test edilir)
def signal_times(arr: np.ndarray, fn, bar_ms: int, min_quote: float) -> np.ndarray:
    """Dedektör sinyal anları (bar kapanışı, ms), artan sıralı."""
    idx = fn(arr, min_quote_24h=min_quote)
    if len(idx) == 0:
        return np.zeros(0, dtype=np.int64)
    return np.sort(arr[idx, COL_OT].astype(np.int64) + int(bar_ms))


def flag_prior_signal(ticks_ms, sig_times, window_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """Her aday tick'i için: tick'ten önce (≤ tick) ve `window_ms` içinde sinyal var mı; varsa öncülük (dk).

    Döner (flag: bool[N], lead_min: float[N]; bayraksızda NaN)."""
    ticks = np.asarray(ticks_ms, dtype=np.int64)
    sig = np.sort(np.asarray(sig_times, dtype=np.int64))
    if len(sig) == 0 or len(ticks) == 0:
        return np.zeros(len(ticks), dtype=bool), np.full(len(ticks), np.nan)
    j = np.searchsorted(sig, ticks, side="right") - 1
    ok = j >= 0
    last = sig[np.clip(j, 0, None)]
    gap = ticks - last
    flag = ok & (gap <= int(window_ms))
    return flag, np.where(flag, gap / 60_000.0, np.nan)


def atr14_pct(arr: np.ndarray) -> np.ndarray:
    """ATR14 (14 barlık basit TR ortalaması, `series.bar_features` ile aynı) / kapanış × 100; ilk 14 bar NaN."""
    h, l, c = arr[:, COL_H], arr[:, COL_L], arr[:, COL_C]
    n = len(c)
    out = np.full(n, np.nan)
    if n < 15:
        return out
    prev = np.empty(n); prev[0] = np.nan; prev[1:] = c[:-1]
    with np.errstate(invalid="ignore"):
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    tr[0] = np.nan
    atr = rolling_sum(np.nan_to_num(tr, nan=0.0), 14) / 14.0
    atr[:14] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(c > 0, atr / np.where(c > 0, c, 1.0) * 100.0, np.nan)


def last_closed_index(ot: np.ndarray, ticks_ms, bar_ms: int) -> np.ndarray:
    """tick anında kapanmış SON barın indeksi (open_time + bar_ms ≤ tick); yoksa −1."""
    return np.searchsorted(ot, np.asarray(ticks_ms, dtype=np.int64) - int(bar_ms), side="right") - 1


def build_windows(ot: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, ticks_ms,
                  k: int = K_BARS) -> dict[str, np.ndarray]:
    """Her tick için tick'ten SONRA açılan (open_time > tick) ilk `k` barın N×k matrisleri (eksik → NaN).

    `eval_window` ile aynı bar seçimi: forming bar (open_time == tick) kullanılmaz."""
    ticks = np.asarray(ticks_ms, dtype=np.int64)
    i0 = np.searchsorted(ot, ticks, side="right")
    idx = i0[:, None] + np.arange(k)[None, :]
    valid = idx < len(ot)
    idxc = np.clip(idx, 0, max(len(ot) - 1, 0))

    def pick(x):
        if len(x) == 0:
            return np.full(idx.shape, np.nan)
        return np.where(valid, x[idxc], np.nan)

    return {"ot": pick(ot.astype(float)), "hi": pick(hi), "lo": pick(lo), "cl": pick(cl)}


def horizon_mask(win_ot: np.ndarray, ticks_ms, H: int) -> tuple[np.ndarray, np.ndarray]:
    """(ok[N], inH[N×k]): ufuk içindeki barlar (open_time < tick + H dk) ve `eval_window` kapsama kuralı
    (ilk bar ≤ 10 dk içinde; bar sayısı ≥ max(1, H/5 − 3); son bar ≥ ufuk sonu − 10 dk)."""
    ticks = np.asarray(ticks_ms, dtype=np.int64)[:, None].astype(float)
    end = ticks + H * 60_000.0
    with np.errstate(invalid="ignore"):
        inH = np.isfinite(win_ot) & (win_ot < end)
    cnt = inH.sum(axis=1)
    first_ok = np.isfinite(win_ot[:, 0]) & ((win_ot[:, 0] - ticks[:, 0]) <= 600_000)
    last_ot = np.where(inH, win_ot, -np.inf).max(axis=1)
    ok = first_ok & (cnt >= max(1, int(H / 5) - 3)) & (last_ot >= end[:, 0] - 600_000)
    return ok, inH


def _first_true(m: np.ndarray, big: int) -> np.ndarray:
    return np.where(m.any(axis=1), np.argmax(m, axis=1), big)


def _masked(win: dict, inH: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (np.where(inH, win["hi"], np.nan), np.where(inH, win["lo"], np.nan), np.where(inH, win["cl"], np.nan))


def _last_close(cl: np.ndarray, inH: np.ndarray) -> np.ndarray:
    cnt = inH.sum(axis=1)
    return cl[np.arange(len(cl)), np.maximum(cnt - 1, 0)]


def exit_fixed(win: dict, inH: np.ndarray, entry, tp_pct, sl_pct, cost: float) -> dict[str, np.ndarray]:
    """Sabit TP/SL (yüzde; skaler ya da N'lik dizi) — `eval_window` ile aynı kural, vektörel.
    Tüm satırlar kapsama kuralını geçmiş olmalı (horizon_mask ok)."""
    hi, lo, cl = _masked(win, inH)
    N, K = hi.shape
    entry = np.asarray(entry, dtype=float).reshape(-1)
    tp = np.broadcast_to(np.asarray(tp_pct, dtype=float), (N,)).astype(float)
    sl = np.broadcast_to(np.asarray(sl_pct, dtype=float), (N,)).astype(float)
    big = K + 1
    with np.errstate(invalid="ignore"):
        tpm = hi >= (entry * (1 + tp / 100))[:, None]
        slm = lo <= (entry * (1 - sl / 100))[:, None]
        mfe = (np.nanmax(hi, axis=1) / entry - 1) * 100
        mae = (np.nanmin(lo, axis=1) / entry - 1) * 100
    itp, isl = _first_true(tpm, big), _first_true(slm, big)
    last = _last_close(cl, inH)
    ret = np.where((isl <= itp) & (isl < big), -sl, np.where(itp < big, tp, (last / entry - 1) * 100))
    return {"net": ret - cost, "hit": mfe >= tp, "mfe": mfe, "mae": mae,
            "outcome": np.where((isl <= itp) & (isl < big), -1, np.where(itp < big, 1, 0))}


def exit_trailing(win: dict, inH: np.ndarray, entry, trigger_pct, gap_pct, sl_pct, cost: float) -> dict[str, np.ndarray]:
    """`strategy_rescan.trail_window` ile aynı kural, vektörel: tetik görülene dek SL; tetikten sonra izleyen stop =
    ÖNCEKİ barların zirvesi × (1 − iz) (kötümser); ufuk sonunda kapanış."""
    hi, lo, cl = _masked(win, inH)
    N, K = hi.shape
    entry = np.asarray(entry, dtype=float).reshape(-1)
    trig = np.broadcast_to(np.asarray(trigger_pct, dtype=float), (N,)).astype(float)
    gap = np.broadcast_to(np.asarray(gap_pct, dtype=float), (N,)).astype(float)
    sl = np.broadcast_to(np.asarray(sl_pct, dtype=float), (N,)).astype(float)
    big = K + 1
    slp = entry * (1 - sl / 100); trp = entry * (1 + trig / 100)
    with np.errstate(invalid="ignore"):
        a = _first_true(hi >= trp[:, None], big)
        isl = _first_true(lo <= slp[:, None], big)
        cm = np.maximum.accumulate(np.nan_to_num(hi, nan=-np.inf), axis=1)
        stop = np.full((N, K), -np.inf)
        stop[:, 1:] = cm[:, :-1] * (1 - gap / 100)[:, None]
        cols = np.arange(K)[None, :]
        hit_stop = (cols > a[:, None]) & (lo <= stop)
    ks = _first_true(hit_stop, big)
    sl_exit = (isl < big) & (isl <= a)
    rows = np.arange(N)
    stop_px = stop[rows, np.minimum(ks, K - 1)]
    exit_px = np.where(sl_exit, slp, np.where(ks < big, stop_px, _last_close(cl, inH)))
    return {"net": (exit_px / entry - 1) * 100 - cost, "activated": a < big,
            "outcome": np.where(sl_exit, -1, np.where(ks < big, 2, 0))}


def cell_stats(net: np.ndarray, hit: np.ndarray | None = None) -> dict:
    net = np.asarray(net, dtype=float)
    net = net[np.isfinite(net)]
    n = len(net)
    if n == 0:
        return {"n": 0}
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    out = {"n": n, "net": float(net.mean()), "sd": sd, "win": float((net > 0).mean()),
           "t": float(net.mean()) / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None}
    if hit is not None:
        hit = np.asarray(hit, dtype=bool)
        out["hit"] = float(hit.mean()); out["ci"] = wilson_interval(int(hit.sum()), len(hit))
    return out


def tercile_labels(x: np.ndarray) -> np.ndarray:
    """0/1/2: alt/orta/üst üçte-birlik (NaN → −1)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), -1, dtype=int)
    f = np.isfinite(x)
    if f.sum() < 3:
        return out
    q1, q2 = np.quantile(x[f], [1 / 3, 2 / 3])
    out[f] = np.where(x[f] <= q1, 0, np.where(x[f] <= q2, 1, 2))
    return out


def hit_diff_ci(k1: int, n1: int, k0: int, n0: int) -> tuple[float, float] | None:
    """İki oran farkı (p1 − p0) için Wald %95 aralığı (n ≥ 30'da yeterli)."""
    if n1 == 0 or n0 == 0:
        return None
    p1, p0 = k1 / n1, k0 / n0
    se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    return (p1 - p0 - 1.96 * se, p1 - p0 + 1.96 * se)


# ================================================================== biçim
def _pct(v): return "—" if v is None else f"%{100 * v:.1f}"
def _t(v): return "" if v is None else f" (t {v:+.1f})"
def _pp(v): return "—" if v is None else f"{100 * v:+.1f} pp"
def _num(v, d=2): return "—" if v is None else f"{v:+.{d}f}"


def _ci(ci):
    return f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}]" if ci else ""


def hhmm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%d.%m %H:%M")


def compare_block(title: str, rows_on: list[dict], rows_off: list[dict], *, lead: list[float] | None = None) -> tuple[list[str], dict]:
    """Bayraklı vs bayraksız: HEADER tablosu + fark satırı (hit60 farkı Wald aralığı, Welch t, şans farkı farkı)."""
    g1, g0 = group_stats(rows_on), group_stats(rows_off)
    md = [f"\n### {title}", HEADER, _row("bayraklı", g1), _row("bayraksız", g0)]
    out = {"on": {k: v for k, v in g1.items() if k != "ci60"}, "off": {k: v for k, v in g0.items() if k != "ci60"}}
    if g1.get("n", 0) and g0.get("n", 0):
        k1 = int(round(g1["hit60"] * g1["n"])); k0 = int(round(g0["hit60"] * g0["n"]))
        dci = hit_diff_ci(k1, g1["n"], k0, g0["n"])
        wt = welch_t(g1, g0)
        dl = (g1["lift"] - g0["lift"]) if (g1.get("lift") is not None and g0.get("lift") is not None) else None
        lead_s = f"; bayraklı öncülük medyanı {np.median(lead):.0f} dk" if lead else ""
        md.append(f"\nFark (bayraklı − bayraksız): hit60 **{_pp(g1['hit60'] - g0['hit60'])}**"
                  f"{(' [' + f'{100 * dci[0]:+.1f}…{100 * dci[1]:+.1f}' + ']') if dci else ''}; "
                  f"net60 {_num(g1['net'] - g0['net'])} (Welch t {_num(wt, 2) if wt is not None else '—'}); "
                  f"şans farkı farkı {_pp(dl)}; bayraklı payı %{100 * g1['n'] / (g1['n'] + g0['n']):.1f}{lead_s}.")
        out.update({"hit_diff": g1["hit60"] - g0["hit60"], "hit_diff_ci": dci, "net_diff": g1["net"] - g0["net"],
                    "welch_t": wt, "lift_diff": dl, "share_on": g1["n"] / (g1["n"] + g0["n"]),
                    "lead_median": float(np.median(lead)) if lead else None})
    return md, out


# ================================================================== ana akış
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--cost", type=float, default=0.225); ap.add_argument("--sl", type=float, default=3.0)
    ap.add_argument("--min-quote", type=float, default=5_000_000.0)
    ap.add_argument("--rank-max", type=int, default=10); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--chance-n", type=int, default=0, help="şans tabanı örneklem (0 = tüm bölümler)")
    ap.add_argument("--out", default="work/ha_feature_lift.md"); ap.add_argument("--json", default="work/ha_feature_lift.json")
    ap.add_argument("--rows-out", default="work/ha_feature_rows.jsonl", help="aday başına bayrak/ATR/net satırları (boş = yazma)")
    ap.add_argument("--db-url", default="")
    ap.add_argument("--ema-k", type=int, default=2, help="ema_fan_5m k parametresi (duyarlılık: 3)")
    ap.add_argument("--persist-m", type=int, default=12, help="persist_1m_5mgrid M parametresi (duyarlılık: 8)")
    args = ap.parse_args(argv)
    FEATURES["ema_fan"]["fn"] = functools.partial(S.ema_fan_5m, k=args.ema_k, g_min=1.5, cooldown_bars=1)
    FEATURES["ema_fan"]["label"] = f"ema_fan_5m (k={args.ema_k}, g=1,5)"
    FEATURES["persist"]["fn"] = functools.partial(S.persist_1m, m=args.persist_m, g_min=1.0, align_5m=True, cooldown_bars=1)
    FEATURES["persist"]["label"] = f"persist_1m_5mgrid (M={args.persist_m}, g=1,0)"
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    import psycopg
    t0 = time.time()
    start_ms, end_ms = parse_day(args.start), parse_day(args.end, end=True)
    with psycopg.connect(url, connect_timeout=10) as conn:
        series5 = load_5m(conn, start_ms - WARM_MS)
        liq = liquid_symbols(series5, args.min_quote)
        series1 = load_1m(conn, liq, start_ms - WARM_MS)
    print(f"[ha-feat] 5m {len(series5)} sembol, 1m {len(series1)}/{len(liq)} likit sembol ({time.time() - t0:.0f} sn)")
    store = CandleStore({s: (a[:, 0], a[:, 2], a[:, 3], a[:, 4]) for s, a in series5.items()})

    # ---- HA canlı-benzeri adaylar (bölüm başı)
    base_all = dedupe_horizon(load_jsonl(args.jsonl, start_ms, end_ms))
    base = [r for r in base_all if not is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= args.rank_max]
    mark_episodes(base)
    eff_start = int(min(a[0, 0] for a in series5.values())) + WARM_MS
    rows = [r for r in base if r.get("ep") and r["symbol"] in store.d and int(r["tick_ms"]) >= eff_start]
    n_warm = sum(1 for r in base if r.get("ep")) - len(rows)
    print(f"[ha-feat] HA canlı-benzeri {len(base)} satır; bölüm {len(rows)} (ısınma/mumsuz atılan {n_warm})")

    # ---- sonuç (TP = target, SL −3) — skaler yol (şans tabanı ve group_stats için)
    for r in rows:
        det = int(r["tick_ms"]) / 1000.0; entry = float(r["price"]); tp = float(r["target_pct"])
        r["e60"] = store.eval(r["symbol"], det, entry, tp, 60, args.sl, args.cost)
        r["e15"] = store.eval(r["symbol"], det, entry, tp, 15, args.sl, args.cost)
    rows = [r for r in rows if r.get("e60")]
    print(f"[ha-feat] 60 dk sonucu olan bölüm {len(rows)} ({time.time() - t0:.0f} sn)")

    # ---- bayraklar
    by_sym: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_sym.setdefault(r["symbol"], []).append(i)
    N = len(rows)
    ticks = np.array([int(r["tick_ms"]) for r in rows], dtype=np.int64)
    flags: dict[str, dict] = {}
    for key, f in FEATURES.items():
        series = series1 if f["tf"] == "1m" else series5
        flag = np.zeros(N, dtype=bool); lead = np.full(N, np.nan); flag30 = np.zeros(N, dtype=bool)
        evaluable = np.zeros(N, dtype=bool)
        n_sig = 0
        for sym, ids in by_sym.items():
            arr = series.get(sym)
            if arr is None:
                continue
            ids = np.array(ids)
            # 1m verisi erken bitebilir: sembolün son barından sonraki tick'ler değerlendirilemez
            cover = ticks[ids] <= int(arr[-1, COL_OT]) + f["bar_ms"] + WINDOW_MIN * 60_000
            cover &= ticks[ids] >= int(arr[0, COL_OT]) + WARM_MS
            evaluable[ids[cover]] = True
            st = signal_times(arr, f["fn"], f["bar_ms"], args.min_quote)
            n_sig += len(st)
            fl, ld = flag_prior_signal(ticks[ids], st, WINDOW_MIN * 60_000)
            fl30, _ = flag_prior_signal(ticks[ids], st, WINDOW_SENS_MIN * 60_000)
            flag[ids] = fl & cover; lead[ids] = np.where(fl & cover, ld, np.nan); flag30[ids] = fl30 & cover
        flags[key] = {"flag": flag, "lead": lead, "flag30": flag30, "evaluable": evaluable, "n_sig": n_sig}
        print(f"[ha-feat] {f['label']}: ham sinyal {n_sig}, değerlendirilebilir aday {int(evaluable.sum())}, "
              f"bayraklı {int(flag.sum())} (%{100 * flag.sum() / max(1, evaluable.sum()):.1f}), 30 dk {int(flag30.sum())} ({time.time() - t0:.0f} sn)")

    # ---- şans tabanı (null3) — tüm bölümlerde
    for r in rows:
        r["ep"] = True
    done = run_chance(rows, store, sample_n=(args.chance_n or len(rows)), seed=args.seed, sl=args.sl, cost=args.cost)
    print(f"[ha-feat] şans tabanı {done}/{len(rows)} satır ({time.time() - t0:.0f} sn)")

    # ---- ATR14(5m) aday anında + pencere matrisleri
    atr = np.full(N, np.nan)
    win = {k: np.full((N, K_BARS), np.nan) for k in ("ot", "hi", "lo", "cl")}
    for sym, ids in by_sym.items():
        arr = series5[sym]; ids = np.array(ids)
        a = atr14_pct(arr)
        j = last_closed_index(arr[:, COL_OT].astype(np.int64), ticks[ids], S.BAR_5M_MS)
        okj = j >= 0
        atr[ids[okj]] = a[j[okj]]
        ot, hi, lo, cl = store.d[sym]
        w = build_windows(ot, hi, lo, cl, ticks[ids])
        for k in win:
            win[k][ids] = w[k]
    entry = np.array([float(r["price"]) for r in rows]); target = np.array([float(r["target_pct"]) for r in rows])
    ok60, in60 = horizon_mask(win["ot"], ticks, 60)
    ok15, in15 = horizon_mask(win["ot"], ticks, 15)
    # doğrulama: vektörel TP=target/SL/60 == store.eval
    chk = exit_fixed(win, in60, entry, target, args.sl, args.cost)
    mism = int(np.sum(ok60 & (np.abs(chk["net"] - np.array([r["e60"]["net"] for r in rows])) > 1e-6)))
    print(f"[ha-feat] vektörel/skaler uyuşmazlık: {mism} / {int(ok60.sum())} (ok60), ok15 {int(ok15.sum())}; "
          f"ATR14(5m)% medyan {np.nanmedian(atr):.3f} (çeyrekler {np.nanquantile(atr, 0.25):.3f}–{np.nanquantile(atr, 0.75):.3f})")

    # ---- çıkış ızgarası
    def grid(mask: np.ndarray) -> list[dict]:
        out = []
        m_atr = mask & np.isfinite(atr) & (atr > 0)
        for H in HORIZONS:
            okH, inH = (ok60, in60) if H == 60 else (ok15, in15)
            sel = m_atr & okH
            if sel.sum() == 0:
                continue
            w = {k: v[sel] for k, v in win.items()}; iH = inH[sel]; e = entry[sel]; a_ = atr[sel]
            for k_, m_ in itertools.product(ATR_K, ATR_M):
                r_ = exit_fixed(w, iH, e, k_ * a_, m_ * a_, args.cost)
                st = cell_stats(r_["net"], r_["hit"])
                st.update({"kind": "atr", "k": k_, "m": m_, "H": H, "tp_median": float(np.median(k_ * a_)),
                           "sl_median": float(np.median(m_ * a_))})
                out.append(st)
            # ATR ölçekli trailing: tetik 1×ATR, iz 0,8×ATR, SL 1,5×ATR
            r_ = exit_trailing(w, iH, e, 1.0 * a_, 0.8 * a_, 1.5 * a_, args.cost)
            st = cell_stats(r_["net"]); st.update({"kind": "trail_atr", "H": H, "activated": float(r_["activated"].mean())}); out.append(st)
            # referans: sabit hedef / sabit trailing
            sel2 = mask & okH
            w2 = {k: v[sel2] for k, v in win.items()}; iH2 = inH[sel2]; e2 = entry[sel2]; t2 = target[sel2]
            for lab, tp_, sl_ in (("target/SL3", t2, args.sl), ("TP2/SL1.5", 2.0, 1.5), ("TP1.5/SL1.5", 1.5, 1.5), ("TP1/SL1", 1.0, 1.0)):
                r_ = exit_fixed(w2, iH2, e2, tp_, sl_, args.cost)
                st = cell_stats(r_["net"], r_["hit"]); st.update({"kind": "fixed", "label": lab, "H": H}); out.append(st)
            r_ = exit_trailing(w2, iH2, e2, TRAIL_TRIGGER, TRAIL_GAP, args.sl, args.cost)
            st = cell_stats(r_["net"]); st.update({"kind": "trail_fixed", "H": H, "activated": float(r_["activated"].mean())}); out.append(st)
        return out

    all_mask = np.ones(N, dtype=bool)
    subsets = [("tüm adaylar", all_mask)]
    for key, f in FEATURES.items():
        subsets.append((f"bayraklı · {f['label']}", flags[key]["flag"]))
        subsets.append((f"bayraksız · {f['label']}", flags[key]["evaluable"] & ~flags[key]["flag"]))
    either = flags["persist"]["flag"] | flags["ema_fan"]["flag"]
    both = flags["persist"]["flag"] & flags["ema_fan"]["flag"]
    subsets.append(("bayraklı · ikisinden biri", either)); subsets.append(("bayraklı · ikisi birden", both))
    trend = np.array([(r.get("mode") or "") == "trend_devam" for r in rows])
    subsets.append(("trend_devam · tüm", trend))
    grids = {name: grid(m) for name, m in subsets}

    # ================================================================== rapor
    md: list[str] = []
    summary: dict = {"window": [args.start, args.end], "cost": args.cost, "sl": args.sl, "episodes": N,
                     "chance_rows": done, "vector_mismatch": mism, "atr_median": float(np.nanmedian(atr)),
                     "features": {}, "grids": {}}
    md.append(f"# Hız Avcısı adayı özelliği olarak erken-giriş bayrakları + ATR hedef/stop ızgarası ({args.start} .. {args.end})")
    md.append(f"Aday kaynağı `{os.path.basename(args.jsonl)}`: rank ≤ {args.rank_max}, aşırı alım kapısı geçen, 60 dk bölüm tekilleştirme, "
              f"ısınma sonrası ({hhmm(eff_start)}'den itibaren) ve 60 dk sonucu olan **{N} bölüm**. Mum: historical_candles 5m "
              f"({len(series5)} sembol); 1m {len(series1)} likit sembol. Net = TP / ilk SL −{args.sl:g} / ufuk sonu, −{args.cost:g} maliyet; "
              f"yalnız tick'ten sonra açılan 5m barlar (forming bar atlanır — `eval_window` ile aynı). Şans tabanı null3, {done} bölümde. "
              f"Bayrak = aday anından önceki {WINDOW_MIN} dk'da dedektörün (soğumasız) ham sinyali. "
              f"Vektörel/skaler uyuşmazlık {mism}/{int(ok60.sum())}.")

    split_ms = parse_day(SPLIT_DAY)
    score = np.array([float(r.get("velocity_score") or np.nan) for r in rows])
    terc = tercile_labels(score)
    md.append("\n## 1. Bayrak: bayraklı vs bayraksız HA adayları (TP = adayın target_pct, SL −3, 60 dk)")
    for key, f in FEATURES.items():
        fl = flags[key]; ev = fl["evaluable"]; on = fl["flag"]
        idx_on = np.flatnonzero(on); idx_off = np.flatnonzero(ev & ~on)
        feat_sum: dict = {"label": f["label"], "n_signals": fl["n_sig"], "evaluable": int(ev.sum()), "flagged": int(on.sum())}
        md.append(f"\n## 1.{list(FEATURES).index(key) + 1} {f['label']} — ham sinyal {fl['n_sig']}, değerlendirilebilir aday {int(ev.sum())}, "
                  f"bayraklı {int(on.sum())}")
        b, o = compare_block("Tüm adaylar", [rows[i] for i in idx_on], [rows[i] for i in idx_off],
                             lead=[float(fl["lead"][i]) for i in idx_on])
        md += b; feat_sum["all"] = o
        # 30 dk duyarlılık
        on30 = fl["flag30"]
        b, o = compare_block(f"Duyarlılık: {WINDOW_SENS_MIN} dk penceresi", [rows[i] for i in np.flatnonzero(on30)],
                             [rows[i] for i in np.flatnonzero(ev & ~on30)])
        md += b; feat_sum["w30"] = o
        # trend_devam
        b, o = compare_block("trend_devam alt kümesi", [rows[i] for i in idx_on if trend[i]], [rows[i] for i in idx_off if trend[i]])
        md += b; feat_sum["trend_devam"] = o
        b, o = compare_block("notr / v_donusu alt kümesi", [rows[i] for i in idx_on if not trend[i]], [rows[i] for i in idx_off if not trend[i]])
        md += b; feat_sum["other_modes"] = o
        # yarı-örnek
        md.append(f"\n### Yarı-örnek (böl: {SPLIT_DAY})")
        md.append("| yarı | küme | n | hit60 [W95] | net60 (t) | şansa göre | hit farkı | Welch t |")
        md.append("|---|---|---|---|---|---|---|---|")
        feat_sum["half"] = {}
        for nm, cond in (("ilk yarı", ticks < split_ms), ("ikinci yarı", ticks >= split_ms)):
            g1 = group_stats([rows[i] for i in idx_on if cond[i]]); g0 = group_stats([rows[i] for i in idx_off if cond[i]])
            wt = welch_t(g1, g0) if g1.get("n") and g0.get("n") else None
            for lab, g in (("bayraklı", g1), ("bayraksız", g0)):
                if g.get("n", 0) == 0:
                    md.append(f"| {nm} | {lab} | 0 | — | — | — | | |"); continue
                md.append(f"| {nm} | {lab} | {g['n']} | {_pct(g['hit60'])}{_ci(g.get('ci60'))} | {g['net']:+.2f}{_t(g.get('t'))} | "
                          f"{_pp(g.get('lift'))} (n={g.get('lift_n', 0)}) | "
                          f"{(_pp(g1['hit60'] - g0['hit60']) if lab == 'bayraklı' and g0.get('n') else '')} | "
                          f"{(_num(wt) if lab == 'bayraklı' and wt is not None else '')} |")
            feat_sum["half"][nm] = {"on": {k: v for k, v in g1.items() if k != "ci60"}, "off": {k: v for k, v in g0.items() if k != "ci60"}, "welch_t": wt}
        # skor üçte-birlikleri × bayrak (bonus sorusu: skorun açıkladığından fazlası var mı)
        md.append("\n### Skor üçte-birlikleri × bayrak (velocity_score)")
        md.append("| skor dilimi | bayraklı n · hit60 · net60 | bayraksız n · hit60 · net60 | hit farkı |")
        md.append("|---|---|---|---|")
        feat_sum["terciles"] = []
        for tcode, tname in ((0, "alt ⅓"), (1, "orta ⅓"), (2, "üst ⅓")):
            g1 = group_stats([rows[i] for i in idx_on if terc[i] == tcode]); g0 = group_stats([rows[i] for i in idx_off if terc[i] == tcode])
            if g1.get("n", 0) and g0.get("n", 0):
                md.append(f"| {tname} | {g1['n']} · {_pct(g1['hit60'])} · {g1['net']:+.2f} | {g0['n']} · {_pct(g0['hit60'])} · {g0['net']:+.2f} | "
                          f"{_pp(g1['hit60'] - g0['hit60'])} |")
            else:
                md.append(f"| {tname} | {g1.get('n', 0)} | {g0.get('n', 0)} | — |")
            feat_sum["terciles"].append({"tercile": tcode, "on": {k: v for k, v in g1.items() if k != "ci60"}, "off": {k: v for k, v in g0.items() if k != "ci60"}})
        summary["features"][key] = feat_sum

    # iki bayrak birleşimi
    ev_both = flags["persist"]["evaluable"] & flags["ema_fan"]["evaluable"]
    md.append("\n## 1.3 İki bayrağın birleşimi (iki dedektör için de değerlendirilebilir adaylar)")
    md.append(HEADER)
    summary["combo"] = {}
    for lab, m in (("hiçbiri", ev_both & ~either), ("yalnız persist", ev_both & flags["persist"]["flag"] & ~flags["ema_fan"]["flag"]),
                   ("yalnız ema_fan", ev_both & flags["ema_fan"]["flag"] & ~flags["persist"]["flag"]), ("ikisi birden", ev_both & both)):
        g = group_stats([rows[i] for i in np.flatnonzero(m)])
        md.append(_row(lab, g)); summary["combo"][lab] = {k: v for k, v in g.items() if k != "ci60"}

    # ızgara
    md.append("\n## 2. Çıkış yapısı ızgarası (hedef/stop = ATR14(5m)% katı; ufuk 15 / 60 dk)")
    md.append(f"ATR14(5m)% aday anında: medyan {np.nanmedian(atr):.3f}, çeyrekler {np.nanquantile(atr, 0.25):.3f}–{np.nanquantile(atr, 0.75):.3f}; "
              f"maliyet {args.cost:g} → 1×ATR hedef çoğu adayda maliyetin ~2 katı. 'kazanan' = net > 0. Referans satırları: adayın kendi hedefi/SL −3, "
              f"sabit TP/SL çiftleri ve trailing (tetik {TRAIL_TRIGGER:g} / iz {TRAIL_GAP:g} / SL −{args.sl:g}); 'trailing ATR' = tetik 1×ATR / iz 0,8×ATR / SL 1,5×ATR.")
    for name, cells in grids.items():
        if not cells:
            continue
        md.append(f"\n### {name} (n = {max(c.get('n', 0) for c in cells)})")
        md.append("| hücre | ufuk | n | hedef medyan % | stop medyan % | hit | net % (t) | kazanan |")
        md.append("|---|---|---|---|---|---|---|---|")
        for c in cells:
            if c.get("n", 0) == 0:
                continue
            if c["kind"] == "atr":
                lab = f"TP {c['k']:g}×ATR · SL {c['m']:g}×ATR"; tpm, slm = f"{c['tp_median']:.2f}", f"{c['sl_median']:.2f}"
            elif c["kind"] == "fixed":
                lab = f"sabit {c['label']}"; tpm = slm = "—"
            elif c["kind"] == "trail_atr":
                lab = f"trailing ATR (tetik %{100 * c['activated']:.0f} aktif)"; tpm = slm = "—"
            else:
                lab = f"trailing sabit {TRAIL_TRIGGER:g}/{TRAIL_GAP:g}/SL{args.sl:g} (tetik %{100 * c['activated']:.0f} aktif)"; tpm = slm = "—"
            md.append(f"| {lab} | {c['H']} | {c['n']} | {tpm} | {slm} | {_pct(c.get('hit'))} | **{c['net']:+.3f}**{_t(c.get('t'))} | {_pct(c['win'])} |")
        summary["grids"][name] = cells
    pos = [(name, c) for name, cells in grids.items() for c in cells if c.get("n", 0) >= 30 and c.get("net", -1) > 0]
    md.append("\n### Pozitif net hücreler (n ≥ 30)")
    if pos:
        for name, c in pos:
            md.append(f"- {name}: {c['kind']} {c.get('label') or ''} k={c.get('k')} m={c.get('m')} H={c['H']} → net {c['net']:+.3f}{_t(c.get('t'))}, n={c['n']}")
    else:
        md.append("- **Yok.** Hiçbir hücre/alt küme net pozitif değil.")
    summary["positive_cells"] = [{"subset": n, **c} for n, c in pos]

    md.append("\n## Sınırlar")
    md.append("- Forming bar (tick'in açtığı 5m bar) değerlendirme dışında (`eval_window` kuralı; tüm HA ölçümleriyle aynı) → ilk 5 dk'daki TP/SL görülmez, 15 dk ufku fiilen 2 bar.")
    md.append("- 1m verisi 16.10 ~20:00'de bitiyor; persist bayrağı yalnız 1m'si olan likit sembollerde ve o ana kadar değerlendirilebilir.")
    md.append("- Dedektörler soğumasız koşturuldu (ham sinyal); bağımsız sinyal ölçümündeki 60 dk soğumalı sayılarla birebir değil.")
    md.append("- Tek 20 günlük dönem; çoklu karşılaştırma (iki bayrak × alt kümeler × ızgara hücreleri) — tek t > 2 yeterli sayılmaz.")
    text = "\n".join(md) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")
    if args.rows_out:
        with open(args.rows_out, "w", encoding="utf-8") as fh:
            for i, r in enumerate(rows):
                fh.write(json.dumps({"symbol": r["symbol"], "tick_ms": int(r["tick_ms"]), "mode": r.get("mode"), "rank": r.get("rank"),
                                     "score": r.get("velocity_score"), "target_pct": r["target_pct"], "atr5m_pct": None if not np.isfinite(atr[i]) else float(atr[i]),
                                     "flag_persist": bool(flags["persist"]["flag"][i]), "flag_ema_fan": bool(flags["ema_fan"]["flag"][i]),
                                     "lead_persist": None if not np.isfinite(flags["persist"]["lead"][i]) else float(flags["persist"]["lead"][i]),
                                     "lead_ema_fan": None if not np.isfinite(flags["ema_fan"]["lead"][i]) else float(flags["ema_fan"]["lead"][i]),
                                     "hit60": bool(r["e60"]["hit"]), "net60": r["e60"]["net"], "lift": r.get("lift")}, ensure_ascii=False) + "\n")
    print(text)
    print(f"[ha-feat] bitti ({time.time() - t0:.0f} sn)")
    return 0


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())
