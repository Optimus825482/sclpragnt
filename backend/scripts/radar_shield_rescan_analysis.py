"""BTC rejim kalkanı + aşırı alım kapısı — rescan tabanlı geriye dönük ölçüm (2026-10-17).

SORU: `BTC_BEAR_REGIME_SHIELD` (BTC 1H EMA200 altı) ve `mfi/rsi_asiri_alim` kapısı bildirimleri
keserken, kestikleri adaylar sonradan hedefe ulaştı mı? Canlı journal'da kalkan etiketi
(`unified_candidate_outcomes.blocked_by`) yalnız 2026-10-16'dan beri tutulduğu için pencere
GERİYE DOĞRU YENİDEN KURULUR:

  * Adaylar: `rescan_velocity_history.py --no-exhaustion-gate --journal-cap 0` JSONL çıktısı
    (aşırı alım kapısı KAPALI; satırdaki `exhausted` alanı canlıda elenecek adayı etiketler).
  * Kalkan: BTCTRY 1H kapanışları (public kline JSON, 210 barlık pencere) üzerinde canlı
    `macro_sentiment_service._fetch_btc_1h_ema200` ile AYNI `_ema(closes, 200)`; forming barın
    kapanışı = tick anındaki son kapanmış 5m BTC kapanışı. Kalkan AÇIK ⇔ fiyat < EMA200.
  * Sonuç: `historical_candles` 5m, `notification_outcomes_report.eval_window` (TP / ilk SL /
    ufuk sonu, maliyet düşülmüş); şans tabanı aynı modülün `compute_chance` (null3: sembol +
    saat dilimi + 30 dk aralık + 30 dk getiri eşleşmiş rastgele anlar).

ÖN KAYITLI KARAR KURALI (scripts/radar_shield_analysis.py ile aynı, veri görülmeden):
  hit60(kalkan) >= hit60(geçen) - 5 puan  -> KALKAN_FAZLA_SIKI
  hit60(kalkan) <  hit60(geçen) - 10 puan -> KALKAN_ISE_YARIYOR
  aksi -> BELIRSIZ; grup n < min_n -> YETERSIZ_VERI.

Bu betik canlı kodu DEĞİŞTİRMEZ, DB'ye YAZMAZ.

Kullanım (backend/ içinden):
  DATABASE_URL=... python scripts/radar_shield_rescan_analysis.py \
      --jsonl work/rescan_21g_nogate.jsonl --btc-1h work/btc_1h.json \
      --start 2026-09-26 --end 2026-10-16 --out work/shield_rescan.md
`--btc-1h` yoksa Binance TR public REST'ten (BTCTRY 1h, 1000 bar) çekilir ve dosyaya yazılır.
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

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.technical_analysis import _ema  # noqa: E402
from scripts.notification_outcomes_report import CandleStore, TZ, compute_chance, load_candles  # noqa: E402
from scripts.radar_lift_analysis import wilson_interval  # noqa: E402

OVERBOUGHT_PREFIXES = ("mfi_asiri_alim", "rsi_asiri_alim")
DEFAULT_COST = 0.225   # BNB indirimli taker %0.1125 × 2 bacak
DEFAULT_SL = 3.0
TIGHT_MARGIN = 0.05
WORKING_MARGIN = 0.10


# ------------------------------------------------------------------ yükleme
def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + 86_400_000 - 1 if end else ms


def load_jsonl(path: str, start_ms: int, end_ms: int) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not r.get("passes"):
                continue
            t = int(r.get("tick_ms") or float(r["created_at"]) * 1000)
            if t < start_ms or t > end_ms:
                continue
            r["tick_ms"] = t
            rows.append(r)
    return rows


def dedupe_horizon(rows: list[dict]) -> list[dict]:
    """(sembol, tick) başına tek satır; 15 dk ufuk satırı tercih edilir (hedef oradan)."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["symbol"], int(r["tick_ms"]))
        h = int(r.get("horizon_minutes") or 5)
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        # sıralamaya giren (rank dolu) satır öncelikli; eşitse 15 dk ufuk (hedef oradan)
        cur_rank = cur.get("rank") is not None; new_rank = r.get("rank") is not None
        if (new_rank and not cur_rank) or (new_rank == cur_rank and h == 15):
            best[key] = r
    return sorted(best.values(), key=lambda r: (int(r["tick_ms"]), r["symbol"]))


