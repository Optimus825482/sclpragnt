// Grafik zaman ekseni: lightweight-charts zamanı HEP UTC biçimler; kullanıcı Türkiye saatini (UTC+3) bekler.
// Mum zaman damgaları (epoch saniye) aynı kalır — yalnız EKRANDA gösterilen saat Europe/Istanbul'a çevrilir.

const TZ = "Europe/Istanbul";

const part = (ms: number, opts: Intl.DateTimeFormatOptions): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hourCycle: "h23", ...opts }).formatToParts(new Date(ms))) {
    if (p.type !== "literal") out[p.type] = p.value;
  }
  return out;
};

const toMs = (time: unknown): number | null => {
  if (typeof time === "number" && Number.isFinite(time)) return time * 1000;
  return null;                                             // BusinessDay nesnesi: günlük takvim, saat yok
};

/** Çarpı eksenindeki etiket (TickMarkType: 0 yıl, 1 ay, 2 gün, 3 saat, 4 saniyeli saat). */
export function istanbulTickMark(time: unknown, tickMarkType: number): string | null {
  const ms = toMs(time);
  if (ms === null) return null;
  if (tickMarkType === 0) return part(ms, { year: "numeric" }).year;
  if (tickMarkType === 1) return part(ms, { month: "short" }).month;
  if (tickMarkType === 2) {
    const p = part(ms, { day: "numeric", month: "short" });
    return `${p.day} ${p.month}`;
  }
  const p = part(ms, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return tickMarkType === 4 ? `${p.hour}:${p.minute}:${p.second}` : `${p.hour}:${p.minute}`;
}

/** Çapraz imleç etiketi: `18 Eki '26  07:32` (Türkiye saati). */
export function istanbulCrosshairTime(time: unknown): string {
  const ms = toMs(time);
  if (ms === null) return "";
  const p = part(ms, { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" });
  return `${p.day} ${p.month} '${p.year}  ${p.hour}:${p.minute}`;
}

/** createChart seçeneklerine yayılır: `{ ...istanbulChartOptions }` + timeScale içine `tickMarkFormatter`. */
export const istanbulLocalization = { timeFormatter: istanbulCrosshairTime };
export const istanbulTickMarkFormatter = (time: unknown, tickMarkType: number) => istanbulTickMark(time, tickMarkType);
