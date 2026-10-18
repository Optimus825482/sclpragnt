"use client";

import { useAppUpdates } from "../lib/serviceWorker";

/**
 * Service worker kaydı + "Yeni sürüm var — Yenile" şeridi. Layout düzeyinde (AuthGate dışında)
 * bağlanır: giriş ekranında da kayıt/sürüm denetimi çalışır. Otomatik yenileme YOK; açık emir
 * penceresi/form kaybolmasın diye yenilemeyi kullanıcı seçer.
 */
export default function AppUpdater() {
  const { pendingBuild, dismiss, reload } = useAppUpdates();
  if (!pendingBuild) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-3 z-[210] mx-auto flex max-w-md items-center gap-3 rounded-xl border border-sky-400/50 bg-bunker-950 px-4 py-3 shadow-2xl"
      style={{ top: "max(0.75rem, env(safe-area-inset-top))" }}
    >
      <div className="min-w-0 flex-1">
        <p className="font-mono text-sm font-bold text-white">Yeni sürüm var</p>
        <p className="text-xs leading-snug text-bunker-muted">Açık işlemini bitirdikten sonra yenile.</p>
      </div>
      <button type="button" onClick={dismiss} className="ui-button ui-button-secondary touch-target shrink-0">SONRA</button>
      <button type="button" onClick={reload} className="ui-button ui-button-primary touch-target shrink-0">YENİLE</button>
    </div>
  );
}
