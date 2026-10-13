"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLiveMessages } from "../lib/liveSocket";
import { apiRequest } from "../lib/api";

export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const normalizeSymbol = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]/g, "");

function readCandle(raw: unknown): Candle | null {
  if (Array.isArray(raw)) {
    const [time, open, high, low, close, volume] = raw;
    const values = [Number(time), Number(open), Number(high), Number(low), Number(close), Number(volume)];
    return values.every(Number.isFinite) ? { time: values[0] > 1e12 ? Math.floor(values[0] / 1000) : values[0], open: values[1], high: values[2], low: values[3], close: values[4], volume: values[5] } : null;
  }
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const time = Number(item.time), open = Number(item.open), high = Number(item.high), low = Number(item.low), close = Number(item.close), volume = Number(item.volume ?? 0);
  return [time, open, high, low, close, volume].every(Number.isFinite)
    ? { time: time > 1e12 ? Math.floor(time / 1000) : time, open, high, low, close, volume } : null;
}

export function MarketChart({ initialSymbol = "BTCUSDT", initialInterval = "5m", compact = false }: { initialSymbol?: string; initialInterval?: string; compact?: boolean }) {
  const [symbol, setSymbol] = useState(normalizeSymbol(initialSymbol));
  const [interval, setInterval] = useState<string>(INTERVALS.includes(initialInterval as typeof INTERVALS[number]) ? initialInterval : "5m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [showAverage, setShowAverage] = useState(true);
  const [showEma, setShowEma] = useState(false);
  const [showRsi, setShowRsi] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await apiRequest(`/api/market-klines/${encodeURIComponent(symbol)}?interval=${interval}&limit=200`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Grafik verisi alınamadı (${response.status})`);
      const data = await response.json();
      const rows = Array.isArray(data?.candles) ? data.candles.map(readCandle).filter(Boolean) as Candle[] : [];
      setCandles(rows);
      setError(rows.length ? "" : "Bu sembol ve zaman aralığı için mum verisi yok.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Grafik verisi alınamadı"); }
  }, [symbol, interval]);

  useEffect(() => { setLive(false); void load(); }, [load]);
  useLiveMessages((message) => {
    if (message.type !== "kline" || !message.data || typeof message.data !== "object") return;
    const bar = message.data as Record<string, unknown>;
    if (normalizeSymbol(String(bar.symbol || "")) !== symbol || String(bar.timeframe) !== interval) return;
    const next = readCandle(bar);
    if (!next) return;
    setLive(true);
    setCandles((current) => {
      const index = current.findIndex((row) => row.time === next.time);
      if (index < 0) return [...current.slice(-199), next];
      const copy = current.slice(); copy[index] = next; return copy;
    });
  });

  const geometry = useMemo(() => {
    const rows = candles.slice(-90);
    if (!rows.length) return null;
    const min = Math.min(...rows.map((c) => c.low)), max = Math.max(...rows.map((c) => c.high));
    const pad = (max - min || max * 0.01 || 1) * 0.08;
    const low = min - pad, high = max + pad, width = 900, height = compact ? 300 : 420;
    const y = (price: number) => 16 + ((high - price) / (high - low)) * (height - 42);
    const step = (width - 24) / rows.length;
    const bars = rows.map((c, i) => ({ candle: c, x: 12 + i * step + step / 2, yOpen: y(c.open), yClose: y(c.close), yHigh: y(c.high), yLow: y(c.low), green: c.close >= c.open }));
    const average = rows.map((_, i) => {
      const start = Math.max(0, i - 19), batch = rows.slice(start, i + 1);
      return { x: bars[i].x, y: y(batch.reduce((sum, item) => sum + item.close, 0) / batch.length) };
    });
    const ema: Array<{ x: number; y: number }> = [];
    const alpha = 2 / 13;
    let emaValue = rows[0].close;
    rows.forEach((candle, i) => { emaValue = i === 0 ? candle.close : candle.close * alpha + emaValue * (1 - alpha); ema.push({ x: bars[i].x, y: y(emaValue) }); });
    const rsiChanges = rows.slice(-15).map((candle, index, batch) => index ? candle.close - batch[index - 1].close : 0).slice(1);
    const gains = rsiChanges.reduce((sum, value) => sum + Math.max(0, value), 0) / 14;
    const losses = rsiChanges.reduce((sum, value) => sum + Math.max(0, -value), 0) / 14;
    const rsi = losses === 0 ? 100 : 100 - 100 / (1 + gains / losses);
    return { bars, average, ema, rsi, width, height, low, high };
  }, [candles, compact]);

  return <section className={`rounded-xl border border-line bg-white ${compact ? "p-3" : "p-4 sm:p-5"}`} aria-label={`${symbol} canlı mum grafiği`}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div><div className="flex items-center gap-2"><strong className="font-mono text-lg text-ink-900">{symbol}</strong><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${live ? "bg-gain-soft text-gain" : "bg-canvas text-ink-500"}`}>{live ? "CANLI" : "AKIŞ BEKLENİYOR"}</span></div><p className="mt-1 text-xs text-ink-400">Binance TR mum verisi · SMA 20</p></div>
      <div className="flex flex-wrap items-center gap-2">
        {!compact && <input aria-label="Grafik sembolü" value={symbol} onChange={(e) => setSymbol(normalizeSymbol(e.target.value))} className="w-32 rounded-lg border border-line px-2.5 py-2 font-mono text-xs text-ink-900 outline-none focus:border-accent" />}
        <div className="flex rounded-lg border border-line p-0.5">{INTERVALS.map((value) => <button key={value} type="button" onClick={() => setInterval(value)} className={`rounded-md px-2 py-1.5 text-xs ${interval === value ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{value}</button>)}</div>
        <button type="button" aria-pressed={showAverage} onClick={() => setShowAverage((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showAverage ? "border-accent/30 bg-accent-soft text-accent" : "border-line text-ink-500"}`}>SMA 20 {showAverage ? "Açık" : "Kapalı"}</button>
        <button type="button" aria-pressed={showEma} onClick={() => setShowEma((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showEma ? "border-amber-300 bg-amber-50 text-amber-700" : "border-line text-ink-500"}`}>EMA 12 {showEma ? "Açık" : "Kapalı"}</button>
        <button type="button" aria-pressed={showRsi} onClick={() => setShowRsi((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showRsi ? "border-violet-300 bg-violet-50 text-violet-700" : "border-line text-ink-500"}`}>RSI 14 {showRsi ? "Açık" : "Kapalı"}</button>
        {showRsi && geometry && <span className={`rounded-lg border px-2.5 py-2 text-xs font-mono ${geometry.rsi >= 70 ? "border-loss/30 bg-loss-soft text-loss" : geometry.rsi <= 30 ? "border-gain/30 bg-gain-soft text-gain" : "border-line text-ink-500"}`}>RSI · {geometry.rsi.toFixed(1)}</span>}
      </div>
    </div>
    {geometry ? <div className="overflow-hidden rounded-lg bg-[#fbfdff]">
      <svg viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" aria-label={`${symbol} ${interval} mum grafiği`} className="block h-auto w-full">
        {[0, 1, 2, 3, 4].map((i) => { const y = 12 + i * ((geometry.height - 40) / 4); const value = geometry.high - i * ((geometry.high - geometry.low) / 4); return <g key={i}><line x1="10" x2="890" y1={y} y2={y} stroke="#e8eef5" strokeWidth="1"/><text x="895" y={y + 4} fill="#718096" fontSize="10" textAnchor="end">{value.toLocaleString("tr-TR", { maximumSignificantDigits: 6 })}</text></g>; })}
        {geometry.bars.map(({ candle, x, yOpen, yClose, yHigh, yLow, green }) => { const step = 876 / geometry.bars.length; const color = green ? "#08a66a" : "#e24755"; return <g key={candle.time}><line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth="1.4"/><rect x={x - Math.max(1.3, step * 0.31)} y={Math.min(yOpen, yClose)} width={Math.max(2.6, step * 0.62)} height={Math.max(1.5, Math.abs(yClose - yOpen))} fill={color} rx="0.7"/></g>; })}
        {showAverage && <polyline fill="none" stroke="#3478e5" strokeWidth="1.8" points={geometry.average.map((point) => `${point.x},${point.y}`).join(" ")} />}
        {showEma && <polyline fill="none" stroke="#e3a126" strokeWidth="1.7" points={geometry.ema.map((point) => `${point.x},${point.y}`).join(" ")} />}
        <line x1="12" x2="888" y1={geometry.height - 24} y2={geometry.height - 24} stroke="#dce5ef" />
        {geometry.bars.filter((_, i) => i % Math.max(1, Math.floor(geometry.bars.length / 6)) === 0).map(({ candle, x }) => <text key={`time-${candle.time}`} x={x} y={geometry.height - 8} fill="#718096" fontSize="10" textAnchor="middle">{new Date(candle.time * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}</text>)}
      </svg>
      <div className="flex h-12 items-end gap-[2px] px-3 pb-1" aria-label="Hacim">
        {geometry.bars.map(({ candle, green }) => { const maxVolume = Math.max(1, ...geometry.bars.map((bar) => bar.candle.volume)); return <i key={`v-${candle.time}`} title={`Hacim ${candle.volume}`} className={`flex-1 rounded-t-sm ${green ? "bg-gain/45" : "bg-loss/40"}`} style={{ height: `${Math.max(3, (candle.volume / maxVolume) * 36)}px` }} />; })}
      </div>
    </div> : <div className="grid h-64 place-items-center rounded-lg bg-canvas text-sm text-ink-400">{error || "Mumlar yükleniyor…"}</div>}
    {error && geometry && <p className="mt-2 text-xs text-warn">{error}</p>}
  </section>;
}

export default MarketChart;
