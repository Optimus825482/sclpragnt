import { describe, it, expect } from "vitest";
import { buildEntryLevels, normalizeSymbol, ENTRY_LEVEL_COLORS } from "./entryLevels";

const holding = { asset: "BTC", total: 0.5, avg_cost_try: 1000, pnl_pct: 2.5, active_sl_price: 900, active_tp_price: 1200 };

describe("normalizeSymbol", () => {
  it("alt çizgi ve büyük/küçük harfi yok sayar", () => {
    expect(normalizeSymbol(" btc_try ")).toBe("BTCTRY");
    expect(normalizeSymbol(null)).toBe("");
  });
});

describe("buildEntryLevels", () => {
  it("Binance holding'i için giriş, SL ve TP üretir (sembol eşleşmesi case/_ duyarsız)", () => {
    for (const s of ["BTCTRY", "btc_try", "Btc_Try"]) {
      const lv = buildEntryLevels(s, [holding], []);
      expect(lv.map((l) => l.kind)).toEqual(["entry", "sl", "tp"]);
      expect(lv.every((l) => l.source === "binance")).toBe(true);
    }
    const [entry, sl, tp] = buildEntryLevels("BTCTRY", [holding], []);
    expect(entry.price).toBe(1000);
    expect(entry.color).toBe(ENTRY_LEVEL_COLORS.entry);
    expect(entry.lineStyle).toBe(0);
    expect(entry.label).toContain("1000.00");
    expect(entry.label).toContain("+2.50%");
    expect(sl).toMatchObject({ price: 900, color: ENTRY_LEVEL_COLORS.sl, lineStyle: 2 });
    expect(tp).toMatchObject({ price: 1200, color: ENTRY_LEVEL_COLORS.tp, lineStyle: 2 });
  });

  it("eksik/geçersiz SL ve TP atlanır", () => {
    const lv = buildEntryLevels("BTCTRY", [{ ...holding, active_sl_price: null, active_tp_price: 0 }], []);
    expect(lv.map((l) => l.kind)).toEqual(["entry"]);
  });

  it("maliyeti bilinmeyen holding hiçbir seviye üretmez; farklı sembol ve TRY atlanır", () => {
    expect(buildEntryLevels("BTCTRY", [{ ...holding, avg_cost_try: null, active_sl_price: null, active_tp_price: null }], [])).toEqual([]);
    expect(buildEntryLevels("ETHTRY", [holding, { asset: "TRY", total: 10, avg_cost_try: 1 }], [])).toEqual([]);
  });

  it("paper: ana ve otonom pozisyon alan adlarını destekler, kapalı olanı atlar", () => {
    const main = { symbol: "ETHTRY", entry: 50, stop: 45, take_profit: 60, qty: 2 };
    const llm = { symbol: "ETHTRY", entry: 50, stop: 45, llm_stop_price: 47, llm_take_profit_price: 70 };
    const auto = { symbol: "ETH_TRY", status: "open", entry_price: 51, stop_loss: 49, take_profit: 55 };
    const closed = { symbol: "ETHTRY", status: "closed", entry_price: 99 };
    expect(buildEntryLevels("ETHTRY", [], [main]).map((l) => l.price)).toEqual([50, 45, 60]);
    expect(buildEntryLevels("ETHTRY", [], [llm]).map((l) => l.price)).toEqual([50, 47, 70]);
    expect(buildEntryLevels("ethtry", [], [auto, closed]).map((l) => l.price)).toEqual([51, 49, 55]);
    expect(buildEntryLevels("ETHTRY", [], [auto, closed]).every((l) => l.source === "paper")).toBe(true);
  });

  it("iki kaynak birlikte: her ikisi de döner, kaynak etiketi ayrışır", () => {
    const lv = buildEntryLevels("BTCTRY", [holding], [{ symbol: "BTCTRY", entry: 990, stop: 950 }]);
    expect(lv.filter((l) => l.source === "binance")).toHaveLength(3);
    expect(lv.filter((l) => l.source === "paper").map((l) => l.kind)).toEqual(["entry", "sl"]);
  });

  it("null/boş girdiler güvenli", () => {
    expect(buildEntryLevels("", [holding], [])).toEqual([]);
    expect(buildEntryLevels("BTCTRY", null, undefined)).toEqual([]);
  });
});
