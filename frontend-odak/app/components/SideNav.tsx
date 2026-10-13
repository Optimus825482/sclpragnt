"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePoll } from "../lib/hooks";

type Health = { status?: string; safety?: { paper_only?: boolean }; market?: { fresh_symbols?: number } };

const ITEMS = [
  { href: "/", label: "Anasayfa", icon: "⌂" },
  { href: "/firsatlar", label: "Fırsatlar", icon: "◎" },
  { href: "/#aktif-islemler", label: "Aktif İşlemler", icon: "≡" },
  { href: "/gecmis-islemler", label: "Geçmiş İşlemler", icon: "◷" },
  { href: "/ayarlar", label: "Ayarlar", icon: "⚙" },
];

export default function SideNav() {
  const pathname = usePathname();
  const health = usePoll<Health>("/api/system/health", 20_000);
  const active = health.data?.status === "ok";

  return (
    <aside className="odak-sidebar hidden lg:flex">
      <nav aria-label="Ana menü" className="flex flex-col gap-1">
        {ITEMS.map((item) => {
          const hrefPath = item.href.split("#")[0];
          const selected = hrefPath === "/" ? pathname === "/" : pathname.startsWith(hrefPath);
          return (
            <Link key={item.label} href={item.href} aria-current={selected ? "page" : undefined}
              className={`odak-side-link ${selected ? "odak-side-link-active" : ""}`}>
              <span aria-hidden="true" className="w-6 text-center text-lg">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <section className="odak-system-status" aria-label="Sistem durumu">
        <p className="flex items-center gap-2 font-semibold text-ink-900">
          <span className={`h-2.5 w-2.5 rounded-full ${active ? "bg-gain" : "bg-warn"}`} />
          {active ? "Sistem Aktif" : health.loading ? "Durum alınıyor" : "Kontrol gerekli"}
        </p>
        <p className="mt-3 flex items-center justify-between text-xs text-ink-500">
          <span>İşlem modu</span><span className="font-semibold text-accent">Paper</span>
        </p>
        <p className="mt-1 text-[11px] text-ink-400">
          {health.data?.market?.fresh_symbols != null
            ? `${health.data.market.fresh_symbols} sembolde güncel veri`
            : "Piyasa verisi bekleniyor"}
        </p>
      </section>
    </aside>
  );
}
