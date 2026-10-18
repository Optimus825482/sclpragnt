/**
 * "Radar tarama logları" (yalnız yönetici) penceresi için saf yardımcılar (node'da test edilir).
 *
 * Sözleşme: GET /api/admin/radar-scan-log?limit=10&symbol=&status=
 * Her sayısal alan null/eksik olabilir; `Number(null) === 0` tuzağına düşmemek için tüm okumalar `num()` üzerinden
 * geçer ("veri yok" 0 DEĞİLDİR). Bilinmeyen durum/ton/neden kodu hata fırlatmaz: nötr rozetle ham metin gösterilir.
 */
import { formatPrice } from "./format";
import { fmtTrTime, num } from "./maBuyUi";

export { fmtTrTime, num };

// ------------------------------------------------------------------ tipler

export type RadarLogTone = "success" | "info" | "warn" | "muted" | "caution" | "danger" | "neutral";

export type RadarLogHorizon = {
  horizon: number;
  passes: boolean | null;
  reason: string | null;
  reasonCode: string | null;
};

export type RadarLogRow = {
  symbol: string;
  status: string;
  tone: RadarLogTone;
  label: string;
  reason: string | null;
  reasonCode: string | null;
  panelScore: number | null;
  horizon: number | null;
  price: number | null;
  atrPct: number | null;
  rsi: number | null;
  mfi: number | null;
  ret3Pct: number | null;
  volumeRatio: number | null;
  mode: string | null;
  targetPct: number | null;
  notified: boolean;
  horizons: RadarLogHorizon[];
};

export type RadarLogCatalogItem = { status: string; label: string; tone: RadarLogTone };

export type RadarLogScan = {
  /** Backend `scan_no`; yoksa negatif sıra numarası (benzersiz kalır). */
  scanNo: number;
  scanAt: number | null; // epoch saniye
  riskOff: boolean;
  riskOffUnknown: boolean;
  minPanelScore: number | null;
  pool: { horizon: number; count: number }[];
  counts: Record<string, number>;
  rows: RadarLogRow[];
};

export type RadarLogResponse = {
  ok: boolean;
  keep: number | null;
  totalScans: number;
  statusCatalog: RadarLogCatalogItem[];
  scans: RadarLogScan[];
};

// ------------------------------------------------------------------ durum / ton

export const TONES: readonly RadarLogTone[] = ["success", "info", "warn", "muted", "caution", "danger", "neutral"];

/** Backend `status_catalog` göndermezse (ya da bilinmeyen durum gelirse) kullanılan yerleşik eşleme. */
export const DEFAULT_STATUS_CATALOG: readonly RadarLogCatalogItem[] = [
  { status: "notified", label: "Bildirildi", tone: "success" },
  { status: "detected", label: "Tespit edildi", tone: "info" },
  { status: "gated", label: "Kapıya takıldı", tone: "warn" },
  { status: "below_threshold", label: "Eşik altı", tone: "muted" },
  { status: "open_position", label: "Açık pozisyon", tone: "muted" },
  { status: "watch", label: "İzlemede", tone: "caution" },
  { status: "rejected", label: "Elendi", tone: "danger" },
  { status: "no_data", label: "Veri yok", tone: "neutral" },
];

const DEFAULT_STATUS_MAP: Record<string, RadarLogCatalogItem> = Object.fromEntries(
  DEFAULT_STATUS_CATALOG.map((c) => [c.status, c]),
);

/** Sıralamada öne alınan durumlar (bildirildi > tespit > kapıya takıldı). */
const STATUS_PRIORITY: Record<string, number> = { notified: 0, detected: 1, gated: 2 };

export function isTone(v: unknown): v is RadarLogTone {
  return typeof v === "string" && (TONES as readonly string[]).includes(v);
}

/** Ton -> mevcut `ui-badge-*` sınıfı (açık/koyu tema uyumlu). Bilinmeyen ton nötr. */
export function toneBadgeClass(tone: string | null | undefined): string {
  switch (tone) {
    case "success": return "ui-badge-positive";
    case "info": return "ui-badge-info";
    case "warn": return "ui-badge-orange";
    case "muted": return "ui-badge-muted";
    case "caution": return "ui-badge-warning";
    case "danger": return "ui-badge-negative";
    default: return "ui-badge-neutral";
  }
}

