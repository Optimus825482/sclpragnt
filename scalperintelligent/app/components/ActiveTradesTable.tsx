"use client";

import Link from "next/link";
import { usePoll } from "../lib/hooks";
import { formatFixed, formatPct, formatPrice, formatSignedTL } from "../lib/format";
import type { BinancePositions, BinanceSettings } from "../lib/types";
import { useWatchlist } from "../lib/watchlist";
import { Badge, EmptyState, PollStatusBand, Skeleton } from "./ui";

/** Binance TR gerçek hesabındaki elde tutulan coinleri ve anlık maliyet farkını gösterir. */
export default function ActiveTradesTable({
  limit = 200,
  compact = false,
  onSelectSymbol,
}: {
  limit?: number;
  compact?: boolean;
  onSelectSymbol?: (symbol: string) => void;
}) {
  const settings = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const account = usePoll<BinancePositions>(settings.data?.configured ? "/api/binance/positions" : null, 20_000);
  const { isFavorite, toggleFavorite } = useWatchlist();

  const holdings = (account.data?.holdings || []).filter((h) => h.asset !== "TRY" && Number(h.total) > 0).slice(0, limit);

  // Ayar isteği HATA verdiyse "bağlı değil" demek yanıltıcı olur (denetim P2):
  // hesap bağlı olabilir, yalnız durum alınamamıştır.
  if (settings.error && !settings.data)
    return <EmptyState title="Binance TR hesap durumu alınamadı" hint={settings.error} tone="loss" />;
  if (!settings.data?.configured && !settings.loading)
    return (
      <EmptyState
        title="Binance TR hesabı bağlı değil"
        hint="Gerçek varlık ve anlık K/Z verisini görmek için Ayarlar'dan hesabınızı bağlayın."
      />
    );
  if (settings.loading || (account.loading && !account.data)) return <Skeleton className="h-40" />;
  if (account.error && !account.data) return <EmptyState title="Binance TR varlıkları alınamadı" hint={account.error} tone="loss" />;
  if (holdings.length === 0)
    return (
      <div className="space-y-2">
        <PollStatusBand error={account.error} updatedAt={account.updatedAt} label="Varlık listesi" />
        <EmptyState title="Açık varlık yok" hint="Bağlı Binance TR hesabında takip edilecek coin bakiyesi bulunmuyor." />
      </div>
    );

  return (
    <div className="odak-scroll">
      <PollStatusBand error={account.error} updatedAt={account.updatedAt} label="Varlık listesi" />
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
            <th className="pb-2 pr-2 font-medium w-8">★</th>
            <th className="pb-2 pr-2 font-medium">Coin</th>
            <th className="pb-2 pr-2 font-medium">Kaynak</th>
            {!compact && <th className="pb-2 pr-2 text-right font-medium">Ortalama Maliyet</th>}
            <th className="pb-2 pr-2 text-right font-medium">Anlık Fiyat</th>
            <th className="pb-2 pr-2 text-right font-medium">Bakiye</th>
            <th className="pb-2 pr-2 text-right font-medium">Net K/Z</th>
            <th className="pb-2 pr-2 text-right font-medium">Getiri %</th>
            <th className="pb-2 text-right font-medium">Hızlı Aksiyon</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((holding) => {
            const symbol = `${holding.asset}TRY`;
            const pnl = holding.pnl_try == null ? null : Number(holding.pnl_try);
            const pct = holding.pnl_pct == null ? null : Number(holding.pnl_pct);
            const tone = pnl == null ? "text-ink-500" : pnl > 0 ? "text-gain font-semibold" : pnl < 0 ? "text-loss font-semibold" : "text-ink-500";
            const fav = isFavorite(symbol);

            return (
              <tr key={holding.asset} className="border-t border-line hover:bg-slate-50/50">
                <td className="py-2.5 pr-2">
                  <button
                    type="button"
                    onClick={() => toggleFavorite(symbol)}
                    className={`text-sm ${fav ? "text-amber-500" : "text-ink-300 hover:text-amber-500"}`}
                    title={fav ? "Favoriden çıkar" : "Favoriye ekle"}
                    aria-label={`${symbol} ${fav ? "favoriden çıkar" : "favoriye ekle"}`}
                    aria-pressed={fav}
                  >
                    {fav ? "★" : "☆"}
                  </button>
                </td>
                <td className="py-2.5 pr-2">
                  <span className="font-mono font-bold text-ink-900">{holding.asset}</span>
                  <span className="text-xs text-ink-400"> / TRY</span>
                </td>
                <td className="py-2.5 pr-2">
                  <Badge tone="accent">Binance TR</Badge>
                </td>
                {!compact && (
                  <td className="py-2.5 pr-2 text-right font-mono text-ink-700">
                    {formatPrice(holding.avg_cost_try)}
                  </td>
                )}
                <td className="py-2.5 pr-2 text-right font-mono text-ink-900 font-medium">
                  {formatPrice(holding.price_try)}
                </td>
                <td className="py-2.5 pr-2 text-right font-mono text-ink-500">
                  {formatFixed(holding.total, 4)}
                </td>
                <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>
                  {pnl == null ? <span title="K/Z hesaplanamadı (maliyet veya fiyat yok)">—</span> : formatSignedTL(pnl)}
                </td>
                <td className={`py-2.5 pr-2 text-right font-mono ${tone}`}>
                  {pct == null ? "—" : formatPct(pct, 2, true)}
                </td>
                <td className="py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <Link
                      href={`/grafik?symbol=${encodeURIComponent(symbol)}`}
                      className="rounded border border-line bg-white px-2 py-1 text-[11px] font-semibold text-accent hover:bg-accent-soft"
                    >
                      Grafik
                    </Link>
                    <button
                      type="button"
                      onClick={() => onSelectSymbol?.(symbol)}
                      className="rounded bg-accent/10 px-2 py-1 text-[11px] font-semibold text-accent hover:bg-accent hover:text-white transition-colors"
                      title="Sembolü emir paneline taşır; emir göndermez"
                      aria-label={`${symbol} sembolünü emir paneline taşı`}
                    >
                      İşlem Yap
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
