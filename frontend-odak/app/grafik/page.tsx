"use client";

import { useEffect, useState } from "react";
import MarketChart from "../components/MarketChart";
import { Card, SectionHeader } from "../components/ui";

type Panels = 1 | 2 | 4;
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLTRY", "AVAXTRY"];

export default function GrafikPage() {
  const [panels, setPanels] = useState<Panels>(1);
  const [symbols, setSymbols] = useState(DEFAULT_SYMBOLS);
  const [interval, setInterval] = useState("5m");

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const symbol = (query.get("symbol") || "").toUpperCase().replace(/[^A-Z0-9_]/g, "");
    const tf = query.get("interval");
    if (symbol) setSymbols((items) => [symbol, ...items.slice(1)]);
    if (["1m", "5m", "15m", "1h", "4h", "1d"].includes(tf || "")) setInterval(tf!);
  }, []);

  const count = panels;

  return <div className="space-y-5">
    <SectionHeader eyebrow="Piyasa" title="Teknik Grafikler" description="Binance TR mumları, anlık oluşan mum güncellemeleri ve gösterge katmanları." actions={<div className="flex rounded-lg border border-line bg-white p-1" aria-label="Grafik panel sayısı">{([1, 2, 4] as const).map((n) => <button key={n} type="button" aria-pressed={panels === n} onClick={() => setPanels(n)} className={`min-w-10 rounded-md px-3 py-2 text-sm font-semibold ${panels === n ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{n}</button>)}</div>} />
    <div className={`grid gap-4 ${count === 1 ? "grid-cols-1" : count === 2 ? "grid-cols-1 2xl:grid-cols-2" : "grid-cols-1 xl:grid-cols-2"}`}>
      {symbols.slice(0, count).map((symbol, index) => <Card key={`${symbol}-${interval}-${index}`} className="min-w-0 p-3 sm:p-4">
        <div className="mb-2 text-xs font-semibold text-ink-400">Panel {index + 1} · Sembol ve zaman aralığı grafik araçlarından değiştirilebilir</div>
        <MarketChart initialSymbol={symbol} initialInterval={interval} />
      </Card>)}
    </div>
    <p className="text-xs text-ink-400">Gösterge: SMA 20 · Alt hacim çubukları. Kline canlı akışı alınamazsa son REST mum verisi görünmeye devam eder.</p>
  </div>;
}
