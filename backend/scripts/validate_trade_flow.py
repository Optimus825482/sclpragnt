"""historical_trade_flow doğrulaması: dakikalık toplamları historical_candles 1m ile karşılaştırır (2026-10-17).

Örnek: N sembol × G gün (sabit tohumlu). Her dakika için
  - buy_base  ↔ taker_buy_base_volume
  - buy_base + sell_base ↔ volume
  - buy_quote + sell_quote ↔ quote_volume
  - n_trades (aggTrade) ↔ trade_count (ham işlem; aggTrade bitişik dolumları birleştirir → n_trades ≤ trade_count)
Bağıl hata = |a − b| / max(b, ε); dakika başına ve sembol-gün toplamı olarak raporlanır.
Çıktı: stdout + work/tradeflow/validation.md (rapor.md'ye backfill_trade_flow --report-only ile eklenir).

Kullanım (backend/): DATABASE_URL=... python scripts/validate_trade_flow.py --symbols 20 --days 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.backfill_trade_flow import VALIDATION_PATH, WORK_DIR  # noqa: E402

DAY_MS = 86_400_000


def main(argv: list[str] | None = None) -> int:
    import psycopg

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", type=int, default=20)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    rnd = random.Random(args.seed)
    out: list[str] = ["## Doğrulama (historical_candles 1m ile)", ""]
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        pairs = conn.execute(
            "SELECT symbol, (minute_open_ms / %s) AS d, count(*) FROM historical_trade_flow "
            "GROUP BY 1, 2 HAVING count(*) >= 200", (DAY_MS,)).fetchall()
        by_sym: dict[str, list[int]] = {}
        for s, d, _ in pairs:
            by_sym.setdefault(s, []).append(int(d))
        syms = sorted(by_sym)
        rnd.shuffle(syms)
        chosen = syms[: args.symbols]
        stats = []
        for s in sorted(chosen):
            days = by_sym[s][:]
            rnd.shuffle(days)
            for d in sorted(days[: args.days]):
                a, b = d * DAY_MS, (d + 1) * DAY_MS
                rows = conn.execute(
                    "SELECT f.minute_open_ms, f.n_trades, f.buy_base, f.sell_base, f.buy_quote, f.sell_quote, "
                    "c.taker_buy_base_volume, c.volume, c.quote_volume, c.trade_count "
                    "FROM historical_trade_flow f JOIN historical_candles c "
                    "ON c.symbol = f.symbol AND c.timeframe = '1m' AND c.open_time = f.minute_open_ms "
                    "WHERE f.symbol = %s AND f.minute_open_ms >= %s AND f.minute_open_ms < %s", (s, a, b)).fetchall()
                n_flow = conn.execute("SELECT count(*) FROM historical_trade_flow WHERE symbol=%s AND minute_open_ms>=%s AND minute_open_ms<%s",
                                      (s, a, b)).fetchone()[0]
                n_cand_trade = conn.execute("SELECT count(*) FROM historical_candles WHERE symbol=%s AND timeframe='1m' AND open_time>=%s "
                                            "AND open_time<%s AND trade_count > 0", (s, a, b)).fetchone()[0]
                if not rows:
                    continue
                arr = np.array([[float(x) if x is not None else np.nan for x in r] for r in rows])
                nt, bb, sb, bq, sq, tb, vol, qv, tc = (arr[:, i] for i in range(1, 10))

                def rel(x, y):
                    return np.abs(x - y) / np.maximum(np.abs(y), 1e-12)

                ok = ~np.isnan(tb)
                r_buy = rel(bb[ok], tb[ok]) if ok.any() else np.array([np.nan])
                r_vol = rel(bb + sb, vol)
                r_qv = rel(bq + sq, qv)
                stats.append({
                    "sym": s, "day": dt.date.fromordinal(719163 + d).isoformat(), "minutes": len(rows), "flow_min": n_flow, "cand_min": n_cand_trade,
                    "buy_max": float(np.nanmax(r_buy)), "buy_day": float(abs(bb[ok].sum() - tb[ok].sum()) / max(tb[ok].sum(), 1e-12)) if ok.any() else np.nan,
                    "vol_max": float(np.nanmax(r_vol)), "vol_day": float(abs((bb + sb).sum() - vol.sum()) / max(vol.sum(), 1e-12)),
                    "qv_max": float(np.nanmax(r_qv)),
                    "tc_ratio": float(nt.sum() / max(tc.sum(), 1)), "tc_le": float(np.mean(nt <= tc)),
                    "tc_eq": float(np.mean(nt == tc)),
                })
    if not stats:
        out.append("Karşılaştırılacak eşleşen dakika bulunamadı.")
    else:
        out += ["| Sembol | Gün (UTC) | Eşleşen dk | flow dk | mum(trade>0) dk | maks göreli hata buy | gün-toplam hata buy | maks hata hacim | gün-toplam hata hacim | maks hata quote | Σn_trades/Σtrade_count | n≤tc oranı | n=tc oranı |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in stats:
            out.append(f"| {x['sym']} | {x['day']} | {x['minutes']} | {x['flow_min']} | {x['cand_min']} | {x['buy_max']:.2e} | {x['buy_day']:.2e} | "
                       f"{x['vol_max']:.2e} | {x['vol_day']:.2e} | {x['qv_max']:.2e} | {x['tc_ratio']:.3f} | {x['tc_le']:.3f} | {x['tc_eq']:.3f} |")
        out += ["", f"- Örnek: {len(chosen)} sembol × ≤{args.days} gün = {len(stats)} sembol-gün, {sum(x['minutes'] for x in stats):,} eşleşen dakika",
                f"- **Maks göreli hata (dakika) buy_base vs taker_buy_base_volume: {max(x['buy_max'] for x in stats):.3e}**",
                f"- **Maks göreli hata (dakika) buy+sell vs volume: {max(x['vol_max'] for x in stats):.3e}**",
                f"- Maks göreli hata (dakika) quote: {max(x['qv_max'] for x in stats):.3e}",
                f"- Σn_trades/Σtrade_count medyan: {float(np.median([x['tc_ratio'] for x in stats])):.3f} (min {min(x['tc_ratio'] for x in stats):.3f}, maks {max(x['tc_ratio'] for x in stats):.3f}); "
                f"n_trades ≤ trade_count olan dakika oranı ortalama {float(np.mean([x['tc_le'] for x in stats])):.3f}",
                "- Yorum: mum `trade_count` ham işlemleri sayar; aggTrades aynı fiyat/taraf/an dolumlarını birleştirir → `n_trades ≤ trade_count`.", ""]
    text = "\n".join(out)
    print(text)
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(VALIDATION_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
