"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../lib/api";
import { fmtDateTime, formatPrice, toMs } from "../lib/format";
import { useAuth } from "../lib/auth";
import { useLiveMessages } from "../lib/liveSocket";
import { mergeMacdDelta } from "../lib/macdSnapshot";

// R1-02: `min_score` artık BİLİNMİYOR olabilir (`null`) — başlangıçta backend
// varsayılanı (70) dahil hiçbir sabit uydurulmaz; sunucunun `effective_min_score`
// alanı tek kaynaktır.
type NotificationSettings = {
  enabled: boolean;
  min_score: number | null;
  min_target_pct: number | null;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
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
  atr_pct: number;
  mode: string;
  horizon_minutes: number;
  ml_target_pct: number | null;
  ml_hit_probability: number | null;
  block_reason?: string | null;
  profiles?: Record<string, ProfileInfo>;
};

type MonitoringState = {
  last_scan_at: number | null;
  scan_count: number;
  candidates: Candidate[];
  watchlist: Candidate[];
};

// R1-01: sunucu sağlık alanları (backend `monitoring.py:_monitoring_state`).
// `null` = alan gelmedi (henüz yüklenmedi / istek başarısız) → arayüz "—" gösterir,
// uydurma 0/yeşil üretmez.
type ServerHealth = {
  loop_active: boolean | null;
  data_ready: boolean | null;
  system_startup: boolean | null;
  next_scan_in_sec: number | null;
};

const EMPTY_HEALTH: ServerHealth = { loop_active: null, data_ready: null, system_startup: null, next_scan_in_sec: null };

// R1-01/R1-04: HTTP durumunu kullanıcıya gösterilebilir Türkçe mesaja çevir.
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
  };
};

const SCAN_INTERVAL_MS = 30_000;

// 🔔 Son bildirimler geçmişi satırı (/api/monitoring/notifications → { history: [...] }).
type NotificationRow = { symbol?: string; score?: number | null; target_pct?: number | null; detected_at?: number | null; sent_via_push?: boolean | null; mode?: string | null };

// Backend normalize_score cap'i (config.MONITORING_SCORE_NORM_CAP, env ile
// değişebilir; tipik ham skor 50-2000). Backend normalde `panel_score` alanını
// gönderir ve asıl kaynak ODUR — buradaki sabit yalnızca `panel_score`
// taşımayan eski/ara yanıtlar için emniyet ağıdır (H-21). Env değişirse
// ekrandaki fallback değer backend'den sapabilir; backend'in gönderdiği
// `panel_score` kullanıldığı sürece sapma olmaz.
const SCORE_NORM_CAP = 2000;

// YÜKSELİŞ EĞİLİMİ ADAYLARI: MACD MONITOR GÜÇ skoru eşiği ve en az 5/6 zaman
// diliminde yeşil histogram şartı (MACD MONITOR sayfasıyla aynı veri
// kaynağından; /api/macd-monitor).
//
// F-18: `strength` MUTLAK bir trend gücü DEĞİLDİR. Backend onu evren içi
// min-max ile 0-10'a normalize eder (macd_monitor.py) → evrenin EN GÜÇLÜ
// sembolü her turda tam 10.0 alır. Bu yüzden 9.8 = "ham skoru evren zirvesinin
// %2'si içinde" demektir; evren kompozisyonu değişince aynı ham veriyle liste
// değişir. Eşik bilinçli olarak korunuyor (davranış değişikliği replay
// gerektirir); yalnızca panel bunu "evren içi sıralama" olarak etiketler.
const RISING_MIN_STRENGTH = 9.8;
const RISING_MIN_GREEN = 5;
const MACD_TFS = ["1m", "3m", "5m", "15m", "30m", "1h"];
const MACD_TF_SHORT: Record<string, string> = { "1m": "1M", "3m": "3M", "5m": "5M", "15m": "15M", "30m": "30M", "1h": "1H" };

type RisingCandidate = {
  symbol: string;
  strength: number;
  green: number;
  dots: (boolean | null)[];
};

// Snapshot'tan eşiği geçen sembolleri çıkar (GÜÇ ≥ 9.8 VE en az 5/6 yeşil).
const extractRisingCandidates = (payload: any): RisingCandidate[] => {
  const symbols = payload?.symbols || {};
  const universe = Array.isArray(payload?.universe) && payload.universe.length
    ? payload.universe
    : Object.keys(symbols);
  const list: RisingCandidate[] = [];
  for (const sym of universe) {
    const row = symbols[sym] || {};
    const tfs = row.tfs || {};
    const dots = MACD_TFS.map((tf) => {
      const cell = tfs[tf];
      return cell ? Boolean(cell.green) : null;
    });
    const green = dots.filter((value) => value === true).length;
    const strength = Number(row.strength);
    if (!Number.isFinite(strength) || strength < RISING_MIN_STRENGTH) continue;
    if (green < RISING_MIN_GREEN) continue;
    list.push({ symbol: sym, strength, green, dots });
  }
  list.sort((a, b) => b.strength - a.strength || b.green - a.green);
  return list;
};

// SIRÇRAMA ADAYLARI: sıçrama skoru (0-100) ≥ eşik — kırılım/squeeze/hacim/agresör.
const JUMP_MIN = 60;
type JumpSig = { break?: boolean | null; state?: string | null; vol?: boolean | null };
type PreSig = { approach?: boolean; m1?: boolean; dip?: boolean };
type PreDetail = {
  proximity?: number | null;
  gap_atr?: number | null;
  m1_margin_atr?: number | null;
  dip_hist?: number | null;
  dip_delta?: number | null;
  transition?: boolean;
  squeeze_now?: boolean;
  as_of?: Record<string, number | null>;
};
type JumpCand = { symbol: string; jump: number; m5: JumpSig | null; m15: JumpSig | null; cvd: { buy_dominant?: boolean; buy_ratio?: number | null; whale_net?: number | null } | null; pre: PreSig | null };
type EarlyCand = {
  symbol: string;
  pre: PreSig;
  jump: number | null;
  earlyScore: number | null;
  detail: PreDetail | null;
};
const extractJumpCandidates = (payload: any): JumpCand[] => {
  const symbols = payload?.symbols || {};
  const universe = Array.isArray(payload?.universe) && payload.universe.length
    ? payload.universe
    : Object.keys(symbols);
  const threshold = Number(payload?.jump_min ?? JUMP_MIN);
  const list: JumpCand[] = [];
  for (const sym of universe) {
    const row = symbols[sym] || {};
    const jump = Number(row?.jump);
    if (!Number.isFinite(jump) || jump < threshold) continue;
    list.push({
      symbol: sym,
      jump,
      m5: row?.sigs?.["5m"] || null,
      m15: row?.sigs?.["15m"] || null,
      cvd: row?.cvd || null,
      pre: row?.pre || null,
    });
  }
  list.sort((a, b) => b.jump - a.jump);
  return list;
};

// ERKEN SİNYAL (YAKLAŞIYOR): kırılım öncesi öncüler — M5 zirveye yakın,
// M1 öncü kırılım, MACD dip dönüşü. Skor eşiği dolmadan haber verir.
// Sıralama artık `early_score` (0-100, TANIMLAYICI) öncelikli: skor yalnız
// adayları SIRALAR, hiçbir kapıyı açmaz/kapatmaz (eşik değildir).
const extractEarlyCandidates = (payload: any): EarlyCand[] => {
  const symbols = payload?.symbols || {};
  const universe = Array.isArray(payload?.universe) && payload.universe.length
    ? payload.universe
    : Object.keys(symbols);
  const list: EarlyCand[] = [];
  for (const sym of universe) {
    const row = symbols[sym] || {};
    const pre = row?.pre || {};
    if (!row?.pre_any) continue;
    const jump = Number(row?.jump);
    const earlyScore = Number(row?.early_score);
    list.push({
      symbol: sym,
      pre,
      jump: Number.isFinite(jump) ? jump : null,
      earlyScore: Number.isFinite(earlyScore) ? earlyScore : null,
      detail: row?.pre_detail || null,
    });
  }
  list.sort((a, b) => (b.earlyScore ?? -1) - (a.earlyScore ?? -1) || (b.jump ?? 0) - (a.jump ?? 0));
  return list;
};

