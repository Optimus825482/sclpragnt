import { describe, expect, it } from "vitest";
import { maRibbonPoints, stochRsiPoints, withLiveBar, MA_LENGTHS, STOCH_PARAMS } from "./positionIndicators";

const bar = (i: number, close: number) => ({ time: 60 * (i + 1), open: close, high: close, low: close, close });
const rising = (n: number) => Array.from({ length: n }, (_, i) => bar(i, 100 + i));

describe("maRibbonPoints — SMA 7 / 20 / 99 (turuncu / mavi / mor)", () => {
  it("uses SMA with lengths 7, 20, 99", () => {
    expect(MA_LENGTHS).toEqual({ fast: 7, mid: 20, slow: 99 });
  });

  it("fast line is the simple mean of the last 7 closes and starts at the 7th bar", () => {
    const bars = Array.from({ length: 10 }, (_, i) => bar(i, i + 1)); // closes 1..10
    const { fast } = maRibbonPoints(bars);
    expect(fast[0]).toEqual({ time: bars[6].time, value: 4 });          // mean(1..7)
    expect(fast[fast.length - 1]).toEqual({ time: bars[9].time, value: 7 }); // mean(4..10)
    expect(fast).toHaveLength(4);
  });

  it("omits lines that do not have enough bars yet instead of emitting nulls", () => {
    const { mid, slow } = maRibbonPoints(rising(10));
    expect(mid).toEqual([]);
    expect(slow).toEqual([]);
  });
});

describe("stochRsiPoints — RSI 14, Stoch 14, K 3, D 3", () => {
  it("uses the standard 14/14/3/3 parameters", () => {
    expect(STOCH_PARAMS).toEqual({ rsiLen: 14, stochLen: 14, kLen: 3, dLen: 3 });
  });

  it("pins K and D to 100 when RSI keeps making new window highs (dip then rally) and aligns points with bar times", () => {
    // 30 bar düşüş, 30 bar yükseliş: toparlanmada RSI her barda pencere zirvesi yapar → stoch 100 → K = D = 100.
    // (Sabit adımla yalnız yükselen seride RSI sabit 100 kalır; pencere zirvesi = dibi olduğundan tanım 0 verir.)
    const bars = Array.from({ length: 60 }, (_, i) => bar(i, i < 30 ? 200 - i : 170 + (i - 30)));
    const { k, d } = stochRsiPoints(bars);
    expect(k[k.length - 1]).toEqual({ time: bars[59].time, value: 100 });
    expect(d[d.length - 1]).toEqual({ time: bars[59].time, value: 100 });
    expect(k.every((p) => p.value >= 0 && p.value <= 100)).toBe(true);
    expect(d.length).toBe(k.length - 2); // D, K'nın 3'lük ortalaması: 2 bar sonra başlar
  });

  it("returns nothing when there are fewer bars than the warm-up needs", () => {
    const { k, d } = stochRsiPoints(rising(20));
    expect(k).toEqual([]);
    expect(d).toEqual([]);
  });
});

describe("withLiveBar — canlı tik sonrası hesap için mum listesi", () => {
  it("replaces the last bar when the live bar is in the same bucket", () => {
    const bars = rising(3);
    const live = { ...bars[2], close: 999, high: 999 };
    const out = withLiveBar(bars, live);
    expect(out).toHaveLength(3);
    expect(out[2].close).toBe(999);
    expect(bars[2].close).toBe(102); // girdi değişmez
  });

  it("appends the live bar when it opens a new bucket", () => {
    const bars = rising(3);
    const out = withLiveBar(bars, bar(3, 5));
    expect(out).toHaveLength(4);
    expect(out[3].close).toBe(5);
  });

  it("ignores a live bar older than the last bar", () => {
    const bars = rising(3);
    expect(withLiveBar(bars, bar(0, 5))).toEqual(bars);
  });
});
