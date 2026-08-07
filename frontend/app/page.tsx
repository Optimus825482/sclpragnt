"use client";

import { useState } from "react";
import LiveTerminal from "./components/LiveTerminal";
import StrategyCards from "./components/StrategyCards";
import AlertPanel from "./components/AlertPanel";

export default function Home() {
  const [alertsOpen, setAlertsOpen] = useState(false);
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
        <h1 className="font-mono text-xl font-bold tracking-tight">
          CANLI <span className="text-neon-green">SCALPING</span>
        </h1>
        <p className="eyebrow mt-1">Strateji başarı durumu · canlı paper işlem akışı · bakiye ve açık pozisyonlar</p>
        </div>
        <button onClick={() => setAlertsOpen(true)} className="ui-button ui-button-secondary">🔔 ALARMLAR</button>
      </header>
      <StrategyCards />
      <LiveTerminal />
      {alertsOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4" onClick={() => setAlertsOpen(false)}><div className="max-h-[90dvh] w-full max-w-6xl overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl" onClick={event => event.stopPropagation()}><div className="mb-3 flex justify-end"><button onClick={() => setAlertsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Alarm modalını kapat">✕ KAPAT</button></div><AlertPanel modal /></div></div>}
    </div>
  );
}
