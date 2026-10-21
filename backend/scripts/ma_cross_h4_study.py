"""H4 MA kesişimi araması — uzun tutma (4 sa … 3 gün) ve büyük hedef (%3–10) ile (2026-10-21).

`ma_cross_combo_search` ile aynı evren önbelleği (canlı sistem seçimi), aynı vektörel çıkış simülatörü ve filtre maskeleri;
yalnız dilim 4h (15m arşivinden kurulur), pencere 3 gün. Eğitim ilk 60 gün, test son 30 gün. H4 sinyali seyrek olduğu için
eşikler n eğitim ≥ 30, n test ≥ 12 (raporda belirtilir). Not: 15m önbelleği 90 gün + 8 gün geriye gider; SMA 99 H4'te 16,5 gün
ısınma ister, bu yüzden pencerenin ilk ~9 günü sinyal üretmez.

KULLANIM: python backend/scripts/ma_cross_h4_study.py
"""
from __future__ import annotations

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
from app import database                                # noqa: E402
from app.config import config                           # noqa: E402

H4_MS = 14_400_000
M15_MS = 900_000
TARGETS = (3.0, 5.0, 8.0, 10.0)
STOPS = (2.0, 3.0, 5.0, 8.0)
HOLDS = (240, 480, 1440, 2880, 4320)
TRAILS = ((0.0, 0.0), (2.0, 1.0), (3.0, 1.5))
MIN_TRAIN, MIN_TEST = 30, 12


