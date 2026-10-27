/**
 * "Alım yap" penceresi (BuyDialog) için saf hesaplar. Ağ çağrısı yapmaz, emir göndermez.
 *
 * Kullanıcı zarar durdur (SL) ve kâr al (TP) FİYATINI yazar; API ise yüzde mesafe (`sl_pct`) ve
 * kazanç/risk oranı (`rr`) ile "manual" modda çalışır. Dönüşüm referans fiyata (planın güncel fiyatı) göre:
 *   sl_pct = (fiyat − SL) / fiyat × 100
 *   rr     = (TP − fiyat) / (fiyat − SL)
 */
import { fmtPrice, fmtQty, fmtTry, type OpenResult } from "../../../lib/tradeUi";

export const SL_PCT_MIN = 0.5;
export const SL_PCT_MAX = 10;
export const RR_MIN = 1;
export const RR_MAX = 5;

/** Alım tutarı düğmeleri: serbest (boşta) TRY bakiyesinin yüzdesi. */
export const BUY_PCT_CHIPS: readonly number[] = [25, 50, 100];

/** Serbest bakiyenin `pct` yüzdesi, kuruşa AŞAĞI yuvarlı (bakiyeyi aşan emir gitmesin). Bakiye yoksa 0. */
export function amountFromFree(freeTry: number | null | undefined, pct: number): number {
  if (!isPos(freeTry) || !isPos(pct)) return 0;
  return Math.floor(freeTry * Math.min(pct, 100)) / 100;
}

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

export const TP_PCT_MAX = 50;
/**
 * Gerçek para kâr al alt sınırı (%). Sunucu `open_position.tp_pct_floor()` = max(0,5; 2×bacak komisyonu×100 + 0,1);
 * pencere komisyonu bilmediği için mutlak 0,5 tabanını uygular, komisyon kısmını sunucu denetler (422).
 */
export const TP_PCT_MIN = 0.5;

/**
 * Bildirim planı modu: kâr al DOĞRUDAN yüzde (`tp_pct`) olarak gider, kazanç/risk oranı (1–5) uygulanmaz.
 * SL aralığı (%0,5–10) ve TP yönü / alt (≥ %0,5) / üst (≤ %50) sınırı denetlenir.
 */
export type SlTpPlanCheck = { ok: true; slPct: number; tpPct: number } | { ok: false; error: string };
export function checkSlTpPlan(price: number, sl: number | null, tp: number | null): SlTpPlanCheck {
  if (!isPos(price)) return { ok: false, error: "Güncel fiyat alınamadı; planı yenile." };
  if (sl == null || sl <= 0) return { ok: false, error: "Zarar durdur fiyatını yaz." };
  if (tp == null || tp <= 0) return { ok: false, error: "Kâr al fiyatını yaz." };
  if (sl >= price) return { ok: false, error: "Zarar durdur fiyatı güncel fiyatın altında olmalı." };
  if (tp <= price) return { ok: false, error: "Kâr al fiyatı güncel fiyatın üstünde olmalı." };
  const slPct = slPctFromPrice(price, sl);
  const tpPct = round(((tp - price) / price) * 100, 4);
  if (slPct == null) return { ok: false, error: "Fiyatlar geçersiz." };
  if (slPct < SL_PCT_MIN) return { ok: false, error: "Zarar durdur güncel fiyata çok yakın (en az %0,5 uzakta olmalı)." };
  if (slPct > SL_PCT_MAX) return { ok: false, error: "Zarar durdur çok uzak (en fazla %10 uzakta olabilir)." };
  if (tpPct < TP_PCT_MIN) return { ok: false, error: "Kâr hedefi çok yakın (en az %0,5 uzakta olmalı; komisyonu karşılamaz)." };
  if (tpPct > TP_PCT_MAX) return { ok: false, error: "Kâr hedefi çok uzak (en fazla %50 olabilir)." };
  return { ok: true, slPct, tpPct };
}

/** `/api/binance/buy` yanıt gövdesi (yalnız onay penceresinde kullanılan alanlar). */
export type BuyFillBody = {
  status?: string;
  executed_qty?: number;
  avg_price?: number;
  executed_quote_qty?: number;
  quote_qty?: string | number;
  fill_verified?: boolean;
  idempotent_replay?: boolean;
};

/** Düz piyasa alımı sonucunu onay penceresi metnine çevirir (dolum = emir detayından doğrulanan miktar). */
export function describeBuyFill(httpStatus: number, body: BuyFillBody | null | undefined, coin: string): OpenResult {
  const b = body || {};
  if (httpStatus === 202 || b.status === "UNKNOWN") {
    return { tone: "warn", title: "Emrin sonucu henüz belli değil", detail: "Emri tekrar göndermeyin. Birazdan Binance TR sayfasından kontrol edin.", needsProtect: false, pending: true };
  }
  if (b.idempotent_replay) {
    return { tone: "warn", title: "Bu alım daha önce gönderilmişti", detail: "Aynı emir ikinci kez gönderilmedi. Binance TR sayfasından kontrol edin.", needsProtect: false, pending: false };
  }
  if (isPos(b.executed_qty) && isPos(b.avg_price)) {
    const total = isPos(b.executed_quote_qty) ? b.executed_quote_qty : b.executed_qty * b.avg_price;
    return {
      tone: "good",
      title: `Alım gerçekleşti: ${fmtQty(b.executed_qty)} ${coin}`,
      detail: `Ortalama fiyat ${fmtPrice(b.avg_price)} · toplam ${fmtTry(total)}`,
      needsProtect: false,
      pending: false,
    };
  }
  return { tone: "warn", title: "Alım emri borsaya iletildi", detail: "Dolum bilgisi henüz gelmedi; Binance TR sayfasından kontrol edin.", needsProtect: false, pending: false };
}
