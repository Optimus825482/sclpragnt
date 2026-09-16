"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveMessages } from "../lib/liveSocket";
import { fmtDateTime, formatPrice } from "../lib/format";
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
  expected_price?: number;
  mode?: string;
  triggered_at?: number;
  detected_at?: number;
  horizon_minutes?: number;
  auto_paper_trade?: { status?: string; error?: string } | null;
  // R3 (2026-09-14): yükseliş/erken sinyali alanları (WS `rising_alert`).
  // `kind` SUNUCUDAN gelen ham alan adıdır ("erken" | "yukselis");
  // `alertKind` bu modülün normalize ettiği tür.
  kind?: string;
  alertKind?: "erken" | "yukselis";
  proximity?: number | null;
  early_score?: number | null;
  green?: number | null;
  strength?: number | null;
  signals?: Record<string, unknown> | null;
};

// Dialog türü: radar (monitoring_alert) · alarm (alert) · yükseliş (rising_alert).
type AlertKind = "radar" | "alarm" | "rising";

const KIND_META: Record<AlertKind, { eyebrow: string; icon: string; accent: string }> = {
  radar: { eyebrow: "RADAR BİLDİRİMİ", icon: "🚨", accent: "border-neon-green/40 bg-neon-green/5" },
  alarm: { eyebrow: "ALARM BİLDİRİMİ", icon: "🔔", accent: "border-amber-300/40 bg-amber-300/5" },
  rising: { eyebrow: "YÜKSELİŞ EĞİLİMİ BİLDİRİMİ", icon: "📈", accent: "border-sky-400/40 bg-sky-400/5" },
};

// H-16: biçim TEK kaynaktan (`lib/format`); buradaki 5. hassasiyet kopyası
// (binlik ayraçsız `toFixed`) kaldırıldı. Sembol argümanı geriye dönük uyum
// için korunur ama artık kullanılmaz.
const fmtPrice = (value: number | undefined, _symbol?: string) => {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${formatPrice(value)} TRY`;
};

export default function RadarAlertModal() {
  const [item, setItem] = useState<RadarAlertItem | null>(null);
  const [queue, setQueue] = useState<RadarAlertItem[]>([]);
  const [kind, setKind] = useState<AlertKind>("radar");
  const busyRef = useRef(false);

  const showNext = useCallback((next: RadarAlertItem | null, nextKind: AlertKind = "radar") => {
    if (next) {
      playRadarAlertSound();
      setKind(nextKind);
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
      showNext(head, head.alertKind === "yukselis" || head.alertKind === "erken" ? "rising" : "radar");
    }
  }, [item, queue, showNext]);

  const onLiveMessage = useCallback((message: { type: string; data?: unknown }) => {
    if (message.type !== "monitoring_alert" && message.type !== "alert"
        && message.type !== "rising_alert") return;
    const alertKind: AlertKind =
      message.type === "rising_alert" ? "rising"
        : message.type === "monitoring_alert" ? "radar" : "alarm";
    // ÖNEMLİ: `monitoring_alert` ve `rising_alert` yayınları LİSTE taşır
    // (`data: [...]`), `alert` ise tek nesne. Eskiden `data` her zaman nesne
    // varsayılıyordu → radar dialog'u sembol/skor olmadan jenerik açılıyordu.
    const payload = message.data;
    const rows = (Array.isArray(payload) ? payload : [payload]).filter(Boolean) as RadarAlertItem[];
    const entries: RadarAlertItem[] = rows.map((raw) => ({
      ...raw,
      id: raw.id ?? (raw as any).event_key ?? `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      symbol: raw.symbol,
      message: raw.message || raw.reason
        || (alertKind === "rising" ? "Yükseliş sinyali" : alertKind === "radar" ? "Yeni radar fırsatı" : "Yeni alarm"),
      title: raw.title,
      alertKind: (raw.alertKind ?? (raw.kind === "erken" || raw.kind === "yukselis" ? raw.kind : undefined)),
      triggered_at: raw.triggered_at ?? raw.detected_at ?? Date.now() / 1000,
    }));
    if (entries.length === 0) return;
    if (busyRef.current) {
      setQueue((current) => [...current, ...entries].slice(-5));
      return;
    }
    const [head, ...rest] = entries;
    if (rest.length) setQueue((current) => [...current, ...rest].slice(-5));
    showNext(head, alertKind);
  }, [showNext]);

  useLiveMessages(onLiveMessage);

  const close = () => showNext(null);

  if (!item) return null;
  const meta = KIND_META[kind];
  const risingKind = item.alertKind;
  const proximityPct = typeof item.proximity === "number" ? Math.round(item.proximity * 100) : null;

  return (
    <div className="fixed inset-0 z-[120] grid place-items-center bg-black/75 p-4" onClick={close} role="alertdialog" aria-modal="true" aria-labelledby="radar-alert-title">
      <section className={`w-full max-w-md overflow-hidden rounded-xl border ${meta.accent} bg-bunker-950 shadow-2xl`} onClick={(e) => e.stopPropagation()}>
          <div className={`flex items-center justify-between border-b border-bunker-800 px-5 py-4 ${meta.accent}`}>
            <div className="flex items-center gap-2">
              <span className="text-xl">{meta.icon}</span>
              <div>
                <p className="eyebrow text-neon-green/80">{meta.eyebrow}</p>
                <h2 id="radar-alert-title" className="font-mono text-lg font-bold text-white">
                  {item.symbol ? <SymbolLink symbol={item.symbol} className="text-neon-green hover:text-white" /> : "YENİ ALARM"}
                </h2>
              </div>
            </div>
            <button type="button" onClick={close} aria-label="Bildirimi kapat" className="text-bunker-muted hover:text-white">✕</button>
          </div>
          <div className="space-y-3 p-5">
            {risingKind && (
              <span className={`inline-block rounded border px-2 py-0.5 font-mono text-[10px] font-bold ${risingKind === "erken" ? "border-sky-400/40 bg-sky-400/10 text-sky-300" : "border-neon-green/40 bg-neon-green/10 text-neon-green"}`}>
                {risingKind === "erken" ? "🌱 ERKEN SİNYAL — YAKLAŞIYOR" : "📈 YÜKSELİŞ EĞİLİMİ"}
              </span>
            )}
            <p className="text-sm leading-relaxed text-white">{item.message}</p>
            {(item.target_pct != null || item.score != null || item.price != null || proximityPct != null) && (
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
                {proximityPct != null && (
                  <div className="rounded-lg border border-sky-400/30 bg-sky-400/5 px-3 py-2 text-center">
                    <p className="eyebrow">ZİRVEYE YAKINLIK</p>
                    <p className="mt-1 font-mono text-sm font-bold text-sky-300">%{proximityPct}</p>
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
                {item.triggered_at ? fmtDateTime(item.triggered_at) : ""}
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
    </div>
  );
}
