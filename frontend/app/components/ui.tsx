import type { ButtonHTMLAttributes, ReactNode } from "react";

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

export function StatCard({ label, value, tone = "default", detail }: { label: string; value: ReactNode; tone?: "default" | "positive" | "negative" | "warning"; detail?: ReactNode }) {
  return <Card className="ui-stat-card"><p className="eyebrow">{label}</p><p className={`ui-stat-value ui-tone-${tone}`}>{value}</p>{detail && <p className="ui-stat-detail">{detail}</p>}</Card>;
}

export function Tabs({ items, active, onChange, className = "" }: { items: Array<{ id: string; label: ReactNode }>; active: string; onChange: (id: string) => void; className?: string }) {
  return <div className={`ui-tabs ${className}`} role="tablist">{items.map((item) => <button key={item.id} role="tab" aria-selected={active === item.id} className={active === item.id ? "active" : ""} onClick={() => onChange(item.id)}>{item.label}</button>)}</div>;
}