const earlyFlagIcons = (pre: PreSig) => {
  const icons: { icon: string; title: string }[] = [];
  if (pre.approach) icons.push({ icon: "🎯", title: "M5 zirveye yaklaşıyor (≤0.5 ATR) + hacim/genişleme" });
  if (pre.m1) icons.push({ icon: "🕐", title: "M1 öncü kırılımı + M5 yeşil" });
  if (pre.dip) icons.push({ icon: "📈", title: "M5 MACD hist dip dönüşü" });
  return icons;
};

const jumpFlagIcons = (cand: JumpCand) => {
  const icons: { icon: string; title: string }[] = [];
  const push = (icon: string, title: string) => icons.push({ icon, title });
  if (cand.m5?.break) push("🚀", "M5: 20-bar yüksek kırılımı");
  if (cand.m15?.break) push("🚀", "M15: 20-bar yüksek kırılımı");
  if (cand.m5?.state === "expand") push("⚡", "M5: volatilite genişlemesi");
  if (cand.m15?.state === "expand") push("⚡", "M15: volatilite genişlemesi");
  if (cand.m5?.state === "squeeze") push("🧲", "M5: sıkışma — yay hazır");
  if (cand.m15?.state === "squeeze") push("🧲", "M15: sıkışma — yay hazır");
  if (cand.m5?.vol) push("🔥", "M5: hacim patlaması");
  if (cand.m15?.vol) push("🔥", "M15: hacim patlaması");
  if (cand.cvd?.buy_dominant) push("🐋", `Alıcı agresör baskın (oran ${Number(cand.cvd.buy_ratio ?? 0).toFixed(2)}${cand.cvd.whale_net ? ` · balina ${cand.cvd.whale_net > 0 ? "+" : ""}${cand.cvd.whale_net}` : ""})`);
  return icons;
};

// R1-08/R1-13: göreli zaman etiketi. "şimdi" İZOLE bir bileşen state'inde
// tutulur → yalnız bu küçük düğüm tazelenir, sayfanın tamamı yeniden render
// edilmez; render sırasında `Date.now()` çağırmak (impure) yasak.
const relativeLabel = (ms: number, nowMs: number): string => {
  const sec = Math.max(0, Math.round((nowMs - ms) / 1000));
  if (sec < 60) return `${sec} sn önce`;
  if (sec < 3600) return `${Math.round(sec / 60)} dk önce`;
  if (sec < 86400) return `${Math.round(sec / 3600)} sa önce`;
  return `${Math.round(sec / 86400)} gün önce`;
};

const RelativeTime = ({ ts, tickMs = 30_000 }: { ts: number | null | undefined; tickMs?: number }) => {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, tickMs);
    return () => clearInterval(timer);
  }, [tickMs]);
  const ms = toMs(ts);
  if (!ms || !now) return null;
  return <span className="text-bunker-muted"> · {relativeLabel(ms, now)}</span>;
};

// R1-13: "yaklaşma bazı N sn önce" (öncü yaşı) izole bileşende tazelenir.
const AgeBadge = ({ ageTs }: { ageTs: number | null | undefined }) => {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 5_000);
    return () => clearInterval(timer);
  }, []);
  const age = numOrNull(ageTs);
  if (age == null || !now) return null;
  const sec = Math.max(0, Math.round(now / 1000 - age));
  return <span className="font-mono text-[9px] text-sky-300/70" title="Yaklaşma öncüsünün yaşı (canlı)">· {sec}sn</span>;
};

// R1-01: sunucu sağlık rozeti. Değer yoksa "—" + nötr (yeşil 0 yok).
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
  return <span className={`rounded border px-2 py-0.5 font-mono text-[10px] font-bold ${HEALTH_TONE[tone]}`}>{label}: {text}</span>;
};

// Panel (0-100) ölçeği: admin eşiği ve bildirim skoru bu ölçekte; ham
// velocity_score (0-200+) arayüzde artık gösterilmez (2026-09-04).
// R1-07: skor BİLİNMİYORSA `null` döner — eskiden eksik skor `0`'a düşüp
// KIRMIZI basılıyordu ("değerlendirilmiş" izlenimi). Render'da `null → "—"`.
const panelScore = (c: { panel_score?: number | null; velocity_score?: number | null }): number | null => {
  if (c.panel_score != null) {
    const p = Number(c.panel_score);
    if (Number.isFinite(p)) return p;
  }
  // Fallback yalnız `panel_score` taşımayan yanıtlar için (H-21).
  if (c.velocity_score == null) return null;
  const raw = Number(c.velocity_score);
  if (!Number.isFinite(raw)) return null;
  return Math.round(100 * Math.min(1, raw / SCORE_NORM_CAP) * 10) / 10;
};

// Skor tonu: veri yok → nötr; yüksek → yeşil; orta → sarı; düşük → kırmızı.
const scoreColor = (score: number | null) =>
  score == null ? "text-bunker-muted" : score >= 70 ? "text-neon-green" : score >= 50 ? "text-yellow-300" : "text-neon-red";
const scoreText = (score: number | null) => (score == null ? "—" : score.toFixed(1));

// İzleme listesindeki sembolün aday olamama sebebi (velocity.py block_reason).
const blockReasonLabel = (reason?: string | null) => {
  if (!reason) return null;
  if (reason.startsWith("mfi_asiri_alim")) return "MFI aşırı alım";
  if (reason.startsWith("mfi_asiri_satim")) return "MFI aşırı satım";
  if (reason.startsWith("rsi_asiri_alim")) return "RSI aşırı alım";
  if (reason.startsWith("atr_yetersiz")) return "ATR yetersiz";
  if (reason.startsWith("bb_genisligi_yetersiz") || reason === "bb_verisi_yok") return "BB dar";
  if (reason === "yapisal_teyit_yok") return "Yapısal teyit yok";
  // R1-20: backend'in `diger` nedeni ayrı etiketlenir; bilinmeyen nedenler ham
  // kodla birlikte `title`da gösterilir (çağrı yerleri `block_reason`ı taşır).
  if (reason === "diger") return "Diğer neden";
  return "Kriter sağlanmadı";
};

