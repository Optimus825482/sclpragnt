"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import RequireAdmin from "../components/RequireAdmin";
import { API_BASE, apiRequest } from "../lib/api";
import type { MultiChartConfig, ChartIndicators } from "./MultiChartCard";

// Dynamic import with ssr: false for Lightweight Charts
const MultiChartCard = dynamic(() => import("./MultiChartCard"), {
    ssr: false,
    loading: () => (
        <div className="h-full min-h-[300px] flex items-center justify-center bg-bunker-950 border border-bunker-800 rounded-xl">
            <div className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
                <span className="w-2 h-2 rounded-full bg-neon-green animate-ping" />
                Grafik Tuvali Hazırlanıyor...
            </div>
        </div>
    ),
});

const DEFAULT_INDICATORS: ChartIndicators = {
    ema9: true,
    ema21: true,
    ema50: false,
    ema200: false,
    bollinger: false,
    volume: true,
    vwap: false,
    obv: false,
    mfi: false,
    rsi: false,
    macd: false,
    stochastic: false,
    williamsR: false,
    cci: false,
    atr: false,
    supertrend: false,
};

const DEFAULT_SLOTS: MultiChartConfig[] = [
    { id: 1, symbol: "BTCTRY",  interval: "1m",  indicators: { ...DEFAULT_INDICATORS } },
    { id: 2, symbol: "ETHTRY",  interval: "5m",  indicators: { ...DEFAULT_INDICATORS } },
    { id: 3, symbol: "SOLTRY",  interval: "15m", indicators: { ...DEFAULT_INDICATORS, rsi: true } },
    { id: 4, symbol: "AVAXTRY", interval: "1h",  indicators: { ...DEFAULT_INDICATORS, macd: true } },
];


const FALLBACK_SYMBOLS = [
    "BTCTRY",
    "ETHTRY",
    "SOLTRY",
    "AVAXTRY",
    "PEPETRY",
    "DOGETRY",
    "XRPTRY",
    "SUITRY",
    "NEARTRY",
    "LINKTRY",
    "TRXTRY",
    "DOTTRY",
    "ADATRY",
    "SHIBTRY",
    "BNBTRY",
];

const LS_KEY_SLOTS = "scalper_tech_charts_slots_v1";
const LS_KEY_LAYOUT = "scalper_tech_charts_layout_v1";

type LayoutType = "grid4" | "split2_h" | "split2_v" | "single";

