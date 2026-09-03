"use client";
import { useMemo, useState } from "react";
import { indicatorRegistry } from "lightweight-charts-indicators";
import type { RegistryEntry } from "./types";

type Props = {
    onSelect: (entry: RegistryEntry) => void;
    onClose: () => void;
    activeStrategy?: string;
};

export const STRATEGY_INDICATOR_IDS = new Set([
    "ut_bot",
    "bb_squeeze",
    "ema_pullback",
    "vwap_macd",
    "cmo_crsi",
    "bb_mfi_mean_reversion",
    "ema_vwap_pullback",
    "bb_squeeze_orderflow",
    "orderflow",
    "momentum",
    "vwap_mean_reversion",
    "keltner_breakout",
    "chop_trend_filter",
    "donchian_breakout",
]);

const STRATEGY_TO_INDICATOR: Record<string, string> = {
    BB_MFI_MEAN_REVERSION: "bb_mfi_mean_reversion",
    EMA_VWAP_PULLBACK: "ema_vwap_pullback",
    BB_SQUEEZE_ORDERFLOW: "bb_squeeze_orderflow",
    ORDERFLOW: "orderflow",
    MOMENTUM: "momentum",
    VWAP_MEAN_REVERSION: "vwap_mean_reversion",
    KELTNER_BREAKOUT: "keltner_breakout",
    CHOP_TREND_FILTER: "chop_trend_filter",
    DONCHIAN_BREAKOUT: "donchian_breakout",
};

export const activeStrategyIndicatorId = (strategy?: string) =>
    STRATEGY_TO_INDICATOR[String(strategy || "BB_MFI_MEAN_REVERSION").toUpperCase()] || "bb_mfi_mean_reversion";

export const filterIndicatorInstances = <T extends { registryId: string }>(instances: T[], activeStrategy?: string) => {
    const activeId = activeStrategyIndicatorId(activeStrategy);
    return instances.filter((instance) => !STRATEGY_INDICATOR_IDS.has(instance.registryId) || instance.registryId === activeId);
};

// UT Bot özel indikatörü: buy/sell sinyallerini grafikte marker olarak gösterir
export const UT_BOT_ENTRY: RegistryEntry = {
    id: "ut_bot",
    name: "UT Bot Alerts (Buy/Sell)",
    shortName: "UT Bot",
    category: "Strateji",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "keyValue", type: "number", title: "Key Value (a)", defval: 1, min: 0.1, step: 0.1 },
        { id: "atrPeriod", type: "number", title: "ATR Periyodu (c)", defval: 11, min: 2, step: 1 },
        { id: "heikinAshi", type: "bool", title: "Heikin Ashi Mumları", defval: false }
    ],
    calculate: (bars: any[], params: any) => {
        // UT Bot sinyalleri marker olarak çizilir — burada boş plot döner,
        // marker'lar page.tsx'te createSeriesMarkers ile eklenir
        return { metadata: { overlay: true }, plots: {} };
    }
};

// BB Squeeze: Bollinger bandı daralması + hacim patlaması → buy/sell marker
export const BB_SQUEEZE_ENTRY: RegistryEntry = {
    id: "bb_squeeze",
    name: "BB Squeeze Alerts (Buy/Sell)",
    shortName: "BB Squeeze",
    category: "Strateji",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "lookback", type: "number", title: "Squeeze Lookback", defval: 20, min: 10, step: 1 },
        { id: "period", type: "number", title: "BB Periyodu", defval: 20, min: 5, step: 1 },
        { id: "stdDev", type: "number", title: "BB Std Dev", defval: 2, min: 0.5, step: 0.1 },
        { id: "volMult", type: "number", title: "Hacim Çarpanı", defval: 1.5, min: 1, step: 0.1 }
    ],
    calculate: (bars: any[], params: any) => {
        return { metadata: { overlay: true }, plots: {} };
    }
};

// EMA Pullback: EMA9>EMA21>EMA50 trend + EMA21'e pullback + RSI soğuma → buy/sell marker
export const EMA_PULLBACK_ENTRY: RegistryEntry = {
    id: "ema_pullback",
    name: "EMA Pullback Alerts (Buy/Sell)",
    shortName: "EMA Pullback",
    category: "Strateji",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "emaShort", type: "number", title: "EMA Kısa", defval: 9, min: 3, step: 1 },
        { id: "emaMid", type: "number", title: "EMA Orta", defval: 21, min: 5, step: 1 },
        { id: "emaTrend", type: "number", title: "EMA Trend", defval: 50, min: 10, step: 1 },
        { id: "rsiPeriod", type: "number", title: "RSI Periyodu", defval: 14, min: 2, step: 1 }
    ],
    calculate: (bars: any[], params: any) => {
        return { metadata: { overlay: true }, plots: {} };
    }
};

