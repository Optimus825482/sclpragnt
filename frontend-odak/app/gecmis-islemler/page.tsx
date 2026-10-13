"use client";

import { useState } from "react";
import { usePoll } from "../lib/hooks";
import { fmtDateTime, formatFixed, formatPct, formatPrice, formatSignedTL } from "../lib/format";
import { baseAsset } from "../lib/opportunity";
import { sourceLabel } from "../lib/sources";
import type { TradesResponse } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";

/**
 * GEÇMİŞ İŞLEMLER — açılıp kapanmış trade'ler (/api/trades).
 * Gerçek sunucu-taraflı sayfalama (`limit` + `offset` + `total`).
 */
const PAGE_SIZE = 30;

export default function GecmisIslemlerPage() {
  const [page, setPage] = useState(0);
  const offset = page * PAGE_SIZE;
  const { data, error, loading } = usePoll<TradesResponse>(`/api/trades?limit=${PAGE_SIZE}&offset=${offset}`, 30_000);

  const trades = data?.trades || [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Geçmiş İşlemler"
        title="Kapanmış işlemler"
        description="Gerçekleşmiş alım/satım işlemleri ve net K/Z sonuçları."
      />

      {loading && !data ? (
        <Skeleton className="h-64" />
      ) : error && !data ? (
        <EmptyState title="İşlem geçmişi alınamadı" hint={error} tone="loss" />
      ) : trades.length === 0 ? (
        <EmptyState title="Kapanmış işlem yok" hint="Henüz kapanmış bir trade bulunmuyor." />
      ) : (
        <Card className="p-4">
          <div className="odak-scroll">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
                  <th className="pb-2 pr-3 font-medium">Kapanış</th>
                  <th className="pb-2 pr-3 font-medium">Coin</th>
                  <th className="pb-2 pr-3 font-medium">Kaynak</th>
                  <th className="pb-2 pr-3 font-medium">Yön</th>
                  <th className="pb-2 pr-3 text-right font-medium">Giriş</th>
                  <th className="pb-2 pr-3 text-right font-medium">Çıkış</th>
                  <th className="pb-2 pr-3 text-right font-medium">Miktar</th>
                  <th className="pb-2 pr-3 text-right font-medium">K/Z</th>
                  <th className="pb-2 pr-3 text-right font-medium">K/Z %</th>
                  <th className="pb-2 font-medium">Sebep</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => {
                  const tone = t.pnl == null ? "text-ink-500" : t.pnl > 0 ? "text-gain" : t.pnl < 0 ? "text-loss" : "text-ink-500";
                  const long = String(t.side || "LONG").toUpperCase() !== "SHORT";
                  return (
                    <tr key={t.id} className="border-t border-line">
                      <td className="py-2 pr-3 font-mono text-xs text-ink-500">{fmtDateTime(t.exit_time)}</td>
                      <td className="py-2 pr-3 font-mono font-semibold text-ink-900">{baseAsset(t.symbol)}</td>
                      <td className="py-2 pr-3">
                        <Badge tone="accent">{sourceLabel(t.strategy) || t.strategy || "—"}</Badge>
                      </td>
                      <td className="py-2 pr-3">
                        <Badge tone={long ? "gain" : "loss"}>{long ? "AL" : "SAT"}</Badge>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPrice(t.entry_price)}</td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPrice(t.exit_price)}</td>
                      <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatFixed(t.quantity, 4)}</td>
                      <td className={`py-2 pr-3 text-right font-mono ${tone}`}>{formatSignedTL(t.pnl)}</td>
                      <td className={`py-2 pr-3 text-right font-mono ${tone}`}>{formatPct(t.pnl_pct, 2, true)}</td>
                      <td className="py-2 text-xs text-ink-400">{t.reason || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
            <span>
              {total} kayıt · sayfa {page + 1}/{pageCount}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
              >
                ← Önceki
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                disabled={page >= pageCount - 1}
                className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
              >
                Sonraki →
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
