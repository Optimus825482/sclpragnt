"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useLiveMessages } from "../lib/liveSocket";
import { sound } from "../lib/sound";
import { formatPct, formatPrice } from "../lib/format";
import { baseAsset } from "../lib/opportunity";
import { SELECT_SYMBOL_QUERY, requestSymbolSelection } from "../lib/uiEvents";

export type SignalToast = {
  id: string;
  symbol: string;
  source: string;
  price?: number | null;
  targetPct?: number | null;
  score?: number | null;
  timestamp: number;
};

const TOAST_TYPES = ["monitoring_alert", "rising_alert", "signal"] as const;
const AUTO_DISMISS_MS = 8_000;

/**
 * Canlı sinyal toast'ları. Kabuk (AppShell) seviyesinde BİR KEZ mount edilir,
 * her sayfada görünür (denetim P1-6). "İşlem Yap" sembolü ana sayfadaki emir
 * paneline taşır; bu EMİR GÖNDERMEZ, gerçek emir ayrı onay ister.
 */
export default function LiveNotificationToast({ onSelectSymbol }: { onSelectSymbol?: (symbol: string) => void }) {
  const [toasts, setToasts] = useState<SignalToast[]>([]);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const timers = useRef(new Map<string, number>());
  const router = useRouter();
  const pathname = usePathname();

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

  useEffect(() => {
    const active = timers.current;
    return () => {
      active.forEach((timer) => window.clearTimeout(timer));
      active.clear();
    };
  }, []);

  const removeToast = (id: string) => {
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  useLiveMessages((msg) => {
    const newSignals: SignalToast[] = [];
    const now = Date.now();
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
        id: `${symbol}-${now}-${Math.random().toString(36).slice(2, 8)}`,
        symbol,
        source,
        price,
        targetPct: targetPct > 0 ? targetPct : null,
        score: score > 0 ? Math.round(score) : null,
        timestamp: now,
      });
    }

    if (newSignals.length === 0) return;
    if (soundEnabled) sound.playSignalChime();

    const shown = newSignals.slice(0, 3);
    setToasts((prev) => {
      const next = [...shown, ...prev].slice(0, 4);
      // Listeden düşenlerin zamanlayıcısı da düşsün.
      const kept = new Set(next.map((t) => t.id));
      timers.current.forEach((timer, id) => {
        if (!kept.has(id)) { window.clearTimeout(timer); timers.current.delete(id); }
      });
      return next;
    });
    // Her toast kendi kimliğiyle kapanır; eski sürüm `now` değerini yakaladığı
    // için `now - timestamp` hep 0 kalıyor ve toast'lar hiç silinmiyordu.
    shown.forEach((toast) => {
      timers.current.set(toast.id, window.setTimeout(() => removeToast(toast.id), AUTO_DISMISS_MS));
    });
  }, TOAST_TYPES);

  if (toasts.length === 0) return null;

  const selectSymbol = (symbol: string) => {
    if (onSelectSymbol) {
      onSelectSymbol(symbol);
      return;
    }
    requestSymbolSelection({ symbol, amount: 1000 });
    if (pathname !== "/") router.push(`/?${SELECT_SYMBOL_QUERY}=${encodeURIComponent(symbol)}`);
  };

  return (
    <div className="fixed bottom-5 right-5 z-50 flex max-w-sm flex-col gap-2 pointer-events-none" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-start gap-3 rounded-xl border border-accent/30 bg-white/95 p-3.5 shadow-2xl backdrop-blur-md transition-all animate-in slide-in-from-bottom-5 duration-300"
          role="status"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent font-bold text-base" aria-hidden="true">
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
                  selectSymbol(toast.symbol);
                  removeToast(toast.id);
                }}
                className="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white shadow-sm hover:bg-accent/90"
                title="Sembolü emir paneline taşır; emir göndermez"
              >
                Panele Aktar
              </button>
              <button
                type="button"
                onClick={() => removeToast(toast.id)}
                className="rounded-md px-2 py-1 text-xs text-ink-400 hover:bg-slate-100 hover:text-ink-700"
                aria-label={`${toast.symbol} bildirimini kapat`}
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
