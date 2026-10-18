import { describe, expect, it } from "vitest";
import { MAX_MISSED, pickMissedAlerts, rowKey } from "./missedAlerts";

const NOW = 1_800_000_000_000; // ms
const sec = (offset: number) => NOW / 1000 + offset;

describe("pickMissedAlerts", () => {
  const base = { sinceMs: NOW - 120_000, nowMs: NOW, seen: new Set<string>() };

  it("kesinti sırasında oluşan, taze bildirimi seçer", () => {
    const rows = [{ id: 1, symbol: "BTCTRY", detected_at: sec(-60), horizon_minutes: 10 }];
    expect(pickMissedAlerts(rows, base)).toHaveLength(1);
  });

  it("kesintiden ÖNCE oluşanı (zaten canlı görülmüş) atlar", () => {
    const rows = [{ id: 1, symbol: "BTCTRY", detected_at: sec(-600), horizon_minutes: 30 }];
    expect(pickMissedAlerts(rows, base)).toEqual([]);
  });

  it("ufku dolmuş (bayat) bildirimi atlar", () => {
    const rows = [{ id: 1, symbol: "BTCTRY", detected_at: sec(-110), horizon_minutes: 1 }];
    expect(pickMissedAlerts(rows, base)).toEqual([]);
  });

  it("ufuk bilinmiyorsa 15 dk üstü bayat sayılır", () => {
    const rows = [{ id: 1, symbol: "ETHTRY", detected_at: sec(-1000) }];
    expect(pickMissedAlerts(rows, { ...base, sinceMs: NOW - 3_600_000 })).toEqual([]);
  });

  it("zaten gösterilmiş (canlı gelen) bildirimi tekrar vermez", () => {
    const row = { id: 7, symbol: "BTCTRY", detected_at: sec(-30), horizon_minutes: 10 };
    expect(pickMissedAlerts([row], { ...base, seen: new Set([rowKey(row)]) })).toEqual([]);
  });

  it("id yoksa sembol+zaman anahtarıyla tekilleştirir", () => {
    const row = { symbol: "SOLTRY", detected_at: sec(-30), horizon_minutes: 10 };
    expect(pickMissedAlerts([row], { ...base, seen: new Set([rowKey(row)]) })).toEqual([]);
  });

  it("geçersiz zaman damgasını yok sayar", () => {
    expect(pickMissedAlerts([{ id: 1, detected_at: null }, { id: 2, detected_at: "x" }], base)).toEqual([]);
  });

  it("eskiden yeniye sıralar ve en çok MAX_MISSED döndürür (en yeniler)", () => {
    const rows = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, symbol: "X", detected_at: sec(-100 + i * 5), horizon_minutes: 10 }));
    const out = pickMissedAlerts(rows, base);
    expect(out).toHaveLength(MAX_MISSED);
    expect(out.map((r) => r.id)).toEqual([4, 5, 6, 7, 8]);
  });
});
