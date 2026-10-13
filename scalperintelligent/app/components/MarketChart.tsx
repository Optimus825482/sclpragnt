"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { apiRequest } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { useAuth } from "../lib/auth";

export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
type Indicator = "volume" | "sma" | "ema" | "bollinger" | "rsi" | "macd" | "vwap" | "atr" | "adx";
type IndicatorConfig = { enabled: Indicator[]; periods: { sma: number; ema: number; bollinger: number; rsi: number; atr: number; adx: number } };
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const INDICATORS: Array<{ id: Indicator; label: string }> = [
  { id: "volume", label: "Hacim" }, { id: "sma", label: "SMA" }, { id: "ema", label: "EMA" },
  { id: "bollinger", label: "Bollinger" }, { id: "rsi", label: "RSI" }, { id: "macd", label: "MACD" },
  { id: "vwap", label: "VWAP" }, { id: "atr", label: "ATR" }, { id: "adx", label: "ADX" },
];
const DEFAULT_CONFIG: IndicatorConfig = { enabled: ["volume", "sma", "rsi", "macd"], periods: { sma: 20, ema: 12, bollinger: 20, rsi: 14, atr: 14, adx: 14 } };
const normalizeSymbol = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]/g, "");

function readCandle(raw: unknown): Candle | null {
  if (Array.isArray(raw)) {
    const [rawTime, rawOpen, rawHigh, rawLow, rawClose, rawVolume] = raw;
    const values = [Number(rawTime), Number(rawOpen), Number(rawHigh), Number(rawLow), Number(rawClose), Number(rawVolume)];
    return values.every(Number.isFinite) ? { time: values[0] > 1e12 ? Math.floor(values[0] / 1000) : values[0], open: values[1], high: values[2], low: values[3], close: values[4], volume: values[5] } : null;
  }
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const time = Number(row.time), open = Number(row.open), high = Number(row.high), low = Number(row.low), close = Number(row.close), volume = Number(row.volume ?? 0);
  return [time, open, high, low, close, volume].every(Number.isFinite) ? { time: time > 1e12 ? Math.floor(time / 1000) : time, open, high, low, close, volume } : null;
}

function sma(values: number[], period: number): Array<number | null> {
  const output: Array<number | null> = Array(values.length).fill(null);
  let total = 0;
  for (let index = 0; index < values.length; index++) {
    total += values[index];
    if (index >= period) total -= values[index - period];
    if (index >= period - 1) output[index] = total / period;
  }
  return output;
}

function ema(values: number[], period: number): Array<number | null> {
  const output: Array<number | null> = Array(values.length).fill(null);
  if (values.length < period) return output;
  const alpha = 2 / (period + 1);
  let current = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  output[period - 1] = current;
  for (let index = period; index < values.length; index++) {
    current = values[index] * alpha + current * (1 - alpha);
    output[index] = current;
  }
  return output;
}

