import { describe, expect, it } from "vitest";
import {
  SL_PCT_CHIPS, TP_PCT_CHIPS, amountFromFree, checkSlTp, checkSlTpPlan, describeBuyFill, pctFromPrice, priceAtPct, pricesFromPlan, rrFromPrices, slPctFromPrice,
} from "./buyDialogMath";

describe("slPctFromPrice", () => {
  it("SL fiyatından yüzde mesafe hesaplar", () => {
    expect(slPctFromPrice(100, 97)).toBe(3);
    expect(slPctFromPrice(2, 1.9)).toBe(5);
  });
  it("geçersiz girdide ya da SL >= fiyat iken null", () => {
    expect(slPctFromPrice(100, 100)).toBeNull();
    expect(slPctFromPrice(100, 110)).toBeNull();
    expect(slPctFromPrice(0, 1)).toBeNull();
    expect(slPctFromPrice(100, NaN)).toBeNull();
    expect(slPctFromPrice(100, -1)).toBeNull();
  });
});

describe("rrFromPrices", () => {
  it("kazanç/risk oranını hesaplar", () => {
    expect(rrFromPrices(100, 97, 106)).toBe(2);
    expect(rrFromPrices(100, 98, 103)).toBe(1.5);
  });
  it("yön hatalıysa null", () => {
    expect(rrFromPrices(100, 101, 106)).toBeNull();
    expect(rrFromPrices(100, 97, 99)).toBeNull();
    expect(rrFromPrices(100, 97, 100)).toBeNull();
  });
});

describe("pricesFromPlan", () => {
  it("sunucu fiyatlarını aynen verir", () => {
    expect(pricesFromPlan(100, { sl_price: 97, tp_price: 106, sl_pct: 3, rr: 2 })).toEqual({ sl: 97, tp: 106 });
  });
  it("fiyat yoksa sl_pct ve rr'den üretir (SL/TP dönüşümüyle tutarlı)", () => {
    const { sl, tp } = pricesFromPlan(100, { sl_pct: 3, rr: 2 });
    expect(sl).toBeCloseTo(97, 8);
    expect(tp).toBeCloseTo(106, 8);
    expect(slPctFromPrice(100, sl as number)).toBe(3);
    expect(rrFromPrices(100, sl as number, tp as number)).toBe(2);
  });
  it("eksik bilgide null", () => {
    expect(pricesFromPlan(0, { sl_pct: 3, rr: 2 })).toEqual({ sl: null, tp: null });
    expect(pricesFromPlan(100, {})).toEqual({ sl: null, tp: null });
  });
});

describe("checkSlTp", () => {
  it("geçerli girdiyi manuel moda çevirir", () => {
    expect(checkSlTp(100, 97, 106)).toEqual({ ok: true, slPct: 3, rr: 2 });
  });
  it("sınırları Türkçe hatayla reddeder", () => {
    expect(checkSlTp(100, 99.8, 101)).toMatchObject({ ok: false, error: expect.stringContaining("çok yakın") });
    expect(checkSlTp(100, 85, 120)).toMatchObject({ ok: false, error: expect.stringContaining("çok uzak") });
    expect(checkSlTp(100, 97, 102)).toMatchObject({ ok: false, error: expect.stringContaining("1:1") });
    expect(checkSlTp(100, 97, 120)).toMatchObject({ ok: false, error: expect.stringContaining("1:5") });
  });
  it("sınır değerleri kabul edilir (%0,5 / %10, oran 1 / 5)", () => {
    expect(checkSlTp(100, 99.5, 100.5).ok).toBe(true);
    expect(checkSlTp(100, 90, 150).ok).toBe(true);
  });
  it("eksik / yönü yanlış fiyatları reddeder", () => {
    expect(checkSlTp(100, null, 106).ok).toBe(false);
    expect(checkSlTp(100, 97, null).ok).toBe(false);
    expect(checkSlTp(100, 101, 106).ok).toBe(false);
    expect(checkSlTp(100, 97, 99).ok).toBe(false);
    expect(checkSlTp(0, 97, 106).ok).toBe(false);
  });
});

