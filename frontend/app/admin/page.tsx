"use client";

import { Suspense, useMemo, type KeyboardEvent } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "../lib/auth";
import { canViewMacdMonitor } from "../lib/macdAccess";

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

const MtfScannerView = dynamic(() => import("../mtf-scanner/page"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      🧠 MTF Tarama yükleniyor…
    </div>
  ),
  ssr: false,
});

const SignalInsightsView = dynamic(() => import("../signal-insights/page"), {
  loading: () => <p role="status" className="p-12 text-center text-sm text-bunker-muted">Sinyal İzleme yükleniyor…</p>,
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

const ReportsBaselineView = dynamic(() => import("./ReportsBaselineTab"), {
  loading: () => (
    <div className="p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">
      📌 Rapor başlangıcı yükleniyor…
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

type AdminTab = "database" | "audit-logs" | "macd-monitor" | "mtf-scanner" | "signal-insights" | "users" | "chat" | "system-health" | "reports-baseline";

const ALL_ADMIN_TABS: { key: AdminTab; label: string; icon: string; adminOnly: boolean }[] = [
  { key: "database", label: "Veritabanı", icon: "🗄️", adminOnly: true },
  { key: "audit-logs", label: "Olay Kayıtları", icon: "🛡️", adminOnly: true },
  { key: "macd-monitor", label: "MACD Monitör", icon: "📊", adminOnly: false },
  { key: "mtf-scanner", label: "MTF Tarama", icon: "🧠", adminOnly: false },
  { key: "signal-insights", label: "Sinyal İzleme", icon: "🎯", adminOnly: true },
  { key: "users", label: "Kullanıcı Yönetimi", icon: "👥", adminOnly: true },
  { key: "chat", label: "Chat Merkezi", icon: "💬", adminOnly: true },
  { key: "system-health", label: "Sistem Sağlığı", icon: "🩺", adminOnly: true },
  { key: "reports-baseline", label: "Rapor Başlangıcı", icon: "📌", adminOnly: true },
];

function AdminPageInner() {
  const { role, username } = useAuth();
  const isAdmin = role === "admin";
  const canMacd = canViewMacdMonitor(role, username);
  const searchParams = useSearchParams();
  const router = useRouter();

  const visibleTabs = useMemo(
    () => ALL_ADMIN_TABS.filter((t) => (isAdmin ? true : canMacd && !t.adminOnly)),
    [isAdmin, canMacd]
  );

  const tabParam = searchParams.get("tab") as AdminTab | null;
  const activeTab: AdminTab =
    tabParam && visibleTabs.some((t) => t.key === tabParam)
      ? tabParam
      : isAdmin
      ? "database"
      : "macd-monitor";

  const selectTab = (tab: AdminTab) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", tab);
    router.replace(`/admin?${params}`, { scroll: false });
  };

  const focusTab = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = visibleTabs.length - 1;
    let next: number;
    switch (event.key) {
      case "ArrowLeft": next = index === 0 ? last : index - 1; break;
      case "ArrowRight": next = index === last ? 0 : index + 1; break;
      case "Home": next = 0; break;
      case "End": next = last; break;
      default: return;
    }
    event.preventDefault();
    document.getElementById(`admin-tab-${visibleTabs[next].key}`)?.focus();
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
          </div>
          <span className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-2.5 py-1 font-mono text-[11px] font-bold text-neon-green">
            {isAdmin ? "ADMIN KONTROLÜ" : "MACD ÖZEL ERİŞİM"}
          </span>
        </div>

        {/* Yatay Kayan Sekme Çubuğu */}
        <div role="tablist"
          className="flex gap-2 overflow-x-auto pb-1 no-scrollbar scrollbar-none touch-pan-x"
          aria-label="Yönetim modülleri"
        >
          {visibleTabs.map((t, index) => {
            const isActive = activeTab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                id={`admin-tab-${t.key}`}
                role="tab"
                tabIndex={isActive ? 0 : -1}
                aria-controls={`admin-panel-${t.key}`}
                onClick={() => selectTab(t.key)}
                onKeyDown={(event) => focusTab(event, index)}
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
        </div>
      </header>

      {/* Aktif Sekme İçeriği */}
      {visibleTabs.filter((t) => t.key !== activeTab).map((t) => (
        <div key={t.key} role="tabpanel" id={`admin-panel-${t.key}`} aria-labelledby={`admin-tab-${t.key}`} hidden />
      ))}
      <div role="tabpanel" id={`admin-panel-${activeTab}`} aria-labelledby={`admin-tab-${activeTab}`} tabIndex={0} className="admin-tab-content min-w-0">
        {activeTab === "database" && isAdmin && <DatabaseView />}
        {activeTab === "audit-logs" && isAdmin && <AuditLogsView />}
        {activeTab === "macd-monitor" && <MacdMonitorView />}
        {activeTab === "mtf-scanner" && <MtfScannerView />}
        {activeTab === "signal-insights" && isAdmin && <SignalInsightsView />}
        {activeTab === "users" && isAdmin && <UsersView />}
        {activeTab === "chat" && isAdmin && <ChatView />}
        {activeTab === "system-health" && isAdmin && <SystemHealthView />}
        {activeTab === "reports-baseline" && isAdmin && <ReportsBaselineView />}
      </div>
    </div>
  );
}
