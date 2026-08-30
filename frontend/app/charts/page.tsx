"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { API_BASE, apiRequest } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import SymbolLink from "../components/SymbolLink";
import {
    createChart, createSeriesMarkers, CandlestickSeries, LineSeries, HistogramSeries,
    IChartApi, ISeriesApi, IPriceLine, UTCTimestamp, Time
} from "lightweight-charts";
import IndicatorPicker, { filterIndicatorInstances, findIndicatorEntry } from "./IndicatorPicker";
import IndicatorSettings from "./IndicatorSettings";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "./types";
import {
    FALLBACK_SYMBOLS, INTERVALS, INTERVAL_MS, PALETTE, TOTAL_HEIGHT, MAIN_MIN,
    uid, clamp, LS_SYMBOL, LS_INTERVAL, LS_INDICATORS, LS_PANE_HEIGHTS, LS_DISPLAY_SETTINGS, API,
    paneMinimumHeight, preferredChartHeight, computePaneLayout,
    formatPrice, chartPriceFormat, loadPersisted,
    DEFAULT_STYLE, DEFAULT_INSTANCES, loadIndicators,
    strategyLabelFor, macdHistogramColor,
    type DisplaySettings, type EditTarget, type LivePortfolio, type PortfolioMetrics, type TimeframeTrend,
} from "./chartShared";
import {
    strongCandlestickPatterns, patternDescriptions, utBotSignals, bbSqueezeSignals, emaPullbackSignals,
    vwapMacdSignals, cmoCrsiSignals, rsiLast, mfiLast, obvLast, spotExecutionSignals,
    strategySignalFns, strategyColors, strategyLabels, type Bar, type PatternMarker,
} from "./signals";



