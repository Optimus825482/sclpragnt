// `lib/format.ts` — biçimlendirme sözleşmesi.
//
// Buradaki asıl değer `null` sözleşmesidir: dosyanın kendi kuralı "veri yoksa
// '—' döner, 0 DEĞİL" diyor ve bu, para/eksen hesaplarında yanlış "başabaş"
// gösterimini engelliyor. `Number(null) === 0` deseni bu kuralı sessizce
// ihlal ettiği için (bkz. `pnl.closedPnlTry` hatası) burada kilitleniyor.

import { describe, it, expect } from "vitest";
import {
  toMs,
  fmtDateTime,
  fmtMinute,
  fmtDate,
  fmtClockTime,
  pricePrecision,
  formatPrice,
  formatTL,
  formatSignedTL,
  formatFixed,
  formatNumber2,
  formatRatioPct,
  localDateInput,
} from "./format";

describe("format — toMs (saniye/ms karışık girdi)", () => {
  it("saniyeyi milisaniyeye çevirir (10 milyar eşiği)", () => {
    expect(toMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000);
  });

  it("geçersiz/eksik girdide 0 döner", () => {
    expect(toMs(null)).toBe(0);
    expect(toMs(undefined)).toBe(0);
    expect(toMs(0)).toBe(0);
    expect(toMs(-1)).toBe(0);
    expect(toMs("abc")).toBe(0);
  });
});

describe("format — tarih/saat", () => {
  const ts = 1_700_000_000_000; // 14/11/2023 22:13 UTC

  it("fmtDateTime eksik girdide '—' döner (0 DEĞİL)", () => {
    expect(fmtDateTime(0)).toBe("—");
    expect(fmtDateTime(null)).toBe("—");
    expect(fmtDateTime(undefined)).toBe("—");
  });

  it("fmtMinute eksik girdide '—' döner", () => {
    expect(fmtMinute(0)).toBe("—");
    expect(fmtMinute(null)).toBe("—");
  });

  it("fmtDate eksik girdide '—' döner", () => {
    expect(fmtDate(null)).toBe("—");
  });

  it("fmtClockTime eksik girdide '—' döner", () => {
    expect(fmtClockTime(null)).toBe("—");
  });

  it("geçerli zaman damgası '—' DEĞİL, saat içerir", () => {
    for (const fn of [fmtDateTime, fmtMinute, fmtDate, fmtClockTime]) {
      const out = fn(ts);
      expect(out).not.toBe("—");
      expect(out.length).toBeGreaterThan(0);
    }
  });

  it("saniye/ms girdi aynı sonucu verir (normalizasyon)", () => {
    expect(fmtMinute(1_700_000_000)).toBe(fmtMinute(1_700_000_000_000));
    expect(fmtDateTime(1_700_000_000)).toBe(fmtDateTime(1_700_000_000_000));
  });
});

describe("format — pricePrecision (hassasiyet kovası)", () => {
  it("kova sınırları", () => {
    expect(pricePrecision(0.5)).toBe(6);
    expect(pricePrecision(50)).toBe(4);
    expect(pricePrecision(500)).toBe(3);
    expect(pricePrecision(5000)).toBe(2);
  });

  it("geçersiz/eksik girdide 2 döner (en yüksek kovaya düşmez)", () => {
    expect(pricePrecision(null)).toBe(2);
    expect(pricePrecision(undefined)).toBe(2);
    expect(pricePrecision(NaN)).toBe(2);
  });

  it("meşru 0 fiyatı <1 kovasına alır (0 bir fiyat değil ama burada basılır)", () => {
    // `formatPrice(0)` zaten "—" döner; kova yalnız veri varken kullanılır.
    expect(pricePrecision(0)).toBe(6);
  });
});

describe("format — fiyat / TL", () => {
  it("formatPrice ≤0 veya eksik girdide '—' döner (0 bir fiyat DEĞİLDİR)", () => {
    expect(formatPrice(0)).toBe("—");
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
    expect(formatPrice(NaN)).toBe("—");
    expect(formatPrice(-1)).toBe("—");
  });

  it("formatPrice geçerli fiyatta sayı basar", () => {
    expect(formatPrice(1.5)).not.toBe("—");
    expect(formatPrice(4250)).not.toBe("—");
  });

  it("formatTL 0'ı '—' YAPMAZ (0 meşru bir bakiyedir)", () => {
    expect(formatTL(0)).not.toBe("—");
    expect(formatTL(null)).toBe("—");
  });

  it("formatSignedTL işareti koyar, meşru 0'ı korur", () => {
    expect(formatSignedTL(0)).toBe("₺0,00");
    expect(formatSignedTL(5).startsWith("+")).toBe(true);
    expect(formatSignedTL(-5).startsWith("-")).toBe(true);
    expect(formatSignedTL(null)).toBe("—");
  });
});

describe("format — genel sayı yardımcıları", () => {
  it("formatFixed sabit ondalık basar, eksik → '—'", () => {
    expect(formatFixed(1.23456, 2)).toBe("1,23");
    expect(formatFixed(null)).toBe("—");
    expect(formatFixed("")).toBe("—");
    // 0 meşru bir sayıdır (miktar 0 olabilir)
    expect(formatFixed(0)).not.toBe("—");
  });

  it("formatNumber2 iki ondalığa yuvarlar", () => {
    expect(formatNumber2(1.005)).toBe("1");
    expect(formatNumber2(1.239)).toBe("1.24");
    expect(formatNumber2(null)).toBe("—");
  });

  it("formatRatioPct bölünen girdiyi yüzdeye çevirir", () => {
    expect(formatRatioPct(0.1234)).toBe("%12.3");
    expect(formatRatioPct(0.1234, 2)).toBe("%12.34");
    expect(formatRatioPct(null)).toBe("—");
    expect(formatRatioPct(0)).toBe("%0.0"); // 0 meşru oran
  });
});

describe("format — localDateInput", () => {
  it("YYYY-MM-DD biçiminde yerel tarih döner", () => {
    expect(localDateInput()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
