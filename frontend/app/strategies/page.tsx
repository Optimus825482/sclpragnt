"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";
import StrategyLlm from "./StrategyLlm";

type Config = {
    ut_enabled: boolean;
    ut_key_value: number;
    ut_atr_period: number;
    ut_heikin_ashi: boolean;
    ut_timeframe: string;
    bb_squeeze_enabled: boolean;
    squeeze_lookback: number;
    bb_period: number;
    bb_std_dev: number;
    ema_pullback_enabled: boolean;
    ema_short: number;
    ema_mid: number;
    ema_trend: number;
    rsi_period: number;
    vwap_macd_enabled: boolean;
    vwap_period: number;
    macd_fast: number;
    macd_slow: number;
    macd_signal: number;
    cmo_crsi_enabled: boolean;
    bb_squeeze_timeframe: string;
    ema_pullback_timeframe: string;
    vwap_macd_timeframe: string;
    cmo_crsi_timeframe: string;
    ema_vwap_enabled: boolean;
    breakout_enabled: boolean;
    orderflow_enabled: boolean;
    momentum_enabled: boolean;
    mean_reversion_enabled: boolean;
    ema_vwap_timeframe: string;
    breakout_timeframe: string;
    orderflow_timeframe: string;
    momentum_timeframe: string;
    mean_reversion_timeframe: string;
    keltner_enabled: boolean; chop_enabled: boolean; donchian_enabled: boolean;
    keltner_timeframe: string; chop_timeframe: string; donchian_timeframe: string;
    orderflow_min_imbalance: number; momentum_short_lookback: number; momentum_long_lookback: number; momentum_min_return_pct: number;
    keltner_ema_period: number; keltner_atr_period: number; keltner_atr_multiplier: number; keltner_volume_multiplier: number;
    chop_period: number; chop_max_value: number; chop_min_rsi: number; donchian_lookback: number; donchian_volume_multiplier: number;
};

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];

type StrategyMeta = {
    key: string;
    name: string;
    icon: string;
    desc: string;
    enabledKey: keyof Config;
    timeframeKey: keyof Config;
    params: { key: keyof Config; label: string; hint: string; step: number; min: number }[];
};

