"use client";

import { usePathname, useSearchParams } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const embeddedAnalysis = pathname === "/symbol-analysis" && searchParams.get("embedded") === "1";

  if (embeddedAnalysis) {
    return <main className="min-h-screen overflow-y-auto"><div className="content-shell">{children}</div></main>;
  }
  return <div className="flex min-h-screen"><Sidebar /><main className="flex-1 min-w-0 min-h-screen overflow-y-auto"><TopBar /><div className="content-shell">{children}</div></main></div>;
}
