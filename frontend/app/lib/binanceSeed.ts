/**
 * 2026-10-18 (basit arayüz): Binance TR sayfası ilk boyamada üst bandın (`usePortfolioSummary`)
 * zaten elinde olan, WS tikleriyle canlı tutulan varlık listesinden tohumlanır; `/api/binance/positions`
 * yanıtı gelince gerçek satırlar (free/locked, açık emirler) tohumun yerini alır.
 *
 * Tohum satırlarında free/locked AYRIMI bilinmez (bant yalnız toplam adedi taşır) → satış bu
 * satırlardan AÇILMAZ (UserBinance `liveEnabled`'ı kapatır); yalnız görüntü içindir.
 */
import type { PortfolioBandData } from "./usePortfolioSummary";
import type { Holding } from "./tradeApi";
import { grossOpenPnlTry } from "./pnl";

const round2 = (n: number) => Math.round(n * 100) / 100;

/** Bant verisinden görüntü amaçlı varlık satırları; Binance kaynağı değilse ya da varlık yoksa null. */
export function seedHoldingsFromBand(band: PortfolioBandData | null | undefined): Holding[] | null {
  if (!band || band.source !== "binance") return null;
  const rows = band.holdings ?? [];
  if (!rows.length && band.freeTry == null) return null;
  const out: Holding[] = [];
  for (const h of rows) {
    const asset = String(h.asset ?? "").toUpperCase();
    if (!asset || asset === "TRY" || !(h.qty > 0) || !(h.price_try > 0)) continue;
    const avg = h.avg_cost_try ?? null;
    out.push({
      asset,
      free: h.qty,
      locked: 0,
      total: h.qty,
      price_try: h.price_try,
      value_try: round2(h.qty * h.price_try),
      avg_cost_try: avg,
      pnl_try: avg != null && avg > 0 ? grossOpenPnlTry(avg, h.price_try, h.qty) : null,
      pnl_pct: avg != null && avg > 0 ? ((h.price_try - avg) / avg) * 100 : null,
      active_orders: [],
    });
  }
  if (band.freeTry != null) {
    out.push({ asset: "TRY", free: band.freeTry, locked: 0, total: band.freeTry, price_try: 1, value_try: round2(band.freeTry) });
  }
  out.sort((a, b) => (b.value_try ?? 0) - (a.value_try ?? 0));
  return out;
}