const STRATEGIES: StrategyMeta[] = [
    { key: "EMA_VWAP_PULLBACK", name: "EMA + VWAP Pullback", icon: "📈", desc: "EMA trendi, VWAP üzeri fiyat ve pullback dönüşünü arar.", enabledKey: "ema_vwap_enabled", timeframeKey: "ema_vwap_timeframe", params: [{ key: "ema_short", label: "EMA Kısa", hint: "Hızlı EMA", step: 1, min: 3 }, { key: "ema_mid", label: "EMA Orta", hint: "Pullback EMA", step: 1, min: 5 }, { key: "ema_trend", label: "EMA Trend", hint: "Ana trend EMA", step: 1, min: 10 }] },
    { key: "BB_SQUEEZE_ORDERFLOW", name: "BB Squeeze + Order-Flow Confirmation", icon: "📦", desc: "Bollinger sıkışması ve akış teyitli kırılımı arar.", enabledKey: "bb_squeeze_enabled", timeframeKey: "bb_squeeze_timeframe", params: [{ key: "squeeze_lookback", label: "Squeeze Lookback", hint: "Sıkışma karşılaştırma penceresi", step: 1, min: 10 }, { key: "bb_period", label: "BB Periyodu", hint: "Bant hesaplama periyodu", step: 1, min: 5 }, { key: "bb_std_dev", label: "BB Std Dev", hint: "Bant genişliği çarpanı", step: 0.1, min: 0.5 }] },
    { key: "ORDERFLOW", name: "Order-Flow Imbalance", icon: "🌊", desc: "Bid/ask dengesizliği ve art arda alış akışını izler.", enabledKey: "orderflow_enabled", timeframeKey: "orderflow_timeframe", params: [{ key: "orderflow_min_imbalance", label: "Minimum Imbalance", hint: "Minimum bid/ask dengesizliği", step: 0.01, min: 0 }] },
    { key: "MOMENTUM", name: "Multi-Timeframe Momentum Ranking", icon: "⚡", desc: "Kısa ve orta vadeli momentumun aynı yönde olmasını arar.", enabledKey: "momentum_enabled", timeframeKey: "momentum_timeframe", params: [{ key: "momentum_short_lookback", label: "Kısa Lookback", hint: "Kısa momentum mum sayısı", step: 1, min: 2 }, { key: "momentum_long_lookback", label: "Uzun Lookback", hint: "Uzun momentum mum sayısı", step: 1, min: 5 }, { key: "momentum_min_return_pct", label: "Minimum Getiri", hint: "Ondalık oran; 0.003 = %0,3", step: 0.0005, min: 0 }] },
    { key: "VWAP_MEAN_REVERSION", name: "VWAP Mean Reversion", icon: "↩️", desc: "Bant altındaki aşırı satımdan VWAP dönüşünü arar.", enabledKey: "mean_reversion_enabled", timeframeKey: "mean_reversion_timeframe", params: [{ key: "bb_period", label: "BB Periyodu", hint: "Mean-reversion bant periyodu", step: 1, min: 5 }, { key: "bb_std_dev", label: "BB Std Dev", hint: "Aşırı sapma seviyesi", step: 0.1, min: 0.5 }] },
    { key: "KELTNER_BREAKOUT", name: "Keltner Breakout", icon: "🔔", desc: "ATR tabanlı Keltner üst bandı kırılımını arar.", enabledKey: "keltner_enabled", timeframeKey: "keltner_timeframe", params: [{ key: "keltner_ema_period", label: "EMA Periyodu", hint: "Keltner merkez EMA", step: 1, min: 5 }, { key: "keltner_atr_period", label: "ATR Periyodu", hint: "Volatilite periyodu", step: 1, min: 5 }, { key: "keltner_atr_multiplier", label: "ATR Çarpanı", hint: "Kanal mesafesi", step: 0.1, min: 0.5 }, { key: "keltner_volume_multiplier", label: "Hacim Çarpanı", hint: "Ortalama hacim üstü eşik", step: 0.1, min: 1 }] },
    { key: "CHOP_TREND_FILTER", name: "CHOP Trend Filter", icon: "📐", desc: "Yatay piyasayı CHOP ile eler, trend momentumunu kullanır.", enabledKey: "chop_enabled", timeframeKey: "chop_timeframe", params: [{ key: "chop_period", label: "CHOP Periyodu", hint: "Piyasa rejimi penceresi", step: 1, min: 5 }, { key: "chop_max_value", label: "Maksimum CHOP", hint: "Bunun altında trend kabul edilir", step: 1, min: 20 }, { key: "chop_min_rsi", label: "Minimum RSI", hint: "Trend momentum filtresi", step: 1, min: 1 }] },
    { key: "DONCHIAN_BREAKOUT", name: "Donchian Breakout", icon: "🏹", desc: "Kanal zirvesinin hacimli kırılımını arar.", enabledKey: "donchian_enabled", timeframeKey: "donchian_timeframe", params: [{ key: "donchian_lookback", label: "Donchian Lookback", hint: "Kanal mum sayısı", step: 1, min: 5 }, { key: "donchian_volume_multiplier", label: "Hacim Çarpanı", hint: "Ortalama hacim üstü eşik", step: 0.05, min: 1 }] },
/* Legacy strategy definitions retained below only for migration compatibility. */
/*
    {
        key: "UT",
        name: "UT Bot",
        icon: "🤖",
        desc: "ATR tabanlı trailing stop. Fiyat stop çizgisini yukarı kırdığında LONG açar, aşağı kırdığında kapatır. Heikin Ashi mumlarıyla gürültü filtrelenir.",
        enabledKey: "ut_enabled",
        timeframeKey: "ut_timeframe",
        params: [
            { key: "ut_key_value", label: "Key Value (a)", hint: "Hassasiyet - ATR çarpanı", step: 0.1, min: 0.1 },
            { key: "ut_atr_period", label: "ATR Periyodu (c)", hint: "ATR hesaplama uzunluğu", step: 1, min: 2 },
        ],
    },
    {
        key: "BB_Squeeze",
        name: "BB Squeeze",
        icon: "📦",
        desc: "Bollinger bandı daralması (squeeze) + hacim patlaması. Band kırılımı yönünde işlem açar. Sıkışma sonrası patlama beklenir.",
        enabledKey: "bb_squeeze_enabled",
        timeframeKey: "bb_squeeze_timeframe",
        params: [
            { key: "squeeze_lookback", label: "Squeeze Lookback", hint: "Karşılaştırma penceresi", step: 1, min: 10 },
            { key: "bb_period", label: "BB Periyodu", hint: "Bollinger hesaplama uzunluğu", step: 1, min: 5 },
            { key: "bb_std_dev", label: "BB Std Dev", hint: "Standart sapma çarpanı", step: 0.1, min: 0.5 },
        ],
    },
    {
        key: "EMA_Pullback",
        name: "EMA Pullback",
        icon: "📉",
        desc: "EMA9 > EMA21 > EMA50 yükseliş trendinde, fiyat EMA21'e geri çekilip döndüğünde alım yapar. RSI 40-55 aralığında soğuma arar.",
        enabledKey: "ema_pullback_enabled",
        timeframeKey: "ema_pullback_timeframe",
        params: [
            { key: "ema_short", label: "EMA Kısa", hint: "Hızlı EMA periyodu", step: 1, min: 3 },
            { key: "ema_mid", label: "EMA Orta", hint: "Orta EMA periyodu", step: 1, min: 5 },
            { key: "ema_trend", label: "EMA Trend", hint: "Trend EMA periyodu", step: 1, min: 10 },
            { key: "rsi_period", label: "RSI Periyodu", hint: "RSI hesaplama uzunluğu", step: 1, min: 2 },
        ],
    },
    {
        key: "VWAP_MACD",
        name: "VWAP + MACD",
        icon: "📊",
        desc: "Fiyat VWAP üzerinde ve MACD histogram pozitifken alım yapar. MACD negatife döndüğünde satış sinyali verir.",
        enabledKey: "vwap_macd_enabled",
        timeframeKey: "vwap_macd_timeframe",
        params: [
            { key: "vwap_period", label: "VWAP Periyodu", hint: "VWAP hesaplama penceresi", step: 1, min: 5 },
            { key: "macd_fast", label: "MACD Hızlı", hint: "Hızlı EMA (12)", step: 1, min: 3 },
            { key: "macd_slow", label: "MACD Yavaş", hint: "Yavaş EMA (26)", step: 1, min: 5 },
            { key: "macd_signal", label: "MACD Sinyal", hint: "Sinyal EMA (9)", step: 1, min: 2 },
        ],
    },
    {
        key: "CMO_CRSI_Dip",
        name: "CMO+CRSI Dip",
        icon: "🕳️",
        desc: "Aşırı düşmüş coinleri avlar: CMO -63 ve CRSI 30 altındaysa dip toplama yapar. CMO +63 veya CRSI 70 üstünde çıkış sinyali verir.",
        enabledKey: "cmo_crsi_enabled",
        timeframeKey: "cmo_crsi_timeframe",
        params: [],
    },
    { key: "EMA_VWAP", name: "EMA + VWAP Trend", icon: "📈", desc: "EMA9 > EMA21 > EMA50 trendi ve VWAP üzeri fiyat kesişimi; akış filtresiyle teyit edilir.", enabledKey: "ema_vwap_enabled", timeframeKey: "ema_vwap_timeframe", params: [] },
    { key: "BREAKOUT", name: "Hacimli Breakout", icon: "🚀", desc: "Son 20 mum zirvesinin hacim patlamasıyla kırılmasını ve pozitif akışı arar.", enabledKey: "breakout_enabled", timeframeKey: "breakout_timeframe", params: [] },
    { key: "ORDERFLOW", name: "Order Flow", icon: "🌊", desc: "Bid/ask derinlik dengesini ve son işlem yönünü kullanır; gerçek akış yoksa sinyal üretmez.", enabledKey: "orderflow_enabled", timeframeKey: "orderflow_timeframe", params: [] },
    { key: "MOMENTUM", name: "Momentum", icon: "⚡", desc: "Kısa vadeli pozitif getiriyi trend ve likidite filtresiyle teyit eder.", enabledKey: "momentum_enabled", timeframeKey: "momentum_timeframe", params: [] },
    { key: "MEAN_REVERSION", name: "Mean Reversion", icon: "↩️", desc: "Bollinger alt bandı ve düşük RSI ile aşırı satıştan dönüş arar; spotta %2 hedefler.", enabledKey: "mean_reversion_enabled", timeframeKey: "mean_reversion_timeframe", params: [] },
*/
];

