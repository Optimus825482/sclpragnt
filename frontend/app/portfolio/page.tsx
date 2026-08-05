"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE, WS_BASE } from "../lib/api";

const STRATEGY_LABEL: Record<string, string> = {
    EMA_VWAP_PULLBACK: "EMA + VWAP Pullback",
    BB_SQUEEZE_ORDERFLOW: "BB Squeeze + Order-Flow",
    ORDERFLOW: "Order-Flow Imbalance",
    MOMENTUM: "MTF Momentum Ranking",
    VWAP_MEAN_REVERSION: "VWAP Mean Reversion",
};

type Position = { symbol: string; entry: number; current: number; pnl_pct: number; pnl_try?: number; value: number; strategy?: string };
type Portfolio = { try: number; total_value: number; realized_pnl?: number; unrealized_pnl?: number; reconciliation_expected?: number; reconciliation_delta?: number; positions: Position[] };
type Trade = { id: number; symbol: string; strategy: string; entry_price: number; exit_price: number; pnl: number; pnl_pct: number; commission?: number; reason?: string; entry_time?: number; exit_time?: number; hold_seconds?: number };

export default function PortfolioPage() {
    const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
    const [closing, setClosing] = useState<string | null>(null);
    const [msg, setMsg] = useState<string | null>(null);
    const [trades, setTrades] = useState<Trade[]>([]);
    const [tradePage, setTradePage] = useState(1);
    const tradesPerPage = 10;

    useEffect(() => {
        let ws: WebSocket | null = null;
        let retry: ReturnType<typeof setTimeout> | null = null;
        let closed = false;

        const connect = () => {
            ws = new WebSocket(`${WS_BASE}/ws`);
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === "portfolio") setPortfolio(msg.data);
            };
            ws.onclose = () => { if (!closed) retry = setTimeout(connect, 2000); };
        };

        connect();
        return () => { closed = true; if (retry) clearTimeout(retry); ws?.close(); };
    }, []);

    useEffect(() => { fetch(`${API_BASE}/api/trades`).then((r) => r.json()).then((d) => setTrades(d.trades || [])).catch(() => undefined); }, []);

    const unrealizedPnl = portfolio?.positions.reduce((s, p) => s + (p.pnl_try ?? ((p.current - p.entry) * (p.value / p.current))), 0) ?? 0;
    const totalPnl = (portfolio?.realized_pnl ?? 0) + unrealizedPnl;
    const winRate = portfolio && portfolio.positions.length > 0
        ? (portfolio.positions.filter((p) => p.pnl_pct > 0).length / portfolio.positions.length) * 100
        : 0;

    const formatTL = (v?: number) =>
        v == null ? "0,00" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    const closePosition = async (symbol: string) => {
        setClosing(symbol);
        setMsg(null);
        try {
            const res = await fetch(`${API_BASE}/api/positions/${symbol}/close`, { method: "POST" });
            const data = await res.json();
            setMsg(data.message ?? (data.ok ? "Kapatıldı" : "Hata"));
        } catch {
            setMsg("Kapatılamadı - backend bağlantısını kontrol et");
        } finally {
            setClosing(null);
        }
    };
    const tradePageCount = Math.max(1, Math.ceil(trades.length / tradesPerPage));
    const visibleTrades = trades.slice((tradePage - 1) * tradesPerPage, tradePage * tradesPerPage);
    const formatDateTime = (ts?: number) => ts ? new Date(ts * 1000).toLocaleString("tr-TR", { hour12: false }) : "—";
    const formatDuration = (seconds?: number, entry?: number, exit?: number) => {
        const total = Math.max(0, seconds ?? (entry && exit ? exit - entry : 0));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const secs = Math.floor(total % 60);
        return hours ? `${hours}s ${minutes}dk` : minutes ? `${minutes}dk ${secs}sn` : `${secs}sn`;
    };
    const exportTrades = () => {
        const headers = ["ID", "Sembol", "Strateji", "Giriş Fiyatı", "Çıkış Fiyatı", "Komisyon", "PnL", "PnL %", "Kapanış Nedeni", "Giriş Zamanı", "Çıkış Zamanı", "Aktif Süre"];
        const rows = trades.map((t) => [t.id, t.symbol, t.strategy, t.entry_price, t.exit_price, t.commission ?? 0, t.pnl, t.pnl_pct, t.reason || "", formatDateTime(t.entry_time), formatDateTime(t.exit_time), formatDuration(t.hold_seconds, t.entry_time, t.exit_time)]);
        const csv = [headers, ...rows].map((row) => row.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(",")).join("\n");
        const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
        const a = document.createElement("a"); a.href = url; a.download = "islem-gecmisi.csv"; a.click(); URL.revokeObjectURL(url);
    };

    return (
        <div className="max-w-7xl mx-auto space-y-6">
            <header>
                <h1 className="font-mono text-xl font-bold tracking-tight">
                    <span className="text-neon-green">PORTFÖY</span> ÖZETİ
                </h1>
                <p className="eyebrow mt-1">Sanal cüzdan · canlı değerleme</p>
            </header>

            <div className="grid md:grid-cols-4 gap-4">
                <div className="card bg-bunker-900 border-neon-green/20">
                    <p className="eyebrow">TOPLAM DEĞER</p>
                    <p className="font-mono text-2xl font-bold text-white mt-1">
                        ₺{formatTL(portfolio?.total_value)}
                    </p>
                </div>
                <div className="card">
                    <p className="eyebrow">MEVCUT TL</p>
                    <p className="font-mono text-2xl font-bold text-neon-green mt-1">
                        ₺{formatTL(portfolio?.try)}
                    </p>
                </div>
                <div className="card">
                    <p className="eyebrow">AÇIK POZİSYON</p>
                    <p className="font-mono text-2xl font-bold text-white mt-1">
                        {portfolio?.positions.length ?? 0}
                    </p>
                </div>
                <div className="card">
                    <p className="eyebrow">GERÇEKLEŞMİŞ + AÇIK PnL</p>
                    <p className={`font-mono text-2xl font-bold mt-1 ${totalPnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                        {totalPnl >= 0 ? "+" : ""}₺{formatTL(totalPnl)}
                    </p>
                </div>
            </div>

            {msg && (
                <div className="card border-neon-green/40 bg-neon-green/5">
                    <p className="font-mono text-sm text-neon-green">{msg}</p>
                </div>
            )}

            <div className={`card border ${Math.abs(portfolio?.reconciliation_delta ?? 0) < 0.05 ? "border-neon-green/30 bg-neon-green/5" : "border-neon-red/50 bg-neon-red/5"}`}>
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div><p className="eyebrow">MUHASEBE MUTABAKATI</p><p className="text-xs text-bunker-muted mt-1">Toplam değer ile başlangıç bakiyesi + gerçekleşmiş/açık PnL karşılaştırması.</p></div>
                    <div className="text-right font-mono text-sm"><p className={Math.abs(portfolio?.reconciliation_delta ?? 0) < 0.05 ? "text-neon-green" : "text-neon-red"}>{Math.abs(portfolio?.reconciliation_delta ?? 0) < 0.05 ? "✓ TUTARLI" : "⚠ FARK VAR"}</p><p className="text-xs text-bunker-muted">Fark: ₺{formatTL(portfolio?.reconciliation_delta)}</p></div>
                </div>
            </div>

            <div className="w-full">
                <div className="card bg-bunker-950 p-0 overflow-hidden w-full">
                    <div className="p-4 border-b border-bunker-800 flex justify-between items-center">
                        <p className="eyebrow">POZİSYONLAR</p>
                        <span className="font-mono text-xs text-bunker-muted">Kazanma: %{winRate.toFixed(0)}</span>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full font-mono text-sm">
                            <thead>
                                <tr className="text-left text-bunker-muted text-xs border-b border-bunker-800">
                                    <th className="p-3">SEMBOL</th>
                                    <th className="p-3">STRATEJİ</th>
                                    <th className="p-3">GİRİŞ</th>
                                    <th className="p-3">ANLIK</th>
                                    <th className="p-3">PnL</th>
                                    <th className="p-3">DEĞER</th>
                                    <th className="p-3"></th>
                                </tr>
                            </thead>
                            <tbody>
                                {!portfolio?.positions.length && (
                                    <tr><td colSpan={7} className="p-4 text-bunker-muted">Açık pozisyon yok.</td></tr>
                                )}
                                {portfolio?.positions.map((p) => (
                                    <tr key={p.symbol} className="border-b border-bunker-800/50 hover:bg-bunker-800/30">
                                        <td className="p-3 font-bold"><Link href={`/symbol-analysis?symbol=${p.symbol}`} className="text-white hover:text-neon-green">{p.symbol}</Link></td>
                                        <td className="p-3 text-neon-yellow">{STRATEGY_LABEL[p.strategy ?? "UT"] ?? p.strategy}</td>
                                        <td className="p-3 text-bunker-muted">${p.entry.toFixed(4)}</td>
                                        <td className="p-3 text-bunker-muted">${p.current.toFixed(4)}</td>
                                        <td className={`p-3 font-bold ${p.pnl_pct >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                            <div>{p.pnl_pct > 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%</div>
                                            <div className="text-xs mt-1">{p.pnl_try != null && p.pnl_try >= 0 ? "+" : ""}₺{formatTL(p.pnl_try ?? 0)}</div>
                                        </td>
                                        <td className="p-3 text-white">₺{formatTL(p.value)}</td>
                                        <td className="p-3">
                                            <button
                                                onClick={() => closePosition(p.symbol)}
                                                disabled={closing === p.symbol}
                                                className="px-3 py-1.5 rounded-lg border border-neon-red/40 bg-neon-red/10 text-neon-red font-mono text-xs hover:bg-neon-red/20 transition-colors disabled:opacity-50"
                                            >
                                                {closing === p.symbol ? "KAPANIYOR..." : "✕ KAPAT"}
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

            </div>

            <section className="card bg-bunker-950 p-0 overflow-hidden">
                <div className="p-4 border-b border-bunker-800 flex flex-wrap gap-3 justify-between items-center">
                    <div><p className="eyebrow">İŞLEM GEÇMİŞİ</p><p className="text-xs text-bunker-muted mt-1">Kapanan pozisyonlar · {trades.length} kayıt</p></div>
                    <button onClick={exportTrades} disabled={!trades.length} className="px-3 py-2 rounded-lg border border-neon-green/40 text-neon-green font-mono text-xs disabled:opacity-40">CSV DIŞA AKTAR</button>
                </div>
                <div className="overflow-x-auto"><table className="w-full font-mono text-xs"><thead><tr className="text-left text-bunker-muted border-b border-bunker-800"><th className="p-3">SEMBOL</th><th className="p-3">STRATEJİ</th><th className="p-3">GİRİŞ</th><th className="p-3">ÇIKIŞ</th><th className="p-3">KOMİSYON</th><th className="p-3">PnL</th><th className="p-3">GİRİŞ ZAMANI</th><th className="p-3">ÇIKIŞ ZAMANI</th><th className="p-3">AKTİF SÜRE</th><th className="p-3">NEDEN</th></tr></thead><tbody>{visibleTrades.map((t) => <tr key={t.id} className="border-b border-bunker-800/50"><td className="p-3 font-bold"><Link href={`/symbol-analysis?symbol=${t.symbol}`} className="text-white hover:text-neon-green">{t.symbol}</Link></td><td className="p-3 text-neon-yellow">{STRATEGY_LABEL[t.strategy] ?? t.strategy}</td><td className="p-3">₺{formatTL(t.entry_price)}</td><td className="p-3">₺{formatTL(t.exit_price)}</td><td className="p-3 text-neon-yellow">₺{formatTL(t.commission ?? 0)}</td><td className={`p-3 font-bold ${t.pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>{t.pnl >= 0 ? "+" : ""}₺{formatTL(t.pnl)}</td><td className="p-3 text-bunker-muted whitespace-nowrap">{formatDateTime(t.entry_time)}</td><td className="p-3 text-bunker-muted whitespace-nowrap">{formatDateTime(t.exit_time)}</td><td className="p-3 text-bunker-muted whitespace-nowrap">{formatDuration(t.hold_seconds, t.entry_time, t.exit_time)}</td><td className="p-3 text-bunker-muted whitespace-nowrap">{t.reason || "-"}</td></tr>)}</tbody></table></div>
                <div className="p-3 flex justify-between items-center text-xs font-mono text-bunker-muted"><span>Sayfa {tradePage} / {tradePageCount}</span><div className="flex gap-2"><button onClick={() => setTradePage((p) => Math.max(1, p - 1))} disabled={tradePage === 1} className="px-2 py-1 border border-bunker-700 rounded disabled:opacity-40">ÖNCEKİ</button><button onClick={() => setTradePage((p) => Math.min(tradePageCount, p + 1))} disabled={tradePage === tradePageCount} className="px-2 py-1 border border-bunker-700 rounded disabled:opacity-40">SONRAKİ</button></div></div>
            </section>
        </div>
    );
}
