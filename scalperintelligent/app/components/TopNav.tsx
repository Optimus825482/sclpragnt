"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { useLiveStatus } from "../lib/liveSocket";
import { useWatchlist } from "../lib/watchlist";
import { sound } from "../lib/sound";
import { Badge, Button } from "./ui";
import FavoriteTickerBand from "./FavoriteTickerBand";

const NAV = [
  { href: "/", label: "Anasayfa" },
  { href: "/firsatlar", label: "Sinyal & Tarama" },
  { href: "/grafik", label: "Grafikler" },
  { href: "/emirler", label: "Açık Emirler" },
  { href: "/gecmis-islemler", label: "İşlem Geçmişi" },
  { href: "/alarmlar", label: "Alarmlar" },
  { href: "/ayarlar", label: "Ayarlar" },
];

export default function TopNav() {
  const pathname = usePathname();
  const { username, role, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  const [soundActive, setSoundActive] = useState(true);
  const liveStatus = useLiveStatus();
  const { favorites } = useWatchlist();

  const isAdmin = role === "admin";
  const initial = (username || "?").charAt(0).toUpperCase();
  const liveLabel = liveStatus === "open" ? "CANLI" : liveStatus === "connecting" ? "BAĞLANIYOR" : "KOPUK";

  useEffect(() => {
    try {
      const stored = localStorage.getItem("odak_sound_enabled");
      if (stored !== null) setSoundActive(stored === "true");
    } catch {
      // pass
    }
  }, []);

  const toggleSound = () => {
    const next = !soundActive;
    setSoundActive(next);
    try {
      localStorage.setItem("odak_sound_enabled", String(next));
    } catch {
      // pass
    }
    if (next) sound.playSuccessTone();
  };

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between gap-3 px-4 sm:px-6">
        {/* Sol Logo ve Başlık */}
        <div className="flex items-center gap-4">
          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-sm font-bold text-white shadow-sm">
              S
            </span>
            <div className="hidden leading-tight sm:block">
              <span className="block text-sm font-bold tracking-tight text-ink-900">SCALPER AGENT</span>
              <span className="block text-[9px] font-semibold uppercase tracking-[0.15em] text-accent">
                Unified Signal Engine
              </span>
            </div>
          </Link>

          {/* Menü Sekmeleri (mobilde kaydırılabilir, kaydırma çubuğu gizli) */}
          <nav className="odak-ticker-scroll flex min-w-0 flex-1 items-center gap-1 overflow-x-auto sm:flex-none" aria-label="Ana navigasyon">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors ${
                    active
                      ? "bg-accent-soft text-accent font-semibold"
                      : "text-ink-500 hover:bg-canvas hover:text-ink-900"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Sağ: Durum Göstergeleri ve Kullanıcı */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Favoriler Rozeti */}
          {favorites.length > 0 && (
            <Link
              href="/?filter=favorites"
              className="hidden md:inline-flex items-center gap-1.5 rounded-lg border border-line bg-canvas/70 px-2.5 py-1 text-xs font-medium text-ink-700 hover:border-accent hover:text-accent transition-colors"
              title="Favorilerimi Göster"
            >
              <span className="text-amber-500 font-bold">★</span>
              <span>{favorites.length} Favori</span>
            </Link>
          )}

          {/* Ses Bildirimi Butonu */}
          <button
            type="button"
            onClick={toggleSound}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors flex items-center gap-1 ${
              soundActive
                ? "border-accent/30 bg-accent-soft text-accent"
                : "border-line bg-canvas text-ink-400 hover:text-ink-700"
            }`}
            title={soundActive ? "Sinyal sesi açık (kapatmak için tıkla)" : "Sinyal sesi kapalı (açmak için tıkla)"}
            aria-label={soundActive ? "Sinyal sesini kapat" : "Sinyal sesini aç"}
            aria-pressed={soundActive}
          >
            <span>{soundActive ? "🔔" : "🔕"}</span>
            <span className="hidden lg:inline">{soundActive ? "Ses Açık" : "Sessiz"}</span>
          </button>

          {/* Canlı Bağlantı Rozeti — durum yalnız renkle değil metinle de taşınır */}
          <div
            className="flex items-center gap-1.5"
            role="status"
            aria-live="polite"
            title={`Canlı veri bağlantısı: ${liveLabel}`}
          >
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${
                liveStatus === "open"
                  ? "bg-gain odak-live-dot"
                  : liveStatus === "connecting"
                  ? "bg-warn animate-pulse"
                  : "bg-loss"
              }`}
            />
            <span className="font-mono text-[11px] font-semibold uppercase text-ink-500">
              <span className="sm:hidden" aria-hidden="true">{liveStatus === "open" ? "●" : liveStatus === "connecting" ? "…" : "✕"}</span>
              <span className="sr-only sm:not-sr-only">{liveLabel}</span>
            </span>
          </div>

          {/* Kullanıcı ve Çıkış */}
          {username && (
            <div className="flex items-center gap-2 border-l border-line pl-2 sm:pl-3">
              <span className="hidden xl:block text-right leading-tight">
                <span className="block text-xs font-semibold text-ink-900">{username}</span>
                <span className="block text-[9px] uppercase tracking-wide text-ink-400">
                  {isAdmin ? "Yönetici" : "Kullanıcı"}
                </span>
              </span>
              <span className="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-xs font-bold text-accent">
                {initial}
              </span>
              {/* Mobilde de erişilebilir: ikon + sr-only metin (denetim P2 a11y) */}
              <Button
                variant="ghost"
                className="min-h-0 px-2 py-1 text-xs"
                disabled={busy}
                aria-label="Oturumu kapat"
                title="Oturumu kapat"
                onClick={async () => {
                  setBusy(true);
                  try {
                    await logout?.();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <span className="sm:hidden" aria-hidden="true">{busy ? "…" : "⎋"}</span>
                <span className="hidden sm:inline">{busy ? "…" : "Çıkış"}</span>
              </Button>
            </div>
          )}
        </div>
      </div>
      </header>
      <FavoriteTickerBand favorites={favorites} />
    </>
  );
}
