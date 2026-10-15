"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../lib/api";

export type FavoriteTicker = {
  symbol: string;
  available: boolean;
  last?: number | null;
  change_pct?: number | null;
  updated_at?: number;
};

type Props = { favorites: string[] };

export default function FavoriteTickerBand({ favorites }: Props) {
  const [tickers, setTickers] = useState<FavoriteTicker[]>([]);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [error, setError] = useState(false);
  const [directions, setDirections] = useState<Record<string, "up" | "down" | "flat">>({});
  const previousTickers = useRef<FavoriteTicker[]>([]);

  useEffect(() => {
    if (favorites.length === 0) {
      previousTickers.current = [];
      setTickers([]);
      setCheckedAt(null);
      return;
    }
    let active = true;
    const symbols = Array.from(new Set(favorites.map((symbol) => symbol.toUpperCase()))).slice(0, 50);
    const query = new URLSearchParams({ symbols: symbols.join(",") });

    const refresh = async () => {
      try {
        const response = await apiRequest(`/api/market-tickers?${query.toString()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`Ticker ${response.status}`);
        const body = await response.json();
        if (!active) return;
        const next = Array.isArray(body?.tickers) ? body.tickers as FavoriteTicker[] : [];
        const previousBySymbol = new Map(previousTickers.current.map((ticker) => [ticker.symbol, ticker]));
        const movement: Record<string, "up" | "down" | "flat"> = {};
        // Yön (renk) iki poll arası fiyat farkından; yüzde ise SUNUCUNUN 24s
        // change_pct değeri (denetim P2: eskiden poll farkı 24s değişimi gibi basılıyordu).
        next.forEach((ticker) => {
          const before = previousBySymbol.get(ticker.symbol)?.last;
          const after = ticker.last;
          const delta = before != null && before > 0 && after != null ? after - before : null;
          movement[ticker.symbol] = delta == null || delta === 0 ? "flat" : delta > 0 ? "up" : "down";
        });
        previousTickers.current = next;
        setDirections(movement);
        setTickers(next);
        setCheckedAt(Number(body?.generated_at) || Date.now() / 1000);
        setError(false);
      } catch {
        if (active) setError(true);
      }
    };

    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [favorites]);

  if (favorites.length === 0) return null;
  const bySymbol = new Map(tickers.map((ticker) => [ticker.symbol, ticker]));
  const now = Date.now() / 1000;
  const stale = error || checkedAt == null || now - checkedAt > 25;

  return (
    <div className="favorite-ticker-sticky border-b border-line bg-slate-950 text-white" aria-label="Favori fiyatları">
      <div className="mx-auto flex min-h-10 max-w-[1600px] items-center gap-3 px-3 sm:px-6">
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Favoriler</span>
        <div className="odak-ticker-scroll flex min-w-0 flex-1 items-center gap-2 overflow-x-auto py-1" role="list">
          {favorites.map((symbol) => {
            const ticker = bySymbol.get(symbol);
            const age = ticker?.updated_at ? Math.max(0, now - ticker.updated_at) : Infinity;
            const itemStale = stale || age > 25;
            const direction = directions[symbol] || "flat";
            const color = itemStale ? "text-slate-400" : direction === "up" ? "text-emerald-400" : direction === "down" ? "text-rose-400" : "text-slate-200";
            const change = ticker?.change_pct;
            return (
              <div key={symbol} role="listitem" className={`flex shrink-0 items-center gap-1.5 rounded-md bg-white/5 px-2 py-1 font-mono text-[11px] ${color}`}>
                <span className="font-semibold">{symbol}</span>
                <span>{ticker?.available && ticker.last != null ? ticker.last.toLocaleString("tr-TR", { maximumSignificantDigits: 8 }) : "—"}</span>
                <span title="24 saatlik değişim">{change == null ? "(—)" : `(${change >= 0 ? "+" : ""}${change.toFixed(2)}%)`}</span>
                {itemStale && <span className="rounded bg-amber-400/15 px-1 text-[9px] text-amber-300">ESKİ</span>}
              </div>
            );
          })}
        </div>
        <span className={`hidden shrink-0 text-[9px] sm:inline ${stale ? "text-amber-300" : "text-emerald-300"}`} role="status">
          {stale ? "Public fiyat · bağlantı eski" : "Public fiyat · güncel"}
        </span>
      </div>
    </div>
  );
}
