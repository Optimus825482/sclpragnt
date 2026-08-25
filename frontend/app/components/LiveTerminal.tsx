"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import SymbolLink from "./SymbolLink";

type Ticker = { symbol: string; last_price: number; volume: number; avg_volume?: number };
type Signal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number };
type Position = { symbol: string; entry: number; current: number; pnl_pct: number; pnl_try?: number; value: number; entry_time?: number; strategy?: string; entry_context?: { signal_context?: { score?: number } } };
type Portfolio = { try: number; total_value: number; positions: Position[] };

export default function LiveTerminal() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const liveStatus = useLiveStatus();
  // Guarded formatters: a malformed WS/API payload must not crash the page.
  const safeNumber = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);
  const pctText = (pct: unknown) => {
    const value = safeNumber(pct);
    return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  };
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const onLiveMessage = useCallback((msg: any) => {
    if (msg.type === "signal") setSignals((current) => [...current, msg.data].slice(-100));
    else if (msg.type === "portfolio") setPortfolio(msg.data);
  }, []);
  useLiveMessages(onLiveMessage);

  useEffect(() => {
    apiRequest(`${API_BASE}/api/signals?limit=100`)
      .then((response) => response.json())
      .then((data) => setSignals((data.signals || []).slice(0, 100).reverse()))
      .catch(() => undefined);

  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [signals]);

  const pnlColor = (pnl: number) => pnl >= 0 ? "text-neon-green" : "text-neon-red";
  const openPnl = portfolio?.positions.reduce((total, position) => total + (position.pnl_try ?? 0), 0) ?? 0;

  const formatTL = (v?: number) =>
    v == null ? "0,00" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="live-terminal grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <div className="portfolio-summary card !p-4 flex justify-between items-center bg-bunker-900 border-neon-green/20">
          <div>
            <p className="eyebrow text-bunker-muted">SANAL PORTFÖY (PAPER)</p>
            <p className="font-mono text-3xl font-bold text-white mt-1">
              ₺{formatTL(portfolio?.total_value)}
            </p>
          </div>
          <div className="text-right">
            <p className="eyebrow text-bunker-muted">MEVCUT TL</p>
            <p className="font-mono text-xl text-neon-green mt-1">
              ₺{formatTL(portfolio?.try)}
            </p>
          </div>
        </div >

        <div className="card bg-bunker-950 p-0 overflow-hidden">
          <div className="p-4 border-b border-bunker-800 flex justify-between items-center">
            <p className="eyebrow">İŞLEM AKIŞI (TRADE LOG)</p>
            {liveStatus === "open"
              ? <span className="text-xs text-neon-green font-mono animate-pulse">● LIVE</span>
              : <span className="text-xs font-mono text-neon-yellow" title="WebSocket bağlantısı yok; veriler bayat olabilir">
                  {liveStatus === "connecting" ? "○ BAĞLANIYOR" : "○ BAĞLANTI YOK"}
                </span>}
          </div>
          <div className="p-4 font-mono text-sm h-64 overflow-y-auto">
            {signals.length === 0 && <p className="text-bunker-muted">$ Bot çalışıyor, strateji sinyali bekleniyor...</p>}
            {signals.map((s, i) => (
              <div key={s.id ?? `${s.timestamp}-${s.symbol}-${s.action}-${i}`} className={`trade-log-row py-1 ${s.action === "BUY_BLOCKED" ? "text-sky-400" : s.action.includes("BUY") ? "text-neon-green" : "text-neon-red"}`}>
                <span className="text-bunker-muted">[{s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString("tr-TR") : "--"}]</span>{" "}
                <span className="font-bold">{s.action}</span>{" "}
                <SymbolLink symbol={s.symbol} className="font-bold text-current hover:text-white" /> {s.price && `@ ₺${s.price.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}{" "}
                <span className="text-bunker-600 text-xs">// {s.reason}</span>
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      </div >

      <div className="space-y-6">
        <div className="card">
          <div className="flex justify-between items-center mb-4">
            <p className="eyebrow">AÇIK POZİSYONLAR</p>
            <div className="text-right font-mono">
              <p className="text-[10px] text-bunker-muted">TOPLAM PnL</p>
              <p className={`text-sm font-bold ${pnlColor(openPnl)}`}>
                {openPnl >= 0 ? "+" : ""}₺{formatTL(openPnl)}
              </p>
            </div>
          </div>
          <div className="space-y-3">
            {portfolio?.positions.length === 0 && <p className="text-bunker-muted text-sm font-mono">Açık pozisyon yok.</p>}
            {portfolio?.positions.map((p) => (
              <div key={p.symbol} className="bg-bunker-950 p-4 rounded-lg border border-bunker-800">
                <div className="flex justify-between mb-2">
                  <SymbolLink symbol={p.symbol} className="font-bold text-white hover:text-neon-green" />
                  <span className={`font-mono ${pnlColor(safeNumber(p.pnl_pct))}`}>
                    {pctText(p.pnl_pct)}
                  </span>
                </div>
                <div className="position-values flex justify-between text-xs text-bunker-muted font-mono">
                  <span>Giriş: ₺{p.entry.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  <span>Anlık: ₺{p.current.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div className="mt-2 text-xs text-right text-bunker-muted font-mono">
                  PnL: <span className={pnlColor(safeNumber(p.pnl_pct))}>{(p.pnl_try ?? 0) >= 0 ? "+" : ""}₺{formatTL(p.pnl_try)}</span> · {pctText(p.pnl_pct)}
                </div>
                <div className="mt-1 text-xs text-bunker-muted font-mono">Sinyal: {p.strategy === "PUMP_MONITOR" ? `Pump Monitor · skor ${p.entry_context?.signal_context?.score ?? "—"}/4` : (p.strategy || "UT")}</div>
                <div className="mt-1 text-xs text-right text-bunker-muted font-mono">
                  Değer: ₺{p.value.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <p className="eyebrow mb-3">RİSK YÖNETİMİ</p>
          <div className="space-y-2 font-mono text-xs">
            <div className="risk-row flex justify-between"><span className="text-bunker-muted">İşlem Başına</span><span className="text-white">1.000,00 TL</span></div>
            <div className="risk-row flex justify-between"><span className="text-bunker-muted">Maksimum Bekleme</span><span className="text-neon-yellow">4 saat</span></div>
            <div className="risk-row flex justify-between"><span className="text-bunker-muted">Take Profit</span><span className="text-neon-green">1% → 0,75% → 0,5% → başa baş</span></div>
            <div className="risk-row flex justify-between"><span className="text-bunker-muted">Katman</span><span className="text-white">3</span></div>
          </div>
        </div>
      </div>
    </div >
  );
}
