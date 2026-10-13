"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLiveMessages } from "../lib/liveSocket";
import { sound } from "../lib/sound";
import { formatPct, formatPrice } from "../lib/format";
import { baseAsset } from "../lib/opportunity";

export type SignalToast = {
  id: string;
  symbol: string;
  source: string;
  price?: number | null;
  targetPct?: number | null;
  score?: number | null;
  timestamp: number;
};

export default function LiveNotificationToast({ onSelectSymbol }: { onSelectSymbol?: (symbol: string) => void }) {
  const [toasts, setToasts] = useState<SignalToast[]>([]);
  const [soundEnabled, setSoundEnabled] = useState(true);

  // Ses ayarını localStorage veya tercihlerden al
  useEffect(() => {
    try {
      const saved = localStorage.getItem("odak_sound_enabled");
      if (saved !== null) {
        setSoundEnabled(saved === "true");
      }
    } catch {
      // pass
    }
  }, []);

  useLiveMessages((msg) => {
    let newSignals: SignalToast[] = [];
    const now = Date.now();

    if (msg.type === "monitoring_alert" || msg.type === "rising_alert" || msg.type === "signal") {
      const rawItems = Array.isArray(msg.data) ? msg.data : [msg.data];

      for (const item of rawItems) {
        if (!item || typeof item !== "object") continue;
        const row = item as Record<string, unknown>;
        const symbol = String(row.symbol || row.pair || "").toUpperCase();
        if (!symbol) continue;

        const targetPct = Number(row.target_pct ?? row.potential_pct ?? row.ceiling_pct ?? 0);
        const score = Number(row.score ?? row.quality_score ?? row.unified_score ?? row.velocity_score ?? 0);
        const price = Number(row.price ?? row.current_price ?? row.entry_price ?? 0) || null;
        const source = String(row.source ?? row.strategy ?? (msg.type === "rising_alert" ? "Yükseliş" : "Radar Sinyali"));

        newSignals.push({
          id: `${symbol}-${now}-${Math.random()}`,
          symbol,
          source,
          price,
          targetPct: targetPct > 0 ? targetPct : null,
          score: score > 0 ? Math.round(score) : null,
          timestamp: now,
        });
      }
    }

    if (newSignals.length > 0) {
      if (soundEnabled) {
        sound.playSignalChime();
      }

      setToasts((prev) => [...newSignals.slice(0, 3), ...prev].slice(0, 4));

      // 8 saniye sonra otomatik kaybolsun
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => now - t.timestamp < 8000));
      }, 8200);
    }
  });

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex max-w-sm flex-col gap-2 pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-start gap-3 rounded-xl border border-accent/30 bg-white/95 p-3.5 shadow-2xl backdrop-blur-md transition-all animate-in slide-in-from-bottom-5 duration-300"
          role="alert"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent font-bold text-base">
            ⚡
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-1">
              <span className="font-mono text-sm font-bold text-ink-900">
                {baseAsset(toast.symbol)}
                <span className="text-xs font-normal text-ink-400"> / TRY</span>
              </span>
              <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                {toast.source}
              </span>
            </div>
            <div className="mt-1 flex items-baseline gap-2 text-xs">
              {toast.price && <span className="font-mono font-medium text-ink-700">{formatPrice(toast.price)}</span>}
              {toast.targetPct != null && (
                <span className="font-mono font-bold text-gain">↗ {formatPct(toast.targetPct, 1, true)}</span>
              )}
              {toast.score != null && <span className="text-[11px] text-ink-400">Skor: {toast.score}</span>}
            </div>
            <div className="mt-2.5 flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  onSelectSymbol?.(toast.symbol);
                  removeToast(toast.id);
                }}
                className="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white shadow-sm hover:bg-accent/90"
              >
                Hemen Al / İşlem Yap
              </button>
              <button
                type="button"
                onClick={() => removeToast(toast.id)}
                className="rounded-md px-2 py-1 text-xs text-ink-400 hover:bg-slate-100 hover:text-ink-700"
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
