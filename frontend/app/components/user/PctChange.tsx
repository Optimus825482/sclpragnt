"use client";
import { pctChange } from "../../lib/userUi";

/** ▲ yeşil / ▼ kırmızı yüzde değişim; hesaplanamazsa "—". */
export default function PctChange({ base, live }: { base: number | null | undefined; live: number | null | undefined }) {
  const p = pctChange(base, live);
  if (p == null) return <span className="text-bunker-muted">—</span>;
  const up = p >= 0;
  return (
    <span className={up ? "text-neon-green" : "text-neon-red"}>
      {up ? "▲" : "▼"} {up ? "+" : ""}{p.toFixed(2).replace(".", ",")}%
    </span>
  );
}
