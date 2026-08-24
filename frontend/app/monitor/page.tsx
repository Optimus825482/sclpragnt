"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import GainerRadar from "../components/GainerRadar";
import { API_BASE, apiRequest } from "../lib/api";

const PumpMonitorPanel = dynamic(
  () => import("../pump-monitor/page").then((module) => module.PumpMonitorPanel),
  { loading: () => <div className="card animate-pulse text-bunker-muted">Pump Monitor yükleniyor…</div> },
);

export default function MonitorPage() {
  const [tab, setTab] = useState<"radar" | "pump" | "fisher">(() =>
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "pump" ? "pump" : "radar",
  );
  return <main className="mx-auto max-w-7xl space-y-6">
    <header>
      <p className="eyebrow">CANLI FIRSAT İZLEME</p>
      <h1 className="font-mono text-xl font-bold tracking-tight">MARKET <span className="text-neon-green">MONITOR</span></h1>
      <p className="mt-1 text-sm text-bunker-muted">Radar sıralaması ile M5/M15 Pump adayları tek çalışma alanında.</p>
    </header>
    <nav className="section-tabs" aria-label="Monitor sekmeleri">
      <button className={tab === "radar" ? "active" : ""} onClick={() => setTab("radar")}>🎯 Gainer Radar</button>
      <button className={tab === "pump" ? "active" : ""} onClick={() => setTab("pump")}>🚀 Pump Monitor</button>
      <button className={tab === "fisher" ? "active" : ""} onClick={() => setTab("fisher")}>〽️ Fisher + Kernel</button>
    </nav>
    {tab === "radar" ? <section className="space-y-4"><GainerRadar /><div className="card bg-bunker-950 text-sm text-bunker-muted">Radar sıralama ve gözlem içindir; otomatik paper pozisyon açmaz.</div></section> : tab === "pump" ? <PumpMonitorPanel /> : <FisherKernelPanel />}
  </main>;
}

type FisherItem = { symbol: string; price?: number; state: string; reason: string; ready: boolean; fisher?: number; trigger?: number; fisher_cross_up?: boolean; fisher_cross_down?: boolean; fisher_entry_zone?: boolean; kernel_green?: boolean; kernel_rq?: number; kernel_gaussian?: number; m3_candles?: number; m5_candles?: number };
type FisherMonitor = { enabled: boolean; active_symbols: number; updated_at?: number; items: FisherItem[] };
const number = (value?: number, digits = 4) => value == null ? "—" : value.toLocaleString("tr-TR", { maximumFractionDigits: digits });

function FisherKernelPanel() {
  const [data, setData] = useState<FisherMonitor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const response = await apiRequest(`${API_BASE}/api/research/fisher-m3-kernel-m5-monitor`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setData(await response.json()); setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Fisher verisi alınamadı"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); const id = window.setInterval(load, 5_000); return () => window.clearInterval(id); }, [load]);
  const items = data?.items || [];
  const stateTone = (state: string) => state === "LONG_READY" ? "text-neon-green" : state === "EXIT_READY" ? "text-sky-300" : state === "KERNEL_RED" ? "text-neon-red" : state === "WARMING" ? "text-yellow-300" : "text-bunker-muted";
  return <section className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">FISHER M3 + KERNEL M5 · EXACT PAPER</p><h2 className="font-mono text-lg font-bold">SİNYAL <span className="text-neon-green">KAPI MONİTÖRÜ</span></h2><p className="mt-1 text-sm text-bunker-muted">Aktif sembollerde her kapalı M1 ile yenilenir. Görüntüleme yapar; bu ekran emir vermez.</p></div><button className="ui-button secondary" onClick={load} disabled={loading}>{loading ? "YÜKLENİYOR" : "YENİLE"}</button></div>
    {error && <div className="card border-neon-red/30 text-neon-red">{error}</div>}
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><MonitorMetric label="AKTİF SEMBOL" value={String(data?.active_symbols ?? 0)} /><MonitorMetric label="LONG HAZIR" value={String(items.filter((item) => item.state === "LONG_READY").length)} tone="text-neon-green" /><MonitorMetric label="KERNEL KIRMIZI" value={String(items.filter((item) => item.state === "KERNEL_RED").length)} tone="text-neon-red" /><MonitorMetric label="SON GÜNCELLEME" value={data?.updated_at ? new Date(data.updated_at * 1000).toLocaleTimeString("tr-TR") : "—"} /></div>
    <div className="card overflow-hidden p-0"><div className="border-b border-bunker-800 px-4 py-3"><p className="eyebrow">ANLIK KURAL DURUMU</p><p className="mt-1 text-xs text-bunker-muted">Örnek: “Fisher kesişimi var · Kernel kırmızı” durumu burada doğrudan görülür.</p></div><div className="overflow-x-auto"><table className="data-table min-w-[920px]"><thead><tr><th>SEMBOL</th><th>FİSHER M3</th><th>GİRİŞ EŞİĞİ</th><th>KERNEL M5</th><th>FİYAT</th><th>DURUM</th></tr></thead><tbody>{items.map((item) => <tr key={item.symbol}><td className="font-bold text-white">{item.symbol}</td><td><span className={item.fisher_cross_up ? "text-neon-green" : item.fisher_cross_down ? "text-sky-300" : "text-white"}>{number(item.fisher)} {item.fisher_cross_up ? "↑ KESİŞİM" : item.fisher_cross_down ? "↓ KESİŞİM" : ""}</span><div className="mt-1 text-[10px] text-bunker-muted">Tetik {number(item.trigger)}</div></td><td className={item.fisher_entry_zone ? "text-neon-green" : "text-bunker-muted"}>{item.ready ? item.fisher_entry_zone ? "✓ -1 altında" : "— -1 altında değil" : `${item.m3_candles || 0}/12 mum`}</td><td className={item.kernel_green ? "text-neon-green" : item.ready ? "text-neon-red" : "text-yellow-300"}>{item.ready ? item.kernel_green ? "● YEŞİL" : "● KIRMIZI" : `${item.m5_candles || 0}/34 mum`}<div className="mt-1 text-[10px] text-bunker-muted">G {number(item.kernel_gaussian)} · RQ {number(item.kernel_rq)}</div></td><td>₺{number(item.price, 6)}</td><td><p className={`font-mono text-xs font-bold ${stateTone(item.state)}`}>{item.state.replaceAll("_", " ")}</p><p className="mt-1 max-w-sm text-[11px] text-bunker-muted">{item.reason}</p></td></tr>)}</tbody></table></div>{!loading && !items.length && <p className="p-6 text-center text-bunker-muted">Aktif sembol bulunamadı veya aktivite taraması bekleniyor.</p>}</div>
    <p className="text-xs text-bunker-muted">Kural sabit: M3 Fisher(11) yukarı kesişim + Fisher &lt; -1 + M5 Kernel yeşil. Çıkış: M3 aşağı kesişim + Fisher &gt; 2. Paper yürütmesi varsa sonraki kapalı M1 açılışını kullanır.</p>
  </section>;
}

function MonitorMetric({ label, value, tone = "text-white" }: { label: string; value: string; tone?: string }) { return <div className="card !p-4"><p className="eyebrow">{label}</p><p className={`mt-2 font-mono text-lg font-bold ${tone}`}>{value}</p></div>; }
