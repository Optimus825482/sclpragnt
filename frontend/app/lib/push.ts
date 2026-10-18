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
  // ÖNEMLİ: Android Chrome UA'sı "…Chrome/120.0 Safari/537.36" ile biter —
  // "safari" alt dizesi içerdiği için basit !/safari/ kontrolü Chrome'u yanlış
  // "safari" sanar. Sıralama önemli: önce Chromium tabanlı olanları yakala.
  //   CriOS  → iOS Chrome (Chromium ama iOS kuralları geçerli → safari grubu)
  if (/crios/i.test(ua)) return "safari"; // iOS Chrome: Web Push kısıtları Safari gibi
  if (/chrome|chromium|edg|edge|opr/i.test(ua)) return "chrome";
  if (/safari|iphone|ipad|ipod/i.test(ua)) return "safari";
  return "other";
}

/**
 * iPhone/iPad/iPod mu? iPadOS 13+ Safari kendini "Macintosh" olarak tanıtır (masaüstü UA);
 * Mac'ten tek ayrım dokunmatik noktalardır (`maxTouchPoints > 1`). Saf: testlenebilsin diye
 * UA/platform/dokunma sayısı parametre alır.
 */
export function isIOSLike(ua: string, platform = "", maxTouchPoints = 0): boolean {
  if (/iphone|ipad|ipod/i.test(ua)) return true;
  return (platform === "MacIntel" || /macintosh/i.test(ua)) && maxTouchPoints > 1;
}

export function isIOS(): boolean {
  if (typeof window === "undefined") return false;
  return isIOSLike(navigator.userAgent || "", navigator.platform || "", navigator.maxTouchPoints || 0);
}

/** UA'dan iOS/iPadOS sürümü: "OS 17_4" (iPhone/iPad UA) ya da "Version/17.4" (iPadOS masaüstü UA). */
export function parseIosVersion(ua: string): { major: number; minor: number } | null {
  const match = /\bOS (\d+)[_.](\d+)/.exec(ua) || /\bVersion\/(\d+)\.(\d+)/.exec(ua);
  if (!match) return null;
  return { major: Number(match[1]), minor: Number(match[2]) };
}

/**
 * Web Push iOS/iPadOS'ta 16.4'te geldi ve YALNIZ Ana Ekrana eklenen uygulamada çalışır.
 * Sürüm okunamazsa engelleme (null → destekli say; asıl kapı `PushManager` kontrolüdür).
 */
export function iosSupportsWebPush(ua: string): boolean {
  const version = parseIosVersion(ua);
  if (!version) return true;
  return version.major > 16 || (version.major === 16 && version.minor >= 4);
}

export type OnboardingStep = "ios_old" | "browser_warn" | "install" | "notify";

/**
 * Onboarding'in İLK adımı. iOS'ta "Chrome kullanın" uyarısı YOKTUR (doğru tarayıcı Safari;
 * kurulum Paylaş → Ana Ekrana Ekle ile yapılır) ve kurulu (standalone) değilken bildirim
 * adımına GEÇİLMEZ: Safari sekmesinde `PushManager` yoktur, izin istemek çıkmaz sokaktır.
 */
export function firstOnboardingStep(env: {
  ios: boolean;
  iosPushOk: boolean;
  browser: BrowserKind;
  standalone: boolean;
}): OnboardingStep {
  if (env.ios) {
    if (!env.iosPushOk) return "ios_old";
    return env.standalone ? "notify" : "install";
  }
  if (env.browser !== "chrome") return "browser_warn";
  return env.standalone ? "notify" : "install";
}

export function isMobileDevice(): boolean {
  if (typeof window === "undefined") return false;
  // iPadOS "Macintosh" UA'sı taşıdığı için ayrıca `isIOS()` bakılır (iPad de mobil akışa girer).
  return /android|iphone|ipad|ipod|mobile|iemobile/i.test(navigator.userAgent || "") || isIOS();
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

/** VAPID public key'i (URL-safe base64) Uint8Array'e çevir + doğrula. */
export function vapidKeyToBytes(): { ok: true; bytes: Uint8Array<ArrayBuffer> } | { ok: false; reason: string } {
  const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
  if (!key) return { ok: false, reason: "vapid_yok" };
  try {
    const clean = key.trim().replace(/-/g, "+").replace(/_/g, "/");
    const padded = clean + "=".repeat((4 - (clean.length % 4)) % 4);
    const raw = atob(padded);
    // P-256 noktası: 65 bayt (0x04 || X || Y). Farklı boyut → geçersiz anahtar.
    if (raw.length !== 65) {
      return { ok: false, reason: "vapid_key_gecersiz_boyut" };
    }
    const bytes = new Uint8Array(65);
    for (let i = 0; i < 65; i++) bytes[i] = raw.charCodeAt(i);
    return { ok: true, bytes };
  } catch {
    return { ok: false, reason: "vapid_key_gecersiz" };
  }
}

/**
 * Abonelik var mı kontrol et; yoksa oluşturup backend'e kaydeder.
 * Dönen: { ok: boolean; reason?: string; subscription?: PushSubscription }
 */
export async function ensurePushSubscription(): Promise<{ ok: boolean; reason?: string }> {
  const support = pushSupported();
  if (!support.ok) return { ok: false, reason: support.reason };

  const keyBytes = vapidKeyToBytes();
  if (!keyBytes.ok) {
    return { ok: false, reason: keyBytes.reason };
  }

  if (typeof Notification !== "undefined" && Notification.permission !== "granted") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return { ok: false, reason: "izin_verilmedi" };
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes.bytes,
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

/**
 * SESSİZ UZLAŞTIRMA (2026-09-16 denetimi) — push'un kendiliğinden susmasını önler.
 *
 * Sorun: tarayıcı push aboneliğini döndürebilir (endpoint rotasyonu, PWA yeniden
 * kurulumu, tarayıcı güncellemesi). Bu durumda backend'deki eski endpoint ölür ve
 * push SESSİZCE durur. `pushsubscriptionchange` olayı bunu yakalamak için var ama
 * Chrome onu güvenilir biçimde tetiklemez; bu yüzden uygulama açılışında aboneliği
 * uzlaştırmak gerekir.
 *
 * `ensurePushSubscription`'dan farkı: **ASLA izin istemez** (açılışta izin
 * penceresi açmak kabul edilemez). İzin zaten verilmişse mevcut aboneliği alıp
 * backend'e yeniden kaydeder; yoksa oluşturur.
 */
export async function reconcilePushSubscription(): Promise<{ ok: boolean; reason?: string }> {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return { ok: false, reason: "izin_yok" };
  }
  return ensurePushSubscription();
}

/** Backend'e kayıtlı abonelik var mı? (push sağlığını görünür kılmak için) */
export function pushPermissionState(): NotificationPermission | "unsupported" {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission;
}
