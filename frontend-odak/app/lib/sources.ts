import type { Candidate } from "./types";

/**
 * Tespit kaynağı etiketleri — "bu sinyali hangi sistem üretti?".
 *
 * Backend `unified_signals.SOURCE_LABELS` (velocity→RADAR, jump→MACD SIRÇRAMA,
 * early→ERKEN SIRÇRAMA, rising→YÜKSELİŞ) ile hizalı; buna aday sözlüğündeki
 * `pool_source` (gainer/mover/discovery/symbol/extra) ve `strategy`
 * (daily_momentum/short_squeeze/both/velocity) etiketleri eklenir.
 */
const SOURCE_LABELS: Record<string, string> = {
  velocity: "Radar",
  jump: "MACD Sıçrama",
  early: "Erken Sıçrama",
  rising: "Yükseliş Eğilimi",
  daily_momentum: "Günlük Momentum",
  short_squeeze: "Short Squeeze",
  both: "Momentum+Squeeze",
  fusion: "Füzyon",
  combined: "Kombine",
  macd_snapshot: "MACD Anlık",
  gainer: "Kazananlar Havuzu",
  mover: "Hareketli Havuz",
  discovery: "Keşif Akışı",
  symbol: "Takip Listesi",
  extra: "Ek Havuz",
  // Pozisyon/strateji kaynakları (aktif işlemler tablosu)
  auto_paper: "Otonom",
  AUTO_PAPER: "Otonom",
  chat_prediction: "Chat Tahmini",
  CHAT_PREDICTION: "Chat Tahmini",
  LLM_PAPER: "LLM Paper",
  global_lead_lag: "Global Lead-Lag",
  GLOBAL_LEAD_LAG: "Global Lead-Lag",
};

/** Tek bir kaynak kodunu okunur etikete çevirir. */
export function sourceLabel(code: unknown): string {
  const key = String(code ?? "").trim().toLowerCase();
  if (!key) return "";
  return SOURCE_LABELS[key] || key;
}

/**
 * Bir aday/bildirim için gösterilecek kaynak etiketleri (tekrarsız, sıralı).
 * Öncelik: `sources` (bildirim zarfı) → `unified_sources` (füzyon motorları) →
 * `pool_source` → `strategy`. Hiçbiri yoksa boş dizi.
 */
export function candidateSources(item: Candidate | Record<string, unknown>): string[] {
  const r = item as Record<string, unknown>;
  const raw = (Array.isArray(r.sources) && r.sources.length ? r.sources : null)
    || (Array.isArray(r.unified_sources) && r.unified_sources.length ? r.unified_sources : null);
  const codes: string[] = [];
  if (raw) {
    for (const s of raw) codes.push(String(s));
  } else {
    if (r.pool_source) codes.push(String(r.pool_source));
    if (r.strategy) codes.push(String(r.strategy));
  }
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const code of codes) {
    const label = sourceLabel(code);
    if (label && !seen.has(label)) {
      seen.add(label);
      labels.push(label);
    }
  }
  return labels;
}
