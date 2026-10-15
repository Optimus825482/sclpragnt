"use client";
import { useAdminView } from "../lib/adminView";

/** Admin için arayüz seçici: Basit = kullanıcıların gördüğü arayüz, Gelişmiş = mevcut arayüz. */
export default function AdminViewSwitch({ className = "" }: { className?: string }) {
  const { view, setView } = useAdminView();
  const options = [
    { id: "simple" as const, label: "Basit", hint: "Kullanıcıların gördüğü arayüz" },
    { id: "advanced" as const, label: "Gelişmiş", hint: "Mevcut yönetim arayüzü" },
  ];
  return (
    <div className={className}>
      <p className="mb-1.5 font-mono text-[10px] font-bold text-bunker-muted">ARAYÜZ</p>
      <div role="radiogroup" aria-label="Arayüz seçimi" className="grid grid-cols-2 gap-1 rounded-lg border border-bunker-700 bg-bunker-950/70 p-1">
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={view === o.id}
            title={o.hint}
            onClick={() => setView(o.id)}
            className={`min-h-[36px] rounded-md px-2 py-1.5 font-mono text-[11px] font-bold transition-colors ${
              view === o.id ? "bg-neon-green text-bunker-950" : "text-bunker-muted hover:text-white"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
