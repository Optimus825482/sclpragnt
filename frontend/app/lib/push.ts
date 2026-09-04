"use client";

/**
 * Web Push abonelik yardımcıları — üç farklı modal'da (NotificationPermission,
 * MobileWelcome, Sidebar) tekrarlanan subscribe/kaydet mantığını tek yerde toplar.
 * Ayrıca tarayıcı tespiti ve kurulu PWA (standalone) algısı ortaklaştırılır.
 */
import { API_BASE, apiRequest } from "../lib/api";

export type BrowserKind = "chrome" | "safari" | "other";

export function detectBrowser(): BrowserKind {
  if (typeof window === "undefined") return "other";
  const ua = navigator.userAgent || "";
  // Chrome (Chromium tabanlı tüm Android tarayıcılar dahil) — Safari/iOS hariç.
  if (/chrome|crios|edg|chromium/i.test(ua) && !/safari/i.test(ua)) return "chrome";
  if (/safari|iphone|ipad|ipod/i.test(ua)) return "safari";
  return "other";
}

export function isMobileDevice(): boolean {
  if (typeof window === "undefined") return false;
  return /android|iphone|ipad|ipod|mobile|iemobile/i.test(navigator.userAgent || "");
}

export function isStandalonePwa(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (window.navigator as any)?.standalone === true
  );
}

/** Tarayıcıda Web Push destekleniyor mu + VAPID public key tanımlı mı? */
export function pushSupported(): { ok: boolean; reason?: string } {
  if (typeof window === "undefined") return { ok: false, reason: "no_window" };
  if (!("serviceWorker" in navigator)) return { ok: false, reason: "service_worker_yok" };
  if (!("PushManager" in window)) return { ok: false, reason: "push_yok" };
  const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
  if (!key) return { ok: false, reason: "vapid_yok" };
  return { ok: true };
}

/**
 * Abonelik var mı kontrol et; yoksa oluşturup backend'e kaydeder.
 * Dönen: { ok: boolean; reason?: string; subscription?: PushSubscription }
 */
export async function ensurePushSubscription(): Promise<{ ok: boolean; reason?: string }> {
  const support = pushSupported();
  if (!support.ok) return { ok: false, reason: support.reason };

  if (typeof Notification !== "undefined" && Notification.permission !== "granted") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return { ok: false, reason: "izin_verilmedi" };
  }

  try {
    const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY as string;
    const registration = await navigator.serviceWorker.ready;
    const padded =
      key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (key.length % 4)) % 4);
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)),
      });
    }
    // Backend'e kaydet (idempotent: ON CONFLICT DO UPDATE)
    const response = await apiRequest(`${API_BASE}/api/alerts/push-subscription`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription.toJSON()),
    });
    if (!response.ok) return { ok: false, reason: `kayit_hatasi_${response.status}` };
    return { ok: true };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : "abonelik_hatasi" };
  }
}
