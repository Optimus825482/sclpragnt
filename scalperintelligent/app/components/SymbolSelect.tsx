"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useWatchlist } from "../lib/watchlist";

/**
 * Aramalı ve favori destekli sembol seçici.
 * Favori sembolleri listenin en başında gösterir.
 */
export default function SymbolSelect({
  symbols,
  value,
  onChange,
  placeholder = "Sembol ara…",
}: {
  symbols: string[];
  value: string | null;
  onChange: (symbol: string) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const { isFavorite, toggleFavorite } = useWatchlist();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    let hits = symbols;
    if (q) {
      hits = symbols.filter((s) => s.includes(q));
    }

    // Sıralama kuralı:
    // 1. Favoriler en başta
    // 2. Arama varsa baştan eşleşenler
    return hits
      .slice()
      .sort((a, b) => {
        const favA = isFavorite(a) ? 1 : 0;
        const favB = isFavorite(b) ? 1 : 0;
        if (favA !== favB) return favB - favA;
        if (q) {
          const startA = a.startsWith(q) ? 1 : 0;
          const startB = b.startsWith(q) ? 1 : 0;
          if (startA !== startB) return startB - startA;
        }
        return a.localeCompare(b);
      })
      .slice(0, 60);
  }, [symbols, query, isFavorite]);

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-lg border border-line bg-white px-3 py-2 text-left text-sm hover:border-ink-400"
      >
        <span className="flex items-center gap-1.5">
          {value && isFavorite(value) && <span className="text-amber-500 text-xs">★</span>}
          <span className={value ? "font-mono font-semibold text-ink-900" : "text-ink-400"}>
            {value || "Sembol seç"}
          </span>
        </span>
        <span className="text-ink-400">▾</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-line bg-white shadow-pop">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            aria-label="Sembol ara"
            className="w-full border-b border-line px-3 py-2 text-sm outline-none"
          />
          <ul role="listbox" className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-4 text-center text-xs text-ink-400">Sonuç yok</li>
            ) : (
              filtered.map((s) => {
                const fav = isFavorite(s);
                return (
                  <li key={s} className="flex items-center justify-between px-2 hover:bg-slate-50">
                    <button
                      type="button"
                      role="option"
                      aria-selected={s === value}
                      onClick={() => {
                        onChange(s);
                        setOpen(false);
                        setQuery("");
                      }}
                      className={`flex-1 py-1.5 text-left font-mono text-xs ${
                        s === value ? "font-bold text-accent" : "text-ink-700"
                      }`}
                    >
                      {s}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFavorite(s);
                      }}
                      className={`p-1 text-xs ${fav ? "text-amber-500" : "text-ink-300 hover:text-amber-500"}`}
                      title={fav ? "Favoriden çıkar" : "Favoriye ekle"}
                      aria-label={`${s} ${fav ? "favoriden çıkar" : "favoriye ekle"}`}
                      aria-pressed={fav}
                    >
                      {fav ? "★" : "☆"}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
