"use client";

import { useEffect, useState } from "react";
import MarketChart from "../components/MarketChart";
import { Card, SectionHeader } from "../components/ui";
import { usePoll } from "../lib/hooks";
import type { MarketSymbols } from "../lib/types";

type Panels = 1 | 2 | 4;
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLTRY", "AVAXTRY"];

export default function GrafikPage() {
  const [panels, setPanels] = useState<Panels>(1);
  const [selectedSymbol, setSelectedSymbol] = useState(DEFAULT_SYMBOLS[0]);
  const [interval, setInterval] = useState("5m");
  const marketSymbols = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const symbolOptions = Array.from(new Set([...DEFAULT_SYMBOLS, ...(marketSymbols.data?.symbols || [])]));

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const symbol = (query.get("symbol") || "").toUpperCase().replace(/[^A-Z0-9_]/g, "");
    const tf = query.get("interval");
    if (symbol) setSelectedSymbol(symbol);
    if (["1m", "5m", "15m", "1h", "4h", "1d"].includes(tf || "")) setInterval(tf!);
  }, []);

  const count = panels;

  return <div className="space-y-5">
    <SectionHeader eyebrow="Piyasa" title="Teknik Grafikler" description="Binance TR mumları, anlık oluşan mum güncellemeleri ve gösterge katmanları." actions={<div className="flex rounded-lg border border-line bg-white p-1" aria-label="Grafik panel sayısı">{([1, 2, 4] as const).map((n) => <button key={n} type="button" aria-pressed={panels === n} onClick={() => setPanels(n)} className={`min-w-10 rounded-md px-3 py-2 text-sm font-semibold ${panels === n ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{n}</button>)}</div>} />
    <div className={`grid gap-4 ${count === 1 ? "grid-cols-1" : count === 2 ? "grid-cols-1 2xl:grid-cols-2" : "grid-cols-1 xl:grid-cols-2"}`}>
      {Array.from({ length: count }, (_, index) => <Card key={index} className="min-w-0 p-3 sm:p-4">
        <div className="mb-2 text-xs font-semibold text-ink-400">Panel {index + 1} · Sembol değişikliği tüm grafiklere uygulanır</div>
        <MarketChart initialSymbol={selectedSymbol} initialInterval={interval} symbols={symbolOptions} onSymbolChange={setSelectedSymbol} />
      </Card>)}
    </div>
    <p className="text-xs text-ink-400">RSI 14 ve ADX 14 seçili zaman dilimine göre hesaplanır · Bollinger Bands (20,2) varsayılan açık · alt panel MACD histogramıdır. Canlı akış alınamazsa son mum verisi gösterilir.</p>
  </div>;
}
