"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { fmtDateTime } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

type BridgePerformanceResponse = {
  ok: boolean;
  day: string;
  summary: {
    day: string;
    total_signals: number;
    total_trades: number;
    open_trades_count: number;
    closed_trades_count: number;
    wins: number;
    losses: number;
    win_rate: number;
    target_touch_rate: number;
    net_pnl_try: number;
    total_commission_try: number;
    avg_pnl_pct: number;
    avg_hold_minutes: number;
    avg_latency_ms: number;
    exit_reasons: Record<string, number>;
  };
  open_positions: Array<{
    symbol: string;
    side: string;
    entry_price: number;
    current_price: number;
    quantity: number;
    unrealized_pnl_try: number;
    unrealized_pnl_pct: number;
    stop_price?: number;
    take_profit_price?: number;
    entry_time?: number;
    trade_id?: string;
    entry_context?: any;
  }>;
  closed_trades: Array<{
    id: number;
    symbol: string;
    entry_price: number;
    exit_price: number;
    quantity: number;
    pnl: number;
    pnl_pct: number;
    commission?: number;
    entry_time: number;
    exit_time: number;
    reason: string;
    trade_id?: string;
    entry_context?: any;
  }>;
  recent_signals: Array<{
    event_id: string;
    received_at: number;
    global_symbol?: string;
    tr_symbol?: string;
    signal_type: string;
    score?: number;
    global_price?: number;
    tr_price?: number;
    latency_ms: number;
    status: string;
    trade?: {
      status: string;
      trade_id?: string;
      reason?: string;
    };
  }>;
};