function calculate(candles: Candle[], periods: IndicatorConfig["periods"]) {
  const closes = candles.map((candle) => candle.close);
  const middle = sma(closes, periods.bollinger);
  const upper = middle.map((value, index) => {
    if (value == null) return null;
    const values = closes.slice(index - periods.bollinger + 1, index + 1);
    const sd = Math.sqrt(values.reduce((sum, current) => sum + (current - value) ** 2, 0) / periods.bollinger);
    return value + 2 * sd;
  });
  const lower = upper.map((value, index) => value == null || middle[index] == null ? null : 2 * (middle[index] as number) - value);
  const rsi: Array<number | null> = Array(candles.length).fill(null);
  const gains: number[] = [], losses: number[] = [];
  for (let index = 1; index < closes.length; index++) {
    const delta = closes[index] - closes[index - 1];
    gains.push(Math.max(0, delta)); losses.push(Math.max(0, -delta));
  }
  if (gains.length >= periods.rsi) {
    let gain = gains.slice(0, periods.rsi).reduce((sum, value) => sum + value, 0) / periods.rsi;
    let loss = losses.slice(0, periods.rsi).reduce((sum, value) => sum + value, 0) / periods.rsi;
    const value = (g: number, l: number) => l === 0 ? 100 : 100 - 100 / (1 + g / l);
    rsi[periods.rsi] = value(gain, loss);
    for (let index = periods.rsi + 1; index < candles.length; index++) {
      gain = (gain * (periods.rsi - 1) + gains[index - 1]) / periods.rsi;
      loss = (loss * (periods.rsi - 1) + losses[index - 1]) / periods.rsi;
      rsi[index] = value(gain, loss);
    }
  }
  const tr: number[] = [], up: number[] = [], down: number[] = [];
  for (let index = 0; index < candles.length; index++) {
    const current = candles[index], previous = candles[index - 1];
    tr.push(previous ? Math.max(current.high - current.low, Math.abs(current.high - previous.close), Math.abs(current.low - previous.close)) : current.high - current.low);
    up.push(previous && current.high - previous.high > previous.low - current.low && current.high > previous.high ? current.high - previous.high : 0);
    down.push(previous && previous.low - current.low > current.high - previous.high && previous.low > current.low ? previous.low - current.low : 0);
  }
  const atr: Array<number | null> = Array(candles.length).fill(null);
  if (candles.length >= periods.atr) {
    let value = tr.slice(0, periods.atr).reduce((sum, current) => sum + current, 0) / periods.atr;
    atr[periods.atr - 1] = value;
    for (let index = periods.atr; index < candles.length; index++) { value = (value * (periods.atr - 1) + tr[index]) / periods.atr; atr[index] = value; }
  }
  const adx: Array<number | null> = Array(candles.length).fill(null);
  if (candles.length >= periods.adx * 2) {
    let smoothTr = tr.slice(1, periods.adx + 1).reduce((sum, value) => sum + value, 0);
    let smoothUp = up.slice(1, periods.adx + 1).reduce((sum, value) => sum + value, 0);
    let smoothDown = down.slice(1, periods.adx + 1).reduce((sum, value) => sum + value, 0);
    const dx: Array<number | null> = Array(candles.length).fill(null);
    for (let index = periods.adx; index < candles.length; index++) {
      if (index > periods.adx) { smoothTr += tr[index] - smoothTr / periods.adx; smoothUp += up[index] - smoothUp / periods.adx; smoothDown += down[index] - smoothDown / periods.adx; }
      const plus = smoothTr ? 100 * smoothUp / smoothTr : 0, minus = smoothTr ? 100 * smoothDown / smoothTr : 0;
      dx[index] = plus + minus ? 100 * Math.abs(plus - minus) / (plus + minus) : 0;
    }
    const first = periods.adx * 2 - 1;
    let value = dx.slice(periods.adx, first + 1).reduce<number>((sum, current) => sum + (current ?? 0), 0) / periods.adx;
    adx[first] = value;
    for (let index = first + 1; index < candles.length; index++) { value = (value * (periods.adx - 1) + (dx[index] ?? 0)) / periods.adx; adx[index] = value; }
  }
  const macdFast = ema(closes, 12), macdSlow = ema(closes, 26);
  const macd = closes.map((_, index) => macdFast[index] != null && macdSlow[index] != null ? (macdFast[index] as number) - (macdSlow[index] as number) : 0);
  const macdStart = macdSlow.findIndex((value) => value != null);
  const signal = macdStart < 0 ? [] : ema(macd.slice(macdStart), 9);
  const histogram: Array<number | null> = Array(candles.length).fill(null);
  if (macdStart >= 0) for (let index = 0; index < signal.length; index++) if (signal[index] != null) histogram[macdStart + index] = macd[macdStart + index] - (signal[index] as number);
  let weighted = 0, volume = 0;
  const vwap = candles.map((candle) => { weighted += ((candle.high + candle.low + candle.close) / 3) * candle.volume; volume += candle.volume; return volume ? weighted / volume : null; });
  return { sma: sma(closes, periods.sma), ema: ema(closes, periods.ema), upper, lower, rsi, adx, atr, histogram, vwap };
}

function storedConfig(username: string | null, panelId: string): IndicatorConfig {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(`odak_chart_indicators:${String(username || "guest").toLowerCase()}:${panelId}`);
    if (!raw) return DEFAULT_CONFIG;
    const parsed = JSON.parse(raw) as Partial<IndicatorConfig>;
    const enabled = Array.isArray(parsed.enabled) ? parsed.enabled.filter((item): item is Indicator => INDICATORS.some((option) => option.id === item)) : DEFAULT_CONFIG.enabled;
    const periods = { ...DEFAULT_CONFIG.periods, ...(parsed.periods || {}) };
    for (const key of Object.keys(periods) as Array<keyof typeof periods>) periods[key] = Math.max(2, Math.min(200, Number(periods[key]) || DEFAULT_CONFIG.periods[key]));
    return { enabled, periods };
  } catch { return DEFAULT_CONFIG; }
}