def mark_episodes(rows: list[dict], gap_min: int = 60) -> None:
    """Aynı sembolde 60 dk içindeki tekrarlar tek bölüm sayılır (`ep`=True ilk satır)."""
    last: dict[str, int] = {}
    for r in rows:  # tick sıralı olmalı
        t = int(r["tick_ms"]); s = r["symbol"]
        r["ep"] = (s not in last) or (t - last[s] >= gap_min * 60_000)
        if r["ep"]:
            last[s] = t


def load_btc_1h(path: str) -> list:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    import urllib.request
    url = "https://api.binance.me/api/v3/klines?symbol=BTCTRY&interval=1h&limit=1000"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — public, sabit URL
        data = json.loads(resp.read().decode("utf-8"))
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return data


def merge_klines(*lists: list) -> list:
    """Kline listelerini open_time'a göre tekilleştirir (sonraki liste kazanır) ve sıralar."""
    by_t: dict[int, list] = {}
    for lst in lists:
        for k in lst or []:
            by_t[int(k[0])] = k
    return [by_t[t] for t in sorted(by_t)]


def fetch_btc_1h_range(start_ms: int, end_ms: int, path: str = "", *, symbol: str = "BTCTRY",
                       base_url: str = "https://api.binance.me/api/v3/klines", pause: float = 0.3) -> list:
    """Binance TR public REST'ten 1h klines'ı start_ms..end_ms için sayfalayarak çeker (limit 1000).
    `path` doluysa ve dosya varsa önce okunur, eksik aralık çekilip birleştirilir ve dosyaya yazılır."""
    import urllib.request
    have: list = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            have = json.load(f)
    cur = start_ms
    new: list = []
    while cur <= end_ms:
        url = f"{base_url}?symbol={symbol}&interval=1h&limit=1000&startTime={cur}&endTime={end_ms}"
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — public, sabit URL
            page = json.loads(resp.read().decode("utf-8"))
        if not page:
            break
        new.extend(page)
        nxt = int(page[-1][0]) + 3_600_000
        if nxt <= cur:
            break
        cur = nxt
        if len(page) < 2:
            break
        time.sleep(pause)
    out = merge_klines(have, new)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    return out


def load_btc_5m(conn) -> tuple[np.ndarray, np.ndarray]:
    rows = conn.execute("SELECT open_time, close::float8 FROM historical_candles "
                        "WHERE symbol='BTCTRY' AND timeframe='5m' ORDER BY open_time").fetchall()
    ot = np.array([int(r[0]) for r in rows], dtype=np.int64)
    cl = np.array([float(r[1]) for r in rows], dtype=float)
    return ot, cl


def btc_regime_table(klines: list, btc5m: tuple[np.ndarray, np.ndarray], ticks_ms) -> dict[int, dict]:
    """tick -> {shield, gap_pct, ret4h_pct, ema, price}. Canlı hesabın birebir yeniden kurulumu."""
    ot = np.array([int(k[0]) for k in klines], dtype=np.int64)
    cl = np.array([float(k[4]) for k in klines], dtype=float)
    ot5, cl5 = btc5m
    out: dict[int, dict] = {}
    for t in sorted(set(int(x) for x in ticks_ms)):
        i = int(np.searchsorted(ot, t, side="right")) - 1
        if i < 209:
            out[t] = {"shield": None, "gap_pct": None, "ret4h_pct": None, "ema": None, "price": None}
            continue
        closes = cl[i - 209:i + 1].copy()
        j = int(np.searchsorted(ot5 + 300_000, t, side="right")) - 1
        price = float(cl5[j]) if j >= 0 else float(closes[-1])
        closes[-1] = price
        ema = _ema(closes, 200)
        if not ema:
            out[t] = {"shield": None, "gap_pct": None, "ret4h_pct": None, "ema": None, "price": price}
            continue
        ret4h = (price / float(cl[i - 4]) - 1) * 100 if i >= 4 and cl[i - 4] > 0 else None
        out[t] = {"shield": bool(price < ema), "gap_pct": (price / ema - 1) * 100,
                  "ret4h_pct": ret4h, "ema": float(ema), "price": price}
    return out


