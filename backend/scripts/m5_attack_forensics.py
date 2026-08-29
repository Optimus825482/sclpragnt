"""Two-hour M5 attack scan + pre-attack M1 forensics.

Adım 1: Tüm işlem gören TRY sembollerinin son 2 saatlik M5 mumlarını çek;
ardışık iki M5 kapanışı arasında +%2 ve üzeri fark üreten "atak"ları tespit et.
Adım 2: Atak başlangıcı M5 mumunun ÖNCESİNDEKİ son 5 kapalı M1 mumunu analiz et
(getiri, hacim spike, ATR%, bant konumu) ve ortak haberci deseni raporla.
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from statistics import mean, median

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.binance_tr_public import trading_symbols, klines, historical_klines


MIN_ATTACK_PCT = 2.0
SCAN_HOURS = 2
PRE_M1_BARS = 5


def m5_features(rows, index):
    """Tek M5 mumunun basit özellikleri."""
    row = rows[index]
    o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
    return {"open": o, "high": h, "low": l, "close": c, "volume": v,
            "body_pct": (c - o) / o * 100 if o else 0,
            "range_pct": (h - l) / l * 100 if l else 0,
            "open_time": int(row[0])}


def pre_attack_m1_features(rows, attack_start_ms):
    """Atak başlangıcından ÖNCE kapanmış son N M1 mumunun haberci özellikleri."""
    pre = [r for r in rows if int(r[0]) + 59_999 <= attack_start_ms]
    window = pre[-PRE_M1_BARS:]
    if len(window) < PRE_M1_BARS:
        return None
    closes = [float(r[4]) for r in window]
    highs = [float(r[2]) for r in window]
    lows = [float(r[3]) for r in window]
    vols = [float(r[5]) for r in window]
    # daha geniş bağlam: 20-bar ortalama hacim (window öncesi dahil)
    avg_vol_all = mean([float(r[5]) for r in pre[-25:-5]]) if len(pre) >= 25 else (mean(vols) or 1)
    trs = []
    for j in range(1, len(rows)):
        h, l, pc = float(rows[j][2]), float(rows[j][3]), float(rows[j - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = mean(trs[-14:]) if len(trs) >= 14 else (mean(trs) or 0)
    last_close = closes[-1]
    hi20 = max([float(r[2]) for r in pre[-20:]]) if len(pre) >= 20 else max(highs)
    lo20 = min([float(r[3]) for r in pre[-20:]]) if len(pre) >= 20 else min(lows)
    return {
        "window_return_pct": round((closes[-1] / closes[0] - 1) * 100, 3),
        "bar_returns_pct": [round((closes[i] / closes[i - 1] - 1) * 100, 3) for i in range(1, len(closes))],
        "volume_ratio_last": round(vols[-1] / avg_vol_all, 2) if avg_vol_all else None,
        "volume_ratio_max": round(max(vols) / avg_vol_all, 2) if avg_vol_all else None,
        "atr_pct": round(atr / last_close * 100, 3) if last_close else None,
        "range_pos": round((last_close - lo20) / (hi20 - lo20), 3) if hi20 > lo20 else None,
        "last_close": last_close,
        "bars": [{"t": datetime.fromtimestamp(int(r[0]) / 1000).strftime("%H:%M"),
                  "ret": round((float(r[4]) / float(rows[rows.index(r) - 1][4]) - 1) * 100, 3) if rows.index(r) > 0 else 0,
                  "vol": float(r[5])} for r in window],
    }


async def main():
    symbols = await trading_symbols("TRY")
    print(f"Aşama 1: {len(symbols)} TRY sembolü, son {SCAN_HOURS} saatlik M5 taraması…", flush=True)
    sem = asyncio.Semaphore(8)
    end_ms = None
    attacks = []

    async def scan(symbol):
        nonlocal end_ms
        async with sem:
            try:
                rows = await klines(symbol, "5m", 24 + 3)  # 2h = 24 mum + pay
            except Exception:
                return
            if len(rows) < 10:
                return
            if end_ms is None:
                end_ms = int(rows[-1][0]) + 300_000
            # son 2 saatlik penceredeki ardışık M5 farkları
            cutoff = int(rows[-1][0]) - SCAN_HOURS * 3_600_000
            for i in range(1, len(rows)):
                prev_close, close = float(rows[i - 1][4]), float(rows[i][4])
                open_time = int(rows[i][0])
                if open_time < cutoff or prev_close <= 0:
                    continue
                change = (close / prev_close - 1) * 100
                if change >= MIN_ATTACK_PCT:
                    f = m5_features(rows, i)
                    f.update({"symbol": symbol, "change_pct": round(change, 2),
                              "prev_close": prev_close})
                    attacks.append(f)

    await asyncio.gather(*(scan(s) for s in symbols))
    attacks.sort(key=lambda a: a["open_time"])
    print(f"Aşama 1 bitti: {len(attacks)} adet ≥%{MIN_ATTACK_PCT} M5 atak bulundu.", flush=True)
    for a in attacks:
        print(f"  {a['symbol']:10} {datetime.fromtimestamp(a['open_time']/1000).strftime('%H:%M')} "
              f"+{a['change_pct']}% gövde %{a['body_pct']:.2f} aralık %{a['range_pct']:.2f}")

    # Aşama 2: her atak için M1 ön analiz
    print(f"\nAşama 2: atak öncesi {PRE_M1_BARS} M1 mum analizi…", flush=True)
    seen = set()
    reports = []
    sem1 = asyncio.Semaphore(6)
    async def analyze(a):
        key = (a["symbol"], a["open_time"])
        if key in seen:
            return
        seen.add(key)
        async with sem1:
            try:
                m1 = await historical_klines(a["symbol"], "1m", 1, end_time_ms=a["open_time"] - 1)
            except Exception:
                return
            if len(m1) < 25:
                return
            feat = pre_attack_m1_features(m1, a["open_time"])
            if feat:
                reports.append({"symbol": a["symbol"], "attack_time": datetime.fromtimestamp(a["open_time"] / 1000).strftime("%H:%M"),
                                 "attack_change_pct": a["change_pct"], "attack_body_pct": round(a["body_pct"], 2),
                                 "pre": feat})

    await asyncio.gather(*(analyze(a) for a in attacks))

    # Aşama 3: ortak desen istatistikleri
    print(f"\nAşama 3: {len(reports)} atak için öncü özellik istatistikleri")
    if reports:
        wr = [r["pre"]["window_return_pct"] for r in reports]
        vr = [r["pre"]["volume_ratio_last"] for r in reports if r["pre"]["volume_ratio_last"]]
        vr_max = [r["pre"]["volume_ratio_max"] for r in reports if r["pre"]["volume_ratio_max"]]
        atr = [r["pre"]["atr_pct"] for r in reports if r["pre"]["atr_pct"]]
        rp = [r["pre"]["range_pos"] for r in reports if r["pre"]["range_pos"] is not None]
        print(f"  5-M1 pencere getirişi : ort {mean(wr):+.2f}% | medyan {median(wr):+.2f}% | pozitif oran %{sum(1 for x in wr if x>0)/len(wr)*100:.0f}")
        if vr: print(f"  hacim oranı (son bar) : ort {mean(vr):.1f}x | medyan {median(vr):.1f}x | ≥2x oran %{sum(1 for x in vr if x>=2)/len(vr)*100:.0f}")
        if vr_max: print(f"  hacim oranı (pencere max): ort {mean(vr_max):.1f}x | medyan {median(vr_max):.1f}x")
        if atr: print(f"  1m ATR%               : ort {mean(atr):.3f} | medyan {median(atr):.3f} | ≥0.15 oran %{sum(1 for x in atr if x>=0.15)/len(atr)*100:.0f}")
        if rp: print(f"  20-bar bant konumu    : ort {mean(rp):.2f} | ≥0.8 oran %{sum(1 for x in rp if x>=0.8)/len(rp)*100:.0f}")
        print("\nSembol bazlı özet:")
        for r in sorted(reports, key=lambda x: -x["attack_change_pct"]):
            p = r["pre"]
            print(f"  {r['symbol']:10} atak {r['attack_time']} +%{r['attack_change_pct']} | "
                  f"ön-pencere %{p['window_return_pct']:+.2f} | hacim {p['volume_ratio_last']}x | "
                  f"ATR %{p['atr_pct']} | bant {p['range_pos']}")

    out = {"generated_at": datetime.now().isoformat(), "scan_hours": SCAN_HOURS,
            "min_attack_pct": MIN_ATTACK_PCT, "attacks": len(attacks), "reports": reports}
    with open("../work/m5_attack_forensics.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=str, indent=1)
    print("\nDetay: work/m5_attack_forensics.json")


if __name__ == "__main__":
    asyncio.run(main())
