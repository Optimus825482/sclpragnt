import { describe, expect, it } from "vitest";
import { protectOrder } from "./protectMath";

const base = { price: 100, slPct: 2, tpPct: 5, qtyPct: 100, total: 3 };

describe("protectOrder (SL / TP / OCO yüzdeyle)", () => {
  it("OCO: SL ve TP güncel fiyattan yüzdeyle; mevcut emirler önce iptal edilir", () => {
    const r = protectOrder({ ...base, mode: "OCO" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.body).toMatchObject({ mode: "OCO", quantity: "all", sl_price: 98, tp_price: 105, cancel_existing: true });
    expect(r.body.sl_limit_price).toBeLessThan(98);
  });
  it("yalnız SL: TP alanı gönderilmez", () => {
    const r = protectOrder({ ...base, mode: "SL_ONLY", tpPct: null });
    expect(r.ok && r.body.tp_price).toBe(undefined);
    expect(r.ok && r.body.sl_price).toBe(98);
  });
  it("yalnız TP: SL alanı gönderilmez", () => {
    const r = protectOrder({ ...base, mode: "TP_ONLY", slPct: null });
    expect(r.ok && r.body.sl_price).toBe(undefined);
    expect(r.ok && r.body.tp_price).toBe(105);
  });
  it("miktar yüzdesi adet olarak aşağı kesilir", () => {
    const r = protectOrder({ ...base, mode: "OCO", qtyPct: 50 });
    expect(r.ok && r.body.quantity).toBe(1.5);
  });
  it("eksik yüzde ve fiyat yokken hata verir", () => {
    expect(protectOrder({ ...base, mode: "OCO", slPct: null }).ok).toBe(false);
    expect(protectOrder({ ...base, mode: "OCO", price: null }).ok).toBe(false);
    expect(protectOrder({ ...base, mode: "OCO", total: 0 }).ok).toBe(false);
  });
});