export default function StrategiesPage() {
    const [cfg, setCfg] = useState<Config | null>(null);
    const [draft, setDraft] = useState<Partial<Config>>({});
    const [active, setActive] = useState(0);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [pageTab, setPageTab] = useState<"strategies" | "llm">("strategies");

    useEffect(() => {
    fetch(`${API_BASE}/api/config`)
            .then((r) => r.json())
            .then((d) => { setCfg(d); setDraft(d); })
            .catch(() => setError("Backend'e bağlanılamadı (http://localhost:8004)"));
    }, []);

    const save = async () => {
        setSaving(true);
        setError(null);
        try {
      const res = await fetch(`${API_BASE}/api/config`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(draft)
            });
            const updated = await res.json();
            setCfg(updated);
            setDraft(updated);
            setSaved(true);
            setTimeout(() => setSaved(false), 2000);
        } catch {
            setError("Kaydedilemedi - backend bağlantısını kontrol et");
        } finally {
            setSaving(false);
        }
    };

    const num = (v: any) => (typeof v === "number" ? v : parseFloat(v));
    const s = STRATEGIES[active];

    return (
        <div className="max-w-5xl mx-auto space-y-6">
            <header className="flex items-center justify-between">
                <div>
                    <h1 className="font-mono text-xl font-bold tracking-tight">
                        <span className="text-neon-green">STRATEJİLER</span>
                    </h1>
                    <p className="eyebrow mt-1">Her strateji ayrı sekme · aktif/pasif & parametreler</p>
                </div>
                {cfg && (
                    <button
                        onClick={save}
                        disabled={saving}
                        className={`px-5 py-2 rounded-lg border font-mono text-sm transition-colors ${saved
                            ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                            : "border-neon-green/40 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"
                            }`}
                    >
                        {saving ? "KAYDEDİLİYOR..." : saved ? "✓ KAYDEDİLDİ" : "KAYDET"}
                    </button>
                )}
            </header>

            {error && (
                <div className="card border-neon-red/40 bg-neon-red/5">
                    <p className="font-mono text-sm text-neon-red">{error}</p>
                </div>
            )}

            {!cfg && !error && (
                <div className="card"><p className="font-mono text-sm text-bunker-muted animate-pulse">Yükleniyor...</p></div>
            )}

            {cfg && (
                <>
                    <div className="flex gap-2 border-b border-bunker-800 pb-2">
                        <button onClick={() => setPageTab("strategies")} className={`min-h-11 px-4 rounded-lg border font-mono text-sm ${pageTab === "strategies" ? "border-neon-green/50 text-neon-green" : "border-bunker-700 text-bunker-muted"}`}>STRATEJİ AYARLARI</button>
                        <button onClick={() => setPageTab("llm")} className={`min-h-11 px-4 rounded-lg border font-mono text-sm ${pageTab === "llm" ? "border-yellow-400/50 text-yellow-300" : "border-bunker-700 text-bunker-muted"}`}>LLM ANALİZİ</button>
                    </div>
                    {pageTab === "llm" && <StrategyLlm />}
                    {pageTab === "strategies" && <>
                    <div className="flex gap-2 flex-wrap">
                        {STRATEGIES.map((st, i) => {
                            const enabled = !!draft[st.enabledKey];
                            return (
                                <button
                                    key={st.key}
                                    onClick={() => setActive(i)}
                                    className={`px-4 py-2.5 rounded-lg border font-mono text-sm transition-colors ${active === i
                                        ? "border-neon-green/50 bg-neon-green/10 text-neon-green"
                                        : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"
                                        }`}
                                >
                                    <span className="mr-2">{st.icon}</span>{st.name}
                                    <span className={`ml-2 inline-block w-2 h-2 rounded-full ${enabled ? "bg-neon-green" : "bg-bunker-600"}`} />
                                </button>
                            );
                        })}
                    </div>

                    <div className="card bg-bunker-950">
                        <div className="flex justify-between items-start mb-4">
                            <div>
                                <p className="font-mono text-lg font-bold text-white">{s.icon} {s.name}</p>
                                <p className="text-sm text-bunker-muted mt-2 max-w-2xl">{s.desc}</p>
                            </div>
                            <button
                                onClick={() => setDraft((d) => ({ ...d, [s.enabledKey]: !d[s.enabledKey] }))}
                                className={`px-4 py-2 rounded-lg border font-mono text-sm transition-colors shrink-0 ${draft[s.enabledKey]
                                    ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                                    : "border-bunker-700 bg-bunker-900 text-bunker-muted"
                                    }`}
                            >
                                {draft[s.enabledKey] ? "● AKTİF" : "○ PASİF"}
                            </button>
                        </div>

                        <div className="space-y-4">
                            <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                                <div className="min-w-0">
                                    <p className="font-mono text-sm text-white">Timeframe</p>
                                    <p className="text-xs text-bunker-muted mt-0.5">Stratejinin takip edeceği mum periyodu</p>
                                </div>
                                <select
                                    value={String(draft[s.timeframeKey] ?? "5m")}
                                    onChange={(e) => setDraft((d) => ({ ...d, [s.timeframeKey]: e.target.value }))}
                                    className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                                >
                                    {TIMEFRAMES.map((tf) => (
                                        <option key={tf} value={tf}>{tf}</option>
                                    ))}
                                </select>
                            </div>
                            {s.params.map((p) => (
                                <div key={p.key as string} className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                                    <div className="min-w-0">
                                        <p className="font-mono text-sm text-white">{p.label}</p>
                                        <p className="text-xs text-bunker-muted mt-0.5">{p.hint}</p>
                                    </div>
                                    <input
                                        type="number"
                                        step={p.step}
                                        min={p.min}
                                        value={num(draft[p.key])}
                                        onChange={(e) => setDraft((d) => ({ ...d, [p.key]: e.target.value === "" ? NaN : Number(e.target.value) }))}
                                        className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                                    />
                                </div>
                            ))}
                            {s.key === "UT" && (
                                <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                                    <div className="min-w-0">
                                        <p className="font-mono text-sm text-white">Heikin Ashi Mumları</p>
                                        <p className="text-xs text-bunker-muted mt-0.5">Sinyalleri HA mumlarından al</p>
                                    </div>
                                    <button
                                        onClick={() => setDraft((d) => ({ ...d, ut_heikin_ashi: !d.ut_heikin_ashi }))}
                                        className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${draft.ut_heikin_ashi
                                            ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                                            : "border-bunker-700 bg-bunker-900 text-bunker-muted"
                                            }`}
                                    >
                                        {draft.ut_heikin_ashi ? "AÇIK" : "KAPALI"}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                    </>}
                </>
            )}
        </div>
    );
}