// VWAP + MACD: fiyat VWAP üstü + MACD pozitif → buy/sell marker
export const VWAP_MACD_ENTRY: RegistryEntry = {
    id: "vwap_macd",
    name: "VWAP + MACD Alerts (Buy/Sell)",
    shortName: "VWAP+MACD",
    category: "Strateji",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "vwapPeriod", type: "number", title: "VWAP Periyodu", defval: 20, min: 5, step: 1 },
        { id: "macdFast", type: "number", title: "MACD Hızlı", defval: 12, min: 3, step: 1 },
        { id: "macdSlow", type: "number", title: "MACD Yavaş", defval: 26, min: 5, step: 1 },
        { id: "macdSignal", type: "number", title: "MACD Sinyal", defval: 9, min: 2, step: 1 }
    ],
    calculate: (bars: any[], params: any) => {
        return { metadata: { overlay: true }, plots: {} };
    }
};

// CMO + CRSI Derin Dip: aşırı düşmüş coinleri avlar → buy/sell marker
export const CMO_CRSI_ENTRY: RegistryEntry = {
    id: "cmo_crsi",
    name: "CMO+CRSI Dip Alerts (Buy/Sell)",
    shortName: "CMO+CRSI",
    category: "Strateji",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "cmoPeriod", type: "number", title: "CMO Periyodu", defval: 9, min: 5, step: 1 },
        { id: "rsiPeriod", type: "number", title: "CRSI RSI Periyodu", defval: 3, min: 2, step: 1 },
        { id: "rankPeriod", type: "number", title: "CRSI Rank Periyodu", defval: 100, min: 20, step: 1 },
        { id: "buyCmo", type: "number", title: "AL CMO Eşiği", defval: -63, min: -100, step: 1 },
        { id: "buyCrsi", type: "number", title: "AL CRSI Eşiği", defval: 30, min: 1, step: 1 },
        { id: "sellCmo", type: "number", title: "SAT CMO Eşiği", defval: 63, min: 1, step: 1 },
        { id: "sellCrsi", type: "number", title: "SAT CRSI Eşiği", defval: 80, min: 1, step: 1 }
    ],
    calculate: (bars: any[], params: any) => {
        return { metadata: { overlay: true }, plots: {} };
    }
};

const bbMfiValues = (bars: any[], params: any) => {
    const bbPeriod = Math.max(5, Math.round(params.bbPeriod ?? 20));
    const bbStdDev = Number(params.bbStdDev ?? 1);
    const mfiPeriod = Math.max(2, Math.round(params.mfiPeriod ?? 14));
    const threshold = Number(params.mfiThreshold ?? 60);
    const closes = bars.map((bar) => Number(bar.close));
    const highs = bars.map((bar) => Number(bar.high));
    const lows = bars.map((bar) => Number(bar.low));
    const volumes = bars.map((bar) => Number(bar.volume));
    const mfi: (number | null)[] = Array(bars.length).fill(null);
    const lower: (number | null)[] = Array(bars.length).fill(null);
    const thresholdLine: (number | null)[] = Array(bars.length).fill(null);

    for (let i = 0; i < bars.length; i++) {
        if (i >= bbPeriod - 1) {
            const window = closes.slice(i - bbPeriod + 1, i + 1);
            const mean = window.reduce((sum, value) => sum + value, 0) / window.length;
            const variance = window.reduce((sum, value) => sum + (value - mean) ** 2, 0) / window.length;
            lower[i] = mean - Math.sqrt(variance) * bbStdDev;
        }
        if (i < mfiPeriod) continue;
        const typical = highs.map((high, index) => (high + lows[index] + closes[index]) / 3);
        let positive = 0;
        let negative = 0;
        for (let j = i - mfiPeriod + 1; j <= i; j++) {
            const flow = typical[j] * volumes[j];
            if (typical[j] > typical[j - 1]) positive += flow;
            else if (typical[j] < typical[j - 1]) negative += flow;
        }
        mfi[i] = negative ? 100 - 100 / (1 + positive / negative) : 100;
        thresholdLine[i] = threshold;
    }
    return { mfi, lower, thresholdLine, threshold };
};