def is_overbought(r: dict) -> bool:
    """Canlı kapı: MFI ≥ VELOCITY_MFI_UPPER (90) ya da RSI ≥ VELOCITY_RSI_UPPER (80) → elenir.
    Kapı kapalı koşuda `exhausted` hiç üretilmez; etiket satırdaki mfi/rsi değerlerinden kurulur."""
    ex = str(r.get("exhausted") or "")
    if ex.startswith(OVERBOUGHT_PREFIXES):
        return True
    from app.routers import velocity as V
    mfi = r.get("mfi"); rsi = r.get("rsi")
    if mfi is not None and float(mfi) >= float(V.VELOCITY_MFI_UPPER):
        return True
    return rsi is not None and float(rsi) >= float(V.VELOCITY_RSI_UPPER)


# ------------------------------------------------------------------ ölçüm
def evaluate(rows: list[dict], store: CandleStore, *, sl: float, cost: float) -> None:
    for r in rows:
        det = int(r["tick_ms"]) / 1000.0
        tp = float(r["target_pct"]); entry = float(r["price"])
        r["e15"] = store.eval(r["symbol"], det, entry, tp, 15, sl, cost)
        r["e60"] = store.eval(r["symbol"], det, entry, tp, 60, sl, cost)


def group_stats(rs: list[dict]) -> dict:
    e60 = [r["e60"] for r in rs if r.get("e60")]
    e15 = [r["e15"] for r in rs if r.get("e15")]
    n = len(e60)
    if n == 0:
        return {"n": 0}
    hits = int(sum(1 for x in e60 if x["hit"]))
    net = np.array([x["net"] for x in e60], dtype=float)
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    lifts = [r["lift"] for r in rs if r.get("lift") is not None]
    return {
        "n": n, "n15": len(e15),
        "hit15": (sum(1 for x in e15 if x["hit"]) / len(e15)) if e15 else None,
        "hit60": hits / n, "ci60": wilson_interval(hits, n),
        "mfe": float(np.mean([x["mfe"] for x in e60])), "mae": float(np.mean([x["mae"] for x in e60])),
        "net": float(net.mean()), "net_sd": sd,
        "t": (float(net.mean()) / (sd / math.sqrt(n))) if n > 1 and sd > 0 else None,
        "lift_n": len(lifts), "lift": (float(np.mean(lifts)) if lifts else None),
    }


def welch_t(a: dict, b: dict) -> float | None:
    if a.get("n", 0) < 2 or b.get("n", 0) < 2:
        return None
    va = a["net_sd"] ** 2 / a["n"]; vb = b["net_sd"] ** 2 / b["n"]
    if va + vb <= 0:
        return None
    return (a["net"] - b["net"]) / math.sqrt(va + vb)


def verdict(passed: dict, shield: dict, min_n: int) -> str:
    if passed.get("n", 0) < min_n or shield.get("n", 0) < min_n:
        return "YETERSIZ_VERI"
    d = shield["hit60"] - passed["hit60"]
    if d >= -TIGHT_MARGIN:
        return "KALKAN_FAZLA_SIKI"
    if d < -WORKING_MARGIN:
        return "KALKAN_ISE_YARIYOR"
    return "BELIRSIZ"


