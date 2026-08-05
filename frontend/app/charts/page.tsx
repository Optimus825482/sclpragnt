"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import {
    createChart, createSeriesMarkers, CandlestickSeries, LineSeries, HistogramSeries,
    IChartApi, ISeriesApi, IPriceLine, UTCTimestamp, Time
} from "lightweight-charts";
import IndicatorPicker, { findIndicatorEntry } from "./IndicatorPicker";
import IndicatorSettings from "./IndicatorSettings";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "./types";

const FALLBACK_SYMBOLS = ["BTCTRY", "ETHTRY", "SOLTRY"];
const INTERVALS = [
    { v: "1m", l: "1M" }, { v: "5m", l: "5M" }, { v: "15m", l: "15M" },
    { v: "30m", l: "M30" }, { v: "1h", l: "1H" }, { v: "4h", l: "4H" }, { v: "1d", l: "D1" }
];
const INTERVAL_MS: Record<string, number> = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000
};
const PALETTE = ["#10b981", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4", "#84cc16", "#f97316"];
const PANE_H = 160;
// sabit canvas yüksekliği: pane aç/kapa toplam yüksekliği değiştirmez, paneller kalanı paylaşır
const TOTAL_HEIGHT = 600;
const MAIN_MIN = 240;
const PANE_MIN = 56;
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

const LS_SYMBOL = "scalper_chart_symbol";
const LS_INTERVAL = "scalper_chart_interval";
const LS_INDICATORS = "scalper_chart_indicators";
const LS_PANE_HEIGHTS = "scalper_chart_pane_heights";
const API = `${API_BASE}/api/chart`;

type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };

type PatternMarker = { time: number; type: "buy" | "sell"; text: string };
const patternDescriptions: Record<string, string> = {
    "BOĞA SARMA": "Düşüş sonrası gelen güçlü boğa mumu, önceki ayı mumunun gövdesini tamamen sarar.",
    "AYI SARMA": "Yükseliş sonrası gelen güçlü ayı mumu, önceki boğa mumunun gövdesini tamamen sarar.",
    "ÇEKİÇ": "Uzun alt fitil ve küçük gövde, aşağı yönlü baskının reddedildiğini gösterir.",
    "TERS ÇEKİÇ": "Uzun üst fitil, yükseliş denemesini ve kararsızlığı gösterir.",
    "DOJİ": "Açılış ve kapanışın birbirine yakın olması piyasa kararsızlığına işaret eder.",
    "ÜÇ BEYAZ ASKER": "Ardışık güçlü boğa mumları kısa vadeli alım baskısını gösterir.",
    "ÜÇ SİYAH KARGA": "Ardışık güçlü ayı mumları kısa vadeli satış baskısını gösterir."
};
const strongCandlestickPatterns = (bars: Bar[]): PatternMarker[] => {
    const out: PatternMarker[] = [];
    for (let i = 1; i < bars.length; i++) {
        const p = bars[i - 1], c = bars[i];
        const pBull = p.close > p.open, cBull = c.close > c.open;
        const pBody = Math.abs(p.close - p.open), cBody = Math.abs(c.close - c.open);
        const pRange = Math.max(p.high - p.low, Number.EPSILON), cRange = Math.max(c.high - c.low, Number.EPSILON);
        const pTop = p.high - Math.max(p.open, p.close), pBottom = Math.min(p.open, p.close) - p.low;
        const cTop = c.high - Math.max(c.open, c.close), cBottom = Math.min(c.open, c.close) - c.low;
        if (!pBull && cBull && c.open <= p.close && c.close >= p.open && cBody >= pBody * .8) out.push({ time: c.time, type: "buy", text: "BOĞA SARMA" });
        else if (pBull && !cBull && c.open >= p.close && c.close <= p.open && cBody >= pBody * .8) out.push({ time: c.time, type: "sell", text: "AYI SARMA" });
        else if (cBottom >= cBody * 2 && cTop <= cBody * .6 && c.close >= c.open) out.push({ time: c.time, type: "buy", text: "ÇEKİÇ" });
        else if (cTop >= cBody * 2 && cBottom <= cBody * .6 && c.close <= c.open) out.push({ time: c.time, type: "sell", text: "TERS ÇEKİÇ" });
        else if (cBody <= cRange * .1 && Math.abs(c.close - p.close) <= pRange * .12) out.push({ time: c.time, type: "buy", text: "DOJİ" });
        else if (i >= 2 && cBull && bars[i - 2].close > bars[i - 2].open && pBull && c.close > p.close) out.push({ time: c.time, type: "buy", text: "ÜÇ BEYAZ ASKER" });
        else if (i >= 2 && !cBull && bars[i - 2].close < bars[i - 2].open && !pBull && c.close < p.close) out.push({ time: c.time, type: "sell", text: "ÜÇ SİYAH KARGA" });
    }
    return out.slice(-80);
};

const loadPersisted = <T,>(key: string, fallback: T): T => {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) as T : fallback;
    } catch {
        return fallback;
    }
};

const DEFAULT_STYLE: IndicatorStyle = {
    colors: ["#10b981", "#3b82f6", "#f59e0b", "#a855f7"],
    lineWidth: 2,
    showPriceLine: true,
    showBounds: true,
    minValue: null,
    maxValue: null
};

const DEFAULT_INSTANCES: IndicatorInstance[] = [
    { uid: uid(), registryId: "bb", name: "BB", overlay: true, params: { length: 20, mult: 2, src: "close" }, style: DEFAULT_STYLE }
];

type EditTarget = { entry: RegistryEntry; editUid?: string };

const loadIndicators = (): IndicatorInstance[] => {
    const raw = loadPersisted<IndicatorInstance[]>(LS_INDICATORS, DEFAULT_INSTANCES);
    // eski format migrasyonu: style alanı yoksa varsayılan ekle
    return raw.map((i) => (i.style ? i : { ...i, style: DEFAULT_STYLE }));
};

