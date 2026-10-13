"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../lib/auth";
import { Button } from "./ui";

/**
 * TEK ÜST MENÜ — sistem adı: SCALPER INTELLIGENT TRADE SYSTEMS.
 * Menü: Anasayfa · Fırsatlar · Geçmiş İşlemler · Ayarlar.
 *
 * Tasarım incelemesindeki "çift navigasyon" sorunu nedeniyle sol sidebar YOK.
 * Canlı/bağlantı durumu sağ üstte kompakt bir nokta ile gösterilir.
 */
const NAV = [
  { href: "/", label: "Anasayfa" },
  { href: "/firsatlar", label: "Fırsatlar" },
  { href: "/gecmis-islemler", label: "Geçmiş İşlemler" },
  { href: "/ayarlar", label: "Ayarlar" },
];

export default function TopNav() {
  const pathname = usePathname();
  const { username, role, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  const isAdmin = role === "admin";
  const initial = (username || "?").charAt(0).toUpperCase();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-white">S</span>
          <span className="hidden leading-tight sm:block">
            <span className="block text-[13px] font-bold tracking-tight text-ink-900">SCALPER</span>
            <span className="block text-[9px] font-medium uppercase tracking-[0.14em] text-ink-400">
              Intelligent Trade Systems
            </span>
          </span>
        </Link>

        <nav className="flex items-center gap-0.5 overflow-x-auto" aria-label="Ana navigasyon">
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

        <div className="ml-auto flex items-center gap-2.5">
          {username && (
            <>
              <span className="hidden sm:block text-right leading-tight">
                <span className="block text-xs font-semibold text-ink-900">{username}</span>
                <span className="block text-[10px] uppercase tracking-wide text-ink-400">{isAdmin ? "Yönetici" : "Kullanıcı"}</span>
              </span>
              <span className="grid h-8 w-8 place-items-center rounded-full bg-canvas text-xs font-bold text-ink-700">
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
            </>
          )}
        </div>
      </div>
    </header>
  );
}