/** Durum -> {label, tone}; önce verilen katalog, sonra yerleşik eşleme, en son ham değer + nötr. */
export function statusMeta(
  status: string | null | undefined,
  catalog: readonly RadarLogCatalogItem[] = [],
): { label: string; tone: RadarLogTone } {
  const key = String(status ?? "").trim();
  const hit = catalog.find((c) => c.status === key) ?? DEFAULT_STATUS_MAP[key];
  if (hit) return { label: hit.label, tone: hit.tone };
  return { label: key || "Bilinmiyor", tone: "neutral" };
}

// ------------------------------------------------------------------ neden kodları

export type ReasonMeta = { label: string; tone: RadarLogTone; known: boolean };

const REASONS: Record<string, { label: string; tone: RadarLogTone }> = {
  atr_yetersiz: { label: "ATR yetersiz", tone: "warn" },
  bb_genisligi_yetersiz: { label: "BB genişliği yetersiz", tone: "warn" },
  bb_verisi_yok: { label: "BB verisi yok", tone: "neutral" },
  yapisal_teyit_yok: { label: "Yapısal teyit yok", tone: "caution" },
  ust_fitil_tuzagi: { label: "Üst fitil tuzağı", tone: "danger" },
  mfi_asiri_alim: { label: "MFI aşırı alım (tükenme)", tone: "danger" },
  rsi_asiri_alim: { label: "RSI aşırı alım (tükenme)", tone: "danger" },
  mfi_asiri_satim: { label: "MFI aşırı satım", tone: "danger" },
  asiri_spread: { label: "Spread yüksek", tone: "danger" },
  skor_esigi: { label: "Skor eşiği altı", tone: "muted" },
  master_surge_katman1: { label: "Master Surge katman-1", tone: "info" },
  skor_tabani: { label: "Skor tabanı altı", tone: "warn" },
  aile_devre_disi: { label: "Aile devre dışı", tone: "muted" },
  radar_kapisi_gecilmedi: { label: "Radar kapısı geçilmedi", tone: "warn" },
  diger: { label: "Diğer", tone: "neutral" },
};

/** Neden kodu -> Türkçe etiket + ton. Bilinmeyen kod: ham kod, nötr ton, `known=false`. Boşsa null. */
export function reasonMeta(code: string | null | undefined): ReasonMeta | null {
  const c = String(code ?? "").trim();
  if (!c) return null;
  const hit = REASONS[c];
  return hit ? { ...hit, known: true } : { label: c, tone: "neutral", known: false };
}

/**
 * Kod gelmediyse ham metnin başındaki `kod` ya da `kod:ayrıntı` ön ekinden kod türetir
 * (örn. "atr_yetersiz:0.20%<0.25%" -> "atr_yetersiz"). İnsan okunur cümle ("skor tabanı altı (...)") kod sayılmaz.
 */
export function deriveReasonCode(code: unknown, reason: unknown): string | null {
  const c = typeof code === "string" ? code.trim() : "";
  if (c) return c;
  const r = typeof reason === "string" ? reason.trim() : "";
  const m = /^([a-z][a-z0-9_]*)(?::|$)/.exec(r);
  return m ? m[1] : null;
}

// ------------------------------------------------------------------ normalizer

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t ? t : null;
};

function normHorizons(raw: unknown): RadarLogHorizon[] {
  if (!isObj(raw)) return [];
  const out: RadarLogHorizon[] = [];
  for (const [k, v] of Object.entries(raw)) {
    const horizon = num(k);
    if (horizon === null) continue;
    const o = isObj(v) ? v : {};
    out.push({
      horizon,
      passes: typeof o.passes === "boolean" ? o.passes : null,
      reason: str(o.reason),
      reasonCode: deriveReasonCode(o.reason_code, o.reason),
    });
  }
  return out.sort((a, b) => a.horizon - b.horizon);
}

