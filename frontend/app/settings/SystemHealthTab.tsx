"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";

export default function SystemHealthTab() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const liveStatus = useLiveStatus();
  const load = useCallback(() => apiFetch("/api/system/health")
    .then((result) => { setData(result); setError(""); })
    .catch(() => setError("Sağlık verisi alınamadı")), []);

  useLiveMessages(useCallback((message: any) => {
    if (["reset", "trade_updated"].includes(message.type)) load();
  }, [load]));

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  const healthy = data?.status === "ok" && liveStatus === "open";
  return <section aria-label="Sistem sağlığı" className="space-y-4">
    <div>
      <p className="eyebrow text-neon-green">SİSTEM SAĞLIĞI</p>
      <p className="mt-1 text-xs text-bunker-muted">Market data · WebSocket · veritabanı · LLM. 10 saniyede bir yenilenir.</p>
    </div>
    {error && <div className="card border-neon-red/40 bg-neon-red/5 text-neon-red">{error}</div>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[["Backend", data?.status || "—"], ["Canlı kanal", liveStatus === "open" ? "bağlı" : liveStatus], ["Semboller", data?.market?.symbols], ["WS istemcileri", data?.websocket_clients]].map(([label, value]) => <div className="card" key={label}><p className="eyebrow">{label}</p><p className={`mt-2 font-mono text-2xl ${label === "Backend" || label === "Canlı kanal" ? healthy ? "text-neon-green" : "text-yellow-300" : "text-white"}`}>{value ?? "—"}</p></div>)}
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      <div className="card"><p className="eyebrow">MARKET DATA</p><p className="mt-3 font-mono text-sm">Ticker: {data?.market?.tickers ?? "—"}</p><p className="mt-2 font-mono text-sm">Max ticker yaşı: {data?.market?.max_ticker_age_sec == null ? "—" : `${data.market.max_ticker_age_sec.toFixed(1)} sn`}</p><p className="mt-2 font-mono text-sm">Timeframe: {data?.market?.timeframes?.join(", ") || "—"}</p></div>
      <div className="card"><p className="eyebrow">ALTYAPI / RİSK</p><p className="mt-3 font-mono text-sm">DB: {data?.database?.status || "—"}</p><p className="mt-2 font-mono text-sm">Açık pozisyon: {data?.portfolio?.open_positions ?? "—"} / {data?.portfolio?.max_open_positions ?? "—"}</p><p className="mt-2 font-mono text-sm">LLM: {data?.llm?.active ? "aktif" : "pasif veya yapılandırılmamış"}</p></div>
    </div>
  </section>;
}
