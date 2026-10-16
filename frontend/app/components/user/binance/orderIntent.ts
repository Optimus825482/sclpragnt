/**
 * Basit mod (kullanıcı arayüzü) al/sat kartları için GERÇEK PARA emir güvenliği yardımcıları (saf, testli).
 *
 * 2026-10-16 (basit arayüz): `client_order_id` her onay penceresi açılışında yeniden üretildiği için ağ hatası sonrası
 * "tekrar dene" mükerrer alım yaratabiliyordu. Kimlik artık "emir niyeti" (sembol + tutar/miktar) başına BİR kez
 * üretilir; yalnız kesin sonuçtan (başarı / kesin red) ya da niyet değişince sıfırlanır.
 * Emir göndermez; ağ çağrısı yapmaz (yalnız hesap/metin üretir).
 */
import { netOpenPnlPct, netOpenPnlTry } from "../../../lib/pnl";
import { newClientOrderId } from "../../../lib/tradeUi";

export type IntentRef = { key: string; id: string };

/** Aynı niyet anahtarı için aynı kimliği döndürür; anahtar değiştiyse (ya da kimlik yoksa) yenisini üretir. */
export function intentId(ref: IntentRef, key: string, gen: () => string = newClientOrderId): string {
  if (!ref.id || ref.key !== key) {
    ref.key = key;
    ref.id = gen();
  }
  return ref.id;
}

/** Kesin sonuçtan sonra (başarı / kesin red) kimliği bırakır; bir sonraki emir yeni kimlik alır. */
export function resetIntent(ref: IntentRef): void {
  ref.key = "";
  ref.id = "";
}

/** Niyet anahtarı: sembol + tutar/miktar (sayı aynı metne normalize edilir). */
export function buyIntentKey(symbol: string, amountTry: number): string {
  return `buy|${symbol}|${Number(amountTry).toFixed(2)}`;
}

export function sellIntentKey(asset: string, chip: number, qty: number): string {
  return `sell|${asset}|${chip}|${Number(qty).toFixed(8)}`;
}

/**
 * HTTP yanıtı geldi: emir KESİN reddedildi mi (yeni kimlikle yeniden denenebilir) yoksa belirsiz mi?
 * 408/504 ve gövdesiz 5xx belirsizdir (proxy zaman aşımı) → aynı kimlik korunur.
 * 202 ayrıca çağıranda ele alınır (status === "failed" ise kesin red).
 */
export function isDefinitiveReject(status: number, detail: unknown): boolean {
  if (status === 408 || status === 504) return false;
  if (status >= 500) return typeof detail === "string" && detail.trim().length > 0;
  return status >= 400;
}

type CallResult = { ok: boolean; status: number; error: string; body: unknown };

/** 2026-10-17 (basit arayüz): nginx'in ürettiği "Backend servisi şu an meşgul veya
 *  başlatılıyor" yanıtı (503, status:"unavailable") — backend'e ulaşılamadı demektir
 *  (deploy / yeniden başlatma / bayat upstream). Emir hatası DEĞİLDİR. */
export function isGatewayUnavailable(r: CallResult): boolean {
  if (r.status !== 503) return false;
  const body = (r.body ?? {}) as { status?: unknown; detail?: unknown };
  const text = `${String(body.status ?? "")} ${String(body.detail ?? "")} ${r.error ?? ""}`.toLowerCase();
  return text.includes("unavailable") || text.includes("meşgul") || text.includes("başlatılıyor");
}

/** Ağ geçidi "unavailable" dönerse birkaç saniye bekleyip yeniden dener (yalnız okuma sorguları için). */
export async function retryWhileGatewayUnavailable<R extends CallResult>(
  fn: () => Promise<R>, attempts = 3, delayMs = 4000,
): Promise<R> {
  let last = await fn();
  for (let i = 1; i < attempts && isGatewayUnavailable(last); i += 1) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    last = await fn();
  }
  return last;
}

/** `/api/binance/order-status` yanıtını (ya da hata metnini) kullanıcıya anlatır. */
export function describeOrderLookup(r: { ok: boolean; status: number; error: string; body: unknown }): string {
  if (!r.ok) {
    if (r.status === 0) return "Sorgu da gönderilemedi (bağlantı yok). Birazdan tekrar sorgulayın; sonuç öğrenilmeden yeniden göndermeyin.";
    if (isGatewayUnavailable(r)) {
      return "Sunucuya ulaşılamadı (backend yeniden başlıyor ya da geçici kesinti). Bu bir emir hatası değil; emir borsaya ulaşmamış olabilir. 10–20 sn sonra \"Durumu sorgula\"ya tekrar basın; sonuç öğrenilmeden yeniden göndermeyin.";
    }
    return `Sorgu başarısız: ${r.error}. Emir yine de borsada olabilir; Bekleyen Emirler ve Geçmiş’i kontrol edin.`;
  }
  const order = (r.body as { order?: Record<string, unknown> } | null)?.order;
  if (!order || typeof order !== "object" || Object.keys(order).length === 0) {
    return "Borsada bu kimlikle emir bulunamadı. Emir ulaşmamış görünüyor; aynı pencereden tekrar göndermek güvenlidir (aynı kimlik kullanılır).";
  }
  const status = String(order.status ?? order.orderStatus ?? "").trim();
  const executed = Number(order.executedQty ?? order.executed_qty);
  const bits = ["Emir borsada BULUNDU"];
  if (status) bits.push(`durum: ${status}`);
  if (Number.isFinite(executed) && executed > 0) bits.push(`dolan miktar: ${executed}`);
  return `${bits.join(", ")}. Tekrar göndermeyin; Bekleyen Emirler ve Geçmiş sekmelerinden doğrulayın.`;
}

export const PRICE_STALE_MS = 15_000;

/** Fiyat yaşı metni ("şimdi", "7 sn önce") + 15 sn üstü uyarı. `fetchedAt` yoksa yaş bilinmiyor. */
export function priceAgeInfo(fetchedAt: number | null, now: number): { text: string; stale: boolean } {
  if (fetchedAt == null) return { text: "güncelleme zamanı bilinmiyor", stale: true };
  const sec = Math.max(0, Math.round((now - fetchedAt) / 1000));
  return { text: sec < 2 ? "şimdi alındı" : `${sec} sn önce alındı`, stale: now - fetchedAt > PRICE_STALE_MS };
}

/** Elindeki coin için NET (gidiş-dönüş komisyonlu) K/Z; maliyet ya da fiyat yoksa null. */
export function holdingNetPnl(
  avgCost: number | null | undefined, livePrice: number | null | undefined, qty: number | null | undefined,
): { pct: number; tryValue: number } | null {
  const pct = netOpenPnlPct(avgCost, livePrice, qty);
  const tryValue = netOpenPnlTry(avgCost, livePrice, qty);
  if (pct === null || tryValue === null) return null;
  return { pct, tryValue };
}

/** Emir tutarı borsanın minimum notional'ının altındaysa hata metni; bilinmiyorsa (null) kontrol atlanır. */
export function minNotionalError(valueTry: number | null | undefined, minNotional: number | null | undefined): string | null {
  const min = Number(minNotional);
  const v = Number(valueTry);
  if (!Number.isFinite(min) || min <= 0 || !Number.isFinite(v)) return null;
  if (v >= min) return null;
  return `Tutar borsanın minimum emir tutarının (${min.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} ₺) altında; satış reddedilir.`;
}

/** Satış için order-status sembol adayları (önce TL çifti, sonra USDT). */
export function sellStatusSymbols(asset: string): string[] {
  const a = String(asset || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  return a ? [`${a}TRY`, `${a}USDT`] : [];
}
