"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import RequireAdmin from "../components/RequireAdmin";
import SymbolLink from "../components/SymbolLink";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// MACD MONITOR — aktif sembollerin M1/M3/M5/M15/M30/H1 MACD histogram yönü.
// Yeşil = histogram > 0 (MACD line sinyalin üstünde), kırmızı = histogram < 0.
// Canlı veri backend'in {"type":"macd_monitor"} WS yayınıyla ~1 sn'de bir
// gelir; REST snapshot (30 sn poll) WS kapalıyken yedek sağlar.
// ---------------------------------------------------------------------------

const TF_ORDER = ["1m", "3m", "5m", "15m", "30m", "1h"];
const TF_LABELS: Record<string, string> = { "1m": "1M", "3m": "3M", "5m": "5M", "15m": "15M", "30m": "30M", "1h": "1H" };
const POLL_MS = 30_000;

type MacdCell = { green: boolean; hist: number };
type SymbolMacd = { last: number | null; tfs: Record<string, MacdCell | null> };
type Snapshot = {
  universe: string[];
  symbols: Record<string, SymbolMacd>;
  generated_at: number;
  timeframes?: string[];
  running?: boolean;
};

const fmtTime = (ts: number | null | undefined) => {
  if (!ts) return "—";
  const date = new Date(ts * 1000);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("tr-TR");
};

const fmtPrice = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  const digits = value < 1 ? 8 : value < 100 ? 6 : 2;
  return Number(value).toLocaleString("tr-TR", { maximumFractionDigits: digits });
};

const histShort = (hist: number) => {
  const abs = Math.abs(hist);
  if (abs === 0) return "0";
  if (abs >= 0.0001) return hist.toFixed(4);
  return hist.toExponential(2);
};

