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
    // Binance TR clientId: tire/alt çizgi yok, en fazla 36 karakter (3703 Invalid client ID).
    expect(a).toMatch(/^[A-Za-z0-9]{8,36}$/);
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

import { suggestSymbols } from "./tradeUi";

describe("suggestSymbols", () => {
  const all = ["ADATRY", "AVAXTRY", "BTCTRY", "BTTTRY", "DOGETRY", "AAVETRY", "ADXTRY"];
  it("3 harften önce öneri yok", () => expect(suggestSymbols(all, "ad")).toEqual([]));
  it("önek önce, sonra içeren", () => {
    expect(suggestSymbols([...all, "WAVAXTRY"], "ava")).toEqual(["AVAX", "WAVAX"]);
    expect(suggestSymbols(all, "btc")).toEqual(["BTC"]);
  });
  it("TRY ekini ve boşlukları yok sayar", () => expect(suggestSymbols(all, " ada/try ")).toEqual(["ADA"]));
  it("sınır ve tekrar", () => expect(suggestSymbols([...all, "ADATRY"], "ada", 1)).toEqual(["ADA"]));
});

describe("suggestSymbols USDT çiftleri", () => {
  it("USDT çiftleri önerilmez (yalnız TL ile işlem)", () =>
    expect(suggestSymbols(["ADATRY", "ADAUSDT"], "ada")).toEqual(["ADA"]));
});

import { filterSmallBalances, groupTradesBySymbol } from "./tradeUi";

describe("groupTradesBySymbol", () => {
  const trades = [
    { symbol: "ADA_TRY", price: "10", qty: "10", quoteQty: "100", time: 1, isBuyer: true },
    { symbol: "ADA_TRY", price: "20", qty: "30", quoteQty: "600", time: 2, isBuyer: true },
    { symbol: "ADA_TRY", price: "25", qty: "20", quoteQty: "500", time: 3, isBuyer: false, realized_pnl_try: 40 },
    { symbol: "XRP_TRY", price: "5", qty: "4", quoteQty: "20", time: 5, isBuyer: false, realized_pnl_try: -2 },
  ];
  const g = groupTradesBySymbol(trades);
  it("aynı sembol tek satır, en son işlem üstte", () => {
    expect(g.map((x) => x.symbol)).toEqual(["XRP/TRY", "ADA/TRY"]);
    expect(g[1].count).toBe(3);
  });
  it("ağırlıklı ortalama = toplam tutar / toplam adet", () => {
    expect(g[1].buyQty).toBe(40);
    expect(g[1].buyAvg).toBeCloseTo(17.5);   // 700 / 40, basit ortalama (15) DEĞİL
    expect(g[1].sellAvg).toBeCloseTo(25);
  });
  it("K/Z toplanır, yön yoksa null", () => {
    expect(g[1].pnl).toBe(40);
    expect(g[0].buyAvg).toBeNull();
    expect(groupTradesBySymbol([{ symbol: "A_TRY", price: 1, qty: 1, quoteQty: 1, time: 1, isBuyer: true }])[0].pnl).toBeNull();
  });
  it("boş liste ve eksik tutar", () => {
    expect(groupTradesBySymbol([])).toEqual([]);
    expect(groupTradesBySymbol([{ symbol: "B_TRY", price: "2", qty: "3", quoteQty: "", time: 1, isBuyer: true }])[0].buyQuote).toBe(6);
  });
});

describe("filterSmallBalances", () => {
  const items = [{ value_try: 10 }, { value_try: 50 }, { value_try: 300 }, { value_try: null }];
  it("50 TL altını gizler, bilinmeyeni göstermez gizlemez", () =>
    expect(filterSmallBalances(items, true).map((x) => x.value_try)).toEqual([50, 300, null]));
  it("kapalıyken hepsi", () => expect(filterSmallBalances(items, false)).toHaveLength(4));
});

import { slTpMode, validateSlTpPrices } from "./tradeUi";

describe("slTpMode", () => {
  it("ikisi birden OCO, tekli modlar", () => {
    expect(slTpMode(110, 95)).toBe("OCO");
    expect(slTpMode(null, 95)).toBe("SL_ONLY");
    expect(slTpMode(110, undefined)).toBe("TP_ONLY");
    expect(slTpMode(0, 0)).toBeNull();
  });
});

describe("validateSlTpPrices", () => {
  it("geçerli OCO ve tekliler", () => {
    expect(validateSlTpPrices(110, 95, 100)).toBeNull();
    expect(validateSlTpPrices(null, 95, 100)).toBeNull();
    expect(validateSlTpPrices(110, null, 100)).toBeNull();
  });
  it("TP, SL'den büyük olmalı", () => expect(validateSlTpPrices(90, 95, 100)).toContain("büyük"));
  it("SL güncel fiyatın altında", () => expect(validateSlTpPrices(null, 101, 100)).toContain("altında"));
  it("TP güncel fiyatın üstünde", () => expect(validateSlTpPrices(99, null, 100)).toContain("üstünde"));
  it("hiçbiri yok", () => expect(validateSlTpPrices(null, null, 100)).toContain("En az bir"));
  it("güncel fiyat yoksa yalnız kendi aralarında", () => expect(validateSlTpPrices(110, 95, null)).toBeNull());
});
