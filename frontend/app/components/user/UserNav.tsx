"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "../../lib/auth";
import { visibleMenu } from "../../lib/userUi";

export default function UserNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const { username, logout } = useAuth();
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
                active ? "bg-bunker-800 text-white" : "text-bunker-muted hover:text-white"
              }`}
            >
              <span aria-hidden className="mr-1">{m.icon}</span>
              {m.label}
            </Link>
          );
        })}
        <span className="ml-auto text-sm text-bunker-muted">{username}</span>
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
