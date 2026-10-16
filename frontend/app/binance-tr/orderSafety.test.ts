import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UncertainOrderError, ceilPriceStr, checkSlTpInputs, describeSellFill, exactQtyInput, floorQty, orderFailureText, parseMoneyInput,
  postJsonGuarded, priceDecimals, qtyToInput, roundPriceStr, summarizeCancelAll, uncertainOrderText,
} from "./orderSafety";

describe("floorQty / qtyToInput", () => {
  it("asla yukarı yuvarlamaz", () => {
    expect(floorQty(0.1234567)).toBe(0.123456);
    expect(Number((0.1234567).toFixed(6))).toBeGreaterThan(0.1234567); // eski yöntem: bakiyeden büyük
    expect(floorQty(0.0000009)).toBe(0);
  });
  it("kayan nokta kalıntısını temizler", () => {
    expect(floorQty(1.1 * 3)).toBe(3.3);
    expect(floorQty(0.3, 6)).toBe(0.3);
  });
  it("geçersiz girdi 0", () => {
    expect(floorQty(Number.NaN)).toBe(0);
    expect(floorQty(-1)).toBe(0);
  });
  it("girdi metni üstelsiz ve sıfırsız", () => {
    expect(qtyToInput(0.5)).toBe("0.5");
    expect(qtyToInput(12)).toBe("12");
    expect(qtyToInput(0.000001)).toBe("0.000001");
    expect(qtyToInput(0.00000049)).toBe("0");
  });
});

describe("exactQtyInput", () => {
  it("üstel gösterim üretmez, sıfırları atar", () => {
    expect(exactQtyInput(1e-7)).toBe("0.0000001");
    expect(exactQtyInput(100)).toBe("100");
    expect(exactQtyInput(0.30000000000000004)).toBe("0.3");
    expect(exactQtyInput(0)).toBe("0");
  });
});

describe("fiyat basamakları", () => {
  it("fiyat aralığına göre", () => {
    expect(priceDecimals(1500)).toBe(2);
    expect(priceDecimals(2.5)).toBe(4);
    expect(priceDecimals(0.05)).toBe(6);
    expect(priceDecimals(0.0005)).toBe(8);
    expect(priceDecimals(null)).toBe(2);
  });
  it("1-10 TL arası coinlerde %3 stop 2 haneye yuvarlanıp bozulmaz", () => {
    expect(roundPriceStr(1.0020 * 1.0033, 1.002)).toBe("1.0053");
  });
  it("break-even yukarı yuvarlanır (maliyetin altına düşmez)", () => {
    // maliyet 1.0000, komisyon+tampon ile 1.00351 → 4 hane: 1.0036 (floor/round 1.0035 olurdu)
    expect(ceilPriceStr(1.00351, 1.002)).toBe("1.0036");
    expect(Number(ceilPriceStr(1.00351, 1.002))).toBeGreaterThanOrEqual(1.00351);
  });
});

describe("hata metinleri", () => {
  it("backend nedeni yutulmaz", () => {
    expect(orderFailureText("sell", 422, "Miktar minimum lotun altında (min 0.001)")).toBe("Miktar minimum lotun altında (min 0.001)");
  });
  it("5xx ve gövdesiz yanıt 'belirsiz' notu alır", () => {
    expect(orderFailureText("buy", 502, "")).toContain("BELİRSİZ");
    expect(orderFailureText("buy", 504, "Gateway Timeout")).toContain("BELİRSİZ");
    expect(orderFailureText("sltp", 408, undefined)).toContain("BELİRSİZ");
  });
  it("4xx gövdesiz yanıt kodu söyler", () => {
    expect(orderFailureText("sell", 429, undefined)).toBe("Satış emri gönderilemedi (HTTP 429)");
  });
  it("belirsiz metin: al/sat idempotent, sl/tp değil", () => {
    expect(uncertainOrderText("sell", true)).toContain("mükerrer emir oluşmaz");
    expect(uncertainOrderText("sell", true)).toContain("zaman aşımına");
    expect(uncertainOrderText("buy", false)).toContain("Bağlantı koptu");
    expect(uncertainOrderText("sltp", false)).toContain("korumasız");
    expect(uncertainOrderText("sltp", false)).not.toContain("mükerrer");
  });
});

