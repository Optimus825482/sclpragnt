import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<ButtonVariant, string> = {
  primary: "ui-button-primary",
  secondary: "ui-button-secondary",
  danger: "ui-button-danger",
  ghost: "ui-button-ghost",
};

export function Button({ variant = "secondary", className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={`ui-button ${variants[variant]} ${className}`} {...props}>{children}</button>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`ui-card ${className}`}>{children}</section>;
}

export function Badge({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: "neutral" | "positive" | "negative" | "warning" | "info"; className?: string }) {
  return <span className={`ui-badge ui-badge-${tone} ${className}`}>{children}</span>;
}

export function SectionHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return <div className="ui-section-header"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2>{description && <p className="ui-section-description">{description}</p>}</div>{actions && <div className="ui-section-actions">{actions}</div>}</div>;
}

export function StatCard({ label, value, tone = "default", detail }: { label: string; value: ReactNode; tone?: "default" | "positive" | "negative" | "warning"; detail?: ReactNode }) {
  return <Card className="ui-stat-card"><p className="eyebrow">{label}</p><p className={`ui-stat-value ui-tone-${tone}`}>{value}</p>{detail && <p className="ui-stat-detail">{detail}</p>}</Card>;
}

export function Tabs({ items, active, onChange, className = "" }: { items: Array<{ id: string; label: ReactNode }>; active: string; onChange: (id: string) => void; className?: string }) {
  const tablistId = useId();
  const move = (index: number, direction: number) => { const next = (index + direction + items.length) % items.length; onChange(items[next].id); document.getElementById(`${tablistId}-${items[next].id}`)?.focus(); };
  return <div className={`ui-tabs ${className}`} role="tablist" aria-label="Bölüm sekmeleri">{items.map((item, index) => <button id={`${tablistId}-${item.id}`} key={item.id} role="tab" type="button" tabIndex={active === item.id ? 0 : -1} aria-selected={active === item.id} className={active === item.id ? "active" : ""} onClick={() => onChange(item.id)} onKeyDown={(event) => { if (event.key === "ArrowRight") { event.preventDefault(); move(index, 1); } if (event.key === "ArrowLeft") { event.preventDefault(); move(index, -1); } }}>{item.label}</button>)}</div>;
}
