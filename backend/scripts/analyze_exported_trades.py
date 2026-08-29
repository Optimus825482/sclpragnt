"""Analyze exported trade history + signal decision CSVs for strategy problems."""
import csv
import sys
from collections import Counter, defaultdict
from statistics import mean, median

TRADES_PATH = r"C:\Users\erkan\Downloads\islem-gecmisi (13).csv"
SIGNALS_PATH = r"C:\Users\erkan\Downloads\sinyal-karar-analizi (2).csv"


def parse_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_dt(value):
    """29.08.2026 08:34:00 -> epoch-ish sortable tuple; use datetime."""
    from datetime import datetime
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError):
        return None


def load_trades():
    rows = []
    with open(TRADES_PATH, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    return rows


def load_signals():
    rows = []
    with open(SIGNALS_PATH, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    return rows


def main():
    trades = load_trades()
    signals = load_signals()
    print(f"işlem: {len(trades)} | sinyal: {len(signals)}")

    # 1) Strateji bazlı özet
    by_strategy = defaultdict(list)
    for t in trades:
        by_strategy[t["Strateji"]].append(t)
    print("\n=== STRATEJİ BAZLI ÖZET ===")
    for name, rows in sorted(by_strategy.items(), key=lambda kv: -len(kv[1])):
        pnls = [parse_float(r["PnL"]) for r in rows if parse_float(r["PnL"]) is not None]
        wins = sum(1 for p in pnls if p > 0)
        holds = [parse_float(r["Aktif süre"]) for r in rows if parse_float(r["Aktif süre"])]
        commission = sum(parse_float(r["Komisyon"]) or 0 for r in rows)
        hold_display = f"{mean(holds)/3600:.1f}h" if holds else "—"
        print(f"{name[:44]:44} n={len(rows):4}  net PnL {sum(pnls):+9.1f}  win %{wins/len(pnls)*100:4.1f}"
              f"  ort.süre {hold_display}  komisyon {commission:.1f}")

    # 2) Fisher stratejisi: SL ihlalleri ve max hold ihlalleri
    fisher = by_strategy.get("FISHER_M3_KERNEL_M5_EXACT_PAPER", [])
    if fisher:
        print(f"\n=== FISHER M3+KERNEL M5 DETAY (n={len(fisher)}) ===")
        sl_viol, hold_viol, tp_ok = 0, 0, 0
        worst = []
        for t in fisher:
            pnl_pct = parse_float(t["PnL %"]) or 0
            planned_sl = parse_float(t["Planlanan SL %"])
            planned_hold = parse_float(t["Planlanan azami süre sn"])
            hold = parse_float(t["Aktif süre"]) or 0
            reason = t["Neden"] or ""
            if planned_sl is not None and pnl_pct < -(planned_sl + 0.4):
                sl_viol += 1
                worst.append((pnl_pct, t["Sembol"], planned_sl, hold/3600, reason))
            if planned_hold is not None and hold > planned_hold * 1.1:
                hold_viol += 1
            if reason == "fisher_m3_kernel_m5_exit_cross":
                tp_ok += 1
        print(f"SL ihlali (kayıp > planlı SL+%0.4): {sl_viol}/{len(fisher)}")
        print(f"Max hold ihlali (süre > planlı x1.1): {hold_viol}/{len(fisher)}")
        print("En kötü 8 SL ihlali:")
        for pnl_pct, sym, planned_sl, hours, reason in sorted(worst)[:8]:
            print(f"  {sym:10} {pnl_pct:+7.2f}%  planlı SL %{planned_sl}  {hours:.1f}h  {reason}")
        # exit reason dağılımı
        reasons = Counter(t["Neden"] for t in fisher)
        print("Çıkış nedenleri:", dict(reasons.most_common(6)))

    # 3) Sinyal CSV: blok nedenleri
    print("\n=== SİNYAL BLOK DAĞILIMI ===")
    blocked = [s for s in signals if s["Sinyal"] == "BUY_BLOCKED"]
    reasons = Counter((s["Neden"] or "").split(":")[0] for s in blocked)
    print(f"toplam BUY_BLOCKED: {len(blocked)}")
    for reason, count in reasons.most_common(6):
        print(f"  {reason}: {count}")

    # 4) Saat bazlı PnL (fisher)
    if fisher:
        print("\n=== SAAT BAZLI ORT. PnL % (fisher) ===")
        by_hour = defaultdict(list)
        for t in fisher:
            dt = parse_dt(t["Giriş zamanı"])
            pnl_pct = parse_float(t["PnL %"])
            if dt and pnl_pct is not None:
                by_hour[dt.hour].append(pnl_pct)
        for hour in sorted(by_hour):
            arr = by_hour[hour]
            print(f"  {hour:02d}:00 n={len(arr):3} ort {mean(arr):+.2f}%")

    # 5) Komisyon etkisi
    if fisher:
        gross = sum((parse_float(t["Brüt PnL (TL)"]) or 0) for t in fisher)
        commission = sum((parse_float(t["Komisyon"]) or 0) for t in fisher)
        print(f"\nFisher brüt {gross:+.1f} TL, komisyon {commission:.1f} TL, net {gross - commission:+.1f} TL")
        # kazanan vs kaybeden süre
        win_holds = [parse_float(t["Aktif süre"]) for t in fisher if (parse_float(t["PnL"]) or 0) > 0 and parse_float(t["Aktif süre"])]
        lose_holds = [parse_float(t["Aktif süre"]) for t in fisher if (parse_float(t["PnL"]) or 0) <= 0 and parse_float(t["Aktif süre"])]
        print(f"kazanan ort süre {mean(win_holds)/3600:.1f}h (n={len(win_holds)}) | kaybeden ort süre {mean(lose_holds)/3600:.1f}h (n={len(lose_holds)})")


if __name__ == "__main__":
    main()
