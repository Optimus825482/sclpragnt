import { API_BASE } from "../lib/api";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "./types";

export const FALLBACK_SYMBOLS = ["BTCTRY", "ETHTRY", "SOLTRY"];
export const INTERVALS = [
    { v: "1m", l: "1M" }, { v: "5m", l: "5M" }, { v: "15m", l: "15M" },
    { v: "30m", l: "M30" }, { v: "1h", l: "1H" }, { v: "4h", l: "4H" }, { v: "1d", l: "D1" }
];
export const INTERVAL_MS: Record<string, number> = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000
};
export const PALETTE = ["#10b981", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4", "#84cc16", "#f97316"];
export const PANE_H = 180;
// sabit canvas yüksekliği: pane aç/kapa toplam yüksekliği değiştirmez, paneller kalanı paylaşır
export const TOTAL_HEIGHT = 600;
export const MAIN_MIN = 300;
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
export const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

export const LS_SYMBOL = "scalper_chart_symbol";
export const LS_INTERVAL = "scalper_chart_interval";
export const LS_INDICATORS = "scalper_chart_indicators";
export const LS_PANE_HEIGHTS = "scalper_chart_pane_heights";
export const LS_DISPLAY_SETTINGS = "scalper_chart_display_settings";
export const API = `${API_BASE}/api/chart`;

export const paneMinimumHeight = (key: string, compact: boolean) => {
    if (key === "volume") return compact ? 76 : 104;
    return compact ? 108 : 136;
};

export const preferredChartHeight = (minimumRequired: number, compact: boolean) => {
    const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
    // Mobilde üst araç çubuğu + alt içerik için ~200px bütçe ayır; chart tüm
    // ekranı kaplamasın (alt tablolara ulaşmak için dev kaydırma yaratıyordu).
    const usable = Math.max(240, viewportHeight - (compact ? 200 : 0));
    const viewportPreference = Math.round(usable * (compact ? 0.78 : 0.78));
    return Math.max(compact ? 340 : TOTAL_HEIGHT, viewportPreference, minimumRequired);
};

// Ekrana göre paylaşımlı yerleşim: hedef toplam yükseklik görünür alanın
// ~%78'i (mobilde %78 — üst/alt UI bütçesi düşüldükten sonra). Alt pane'ler
// önce kayıtlı/tercih edilen yüksekliklerini alır; toplam taşırsa ORANSAL
// olarak kısalır (mutlak minimumların altına inmeden). Ana grafik kalan
// bütçenin tamamını kullanır. Böylece çok sayıda gösterge eklenince canvas
// ekranı aşmaz, her pane daralsa da okunur kalır.
export const computePaneLayout = (
    keys: string[],
    saved: Record<string, number>,
    compact: boolean
): { total: number; heights: number[] } => {
    const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
    const baseMin = compact ? 210 : MAIN_MIN;
    // Mobil tavan: viewport'un %82'si, üst/alt UI için en az ~110px pay bırak.
    const usable = Math.max(280, viewportHeight - (compact ? 110 : 0));
    const targetTotal = clamp(
        Math.round(usable * (compact ? 0.82 : 0.78)),
        compact ? 340 : TOTAL_HEIGHT,
        Math.round(usable * (compact ? 0.95 : 0.92))
    );
    const minOf = (key: string) => paneMinimumHeight(key, compact);
    const wanted = keys.map((key, i) =>
        i === 0
            ? baseMin
            : Math.max(minOf(key), saved[key] || (key === "volume" ? minOf(key) : compact ? 124 : PANE_H))
    );
    const totalWanted = wanted.reduce((a, b) => a + b, 0);
    if (totalWanted > targetTotal) {
        const mins = keys.map((key, i) => (i === 0 ? baseMin : minOf(key)));
        const shrinkable = wanted.map((w, i) => w - mins[i]);
        const shrinkableTotal = shrinkable.reduce((a, b) => a + b, 0);
        if (shrinkableTotal > 0) {
            const factor = Math.min(1, (totalWanted - targetTotal) / shrinkableTotal);
            for (let i = 0; i < wanted.length; i++) wanted[i] = Math.round(wanted[i] - shrinkable[i] * factor);
        }
    }
    const subTotal = wanted.slice(1).reduce((a, b) => a + b, 0);
    const mainH = Math.max(baseMin, targetTotal - subTotal);
    const heights = [mainH, ...wanted.slice(1)];
    return { total: heights.reduce((a, b) => a + b, 0), heights };
};

export const macdHistogramColor = (value: number, previous?: number) => {
    const rising = previous == null || value >= previous;
    if (value >= 0) return rising ? "rgba(52, 211, 153, 0.94)" : "rgba(5, 150, 105, 0.84)";
    return rising ? "rgba(248, 113, 113, 0.84)" : "rgba(239, 68, 68, 0.94)";
};

// Grafik fiyatları, sembolün mevcut değer aralığına göre aynı okunabilirlikte
// kalır. Bu kural sağ eksen, fiyat çizgileri ve açık pozisyon tablosunda ortak
// kullanılır; böylece aynı fiyat farklı yerlerde farklı yuvarlanmaz.
export const pricePrecision = (value: number) => {
    const absolute = Math.abs(Number(value) || 0);
    // Alt-1 fiyatlar da (örn. 0,335) üç basamakla okunur olmalı.
    if (absolute < 100) return 3;
    if (absolute >= 100 && absolute < 1000) return 2;
    return 1;
};
export const formatPrice = (value: number | null | undefined) => {
    const numeric = Number(value);
    return Number.isFinite(numeric)
        ? numeric.toLocaleString("tr-TR", {
            minimumFractionDigits: pricePrecision(numeric),
            maximumFractionDigits: pricePrecision(numeric)
        })
        : "—";
};
export const chartPriceFormat = (value: number) => {
    const precision = pricePrecision(value);
    return { type: "price" as const, precision, minMove: Number(`1e-${precision}`) };
};

export type DisplaySettings = { showPositions: boolean; showStopTakeProfit: boolean; showPatterns: boolean; showPressure: boolean; showMonitoringLines: boolean };
export type LivePortfolio = { total_value?: number; unrealized_pnl?: number };
export type PortfolioMetrics = { closed_trades: number; winning_trades: number; net_pnl: number; win_rate: number };
export type TimeframeTrend = { timeframe: string; alignment: "bullish" | "bearish" | "mixed" | "unknown"; data_ready: boolean };

export const loadPersisted = <T,>(key: string, fallback: T): T => {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) as T : fallback;
    } catch {
        return fallback;
    }
};

