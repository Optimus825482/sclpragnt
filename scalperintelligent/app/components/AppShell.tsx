"use client";

import type { ReactNode } from "react";
import { useLiveConnection } from "../lib/liveSocket";
import { WatchlistProvider } from "../lib/watchlist";
import TopNav from "./TopNav";
import LiveNotificationToast from "./LiveNotificationToast";

/**
 * Oturum açılmış kabuk: AuthGate altında BİR KEZ mount edilen paylaşımlı
 * sağlayıcılar (favori listesi), kalıcı WS bağlantısı ve bildirim toast'u.
 * Sayfalar bunları ayrı ayrı kurmaz.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  useLiveConnection();
  return (
    <WatchlistProvider>
      <TopNav />
      <div className="mx-auto max-w-[1600px] px-3 py-4 sm:px-6 sm:py-6">
        <main className="min-w-0">{children}</main>
      </div>
      <LiveNotificationToast />
    </WatchlistProvider>
  );
}
