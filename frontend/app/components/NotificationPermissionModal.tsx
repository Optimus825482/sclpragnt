"use client";

import { useEffect, useState } from "react";
import { ensurePushSubscription } from "../lib/push";

const STORAGE_KEY = "scalper:notification-permission-asked";

/** Masaüstü tarayıcılar için: Radar bildirimlerini açmak için izin ister.
 *  Mobil cihazlarda PushOnboardingModal yönetir; bu modal yalnız masaüstü.
 *  İzin verilmiş olsa bile backend'de abonelik yoksa tekrar sorar. */
export default function NotificationPermissionModal({ active = false }: { active?: boolean }) {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (typeof window === "undefined" || !active) return;
    const mobile = /android|iphone|ipad|ipod|mobile|iemobile/i.test(navigator.userAgent || "");
    if (mobile) return; // mobilde PushOnboardingModal çalışır
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    if (Notification.permission === "denied") return; // kalıcı red — tekrar sorma
    try {
      if (localStorage.getItem(STORAGE_KEY)) return;
    } catch {
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), 1500);
    return () => window.clearTimeout(timer);
  }, [active]);

  const enable = async () => {
    setBusy(true); setError("");
    try {
      const result = await ensurePushSubscription();
      if (!result.ok) {
        if (result.reason === "izin_verilmedi") {
          try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
          throw new Error("Bildirim izni verilmedi. Fırsatları kaçırmamak için izni tarayıcı ayarlarından açabilirsiniz.");
        }
        if (result.reason === "push_yok" || result.reason === "vapid_yok") {
          throw new Error("Bu tarayıcı/sürüm Web Push desteklemiyor — Chrome ile açmayı deneyin.");
        }
        if (result.reason === "service_worker_yok") {
          throw new Error("Service Worker desteklenmiyor — güncel bir tarayıcı kullanın.");
        }
        throw new Error("Bildirimler etkinleştirilemedi");
      }
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
      setVisible(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bildirimler etkinleştirilemedi");
    } finally {
      setBusy(false);
    }
  };

  // "BİR DAHA GÖSTERME" — kalıcı kapat
  const dismissForever = () => {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
    setVisible(false);
  };

  // "SONRA" — anlık kapat, bir dahaki oturumda tekrar sorulabilir
  const dismissNow = () => {
    setVisible(false);
  };

  if (!visible) return null;
  return (
    <div className="fixed inset-0 z-[115] grid place-items-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="notif-permission-title">
      <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
          <span className="text-xl">📡</span>
          <div>
            <p className="eyebrow">RADAR BİLDİRİMLERİ</p>
            <h2 id="notif-permission-title" className="font-mono text-lg font-bold text-white">Fırsatları kaçırma</h2>
          </div>
        </div>
        <div className="space-y-3 p-5">
          <p className="text-sm leading-relaxed text-bunker-muted">
            Radar yüksek potansiyelli semboller tespit ettiğinde, uygulama açık olmasa bile <strong className="text-white">masaüstü/tarayıcı bildirimi</strong> almak ister misiniz?
          </p>
          <p className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-xs text-bunker-muted">
            Uygulama açıkken bildirimler, sesli uyarıyla birlikte uygulama içinde onay penceresi olarak görünür.
          </p>
          {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={dismissNow} className="ui-button ui-button-secondary">SONRA</button>
            <button type="button" onClick={enable} disabled={busy} className="ui-button ui-button-primary">
              {busy ? "ETKİNLEŞTİRİLİYOR…" : "BİLDİRİMLERİ AÇ"}
            </button>
          </div>
          <div className="text-center">
            <button type="button" onClick={dismissForever} className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 hover:text-bunker-muted hover:underline">
              BİR DAHA GÖSTERME
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
