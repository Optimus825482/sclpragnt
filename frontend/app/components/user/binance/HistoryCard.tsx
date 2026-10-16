"use client";
import { useCallback, useEffect, useState } from "react";
import { call, type DayTrade } from "../../../lib/tradeApi";
import { localDateInput } from "../../../lib/format";
import { fmtPrice, fmtQty, fmtSignedTry, fmtTry } from "../../../lib/tradeUi";

type DayResponse = { trades?: DayTrade[]; daily?: { realized_pnl_try?: number; wins?: number; losses?: number } | null };

const fmtClock = (ms: number) =>
  new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

export default function HistoryCard({ enabled, refreshKey }: { enabled: boolean; refreshKey: number }) {
  const [day, setDay] = useState(() => localDateInput());
  const [data, setData] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError("");
    const r = await call<DayResponse>("GET", `/api/binance/trades-day?date=${encodeURIComponent(day)}`);
    setLoading(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    setData(r.body);
  }, [day, enabled]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const trades = [...(data?.trades || [])].sort((a, b) => b.time - a.time);
  const pnl = data?.daily?.realized_pnl_try;

  return (
    <section className="card space-y-3 p-4" aria-labelledby="gecmis-baslik">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="gecmis-baslik" className="text-lg font-bold text-white">İşlem geçmişi</h2>
        <label className="text-sm text-white">
          <span className="sr-only">Gün</span>
          <input type="date" value={day} max={localDateInput()} onChange={(e) => setDay(e.target.value)} className="input min-h-[44px] rounded-lg border px-3 text-base" />
        </label>
      </div>
      {pnl != null && (
        <p className="text-sm text-white">
          Günün gerçekleşen sonucu:{" "}
          <strong className={pnl >= 0 ? "text-neon-green" : "text-neon-red"}>{fmtSignedTry(pnl)}</strong>
          <span className="text-bunker-muted"> (komisyon dahil)</span>
        </p>
      )}
      {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
      {loading && trades.length === 0 && <p className="text-sm text-bunker-muted">Yükleniyor…</p>}
      {!loading && !error && trades.length === 0 && <p className="text-sm text-bunker-muted">Bu günde işlem yok.</p>}
      <ul className="divide-y divide-bunker-800">
        {trades.map((t) => (
          <li key={`${t.id}-${t.time}`} className="flex items-center justify-between gap-3 py-2 text-sm">
            <div className="min-w-0 text-white">
              <p className="font-semibold">
                <span className={t.isBuyer ? "text-neon-green" : "text-neon-red"}>{t.isBuyer ? "Alış" : "Satış"}</span>{" "}
                {t.symbol.replace("_", "/")}
              </p>
              <p className="text-bunker-muted">{fmtClock(t.time)} · {fmtQty(Number(t.qty))} adet · fiyat {fmtPrice(Number(t.price))}</p>
            </div>
            <div className="text-right text-white">
              <p>{fmtTry(Number(t.quoteQty))}</p>
              {t.realized_pnl_try != null && !t.isBuyer && (
                <p className={t.realized_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"}>{fmtSignedTry(t.realized_pnl_try)}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
