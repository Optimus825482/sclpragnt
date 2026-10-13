"use client";

import { usePoll } from "../lib/hooks";
import { formatFixed, formatPct, formatPrice, formatSignedTL } from "../lib/format";
import type { BinancePositions, BinanceSettings } from "../lib/types";
import { Badge, EmptyState, Skeleton } from "./ui";

/** Binance TR gerçek hesabındaki elde tutulan coinleri ve anlık maliyet farkını gösterir. */
export default function ActiveTradesTable({ limit = 200, compact = false }: { limit?: number; compact?: boolean }) {
  const settings = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const account = usePoll<BinancePositions>(settings.data?.configured ? "/api/binance/positions" : null, 20_000);
  const holdings = (account.data?.holdings || []).filter((h) => h.asset !== "TRY" && Number(h.total) > 0).slice(0, limit);

  if (!settings.data?.configured && !settings.loading)
    return <EmptyState title="Binance TR hesabı bağlı değil" hint="Gerçek varlık ve anlık K/Z verisini görmek için Ayarlar'dan hesabınızı bağlayın." />;
  if (settings.loading || (account.loading && !account.data)) return <Skeleton className="h-40" />;
  if (account.error && !account.data) return <EmptyState title="Binance TR varlıkları alınamadı" hint={account.error} tone="loss" />;
  if (holdings.length === 0) return <EmptyState title="Açık varlık yok" hint="Bağlı Binance TR hesabında takip edilecek coin bakiyesi bulunmuyor." />;

  return (
    <div className="odak-scroll">
      <table className="w-full min-w-[740px] border-collapse text-sm">
        <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
          <th className="pb-2 pr-2 font-medium">Coin</th><th className="pb-2 pr-2 font-medium">Kaynak</th><th className="pb-2 pr-2 font-medium">Yön</th>
          {!compact && <th className="pb-2 pr-2 text-right font-medium">Giriş Fiyatı</th>}
          <th className="pb-2 pr-2 text-right font-medium">Mevcut Fiyat</th><th className="pb-2 pr-2 text-right font-medium">Miktar</th>
          <th className="pb-2 pr-2 text-right font-medium">Kâr/Zarar</th><th className="pb-2 pr-2 text-right font-medium">Kâr/Zarar %</th><th className="pb-2 font-medium">Durum</th>
        </tr></thead>
        <tbody>{holdings.map((holding) => {
          const pnl = holding.pnl_try == null ? null : Number(holding.pnl_try);
          const pct = holding.pnl_pct == null ? null : Number(holding.pnl_pct);
          const tone = pnl == null ? "text-ink-500" : pnl > 0 ? "text-gain" : pnl < 0 ? "text-loss" : "text-ink-500";
          return <tr key={holding.asset} className="border-t border-line">
            <td className="py-2.5 pr-2"><span className="font-mono font-semibold text-ink-900">{holding.asset}</span><span className="text-ink-400"> / TRY</span></td>
            <td className="py-2.5 pr-2"><Badge tone="accent">Binance TR</Badge></td>
            <td className="py-2.5 pr-2"><Badge tone="gain">AL</Badge></td>
            {!compact && <td className="py-2.5 pr-2 text-right font-mono text-ink-700">{formatPrice(holding.avg_cost_try)}</td>}
            <td className="py-2.5 pr-2 text-right font-mono text-ink-700">{formatPrice(holding.price_try)}</td>
            <td className="py-2.5 pr-2 text-right font-mono text-ink-500">{formatFixed(holding.total, 6)}</td>
            <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>{formatSignedTL(pnl)}</td>
            <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>{formatPct(pct, 2, true)}</td>
            <td className="py-2.5"><Badge tone="neutral">Açık</Badge></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  );
}
