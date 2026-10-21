"""H4 MA7↗MA20 kesişimi — 90 günlük replay (2026-10-21 19:15, kullanıcı isteği).

Canlı kural (ma_buy_profiles H4): SMA 7/20/99, MA7 MA20'yi yukarı keser, MA99 şartı YOK, gövde/StochRSI eleği yok,
sembolün 24 sa TL hacmi ≥ 5M; paper çıkışı hedef %10, stop %8, en çok 3 gün, iz süren stop yok.

Evren: `ma_cross_combo_search --universe liquid` önbelleği (24 sa hacmi ≥ 1M TL olan tüm TRY çiftleri; 10 dk'lık üyelik
zaman çizelgesi). 24 sa TL hacmi her H4 kapanışında 15m mumlardan (hacim × kapanış toplamı, son 96 mum) türetilir; hacim
tabanı varyantları bununla uygulanır. Giriş sinyal mumunun kapanışı, 1 dk mumlarla kötümser çıkış (aynı mumda stop ve
hedef → stop), gidiş-dönüş maliyet config'ten, sembol başına tek pozisyon. Eğitim ilk 60 gün, test son 30 gün.

Bölümler: (A) canlı çıkışla kural × hacim tabanı; (B) 5M tabanla çıkış ızgarası; (C) 5M tabanla tekli filtreler;
(D) aylık kırılım; (E) 3 gün içindeki zirve ve zirveye süre (radar sekmesindeki ölçümün tarihsel dağılımı).

KULLANIM: python backend/scripts/ma_buy_h4_replay_7_20.py [--cache backend/work/ma_cross_search_cache_90g_liquid.pkl]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import itertools
import json
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ma_cross_combo_search as S                      # noqa: E402
from ma_cross_h4_study import h4_from_15m              # noqa: E402
from app import database, ma_buy_rules, ma_buy_signals  # noqa: E402
from app.config import config                           # noqa: E402

H4_MS = 14_400_000
M15_MS = 900_000
DAY_MS = 86_400_000
LIVE_TP, LIVE_SL, LIVE_HOLD = 10.0, 8.0, 4320
FLOORS = (1e6, 5e6, 10e6, 20e6, 50e6)
TARGETS = (5.0, 8.0, 10.0, 15.0)
STOPS = (3.0, 5.0, 8.0)
HOLDS = (1440, 2880, 4320)
TRAILS = ((0.0, 0.0), (3.0, 1.5))
MIN_TRAIN, MIN_TEST = 30, 12
RULES = ("7↗20 (MA99 şartsız)", "7↗20 + MA20>MA99", "20↗99 (MA7>MA20)")


def qv24_at_h4(b15: dict, h4_open_ms: np.ndarray) -> np.ndarray:
    """Her H4 mumunun KAPANIŞI itibarıyla son 24 saatte kapanan 15m mumların TL hacmi (hacim × kapanış)."""
    close15 = b15["open_ms"] + M15_MS
    qv = b15["volume"] * b15["close"]
    cs = np.cumsum(np.insert(qv, 0, 0.0))
    out = np.zeros(len(h4_open_ms))
    for k, o in enumerate(h4_open_ms):
        t = int(o) + H4_MS
        hi = int(np.searchsorted(close15, t, side="right"))
        lo = int(np.searchsorted(close15, t - DAY_MS, side="right"))
        out[k] = cs[hi] - cs[lo]
    return out


def signals_for_symbol(symbol: str, b: dict, b15: dict, member: S.Membership, start_ms: int) -> tuple[dict, dict]:
    """{kural: idx dizisi}, özellikler (bar bazında)."""
    closes = b["close"]
    n = len(closes)
    if n < 120:
        return {}, {}
    cl = closes.tolist()
    f, m, s = (S._np(ma_buy_signals.sma_series(cl, p)) for p in (7, 20, 99))
    ok_fm = np.zeros(n, dtype=bool)
    ok_fm[1:] = (f[:-1] <= m[:-1]) & (f[1:] > m[1:])
    ok_ms = np.zeros(n, dtype=bool)
    ok_ms[1:] = (m[:-1] <= s[:-1]) & (m[1:] > s[1:])
    masks = {RULES[0]: ok_fm & ~np.isnan(m), RULES[1]: ok_fm & (m > s), RULES[2]: ok_ms & (f > m)}
    close_ms = b["open_ms"] + H4_MS
    bars_dicts = [{"high": h, "low": l, "close": c} for h, l, c in zip(b["high"], b["low"], closes)]
    vol = b["volume"]
    vavg = np.full(n, np.nan)
    cs = np.cumsum(np.insert(vol, 0, 0.0))
    vavg[20:] = (cs[20:-1] - cs[:-21]) / 20.0
    feats = {
        "body_pct": (closes - b["open"]) / np.where(b["open"] > 0, b["open"], np.nan) * 100.0,
        "vol_ratio": vol / np.where(vavg > 0, vavg, np.nan),
        "adx": S._np(ma_buy_rules.adx_series(bars_dicts, 14)),
        "rsi": S._np(ma_buy_signals.rsi_series(cl, 14)),
        "stoch": S._np(ma_buy_signals.stoch_rsi_k(cl)),
        "dist_slow": (closes - s) / np.where(s > 0, s, np.nan) * 100.0,
        "mid_above_slow": (m > s).astype(np.float64),
        "qv24": qv24_at_h4(b15, b["open_ms"]),
        "hour": np.array([dt.datetime.fromtimestamp(t / 1000, S.TZ).hour for t in close_ms], dtype=np.float64),
        "close_ms": close_ms.astype(np.float64),
    }
    out = {}
    for rule, mask in masks.items():
        idx = np.flatnonzero(mask)
        idx = np.array([i for i in idx if close_ms[i] >= start_ms and member.has(symbol, int(close_ms[i]))], dtype=np.int64)
        if len(idx):
            out[rule] = idx
    return out, feats


def peak_stats(W: np.ndarray, hold: int) -> dict:
    """3 gün içindeki zirve (%), zirveye süre (dk) ve dip (%) dağılımı — stop/hedef uygulanmadan."""
    H = W[:, 0, :hold]
    L = W[:, 1, :hold]
    valid = ~np.all(np.isnan(H), axis=1)
    H, L = H[valid], L[valid]
    if not len(H):
        return {}
    Hf = np.where(np.isnan(H), -np.inf, H)
    peak_i = np.argmax(Hf, axis=1)
    peak = (Hf[np.arange(len(H)), peak_i] - 1.0) * 100.0
    drop = (np.nanmin(L, axis=1) - 1.0) * 100.0
    mins = peak_i + 1.0
    return {"n": int(len(H)), "peak_mean": float(peak.mean()), "peak_median": float(np.median(peak)),
            "peak_ge2": float((peak >= 2).mean() * 100), "peak_ge5": float((peak >= 5).mean() * 100),
            "peak_ge10": float((peak >= 10).mean() * 100), "t_median_min": float(np.median(mins)),
            "t_mean_min": float(mins.mean()), "drop_mean": float(drop.mean()), "drop_median": float(np.median(drop)),
            "drop_le_m8": float((drop <= -8).mean() * 100)}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(S.WORK_DIR, "ma_cross_search_cache_90g_liquid.pkl"))
    args = ap.parse_args()
    S.MAXW = max(HOLDS)
    with open(args.cache, "rb") as fh:
        cache = pickle.load(fh)
    now_ms, start_ms = cache["now_ms"], cache["start_ms"]
    split_ms = now_ms - 30 * DAY_MS
    member = S.Membership(cache["timeline"])
    cost_pct = 100.0 * (2 * float(config.effective_commission_pct()) + 2 * float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025)))
    per_rule: dict = defaultdict(lambda: {"symbol": [], "close_ms": [], "W": [], "F": defaultdict(list)})
    syms = cache["scan_symbols"]
    t_start = time.time()
    for n, symbol in enumerate(syms, 1):
        b15 = cache["tf_bars"][(symbol, "15m")]
        b = h4_from_15m(b15)
        sets, feats = signals_for_symbol(symbol, b, b15, member, start_ms)
        if not sets:
            continue
        m1_rows = await database.get_market_candles(symbol, "1m", start_ms=start_ms - DAY_MS, end_ms=now_ms)
        m1 = {"open_ms": np.array([int(r["open_time"]) for r in m1_rows], dtype=np.int64),
              "high": np.array([float(r["high"]) for r in m1_rows]), "low": np.array([float(r["low"]) for r in m1_rows]),
              "close": np.array([float(r["close"]) for r in m1_rows])}
        if len(m1["open_ms"]) < 1000:
            continue
        for rule, idx in sets.items():
            cms = [int(b["open_ms"][i]) + H4_MS for i in idx]
            W = S.windows_for(cms, m1, b["close"], b["close"][idx])
            d = per_rule[rule]
            d["symbol"] += [symbol] * len(idx); d["close_ms"] += cms; d["W"].append(W)
            for k, arr in feats.items():
                d["F"][k].append(arr[idx])
        if n % 25 == 0 or n == len(syms):
            print(f"  sinyal/pencere: {n}/{len(syms)} ({time.time() - t_start:.0f} sn)", file=sys.stderr)

    def stats(net: np.ndarray, m: np.ndarray, is_train: np.ndarray) -> dict | None:
        tr, te = m & is_train, m & ~is_train
        ntr, nte = int(tr.sum()), int(te.sum())
        if ntr < MIN_TRAIN or nte < MIN_TEST:
            return None
        a, b_ = net[tr], net[te]
        return {"ntr": ntr, "nte": nte, "tr": float(a.mean()), "te": float(b_.mean()), "wtr": float((a > 0).mean() * 100),
                "wte": float((b_ > 0).mean() * 100), "med_tr": float(np.median(a)), "med_te": float(np.median(b_)),
                "all": float(net[m].mean()), "n": int(m.sum())}

    def fmt(r: dict | None) -> str:
        if r is None:
            return "| — | — | — | — | — | — | — |"
        return (f"| {r['ntr']} | {r['tr']:+.2f}% | {r['med_tr']:+.2f}% | {r['wtr']:.0f}% | {r['nte']} | {r['te']:+.2f}% | {r['wte']:.0f}% |")

    HEAD = "| n eğitim | Ort. net eğitim | Medyan eğitim | Kazanan | n test | Ort. net test | Kazanan |"
    SEP = "|---:|---:|---:|---:|---:|---:|---:|"
    lines: list[str] = []
    generated = dt.datetime.now(S.TZ)
    lines += [f"# H4 MA7↗MA20 kesişimi — 90 gün replay ({generated:%Y-%m-%d %H:%M})", "",
              f"Evren: 24 sa hacmi ≥ 1M TL olan tüm TRY çiftleri ({cache['n_universe']} çift, önbellek: {os.path.basename(args.cache)}); "
              f"hacim tabanı her sinyalde 15m mumlardan türetilen 24 sa TL hacmiyle uygulanır. Dilim H4 (15m arşivinden). "
              f"Eğitim ilk 60 gün, test son 30 gün. Maliyet {cost_pct:.3f}%. Giriş sinyal mumu kapanışı; 1 dk mumlarla kötümser çıkış; "
              f"sembol başına tek pozisyon. Eşik n eğitim ≥ {MIN_TRAIN}, n test ≥ {MIN_TEST}.", "",
              "Canlı kural: **7↗20 (MA99 şartsız), hacim ≥ 5M, hedef %10, stop %8, en çok 3 gün, iz süren stop yok.**", ""]

    summary_json: dict = {}
    data: dict = {}
    for rule, d in per_rule.items():
        symbols = np.array(d["symbol"]); close_ms = np.array(d["close_ms"], dtype=np.int64)
        W = np.concatenate(d["W"], axis=0)
        F = {k: np.concatenate(v) for k, v in d["F"].items()}
        data[rule] = (symbols, close_ms, W, F)

    # (A) kural × hacim tabanı, canlı çıkış
    lines += ["## A. Kural × hacim tabanı (hedef %10, stop %8, 3 gün, iz süren yok)", "",
              "| Kural | Hacim tabanı | Ham sinyal |" + HEAD[1:], "|---|---|---:|" + SEP[1:]]
    for rule in RULES:
        if rule not in data:
            continue
        symbols, close_ms, W, F = data[rule]
        is_train = close_ms < split_ms
        dedup = S.dedup_mask(symbols, close_ms, LIVE_HOLD)
        net = S.simulate(W, LIVE_TP, LIVE_SL, LIVE_HOLD, 0.0, 0.0, cost_pct)
        base = ~np.isnan(net) & dedup
        for floor in FLOORS:
            m = base & (F["qv24"] >= floor)
            r = stats(net, m, is_train)
            lines.append(f"| {rule} | ≥ {floor / 1e6:g}M | {int((F['qv24'] >= floor).sum())} |" + fmt(r)[1:])
            if rule == RULES[0]:
                summary_json[f"floor_{int(floor / 1e6)}M"] = r
    lines.append("")

    if RULES[0] in data:
        symbols, close_ms, W, F = data[RULES[0]]
        is_train = close_ms < split_ms
        floor5 = F["qv24"] >= 5e6
        # (B) çıkış ızgarası
        lines += ["## B. 7↗20 (MA99 şartsız), hacim ≥ 5M — çıkış ızgarası", "",
                  "| Hedef% | Stop% | Tutma dk | İz süren |" + HEAD[1:], "|---:|---:|---:|---|" + SEP[1:]]
        grid = []
        for tp, sl, hold, (trig, gap) in itertools.product(TARGETS, STOPS, HOLDS, TRAILS):
            net = S.simulate(W, tp, sl, hold, trig, gap, cost_pct)
            m = ~np.isnan(net) & S.dedup_mask(symbols, close_ms, hold) & floor5
            r = stats(net, m, is_train)
            if r:
                grid.append((tp, sl, hold, trig, gap, r))
        grid.sort(key=lambda g: min(g[5]["tr"], g[5]["te"]), reverse=True)
        for tp, sl, hold, trig, gap, r in grid[:20]:
            trail = "yok" if trig == 0 else f"{trig:g}/{gap:g}"
            lines.append(f"| {tp:g} | {sl:g} | {hold} | {trail} |" + fmt(r)[1:])
        live = [g for g in grid if g[:5] == (LIVE_TP, LIVE_SL, LIVE_HOLD, 0.0, 0.0)]
        lines += ["", "Canlı çıkış (10 / 8 / 4320 / yok): " + ((HEAD + "\n" + SEP + "\n" + fmt(live[0][5])) if live else "eşik altı"), ""]
        summary_json["grid_top"] = [[g[0], g[1], g[2], g[3], g[4], g[5]] for g in grid[:20]]

        # (C) tekli filtreler, canlı çıkış
        net = S.simulate(W, LIVE_TP, LIVE_SL, LIVE_HOLD, 0.0, 0.0, cost_pct)
        base = ~np.isnan(net) & S.dedup_mask(symbols, close_ms, LIVE_HOLD) & floor5
        filters = {
            "yok": np.ones(len(net), dtype=bool),
            "MA20 > MA99 (eski şart)": F["mid_above_slow"] > 0,
            "gövde ≥ 0.3%": F["body_pct"] >= 0.3,
            "gövde ≥ 1%": F["body_pct"] >= 1.0,
            "hacim oranı ≥ 1.5× (H4, 20 mum)": F["vol_ratio"] >= 1.5,
            "hacim oranı ≥ 2×": F["vol_ratio"] >= 2.0,
            "ADX14 > 20": F["adx"] > 20,
            "ADX14 > 25": F["adx"] > 25,
            "RSI14 < 70": F["rsi"] < 70,
            "StochRSI ≤ 80": ~(F["stoch"] > 80),
            "MA99'a uzaklık ≤ 2%": F["dist_slow"] <= 2.0,
            "MA99'a uzaklık ≤ 5%": F["dist_slow"] <= 5.0,
            "saat 09–23": (F["hour"] >= 9) & (F["hour"] <= 23),
        }
        lines += ["## C. 7↗20, hacim ≥ 5M, canlı çıkış — tekli ek filtreler", "", "| Filtre |" + HEAD[1:], "|---|" + SEP[1:]]
        for name, fm in filters.items():
            lines.append(f"| {name} |" + fmt(stats(net, base & fm, is_train))[1:])
        lines.append("")

        # (D) aylık
        lines += ["## D. 7↗20, hacim ≥ 5M, canlı çıkış — 30 günlük dilimler", "", "| Dönem | n | Ort. net | Medyan | Kazanan |", "|---|---:|---:|---:|---:|"]
        for k in range(3):
            lo, hi = start_ms + k * 30 * DAY_MS, start_ms + (k + 1) * 30 * DAY_MS
            m = base & (close_ms >= lo) & (close_ms < hi)
            if m.sum():
                a = net[m]
                lines.append(f"| {dt.datetime.fromtimestamp(lo / 1000, S.TZ):%d.%m} – {dt.datetime.fromtimestamp(hi / 1000, S.TZ):%d.%m} | {int(m.sum())} | "
                             f"{a.mean():+.2f}% | {np.median(a):+.2f}% | {(a > 0).mean() * 100:.0f}% |")
        lines.append("")

        # (E) zirve dağılımı
        ps = peak_stats(W[base], LIVE_HOLD)
        if ps:
            lines += ["## E. 7↗20, hacim ≥ 5M — 3 gün içindeki zirve ve zirveye süre (stop/hedef uygulanmadan)", "",
                      f"- İşlem: {ps['n']}. Zirve ortalama {ps['peak_mean']:+.2f}%, medyan {ps['peak_median']:+.2f}%. "
                      f"Zirve ≥ %2: {ps['peak_ge2']:.0f}%, ≥ %5: {ps['peak_ge5']:.0f}%, ≥ %10: {ps['peak_ge10']:.0f}%.",
                      f"- Zirveye süre: medyan {ps['t_median_min'] / 60:.1f} sa, ortalama {ps['t_mean_min'] / 60:.1f} sa.",
                      f"- Dip ortalama {ps['drop_mean']:+.2f}%, medyan {ps['drop_median']:+.2f}%; dip ≤ −8% (stop) payı {ps['drop_le_m8']:.0f}%.", ""]
            summary_json["peak"] = ps
        summary_json["n_raw_7_20"] = int(len(net))

    lines += ["## Okuma", "",
              "- A tablosu kuralın kendisini ve hacim tabanının etkisini gösterir; 5M tabanı canlı ayardır.",
              "- B'de canlı çıkış ile komşuları karşılaştırın: yalnız bir hücre artıysa seçim gürültüsüdür, komşular da artıysa sağlamdır.",
              "- D'de dönemler arasında işaret değişiyorsa sonuç piyasa yönüne bağlıdır; 3 günlük tutmada bu beklenir.",
              "- E radar sekmesindeki 'en yüksek / zirveye süre' ölçümünün tarihsel karşılığıdır.", ""]
    md = "\n".join(lines)
    path = os.path.join(S.DOCS_DIR, f"MA_BUY_H4_REPLAY_7_20_90g_{generated:%Y-%m-%d}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(S.WORK_DIR, f"ma_buy_h4_replay_7_20_{generated:%Y-%m-%d}.json"), "w", encoding="utf-8") as fh:
        json.dump(summary_json, fh, ensure_ascii=False, indent=1)
    print(md)
    print(f"\nRapor: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
