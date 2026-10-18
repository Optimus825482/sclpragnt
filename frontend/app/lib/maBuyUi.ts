/**
 * "MA BUY sinyal kaydı" (yalnız yönetici) sayfası için saf yardımcılar (node'da test edilir).
 *
 * Sözleşme: GET /api/admin/ma-buy-signals. Her sayısal alan null/eksik olabilir; `Number(null) === 0`
 * tuzağına düşmemek için tüm okumalar `num()` üzerinden geçer ("veri yok" 0 DEĞİLDİR).
 */
import { formatPrice } from "./format";

export type MaBuyStatus = "open" | "done" | "no_data";
export type MaBuyRule = "fast_cross_mid" | "mid_cross_slow";

export type MaBuySignal = {
  id: number;
  symbol: string;
  timeframe: string;
  rules: string[];
  barCloseMs: number | null;
  detectedAt: number | null; // epoch saniye
  signalPrice: number | null;
  emaFast: number | null;
  emaMid: number | null;
  emaSlow: number | null;
  status: MaBuyStatus;
  maxRise5: number | null;
  maxRise10: number | null;
  maxRise15: number | null;
  maxDrop15: number | null;
  close15: number | null;
  peakBarMinutes: number | null;
  evaluatedAt: number | null;
};

export type MaBuyThreshold = { minPct: number; n: number | null; share: number | null };
export type MaBuyRuleStat = {
  count: number | null;
  evaluated: number | null;
  avgMaxRise15: number | null;
  medianMaxRise15: number | null;
};
export type MaBuySummary = {
  count: number;
  evaluated: number;
  pending: number;
  avgMaxRise15: number | null;
  medianMaxRise15: number | null;
  avgMaxDrop15: number | null;
  avgClose15: number | null;
  grossFloorPct: number | null;
  thresholds: MaBuyThreshold[];
  byRule: Record<string, MaBuyRuleStat>;
};
export type MaBuyTracker = {
  enabled: boolean | null;
  timeframes: string[];
  scope: string | null;
  lastScanAt: number | null;
  lastScanSymbols: number | null;
  lastError: string | null;
};
export type MaBuyResponse = {
  days: number | null;
  total: number;
  items: MaBuySignal[];
  summary: MaBuySummary;
  tracker: MaBuyTracker;
};

/** Sinyalden sonra yükselişin ölçüldüğü pencere (dakika). */
export const MEASURE_MINUTES = 15;
/** Net %1,5 hedef + maliyet; backend `gross_floor_pct` göndermezse kullanılan yedek. */
export const DEFAULT_GROSS_FLOOR_PCT = 1.705;

export const DAY_OPTIONS = [1, 3, 7, 30] as const;
export const RULE_OPTIONS: { value: "" | MaBuyRule; label: string }[] = [
  { value: "", label: "Tüm kurallar" },
  { value: "fast_cross_mid", label: "Turuncu maviyi yukarı kesti" },
  { value: "mid_cross_slow", label: "Mavi morun üstüne çıktı" },
];
export const TIMEFRAME_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tüm zaman dilimleri" },
  { value: "1m", label: "M1" },
  { value: "5m", label: "M5" },
  { value: "15m", label: "M15" },
];

/** `5m` -> `M5`, `1m` -> `M1`, `15m` -> `M15`; tanınmayan değer olduğu gibi büyük harfle. */
export function timeframeLabel(tf: string | null | undefined): string {
  const m = /^(\d+)m$/i.exec(String(tf ?? "").trim());
  return m ? `M${m[1]}` : String(tf ?? "").toUpperCase() || "—";
}

export const STATUS_OPTIONS: { value: "" | MaBuyStatus; label: string }[] = [
  { value: "", label: "Tüm durumlar" },
  { value: "done", label: "Ölçüldü" },
  { value: "open", label: "Ölçülüyor" },
  { value: "no_data", label: "Veri yok" },
];

const RULE_LABELS: Record<string, string> = {
  fast_cross_mid: "Turuncu maviyi yukarı kesti",
  mid_cross_slow: "Mavi morun üstüne çıktı",
};

/** Kural kimliğini sade Türkçe etikete çevirir; tanınmazsa ham değer, boşsa "". */
export function ruleLabel(rule: string | null | undefined): string {
  const r = String(rule ?? "").trim();
  if (!r) return "";
  return RULE_LABELS[r] ?? r;
}

/** null/undefined/""/NaN/boolean -> null; aksi halde sonlu sayı. (`Number(null)` = 0 tuzağını önler.) */
export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "" || typeof v === "boolean") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const trNum = (v: number, digits: number) =>
  v.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Yüzde: `+1,30%` / `-0,60%` / `0,00%`; veri yoksa "—". `signed=false` ise artı işareti basılmaz. */
