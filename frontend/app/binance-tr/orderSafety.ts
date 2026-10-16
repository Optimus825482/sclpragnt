/**
 * Binance TR terminali / pozisyon grafiği için GERÇEK PARA emir güvenliği yardımcıları (saf, testli).
 *
 * 2026-10-16 (basit arayüz): sayfada ve grafik modalında dağınık duran yuvarlama, "durum belirsiz" ve
 * kısmi dolum mantığı tek yere toplandı. Buradaki hiçbir fonksiyon emir göndermez; yalnız hesap/metin üretir
 * (tek istisna `postJsonGuarded`: zaman aşımlı POST, ağ/zaman aşımı hatasında `UncertainOrderError` fırlatır).
 */
import { API_BASE, apiRequest } from "../lib/api";
import { validateSlTpPrices } from "../lib/tradeUi";

/** Emir isteği için üst süre. Backend kendi zaman aşımlarıyla bundan önce döner; bu yalnız asılı kalan bağlantıyı keser. */
export const ORDER_TIMEOUT_MS = 45_000;

export type OrderKind = "buy" | "sell" | "sltp";

/**
 * Miktarı AŞAĞI keser (asla yukarı yuvarlamaz). `toFixed` yarıya yuvarladığı için 0.1234567 → "0.123457" üretir ve
 * eldeki bakiyeden BÜYÜK miktar göndermeye yol açardı. `toPrecision(12)` 0.3*3 gibi kayan nokta kalıntılarını temizler.
 */
export function floorQty(value: number, decimals = 6): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  const f = 10 ** decimals;
  return Math.floor(Number((value * f).toPrecision(12))) / f;
}

/** `floorQty` sonucunu girdi alanı için üstel gösterimsiz, sondaki sıfırsız metne çevirir ("0.5", "12"). */
export function qtyToInput(value: number, decimals = 6): string {
  const q = floorQty(value, decimals);
  if (q <= 0) return "0";
  return q.toFixed(decimals).replace(/\.?0+$/, "");
}

/** Bakiyenin TAMAMI için girdi metni (Binance TR en çok 8 ondalık): üstel gösterim ("1e-7") üretmez; sunucu zaten step'e aşağı keser. */
export function exactQtyInput(value: number): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "0";
  return n.toFixed(8).replace(/\.?0+$/, "") || "0";
}

/** Fiyat basamak sayısı (sunucu tick'e zaten yuvarlar; burada amaç % hesabını 2 hanede bozmamak). */
export function priceDecimals(price: number | null | undefined): number {
  const p = Number(price);
  if (!Number.isFinite(p) || p <= 0) return 2;
  if (p >= 100) return 2;
  if (p >= 1) return 4;
  if (p >= 0.01) return 6;
  return 8;
}

/** Referans fiyata göre en yakın basamağa yuvarla (metin). */
export function roundPriceStr(value: number, ref: number | null | undefined): string {
  return value.toFixed(priceDecimals(ref));
}

/** Aşağı değil YUKARI yuvarla: break-even stop'u maliyetin altına düşmesin. */
export function ceilPriceStr(value: number, ref: number | null | undefined): string {
  const d = priceDecimals(ref);
  const f = 10 ** d;
  return (Math.ceil(Number((value * f).toPrecision(12))) / f).toFixed(d);
}

/** Emir türü etiketi (hata metinleri için). */
const KIND_LABEL: Record<OrderKind, string> = {
  buy: "Alım emri gönderilemedi",
  sell: "Satış emri gönderilemedi",
  sltp: "SL/TP emri kurulamadı",
};

/** "Durum belirsiz" uyarısı: emrin borsaya ulaşıp ulaşmadığı bilinmiyor. */
export function uncertainOrderText(kind: OrderKind, timedOut: boolean): string {
  const head = timedOut ? "Yanıt zaman aşımına uğradı" : "Bağlantı koptu";
  const check = "Bekleyen Emirler ve Günün İşlemleri sekmelerinden kontrol edin.";
  if (kind === "sltp") {
    return `${head}: SL/TP emrinin kurulup kurulmadığı BELİRSİZ (eski emirler iptal edilmiş olabilir). ${check} Pozisyon korumasız kalmış olabilir.`;
  }
  return `${head}: emrin borsaya ulaşıp ulaşmadığı BELİRSİZ. ${check} Aynı pencereden tekrar gönderirseniz aynı emir kimliği kullanıldığı için mükerrer emir oluşmaz.`;
}

/** HTTP hatası için kullanıcıya gösterilecek metin: backend nedeni yutulmaz; 5xx/zaman aşımında "belirsiz" notu eklenir. */
export function orderFailureText(kind: OrderKind, status: number, detail: unknown): string {
  const d = typeof detail === "string" ? detail.trim() : "";
  const ambiguous = status === 408 || status === 504 || (status >= 500 && !d);
  const base = d || `${KIND_LABEL[kind]} (HTTP ${status})`;
  if (ambiguous) {
    return `${base} — emrin durumu BELİRSİZ olabilir; Bekleyen Emirler ve Günün İşlemleri sekmelerinden kontrol edin.`;
  }
  return base;
}

/** Ağ kesintisi / zaman aşımı / okunamayan 2xx yanıtı: emir durumu bilinmiyor. */
export class UncertainOrderError extends Error {
  readonly timedOut: boolean;
  constructor(timedOut: boolean) {
    super(timedOut ? "Yanıt zaman aşımına uğradı" : "Bağlantı koptu");
    this.name = "UncertainOrderError";
    this.timedOut = timedOut;
  }
}