export default function TechnicalChartsPage() {
    const [slots, setSlots] = useState<MultiChartConfig[]>(DEFAULT_SLOTS);
    const [layout, setLayout] = useState<LayoutType>("grid4");
    const [maximizedId, setMaximizedId] = useState<number | null>(null);
    const [availableSymbols, setAvailableSymbols] = useState<string[]>(FALLBACK_SYMBOLS);
    const [globalSymbol, setGlobalSymbol] = useState<string>("BTCTRY");
    const [globalSymbolInput, setGlobalSymbolInput] = useState<string>("BTCTRY");
    const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);

    // Load persisted configurations from localStorage on mount
    useEffect(() => {
        try {
            const savedSlots = localStorage.getItem(LS_KEY_SLOTS);
            if (savedSlots) {
                const parsed = JSON.parse(savedSlots);
                if (Array.isArray(parsed) && parsed.length === 4) {
                    setSlots(parsed);
                    if (parsed[0]?.symbol) {
                        setGlobalSymbol(parsed[0].symbol);
                        setGlobalSymbolInput(parsed[0].symbol);
                    }
                }
            }

            const savedLayout = localStorage.getItem(LS_KEY_LAYOUT) as LayoutType;
            if (savedLayout && ["grid4", "split2_h", "split2_v", "single"].includes(savedLayout)) {
                setLayout(savedLayout);
            }
        } catch { }

        // Fetch configured symbols from API
        apiRequest(`${API_BASE}/api/config`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data?.symbols && Array.isArray(data.symbols) && data.symbols.length > 0) {
                    setAvailableSymbols((curr) => {
                        const merged = new Set([...curr, ...data.symbols]);
                        return [...merged].sort((a, b) => a.localeCompare(b));
                    });
                }
            })
            .catch(() => { });
    }, []);

    // Save slots when changed
    const updateSlot = useCallback((id: number, updated: Partial<MultiChartConfig>) => {
        setSlots((prev) => {
            const next = prev.map((s) => (s.id === id ? { ...s, ...updated } : s));
            try {
                localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next));
            } catch { }
            return next;
        });
    }, []);

    // Save layout
    const changeLayout = (newLayout: LayoutType) => {
        setLayout(newLayout);
        setMaximizedId(null);
        try {
            localStorage.setItem(LS_KEY_LAYOUT, newLayout);
        } catch { }
    };

    // Apply global symbol to ALL 4 charts
    const applyGlobalSymbolToAll = (sym: string) => {
        const clean = sym.trim().toUpperCase();
        if (!clean) return;
        setSlots((prev) => {
            const next = prev.map((s) => ({ ...s, symbol: clean }));
            try {
                localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next));
            } catch { }
            return next;
        });
        setGlobalSymbol(clean);
        setGlobalSymbolInput(clean);
        setGlobalSearchOpen(false);
    };

    // Quick MTF (Multi-Timeframe) Template: Apply 1m, 5m, 15m, 1h to the 4 slots with the same symbol
    const applyMtfTemplate = () => {
        const targetSymbol = globalSymbol || slots[0]?.symbol || "BTCTRY";
        const mtfIntervals = ["1m", "5m", "15m", "1h"];
        setSlots((prev) => {
            const next = prev.map((s, idx) => ({
                ...s,
                symbol: targetSymbol,
                interval: mtfIntervals[idx] || "5m",
            }));
            try {
                localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next));
            } catch { }
            return next;
        });
        setLayout("grid4");
        setMaximizedId(null);
    };

    // Refresh all charts
    const refreshAll = () => {
        setRefreshKey((k) => k + 1);
    };

    // Toggle maximize single chart
    const toggleMaximize = (id: number) => {
        setMaximizedId((curr) => (curr === id ? null : id));
    };

    // Active slots to render based on layout & maximized state
    const visibleSlots = useMemo(() => {
        if (maximizedId !== null) {
            return slots.filter((s) => s.id === maximizedId);
        }
        if (layout === "single") {
            return slots.slice(0, 1);
        }
        if (layout === "split2_h" || layout === "split2_v") {
            return slots.slice(0, 2);
        }
        return slots; // "grid4"
    }, [slots, layout, maximizedId]);

    // Grid CSS class
    const gridLayoutClass = useMemo(() => {
        if (maximizedId !== null || layout === "single") {
            return "grid-cols-1 grid-rows-1";
        }
        if (layout === "split2_h") {
            return "grid-cols-1 md:grid-cols-2 grid-rows-1";
        }
        if (layout === "split2_v") {
            return "grid-cols-1 grid-rows-2";
        }
        return "grid-cols-1 md:grid-cols-2 grid-rows-2"; // 2x2 grid
    }, [maximizedId, layout]);

    return (
        <RequireAdmin>
            <main className="page-shell flex flex-col h-[calc(100vh-4rem)] p-2 md:p-3 overflow-hidden">
                {/* Global Command Bar */}
                <div className="flex flex-wrap items-center justify-between gap-2.5 px-3 py-2 bg-bunker-900 border border-bunker-800 rounded-xl mb-2 shrink-0">
                    {/* Left: Title & Kicker */}
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                            <span className="text-lg">🖥️</span>
                            <div>
                                <h1 className="font-mono text-sm font-bold text-white flex items-center gap-2">
                                    TEKNİK GRAFİK
                                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-neon-green/15 text-neon-green border border-neon-green/30">
                                        4'LÜ TRADING DESK
                                    </span>
                                </h1>
                                <p className="text-[10px] text-bunker-muted font-mono hidden sm:block">
                                    Bağımsız TF, sembol ve indikatörlerle çoklu TradingView ekranı
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Center: Global Symbol Controller & MTF Template */}
                    <div className="flex items-center gap-2 flex-wrap">
                        {/* Global Symbol Picker with "Tümüne Uygula" */}
                        <div className="relative flex items-center">
                            <div className="flex items-center bg-bunker-950 rounded-lg border border-bunker-700 overflow-hidden focus-within:border-neon-green/50">
                                <input
                                    type="text"
                                    value={globalSymbolInput}
                                    onChange={(e) => {
                                        setGlobalSymbolInput(e.target.value.toUpperCase());
                                        setGlobalSearchOpen(true);
                                    }}
                                    onFocus={() => setGlobalSearchOpen(true)}
                                    placeholder="Sembol..."
                                    className="w-24 md:w-28 px-2.5 py-1 font-mono text-xs text-white bg-transparent outline-none uppercase placeholder-bunker-600"
                                />
                                <button
                                    type="button"
                                    onClick={() => applyGlobalSymbolToAll(globalSymbolInput)}
                                    className="px-2.5 py-1 bg-neon-green/20 hover:bg-neon-green/30 text-neon-green border-l border-bunker-700 font-mono text-xs font-bold transition-colors"
                                    title="Bu sembolü 4 grafiğe birden yükle"
                                >
                                    ⚡ TÜMÜNE UYGULA
                                </button>
                            </div>

                            {/* Global Dropdown Suggestions */}
                            {globalSearchOpen && (
                                <div className="absolute left-0 top-full mt-1.5 z-50 w-52 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-2 max-h-48 overflow-y-auto">
                                    <div className="flex items-center justify-between pb-1 mb-1 border-b border-bunker-800">
                                        <span className="text-[10px] font-mono text-bunker-muted font-bold">
                                            Hızlı Sembol Seç
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => setGlobalSearchOpen(false)}
                                            className="text-bunker-muted hover:text-white text-xs"
                                        >
                                            ✕
                                        </button>
                                    </div>
                                    {availableSymbols
                                        .filter((s) => s.includes(globalSymbolInput.trim()))
                                        .slice(0, 15)
                                        .map((s) => (
                                            <button
                                                key={s}
                                                type="button"
                                                onClick={() => applyGlobalSymbolToAll(s)}
                                                className="w-full text-left px-2 py-1 rounded text-xs font-mono text-bunker-muted hover:bg-bunker-800 hover:text-white transition-colors"
                                            >
                                                {s}
                                            </button>
                                        ))}
                                </div>
                            )}
                        </div>

                        {/* MTF Template Button */}
                        <button
                            type="button"
                            onClick={applyMtfTemplate}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-neon-yellow hover:text-white font-mono text-xs font-bold transition-colors"
                            title="Aynı sembolü 1m, 5m, 15m, 1h zaman dilimlerinde 4 ekrana dağıtır"
                        >
                            <span>⏱</span>
                            <span className="hidden sm:inline">HIZLI MTF ŞABLONU</span>
                            <span className="sm:hidden">MTF</span>
                        </button>
                    </div>

                    {/* Right: Layout Switcher & Actions */}
                    <div className="flex items-center gap-2">
                        {/* Layout Selector */}
                        <div className="flex items-center bg-bunker-950 p-0.5 rounded-lg border border-bunker-700">
                            <button
                                type="button"
                                onClick={() => changeLayout("grid4")}
                                className={`px-2 py-1 rounded font-mono text-xs transition-colors ${
                                    layout === "grid4" && maximizedId === null
                                        ? "bg-neon-green text-bunker-950 font-bold"
                                        : "text-bunker-muted hover:text-white"
                                }`}
                                title="4'lü Grid (2x2)"
                            >
                                ⊞ 4'LÜ
                            </button>
                            <button
                                type="button"
                                onClick={() => changeLayout("split2_h")}
                                className={`px-2 py-1 rounded font-mono text-xs transition-colors ${
                                    layout === "split2_h" && maximizedId === null
                                        ? "bg-neon-green text-bunker-950 font-bold"
                                        : "text-bunker-muted hover:text-white"
                                }`}
                                title="2'li Yan Yana (1x2)"
                            >
                                ▥ 2'Lİ YATAY
                            </button>
                            <button
                                type="button"
                                onClick={() => changeLayout("split2_v")}
                                className={`px-2 py-1 rounded font-mono text-xs transition-colors ${
                                    layout === "split2_v" && maximizedId === null
                                        ? "bg-neon-green text-bunker-950 font-bold"
                                        : "text-bunker-muted hover:text-white"
                                }`}
                                title="2'li Alt Alta (2x1)"
                            >
                                ▤ 2'Lİ DİKEY
                            </button>
                            <button
                                type="button"
                                onClick={() => changeLayout("single")}
                                className={`px-2 py-1 rounded font-mono text-xs transition-colors ${
                                    layout === "single" || maximizedId !== null
                                        ? "bg-neon-green text-bunker-950 font-bold"
                                        : "text-bunker-muted hover:text-white"
                                }`}
                                title="Tekli Odak (1x1)"
                            >
                                ▢ TEKLİ
                            </button>
                        </div>

                        {/* Refresh All */}
                        <button
                            type="button"
                            onClick={refreshAll}
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-white font-mono text-xs transition-colors"
                            title="Tüm grafikleri yenile"
                        >
                            <span>↻</span>
                            <span className="hidden md:inline">YENİLE</span>
                        </button>
                    </div>
                </div>

                {/* Multi-Chart Grid View */}
                <div key={refreshKey} className={`grid gap-2 flex-1 min-h-0 w-full ${gridLayoutClass}`}>
                    {visibleSlots.map((slot) => (
                        <MultiChartCard
                            key={`${slot.id}_${slot.symbol}_${slot.interval}`}
                            config={slot}
                            availableSymbols={availableSymbols}
                            isMaximized={maximizedId === slot.id}
                            onToggleMaximize={() => toggleMaximize(slot.id)}
                            onUpdateConfig={(updated) => updateSlot(slot.id, updated)}
                        />
                    ))}
                </div>
            </main>
        </RequireAdmin>
    );
}
