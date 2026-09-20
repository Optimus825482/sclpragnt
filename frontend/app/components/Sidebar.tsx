"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "./ui";
import { apiFetch } from "../lib/api";
import { toMs } from "../lib/format";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import SymbolLink from "./SymbolLink";
import { useAuth } from "../lib/auth";
import { canViewMacdMonitor } from "../lib/macdAccess";
import { ML_PROB_CLASS, ML_PROB_TITLE, formatMlProbability } from "../lib/mlProbability";

const MENU_ITEMS = [
    { href: "/profile", label: "Profil", icon: "👤", desc: "Hesap ve şifre" },
    { href: "/portfolio", label: "Sanal Portföy", icon: "💼", desc: "Canlı sanal portföy ve otonom işlemler" },
    { href: "/monitoring", label: "Radar", icon: "📡", desc: "Otonom izleme ve hız avcısı" },
    { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
    { href: "/binance-tr", label: "Binance TR", icon: "🏛️", desc: "Kendi Binance TR hesabında canlı işlem" },
    { href: "/reports", label: "Raporlar", icon: "📋", desc: "Sinyal ve işlem raporları" },
    { href: "/chat", label: "Chat", icon: "💬", desc: "Uzman trader LLM asistanı" },
    { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu", adminOnly: true },
    { href: "/admin", label: "Yönetim", icon: "🛠️", desc: "Veritabanı, kayıtlar, MACD monitör", requiresStaff: true },
];
const formatNotificationDate = (value: unknown) => {
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(toMs(numeric)) : new Date(String(value || ""));
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("tr-TR");
};

export default function Sidebar() {
    const pathname = usePathname();
    const { username, role, logout } = useAuth();
    const isAdmin = role === "admin";
    const canViewMacd = canViewMacdMonitor(role, username);
    const [open, setOpen] = useState(false);
    const [busyLogout, setBusyLogout] = useState(false);
    const [installEvent, setInstallEvent] = useState<any>(null);
    const [installed, setInstalled] = useState(false);
    const [notifications, setNotifications] = useState<any[]>([]);
    const [unread, setUnread] = useState(0);
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    const [health, setHealth] = useState<any>(null);
    const liveStatus = useLiveStatus();
    const onLiveMessage = useCallback((message: any) => {
        if (message.type !== "alert") return;
        const item = { ...(message.data || {}), id: message.data?.id || `${Date.now()}`, triggered_at: message.data?.triggered_at || Date.now() / 1000 };
        setNotifications((current) => [item, ...current.filter((entry) => entry.id !== item.id)].slice(0, 30));
        setUnread((count) => count + 1);
    }, []);
    useLiveMessages(onLiveMessage);
    useEffect(() => {
        if ("serviceWorker" in navigator) {
            if (process.env.NODE_ENV === "production") {
                // PUSH-RESILIENCE (2026-09-16): SW'ye VAPID public key'i SORGU ile
                // geçir. Service worker bundle'ı `process.env` göremez; abonelik
                // döndüğünde (`pushsubscriptionchange`) yeniden abone olmak için
                // anahtara ihtiyaç duyar. Anahtar, abonelik kadar uzun olmayan
                // base64url olduğundan sorgu parametresi güvenli.
                const vapid = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";
                navigator.serviceWorker.register(
                    `/sw.js?v=${process.env.NEXT_PUBLIC_BUILD_ID || "dev"}${vapid ? `&vapid=${encodeURIComponent(vapid)}` : ""}`,
                ).catch(() => undefined);
            }
            else navigator.serviceWorker.getRegistrations().then((registrations) => registrations.forEach((registration) => registration.unregister()));
        }
        const handler = (event: Event) => { event.preventDefault(); setInstallEvent(event); };
        window.addEventListener("beforeinstallprompt", handler);
        const installedHandler = () => setInstalled(true);
        window.addEventListener("appinstalled", installedHandler);
        return () => {
            window.removeEventListener("beforeinstallprompt", handler);
            window.removeEventListener("appinstalled", installedHandler);
        };
    }, []);
    useEffect(() => setOpen(false), [pathname]);
    useEffect(() => {
        if (!open) return;
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setOpen(false);
        };
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            document.body.style.overflow = prevOverflow;
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open]);
    useEffect(() => {
        const handleOpen = () => setOpen(true);
        window.addEventListener("open-mobile-menu", handleOpen);
        return () => window.removeEventListener("open-mobile-menu", handleOpen);
    }, []);
    useEffect(() => {
        const load = () => apiFetch("/api/alerts")
            .then((data) => setNotifications((data.events || []).slice(0, 30)))
            .catch(() => undefined);
        load();
    }, []);
    const loadHealth = useCallback(() => {
        apiFetch("/api/system/health").then(setHealth).catch(() => setHealth(null));
    }, []);
    useEffect(() => { loadHealth(); }, [loadHealth]);
    useVisibleInterval(loadHealth, 10_000);
    const isStandalone = typeof window !== "undefined" && (window.matchMedia?.("(display-mode: standalone)").matches || (window.navigator as any)?.standalone === true);
    const install = async () => {
        if (!installEvent) return;
        await installEvent.prompt();
        setInstallEvent(null);
    };

    return (
        <>
            <Button className="mobile-menu-button" onClick={() => setOpen(true)} aria-label="Menüyü aç">☰</Button>
            {open && <button className="mobile-menu-backdrop" onClick={() => setOpen(false)} aria-label="Menüyü kapat" />}
        <aside className={`app-sidebar w-64 max-w-[85vw] md:w-56 shrink-0 border-r border-bunker-800 bg-bunker-900/95 flex flex-col h-screen sticky top-0 ${open ? "is-open" : ""}`}>
            <div className="p-4 sm:p-5 border-b border-bunker-800">
                <div className="flex items-center justify-between">
                    <Link href="/" onClick={() => setOpen(false)} className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-neon-green animate-pulse" />
                        <span className="font-mono text-sm font-bold tracking-tight">
                            SCALPER<span className="text-neon-green">AGENT</span>
                        </span>
                    </Link>
                    <button
                        type="button"
                        onClick={() => setOpen(false)}
                        className="md:hidden flex items-center justify-center w-8 h-8 rounded-lg text-bunker-muted hover:text-white hover:bg-bunker-800 transition-colors"
                        aria-label="Menüyü kapat"
                    >
                        ✕
                    </button>
                </div>
                <p className="eyebrow mt-2">V4 · Paper Trading</p>
                <button
                    type="button"
                    onClick={() => { setNotificationsOpen(true); setUnread(0); }}
                    className="relative mt-3.5 flex w-full items-center justify-between rounded-lg border border-bunker-700 bg-bunker-950/70 px-3 py-2 text-left transition-colors hover:border-neon-green/50"
                    aria-label={`Bildirimleri aç${unread ? `, ${unread} yeni bildirim` : ""}`}
                >
                    <span className="flex items-center gap-2 font-mono text-xs text-white"><span className="text-lg">🔔</span> BİLDİRİMLER</span>
                    {unread > 0 && <span className="min-w-5 rounded-full bg-neon-red px-1.5 py-0.5 text-center font-mono text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
                </button>
            </div>

            <nav className="flex-1 overflow-y-auto p-3 space-y-1">
                {MENU_ITEMS.filter((m) =>
                    m.adminOnly ? isAdmin : m.requiresStaff ? (isAdmin || canViewMacd) : true
                ).map((m) => {
                    const active = pathname === m.href || (m.href === "/admin" && ["/admin", "/database", "/audit-logs", "/macd-monitor", "/users", "/chat"].includes(pathname));
                    return (
                        <div key={m.href}>
                        <Link
                            href={m.href}
                            onClick={() => setOpen(false)}
                            className={`block px-3 py-2.5 rounded-lg border transition-colors touch-target ${active
                                ? "bg-neon-green/10 border-neon-green/30"
                                : "border-transparent hover:bg-bunker-800/60 hover:border-bunker-700"
                                }`}
                        >
                            <span className="flex items-center gap-2.5">
                                <span className="text-sm">{m.icon}</span>
                                <span className={`font-mono text-sm ${active ? "text-neon-green font-bold" : "text-white"}`}>
                                    {m.label}
                                </span>
                            </span>
                            <span className="block text-[11px] text-bunker-muted mt-0.5 ml-7">{m.desc}</span>
                        </Link>
                        </div>
                    );
                })}
            </nav>

            <div className="p-4 border-t border-bunker-800">
                {username && (
                    <div className="mb-3">
                        <Link href="/profile" title="Profili düzenle (şifre güncelle)" className="mb-1 flex items-center gap-1.5 rounded-lg border border-transparent px-1 py-1 font-mono text-[11px] text-bunker-muted transition-colors hover:border-bunker-700 hover:bg-bunker-800/60 hover:text-white">
                            <span className="w-1.5 h-1.5 rounded-full bg-neon-green" />
                            <span className="truncate">{username}</span>
                            <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${isAdmin ? "border border-neon-green/50 text-neon-green" : "border border-bunker-600 text-bunker-muted"}`}>{isAdmin ? "ADMIN" : "USER"}</span>
                            <span className="ml-auto text-[10px] opacity-60">⚙</span>
                        </Link>
                        <button
                            type="button"
                            onClick={async () => { setBusyLogout(true); try { await logout?.(); } finally { setBusyLogout(false); } }}
                            disabled={busyLogout}
                            className="flex w-full items-center justify-center gap-2 rounded-lg border border-bunker-700 bg-bunker-950/70 px-3 py-2 font-mono text-[11px] font-bold text-bunker-muted transition-colors hover:border-neon-red/60 hover:bg-neon-red/10 hover:text-neon-red disabled:opacity-50"
                            title="Oturumu kapat ve giriş ekranına dön"
                        >
                            {busyLogout ? "ÇIKILIYOR…" : "⏻ OTURUMU KAPAT"}
                        </button>
                    </div>
                )}
                <Button variant={installEvent ? "primary" : "secondary"} onClick={install} disabled={!installEvent} className="w-full mb-4">⬇ {installEvent ? "UYGULAMA OLARAK YÜKLE" : "YÜKLEME İÇİN TARAYICI MENÜSÜ"}</Button>
                {!installed && !installEvent && !isStandalone && (
                    <div className="mb-4 rounded-lg border border-bunker-700 bg-bunker-900/70 p-3">
                        <p className="font-mono text-xs font-bold text-white">📱 UYGULAMA OLARAK YÜKLE</p>
                        <p className="mt-1 text-[11px] leading-relaxed text-bunker-muted">
                            {/iPad|iPhone|iPod/.test(navigator.userAgent)
                                ? "Tarayıcıda Paylaş (⎋) → “Ana Ekrana Ekle” ile kurun."
                                : "Butonu kullanarak uygulamayı cihazınıza kurun."}
                        </p>
                    </div>
                )}
                <Link
                    href="/system-health"
                    onClick={() => setOpen(false)}
                    className={`group block rounded-lg border p-2.5 transition-all ${
                        pathname === "/system-health"
                            ? "border-neon-green/50 bg-neon-green/10"
                            : "border-bunker-800 bg-bunker-950/60 hover:border-bunker-700 hover:bg-bunker-900/80"
                    }`}
                    title="Detaylı sistem sağlığını görüntüle"
                >
                    <div className="flex items-center justify-between">
                        <p className="eyebrow group-hover:text-white transition-colors">SİSTEM SAĞLIĞI</p>
                        <span className="font-mono text-[10px] text-bunker-muted group-hover:text-neon-green transition-colors">Detay →</span>
                    </div>
                    <p className={`font-mono text-xs mt-1 flex items-center gap-1.5 ${health?.status === "ok" && liveStatus === "open" ? "text-neon-green" : "text-yellow-300"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${health?.status === "ok" && liveStatus === "open" ? "bg-neon-green animate-pulse" : "bg-yellow-300"}`} />
                        {health ? `${String(health.status || "bilinmiyor").toUpperCase()} · WS ${liveStatus === "open" ? "BAĞLI" : "KAPALI"}` : "BAĞLANTI BEKLENİYOR"}
                    </p>
                    <p className="font-mono text-[10px] text-bunker-muted mt-0.5">Canlı servis & altyapı durumu</p>
                </Link>
                <p className="mt-2 font-mono text-[9px] text-bunker-muted/60" title="Build ID — eğer güncelleme sonrası bu değişmişse yeni sürüm yüklenmiştir">
                  ● v{typeof window !== "undefined" ? (document.documentElement.dataset.buildId || process.env.NEXT_PUBLIC_BUILD_ID || "dev") : (process.env.NEXT_PUBLIC_BUILD_ID || "dev")}
                </p>
            </div>
        </aside>
        {notificationsOpen && <div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4" onClick={() => setNotificationsOpen(false)}>
            <section className="w-full max-w-xl max-h-[90vh] flex flex-col overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notifications-title">
                <div className="flex shrink-0 items-center justify-between border-b border-bunker-800 px-5 py-4">
                    <div><p className="eyebrow">CANLI MERKEZ</p><h2 id="notifications-title" className="font-mono text-lg font-bold text-white">Bildirimler</h2></div>
                    <button type="button" onClick={() => setNotificationsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Bildirimleri kapat">✕</button>
                </div>
                <div className="max-h-[75vh] overflow-y-auto p-4">
                    {notifications.length === 0 ? <p className="py-8 text-center font-mono text-sm text-bunker-muted">Henüz bildirim yok.</p> : <div className="space-y-2">{notifications.map((item, index) => <article key={item.id || index} className="rounded-lg border border-bunker-800 bg-bunker-900/70 p-3"><div className="flex items-start justify-between gap-3">{item.symbol ? <SymbolLink symbol={item.symbol} className="font-bold text-neon-green hover:text-white" /> : <span className="font-mono text-sm font-bold text-neon-green">SİSTEM</span>}<time className="font-mono text-[10px] text-bunker-muted">{formatNotificationDate(item.triggered_at)}</time></div><p className="mt-1 text-sm text-white">{item.message || item.reason || "Yeni alarm bildirimi"}</p>{item.ml_hit_probability != null && <span className={`mt-1 inline-block ${ML_PROB_CLASS}`} title={ML_PROB_TITLE}>ML {formatMlProbability(item.ml_hit_probability)}</span>}</article>)}</div>}
                </div>
            </section>
        </div>}
        </>
    );
}

