"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "../../lib/auth";
import { visibleMenu } from "../../lib/userUi";
import { useAdminView } from "../../lib/adminView";

export default function UserNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const { username, role, logout } = useAuth();
  const { setView } = useAdminView();
  return (
    // 2026-10-17 (basit arayüz): yapışkanlık UserShell'deki ortak bloğa taşındı; menü tek
    // satır (sarmalama yok), öğeler eşit yükseklikte, sağ grup sabit genişlikte.
    <header className="hidden border-b border-bunker-800 bg-bunker-900 md:block">
      <nav aria-label="Ana menü" className="mx-auto flex h-14 max-w-5xl flex-nowrap items-center gap-1 overflow-x-auto px-4">
        {visibleMenu(hidden).map((m) => {
          const active = m.href === "/" ? pathname === "/" : pathname.startsWith(m.href);
          return (
            <Link
              key={m.id}
              href={m.href}
              aria-current={active ? "page" : undefined}
              className={`inline-flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-sm font-medium ${
                active ? "u-btn-brand" : "text-bunker-muted hover:bg-bunker-950 hover:text-white"
              }`}
            >
              <span aria-hidden className="text-base leading-none">{m.icon}</span>
              <span>{m.label}</span>
            </Link>
          );
        })}
        <div className="ml-auto flex shrink-0 items-center gap-2 pl-3">
          {role === "admin" && (
            <button type="button" onClick={() => setView("advanced")} className="ui-button ui-button-secondary h-9 whitespace-nowrap px-3 text-xs" title="Mevcut yönetim arayüzüne dön">
              Gelişmiş görünüm
            </button>
          )}
          <span className="max-w-[9rem] truncate text-sm text-bunker-muted" title={username || ""}>{username}</span>
          <button
            type="button"
            onClick={() => void logout?.()}
            className="ui-button ui-button-secondary h-9 whitespace-nowrap px-3 text-xs"
          >
            Çıkış
          </button>
        </div>
      </nav>
    </header>
  );
}
