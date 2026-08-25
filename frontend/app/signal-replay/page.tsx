"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type ReplayResult = {
  symbol: string;
  action?: string;
  decision?: string;
  reason?: string;
  price?: number;
  timeframe?: string;
  [key: string]: unknown;
};

type ReplayJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  strategy: string;
  timeframe: string;
  candle_count: number;
  completed: number;
  total: number;
  results: ReplayResult[];
  logs: string[];
  error?: string;
  started_at?: number;
};

const CANDLE_COUNTS = [1, 2, 3, 5, 10, 20];

export default function SignalReplayPage() {
  const [job, setJob] = useState<ReplayJob | null>(null);
  const [candleCount, setCandleCount] = useState(6);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const start = useCallback(async () => {
    setStarting(true);
    setError("");
    setJob(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/strategy/replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candle_count: candleCount }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setJob({
        job_id: data.job_id,
        status: data.status || "queued",
        strategy: data.strategy ?? "",
        timeframe: data.timeframe ?? "5m",
        candle_count: candleCount,
        completed: 0,
        total: 0,
        results: [],
        logs: [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay başlatılamadı");
    } finally {
      setStarting(false);
    }
  }, [candleCount]);

  // Poll until the read-only replay job reaches a terminal state.
  useEffect(() => {
    if (!job || ["completed", "failed"].includes(job.status)) return;
    let cancelled = false;
    pollRef.current = setTimeout(async () => {
      try {
        const response = await apiRequest(`${API_BASE}/api/strategy/replay/${job.job_id}`, { cache: "no-store" });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data) throw new Error(data?.detail || `HTTP ${response.status}`);
        if (!cancelled) setJob((current) => ({ ...(current as ReplayJob), ...data }));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Replay durumu alınamadı");
      }
    }, 1_500);
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [job]);

  const running = !!job && !["completed", "failed"].includes(job.status);
  const progress = job && job.total > 0 ? Math.round((job.completed / job.total) * 100) : running ? 10 : 0;

  return (
    <main className="page-shell space-y-5">
      <header className="page-heading">
        <p className="eyebrow">SALT OKUNUR · PAPER</p>
        <h1 className="font-mono text-xl font-bold tracking-tight">SİNYAL <span className="text-neon-green">REPLAY</span></h1>
        <p className="mt-1 text-sm text-bunker-muted">
          Aktif stratejinin son kapalı 5m mumlardaki kararlarını yeniden üretir. Pozisyon açmaz, cüzdana dokunmaz.
        </p>
      </header>

      <section className="card space-y-4">
        <div className="flex flex-wrap items-end gap-4">
          <label className="space-y-1 text-xs text-bunker-muted">
            <span className="eyebrow block">GERİYE DÖNÜK MUM SAYISI</span>
            <select
              className="input w-40"
              value={candleCount}
              onChange={(event) => setCandleCount(Number(event.target.value))}
              disabled={running}
            >
              {CANDLE_COUNTS.map((count) => (
                <option key={count} value={count}>{count} mum</option>
              ))}
            </select>
          </label>
          <button type="button" className="ui-button primary" onClick={start} disabled={starting || running}>
            {running ? "REPLAY ÇALIŞIYOR…" : starting ? "BAŞLATILIYOR…" : "▶ REPLAY BAŞLAT"}
          </button>
          <p className="text-xs text-bunker-muted">
            Aktif strateji: <span className="font-mono text-white">{job?.strategy || "BB_MFI_MEAN_REVERSION"}</span> · TF{" "}
            <span className="font-mono text-white">{job?.timeframe || "5m"}</span>
          </p>
        </div>

        {error && <div className="card border-neon-red/30 text-neon-red text-sm">{error}</div>}

        {job && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs font-mono text-bunker-muted">
              <span>DURUM: <span className={job.status === "failed" ? "text-neon-red" : job.status === "completed" ? "text-neon-green" : "text-neon-yellow"}>{job.status.toUpperCase()}</span></span>
              <span>{job.completed}/{job.total || "?"} sembol</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded bg-bunker-800">
              <div className="h-full bg-neon-green transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}
      </section>

      {job?.results?.length ? (
        <section className="card overflow-hidden p-0 signal-replay-log">
          <div className="border-b border-bunker-800 px-4 py-3">
            <p className="eyebrow">KARAR SONUÇLARI</p>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table min-w-[720px]">
              <thead>
                <tr><th>Sembol</th><th>Karar</th><th>Fiyat</th><th>Gerekçe</th></tr>
              </thead>
              <tbody>
                {job.results.map((row, index) => {
                  const action = String(row.action ?? row.decision ?? "—").toUpperCase();
                  return (
                    <tr key={`${row.symbol}-${index}`}>
                      <td className="font-bold"><SymbolLink symbol={row.symbol} className="text-white hover:text-neon-green" /></td>
                      <td className={`font-mono font-bold ${action.includes("BUY_SIGNAL") ? "text-neon-green" : action === "BUY_BLOCKED" ? "text-sky-300" : "text-bunker-muted"}`}>{action}</td>
                      <td className="font-mono">{typeof row.price === "number" && Number.isFinite(row.price) ? `₺${row.price.toLocaleString("tr-TR")}` : "—"}</td>
                      <td className="max-w-md truncate text-bunker-muted" title={row.reason}>{row.reason ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        job && !running && !error && (
          <section className="card text-sm text-bunker-muted">Bu replay için karar kaydı üretilmedi.</section>
        )
      )}

      <p className="text-xs text-bunker-muted">
        Replay yalnızca kapanmış public mumlarla çalışır; sonuçlar gözlemseldir ve işlem kararı değildir.
        Canlı sinyal akışı için <Link href="/" className="text-sky-300 hover:text-white">ana terminali</Link> kullanın.
      </p>
    </main>
  );
}
