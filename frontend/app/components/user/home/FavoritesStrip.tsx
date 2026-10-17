"use client";
import Link from "next/link";
import PctChange from "../PctChange";
import { formatPrice } from "../../../lib/format";
import { baseSymbol } from "../../../lib/userUi";
import type { WatchItem } from "../../../lib/useWatchPrefs";

type Entry = { symbol: string; price: number; pinned: boolean; favorite: boolean };

/** İzlemedekiler (önce) + favoriler tek listede birleşir; aynı sembol bir kez, fiyat referansı izlemeye alındığı andaki fiyattır. */
export function mergeWatch(pinned: WatchItem[], favorites: WatchItem[]): Entry[] {
  const map = new Map<string, Entry>();
  for (const p of pinned) map.set(p.symbol, { symbol: p.symbol, price: p.price, pinned: true, favorite: false });
  for (const f of favorites) {
    const e = map.get(f.symbol);
    if (e) {
      e.favorite = true;
      if (!(e.price > 0)) e.price = f.price;
    } else {
      map.set(f.symbol, { symbol: f.symbol, price: f.price, pinned: false, favorite: true });
    }
  }
  return [...map.values()];
}

/**
 * Ana sayfanın en üstü: izlemedeki + favori semboller için küçük kartlar (sembol, canlı fiyat,
 * kayıt fiyatına göre %, "İzlemede"/"Favori" etiketi, × ile çıkarma). Hiç yoksa çizilmez.
 */
export default function WatchStrip({
  pinned, favorites, prices, onRemove,
}: {
  pinned: WatchItem[];
  favorites: WatchItem[];
  prices: Record<string, number>;
  onRemove: (symbol: string, which: { pinned: boolean; favorite: boolean }) => void;
}) {
  const entries = mergeWatch(pinned, favorites);
  if (entries.length === 0) return null;
  return (
    <section aria-label="İzlediklerim">
      <h2 className="mb-1 text-base font-semibold">İzlediklerim</h2>
      <ul className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
        {entries.map((e) => {
          const live = prices[e.symbol] ?? null;
          const tags = [e.pinned && "İzlemede", e.favorite && "Favori"].filter(Boolean).join(" · ");
          const removeWhat = e.pinned && e.favorite ? "izlemeden ve favoriden" : e.pinned ? "izlemeden" : "favoriden";
          return (
            <li key={e.symbol} className="relative shrink-0">
              <Link
                href={`/charts?symbol=${encodeURIComponent(e.symbol)}&timeframe=5m`}
                className="card flex min-h-[44px] flex-col justify-center px-3 py-1.5 pr-10 leading-tight"
                aria-label={`${baseSymbol(e.symbol)} grafiğini aç`}
              >
                <span className="font-mono text-sm font-bold">{baseSymbol(e.symbol)}<span className="text-bunker-muted">/TRY</span></span>
                <span className="flex items-baseline gap-2 text-xs">
                  <span>{Number(live) > 0 ? `₺${formatPrice(live)}` : "—"}</span>
                  <PctChange base={e.price} live={live} />
                </span>
                <span className="text-[10px] text-bunker-muted">{tags}</span>
              </Link>
              <button
                type="button"
                aria-label={`${baseSymbol(e.symbol)} ${removeWhat} çıkar`}
                onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); onRemove(e.symbol, { pinned: e.pinned, favorite: e.favorite }); }}
                className="absolute right-0 top-0 inline-flex h-full min-h-[44px] w-9 items-center justify-center text-lg text-bunker-muted"
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
