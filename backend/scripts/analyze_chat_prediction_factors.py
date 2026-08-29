"""Factor attribution for Chat M5/M15 replay picks.

Loads replay result JSONs, merges evaluated picks, and cross-tabulates the
decision-time evidence/risk tags, pool context, MFE/MAE shape and BTC market
beta against the measured outcome. Read-only research helper.
"""
import json
import sys
import glob
from collections import defaultdict, Counter
from statistics import mean, median

sys.path.insert(0, ".")

BTC_SYMBOL = "BTCTRY"


def load_picks(pattern="../work/replay_*.json"):
    picks = []
    for path in sorted(glob.glob(pattern)):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for pick in data.get("picks") or []:
            row = dict(pick)
            row["_source"] = path.split("replay_")[-1].replace(".json", "")
            picks.append(row)
    return picks


def evaluated(picks):
    return [p for p in picks if p.get("status") == "evaluated"]


def tags(pick):
    """Canonical decision-time factor tags from evidence/risks text."""
    result = set()
    for item in pick.get("evidence") or []:
        text = str(item)
        if "EMA hizalaması bullish" in text: result.add("ema_bullish")
        elif "ADX" in text and "trend gücü" in text: result.add("adx_guclu")
        elif "hacim ortalamanın" in text: result.add("hacim_yuksek")
        elif "momentum aynı yönde" in text: result.add("momentum_uyumlu")
        elif "rejim" in text: result.add("rejim_bull")
        elif "işlem kalitesi" in text: result.add("islem_kalitesi")
        elif "spread" in text: result.add("spread_uygun")
        else: result.add(text[:30])
    for item in pick.get("risks") or []:
        text = str(item)
        if "EMA hizalaması karışık" in text: result.add("r_ema_karisik")
        elif "ADX düşük" in text: result.add("r_adx_dusuk")
        elif "hacim verisi eksik" in text: result.add("r_hacim_eksik")
        elif "spread" in text: result.add("r_spread_eksik")
        else: result.add(text[:30])
    return result


def btc_windows(picks):
    """BTC return over each pick's horizon window (market beta factor)."""
    from app.binance_tr_public import historical_klines
    times = [p["decision_at"] for p in picks]
    start_ms = int(min(times) * 1000)
    end_ms = int(max(p["decision_at"] for p in picks) * 1000) + 16 * 60_000
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        batch = historical_klines(BTC_SYMBOL, "1m", 2, end_time_ms=end_ms)
        break
    try:
        rows = historical_klines_sync(BTC_SYMBOL, start_ms, end_ms)
    except Exception:
        pass
    return rows


def historical_klines_sync(symbol, start_ms, end_ms):
    import asyncio
    from app.binance_tr_public import klines
    async def run():
        rows, cursor = [], start_ms
        while cursor < end_ms:
            batch = await klines(symbol, "1m", 1000, cursor, end_ms)
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 1000:
                break
            cursor = int(batch[-1][0]) + 60_000
        return rows
    return asyncio.run(run())


def btc_return_at(candles, decision_at, horizon_minutes):
    due = decision_at + horizon_minutes * 60
    window = [row for row in candles if decision_at * 1000 <= int(row[0]) and int(row[0]) + 59_999 <= due * 1000]
    if len(window) < horizon_minutes * 0.8:
        return None
    return float(window[-1][4]) / float(window[0][1]) - 1