function normCatalog(raw: unknown): RadarLogCatalogItem[] {
  if (!Array.isArray(raw)) return [];
  const out: RadarLogCatalogItem[] = [];
  for (const x of raw) {
    if (!isObj(x)) continue;
    const status = str(x.status);
    if (!status) continue;
    const def = DEFAULT_STATUS_MAP[status];
    out.push({
      status,
      label: str(x.label) ?? def?.label ?? status,
      tone: isTone(x.tone) ? x.tone : def?.tone ?? "neutral",
    });
  }
  return out;
}

export function normalizeRow(raw: unknown, catalog: readonly RadarLogCatalogItem[] = []): RadarLogRow | null {
  if (!isObj(raw)) return null;
  const symbol = String(raw.symbol ?? "").replace(/_/g, "").toUpperCase().trim();
  if (!symbol) return null;
  const status = str(raw.status) ?? "unknown";
  const meta = statusMeta(status, catalog);
  const reason = str(raw.reason);
  return {
    symbol,
    status,
    tone: isTone(raw.tone) ? raw.tone : meta.tone,
    label: str(raw.label) ?? meta.label,
    reason,
    reasonCode: deriveReasonCode(raw.reason_code, raw.reason),
    panelScore: num(raw.panel_score),
    horizon: num(raw.horizon),
    price: num(raw.price),
    atrPct: num(raw.atr_pct),
    rsi: num(raw.rsi),
    mfi: num(raw.mfi),
    ret3Pct: num(raw.ret3_pct),
    volumeRatio: num(raw.volume_ratio),
    mode: str(raw.mode),
    targetPct: num(raw.target_pct),
    notified: raw.notified === true || status === "notified",
    horizons: normHorizons(raw.horizons),
  };
}

function normPool(raw: unknown): { horizon: number; count: number }[] {
  if (!isObj(raw)) return [];
  const out: { horizon: number; count: number }[] = [];
  for (const [k, v] of Object.entries(raw)) {
    const horizon = num(k);
    const count = num(v);
    if (horizon !== null && count !== null) out.push({ horizon, count });
  }
  return out.sort((a, b) => a.horizon - b.horizon);
}

function countRows(rows: readonly RadarLogRow[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) out[r.status] = (out[r.status] ?? 0) + 1;
  return out;
}

export function normalizeScan(raw: unknown, index = 0, catalog: readonly RadarLogCatalogItem[] = []): RadarLogScan | null {
  if (!isObj(raw)) return null;
  const rows: RadarLogRow[] = [];
  if (Array.isArray(raw.rows)) {
    for (const x of raw.rows) {
      const row = normalizeRow(x, catalog);
      if (row) rows.push(row);
    }
  }
  let counts: Record<string, number> = {};
  if (isObj(raw.counts)) {
    for (const [k, v] of Object.entries(raw.counts)) {
      const n = num(v);
      if (n !== null && n >= 0) counts[k] = n;
    }
  } else {
    counts = countRows(rows);
  }
  return {
    scanNo: num(raw.scan_no) ?? -(index + 1),
    scanAt: num(raw.scan_at),
    riskOff: raw.risk_off === true,
    riskOffUnknown: raw.risk_off_unknown === true,
    minPanelScore: num(raw.min_panel_score),
    pool: normPool(raw.pool),
    counts,
    rows,
  };
}

/** Yanıtı savunmacı biçimde normalleştirir: eksik anahtar/yanlış tip hata fırlatmaz. Taramalar en yeni önce sıralanır. */
export function normalizeResponse(raw: unknown): RadarLogResponse {
  const r = isObj(raw) ? raw : {};
  const statusCatalog = normCatalog(r.status_catalog);
  const scans: RadarLogScan[] = [];
  if (Array.isArray(r.scans)) {
    r.scans.forEach((x, i) => {
      const s = normalizeScan(x, i, statusCatalog);
      if (s) scans.push(s);
    });
  }
  scans.sort((a, b) => {
    const ta = a.scanAt ?? -Infinity;
    const tb = b.scanAt ?? -Infinity;
    if (ta !== tb) return tb > ta ? 1 : -1;
    return b.scanNo - a.scanNo;
  });
  return {
    ok: r.ok !== false,
    keep: num(r.keep),
    totalScans: num(r.total_scans) ?? scans.length,
    statusCatalog,
    scans,
  };
}

// ------------------------------------------------------------------ sorgu / hata

