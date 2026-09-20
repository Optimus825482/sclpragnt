"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
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
    ema9: false,
    ema21: false,
    ema50: false,
    ema200: false,
    bollinger: false,
    volume: false,
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
    { id: 1, symbol: "BTCTRY", interval: "1m",  indicators: { ...DEFAULT_INDICATORS } },
    { id: 2, symbol: "BTCTRY", interval: "3m",  indicators: { ...DEFAULT_INDICATORS } },
    { id: 3, symbol: "BTCTRY", interval: "5m",  indicators: { ...DEFAULT_INDICATORS } },
    { id: 4, symbol: "BTCTRY", interval: "15m", indicators: { ...DEFAULT_INDICATORS } },
];

const FALLBACK_SYMBOLS = [
    "BTCTRY", "ETHTRY", "SOLTRY", "AVAXTRY", "PEPETRY", "DOGETRY",
    "XRPTRY", "SUITRY", "NEARTRY", "LINKTRY", "TRXTRY", "DOTTRY",
    "ADATRY", "SHIBTRY", "BNBTRY",
];

const LS_KEY_SLOTS   = "scalper_tech_charts_slots_v2";
const LS_KEY_LAYOUT  = "scalper_tech_charts_layout_v2";
const LS_KEY_SIDEBAR = "scalper_tech_charts_sidebar_v2";

type LayoutType = "grid4" | "split2_h" | "split2_v" | "single";

// Tüm indikatör tanımları (page'de global panel için)
const ALL_INDICATORS: { key: keyof ChartIndicators; label: string; emoji: string }[] = [
    { key: "ema9",       label: "EMA 9",        emoji: "📊" },
    { key: "ema21",      label: "EMA 21",       emoji: "📊" },
    { key: "ema50",      label: "EMA 50",       emoji: "📊" },
    { key: "ema200",     label: "EMA 200",      emoji: "📊" },
    { key: "bollinger",  label: "Bollinger",    emoji: "〽️" },
    { key: "supertrend", label: "Supertrend",   emoji: "🔮" },
    { key: "volume",     label: "Hacim",        emoji: "📦" },
    { key: "vwap",       label: "VWAP",         emoji: "〰️" },
    { key: "obv",        label: "OBV",          emoji: "🔼" },
    { key: "mfi",        label: "MFI",          emoji: "💰" },
    { key: "rsi",        label: "RSI 14",       emoji: "⚡" },
    { key: "macd",       label: "MACD",         emoji: "🌊" },
    { key: "stochastic", label: "Stoch",        emoji: "🎯" },
    { key: "williamsR",  label: "W%R",          emoji: "📉" },
    { key: "cci",        label: "CCI",          emoji: "🔁" },
    { key: "atr",        label: "ATR",          emoji: "📐" },
];

