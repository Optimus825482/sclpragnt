"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useLiveMessages } from "./liveSocket";
import { useVisibleInterval } from "./useVisibleInterval";

const SILENCE_MS = 15_000;

/** Saf: WS'in kapsamadığı (son yayında bulunmayan) semboller — bunlar WS taze olsa da REST ile yoklanır. */
export function symbolsMissingFromWs(keySymbols: readonly string[], wsSymbols: ReadonlySet<string>): string[] {
  return keySymbols.filter((s) => !wsSymbols.has(s));
}

/**
 * Sembol -> canlı fiyat. Birincil kaynak: backend `watch_prices` WS yayını.
 * WS 15 sn sessiz kalırsa tek toplu `/api/market-tickers` isteğiyle yoklar.
 *
 * 2026-10-18 (denetim #3): backend yayını yalnız son bildirimler + 7 günlük yükselenleri kapsar (üst sınır 50);
 * izleme/favori sembolleri çoğu zaman kapsam dışıdır. Son WS yayınında BULUNMAYAN semboller, WS tazeliğine
 * bakılmaksızın 5 sn'de bir REST ile yoklanır; aksi halde fiyatları "—" ya da donuk kalıyordu.
 */
export function useWatchPrices(symbols: string[]): Record<string, number> {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const lastWsAt = useRef(0);
  const wsSymbols = useRef<Set<string>>(new Set());
  const key = [...new Set(symbols.filter(Boolean).map((s) => s.toUpperCase()))].slice(0, 50).join(",");
  const keyRef = useRef(key);
  keyRef.current = key;

  useLiveMessages(
    useCallback((m: { type: string; data?: unknown }) => {
      if (m?.type !== "watch_prices") return;
      const next = (m.data as { prices?: Record<string, number> } | undefined)?.prices;
      if (next && typeof next === "object") {
        lastWsAt.current = Date.now();
        wsSymbols.current = new Set(Object.keys(next));
        setPrices((cur) => ({ ...cur, ...next }));
      }
    }, []),
    ["watch_prices"],
  );

  const poll = useCallback(async () => {
    if (!keyRef.current) return;
    const wsFresh = Date.now() - lastWsAt.current < SILENCE_MS;
    const want = wsFresh ? symbolsMissingFromWs(keyRef.current.split(","), wsSymbols.current) : keyRef.current.split(",");
    if (want.length === 0) return;
    try {
      const d = await getJSON<{ tickers?: { symbol: string; available: boolean; last: number }[] }>(
        `/api/market-tickers?symbols=${want.join(",")}`,
      );
      const next: Record<string, number> = {};
      for (const t of d.tickers ?? []) if (t.available && t.last > 0) next[t.symbol] = t.last;
      if (Object.keys(next).length === 0) return;
      setPrices((cur) => {
        let changed = false;
        for (const k of Object.keys(next)) if (cur[k] !== next[k]) { changed = true; break; }
        return changed ? { ...cur, ...next } : cur;
      });
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
