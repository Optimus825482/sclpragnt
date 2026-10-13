"""YENİ BİLGİ SINIFI ARAŞTIRMASI — ÖN TEST (2026-10-13).

Kullanıcı: "order-flow derinliği, haber/duygu, cross-venue) ya da farklı venue/varlık
sınıfını ARAŞTIR; ilk 3 adayı kısa vadeli ön teste tabi tut; geceleri kapsamlı
backtest/replay yap."

ERİŞİLEBİLİRLİK + TARİHSELLİK TARAMASI (doğrulandı):
  * funding rate (fapi)          : 120+ gün geriye ✅ → TEST EDİLEBİLİR
  * fear&greed (alternative.me)  : 90 gün günlük ✅   → TEST EDİLEBİLİR
  * OKX/Coinbase klines          : canlı ✅ (geçmiş sınırlı ama kesişim var)
  * OI/long-short (futures/data) : HTTPError / kısa pencere ❌
  * CryptoPanic haber            : 403 (token gerekli) ❌

İLK 3 ADAY (erişilebilir + geriye dönük test edilebilir):
  A1 FUNDING TAŞIMA: aşırı pozitif funding (kalabalık long) → ters dönüş beklentisi.
  A2 MAKRO DUYGU   : Fear&Greed aşırı uçları → risk iştahı yönü.
  A3 CROSS-VENUE   : BTC OKX (USDT) → BTC TRY (onsuz lead-lag var mı).

ÖN TEST: her adayın, mevcut TRY fiyat serilerinin İLERİ getirisiyle ilişkisi
(korelasyon + uç-kuvruk farkı). Amaç: "devam etmeye değer mi" sinyali. Kapsamlı
walk-forward/replay GECE (off-peak) koşusuna bırakılır.

KULLANIM:
    python backend/scripts/research_new_channels_precheck.py --days 60
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.request
import ssl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE


def _get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read().decode())


def _corr(a, b) -> float:
    n = min(len(a), len(b))
    if n < 20:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / n
    sd = statistics.pstdev(a) * statistics.pstdev(b)
    return round(cov / sd, 3) if sd else 0.0


def _btc_5m_closes(days: float) -> list[tuple[float, float]]:
    """BTCTRY 5m kapanışları (ts, close), sqlite'tan."""
    conn = sqlite3.connect(_DB)
    rows = conn.execute(
        "SELECT open_time, close FROM klines WHERE interval='5m' AND symbol='BTCTRY' "
        "ORDER BY open_time").fetchall()
    conn.close()
    out = [(float(ot) / 1000.0, float(cl)) for ot, cl in rows if cl and cl > 0]
    if out:
        cut = out[-1][0] - days * 86400
        out = [r for r in out if r[0] >= cut]
    return out


