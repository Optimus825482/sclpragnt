"""90 günlük doğrulama: BTC rejim kalkanı, aşırı alım kapısı ve taker çarpanı (2026-10-17).

21 günlük ölçümün (docs/REJIM_KALKANI_ANALIZI_2026-10-17.md) üç canlı kararını 90 günlük
rescan üzerinde, 30 günlük bloklar halinde yeniden sınar:
  1. RADAR_SHIELD_MODE=badge           (kalkan engel yerine rozet)
  2. VELOCITY_EXHAUSTION_MODE=penalty  (aşırı alım kapısı skor cezası)
  3. Taker çarpanı (strong >= 0.58 ×1.05, weak <= 0.45 ×0.95) — hiç doğrulanmamıştı.

Girdi: `rescan_velocity_history.py --no-exhaustion-gate --journal-cap 0` JSONL'i (taker alanları
`radar.taker_buy_ratio` / `radar.taker_confirm`), BTCTRY 1h kline önbelleği (>= 210 bar öncesi dâhil).
Çekirdek fonksiyonlar `radar_shield_rescan_analysis.py`'den gelir; bu betik YALNIZ okur, DB'ye yazmaz,
canlı kodu değiştirmez.

ÖN KAYITLI KURALLAR (sonuçlar görülmeden yazıldı):
  Kalkan   : hit60(kalkan açık) >= hit60(kapalı) - 5 pp -> KALKAN_FAZLA_SIKI;  < -10 pp -> KALKAN_ISE_YARIYOR.
  Aşırı alım (kalkan kapalı): hit60(elenen) >= hit60(geçen) - 5 pp -> KAPI_DEGER_KATMIYOR; < -10 pp -> KAPI_ISE_YARIYOR.
  Taker    : fark = hit60(strong) - hit60(weak); blokların >= 2/3'ünde fark >= +3 pp VE tüm pencerede
             iki oran z-testi z >= 2 -> TAKER_DOGRULANDI; tüm pencerede fark <= 0 -> TAKER_ANLAMSIZ_YA_DA_TERS;
             aksi -> TAKER_BELIRSIZ.

Kullanım (backend/ içinden):
  python scripts/validation90_report.py --jsonl work/rescan_90g_nogate.jsonl \
      --btc-1h work/btc_1h_120d.json --start 2026-07-20 --end 2026-10-16 --out-dir work/validation90
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.notification_outcomes_report import CandleStore, TZ  # noqa: E402
from scripts.radar_shield_rescan_analysis import (  # noqa: E402
    HEADER, _row, btc_regime_table, build_report, dedupe_horizon, evaluate, group_stats,
    is_overbought, load_btc_1h, load_btc_5m, load_jsonl, mark_episodes, parse_day, run_chance,
    verdict, welch_t,
)

STRONG_MULT = 1.05
WEAK_MULT = 0.95
STRONG_RATIO = 0.58
WEAK_RATIO = 0.45
DEFAULT_BLOCKS = ("2026-07-20:2026-08-18", "2026-08-19:2026-09-17", "2026-09-18:2026-10-16")


# ------------------------------------------------------------------ saf yardımcılar
def parse_blocks(spec: str) -> list[tuple[str, str]]:
    """'a:b,c:d' -> [(a,b),(c,d)] (YYYY-MM-DD, gün dâhil)."""
    out = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        a, b = part.split(":")
        out.append((a.strip(), b.strip()))
    return out


def in_block(r: dict, start_ms: int, end_ms: int) -> bool:
    return start_ms <= int(r["tick_ms"]) <= end_ms


def taker_bucket(r: dict) -> str:
    """strong / neutral / weak / unavailable — canlı `radar.taker_confirm` ile aynı sınıflama."""
    rad = r.get("radar") or {}
    c = rad.get("taker_confirm")
    if c in ("strong", "weak"):
        return c
    if rad.get("taker_buy_ratio") is not None:
        return "neutral"
    return "unavailable"


def taker_ratio(r: dict) -> float | None:
    v = (r.get("radar") or {}).get("taker_buy_ratio")
    return None if v is None else float(v)


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """İki oran farkı için havuzlanmış z (grup1 - grup2)."""
    if n1 < 1 or n2 < 1:
        return None
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se <= 0:
        return None
    return (x1 / n1 - x2 / n2) / se


def taker_rule(block_diffs_pp: list[float | None], full_diff_pp: float | None, full_z: float | None) -> str:
    """Ön kayıtlı taker kuralı (modül başlığı)."""
    if full_diff_pp is None or full_z is None:
        return "YETERSIZ_VERI"
    ok_blocks = sum(1 for d in block_diffs_pp if d is not None and d >= 3.0)
    need = math.ceil(len([d for d in block_diffs_pp if d is not None]) * 2 / 3)
    if ok_blocks >= need and full_z >= 2.0:
        return "TAKER_DOGRULANDI"
    if full_diff_pp <= 0:
        return "TAKER_ANLAMSIZ_YA_DA_TERS"
    return "TAKER_BELIRSIZ"


def ob_verdict(passed: dict, elim: dict, min_n: int) -> str:
    """Aşırı alım kapısı için ön kayıtlı kural (kalkan kuralının aynası)."""
    v = verdict(passed, elim, min_n)
    return {"KALKAN_FAZLA_SIKI": "KAPI_DEGER_KATMIYOR", "KALKAN_ISE_YARIYOR": "KAPI_ISE_YARIYOR"}.get(v, v)


def quantile_edges(values: list[float], k: int = 10) -> list[float]:
    """k dilim için k-1 iç sınır (eşit sayıda gözlem)."""
    if not values:
        return []
    arr = np.array(values, dtype=float)
    return [float(np.quantile(arr, i / k)) for i in range(1, k)]


def bucket_index(v: float, edges: list[float]) -> int:
    """Sınırlara göre dilim (0..len(edges)); kenar değer üst dilime düşer."""
    return int(np.searchsorted(np.array(edges), v, side="right"))


def cluster_bootstrap_diff(a: list[dict], b: list[dict], value, *, day_ms: int = 86_400_000,
                           n_boot: int = 2000, seed: int = 11) -> tuple[float, float, float] | None:
    """mean(value|a) - mean(value|b) farkı için GÜN-küme bootstrap (günler yeniden örneklenir).
    Döner: (nokta tahmin, alt95, üst95); herhangi bir grup boşsa None."""
    if not a or not b:
        return None

    def agg(rs):
        d: dict[int, list[float]] = collections.defaultdict(list)
        for r in rs:
            d[int(r["tick_ms"]) // day_ms].append(float(value(r)))
        return d

    da, db = agg(a), agg(b)
    days = sorted(set(da) | set(db))
    sa = {k: (sum(v), len(v)) for k, v in da.items()}
    sb = {k: (sum(v), len(v)) for k, v in db.items()}
    na0 = sum(x[1] for x in sa.values()); nb0 = sum(x[1] for x in sb.values())
    point = sum(x[0] for x in sa.values()) / na0 - sum(x[0] for x in sb.values()) / nb0
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(days), size=len(days))
        sa_s = sa_n = sb_s = sb_n = 0.0
        for i in pick:
            d = days[int(i)]
            if d in sa:
                sa_s += sa[d][0]; sa_n += sa[d][1]
            if d in sb:
                sb_s += sb[d][0]; sb_n += sb[d][1]
        if sa_n > 0 and sb_n > 0:
            diffs.append(sa_s / sa_n - sb_s / sb_n)
    if not diffs:
        return None
    return point, float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))


def counterfactual_ranks(rows: list[dict], *, strong_mult: float = STRONG_MULT,
                         weak_mult: float = WEAK_MULT) -> dict[tuple, int]:
    """Taker çarpanı GERİ ALINIRSA (tick, ufuk) sıralaması. Anahtar: (tick_ms, symbol, horizon).
    `rows`: passes=True tüm satırlar (journal-cap 0), dedupe ÖNCESİ."""
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[(int(r["tick_ms"]), int(r.get("horizon_minutes") or 5))].append(r)
    out: dict[tuple, int] = {}
    for (t, h), rs in groups.items():
        def raw(r):
            s = float(r.get("velocity_score") or 0.0)
            b = taker_bucket(r)
            if b == "strong":
                return s / strong_mult
            if b == "weak":
                return s / weak_mult
            return s
        for i, r in enumerate(sorted(rs, key=raw, reverse=True), 1):
            out[(t, r["symbol"], h)] = i
    return out


def load_candles_lowmem(conn, since_ts: float, symbols: set[str]) -> CandleStore:
    """5m mumları sembol sembol okur (tuple listesi kurmadan; 90 gün için bellek dostu)."""
    series = {}
    since_ms = int((since_ts - 6 * 3600) * 1000)
    for sym in sorted(symbols):
        rows = conn.execute("SELECT open_time, high::float8, low::float8, close::float8 FROM historical_candles "
                            "WHERE symbol=%s AND timeframe='5m' AND open_time >= %s ORDER BY open_time",
                            (sym, since_ms)).fetchall()
        if len(rows) < 20:
            continue
        a = np.array(rows, dtype=float)
        series[sym] = (a[:, 0], a[:, 1], a[:, 2], a[:, 3])
    return CandleStore(series)


# ------------------------------------------------------------------ tablolar
def _stat_line(name: str, rs: list[dict]) -> tuple[str, dict]:
    g = group_stats(rs)
    return _row(name, g), g


def table(title: str, groups: list[tuple[str, list[dict]]]) -> tuple[str, dict]:
    lines = [f"\n#### {title}", HEADER]
    stats = {}
    for name, rs in groups:
        line, g = _stat_line(name, rs)
        lines.append(line)
        stats[name] = g
    return "\n".join(lines), stats


def sel_regime(rs, regime, *, shield=None, ob=None):
    out = []
    for r in rs:
        reg = regime.get(int(r["tick_ms"])) or {}
        if shield is not None and reg.get("shield") != shield:
            continue
        if ob is not None and is_overbought(r) != ob:
            continue
        out.append(r)
    return out


def taker_sections(ep_live: list[dict], blocks: dict[str, list[dict]], regime: dict[int, dict],
                   rows_dedup_all: list[dict], min_n: int) -> tuple[str, dict]:
    """Taker doğrulama tabloları. ep_live: rank<=10, kapı geçen bölüm satırları (tüm pencere)."""
    md: list[str] = []
    res: dict = {}
    avail = [r for r in ep_live if taker_bucket(r) != "unavailable"]
    n_un = len(ep_live) - len(avail)
    md.append(f"Canlı-benzeri küme (rank<=10, aşırı alım değil, bağımsız bölüm): {len(ep_live)}; taker verisi yok: {n_un} "
              f"(%{100 * n_un / max(1, len(ep_live)):.1f}).")

    # A. strong / neutral / weak — blok ve tüm pencere
    diffs_pp: list[float | None] = []
    for bname, rs in list(blocks.items()) + [("TÜM PENCERE", avail)]:
        groups = [(f"taker {b}", [r for r in rs if taker_bucket(r) == b]) for b in ("strong", "neutral", "weak")]
        txt, st = table(f"A. Taker sınıfı — {bname}", groups)
        md.append(txt)
        s, w = st["taker strong"], st["taker weak"]
        d = None
        if s.get("n", 0) >= min_n and w.get("n", 0) >= min_n:
            d = 100 * (s["hit60"] - w["hit60"])
            z = two_prop_z(int(round(s["hit60"] * s["n"])), s["n"], int(round(w["hit60"] * w["n"])), w["n"])
            wt = welch_t(s, w)
            ls, lw = s.get("lift"), w.get("lift")
            lift_d = None if (ls is None or lw is None) else 100 * (ls - lw)
            ld_s = "—" if lift_d is None else f"{lift_d:+.1f} pp"
            md.append(f"\nstrong − weak: hit60 {d:+.1f} pp (z {z:+.2f}); net60 {s['net'] - w['net']:+.2f} (Welch t {wt:+.2f}); "
                      f"şansa göre lift farkı {ld_s}.")
            res[bname] = {"diff_pp": d, "z": z, "welch_t": wt, "lift_diff_pp": lift_d,
                          "strong": {k: s[k] for k in ("n", "hit60", "net")}, "weak": {k: w[k] for k in ("n", "hit60", "net")},
                          "neutral": {k: st["taker neutral"].get(k) for k in ("n", "hit60", "net")}}
        if bname != "TÜM PENCERE":
            diffs_pp.append(d)
        else:
            res["rule"] = taker_rule(diffs_pp, d, res.get(bname, {}).get("z"))
    md.append(f"\nÖn kayıtlı taker kuralı: **{res.get('rule')}** (blok farkları pp: "
              f"{', '.join('—' if x is None else f'{x:+.1f}' for x in diffs_pp)}).")

    # A2. kalkan ayrımı (rejim karışıklığı kontrolü)
    groups = []
    for sh, sname in ((False, "kalkan kapalı"), (True, "kalkan açık")):
        for b in ("strong", "weak"):
            groups.append((f"{sname} · taker {b}", [r for r in sel_regime(avail, regime, shield=sh) if taker_bucket(r) == b]))
    txt, _ = table("A2. Taker sınıfı × kalkan durumu (tüm pencere)", groups)
    md.append(txt)

    if not avail:
        md.append(chr(10) + "Taker verisi yok; B-E tablolari atlandi.")
        res["rule"] = res.get("rule", "YETERSIZ_VERI")
        return chr(10).join(md), res

    # B. ondalıklar (tüm pencere)
    vals = [taker_ratio(r) for r in avail]
    edges = quantile_edges([v for v in vals if v is not None], 10)
    groups = []
    for i in range(10):
        lo = "−∞" if i == 0 else f"{edges[i - 1]:.3f}"
        hi = "+∞" if i == 9 else f"{edges[i]:.3f}"
        groups.append((f"D{i + 1} [{lo}, {hi})", [r for r in avail if taker_ratio(r) is not None and bucket_index(taker_ratio(r), edges) == i]))
    txt, st = table("B. taker_buy_ratio ondalıkları (tüm pencere, eşit sayıda gözlem)", groups)
    md.append(txt)
    res["deciles"] = {k: {kk: vv for kk, vv in v.items() if kk in ("n", "hit60", "net", "lift", "lift_n")} for k, v in st.items()}
    res["decile_edges"] = edges
    # monotonluk: D1..D10 hit60 ile sıra korelasyonu
    xs = [i for i in range(10) if st[groups[i][0]].get("n", 0) > 0]
    hs = [st[groups[i][0]]["hit60"] for i in xs]
    if len(xs) >= 5:
        rx = np.argsort(np.argsort(xs)); rh = np.argsort(np.argsort(hs))
        res["decile_spearman_hit60"] = float(np.corrcoef(rx, rh)[0, 1])
        md.append(f"\nOndalık sırası ile hit60 arasında Spearman ρ = {res['decile_spearman_hit60']:+.2f}.")

    # C. sabit genişlik kutular
    fixed = [(0.0, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.58), (0.58, 0.62), (0.62, 0.70), (0.70, 1.01)]
    groups = [(f"[{a:.2f}, {b:.2f})", [r for r in avail if taker_ratio(r) is not None and a <= taker_ratio(r) < b]) for a, b in fixed]
    txt, _ = table("C. taker_buy_ratio sabit kutular (tüm pencere)", groups)
    md.append(txt)

    # D. eşik taraması
    md.append("\n#### D. Eşik taraması (tüm pencere): oran >= c  vs  oran < c")
    md.append("| c | n(>=c) | hit60(>=c) | n(<c) | hit60(<c) | fark pp | z | net60 (>=c) | net60 (<c) | Welch t | lift(>=c) | lift(<c) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    sweep = {}
    for c in (0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.58, 0.60, 0.62, 0.65):
        hi_rs = [r for r in avail if taker_ratio(r) >= c]; lo_rs = [r for r in avail if taker_ratio(r) < c]
        a, b = group_stats(hi_rs), group_stats(lo_rs)
        if a.get("n", 0) < 5 or b.get("n", 0) < 5:
            continue
        z = two_prop_z(int(round(a["hit60"] * a["n"])), a["n"], int(round(b["hit60"] * b["n"])), b["n"])
        wt = welch_t(a, b)

        def lf(g):
            return "—" if g.get("lift") is None else f"{100 * g['lift']:+.1f}"
        md.append(f"| {c:.2f} | {a['n']} | %{100 * a['hit60']:.1f} | {b['n']} | %{100 * b['hit60']:.1f} | "
                  f"{100 * (a['hit60'] - b['hit60']):+.1f} | {z:+.2f} | {a['net']:+.2f} | {b['net']:+.2f} | {wt:+.2f} | {lf(a)} | {lf(b)} |")
        sweep[f"{c:.2f}"] = {"diff_pp": 100 * (a["hit60"] - b["hit60"]), "z": z, "n_hi": a["n"], "n_lo": b["n"], "welch_t": wt}
    res["sweep"] = sweep

    # E. karşı-olgusal sıralama: çarpan olmasaydı top-10 kimler olurdu?
    prom = [r for r in rows_dedup_all if r.get("rank") is not None and int(r["rank"]) <= 10
            and r.get("rank_raw") is not None and int(r["rank_raw"]) > 10 and not is_overbought(r)]
    dem = [r for r in rows_dedup_all if (r.get("rank") is None or int(r["rank"]) > 10)
           and r.get("rank_raw") is not None and int(r["rank_raw"]) <= 10 and not is_overbought(r)]
    kept = [r for r in rows_dedup_all if r.get("rank") is not None and int(r["rank"]) <= 10
            and r.get("rank_raw") is not None and int(r["rank_raw"]) <= 10 and not is_overbought(r)]
    groups = [("TERFİ: çarpanla top-10'a girdi (çarpansız dışında) — strong bonusu sayesinde", prom),
              ("DÜŞÜŞ: çarpanla top-10'dan çıktı (çarpansız içinde) — weak cezası yüzünden", dem),
              ("DEĞİŞMEYEN: iki durumda da top-10", kept)]
    txt, st = table("E. Çarpanın marjinal etkisi (karşı-olgusal sıralama; bağımlı satırlar, bölüm tekilleştirmesi yok)", groups)
    md.append(txt)
    res["counterfactual"] = {k: {kk: vv for kk, vv in v.items() if kk in ("n", "hit60", "net", "t", "lift")} for k, v in st.items()}
    if prom and dem:
        cb = cluster_bootstrap_diff(prom, dem, lambda r: r["e60"]["hit"], n_boot=1000)
        if cb:
            md.append(f"\nTERFİ − DÜŞÜŞ hit60 farkı {100 * cb[0]:+.1f} pp, gün-küme bootstrap %95 GA [{100 * cb[1]:+.1f}, {100 * cb[2]:+.1f}].")
            res["counterfactual"]["diff_prom_dem_pp"] = [100 * x for x in cb]
    return "\n".join(md), res


def penalized_top_share(rows_dedup: list[dict], regime: dict[int, dict], *, mult: float = 0.85, top: int = 10) -> dict:
    """VELOCITY_EXHAUSTION_MODE=penalty gerçekte kaç aşırı alım adayını top-N'de bırakır?
    Tick bazında (sembol başına tek satır) trend_devam + aşırı alım + kalkan kapalı satırlara skor×mult
    uygulanıp yeniden sıralanır. Döner: {n, still_top, share}. Not: ufuklar tekilleştirilmiş satırlarla yaklaşık."""
    by_tick: dict[int, list[dict]] = collections.defaultdict(list)
    for r in rows_dedup:
        by_tick[int(r["tick_ms"])].append(r)
    n = still = 0
    for t, rs in by_tick.items():
        if (regime.get(t) or {}).get("shield") is not False:
            continue

        def adj(r):
            sc = float(r.get("velocity_score") or 0.0)
            if r.get("mode") == "trend_devam" and is_overbought(r):
                sc *= mult
            return sc
        order = sorted(rs, key=adj, reverse=True)
        for i, r in enumerate(order, 1):
            if r.get("mode") == "trend_devam" and is_overbought(r) and r.get("rank") is not None and int(r["rank"]) <= top:
                n += 1
                if i <= top:
                    still += 1
    return {"n": n, "still_top": still, "share": (still / n) if n else None}


def _fl(r: dict, key: str):
    v = r.get(key)
    return None if v is None else float(v)


GATE_VARIANTS = (
    ("MFI>=90 veya RSI>=80 (canlı)", lambda m, r: (m is not None and m >= 90) or (r is not None and r >= 80)),
    ("yalnız MFI>=90", lambda m, r: m is not None and m >= 90),
    ("yalnız RSI>=80", lambda m, r: r is not None and r >= 80),
    ("MFI>=95", lambda m, r: m is not None and m >= 95),
    ("RSI>=85", lambda m, r: r is not None and r >= 85),
    ("MFI>=90 VE RSI>=80", lambda m, r: m is not None and m >= 90 and r is not None and r >= 80),
    ("MFI>=95 veya RSI>=85", lambda m, r: (m is not None and m >= 95) or (r is not None and r >= 85)),
)


def _fmt_g(g: dict) -> str:
    lift = format(100 * g["lift"], "+.1f") if g.get("lift") is not None else "—"
    return "%" + format(100 * g["hit60"], ".1f") + " / " + lift + " / " + format(g["net"], "+.2f")


def gate_sections(eps: list[dict], blocks: dict[str, list[dict]], regime: dict[int, dict],
                  rows_dedup: list[dict]) -> tuple[str, dict]:
    """Aşırı alım kapısı ayrıştırması. eps: rank<=10 bağımsız bölümler (tüm pencere, kapı DAHİL)."""
    md: list[str] = []
    res: dict = {}
    allv = [r for r in eps if r.get("e60")]
    mfi_bins = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 95), (95, 101)]
    rsi_bins = [(0, 60), (60, 70), (70, 75), (75, 80), (80, 85), (85, 101)]
    groups = [("MFI [" + str(a) + ", " + str(b) + ")", [r for r in allv if _fl(r, "mfi") is not None and a <= _fl(r, "mfi") < b]) for a, b in mfi_bins]
    txt, st = table("G1. MFI14(1m) kutuları (tüm pencere, rank<=10 bölümler, kalkan fark etmez)", groups)
    md.append(txt)
    res["mfi_bins"] = {k: {kk: vv for kk, vv in v.items() if kk in ("n", "hit60", "net", "lift")} for k, v in st.items()}
    groups = [("RSI [" + str(a) + ", " + str(b) + ")", [r for r in allv if _fl(r, "rsi") is not None and a <= _fl(r, "rsi") < b]) for a, b in rsi_bins]
    txt, st = table("G1b. RSI14(1m) kutuları (tüm pencere)", groups)
    md.append(txt)
    res["rsi_bins"] = {k: {kk: vv for kk, vv in v.items() if kk in ("n", "hit60", "net", "lift")} for k, v in st.items()}

    md.append("\n#### G2. Kapı varyantları — kalkan KAPALI bölümlerde elenen vs geçen (hit60 / lift pp / net60)")
    names = list(blocks) + ["TÜM"]
    md.append("| varyant | " + " | ".join(names) + " |")
    md.append("|---|" + "---|" * len(names))
    res["variants"] = {}
    for vname, fn in GATE_VARIANTS:
        cells = []
        for bn in names:
            rs = allv if bn == "TÜM" else blocks[bn]
            rs = [r for r in rs if (regime.get(int(r["tick_ms"])) or {}).get("shield") is False]
            el = [r for r in rs if fn(_fl(r, "mfi"), _fl(r, "rsi"))]
            ps = [r for r in rs if not fn(_fl(r, "mfi"), _fl(r, "rsi"))]
            ge, gp = group_stats(el), group_stats(ps)
            if ge.get("n", 0) < 30 or gp.get("n", 0) < 30:
                cells.append("n=" + str(ge.get("n", 0)))
                continue
            cells.append("elenen " + _fmt_g(ge) + " (n=" + str(ge["n"]) + ") · geçen " + _fmt_g(gp))
            res["variants"].setdefault(vname, {})[bn] = {"elim_hit": ge["hit60"], "pass_hit": gp["hit60"], "elim_n": ge["n"],
                                                         "elim_lift": ge.get("lift"), "pass_lift": gp.get("lift"),
                                                         "elim_net": ge["net"], "pass_net": gp["net"]}
        md.append("| " + vname + " | " + " | ".join(cells) + " |")

    pt = penalized_top_share(rows_dedup, regime)
    res["penalty_share"] = pt
    md.append("\n#### H. Skor cezası (x0.85) aşırı alım adaylarını top-10'dan çıkarıyor mu? (trend_devam, kalkan kapalı, tick bazında)")
    share = "—" if pt["share"] is None else "%" + format(100 * pt["share"], ".1f")
    md.append("rank<=10 aşırı alım trend_devam satırı: " + str(pt["n"]) + "; ceza sonrası hâlâ top-10'da: " + str(pt["still_top"]) + " (" + share + ").")
    return "\n".join(md), res


def taker_coarse_by_block(blocks: dict[str, list[dict]], allv: list[dict]) -> tuple[str, dict]:
    """F. Kaba taker kutuları × blok (tutarlılık kontrolü)."""
    bins = [(0.0, 0.35), (0.35, 0.45), (0.45, 0.58), (0.58, 0.70), (0.70, 1.01)]
    names = list(blocks) + ["TÜM"]
    md = ["\n#### F. Kaba taker kutuları × blok (hit60 / lift pp / net60, n)", "| kutu | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    res: dict = {}
    for a, b in bins:
        cells = []
        for bn in names:
            rs = allv if bn == "TÜM" else blocks[bn]
            g = group_stats([r for r in rs if taker_ratio(r) is not None and a <= taker_ratio(r) < b])
            if g.get("n", 0) == 0:
                cells.append("—")
                continue
            cells.append(_fmt_g(g) + " (n=" + str(g["n"]) + ")")
            res.setdefault(format(a, ".2f") + "-" + format(b, ".2f"), {})[bn] = {"hit60": g["hit60"], "lift": g.get("lift"), "net": g["net"], "n": g["n"]}
        md.append("| [" + format(a, ".2f") + ", " + format(b, ".2f") + ") | " + " | ".join(cells) + " |")
    return "\n".join(md), res


# ------------------------------------------------------------------ ana akış
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--btc-1h", default="work/btc_1h_120d.json")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--blocks", default=",".join(DEFAULT_BLOCKS))
    ap.add_argument("--cost", type=float, default=0.225); ap.add_argument("--sl", type=float, default=3.0)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--rank-max", type=int, default=10)
    ap.add_argument("--chance-n", type=int, default=0, help="blok başına şans tabanı örneklemi (0 = tüm bölümler)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out-dir", default="work/validation90")
    ap.add_argument("--db-url", default="")
    args = ap.parse_args(argv)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    import psycopg
    t0 = time.time()
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    start_ms, end_ms = parse_day(args.start), parse_day(args.end, end=True)
    raw = load_jsonl(args.jsonl, start_ms, end_ms)
    cf = counterfactual_ranks(raw)
    rows_all = dedupe_horizon(raw)
    for r in rows_all:
        r["rank_raw"] = cf.get((int(r["tick_ms"]), r["symbol"], int(r.get("horizon_minutes") or 5)))
    del raw
    mark_episodes(rows_all)
    rows = [r for r in rows_all if r.get("rank") is not None and int(r["rank"]) <= args.rank_max]
    mark_episodes(rows)
    print(f"[v90] tüm {len(rows_all)} · rank<={args.rank_max} {len(rows)} · bölüm {sum(1 for r in rows if r['ep'])} ({time.time() - t0:.0f} sn)", flush=True)
    un = sum(1 for r in rows_all if taker_bucket(r) == "unavailable")
    print(f"[v90] taker yok: {un}/{len(rows_all)}", flush=True)

    klines = load_btc_1h(args.btc_1h)
    syms = {r["symbol"] for r in rows_all}
    with psycopg.connect(url, connect_timeout=10) as conn:
        btc5m = load_btc_5m(conn)
        store = load_candles_lowmem(conn, start_ms / 1000.0, syms)
    grid = list(range(start_ms, end_ms, 300_000))
    regime = btc_regime_table(klines, btc5m, grid)
    regime.update(btc_regime_table(klines, btc5m, [r["tick_ms"] for r in rows_all]))
    print(f"[v90] rejim {len(regime)} tick, mum {len(store.d)} sembol ({time.time() - t0:.0f} sn)", flush=True)
    evaluate(rows_all, store, sl=args.sl, cost=args.cost)
    print(f"[v90] sonuçlar ({time.time() - t0:.0f} sn)", flush=True)

    blocks = parse_blocks(args.blocks)
    windows = [(f"{a} .. {b}", a, b) for a, b in blocks] + [(f"TÜM PENCERE {args.start} .. {args.end}", args.start, args.end)]
    raw_md: list[str] = []
    summ: dict = {}
    block_ep: dict[str, list[dict]] = {}
    for label, a, b in windows:
        s_ms, e_ms = parse_day(a), parse_day(b, end=True)
        is_full = label.startswith("TÜM")
        rs_rows = [r for r in rows if in_block(r, s_ms, e_ms)]
        rs_all = [r for r in rows_all if in_block(r, s_ms, e_ms)]
        reg = {t: v for t, v in regime.items() if s_ms <= t <= e_ms}
        if not is_full:
            done = run_chance(rs_rows, store, sample_n=args.chance_n or 10 ** 9, seed=args.seed, sl=args.sl, cost=args.cost)
            print(f"[v90] {label}: şans tabanı {done} ({time.time() - t0:.0f} sn)", flush=True)
        else:
            done = sum(1 for r in rs_rows if r.get("lift") is not None)
        ns = SimpleNamespace(start=a, end=b, cost=args.cost, sl=args.sl, jsonl=args.jsonl, rank_max=args.rank_max, min_n=args.min_n)
        md, summary = build_report(rs_rows, reg, args=ns, store=store, chance_done=done, rows_all=rs_all)
        raw_md.append(f"\n\n# ===== BLOK: {label} =====\n" + md)
        # küme-bootstrap: kalkan açık - kapalı (kapı geçen bölümler)
        eps = [r for r in rs_rows if r.get("ep") and not is_overbought(r) and r.get("e60")]
        on = [r for r in eps if (reg.get(int(r["tick_ms"])) or {}).get("shield") is True]
        off = [r for r in eps if (reg.get(int(r["tick_ms"])) or {}).get("shield") is False]
        summary["boot_shield_hit"] = cluster_bootstrap_diff(on, off, lambda r: r["e60"]["hit"])
        summary["boot_shield_net"] = cluster_bootstrap_diff(on, off, lambda r: r["e60"]["net"])
        epo = [r for r in rs_rows if r.get("ep") and r.get("e60") and (reg.get(int(r["tick_ms"])) or {}).get("shield") is False]
        summary["boot_ob_hit"] = cluster_bootstrap_diff([r for r in epo if is_overbought(r)], [r for r in epo if not is_overbought(r)],
                                                        lambda r: r["e60"]["hit"])
        summary["boot_ob_net"] = cluster_bootstrap_diff([r for r in epo if is_overbought(r)], [r for r in epo if not is_overbought(r)],
                                                        lambda r: r["e60"]["net"])
        # temel çizgi: canlı-benzeri (kapı geçti) — kalkan kapalı (eski canlı) ve kalkandan bağımsız (badge)
        base_off = group_stats(off)
        base_any = group_stats(eps)
        summary["base_shield_off"] = {k: v for k, v in base_off.items() if k != "ci60"}
        summary["base_any"] = {k: v for k, v in base_any.items() if k != "ci60"}
        summ[label] = summary
        if not is_full:
            block_ep[label] = [r for r in rs_rows if r.get("ep") and not is_overbought(r) and r.get("e60")]

    # taker
    ep_live_full = [r for r in rows if r.get("ep") and not is_overbought(r) and r.get("e60")]
    tk_md, tk_res = taker_sections(ep_live_full, block_ep, regime, rows_all, args.min_n)
    raw_md.append("\n\n# ===== TAKER DOĞRULAMA =====\n" + tk_md)
    summ["taker"] = tk_res
    allv_live = [r for r in ep_live_full if taker_bucket(r) != "unavailable"]
    f_md, f_res = taker_coarse_by_block(block_ep, allv_live)
    raw_md.append(f_md)
    summ["taker_coarse"] = f_res
    block_ep_all = {}
    for label, a, b in windows[:-1]:
        s_ms, e_ms = parse_day(a), parse_day(b, end=True)
        block_ep_all[label] = [r for r in rows if r.get("ep") and r.get("e60") and in_block(r, s_ms, e_ms)]
    eps_all = [r for r in rows if r.get("ep") and r.get("e60")]
    g_md, g_res = gate_sections(eps_all, block_ep_all, regime, rows_all)
    raw_md.append("\n\n# ===== ASIRI ALIM KAPISI AYRISTIRMA =====\n" + g_md)
    summ["gate"] = g_res

    (out_dir / "blocks_raw.md").write_text("".join(raw_md), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"[v90] bitti ({time.time() - t0:.0f} sn) -> {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
