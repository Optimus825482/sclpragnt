// Biçimlendirme — koyu tema frontend'inin `lib/format.ts` sözleşmesiyle AYNI
// kurallar (tek kaynak ilkesi). Veri yoksa "—" (0 DEĞİL).

export function toMs(ts: number | string | null | undefined): number {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value < 10_000_000_000 ? value * 1000 : value;
}

export function fmtClockTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString("tr-TR");
}

export function fmtDateTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

export function pricePrecision(value: number | null | undefined): number {
  if (value == null) return 2;
  const abs = Math.abs(value);
  if (!Number.isFinite(abs)) return 2;
  if (abs < 1) return 6;
  if (abs < 100) return 4;
  if (abs < 1000) return 3;
  return 2;
}

/** Fiyat biçimi (tr-TR). Eksik/≤0 → "—". */
export function formatPrice(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: pricePrecision(n),
  });
}

/** Sabit ondalıklı sayı (adet, miktar). Eksik/geçersiz → "—". */
export function formatFixed(value: number | string | null | undefined, digits = 2): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Türk Lirası: ₺ önek, 2 ondalık. */
export function formatTL(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  return `₺${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** İşaretli TL: kâr `+₺…`, zarar `-₺…`. */
export function formatSignedTL(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const magnitude = formatTL(Math.abs(n));
  if (n < 0) return `-${magnitude}`;
  if (n > 0) return `+${magnitude}`;
  return magnitude;
}

/**
 * YÜZDE alanları için biçim. Backend bu alanları ÇOĞUNLUKLA hazır yüzde olarak
 * döndürür (`change_pct`, `potential_pct`, `net_pct`, `mfe_pct` … → 3.97 = %3,97).
 * Bu yüzden çarpmadan basılır. `sign` ile pozitifte başa işaret konur.
 *
 * İŞARET YERİ: negatifte eksi, yüzde işaretinden ÖNCE gelir → `-%3.97`
 * (Türkçe yazım). Eskiden `%-3.97` çıkıyordu.
 */
export function formatPct(value: number | string | null | undefined, digits = 2, sign = false): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  const neg = n < 0 || Object.is(n, -0);
  const prefix = neg ? "-" : sign && n > 0 ? "+" : "";
  return `${prefix}%${Math.abs(n).toFixed(digits)}`;
}

/** Büyük sayıları kısaltır: 1.25B, 340M, 12.4K. Eksik/geçersiz → "—". */
export function formatCompact(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
}
