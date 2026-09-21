"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
    createChart,
    CandlestickSeries,
    LineSeries,
    HistogramSeries,
    IChartApi,
    ISeriesApi,
    UTCTimestamp,
    ColorType,
    LineStyle,
} from "lightweight-charts";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice, pricePrecision } from "../lib/format";

export interface ChartIndicators {
    // EMAs
    ema9: boolean;
    ema21: boolean;
    ema50: boolean;
    ema200: boolean;
    // Bands
    bollinger: boolean;
    // Volume-based
    volume: boolean;
    vwap: boolean;
    obv: boolean;
    mfi: boolean;
    // Oscillators (subpane)
    rsi: boolean;
    macd: boolean;
    stochastic: boolean;
    williamsR: boolean;
    cci: boolean;
    // Trend
    atr: boolean;
    supertrend: boolean;
}

export interface MultiChartConfig {
    id: number;
    symbol: string;
    interval: string;
    indicators: ChartIndicators;
}

interface MultiChartCardProps {
    config: MultiChartConfig;
    availableSymbols: string[];
    isMaximized: boolean;
    onToggleMaximize: () => void;
    onUpdateConfig: (updated: Partial<MultiChartConfig>) => void;
}

const INTERVALS = [
    { v: "1m",  l: "1D" },
    { v: "3m",  l: "3D" },
    { v: "5m",  l: "5D" },
    { v: "15m", l: "15D" },
    { v: "30m", l: "30D" },
    { v: "1h",  l: "1S" },
    { v: "4h",  l: "4S" },
    { v: "1d",  l: "1G" },
];

const INTERVAL_MS: Record<string, number> = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
};

// ─── Math utilities ───────────────────────────────────────────────────────────

type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };
type Point = { time: UTCTimestamp; value: number };

function calcEMA(bars: Bar[], period: number): Point[] {
    if (bars.length < period) return [];
    const k = 2 / (period + 1);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += bars[i].close;
    let ema = sum / period;
    const result: Point[] = [{ time: bars[period - 1].time as UTCTimestamp, value: ema }];
    for (let i = period; i < bars.length; i++) {
        ema = bars[i].close * k + ema * (1 - k);
        result.push({ time: bars[i].time as UTCTimestamp, value: ema });
    }
    return result;
}

function calcSMA(bars: Bar[], period: number): Point[] {
    const result: Point[] = [];
    for (let i = period - 1; i < bars.length; i++) {
        let sum = 0;
        for (let j = 0; j < period; j++) sum += bars[i - j].close;
        result.push({ time: bars[i].time as UTCTimestamp, value: sum / period });
    }
    return result;
}

function calcBollinger(bars: Bar[], period = 20, mult = 2) {
    const upper: Point[] = [], middle: Point[] = [], lower: Point[] = [];
    for (let i = period - 1; i < bars.length; i++) {
        let sum = 0;
        for (let j = 0; j < period; j++) sum += bars[i - j].close;
        const sma = sum / period;
        let varSum = 0;
        for (let j = 0; j < period; j++) varSum += Math.pow(bars[i - j].close - sma, 2);
        const std = Math.sqrt(varSum / period);
        const t = bars[i].time as UTCTimestamp;
        middle.push({ time: t, value: sma });
        upper.push({ time: t, value: sma + mult * std });
        lower.push({ time: t, value: sma - mult * std });
    }
    return { upper, middle, lower };
}

function calcRSI(bars: Bar[], period = 14): Point[] {
    if (bars.length <= period) return [];
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
        const d = bars[i].close - bars[i - 1].close;
        if (d >= 0) gains += d; else losses -= d;
    }
    let ag = gains / period, al = losses / period;
    const result: Point[] = [{ time: bars[period].time as UTCTimestamp, value: 100 - 100 / (1 + (al === 0 ? 100 : ag / al)) }];
    for (let i = period + 1; i < bars.length; i++) {
        const d = bars[i].close - bars[i - 1].close;
        ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
        al = (al * (period - 1) + (d < 0 ? -d : 0)) / period;
        result.push({ time: bars[i].time as UTCTimestamp, value: 100 - 100 / (1 + (al === 0 ? 100 : ag / al)) });
    }
    return result;
}

// ADX-14 (Wilder): TR/+DM/-DM Wilder yumuşatması → DI+/DI- → DX → ADX.
// Başlıktaki canlı değer son ADX'i döndürür; seri çizilmez.
function calcADXLatest(bars: Bar[], period = 14): number | null {
    if (bars.length < period * 2 + 1) return null;
    const trs: number[] = [], plusDM: number[] = [], minusDM: number[] = [];
    for (let i = 1; i < bars.length; i++) {
        const up = bars[i].high - bars[i - 1].high;
        const down = bars[i - 1].low - bars[i].low;
        plusDM.push(up > down && up > 0 ? up : 0);
        minusDM.push(down > up && down > 0 ? down : 0);
        trs.push(Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close)));
    }
    const dxOf = (tr: number, pdm: number, mdm: number) => {
        const pdi = tr > 0 ? (100 * pdm) / tr : 0;
        const mdi = tr > 0 ? (100 * mdm) / tr : 0;
        const sum = pdi + mdi;
        return sum > 0 ? (100 * Math.abs(pdi - mdi)) / sum : 0;
    };
    let tr = 0, pdm = 0, mdm = 0;
    for (let i = 0; i < period; i++) { tr += trs[i]; pdm += plusDM[i]; mdm += minusDM[i]; }
    const dxs: number[] = [dxOf(tr, pdm, mdm)];
    for (let i = period; i < trs.length; i++) {
        tr = tr - tr / period + trs[i];
        pdm = pdm - pdm / period + plusDM[i];
        mdm = mdm - mdm / period + minusDM[i];
        dxs.push(dxOf(tr, pdm, mdm));
    }
    if (dxs.length < period) return null;
    let adx = 0;
    for (let i = 0; i < period; i++) adx += dxs[i];
    adx /= period;
    for (let i = period; i < dxs.length; i++) adx = (adx * (period - 1) + dxs[i]) / period;
    return adx;
}

