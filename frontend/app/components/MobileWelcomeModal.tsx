"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type Step = "install" | "notify" | null;

const STORAGE_KEY = "scalper:welcome-asked";

function isMobileDevice() {
  if (typeof window === "undefined") return false;
  const ua = (navigator.userAgent || "").toLowerCase();
  return /android|iphone|ipad|ipod|mobile|iemobile/.test(ua);
}

function isStandalone() {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(display-mode: standalone)").matches || (window.navigator as any)?.standalone === true;
}

/** Mobilde giriş sonrası tek seferlik: ana ekrana ekle + bildirim izni. */
export default function MobileWelcomeModal({ active = false }: { active?: boolean }) {
  const [step, setStep] = useState<Step>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const installPromptRef = useRef<any>(null);

  // beforeinstallprompt'u yakala (Android/Chrome)
  useEffect(() => {
    if (!active) return;
    const handler = (e: Event) => {
      e.preventDefault();
      installPromptRef.current = e;
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, [active]);

  // Mobilde ve henüz kurulu değilse adım 1'i başlat
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!isMobileDevice() || isStandalone()) return; // mobil ve kurulu değil
    try {
      if (localStorage.getItem(STORAGE_KEY)) return;
    } catch {
      return;
    }
    const timer = window.setTimeout(() => setStep("install"), 1200);
    return () => window.clearTimeout(timer);
  }, [active]);

  const dismiss = () => {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
    setStep(null);
  };

  // Kurulum adımından bildirim adımına geç; izin zaten verilmişse bitir.
  const goNotify = () => {
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
      dismiss();
      return;
    }
    setStep("notify");
    setError("");
  };

  // --- AŞAMA 1: Ana ekrana ekle ---
  const installPWA = async () => {
    setBusy(true); setError("");
    try {
      if (installPromptRef.current) {
        // Android/Chrome: native kurulum penceresi
        const choice = await installPromptRef.current.prompt();
        installPromptRef.current = null;
        // Kullanıcı kurulumu tamamladıysa bildirim adımına geç; iptal ettiyse yine de bildirimi sor
        goNotify();
        return;
      }
      // iOS veya beforeinstallprompt yok: Paylaş talimatı zaten ekranda; bildirim adımına geç
      goNotify();
    } catch {
      setError("Kurulum başlatılamadı.");
    } finally {
      setBusy(false);
    }
  };

  // --- AŞAMA 2: Bildirim izni ---
  const enableNotifications = async () => {
    setBusy(true); setError("");
    try {
      if (!("Notification" in window)) throw new Error("Bu tarayıcı bildirim desteklemiyor");
      if (!("PushManager" in window)) throw new Error("Bu tarayıcı Web Push desteklemiyor");
      const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
      if (!key) throw new Error("VAPID public key yapılandırılmamış");
      if (Notification.permission !== "granted") {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") throw new Error("Bildirim izni verilmedi. Ayarlardan açabilirsiniz.");
      }
      const registration = await navigator.serviceWorker.ready;
      const padded = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (key.length % 4)) % 4);
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
      dismiss();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bildirimler etkinleştirilemedi");
    } finally {
      setBusy(false);
    }
  };

  if (!step) return null;

  const iOS = /iphone|ipad|ipod/.test((navigator.userAgent || "").toLowerCase());

  return (
    <div className="fixed inset-0 z-[115] grid place-items-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <section className="w-full max-w-sm overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl">
        {step === "install" && (
          <>
            <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
              <span className="text-xl">📱</span>
              <div>
                <p className="eyebrow">HOŞ GELDİN</p>
                <h2 id="welcome-title" className="font-mono text-lg font-bold text-white">Ana Ekrana Ekle</h2>
              </div>
            </div>
            <div className="space-y-3 p-5">
              <p className="text-sm leading-relaxed text-bunker-muted">
                {iOS
                  ? "Safari'de Paylaş (⎋) → “Ana Ekrana Ekle” ile uygulamayı cihazına kur. Böylece bildirimleri alır ve hızlı erişim sağlarsın."
                  : "Uygulamayı cihazına kurarak bildirimleri alabilir ve hızlı erişim sağlayabilirsin."}
              </p>
              {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={goNotify} className="ui-button ui-button-secondary">SONRA</button>
                {iOS ? (
                  <button type="button" onClick={goNotify} className="ui-button ui-button-primary">ANLADIM, DEVAM</button>
                ) : (
                  <button type="button" onClick={installPWA} disabled={busy} className="ui-button ui-button-primary">
                    {busy ? "AÇILIYOR…" : "📲 KUR"}
                  </button>
                )}
              </div>
            </div>
          </>
        )}
        {step === "notify" && (
          <>
            <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
              <span className="text-xl">🔔</span>
              <div>
                <p className="eyebrow">BİLDİRİMLER</p>
                <h2 className="font-mono text-lg font-bold text-white">Fırsatları Kaçırma</h2>
              </div>
            </div>
            <div className="space-y-3 p-5">
              <p className="text-sm leading-relaxed text-bunker-muted">
                Radar yüksek potansiyel sembol tespit ettiğinde anında bildirim almak için izin ver.
              </p>
              {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={dismiss} className="ui-button ui-button-secondary">HAYIR</button>
                <button type="button" onClick={enableNotifications} disabled={busy} className="ui-button ui-button-primary">
                  {busy ? "AÇILIYOR…" : "BİLDİRİMLERİ AÇ"}
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
