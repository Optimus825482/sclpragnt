import { afterEach, describe, expect, it } from "vitest";
import { resetCommissionPct, applyCommissionPct } from "../../../lib/pnl";
import {
  PRICE_STALE_MS, buyIntentKey, describeOrderLookup, holdingNetPnl, intentId, isDefinitiveReject, minNotionalError, priceAgeInfo,
  resetIntent, sellIntentKey, sellStatusSymbols, type IntentRef,
} from "./orderIntent";

afterEach(() => resetCommissionPct());

describe("intentId (mükerrer alım koruması)", () => {
  it("aynı niyette (yeniden aç / ağ hatası sonrası tekrar) AYNI kimliği verir", () => {
    const ref: IntentRef = { key: "", id: "" };
    let n = 0;
    const gen = () => `id-${++n}`;
    const a = intentId(ref, buyIntentKey("ADATRY", 100), gen);
    const b = intentId(ref, buyIntentKey("ADATRY", 100), gen);
    expect(a).toBe("id-1");
    expect(b).toBe("id-1");
  });
  it("sembol ya da tutar değişince yeni kimlik; kesin sonuçtan sonra (reset) yeni kimlik", () => {
    const ref: IntentRef = { key: "", id: "" };
    let n = 0;
    const gen = () => `id-${++n}`;
    intentId(ref, buyIntentKey("ADATRY", 100), gen);
    expect(intentId(ref, buyIntentKey("ADATRY", 150), gen)).toBe("id-2");
    expect(intentId(ref, buyIntentKey("BTCTRY", 150), gen)).toBe("id-3");
    resetIntent(ref);
    expect(intentId(ref, buyIntentKey("BTCTRY", 150), gen)).toBe("id-4");
  });
  it("tutar aynı metne normalize edilir", () => {
    expect(buyIntentKey("ADATRY", 100)).toBe(buyIntentKey("ADATRY", 100.0));
    expect(sellIntentKey("ADA", 100, 0)).not.toBe(sellIntentKey("ADA", 50, 2.5));
  });
});

describe("isDefinitiveReject", () => {
  it("4xx kesin red; 408/504 ve gövdesiz 5xx belirsiz", () => {
    expect(isDefinitiveReject(422, "x")).toBe(true);
    expect(isDefinitiveReject(409, "x")).toBe(true);
    expect(isDefinitiveReject(408, "")).toBe(false);
    expect(isDefinitiveReject(504, "x")).toBe(false);
    expect(isDefinitiveReject(502, "")).toBe(false);
    expect(isDefinitiveReject(502, "Alım emri gönderilemedi: x")).toBe(true);
    expect(isDefinitiveReject(200, "")).toBe(false);
  });
});

describe("describeOrderLookup", () => {
  it("emir yoksa tekrar göndermenin güvenli olduğunu söyler", () => {
    expect(describeOrderLookup({ ok: true, status: 200, error: "", body: { ok: true, order: {} } })).toContain("bulunamadı");
  });
  it("emir bulunduysa tekrar göndermeyin der ve dolumu yazar", () => {
    const t = describeOrderLookup({ ok: true, status: 200, error: "", body: { order: { status: "FILLED", executedQty: "12.5" } } });
    expect(t).toContain("BULUNDU");
    expect(t).toContain("FILLED");
    expect(t).toContain("12.5");
    expect(t).toContain("Tekrar göndermeyin");
  });
  it("sorgu da başarısızsa belirsizliği korur", () => {
    expect(describeOrderLookup({ ok: false, status: 0, error: "x", body: {} })).toContain("yeniden göndermeyin");
    expect(describeOrderLookup({ ok: false, status: 502, error: "Emir durumu alınamadı", body: {} })).toContain("olabilir");
  });
});

describe("priceAgeInfo", () => {
  it("15 sn üstü eski", () => {
    const now = 100_000;
    expect(priceAgeInfo(now - 3_000, now)).toEqual({ text: "3 sn önce alındı", stale: false });
    expect(priceAgeInfo(now - PRICE_STALE_MS - 1, now).stale).toBe(true);
    expect(priceAgeInfo(now, now).text).toBe("şimdi alındı");
  });
  it("zaman bilinmiyorsa uyarır", () => {
    expect(priceAgeInfo(null, 1).stale).toBe(true);
  });
});

describe("holdingNetPnl", () => {
  it("brüt değil NET (gidiş-dönüş komisyonu düşülmüş)", () => {
    applyCommissionPct(0.001);
    // maliyet 100, fiyat 110, 10 adet: brüt 100; komisyon 0.001*10*(100+110)=2.1 → net 97.9
    const r = holdingNetPnl(100, 110, 10);
    expect(r?.tryValue).toBeCloseTo(97.9, 6);
    expect(r?.pct).toBeCloseTo(9.79, 6);
  });
  it("maliyet ya da fiyat yoksa null (0 değil)", () => {
    expect(holdingNetPnl(null, 110, 10)).toBeNull();
    expect(holdingNetPnl(100, null, 10)).toBeNull();
    expect(holdingNetPnl(100, 110, 0)).toBeNull();
  });
});

describe("minNotionalError", () => {
  it("altındaysa mesaj; bilinmiyorsa atlanır", () => {
    expect(minNotionalError(5, 10)).toContain("minimum");
    expect(minNotionalError(10, 10)).toBeNull();
    expect(minNotionalError(5, null)).toBeNull();
    expect(minNotionalError(5, 0)).toBeNull();
  });
});

describe("sellStatusSymbols", () => {
  it("önce TRY sonra USDT", () => {
    expect(sellStatusSymbols("ada")).toEqual(["ADATRY", "ADAUSDT"]);
    expect(sellStatusSymbols("")).toEqual([]);
  });
});
