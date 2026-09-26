/**
 * Skor (0-100 panel ölçeği) renk dili — TEK KAYNAK (UX denetimi 2026-09-27).
 *
 * Denetim bulgusu: aynı skor Monitoring'de sarı, Grafik radar panelinde
 * kırmızı görünüyordu (eşikler sayfa başına kopyalanmıştı). Eşikler
 * Monitoring kalibrasyonundan gelir (SCORE_TONE_GREEN/YELLOW).
 */

/** Yeşil (güçlü) eşiği — Monitoring kalibrasyonu. */
export const SCORE_TONE_GREEN = 71.5;
/** Sarı (sınırda) eşiği — Monitoring kalibrasyonu. */
export const SCORE_TONE_YELLOW = 68.2;

/** Skor → renk sınıfı. null/NaN → nötr gri. */
export function scoreToneClass(score: number | null | undefined): string {
  const v = score == null ? null : Number(score);
  if (v == null || !Number.isFinite(v)) return "text-bunker-muted";
  return v >= SCORE_TONE_GREEN ? "text-neon-green"
    : v >= SCORE_TONE_YELLOW ? "text-yellow-300"
      : "text-neon-red";
}

/** Skor → "85.4" metni. null/NaN → "—". */
export function scoreToneText(score: number | null | undefined): string {
  const v = score == null ? null : Number(score);
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(1);
}
