"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLiveMessages } from "../lib/liveSocket";
import { apiRequest } from "../lib/api";

export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const normalizeSymbol = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]/g, "");
const PERIOD = 14;

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

function ema(values: number[], period: number) {
  const result: Array<number | null> = Array(values.length).fill(null);
  if (values.length < period) return result;
  const alpha = 2 / (period + 1);
  let current = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  result[period - 1] = current;
  for (let index = period; index < values.length; index++) {
    current = values[index] * alpha + current * (1 - alpha);
    result[index] = current;
  }
  return result;
}

function indicators(candles: Candle[]) {
  const closes = candles.map((candle) => candle.close);
  const rsi: Array<number | null> = Array(candles.length).fill(null);
  const adx: Array<number | null> = Array(candles.length).fill(null);
  let avgGain = 0, avgLoss = 0;
  if (candles.length > PERIOD) {
    for (let i = 1; i <= PERIOD; i++) {
      const change = closes[i] - closes[i - 1];
      avgGain += Math.max(0, change) / PERIOD;
      avgLoss += Math.max(0, -change) / PERIOD;
    }
    rsi[PERIOD] = avgGain === 0 && avgLoss === 0 ? 50 : avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    for (let i = PERIOD + 1; i < candles.length; i++) {
      const change = closes[i] - closes[i - 1];
      avgGain = (avgGain * (PERIOD - 1) + Math.max(0, change)) / PERIOD;
      avgLoss = (avgLoss * (PERIOD - 1) + Math.max(0, -change)) / PERIOD;
      rsi[i] = avgGain === 0 && avgLoss === 0 ? 50 : avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }

  const dx: Array<number | null> = Array(candles.length).fill(null);
  let trSmooth = 0, plusSmooth = 0, minusSmooth = 0;
  for (let i = 1; i < candles.length; i++) {
    const candle = candles[i], previous = candles[i - 1];
    const tr = Math.max(candle.high - candle.low, Math.abs(candle.high - previous.close), Math.abs(candle.low - previous.close));
    const up = candle.high - previous.high, down = previous.low - candle.low;
    const plus = up > down && up > 0 ? up : 0, minus = down > up && down > 0 ? down : 0;
    if (i <= PERIOD) { trSmooth += tr; plusSmooth += plus; minusSmooth += minus; }
    else { trSmooth = trSmooth - trSmooth / PERIOD + tr; plusSmooth = plusSmooth - plusSmooth / PERIOD + plus; minusSmooth = minusSmooth - minusSmooth / PERIOD + minus; }
    if (i >= PERIOD && trSmooth > 0) {
      const plusDi = 100 * plusSmooth / trSmooth, minusDi = 100 * minusSmooth / trSmooth;
      dx[i] = plusDi + minusDi === 0 ? 0 : 100 * Math.abs(plusDi - minusDi) / (plusDi + minusDi);
    }
  }
  const firstAdxIndex = PERIOD * 2 - 1;
  if (dx.length > firstAdxIndex) {
    let currentAdx = dx.slice(PERIOD, firstAdxIndex + 1).reduce<number>((sum, value) => sum + (value ?? 0), 0) / PERIOD;
    adx[firstAdxIndex] = currentAdx;
    for (let i = firstAdxIndex + 1; i < dx.length; i++) {
      currentAdx = (currentAdx * (PERIOD - 1) + (dx[i] ?? 0)) / PERIOD;
      adx[i] = currentAdx;
    }
  }

  const sma20: Array<number | null> = Array(candles.length).fill(null);
  const upper: Array<number | null> = Array(candles.length).fill(null);
  const lower: Array<number | null> = Array(candles.length).fill(null);
  for (let i = 19; i < candles.length; i++) {
    const batch = closes.slice(i - 19, i + 1);
    const mean = batch.reduce((sum, value) => sum + value, 0) / 20;
    const deviation = Math.sqrt(batch.reduce((sum, value) => sum + (value - mean) ** 2, 0) / 20);
    sma20[i] = mean; upper[i] = mean + 2 * deviation; lower[i] = mean - 2 * deviation;
  }
  const ema12 = ema(closes, 12), ema26 = ema(closes, 26);
  const macd = closes.map((_, i) => ema12[i] != null && ema26[i] != null ? (ema12[i] as number) - (ema26[i] as number) : null);
  const macdSeedIndex = macd.findIndex((value) => value != null);
  const signalOnDense = macdSeedIndex >= 0 ? ema(macd.slice(macdSeedIndex) as number[], 9) : [];
  const histogram: Array<number | null> = Array(candles.length).fill(null);
  if (macdSeedIndex >= 0) {
    for (let i = 0; i < signalOnDense.length; i++) {
      if (signalOnDense[i] != null && macd[macdSeedIndex + i] != null) histogram[macdSeedIndex + i] = (macd[macdSeedIndex + i] as number) - (signalOnDense[i] as number);
    }
  }
  return { rsi, adx, sma20, upper, lower, ema12, histogram };
}

export function MarketChart({ initialSymbol = "BTCUSDT", initialInterval = "5m", compact = false, symbols = [], onSymbolChange }: {
  initialSymbol?: string; initialInterval?: string; compact?: boolean; symbols?: string[]; onSymbolChange?: (symbol: string) => void;
}) {
  const [symbol, setSymbol] = useState(normalizeSymbol(initialSymbol));
  const [interval, setInterval] = useState<string>(INTERVALS.includes(initialInterval as typeof INTERVALS[number]) ? initialInterval : "5m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [showBollinger, setShowBollinger] = useState(true);
  const [showAverage, setShowAverage] = useState(false);
  const [showEma, setShowEma] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => { setSymbol(normalizeSymbol(initialSymbol)); }, [initialSymbol]);
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
    const calc = indicators(candles);
    const start = Math.max(0, candles.length - 90);
    const indexed = candles.map((candle, index) => ({ candle, index })).slice(start);
    if (!indexed.length) return null;
    const prices = indexed.flatMap(({ index, candle }) => [candle.low, candle.high,
      ...(showBollinger && calc.upper[index] != null ? [calc.upper[index] as number, calc.lower[index] as number] : [])]);
    const min = Math.min(...prices), max = Math.max(...prices);
    const pad = (max - min || max * 0.01 || 1) * 0.08;
    const low = min - pad, high = max + pad, width = 900, height = compact ? 270 : 350;
    const y = (price: number) => 16 + ((high - price) / (high - low)) * (height - 42);
    const step = (width - 24) / indexed.length;
    const bars = indexed.map(({ candle, index }, i) => ({ candle, index, x: 12 + i * step + step / 2, yOpen: y(candle.open), yClose: y(candle.close), yHigh: y(candle.high), yLow: y(candle.low), green: candle.close >= candle.open }));
    const line = (values: Array<number | null>) => bars.filter(({ index }) => values[index] != null).map(({ index, x }) => ({ x, y: y(values[index] as number) }));
    const macdValues = bars.map(({ index }) => calc.histogram[index]).filter((value): value is number => value != null);
    const maxMacd = Math.max(0, ...macdValues.map(Math.abs)) || 1;
    const macdHeight = compact ? 58 : 76;
    const macdBars = bars.map(({ candle, index, x }) => ({ candle, x, value: calc.histogram[index], y: calc.histogram[index] == null ? null : (macdHeight / 2) - ((calc.histogram[index] as number) / maxMacd) * (macdHeight * 0.42) }));
    const average = line(calc.sma20);
    const emaLine = line(calc.ema12);
    const lastIndex = candles.length - 1;
    return { bars, upper: line(calc.upper), lower: line(calc.lower), average, ema: emaLine, rsi: calc.rsi[lastIndex], adx: calc.adx[lastIndex], macdBars, macdHeight, width, height, low, high };
  }, [candles, compact, showBollinger]);

  const filteredSymbols = useMemo(() => {
    const query = normalizeSymbol(search);
    if (query.length < 2) return [];
    return symbols.filter((item) => normalizeSymbol(item).includes(query))
      .sort((a, b) => Number(normalizeSymbol(b).startsWith(query)) - Number(normalizeSymbol(a).startsWith(query))).slice(0, 12);
  }, [search, symbols]);

  const changeSymbol = (value: string) => {
    const next = normalizeSymbol(value);
    if (!next) return;
    setSymbol(next);
    onSymbolChange?.(next);
    setSearch(""); setSearchOpen(false);
  };

  return <section className={`rounded-xl border border-line bg-white ${compact ? "p-3" : "p-4 sm:p-5"}`} aria-label={`${symbol} canlı mum grafiği`}>
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div className="relative">
        {compact ? <strong className="font-mono text-lg text-ink-900">{symbol}</strong> : <button type="button" onClick={() => { setSearchOpen((value) => !value); setSearch(""); }} className="font-mono text-lg font-bold text-ink-900 hover:text-accent" aria-expanded={searchOpen} aria-haspopup="listbox">{symbol}⌄</button>}
        <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${live ? "bg-gain-soft text-gain" : "bg-canvas text-ink-500"}`}>{live ? "CANLI" : "AKIŞ BEKLENİYOR"}</span>
        {searchOpen && !compact && <div className="absolute left-0 top-8 z-30 w-64 rounded-lg border border-line bg-white p-2 shadow-pop">
          <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setSearchOpen(false); }} placeholder="İlk 2 harfi yazın…" aria-label="Sembol ara" role="combobox" aria-expanded={filteredSymbols.length > 0} aria-controls={`symbol-options-${symbol}`} className="w-full rounded-md border border-line px-2.5 py-2 font-mono text-sm outline-none focus:border-accent" />
          {search.length > 0 && search.length < 2 && <p className="px-2 py-2 text-xs text-ink-400">Öneriler için en az 2 harf yazın.</p>}
          {search.length >= 2 && <ul id={`symbol-options-${symbol}`} role="listbox" className="mt-1 max-h-56 overflow-auto">{filteredSymbols.length ? filteredSymbols.map((option) => <li key={option}><button type="button" role="option" aria-selected={normalizeSymbol(option) === symbol} onClick={() => changeSymbol(option)} className="w-full rounded px-2 py-1.5 text-left font-mono text-sm hover:bg-accent-soft">{option}</button></li>) : <li className="px-2 py-2 text-xs text-ink-400">Eşleşen sembol yok.</li>}</ul>}
        </div>}
        <p className="mt-1 text-xs text-ink-400">Binance TR mumları · {interval} · RSI/ADX(14)</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-line p-0.5" aria-label="Grafik zaman dilimi">{INTERVALS.map((value) => <button key={value} type="button" aria-pressed={interval === value} onClick={() => setInterval(value)} className={`rounded-md px-2 py-1.5 text-xs ${interval === value ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{value}</button>)}</div>
        <button type="button" aria-pressed={showBollinger} onClick={() => setShowBollinger((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showBollinger ? "border-violet-300 bg-violet-50 text-violet-700" : "border-line text-ink-500"}`}>Bollinger 20,2 {showBollinger ? "Açık" : "Kapalı"}</button>
        <button type="button" aria-pressed={showAverage} onClick={() => setShowAverage((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showAverage ? "border-accent/30 bg-accent-soft text-accent" : "border-line text-ink-500"}`}>SMA 20 {showAverage ? "Açık" : "Ekle"}</button>
        <button type="button" aria-pressed={showEma} onClick={() => setShowEma((value) => !value)} className={`rounded-lg border px-2.5 py-2 text-xs ${showEma ? "border-amber-300 bg-amber-50 text-amber-700" : "border-line text-ink-500"}`}>EMA 12 {showEma ? "Açık" : "Ekle"}</button>
      </div>
    </div>
    <div className="mb-2 flex flex-wrap gap-2 text-xs">
      <span className={`rounded-md border px-2.5 py-1.5 font-mono ${geometry?.rsi != null && geometry.rsi >= 70 ? "border-loss/30 bg-loss-soft text-loss" : geometry?.rsi != null && geometry.rsi <= 30 ? "border-gain/30 bg-gain-soft text-gain" : "border-line bg-white text-ink-600"}`}>RSI 14 · {geometry?.rsi != null ? geometry.rsi.toFixed(1) : "—"}</span>
      <span className="rounded-md border border-line bg-white px-2.5 py-1.5 font-mono text-ink-600">ADX 14 · {geometry?.adx != null ? geometry.adx.toFixed(1) : "—"}</span>
      <span className="rounded-md border border-line bg-white px-2.5 py-1.5 text-ink-400">{interval} mumlarına göre hesaplanır</span>
    </div>
    {geometry ? <div className="overflow-hidden rounded-lg bg-[#fbfdff]">
      <svg viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" aria-label={`${symbol} ${interval} Bollinger bantlı mum grafiği`} className="block h-auto w-full">
        {[0, 1, 2, 3, 4].map((i) => { const y = 12 + i * ((geometry.height - 40) / 4); const value = geometry.high - i * ((geometry.high - geometry.low) / 4); return <g key={i}><line x1="10" x2="890" y1={y} y2={y} stroke="#e8eef5" strokeWidth="1"/><text x="895" y={y + 4} fill="#718096" fontSize="10" textAnchor="end">{value.toLocaleString("tr-TR", { maximumSignificantDigits: 6 })}</text></g>; })}
        {showBollinger && <><polyline fill="none" stroke="#9370db" strokeOpacity="0.75" strokeWidth="1.3" points={geometry.upper.map((point) => `${point.x},${point.y}`).join(" ")} /><polyline fill="none" stroke="#9370db" strokeOpacity="0.75" strokeWidth="1.3" points={geometry.lower.map((point) => `${point.x},${point.y}`).join(" ")} /></>}
        {geometry.bars.map(({ candle, x, yOpen, yClose, yHigh, yLow, green }) => { const step = 876 / geometry.bars.length; const color = green ? "#08a66a" : "#e24755"; return <g key={candle.time}><line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth="1.4"/><rect x={x - Math.max(1.3, step * 0.31)} y={Math.min(yOpen, yClose)} width={Math.max(2.6, step * 0.62)} height={Math.max(1.5, Math.abs(yClose - yOpen))} fill={color} rx="0.7"/></g>; })}
        {showAverage && <polyline fill="none" stroke="#3478e5" strokeWidth="1.8" points={geometry.average.map((point) => `${point.x},${point.y}`).join(" ")} />}
        {showEma && <polyline fill="none" stroke="#e3a126" strokeWidth="1.7" points={geometry.ema.map((point) => `${point.x},${point.y}`).join(" ")} />}
        <line x1="12" x2="888" y1={geometry.height - 24} y2={geometry.height - 24} stroke="#dce5ef" />
        {geometry.bars.filter((_, i) => i % Math.max(1, Math.floor(geometry.bars.length / 6)) === 0).map(({ candle, x }) => <text key={`time-${candle.time}`} x={x} y={geometry.height - 8} fill="#718096" fontSize="10" textAnchor="middle">{new Date(candle.time * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}</text>)}
      </svg>
      <div className="border-t border-line/70 px-3 pb-2 pt-1" aria-label="MACD 12 26 9 histogramı">
        <div className="mb-1 flex items-center justify-between text-[10px] font-medium text-ink-400"><span>MACD 12,26,9 · Histogram</span><span>{interval}</span></div>
        <svg viewBox={`0 0 ${geometry.width} ${geometry.macdHeight}`} role="img" aria-label={`${symbol} MACD histogramı`} className="block h-auto w-full">
          <line x1="10" x2="890" y1={geometry.macdHeight / 2} y2={geometry.macdHeight / 2} stroke="#cbd5e1" strokeDasharray="4 3" />
          {geometry.macdBars.map(({ candle, x, value, y }) => value == null || y == null ? null : <rect key={`macd-${candle.time}`} x={x - Math.max(1.2, (876 / geometry.macdBars.length) * 0.32)} y={Math.min(y, geometry.macdHeight / 2)} width={Math.max(2.4, (876 / geometry.macdBars.length) * 0.64)} height={Math.max(1, Math.abs(geometry.macdHeight / 2 - y))} fill={value >= 0 ? "#08a66a" : "#e24755"} opacity="0.82" rx="0.6" />)}
        </svg>
      </div>
    </div> : <div className="grid h-64 place-items-center rounded-lg bg-canvas text-sm text-ink-400">{error || "Mumlar yükleniyor…"}</div>}
    {error && geometry && <p className="mt-2 text-xs text-warn">{error}</p>}
  </section>;
}

export default MarketChart;
