// `lib/pnl.ts` — AÇIK POZİSYON K/Z MATEMATİĞİ (para yazan yol).
//
// Neden burada gerçek sayısal test var
// ------------------------------------
// `backend/tests/test_w6_money_math.py` frontend/backend komisyon eşitliğini
// YALNIZCA regex ile doğruluyor (kaynakta "0.0015" geçiyor mu). Bu test
// yeşil kalırken `pnl.ts` hesabı yanlış olabilirdi. Buradaki testler
// bilinen girdi → bilinen çıktı eşleşmesini SAYISAL olarak kilitler.
//
// Beklenen değerler elle hesaplandı (backend `config.COMMISSION_PCT` = 0.0015):
//   net = (current - entry) * qty − 0.0015 * qty * (entry + current)
//       = gidiş-dönüş komisyonu iki bacaktan düşülür (yalnız giriş bacağı DEĞİL).

import { describe, it, expect, beforeEach } from "vitest";
import {
  COMMISSION_PCT_FALLBACK,
  applyCommissionPct,
  commissionPct,
  resetCommissionPct,
  grossOpenPnlTry,
  netOpenPnlTry,
  netOpenPnlPct,
  closedPnlTry,
} from "./pnl";

const EPS = 1e-9;

// `applyCommissionPct` modül düzeyi durum değiştirir. Her `describe` bloğundan
// önce backend varsayılanına döndürüyoruz; aksi halde "oran 0.002" bırakan bir
// test, sonraki tüm net hesapları bozardı (testler sırayla çalıştığı için
// sessiz ve çok yanıltıcı bir hata).
beforeEach(() => {
  resetCommissionPct();
});

describe("pnl — komisyon oranı yönetimi", () => {
  it("varsayılan oran backend COMMISSION_PCT ile aynı", () => {
    // NOT: `applyCommissionPct` modül durumunu değiştirdiği için bu test
    // dosyanın en başında ve izole çalışır (aşağıdaki `beforeEach` sıfırlar).
    expect(commissionPct()).toBe(COMMISSION_PCT_FALLBACK);
    expect(commissionPct()).toBe(0.0015);
  });

  it("geçerli yeni oranı uygular", () => {
    applyCommissionPct(0.002);
    expect(commissionPct()).toBe(0.002);
  });

  it("geçersiz değerleri yok sayar (oran korunur)", () => {
    applyCommissionPct(0.002);
    // negatif, 0, 0.05 üstü, NaN, null, string-olmayan → hepsi yok sayılmalı
    applyCommissionPct(-0.001);
    expect(commissionPct()).toBe(0.002);
    applyCommissionPct(0);
    expect(commissionPct()).toBe(0.002);
    applyCommissionPct(0.5);
    expect(commissionPct()).toBe(0.002);
    applyCommissionPct(NaN);
    expect(commissionPct()).toBe(0.002);
    applyCommissionPct(null);
    expect(commissionPct()).toBe(0.002);
    applyCommissionPct(undefined);
    expect(commissionPct()).toBe(0.002);
  });
});

describe("pnl — brüt açık pozisyon K/Z", () => {
  it("bilinen girdi → bilinen çıktı", () => {
    // (110 − 100) × 2 = 20
    expect(grossOpenPnlTry(100, 110, 2)).toBeCloseTo(20, 10);
  });

  it("zararda negatif döner", () => {
    expect(grossOpenPnlTry(100, 90, 1)).toBeCloseTo(-10, 10);
  });

  it("eksik girdide 0 DEĞİL `null` döner", () => {
    // 0 bir K/Z değil "veri yok"tur; UI'nin yeşile boyaması için null şart.
    expect(grossOpenPnlTry(null, 110, 2)).toBeNull();
    expect(grossOpenPnlTry(100, undefined, 2)).toBeNull();
    expect(grossOpenPnlTry(100, 110, 0)).toBeNull();
    expect(grossOpenPnlTry(0, 110, 2)).toBeNull();
    expect(grossOpenPnlTry(100, 0, 2)).toBeNull();
    expect(grossOpenPnlTry(NaN, 110, 2)).toBeNull();
  });
});

