"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

const STORAGE_KEY = "scalper:notification-permission-asked";

/** Login sonrası bir kez gösterilir: Radar bildirimlerini açmak için izin ister.
 *  `active` true olduğunda (oturum açıldı) görünür; localStorage ile bir kez sorulur. */
export default function NotificationPermissionModal({ active = false }: { active?: boolean }) {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (typeof window === "undefined" || !active) return;
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    if (window.matchMedia?.("(display-mode: standalone)").matches) return; // Kurulu PWA: push zaten ayarlı olabilir
    if (Notification.permission === "granted") return; // izin zaten verilmiş
    if (Notification.permission === "denied") return; // kalıcı red — tekrar sorma, ekranı karartma
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
      if (!("Notification" in window)) throw new Error("Bu tarayıcı bildirim desteklemiyor");
      if (!("PushManager" in window)) throw new Error("Bu tarayıcı Web Push desteklemiyor");
      const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
      if (!key) throw new Error("VAPID public key yapılandırılmamış");
      if (Notification.permission !== "granted") {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") throw new Error("Bildirim izni verilmedi. Radar fırsatlarını kaçırmamak için izni tarayıcı ayarlarından açabilirsiniz.");
      }
      const registration = await navigator.serviceWorker.ready;
      const padded = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - key.length % 4) % 4);
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)),
        });
      }
      await apiRequest(`${API_BASE}/api/alerts/push-subscription`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(subscription.toJSON()),
      });
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
      setVisible(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bildirimler etkinleştirilemedi");
    } finally {
      setBusy(false);
    }
  };

  const dismiss = () => {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
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
            <button type="button" onClick={dismiss} className="ui-button ui-button-secondary">SONRA</button>
            <button type="button" onClick={enable} disabled={busy} className="ui-button ui-button-primary">
              {busy ? "ETKİNLEŞTİRİLİYOR…" : "BİLDİRİMLERİ AÇ"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
