"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";

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
  useEffect(() => { load(); }, [load]);
  useVisibleInterval(load, 10_000);

  const healthy = data?.status === "ok" && liveStatus === "open";
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-bunker-800 pb-4">
        <div>
          <h1 className="font-mono text-xl sm:text-2xl font-bold tracking-tight">
            <span className="text-neon-green">SİSTEM</span> SAĞLIĞI
          </h1>
          <p className="eyebrow mt-1">Market data · WebSocket · Veritabanı · LLM</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-lg border px-3 py-1.5 font-mono text-xs font-bold flex items-center gap-1.5 ${
              healthy
                ? "border-neon-green/40 bg-neon-green/10 text-neon-green"
                : "border-yellow-300/40 bg-yellow-300/10 text-yellow-300"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                healthy ? "bg-neon-green animate-pulse" : "bg-yellow-300"
              }`}
            />
            {healthy ? "SİSTEM SAĞLIKLI" : "KISMİ / BEKLEMEDE"}
          </span>
          <button
            type="button"
            onClick={load}
            className="ui-button ui-button-secondary touch-target"
            title="Verileri yenile"
          >
            🔄 Yenile
          </button>
        </div>
      </header>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/5 p-4 text-neon-red font-mono text-sm">
          ⚠ {error}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {[
          ["Backend", data?.status ? String(data.status).toUpperCase() : "—"],
          ["Canlı Kanal (WS)", liveStatus === "open" ? "BAĞLI" : liveStatus.toUpperCase()],
          ["İzlenen Sembol", data?.market?.symbols ?? "—"],
          ["WS İstemcileri", data?.websocket_clients ?? "—"],
        ].map(([label, value]) => {
          const isStatusCard = label.includes("Backend") || label.includes("Canlı");
          return (
            <div className="card p-4 sm:p-5" key={label}>
              <p className="eyebrow">{label}</p>
              <p
                className={`font-mono text-xl sm:text-2xl font-bold mt-2 ${
                  isStatusCard ? (healthy ? "text-neon-green" : "text-yellow-300") : "text-white"
                }`}
              >
                {value}
              </p>
            </div>
          );
        })}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-2">
            <p className="eyebrow text-neon-green">MARKET DATA SERVİSİ</p>
            <span className="font-mono text-[10px] text-bunker-muted">Binance Public Feed</span>
          </div>
          <div className="space-y-2 font-mono text-sm">
            <div className="flex justify-between items-center py-1 border-b border-bunker-800/40">
              <span className="text-bunker-muted text-xs">Aktif Ticker Sayısı:</span>
              <span className="text-white font-bold">{data?.market?.tickers ?? "—"}</span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-bunker-800/40">
              <span className="text-bunker-muted text-xs">Maksimum Ticker Yaşı:</span>
              <span className="text-white">
                {data?.market?.max_ticker_age_sec == null
                  ? "—"
                  : `${data.market.max_ticker_age_sec.toFixed(1)} sn`}
              </span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-bunker-muted text-xs">Aktif Zaman Dilimleri:</span>
              <span className="text-neon-green text-xs font-bold">
                {data?.market?.timeframes?.join(", ") || "—"}
              </span>
            </div>
          </div>
        </div>

        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-2">
            <p className="eyebrow text-cyan-400">ALTYAPI & RİSK KORUMASI</p>
            <span className="font-mono text-[10px] text-bunker-muted">PostgreSQL · Risk Gate</span>
          </div>
          <div className="space-y-2 font-mono text-sm">
            <div className="flex justify-between items-center py-1 border-b border-bunker-800/40">
              <span className="text-bunker-muted text-xs">Veritabanı Durumu:</span>
              <span className={`font-bold ${data?.database?.status === "ok" ? "text-neon-green" : "text-yellow-300"}`}>
                {data?.database?.status ? String(data.database.status).toUpperCase() : "—"}
              </span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-bunker-800/40">
              <span className="text-bunker-muted text-xs">Açık Pozisyon / Limit:</span>
              <span className="text-white">
                {data?.portfolio?.open_positions ?? "0"} / {data?.portfolio?.max_open_positions ?? "—"}
              </span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-bunker-muted text-xs">LLM Motoru:</span>
              <span className={`text-xs font-bold ${data?.llm?.active ? "text-neon-green" : "text-bunker-muted"}`}>
                {data?.llm?.active ? "AKTİF & BAĞLI" : "PASİF / AYARLANMAMIŞ"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
