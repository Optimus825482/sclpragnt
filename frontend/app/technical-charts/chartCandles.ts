import { getJSON } from "../lib/api";

const inFlight = new Map<string, Promise<number[][]>>();

export function requestChartCandles(symbol: string, interval: string): Promise<number[][]> {
  const query = new URLSearchParams({ interval, limit: "300" });
  const path = `/api/market-klines/${encodeURIComponent(symbol)}?${query}`;
  const pending = inFlight.get(path);
  if (pending) return pending;

  // Only share ongoing work. A reload after completion still asks for fresh candles.
  const request = getJSON<{ candles?: number[][] }>(path)
    .then((payload) => Array.isArray(payload?.candles) ? payload.candles : [])
    .finally(() => inFlight.delete(path));
  inFlight.set(path, request);
  return request;
}