function calcMACD(bars: Bar[], fast = 12, slow = 26, signal = 9) {
    if (bars.length < slow + signal) return { macd: [] as Point[], signal: [] as Point[], histogram: [] as (Point & { color: string })[] };
    const fEma = calcEMA(bars, fast), sEma = calcEMA(bars, slow);
    const fMap = new Map(fEma.map(f => [f.time, f.value]));
    const macdLine: Bar[] = sEma.map(s => {
        const fv = fMap.get(s.time);
        return { time: s.time, open: 0, high: 0, low: 0, close: fv != null ? fv - s.value : 0, volume: 0 };
    }).filter(b => fMap.has(b.time as any));
    const sigLine = calcEMA(macdLine, signal);
    const sigMap = new Map(sigLine.map(s => [s.time, s.value]));
    const macd: Point[] = [], sig: Point[] = [], hist: (Point & { color: string })[] = [];
    for (const m of macdLine) {
        const sv = sigMap.get(m.time as UTCTimestamp);
        if (sv != null) {
            const h = m.close - sv;
            const t = m.time as UTCTimestamp;
            macd.push({ time: t, value: m.close });
            sig.push({ time: t, value: sv });
            hist.push({ time: t, value: h, color: h >= 0 ? "rgba(16,185,129,0.85)" : "rgba(239,68,68,0.85)" });
        }
    }
    return { macd, signal: sig, histogram: hist };
}

function calcVWAP(bars: Bar[]): Point[] {
    let cumPV = 0, cumV = 0;
    return bars.map(b => {
        const tp = (b.high + b.low + b.close) / 3;
        cumPV += tp * b.volume;
        cumV += b.volume;
        return { time: b.time as UTCTimestamp, value: cumV === 0 ? tp : cumPV / cumV };
    });
}

function calcStochastic(bars: Bar[], kPeriod = 14, dPeriod = 3): { k: Point[]; d: Point[] } {
    const k: Point[] = [];
    for (let i = kPeriod - 1; i < bars.length; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = 0; j < kPeriod; j++) { hi = Math.max(hi, bars[i - j].high); lo = Math.min(lo, bars[i - j].low); }
        k.push({ time: bars[i].time as UTCTimestamp, value: hi === lo ? 50 : ((bars[i].close - lo) / (hi - lo)) * 100 });
    }
    const d: Point[] = [];
    for (let i = dPeriod - 1; i < k.length; i++) {
        let sum = 0;
        for (let j = 0; j < dPeriod; j++) sum += k[i - j].value;
        d.push({ time: k[i].time, value: sum / dPeriod });
    }
    return { k, d };
}

function calcWilliamsR(bars: Bar[], period = 14): Point[] {
    const result: Point[] = [];
    for (let i = period - 1; i < bars.length; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = 0; j < period; j++) { hi = Math.max(hi, bars[i - j].high); lo = Math.min(lo, bars[i - j].low); }
        result.push({ time: bars[i].time as UTCTimestamp, value: hi === lo ? -50 : ((hi - bars[i].close) / (hi - lo)) * -100 });
    }
    return result;
}

function calcCCI(bars: Bar[], period = 20): Point[] {
    const result: Point[] = [];
    for (let i = period - 1; i < bars.length; i++) {
        const tps = bars.slice(i - period + 1, i + 1).map(b => (b.high + b.low + b.close) / 3);
        const sma = tps.reduce((a, b) => a + b, 0) / period;
        const md = tps.reduce((a, b) => a + Math.abs(b - sma), 0) / period;
        result.push({ time: bars[i].time as UTCTimestamp, value: md === 0 ? 0 : (tps[tps.length - 1] - sma) / (0.015 * md) });
    }
    return result;
}

function calcATR(bars: Bar[], period = 14): Point[] {
    if (bars.length < period + 1) return [];
    const trs: number[] = [bars[0].high - bars[0].low];
    for (let i = 1; i < bars.length; i++) {
        const tr = Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close));
        trs.push(tr);
    }
    let atr = trs.slice(0, period).reduce((a, b) => a + b, 0) / period;
    const result: Point[] = [{ time: bars[period - 1].time as UTCTimestamp, value: atr }];
    for (let i = period; i < bars.length; i++) {
        atr = (atr * (period - 1) + trs[i]) / period;
        result.push({ time: bars[i].time as UTCTimestamp, value: atr });
    }
    return result;
}

function calcOBV(bars: Bar[]): Point[] {
    let obv = 0;
    return bars.map((b, i) => {
        if (i > 0) obv += b.close > bars[i - 1].close ? b.volume : b.close < bars[i - 1].close ? -b.volume : 0;
        return { time: b.time as UTCTimestamp, value: obv };
    });
}

function calcMFI(bars: Bar[], period = 14): Point[] {
    if (bars.length <= period) return [];
    const tps = bars.map(b => (b.high + b.low + b.close) / 3);
    const result: Point[] = [];
    for (let i = period; i < bars.length; i++) {
        let posFlow = 0, negFlow = 0;
        for (let j = i - period + 1; j <= i; j++) {
            const mf = tps[j] * bars[j].volume;
            if (tps[j] > tps[j - 1]) posFlow += mf; else negFlow += mf;
        }
        result.push({ time: bars[i].time as UTCTimestamp, value: negFlow === 0 ? 100 : 100 - 100 / (1 + posFlow / negFlow) });
    }
    return result;
}