def run_chance(rows: list[dict], store: CandleStore, *, sample_n: int, seed: int, sl: float, cost: float) -> int:
    """Bölüm (ep) satırlarından rastgele örneklem için null3 şans tabanı; r['lift'] = hit60 - null3.hit."""
    rng = np.random.default_rng(seed)
    pool = [r for r in rows if r.get("ep") and r.get("e60") and r["symbol"] in store.d]
    if not pool:
        return 0
    idx = rng.permutation(len(pool))[:sample_n]
    recs = []
    for i in idx:
        r = pool[int(i)]
        det = int(r["tick_ms"]) / 1000.0
        hour = int(((det + 3 * 3600) // 3600) % 24)
        recs.append({"id": int(i), "sym": r["symbol"], "tp": float(r["target_pct"]), "det": det,
                     "hour": hour, 60: r["e60"], "_row": r})
    compute_chance(recs, store, rng, sl=sl, cost=cost)
    done = 0
    for rec in recs:
        null3 = rec.get("null3") or rec.get("null2") or rec.get("null")
        if null3:
            rec["_row"]["lift"] = float(rec[60]["hit"]) - float(null3["hit"])
            rec["_row"]["null_hit"] = float(null3["hit"])
            done += 1
    return done


# ------------------------------------------------------------------ rapor
def _pct(v) -> str:
    return "—" if v is None else f"%{100 * v:.1f}"


def _num(v, d=2) -> str:
    return "—" if v is None else f"{v:+.{d}f}"


def _row(name: str, g: dict) -> str:
    if g.get("n", 0) == 0:
        return f"| {name} | 0 | — | — | — | — | — | — | — |"
    ci = g.get("ci60")
    ci_s = f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}]" if ci else ""
    t = g.get("t")
    net_s = f"{g['net']:+.2f}" + (f" (t {t:+.1f})" if t is not None else "")
    lift_s = (f"{100 * g['lift']:+.1f} pp (n={g['lift_n']})" if g.get("lift") is not None else "—")
    return (f"| {name} | {g['n']} | {_pct(g.get('hit15'))} | {_pct(g['hit60'])}{ci_s} | "
            f"{g['mfe']:+.2f} | {g['mae']:+.2f} | {net_s} | {lift_s} |")


HEADER = ("| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |\n"
          "|---|---|---|---|---|---|---|---|")


