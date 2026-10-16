// Grafikte (charts sayfası) açık pozisyonun GİRİŞ / SL / TP seviyelerini
// hesaplayan SAF yardımcı. React/DOM bağımlılığı yok → vitest ile test edilir.
//
// Kaynaklar:
//   • binance: GET /api/binance/positions → `holdings[]`
//       { asset, total, avg_cost_try, price_try, pnl_pct, active_sl_price, active_tp_price }
//   • paper: sayfadaki `allPositions` / `positions` / `autoPaperPositions`
//       ana paper: { symbol, entry, stop|llm_stop_price, take_profit|llm_take_profit_price, qty? }
//       otonom   : { symbol, entry_price, stop_loss, take_profit, status }

export type EntryLevelKind = "entry" | "sl" | "tp";
export type EntryLevelSource = "binance" | "paper";

export type EntryLevel = {
  price: number;
  kind: EntryLevelKind;
  source: EntryLevelSource;
  label: string;
  color: string;
  /** lightweight-charts lineStyle: 0 düz, 2 kesikli */
  lineStyle: 0 | 2;
};

/** Tema: giriş = vurgu rengi (globals.css #79f2b4), SL kırmızı, TP yeşil. */
export const ENTRY_LEVEL_COLORS = {
  entry: "#79f2b4",
  sl: "#ef4444",
  tp: "#22c55e",
} as const;

/** "btc_try" / "BTCTRY" / " btcTry " → "BTCTRY" */
export function normalizeSymbol(s: unknown): string {
  return String(s ?? "").replace(/_/g, "").trim().toUpperCase();
}

function posNum(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function fmtPrice(p: number): string {
  if (p >= 100) return p.toFixed(2);
  if (p >= 1) return p.toFixed(4);
  return p.toPrecision(4);
}

function fmtQty(q: number): string {
  return q >= 100 ? q.toFixed(0) : q >= 1 ? q.toFixed(2) : q.toPrecision(3);
}

function fmtPct(p: number): string {
  return `${p >= 0 ? "+" : ""}${p.toFixed(2)}%`;
}

function entryLabel(prefix: string, price: number, qty: number | null, pct: number | null): string {
  let text = `${prefix} ${fmtPrice(price)}`;
  if (qty != null) text += ` · ${fmtQty(qty)}`;
  if (pct != null) text += ` · ${fmtPct(pct)}`;
  return text;
}

function push(
  out: EntryLevel[], source: EntryLevelSource, kind: EntryLevelKind,
  price: number | null, label: string,
) {
  if (price == null) return;
  out.push({
    price, kind, source, label, color: ENTRY_LEVEL_COLORS[kind],
    lineStyle: kind === "entry" ? 0 : 2,
  });
}

/**
 * @param symbol            grafikteki sembol (BTCTRY / BTC_TRY, büyük-küçük fark etmez)
 * @param binancePositions  /api/binance/positions `holdings` dizisi (veya null)
 * @param paperPositions    paper pozisyon dizisi (ana + otonom) (veya null)
 */
export function buildEntryLevels(
  symbol: string,
  binancePositions: readonly any[] | null | undefined,
  paperPositions: readonly any[] | null | undefined,
): EntryLevel[] {
  const target = normalizeSymbol(symbol);
  const out: EntryLevel[] = [];
  if (!target) return out;

  for (const h of binancePositions ?? []) {
    if (!h) continue;
    const asset = normalizeSymbol(h.asset);
    if (!asset || asset === "TRY") continue;
    // Holding'in kendi sembolü varsa onu, yoksa {ASSET}TRY kullan.
    const sym = h.symbol ? normalizeSymbol(h.symbol) : `${asset}TRY`;
    if (sym !== target) continue;
    const entry = posNum(h.avg_cost_try);
    const pctRaw = h.pnl_pct == null ? null : Number(h.pnl_pct);
    const pct = pctRaw != null && Number.isFinite(pctRaw) ? pctRaw : null;
    push(out, "binance", "entry", entry, entry == null ? "" : entryLabel("TR Giriş", entry, posNum(h.total), pct));
    push(out, "binance", "sl", posNum(h.active_sl_price), "TR SL");
    push(out, "binance", "tp", posNum(h.active_tp_price), "TR TP");
  }

  for (const p of paperPositions ?? []) {
    if (!p || normalizeSymbol(p.symbol) !== target) continue;
    if (p.status != null && p.status !== "open") continue;
    const entry = posNum(p.entry_price ?? p.entry);
    const stop = posNum(p.stop_loss ?? p.llm_stop_price ?? p.stop);
    const tp = posNum(p.take_profit ?? p.llm_take_profit_price);
    const qty = posNum(p.qty ?? p.quantity);
    push(out, "paper", "entry", entry, entry == null ? "" : entryLabel("Giriş", entry, qty, null));
    push(out, "paper", "sl", stop, "SL");
    push(out, "paper", "tp", tp, "TP");
  }
  return out;
}
