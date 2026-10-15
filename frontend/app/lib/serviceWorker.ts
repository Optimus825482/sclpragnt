"use client";
import { useEffect } from "react";

/**
 * SW'ye VAPID public key'i SORGU ile geçirir (SW bundle'ı `process.env` göremez;
 * `pushsubscriptionchange` sonrası yeniden abone olmak için anahtara ihtiyaç duyar).
 */
export function serviceWorkerUrl(build: string, vapid: string): string {
  const v = build || "dev";
  return `/sw.js?v=${v}${vapid ? `&vapid=${encodeURIComponent(vapid)}` : ""}`;
}

/**
 * Service worker kaydı. TEK yerden (AppShell) çağrılır; hem admin (Sidebar'lı) hem kullanıcı
 * kabuğu için push çalışsın diye. Önceden kayıt yalnız Sidebar içindeydi: kullanıcı kabuğu
 * Sidebar'ı yüklemediği için SW hiç kaydolmuyor, `serviceWorker.ready` sonsuza dek bekliyordu.
 * Geliştirme modunda mevcut kayıtlar kaldırılır (eski Sidebar davranışı korunur).
 */
export function useServiceWorker() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV === "production") {
      const vapid = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";
      navigator.serviceWorker
        .register(serviceWorkerUrl(process.env.NEXT_PUBLIC_BUILD_ID || "", vapid))
        .catch(() => undefined);
    } else {
      navigator.serviceWorker
        .getRegistrations()
        .then((registrations) => registrations.forEach((registration) => registration.unregister()))
        .catch(() => undefined);
    }
  }, []);
}