export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  const n = num(v);
  if (n === null) return "—";
  const body = trNum(Math.abs(n), digits);
  // "-0,00" gibi görünmesin
  const isZero = Number(Math.abs(n).toFixed(digits)) === 0;
  if (isZero) return `${body}%`;
  if (n < 0) return `-${body}%`;
  return `${signed ? "+" : ""}${body}%`;
}

/** Pay (0-1) -> `%40`; veri yoksa "—". */
export function fmtShare(v: number | null | undefined, digits = 0): string {
  const n = num(v);
  if (n === null) return "—";
  return `%${trNum(n * 100, digits)}`;
}

/** Eşik başlığı: 1.705 -> `%1,705`, 2 -> `%2`. */
export function fmtThreshold(minPct: number): string {
  return `%${minPct.toLocaleString("tr-TR", { maximumFractionDigits: 3 })}`;
}

export function fmtSignalPrice(v: number | null | undefined): string {
  return formatPrice(v ?? null);
}

/** Epoch saniye/ms -> Türkiye saatiyle `18.10 05:20` (gün.ay ss:dd). Geçersizse "—". */
export function fmtTrTime(ts: number | null | undefined): string {
  const n = num(ts);
  if (n === null || n <= 0) return "—";
  const ms = n < 10_000_000_000 ? n * 1000 : n;
  const parts = new Intl.DateTimeFormat("tr-TR", {
    timeZone: "Europe/Istanbul",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(ms));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")}.${get("month")} ${get("hour")}:${get("minute")}`;
}

/** Mum süresi (sn): "5m" -> 300, "15m" -> 900; bilinmiyorsa 5 dk. */
function timeframeSec(tf: string | null | undefined): number {
  const m = /^(\d+)m$/.exec(String(tf ?? ""));
  return m ? Number(m[1]) * 60 : 300;
}

/**
 * Sinyalin MUM zamanı (epoch saniye) = sinyal mumunun AÇILIŞI; grafikte o mumun üzerinde görünen saatle aynıdır.
 * (Eskiden `detected_at` — tarayıcının sinyali yakaladığı an — gösteriliyordu; mum zamanından geç olabilir.)
 * Mum bilinmiyorsa yakalanma anına düşer.
 */
export function signalTimeSec(
  item: Pick<MaBuySignal, "detectedAt" | "barCloseMs"> & { timeframe?: string },
): number | null {
  if (item.barCloseMs !== null && item.barCloseMs > 0) return item.barCloseMs / 1000 - timeframeSec(item.timeframe);
  if (item.detectedAt !== null && item.detectedAt > 0) return item.detectedAt;
  return null;
}

/** 15 dk içindeki en yüksek yükseliş brüt tabanı (%1,705) aştı mı? Veri yoksa false. */
export function hitsGrossFloor(item: Pick<MaBuySignal, "maxRise15">, floor: number | null | undefined): boolean {
  const f = num(floor);
  if (f === null) return false;
  const r = num(item.maxRise15);
  return r !== null && r >= f - 1e-9;
}

/** 725 -> `12 dk 05 sn`; 45 -> `45 sn`; 0 -> `birazdan`. */
export function countdownLabel(remainingSec: number): string {
  const s = Math.max(0, Math.round(remainingSec));
  if (s <= 0) return "birazdan";
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m === 0) return `${r} sn`;
  return `${m} dk ${String(r).padStart(2, "0")} sn`;
}

/**
 * 15 dakikalık ölçüme kalan saniye = 15 dk - (şimdi - mum kapanışı). 0'a kenetlenir.
 * Mum kapanışı bilinmiyorsa null.
 */
export function openCountdown(
  item: Pick<MaBuySignal, "barCloseMs">,
  nowSec: number,
): { remainingSec: number; label: string } | null {
  const close = num(item.barCloseMs);
  const now = num(nowSec);
  if (close === null || close <= 0 || now === null) return null;
  const elapsed = now - close / 1000;
  const remainingSec = Math.max(0, Math.round(MEASURE_MINUTES * 60 - elapsed));
  return { remainingSec, label: countdownLabel(remainingSec) };
}

export type StatusTone = "wait" | "good" | "mute";
/** Durum çipi: open -> "ölçülüyor · kalan ...", no_data -> "veri yok", done -> "ölçüldü". */
export function statusChip(
  item: Pick<MaBuySignal, "status" | "barCloseMs">,
  nowSec: number,
): { label: string; tone: StatusTone } {
  if (item.status === "open") {
    const c = openCountdown(item, nowSec);
    return { label: c ? `ölçülüyor · ${c.label}` : "ölçülüyor", tone: "wait" };
  }
  if (item.status === "no_data") return { label: "veri yok", tone: "mute" };
  return { label: "ölçüldü", tone: "good" };
}