describe("tek dokunuş SL/TP düğmeleri", () => {
  it("priceAtPct yüzde mesafeyi fiyata çevirir", () => {
    expect(priceAtPct(100, -2)).toBeCloseTo(98);
    expect(priceAtPct(100, 5)).toBeCloseTo(105);
    expect(priceAtPct(0, 5)).toBeNull();
  });
  it("pctFromPrice düğmenin seçili görünmesi için yüzdeyi geri bulur", () => {
    expect(pctFromPrice(100, 98)).toBe(-2);
    expect(pctFromPrice(100, 105)).toBe(5);
    expect(pctFromPrice(100, null)).toBeNull();
  });
  it("varsayılan düğme çiftleri API oran sınırına (1–5) uyar", () => {
    const p = 100;
    const ok = SL_PCT_CHIPS.some((sl) => TP_PCT_CHIPS.some((tp) => checkSlTp(p, priceAtPct(p, -sl), priceAtPct(p, tp)).ok));
    expect(ok).toBe(true);
    expect(checkSlTp(p, priceAtPct(p, -2), priceAtPct(p, 5)).ok).toBe(true);
  });
});

describe("serbest bakiyeden alım tutarı", () => {
  it("yüzdeyi kuruşa aşağı yuvarlar, bakiyeyi aşmaz", () => {
    expect(amountFromFree(1000, 25)).toBe(250);
    expect(amountFromFree(333.337, 100)).toBe(333.33);
    expect(amountFromFree(100, 150)).toBe(100);
    expect(amountFromFree(null, 50)).toBe(0);
    expect(amountFromFree(0, 50)).toBe(0);
  });
});

describe("describeBuyFill (alım onay penceresi)", () => {
  it("doğrulanan dolumu miktar + ortalama fiyatla anlatır", () => {
    const r = describeBuyFill(200, { executed_qty: 0.5, avg_price: 200, executed_quote_qty: 100 }, "BTC");
    expect(r.tone).toBe("good");
    expect(r.title).toContain("Alım gerçekleşti");
    expect(r.title).toContain("BTC");
  });
  it("202 / belirsiz sonuçta tekrar göndermeyi önermez", () => {
    expect(describeBuyFill(202, {}, "BTC").pending).toBe(true);
  });
  it("dolum bilgisi yoksa uyarı tonunda 'iletildi' der", () => {
    const r = describeBuyFill(200, { fill_verified: false }, "BTC");
    expect(r.tone).toBe("warn");
    expect(r.pending).toBe(false);
  });
});

describe("checkSlTpPlan (plan modunda RR sınırı yok)", () => {
  it("TP < SL mesafesi olsa da geçerli; sl_pct ve tp_pct döner", () => {
    const r = checkSlTpPlan(100, 95.8, 103.6);
    expect(r).toEqual({ ok: true, slPct: 4.2, tpPct: 3.6 });
  });
  it("SL aralığı ve TP yönü denetlenir", () => {
    expect(checkSlTpPlan(100, 100, 103).ok).toBe(false);
    expect(checkSlTpPlan(100, 99.9, 103).ok).toBe(false);
    expect(checkSlTpPlan(100, 95, 99).ok).toBe(false);
    expect(checkSlTpPlan(100, 95, 160).ok).toBe(false); // tp > %50
    expect(checkSlTpPlan(0, 95, 103).ok).toBe(false);
  });
  it("TP alt sınırı %0,5 (gerçek para; komisyon kısmını sunucu denetler)", () => {
    const low = checkSlTpPlan(100, 95, 100.4);
    expect(low.ok).toBe(false);
    if (!low.ok) expect(low.error).toContain("%0,5");
    expect(checkSlTpPlan(100, 95, 100.5)).toEqual({ ok: true, slPct: 5, tpPct: 0.5 });
  });
});