export default function MacdMonitorPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyGreen, setOnlyGreen] = useState(false);
  const [sortAlpha, setSortAlpha] = useState(false);
  const liveStatus = useLiveStatus();

  const loadSnapshot = useCallback(() => {
    apiFetch("/api/admin/macd-monitor")
      .then((data) => {
        setSnapshot(data as Snapshot);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSnapshot();
    const timer = window.setInterval(loadSnapshot, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "macd_monitor" && message.data) setSnapshot(message.data);
  }, []);
  useLiveMessages(onLiveMessage);

  const tfs = useMemo(() => {
    const source = snapshot?.timeframes?.length ? snapshot.timeframes : TF_ORDER;
    return TF_ORDER.filter((tf) => source.includes(tf));
  }, [snapshot]);

  const rows = useMemo(() => {
    const symbols = snapshot?.symbols || {};
    const universe = snapshot?.universe?.length
      ? snapshot.universe
      : Object.keys(symbols);
    const upperQuery = query.trim().toUpperCase();

    const list = universe
      .filter((symbol) => !upperQuery || symbol.toUpperCase().includes(upperQuery))
      .map((symbol) => {
        const row = symbols[symbol];
        const tfsMap = row?.tfs || {};
        const greenCount = tfs.reduce((sum, tf) => sum + (tfsMap[tf]?.green ? 1 : 0), 0);
        return { symbol, last: row?.last ?? null, tfsMap, greenCount };
      })
      .filter((r) => !onlyGreen || r.greenCount === tfs.length);

    list.sort((a, b) =>
      sortAlpha
        ? a.symbol.localeCompare(b.symbol)
        : b.greenCount - a.greenCount || a.symbol.localeCompare(b.symbol),
    );
    return list;
  }, [snapshot, query, onlyGreen, sortAlpha, tfs]);

  const allGreenSymbols = useMemo(() => {
    const symbols = snapshot?.symbols || {};
    return (snapshot?.universe?.length ? snapshot.universe : Object.keys(symbols)).filter(
      (symbol) => tfs.length > 0 && tfs.every((tf) => symbols[symbol]?.tfs?.[tf]?.green),
    ).length;
  }, [snapshot, tfs]);

  const universeCount = snapshot?.universe?.length || Object.keys(snapshot?.symbols || {}).length;
  const stale = liveStatus === "open" && snapshot?.generated_at
    && Date.now() / 1000 - snapshot.generated_at > 15;

  return (
    <RequireAdmin>
      <main className="page-shell">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">CANLI MACD MONİTÖR</p>
            <h1 className="font-mono text-2xl font-bold text-white">MACD MONITOR</h1>
            <p className="mt-1 text-sm text-bunker-muted">
              Aktif sembollerin MACD histogram yönü — <b className="text-neon-green">yeşil</b> hist &gt; 0,{" "}
              <b className="text-neon-red">kırmızı</b> hist &lt; 0 (fiyat tick&apos;leriyle ~1 sn&apos;de bir tazelenir)
            </p>
          </div>
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 font-mono text-xs ${liveStatus === "open" ? "border-neon-green/40 bg-neon-green/5 text-neon-green" : "border-yellow-300/40 bg-yellow-300/5 text-yellow-300"}`}>
            <span className={`w-2 h-2 rounded-full ${liveStatus === "open" ? "bg-neon-green animate-pulse" : "bg-yellow-300"}`} />
            {liveStatus === "open" ? "CANLI · WS BAĞLI" : "WS KAPALI · REST YEDEK"}
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="card">
            <p className="eyebrow">AKTİF SEMBOL</p>
            <p className="mt-1 font-mono text-2xl font-bold text-white">{universeCount}</p>
          </div>
          <div className="card">
            <p className="eyebrow">TAM YEŞİL ({tfs.length}/{tfs.length})</p>
            <p className="mt-1 font-mono text-2xl font-bold text-neon-green">{allGreenSymbols}</p>
          </div>
          <div className="card">
            <p className="eyebrow">SON GÜNCELLEME</p>
            <p className="mt-1 font-mono text-lg font-bold text-white">{fmtTime(snapshot?.generated_at)}</p>
          </div>
          <div className="card">
            <p className="eyebrow">VERİ KAPSAMI</p>
            <p className="mt-1 font-mono text-lg font-bold text-bunker-muted">{tfs.map((tf) => TF_LABELS[tf]).join(" · ")}</p>
          </div>
        </div>

        <div className="card mt-4">
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Sembol ara (örn. BTC)…"
              className="input w-56"
              aria-label="Sembol ara"
            />
            <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
              <input type="checkbox" checked={onlyGreen} onChange={(event) => setOnlyGreen(event.target.checked)} className="accent-neon-green" />
              Sadece {tfs.length}/{tfs.length} yeşil
            </label>
            <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
              <input type="checkbox" checked={sortAlpha} onChange={(event) => setSortAlpha(event.target.checked)} className="accent-neon-green" />
              Alfabetik sırala
            </label>
            <button type="button" onClick={loadSnapshot} className="ui-button ui-button-secondary ml-auto">YENİLE</button>
          </div>

          {stale && (
            <p className="mt-3 rounded-lg border border-yellow-300/40 bg-yellow-300/5 px-3 py-2 font-mono text-xs text-yellow-300">
              Son veri 15 sn&apos;den eski — WS mesajları gelmiyor olabilir.
            </p>
          )}
          {error && (
            <p className="mt-3 rounded-lg border border-neon-red/40 bg-neon-red/5 px-3 py-2 font-mono text-xs text-neon-red">
              Veri alınamadı: {error}
            </p>
          )}

          <div className="mt-4 overflow-x-auto">
            {loading && !snapshot ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Veri bekleniyor… (ilk M3/M30 serileri ısınıyor)</p>
            ) : rows.length === 0 ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">
                {universeCount === 0 ? "Henüz aktif sembol yok. Activity taraması tamamlanınca liste dolar." : "Filtreye uyan sembol yok."}
              </p>
            ) : (
              <table className="w-full border-collapse font-mono text-sm">
                <thead>
                  <tr className="border-b border-bunker-800 text-left text-[11px] text-bunker-muted">
                    <th className="px-3 py-2">SEMBOL</th>
                    <th className="px-3 py-2 text-right">FİYAT</th>
                    {tfs.map((tf) => (
                      <th key={tf} className="px-3 py-2 text-center">{TF_LABELS[tf]}</th>
                    ))}
                    <th className="px-3 py-2 text-center" title={`${tfs.length} zaman diliminde yeşil sayısı`}>YEŞİL</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.symbol} className="border-b border-bunker-800/60 transition-colors hover:bg-bunker-800/40">
                      <td className="px-3 py-2">
                        <SymbolLink symbol={row.symbol} className="font-bold text-white hover:text-neon-green" />
                      </td>
                      <td className="px-3 py-2 text-right text-bunker-muted">{fmtPrice(row.last)}</td>
                      {tfs.map((tf) => {
                        const cell = row.tfsMap[tf];
                        return (
                          <td key={tf} className="px-3 py-2 text-center">
                            {cell ? (
                              <span
                                title={`histogram: ${histShort(cell.hist)}`}
                                className={`inline-flex min-w-[2.25rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${
                                  cell.green
                                    ? "border-neon-green/40 bg-neon-green/10 text-neon-green"
                                    : "border-neon-red/40 bg-neon-red/10 text-neon-red"
                                }`}
                              >
                                {cell.green ? "▲" : "▼"}
                              </span>
                            ) : (
                              <span className="text-bunker-muted/60" title="Yetersiz mum verisi">—</span>
                            )}
                          </td>
                        );
                      })}
                      <td className="px-3 py-2 text-center">
                        <span
                          className={`inline-flex min-w-[2.25rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${
                            row.greenCount === tfs.length && tfs.length > 0
                              ? "border-neon-green/50 bg-neon-green/15 text-neon-green"
                              : row.greenCount === 0
                                ? "border-neon-red/50 bg-neon-red/15 text-neon-red"
                                : "border-bunker-600 bg-bunker-900 text-white"
                          }`}
                        >
                          {tfs.length > 0 ? `${row.greenCount}/${tfs.length}` : "—"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <p className="mt-3 font-mono text-[10px] text-bunker-muted/70">
            Hesaplama: kapanmış mum serisine canlı fiyat eklenerek MACD (12, 26, 9). M3/M30 serileri REST ile aralıklı tazelenir.
          </p>
        </div>
      </main>
    </RequireAdmin>
  );
}
