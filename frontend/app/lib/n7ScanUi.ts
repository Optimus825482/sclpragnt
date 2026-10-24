/**
 * "N7 TARAMA" sekmesi (Radar sayfası) için saf yardımcılar — node'da test edilir.
 *
 * Sözleşme:
 *   POST /api/radar/n7-scan/run  {top:3} → {status:"running", started_at, top} | 409 "Tarama zaten çalışıyor"
 *   GET  /api/radar/n7-scan            → N7ScanState (aşağıda)
 *
 * Her sayısal alan null/eksik olabilir; `Number(null) === 0` tuzağına düşmemek için okumalar `num()`
 * üzerinden geçer ("veri yok" 0 DEĞİLDİR, "—" basılır).
 */
import { num } from "./maBuyUi";

export { num };

// ------------------------------------------------------------------ tipler

export type N7ScanStatus = "idle" | "running" | "done" | "error";

export type N7Pick = {
  sym: string;
  px: number | null;
  score: number | null;
  r1: number | null;
  r2: number | null;
  r4: number | null;
  r24: number | null;
  vr: number | null;
  vwap_rel: number | null;
  room: number | null;
  base: number | null;
  hl: number | null;
  atr15: number | null;
  qv24: number | null;
};

export type N7Result = {
  cutoff_ms: number | null;
  universe: number | null;
  candidates: number | null;
  scanned: number | null;
  elapsed_s: number | null;
  source: string | null;
  rule: string | null;
  picked: N7Pick[];
};

export type N7ScanState = {
  status: N7ScanStatus;
  started_at: number | null;
  finished_at: number | null;
  progress: { done: number; total: number };
  error: string | null;
  top: number;
  result: N7Result | null;
};

export const N7_DEFAULT_TOP = 3;
export const N7_POLL_MS = 3000;

// ------------------------------------------------------------------ normalize

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

const STATUSES: readonly N7ScanStatus[] = ["idle", "running", "done", "error"];

export function normalizeStatus(v: unknown): N7ScanStatus {
  return typeof v === "string" && (STATUSES as readonly string[]).includes(v) ? (v as N7ScanStatus) : "idle";
}

export function normalizePick(raw: unknown): N7Pick | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const sym = str(r.sym);
  if (!sym) return null;
  return {
    sym: sym.toUpperCase(),
    px: num(r.px),
    score: num(r.score),
    r1: num(r.r1),
    r2: num(r.r2),
    r4: num(r.r4),
    r24: num(r.r24),
    vr: num(r.vr),
    vwap_rel: num(r.vwap_rel),
    room: num(r.room),
    base: num(r.base),
    hl: num(r.hl),
    atr15: num(r.atr15),
    qv24: num(r.qv24),
  };
}

export function normalizeResult(raw: unknown): N7Result | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const picked = Array.isArray(r.picked)
    ? r.picked.map(normalizePick).filter((p): p is N7Pick => p !== null)
    : [];
  return {
    cutoff_ms: num(r.cutoff_ms),
    universe: num(r.universe),
    candidates: num(r.candidates),
    scanned: num(r.scanned),
    elapsed_s: num(r.elapsed_s),
    source: str(r.source),
    rule: str(r.rule),
    picked,
  };
}

export function normalizeState(raw: unknown): N7ScanState {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const prog = (r.progress && typeof r.progress === "object" ? r.progress : {}) as Record<string, unknown>;
  return {
    status: normalizeStatus(r.status),
    started_at: num(r.started_at),
    finished_at: num(r.finished_at),
    progress: { done: num(prog.done) ?? 0, total: num(prog.total) ?? 0 },
    error: str(r.error),
    top: num(r.top) ?? N7_DEFAULT_TOP,
    result: normalizeResult(r.result),
  };
}

// ------------------------------------------------------------------ seçim

/** En iyi N: skora göre azalan (skoru olmayanlar sona), `picked` zaten sıralı gelse de güvence. */
export function topPicks(result: N7Result | null, n = N7_DEFAULT_TOP): N7Pick[] {
  if (!result) return [];
  return [...result.picked]
    .sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity))
    .slice(0, Math.max(0, n));
}

// ------------------------------------------------------------------ biçim