export type SortKey = "time" | "rise15";
export type SortDir = "asc" | "desc";

/** Yeni dizi döner. Boş (null) yükselişler yön fark etmeksizin sona gider; eşitlikte yeni sinyal önde. */
export function sortSignals(items: readonly MaBuySignal[], key: SortKey, dir: SortDir): MaBuySignal[] {
  const sign = dir === "asc" ? 1 : -1;
  const t = (x: MaBuySignal) => signalTimeSec(x) ?? 0;
  return [...items].sort((a, b) => {
    if (key === "rise15") {
      const ra = a.maxRise15;
      const rb = b.maxRise15;
      if (ra === null && rb === null) return t(b) - t(a);
      if (ra === null) return 1;
      if (rb === null) return -1;
      if (ra !== rb) return (ra - rb) * sign;
      return t(b) - t(a);
    }
    const d = t(a) - t(b);
    if (d !== 0) return d * sign;
    return (a.id - b.id) * sign;
  });
}

/** İstemci tarafı sembol araması: büyük/küçük harf, `_` ve boşluk yok sayılır; boş arama hepsini döner. */
export function filterBySymbol(items: readonly MaBuySignal[], query: string): MaBuySignal[] {
  const q = String(query ?? "").replace(/[_\s]/g, "").toUpperCase();
  if (!q) return [...items];
  return items.filter((x) => x.symbol.includes(q));
}

/** Sunucu sorgu dizesi (sembol süzgeci istemci tarafındadır, gönderilmez). */
export function buildQuery(opts: { days: number; rule?: string; status?: string; timeframe?: string; limit?: number }): string {
  const p = new URLSearchParams();
  p.set("days", String(opts.days));
  if (opts.rule) p.set("rule", opts.rule);
  if (opts.status) p.set("status", opts.status);
  if (opts.timeframe) p.set("timeframe", opts.timeframe);
  p.set("limit", String(opts.limit ?? 500));
  return p.toString();
}

// ---------------------------------------------------------------- normalizer

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function normStatus(v: unknown): MaBuyStatus {
  return v === "open" || v === "done" || v === "no_data" ? v : "no_data";
}

export function normalizeSignal(raw: unknown, index = 0): MaBuySignal | null {
  if (!isObj(raw)) return null;
  const symbol = String(raw.symbol ?? "").replace(/_/g, "").toUpperCase();
  if (!symbol) return null;
  const rules = Array.isArray(raw.rules) ? raw.rules.map((r) => String(r)).filter(Boolean) : [];
  return {
    id: num(raw.id) ?? -(index + 1),
    symbol,
    timeframe: String(raw.timeframe ?? "5m") || "5m",
    rules,
    barCloseMs: num(raw.bar_close_ms),
    detectedAt: num(raw.detected_at),
    signalPrice: num(raw.signal_price),
    emaFast: num(raw.ema_fast),
    emaMid: num(raw.ema_mid),
    emaSlow: num(raw.ema_slow),
    status: normStatus(raw.status),
    maxRise5: num(raw.max_rise_5m_pct),
    maxRise10: num(raw.max_rise_10m_pct),
    maxRise15: num(raw.max_rise_15m_pct),
    maxDrop15: num(raw.max_drop_15m_pct),
    close15: num(raw.close_15m_pct),
    peakBarMinutes: num(raw.peak_bar_minutes),
    evaluatedAt: num(raw.evaluated_at),
  };
}

function normRuleStat(raw: unknown): MaBuyRuleStat {
  const r = isObj(raw) ? raw : {};
  return {
    count: num(r.count),
    evaluated: num(r.evaluated),
    avgMaxRise15: num(r.avg_max_rise_15m_pct),
    medianMaxRise15: num(r.median_max_rise_15m_pct),
  };
}

