"use client";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import LlmManagement from "./LlmManagement";
import SystemHealthTab from "./SystemHealthTab";
import SymbolLink from "../components/SymbolLink";

type Config = {
  symbols: string[];
  removed_invalid_symbols?: string[];
  min_notional: number;
  default_order_usdt: number;
  order_pct: number;
  symbol_activity_m1_flat_filter_enabled: boolean;
  symbol_activity_m1_flat_max_range_pct: number;
  symbol_activity_m1_flat_5m_max_count: number;
  symbol_activity_m1_flat_30m_max_count: number;
  min_24h_quote_volume_try: number;
  high_liquidity_bypass_volume_try: number;
  min_volume_ratio: number;
  min_orderbook_depth_multiplier: number;
  max_open_positions: number;
  hard_stop_loss_pct: number;
  cooldown_bars: number;
  take_profit_pct: number;
  trailing_stop_pct: number;
  initial_balance_try: number;
  mode: string;
  market_data: string;
  gainer_radar_min_score: number;
  top_gainers_auto_activate: boolean;
  top_gainers_limit: number;
  top_gainers_refresh_sec: number;
};

import ChatSettingsPanel from "./ChatSettingsPanel";
import RequireAdmin from "../components/RequireAdmin";
import { useAuth } from "../lib/auth";

