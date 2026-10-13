"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Aramalı sembol seçici (tasarımdaki "üstten sembol adına tıklayınca açılan
 * arama özellikli select"). Harici kütüphane yok; basit filtre + klavye.
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
    if (!q) return symbols.slice(0, 60);
    const hits = symbols.filter((s) => s.includes(q));
    // Baştan eşleşenler önce (daha sezgisel).
    hits.sort((a, b) => Number(b.startsWith(q)) - Number(a.startsWith(q)));
    return hits.slice(0, 60);
  }, [symbols, query]);

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-lg border border-line bg-white px-3 py-2 text-left text-sm hover:border-ink-400"
      >
        <span className={value ? "font-mono font-semibold text-ink-900" : "text-ink-400"}>{value || "Sembol seç"}</span>
        <span className="text-ink-400">▾</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-line bg-white shadow-pop">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="w-full border-b border-line px-3 py-2 text-sm outline-none"
          />
          <ul role="listbox" className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-4 text-center text-xs text-ink-400">Sonuç yok</li>
            ) : (
              filtered.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={s === value}
                    onClick={() => {
                      onChange(s);
                      setOpen(false);
                      setQuery("");
                    }}
                    className={`block w-full px-3 py-1.5 text-left font-mono text-xs hover:bg-accent-soft ${
                      s === value ? "bg-accent-soft text-accent" : "text-ink-700"
                    }`}
                  >
                    {s}
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
