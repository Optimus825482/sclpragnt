"use client";
import { useMemo, useState } from "react";
import { indicatorRegistry } from "lightweight-charts-indicators";
import type { RegistryEntry } from "./types";

type Props = {
    onSelect: (entry: RegistryEntry) => void;
    onClose: () => void;
};

export const filterIndicatorInstances = <T extends { registryId: string }>(instances: T[]) => {
    // Kayıtlı (localStorage/DB) yerleşimlerden artık registry'de bulunmayan
    // eski strateji indikatörlerini düşürür; bilinen her şey korunur.
    return instances.filter((instance) => findIndicatorEntry(instance.registryId) != null);
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

// Nadaraya-Watson: Rational Quadratic Kernel (Non-Repainting)
// Tek çizgi — trend yönüne göre yeşil (yükseliş) veya kırmızı (düşüş).
// Rational Quadratic Kernel kullanarak fiyatı tahmin eder.
// Varsayılan grafik indikatörü; kullanıcı kendi ekledikçe yerini alır.
export const SLING_SHOT_ENTRY: RegistryEntry = {
    id: "sling_shot",
    name: "Rational Quadratic Kernel",
    shortName: "RQ Kernel",
    category: "Trend",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "h", type: "number", title: "Lookback Window", defval: 8, min: 3, step: 1 },
        { id: "r", type: "number", title: "Relative Weighting", defval: 2, min: 0.25, step: 0.25 },
        { id: "smoothColors", type: "bool", title: "Smooth Colors", defval: false },
        { id: "showSignals", type: "bool", title: "B/S Sinyallerini Göster", defval: true },
    ],
    calculate: (bars: any[], params: any) => {
        const h = Math.max(3, Number(params.h ?? 8));
        const r = Math.max(0.25, Number(params.r ?? 2));
        const smoothColors = params.smoothColors ?? false;
        const closes = bars.map((bar: any) => Number(bar.close));
        const t = bars.map((bar: any) => Number(bar.time));
        // Nadaraya-Watson Rational Quadratic Kernel regresyonu
        // w(i) = (1 + (i^2 / (h^2 * 2 * r)))^(-r)
        // yhat = sum(price[i] * w(i)) / sum(w(i))
        const calculateYhat = (endIdx: number): number | null => {
            if (endIdx < 1) return null;
            let currentWeight = 0;
            let cumulativeWeight = 0;
            // Son h kadar mum için hesapla (geriye doğru)
            const lookback = Math.min(h, endIdx + 1);
            for (let i = 0; i < lookback; i++) {
                const price = closes[endIdx - i];
                if (price == null || !Number.isFinite(price)) continue;
                // Rational Quadratic Kernel ağırlığı
                const w = Math.pow(1 + (Math.pow(i, 2) / (Math.pow(h, 2) * 2 * r)), -r);
                currentWeight += price * w;
                cumulativeWeight += w;
            }
            if (cumulativeWeight === 0) return null;
            return currentWeight / cumulativeWeight;
        };
        // Tüm barlar için yhat hesapla
        const yhat1: (number | null)[] = []; // Mevcut tahmin
        const yhat2: (number | null)[] = []; // Lag'li tahmin (smooth colors için)
        for (let i = 0; i < bars.length; i++) {
            yhat1.push(calculateYhat(i));
            yhat2.push(calculateYhat(Math.max(0, i - 2))); // 2 bar lag
        }
        // Trend yönüne göre renk belirle — TEK SERİ, segment bazlı renk
        const kernelLine: { time: number; value: number | null; color?: string }[] = [];
        for (let i = 0; i < bars.length; i++) {
            const v = yhat1[i];
            if (v == null || !Number.isFinite(v)) {
                kernelLine.push({ time: t[i], value: null });
                continue;
            }
            // Önceki değerler
            const prev1 = i >= 1 ? yhat1[i - 1] : null;
            const prev2 = i >= 2 ? yhat1[i - 2] : null;
            const v2 = yhat2[i];
            let isBullish = false;
            if (smoothColors) {
                isBullish = v2 != null && v2 > v;
            } else {
                if (prev1 != null && prev2 != null) {
                    const wasBearish = prev2 > prev1;
                    const isBearishNow = prev1 > v;
                    const isBullishNow = prev1 < v;
                    isBullish = isBullishNow || (wasBearish && !isBearishNow);
                } else if (prev1 != null) {
                    isBullish = prev1 < v;
                } else {
                    isBullish = true;
                }
            }
            kernelLine.push({ time: t[i], value: v, color: isBullish ? "#3AFF17" : "#FD1707" });
        }
        return {
            metadata: { overlay: true },
            plots: {
                plot0: kernelLine, // Tek seri, her nokta kendi renginde
            },
        };
    },
};

