"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { call, type DayTrade } from "../../../lib/tradeApi";
import { localDateInput } from "../../../lib/format";
import { fmtPrice, fmtQty, fmtSignedPct, fmtSignedTry, fmtTry, groupTradesBySymbol } from "../../../lib/tradeUi";

type DayResponse = { trades?: DayTrade[]; daily?: { realized_pnl_try?: number; wins?: number; losses?: number } | null };

const TH = "whitespace-nowrap px-3 py-2 text-right text-xs font-semibold text-bunker-muted";
const TD_BASE = "whitespace-nowrap px-3 py-2 text-right text-sm";
const TD = `${TD_BASE} text-white`;
// Kâr yeşil, zarar kırmızı (TD'deki `text-white` renk sınıfıyla çakışıp rengi ezmesin diye taban sınıf ayrı).
const pnlTone = (v: number | null | undefined) => (v == null ? "text-white" : v > 0 ? "text-neon-green" : v < 0 ? "text-neon-red" : "text-white");

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

  const groups = useMemo(() => groupTradesBySymbol(data?.trades || []), [data]);
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
      {loading && groups.length === 0 && <p className="text-sm text-bunker-muted">Yükleniyor…</p>}
      {!loading && !error && groups.length === 0 && <p className="text-sm text-bunker-muted">Bu günde işlem yok.</p>}

      {groups.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="data-table w-full min-w-[640px]">
              <caption className="sr-only">Seçilen günün işlemleri, coin bazında gruplu</caption>
              <thead>
                <tr>
                  <th scope="col" className={`${TH} text-left`}>Coin</th>
                  <th scope="col" className={TH}>Alış adet</th>
                  <th scope="col" className={TH}>Ort. alış fiyatı</th>
                  <th scope="col" className={TH}>Alış tutarı</th>
                  <th scope="col" className={TH}>Satış adet</th>
                  <th scope="col" className={TH}>Ort. satış fiyatı</th>
                  <th scope="col" className={TH}>Satış tutarı</th>
                  <th scope="col" className={TH}>Sonuç</th>
                  <th scope="col" className={TH}>K/Z %</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.symbol}>
                    <th scope="row" className={`${TD} text-left font-semibold`}>
                      {g.symbol}
                      <span className="block text-xs font-normal text-bunker-muted">{g.count} işlem</span>
                    </th>
                    <td className={TD}>{g.buyQty > 0 ? fmtQty(g.buyQty) : "—"}</td>
                    <td className={TD}>{g.buyAvg != null ? fmtPrice(g.buyAvg) : "—"}</td>
                    <td className={TD}>{g.buyQty > 0 ? fmtTry(g.buyQuote) : "—"}</td>
                    <td className={TD}>{g.sellQty > 0 ? fmtQty(g.sellQty) : "—"}</td>
                    <td className={TD}>{g.sellAvg != null ? fmtPrice(g.sellAvg) : "—"}</td>
                    <td className={TD}>{g.sellQty > 0 ? fmtTry(g.sellQuote) : "—"}</td>
                    <td className={`${TD_BASE} font-semibold ${pnlTone(g.pnl)}`}>
                      {g.pnl == null ? "—" : fmtSignedTry(g.pnl)}
                    </td>
                    <td className={`${TD_BASE} font-semibold ${pnlTone(g.pnlPct)}`}>
                      {g.pnlPct == null ? "—" : fmtSignedPct(g.pnlPct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-bunker-muted">Ortalama fiyat, toplam tutarın toplam adede bölünmesiyle (ağırlıklı ortalama) hesaplanır.</p>
        </>
      )}
    </section>
  );
}