const CandidateDetail = ({ c, kind, onClose }: { c: Candidate; kind: "radar" | "watch"; onClose: () => void }) => {
  const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
  const price = Number(c.price);
  const validTarget = Number.isFinite(targetPct) && targetPct > 0 && Number.isFinite(price) && price > 0;
  const expected = validTarget ? price * (1 + targetPct / 100) : null;
  const mlActive = Number(c.ml_target_pct) > 0 && c.ml_hit_probability != null;
  // R1-11: Escape ile kapanma + açılışta odak diyaloğa taşınır + kapanışta
  // odağı eski sahibine geri verir (klavye-only erişilebilirlik).
  const dialogRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const previous = typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null;
    dialogRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus?.();
    };
  }, [onClose]);
  const trapFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (!nodes || nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  const score = panelScore(c);
  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="candidate-detail-title">
      <section
        ref={dialogRef}
        tabIndex={-1}
        onKeyDown={trapFocus}
        className="w-full max-w-sm rounded-xl border border-neon-green/40 bg-bunker-950 shadow-2xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-bunker-800 bg-neon-green/5 px-5 py-4">
          <div>
            <p className="eyebrow text-neon-green/80">{kind === "radar" ? "RADAR ADAYI" : "İZLEME ÖĞESİ"}</p>
            <h2 id="candidate-detail-title" className="font-mono text-lg font-bold text-white">{c.symbol}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Kapat" className="text-bunker-muted hover:text-white">✕</button>
        </div>
        <div className="grid grid-cols-2 gap-3 p-5">
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">SKOR</p>
            <p className={`mt-1 font-mono text-lg font-bold ${scoreColor(score)}`}>{scoreText(score)}</p>
          </div>
          <div className="rounded-lg border border-neon-green/30 bg-neon-green/5 px-3 py-2 text-center">
            <p className="eyebrow">HEDEF (5/15dk)</p>
            <p className={`mt-1 font-mono text-lg font-bold ${validTarget ? "text-neon-green" : "text-bunker-muted"}`}>{validTarget ? `+%${targetPct.toFixed(1)}` : "—"}</p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">ANLIK</p>
            <p className="mt-1 font-mono text-sm font-bold text-white">{formatPrice(price)} <span className="text-[10px] text-bunker-muted">TRY</span></p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">BEKLENEN</p>
            <p className="mt-1 font-mono text-sm font-bold text-neon-green">{expected != null ? formatPrice(expected) : "—"}</p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">ML OLASILIK</p>
            <p className={`mt-1 font-mono text-sm font-bold ${mlActive ? (Number(c.ml_hit_probability) >= 0.6 ? "text-neon-green" : "text-yellow-300") : "text-bunker-muted"}`}>
              {mlActive ? `%${Math.round(Number(c.ml_hit_probability) * 100)}` : "—"}
            </p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">UFUK</p>
            <p className="mt-1 font-mono text-sm font-bold text-white">{c.horizon_minutes ? `${c.horizon_minutes}dk` : "—"}</p>
          </div>
        </div>
        {c.profiles && Object.keys(c.profiles).length > 0 && (
          <div className="border-t border-bunker-800 px-5 py-3">
            <p className="eyebrow mb-2">HIZ PROFİLLERİ</p>
            <div className="space-y-1.5">
              {Object.values(c.profiles).map((p) => (
                <div key={p.horizon_minutes} className={`flex items-center justify-between rounded border px-2.5 py-1.5 font-mono text-[11px] ${p.passes ? "border-neon-green/30 bg-neon-green/5" : "border-bunker-800 bg-bunker-900/40"}`}>
                  <span className="font-bold text-white">{p.horizon_minutes}dk</span>
                  <span className="text-bunker-muted">hedef <b className={p.target_pct == null ? "text-bunker-muted" : "text-neon-green"}>{p.target_pct == null ? "—" : `+%${Number(p.target_pct).toFixed(1)}`}</b></span>
                  <span className="text-bunker-muted">skor <b className="text-white">{scoreText(panelScore({ velocity_score: p.velocity_score }))}</b></span>
                  <span className={p.passes ? "text-neon-green" : "text-neon-red"} title={p.block_reason ? `Ham neden: ${p.block_reason}` : undefined}>{p.passes ? "GEÇTİ" : (blockReasonLabel(p.block_reason) ?? "İZLE")}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="flex justify-between border-t border-bunker-800 px-5 py-3">
          <span className={`rounded px-2 py-0.5 text-xs font-mono ${c.mode === "trend_devam" ? "bg-neon-green/15 text-neon-green" : c.mode === "v_donusu" ? "bg-yellow-400/15 text-yellow-300" : "bg-sky-400/15 text-sky-300"}`}>
            {c.mode === "trend_devam" ? "TREND" : c.mode === "v_donusu" ? "V-DÖNÜŞÜ" : "NÖTR"}
          </span>
          <div className="flex gap-2">
            <Link href={`/charts?symbol=${c.symbol}`} className="ui-button ui-button-secondary">GRAFİK</Link>
            <button type="button" onClick={onClose} className="ui-button ui-button-primary">TAMAM</button>
          </div>
        </div>
      </section>
    </div>
  );
};

export default function MonitoringPage() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [state, setState] = useState<MonitoringState>({ last_scan_at: null, scan_count: 0, candidates: [], watchlist: [] });
  const [effectiveMinScore, setEffectiveMinScore] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  // R1-02: eşik/ayar başlangıçta BİLİNMİYOR (`null`) — eski istemci sabiti
  // `min_score: 50` backend varsayılanı 70 ile çelişiyordu ve fetch başarısız
  // olursa kalıcı yanlış eşik gösteriliyordu. Tek kaynak sunucunun
  // `effective_min_score` / `monitoring_min_score_panel` alanlarıdır.
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [thresholds, setThresholds] = useState<{ panel: number | null; raw: number | null }>({ panel: null, raw: null });
  // R1-01: sunucu sağlığı + okuma hataları artık GÖRÜNÜR (yutulmaz).
  const [health, setHealth] = useState<ServerHealth>(EMPTY_HEALTH);
  const [stateError, setStateError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [stateLoaded, setStateLoaded] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  // R1-04: tarama tetikleme sonucu (önbellek/yetki/hata) kullanıcıya bildirilir.
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ c: Candidate; kind: "radar" | "watch" } | null>(null);
  const [minScoreInput, setMinScoreInput] = useState<string>("");
  const [minScoreDirty, setMinScoreDirty] = useState(false);
  const [savingMinScore, setSavingMinScore] = useState(false);
  // Global admin ayarları (bildirim kartı): hedef % ve sessiz saatler.
  const [targetPctInput, setTargetPctInput] = useState<string>("");
  const [quietStart, setQuietStart] = useState<string>("");
  const [quietEnd, setQuietEnd] = useState<string>("");
  const [savingSettings, setSavingSettings] = useState(false);
  // 🔔 Son bildirimler geçmişi (null = henüz yüklenmedi).
  const [historyRows, setHistoryRows] = useState<NotificationRow[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  // 🩺 Teşhis kartı (yalnız admin).
  const [diag, setDiag] = useState<Record<string, any> | null>(null);
  const [diagError, setDiagError] = useState<string | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);

  // R1-06/R1-10: istek nesli + in-flight kapıları. Yalnız EN YENİ neslin yanıtı
  // uygulanır (last-write-wins yarışı) ve unmount sonrası yazım yapılmaz.
  const stateReqIdRef = useRef(0);
  const stateInFlightRef = useRef(false);
  const scanInFlightRef = useRef(false);
  const macdReqIdRef = useRef(0);
  const mountedRef = useRef(true);
  // R1-16: poll aralığı sabit 30 sn yerine sunucunun `next_scan_in_sec`ine hizalanır.
  const nextPollMsRef = useRef(SCAN_INTERVAL_MS);

  // YÜKSELİŞ/SIRÇRAMA ADAYLARI (MACD MONITOR beslemesi): REST 15 sn poll +
  // WS macd_monitor mesajıyla anlık tazeleme; iki panel aynı payload'dan türer.
  const [macdData, setMacdData] = useState<any>(null);
  // R1-03: besleme hatası görünür duruma bağlanır; `macdData === null` ile
  // "hiç aday yok" ayrımı korunur ve 3 panel sessizce kaybolmaz.
  const [macdError, setMacdError] = useState<string | null>(null);
  const loadMacd = useCallback(async (signal?: AbortSignal) => {
    const reqId = ++macdReqIdRef.current;
    try {
      const res = await apiRequest(`${API_BASE}/api/macd-monitor`, { cache: "no-store", signal });
      if (reqId !== macdReqIdRef.current || !mountedRef.current) return;
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (reqId !== macdReqIdRef.current || !mountedRef.current) return;
      if (!data || !data.symbols) {
        setMacdError("MACD MONITOR yanıtı boş (sembol verisi yok).");
        return;
      }
      setMacdData(data);
      setMacdError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current || reqId !== macdReqIdRef.current) return;
      setMacdError(`MACD MONITOR verisi alınamadı (${humanizeError(err)})`);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void loadMacd(controller.signal);
    const timer = window.setInterval(() => { if (!document.hidden) void loadMacd(controller.signal); }, 15_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [loadMacd]);

  // R1-01/R1-02: tek noktadan /api/monitoring/* yanıtını uygula (state + sağlık +
  // ayar/eşik). `candidates`/`watchlist` dizi değilse BOŞ diziye düşürülür (nesne
  // gelirse render'da `.filter` throw ediyordu — bkz. R1 §5).
  const applyMonitoringPayload = useCallback((data: any) => {
    setState({
      last_scan_at: data?.last_scan_at ?? data?.scan_at ?? null,
      scan_count: numOrNull(data?.scan_count) ?? 0,
      candidates: Array.isArray(data?.candidates) ? data.candidates : [],
      watchlist: Array.isArray(data?.watchlist) ? data.watchlist : [],
    });
    setHealth({
      loop_active: boolOrNull(data?.loop_active),
      data_ready: boolOrNull(data?.data_ready),
      system_startup: boolOrNull(data?.system_startup),
      next_scan_in_sec: numOrNull(data?.next_scan_in_sec),
    });
    const parsed = parseSettings(data?.settings);
    if (parsed) setSettings(parsed);
    setEffectiveMinScore(numOrNull(data?.effective_min_score));
    // M1 sözleşmesi: `monitoring_min_score_panel` / `monitoring_min_raw_score`
    // gönderildiğinde eşik panelde AYNEN gösterilir (ham eşik de yanında).
    const panel = numOrNull(data?.monitoring_min_score_panel ?? data?.settings?.monitoring_min_score_panel);
    const raw = numOrNull(data?.monitoring_min_raw_score ?? data?.settings?.monitoring_min_raw_score);
    if (panel != null || raw != null) setThresholds({ panel, raw });
    setStateError(null);
    setStateLoaded(true);
    setLastUpdatedAt(Date.now());
    const nextIn = numOrNull(data?.next_scan_in_sec);
    nextPollMsRef.current = nextIn != null ? Math.max(15_000, Math.round(nextIn) * 1000) : SCAN_INTERVAL_MS;
  }, []);

  // F-15 (frontend yarısı): SALT-OKUNUR tarama durumu okuyucu. Sayfa otomatik
  // olarak yan etkili `/api/monitoring/scan` ÇAĞIRMAZ (o uç tam tarama + DB yazımı
  // + web push + otonom paper pozisyon açma yapar). Taze tarama yalnız adminin
  // "ŞİMDİ TARA" düğmesiyle (runScan) tetiklenir.
  const loadState = useCallback(async (signal?: AbortSignal) => {
    // R1-18: önceki istek hâlâ uçtaysa üst üste binme; taze tarama sürerken
    // de poll başlamaz (tarama sonucunu ezmesin — R1-06).
    if (stateInFlightRef.current || scanInFlightRef.current) return;
    stateInFlightRef.current = true;
    const reqId = ++stateReqIdRef.current;
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store", signal });
      if (reqId !== stateReqIdRef.current || !mountedRef.current) return;
      // H-27: boş gövdeli/hata yanıtı `json()` throw edip sessizce yutuluyordu
      // ("veri yok" gibi görünüyordu) → önce `ok` kontrolü.
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (reqId !== stateReqIdRef.current || !mountedRef.current) return;
      applyMonitoringPayload(data);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current || reqId !== stateReqIdRef.current) return;
      // R1-01: hata artık YUTULMAZ — görünür şerit + "yeniden dene".
      setStateError(humanizeError(err));
    } finally {
      stateInFlightRef.current = false;
    }
  }, [applyMonitoringPayload]);

  // 🔔 Son bildirimler geçmişi: ilk 10 satır; WS monitoring_alert ile tazelenir.
  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/notifications`, { cache: "no-store", signal });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current) return;
      const list: NotificationRow[] = Array.isArray(data?.history) ? data.history : [];
      setHistoryRows(list.slice(0, 10));
      setHistoryError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current) return;
      setHistoryError(humanizeError(err));
    }
  }, []);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "macd_monitor" && message.data) {
      setMacdData(message.data);
      // WS tam snapshot beslemenin sağlıklı olduğunu kanıtlar → REST hatası bayat.
      setMacdError(null);
    }
    // Delta yayını da birleştirilmeli (B9): backend çoğu turda yalnızca DEĞİŞEN
    // sembolleri yayınlar; yalnız `macd_monitor` dinlenirse panel her 5. pass'a
    // (≈5 sn) düşer. R1-05: `mergeMacdDelta` değişiklik yoksa AYNI referansı
    // döner → üç `useMemo` boşuna (tüm evrende) yeniden hesaplanmaz.
    if (message.type === "macd_monitor_delta" && message.data?.symbols) {
      setMacdData((prev: any) => mergeMacdDelta(prev, message.data));
      setMacdError(null);
    }
    // H-20/R1-14: arka plan taraması yeni radar bildirimi yayınladığında aday
    // listesi + sağlık alanları anında tazelenir (tek okuma yolu).
    if (message.type === "monitoring_alert") { void loadState(); void loadHistory(); }
  }, [loadState, loadHistory]);
  useLiveMessages(onLiveMessage);
  const rising = useMemo(() => extractRisingCandidates(macdData), [macdData]);
  const jumpers = useMemo(() => extractJumpCandidates(macdData), [macdData]);
  const earlyCands = useMemo(() => extractEarlyCandidates(macdData), [macdData]);
  const jumpThreshold = Number(macdData?.jump_min ?? JUMP_MIN);

  // Admin girişteyken poll inputu ezmesin: yalnız düzenlenmemişken (dirty
  // değilken) ve ayar YÜKLENDİĞİNDE sunucu değeriyle senkronlanır.
  // Global admin ayar kartı girdileri (hedef %, sessiz saatler) da burada senkron.
  useEffect(() => {
    if (!settings) return;
    if (!minScoreDirty && settings.min_score != null) setMinScoreInput(String(Math.round(settings.min_score)));
    setTargetPctInput(settings.min_target_pct != null ? String(settings.min_target_pct) : "");
    setQuietStart(settings.quiet_hours_start ?? "");
    setQuietEnd(settings.quiet_hours_end ?? "");
  }, [settings, minScoreDirty]);

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

  // Genel ayar kaydedici: tüm global admin ayar güncellemeleri bu yoldan gider.
  const putSettings = useCallback(async (patch: Record<string, unknown>, okMessage: string) => {
    setSavingMinScore(true);
    setSavingSettings(true);
    setSettingsError(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      // R1-04: yetki/oturum hataları sessizce yutulmaz.
      if (res.status === 401 || res.status === 403) { setSettingsError("Ayarları yalnız yönetici değiştirebilir — yetkiniz yok."); return; }
      if (!res.ok) throw new HttpStatusError(res.status);
      if (okMessage) setScanNote(okMessage);
      await loadSettings();
    } catch (err) {
      if (!mountedRef.current) return;
      setSettingsError(`Ayar kaydedilemedi: ${humanizeError(err)}`);
    } finally {
      if (mountedRef.current) { setSavingMinScore(false); setSavingSettings(false); }
    }
  }, [loadSettings]);

  const saveMinScore = useCallback(async () => {
    const val = Number(minScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) {
      setSettingsError("Eşik 0-100 arasında bir sayı olmalı.");
      return;
    }
    setMinScoreDirty(false);
    await putSettings({ min_score: val }, "Eşik kaydedildi.");
  }, [minScoreInput, putSettings]);

  // 🩺 Teşhis: yalnız admin uç noktası (403 → humanizeError yetki mesajı verir).
  const loadDiag = useCallback(async () => {
    setDiagLoading(true);
    setDiagError(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/diagnostics`, { cache: "no-store" });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current) return;
      setDiag(data && typeof data === "object" ? data : null);
    } catch (err) {
      if (!mountedRef.current) return;
      setDiagError(humanizeError(err));
    } finally {
      if (mountedRef.current) setDiagLoading(false);
    }
  }, []);

  // 🧹 Bildirim spam koruması sıfırlama (yalnız admin).
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

  // R1-04: tarama tetikleme artık POST (GET salt-okunur; M1 sözleşmesi). Cached
  // yanıt TAZE tarama değildir: sayaçlar/last_scan_at güncellenmez, kullanıcıya
  // bilgi verilir. 401/403'te net "yetkiniz yok" mesajı gösterilir.
  const runScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setScanNote(null);
    // Tarama sürerken poll başlamasın (sonucu ezmesin) + nesil yalnız tarama olsun.
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
        setScanNote("Tarama tamamlandı.");
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
    const controller = new AbortController();
    void loadSettings(controller.signal);
    void loadState(controller.signal);
    void loadHistory(controller.signal);
    // R1-16/R1-18: poll `next_scan_in_sec`e hizalanır; arka planda atlanır,
    // sekmeye dönünce hemen tazelenir. Tek timeout zinciri → üst üste binmez.
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
    const onVisibility = () => { if (!document.hidden) void loadState(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      mountedRef.current = false;
      controller.abort();
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [loadState, loadSettings, loadHistory]);

  // R1-02/R1-09: TEK eşik kaynağı sunucunun etkin eşiğidir. Sunucudan gelene
  // kadar "—" gösterilir; istemci sabiti (eski 50) KALDIRILDI. M1 ile gelen
  // `monitoring_min_score_panel` varsa yedek olarak kullanılır.
  const effThreshold = effectiveMinScore ?? thresholds.panel;
  const rawThreshold = thresholds.raw;
  // R1-09: istemci yan-eşik filtresi KALDIRILDI — tek doğruluk kaynağı backend
  // (`monitoring.py` `panel_score >= effective_min_score`). İstemci `panelScore`
  // fallback'iyle ikinci kez filtrelemek, `MONITORING_SCORE_NORM_CAP` env ile
  // değişince backend'in tuttuğu adayı gizleyebiliyordu.
  const candidates = state.candidates;

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">RADAR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Otonom İzleme</h1>
          <p className="mt-1 text-sm text-bunker-muted">Yüksek potansiyelli sembolleri tarar, uygun olanları bildirir.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Tek eşik (2026-09-04): RISK_OFF çarpanı kaldırıldı; admin'in
              girdiği değer her yerde aynen uygulanır ve gösterilir.
              R1-02: sunucudan etkin eşik gelene kadar "—" (uydurma 50 YOK). */}
          <span className="ui-button ui-button-secondary pointer-events-none" title="Radar, bildirim ve raporlarda uygulanan global eşik (kaynak: sunucu)">
            ⚖️ EŞİK: SKOR ≥ {effThreshold != null ? effThreshold : "—"} · GLOBAL
            {rawThreshold != null ? ` (ham ≥ ${rawThreshold})` : ""}
          </span>
          {/* Eşik girişi/kaydetme "⚙️ BİLDİRİM AYARLARI · GLOBAL (YÖNETİCİ)"
              kartına taşındı (aşağıda); başlıkta yalnız salt-okunur rozet kalır. */}
          {/* R1-04: taze tarama YALNIZ yetkiliye (admin) gösterilir; aksi halde
              buton tüm rollere açıkken backend `cached:true` döndürüp bayat veri
              "taze tarama" gibi sunuluyordu. Yetkisiz kullanıcıya net mesaj. */}
          {isAdmin ? (
            <button onClick={runScan} disabled={scanning} className="ui-button ui-button-primary">{scanning ? "TARANIYOR…" : "ŞİMDİ TARA"}</button>
          ) : (
            <span className="ui-button ui-button-secondary pointer-events-none font-mono" title="Taze taramayı yalnız yönetici tetikleyebilir">
              🔒 ŞİMDİ TARA: yetkiniz yok
            </span>
          )}
        </div>
      </div>

      {/* Bildirim ayarları artık global admin ayarıdır; kullanıcı paneli kaldırıldı (2026-09-04).
          Ayar yalnız admin tarafından, /api/monitoring/settings PUT üzerinden değiştirilebilir. */}

      {/* R1-01: okuma hatası GÖRÜNÜR — "her şey yolunda" sanılmasın. */}
      {(stateError || settingsError) && (
        <div role="alert" className="card flex flex-wrap items-center justify-between gap-3 border-neon-red/40 bg-neon-red/5">
          <p className="text-sm text-neon-red">
            ⚠ {stateError ?? settingsError}
            {lastUpdatedAt != null && <span className="text-bunker-muted"> · son başarılı okuma: {fmtDateTime(lastUpdatedAt)}</span>}
          </p>
          <button type="button" onClick={() => { void loadSettings(); void loadState(); }} className="ui-button ui-button-secondary">YENİDEN DENE</button>
        </div>
      )}

      {scanError && (
        <div role="alert" className="card border-neon-red/40 bg-neon-red/5">
          <p className="text-sm text-neon-red">⚠ {scanError}</p>
        </div>
      )}
      {scanNote && !scanError && (
        <div role="status" className="card border-neon-green/30 bg-neon-green/5">
          <p className="text-sm text-neon-green">✓ {scanNote}</p>
        </div>
      )}

      {/* R1-01: sunucu sağlığı — `loop_active`/`data_ready`/`system_startup`
          backend'de mevcuttu ama arayüz hiçbirini okumuyordu. Değer yoksa "—". */}
      <section className="card" aria-label="Sunucu sağlık durumu">
        <p className="eyebrow">SUNUCU DURUMU</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <HealthChip label="Tarama döngüsü" value={health.loop_active} onText="AKTİF" offText="DURDU" onTone="good" offTone="bad" />
          <HealthChip label="Veri hazır" value={health.data_ready} onText="HAZIR" offText="YOK" onTone="good" offTone="warn" />
          <HealthChip label="Sistem başlangıcı" value={health.system_startup} onText="YENİ BAŞLADI" offText="OTURDU" onTone="warn" offTone="good" />
          {health.next_scan_in_sec != null && (
            <span className="font-mono text-[11px] text-bunker-muted">sonraki tarama ~{health.next_scan_in_sec} sn</span>
          )}
          {lastUpdatedAt != null && (
            <span className="font-mono text-[11px] text-bunker-muted">son okuma<RelativeTime ts={lastUpdatedAt} /></span>
          )}
        </div>
      </section>

      {/* ⚙️ GLOBAL ADMIN AYARLARI: eşik, bildirim aç/kapa, min hedef %, sessiz
          saatler + bildirim spam koruması sıfırlama. Yalnız admin görür; tüm
          yazım PUT /api/monitoring/settings üzerinden gider. */}
      {isAdmin && (
        <section className="card" aria-label="Global bildirim ayarları (yönetici)">
          <p className="eyebrow text-neon-green">⚙️ BİLDİRİM AYARLARI · GLOBAL (YÖNETİCİ)</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div>
              <p className="eyebrow text-bunker-muted">MİN SKOR (0-100)</p>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={minScoreInput}
                onChange={(e) => { setMinScoreInput(e.target.value); setMinScoreDirty(true); }}
                title="Admin eşiği: radar listesi, bildirim, rapor ve otonom taramada aynen uygulanır"
                placeholder="—"
                className="mt-1 w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
              />
            </div>
            <button
              onClick={saveMinScore}
              disabled={savingMinScore || !minScoreDirty || !minScoreInput || Number(minScoreInput) < 0 || Number(minScoreInput) > 100}
              className="ui-button ui-button-primary"
            >
              {savingMinScore ? "KAYDEDİLİYOR…" : "EŞİĞİ KAYDET"}
            </button>
            <button
              onClick={() => { setMinScoreDirty(false); void putSettings({ min_score: null }, "Eşik varsayılana sıfırlandı."); }}
              disabled={savingMinScore || settings?.min_score == null}
              title="Varsayılan ham eşik değerine dön (sunucu MONITORING_MIN_RAW_SCORE)"
              className="ui-button ui-button-secondary"
            >
              SIFIRLA
            </button>

            <div>
              <p className="eyebrow text-bunker-muted">BİLDİRİMLER</p>
              <button
                onClick={() => void putSettings({ enabled: !settings?.enabled }, settings?.enabled ? "Bildirimler kapatıldı." : "Bildirimler açıldı.")}
                disabled={savingMinScore || settings == null}
                title="Global bildirim anahtarı (tüm kullanıcılara uygulanır)"
                className={`ui-button ui-button-secondary mt-1 font-mono ${settings?.enabled ? "text-neon-green" : "text-neon-red"}`}
              >
                {settings?.enabled ? "AÇIK" : "KAPALI"}
              </button>
            </div>

            <div>
              <p className="eyebrow text-bunker-muted">MİN HEDEF %</p>
              <input
                type="number"
                min={0}
                max={50}
                step={0.1}
                value={targetPctInput}
                onChange={(e) => setTargetPctInput(e.target.value)}
                title="Bildirim için gereken en düşük hedef yüzdesi"
                placeholder="—"
                className="mt-1 w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
              />
            </div>
            <button
              onClick={() => {
                const val = Number(targetPctInput);
                if (!Number.isFinite(val) || val < 0) { setSettingsError("Min hedef % geçersiz."); return; }
                void putSettings({ min_target_pct: val }, "Min hedef % kaydedildi.");
              }}
              disabled={savingMinScore || !targetPctInput || (settings?.min_target_pct != null ? Number(targetPctInput) === settings.min_target_pct : false)}
              className="ui-button ui-button-primary"
            >
              {savingMinScore ? "KAYDEDİLİYOR…" : "KAYDET"}
            </button>

            <div>
              <p className="eyebrow text-bunker-muted">SESSİZ SAATLER</p>
              <div className="mt-1 flex items-center gap-1.5">
                <input
                  type="time"
                  value={quietStart}
                  onChange={(e) => setQuietStart(e.target.value)}
                  title="Bildirim sessiz saati başlangıcı"
                  className="bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                />
                <span className="font-mono text-xs text-bunker-muted">→</span>
                <input
                  type="time"
                  value={quietEnd}
                  onChange={(e) => setQuietEnd(e.target.value)}
                  title="Bildirim sessiz saati bitişi"
                  className="bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                />
              </div>
            </div>
            <button
              onClick={() => {
                if ((quietStart && !quietEnd) || (!quietStart && quietEnd)) {
                  setSettingsError("Sessiz saat başlangıç ve bitiş birlikte girilmeli.");
                  return;
                }
                void putSettings({ quiet_hours_start: quietStart || null, quiet_hours_end: quietEnd || null }, "Sessiz saatler kaydedildi.");
              }}
              disabled={savingMinScore}
              className="ui-button ui-button-primary"
            >
              {savingMinScore ? "KAYDEDİLİYOR…" : "KAYDET"}
            </button>

            <button
              onClick={() => void resetNotifications()}
              disabled={savingSettings}
              title="Aynı semboller yeniden bildirilebilir — spam koruması sıfırlanır"
              className="ui-button ui-button-secondary"
            >
              BİLDİRİM SIFIRLA
            </button>
          </div>
        </section>
      )}

      {/* 🩺 TEŞHİS: sunucu iç durumu (yalnız admin; uç nokta 403 verebilir). */}
      {isAdmin && (
        <details className="card">
          <summary className="eyebrow cursor-pointer">🩺 TEŞHİS (YÖNETİCİ)</summary>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button onClick={() => void loadDiag()} disabled={diagLoading} className="ui-button ui-button-primary">
              {diagLoading ? "YÜKLENİYOR…" : "YENİLE"}
            </button>
            {diagError && <p className="text-sm text-neon-red">⚠ {diagError}</p>}
          </div>
          {diag && (
            <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {(() => {
                const rateLimiter = diag.rate_limiter;
                const rateLimiterText = rateLimiter == null ? "—"
                  : typeof rateLimiter === "string" ? rateLimiter
                  : (() => { const s = JSON.stringify(rateLimiter); return s.length > 120 ? `${s.slice(0, 120)}…` : s; })();
                const rows: { label: string; value: string }[] = [
                  { label: "Tarama sayısı", value: numOrNull(diag.scan_count) != null ? String(numOrNull(diag.scan_count)) : "—" },
                  { label: "Son tarama", value: diag.last_scan_at != null ? fmtDateTime(diag.last_scan_at) : "—" },
                  { label: "Etkin eşik", value: numOrNull(diag.effective_min_score) != null ? String(numOrNull(diag.effective_min_score)) : "—" },
                  { label: "WS bağlantı", value: numOrNull(diag.ws_health?.active_connections) != null ? String(numOrNull(diag.ws_health?.active_connections)) : "—" },
                  { label: "WS son hata", value: diag.ws_health?.ws_last_error ? String(diag.ws_health.ws_last_error) : "—" },
                  { label: "Önbellek mum", value: numOrNull(diag.memory_metrics?.total_cached_klines) != null ? String(numOrNull(diag.memory_metrics?.total_cached_klines)) : "—" },
                  { label: "Bildirim gecikme (ort, ms)", value: numOrNull(diag.db_latency?.avg_notify_ms) != null ? String(numOrNull(diag.db_latency?.avg_notify_ms)) : "—" },
                  { label: "Rate limiter", value: rateLimiterText },
                ];
                return rows.map((row) => (
                  <div key={row.label} className="flex items-baseline justify-between gap-3 border-b border-bunker-800/60 py-1">
                    <span className="text-xs text-bunker-muted">{row.label}</span>
                    <span className="truncate font-mono text-xs text-white" title={row.value}>{row.value}</span>
                  </div>
                ));
              })()}
            </div>
          )}
        </details>
      )}

      {/* R1-08/R1-14: kartlar dar ekranda tek kolon; "Son Tarama" artık TARİH+SAAT
          (dünkü tarama taze sanılmasın) + göreli etiket; sayaçlar sunucudan veri
          gelmeden "—" (0/yeşil ile "sağlıklı" izlenimi vermez). */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="card">
          <p className="eyebrow">Son Tarama</p>
          <p className={`mt-2 font-mono text-lg ${state.last_scan_at != null ? "text-white" : "text-bunker-muted"}`}>
            {fmtDateTime(state.last_scan_at)}
            <RelativeTime ts={state.last_scan_at} />
          </p>
        </div>
        <div className="card">
          <p className="eyebrow">Tarama Sayısı</p>
          <p className={`mt-2 font-mono text-lg ${stateLoaded && !stateError ? "text-white" : "text-bunker-muted"}`}>{stateLoaded ? state.scan_count : "—"}</p>
        </div>
        <div className="card">
          <p className="eyebrow">Aday Sayısı</p>
          <p className={`mt-2 font-mono text-lg ${stateLoaded && !stateError ? "text-neon-green" : "text-bunker-muted"}`}>{stateLoaded ? candidates.length : "—"}</p>
        </div>
      </div>

      {/* R1-03: MACD beslemesi düştüğünde 3 panelin SESSİZCE kaybolması yerine
          görünür durum. `macdData === null` → besleme yok ("hiç aday yok" değil). */}
      {macdData == null && (
        <section className={`card ${macdError ? "border-neon-red/40 bg-neon-red/5" : ""}`} role={macdError ? "alert" : undefined}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="eyebrow text-bunker-muted">📡 MACD MONITOR BESLEMESİ</p>
            <button type="button" onClick={() => { void loadMacd(); }} className="ui-button ui-button-secondary">YENİDEN DENE</button>
          </div>
          <p className={`mt-2 text-sm ${macdError ? "text-neon-red" : "text-bunker-muted"}`}>
            {macdError ?? "Veri yükleniyor…"}
          </p>
          <p className="mt-1 text-xs text-bunker-muted">YÜKSELİŞ / SIRÇRAMA / ERKEN panelleri bu beslemeden üretilir; veri yokken gösterilemez.</p>
        </section>
      )}
      {macdData != null && macdError && (
        <section className="card border-yellow-400/40" role="status">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-yellow-300">⚠ MACD beslemesi hatası ({macdError}) — son alınan veri gösteriliyor (bayat olabilir).</p>
            <button type="button" onClick={() => { void loadMacd(); }} className="ui-button ui-button-secondary">YENİDEN DENE</button>
          </div>
        </section>
      )}

      {rising.length > 0 && (
        <section className="card border-neon-green/30">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="eyebrow text-neon-green">📈 YÜKSELİŞ EĞİLİMİ ADAYLARI ({rising.length})</p>
            <Link href="/macd-monitor" className="font-mono text-[10px] text-bunker-muted transition-colors hover:text-neon-green">
              MACD MONITOR&apos;DE GÖR →
            </Link>
          </div>
          <p className="mt-1 text-xs text-bunker-muted">
            <b>Evren içi normalize</b> trend gücü ≥ {RISING_MIN_STRENGTH}/10 (0-10 min-max; evrenin en güçlü sembolü 10.0 alır → 9.8 &quot;ham skorda evren zirvesinin %2&apos;si içinde&quot; demektir; 20 barlık lineer regresyon: R² × eğim/bar aralığı) ve en az {RISING_MIN_GREEN}/6 zaman diliminde MACD histogramı yeşil olan semboller — en güçlü yükseliş adayları.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {rising.map((item) => {
              const dotsAria = MACD_TFS
                .map((tf, index) => `${MACD_TF_SHORT[tf]} ${item.dots[index] === true ? "yeşil" : item.dots[index] === false ? "kırmızı" : "veri yok"}`)
                .join(", ");
              return (
              <Link
                key={item.symbol}
                href={`/charts?symbol=${encodeURIComponent(item.symbol)}`}
                className="group rounded-lg border border-neon-green/40 bg-neon-green/10 px-3 py-2 transition-colors hover:border-neon-green/70 hover:bg-neon-green/15"
                title={`${item.symbol} grafiğini aç · GÜÇ ${item.strength.toFixed(1)} · ${item.green}/6 yeşil (6 zaman diliminden ${item.dots.filter((d) => d !== null).length} tanesi verili)`}
              >
                <span className="flex items-center gap-2 font-mono text-sm font-bold text-white">
                  {item.symbol}
                  <span className="rounded border border-neon-green/60 bg-neon-green/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-neon-green">
                    GÜÇ {item.strength.toFixed(1)}
                  </span>
                  {/* R1-17: payda her yerde /6 (title da /6); R1-12: erişilebilir etiket. */}
                  <span className="font-mono text-[10px] text-bunker-muted" aria-label={`6 zaman diliminden ${item.green} tanesi yeşil`}>{item.green}/6</span>
                </span>
                <span className="mt-1.5 flex gap-0.5" role="img" aria-label={`Zaman dilimi renkleri: ${dotsAria}`}>
                  {item.dots.map((value, index) => (
                    <span
                      key={MACD_TFS[index]}
                      aria-hidden="true"
                      title={`${MACD_TF_SHORT[MACD_TFS[index]]}: ${value === true ? "yeşil" : value === false ? "kırmızı" : "veri yok"}`}
                      className={`h-1.5 w-4 rounded-sm ${value === true ? "bg-neon-green" : value === false ? "bg-neon-red" : "bg-bunker-700"}`}
                    />
                  ))}
                </span>
              </Link>
              );
            })}
          </div>
        </section>
      )}

      {earlyCands.length > 0 && (
        <section className="card border-sky-400/30">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="eyebrow text-sky-300">🌱 ERKEN SİNYAL · YAKLAŞIYOR ({earlyCands.length})</p>
            <Link href="/macd-monitor" className="font-mono text-[10px] text-bunker-muted transition-colors hover:text-sky-300">
              MACD MONITOR&apos;DE GÖR →
            </Link>
          </div>
          <p className="mt-1 text-xs text-bunker-muted">
            Kırılımdan ÖNCE öncüller: 🎯 M5 zirveye yaklaşıyor (≤0.5 ATR + aktivite) · 🕐 M1 öncü kırılım · 📈 MACD dip dönüşü. Kartlardaki sayı <b>erken sinyal olgunluğudur</b> (0-100, yalnız sıralama/teşhis — eşik DEĞİLDİR). Alarmlar Ayarlar → MACD/Sıçrama&apos;dan yönetilir.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {earlyCands.map((item) => {
              const proximity = item.detail?.proximity;
              // R1-13: yaş render sırasında hesaplanmaz; izole `<AgeBadge>` canlı tazeler.
              const age = item.detail?.as_of?.approach;
              const title = [
                `${item.symbol} grafiğini aç`,
                item.earlyScore != null ? `erken olgunluk ${item.earlyScore}/100 (tanımlayıcı)` : null,
                item.jump != null ? `sıçrama skoru ${item.jump}/100` : null,
                proximity != null ? `zirveye yakınlık ${(proximity * 100).toFixed(0)}%` : null,
                item.detail?.transition ? "sıkışma→genişleme geçişi" : null,
              ].filter(Boolean).join(" · ");
              const flags = earlyFlagIcons(item.pre);
              return (
                <Link
                  key={item.symbol}
                  href={`/charts?symbol=${encodeURIComponent(item.symbol)}`}
                  className="group rounded-lg border border-sky-400/40 bg-sky-400/10 px-3 py-2 transition-colors hover:border-sky-300/70 hover:bg-sky-400/15"
                  title={title}
                >
                  <span className="flex items-center gap-2 font-mono text-sm font-bold text-white">
                    {item.symbol}
                    {item.earlyScore != null && (
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold ${
                          item.earlyScore >= 60
                            ? "border-sky-400/60 bg-sky-400/20 text-sky-200"
                            : "border-sky-400/30 bg-sky-400/5 text-sky-300/80"
                        }`}
                      >
                        {item.earlyScore}
                      </span>
                    )}
                    {item.jump != null && (
                      <span className="rounded border border-bunker-600 bg-bunker-900 px-1.5 py-0.5 font-mono text-[10px] font-bold text-bunker-muted">
                        {item.jump}
                      </span>
                    )}
                    <AgeBadge ageTs={age} />
                    {/* R1-12: emoji sinyaller yalnız görsel değil — ekran okuyucu
                        için metin karşılığı (`sr-only`). */}
                    <span className="flex gap-0.5 text-[11px] leading-none" aria-hidden="true">
                      {flags.map((entry, index) => (
                        <span key={`${entry.icon}-${index}`} title={entry.title}>{entry.icon}</span>
                      ))}
                      {item.detail?.transition && (
                        <span title="M5 sıkışma → genişleme geçişi (yay boşandı) — tanımlayıcı">⇗</span>
                      )}
                    </span>
                    <span className="sr-only">
                      {[...flags.map((entry) => entry.title), item.detail?.transition ? "M5 sıkışma→genişleme geçişi" : ""].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {jumpers.length > 0 && (
        <section className="card border-yellow-400/30">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="eyebrow text-yellow-300">🚀 SIRÇRAMA ADAYLARI ({jumpers.length})</p>
            <Link href="/macd-monitor" className="font-mono text-[10px] text-bunker-muted transition-colors hover:text-yellow-300">
              MACD MONITOR&apos;DE GÖR →
            </Link>
          </div>
          <p className="mt-1 text-xs text-bunker-muted">
            Sıçrama skoru ≥ {jumpThreshold}/100: trend gücü + MACD yeşil + M5/M15 kırılım, volatilite genişlemesi, hacim ve alıcı agresör teyidi. Eşiği geçenler alarm/push ile bildirilir (Ayarlar → MACD/Sıçrama).
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {jumpers.map((item) => {
              const icons = jumpFlagIcons(item);
              return (
                <Link
                  key={item.symbol}
                  href={`/charts?symbol=${encodeURIComponent(item.symbol)}`}
                  className="group rounded-lg border border-yellow-400/40 bg-yellow-400/10 px-3 py-2 transition-colors hover:border-yellow-300/70 hover:bg-yellow-400/15"
                  title={`${item.symbol} grafiğini aç · SIRÇRAMA ${item.jump}/100`}
                >
                  <span className="flex items-center gap-2 font-mono text-sm font-bold text-white">
                    {item.symbol}
                    <span className="rounded border border-yellow-300/60 bg-yellow-400/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-yellow-300">
                      {item.jump}/100
                    </span>
                    {icons.length > 0 && (
                      <span className="flex gap-0.5 text-[11px] leading-none" aria-hidden="true">
                        {icons.map((entry, index) => (
                          <span key={`${entry.icon}-${index}`} title={entry.title}>{entry.icon}</span>
                        ))}
                      </span>
                    )}
                    {/* R1-12: emoji sinyallerin ekran okuyucu metni. */}
                    {icons.length > 0 && <span className="sr-only">{icons.map((entry) => entry.title).join(" · ")}</span>}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      <section className="card">
        <p className="eyebrow text-neon-green">🎯 UYGUN ADAYLAR ({candidates.length})</p>
        {candidates.length === 0 ? (
          stateError && !stateLoaded ? (
            <p className="mt-3 text-sm text-neon-red">Sunucu verisi alınamadı — aday listesi BİLİNMİYOR. (Yukarıdan "YENİDEN DENE".)</p>
          ) : health.loop_active === false ? (
            <p className="mt-3 text-sm text-neon-red">Tarama döngüsü ÇALIŞMIYOR — arka plan tarayıcısı durmuş görünüyor; otonom izleme devam etmiyor.</p>
          ) : health.system_startup === true ? (
            <p className="mt-3 text-sm text-bunker-muted">Sunucu yeni başladı; ilk tarama henüz tamamlanmadı.</p>
          ) : (
            <p className="mt-3 text-sm text-bunker-muted">Eşiği geçen aday yok (eşik: skor ≥ {effThreshold != null ? effThreshold : "—"}). Tarama devam ediyor…</p>
          )
        ) : (
          <div className="mt-3 space-y-2">
            {candidates.map((c, i) => {
              const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
              const validTarget = Number.isFinite(targetPct) && targetPct > 0;
              const mlActive = Number(c.ml_target_pct) > 0 && c.ml_hit_probability != null;
              const score = panelScore(c);
              return (
                <button key={c.symbol} type="button" onClick={() => setSelected({ c, kind: "radar" })} className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border border-bunker-800 bg-bunker-900/40 px-4 py-3 text-left transition-colors hover:border-neon-green/40 hover:bg-bunker-900/70">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-6 shrink-0 text-center font-mono text-xs text-bunker-muted">{i + 1}</span>
                    <span className="truncate font-mono font-bold text-white">{c.symbol}</span>
                    {mlActive ? <span className="shrink-0 rounded border border-violet-400/40 bg-violet-400/10 px-1.5 py-0.5 font-mono text-[9px] text-violet-300" title={`ML hedef: %${Number(c.ml_target_pct).toFixed(1)}, olasılık: %${Math.round(Number(c.ml_hit_probability) * 100)}`}>ML</span> : null}
                  </div>
                  {/* R1-14: dar ekranda HEDEF gizlenir, SKOR kalır; satır taşmaz. */}
                  <div className="flex shrink-0 items-center gap-2 sm:gap-4">
                    <div className="text-right">
                      <p className="font-mono text-xs text-bunker-muted">SKOR</p>
                      <p className={`font-mono text-sm font-bold ${scoreColor(score)}`}>{scoreText(score)}</p>
                    </div>
                    <div className="hidden text-right sm:block">
                      <p className="font-mono text-xs text-bunker-muted">HEDEF</p>
                      <p className={`font-mono text-sm font-bold ${validTarget ? "text-neon-green" : "text-bunker-muted"}`}>{validTarget ? `+%${targetPct.toFixed(1)}` : "—"}</p>
                    </div>
                    <span className="font-mono text-xs text-bunker-muted">›</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* 🔔 SON BİLDİRİMLER: son 10 bildirim; WS monitoring_alert ile tazelenir. */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="eyebrow text-neon-green">🔔 SON BİLDİRİMLER</p>
          {historyError && (
            <button type="button" onClick={() => { void loadHistory(); }} className="ui-button ui-button-secondary">YENİDEN DENE</button>
          )}
        </div>
        {historyError ? (
          <p className="mt-2 text-sm text-neon-red">⚠ {historyError}</p>
        ) : historyRows == null ? (
          <p className="mt-2 text-sm text-bunker-muted">Yükleniyor…</p>
        ) : historyRows.length === 0 ? (
          <p className="mt-2 text-sm text-bunker-muted">Henüz bildirim yok.</p>
        ) : (
          <div className="mt-3 space-y-1.5">
            {historyRows.map((row, index) => {
              const score = numOrNull(row.score);
              const targetPct = numOrNull(row.target_pct);
              const ts = toMs(row.detected_at);
              return (
                <div
                  key={`${row.symbol ?? "?"}-${row.detected_at ?? index}-${index}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-bunker-800 bg-bunker-900/40 px-3 py-1.5 font-mono text-xs"
                  title={ts ? fmtDateTime(ts) : undefined}
                >
                  <span className="font-bold text-white">{row.symbol ?? "—"}</span>
                  <span className="flex items-center gap-3">
                    <span className={`font-bold ${scoreColor(score)}`}>{scoreText(score)}</span>
                    <span className={targetPct != null && targetPct > 0 ? "text-neon-green" : "text-bunker-muted"}>
                      {targetPct != null && targetPct > 0 ? `+%${targetPct.toFixed(1)}` : "—"}
                    </span>
                    <span className={row.sent_via_push === true ? "text-neon-green" : "text-bunker-muted"}>
                      {row.sent_via_push === true ? "PUSH ✓" : row.sent_via_push === false ? "PUSH —" : "—"}
                    </span>
                    <RelativeTime ts={row.detected_at} />
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {state.watchlist.length > 0 && (
        <section className="card">
          <p className="eyebrow text-yellow-300">👁 İZLEME LİSTESİ ({state.watchlist.length})</p>
          <div className="mt-3 space-y-2">
            {state.watchlist.map((w) => {
              const reason = blockReasonLabel(w.block_reason);
              const score = panelScore(w);
              return (
                <button key={w.symbol} type="button" onClick={() => setSelected({ c: w, kind: "watch" })} className="flex w-full items-center justify-between gap-2 rounded-lg border border-bunker-800 bg-bunker-900/40 px-4 py-2.5 text-left transition-colors hover:border-yellow-400/40">
                  <span className="min-w-0 truncate font-mono text-sm font-bold text-white">{w.symbol}</span>
                  <span className="flex shrink-0 items-center gap-2 sm:gap-3">
                    {reason && (
                      <span
                        className="hidden rounded border border-neon-red/30 bg-neon-red/10 px-1.5 py-0.5 font-mono text-[9px] text-neon-red sm:inline"
                        title={w.block_reason ? `Ham neden: ${w.block_reason}` : "Eşik skoru geçse bile aday kriterlerine takılan yön"}
                      >
                        {reason}
                      </span>
                    )}
                    <span className={`font-mono text-sm font-bold ${scoreColor(score)}`}>{scoreText(score)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {selected && <CandidateDetail c={selected.c} kind={selected.kind} onClose={() => setSelected(null)} />}
    </main>
  );
}
