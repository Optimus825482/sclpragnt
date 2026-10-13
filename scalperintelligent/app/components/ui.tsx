"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { sourceLabel } from "../lib/sources";

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

/* --- Motor bazlı sinyal kaynak rozetleri --------------------------------- */

type SourceBadgeStyle = { label: string; icon: ReactNode; cls: string };

const SOURCE_BADGE_NEUTRAL = "border-line bg-canvas text-ink-500";

/** Her tarama motoruna özgü renk + ikon. Açık tema tek vurgu (mavi) korunur. */
const SOURCE_BADGES: Record<string, SourceBadgeStyle> = {
  velocity: { label: "Radar", icon: "◎", cls: "border-accent/25 bg-accent-soft text-accent" },
  jump: { label: "MACD Sıçrama", icon: "⚡", cls: "border-violet-200 bg-violet-50 text-violet-700" },
  early: { label: "Erken Sıçrama", icon: "◷", cls: "border-violet-200 bg-violet-50/60 text-violet-600" },
  rising: { label: "Yükseliş", icon: "↗", cls: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  daily_momentum: { label: "Momentum", icon: "⇗", cls: "border-amber-200 bg-amber-50 text-amber-700" },
  short_squeeze: { label: "Squeeze", icon: "⇈", cls: "border-orange-200 bg-orange-50 text-orange-700" },
  pulse: {
    label: "Nabız", icon: <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />,
    cls: "border-rose-200 bg-rose-50 text-rose-600",
  },
  snapback: { label: "Snapback", icon: "⟲", cls: "border-cyan-200 bg-cyan-50 text-cyan-700" },
  macd_mtf: { label: "MACD MTF", icon: "≣", cls: "border-indigo-200 bg-indigo-50 text-indigo-700" },
  macd_snapshot: { label: "MACD Anlık", icon: "◐", cls: "border-slate-200 bg-slate-100 text-slate-600" },
  fusion: { label: "Füzyon", icon: "✦", cls: "border-transparent bg-accent text-white" },
  both: { label: "Momentum+Squeeze", icon: "⇄", cls: "border-amber-200 bg-amber-50 text-amber-700" },
  gainer: { label: "Kazananlar", icon: "▲", cls: SOURCE_BADGE_NEUTRAL },
  mover: { label: "Hareketli", icon: "◆", cls: SOURCE_BADGE_NEUTRAL },
  discovery: { label: "Keşif", icon: "✚", cls: SOURCE_BADGE_NEUTRAL },
  symbol: { label: "Takip", icon: "★", cls: SOURCE_BADGE_NEUTRAL },
  extra: { label: "Ek Havuz", icon: "＋", cls: SOURCE_BADGE_NEUTRAL },
};

/**
 * Sinyal motorlarını her birine özgü renkli/ikonlu rozetlerle gösterir.
 * `codes` ham kaynak kodlarıdır (örn. "velocity", "snapback"); bilinmeyen
 * kodlar nötr rozete düşer ve `sourceLabel` etiketi kullanılır.
 */
export function SourceBadges({
  codes,
  max = 4,
  label,
  className = "",
}: {
  codes: string[];
  max?: number;
  label?: string;
  className?: string;
}) {
  const visible = codes.slice(0, max);
  if (!visible.length) return null;
  return (
    <div className={`flex flex-wrap items-center gap-1 ${className}`}>
      {label && <span className="text-[9px] uppercase tracking-wide text-ink-400">{label}</span>}
      {visible.map((code) => {
        const badge = SOURCE_BADGES[code] ?? { label: sourceLabel(code) || code, icon: "▪", cls: SOURCE_BADGE_NEUTRAL };
        return (
          <span
            key={code}
            title={`Sinyal kaynağı: ${badge.label}`}
            className={`inline-flex max-w-[10rem] items-center gap-1 whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-semibold leading-none ${badge.cls}`}
          >
            <span aria-hidden className="inline-flex items-center text-[9px] leading-none">{badge.icon}</span>
            <span className="truncate">{badge.label}</span>
          </span>
        );
      })}
      {codes.length > max && (
        <span
          className="rounded-full border border-line bg-canvas px-1.5 py-0.5 text-[10px] font-semibold text-ink-400"
          title={codes.slice(max).map((code) => sourceLabel(code) || code).join(", ")}
        >
          +{codes.length - max}
        </span>
      )}
    </div>
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

/** Aç/kapat anahtarı (erişilebilir switch). */
export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-center justify-between gap-4 py-2.5 ${disabled ? "opacity-50" : ""}`}>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink-900">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-ink-400">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={typeof label === "string" ? label : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          checked ? "bg-gain" : "bg-ink-400/40"
        } disabled:cursor-not-allowed`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
            checked ? "left-[1.375rem]" : "left-0.5"
          }`}
        />
      </button>
    </label>
  );
}
