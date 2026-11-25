"use client";

/**
 * Radar > "Yükselenler" sekmesi (2026-11-25, kullanıcı isteği).
 *
 * Son 24 saatte en çok yükselen TRY çiftleri — Binance TR 24s ticker'ından,
 * ilk 20. Sekme açıkken 180 saniyede bir, sekme görünür değilken durur.
 *
 * NEDEN TR kaynağı: işlem evrenimiz TRY çiftleri; global (USD) sıralamalar
 * alakasız semboller getiriyordu ve CMC kotası harcıyordu.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE, apiRequest } from "../lib/api";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import SymbolLink from "./SymbolLink";

type GainerRow = {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  high_24h?: number | null;
  low_24h?: number | null;
};

// 2026-11-25 (kullanıcı): 180 sn (borsa ağırlığını korumak için).
const REFRESH_MS = 180_000;

function fmtPrice(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value >= 1000) return value.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
  if (value >= 1) return value.toLocaleString("tr-TR", { maximumFractionDigits: 4 });
  return value.toLocaleString("tr-TR", { maximumFractionDigits: 8 });
}

function fmtVolumeM(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${(value / 1_000_000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}M`;
}

export default function TopGainersList() {
  const [items, setItems] = useState<GainerRow[] | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const r = await apiRequest(`${API_BASE}/api/radar/top-gainers?limit=20`, { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Veri alınamadı");
      setItems(Array.isArray(d?.items) ? d.items : []);
      setUpdatedAt(typeof d?.generated_at === "number" ? d.generated_at : Date.now() / 1000);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Veri alınamadı");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Sekme görünürken 15 sn'de bir tazele; arka plandayken dur.
  useVisibleInterval(load, REFRESH_MS);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-bunker-muted">
          Son 24 saatte en çok yükselen 20 TRY çifti · Binance TR ·{" "}
          {updatedAt ? `son güncelleme ${new Date(updatedAt * 1000).toLocaleTimeString("tr-TR")}` : "yükleniyor…"}
        </p>
        <button type="button" onClick={load} className="ui-button ui-button-secondary">
          YENİLE
        </button>
      </div>

      {error && <p className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      {items == null && !error && <p className="py-6 text-center text-sm text-bunker-muted">Yükleniyor…</p>}
      {items && items.length === 0 && !error && (
        <p className="py-6 text-center text-sm text-bunker-muted">Şu an yükselen çift yok.</p>
      )}

      {items && items.length > 0 && (
        <ol className="divide-y divide-bunker-800 rounded-xl border border-bunker-800 overflow-hidden">
          {items.map((row, idx) => (
            <li key={row.symbol} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="flex min-w-0 items-center gap-3">
                <span className="w-6 shrink-0 text-right font-mono text-xs text-bunker-muted">{idx + 1}</span>
                <SymbolLink symbol={row.symbol} className="truncate font-semibold text-white" />
              </div>
              <div className="flex shrink-0 items-center gap-3 font-mono text-xs">
                <span className="text-white">{fmtPrice(row.price)}</span>
                <span className="text-neon-green">+{row.change_24h.toFixed(2)}%</span>
                <span className="hidden text-bunker-muted sm:inline">{fmtVolumeM(row.volume_24h)}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
