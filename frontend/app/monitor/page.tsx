"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import RequireAdmin from "../components/RequireAdmin";
import SymbolLink from "../components/SymbolLink";
import { API_BASE, apiRequest } from "../lib/api";
import { fmtClockTime, fmtMinute, formatPrice } from "../lib/format";
import { useVisibleInterval } from "../lib/useVisibleInterval";

const statuses = {
  early: { label: "Erken izleme", tone: "text-cyan-300" },
  watch: { label: "+%10 teyit", tone: "text-amber-300" },
  open: { label: "Paper açık", tone: "text-neon-green" },
  closed: { label: "Paper kapandı", tone: "text-white" },
  blocked: { label: "Paper açılmadı", tone: "text-rose-300" },
  expired: { label: "Pencere doldu", tone: "text-bunker-muted" },
};

type MonitorRow = {
  symbol: string;
  seed_ms: number;
  base_price: number;
  early_watch_ms: number | null;
  early_watch_price: number | null;
  watch_ms: number | null;
  signal_ms: number | null;
  signal_price: number | null;
  entry_price: number | null;
  exit_price: number | null;
  closed_at: number | null;
  net_pnl_pct: number | null;
  mark_net_pct: number | null;
  current_price: number | null;
  expires_at_ms: number;
  display_status: keyof typeof statuses;
};

type MonitorSnapshot = { rows: MonitorRow[]; as_of_ms: number; hours: number; limit: number };
type Filter = "all" | "active" | "signals";

const filters: { id: Filter; label: string }[] = [
  { id: "all", label: "Tümü" },
  { id: "active", label: "Aktif" },
  { id: "signals", label: "+%15 sinyalleri" },
];
const percent = new Intl.NumberFormat("tr-TR", {
  style: "percent", maximumFractionDigits: 2, signDisplay: "exceptZero",
});
const price = (value: number | null) => value == null ? "—" : `₺${formatPrice(value)}`;
const isWatching = (row: MonitorRow) => row.display_status === "early" || row.display_status === "watch";
const isActive = (row: MonitorRow) => isWatching(row) || row.display_status === "open";

export default function MonitorPage() {
  return <RequireAdmin><MonitorView /></RequireAdmin>;
}