/** "ABCTRY" → "ABC" (yalnız son ek). */
export function stripTry(sym: string): string {
  return sym.endsWith("TRY") && sym.length > 3 ? sym.slice(0, -3) : sym;
}

const trFixed = (v: number, digits: number) =>
  v.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** İşaretli yüzde: `+2,4%` / `-0,8%` / `—`. Girdi yüzde birimindedir. */
export function fmtSignedPct(v: number | null | undefined, digits = 1): string {
  const n = num(v);
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${trFixed(n, digits)}%`;
}

/** İşaretsiz yüzde: `3,2%` / `—`. */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  const n = num(v);
  return n === null ? "—" : `${trFixed(n, digits)}%`;
}

/** Hacim oranı: `4,0×` / `—`. */
export function fmtRatioX(v: number | null | undefined, digits = 1): string {
  const n = num(v);
  return n === null ? "—" : `${trFixed(n, digits)}×`;
}

/** Skor: 1 ondalık, `—`. */
export function fmtScore(v: number | null | undefined): string {
  const n = num(v);
  return n === null ? "—" : trFixed(n, 1);
}

/** Yüzde tonu: pozitif yeşil, negatif kırmızı, 0/yok nötr (sayfanın mevcut renk dili). */
export function pctTone(v: number | null | undefined): string {
  const n = num(v);
  if (n === null || n === 0) return "text-bunker-muted";
  return n > 0 ? "text-neon-green" : "text-neon-red";
}

/** Geçen süre (sn) — çalışırken `started_at`'tan şimdiye. */
export function elapsedSeconds(state: N7ScanState, nowMs: number): number | null {
  const start = num(state.started_at);
  if (start === null || start <= 0) return null;
  const startMs = start < 10_000_000_000 ? start * 1000 : start;
  const end = state.status === "running" ? nowMs : (num(state.finished_at) ?? nowMs);
  const endMs = end < 10_000_000_000 ? end * 1000 : end;
  return Math.max(0, Math.round((endMs - startMs) / 1000));
}

/** Durum satırı metni + tonu. Ekranda tek yerde basılır. */
export function statusLine(
  state: N7ScanState,
  nowMs: number,
): { text: string; tone: "muted" | "running" | "ok" | "error" } {
  if (state.status === "running") {
    const { done, total } = state.progress;
    const el = elapsedSeconds(state, nowMs);
    const prog = total > 0 ? `${done} / ${total} sembol` : "başlatılıyor…";
    return { text: `TARANIYOR · ${prog}${el !== null ? ` · ${el} sn` : ""}`, tone: "running" };
  }
  if (state.status === "error") {
    return { text: `HATA · ${state.error ?? "bilinmeyen hata"}`, tone: "error" };
  }
  if (state.status === "done" && state.result) {
    const n = state.result.picked.length;
    return { text: `TAMAMLANDI · ${n} sembol seçildi`, tone: "ok" };
  }
  return { text: "HENÜZ TARAMA YOK · TARA ile başlat", tone: "muted" };
}

/** Alt bilgi: "Kesit HH:MM · evren N · aday M · T sn". Saat biçimi dışarıdan verilir (fmt bağımlılığı yok). */
export function summaryLine(result: N7Result | null, fmtClock: (ms: number | null) => string): string {
  if (!result) return "";
  const parts: string[] = [`Kesit ${fmtClock(result.cutoff_ms)}`];
  parts.push(`evren ${result.universe ?? "—"}`);
  parts.push(`aday ${result.candidates ?? "—"}`);
  if (result.elapsed_s !== null) parts.push(`${Math.round(result.elapsed_s)} sn`);
  return parts.join(" · ");
}

/** 409 "zaten çalışıyor" tespiti — hata değil, durum metni olarak gösterilir. */
export const N7_ALREADY_RUNNING = "Tarama zaten çalışıyor";

export function isAlreadyRunning(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return msg.includes(N7_ALREADY_RUNNING) || msg.includes("API 409");
}

export const N7_METHOD_NOTE =
  "M1H: son 1/2/4 sa getirisi + hacim + VWAP + yükselen dip + sembolün kendi 7 günlük '1 saatte +%2 görme' oranı; " +
  "son 1 saatte +%8 üstü sıçrayan cezalı. Yatırım tavsiyesi değildir.";
