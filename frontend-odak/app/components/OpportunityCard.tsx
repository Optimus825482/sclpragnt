"use client";

import { Badge } from "./ui";
import { formatPct, formatPrice } from "../lib/format";
import type { Opportunity } from "../lib/types";

/**
 * Fırsat kartı. Tasarımdaki kartın sadeleştirilmiş hâli: her alan gerçek bir
 * backend değerine bağlı, olmayan alan gizlenir (uydurma yok).
 */
export default function OpportunityCard({
  rank,
  item,
  selected,
  onSelect,
}: {
  rank: number;
  item: Opportunity;
  selected: boolean;
  onSelect: () => void;
}) {
  const potential = item.potential_pct ?? item.ceiling_pct ?? null;
  const change = item.change_pct ?? null;
  const strength = item.quality_score ?? item.scan_score ?? null;
  const horizon = (item as { horizon_minutes?: number }).horizon_minutes ?? null;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`odak-card w-full p-4 text-left transition-shadow hover:shadow-pop ${
        selected ? "ring-2 ring-accent" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-canvas text-xs font-bold text-ink-500">{rank}</span>
          <div>
            <p className="font-mono text-sm font-semibold text-ink-900">{item.symbol}</p>
            {horizon != null && <p className="text-[11px] text-ink-400">{horizon} dk ufuk</p>}
          </div>
        </div>
        {potential != null && (
          <div className="text-right">
            <p className="font-mono text-lg font-bold text-gain">↗ {formatPct(potential, 1)}</p>
            <p className="text-[10px] leading-tight text-ink-400">potansiyel</p>
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <span className="font-mono text-sm text-ink-700">{formatPrice(item.current_price)}</span>
        {change != null && (
          <span className={`font-mono text-xs ${change >= 0 ? "text-gain" : "text-loss"}`}>
            {change >= 0 ? "+" : ""}
            {formatPct(change, 1)}
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3">
        <div>
          <p className="text-[10px] text-ink-400">Hedef</p>
          <p className="font-mono text-xs text-ink-700">{formatPct(item.potential_pct, 1, true)}</p>
        </div>
        <div>
          <p className="text-[10px] text-ink-400">Sinyal gücü</p>
          <p className="font-mono text-xs text-ink-700">{strength != null ? Math.round(strength) : "—"}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <Badge tone="accent">Detay</Badge>
        <span className="text-[11px] text-ink-400">{item.strategy || item.status || ""}</span>
      </div>
    </button>
  );
}
