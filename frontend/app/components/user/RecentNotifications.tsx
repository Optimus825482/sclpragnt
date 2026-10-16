"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import type { WatchPrefs } from "../../lib/useWatchPrefs";
import BuyDialog from "./home/BuyDialog";
import NotificationCard, { PinnedCompactCard, type CardActions, type RecentRow } from "./home/NotificationCard";

export type { RecentRow } from "./home/NotificationCard";

const nowSeconds = () => Math.floor(Date.now() / 1000);

export default function RecentNotifications({
  rows, prices, failed = false, prefs,
}: { rows: RecentRow[]; prices: Record<string, number>; failed?: boolean; prefs: WatchPrefs }) {
  const [nowSec, setNowSec] = useState(nowSeconds);
  useVisibleInterval(() => setNowSec(nowSeconds()), 30_000);
  const [buy, setBuy] = useState<{ symbol: string; price: number | null } | null>(null);
  const [prefError, setPrefError] = useState("");

  const live = (symbol: string) => prices[symbol.toUpperCase()] ?? prices[symbol] ?? null;
  const guard = (p: Promise<void>) => {
    setPrefError("");
    p.catch(() => setPrefError("Değişiklik kaydedilemedi, lütfen tekrar deneyin."));
  };
  const actions: CardActions = {
    isFavorite: prefs.isFavorite,
    isPinned: prefs.isPinned,
    onToggleFavorite: (s, p) => guard(prefs.toggleFavorite(s, p)),
    onTogglePin: (s, p) => guard(prefs.togglePin(s, p)),
    onBuy: (s, p) => setBuy({ symbol: s, price: p }),
  };

  // İzlemedekiler: bildirim satırı varsa o (ilk eşleşen), yoksa kompakt kart. Satır tekrar listelenmez.
  const { pinnedCards, rest } = useMemo(() => {
    const used = new Set<RecentRow>();
    const cards = prefs.pinned.map((item) => {
      const row = rows.find((r) => !used.has(r) && r.symbol.replace(/_/g, "").toUpperCase() === item.symbol);
      if (row) used.add(row);
      return { item, row };
    });
    return { pinnedCards: cards, rest: rows.filter((r) => !used.has(r)) };
  }, [rows, prefs.pinned]);

  const nothing = rows.length === 0 && pinnedCards.length === 0;
  return (
    <section aria-label="Son bildirimler">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Son bildirimler</h2>
        <Link href="/notifications" className="inline-flex min-h-[44px] items-center text-sm text-neon-green">Tümünü gör</Link>
      </div>
      {prefError && <p role="alert" className="mb-2 rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{prefError}</p>}
      {nothing && failed ? (
        <div role="alert" className="card p-4 text-sm text-neon-red">Bildirimler yüklenemedi. Birazdan yeniden denenecek.</div>
      ) : nothing ? (
        <div className="card p-4 text-sm text-bunker-muted">Henüz bildirim yok. Sistem yeni bir fırsat bulduğunda burada görünür.</div>
      ) : (
        <div className="space-y-5">
          {failed && rows.length === 0 && (
            <div role="alert" className="card p-3 text-sm text-neon-red">Bildirimler yüklenemedi. Birazdan yeniden denenecek.</div>
          )}
          {pinnedCards.length > 0 && (
            <div>
              <h3 className="mb-2 text-base font-semibold">İzlemedekiler</h3>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {pinnedCards.map(({ item, row }) =>
                  row ? (
                    <NotificationCard key={`pin-${item.symbol}`} row={row} live={live(item.symbol)} nowSec={nowSec} actions={actions} pinned={item} />
                  ) : (
                    <PinnedCompactCard key={`pin-${item.symbol}`} item={item} live={live(item.symbol)} actions={actions} />
                  ),
                )}
              </div>
            </div>
          )}
          {rest.length > 0 && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {rest.map((r, i) => (
                <NotificationCard key={`${r.id ?? r.symbol}-${r.detected_at}-${i}`} row={r} rank={i + 1} live={live(r.symbol)} nowSec={nowSec} actions={actions} />
              ))}
            </div>
          )}
        </div>
      )}
      {buy && <BuyDialog open symbol={buy.symbol} referencePrice={buy.price} onClose={() => setBuy(null)} />}
    </section>
  );
}
