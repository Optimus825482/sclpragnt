/**
 * WS kesintisi sırasında kaçırılan radar bildirimlerini REST geçmişinden seçer.
 * Saf fonksiyon (testli): `RadarAlertModal` yeniden bağlanınca `/api/monitoring/notifications`
 * satırlarını buradan geçirir.
 */
export type NotificationHistoryRow = {
  id?: string | number;
  symbol?: string;
  detected_at?: number | string | null;
  horizon_minutes?: number | null;
  message?: string;
  [key: string]: unknown;
};

/** Ufuk bilinmiyorsa bildirim bu süreden eskiyse "bayat" sayılır ve gösterilmez. */
export const DEFAULT_MAX_AGE_SEC = 15 * 60;
/** En çok bu kadar telafi bildirimi (modal kuyruğu zaten 5 ile sınırlı). */
export const MAX_MISSED = 5;
/** Saat/yayın gecikmesi payı: kesinti başlangıcından bu kadar önceki kayıtlar da kaçırılmış sayılır. */
const SLACK_SEC = 3;

export function rowKey(row: NotificationHistoryRow): string {
  if (row.id != null && row.id !== "") return `id:${row.id}`;
  return symTimeKey(row);
}

/** id'siz yayınları DB satırıyla eşlemek için ikinci anahtar (sembol + saniye). */
export function symTimeKey(row: NotificationHistoryRow): string {
  return `sym:${row.symbol ?? ""}|${Math.floor(Number(row.detected_at) || 0)}`;
}

export function pickMissedAlerts(
  history: readonly NotificationHistoryRow[],
  opts: { sinceMs: number; nowMs: number; seen: ReadonlySet<string> },
): NotificationHistoryRow[] {
  const sinceSec = opts.sinceMs / 1000 - SLACK_SEC;
  const nowSec = opts.nowMs / 1000;
  const picked = history.filter((row) => {
    const detected = Number(row.detected_at);
    if (!Number.isFinite(detected) || detected <= 0) return false;
    if (detected < sinceSec) return false; // kesintiden önce: zaten canlı görülmüş olmalı
    const horizonSec = Number(row.horizon_minutes) > 0 ? Number(row.horizon_minutes) * 60 : DEFAULT_MAX_AGE_SEC;
    if (nowSec - detected > Math.min(horizonSec, DEFAULT_MAX_AGE_SEC)) return false; // bayat
    return !opts.seen.has(rowKey(row)) && !opts.seen.has(symTimeKey(row));
  });
  // Eskiden yeniye göster; çok fazlaysa en yenilerini tut.
  picked.sort((a, b) => Number(a.detected_at) - Number(b.detected_at));
  return picked.slice(-MAX_MISSED);
}
