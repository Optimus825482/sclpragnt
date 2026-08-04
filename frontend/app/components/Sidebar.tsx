"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const MENU = [
    { href: "/", label: "Scalping", icon: "⚡", desc: "Canlı terminal" },
    { href: "/portfolio", label: "Portföy", icon: "📊", desc: "Varlıklar & PnL" },
    { href: "/strategies", label: "Stratejiler", icon: "🧠", desc: "Aktif/pasif & ayarlar" },
    { href: "/gainer-radar", label: "Gainer Radar", icon: "🎯", desc: "Fırsat tarayıcı" },
    { href: "/history", label: "İşlem Geçmişi", icon: "📜", desc: "Kapanan pozisyonlar" },
    { href: "/backtest", label: "Backtest", icon: "🧪", desc: "Strateji test lab" },
    { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
    { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu" }
];

export default function Sidebar() {
    const pathname = usePathname();
    const [open, setOpen] = useState(false);
    const [installEvent, setInstallEvent] = useState<any>(null);
    useEffect(() => {
        if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
        const handler = (event: Event) => { event.preventDefault(); setInstallEvent(event); };
        window.addEventListener("beforeinstallprompt", handler);
        return () => window.removeEventListener("beforeinstallprompt", handler);
    }, []);
    useEffect(() => setOpen(false), [pathname]);
    const install = async () => {
        if (!installEvent) return;
        await installEvent.prompt();
        setInstallEvent(null);
    };

    return (
        <>
            <button className="mobile-menu-button" onClick={() => setOpen(true)} aria-label="Menüyü aç">☰</button>
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
            </div>

            <nav className="flex-1 p-3 space-y-1">
                {MENU.map((m) => {
                    const active = pathname === m.href;
                    return (
                        <Link
                            key={m.href}
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
                    );
                })}
            </nav>

            <div className="p-4 border-t border-bunker-800">
                <button onClick={install} disabled={!installEvent} className={`w-full mb-4 px-3 py-2 rounded-lg border font-mono text-xs ${installEvent ? "border-neon-green/50 bg-neon-green/10 text-neon-green hover:bg-neon-green/20" : "border-bunker-700 bg-bunker-900 text-bunker-muted"}`}>⬇ {installEvent ? "UYGULAMA OLARAK YÜKLE" : "YÜKLEME İÇİN TARAYICI MENÜSÜ"}</button>
                <p className="eyebrow">SİSTEM DURUMU</p>
                <p className="font-mono text-xs text-neon-green mt-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" /> Çalışıyor
                </p>
                <p className="font-mono text-[11px] text-bunker-muted mt-1">ws://localhost:8004</p>
            </div>
        </aside>
        </>
    );
}
