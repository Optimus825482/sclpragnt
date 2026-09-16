"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import RadarAlertModal from "./RadarAlertModal";
import { reconcilePushSubscription } from "../lib/push";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const embeddedAnalysis = pathname === "/symbol-analysis" && searchParams.get("embedded") === "1";

  // PUSH-RESILIENCE (2026-09-16): açılışta aboneliği SESSİZCE uzlaştır.
  //
  // Tarayıcı push aboneliğini döndürebilir (endpoint rotasyonu / PWA yeniden
  // kurulumu) → backend'deki eski endpoint ölür → ölü abonelik temizlenir ve push
  // bir daha HİÇ gönderilmez; kullanıcı bunu fark etmez. `pushsubscriptionchange`
  // olayı bunu yakalamak için tasarlandı ama Chrome onu güvenilir tetiklemez;
  // bu yüzden her açılışta mevcut aboneliği backend'e yeniden yazıyoruz.
  //
  // ASLA izin istemez: `reconcilePushSubscription` yalnız izin ZATEN verilmişse
  // çalışır (izin penceresi açılışta gösterilemez). Hata sessizce yutulur —
  // push uzlaştırması kritik yol değil.
  useEffect(() => {
    void reconcilePushSubscription().catch(() => undefined);
  }, []);

  if (embeddedAnalysis) {
    return <main className="min-h-screen overflow-y-auto"><div className="content-shell">{children}</div></main>;
  }
  return <div className="flex min-h-screen"><Sidebar /><main className="flex-1 min-w-0 min-h-screen overflow-y-auto"><TopBar /><div className="content-shell">{children}</div></main><RadarAlertModal /></div>;
}