export function MarketChart({ initialSymbol = "BTCUSDT", initialInterval = "5m", compact = false, symbols = [], onSymbolChange, onIntervalChange, panelId = "main" }: {
  initialSymbol?: string; initialInterval?: string; compact?: boolean; symbols?: string[]; onSymbolChange?: (symbol: string) => void; onIntervalChange?: (interval: string) => void; panelId?: string;
}) {
  const { username } = useAuth();
  const [symbol, setSymbol] = useState(normalizeSymbol(initialSymbol));
  const [interval, setInterval] = useState<string>(INTERVALS.includes(initialInterval as typeof INTERVALS[number]) ? initialInterval : "5m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [restAt, setRestAt] = useState<number | null>(null);
  const [tickAt, setTickAt] = useState<number | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [ready, setReady] = useState(false);
  const [config, setConfig] = useState<IndicatorConfig>(DEFAULT_CONFIG);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loadedConfigKey, setLoadedConfigKey] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const subContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const subChartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const seriesRef = useRef<Record<string, ISeriesApi<any>>>({});
  const socketStatus = useLiveStatus();
  const socketStatusRef = useRef(socketStatus);
  const tickAtRef = useRef<number | null>(tickAt);
  socketStatusRef.current = socketStatus;
  tickAtRef.current = tickAt;

  useEffect(() => { setSymbol(normalizeSymbol(initialSymbol)); }, [initialSymbol]);
  useEffect(() => { setInterval(INTERVALS.includes(initialInterval as typeof INTERVALS[number]) ? initialInterval : "5m"); }, [initialInterval]);
  const configStorageKey = `odak_chart_indicators:${String(username || "guest").toLowerCase()}:${panelId}`;
  useEffect(() => { setConfig(storedConfig(username, panelId)); setLoadedConfigKey(configStorageKey); }, [configStorageKey, panelId, username]);
  useEffect(() => {
    if (loadedConfigKey !== configStorageKey || typeof window === "undefined") return;
    localStorage.setItem(configStorageKey, JSON.stringify(config));
  }, [config, configStorageKey, loadedConfigKey]);

  const load = useCallback(async () => {
    try {
      const response = await apiRequest(`/api/market-klines/${encodeURIComponent(symbol)}?interval=${interval}&limit=300`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Grafik verisi alınamadı (${response.status})`);
      const body = await response.json();
      const rows = Array.isArray(body?.candles) ? body.candles.map(readCandle).filter(Boolean) as Candle[] : [];
      if (rows.length) setCandles((current) => {
        const live = current.filter((candle) => tickAtRef.current != null && candle.time === current[current.length - 1]?.time && Date.now() - tickAtRef.current < 60_000);
        const merged = new Map(rows.map((candle) => [candle.time, candle]));
        live.forEach((candle) => merged.set(candle.time, candle));
        return Array.from(merged.values()).sort((left, right) => left.time - right.time).slice(-300);
      });
      setRestAt(Date.now());
      setError(rows.length ? "" : "Bu sembol ve zaman aralığı için mum verisi yok.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Grafik verisi alınamadı"); }
  }, [interval, symbol]);
  useEffect(() => { setTickAt(null); void load(); }, [load]);
  useLiveMessages((message) => {
    if (message.type !== "kline" || !message.data || typeof message.data !== "object") return;
    const bar = message.data as Record<string, unknown>;
    if (normalizeSymbol(String(bar.symbol || "")) !== symbol || String(bar.timeframe) !== interval) return;
    const candle = readCandle(bar);
    if (!candle) return;
    tickAtRef.current = Date.now();
    setTickAt(tickAtRef.current);
    setError("");
    setCandles((current) => {
      const index = current.findIndex((row) => row.time === candle.time);
      if (index < 0) return [...current.slice(-299), candle];
      const next = current.slice(); next[index] = candle; return next;
    });
  });
  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(Date.now());
      if (socketStatusRef.current !== "open" || !tickAtRef.current || Date.now() - tickAtRef.current > 30_000) void load();
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    let main: IChartApi | null = null;
    let sub: IChartApi | null = null;
    void import("lightweight-charts").then((charts) => {
      if (cancelled || !containerRef.current || !subContainerRef.current) return;
      const common = { layout: { background: { color: "#ffffff" }, textColor: "#64748b", attributionLogo: true }, grid: { vertLines: { color: "#eef2f7" }, horzLines: { color: "#eef2f7" } }, rightPriceScale: { borderColor: "#e2e8f0" }, timeScale: { borderColor: "#e2e8f0", timeVisible: true, secondsVisible: false }, crosshair: { mode: 1 } };
      main = charts.createChart(containerRef.current, { ...common, width: containerRef.current.clientWidth, height: compact ? 230 : 360 });
      sub = charts.createChart(subContainerRef.current, { ...common, width: subContainerRef.current.clientWidth, height: compact ? 72 : 115, timeScale: { ...common.timeScale, visible: false } });
      chartRef.current = main; subChartRef.current = sub;
      candleSeriesRef.current = main.addSeries(charts.CandlestickSeries, { upColor: "#08a66a", downColor: "#e24755", borderVisible: false, wickUpColor: "#08a66a", wickDownColor: "#e24755" });
      seriesRef.current = {
        volume: main.addSeries(charts.HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false }),
        sma: main.addSeries(charts.LineSeries, { color: "#3478e5", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }),
        ema: main.addSeries(charts.LineSeries, { color: "#e3a126", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }),
        upper: main.addSeries(charts.LineSeries, { color: "#9370db", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }),
        lower: main.addSeries(charts.LineSeries, { color: "#9370db", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }),
        vwap: main.addSeries(charts.LineSeries, { color: "#0e9f9a", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }),
        rsi: sub.addSeries(charts.LineSeries, { color: "#7c3aed", lineWidth: 2, priceScaleId: "rsi" }),
        adx: sub.addSeries(charts.LineSeries, { color: "#f59e0b", lineWidth: 2, priceScaleId: "adx" }),
        atr: sub.addSeries(charts.LineSeries, { color: "#0e9f9a", lineWidth: 2, priceScaleId: "atr" }),
        macd: sub.addSeries(charts.HistogramSeries, { priceScaleId: "macd", priceLineVisible: false, lastValueVisible: false }),
      };
      main.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      ["rsi", "adx", "atr", "macd"].forEach((scale) => sub?.priceScale(scale).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } }));
      main.timeScale().subscribeVisibleLogicalRangeChange((range) => { if (range) sub?.timeScale().setVisibleLogicalRange(range); });
      sub.timeScale().subscribeVisibleLogicalRangeChange((range) => { if (range) main?.timeScale().setVisibleLogicalRange(range); });
      observer = new ResizeObserver(() => {
        if (containerRef.current) main?.applyOptions({ width: containerRef.current.clientWidth });
        if (subContainerRef.current) sub?.applyOptions({ width: subContainerRef.current.clientWidth });
      });
      observer.observe(containerRef.current); observer.observe(subContainerRef.current);
      setReady(true);
    }).catch(() => setError("Grafik bileşeni yüklenemedi."));
    return () => { cancelled = true; observer?.disconnect(); main?.remove(); sub?.remove(); chartRef.current = null; subChartRef.current = null; candleSeriesRef.current = null; seriesRef.current = {}; setReady(false); };
  }, [compact]);

  const values = useMemo(() => calculate(candles, config.periods), [candles, config.periods]);
  useEffect(() => {
    if (!ready || !candleSeriesRef.current || !chartRef.current || !subChartRef.current) return;
    const toTime = (value: number) => value as UTCTimestamp;
    const lineData = (input: Array<number | null>) => candles.flatMap((candle, index) => input[index] == null ? [] : [{ time: toTime(candle.time), value: input[index] as number }]);
    const enabled = new Set(config.enabled);
    candleSeriesRef.current.setData(candles.map((candle) => ({ time: toTime(candle.time), open: candle.open, high: candle.high, low: candle.low, close: candle.close })));
    seriesRef.current.volume?.setData(enabled.has("volume") ? candles.map((candle) => ({ time: toTime(candle.time), value: candle.volume, color: candle.close >= candle.open ? "rgba(8,166,106,.45)" : "rgba(226,71,85,.45)" })) : []);
    seriesRef.current.sma?.setData(enabled.has("sma") ? lineData(values.sma) : []);
    seriesRef.current.ema?.setData(enabled.has("ema") ? lineData(values.ema) : []);
    seriesRef.current.upper?.setData(enabled.has("bollinger") ? lineData(values.upper) : []);
    seriesRef.current.lower?.setData(enabled.has("bollinger") ? lineData(values.lower) : []);
    seriesRef.current.vwap?.setData(enabled.has("vwap") ? lineData(values.vwap) : []);
    seriesRef.current.rsi?.setData(enabled.has("rsi") ? lineData(values.rsi) : []);
    seriesRef.current.adx?.setData(enabled.has("adx") ? lineData(values.adx) : []);
    seriesRef.current.atr?.setData(enabled.has("atr") ? lineData(values.atr) : []);
    seriesRef.current.macd?.setData(enabled.has("macd") ? candles.flatMap((candle, index) => values.histogram[index] == null ? [] : [{ time: toTime(candle.time), value: values.histogram[index] as number, color: (values.histogram[index] as number) >= 0 ? "#08a66a" : "#e24755" }]) : []);
    chartRef.current.timeScale().fitContent(); subChartRef.current.timeScale().fitContent();
  }, [candles, config.enabled, ready, values]);

  const filteredSymbols = useMemo(() => {
    const query = normalizeSymbol(search);
    return query.length < 2 ? [] : symbols.filter((item) => normalizeSymbol(item).includes(query)).sort((a, b) => Number(normalizeSymbol(b).startsWith(query)) - Number(normalizeSymbol(a).startsWith(query))).slice(0, 12);
  }, [search, symbols]);
  const changeSymbol = (value: string) => { const next = normalizeSymbol(value); if (!next) return; setSymbol(next); onSymbolChange?.(next); setSearch(""); setSearchOpen(false); };
  const changeInterval = (value: string) => { setInterval(value); onIntervalChange?.(value); };
  const toggleIndicator = (id: Indicator) => setConfig((previous) => ({ ...previous, enabled: previous.enabled.includes(id) ? previous.enabled.filter((value) => value !== id) : [...previous.enabled, id] }));
  const updatePeriod = (key: keyof IndicatorConfig["periods"], raw: string) => setConfig((previous) => ({ ...previous, periods: { ...previous.periods, [key]: Math.max(2, Math.min(200, Number(raw) || 2)) } }));
  const last = candles[candles.length - 1];
  const tickAge = tickAt == null ? null : Math.max(0, Math.floor((clock - tickAt) / 1000));
  const live = socketStatus === "open" && tickAge != null && tickAge <= 30;
  const restAge = restAt == null ? null : Math.max(0, Math.floor((clock - restAt) / 1000));
  const enabledIndicators = INDICATORS.filter(({ id }) => config.enabled.includes(id));

  return <section className={`rounded-xl border border-line bg-white ${compact ? "p-3" : "p-4 sm:p-5"}`} aria-label={`${symbol} canlı mum grafiği`}>
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div className="relative min-w-0">
        {compact ? <strong className="font-mono text-lg text-ink-900">{symbol}</strong> : <button type="button" onClick={() => { setSearchOpen((value) => !value); setSearch(""); }} className="font-mono text-lg font-bold text-ink-900 hover:text-accent" aria-expanded={searchOpen} aria-haspopup="listbox">{symbol}⌄</button>}
        <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${live ? "bg-gain-soft text-gain" : "bg-canvas text-ink-500"}`}>{live ? "CANLI" : "REST / ESKİ"}</span>
        {!compact && <p className="mt-1 text-xs text-ink-400">Binance TR public mumları · {interval}</p>}
        {searchOpen && !compact && <div className="absolute left-0 top-8 z-30 w-64 rounded-lg border border-line bg-white p-2 shadow-pop">
          <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setSearchOpen(false); }} placeholder="İlk 2 harfi yazın…" aria-label="Sembol ara" role="combobox" aria-expanded={filteredSymbols.length > 0} aria-controls={`symbol-options-${symbol}`} className="w-full rounded-md border border-line px-2.5 py-2 font-mono text-sm outline-none focus:border-accent" />
          {search.length > 0 && search.length < 2 && <p className="px-2 py-2 text-xs text-ink-400">Öneriler için en az 2 harf yazın.</p>}
          {search.length >= 2 && <ul id={`symbol-options-${symbol}`} role="listbox" className="mt-1 max-h-56 overflow-auto">{filteredSymbols.length ? filteredSymbols.map((option) => <li key={option}><button type="button" role="option" aria-selected={normalizeSymbol(option) === symbol} onClick={() => changeSymbol(option)} className="w-full rounded px-2 py-1.5 text-left font-mono text-sm hover:bg-accent-soft">{option}</button></li>) : <li className="px-2 py-2 text-xs text-ink-400">Eşleşen sembol yok.</li>}</ul>}
        </div>}
      </div>
      {!compact && <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-line p-0.5" aria-label="Grafik zaman dilimi">{INTERVALS.map((value) => <button key={value} type="button" aria-pressed={interval === value} onClick={() => changeInterval(value)} className={`rounded-md px-2 py-1.5 text-xs ${interval === value ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{value}</button>)}</div>
        <button type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)} className="rounded-lg border border-line px-2.5 py-2 text-xs text-ink-600">Göstergeler ⚙</button>
      </div>}
    </div>
    {!compact && settingsOpen && <div className="mb-3 rounded-lg border border-line bg-slate-50 p-3">
      <div className="flex flex-wrap gap-2">{INDICATORS.map(({ id, label }) => <button key={id} type="button" aria-pressed={config.enabled.includes(id)} onClick={() => toggleIndicator(id)} className={`rounded-md border px-2.5 py-1.5 text-xs ${config.enabled.includes(id) ? "border-accent bg-accent-soft text-accent" : "border-line bg-white text-ink-500"}`}>{label}</button>)}</div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">{([ ["sma", "SMA"], ["ema", "EMA"], ["bollinger", "BB"], ["rsi", "RSI"], ["atr", "ATR"], ["adx", "ADX"] ] as const).map(([key, label]) => <label key={key} className="text-[10px] text-ink-500">{label} periyodu<input type="number" min={2} max={200} value={config.periods[key]} onChange={(event) => updatePeriod(key, event.target.value)} className="mt-1 w-full rounded border border-line bg-white px-2 py-1 font-mono text-xs text-ink-800" /></label>)}</div>
    </div>}
    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[10px]" aria-label="Gösterge değerleri">
      {enabledIndicators.map(({ id, label }) => {
        const index = candles.length - 1;
        const values: Record<Indicator, number | null> = { volume: last?.volume ?? null, sma: calculatedValue("sma", index), ema: calculatedValue("ema", index), bollinger: calculatedValue("upper", index), rsi: calculatedValue("rsi", index), macd: calculatedValue("histogram", index), vwap: calculatedValue("vwap", index), atr: calculatedValue("atr", index), adx: calculatedValue("adx", index) };
        return <span key={id} className="rounded-md border border-line bg-white px-2 py-1 font-mono text-ink-600">{label}{id === "macd" ? " Hist" : id === "bollinger" ? ` Üst ${config.periods.bollinger},2` : id === "sma" || id === "ema" || id === "rsi" || id === "atr" || id === "adx" ? ` ${config.periods[id]}` : ""} · {values[id] == null ? "—" : values[id]?.toLocaleString("tr-TR", { maximumSignificantDigits: 6 })}</span>;
      })}
    </div>
    <div ref={containerRef} className={`w-full overflow-hidden rounded-t-lg bg-white ${compact ? "h-[230px]" : "h-[360px]"}`} />
    <div ref={subContainerRef} className={`w-full overflow-hidden rounded-b-lg border-t border-line/70 ${compact ? "h-[72px]" : "h-[115px]"} ${config.enabled.some((id) => ["rsi", "macd", "atr", "adx"].includes(id)) ? "" : "hidden"}`} />
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-ink-400" role="status">
      <span>{live ? `WebSocket canlı · son mum ${tickAge}s önce` : `REST yedek · son yenileme ${restAge == null ? "bekleniyor" : `${restAge}s önce`}`}{error ? ` · ${error}` : ""}</span>
      <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" className="underline decoration-dotted">TradingView Lightweight Charts™ attribution</a>
    </div>
  </section>;

  function calculatedValue(key: "sma" | "ema" | "upper" | "rsi" | "histogram" | "vwap" | "atr" | "adx", index: number): number | null {
    const value = values[key][index];
    return value == null ? null : value;
  }
}

export default MarketChart;
