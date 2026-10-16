import { describe, expect, it } from "vitest";
import {
  amountFromPct, capAmount, describeOpenResult, errorText, fmtPct, fmtPrice, fmtSignedTry, fmtTry,
  isValidClientOrderId, newClientOrderId, parseTrNumber, rrLabel, scenarioTexts, suggestionSourceLabel,
} from "./tradeUi";

describe("biçimleme", () => {
  it("TL tr-TR", () => {
    expect(fmtTry(1234.5)).toBe("₺1.234,50");
    expect(fmtTry(null)).toBe("—");
    expect(fmtTry(Number.NaN)).toBe("—");
  });
  it("işaretli TL", () => {
    expect(fmtSignedTry(12.3)).toBe("+₺12,30");
    expect(fmtSignedTry(-4.1)).toBe("−₺4,10");
    expect(fmtSignedTry(0)).toBe("₺0,00");
  });
  it("yüzde ve fiyat", () => {
    expect(fmtPct(12.5)).toBe("%12,5");
    expect(fmtPct(-0.5)).toBe("−%0,5");
    expect(fmtPrice(0.00001234)).toContain("0,00001234");
    expect(fmtPrice(0)).toBe("—");
    expect(fmtPrice(250.5)).toBe("250,50");
  });
  it("RR etiketi", () => expect(rrLabel(2)).toBe("1 : 2"));
});

describe("parseTrNumber", () => {
  it("virgül ve nokta", () => {
    expect(parseTrNumber("12,5")).toBe(12.5);
    expect(parseTrNumber("12.5")).toBe(12.5);
    expect(parseTrNumber("1.234,5")).toBe(1234.5);
  });
  it("geçersiz", () => {
    expect(parseTrNumber("")).toBeNull();
    expect(parseTrNumber("abc")).toBeNull();
    expect(parseTrNumber(null)).toBeNull();
  });
});

describe("client_order_id", () => {
  it("sunucu kuralına uyar ve benzersizdir", () => {
    const a = newClientOrderId();
    const b = newClientOrderId();
    expect(isValidClientOrderId(a)).toBe(true);
    expect(a).not.toBe(b);
  });
  it("geçersizler", () => {
    expect(isValidClientOrderId("kisa")).toBe(false);
    expect(isValidClientOrderId("bosluk iceren id1")).toBe(false);
  });
});

describe("tutar", () => {
  it("yüzde, Risk Merkezi sınırını aşamaz", () => {
    expect(amountFromPct(1000, 50, 20)).toBe(200);
    expect(amountFromPct(1000, 10, 20)).toBe(100);
  });
  it("kuruşa aşağı yuvarlar", () => expect(amountFromPct(100.019, 100, 100)).toBe(100.01));
  it("bakiye yok / geçersiz", () => {
    expect(amountFromPct(0, 50, 50)).toBe(0);
    expect(amountFromPct(Number.NaN, 50, 50)).toBe(0);
    expect(amountFromPct(1000, -5, 50)).toBe(0);
  });
  it("üst sınır", () => expect(capAmount(500, 20)).toBe(100));
});

describe("senaryo metni", () => {
  it("jargonsuz ve işaretli", () => {
    const t = scenarioTexts({ loss_try: -8.4, gain_try: 16.2, sl_price: 98, tp_price: 104 });
    expect(t.bad).toContain("−₺8,40");
    expect(t.good).toContain("+₺16,20");
    expect(t.bad.toLowerCase()).not.toContain("oco");
  });
  it("öneri kaynağı", () => {
    expect(suggestionSourceLabel("llm")).toBe("Yapay zekâ önerisi");
    expect(suggestionSourceLabel("kural")).toBe("Otomatik hesap");
    expect(suggestionSourceLabel(undefined)).toBe("Otomatik hesap");
  });
});

describe("describeOpenResult", () => {
  it("koruma kuruldu", () => {
    const r = describeOpenResult(200, { protection: { status: "placed" } });
    expect(r.tone).toBe("good");
    expect(r.needsProtect).toBe(false);
  });
  it("koruma kurulamadı → yeniden dene", () => {
    const r = describeOpenResult(200, { protection: { status: "failed", error: "x" } });
    expect(r.tone).toBe("bad");
    expect(r.needsProtect).toBe(true);
  });
  it("koruma atlandı", () => {
    const r = describeOpenResult(200, { protection: { status: "skipped" } });
    expect(r.needsProtect).toBe(true);
  });
  it("belirsiz sonuç: tekrar gönderme uyarısı", () => {
    const r = describeOpenResult(202, { status: "UNKNOWN" });
    expect(r.pending).toBe(true);
    expect(r.detail).toContain("tekrar göndermeyin");
  });
  it("boş gövde çökmez", () => expect(describeOpenResult(200, null).tone).toBe("mute"));
});

describe("errorText", () => {
  it("detay yoksa yedek", () => {
    expect(errorText("Limit aşıldı")).toBe("Limit aşıldı");
    expect(errorText(undefined)).toBe("İşlem yapılamadı");
    expect(errorText({ a: 1 }, "Hata")).toBe("Hata");
  });
});

import { hasBlockingWarnings, normalizeSymbol } from "./tradeUi";

describe("normalizeSymbol", () => {
  it("TRY çiftine çevirir", () => {
    expect(normalizeSymbol("ada")).toBe("ADATRY");
    expect(normalizeSymbol("ADA/TRY")).toBe("ADATRY");
    expect(normalizeSymbol("ada_try")).toBe("ADATRY");
    expect(normalizeSymbol(" btc ")).toBe("BTCTRY");
  });
  it("geçersiz", () => {
    expect(normalizeSymbol("")).toBe("");
    expect(normalizeSymbol("TRY")).toBe("");
    expect(normalizeSymbol(null)).toBe("");
  });
  it("uyarılar", () => {
    expect(hasBlockingWarnings([])).toBe(false);
    expect(hasBlockingWarnings(["limit_asildi"])).toBe(true);
    expect(hasBlockingWarnings(undefined)).toBe(false);
  });
});
