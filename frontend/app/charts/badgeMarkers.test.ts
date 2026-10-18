import { describe, expect, it } from "vitest";
import { BADGE_GAP, BADGE_H, BADGE_TIP, badgeBox, badgeFromSignal, drawBadges } from "./badgeMarkers";
import type { Bar } from "./signals";

const bar: Bar = { time: 100, open: 10, high: 12, low: 9, close: 11, volume: 1 };

describe("badgeFromSignal", () => {
  it("alış → mumun altına yeşil BUY rozeti; satış → üstüne kırmızı SELL", () => {
    expect(badgeFromSignal({ time: 100, type: "buy", badge: true }, bar)).toEqual({
      time: 100, price: 9, text: "BUY", bg: "#16a34a", fg: "#ffffff", above: false,
    });
    expect(badgeFromSignal({ time: 100, type: "sell", badge: true, text: "ÇIK" }, bar)).toMatchObject({
      price: 12, text: "ÇIK", bg: "#dc2626", above: true,
    });
  });
  it("rozet istemeyen sinyal ya da mum yok → null", () => {
    expect(badgeFromSignal({ time: 100, type: "buy" }, bar)).toBeNull();
    expect(badgeFromSignal({ time: 100, type: "buy", badge: true }, undefined)).toBeNull();
  });
  it("sinyal rengi zemine geçer", () => {
    expect(badgeFromSignal({ time: 100, type: "buy", badge: true, color: "#123456" }, bar)!.bg).toBe("#123456");
  });
});

describe("badgeBox", () => {
  it("altta: kutu mum ucunun altında, gap + uç kadar boşlukla; genişlik metin + dolgu, en az 28", () => {
    const b = badgeBox(20, 100, 50, false);
    expect(b).toEqual({ left: 83, top: 50 + BADGE_GAP + BADGE_TIP, w: 34, h: BADGE_H });
    expect(badgeBox(4, 100, 50, false).w).toBe(28);
  });
  it("üstte: kutu mum ucunun üstünde biter", () => {
    const b = badgeBox(20, 100, 50, true);
    expect(b.top + b.h + BADGE_TIP + BADGE_GAP).toBe(50);
  });
});


describe("drawBadges (sahte 2D bağlam)", () => {
  const fakeCtx = () => {
    const calls: string[] = [];
    const ctx: any = new Proxy({}, {
      get(_t, prop: string) {
        if (prop === "measureText") return (txt: string) => ({ width: txt.length * 7 });
        return (..._a: unknown[]) => { calls.push(prop); };
      },
      set() { return true; },
    });
    return { ctx: ctx as CanvasRenderingContext2D, calls };
  };
  it("görünür rozetleri çizer (hap + uç + yazı), alan dışını atlar", () => {
    const { ctx, calls } = fakeCtx();
    const n = drawBadges(ctx, [
      { x: 100, y: 50, text: "BUY", bg: "#16a34a", fg: "#fff", above: false },
      { x: 900, y: 50, text: "BUY", bg: "#16a34a", fg: "#fff", above: false },   // alan dışı (width 600)
      { x: NaN, y: 50, text: "BUY", bg: "#16a34a", fg: "#fff", above: true },
    ], 600);
    expect(n).toBe(1);
    expect(calls.filter((c) => c === "fillText")).toHaveLength(1);
    expect(calls.filter((c) => c === "fill")).toHaveLength(1);
    expect(calls.filter((c) => c === "stroke")).toHaveLength(1);
    expect(calls[0]).toBe("save");
    expect(calls[calls.length - 1]).toBe("restore");
  });
});
