import { describe, expect, it } from "vitest";
import {
  confluenceLabel, filterRows, istanbulToday, meanMfe, resultGroup, sourceLabel, toRateRows, type ReportRow,
} from "./signalReport";

const row = (o: Partial<ReportRow>): ReportRow => ({
  id: 1, symbol: "BTCTRY", status: "BEKLİYOR", mfe_pct: null, ...o,
});

describe("etiketler", () => {
  it("kaynak adları Türkçe", () => {
    expect(sourceLabel("velocity")).toBe("Hız");
    expect(sourceLabel("jump")).toBe("Sıçrama");
    expect(sourceLabel("early")).toBe("Erken uyarı");
    expect(sourceLabel("rising")).toBe("Yükseliş eğilimi");
    expect(sourceLabel("global")).toBe("Global teyit");
  });
  it("bilinmeyen kaynak olduğu gibi", () => expect(sourceLabel("xyz")).toBe("xyz"));
  it("teyit kademeleri", () => {
    expect(confluenceLabel("1")).toBe("Tek kaynak");
    expect(confluenceLabel("2")).toBe("2 kaynak teyitli");
    expect(confluenceLabel("4")).toBe("4'lü teyit");
  });
});

describe("resultGroup", () => {
  it("durumları gruplar", () => {
    expect(resultGroup("TAMAMEN BAŞARILI")).toBe("hit");
    expect(resultGroup("KISMİ")).toBe("partial");
    expect(resultGroup("BAŞARISIZ")).toBe("miss");
    expect(resultGroup("BEKLİYOR")).toBe("open");
    expect(resultGroup("ÖLÇÜLEMEDİ")).toBe("open");
  });
});

describe("filterRows", () => {
  // Panel bildirimi kavramı kaldırıldı: yalnız sonuç süzgeci vardır, kanal süzgeci yoktur.
  const rows = [
    row({ id: 1, status: "TAMAMEN BAŞARILI" }),
    row({ id: 2, status: "KISMİ" }),
    row({ id: 3, status: "BAŞARISIZ" }),
    row({ id: 4, status: "BEKLİYOR" }),
  ];
  it("tümü", () => expect(filterRows(rows, "all")).toHaveLength(4));
  it("sonuç süzgeci", () => expect(filterRows(rows, "hit").map((r) => r.id)).toEqual([1]));
  it("bekleyen grubu", () => expect(filterRows(rows, "open").map((r) => r.id)).toEqual([4]));
  it("kanal alanı olmayan satırlar elenmez", () => expect(filterRows(rows, "partial").map((r) => r.id)).toEqual([2]));
});

describe("toRateRows", () => {
  const stats = {
    velocity: { count: 10, evaluated: 8, success_count: 4, success_rate: 50 },
    jump: { count: 5, evaluated: 0, success_count: 0, success_rate: null },
  };
  it("etiket, oran ve sıralama (çok örnekli önce)", () => {
    const out = toRateRows(stats, sourceLabel);
    expect(out.map((r) => r.label)).toEqual(["Hız", "Sıçrama"]);
    expect(out[0]).toMatchObject({ evaluated: 8, success: 4, rate: 50 });
    expect(out[1].rate).toBeNull();
  });
  it("boş girdi", () => expect(toRateRows(undefined, sourceLabel)).toEqual([]));
  it("verilen sıra korunur", () => {
    expect(toRateRows(stats, sourceLabel, ["jump", "velocity"]).map((r) => r.key)).toEqual(["jump", "velocity"]);
  });
});

describe("meanMfe", () => {
  it("yalnız ölçülmüş satırların ortalaması", () => {
    const rows = [row({ status: "TAMAMEN BAŞARILI", mfe_pct: 4 }), row({ status: "KISMİ", mfe_pct: 2 }),
      row({ status: "BEKLİYOR", mfe_pct: null }), row({ status: "ÖLÇÜLEMEDİ", mfe_pct: 99 })];
    expect(meanMfe(rows)).toBeCloseTo(3, 6);
  });
  it("ölçülmüş yoksa null", () => expect(meanMfe([row({ status: "BEKLİYOR" })])).toBeNull());
});

describe("istanbulToday", () => {
  it("UTC+3 takvim günü (gece yarısı geçişi)", () => {
    expect(istanbulToday(new Date("2026-10-15T21:30:00Z"))).toBe("2026-10-16"); // 00:30 İstanbul
    expect(istanbulToday(new Date("2026-10-15T20:59:00Z"))).toBe("2026-10-15"); // 23:59 İstanbul
  });
});
