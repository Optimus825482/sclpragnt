"use client";

import { Badge, EmptyState, Skeleton } from "./ui";
import { formatFixed, formatPct, formatPrice, formatSignedTL } from "../lib/format";
import { netOpenPnlPct, netOpenPnlTry } from "../lib/pnl";
import { usePoll } from "../lib/hooks";
import type { PositionsResponse } from "../lib/types";

/**
 * Aktif işlem tablosu — tasarımdaki "Aktif İşlemlerim" tablosunun gerçek
 * veriyle eşlenmiş hâli. K/Z NET (gidiş-dönüş komisyonu düşülmüş) hesaplanır;
 * backend'in `pnl_try`/`pnl_pct` alanları öncelikli, yoksa yerel net hesap.
 */
export default function ActiveTradesTable({ limit = 5, showHeaderLink = true }: { limit?: number; showHeaderLink?: boolean }) {
  const { data, error, loading } = usePoll<PositionsResponse>("/api/positions", 10_000);
  const positions = (data?.positions || []).slice(0, limit);

  if (loading && !data) {
    return <Skeleton className="h-40" />;
  }
  if (error && !data) {
    return <EmptyState title="Pozisyonlar alınamadı" hint={error} tone="loss" />;
  }
  if (positions.length === 0) {
    return <EmptyState title="Açık pozisyon yok" hint="Otonom veya manuel açılmış bir işlem bulunmuyor." />;
  }

  return (
    <div className="odak-scroll">
      <table className="w-full min-w-[680px] border-collapse text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
            <th className="pb-2 pr-3 font-medium">Coin</th>
            <th className="pb-2 pr-3 font-medium">Yön</th>
            <th className="pb-2 pr-3 text-right font-medium">Giriş</th>
            <th className="pb-2 pr-3 text-right font-medium">Güncel</th>
            <th className="pb-2 pr-3 text-right font-medium">Miktar</th>
            <th className="pb-2 pr-3 text-right font-medium">K/Z</th>
            <th className="pb-2 pr-3 text-right font-medium">K/Z %</th>
            <th className="pb-2 font-medium">Durum</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const preferNet = pos.pnl_try != null && Number.isFinite(Number(pos.pnl_try));
            const pnl = preferNet ? Number(pos.pnl_try) : netOpenPnlTry(pos.entry, pos.current, pos.quantity, pos.side);
            const pct = preferNet && pos.pnl_pct != null ? Number(pos.pnl_pct) : netOpenPnlPct(pos.entry, pos.current, pos.quantity, pos.side);
            const tone = pnl == null ? "text-ink-500" : pnl > 0 ? "text-gain" : pnl < 0 ? "text-loss" : "text-ink-500";
            const long = String(pos.side).toUpperCase() !== "SHORT";
            return (
              <tr key={`${pos.symbol}-${pos.entry_time ?? 0}-${pos.auto_paper_id ?? pos.strategy}`} className="border-t border-line">
                <td className="py-2.5 pr-3 font-mono font-semibold text-ink-900">{pos.symbol}</td>
                <td className="py-2.5 pr-3">
                  <Badge tone={long ? "gain" : "loss"}>{long ? "AL" : "SAT"}</Badge>
                </td>
                <td className="py-2.5 pr-3 text-right font-mono text-ink-700">{formatPrice(pos.entry)}</td>
                <td className="py-2.5 pr-3 text-right font-mono text-ink-700">{formatPrice(pos.current)}</td>
                <td className="py-2.5 pr-3 text-right font-mono text-ink-500">{formatFixed(pos.quantity, 2)}</td>
                <td className={`py-2.5 pr-3 text-right font-mono ${tone}`}>{formatSignedTL(pnl)}</td>
                <td className={`py-2.5 pr-3 text-right font-mono ${tone}`}>{formatPct(pct, 2, true)}</td>
                <td className="py-2.5">
                  <Badge tone={pos.price_stale ? "warn" : "neutral"}>{pos.price_stale ? "Fiyat bayat" : pos.strategy || "Açık"}</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