// BB-MFI aktif stratejisinin MFI pane'i: MFI çizgisi ve giriş eşiği.
export const BB_MFI_ENTRY: RegistryEntry = {
    id: "bb_mfi_mean_reversion",
    name: "BB + MFI Mean Reversion",
    shortName: "BB + MFI",
    category: "Strateji",
    group: "custom",
    overlay: false,
    inputConfig: [
        { id: "bbPeriod", type: "number", title: "BB Periyodu", defval: 20, min: 5, step: 1 },
        { id: "bbStdDev", type: "number", title: "BB Std Dev", defval: 1, min: 0.1, step: 0.1 },
        { id: "mfiPeriod", type: "number", title: "MFI Periyodu", defval: 14, min: 2, step: 1 },
        { id: "mfiThreshold", type: "number", title: "MFI AL Eşiği", defval: 60, min: 1, max: 99, step: 1 },
    ],
    calculate: (bars: any[], params: any) => {
        const values = bbMfiValues(bars, params);
        return {
            metadata: { overlay: false },
            plots: {
                mfi: bars.map((bar, index) => ({ time: bar.time, value: values.mfi[index], color: values.mfi[index] != null && values.mfi[index] < values.threshold ? "#10b981" : "#f59e0b" })),
                threshold: bars.map((bar, index) => ({ time: bar.time, value: values.thresholdLine[index] })),
            },
        };
    },
};

const SIMPLE_STRATEGY_ENTRY = (id: string, name: string, shortName: string): RegistryEntry => ({
    id, name, shortName, category: "Strateji", group: "custom", overlay: true,
    inputConfig: [], calculate: () => ({ metadata: { overlay: true }, plots: {} })
});

const EMA_VWAP_ENTRY = SIMPLE_STRATEGY_ENTRY("ema_vwap", "EMA + VWAP Trend Alerts", "EMA+VWAP");
const BREAKOUT_ENTRY = SIMPLE_STRATEGY_ENTRY("breakout", "Hacimli Breakout Alerts", "Breakout");
const ORDERFLOW_ENTRY = SIMPLE_STRATEGY_ENTRY("orderflow", "Order Flow Alerts", "Order Flow");
const MOMENTUM_ENTRY = SIMPLE_STRATEGY_ENTRY("momentum", "Momentum Alerts", "Momentum");
const MEAN_REVERSION_ENTRY = SIMPLE_STRATEGY_ENTRY("mean_reversion", "Mean Reversion Alerts", "Mean Rev.");

export const STRATEGY_ENTRIES = [
    SIMPLE_STRATEGY_ENTRY("ema_vwap_pullback", "EMA + VWAP Pullback", "EMA+VWAP"),
    SIMPLE_STRATEGY_ENTRY("bb_squeeze_orderflow", "BB Squeeze + Order-Flow Confirmation", "BB+FLOW"),
    ORDERFLOW_ENTRY,
    MOMENTUM_ENTRY,
    SIMPLE_STRATEGY_ENTRY("vwap_mean_reversion", "VWAP Mean Reversion", "VWAP MR"),
    SIMPLE_STRATEGY_ENTRY("keltner_breakout", "Keltner Breakout", "Keltner"),
    SIMPLE_STRATEGY_ENTRY("chop_trend_filter", "CHOP Trend Filter", "CHOP"),
    SIMPLE_STRATEGY_ENTRY("donchian_breakout", "Donchian Breakout", "Donchian"),
];

const emaSeries = (bars: any[], period: number, color: string) => {
    const closes = bars.map((bar: any) => Number(bar.close));
    const out: { time: number; value: number | null; color?: string }[] = [];
    const k = 2 / (period + 1);
    let ema: number | null = null;
    for (let i = 0; i < bars.length; i++) {
        const t = Number(bars[i].time);
        const c = closes[i];
        ema = ema === null ? c : (c - ema) * k + ema;
        out.push({ time: t, value: Number.isFinite(ema) ? ema : null, color });
    }
    return out;
};

// SlingShot: yalnız EMA50 (lime) + EMA11 (red) çizgileri — üçgen/marker YOK.
// Varsayılan grafik indikatörü; kullanıcı kendi ekledikçe yerini alır.
export const SLING_SHOT_ENTRY: RegistryEntry = {
    id: "sling_shot",
    name: "SlingShot (EMA50/EMA11)",
    shortName: "SlingShot",
    category: "Trend",
    group: "custom",
    overlay: true,
    inputConfig: [],
    calculate: (bars: any[], params: any) => {
        return {
            metadata: { overlay: true },
            plots: {
                plot0: emaSeries(bars, 50, "#39FF14"),
                plot1: emaSeries(bars, 11, "#ef4444"),
            },
        };
    },
};

