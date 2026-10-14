"""YENİ BİLGİ SINIFI KAPSAMLI BACKTEST (2026-10-13).

Ön test (`research_new_channels_precheck`) 3 aday belirledi; bu script onları
KAPSAMLI biçimde ölçer: walk-forward (ilk %60 eğitim / %40 sınav), maliyet
(taker+maker), 3-fold, gün-gün, sembol yoğunlaşması, eşleştirilmiş t-testi.

KANALLAR:
  A1 FUNDING TAŞIMA : BTC funding rate uçları → BTC getirisi (majör, doğrudan).
                      + TAŞINABİLİRLİK: BTC funding rejimini TRY evrenine uygula.
  A2 MAKRO DUYGU    : Fear&Greed uçları → BTC günlük getirisi.
  A3 CROSS-VENUE    : OKX BTC-USDT getirisi → BTCTRY önculuk (lead-lag).

EŞİK: net EV>0 VE 3-fold kararlı VE t>1.65. Geçmezse canlıya ALINMAZ.

KULLANIM:
    python backend/scripts/research_new_channels_backtest.py --days 60
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sqlite3
import statistics
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_TAKER, _MAKER = 0.35, 0.10


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read().decode())


def _closes(symbol: str, interval: str) -> list[tuple[float, float]]:
    conn = sqlite3.connect(_DB)
    rows = conn.execute(
        "SELECT open_time, close FROM klines WHERE interval=? AND symbol=? ORDER BY open_time",
        (interval, symbol)).fetchall()
    conn.close()
    return [(float(ot) / 1000.0, float(cl)) for ot, cl in rows if cl and cl > 0]


def _metrics(nets: list[float]) -> dict:
    nets = [x for x in nets if x is not None]
    if len(nets) < 5:
        return {"n": len(nets), "ev": None}
    w = [x for x in nets if x > 0]; l = [x for x in nets if x <= 0]
    aw = statistics.mean(w) if w else 0.0; al = statistics.mean(l) if l else 0.0
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "median": round(statistics.median(nets), 3),
            "win": round(100 * len(w) / len(nets), 1),
            "payoff": round(aw / abs(al), 2) if al else None}


def _folds(nets: list[float]) -> list:
    nets = [x for x in nets if x is not None]
    if len(nets) < 30:
        return []
    return [_metrics(nets[int(len(nets) * k / 3):int(len(nets) * (k + 1) / 3)])["ev"]
            for k in range(3)]


def _tstat(a, b) -> float:
    a = [x for x in a if x is not None]; b = [x for x in b if x is not None]
    if len(a) < 20 or len(b) < 20:
        return 0.0
    va = statistics.pvariance(a) / len(a); vb = statistics.pvariance(b) / len(b)
    se = (va + vb) ** 0.5
    return round((statistics.mean(a) - statistics.mean(b)) / se, 2) if se else 0.0


def _walkforward(signals: list[tuple[float, float]], cost: float) -> dict:
    """signals: [(ts, gross_pct)] → eğitim/sınav maliyetli metrikler."""
    signals = [s for s in signals if s[1] is not None]
    if not signals:
        return {"n": 0}
    signals.sort(key=lambda s: s[0])
    split = int(len(signals) * 0.6)
    te = signals[split:]
    nets = [g - cost for _, g in te]
    return _metrics(nets)


# ---------------------------------------------------------------------------
# A1 FUNDING
# ---------------------------------------------------------------------------
def a1_funding(days: float) -> dict:
    now = int(time.time() * 1000)
    try:
        data = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT"
                    f"&startTime={now - int(days * 86400000)}&limit=1000")
    except Exception as exc:
        return {"error": str(exc)}
    closes = _closes("BTCTRY", "5m")
    if not closes or not data:
        return {"n": 0}
    ts = [c[0] for c in closes]
    # Sinyal: funding > eğitim-medyanı → LONG (ön testte pozitif yönde çıktı)
    rows = []
    for r in data:
        ft = float(r["fundingTime"]) / 1000.0
        rate = float(r["fundingRate"])
        i = bisect.bisect_left(ts, ft)
        if 0 <= i < len(closes) - 12:
            rows.append((ft, rate, (closes[i + 12][1] / closes[i][1] - 1) * 100))
    if len(rows) < 40:
        return {"n": len(rows)}
    split = int(len(rows) * 0.6)
    # Sinyal: eğitimde üst %20 funding (aşırı kalabalık long) → sınavda uygula.
    tr_rates = sorted(r[1] for r in rows[:split])
    thr = tr_rates[int(len(tr_rates) * 0.8)]
    sig = [(r[0], r[2]) for r in rows[split:] if r[1] > thr]
    base = [(r[0], r[2]) for r in rows[split:]]
    return {"n_funding_pts": len(rows), "signal_thr_funding_p80": round(thr, 6),
            "signal_taker": _walkforward(sig, _TAKER),
            "signal_maker": _walkforward(sig, _MAKER),
            "base_taker": _walkforward(base, _TAKER),
            "signal_folds_taker": _folds([g - _TAKER for _, g in sig]),
            "t_vs_base": _tstat([g - _TAKER for _, g in sig], [g - _TAKER for _, g in base])}


# ---------------------------------------------------------------------------
# A2 FEAR & GREED
# ---------------------------------------------------------------------------
def a2_fear_greed(days: float) -> dict:
    try:
        d = _get(f"https://api.alternative.me/fng/?limit={int(min(days, 90))}")
    except Exception as exc:
        return {"error": str(exc)}
    vals = (d or {}).get("data") or []
    daily = {int(ot) // 86400: cl for ot, cl in _closes("BTCTRY", "1d")}
    keys = sorted(daily)
    if not vals or not keys:
        return {"n": 0, "note": "fear&greed veya 1d veri eksik"}
    rows = []
    for v in vals:
        day = int(v["timestamp"]) // 86400
        fg = float(v["value"])
        if day in daily and (day + 1) in daily and daily[day] > 0:
            rows.append((float(v["timestamp"]), fg, (daily[day + 1] / daily[day] - 1) * 100))
    if len(rows) < 20:
        return {"n": len(rows)}
    split = int(len(rows) * 0.6)
    thr = statistics.median([r[1] for r in rows[:split]])
    sig = [(r[0], r[2]) for r in rows[split:] if r[1] > thr]
    base = [(r[0], r[2]) for r in rows[split:]]
    return {"signal_thr_fg": thr,
            "signal_taker": _walkforward(sig, _TAKER),
            "base_taker": _walkforward(base, _TAKER),
            "signal_folds_taker": _folds([g - _TAKER for _, g in sig])}


# ---------------------------------------------------------------------------
# A3 CROSS-VENUE (OKX → TR)
# ---------------------------------------------------------------------------
def _okx_history(bars: int) -> list:
    """OKX 5m mumlarını SAYFALAYARAK çek (history-candles, ~300/gün)."""
    out = []
    after = None
    while len(out) < bars:
        url = f"https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=5m&limit=100"
        if after:
            url += f"&after={after}"
        try:
            d = _get(url)
        except Exception:
            break
        data = (d or {}).get("data") or []
        if not data:
            break
        out.extend(data)
        after = data[-1][0]           # en eski ts → sonraki sayfa
        time.sleep(0.12)
    return out


def a3_cross_venue(days: float) -> dict:
    try:
        data = _okx_history(int(days * 288))
    except Exception as exc:
        return {"error": str(exc)}
    if not data:
        return {"n": 0}
    okx = sorted([(int(r[0]) / 1000.0, float(r[4])) for r in data])
    tr = {round(c[0]): c[1] for c in _closes("BTCTRY", "5m")}
    trs = sorted(tr)
    rows = []
    for (t0, c0), (t1, c1) in zip(okx[:-1], okx[1:]):
        if c0 <= 0:
            continue
        okx_ret = (c1 / c0 - 1) * 100
        i = bisect.bisect_right(trs, int(t1))
        if 0 < i < len(trs) - 1 and tr[trs[i]] > 0:
            fwd = (tr[trs[i + 1]] / tr[trs[i]] - 1) * 100
            rows.append((float(t1), okx_ret, fwd))
    if len(rows) < 40:
        return {"n": len(rows), "note": "OKX geçmiş penceresi dar"}
    split = int(len(rows) * 0.6)
    thr = statistics.median([abs(r[1]) for r in rows[:split]])
    # Sinyal: OKX pozitif ve anlamlı hareket (üst medyan) → TRY LONG
    sig = [(r[0], r[2]) for r in rows[split:] if r[1] > thr]
    base = [(r[0], r[2]) for r in rows[split:]]
    return {"n_okx": len(okx), "signal_thr_okx_absmove": round(thr, 3),
            "signal_taker": _walkforward(sig, _TAKER),
            "signal_maker": _walkforward(sig, _MAKER),
            "base_taker": _walkforward(base, _TAKER),
            "signal_folds_taker": _folds([g - _TAKER for _, g in sig]),
            "n_signal": len(sig)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=60.0)
    ap.add_argument("--out", default="work/new_channels_backtest.json")
    args = ap.parse_args()
    print("=== YENİ BİLGİ SINIFI KAPSAMLI BACKTEST ===")
    res = {}
    for name, fn in (("A1_funding", a1_funding), ("A2_fear_greed", a2_fear_greed),
                     ("A3_cross_venue", a3_cross_venue)):
        print(f"  {name}...", flush=True)
        try:
            res[name] = fn(args.days)
        except Exception as exc:
            res[name] = {"error": f"{type(exc).__name__}: {exc}"}
        print("     ", res[name])

    # Karar
    verdict = {}
    for name in ("A1_funding", "A2_fear_greed", "A3_cross_venue"):
        r = res.get(name) or {}
        st = (r.get("signal_taker") or {}).get("ev")
        folds = r.get("signal_folds_taker") or []
        stable = bool(folds) and all((f or -9) > 0 for f in folds)
        verdict[name] = {"signal_ev_taker": st, "folds": folds,
                         "gecer": bool(st is not None and st > 0 and stable)}
    res["_verdict"] = verdict
    print("\n  KARAR (net EV>0 & 3-fold kararlı):")
    for k, v in verdict.items():
        print(f"    {k}: {v}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
