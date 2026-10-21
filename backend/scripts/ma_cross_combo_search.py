"""MA kesişimi kombinasyon araması — "süreyi kısaltıp en az %2 hedefle kârlı olan var mı?" (2026-10-21).

Önceki ölçümler (docs/MA_BUY_*): SMA 7/20/99 kesişimi, hangi çıkış/filtreyle olursa olsun işlem başına ≈ −maliyet. Bu betik
aramayı sistematik yapar ve örneklem içi / dışı ayırır ki "en iyi" kombinasyon şans eseri bulunmuş olmasın:
  * EVREN   : canlı sistem mantığı (her 10 dk 24 sa yükselenler ilk N + saatlik aktivite filtresi; runtime_config'ten okunur).
  * GİRİŞ   : TF × MA üçlüsü × kesişim kuralı (hızlı×orta ve ikisi yavaşın üstünde / yalnız hızlı×orta / orta×yavaş). Sinyal mumu
              kapanışında sembol taranan kümedeyse sayılır; giriş = kapanış fiyatı.
  * ÇIKIŞ   : hedef {2, 2.5, 3} × stop {1, 1.5, 2, 3, 4} × tutma {30…240 dk} × iz süren stop {yok, 1/0.5, 1.5/0.75, 2/1}.
              1 dakikalık mumlarla, aynı mumda stop ve hedef görülürse STOP (kötümser); iz süren stop bir önceki mumun tepesinden.
              Maliyet: gidiş-dönüş komisyon (BNB indirimli taker ×2) + kayma ×2.
  * FİLTRE  : sinyal anındaki özellikler (StochRSI, RSI, ADX, gövde, hacim oranı, yavaş MA eğimi, yavaşa uzaklık, MACD hist) tek ve
              ikili maskeler olarak; çıkış sonucu filtreden bağımsız olduğu için her maske ucuz değerlendirilir.
  * ÖLÇÜ    : ilk 60 gün EĞİTİM (en iyi burada seçilir), son 30 gün TEST (seçim sonrası tek sefer bakılır).
              Aynı sembolde `tutma` süresi dolmadan gelen ikinci sinyal atlanır (canlıda sembol başına tek pozisyon).

ADIMLAR / ÖNBELLEK: evren zaman çizelgesi ve TF mumları `work/ma_cross_search_cache.pkl`e yazılır (ikinci koşu hızlı).

KULLANIM:
    python backend/scripts/ma_cross_combo_search.py --days 90 --test-days 30
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import itertools
import json
import os
import pickle
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database, ma_buy_rules, ma_buy_signals, ma_buy_tracker, ma_buy_replay_universe as uni   # noqa: E402
from app.binance_tr_public import trading_symbols                                                          # noqa: E402
from app.config import config                                                                              # noqa: E402
from app.ma_buy_notify import tf_label                                                                     # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
WORK_DIR = os.path.join(ROOT, "work")
CACHE_TPL = os.path.join(WORK_DIR, "ma_cross_search_cache_{days}.pkl")
TZ = dt.timezone(dt.timedelta(hours=3))
DAY_MS = 86_400_000
M15_MS = 900_000
MAXW = 240                      # en uzun tutma (dk) → 1 dk pencere genişliği
TFS = ("5m", "15m", "30m", "1h")
TRIPLES = ((7, 20, 99), (5, 13, 50), (9, 21, 55), (10, 30, 100), (3, 8, 21), (8, 34, 89))
RULES = ("ribbon", "fast_mid", "mid_slow")            # ribbon: hızlı×orta yukarı ve ikisi yavaşın üstünde
TARGETS = (2.0, 2.5, 3.0)
STOPS = (1.0, 1.5, 2.0, 3.0, 4.0)
HOLDS = (30, 60, 90, 120, 180, 240)
TRAILS = ((0.0, 0.0), (1.0, 0.5), (1.5, 0.75), (2.0, 1.0))
MIN_TRAIN, MIN_TEST = 60, 25


# ------------------------------------------------------------------------------------------------- veri / evren
async def rows_for(symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    base = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "15m", "1h": "15m"}[tf]
    rows = uni.db_rows_to_klines(await database.get_market_candles(symbol, base, start_ms=start_ms, end_ms=end_ms))
    return rows if base == tf else uni.aggregate_klines(rows, M15_MS, ma_buy_tracker.SUPPORTED_TF_MS[tf])


def bars_array(rows, tf_ms: int, now_ms: int) -> dict:
    """closed_bars → numpy sütunları (+ hacim, row[5])."""
    vol = {}
    for r in rows or []:
        try:
            vol[int(r[0])] = float(r[5])
        except (TypeError, ValueError, IndexError):
            pass
    bars = ma_buy_tracker.closed_bars(rows, tf_ms, now_ms)
    cols = {k: np.array([b[k] for b in bars], dtype=np.float64) for k in ("open", "high", "low", "close")}
    cols["open_ms"] = np.array([b["open_ms"] for b in bars], dtype=np.int64)
    cols["volume"] = np.array([vol.get(b["open_ms"], 0.0) for b in bars], dtype=np.float64)
    return cols


async def build_cache(days: int, now_ms: int, universe_mode: str = "live") -> dict:
    """universe_mode: live (canlı seçim), liquid (24 sa hacmi ≥ eşik olan tüm çiftler), decliners (likitler içinde en çok düşen N)."""
    start_ms = now_ms - days * DAY_MS
    t0 = start_ms - 8 * DAY_MS
    runtime = json.loads(await database.get_llm_setting("runtime_config", "{}") or "{}")
    uni.apply_runtime_overrides(runtime)
    settings = uni.selection_settings()
    universe = sorted(await trading_symbols("TRY"))
    limit = int(settings["TOP_GAINERS_LIMIT"])
    gainer_period = int(settings["TOP_GAINERS_REFRESH_SEC"]) * 1000
    activity_period = int(settings["SYMBOL_ACTIVITY_REFRESH_SEC"]) * 1000
    gainer_marks = uni.refresh_marks(start_ms - activity_period, now_ms, gainer_period)
    activity_marks = uni.refresh_marks(start_ms, now_ms, activity_period, offset_ms=20_000)
    print(f"evren: {len(universe)} çift, ilk {limit} yükselen, {days} gün", file=sys.stderr)
    stats_by_mark: list[dict] = [dict() for _ in gainer_marks]
    for n, symbol in enumerate(universe, 1):
        p5 = uni.parse_rows(await rows_for(symbol, "5m", t0, now_ms))
        for i, st in enumerate(uni.ticker_stats_series(p5, gainer_marks)):
            if st is not None:
                stats_by_mark[i][symbol] = st
        if n % 50 == 0:
            print(f"  5m ticker: {n}/{len(universe)}", file=sys.stderr)
    if universe_mode != "live":
        min_qv = float(settings.get("SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY") or 1_000_000)
        timeline = []
        for t, stats in zip(gainer_marks, stats_by_mark):
            liquid = {s: st for s, st in stats.items() if float(st.get("quote_volume", 0.0)) >= min_qv}
            if universe_mode == "liquid":
                members = set(liquid)
            else:   # decliners: likitler içinde 24 sa değişimi en düşük `limit` çift
                members = set(sorted(liquid, key=lambda s: float(liquid[s].get("change_pct", 0.0)))[:limit])
            timeline.append({"at_ms": t, "members": members})
        return await _finish_cache(days, now_ms, start_ms, t0, settings, len(universe), timeline, universe_mode)
    tracked_by_amark = []
    for t in activity_marks:
        gi = bisect_left(gainer_marks, t + 1) - 1
        tracked_by_amark.append(uni.rank_top_gainers(stats_by_mark[gi], limit) if gi >= 0 else [])
    need: dict[str, set] = defaultdict(set)
    for i, syms in enumerate(tracked_by_amark):
        for s in syms:
            need[s].add(i)
    active: dict[str, set] = defaultdict(set)
    for n, symbol in enumerate(sorted(need), 1):
        p5 = uni.parse_rows(await rows_for(symbol, "5m", t0, now_ms))
        p1 = uni.parse_rows(await rows_for(symbol, "1m", start_ms - DAY_MS, now_ms))
        marks = sorted(need[symbol])
        for i, st in zip(marks, uni.ticker_stats_series(p5, [activity_marks[i] for i in marks])):
            t = activity_marks[i]
            res = uni.activity_status(uni.history_upto(p5, t, uni.M5_HISTORY_BARS), uni.history_upto(p1, t, uni.M1_HISTORY_BARS),
                                      quote_volume=(st or {}).get("quote_volume", 0.0), now_ms=t)
            if res["status"] == "ACTIVE":
                active[symbol].add(i)
        if n % 50 == 0 or n == len(need):
            print(f"  aktivite: {n}/{len(need)}", file=sys.stderr)
    timeline = []
    for i, t in enumerate(activity_marks):
        act = {s for s in tracked_by_amark[i] if i in active[s]}
        timeline.append({"at_ms": t, "members": act if act else set(tracked_by_amark[i])})
    return await _finish_cache(days, now_ms, start_ms, t0, settings, len(universe), timeline, universe_mode)


async def _finish_cache(days, now_ms, start_ms, t0, settings, n_universe, timeline, universe_mode) -> dict:
    scan_symbols = sorted(uni.symbols_ever(s["members"] for s in timeline))
    tf_bars = {}
    for n, symbol in enumerate(scan_symbols, 1):
        for tf in TFS:
            tf_bars[(symbol, tf)] = bars_array(await rows_for(symbol, tf, t0, now_ms), ma_buy_tracker.SUPPORTED_TF_MS[tf], now_ms)
        if n % 50 == 0 or n == len(scan_symbols):
            print(f"  TF mumları: {n}/{len(scan_symbols)}", file=sys.stderr)
    return {"days": days, "now_ms": now_ms, "start_ms": start_ms, "settings": settings, "n_universe": n_universe,
            "universe_mode": universe_mode, "timeline": timeline, "scan_symbols": scan_symbols, "tf_bars": tf_bars,
            "avg_members": statistics.fmean(len(s["members"]) for s in timeline)}


class Membership:
    def __init__(self, timeline):
        self.at = [int(s["at_ms"]) for s in timeline]
        self.members = [s["members"] for s in timeline]

    def has(self, symbol: str, t_ms: int) -> bool:
        i = bisect_right(self.at, int(t_ms)) - 1
        return i >= 0 and symbol in self.members[i]


# ------------------------------------------------------------------------------------------------- sinyal + özellik
def _np(series) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in series], dtype=np.float64)


def signal_sets_for_symbol(symbol: str, tf: str, b: dict, member: Membership, start_ms: int) -> dict:
    """{(triple, rule): [(bar_index, close_ms)]} + ortak özellik dizileri (bar bazında)."""
    tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
    closes = b["close"]
    n = len(closes)
    if n < 120:
        return {}, {}
    close_list = closes.tolist()
    bars_dicts = [{"high": h, "low": l, "close": c} for h, l, c in zip(b["high"], b["low"], closes)]
    feats = {
        "stoch": _np(ma_buy_signals.stoch_rsi_k(close_list)),
        "rsi": _np(ma_buy_signals.rsi_series(close_list, 14)),
        "adx": _np(ma_buy_rules.adx_series(bars_dicts, 14)),
        "macd_hist": _np(ma_buy_rules.macd_hist_series(close_list)),
        "body_pct": (closes - b["open"]) / np.where(b["open"] > 0, b["open"], np.nan) * 100.0,
    }
    vol = b["volume"]
    vavg = np.full(n, np.nan)
    cs = np.cumsum(np.insert(vol, 0, 0.0))
    vavg[20:] = (cs[20:-1] - cs[:-21]) / 20.0           # önceki 20 mumun ortalaması (sinyal mumu hariç)
    feats["vol_ratio"] = vol / np.where(vavg > 0, vavg, np.nan)
    rng = (b["high"] - b["low"]) / np.where(closes > 0, closes, np.nan) * 100.0
    atr14 = np.full(n, np.nan)
    cr = np.cumsum(np.insert(np.nan_to_num(rng), 0, 0.0))
    atr14[13:] = (cr[14:] - cr[:-14]) / 14.0
    feats["atr_pct"] = atr14
    close_ms = b["open_ms"] + tf_ms
    sets: dict = {}
    smas = {}
    for p in sorted({p for t in TRIPLES for p in t}):
        smas[p] = _np(ma_buy_signals.sma_series(close_list, p))
    for triple in TRIPLES:
        f, m, s = (smas[p] for p in triple)
        slope5 = np.full(n, np.nan)
        slope5[5:] = (s[5:] - s[:-5]) / np.where(s[:-5] > 0, s[:-5], np.nan) * 100.0
        dist = (closes - s) / np.where(s > 0, s, np.nan) * 100.0
        ok_fm = np.zeros(n, dtype=bool)
        ok_fm[1:] = (f[:-1] <= m[:-1]) & (f[1:] > m[1:])
        ok_ms = np.zeros(n, dtype=bool)
        ok_ms[1:] = (m[:-1] <= s[:-1]) & (m[1:] > s[1:])
        above = (f > s) & (m > s)
        for rule in RULES:
            mask = {"ribbon": ok_fm & above, "fast_mid": ok_fm, "mid_slow": ok_ms}[rule]
            idx = np.flatnonzero(mask & ~np.isnan(s))
            sig = [(int(i), int(close_ms[i])) for i in idx if close_ms[i] >= start_ms and member.has(symbol, int(close_ms[i]))]
            if sig:
                sets[(triple, rule)] = (sig, slope5, dist)
    return sets, feats


FEATURE_NAMES = ("stoch", "rsi", "adx", "macd_hist", "macd_hist_prev", "body_pct", "vol_ratio", "atr_pct", "slow_slope", "dist_slow", "hour")


PULLBACK_PCT = 0.0          # >0: giriş = kapanış×(1−x/100) limit emri; PULLBACK_WAIT dk içinde dolmazsa işlem yok
PULLBACK_WAIT = 15


def windows_for(sig_close_ms: list[int], m1: dict, tf_bars_close: np.ndarray, entries: np.ndarray) -> np.ndarray:
    """Her sinyal için giriş fiyatına normalize (yüksek, düşük, kapanış) 1 dk penceresi [n, 3, MAXW]; eksik → NaN.
    PULLBACK_PCT > 0 ise limit emir: ilk PULLBACK_WAIT dakikada düşük ≤ seviye olan ilk mumda dolum, pencere o mumdan SONRA başlar."""
    ot = m1["open_ms"]
    out = np.full((len(sig_close_ms), 3, MAXW), np.nan, dtype=np.float32)
    for k, (t, e) in enumerate(zip(sig_close_ms, entries)):
        i0 = int(np.searchsorted(ot, t))
        if PULLBACK_PCT > 0 and e > 0:
            level = e * (1.0 - PULLBACK_PCT / 100.0)
            lows = m1["low"][i0: i0 + PULLBACK_WAIT]
            hit = np.flatnonzero(lows <= level)
            if len(hit) == 0:
                continue
            i0 = i0 + int(hit[0]) + 1
            e = level
        i1 = min(i0 + MAXW, len(ot))
        if i1 - i0 < 10 or e <= 0:
            continue
        out[k, 0, : i1 - i0] = m1["high"][i0:i1] / e
        out[k, 1, : i1 - i0] = m1["low"][i0:i1] / e
        out[k, 2, : i1 - i0] = m1["close"][i0:i1] / e
    return out


# ------------------------------------------------------------------------------------------------- vektörel çıkış
def simulate(W: np.ndarray, tp: float, sl: float, hold: int, trig: float, gap: float, cost_pct: float) -> np.ndarray:
    """W: [n,3,MAXW] oranlar. Dönen: net % (NaN = veri yok)."""
    n = W.shape[0]
    H, L, C = W[:, 0, :], W[:, 1, :], W[:, 2, :]
    exit_r = np.full(n, np.nan)
    done = np.zeros(n, dtype=bool)
    peak = np.ones(n)
    tstop = np.full(n, 1.0 - sl / 100.0)
    tp_lvl = 1.0 + tp / 100.0
    last_close = np.full(n, np.nan)
    steps = min(hold, MAXW)
    for t in range(steps):
        h, l, c = H[:, t], L[:, t], C[:, t]
        valid = ~np.isnan(c) & ~done
        last_close = np.where(valid, c, last_close)
        hit_stop = valid & (l <= tstop)
        exit_r = np.where(hit_stop, tstop, exit_r)
        done |= hit_stop
        hit_tp = valid & ~hit_stop & (h >= tp_lvl)
        exit_r = np.where(hit_tp, tp_lvl, exit_r)
        done |= hit_tp
        peak = np.where(valid & ~done, np.maximum(peak, h), peak)
        if trig > 0:
            active = peak >= 1.0 + trig / 100.0
            tstop = np.where(active, np.maximum(tstop, peak * (1.0 - gap / 100.0)), tstop)
    timeout = ~done & ~np.isnan(last_close)
    exit_r = np.where(timeout, last_close, exit_r)
    return (exit_r - 1.0) * 100.0 - cost_pct


# ------------------------------------------------------------------------------------------------- ana akış
def dedup_mask(symbols: np.ndarray, close_ms: np.ndarray, hold_min: int) -> np.ndarray:
    """Sembol başına tek pozisyon: önceki alınan sinyalin tutma süresi dolmadan gelen sinyal atlanır."""
    keep = np.zeros(len(symbols), dtype=bool)
    last: dict = {}
    order = np.argsort(close_ms, kind="stable")
    for i in order:
        s = symbols[i]
        if s not in last or close_ms[i] >= last[s] + hold_min * 60_000:
            keep[i] = True
            last[s] = close_ms[i]
    return keep


def filter_masks(F: dict) -> dict:
    singles = {
        "yok": np.ones(len(F["rsi"]), dtype=bool),
        "StochRSI≤80": ~(F["stoch"] > 80),
        "StochRSI≤50": ~(F["stoch"] > 50),
        "RSI 45–65": (F["rsi"] >= 45) & (F["rsi"] <= 65),
        "RSI<70": F["rsi"] < 70,
        "ADX>20": F["adx"] > 20,
        "ADX>25": F["adx"] > 25,
        "gövde≥0.3%": F["body_pct"] >= 0.3,
        "gövde≥1%": F["body_pct"] >= 1.0,
        "hacim≥1.5×": F["vol_ratio"] >= 1.5,
        "hacim≥2×": F["vol_ratio"] >= 2.0,
        "yavaş MA yükseliyor": F["slow_slope"] > 0,
        "yavaşa uzaklık≤2%": F["dist_slow"] <= 2.0,
        "yavaşa uzaklık≤1%": F["dist_slow"] <= 1.0,
        "MACD hist artıyor": F["macd_hist"] > F["macd_hist_prev"],
        "ATR14≥0.6%": F["atr_pct"] >= 0.6,
        "saat 09–23": (F["hour"] >= 9) & (F["hour"] <= 23),
    }
    masks = dict(singles)
    names = [k for k in singles if k != "yok"]
    for a, b in itertools.combinations(names, 2):
        masks[f"{a} + {b}"] = singles[a] & singles[b]
    return masks


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--test-days", type=int, default=30)
    ap.add_argument("--rebuild-cache", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--targets", default=None, help="virgülle hedef %% listesi (varsayılan 2,2.5,3)")
    ap.add_argument("--stops", default=None, help="virgülle stop %% listesi")
    ap.add_argument("--holds", default=None, help="virgülle tutma dk listesi (en büyüğü pencere genişliği olur)")
    ap.add_argument("--universe", choices=("live", "liquid", "decliners"), default="live")
    ap.add_argument("--pullback", type=float, default=0.0, help="limit giriş: kapanışın %% kaç altından (0 = piyasa, kapanış)")
    ap.add_argument("--pullback-wait", type=int, default=15)
    args = ap.parse_args()
    global TARGETS, STOPS, HOLDS, MAXW, PULLBACK_PCT, PULLBACK_WAIT
    if args.targets:
        TARGETS = tuple(float(x) for x in args.targets.split(","))
    if args.stops:
        STOPS = tuple(float(x) for x in args.stops.split(","))
    if args.holds:
        HOLDS = tuple(int(x) for x in args.holds.split(","))
        MAXW = max(HOLDS)
    PULLBACK_PCT, PULLBACK_WAIT = float(args.pullback), int(args.pullback_wait)
    os.makedirs(WORK_DIR, exist_ok=True)
    CACHE = CACHE_TPL.format(days=f"{args.days}g{'' if args.universe == 'live' else '_' + args.universe}")
    if os.path.exists(CACHE) and not args.rebuild_cache:
        with open(CACHE, "rb") as fh:
            cache = pickle.load(fh)
        print(f"önbellek: {CACHE} ({cache['days']} gün, {len(cache['scan_symbols'])} sembol)", file=sys.stderr)
    else:
        cache = await build_cache(args.days, int(time.time() * 1000), args.universe)
        with open(CACHE, "wb") as fh:
            pickle.dump(cache, fh, protocol=pickle.HIGHEST_PROTOCOL)
    now_ms, start_ms = cache["now_ms"], cache["start_ms"]
    split_ms = now_ms - args.test_days * DAY_MS
    member = Membership(cache["timeline"])
    cost_pct = 100.0 * (2 * float(config.effective_commission_pct()) + 2 * float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025)))

    # --- sinyaller + pencereler (sembol başına 1 dk verisi bir kez okunur)
    per_set: dict = defaultdict(lambda: {"symbol": [], "close_ms": [], "W": [], "F": defaultdict(list)})
    t_start = time.time()
    for n, symbol in enumerate(cache["scan_symbols"], 1):
        m1_rows = await database.get_market_candles(symbol, "1m", start_ms=start_ms - DAY_MS, end_ms=now_ms)
        m1 = {"open_ms": np.array([int(r["open_time"]) for r in m1_rows], dtype=np.int64),
              "high": np.array([float(r["high"]) for r in m1_rows]), "low": np.array([float(r["low"]) for r in m1_rows]),
              "close": np.array([float(r["close"]) for r in m1_rows])}
        if len(m1["open_ms"]) < 1000:
            continue
        for tf in TFS:
            b = cache["tf_bars"][(symbol, tf)]
            sets, feats = signal_sets_for_symbol(symbol, tf, b, member, start_ms)
            for (triple, rule), (sig, slope5, dist) in sets.items():
                idx = np.array([i for i, _ in sig]); cms = [t for _, t in sig]
                entries = b["close"][idx]
                W = windows_for(cms, m1, b["close"], entries)
                d = per_set[(tf, triple, rule)]
                d["symbol"] += [symbol] * len(sig); d["close_ms"] += cms; d["W"].append(W)
                for k in ("stoch", "rsi", "adx", "macd_hist", "body_pct", "vol_ratio", "atr_pct"):
                    d["F"][k].append(feats[k][idx])
                d["F"]["macd_hist_prev"].append(feats["macd_hist"][np.maximum(idx - 1, 0)])
                d["F"]["slow_slope"].append(slope5[idx]); d["F"]["dist_slow"].append(dist[idx])
                d["F"]["hour"].append(np.array([dt.datetime.fromtimestamp(t / 1000, TZ).hour for t in cms], dtype=np.float64))
        if n % 25 == 0 or n == len(cache["scan_symbols"]):
            print(f"  sinyal/pencere: {n}/{len(cache['scan_symbols'])} ({time.time()-t_start:.0f} sn)", file=sys.stderr)

    # --- arama
    all_train_means: list[float] = []
    results = []          # yalnız eğitimde artı olanlar saklanır; (train_mean, test_mean, n_train, n_test, train_win, test_win, tf, triple, rule, tp, sl, hold, trail, filter)
    combos = list(itertools.product(TARGETS, STOPS, HOLDS, TRAILS))
    t_start = time.time()
    for si, (key, d) in enumerate(sorted(per_set.items()), 1):
        tf, triple, rule = key
        symbols = np.array(d["symbol"]); close_ms = np.array(d["close_ms"], dtype=np.int64)
        W = np.concatenate(d["W"], axis=0)
        F = {k: np.concatenate(v) for k, v in d["F"].items()}
        masks = filter_masks(F)
        is_train = close_ms < split_ms
        dedups = {h: dedup_mask(symbols, close_ms, h) for h in HOLDS}
        for tp, sl, hold, (trig, gap) in combos:
            net = simulate(W, tp, sl, hold, trig, gap, cost_pct)
            base = ~np.isnan(net) & dedups[hold]
            for fname, fm in masks.items():
                m = base & fm
                tr, te = m & is_train, m & ~is_train
                ntr, nte = int(tr.sum()), int(te.sum())
                if ntr < MIN_TRAIN or nte < MIN_TEST:
                    continue
                a, b_ = net[tr], net[te]
                tm = float(a.mean())
                all_train_means.append(tm)
                if tm <= 0:
                    continue
                results.append((float(a.mean()), float(b_.mean()), ntr, nte, float((a > 0).mean() * 100), float((b_ > 0).mean() * 100),
                                tf, triple, rule, tp, sl, hold, (trig, gap), fname))
        print(f"  arama: {si}/{len(per_set)} set {key} n={len(symbols)} deneme={len(all_train_means)} artı={len(results)} ({time.time()-t_start:.0f} sn)", file=sys.stderr)

    # --- rapor
    generated = dt.datetime.now(TZ)
    tag = args.tag or f"{cache['days']}g_{generated:%Y-%m-%d}"
    by_train = sorted(results, key=lambda r: r[0], reverse=True)
    robust = [r for r in results if r[0] > 0 and r[1] > 0]
    robust.sort(key=lambda r: min(r[0], r[1]), reverse=True)
    n_sets = len(per_set)
    n_total = sum(len(d["symbol"]) for d in per_set.values())

    def row(r):
        tr, te, ntr, nte, wtr, wte, tf, triple, rule, tp, sl, hold, (trig, gap), fname = r
        trail = "yok" if trig == 0 else f"{trig:g}/{gap:g}"
        return (f"| {tf_label(tf)} | {'/'.join(map(str, triple))} | {rule} | {tp:g} | {sl:g} | {hold} | {trail} | {fname} | "
                f"{ntr} | {tr:+.2f}% | {wtr:.0f}% | {nte} | {te:+.2f}% | {wte:.0f}% |")

    head = ("| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |\n"
            "|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|")
    lines = [f"# MA kesişimi kombinasyon araması — {cache['days']} gün ({generated:%Y-%m-%d %H:%M})", "",
             "Evren: " + {"live": f"canlı sistem mantığı (ilk {cache['settings']['TOP_GAINERS_LIMIT']} yükselen + saatlik aktivite",
                           "liquid": "24 sa hacmi ≥ 1M TL olan tüm çiftler (aktivite filtresi yok)",
                           "decliners": f"likitler içinde 24 sa değişimi en düşük {cache['settings']['TOP_GAINERS_LIMIT']}"}[cache.get("universe_mode", "live")]
             + f"; {cache['n_universe']} TRY çifti; "
             f"saatlik ortalama taranan {cache['avg_members']:.1f}). Eğitim: ilk {cache['days']-args.test_days} gün, test: son {args.test_days} gün. "
             f"Maliyet (gidiş-dönüş): {cost_pct:.3f}%. Giriş: {'sinyal mumu kapanışı (piyasa)' if PULLBACK_PCT <= 0 else f'kapanışın %{PULLBACK_PCT:g} altına limit, {PULLBACK_WAIT} dk içinde dolmazsa yok'}. Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).", "",
             f"Denenen: {n_sets} giriş seti (TF × MA üçlüsü × kural; toplam {n_total} ham sinyal) × {len(combos)} çıkış kombinasyonu × "
             f"{len(filter_masks({k: np.zeros(1) for k in FEATURE_NAMES}))} filtre maskesi = {len(all_train_means)} geçerli deneme (n eğitim ≥ {MIN_TRAIN}, n test ≥ {MIN_TEST}); {len(results)} tanesi eğitimde artı.", "",
             "## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)", "",
             head] + [row(r) for r in robust[:25]]
    if not robust:
        lines.append("| — | hiçbir kombinasyon iki dönemde de artı değil | | | | | | | | | | | | |")
    lines += ["", "## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)", "", head] + [row(r) for r in by_train[:25]]
    lines += ["", "## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)", "", head]
    short = [r for r in by_train if r[9] == 2.0 and r[11] <= 60][:15]
    lines += [row(r) for r in short] or ["| — | yok | | | | | | | | | | | | |"]
    all_means = np.array(all_train_means) if all_train_means else np.array([0.0])
    test_of_top = np.array([r[1] for r in by_train[:100]]) if results else np.array([0.0])
    lines += ["", "## Okuma", "",
              f"- {len(all_train_means)} denemenin eğitim ortalaması medyanı {np.median(all_means):+.2f}%, en iyi {all_means.max():+.2f}%; eğitimde en iyi 100'ün "
              f"test ortalaması medyanı {np.median(test_of_top):+.2f}% ve {int((test_of_top > 0).sum())} tanesi testte artı.",
              "- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. "
              f"{len(filter_masks({k: np.zeros(1) for k in FEATURE_NAMES})) * len(combos) * n_sets} denemeden şans eseri de artı çıkanlar olur.",
              "- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.", ""]
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_KESISIM_KOMBINASYON_ARAMA_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(WORK_DIR, f"ma_cross_combo_search_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump([list(r[:7]) + ["/".join(map(str, r[7]))] + list(r[8:12]) + [list(r[12]), r[13]] for r in by_train[:2000]], fh)
    print(md)
    print(f"\nRapor: {md_path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
