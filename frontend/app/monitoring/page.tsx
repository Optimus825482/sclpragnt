"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../lib/api";
import { fmtDateTime, formatPrice, toMs } from "../lib/format";
import { useAuth } from "../lib/auth";
import { useLiveMessages } from "../lib/liveSocket";
import { useModalA11y } from "../lib/useModalA11y";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { ML_PROB_TITLE, formatMlProbability } from "../lib/mlProbability";
import AppLoader from "../components/AppLoader";

type NotificationSettings = {
  enabled: boolean;
  min_score: number | null;
  min_target_pct: number | null;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  macd_refire_gate: boolean | null;
};

type ProfileInfo = {
  horizon_minutes: number;
  target_pct: number | null;
  velocity_score: number | null;
  upside_rank: number | null;
  passes: boolean;
  block_reason?: string | null;
};

type Candidate = {
  symbol: string;
  velocity_score: number;
  panel_score?: number | null;
  upside_rank?: number | null;
  target_pct: number;
  price: number;
  atr_pct?: number | null;
  mode: string;
  horizon_minutes: number;
  ml_target_pct: number | null;
  ml_hit_probability: number | null;
  rr?: number | null;
  sl_pct?: number | null;
  block_reason?: string | null;
  profiles?: Record<string, ProfileInfo>;
  status?: "bekliyor" | "tamamen" | "kismi" | "basarisiz" | null;
  unified_score?: number | null;
  unified_sources?: string[];
  unified_pass?: boolean;
  confluence_4way?: boolean;
  tp1_scalp_pct?: number | null;
  tp2_runner_pct?: number | null;
  master_surge?: any;
};

/** Teyit eşiğine yaklaşan ("ısınan") sembol — backend `state.warm` sözleşmesi. */
type WarmCandidate = {
  symbol: string;
  velocity_score: number | null;
  warm_reason: string | null;      // "atr_yaklas" | "bb_yaklas" | "struct_yaklas" | "m1_m3_oncu_atr"
  warm_proximity: number | null;   // 0..1 (kapıya yakınlık)
  price: number | null;
  change_24h: number | null;       // yüzde
  atr_pct: number | null;
  target_pct: number | null;
  horizon_minutes: number | null;
  profile: "5m" | "15m" | null;
  detected_at: number | null;      // epoch sn
  macd_mtf?: MacdMtfCompact | null;
};

/** MACD MTF konfluans özeti (backend `macd_mtf.cached_compact`) — M1/M3/M5/M15 MACD-Signal uyumu. */
type MacdMtfCompact = {
  symbol?: string;
  coverage?: number;
  confluence?: number | null;      // 0-100
  verdict?: string | null;         // GÜÇLÜ | ORTA | ZAYIF | VERİ YOK
  green_count?: number;
  parallel_up_count?: number;
  fresh_cross?: string[];          // taze yukarı kesişim TF'leri
  age_sec?: number;
};

/** Akıştan gelen ham keşif nabzı — backend `state.pulse` sözleşmesi (EN ERKEN katman, saniyeler). */
type PulseCandidate = {
  symbol: string;
  price: number | null;
  return_1m_pct: number | null;   // yüzde
  return_20s_pct: number | null;  // yüzde
  volume_burst: number | null;    // medyan hacme oran
  sample_age_sec: number | null;
  detected_at: number | null;     // epoch sn
  macd_mtf?: MacdMtfCompact | null;
};

/** MTF MACD rozeti: kullanıcının "kesişim + paralel yukarı" metodunun özeti. */
const mtfBadge = (mtf: MacdMtfCompact | null | undefined) => {
  if (!mtf) return null;
  const verdict = mtf.verdict ?? "VERİ YOK";
  if (verdict === "VERİ YOK") return null; // veri yoksa satırı kirletme
  const fresh = mtf.fresh_cross?.length ? ` · taze kesişim: ${mtf.fresh_cross.join(", ")}` : "";
  const title = `MTF MACD uyumu: ${mtf.green_count ?? 0} yeşil · ${mtf.parallel_up_count ?? 0} paralel yukarı${fresh}` +
    (mtf.age_sec != null ? ` (${Math.round(mtf.age_sec)} sn önce)` : "");
  if (verdict === "GÜÇLÜ") return { label: `MTF ✓ ${mtf.confluence ?? ""}`, cls: "border-neon-green/40 bg-neon-green/10 text-neon-green", title };
  if (verdict === "ORTA") return { label: `MTF ~ ${mtf.confluence ?? ""}`, cls: "border-yellow-400/40 bg-yellow-400/10 text-yellow-300", title };
  return { label: `MTF ✗ ${mtf.confluence ?? ""}`, cls: "border-bunker-700 bg-bunker-800 text-bunker-muted", title };
};

type MonitoringState = {
  last_scan_at: number | null;
  scan_count: number;
  candidates: Candidate[];
  watchlist: Candidate[];
  warm?: WarmCandidate[];
  pulse?: PulseCandidate[];
};

/** LLM ikinci-göz teşhisi (backend state.llm_second_eye) — sessiz arıza görünür olsun. */
type LlmEyeStatus = {
  delivered: number;
  evaluated: number;
  skipped: number;
  last_error_kind: string | null;   // provider_missing | timeout | http | schema | bad_response
  last_error: string | null;
  provider_missing_active: boolean;
};

const llmEyeChip = (s: LlmEyeStatus | null): { label: string; cls: string; title: string } | null => {
  if (!s) return null;
  if (s.last_error_kind === "provider_missing" || s.provider_missing_active) {
    return { label: "🧠 LLM: SAĞLAYICI YOK", cls: "border-neon-red/50 bg-neon-red/10 text-neon-red", title: s.last_error ?? "llm_enabled veya aktif chat modeli eksik — Ayarlar → LLM'i kontrol et" };
  }
  if (s.last_error_kind === "timeout") {
    return { label: "🧠 LLM: ZAMAN AŞIMI", cls: "border-yellow-400/50 bg-yellow-400/10 text-yellow-300", title: s.last_error ?? "Sağlayıcı yanıt vermedi — daha hızlı bir model seç" };
  }
  if (s.last_error_kind) {
    return { label: `🧠 LLM: ${s.last_error_kind.toUpperCase()}`, cls: "border-yellow-400/50 bg-yellow-400/10 text-yellow-300", title: s.last_error ?? "" };
  }
  if (s.delivered > 0) {
    return { label: `🧠 LLM: ${s.delivered} karar`, cls: "border-neon-green/40 bg-neon-green/10 text-neon-green", title: `${s.evaluated} değerlendirme · ${s.skipped} atlanan` };
  }
  return { label: "🧠 LLM: bekliyor", cls: "border-bunker-700 bg-bunker-800 text-bunker-muted", title: "İlk bildirim bekleniyor" };
};

type ServerHealth = {
  loop_active: boolean | null;
  data_ready: boolean | null;
  system_startup: boolean | null;
  next_scan_in_sec: number | null;
};

const EMPTY_HEALTH: ServerHealth = { loop_active: null, data_ready: null, system_startup: null, next_scan_in_sec: null };

function compareVapidKey(backendKey: string | null): { ok: boolean; offText: string } | null {
  if (!backendKey) return null;
  const own = (process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "").trim();
  if (!own) return { ok: false, offText: "FRONTEND ANAHTARI YOK" };
  return own === backendKey.trim()
    ? { ok: true, offText: "" }
    : { ok: false, offText: "UYUŞMUYOR — PUSH 401" };
}

class HttpStatusError extends Error {
  status: number;
  constructor(status: number) {
    super(`HTTP ${status}`);
    this.name = "HttpStatusError";
    this.status = status;
  }
}

const isAbortError = (err: unknown): boolean =>
  typeof err === "object" && err !== null && (err as { name?: string }).name === "AbortError";

