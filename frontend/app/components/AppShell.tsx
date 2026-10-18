"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import PortfolioBand from "./PortfolioBand";
import RadarAlertModal from "./RadarAlertModal";
import BottomNav from "./BottomNav";
import { reconcilePushSubscription } from "../lib/push";
import UserShell from "./user/UserShell";
import { useIsUserView } from "../lib/adminView";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const userView = useIsUserView();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const embeddedAnalysis = pathname === "/symbol-analysis" && searchParams.get("embedded") === "1";

  // PUSH-RESILIENCE (2026-09-16): açılışta aboneliği SESSİZCE uzlaştır.
  useEffect(() => {
    void reconcilePushSubscription().catch(() => undefined);
  }, []);

  if (userView && !embeddedAnalysis) {
    return <UserShell>{children}</UserShell>;
  }
  if (embeddedAnalysis) {
    return <main className="min-h-screen overflow-y-auto"><div className="content-shell">{children}</div></main>;
  }
  return (
    <div className="flex min-h-screen">
      <div data-sidebar><Sidebar /></div>
      <main className="flex-1 min-w-0 min-h-screen overflow-y-auto">
        <div data-topbar><TopBar /><PortfolioBand /></div>
        <div className="content-shell">{children}</div>
      </main>
      <BottomNav />
      <RadarAlertModal />
    </div>
  );
}
