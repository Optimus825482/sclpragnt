"use client";
import Link from "next/link";
import { useState } from "react";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import type { WatchPrefs } from "../../lib/useWatchPrefs";
import BuyDialog from "./home/BuyDialog";
import type { TradePlan } from "./home/tradePlan";
import NotificationCard, { type CardActions, type RecentRow } from "./home/NotificationCard";

export type { RecentRow } from "./home/NotificationCard";

const nowSeconds = () => Math.floor(Date.now() / 1000);

export default function RecentNotifications({
  rows, prices, failed = false, prefs,
}: { rows: RecentRow[]; prices: Record<string, number>; failed?: boolean; prefs: WatchPrefs }) {
  const [nowSec, setNowSec] = useState(nowSeconds);
  useVisibleInterval(() => setNowSec(nowSeconds()), 30_000);
  const [buy, setBuy] = useState<{ symbol: string; price: number | null; plan: TradePlan | null; planKey: string | null } | null>(null);
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
    onBuy: (s, p, plan, planKey) => setBuy({ symbol: s, price: p, plan: plan ?? null, planKey: planKey ?? null }),
  };

  const nothing = rows.length === 0;
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
        <div className="space-y-3">
          {failed && (
            <div role="alert" className="card p-3 text-sm text-neon-red">Bildirimler yenilenemedi, son bilinen liste gösteriliyor.</div>
          )}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {rows.map((r, i) => (
              <NotificationCard key={`${r.id ?? r.symbol}-${r.detected_at}-${i}`} row={r} rank={i + 1} live={live(r.symbol)} nowSec={nowSec} actions={actions} />
            ))}
          </div>
        </div>
      )}
      {buy && <BuyDialog open symbol={buy.symbol} referencePrice={buy.price} tradePlan={buy.plan} planKey={buy.plan ? buy.planKey : null} onClose={() => setBuy(null)} />}
    </section>
  );
}
