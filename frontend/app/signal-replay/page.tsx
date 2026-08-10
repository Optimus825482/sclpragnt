"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { Card, SectionHeader } from "../components/ui";
import SymbolLink from "../components/SymbolLink";

type LogItem = { level: string; message: string };
type ReplayResult = { symbol: string; candle_number: number; timestamp: number; close: number; action: "BUY_SIGNAL" | "NO_SIGNAL" | "WARMUP" };
type Job = {
  job_id: string; status: string; strategy: string; timeframe: string; candle_count: number;
  completed: number; total: number; logs: LogItem[]; results: ReplayResult[]; error?: string;
};

async function responseError(response: Response, fallback: string) {
  const body = await response.text();
  try {
    const data = JSON.parse(body);
    return data.detail || data.error || fallback;
  } catch {
    return body || fallback;
  }
}

export default function SignalReplayPage() {
  const [candleCount, setCandleCount] = useState(6);
  const [job, setJob] = useState<Job | null>(null);
  const [starting, setStarting] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [job?.logs.length]);

  const start = async () => {
    setStarting(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/strategy/replay`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candle_count: candleCount }),
      });
      if (!response.ok) throw new Error(await responseError(response, "Denetim başlatılamadı"));
      const data = await response.json();
      if (!data.ok) throw new Error(data.detail || data.error || "Denetim başlatılamadı");
      setJob({ ...data, logs: [], results: [], completed: 0, total: 0 });
    } catch (error) {
      setJob({ job_id: "error", status: "error", strategy: "—", timeframe: "5m", candle_count: candleCount, completed: 0, total: 0, results: [], logs: [{ level: "error", message: error instanceof Error ? error.message : "Denetim başlatılamadı" }] });
    } finally { setStarting(false); }
  };

  useEffect(() => {
    if (!job?.job_id || job.status === "completed" || job.status === "error" || job.job_id === "error") return;
    const timer = window.setInterval(async () => {
      try {
        const response = await apiRequest(`${API_BASE}/api/strategy/replay/${job.job_id}`, { cache: "no-store" });
        if (response.ok) setJob(await response.json());
      } catch { /* Polling resumes on the next interval; the previous results remain visible. */ }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const progress = job?.total ? Math.round((job.completed / job.total) * 100) : 0;
  const orderedResults = useMemo(() => [...(job?.results || [])].sort((a, b) => b.timestamp - a.timestamp || a.symbol.localeCompare(b.symbol)), [job?.results]);
  const buySignals = orderedResults.filter(item => item.action === "BUY_SIGNAL").length;
  const statusLabel = job?.status === "running" ? "Çalışıyor" : job?.status === "completed" ? "Tamamlandı" : job?.status === "error" ? "Hata" : "Hazır";

  return <main className="mx-auto max-w-7xl space-y-6">
    <SectionHeader eyebrow="PAPER · SALT OKUNUR" title="Sinyal Denetimi" description="Aktif tüm sembollerde seçtiğiniz sayıdaki en son kapanmış 5 dakikalık mumu mevcut stratejiyle denetler. Pozisyon, bakiye ve strateji durumu değiştirilmez." actions={<div className="flex items-center gap-2"><label className="sr-only" htmlFor="replay-candle-count">Kapanmış M5 mum sayısı</label><select id="replay-candle-count" value={candleCount} onChange={event => setCandleCount(Number(event.target.value))} disabled={starting || job?.status === "running"} className="rounded border border-bunker-700 bg-bunker-950 px-2 py-2 font-mono text-xs text-white">{Array.from({ length: 20 }, (_, index) => index + 1).map(count => <option key={count} value={count}>{count} mum</option>)}</select><button onClick={start} disabled={starting || job?.status === "running"} className="ui-button ui-button-primary">{starting || job?.status === "running" ? "⟳ ÇALIŞIYOR…" : "▶ DENETLE"}</button></div>} />
    <div className="grid gap-4 md:grid-cols-4"><Card><p className="eyebrow">STRATEJİ</p><p className="mt-2 font-mono text-sm text-neon-green">{job?.strategy || "Mevcut aktif strateji"}</p></Card><Card><p className="eyebrow">KAPANMIŞ M5 MUM</p><p className="mt-2 font-mono text-sm text-white">{job?.candle_count || candleCount} adet</p></Card><Card><p className="eyebrow">BUY SİNYALİ</p><p className="mt-2 font-mono text-sm text-neon-green">{buySignals}</p></Card><Card><p className="eyebrow">DURUM</p><p className="mt-2 font-mono text-sm text-white">{statusLabel}{job?.total ? ` · ${progress}%` : ""}</p></Card></div>
    <Card><div className="mb-3 flex items-center justify-between gap-3"><div><p className="eyebrow">MUM BAZLI SONUÇLAR</p><h2 className="font-mono text-lg font-bold text-white">Aktif sembol denetimi</h2></div><span className="font-mono text-xs text-bunker-muted">{job?.completed || 0}/{job?.total || 0}</span></div><div className="h-1.5 overflow-hidden rounded bg-bunker-800"><div className="h-full bg-neon-green transition-all" style={{ width: `${progress}%` }} /></div><div className="table-scroll mt-4"><table className="data-table"><thead><tr><th>Kapanış</th><th>Sembol</th><th>Mum</th><th>Fiyat</th><th>Sonuç</th></tr></thead><tbody>{orderedResults.length ? orderedResults.map((item, index) => <tr key={`${item.symbol}-${item.timestamp}-${index}`}><td>{new Date(item.timestamp * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td><td><SymbolLink symbol={item.symbol} className="text-white hover:text-neon-green" /></td><td>#{item.candle_number}</td><td>{item.close.toLocaleString("tr-TR", { maximumFractionDigits: 8 })}</td><td className={item.action === "BUY_SIGNAL" ? "text-neon-green" : item.action === "WARMUP" ? "text-yellow-300" : "text-bunker-muted"}>{item.action}</td></tr>) : <tr><td colSpan={5} className="py-10 text-center text-bunker-muted">Denetle düğmesine basınca sonuçlar burada görünür.</td></tr>}</tbody></table></div></Card>
    <Card><p className="eyebrow">DENETİM GÜNLÜĞÜ</p><div ref={logRef} className="signal-replay-log mt-3 max-h-64 overflow-y-auto rounded-lg border border-bunker-800 bg-black/30 p-3 font-mono text-xs">{!job?.logs.length ? <p className="py-6 text-center text-bunker-muted">Bekleniyor.</p> : job.logs.map((item, index) => <p key={`${index}-${item.message}`} className={`border-b border-bunker-900 py-1.5 ${item.level === "error" ? "text-red-300" : item.level === "success" ? "text-cyan-300" : "text-bunker-muted"}`}>{item.message}</p>)}</div></Card>
  </main>;
}
