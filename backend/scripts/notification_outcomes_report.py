"""Bildirim (ve sinyal) sonuç kalitesi ölçümü — kalıcı analiz sistemi.

SORU: Bildirimden SONRA (detected_at'ten sonra açılan 5m mumlarla) fiyat
bildirimin hedefine ulaştı mı; bu, aynı sembolde rastgele seçilmiş eşleşmiş
anların (şans tabanı) üstünde mi?

ÖLÇÜ (salt-okunur; `historical_candles` 5m):
  * hit30/60/120  : ufuk içinde MFE >= hedef (bildirimin target_pct'i; boşsa 2.0).
  * MFE / MAE     : giriş fiyatına göre ufuk içi en yüksek / en düşük.
  * net proxy     : TP / ilk SL (aynı mumda SL önce) / ufuk sonu kapanış, maliyet düşülmüş.
  * şans tabanı   : aynı sembol + aynı hedef, bildirimden >=2 sa uzak <=30 rastgele an;
                    (1) saat dilimi, (2) + son 30dk aralığı (volatilite), (3) + son 30dk getirisi.
  * kırılımlar    : hafta / aile / kaynak kombinasyonu / mode / skor kovası / ufuk / saat,
                    karşı-olgusal kapı senaryoları, uygulama etiketi çapraz kontrolü,
                    tekrarsız (60 dk cooldown) varyant, precision@k, Spearman.

KAYNAKLAR:
  --source notifications (varsayılan) : `monitoring_notifications` (günlük 2026-09-16'dan başlar).
  --source signals                    : `signals` tablosu; yalnız `--signals-actions`
      (varsayılan BUY_SIGNAL) satırları giriş sayılır. Hedef kolonu yoktur, sabit hedefler
      1.5 / 2 / 3 % ayrı ayrı ölçülür; `mode` yerine `strategy` ile kırılır. Eski
      stratejiler (PUMP_MONITOR, BB_MFI_*, FISHER_* ...) kaldırılmıştır; rapor her
      stratejinin tarih aralığını yazar ki sonuçlar karıştırılmasın.

Bu modül import anında DATABASE_URL okumaz; yalnız main() içinde okunur.
Konsol çıktısı için: PYTHONIOENCODING=utf-8 ayarlayın (Windows).

KULLANIM (backend klasöründen):
    python scripts/notification_outcomes_report.py --days 30 --out rapor.md
    python scripts/notification_outcomes_report.py --since 2026-09-16 --json --out rapor.md
    python scripts/notification_outcomes_report.py --source signals --days 60 --out sinyal_60g.md
    python scripts/notification_outcomes_report.py --days 14 \
        --modes-disabled notr,v_donusu,llm_ikinci_goz --unified-min-score 95 --min-n 30
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
from typing import Any, Callable, Iterable

import numpy as np

TZ = timezone(timedelta(hours=3))  # İstanbul (DST yok)
COST = 0.35          # gidiş-dönüş maliyet, % (bkz. docs/RADAR_ESIK_SOZLESMESI.md)
SL = 3.0             # net proxy sert stop, %
HORIZ = (30, 60, 120)
NULL_K = 30          # şans tabanı: bildirim başına en çok rastgele an
SIGNAL_TARGETS = (1.5, 2.0, 3.0)
DEFAULT_MODES_DISABLED = ("notr", "v_donusu", "llm_ikinci_goz")
SQUEEZE = frozenset({"short_squeeze", "snapback"})


# ------------------------------------------------------------------ istatistik
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson %95 güven aralığı (yüzde olarak); n=0 -> (nan, nan)."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def _avg_ranks(a: np.ndarray) -> np.ndarray:
    """Eşitlikte ortalama sıra (1 tabanlı)."""
    a = np.asarray(a, float)
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    ends = np.cumsum(cnt)
    avg = ends - (cnt - 1) / 2.0
    return avg[inv]


def spearman(x: Iterable[float], y: Iterable[float]) -> tuple[float, float]:
    """Spearman rho ve yaklaşık iki yönlü p (normal yaklaşımı; n>=30 için uygun).

    scipy gerektirmez. Sabit dizi -> (nan, nan).
    """
    xa, ya = np.asarray(list(x), float), np.asarray(list(y), float)
    n = len(xa)
    if n < 3 or len(ya) != n:
        return float("nan"), float("nan")
    rx, ry = _avg_ranks(xa), _avg_ranks(ya)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan"), float("nan")
    rho = float(np.corrcoef(rx, ry)[0, 1])
    if abs(rho) >= 1.0:
        return rho, 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return rho, math.erfc(abs(t) / math.sqrt(2))


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """2x2 [[a,b],[c,d]] için iki yönlü Fisher exact p (hipergeometrik toplam)."""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2

    def lpmf(x: int) -> float:
        return (math.lgamma(n1 + 1) - math.lgamma(x + 1) - math.lgamma(n1 - x + 1)
                + math.lgamma(n2 + 1) - math.lgamma(k - x + 1) - math.lgamma(n2 - k + x + 1)
                - (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)))
    lo, hi = max(0, k - n2), min(n1, k)
    p_obs = lpmf(a)
    tot = 0.0
    for x in range(lo, hi + 1):
        lp = lpmf(x)
        if lp <= p_obs + 1e-9:
            tot += math.exp(lp)
    return min(1.0, tot)


# ---------------------------------------------------------------- mum deposu
class CandleStore:
    """Sembol -> (open_time_ms, high, low, close) dizileri (+ isteğe bağlı open)."""

    def __init__(self, series: dict[str, tuple[np.ndarray, ...]]):
        self.d: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        self.op: dict[str, np.ndarray] = {}
        for s, arrs in series.items():
            self.d[s] = (arrs[0], arrs[1], arrs[2], arrs[3])
            if len(arrs) > 4:
                self.op[s] = arrs[4]
        if self.d:
            self.tmin = min(v[0][0] for v in self.d.values()) / 1000
            self.tmax = max(v[0][-1] for v in self.d.values()) / 1000 + 300
        else:
            self.tmin = self.tmax = 0.0

    @classmethod
    def from_rows(cls, rows: Iterable[tuple]) -> "CandleStore":
        """rows: (symbol, open_time_ms, high, low, close[, open]) — sembol,zaman sıralı olmalı."""
        acc: dict[str, list] = collections.defaultdict(list)
        for r in rows:
            acc[r[0]].append(tuple(float(x) for x in r[1:]))
        series = {}
        for s, v in acc.items():
            a = np.array(sorted(v), dtype=float)
            cols = [a[:, i] for i in range(a.shape[1])]
            series[s] = tuple(cols)
        return cls(series)

    def eval(self, sym: str, det: float, entry: float, tp: float, H: int,
             sl: float = SL, cost: float = COST) -> dict | None:
        """Bildirimden (det, sn) SONRA açılan mumlarla H dk'lık sonuç; kapsam yetersizse None."""
        if sym not in self.d:
            return None
        return eval_window(*self.d[sym], det, entry, tp, H, sl, cost)