function calcSupertrend(bars: Bar[], period = 10, mult = 3) {
    const atrList = calcATR(bars, period);
    if (!atrList.length) return { up: [] as Point[], dn: [] as Point[], trend: [] as (Point & { color: string })[] };
    const startIdx = bars.length - atrList.length;
    const up: Point[] = [], dn: Point[] = [], trend: (Point & { color: string })[] = [];
    let prevUp = 0, prevDn = 0, direction = 1;
    for (let i = 0; i < atrList.length; i++) {
        const bi = startIdx + i;
        const atr = atrList[i].value;
        const hl2 = (bars[bi].high + bars[bi].low) / 2;
        const basicUp = hl2 - mult * atr;
        const basicDn = hl2 + mult * atr;
        const finalUp = i === 0 ? basicUp : (basicUp > prevUp || bars[bi - 1].close < prevUp ? basicUp : prevUp);
        const finalDn = i === 0 ? basicDn : (basicDn < prevDn || bars[bi - 1].close > prevDn ? basicDn : prevDn);
        const close = bars[bi].close;
        if (direction === 1 && close < finalUp) direction = -1;
        else if (direction === -1 && close > finalDn) direction = 1;
        up.push({ time: bars[bi].time as UTCTimestamp, value: finalUp });
        dn.push({ time: bars[bi].time as UTCTimestamp, value: finalDn });
        trend.push({ time: bars[bi].time as UTCTimestamp, value: direction === 1 ? finalUp : finalDn, color: direction === 1 ? "#10b981" : "#ef4444" });
        prevUp = finalUp;
        prevDn = finalDn;
    }
    return { up, dn, trend };
}

// ─── Countdown subcomponent ───────────────────────────────────────────────────

function CardCandleCountdown({ intervalMs }: { intervalMs: number }) {
    const [rem, setRem] = useState(0);
    useEffect(() => {
        const ms = intervalMs > 0 ? intervalMs : 60_000;
        const tick = () => setRem(Math.max(0, Math.ceil(Date.now() / ms) * ms - Date.now()));
        tick();
        const t = setInterval(tick, 250);
        return () => clearInterval(t);
    }, [intervalMs]);
    const m = Math.floor(rem / 60000), s = Math.floor((rem % 60000) / 1000);
    return <span className="font-mono text-[11px] text-neon-green/90 font-semibold tabular-nums" title="Mum Kapanış Sayacı">⏱ {String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}</span>;
}

// ─── Indicator Groups for UI ──────────────────────────────────────────────────

interface IndicatorDef {
    key: keyof ChartIndicators;
    label: string;
    color: string;
    dotColor: string;
    category: string;
    overlay: boolean;
}

const INDICATOR_DEFS: IndicatorDef[] = [
    // EMAs
    { key: "ema9",       label: "EMA 9 (Kısa)",      color: "text-blue-400",   dotColor: "bg-blue-500",   category: "EMA Ribbon", overlay: true  },
    { key: "ema21",      label: "EMA 21 (Orta)",      color: "text-emerald-400",dotColor: "bg-emerald-500",category: "EMA Ribbon", overlay: true  },
    { key: "ema50",      label: "EMA 50 (Trend)",     color: "text-amber-400",  dotColor: "bg-amber-500",  category: "EMA Ribbon", overlay: true  },
    { key: "ema200",     label: "EMA 200 (Ana Trend)",color: "text-purple-400", dotColor: "bg-purple-500", category: "EMA Ribbon", overlay: true  },
    // Bands
    { key: "bollinger",  label: "Bollinger Bantları (BB 20)",color: "text-indigo-400",dotColor: "bg-indigo-500",category: "Bantlar", overlay: true  },
    { key: "supertrend", label: "Supertrend (10,3)",  color: "text-pink-400",   dotColor: "bg-pink-500",   category: "Bantlar", overlay: true  },
    // Volume-based
    { key: "volume",     label: "Hacim (Volume)",     color: "text-gray-300",   dotColor: "bg-gray-500",   category: "Hacim", overlay: false },
    { key: "vwap",       label: "VWAP (Kümülatif)",   color: "text-yellow-400", dotColor: "bg-yellow-500", category: "Hacim", overlay: true  },
    { key: "obv",        label: "OBV (On Balance Vol)",color: "text-teal-400",  dotColor: "bg-teal-500",   category: "Hacim", overlay: false },
    { key: "mfi",        label: "MFI (Para Akışı, 14)",color: "text-lime-400", dotColor: "bg-lime-500",    category: "Hacim", overlay: false },
    // Oscillators
    { key: "rsi",        label: "RSI (14)",            color: "text-cyan-400",   dotColor: "bg-cyan-500",   category: "Osilatörler", overlay: false },
    { key: "macd",       label: "MACD (12,26,9)",      color: "text-orange-400", dotColor: "bg-orange-500", category: "Osilatörler", overlay: false },
    { key: "stochastic", label: "Stochastic (14,3)",   color: "text-red-400",    dotColor: "bg-red-500",    category: "Osilatörler", overlay: false },
    { key: "williamsR",  label: "Williams %R (14)",    color: "text-violet-400", dotColor: "bg-violet-500", category: "Osilatörler", overlay: false },
    { key: "cci",        label: "CCI (Emtia Kanalı, 20)",color: "text-rose-400",dotColor: "bg-rose-500",  category: "Osilatörler", overlay: false },
    // Trend
    { key: "atr",        label: "ATR (Volatilite, 14)",color: "text-fuchsia-400",dotColor: "bg-fuchsia-500",category: "Trend & Volatilite", overlay: false },
];

// ─── Main Component ───────────────────────────────────────────────────────────

