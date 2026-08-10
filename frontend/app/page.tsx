"use client";

import { useState } from "react";
import { API_BASE, apiRequest } from "./lib/api";
import LiveTerminal from "./components/LiveTerminal";
import StrategyCards from "./components/StrategyCards";
import AlertPanel from "./components/AlertPanel";

export default function Home() {
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [manualState, setManualState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [manualMessage, setManualMessage] = useState("");
  const runManualScan = async () => {
    setManualState("running"); setManualMessage("Aktif semboller taranıyor…");
    try {
      const response = await apiRequest(`${API_BASE}/api/strategy/manual-scan`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.reason || "Tarama çalıştırılamadı");
      setManualState("done");
      setManualMessage(`${data.symbols_checked} sembol kontrol edildi · ${data.signals?.length || 0} sinyal`);
    } catch (error) {
      setManualState("error"); setManualMessage(error instanceof Error ? error.message : "Tarama hatası");
    }
  };
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
        <h1 className="font-mono text-xl font-bold tracking-tight">
          CANLI <span className="text-neon-green">SCALPING</span>
        </h1>
        <p className="eyebrow mt-1">Strateji başarı durumu · canlı paper işlem akışı · bakiye ve açık pozisyonlar</p>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <button onClick={runManualScan} disabled={manualState === "running"} className="ui-button ui-button-primary disabled:cursor-wait disabled:opacity-60">
            {manualState === "running" ? "⟳ TARAMA…" : "▶ MANUEL KONTROL"}
          </button>
          <button onClick={() => setAlertsOpen(true)} className="ui-button ui-button-secondary">🔔 ALARMLAR</button>
        </div>
      </header>
      {manualMessage && <div className={`rounded-lg border px-3 py-2 text-xs font-mono ${manualState === "error" ? "border-red-500/40 text-red-300" : "border-neon-green/30 text-bunker-muted"}`}>{manualMessage}</div>}
      <StrategyCards />
      <LiveTerminal />
      {alertsOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4" onClick={() => setAlertsOpen(false)}><div className="max-h-[90dvh] w-full max-w-6xl overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl" onClick={event => event.stopPropagation()}><div className="mb-3 flex justify-end"><button onClick={() => setAlertsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Alarm modalını kapat">✕ KAPAT</button></div><AlertPanel modal /></div></div>}
    </div>
  );
}
