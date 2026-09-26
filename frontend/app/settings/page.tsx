"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { formatSignedTL, toMs } from "../lib/format";
import LlmManagement from "./LlmManagement";
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
  const [activeTab, setActiveTab] = useState<"symbols" | "radar" | "app" | "notifications" | "strategies" | "llm" | "chat" | "auto-paper" | "macd">("symbols");
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
  const [radarBackfillOpen, setRadarBackfillOpen] = useState(false);
  const [radarBackfill, setRadarBackfill] = useState<any>({ status: "idle", progress: 0, logs: [] });
  const [startingRadarBackfill, setStartingRadarBackfill] = useState(false);
  // TEST BİLDİRİMİ (2026-09-16): push zincirini tek tuşla sına. Bildirim
  // gelmediğinde NEREDE koptuğunu (VAPID yok / abone yok / teslim edilemedi)
  // backend `detail` alanında söyler.
  const [testingPush, setTestingPush] = useState(false);
  const [pushTestResult, setPushTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const tab = new URLSearchParams(window.location.search).get("tab") as any;
    if (tab && ["symbols", "radar", "app", "strategies", "auto-paper", "macd", "llm", "chat"].includes(tab)) {
      setActiveTab(tab);
    }
  }, []);

  const selectTab = (key: "symbols" | "radar" | "app" | "notifications" | "strategies" | "llm" | "chat" | "auto-paper" | "macd") => {
    setActiveTab(key);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", key);
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  };

  useEffect(() => {
    apiRequest(`${API_BASE}/api/config`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => { setCfg(d); setDraft(d); })
      .catch(() => setError(`Backend'e bağlanılamadı (${API_BASE})`));
    apiRequest(`${API_BASE}/api/market-symbols`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch(() => setError("Binance TR sembolleri alınamadı"));
    apiRequest(`${API_BASE}/api/llm/config`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setLlm)
      .catch(() => setError("LLM yapılandırması alınamadı (HTTP hatası)"));
    // `getJSON` 4xx/5xx'te Error fırlatır (4xx detayını `detail` alanından
    // taşır). Önceki elle `r.ok` deseni de çalışıyordu ama 7 yükleyicinin
    // tamamında tekrarlanıyordu ve hata mesajı backend detayını hep atıyordu.
    getJSON<{ min_score?: number | null }>("/api/monitoring/settings")
      .then((d) => {
        const ms = d.min_score ?? 50;
        setMonitoringMinScore(ms);
        setMonitoringMinScoreInput(String(Math.round(ms)));
      })
      .catch(() => undefined);
    loadMlStatus();
  }, []);

  // Aşağıdaki 6 yükleyicinin tamamı `.then(r => r.json())` deseni kullanıyordu:
  // 401/500'de hata gövdesi `{}` olarak state'e yazılıyor ve kullanıcı
  // "boş liste" görüp nedenini bilmiyordu. `getJSON` bunu tek yerde çözer.
  const loadTopGainers = useCallback(() => {
    getJSON<Record<string, unknown>>("/api/market/top-gainers")
      .then((d) => setTopGainers(d))
      .catch(() => undefined);
  }, []);
  useEffect(() => { loadTopGainers(); }, [loadTopGainers]);
  useVisibleInterval(loadTopGainers, 60000);

  const loadMtf = useCallback(() => {
    getJSON<Record<string, unknown>>("/api/historical-mtf-backfill/status")
      .then((d) => setMtfBackfill(d))
      .catch(() => undefined);
  }, []);
  useEffect(() => { if (mtfBackfillOpen) loadMtf(); }, [mtfBackfillOpen, loadMtf]);
  useVisibleInterval(loadMtf, mtfBackfillOpen ? 1500 : null);

  const loadParity = useCallback(() => {
    getJSON<Record<string, unknown>>("/api/replay-parity-backfill/status")
      .then((d) => setParityBackfill(d))
      .catch(() => undefined);
  }, []);
  useEffect(() => { if (parityBackfillOpen) loadParity(); }, [parityBackfillOpen, loadParity]);
  useVisibleInterval(loadParity, parityBackfillOpen ? 1500 : null);

  const loadMl = useCallback(() => {
    getJSON<Record<string, unknown>>("/api/velocity-ml-backfill/status")
      .then((d) => setMlBackfill(d))
      .catch(() => undefined);
  }, []);
  useEffect(() => { if (mlBackfillOpen) loadMl(); }, [mlBackfillOpen, loadMl]);
  useVisibleInterval(loadMl, mlBackfillOpen ? 1500 : null);

  const loadRadar = useCallback(() => {
    getJSON<Record<string, unknown>>("/api/radar-outcomes-backfill/status")
      .then((d) => setRadarBackfill(d))
      .catch(() => undefined);
  }, []);
  useEffect(() => { if (radarBackfillOpen) loadRadar(); }, [radarBackfillOpen, loadRadar]);
  useVisibleInterval(loadRadar, radarBackfillOpen ? 1500 : null);

  const loadActivity = useCallback(() => {
    getJSON<{ statuses?: Record<string, unknown> }>("/api/symbol-activity")
      .then((d) => setActivity(d.statuses || {}))
      .catch(() => undefined);
  }, []);
  useEffect(() => { loadActivity(); }, [loadActivity]);
  useVisibleInterval(loadActivity, 60000);

  // H-20: `symbol_activity` WS mesajı yalnızca manuel aktivasyon yenilemesinde
  // yayınlanır ve daha önce hiç tüketilmiyordu → başka bir sekmede yapılan
  // yenileme bu panelde 60 sn poll'a kadar bayat kalıyordu. Mesaj geldiğinde
  // durum anında güncellenir (güvenli + ucuz: yalnız setState).
  useLiveMessages((message: any) => {
    if (message.type === "symbol_activity" && message.data?.statuses) setActivity(message.data.statuses);
  });

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
    // Boş/whitespace girişi Number("") === 0 olarak kaydedilip TÜM adayları
    // geçirmesin — denetim maddesi: boş girişte validasyon hatası göster.
    if (monitoringMinScoreInput.trim() === "") { setError("Monitoring min skor boş olamaz (0-100 arası girin)"); return; }
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

  // TEST BİLDİRİMİ (2026-09-16): Ayarlar > Uygulama Ayarları'ndaki buton.
  // Backend'e "tüm aboneliklere test push'u gönder" der ve sonucu (veya zincirin
  // hangi katmanında koptuğunu) gösterir. Böylece kullanıcı push'un çalışıp
  // çalışmadığını gerçek bir bildirimle doğrular; "sessizce ölü" hâl kalmaz.
  const sendTestPush = async () => {
    setTestingPush(true);
    setPushTestResult(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/alerts/push-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Test bildirimi gönderilemedi (HTTP ${res.status})`);
      const sent = Number(data.sent ?? 0);
      const total = Number(data.total ?? 0);
      const dead = Number(data.dead ?? 0);
      setPushTestResult({
        ok: true,
        text: `✓ Gönderildi · ${sent}/${total} aboneye${dead > 0 ? ` · ${dead} ölü abonelik temizlendi` : ""}. `
          + "Bildirim gelmediyse işletim sistemi/tarayıcı bildirim izinlerini ve Rahatsız Etme modunu kontrol edin.",
      });
    } catch (err) {
      setPushTestResult({ ok: false, text: err instanceof Error ? err.message : "Test bildirimi gönderilemedi" });
    } finally {
      setTestingPush(false);
    }
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
  // H-30: boş sayısal input `num()` ile "0" olarak geri yazılıyordu; kullanıcı
  // alanı temizleyip rakam yazmak isterken "0" ile uğraşıyordu. Kaydetme
  // kontrolü (NaN reddi) zaten var → input boş kalabilir.
  const numInput = (v: any) =>
    v == null || v === "" || (typeof v === "number" && !Number.isFinite(v)) ? "" : v;
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
    if (!window.confirm("Tüm eski işlemler, sinyaller, karar logları ve snapshotlar silinecek. Cüzdan 10.000 TL ile başlayacak. Devam edilsin mi?")) return;
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

  const startRadarOutcomesBackfill = async () => {
    if (!window.confirm("Ölçülemeyen ('ÖLÇÜLEMEDİ') ve eksik radar/birleşik sinyal bildirimleri Binance TR arşiv 1m mumlarıyla geriye dönük hesaplanacak. Raporlar sayfasındaki başarı oranları güncellenecektir. Devam edilsin mi?")) return;
    setStartingRadarBackfill(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/radar-outcomes-backfill/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Radar backfill başlatılamadı");
      setRadarBackfillOpen(true);
      setRadarBackfill(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Radar backfill başlatılamadı");
    } finally {
      setStartingRadarBackfill(false);
    }
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
    // API key'i gönder; state'teki değer immutable güncellenir (React state'ini
    // doğrudan mutate etmek render'ı tetiklemez ve Strict Mode'da iz sürülemez).
    const apiKeyToSend = llmForm.api_key;
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
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(setMlStatus)
    .catch(() => setMlError("ML durumu alınamadı (HTTP hatası)"));

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
        <nav className="flex gap-2 overflow-x-auto border-b border-bunker-800 pb-2 no-scrollbar scrollbar-none touch-pan-x" aria-label="Ayar sekmeleri">
          {([
            ["symbols", "Semboller", "🪙"],
            ["radar", "Radar", "📡"],
            ["app", "Uygulama Ayarları", "⚙️"],
            ["notifications", "Bildirim Ayarları", "🔔"],
            ["strategies", "Strateji Ayarları", "📈"],
            ["auto-paper", "Otonom Paper", "🤖"],
            ["macd", "MACD / Sıçrama", "🚀"],
            ["llm", "LLM / Provider", "🤖"],
            ["chat", "Chat Ayarları", "✦"],
          ] as const).map(([key, label, icon]) => (
            <button key={key} onClick={() => selectTab(key)} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors touch-target ${activeTab === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green font-bold shadow-sm" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>
              {icon} {label}
            </button>
          ))}
        </nav>
      )}

      {cfg && (
        <>
          <div className={`${activeTab !== "radar" ? "hidden" : ""}`}>
            <div className="space-y-4">
              <RadarSettingsPanel />
              <RadarReplayPanel />
            </div>
          </div>
          <div className={`${activeTab !== "notifications" ? "hidden" : ""}`}>
            <NotificationSettingsPanel />
          </div>
          <div className={`${activeTab !== "chat" ? "hidden" : ""}`}>
            <ChatSettingsPanel />
          </div>
          <div className={`${activeTab !== "auto-paper" ? "hidden" : ""}`}>
            <AutoPaperSettingsPanel />
          </div>
          <div className={`${activeTab !== "macd" ? "hidden" : ""}`}>
            <MacdJumpSettingsPanel />
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
              <input type="number" min={0} max={100} step={1} value={numInput(draft.gainer_radar_min_score)} onChange={(e) => setDraft((d) => ({ ...d, gainer_radar_min_score: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none" />
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
                    <input type="number" min={0} step={step} value={numInput((draft as any)[key])} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" />
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Önerilen: 1.000.000 TL · 0,3x · 5x</p>
            </div>
          </div>
          <div className={`space-y-4 ${activeTab !== "llm" ? "hidden" : ""}`}>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">LLM PROVIDER EKLE</p><p className="text-xs text-bunker-muted mb-3">Yalnızca teknik yorum üretir; emir veya pozisyon kararı vermez.</p><div className="grid md:grid-cols-2 gap-3"><input placeholder="Provider adı" value={llmForm.name} onChange={e => setLlmForm({...llmForm,name:e.target.value})} className="input" /><input placeholder="Base URL (https://.../v1)" value={llmForm.base_url} onChange={e => setLlmForm({...llmForm,base_url:e.target.value})} className="input" /><input type="password" placeholder="API key" value={llmForm.api_key} onChange={e => setLlmForm({...llmForm,api_key:e.target.value})} className="input" /><button onClick={saveLlmProvider} disabled={!llm.encryption_configured || !llmForm.name.trim() || !llmForm.base_url.trim() || !llmForm.api_key.trim()} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs disabled:opacity-40 disabled:cursor-not-allowed">PROVIDER KAYDET</button></div><p className={`text-xs mt-3 ${llm.encryption_configured ? "text-bunker-muted" : "text-yellow-300"}`}>Şifreleme anahtarı: {llm.encryption_configured ? "hazır" : "sunucuda LLM_ENCRYPTION_KEY eksik; Provider kaydı için backend ortamına eklenmeli"}</p></div>
            <div className="card bg-bunker-950"><p className="eyebrow mb-3">MODEL / UZMANLIK</p><div className="grid md:grid-cols-2 gap-3"><select value={llmForm.provider_id} onChange={e => setLlmForm({...llmForm,provider_id:e.target.value})} className="input"><option value="">Provider seç</option>{(llm.providers ?? []).map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}</select><input placeholder="Model adı" value={llmForm.model} onChange={e => setLlmForm({...llmForm,model:e.target.value})} className="input" /><select value={llmForm.model_type} onChange={e => setLlmForm({...llmForm,model_type:e.target.value})} className="input"><option value="chat">Chat modeli</option><option value="embedding">Embedding modeli</option></select>{llmForm.model_type === "embedding" && <input type="number" min="1" placeholder="Embedding dimension" value={llmForm.dimensions} onChange={e => setLlmForm({...llmForm,dimensions:e.target.value})} className="input" />}<button onClick={() => llmRequest(`${API_BASE}/api/llm/models`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:Number(llmForm.provider_id),name:llmForm.model,model_type:llmForm.model_type,dimensions:llmForm.dimensions ? Number(llmForm.dimensions) : undefined})}, "Model kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">MODEL EKLE</button>{llmForm.model_type === "embedding" && <button onClick={async () => { const r=await apiRequest(`${API_BASE}/api/llm/embedding/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"embedding bağlantı testi"})}); const b=await r.json(); const m=b.status === "ok" ? `Embedding başarılı · ${b.dimensions} dimension` : (b.error || "Embedding testi başarısız"); setLlmMessage(m); window.alert(m); }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">EMBEDDING TEST ET</button>}<input placeholder="Uzmanlık adı" value={llmForm.skill} onChange={e => setLlmForm({...llmForm,skill:e.target.value})} className="input" /><textarea placeholder="Uzmanlık talimatları" value={llmForm.instructions} onChange={e => setLlmForm({...llmForm,instructions:e.target.value})} className="input min-h-24" /><button onClick={() => llmRequest(`${API_BASE}/api/llm/skills`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:llmForm.skill,instructions:llmForm.instructions})}, "Uzmanlık kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">UZMANLIK EKLE</button></div>{llmMessage && <p className="text-xs text-neon-green mt-3">{llmMessage}</p>}</div>
            <div className="card bg-bunker-950 flex flex-wrap gap-3"><select value={llm.active_model_id || ""} onChange={async e => { const id=Number(e.target.value); await llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:id})}, "LLM aktif edildi"); }} className="input"><option value="">Aktif model seç</option>{(llm.models ?? []).map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}</select><button onClick={() => llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:llm.active_model_id})}, "LLM aktif edildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">LLM AKTİF</button><button onClick={async () => { setLlmMessage("TEST EDİLİYOR..."); try { const r=await apiRequest(`${API_BASE}/api/llm/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const body=await r.json(); const message=body.status === "ok" ? "Bağlantı başarılı" : (body.error || body.status || "Test başarısız"); setLlmMessage(message); window.alert(message); } catch { setLlmMessage("LLM test bağlantısı kurulamadı"); window.alert("LLM test bağlantısı kurulamadı"); } }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">TEST ET</button></div>
            <div className="card border-purple-400/30 bg-purple-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"><div><p className="eyebrow text-purple-300">MEVCUT KAYITLARI VECTORLEŞTİR</p><p className="text-xs text-bunker-muted mt-2">Kapanmış işlemler ve sinyaller aktif embedding modeliyle pgvector memory tablosuna aktarılır.</p></div><div className="flex flex-wrap gap-2"><button onClick={backfillEmbeddings} disabled={backfilling} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${backfillDone ? "border-neon-green/60 text-neon-green" : "border-purple-400/50 text-purple-300"}`}>{backfilling ? "KUYRUĞA ALINIYOR..." : backfillDone ? "✓ KUYRUĞA ALINDI" : "EMBEDDING BACKFILL BAŞLAT"}</button><button onClick={repairHistoricalMemory} disabled={repairingMemory} className="shrink-0 px-4 py-2 rounded-lg border border-yellow-400/50 text-yellow-300 font-mono text-xs">{repairingMemory ? "ONARILIYOR..." : "TARİHSEL SNAPSHOT ONAR"}</button></div></div>
            <div className="card border-yellow-400/30 bg-yellow-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"><div><p className="eyebrow text-yellow-300">LLM PAPER İŞLEM YETKİSİ</p><p className="text-xs text-bunker-muted mt-2">Açıkken LLM yalnızca sanal portföyde kontrollü LONG pozisyonu açabilir. Gerçek emir API'si kullanılmaz.</p></div><div className="flex gap-2"><button onClick={async()=>{const enabled=!llm.paper_trade_enabled;await llmRequest(`${API_BASE}/api/llm/paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Paper işlem yetkisi açıldı":"Paper işlem yetkisi kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.paper_trade_enabled?"border-neon-green/60 text-neon-green":"border-bunker-700 text-bunker-muted"}`}>{llm.paper_trade_enabled?"AÇIK · KAPAT":"KAPALI · AÇ"}</button><button disabled={!llm.paper_trade_enabled} onClick={async()=>{const enabled=!llm.auto_paper_enabled;await llmRequest(`${API_BASE}/api/llm/auto-paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Kapanış sonrası otomatik yenileme açıldı":"Otomatik yenileme kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.auto_paper_enabled?"border-yellow-300/60 text-yellow-300":"border-bunker-700 text-bunker-muted"}`}>{llm.auto_paper_enabled?"KAPANIŞ SONRASI · KAPAT":"KAPANIŞ SONRASI · AÇ"}</button></div></div>
            <LlmManagement llm={llm} reload={reloadLlm} />
          </div>

          <div className={`card border-neon-red/30 bg-neon-red/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-red">PAPER TRADING KAYITLARI</p>
                <p className="font-mono text-sm text-white mt-2">Tüm eski paper-trading ve strateji geçmişini temizle</p>
                <p className="text-xs text-bunker-muted mt-1">İşlemler, sinyaller, karar logları ve snapshotlar silinir. Ayarlar ve piyasa cache&apos;i korunur; yeni bakiye 10.000 TL olur.</p>
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
                <p className="text-xs text-bunker-muted mt-1">PostgreSQL custom-format .dump yedeği alınır. İşlemler, sinyaller ve açık pozisyonlar dahil edilir.</p>
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
                    // Audit: eksik alan .toLocaleString'de crash ediyordu → "—" fallback.
                    ? `Son eğitim: ${new Date(toMs(mlStatus.artifact.created_at)).toLocaleString("tr-TR")} · ${mlStatus.artifact.sample_count?.toLocaleString?.("tr-TR") ?? "—"} örnek · ${mlStatus.artifact.symbol_count ?? "—"} sembol · ${mlStatus.artifact.journal_sample_count ?? "—"} journal örneği`
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
                  value={numInput(draft.default_order_usdt)}
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
                  value={numInput(draft.max_open_positions)}
                  onChange={(e) => setDraft((d) => ({ ...d, max_open_positions: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>

              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
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
                  <p className="font-mono text-sm text-white">Kapanış Sonrası Cooldown</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Yeni girişten önce beklenecek mum sayısı</p>
                </div>
                <input type="number" step={1} min={0} max={100} value={numInput(draft.cooldown_bars)} onChange={(e) => setDraft((d) => ({ ...d, cooldown_bars: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right outline-none" />
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

          {/* TEST BİLDİRİMİ (2026-09-16): push zincirini UÇTAN UCA kanıtlar.
              Bildirim gelmiyorsa backend kopan katmanı `detail` alanında söyler
              (VAPID yok / kayıtlı abone yok / teslim edilemedi) — kullanıcı
              "push çalışmıyor" demek yerine NEDENİNİ görür. */}
          <div className={`card border-sky-400/30 bg-sky-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-sky-300">BİLDİRİM TESTİ</p>
                <p className="text-xs text-bunker-muted mt-1">Tüm kayıtlı cihazlara bir test bildirimi gönderir. Ses, başlık ve tıklama davranışını (bildirime dokununca monitoring sayfası açılır) doğrular. Bildirim gelmezse önce tarayıcı bildirim iznini ve Rahatsız Etme modunu kontrol edin.</p>
              </div>
              <button
                type="button"
                onClick={sendTestPush}
                disabled={testingPush || !isAdmin}
                className="shrink-0 px-4 py-2 rounded-lg border border-sky-400/50 text-sky-300 font-mono text-xs hover:bg-sky-400/10 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testingPush ? "GÖNDERİLİYOR…" : "TEST BİLDİRİMİ GÖNDER"}
              </button>
            </div>
            {pushTestResult && (
              <p className={`mt-3 font-mono text-xs ${pushTestResult.ok ? "text-neon-green" : "text-neon-red"}`}>
                {pushTestResult.text}
              </p>
            )}
          </div>

          {/* RADAR ÖLÇÜMLERİNİ YENİDEN HESAPLA (BACKFILL / REPLAY) */}
          <div className={`card border-neon-green/30 bg-neon-green/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-green">RADAR ÖLÇÜMLERİNİ YENİDEN HESAPLA (BACKFILL / REPLAY)</p>
                <p className="text-xs text-bunker-muted mt-1">
                  Ufku dolmuş ancak geçmişte ölçülememiş (&quot;ÖLÇÜLEMEDİ&quot; kalmış) tüm radar ve birleşik sinyal bildirimlerini Binance TR 1m arşiv mumlarıyla geriye dönük tarar. Gerçek MFE, çıkış yüzdesi ve hedef dokunuşunu hesaplayarak Raporlar sayfasındaki başarı tablosunu günceller.
                </p>
              </div>
              <button
                type="button"
                onClick={startRadarOutcomesBackfill}
                disabled={startingRadarBackfill || !isAdmin || radarBackfill.status === "running"}
                className="shrink-0 px-4 py-2 rounded-lg border border-neon-green/50 text-neon-green font-mono text-xs hover:bg-neon-green/10 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {startingRadarBackfill || radarBackfill.status === "running" ? "HESAPLANIYOR…" : "RADAR ÖLÇÜMLERİNİ YENİDEN HESAPLA"}
              </button>
            </div>
            {radarBackfill.status === "running" && (
              <div className="mt-3 flex items-center gap-3">
                <div className="flex-1 h-2 rounded bg-bunker-800">
                  <div className="h-2 rounded bg-neon-green transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(radarBackfill.progress || 0)))}%` }} />
                </div>
                <span className="font-mono text-xs text-neon-green">%{radarBackfill.progress || 0}</span>
                <button
                  type="button"
                  onClick={() => setRadarBackfillOpen(true)}
                  className="font-mono text-xs text-bunker-muted underline hover:text-white"
                >
                  Detayları Göster
                </button>
              </div>
            )}
          </div>
        </>
      )}
      {mtfBackfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setMtfBackfillOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4"><div><p className="eyebrow text-purple-300">MTF BACKFILL LOG</p><p className="font-mono text-sm text-white mt-1">{mtfBackfill.message || "Hazırlanıyor..."}</p></div><button onClick={() => setMtfBackfillOpen(false)} className="text-bunker-muted hover:text-white">✕</button></div>
            <div className="grid grid-cols-3 gap-3 mb-4 text-xs font-mono"><div><span className="text-bunker-muted">DURUM</span><p className="text-purple-300 mt-1">{String(mtfBackfill.status || "idle").toUpperCase()}</p></div><div><span className="text-bunker-muted">İLERLEME</span><p className="text-white mt-1">{mtfBackfill.completed ?? 0}/{mtfBackfill.total ?? 0} · %{mtfBackfill.progress ?? 0}</p></div><div><span className="text-bunker-muted">SONUÇ</span><p className="text-neon-green mt-1">{mtfBackfill.result ? `${mtfBackfill.result.updated} güncellendi` : "—"}</p></div></div>
            <div className="h-2 rounded bg-bunker-800 mb-4"><div className="h-2 rounded bg-purple-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(mtfBackfill.progress || 0)))}%` }} /></div>
            <div className="max-h-[48vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(mtfBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(toMs(log.timestamp)).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(mtfBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
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
            <div className="max-h-[36vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(parityBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(toMs(log.timestamp)).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(parityBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
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
            <div className="max-h-[44vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">{(mlBackfill.logs || []).map((log: any, index: number) => <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>[{log.timestamp ? new Date(toMs(log.timestamp)).toLocaleTimeString("tr-TR") : "—"}] {log.message}</p>)}{!(mlBackfill.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}</div>
            {mlBackfill.status === "complete" && mlBackfill.result && <div className="mt-4 rounded border border-neon-green/30 bg-neon-green/5 p-3 font-mono text-xs text-neon-green">Tamamlandı · güncellenen={mlBackfill.result.updated ?? 0} atlanan={mlBackfill.result.skipped ?? 0} sembol={mlBackfill.result.symbols ?? 0} · gölge (mevcut model)</div>}
            <p className="text-[11px] text-bunker-muted mt-3">Pencereyi kapatsanız da job backend&apos;de arka planda devam eder; tekrar açarak son durumu görebilirsiniz. İşlem, PnL ve pozisyonlar değişmez.</p>
          </div>
        </div>
      )}
      {radarBackfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setRadarBackfillOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4">
              <div>
                <p className="eyebrow text-neon-green">RADAR ÖLÇÜM YENİDEN HESAPLAMA (BACKFILL)</p>
                <p className="font-mono text-sm text-white mt-1">{radarBackfill.message || "Hazırlanıyor..."}</p>
              </div>
              <button onClick={() => setRadarBackfillOpen(false)} className="text-bunker-muted hover:text-white">✕</button>
            </div>
            <div className="grid grid-cols-4 gap-3 mb-4 text-xs font-mono">
              <div>
                <span className="text-bunker-muted">DURUM</span>
                <p className="text-neon-green mt-1">{String(radarBackfill.status || "idle").toUpperCase()}</p>
              </div>
              <div>
                <span className="text-bunker-muted">İLERLEME</span>
                <p className="text-white mt-1">{radarBackfill.completed ?? 0}/{radarBackfill.total ?? 0} · %{radarBackfill.progress ?? 0}</p>
              </div>
              <div>
                <span className="text-bunker-muted">GÜNCELLENEN</span>
                <p className="text-neon-green mt-1">{radarBackfill.updated ?? 0}</p>
              </div>
              <div>
                <span className="text-bunker-muted">ATLANAN</span>
                <p className="text-yellow-300 mt-1">{radarBackfill.skipped ?? 0}</p>
              </div>
            </div>
            <div className="h-2 rounded bg-bunker-800 mb-4">
              <div className="h-2 rounded bg-neon-green transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(radarBackfill.progress || 0)))}%` }} />
            </div>
            {radarBackfill.current_symbol && (
              <p className="font-mono text-xs text-neon-green mb-3">İşlenen: {radarBackfill.current_symbol}</p>
            )}
            <div className="max-h-[44vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">
              {(radarBackfill.logs || []).map((log: any, index: number) => (
                <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>
                  [{log.timestamp ? new Date(toMs(log.timestamp)).toLocaleTimeString("tr-TR") : "—"}] {log.message}
                </p>
              ))}
              {!(radarBackfill.logs || []).length && (
                <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>
              )}
            </div>
            {radarBackfill.status === "complete" && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded border border-neon-green/30 bg-neon-green/5 p-3">
                <p className="font-mono text-xs text-neon-green">
                  Yeniden hesaplama tamamlandı! {radarBackfill.updated ?? 0} bildirim başarıyla güncellendi.
                </p>
                <a
                  href="/reports"
                  className="shrink-0 rounded-lg border border-neon-green/50 bg-neon-green/10 px-3 py-1.5 font-mono text-xs text-neon-green hover:bg-neon-green/20"
                >
                  RAPORLARI GÖRÜNTÜLE →
                </a>
              </div>
            )}
            <p className="text-[11px] text-bunker-muted mt-3">Pencereyi kapatsanız da işlem arka planda devam eder; tekrar açarak son durumu görebilirsiniz.</p>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 📡 RADAR AYARLARI (2026-09-16) — Monitoring sayfasındaki global bildirim ayar
 * kartı BURAYA taşındı (Ayarlar > Radar). Aynı uçlar kullanılır:
 *   GET  /api/monitoring/settings   (okuma)
 *   PUT  /api/monitoring/settings   (yazım — merge semantiği, yalnız gönderilenler)
 * Ayrıca birleşik radar (Hız Avcısı + Yükseliş + Radar) anahtarları da buradadır:
 *   radar_combined_enabled / radar_unified_notify /
 *   radar_route_velocity_auto_through_auto_paper / radar_confluence_window_sec
 * Kapalıyken hiçbir üretim davranışı değişmez — anahtarlar Aşama 2 teslimatı için.
 *
 * NOT: Bu bileşen Monitoring'deki CANLI göstergeleri içermez; eşik rozeti, sağlık
 * çipleri, teşhis kartı ve "ŞİMDİ TARA"/"BİLDİRİM SIFIRLA" operatörlük eylemleri
 * Monitoring'de kalır (orada sunucu state'i ile beslenmeye devam eder).
 */
