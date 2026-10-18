"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { CURRENT_BUILD, fetchRemoteBuild, shouldOfferUpdate } from "./appVersion";
import { isChunkLoadError } from "./chunkError";

/**
 * SW adresi SABİTTİR. Derleme kimliği ve VAPID anahtarı artık URL sorgusunda değil,
 * `/sw.js` içeriğinde gömülüdür (bkz. app/sw.js/route.ts). Böylece her deploy'da dosya
 * baytları değişir ve tarayıcının kendi güncelleme denetimi yeni SW'yi bulur.
 */
export const SERVICE_WORKER_URL = "/sw.js";

/** Görünürken sürüm denetim aralığı. */
export const UPDATE_CHECK_INTERVAL_MS = 10 * 60 * 1000;
/** Üst üste tetikleyicilerde (görünür olma + online + aralık) gereksiz ağ istekleri olmasın. */
export const MIN_UPDATE_CHECK_GAP_MS = 30_000;

/** Son denetimden bu yana yeterli süre geçti mi? (`last=0` → hiç denetlenmedi) */
export function shouldRunUpdateCheck(last: number, now: number, minGapMs = MIN_UPDATE_CHECK_GAP_MS): boolean {
  return !last || now - last >= minGapMs;
}

export type AppUpdateState = {
  /** Gösterilecek bekleyen sürüm (yoksa null); şerit bunu kullanır. */
  pendingBuild: string | null;
  /** Kullanıcı "Sonra" dediyse aynı sürüm için tekrar gösterilmez. */
  dismiss: () => void;
  reload: () => void;
};

/**
 * Service worker kaydı + kurulu PWA için sürüm izleme. TEK yerden (AppUpdater, layout düzeyinde)
 * çağrılır → giriş ekranında da çalışır; hem admin hem kullanıcı kabuğu için push çalışır.
 *
 * Yeni sürüm üç yolla fark edilir: (1) `/build-id.json` kıyası, (2) yeni SW'nin `SW_VERSION`
 * mesajı, (3) deploy sonrası tembel chunk hatası. Hiçbirinde OTOMATİK YENİLEME yapılmaz —
 * açık emir penceresi/form kaybolmasın; kullanıcı şeritten kendisi yeniler.
 */
export function useAppUpdates(): AppUpdateState {
  const [pendingBuild, setPendingBuild] = useState<string | null>(null);
  const [dismissedBuild, setDismissedBuild] = useState<string | null>(null);
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null);
  const lastCheckRef = useRef(0);

  const offer = useCallback((build: string | null | undefined) => {
    if (build) setPendingBuild(build);
  }, []);

  const check = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && !shouldRunUpdateCheck(lastCheckRef.current, now)) return;
    lastCheckRef.current = now;
    // Bayt kıyaslı SW güncellemesi (yeni SW kurulursa SW_VERSION mesajı da gelir).
    try { await registrationRef.current?.update(); } catch { /* çevrimdışı: yok say */ }
    const remote = await fetchRemoteBuild();
    if (shouldOfferUpdate(CURRENT_BUILD, remote)) offer(remote);
  }, [offer]);

  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    // Gömülü sayfa (analiz iframe'i): kayıt/şerit üst pencerede zaten var; çift şerit olmasın.
    try { if (window.self !== window.top) return; } catch { return; }
    if (process.env.NODE_ENV !== "production") {
      navigator.serviceWorker
        .getRegistrations()
        .then((registrations) => registrations.forEach((registration) => registration.unregister()))
        .catch(() => undefined);
      return;
    }

    let cancelled = false;
    navigator.serviceWorker
      .register(SERVICE_WORKER_URL, { updateViaCache: "none" })
      .then((registration) => {
        if (cancelled) return;
        registrationRef.current = registration;
        void check(true);
      })
      .catch(() => undefined);

    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; build?: string } | null;
      if (data?.type === "SW_VERSION" && shouldOfferUpdate(CURRENT_BUILD, data.build)) offer(data.build);
    };
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    const onOnline = () => { void check(); };
    const onPageShow = (event: PageTransitionEvent) => { if (event.persisted) void check(true); };
    // Deploy sonrası eski sayfa tembel chunk isterse (404): yenileme önerisi.
    const onError = (event: ErrorEvent) => { if (isChunkLoadError(event.error ?? event.message)) offer("chunk-error"); };
    const onRejection = (event: PromiseRejectionEvent) => { if (isChunkLoadError(event.reason)) offer("chunk-error"); };

    navigator.serviceWorker.addEventListener("message", onMessage);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("pageshow", onPageShow);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void check();
    }, UPDATE_CHECK_INTERVAL_MS);

    return () => {
      cancelled = true;
      navigator.serviceWorker.removeEventListener("message", onMessage);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("pageshow", onPageShow);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
      window.clearInterval(interval);
    };
  }, [check, offer]);

  const dismiss = useCallback(() => setDismissedBuild(pendingBuild), [pendingBuild]);
  const reload = useCallback(() => window.location.reload(), []);

  return {
    pendingBuild: pendingBuild && pendingBuild !== dismissedBuild ? pendingBuild : null,
    dismiss,
    reload,
  };
}
