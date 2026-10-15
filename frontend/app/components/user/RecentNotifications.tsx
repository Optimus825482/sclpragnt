"use client";
import Link from "next/link";
import SymbolLink from "../SymbolLink";
import PctChange from "./PctChange";
import { formatPrice, toMs } from "../../lib/format";

export type RecentRow = { symbol: string; price: number; detected_at: number };

function when(ts: number): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  const time = new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  const rel = min < 1 ? "az önce" : min < 60 ? `${min} dk önce` : `${Math.floor(min / 60)} sa önce`;
  return `${time} · ${rel}`;
}

export default function RecentNotifications({ rows, prices }: { rows: RecentRow[]; prices: Record<string, number> }) {
  const live = (r: RecentRow) => prices[r.symbol.toUpperCase()] ?? prices[r.symbol] ?? null;
  return (
    <section aria-label="Son bildirimler">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Son bildirimler</h2>
        <Link href="/notifications" className="inline-flex min-h-[44px] items-center text-sm text-neon-green">Tümünü gör</Link>
      </div>
      {rows.length === 0 ? (
        <div className="card p-4 text-sm text-bunker-muted">Henüz bildirim yok. Sistem yeni bir fırsat bulduğunda burada görünür.</div>
      ) : (
        <>
          <div className="space-y-2 md:hidden">
            {rows.map((r, i) => (
              <div key={`${r.symbol}-${r.detected_at}-${i}`} className="card p-3">
                <div className="flex min-h-[44px] items-center justify-between">
                  <SymbolLink symbol={r.symbol} className="font-mono text-base font-semibold text-white hover:text-neon-green" />
                  <PctChange base={r.price} live={live(r)} />
                </div>
                <p className="text-xs text-bunker-muted">{when(r.detected_at)}</p>
                <dl className="mt-1 grid grid-cols-2 gap-2 text-sm">
                  <div><dt className="text-bunker-muted">Bildirim fiyatı</dt><dd>{formatPrice(r.price)}</dd></div>
                  <div><dt className="text-bunker-muted">Canlı</dt><dd>{formatPrice(live(r))}</dd></div>
                </dl>
              </div>
            ))}
          </div>
          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="text-left text-bunker-muted">
                <tr>
                  <th className="p-3 font-medium">Zaman</th>
                  <th className="p-3 font-medium">Sembol</th>
                  <th className="p-3 font-medium">Bildirim fiyatı</th>
                  <th className="p-3 font-medium">Canlı</th>
                  <th className="p-3 font-medium">Değişim</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.symbol}-${r.detected_at}-${i}`} className="border-t border-bunker-700">
                    <td className="p-3">{when(r.detected_at)}</td>
                    <td className="p-3"><SymbolLink symbol={r.symbol} /></td>
                    <td className="p-3">{formatPrice(r.price)}</td>
                    <td className="p-3">{formatPrice(live(r))}</td>
                    <td className="p-3"><PctChange base={r.price} live={live(r)} /></td>
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
