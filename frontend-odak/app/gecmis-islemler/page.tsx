"use client";

import { useMemo, useState } from "react";
import { usePoll } from "../lib/hooks";
import { fmtDateTime, formatFixed, formatPrice, formatSignedTL } from "../lib/format";
import { baseAsset } from "../lib/opportunity";
import type { BinanceSettings } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";

type BinanceFill = {
  id?: number | string; symbol: string; time?: number; price?: number; qty?: number;
  quoteQty?: number; isBuyer?: boolean; commission?: number; commissionAsset?: string;
  basis_price?: number; realized_pnl_try?: number;
};
type BinanceDay = { trades?: BinanceFill[]; count?: number; daily?: { realized_pnl_try?: number; wins?: number; losses?: number } };
const PAGE_SIZE = 25;

function todayIstanbul() {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "00";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Gerçek Binance TR dolum geçmişi; gün filtresi sunucuya, sayfalama ekrana uygulanır. */
export default function GecmisIslemlerPage() {
  const [date, setDate] = useState(todayIstanbul);
  const [page, setPage] = useState(0);
  const settings = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const result = usePoll<BinanceDay>(settings.data?.configured ? `/api/binance/trades-day?date=${date}` : null, 120_000, 30_000);
  const trades = useMemo(() => result.data?.trades || [], [result.data]);
  const pageCount = Math.max(1, Math.ceil(trades.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = trades.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (settings.loading) return <Skeleton className="h-64" />;
  if (!settings.data?.configured) return <EmptyState title="Binance TR hesabı bağlı değil" hint="Gerçek alım/satım geçmişini görüntülemek için Ayarlar'dan hesabınızı bağlayın." />;

  return <div className="space-y-5">
    <SectionHeader eyebrow="Geçmiş İşlemler" title="Binance TR işlem geçmişi" description="Seçilen günde gerçekleşen gerçek spot alım ve satım dolumları." actions={
      <label className="flex items-center gap-2 text-sm text-ink-500">Gün
        <input type="date" value={date} onChange={(e) => { setDate(e.target.value); setPage(0); }} className="rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900" />
      </label>
    } />

    {result.loading && !result.data ? <Skeleton className="h-64" /> : result.error && !result.data ? <EmptyState title="Binance geçmişi alınamadı" hint={result.error} tone="loss" /> : trades.length === 0 ? <EmptyState title="Bu günde işlem yok" hint="Seçilen tarihte Binance TR hesabında gerçekleşmiş dolum bulunmuyor." /> : <Card className="p-4">
      <div className="mb-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Dolum</p><p className="mt-1 font-mono font-semibold text-ink-900">{result.data?.count ?? trades.length}</p></div>
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Günlük Gerçekleşen Net K/Z</p><p className={`mt-1 font-mono font-semibold ${(result.data?.daily?.realized_pnl_try || 0) >= 0 ? "text-gain" : "text-loss"}`}>{formatSignedTL(result.data?.daily?.realized_pnl_try)}</p></div>
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Sonuç</p><p className="mt-1 font-mono font-semibold text-ink-900">{result.data?.daily?.wins ?? 0} kâr · {result.data?.daily?.losses ?? 0} zarar</p></div>
      </div>
      <div className="odak-scroll"><table className="w-full min-w-[900px] border-collapse text-sm">
        <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
          <th className="pb-2 pr-3 font-medium">Zaman</th><th className="pb-2 pr-3 font-medium">Coin</th><th className="pb-2 pr-3 font-medium">Yön</th>
          <th className="pb-2 pr-3 text-right font-medium">Fiyat</th><th className="pb-2 pr-3 text-right font-medium">Miktar</th>
          <th className="pb-2 pr-3 text-right font-medium">Tutar</th><th className="pb-2 pr-3 text-right font-medium">Komisyon</th><th className="pb-2 pr-3 text-right font-medium">Net K/Z</th><th className="pb-2 font-medium">Emir No</th>
        </tr></thead>
        <tbody>{visible.map((trade, i) => {
          const buying = Boolean(trade.isBuyer);
          const pnl = trade.realized_pnl_try;
          const tone = pnl == null ? "text-ink-400" : pnl >= 0 ? "text-gain" : "text-loss";
          return <tr key={`${trade.symbol}-${trade.id ?? i}`} className="border-t border-line">
            <td className="py-2 pr-3 font-mono text-xs text-ink-500">{fmtDateTime(trade.time)}</td>
            <td className="py-2 pr-3 font-mono font-semibold text-ink-900">{baseAsset(trade.symbol)}</td>
            <td className="py-2 pr-3"><Badge tone={buying ? "gain" : "loss"}>{buying ? "AL" : "SAT"}</Badge></td>
            <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPrice(trade.price)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatFixed(trade.qty, 6)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatFixed(trade.quoteQty, 2)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatFixed(trade.commission, 6)} {trade.commissionAsset || ""}</td>
            <td className={`py-2 pr-3 text-right font-mono ${tone}`}>{formatSignedTL(pnl)}</td>
            <td className="py-2 font-mono text-xs text-ink-400">{trade.id ?? "—"}</td>
          </tr>;
        })}</tbody>
      </table></div>
      <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
        <span>{trades.length} kayıt · sayfa {safePage + 1}/{pageCount}</span>
        <div className="flex gap-2">
          <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0} className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40">← Önceki</button>
          <button type="button" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={safePage >= pageCount - 1} className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40">Sonraki →</button>
        </div>
      </div>
    </Card>}
  </div>;
}