// Uygulama içi özel kayıtlar da paket registry'siyle aynı kaynaktan seçilebilmeli.
// Aksi halde picker'da görünen ancak grafik renderer'ında bulunamayan indikatörler oluşuyordu.
export const CUSTOM_INDICATOR_ENTRIES: RegistryEntry[] = [
    SLING_SHOT_ENTRY,
    UT_BOT_ENTRY,
    BB_SQUEEZE_ENTRY,
    EMA_PULLBACK_ENTRY,
    VWAP_MACD_ENTRY,
    CMO_CRSI_ENTRY,
    BB_MFI_ENTRY,
    ...STRATEGY_ENTRIES,
];

export const findIndicatorEntry = (id: string): RegistryEntry | undefined =>
    CUSTOM_INDICATOR_ENTRIES.find((entry) => entry.id === id) ||
    (indicatorRegistry.find((entry: any) => entry.id === id) as RegistryEntry | undefined);

export default function IndicatorPicker({ onSelect, onClose, activeStrategy }: Props) {
    const [q, setQ] = useState("");
    const [cat, setCat] = useState("Tümü");

    const indicators = useMemo(
        () => [
            ...CUSTOM_INDICATOR_ENTRIES.filter((entry) => !STRATEGY_INDICATOR_IDS.has(entry.id) || entry.id === activeStrategyIndicatorId(activeStrategy)),
            ...indicatorRegistry.filter((i: any) => i.group !== "candlestick-port"),
        ] as RegistryEntry[],
        [activeStrategy]
    );
    const cats = useMemo(
        () => ["Tümü", ...Array.from(new Set(indicators.map((i) => i.category)))],
        [indicators]
    );
    const filtered = indicators.filter(
        (i) =>
            (cat === "Tümü" || i.category === cat) &&
            (!q ||
                i.name.toLowerCase().includes(q.toLowerCase()) ||
                i.shortName.toLowerCase().includes(q.toLowerCase()) ||
                i.id.includes(q.toLowerCase()))
    );

    return (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center pt-16" onClick={onClose}>
            <div
                className="bg-bunker-900 border border-bunker-700 rounded-xl w-[600px] max-w-[95vw] max-h-[75vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="p-4 border-b border-bunker-800">
                    <div className="flex justify-between items-center mb-3">
                        <p className="font-mono text-sm font-bold text-white">İNDİKATÖR EKLE</p>
                        <button onClick={onClose} className="text-bunker-muted hover:text-white text-lg leading-none">✕</button>
                    </div>
                    <input
                        autoFocus
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        placeholder="İndikatör ara (RSI, MACD, EMA, Bollinger...)"
                        className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white placeholder-bunker-700 focus:border-neon-green/50 outline-none"
                    />
                    <div className="flex flex-wrap gap-1.5 mt-3">
                        {cats.map((c) => (
                            <button
                                key={c}
                                onClick={() => setCat(c)}
                                className={`px-2.5 py-1 rounded-full border font-mono text-[11px] transition-colors ${cat === c
                                    ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                                    : "border-bunker-700 text-bunker-muted hover:text-white"
                                    }`}
                            >
                                {c}
                            </button>
                        ))}
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto p-2">
                    {filtered.map((i) => (
                        <button
                            key={i.id}
                            onClick={() => onSelect(i)}
                            className="w-full text-left px-3 py-2.5 rounded-lg hover:bg-bunker-800/60 flex justify-between items-center gap-3 border-b border-bunker-800/30"
                        >
                            <div className="min-w-0">
                                <p className="font-mono text-sm text-white">{i.shortName}</p>
                                <p className="text-xs text-bunker-muted truncate">{i.name}</p>
                            </div>
                            <span className={`shrink-0 text-[10px] font-mono px-2 py-0.5 rounded-full border ${i.overlay ? "text-neon-yellow border-neon-yellow/30" : "text-neon-green border-neon-green/30"}`}>
                                {i.overlay ? "GRAFİK" : "PANE"}
                            </span>
                        </button>
                    ))}
                    {filtered.length === 0 && (
                        <p className="text-center text-bunker-muted py-10 font-mono text-sm">Sonuç yok</p>
                    )}
                </div>
            </div>
        </div>
    );
}
