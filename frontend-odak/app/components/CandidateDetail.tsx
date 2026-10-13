"use client";

import { Badge, Button, Card, EmptyState } from "./ui";
import { formatFixed, formatPct, formatPrice } from "../lib/format";
import { fmtDateTime } from "../lib/format";
import type { Opportunity } from "../lib/types";

/**
 * Sağ panel — tasarımdaki "Emir Kartı"nın yerine ADAY DETAYI.
 *
 * Bilinçli sapma: bu sistem PAPER-ONLY'dir; sahte AL/SAT emir formülü koymak
 * yanıltıcı olurdu. Bunun yerine seçili adayın gerçek alanları gösterilir ve
 * gerçek işlem için mevcut panelin Binance TR sayfasına bağlantı verilir.
 */
export default function CandidateDetail({ item }: { item: Opportunity | null }) {
  if (!item) {
    return (
      <Card className="p-4">
        <p className="odak-kicker">Aday detayı</p>
        <div className="mt-3">
          <EmptyState title="Bir fırsat seçin" hint="Soldaki kartlardan birine dokunun." />
        </div>
      </Card>
    );
  }

  const potential = item.potential_pct ?? item.ceiling_pct ?? null;
  const rows: Array<[string, string]> = [
    ["Güncel fiyat", formatPrice(item.current_price)],
    ["Giriş/anchor", formatPrice(item.entry_price)],
    ["Değişim", formatPct(item.change_pct, 2, true)],
    ["Potansiyel", formatPct(potential, 2, true)],
    ["Tavan fiyat", formatPrice(item.ceiling_price)],
    ["Potansiyel fiyat", formatPrice(item.potential_price)],
    ["Kalite skoru", item.quality_score != null ? formatFixed(item.quality_score, 0) : "—"],
    ["Tarama skoru", item.scan_score != null ? formatFixed(item.scan_score, 0) : "—"],
    ["Hedef olasılığı", item.target_probability != null ? formatPct(item.target_probability, 0) : "—"],
    ["Strateji", item.strategy || "—"],
    ["Durum", item.status || "—"],
    ["Oluşturma", fmtDateTime(item.created_at)],
  ];

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="odak-kicker">Aday detayı</p>
          <h3 className="mt-1 font-mono text-lg font-bold text-ink-900">{item.symbol}</h3>
        </div>
        {potential != null && <Badge tone="gain">↗ {formatPct(potential, 1)}</Badge>}
      </div>

      <dl className="mt-4 space-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between border-b border-line/70 pb-1.5 last:border-0">
            <dt className="text-ink-500">{label}</dt>
            <dd className="font-mono text-ink-900">{value}</dd>
          </div>
        ))}
      </dl>

      <a
        href="http://localhost:3004/binance-tr"
        className="mt-4 block"
        title="Gerçek hesap işlemleri mevcut panelde yapılır (paper-only değil)"
      >
        <Button variant="primary" className="w-full">
          Binance TR'de işlem ↗
        </Button>
      </a>
      <p className="mt-2 text-center text-[11px] text-ink-400">
        Bu panel salt-okunur (paper veri). Gerçek emirler mevcut arayüzde.
      </p>
    </Card>
  );
}