describe("describeSellFill", () => {
  it("gerçek dolumu kullanır", () => {
    const f = describeSellFill({ executed_qty: 0.5, avg_price: 100, cummulative_quote_qty: 49.9 }, 0.6, 90);
    expect(f).toMatchObject({ qty: 0.5, price: 100, total: 49.9, partial: false });
  });
  it("dolum yoksa istenen miktar ve ekran fiyatı", () => {
    const f = describeSellFill({}, 2, 10);
    expect(f).toMatchObject({ qty: 2, price: 10, total: 20 });
  });
  it("ortalama fiyatı toplam tutardan türetir", () => {
    expect(describeSellFill({ executed_qty: 4, cummulative_quote_qty: 200 }, 4, null).price).toBe(50);
  });
  it("kısmi dolum işaretlenir", () => {
    const f = describeSellFill({ executed_qty: 1, partial: true, remaining_qty: 0.25, dust_remaining: true }, 1.25, 5);
    expect(f.partial).toBe(true);
    expect(f.remaining).toBe(0.25);
    expect(f.dust).toBe(true);
  });
  it("hiçbir veri yoksa null", () => {
    expect(describeSellFill(null, 0, null)).toMatchObject({ qty: null, price: null, total: null });
  });
});

describe("summarizeCancelAll", () => {
  it("OCO ikinci bacak hatası: liste boşsa başarı", () => {
    const s = summarizeCancelAll([1, 2], [], 1, 1);
    expect(s).toMatchObject({ cancelled: 2, remaining: 0, level: "success" });
  });
  it("hâlâ açık emir varsa hata", () => {
    const s = summarizeCancelAll([1, 2, 3], [2], 2, 1);
    expect(s.level).toBe("error");
    expect(s.remaining).toBe(1);
    expect(s.text).toContain("AKTİF");
  });
  it("liste alınamazsa istek sonuçlarına göre ve belirsizlik söylenir", () => {
    expect(summarizeCancelAll([1], null, 1, 0).text).toContain("yenilenemedi");
    expect(summarizeCancelAll([1, 2], null, 1, 1).level).toBe("error");
  });
});

describe("checkSlTpInputs", () => {
  it("SL_ONLY'de artık TP yok sayılır", () => {
    expect(checkSlTpInputs("SL_ONLY", 50, 90, 100)).toBeNull();
  });
  it("TP_ONLY'de artık SL yok sayılır", () => {
    expect(checkSlTpInputs("TP_ONLY", 110, 120, 100)).toBeNull();
  });
  it("OCO: SL güncel fiyatın üstündeyse reddedilir", () => {
    expect(checkSlTpInputs("OCO", 120, 105, 100)).toContain("altında");
  });
  it("OCO: TP güncel fiyatın altındaysa reddedilir", () => {
    expect(checkSlTpInputs("OCO", 99, 90, 100)).toContain("üstünde");
  });
  it("OCO geçerli", () => {
    expect(checkSlTpInputs("OCO", 110, 95, 100)).toBeNull();
  });
});

describe("parseMoneyInput", () => {
  it("Türkçe ve nokta yazımları", () => {
    expect(parseMoneyInput("12,5")).toBe(12.5);
    expect(parseMoneyInput("12.5")).toBe(12.5);
    expect(parseMoneyInput("1.234,56")).toBe(1234.56);
    expect(parseMoneyInput(" 100 ")).toBe(100);
  });
  it("geçersiz → NaN", () => {
    expect(Number.isNaN(parseMoneyInput(""))).toBe(true);
    expect(Number.isNaN(parseMoneyInput("abc"))).toBe(true);
    expect(Number.isNaN(parseMoneyInput("-5"))).toBe(true);
    expect(Number.isNaN(parseMoneyInput("1e3"))).toBe(true);
    expect(Number.isNaN(parseMoneyInput(null))).toBe(true);
  });
});

describe("postJsonGuarded", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const jsonResponse = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as unknown as Response;

  it("HTTP hatası da yanıt olarak döner (gövde korunur)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(422, { detail: "Yetersiz bakiye" })));
    const r = await postJsonGuarded("/x", { a: 1 });
    expect(r).toMatchObject({ status: 422, ok: false, body: { detail: "Yetersiz bakiye" } });
  });

  it("ağ hatası → belirsiz (zaman aşımı değil)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await postJsonGuarded("/x", {}).catch((e) => e);
    expect(err).toBeInstanceOf(UncertainOrderError);
    expect(err.timedOut).toBe(false);
  });

  it("2xx ama okunamayan gövde → belirsiz", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("x"); } }) as unknown as Response));
    await expect(postJsonGuarded("/x", {})).rejects.toBeInstanceOf(UncertainOrderError);
  });

  it("4xx okunamayan gövde → boş gövdeyle yanıt", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError("x"); } }) as unknown as Response));
    await expect(postJsonGuarded("/x", {})).resolves.toMatchObject({ status: 502, ok: false, body: {} });
  });

  it("zaman aşımı → belirsiz ve timedOut=true", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_u: unknown, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
    })));
    const p = postJsonGuarded("/x", {}, 1000).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    const err = await p;
    expect(err).toBeInstanceOf(UncertainOrderError);
    expect(err.timedOut).toBe(true);
  });
});
