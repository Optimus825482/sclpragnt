"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import MarketChart from "../components/MarketChart";
import { Card, SectionHeader } from "../components/ui";
import { usePoll } from "../lib/hooks";
import { useWatchlist } from "../lib/watchlist";
import type { MarketSymbols } from "../lib/types";

type Panels = 1 | 2 | 4;
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLTRY", "AVAXTRY"];

export default function GrafikPage() {
  const [panels, setPanels] = useState<Panels>(1);
  const [selectedSymbol, setSelectedSymbol] = useState(DEFAULT_SYMBOLS[0]);
  const [interval, setInterval] = useState("5m");
  const marketSymbols = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const { favorites, isFavorite, toggleFavorite } = useWatchlist();

  const symbolOptions = Array.from(
    new Set([...favorites, ...DEFAULT_SYMBOLS, ...(marketSymbols.data?.symbols || [])])
  );

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const symbol = (query.get("symbol") || "").toUpperCase().replace(/[^A-Z0-9_]/g, "");
    const tf = query.get("interval");
    if (symbol) setSelectedSymbol(symbol);
    if (["1m", "5m", "15m", "1h", "4h", "1d"].includes(tf || "")) setInterval(tf!);
  }, []);

  const isFav = isFavorite(selectedSymbol);

  return (
    <div className="space-y-4">
      <SectionHeader
        eyebrow="Teknik Analiz"
        title="Canlı Binance TR Grafikleri"
        description="Profesyonel mum grafikleri, RSI, MACD, Bollinger bantları ve hacim analizi."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/"
              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-accent/90"
            >
              ← Anasayfa & İşlem Paneli
            </Link>
            <div className="flex rounded-lg border border-line bg-white p-1" aria-label="Grafik panel sayısı">
              {([1, 2, 4] as const).map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-pressed={panels === n}
                  onClick={() => setPanels(n)}
                  className={`min-w-8 rounded-md px-2.5 py-1 text-xs font-semibold ${
                    panels === n ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas"
                  }`}
                >
                  {n} Panel
                </button>
              ))}
            </div>
          </div>
        }
      />

      {/* FAVORİ SEMBOLLER HIZLI GEÇİŞ ÇUBUĞU */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-white p-2.5 shadow-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-ink-500 mr-1 flex items-center gap-1">
            <span className="text-amber-500">★</span> Favoriler:
          </span>
          {favorites.length === 0 ? (
            <span className="text-xs text-ink-400">Henüz favori eklenmedi (yıldız butonuna tıklayın).</span>
          ) : (
            favorites.map((sym) => (
              <button
                key={sym}
                type="button"
                onClick={() => setSelectedSymbol(sym)}
                className={`rounded-lg border px-2.5 py-1 font-mono text-xs font-medium transition-colors ${
                  selectedSymbol === sym
                    ? "border-accent bg-accent-soft text-accent font-bold"
                    : "border-line bg-canvas/70 text-ink-700 hover:border-accent"
                }`}
              >
                {sym}
              </button>
            ))
          )}
        </div>

        <button
          type="button"
          onClick={() => toggleFavorite(selectedSymbol)}
          className={`flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
            isFav
              ? "border-amber-400 bg-amber-50 text-amber-600 font-bold"
              : "border-line bg-white text-ink-600 hover:border-amber-400"
          }`}
        >
          <span>{isFav ? "★" : "☆"}</span>
          <span>{isFav ? "Favorilerden Çıkar" : "Bu Sembolü Favorile"}</span>
        </button>
      </div>

      {/* GRAFİK PANELLERİ */}
      <div
        className={`grid gap-4 ${
          panels === 1 ? "grid-cols-1" : panels === 2 ? "grid-cols-1 2xl:grid-cols-2" : "grid-cols-1 xl:grid-cols-2"
        }`}
      >
        {Array.from({ length: panels }, (_, index) => (
          <Card key={index} className="min-w-0 p-3 sm:p-4">
            <div className="mb-2 text-xs font-semibold text-ink-400">
              Panel {index + 1} · {selectedSymbol} ({interval})
            </div>
            <MarketChart
              initialSymbol={selectedSymbol}
              initialInterval={interval}
              symbols={symbolOptions}
              onSymbolChange={setSelectedSymbol}
            />
          </Card>
        ))}
      </div>
      <p className="text-[11px] text-ink-400">
        RSI (14) ve ADX (14) seçili periyoda göre hesaplanır · Bollinger Bands (20,2) açık · Alt panel MACD histogramıdır.
      </p>
    </div>
  );
}
