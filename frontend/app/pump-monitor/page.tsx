"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type Candidate = {
  symbol: string; price?: number; status: string; eligible?: boolean; high_confidence?: boolean;
  score?: number; bb_position?: number; mfi_14?: number; rsi_14?: number; volume_ratio_20?: number;
  m15_alignment?: string; m30_alignment?: string; has_open_position?: boolean; reason?: string;
  checks?: Record<string, boolean>;
};
type Signal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number };
type Monitor = { items: Candidate[]; history: Signal[]; generated_at?: number; paper_trades?: unknown[]; config?: Record<string, unknown> };

const price = (value?: number) => value == null ? "—" : `₺${value.toLocaleString("tr-TR", { maximumFractionDigits: 6 })}`;
const time = (value?: number) => value ? new Date(value * 1000).toLocaleString("tr-TR") : "—";

export default function PumpMonitorPage() {
  const [data, setData] = useState<Monitor | null>(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const response = await apiRequest(`${API_BASE}/api/pump-monitor`);
      if (!response.ok) throw new Error("Pump Monitor verisi alınamadı");
      setData(await response.json()); setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Bağlantı hatası"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); const id = window.setInterval(load, 30_000); return () => window.clearInterval(id); }, [load]);
  const execute = async () => {
    setExecuting(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/pump-monitor/scan`, { method: "POST" });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Paper tarama çalıştırılamadı");
      setData(await response.json()); setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Tarama hatası"); }
    finally { setExecuting(false); }
  };
  const candidates = data?.items || [];
  return <div className="mx-auto max-w-7xl space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="font-mono text-xl font-bold tracking-tight">PUMP <span className="text-neon-green">MONITOR</span></h1>
        <p className="eyebrow mt-1">M5 erken teşhis · M15/M30 bağlam · yalnızca paper portföy</p></div>
      <button className="ui-button ui-button-primary" onClick={execute} disabled={executing}>{executing ? "TARANIYOR…" : "PAPER TARAMA ÇALIŞTIR"}</button>
    </header>
    {error && <p className="rounded-lg border border-red-500/50 bg-red-500/10 p-3 font-mono text-sm text-red-300">{error}</p>}
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Metric label="UYGUN ADAY" value={String(candidates.filter((item) => item.eligible).length)} tone="text-neon-green" />
      <Metric label="YÜKSEK GÜVEN" value={String(candidates.filter((item) => item.high_confidence).length)} tone="text-neon-green" />
      <Metric label="AÇIK PUMP" value={String(candidates.filter((item) => item.has_open_position).length)} />
      <Metric label="EŞİK" value={`Skor ≥${data?.config?.min_score ?? 3}`} />
      <Metric label="SON GÜNCELLEME" value={data?.generated_at ? new Date(data.generated_at * 1000).toLocaleTimeString("tr-TR") : "—"} />
    </section>
    <section className="card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-bunker-800 px-4 py-3"><div><p className="eyebrow">AÇILIŞ ADAYLARI</p><p className="text-xs text-bunker-muted">BB üst bant genişlemesi, MFI/RSI ve M15 doğrulaması aynı kapıda değerlendirilir.</p></div><span className="font-mono text-xs text-bunker-muted">{loading ? "YÜKLENİYOR" : `${candidates.length} SEMBOL`}</span></div>
      <div className="overflow-x-auto"><table className="w-full text-left font-mono text-xs"><thead className="border-b border-bunker-800 text-bunker-muted"><tr><th className="px-4 py-3">SEMBOL</th><th>SKOR</th><th>M5</th><th>M15 / M30</th><th>HACİM</th><th>DURUM</th><th className="px-4">KONTROL</th></tr></thead><tbody>
        {candidates.map((item) => <tr key={item.symbol} className="border-b border-bunker-800/70 hover:bg-bunker-900/60"><td className="px-4 py-3"><Link className="font-bold text-white hover:text-neon-green" href={`/charts?symbol=${encodeURIComponent(item.symbol)}&timeframe=5m`}>{item.symbol}</Link><div className="mt-1 text-bunker-muted">{price(item.price)}</div></td><td className={item.eligible ? "font-bold text-neon-green" : "text-white"}>{item.score == null ? "—" : `${item.score}/4`}{item.high_confidence && <div className="mt-1 text-[10px] text-neon-green">YÜKSEK</div>}</td><td><div>BB {item.bb_position == null ? "—" : item.bb_position.toFixed(2)}</div><div className="text-bunker-muted">MFI {item.mfi_14?.toFixed(0) ?? "—"} · RSI {item.rsi_14?.toFixed(0) ?? "—"}</div></td><td><div className={item.m15_alignment === "bullish" ? "text-neon-green" : "text-bunker-muted"}>15m {item.m15_alignment ?? "—"}</div><div className={item.m30_alignment === "bullish" ? "text-neon-green" : "text-bunker-muted"}>30m {item.m30_alignment ?? "—"}</div></td><td>{item.volume_ratio_20 == null ? "—" : `${item.volume_ratio_20.toFixed(2)}x`}</td><td><span className={item.eligible ? "text-neon-green" : item.status === "WARMING" ? "text-yellow-300" : "text-bunker-muted"}>{item.has_open_position ? "PAPER AÇIK" : item.status}</span><div className="mt-1 max-w-[15rem] text-[10px] text-bunker-muted">{item.reason}</div></td><td className="px-4">{item.checks ? Object.entries(item.checks).map(([name, ok]) => <div key={name} className={ok ? "text-neon-green" : "text-bunker-muted"}>{ok ? "✓" : "–"} {name}</div>) : "—"}</td></tr>)}
      </tbody></table></div>
    </section>
    <section className="card"><div className="mb-3 flex items-center justify-between"><p className="eyebrow">SİNYAL GEÇMİŞİ</p><span className="text-xs text-bunker-muted">yalnızca Pump Monitor kayıtları</span></div><div className="space-y-2">{(data?.history || []).slice(0, 20).map((signal, index) => <div key={signal.id || `${signal.timestamp}-${index}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-bunker-800 bg-bunker-950/60 px-3 py-2 font-mono text-xs"><span className="text-bunker-muted">{time(signal.timestamp)}</span><Link href={`/charts?symbol=${encodeURIComponent(signal.symbol)}&timeframe=5m`} className="font-bold text-white hover:text-neon-green">{signal.symbol}</Link><span className={signal.action.includes("BUY") ? "text-neon-green" : "text-sky-300"}>{signal.action}</span><span className="text-bunker-muted">{signal.reason}</span></div>)}{!data?.history?.length && <p className="py-4 text-center text-sm text-bunker-muted">Henüz kaydedilmiş Pump Monitor sinyali yok.</p>}</div></section>
    <p className="text-xs text-bunker-muted">Araştırma kuralı: skor ≥3 ve M15 bullish. Hacim ≥1.0x yüksek güven etiketi verir; tüm açılışlar ortak likidite, bakiye ve yeniden-giriş kapılarından geçer.</p>
  </div>;
}

function Metric({ label, value, tone = "text-white" }: { label: string; value: string; tone?: string }) { return <div className="card !p-4"><p className="eyebrow">{label}</p><p className={`mt-2 font-mono text-lg font-bold ${tone}`}>{value}</p></div>; }
