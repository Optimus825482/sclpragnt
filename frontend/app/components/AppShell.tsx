"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import RadarAlertModal from "./RadarAlertModal";
import { reconcilePushSubscription } from "../lib/push";

const CURRENT_BUILD = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

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

  // SW VERSİYON KONTROLÜ (2026-09-16): yeni bir deploy sunucuya inince
  // NEXT_PUBLIC_BUILD_ID değişir → sw.js URL'i (`?v=<YENI_BUILD>`) değişir →
  // tarayıcı yeni SW'i indirip kurar → `activate` event'inde bize
  // `{type:"SW_VERSION", build}` mesajı gönderir. Biz bu mesajı alınca ve build
  // farklıysa sayfayı yenileriz; böylece eski JS/HTML yerine yeni asset'ler
  // yüklenir. Kullanıcı hard refresh yapmaz. İlk yüklemede (build eşit) veya
  // mesaj yoksa yenilemez. sessionStorage ile "bu build için zaten yenilendi"
  // bayrağı tutulur ki döngü oluşmasın (yenileme sonrası yeni sayfa yine aynı
  // mesajı görse bile yeniden yenilenmez).
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || data.type !== "SW_VERSION") return;
      if (data.build === CURRENT_BUILD) return;
      const flag = `scalper_sw_reloaded_${data.build}`;
      if (typeof sessionStorage !== "undefined" && sessionStorage.getItem(flag)) return;
      if (typeof sessionStorage !== "undefined") sessionStorage.setItem(flag, "1");
      if (typeof window !== "undefined") window.location.reload();
    }
    if (typeof navigator !== "undefined" && navigator.serviceWorker) {
      navigator.serviceWorker.addEventListener("message", onMessage);
      return () => { try { navigator.serviceWorker.removeEventListener("message", onMessage); } catch { /* yok say */ } };
    }
  }, []);

  if (embeddedAnalysis) {
    return <main className="min-h-screen overflow-y-auto"><div className="content-shell">{children}</div></main>;
  }
  return <div className="flex min-h-screen"><Sidebar /><main className="flex-1 min-w-0 min-h-screen overflow-y-auto"><TopBar /><div className="content-shell">{children}</div></main><RadarAlertModal /></div>;
}