def test_funding(days: float) -> dict:
    """A1: funding aşırı pozitif/negatif → sonraki BTC getirisi."""
    now = int(time.time() * 1000)
    try:
        data = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT"
                    f"&startTime={now - int(days * 86400000)}&limit=1000")
    except Exception as exc:
        return {"error": str(exc)}
    if not data:
        return {"n": 0}
    # funding (8 saatlik) → zaman; BTC 5m kapanışlarına eşle
    closes = _btc_5m_closes(days)
    if not closes:
        return {"error": "no_btc"}
    ts = [c[0] for c in closes]
    import bisect
    pairs = []
    for row in data:
        ft = float(row["fundingTime"]) / 1000.0
        rate = float(row["fundingRate"])
        i = bisect.bisect_left(ts, ft)
        # funding anından sonraki 1 saat (12 bar) getirisi
        if 0 <= i < len(closes) - 12:
            fwd = (closes[i + 12][1] / closes[i][1] - 1) * 100
            pairs.append((rate, fwd))
    if len(pairs) < 20:
        return {"n": len(pairs)}
    rates = [p[0] for p in pairs]; fwds = [p[1] for p in pairs]
    srt = sorted(pairs)
    k = max(1, len(srt) // 5)
    return {"n": len(pairs), "corr": _corr(rates, fwds),
            "funding_positive_ev": round(statistics.mean([x[1] for x in srt[-k:]]), 3),
            "funding_negative_ev": round(statistics.mean([x[1] for x in srt[:k]]), 3),
            "mean_fwd": round(statistics.mean(fwds), 3)}


def test_fear_greed(days: float) -> dict:
    """A2: Fear&Greed uçları → o gün BTC 1g getirisi (günlük)."""
    try:
        d = _get(f"https://api.alternative.me/fng/?limit={int(min(days, 90))}")
    except Exception as exc:
        return {"error": str(exc)}
    vals = (d or {}).get("data") or []
    if not vals:
        return {"n": 0}
    # günlük BTC kapanışları sqlite'tan
    conn = sqlite3.connect(_DB)
    rows = conn.execute(
        "SELECT open_time, close FROM klines WHERE interval='1d' AND symbol='BTCTRY' ORDER BY open_time").fetchall()
    conn.close()
    daily = {int(ot) // 86400000: float(cl) for ot, cl in rows if cl and cl > 0}
    keys = sorted(daily)
    pairs = []
    for v in vals:
        day = int(v["timestamp"]) // 86400000
        fg = float(v["value"])
        if day in daily and (day + 1) in daily and daily[day] > 0:
            fwd = (daily[day + 1] / daily[day] - 1) * 100
            pairs.append((fg, fwd))
    if len(pairs) < 10:
        return {"n": len(pairs), "note": "1d BTC verisi eksik olabilir"}
    fgs = [p[0] for p in pairs]; fw = [p[1] for p in pairs]
    srt = sorted(pairs); k = max(1, len(srt) // 4)
    return {"n": len(pairs), "corr": _corr(fgs, fw),
            "greed_ev": round(statistics.mean([x[1] for x in srt[-k:]]), 3),
            "fear_ev": round(statistics.mean([x[1] for x in srt[:k]]), 3)}


def test_cross_venue(days: float) -> dict:
    """A3: OKX BTC-USDT 5m getirisi → BTCTRY 5m getirisi (lead-lag var mı)."""
    try:
        d = _get("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=300")
    except Exception as exc:
        return {"error": str(exc)}
    data = (d or {}).get("data") or []
    if not data:
        return {"n": 0}
    # OKX: [ts, o, h, l, c, ...] (en yeni ilk) → tersine çevir
    okx = sorted([(int(r[0]) / 1000.0, float(r[4])) for r in data])
    okx_ret = {round(t): (c / p - 1) * 100 for (t, c), (tp, p) in
               zip(okx[1:], okx[:-1]) if p > 0}
    closes = _btc_5m_closes(days)
    tr = {round(c[0]): c[1] for c in closes}
    trs = sorted(tr)
    # OKX getirisi → BTCTRY SONRAKI bar getirisi (lead testi)
    pairs = []
    for t, r in okx_ret.items():
        # t'den sonra gelen TRY barları
        import bisect
        i = bisect.bisect_right(trs, t)
        if 0 < i < len(trs) - 1 and tr[trs[i]] > 0:
            fwd = (tr[trs[i + 1]] / tr[trs[i]] - 1) * 100 if i + 1 < len(trs) else None
            same = (tr[trs[i]] / tr[trs[i - 1]] - 1) * 100 if tr[trs[i - 1]] > 0 else 0
            if fwd is not None:
                pairs.append((r, fwd, same))
    if len(pairs) < 20:
        return {"n": len(pairs)}
    okxr = [p[0] for p in pairs]; fwd = [p[1] for p in pairs]; same = [p[2] for p in pairs]
    return {"n": len(pairs), "corr_okx_fwd": _corr(okxr, fwd),
            "corr_okx_same": _corr(okxr, same),
            "note": "same=yüksek ise eşzamanlı; fwd=same'den büyükse öncülük var"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=60.0)
    ap.add_argument("--out", default="work/new_channels_precheck.json")
    args = ap.parse_args()
    print("=== YENİ BİLGİ SINIFI ÖN TESTİ (ilk 3 aday) ===")
    res = {}
    print("  A1 FUNDING...", flush=True)
    res["A1_funding_carry"] = test_funding(args.days)
    print("     ", res["A1_funding_carry"])
    print("  A2 FEAR&GREED...", flush=True)
    res["A2_fear_greed"] = test_fear_greed(args.days)
    print("     ", res["A2_fear_greed"])
    print("  A3 CROSS-VENUE (OKX→TR)...", flush=True)
    res["A3_cross_venue"] = test_cross_venue(args.days)
    print("     ", res["A3_cross_venue"])

    # Ön karar: hangisi devam etmeye değer (|corr|>=0.05 veya uç-kuvruk farkı>=0.3)
    verdict = {}
    f = res["A1_funding_carry"]
    verdict["A1"] = "DEVAM" if abs(f.get("corr", 0)) >= 0.05 else "zayıf"
    fg = res["A2_fear_greed"]
    verdict["A2"] = "DEVAM" if abs(fg.get("corr", 0)) >= 0.05 else "zayıf"
    cv = res["A3_cross_venue"]
    cov = cv.get("corr_okx_fwd", 0)
    verdict["A3"] = "DEVAM" if abs(cov) >= 0.05 else "zayıf"
    print("\n  ÖN KARAR:", verdict)
    res["precheck_verdict"] = verdict
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
