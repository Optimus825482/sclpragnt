"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAllPages } from "../lib/api";

type Trade = {
    id: number;
    symbol: string;
    strategy: string;
    side: string;
    entry_price: number;
    exit_price: number;
    quantity: number;
    pnl: number;
    pnl_pct: number;
    commission?: number;
    reason?: string;
    entry_time: number;
    exit_time: number;
};

const STRATEGY_LABEL: Record<string, string> = {
    VELOCITY: "Hız Avcısı",
    CHAT_PREDICTION: "Hız Avcısı (Otonom)",
    LLM_PAPER: "LLM Paper",
    GAINER_RADAR: "Gainer Radar",
};

export default function HistoryPage() {
    const [trades, setTrades] = useState<Trade[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [complete, setComplete] = useState(true);

    useEffect(() => {
        fetchAllPages<Trade>("/api/trades", "trades")
            .then((result) => { setTrades(result.rows); setComplete(result.complete); })
            .catch(() => setError("İşlem geçmişi backend'den alınamadı."))
            .finally(() => setLoading(false));
    }, []);

    const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);
    const wins = trades.filter((t) => t.pnl > 0).length;
    const winRate = trades.length ? (wins / trades.length) * 100 : 0;
    const formatTL = (v: number) =>
        v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fmtTime = (ts?: number) =>
        ts ? new Date(ts * 1000).toLocaleString("tr-TR", { hour12: false }) : "-";

    return (
        <div className="max-w-7xl mx-auto space-y-6">
            <header>
                <h1 className="font-mono text-xl font-bold tracking-tight">
                    <span className="text-neon-green">İŞLEM</span> GEÇMİŞİ
                </h1>
                <p className="eyebrow mt-1">Kapanan pozisyonlar · detaylı tablo</p>
                <p className={`mt-2 font-mono text-xs ${complete ? "text-neon-green" : "text-yellow-300"}`}>
                    {complete ? "Mevcut offset sayfaları yüklendi · canlı insert sırasında snapshot garantisi yok" : "10.000 kayıt sınırına ulaşıldı; backend keyset/aggregate endpoint'i gerekli"}
                </p>
            </header>

            <div className="grid md:grid-cols-4 gap-4">
                <div className="card bg-bunker-900 border-neon-green/20">
                    <p className="eyebrow">TOPLAM İŞLEM</p>
                    <p className="font-mono text-2xl font-bold text-white mt-1">{trades.length}</p>
                </div>
                <div className="card">
                    <p className="eyebrow">GERÇEKLEŞMİŞ PnL</p>
                    <p className={`font-mono text-2xl font-bold mt-1 ${totalPnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                        {totalPnl >= 0 ? "+" : ""}₺{formatTL(totalPnl)}
                    </p>
                </div>
                <div className="card">
                    <p className="eyebrow">KAZANAN</p>
                    <p className="font-mono text-2xl font-bold text-neon-green mt-1">{wins}</p>
                </div>
                <div className="card">
                    <p className="eyebrow">KAZANMA ORANI</p>
                    <p className="font-mono text-2xl font-bold text-white mt-1">%{winRate.toFixed(1)}</p>
                </div>
            </div>

            <div className="card bg-bunker-950 p-0 overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full font-mono text-sm">
                        <thead>
                            <tr className="text-left text-bunker-muted text-xs border-b border-bunker-800">
                                <th className="p-3">SEMBOL</th>
                                <th className="p-3">STRATEJİ</th>
                                <th className="p-3">YÖN</th>
                                <th className="p-3">GİRİŞ</th>
                                <th className="p-3">ÇIKIŞ</th>
                                <th className="p-3">MIKTAR</th>
                                <th className="p-3">KOMİSYON</th>
                                <th className="p-3">PnL</th>
                                <th className="p-3">PnL %</th>
                                <th className="p-3">KAPANIŞ NEDENİ</th>
                                <th className="p-3">AÇILIŞ</th>
                                <th className="p-3">KAPANIŞ</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading && (
                                <tr><td colSpan={12} className="p-4 text-bunker-muted animate-pulse">Yükleniyor...</td></tr>
                            )}
                            {!loading && !error && trades.length === 0 && (
                                <tr><td colSpan={12} className="p-4 text-bunker-muted">Henüz kapanan pozisyon yok.</td></tr>
                            )}
                            {error && (
                                <tr><td colSpan={12} className="p-4 text-neon-red">{error}</td></tr>
                            )}
                            {trades.map((t) => (
                                <tr key={t.id} className="border-b border-bunker-800/50 hover:bg-bunker-800/30">
                                <td className="p-3 font-bold"><Link href={`/charts?symbol=${encodeURIComponent(t.symbol)}&timeframe=5m`} className="text-white hover:text-neon-green">{t.symbol}</Link></td>
                                    <td className="p-3 text-neon-yellow">{STRATEGY_LABEL[t.strategy] ?? t.strategy}</td>
                                    <td className="p-3">
                                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${t.side === "LONG" ? "bg-neon-green/15 text-neon-green" : "bg-neon-red/15 text-neon-red"}`}>
                                            {t.side === "LONG" ? "LONG" : "SHORT"}
                                        </span>
                                    </td>
                                    <td className="p-3 text-bunker-muted">₺{formatTL(t.entry_price)}</td>
                                    <td className="p-3 text-bunker-muted">₺{formatTL(t.exit_price)}</td>
                                    <td className="p-3 text-bunker-muted">{t.quantity.toFixed(6)}</td>
                                    <td className="p-3 text-neon-yellow">₺{formatTL(t.commission ?? 0)}</td>
                                    <td className={`p-3 font-bold ${t.pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                        {t.pnl >= 0 ? "+" : ""}₺{formatTL(t.pnl)}
                                    </td>
                                    <td className={`p-3 font-bold ${t.pnl_pct >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                        {t.pnl_pct > 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                                    </td>
                                    <td className="p-3 text-neon-yellow text-xs whitespace-nowrap">{t.reason || "-"}</td>
                                    <td className="p-3 text-bunker-muted text-xs">{fmtTime(t.entry_time)}</td>
                                    <td className="p-3 text-bunker-muted text-xs">{fmtTime(t.exit_time)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
