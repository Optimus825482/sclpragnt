"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { visibleMenu } from "../../lib/userUi";
import { openAssistant } from "../../lib/assistantEvents";

export default function UserBottomNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const items = visibleMenu(hidden);
  const main = items.slice(0, 4);
  const rest = items.slice(4);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  // "Diğer" listesi: bir satıra, başka bir menü düğmesine ya da sayfada herhangi bir yere dokununca / Esc ile / sayfa
  // değişince kapanır (eskiden <details> açık kalıyordu).
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLLIElement>(null);
  useEffect(() => { setMoreOpen(false); }, [pathname]);
  useEffect(() => {
    if (!moreOpen) return;
    const onPointer = (e: Event) => {
      if (moreRef.current && e.target instanceof Node && moreRef.current.contains(e.target)) return;
      setMoreOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMoreOpen(false); };
    document.addEventListener("pointerdown", onPointer, true);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onPointer, true); document.removeEventListener("keydown", onKey); };
  }, [moreOpen]);
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
                isActive(m.href) ? "font-bold text-[color:var(--u-brand)]" : "text-bunker-muted"
              }`}
            >
              <span aria-hidden className="text-lg">{m.icon}</span>
              {m.label}
            </Link>
          </li>
        ))}
        {/* Asistan artık yüzen düğme değil: mobilde bu listeden açılır. */}
        <li ref={moreRef} className="relative flex-1">
          <button
            type="button"
            aria-expanded={moreOpen}
            aria-haspopup="menu"
            onClick={() => setMoreOpen((v) => !v)}
            className={`touch-target flex min-h-[44px] w-full cursor-pointer flex-col items-center justify-center text-xs ${moreOpen ? "font-bold text-[color:var(--u-brand)]" : "text-bunker-muted"}`}
          >
            <span aria-hidden className="text-lg">☰</span>
            Diğer
          </button>
          {moreOpen && (
            <ul role="menu" className="absolute bottom-full right-0 mb-1 w-44 rounded-xl border border-bunker-800 bg-bunker-900 p-1 shadow-lg">
              <li role="none">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setMoreOpen(false); openAssistant(); }}
                  className="flex min-h-[44px] w-full items-center gap-2 rounded-lg px-3 text-left text-sm text-white"
                >
                  <span aria-hidden>🤖</span>
                  Asistan
                </button>
              </li>
              {rest.map((m) => (
                <li key={m.id} role="none">
                  <Link
                    href={m.href}
                    role="menuitem"
                    onClick={() => setMoreOpen(false)}
                    className="flex min-h-[44px] items-center gap-2 rounded-lg px-3 text-sm text-white"
                  >
                    <span aria-hidden>{m.icon}</span>
                    {m.label}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </li>
      </ul>
    </nav>
  );
}
