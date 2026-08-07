"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

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

const STRATEGIES = [
    { key: "EMA_VWAP_PULLBACK", name: "EMA + VWAP Pullback", icon: "📈" },
    { key: "BB_SQUEEZE_ORDERFLOW", name: "BB Squeeze + Order-Flow Confirmation", icon: "📦" },
    { key: "ORDERFLOW", name: "Order-Flow Imbalance", icon: "🌊" },
    { key: "MOMENTUM", name: "Multi-Timeframe Momentum Ranking", icon: "⚡" },
    { key: "VWAP_MEAN_REVERSION", name: "VWAP Mean Reversion", icon: "↩️" },
    { key: "KELTNER_BREAKOUT", name: "Keltner Breakout", icon: "🔔" },
    { key: "CHOP_TREND_FILTER", name: "CHOP Trend Filter", icon: "📐" },
    { key: "DONCHIAN_BREAKOUT", name: "Donchian Breakout", icon: "🏹" },
];

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];
const SYMBOLS = ["BTCTRY", "ETHTRY", "SOLTRY", "XRPTRY", "ADATRY", "AVAXTRY", "LINKTRY", "NEARTRY", "APTTRY", "ARBTRY", "OPTRY", "SUITRY", "DOGETRY", "INJTRY", "WLDTRY"];

const fmtTL = (v: number) =>
    v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtTime = (ts: number) =>
    new Date(ts * 1000).toLocaleString("tr-TR", { hour12: false });
const fmtTradeTime = (ts?: number) => ts ? fmtTime(ts) : "—";

export default function BacktestPage() {
    const [symbol, setSymbol] = useState("BTCTRY");
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

    const loadHistory = () => {
        fetch(`${API_BASE}/api/backtests?limit=50`)
            .then((r) => r.json())
            .then((d) => setHistory(d.backtests))
            .catch(() => { });
    };

    useEffect(() => { loadHistory(); }, []);

    const run = async () => {
        setRunning(true);
        setError(null);
        setResult(null);
        try {
            const res = await fetch(`${API_BASE}/api/backtest/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ symbol, interval, days_back: daysBack, strategy, order_size: orderSize })
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
        await fetch(`${API_BASE}/api/backtests/${id}`, { method: "DELETE" });
        loadHistory();
    };

    const runRobustness = async () => {
        setRobustnessRunning(true);
        try {
            const res = await fetch(`${API_BASE}/api/backtest/robustness`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, interval, strategy, windows: [14, 30, 60] }) });
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
                            {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
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
                        <input type="number" min={100} step={100} value={orderSize}
                            onChange={(e) => setOrderSize(parseInt(e.target.value) || 500)}
                            className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm" />
                    </div>
                    <div className="flex items-end">
                        <button onClick={run} disabled={running}
                            className="w-full px-4 py-2 rounded-lg border border-neon-green/40 bg-neon-green/10 text-neon-green font-mono text-sm hover:bg-neon-green/20 disabled:opacity-50">
                            {running ? "ÇALIŞIYOR..." : "▶ TEST ET"}
                        </button>
                    </div>
                </div>
                <p className="text-[11px] text-bunker-muted mt-3 font-mono">
                    {strat?.icon} {strat?.name} · komisyon + spread + slippage dahil · kronolojik OOS doğrulaması zorunlu · Başlangıç 10.000 ₺
                </p>
                <button onClick={runRobustness} disabled={robustnessRunning}
                    className="mt-3 px-4 py-2 rounded-lg border border-yellow-400/40 bg-yellow-400/10 text-yellow-300 font-mono text-xs disabled:opacity-50">
                    {robustnessRunning ? "DAYANIKLILIK TESTİ..." : "↗ 14/30/60 GÜN DAYANIKLILIK TESTİ"}
                </button>
            </div>

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
                            <span className="text-neon-green">{result.symbol}</span> · {result.interval} · {result.strategy} · {result.days_back} gün
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
                                    <td className="p-3 font-bold text-white">{h.symbol}</td>
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
