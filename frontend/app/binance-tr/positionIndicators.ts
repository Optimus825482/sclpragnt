/**
 * Pozisyon grafiği (BinancePositionChartModal) göstergeleri — saf hesap, DOM/grafik yok.
 *
 * 2026-10-20: MA 7 / 20 / 99 (SMA; bildirim motoru ve ana grafikteki MA şeridiyle aynı tür) ve
 * StochRSI 14/14/3/3 paneli. Matematik `charts/signals.ts` ile ORTAK (smaSeries, stochRsi) ki
 * grafikteki çizgiler push bildirimlerindeki kesişimlerle birebir aynı muma otursun.
 */
import { smaSeries, stochRsi } from "../charts/signals";

export type IndicatorBar = { time: number; open: number; high: number; low: number; close: number };
export type LinePoint = { time: number; value: number };

export const MA_LENGTHS = { fast: 7, mid: 20, slow: 99 } as const;
export const MA_COLORS = { fast: "#f59e0b", mid: "#3b82f6", slow: "#a855f7" } as const; // turuncu / mavi / mor
export const STOCH_PARAMS = { rsiLen: 14, stochLen: 14, kLen: 3, dLen: 3 } as const;
export const STOCH_LEVELS = [20, 50, 80] as const;

const toPoints = (bars: IndicatorBar[], values: (number | null)[]): LinePoint[] => {
  const out: LinePoint[] = [];
  for (let i = 0; i < bars.length; i++) {
    const v = values[i];
    if (v != null && Number.isFinite(v)) out.push({ time: bars[i].time, value: v });
  }
  return out;
};

/** SMA 7/20/99 çizgileri; yeterli mum olmayan çizgi boş döner (null nokta üretilmez). */
export function maRibbonPoints(bars: IndicatorBar[]): { fast: LinePoint[]; mid: LinePoint[]; slow: LinePoint[] } {
  const closes = bars.map((b) => b.close);
  const line = (n: number) => (bars.length >= n ? toPoints(bars, smaSeries(closes, n)) : []);
  return { fast: line(MA_LENGTHS.fast), mid: line(MA_LENGTHS.mid), slow: line(MA_LENGTHS.slow) };
}

/** StochRSI K ve D çizgileri (0–100). Isınma süresi dolmadan boş döner. */
export function stochRsiPoints(bars: IndicatorBar[]): { k: LinePoint[]; d: LinePoint[] } {
  const closes = bars.map((b) => b.close);
  const { k, d } = stochRsi(closes, STOCH_PARAMS.rsiLen, STOCH_PARAMS.stochLen, STOCH_PARAMS.kLen, STOCH_PARAMS.dLen);
  return { k: toPoints(bars, k), d: toPoints(bars, d) };
}

/** Canlı mum listesi: aynı kovadaki mum değiştirilir, yeni kova eklenir, eski mum yok sayılır. Girdi değişmez. */
export function withLiveBar<T extends IndicatorBar>(bars: T[], live: T): T[] {
  if (bars.length === 0) return [live];
  const last = bars[bars.length - 1];
  if (live.time === last.time) return [...bars.slice(0, -1), live];
  if (live.time > last.time) return [...bars, live];
  return bars;
}
