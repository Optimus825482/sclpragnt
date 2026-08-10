"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";

export default function SystemHealth() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const liveStatus = useLiveStatus();
  const load = useCallback(() => apiFetch("/api/system/health")
    .then((result) => { setData(result); setError(""); })
    .catch(() => setError("Sağlık verisi alınamadı")), []);
  const onLiveMessage = useCallback((message: any) => {
    if (["reset", "trade_updated"].includes(message.type)) load();
  }, [load]);
  useLiveMessages(onLiveMessage);
  useEffect(() => { load(); const id = window.setInterval(load, 10_000); return () => window.clearInterval(id); }, [load]);

  const healthy = data?.status === "ok" && liveStatus === "open";
  return <div className="max-w-6xl mx-auto space-y-6">
    <header><h1 className="font-mono text-xl font-bold"><span className="text-neon-green">SİSTEM</span> SAĞLIĞI</h1><p className="eyebrow mt-1">Market data · WebSocket · veritabanı · LLM</p></header>
    {error && <div className="card text-neon-red">{error}</div>}
    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {[["Backend", data?.status || "—"], ["Canlı kanal", liveStatus === "open" ? "bağlı" : liveStatus], ["Semboller", data?.market?.symbols], ["WS istemcileri", data?.websocket_clients]].map(([label, value]) => <div className="card" key={label}><p className="eyebrow">{label}</p><p className={`font-mono text-2xl mt-2 ${label === "Backend" || label === "Canlı kanal" ? healthy ? "text-neon-green" : "text-yellow-300" : "text-white"}`}>{value ?? "—"}</p></div>)}
    </div>
    <div className="grid md:grid-cols-2 gap-4">
      <div className="card"><p className="eyebrow">MARKET DATA</p><p className="font-mono text-sm mt-3">Ticker: {data?.market?.tickers ?? "—"}</p><p className="font-mono text-sm mt-2">Max ticker yaşı: {data?.market?.max_ticker_age_sec == null ? "—" : `${data.market.max_ticker_age_sec.toFixed(1)} sn`}</p><p className="font-mono text-sm mt-2">Timeframe: {data?.market?.timeframes?.join(", ") || "—"}</p></div>
      <div className="card"><p className="eyebrow">ALTYAPI / RİSK</p><p className="font-mono text-sm mt-3">DB: {data?.database?.status || "—"}</p><p className="font-mono text-sm mt-2">Açık pozisyon: {data?.portfolio?.open_positions ?? "—"} / {data?.portfolio?.max_open_positions ?? "—"}</p><p className="font-mono text-sm mt-2">LLM: {data?.llm?.active ? "aktif" : "pasif veya yapılandırılmamış"}</p></div>
    </div>
  </div>;
}