/** Yanıtı savunmacı biçimde normalleştirir: eksik anahtar/yanlış tip hata fırlatmaz. */
export function normalizeResponse(raw: unknown): MaBuyResponse {
  const r = isObj(raw) ? raw : {};
  const items: MaBuySignal[] = [];
  if (Array.isArray(r.items)) {
    r.items.forEach((x, i) => {
      const s = normalizeSignal(x, i);
      if (s) items.push(s);
    });
  }
  const s = isObj(r.summary) ? r.summary : {};
  const thresholds: MaBuyThreshold[] = [];
  if (Array.isArray(s.thresholds)) {
    for (const t of s.thresholds) {
      if (!isObj(t)) continue;
      const minPct = num(t.min_pct);
      if (minPct === null) continue;
      thresholds.push({ minPct, n: num(t.n), share: num(t.share) });
    }
  }
  const byRule: Record<string, MaBuyRuleStat> = {};
  if (isObj(s.by_rule)) {
    for (const [k, v] of Object.entries(s.by_rule)) byRule[k] = normRuleStat(v);
  }
  const t = isObj(r.tracker) ? r.tracker : {};
  const evaluated = num(s.evaluated) ?? items.filter((x) => x.status === "done").length;
  const pending = num(s.pending) ?? items.filter((x) => x.status === "open").length;
  return {
    days: num(r.days),
    total: num(r.total) ?? items.length,
    items,
    summary: {
      count: num(s.count) ?? items.length,
      evaluated,
      pending,
      avgMaxRise15: num(s.avg_max_rise_15m_pct),
      medianMaxRise15: num(s.median_max_rise_15m_pct),
      avgMaxDrop15: num(s.avg_max_drop_15m_pct),
      avgClose15: num(s.avg_close_15m_pct),
      grossFloorPct: num(s.gross_floor_pct),
      thresholds,
      byRule,
    },
    tracker: {
      enabled: typeof t.enabled === "boolean" ? t.enabled : null,
      timeframes: Array.isArray(t.timeframes) ? t.timeframes.map((x) => String(x)) : [],
      scope: typeof t.scope === "string" ? t.scope : null,
      lastScanAt: num(t.last_scan_at),
      lastScanSymbols: num(t.last_scan_symbols),
      lastError: typeof t.last_error === "string" && t.last_error.trim() ? t.last_error : null,
    },
  };
}

/** Tarama izleme satırı: "Son tarama: 18.10 05:20 · 7 sembol · hata: ...". */
export function trackerLine(t: MaBuyTracker): string {
  const parts: string[] = [];
  parts.push(`Son tarama: ${t.lastScanAt !== null ? fmtTrTime(t.lastScanAt) : "henüz yok"}`);
  if (t.lastScanSymbols !== null) parts.push(`${t.lastScanSymbols} sembol`);
  if (t.enabled === false) parts.push("izleme kapalı");
  if (t.lastError) parts.push(`hata: ${t.lastError}`);
  return parts.join(" · ");
}

/** HTTP durum koduna göre kullanıcıya gösterilecek hata metni. */
export function errorMessage(status: number | null, detail?: string | null): string {
  if (status === 403) return "Bu sayfa yalnızca yönetici içindir.";
  if (status === 401) return "Oturum bulunamadı veya süresi doldu. Lütfen yeniden giriş yapın.";
  return detail && detail.trim() ? detail : "MA BUY sinyalleri alınamadı";
}

// ---------------------------------------------------------------- Ayarlar > MA BUY (push + otonom paper)
/** Bildirim/paper zaman dilimleri (backend `ma_buy_notify._TFS` ile aynı sıra). */
export const MA_BUY_NOTIFY_TFS = ["1m", "5m", "15m"] as const;

/** "1m,5m" → seçili TF kümesi. */
export function parseTfList(raw: string | null | undefined): Set<string> {
  return new Set(String(raw ?? "").split(",").map((t) => t.trim()).filter((t) => (MA_BUY_NOTIFY_TFS as readonly string[]).includes(t)));
}

/** Seçili TF kümesi → "1m,5m" (sabit sıra). */
export function formatTfList(selected: Set<string>): string {
  return MA_BUY_NOTIFY_TFS.filter((t) => selected.has(t)).join(",");
}

/** "1m:1,5m:1.5" → { "1m": 1, "5m": 1.5 } (bozuk parça atlanır). */
export function parseTargetPct(raw: string | null | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of String(raw ?? "").split(",")) {
    const [tf, val] = part.split(":").map((s) => s.trim());
    const n = Number(val);
    if (tf && (MA_BUY_NOTIFY_TFS as readonly string[]).includes(tf) && Number.isFinite(n) && n > 0) out[tf] = n;
  }
  return out;
}

/** { "1m": 1, "5m": 1.5 } → "1m:1,5m:1.5" (boş/geçersiz değerler yazılmaz; backend 0–20 aralığını doğrular). */
export function formatTargetPct(map: Record<string, number | null | undefined>): string {
  return MA_BUY_NOTIFY_TFS.filter((t) => {
    const v = map[t];
    return typeof v === "number" && Number.isFinite(v) && v > 0;
  }).map((t) => `${t}:${map[t]}`).join(",");
}
