import { describe, expect, it } from "vitest";
import { WATCH_MAX, addWatchItem, hasWatchItem, normalizeWatchList, removeWatchItem } from "./useWatchPrefs";

const it1 = (symbol: string, price = 1, at = 100) => ({ symbol, price, at });

describe("normalizeWatchList", () => {
  it("dizi değilse boş", () => {
    expect(normalizeWatchList(null)).toEqual([]);
    expect(normalizeWatchList({})).toEqual([]);
  });
  it("sembolü büyütür, tekrarı ve boşu atar, bozuk sayıyı 0 yapar", () => {
    const out = normalizeWatchList([{ symbol: "straxtry", price: "2.5", at: 5 }, { symbol: "STRAXTRY", price: 9, at: 6 }, { symbol: "", price: 1 }, null, { symbol: "BTCTRY", price: "x", at: -1 }]);
    expect(out).toEqual([{ symbol: "STRAXTRY", price: 2.5, at: 5 }, { symbol: "BTCTRY", price: 0, at: 0 }]);
  });
  it("en fazla 30", () => {
    const many = Array.from({ length: 40 }, (_, i) => it1(`S${i}TRY`));
    expect(normalizeWatchList(many)).toHaveLength(WATCH_MAX);
  });
});

describe("add/remove/has", () => {
  it("yeni başa eklenir, aynı sembol değiştirilir", () => {
    const l = addWatchItem([it1("AAATRY", 1)], it1("BBBTRY", 2));
    expect(l.map((x) => x.symbol)).toEqual(["BBBTRY", "AAATRY"]);
    const l2 = addWatchItem(l, it1("AAATRY", 7));
    expect(l2).toEqual([it1("AAATRY", 7), it1("BBBTRY", 2)]);
  });
  it("30'u aşınca en eski düşer", () => {
    let l: ReturnType<typeof normalizeWatchList> = [];
    for (let i = 0; i < 31; i++) l = addWatchItem(l, it1(`S${i}TRY`));
    expect(l).toHaveLength(WATCH_MAX);
    expect(hasWatchItem(l, "S0TRY")).toBe(false);
    expect(hasWatchItem(l, "s30try")).toBe(true);
  });
  it("remove", () => {
    expect(removeWatchItem([it1("AAATRY"), it1("BBBTRY")], "aaatry").map((x) => x.symbol)).toEqual(["BBBTRY"]);
  });
});

// 2026-10-18 (denetim #3): WS kapsamı dışındaki semboller REST ile yoklanır.
import { symbolsMissingFromWs } from "./useWatchPrices";
describe("symbolsMissingFromWs", () => {
  it("son WS yayınında olmayanları döndürür", () => {
    expect(symbolsMissingFromWs(["AAATRY", "BBBTRY", "CCCTRY"], new Set(["BBBTRY"]))).toEqual(["AAATRY", "CCCTRY"]);
  });
  it("WS hepsini kapsıyorsa boş", () => {
    expect(symbolsMissingFromWs(["AAATRY"], new Set(["AAATRY", "ZZZTRY"]))).toEqual([]);
  });
  it("WS hiç yayın yapmadıysa hepsi eksik", () => {
    expect(symbolsMissingFromWs(["AAATRY", "BBBTRY"], new Set())).toEqual(["AAATRY", "BBBTRY"]);
  });
});
