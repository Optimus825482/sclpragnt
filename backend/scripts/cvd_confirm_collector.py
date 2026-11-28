"""CVD onay collector — CryptoHFTData saatlik parquet -> work/cvd_confirmed.jsonl.

CryptoHFTData gerçek zamanlı yayın vermez (docs: "No real-time trading feed",
/v1/status `lookback_hours: 2`); her saat bittikten ~1-2 saat sonra o saatin tam
işlem kayıtları yayınlanır. Bu betik izlenen semboller için yayınlanmış saatleri
indirip gerçek taker akışını (CVD) hesaplar ve JSONL'e yazar. Uygulama tarafı
(`app/confirmed_flow.py`) bu dosyayı yalnızca okur, pandas/cryptohftdata
gerektirmez.

Gerekli venv: pandas + cryptohftdata (research venv), örn.
    backend/work/portal_breakout_replay/.venv-l2

Kullanım:
    python scripts/cvd_confirm_collector.py --once
    python scripts/cvd_confirm_collector.py --symbols TLMTRY --hours 6
    python scripts/cvd_confirm_collector.py --daemon --interval 600
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cryptohftdata as chd
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BACKEND_DIR / "work" / "cvd_confirmed.jsonl"
DEFAULT_SYMBOLS = ("TLMTRY",)
LOOKBACK_HOURS = 6  # her turda son N saat yoklanır


def _row_from_hour(h: pd.DataFrame) -> dict:
    buy = float(h.loc[h["buyer_taker"], "qv"].sum())
    sell = float(h.loc[~h["buyer_taker"], "qv"].sum())
    total = float(h["qv"].sum())
    big = h.nlargest(3, "qv")
    return {
        "trades": int(len(h)),
        "quote_volume": round(total),
        "taker_buy": round(buy),
        "taker_sell": round(sell),
        "net_cvd": round(buy - sell),
        "cvd_pct_of_volume": round((buy - sell) / total * 100, 2) if total else 0.0,
        "vwap": round(total / float(h["quantity"].sum()), 8) if float(h["quantity"].sum()) else None,
        "open": round(float(h["price"].iloc[0]), 8),
        "close": round(float(h["price"].iloc[-1]), 8),
        "high": round(float(h["price"].max()), 8),
        "low": round(float(h["price"].min()), 8),
        "big_prints": [
            {
                "saat": r.ts.strftime("%H:%M"),
                "fiyat": round(r.price, 8),
                "try": round(r.qv),
                "yon": "ALIM" if r.buyer_taker else "SATIM",
            }
            for r in big.itertuples()
        ],
    }


def fetch_day(symbol: str, day: str) -> pd.DataFrame | None:
    try:
        df = chd.get_trades(symbol, chd.exchanges.BINANCE_SPOT, f"{day}T00:00:00", f"{day}T23:59:59")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {symbol} {day} indirilemedi: {exc}", flush=True)
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    df["price"] = df["price"].astype(float)
    df["quantity"] = df["quantity"].astype(float)
    df["qv"] = df["price"] * df["quantity"]
    df["buyer_taker"] = ~df["is_buyer_maker"].astype(bool)
    df["ts"] = pd.to_datetime(df["trade_time"].astype("int64"), unit="ms", utc=True)
    return df


def load_existing(path: Path) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("symbol") and row.get("hour"):
                out[(row["symbol"], row["hour"])] = row
    return out


def write_store(path: Path, store: dict[tuple[str, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for key in sorted(store):
            fh.write(json.dumps(store[key], ensure_ascii=False) + "\n")
    tmp.replace(path)


def collect(symbols: list[str], out: Path, hours: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    store = load_existing(out)
    added = 0
    for symbol in symbols:
        wanted = {(now - timedelta(hours=b)).strftime("%Y-%m-%d") for b in range(1, hours + 1)}
        for day in sorted(wanted):
            frame = fetch_day(symbol, day)
            if frame is None:
                continue
            for back in range(1, hours + 1):
                h_time = now - timedelta(hours=back)
                if h_time.strftime("%Y-%m-%d") != day:
                    continue
                key = (symbol, h_time.strftime("%Y-%m-%dT%H:00:00"))
                if key in store:  # zaten kesinleşmiş
                    continue
                slab = frame[frame["ts"].dt.hour == h_time.hour]
                if slab.empty:
                    continue  # saat henüz yayınlanmadı
                record = {
                    "symbol": symbol,
                    "hour": key[1],
                    "source": "cryptohftdata:binance_spot",
                    "fetched_at": now.isoformat(),
                    "fetched_at_epoch": round(time.time(), 3),
                }
                record.update(_row_from_hour(slab))
                store[key] = record
                added += 1
                print(
                    f"  + {symbol} {key[1]} CVD {record['cvd_pct_of_volume']:+.2f}% "
                    f"hacim {record['quote_volume'] / 1e6:.1f}M ({record['trades']:,} işlem)",
                    flush=True,
                )
    if added:
        write_store(out, store)
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description="CVD onay collector (CryptoHFTData saatlik)")
    ap.add_argument("--symbols", default=os.environ.get("CVD_CONFIRMED_SYMBOLS", ",".join(DEFAULT_SYMBOLS)))
    ap.add_argument("--hours", type=int, default=LOOKBACK_HOURS)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--once", action="store_true", help="tek tur çalış ve çık")
    ap.add_argument("--daemon", action="store_true", help="sürekli çalış")
    ap.add_argument("--interval", type=float, default=600.0, help="daemon tur aralığı (sn)")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out = Path(args.out)
    print(f"# CVD onay collector | semboller={symbols} | çıktı={out}", flush=True)
    while True:
        started = time.time()
        added = collect(symbols, out, args.hours)
        print(f"# tur bitti: {added} yeni saat · {time.time() - started:.1f} sn", flush=True)
        if args.once or not args.daemon:
            return 0
        time.sleep(max(60.0, args.interval))


if __name__ == "__main__":
    sys.exit(main())