export function buildQuery(opts: { limit?: number; symbol?: string; status?: string } = {}): string {
  const p = new URLSearchParams();
  p.set("limit", String(opts.limit ?? 10));
  if (opts.symbol) p.set("symbol", opts.symbol);
  if (opts.status) p.set("status", opts.status);
  return p.toString();
}

/** HTTP durum koduna göre kullanıcıya gösterilecek hata metni. */
export function errorMessage(status: number | null, detail?: string | null): string {
  if (status === 403) return "Bu pencere yalnızca yönetici içindir.";
  if (status === 401) return "Bu pencere yalnızca yönetici içindir. Oturum bulunamadı veya süresi doldu; yeniden giriş yapın.";
  return detail && detail.trim() ? detail : "Radar tarama logları alınamadı";
}

// ------------------------------------------------------------------ süzme / sıralama

/** İstemci tarafı sembol araması: büyük/küçük harf, `_` ve boşluk yok sayılır; boş arama hepsini döner. */
export function symbolMatches(symbol: string, query: string): boolean {
  const q = String(query ?? "").replace(/[_\s]/g, "").toUpperCase();
  return !q || symbol.includes(q);
}

/** Durum (boş = hepsi) ve sembol aramasına göre süzer; yeni dizi döner. */
export function filterRows(
  rows: readonly RadarLogRow[],
  opts: { status?: string | null; query?: string | null } = {},
): RadarLogRow[] {
  const status = String(opts.status ?? "").trim();
  const query = String(opts.query ?? "");
  return rows.filter((r) => (!status || r.status === status) && symbolMatches(r.symbol, query));
}

/**
 * Önce bildirildi/tespit/kapıya takıldı, sonra skora göre azalan (skoru olmayan sona), eşitlikte sembol A-Z.
 * Yeni dizi döner.
 */
export function sortRows(rows: readonly RadarLogRow[]): RadarLogRow[] {
  const pr = (r: RadarLogRow) => STATUS_PRIORITY[r.status] ?? 3;
  return [...rows].sort((a, b) => {
    const d = pr(a) - pr(b);
    if (d !== 0) return d;
    if (a.panelScore !== b.panelScore) {
      if (a.panelScore === null) return 1;
      if (b.panelScore === null) return -1;
      return b.panelScore - a.panelScore;
    }
    return a.symbol < b.symbol ? -1 : a.symbol > b.symbol ? 1 : 0;
  });
}

/** Performans için en çok `max` satırı döner; kalan sayısı `hidden`. */
export const MAX_RENDER_ROWS = 150;
export function limitRows<T>(rows: readonly T[], max = MAX_RENDER_ROWS): { shown: T[]; hidden: number } {
  const cap = Math.max(0, Math.floor(max));
  if (rows.length <= cap) return { shown: [...rows], hidden: 0 };
  return { shown: rows.slice(0, cap), hidden: rows.length - cap };
}

// ------------------------------------------------------------------ sayaç özeti / tarama gezinme

export type StatusSummaryItem = { status: string; label: string; tone: RadarLogTone; count: number };

/**
 * Durum başına sayaç özeti (yalnız sayısı > 0 olanlar): önce katalog sırası, sonra yerleşik sıra, en sonda
 * bilinmeyen durumlar. `counts` yoksa satırlardan sayılır.
 */
export function statusSummary(scan: RadarLogScan | null | undefined, catalog: readonly RadarLogCatalogItem[] = []): StatusSummaryItem[] {
  if (!scan) return [];
  const counts = Object.keys(scan.counts).length > 0 ? scan.counts : countRows(scan.rows);
  const order: string[] = [];
  for (const c of catalog) if (!order.includes(c.status)) order.push(c.status);
  for (const c of DEFAULT_STATUS_CATALOG) if (!order.includes(c.status)) order.push(c.status);
  for (const k of Object.keys(counts)) if (!order.includes(k)) order.push(k);
  const out: StatusSummaryItem[] = [];
  for (const status of order) {
    const count = counts[status] ?? 0;
    if (count <= 0) continue;
    out.push({ status, count, ...statusMeta(status, catalog) });
  }
  return out;
}