export default function ChartsPage() {
    const searchParams = useSearchParams();
    const [symbol, setSymbol] = useState<string>("BTCTRY");
    const [symbols, setSymbols] = useState<string[]>(FALLBACK_SYMBOLS);
    const [analysisOpen, setAnalysisOpen] = useState(false);
    const [interval, setTf] = useState<string>("5m");
    const [activeStrategy, setActiveStrategy] = useState<string>("BB_MFI_MEAN_REVERSION");
    const [loading, setLoading] = useState(true);
    const [bars, setBars] = useState<Bar[]>([]);
    const [instances, setInstances] = useState<IndicatorInstance[]>(DEFAULT_INSTANCES);
    const [picking, setPicking] = useState(false);
    const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
    const [volumeVisible, setVolumeVisible] = useState(false);
    const [countdown, setCountdown] = useState<number>(0);
    const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
    const [showPositions, setShowPositions] = useState(false);
    const [showStopTakeProfit, setShowStopTakeProfit] = useState(false);
    const [showPatterns, setShowPatterns] = useState(false);
    const [showStrategySignals, setShowStrategySignals] = useState(false);
    const [showPressure, setShowPressure] = useState(true);
    const [m5Bars, setM5Bars] = useState<Bar[]>([]);
    const [chartSettingsOpen, setChartSettingsOpen] = useState(false);
    const [patternTooltip, setPatternTooltip] = useState<{ x: number; y: number; pattern: PatternMarker } | null>(null);
    const [positions, setPositions] = useState<any[]>([]);
    const [livePortfolio, setLivePortfolio] = useState<LivePortfolio | null>(null);
    const [portfolioMetrics, setPortfolioMetrics] = useState<PortfolioMetrics | null>(null);
    const [timeframeTrends, setTimeframeTrends] = useState<TimeframeTrend[]>([]);
    const chartHeightRef = useRef(TOTAL_HEIGHT);
    const positionLinesRef = useRef<Map<string, IPriceLine[]>>(new Map());
    const positionMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const utBotMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const patternMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const activeStrategyMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
    const [visibleRange, setVisibleRange] = useState<{ from: number; to: number } | null>(null);

    // localStorage yükleme: hydration uyumluluğu için client tarafında yap
    useEffect(() => {
        const querySymbol = searchParams.get("symbol")?.replace(/_/g, "").toUpperCase() || "";
        const savedSymbol = querySymbol || loadPersisted(LS_SYMBOL, "BTCTRY");
        const savedInterval = querySymbol ? "5m" : loadPersisted(LS_INTERVAL, "5m");
        setSymbol(savedSymbol);
        setTf(savedInterval);
        apiRequest(`${API_BASE}/api/config`).then((r) => r.json()).then((d) => {
            const active = Array.isArray(d.symbols) && d.symbols.length ? d.symbols : FALLBACK_SYMBOLS;
            const available = [...new Set([...active, ...(querySymbol ? [querySymbol] : [])])].sort((a, b) => a.localeCompare(b));
            setSymbols(available);
            setSymbol((current) => available.includes(current) ? current : active[0]);
            const configuredStrategy = String(d.active_strategy || "BB_MFI_MEAN_REVERSION").toUpperCase();
            setActiveStrategy(configuredStrategy);
            setInstances(filterIndicatorInstances(loadIndicators(), configuredStrategy));
            loadFromDb(savedSymbol, configuredStrategy);
        }).catch(() => {
            setSymbols(FALLBACK_SYMBOLS);
            setInstances(filterIndicatorInstances(loadIndicators(), "BB_MFI_MEAN_REVERSION"));
            loadFromDb(savedSymbol, "BB_MFI_MEAN_REVERSION");
        });
    // İlk yüklemede query değeri kullanılır; sonraki Link yönlendirmeleri
    // aşağıdaki effect tarafından state'e aktarılır.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const settings = loadPersisted<DisplaySettings>(LS_DISPLAY_SETTINGS, {
            showPositions: false, showStopTakeProfit: false, showPatterns: false, showStrategySignals: false,
            showPressure: true
        });
        setShowPositions(settings.showPositions);
        setShowStopTakeProfit(settings.showStopTakeProfit);
        setShowPatterns(settings.showPatterns);
        setShowStrategySignals(!!settings.showStrategySignals);
        setShowPressure(settings.showPressure !== false);
    }, []);

    useEffect(() => {
        try {
            localStorage.setItem(LS_DISPLAY_SETTINGS, JSON.stringify({ showPositions, showStopTakeProfit, showPatterns, showStrategySignals, showPressure } satisfies DisplaySettings));
        } catch { /* görüntü ayarı yalnızca yerelde saklanır */ }
    }, [showPositions, showStopTakeProfit, showPatterns, showStrategySignals, showPressure]);

    // Sembol rozeti /charts?symbol=...&timeframe=5m ile istemci içi
    // yönlendirme yapar. Sayfa unmount olmadığı için URL değişimini ayrıca
    // dinlemek gerekir; aksi halde yalnız tam sayfa yenilemesinde çalışırdı.
    useEffect(() => {
        const requestedSymbol = searchParams.get("symbol")?.replace(/_/g, "").toUpperCase();
        if (!requestedSymbol) return;
        const requestedTimeframe = searchParams.get("timeframe");
        const targetTimeframe = requestedTimeframe && INTERVAL_MS[requestedTimeframe] ? requestedTimeframe : "5m";
        setSymbols((current) => current.includes(requestedSymbol)
            ? current
            : [...current, requestedSymbol].sort((left, right) => left.localeCompare(right)));
        setSymbol(requestedSymbol);
        setTf(targetTimeframe);
        localStorage.setItem(LS_SYMBOL, JSON.stringify(requestedSymbol));
        localStorage.setItem(LS_INTERVAL, JSON.stringify(targetTimeframe));
        loadFromDb(requestedSymbol, activeStrategy, targetTimeframe);
        // loadFromDb is intentionally invoked only when the route query changes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchParams]);

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
        const onVisibleRangeChange = (range: { from: number; to: number } | null) => setVisibleRange(range);
        chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);

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
            const compact = window.innerWidth < 768;
            const keys = [...paneKeyByIndexRef.current.entries()]
                .sort(([left], [right]) => left - right)
                .map(([, key]) => key);
            if (!keys.length) {
                chartHeightRef.current = preferredChartHeight(MAIN_MIN, compact);
            } else {
                // mevcut pane yüksekliklerini koruyarak ekran bütçesine göre yeniden dağıt
                const current: Record<string, number> = {};
                chartRef.current.panes().forEach((p, i) => { current[keys[i] || String(i)] = p.getHeight(); });
                const layout = computePaneLayout(keys, current, compact);
                chartHeightRef.current = layout.total;
                layout.heights.forEach((h, i) => chartRef.current!.panes()[i]?.setHeight(h));
            }
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: chartHeightRef.current });
        });
        ro.observe(containerRef.current);

        return () => {
            clearInterval(saveTimer);
            ro.disconnect();
            chart.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
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
                const res = await apiRequest(`${API_BASE}/api/market-klines/${symbol}?interval=${interval}&limit=200`);
                const payload = await res.json();
                const data = payload.candles || [];
                if (cancelled || !candleRef.current) return;
                const candles: Bar[] = data.map((k: number[]) => ({
                    time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]
                }));
                setBars(candles);
                candleRef.current.setData(candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
                const last = candles[candles.length - 1]?.close ?? 0;
                candleRef.current.applyOptions({ priceFormat: chartPriceFormat(last) });
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

    // Strateji işaretleri görüntülenen periyottan bağımsız olarak M5 kaynağından
    // hesaplanır. Böylece 1s/4s görünümde de aynı M5 strateji ayarı korunur.
    useEffect(() => {
        let cancelled = false;
        apiRequest(`${API_BASE}/api/market-klines/${symbol}?interval=5m&limit=500`)
            .then((res) => res.json())
            .then((payload) => {
                if (cancelled) return;
                setM5Bars((payload.candles || []).map((k: number[]) => ({
                    time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]
                })));
            }).catch(() => { if (!cancelled) setM5Bars([]); });
        return () => { cancelled = true; };
    }, [symbol]);

    // canlı mum güncelleme: Binance WebSocket'ten seçili sembolün kline'ını dinle
    useEffect(() => {
        let ws: WebSocket | null = null;
        let retryTimer: ReturnType<typeof setTimeout> | null = null;
        let attempt = 0;
        let closed = false;
        const connect = () => {
            if (closed) return;

            ws = new WebSocket(`wss://stream-cloud.binance.tr/ws/${symbol.toLowerCase()}@kline_${interval}`);
            ws.onclose = () => {
                if (!closed) {
                    attempt += 1;
                    retryTimer = setTimeout(connect, Math.min(30_000, 2_000 * 2 ** Math.min(attempt, 4)) + Math.random() * 1_000);
                }
            };

            ws.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data);
                const k = msg.k;
                if (!k) return;
                const bar: Bar = {
                    time: Math.floor(k.t / 1000),
                    open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v
                };
                // Fiyat, eşik aralıklarından birini geçerse sağ ölçeğin
                // hassasiyeti de canlı olarak aynı kurala geçsin.
                candleRef.current?.applyOptions({ priceFormat: chartPriceFormat(bar.close) });
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
        };
        connect();
        return () => {
            closed = true;
            if (retryTimer) clearTimeout(retryTimer);
            ws?.close();
        };
    }, [symbol, interval]);

    // WebSocket anlık portföyü taşır; HTTP yalnızca bağlantı kopması için
    // düşük frekanslı geri dönüş yoludur. Manuel kapatma sonrası da buradan
    // tazelenir.
    const fetchPositions = useCallback(async () => {
        try {
            const res = await apiRequest(`${API_BASE}/api/positions`);
            // Hata yanıtı (401/5xx) pozisyon listesini SIFIRLAMAMALI: daha
            // önce `data.positions || []` her yanıtta uygulandığı için bir
            // başarısız REST çağrısı WS'ten gelen listeyi siliyor ve tablo
            // "Açık pozisyon yok" gösteriyordu. Başarılı yanıtta da yalnızca
            // positions alanı gerçekten dizi ise güncelle; aksi halde mevcut
            // liste korunur.
            if (!res.ok) return;
            const data = await res.json();
            if (Array.isArray(data?.positions)) setPositions(data.positions);
        } catch { /* backend yoksa sessiz geç; mevcut liste korunur */ }
    }, []);

    useEffect(() => {
        fetchPositions();
        const t = setInterval(fetchPositions, 30_000);
        return () => clearInterval(t);
    }, [fetchPositions]);

    const loadPortfolioSummary = useCallback(async () => {
        try {
            const response = await apiRequest(`${API_BASE}/api/portfolio/summary`);
            const result = await response.json();
            if (result.portfolio && Object.keys(result.portfolio).length) setLivePortfolio(result.portfolio as LivePortfolio);
            if (result.metrics) setPortfolioMetrics(result.metrics as PortfolioMetrics);
        } catch { /* özet için portföy metrikleri geçici olarak kullanılamıyor */ }
    }, []);

    useEffect(() => {
        loadPortfolioSummary();
        const timer = setInterval(loadPortfolioSummary, 30_000);
        return () => clearInterval(timer);
    }, [loadPortfolioSummary]);

    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            try {
                const response = await apiRequest(`${API_BASE}/api/chart/${encodeURIComponent(symbol)}/timeframe-trends`);
                const result = await response.json();
                if (!cancelled) setTimeframeTrends(Array.isArray(result.timeframes) ? result.timeframes : []);
            } catch {
                if (!cancelled) setTimeframeTrends([]);
            }
        };
        load();
        const timer = setInterval(load, 20_000);
        return () => { cancelled = true; clearInterval(timer); };
    }, [symbol]);

    useLiveMessages(useCallback((message: any) => {
        if (message.type === "portfolio") {
            setLivePortfolio(message.data as LivePortfolio);
            // WS portfolio'da positions alanı eksikse mevcut REST listesini
            // boşaltma; alan varsa (dizi) güncelle.
            if (Array.isArray(message.data?.positions)) {
                setPositions(message.data.positions);
            }
        }
        if (["trade_updated", "signal", "reset"].includes(message.type)) loadPortfolioSummary();
    }, [loadPortfolioSummary]));

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

        // HACİM pane'i (isteğe bağlı)
        if (volumeVisible) {
            const volData = bars.map((b) => ({
                time: b.time as UTCTimestamp,
                value: b.volume,
                color: b.close >= b.open ? "rgba(16,185,129,0.45)" : "rgba(239,68,68,0.45)"
            }));
            const volumeSeries = chart.addSeries(HistogramSeries, {
                priceLineVisible: false, lastValueVisible: false
            }, paneIdx);
            volumeSeries.setData(volData);
            volumeRef.current = volumeSeries;
            volumePaneIndexRef.current = paneIdx;
            chart.priceScale("right", paneIdx).applyOptions({ scaleMargins: { top: 0.25, bottom: 0.02 } });
            paneIdx++;
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
                // çizgi başına stil: lineWidths yoksa tüm çizgiler lineWidth kullanır
                const widthFor = (pi: number) =>
                    (style.lineWidths?.[pi] ?? style.lineWidth) as 1 | 2 | 3 | 4;
                const arr = plots.map((plot, pi) => {
                    const lastPoint = [...plot].reverse().find((p) => p.value != null && !Number.isNaN(p.value));
                    const s = chart.addSeries(LineSeries, {
                        color: style.colors[pi] || PALETTE[pi % PALETTE.length],
                        lineWidth: widthFor(pi),
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
                const isMacd = inst.registryId === "macd";
                // min/max bantları: 3+ plotlu indikatörlerde son plotlar banttır (RSI 30/70 gibi)
                const boundStart = isHisto ? 3 : Math.min(plots.length, 2);
                const arr: (ISeriesApi<"Line"> | ISeriesApi<"Histogram">)[] = [];
                const manualBounds = [
                    ...(style.minValue != null ? [{ value: style.minValue, color: style.colors[1] || PALETTE[1] }] : []),
                    ...(style.maxValue != null ? [{ value: style.maxValue, color: style.colors[2] || PALETTE[2] }] : [])
                ];
                plots.forEach((plot, pi) => {
                    const widthFor = (idx: number) =>
                        (style.lineWidths?.[idx] ?? style.lineWidth) as 1 | 2 | 3 | 4;
                    const numericPoints = plot.filter((p) => p.value != null && !Number.isNaN(p.value));
                    const data = numericPoints.map((p, index) => {
                        const value = p.value as number;
                        const color = isMacd && isHisto && pi === 0
                            ? macdHistogramColor(value, numericPoints[index - 1]?.value as number | undefined)
                            : p.color; // plot kendi semantik rengini veriyorsa (eşik altı yeşil vb.) ona öncelik ver
                        return {
                            time: p.time as UTCTimestamp,
                            value,
                            ...(color ? { color } : {})
                        };
                    });
                    if (!data.length) return;
                    if (isHisto && pi === 0) {
                        const s = chart.addSeries(HistogramSeries, {
                            color: style.colors[0] || PALETTE[0], base: 0,
                            priceLineVisible: false, lastValueVisible: false
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
                            lineWidth: widthFor(pi), priceLineVisible: style.showPriceLine, lastValueVisible: style.showPriceLine
                        }, paneIdx);
                        s.setData(data);
                        if (style.showPriceLine) {
                            s.applyOptions({ priceLineVisible: true, lastValueVisible: true });
                        }
                        arr.push(s);
                    }
                });
                paneSeries.current.set(inst.uid, arr);
                // Tüm gösterge panellerinde çizginin pane'e yapışmasını engellemek
                // için üst/alt boşluk bırak; MACD ayrıca sıfır merkezli düzen alır.
                chart.priceScale("right", paneIdx).applyOptions({
                    autoScale: true,
                    scaleMargins: { top: 0.12, bottom: 0.12 }
                });
                if (isMacd && arr.length) {
                    // MACD histogram sıfır merkezli olmalı. Varsayılan fiyat
                    // ölçeği küçük histogram değerlerini düzleştirebildiği
                    // için pane'e belirgin bir sıfır çizgisi ve dengeli marj
                    // uygula.
                    chart.priceScale("right", paneIdx).applyOptions({
                        autoScale: true,
                        scaleMargins: { top: 0.12, bottom: 0.12 }
                    });
                    arr[0].createPriceLine({
                        price: 0,
                        color: "rgba(148,163,184,0.65)",
                        lineWidth: 1,
                        lineStyle: 2,
                        axisLabelVisible: false,
                        title: "0"
                    });
                }
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
        // Anahtarları GERÇEKTEN oluşturulan pane'lerden türet: hesaplanamayan
        // (plot üretemeyen) indikatörler pane açmaz; hepsi için anahtar üretmek
        // kayıtlı yüksekliklerin yanlış pane'lere uygulanmasına yol açar.
        const paneKeys: string[] = ["main"];
        if (volumeVisible) paneKeys.push("volume");
        [...instPanes.entries()].sort(([, a], [, b]) => a - b).forEach(([key]) => paneKeys.push(key));
        // Kaydedilmiş yükseklikleri koru, ancak eski 44/56px kayıtları okunabilir
        // minimumun altına inemesin. Gerekirse canvas büyür; panel sıkışmaz.
        // skipHeight: bars canlı güncellenirken kullanıcı sürüklemesi korunur.
        if (!skipHeight) {
            const compact = typeof window !== "undefined" && window.innerWidth < 768;
            const layout = computePaneLayout(paneKeys, paneHeightsRef.current, compact);
            chartHeightRef.current = layout.total;
            chart.applyOptions({ height: layout.total });
            chart.panes().forEach((p, i) => {
                const key = paneKeys[i] || `pane${i}`;
                paneKeyByIndexRef.current.set(i, key);
                p.setHeight(layout.heights[i] ?? paneMinimumHeight(key, compact));
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
        if (showPositions) addLine(pos.entry, "#10b981", `GİRİŞ ${formatPrice(pos.entry)}`);
        if (showStopTakeProfit) {
            const stop = pos.llm_stop_price ?? pos.stop;
            const takeProfit = pos.llm_take_profit_price ?? pos.take_profit;
            addLine(stop, "#ef4444", `SL ${formatPrice(stop)}`);
            addLine(takeProfit, "#3b82f6", `TP ${formatPrice(takeProfit)}`);
        }
        if (lines.length) positionLinesRef.current.set(symbol, lines);

        // giriş noktasına marker ekle (v5 createSeriesMarkers)
        if (!showPositions) return;
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
    }, [showPositions, showStopTakeProfit, positions, symbol, bars, interval]);

    // BB-MFI stratejisinin backend ile aynı dip koşulunu marker olarak göster.

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

    // Aktif stratejinin M5 sinyalleri, seçili grafik periyoduna yuvarlanarak
    // her görünümde gösterilir; hesap kaynağı daima M5 kalır.
    useEffect(() => {
        activeStrategyMarkersRef.current?.setMarkers([]);
        activeStrategyMarkersRef.current = null;
        if (!showStrategySignals || !bars.length || !m5Bars.length || !candleRef.current) return;
        const strategyKey = activeStrategy.toLowerCase();
        const signalFn = strategySignalFns[strategyKey];
        if (!signalFn) return;
        const range = visibleRange || { from: 0, to: bars.length - 1 };
        const firstVisibleIndex = Math.max(0, Math.floor(range.from));
        const lastVisibleIndex = Math.min(bars.length - 1, Math.ceil(range.to));
        // İşaretin tam olarak görüntülenen muma ait olması için sinyalleri
        // indeks aralığı üzerinden daraltıyoruz; strateji ise gerekli ısınma
        // geçmişini koruyarak tüm M5 serisinde değerlendirilir.
        const visibleTimes = new Set(bars.slice(firstVisibleIndex, lastVisibleIndex + 1).map((bar) => bar.time));
        const targetSeconds = (INTERVAL_MS[interval] || 300_000) / 1000;
        const mapped = new Map<number, { time: number; type: "buy" | "sell" }>();
        signalFn(m5Bars.slice(0, -1), {}).forEach((signal) => {
            const targetTime = Math.floor(signal.time / targetSeconds) * targetSeconds;
            if (visibleTimes.has(targetTime)) mapped.set(targetTime, { ...signal, time: targetTime });
        });
        const signals = [...mapped.values()];
        try {
            const markers = createSeriesMarkers(candleRef.current, []);
            activeStrategyMarkersRef.current = markers;
            markers.setMarkers(signals.map((signal) => ({
                time: signal.time as UTCTimestamp,
                position: signal.type === "buy" ? "belowBar" as const : "aboveBar" as const,
                color: signal.type === "buy" ? "#2563eb" : "#f97316",
                shape: signal.type === "buy" ? "circle" as const : "circle" as const,
                text: signal.type === "buy" ? "M5 B" : "M5 S",
                size: 1,
            })));
        } catch { /* görünür zaman aralığı değişirken marker dışarıda kalabilir */ }
    }, [showStrategySignals, interval, activeStrategy, bars, m5Bars, visibleRange]);

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
                // Boğa/yükseliş yeşil, ayı/düşüş kırmızı.
                color: p.type === "buy" ? "#10b981" : "#ef4444",
                shape: p.type === "buy" ? "arrowUp" : "arrowDown",
                text: p.type === "buy" ? "↑" : "↓",
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
            volumeVisible,
            display: { showPositions, showStopTakeProfit, showPatterns, showStrategySignals, showPressure } satisfies DisplaySettings
        };
        try {
            await apiRequest(`${API}/${symbol}`, {
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
    const loadFromDb = async (s: string, strategy = activeStrategy, forcedInterval?: string) => {
        try {
            const res = await apiRequest(`${API}/${s}`);
            const data = await res.json();
            const st = data?.settings;
            if (!st) return;
            const resolvedInterval = forcedInterval || st.interval || "5m";
            setTf(resolvedInterval);
            localStorage.setItem(LS_INTERVAL, JSON.stringify(resolvedInterval));
            if (st.indicators?.length) {
                const filteredIndicators = filterIndicatorInstances(st.indicators as IndicatorInstance[], strategy);
                setInstances(filteredIndicators);
                localStorage.setItem(LS_INDICATORS, JSON.stringify(filteredIndicators));
            }
            if (st.paneHeights) {
                paneHeightsRef.current = st.paneHeights;
                try { localStorage.setItem(LS_PANE_HEIGHTS, JSON.stringify(st.paneHeights)); } catch { }
            }
            if (typeof st.volumeVisible === "boolean") setVolumeVisible(st.volumeVisible);
            if (typeof st.display?.showPositions === "boolean") setShowPositions(st.display.showPositions);
            if (typeof st.display?.showStopTakeProfit === "boolean") setShowStopTakeProfit(st.display.showStopTakeProfit);
            if (typeof st.display?.showPatterns === "boolean") setShowPatterns(st.display.showPatterns);
            if (typeof st.display?.showStrategySignals === "boolean") setShowStrategySignals(st.display.showStrategySignals);
            if (typeof st.display?.showPressure === "boolean") setShowPressure(st.display.showPressure);
        } catch { /* backend yoksa localStorage kullan */ }
    };

    const [closingSymbol, setClosingSymbol] = useState<string | null>(null);
    const closePositionManually = async (sym: string) => {
        if (closingSymbol) return;
        setClosingSymbol(sym);
        try {
            const res = await apiRequest(`${API_BASE}/api/positions/${encodeURIComponent(sym)}/close`, { method: "POST" });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data?.message || "kapatma başarısız");
            // pozisyon listesi WS "signal" yayınıyla da tazelenir; burada emin olmak için çek
            await fetchPositions();
            loadPortfolioSummary();
        } catch (err: any) {
            console.error("manuel kapatma hatası:", err);
            alert(`${sym} kapatılamadı: ${err?.message || "bilinmeyen hata"}`);
        } finally {
            setClosingSymbol(null);
        }
    };

    const openPnl = livePortfolio?.unrealized_pnl ?? positions.reduce((total, position) => total + Number(position.pnl_try || 0), 0);
    const netPnl = portfolioMetrics?.net_pnl ?? 0;
    const winRate = portfolioMetrics?.win_rate ?? 0;
    const money = (value: number) => `₺${value.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    const pnlClass = (value: number) => value >= 0 ? "text-neon-green" : "text-red-400";
    const pressure = (() => {
        const recent = bars.slice(-8);
        if (recent.length < 2) return 0;
        const weighted = recent.reduce((sum, bar) => {
            const range = Math.max(bar.high - bar.low, Number.EPSILON);
            return sum + (((bar.close - bar.low) / range) * 2 - 1) * bar.volume;
        }, 0);
        const volume = recent.reduce((sum, bar) => sum + bar.volume, 0);
        return clamp(volume ? (weighted / volume) * 100 : 0, -100, 100);
    })();

    // Grafik altı gösterge şeridi: seçili zaman diliminin son mumlarından
    // hesaplanır. bars WebSocket ile güncellendikçe bu memo da yeniden çalışır,
    // böylece değerler mumla birlikte canlı tazelenir.
    const strip = useMemo(() => ({
        rsi: rsiLast(bars, 14),
        mfi: mfiLast(bars, 14),
        obv: obvLast(bars)
    }), [bars]);

    const obvCompact = (value: number) => {
        const abs = Math.abs(value);
        if (abs >= 1e9) return `${(value / 1e9).toLocaleString("tr-TR", { maximumFractionDigits: 2 })} Mr`;
        if (abs >= 1e6) return `${(value / 1e6).toLocaleString("tr-TR", { maximumFractionDigits: 2 })} Mn`;
        if (abs >= 1e3) return `${(value / 1e3).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} B`;
        return value.toLocaleString("tr-TR", { maximumFractionDigits: 0 });
    };
    const num1 = (value: number | null) => value == null ? "—" : value.toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    // RSI/MFI bölge etiketi: aşırı bölgelerde renk değişir, nötrde beyaz kalır.
    const zoneClass = (value: number | null, oversold: number, overbought: number) =>
        value == null ? "text-bunker-muted" : value <= oversold ? "text-neon-green" : value >= overbought ? "text-red-400" : "text-white";
    const zoneLabel = (value: number | null, oversold: number, overbought: number) =>
        value == null ? "VERİ YOK" : value <= oversold ? "AŞIRI SATIM" : value >= overbought ? "AŞIRI ALIM" : "NÖTR";

    return (
        <div className="max-w-7xl mx-auto space-y-5">
            <header className="chart-page-header flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h1 className="font-mono text-xl font-bold tracking-tight">
                        <span className="text-neon-green">GRAFİK</span> TERMİNALİ
                    </h1>
                    <p className="eyebrow mt-1">Binance public API · son 200 mum</p>
                </div>
                <div className="chart-toolbar w-full lg:w-auto flex flex-wrap items-center gap-2 sm:gap-3">
                    <select
                        value={symbol}
                        onChange={(e) => changeSymbol(e.target.value)}
                        className="chart-symbol-select bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                    >
                        {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button
                        type="button"
                        onClick={() => setAnalysisOpen(true)}
                        className="px-3 py-2 rounded-lg border border-yellow-400/50 bg-yellow-400/10 font-mono text-xs text-yellow-300 hover:bg-yellow-400/20"
                    >
                        🔬 ANALİZ
                    </button>
                    <div className="chart-intervals max-w-full overflow-x-auto flex rounded-lg border border-bunker-700">
                        {INTERVALS.map((i) => (
                            <button
                                key={i.v}
                                onClick={() => changeInterval(i.v)}
                                className={`chart-interval-button px-3 py-2 font-mono text-xs transition-colors ${interval === i.v ? "bg-neon-green/15 text-neon-green" : "bg-bunker-900 text-bunker-muted hover:text-white"}`}
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
                </div>
            </header>

            <section aria-label="Portföy özeti" className="grid grid-cols-2 gap-2 rounded-xl border border-bunker-800 bg-bunker-950/80 p-3 sm:grid-cols-5">
                <div className="min-w-0"><p className="eyebrow">TOPLAM PORTFÖY</p><p className="mt-1 truncate font-mono text-sm font-bold text-white">{livePortfolio?.total_value == null ? "—" : money(livePortfolio.total_value)}</p></div>
                <div className="min-w-0"><p className="eyebrow">AÇIK PnL</p><p className={`mt-1 truncate font-mono text-sm font-bold ${pnlClass(openPnl)}`}>{openPnl >= 0 ? "+" : ""}{money(openPnl)}</p></div>
                <div className="min-w-0"><p className="eyebrow">KAPANAN İŞLEM</p><p className="mt-1 font-mono text-sm font-bold text-white">{portfolioMetrics?.closed_trades ?? "—"}</p></div>
                <div className="min-w-0"><p className="eyebrow">BAŞARI</p><p className="mt-1 font-mono text-sm font-bold text-white">%{winRate.toFixed(1)}</p></div>
                <div className="min-w-0 col-span-2 sm:col-span-1"><p className="eyebrow">NET PnL</p><p className={`mt-1 truncate font-mono text-sm font-bold ${pnlClass(netPnl)}`}>{netPnl >= 0 ? "+" : ""}{money(netPnl)}</p></div>
            </section>

            <section aria-label="Zaman dilimi trend durumu" className="flex flex-wrap items-stretch gap-2 rounded-xl border border-bunker-800 bg-bunker-950/80 p-3">
                <p className="flex items-center pr-1 font-mono text-[10px] font-bold tracking-wider text-bunker-muted">TF YÖNÜ<br />KAPANMIŞ MUM</p>
                {INTERVALS.map(({ v, l }) => {
                    const trend = timeframeTrends.find((item) => item.timeframe === v);
                    const direction = trend?.alignment ?? "unknown";
                    const tone = direction === "bullish" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : direction === "bearish" ? "border-red-400/40 bg-red-400/10 text-red-400" : direction === "mixed" ? "border-yellow-400/35 bg-yellow-400/10 text-yellow-300" : "border-bunker-700 bg-bunker-900/60 text-bunker-muted";
                    const arrow = direction === "bullish" ? "↑" : direction === "bearish" ? "↓" : "—";
                    const label = direction === "bullish" ? "BULLISH" : direction === "bearish" ? "BEARISH" : direction === "mixed" ? "KARIŞIK" : "VERİ YOK";
                    return <div key={v} title={`${l}: ${label}`} className={`min-w-[58px] rounded-lg border px-2 py-1.5 text-center font-mono ${tone}`}><p className="text-[10px] font-bold">{l}</p><p className="mt-0.5 text-lg font-bold leading-5" aria-label={label}>{arrow}</p></div>;
                })}
            </section>

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

            {analysisOpen && <div className="fixed inset-0 z-[90] grid place-items-center bg-black/75 p-3 sm:p-6" onClick={() => setAnalysisOpen(false)}>
                <section className="w-full max-w-7xl h-[92vh] overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="symbol-analysis-modal-title">
                    <div className="flex items-center justify-between border-b border-bunker-800 px-4 py-3">
                        <h2 id="symbol-analysis-modal-title" className="font-mono text-sm font-bold text-white"><SymbolLink symbol={symbol} className="text-neon-green hover:text-white" /> · SEMBOL ANALİZİ</h2>
                        <button type="button" onClick={() => setAnalysisOpen(false)} className="px-3 py-1 text-bunker-muted hover:text-white" aria-label="Sembol analizini kapat">✕</button>
                    </div>
                    <iframe title={`${symbol} sembol analizi`} src={`/symbol-analysis?symbol=${encodeURIComponent(symbol)}&embedded=1`} className="h-[calc(92vh-52px)] w-full border-0" />
                </section>
            </div>}

            {chartSettingsOpen && <div className="fixed inset-0 z-[90] grid place-items-center bg-black/75 p-3 sm:p-6" onClick={() => setChartSettingsOpen(false)}>
                <section className="flex max-h-[86vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="chart-settings-modal-title">
                    <div className="flex shrink-0 items-center justify-between border-b border-bunker-800 px-4 py-2.5">
                        <div>
                            <h2 id="chart-settings-modal-title" className="font-mono text-sm font-bold text-white">GRAFİK AYARLARI</h2>
                            <p className="mt-1 text-xs text-bunker-muted"><SymbolLink symbol={symbol} className="text-neon-green" /> · görünüm tercihleri</p>
                        </div>
                        <button type="button" onClick={() => setChartSettingsOpen(false)} className="min-h-10 min-w-10 rounded-lg text-bunker-muted hover:bg-bunker-900 hover:text-white" aria-label="Grafik ayarlarını kapat">✕</button>
                    </div>
                    <div className="grid grid-cols-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2">
                        {[
                            { checked: volumeVisible, setChecked: setVolumeVisible, title: "Hacim paneli", description: "Hacim mumlarını göster." },
                            { checked: showPositions, setChecked: setShowPositions, title: "Pozisyonlar", description: "Giriş çizgisi ve işareti." },
                            { checked: showStopTakeProfit, setChecked: setShowStopTakeProfit, title: "SL / TP", description: "Kayıtlı hedef ve stop seviyeleri." },
                            { checked: showPatterns, setChecked: setShowPatterns, title: "Formasyonlar", description: "Teyitli mum formasyonları." },
                            { checked: showPressure, setChecked: setShowPressure, title: "Alıcı / satıcı basıncı", description: "Merkez-sıfırlı canlı basınç bandı." },
                            { checked: showStrategySignals, setChecked: setShowStrategySignals, title: "M5 strateji sinyalleri", description: "Tüm zaman dilimlerinde M5 kaynaklı işaretler." },
                        ].map((setting) => (
                            <button
                                key={setting.title}
                                type="button"
                                role="switch"
                                aria-checked={setting.checked}
                                onClick={() => setting.setChecked(!setting.checked)}
                                className="flex w-full items-center gap-2.5 rounded-lg border border-bunker-800 bg-bunker-900/50 p-2.5 text-left transition-colors hover:border-bunker-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neon-green/70"
                            >
                                <span className={`relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors ${setting.checked ? "bg-neon-green" : "bg-bunker-700"}`} aria-hidden="true">
                                    <span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${setting.checked ? "translate-x-6" : "translate-x-1"}`} />
                                </span>
                                <span className="min-w-0"><span className="block font-mono text-xs font-bold text-white">{setting.title}</span><span className="mt-0.5 block text-[11px] leading-4 text-bunker-muted">{setting.description}</span></span>
                            </button>
                        ))}
                    </div>
                </section>
            </div>}

            {showPressure && <section className="rounded-xl border border-bunker-800 bg-bunker-950/95 px-3 py-2.5 sm:px-4" aria-label="Alıcı satıcı basıncı">
                    <div className="mb-1.5 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider"><span className={pressure < 0 ? "text-red-400" : "text-bunker-muted"}>SATICI %{Math.max(0, 50 - pressure / 2).toFixed(0)}</span><span className="text-bunker-muted">BASINÇ · 0</span><span className={pressure >= 0 ? "text-neon-green" : "text-bunker-muted"}>ALICI %{Math.max(0, 50 + pressure / 2).toFixed(0)}</span></div>
                    <div className="relative h-2 overflow-hidden rounded-full bg-bunker-800"><div className="absolute inset-y-0 left-1/2 w-px bg-white/60" /><div className={`absolute top-0 h-full transition-[width] duration-150 ease-out ${pressure >= 0 ? "left-1/2 bg-neon-green" : "right-1/2 bg-red-400"}`} style={{ width: `${Math.abs(pressure) / 2}%` }} /></div>
                </section>}

            <div className="chart-card card bg-bunker-950 p-0 overflow-hidden relative">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center z-10 bg-bunker-950/70">
                        <p className="font-mono text-sm text-neon-green animate-pulse">YÜKLENİYOR...</p>
                    </div>
                )}
                <div ref={containerRef} className="w-full" />
                {/* gösterge şeridi: grafiğin altına sabitlenmiş, seçili TF'den canlı hesaplanan değerler */}
                <div className="grid grid-cols-3 divide-x divide-bunker-800 border-t border-bunker-800 bg-bunker-950">
                    {([
                        { key: "RSI", value: strip.rsi, text: num1(strip.rsi), zone: zoneLabel(strip.rsi, 30, 70), cls: zoneClass(strip.rsi, 30, 70), hint: "14 periyot · 30/70 eşik" },
                        { key: "MFI", value: strip.mfi, text: num1(strip.mfi), zone: zoneLabel(strip.mfi, 20, 80), cls: zoneClass(strip.mfi, 20, 80), hint: "14 periyot · 20/80 eşik" },
                        { key: "OBV", value: strip.obv.value, text: strip.obv.value == null ? "—" : obvCompact(strip.obv.value), zone: strip.obv.deltaPct == null ? "VERİ YOK" : `${strip.obv.deltaPct >= 0 ? "+" : ""}${strip.obv.deltaPct.toFixed(0)}% / 20 mum`, cls: strip.obv.deltaPct == null ? "text-bunker-muted" : strip.obv.deltaPct >= 0 ? "text-neon-green" : "text-red-400", hint: "birikimli hacim farkı" },
                    ]).map((item) => (
                        <div key={item.key} title={item.hint} className="px-2 py-2 sm:px-4 sm:py-2.5 min-w-0 text-center">
                            <p className="font-mono text-[10px] font-bold tracking-wider text-bunker-muted">{item.key}</p>
                            <p className={`mt-0.5 truncate font-mono text-sm font-bold tabular-nums ${item.cls}`}>{item.text}</p>
                            <p className={`mt-0.5 hidden truncate font-mono text-[10px] tracking-wide sm:block ${item.cls}`}>{item.zone}</p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-bunker-muted">{interval}</p>
                        </div>
                    ))}
                </div>
                {patternTooltip && (
                    <div
                        className={`absolute z-30 w-64 rounded-xl border p-3 shadow-[0_12px_35px_rgba(0,0,0,0.45)] backdrop-blur pointer-events-none ${patternTooltip.pattern.type === "buy" ? "border-emerald-300/60 bg-emerald-950/95" : "border-red-300/60 bg-red-950/95"}`}
                        style={{ left: Math.min(Math.max(patternTooltip.x + 16, 12), 360), top: Math.max(patternTooltip.y - 24, 12) }}
                    >
                        <div className="flex items-center gap-2">
                            <span className={`flex h-6 w-6 items-center justify-center rounded-full border font-mono text-xs font-bold ${patternTooltip.pattern.type === "buy" ? "border-emerald-200 bg-emerald-500/30 text-emerald-50" : "border-red-200 bg-red-500/30 text-red-50"}`}>{patternTooltip.pattern.type === "buy" ? "↑" : "↓"}</span>
                            <span className="font-mono text-xs font-bold text-white">{patternTooltip.pattern.text}</span>
                        </div>
                        <p className="mt-2 text-xs leading-5 text-white/85">{patternDescriptions[patternTooltip.pattern.text]}</p>
                        <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-white/70">{patternTooltip.pattern.type === "buy" ? "↑ Boğa / bullish" : "↓ Ayı / bearish"} · {interval}</p>
                    </div>
                )}
                {/* mum kapanış geri sayımı ve görünüm ayarları: grafiğin sağ üst köşesi */}
                <div className="absolute top-3 right-3 z-20 flex items-center gap-2">
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-bunker-700 bg-bunker-900/90 backdrop-blur font-mono text-xs text-bunker-muted pointer-events-none">
                        <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" />
                        MUM KAPANIŞ: <span className="text-neon-green font-bold tabular-nums">
                            {String(Math.floor(countdown / 60000)).padStart(2, "0")}:{String(Math.floor((countdown % 60000) / 1000)).padStart(2, "0")}
                        </span>
                    </div>
                    <button type="button" onClick={() => setChartSettingsOpen(true)} aria-label="Grafik ayarlarını aç" title="Grafik ayarları" className="grid h-8 w-8 place-items-center rounded-lg border border-bunker-700 bg-bunker-900/90 text-bunker-muted backdrop-blur transition-colors hover:border-neon-green/50 hover:text-neon-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neon-green/70">
                        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current" strokeWidth="2"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" /><path d="m19.4 15 .1.1 1.4 1.1-2 3.4-1.7-.7a7.5 7.5 0 0 1-2.3 1.3L14.6 22h-4l-.3-1.8a7.5 7.5 0 0 1-2.3-1.3l-1.7.7-2-3.4 1.4-1.1.1-.1a7.4 7.4 0 0 1 0-2l-.1-.1-1.4-1.1 2-3.4 1.7.7a7.5 7.5 0 0 1 2.3-1.3l.3-1.8h4l.3 1.8a7.5 7.5 0 0 1 2.3 1.3l1.7-.7 2 3.4-1.4 1.1-.1.1a7.4 7.4 0 0 1 0 2Z" /></svg>
                    </button>
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
                                <th className="px-4 py-2">TUTAR (TL)</th>
                                <th className="px-4 py-2 text-right">PnL</th>
                                <th className="px-3 py-2 text-right" aria-label="Manuel kapatma"><span className="sr-only">Kapat</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            {positions.length === 0 ? (
                                <tr>
                                    <td colSpan={7} className="px-4 py-5 text-center text-bunker-muted">Açık pozisyon yok</td>
                                </tr>
                            ) : (
                                positions.map((p) => {
                                    const pnl = p.pnl_pct ?? 0;
                                    const pnlTry = p.pnl_try ?? 0;
                                    const time = p.entry_time
                                        ? new Date(p.entry_time * 1000).toLocaleTimeString("tr-TR")
                                        : "-";
                                    const entryValue = Number(p.entry || 0) * Number(p.quantity || 0);
                                    return (
                                        <tr key={p.symbol} className="border-b border-bunker-800/50 hover:bg-bunker-900/50">
                                            <td className="px-4 py-2 text-white font-bold"><SymbolLink symbol={p.symbol} className="text-white hover:text-neon-green" />
                                                <div className="mt-1 text-[10px] font-mono text-bunker-muted">{strategyLabelFor(p)}</div>
                                            </td>
                                            <td className="px-4 py-2 text-bunker-muted">{time}</td>
                                            <td className="px-4 py-2 text-bunker-muted">{formatPrice(p.entry)}</td>
                                            <td className="px-4 py-2 text-white">{formatPrice(p.current)}</td>
                                            <td className="px-4 py-2 text-bunker-muted">{entryValue > 0 ? money(entryValue) : "—"}</td>
                                            <td className={`px-4 py-2 text-right font-bold ${pnl >= 0 ? "text-neon-green" : "text-red-400"}`}>
                                                <div>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%</div>
                                                <div className="text-xs mt-1">{pnlTry >= 0 ? "+" : ""}₺{pnlTry.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
                                            </td>
                                            <td className="px-3 py-2 text-right">
                                                <button
                                                    type="button"
                                                    onClick={() => closePositionManually(p.symbol)}
                                                    disabled={closingSymbol != null}
                                                    title={`${p.symbol} pozisyonunu güncel fiyatla kapat`}
                                                    className={`min-h-9 px-3 rounded-lg border font-mono text-xs transition-colors ${closingSymbol === p.symbol
                                                        ? "border-bunker-600 bg-bunker-900 text-bunker-muted animate-pulse"
                                                        : "border-red-400/50 bg-red-400/10 text-red-400 hover:bg-red-400/20 active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed"
                                                        }`}
                                                >
                                                    {closingSymbol === p.symbol ? "KAPATILIYOR…" : "KAPAT"}
                                                </button>
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
                <SymbolLink symbol={symbol} className="text-bunker-muted hover:text-neon-green" /> · {interval} periyodu · mumlar UTC — bot 1m kline kullanır, analiz zaman dilimiyle birebir uyumlu
            </p>

            {picking && <IndicatorPicker activeStrategy={activeStrategy} onSelect={(e) => { setPicking(false); setEditTarget({ entry: e }); }} onClose={() => setPicking(false)} />}
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
