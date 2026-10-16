/** Basit Binance TR / Risk Merkezi arayüzü için saf yardımcılar (node'da test edilir). */

export type Tone = "good" | "warn" | "bad" | "wait" | "mute";

const TR = "tr-TR";

export function fmtTry(value: number | null | undefined, digits = 2): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  return `₺${n.toLocaleString(TR, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Artı/eksi işaretli TL: +₺12,30 / −₺4,10 */
export function fmtSignedTry(value: number | null | undefined, digits = 2): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const body = fmtTry(Math.abs(n), digits);
  if (n > 0) return `+${body}`;
  if (n < 0) return `−${body}`;
  return body;
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const body = `%${Math.abs(n).toLocaleString(TR, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  return n < 0 ? `−${body}` : body;
}

/** Fiyat: küçük fiyatlarda daha çok basamak (0,00001234 gibi coinler için). */
export function fmtPrice(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n) || n <= 0) return "—";
  const digits = n >= 100 ? 2 : n >= 1 ? 3 : n >= 0.01 ? 4 : 8;
  return n.toLocaleString(TR, { minimumFractionDigits: 2, maximumFractionDigits: digits });
}

export function fmtQty(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(TR, { maximumFractionDigits: 8 });
}

/** "12,5" ve "12.5" yazımlarını kabul eder; geçersizse null. */
export function parseTrNumber(text: string | number | null | undefined): number | null {
  if (typeof text === "number") return Number.isFinite(text) ? text : null;
  const s = String(text ?? "").trim().replace(/\s/g, "");
  if (!s) return null;
  const normalized = s.includes(",") ? s.replace(/\./g, "").replace(",", ".") : s;
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
}

/** Sunucu `client_order_id` kuralı: 8–64 karakter, [A-Za-z0-9_-]. Her onay penceresi açılışında yeni üretilir. */
export function newClientOrderId(): string {
  const rnd =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  return `web-${rnd}`.slice(0, 64);
}

export function isValidClientOrderId(value: string): boolean {
  return /^[A-Za-z0-9_-]{8,64}$/.test(value);
}

/** Harcanacak tutar: serbest bakiyenin yüzdesi, Risk Merkezi sınırını aşamaz. Kuruşa aşağı yuvarlanır. */
export function amountFromPct(freeTry: number, pct: number, maxPct: number): number {
  const free = Number(freeTry);
  if (!Number.isFinite(free) || free <= 0) return 0;
  const p = Math.min(Math.max(Number(pct) || 0, 0), Number(maxPct) || 0);
  return Math.floor(free * (p / 100) * 100) / 100;
}

export function capAmount(freeTry: number, maxPct: number): number {
  return amountFromPct(freeTry, maxPct, maxPct);
}

export const RR_PRESETS: readonly number[] = [1.5, 2, 3];

export function rrLabel(rr: number): string {
  const n = Number(rr);
  if (!Number.isFinite(n)) return "—";
  return `1 : ${n.toLocaleString(TR, { maximumFractionDigits: 2 })}`;
}

export type PlanLike = {
  loss_try: number;
  gain_try: number;
  sl_price: number;
  tp_price: number;
  sl_pct?: number;
  rr?: number;
};

/** Plan kartı için düz Türkçe cümleler (jargon yok). */
export function scenarioTexts(plan: PlanLike): { bad: string; good: string } {
  return {
    bad: `Fiyat ${fmtPrice(plan.sl_price)} seviyesine inerse otomatik satılır; yaklaşık ${fmtSignedTry(plan.loss_try)} zarar.`,
    good: `Fiyat ${fmtPrice(plan.tp_price)} seviyesine çıkarsa otomatik satılır; yaklaşık ${fmtSignedTry(plan.gain_try)} kâr.`,
  };
}

export function suggestionSourceLabel(source: string | undefined): string {
  return source === "llm" ? "Yapay zekâ önerisi" : "Otomatik hesap";
}

export type OpenResult = { tone: Tone; title: string; detail: string; needsProtect: boolean; pending: boolean };

type OpenBody = {
  status?: string;
  executed_qty?: number;
  protection?: { status?: string; error?: string; reason?: string };
  idempotent_replay?: boolean;
};

