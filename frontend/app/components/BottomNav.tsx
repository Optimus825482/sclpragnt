"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/monitoring", label: "Radar", icon: "📡" },
  { href: "/binance-tr", label: "Binance TR", icon: "🏛️" },
  { href: "/charts", label: "Grafik", icon: "📈" },
  { href: "/portfolio", label: "Portföy", icon: "💼" },
];

export default function BottomNav() {
  const pathname = usePathname();

  const handleOpenMenu = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("open-mobile-menu"));
    }
  };

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 flex md:hidden items-center justify-around border-t border-bunker-800 bg-bunker-950/95 backdrop-blur-lg px-1 py-1 text-[11px] font-mono shadow-2xl transition-transform"
      style={{ paddingBottom: "max(0.35rem, env(safe-area-inset-bottom, 0px))" }}
      aria-label="Mobil Hızlı Gezinme"
    >
      {NAV_ITEMS.map((item) => {
        const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex flex-1 flex-col items-center justify-center py-1.5 px-1 rounded-lg transition-all touch-target ${
              isActive
                ? "text-neon-green font-bold scale-105"
                : "text-bunker-muted hover:text-white"
            }`}
          >
            <span className="text-lg leading-none mb-1">{item.icon}</span>
            <span className="truncate tracking-tight text-[10px]">{item.label}</span>
          </Link>
        );
      })}

      <button
        type="button"
        onClick={handleOpenMenu}
        className="flex flex-1 flex-col items-center justify-center py-1.5 px-1 rounded-lg text-bunker-muted hover:text-white transition-all touch-target"
        aria-label="Tüm Menüyü Aç"
      >
        <span className="text-lg leading-none mb-1">☰</span>
        <span className="truncate tracking-tight text-[10px]">Menü</span>
      </button>
    </nav>
  );
}