// Supertrend: ATR tabanlı dinamik trend ve tersine dönüş indikatörü
export const SUPERTREND_ENTRY: RegistryEntry = {
    id: "supertrend",
    name: "Supertrend (ATR Trend)",
    shortName: "Supertrend",
    category: "Trend",
    group: "custom",
    overlay: true,
    inputConfig: [
        { id: "period", type: "number", title: "ATR Periyodu", defval: 10, min: 2, max: 100, step: 1 },
        { id: "multiplier", type: "number", title: "ATR Çarpanı", defval: 3, min: 0.5, max: 10, step: 0.5 },
    ],
    calculate: (bars: any[], params: any) => {
        const period = Math.max(2, Number(params.period ?? 10));
        const multiplier = Math.max(0.5, Number(params.multiplier ?? 3));
        if (!bars || bars.length <= period) {
            return { metadata: { overlay: true }, plots: { plot0: [] } };
        }

        // 1. True Range (TR)
        const trList: number[] = [];
        trList.push(Number(bars[0].high) - Number(bars[0].low));
        for (let i = 1; i < bars.length; i++) {
            const high = Number(bars[i].high);
            const low = Number(bars[i].low);
            const prevClose = Number(bars[i - 1].close);
            const hl = high - low;
            const hpc = Math.abs(high - prevClose);
            const lpc = Math.abs(low - prevClose);
            trList.push(Math.max(hl, hpc, lpc));
        }

        // 2. Wilder's ATR
        let atr = 0;
        for (let i = 0; i < period; i++) {
            atr += trList[i];
        }
        atr /= period;

        const plot0: { time: number; value: number | null; color?: string }[] = [];
        let prevUpperBand = 0;
        let prevLowerBand = 0;
        let direction: "UP" | "DOWN" = "UP";

        for (let i = period; i < bars.length; i++) {
            atr = ((atr * (period - 1)) + trList[i]) / period;
            const high = Number(bars[i].high);
            const low = Number(bars[i].low);
            const close = Number(bars[i].close);
            const prevClose = Number(bars[i - 1].close);
            const hl2 = (high + low) / 2;

            const basicUpper = hl2 + (multiplier * atr);
            const basicLower = hl2 - (multiplier * atr);

            const finalUpper = (basicUpper < prevUpperBand || prevClose > prevUpperBand)
                ? basicUpper : prevUpperBand;
            const finalLower = (basicLower > prevLowerBand || prevClose < prevLowerBand)
                ? basicLower : prevLowerBand;

            if (direction === "UP" && close < finalLower) {
                direction = "DOWN";
            } else if (direction === "DOWN" && close > finalUpper) {
                direction = "UP";
            }

            const superTrendVal = direction === "UP" ? finalLower : finalUpper;
            const rawTime = bars[i].time;
            const timeSec = rawTime > 1e11 ? Math.floor(rawTime / 1000) : Math.floor(rawTime);

            plot0.push({
                time: timeSec,
                value: Number(superTrendVal.toFixed(6)),
                color: direction === "UP" ? "#10b981" : "#ef4444",
            });

            prevUpperBand = finalUpper;
            prevLowerBand = finalLower;
        }

        return {
            metadata: { overlay: true },
            plots: {
                plot0,
            },
        };
    },
};

// Uygulama içi özel kayıtlar da paket registry'siyle aynı kaynaktan seçilebilmeli.
// Aksi halde picker'da görünen ancak grafik renderer'ında bulunamayan indikatörler oluşuyordu.
export const CUSTOM_INDICATOR_ENTRIES: RegistryEntry[] = [
    SUPERTREND_ENTRY,
    SLING_SHOT_ENTRY,
    EMA_PULLBACK_ENTRY,
    VWAP_MACD_ENTRY,
    CMO_CRSI_ENTRY,
];

export const findIndicatorEntry = (id: string): RegistryEntry | undefined =>
    CUSTOM_INDICATOR_ENTRIES.find((entry) => entry.id === id) ||
    (indicatorRegistry.find((entry: any) => entry.id === id) as RegistryEntry | undefined);

export default function IndicatorPicker({ onSelect, onClose }: Props) {
    const [q, setQ] = useState("");
    const [cat, setCat] = useState("Tümü");

    const indicators = useMemo(
        () => [
            ...CUSTOM_INDICATOR_ENTRIES,
            ...indicatorRegistry.filter((i: any) => i.group !== "candlestick-port"),
        ] as RegistryEntry[],
        []
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
