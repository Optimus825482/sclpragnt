"use client";
import { useEffect, useRef, useState } from "react";
import { API_BASE, WS_BASE } from "../lib/api";

type Ticker = { symbol: string; last_price: number; volume: number; avg_volume?: number };
type Signal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number };
type Position = { symbol: string; entry: number; current: number; pnl_pct: number; pnl_try?: number; value: number };
type Portfolio = { try: number; total_value: number; positions: Position[] };

export default function LiveTerminal() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    fetch(`${API_BASE}/api/signals?limit=100`)
      .then((response) => response.json())
      .then((data) => setSignals((data.signals || []).slice(0, 100).reverse()))
      .catch(() => undefined);

    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws`);
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "tickers") return;
        else if (msg.type === "signal") setSignals((p) => [...p, msg.data].slice(-100));
        else if (msg.type === "portfolio") setPortfolio(msg.data);
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [signals]);

  const pnlColor = (pnl: number) => pnl >= 0 ? "text-neon-green" : "text-neon-red";

  const formatTL = (v?: number) =>
    v == null ? "0,00" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <div className="card !p-4 flex justify-between items-center bg-bunker-900 border-neon-green/20">
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
            <span className="text-xs text-neon-green font-mono animate-pulse">● LIVE</span>
          </div>
          <div className="p-4 font-mono text-sm h-64 overflow-y-auto">
            {signals.length === 0 && <p className="text-bunker-muted">$ Bot çalışıyor, strateji sinyali bekleniyor...</p>}
            {signals.map((s, i) => (
              <div key={s.id ?? `${s.timestamp}-${s.symbol}-${s.action}-${i}`} className={`py-1 ${s.action.includes("BUY") ? "text-neon-green" : "text-neon-red"}`}>
                <span className="text-bunker-muted">[{s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString("tr-TR") : "--"}]</span>{" "}
                <span className="font-bold">{s.action}</span>{" "}
                {s.symbol} {s.price && `@ ₺${s.price.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}{" "}
                <span className="text-bunker-700 text-xs">// {s.reason}</span>
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      </div >

      <div className="space-y-6">
        <div className="card">
          <p className="eyebrow mb-4">AÇIK POZİSYONLAR</p>
          <div className="space-y-3">
            {portfolio?.positions.length === 0 && <p className="text-bunker-muted text-sm font-mono">Açık pozisyon yok.</p>}
            {portfolio?.positions.map((p) => (
              <div key={p.symbol} className="bg-bunker-950 p-4 rounded-lg border border-bunker-800">
                <div className="flex justify-between mb-2">
                  <span className="font-bold font-mono">{p.symbol}</span>
                  <span className={`font-mono ${pnlColor(p.pnl_pct)}`}>
                    {p.pnl_pct > 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="flex justify-between text-xs text-bunker-muted font-mono">
                  <span>Giriş: ₺{p.entry.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  <span>Anlık: ₺{p.current.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </div>
                <div className="mt-2 text-xs text-right text-bunker-muted font-mono">
                  PnL: <span className={pnlColor(p.pnl_pct)}>{p.pnl_try != null && p.pnl_try >= 0 ? "+" : ""}₺{formatTL(p.pnl_try)}</span> · {p.pnl_pct.toFixed(2)}%
                </div>
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
            <div className="flex justify-between"><span className="text-bunker-muted">İşlem Başına</span><span className="text-white">1.000,00 TL</span></div>
            <div className="flex justify-between"><span className="text-bunker-muted">Maksimum Bekleme</span><span className="text-neon-yellow">12 saat</span></div>
            <div className="flex justify-between"><span className="text-bunker-muted">Take Profit</span><span className="text-neon-green">+0,5%</span></div>
            <div className="flex justify-between"><span className="text-bunker-muted">Katman</span><span className="text-white">3</span></div>
          </div>
        </div>
      </div>
    </div >
  );
}
