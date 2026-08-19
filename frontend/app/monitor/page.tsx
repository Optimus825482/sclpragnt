"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import GainerRadar from "../components/GainerRadar";

const PumpMonitorPanel = dynamic(
  () => import("../pump-monitor/page").then((module) => module.PumpMonitorPanel),
  { loading: () => <div className="card animate-pulse text-bunker-muted">Pump Monitor yükleniyor…</div> },
);

export default function MonitorPage() {
  const [tab, setTab] = useState<"radar" | "pump">(() =>
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
    </nav>
    {tab === "radar" ? <section className="space-y-4"><GainerRadar /><div className="card bg-bunker-950 text-sm text-bunker-muted">Radar sıralama ve gözlem içindir; otomatik paper pozisyon açmaz.</div></section> : <PumpMonitorPanel />}
  </main>;
}
