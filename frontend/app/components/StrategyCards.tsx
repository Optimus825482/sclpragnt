"use client";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type StrategyStat = { trades: number; wins: number; pnl: number; commission: number; win_rate: number; profit_factor?: number | null };
type Stats = Record<string, StrategyStat>;

const STRATEGY_META: Record<string, { name: string; icon: string }> = {
    EMA_VWAP_PULLBACK: { name: "EMA + VWAP Pullback", icon: "📈" },
    BB_SQUEEZE_ORDERFLOW: { name: "BB Squeeze + Order-Flow", icon: "📦" },
    ORDERFLOW: { name: "Order-Flow Imbalance", icon: "🌊" },
    MOMENTUM: { name: "MTF Momentum Ranking", icon: "⚡" },
    VWAP_MEAN_REVERSION: { name: "VWAP Mean Reversion", icon: "↩️" },
    KELTNER_BREAKOUT: { name: "Keltner Breakout", icon: "🔔" },
    CHOP_TREND_FILTER: { name: "CHOP Trend Filter", icon: "📐" },
    DONCHIAN_BREAKOUT: { name: "Donchian Breakout", icon: "🏹" },
    BB_MFI_MEAN_REVERSION: { name: "BB + MFI Mean Reversion", icon: "🎯" },
    PUMP_MONITOR: { name: "Pump Monitor", icon: "🚀" },
    FISHER_M3_KERNEL_M5_EXACT_PAPER: { name: "Fisher M3 + Kernel M5", icon: "〽️" },
};

export default function StrategyCards() {
    const [stats, setStats] = useState<Stats>({});
    const [active, setActive] = useState<string[]>([]);

    useEffect(() => {
        const load = () => apiRequest(`${API_BASE}/api/strategies/stats`)
            .then((r) => r.json())
            .then((d) => { setStats(d.stats || {}); setActive(Array.isArray(d.active) ? d.active : []); })
            .catch(() => undefined);
        load();
        const timer = setInterval(() => {
            load();
        }, 3000);
        return () => clearInterval(timer);
    }, []);

    const formatTL = (v: number) =>
        v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    return (
        <section className="space-y-3">
            <div className="ui-section-header"><div><p className="eyebrow">AKTİF STRATEJİ BAŞARISI</p><p className="ui-section-description">Kapanmış paper işlemler · komisyon sonrası net sonuç.</p></div><span className="font-mono text-xs text-neon-green">{active.length} AKTİF</span></div>
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {active.map((key) => {
                const meta = STRATEGY_META[key] || { name: key.replaceAll("_", " "), icon: "⚙️" };
                const s = stats[key];
                return (
                    <div key={key} className="card bg-bunker-950 border-neon-green/30">
                        <div className="flex items-center justify-between mb-2">
                            <p className="font-mono text-sm font-bold text-white">
                                <span className="mr-2">{meta.icon}</span>{meta.name}
                            </p>
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-neon-green/15 text-neon-green">AKTİF</span>
                        </div>
                        {!s ? (
                            <p className="font-mono text-xs text-bunker-muted">Henüz işlem yok</p>
                        ) : (
                            <div className="space-y-1.5">
                                <div className="flex justify-between font-mono text-xs">
                                    <span className="text-bunker-muted">İşlem</span>
                                    <span className="text-white font-bold">{s.trades}</span>
                                </div>
                                <div className="flex justify-between font-mono text-xs">
                                    <span className="text-bunker-muted">Kazanma</span>
                                    <span className="text-white font-bold">%{s.win_rate.toFixed(0)}</span>
                                </div>
                                <div className="flex justify-between font-mono text-xs">
                                    <span className="text-bunker-muted">PnL</span>
                                    <span className={`font-bold ${s.pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                                        {s.pnl >= 0 ? "+" : ""}₺{formatTL(s.pnl)}
                                    </span>
                                </div>
                                <div className="flex justify-between font-mono text-xs">
                                    <span className="text-bunker-muted">Kâr faktörü</span>
                                    <span className="text-white font-bold">{s.profit_factor == null ? "—" : s.profit_factor.toFixed(2)}</span>
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}
            {!active.length && <div className="card bg-bunker-950 text-sm text-bunker-muted">Aktif strateji bilgisi bekleniyor.</div>}
            </div>
        </section>
    );
}
