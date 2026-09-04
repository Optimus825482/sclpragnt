"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "./ui";
import { apiFetch } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import SymbolLink from "./SymbolLink";
import { useAuth } from "../lib/auth";

const MENU_BASE = [
    { href: "/portfolio", label: "Portföy", icon: "💼", desc: "Canlı portföy ve otonom işlem takibi" },
    { href: "/reports", label: "Raporlar", icon: "📋", desc: "Sinyal ve işlem raporları" },
    { href: "/monitoring", label: "Radar", icon: "📡", desc: "Otonom izleme ve hız avcısı" },
    { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
    { href: "/profile", label: "Profil", icon: "👤", desc: "Hesap ve şifre" },
];
// Admin-only menü öğeleri: normal kullanıcılar göremez.
const MENU_ADMIN = [
    { href: "/users", label: "Kullanıcı Yönetimi", icon: "👥", desc: "Kullanıcı ekle/düzenle/sil" },
    { href: "/audit-logs", label: "Olay Kayıtları", icon: "🛡", desc: "Giriş ve kullanıcı hareketleri" },
    { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu" },
    { href: "/database", label: "Veritabanı", icon: "🗄️", desc: "Tablo verileri, CSV/SQL indirme" },
    { href: "/chat", label: "Chat", icon: "💬", desc: "LLM chat merkezi (admin)" },
];
const formatNotificationDate = (value: unknown) => {
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric) : new Date(String(value || ""));
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("tr-TR");
};

export default function Sidebar() {
    const pathname = usePathname();
    const { username, role } = useAuth();
    const isAdmin = role === "admin";
    const [open, setOpen] = useState(false);
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
            if (process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js?v=13").catch(() => undefined);
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
        const load = () => apiFetch("/api/alerts")
            .then((data) => setNotifications((data.events || []).slice(0, 30)))
            .catch(() => undefined);
        load();
    }, []);
    useEffect(() => {
        const load = () => apiFetch("/api/system/health").then(setHealth).catch(() => setHealth(null));
        load();
        const timer = window.setInterval(load, 10_000);
        return () => window.clearInterval(timer);
    }, []);
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
        <aside className={`app-sidebar w-56 shrink-0 border-r border-bunker-800 bg-bunker-900/95 flex flex-col h-screen sticky top-0 ${open ? "is-open" : ""}`}>
            <div className="p-5 border-b border-bunker-800">
                <Link href="/" className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-neon-green animate-pulse" />
                    <span className="font-mono text-sm font-bold tracking-tight">
                        SCALPER<span className="text-neon-green">AGENT</span>
                    </span>
                </Link>
                <p className="eyebrow mt-2">V4 · Paper Trading</p>
                <button
                    type="button"
                    onClick={() => { setNotificationsOpen(true); setUnread(0); }}
                    className="relative mt-4 flex w-full items-center justify-between rounded-lg border border-bunker-700 bg-bunker-950/70 px-3 py-2 text-left transition-colors hover:border-neon-green/50"
                    aria-label={`Bildirimleri aç${unread ? `, ${unread} yeni bildirim` : ""}`}
                >
                    <span className="flex items-center gap-2 font-mono text-xs text-white"><span className="text-lg">🔔</span> BİLDİRİMLER</span>
                    {unread > 0 && <span className="min-w-5 rounded-full bg-neon-red px-1.5 py-0.5 text-center font-mono text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
                </button>
            </div>

            <nav className="flex-1 overflow-y-auto p-3 space-y-1">
                {[...MENU_BASE, ...(isAdmin ? MENU_ADMIN : [])].map((m) => {
                    const active = pathname === m.href;
                    return (
                        <div key={m.href}>
                        <Link
                            href={m.href}
                            className={`block px-3 py-2.5 rounded-lg border transition-colors ${active
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
                        {(m as any).children && (active || open) && <div className="ml-8 mt-1 space-y-1">{(m as any).children.map((child:any) => <Link key={child.href} href={child.href} className={`block px-2 py-1 rounded font-mono text-[11px] ${pathname === "/portfolio" && typeof window !== "undefined" && window.location.search.includes("tab=history") ? "text-neon-green" : "text-bunker-muted hover:text-white"}`}>↳ {child.label}</Link>)}</div>}
                        </div>
                    );
                })}
            </nav>

            <div className="p-4 border-t border-bunker-800">
                {username && (
                    <Link href="/profile" title="Profili düzenle (şifre güncelle)" className="mb-2 flex items-center gap-1.5 rounded-lg border border-transparent px-1 py-1 font-mono text-[11px] text-bunker-muted transition-colors hover:border-bunker-700 hover:bg-bunker-800/60 hover:text-white">
                        <span className="w-1.5 h-1.5 rounded-full bg-neon-green" />
                        <span className="truncate">{username}</span>
                        <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${isAdmin ? "border border-neon-green/50 text-neon-green" : "border border-bunker-600 text-bunker-muted"}`}>{isAdmin ? "ADMIN" : "USER"}</span>
                        <span className="ml-auto text-[10px] opacity-60">⚙</span>
                    </Link>
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
                <p className="eyebrow">SİSTEM DURUMU</p>
                <p className={`font-mono text-xs mt-2 flex items-center gap-1.5 ${health?.status === "ok" && liveStatus === "open" ? "text-neon-green" : "text-yellow-300"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${health?.status === "ok" && liveStatus === "open" ? "bg-neon-green animate-pulse" : "bg-yellow-300"}`} />
                    {health ? `${String(health.status || "bilinmiyor").toUpperCase()} · WS ${liveStatus === "open" ? "BAĞLI" : "KAPALI"}` : "BAĞLANTI BEKLENİYOR"}
                </p>
                <p className="font-mono text-[11px] text-bunker-muted mt-1">Paylaşılan güvenli canlı kanal</p>
                <p className="mt-2 font-mono text-[9px] text-bunker-muted/60" title="Build ID — eğer güncelleme sonrası bu değişmişse yeni sürüm yüklenmiştir">
                  ● v{typeof window !== "undefined" ? (document.documentElement.dataset.buildId || process.env.NEXT_PUBLIC_BUILD_ID || "dev") : (process.env.NEXT_PUBLIC_BUILD_ID || "dev")}
                </p>
            </div>
        </aside>
        {notificationsOpen && <div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4" onClick={() => setNotificationsOpen(false)}>
            <section className="w-full max-w-xl overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notifications-title">
                <div className="flex items-center justify-between border-b border-bunker-800 px-5 py-4">
                    <div><p className="eyebrow">CANLI MERKEZ</p><h2 id="notifications-title" className="font-mono text-lg font-bold text-white">Bildirimler</h2></div>
                    <button type="button" onClick={() => setNotificationsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Bildirimleri kapat">✕</button>
                </div>
                <div className="max-h-[65vh] overflow-y-auto p-4">
                    {notifications.length === 0 ? <p className="py-8 text-center font-mono text-sm text-bunker-muted">Henüz bildirim yok.</p> : <div className="space-y-2">{notifications.map((item, index) => <article key={item.id || index} className="rounded-lg border border-bunker-800 bg-bunker-900/70 p-3"><div className="flex items-start justify-between gap-3">{item.symbol ? <SymbolLink symbol={item.symbol} className="font-bold text-neon-green hover:text-white" /> : <span className="font-mono text-sm font-bold text-neon-green">SİSTEM</span>}<time className="font-mono text-[10px] text-bunker-muted">{formatNotificationDate(item.triggered_at)}</time></div><p className="mt-1 text-sm text-white">{item.message || item.reason || "Yeni alarm bildirimi"}</p>{item.ml_hit_probability != null && <span className={`mt-1 inline-block rounded border px-1.5 py-0.5 font-mono text-[10px] ${Number(item.ml_hit_probability) >= 0.6 ? 'border-neon-green/40 bg-neon-green/10 text-neon-green' : Number(item.ml_hit_probability) >= 0.45 ? 'border-yellow-300/40 bg-yellow-300/10 text-yellow-300' : 'border-neon-red/40 bg-neon-red/10 text-neon-red'}`}>ML %{Math.round(Number(item.ml_hit_probability) * 100)}</span>}</article>)}</div>}
                </div>
            </section>
        </div>}
        </>
    );
}