const numOrNull = (value: unknown): number | null => {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const boolOrNull = (value: unknown): boolean | null => (typeof value === "boolean" ? value : null);

const httpMessage = (status: number): string => {
  if (status === 401) return "Oturum süresi doldu — yeniden giriş yapın.";
  if (status === 403) return "Bu işlem için yetkiniz yok (yalnız yönetici).";
  if (status === 404 || status === 405) return `Sunucu bu uç noktayı desteklemiyor (${status}) — sürüm uyuşmazlığı olabilir.`;
  if (status >= 500) return `Sunucu hatası (${status}).`;
  return `İstek başarısız (${status}).`;
};

const humanizeError = (err: unknown): string => {
  if (err instanceof HttpStatusError) return httpMessage(err.status);
  if (typeof err === "object" && err !== null && "status" in err) {
    const s = Number((err as { status?: unknown }).status);
    if (Number.isFinite(s) && s > 0) return httpMessage(s);
  }
  return "Sunucuya ulaşılamıyor (bağlantı hatası).";
};

const parseSettings = (raw: unknown): NotificationSettings | null => {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  return {
    enabled: value.enabled !== false,
    min_score: numOrNull(value.min_score),
    min_target_pct: numOrNull(value.min_target_pct),
    quiet_hours_start: (value.quiet_hours_start as string | null | undefined) ?? null,
    quiet_hours_end: (value.quiet_hours_end as string | null | undefined) ?? null,
    macd_refire_gate: typeof value.macd_refire_gate === "boolean" ? value.macd_refire_gate : null,
  };
};

const SCAN_INTERVAL_MS = 30_000;

/** Isınan sebep kodu → Türkçe etiket (bilinmeyen kod ham haliyle gösterilir). */
const WARM_REASON_LABEL: Record<string, string> = {
  atr_yaklas: "ATR eşiğine yaklaşıyor",
  bb_yaklas: "Bollinger genişliyor",
  struct_yaklas: "yapısal teyit yaklaşıyor",
  m1_m3_oncu_atr: "M1/M3 öncü ATR patlaması",
};

const WARM_PROFILE_LABEL: Record<string, string> = {
  "5m": "5dk",
  "15m": "15dk",
};

/** `state.warm` listesini savunmacı biçimde WarmCandidate[]'e normalize eder. */
const parseWarmCandidates = (raw: unknown): WarmCandidate[] => {
  if (!Array.isArray(raw)) return [];
  const list: WarmCandidate[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const v = item as Record<string, unknown>;
    if (typeof v.symbol !== "string" || !v.symbol) continue;
    const reason: string | null = typeof v.warm_reason === "string" && v.warm_reason ? v.warm_reason : null;
    const profileRaw: unknown = v.profile;
    const profile: WarmCandidate["profile"] = profileRaw === "5m" || profileRaw === "15m" ? profileRaw : null;
    list.push({
      symbol: v.symbol,
      velocity_score: numOrNull(v.velocity_score),
      warm_reason: reason,
      warm_proximity: numOrNull(v.warm_proximity),
      price: numOrNull(v.price),
      change_24h: numOrNull(v.change_24h),
      atr_pct: numOrNull(v.atr_pct),
      target_pct: numOrNull(v.target_pct),
      horizon_minutes: numOrNull(v.horizon_minutes),
      profile,
      detected_at: numOrNull(v.detected_at),
    });
  }
  return list;
};

/** `state.pulse` listesini savunmacı biçimde PulseCandidate[]'e normalize eder. */
const parsePulseCandidates = (raw: unknown): PulseCandidate[] => {
  if (!Array.isArray(raw)) return [];
  const list: PulseCandidate[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const v = item as Record<string, unknown>;
    if (typeof v.symbol !== "string" || !v.symbol) continue;
    list.push({
      symbol: v.symbol,
      price: numOrNull(v.price),
      return_1m_pct: numOrNull(v.return_1m_pct),
      return_20s_pct: numOrNull(v.return_20s_pct),
      volume_burst: numOrNull(v.volume_burst),
      sample_age_sec: numOrNull(v.sample_age_sec),
      detected_at: numOrNull(v.detected_at),
    });
  }
  return list;
};

/** Pulse getiri değeri → `+0.62%` biçimi (null → "—"). */
const formatPulseReturn = (v: number | null): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

const pulseReturnColor = (v: number | null): string =>
  v == null ? "text-bunker-muted" : v >= 0 ? "text-neon-green" : "text-neon-red";

type NotificationRow = {
  symbol?: string;
  score?: number | null;
  target_pct?: number | null;
  detected_at?: number | null;
  sent_via_push?: boolean | null;
  mode?: string | null;
  price?: number | null;
  expected_price?: number | null;
  llm_verdict?: string | null;
  llm_confidence?: number | null;
  llm_reasons?: { reasons?: string[]; trap_evidence?: string[]; summary?: string | null } | null;
};

/** LLM ikinci-göz karar rozeti: DEVAM ✓ yeşil, FAKE ⚠ kırmızı, BELİRSİZ gri. */
const llmVerdictBadge = (row: NotificationRow) => {
  const verdict = row.llm_verdict;
  if (!verdict) return null;
  const conf = row.llm_confidence;
  const confTxt = conf != null ? ` %${Math.round(conf)}` : "";
  if (verdict === "DEVAM") {
    return { label: `🧠 DEVAM ✓${confTxt}`, cls: "border-neon-green/40 bg-neon-green/10 text-neon-green", tone: "text-neon-green" };
  }
  if (verdict === "FAKE" || verdict === "TUZAK") {
    return { label: `🧠 FAKE ⚠${confTxt}`, cls: "border-neon-red/40 bg-neon-red/10 text-neon-red", tone: "text-neon-red" };
  }
  return { label: `🧠 BELİRSİZ${confTxt}`, cls: "border-bunker-700 bg-bunker-800 text-bunker-muted", tone: "text-bunker-muted" };
};

const SCORE_NORM_MODE: "log" | "linear" = "log";
const SCORE_NORM_LOG_REF = 25000;
const SCORE_NORM_CAP = 2000;

const relativeLabel = (ms: number, nowMs: number): string => {
  const sec = Math.max(0, Math.round((nowMs - ms) / 1000));
  if (sec < 60) return `${sec} sn önce`;
  if (sec < 3600) return `${Math.round(sec / 60)} dk önce`;
  if (sec < 86400) return `${Math.round(sec / 3600)} sa önce`;
  return `${Math.round(sec / 86400)} gün önce`;
};

const RelativeTime = ({ ts, tickMs = 30_000 }: { ts: number | null | undefined; tickMs?: number }) => {
  const [now, setNow] = useState(0);
  // Sekme arka plandayken "x dk önce" sayacı boşuna render edip dakikalarca
  // uyuyordu; `useVisibleInterval` döngüyü görünürlüğe bağlar.
  useVisibleInterval(() => setNow(Date.now()), tickMs);
  useEffect(() => { setNow(Date.now()); }, [ts]);
  const ms = toMs(ts);
  if (!ms || !now) return null;
  return <span className="text-bunker-muted"> · {relativeLabel(ms, now)}</span>;
};

const HEALTH_TONE = {
  good: "border-neon-green/40 bg-neon-green/10 text-neon-green",
  bad: "border-neon-red/40 bg-neon-red/10 text-neon-red",
  warn: "border-yellow-400/40 bg-yellow-400/10 text-yellow-300",
  muted: "border-bunker-700 bg-bunker-900/60 text-bunker-muted",
} as const;

const HealthChip = ({ label, value, onText, offText, onTone, offTone }: {
  label: string;
  value: boolean | null;
  onText: string;
  offText: string;
  onTone: keyof typeof HEALTH_TONE;
  offTone: keyof typeof HEALTH_TONE;
}) => {
  const tone = value == null ? "muted" : value ? onTone : offTone;
  const text = value == null ? "—" : value ? onText : offText;
  return <span className={`rounded-lg border px-2.5 py-1 font-mono text-[11px] font-bold ${HEALTH_TONE[tone]}`}>{label}: {text}</span>;
};

const LivenessBadge = ({ lastScanAt, loading }: { lastScanAt: number | null; loading?: boolean }) => {
  const [now, setNow] = useState(0);
  useVisibleInterval(() => setNow(Date.now()), 10_000);
  useEffect(() => { setNow(Date.now()); }, [lastScanAt]);
  if (loading) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/40 bg-sky-400/10 px-2.5 py-0.5 font-mono text-[10px] font-bold text-sky-300">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
        SENKRONİZE EDİLİYOR…
      </span>
    );
  }
  const ms = toMs(lastScanAt);
  if (!ms || !now) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/40 bg-sky-400/10 px-2.5 py-0.5 font-mono text-[10px] font-bold text-sky-300">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
        İLK TARAMA BEKLENİYOR
      </span>
    );
  }
  const sec = Math.max(0, Math.round((now - ms) / 1000));
  if (sec <= 90) {
    return <span className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold ${HEALTH_TONE.good}`}>● CANLI TARAMA AKTİF</span>;
  }
  if (sec <= 300) {
    return <span className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold ${HEALTH_TONE.warn}`}>● VERİ BAYAT ({sec}s)</span>;
  }
  return <span className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold ${HEALTH_TONE.bad}`}>● BAĞLANTI KESİLDİ</span>;
};

const computeTpSlRr = (c: Candidate) => {
  const price = Number(c.price);
  const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
  const slPct = Number(c.sl_pct);
  const serverRr = Number(c.rr);
  const valid = Number.isFinite(price) && price > 0 && Number.isFinite(targetPct) && targetPct > 0;
  if (!valid) return { tp: null as number | null, sl: null as number | null, rr: null as number | null };
  const tp = price * (1 + targetPct / 100);
  const hasSl = Number.isFinite(slPct) && slPct > 0;
  const sl = hasSl ? price * (1 - slPct / 100) : null;
  const rr = Number.isFinite(serverRr) && serverRr > 0
    ? serverRr
    : (hasSl ? targetPct / slPct : null);
  return { tp, sl, rr };
};

const STATUS_STYLE: Record<string, string> = {
  bekliyor: "border-bunker-600 bg-bunker-800/60 text-bunker-muted",
  tamamen: "border-neon-green/40 bg-neon-green/15 text-neon-green",
  kismi: "border-yellow-400/40 bg-yellow-400/15 text-yellow-300",
  basarisiz: "border-neon-red/40 bg-neon-red/15 text-neon-red",
};
const STATUS_LABEL: Record<string, string> = {
  bekliyor: "BEKLİYOR",
  tamamen: "HEDEFE ULAŞTI",
  kismi: "KISMI",
  basarisiz: "BAŞARISIZ",
};
const StatusChip = ({ status }: { status?: string | null }) => {
  const key = status ?? "bekliyor";
  const style = STATUS_STYLE[key] ?? STATUS_STYLE.bekliyor;
  const label = STATUS_LABEL[key] ?? STATUS_LABEL.bekliyor;
  return <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${style}`}>{label}</span>;
};

const panelScore = (c: { panel_score?: number | null; velocity_score?: number | null }): number | null => {
  if (c.panel_score != null) {
    const p = Number(c.panel_score);
    if (Number.isFinite(p)) return p;
  }
  if (c.velocity_score == null) return null;
  const raw = Number(c.velocity_score);
  if (!Number.isFinite(raw)) return null;
  if (raw <= 0) return 0;
  if (SCORE_NORM_MODE === "log") {
    return Math.round(100 * Math.log1p(raw) / Math.log1p(SCORE_NORM_LOG_REF) * 10) / 10;
  }
  return Math.round(100 * Math.min(1, raw / SCORE_NORM_CAP) * 10) / 10;
};

