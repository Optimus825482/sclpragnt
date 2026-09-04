"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import SymbolLink from "../components/SymbolLink";

type NotificationSettings = {
  enabled: boolean;
  min_score: number;
  min_target_pct: number;
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

const SCAN_INTERVAL_MS = 30_000;
// Backend normalize_score cap'ı (MONITORING_SCORE_NORM_CAP): ham velocity_score
// bu değere bölünüp 0-100 panel ölçeğine çevrilir. Backend artık panel_score
// alanını gönderir; eski yanıt.cache'leri için burada da hesaplanır.
const SCORE_NORM_CAP = 40;

const fmtTime = (ts: number | null) => {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("tr-TR");
};

const fmtPrice = (value: number | undefined, symbol?: string) => {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  const digits = symbol && value < 100 ? 6 : value < 10 ? 4 : 2;
  return Number(value).toLocaleString("tr-TR", { maximumFractionDigits: digits });
};

// Panel (0-100) ölçeği: admin eşiği ve bildirim skoru bu ölçekte; ham
// velocity_score (0-200+) arayüzde artık gösterilmez (2026-09-04).
const panelScore = (c: { panel_score?: number | null; velocity_score?: number | null }) => {
  const p = Number(c.panel_score);
  if (Number.isFinite(p) && c.panel_score != null) return p;
  const raw = Number(c.velocity_score) || 0;
  return Math.round(100 * Math.min(1, raw / SCORE_NORM_CAP) * 10) / 10;
};

const scoreColor = (score: number) => {
  if (score >= 70) return "text-neon-green";
  if (score >= 50) return "text-yellow-300";
  return "text-neon-red";
};

// İzleme listesindeki sembolün aday olamama sebebi (velocity.py block_reason).
const blockReasonLabel = (reason?: string | null) => {
  if (!reason) return null;
  if (reason.startsWith("mfi_asiri_alim")) return "MFI aşırı alım";
  if (reason.startsWith("mfi_asiri_satim")) return "MFI aşırı satım";
  if (reason.startsWith("rsi_asiri_alim")) return "RSI aşırı alım";
  if (reason.startsWith("atr_yetersiz")) return "ATR yetersiz";
  if (reason.startsWith("bb_genisligi_yetersiz") || reason === "bb_verisi_yok") return "BB dar";
  if (reason === "yapisal_teyit_yok") return "Yapısal teyit yok";
  return "Kriter sağlanmadı";
};

const CandidateDetail = ({ c, onClose }: { c: Candidate; onClose: () => void }) => {
  const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
  const price = Number(c.price);
  const validTarget = Number.isFinite(targetPct) && targetPct > 0 && Number.isFinite(price) && price > 0;
  const expected = validTarget ? price * (1 + targetPct / 100) : null;
  const mlActive = Number(c.ml_target_pct) > 0 && c.ml_hit_probability != null;
  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="candidate-detail-title">
      <section className="w-full max-w-sm rounded-xl border border-neon-green/40 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-bunker-800 bg-neon-green/5 px-5 py-4">
          <div>
            <p className="eyebrow text-neon-green/80">RADAR ADAYI</p>
            <h2 id="candidate-detail-title" className="font-mono text-lg font-bold text-white">{c.symbol}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Kapat" className="text-bunker-muted hover:text-white">✕</button>
        </div>
        <div className="grid grid-cols-2 gap-3 p-5">
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">SKOR</p>
            <p className={`mt-1 font-mono text-lg font-bold ${scoreColor(panelScore(c))}`}>{panelScore(c).toFixed(1)}</p>
          </div>
          <div className="rounded-lg border border-neon-green/30 bg-neon-green/5 px-3 py-2 text-center">
            <p className="eyebrow">HEDEF (5/15dk)</p>
            <p className="mt-1 font-mono text-lg font-bold text-neon-green">{validTarget ? `+%${targetPct.toFixed(1)}` : "—"}</p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">ANLIK</p>
            <p className="mt-1 font-mono text-sm font-bold text-white">{fmtPrice(price, c.symbol)} <span className="text-[10px] text-bunker-muted">TRY</span></p>
          </div>
          <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-center">
            <p className="eyebrow">BEKLENEN</p>
            <p className="mt-1 font-mono text-sm font-bold text-neon-green">{expected != null ? `${fmtPrice(expected, c.symbol)}` : "—"}</p>
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
                  <span className="text-bunker-muted">hedef <b className="text-neon-green">+%{Number(p.target_pct ?? 0).toFixed(1)}</b></span>
                  <span className="text-bunker-muted">skor <b className="text-white">{panelScore({ velocity_score: p.velocity_score }).toFixed(1)}</b></span>
                  <span className={p.passes ? "text-neon-green" : "text-neon-red"}>{p.passes ? "GEÇTİ" : (blockReasonLabel(p.block_reason) ?? "İZLE")}</span>
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
            <a href={`/charts?symbol=${c.symbol}`} className="ui-button ui-button-secondary">GRAFİK</a>
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
  // Eşik artık global admin ayarı: herkese UYGULANAN (etkin) değer gösterilir;
  // admin bu sayfadan değiştirebilir (2026-09-04 kullanıcı kararı).
  const [settings, setSettings] = useState<NotificationSettings>({ enabled: true, min_score: 50, min_target_pct: 2.0, quiet_hours_start: null, quiet_hours_end: null });
  const [selected, setSelected] = useState<Candidate | null>(null);
  const scanTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [minScoreInput, setMinScoreInput] = useState<string>("50");
  const [minScoreDirty, setMinScoreDirty] = useState(false);
  const [savingMinScore, setSavingMinScore] = useState(false);

  // Admin girişteyken 30sn'lik tarama döngüsü inputu ezmesin: yalnız
  // düzenlenmemişken (dirty değilken) ayar değeriyle senkronlanır.
  useEffect(() => {
    if (!minScoreDirty) setMinScoreInput(String(Math.round(settings.min_score)));
  }, [settings.min_score, minScoreDirty]);

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setSettings({ enabled: data.enabled ?? true, min_score: data.min_score ?? 50, min_target_pct: data.min_target_pct ?? 2.0, quiet_hours_start: data.quiet_hours_start ?? null, quiet_hours_end: data.quiet_hours_end ?? null });
        setEffectiveMinScore(data.effective_min_score != null ? Number(data.effective_min_score) : null);
      }
    } catch { /* varsayılan */ }
  }, []);

  const saveMinScore = useCallback(async () => {
    const val = Number(minScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) return;
    setSavingMinScore(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_score: val }),
      });
      if (res.ok) {
        setMinScoreDirty(false);
        await loadSettings();
      }
    } catch { /* sessiz */ } finally { setSavingMinScore(false); }
  }, [minScoreInput, loadSettings]);

  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/scan`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setState({ last_scan_at: data.scan_at, scan_count: data.scan_count, candidates: data.candidates || [], watchlist: data.watchlist || [] });
        if (data.settings) setSettings({ enabled: data.settings.enabled ?? true, min_score: data.settings.min_score ?? 50, min_target_pct: data.settings.min_target_pct ?? 2.0, quiet_hours_start: data.settings.quiet_hours_start ?? null, quiet_hours_end: data.settings.quiet_hours_end ?? null });
        setEffectiveMinScore(data.effective_min_score != null ? Number(data.effective_min_score) : null);
      }
    } catch { /* sessiz */ } finally { setScanning(false); }
  }, []);

  useEffect(() => {
    loadSettings();
    apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store" }).then((r) => r.json()).then((data) => {
      setState({ last_scan_at: data.last_scan_at, scan_count: data.scan_count, candidates: data.candidates || [], watchlist: data.watchlist || [] });
      if (data.settings) setSettings({ enabled: data.settings.enabled ?? true, min_score: data.settings.min_score ?? 50, min_target_pct: data.settings.min_target_pct ?? 2.0, quiet_hours_start: data.settings.quiet_hours_start ?? null, quiet_hours_end: data.settings.quiet_hours_end ?? null });
      setEffectiveMinScore(data.effective_min_score != null ? Number(data.effective_min_score) : null);
    }).catch(() => {});
    scanTimerRef.current = setInterval(runScan, SCAN_INTERVAL_MS);
    return () => { if (scanTimerRef.current) clearInterval(scanTimerRef.current); };
  }, [runScan, loadSettings]);

  // Tek eşik (2026-09-04): backend'in gönderdiği etkin değer; yoksa admin ayarı.
  const effThreshold = effectiveMinScore != null
    ? effectiveMinScore
    : Math.min(100, Math.round(settings.min_score));
  // Eşik altı adaylar listede gizlenir (backend de filtreler; bu ikinci emniyet).
  const visibleCandidates = state.candidates.filter((c) => panelScore(c) >= effThreshold);

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
              girdiği değer her yerde aynen uygulanır ve gösterilir. */}
          <span className="ui-button ui-button-secondary pointer-events-none" title="Radar, bildirim ve raporlarda uygulanan global eşik">
            ⚖️ EŞİK: SKOR ≥ {effThreshold} · GLOBAL
          </span>
          {isAdmin && (
            <>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={minScoreInput}
                onChange={(e) => { setMinScoreInput(e.target.value); setMinScoreDirty(true); }}
                title="Admin eşiği: radar listesi, bildirim, rapor ve otonom taramada aynen uygulanır"
                className="w-20 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
              />
              <button
                onClick={saveMinScore}
                disabled={savingMinScore || !minScoreDirty || !minScoreInput || Number(minScoreInput) < 0 || Number(minScoreInput) > 100}
                className="ui-button ui-button-primary"
              >
                {savingMinScore ? "KAYDEDİLİYOR…" : "EŞİĞİ KAYDET"}
              </button>
            </>
          )}
          <button onClick={runScan} disabled={scanning} className="ui-button ui-button-primary">{scanning ? "TARANIYOR…" : "ŞİMDİ TARA"}</button>
        </div>
      </div>

      {/* Bildirim ayarları artık global admin ayarıdır; kullanıcı paneli kaldırıldı (2026-09-04).
          Ayar yalnız admin tarafından, /api/monitoring/settings PUT üzerinden değiştirilebilir. */}

      <div className="grid grid-cols-3 gap-3">
        <div className="card"><p className="eyebrow">Son Tarama</p><p className="mt-2 font-mono text-lg text-white">{fmtTime(state.last_scan_at)}</p></div>
        <div className="card"><p className="eyebrow">Tarama Sayısı</p><p className="mt-2 font-mono text-lg text-white">{state.scan_count}</p></div>
        <div className="card"><p className="eyebrow">Aday Sayısı</p><p className="mt-2 font-mono text-lg text-neon-green">{visibleCandidates.length}</p></div>
      </div>

      <section className="card">
        <p className="eyebrow text-neon-green">🎯 UYGUN ADAYLAR ({visibleCandidates.length})</p>
        {visibleCandidates.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Eşiği geçen aday yok (eşik: skor ≥ {effThreshold}). Tarama devam ediyor…</p>
        ) : (
          <div className="mt-3 space-y-2">
            {visibleCandidates.map((c, i) => {
              const targetPct = Number(c.target_pct) > 0 ? Number(c.target_pct) : Number(c.ml_target_pct);
              const validTarget = Number.isFinite(targetPct) && targetPct > 0;
              const mlActive = Number(c.ml_target_pct) > 0 && c.ml_hit_probability != null;
              return (
                <button key={c.symbol} type="button" onClick={() => setSelected(c)} className="flex w-full items-center justify-between rounded-lg border border-bunker-800 bg-bunker-900/40 px-4 py-3 text-left transition-colors hover:border-neon-green/40 hover:bg-bunker-900/70">
                  <div className="flex items-center gap-3">
                    <span className="w-6 text-center font-mono text-xs text-bunker-muted">{i + 1}</span>
                    <span className="font-mono font-bold text-white">{c.symbol}</span>
                    {mlActive ? <span className="rounded border border-violet-400/40 bg-violet-400/10 px-1.5 py-0.5 font-mono text-[9px] text-violet-300" title={`ML hedef: %${Number(c.ml_target_pct).toFixed(1)}, olasılık: %${Math.round(Number(c.ml_hit_probability) * 100)}`}>ML</span> : null}
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="font-mono text-xs text-bunker-muted">SKOR</p>
                      <p className={`font-mono text-sm font-bold ${scoreColor(panelScore(c))}`}>{panelScore(c).toFixed(1)}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-xs text-bunker-muted">HEDEF</p>
                      <p className="font-mono text-sm font-bold text-neon-green">{validTarget ? `+%${targetPct.toFixed(1)}` : "—"}</p>
                    </div>
                    <span className="font-mono text-xs text-bunker-muted">›</span>
                  </div>
                </button>
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
              return (
                <button key={w.symbol} type="button" onClick={() => setSelected(w)} className="flex w-full items-center justify-between rounded-lg border border-bunker-800 bg-bunker-900/40 px-4 py-2.5 text-left transition-colors hover:border-yellow-400/40">
                  <span className="font-mono text-sm font-bold text-white">{w.symbol}</span>
                  <span className="flex items-center gap-3">
                    {reason && <span className="rounded border border-neon-red/30 bg-neon-red/10 px-1.5 py-0.5 font-mono text-[9px] text-neon-red" title="Eşik skoru geçse bile aday kriterlerine takılan yön">{reason}</span>}
                    <span className={`font-mono text-sm font-bold ${scoreColor(panelScore(w))}`}>{panelScore(w).toFixed(1)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {selected && <CandidateDetail c={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
