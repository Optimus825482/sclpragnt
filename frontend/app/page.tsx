"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest, fetchAllPages } from "./lib/api";
import { useLiveMessages, useLiveStatus } from "./lib/liveSocket";
import SymbolLink from "./components/SymbolLink";
import AlertPanel from "./components/AlertPanel";
import { useAuth } from "./lib/auth";

type Position = {
  symbol: string;
  side?: string;
  entry: number;
  current: number;
  pnl_pct: number;
  pnl_try?: number;
  value: number;
  quantity?: number;
  entry_time?: number;
  strategy?: string;
};
type Portfolio = {
  try: number;
  total_value: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  positions: Position[];
};
type Trade = {
  id: number;
  symbol: string;
  strategy: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct?: number;
  commission?: number;
  hold_seconds?: number;
  exit_time?: number;
  entry_time?: number;
  reason?: string;
};
type Signal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number; strategy?: string };

const STRATEGY_LABEL: Record<string, string> = {
  EMA_VWAP_PULLBACK: "EMA + VWAP Pullback",
  BB_SQUEEZE_ORDERFLOW: "BB Squeeze + Order-Flow",
  ORDERFLOW: "Order-Flow Imbalance",
  MOMENTUM: "MTF Momentum Ranking",
  VWAP_MEAN_REVERSION: "VWAP Mean Reversion",
  KELTNER_BREAKOUT: "Keltner Breakout",
  CHOP_TREND_FILTER: "CHOP Trend Filter",
  DONCHIAN_BREAKOUT: "Donchian Breakout",
  LLM_PAPER: "LLM Paper",
  PUMP_MONITOR: "Pump Monitor",
  CHAT_PREDICTION: "Hız Avcısı (Otonom)",
  FISHER_M3_KERNEL_M5_EXACT_PAPER: "Fisher M3 + Kernel M5",
  BB_MFI_MEAN_REVERSION: "BB + MFI Mean Reversion",
};
const money = (v?: number | null) =>
  v == null ? "0,00" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function MetricCard({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="ui-card ui-stat-card">
      <p className="eyebrow">{label}</p>
      <p className={`ui-stat-value ${tone}`}>{value}</p>
    </div>
  );
}

