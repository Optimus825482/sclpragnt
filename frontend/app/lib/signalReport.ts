/** Kullanıcı sinyal başarı raporu için saf yardımcılar (node'da test edilir). */
import { statusLabel } from "./userUi";

export type ReportRow = {
  id: number;
  symbol: string;
  status: string;
  /** Geriye dönük alan: rapor artık yalnız push bildirimlerini döndürür (panel bildirimi yok). */
  sent_via_push?: boolean;
  mfe_pct: number | null;
  detected_at?: number;
  target_pct?: number;
  horizon_minutes?: number;
  sources?: string[];
  score?: number;
  price?: number;
};

export type ResultFilter = "all" | "hit" | "partial" | "miss" | "open";

const SOURCE_LABELS: Record<string, string> = {
  velocity: "Hız",
  jump: "Sıçrama",
  early: "Erken uyarı",
  rising: "Yükseliş eğilimi",
  global: "Global teyit",
};

export function sourceLabel(key: string): string {
  return SOURCE_LABELS[key] ?? key;
}

export function confluenceLabel(key: string): string {
  if (key === "1") return "Tek kaynak";
  if (key === "4") return "4'lü teyit";
  return `${key} kaynak teyitli`;
}

export function resultGroup(status: string): Exclude<ResultFilter, "all"> {
  switch (status) {
    case "TAMAMEN BAŞARILI": return "hit";
    case "KISMİ": return "partial";
    case "BAŞARISIZ": return "miss";
    default: return "open";   // BEKLİYOR + ÖLÇÜLEMEDİ
  }
}

export function filterRows(rows: ReportRow[], result: ResultFilter): ReportRow[] {
  return rows.filter((r) => result === "all" || resultGroup(r.status) === result);
}

export type RateRow = { key: string; label: string; count: number; evaluated: number; success: number; rate: number | null };
type StatEntry = { count?: number | null; evaluated?: number | null; success_count?: number | null; success_rate?: number | null };

/** Backend istatistik sözlüğünü çubuk satırlarına çevirir. Sıra verilmezse çok örnekli önce. */
export function toRateRows(
  stats: Record<string, StatEntry> | null | undefined,
  label: (key: string) => string,
  order?: string[],
): RateRow[] {
  if (!stats) return [];
  const keys = order ?? Object.keys(stats).sort((a, b) => Number(stats[b]?.evaluated ?? 0) - Number(stats[a]?.evaluated ?? 0));
  return keys.filter((k) => stats[k]).map((k) => {
    const s = stats[k];
    const evaluated = Number(s.evaluated ?? 0);
    const rate = s.success_rate;
    return {
      key: k,
      label: label(k),
      count: Number(s.count ?? 0),
      evaluated,
      success: Number(s.success_count ?? 0),
      rate: evaluated > 0 && rate != null && Number.isFinite(Number(rate)) ? Number(rate) : null,
    };
  });
}

const MEASURED = new Set(["TAMAMEN BAŞARILI", "KISMİ", "BAŞARISIZ"]);

/** Ölçülmüş satırların ortalama en yüksek getirisi (MFE, %). Ölçülmüş yoksa null. */
export function meanMfe(rows: ReportRow[]): number | null {
  const vals = rows.filter((r) => MEASURED.has(r.status) && r.mfe_pct != null).map((r) => Number(r.mfe_pct));
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

/** İstanbul (UTC+3) takvim günü, YYYY-MM-DD. */
export function istanbulToday(now: Date = new Date()): string {
  return new Date(now.getTime() + 3 * 3600 * 1000).toISOString().slice(0, 10);
}

export { statusLabel };