def main():
    picks = load_picks()
    ev = evaluated(picks)
    print(f"Toplam pick: {len(picks)} | değerlendirilebilen: {len(ev)} "
          f"| kaynaklar: {Counter(p['_source'] for p in picks)}")
    if not ev:
        return
    candles = historical_klines_sync(BTC_SYMBOL, int(min(p["decision_at"] for p in ev) * 1000) - 60_000,
                                     int(max(p["decision_at"] for p in ev) * 1000) + 17 * 60_000)
    print(f"BTC 1m mum: {len(candles)}")

    hit = lambda p: 1 if p.get("direction_correct") else 0
    raw_up = lambda p: 1 if p["outcome_return_pct"] > 0 else 0

    print("\n=== 1) KARAR ANI FAKTÖR ETİKETLERİ → SONUÇ (cost-kalibre isabet / saf yukarı isabet / n) ===")
    tag_stats = defaultdict(list)
    for p in ev:
        for t in tags(p):
            tag_stats[t].append(p)
    rows = sorted(tag_stats.items(), key=lambda kv: len(kv[1]), reverse=True)
    for t, arr in rows:
        n = len(arr)
        print(f"  {t:20} n={n:3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  raw-up %{mean(raw_up(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")

    print("\n=== 2) BTC BETA: tahmin penceresinde BTC'nin yönü ===")
    for label, pred in (("BTC yükselirken", lambda b: b and b > 0), ("BTC düşerken", lambda b: b and b < 0)):
        arr = [p for p in ev if pred(btc_return_at(candles, p["decision_at"], p["horizon_minutes"]))]
        if arr:
            print(f"  {label:18} n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  raw-up %{mean(raw_up(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")
    none_beta = [p for p in ev if btc_return_at(candles, p["decision_at"], p["horizon_minutes"]) is None]
    if none_beta:
        print(f"  (BTC penceresi kapanmamış: n={len(none_beta)})")

    print("\n=== 3) MFE/MAE ŞEKLİ: fiyat önce hangi yöne gitti? ===")
    favorable_first = [p for p in ev if p["max_favorable_pct"] >= abs(p["max_adverse_pct"])]
    adverse_first = [p for p in ev if p["max_favorable_pct"] < abs(p["max_adverse_pct"])]
    for label, arr in (("önce yukarı dokunmuş", favorable_first), ("önce aşağı dokunmuş", adverse_first)):
        if arr:
            print(f"  {label:22} n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")

    print("\n=== 4) HAVUZ BAĞLAMI: 24s değişim çok yüksekse (aşırı uzamış) ne oluyor? ===")
    with_pool = [p for p in ev if p.get("pool_change_pct") is not None]
    if with_pool:
        extended = [p for p in with_pool if p["pool_change_pct"] >= 10]
        fresh = [p for p in with_pool if p["pool_change_pct"] < 10]
        for label, arr in (("24s ≥ %10 (aşırı uzamış)", extended), ("24s < %10", fresh)):
            if arr:
                print(f"  {label:24} n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  raw-up %{mean(raw_up(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")
    else:
        print("  (eski veri havuz bağlamı içermiyor)")

    print("\n=== 5) SKOR ÜÇDE-BİRLERİ ===")
    ordered = sorted(ev, key=lambda p: p["score"])
    n = len(ordered)
    for label, arr in (("alt", ordered[:n // 3]), ("orta", ordered[n // 3:2 * n // 3]), ("üst", ordered[2 * n // 3:])):
        if arr:
            print(f"  skor {label:6} ort {mean(p['score'] for p in arr):5.2f}  n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")

    print("\n=== 6) SEMBOL TEKRARI: aynı sembol art arda seçilince ===")
    per_symbol_count = Counter(p["symbol"] for p in ev)
    repeated = [p for p in ev if per_symbol_count[p["symbol"]] >= 5]
    single = [p for p in ev if per_symbol_count[p["symbol"]] < 5]
    for label, arr in (("≥5 kez seçilen", repeated), ("<5 kez", single)):
        if arr:
            print(f"  {label:12} n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")

    print("\n=== 7) SAAT BANDI ===")
    bands = defaultdict(list)
    for p in ev:
        import datetime
        hour = datetime.datetime.fromtimestamp(p["decision_at"]).hour
        bands[("gece 00-06" if hour < 6 else "sabah 06-12" if hour < 12 else "öğle 12-18" if hour < 18 else "akşam 18-24")].append(p)
    for label, arr in sorted(bands.items()):
        if arr:
            print(f"  {label:12} n={len(arr):3}  hit %{mean(hit(p) for p in arr)*100:5.1f}  raw-up %{mean(raw_up(p) for p in arr)*100:5.1f}  ort.getiri %{mean(p['outcome_return_pct'] for p in arr)*100:+.3f}")


if __name__ == "__main__":
    main()
