"use client";

import { Badge } from "./ui";
import { formatPct, formatPrice } from "../lib/format";
import type { OpportunityView } from "../lib/opportunity";

/**
 * Fırsat kartı — tasarımdaki kartın birebir karşılığı:
 * sıra no · süre rozeti · coin/isim · yükseliş potansiyeli kutusu · fiyat+değişim
 * · Hedef / Sinyal Gücü / Hacim Artışı · "İşleme Gir" butonu.
 * Kartın altında hangi TESPİT SİSTEMİNİN ürettiği etiketler görünür.
 */
export default function OpportunityCard({
  rank,
  item,
  selected,
  onSelect,
}: {
  rank: number;
  item: OpportunityView;
  selected: boolean;
  onSelect: () => void;
}) {
  const { potentialPct, changePct, strength, price, horizonMinutes, volumeRatio } = item;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`odak-card flex w-full flex-col p-4 text-left transition-shadow hover:shadow-pop ${
        selected ? "ring-2 ring-accent" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-canvas text-xs font-bold text-ink-500">{rank}</span>
          {horizonMinutes != null && (
            <span className="rounded-md bg-canvas px-1.5 py-0.5 font-mono text-[10px] font-semibold text-ink-500">
              {horizonMinutes} DK
            </span>
          )}
        </div>
        {potentialPct != null && (
          <div className="rounded-lg bg-gain-soft px-2.5 py-1 text-right">
            <p className="font-mono text-base font-bold leading-none text-gain">↗ {formatPct(potentialPct, 0)}</p>
            <p className="mt-0.5 text-[9px] leading-tight text-gain/80">Yükseliş Potansiyeli</p>
          </div>
        )}
      </div>

      <div className="mt-3">
        <p className="font-mono text-sm font-bold text-ink-900">
          {item.base} <span className="text-ink-400">/ TRY</span>
        </p>
      </div>

      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="font-mono text-lg font-semibold text-ink-900">{formatPrice(price)}</span>
        {changePct != null && (
          <span className={`font-mono text-xs font-semibold ${changePct >= 0 ? "text-gain" : "text-loss"}`}>
            {changePct >= 0 ? "+" : ""}
            {formatPct(changePct, 1)}
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-center">
        <div>
          <p className="text-[9px] uppercase tracking-wide text-ink-400">Hedef</p>
          <p className="font-mono text-xs font-semibold text-ink-700">{formatPct(item.targetPct ?? potentialPct, 1, true)}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase tracking-wide text-ink-400">Sinyal Gücü</p>
          <p className="font-mono text-xs font-semibold text-ink-700">{strength != null ? `%${Math.round(strength)}` : "—"}</p>
        </div>
        <div>
          <p className="text-[9px] uppercase tracking-wide text-ink-400">Hacim Oranı</p>
          <p className="font-mono text-xs font-semibold text-ink-700">
            {/* volume_ratio ortalamaya göre ORAN (≥2.0 eşik). Oran olarak bas:
                1.8× gibi. Yüzdeye çevirmek yanıltıcı olurdu. */}
            {volumeRatio != null ? `${volumeRatio.toFixed(2)}×` : "—"}
          </p>
        </div>
      </div>

      {/* Hangi sistem üretti */}
      {item.sources.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {item.sources.slice(0, 3).map((s) => (
            <Badge key={s} tone="accent">
              {s}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-3">
        <span className="inline-flex w-full items-center justify-center rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white">
          İşleme Gir →
        </span>
      </div>
    </button>
  );
}
