import { describe, it, expect } from "vitest";
import { istanbulCrosshairTime, istanbulTickMark } from "./chartTime";

// 2026-10-18 04:32:00 UTC = 07:32 Türkiye saati
const T = Date.UTC(2026, 9, 18, 4, 32, 0) / 1000;

describe("chartTime — Türkiye saati (UTC+3)", () => {
  it("imleç etiketi UTC'ye 3 saat ekler", () => {
    expect(istanbulCrosshairTime(T)).toMatch(/18 Eki '26\s+07:32/);
  });
  it("çarpı etiketi saat/gün/ay/yıl", () => {
    expect(istanbulTickMark(T, 3)).toBe("07:32");
    expect(istanbulTickMark(T, 4)).toBe("07:32:00");
    expect(istanbulTickMark(T, 2)).toMatch(/18 Eki/);
    expect(istanbulTickMark(T, 1)).toMatch(/Eki/);
    expect(istanbulTickMark(T, 0)).toBe("2026");
  });
  it("gün sınırı: 22:30 UTC ertesi gün 01:30", () => {
    const t = Date.UTC(2026, 9, 18, 22, 30, 0) / 1000;
    expect(istanbulTickMark(t, 3)).toBe("01:30");
    expect(istanbulCrosshairTime(t)).toMatch(/19 Eki/);
  });
  it("sayı olmayan zaman (BusinessDay) güvenli", () => {
    expect(istanbulCrosshairTime({ year: 2026, month: 10, day: 18 })).toBe("");
    expect(istanbulTickMark({ year: 2026 }, 3)).toBeNull();
  });
});