const formatMoney = (val: number | null | undefined): string => {
  const num = Number(val || 0);
  return `${num >= 0 ? "+" : ""}${num.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
};

const formatPct = (val: number | null | undefined): string => {
  const num = Number(val || 0);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
};

const exitReasonBadge = (reason: string) => {
  const r = String(reason || "").toLowerCase();
  if (r.includes("take_profit")) {
    return { label: "🎯 HEDEFE ULAŞTI (TP)", cls: "bg-neon-green/15 text-neon-green border-neon-green/40" };
  }
  if (r.includes("emergency_stop")) {
    return { label: "🚨 ACİL STOP", cls: "bg-neon-red/15 text-neon-red border-neon-red/40" };
  }
  if (r.includes("stop")) {
    return { label: "🛑 STOP-LOSS", cls: "bg-neon-red/15 text-neon-red border-neon-red/40" };
  }
  if (r.includes("max_hold")) {
    return { label: "⏱ SÜRE DOLDU (VADE)", cls: "bg-amber-400/15 text-amber-300 border-amber-400/40" };
  }
  return { label: reason || "DİĞER", cls: "bg-bunker-800 text-bunker-muted border-bunker-700" };
};

export default function GlobalBridgeTab({ day = "all" }: { day?: string }) {
  const [data, setData] = useState<BridgePerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const res = await getJSON<BridgePerformanceResponse>(`/api/bridge/performance?day=${encodeURIComponent(day)}`);
      setData(res);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Köprü performans verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useVisibleInterval(loadData, 10_000);

  useLiveMessages(
    useCallback(
      (msg: any) => {
        if (["global_bridge_signal", "signal", "trade_updated", "reset"].includes(msg.type)) {
          loadData();
        }
      },
      [loadData]
    )
  );

  const summary = data?.summary;
  const openPositions = data?.open_positions || [];
  const closedTrades = data?.closed_trades || [];
  const recentSignals = data?.recent_signals || [];

  return (
    <section aria-label="Global Lead-Lag Köprü Raporu" className="space-y-6">
      {/* BAŞLIK & DÖNEM BİLGİSİ */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-bunker-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🌉</span>
            <h2 className="font-mono text-lg font-bold text-white">Global Lead-Lag Öncü-Artçı Sinyal &amp; İşlem Başarısı</h2>
          </div>
          <p className="text-xs text-bunker-muted mt-1">
            Binance Global (USDT) öncü hareketlerinin Binance TR (TRY) paritelerindeki yansımaları, açılan otonom işlemler ve gerçekleşen PnL sonuçları.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-xl border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-bunker-muted">
            Dönem: <span className="text-white font-bold">{day === "all" ? "Tüm Zamanlar" : day}</span>
          </span>
          <button
            type="button"
            onClick={loadData}
            className="rounded-xl border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-bunker-muted hover:text-white"
          >
            ↻ Yenile
          </button>
        </div>
      </div>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/10 text-xs font-mono text-neon-red p-4 rounded-xl">
          {error}
        </div>
      )}

      {/* 1. ÖZET METRİK KARTLARI */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Sinyal Sayısı */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">GLOBAL SİNYAL</p>
          <p className="font-mono text-2xl font-black text-white mt-1">
            {summary?.total_signals ?? 0}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">Öncü Bildirim</p>
        </div>

        {/* Gerçekleşen İşlem */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">OTONOM İŞLEMLER</p>
          <p className="font-mono text-2xl font-black text-neon-cyan mt-1">
            {summary?.total_trades ?? 0}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">
            Açık: {summary?.open_trades_count ?? 0} | Kapanan: {summary?.closed_trades_count ?? 0}
          </p>
        </div>

        {/* Win Rate */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">BAŞARI ORANI (WIN RATE)</p>
          <p
            className={`font-mono text-2xl font-black mt-1 ${
              (summary?.win_rate ?? 0) >= 50 ? "text-neon-green" : "text-amber-400"
            }`}
          >
            %{summary?.win_rate?.toFixed(1) ?? "0.0"}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">
            {summary?.wins ?? 0} Kâr / {summary?.losses ?? 0} Zarar
          </p>
        </div>

        {/* TP Hedef Dokunuşu */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">HEDEFE ULAŞMA (TP)</p>
          <p className="font-mono text-2xl font-black text-neon-green mt-1">
            %{summary?.target_touch_rate?.toFixed(1) ?? "0.0"}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">Planlı TP Çıkışı</p>
        </div>

        {/* Net PnL */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">NET KÂR / ZARAR</p>
          <p
            className={`font-mono text-xl sm:text-2xl font-black mt-1 ${
              (summary?.net_pnl_try ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"
            }`}
          >
            {formatMoney(summary?.net_pnl_try)}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">
            Komisyon: {formatMoney(summary?.total_commission_try)}
          </p>
        </div>

        {/* Ortalama Gecikme */}
        <div className="card p-4 rounded-2xl border-bunker-800 bg-bunker-900/60">
          <p className="eyebrow text-bunker-muted text-[10px]">ORTALAMA GECİKME</p>
          <p className="font-mono text-2xl font-black text-neon-cyan mt-1">
            {summary?.avg_latency_ms ? `${summary.avg_latency_ms} ms` : "—"}
          </p>
          <p className="text-[10px] text-bunker-muted mt-1 font-mono">
            Ort. Süre: {summary?.avg_hold_minutes ?? 0} dk
          </p>
        </div>
      </div>

      {/* 2. ÇIKIŞ NEDENLERİ DAĞILIMI */}
      {summary && summary.closed_trades_count > 0 && (
        <div className="card border-bunker-800 bg-bunker-900/60 p-5 rounded-2xl space-y-3">
          <div className="flex items-center gap-2 border-b border-bunker-800 pb-3">
            <span className="text-neon-green">📊</span>
            <h3 className="font-mono text-sm font-bold text-white">Çıkış Nedenleri Dağılımı</h3>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 rounded-xl border border-neon-green/30 bg-neon-green/5">
              <p className="eyebrow text-neon-green text-[10px]">HEDEFE ULAŞAN (TP)</p>
              <p className="font-mono text-xl font-bold text-neon-green mt-1">
                {summary.exit_reasons["lead_lag_take_profit"] || summary.exit_reasons["chat_plan_take_profit"] || 0}
              </p>
            </div>
            <div className="p-3 rounded-xl border border-amber-400/30 bg-amber-400/5">
              <p className="eyebrow text-amber-300 text-[10px]">SÜRE DOLDU (MAX HOLD)</p>
              <p className="font-mono text-xl font-bold text-amber-300 mt-1">
                {summary.exit_reasons["lead_lag_max_hold"] || summary.exit_reasons["chat_plan_max_hold"] || 0}
              </p>
            </div>
            <div className="p-3 rounded-xl border border-neon-red/30 bg-neon-red/5">
              <p className="eyebrow text-neon-red text-[10px]">STOP-LOSS</p>
              <p className="font-mono text-xl font-bold text-neon-red mt-1">
                {summary.exit_reasons["system_stop_loss"] || summary.exit_reasons["hard_stop_loss"] || 0}
              </p>
            </div>
            <div className="p-3 rounded-xl border border-red-500/30 bg-red-500/5">
              <p className="eyebrow text-red-400 text-[10px]">ACİL STOP</p>
              <p className="font-mono text-xl font-bold text-red-400 mt-1">
                {summary.exit_reasons["velocity_emergency_stop"] || 0}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 3. AKTİF AÇIK LEAD-LAG POZİSYONLARI */}
      {openPositions.length > 0 && (
        <div className="card border-neon-cyan/40 bg-neon-cyan/5 p-5 rounded-2xl space-y-3">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <div className="flex items-center gap-2">
              <span className="text-neon-cyan animate-pulse">●</span>
              <h3 className="font-mono text-sm font-bold text-white">
                Aktif Açık Lead-Lag Pozisyonları ({openPositions.length})
              </h3>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-bunker-800 text-[11px] text-bunker-muted uppercase">
                  <th className="py-2 px-2">Sembol</th>
                  <th className="py-2 px-2 text-right">Giriş</th>
                  <th className="py-2 px-2 text-right">Güncel Fiyat</th>
                  <th className="py-2 px-2 text-right">Hedef (TP)</th>
                  <th className="py-2 px-2 text-right">Anlık PnL</th>
                  <th className="py-2 px-2 text-right">Getiri (%)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {openPositions.map((pos) => (
                  <tr key={pos.symbol} className="hover:bg-bunker-800/30">
                    <td className="py-2.5 px-2 font-bold text-white">
                      <SymbolLink symbol={pos.symbol} />
                    </td>
                    <td className="py-2.5 px-2 text-right text-white">₺{pos.entry_price.toFixed(4)}</td>
                    <td className="py-2.5 px-2 text-right text-neon-cyan font-bold">
                      ₺{pos.current_price.toFixed(4)}
                    </td>
                    <td className="py-2.5 px-2 text-right text-neon-green">
                      {pos.take_profit_price ? `₺${pos.take_profit_price.toFixed(4)}` : "—"}
                    </td>
                    <td
                      className={`py-2.5 px-2 text-right font-bold ${
                        pos.unrealized_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"
                      }`}
                    >
                      {formatMoney(pos.unrealized_pnl_try)}
                    </td>
                    <td
                      className={`py-2.5 px-2 text-right font-bold ${
                        pos.unrealized_pnl_pct >= 0 ? "text-neon-green" : "text-neon-red"
                      }`}
                    >
                      {formatPct(pos.unrealized_pnl_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 4. KAPANMIŞ İŞLEMLER VE BAŞARI LİSTESİ */}
      <div className="card border-bunker-800 bg-bunker-900/60 p-5 rounded-2xl space-y-3">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-neon-green">🏆</span>
            <h3 className="font-mono text-sm font-bold text-white">
              Kapanmış Lead-Lag İşlemleri ve Başarı Geçmişi
            </h3>
          </div>
          <span className="text-xs font-mono text-bunker-muted">{closedTrades.length} İşlem</span>
        </div>

        {closedTrades.length === 0 ? (
          <p className="text-xs text-bunker-muted font-mono py-8 text-center">
            Seçilen dönemde henüz kapanmış bir Global Lead-Lag işlemi bulunmuyor.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-bunker-800 text-[11px] text-bunker-muted uppercase">
                  <th className="py-2 px-2">Kapanış</th>
                  <th className="py-2 px-2">Sembol</th>
                  <th className="py-2 px-2 text-right">Giriş / Çıkış</th>
                  <th className="py-2 px-2 text-right">Net PnL (₺)</th>
                  <th className="py-2 px-2 text-right">Getiri (%)</th>
                  <th className="py-2 px-2">Çıkış Nedeni</th>
                  <th className="py-2 px-2 text-right">Süre</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {closedTrades.map((trade) => {
                  const badge = exitReasonBadge(trade.reason);
                  const holdMins = trade.exit_time && trade.entry_time
                    ? Math.round((trade.exit_time - trade.entry_time) / 60)
                    : null;

                  return (
                    <tr key={trade.id} className="hover:bg-bunker-800/40 transition-colors">
                      <td className="py-2.5 px-2 text-bunker-muted whitespace-nowrap">
                        {fmtDateTime(trade.exit_time)}
                      </td>
                      <td className="py-2.5 px-2 font-bold text-white whitespace-nowrap">
                        <SymbolLink symbol={trade.symbol} />
                      </td>
                      <td className="py-2.5 px-2 text-right text-bunker-muted whitespace-nowrap">
                        <span className="text-white">₺{Number(trade.entry_price).toFixed(4)}</span>
                        <span> → </span>
                        <span className="text-white">₺{Number(trade.exit_price).toFixed(4)}</span>
                      </td>
                      <td
                        className={`py-2.5 px-2 text-right font-bold whitespace-nowrap ${
                          trade.pnl >= 0 ? "text-neon-green" : "text-neon-red"
                        }`}
                      >
                        {formatMoney(trade.pnl)}
                      </td>
                      <td
                        className={`py-2.5 px-2 text-right font-bold whitespace-nowrap ${
                          trade.pnl_pct >= 0 ? "text-neon-green" : "text-neon-red"
                        }`}
                      >
                        {formatPct(trade.pnl_pct)}
                      </td>
                      <td className="py-2.5 px-2 whitespace-nowrap">
                        <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
                          {badge.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-2 text-right text-bunker-muted whitespace-nowrap">
                        {holdMins !== null ? `${holdMins} dk` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 5. SON GLOBAL SİNYAL VE TETİKLEME GÜNLÜĞÜ */}
      <div className="card border-bunker-800 bg-bunker-900/60 p-5 rounded-2xl space-y-3">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-neon-cyan">📡</span>
            <h3 className="font-mono text-sm font-bold text-white">Gelen Öncü Sinyal ve Tetikleme Günlüğü</h3>
          </div>
          <span className="text-xs font-mono text-bunker-muted">{recentSignals.length} Sinyal</span>
        </div>

        {recentSignals.length === 0 ? (
          <p className="text-xs text-bunker-muted font-mono py-6 text-center">
            Seçilen dönem için kaydedilmiş bir öncü sinyal kaydı bulunmuyor.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-bunker-800 text-[11px] text-bunker-muted uppercase">
                  <th className="py-2 px-2">Zaman</th>
                  <th className="py-2 px-2">Eşleşme (Global → TR)</th>
                  <th className="py-2 px-2">Tür</th>
                  <th className="py-2 px-2 text-right">Skor</th>
                  <th className="py-2 px-2 text-right">Gecikme</th>
                  <th className="py-2 px-2 text-right">Tetikleme Durumu</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {recentSignals.map((sig, idx) => (
                  <tr key={sig.event_id || idx} className="hover:bg-bunker-800/40 transition-colors">
                    <td className="py-2.5 px-2 text-bunker-muted whitespace-nowrap">
                      {new Date(sig.received_at * 1000).toLocaleTimeString("tr-TR")}
                    </td>
                    <td className="py-2.5 px-2 font-bold text-white whitespace-nowrap">
                      {sig.tr_symbol ? (
                        <span>
                          <span className="text-bunker-muted">{sig.global_symbol || "—"} → </span>
                          <span className="text-neon-cyan">{sig.tr_symbol}</span>
                        </span>
                      ) : (
                        <span className="text-bunker-muted">— (Ping)</span>
                      )}
                    </td>
                    <td className="py-2.5 px-2 text-bunker-muted whitespace-nowrap">
                      <span className="rounded bg-bunker-800 px-1.5 py-0.5 text-[10px]">
                        {sig.signal_type}
                      </span>
                    </td>
                    <td className="py-2.5 px-2 text-right font-bold text-white whitespace-nowrap">
                      {sig.score ? sig.score.toFixed(1) : "—"}
                    </td>
                    <td className="py-2.5 px-2 text-right text-neon-cyan whitespace-nowrap">
                      {sig.latency_ms ? `${sig.latency_ms} ms` : "—"}
                    </td>
                    <td className="py-2.5 px-2 text-right whitespace-nowrap">
                      {sig.status === "pong" ? (
                        <span className="text-neon-green">✓ Pong</span>
                      ) : sig.status === "executed" ? (
                        <span className="text-neon-green font-bold">🚀 Pozisyon Açıldı</span>
                      ) : sig.status === "cooldown_skipped" ? (
                        <span className="text-amber-400">⏱ Cooldown Engeli</span>
                      ) : sig.status === "score_below_minimum" ? (
                        <span className="text-bunker-muted">Düşük Skor</span>
                      ) : sig.status === "blocked" ? (
                        <span className="text-neon-red" title={sig.trade?.reason}>
                          ⛔ Bloke Edildi
                        </span>
                      ) : (
                        <span className="text-bunker-muted">{sig.status}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