export default function SettingsPage() {
  return <RequireAdmin><SettingsPageInner /></RequireAdmin>;
}
function SettingsPageInner() {
  const [activeTab, setActiveTab] = useState<"symbols" | "app" | "strategies" | "llm" | "chat" | "auto-paper" | "system-health">("symbols");
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
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [monitoringMinScore, setMonitoringMinScore] = useState<number | null>(null);
  const [monitoringMinScoreInput, setMonitoringMinScoreInput] = useState<string>("50");
  const [savingMonitoringMinScore, setSavingMonitoringMinScore] = useState(false);
  const [backfillDone, setBackfillDone] = useState(false);
  const [repairingMemory, setRepairingMemory] = useState(false);
  const [activity, setActivity] = useState<Record<string, any>>({});
  const [activityFilter, setActivityFilter] = useState<"all" | "ACTIVE" | "PASSIVE" | "WARMING">("all");
  const [refreshingActivity, setRefreshingActivity] = useState(false);
  const [topGainers, setTopGainers] = useState<any>({});
  const [refreshingTopGainers, setRefreshingTopGainers] = useState(false);
  const [mtfBackfillOpen, setMtfBackfillOpen] = useState(false);
  const [mtfBackfill, setMtfBackfill] = useState<any>({ status: "idle", progress: 0, logs: [] });
  const [startingMtfBackfill, setStartingMtfBackfill] = useState(false);
  const [parityBackfillOpen, setParityBackfillOpen] = useState(false);
  const [parityBackfill, setParityBackfill] = useState<any>({ status: "idle", progress: 0, logs: [] });
  const [startingParityBackfill, setStartingParityBackfill] = useState(false);
  const [mlBackfillOpen, setMlBackfillOpen] = useState(false);
  const [mlBackfill, setMlBackfill] = useState<any>({ status: "idle", progress: 0, logs: [] });
  const [startingMlBackfill, setStartingMlBackfill] = useState(false);

  useEffect(() => {
    const tab = new URLSearchParams(window.location.search).get("tab");
    if (tab === "strategies") setActiveTab("strategies");
  }, []);

  useEffect(() => {
    apiRequest(`${API_BASE}/api/config`)
      .then((r) => r.json())
      .then((d) => { setCfg(d); setDraft(d); })
      .catch(() => setError(`Backend'e bağlanılamadı (${API_BASE})`));
    apiRequest(`${API_BASE}/api/market-symbols`)
      .then((r) => r.json())
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch(() => setError("Binance TR sembolleri alınamadı"));
    apiRequest(`${API_BASE}/api/llm/config`).then((r) => r.json()).then(setLlm).catch(() => undefined);
    apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const ms = d.min_score ?? 50;
        setMonitoringMinScore(ms);
        setMonitoringMinScoreInput(String(Math.round(ms)));
      })
      .catch(() => undefined);
    loadMlStatus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () => apiRequest(`${API_BASE}/api/market/top-gainers`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setTopGainers(d); })
      .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 60000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!mtfBackfillOpen) return;
    let cancelled = false;
    const load = () => apiRequest(`${API_BASE}/api/historical-mtf-backfill/status`, { cache: "no-store" })
      .then((r) => r.json()).then((d) => { if (!cancelled) setMtfBackfill(d); }).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [mtfBackfillOpen]);

  useEffect(() => {
    if (!parityBackfillOpen) return;
    let cancelled = false;
    const load = () => apiRequest(`${API_BASE}/api/replay-parity-backfill/status`, { cache: "no-store" })
      .then((r) => r.json()).then((d) => { if (!cancelled) setParityBackfill(d); }).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [parityBackfillOpen]);

  useEffect(() => {
    if (!mlBackfillOpen) return;
    let cancelled = false;
    const load = () => apiRequest(`${API_BASE}/api/velocity-ml-backfill/status`, { cache: "no-store" })
      .then((r) => r.json()).then((d) => { if (!cancelled) setMlBackfill(d); }).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [mlBackfillOpen]);

  useEffect(() => {
    const load = () => apiRequest(`${API_BASE}/api/symbol-activity`, { cache: "no-store" }).then((r) => r.json()).then((d) => setActivity(d.statuses || {})).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 60000);
    return () => window.clearInterval(timer);
  }, []);

  const refreshActivity = async () => {
    setRefreshingActivity(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/symbol-activity/refresh`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Aktivasyon kontrolü başarısız");
      setActivity(data.statuses || {});
    } catch (err) { setError(err instanceof Error ? err.message : "Aktivasyon kontrolü başarısız"); }
    finally { setRefreshingActivity(false); }
  };

  const saveMonitoringMinScore = async () => {
    const val = Number(monitoringMinScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) { setError("Monitoring min skor 0-100 arası olmalı"); return; }
    setSavingMonitoringMinScore(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_score: val }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Kaydetme başarısız");
      setMonitoringMinScore(data.min_score ?? val);
      setMonitoringMinScoreInput(String(Math.round(data.min_score ?? val)));
    } catch (err) { setError(err instanceof Error ? err.message : "Monitoring eşiği kaydedilemedi"); }
    finally { setSavingMonitoringMinScore(false); }
  };

  const refreshTopGainers = async () => {
    setRefreshingTopGainers(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/market/top-gainers?refresh=true`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Top-gainer listesi alınamadı");
      setTopGainers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Top-gainer listesi alınamadı");
    } finally {
      setRefreshingTopGainers(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      // A cleared numeric input serializes NaN → null and could persist a
      // broken trading parameter. Reject the save with the offending keys.
      const invalidKeys = Object.entries(draft)
        .filter(([, value]) => typeof value === "number" && !Number.isFinite(value))
        .map(([key]) => key);
      if (invalidKeys.length) throw new Error(`Bu alanlar sayısal olmalıdır: ${invalidKeys.join(", ")}`);
      const res = await apiRequest(`${API_BASE}/api/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft)
      });
      const rawBody = await res.text();
      let body: any = null;
      try {
        body = rawBody ? JSON.parse(rawBody) : null;
      } catch {
        // Reverse proxies may return an HTML/plain-text error page; never surface a JSON parser error to the user.
      }
      if (!res.ok) {
        const detail = body?.detail || body?.error || body?.message;
        const textDetail = rawBody && !/<[^>]+>/.test(rawBody) ? rawBody.trim().slice(0, 240) : "";
        throw new Error(detail || textDetail || `Ayarlar kaydedilemedi (HTTP ${res.status}${res.statusText ? `: ${res.statusText}` : ""})`);
      }
      if (!body || typeof body !== "object") throw new Error("Ayarlar kaydedildi ancak sunucudan geçerli yanıt alınamadı.");
      const updated = body;
      setCfg(updated);
      setDraft(updated);
      setSaved(true);
      const removed = Array.isArray(updated.removed_invalid_symbols) ? updated.removed_invalid_symbols : [];
      window.alert(removed.length
        ? `Ayarlar kaydedildi. Binance TR'de işlemde olmayan semboller çıkarıldı: ${removed.join(", ")}`
        : "Ayarlar başarıyla kaydedildi.");
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kaydedilemedi - backend bağlantısını kontrol et");
    } finally {
      setSaving(false);
    }
  };

  const num = (v: any) => (typeof v === "number" ? v : Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
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
      const res = await apiRequest(`${API_BASE}/api/reset`, { method: "POST" });
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
      const previewResponse = await apiRequest(`${API_BASE}/api/portfolio/reconcile`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: false }) });
      const preview = await previewResponse.json();
      if (!previewResponse.ok) throw new Error(preview.detail || "Mutabakat önizlemesi alınamadı");
      const targets = preview.would_remove || [];
      const detail = targets.length ? `\nSilinecek açık pozisyonlar ve ilişkili açılış kayıtları:\n- ${targets.map((item:any) => `${item.symbol} · ₺${Number(item.cost).toFixed(2)}`).join("\n- ")}` : "\nSilinecek pozisyon yok; yalnızca bakiye yeniden hesaplanacak.";
      if (!window.confirm(`Portföy mutabakatı önizlemesi hazır.${detail}\n\nDevam edilsin mi?`)) return;
      const response = await apiRequest(`${API_BASE}/api/portfolio/reconcile`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }) });
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
      const response = await apiRequest(`${API_BASE}/api/memory/backfill`, { method: "POST" });
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
      const response = await apiRequest(`${API_BASE}/api/memory/repair-historical`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Tarihsel memory onarımı başlatılamadı");
      setLlmMessage(`${body.queued || 0} tarihsel snapshot yeniden embedding kuyruğuna alındı.`);
    } catch (err) { setLlmMessage(err instanceof Error ? err.message : "Tarihsel memory onarımı başarısız"); }
    finally { setRepairingMemory(false); }
  };

  const startHistoricalMtfBackfill = async () => {
    if (!window.confirm("Kapanmış işlemler ve açık pozisyonların giriş zamanları Binance TR public history ile yeniden hesaplanacak. PnL, bakiye ve pozisyonlar değişmeyecek. Devam edilsin mi?")) return;
    setStartingMtfBackfill(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/historical-mtf-backfill/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "MTF backfill başlatılamadı");
      setMtfBackfillOpen(true);
      setMtfBackfill(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "MTF backfill başlatılamadı");
    } finally { setStartingMtfBackfill(false); }
  };

  const startReplayParityBackfill = async () => {
    if (!window.confirm("Mevcut karar kayıtları ayrı denetim satırlarıyla backfill edilecek. İşlemler, PnL, bakiye ve ayarlar değişmez. Eksik geçmiş likidite/M1 bağlamı unknown kalır. Devam edilsin mi?")) return;
    setStartingParityBackfill(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/replay-parity-backfill/start`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Replay-parity backfill başlatılamadı");
      setParityBackfillOpen(true);
      setParityBackfill(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay-parity backfill başlatılamadı");
    } finally { setStartingParityBackfill(false); }
  };

  const startVelocityMlBackfill = async () => {
    if (!window.confirm("ML kolonları boş velocity adayları geçmiş 1m mumlardan gölge ML tahminiyle doldurulacak. İşlem, PnL ve pozisyonlar değişmeyecek; yalnız rapor/kalibrasyon verisi. Devam edilsin mi?")) return;
    setStartingMlBackfill(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/velocity-ml-backfill/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "ML geri doldurma başlatılamadı");
      setMlBackfillOpen(true);
      setMlBackfill(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ML geri doldurma başlatılamadı");
    } finally { setStartingMlBackfill(false); }
  };

  const downloadParityTradeCsv = async () => {
    try {
      const response = await apiRequest(`${API_BASE}/api/replay-parity-backfill/trades.csv`, { cache: "no-store" });
      if (!response.ok) throw new Error("İşlem CSV'si indirilemedi");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const disposition = response.headers.get("content-disposition") || "";
      anchor.download = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "paper-islem-detaylari.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) { setError(err instanceof Error ? err.message : "İşlem CSV'si indirilemedi"); }
  };

  const reloadLlm = async () => setLlm(await (await apiRequest(`${API_BASE}/api/llm/config`, { cache: "no-store" })).json());
  const llmRequest = async (url: string, options: RequestInit, success: string) => {
    setLlmMessage(null);
    try {
      const response = await apiRequest(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) throw new Error(body.detail || body.error || "İşlem başarısız");
      await reloadLlm();
      setLlmMessage(success);
      window.alert(`${success}.`);
    } catch (err) {
      setLlmMessage(err instanceof Error ? err.message : "LLM işlemi başarısız");
    }
  };

  const saveLlmProvider = async () => {
    // API key'i gönder ve hemen state'ten temizle (bellek sızıntısını önle)
    const apiKeyToSend = llmForm.api_key;
    llmForm.api_key = ""; // State'ten temizle
    await llmRequest(
      `${API_BASE}/api/llm/providers`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: llmForm.name.trim(),
          base_url: llmForm.base_url.trim(),
          api_key: apiKeyToSend,
        }),
      },
      "Provider kaydedildi",
    );
    // Başarısız olsa da key'i bellekte tutmamak için state'i sıfırla
    setLlmForm(prev => ({ ...prev, api_key: "" }));
  };

  const [mlStatus, setMlStatus] = useState<any>(null);
  const [mlTraining, setMlTraining] = useState(false);
  const [mlDone, setMlDone] = useState(false);
  const [mlError, setMlError] = useState<string | null>(null);

  const loadMlStatus = () => apiRequest(`${API_BASE}/api/ml/status`, { cache: "no-store" })
    .then((r) => r.json()).then(setMlStatus).catch(() => undefined);

  const trainMlNow = async () => {
    setMlTraining(true);
    setMlDone(false);
    setMlError(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/ml/train`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Eğitim başarısız (HTTP ${res.status})`);
      }
      setMlDone(true);
      loadMlStatus();
    } catch (e) {
      setMlError(e instanceof Error ? e.message : "Bilinmeyen hata");
    } finally {
      setMlTraining(false);
    }
  };

  const downloadBackup = async () => {
    setBackingUp(true);
    setError(null);
    setBackupDone(false);
    try {
      const res = await apiRequest(`${API_BASE}/api/postgres/backup`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Yedekleme başarısız (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const header = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
      const isPostgresCustomDump = Array.from(header).join(",") === "80,71,68,77,80";
      if (!isPostgresCustomDump) {
        throw new Error("Sunucunun ürettiği dosya geçerli PostgreSQL custom-format yedeği değil");
      }
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
    <div className="settings-page max-w-5xl mx-auto space-y-6">
      <header className="settings-header flex items-center justify-between">
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
            ["chat", "Chat Ayarları", "✦"],
            ["auto-paper", "Otonom Paper", "🤖"],
            ["system-health", "Sistem Sağlığı", "🩺"],
          ] as const).map(([key, label, icon]) => (
            <button key={key} onClick={() => setActiveTab(key)} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${activeTab === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>
              {icon} {label}
            </button>
          ))}
        </nav>
      )}

      {cfg && (
        <>
          <div className={`${activeTab !== "system-health" ? "hidden" : ""}`}>
            <SystemHealthTab />
          </div>
          <div className={`${activeTab !== "chat" ? "hidden" : ""}`}>
            <ChatSettingsPanel />
          </div>
          <div className={`${activeTab !== "auto-paper" ? "hidden" : ""}`}>
            <AutoPaperSettingsPanel />
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
                return <div key={symbol} className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 font-mono text-xs transition-colors ${active ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted"}`}><SymbolLink symbol={symbol} className={active ? "text-neon-green hover:text-white" : "text-bunker-muted hover:text-white"} /><button type="button" onClick={() => toggleSymbol(symbol)} className="rounded px-1 hover:text-white" aria-label={`${active ? "Sembolü pasifleştir" : "Sembolü aktifleştir"}: ${symbol}`}>{active ? "✓" : "+"}</button></div>;
              })}
              {!filteredSymbols.length && <span className="text-xs text-bunker-muted font-mono">Sembol bulunamadı</span>}
            </div>
            <div className="mt-4 pt-3 border-t border-bunker-800/60">
              <p className="eyebrow mb-2">AKTİF TARAMA SEMBOLLERİ · {selectedSymbols.length}</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {selectedSymbols.map((symbol) => <div key={symbol} className="flex min-h-10 items-center justify-between gap-2 rounded-lg border border-neon-green/60 bg-neon-green/15 px-3 py-2 text-left font-mono text-xs text-neon-green"><SymbolLink symbol={symbol} className="text-neon-green hover:text-white" /><button type="button" onClick={() => toggleSymbol(symbol)} className="px-1 text-neon-green/70 hover:text-white" aria-label="Sembolü pasifleştir">×</button></div>)}
                {!selectedSymbols.length && <p className="col-span-full rounded-lg border border-yellow-400/40 bg-yellow-400/5 px-3 py-3 font-mono text-xs text-yellow-300">Aktif tarama sembolü seçilmedi.</p>}
              </div>
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
                <div>
                  <p className="eyebrow text-neon-green">DİNAMİK TOP-GAINER EVRENİ</p>
                  <p className="text-xs text-bunker-muted mt-1">Açık olduğunda Binance TR 24 saatlik top-gainer listesinden seçilen semboller izlenir. Liste periyodik yenilenir; aktif strateji koşulları sağlanırsa yalnızca paper işlem açılır.</p>
                </div>
                <button type="button" onClick={refreshTopGainers} disabled={refreshingTopGainers} className="rounded border border-neon-green/50 bg-neon-green/10 px-2 py-1 font-mono text-[11px] text-neon-green transition-colors hover:bg-neon-green/20 disabled:cursor-wait disabled:opacity-60">{refreshingTopGainers ? "GÜNCELLENİYOR..." : "LİSTEYİ YENİLE"}</button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className="flex items-center justify-between gap-3 rounded-lg border border-neon-green/40 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-neon-green">Dinamik evreni etkinleştir</span><input type="checkbox" checked={Boolean(draft.top_gainers_auto_activate)} onChange={(e) => setDraft((d) => ({ ...d, top_gainers_auto_activate: e.target.checked }))} /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Top-gainer limiti</span><input type="number" min={1} max={50} step={1} value={num(draft.top_gainers_limit)} onChange={(e) => setDraft((d) => ({ ...d, top_gainers_limit: e.target.value === "" ? NaN : Number(e.target.value) }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Yenileme (dakika)</span><input type="number" min={1} max={60} step={1} value={num(draft.top_gainers_refresh_sec) / 60} onChange={(e) => setDraft((d) => ({ ...d, top_gainers_refresh_sec: e.target.value === "" ? NaN : Number(e.target.value) * 60 }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {Array.isArray(topGainers.selected) && topGainers.selected.map((symbol: string) => <span key={symbol} className="rounded border border-neon-green/40 bg-neon-green/10 px-2 py-1 font-mono text-[11px] text-neon-green">{symbol}</span>)}
                {!Array.isArray(topGainers.selected) || !topGainers.selected.length ? <span className="rounded border border-bunker-800 bg-bunker-900 px-2 py-1 font-mono text-[11px] text-bunker-muted">Top-gainer listesi henüz yüklenmedi</span> : null}
              </div>
              {Array.isArray(topGainers.preserved_open_positions) && topGainers.preserved_open_positions.length > 0 && (
                <p className="mt-2 font-mono text-[11px] text-bunker-muted">Açık pozisyonlar korunur: {topGainers.preserved_open_positions.join(", ")}</p>
              )}
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <div><p className="eyebrow text-neon-green">GERÇEK AKTİVİTE DURUMU</p><p className="text-xs text-bunker-muted mt-1">Arka planda saatte bir güncellenir; bu ekrandan manuel kontrol de yapılabilir. Aktiflik; hareket, ATR, hacim ve tamamlanmış M1 düz mum yoğunluğu ile hesaplanır.</p></div>
                <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono"><span className="rounded border border-neon-green/40 px-2 py-1 text-neon-green">AKTİF {activityCounts.ACTIVE}</span><span className="rounded border border-yellow-400/40 px-2 py-1 text-yellow-300">PASİF {activityCounts.PASSIVE}</span><span className="rounded border border-sky-400/40 px-2 py-1 text-sky-300">ISINIYOR {activityCounts.WARMING}</span><button type="button" onClick={refreshActivity} disabled={refreshingActivity} className="rounded border border-neon-green/50 bg-neon-green/10 px-2 py-1 text-neon-green transition-colors hover:bg-neon-green/20 disabled:cursor-wait disabled:opacity-60">{refreshingActivity ? "KONTROL EDİLİYOR..." : "AKTİVASYON KONTROLÜ"}</button></div>
              </div>
              <div className="flex flex-wrap gap-2 mb-3">{([ ["all", "TÜMÜ"], ["ACTIVE", "AKTİF"], ["PASSIVE", "PASİF"], ["WARMING", "ISINIYOR"] ] as const).map(([key, label]) => <button key={key} onClick={() => setActivityFilter(key)} className={`rounded-lg border px-3 py-1.5 font-mono text-xs ${activityFilter === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green" : "border-bunker-700 text-bunker-muted"}`}>{label}</button>)}</div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-[32rem] overflow-y-auto pr-1">
                {visibleActivity.map((item: any) => <div key={item.symbol} className={`rounded-lg border px-3 py-2 ${item.status === "ACTIVE" ? "border-neon-green/30 bg-neon-green/5" : item.status === "WARMING" ? "border-sky-400/30 bg-sky-400/5" : "border-bunker-800 bg-bunker-900/60"}`}><div className="flex items-center justify-between gap-2"><SymbolLink symbol={item.symbol} className="font-mono text-sm text-white hover:text-neon-green" /><span className={`font-mono text-[10px] ${item.status === "ACTIVE" ? "text-neon-green" : item.status === "WARMING" ? "text-sky-300" : "text-yellow-300"}`}>{item.status}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-[10px] font-mono text-bunker-muted"><span>15m {item.range_15m_pct == null ? "—" : `${item.range_15m_pct}%`}</span><span>ATR {item.atr_pct == null ? "—" : `${item.atr_pct}%`}</span><span>VOL {item.volume_ratio == null ? "—" : `${item.volume_ratio}x`}</span><span>M1 düz {item.m1_flat_sample_30m ? `${item.m1_flat_5m_count}/5 · ${item.m1_flat_30m_count}/30` : "—"}</span></div><p className="mt-2 truncate text-[10px] text-bunker-muted" title={item.reason || ""}>{item.reason || "—"}</p></div>)}
                {!visibleActivity.length && <p className="col-span-full py-6 text-center font-mono text-xs text-bunker-muted">Aktivite verisi henüz hazır değil.</p>}
              </div>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="border-b border-bunker-800 pb-5 mb-5">
              <p className="eyebrow text-neon-green">POZİSYON BOYUTU</p>
              <p className="text-xs text-bunker-muted mt-1">Yeni paper işlemde kullanılacak bakiye oranı.</p>
              <div className="grid sm:grid-cols-3 gap-3 mt-3">
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Global işlem yüzdesi</span><input type="number" min={0.1} max={100} step={0.5} value={num(draft.order_pct) * 100} onChange={e => setDraft(d => ({ ...d, order_pct: Number(e.target.value) / 100 }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-neon-yellow/40 bg-bunker-900 px-3 py-2 flex items-center justify-between gap-3"><span className="font-mono text-xs text-neon-yellow">M1 düz mum pasif filtresi</span><input type="checkbox" checked={Boolean(draft.symbol_activity_m1_flat_filter_enabled)} onChange={e => setDraft(d => ({ ...d, symbol_activity_m1_flat_filter_enabled: e.target.checked }))} /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">Düz mum max. H-L aralığı (%)</span><input type="number" min={0} max={5} step={0.001} value={num(draft.symbol_activity_m1_flat_max_range_pct)} onChange={e => setDraft(d => ({ ...d, symbol_activity_m1_flat_max_range_pct: Number(e.target.value) }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">5 dk düz M1 pasifleştirme eşiği</span><input type="number" min={1} max={5} step={1} value={num(draft.symbol_activity_m1_flat_5m_max_count)} onChange={e => setDraft(d => ({ ...d, symbol_activity_m1_flat_5m_max_count: Number(e.target.value) }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
                <label className="rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">30 dk düz M1 pasifleştirme eşiği</span><input type="number" min={1} max={30} step={1} value={num(draft.symbol_activity_m1_flat_30m_max_count)} onChange={e => setDraft(d => ({ ...d, symbol_activity_m1_flat_30m_max_count: Number(e.target.value) }))} className="mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white" /></label>
              </div>
            </div>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="eyebrow">GAINER RADAR MİNİMUM SKOR</p>
                <p className="text-xs text-bunker-muted mt-1">Radar şu anda yalnızca gözlem ve sıralama yapar; otomatik paper işlem açmaz. Önerilen başlangıç: 50.</p>
              </div>
              <input type="number" min={0} max={100} step={1} value={num(draft.gainer_radar_min_score)} onChange={(e) => setDraft((d) => ({ ...d, gainer_radar_min_score: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none" />
            </div>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="eyebrow">MONİTORİNG MİNİMUM SKOR</p>
                <p className="text-xs text-bunker-muted mt-1">Bildirim gönderme eşiği (0-100 panel skoru, global). Bu değerin altındaki adaylar bildirilmez, radar listesinde gösterilmez ve raporlara katılmaz. Riskli (RISK-OFF) rejimde eşik 1.5× uygulanır ve etkin değer monitoring sayfasında gösterilir. Mevcut: {monitoringMinScore ?? "—"}.</p>
              </div>
              <div className="flex items-center gap-2">
                <input type="number" min={0} max={100} step={1} value={monitoringMinScoreInput} onChange={(e) => setMonitoringMinScoreInput(e.target.value === "" ? "" : String(Number(e.target.value)))} className="w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none" />
                <button type="button" onClick={saveMonitoringMinScore} disabled={savingMonitoringMinScore || !isAdmin} className="ui-button ui-button-primary px-3 py-1.5 text-xs disabled:opacity-50">{savingMonitoringMinScore ? "KAYDEDİLİYOR…" : "KAYDET"}</button>
              </div>
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <p className="eyebrow">LİKİDİTE FİLTRESİ</p>
              <p className="text-xs text-bunker-muted mt-1">İşlem açılmadan önce düşük hacim ve sığ emir defteri engellenir.</p>
              <div className="grid sm:grid-cols-2 gap-3 mt-3">
                {([
                  ["min_24h_quote_volume_try", "Minimum 24s hacim (TL)", 1000],
                  ["high_liquidity_bypass_volume_try", "Yüksek likidite eşiği (TL)", 1000],
                  ["min_volume_ratio", "Minimum hacim oranı", 0.1],
                  ["min_orderbook_depth_multiplier", "Emir defteri çarpanı", 0.5],
                ] as const).map(([key, label, step]) => (
                  <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2">
                    <span className="font-mono text-xs text-bunker-muted">{label}</span>
                    <input type="number" min={0} step={step} value={num((draft as any)[key])} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" />
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Önerilen: 1.000.000 TL · 0,3x · 5x</p>
            </div>
          </div>
          <div className={`space-y-4 ${activeTab !== "llm" ? "hidden" : ""}`}>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">LLM PROVIDER EKLE</p><p className="text-xs text-bunker-muted mb-3">Yalnızca teknik yorum üretir; emir veya pozisyon kararı vermez.</p><div className="grid md:grid-cols-2 gap-3"><input placeholder="Provider adı" value={llmForm.name} onChange={e => setLlmForm({...llmForm,name:e.target.value})} className="input" /><input placeholder="Base URL (https://.../v1)" value={llmForm.base_url} onChange={e => setLlmForm({...llmForm,base_url:e.target.value})} className="input" /><input type="password" placeholder="API key" value={llmForm.api_key} onChange={e => setLlmForm({...llmForm,api_key:e.target.value})} className="input" /><button onClick={saveLlmProvider} disabled={!llm.encryption_configured || !llmForm.name.trim() || !llmForm.base_url.trim() || !llmForm.api_key.trim()} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs disabled:opacity-40 disabled:cursor-not-allowed">PROVIDER KAYDET</button></div><p className={`text-xs mt-3 ${llm.encryption_configured ? "text-bunker-muted" : "text-yellow-300"}`}>Şifreleme anahtarı: {llm.encryption_configured ? "hazır" : "sunucuda LLM_ENCRYPTION_KEY eksik; Provider kaydı için backend ortamına eklenmeli"}</p></div>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">MODEL / UZMANLIK</p><div className="grid md:grid-cols-2 gap-3"><select value={llmForm.provider_id} onChange={e => setLlmForm({...llmForm,provider_id:e.target.value})} className="input"><option value="">Provider seç</option>{llm.providers.map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}</select><input placeholder="Model adı" value={llmForm.model} onChange={e => setLlmForm({...llmForm,model:e.target.value})} className="input" /><select value={llmForm.model_type} onChange={e => setLlmForm({...llmForm,model_type:e.target.value})} className="input"><option value="chat">Chat modeli</option><option value="embedding">Embedding modeli</option></select>{llmForm.model_type === "embedding" && <input type="number" min="1" placeholder="Embedding dimension" value={llmForm.dimensions} onChange={e => setLlmForm({...llmForm,dimensions:e.target.value})} className="input" />}<button onClick={() => llmRequest(`${API_BASE}/api/llm/models`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:Number(llmForm.provider_id),name:llmForm.model,model_type:llmForm.model_type,dimensions:llmForm.dimensions ? Number(llmForm.dimensions) : undefined})}, "Model kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">MODEL EKLE</button>{llmForm.model_type === "embedding" && <button onClick={async () => { const r=await apiRequest(`${API_BASE}/api/llm/embedding/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"embedding bağlantı testi"})}); const b=await r.json(); const m=b.status === "ok" ? `Embedding başarılı · ${b.dimensions} dimension` : (b.error || "Embedding testi başarısız"); setLlmMessage(m); window.alert(m); }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">EMBEDDING TEST ET</button>}<input placeholder="Uzmanlık adı" value={llmForm.skill} onChange={e => setLlmForm({...llmForm,skill:e.target.value})} className="input" /><textarea placeholder="Uzmanlık talimatları" value={llmForm.instructions} onChange={e => setLlmForm({...llmForm,instructions:e.target.value})} className="input min-h-24" /><button onClick={() => llmRequest(`${API_BASE}/api/llm/skills`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:llmForm.skill,instructions:llmForm.instructions})}, "Uzmanlık kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">UZMANLIK EKLE</button></div>{llmMessage && <p className="text-xs text-neon-green mt-3">{llmMessage}</p>}</div>
            <div className="card bg-bunker-950 flex flex-wrap gap-3"><select value={llm.active_model_id || ""} onChange={async e => { const id=Number(e.target.value); await llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:id})}, "LLM aktif edildi"); }} className="input"><option value="">Aktif model seç</option>{llm.models.map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}</select><button onClick={() => llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:llm.active_model_id})}, "LLM aktif edildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">LLM AKTİF</button><button onClick={async () => { setLlmMessage("TEST EDİLİYOR..."); try { const r=await apiRequest(`${API_BASE}/api/llm/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const body=await r.json(); const message=body.status === "ok" ? "Bağlantı başarılı" : (body.error || body.status || "Test başarısız"); setLlmMessage(message); window.alert(message); } catch { setLlmMessage("LLM test bağlantısı kurulamadı"); window.alert("LLM test bağlantısı kurulamadı"); } }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">TEST ET</button></div>
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

          <div className={`card border-amber-300/30 bg-amber-300/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="min-w-0">
                <p className="eyebrow text-amber-300">ML FIYAT TAHMIN MODELI</p>
                <p className="font-mono text-sm text-white mt-2">Yükseliş hedefi modelini journal sonuçlarıyla yeniden eğit</p>
                <p className="text-xs text-bunker-muted mt-1">
                  {mlStatus?.status === "ready" && mlStatus?.artifact
                    ? `Son eğitim: ${new Date(Number(mlStatus.artifact.created_at) * 1000).toLocaleString("tr-TR")} · ${mlStatus.artifact.sample_count.toLocaleString("tr-TR")} örnek · ${mlStatus.artifact.symbol_count} sembol · ${mlStatus.artifact.journal_sample_count} journal örneği`
                    : mlStatus?.status === "not_trained"
                      ? "Henüz eğitim yok; otomatik döngü veya buton ile başlatın."
                      : "Durum alınıyor..."}
                  {mlStatus?.interval_hours ? ` · Otomatik: her ${mlStatus.interval_hours} saatte bir` : ""}
                </p>
                {mlError && <p className="text-xs text-neon-red mt-1">{mlError}</p>}
              </div>
              <button onClick={trainMlNow} disabled={mlTraining} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${mlDone ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-amber-300/50 bg-amber-300/10 text-amber-300 hover:bg-amber-300/20"}`}>
                {mlTraining ? "EĞİTİLİYOR..." : mlDone ? "✓ EĞİTİM TAMAM" : "ŞİMDİ EĞİT"}
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

          <div className={`card border-purple-400/30 bg-purple-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-purple-300">GEÇMİŞ MTF SNAPSHOT BACKFILL</p>
                <p className="font-mono text-sm text-white mt-2">Eski işlem girişlerini M1/M5/M15/H1/H4 ile zenginleştir</p>
                <p className="text-xs text-bunker-muted mt-1">Binance TR public history kullanılır. PnL, bakiye ve işlem sonucu değişmez; geçmişte kaydedilmeyen likidite bağlamı unknown kalır.</p>
              </div>
              <button onClick={startHistoricalMtfBackfill} disabled={startingMtfBackfill || mtfBackfill.status === "running"} className="shrink-0 px-4 py-2 rounded-lg border border-purple-400/50 bg-purple-400/10 text-purple-300 hover:bg-purple-400/20 font-mono text-xs">
                {startingMtfBackfill || mtfBackfill.status === "running" ? "BACKFILL ÇALIŞIYOR..." : "MTF BACKFILL BAŞLAT"}
              </button>
            </div>
          </div>

          <div className={`card border-cyan-400/30 bg-cyan-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-cyan-300">REPLAY KARAR PARİTESİ</p>
                <p className="font-mono text-sm text-white mt-2">Eski kararları denetim amaçlı backfill et</p>
                <p className="text-xs text-bunker-muted mt-1">Karar olayları ayrı denetim satırlarına eklenir. PnL, bakiye, pozisyon ve strateji koşulları değişmez; geçmişte kaydedilmeyen likidite/M1 bağlamı unknown kalır.</p>
              </div>
              <button onClick={startReplayParityBackfill} disabled={startingParityBackfill || parityBackfill.status === "running"} className="shrink-0 px-4 py-2 rounded-lg border border-cyan-400/50 bg-cyan-400/10 text-cyan-300 hover:bg-cyan-400/20 font-mono text-xs disabled:opacity-50">
                {startingParityBackfill || parityBackfill.status === "running" ? "BACKFILL ÇALIŞIYOR..." : "BACKFILL BAŞLAT"}
              </button>
            </div>
          </div>

          <div className={`card border-emerald-400/30 bg-emerald-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-emerald-300">ML HEDEF GERİ DOLDURMA</p>
                <p className="font-mono text-sm text-white mt-2">Boş ML kolonlarını geçmiş 1m mumlardan gölge tahminle doldur</p>
                <p className="text-xs text-bunker-muted mt-1">velocity_candidates.ml_hit_probability / ml_target_pct. Mevcut ML modeliyle gölge; işlem/PnL/pozisyon değişmez. Rapor ve kalibrasyon verisi için.</p>
              </div>
              <button onClick={startVelocityMlBackfill} disabled={startingMlBackfill || mlBackfill.status === "running"} className="shrink-0 px-4 py-2 rounded-lg border border-emerald-400/50 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/20 font-mono text-xs disabled:opacity-50">
                {startingMlBackfill || mlBackfill.status === "running" ? "GERİ DOLDURULUYOR..." : "ML GERİ DOLDUR"}
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
                  <p className="text-xs text-bunker-muted mt-0.5">Yeni pozisyon girişleri için üst sınır; 0 = sınırsız</p>
                </div>
                <input
                  type="number"
                  step={1}
                  min={0}
                  max={500}
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
      {mtfBackfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setMtfBackfillOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4"><div><p className="eyebrow text-purple-300">MTF BACKFILL LOG</p><p className="font-mono text-sm text-white mt-1">{mtfBackfill.message || "Hazırlanıyor..."}</p></div><button onClick={() => setMtfBackfillOpen(false)} className="text-bunker-muted hover:text-white">✕</button></div>
            <div className="grid grid-cols-3 gap-3 mb-4 text-xs font-mono"><div><span className="text-bunker-muted">DURUM</span><p className="text-purple-300 mt-1">{String(mtfBackfill.status || "idle").toUpperCase()}</p></div><div><span className="text-bunker-muted">İLERLEME</span><p className="text-white mt-1">{mtfBackfill.completed ?? 0}/{mtfBackfill.total ?? 0} · %{mtfBackfill.progress ?? 0}</p></div><div><span className="text-bunker-muted">SONUÇ</span><p className="text-neon-green mt-1">{mtfBackfill.result ? `${mtfBackfill.result.updated} güncellendi` : "—"}</p></div></div>
            <div className="h-2 rounded bg-bunker-800 mb-4"><div className="h-2 rounded bg-purple-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(mtfBackfill.progress || 0)))}%` }} /></div>
            <div className="max-h-[48vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(mtfBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(log.timestamp * 1000).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(mtfBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
            <p className="text-[11px] text-bunker-muted mt-3">Pencereyi kapatsanız da job backend’de arka planda devam eder; tekrar açarak son durumu görebilirsiniz.</p>
          </div>
        </div>
      )}
      {parityBackfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setParityBackfillOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4"><div><p className="eyebrow text-cyan-300">REPLAY PARİTE BACKFILL</p><p className="font-mono text-sm text-white mt-1">{parityBackfill.message || "Hazırlanıyor..."}</p></div><button onClick={() => setParityBackfillOpen(false)} className="text-bunker-muted hover:text-white">✕</button></div>
            <div className="grid grid-cols-3 gap-3 mb-4 text-xs font-mono"><div><span className="text-bunker-muted">DURUM</span><p className="text-cyan-300 mt-1">{String(parityBackfill.status || "idle").toUpperCase()}</p></div><div><span className="text-bunker-muted">İLERLEME</span><p className="text-white mt-1">{parityBackfill.completed ?? 0}/{parityBackfill.total ?? 0} · %{parityBackfill.progress ?? 0}</p></div><div><span className="text-bunker-muted">SONUÇ</span><p className="text-neon-green mt-1">{parityBackfill.result ? `${parityBackfill.result.written ?? 0} eklendi` : "—"}</p></div></div>
            <div className="h-2 rounded bg-bunker-800 mb-4"><div className="h-2 rounded bg-cyan-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(parityBackfill.progress || 0)))}%` }} /></div>
            <div className="max-h-[36vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(parityBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(log.timestamp * 1000).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(parityBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
            {parityBackfill.status === "complete" && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded border border-neon-green/30 bg-neon-green/5 p-3"><p className="font-mono text-xs text-neon-green">Backfill tamamlandı. Tüm kapalı işlem ayrıntılarını indirip bu sohbete yükleyebilirsiniz.</p><button onClick={downloadParityTradeCsv} className="shrink-0 rounded-lg border border-neon-green/50 bg-neon-green/10 px-3 py-2 font-mono text-xs text-neon-green hover:bg-neon-green/20">TÜM İŞLEM CSV&apos;SİNİ İNDİR</button></div>}
            <p className="text-[11px] text-bunker-muted mt-3">Pencereyi kapatsanız da job backend&apos;de devam eder. CSV yalnızca kapalı paper işlemlerini; tam giriş bağlamı, teknik ve MTF JSON alanlarıyla içerir.</p>
          </div>
        </div>
      )}
      {mlBackfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setMlBackfillOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4"><div><p className="eyebrow text-emerald-300">ML HEDEF GERİ DOLDURMA</p><p className="font-mono text-sm text-white mt-1">{mlBackfill.message || "Hazırlanıyor..."}</p></div><button onClick={() => setMlBackfillOpen(false)} className="text-bunker-muted hover:text-white">✕</button></div>
            <div className="grid grid-cols-4 gap-3 mb-4 text-xs font-mono"><div><span className="text-bunker-muted">DURUM</span><p className="text-emerald-300 mt-1">{String(mlBackfill.status || "idle").toUpperCase()}</p></div><div><span className="text-bunker-muted">İLERLEME</span><p className="text-white mt-1">{mlBackfill.completed ?? 0}/{mlBackfill.total ?? 0} · %{mlBackfill.progress ?? 0}</p></div><div><span className="text-bunker-muted">GÜNCELLENEN</span><p className="text-neon-green mt-1">{mlBackfill.updated ?? 0}</p></div><div><span className="text-bunker-muted">ATLANAN</span><p className="text-yellow-300 mt-1">{mlBackfill.skipped ?? 0}</p></div></div>
            <div className="h-2 rounded bg-bunker-800 mb-4"><div className="h-2 rounded bg-emerald-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(mlBackfill.progress || 0)))}%` }} /></div>
            {mlBackfill.current_symbol && <p className="font-mono text-xs text-emerald-300 mb-3">İşlenen: {mlBackfill.current_symbol}</p>}
            <div className="max-h-[44vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(mlBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(log.timestamp * 1000).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(mlBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
            {mlBackfill.status === "complete" && mlBackfill.result && <div className="mt-4 rounded border border-neon-green/30 bg-neon-green/5 p-3 font-mono text-xs text-neon-green">Tamamlandı · güncellenen={mlBackfill.result.updated ?? 0} atlanan={mlBackfill.result.skipped ?? 0} sembol={mlBackfill.result.symbols ?? 0} · gölge (mevcut model)</div>}
            <p className="text-[11px] text-bunker-muted mt-3">Pencereyi kapatsanız da job backend&apos;de arka planda devam eder; tekrar açarak son durumu görebilirsiniz. İşlem, PnL ve pozisyonlar değişmez.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function AutoPaperSettingsPanel() {
  const [settings, setSettings] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [draft, setDraft] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [sRes, stRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/auto-paper/settings`),
        apiRequest(`${API_BASE}/api/auto-paper/stats`),
      ]);
      if (sRes.ok) { const d = await sRes.json(); setSettings(d.settings); setDraft(d.settings); }
      if (stRes.ok) { const d = await stRes.json(); setStats(d.stats); }
    } catch { setError("Veri alınamadı"); }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true); setError(null); setSaved(false);
    try {
      const res = await apiRequest(`${API_BASE}/api/auto-paper/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Kayıt hatası"); }
      const d = await res.json();
      setSettings(d.settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) { setError(e instanceof Error ? e.message : "Bilinmeyen hata"); }
    finally { setSaving(false); }
  };

  const resetData = async () => {
    if (!window.confirm("ESKİ TÜM TRADE/PORTFÖY VERİLERİ SİLİNECEK! Cüzdan 10.000 TL olarak sıfırlanacak. Devam etmek istiyor musunuz?")) return;
    setResetting(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/auto-paper/reset`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      if (!res.ok) throw new Error("Sıfırlama başarısız");
      setResetting(false);
      window.location.reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Sıfırlama hatası"); setResetting(false); }
  };

  const set = (key: string, value: any) => setDraft((prev: any) => ({ ...prev, [key]: value }));

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow mb-4">OTONOM PAPER TRADE AYARLARI</p>
      {error && <p className="text-neon-red text-xs mb-3">{error}</p>}
      {saved && <p className="text-neon-green text-xs mb-3">✅ Kaydedildi</p>}

      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Toplam</p>
            <p className="text-lg font-mono text-white">{stats.total}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Açık</p>
            <p className="text-lg font-mono text-yellow-300">{stats.open}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kapanmış</p>
            <p className="text-lg font-mono text-white">{stats.closed}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Başarı</p>
            <p className={`text-lg font-mono ${stats.win_rate >= 50 ? "text-neon-green" : "text-neon-red"}`}>%{stats.win_rate}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Net PnL</p>
            <p className={`text-lg font-mono ${stats.total_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"}`}>{stats.total_pnl_try >= 0 ? "+" : ""}{stats.total_pnl_try.toFixed(2)}₺</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kazanan</p>
            <p className="text-lg font-mono text-neon-green">{stats.winning}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kaybeden</p>
            <p className="text-lg font-mono text-neon-red">{stats.losing}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Ort. PnL</p>
            <p className={`text-lg font-mono ${stats.avg_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"}`}>{stats.avg_pnl_try >= 0 ? "+" : ""}{stats.avg_pnl_try.toFixed(2)}₺</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Aktif</label>
          <select value={draft.enabled ? "1" : "0"} onChange={(e) => set("enabled", e.target.value === "1")} className="input">
            <option value="1">Açık</option>
            <option value="0">Kapalı</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Minimum Skor (0-100)</label>
          <input type="number" min="0" max="100" value={draft.min_score ?? 50} onChange={(e) => set("min_score", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Bakiye Yüzdesi (%)</label>
          <input type="number" min="1" max="100" value={draft.balance_pct ?? 35} onChange={(e) => set("balance_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Stop Loss (%)</label>
          <input type="number" min="0.1" max="20" step="0.1" value={draft.stop_loss_pct ?? 3} onChange={(e) => set("stop_loss_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Varsayılan Hedef (%)</label>
          <input type="number" min="0.5" max="20" step="0.1" value={draft.default_target_pct ?? 2} onChange={(e) => set("default_target_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Minimum Emir (TRY)</label>
          <input type="number" min="10" value={draft.min_order_try ?? 50} onChange={(e) => set("min_order_try", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Breakeven Tetikleme (%)</label>
          <input type="number" min="0.5" max="10" step="0.1" value={draft.breakeven_trigger_pct ?? 1.5} onChange={(e) => set("breakeven_trigger_pct", Number(e.target.value))} className="input" />
        </div>
      </div>

      <div className="flex gap-3 mt-6">
        <button onClick={save} disabled={saving} className="px-5 py-2 rounded-lg border border-neon-green/50 text-neon-green font-mono text-xs hover:bg-neon-green/10 disabled:opacity-50">
          {saving ? "KAYDEDİLİYOR..." : "KAYDET"}
        </button>
        <button onClick={resetData} disabled={resetting} className="px-5 py-2 rounded-lg border border-neon-red/50 text-neon-red font-mono text-xs hover:bg-neon-red/10 disabled:opacity-50">
          {resetting ? "SIFIRLANIYOR..." : "TÜM VERİYİ SIFIRLA"}
        </button>
      </div>
    </div>
  );
}
