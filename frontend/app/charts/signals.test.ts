// `charts/signals.ts` — GÖSTERGE MATEMATİĞİ (backend ile aynı olması gereken).
//
// REFERANS: `backend/app/technical_analysis.py`
//   `_rsi_series` / `_rsi`  → satır 27-55
//   `_cmo`                 → satır 128-131
//   `_crsi`                → satır 139-143
//   `_mfi`                 → satır 208-222
//
// Beklenen değerler backend'in KENDİ kodundan üretildi (aynı seriler
// `technical_analysis.py` fonksiyonlarına verilerek), frontend çıktısıyla
// karşılaştırılıyor. Yani sapma varsa test KIRMIZI olur.
//
// `crsi` ve `mfiLast` daha önce backend'den SAPIYORDU (denetim görev 12):
//   • crsi  → percent rank 1-bar DEĞİŞİMİ üzerinden sayılıyordu
//              (backend FİYAT SEVİYESİ kullanıyor) ve streak RSI'de
//              `down == 0` koşulsuz 100 dönüyordu (backend `up > 0` şartı
//              koyuyor, yoksa 50 döner).
//   • mfi   → `negative === 0 → 100` koşulsuzdu; backend `pos > 0 ? 100 : 50`
//              diyor. Artık düzeltildi, aşağıdaki testler bunu kilitler.

import { describe, it, expect } from "vitest";
import { rsi, cmo, crsi, mfiLast, rsiLast, obvLast, type Bar } from "./signals";

// ── Test serileri ───────────────────────────────────────────────────────────

/** Monoton artan: RSI 100, CRSI 100, MFI 100. */
const CLOSES_UP = Array.from({ length: 25 }, (_, i) => 100 + i);

/** Monoton azalan: RSI 0, CRSI 0, MFI 0. */
const CLOSES_DOWN = Array.from({ length: 25 }, (_, i) => 200 - i);

/** Düz seri: RSI 50, MFI 50 (nötr), CRSI 33.33 (streak 50 + rank 0 + RSI 50). */
const CLOSES_FLAT = Array.from({ length: 25 }, () => 50);

/** Gerçekçi dalgalı seri (backend referans çıktıları aşağıda). */
const CLOSES_MIXED = [
  100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112,
  114, 113, 115, 117, 116, 118, 120, 119, 121, 123, 122, 124,
];

const BARS_FROM = (closes: number[], volume = 100): Bar[] =>
  closes.map((c, i) => ({
    time: 1_700_000_000 + i * 60,
    open: c,
    high: c + 1,
    low: c - 1,
    close: c,
    volume,
  }));

const BARS_MIXED = BARS_FROM(CLOSES_MIXED);
const BARS_MIXED_VAR_VOL = BARS_FROM(
  CLOSES_MIXED,
);

// Varyantlı hacim: backend referansı farklı çıkıyor (aşağıda doğrulandı).
const BARS_MIXED_ALT_VOL = CLOSES_MIXED.map((c, i) => ({
  time: 1_700_000_000 + i * 60,
  open: c,
  high: c + 1,
  low: c - 1,
  close: c,
  volume: 100 + (i % 3) * 10,
}));

// ── RSI ─────────────────────────────────────────────────────────────────────

describe("signals — RSI (Wilder, backend `_rsi_series`)", () => {
  it("yalnız artan seride 100", () => {
    expect(rsi(CLOSES_UP, 14)).toBeCloseTo(100, 10);
  });

  it("yalnız azalan seride 0", () => {
    expect(rsi(CLOSES_DOWN, 14)).toBeCloseTo(0, 10);
  });

  it("düz seride nötr 50", () => {
    expect(rsi(CLOSES_FLAT, 14)).toBeCloseTo(50, 10);
  });

  it("dalgalı seri backend ile birebir aynı", () => {
    // backend: 80.08414520951531
    expect(rsi(CLOSES_MIXED, 14)).toBeCloseTo(80.08414520951531, 8);
  });

  it("yetersiz veride `null` döner", () => {
    expect(rsi([1, 2, 3], 14)).toBeNull();
  });

  it("rsiLast kapanış serisini kullanır", () => {
    expect(rsiLast(BARS_MIXED, 14)).toBeCloseTo(80.08414520951531, 8);
  });
});