// UT Bot sinyalleri: Pine Script'teki xATRTrailingStop + crossover mantığı
// Döner: { time, type: "buy"|"sell" }[] — marker olarak çizilir
const utBotSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    if (bars.length < 20) return [];
    const keyValue = params.keyValue ?? 1;
    const atrPeriod = Math.max(2, Math.round(params.atrPeriod ?? 11));
    const useHA = !!params.heikinAshi;

    // ATR hesapla (Wilder değil, basit ortalama — backend ile uyumlu)
    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const atr = (i: number): number => {
        if (i < atrPeriod) return 0;
        let sum = 0;
        for (let j = i - atrPeriod + 1; j <= i; j++) {
            const tr = Math.max(
                highs[j] - lows[j],
                Math.abs(highs[j] - closes[j - 1]),
                Math.abs(lows[j] - closes[j - 1])
            );
            sum += tr;
        }
        return sum / atrPeriod;
    };

    // Heikin Ashi mumları (opsiyonel)
    let src = closes;
    if (useHA) {
        const haClose = bars.map((b) => (b.open + b.high + b.low + b.close) / 4);
        src = haClose;
    }

    const nLoss = keyValue * atr(bars.length - 1);
    const stop: number[] = [];
    const pos: number[] = [];
    for (let i = 0; i < bars.length; i++) {
        const s = src[i];
        const prevStop = i > 0 ? stop[i - 1] : 0;
        const prevSrc = i > 0 ? src[i - 1] : 0;
        if (i === 0) {
            stop.push(s - nLoss);
            pos.push(0);
            continue;
        }
        let st: number;
        if (s > prevStop && prevSrc > prevStop) st = Math.max(prevStop, s - nLoss);
        else if (s < prevStop && prevSrc < prevStop) st = Math.min(prevStop, s + nLoss);
        else if (s > prevStop) st = s - nLoss;
        else st = s + nLoss;
        stop.push(st);
        let p: number;
        if (prevSrc < stop[i - 1] && s > stop[i - 1]) p = 1;
        else if (prevSrc > stop[i - 1] && s < stop[i - 1]) p = -1;
        else p = pos[i - 1];
        pos.push(p);
    }

    // crossover: ema(src,1) = src — buy/sell sadece stop kırılımında
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = 1; i < bars.length; i++) {
        const above = src[i] > stop[i] && src[i - 1] <= stop[i - 1];
        const below = src[i] < stop[i] && src[i - 1] >= stop[i - 1];
        if (above) signals.push({ time: bars[i].time, type: "buy" });
        else if (below) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// BB Squeeze sinyalleri: band daralması + hacim patlaması → kırılım yönünde buy/sell
const bbSqueezeSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const lookback = Math.max(10, Math.round(params.lookback ?? 20));
    const period = Math.max(5, Math.round(params.period ?? 20));
    const stdDev = params.stdDev ?? 2;
    const volMult = params.volMult ?? 1.5;
    if (bars.length < lookback + period) return [];

    const closes = bars.map((b) => b.close);
    const volumes = bars.map((b) => b.volume);
    const bb = (i: number) => {
        const slice = closes.slice(i - period + 1, i + 1);
        const sma = slice.reduce((a, b) => a + b, 0) / period;
        const std = Math.sqrt(slice.reduce((a, b) => a + (b - sma) ** 2, 0) / period);
        return { upper: sma + std * stdDev, lower: sma - std * stdDev, bandwidth: (2 * std * stdDev) / sma };
    };

    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = lookback; i < bars.length; i++) {
        const cur = bb(i);
        // geçmiş bandwidth'lerin minimumu
        let minBw = Infinity;
        for (let j = i - lookback + 1; j < i; j++) {
            if (j >= period) minBw = Math.min(minBw, bb(j).bandwidth);
        }
        if (minBw === Infinity) continue;
        const isSqueeze = cur.bandwidth <= minBw * 1.1;
        const avgVol = volumes.slice(i - 10, i).reduce((a, b) => a + b, 0) / Math.min(10, i);
        const volSpike = volumes[i] > avgVol * volMult;
        if (isSqueeze && volSpike && closes[i] > cur.upper) signals.push({ time: bars[i].time, type: "buy" });
        else if (isSqueeze && volSpike && closes[i] < cur.lower) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// EMA hesaplama (backend ile aynı: ağırlıklı konvolüsyon)
const ema = (values: number[], period: number): number | null => {
    if (values.length < period) return null;
    const weights = Array.from({ length: period }, (_, i) => Math.exp(-1 + (i / (period - 1)) * 1));
    const wSum = weights.reduce((a, b) => a + b, 0);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += values[values.length - period + i] * weights[i];
    return sum / wSum;
};

// RSI hesaplama (backend ile aynı)
const rsi = (values: number[], period: number): number | null => {
    if (values.length < period + 1) return null;
    let gain = 0, loss = 0;
    for (let i = 1; i <= period; i++) {
        const d = values[i] - values[i - 1];
        if (d > 0) gain += d; else loss -= d;
    }
    let avgGain = gain / period, avgLoss = loss / period;
    for (let i = period + 1; i < values.length; i++) {
        const d = values[i] - values[i - 1];
        avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
        avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    }
    if (avgLoss === 0) return 100;
    return 100 - 100 / (1 + avgGain / avgLoss);
};

// EMA Pullback sinyalleri: trend + pullback + RSI soğuma → buy; trend bozulması → sell
const emaPullbackSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const emaShort = Math.max(3, Math.round(params.emaShort ?? 9));
    const emaMid = Math.max(5, Math.round(params.emaMid ?? 21));
    const emaTrend = Math.max(10, Math.round(params.emaTrend ?? 50));
    const rsiPeriod = Math.max(2, Math.round(params.rsiPeriod ?? 14));
    if (bars.length < emaTrend + 5) return [];

    const closes = bars.map((b) => b.close);
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = emaTrend + 1; i < bars.length; i++) {
        const e9 = ema(closes.slice(0, i + 1), emaShort);
        const e21 = ema(closes.slice(0, i + 1), emaMid);
        const e50 = ema(closes.slice(0, i + 1), emaTrend);
        const r = rsi(closes.slice(0, i + 1), rsiPeriod);
        if (e9 == null || e21 == null || e50 == null || r == null) continue;
        const uptrend = e9 > e21 && e21 > e50;
        const pulledBack = closes[i - 1] <= e21 && closes[i] > e21;
        const cooled = r >= 40 && r <= 55;
        if (uptrend && pulledBack && cooled) signals.push({ time: bars[i].time, type: "buy" });
        else if (e9 < e21) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// VWAP + MACD sinyalleri: fiyat VWAP üstü + MACD pozitif → buy; MACD negatif → sell
const vwapMacdSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const vwapPeriod = Math.max(5, Math.round(params.vwapPeriod ?? 20));
    const fast = Math.max(3, Math.round(params.macdFast ?? 12));
    const slow = Math.max(5, Math.round(params.macdSlow ?? 26));
    const signal = Math.max(2, Math.round(params.macdSignal ?? 9));
    if (bars.length < vwapPeriod + slow + signal) return [];

    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const volumes = bars.map((b) => b.volume);

    const macdAt = (i: number): { macd: number; signal: number; hist: number } | null => {
        if (i < slow + signal) return null;
        const slice = closes.slice(0, i + 1);
        const eFast = ema(slice, fast);
        const eSlow = ema(slice, slow);
        if (eFast == null || eSlow == null) return null;
        const macdLine = eFast - eSlow;
        // sinyal çizgisi: macd değerlerinin EMA'sı (basit yaklaşım)
        const macdVals: number[] = [];
        for (let j = slow; j <= i; j++) {
            const ef = ema(closes.slice(0, j + 1), fast);
            const es = ema(closes.slice(0, j + 1), slow);
            if (ef != null && es != null) macdVals.push(ef - es);
        }
        const sig = ema(macdVals, signal);
        if (sig == null) return null;
        return { macd: macdLine, signal: sig, hist: macdLine - sig };
    };

    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = vwapPeriod + slow + signal; i < bars.length; i++) {
        const tp = highs.slice(i - vwapPeriod + 1, i + 1).map((h, idx) => (h + lows[i - vwapPeriod + 1 + idx] + closes[i - vwapPeriod + 1 + idx]) / 3);
        const vols = volumes.slice(i - vwapPeriod + 1, i + 1);
        const vwap = tp.reduce((a, b, idx) => a + b * vols[idx], 0) / vols.reduce((a, b) => a + b, 0);
        const m = macdAt(i);
        if (!m) continue;
        if (closes[i] > vwap && m.hist > 0 && m.macd > m.signal) signals.push({ time: bars[i].time, type: "buy" });
        else if (m.hist < 0 && m.macd < m.signal) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// CMO hesaplama (backend ile aynı)
const cmo = (values: number[], period: number): number | null => {
    if (values.length < period + 1) return null;
    let gains = 0, losses = 0;
    for (let i = values.length - period; i < values.length; i++) {
        const d = values[i] - values[i - 1];
        if (d > 0) gains += d; else losses -= d;
    }
    if (gains + losses === 0) return 0;
    return 100 * (gains - losses) / (gains + losses);
};

// CRSI hesaplama (backend ile aynı: RSI3 + Streak RSI2 + PercentRank50)
const crsi = (values: number[], rsiPeriod: number, rankPeriod: number): number | null => {
    if (values.length < rankPeriod + 2) return null;
    const r = rsi(values, rsiPeriod);
    if (r == null) return null;
    // streak serisi
    const streaks: number[] = [0];
    for (let i = 1; i < values.length; i++) {
        if (values[i] > values[i - 1]) streaks.push(streaks[i - 1] > 0 ? Math.max(1, streaks[i - 1] + 1) : 1);
        else if (values[i] < values[i - 1]) streaks.push(streaks[i - 1] < 0 ? Math.min(-1, streaks[i - 1] - 1) : -1);
        else streaks.push(0);
    }
    const up = streaks.slice(-2).filter((s) => s > 0);
    const down = streaks.slice(-2).filter((s) => s < 0).map((s) => Math.abs(s));
    const avgUp = up.length ? up.reduce((a, b) => a + b, 0) / up.length : 0;
    const avgDown = down.length ? down.reduce((a, b) => a + b, 0) / down.length : 0;
    const streakRsi = avgDown === 0 ? 100 : 100 - 100 / (1 + avgUp / avgDown);
    // percent rank
    const currentChange = values[values.length - 1] - values[values.length - 2];
    const lookback = values.slice(-rankPeriod - 1, -1);
    let below = 0;
    for (let i = 1; i < lookback.length; i++) {
        if (lookback[i] - lookback[i - 1] < currentChange) below++;
    }
    const percentRank = lookback.length > 1 ? (below / (lookback.length - 1)) * 100 : 0;
    return (r + streakRsi + percentRank) / 3;
};

// CMO + CRSI Derin Dip sinyalleri: aşırı düşüş → buy; aşırı yükseliş → sell
const cmoCrsiSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const cmoPeriod = Math.max(5, Math.round(params.cmoPeriod ?? 9));
    const rsiPeriod = Math.max(2, Math.round(params.rsiPeriod ?? 3));
    const rankPeriod = Math.max(20, Math.round(params.rankPeriod ?? 100));
    const buyCmo = params.buyCmo ?? -63;
    const buyCrsi = params.buyCrsi ?? 30;
    const sellCmo = params.sellCmo ?? 63;
    const sellCrsi = params.sellCrsi ?? 70;
    if (bars.length < rankPeriod + 2) return [];

    const closes = bars.map((b) => b.close);
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = rankPeriod + 1; i < bars.length; i++) {
        const slice = closes.slice(0, i + 1);
        const c = cmo(slice, cmoPeriod);
        const cr = crsi(slice, rsiPeriod, rankPeriod);
        if (c == null || cr == null) continue;
        if (c <= buyCmo && cr <= buyCrsi) signals.push({ time: bars[i].time, type: "buy" });
        else if (c >= sellCmo) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

export default function ChartsPage() {
    const [symbol, setSymbol] = useState<string>("BTCTRY");
    const [symbols, setSymbols] = useState<string[]>(FALLBACK_SYMBOLS);
    const [interval, setTf] = useState<string>("5m");
    const [loading, setLoading] = useState(true);
    const [bars, setBars] = useState<Bar[]>([]);
    const [instances, setInstances] = useState<IndicatorInstance[]>(DEFAULT_INSTANCES);
    const [picking, setPicking] = useState(false);
    const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
    const [volumeVisible, setVolumeVisible] = useState(true);
    const [countdown, setCountdown] = useState<number>(0);
    const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
    const [showPositions, setShowPositions] = useState(false);
    const [showPatterns, setShowPatterns] = useState(false);
    const [patternTooltip, setPatternTooltip] = useState<{ x: number; y: number; pattern: PatternMarker } | null>(null);
    const [positions, setPositions] = useState<any[]>([]);
    const chartHeightRef = useRef(TOTAL_HEIGHT);
    const positionLinesRef = useRef<Map<string, IPriceLine[]>>(new Map());
    const positionMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const utBotMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const patternMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);

    // localStorage yükleme: hydration uyumluluğu için client tarafında yap
    useEffect(() => {
        fetch(`${API_BASE}/api/config`).then((r) => r.json()).then((d) => {
            const active = Array.isArray(d.symbols) && d.symbols.length ? d.symbols : FALLBACK_SYMBOLS;
            setSymbols([...active].sort((a, b) => a.localeCompare(b)));
            setSymbol((current) => active.includes(current) ? current : active[0]);
        }).catch(() => setSymbols(FALLBACK_SYMBOLS));
        const savedSymbol = loadPersisted(LS_SYMBOL, "BTCTRY");
        const savedInterval = loadPersisted(LS_INTERVAL, "5m");
        setSymbol(savedSymbol);
        setTf(savedInterval);
        setInstances(loadIndicators());
        loadFromDb(savedSymbol);
    }, []);

    // mum kapanış geri sayımı: seçili TF'ye göre kalan süre
    useEffect(() => {
        const tick = () => {
            const now = Date.now();
            const ms = INTERVAL_MS[interval] || 60_000;
            const next = Math.ceil(now / ms) * ms;
            setCountdown(Math.max(0, next - now));
        };
        tick();
        const t = setInterval(tick, 250);
        return () => clearInterval(t);
    }, [interval]);

    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const overlaySeries = useRef<Map<string, ISeriesApi<"Line">[]>>(new Map());
    const paneSeries = useRef<Map<string, (ISeriesApi<"Line"> | ISeriesApi<"Histogram">)[]>>(new Map());
    const volumePaneIndexRef = useRef<number | null>(null);
    // pane yükseklikleri: "main" | "volume" | indikatör uid anahtarıyla saklanır — index bazlı değil,
    // böylece hacim kapatılıp paneler kayınca yükseklikler doğru pane'e uygulanır
    const paneHeightsRef = useRef<Record<string, number>>(
        typeof window === "undefined" ? {} : loadPersisted<Record<string, number>>(LS_PANE_HEIGHTS, {})
    );
    const paneKeyByIndexRef = useRef<Map<number, string>>(new Map());

    // ana grafik kurulumu (bir kez)
    useEffect(() => {
        if (!containerRef.current) return;
        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: chartHeightRef.current,
            layout: { background: { color: "transparent" }, textColor: "#6b7280", fontFamily: "JetBrains Mono, monospace" },
            grid: {
                vertLines: { color: "rgba(55, 65, 81, 0.2)" },
                horzLines: { color: "rgba(55, 65, 81, 0.2)" }
            },
            crosshair: { mode: 0, vertLine: { color: "#10b981" }, horzLine: { color: "#10b981" } },
            timeScale: { timeVisible: true, secondsVisible: false }
        });
        chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });
        const series = chart.addSeries(CandlestickSeries, {
            upColor: "#10b981", downColor: "#ef4444", borderVisible: false,
            wickUpColor: "#10b981", wickDownColor: "#ef4444"
        });
        chartRef.current = chart;
        candleRef.current = series;

        // pane yüksekliklerini izle: kullanıcı sürükleyince localStorage'a yaz (key bazlı)
        const saveTimer = setInterval(() => {
            if (!chartRef.current) return;
            // render henüz pane key'lerini doldurmadıysa yazma — yoksa gerçek ama küçük değerler
            // ilk render öncesi DOM boyutları localStorage'a kaydedilip chart'ı küçültür
            if (paneKeyByIndexRef.current.size === 0) return;
            const heights: Record<string, number> = {};
            chartRef.current.panes().forEach((p, i) => {
                const key = paneKeyByIndexRef.current.get(i) || String(i);
                heights[key] = p.getHeight();
            });
            const key = JSON.stringify(heights);
            if (key !== JSON.stringify(paneHeightsRef.current)) {
                paneHeightsRef.current = heights;
                try { localStorage.setItem(LS_PANE_HEIGHTS, key); } catch { }
            }
        }, 1000);

        // pencere boyutu değişince grafiği yeniden boyutlandır (autoSize yerine manuel — pane yükseklikleri sabit)
        const ro = new ResizeObserver(() => {
            if (!chartRef.current || !containerRef.current) return;
            const viewportHeight = typeof window !== "undefined" ? window.innerHeight : 900;
            chartHeightRef.current = clamp(Math.round(viewportHeight * (window.innerWidth < 768 ? 0.52 : 0.62)), 420, 600);
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: chartHeightRef.current });
        });
        ro.observe(containerRef.current);

        return () => {
            clearInterval(saveTimer);
            ro.disconnect();
            chart.remove();
            chartRef.current = null;
            candleRef.current = null;
        };
    }, []);

    // veri çekme
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        const load = async () => {
            try {
                const res = await fetch(`https://api.binance.me/api/v1/klines?symbol=${symbol}&interval=${interval}&limit=200`);
                const data = await res.json();
                if (cancelled || !candleRef.current) return;
                const candles: Bar[] = data.map((k: number[]) => ({
                    time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]
                }));
                setBars(candles);
                candleRef.current.setData(candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
                const last = candles[candles.length - 1]?.close ?? 0;
                const priceFormat = last < 0.001
                    ? { type: "price" as const, precision: 8, minMove: 0.00000001 }
                    : last < 0.1
                        ? { type: "price" as const, precision: 6, minMove: 0.000001 }
                        : last < 1
                            ? { type: "price" as const, precision: 4, minMove: 0.0001 }
                            : { type: "price" as const, precision: 2, minMove: 0.01 };
                candleRef.current.applyOptions({ priceFormat });
                // fiyat ölçeğini sıfırla: önceki sembolün zoom/scale'i yeni sembole taşınmasın
                chartRef.current?.priceScale("right").applyOptions({ autoScale: true });
                chartRef.current?.timeScale().fitContent();
            } catch (e) {
                console.error("kline hatası:", e);
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        load();
        return () => { cancelled = true; };
    }, [symbol, interval]);

    // canlı mum güncelleme: Binance WebSocket'ten seçili sembolün kline'ını dinle
    useEffect(() => {
        const ws = new WebSocket(`wss://stream-cloud.binance.tr/ws/${symbol.toLowerCase()}@kline_${interval}`);
        ws.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data);
                const k = msg.k;
                if (!k) return;
                const bar: Bar = {
                    time: Math.floor(k.t / 1000),
                    open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v
                };
                setBars((prev) => {
                    if (!prev.length) return prev;
                    const last = prev[prev.length - 1];
                    if (bar.time === last.time) {
                        // aynı mum güncelleniyor — update() ile yerinde güncelle (görünümü sıfırlamaz)
                        candleRef.current?.update(bar as any);
                        const next = [...prev];
                        next[next.length - 1] = bar;
                        return next;
                    }
                    if (bar.time > last.time) {
                        // yeni mum açıldı — update() son bara ekler
                        candleRef.current?.update(bar as any);
                        return [...prev.slice(-199), bar];
                    }
                    return prev;
                });
            } catch { /* parse hatası yoksay */ }
        };
        return () => ws.close();
    }, [symbol, interval]);

    // açık pozisyonları çek: her 5 sn'de bir, pozisyon gösterimi için
    useEffect(() => {
        let cancelled = false;
        const fetchPositions = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/positions`);
                const data = await res.json();
                if (!cancelled) setPositions(data.positions || []);
            } catch { /* backend yoksa sessiz geç */ }
        };
        fetchPositions();
        const t = setInterval(fetchPositions, 5000);
        return () => { cancelled = true; clearInterval(t); };
    }, []);

    // mum serisi ilk yüklemede load() içinde setData ile kurulur,
    // canlı güncelleme WebSocket handler'ında update() ile yapılır (görünüm sıfırlanmaz)

    // indikatörleri çiz: sadece yapı değişince (indikatör/hacim) yeniden inşa et
    const buildLayout = useCallback((skipHeight: boolean) => {
        const chart = chartRef.current;
        if (!chart) return;

        // Önce tüm eski serileri ve pane'leri temizle
        overlaySeries.current.forEach((arr) => arr.forEach((s) => {
            try { chart.removeSeries(s); } catch { }
        }));
        overlaySeries.current.clear();

        paneSeries.current.forEach((arr) => arr.forEach((s) => {
            try { chart.removeSeries(s); } catch { }
        }));
        paneSeries.current.clear();

        if (volumeRef.current) {
            try { chart.removeSeries(volumeRef.current); } catch { }
        }
        volumeRef.current = null;
        volumePaneIndexRef.current = null;

        while (chart.panes().length > 1) chart.removePane(1);
        chart.chartElement().querySelectorAll(".pane-title").forEach((n) => n.remove());

        const instPanes = new Map<string, number>(); // uid -> pane index
        let paneIdx = 1;

        // HACİM pane'i (pane 1, isteğe bağlı)
        if (volumeVisible) {
            const volData = bars.map((b) => ({
                time: b.time as UTCTimestamp,
                value: b.volume,
                color: b.close >= b.open ? "rgba(16,185,129,0.45)" : "rgba(239,68,68,0.45)"
            }));
            const volumeSeries = chart.addSeries(HistogramSeries, {
                priceLineVisible: false, lastValueVisible: false
            }, 1);
            volumeSeries.setData(volData);
            volumeRef.current = volumeSeries;
            volumePaneIndexRef.current = 1;
            chart.priceScale("right", 1).applyOptions({ scaleMargins: { top: 0.25, bottom: 0.02 } });
            paneIdx = 2;
        }
        for (const inst of instances) {
            const entry = findIndicatorEntry(inst.registryId);
            if (!entry) continue;
            let result;
            try {
                result = entry.calculate(bars, inst.params);
            } catch {
                // Eksik/uyumsuz parametre tek bir indikatörün tüm grafiği bozmasını engeller.
                continue;
            }
            // Bazı community/pattern indikatörleri çizim primitive'i döndürür;
            // bu renderer yalnızca numeric plot serilerini destekler.
            // Böyle bir sonuç tüm grafik akışını kırmadan marker/primitive katmanına bırakılır.
            const plots = result?.plots
                ? Object.values(result.plots).filter((p) => Array.isArray(p) && p.some((pt) => pt.value != null && !Number.isNaN(pt.value)))
                : [];
            if (!plots.length) continue;

            const style = inst.style;
            const isHisto = plots.length >= 3;

            if (inst.overlay) {
                const arr = plots.map((plot, pi) => {
                    const lastPoint = [...plot].reverse().find((p) => p.value != null && !Number.isNaN(p.value));
                    const s = chart.addSeries(LineSeries, {
                        color: style.colors[pi] || PALETTE[pi % PALETTE.length],
                        lineWidth: style.lineWidth as 1 | 2 | 3 | 4,
                        priceLineVisible: style.showPriceLine,
                        lastValueVisible: style.showPriceLine
                    });
                    const data = plot
                        .filter((p) => p.value != null && !Number.isNaN(p.value))
                        .map((p) => ({ time: p.time as UTCTimestamp, value: p.value as number }));
                    s.setData(data);
                    if (lastPoint && style.showPriceLine) {
                        s.applyOptions({ priceLineVisible: true, lastValueVisible: true });
                        try {
                            (s as any).setData(data);
                        } catch {
                            // ignore
                        }
                    }
                    return s;
                });
                overlaySeries.current.set(inst.uid, arr);
            } else {
                instPanes.set(inst.uid, paneIdx);
                // min/max bantları: 3+ plotlu indikatörlerde son plotlar banttır (RSI 30/70 gibi)
                const boundStart = isHisto ? 3 : Math.min(plots.length, 2);
                const arr: (ISeriesApi<"Line"> | ISeriesApi<"Histogram">)[] = [];
                const manualBounds = [
                    ...(style.minValue != null ? [{ value: style.minValue, color: style.colors[1] || PALETTE[1] }] : []),
                    ...(style.maxValue != null ? [{ value: style.maxValue, color: style.colors[2] || PALETTE[2] }] : [])
                ];
                plots.forEach((plot, pi) => {
                    const data = plot
                        .filter((p) => p.value != null && !Number.isNaN(p.value))
                        .map((p) => ({
                            time: p.time as UTCTimestamp, value: p.value as number,
                            ...(p.color ? { color: p.color } : {})
                        }));
                    if (!data.length) return;
                    if (isHisto && pi === 0) {
                        const s = chart.addSeries(HistogramSeries, {
                            color: style.colors[0] || PALETTE[0], priceLineVisible: false, lastValueVisible: false
                        }, paneIdx);
                        s.setData(data);
                        arr.push(s);
                    } else if (pi >= boundStart) {
                        // bant çizgisi: göster/gizle stile bağlı
                        if (!style.showBounds) return;
                        const s = chart.addSeries(LineSeries, {
                            color: style.colors[pi] || PALETTE[pi % PALETTE.length],
                            lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false
                        }, paneIdx);
                        s.setData(data);
                        arr.push(s);
                    } else {
                        const s = chart.addSeries(LineSeries, {
                            color: style.colors[pi] || PALETTE[pi % PALETTE.length],
                            lineWidth: style.lineWidth as 1 | 2 | 3 | 4, priceLineVisible: style.showPriceLine, lastValueVisible: style.showPriceLine
                        }, paneIdx);
                        s.setData(data);
                        if (style.showPriceLine) {
                            s.applyOptions({ priceLineVisible: true, lastValueVisible: true });
                        }
                        arr.push(s);
                    }
                });
                paneSeries.current.set(inst.uid, arr);
                paneIdx++;
            }
        }

        // manuel min/max bant değerleri varsa bunları da çiz
        instances.forEach((inst) => {
            const entry = findIndicatorEntry(inst.registryId);
            if (!entry || inst.overlay) return;
            const style = inst.style;
            if (!style.showBounds) return;
            const paneIndex = instPanes.get(inst.uid);
            if (!paneIndex || style.minValue == null && style.maxValue == null) return;

            const bounds = [
                ...(style.minValue != null ? [{ value: style.minValue, color: style.colors[1] || PALETTE[1] }] : []),
                ...(style.maxValue != null ? [{ value: style.maxValue, color: style.colors[2] || PALETTE[2] }] : [])
            ];

            // bantları pane serisine fiyat çizgisi olarak ekle → tüm pane genişliğine, sağ fiyat eksenine kadar uzar
            const paneSeriesArr = paneSeries.current.get(inst.uid);
            const anchor = paneSeriesArr?.[0];
            if (!anchor) return;
            bounds.forEach((bound) => {
                anchor.createPriceLine({
                    price: bound.value,
                    color: bound.color,
                    lineWidth: 1,
                    lineStyle: 2,
                    axisLabelVisible: true,
                    title: String(bound.value)
                });
            });
        });

        // pane yükseklikleri: key bazlı eşleştirme — main/volume/uid
        // paneKeyByIndexRef'e her pane'in anahtarını yaz (observer bunu kullanır)
        paneKeyByIndexRef.current.clear();
        const paneKeys: string[] = ["main"];
        if (volumeVisible) paneKeys.push("volume");
        // non-overlay indikatörler render sırasında paneIdx sırasıyla eklenir; burada uid sırasını kullan
        for (const inst of instances) {
            if (!inst.overlay) paneKeys.push(inst.uid);
        }
        const paneCount = chart.panes().length;
        // sabit toplam yükseklik: canvas (TOTAL_HEIGHT) asla değişmez.
        // Kaydedilmiş pane yükseklikleri birebir korunur; main pane kalanı (slack) emer,
        // böylece pane aç/kapa sadece main'i büyütür/küçültür, diğer paneller sabit kalır.
        // skipHeight: bars canlı güncellenirken yükseklikleri EZME — kullanıcı sürüklemesi korunur
        if (!skipHeight) {
            const alloc = paneKeys.map((key, i) => ({
                key,
                h: i === 0
                    ? MAIN_MIN
                    : clamp(paneHeightsRef.current[key] || (key === "volume" ? 90 : PANE_H), PANE_MIN, chartHeightRef.current)
            }));
            const nonMain = alloc.reduce((s, x, i) => (i === 0 ? s : s + x.h), 0);
            const mainH = clamp(chartHeightRef.current - nonMain, MAIN_MIN, chartHeightRef.current);
            const targetH = alloc.map((x, i) => (i === 0 ? mainH : x.h));

            chart.applyOptions({ height: chartHeightRef.current });
            chart.panes().forEach((p, i) => {
                const key = paneKeys[i] || `pane${i}`;
                paneKeyByIndexRef.current.set(i, key);
                p.setHeight(targetH[i] ?? PANE_MIN);
            });
        }

        // pane başlıkları: TradingView gibi pane'in sol üst KÖŞESİNİN İÇİNDE
        // başlık pane TR'sinin (table tr[2i]) ilk hücresine gömülür → pane resize edilince otomatik takip eder
        requestAnimationFrame(() => {
            const el = chart.chartElement();
            el.querySelectorAll(".pane-title").forEach((n) => n.remove());
            const rows = Array.from(el.querySelectorAll("table tr"));
            const paneCount = chart.panes().length;
            if (!volumeVisible) {
                const toggle = document.createElement("div");
                toggle.className = "pane-title";
                toggle.style.cssText = `position:absolute;top:4px;left:8px;z-index:5;display:flex;align-items:center;gap:5px;background:rgba(11,15,20,0.9);border:1px solid #1f2937;border-radius:6px;padding:2px 7px;font-family:JetBrains Mono,monospace;font-size:11px;color:#9ca3af;cursor:pointer;pointer-events:auto;`;
                const label = document.createElement("span");
                label.innerText = "HACİM KAPALI";
                const open = document.createElement("button");
                open.innerText = "＋";
                open.style.cssText = "background:none;border:none;color:#34d399;cursor:pointer;font-size:11px;padding:0 2px;";
                open.title = "Aç";
                open.onclick = () => setVolumeVisible(true);
                toggle.append(label, open);
                el.appendChild(toggle);
            }
            for (let i = 1; i < paneCount; i++) {
                const tr = rows[2 * i];
                if (!tr) continue;
                const td = tr.querySelector("td") as HTMLElement | null;
                if (!td) continue;
                td.style.position = "relative";

                let bar: HTMLDivElement;
                if (volumeVisible && i === 1) {
                    // HACİM başlığı (kapama butonu ile)
                    bar = document.createElement("div");
                    bar.className = "pane-title";
                    bar.style.cssText = `position:absolute;top:4px;left:8px;z-index:5;display:flex;align-items:center;gap:5px;background:rgba(11,15,20,0.9);border:1px solid #1f2937;border-radius:6px;padding:2px 7px;font-family:JetBrains Mono,monospace;font-size:11px;color:#9ca3af;cursor:default;pointer-events:auto;`;
                    const name = document.createElement("span");
                    name.innerText = "HACİM";
                    const close = document.createElement("button");
                    close.innerText = "✕";
                    close.style.cssText = "background:none;border:none;color:#9ca3af;cursor:pointer;font-size:11px;padding:0 2px;";
                    close.title = "Kapat";
                    close.onclick = () => setVolumeVisible(false);
                    bar.append(name, close);
                } else {
                    const inst = [...instances].find((x) => instPanes.get(x.uid) === i);
                    if (!inst) continue;
                    bar = document.createElement("div");
                    bar.className = "pane-title";
                    bar.style.cssText = `position:absolute;top:4px;left:8px;z-index:5;display:flex;align-items:center;gap:5px;background:rgba(11,15,20,0.9);border:1px solid #1f2937;border-radius:6px;padding:2px 7px;font-family:JetBrains Mono,monospace;font-size:11px;color:#34d399;cursor:default;pointer-events:auto;`;
                    const name = document.createElement("span");
                    name.innerText = inst.name;
                    const gear = document.createElement("button");
                    gear.innerText = "⚙";
                    gear.style.cssText = "background:none;border:none;color:#9ca3af;cursor:pointer;font-size:11px;padding:0 2px;";
                    gear.title = "Ayarlar";
                    gear.onclick = () => {
                        const entry = findIndicatorEntry(inst.registryId);
                        if (entry) setEditTarget({ entry, editUid: inst.uid });
                    };
                    const x = document.createElement("button");
                    x.innerText = "✕";
                    x.style.cssText = "background:none;border:none;color:#9ca3af;cursor:pointer;font-size:11px;padding:0 2px;";
                    x.title = "Kaldır";
                    x.onclick = () => removeIndicator(inst.uid);
                    bar.append(name, gear, x);
                }
                td.appendChild(bar);
            }
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bars, instances, volumeVisible]);

    // yapı değişince (indikatör/hacim) yeniden inşa et + yükseklik uygula
    useEffect(() => {
        buildLayout(false);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [instances, volumeVisible]);

    // bars canlı güncellenince sadece veriyi yeniden çiz — yükseklikleri EZME
    useEffect(() => {
        buildLayout(true);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bars]);

    // Spot pozisyon çizgileri: giriş ve sabit %2 satış hedefi.
    useEffect(() => {
        const chart = chartRef.current;
        const series = candleRef.current;
        if (!chart || !series) return;

        // eski çizgileri temizle
        positionLinesRef.current.forEach((lines) => lines.forEach((l) => {
            try { series.removePriceLine(l); } catch { }
        }));
        positionLinesRef.current.clear();
        // eski marker'ları temizle
        positionMarkersRef.current?.setMarkers([]);
        positionMarkersRef.current = null;

        if (!showPositions) return;

        const pos = positions.find((p) => p.symbol === symbol);
        if (!pos) return;

        const lines: IPriceLine[] = [];
        const addLine = (price: number, color: string, title: string) => {
            if (price == null || price <= 0) return;
            try {
                const pl = series.createPriceLine({
                    price, color, lineWidth: 1, lineStyle: 2,
                    axisLabelVisible: true, title
                });
                lines.push(pl);
            } catch { }
        };
        addLine(pos.entry, "#10b981", `GİRİŞ ${pos.entry}`);
        addLine(pos.entry * 1.02, "#3b82f6", "SATIŞ HEDEFİ +2%");
        positionLinesRef.current.set(symbol, lines);

        // giriş noktasına marker ekle (v5 createSeriesMarkers)
        try {
            const markers = createSeriesMarkers(series, []);
            positionMarkersRef.current = markers;
            // entry_time backend'de time.time() = saniye; UTCTimestamp de saniye.
            // Marker zamanı mum zamanıyla EŞLEŞMELİ (skill: misaligned markers dropped silently)
            // → entry_time'ı seçili interval'in mum başlangıcına yuvarla
            const ms = INTERVAL_MS[interval] || 60_000;
            const entrySec = pos.entry_time ?? Math.floor(Date.now() / 1000);
            const barTime = Math.floor(entrySec / (ms / 1000)) * (ms / 1000);
            markers.setMarkers([{
                time: barTime as UTCTimestamp,
                position: pos.side === "LONG" ? "belowBar" : "aboveBar",
                color: pos.side === "LONG" ? "#10b981" : "#ef4444",
                shape: pos.side === "LONG" ? "arrowUp" : "arrowDown",
                text: pos.side === "LONG" ? "LONG" : "SHORT",
                size: 1
            }]);
        } catch { /* marker zamanı veri aralığında değilse sessiz geç */ }
    }, [showPositions, positions, symbol, bars]);

    // Strateji buy/sell marker'ları: instances'ta strateji indikatörü varsa seçili TF'ye göre hesapla ve çiz
    const extendedStrategySignals = (bars: Bar[], kind: string) => {
        const out: { time: number; type: "buy" | "sell" }[] = [];
        for (let i = 50; i < bars.length; i++) {
            const c = bars[i].close;
            const mean = bars.slice(i - 20, i).reduce((s, b) => s + b.close, 0) / 20;
            const high = Math.max(...bars.slice(i - 20, i).map((b) => b.high));
            const low = Math.min(...bars.slice(i - 20, i).map((b) => b.low));
            const ret5 = c / bars[i - 5].close - 1;
            const buy = kind === "ema_vwap" ? c > mean && bars[i - 1].close <= mean
                : kind === "breakout" ? c > high && bars[i].volume > (bars.slice(i - 20, i).reduce((s, b) => s + b.volume, 0) / 20) * 1.5
                : kind === "orderflow" ? bars[i - 2].close < bars[i - 1].close && bars[i - 1].close < c
                : kind === "momentum" ? ret5 > 0.003 && c > mean
                : c < low;
            if (buy) out.push({ time: bars[i].time, type: "buy" });
        }
        return out;
    };
    const strategySignalFns: Record<string, (bars: Bar[], params: Record<string, any>) => { time: number; type: "buy" | "sell" }[]> = {
        ut_bot: utBotSignals,
        bb_squeeze: bbSqueezeSignals,
        ema_pullback: emaPullbackSignals,
        vwap_macd: vwapMacdSignals,
        cmo_crsi: cmoCrsiSignals,
        ema_vwap_pullback: (bars) => extendedStrategySignals(bars, "ema_vwap"),
        bb_squeeze_orderflow: (bars) => extendedStrategySignals(bars, "breakout"),
        orderflow: (bars) => extendedStrategySignals(bars, "orderflow"),
        momentum: (bars) => extendedStrategySignals(bars, "momentum"),
        vwap_mean_reversion: (bars) => extendedStrategySignals(bars, "mean_reversion"),
        keltner_breakout: (bars) => extendedStrategySignals(bars, "breakout"),
        chop_trend_filter: (bars) => extendedStrategySignals(bars, "momentum"),
        donchian_breakout: (bars) => extendedStrategySignals(bars, "breakout"),
    };
    const strategyColors: Record<string, { buy: string; sell: string }> = {
        ut_bot: { buy: "#22c55e", sell: "#ef4444" }, bb_squeeze: { buy: "#f97316", sell: "#ef4444" }, ema_pullback: { buy: "#38bdf8", sell: "#ef4444" }, vwap_macd: { buy: "#c084fc", sell: "#ef4444" }, cmo_crsi: { buy: "#eab308", sell: "#ef4444" },
        ema_vwap_pullback: { buy: "#22c55e", sell: "#ef4444" }, bb_squeeze_orderflow: { buy: "#f97316", sell: "#ef4444" }, orderflow: { buy: "#38bdf8", sell: "#ef4444" }, momentum: { buy: "#eab308", sell: "#ef4444" }, vwap_mean_reversion: { buy: "#c084fc", sell: "#ef4444" },
        keltner_breakout: { buy: "#fb7185", sell: "#ef4444" }, chop_trend_filter: { buy: "#a3e635", sell: "#ef4444" }, donchian_breakout: { buy: "#60a5fa", sell: "#ef4444" },
    };
    const strategyLabels: Record<string, string> = {
        ut_bot: "UT", bb_squeeze: "BB SQ", ema_pullback: "EMA PB", vwap_macd: "VWAP MACD", cmo_crsi: "CMO CRSI",
        ema_vwap_pullback: "EMA+VWAP", bb_squeeze_orderflow: "BB+FLOW", orderflow: "FLOW", momentum: "MTF MOM", vwap_mean_reversion: "VWAP MR",
        keltner_breakout: "KELT", chop_trend_filter: "CHOP", donchian_breakout: "DONCH",
    };

    // Grafik sinyallerini spot yürütme modeline dönüştür:
    // alıştan sonra yalnızca +2% hedef satış üretir; karşıt sinyal çıkış değildir.
    const spotExecutionSignals = (bars: Bar[], raw: { time: number; type: "buy" | "sell" }[]) => {
        const byTime = new Map(bars.map((bar) => [bar.time, bar]));
        let entry: number | null = null;
        const executed: { time: number; type: "buy" | "sell" }[] = [];
        const signalsByTime = new Map(raw.map((signal) => [signal.time, signal]));
        for (const bar of bars) {
            const signal = signalsByTime.get(bar.time);
            if (entry == null && signal?.type === "buy") {
                entry = bar.close;
                executed.push(signal);
            } else if (entry != null) {
                const target = entry * 1.02;
                if (bar.high >= target) {
                    executed.push({ time: bar.time, type: "sell" });
                    entry = null;
                }
            }
        }
        return executed;
    };

    useEffect(() => {
        const series = candleRef.current;
        if (!series) return;

        // eski marker'ları temizle
        utBotMarkersRef.current?.setMarkers([]);
        utBotMarkersRef.current = null;

        const stratInsts = instances.filter((i) => i.registryId in strategySignalFns);
        if (!stratInsts.length || bars.length === 0) return;

        try {
            const markers = createSeriesMarkers(series, []);
            utBotMarkersRef.current = markers;
            const all: { time: UTCTimestamp; position: "belowBar" | "aboveBar"; color: string; shape: "arrowUp" | "arrowDown"; text: string; size: number }[] = [];
            for (const inst of stratInsts) {
                const fn = strategySignalFns[inst.registryId];
                const colors = strategyColors[inst.registryId];
                const label = strategyLabels[inst.registryId];
                const signals = spotExecutionSignals(bars, fn(bars, inst.params));
                for (const s of signals) {
                    all.push({
                        time: s.time as UTCTimestamp,
                        position: s.type === "buy" ? "belowBar" : "aboveBar",
                        color: s.type === "buy" ? colors.buy : colors.sell,
                        shape: s.type === "buy" ? "arrowUp" : "arrowDown",
                        text: s.type === "buy" ? `${label} BUY` : `${label} SELL`,
                        size: 1
                    });
                }
            }
            markers.setMarkers(all);
        } catch { /* marker hatası sessiz geç */ }
    }, [instances, bars, symbol]);

    // Güçlü mum formasyonlarını seçili timeframe üzerinde marker olarak göster.
    useEffect(() => {
        patternMarkersRef.current?.setMarkers([]);
        patternMarkersRef.current = null;
        if (!showPatterns || !bars.length || !candleRef.current) return;
        try {
            const markers = createSeriesMarkers(candleRef.current, []);
            patternMarkersRef.current = markers;
            markers.setMarkers(strongCandlestickPatterns(bars).map((p) => ({
                time: p.time as UTCTimestamp,
                position: p.type === "buy" ? "belowBar" : "aboveBar",
                color: "#60a5fa",
                shape: "circle",
                text: "P",
                size: 1
            })));
        } catch { /* marker zamanı veri aralığı dışındaysa sessiz geç */ }
    }, [showPatterns, bars, symbol, interval]);

    useEffect(() => {
        const chart = chartRef.current;
        if (!chart || !showPatterns) { setPatternTooltip(null); return; }
        const patterns = new Map(strongCandlestickPatterns(bars).map((p) => [p.time, p]));
        const onMove = (param: any) => {
            const time = typeof param.time === "number" ? param.time : null;
            const point = param.point;
            const pattern = time == null ? null : patterns.get(time);
            if (!pattern || !point) { setPatternTooltip(null); return; }
            setPatternTooltip({ x: point.x, y: point.y, pattern });
        };
        chart.subscribeCrosshairMove(onMove);
        return () => chart.unsubscribeCrosshairMove(onMove);
    }, [showPatterns, bars, symbol, interval]);

    const addIndicator = (entry: RegistryEntry, params: Record<string, any>, style: IndicatorStyle) => {
        const next = [...instances, { uid: uid(), registryId: entry.id, name: entry.shortName, overlay: entry.overlay, params, style }];
        setInstances(next);
        localStorage.setItem(LS_INDICATORS, JSON.stringify(next));
        setEditTarget(null);
        setPicking(false);
    };

    const updateIndicator = (editUid: string, params: Record<string, any>, style: IndicatorStyle) => {
        const next = instances.map((i) => (i.uid === editUid ? { ...i, params, style } : i));
        setInstances(next);
        localStorage.setItem(LS_INDICATORS, JSON.stringify(next));
        setEditTarget(null);
    };

    const removeIndicator = (u: string) => {
        const next = instances.filter((i) => i.uid !== u);
        setInstances(next);
        localStorage.setItem(LS_INDICATORS, JSON.stringify(next));
    };

    const changeSymbol = (s: string) => {
        setSymbol(s);
        localStorage.setItem(LS_SYMBOL, JSON.stringify(s));
        loadFromDb(s);
    };

    const changeInterval = (i: string) => {
        setTf(i);
        localStorage.setItem(LS_INTERVAL, JSON.stringify(i));
    };

    // seçili sembolün grafik ayarlarını veritabanına kaydet (indikatör, TF, pane yükseklikleri, hacim)
    const saveToDb = async () => {
        setSaveState("saving");
        const payload = {
            interval,
            indicators: instances,
            paneHeights: paneHeightsRef.current,
            volumeVisible
        };
        try {
            await fetch(`${API}/${symbol}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            setSaveState("saved");
            setTimeout(() => setSaveState("idle"), 2000);
        } catch {
            setSaveState("idle");
        }
    };

    // veritabanından sembol ayarlarını yükle — varsa localStorage'ı ezer (DB daha güncel)
    const loadFromDb = async (s: string) => {
        try {
            const res = await fetch(`${API}/${s}`);
            const data = await res.json();
            const st = data?.settings;
            if (!st) return;
            setTf(st.interval || "5m");
            localStorage.setItem(LS_INTERVAL, JSON.stringify(st.interval || "5m"));
            if (st.indicators?.length) {
                setInstances(st.indicators);
                localStorage.setItem(LS_INDICATORS, JSON.stringify(st.indicators));
            }
            if (st.paneHeights) {
                paneHeightsRef.current = st.paneHeights;
                try { localStorage.setItem(LS_PANE_HEIGHTS, JSON.stringify(st.paneHeights)); } catch { }
            }
            if (typeof st.volumeVisible === "boolean") setVolumeVisible(st.volumeVisible);
        } catch { /* backend yoksa localStorage kullan */ }
    };

    return (
        <div className="max-w-7xl mx-auto space-y-5">
            <header className="flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h1 className="font-mono text-xl font-bold tracking-tight">
                        <span className="text-neon-green">GRAFİK</span> TERMİNALİ
                    </h1>
                    <p className="eyebrow mt-1">Binance public API · son 200 mum</p>
                </div>
                <div className="w-full lg:w-auto flex flex-wrap items-center gap-2 sm:gap-3">
                    <select
                        value={symbol}
                        onChange={(e) => changeSymbol(e.target.value)}
                        className="bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                    >
                        {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <div className="max-w-full overflow-x-auto flex rounded-lg border border-bunker-700">
                        {INTERVALS.map((i) => (
                            <button
                                key={i.v}
                                onClick={() => changeInterval(i.v)}
                                className={`px-3 py-2 font-mono text-xs transition-colors ${interval === i.v ? "bg-neon-green/15 text-neon-green" : "bg-bunker-900 text-bunker-muted hover:text-white"}`}
                            >
                                {i.l}
                            </button>
                        ))}
                    </div>
                    <button
                        onClick={() => setPicking(true)}
                        className="order-first lg:order-none px-4 py-2 min-h-10 rounded-lg border border-neon-green/40 bg-neon-green/10 font-mono text-sm text-neon-green hover:bg-neon-green/20 active:scale-[0.98] transition-transform"
                    >
                        + İNDİKATÖR
                    </button>
                    <button
                        onClick={saveToDb}
                        disabled={saveState === "saving"}
                        className={`px-4 py-2 rounded-lg border font-mono text-sm transition-colors ${saveState === "saved"
                            ? "border-neon-green bg-neon-green/20 text-neon-green"
                            : "border-neon-yellow/40 bg-neon-yellow/10 text-neon-yellow hover:bg-neon-yellow/20"
                            }`}
                    >
                        {saveState === "saving" ? "KAYDEDİLİYOR..." : saveState === "saved" ? "✓ KAYDEDİLDİ" : "KAYDET"}
                    </button>
                    <button
                        onClick={() => setShowPositions(!showPositions)}
                        className={`px-4 py-2 rounded-lg border font-mono text-sm transition-colors ${showPositions
                            ? "border-neon-green bg-neon-green/20 text-neon-green"
                            : "border-bunker-600 bg-bunker-900 text-bunker-muted hover:text-white"
                            }`}
                    >
                        POZİSYONLAR {showPositions ? "GİZLE" : "GÖSTER"}
                    </button>
                    <button
                        onClick={() => setShowPatterns(!showPatterns)}
                        aria-label={showPatterns ? "Mum formasyonlarını gizle" : "Mum formasyonlarını göster"}
                        title={showPatterns ? "Mum formasyonlarını gizle" : "Mum formasyonlarını göster"}
                        className={`px-4 py-2 rounded-lg border font-mono text-sm transition-colors ${showPatterns
                            ? "border-neon-green bg-neon-green/20 text-neon-green"
                            : "border-bunker-600 bg-bunker-900 text-bunker-muted hover:text-white"
                            }`}
                    >
                        {showPatterns ? "◉ FORMASYONLARI GİZLE" : "◌ FORMASYONLARI GÖSTER"}
                    </button>
                </div>
            </header>

            <button
                onClick={() => setPicking(true)}
                aria-label="İndikatör ekle"
                className="lg:hidden fixed bottom-5 right-4 z-40 min-h-12 px-4 rounded-full border border-neon-green/50 bg-bunker-950/95 text-neon-green shadow-[0_8px_30px_rgba(16,185,129,0.2)] backdrop-blur font-mono text-sm font-bold active:scale-95 transition-transform"
            >
                ＋ İNDİKATÖR
            </button>

            {instances.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="eyebrow">AKTİF:</span>
                    {instances.map((o) => (
                        <span
                            key={o.uid}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-mono text-xs ${o.overlay
                                ? "border-neon-yellow/30 bg-neon-yellow/10 text-neon-yellow"
                                : "border-neon-green/30 bg-neon-green/10 text-neon-green"
                                }`}
                        >
                            {o.name}
                            <button onClick={() => removeIndicator(o.uid)} className="hover:text-white">✕</button>
                        </span>
                    ))}
                </div>
            )}

            <div className="card bg-bunker-950 p-0 overflow-hidden relative">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center z-10 bg-bunker-950/70">
                        <p className="font-mono text-sm text-neon-green animate-pulse">YÜKLENİYOR...</p>
                    </div>
                )}
                <div ref={containerRef} className="w-full" />
                {patternTooltip && (
                    <div
                        className="absolute z-30 w-64 rounded-xl border border-blue-400/40 bg-bunker-950/95 p-3 shadow-[0_12px_35px_rgba(0,0,0,0.45)] backdrop-blur pointer-events-none"
                        style={{ left: Math.min(Math.max(patternTooltip.x + 16, 12), 360), top: Math.max(patternTooltip.y - 24, 12) }}
                    >
                        <div className="flex items-center gap-2">
                            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-blue-300 bg-blue-500/25 font-mono text-xs font-bold text-blue-200">P</span>
                            <span className="font-mono text-xs font-bold text-blue-200">{patternTooltip.pattern.text}</span>
                        </div>
                        <p className="mt-2 text-xs leading-5 text-slate-300">{patternDescriptions[patternTooltip.pattern.text]}</p>
                        <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-slate-500">{patternTooltip.pattern.type === "buy" ? "Boğa yönlü" : "Ayı yönlü"} · {interval}</p>
                    </div>
                )}
                {/* mum kapanış geri sayımı: grafiğin üzerinde sağ üst köşe */}
                <div className="absolute top-3 right-3 z-20 flex items-center gap-2 px-3 py-1.5 rounded-lg border border-bunker-700 bg-bunker-900/90 backdrop-blur font-mono text-xs text-bunker-muted pointer-events-none">
                    <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" />
                    MUM KAPANIŞ: <span className="text-neon-green font-bold tabular-nums">
                        {String(Math.floor(countdown / 60000)).padStart(2, "0")}:{String(Math.floor((countdown % 60000) / 1000)).padStart(2, "0")}
                    </span>
                </div>
            </div>

            {/* tüm açık pozisyonlar: giriş zamanı, fiyatı ve dinamik PnL */}
            <div className="card bg-bunker-950 border border-bunker-800">
                <div className="flex items-center justify-between px-4 py-2 border-b border-bunker-800">
                    <h2 className="font-mono text-sm font-bold text-neon-green">AÇIK POZİSYONLAR</h2>
                    <span className="font-mono text-xs text-bunker-muted">{positions.length} pozisyon</span>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm font-mono">
                        <thead>
                            <tr className="text-left text-bunker-muted text-xs border-b border-bunker-800">
                                <th className="px-4 py-2">SEMBOL</th>
                                <th className="px-4 py-2">GİRİŞ ZAMANI</th>
                                <th className="px-4 py-2">GİRİŞ</th>
                                <th className="px-4 py-2">GÜNCEL</th>
                                <th className="px-4 py-2">MİKTAR</th>
                                <th className="px-4 py-2 text-right">PnL</th>
                            </tr>
                        </thead>
                        <tbody>
                            {positions.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="px-4 py-5 text-center text-bunker-muted">Açık pozisyon yok</td>
                                </tr>
                            ) : (
                                positions.map((p) => {
                                    const pnl = p.pnl_pct ?? 0;
                                    const pnlTry = p.pnl_try ?? 0;
                                    const time = p.entry_time
                                        ? new Date(p.entry_time * 1000).toLocaleTimeString("tr-TR")
                                        : "-";
                                    return (
                                        <tr key={p.symbol} className="border-b border-bunker-800/50 hover:bg-bunker-900/50">
                                            <td className="px-4 py-2 text-white font-bold">{p.symbol}</td>
                                            <td className="px-4 py-2 text-bunker-muted">{time}</td>
                                            <td className="px-4 py-2 text-bunker-muted">{p.entry?.toFixed?.(4) ?? p.entry}</td>
                                            <td className="px-4 py-2 text-white">{p.current?.toFixed?.(4) ?? p.current}</td>
                                            <td className="px-4 py-2 text-bunker-muted">{p.quantity?.toFixed?.(4) ?? p.quantity}</td>
                                            <td className={`px-4 py-2 text-right font-bold ${pnl >= 0 ? "text-neon-green" : "text-red-400"}`}>
                                                <div>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%</div>
                                                <div className="text-xs mt-1">{pnlTry >= 0 ? "+" : ""}₺{pnlTry.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            <p className="text-xs text-bunker-muted font-mono">
                {symbol} · {interval} periyodu · mumlar UTC — bot 1m kline kullanır, analiz zaman dilimiyle birebir uyumlu
            </p>

            {picking && <IndicatorPicker onSelect={(e) => { setPicking(false); setEditTarget({ entry: e }); }} onClose={() => setPicking(false)} />}
            {editTarget && (
                <IndicatorSettings
                    entry={editTarget.entry}
                    initialParams={editTarget.editUid ? instances.find((i) => i.uid === editTarget.editUid)?.params : undefined}
                    initialStyle={editTarget.editUid ? instances.find((i) => i.uid === editTarget.editUid)?.style : undefined}
                    editing={!!editTarget.editUid}
                    onAdd={(params, style) =>
                        editTarget.editUid
                            ? updateIndicator(editTarget.editUid, params, style)
                            : addIndicator(editTarget.entry, params, style)
                    }
                    onClose={() => setEditTarget(null)}
                />
            )}
        </div>
    );
}
