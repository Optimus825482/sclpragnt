"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type Candidate = {
  symbol: string;
  velocity_score: number;
  target_pct: number;
  price: number;
  atr_pct: number;
  mode: string;
  horizon_minutes: number;
  ml_target_pct: number | null;
  ml_hit_probability: number | null;
};

type NotificationSettings = {
  enabled: boolean;
  min_score: number;
  min_target_pct: number;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
};

type MonitoringState = {
  last_scan_at: number | null;
  scan_count: number;
  candidates: Candidate[];
  watchlist: Candidate[];
};

const SCAN_INTERVAL_MS = 30_000;

const fmtTime = (ts: number | null) => {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("tr-TR");
};

const fmtPrice = (value: number | undefined, symbol?: string) => {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  const digits = symbol && value < 100 ? 6 : value < 10 ? 4 : 2;
  return Number(value).toLocaleString("tr-TR", { maximumFractionDigits: digits });
};

const scoreColor = (score: number) => {
  if (score >= 4.0) return "text-neon-green";
  if (score >= 2.0) return "text-yellow-300";
  return "text-neon-red";
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
            <p className={`mt-1 font-mono text-lg font-bold ${scoreColor(Number(c.velocity_score) || 0)}`}>{(Number(c.velocity_score) || 0).toFixed(1)}</p>
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
  const [state, setState] = useState<MonitoringState>({ last_scan_at: null, scan_count: 0, candidates: [], watchlist: [] });
  const [scanning, setScanning] = useState(false);
  const [settings, setSettings] = useState<NotificationSettings>({ enabled: true, min_score: 1.0, min_target_pct: 2.0, quiet_hours_start: null, quiet_hours_end: null });
  const [showSettings, setShowSettings] = useState(false);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const scanTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setSettings({ enabled: data.enabled ?? true, min_score: data.min_score ?? 1.0, min_target_pct: data.min_target_pct ?? 2.0, quiet_hours_start: data.quiet_hours_start ?? null, quiet_hours_end: data.quiet_hours_end ?? null });
      }
    } catch { /* varsayılan */ }
  }, []);

  const saveSettings = useCallback(async (next: NotificationSettings) => {
    try {
      await apiRequest(`${API_BASE}/api/monitoring/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
      setSettings(next);
    } catch { /* kaydedilemedi */ }
  }, []);

  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/scan`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setState({ last_scan_at: data.scan_at, scan_count: data.scan_count, candidates: data.candidates || [], watchlist: data.watchlist || [] });
        if (data.settings) setSettings({ enabled: data.settings.enabled ?? true, min_score: data.settings.min_score ?? 1.0, min_target_pct: data.settings.min_target_pct ?? 2.0, quiet_hours_start: data.settings.quiet_hours_start ?? null, quiet_hours_end: data.settings.quiet_hours_end ?? null });
      }
    } catch { /* sessiz */ } finally { setScanning(false); }
  }, []);

  useEffect(() => {
    loadSettings();
    apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store" }).then((r) => r.json()).then((data) => {
      setState({ last_scan_at: data.last_scan_at, scan_count: data.scan_count, candidates: data.candidates || [], watchlist: data.watchlist || [] });
    }).catch(() => {});
    scanTimerRef.current = setInterval(runScan, SCAN_INTERVAL_MS);
    return () => { if (scanTimerRef.current) clearInterval(scanTimerRef.current); };
  }, [runScan, loadSettings]);

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">RADAR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Otonom İzleme</h1>
          <p className="mt-1 text-sm text-bunker-muted">Yüksek potansiyelli sembolleri tarar, uygun olanları bildirir.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setShowSettings(!showSettings)} className="ui-button ui-button-secondary">⚙️ Ayarlar</button>
          <button onClick={runScan} disabled={scanning} className="ui-button ui-button-primary">{scanning ? "TARANIYOR…" : "ŞİMDİ TARA"}</button>
        </div>
      </div>

      {showSettings && (
        <div className="card border-neon-green/20">
          <p className="eyebrow text-neon-green">BİLDİRİM AYARLARI</p>
          <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between">
              <p className="font-mono text-sm text-white">Bildirimleri Etkinleştir</p>
              <button onClick={() => saveSettings({ ...settings, enabled: !settings.enabled })} className={`w-12 h-6 rounded-full border transition-colors relative ${settings.enabled ? "bg-neon-green/30 border-neon-green/50" : "bg-bunker-800 border-bunker-700"}`}>
                <span className={`absolute top-0.5 w-5 h-5 rounded-full transition-all ${settings.enabled ? "left-6 bg-neon-green" : "left-0.5 bg-bunker-muted"}`} />
              </button>
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <p className="font-mono text-sm text-white">Minimum Skor</p>
                <span className="font-mono text-sm text-neon-green">{settings.min_score.toFixed(1)}</span>
              </div>
              <input type="range" min="0.5" max="6.0" step="0.1" value={settings.min_score} onChange={(e) => setSettings({ ...settings, min_score: parseFloat(e.target.value) })} onMouseUp={() => saveSettings(settings)} onTouchEnd={() => saveSettings(settings)} className="w-full accent-neon-green" />
              <div className="flex justify-between text-[10px] text-bunker-muted mt-1"><span>0.5</span><span>6.0</span></div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <p className="font-mono text-sm text-white">Minimum Hedef Artış</p>
                <span className="font-mono text-sm text-neon-green">%{settings.min_target_pct.toFixed(1)}</span>
              </div>
              <input type="range" min="1.0" max="15.0" step="0.5" value={settings.min_target_pct} onChange={(e) => setSettings({ ...settings, min_target_pct: parseFloat(e.target.value) })} onMouseUp={() => saveSettings(settings)} onTouchEnd={() => saveSettings(settings)} className="w-full accent-neon-green" />
              <div className="flex justify-between text-[10px] text-bunker-muted mt-1"><span>%1</span><span>%15</span></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="font-mono text-sm text-white mb-1">Sessiz Saat Başlangıç</p>
                <input type="time" value={settings.quiet_hours_start || ""} onChange={(e) => saveSettings({ ...settings, quiet_hours_start: e.target.value || null })} className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none" />
              </div>
              <div>
                <p className="font-mono text-sm text-white mb-1">Sessiz Saat Bitiş</p>
                <input type="time" value={settings.quiet_hours_end || ""} onChange={(e) => saveSettings({ ...settings, quiet_hours_end: e.target.value || null })} className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none" />
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-3">
        <div className="card"><p className="eyebrow">Son Tarama</p><p className="mt-2 font-mono text-lg text-white">{fmtTime(state.last_scan_at)}</p></div>
        <div className="card"><p className="eyebrow">Tarama Sayısı</p><p className="mt-2 font-mono text-lg text-white">{state.scan_count}</p></div>
        <div className="card"><p className="eyebrow">Aday Sayısı</p><p className="mt-2 font-mono text-lg text-neon-green">{state.candidates.length}</p></div>
      </div>

      <section className="card">
        <p className="eyebrow text-neon-green">🎯 UYGUN ADAYLAR ({state.candidates.length})</p>
        {state.candidates.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Henüz uygun aday yok. Tarama devam ediyor…</p>
        ) : (
          <div className="mt-3 space-y-2">
            {state.candidates.map((c, i) => {
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
                      <p className={`font-mono text-sm font-bold ${scoreColor(Number(c.velocity_score) || 0)}`}>{(Number(c.velocity_score) || 0).toFixed(1)}</p>
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
            {state.watchlist.map((w) => (
              <button key={w.symbol} type="button" onClick={() => setSelected(w)} className="flex w-full items-center justify-between rounded-lg border border-bunker-800 bg-bunker-900/40 px-4 py-2.5 text-left transition-colors hover:border-yellow-400/40">
                <span className="font-mono text-sm font-bold text-white">{w.symbol}</span>
                <span className={`font-mono text-sm font-bold ${scoreColor(Number(w.velocity_score) || 0)}`}>{(Number(w.velocity_score) || 0).toFixed(1)}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {selected && <CandidateDetail c={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