def eval_window(ot: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray,
                det: float, entry: float, tp: float, H: int,
                sl: float = SL, cost: float = COST) -> dict | None:
    """Saf fonksiyon: tek pencere. Yalnız open_time > det*1000 mumlar kullanılır."""
    det_ms = det * 1000
    i0 = int(np.searchsorted(ot, det_ms, side="right"))
    end_ms = det_ms + H * 60000
    i1 = int(np.searchsorted(ot, end_ms, side="left"))
    if i0 >= len(ot) or ot[i0] - det_ms > 600000:
        return None
    if i1 - i0 < max(1, int(H / 5) - 3):
        return None
    if ot[i1 - 1] < end_ms - 600000:
        return None
    h, l, c = hi[i0:i1], lo[i0:i1], cl[i0:i1]
    mfe = (h.max() / entry - 1) * 100
    mae = (l.min() / entry - 1) * 100
    slm = l <= entry * (1 - sl / 100)
    tpm = h >= entry * (1 + tp / 100)
    big = 10 ** 9
    isl = int(np.argmax(slm)) if slm.any() else big
    itp = int(np.argmax(tpm)) if tpm.any() else big
    if isl <= itp and isl < big:
        ret = -sl
    elif itp < big:
        ret = tp
    else:
        ret = (c[-1] / entry - 1) * 100
    return dict(mfe=float(mfe), mae=float(mae), hit=bool(mfe >= tp), net=float(ret - cost))


# ------------------------------------------------------------- satır hazırlama
def parse_sources(s: Any) -> list[str]:
    """`sources` kolonunu (JSON liste / virgüllü metin) sıralı liste yapar."""
    if s is None or s == "":
        return []
    if isinstance(s, (list, tuple)):
        return sorted(str(x) for x in s)
    try:
        v = json.loads(s)
        return sorted(str(x) for x in v) if isinstance(v, list) else [str(v)]
    except Exception:
        return sorted(x.strip() for x in re.split(r"[,\s]+", str(s).strip("[]{}\"")) if x)


def score_bucket(x: float) -> str:
    if x < 70:
        return "1 <70"
    if x < 85:
        return "2 70-85"
    if x < 95:
        return "3 85-95"
    if x < 100:
        return "4 95-99.9"
    return "5 100+"


