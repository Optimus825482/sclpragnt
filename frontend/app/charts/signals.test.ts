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
import {
  rsi, cmo, crsi, mfiLast, rsiLast, obvLast, type Bar,
  rsiSeries, stochRsi, stochRsiCrossSignals, maRibbonBuySignals, stochMaSignals, emaSeries, smaSeries, rqKernelSignals, rqKernelPreSignals, spotExecutionSignals, strategySignalFns, strategyLabels,
} from "./signals";
import { rqkSeries, rqkLag2, rqkBullish, rqkColors } from "./rqk";
import { SLING_SHOT_ENTRY } from "./IndicatorPicker";

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

// ── Rational Quadratic Kernel + StochRSI ön sinyali ─────────────────────────

/** Deterministik sentetik seri: dalga + düşüş eğilimi + sahte gürültü (sinüs katmanları). */
const synthCloses = (n: number, seed = 1): number[] =>
  Array.from({ length: n }, (_, i) =>
    100 + 8 * Math.sin(i / 6 + seed) + 3 * Math.sin(i / 2.3 + seed * 2) - i * 0.05 + 1.5 * Math.cos(i * 1.7 + seed));

const toBars = (closes: number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1_700_000_000 + i * 60, open: c, high: c + 0.5, low: c - 0.5, close: c, volume: 1000 }));

/** ESKİ (inline) SLING_SHOT_ENTRY.calculate mantığının birebir kopyası — regresyon referansı. */
const legacyKernel = (closes: number[], h: number, r: number, smoothColors: boolean) => {
  const calc = (endIdx: number): number | null => {
    if (endIdx < 1) return null;
    let cw = 0, tw = 0;
    const lookback = Math.min(h, endIdx + 1);
    for (let i = 0; i < lookback; i++) {
      const price = closes[endIdx - i];
      if (price == null || !Number.isFinite(price)) continue;
      const w = Math.pow(1 + (Math.pow(i, 2) / (Math.pow(h, 2) * 2 * r)), -r);
      cw += price * w; tw += w;
    }
    return tw === 0 ? null : cw / tw;
  };
  const y1: (number | null)[] = [], y2: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) { y1.push(calc(i)); y2.push(calc(Math.max(0, i - 2))); }
  return closes.map((_, i) => {
    const v = y1[i];
    if (v == null || !Number.isFinite(v)) return { v: null, bull: null as boolean | null };
    const prev1 = i >= 1 ? y1[i - 1] : null, prev2 = i >= 2 ? y1[i - 2] : null, v2 = y2[i];
    let bull = false;
    if (smoothColors) bull = v2 != null && v2 > v;
    else if (prev1 != null && prev2 != null) bull = prev1 < v || (prev2 > prev1 && !(prev1 > v));
    else if (prev1 != null) bull = prev1 < v;
    else bull = true;
    return { v, bull };
  });
};

