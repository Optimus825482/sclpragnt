"use client";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type BacktestResult = {
    id: number;
    timestamp: number;
    symbol: string;
    interval: string;
    strategy: string;
    params: Record<string, number | boolean>;
    days_back: number;
    initial_balance: number;
    final_balance: number;
    net_pnl: number;
    net_pnl_pct: number;
    total_trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    order_size: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    trailing_stop_pct: number;
    trades: { side: string; entry: number; exit: number; pnl: number; commission?: number; reason: string; entry_time?: number; exit_time?: number; bars_held?: number }[];
    validation_status?: "PASS" | "FAIL";
    oos_validation?: { positive_oos_folds?: number; folds?: number; net_pnl?: number };
};

type BbMfiBacktestSettings = {
    bbPeriod: number;
    bbStdDev: number;
    mfiPeriod: number;
    rsiPeriod: number;
    v1RsiLowerLevel: number;
    v1RsiUpperLevel: number;
    v2RsiLowerLevel: number;
    v2RsiUpperLevel: number;
    mfiEntryMax: number;
    rsiExitMin: number;
    mfiExitMin: number;
    stopLossPct: number;
    takeProfitPct: number;
    orderPct: number;
    pyramidingLayers: number;
};

const DEFAULT_BB_MFI_SETTINGS: BbMfiBacktestSettings = {
    bbPeriod: 21,
    bbStdDev: 2,
    mfiPeriod: 16,
    rsiPeriod: 13,
    v1RsiLowerLevel: 42,
    v1RsiUpperLevel: 70,
    v2RsiLowerLevel: 42,
    v2RsiUpperLevel: 76,
    mfiEntryMax: 59,
    rsiExitMin: 69,
    mfiExitMin: 69,
    stopLossPct: 8.882,
    takeProfitPct: 2.317,
    orderPct: 10,
    pyramidingLayers: 2,
};

const numberOr = (value: unknown, fallback: number) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const STRATEGIES = [
    { key: "EMA_VWAP_PULLBACK", name: "EMA + VWAP Pullback", icon: "📈" },
    { key: "BB_SQUEEZE_ORDERFLOW", name: "BB Squeeze + Order-Flow Confirmation", icon: "📦" },
    { key: "ORDERFLOW", name: "Order-Flow Imbalance", icon: "🌊" },
    { key: "MOMENTUM", name: "Multi-Timeframe Momentum Ranking", icon: "⚡" },
    { key: "VWAP_MEAN_REVERSION", name: "VWAP Mean Reversion", icon: "↩️" },
    { key: "BB_MFI_MEAN_REVERSION", name: "BB + MFI Mean Reversion", icon: "🎯" },
    { key: "KELTNER_BREAKOUT", name: "Keltner Breakout", icon: "🔔" },
    { key: "CHOP_TREND_FILTER", name: "CHOP Trend Filter", icon: "📐" },
    { key: "DONCHIAN_BREAKOUT", name: "Donchian Breakout", icon: "🏹" },
];

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];

const fmtTL = (v: number) =>
    v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtTime = (ts: number) =>
    new Date(ts * 1000).toLocaleString("tr-TR", { hour12: false });
const fmtTradeTime = (ts?: number) => ts ? fmtTime(ts) : "—";

function BbMfiInput({ label, value, onChange, suffix, ...inputProps }: {
    label: string;
    value: number;
    onChange: (value: string) => void;
    suffix?: string;
    min?: number;
    max?: number;
    step?: number;
}) {
    return <label className="rounded-xl border border-bunker-800 bg-bunker-900 p-3">
        <span className="font-mono text-xs text-bunker-muted">{label}</span>
        <div className="mt-1 flex items-center gap-2">
            <input type="number" value={value} onChange={(event) => onChange(event.target.value)}
                className="min-w-0 flex-1 bg-transparent font-mono text-sm text-white outline-none focus:text-neon-green" {...inputProps} />
            {suffix && <span className="font-mono text-xs text-bunker-muted">{suffix}</span>}
        </div>
    </label>;
}

