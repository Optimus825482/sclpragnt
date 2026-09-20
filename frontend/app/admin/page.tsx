"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "../lib/auth";
import { canViewMacdMonitor } from "../lib/macdAccess";
import RequireAdmin from "../components/RequireAdmin";

const DatabaseView = dynamic(() => import("../database/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      🗄️ Veritabanı yönetimi yükleniyor…
    </div>
  ),
  ssr: false,
});

const AuditLogsView = dynamic(() => import("../audit-logs/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      🛡️ Olay kayıtları yükleniyor…
    </div>
  ),
  ssr: false,
});

const MacdMonitorView = dynamic(() => import("../macd-monitor/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      📊 MACD Monitör yükleniyor…
    </div>
  ),
  ssr: false,
});

const UsersView = dynamic(() => import("../users/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      👥 Kullanıcı yönetimi yükleniyor…
    </div>
  ),
  ssr: false,
});

const ChatView = dynamic(() => import("../chat/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      💬 Chat merkezi yükleniyor…
    </div>
  ),
  ssr: false,
});

const SystemHealthView = dynamic(() => import("../system-health/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      🩺 Sistem sağlığı yükleniyor…
    </div>
  ),
  ssr: false,
});

export default function AdminPage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
          Yönetim Merkezi yükleniyor…
        </div>
      }
    >
      <AdminPageInner />
    </Suspense>
  );
}

function AdminPageInner() {
  const { role, username } = useAuth();
  const isAdmin = role === "admin";
  const canMacd = canViewMacdMonitor(role, username);
  const searchParams = useSearchParams();
  const router = useRouter();

  type AdminTab = "database" | "audit-logs" | "macd-monitor" | "users" | "chat" | "system-health";

  const allTabs: { key: AdminTab; label: string; icon: string; adminOnly: boolean }[] = [
    { key: "database", label: "Veritabanı", icon: "🗄️", adminOnly: true },
    { key: "audit-logs", label: "Olay Kayıtları", icon: "🛡️", adminOnly: true },
    { key: "macd-monitor", label: "MACD Monitör", icon: "📊", adminOnly: false },
    { key: "users", label: "Kullanıcı Yönetimi", icon: "👥", adminOnly: true },
    { key: "chat", label: "Chat Merkezi", icon: "💬", adminOnly: true },
    { key: "system-health", label: "Sistem Sağlığı", icon: "🩺", adminOnly: true },
  ];

  const visibleTabs = allTabs.filter((t) => (isAdmin ? true : canMacd && !t.adminOnly));

  const tabParam = searchParams.get("tab") as AdminTab | null;
  const initialTab: AdminTab =
    tabParam && visibleTabs.some((t) => t.key === tabParam)
      ? tabParam
      : isAdmin
      ? "database"
      : "macd-monitor";

  const [activeTab, setActiveTab] = useState<AdminTab>(initialTab);

  useEffect(() => {
    if (tabParam && visibleTabs.some((t) => t.key === tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam);
    }
  }, [tabParam, visibleTabs, activeTab]);

  const selectTab = (tab: AdminTab) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    router.replace(url.pathname + url.search, { scroll: false });
  };

  if (!isAdmin && !canMacd) {
    return (
      <div className="p-8 text-center">
        <div className="card max-w-md mx-auto border-neon-red/40 bg-neon-red/5 p-6">
          <p className="font-mono text-base font-bold text-neon-red">YETKİSİZ ERİŞİM</p>
          <p className="text-xs text-bunker-muted mt-2">
            Bu yönetim alanına erişmek için yönetici veya özel yetkilendirme gereklidir.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page-container max-w-7xl mx-auto space-y-6">
      {/* Yönetim Merkezi Üst Başlık & Sekmeler */}
      <header className="border-b border-bunker-800 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <h1 className="font-mono text-xl sm:text-2xl font-bold tracking-tight">
              <span className="text-neon-green">YÖNETİM</span> MERKEZİ
            </h1>
            <p className="eyebrow mt-0.5">
              Veritabanı · Olay Kayıtları · MACD Monitör · Kullanıcılar · Chat · Sistem Sağlığı
            </p>
          </div>
          <span className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-2.5 py-1 font-mono text-[11px] font-bold text-neon-green">
            {isAdmin ? "ADMIN KONTROLÜ" : "MACD ÖZEL ERİŞİM"}
          </span>
        </div>

        {/* Yatay Kayan Sekme Çubuğu */}
        <nav
          className="flex gap-2 overflow-x-auto pb-1 no-scrollbar scrollbar-none touch-pan-x"
          aria-label="Yönetim modülleri"
        >
          {visibleTabs.map((t) => {
            const isActive = activeTab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => selectTab(t.key)}
                className={`shrink-0 whitespace-nowrap flex items-center gap-2 px-3.5 py-2 rounded-lg border font-mono text-xs transition-all touch-target ${
                  isActive
                    ? "border-neon-green/60 bg-neon-green/15 text-neon-green font-bold shadow-md shadow-neon-green/5"
                    : "border-bunker-800 bg-bunker-900/80 text-bunker-muted hover:text-white hover:border-bunker-700 hover:bg-bunker-800/60"
                }`}
                aria-selected={isActive}
              >
                <span className="text-sm">{t.icon}</span>
                <span>{t.label}</span>
              </button>
            );
          })}
        </nav>
      </header>

      {/* Aktif Sekme İçeriği */}
      <div className="admin-tab-content min-w-0">
        {activeTab === "database" && isAdmin && <DatabaseView />}
        {activeTab === "audit-logs" && isAdmin && <AuditLogsView />}
        {activeTab === "macd-monitor" && <MacdMonitorView />}
        {activeTab === "users" && isAdmin && <UsersView />}
        {activeTab === "chat" && isAdmin && <ChatView />}
        {activeTab === "system-health" && isAdmin && <SystemHealthView />}
      </div>
    </div>
  );
}