/** Seçili tarama no'suna göre dizindeki yeri; bulunamazsa (ya da seçim yoksa) en yeni (0). Liste boşsa -1. */
export function selectedIndex(scans: readonly RadarLogScan[], selectedNo: number | null): number {
  if (scans.length === 0) return -1;
  if (selectedNo === null) return 0;
  const i = scans.findIndex((s) => s.scanNo === selectedNo);
  return i >= 0 ? i : 0;
}

/** `dir=+1` daha eski, `-1` daha yeni; sınırlarda kenetlenir. */
export function stepIndex(index: number, dir: 1 | -1, length: number): number {
  if (length <= 0) return -1;
  return Math.min(length - 1, Math.max(0, index + dir));
}

// ------------------------------------------------------------------ biçimleyiciler

const trNum = (v: number, digits: number) =>
  v.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Düz sayı (tr-TR); veri yoksa "—". */
export function fmtNum(v: number | null | undefined, digits = 1): string {
  const n = num(v);
  return n === null ? "—" : trNum(n, digits);
}

/** Panel skoru: tek ondalık; veri yoksa "—". */
export function fmtScore(v: number | null | undefined): string {
  return fmtNum(v, 1);
}

/** Yüzde puanı değeri (0.41 -> `0,41%`); `signed` ise artı/eksi işaret basılır. Veri yoksa "—". */
export function fmtPctValue(v: number | null | undefined, digits = 2, signed = false): string {
  const n = num(v);
  if (n === null) return "—";
  const body = trNum(Math.abs(n), digits);
  if (Number(Math.abs(n).toFixed(digits)) === 0) return `${body}%`;
  if (n < 0) return `-${body}%`;
  return `${signed ? "+" : ""}${body}%`;
}

/** Hacim oranı: 1.8 -> `1,8×`. */
export function fmtRatio(v: number | null | undefined): string {
  const n = num(v);
  return n === null ? "—" : `${trNum(n, 1)}×`;
}

/** Ufuk (dakika): 5 -> `5 dk`. */
export function fmtHorizon(v: number | null | undefined): string {
  const n = num(v);
  return n === null ? "—" : `${trNum(n, 0)} dk`;
}

export function fmtPrice(v: number | null | undefined): string {
  return formatPrice(v ?? null);
}

/** RSI/MFI tek hücrede: `58 / 61`; ikisi de yoksa "—". */
export function fmtRsiMfi(rsi: number | null | undefined, mfi: number | null | undefined): string {
  const a = num(rsi);
  const b = num(mfi);
  if (a === null && b === null) return "—";
  return `${a === null ? "—" : trNum(a, 0)} / ${b === null ? "—" : trNum(b, 0)}`;
}

/** Havuz özeti: `5 dk · 105 sembol, 15 dk · 105 sembol`; yoksa "—". */
export function poolLine(pool: readonly { horizon: number; count: number }[]): string {
  if (pool.length === 0) return "—";
  return pool.map((p) => `${fmtHorizon(p.horizon)} · ${p.count.toLocaleString("tr-TR")} sembol`).join(", ");
}

/** Tarama seçici etiketi: `#1234 · 18.10 05:20` (Türkiye saati). */
export function scanLabel(scan: Pick<RadarLogScan, "scanNo" | "scanAt">): string {
  const no = scan.scanNo > 0 ? `#${scan.scanNo}` : "tarama";
  return `${no} · ${fmtTrTime(scan.scanAt)}`;
}

/** Eşik etiketi: `Panel eşiği 71,5`; yoksa "Panel eşiği —". */
export function thresholdLabel(v: number | null | undefined): string {
  return `Panel eşiği ${fmtScore(v)}`;
}

export type RiskBadge = { label: string; tone: RadarLogTone };
/** Risk-off rozeti: açık -> danger, bilinmiyor -> caution, değilse success. */
export function riskBadge(scan: Pick<RadarLogScan, "riskOff" | "riskOffUnknown">): RiskBadge {
  if (scan.riskOffUnknown) return { label: "Risk-off: bilinmiyor", tone: "caution" };
  if (scan.riskOff) return { label: "Risk-off: AÇIK", tone: "danger" };
  return { label: "Risk-off: yok", tone: "success" };
}