describe("rqkSeries / rqkBullish", () => {
  it("elle doğrulanmış fixture: h=3, r=2, closes [10,12,11,13]", () => {
    // w(k) = (1 + k²/36)^-2  →  w0=1, w1=(36/37)²=0.946676, w2=(9/10)²=0.81
    const y = rqkSeries([10, 12, 11, 13], 3, 2);
    expect(y[0]).toBeNull();
    expect(y[1]).toBeCloseTo((12 + 10 * 0.9466764) / (1 + 0.9466764), 5);
    expect(y[2]).toBeCloseTo((11 + 12 * 0.9466764 + 10 * 0.81) / (1 + 0.9466764 + 0.81), 5);
    expect(y[3]).toBeCloseTo((13 + 11 * 0.9466764 + 12 * 0.81) / (1 + 0.9466764 + 0.81), 5);
    expect(y[1]).toBeCloseTo(11.027392, 4);
    expect(y[2]).toBeCloseTo(11.049579, 4);
    expect(y[3]).toBeCloseTo(12.019343, 4);
  });

  it("eski inline implementasyonla birebir aynı (yhat + renk), tüm parametre kombinasyonlarında", () => {
    for (const seed of [1, 2, 3]) {
      const closes = synthCloses(120, seed);
      closes[17] = NaN; // sonlu olmayan kapanış kenar durumu
      for (const [h, r] of [[3, 0.25], [8, 2], [13, 1.5], [30, 4]] as const) {
        for (const smooth of [false, true]) {
          const ref = legacyKernel(closes, h, r, smooth);
          const y = rqkSeries(closes, h, r);
          const bull = rqkBullish(y, rqkLag2(y), smooth);
          y.forEach((v, i) => {
            expect(v).toBe(ref[i].v);
            expect(bull[i]).toBe(ref[i].bull);
          });
        }
      }
    }
  });

  it("SLING_SHOT_ENTRY.calculate çıktısı rqk ile aynı renk/değerleri üretir", () => {
    const bars = toBars(synthCloses(80));
    const out = SLING_SHOT_ENTRY.calculate(bars as any, {}) as any;
    const { yhat, bullish } = rqkColors(bars.map((b) => b.close), {});
    out.plots.plot0.forEach((pt: any, i: number) => {
      expect(pt.value).toBe(yhat[i]);
      if (bullish[i] == null) expect(pt.color).toBeUndefined();
      else expect(pt.color).toBe(bullish[i] ? "#3AFF17" : "#FD1707");
    });
  });
});

describe("RQ Kernel B/S okları = renk dönüşleri", () => {
  const flips = (closes: number[], bars: Bar[], params: Record<string, any>) => {
    const h = Math.max(3, Number(params.h ?? 8)), r = Math.max(0.25, Number(params.r ?? 2));
    const y = rqkSeries(closes, h, r);
    const bull = rqkBullish(y, rqkLag2(y), params.smoothColors ?? false);
    const out: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = 1; i < closes.length; i++) {
      if (bull[i] === true && bull[i - 1] === false) out.push({ time: bars[i].time, type: "buy" });
      if (bull[i] === false && bull[i - 1] === true) out.push({ time: bars[i].time, type: "sell" });
    }
    return out;
  };

  it("varsayılan ve özel parametrelerde renk dönüşleriyle birebir örtüşür", () => {
    for (const params of [{}, { h: 8, r: 2, smoothColors: false }, { h: 5, r: 1, smoothColors: true }, { h: 14, r: 3 }]) {
      const closes = synthCloses(200, 2);
      const bars = toBars(closes);
      const sig = rqKernelSignals(bars, params);
      expect(sig.length).toBeGreaterThan(4);
      expect(sig).toEqual(flips(closes, bars, params));
      sig.forEach((s, i) => { if (i > 0) expect(s.type).not.toBe(sig[i - 1].type); });
    }
  });

  it("strategySignalFns.sling_shot instance parametrelerini kullanır ve etiket 'RQ Kernel'", () => {
    const bars = toBars(synthCloses(150, 3));
    const viaFn = strategySignalFns.sling_shot(bars, { h: 5, r: 1, smoothColors: true, showPreSignals: false });
    expect(viaFn).toEqual(rqKernelSignals(bars, { h: 5, r: 1, smoothColors: true }));
    expect(viaFn).not.toEqual(rqKernelSignals(bars, {})); // parametre gerçekten akıyor
    expect(strategyLabels.sling_shot).toBe("RQ Kernel");
  });

  it("monoton artan seride dönüş yok (tek yön)", () => {
    expect(rqKernelSignals(toBars(CLOSES_UP), {})).toEqual([]);
  });
});