/** open-position yanıtını (HTTP durumu + gövde) kullanıcıya anlatılacak sonuca çevirir. */
export function describeOpenResult(httpStatus: number, body: OpenBody | null | undefined): OpenResult {
  const b = body || {};
  if (httpStatus === 202 || b.status === "UNKNOWN") {
    return {
      tone: "warn",
      title: "Emrin sonucu henüz belli değil",
      detail: "Emri tekrar göndermeyin. Birazdan açık emirler ve işlem geçmişinden kontrol edin.",
      needsProtect: false,
      pending: true,
    };
  }
  const prot = b.protection?.status;
  if (prot === "placed") {
    return { tone: "good", title: "Pozisyon açıldı, koruma emri kuruldu", detail: "Zarar durdur ve kâr al emirleri Binance TR'de bekliyor.", needsProtect: false, pending: false };
  }
  if (prot === "failed") {
    return {
      tone: "bad",
      title: "Pozisyon açıldı ama koruma emri kurulamadı",
      detail: "Şu an zarar durdurma yok. Koruma emrini yeniden deneyin.",
      needsProtect: true,
      pending: false,
    };
  }
  if (prot === "skipped") {
    return {
      tone: "warn",
      title: "Pozisyon açıldı, koruma emri atlandı",
      detail: b.protection?.reason || "Gerçekleşen miktar belirlenemedi. Açık emirler ve bakiyeyi kontrol edin.",
      needsProtect: true,
      pending: false,
    };
  }
  return { tone: "mute", title: "İşlem tamamlandı", detail: "", needsProtect: false, pending: false };
}

/** Sunucu hata gövdesinden okunur mesaj. */
export function errorText(detail: unknown, fallback = "İşlem yapılamadı"): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}

/** "ada", "ADA/TRY", "ada_try" → "ADATRY". Boş/geçersizse "". */
export function normalizeSymbol(input: string | null | undefined): string {
  const s = String(input ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!s || s === "TRY") return "";
  return s.endsWith("TRY") ? s : `${s}TRY`;
}

/** Sunucu uyarı anahtarı yoksa genel mesaj; alım düğmesi uyarı varken kapalı kalır. */
export function hasBlockingWarnings(warnings: string[] | null | undefined): boolean {
  return Array.isArray(warnings) && warnings.length > 0;
}

export const AMOUNT_CHIPS: readonly number[] = [25, 50, 100];

/** Öneri listesi: en az 3 harfte başlar; önce öneki eşleşenler, sonra içerenler. Dönüş: coin adları (TRY'siz). */
export function suggestSymbols(all: readonly string[], query: string, limit = 8): string[] {
  const q = String(query ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/TRY$/, "");
  if (q.length < 3) return [];
  const assets = Array.from(new Set(all.filter((s) => !String(s).toUpperCase().endsWith("USDT")).map((s) => String(s).toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/TRY$/, "")).filter((s) => s && s !== "TRY")));
  const starts = assets.filter((a) => a.startsWith(q)).sort();
  const contains = assets.filter((a) => !a.startsWith(q) && a.includes(q)).sort();
  return [...starts, ...contains].slice(0, limit);
}

export type TradeLike = {
  symbol: string;
  price: string | number;
  qty: string | number;
  quoteQty: string | number;
  time: number;
  isBuyer: boolean;
  realized_pnl_try?: number | null;
};

export type SymbolGroup = {
  symbol: string;
  buyQty: number;
  buyQuote: number;
  buyAvg: number | null;
  sellQty: number;
  sellQuote: number;
  sellAvg: number | null;
  pnl: number | null;
  count: number;
  lastTime: number;
};

const num = (v: unknown) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** Aynı sembolün işlemlerini tek satırda toplar. Ortalama fiyat = toplam tutar / toplam adet (ağırlıklı ortalama). */
export function groupTradesBySymbol(trades: readonly TradeLike[]): SymbolGroup[] {
  const map = new Map<string, SymbolGroup>();
  for (const t of trades) {
    const key = String(t.symbol || "").replace("_", "/");
    if (!key) continue;
    const g = map.get(key) ?? { symbol: key, buyQty: 0, buyQuote: 0, buyAvg: null, sellQty: 0, sellQuote: 0, sellAvg: null, pnl: null, count: 0, lastTime: 0 };
    const qty = num(t.qty);
    const quote = num(t.quoteQty) || qty * num(t.price);
    if (t.isBuyer) { g.buyQty += qty; g.buyQuote += quote; }
    else { g.sellQty += qty; g.sellQuote += quote; }
    if (t.realized_pnl_try != null && Number.isFinite(Number(t.realized_pnl_try))) g.pnl = (g.pnl ?? 0) + Number(t.realized_pnl_try);
    g.count += 1;
    g.lastTime = Math.max(g.lastTime, num(t.time));
    map.set(key, g);
  }
  return Array.from(map.values())
    .map((g) => ({ ...g, buyAvg: g.buyQty > 0 ? g.buyQuote / g.buyQty : null, sellAvg: g.sellQty > 0 ? g.sellQuote / g.sellQty : null }))
    .sort((a, b) => b.lastTime - a.lastTime);
}

export const SMALL_BALANCE_TRY = 50;

/** Değeri eşiğin altındaki bakiyeleri ayıklar. Değeri bilinmeyenler (fiyat yok) gizlenmez. */
export function filterSmallBalances<T extends { value_try: number | null }>(items: readonly T[], hide: boolean, min = SMALL_BALANCE_TRY): T[] {
  if (!hide) return [...items];
  return items.filter((h) => h.value_try == null || !Number.isFinite(Number(h.value_try)) || Number(h.value_try) >= min);
}