export const DEFAULT_STYLE: IndicatorStyle = {
    colors: ["#10b981", "#3b82f6", "#f59e0b", "#a855f7"],
    lineWidth: 2,
    showPriceLine: true,
    showBounds: true,
    minValue: null,
    maxValue: null
};

// Grafik yalnızca kullanıcının ekleyip kaydettiği göstergelerle açılır.
export const DEFAULT_INSTANCES: IndicatorInstance[] = [];

export type EditTarget = { entry: RegistryEntry; editUid?: string };

// Varsayılan indikatör: Rational Quadratic Kernel — tek çizgi, trende göre renk değiştirir.
// Kullanıcı kendi indikatörlerini ekledikçe kayıt bunun yerini alır.
export const DEFAULT_SLING_SHOT: IndicatorInstance = {
    uid: "sling_shot-default",
    registryId: "sling_shot",
    name: "Rational Quadratic Kernel",
    overlay: true,
    params: {},
    style: { ...DEFAULT_STYLE, colors: ["#3AFF17", "#FD1707"] },
};

export const loadIndicators = (): IndicatorInstance[] => {
    const raw = loadPersisted<IndicatorInstance[]>(LS_INDICATORS, DEFAULT_INSTANCES);
    const mapped = raw.map((i) => (i.style ? i : { ...i, style: DEFAULT_STYLE }));
    // hiç kayıtlı indikatör yoksa varsayılan SlingShot ile aç
    return mapped.length ? mapped : [DEFAULT_SLING_SHOT];
};

export const STRATEGY_LABEL_TR: Record<string, string> = {
    VELOCITY: "Hız Avcısı",
    CHAT_PREDICTION: "🚀 Hız Avcısı (Otonom)",
    LLM_PAPER: "LLM Paper",
    GAINER_RADAR: "Gainer Radar",
};

export function strategyLabelFor(p: { strategy?: string; entry_context?: any }) {
    const strat = String(p.strategy || "").toUpperCase();
    if (strat === "CHAT_PREDICTION") {
        const score = (p.entry_context as any)?.velocity_score;
        const mode = (p.entry_context as any)?.mode === "v_donusu" ? "V-dönüşü" : "Trend-devam";
        return `🚀 Hız Avcısı${score != null ? ` · skor ${score}` : ""} · ${mode}`;
    }
    return STRATEGY_LABEL_TR[strat] || p.strategy || "—";
}