function RadarSettingsPanel() {
  const [settings, setSettings] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [minScoreInput, setMinScoreInput] = useState<string>("");
  const [targetPctInput, setTargetPctInput] = useState<string>("");
  const [quietStart, setQuietStart] = useState("");
  const [quietEnd, setQuietEnd] = useState("");
  const [confluenceInput, setConfluenceInput] = useState<string>("");

  const load = async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSettings(data && typeof data === "object" ? data : null);
      if (data?.min_score != null) setMinScoreInput(String(data.min_score));
      if (data?.min_target_pct != null) setTargetPctInput(String(data.min_target_pct));
      if (data?.quiet_hours_start) setQuietStart(String(data.quiet_hours_start));
      if (data?.quiet_hours_end) setQuietEnd(String(data.quiet_hours_end));
      if (data?.radar_confluence_window_sec != null) setConfluenceInput(String(data.radar_confluence_window_sec));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Radar ayarları okunamadı");
    }
  };

  useEffect(() => { load(); }, []);

  const put = async (patch: Record<string, unknown>, okMessage: string) => {
    setSaving(true); setError(null); setNote(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (res.status === 401 || res.status === 403) { setError("Ayarları yalnız yönetici değiştirebilir — yetkiniz yok."); return; }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setNote(okMessage);
      await load();
    } catch (err) {
      setError(`Ayar kaydedilemedi: ${err instanceof Error ? err.message : "bilinmeyen hata"}`);
    } finally {
      setSaving(false);
    }
  };

  const saveMinScore = async () => {
    const val = Number(minScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) { setError("Eşik 0-100 arasında bir sayı olmalı."); return; }
    await put({ min_score: val }, "Eşik kaydedildi.");
  };

  // Min hedef aralığı SUNUCUDAN gelir (tek doğruluk kaynağı). İstemci yalnız
  // `val < 0` kontrol ederken aralık dışı bir değer kaydedilmeye çalışılıyor ve
  // sunucu 422 dönüyordu — kullanıcı NEDENİNİ göremiyordu.
  const targetMin = Number(settings?.min_target_pct_min ?? 1.5) || 1.5;
  const targetMax = Number(settings?.min_target_pct_max ?? 6) || 6;

  const saveTargetPct = async () => {
    const val = Number(targetPctInput);
    if (!Number.isFinite(val) || val < targetMin || val > targetMax) {
      setError(`Min hedef % ${targetMin}-${targetMax} arasında olmalı (sunucu aralığı).`);
      return;
    }
    await put({ min_target_pct: val }, "Min hedef % kaydedildi.");
  };

  const saveQuietHours = async () => {
    if ((quietStart && !quietEnd) || (!quietStart && quietEnd)) { setError("Sessiz saat başlangıç ve bitiş birlikte girilmeli."); return; }
    await put({ quiet_hours_start: quietStart || null, quiet_hours_end: quietEnd || null }, "Sessiz saatler kaydedildi.");
  };

  const saveConfluence = async () => {
    const val = Number(confluenceInput);
    if (!Number.isFinite(val) || val < 60 || val > 21600) { setError("Çakışma penceresi 60-21600 sn arasında olmalı."); return; }
    await put({ radar_confluence_window_sec: Math.round(val) }, "Çakışma penceresi kaydedildi.");
  };

  const toggle = (key: string, current: boolean | null, onText: string, offText: string) => (
    <button
      type="button"
      onClick={() => put({ [key]: !current }, `${onText}/${offText} kaydedildi.`)}
      disabled={saving || current == null}
      className={`ui-button ui-button-secondary mt-1 font-mono ${current ? "text-neon-green" : "text-bunker-muted"}`}
    >
      {current == null ? "—" : current ? "AÇIK" : "KAPALI"}
    </button>
  );

  const numInputCls = "mt-1 w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none";
  const timeInputCls = "bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none";

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow text-neon-green">⚙️ RADAR · BİLDİRİM AYARLARI (GLOBAL · YÖNETİCİ)</p>
      <p className="text-xs text-bunker-muted mt-1">Radar eşiği radar listesi, bildirim, rapor ve otonom taramada aynen uygulanır. Değişiklik tüm kullanıcıları anında etkiler.</p>

      {error && <p className="mt-3 font-mono text-xs text-neon-red">⚠ {error}</p>}
      {note && <p className="mt-3 font-mono text-xs text-neon-green">✓ {note}</p>}
      {!settings && !error && <p className="mt-3 font-mono text-xs text-bunker-muted animate-pulse">Yükleniyor...</p>}

      {settings && (
        <div className="mt-4 space-y-4">
          {/* EŞİK + BİLDİRİM ANAHTARI */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <p className="eyebrow text-bunker-muted">MİN SKOR (0-100)</p>
              <input type="number" min={0} max={100} step={1} value={minScoreInput}
                onChange={(e) => setMinScoreInput(e.target.value)} placeholder="—" className={numInputCls} />
            </div>
            <button type="button" onClick={saveMinScore} disabled={saving}
              className="ui-button ui-button-primary">{saving ? "KAYDEDİLİYOR…" : "EŞİĞİ KAYDET"}</button>
            <button type="button" onClick={() => put({ min_score: null }, "Eşik varsayılana sıfırlandı.")}
              disabled={saving || settings.min_score_explicit === false}
              title="Varsayılan ham eşik değerine dön (sunucu MONITORING_MIN_RAW_SCORE)"
              className="ui-button ui-button-secondary">SIFIRLA</button>
            <div>
              <p className="eyebrow text-bunker-muted">BİLDİRİMLER</p>
              {toggle("enabled", settings.enabled, "Bildirimler açıldı", "Bildirimler kapatıldı")}
            </div>
          </div>

          {/* HEDEF + SESSİZ SAAT */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <p className="eyebrow text-bunker-muted">MİN HEDEF %</p>
              <input type="number" min={targetMin} max={targetMax} step={0.1} value={targetPctInput}
                onChange={(e) => setTargetPctInput(e.target.value)} placeholder="—" className={numInputCls} />
              <p className="text-[11px] text-bunker-muted mt-1">{targetMin}-{targetMax} arası</p>
            </div>
            <button type="button" onClick={saveTargetPct} disabled={saving}
              className="ui-button ui-button-primary">{saving ? "KAYDEDİLİYOR…" : "KAYDET"}</button>
            <div>
              <p className="eyebrow text-bunker-muted">SESSİZ SAATLER</p>
              <div className="mt-1 flex items-center gap-1.5">
                <input type="time" value={quietStart} onChange={(e) => setQuietStart(e.target.value)} className={timeInputCls} />
                <span className="font-mono text-xs text-bunker-muted">→</span>
                <input type="time" value={quietEnd} onChange={(e) => setQuietEnd(e.target.value)} className={timeInputCls} />
              </div>
            </div>
            <button type="button" onClick={saveQuietHours} disabled={saving}
              className="ui-button ui-button-primary">{saving ? "KAYDEDİLİYOR…" : "KAYDET"}</button>
          </div>

          {/* BİRLEŞİK RADAR (Aşama 1/2) */}
          <div className="border-t border-bunker-800 pt-4">
            <p className="eyebrow text-sky-300">BİRLEŞİK RADAR · HIZ AVCISI + YÜKSELİŞ + TESPİT</p>
            <p className="text-xs text-bunker-muted mt-1">Üç sinyal kaynağı tek karar noktasında birleşir: her kaynak kendi kalibre eşiğini korur, sembol herhangi birini geçerse adaydır. İki kaynak aynı pencere içinde geçerse <span className="font-mono">confluence</span> işaretlenir. Yeni eşik icat edilmez.</p>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div>
                <p className="eyebrow text-bunker-muted">BİRLEŞİK MOTOR</p>
                {toggle("radar_combined_enabled", settings.radar_combined_enabled, "Birleşik motor açıldı", "Birleşik motor kapatıldı")}
              </div>
              <div>
                <p className="eyebrow text-bunker-muted">TEK TİP BİLDİRİM</p>
                {toggle("radar_unified_notify", settings.radar_unified_notify, "Tek tip bildirim açıldı", "Tek tip bildirim kapatıldı")}
                <p className="text-[11px] text-bunker-muted mt-1 max-w-[26ch]">Aynı sembol için iki ayrı push yerine tek bildirim (tag: radar-SEMBOLOLUŞUR).</p>
              </div>
              <div>
                <p className="eyebrow text-bunker-muted">OTONOM → AUTO PAPER</p>
                {toggle("radar_route_velocity_auto_through_auto_paper", settings.radar_route_velocity_auto_through_auto_paper, "Yönlendirme açıldı", "Yönlendirme kapatıldı")}
                <p className="text-[11px] text-bunker-muted mt-1 max-w-[26ch]">Tüm otonom paper pozisyonları tek defterde; max 3 açık pozisyon ve B1-B4 merdiveniyle kapanır.</p>
              </div>
              <div>
                <p className="eyebrow text-bunker-muted">ÇAKIŞMA PENCERESİ (SN)</p>
                <input type="number" min={60} max={21600} step={60} value={confluenceInput}
                  onChange={(e) => setConfluenceInput(e.target.value)} placeholder="1800"
                  title="İki kaynağın aynı olay sayılması için maksimum aralık (60-21600 sn)"
                  className={numInputCls} />
              </div>
              <button type="button" onClick={saveConfluence} disabled={saving}
                className="ui-button ui-button-primary">{saving ? "KAYDEDİLİYOR…" : "KAYDET"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 🔔 BİLDİRİM AYARLARI (2026-09-20) — Admin gerçek işlem bildirimi alıcıları.
 * Binance TR sayfasından pozisyon açılırken "Bildirim Gönder" işaretlenirse
 * push yalnız burada seçilen kullanıcılara gider:
 *   GET/POST /api/notifications/recipients  (alıcı listesi — admin)
 *   GET      /api/admin/users               (kullanıcı listesi — admin)
 * Bildirim "{kullanıcı} {SEMBOLOLUŞUR} sembolünde {fiyat} fiyatla pozisyon
 * açtı" biçimindedir; tutar/miktar İÇERMEZ. Teslimat yalnız oturum açmış ve
 * push izni vermiş kullanıcıların kayıtlı cihazlarına yapılır.
 */
function NotificationSettingsPanel() {
  const [users, setUsers] = useState<{ username: string; role: string; is_active: boolean }[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [usersRes, recRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/admin/users`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/notifications/recipients`, { cache: "no-store" }),
      ]);
      if (!usersRes.ok) throw new Error(`Kullanıcı listesi alınamadı (HTTP ${usersRes.status})`);
      if (!recRes.ok) throw new Error(`Alıcılar okunamadı (HTTP ${recRes.status})`);
      const usersData = await usersRes.json().catch(() => ({}));
      const recData = await recRes.json().catch(() => ({}));
      setUsers(Array.isArray(usersData.users) ? usersData.users : []);
      setSelected(Array.isArray(recData.recipients) ? recData.recipients : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bildirim ayarları okunamadı");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const toggleUser = (username: string) => {
    setSelected((prev) => (prev.includes(username) ? prev.filter((u) => u !== username) : [...prev, username]));
  };

  const save = async () => {
    setSaving(true); setError(null); setNote(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/notifications/recipients`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipients: selected }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json().catch(() => ({}));
      if (Array.isArray(data.recipients)) setSelected(data.recipients);
      setNote("Bildirim alıcıları kaydedildi.");
    } catch (err) {
      setError(`Kaydedilemedi: ${err instanceof Error ? err.message : "bilinmeyen hata"}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow text-neon-green">🔔 BİLDİRİM AYARLARI · YÖNETİCİ İŞLEM BİLDİRİMİ</p>
      <p className="text-xs text-bunker-muted mt-1">
        Yönetici Binance TR sayfasından gerçek pozisyon açarken <span className="text-white font-bold">“Bildirim gönder”</span> seçeneğini işaretlerse,
        seçili kullanıcılara sembol ve açılış fiyatı bildirilir (tutar/miktar gönderilmez). Bildirim yalnız uygulamada oturum açmış ve push izni vermiş kullanıcılara iletilir.
      </p>

      {error && <p className="mt-3 font-mono text-xs text-neon-red">⚠ {error}</p>}
      {note && <p className="mt-3 font-mono text-xs text-neon-green">✓ {note}</p>}
      {loading && <p className="mt-3 font-mono text-xs text-bunker-muted animate-pulse">Yükleniyor...</p>}

      {!loading && (
        <div className="mt-4 space-y-3">
          <p className="eyebrow text-bunker-muted">BİLDİRİM ALACAK KULLANICILAR · {selected.length}</p>
          {users.length === 0 && <p className="text-xs text-bunker-muted font-mono">Kullanıcı bulunamadı.</p>}
          <div className="grid gap-1.5 sm:grid-cols-2">
            {users.map((u) => {
              const active = selected.includes(u.username);
              return (
                <label key={u.username} className={`flex cursor-pointer select-none items-center gap-2 rounded-lg border px-3 py-2 transition-colors ${active ? "border-neon-green/60 bg-neon-green/10" : "border-bunker-700 bg-bunker-900/60 hover:border-bunker-600"}`}>
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleUser(u.username)}
                    className="h-4 w-4 accent-[color:var(--neon-green,#22c55e)]"
                  />
                  <span className={`font-mono text-xs ${active ? "text-neon-green font-bold" : "text-bunker-muted"}`}>{u.username}</span>
                  {String(u.role || "").toLowerCase() === "admin" && (
                    <span className="ml-auto rounded bg-sky-400/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-sky-300">ADMIN</span>
                  )}
                  {u.is_active === false && <span className="ml-auto rounded bg-neon-red/15 px-1.5 py-0.5 font-mono text-[10px] text-neon-red">PASİF</span>}
                </label>
              );
            })}
          </div>
          <button type="button" onClick={save} disabled={saving} className="ui-button ui-button-primary">
            {saving ? "KAYDEDİLİYOR…" : "ALICILARI KAYDET"}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * 📡 BİRLEŞİK RADAR REPLAY (2026-09-16) — 24 saatlik backtest, canlı log + CSV.
 * Backend: POST /api/combined-radar-replay/start + GET .../status + .../report.csv.
 * Üretim davranışını DEĞİŞTİRMEZ; yalnız journal + geçmiş mumlarla ölçer.
 */
function RadarReplayPanel() {
  const [job, setJob] = useState<any>({ status: "idle", progress: 0, completed: 0, total: 0, logs: [], result: null });
  const [open, setOpen] = useState(false);
  const [hours, setHours] = useState("24");
  // OUT-OF-SAMPLE: pencereyi geçmişe kaydırır. Tek dönemde ızgaranın maksimumunu
  // seçmek iyimser yanlıdır; aynı ızgara ikinci bir dönemde koşulup en iyi hücrenin
  // DAYANIP DAYANMADIĞI ölçülür. 0 = kapat (şimdiye kadar).
  const [offsetHours, setOffsetHours] = useState("0");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/combined-radar-replay/status`, { cache: "no-store" });
      if (res.ok) setJob(await res.json());
    } catch { /* durum okunamadı — açık pencere poll ile tekrar dener */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useVisibleInterval(load, open ? 2000 : null);

  const start = async () => {
    setError(null);
    setOpen(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/combined-radar-replay/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hours: Number(hours) || 24,
                               offset_hours: Number(offsetHours) || 0 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      setJob(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay başlatılamadı");
    }
  };

  const downloadCsv = async (path = "report.csv", fallback = "birlesik-radar-replay.csv") => {
    try {
      const response = await apiRequest(`${API_BASE}/api/combined-radar-replay/${path}`, { cache: "no-store" });
      if (!response.ok) {
        // Sunucunun SEBEBİNİ kaybetme: sonuç yokken uç 409 + açıklama döner
        // ("replay hiç çalıştırılmadı" / "hâlâ çalışıyor" / "HATA ile durdu").
        // Eskiden burada genel bir mesaj vardı ve kullanıcı boş dosyayı
        // "replay çalıştı ama sonuç boş" sanıyordu.
        let detail = "";
        try {
          const body = await response.json();
          detail = typeof body?.detail === "string" ? body.detail : "";
        } catch { /* gövde JSON değilse genel mesaja düş */ }
        throw new Error(detail || `Replay CSV indirilemedi (HTTP ${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const disposition = response.headers.get("content-disposition") || "";
      anchor.download = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallback;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay CSV indirilemedi");
    }
  };

  const running = job?.status === "running";
  const complete = job?.status === "complete";
  const pct = Math.max(0, Math.min(100, Number(job?.progress || 0)));

  return (
    <div className="card bg-bunker-950">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="eyebrow text-amber-300">REPLAY / BACKTEST (24s / 72s)</p>
          <p className="text-xs text-bunker-muted mt-1">Birleşik radarın (Hız Avcısı + Yükseliş + MACD Sıçrama/Erken Sıçrama + <span className="font-mono">unified</span> füzyon) geçmiş başarısını, geçmiş mumlarla B1-B4 merdivenini simüle ederek ölçer. Üretim davranışını <span className="font-mono">DEĞİŞTİRMEZ</span>.</p>
        </div>
        <div className="flex items-center gap-2">
          {/* OUT-OF-SAMPLE: pencereyi geçmişe kaydırır. "24 saat + 24 saat önce"
              tamamen AYRI bir dönemi ölçer → tek dönemde seçilen en iyi TP/SL
              hücresinin o dönemde DAYANIP DAYANMADIĞI görülür. */}
          <label className="flex items-center gap-1.5"
            title="Out-of-sample: pencereyi kaç saat geriye kaydır. 0 = şimdiye kadar. Örn. pencere=24 ve önce=24 → önceki gün (baz dönemle çakışmayan ayrı dönem).">
            <span className="font-mono text-[10px] text-bunker-muted">ÖNCE</span>
            <input type="number" min={0} max={720} value={offsetHours} onChange={(e) => setOffsetHours(e.target.value)}
              className="w-16 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-amber-300/60 outline-none" />
          </label>
          <input type="number" min={1} max={168} value={hours} onChange={(e) => setHours(e.target.value)}
            title="Geriye dönük pencere (saat). 24 = son 24 saat, 72 = son 72 saat."
            className="w-20 bg-bunker-900 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-amber-300/60 outline-none" />
          <button type="button" onClick={start} disabled={running}
            className="shrink-0 px-4 py-2 rounded-lg border border-amber-300/50 text-amber-300 font-mono text-xs hover:bg-amber-300/10 disabled:opacity-50 disabled:cursor-not-allowed">
            {running ? "ÇALIŞIYOR…" : "REPLAY BAŞLAT"}
          </button>
        </div>
      </div>
      {Number(offsetHours) > 0 && (
        <p className="mt-3 font-mono text-[11px] text-amber-300/80">
          OUT-OF-SAMPLE DOĞRULAMA: <b>baz dönem de ayrıca koşulur</b> (iki dönem, aynı TP/SL
          ızgarası) ve baz dönemin en iyi hücresi bu dönemde de pozitif kalıyor mu diye
          karşılaştırılır. Karar raporun sonunda <span className="text-white">KARAR:</span>{" "}
          satırında çıkar (kural önceden sabit — sonuca göre yorumlanamaz). Süre ~2× uzar.
          İki dönem ÇAKIŞMAMALI: bu pencere {hours} saat olduğu için ÖNCE ≥ {hours} olmalı.
        </p>
      )}
      {error && <p className="mt-3 font-mono text-xs text-neon-red">⚠ {error}</p>}

      {open && (
        <div className="fixed inset-0 z-50 bg-black/70 p-4 flex items-center justify-center" onClick={() => setOpen(false)}>
          <div className="card bg-bunker-950 w-full max-w-3xl max-h-[85vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-4">
              <div>
                <p className="eyebrow text-amber-300">BİRLEŞİK RADAR REPLAY</p>
                <p className="font-mono text-sm text-white mt-1">{job?.message || "Hazırlanıyor..."}</p>
              </div>
              <button onClick={() => setOpen(false)} className="text-bunker-muted hover:text-white">✕</button>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-4 text-xs font-mono">
              <div><span className="text-bunker-muted">DURUM</span><p className="text-amber-300 mt-1">{String(job?.status || "idle").toUpperCase()}</p></div>
              <div><span className="text-bunker-muted">İLERLEME</span><p className="text-white mt-1">{job?.completed ?? 0}/{job?.total ?? 0} · %{job?.progress ?? 0}</p></div>
              <div><span className="text-bunker-muted">SONUÇ</span><p className="text-neon-green mt-1">{complete ? "RAPOR HAZIR" : "—"}</p></div>
            </div>
            <div className="h-2 rounded bg-bunker-800 mb-4"><div className="h-2 rounded bg-amber-400 transition-all" style={{ width: `${pct}%` }} /></div>
            <div className="max-h-[26vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 space-y-1">
              {(job?.logs || []).map((log: any, index: number) => (
                <p key={`${log.timestamp}-${index}`} className={`font-mono text-[11px] ${log.level === "error" ? "text-red-300" : log.level === "success" ? "text-neon-green" : log.level === "warning" ? "text-yellow-300" : "text-bunker-muted"}`}>
                  [{log.timestamp ? new Date(toMs(log.timestamp)).toLocaleTimeString("tr-TR") : "—"}] {log.message}
                </p>
              ))}
              {!(job?.logs || []).length && <p className="font-mono text-xs text-bunker-muted">Log bekleniyor...</p>}
            </div>
            {complete && job?.result?.report_text && (
              <pre className="mt-3 max-h-[28vh] overflow-auto rounded border border-bunker-800 bg-black/20 p-3 font-mono text-[11px] text-bunker-muted whitespace-pre-wrap">{job.result.report_text}</pre>
            )}
            {complete && (
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] text-bunker-muted">Sinyal bazlı ölçüm (her satır bir sinyal: çıkış, net%, MFE/MAE).</p>
                  <button onClick={() => downloadCsv("report.csv", "birlesik-radar-replay.csv")} className="shrink-0 rounded-lg border border-neon-green/50 bg-neon-green/10 px-3 py-2 font-mono text-xs text-neon-green hover:bg-neon-green/20">SİNYAL CSV</button>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] text-bunker-muted">Geometri taraması (hedef × stop ızgarası → hangi ayar net pozitife dönüyor).</p>
                  <button onClick={() => downloadCsv("sweep.csv", "birlesik-radar-geometri-taramasi.csv")} className="shrink-0 rounded-lg border border-amber-300/50 bg-amber-300/10 px-3 py-2 font-mono text-xs text-amber-300 hover:bg-amber-300/20">TARAMA CSV</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MacdJumpSettingsPanel() {
  const [draft, setDraft] = useState<any>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/macd-monitor/settings`);
      if (res.ok) { const d = await res.json(); setDraft(d.settings || {}); setLoaded(true); }
    } catch { setError("Veri alınamadı"); }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true); setError(null); setSaved(false);
    try {
      const res = await apiRequest(`${API_BASE}/api/macd-monitor/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Kayıt hatası"); }
      const d = await res.json();
      setDraft(d.settings || {});
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) { setError(e instanceof Error ? e.message : "Bilinmeyen hata"); }
    finally { setSaving(false); }
  };

  const set = (key: string, value: any) => setDraft((prev: any) => ({ ...prev, [key]: value }));
  // Ayarlar yüklenene kadar kontroller kilitli: `draft` boşken select'ler
  // yanlışlıkla "Kapalı" gösteriyordu (varsayılan Açık) — A12.
  const pending = !loaded;

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow mb-2">MACD MONITOR · SIRÇRAMA ADAYI AYARLARI</p>
      <p className="text-xs text-bunker-muted mb-4">
        Sıçrama skoru eşiği ve alarm davranışı. Eşik; MACD MONITOR sayfasındaki SIRÇRAMA sütunu ile
        İzleme sayfasındaki "SIRÇRAMA ADAYLARI" listesini ve alarmları aynı anda yönetir.
      </p>
      {error && <p className="text-neon-red text-xs mb-3">{error}</p>}
      {saved && <p className="text-neon-green text-xs mb-3">✅ Kaydedildi</p>}
      {pending && !error && <p className="text-bunker-muted text-xs mb-3">Ayarlar yükleniyor…</p>}

      <div className={`grid gap-4 md:grid-cols-3 ${pending ? "opacity-60" : ""}`}>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Sıçrama Adayı Eşiği (0-100)</label>
          <input type="number" min="0" max="100" disabled={pending} value={draft.jump_min_score ?? 60} onChange={(e) => set("jump_min_score", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Eşik Alarmları</label>
          <select disabled={pending} value={draft.alerts_enabled ? "1" : "0"} onChange={(e) => set("alerts_enabled", e.target.value === "1")} className="input">
            <option value="1">Açık (WS + banner)</option>
            <option value="0">Kapalı</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Web Push Bildirimi</label>
          <select disabled={pending} value={draft.push_enabled ? "1" : "0"} onChange={(e) => set("push_enabled", e.target.value === "1")} className="input">
            <option value="1">Açık</option>
            <option value="0">Kapalı</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Erken Sinyal Alarmları</label>
          <select disabled={pending} value={draft.early_alerts_enabled ? "1" : "0"} onChange={(e) => set("early_alerts_enabled", e.target.value === "1")} className="input">
            <option value="1">Açık (varsayılan)</option>
            <option value="0">Kapalı</option>
          </select>
        </div>
      </div>
      <p className="mt-3 text-[11px] text-bunker-muted leading-relaxed">
        <b className="text-sky-300">Erken Sinyal (YAKLAŞIYOR):</b> kırılımdan önce haber verir — M5 zirveye yaklaşma (≤0.5 ATR + aktivite),
        M1 öncü kırılımı (M5 yeşilken) ve MACD hist dip dönüşü. "Web Push Bildirimi" kapalıyken hiç push
        gönderilmez; sayfa içi canlı banner (WS) yine çalışır. "Eşik Alarmları" kapalıysa hiçbir alarm üretilmez —
        skor ve listeler yine güncellenir.
      </p>

      <div className="flex gap-3 mt-6">
        <button onClick={save} disabled={saving || pending} className="px-5 py-2 rounded-lg border border-neon-green/50 text-neon-green font-mono text-xs hover:bg-neon-green/10 disabled:opacity-50">
          {saving ? "KAYDEDİLİYOR..." : "KAYDET"}
        </button>
      </div>
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
  // H-07: ayarlar yüklenene kadar form KİLİTLİ olmalı. `draft = {}` iken
  // `draft.enabled ? "1" : "0"` → "0" (Kapalı) ve `draft.min_score ?? 50` →
  // 50 görünüyordu; kullanıcı KAYDET'e basınca otonom trade KAPANIYOR ve
  // eşikler varsayılana dönüyordu. `MacdJumpSettingsPanel` ile aynı
  // `loaded`/`pending` deseni.
  const [loaded, setLoaded] = useState(false);

  const load = async () => {
    setError(null);
    try {
      const [sRes, stRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/auto-paper/settings`),
        apiRequest(`${API_BASE}/api/auto-paper/stats`),
      ]);
      if (sRes.ok) {
        const d = await sRes.json();
        setSettings(d.settings);
        setDraft(d.settings || {});
        setLoaded(true);
      } else {
        setError("Otonom paper ayarları alınamadı");
      }
      if (stRes.ok) { const d = await stRes.json(); setStats(d.stats); }
    } catch { setError("Veri alınamadı"); }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!loaded) return;
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
    if (!window.confirm("Portföy 10.000 TL'ye sıfırlanacak. Eski işlem kayıtları korunur ancak raporlara/hesaplamalara katılmaz. Devam etmek istiyor musunuz?")) return;
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
  // H-07: ayarlar gelmeden form değerleri varsayılana düşmesin.
  const pending = !loaded;

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow mb-4">OTONOM PAPER TRADE AYARLARI</p>
      {error && (
        <p className="mb-3 flex flex-wrap items-center gap-2 text-neon-red text-xs">
          {error}
          <button type="button" onClick={load} className="rounded border border-neon-red/40 px-2 py-0.5 font-mono hover:bg-neon-red/10">YENİDEN DENE</button>
        </p>
      )}
      {saved && <p className="text-neon-green text-xs mb-3">✅ Kaydedildi</p>}
      {pending && !error && <p className="text-bunker-muted text-xs mb-3">Ayarlar yükleniyor…</p>}
      {pending && error && (
        <p className="mb-3 rounded border border-neon-red/40 bg-neon-red/5 px-3 py-2 text-xs text-neon-red">
          Ayarlar yüklenemediği için form kilitli — kaydetmek otonom trade ayarlarını varsayılana döndürürdü.
        </p>
      )}

      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Toplam</p>
            <p className="text-lg font-mono text-white">{stats.total ?? "—"}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Açık</p>
            <p className="text-lg font-mono text-yellow-300">{stats.open ?? "—"}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kapanmış</p>
            <p className="text-lg font-mono text-white">{stats.closed ?? "—"}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Başarı</p>
            {/* H-11: hiç işlem kapanmamışken backend win_rate=0.0 döner →
                kırmızı "%0" "başarısız" izlenimi veriyordu. Ölçüm yoksa nötr. */}
            {(() => {
              const measured = stats.closed != null && Number(stats.closed) > 0 && stats.win_rate != null && Number.isFinite(Number(stats.win_rate));
              const tone = !measured ? "text-bunker-muted" : Number(stats.win_rate) >= 50 ? "text-neon-green" : "text-neon-red";
              return <p className={`text-lg font-mono ${tone}`}>{measured ? `%${stats.win_rate}` : "—"}</p>;
            })()}
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Net PnL</p>
            <p className={`text-lg font-mono ${stats.total_pnl_try == null ? "text-bunker-muted" : Number(stats.total_pnl_try) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{stats.total_pnl_try == null ? "—" : formatSignedTL(stats.total_pnl_try)}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kazanan</p>
            <p className="text-lg font-mono text-neon-green">{stats.winning ?? "—"}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Kaybeden</p>
            <p className="text-lg font-mono text-neon-red">{stats.losing ?? "—"}</p>
          </div>
          <div className="rounded border border-bunker-700 bg-bunker-900 p-3">
            <p className="eyebrow">Ort. PnL</p>
            {/* H-11: `avg_pnl_try` null iken `.toFixed(2)` TypeError atıp
                sayfayı error boundary'ye düşürüyordu. */}
            <p className={`text-lg font-mono ${stats.avg_pnl_try == null || !Number.isFinite(Number(stats.avg_pnl_try)) ? "text-bunker-muted" : Number(stats.avg_pnl_try) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
              {stats.avg_pnl_try == null || !Number.isFinite(Number(stats.avg_pnl_try)) ? "—" : formatSignedTL(stats.avg_pnl_try)}
            </p>
          </div>
        </div>
      )}

      <div className={`grid gap-4 md:grid-cols-2 ${pending ? "opacity-60" : ""}`}>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Aktif</label>
          <select disabled={pending} value={draft.enabled ? "1" : "0"} onChange={(e) => set("enabled", e.target.value === "1")} className="input">
            <option value="1">Açık</option>
            <option value="0">Kapalı</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Minimum Skor (0-100)</label>
          <input type="number" min="0" max="100" disabled={pending} value={draft.min_score ?? 50} onChange={(e) => set("min_score", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Bakiye Yüzdesi (%)</label>
          <input type="number" min="1" max="100" disabled={pending} value={draft.balance_pct ?? 35} onChange={(e) => set("balance_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Stop Loss (%)</label>
          <input type="number" min="0.1" max="20" step="0.1" disabled={pending} value={draft.stop_loss_pct ?? 3} onChange={(e) => set("stop_loss_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Varsayılan Hedef (%)</label>
          <input type="number" min="0.5" max="20" step="0.1" disabled={pending} value={draft.default_target_pct ?? 2} onChange={(e) => set("default_target_pct", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Minimum Emir (TRY)</label>
          <input type="number" min="10" disabled={pending} value={draft.min_order_try ?? 50} onChange={(e) => set("min_order_try", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Max Açık Pozisyon (1-30)</label>
          {/* D-11/Erkan (2026-09-18): global maksimum açık otonom pozisyon;
              eskiden 3 sabitti. Çalışma-anı DB ayarı — kaydettikten sonra
              anında geçerli (deploy yenilemesine gerek yok). */}
          <input type="number" min="1" max="30" disabled={pending} value={draft.max_open_positions ?? 8} onChange={(e) => set("max_open_positions", Number(e.target.value))} className="input" />
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Başabaş (Breakeven) Koruması</label>
          <select disabled={pending} value={draft.breakeven_enabled ? "1" : "0"} onChange={(e) => set("breakeven_enabled", e.target.value === "1")} className="input">
            <option value="0">Kapalı (Tavsiye Edilen - Erken Kâr Kapanışını Önler)</option>
            <option value="1">Açık</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-mono text-bunker-muted block mb-1">Breakeven Tetikleme (%)</label>
          <input type="number" min="0.5" max="10" step="0.1" disabled={pending || !draft.breakeven_enabled} value={draft.breakeven_trigger_pct ?? 1.5} onChange={(e) => set("breakeven_trigger_pct", Number(e.target.value))} className="input" />
        </div>
        <div className="md:col-span-2 border-t border-bunker-800 pt-3">
          <label className="text-xs font-mono text-neon-green block mb-2">TRAILING STOP MODÜLÜ</label>
          <p className="text-xs text-bunker-muted mb-3">Pozisyon %trigger kadar kâra geçince fiyatı %gap geriden takip eder; fiyat bu seviyeye düşerse pozisyon otomatik kapanır. Trailing devreye girdikten sonra take-profit uygulanmaz — çıkışı trailing stop yönetir. Varsayılan AÇIK.</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="text-xs font-mono text-bunker-muted block mb-1">Modül</label>
              <select disabled={pending} value={draft.trailing_enabled ? "1" : "0"} onChange={(e) => set("trailing_enabled", e.target.value === "1")} className="input">
                <option value="1">Açık</option>
                <option value="0">Kapalı</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-mono text-bunker-muted block mb-1">Kâr Tetikleme (%)</label>
              <input type="number" min="0.5" max="20" step="0.1" disabled={pending} value={draft.trailing_trigger_pct ?? 2} onChange={(e) => set("trailing_trigger_pct", Number(e.target.value))} className="input" />
            </div>
            <div>
              <label className="text-xs font-mono text-bunker-muted block mb-1">Takip Mesafesi (%)</label>
              <input type="number" min="0.1" max="0.6" step="0.05" disabled={pending} value={draft.trailing_gap_pct ?? 0.6} onChange={(e) => set("trailing_gap_pct", Number(e.target.value))} className="input" />
            </div>
          </div>
        </div>
        <div className="md:col-span-2 border-t border-bunker-800 pt-3">
          <label className="text-xs font-mono text-neon-green block mb-2">TRAILING/BREAKEVEN SONRASI YENİDEN AÇ</label>
          <p className="text-xs text-bunker-muted mb-3">Trailing veya breakeven ile kapanan pozisyonda; sembol İzleme sayfasının "Uygun Adaylar" listesinde kaldığı sürece aynı sembole yeniden işlem açılır. Adaylıktan düşerse yeniden açılmaz. Varsayılan AÇIK.</p>
          <div className="max-w-xs">
            <select disabled={pending} value={draft.reopen_after_protect_close ? "1" : "0"} onChange={(e) => set("reopen_after_protect_close", e.target.value === "1")} className="input">
              <option value="1">Açık</option>
              <option value="0">Kapalı</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex gap-3 mt-6">
        <button onClick={save} disabled={saving || pending} className="px-5 py-2 rounded-lg border border-neon-green/50 text-neon-green font-mono text-xs hover:bg-neon-green/10 disabled:opacity-50">
          {saving ? "KAYDEDİLİYOR..." : "KAYDET"}
        </button>
        <button onClick={resetData} disabled={resetting} className="px-5 py-2 rounded-lg border border-neon-red/50 text-neon-red font-mono text-xs hover:bg-neon-red/10 disabled:opacity-50">
          {resetting ? "SIFIRLANIYOR..." : "TÜM VERİYİ SIFIRLA"}
        </button>
      </div>
    </div>
  );
}
