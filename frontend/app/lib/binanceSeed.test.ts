import { describe, expect, it } from "vitest";
import { seedHoldingsFromBand } from "./binanceSeed";
import type { PortfolioBandData } from "./usePortfolioSummary";

const band = (over: Partial<PortfolioBandData>): PortfolioBandData => ({
  source: "binance",
  totalTry: 1000,
  freeTry: 250,
  dailyPnlTry: null,
  updatedAt: null,
  openCount: 1,
  unrealizedTry: null,
  unrealizedPct: null,
  positions: null,
  holdings: [{ asset: "sol", qty: 2, price_try: 300, avg_cost_try: 250, counted: true }],
  baseTotalTry: 1000,
  liveAt: null,
  ...over,
});

describe("seedHoldingsFromBand", () => {
  it("bant varlıklarını görüntü satırına çevirir (K/Z brüt, TRY satırı serbest bakiye)", () => {
    const rows = seedHoldingsFromBand(band({}))!;
    expect(rows.map((r) => r.asset)).toEqual(["SOL", "TRY"]);
    const sol = rows[0];
    expect(sol.total).toBe(2);
    expect(sol.value_try).toBe(600);
    expect(sol.pnl_try).toBeCloseTo(100, 6);
    expect(sol.pnl_pct).toBeCloseTo(20, 6);
    expect(rows[1]).toMatchObject({ asset: "TRY", free: 250, total: 250, price_try: 1 });
  });
  it("paper kaynağında ya da veri yokken null", () => {
    expect(seedHoldingsFromBand(null)).toBeNull();
    expect(seedHoldingsFromBand(band({ source: "paper" }))).toBeNull();
    expect(seedHoldingsFromBand(band({ holdings: [], freeTry: null }))).toBeNull();
  });
  it("geçersiz satırları atlar, maliyet yoksa K/Z null", () => {
    const rows = seedHoldingsFromBand(band({
      holdings: [
        { asset: "x", qty: 0, price_try: 5 },
        { asset: "y", qty: 1, price_try: 0 },
        { asset: "btc", qty: 0.5, price_try: 4_000_000, avg_cost_try: null },
      ],
      freeTry: null,
    }))!;
    expect(rows.map((r) => r.asset)).toEqual(["BTC"]);
    expect(rows[0].pnl_try).toBeNull();
    expect(rows[0].value_try).toBe(2_000_000);
  });
  it("değere göre azalan sıralar", () => {
    const rows = seedHoldingsFromBand(band({
      holdings: [{ asset: "a", qty: 1, price_try: 10 }, { asset: "b", qty: 1, price_try: 500 }],
      freeTry: 100,
    }))!;
    expect(rows.map((r) => r.asset)).toEqual(["B", "TRY", "A"]);
  });
});
