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
    <header className="sticky top-0 z-30 hidden border-b border-bunker-800 bg-bunker-900 md:block">
      <nav aria-label="Ana menü" className="mx-auto flex max-w-5xl items-center gap-1 px-4 py-2">
        {visibleMenu(hidden).map((m) => {
          const active = m.href === "/" ? pathname === "/" : pathname.startsWith(m.href);
          return (
            <Link
              key={m.id}
              href={m.href}
              aria-current={active ? "page" : undefined}
              className={`rounded-lg px-3 py-2 text-sm font-medium ${
                active ? "u-btn-brand" : "text-bunker-muted hover:bg-bunker-950 hover:text-white"
              }`}
            >
              <span aria-hidden className="mr-1">{m.icon}</span>
              {m.label}
            </Link>
          );
        })}
        {role === "admin" && (
          <button type="button" onClick={() => setView("advanced")} className="ui-button ui-button-secondary ml-auto px-3 py-1.5 text-sm" title="Mevcut yönetim arayüzüne dön">
            Gelişmiş arayüze geç
          </button>
        )}
        <span className={`${role === "admin" ? "ml-2" : "ml-auto"} text-sm text-bunker-muted`}>{username}</span>
        <button
          type="button"
          onClick={() => void logout?.()}
          className="ui-button ui-button-secondary ml-2 px-3 py-1.5 text-sm"
        >
          Çıkış
        </button>
      </nav>
    </header>
  );
}
