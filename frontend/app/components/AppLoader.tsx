"use client";

import { useEffect, useState } from "react";

export type AppLoaderProps = {
  label?: string;
  sublabel?: string;
  variant?: "radar" | "default" | "card" | "inline";
  fullscreen?: boolean;
  minHeight?: string;
  className?: string;
};

export default function AppLoader({
  label = "SİSTEM VERİLERİ YÜKLENİYOR…",
  sublabel = "Canlı piyasa motoru ve veriler senkronize ediliyor",
  variant = "radar",
  fullscreen = false,
  minHeight = "min-h-[55vh]",
  className = "",
}: AppLoaderProps) {
  const [telemetryIndex, setTelemetryIndex] = useState(0);

  const telemetryLines = [
    "MOTOR: AKTİF // PİYASA VERİLERİ OKUNUYOR",
    "CANLI TIKLER: SENKRON // RADAR DERİNLİK KONTROLÜ",
    "IVME & TREND ANALİZİ: ÇALIŞIYOR",
    "GÜÇLÜ SİNYALLER HESAPLANIYOR // DOĞRULAMA AKTİF",
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      setTelemetryIndex((prev) => (prev + 1) % telemetryLines.length);
    }, 1800);
    return () => clearInterval(timer);
  }, [telemetryLines.length]);

  if (variant === "inline") {
    return (
      <div className={`inline-flex items-center gap-2.5 font-mono text-xs text-neon-green ${className}`} role="status">
        <span className="relative flex h-2.5 w-2.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-green opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-neon-green" />
        </span>
        <span className="font-bold tracking-wider">{label}</span>
      </div>
    );
  }

  if (variant === "card") {
    return (
      <div className={`flex flex-col items-center justify-center p-8 text-center rounded-xl border border-bunker-800 bg-bunker-900/40 backdrop-blur-sm ${className}`} role="status">
        <div className="monitoring-radar mb-4 scale-90">
          <div className="monitoring-radar-ring monitoring-radar-ring-1" />
          <div className="monitoring-radar-ring monitoring-radar-ring-2" />
          <div className="monitoring-radar-ring monitoring-radar-ring-3" />
          <div className="monitoring-radar-sweep" />
          <div className="monitoring-radar-center" />
        </div>
        <p className="font-mono text-sm font-bold text-neon-green tracking-wide">{label}</p>
        {sublabel && <p className="mt-1 font-mono text-xs text-bunker-muted max-w-sm">{sublabel}</p>}
      </div>
    );
  }

  const containerClasses = fullscreen
    ? "fixed inset-0 z-50 flex flex-col items-center justify-center bg-bunker-950/95 backdrop-blur-md p-6"
    : `flex flex-col items-center justify-center ${minHeight} p-6 ${className}`;

  return (
    <div className={containerClasses} role="status" aria-live="polite">
      {/* Visual Animation: Radar or Orbital Cyber Spinner */}
      {variant === "radar" ? (
        <div className="relative flex items-center justify-center mb-6">
          {/* Outer Ambient Glow */}
          <div className="absolute w-44 h-44 rounded-full bg-neon-green/10 blur-xl animate-pulse pointer-events-none" />

          {/* Radar Container */}
          <div className="monitoring-radar !w-32 !h-32 shadow-2xl shadow-neon-green/10 border-neon-green/40">
            {/* HUD Target Ticks */}
            <div className="absolute top-1 left-1/2 -translate-x-1/2 w-0.5 h-1.5 bg-neon-green/60" />
            <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-0.5 h-1.5 bg-neon-green/60" />
            <div className="absolute left-1 top-1/2 -translate-y-1/2 w-1.5 h-0.5 bg-neon-green/60" />
            <div className="absolute right-1 top-1/2 -translate-y-1/2 w-1.5 h-0.5 bg-neon-green/60" />

            {/* Concentric Rings */}
            <div className="monitoring-radar-ring monitoring-radar-ring-1" />
            <div className="monitoring-radar-ring monitoring-radar-ring-2" />
            <div className="monitoring-radar-ring monitoring-radar-ring-3" />

            {/* Sweeping Beam */}
            <div className="monitoring-radar-sweep" />

            {/* Glowing Center Point */}
            <div className="monitoring-radar-center" />

            {/* Dynamic Signal Blips */}
            <span
              className="absolute w-1.5 h-1.5 rounded-full bg-neon-green animate-ping"
              style={{ top: "32%", left: "68%", animationDuration: "1.6s" }}
            />
            <span
              className="absolute w-1 h-1 rounded-full bg-cyan-400 animate-ping"
              style={{ top: "62%", left: "28%", animationDuration: "2.2s", animationDelay: "0.8s" }}
            />
          </div>
        </div>
      ) : (
        <div className="relative flex items-center justify-center mb-6">
          <div className="absolute w-36 h-36 rounded-full bg-neon-green/10 blur-xl animate-pulse" />
          <div className="relative w-24 h-24">
            {/* Dual Ring Spinner */}
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-neon-green border-r-neon-green/50 animate-spin" />
            <div
              className="absolute inset-2 rounded-full border-2 border-transparent border-b-cyan-400 border-l-cyan-400/50 animate-spin"
              style={{ animationDirection: "reverse", animationDuration: "1.4s" }}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="w-2.5 h-2.5 rounded-full bg-neon-green shadow-lg shadow-neon-green" />
            </div>
          </div>
        </div>
      )}

      {/* Label and Subtitle */}
      <div className="text-center space-y-2 max-w-md">
        <div className="inline-flex items-center gap-2 rounded-full border border-neon-green/30 bg-neon-green/10 px-3 py-1 font-mono text-[10px] font-bold text-neon-green uppercase tracking-wider">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" />
          CANLI SİSTEM TELEMETRİSİ
        </div>

        <h3 className="font-mono text-base sm:text-lg font-black text-white tracking-wide">
          {label}
        </h3>

        {sublabel && (
          <p className="font-mono text-xs text-bunker-muted leading-relaxed">
            {sublabel}
          </p>
        )}

        {/* Telemetry Ticker */}
        <div className="pt-2">
          <p className="font-mono text-[11px] text-cyan-400/80 bg-bunker-900/60 border border-bunker-800 rounded-lg px-3 py-1.5 inline-block tracking-wider">
            {telemetryLines[telemetryIndex]}
          </p>
        </div>
      </div>
    </div>
  );
}
