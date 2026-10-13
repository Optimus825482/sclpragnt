"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import MarketChart from "../components/MarketChart";
import { Card, SectionHeader } from "../components/ui";
import { usePoll } from "../lib/hooks";
import { useWatchlist } from "../lib/watchlist";
import { useAuth } from "../lib/auth";
import type { MarketSymbols } from "../lib/types";

type Panels = 1 | 2 | 4;
type ChartPanel = { symbol: string; interval: string };
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLTRY", "AVAXTRY"];
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"];
const defaultPanels = (): ChartPanel[] => DEFAULT_SYMBOLS.map((symbol) => ({ symbol, interval: "5m" }));

export default function GrafikPage() {
  const { username } = useAuth();
  const [panelCount, setPanelCount] = useState<Panels>(1);
  const [panelConfigs, setPanelConfigs] = useState<ChartPanel[]>(defaultPanels);
  const [syncPanels, setSyncPanels] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const marketSymbols = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const { favorites } = useWatchlist();
  const storageKey = `odak_chart_layout:${String(username || "guest").toLowerCase()}`;

  const symbolOptions = useMemo(() => Array.from(new Set([...favorites, ...DEFAULT_SYMBOLS, ...(marketSymbols.data?.symbols || [])])), [favorites, marketSymbols.data?.symbols]);

  useEffect(() => {
    let querySymbol = "";
    let queryInterval = "";
    const query = new URLSearchParams(window.location.search);
    querySymbol = (query.get("symbol") || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    queryInterval = query.get("interval") || "";
    try {
      const raw = localStorage.getItem(storageKey);
      const saved = raw ? JSON.parse(raw) : null;
      if (saved && Array.isArray(saved.panels)) {
        const next = defaultPanels();
        saved.panels.slice(0, 4).forEach((panel: Partial<ChartPanel>, index: number) => {
          const symbol = String(panel.symbol || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
          const interval = INTERVALS.includes(String(panel.interval)) ? String(panel.interval) : "5m";
          if (symbol) next[index] = { symbol, interval };
        });
        setPanelConfigs(next);
        if ([1, 2, 4].includes(Number(saved.panelCount))) setPanelCount(Number(saved.panelCount) as Panels);
        setSyncPanels(Boolean(saved.syncPanels));
      }
    } catch {
      setPanelConfigs(defaultPanels());
    }
    if (querySymbol) setPanelConfigs((previous) => previous.map((panel, index) => index === 0 ? { ...panel, symbol: querySymbol } : panel));
    if (INTERVALS.includes(queryInterval)) setPanelConfigs((previous) => previous.map((panel, index) => index === 0 ? { ...panel, interval: queryInterval } : panel));
    setLoaded(true);
  }, [storageKey]);

  useEffect(() => {
    if (!loaded) return;
    localStorage.setItem(storageKey, JSON.stringify({ panelCount, panels: panelConfigs, syncPanels }));
  }, [loaded, panelCount, panelConfigs, storageKey, syncPanels]);

  function updatePanel(index: number, field: keyof ChartPanel, value: string) {
    setPanelConfigs((previous) => previous.map((panel, panelIndex) => {
      if (syncPanels || panelIndex === index) return { ...panel, [field]: value };
      return panel;
    }));
  }

  return (
    <div className="space-y-4">
      <SectionHeader
        eyebrow="Teknik Analiz"
        title="Canlı Binance TR Grafikleri"
        description="Yakınlaştırılabilir mum grafikleri, kullanıcıya özel gösterge ayarları ve WebSocket güncellemesi."
        actions={<div className="flex flex-wrap items-center gap-2">
          <Link href="/" className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-accent/90">← Anasayfa & İşlem Paneli</Link>
          <div className="flex rounded-lg border border-line bg-white p-1" aria-label="Grafik panel sayısı">
            {([1, 2, 4] as const).map((count) => <button key={count} type="button" aria-pressed={panelCount === count} onClick={() => setPanelCount(count)} className={`min-w-8 rounded-md px-2.5 py-1 text-xs font-semibold ${panelCount === count ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"}`}>{count} Panel</button>)}
          </div>
        </div>}
      />

      <Card className="flex flex-wrap items-center justify-between gap-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-ink-500">Favoriler:</span>
          {favorites.length ? favorites.map((symbol) => <button key={symbol} type="button" onClick={() => updatePanel(0, "symbol", symbol)} className="rounded-lg border border-line bg-canvas/70 px-2.5 py-1 font-mono text-xs hover:border-accent">{symbol}</button>) : <span className="text-xs text-ink-400">Henüz favori eklenmedi.</span>}
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-600"><input type="checkbox" checked={syncPanels} onChange={(event) => setSyncPanels(event.target.checked)} />Panelleri eşitle</label>
      </Card>

      <div className={`grid gap-4 ${panelCount === 1 ? "grid-cols-1" : "grid-cols-1 2xl:grid-cols-2"}`}>
        {panelConfigs.slice(0, panelCount).map((panel, index) => <Card key={index} className="min-w-0 p-3 sm:p-4">
          <div className="mb-2 text-xs font-semibold text-ink-400">Panel {index + 1} · {panel.symbol} ({panel.interval}) · bağımsız sembol ve zaman aralığı</div>
          <MarketChart
            panelId={`panel-${index + 1}`}
            initialSymbol={panel.symbol}
            initialInterval={panel.interval}
            symbols={symbolOptions}
            onSymbolChange={(symbol) => updatePanel(index, "symbol", symbol)}
            onIntervalChange={(interval) => updatePanel(index, "interval", interval)}
          />
        </Card>)}
      </div>
      <p className="text-[11px] text-ink-400">Hazır göstergeler: Hacim, SMA, EMA, Bollinger Bands, RSI, MACD, VWAP, ATR ve ADX. Grafik kütüphanesi: TradingView Lightweight Charts™.</p>
    </div>
  );
}
