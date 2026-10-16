// `lib/usePortfolioSummary.ts` — bant verisinin SAF toplama/normalize fonksiyonları.
//
// Hook'un kendisi (REST + WS) bilerek test edilmez (jsdom yok; vitest kapsamı
// `lib/` saf matematiği). K/Z kuralı `pnl.ts` ile aynıdır (net, gidiş-dönüş
// komisyonlu); komisyon oranı testte 0.001 sabitlenir.

import { describe, it, expect, beforeEach } from "vitest";
import { applyCommissionPct, resetCommissionPct } from "./pnl";
import { aggregateOpenPositions, applyPaperSnapshot, normalizeBand, type PortfolioBandData } from "./usePortfolioSummary";

beforeEach(() => {
  resetCommissionPct();
  applyCommissionPct(0.001);
});

// net = (c-e)*q − 0.001*q*(e+c)
const A = { symbol: "AAATRY", side: "LONG", entry: 100, current: 110, quantity: 5 }; // 50 − 1.05 = 48.95
const B = { symbol: "BBBTRY", entry: 10, current: 9, quantity: 10 }; // −10 − 0.19 = −10.19

describe("aggregateOpenPositions", () => {
  it("net K/Z ve % (giriş değeri tabanı) toplar", () => {
    const r = aggregateOpenPositions([A, B]);
    expect(r.count).toBe(2);
    expect(r.pnlTry).toBeCloseTo(48.95 - 10.19, 9);
    expect(r.pnlPct).toBeCloseTo(((48.95 - 10.19) / (500 + 100)) * 100, 9);
  });

  it("pozisyon yoksa meşru 0, veri yok değil", () => {
    expect(aggregateOpenPositions([])).toEqual({ count: 0, pnlTry: 0, pnlPct: 0 });
    expect(aggregateOpenPositions(null)).toEqual({ count: 0, pnlTry: 0, pnlPct: 0 });
  });

  it("ölçülemeyen satır toplama girmez; hiçbiri ölçülemezse null", () => {
    const partial = aggregateOpenPositions([A, { entry: 5, current: null, quantity: 1 }]);
    expect(partial.count).toBe(2);
    expect(partial.pnlTry).toBeCloseTo(48.95, 9);
    expect(partial.pnlPct).toBeCloseTo((48.95 / 500) * 100, 9);

    const none = aggregateOpenPositions([{ entry: 5, current: 0, quantity: 1 }]);
    expect(none).toEqual({ count: 1, pnlTry: null, pnlPct: null });
  });

  it("SHORT yönünde fiyat düşüşü kârdır", () => {
    const r = aggregateOpenPositions([{ side: "SHORT", entry: 100, current: 90, quantity: 1 }]);
    expect(r.pnlTry).toBeCloseTo(10 - 0.001 * 190, 9);
  });
});

describe("normalizeBand", () => {
  it("Binance yanıtını olduğu gibi (sunucu değerleri) eşler", () => {
    const d = normalizeBand({
      source: "binance", total_try: 2552, free_try: 1200.5, open_count: 3,
      unrealized_try: 80, unrealized_pct: 8.7, daily_pnl_try: -4.2, updated_at: 123,
      positions: [A], // Binance'te yok sayılır
    });
    expect(d).toEqual({
      source: "binance", totalTry: 2552, freeTry: 1200.5, openCount: 3,
      unrealizedTry: 80, unrealizedPct: 8.7, dailyPnlTry: -4.2, updatedAt: 123, positions: null,
    });
  });

  it("Paper'da K/Z ham pozisyonlardan kanonik formülle yeniden hesaplanır", () => {
    const d = normalizeBand({
      source: "paper", total_try: 5100, free_try: 4000, open_count: 99,
      unrealized_try: 12345, unrealized_pct: 99, daily_pnl_try: 7, positions: [A, B],
    })!;
    expect(d.source).toBe("paper");
    expect(d.openCount).toBe(2); // sunucunun open_count'u değil, liste
    expect(d.unrealizedTry).toBeCloseTo(48.95 - 10.19, 9);
    expect(d.dailyPnlTry).toBe(7);
  });

  it("eksik/geçersiz alanlar null olur (0 değil); bilinmeyen kaynak paper", () => {
    const d = normalizeBand({ total_try: null, free_try: "x" as unknown as number, daily_pnl_try: undefined })!;
    expect(d.source).toBe("paper");
    expect(d.totalTry).toBeNull();
    expect(d.freeTry).toBeNull();
    expect(d.dailyPnlTry).toBeNull();
    expect(normalizeBand(null)).toBeNull();
  });
});

describe("applyPaperSnapshot", () => {
  const prev: PortfolioBandData = {
    source: "paper", totalTry: 100, freeTry: 50, openCount: 0,
    unrealizedTry: 0, unrealizedPct: 0, dailyPnlTry: 3.5, updatedAt: 1, positions: [],
  };

  it("WS anlık görüntüsüyle toplam/serbest/pozisyon/K-Z yenilenir, günlük K/Z korunur", () => {
    const next = applyPaperSnapshot(prev, {
      total_value: 5100, try: 4000, positions: [A], auto_paper_positions: [B],
    })!;
    expect(next.totalTry).toBe(5100);
    expect(next.freeTry).toBe(4000);
    expect(next.openCount).toBe(2);
    expect(next.unrealizedTry).toBeCloseTo(48.95 - 10.19, 9);
    expect(next.dailyPnlTry).toBe(3.5);
  });

  it("alan eksikse önceki toplam/serbest korunur", () => {
    const next = applyPaperSnapshot(prev, { positions: [], auto_paper_positions: [] })!;
    expect(next.totalTry).toBe(100);
    expect(next.freeTry).toBe(50);
    expect(next.unrealizedTry).toBe(0);
  });

  it("Binance bandında veya veri yokken değişiklik yapmaz (null)", () => {
    expect(applyPaperSnapshot({ ...prev, source: "binance" }, { total_value: 1 })).toBeNull();
    expect(applyPaperSnapshot(null, { total_value: 1 })).toBeNull();
    expect(applyPaperSnapshot(prev, null)).toBeNull();
  });
});
