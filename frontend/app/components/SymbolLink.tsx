import Link from "next/link";

type SymbolLinkProps = {
  symbol?: string | null;
  className?: string;
};

export default function SymbolLink({ symbol, className = "font-mono text-white hover:text-neon-green" }: SymbolLinkProps) {
  const value = String(symbol || "").replace(/_/g, "").toUpperCase();
  if (!value) return null;
  return (
    <Link
      href={`/charts?symbol=${encodeURIComponent(value)}&timeframe=5m`}
      className={`inline-flex cursor-pointer items-center ${className}`}
      title={`${value} M5 grafiğini aç`}
      aria-label={`${value} M5 grafiğini aç`}
    >
      {value}
    </Link>
  );
}