describe("pnl — net açık pozisyon K/Z (komisyonlu, kanonik)", () => {
  // Tüm net beklentiler backend `COMMISSION_PCT = 0.0015` ile elle hesaplandı.

  it("kâr durumu: 100 → 110, 2 adet", () => {
    // gross = 20; fees = 0.0015 * 2 * (100 + 110) = 0.63; net = 19.37
    expect(netOpenPnlTry(100, 110, 2)).toBeCloseTo(19.37, 10);
  });

  it("zarar durumu: 100 → 90, 1 adet", () => {
    // gross = −10; fees = 0.0015 * 1 * (100 + 90) = 0.285; net = −10.285
    expect(netOpenPnlTry(100, 90, 1)).toBeCloseTo(-10.285, 10);
  });

  it("büyük pozisyon: 4250 → 4400, 0.5 adet", () => {
    // gross = 75; fees = 0.0015 * 0.5 * 8650 = 6.4875; net = 68.5125
    expect(netOpenPnlTry(4250, 4400, 0.5)).toBeCloseTo(68.5125, 10);
  });

  it("büyük zarar: 100000 → 99500, 0.01 adet", () => {
    // gross = −5; fees = 0.0015 * 0.01 * 199500 = 2.9925; net = −7.9925
    expect(netOpenPnlTry(100000, 99500, 0.01)).toBeCloseTo(-7.9925, 10);
  });

  it("başabaş (entry === current) pozisyon KAZANMAZ, kaybeder", () => {
    // gross = 0; fees = 0.0015 * q * 2*entry > 0 → net NEGATİF.
    // Bu, iki bacaklı komisyonun varlık nedenidir: giriş + çıkış birlikte.
    const net = netOpenPnlTry(100, 100, 2);
    expect(net).not.toBeNull();
    expect(net as number).toBeLessThan(0);
    expect(net).toBeCloseTo(-0.6, 10); // 0.0015 * 2 * 200 = 0.6
  });

  it("eksik girdide `null` döner (0 DEĞİL)", () => {
    expect(netOpenPnlTry(null, 110, 2)).toBeNull();
    expect(netOpenPnlTry(100, undefined, 2)).toBeNull();
    expect(netOpenPnlTry(100, 110, null)).toBeNull();
    expect(netOpenPnlTry(0, 110, 2)).toBeNull();
    expect(netOpenPnlTry(100, 0, 2)).toBeNull();
    expect(netOpenPnlTry(100, 110, 0)).toBeNull();
  });

  it("komisyon oranı değişince net de değişir (backend ile senkron)", () => {
    const baseline = netOpenPnlTry(100, 110, 2) as number;
    applyCommissionPct(0.002);
    // fees = 0.002 * 2 * 210 = 0.84 → net = 19.16
    expect(netOpenPnlTry(100, 110, 2)).toBeCloseTo(19.16, 10);
    expect(netOpenPnlTry(100, 110, 2)).not.toBeCloseTo(baseline, 6);
  });

  it("net daima brütten küçük veya eşittir (komisyon asla kazandırmaz)", () => {
    const cases: [number, number, number][] = [
      [100, 110, 2],
      [100, 90, 1],
      [4250, 4400, 0.5],
      [100000, 99500, 0.01],
      [50, 50, 10],
      [1, 1.0001, 1_000_000],
    ];
    for (const [e, c, q] of cases) {
      const gross = grossOpenPnlTry(e, c, q) as number;
      const net = netOpenPnlTry(e, c, q) as number;
      expect(net).toBeLessThanOrEqual(gross + EPS);
    }
  });
});

describe("pnl — net açık pozisyon getirisi (%)", () => {
  it("bilinen girdi → bilinen çıktı", () => {
    // 4250 → 4400, 0.5 adet: net = 68.5125; taban = 4250 * 0.5 = 2125
    // 68.5125 / 2125 * 100 = 3.224117647…
    expect(netOpenPnlPct(4250, 4400, 0.5)).toBeCloseTo(3.224117647058824, 9);
  });

  it("brüt getiriden daha küçüktür (komisyon dolaylı olarak)", () => {
    // brüt getiri = (4400-4250)/4250*100 = 3.5294117647…
    const grossPct = ((4400 - 4250) / 4250) * 100;
    const netPct = netOpenPnlPct(4250, 4400, 0.5) as number;
    expect(netPct).toBeLessThan(grossPct);
  });

  it("eksik girdide `null` döner", () => {
    expect(netOpenPnlPct(null, 4400, 0.5)).toBeNull();
    expect(netOpenPnlPct(4250, 0, 0.5)).toBeNull();
    expect(netOpenPnlPct(4250, 4400, 0)).toBeNull();
  });
});

describe("pnl — kapalı işlem K/Z (null-korumalı okuma)", () => {
  it("geçerli sayıyı olduğu gibi geçirir (backend zaten komisyonlu yazar)", () => {
    expect(closedPnlTry(1234.56)).toBe(1234.56);
    expect(closedPnlTry(0)).toBe(0);
    expect(closedPnlTry(-99.9)).toBe(-99.9);
  });

  it("geçersiz girdide `null` döner", () => {
    expect(closedPnlTry(null)).toBeNull();
    expect(closedPnlTry(undefined)).toBeNull();
    expect(closedPnlTry("abc")).toBeNull();
    expect(closedPnlTry(NaN)).toBeNull();
  });
});

describe("pnl — modül durumu izolasyonu", () => {
  it("resetCommissionPct varsayılanı geri getirir", () => {
    applyCommissionPct(0.003);
    expect(commissionPct()).toBeCloseTo(0.003, 12);
    resetCommissionPct();
    expect(commissionPct()).toBeCloseTo(0.0015, 12);
  });
});