export default function MultiChartCard({ config, availableSymbols, isMaximized, onToggleMaximize, onUpdateConfig }: MultiChartCardProps) {
    const cardRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const seriesMapRef = useRef<Map<string, ISeriesApi<any>>>(new Map());
    const [loading, setLoading] = useState(true);
    const [symbolSearchOpen, setSymbolSearchOpen] = useState(false);
    const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
    const [searchFilter, setSearchFilter] = useState("");
    const [indicatorCat, setIndicatorCat] = useState<string>("Tümü");
    const [priceData, setPriceData] = useState<{ last: number; changePct: number } | null>(null);
    // Seçili TF'nin son mumlarından hesaplanan canlı momentum değerleri.
    const [momentum, setMomentum] = useState<{ rsi14: number | null; adx14: number | null } | null>(null);
    const [hoverLegend, setHoverLegend] = useState<{ open: number; high: number; low: number; close: number } | null>(null);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [isDark, setIsDark] = useState(true); // dark varsayılan
    const klineReqIdRef = useRef(0);
    const lastBarsRef = useRef<Bar[]>([]);

    // Fullscreen API handler
    const toggleFullscreen = useCallback(() => {
        if (!cardRef.current) return;
        if (!document.fullscreenElement) {
            cardRef.current.requestFullscreen().catch(err => console.warn("Fullscreen hata:", err));
        } else {
            document.exitFullscreen();
        }
    }, []);

    useEffect(() => {
        const handler = () => setIsFullscreen(!!document.fullscreenElement);
        document.addEventListener("fullscreenchange", handler);
        return () => document.removeEventListener("fullscreenchange", handler);
    }, []);

    // Tema değişikliği
    useEffect(() => {
        if (!chartRef.current) return;
        chartRef.current.applyOptions({
            layout: {
                background: { type: ColorType.Solid, color: isDark ? "#06080d" : "#ffffff" },
                textColor: isDark ? "#9ca3af" : "#374151",
            },
            grid: {
                vertLines: { color: isDark ? "rgba(31,41,55,0.4)" : "rgba(229,231,235,0.8)" },
                horzLines: { color: isDark ? "rgba(31,41,55,0.4)" : "rgba(229,231,235,0.8)" },
            },
        });
    }, [isDark]);

    const filteredSymbols = availableSymbols.filter(s => s.toLowerCase().includes(searchFilter.toLowerCase().trim()));

    // ── Chart init ────────────────────────────────────────────────────────────
    useEffect(() => {
        if (!containerRef.current) return;
        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 280,
            layout: { background: { type: ColorType.Solid, color: "#06080d" }, textColor: "#9ca3af", fontFamily: "JetBrains Mono, monospace", fontSize: 11 },
            grid: { vertLines: { color: "rgba(31,41,55,0.4)" }, horzLines: { color: "rgba(31,41,55,0.4)" } },
            crosshair: { mode: 0, vertLine: { color: "#10b981", width: 1, style: LineStyle.Dashed }, horzLine: { color: "#10b981", width: 1, style: LineStyle.Dashed } },
            timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1f2937" },
            rightPriceScale: { borderColor: "#1f2937", scaleMargins: { top: 0.1, bottom: 0.15 } },
            handleScroll: { vertTouchDrag: false, horzTouchDrag: true, mouseWheel: true, pressedMouseMove: true },
        });
        const candleSeries = chart.addSeries(CandlestickSeries, { upColor: "#10b981", downColor: "#ef4444", borderVisible: false, wickUpColor: "#10b981", wickDownColor: "#ef4444" });
        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;
        chart.subscribeCrosshairMove((param) => {
            if (!param.time || !param.seriesData || !candleSeriesRef.current) { setHoverLegend(null); return; }
            const candle = param.seriesData.get(candleSeriesRef.current) as any;
            if (candle?.open !== undefined) setHoverLegend({ open: candle.open, high: candle.high, low: candle.low, close: candle.close });
            else setHoverLegend(null);
        });
        const ro = new ResizeObserver(() => {
            if (!chartRef.current || !containerRef.current) return;
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight });
        });
        ro.observe(containerRef.current);
        return () => { ro.disconnect(); chart.remove(); chartRef.current = null; candleSeriesRef.current = null; seriesMapRef.current.clear(); };
    }, []);

    // ── Fetch klines ──────────────────────────────────────────────────────────
    const fetchKlines = useCallback(async () => {
        if (!config.symbol) return;
        const reqId = ++klineReqIdRef.current;
        try {
            const res = await apiRequest(`${API_BASE}/api/market-klines/${config.symbol}?interval=${config.interval}&limit=300`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const payload = await res.json();
            if (reqId !== klineReqIdRef.current) return;
            const candlesRaw = payload.candles || [];
            if (!candlesRaw.length || !candleSeriesRef.current || !chartRef.current) return;
            const bars: Bar[] = candlesRaw.map((k: number[]) => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] }));
            lastBarsRef.current = bars;
            candleSeriesRef.current.setData(bars.map(b => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
            const last = bars[bars.length - 1];
            if (last) {
                const precision = pricePrecision(last.close);
                candleSeriesRef.current.applyOptions({ priceFormat: { type: "price", precision, minMove: 1 / Math.pow(10, precision) } });
                // changePct: son mumun açılış→kapanış değişimi (gerçek mum hareketi)
                const lastChangePct = last.open > 0 ? ((last.close - last.open) / last.open) * 100 : 0;
                // 24 saatlik değişim için ~288 mum (1m) veya ~96 mum (15m) geriye git
                const barsPerDay = Math.round(86_400_000 / (INTERVAL_MS[config.interval] || 60_000));
                const refIdx = Math.max(0, bars.length - 1 - barsPerDay);
                const refBar = bars[refIdx];
                const dayChangePct = refBar?.open > 0 ? ((last.close - refBar.open) / refBar.open) * 100 : lastChangePct;
                setPriceData({ last: last.close, changePct: dayChangePct });
            }
            // Başlık göstergeleri: seçili TF'nin son mumlarından RSI-14 / ADX-14.
            const rsiSeries = calcRSI(bars, 14);
            setMomentum({
                rsi14: rsiSeries.length ? rsiSeries[rsiSeries.length - 1].value : null,
                adx14: calcADXLatest(bars, 14),
            });
            rebuildIndicators(bars);
            setLoading(false);
        } catch (err) {
            console.error(`MultiChartCard [${config.symbol}] error:`, err);
            setLoading(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [config.symbol, config.interval]);

    // ── Rebuild indicators ────────────────────────────────────────────────────
    const rebuildIndicators = useCallback((bars: Bar[]) => {
        const chart = chartRef.current;
        if (!chart || !bars.length) return;
        seriesMapRef.current.forEach(s => { try { chart.removeSeries(s); } catch { } });
        seriesMapRef.current.clear();
        const ind = config.indicators;
        let subpane = 1;

        // ── Overlay: EMAs ────────────────────────────────────────────────────
        if (ind.ema9)   { const d = calcEMA(bars, 9);   if (d.length) { const s = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, title: "EMA9",   priceLineVisible: false }); s.setData(d); seriesMapRef.current.set("ema9", s); } }
        if (ind.ema21)  { const d = calcEMA(bars, 21);  if (d.length) { const s = chart.addSeries(LineSeries, { color: "#10b981", lineWidth: 1, title: "EMA21",  priceLineVisible: false }); s.setData(d); seriesMapRef.current.set("ema21", s); } }
        if (ind.ema50)  { const d = calcEMA(bars, 50);  if (d.length) { const s = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, title: "EMA50",  priceLineVisible: false }); s.setData(d); seriesMapRef.current.set("ema50", s); } }
        if (ind.ema200) { const d = calcEMA(bars, 200); if (d.length) { const s = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 2, title: "EMA200", priceLineVisible: false }); s.setData(d); seriesMapRef.current.set("ema200", s); } }

        // ── Overlay: Bollinger Bands ─────────────────────────────────────────
        if (ind.bollinger) {
            const bb = calcBollinger(bars);
            if (bb.middle.length) {
                const mid = chart.addSeries(LineSeries, { color: "rgba(99,102,241,0.7)", lineWidth: 1, lineStyle: LineStyle.Dotted, title: "BB Mid", priceLineVisible: false });
                const up  = chart.addSeries(LineSeries, { color: "rgba(99,102,241,0.9)", lineWidth: 1, title: "BB Up",  priceLineVisible: false });
                const low = chart.addSeries(LineSeries, { color: "rgba(99,102,241,0.9)", lineWidth: 1, title: "BB Low", priceLineVisible: false });
                mid.setData(bb.middle); up.setData(bb.upper); low.setData(bb.lower);
                seriesMapRef.current.set("bb_mid", mid); seriesMapRef.current.set("bb_up", up); seriesMapRef.current.set("bb_low", low);
            }
        }

        // ── Overlay: VWAP ────────────────────────────────────────────────────
        if (ind.vwap) {
            const d = calcVWAP(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#eab308", lineWidth: 2, lineStyle: LineStyle.Dashed, title: "VWAP", priceLineVisible: false });
                s.setData(d); seriesMapRef.current.set("vwap", s);
            }
        }

        // ── Overlay: Supertrend ──────────────────────────────────────────────
        if (ind.supertrend) {
            const st = calcSupertrend(bars);
            if (st.trend.length) {
                const s = chart.addSeries(LineSeries, { color: "#10b981", lineWidth: 2, title: "SuperTrend", priceLineVisible: false });
                s.setData(st.trend.map(p => ({ time: p.time, value: p.value })));
                seriesMapRef.current.set("supertrend", s);
            }
        }

        // ── Overlay: Volume (on vol scale) ───────────────────────────────────
        if (ind.volume) {
            const vs = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol_scale" });
            chart.priceScale("vol_scale").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
            vs.setData(bars.map(b => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "rgba(16,185,129,0.35)" : "rgba(239,68,68,0.35)" })));
            seriesMapRef.current.set("volume", vs);
        }

        // ── Subpane: RSI ─────────────────────────────────────────────────────
        if (ind.rsi) {
            const d = calcRSI(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, title: "RSI14", priceScaleId: "rsi_s" }, subpane);
                s.setData(d);
                chart.priceScale("rsi_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                s.createPriceLine({ price: 70, color: "rgba(239,68,68,0.5)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "70" });
                s.createPriceLine({ price: 30, color: "rgba(16,185,129,0.5)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "30" });
                seriesMapRef.current.set("rsi", s); subpane++;
            }
        }

        // ── Subpane: MACD ────────────────────────────────────────────────────
        if (ind.macd) {
            const { macd, signal: sig, histogram } = calcMACD(bars);
            if (macd.length) {
                const hist = chart.addSeries(HistogramSeries, { title: "MACD Hist", priceScaleId: "macd_s" }, subpane);
                hist.setData(histogram);
                const line = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, title: "MACD", priceScaleId: "macd_s", priceLineVisible: false }, subpane);
                line.setData(macd);
                const sigS = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, title: "Signal", priceScaleId: "macd_s", priceLineVisible: false }, subpane);
                sigS.setData(sig);
                chart.priceScale("macd_s", subpane).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.15 } });
                seriesMapRef.current.set("macd_hist", hist); seriesMapRef.current.set("macd_line", line); seriesMapRef.current.set("macd_sig", sigS); subpane++;
            }
        }

        // ── Subpane: Stochastic ──────────────────────────────────────────────
        if (ind.stochastic) {
            const { k, d } = calcStochastic(bars);
            if (k.length) {
                const sk = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, title: "Stoch %K", priceScaleId: "stoch_s" }, subpane);
                sk.setData(k);
                const sd = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, title: "Stoch %D", priceScaleId: "stoch_s", priceLineVisible: false }, subpane);
                sd.setData(d);
                chart.priceScale("stoch_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                sk.createPriceLine({ price: 80, color: "rgba(239,68,68,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "80" });
                sk.createPriceLine({ price: 20, color: "rgba(16,185,129,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "20" });
                seriesMapRef.current.set("stoch_k", sk); seriesMapRef.current.set("stoch_d", sd); subpane++;
            }
        }

        // ── Subpane: Williams %R ─────────────────────────────────────────────
        if (ind.williamsR) {
            const d = calcWilliamsR(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, title: "W%R", priceScaleId: "willr_s" }, subpane);
                s.setData(d);
                chart.priceScale("willr_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                s.createPriceLine({ price: -20, color: "rgba(239,68,68,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "-20" });
                s.createPriceLine({ price: -80, color: "rgba(16,185,129,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "-80" });
                seriesMapRef.current.set("willr", s); subpane++;
            }
        }

        // ── Subpane: CCI ─────────────────────────────────────────────────────
        if (ind.cci) {
            const d = calcCCI(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#f43f5e", lineWidth: 1, title: "CCI20", priceScaleId: "cci_s" }, subpane);
                s.setData(d);
                chart.priceScale("cci_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                s.createPriceLine({ price: 100, color: "rgba(239,68,68,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "+100" });
                s.createPriceLine({ price: -100, color: "rgba(16,185,129,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "-100" });
                seriesMapRef.current.set("cci", s); subpane++;
            }
        }

        // ── Subpane: ATR ─────────────────────────────────────────────────────
        if (ind.atr) {
            const d = calcATR(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#d946ef", lineWidth: 1, title: "ATR14", priceScaleId: "atr_s" }, subpane);
                s.setData(d);
                chart.priceScale("atr_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                seriesMapRef.current.set("atr", s); subpane++;
            }
        }

        // ── Subpane: OBV ─────────────────────────────────────────────────────
        if (ind.obv) {
            const d = calcOBV(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#14b8a6", lineWidth: 1, title: "OBV", priceScaleId: "obv_s" }, subpane);
                s.setData(d);
                chart.priceScale("obv_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                seriesMapRef.current.set("obv", s); subpane++;
            }
        }

        // ── Subpane: MFI ─────────────────────────────────────────────────────
        if (ind.mfi) {
            const d = calcMFI(bars);
            if (d.length) {
                const s = chart.addSeries(LineSeries, { color: "#84cc16", lineWidth: 1, title: "MFI14", priceScaleId: "mfi_s" }, subpane);
                s.setData(d);
                chart.priceScale("mfi_s", subpane).applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
                s.createPriceLine({ price: 80, color: "rgba(239,68,68,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "80" });
                s.createPriceLine({ price: 20, color: "rgba(16,185,129,0.4)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "20" });
                seriesMapRef.current.set("mfi", s); subpane++;
            }
        }
    }, [config.indicators]);

    useEffect(() => { setLoading(true); fetchKlines().then(() => chartRef.current?.timeScale().fitContent()); }, [fetchKlines]);
    useEffect(() => { if (lastBarsRef.current.length > 0) rebuildIndicators(lastBarsRef.current); }, [config.indicators, rebuildIndicators]);
    useEffect(() => { const iv = setInterval(() => { if (typeof document !== "undefined" && document.hidden) return; fetchKlines(); }, 6000); return () => clearInterval(iv); }, [fetchKlines]);

    const activeCount = Object.values(config.indicators).filter(Boolean).length;
    const intervalMs = INTERVAL_MS[config.interval] || 60_000;

    // Indicator categories for grouped menu
    const cats = ["Tümü", ...Array.from(new Set(INDICATOR_DEFS.map(d => d.category)))];
    const visibleDefs = indicatorCat === "Tümü" ? INDICATOR_DEFS : INDICATOR_DEFS.filter(d => d.category === indicatorCat);

    const handleSelectSymbol = (raw: string) => {
        let clean = raw.trim().toUpperCase();
        if (!clean) return;
        if (!clean.endsWith("TRY") && availableSymbols.includes(clean + "TRY")) {
            clean = clean + "TRY";
        }
        onUpdateConfig({ symbol: clean });
        setSymbolSearchOpen(false);
        setSearchFilter("");
    };

    return (
        <div
            ref={cardRef}
            className={`flex flex-col border border-bunker-800 rounded-xl overflow-hidden shadow-lg transition-all ${
                isDark ? "bg-bunker-950" : "bg-white"
            } ${isMaximized ? "col-span-full row-span-full h-full" : "h-full min-h-[300px]"} ${
                isFullscreen ? "fixed inset-0 z-[9999] rounded-none border-none" : ""
            }`}
        >
            {/* ── Header ─────────────────────────────────────────────────────── */}
            <div className={`flex flex-wrap items-center justify-between gap-1.5 px-3 py-2 border-b shrink-0 text-xs ${isDark ? "bg-bunker-900/90 border-bunker-800" : "bg-gray-50 border-gray-200"}`}>
                {/* Left: ID + Symbol */}
                <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-neon-green/15 text-neon-green border border-neon-green/30 shrink-0">#{config.id}</span>
                    <div className="relative">
                        <button type="button" onClick={() => { setSymbolSearchOpen(v => !v); setIndicatorMenuOpen(false); }}
                            className="flex items-center gap-1 px-2 py-1 rounded-md bg-bunker-800/80 hover:bg-bunker-700/80 border border-bunker-700 text-white font-mono font-bold text-xs transition-colors">
                            {config.symbol} <span className="text-[9px] text-bunker-muted">▼</span>
                        </button>
                        {symbolSearchOpen && (
                            <div className="absolute left-0 top-full mt-1.5 z-50 w-64 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-2.5">
                                <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-bunker-800">
                                    <span className="font-mono text-[11px] font-bold text-white">Sembol Seç ({availableSymbols.length})</span>
                                    <button type="button" onClick={() => setSymbolSearchOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
                                </div>
                                <input
                                    autoFocus
                                    type="text"
                                    value={searchFilter}
                                    onChange={e => setSearchFilter(e.target.value)}
                                    onKeyDown={e => {
                                        if (e.key === "Enter") {
                                            e.preventDefault();
                                            if (filteredSymbols.length > 0) {
                                                handleSelectSymbol(filteredSymbols[0]);
                                            } else if (searchFilter.trim()) {
                                                handleSelectSymbol(searchFilter);
                                            }
                                        }
                                    }}
                                    placeholder="Ara (örn. SAGA)..."
                                    className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-xs text-white placeholder-bunker-500 focus:border-neon-green/50 outline-none mb-2"
                                />
                                {searchFilter.trim() && (
                                    <button
                                        type="button"
                                        onClick={() => handleSelectSymbol(searchFilter)}
                                        className="w-full text-left px-2 py-1 mb-2 rounded text-[11px] font-mono bg-neon-green/15 text-neon-green hover:bg-neon-green/25 font-bold border border-neon-green/30 transition-colors"
                                    >
                                        ⚡ {(() => {
                                            const up = searchFilter.trim().toUpperCase();
                                            return !up.endsWith("TRY") && availableSymbols.includes(up + "TRY") ? up + "TRY" : up;
                                        })()} Aç
                                    </button>
                                )}
                                <div className="flex flex-wrap gap-1 mb-2">
                                    {["BTCTRY","ETHTRY","SOLTRY","AVAXTRY","PEPETRY","XRPTRY"].map(s => (
                                        <button key={s} type="button" onClick={() => handleSelectSymbol(s)}
                                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono border transition-colors ${config.symbol === s ? "bg-neon-green/20 border-neon-green/50 text-neon-green font-bold" : "bg-bunker-800/60 border-bunker-700 text-bunker-muted hover:text-white"}`}>
                                            {s.replace("TRY","")}
                                        </button>
                                    ))}
                                </div>
                                <div className="max-h-56 overflow-y-auto space-y-0.5">
                                    {filteredSymbols.slice(0, 50).map(s => (
                                        <button key={s} type="button" onClick={() => handleSelectSymbol(s)}
                                            className={`w-full text-left px-2.5 py-1.5 rounded font-mono text-xs flex items-center justify-between transition-colors ${config.symbol === s ? "bg-neon-green/15 text-neon-green font-bold" : "text-bunker-muted hover:bg-bunker-800 hover:text-white"}`}>
                                            <span>{s}</span>{config.symbol === s && <span>✓</span>}
                                        </button>
                                    ))}
                                    {!filteredSymbols.length && <p className="text-center text-[11px] text-bunker-muted py-3 font-mono">Sonuç bulunamadı</p>}
                                </div>
                            </div>
                        )}
                    </div>
                    {priceData && (
                        <div className="flex items-center gap-1.5 font-mono">
                            <span className="text-white font-bold text-xs">₺{formatPrice(priceData.last)}</span>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${priceData.changePct >= 0 ? "bg-neon-green/15 text-neon-green border border-neon-green/30" : "bg-neon-red/15 text-neon-red border border-neon-red/30"}`}>
                                {priceData.changePct >= 0 ? "+" : ""}{priceData.changePct.toFixed(2)}%
                            </span>
                        </div>
                    )}
                </div>

                {/* Center: TF Selector */}
                <div className="flex items-center gap-0.5 bg-bunker-950/80 p-0.5 rounded-lg border border-bunker-800">
                    {INTERVALS.map(int => (
                        <button key={int.v} type="button" onClick={() => onUpdateConfig({ interval: int.v })}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium transition-colors ${config.interval === int.v ? "bg-neon-green text-bunker-950 font-bold" : "text-bunker-muted hover:text-white hover:bg-bunker-800/60"}`}>
                            {int.l}
                        </button>
                    ))}
                </div>

                {/* Right: Indicator Picker + Controls */}
                <div className="flex items-center gap-2">
                    <CardCandleCountdown intervalMs={intervalMs} />

                    {/* Indicator dropdown */}
                    <div className="relative">
                        <button type="button" onClick={() => { setIndicatorMenuOpen(v => !v); setSymbolSearchOpen(false); }}
                            className={`flex items-center gap-1 px-2 py-1 rounded-md border font-mono text-[11px] transition-colors ${activeCount > 0 ? "bg-neon-green/10 border-neon-green/40 text-neon-green font-bold" : "bg-bunker-800/60 border-bunker-700 text-bunker-muted hover:text-white"}`}>
                            <span className="hidden sm:inline">fx İndikatör</span><span className="sm:hidden">fx</span>
                            <span className="bg-bunker-700 text-white font-bold rounded-full w-4 h-4 text-[9px] flex items-center justify-center">{activeCount}</span>
                            <span className="text-[9px]">▼</span>
                        </button>

                        {indicatorMenuOpen && (
                            <div className="absolute right-0 top-full mt-1.5 z-50 w-72 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-2.5">
                                <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-bunker-800">
                                    <span className="font-mono text-[11px] font-bold text-white">İndikatörler ({activeCount} aktif)</span>
                                    <button type="button" onClick={() => setIndicatorMenuOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
                                </div>
                                {/* Category Tabs */}
                                <div className="flex flex-wrap gap-1 mb-2.5">
                                    {cats.map(c => (
                                        <button key={c} type="button" onClick={() => setIndicatorCat(c)}
                                            className={`px-2 py-0.5 rounded-full text-[10px] font-mono border transition-colors ${indicatorCat === c ? "bg-neon-green/20 border-neon-green/50 text-neon-green font-bold" : "border-bunker-700 text-bunker-muted hover:text-white"}`}>
                                            {c}
                                        </button>
                                    ))}
                                </div>
                                <div className="space-y-0.5 max-h-72 overflow-y-auto">
                                    {visibleDefs.map(def => (
                                        <label key={def.key} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-bunker-800/60 cursor-pointer group">
                                            <span className={`flex items-center gap-1.5 font-mono text-[11px] ${def.color}`}>
                                                <span className={`w-2 h-2 rounded-full ${def.dotColor} inline-block shrink-0`} />
                                                <span>{def.label}</span>
                                                <span className={`text-[9px] px-1 py-0.5 rounded border ${def.overlay ? "border-yellow-500/30 text-yellow-400" : "border-green-500/30 text-green-400"}`}>
                                                    {def.overlay ? "GRAFİK" : "PANE"}
                                                </span>
                                            </span>
                                            <input type="checkbox" checked={config.indicators[def.key]} onChange={e => onUpdateConfig({ indicators: { ...config.indicators, [def.key]: e.target.checked } })}
                                                className="rounded border-bunker-700 bg-bunker-950 text-neon-green focus:ring-0 shrink-0" />
                                        </label>
                                    ))}
                                </div>
                                {/* Quick Presets */}
                                <div className="mt-2 pt-2 border-t border-bunker-800 flex flex-wrap gap-1.5">
                                    <button type="button" onClick={() => onUpdateConfig({ indicators: { ...Object.fromEntries(Object.keys(config.indicators).map(k => [k, false])) as any, ema9: true, ema21: true, volume: true } })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors">Temel</button>
                                    <button type="button" onClick={() => onUpdateConfig({ indicators: { ...Object.fromEntries(Object.keys(config.indicators).map(k => [k, false])) as any, ema9: true, ema21: true, ema50: true, bollinger: true, rsi: true, volume: true } })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors">Orta</button>
                                    <button type="button" onClick={() => onUpdateConfig({ indicators: { ema9: true, ema21: true, ema50: true, ema200: true, bollinger: true, vwap: true, volume: true, rsi: true, macd: true, stochastic: false, williamsR: false, cci: false, atr: false, supertrend: false, obv: false, mfi: false } })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors">Pro</button>
                                    <button type="button" onClick={() => onUpdateConfig({ indicators: Object.fromEntries(Object.keys(config.indicators).map(k => [k, false])) as any })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-neon-red/10 hover:bg-neon-red/20 border border-neon-red/30 text-neon-red transition-colors">Temizle</button>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Yenile */}
                    <button
                        type="button"
                        onClick={() => { setLoading(true); fetchKlines(); }}
                        className="p-1 rounded text-bunker-muted hover:text-white hover:bg-bunker-800 transition-colors"
                        title="Yenile"
                    >↻</button>

                    {/* Tema Toggle */}
                    <button
                        type="button"
                        onClick={() => setIsDark(d => !d)}
                        className={`p-1 rounded text-xs transition-colors ${isDark ? "text-bunker-muted hover:text-yellow-400 hover:bg-bunker-800" : "text-yellow-500 bg-yellow-50 border border-yellow-200"}`}
                        title={isDark ? "Aydınlık Temaya Geç" : "Karanlık Temaya Geç"}
                    >
                        {isDark ? "☀️" : "🌙"}
                    </button>

                    {/* Kart Büyüt */}
                    <button
                        type="button"
                        onClick={onToggleMaximize}
                        className={`p-1 rounded text-xs transition-colors ${isMaximized ? "bg-neon-green text-bunker-950 font-bold" : "text-bunker-muted hover:text-white hover:bg-bunker-800"}`}
                        title={isMaximized ? "Küçült" : "Kartı Büyüt"}
                    >
                        {isMaximized ? "🗗" : "⛶"}
                    </button>

                    {/* Tam Ekran (Fullscreen API) */}
                    <button
                        type="button"
                        onClick={toggleFullscreen}
                        className={`p-1 rounded text-xs transition-colors ${isFullscreen ? "bg-neon-green/20 text-neon-green border border-neon-green/40 font-bold" : "text-bunker-muted hover:text-white hover:bg-bunker-800"}`}
                        title={isFullscreen ? "Tam Ekrandan Çık (Esc)" : "Tam Ekran"}
                    >
                        {isFullscreen ? "⊠" : "⊡"}
                    </button>
                </div>
            </div>

            {/* ── Chart Area ─────────────────────────────────────────────────── */}
            <div className="relative flex-1 w-full min-h-[200px] overflow-hidden">
                <div className="absolute top-2 left-3 z-10 pointer-events-none flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-bunker-muted bg-bunker-950/70 px-2 py-1 rounded border border-bunker-800/50">
                    <span className="text-white font-bold">{config.symbol}</span>
                    <span className="text-bunker-400">{config.interval.toUpperCase()}</span>
                    {hoverLegend ? (<>
                        <span>A: <strong className="text-white">{formatPrice(hoverLegend.open)}</strong></span>
                        <span>Y: <strong className="text-neon-green">{formatPrice(hoverLegend.high)}</strong></span>
                        <span>D: <strong className="text-neon-red">{formatPrice(hoverLegend.low)}</strong></span>
                        <span>K: <strong className="text-white">{formatPrice(hoverLegend.close)}</strong></span>
                    </>) : (<>
                        {priceData && <span>Son: <strong className="text-white">{formatPrice(priceData.last)}</strong></span>}
                        {/* RSI-14 / ADX-14: seçili TF'nin son mumlarından, her veri tazelemesinde güncellenir */}
                        {momentum?.rsi14 != null && (
                            <span>RSI-14: <strong className={momentum.rsi14 >= 50 ? "text-neon-green" : "text-neon-red"}>{momentum.rsi14.toFixed(1)}</strong></span>
                        )}
                        {momentum?.adx14 != null && (
                            <span>ADX-14: <strong className={momentum.adx14 >= 25 ? "text-neon-green" : momentum.adx14 >= 20 ? "text-yellow-300" : "text-bunker-muted"}>{momentum.adx14.toFixed(1)}</strong></span>
                        )}
                    </>)}
                </div>
                <div ref={containerRef} className="w-full h-full" />
                {loading && (
                    <div className="absolute inset-0 bg-bunker-950/60 backdrop-blur-sm flex items-center justify-center pointer-events-none">
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-bunker-900 border border-bunker-700 text-white font-mono text-xs">
                            <span className="w-2 h-2 rounded-full bg-neon-green animate-ping" />Mumlar Yükleniyor...
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