const SCORE_TONE_GREEN = 71.5;
const SCORE_TONE_YELLOW = 68.2;
const scoreColor = (score: number | null) =>
  score == null ? "text-bunker-muted" : score >= SCORE_TONE_GREEN ? "text-neon-green" : score >= SCORE_TONE_YELLOW ? "text-yellow-300" : "text-neon-red";
const scoreText = (score: number | null) => (score == null ? "—" : score.toFixed(1));

const blockReasonLabel = (reason?: string | null) => {
  if (!reason) return null;
  if (reason.startsWith("mfi_asiri_alim")) return "MFI aşırı alım";
  if (reason.startsWith("mfi_asiri_satim")) return "MFI aşırı satım";
  if (reason.startsWith("rsi_asiri_alim")) return "RSI aşırı alım";
  if (reason.startsWith("atr_yetersiz")) {
    const m = reason.match(/atr_yetersiz:([\d.]+)%<([\d.]+)%/);
    if (m) return `ATR (%${m[1]} < %${m[2]})`;
    return "ATR yetersiz";
  }
  if (reason.startsWith("bb_genisligi_yetersiz") || reason === "bb_verisi_yok") return "Bollinger dar";
  if (reason === "yapisal_teyit_yok") return "Yapısal trend yok";
  if (reason === "diger") return "Kriter altı";
  return "Kriter bekleniyor";
};