def hour_bin(h: int) -> str:
    a = (h // 3) * 3
    return f"{a:02d}-{a + 2:02d}"


def normalize_notification_row(row: tuple) -> dict:
    """monitoring_notifications satırı -> ortak sözlük (sütun sırası _NOTIF_SQL)."""
    (i, sym, sc, tp, pr, hz, mode, det, src, cid, ost, smfe, smae, mv, lv) = row
    return dict(id=i, symbol=sym, score=sc if sc is not None else 0.0, target_pct=tp, price=pr,
                horizon_minutes=hz, mode=mode or "(bos)", detected_at=float(det),
                sources=parse_sources(src), outcome_status=ost, mfe_pct=smfe, mae_pct=smae,
                macd_mtf_verdict=mv, llm_verdict=lv)


def normalize_signal_row(row: tuple) -> dict:
    """signals satırı (id, timestamp, symbol, action, price, strategy) -> ortak sözlük."""
    (i, ts, sym, action, pr, strategy) = row
    return dict(id=i, symbol=sym, score=None, target_pct=None, price=pr, horizon_minutes=None,
                mode=strategy or "(bos)", detected_at=float(ts), sources=[], outcome_status=None,
                mfe_pct=None, mae_pct=None, macd_mtf_verdict=None, llm_verdict=None, action=action)


def build_records(rows: list[dict], store: CandleStore, *, tp_override: float | None = None,
                  tp_default: float = 2.0, sl: float = SL, cost: float = COST,
                  horizons: tuple[int, ...] = HORIZ) -> tuple[list[dict], dict]:
    """Ortak satırları mum sonuçlarıyla zenginleştirir. (kayıtlar, atlama sayaçları) döner."""
    N: list[dict] = []
    skip_sym: collections.Counter = collections.Counter()
    skip_hz: collections.Counter = collections.Counter()
    scalebad = 0
    for row in rows:
        sym = row["symbol"]
        det = row["detected_at"]
        tp = tp_override if tp_override else (row["target_pct"] if row["target_pct"] and row["target_pct"] > 0 else tp_default)
        if sym not in store.d:
            skip_sym[sym] += 1
            continue
        ot, hi, lo, cl = store.d[sym]
        j = int(np.searchsorted(ot, det * 1000, side="right"))
        pr = row["price"]
        entry = pr if pr and pr > 0 else (cl[j - 1] if j > 0 else None)
        if entry is None:
            skip_sym[sym] += 1
            continue
        if j < len(ot) and abs(entry / cl[j] - 1) > 0.2:
            scalebad += 1
        r = dict(row)
        r.update(sym=sym, tp=tp, det=det, entry=entry, hz=row["horizon_minutes"], src=row["sources"],
                 ost=row["outcome_status"], smfe=row["mfe_pct"], smae=row["mae_pct"],
                 mv=row["macd_mtf_verdict"], lv=row["llm_verdict"])
        for H in horizons:
            e = store.eval(sym, det, entry, tp, H, sl, cost)
            r[H] = e
            if e is None:
                skip_hz[H] += 1
        d = datetime.fromtimestamp(det, TZ)
        r["day"] = d.strftime("%m-%d")
        r["hour"] = d.hour
        r["week"] = f"H{d.isocalendar()[1]}"
        r["fam"] = r["src"] or ["(bos)"]
        r["combo"] = "+".join(r["src"]) if r["src"] else "(bos)"
        N.append(r)
    return N, dict(skip_sym=skip_sym, skip_hz=skip_hz, scalebad=scalebad)


def dedup(recs: list[dict], cooldown_s: float = 3600) -> list[dict]:
    """Aynı sembolde cooldown içindeki ikinci ve sonraki kayıtları atar (erken olan kalır)."""
    keep, last = [], {}
    for r in sorted(recs, key=lambda r: r["det"]):
        if r["sym"] in last and r["det"] - last[r["sym"]] < cooldown_s:
            continue
        last[r["sym"]] = r["det"]
        keep.append(r)
    return keep


def mark_dedup(N: list[dict]) -> None:
    ok = [r for r in N if r.get(60)]
    ids = {r["id"] for r in dedup(ok)}
    for r in N:
        r["dd"] = r["id"] in ids


# ------------------------------------------------------------ şans tabanı
def compute_chance(N: list[dict], store: CandleStore, rng: np.random.Generator, *,
                   k: int = NULL_K, sl: float = SL, cost: float = COST) -> None:
    """Her ölçülmüş kayda null / null2 / null3 şans tabanını ekler (kaynaktaki ile aynı mantık).

    null  : aynı sembol + aynı hedef, +-1 saat dilimi
    null2 : + son 30dk high-low aralığı benzer (+-%25, en az 0.4pt)
    null3 : + son 30dk getirisi benzer (+-%25, en az 0.4pt)
    Rastgele anlar bildirimden >=2 sa uzaktır; giriş = o anın kapanışı, sonuç sonraki mumlardan.
    En az 8 an bulunamazsa taban None kalır.
    """
    cache: dict[str, tuple] = {}

    def trail(sym: str):
        if sym in cache:
            return cache[sym]
        ot, hi, lo, cl = store.d[sym]
        n = len(ot)
        rg = np.full(n, np.nan)
        rt = np.full(n, np.nan)
        if n > 7:
            swh = np.lib.stride_tricks.sliding_window_view(hi, 6).max(axis=1)
            swl = np.lib.stride_tricks.sliding_window_view(lo, 6).min(axis=1)
            rg[5:] = swh / swl - 1
            rt[6:] = cl[6:] / cl[:-6] - 1
        hrs = ((ot / 1000 + 3 * 3600) // 3600 % 24).astype(int)
        cache[sym] = (rg, rt, hrs)
        return cache[sym]

    def run_null(sym: str, tp: float, js: np.ndarray):
        ot, hi, lo, cl = store.d[sym]
        res = []
        for j in js:
            e = store.eval(sym, (ot[j] + 299999) / 1000, cl[j], tp, 60, sl, cost)
            if e:
                res.append(e)
            if len(res) >= k:
                break
        if len(res) < 8:
            return None
        return dict(hit=float(np.mean([x["hit"] for x in res])), net=float(np.mean([x["net"] for x in res])), k=len(res))

    for r in N:
        r["null"] = r["null2"] = r["null3"] = None
        if not r.get(60):
            continue
        ot, hi, lo, cl = store.d[r["sym"]]
        rg, rt, hrs = trail(r["sym"])
        j0 = int(np.searchsorted(ot + 300000, r["det"] * 1000, side="right")) - 1
        valid = np.zeros(len(ot), bool)
        valid[6:len(ot) - 30] = True
        valid &= np.abs(ot / 1000 - r["det"]) >= 7200
        dh = np.abs(hrs - r["hour"])
        dh = np.minimum(dh, 24 - dh)
        c1 = valid & (dh <= 1)
        r["null"] = run_null(r["sym"], r["tp"], rng.permutation(np.where(c1)[0]))
        if j0 >= 6 and not np.isnan(rg[j0]):
            rgn, rtn = rg[j0], rt[j0]
            c2 = valid & (np.abs(rg - rgn) <= max(0.004, 0.25 * rgn))
            r["null2"] = run_null(r["sym"], r["tp"], rng.permutation(np.where(c2)[0]))
            c3 = c2 & (np.abs(rt - rtn) <= max(0.004, 0.25 * abs(rtn)))
            r["null3"] = run_null(r["sym"], r["tp"], rng.permutation(np.where(c3)[0]))


# ------------------------------------------------------------- senaryolar
def build_scenarios(modes_disabled: Iterable[str], unified_min_score: float,
                    has_score: bool = True) -> list[tuple[str, Callable[[dict], bool]]]:
    """Karşı-olgusal kapı senaryoları: (ad, süzgeç).

    'güncel politika' = kapatılan modlar çıkar + unified yalnız skor >= unified_min_score.
    """
    dis = set(modes_disabled)
    not_squeeze = lambda r: not (r["src"] and set(r["src"]) <= SQUEEZE)  # noqa: E731
    mode_ok = lambda r: r["mode"] not in dis  # noqa: E731

    def policy(r: dict) -> bool:
        if not mode_ok(r):
            return False
        if has_score and r["mode"] == "unified" and (r["score"] or 0) < unified_min_score:
            return False
        return True

    sc = [
        ("0 Orijinal (kapisiz)", lambda r: True),
        ("a short_squeeze/snapback-yalniz cikar", not_squeeze),
        (f"b kapali modlar cikar ({','.join(sorted(dis)) or '-'})", mode_ok),
        (f"c GUNCEL POLITIKA = b + unified skor>={unified_min_score:g}", policy),
    ]
    if has_score:
        sc.append(("d = c + tum skor>=95", lambda r: policy(r) and r["score"] >= 95))
    sc.append(("e = c + yalniz trend_devam", lambda r: policy(r) and r["mode"] == "trend_devam"))
    return sc


# ------------------------------------------------------------ tablo yardımcıları
def _vals(recs: list[dict], H: int) -> list[dict]:
    return [r[H] for r in recs if r.get(H)]


def _nanmean(x) -> float:
    x = list(x)
    return float(np.mean(x)) if x else float("nan")


HDR = ("| {g} | n60 | hit30% | hit60% [Wilson95] | hit120% | med MFE60 / MAE60 | net60% ±95%CI | "
       "sans hit60% (saat / vol / vol+getiri) | sans net60 (vol+getiri) | tekrarsiz n / hit60 |\n"
       "|---|---|---|---|---|---|---|---|---|---|")


def fmt_row(label: str, recs: list[dict], min_n: int = 30) -> str:
    v60 = _vals(recs, 60)
    n = len(v60)
    if n == 0:
        return f"| {label} | 0 | - | - | - | - | - | - | - | - |"
    k = sum(x["hit"] for x in v60)
    lo, hi = wilson(k, n)

    def hh(H: int) -> str:
        v = _vals(recs, H)
        return f"{100 * np.mean([x['hit'] for x in v]):.1f}" if v else "-"
    net = np.array([x["net"] for x in v60])
    se = net.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")

    def nm(key: str, f: str) -> float:
        return _nanmean(r[key][f] for r in recs if r.get(60) and r.get(key))
    nulls = f"{100 * nm('null', 'hit'):.1f} / {100 * nm('null2', 'hit'):.1f} / {100 * nm('null3', 'hit'):.1f}"
    ddr = [r for r in recs if r.get(60) and r.get("dd")]
    ddt = f"{len(ddr)} / {100 * np.mean([r[60]['hit'] for r in ddr]):.1f}" if ddr else "-"
    mark = "" if n >= min_n else f" (n<{min_n})"
    return (f"| {label}{mark} | {n} | {hh(30)} | **{100 * k / n:.1f}** [{lo:.0f},{hi:.0f}] | {hh(120)} | "
            f"{np.median([x['mfe'] for x in v60]):.2f} / {np.median([x['mae'] for x in v60]):.2f} | "
            f"{net.mean():+.2f}±{1.96 * se:.2f} | {nulls} | {nm('null3', 'net'):+.2f} | {ddt} |")


def group_by(recs: list[dict], keyf: Callable, multi: bool = False) -> dict:
    g: dict = collections.defaultdict(list)
    for r in recs:
        ks = keyf(r)
        for k in (ks if multi else [ks]):
            g[k].append(r)
    return g


def table(out: list[str], title: str, groups: dict, *, sort: str = "key", minn: int = 1,
          g: str = "grup", min_n: int = 30) -> None:
    out.append(f"\n### {title}")
    out.append(HDR.format(g=g))
    items = [(k, v) for k, v in groups.items() if len(_vals(v, 60)) >= minn]
    if sort == "key":
        items.sort(key=lambda x: str(x[0]))
    elif sort == "n":
        items.sort(key=lambda x: -len(_vals(x[1], 60)))
    for k, v in items:
        out.append(fmt_row(str(k), v, min_n))


# --------------------------------------------------------------- rapor gövdesi
def analyze(N: list[dict], *, label: str, has_score: bool, has_sources: bool, has_labels: bool,
            modes_disabled: Iterable[str], unified_min_score: float, min_n: int,
            skips: dict | None = None) -> tuple[list[str], dict]:
    """Kayıtlardan (şans tabanı hesaplanmış) markdown satırları + özet sözlük üretir."""
    out: list[str] = []
    summary: dict = {"label": label}
    ok = [r for r in N if r.get(60)]
    wk_days: dict = collections.defaultdict(list)
    for r in N:
        wk_days[r["week"]].append(r["day"])
    weeks = sorted(wk_days)

    out.append(f"\n## {label}")
    if skips:
        out.append(f"Toplam kayit {len(N) + sum(skips['skip_sym'].values())}; mumu olmayan sembol nedeniyle atlanan: "
                   f"{sum(skips['skip_sym'].values())} ({len(skips['skip_sym'])} sembol) {dict(skips['skip_sym'].most_common(5))}; "
                   "ufuk kapsami yetersiz (atlanan): " + ", ".join(f"{H}dk={skips['skip_hz'][H]}" for H in HORIZ)
                   + f"; fiyat/mum olcek uyumsuz(>20%): {skips['scalebad']}")
    out.append(f"Olculen (hit60 var): {len(ok)}. Bos mode: {sum(1 for r in N if r['mode'] == '(bos)')}")
    if not ok:
        out.append("\nOlculen kayit yok; rapor bos.")
        summary["n60"] = 0
        return out, summary
    out.append("ISO haftalar (Istanbul): " + "; ".join(f"{w} {min(d)}..{max(d)}" for w, d in sorted(wk_days.items()))
               + " (ilk ve son hafta kismi)")

    # --- mode / strateji kapsam tablosu (tarih aralıkları)
    rng_t: dict = collections.defaultdict(list)
    for r in N:
        rng_t[r["mode"]].append(r["det"])
    out.append("\n### Mode / strateji kapsami (tarih araligi)")
    out.append("| mode/strateji | ilk | son | kayit | olculen (hit60) |")
    out.append("|---|---|---|---|---|")
    for m, ts in sorted(rng_t.items(), key=lambda x: -len(x[1])):
        meas = sum(1 for r in ok if r["mode"] == m)
        out.append(f"| {m} | {datetime.fromtimestamp(min(ts), TZ):%Y-%m-%d} | {datetime.fromtimestamp(max(ts), TZ):%Y-%m-%d} | {len(ts)} | {meas} |")

    # --- 1. genel
    out.append("\n### 1. Genel ve haftalik kararlilik")
    out.append("Sans tabanlari: her kayit icin AYNI sembol + AYNI hedef, bildirimden >=2 sa uzak <=30 rastgele an (grup ortalamasi). "
               "saat = +-1 saat dilimi; vol = + son 30dk high-low araligi benzer; vol+getiri = + son 30dk getirisi benzer. "
               "Tekrarsiz = ayni sembol 60 dk cooldown alt kumesi. Net proxy: TP / ilk SL / ufuk sonu, maliyet dusulmus.")
    g0: dict = {"0 TUMU": N, "1 TUMU tekrarsiz": [r for r in N if r["dd"]]}
    for w in weeks:
        g0[f"2 hafta {w} ({min(wk_days[w])}..{max(wk_days[w])})"] = [r for r in N if r["week"] == w]
    table(out, "Genel + haftalik", g0, min_n=min_n)
    table(out, "Gun bazinda", group_by(N, lambda r: r["day"]), g="gun", min_n=min_n)

    # özet: genel
    v60 = [r[60] for r in ok]
    hit60 = 100 * _nanmean(x["hit"] for x in v60)
    ch3 = [r["null3"] for r in ok if r["null3"]]
    summary.update(
        n60=len(ok), n_total=len(N),
        hit30=100 * _nanmean(x["hit"] for x in _vals(N, 30)), hit60=hit60,
        hit120=100 * _nanmean(x["hit"] for x in _vals(N, 120)),
        net60=_nanmean(x["net"] for x in v60),
        med_mfe60=float(np.median([x["mfe"] for x in v60])), med_mae60=float(np.median([x["mae"] for x in v60])),
        chance_hit60_null1=100 * _nanmean(r["null"]["hit"] for r in ok if r["null"]),
        chance_hit60_null2=100 * _nanmean(r["null2"]["hit"] for r in ok if r["null2"]),
        chance_hit60=100 * _nanmean(x["hit"] for x in ch3),
        chance_net60=_nanmean(x["net"] for x in ch3),
        chance_cover=len(ch3))
    summary["lift_pp"] = (100 * _nanmean(r[60]["hit"] for r in ok if r["null3"]) - summary["chance_hit60"]) if ch3 else None

    # --- precision@k
    if has_score:
        byday: dict = collections.defaultdict(list)
        for r in ok:
            byday[r["day"]].append(r)
        out.append("\n### Gun-ici precision@k (skora gore; skor 100'e kirpilmis, esitlikte erken olan)")
        out.append("| gun | n | taban hit60% | P@5 | P@10 |")
        out.append("|---|---|---|---|---|")
        pk: dict = {5: [], 10: []}
        tot: dict = {5: [0, 0], 10: [0, 0]}
        bases = []
        for d in sorted(byday):
            v = sorted(byday[d], key=lambda r: (-min(r["score"], 100), r["det"]))
            bases.append(100 * np.mean([r[60]["hit"] for r in v]))
            cells = []
            for kk in (5, 10):
                top = v[:kk]
                p = np.mean([r[60]["hit"] for r in top])
                cells.append(f"{p:.2f}" if len(v) >= kk else f"{p:.2f}*")
                if len(v) >= kk:
                    pk[kk].append(p)
                    tot[kk][0] += sum(r[60]["hit"] for r in top)
                    tot[kk][1] += kk
            out.append(f"| {d} | {len(v)} | {bases[-1]:.1f} | {cells[0]} | {cells[1]} |")
        if pk[5] and pk[10]:
            out.append(f"Gun ort. P@5={np.mean(pk[5]):.3f} ({len(pk[5])} gun), P@10={np.mean(pk[10]):.3f} ({len(pk[10])} gun); "
                       f"havuz P@5={tot[5][0] / tot[5][1]:.3f}, P@10={tot[10][0] / tot[10][1]:.3f}; "
                       f"gun-ort. taban hit60={np.mean(bases):.1f}% (* = o gun < k kayit, ortalamaya girmedi)")
            summary["p_at_5"] = float(np.mean(pk[5]))
            summary["p_at_10"] = float(np.mean(pk[10]))

        sc = np.array([min(r["score"], 100) for r in ok])
        rho, p = spearman(sc, [r[60]["mfe"] for r in ok])
        rho_n, _ = spearman(sc, [r[60]["net"] for r in ok])
        out.append(f"\nSpearman(score, MFE60) n={len(ok)}: rho={rho:.3f} p~{p:.3g}; Spearman(score, net60): rho={rho_n:.3f}")
        okd = [r for r in ok if r["dd"]]
        rd, pd_ = spearman([min(r["score"], 100) for r in okd], [r[60]["mfe"] for r in okd])
        out.append(f"Tekrarsiz n={len(okd)}: rho={rd:.3f} p~{pd_:.3g}")
        summary["spearman_score_mfe60"] = rho

        def sp(sub: list[dict]) -> str:
            if len(sub) < min_n:
                return f"n={len(sub)} (<{min_n})"
            a = spearman([min(r["score"], 100) for r in sub], [r[60]["mfe"] for r in sub])
            s2 = [r for r in sub if r["dd"]]
            b = spearman([min(r["score"], 100) for r in s2], [r[60]["mfe"] for r in s2]) if len(s2) >= min_n else None
            return (f"n={len(sub)} rho={a[0]:.3f} (p~{a[1]:.2g}) | tekrarsiz n={len(s2)} "
                    + (f"rho={b[0]:.3f} (p~{b[1]:.2g})" if b else f"(<{min_n})"))
        out.append("Aile / mode icinde Spearman(score, MFE60) [tum | tekrarsiz]:")
        if has_sources:
            for f in sorted({s for r in ok for s in r["fam"]}):
                out.append(f"- aile {f}: {sp([r for r in ok if f in r['fam']])}")
        for m in sorted({r["mode"] for r in ok}):
            out.append(f"- mode {m}: {sp([r for r in ok if r['mode'] == m])}")

    # --- 2. kırılımlar
    out.append("\n### 2. Kirilimlar (hit60 odakli)")
    mode_name = "mode" if has_score else "strateji"
    by_mode = group_by(N, lambda r: r["mode"])
    table(out, mode_name.capitalize(), by_mode, sort="n", g=mode_name, min_n=min_n)
    summary["by_mode"] = {m: _group_summary(v) for m, v in by_mode.items() if _vals(v, 60)}
    if has_sources:
        by_fam = group_by(N, lambda r: r["fam"], multi=True)
        table(out, "Aile (satir birden fazla ailede sayilir)", by_fam, sort="n", g="aile", min_n=min_n)
        summary["by_family"] = {f: _group_summary(v) for f, v in by_fam.items() if _vals(v, 60)}
        combos = collections.Counter(r["combo"] for r in ok)
        top8 = [c for c, _ in combos.most_common(8)]
        table(out, "Tam kaynak kombinasyonu (ilk 8)", group_by([r for r in N if r["combo"] in top8], lambda r: r["combo"]),
              sort="n", g="kombinasyon", min_n=min_n)
        table(out, f"{mode_name.capitalize()} x kaynak kombinasyonu (n>={min_n})",
              group_by(N, lambda r: f"{r['mode']} | {r['combo']}"), sort="n", minn=min_n, g=f"{mode_name} | kombinasyon", min_n=min_n)
    if has_score:
        by_sb = group_by(N, lambda r: score_bucket(r["score"]))
        table(out, "Skor kovasi", by_sb, g="skor", min_n=min_n)
        summary["by_score_bucket"] = {b: _group_summary(v) for b, v in by_sb.items() if _vals(v, 60)}
        table(out, "horizon_minutes (bildirimin kendi ufku)", group_by(N, lambda r: str(r["hz"])), g="horizon", min_n=min_n)
        table(out, "llm_verdict", group_by(N, lambda r: r["lv"] or "(yok)"), sort="n", g="llm", min_n=min_n)
        table(out, "macd_mtf_verdict", group_by(N, lambda r: r["mv"] or "(yok)"), sort="n", g="macd_mtf", min_n=min_n)
        table(out, "Mode x skor>=95", group_by(N, lambda r: f"{r['mode']} / {'95+' if r['score'] >= 95 else '<95'}"), g="mode/skor", min_n=min_n)
        for m in sorted({r["mode"] for r in N}):
            sub = [r for r in N if r["mode"] == m]
            if len(_vals(sub, 60)) >= 2 * min_n:
                table(out, f"{m} x skor kovasi", group_by(sub, lambda r: score_bucket(r["score"])), g=f"{m} / skor", min_n=min_n)
    table(out, "Saat (Istanbul, 3 saatlik dilim)", group_by(N, lambda r: hour_bin(r["hour"])), g="saat", min_n=min_n)
    table(out, "Tekrarsiz mode/strateji", group_by([r for r in N if r["dd"]], lambda r: r["mode"]), sort="n",
          g=f"{mode_name} (tekrarsiz)", min_n=min_n)

    # --- haftalık pivot
    def pivot(title: str, keyf: Callable, multi: bool = False) -> None:
        out.append(f"\n### {title} - haftalik hit60% (n)")
        out.append("| grup | " + " | ".join(weeks) + " |")
        out.append("|---|" + "---|" * len(weeks))
        g = group_by(N, keyf, multi=multi)
        for k in sorted(g, key=lambda k: -len(_vals(g[k], 60))):
            if len(_vals(g[k], 60)) < min_n:
                continue
            cells = []
            for w in weeks:
                v = _vals([r for r in g[k] if r["week"] == w], 60)
                cells.append(f"{100 * np.mean([x['hit'] for x in v]):.0f} ({len(v)})" if v else "-")
            out.append(f"| {k} | " + " | ".join(cells) + " |")
    pivot(mode_name.capitalize(), lambda r: r["mode"])
    if has_sources:
        pivot("Aile", lambda r: r["fam"], True)

    # --- 3. karşı-olgusal
    scen = build_scenarios(modes_disabled, unified_min_score, has_score)
    out.append("\n### 3. Karsi-olgusal kapi senaryolari (ayni kayitlar uzerinde geriye donuk filtre)")
    if has_sources:
        out.append(f"short_squeeze/snapback-yalniz satir: {sum(1 for r in N if r['src'] and set(r['src']) <= SQUEEZE)}; "
                   f"tum kaynak adlari: {dict(collections.Counter(s for r in N for s in r['src']))}.")
    n_orig = len(ok)
    out.append("\n| senaryo | n kalan | orijinalin % | hit60% [Wilson95] | net60% ±95%CI | sans hit60% (vol+getiri) | sans net60 | tekrarsiz n / hit60 / net | "
               + " | ".join(f"{w} hit60 (n)" for w in weeks) + " | haftada orijinalden iyi |")
    out.append("|---|---|---|---|---|---|---|---|" + "---|" * len(weeks) + "---|")
    SC: dict = {}
    summary["scenarios"] = {}
    for name, f in scen:
        kept = [r for r in ok if f(r)]
        SC[name] = kept
        if not kept:
            out.append(f"| {name} | 0 | 0% | - | - | - | - | - | " + " | ".join("-" for _ in weeks) + " | - |")
            summary["scenarios"][name] = {"n": 0}
            continue
        v = [r[60] for r in kept]
        k = sum(x["hit"] for x in v)
        lo, hi = wilson(k, len(v))
        net = np.array([x["net"] for x in v])
        se = net.std(ddof=1) / math.sqrt(len(net)) if len(net) > 1 else float("nan")
        k3 = [r for r in kept if r["null3"]]
        nl = 100 * _nanmean(r["null3"]["hit"] for r in k3)
        nln = _nanmean(r["null3"]["net"] for r in k3)
        lift = 100 * _nanmean(r[60]["hit"] for r in k3) - nl if k3 else float("nan")
        ddv = [r[60] for r in dedup(kept)]
        cells, better, comp = [], 0, 0
        for w in weeks:
            kw = [r[60]["hit"] for r in kept if r["week"] == w]
            ow = [r[60]["hit"] for r in ok if r["week"] == w]
            if kw:
                cells.append(f"{100 * np.mean(kw):.0f} ({len(kw)})")
                if len(kw) >= 15 and len(ow) >= 15:
                    comp += 1
                    better += int(np.mean(kw) > np.mean(ow))
            else:
                cells.append("-")
        out.append(f"| {name} | {len(kept)} | {100 * len(kept) / n_orig:.0f}% | {100 * k / len(v):.1f} [{lo:.0f},{hi:.0f}] | "
                   f"{net.mean():+.2f}±{1.96 * se:.2f} | {nl:.1f} (fark {lift:+.1f}) | {nln:+.2f} | "
                   f"{len(ddv)} / {100 * np.mean([x['hit'] for x in ddv]):.1f} / {np.mean([x['net'] for x in ddv]):+.2f} | "
                   + " | ".join(cells) + f" | {better}/{comp} (n>=15) |")
        summary["scenarios"][name] = dict(n=len(kept), hit60=100 * k / len(v), net60=float(net.mean()),
                                          chance_hit60=nl, lift_pp=lift, chance_net60=nln)
    out.append(f"Orijinal hit60={hit60:.1f}%. 'Haftada orijinalden iyi': kalan kumenin haftalik hit60'i o haftanin orijinalinden yuksek mi "
               "(her ikisinde n>=15 olan haftalar).")
    out.append("\nKalan vs elenen (Fisher exact, hit60):")
    out.append("| senaryo | kalan n / hit60 | elenen n / hit60 | elenen net60 | kalan net60 | Fisher p (iki yonlu) |")
    out.append("|---|---|---|---|---|---|")
    for name, f in scen[1:]:
        kept = SC[name]
        kid = {r["id"] for r in kept}
        drop = [r for r in ok if r["id"] not in kid]
        if not drop or not kept:
            out.append(f"| {name} | {len(kept)} | {len(drop)} | - | - | - |")
            continue
        k1, n1 = sum(r[60]["hit"] for r in kept), len(kept)
        k2, n2 = sum(r[60]["hit"] for r in drop), len(drop)
        pf = fisher_exact(k1, n1 - k1, k2, n2 - k2)
        out.append(f"| {name} | {n1} / {100 * k1 / n1:.1f} | {n2} / {100 * k2 / n2:.1f} | "
                   f"{np.mean([r[60]['net'] for r in drop]):+.2f} | {np.mean([r[60]['net'] for r in kept]):+.2f} | {pf:.3g} |")
    out.append("\nSenaryo hit30/hit60/hit120:")
    out.append("| senaryo | n | hit30 | hit60 | hit120 | med MFE60 | med MAE60 |")
    out.append("|---|---|---|---|---|---|---|")
    for name, _ in scen:
        kept = SC[name]
        if not kept:
            continue

        def hh(H: int, kept=kept) -> str:
            v = _vals(kept, H)
            return f"{100 * np.mean([x['hit'] for x in v]):.1f}" if v else "-"
        out.append(f"| {name} | {len(kept)} | {hh(30)} | {hh(60)} | {hh(120)} | "
                   f"{np.median([r[60]['mfe'] for r in kept]):.2f} | {np.median([r[60]['mae'] for r in kept]):.2f} |")
    ndays = len({r["day"] for r in ok})
    out.append(f"\nGunluk hacim (olculen, {ndays} gun): " + "; ".join(
        f"{name.split(' ')[0]}: {len(SC[name]) / ndays:.1f}/gun" for name, _ in scen))

    # --- 4. uygulama etiketi çapraz kontrolü
    if has_labels:
        lab = [r for r in N if r["ost"]]
        out.append("\n### 4. Capraz kontrol: uygulama etiketi (outcome_status) vs mum-bazli hit")
        if not lab:
            out.append("Etiketli satir yok.")
        else:
            out.append(f"Etiketli satir n={len(lab)}: " + ", ".join(f"{k}={v}" for k, v in collections.Counter(r['ost'] for r in lab).items()))
            for H in HORIZ:
                sub = [r for r in lab if r[H]]
                if not sub:
                    continue
                out.append(f"\nHit{H} (n={len(sub)}): satir=uygulama etiketi, sutun=mum-bazli hit")
                out.append("| etiket | mum hit | mum hit degil | hit % |")
                out.append("|---|---|---|---|")
                for o in ("HEDEFE_ULTI", "STOP", "SURE_DOLDU"):
                    s = [r for r in sub if r["ost"] == o]
                    h = sum(r[H]["hit"] for r in s)
                    out.append(f"| {o} | {h} | {len(s) - h} | {100 * h / max(1, len(s)):.1f} |")
                agree = sum(1 for r in sub if (r["ost"] == "HEDEFE_ULTI") == r[H]["hit"])
                out.append(f"Uyum (HEDEFE_ULTI == mum hit): {100 * agree / len(sub):.1f}% ({agree}/{len(sub)})")
            sub = [r for r in lab if r[60] and r["smfe"] is not None]
            if len(sub) >= 3:
                rho, _ = spearman([r["smfe"] for r in sub], [r[60]["mfe"] for r in sub])
                out.append(f"\nSpearman(uygulama kayitli MFE, mum MFE60) n={len(sub)}: rho={rho:.3f}; "
                           f"medyan kayitli MFE={np.median([r['smfe'] for r in sub]):.2f} vs mum MFE60={np.median([r[60]['mfe'] for r in sub]):.2f}")
    return out, summary


def _group_summary(recs: list[dict]) -> dict:
    v = _vals(recs, 60)
    k3 = [r for r in recs if r.get(60) and r.get("null3")]
    ch = 100 * _nanmean(r["null3"]["hit"] for r in k3) if k3 else None
    real_matched = 100 * _nanmean(r[60]["hit"] for r in k3) if k3 else None
    return dict(n=len(v), hit60=100 * _nanmean(x["hit"] for x in v), net60=_nanmean(x["net"] for x in v),
                chance_hit60=ch, lift_pp=(real_matched - ch) if ch is not None else None)


# ------------------------------------------------------------------ G/Ç (I/O)
_NOTIF_SQL = ("SELECT id, symbol, score, target_pct, price, horizon_minutes, mode, detected_at, sources, candidate_id, "
              "outcome_status, mfe_pct, mae_pct, macd_mtf_verdict, llm_verdict FROM monitoring_notifications "
              "WHERE detected_at >= %s ORDER BY detected_at")
_SIGNAL_SQL = ("SELECT id, timestamp, symbol, action, price, strategy FROM signals "
               "WHERE action = ANY(%s) AND timestamp >= %s AND price > 0 ORDER BY timestamp")
_CANDLE_SQL = ("SELECT symbol, open_time, high::float8, low::float8, close::float8 FROM historical_candles "
               "WHERE timeframe = '5m' AND open_time >= %s ORDER BY symbol, open_time")


_CANDLE_SQL_OPEN = ("SELECT symbol, open_time, high::float8, low::float8, close::float8, open::float8 "
                    "FROM historical_candles WHERE timeframe = '5m' AND open_time >= %s ORDER BY symbol, open_time")


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url


def load_rows(conn, source: str, since_ts: float, signal_actions: list[str]) -> list[dict]:
    if source == "signals":
        return [normalize_signal_row(r) for r in conn.execute(_SIGNAL_SQL, (signal_actions, since_ts)).fetchall()]
    return [normalize_notification_row(r) for r in conn.execute(_NOTIF_SQL, (since_ts,)).fetchall()]


def load_candles(conn, since_ts: float, with_open: bool = False) -> CandleStore:
    """Pencereden 6 sa önceki mumlardan itibaren (iz için) tüm 5m mumları yükler."""
    sql = _CANDLE_SQL_OPEN if with_open else _CANDLE_SQL
    rows = conn.execute(sql, (int((since_ts - 6 * 3600) * 1000),)).fetchall()
    return CandleStore.from_rows(rows)


def generate_report(rows: list[dict], store: CandleStore, *, source: str, since_ts: float,
                    modes_disabled: Iterable[str] = DEFAULT_MODES_DISABLED, unified_min_score: float = 95.0,
                    min_n: int = 30, sl: float = SL, cost: float = COST, seed: int = 7) -> tuple[str, dict]:
    """Saf: (satırlar, mum deposu) -> (markdown, özet sözlük). DB'ye dokunmaz."""
    md: list[str] = []
    summary: dict = {"source": source, "since": datetime.fromtimestamp(since_ts, TZ).strftime("%Y-%m-%d %H:%M"),
                     "sl": sl, "cost": cost, "min_n": min_n}
    last = max((r["detected_at"] for r in rows), default=since_ts)
    md.append(f"# Bildirim/sinyal sonuc kalitesi - kaynak: {source} "
              f"({datetime.fromtimestamp(since_ts, TZ):%Y-%m-%d} .. {datetime.fromtimestamp(last, TZ):%Y-%m-%d %H:%M} Istanbul)")
    if store.d:
        md.append(f"Mum: historical_candles 5m, {len(store.d)} sembol, {datetime.fromtimestamp(store.tmin, TZ):%m-%d %H:%M} .. "
                  f"{datetime.fromtimestamp(store.tmax, TZ):%m-%d %H:%M}. Hit = ufuk icinde MFE >= hedef; yalniz detected_at SONRASI acilan mumlar. "
                  f"Net proxy: TP / ilk SL -{sl:g}% (ayni mumda SL once) / ufuk sonu kapanis, -{cost:g}% maliyet. "
                  f"Wilson95 hit60 icin; n<{min_n} satirlar sonuc cikarmaya uygun degil.")
    md.append(f"Kapali modlar (karsi-olgusal): {', '.join(modes_disabled) or '-'}; unified asgari skor: {unified_min_score:g}.")
    if not rows:
        md.append("\nPencerede kayit yok.")
        summary["empty"] = True
        return "\n".join(md) + "\n", summary

    if source == "signals":
        md.append("\n**Strateji kirilimi ve tarih araligi (kaldirilmis stratejiler eski donemlere aittir; guncel sonuclarla karistirmayin):**")
        md.append("| strateji | ilk | son | kayit |")
        md.append("|---|---|---|---|")
        st: dict = collections.defaultdict(list)
        for r in rows:
            st[r["mode"]].append(r["detected_at"])
        for s, ts in sorted(st.items(), key=lambda x: -len(x[1])):
            md.append(f"| {s} | {datetime.fromtimestamp(min(ts), TZ):%Y-%m-%d} | {datetime.fromtimestamp(max(ts), TZ):%Y-%m-%d} | {len(ts)} |")
        summary["strategies"] = {s: dict(first=datetime.fromtimestamp(min(t), TZ).strftime("%Y-%m-%d"),
                                         last=datetime.fromtimestamp(max(t), TZ).strftime("%Y-%m-%d"), n=len(t))
                                 for s, t in st.items()}
        summary["targets"] = {}
        for tp in SIGNAL_TARGETS:
            N, skips = build_records(rows, store, tp_override=tp, sl=sl, cost=cost)
            mark_dedup(N)
            compute_chance(N, store, np.random.default_rng(seed), sl=sl, cost=cost)
            lines, sm = analyze(N, label=f"Sabit hedef %{tp:g}", has_score=False, has_sources=False, has_labels=False,
                                modes_disabled=modes_disabled, unified_min_score=unified_min_score, min_n=min_n, skips=skips)
            md.extend(lines)
            summary["targets"][f"{tp:g}"] = sm
    else:
        N, skips = build_records(rows, store, sl=sl, cost=cost)
        mark_dedup(N)
        compute_chance(N, store, np.random.default_rng(seed), sl=sl, cost=cost)
        mx = max((r["score"] for r in N), default=0)
        md.append(f"Skor>100 satirlar: {sum(1 for r in N if r['score'] > 100)} (max {mx:.0f}; '100+' kovasinda; P@k/Spearman'da 100'e kirpildi).")
        lines, sm = analyze(N, label="Bildirimler (kendi target_pct'i; bos ise 2.0)", has_score=True, has_sources=True,
                            has_labels=True, modes_disabled=modes_disabled, unified_min_score=unified_min_score,
                            min_n=min_n, skips=skips)
        md.extend(lines)
        summary.update(sm)
    return "\n".join(md) + "\n", summary


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    return o


def run_report(db_url: str, *, source: str = "notifications", days: float = 30.0, since: str | None = None,
               signal_actions: Iterable[str] = ("BUY_SIGNAL",), **kw: Any) -> tuple[str, dict]:
    """DB'den okuyup rapor üretir (radar_periodic_review da bunu çağırır)."""
    import psycopg
    since_ts = (datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=TZ).timestamp()
                if since else time.time() - days * 86400.0)
    with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
        rows = load_rows(conn, source, since_ts, list(signal_actions))
        store = load_candles(conn, since_ts) if rows else CandleStore({})
    return generate_report(rows, store, source=source, since_ts=since_ts, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bildirim/sinyal sonuc kalitesi (mum bazli hit, sans tabani, karsi-olgusal).")
    ap.add_argument("--days", type=float, default=30.0, help="Geriye donuk gun (varsayilan 30)")
    ap.add_argument("--since", default=None, help="Baslangic YYYY-MM-DD (Istanbul); verilirse --days yok sayilir")
    ap.add_argument("--out", default=None, help="Markdown rapor dosyasi")
    ap.add_argument("--json", action="store_true", help="Ozet JSON: --out varsa <out>.json'a, yoksa stdout'a")
    ap.add_argument("--source", choices=("notifications", "signals"), default="notifications")
    ap.add_argument("--signals-actions", default="BUY_SIGNAL",
                    help="signals.action degerleri, virgullu (varsayilan BUY_SIGNAL; or. BUY_SIGNAL,PUMP_CANDIDATE)")
    ap.add_argument("--modes-disabled", default=",".join(DEFAULT_MODES_DISABLED),
                    help="Karsi-olgusalda kapali sayilan modlar (virgullu)")
    ap.add_argument("--unified-min-score", type=float, default=95.0, help="Guncel politika: unified asgari skor")
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--sl", type=float, default=SL)
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if args.days <= 0 or args.min_n < 1:
        print("HATA: --days pozitif, --min-n >= 1 olmali.", file=sys.stderr)
        return 2
    dis = [m.strip() for m in args.modes_disabled.split(",") if m.strip()]
    actions = [a.strip() for a in args.signals_actions.split(",") if a.strip()]
    try:
        md, summary = run_report(_db_url(), source=args.source, days=args.days, since=args.since, signal_actions=actions,
                                 modes_disabled=dis, unified_min_score=args.unified_min_score, min_n=args.min_n,
                                 sl=args.sl, cost=args.cost, seed=args.seed)
    except Exception as exc:  # noqa: BLE001 - CLI sınırı
        print(f"HATA: rapor uretilemedi ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    js = json.dumps(_clean(summary), ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        if args.json:
            with open(args.out + ".json", "w", encoding="utf-8") as f:
                f.write(js)
    if args.json and not args.out:
        print(js)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
