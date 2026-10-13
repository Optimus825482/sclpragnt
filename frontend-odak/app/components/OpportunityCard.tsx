"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "./ui";
import { formatPct, formatPrice } from "../lib/format";
import type { OpportunityView } from "../lib/opportunity";
import MarketChart from "./MarketChart";

function chartInterval(minutes: number | null) { return minutes != null && minutes >= 60 ? "1h" : "5m"; }

export default function OpportunityCard({ rank, item, selected, onSelect }: { rank: number; item: OpportunityView; selected: boolean; onSelect: () => void }) {
  const { potentialPct, changePct, strength, price, horizonMinutes, volumeRatio } = item;
  const [chartOpen, setChartOpen] = useState(false);
  const interval = chartInterval(horizonMinutes);
  const chartUrl = `/grafik?symbol=${encodeURIComponent(item.symbol)}&interval=${interval}`;

  useEffect(() => {
    if (!chartOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setChartOpen(false); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [chartOpen]);

  return <>
    <article className={`odak-card flex w-full flex-col p-4 transition-shadow hover:shadow-pop ${selected ? "ring-2 ring-accent" : ""}`}>
      <button type="button" onClick={onSelect} aria-pressed={selected} className="text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-md bg-canvas text-xs font-bold text-ink-500">{rank}</span>{horizonMinutes != null && <span className="rounded-md bg-canvas px-1.5 py-0.5 font-mono text-[10px] font-semibold text-ink-500">{horizonMinutes} DK</span>}</div>
          {potentialPct != null && <div className="rounded-lg bg-gain-soft px-2.5 py-1 text-right"><p className="font-mono text-base font-bold leading-none text-gain">↗ {formatPct(potentialPct, 0)}</p><p className="mt-0.5 text-[9px] leading-tight text-gain/80">Yükseliş Potansiyeli</p></div>}
        </div>
        <p className="mt-3 font-mono text-sm font-bold text-ink-900">{item.base} <span className="text-ink-400">/ TRY</span></p>
        <div className="mt-1.5 flex items-baseline gap-2"><span className="font-mono text-lg font-semibold text-ink-900">{formatPrice(price)}</span>{changePct != null && <span className={`font-mono text-xs font-semibold ${changePct >= 0 ? "text-gain" : "text-loss"}`}>{changePct >= 0 ? "+" : ""}{formatPct(changePct, 1)}</span>}</div>
      </button>
      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-center">
        <div><p className="text-[9px] uppercase tracking-wide text-ink-400">Hedef</p><p className="font-mono text-xs font-semibold text-ink-700">{formatPct(item.targetPct ?? potentialPct, 1, true)}</p></div>
        <div><p className="text-[9px] uppercase tracking-wide text-ink-400">Sinyal Gücü</p><p className="font-mono text-xs font-semibold text-ink-700">{strength != null ? `%${Math.round(strength)}` : "—"}</p></div>
        <div><p className="text-[9px] uppercase tracking-wide text-ink-400">Hacim Oranı</p><p className="font-mono text-xs font-semibold text-ink-700">{volumeRatio != null ? `${volumeRatio.toFixed(2)}×` : "—"}</p></div>
      </div>
      {item.sources.length > 0 && <div className="mt-3 flex flex-wrap gap-1">{item.sources.slice(0, 3).map((source) => <Badge key={source} tone="accent">{source}</Badge>)}</div>}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" onClick={onSelect} className="inline-flex items-center justify-center rounded-lg bg-accent px-2 py-2 text-xs font-semibold text-white">İşleme Gir →</button>
        <button type="button" onClick={() => setChartOpen(true)} aria-haspopup="dialog" className="inline-flex items-center justify-center rounded-lg border border-accent/30 bg-accent-soft px-2 py-2 text-xs font-semibold text-accent">▥ Grafik</button>
      </div>
    </article>
    {chartOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-3 sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setChartOpen(false); }}>
      <section role="dialog" aria-modal="true" aria-labelledby={`chart-title-${rank}`} className="max-h-[95vh] w-full max-w-5xl overflow-y-auto rounded-2xl border border-line bg-white p-4 shadow-2xl sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-medium text-ink-400">Fırsat grafiği</p><h2 id={`chart-title-${rank}`} className="text-lg font-semibold text-ink-900">{item.base} / TRY</h2></div><div className="flex items-center gap-2"><Link href={chartUrl} onClick={() => setChartOpen(false)} className="rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white">Grafik sayfasında aç</Link><button type="button" aria-label="Grafik penceresini kapat" onClick={() => setChartOpen(false)} className="grid h-9 w-9 place-items-center rounded-lg border border-line text-lg text-ink-500 hover:bg-canvas">×</button></div></div>
        <MarketChart initialSymbol={item.symbol} initialInterval={interval} compact />
      </section>
    </div>}
  </>;
}