describe("StochRSI", () => {
  it("rsiSeries son değeri rsi() ile aynı", () => {
    for (const c of [CLOSES_MIXED, CLOSES_UP, CLOSES_DOWN, CLOSES_FLAT]) {
      const s = rsiSeries(c, 14);
      expect(s[c.length - 1]).toBeCloseTo(rsi(c, 14) as number, 10);
      expect(s.slice(0, 14).every((v) => v === null)).toBe(true);
    }
  });

  it("elle doğrulanmış fixture (rsi=2, stoch=2, K=2, D=2)", () => {
    // closes [10,11,10,11,12,11]; RSI[2]=50, RSI[3]=75, RSI[4]=87.5, RSI[5]=43.75
    const r = stochRsi([10, 11, 10, 11, 12, 11], 2, 2, 2, 2);
    expect(r.rsi[2]).toBeCloseTo(50, 10);
    expect(r.rsi[3]).toBeCloseTo(75, 10);
    expect(r.rsi[4]).toBeCloseTo(87.5, 10);
    expect(r.rsi[5]).toBeCloseTo(43.75, 10);
    expect(r.stoch.slice(0, 3)).toEqual([null, null, null]);
    expect(r.stoch[3]).toBeCloseTo(100, 10);
    expect(r.stoch[4]).toBeCloseTo(100, 10);
    expect(r.stoch[5]).toBeCloseTo(0, 10);
    expect(r.k[3]).toBeNull();
    expect(r.k[4]).toBeCloseTo(100, 10);
    expect(r.k[5]).toBeCloseTo(50, 10);
    expect(r.d[4]).toBeNull();
    expect(r.d[5]).toBeCloseTo(75, 10);
  });

  it("sabit seri: aralık 0 → stoch 0, NaN yok", () => {
    const r = stochRsi(Array.from({ length: 60 }, () => 50), 14, 14, 3, 3);
    const defined = (a: (number | null)[]) => a.filter((v) => v !== null) as number[];
    expect(defined(r.stoch).length).toBeGreaterThan(0);
    for (const arr of [r.rsi, r.stoch, r.k, r.d]) for (const v of defined(arr)) expect(Number.isNaN(v)).toBe(false);
    expect(defined(r.stoch).every((v) => v === 0)).toBe(true);
    expect(defined(r.k).every((v) => v === 0)).toBe(true);
    expect(defined(r.d).every((v) => v === 0)).toBe(true);
  });
});

describe("Ön sinyal (kernel + StochRSI)", () => {
  const closes = synthCloses(400, 1);
  const bars = toBars(closes);
  const ref = (params: Record<string, any>) => {
    const level = params.stochLevel ?? 20;
    const { bullish } = rqkColors(closes, params);
    const { k, d } = stochRsi(closes, 14, 14, 3, 3);
    const times: number[] = [];
    for (let i = 1; i < closes.length; i++) {
      if (k[i - 1] == null || d[i - 1] == null || k[i] == null || d[i] == null) continue;
      if (k[i - 1]! <= d[i - 1]! && k[i]! > d[i]! && k[i - 1]! < level && bullish[i] === false) times.push(bars[i].time);
    }
    return times;
  };

  it("yalnız: K D'yi yukarı keserken, K[i-1] < seviye iken ve kernel kırmızıyken tetiklenir", () => {
    const sig = rqKernelPreSignals(bars, { stochLevel: 30 });
    expect(sig.length).toBeGreaterThan(0);
    expect(sig.map((s) => s.time)).toEqual(ref({ stochLevel: 30 }));
    const idx = new Map(bars.map((b, i) => [b.time, i]));
    const { bullish } = rqkColors(closes, {});
    const { k, d } = stochRsi(closes, 14, 14, 3, 3);
    for (const s of sig) {
      expect(s.type).toBe("pre");
      const i = idx.get(s.time)!;
      expect(bullish[i]).toBe(false);
      expect(k[i - 1]!).toBeLessThanOrEqual(d[i - 1]!);
      expect(k[i]!).toBeGreaterThan(d[i]!);
      expect(k[i - 1]!).toBeLessThan(30);
    }
  });

  it("seviye düşünce sinyaller yalnızca azalır (20 alt kümesi 30), seviye 0 → sinyal yok", () => {
    const s20 = rqKernelPreSignals(bars, { stochLevel: 20 }).map((s) => s.time);
    const s30 = rqKernelPreSignals(bars, { stochLevel: 30 }).map((s) => s.time);
    expect(s20).toEqual(ref({ stochLevel: 20 }));
    s20.forEach((t) => expect(s30).toContain(t));
    expect(s30.length).toBeGreaterThanOrEqual(s20.length);
    expect(rqKernelPreSignals(bars, { stochLevel: 0 })).toEqual([]);
  });

  it("kernel yeşilken veya seri sabitken ön sinyal üretilmez", () => {
    expect(rqKernelPreSignals(toBars(CLOSES_UP), { stochLevel: 50 })).toEqual([]);
    expect(rqKernelPreSignals(toBars(CLOSES_FLAT), { stochLevel: 50 })).toEqual([]);
  });

  it("showPreSignals=false → strateji fonksiyonu ön sinyal döndürmez; açıkken 'pre' içerir", () => {
    const withPre = strategySignalFns.sling_shot(bars, { stochLevel: 30 });
    const without = strategySignalFns.sling_shot(bars, { stochLevel: 30, showPreSignals: false });
    expect(without.some((s) => s.type === "pre")).toBe(false);
    expect(withPre.filter((s) => s.type === "pre").length).toBe(rqKernelPreSignals(bars, { stochLevel: 30 }).length);
    expect(withPre.filter((s) => s.type !== "pre")).toEqual(without);
  });

  it("spotExecutionSignals ön sinyalleri işlem saymaz", () => {
    const raw = strategySignalFns.sling_shot(bars, { stochLevel: 30 });
    expect(raw.some((s) => s.type === "pre")).toBe(true);
    const onlyTrades = raw.filter((s) => s.type !== "pre");
    expect(spotExecutionSignals(bars, raw)).toEqual(spotExecutionSignals(bars, onlyTrades));
    expect(spotExecutionSignals(bars, raw.filter((s) => s.type === "pre"))).toEqual([]);
  });
});


