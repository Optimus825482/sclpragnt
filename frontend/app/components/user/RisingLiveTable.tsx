"use client";
import SymbolLink from "../SymbolLink";
import PctChange from "./PctChange";
import { formatPrice } from "../../lib/format";
import { statusLabel } from "../../lib/userUi";

export type RisingRow = {
  symbol: string;
  entry_price: number;
  current_price?: number | null;
  change_pct?: number | null;
  ceiling_pct?: number | null;
  status?: string;
};

const pct = (v: number | null | undefined) =>
  v == null || !Number.isFinite(Number(v)) ? "—" : `%${Number(v).toFixed(1).replace(".", ",")}`;

export default function RisingLiveTable({ rows, prices }: { rows: RisingRow[]; prices: Record<string, number> }) {
  const live = (r: RisingRow) => prices[r.symbol.toUpperCase()] ?? prices[r.symbol] ?? r.current_price ?? null;
  return (
    <section aria-label="Bugün yükselenler">
      <h2 className="mb-2 text-lg font-semibold">Bugün yükselenler</h2>
      {rows.length === 0 ? (
        <div className="card p-4 text-sm text-bunker-muted">Bugün henüz yükselen coin yok.</div>
      ) : (
        <>
          <div className="space-y-2 md:hidden">
            {rows.map((r) => (
              <div key={r.symbol} className="card p-3">
                <div className="flex min-h-[44px] items-center justify-between">
                  <SymbolLink symbol={r.symbol} className="font-mono text-base font-semibold text-white hover:text-neon-green" />
                  <PctChange base={r.entry_price} live={live(r)} />
                </div>
                <dl className="grid grid-cols-3 gap-2 text-sm">
                  <div><dt className="text-bunker-muted">Bildirim</dt><dd>{formatPrice(r.entry_price)}</dd></div>
                  <div><dt className="text-bunker-muted">Canlı</dt><dd>{formatPrice(live(r))}</dd></div>
                  <div><dt className="text-bunker-muted">Tavan</dt><dd>{pct(r.ceiling_pct)}</dd></div>
                </dl>
              </div>
            ))}
          </div>
          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="text-left text-bunker-muted">
                <tr>
                  <th className="p-3 font-medium">Sembol</th>
                  <th className="p-3 font-medium">Bildirim fiyatı</th>
                  <th className="p-3 font-medium">Canlı</th>
                  <th className="p-3 font-medium">Değişim</th>
                  <th className="p-3 font-medium">Tavan</th>
                  <th className="p-3 font-medium">Durum</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol} className="border-t border-bunker-700">
                    <td className="p-3"><SymbolLink symbol={r.symbol} /></td>
                    <td className="p-3">{formatPrice(r.entry_price)}</td>
                    <td className="p-3">{formatPrice(live(r))}</td>
                    <td className="p-3"><PctChange base={r.entry_price} live={live(r)} /></td>
                    <td className="p-3">{pct(r.ceiling_pct)}</td>
                    <td className="p-3">{r.status ? statusLabel(r.status).label : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
