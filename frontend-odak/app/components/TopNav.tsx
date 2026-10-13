"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../lib/auth";
import { useLiveStatus } from "../lib/liveSocket";
import { Badge, Button } from "./ui";

/**
 * TEK ÜST MENÜ — bilinçli karar.
 *
 * Tasarım incelemesinde en yüksek öncelikli sorun, aynı menülerin hem üstte hem
 * solda tekrar etmesiydi. Bu arayüzde navigasyon YALNIZCA burada; sol sidebar
 * kaldırıldı. Sistem durumu kompakt bir şeride taşındı (bkz. StatusStrip).
 */
const NAV = [
  { href: "/", label: "Fırsatlar" },
  { href: "/positions", label: "Pozisyonlar" },
  { href: "/strategies", label: "Stratejiler" },
];

export default function TopNav() {
  const pathname = usePathname();
  const { username, role, logout } = useAuth();
  const liveStatus = useLiveStatus();
  const [busy, setBusy] = useState(false);

  const isAdmin = role === "admin";
  const initial = (username || "?").charAt(0).toUpperCase();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
        {/* Marka */}
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-white">O</span>
          <span className="hidden text-sm font-semibold tracking-tight text-ink-900 sm:block">
            ODAK <span className="font-normal text-ink-500">AI Trader</span>
          </span>
        </Link>

        {/* Ana menü (yalnızca burada) */}
        <nav className="flex items-center gap-1 overflow-x-auto" aria-label="Ana navigasyon">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  active ? "bg-accent-soft text-accent" : "text-ink-500 hover:bg-canvas hover:text-ink-900"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Sağ araçlar */}
        <div className="ml-auto flex items-center gap-2.5">
          <span className="hidden items-center gap-1.5 sm:flex">
            <Badge tone={liveStatus === "open" ? "gain" : "warn"}>
              <span className={`h-1.5 w-1.5 rounded-full ${liveStatus === "open" ? "bg-gain odak-live-dot" : "bg-warn"}`} />
              {liveStatus === "open" ? "Canlı" : "Bağlantı yok"}
            </Badge>
          </span>

          {/* Binance TR — kendi hesabın (mevcut arayüzdeki canlı işlem) */}
          <a
            href="http://localhost:3004/binance-tr"
            className="hidden rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-500 hover:border-ink-400 hover:text-ink-900 sm:inline-flex"
            title="Mevcut panelde Binance TR canlı işlem"
          >
            Binance TR ↗
          </a>

          {username && (
            <div className="flex items-center gap-2">
              <span
                className="grid h-8 w-8 place-items-center rounded-full bg-canvas text-xs font-bold text-ink-700"
                title={`${username}${isAdmin ? " (yönetici)" : ""}`}
              >
                {initial}
              </span>
              <Button
                variant="ghost"
                className="hidden min-h-0 px-2 py-1 text-xs sm:inline-flex"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await logout?.();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "…" : "Çıkış"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
