"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";

const base =
  "inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 px-3.5 py-2 min-h-[2.5rem]";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-white text-ink-700 border border-line hover:border-ink-400 hover:text-ink-900",
  ghost: "bg-transparent text-ink-500 hover:bg-canvas hover:text-ink-900",
  danger: "bg-loss text-white hover:brightness-95",
  success: "bg-gain text-white hover:brightness-95",
};

export function Button({
  variant = "secondary",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button className={`${base} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`odak-card ${className}`}>{children}</section>;
}

type Tone = "neutral" | "accent" | "gain" | "loss" | "warn";

const badgeTones: Record<Tone, string> = {
  neutral: "bg-canvas text-ink-500 border-line",
  accent: "bg-accent-soft text-accent border-accent/25",
  gain: "bg-gain-soft text-gain border-gain/25",
  loss: "bg-loss-soft text-loss border-loss/25",
  warn: "bg-warn-soft text-warn border-warn/25",
};

/** DURUM/pill rozeti. Metin-formu (saniye) veya ikonludan bağımsız. */
export function Badge({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none ${badgeTones[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <p className="odak-kicker">{eyebrow}</p>}
        <h2 className="mt-1 text-lg font-semibold text-ink-900">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-ink-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Sekme çubuğu — tek vurgu rengi mavi (harici kütüphane yok). */
export function Tabs({
  items,
  active,
  onChange,
}: {
  items: Array<{ id: string; label: ReactNode }>;
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div role="tablist" aria-label="Bölüm sekmeleri" className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-white p-1">
      {items.map((item) => {
        const isActive = active === item.id;
        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={isActive}
            onClick={() => onChange(item.id)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              isActive ? "bg-accent text-white" : "text-ink-500 hover:bg-canvas hover:text-ink-900"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function Stat({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
}) {
  const valueTone =
    tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : tone === "warn" ? "text-warn" : "text-ink-900";
  return (
    <Card className="p-4">
      <p className="odak-kicker">{label}</p>
      <p className={`mt-1.5 font-mono text-2xl font-semibold tracking-tight ${valueTone}`}>{value}</p>
      {detail && <p className="mt-1 text-xs text-ink-400">{detail}</p>}
    </Card>
  );
}

/** Boş/hata durumu için metin paneli. */
export function EmptyState({ title, hint, tone = "neutral" }: { title: string; hint?: string; tone?: "neutral" | "loss" }) {
  return (
    <div className={`rounded-xl border border-dashed px-4 py-8 text-center ${tone === "loss" ? "border-loss/30 bg-loss-soft/40" : "border-line bg-white/60"}`}>
      <p className={`text-sm font-medium ${tone === "loss" ? "text-loss" : "text-ink-700"}`}>{title}</p>
      {hint && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}

/** İskelet yükleme bloğu. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-canvas ${className}`} />;
}
