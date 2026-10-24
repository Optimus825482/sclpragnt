/**
 * "Bugün #3" rozeti (2026-10-24): bu coin için BUGÜN (00:00 Europe/Istanbul'dan beri) kaçıncı
 * bildirim. Sıra backend'de kalıcı bildirim geçmişinden hesaplanır (`daily_seq`); zaman dilimi,
 * tarama türü ve mod ayırt edilmez. Sayı değilse (eski gün, bilinmiyor) rozet çizilmez.
 */
export function dailySeqText(seq: number): string {
  return `Bugün #${seq}`;
}

export function dailySeqAria(seq: number): string {
  return `Bugün bu coin için ${seq}. bildirim`;
}

export const DAILY_SEQ_TITLE = "Bu coin için bugünkü kaçıncı bildirim (00:00'dan beri, tüm zaman dilimleri)";

export default function DailySeqChip({ seq, className = "" }: { seq: number | null | undefined; className?: string }) {
  if (typeof seq !== "number" || !Number.isFinite(seq)) return null;
  return (
    <span className={`u-chip u-chip-wait ${className}`.trim()} title={DAILY_SEQ_TITLE} aria-label={dailySeqAria(seq)}>
      {dailySeqText(seq)}
    </span>
  );
}