function MonitorView() {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const inFlight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    const request = new AbortController();
    inFlight.current = request;
    try {
      const response = await apiRequest(`${API_BASE}/api/reports/large-move-monitor`, { signal: request.signal });
      if (!response.ok) throw new Error(String(response.status));
      const data: MonitorSnapshot = await response.json();
      if (!request.signal.aborted) {
        setSnapshot(data);
        setError(false);
      }
    } catch {
      if (!request.signal.aborted) setError(true);
    } finally {
      if (inFlight.current === request) inFlight.current = null;
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (mounted) void refresh();
    });
    return () => {
      mounted = false;
      inFlight.current?.abort();
      inFlight.current = null;
    };
  }, [refresh]);
  useVisibleInterval(refresh, 5_000);

  const rows = snapshot?.rows ?? [];
  const symbolQuery = query.trim().replaceAll("_", "").toUpperCase();
  const matching = rows.filter((row) => row.symbol.includes(symbolQuery)
    && (filter !== "active" || isActive(row))
    && (filter !== "signals" || row.signal_ms != null));

  return (
    <section className="max-w-7xl mx-auto space-y-5" aria-labelledby="monitor-title">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-bunker-800 pb-4">
        <div>
          <h1 id="monitor-title" className="text-2xl font-bold text-white">Büyük Hareket Monitor</h1>
          <p className="mt-1 text-sm text-bunker-muted">
            +%5 erken izleme · +%10 cihaz bildirimi · +%15 paper giriş sinyali
          </p>
        </div>
        <Link className="ui-button ui-button-secondary touch-target" href="/reports">Raporlar</Link>
      </header>

      <dl className="grid grid-cols-3 gap-2">
        {[
          ["Erken izleme", rows.filter((row) => row.display_status === "early").length, "text-cyan-300"],
          ["+%10 teyit", rows.filter((row) => row.display_status === "watch").length, "text-amber-300"],
          ["Açık paper", rows.filter((row) => row.display_status === "open").length, "text-neon-green"],
        ].map(([label, count, tone]) => (
          <div key={label} className="rounded-lg border border-bunker-800 bg-bunker-950/70 px-3 py-2.5">
            <dt className="text-xs text-bunker-muted">{label}</dt>
            <dd className={`mt-1 font-mono text-xl font-semibold tabular-nums ${tone}`}>{snapshot ? count : "—"}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <fieldset className="flex flex-wrap gap-1.5">
            <legend className="sr-only">Kayıt filtresi</legend>
            {filters.map(({ id, label }) => (
              <button key={id} type="button" aria-pressed={id === filter} onClick={() => setFilter(id)}
                className={`ui-button touch-target ${id === filter ? "ui-button-primary" : "ui-button-secondary"}`}>
                {label}
              </button>
            ))}
          </fieldset>
          <label className="text-xs text-bunker-muted">
            Parite ara
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
              placeholder="Örn. CFGTRY" className="input mt-1 block w-36 touch-target" />
          </label>
        </div>
        <button type="button" onClick={() => void refresh()} className="ui-button ui-button-secondary touch-target">Yenile</button>
      </div>

      {error && <p role="status" className="text-sm text-amber-300">
        {snapshot ? "Bağlantı kesildi. Son alınan veriler gösteriliyor." : "Monitor verisi alınamadı. Bağlantı yeniden deneniyor."}
      </p>}
      {!snapshot && !error && <p role="status" className="card p-5 text-sm text-bunker-muted">Monitor yükleniyor…</p>}
      {snapshot && (
        <>
          <div className="flex flex-wrap justify-between gap-1 text-xs text-bunker-muted">
            <p>Son {snapshot.hours} saat · {matching.length} kayıt{rows.length === snapshot.limit ? ` · en çok ${snapshot.limit}` : ""}</p>
            <p>Son güncelleme {fmtClockTime(snapshot.as_of_ms)}</p>
          </div>
          {matching.length === 0 ? (
            <p className="card p-5 text-sm text-bunker-muted">Bu filtreye uyan izleme kaydı yok.</p>
          ) : (
            <div role="region" aria-label="Büyük Hareket izleme tablosu" tabIndex={0} className="table-scroll max-h-[66vh]">
              <table className="data-table table-compact whitespace-nowrap">
                <thead className="sticky top-0 z-20 bg-bunker-950">
                  <tr>
                    <th scope="col" className="sticky left-0 bg-bunker-950">Parite</th>
                    {["Durum", "+%5 erken izleme", "+%10 teyit", "+%15 sinyali", "Güncel / bazdan", "Paper"].map((label) => (
                      <th scope="col" key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matching.map((row) => {
                    const status = statuses[row.display_status];
                    const change = row.current_price != null ? row.current_price / row.base_price - 1 : null;
                    const pnl = row.net_pnl_pct ?? row.mark_net_pct;
                    return (
                      <tr key={`${row.symbol}-${row.seed_ms}`}>
                        <th scope="row" className="sticky left-0 z-10 bg-bunker-950">
                          <SymbolLink symbol={row.symbol} timeframe="1m" />
                        </th>
                        <td>
                          <span className={`font-semibold ${status.tone}`}>{status.label}</span>
                          {isWatching(row) && <span className="block text-xs text-bunker-muted">Pencere sonu {fmtMinute(row.expires_at_ms)}</span>}
                        </td>
                        <td>{fmtMinute(row.early_watch_ms)}{row.early_watch_price != null && <span className="block text-xs text-cyan-300">{price(row.early_watch_price)}</span>}</td>
                        <td>{fmtMinute(row.watch_ms)}</td>
                        <td>{fmtMinute(row.signal_ms)}{row.signal_price != null && <span className="block text-xs text-amber-300">{price(row.signal_price)}</span>}</td>
                        <td>
                          {price(row.current_price)}
                          {change != null && <span className={`block text-xs ${change >= 0 ? "text-neon-green" : "text-rose-300"}`}>{percent.format(change)}</span>}
                        </td>
                        <td>
                          {row.entry_price == null ? "—" : price(row.entry_price)}
                          {row.exit_price != null && <span className="ml-1">→ {price(row.exit_price)}</span>}
                          {row.closed_at != null && <span className="block text-xs text-bunker-muted">{fmtMinute(row.closed_at)}</span>}
                          {pnl != null && <span className={`block text-xs ${pnl >= 0 ? "text-neon-green" : "text-rose-300"}`}>{percent.format(pnl / 100)}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
