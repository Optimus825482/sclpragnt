/**
 * "Alım yap" penceresi (BuyDialog) için saf hesaplar. Ağ çağrısı yapmaz, emir göndermez.
 *
 * Kullanıcı zarar durdur (SL) ve kâr al (TP) FİYATINI yazar; API ise yüzde mesafe (`sl_pct`) ve
 * kazanç/risk oranı (`rr`) ile "manual" modda çalışır. Dönüşüm referans fiyata (planın güncel fiyatı) göre:
 *   sl_pct = (fiyat − SL) / fiyat × 100
 *   rr     = (TP − fiyat) / (fiyat − SL)
 */

export const SL_PCT_MIN = 0.5;
export const SL_PCT_MAX = 10;
export const RR_MIN = 1;
export const RR_MAX = 5;

/** Tek dokunuş SL/TP düğmeleri: güncel fiyattan yüzde mesafe. Oran (TP%/SL%) API sınırı 1–5 içinde kalmalı. */
export const SL_PCT_CHIPS: readonly number[] = [1, 2, 3, 5];
export const TP_PCT_CHIPS: readonly number[] = [2, 3, 5, 8];

const isPos = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;
const round = (n: number, digits: number) => {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
};

/** SL fiyatından zarar durdur mesafesi (%). Fiyat/SL geçersizse ya da SL fiyatın altında değilse null. */
export function slPctFromPrice(price: number, sl: number): number | null {
  if (!isPos(price) || !isPos(sl) || sl >= price) return null;
  return round(((price - sl) / price) * 100, 4);
}

/** Fiyatın `pct` yüzde uzağı (eksi = aşağı). Fiyat geçersizse null. */
export function priceAtPct(price: number, pct: number): number | null {
  if (!isPos(price) || !Number.isFinite(pct)) return null;
  return price * (1 + pct / 100);
}

/** Fiyatın güncel fiyata göre yüzde farkı (düğmenin seçili görünmesi için). */
export function pctFromPrice(price: number, target: number | null): number | null {
  if (!isPos(price) || target == null || !isPos(target)) return null;
  return round(((target - price) / price) * 100, 2);
}

/** SL ve TP fiyatından kazanç/risk oranı. SL fiyatın altında, TP fiyatın üstünde değilse null. */
export function rrFromPrices(price: number, sl: number, tp: number): number | null {
  if (!isPos(price) || !isPos(sl) || !isPos(tp) || sl >= price || tp <= price) return null;
  return round((tp - price) / (price - sl), 4);
}

/** Planın SL/TP fiyatları (sunucu değerleri varsa onlar; yoksa sl_pct + rr'den hesaplanır). */
export function pricesFromPlan(
  price: number,
  plan: { sl_price?: number | null; tp_price?: number | null; sl_pct?: number | null; rr?: number | null },
): { sl: number | null; tp: number | null } {
  if (isPos(plan.sl_price) && isPos(plan.tp_price)) return { sl: plan.sl_price, tp: plan.tp_price };
  if (!isPos(price) || !isPos(plan.sl_pct) || !isPos(plan.rr)) return { sl: null, tp: null };
  const sl = price * (1 - plan.sl_pct / 100);
  const tp = price + (price - sl) * plan.rr;
  return { sl, tp };
}

export type SlTpCheck =
  | { ok: true; slPct: number; rr: number }
  | { ok: false; error: string };

/** Yazılan SL/TP fiyatlarını API'nin manuel moduna çevirir ve sınırları (SL %0,5–10, oran 1–5) Türkçe hatalarla denetler. */
export function checkSlTp(price: number, sl: number | null, tp: number | null): SlTpCheck {
  if (!isPos(price)) return { ok: false, error: "Güncel fiyat alınamadı; planı yenile." };
  if (sl == null || sl <= 0) return { ok: false, error: "Zarar durdur fiyatını yaz." };
  if (tp == null || tp <= 0) return { ok: false, error: "Kâr al fiyatını yaz." };
  if (sl >= price) return { ok: false, error: "Zarar durdur fiyatı güncel fiyatın altında olmalı." };
  if (tp <= price) return { ok: false, error: "Kâr al fiyatı güncel fiyatın üstünde olmalı." };
  const slPct = slPctFromPrice(price, sl);
  const rr = rrFromPrices(price, sl, tp);
  if (slPct == null || rr == null) return { ok: false, error: "Fiyatlar geçersiz." };
  if (slPct < SL_PCT_MIN) return { ok: false, error: "Zarar durdur güncel fiyata çok yakın (en az %0,5 uzakta olmalı)." };
  if (slPct > SL_PCT_MAX) return { ok: false, error: "Zarar durdur çok uzak (en fazla %10 uzakta olabilir)." };
  if (rr < RR_MIN) return { ok: false, error: "Kâr hedefi, zarar mesafesinden küçük olamaz (oran en az 1:1)." };
  if (rr > RR_MAX) return { ok: false, error: "Kâr hedefi çok uzak (oran en fazla 1:5 olabilir)." };
  return { ok: true, slPct, rr };
}