def h4_from_15m(b15: dict) -> dict:
    """15m numpy sütunları → tam dolu (16 alt mum) H4 mumları."""
    key = (b15["open_ms"] // H4_MS) * H4_MS
    out = {k: [] for k in ("open_ms", "open", "high", "low", "close", "volume")}
    i = 0
    n = len(key)
    while i < n:
        j = i
        while j < n and key[j] == key[i]:
            j += 1
        if j - i == 16:
            out["open_ms"].append(int(key[i])); out["open"].append(float(b15["open"][i]))
            out["high"].append(float(b15["high"][i:j].max())); out["low"].append(float(b15["low"][i:j].min()))
            out["close"].append(float(b15["close"][j - 1])); out["volume"].append(float(b15["volume"][i:j].sum()))
        i = j
    return {k: np.array(v, dtype=np.int64 if k == "open_ms" else np.float64) for k, v in out.items()}


async def main() -> int:
    S.MAXW = max(HOLDS)
    cache_path = S.CACHE_TPL.format(days=90)
    with open(cache_path, "rb") as fh:
        cache = pickle.load(fh)
    now_ms, start_ms = cache["now_ms"], cache["start_ms"]
    split_ms = now_ms - 30 * S.DAY_MS
    member = S.Membership(cache["timeline"])
    cost_pct = 100.0 * (2 * float(config.effective_commission_pct()) + 2 * float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025)))
    per_set: dict = defaultdict(lambda: {"symbol": [], "close_ms": [], "W": [], "F": defaultdict(list)})
    t_start = time.time()
    syms = cache["scan_symbols"]
    for n, symbol in enumerate(syms, 1):
        b = h4_from_15m(cache["tf_bars"][(symbol, "15m")])
        sets, feats = S.signal_sets_for_symbol(symbol, "4h", b, member, start_ms)
        if not sets:
            continue
        m1_rows = await database.get_market_candles(symbol, "1m", start_ms=start_ms - S.DAY_MS, end_ms=now_ms)
        m1 = {"open_ms": np.array([int(r["open_time"]) for r in m1_rows], dtype=np.int64),
              "high": np.array([float(r["high"]) for r in m1_rows]), "low": np.array([float(r["low"]) for r in m1_rows]),
              "close": np.array([float(r["close"]) for r in m1_rows])}
        if len(m1["open_ms"]) < 1000:
            continue
        for (triple, rule), (sig, slope5, dist) in sets.items():
            idx = np.array([i for i, _ in sig]); cms = [t for _, t in sig]
            entries = b["close"][idx]
            W = S.windows_for(cms, m1, b["close"], entries)
            d = per_set[("4h", triple, rule)]
            d["symbol"] += [symbol] * len(sig); d["close_ms"] += cms; d["W"].append(W)
            for k in ("stoch", "rsi", "adx", "macd_hist", "body_pct", "vol_ratio", "atr_pct"):
                d["F"][k].append(feats[k][idx])
            d["F"]["macd_hist_prev"].append(feats["macd_hist"][np.maximum(idx - 1, 0)])
            d["F"]["slow_slope"].append(slope5[idx]); d["F"]["dist_slow"].append(dist[idx])
            d["F"]["hour"].append(np.array([dt.datetime.fromtimestamp(t / 1000, S.TZ).hour for t in cms], dtype=np.float64))
        if n % 25 == 0 or n == len(syms):
            print(f"  H4 sinyal/pencere: {n}/{len(syms)} ({time.time()-t_start:.0f} sn)", file=sys.stderr)

    all_train: list[float] = []
    results = []
    combos = list(itertools.product(TARGETS, STOPS, HOLDS, TRAILS))
    t_start = time.time()
    for si, (key, d) in enumerate(sorted(per_set.items()), 1):
        tf, triple, rule = key
        symbols = np.array(d["symbol"]); close_ms = np.array(d["close_ms"], dtype=np.int64)
        W = np.concatenate(d["W"], axis=0)
        F = {k: np.concatenate(v) for k, v in d["F"].items()}
        masks = S.filter_masks(F)
        is_train = close_ms < split_ms
        dedups = {h: S.dedup_mask(symbols, close_ms, h) for h in HOLDS}
        for tp, sl, hold, (trig, gap) in combos:
            net = S.simulate(W, tp, sl, hold, trig, gap, cost_pct)
            base = ~np.isnan(net) & dedups[hold]
            for fname, fm in masks.items():
                m = base & fm
                tr, te = m & is_train, m & ~is_train
                ntr, nte = int(tr.sum()), int(te.sum())
                if ntr < MIN_TRAIN or nte < MIN_TEST:
                    continue
                a, b_ = net[tr], net[te]
                tm = float(a.mean()); all_train.append(tm)
                if tm <= 0:
                    continue
                results.append((tm, float(b_.mean()), ntr, nte, float((a > 0).mean() * 100), float((b_ > 0).mean() * 100),
                                tf, triple, rule, tp, sl, hold, (trig, gap), fname))
        print(f"  arama: {si}/{len(per_set)} {key} n={len(symbols)} deneme={len(all_train)} artı={len(results)} ({time.time()-t_start:.0f} sn)", file=sys.stderr)

    generated = dt.datetime.now(S.TZ)
    by_train = sorted(results, key=lambda r: r[0], reverse=True)
    robust = sorted([r for r in results if r[0] > 0 and r[1] > 0], key=lambda r: min(r[0], r[1]), reverse=True)
    two_pct = [r for r in robust if r[0] >= 2.0 and r[1] >= 2.0]

    def row(r):
        tr, te, ntr, nte, wtr, wte, tf, triple, rule, tp, sl, hold, (trig, gap), fname = r
        trail = "yok" if trig == 0 else f"{trig:g}/{gap:g}"
        return (f"| {'/'.join(map(str, triple))} | {rule} | {tp:g} | {sl:g} | {hold} | {trail} | {fname} | "
                f"{ntr} | {tr:+.2f}% | {wtr:.0f}% | {nte} | {te:+.2f}% | {wte:.0f}% |")

    head = ("| MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |\n"
            "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|")
    n_total = sum(len(d["symbol"]) for d in per_set.values())
    all_arr = np.array(all_train) if all_train else np.array([0.0])
    lines = [f"# H4 MA kesişimi araması — 90 gün, uzun tutma ve büyük hedef ({generated:%Y-%m-%d %H:%M})", "",
             f"Evren: canlı sistem mantığı (ilk {cache['settings']['TOP_GAINERS_LIMIT']} yükselen + saatlik aktivite; {cache['n_universe']} TRY çifti). "
             f"Dilim H4 (15m arşivinden). Eğitim ilk 60 gün, test son 30 gün. Maliyet {cost_pct:.3f}%. Sembol başına tek pozisyon. "
             f"Eşik: n eğitim ≥ {MIN_TRAIN}, n test ≥ {MIN_TEST} (H4 sinyali seyrek).", "",
             f"Denenen: {len(per_set)} giriş seti ({n_total} ham H4 sinyali) × {len(combos)} çıkış kombinasyonu × {len(S.filter_masks({k: np.zeros(1) for k in S.FEATURE_NAMES}))} "
             f"filtre = {len(all_train)} geçerli deneme; {len(results)} tanesi eğitimde artı.", "",
             "## İki dönemde de ≥ +2% olanlar", "", head] + ([row(r) for r in two_pct[:20]] or ["| — | yok | | | | | | | | | | | |"])
    lines += ["", "## Hem eğitimde hem testte artı olanlar (min(eğitim, test))", "", head] + ([row(r) for r in robust[:25]] or ["| — | yok | | | | | | | | | | | |"])
    lines += ["", "## Eğitimde en iyi 15", "", head] + [row(r) for r in by_train[:15]]
    lines += ["", "## Okuma", "",
              f"- {len(all_train)} denemenin eğitim ortalaması medyanı {np.median(all_arr):+.2f}%, en iyi {all_arr.max():+.2f}%.",
              "- H4'te sinyal sayısı az; +%2 üstü görünen sonuçların n'i küçükse şans payı büyüktür. Komşu varyantları da artı olan kümeye bakın.",
              "- Tutma 1–3 gün olduğunda sonuç TF kuralından çok piyasa yönüne bağlıdır (90 günün ilk 60 ve son 30 gününün rejimi farklı olabilir).", ""]
    md = "\n".join(lines)
    path = os.path.join(S.DOCS_DIR, f"MA_KESISIM_H4_ARAMA_90g_{generated:%Y-%m-%d}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(S.WORK_DIR, f"ma_cross_h4_study_{generated:%Y-%m-%d}.json"), "w", encoding="utf-8") as fh:
        json.dump([list(r[:7]) + ["/".join(map(str, r[7]))] + list(r[8:12]) + [list(r[12]), r[13]] for r in by_train[:2000]], fh)
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