def build_report(rows: list[dict], regime: dict[int, dict], *, args, store: CandleStore,
                 chance_done: int, rows_all: list[dict] | None = None) -> tuple[str, dict]:
    rows_all = rows_all or rows
    ep = [r for r in rows if r.get("ep")]
    summary: dict = {"window": [args.start, args.end], "cost": args.cost, "sl": args.sl,
                     "rows_total": len(rows), "episodes": len(ep), "chance_rows": chance_done}
    md: list[str] = []
    md.append(f"# Rejim kalkanı + aşırı alım kapısı — rescan ölçümü ({args.start} .. {args.end})")
    md.append(f"Aday kaynağı: `{os.path.basename(args.jsonl)}` (aşırı alım kapısı kapalı, journal cap 0). "
              f"Birincil küme: tick başına sıralamaya giren adaylar (rank ≤ {args.rank_max}; canlı bildirim havuzuna en yakın) "
              f"— satır {len(rows)} (sembol-tick), bağımsız bölüm (60 dk) {len(ep)}; tüm geçenler {len(rows_all)} satır. "
              f"Mum: historical_candles 5m, {len(store.d)} sembol. Net = TP / ilk SL −{args.sl:g}% / ufuk sonu, "
              f"−{args.cost:g}% maliyet. Şans tabanı (null3) {chance_done} bölüm satırında ölçüldü.")

    # kalkan payı
    ticks = sorted(regime)
    by_day: dict[str, list[bool]] = collections.defaultdict(list)
    for t in ticks:
        s = regime[t]["shield"]
        if s is not None:
            by_day[datetime.fromtimestamp(t / 1000, TZ).strftime("%m-%d")].append(s)
    md.append("\n## 0. Kalkan ne kadar süre açıktı? (5 dk tick payı, gün başına)")
    md.append(" · ".join(f"{d} %{100 * np.mean(v):.0f}" for d, v in sorted(by_day.items())))
    all_on = [s for v in by_day.values() for s in v]
    summary["shield_share"] = float(np.mean(all_on)) if all_on else None
    md.append(f"\nToplam: tick'lerin **%{100 * summary['shield_share']:.0f}**'inde kalkan açık (BTC < 1H EMA200).")

    def tbl(title: str, groups: list[tuple[str, list[dict]]], key: str) -> None:
        md.append(f"\n## {title}")
        md.append(HEADER)
        summary[key] = {}
        for name, rs in groups:
            g = group_stats(rs)
            summary[key][name] = {k: v for k, v in g.items() if k != "ci60"}
            md.append(_row(name, g))

    def sel(rs, *, shield=None, ob=None, mode=None, soft=None):
        out = []
        for r in rs:
            reg = regime.get(int(r["tick_ms"])) or {}
            if shield is not None and reg.get("shield") != shield:
                continue
            if ob is not None and is_overbought(r) != ob:
                continue
            if mode is not None and (r.get("mode") or "") != mode:
                continue
            if soft is not None:
                gap = reg.get("gap_pct"); r4 = reg.get("ret4h_pct")
                if reg.get("shield") is not True:
                    continue
                hard = (gap is not None and gap <= -1.0) and (r4 is not None and r4 < 0)
                if hard != soft:
                    continue
            out.append(r)
        return out

    # 1. kalkan (bağımsız bölümler) — aşırı alım kapısı canlıdaki gibi AÇIK (ob=False)
    live_like = sel(ep, ob=False)
    g_off = sel(live_like, shield=False); g_on = sel(live_like, shield=True)
    tbl("1. BTC rejim kalkanı (canlı kapılar aynen; bağımsız bölümler)",
        [("Kalkan KAPALI — BTC ≥ EMA200 (bildirim gitti)", g_off), ("Kalkan AÇIK — BTC < EMA200 (bildirim KESİLDİ)", g_on)], "shield")
    st_off, st_on = group_stats(g_off), group_stats(g_on)
    v = verdict(st_off, st_on, args.min_n)
    wt = welch_t(st_on, st_off)
    summary["shield_verdict"] = v
    md.append(f"\nÖn kayıtlı kural: **{v}** (hit60 fark {100 * ((st_on.get('hit60') or 0) - (st_off.get('hit60') or 0)):+.1f} puan; "
              f"net60 farkı Welch t {wt:+.2f})." if wt is not None else f"\nÖn kayıtlı kural: **{v}**.")

    # 1b. kalkanın yumuşatılmış hali
    tbl("1b. Kalkan AÇIKKEN alt kümeler — yumuşatma adayı (sert = EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0)",
        [("Kalkan açık, YUMUŞAK bölge (gap > −1% ya da BTC 4s ≥ 0) → yumuşatılırsa bildirim gider", sel(live_like, soft=False)),
         ("Kalkan açık, SERT bölge (gap ≤ −1% ve BTC 4s < 0) → yine kesilir", sel(live_like, soft=True))], "shield_soft")

    # 2. aşırı alım kapısı (kalkan kapalıyken; yani bildirime tek engel bu kapı)
    tbl("2. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan KAPALI bölümlerde",
        [("Kapı GEÇTİ (bildirim gitti)", sel(ep, shield=False, ob=False)),
         ("Kapı ELEDİ (mfi/rsi_asiri_alim)", sel(ep, shield=False, ob=True))], "overbought")
    tbl("2b. Aşırı alım kapısı — trend_devam modu, kalkan KAPALI",
        [("trend_devam · geçti", sel(ep, shield=False, ob=False, mode="trend_devam")),
         ("trend_devam · aşırı alım elendi", sel(ep, shield=False, ob=True, mode="trend_devam"))], "overbought_trend")

    # 3. 2×2
    tbl("3. Kalkan × aşırı alım (bağımsız bölümler)",
        [("kalkan kapalı · kapı geçti", sel(ep, shield=False, ob=False)),
         ("kalkan kapalı · aşırı alım", sel(ep, shield=False, ob=True)),
         ("kalkan açık · kapı geçti", sel(ep, shield=True, ob=False)),
         ("kalkan açık · aşırı alım", sel(ep, shield=True, ob=True))], "cross")

    # 4. trend_devam × kalkan
    tbl("4. trend_devam modu × kalkan (kapı geçen)",
        [("trend_devam · kalkan kapalı", sel(ep, shield=False, ob=False, mode="trend_devam")),
         ("trend_devam · kalkan açık", sel(ep, shield=True, ob=False, mode="trend_devam"))], "trend_shield")

    # 5. tüm satırlar (bölüm tekilleştirmesiz) — büyük n, bağımlı
    tbl("5. Aynı kırılım, TÜM geçen adaylar (rank sınırı yok; bağımlı satırlar — yön teyidi)",
        [("kalkan kapalı · geçti", sel(rows_all, shield=False, ob=False)), ("kalkan açık · geçti", sel(rows_all, shield=True, ob=False)),
         ("kalkan kapalı · aşırı alım", sel(rows_all, shield=False, ob=True)), ("kalkan açık · aşırı alım", sel(rows_all, shield=True, ob=True))], "all_rows")

    md.append("\n## Sınırlar")
    md.append("- Pencere kısa/tek dönem olabilir; kalkanın açık olduğu günler kümelenmiş (rejim-dönem karışıklığı olası). Çoklu dönem için scripts/validation90_report.py.")
    md.append("- Rescan sapmaları (spread, taker oranı, ML hedef, kadans) docs/RESCAN_HARNESS.md'de; canlı adayların ~%90'ı yeniden üretiliyor.")
    md.append("- Giriş = aday fiyatı (bildirim anı); gecikmeli dolum yok. Hedef = adayın kendi target_pct'si; SL sabit.")
    md.append("- Şans tabanı yalnız örneklemde; 'şansa göre' sütunu hit60 − null3(hit). Çoklu karşılaştırma: tek t > 2 yeterli sayılmaz.")
    return "\n".join(md) + "\n", summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--btc-1h", default="work/btc_1h.json")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--cost", type=float, default=DEFAULT_COST); ap.add_argument("--sl", type=float, default=DEFAULT_SL)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--rank-max", type=int, default=10, help="birincil küme: tick başına sıralama ≤ N (0 = hepsi)")
    ap.add_argument("--chance-n", type=int, default=3000); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="work/shield_rescan.md"); ap.add_argument("--json", default="")
    ap.add_argument("--db-url", default="")
    args = ap.parse_args(argv)
    url = args.db_url or os.getenv("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL gerekli")
    import psycopg
    t0 = time.time()
    start_ms, end_ms = parse_day(args.start), parse_day(args.end, end=True)
    rows_all = dedupe_horizon(load_jsonl(args.jsonl, start_ms, end_ms))
    mark_episodes(rows_all)
    rows = [r for r in rows_all if not args.rank_max or (r.get("rank") is not None and int(r["rank"]) <= args.rank_max)]
    mark_episodes(rows)
    print(f"[shield] tüm {len(rows_all)} · birincil (rank≤{args.rank_max}) {len(rows)}, bölüm {sum(1 for r in rows if r['ep'])} ({time.time() - t0:.0f} sn)")
    klines = load_btc_1h(args.btc_1h)
    with psycopg.connect(url, connect_timeout=10) as conn:
        btc5m = load_btc_5m(conn)
        store = load_candles(conn, start_ms / 1000.0)
    regime = btc_regime_table(klines, btc5m, [r["tick_ms"] for r in rows_all])
    # kalkan payı için tüm 5 dk ızgarası
    grid = list(range(start_ms, end_ms, 300_000))
    regime.update(btc_regime_table(klines, btc5m, grid))
    print(f"[shield] rejim {len(regime)} tick, mum {len(store.d)} sembol ({time.time() - t0:.0f} sn)")
    evaluate(rows_all, store, sl=args.sl, cost=args.cost)
    print(f"[shield] sonuçlar ({time.time() - t0:.0f} sn)")
    done = run_chance(rows, store, sample_n=args.chance_n, seed=args.seed, sl=args.sl, cost=args.cost)
    print(f"[shield] şans tabanı {done} satır ({time.time() - t0:.0f} sn)")
    md, summary = build_report(rows, regime, args=args, store=store, chance_done=done, rows_all=rows_all)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