// ── CMO ─────────────────────────────────────────────────────────────────────

describe("signals — CMO (backend `_cmo`)", () => {
  it("yalnız artan seride +100", () => {
    expect(cmo(CLOSES_UP, 9)).toBeCloseTo(100, 10);
  });

  it("yalnız azalan seride −100", () => {
    expect(cmo(CLOSES_DOWN, 9)).toBeCloseTo(-100, 10);
  });

  it("yetersiz veride `null` döner", () => {
    expect(cmo([1, 2], 9)).toBeNull();
  });
});

// ── CRSI ────────────────────────────────────────────────────────────────────

describe("signals — CRSI (backend `_crsi`: RSI + StreakRSI + PercentRank / 3)", () => {
  it("yalnız artan seride 100", () => {
    // backend `_crsi(closes, 3, 2, 10)` = 100.0
    expect(crsi(CLOSES_UP, 3, 10)).toBeCloseTo(100, 8);
  });

  it("yalnız azalan seride 0", () => {
    expect(crsi(CLOSES_DOWN, 3, 10)).toBeCloseTo(0, 8);
  });

  it("DÜZ seride 50 DEĞİL 33.33 (streak RSI'de nötr kuralı)", () => {
    // backend: streak_rsi = 50 (up == 0 ve down == 0 → nötr), rank = 0,
    // RSI = 50 → (50 + 50 + 0) / 3 = 33.333…
    //
    // ESKİ frontend kodu burada 100 dönerdi (`avgDown === 0 → 100` koşulsuz):
    // yatay piyasada CRSI ~15 pence yukarıda, "derin dip" sinyali üretirdi.
    const value = crsi(CLOSES_FLAT, 3, 10);
    expect(value).toBeCloseTo(33.333333333333336, 8);
  });

  it("dalgalı seri backend ile birebir aynı", () => {
    // backend `_crsi(closes, 3, 2, 20)` = 77.0832506675858
    //
    // ESKİ frontend kodu 1-bar DEĞİŞİMİ üzerinden percent rank saydığı için
    // burada FARKLI bir değer döndürüyordu.
    expect(crsi(CLOSES_MIXED, 3, 20)).toBeCloseTo(77.0832506675858, 8);
  });

  it("percent rank FİYAT SEVİYESİ üzerinden hesaplanır", () => {
    // Son kapanış, penceredeki TÜM kapanışlardan büyük → rank = 100.
    // Bu, 1-bar değişim yönteminden bağımsız olarak doğrulanabilir: son
    // kapanış 124, geriye bakan pencere 20 mumun tamamı daha küçük.
    const base = crsi(CLOSES_MIXED, 3, 20) as number;
    // (RSI + streakRsi + 100) / 3 olmalı. RSI 3 için seri sonunu hesapla:
    const r3 = rsi(CLOSES_MIXED, 3) as number;
    // Son iki streak: CLOSES_MIXED son iki adımı 123 → 122 → 124.
    // 123→122: negatif (-1), 122→124: pozitif (+1) → up=1, down=1
    // streakRsi = 100 - 100/(1 + 1/1) = 50
    expect(base).toBeCloseTo((r3 + 50 + 100) / 3, 10);
  });

  it("yetersiz veride `null` döner (rankPeriod + rsiPeriod + 2 kuralı)", () => {
    // backend: `len(closes) < rank_period + rsi_period + 2 → None`
    const tooShort = Array.from({ length: 20 }, (_, i) => 100 + (i % 5));
    expect(crsi(tooShort, 3, 20)).toBeNull();
    // Bir mum daha → kabul.
    const justEnough = Array.from({ length: 25 }, (_, i) => 100 + (i % 5));
    expect(crsi(justEnough, 3, 20)).not.toBeNull();
  });

  it("sonuç 0–100 aralığında kalır", () => {
    for (const closes of [CLOSES_UP, CLOSES_DOWN, CLOSES_FLAT, CLOSES_MIXED]) {
      const v = crsi(closes, 3, 20) as number;
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });
});

// ── MFI ─────────────────────────────────────────────────────────────────────

describe("signals — MFI (backend `_mfi`)", () => {
  it("yalnız artan seride 100 (aşırı alım)", () => {
    expect(mfiLast(BARS_FROM(CLOSES_UP))).toBeCloseTo(100, 8);
  });

  it("yalnız azalan seride 0", () => {
    expect(mfiLast(BARS_FROM(CLOSES_DOWN))).toBeCloseTo(0, 8);
  });

  it("DÜZ seride 100 DEĞİL 50 (nötr) — eski hata düzeltildi", () => {
    // backend: `return 100.0 if pos > 0 else 50.0` → pos == 0 → 50.
    //
    // ESKİ frontend kodu `negative === 0 → 100` koşulsuzdu: düz fiyatta
    // "aşırı alım" sinyali üretiyordu (yanlış yönlendirme).
    expect(mfiLast(BARS_FROM(CLOSES_FLAT))).toBeCloseTo(50, 8);
  });

  it("sıfır hacimde de nötr 50 döner (hacim taşısa da akış 0)", () => {
    const zeroVol = BARS_FROM(CLOSES_UP, 0);
    expect(mfiLast(zeroVol)).toBeCloseTo(50, 8);
  });

  it("dalgalı seri backend ile birebir aynı (tek tip hacim)", () => {
    // backend `_mfi(highs, lows, closes, [100]*25, 14)` = 64.72019464720194
    expect(mfiLast(BARS_MIXED)).toBeCloseTo(64.72019464720194, 8);
  });

  it("dalgalı seri, değişken hacimle backend ile birebir aynı", () => {
    // backend `_mfi(..., [100 + (i%3)*10], 14)` = 61.49164545756335
    expect(mfiLast(BARS_MIXED_ALT_VOL)).toBeCloseTo(61.49164545756335, 8);
  });

  it("yetersiz veride `null` döner", () => {
    expect(mfiLast(BARS_FROM(CLOSES_UP.slice(0, 10)))).toBeNull();
  });

  it("sonuç 0–100 aralığında kalır", () => {
    for (const bars of [BARS_FROM(CLOSES_UP), BARS_FROM(CLOSES_DOWN), BARS_MIXED, BARS_MIXED_ALT_VOL]) {
      const v = mfiLast(bars) as number;
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });

  it("hacim arttıkça pozitif akış baskınlığı değişir (duyarlılık)", () => {
    const low = mfiLast(BARS_MIXED) as number;
    const high = mfiLast(BARS_MIXED_ALT_VOL) as number;
    // İki hacim profilinin sonucu AYNI olmamalı — aksi halde hesap hacmi
    // yok sayıyor demektir (regresyon koruması).
    expect(low).not.toBeCloseTo(high, 8);
  });
});

// ── OBV ─────────────────────────────────────────────────────────────────────

describe("signals — OBV", () => {
  it("yalnız artan seride birikimli pozitif hacim", () => {
    const r = obvLast(BARS_FROM(CLOSES_UP, 10));
    // 24 mum × +10 hacim = +240
    expect(r.value).toBeCloseTo(240, 8);
  });

  it("yalnız azalan seride birikimli negatif hacim", () => {
    const r = obvLast(BARS_FROM(CLOSES_DOWN, 10));
    expect(r.value).toBeCloseTo(-240, 8);
  });

  it("yetersiz veride `null` döner", () => {
    expect(obvLast([]).value).toBeNull();
    expect(obvLast([{ time: 1, open: 1, high: 1, low: 1, close: 1, volume: 1 }]).value).toBeNull();
  });
});
