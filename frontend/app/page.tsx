"use client";

/**
 * Ana Sayfa — Mobil öncelikli dashboard.
 * Hoş geldin mesajı + bugünün sinyal/success/otonom/PnL özeti + portföy bakiyesi.
 * Basit modda (ui-mode) yalnızca temel metrikler + son aktivite.
 * Gelişmiş modda (varsayılan) otonom pozisyonlar + strateji performansı eklenir.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "./lib/api";
import { useAuth } from "./lib/auth";
import { useLiveMessages as useLiveSocketMessages, useLiveStatus } from "./lib/liveSocket";
import { useUiMode } from "./lib/ui-mode";

/* ============== TİPLER ============== */
type DashboardSummary = {
  signals_today: { total: number; buy_signals: number; close_signals: number };
  auto_paper_today: { trades: number; pnl: number; winning: number; losing: number };
  portfolio: { balance: number; open_positions: number; total_value: number };
};
type AutoPaperTrade = {
  id: number; symbol: string; entry_price: number; current_price?: number | null;
  quantity: number; take_profit?: number | null; stop_loss?: number | null;
};
type LiveSignal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number };

/* ============== YARDIMCILAR ============== */
const money = (v?: number | null) =>
  v == null ? "0,00" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signedMoney = (v?: number | null) =>
  v == null ? "—" : `${v < 0 ? "-" : ""}${Math.abs(v).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtTime = (ts?: number | null) => {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
};

function MetricCard({ label, value, hint, tone = "" }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="ui-card ui-stat-card">
      <p className="eyebrow">{label}</p>
      <p className={`ui-stat-value ${tone}`}>{value}</p>
      {hint && <p className="ui-stat-detail">{hint}</p>}
    </div>
  );
}

/* ============== SAYFA ============== */
export default function Home() {
  const { username } = useAuth();
  const liveStatus = useLiveStatus();
  const [mode, toggleMode] = useUiMode();
  const isAdvanced = mode === "advanced";

  // Dashboard verisi
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [autoPaperOpen, setAutoPaperOpen] = useState<AutoPaperTrade[]>([]);
  const [liveSignals, setLiveSignals] = useState<LiveSignal[]>([]);

  // Yükle
  const load = useCallback(() => {
    if (document.hidden) return;
    apiRequest(`${API_BASE}/api/dashboard/summary`, { cache: "no-store" })
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => setSummary(d))
      .catch(() => undefined);
    apiRequest(`${API_BASE}/api/auto-paper/trades?status=open`, { cache: "no-store" })
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => setAutoPaperOpen(d.trades || []))
      .catch(() => undefined);
    apiRequest(`${API_BASE}/api/signals?limit=30`, { cache: "no-store" })
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => setLiveSignals((d.signals || []).slice(-10).reverse()))
      .catch(() => undefined);
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  // WS
  useLiveSocketMessages(useCallback((msg: any) => {
    if (msg.type === "signal") {
      setLiveSignals((prev) => [msg.data, ...prev].slice(0, 10));
      setAutoPaperOpen([]); // debounce beklemeden tazeleme; 15sn poll'a kalır
    }
  }, []));

  const s = summary;
  const pnlTone = s && s.auto_paper_today.pnl >= 0 ? "text-neon-green" : "text-neon-red";
  const apPnl = s?.auto_paper_today.pnl ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      {/* Üst: Hoş geldin + canlı + mod toggle */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">CANLI DASHBOARD</p>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            {username ? (
              <>Hoş geldin, <span className="text-neon-green">{username.charAt(0).toUpperCase() + username.slice(1)}</span> 👋</>
            ) : (
              <>PORTFÖY & <span className="text-neon-green">SCALPING</span></>
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded border px-2 py-1 font-mono text-[10px] ${liveStatus === "open" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-yellow-300/40 bg-yellow-300/10 text-yellow-300"}`}>
            {liveStatus === "open" ? "● CANLI" : "○ BAĞLANTI KESİK"}
          </span>
          <button onClick={toggleMode} className="rounded border border-bunker-700 px-2 py-1 font-mono text-[10px] text-bunker-muted hover:border-neon-green/40 hover:text-neon-green" title={`Şu an: ${isAdvanced ? "Gelişmiş" : "Basit"} mod`}>
            {isAdvanced ? "⚙ GELİŞMİŞ" : "🔵 BASİT"}
          </button>
        </div>
      </header>

      {/* 4 kart: 2 sütun mobil, 4 sütun masaüstü */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="BUGÜN SİNYAL" value={String(s?.signals_today.total ?? "…")} hint={`${s?.signals_today.buy_signals ?? 0} giriş · ${s?.signals_today.close_signals ?? 0} çıkış`} />
        <MetricCard label="OTONOM İŞLEM" value={`${s?.auto_paper_today.trades ?? 0} · ₺${signedMoney(apPnl)}`} tone={s ? pnlTone : ""} hint={`${s?.auto_paper_today.winning ?? 0} kazanç · ${s?.auto_paper_today.losing ?? 0} kayıp`} />
        <MetricCard label="PORTFÖY" value={`₺${money(s?.portfolio.total_value)}`} hint={`₺${money(s?.portfolio.balance)} serbest`} />
        <MetricCard label="AÇIK POZİSYON" value={String(s?.portfolio.open_positions ?? 0)} hint={s?.portfolio.open_positions ? "pozisyon var" : "yok"} />
      </div>

      {/* Otonom açık pozisyonlar (yalnız varsa) */}
      {autoPaperOpen.length > 0 && (
        <section className="card">
          <div className="ui-section-header">
            <div><p className="eyebrow text-neon-green">🤖 OTONOM POZİSYONLAR</p></div>
            <span className="font-mono text-xs text-bunker-muted">{autoPaperOpen.length} pozisyon</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {autoPaperOpen.map((t) => {
              const entry = Number(t.entry_price);
              const current = Number(t.current_price) > 0 ? Number(t.current_price) : entry;
              const pnl = (current - entry) * Number(t.quantity);
              const pnlPct = entry > 0 ? ((current - entry) / entry * 100) : 0;
              return (
                <div key={t.id} className="rounded-lg border border-bunker-700 bg-bunker-900/60 p-3">
                  <p className="font-mono font-bold text-white">{t.symbol}</p>
                  <p className={`mt-1 font-mono text-sm ${pnl >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                    {pnl >= 0 ? "+" : ""}{pnlPct.toFixed(2)}% · ₺{signedMoney(pnl)}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-bunker-muted">
                    TP {Number(t.take_profit || 0).toFixed(2)} · SL {Number(t.stop_loss || 0).toFixed(2)}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Gelişmiş mod: strateji performansı */}
      {isAdvanced && (
        <section className="card">
          <div className="ui-section-header">
            <div><p className="eyebrow">📊 STRATEJİ PERFORMANSI</p></div>
            <a href="/reports" className="font-mono text-[11px] text-bunker-muted hover:text-neon-green underline-offset-2 underline">{">"} Raporlar</a>
          </div>
          <div className="mt-2 flex flex-wrap gap-3">
            <APStatCard label="Bugün sinyal" value={String(s?.signals_today.total ?? 0)} />
            <APStatCard label="Otonom işlem" value={String(s?.auto_paper_today.trades ?? 0)} sub={s ? `₺${signedMoney(apPnl)}` : ""} />
            <APStatCard label="Serbest TL" value={`₺${money(s?.portfolio.balance)}`} />
            <APStatCard label="Toplam Değer" value={`₺${money(s?.portfolio.total_value)}`} />
          </div>
        </section>
      )}

      {/* Son aktivite akışı (mobilde 4-5 satır) */}
      <section className="card bg-bunker-950 p-0 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-bunker-800">
          <p className="eyebrow">SON AKTİVİTE</p>
          {liveStatus === "open" && <span className="font-mono text-[10px] text-neon-green animate-pulse">● LİVE</span>}
        </div>
        <div className="px-4 py-3 font-mono text-sm max-h-40 overflow-y-auto">
          {liveSignals.length === 0 && <p className="text-bunker-muted">Sinyal bekleniyor…</p>}
          {liveSignals.slice(0, isAdvanced ? 8 : 4).map((s, i) => (
            <div key={s.id ?? i} className={`py-1 text-xs ${s.action === "BUY_BLOCKED" ? "text-sky-400" : s.action.includes("BUY") ? "text-neon-green" : "text-neon-red"}`}>
              <span className="text-bunker-muted">[{fmtTime(s.timestamp)}]</span>{" "}
              <b>{s.action}</b>{" "}
              <span className="text-white">{s.symbol}</span>
              {s.price ? ` @ ₺${Number(s.price).toLocaleString("tr-TR", { maximumFractionDigits: 2 })}` : ""}
              {s.reason && <span className="text-bunker-muted ml-1">· {s.reason}</span>}
            </div>
          ))}
        </div>
        {(liveSignals.length > 4 || isAdvanced) && (
          <div className="border-t border-bunker-800 px-4 py-2 text-center">
            <a href="/reports" className="font-mono text-[10px] text-bunker-muted hover:text-neon-green underline-offset-2 underline">Tümünü gör →</a>
          </div>
        )}
      </section>
    </div>
  );
}

function APStatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex-1 rounded-lg border border-bunker-800 bg-bunker-900/50 px-3 py-2 min-w-[100px]">
      <p className="font-mono text-[10px] text-bunker-muted">{label}</p>
      <p className="font-mono text-sm font-bold text-white">{value}</p>
      {sub && <p className="font-mono text-[10px] text-bunker-muted">{sub}</p>}
    </div>
  );
}