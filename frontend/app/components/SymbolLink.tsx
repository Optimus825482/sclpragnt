import Link from "next/link";

type SymbolLinkProps = {
  symbol?: string | null;
  className?: string;
  timeframe?: string;
  newTab?: boolean;
};

export default function SymbolLink({ symbol, className = "font-mono text-white hover:text-neon-green", timeframe = "5m", newTab = false }: SymbolLinkProps) {
  const value = String(symbol || "").replace(/_/g, "").toUpperCase();
  if (!value) return null;
  return (
    <Link
      href={`/charts?symbol=${encodeURIComponent(value)}&timeframe=${encodeURIComponent(timeframe)}`}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noreferrer" : undefined}
      className={`inline-flex cursor-pointer items-center ${className}`}
      title={`${value} ${timeframe.toUpperCase()} grafiğini aç`}
      aria-label={`${value} ${timeframe.toUpperCase()} grafiğini aç`}
    >
      {value}
    </Link>
  );
}
