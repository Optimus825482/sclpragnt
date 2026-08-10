"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "./ui";
import { API_BASE, WS_BASE } from "../lib/api";

const MENU = [
    { href: "/chat", label: "Chat", icon: "✦", desc: "LLM sohbet merkezi" },
    { href: "/", label: "Scalping", icon: "⚡", desc: "Canlı terminal" },
    { href: "/portfolio", label: "Portföy", icon: "📊", desc: "Varlıklar & PnL", children: [{ href: "/portfolio?tab=history", label: "İşlem Geçmişi" }] },
    { href: "/gainer-radar", label: "Gainer Radar", icon: "🎯", desc: "Fırsat tarayıcı" },
    { href: "/alerts", label: "Alarmlar", icon: "🔔", desc: "Fiyat ve paper giriş alarmları" },
    { href: "/reports", label: "Raporlar", icon: "📋", desc: "Performans analizi" },
    { href: "/backtest", label: "Backtest", icon: "🧪", desc: "Strateji test lab" },
    { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
    { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu" }
];
const formatNotificationDate = (value: unknown) => {
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric) : new Date(String(value || ""));
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("tr-TR");
};

export default function Sidebar() {
    const pathname = usePathname();
    const [open, setOpen] = useState(false);
    const [installEvent, setInstallEvent] = useState<any>(null);
    const [notifications, setNotifications] = useState<any[]>([]);
    const [unread, setUnread] = useState(0);
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    useEffect(() => {
        if ("serviceWorker" in navigator) {
            if (process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js").catch(() => undefined);
            else navigator.serviceWorker.getRegistrations().then((registrations) => registrations.forEach((registration) => registration.unregister()));
        }
        const handler = (event: Event) => { event.preventDefault(); setInstallEvent(event); };
        window.addEventListener("beforeinstallprompt", handler);
        return () => window.removeEventListener("beforeinstallprompt", handler);
    }, []);
    useEffect(() => setOpen(false), [pathname]);
    useEffect(() => {
        let ws: WebSocket | null = null;
        const load = () => fetch(`${API_BASE}/api/alerts`, { cache: "no-store" })
            .then((response) => response.json())
            .then((data) => setNotifications((data.events || []).slice(0, 30)))
            .catch(() => undefined);
        load();
        try {
            ws = new WebSocket(`${WS_BASE}/ws`);
            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (message.type !== "alert") return;
                    const item = { ...(message.data || {}), id: message.data?.id || `${Date.now()}`, triggered_at: message.data?.triggered_at || Date.now() / 1000 };
                    setNotifications((current) => [item, ...current.filter((entry) => entry.id !== item.id)].slice(0, 30));
                    setUnread((count) => count + 1);
                } catch { /* malformed websocket event */ }
            };
        } catch { /* websocket is optional */ }
        return () => ws?.close();
    }, []);
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

            <nav className="flex-1 p-3 space-y-1">
                {MENU.map((m) => {
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
                <Button variant={installEvent ? "primary" : "secondary"} onClick={install} disabled={!installEvent} className="w-full mb-4">⬇ {installEvent ? "UYGULAMA OLARAK YÜKLE" : "YÜKLEME İÇİN TARAYICI MENÜSÜ"}</Button>
                <p className="eyebrow">SİSTEM DURUMU</p>
                <p className="font-mono text-xs text-neon-green mt-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" /> Çalışıyor
                </p>
                <p className="font-mono text-[11px] text-bunker-muted mt-1">ws://localhost:8004</p>
            </div>
        </aside>
        {notificationsOpen && <div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4" onClick={() => setNotificationsOpen(false)}>
            <section className="w-full max-w-xl overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notifications-title">
                <div className="flex items-center justify-between border-b border-bunker-800 px-5 py-4">
                    <div><p className="eyebrow">CANLI MERKEZ</p><h2 id="notifications-title" className="font-mono text-lg font-bold text-white">Bildirimler</h2></div>
                    <button type="button" onClick={() => setNotificationsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Bildirimleri kapat">✕</button>
                </div>
                <div className="max-h-[65vh] overflow-y-auto p-4">
                    {notifications.length === 0 ? <p className="py-8 text-center font-mono text-sm text-bunker-muted">Henüz bildirim yok.</p> : <div className="space-y-2">{notifications.map((item, index) => <article key={item.id || index} className="rounded-lg border border-bunker-800 bg-bunker-900/70 p-3"><div className="flex items-start justify-between gap-3"><span className="font-mono text-sm font-bold text-neon-green">{item.symbol || "SİSTEM"}</span><time className="font-mono text-[10px] text-bunker-muted">{formatNotificationDate(item.triggered_at)}</time></div><p className="mt-1 text-sm text-white">{item.message || item.reason || "Yeni alarm bildirimi"}</p></article>)}</div>}
                </div>
            </section>
        </div>}
        </>
    );
}
