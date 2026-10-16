"use client";
import Link from "next/link";
import PctChange from "../PctChange";
import { formatPrice } from "../../../lib/format";
import { baseSymbol } from "../../../lib/userUi";
import type { WatchItem } from "../../../lib/useWatchPrefs";

/** Ana sayfa üstü: favori semboller (canlı fiyat + favoriye alındığı andan beri değişim). Favori yoksa hiç çizilmez. */
export default function FavoritesStrip({ items, prices, onRemove }: { items: WatchItem[]; prices: Record<string, number>; onRemove: (symbol: string) => void }) {
  if (items.length === 0) return null;
  return (
    <section aria-label="Favoriler">
      <h2 className="mb-2 text-lg font-semibold">Favoriler</h2>
      <ul className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
        {items.map((f) => {
          const live = prices[f.symbol] ?? null;
          return (
            <li key={f.symbol} className="relative shrink-0">
              <Link
                href={`/charts?symbol=${encodeURIComponent(f.symbol)}&timeframe=5m`}
                className="card flex min-h-[44px] items-center gap-3 py-2 pl-3 pr-12"
                aria-label={`${baseSymbol(f.symbol)} grafiğini aç`}
              >
                <span className="font-mono font-bold">{baseSymbol(f.symbol)}<span className="text-bunker-muted">/TRY</span></span>
                <span className="text-sm">{Number(live) > 0 ? `₺${formatPrice(live)}` : "—"}</span>
                <span className="flex flex-col text-xs leading-tight">
                  <PctChange base={f.price} live={live} />
                  {f.price > 0 && <span className="text-bunker-muted">alma {formatPrice(f.price)}</span>}
                </span>
              </Link>
              <button
                type="button"
                aria-label={`${baseSymbol(f.symbol)} favoriden çıkar`}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onRemove(f.symbol); }}
                className="absolute right-0 top-0 inline-flex h-full min-h-[44px] min-w-[44px] items-center justify-center text-lg text-bunker-muted"
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