export type GuardedResponse<T> = { status: number; ok: boolean; body: T };

/**
 * JSON POST (zaman aşımlı). HTTP yanıtı geldiyse (4xx/5xx dahil) döner; yanıt hiç gelmediyse (ağ, zaman aşımı) ya da
 * 2xx yanıtın gövdesi okunamadıysa `UncertainOrderError` fırlatır — çağıran bunu "durum belirsiz" diye gösterip listeleri tazeler.
 */
export async function postJsonGuarded<T = Record<string, unknown>>(
  path: string,
  payload: unknown,
  timeoutMs: number = ORDER_TIMEOUT_MS,
): Promise<GuardedResponse<T>> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    let response: Response;
    try {
      response = await apiRequest(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
    } catch {
      throw new UncertainOrderError(ctrl.signal.aborted);
    }
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      if (response.ok) throw new UncertainOrderError(ctrl.signal.aborted);
      body = {};
    }
    return { status: response.status, ok: response.ok, body: (body ?? {}) as T };
  } finally {
    clearTimeout(timer);
  }
}

export type SellFillBody = {
  executed_qty?: unknown;
  avg_price?: unknown;
  cummulative_quote_qty?: unknown;
  partial?: unknown;
  remaining_qty?: unknown;
  dust_remaining?: unknown;
  [key: string]: unknown;
};

export type SellFill = {
  qty: number | null;
  price: number | null;
  total: number | null;
  partial: boolean;
  remaining: number | null;
  dust: boolean;
};

const pos = (v: unknown): number | null => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

/**
 * /api/binance/sell başarılı yanıtını özetler. GERÇEK dolum (executed_qty, avg_price) önceliklidir; yoksa istenen
 * miktar ve (son çare) ekrandaki fiyat kullanılır. `partial` ise kullanıcıya "TAMAMLANDI" denmemeli.
 */
export function describeSellFill(body: SellFillBody | null | undefined, requestedQty: number, fallbackPrice: number | null): SellFill {
  const b = body || {};
  const qty = pos(b.executed_qty) ?? pos(requestedQty);
  const quote = pos(b.cummulative_quote_qty);
  const price = pos(b.avg_price) ?? (quote && qty ? quote / qty : null) ?? pos(fallbackPrice);
  const total = quote ?? (qty && price ? qty * price : null);
  const remaining = pos(b.remaining_qty);
  return {
    qty,
    price,
    total,
    partial: b.partial === true,
    remaining,
    dust: b.dust_remaining === true,
  };
}

/** Hepsini iptal sonrası gerçek durum: hâlâ açık kalan emir sayısına bakılır (OCO'nun ikinci bacağı hata verse bile). */
export function summarizeCancelAll(
  attemptedIds: readonly number[],
  stillOpenIds: readonly number[] | null,
  okCount: number,
  failCount: number,
): { cancelled: number; remaining: number | null; level: "success" | "error"; text: string } {
  if (stillOpenIds) {
    const open = new Set(stillOpenIds);
    const remaining = attemptedIds.filter((id) => open.has(id)).length;
    const cancelled = attemptedIds.length - remaining;
    if (remaining === 0) {
      return { cancelled, remaining, level: "success", text: `${cancelled} emir iptal edildi.` };
    }
    return {
      cancelled,
      remaining,
      level: "error",
      text: `${remaining} emir hâlâ AKTİF (${cancelled} iptal edildi). Pozisyon korumasız olabilir; Bekleyen Emirler listesini kontrol edin.`,
    };
  }
  // Güncel liste alınamadı → yalnız istek sonuçlarına dayan, belirsizliği söyle.
  if (failCount === 0) return { cancelled: okCount, remaining: null, level: "success", text: `${okCount} emir iptal isteği başarılı; liste yenilenemedi, kontrol edin.` };
  return {
    cancelled: okCount,
    remaining: null,
    level: "error",
    text: `${okCount} emir iptal edildi, ${failCount} istek başarısız; liste yenilenemedi — emirler hâlâ aktif olabilir.`,
  };
}

/** Moda göre yalnız ilgili seviyeleri doğrular (SL_ONLY'de artık TP, TP_ONLY'de artık SL kontrol edilmez). Hata metni ya da null. */
export function checkSlTpInputs(
  mode: "OCO" | "SL_ONLY" | "TP_ONLY",
  tp: number | null | undefined,
  sl: number | null | undefined,
  last: number | null | undefined,
): string | null {
  const t = mode === "SL_ONLY" ? null : tp;
  const s = mode === "TP_ONLY" ? null : sl;
  return validateSlTpPrices(t, s, last);
}

/** Finans alanı girdisi: "12,5", "12.5" ve "1.234,56" kabul edilir; geçersiz → NaN. (Eski `parseFloat(x.replace(",", "."))` "1.234,56"yı 1.234 okuyordu.) */
export function parseMoneyInput(text: string | null | undefined): number {
  const s = String(text ?? "").trim().replace(/\s/g, "");
  if (!s) return NaN;
  const normalized = s.includes(",") ? s.replace(/\./g, "").replace(",", ".") : s;
  if (!/^\d*\.?\d+$|^\d+\.$/.test(normalized)) return NaN;
  return Number(normalized);
}