export default function BacktestPage() {
    const [symbol, setSymbol] = useState("BTCTRY");
    const [symbols, setSymbols] = useState<string[]>(["BTCTRY"]);
    const [interval, setInterval] = useState("5m");
    const [daysBack, setDaysBack] = useState(30);
    const [strategy, setStrategy] = useState("EMA_VWAP_PULLBACK");
    const [orderSize, setOrderSize] = useState(500);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<BacktestResult | null>(null);
    const [history, setHistory] = useState<BacktestResult[]>([]);
    const [robustness, setRobustness] = useState<any>(null);
    const [robustnessRunning, setRobustnessRunning] = useState(false);
    const [bbMfiSettingsOpen, setBbMfiSettingsOpen] = useState(false);
    const [bbMfiSettings, setBbMfiSettings] = useState<BbMfiBacktestSettings>(DEFAULT_BB_MFI_SETTINGS);

    const loadHistory = () => {
        apiRequest(`${API_BASE}/api/backtests?limit=50`)
            .then((r) => r.json())
            .then((d) => setHistory(d.backtests))
            .catch(() => { });
    };

    useEffect(() => {
        loadHistory();
        Promise.all([
            apiRequest(`${API_BASE}/api/config`, { cache: "no-store" }).then((r) => r.json()),
            apiRequest(`${API_BASE}/api/symbol-activity`, { cache: "no-store" }).then((r) => r.json()),
        ]).then(([configData, activityData]) => {
            const configured = Array.isArray(configData.symbols) ? configData.symbols : [];
            const active = Object.values(activityData.statuses || {})
                .filter((item: any) => item.status === "ACTIVE")
                .map((item: any) => item.symbol);
            const list = (active.length ? active : configured).length ? [...(active.length ? active : configured)].sort() : ["BTCTRY"];
            setSymbols(list);
            setSymbol((current) => list.includes(current) ? current : list[0]);
            if (configData.active_strategy) setStrategy(configData.active_strategy);
            setBbMfiSettings({
                bbPeriod: numberOr(configData.bb_mfi_bb_period, DEFAULT_BB_MFI_SETTINGS.bbPeriod),
                bbStdDev: numberOr(configData.bb_mfi_bb_std_dev, DEFAULT_BB_MFI_SETTINGS.bbStdDev),
                mfiPeriod: numberOr(configData.bb_mfi_mfi_period, DEFAULT_BB_MFI_SETTINGS.mfiPeriod),
                rsiPeriod: numberOr(configData.bb_mfi_rsi_period, DEFAULT_BB_MFI_SETTINGS.rsiPeriod),
                v1RsiLowerLevel: numberOr(configData.bb_mfi_v1_rsi_lower_level, DEFAULT_BB_MFI_SETTINGS.v1RsiLowerLevel),
                v1RsiUpperLevel: numberOr(configData.bb_mfi_v1_rsi_upper_level, DEFAULT_BB_MFI_SETTINGS.v1RsiUpperLevel),
                v2RsiLowerLevel: numberOr(configData.bb_mfi_v2_rsi_lower_level, DEFAULT_BB_MFI_SETTINGS.v2RsiLowerLevel),
                v2RsiUpperLevel: numberOr(configData.bb_mfi_v2_rsi_upper_level, DEFAULT_BB_MFI_SETTINGS.v2RsiUpperLevel),
                mfiEntryMax: numberOr(configData.bb_mfi_entry_mfi_max, DEFAULT_BB_MFI_SETTINGS.mfiEntryMax),
                rsiExitMin: numberOr(configData.bb_mfi_exit_rsi_min, DEFAULT_BB_MFI_SETTINGS.rsiExitMin),
                mfiExitMin: numberOr(configData.bb_mfi_exit_mfi_min, DEFAULT_BB_MFI_SETTINGS.mfiExitMin),
                stopLossPct: numberOr(configData.bb_mfi_stop_loss_pct, DEFAULT_BB_MFI_SETTINGS.stopLossPct / 100) * 100,
                takeProfitPct: numberOr(configData.bb_mfi_take_profit_pct, DEFAULT_BB_MFI_SETTINGS.takeProfitPct / 100) * 100,
                orderPct: numberOr(configData.order_pct, DEFAULT_BB_MFI_SETTINGS.orderPct / 100) * 100,
                pyramidingLayers: numberOr(configData.pyramiding_layers, DEFAULT_BB_MFI_SETTINGS.pyramidingLayers),
            });
        }).catch(() => undefined);
    }, []);

    const run = async () => {
        setRunning(true);
        setError(null);
        setResult(null);
        try {
            const bbMfiPayload = strategy === "BB_MFI_MEAN_REVERSION" ? {
                params: {
                    bb_mfi_bb_period: bbMfiSettings.bbPeriod,
                    bb_mfi_bb_std_dev: bbMfiSettings.bbStdDev,
                    bb_mfi_mfi_period: bbMfiSettings.mfiPeriod,
                    bb_mfi_rsi_period: bbMfiSettings.rsiPeriod,
                    bb_mfi_v1_rsi_lower_level: bbMfiSettings.v1RsiLowerLevel,
                    bb_mfi_v1_rsi_upper_level: bbMfiSettings.v1RsiUpperLevel,
                    bb_mfi_v2_rsi_lower_level: bbMfiSettings.v2RsiLowerLevel,
                    bb_mfi_v2_rsi_upper_level: bbMfiSettings.v2RsiUpperLevel,
                    bb_mfi_entry_mfi_max: bbMfiSettings.mfiEntryMax,
                    bb_mfi_exit_rsi_min: bbMfiSettings.rsiExitMin,
                    bb_mfi_exit_mfi_min: bbMfiSettings.mfiExitMin,
                    bb_mfi_stop_loss_pct: bbMfiSettings.stopLossPct / 100,
                    bb_mfi_take_profit_pct: bbMfiSettings.takeProfitPct / 100,
                },
                order_pct: bbMfiSettings.orderPct / 100,
                pyramiding_layers: bbMfiSettings.pyramidingLayers,
                stop_loss_pct: bbMfiSettings.stopLossPct / 100,
                take_profit_pct: bbMfiSettings.takeProfitPct / 100,
            } : {};
            const res = await apiRequest(`${API_BASE}/api/backtest/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ symbol, interval, days_back: daysBack, strategy, order_size: orderSize, ...bbMfiPayload })
            });
            const d = await res.json();
            if (!d.ok) { setError(d.error || "Backtest başarısız"); return; }
            setResult(d.result);
            loadHistory();
        } catch {
            setError("Backend'e bağlanılamadı (http://localhost:8004)");
        } finally {
            setRunning(false);
        }
    };

    const remove = async (id: number) => {
        await apiRequest(`${API_BASE}/api/backtests/${id}`, { method: "DELETE" });
        loadHistory();
    };

    const startTest = () => {
        if (strategy === "BB_MFI_MEAN_REVERSION") {
            setBbMfiSettingsOpen(true);
            return;
        }
        void run();
    };

    const updateBbMfiSetting = (key: keyof BbMfiBacktestSettings, value: string) => {
        const nextValue = Number(value);
        setBbMfiSettings((current) => ({ ...current, [key]: Number.isFinite(nextValue) ? nextValue : current[key] }));
    };

    const runRobustness = async () => {
        setRobustnessRunning(true);
        try {
            const res = await apiRequest(`${API_BASE}/api/backtest/robustness`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, interval, strategy, windows: [14, 30, 60] }) });
            setRobustness(await res.json());
        } catch { setRobustness({ ok: false, error: "Robustness testi çalıştırılamadı" }); }
        finally { setRobustnessRunning(false); }
    };

    const strat = STRATEGIES.find((s) => s.key === strategy);
    const resultProfitFactor = result ? (() => { const gains = result.trades.filter(t => t.pnl > 0).reduce((a, t) => a + t.pnl, 0); const losses = Math.abs(result.trades.filter(t => t.pnl < 0).reduce((a, t) => a + t.pnl, 0)); return losses ? gains / losses : null; })() : null;
    const resultCommission = result ? result.trades.reduce((a, t) => a + Number(t.commission || 0), 0) : 0;

    return (
        <div className="max-w-7xl mx-auto space-y-6">
            <header>
                <h1 className="font-mono text-xl font-bold tracking-tight">
                    <span className="text-neon-green">BACKTEST</span> LAB
                </h1>
                <p className="eyebrow mt-1">Tarihsel veriyle strateji testi · sonuçlar DB'de saklanır</p>
            </header>

            <div className="card">
                <div className="grid md:grid-cols-6 gap-4">
                    <div>
                        <label className="eyebrow block mb-1.5">SEMBOL</label>
                        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm">
                            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="eyebrow block mb-1.5">TIMEFRAME</label>
                        <select value={interval} onChange={(e) => setInterval(e.target.value)}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm">
                            {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="eyebrow block mb-1.5">GÜN</label>
                        <input type="number" min={1} max={365} value={daysBack}
                            onChange={(e) => setDaysBack(parseInt(e.target.value) || 30)}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm" />
                    </div>
                    <div>
                        <label className="eyebrow block mb-1.5">STRATEJİ</label>
                        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm">
                            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="eyebrow block mb-1.5">İŞLEM (₺)</label>
                        <input type="number" min={100} step={100} value={strategy === "BB_MFI_MEAN_REVERSION" ? 1000 : orderSize}
                            onChange={(e) => setOrderSize(parseInt(e.target.value) || 500)}
                            disabled={strategy === "BB_MFI_MEAN_REVERSION"}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm" />
                    </div>
                    <div className="flex items-end">
                        <button onClick={startTest} disabled={running}
                            className="w-full px-4 py-2 rounded-lg border border-neon-green/40 bg-neon-green/10 text-neon-green font-mono text-sm hover:bg-neon-green/20 disabled:opacity-50">
                            {running ? "ÇALIŞIYOR..." : "▶ TEST ET"}
                        </button>
                    </div>
                </div>
                <p className="text-[11px] text-bunker-muted mt-3 font-mono">
                    {strat?.icon} {strat?.name} · komisyon + spread + slippage dahil · kronolojik OOS doğrulaması zorunlu · Başlangıç 10.000 ₺
                </p>
                {strategy === "BB_MFI_MEAN_REVERSION" && <p className="mt-2 text-[11px] font-mono text-neon-yellow">Pine v3 Flawless Victory: giriş BB(21, 2,0) altı + MFI(16)&lt;59; sinyal çıkışı RSI(13)&gt;69 + MFI(16)&gt;69; SL %8,882 / TP %2,317. Başlangıç 10.000 ₺, her giriş özsermayenin %10&apos;u ve en çok 2 katmandır. Komisyon, spread ve slippage sonucu korumacı yapar; TradingView&apos;deki maliyetsiz sonuçla birebir kıyaslanmamalıdır.</p>}
                {strategy === "BB_MFI_MEAN_REVERSION" && <button onClick={() => setBbMfiSettingsOpen(true)}
                    className="mt-3 px-4 py-2 rounded-lg border border-neon-green/35 bg-bunker-900 text-neon-green font-mono text-xs hover:bg-neon-green/10">
                    ⚙ AYARLAR
                </button>}
                <button onClick={runRobustness} disabled={robustnessRunning}
                    className="mt-3 px-4 py-2 rounded-lg border border-yellow-400/40 bg-yellow-400/10 text-yellow-300 font-mono text-xs disabled:opacity-50">
                    {robustnessRunning ? "DAYANIKLILIK TESTİ..." : "↗ 14/30/60 GÜN DAYANIKLILIK TESTİ"}
                </button>
            </div>

            {bbMfiSettingsOpen && <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="bb-mfi-settings-title">
                <button aria-label="Ayarlar penceresini kapat" className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={() => setBbMfiSettingsOpen(false)} />
                <div className="relative w-full max-w-2xl max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-neon-green/30 bg-bunker-950 shadow-2xl shadow-black/60">
                    <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-bunker-800 bg-bunker-950/95 px-5 py-4 backdrop-blur">
                        <div>
                            <p className="eyebrow text-neon-green">BB + MFI MEAN REVERSION</p>
                            <h2 id="bb-mfi-settings-title" className="mt-1 font-mono text-lg font-bold">BACKTEST AYARLARI</h2>
                            <p className="mt-1 text-xs text-bunker-muted">Canlı yapılandırmadan başlatıldı; burada yaptığınız değişiklikler yalnızca bu backtest isteğini etkiler.</p>
                        </div>
                        <button aria-label="Kapat" onClick={() => setBbMfiSettingsOpen(false)} className="rounded-lg border border-bunker-700 px-2.5 py-1.5 font-mono text-sm text-bunker-muted hover:border-neon-green/40 hover:text-white">×</button>
                    </div>
                    <div className="space-y-5 p-5">
                        <section>
                            <p className="eyebrow text-neon-green">GİRİŞ</p>
                            <div className="mt-2 grid gap-3 sm:grid-cols-2">
                                <BbMfiInput label="BB periyodu" value={bbMfiSettings.bbPeriod} min={5} step={1} onChange={(value) => updateBbMfiSetting("bbPeriod", value)} />
                                <BbMfiInput label="BB std. sapma" value={bbMfiSettings.bbStdDev} min={0.1} step={0.1} onChange={(value) => updateBbMfiSetting("bbStdDev", value)} />
                                <BbMfiInput label="MFI periyodu" value={bbMfiSettings.mfiPeriod} min={2} step={1} onChange={(value) => updateBbMfiSetting("mfiPeriod", value)} />
                                <BbMfiInput label="RSI periyodu" value={bbMfiSettings.rsiPeriod} min={2} step={1} onChange={(value) => updateBbMfiSetting("rsiPeriod", value)} />
                                <BbMfiInput label="v3 MFI alt seviye (giriş)" value={bbMfiSettings.mfiEntryMax} min={0} max={100} step={1} suffix="<" onChange={(value) => updateBbMfiSetting("mfiEntryMax", value)} />
                            </div>
                        </section>
                        <section>
                            <p className="eyebrow text-sky-300">PINE v1 / v2 RSI SEVİYELERİ</p>
                            <div className="mt-2 grid gap-3 sm:grid-cols-2">
                                <BbMfiInput label="v1 RSI alt seviye" value={bbMfiSettings.v1RsiLowerLevel} min={0} max={100} step={1} onChange={(value) => updateBbMfiSetting("v1RsiLowerLevel", value)} />
                                <BbMfiInput label="v1 RSI üst seviye" value={bbMfiSettings.v1RsiUpperLevel} min={0} max={100} step={1} onChange={(value) => updateBbMfiSetting("v1RsiUpperLevel", value)} />
                                <BbMfiInput label="v2 RSI alt seviye" value={bbMfiSettings.v2RsiLowerLevel} min={0} max={100} step={1} onChange={(value) => updateBbMfiSetting("v2RsiLowerLevel", value)} />
                                <BbMfiInput label="v2 RSI üst seviye" value={bbMfiSettings.v2RsiUpperLevel} min={0} max={100} step={1} onChange={(value) => updateBbMfiSetting("v2RsiUpperLevel", value)} />
                            </div>
                        </section>
                        <section>
                            <p className="eyebrow text-yellow-300">SİNYAL ÇIKIŞI VE RİSK</p>
                            <div className="mt-2 grid gap-3 sm:grid-cols-2">
                                <BbMfiInput label="v3 RSI üst seviye (çıkış)" value={bbMfiSettings.rsiExitMin} min={0} max={100} step={1} suffix=">" onChange={(value) => updateBbMfiSetting("rsiExitMin", value)} />
                                <BbMfiInput label="v3 MFI üst seviye (çıkış)" value={bbMfiSettings.mfiExitMin} min={0} max={100} step={1} suffix=">" onChange={(value) => updateBbMfiSetting("mfiExitMin", value)} />
                                <BbMfiInput label="Stop-loss" value={bbMfiSettings.stopLossPct} min={0.1} max={99} step={0.001} suffix="%" onChange={(value) => updateBbMfiSetting("stopLossPct", value)} />
                                <BbMfiInput label="Take-profit" value={bbMfiSettings.takeProfitPct} min={0.1} max={99} step={0.001} suffix="%" onChange={(value) => updateBbMfiSetting("takeProfitPct", value)} />
                            </div>
                        </section>
                        <section>
                            <p className="eyebrow text-neon-green">POZİSYON BOYUTU</p>
                            <div className="mt-2 grid gap-3 sm:grid-cols-2">
                                <BbMfiInput label="Özsermayeden işlem" value={bbMfiSettings.orderPct} min={0.1} max={100} step={0.5} suffix="%" onChange={(value) => updateBbMfiSetting("orderPct", value)} />
                                <BbMfiInput label="Piramitleme katmanı" value={bbMfiSettings.pyramidingLayers} min={1} max={10} step={1} onChange={(value) => updateBbMfiSetting("pyramidingLayers", value)} />
                            </div>
                        </section>
                    </div>
                    <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-bunker-800 bg-bunker-950/95 px-5 py-4 backdrop-blur">
                        <p className="max-w-sm text-[11px] font-mono text-bunker-muted">Canlı ayarlar kaydedilmez ve paper canlı akışına gönderilmez.</p>
                        <div className="flex gap-2">
                            <button onClick={() => setBbMfiSettingsOpen(false)} className="rounded-lg border border-bunker-700 px-3 py-2 font-mono text-xs text-bunker-muted hover:text-white">VAZGEÇ</button>
                            <button onClick={() => { setBbMfiSettingsOpen(false); void run(); }} disabled={running} className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-3 py-2 font-mono text-xs text-neon-green hover:bg-neon-green/20 disabled:opacity-50">▶ AYARLARLA TEST ET</button>
                        </div>
                    </div>
                </div>
            </div>}

            {robustness && <div className="card border-yellow-400/20 bg-yellow-400/5">
                <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="eyebrow text-yellow-300">DAYANIKLILIK / MALİYET SONRASI</p><p className="text-xs text-bunker-muted mt-1">Bu test komisyon, spread ve slippage varsayımlarıyla kronolojik OOS fold sonuçlarını karşılaştırır.</p></div><span className={`font-mono font-bold ${robustness.walk_forward_assessment?.status === "STABLE" ? "text-neon-green" : "text-yellow-300"}`}>{robustness.walk_forward_assessment?.status || "—"}</span></div>
                <div className="grid sm:grid-cols-3 gap-3 mt-4 text-sm font-mono">{(robustness.windows || []).map((w: any) => <div key={w.days_back} className="border border-bunker-800 rounded-lg p-3"><p className="eyebrow">{w.days_back} GÜN</p><p className={Number(w.net_pnl) >= 0 ? "text-neon-green mt-1" : "text-neon-red mt-1"}>₺{fmtTL(Number(w.net_pnl || 0))}</p><p className="text-bunker-muted text-xs mt-1">{w.trades || 0} işlem · PF {w.profit_factor ?? "—"}</p></div>)}</div>
                {robustness.error && <p className="text-sm text-neon-red mt-3">{robustness.error}</p>}
            </div>}

            {error && (
                <div className="card border-neon-red/40 bg-neon-red/5">
                    <p className="font-mono text-sm text-neon-red">{error}</p>
                </div>
            )}

            {result && (
                <div className="card bg-bunker-900 border-neon-green/20">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="font-mono font-bold">
                            <span className="text-neon-green"><SymbolLink symbol={result.symbol} className="text-neon-green hover:text-white" /></span> · {result.interval} · {result.strategy} · {result.days_back} gün
                        </h2>
                        <span className={`eyebrow ${result.validation_status === "PASS" ? "text-neon-green" : "text-yellow-300"}`}>OOS {result.validation_status || "—"} · {fmtTime(result.timestamp)}</span>
                    </div>
                    <div className="grid md:grid-cols-4 gap-4">
                        <div>
                            <p className="eyebrow">NET PnL</p>
                            <p className={`font-mono text-2xl font-bold mt-1 ${result.net_pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                {result.net_pnl >= 0 ? "+" : ""}₺{fmtTL(result.net_pnl)}
                                <span className="text-sm ml-1">({result.net_pnl_pct >= 0 ? "+" : ""}{result.net_pnl_pct}%)</span>
                            </p>
                        </div>
                        <div>
                            <p className="eyebrow">SON BAKİYE</p>
                            <p className="font-mono text-2xl font-bold text-white mt-1">₺{fmtTL(result.final_balance)}</p>
                        </div>
                        <div>
                            <p className="eyebrow">İŞLEM / KAZANMA</p>
                            <p className="font-mono text-2xl font-bold text-white mt-1">
                                {result.total_trades} <span className="text-sm text-bunker-muted">· %{result.win_rate}</span>
                            </p>
                        </div>
                        <div>
                            <p className="eyebrow">KÂR / ZARAR</p>
                            <p className="font-mono text-2xl font-bold mt-1">
                                <span className="text-neon-green">{result.wins}</span>
                                <span className="text-bunker-muted"> / </span>
                                <span className="text-neon-red">{result.losses}</span>
                            </p>
                        </div>
                    </div>
                    <div className="grid sm:grid-cols-3 gap-3 mt-4 text-sm font-mono">
                        <div className="border border-bunker-800 rounded-lg p-3"><p className="eyebrow">KOMİSYON</p><p className="mt-1 text-yellow-300">₺{fmtTL(resultCommission)}</p></div>
                        <div className="border border-bunker-800 rounded-lg p-3"><p className="eyebrow">PROFIT FACTOR</p><p className="mt-1">{resultProfitFactor == null ? "—" : resultProfitFactor.toFixed(2)}</p></div>
                        <div className="border border-bunker-800 rounded-lg p-3"><p className="eyebrow">DEĞERLENDİRME</p><p className={`mt-1 font-bold ${result.net_pnl > 0 && (resultProfitFactor == null || resultProfitFactor >= 1) ? "text-neon-green" : "text-neon-red"}`}>{result.net_pnl > 0 && (resultProfitFactor == null || resultProfitFactor >= 1) ? "MALİYET SONRASI POZİTİF" : "MALİYET SONRASI ZAYIF"}</p></div>
                    </div>
                    {result.trades.length > 0 && (
                        <div className="mt-4 overflow-x-auto">
                            <table className="w-full font-mono text-xs">
                                <thead>
                                    <tr className="text-left text-bunker-muted border-b border-bunker-800">
                                        <th className="p-2">#</th>
                                        <th className="p-2">AÇILIŞ ZAMANI</th>
                                        <th className="p-2">KAPANIŞ ZAMANI</th>
                                        <th className="p-2">BAR</th>
                                        <th className="p-2">GİRİŞ</th>
                                        <th className="p-2">ÇIKIŞ</th>
                                        <th className="p-2">PnL</th>
                                        <th className="p-2">NEDEN</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {result.trades.map((t, i) => (
                                        <tr key={i} className="border-b border-bunker-800/50">
                                            <td className="p-2 text-bunker-muted">{i + 1}</td>
                                            <td className="p-2 whitespace-nowrap">{fmtTradeTime(t.entry_time)}</td>
                                            <td className="p-2 whitespace-nowrap">{fmtTradeTime(t.exit_time)}</td>
                                            <td className="p-2 text-center">{t.bars_held ?? "—"}</td>
                                            <td className="p-2">₺{fmtTL(t.entry)}</td>
                                            <td className="p-2">₺{fmtTL(t.exit)}</td>
                                            <td className={`p-2 font-bold ${t.pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                                {t.pnl >= 0 ? "+" : ""}₺{fmtTL(t.pnl)}
                                            </td>
                                            <td className="p-2 text-bunker-muted">{t.reason}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            <div className="card bg-bunker-950 p-0 overflow-hidden">
                <div className="p-4 border-b border-bunker-800 flex items-center justify-between">
                    <h2 className="font-mono font-bold text-sm">KAYITLI TESTLER</h2>
                    <span className="eyebrow">{history.length} kayıt</span>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full font-mono text-sm">
                        <thead>
                            <tr className="text-left text-bunker-muted text-xs border-b border-bunker-800">
                                <th className="p-3">TARİH</th>
                                <th className="p-3">SEMBOL</th>
                                <th className="p-3">TF</th>
                                <th className="p-3">STRATEJİ</th>
                                <th className="p-3">GÜN</th>
                                <th className="p-3">İŞLEM</th>
                                <th className="p-3">KAZANMA</th>
                                <th className="p-3">NET PnL</th>
                                <th className="p-3"></th>
                            </tr>
                        </thead>
                        <tbody>
                            {history.length === 0 && (
                                <tr><td colSpan={9} className="p-4 text-bunker-muted">Henüz backtest çalıştırılmadı.</td></tr>
                            )}
                            {history.map((h) => (
                                <tr key={h.id} className="border-b border-bunker-800/50 hover:bg-bunker-800/30">
                                    <td className="p-3 text-bunker-muted">{fmtTime(h.timestamp)}</td>
                                    <td className="p-3 font-bold text-white"><SymbolLink symbol={h.symbol} className="text-white hover:text-neon-green" /></td>
                                    <td className="p-3 text-neon-yellow">{h.interval}</td>
                                    <td className="p-3">{STRATEGIES.find((s) => s.key === h.strategy)?.name ?? h.strategy}</td>
                                    <td className="p-3 text-bunker-muted">{h.days_back}</td>
                                    <td className="p-3">{h.total_trades}</td>
                                    <td className="p-3">%{h.win_rate}</td>
                                    <td className={`p-3 font-bold ${h.net_pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                        {h.net_pnl >= 0 ? "+" : ""}₺{fmtTL(h.net_pnl)}
                                    </td>
                                    <td className="p-3">
                                        <button onClick={() => remove(h.id)}
                                            className="text-bunker-muted hover:text-neon-red font-mono text-xs">SİL</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