export default function TechnicalChartsPage() {
    const pageRef = useRef<HTMLDivElement>(null);
    const [slots, setSlots]             = useState<MultiChartConfig[]>(DEFAULT_SLOTS);
    const [layout, setLayout]           = useState<LayoutType>("grid4");
    const [maximizedId, setMaximizedId] = useState<number | null>(null);
    const [availableSymbols, setAvailableSymbols] = useState<string[]>(FALLBACK_SYMBOLS);
    const [globalSymbol, setGlobalSymbol]         = useState<string>("BTCTRY");
    const [globalSymbolInput, setGlobalSymbolInput] = useState<string>("BTCTRY");
    const [globalSearchOpen, setGlobalSearchOpen]   = useState(false);
    const [refreshKey, setRefreshKey]   = useState(0);
    const [sidebarHidden, setSidebarHidden] = useState(false);
    const [isPageFullscreen, setIsPageFullscreen] = useState(false);
    const [globalIndOpen, setGlobalIndOpen] = useState(false);

    // ── Sidebar gizle/göster ───────────────────────────────────────────────────
    // body üzerinde class ile AppShell Sidebar'ı gizler
    useEffect(() => {
        const sidebar = document.querySelector<HTMLElement>("[data-sidebar]");
        const topbar  = document.querySelector<HTMLElement>("[data-topbar]");
        if (sidebarHidden) {
            sidebar?.classList.add("!hidden");
            topbar?.classList.add("!hidden");
        } else {
            sidebar?.classList.remove("!hidden");
            topbar?.classList.remove("!hidden");
        }
        try { localStorage.setItem(LS_KEY_SIDEBAR, sidebarHidden ? "1" : "0"); } catch { }
        return () => {
            // cleanup: sayfadan çıkınca sidebar'ı geri aç
            sidebar?.classList.remove("!hidden");
            topbar?.classList.remove("!hidden");
        };
    }, [sidebarHidden]);

    // ── Sayfa tam ekran ────────────────────────────────────────────────────────
    const togglePageFullscreen = useCallback(() => {
        if (!document.fullscreenElement) {
            pageRef.current?.requestFullscreen().catch(err =>
                console.warn("Fullscreen hata:", err)
            );
        } else {
            document.exitFullscreen();
        }
    }, []);

    useEffect(() => {
        const handler = () => setIsPageFullscreen(!!document.fullscreenElement);
        document.addEventListener("fullscreenchange", handler);
        return () => document.removeEventListener("fullscreenchange", handler);
    }, []);

    // ── LocalStorage yükle ─────────────────────────────────────────────────────
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
            const savedSidebar = localStorage.getItem(LS_KEY_SIDEBAR);
            if (savedSidebar === "1") setSidebarHidden(true);
        } catch { }

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

    // ── Slot güncelle ──────────────────────────────────────────────────────────
    const updateSlot = useCallback((id: number, updated: Partial<MultiChartConfig>) => {
        setSlots((prev) => {
            const next = prev.map((s) => (s.id === id ? { ...s, ...updated } : s));
            try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
            return next;
        });
    }, []);

    // ── Layout değiştir ────────────────────────────────────────────────────────
    const changeLayout = (newLayout: LayoutType) => {
        setLayout(newLayout);
        setMaximizedId(null);
        try { localStorage.setItem(LS_KEY_LAYOUT, newLayout); } catch { }
    };

    // ── Global sembolü 4 grafiğe uygula ───────────────────────────────────────
    const applyGlobalSymbolToAll = (sym: string) => {
        const clean = sym.trim().toUpperCase();
        if (!clean) return;
        setSlots((prev) => {
            const next = prev.map((s) => ({ ...s, symbol: clean }));
            try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
            return next;
        });
        setGlobalSymbol(clean);
        setGlobalSymbolInput(clean);
        setGlobalSearchOpen(false);
    };

    // ── MTF Şablonu: 1m,3m,5m,15m ─────────────────────────────────────────────
    const applyMtfTemplate = () => {
        const targetSymbol = globalSymbol || slots[0]?.symbol || "BTCTRY";
        const mtfIntervals = ["1m", "3m", "5m", "15m"];
        setSlots((prev) => {
            const next = prev.map((s, idx) => ({
                ...s,
                symbol: targetSymbol,
                interval: mtfIntervals[idx] || "5m",
            }));
            try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
            return next;
        });
        setLayout("grid4");
        setMaximizedId(null);
    };

    // ── Tüm grafiklere indikatör aç/kapat ─────────────────────────────────────
    const toggleGlobalIndicator = useCallback((key: keyof ChartIndicators) => {
        setSlots((prev) => {
            // Eğer herhangi bir slotta aktifse → hepsini kapat; yoksa → hepsini aç
            const anyActive = prev.some(s => s.indicators[key]);
            const next = prev.map(s => ({
                ...s,
                indicators: { ...s.indicators, [key]: !anyActive },
            }));
            try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
            return next;
        });
    }, []);

    // Tüm grafikleri temizle
    const clearAllIndicators = useCallback(() => {
        setSlots((prev) => {
            const next = prev.map(s => ({
                ...s,
                indicators: { ...DEFAULT_INDICATORS },
            }));
            try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
            return next;
        });
    }, []);

    // ── Refresh ────────────────────────────────────────────────────────────────
    const refreshAll = () => setRefreshKey((k) => k + 1);

    // ── Maximize tek kart ──────────────────────────────────────────────────────
    const toggleMaximize = (id: number) => {
        setMaximizedId((curr) => (curr === id ? null : id));
    };

    // ── Görünür slotlar ────────────────────────────────────────────────────────
    const visibleSlots = useMemo(() => {
        if (maximizedId !== null) return slots.filter((s) => s.id === maximizedId);
        if (layout === "single")                      return slots.slice(0, 1);
        if (layout === "split2_h" || layout === "split2_v") return slots.slice(0, 2);
        return slots;
    }, [slots, layout, maximizedId]);

    const gridLayoutClass = useMemo(() => {
        if (maximizedId !== null || layout === "single") return "grid-cols-1 grid-rows-1";
        if (layout === "split2_h")  return "grid-cols-1 md:grid-cols-2 grid-rows-1";
        if (layout === "split2_v")  return "grid-cols-1 grid-rows-2";
        return "grid-cols-1 md:grid-cols-2 grid-rows-2";
    }, [maximizedId, layout]);

    // Hangi indikatörler en az 1 slotta aktif? (global panel toggle state'i için)
    const activeGlobal = useMemo(() => {
        const result: Partial<Record<keyof ChartIndicators, boolean>> = {};
        ALL_INDICATORS.forEach(({ key }) => {
            result[key] = slots.some(s => s.indicators[key]);
        });
        return result;
    }, [slots]);

    return (
        <RequireAdmin>
            {/* Tam ekran container — sayfa içeriğinin tamamını sarar */}
            <div
                ref={pageRef}
                className={`flex flex-col bg-bunker-950 ${
                    isPageFullscreen
                        ? "fixed inset-0 z-[9998] overflow-hidden"
                        : "h-[calc(100vh-4rem)]"
                }`}
            >
                {/* ── Komut Çubuğu ─────────────────────────────────────────────── */}
                <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-bunker-900 border-b border-bunker-800 shrink-0">

                    {/* Sol: Başlık + Sidebar Toggle + Tam Ekran */}
                    <div className="flex items-center gap-2">
                        {/* Sidebar Toggle */}
                        <button
                            type="button"
                            onClick={() => setSidebarHidden(v => !v)}
                            className={`p-1.5 rounded-lg border font-mono text-xs transition-colors ${
                                sidebarHidden
                                    ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                                    : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                            }`}
                            title={sidebarHidden ? "Sidebar'ı Aç" : "Sidebar'ı Gizle (Daha Fazla Alan)"}
                        >
                            {sidebarHidden ? "◨" : "◧"}
                        </button>

                        {/* Sayfa Tam Ekran */}
                        <button
                            type="button"
                            onClick={togglePageFullscreen}
                            className={`p-1.5 rounded-lg border font-mono text-xs transition-colors ${
                                isPageFullscreen
                                    ? "bg-neon-green/15 border-neon-green/40 text-neon-green font-bold"
                                    : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                            }`}
                            title={isPageFullscreen ? "Tam Ekrandan Çık (Esc)" : "Komple Sayfa Tam Ekran"}
                        >
                            {isPageFullscreen ? "⊠" : "⊞"}
                        </button>

                        {/* Başlık */}
                        <div className="hidden sm:block">
                            <h1 className="font-mono text-sm font-bold text-white flex items-center gap-2">
                                🖥️ TEKNİK GRAFİK
                                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-neon-green/15 text-neon-green border border-neon-green/30">
                                    4'LÜ MTF
                                </span>
                            </h1>
                        </div>
                    </div>

                    {/* Orta: Global Sembol + MTF */}
                    <div className="flex items-center gap-2 flex-wrap">
                        {/* Global Sembol Seçici */}
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
                                    ⚡ TÜMÜNE
                                </button>
                            </div>

                            {globalSearchOpen && (
                                <div className="absolute left-0 top-full mt-1.5 z-50 w-52 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-2 max-h-48 overflow-y-auto">
                                    <div className="flex items-center justify-between pb-1 mb-1 border-b border-bunker-800">
                                        <span className="text-[10px] font-mono text-bunker-muted font-bold">Hızlı Sembol Seç</span>
                                        <button type="button" onClick={() => setGlobalSearchOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
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

                        {/* MTF Şablonu */}
                        <button
                            type="button"
                            onClick={applyMtfTemplate}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-neon-yellow hover:text-white font-mono text-xs font-bold transition-colors"
                            title="Aynı sembolü 1m, 3m, 5m, 15m zaman dilimlerinde 4 ekrana dağıtır"
                        >
                            <span>⏱</span>
                            <span className="hidden sm:inline">MTF 1·3·5·15</span>
                            <span className="sm:hidden">MTF</span>
                        </button>

                        {/* ── Global İndikatör Paneli ──────────────────────────── */}
                        <div className="relative">
                            <button
                                type="button"
                                onClick={() => setGlobalIndOpen(v => !v)}
                                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border font-mono text-xs font-bold transition-colors ${
                                    globalIndOpen
                                        ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                                        : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                                }`}
                                title="Tüm grafiklere aynı indikatörü ekle/kaldır"
                            >
                                <span>fx</span>
                                <span className="hidden sm:inline">TÜMÜNE İNDİKATÖR</span>
                                <span className="sm:hidden">fx</span>
                                <span className="bg-bunker-700 text-white font-bold rounded-full w-4 h-4 text-[9px] flex items-center justify-center">
                                    {ALL_INDICATORS.filter(({ key }) => activeGlobal[key]).length}
                                </span>
                            </button>

                            {globalIndOpen && (
                                <div className="absolute left-0 top-full mt-1.5 z-50 w-80 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-3">
                                    <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-bunker-800">
                                        <span className="font-mono text-[11px] font-bold text-white">
                                            Tüm Grafiklere Uygula
                                        </span>
                                        <div className="flex items-center gap-2">
                                            <button
                                                type="button"
                                                onClick={clearAllIndicators}
                                                className="px-2 py-0.5 rounded text-[10px] font-mono bg-neon-red/10 border border-neon-red/30 text-neon-red hover:bg-neon-red/20 transition-colors"
                                            >
                                                Temizle
                                            </button>
                                            <button type="button" onClick={() => setGlobalIndOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
                                        </div>
                                    </div>
                                    <p className="text-[10px] font-mono text-bunker-muted mb-2">
                                        Tıklayınca 4 grafik kartına birden ekler/kaldırır
                                    </p>
                                    <div className="grid grid-cols-2 gap-1">
                                        {ALL_INDICATORS.map(({ key, label, emoji }) => {
                                            const active = !!activeGlobal[key];
                                            return (
                                                <button
                                                    key={key}
                                                    type="button"
                                                    onClick={() => toggleGlobalIndicator(key)}
                                                    className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg border font-mono text-[11px] transition-colors text-left ${
                                                        active
                                                            ? "bg-neon-green/15 border-neon-green/40 text-neon-green font-bold"
                                                            : "bg-bunker-800/60 border-bunker-700 text-bunker-muted hover:text-white hover:bg-bunker-800"
                                                    }`}
                                                >
                                                    <span>{emoji}</span>
                                                    <span>{label}</span>
                                                    {active && <span className="ml-auto text-neon-green text-[9px]">✓</span>}
                                                </button>
                                            );
                                        })}
                                    </div>
                                    {/* Hızlı Preset */}
                                    <div className="mt-2 pt-2 border-t border-bunker-800 flex flex-wrap gap-1.5">
                                        <span className="text-[10px] font-mono text-bunker-muted self-center">Preset:</span>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setSlots(prev => {
                                                    const next = prev.map(s => ({ ...s, indicators: { ...DEFAULT_INDICATORS, ema9: true, ema21: true, volume: true } }));
                                                    try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
                                                    return next;
                                                });
                                            }}
                                            className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                        >Temel</button>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setSlots(prev => {
                                                    const next = prev.map(s => ({ ...s, indicators: { ...DEFAULT_INDICATORS, ema9: true, ema21: true, bollinger: true, rsi: true, volume: true } }));
                                                    try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
                                                    return next;
                                                });
                                            }}
                                            className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                        >Orta</button>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setSlots(prev => {
                                                    const next = prev.map(s => ({ ...s, indicators: { ...DEFAULT_INDICATORS, ema9: true, ema21: true, ema50: true, vwap: true, rsi: true, macd: true, volume: true } }));
                                                    try { localStorage.setItem(LS_KEY_SLOTS, JSON.stringify(next)); } catch { }
                                                    return next;
                                                });
                                            }}
                                            className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                        >Pro</button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Sağ: Layout + Yenile */}
                    <div className="flex items-center gap-2">
                        {/* Layout Seçici */}
                        <div className="flex items-center bg-bunker-950 p-0.5 rounded-lg border border-bunker-700">
                            {(["grid4", "split2_h", "split2_v", "single"] as LayoutType[]).map((l) => {
                                const labels: Record<LayoutType, string> = {
                                    grid4: "⊞ 4'LÜ", split2_h: "▥ 2H", split2_v: "▤ 2V", single: "▢ TEKLİ",
                                };
                                const titles: Record<LayoutType, string> = {
                                    grid4: "4'lü Grid (2x2)", split2_h: "2'li Yan Yana", split2_v: "2'li Alt Alta", single: "Tekli Odak",
                                };
                                return (
                                    <button
                                        key={l}
                                        type="button"
                                        onClick={() => changeLayout(l)}
                                        className={`px-2 py-1 rounded font-mono text-xs transition-colors ${
                                            layout === l && maximizedId === null
                                                ? "bg-neon-green text-bunker-950 font-bold"
                                                : "text-bunker-muted hover:text-white"
                                        }`}
                                        title={titles[l]}
                                    >
                                        {labels[l]}
                                    </button>
                                );
                            })}
                        </div>

                        {/* Yenile */}
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

                {/* ── Grafik Gridi ──────────────────────────────────────────────── */}
                <div
                    key={refreshKey}
                    className={`grid gap-2 flex-1 min-h-0 w-full p-2 ${gridLayoutClass}`}
                >
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
            </div>
        </RequireAdmin>
    );
}
