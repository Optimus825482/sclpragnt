"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";
import LlmManagement from "./LlmManagement";

type Config = {
  symbols: string[];
  min_notional: number;
  default_order_usdt: number;
  active_strategy: string;
  active_strategy_timeframe: string;
  order_pct: number;
  pyramiding_layers: number;
  bb_mfi_stop_loss_pct: number;
  bb_mfi_take_profit_pct: number;
  symbol_order_pct: Record<string, number>;
  symbol_pyramiding_layers: Record<string, number>;
  min_24h_quote_volume_try: number;
  high_liquidity_bypass_volume_try: number;
  min_volume_ratio: number;
  max_spread_pct: number;
  min_orderbook_depth_multiplier: number;
  max_open_positions: number;
  hard_stop_loss_pct: number;
  cooldown_bars: number;
  take_profit_pct: number;
  trailing_stop_pct: number;
  ut_enabled: boolean;
  ut_symbols: string[];
  ut_key_value: number;
  ut_atr_period: number;
  ut_heikin_ashi: boolean;
  initial_balance_try: number;
  mode: string;
  market_data: string;
  gainer_radar_min_score: number;
  adr_filter_enabled: boolean;
  adr_period: number;
  adr_min_pct: number;
  adr_max_utilization_pct: number;
  adr_min_remaining_pct: number;
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"symbols" | "app" | "strategies" | "llm" | "scan-logs">("symbols");
  const [cfg, setCfg] = useState<Config | null>(null);
  const [draft, setDraft] = useState<Partial<Config>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetDone, setResetDone] = useState(false);
  const [marketSymbols, setMarketSymbols] = useState<string[]>([]);
  const [symbolQuery, setSymbolQuery] = useState("");
  const [backingUp, setBackingUp] = useState(false);
  const [backupDone, setBackupDone] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [reconcileDone, setReconcileDone] = useState(false);
  const [llm, setLlm] = useState<any>({ providers: [], models: [], skills: [], active_model_id: null, encryption_configured: false });
  const [llmForm, setLlmForm] = useState({ name: "OpenAI Compatible", base_url: "", api_key: "", provider_id: "", model: "", model_type: "chat", dimensions: "", skill: "", instructions: "" });
  const [llmMessage, setLlmMessage] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillDone, setBackfillDone] = useState(false);
  const [repairingMemory, setRepairingMemory] = useState(false);
  const [scanLogs, setScanLogs] = useState<any[]>([]);
  const [scanLogFilter, setScanLogFilter] = useState<"all" | "automatic" | "manual">("all");
  const [activity, setActivity] = useState<Record<string, any>>({});
  const [activityFilter, setActivityFilter] = useState<"all" | "ACTIVE" | "PASSIVE" | "WARMING">("all");

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((r) => r.json())
      .then((d) => { setCfg(d); setDraft(d); })
      .catch(() => setError("Backend'e bağlanılamadı (http://localhost:8004)"));
    fetch(`${API_BASE}/api/market-symbols`)
      .then((r) => r.json())
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch(() => setError("Binance TR sembolleri alınamadı"));
    fetch(`${API_BASE}/api/llm/config`).then((r) => r.json()).then(setLlm).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (activeTab !== "scan-logs") return;
    let cancelled = false;
    const load = () => fetch(`${API_BASE}/api/strategy/scan-logs?limit=1000${scanLogFilter === "all" ? "" : `&scan_type=${scanLogFilter}`}`)
      .then((r) => r.json()).then((d) => { if (!cancelled) setScanLogs(d.logs || []); }).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [activeTab, scanLogFilter]);

  useEffect(() => {
    const load = () => fetch(`${API_BASE}/api/symbol-activity`, { cache: "no-store" }).then((r) => r.json()).then((d) => setActivity(d.statuses || {})).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft)
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Ayarlar kaydedilemedi");
      const updated = await res.json();
      setCfg(updated);
      setDraft(updated);
      setSaved(true);
      window.alert("Ayarlar başarıyla kaydedildi.");
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kaydedilemedi - backend bağlantısını kontrol et");
    } finally {
      setSaving(false);
    }
  };

  const num = (v: any) => (typeof v === "number" ? v : parseFloat(v));
  const selectedSymbols = Array.from(new Set((draft.symbols || []).map((symbol) => String(symbol).replace(/_/g, "").toUpperCase()))).sort();
  const filteredSymbols = marketSymbols.filter((s) => s.includes(symbolQuery.trim().toUpperCase()));
  const visibleActivity = Object.values(activity).filter((item: any) => activityFilter === "all" || item.status === activityFilter).filter((item: any) => !symbolQuery.trim() || item.symbol.includes(symbolQuery.trim().toUpperCase()));
  const activityCounts = { ACTIVE: Object.values(activity).filter((x: any) => x.status === "ACTIVE").length, PASSIVE: Object.values(activity).filter((x: any) => x.status === "PASSIVE").length, WARMING: Object.values(activity).filter((x: any) => x.status === "WARMING").length };
  const toggleSymbol = (symbol: string) => setDraft((d) => {
    const normalized = String(symbol).replace(/_/g, "").toUpperCase();
    const current = Array.from(new Set((d.symbols || []).map((item) => String(item).replace(/_/g, "").toUpperCase())));
    return { ...d, symbols: current.includes(normalized) ? current.filter((item) => item !== normalized) : [...current, normalized] };
  });

  const resetTradingData = async () => {
    if (!window.confirm("Tüm eski işlemler, sinyaller, karar logları, backtestler, snapshotlar, açık emirler ve sanal cüzdan silinecek. Strateji/LLM ayarları ve piyasa verileri korunacak. Cüzdan 10.000 TL ile başlayacak. Devam edilsin mi?")) return;
    setResetting(true);
    setError(null);
    setResetDone(false);
    try {
      const res = await fetch(`${API_BASE}/api/reset`, { method: "POST" });
      if (!res.ok) throw new Error("reset failed");
      setResetDone(true);
      setTimeout(() => setResetDone(false), 3000);
    } catch {
      setError("Kayıtlar sıfırlanamadı - backend bağlantısını kontrol et");
    } finally {
      setResetting(false);
    }
  };

  const reconcilePortfolio = async () => {
    setReconciling(true); setError(null);
    try {
      const previewResponse = await fetch(`${API_BASE}/api/portfolio/reconcile`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: false }) });
      const preview = await previewResponse.json();
      if (!previewResponse.ok) throw new Error(preview.detail || "Mutabakat önizlemesi alınamadı");
      const targets = preview.would_remove || [];
      const detail = targets.length ? `\nSilinecek açık pozisyonlar ve ilişkili açılış kayıtları:\n- ${targets.map((item:any) => `${item.symbol} · ₺${Number(item.cost).toFixed(2)}`).join("\n- ")}` : "\nSilinecek pozisyon yok; yalnızca bakiye yeniden hesaplanacak.";
      if (!window.confirm(`Portföy mutabakatı önizlemesi hazır.${detail}\n\nDevam edilsin mi?`)) return;
      const response = await fetch(`${API_BASE}/api/portfolio/reconcile`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Portföy mutabakatı başarısız");
      setReconcileDone(true);
      const removed = (body.removed_overallocated_positions || []).map((item:any) => item.symbol).join(", ");
      window.alert(`Portföy mutabakatı tamamlandı. TRY: ₺${Number(body.after_try).toFixed(2)}${removed ? `\nTemizlenen sermaye aşımı pozisyonları: ${removed}` : ""}`);
      setTimeout(() => setReconcileDone(false), 2500);
    } catch (err) { setError(err instanceof Error ? err.message : "Portföy mutabakatı başarısız"); }
    finally { setReconciling(false); }
  };

  const backfillEmbeddings = async () => {
    if (!window.confirm("Mevcut işlem ve sinyal kayıtları embedding modeline gönderilecek. Kayıtlar silinmeyecek. Devam edilsin mi?")) return;
    setBackfilling(true); setLlmMessage(null);
    try {
      const response = await fetch(`${API_BASE}/api/memory/backfill`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Embedding backfill başlatılamadı");
      setBackfillDone(true);
      setLlmMessage(`${body.queued || 0} kayıt embedding kuyruğuna alındı.`);
      setTimeout(() => setBackfillDone(false), 3000);
    } catch (err) { setLlmMessage(err instanceof Error ? err.message : "Embedding backfill başarısız"); }
    finally { setBackfilling(false); }
  };

  const repairHistoricalMemory = async () => {
    if (!window.confirm("Eksik tarihsel likidite alanları tahmin edilmeden işaretlenecek ve ilgili embedding kayıtları yeniden üretilecek. Devam edilsin mi?")) return;
    setRepairingMemory(true); setLlmMessage(null);
    try {
      const response = await fetch(`${API_BASE}/api/memory/repair-historical`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Tarihsel memory onarımı başlatılamadı");
      setLlmMessage(`${body.queued || 0} tarihsel snapshot yeniden embedding kuyruğuna alındı.`);
    } catch (err) { setLlmMessage(err instanceof Error ? err.message : "Tarihsel memory onarımı başarısız"); }
    finally { setRepairingMemory(false); }
  };

  const reloadLlm = async () => setLlm(await (await fetch(`${API_BASE}/api/llm/config`, { cache: "no-store" })).json());
  const llmRequest = async (url: string, options: RequestInit, success: string) => {
    setLlmMessage(null);
    try {
      const response = await fetch(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) throw new Error(body.detail || body.error || "İşlem başarısız");
      await reloadLlm();
      setLlmMessage(success);
      window.alert(`${success}.`);
    } catch (err) {
      setLlmMessage(err instanceof Error ? err.message : "LLM işlemi başarısız");
    }
  };

  const downloadBackup = async () => {
    setBackingUp(true);
    setError(null);
    setBackupDone(false);
    try {
      const res = await fetch(`${API_BASE}/api/backup`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Yedekleme başarısız (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const disposition = res.headers.get("content-disposition") || "";
      const serverFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      anchor.download = serverFilename || `scalperagent-postgres-${new Date().toISOString().replace(/[:.]/g, "-")}.dump`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setBackupDone(true);
      setTimeout(() => setBackupDone(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "PostgreSQL veritabanı yedeği alınamadı");
    } finally {
      setBackingUp(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            <span className="text-neon-green">AYARLAR</span>
          </h1>
          <p className="eyebrow mt-1">Strateji parametreleri - anında uygulanır</p>
        </div>
        {cfg && (
          <button
            onClick={save}
            disabled={saving}
            className={`px-5 py-2 rounded-lg border font-mono text-sm transition-colors ${saved
              ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
              : "border-neon-green/40 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"
              }`}
          >
            {saving ? "KAYDEDİLİYOR..." : saved ? "✓ KAYDEDİLDİ" : "KAYDET"}
          </button>
        )}
      </header>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/5">
          <p className="font-mono text-sm text-neon-red">{error}</p>
        </div>
      )}

      {!cfg && !error && (
        <div className="card"><p className="font-mono text-sm text-bunker-muted animate-pulse">Yükleniyor...</p></div>
      )}

      {cfg && (
        <nav className="flex gap-2 overflow-x-auto border-b border-bunker-800 pb-2" aria-label="Ayar sekmeleri">
          {([
            ["symbols", "Semboller", "🪙"],
            ["app", "Uygulama Ayarları", "⚙️"],
            ["strategies", "Strateji Ayarları", "📈"],
            ["llm", "LLM / Provider", "🤖"],
            ["scan-logs", "Tarama Logları", "🧾"],
          ] as const).map(([key, label, icon]) => (
            <button key={key} onClick={() => setActiveTab(key)} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${activeTab === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>
              {icon} {label}
            </button>
          ))}
        </nav>
      )}

      {cfg && (
        <>
          <div className={`card bg-bunker-950 ${activeTab !== "scan-logs" ? "hidden" : ""}`}>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div>
                <p className="eyebrow text-neon-green">SEMBOL BAZLI TARAMA KANITI</p>
                <p className="text-xs text-bunker-muted mt-1">Otomatik 5m kapanış taraması ve manuel kontrolün her sembol için sonucu. Son kayıtlar RAM&apos;de sınırlı tutulur.</p>
              </div>
              <select value={scanLogFilter} onChange={(e) => setScanLogFilter(e.target.value as typeof scanLogFilter)} className="input w-auto">
                <option value="all">Tümü</option><option value="automatic">Otomatik tarama</option><option value="manual">Manuel tarama</option>
              </select>
            </div>
            <div className="max-h-[65vh] overflow-auto rounded-lg border border-bunker-800">
              <table className="w-full text-left font-mono text-[11px]"><thead className="sticky top-0 bg-bunker-900 text-bunker-muted"><tr><th className="px-3 py-2">ZAMAN</th><th className="px-3 py-2">TÜR</th><th className="px-3 py-2">SEMBOL</th><th className="px-3 py-2">SONUÇ</th><th className="px-3 py-2">FİYAT</th><th className="px-3 py-2">NEDEN</th></tr></thead><tbody>
                {scanLogs.map((log, index) => <tr key={`${log.timestamp}-${log.symbol}-${index}`} className="border-t border-bunker-800/70"><td className="px-3 py-2 text-bunker-muted">{new Date(log.timestamp * 1000).toLocaleTimeString("tr-TR")}</td><td className="px-3 py-2 text-sky-300">{log.scan_type === "manual" ? "MANUEL" : "OTOMATİK"}</td><td className="px-3 py-2 text-white">{log.symbol}</td><td className={`px-3 py-2 ${String(log.status).includes("SIGNAL") ? "text-neon-green" : String(log.status).includes("ERROR") ? "text-red-300" : "text-yellow-300"}`}>{log.status}</td><td className="px-3 py-2 text-bunker-muted">{log.price ?? "—"}</td><td className="px-3 py-2 text-bunker-muted">{log.reason || log.error || "—"}</td></tr>)}
                {!scanLogs.length && <tr><td colSpan={6} className="px-3 py-8 text-center text-bunker-muted">Henüz tarama kaydı yok. Otomatik veya manuel tarama çalıştığında burada görünecek.</td></tr>}
              </tbody></table>
            </div>
          </div>
          <div className={`card bg-bunker-950 ${activeTab !== "symbols" ? "hidden" : ""}`}>
            <div className="flex justify-between items-center mb-4">
              <div>
                <p className="eyebrow">BINANCE TR SEMBOLLERİ</p>
                <p className="text-xs text-bunker-muted mt-1">Arayın, seçerek ekleyin; seçili sembolleri aktif/pasif yapın.</p>
              </div>
              <span className="font-mono text-xs text-bunker-muted">{selectedSymbols.length} aktif</span>
            </div>
            <input
              value={symbolQuery}
              onChange={(e) => setSymbolQuery(e.target.value)}
              placeholder="Sembol ara: BTC, ETH, SOL..."
              className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white placeholder-bunker-700 outline-none focus:border-neon-green/50"
            />
            <div className="flex flex-wrap gap-2 mt-3 max-h-36 overflow-y-auto">
              {filteredSymbols.map((symbol) => {
                const active = selectedSymbols.includes(symbol);
                return <button key={symbol} onClick={() => toggleSymbol(symbol)} className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${active ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>{active ? "✓ " : "+ "}{symbol}</button>;
              })}
              {!filteredSymbols.length && <span className="text-xs text-bunker-muted font-mono">Sembol bulunamadı</span>}
            </div>
            <div className="mt-4 pt-3 border-t border-bunker-800/60">
              <p className="eyebrow mb-2">AKTİF TARAMA SEMBOLLERİ · {selectedSymbols.length}</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {selectedSymbols.map((symbol) => <button key={symbol} onClick={() => toggleSymbol(symbol)} className="flex min-h-10 items-center justify-between gap-2 rounded-lg border border-neon-green/60 bg-neon-green/15 px-3 py-2 text-left font-mono text-xs text-neon-green"><span>AKTİF · {symbol}</span><span aria-hidden="true">×</span></button>)}
                {!selectedSymbols.length && <p className="col-span-full rounded-lg border border-yellow-400/40 bg-yellow-400/5 px-3 py-3 font-mono text-xs text-yellow-300">Aktif tarama sembolü seçilmedi.</p>}
              </div>
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <div><p className="eyebrow text-neon-green">GERÇEK AKTİVİTE DURUMU</p><p className="text-xs text-bunker-muted mt-1">30 saniyede bir yenilenir. Aktiflik; 30m hareket, ATR, mum hacmi ve spread kontrolleriyle hesaplanır.</p></div>
                <div className="flex flex-wrap gap-2 text-[11px] font-mono"><span className="rounded border border-neon-green/40 px-2 py-1 text-neon-green">AKTİF {activityCounts.ACTIVE}</span><span className="rounded border border-yellow-400/40 px-2 py-1 text-yellow-300">PASİF {activityCounts.PASSIVE}</span><span className="rounded border border-sky-400/40 px-2 py-1 text-sky-300">ISINIYOR {activityCounts.WARMING}</span></div>
              </div>
              <div className="flex flex-wrap gap-2 mb-3">{([ ["all", "TÜMÜ"], ["ACTIVE", "AKTİF"], ["PASSIVE", "PASİF"], ["WARMING", "ISINIYOR"] ] as const).map(([key, label]) => <button key={key} onClick={() => setActivityFilter(key)} className={`rounded-lg border px-3 py-1.5 font-mono text-xs ${activityFilter === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green" : "border-bunker-700 text-bunker-muted"}`}>{label}</button>)}</div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-[32rem] overflow-y-auto pr-1">
                {visibleActivity.map((item: any) => <div key={item.symbol} className={`rounded-lg border px-3 py-2 ${item.status === "ACTIVE" ? "border-neon-green/30 bg-neon-green/5" : item.status === "WARMING" ? "border-sky-400/30 bg-sky-400/5" : "border-bunker-800 bg-bunker-900/60"}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-sm text-white">{item.symbol}</span><span className={`font-mono text-[10px] ${item.status === "ACTIVE" ? "text-neon-green" : item.status === "WARMING" ? "text-sky-300" : "text-yellow-300"}`}>{item.status}</span></div><div className="mt-2 grid grid-cols-3 gap-2 text-[10px] font-mono text-bunker-muted"><span>30m {item.range_30m_pct == null ? "—" : `${item.range_30m_pct}%`}</span><span>ATR {item.atr_pct == null ? "—" : `${item.atr_pct}%`}</span><span>VOL {item.volume_ratio == null ? "—" : `${item.volume_ratio}x`}</span></div><p className="mt-2 truncate text-[10px] text-bunker-muted" title={item.reason || ""}>{item.reason || "—"}{item.spread_pct != null ? ` · spread ${item.spread_pct}%` : ""}</p></div>)}
                {!visibleActivity.length && <p className="col-span-full py-6 text-center font-mono text-xs text-bunker-muted">Aktivite verisi henüz hazır değil.</p>}
              </div>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="border-b border-bunker-800 pb-5 mb-5">
              <p className="eyebrow text-neon-green">CANLI STRATEJİ / POZİSYON BOYUTU</p>
              <p className="text-xs text-bunker-muted mt-1">Yeni strateji paper canlı akışında kullanılır. Varsayılan başlangıç: bakiye %10 ve en fazla 2 katman.</p>
              <div className="grid sm:grid-cols-3 gap-3 mt-3">
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Strateji</span><select value={draft.active_strategy || "BB_MFI_MEAN_REVERSION"} onChange={e => setDraft(d => ({ ...d, active_strategy: e.target.value }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white"><option value="BB_MFI_MEAN_REVERSION">BB + MFI Mean Reversion</option></select></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Timeframe</span><select value={draft.active_strategy_timeframe || "5m"} onChange={e => setDraft(d => ({ ...d, active_strategy_timeframe: e.target.value }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white"><option>5m</option><option>1m</option><option>15m</option></select></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Global işlem yüzdesi</span><input type="number" min={0.1} max={100} step={0.5} value={num(draft.order_pct) * 100} onChange={e => setDraft(d => ({ ...d, order_pct: Number(e.target.value) / 100 }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Global piramitleme</span><input type="number" min={1} max={10} step={1} value={num(draft.pyramiding_layers)} onChange={e => setDraft(d => ({ ...d, pyramiding_layers: Number(e.target.value) }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">BB-MFI stop (%)</span><input type="number" min={0.1} max={99} step={0.1} value={num(draft.bb_mfi_stop_loss_pct) * 100} onChange={e => setDraft(d => ({ ...d, bb_mfi_stop_loss_pct: Number(e.target.value) / 100 }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">BB-MFI hedef (%)</span><input type="number" min={0.1} max={99} step={0.1} value={num(draft.bb_mfi_take_profit_pct) * 100} onChange={e => setDraft(d => ({ ...d, bb_mfi_take_profit_pct: Number(e.target.value) / 100 }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
              </div>
              <p className="eyebrow mt-4">SEMBOL BAZLI OVERRIDE · BOŞSA GLOBAL DEĞER KULLANILIR</p>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2 mt-2">{(draft.symbols || []).map(symbol => <div key={symbol} className="flex items-center gap-2 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-white flex-1">{symbol}</span><input aria-label={`${symbol} işlem yüzdesi`} type="number" min={0.1} max={100} step={0.5} placeholder={`${num(draft.order_pct) * 100}%`} value={draft.symbol_order_pct?.[symbol] == null ? "" : Number(draft.symbol_order_pct[symbol] * 100)} onChange={e => setDraft(d => ({ ...d, symbol_order_pct: { ...(d.symbol_order_pct || {}), [symbol]: e.target.value === "" ? undefined as any : Number(e.target.value) / 100 } }))} className="w-20 bg-bunker-950 border border-bunker-700 rounded px-2 py-1 font-mono text-[11px] text-white" /><input aria-label={`${symbol} piramitleme`} type="number" min={1} max={10} step={1} placeholder={String(draft.pyramiding_layers || 2)} value={draft.symbol_pyramiding_layers?.[symbol] ?? ""} onChange={e => setDraft(d => ({ ...d, symbol_pyramiding_layers: { ...(d.symbol_pyramiding_layers || {}), [symbol]: e.target.value === "" ? undefined as any : Number(e.target.value) } }))} className="w-14 bg-bunker-950 border border-bunker-700 rounded px-2 py-1 font-mono text-[11px] text-white" /></div>)}</div>
            </div>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="eyebrow">GAINER RADAR MİNİMUM SKOR</p>
                <p className="text-xs text-bunker-muted mt-1">Radar şu anda yalnızca gözlem ve sıralama yapar; otomatik paper işlem açmaz. Önerilen başlangıç: 50.</p>
              </div>
              <input type="number" min={0} max={100} step={1} value={num(draft.gainer_radar_min_score)} onChange={(e) => setDraft((d) => ({ ...d, gainer_radar_min_score: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none" />
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <p className="eyebrow">LİKİDİTE FİLTRESİ</p>
              <p className="text-xs text-bunker-muted mt-1">İşlem açılmadan önce düşük hacim, geniş spread ve sığ emir defteri engellenir.</p>
              <div className="grid sm:grid-cols-2 gap-3 mt-3">
                {([
                  ["min_24h_quote_volume_try", "Minimum 24s hacim (TL)", 1000],
                  ["high_liquidity_bypass_volume_try", "Yüksek likidite eşiği (TL)", 1000],
                  ["min_volume_ratio", "Minimum hacim oranı", 0.1],
                  ["max_spread_pct", "Maksimum spread (%)", 0.01],
                  ["min_orderbook_depth_multiplier", "Emir defteri çarpanı", 0.5],
                ] as const).map(([key, label, step]) => (
                  <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2">
                    <span className="font-mono text-xs text-bunker-muted">{label}</span>
                    <input type="number" min={0} step={step} value={num((draft as any)[key])} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" />
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Önerilen: 1.000.000 TL · 0,3x · %0,30 · 5x</p>
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <p className="eyebrow">MTF MOMENTUM · ADR FİLTRESİ</p>
              <p className="text-xs text-bunker-muted mt-1">Yalnızca MTF Momentum girişlerinde, sembolün günlük hareket kapasitesi ve gün içi aşırı uzama kontrol edilir.</p>
              <div className="grid sm:grid-cols-2 gap-3 mt-3">
                <label className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">ADR filtresi</span><input type="checkbox" checked={Boolean(draft.adr_filter_enabled)} onChange={(e) => setDraft((d) => ({ ...d, adr_filter_enabled: e.target.checked }))} /></label>
                {([ ["adr_period", "ADR periyodu (gün)", 1], ["adr_min_pct", "Minimum ADR (%)", 0.1], ["adr_max_utilization_pct", "Maksimum kullanım (%)", 0.01], ["adr_min_remaining_pct", "Minimum kalan hareket (%)", 0.1] ] as const).map(([key, label, step]) => <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">{label}</span><input type="number" min={0} step={step} value={key === "adr_period" ? num((draft as any)[key]) : num((draft as any)[key]) * 100} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : key === "adr_period" ? Number(e.target.value) : Number(e.target.value) / 100 }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" /></label>)}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Başlangıç: 14 gün · minimum ADR %2 · gün içi kullanım en fazla %80 · kalan kapasite en az %1</p>
            </div>
          </div>
          <div className={`space-y-4 ${activeTab !== "llm" ? "hidden" : ""}`}>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">LLM PROVIDER EKLE</p><p className="text-xs text-bunker-muted mb-3">Yalnızca teknik yorum üretir; emir veya pozisyon kararı vermez.</p><div className="grid md:grid-cols-2 gap-3"><input placeholder="Provider adı" value={llmForm.name} onChange={e => setLlmForm({...llmForm,name:e.target.value})} className="input" /><input placeholder="Base URL (https://.../v1)" value={llmForm.base_url} onChange={e => setLlmForm({...llmForm,base_url:e.target.value})} className="input" /><input type="password" placeholder="API key" value={llmForm.api_key} onChange={e => setLlmForm({...llmForm,api_key:e.target.value})} className="input" /><button onClick={() => llmRequest(`${API_BASE}/api/llm/providers`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(llmForm)}, "Provider kaydedildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">PROVIDER KAYDET</button></div><p className="text-xs text-bunker-muted mt-3">Şifreleme anahtarı: {llm.encryption_configured ? "hazır" : "sunucuda LLM_ENCRYPTION_KEY eksik"}</p></div>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">MODEL / UZMANLIK</p><div className="grid md:grid-cols-2 gap-3"><select value={llmForm.provider_id} onChange={e => setLlmForm({...llmForm,provider_id:e.target.value})} className="input"><option value="">Provider seç</option>{llm.providers.map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}</select><input placeholder="Model adı" value={llmForm.model} onChange={e => setLlmForm({...llmForm,model:e.target.value})} className="input" /><select value={llmForm.model_type} onChange={e => setLlmForm({...llmForm,model_type:e.target.value})} className="input"><option value="chat">Chat modeli</option><option value="embedding">Embedding modeli</option></select>{llmForm.model_type === "embedding" && <input type="number" min="1" placeholder="Embedding dimension" value={llmForm.dimensions} onChange={e => setLlmForm({...llmForm,dimensions:e.target.value})} className="input" />}<button onClick={() => llmRequest(`${API_BASE}/api/llm/models`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:Number(llmForm.provider_id),name:llmForm.model,model_type:llmForm.model_type,dimensions:llmForm.dimensions ? Number(llmForm.dimensions) : undefined})}, "Model kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">MODEL EKLE</button>{llmForm.model_type === "embedding" && <button onClick={async () => { const r=await fetch(`${API_BASE}/api/llm/embedding/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"embedding bağlantı testi"})}); const b=await r.json(); const m=b.status === "ok" ? `Embedding başarılı · ${b.dimensions} dimension` : (b.error || "Embedding testi başarısız"); setLlmMessage(m); window.alert(m); }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">EMBEDDING TEST ET</button>}<input placeholder="Uzmanlık adı" value={llmForm.skill} onChange={e => setLlmForm({...llmForm,skill:e.target.value})} className="input" /><textarea placeholder="Uzmanlık talimatları" value={llmForm.instructions} onChange={e => setLlmForm({...llmForm,instructions:e.target.value})} className="input min-h-24" /><button onClick={() => llmRequest(`${API_BASE}/api/llm/skills`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:llmForm.skill,instructions:llmForm.instructions})}, "Uzmanlık kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">UZMANLIK EKLE</button></div>{llmMessage && <p className="text-xs text-neon-green mt-3">{llmMessage}</p>}</div>
            <div className="card bg-bunker-950 flex flex-wrap gap-3"><select value={llm.active_model_id || ""} onChange={async e => { const id=Number(e.target.value); await llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:id})}, "LLM aktif edildi"); }} className="input"><option value="">Aktif model seç</option>{llm.models.map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}</select><button onClick={() => llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:llm.active_model_id})}, "LLM aktif edildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">LLM AKTİF</button><button onClick={async () => { setLlmMessage("TEST EDİLİYOR..."); try { const r=await fetch(`${API_BASE}/api/llm/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const body=await r.json(); const message=body.status === "ok" ? "Bağlantı başarılı" : (body.error || body.status || "Test başarısız"); setLlmMessage(message); window.alert(message); } catch { setLlmMessage("LLM test bağlantısı kurulamadı"); window.alert("LLM test bağlantısı kurulamadı"); } }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">TEST ET</button></div>
            <div className="card border-purple-400/30 bg-purple-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"><div><p className="eyebrow text-purple-300">MEVCUT KAYITLARI VECTORLEŞTİR</p><p className="text-xs text-bunker-muted mt-2">Kapanmış işlemler ve sinyaller aktif embedding modeliyle pgvector memory tablosuna aktarılır.</p></div><div className="flex flex-wrap gap-2"><button onClick={backfillEmbeddings} disabled={backfilling} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${backfillDone ? "border-neon-green/60 text-neon-green" : "border-purple-400/50 text-purple-300"}`}>{backfilling ? "KUYRUĞA ALINIYOR..." : backfillDone ? "✓ KUYRUĞA ALINDI" : "EMBEDDING BACKFILL BAŞLAT"}</button><button onClick={repairHistoricalMemory} disabled={repairingMemory} className="shrink-0 px-4 py-2 rounded-lg border border-yellow-400/50 text-yellow-300 font-mono text-xs">{repairingMemory ? "ONARILIYOR..." : "TARİHSEL SNAPSHOT ONAR"}</button></div></div>
            <div className="card border-yellow-400/30 bg-yellow-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"><div><p className="eyebrow text-yellow-300">LLM PAPER İŞLEM YETKİSİ</p><p className="text-xs text-bunker-muted mt-2">Açıkken LLM yalnızca sanal portföyde kontrollü LONG pozisyonu açabilir. Gerçek emir API'si kullanılmaz.</p></div><div className="flex gap-2"><button onClick={async()=>{const enabled=!llm.paper_trade_enabled;await llmRequest(`${API_BASE}/api/llm/paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Paper işlem yetkisi açıldı":"Paper işlem yetkisi kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.paper_trade_enabled?"border-neon-green/60 text-neon-green":"border-bunker-700 text-bunker-muted"}`}>{llm.paper_trade_enabled?"AÇIK · KAPAT":"KAPALI · AÇ"}</button><button disabled={!llm.paper_trade_enabled} onClick={async()=>{const enabled=!llm.auto_paper_enabled;await llmRequest(`${API_BASE}/api/llm/auto-paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Kapanış sonrası otomatik yenileme açıldı":"Otomatik yenileme kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.auto_paper_enabled?"border-yellow-300/60 text-yellow-300":"border-bunker-700 text-bunker-muted"}`}>{llm.auto_paper_enabled?"KAPANIŞ SONRASI · KAPAT":"KAPANIŞ SONRASI · AÇ"}</button></div></div>
            <LlmManagement llm={llm} reload={reloadLlm} />
          </div>

          <div className={`card border-neon-red/30 bg-neon-red/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-red">PAPER TRADING KAYITLARI</p>
                <p className="font-mono text-sm text-white mt-2">Tüm eski paper-trading ve strateji geçmişini temizle</p>
                <p className="text-xs text-bunker-muted mt-1">İşlemler, sinyaller, karar logları, backtestler ve snapshotlar silinir. Ayarlar ve piyasa cache&apos;i korunur; yeni bakiye 10.000 TL olur.</p>
              </div>
              <button
                onClick={resetTradingData}
                disabled={resetting}
                className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${resetDone
                  ? "border-neon-green/60 bg-neon-green/15 text-neon-green"
                  : "border-neon-red/50 bg-neon-red/10 text-neon-red hover:bg-neon-red/20"
                  }`}
              >
                {resetting ? "TEMİZLENİYOR..." : resetDone ? "✓ TEMİZLENDİ" : "ESKİ KAYITLARI TEMİZLE"}
              </button>
            </div>
          </div>

          <div className={`card border-neon-green/30 bg-neon-green/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-green">VERİTABANI YEDEĞİ</p>
                <p className="font-mono text-sm text-white mt-2">Canlı paper-trading veritabanının tutarlı kopyasını indir</p>
                <p className="text-xs text-bunker-muted mt-1">PostgreSQL custom-format .dump yedeği alınır. İşlemler, sinyaller, açık pozisyonlar ve backtest kayıtları dahil edilir.</p>
              </div>
              <button onClick={downloadBackup} disabled={backingUp} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${backupDone ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-neon-green/50 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"}`}>
                {backingUp ? "YEDEKLENİYOR..." : backupDone ? "✓ YEDEK İNDİRİLDİ" : "VERİTABANI YEDEĞİ AL"}
              </button>
            </div>
          </div>

          <div className={`card border-sky-400/30 bg-sky-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-sky-300">PORTFÖY MUTABAKATI</p>
                <p className="font-mono text-sm text-white mt-2">Cüzdanı tüm işlem ve pozisyon kayıtlarıyla eşleştir</p>
                <p className="text-xs text-bunker-muted mt-1">Kapanan işlemler, açık pozisyon maliyetleri ve komisyonlar kontrol edilir; kayıtlar silinmez.</p>
              </div>
              <button onClick={reconcilePortfolio} disabled={reconciling} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${reconcileDone ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-sky-400/50 bg-sky-400/10 text-sky-300 hover:bg-sky-400/20"}`}>
                {reconciling ? "MUTABAKAT YAPILIYOR..." : reconcileDone ? "✓ MUTABAKAT TAMAM" : "PORTFÖYÜ MUTABIKLAŞTIR"}
              </button>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "strategies" ? "hidden" : ""}`}>
            <div className="flex justify-between items-center mb-4">
              <p className="eyebrow">İŞLEM VE RİSK YÖNETİMİ</p>
            </div>
              <p className="text-xs text-bunker-muted mb-4">
              Spot scalping: ayarlanabilir kâr hedefi, 4 saat maksimum bekleme ve aynı sembolde tek pozisyon.
            </p>
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">İşlem Başına</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Her girişte kullanılan sanal miktar (TRY)</p>
                </div>
                <input
                  type="number"
                  step={5}
                  min={5}
                  value={num(draft.default_order_usdt)}
                  onChange={(e) => setDraft((d) => ({ ...d, default_order_usdt: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Maksimum Açık Pozisyon</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Yeni pozisyon girişleri için global üst sınır</p>
                </div>
                <input
                  type="number"
                  step={1}
                  min={1}
                  max={36}
                  value={num(draft.max_open_positions)}
                  onChange={(e) => setDraft((d) => ({ ...d, max_open_positions: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Hard Stop Loss</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Spot modelde kullanılmaz</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.hard_stop_loss_pct) * 100}
                  onChange={(e) => setDraft((d) => ({ ...d, hard_stop_loss_pct: (e.target.value === "" ? NaN : Number(e.target.value)) / 100 }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <div className="mb-4 flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                    <div className="min-w-0"><p className="font-mono text-sm text-white">Kapanış Sonrası Cooldown</p><p className="text-xs text-bunker-muted mt-0.5">Yeni girişten önce beklenecek mum sayısı</p></div>
                    <input type="number" step={1} min={0} max={100} value={num(draft.cooldown_bars)} onChange={(e) => setDraft((d) => ({ ...d, cooldown_bars: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right outline-none" />
                  </div>
                  <p className="font-mono text-sm text-white">Take Profit</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Pozisyon bu kâr oranına ulaştığında satılır (komisyon hariç)</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.take_profit_pct) * 100}
                  onChange={(e) => setDraft((d) => ({ ...d, take_profit_pct: (e.target.value === "" ? NaN : Number(e.target.value)) / 100 }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Key Value (a)</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Hassasiyet - ATR çarpanı</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.ut_key_value)}
                  onChange={(e) => setDraft((d) => ({ ...d, ut_key_value: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">ATR Periyodu (c)</p>
                  <p className="text-xs text-bunker-muted mt-0.5">ATR hesaplama uzunluğu</p>
                </div>
                <input
                  type="number"
                  step={1}
                  min={2}
                  value={num(draft.ut_atr_period)}
                  onChange={(e) => setDraft((d) => ({ ...d, ut_atr_period: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Heikin Ashi Mumları</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Sinyalleri HA mumlarından al</p>
                </div>
                <button
                  onClick={() => setDraft((d) => ({ ...d, ut_heikin_ashi: !d.ut_heikin_ashi }))}
                  className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${draft.ut_heikin_ashi
                    ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                    : "border-bunker-700 bg-bunker-900 text-bunker-muted"
                    }`}
                >
                  {draft.ut_heikin_ashi ? "AÇIK" : "KAPALI"}
                </button>
              </div>
              <div className="hidden">
                <p className="font-mono text-sm text-white mb-2">AKTİF SEMBOLLER</p>
                <div className="flex flex-wrap gap-2">
                  {cfg.symbols.map((s) => {
                    const active = (draft.ut_symbols || []).includes(s);
                    return (
                      <button
                        key={s}
                        onClick={() => setDraft((d) => ({
                          ...d,
                          ut_symbols: active
                            ? (d.ut_symbols || []).filter((x) => x !== s)
                            : [...(d.ut_symbols || []), s]
                        }))}
                        className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${active
                          ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                          : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"
                          }`}
                      >
                        {s}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "app" ? "hidden" : ""}`}>
            <p className="eyebrow mb-3">MOD</p>
            <div className="flex gap-3">
              <span className="px-3 py-1.5 rounded-full border border-neon-green/40 text-neon-green font-mono text-xs">
                PAPER TRADING
              </span>
              <span className="px-3 py-1.5 rounded-full border border-neon-green/40 text-neon-green font-mono text-xs">PAPER · PUBLIC API</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
