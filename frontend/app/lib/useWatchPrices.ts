"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useLiveMessages } from "./liveSocket";
import { useVisibleInterval } from "./useVisibleInterval";

const SILENCE_MS = 15_000;

/**
 * Sembol -> canlı fiyat. Birincil kaynak: backend `watch_prices` WS yayını.
 * WS 15 sn sessiz kalırsa tek toplu `/api/market-tickers` isteğiyle yoklar.
 */
export function useWatchPrices(symbols: string[]): Record<string, number> {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const lastWsAt = useRef(0);
  const key = [...new Set(symbols.filter(Boolean).map((s) => s.toUpperCase()))].slice(0, 50).join(",");
  const keyRef = useRef(key);
  keyRef.current = key;

  useLiveMessages(
    useCallback((m: { type: string; data?: unknown }) => {
      if (m?.type !== "watch_prices") return;
      const next = (m.data as { prices?: Record<string, number> } | undefined)?.prices;
      if (next && typeof next === "object") {
        lastWsAt.current = Date.now();
        setPrices((cur) => ({ ...cur, ...next }));
      }
    }, []),
    ["watch_prices"],
  );

  const poll = useCallback(async () => {
    if (!keyRef.current) return;
    if (Date.now() - lastWsAt.current < SILENCE_MS) return;
    try {
      const d = await getJSON<{ tickers?: { symbol: string; available: boolean; last: number }[] }>(
        `/api/market-tickers?symbols=${keyRef.current}`,
      );
      const next: Record<string, number> = {};
      for (const t of d.tickers ?? []) if (t.available && t.last > 0) next[t.symbol] = t.last;
      setPrices((cur) => ({ ...cur, ...next }));
    } catch {
      /* sessiz: bir sonraki turda yeniden denenir */
    }
  }, []);

  useVisibleInterval(poll, 5_000);
  useEffect(() => {
    void poll();
  }, [poll, key]);

  return prices;
}
