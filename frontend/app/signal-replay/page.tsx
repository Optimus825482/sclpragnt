"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { Card, SectionHeader } from "../components/ui";
import SymbolLink from "../components/SymbolLink";

type LogItem = { level: string; message: string; symbol?: string; timestamp?: number };
type Job = { job_id: string; status: string; strategy: string; timeframe: string; minutes: number; completed: number; total: number; logs: LogItem[]; error?: string };

export default function SignalReplayPage() {
  const [job, setJob] = useState<Job | null>(null);
  const [starting, setStarting] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [job?.logs.length]);

  const start = async () => {
    setStarting(true);
    try {
      const response = await fetch(`${API_BASE}/api/strategy/replay`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes: 30 }) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || data.error || "Replay başlatılamadı");
      setJob({ ...data, logs: [], completed: 0, total: 0 });
    } catch (error) {
      setJob({ job_id: "error", status: "error", strategy: "—", timeframe: "5m", minutes: 30, completed: 0, total: 0, logs: [{ level: "error", message: error instanceof Error ? error.message : "Replay başlatılamadı" }] });
    } finally { setStarting(false); }
  };

  useEffect(() => {
    if (!job?.job_id || job.status === "completed" || job.status === "error" || job.job_id === "error") return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`${API_BASE}/api/strategy/replay/${job.job_id}`, { cache: "no-store" });
      if (response.ok) setJob(await response.json());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const progress = job?.total ? Math.round((job.completed / job.total) * 100) : 0;
  return <div className="mx-auto max-w-7xl space-y-6">
    <SectionHeader eyebrow="PAPER · SALT OKUNUR" title="Sinyal Denetimi" description="Aktif stratejiyi son 30 dakikanın 5 dakikalık kesitlerinde geriye dönük çalıştırır. Pozisyon açmaz, bakiyeyi değiştirmez." actions={<button onClick={start} disabled={starting || job?.status === "running"} className="ui-button ui-button-primary">{starting || job?.status === "running" ? "⟳ ÇALIŞIYOR…" : "▶ BAŞLAT"}</button>} />
    <div className="grid gap-4 md:grid-cols-3"><Card><p className="eyebrow">STRATEJİ</p><p className="mt-2 font-mono text-sm text-neon-green">{job?.strategy || "Mevcut aktif strateji"}</p></Card><Card><p className="eyebrow">PENCERE</p><p className="mt-2 font-mono text-sm text-white">30 dakika · 5m</p></Card><Card><p className="eyebrow">DURUM</p><p className="mt-2 font-mono text-sm text-white">{job?.status || "Hazır"}{job?.total ? ` · ${progress}%` : ""}</p></Card></div>
    <Card><div className="mb-3 flex items-center justify-between gap-3"><div className="min-w-0"><p className="eyebrow">CANLI DENETİM GÜNLÜĞÜ</p><h2 className="font-mono text-lg font-bold text-white">Sinyal kontrol akışı</h2></div><span className="shrink-0 font-mono text-xs text-bunker-muted">{job?.completed || 0}/{job?.total || 0}</span></div><div className="h-1.5 overflow-hidden rounded bg-bunker-800"><div className="h-full bg-neon-green transition-all" style={{ width: `${progress}%` }} /></div><div ref={logRef} className="signal-replay-log mt-4 h-[55vh] overflow-y-auto rounded-lg border border-bunker-800 bg-black/30 p-3 font-mono text-xs">{!job?.logs?.length ? <p className="py-10 text-center text-bunker-muted">Başlat düğmesine basınca 30 dakikalık replay günlüğü burada görünecek.</p> : job.logs.map((item, index) => <div key={`${index}-${item.message}`} className={`border-b border-bunker-900 py-1.5 ${item.level === "signal" ? "text-neon-green" : item.level === "error" ? "text-red-300" : item.level === "success" ? "text-cyan-300" : "text-bunker-muted"}`}><span className="mr-2 text-bunker-600">[{String(index + 1).padStart(3, "0")}]</span>{item.symbol && <><SymbolLink symbol={item.symbol} className="mr-2 text-current hover:text-white" />· </>}{item.message}</div>)}</div></Card>
  </div>;
}
