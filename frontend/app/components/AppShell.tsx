"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import RadarAlertModal from "./RadarAlertModal";
import BottomNav from "./BottomNav";
import { reconcilePushSubscription } from "../lib/push";

const CURRENT_BUILD = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const embeddedAnalysis = pathname === "/symbol-analysis" && searchParams.get("embedded") === "1";

  // PUSH-RESILIENCE (2026-09-16): açılışta aboneliği SESSİZCE uzlaştır.
  useEffect(() => {
    void reconcilePushSubscription().catch(() => undefined);
  }, []);

  // SW VERSİYON KONTROLÜ (2026-09-16)
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
  return (
    <div className="flex min-h-screen">
      <div data-sidebar><Sidebar /></div>
      <main className="flex-1 min-w-0 min-h-screen overflow-y-auto">
        <div data-topbar><TopBar /></div>
        <div className="content-shell">{children}</div>
      </main>
      <BottomNav />
      <RadarAlertModal />
    </div>
  );
}
