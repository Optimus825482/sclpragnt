"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { visibleMenu } from "../../lib/userUi";

export default function UserBottomNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const items = visibleMenu(hidden);
  const main = items.slice(0, 4);
  const rest = items.slice(4);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <nav
      aria-label="Alt menü"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-bunker-800 bg-bunker-900 pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="flex">
        {main.map((m) => (
          <li key={m.id} className="flex-1">
            <Link
              href={m.href}
              aria-current={isActive(m.href) ? "page" : undefined}
              className={`touch-target flex min-h-[44px] flex-col items-center justify-center text-xs ${
                isActive(m.href) ? "text-neon-green" : "text-bunker-muted"
              }`}
            >
              <span aria-hidden className="text-lg">{m.icon}</span>
              {m.label}
            </Link>
          </li>
        ))}
        {rest.length > 0 && (
          <li className="relative flex-1">
            <details>
              <summary className="touch-target flex min-h-[44px] cursor-pointer list-none flex-col items-center justify-center text-xs text-bunker-muted">
                <span aria-hidden className="text-lg">☰</span>
                Diğer
              </summary>
              <ul className="absolute bottom-full right-0 mb-1 w-44 rounded-xl border border-bunker-800 bg-bunker-900 p-1 shadow-lg">
                {rest.map((m) => (
                  <li key={m.id}>
                    <Link
                      href={m.href}
                      className="flex min-h-[44px] items-center gap-2 rounded-lg px-3 text-sm text-white"
                    >
                      <span aria-hidden>{m.icon}</span>
                      {m.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </details>
          </li>
        )}
      </ul>
    </nav>
  );
}