// 2026-10-18 (kullanıcı isteği): StochRSI kesişim okları + MA şerit BUY etiketi.
const mkBars = (closes: number[]): Bar[] => closes.map((c, i) => ({ time: 1_700_000_000 + i * 300, open: c, high: c + 0.5, low: c - 0.5, close: c, volume: 1 }));

describe("emaSeries / smaSeries", () => {
  it("SMA tohumlu EMA ve kayan SMA", () => {
    const v = [1, 2, 3, 4, 5, 6];
    const sma = smaSeries(v, 3);
    expect(sma.slice(0, 2)).toEqual([null, null]);
    expect(sma[2]).toBeCloseTo(2, 9);
    expect(sma[5]).toBeCloseTo(5, 9);
    const ema = emaSeries(v, 3);
    expect(ema[2]).toBeCloseTo(2, 9);                 // tohum = ilk 3'ün SMA'sı
    expect(ema[3]).toBeCloseTo(2 + (4 - 2) * 0.5, 9); // alpha 0.5
    expect(emaSeries([1, 2], 3)).toEqual([null, null]);
  });
});

describe("stochRsiCrossSignals", () => {
  it("20 altı yukarı kesişim → yeşil ok altta; 80 üstü aşağı kesişim → kırmızı ok üstte; aradakiler yok", () => {
    // Uzun düşüş (K/D dibe iner), sonra sert yükseliş (K, D'yi 20 altından yukarı keser),
    // sonra uzun yükseliş (K/D tepeye çıkar) ve düşüş (K, D'yi 80 üstünden aşağı keser).
    const closes: number[] = [];
    let c = 100;
    for (let i = 0; i < 40; i++) { c -= 0.8; closes.push(c); }
    for (let i = 0; i < 30; i++) { c += 1.1; closes.push(c); }
    for (let i = 0; i < 30; i++) { c -= 1.0; closes.push(c); }
    const bars = mkBars(closes);
    const sig = stochRsiCrossSignals(bars, {});
    const buys = sig.filter((s) => s.type === "buy");
    const sells = sig.filter((s) => s.type === "sell");
    expect(buys.length).toBeGreaterThanOrEqual(1);
    expect(sells.length).toBeGreaterThanOrEqual(1);
    expect(buys[0]).toMatchObject({ shape: "arrowUp", color: "#10b981", text: "" });
    expect(sells[0]).toMatchObject({ shape: "arrowDown", color: "#ef4444", text: "" });
    expect(buys[0].time).toBeLessThan(sells[0].time);
    // Kesişim bar indeksinde K gerçekten D'yi geçmiş olmalı ve bir önceki K < 20 olmalı
    const { k, d } = stochRsi(closes, 14, 14, 3, 3);
    const idx = bars.findIndex((b) => b.time === buys[0].time);
    expect(k[idx - 1]! <= d[idx - 1]! && k[idx]! > d[idx]! && k[idx - 1]! < 20).toBe(true);
    // Seviyeler sıkılaştırılınca sinyal azalır/yok olur
    // Düz çizgisel seride K tam 0/100 olabilir; imkânsız seviyelerle hiç sinyal üretilmemeli
    expect(stochRsiCrossSignals(bars, { stochLow: -1, stochHigh: 101 })).toHaveLength(0);
  });
  it("yetersiz veri → boş", () => {
    expect(stochRsiCrossSignals(mkBars([1, 2, 3, 4, 5]), {})).toEqual([]);
  });
});

