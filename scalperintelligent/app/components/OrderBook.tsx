"use client";

import { useMemo } from "react";
import { usePoll } from "../lib/hooks";
import { formatCompact, formatPrice } from "../lib/format";
import { Badge } from "./ui";

export type MarketDepth = {
  symbol?: string;
  bids?: Array<[number | string, number | string]>;
  asks?: Array<[number | string, number | string]>;
  last_update_ms?: number;
  error?: string;
};

function parseLevels(raw?: Array<[number | string, number | string]>) {
  return (raw || [])
    .map(([price, qty]) => ({ price: Number(price), qty: Number(qty) }))
    .filter((level) => Number.isFinite(level.price) && Number.isFinite(level.qty) && level.price > 0 && level.qty > 0)
    .slice(0, 10);
}

/**
 * Emir defteri (DOM): seçili sembolün canlı alış/satış derinliği + spread.
 * Kaynak: backend public derinlik proxy'si (`/api/market-depth/{symbol}`),
 * özel anahtar içermez; sadece gösterim amaçlıdır.
 */
export default function OrderBook({ symbol }: { symbol: string | null }) {
  const depth = usePoll<MarketDepth>(symbol ? `/api/market-depth/${symbol}?limit=20` : null, 5_000);
  const levels = useMemo(() => {
    const bids = parseLevels(depth.data?.bids);
    const asks = parseLevels(depth.data?.asks);
    return { bids, asks };
  }, [depth.data]);

  if (!symbol) return null;
  const { bids, asks } = levels;
  const bestBid = bids[0]?.price ?? null;
  const bestAsk = asks[0]?.price ?? null;
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null;
  const spreadPct = spread != null && bestAsk ? (spread / bestAsk) * 100 : null;
  const maxQty = Math.max(1, ...bids.map((l) => l.qty), ...asks.map((l) => l.qty));

  return (
    <div className="mt-3 rounded-xl border border-line p-2.5">
      <div className="flex items-center justify-between">
        <p className="odak-kicker">Emir Defteri</p>
        {spread != null && (
          <Badge tone={spreadPct != null && spreadPct > 0.5 ? "warn" : "neutral"}>
            spread {formatPrice(spread)}{spreadPct != null ? ` · %${spreadPct.toFixed(2)}` : ""}
          </Badge>
        )}
      </div>
      {depth.error && !depth.data ? (
        <p className="mt-2 text-[11px] text-loss">Derinlik alınamadı: {depth.error}</p>
      ) : (
        <div className="mt-2 space-y-px font-mono text-[10.5px]">
          {[...asks].reverse().map((level, i) => (
            <div key={`ask-${i}`} className="relative flex items-center justify-between px-1 py-0.5">
              <span className="absolute inset-y-0 right-0 bg-loss/10" style={{ width: `${(level.qty / maxQty) * 100}%` }} aria-hidden="true" />
              <span className="relative text-loss">{formatPrice(level.price)}</span>
              <span className="relative text-ink-500">{formatCompact(level.qty)}</span>
            </div>
          ))}
          {bestBid != null && bestAsk != null && (
            <div className="flex items-center justify-between border-y border-line bg-canvas px-1 py-1 text-[11px] font-bold">
              <span className="text-ink-900">{formatPrice((bestBid + bestAsk) / 2)}</span>
              <span className="text-ink-400">orta</span>
            </div>
          )}
          {bids.map((level, i) => (
            <div key={`bid-${i}`} className="relative flex items-center justify-between px-1 py-0.5">
              <span className="absolute inset-y-0 right-0 bg-gain/10" style={{ width: `${(level.qty / maxQty) * 100}%` }} aria-hidden="true" />
              <span className="relative text-gain">{formatPrice(level.price)}</span>
              <span className="relative text-ink-500">{formatCompact(level.qty)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
