"use client";

import { Badge, EmptyState, Skeleton } from "./ui";
import { formatFixed, formatPct, formatPrice, formatSignedTL } from "../lib/format";
import { netOpenPnlPct, netOpenPnlTry } from "../lib/pnl";
import { usePoll } from "../lib/hooks";
import { baseAsset } from "../lib/opportunity";
import { candidateSources } from "../lib/sources";
import type { PositionsResponse } from "../lib/types";

/**
 * Aktif işlem tablosu — tasarımdaki "Aktif İşlemlerim" tablosu.
 * K/Z NET (gidiş-dönüş komisyonu düşülmüş): backend `pnl_try`/`pnl_pct`
 * öncelikli, yoksa yerel net hesap. Kaynak (hangi sistem) rozet olarak gösterilir.
 */
export default function ActiveTradesTable({ limit = 200, compact = false }: { limit?: number; compact?: boolean }) {
  const { data, error, loading } = usePoll<PositionsResponse>("/api/positions", 10_000);
  const positions = (data?.positions || []).slice(0, limit);

  if (loading && !data) return <Skeleton className="h-40" />;
  if (error && !data) return <EmptyState title="Pozisyonlar alınamadı" hint={error} tone="loss" />;
  if (positions.length === 0)
    return <EmptyState title="Açık pozisyon yok" hint="Otonom veya manuel açılmış bir işlem bulunmuyor." />;

  return (
    <div className="odak-scroll">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
            <th className="pb-2 pr-2 font-medium">Coin</th>
            <th className="pb-2 pr-2 font-medium">Kaynak</th>
            <th className="pb-2 pr-2 font-medium">Yön</th>
            {!compact && <th className="pb-2 pr-2 text-right font-medium">Giriş Fiyatı</th>}
            <th className="pb-2 pr-2 text-right font-medium">Mevcut Fiyat</th>
            <th className="pb-2 pr-2 text-right font-medium">Miktar</th>
            <th className="pb-2 pr-2 text-right font-medium">Kâr/Zarar</th>
            <th className="pb-2 pr-2 text-right font-medium">Kâr/Zarar %</th>
            <th className="pb-2 font-medium">Durum</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos, i) => {
            const preferNet = pos.pnl_try != null && Number.isFinite(Number(pos.pnl_try));
            const pnl = preferNet ? Number(pos.pnl_try) : netOpenPnlTry(pos.entry, pos.current, pos.quantity, pos.side);
            const pct = preferNet && pos.pnl_pct != null ? Number(pos.pnl_pct) : netOpenPnlPct(pos.entry, pos.current, pos.quantity, pos.side);
            const tone = pnl == null ? "text-ink-500" : pnl > 0 ? "text-gain" : pnl < 0 ? "text-loss" : "text-ink-500";
            const long = String(pos.side).toUpperCase() !== "SHORT";
            const tags = candidateSources(pos as unknown as Record<string, unknown>);
            return (
              <tr key={`${pos.symbol}-${pos.entry_time ?? 0}-${pos.auto_paper_id ?? i}`} className="border-t border-line">
                <td className="py-2.5 pr-2">
                  <span className="font-mono font-semibold text-ink-900">{baseAsset(pos.symbol)}</span>
                  <span className="text-ink-400"> / TRY</span>
                </td>
                <td className="py-2.5 pr-2">
                  <div className="flex flex-wrap gap-1">
                    {(tags.length ? tags : [pos.strategy]).slice(0, 2).map((t) => (
                      <Badge key={t} tone="accent">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="py-2.5 pr-2">
                  <Badge tone={long ? "gain" : "loss"}>{long ? "AL" : "SAT"}</Badge>
                </td>
                {!compact && <td className="py-2.5 pr-2 text-right font-mono text-ink-700">{formatPrice(pos.entry)}</td>}
                <td className="py-2.5 pr-2 text-right font-mono text-ink-700">{formatPrice(pos.current)}</td>
                <td className="py-2.5 pr-2 text-right font-mono text-ink-500">{formatFixed(pos.quantity, 2)}</td>
                <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>{formatSignedTL(pnl)}</td>
                <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>{formatPct(pct, 2, true)}</td>
                <td className="py-2.5">
                  <Badge tone={pos.price_stale ? "warn" : "neutral"}>{pos.price_stale ? "Fiyat bayat" : "Açık"}</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
