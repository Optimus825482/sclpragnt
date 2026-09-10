// Sayfa bazlı kopyalanan biçimlendirme kurallarının tek kaynağı.
// Aynı fiyat/ zaman değeri farklı sayfalarda farklı hassasiyetle basılmaması
// için tüm bileşenler bu modülü kullanmalıdır.

/**
 * Zaman damgasını milisaniyeye normalize eder. Backend karışık birim
 * gönderir (epoch saniye veya ms); eski `ts < 10_000_000_000 ? ts * 1000 : ts`
 * sezgiseli 8 sayfada kopyalanmıştı — artık burada tek yerde.
 */
export function toMs(ts: number | string | null | undefined): number {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value < 10_000_000_000 ? value * 1000 : value;
}

/** tr-TR kısa tarih + saat (tarayıcı yerel dilimi). */
export function fmtDateTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

/** tr-TR yalnız tarih. */
export function fmtDate(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleDateString("tr-TR");
}

/**
 * Paylaşılan fiyat hassasiyeti: <1 → 6 hane, <100 → 4 hane, <1000 → 3 hane,
 * aksi 2 hane. Grafik bileşenlerindeki `chartShared.pricePrecision` ile AYNI
 * kural olmalı; aynı fiyat farklı sayfalarda farklı yuvarlanmasın.
 */
export function formatPrice(value: number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const digits = abs < 1 ? 6 : abs < 100 ? 4 : abs < 1000 ? 3 : 2;
  return n.toLocaleString("tr-TR", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

/** Türk Lirası biçimi: ₺ sonekli, tr-TR gruplama. */
export function formatTL(value: number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}₺`;
}

/** Yerel (UTC değil) YYYY-MM-DD — date input default değeri için. */
export function localDateInput(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}