const CandidateDetail = ({ c, kind, onClose }: { c: Candidate; kind: "radar" | "watch"; onClose: () => void }) => {
  const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
  const price = Number(c.price);
  const validTarget = Number.isFinite(targetPct) && targetPct > 0 && Number.isFinite(price) && price > 0;
  const expected = validTarget ? price * (1 + targetPct / 100) : null;
  const { sl, rr } = computeTpSlRr(c);
  // Escape + odak tuzağı + geri odak: `lib/useModalA11y` ile paylaşılan tek
  // doğruluk kaynağı (binance-tr'ın gerçek para modalları da bunu kullanır).
  const a11y = useModalA11y(true, onClose, `${kind === "radar" ? "Radar adayı" : "İzlenen sembol"} — ${c.symbol}`);

  const isUnifiedPass = c.unified_pass === true;
  const score = isUnifiedPass && c.unified_score != null ? Number(c.unified_score) : panelScore(c);

  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="candidate-detail-title" aria-label={a11y.label}>
      <section
        ref={a11y.ref}
        tabIndex={-1}
        onKeyDown={a11y.onKeyDown}
        className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-2xl border border-neon-green/40 bg-bunker-950 shadow-2xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-bunker-800 bg-neon-green/5 px-6 py-4">
          <div>
            <p className="eyebrow text-neon-green">{kind === "radar" ? "🎯 ONAYLI YÜKSELME ADAYI" : "👁 İZLEMEDEKİ SEMBOL"}</p>
            <h2 id="candidate-detail-title" className="font-mono text-2xl font-black text-white">{c.symbol}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Kapat" className="rounded-lg p-1 text-bunker-muted hover:bg-bunker-800 hover:text-white transition-colors">✕</button>
        </div>

        <div className="grid grid-cols-2 gap-3 p-6">
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-3 text-center">
            <p className="eyebrow text-bunker-muted">GÜVEN SKORU</p>
            <p className={`mt-1 font-mono text-2xl font-black ${scoreColor(score)}`}>{scoreText(score)}</p>
          </div>
          <div className="rounded-xl border border-neon-green/30 bg-neon-green/10 p-3 text-center">
            <p className="eyebrow text-neon-green">HEDEF POTANSİYEL</p>
            <p className={`mt-1 font-mono text-2xl font-black ${validTarget ? "text-neon-green" : "text-bunker-muted"}`}>{validTarget ? `+${targetPct.toFixed(1)}%` : "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-bunker-muted">GİRİŞ / ANLIK</p>
            <p className="mt-1 font-mono text-base font-bold text-white">₺{formatPrice(price)}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-neon-green">HEDEF FİYAT (TP)</p>
            <p className="mt-1 font-mono text-base font-bold text-neon-green">{expected != null ? `₺${formatPrice(expected)}` : "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-neon-red">STOP LOSS (SL)</p>
            <p className="mt-1 font-mono text-base font-bold text-neon-red">{sl != null ? `₺${formatPrice(sl)}` : "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-yellow-300">ÖDÜL / RİSK (R:R)</p>
            <p className="mt-1 font-mono text-base font-bold text-yellow-300">{rr != null ? rr.toFixed(2) : "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-bunker-muted">BEKLENEN SÜRE</p>
            <p className="mt-1 font-mono text-sm font-bold text-white">{c.horizon_minutes ? `${c.horizon_minutes} Dakika` : "5 Dakika"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-center">
            <p className="eyebrow text-bunker-muted">ML İSABET ORANI</p>
            <p className="mt-1 font-mono text-sm font-bold text-violet-300" title={ML_PROB_TITLE}>
              {formatMlProbability(c.ml_hit_probability)}
            </p>
          </div>
        </div>

        {c.profiles && Object.keys(c.profiles).length > 0 && (
          <div className="border-t border-bunker-800 px-6 py-4">
            <p className="eyebrow mb-2 text-bunker-muted">ZAMAN PROFİL ANALİZİ</p>
            <div className="space-y-2">
              {Object.values(c.profiles).map((p) => (
                <div key={p.horizon_minutes} className={`flex items-center justify-between rounded-lg border px-3 py-2 font-mono text-xs ${p.passes ? "border-neon-green/30 bg-neon-green/5" : "border-bunker-800 bg-bunker-900/40"}`}>
                  <span className="font-bold text-white">{p.horizon_minutes}dk Ufuk</span>
                  <span className="text-bunker-muted">Hedef: <b className={p.target_pct == null ? "text-bunker-muted" : "text-neon-green"}>{p.target_pct == null ? "—" : `+${Number(p.target_pct).toFixed(1)}%`}</b></span>
                  <span className="text-bunker-muted">Skor: <b className="text-white">{scoreText(panelScore({ velocity_score: p.velocity_score }))}</b></span>
                  <span className={p.passes ? "text-neon-green font-bold" : "text-neon-red"} title={p.block_reason ? `Ham neden: ${p.block_reason}` : undefined}>
                    {p.passes ? "ONAYLI" : (blockReasonLabel(p.block_reason) ?? "İZLE")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-bunker-800 px-6 py-4 bg-bunker-900/50">
          <span className={`rounded-md px-2.5 py-1 text-xs font-mono font-bold ${c.mode === "trend_devam" ? "bg-neon-green/15 text-neon-green" : c.mode === "v_donusu" ? "bg-yellow-400/15 text-yellow-300" : "bg-sky-400/15 text-sky-300"}`}>
            {c.mode === "trend_devam" ? "TREND DEVAM" : c.mode === "v_donusu" ? "V-DÖNÜŞÜ" : "NÖTR REJİM"}
          </span>
          <div className="flex gap-2">
            <Link href={`/charts?symbol=${encodeURIComponent(c.symbol)}`} className="ui-button ui-button-secondary py-2 px-4 text-xs">GRAFİKTE AÇ</Link>
            <button type="button" onClick={onClose} className="ui-button ui-button-primary py-2 px-4 text-xs">KAPAT</button>
          </div>
        </div>
      </section>
    </div>
  );
};

export default function MonitoringPage() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [state, setState] = useState<MonitoringState>({ last_scan_at: null, scan_count: 0, candidates: [], watchlist: [], warm: [], pulse: [] });
  const [effectiveMinScore, setEffectiveMinScore] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [, setSettings] = useState<NotificationSettings | null>(null);
  const [thresholds, setThresholds] = useState<{ panel: number | null; raw: number | null }>({ panel: null, raw: null });
  const [rrGate, setRrGate] = useState<{ min: number | null; slPct: number | null; blocked: number | null; enabled: boolean | null }>(
    { min: null, slPct: null, blocked: null, enabled: null },
  );
  const [pushHealth, setPushHealth] = useState<{
    subscribers: number | null;
    backend_vapid_configured: boolean;
    vapid_public_key: string | null;
  } | null>(null);
  const [health, setHealth] = useState<ServerHealth>(EMPTY_HEALTH);
  const [llmEyeStatus, setLlmEyeStatus] = useState<LlmEyeStatus | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [stateLoaded, setStateLoaded] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ c: Candidate; kind: "radar" | "watch" } | null>(null);

  // Sekme yönetimi: Kullanıcının odaklanmak istediği görünümler
  const [activeTab, setActiveTab] = useState<"candidates" | "watchlist" | "notifications" | "overview">("candidates");

  // Filtreleme / sıralama
  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterMode, setFilterMode] = useState<"all" | "trend_devam" | "v_donusu" | "notr">("all");
  const [sortBy, setSortBy] = useState<"score" | "target" | "rr" | "atr">("score");

  const [savingSettings, setSavingSettings] = useState(false);
  const [historyRows, setHistoryRows] = useState<NotificationRow[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Eşik düzenleme modalı (Admin)
  const [showScoreModal, setShowScoreModal] = useState(false);
  const [editScoreInput, setEditScoreInput] = useState("70");
  const [savingScore, setSavingScore] = useState(false);

  const stateReqIdRef = useRef(0);
  const stateInFlightRef = useRef(false);
  const scanInFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const nextPollMsRef = useRef(SCAN_INTERVAL_MS);

  const applyMonitoringPayload = useCallback((data: any) => {
    setState({
      last_scan_at: data?.last_scan_at ?? data?.scan_at ?? null,
      scan_count: numOrNull(data?.scan_count) ?? 0,
      candidates: Array.isArray(data?.candidates) ? data.candidates : [],
      watchlist: Array.isArray(data?.watchlist) ? data.watchlist : [],
      warm: parseWarmCandidates(data?.warm),
      pulse: parsePulseCandidates(data?.pulse),
    });
    const lse = data?.llm_second_eye;
    setLlmEyeStatus(lse && typeof lse === "object"
      ? {
        delivered: numOrNull(lse.delivered) ?? 0,
        evaluated: numOrNull(lse.evaluated) ?? 0,
        skipped: numOrNull(lse.skipped) ?? 0,
        last_error_kind: typeof lse.last_error_kind === "string" ? lse.last_error_kind : null,
        last_error: typeof lse.last_error === "string" ? lse.last_error : null,
        provider_missing_active: Boolean(lse.provider_missing_active),
      }
      : null);
    setHealth({
      loop_active: boolOrNull(data?.loop_active),
      data_ready: boolOrNull(data?.data_ready),
      system_startup: boolOrNull(data?.system_startup),
      next_scan_in_sec: numOrNull(data?.next_scan_in_sec),
    });
    const parsed = parseSettings(data?.settings);
    if (parsed) setSettings(parsed);
    setEffectiveMinScore(numOrNull(data?.effective_min_score));
    const panel = numOrNull(data?.monitoring_min_score_panel ?? data?.settings?.monitoring_min_score_panel);
    const raw = numOrNull(data?.monitoring_min_raw_score ?? data?.settings?.monitoring_min_raw_score);
    if (panel != null || raw != null) setThresholds({ panel, raw });
    setRrGate({
      min: numOrNull(data?.rr_min ?? data?.settings?.rr_min),
      slPct: numOrNull(data?.rr_sl_pct ?? data?.settings?.rr_sl_pct),
      blocked: numOrNull(data?.rr_blocked),
      enabled: typeof (data?.rr_enabled ?? data?.settings?.rr_enabled) === "boolean"
        ? Boolean(data?.rr_enabled ?? data?.settings?.rr_enabled)
        : null,
    });
    const push = data?.push;
    setPushHealth(push && typeof push === "object"
      ? {
        subscribers: numOrNull(push.subscribers),
        backend_vapid_configured: Boolean(push.backend_vapid_configured),
        vapid_public_key: typeof push.vapid_public_key === "string" && push.vapid_public_key
          ? String(push.vapid_public_key)
          : null,
      }
      : null);
    setStateError(null);
    setStateLoaded(true);
    setLastUpdatedAt(Date.now());
    const nextIn = numOrNull(data?.next_scan_in_sec);
    nextPollMsRef.current = nextIn != null ? Math.max(15_000, Math.round(nextIn) * 1000) : SCAN_INTERVAL_MS;
  }, []);

  const loadState = useCallback(async (opts?: { signal?: AbortSignal; force?: boolean }) => {
    if (!opts?.force && (stateInFlightRef.current || scanInFlightRef.current)) return;
    stateInFlightRef.current = true;
    const reqId = ++stateReqIdRef.current;
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store", signal: opts?.signal });
      if (reqId !== stateReqIdRef.current || !mountedRef.current) return;
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (reqId !== stateReqIdRef.current || !mountedRef.current) return;
      applyMonitoringPayload(data);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current || reqId !== stateReqIdRef.current) return;
      setStateError(humanizeError(err));
    } finally {
      stateInFlightRef.current = false;
    }
  }, [applyMonitoringPayload]);

  const historyReqIdRef = useRef(0);
  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    const reqId = ++historyReqIdRef.current;
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/notifications`, { cache: "no-store", signal });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current || historyReqIdRef.current !== reqId) return;
      const list: NotificationRow[] = Array.isArray(data?.history) ? data.history : [];
      setHistoryRows(list.slice(0, 15));
      setHistoryError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current || historyReqIdRef.current !== reqId) return;
      setHistoryError(humanizeError(err));
    }
  }, []);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "monitoring_alert") {
      void loadState();
      void loadHistory();
    }
  }, [loadState, loadHistory]);
  useLiveMessages(onLiveMessage);

  const loadSettings = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store", signal });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current) return;
      const parsed = parseSettings(data);
      if (parsed) setSettings(parsed);
      setEffectiveMinScore(numOrNull(data?.effective_min_score));
      const panel = numOrNull(data?.monitoring_min_score_panel);
      const raw = numOrNull(data?.monitoring_min_raw_score);
      if (panel != null || raw != null) setThresholds((prev) => ({ panel: panel ?? prev.panel, raw: raw ?? prev.raw }));
      setSettingsError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current) return;
      setSettingsError(humanizeError(err));
    }
  }, []);

  const resetNotifications = useCallback(async () => {
    setSettingsError(null);
    setSavingSettings(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/reset-notifications`, { method: "POST", cache: "no-store" });
      if (res.status === 401 || res.status === 403) { setSettingsError("Bu işlemi yalnız yönetici yapabilir — yetkiniz yok."); return; }
      if (!res.ok) throw new HttpStatusError(res.status);
      setScanNote("Bildirim spam koruması sıfırlandı.");
      await loadSettings();
      await loadState();
    } catch (err) {
      if (!mountedRef.current) return;
      setSettingsError(`Bildirim sıfırlanamadı: ${humanizeError(err)}`);
    } finally {
      if (mountedRef.current) setSavingSettings(false);
    }
  }, [loadSettings, loadState]);

  const handleSaveScore = useCallback(async () => {
    const val = Number(editScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) {
      setSettingsError("Eşik skoru 0 ile 100 arasında olmalıdır.");
      return;
    }
    setSavingScore(true);
    setSettingsError(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_score: val }),
      });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      setShowScoreModal(false);
      setScanNote(`Bildirim eşik skoru ≥ ${data.min_score ?? val} olarak güncellendi.`);
      await loadSettings();
      await loadState();
    } catch (err) {
      if (!mountedRef.current) return;
      setSettingsError(`Eşik kaydedilemedi: ${humanizeError(err)}`);
    } finally {
      if (mountedRef.current) setSavingScore(false);
    }
  }, [editScoreInput, loadSettings, loadState]);

  const runScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setScanNote(null);
    scanInFlightRef.current = true;
    const reqId = ++stateReqIdRef.current;
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/scan`, { method: "POST", cache: "no-store" });
      if (reqId !== stateReqIdRef.current || !mountedRef.current) return;
      if (res.status === 401 || res.status === 403) {
        setScanError("Bu taramayı yalnızca yönetici tetikleyebilir — yetkiniz yok.");
        return;
      }
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current || reqId !== stateReqIdRef.current) return;
      if (data?.error) { setScanError(`Tarama hatası: ${data.error}`); return; }
      applyMonitoringPayload(data);
      if (data?.cached === true) {
        setScanNote(`Taze tarama yapılmadı; son önbellek gösteriliyor${data?.system_startup ? " (sistem yeni başladı)" : ""}.`);
      } else {
        setScanNote("Tarama tamamlandı ve yeni adaylar güncellendi.");
      }
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current) return;
      setScanError(`Tarama başlatılamadı: ${humanizeError(err)}`);
    } finally {
      scanInFlightRef.current = false;
      if (mountedRef.current) setScanning(false);
    }
  }, [applyMonitoringPayload]);

  useEffect(() => {
    mountedRef.current = true;
    void loadSettings();
    void loadState({ force: true });
    void loadHistory();

    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = (delayMs: number) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        if (document.hidden) { schedule(SCAN_INTERVAL_MS); return; }
        await loadState();
        schedule(nextPollMsRef.current);
      }, delayMs);
    };
    schedule(SCAN_INTERVAL_MS);

    const onVisibility = () => {
      if (!document.hidden) {
        void loadState({ force: true });
        void loadHistory();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      mountedRef.current = false;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [loadState, loadSettings, loadHistory]);

  const effThreshold = effectiveMinScore ?? thresholds.panel;
  const rawThreshold = thresholds.raw;
  const candidates = state.candidates;
  // Backend yakınlığa göre desc sıralı ve max 12 gönderir; sıralamaya dokunulmaz,
  // yalnızca savunmacı kırpma yapılır.
  const warmList = (state.warm ?? []).slice(0, 12);
  // Backend |getiri| büyükten küçüğe sıralı ve max 15 gönderir; sıralamaya dokunulmaz,
  // yalnızca savunmacı kırpma yapılır. (pulse undefined gelebilir — [] kabul eder.)
  const pulseList = (state.pulse ?? []).slice(0, 15);

  const filteredCandidates = useMemo(() => {
    let list = [...candidates];
    if (filterSymbol.trim()) {
      const q = filterSymbol.trim().toUpperCase();
      list = list.filter((c) => c.symbol.toUpperCase().includes(q));
    }
    if (filterMode !== "all") {
      list = list.filter((c) => c.mode === filterMode);
    }
    list.sort((a, b) => {
      if (sortBy === "score") {
        const scoreOf = (c: Candidate) =>
          c.unified_pass === true && c.unified_score != null ? Number(c.unified_score) : (panelScore(c) ?? -1);
        return scoreOf(b) - scoreOf(a);
      }
      if (sortBy === "target") {
        const ta = Number(a.target_pct) || 0;
        const tb = Number(b.target_pct) || 0;
        return tb - ta;
      }
      if (sortBy === "rr") {
        const ra = computeTpSlRr(a).rr ?? -1;
        const rb = computeTpSlRr(b).rr ?? -1;
        return rb - ra;
      }
      if (sortBy === "atr") {
        const aa = Number.isFinite(Number(a.atr_pct)) ? Number(a.atr_pct) : -1;
        const ab = Number.isFinite(Number(b.atr_pct)) ? Number(b.atr_pct) : -1;
        return ab - aa;
      }
      return 0;
    });
    return list;
  }, [candidates, filterSymbol, filterMode, sortBy]);

  if (!stateLoaded && !stateError) {
    return (
      <main className="page-shell space-y-6">
        <div className="page-heading flex flex-wrap items-start justify-between gap-4 border-b border-bunker-800 pb-5">
          <div>
            <div className="flex items-center gap-2">
              <p className="eyebrow text-neon-green">OTONOM PİYASA RADARI</p>
              <LivenessBadge lastScanAt={null} loading={true} />
            </div>
            <h1 className="font-mono text-2xl sm:text-3xl font-black text-white mt-1">Radar &amp; Hız Avcısı</h1>
            <p className="mt-1 text-sm text-bunker-muted max-w-2xl">
              Piyasadaki en güçlü ivme ve yükselme potansiyeli taşıyan semboller filtrelenir, doğrulanmış fırsatlar anlık olarak listelenir ve bildirilir.
            </p>
          </div>
        </div>

        <AppLoader
          variant="radar"
          label="OTONOM PİYASA RADARI SENKRONİZE EDİLİYOR…"
          sublabel="Tüm Binance TR işlem çiftleri derinlik, hacim, ATR ve momentum filtrelerinden geçiriliyor"
          minHeight="min-h-[55vh]"
        />
      </main>
    );
  }

  return (
    <main className="page-shell space-y-6">
      {/* 1. ÜST BAŞLIK VE HIZLI EYLEMLER */}
      <div className="page-heading flex flex-wrap items-start justify-between gap-4 border-b border-bunker-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <p className="eyebrow text-neon-green">OTONOM PİYASA RADARI</p>
            <LivenessBadge lastScanAt={state.last_scan_at} />
            {(() => {
              const chip = llmEyeChip(llmEyeStatus);
              return chip ? (
                <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold ${chip.cls}`} title={chip.title}>
                  {chip.label}
                </span>
              ) : null;
            })()}
          </div>
          <h1 className="font-mono text-2xl sm:text-3xl font-black text-white mt-1">Yükselme Takip &amp; Bildirim</h1>
          <p className="mt-1 text-sm text-bunker-muted max-w-2xl">
            Piyasadaki en güçlü ivme ve yükselme potansiyeli taşıyan semboller filtrelenir, doğrulanmış fırsatlar anlık olarak listelenir ve bildirilir.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {isAdmin ? (
            <button
              type="button"
              onClick={() => {
                setEditScoreInput(String(Math.round(effThreshold ?? 70)));
                setShowScoreModal(true);
              }}
              className="ui-button ui-button-secondary text-xs hover:border-neon-green/60 hover:text-white flex items-center gap-1.5 transition-all cursor-pointer"
              title="Skor eşiğini değiştirmek için tıklayın"
            >
              <span>🎯 EŞİK: SKOR ≥ {effThreshold != null ? effThreshold : "—"}</span>
              <span className="text-[10px] text-neon-green border border-neon-green/40 px-1 rounded bg-neon-green/10">Düzenle ✎</span>
            </button>
          ) : (
            <span className="ui-button ui-button-secondary pointer-events-none text-xs" title="Radar eşik filtresi">
              🎯 EŞİK: SKOR ≥ {effThreshold != null ? effThreshold : "—"}
            </span>
          )}

          {isAdmin ? (
            <button
              onClick={runScan}
              disabled={scanning}
              className="ui-button ui-button-primary text-xs flex items-center gap-1.5"
            >
              {scanning ? (
                <>
                  <span className="animate-spin text-sm">⏳</span> TARANIYOR…
                </>
              ) : (
                <>
                  <span>⚡</span> ŞİMDİ TARA
                </>
              )}
            </button>
          ) : (
            <span className="ui-button ui-button-secondary pointer-events-none text-xs font-mono text-bunker-muted">
              🔒 Tarama: Yönetici
            </span>
          )}

          {isAdmin && (
            <button
              onClick={() => void resetNotifications()}
              disabled={savingSettings}
              title="Aynı sembollerin tekrar bildirilebilmesi için spam engelini sıfırlar"
              className="ui-button ui-button-secondary text-xs"
            >
              BİLDİRİM SIFIRLA
            </button>
          )}
        </div>
      </div>

      {/* 2. HATA VE BİLGİLENDİRME ŞERİTLERİ */}
      {(stateError || settingsError) && (
        <div role="alert" className="card flex flex-wrap items-center justify-between gap-3 border-neon-red/40 bg-neon-red/5 p-4 rounded-xl">
          <p className="text-sm text-neon-red font-mono">
            ⚠ {stateError ?? settingsError}
            {lastUpdatedAt != null && <span className="text-bunker-muted text-xs"> (Son okuma: {fmtDateTime(lastUpdatedAt)})</span>}
          </p>
          <button type="button" onClick={() => { void loadSettings(); void loadState({ force: true }); }} className="ui-button ui-button-secondary text-xs py-1 px-3">YENİDEN DENE</button>
        </div>
      )}

      {scanError && (
        <div role="alert" className="card border-neon-red/40 bg-neon-red/5 p-4 rounded-xl">
          <p className="text-sm text-neon-red font-mono">⚠ {scanError}</p>
        </div>
      )}
      {scanNote && !scanError && (
        <div role="status" className="card border-neon-green/30 bg-neon-green/5 p-4 rounded-xl">
          <p className="text-sm text-neon-green font-mono">✓ {scanNote}</p>
        </div>
      )}

      {/* 3. KRİTİK KPI VE ÖZET KARTLARI (DASHBOARD KARTLARI) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <button
          type="button"
          onClick={() => setActiveTab("candidates")}
          className={`card text-left transition-all p-4 rounded-xl border ${activeTab === "candidates" ? "border-neon-green bg-neon-green/10 shadow-lg shadow-neon-green/5" : "border-bunker-800 bg-bunker-900/40 hover:border-neon-green/40"}`}
        >
          <div className="flex items-center justify-between">
            <p className="eyebrow text-neon-green">YÜKSELME ADAYLARI</p>
            <span className="text-xs">🎯</span>
          </div>
          <p className="mt-2 font-mono text-3xl font-black text-white">
            {stateLoaded ? candidates.length : "—"}
          </p>
          <p className="mt-1 text-[11px] text-bunker-muted">İşleme hazır, onaylı sinyaller</p>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("watchlist")}
          className={`card text-left transition-all p-4 rounded-xl border ${activeTab === "watchlist" ? "border-yellow-400 bg-yellow-400/10 shadow-lg shadow-yellow-400/5" : "border-bunker-800 bg-bunker-900/40 hover:border-yellow-400/40"}`}
        >
          <div className="flex items-center justify-between">
            <p className="eyebrow text-yellow-300">İZLEME LİSTESİ</p>
            <span className="text-xs">👁</span>
          </div>
          <p className="mt-2 font-mono text-3xl font-black text-white">
            {stateLoaded ? state.watchlist.length : "—"}
          </p>
          <p className="mt-1 text-[11px] text-bunker-muted">Kriter sınırında takip edilenler</p>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("notifications")}
          className={`card text-left transition-all p-4 rounded-xl border ${activeTab === "notifications" ? "border-sky-400 bg-sky-400/10 shadow-lg shadow-sky-400/5" : "border-bunker-800 bg-bunker-900/40 hover:border-sky-400/40"}`}
        >
          <div className="flex items-center justify-between">
            <p className="eyebrow text-sky-300">SON BİLDİRİMLER</p>
            <span className="text-xs">🔔</span>
          </div>
          <p className="mt-2 font-mono text-3xl font-black text-white">
            {historyRows != null ? historyRows.length : "—"}
          </p>
          <p className="mt-1 text-[11px] text-bunker-muted">Kullanıcıya giden anlık uyarılar</p>
        </button>

        <div className="card p-4 rounded-xl border border-bunker-800 bg-bunker-900/40">
          <div className="flex items-center justify-between">
            <p className="eyebrow text-bunker-muted">TARAMA DÖNGÜSÜ</p>
            <span className="text-xs">⏱</span>
          </div>
          <p className="mt-2 font-mono text-base font-bold text-white truncate">
            {fmtDateTime(state.last_scan_at)}
          </p>
          <div className="mt-1 flex items-center justify-between text-[11px] text-bunker-muted font-mono">
            <span>#{state.scan_count} Tur</span>
            <RelativeTime ts={state.last_scan_at} />
          </div>
        </div>
      </div>

      {/* 4. SEKME NAVİGASYON ÇUBUĞU */}
      <div className="flex items-center justify-between border-b border-bunker-800 pb-2">
        <div className="flex items-center gap-1 sm:gap-2 overflow-x-auto no-scrollbar">
          <button
            type="button"
            onClick={() => setActiveTab("candidates")}
            className={`rounded-xl px-4 py-2 font-mono text-xs sm:text-sm font-bold transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === "candidates"
                ? "bg-neon-green/15 text-neon-green border border-neon-green/40 shadow-sm"
                : "text-bunker-muted hover:text-white hover:bg-bunker-900"
            }`}
          >
            <span>🎯</span> Yükselme Adayları
            <span className="rounded-full bg-bunker-900 px-2 py-0.5 text-[10px] text-white">
              {candidates.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("watchlist")}
            className={`rounded-xl px-4 py-2 font-mono text-xs sm:text-sm font-bold transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === "watchlist"
                ? "bg-yellow-400/15 text-yellow-300 border border-yellow-400/40 shadow-sm"
                : "text-bunker-muted hover:text-white hover:bg-bunker-900"
            }`}
          >
            <span>👁</span> İzleme Listesi
            <span className="rounded-full bg-bunker-900 px-2 py-0.5 text-[10px] text-white">
              {state.watchlist.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("notifications")}
            className={`rounded-xl px-4 py-2 font-mono text-xs sm:text-sm font-bold transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === "notifications"
                ? "bg-sky-400/15 text-sky-300 border border-sky-400/40 shadow-sm"
                : "text-bunker-muted hover:text-white hover:bg-bunker-900"
            }`}
          >
            <span>🔔</span> Son Bildirimler
            <span className="rounded-full bg-bunker-900 px-2 py-0.5 text-[10px] text-white">
              {historyRows?.length ?? 0}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("overview")}
            className={`rounded-xl px-4 py-2 font-mono text-xs sm:text-sm font-bold transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === "overview"
                ? "bg-white/10 text-white border border-white/20 shadow-sm"
                : "text-bunker-muted hover:text-white hover:bg-bunker-900"
            }`}
          >
            <span>📊</span> Tümünü Göster
          </button>
        </div>

        {/* Sağ köşe sistem sağlığı rozetleri */}
        <div className="hidden lg:flex items-center gap-2">
          {pushHealth != null && (
            <HealthChip
              label="Push"
              value={pushHealth.subscribers != null && pushHealth.subscribers > 0 && pushHealth.backend_vapid_configured}
              onText={`${pushHealth.subscribers} Aktif`}
              offText={pushHealth.backend_vapid_configured ? "Abone Yok" : "Kapalı"}
              onTone="good"
              offTone="warn"
            />
          )}
          {pushHealth?.backend_vapid_configured && (() => {
            const verdict = compareVapidKey(pushHealth.vapid_public_key);
            if (!verdict) return null;
            return (
              <HealthChip
                label="VAPID"
                value={verdict.ok}
                onText="Uyumlu"
                offText={verdict.offText}
                onTone="good"
                offTone="bad"
              />
            );
          })()}
        </div>
      </div>

      {/* 5. ANA İÇERİK BÖLÜMLERİ */}

      {/* BÖLÜM 1: 🎯 YÜKSELME ADAYLARI */}
      {(activeTab === "candidates" || activeTab === "overview") && (
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-bunker-800/80 pb-3">
            <div>
              <h2 className="font-mono text-lg font-black text-white flex items-center gap-2">
                <span>🎯</span> YÜKSELME POTANSİYELİ OLAN ADAYLAR
                <span className="rounded-full bg-neon-green/20 text-neon-green border border-neon-green/40 px-2 py-0.5 text-xs">
                  {filteredCandidates.length}
                </span>
              </h2>
              <p className="mt-1 text-xs text-bunker-muted">
                Volatilite (ATR), yapısal trend, momentum ve hacim kriterlerini tam sağlayan onaylı fırsatlar.
                {rrGate.slPct != null ? ` · SL Dayanağı: %${rrGate.slPct.toFixed(1)} · Min R/R: ${rrGate.min?.toFixed(2) ?? "—"}` : ""}
              </p>
            </div>

            {/* Filtre ve Arama Araçları */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <input
                  type="text"
                  value={filterSymbol}
                  onChange={(e) => setFilterSymbol(e.target.value)}
                  placeholder="Sembol ara (örn: BTC)"
                  className="w-32 sm:w-36 bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-xs text-white placeholder-bunker-muted focus:border-neon-green/50 outline-none transition-all"
                />
                {filterSymbol && (
                  <button type="button" onClick={() => setFilterSymbol("")} className="absolute right-2 top-1.5 text-bunker-muted hover:text-white text-xs">✕</button>
                )}
              </div>

              <select
                value={filterMode}
                onChange={(e) => setFilterMode(e.target.value as typeof filterMode)}
                className="bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green/50 outline-none"
              >
                <option value="all">Tüm Modlar</option>
                <option value="trend_devam">Trend Devam</option>
                <option value="v_donusu">V-Dönüşü</option>
                <option value="notr">Nötr</option>
              </select>

              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                className="bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green/50 outline-none"
              >
                <option value="score">Skor (Yüksek)</option>
                <option value="target">Hedef (Yüksek)</option>
                <option value="rr">R/R Oranı</option>
                <option value="atr">ATR% Volatilite</option>
              </select>
            </div>
          </div>

          {/* Aday Listesi */}
          {filteredCandidates.length === 0 ? (
            <div className="py-12 text-center">
              <div className="font-mono text-3xl mb-2 text-bunker-muted">🔍</div>
              {stateError && !stateLoaded ? (
                <p className="text-sm text-neon-red font-mono">Sunucu verisi alınamadı. Yukarıdan &apos;Yeniden Dene&apos; butonunu kullanabilirsiniz.</p>
              ) : health.loop_active === false ? (
                <p className="text-sm text-neon-red font-mono">Tarama döngüsü çalışmıyor — otonom tarayıcı durdurulmuş.</p>
              ) : health.system_startup === true ? (
                <div className="space-y-3 py-4">
                  <div className="monitoring-radar mx-auto scale-75">
                    <div className="monitoring-radar-ring monitoring-radar-ring-1" />
                    <div className="monitoring-radar-ring monitoring-radar-ring-2" />
                    <div className="monitoring-radar-ring monitoring-radar-ring-3" />
                    <div className="monitoring-radar-sweep" />
                    <div className="monitoring-radar-center" />
                  </div>
                  <p className="text-sm text-neon-green font-mono font-bold tracking-wide">RADAR AKTİF · İLK PİYASA TARAMASI YÜRÜTÜLÜYOR…</p>
                  <p className="text-xs text-bunker-muted font-mono max-w-md mx-auto">
                    Tüm Binance TR çiftleri analiz ediliyor. Kriterleri sağlayan onaylı sinyaller birazdan burada listelenecek.
                  </p>
                </div>
              ) : candidates.length === 0 ? (
                <p className="text-sm text-bunker-muted font-mono">
                  Şu an için eşiği (Skor ≥ {effThreshold != null ? effThreshold : "—"}) geçen aday bulunmuyor. Sistem periyodik olarak taramaya devam ediyor.
                </p>
              ) : (
                <p className="text-sm text-bunker-muted font-mono">Arama veya mod filtresine uyan aday bulunamadı.</p>
              )}
            </div>
          ) : (
            <div className="space-y-2.5">
              {filteredCandidates.map((c, i) => {
                const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
                const validTarget = Number.isFinite(targetPct) && targetPct > 0;
                const mlActive = Number(c.ml_target_pct) > 0 && c.ml_hit_probability != null;
                const unifiedSources = (c.unified_sources || []).filter((s) => typeof s === "string" && s);
                const isUnifiedPass = c.unified_pass === true;
                const score = isUnifiedPass && c.unified_score != null ? Number(c.unified_score) : panelScore(c);
                const { tp, sl, rr } = computeTpSlRr(c);
                const modeLabel = c.mode === "trend_devam" ? "TREND" : c.mode === "v_donusu" ? "V-DÖNÜŞÜ" : "NÖTR";
                const modeClass = c.mode === "trend_devam" ? "bg-neon-green/15 text-neon-green border-neon-green/30" : c.mode === "v_donusu" ? "bg-yellow-400/15 text-yellow-300 border-yellow-400/30" : "bg-sky-400/15 text-sky-300 border-sky-400/30";

                return (
                  <div
                    key={c.symbol}
                    onClick={() => setSelected({ c, kind: "radar" })}
                    className="group flex flex-col lg:flex-row lg:items-center justify-between gap-3 w-full rounded-xl border border-bunker-800 bg-bunker-900/50 p-3.5 sm:px-5 sm:py-3.5 text-left transition-all hover:border-neon-green/50 hover:bg-bunker-900/90 cursor-pointer shadow-sm hover:shadow-md"
                  >
                    {/* Sol taraf: Sembol ve Rozetler */}
                    <div className="flex items-center justify-between lg:justify-start gap-3 min-w-0">
                      <div className="flex items-center gap-2.5">
                        <span className="w-6 text-center font-mono text-xs font-bold text-bunker-muted">#{i + 1}</span>
                        <span className="font-mono text-lg sm:text-base font-black text-white group-hover:text-neon-green transition-colors">
                          {c.symbol}
                        </span>

                        <span className={`shrink-0 rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold uppercase ${modeClass}`}>
                          {modeLabel}
                        </span>

                        {(unifiedSources.length >= 4 || c.confluence_4way) ? (
                          <span className="shrink-0 rounded-md border border-amber-400/60 bg-amber-400/20 px-2 py-0.5 font-mono text-[10px] font-black text-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.25)] animate-pulse" title="Master Surge: 4'lü Tam Mutabakat (Yüksek Hassasiyet)">
                            ⚡ 4&apos;lü Teyit (Master Surge)
                          </span>
                        ) : unifiedSources.length >= 2 ? (
                          <span className="shrink-0 rounded-md border border-neon-green/50 bg-neon-green/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-neon-green" title={`Çoklu Gösterge Teyidi: ${unifiedSources.length} sinyal destekliyor`}>
                            ⚡ {unifiedSources.length}&apos;li Teyit
                          </span>
                        ) : null}

                        {mlActive && (
                          <span className="shrink-0 rounded-md border border-violet-400/40 bg-violet-400/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-violet-300" title={`Yapay Zeka Tahmin Modeli: %${((c.ml_hit_probability ?? 0) * 100).toFixed(0)} Güven`}>
                            ML %{((c.ml_hit_probability ?? 0) * 100).toFixed(0)}
                          </span>
                        )}
                      </div>

                      {/* Mobil Üst Sağ Durum */}
                      <div className="lg:hidden flex items-center gap-2">
                        <StatusChip status={c.status} />
                        <span className={`font-mono text-xs font-black ${scoreColor(score)} bg-bunker-950 px-2 py-0.5 rounded border border-bunker-700`}>
                          {scoreText(score)}
                        </span>
                      </div>
                    </div>

                    {/* Sağ taraf: Fiyat, Hedef, TP/SL, R:R ve Butonlar */}
                    <div className="flex items-center justify-between lg:justify-end gap-3 sm:gap-6 pt-2 lg:pt-0 border-t lg:border-t-0 border-bunker-800/60 font-mono">
                      {/* Skor */}
                      <div className="hidden lg:block text-right min-w-[50px]">
                        <p className="text-[10px] text-bunker-muted">SKOR</p>
                        <p className={`text-sm font-black ${scoreColor(score)}`}>{scoreText(score)}</p>
                      </div>

                      {/* Fiyat */}
                      {c.price > 0 && (
                        <div className="text-left lg:text-right min-w-[70px]">
                          <p className="text-[10px] text-bunker-muted">FİYAT</p>
                          <p className="text-xs font-bold text-white">₺{formatPrice(c.price)}</p>
                        </div>
                      )}

                      {/* Beklenen Hedef */}
                      <div className="text-left lg:text-right min-w-[65px]">
                        <p className="text-[10px] text-bunker-muted">HEDEF</p>
                        <p className={`text-xs font-black ${validTarget ? "text-neon-green" : "text-bunker-muted"}`}>
                          {validTarget ? `+${targetPct.toFixed(1)}%` : "—"}
                        </p>
                      </div>

                      {/* TP | SL Seviyeleri */}
                      <div className="hidden md:block text-right min-w-[130px]">
                        <p className="text-[10px] text-bunker-muted">TP / SL</p>
                        <p className="text-xs text-white">
                          <span className="text-neon-green font-bold">{tp != null ? `₺${formatPrice(tp)}` : "—"}</span>
                          <span className="text-bunker-muted mx-1">/</span>
                          <span className="text-neon-red font-bold">{sl != null ? `₺${formatPrice(sl)}` : "—"}</span>
                        </p>
                      </div>

                      {/* R/R Oranı */}
                      <div className="hidden sm:block text-right min-w-[50px]">
                        <p className="text-[10px] text-bunker-muted">R:R</p>
                        <p className={`text-xs font-bold ${rr != null && rr >= 1.5 ? "text-neon-green" : rr != null && rr >= 1 ? "text-yellow-300" : "text-bunker-muted"}`}>
                          {rr != null ? `${rr.toFixed(2)}` : "—"}
                        </p>
                      </div>

                      {/* Durum Rozeti */}
                      <div className="hidden lg:block min-w-[80px] text-center">
                        <StatusChip status={c.status} />
                      </div>

                      {/* Aksiyon */}
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/charts?symbol=${encodeURIComponent(c.symbol)}`}
                          onClick={(e) => e.stopPropagation()}
                          className="ui-button ui-button-secondary py-1 px-3 text-xs flex items-center gap-1 hover:border-neon-green/60"
                          title="Grafiği aç"
                        >
                          <span>Grafik</span>
                        </Link>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {filteredCandidates.length > 0 && (
            <div className="pt-2 border-t border-bunker-800/80 flex flex-wrap items-center justify-between text-[11px] text-bunker-muted">
              <span>💡 Detaylı analiz ve zaman ufuklarını görmek için aday satırına tıklayın.</span>
              <span>Durumlar: <b className="text-neon-green">HEDEFE ULAŞTI</b> · <b className="text-yellow-300">KISMI</b> · <b className="text-bunker-muted">BEKLİYOR</b></span>
            </div>
          )}
        </section>
      )}

      {/* BÖLÜM 1.4: 💙 CANLI NABIZ — HAM KEŞİF (akıştan ham momentum; warm'ın ÜSTÜNDE — daha erken katman.
          Sadece backend pulse verisi doluysa render edilir; undefined/boşsa kart hiç çıkmaz.) */}
      {(activeTab === "candidates" || activeTab === "overview") && pulseList.length > 0 && (
        <section aria-labelledby="pulse-panel-title" className="card p-5 rounded-2xl border border-sky-400/40 bg-bunker-950/60 shadow-xl space-y-3">
          <div className="border-b border-bunker-800/80 pb-3">
            <h2 id="pulse-panel-title" className="font-mono text-lg font-black text-sky-300 flex flex-wrap items-center gap-2">
              <span>💙</span> CANLI NABIZ — HAM KEŞİF
              <span className="rounded-md border border-sky-400/60 bg-sky-400/15 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-sky-300">
                ONAYLANMADI
              </span>
            </h2>
            <p className="mt-1 text-xs text-bunker-muted">
              Akıştan ham momentum. Tarama/teyit beklenmeden gösterilir — gürültülü olabilir.
              Sembol adına veya GRAFİKTE AÇ'a tıklayınca grafik aynı sayfada açılır.
            </p>
          </div>

          <ul className="space-y-1.5">
            {pulseList.map((p) => {
              // Bayat örnek: 20 sn'den eski akış örneği soluk gösterilir.
              const stale = p.sample_age_sec != null && p.sample_age_sec > 20;
              return (
                <li
                  key={p.symbol}
                  title={stale ? "Bayat örnek — akış verisi eski" : undefined}
                  className={`flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-1.5 font-mono text-xs leading-tight ${stale ? "opacity-40" : ""}`}
                >
                  <span
                    aria-hidden="true"
                    className={`w-1.5 h-1.5 shrink-0 rounded-full ${stale ? "bg-bunker-600" : "bg-sky-400 animate-pulse"}`}
                  />
                  <Link
                    href={`/charts?symbol=${encodeURIComponent(p.symbol)}`}
                    title="Grafiği aç"
                    className="font-mono text-sm font-black text-white truncate hover:text-sky-300 hover:underline underline-offset-4"
                  >
                    {p.symbol}
                  </Link>
                  {(() => {
                    const badge = mtfBadge(p.macd_mtf);
                    return badge ? (
                      <span className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`} title={badge.title}>
                        {badge.label}
                      </span>
                    ) : null;
                  })()}
                  <span className={pulseReturnColor(p.return_20s_pct)}>
                    20s: <b className="font-bold">{formatPulseReturn(p.return_20s_pct)}</b>
                  </span>
                  <span className={pulseReturnColor(p.return_1m_pct)}>
                    1dk: <b className="font-bold">{formatPulseReturn(p.return_1m_pct)}</b>
                  </span>
                  <span className="text-bunker-muted">
                    {p.volume_burst != null ? `${p.volume_burst.toFixed(1)}× hacim` : "— hacim"}
                  </span>
                  <span className="ml-auto text-white">{p.price != null && p.price > 0 ? `₺${formatPrice(p.price)}` : "—"}</span>
                  <Link
                    href={`/charts?symbol=${encodeURIComponent(p.symbol)}`}
                    title="Grafiği aç"
                    className="ui-button ui-button-secondary shrink-0 py-1 px-2.5 text-[11px]"
                  >
                    GRAFİKTE AÇ
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {/* BÖLÜM 1.5: 🔥 ISINANLAR — ERKEN UYARI (onaylanmadı; yalnız ekranda erken görünürlük) */}
      {(activeTab === "candidates" || activeTab === "overview") && warmList.length > 0 && (
        <section aria-labelledby="warm-panel-title" className="card p-5 rounded-2xl border border-amber-400/40 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="border-b border-bunker-800/80 pb-3">
            <h2 id="warm-panel-title" className="font-mono text-lg font-black text-amber-300 flex flex-wrap items-center gap-2">
              <span>🔥</span> ISINANLAR — ERKEN UYARI
              <span className="rounded-md border border-amber-400/60 bg-amber-400/15 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-amber-300">
                ONAYLANMADI
              </span>
            </h2>
            <p className="mt-1 text-xs text-bunker-muted">
              Teyit eşiğine yaklaşan semboller. Bu liste işlem sinyali DEĞİLDİR.
              Sembol adına veya GRAFİKTE AÇ'a tıklayınca grafik aynı sayfada açılır.
            </p>
          </div>

          <div className="space-y-2">
            {warmList.map((w) => {
              const proximityPct = Math.round((w.warm_proximity ?? 0) * 100);
              const reasonLabel = w.warm_reason ? (WARM_REASON_LABEL[w.warm_reason] ?? w.warm_reason) : null;
              const profileLabel = w.profile ? (WARM_PROFILE_LABEL[w.profile] ?? w.profile) : null;
              const change = w.change_24h;
              return (
                <div
                  key={w.symbol}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-xl border border-bunker-800 bg-bunker-900/40 p-3 sm:px-4 font-mono text-xs"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Link
                      href={`/charts?symbol=${encodeURIComponent(w.symbol)}`}
                      title="Grafiği aç"
                      className="font-mono text-sm font-black text-white truncate hover:text-amber-300 hover:underline underline-offset-4"
                    >
                      {w.symbol}
                    </Link>
                    <span className="shrink-0 rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 font-bold text-amber-300" title="Teyit kapısına yakınlık">
                      %{proximityPct}
                    </span>
                    {reasonLabel && (
                      <span
                        className="rounded-md border border-bunker-700 bg-bunker-900/80 px-2 py-0.5 text-[10px] text-bunker-muted truncate max-w-[190px]"
                        title={w.warm_reason ?? undefined}
                      >
                        {reasonLabel}
                      </span>
                    )}
                    {(() => {
                      const badge = mtfBadge(w.macd_mtf);
                      return badge ? (
                        <span className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`} title={badge.title}>
                          {badge.label}
                        </span>
                      ) : null;
                    })()}
                  </div>

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:justify-end text-bunker-muted">
                    {w.price != null && w.price > 0 && <span className="text-white">₺{formatPrice(w.price)}</span>}
                    <span className={change == null ? "text-bunker-muted" : change >= 0 ? "text-neon-green" : "text-neon-red"}>
                      24s: {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
                    </span>
                    <span>
                      Hedef: <b className={w.target_pct != null ? "text-neon-green" : "text-bunker-muted"}>{w.target_pct != null ? `+${w.target_pct.toFixed(1)}%` : "—"}</b>
                    </span>
                    {profileLabel && (
                      <span className="shrink-0 rounded-md bg-bunker-800 px-2 py-0.5 text-[10px] text-bunker-muted">{profileLabel}</span>
                    )}
                    <Link
                      href={`/charts?symbol=${encodeURIComponent(w.symbol)}`}
                      title="Grafiği aç"
                      className="ui-button ui-button-secondary shrink-0 py-1 px-2.5 text-[11px]"
                    >
                      GRAFİKTE AÇ
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* BÖLÜM 2: 👁 İZLEME LİSTESİ (WATCHLIST) */}
      {(activeTab === "watchlist" || activeTab === "overview") && (
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-bunker-800/80 pb-3">
            <div>
              <h2 className="font-mono text-lg font-black text-yellow-300 flex items-center gap-2">
                <span>👁</span> İZLEMEYE ALINAN SEMBOLLER (WATCHLIST)
                <span className="rounded-full bg-yellow-400/20 text-yellow-300 border border-yellow-400/40 px-2 py-0.5 text-xs">
                  {state.watchlist.length}
                </span>
              </h2>
              <p className="mt-1 text-xs text-bunker-muted">
                Yüksek hareketlilik gösteren ancak eşik kriterlerinden birini (dar bant, düşük ATR veya zayıf eğim) henüz tamamlamamış olan takipteki semboller.
              </p>
            </div>
          </div>

          {state.watchlist.length === 0 ? (
            <div className="py-8 text-center text-bunker-muted font-mono text-sm">
              Şu anda izleme listesinde bekleyen sembol bulunmuyor.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {state.watchlist.map((w) => {
                const reason = blockReasonLabel(w.block_reason);
                const score = panelScore(w);
                return (
                  <button
                    key={w.symbol}
                    type="button"
                    onClick={() => setSelected({ c: w, kind: "watch" })}
                    className="flex items-center justify-between gap-3 rounded-xl border border-bunker-800 bg-bunker-900/40 p-3 text-left transition-all hover:border-yellow-400/50 hover:bg-bunker-900/80"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="font-mono text-base font-black text-white">{w.symbol}</span>
                      {reason && (
                        <span
                          className="rounded-md border border-neon-red/30 bg-neon-red/10 px-2 py-0.5 font-mono text-[10px] font-bold text-neon-red truncate max-w-[140px]"
                          title={w.block_reason ? `Ham Neden: ${w.block_reason}` : undefined}
                        >
                          {reason}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-3 font-mono">
                      {w.price > 0 && <span className="text-xs text-white">₺{formatPrice(w.price)}</span>}
                      <span className={`text-xs font-black ${scoreColor(score)} bg-bunker-950 px-2 py-1 rounded border border-bunker-800`}>
                        Skor: {scoreText(score)}
                      </span>
                      <span className="text-bunker-muted text-sm">›</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* BÖLÜM 3: 🔔 SON GÖNDERİLEN BİLDİRİMLER (BİLDİRİM GEÇMİŞİ) */}
      {(activeTab === "notifications" || activeTab === "overview") && (
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bunker-800/80 pb-3">
            <div>
              <h2 className="font-mono text-lg font-black text-sky-300 flex items-center gap-2">
                <span>🔔</span> SON GÖNDERİLEN BİLDİRİMLER
                <span className="rounded-full bg-sky-400/20 text-sky-300 border border-sky-400/40 px-2 py-0.5 text-xs">
                  {historyRows?.length ?? 0}
                </span>
              </h2>
              <p className="mt-1 text-xs text-bunker-muted">
                Radar ve birleşik sinyal motoru tarafından tespit edilip kullanıcıya push veya web arayüzüyle iletilen son uyarılar.
              </p>
            </div>

            {historyError && (
              <button type="button" onClick={() => { void loadHistory(); }} className="ui-button ui-button-secondary text-xs py-1 px-3">
                YENİDEN DENE
              </button>
            )}
          </div>

          {historyError ? (
            <p className="text-sm text-neon-red font-mono py-4">⚠ {historyError}</p>
          ) : historyRows == null ? (
            <p className="text-sm text-bunker-muted font-mono py-6 text-center">Bildirimler yükleniyor…</p>
          ) : historyRows.length === 0 ? (
            <div className="py-8 text-center text-bunker-muted font-mono text-sm">
              Henüz gönderilmiş bir bildirim bulunmuyor.
            </div>
          ) : (
            <div className="space-y-2">
              {historyRows.map((row, index) => {
                const score = numOrNull(row.score);
                const targetPct = numOrNull(row.target_pct);
                const ts = toMs(row.detected_at);
                const isPush = row.sent_via_push === true;

                return (
                  <div
                    key={`${row.symbol ?? "?"}-${row.detected_at ?? index}-${index}`}
                    className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-xl border border-bunker-800 bg-bunker-900/40 p-3 sm:px-4 sm:py-2.5 font-mono text-xs transition-colors hover:border-sky-400/40"
                    title={ts ? fmtDateTime(ts) : undefined}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-black text-sm text-white">{row.symbol ?? "—"}</span>
                      {targetPct != null && targetPct > 0 && (
                        <span className="rounded-md bg-neon-green/10 border border-neon-green/30 text-neon-green px-2 py-0.5 font-bold">
                          +{targetPct.toFixed(1)}% Hedef
                        </span>
                      )}
                      <span className="text-bunker-muted text-[11px]">
                        Skor: <b className={scoreColor(score)}>{scoreText(score)}</b>
                      </span>
                      {(() => {
                        const badge = llmVerdictBadge(row);
                        if (!badge) return null;
                        const reasonList = row.llm_reasons;
                        const tipParts: string[] = [];
                        if (reasonList?.summary) tipParts.push(reasonList.summary);
                        if (reasonList?.reasons?.length) tipParts.push(`Kanıt: ${reasonList.reasons.join(", ")}`);
                        if (reasonList?.trap_evidence?.length) tipParts.push(`Tuzak: ${reasonList.trap_evidence.join(", ")}`);
                        return (
                          <span
                            className={`rounded px-2 py-0.5 text-[10px] font-bold border ${badge.cls}`}
                            title={tipParts.length > 0 ? tipParts.join(" | ") : `LLM ikinci göz kararı: ${row.llm_verdict}`}
                          >
                            {badge.label}
                          </span>
                        );
                      })()}
                    </div>

                    <div className="flex items-center justify-between sm:justify-end gap-3 text-bunker-muted">
                      <span className={`rounded px-2 py-0.5 text-[10px] font-bold ${isPush ? "bg-neon-green/15 text-neon-green border border-neon-green/40" : "bg-bunker-800 text-bunker-muted"}`}>
                        {isPush ? "PUSH İLETİLDİ" : "PANEL UYARISI"}
                      </span>
                      <span className="text-xs">
                        <RelativeTime ts={row.detected_at} />
                      </span>
                      {row.symbol && (
                        <Link
                          href={`/charts?symbol=${encodeURIComponent(row.symbol)}`}
                          className="text-bunker-muted hover:text-white px-1.5 py-0.5 rounded border border-bunker-700 hover:border-neon-green/40 text-[11px]"
                        >
                          Grafik
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* DETAY MODALI */}
      {selected && <CandidateDetail c={selected.c} kind={selected.kind} onClose={() => setSelected(null)} />}

      {/* SKOR EŞİĞİ DÜZENLEME MODALI (ADMIN) */}
      {showScoreModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setShowScoreModal(false)}
        >
          <div
            className="card max-w-md w-full p-6 rounded-2xl border border-neon-green/40 bg-bunker-950 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
              <h3 className="font-mono text-base font-black text-white flex items-center gap-2">
                <span>🎯</span> RADAR BİLDİRİM EŞİĞİ
              </h3>
              <button
                type="button"
                onClick={() => setShowScoreModal(false)}
                className="text-bunker-muted hover:text-white font-mono text-sm"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-bunker-muted leading-relaxed">
              Bu eşik hem <b>bildirim gönderme şartını</b>, hem <b>Monitoring aday listesini</b> hem de <b>Raporlama merkezindeki başarı takibini</b> doğrudan belirler.
              Bu skorun altındaki zayıf sinyaller bildirilmez.
            </p>

            <div className="space-y-2">
              <label className="block text-xs font-mono text-white font-bold">
                MİNİMUM SKOR (0 - 100 Panel Puanı):
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={editScoreInput}
                  onChange={(e) => setEditScoreInput(e.target.value)}
                  className="w-full bg-bunker-900 border border-bunker-700 rounded-xl px-4 py-2 font-mono text-lg text-white font-bold text-center focus:border-neon-green/50 outline-none"
                  autoFocus
                />
              </div>
              <div className="flex gap-2 pt-1">
                {[50, 60, 70, 80, 90].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setEditScoreInput(String(preset))}
                    className={`flex-1 py-1 rounded-lg border font-mono text-xs transition-colors ${
                      editScoreInput === String(preset)
                        ? "border-neon-green/60 bg-neon-green/20 text-neon-green font-bold"
                        : "border-bunker-800 bg-bunker-900 text-bunker-muted hover:text-white"
                    }`}
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-bunker-800">
              <button
                type="button"
                onClick={() => setShowScoreModal(false)}
                className="ui-button ui-button-secondary text-xs py-2 px-4"
              >
                İPTAL
              </button>
              <button
                type="button"
                onClick={handleSaveScore}
                disabled={savingScore}
                className="ui-button ui-button-primary text-xs py-2 px-5 flex items-center gap-1.5"
              >
                {savingScore ? "KAYDEDİLİYOR…" : "KAYDET VE UYGULA"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

