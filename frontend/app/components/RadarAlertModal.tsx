"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveMessages } from "../lib/liveSocket";
import SymbolLink from "./SymbolLink";

/** Kısa, keskin "radar" sesi: iki vuruşlu yüksek ton + düşük vurgu. */
export function playRadarAlertSound() {
  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;
    const context = new AudioContextClass();
    const now = context.currentTime;
    const notes: Array<[number, number, number]> = [
      [1046.5, now, 0.12],      // C6
      [1318.5, now + 0.14, 0.12], // E6
      [1568.0, now + 0.28, 0.22], // G6
    ];
    for (const [freq, start, dur] of notes) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + dur + 0.02);
      oscillator.addEventListener("ended", () => context.close());
    }
  } catch {
    // Ses engellenmişse (otomatik oynatma politikası) modal yine de görünür.
  }
}

export type RadarAlertItem = {
  id?: string | number;
  symbol?: string;
  message?: string;
  reason?: string;
  title?: string;
  score?: number;
  target_pct?: number;
  price?: number;
  mode?: string;
  triggered_at?: number;
  auto_paper_trade?: { status?: string; error?: string } | null;
};

const fmtPrice = (value: number | undefined, symbol?: string) => {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = symbol && symbol.includes("TRY") && value < 100 ? 6 : value < 10 ? 4 : 2;
  return `${Number(value).toFixed(digits)} TRY`;
};

export default function RadarAlertModal() {
  const [item, setItem] = useState<RadarAlertItem | null>(null);
  const [queue, setQueue] = useState<RadarAlertItem[]>([]);
  const busyRef = useRef(false);

  const showNext = useCallback((next: RadarAlertItem | null) => {
    if (next) {
      playRadarAlertSound();
      setItem(next);
      busyRef.current = true;
    } else {
      setItem(null);
      busyRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (!item && queue.length > 0) {
      const [head, ...rest] = queue;
      setQueue(rest);
      showNext(head);
    }
  }, [item, queue, showNext]);

  const onLiveMessage = useCallback((message: { type: string; data?: unknown }) => {
    if (message.type !== "alert") return;
    const data = (message.data || {}) as RadarAlertItem;
    const entry: RadarAlertItem = {
      ...data,
      id: data.id ?? (data as any).event_key ?? `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      symbol: data.symbol,
      message: data.message || data.reason || "Yeni radar bildirimi",
      triggered_at: data.triggered_at || Date.now() / 1000,
    };
    if (busyRef.current) {
      setQueue((current) => [...current, entry].slice(-5));
    } else {
      showNext(entry);
    }
  }, [showNext]);

  useLiveMessages(onLiveMessage);

  const close = () => showNext(null);

  return (
    <div className="fixed inset-0 z-[120] grid place-items-center bg-black/75 p-4" onClick={close} role="alertdialog" aria-modal="true" aria-labelledby="radar-alert-title">
      {item ? (
        <section className="w-full max-w-md overflow-hidden rounded-xl border border-neon-green/40 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-bunker-800 bg-neon-green/5 px-5 py-4">
            <div className="flex items-center gap-2">
              <span className="text-xl">🚨</span>
              <div>
                <p className="eyebrow text-neon-green/80">RADAR BİLDİRİMİ</p>
                <h2 id="radar-alert-title" className="font-mono text-lg font-bold text-white">
                  {item.symbol ? <SymbolLink symbol={item.symbol} className="text-neon-green hover:text-white" /> : "YENİ ALARM"}
                </h2>
              </div>
            </div>
            <button type="button" onClick={close} aria-label="Bildirimi kapat" className="text-bunker-muted hover:text-white">✕</button>
          </div>
          <div className="space-y-3 p-5">
            <p className="text-sm leading-relaxed text-white">{item.message}</p>
            {(item.target_pct != null || item.score != null || item.price != null) && (
              <div className="grid grid-cols-3 gap-2">
                {item.price != null && (
                  <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
                    <p className="eyebrow">ANLIK</p>
                    <p className="mt-1 font-mono text-sm font-bold text-white">{fmtPrice(item.price, item.symbol)}</p>
                  </div>
                )}
                {item.target_pct != null && (
                  <div className="rounded-lg border border-neon-green/30 bg-neon-green/5 px-3 py-2 text-center">
                    <p className="eyebrow">HEDEF</p>
                    <p className="mt-1 font-mono text-sm font-bold text-neon-green">+%{Number(item.target_pct).toFixed(1)}</p>
                  </div>
                )}
                {item.score != null && (
                  <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
                    <p className="eyebrow">SKOR</p>
                    <p className="mt-1 font-mono text-sm font-bold text-amber-300">{Number(item.score).toFixed(1)}</p>
                  </div>
                )}
              </div>
            )}
            {item.auto_paper_trade && item.auto_paper_trade.status === "ok" && (
              <p className="rounded-lg border border-neon-green/30 bg-neon-green/10 px-3 py-2 text-sm text-neon-green">
                🤖 Otomatik paper işlem denemesi başlatıldı.
              </p>
            )}
            {item.auto_paper_trade && item.auto_paper_trade.status && item.auto_paper_trade.status !== "ok" && (
              <p className="rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-300">
                Otomatik paper işlem: {item.auto_paper_trade.error || item.auto_paper_trade.status}
              </p>
            )}
            <div className="flex items-center justify-between pt-1">
              <p className="font-mono text-[10px] text-bunker-muted">
                {item.triggered_at
                  ? new Date(Number(item.triggered_at) < 10_000_000_000 ? Number(item.triggered_at) * 1000 : Number(item.triggered_at)).toLocaleString("tr-TR")
                  : ""}
              </p>
              <div className="flex gap-2">
                {item.symbol && (
                  <a href={`/charts?symbol=${item.symbol}`} onClick={close} className="ui-button ui-button-secondary">GRAFİĞE GİT</a>
                )}
                <button type="button" onClick={close} className="ui-button ui-button-primary">ANLAŞILDI</button>
              </div>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
