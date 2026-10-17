"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
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
  // 2026-09-17: `monitoring_alert` yayınlarında mevcut (hâlâ BEKLİYOR)
  // bildirimin tazelemesini işaretler — modal bu satırları GÖSTERMEZ.
  updated?: boolean;
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
// NOT (2026-10-07): Global taraması v4'ün içine alındığında "global" türü
// KALDIRILDI — Global erken tespitleri sıradan bir TR radar bildirimi olarak
// görünür (kullanıcı direktifi: arayüzde Global'e dair hiçbir şey olmayacak).
type AlertKind = "radar" | "alarm" | "rising";

// 2026-10-17: renkler artık `globals.css` içindeki `.ra-*` sınıflarından (opak, tema-bağımsız) gelir;
// burada yalnız metin/ikon tutulur. `data-kind` üst çizgi/vurgu rengini seçer.
const KIND_META: Record<AlertKind, { eyebrow: string; icon: string }> = {
  radar: { eyebrow: "RADAR BİLDİRİMİ", icon: "🚨" },
  alarm: { eyebrow: "ALARM BİLDİRİMİ", icon: "🔔" },
  rising: { eyebrow: "YÜKSELİŞ EĞİLİMİ BİLDİRİMİ", icon: "📈" },
};

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
  const dialogRef = useRef<HTMLElement | null>(null);

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
      showNext(
        head,
        head.alertKind === "yukselis" || head.alertKind === "erken" ? "rising" : "radar"
      );
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
    // MÜKERRER BİLDİRİM ÖNLEMİ (2026-09-17): `monitoring_alert` yayınları
    // YENİ + GÜNCELLENEN kayıtları birlikte taşır. `updated=true` satırı zaten
    // açık olan bir bildirimin (aynı sembol, hâlâ BEKLİYOR) her taramadaki
    // tazelemesidir — modal'ı tekrar açıp sesi yeniden çalmamalı. Panel
    // tablosu bu satırları yine kullanır (sayfa kendi `loadState` çağrısıyla).
    const freshRows = rows.filter((r) => !r.updated);
    const entries: RadarAlertItem[] = freshRows.map((raw) => {
      return {
        ...raw,
        id: raw.id ?? (raw as any).event_key ?? `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        symbol: raw.symbol,
        message: raw.message || raw.reason
          || (alertKind === "rising" ? "Yükseliş sinyali" : alertKind === "radar" ? "Yeni radar fırsatı" : "Yeni alarm"),
        title: raw.title,
        alertKind: raw.alertKind ?? (raw.kind === "erken" || raw.kind === "yukselis" ? raw.kind : undefined),
        triggered_at: raw.triggered_at ?? raw.detected_at ?? Date.now() / 1000,
      };
    });
    if (entries.length === 0) return;
    if (busyRef.current) {
      setQueue((current) => [...current, ...entries].slice(-5));
      return;
    }
    const [head, ...rest] = entries;
    if (rest.length) setQueue((current) => [...current, ...rest].slice(-5));
    showNext(head, alertKind);
  }, [showNext]);

  useLiveMessages(onLiveMessage, ["monitoring_alert", "alert", "rising_alert"]);

  const close = useCallback(() => showNext(null), [showNext]);

  // Erişilebilirlik: açılınca odak pencereye (ANLAŞILDI düğmesine) taşınır, Escape kapatır,
  // Tab pencere içinde döner, kapanınca odak önceki öğeye geri verilir.
  const open = item !== null;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    const primary = dialog?.querySelector<HTMLElement>("[data-ra-primary]");
    (primary ?? dialog)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialogRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      try { previous?.focus?.(); } catch { /* odak geri verilemezse sessiz geç */ }
    };
  }, [open, close]);

  if (!item) return null;
  const meta = KIND_META[kind];
  const risingKind = item.alertKind;
  const proximityPct = typeof item.proximity === "number" ? Math.round(item.proximity * 100) : null;

  return (
    <div className="ra-overlay" onClick={close}>
      <section
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="radar-alert-title"
        aria-describedby="radar-alert-message"
        tabIndex={-1}
        data-kind={kind}
        className="ra-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ra-head">
          <div className="ra-head-main">
            <span className="ra-icon" aria-hidden="true">{meta.icon}</span>
            <div>
              <p className="ra-eyebrow">{meta.eyebrow}</p>
              <h2 id="radar-alert-title" className="ra-title">
                {item.symbol ? <SymbolLink symbol={item.symbol} className="ra-symbol" /> : "YENİ ALARM"}
              </h2>
            </div>
          </div>
          <button type="button" onClick={close} aria-label="Bildirimi kapat" className="ra-close">✕</button>
        </div>
        <div className="ra-body">
          {risingKind && (
            <span className={`ra-chip ${risingKind === "erken" ? "ra-chip-info" : ""}`}>
              {risingKind === "erken" ? "🌱 ERKEN SİNYAL — YAKLAŞIYOR" : "📈 YÜKSELİŞ EĞİLİMİ"}
            </span>
          )}
          <p id="radar-alert-message" className="ra-msg">{item.message}</p>
          {(item.target_pct != null || item.score != null || item.price != null || proximityPct != null) && (
            <div className="ra-tiles">
              {item.price != null && (
                <div className="ra-tile">
                  <p className="ra-tile-label">ANLIK</p>
                  <p className="ra-tile-value">{fmtPrice(item.price, item.symbol)}</p>
                </div>
              )}
              {item.target_pct != null && (
                <div className="ra-tile ra-tile-good">
                  <p className="ra-tile-label">HEDEF</p>
                  <p className="ra-tile-value">+%{Number(item.target_pct).toFixed(1)}</p>
                </div>
              )}
              {item.score != null && (
                <div className="ra-tile ra-tile-warn">
                  <p className="ra-tile-label">SKOR</p>
                  <p className="ra-tile-value">{Number(item.score).toFixed(1)}</p>
                </div>
              )}
              {proximityPct != null && (
                <div className="ra-tile ra-tile-info">
                  <p className="ra-tile-label">ZİRVEYE YAKINLIK</p>
                  <p className="ra-tile-value">%{proximityPct}</p>
                </div>
              )}
            </div>
          )}
          {item.auto_paper_trade && item.auto_paper_trade.status === "ok" && (
            <p className="ra-note">🤖 Otomatik paper işlem denemesi başlatıldı.</p>
          )}
          {item.auto_paper_trade && item.auto_paper_trade.status && item.auto_paper_trade.status !== "ok" && (
            <p className="ra-note ra-note-warn">
              Otomatik paper işlem: {item.auto_paper_trade.error || item.auto_paper_trade.status}
            </p>
          )}
          <div className="ra-foot">
            <p className="ra-time">{item.triggered_at ? fmtDateTime(item.triggered_at) : ""}</p>
            <div className="ra-actions">
              {item.symbol && (
                <Link href={`/charts?symbol=${item.symbol}`} onClick={close} className="ui-button ui-button-secondary touch-target flex items-center justify-center">GRAFİĞE GİT</Link>
              )}
              <button type="button" onClick={close} data-ra-primary className="ui-button ui-button-primary touch-target">ANLAŞILDI</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
