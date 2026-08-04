"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

type StrategyStat = { trades: number; wins: number; pnl: number; commission: number; win_rate: number };
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
};

export default function StrategyCards() {
    const [stats, setStats] = useState<Stats>({});
    const [enabled, setEnabled] = useState<Record<string, boolean>>({});

    useEffect(() => {
    fetch(`${API_BASE}/api/strategies/stats`)
            .then((r) => r.json())
            .then((d) => setStats(d.stats))
            .catch(() => { });
        fetch(`${API_BASE}/api/config`)
            .then((r) => r.json())
            .then((d) => setEnabled({
                EMA_VWAP_PULLBACK: d.ema_vwap_enabled,
                BB_SQUEEZE_ORDERFLOW: d.bb_squeeze_enabled,
                ORDERFLOW: d.orderflow_enabled,
                MOMENTUM: d.momentum_enabled,
                VWAP_MEAN_REVERSION: d.mean_reversion_enabled,
                KELTNER_BREAKOUT: d.keltner_enabled,
                CHOP_TREND_FILTER: d.chop_enabled,
                DONCHIAN_BREAKOUT: d.donchian_enabled,
            }))
            .catch(() => { });
    }, []);

    const formatTL = (v: number) =>
        v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    return (
        <div className="grid md:grid-cols-2 xl:grid-cols-5 gap-4">
            {Object.entries(STRATEGY_META).map(([key, meta]) => {
                const s = stats[key];
                const isOn = enabled[key];
                return (
                    <div key={key} className={`card bg-bunker-950 ${isOn ? "border-neon-green/30" : "border-bunker-800"}`}>
                        <div className="flex items-center justify-between mb-2">
                            <p className="font-mono text-sm font-bold text-white">
                                <span className="mr-2">{meta.icon}</span>{meta.name}
                            </p>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${isOn ? "bg-neon-green/15 text-neon-green" : "bg-bunker-800 text-bunker-muted"}`}>
                                {isOn ? "AKTİF" : "PASİF"}
                            </span>
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
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