function pnlText(pct: number) {
  const v = Number.isFinite(pct) ? pct : 0;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export default function Home() {
  const { username } = useAuth();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [closing, setClosing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);
  const [velocityStatus, setVelocityStatus] = useState<any>(null);
  // AÇIK POZİSYONLAR tablosu güvenilir kaynak: REST /api/positions
  // (WS portfolio mesajı koparsa panel boş kalmasın diye REST'ten beslenir)
  const [restPositions, setRestPositions] = useState<Position[]>([]);
  const liveStatus = useLiveStatus();

  const loadRestPositions = useCallback(() => {
    apiRequest(`${API_BASE}/api/positions`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { setRestPositions(d.positions || []); })
      .catch(() => undefined);
  }, []);

  // REST 15 sn'de bir taban veriyi tazeler; WS portfolio mesajı geldiğinde
  // güncel anlık değerlerle üzerine yazılır. Böylece WS kopukken bile açık
  // pozisyonlar listede görünür (eskiden tablo yalnızca WS'e bağlıydı ve
  // bağlantı kopunca "Açık pozisyon yok" yanıltıcı metni gösteriyordu).
  useEffect(() => {
    loadRestPositions();
    const timer = window.setInterval(loadRestPositions, 15000);
    return () => window.clearInterval(timer);
  }, [loadRestPositions]);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      apiRequest(`${API_BASE}/api/velocity/status`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d) => { if (!cancelled) setVelocityStatus(d); })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const runManualVelocityScan = async () => {
    if (scanBusy) return;
    setScanBusy(true);
    setScanResult(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/velocity/manual-scan`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || "Tarama başarısız");
      setScanResult(data);
    } catch (e) {
      setScanResult({ error: e instanceof Error ? e.message : "Tarama hatası" });
    } finally {
      setScanBusy(false);
    }
  };
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const loadTrades = useCallback(() => {
    fetchAllPages<Trade>("/api/trades", "trades")
      .then((result) => setTrades(result.rows))
      .catch(() => undefined);
  }, []);
  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "portfolio") setPortfolio(message.data);
    if (message.type === "signal") setSignals((current) => [...current, message.data].slice(-120));
    if (["signal", "trade_updated", "reset"].includes(message.type)) loadTrades();
  }, [loadTrades]);
  useLiveMessages(onLiveMessage);

  useEffect(() => {
    loadTrades();
    apiRequest(`${API_BASE}/api/signals?limit=100`)
      .then((response) => response.json())
      .then((data) => setSignals((data.signals || []).slice(0, 100).reverse()))
      .catch(() => undefined);
  }, [loadTrades]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [signals]);

  const closePosition = async (symbol: string) => {
    if (!window.confirm(`${symbol} pozisyonu güncel fiyatla kapatılsın mı?`)) return;
    setClosing(symbol);
    setMsg(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/positions/${symbol}/close`, { method: "POST" });
      const data = await response.json();
      setMsg(data.message || (data.ok ? "Pozisyon kapatıldı." : "Pozisyon kapatılamadı."));
      loadRestPositions();
    } catch {
      setMsg("Pozisyon kapatılamadı.");
    } finally {
      setClosing(null);
    }
  };

  // Tablo kaynağı: REST tabanlı liste + WS portfolio'dan güncel kalemler.
  // WS kalemi varsa REST kalemini ezer (anlık PnL taze olur); WS yoksa REST
  // listesi tek başına görünür kalır. Aynı sembol için güncel entry_time
  // sahip olan kazanır (manuel kapatma/açılış sonrası tutarlılık).
  const displayPositions = useMemo(() => {
    const bySymbol = new Map<string, Position>();
    for (const p of restPositions) bySymbol.set(p.symbol, p);
    for (const p of portfolio?.positions || []) {
      const existing = bySymbol.get(p.symbol);
      if (!existing || Number(p.entry_time || 0) >= Number(existing.entry_time || 0)) {
        bySymbol.set(p.symbol, p);
      }
    }
    return [...bySymbol.values()].sort((a, b) =>
      Number(b.entry_time || 0) - Number(a.entry_time || 0));
  }, [restPositions, portfolio]);

  // Performans istatistikleri: kapanmış işlemler + bugün
  // dayStart'ı ref olarak sakla — gece yarısı geçişlerinde doğru gün sınırını koru
  const dayStartRef = useRef(Math.floor(new Date().setHours(0, 0, 0, 0) / 1000));
  useEffect(() => {
    // Her dakika gün sınırını kontrol et — gece yarısı geşişini yakala
    const interval = setInterval(() => {
      const newDayStart = Math.floor(new Date().setHours(0, 0, 0, 0) / 1000);
      if (newDayStart !== dayStartRef.current) {
        dayStartRef.current = newDayStart;
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, []);
  const stats = useMemo(() => {
    const dayStart = dayStartRef.current;
    const closed = trades.filter((t) => Number(t.exit_time || 0) > 0);
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
    const netPnl = closed.reduce((a, t) => a + (t.pnl ?? 0), 0);
    const commission = closed.reduce((a, t) => a + (t.commission ?? 0), 0);
    const today = closed.filter((t) => Number(t.exit_time || 0) >= dayStart);
    const todayPnl = today.reduce((a, t) => a + (t.pnl ?? 0), 0);
    const openPnl = displayPositions.reduce((a, p) => a + (p.pnl_try ?? 0), 0);
    return {
      closedCount: closed.length, wins, winRate: closed.length ? wins / closed.length * 100 : null,
      netPnl, commission, todayCount: today.length, todayPnl, openPnl,
    };
  }, [trades, displayPositions]);

  const strategyStats = useMemo(() => {
    const map = new Map<string, { count: number; wins: number; pnl: number }>();
    for (const t of trades) {
      if (Number(t.exit_time || 0) <= 0) continue;
      const s = map.get(t.strategy) || { count: 0, wins: 0, pnl: 0 };
      s.count += 1; s.pnl += t.pnl ?? 0; if ((t.pnl ?? 0) > 0) s.wins += 1;
      map.set(t.strategy, s);
    }
    return [...map.entries()].sort((a, b) => b[1].pnl - a[1].pnl);
  }, [trades]);

  const pnlTone = (v: number) => v >= 0 ? "ui-tone-positive" : "ui-tone-negative";

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            {username ? (
              <>Hoş geldin, <span className="text-neon-green">{username.charAt(0).toUpperCase() + username.slice(1)}</span> 👋</>
            ) : (
              <>PORTFÖY & <span className="text-neon-green">SCALPING</span></>
            )}
          </h1>
          <p className="eyebrow mt-1">Sermaye durumu · işlem başarısı · canlı işlem akışı</p>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <button onClick={runManualVelocityScan} disabled={scanBusy} className="ui-button ui-button-primary disabled:cursor-wait disabled:opacity-60">
            {scanBusy ? "⚡ TARANIYOR…" : "🚀 MANUEL HIZ TARAMASI"}
          </button>
          <button onClick={() => setAlertsOpen(true)} className="ui-button ui-button-secondary">🔔 ALARMLAR</button>
        </div>
      </header>
      {msg && <div className="rounded-lg border px-3 py-2 text-xs font-mono border-neon-green/30 text-bunker-muted">{msg}</div>}
      {velocityStatus && (
        <div className="rounded-lg border border-bunker-700 bg-bunker-900/60 px-3 py-2 text-[11px] font-mono text-bunker-muted flex flex-wrap gap-x-4 gap-y-1">
          <span>⏱ Son otonom tarama: <b className={velocityStatus.last_scan_at ? (Math.floor(Date.now()/1000) - (velocityStatus.last_scan_at ?? 0) < 360 ? "text-neon-green" : "text-yellow-300") : "text-bunker-muted"}>{velocityStatus.last_scan_at ? new Date((velocityStatus.last_scan_at ?? 0)*1000).toLocaleTimeString("tr-TR") : "—"}</b></span>
          <span>📊 Son M5 kapanış: <b>{velocityStatus.last_m5_close_ms ? new Date((velocityStatus.last_m5_close_ms ?? 0)).toLocaleTimeString("tr-TR") : "—"}</b></span>
          <span>🎯 Havuz: <b>{velocityStatus.pool_size}</b> sembol</span>
          <span>🧩 Desen filtresi: <b className={velocityStatus.pattern_filter_enabled ? "text-neon-green" : "text-yellow-300"}>{velocityStatus.pattern_filter_enabled ? "AÇIK" : "KAPALI"}</b></span>
          <span>🛑 Stop: <b>%{velocityStatus.sl_pct}</b></span>
          <span>🟢 Otonom: <b className={velocityStatus.auto_enabled ? "text-neon-green" : "text-bunker-muted"}>{velocityStatus.auto_enabled ? "AÇIK" : "KAPALI"}</b></span>
        </div>
      )}

      {scanResult && (
        <div className="card space-y-3 border-sky-400/30 bg-sky-400/5">
          <div className="flex items-center justify-between">
            <p className="eyebrow text-sky-300">MANUEL HIZ AVCISI SONUCU</p>
            <span className="font-mono text-[10px] text-bunker-muted">{scanResult.best_candidate ? new Date().toLocaleTimeString("tr-TR") : ""}</span>
          </div>
          {scanResult.error && <p className="text-xs text-neon-red">{scanResult.error}</p>}
          {scanResult.message && <p className="text-xs text-yellow-300">{scanResult.message}</p>}
          {scanResult.best_candidate && (
            <div className="text-xs space-y-1">
              <p>
                En iyi aday: <b className="font-mono text-white">{scanResult.best_candidate.symbol}</b> · skor{" "}
                <b className="text-neon-green">{scanResult.best_candidate.velocity_score}</b> · mod{" "}
                {scanResult.best_candidate.mode === "v_donusu" ? "V-dönüşü" : "trend-devam"} · ATR %{scanResult.best_candidate.atr_pct} · RSI {scanResult.best_candidate.rsi} · MFI {scanResult.best_candidate.mfi}
              </p>
              <p>
                <span className="text-bunker-muted">M5 momentum deseni:</span>{" "}
                {scanResult.best_candidate.m5_pattern_ok
                  ? <b className="text-neon-green">✓ UYGUN (6/6)</b>
                  : <b className="text-red-400">✗ GEÇMEDİ</b>}{" "}
                <span className="text-[10px] text-bunker-muted">
                  {scanResult.best_candidate.m5_pattern
                    ? Object.entries(scanResult.best_candidate.m5_pattern)
                        .filter(([, v]) => v === false)
                        .map(([k]) => k.replace("g0_", "").replace("g1_", "").replace("g2_", ""))
                        .join(", ") || "tümü sağlandı"
                    : "veri yok"}
                </span>
              </p>
              <p className={scanResult.opened ? "text-neon-green font-bold" : "text-yellow-300"}>
                {scanResult.opened
                  ? `✓ PAPER POZİSYON AÇILDI · ${scanResult.outcome.order_value_try} TL · stop %${scanResult.outcome.stop_loss_pct}`
                  : `İşlem açılmadı: ${scanResult.outcome?.reason || scanResult.outcome?.status || "bilinmiyor"}`}
              </p>
            </div>
          )}
          {scanResult.scan5?.candidates?.length > 0 && (
            <div>
              <p className="eyebrow mb-1">5 DK %2 GEÇENLER</p>
              <div className="flex flex-wrap gap-1.5">
                {scanResult.scan5.candidates.map((c: any) => (
                  <span key={c.symbol} className="rounded border border-neon-green/40 bg-neon-green/5 px-2 py-0.5 font-mono text-[10px] text-neon-green">{c.symbol} · skor {c.velocity_score}</span>
                ))}
              </div>
            </div>
          )}
          {scanResult.scan15?.candidates?.length > 0 && (
            <div>
              <p className="eyebrow mb-1">15 DK %3 GEÇENLER</p>
              <div className="flex flex-wrap gap-1.5">
                {scanResult.scan15.candidates.map((c: any) => (
                  <span key={c.symbol} className="rounded border border-sky-400/40 bg-sky-400/5 px-2 py-0.5 font-mono text-[10px] text-sky-300">{c.symbol} · skor {c.velocity_score}</span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] text-bunker-muted">Uygun aday bulunursa otonom döngüyle aynı risk kapılarından geçirilip serbest TL'nin %50'si ile paper pozisyon açılır (stop %1.5, break-even → +%1'de ATR trailing).</p>
        </div>
      )}

      {/* ÜST: Dinamik portföy bilgileri */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard label="TOPLAM DEĞER" value={`₺${money(portfolio?.total_value)}`} />
        <MetricCard label="MEVCUT TL" value={`₺${money(portfolio?.try)}`} tone="ui-tone-positive" />
        <MetricCard label="AÇIK POZİSYON" value={displayPositions.length} />
        <MetricCard label="AÇIK PnL" value={`₺${money(stats.openPnl)}`} tone={pnlTone(stats.openPnl)} />
        <MetricCard label="GERÇEKLEŞEN PnL" value={`₺${money(portfolio?.realized_pnl ?? stats.netPnl)}`} tone={pnlTone(portfolio?.realized_pnl ?? stats.netPnl)} />
      </div>

      {/* ORTA: Kapanmış/açık işlem başarı kartları */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <MetricCard label="KAPANMIŞ İŞLEM" value={stats.closedCount} />
        <MetricCard label="BAŞARI ORANI" value={stats.winRate != null ? `%${stats.winRate.toFixed(1)}` : "—"} tone={stats.winRate != null && stats.winRate >= 50 ? "ui-tone-positive" : "ui-tone-negative"} />
        <MetricCard label="NET PnL" value={`₺${money(stats.netPnl)}`} tone={pnlTone(stats.netPnl)} />
        <MetricCard label="BUGÜN İŞLEM" value={stats.todayCount} />
        <MetricCard label="BUGÜN PnL" value={`₺${money(stats.todayPnl)}`} tone={pnlTone(stats.todayPnl)} />
        <MetricCard label="KOMİSYON" value={`₺${money(stats.commission)}`} />
      </div>

      {/* Açık pozisyonlar + strateji performansı yan yana */}
      <div className="grid lg:grid-cols-2 gap-6">
        <section className="ui-card portfolio-table-card">
          <div className="ui-section-header">
            <div>
              <p className="eyebrow">AÇIK POZİSYONLAR</p>
              <p className="ui-section-description">Anlık değerler ve paper pozisyon yönetimi</p>
            </div>
          </div>
          <div className="table-scroll mt-3">
            <table className="data-table">
              <thead><tr><th>Sembol</th><th>Strateji</th><th>PnL</th><th>%</th><th>İşlem</th></tr></thead>
              <tbody>
                {displayPositions.map((p) => (
                  <tr key={p.symbol}>
                    <td><SymbolLink symbol={p.symbol} className="text-white hover:text-neon-green" /></td>
                    <td className="text-xs">{STRATEGY_LABEL[p.strategy || ""] || p.strategy || "—"}</td>
                    <td className={pnlTone(p.pnl_try ?? 0)}>₺{money(p.pnl_try ?? 0)}</td>
                    <td className={pnlTone(p.pnl_pct)}>{pnlText(p.pnl_pct)}</td>
                    <td><button onClick={() => closePosition(p.symbol)} disabled={closing !== null} className="rounded border border-red-400/50 bg-red-400/10 px-2 py-1 font-mono text-[10px] text-red-300 disabled:opacity-50">{closing === p.symbol ? "…" : "KAPAT"}</button></td>
                  </tr>
                ))}
                {!displayPositions.length && <tr><td colSpan={5} className="py-6 text-center text-bunker-muted">{liveStatus === "open" ? "Açık pozisyon yok; otonom hız avcısı yeni fırsat arıyor." : "Pozisyon verisi alınamıyor — bağlantı durumu: " + liveStatus}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
        <section className="ui-card">
          <div className="ui-section-header"><div><p className="eyebrow">STRATEJİ PERFORMANSI</p><p className="ui-section-description">Kapanmış paper işlemler, komisyon sonrası net sonuç.</p></div><span className="font-mono text-xs text-bunker-muted">{trades.length} işlem</span></div>
          <div className="table-scroll mt-3">
            <table className="data-table">
              <thead><tr><th>Strateji</th><th>İşlem</th><th>Başarı</th><th>Net PnL</th></tr></thead>
              <tbody>
                {strategyStats.map(([name, stat]) => (
                  <tr key={name}>
                    <td className="text-xs">{STRATEGY_LABEL[name] || name}</td>
                    <td>{stat.count}</td>
                    <td className={stat.wins / stat.count >= .5 ? "ui-tone-positive" : "ui-tone-negative"}>%{(stat.wins / stat.count * 100).toFixed(1)}</td>
                    <td className={pnlTone(stat.pnl)}>₺{money(stat.pnl)}</td>
                  </tr>
                ))}
                {!strategyStats.length && <tr><td colSpan={4} className="py-6 text-center text-bunker-muted">Kapanmış işlem verisi bekleniyor.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* ALT: Dinamik log ekranı */}
      <section className="card bg-bunker-950 p-0 overflow-hidden">
        <div className="p-4 border-b border-bunker-800 flex justify-between items-center">
          <p className="eyebrow">CANLI İŞLEM AKIŞI (DİNAMİK LOG)</p>
          {liveStatus === "open"
            ? <span className="text-xs text-neon-green font-mono animate-pulse">● LIVE</span>
            : <span className="text-xs font-mono text-yellow-300">{liveStatus === "connecting" ? "○ BAĞLANIYOR" : "○ BAĞLANTI YOK"}</span>}
        </div>
        <div className="p-4 font-mono text-sm h-72 overflow-y-auto">
          {signals.length === 0 && <p className="text-bunker-muted">$ Otonom hız avcısı çalışıyor, sinyal bekleniyor…</p>}
          {signals.map((s, i) => (
            <div key={s.id ?? `${s.timestamp}-${s.symbol}-${s.action}-${i}`} className={`trade-log-row py-1 ${s.action === "BUY_BLOCKED" ? "text-sky-400" : s.action.includes("BUY") ? "text-neon-green" : "text-neon-red"}`}>
              <span className="text-bunker-muted">[{s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString("tr-TR") : "--"}]</span>{" "}
              <span className="font-bold">{s.action}</span>{" "}
              <SymbolLink symbol={s.symbol} className="font-bold text-current hover:text-white" /> {s.price ? `@ ₺${s.price.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : ""}{" "}
              {s.reason && <span className="text-bunker-muted text-xs">· {s.reason}</span>}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </section>

      {alertsOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4" onClick={() => setAlertsOpen(false)}><div className="max-h-[90dvh] w-full max-w-6xl overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl" onClick={event => event.stopPropagation()}><div className="mb-3 flex justify-end"><button onClick={() => setAlertsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Alarm modalını kapat">✕ KAPAT</button></div><AlertPanel modal /></div></div>}
    </div>
  );
}
