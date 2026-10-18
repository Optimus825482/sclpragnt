"use client";

import RequireAdmin from "../components/RequireAdmin";
import MaBuySignals from "../components/admin/MaBuySignals";

/**
 * Yalnız yönetici: MA BUY sinyal kaydı. Menüde YOK; yalnızca Ayarlar sayfasındaki düğmeyle açılır.
 * Hem gelişmiş (AppShell) hem basit (UserShell) kabukta çalışır; admin değilse RequireAdmin yetkisiz ekranını gösterir.
 */
export default function MaBuySignalsPage() {
  return (
    <RequireAdmin>
      <MaBuySignals />
    </RequireAdmin>
  );
}
