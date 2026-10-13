import type { Candidate, DailyOpportunity } from "./types";
import { candidateSources, sourceLabel } from "./sources";

/**
 * İki farklı backend şeklini TEK görünüme indirger.
 *
 *   - `/api/monitoring/state`    → `price`, `change_24h`, `panel_score`/`unified_score`, `ceiling_pct`, `volume_ratio`
 *   - `/api/daily-rising/state`  → `current_price`, `change_pct`, `quality_score`, `potential_pct`
 *
 * Panel her iki kaynağı da gösterebildiği için kart/detay bileşenleri HAM alan
 * adlarına değil bu görünüme bağlanır. Alan yoksa `null` → arayüz "—" basar.
 */
export type OpportunityView = {
  symbol: string;          // tam sembol, ör. SOLTRY
  base: string;            // SOL (TRY/USDT soneki atılmış)
  price: number | null;
  changePct: number | null;
  potentialPct: number | null;
  targetPct: number | null;
  volumeRatio: number | null; // Hacim Artışı (×)
  strength: number | null;    // Sinyal Gücü / skor
  horizonMinutes: number | null;
  strategy: string | null;
  status: string | null;
  createdAt: number | null;
  entryPrice: number | null;
  ceilingPrice: number | null;
  potentialPrice: number | null;
  targetProbability: number | null;
  sources: string[];
  confirmSources: string[];
  confirmLayers: string[];
  opposingSources: string[];
  sourceEvidence: Record<string, unknown>;
  stopLoss: number | null;
  stopLossPct: number | null;
  scoreComponents: Array<{ label: string; value: number }>;
};

function num(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function firstNum(...values: unknown[]): number | null {
  for (const v of values) {
    const n = num(v);
    if (n != null) return n;
  }
  return null;
}
function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/** Sembol sonekini (TRY/USDT) atarak taban varlığı verir. */
export function baseAsset(symbol: string): string {
  const s = String(symbol || "").toUpperCase();
  if (s.endsWith("TRY")) return s.slice(0, -3);
  if (s.endsWith("USDT")) return s.slice(0, -4);
  return s;
}

export function toOpportunityView(raw: Candidate | DailyOpportunity | Record<string, unknown>): OpportunityView {
  const r = raw as Record<string, unknown>;
  const symbol = String(r.symbol ?? "").toUpperCase();
  
  // Sinyal gücü: 0-1 arası geldiyse 100 ile çarp, yoksa direkt al
  let rawStrength = firstNum(r.quality_score, r.panel_score, r.unified_score, r.scan_score, r.velocity_score, r.score);
  if (rawStrength != null && rawStrength > 0 && rawStrength <= 1.0) {
    rawStrength = Math.round(rawStrength * 100);
  }

  return {
    symbol,
    base: baseAsset(symbol),
    price: firstNum(r.current_price, r.price, r.last),
    // Değişim: change_pct | change_24h | (pulse) return_1m_pct | return_20s_pct
    changePct: firstNum(r.change_pct, r.change_24h, r.return_1m_pct, r.return_20s_pct),
    // Potansiyel: potential_pct | tavan (ceiling_pct) | hedef (target_pct)
    potentialPct: firstNum(r.potential_pct, r.ceiling_pct, r.target_pct),
    targetPct: num(r.target_pct),
    volumeRatio: firstNum(r.volume_ratio, r.volume_surge_ratio, r.surge_mult),
    strength: rawStrength,
    horizonMinutes: num(r.horizon_minutes),
    strategy: str(r.strategy),
    status: str(r.status),
    createdAt: firstNum(r.detected_at, r.created_at, r.last_closed_at),
    entryPrice: num(r.entry_price),
    ceilingPrice: num(r.ceiling_price),
    potentialPrice: num(r.potential_price),
    targetProbability: num(r.target_probability),
    sources: candidateSources(r),
    confirmSources: (Array.isArray(r.supporting_sources) ? r.supporting_sources : []).map(sourceLabel).filter(Boolean),
    confirmLayers: (Array.isArray(r.confirm_layers) ? r.confirm_layers : []).map(sourceLabel).filter(Boolean),
    opposingSources: (Array.isArray(r.opposing_sources) ? r.opposing_sources : Array.isArray(r.conflicting_sources) ? r.conflicting_sources : []).map(sourceLabel).filter(Boolean),
    sourceEvidence: r.source_evidence != null && typeof r.source_evidence === "object" ? r.source_evidence as Record<string, unknown> : {},
    stopLoss: num(r.stop_loss),
    stopLossPct: num(r.stop_loss_pct),
    scoreComponents: [
      ["Kalite", r.quality_score], ["Birleşik", r.scan_score], ["Hız", r.velocity_score], ["Panel", r.panel_score],
    ].flatMap(([label, value]) => {
      const score = num(value);
      return score == null ? [] : [{ label: String(label), value: score }];
    }),
  };
}