describe("maRibbonBuySignals", () => {
  it("orta > yavaş iken hızlının ortayı yukarı kesmesi → BUY etiketi; aşağı trendde yok", () => {
    // Yavaş yükseliş (orta > yavaş kurulsun), kısa geri çekilme (hızlı ortanın altına), sonra sıçrama (hızlı ortayı yukarı keser)
    const closes: number[] = [];
    let c = 100;
    for (let i = 0; i < 120; i++) { c += 0.3; closes.push(c); }
    for (let i = 0; i < 8; i++) { c -= 1.2; closes.push(c); }
    for (let i = 0; i < 12; i++) { c += 1.5; closes.push(c); }
    const bars = mkBars(closes);
    const sig = maRibbonBuySignals(bars, { maFast: 7, maMid: 20, maSlow: 99 });
    expect(sig.length).toBeGreaterThanOrEqual(1);
    expect(sig[sig.length - 1]).toMatchObject({ type: "buy", text: "BUY", badge: true, color: "#16a34a" });
    const idx = bars.findIndex((b) => b.time === sig[sig.length - 1].time);
    expect(idx).toBeGreaterThan(128);                 // kesişim sıçramadan sonra
    const fast = emaSeries(closes, 7), mid = emaSeries(closes, 20), slow = emaSeries(closes, 99);
    expect(fast[idx - 1]! <= mid[idx - 1]! && fast[idx]! > mid[idx]! && mid[idx]! > slow[idx]!).toBe(true);
    // Düşüş trendinde (orta < yavaş) kesişim olsa da BUY yok
    const down = mkBars(closes.map((v, i) => 300 - v + (i % 9 === 0 ? 3 : 0)));
    const downSig = maRibbonBuySignals(down, {});
    const sl = emaSeries(down.map((b) => b.close), 99), md = emaSeries(down.map((b) => b.close), 20);
    for (const s of downSig) { const j = down.findIndex((b) => b.time === s.time); expect(md[j]! > sl[j]!).toBe(true); }
  });
  it("sma türü ve kapatma bayrakları", () => {
    const closes = Array.from({ length: 150 }, (_, i) => 100 + i * 0.2 + (i > 140 ? 3 : 0) - (i > 132 && i <= 140 ? 2 : 0));
    const bars = mkBars(closes);
    const ema = maRibbonBuySignals(bars, {});
    const sma = maRibbonBuySignals(bars, { maType: "sma" });
    expect(Array.isArray(ema) && Array.isArray(sma)).toBe(true);
    const all = stochMaSignals(bars, {});
    const none = stochMaSignals(bars, { showStochArrows: false, showMaBuy: false });
    expect(none).toEqual([]);
    expect(all.length).toBe(stochRsiCrossSignals(bars, {}).length + maRibbonBuySignals(bars, {}).length);
    for (let i = 1; i < all.length; i++) expect(all[i].time).toBeGreaterThanOrEqual(all[i - 1].time);
  });
});
