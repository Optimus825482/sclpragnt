"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import MarkdownMessage from "../components/MarkdownMessage";
import SymbolLink from "../components/SymbolLink";
import { streamChat } from "../lib/streamChat";
import { useLiveMessages } from "../lib/liveSocket";
import Link from "next/link";
import { Badge, Button, Card } from "../components/ui";

type Message = { role: "user" | "assistant"; content: string };
type Skill = {
  id: number;
  name: string;
  instructions: string;
  enabled: boolean;
};
type ToolLog = {
  id: number;
  tool_name: string;
  timestamp: number;
  success: boolean;
  duration_ms?: number;
  result_summary?: string;
};
type AgentEvaluation = {
  id: number;
  evaluator_type: string;
  score?: number;
  passed: boolean;
  failure_category?: string;
};
type AgentTrace = {
  trace_id: string;
  intent?: string;
  status: string;
  started_at?: string;
};
type LivePriceWatch = {
  symbol: string;
  price?: number;
  startPrice?: number;
  changePct?: number;
  high?: number;
  low?: number;
  samples?: number;
  status: "connecting" | "live" | "completed" | "stopped" | "error";
};
type UpsideCandidate = {
  symbol: string;
  rank: number;
  score?: number;
  data_ready: boolean;
  trend_direction?: string;
  price?: number;
  returns_pct?: Record<string, number | null>;
  trend?: Record<string, number | string | null>;
  volume?: Record<string, number | null>;
  liquidity?: Record<string, number | null>;
  evidence?: string[];
  risks?: string[];
  data_gaps?: string[];
};
type UpsideScanResult = {
  candidates: UpsideCandidate[];
  generated_at?: number;
  horizon_minutes?: number;
  symbols_scanned?: number;
  skipped?: string[];
};
const indicatorNumber = (value: number | string | Record<string, unknown> | null | undefined, key?: string) => {
  const candidate = key && value && typeof value === "object" ? value[key] : value;
  return typeof candidate === "number" || typeof candidate === "string" ? candidate : "—";
};
type VelocityCandidate = {
  symbol: string;
  rank?: number;
  price: number;
  atr_pct: number;
  bb_width_pct?: number | null;
  rsi?: number | null;
  mfi?: number | null;
  mode?: string | null;
  exhausted?: string | null;
  ret3_pct: number;
  velocity_score: number;
  passes: boolean;
  calibrated_hit_pct?: number | null;
};
type VelocityScanResult = {
  generated_at?: number;
  symbols_scanned?: number;
  calibration?: { base_rate_pct?: number; conditional_hit_pct?: number; note?: string };
  candidates: VelocityCandidate[];
  watchlist?: VelocityCandidate[];
};
const TOOL_GROUPS = [
  [
    "Veri",
    [
      "get_strategy_config",
      "get_strategy_stats",
      "get_trades",
      "get_signals",
      "get_decision_logs",
      "query_database",
      "read_only_sql",
      "search_memory",
    ],
  ],
  [
    "Araştırma",
    [
      "run_backtest",
      "run_custom_backtest",
      "run_backtest_robustness",
      "get_backtest_history",
      "scan_market_snapshots",
      "detect_15m_upside_candidates",
      "deep_analyze_symbol",
      "get_data_quality",
      "get_microstructure_snapshot",
      "get_regime_snapshot",
      "calculate_trade_economics",
      "get_symbol_outcome_profile",
      "run_walk_forward",
      "run_execution_stress_test",
      "run_parameter_sensitivity",
      "run_holdout_test",
      "run_statistical_validation",
      "get_backtest_data_quality",
      "activate_coin",
      "place_paper_order",
      "open_llm_paper_trade",
    ],
  ],
  [
    "Canlı kontrol",
    [
      "create_market_alert",
      "update_market_alert",
      "remove_market_alert",
      "list_market_alerts",
      "get_llm_open_position",
      "update_llm_position_plan",
      "close_llm_position",
      "set_llm_symbol_guard",
      "remove_llm_symbol_guard",
      "list_llm_symbol_guards",
      "request_codex_research",
      "get_a2a_messages",
      "get_order_status",
      "cancel_paper_order",
      "modify_paper_order",
      "reconcile_portfolio",
      "deactivate_coin",
    ],
  ],
] as const;
const ALL_TOOLS = TOOL_GROUPS.flatMap(([, names]) => names);
const QUICK_PROMPTS = [
  "Aktif stratejileri net PnL ve riskleriyle özetle.",
  "Açık pozisyonları maliyet ve invalidasyon açısından incele.",
  "Son 24 saatteki en önemli sinyal değişimlerini göster.",
] as const;
const starter: Message[] = [
  {
    role: "assistant",
    content: "Hazır. Ne araştırmak istersin?",
  },
];
const CHAT_STORAGE_KEY = "scalperagent:chat:main:v1";
const CHAT_SESSION_KEY = "scalperagent:chat:session:v1";
const CONTEXT_WINDOW_TOKENS = 1_000_000;
const estimateTokens = (items: Message[]) =>
  Math.ceil(
    items.reduce(
      (total, item) => total + item.content.length + item.role.length + 12,
      0,
    ) / 4,
  );
const newSessionId = () =>
  `chat:main:${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

function VelocityPanel({ title, badge, tone, result }: {
  title: string;
  badge: string;
  tone: "green" | "blue";
  result: VelocityScanResult;
}) {
  const toneText = tone === "green" ? "text-neon-green" : "text-sky-300";
  const badgeCls = tone === "green"
    ? "border-neon-green/50 bg-neon-green/10 text-neon-green"
    : "border-sky-400/50 bg-sky-400/10 text-sky-300";
  const candidates = result.candidates || [];
  const watchlist = result.watchlist || [];
  return (
    <div className="chat-price-watch !block" role="status" aria-live="polite">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <p className="eyebrow">{title} · İLK 3</p>
          <p className="text-xs text-bunker-muted mt-1">{result.symbols_scanned || 0} sembol tarandı · ATR≥%0.3 + BB≥%2.5 + RSI 35-80 + MFI 10-90</p>
        </div>
        <span className="text-[10px] text-bunker-muted shrink-0">{result.generated_at ? new Date(result.generated_at * 1000).toLocaleTimeString("tr-TR") : "—"}</span>
      </div>
      {candidates.length === 0 ? (
        <p className="text-xs text-yellow-300">Şu an koşulları geçen sembol yok; yüksek salınım rejimi bekleniyor (aşırı alım/satım semboller elenir).</p>
      ) : (
        <div className="velocity-table">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-bunker-muted">
                <th className="text-left py-1 pr-2 font-normal">#</th>
                <th className="text-left py-1 pr-2 font-normal">Sembol</th>
                <th className="text-right py-1 px-2 font-normal">Fiyat</th>
                <th className="text-right py-1 px-2 font-normal">ATR%</th>
                <th className="text-right py-1 px-2 font-normal">BB%</th>
                <th className="text-right py-1 px-2 font-normal">RSI</th>
                <th className="text-right py-1 px-2 font-normal">MFI</th>
                <th className="text-center py-1 px-2 font-normal">Mod</th>
                <th className="text-right py-1 pl-2 font-normal">Skor</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.symbol} className="border-t border-bunker-800">
                  <td className="py-1.5 pr-2 font-mono text-bunker-muted">{c.rank ?? "—"}</td>
                  <td className="py-1.5 pr-2 font-bold"><SymbolLink symbol={c.symbol} timeframe="1m" newTab className={`hover:text-white ${toneText}`} /></td>
                  <td className="py-1.5 px-2 text-right font-mono text-white">{c.price.toLocaleString("tr-TR", { maximumFractionDigits: 8 })}</td>
                  <td className="py-1.5 px-2 text-right font-mono">{c.atr_pct}</td>
                  <td className="py-1.5 px-2 text-right font-mono">{c.bb_width_pct}</td>
                  <td className={`py-1.5 px-2 text-right font-mono ${(c.rsi ?? 50) >= 70 ? "text-yellow-300" : ""}`}>{c.rsi}</td>
                  <td className={`py-1.5 px-2 text-right font-mono ${(c.mfi ?? 50) >= 80 ? "text-yellow-300" : ""}`}>{c.mfi}</td>
                  <td className="py-1.5 px-2 text-center"><span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${c.mode === "v_donusu" ? "border border-purple-400/50 text-purple-300" : "border border-neon-green/40 text-neon-green"}`}>{c.mode === "v_donusu" ? "V-DÖN" : "TREND"}</span></td>
                  <td className={`py-1.5 pl-2 text-right font-mono font-bold ${toneText}`}>{c.velocity_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {watchlist.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 items-center">
          <span className="text-[10px] text-bunker-muted">İZLEME:</span>
          {watchlist.map((w) => (
            <span key={w.symbol} className="rounded border border-bunker-700 px-1.5 py-0.5 font-mono text-[10px] text-bunker-muted">
              <SymbolLink symbol={w.symbol} timeframe="1m" newTab className="text-bunker-muted hover:text-white" /> {w.velocity_score}
            </span>
          ))}
        </div>
      )}
      <p className="text-[10px] text-yellow-300 mt-2">{result.calibration?.note || "Tahmin/garanti değildir; kapanmış mumlar, paper-only."}</p>
      <span className={`hidden ${badgeCls}`}>{badge}</span>
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(starter);
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [activeTools, setActiveTools] = useState<string[]>(ALL_TOOLS);
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [logs, setLogs] = useState<ToolLog[]>([]);
  const [evaluations, setEvaluations] = useState<AgentEvaluation[]>([]);
  const [instincts, setInstincts] = useState<any[]>([]);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [sessionId, setSessionId] = useState("chat:main");
  const [livePriceWatch, setLivePriceWatch] = useState<LivePriceWatch | null>(null);
  const [upsideResults, setUpsideResults] = useState<Record<5 | 15, UpsideScanResult>>({ 5: { candidates: [] }, 15: { candidates: [] } });
  const [upsidePanelTab, setUpsidePanelTab] = useState<5 | 15>(15);
  const [upsideScanBusy, setUpsideScanBusy] = useState(false);
  const [velocityResult, setVelocityResult] = useState<VelocityScanResult | null>(null);
  const [velocityBusy, setVelocityBusy] = useState(false);
  const [velocity15Result, setVelocity15Result] = useState<VelocityScanResult | null>(null);
  const [velocity15Busy, setVelocity15Busy] = useState(false);
  const [upsideScoutBusy, setUpsideScoutBusy] = useState(false);
  // Model akışı: arka plan etkinliklerinin canlı logu (en yeni üstte)
  const [activities, setActivities] = useState<{ key: string; kind: string; text: string; time: string; success?: boolean; duration_ms?: number }[]>([]);
  const activityEndRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsUrlsRef = useRef<string[]>([]);
  const ttsSessionRef = useRef(0);
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);
  const [ttsRate, setTtsRate] = useState(0);
  const [ttsPitch, setTtsPitch] = useState(0);
  const chatSettingsReady = useRef(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(CHAT_STORAGE_KEY) || "null",
      );
      const savedSession =
        localStorage.getItem(CHAT_SESSION_KEY) || newSessionId();
      if (Array.isArray(saved) && saved.length)
        setMessages(
          saved.filter(
            (item): item is Message =>
              item?.role && typeof item.content === "string",
          ),
        );
      localStorage.setItem(CHAT_SESSION_KEY, savedSession);
      setSessionId(savedSession);
    } catch {
      /* local storage is optional; backend memory remains authoritative */
    }
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (hydrated)
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
  }, [messages, hydrated]);
  useEffect(() => () => {
    ttsAudioRef.current?.pause();
    ttsUrlsRef.current.forEach(URL.revokeObjectURL);
  }, []);

  const stopSpeaking = () => {
    ttsSessionRef.current += 1;
    ttsAudioRef.current?.pause();
    ttsUrlsRef.current.forEach(URL.revokeObjectURL);
    ttsUrlsRef.current = [];
    setSpeakingIndex(null);
  };
  const speak = async (content: string, index: number) => {
    stopSpeaking();
    const session = ttsSessionRef.current;
    const clean = content.replace(/```[\s\S]*?```/g, " ").replace(/`([^`]*)`/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[#>*_~|]/g, " ")
      .replace(/\p{Extended_Pictographic}/gu, " ").replace(/[.!?…]+/g, ",").replace(/\s+/g, " ").trim();
    const chunks = clean.match(/.{1,360}(?:\s|$)/g)?.map((part) => part.trim()).filter(Boolean) || [];
    if (!chunks.length) return;
    setSpeakingIndex(index);
    try {
      const requests = chunks.map(async (text) => {
        const response = await apiRequest(`${API_BASE}/api/tts/edge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, rate: ttsRate, pitch: ttsPitch }) });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `Ses servisi HTTP ${response.status}`);
        }
        return URL.createObjectURL(await response.blob());
      });
      const play = async (chunkIndex: number) => {
        if (session !== ttsSessionRef.current) return;
        const url = await requests[chunkIndex]; ttsUrlsRef.current.push(url);
        if (session !== ttsSessionRef.current) { URL.revokeObjectURL(url); return; }
        const audio = new Audio(url); ttsAudioRef.current = audio;
        audio.onended = () => { URL.revokeObjectURL(url); if (session !== ttsSessionRef.current) return; if (chunkIndex + 1 < requests.length) void play(chunkIndex + 1); else setSpeakingIndex(null); };
        audio.onerror = () => { if (session === ttsSessionRef.current) { stopSpeaking(); setError("Tarayıcı ses parçasını oynatamadı."); } };
        await audio.play();
      };
      await play(0);
    } catch (cause) { if (session === ttsSessionRef.current) { stopSpeaking(); setError(cause instanceof Error ? cause.message : "Sesli yanıt üretilemedi."); } }
  };
  useEffect(() => {
    Promise.all([
      apiRequest(`${API_BASE}/api/llm/config`).then((r) => r.json()),
      apiRequest(`${API_BASE}/api/llm/chat-settings`).then((r) => r.json()),
    ])
      .then(([data, settings]) => {
        setSkills(data.skills || []);
        if (Array.isArray(settings.active_tools))
          setActiveTools(Array.from(new Set([...ALL_TOOLS, ...settings.active_tools])));
        if (Array.isArray(settings.active_skills))
          setActiveSkills(settings.active_skills);
        if (Number.isFinite(settings.tts_rate)) setTtsRate(settings.tts_rate);
        if (Number.isFinite(settings.tts_pitch)) setTtsPitch(settings.tts_pitch);
        chatSettingsReady.current = true;
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!chatSettingsReady.current) return;
    const timer = window.setTimeout(() => {
      apiRequest(`${API_BASE}/api/llm/chat-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_tools: activeTools,
          active_skills: activeSkills,
          tts_rate: ttsRate,
          tts_pitch: ttsPitch,
        }),
      }).catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeTools, activeSkills, ttsRate, ttsPitch]);
  useEffect(() => {
    const load = () =>
      apiRequest(`${API_BASE}/api/llm/tool-logs?limit=24`)
        .then((r) => r.json())
        .then((data) => setLogs(data.logs || []))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const load = () =>
      Promise.all([
        apiRequest(`${API_BASE}/api/llm/evaluations?limit=8`).then((r) => r.json()),
        apiRequest(`${API_BASE}/api/llm/instincts?status=active&limit=6`).then((r) =>
          r.json(),
        ),
        apiRequest(`${API_BASE}/api/llm/agent-traces?limit=8`).then((r) => r.json()),
      ])
        .then(([evaluationData, instinctData, traceData]) => {
          setEvaluations(evaluationData.evaluations || []);
          setInstincts(instinctData.instincts || []);
          setTraces(traceData.traces || []);
        })
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (
        event.key !== "Enter" ||
        event.shiftKey ||
        (event.target as HTMLElement)?.tagName !== "TEXTAREA"
      )
        return;
      event.preventDefault();
      if (!busy && input.trim())
        (event.target as HTMLTextAreaElement).form?.requestSubmit();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [busy, input]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // Arka plan model etkinliklerini canlı akışa ekle (en yeni üstte)
  useLiveMessages((msg: any) => {
    if (msg.type !== "model_activity") return;
    const d = msg.data || {};
    const text: string = typeof d.summary === "string" && d.summary
      ? d.summary
      : `${d.kind || "işlem"}: ${d.tool || ""}`;
    setActivities((current) => [{
      key: `${d.at || Date.now() / 1000}-${d.tool || d.kind}-${Math.random().toString(36).slice(2, 7)}`,
      kind: String(d.kind || "info"),
      text,
      time: new Date((d.at || Date.now() / 1000) * 1000).toLocaleTimeString("tr-TR"),
      success: d.success,
      duration_ms: d.duration_ms,
    }, ...current].slice(0, 40));
  });
  const enabledSkills = useMemo(
    () => skills.filter((s) => s.enabled),
    [skills],
  );
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError("");
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      setMessages([...next, { role: "assistant", content: "" }]);
      await streamChat(
        `${API_BASE}/api/strategies/llm/chat`,
        next,
        (delta) =>
          setMessages((current) => [
            ...current.slice(0, -1),
            {
              role: "assistant",
              content: (current[current.length - 1]?.content || "") + delta,
            },
          ]),
        {
          active_tools: activeTools,
          active_skills: activeSkills,
          session_id: sessionId,
        },
        {
          signal: controller.signal,
          onEvent: ({ event, data }) => {
            if (event === "watch_started") {
              setLivePriceWatch({ symbol: String(data.symbol || ""), status: "connecting" });
            } else if (event === "price") {
              setLivePriceWatch({
                symbol: String(data.symbol || ""),
                price: Number(data.price),
                startPrice: Number(data.start_price),
                changePct: Number(data.change_pct),
                high: Number(data.high),
                low: Number(data.low),
                samples: Number(data.samples),
                status: "live",
              });
            } else if (event === "done" && data.watch_completed) {
              setLivePriceWatch((current) => current ? { ...current, status: "completed" } : current);
            }
          },
        },
      );
    } catch (e) {
      if (controller.signal.aborted) {
        setLivePriceWatch((current) => current ? { ...current, status: "stopped" } : current);
        return;
      }
      const message =
        e instanceof Error ? e.message : "LLM bağlantısı kurulamadı.";
      setError(message);
      setMessages([...next, { role: "assistant", content: message }]);
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
      setBusy(false);
    }
  };
  const detectUpsideCandidates = async (horizon: 5 | 15) => {
    if (upsideScanBusy) return;
    setUpsideScanBusy(true);
    setError("");
    try {
      const endpoint = horizon === 5 ? "upside-candidates-5m" : "upside-candidates";
      const response = await apiRequest(`${API_BASE}/api/market-snapshot/${endpoint}?limit=3`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "15 dakikalık tarama başarısız");
      const result: UpsideScanResult = { generated_at: data.generated_at, horizon_minutes: data.horizon_minutes, symbols_scanned: data.symbols_scanned, skipped: data.symbols_skipped_open || [], candidates: (Array.isArray(data.candidates) ? data.candidates : []).slice(0, 3) };
      setUpsideResults((current) => ({ ...current, [horizon]: result }));
      setUpsidePanelTab(horizon);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "15 dakikalık tarama başarısız");
    } finally {
      setUpsideScanBusy(false);
    }
  };
  const detectVelocityCandidates = async () => {
    if (velocityBusy) return;
    setVelocityBusy(true);
    setError("");
    try {
      const response = await apiRequest(`${API_BASE}/api/market-snapshot/velocity-5m`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Hız taraması başarısız");
      setVelocityResult(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Hız taraması başarısız");
    } finally {
      setVelocityBusy(false);
    }
  };
  const detectVelocity15 = async () => {
    if (velocity15Busy) return;
    setVelocity15Busy(true);
    setError("");
    try {
      const response = await apiRequest(`${API_BASE}/api/market-snapshot/velocity-15m`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Hız taraması başarısız");
      setVelocity15Result(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Hız taraması başarısız");
    } finally {
      setVelocity15Busy(false);
    }
  };
  const runUpsideScout = async () => {
    if (upsideScoutBusy || busy) return;
    setUpsideScoutBusy(true);
    setError("");
    try {
      const response = await apiRequest(`${API_BASE}/api/llm/upside-scout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      // 5xx yanıtlar JSON değil düz metin olabilir; okunabilir hataya çevir.
      let data: any;
      try {
        data = await response.json();
      } catch {
        const text = await response.text().catch(() => "");
        throw new Error(text.slice(0, 200) || `Sunucu hatası (HTTP ${response.status})`);
      }
      if (!response.ok || data.enabled === false) {
        throw new Error(data.detail || data.error || "Yükseliş keşfi başarısız");
      }
      const syms = Array.isArray(data.symbols) && data.symbols.length
        ? data.symbols.join(", ")
        : data.symbol;
      setMessages((current) => [
        ...current,
        {
          role: "user" as const,
          content: `🎯 EN HIZLI YÜKSELİŞ KEŞFİ: ${syms}`,
        },
        { role: "assistant" as const, content: data.analysis || "Analiz üretilemedi." },
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Yükseliş keşfi başarısız");
    } finally {
      setUpsideScoutBusy(false);
    }
  };
  const stopLiveWatch = () => {
    streamAbortRef.current?.abort();
    setLivePriceWatch((current) => current ? { ...current, status: "stopped" } : current);
  };
  const stopResponse = () => {
    streamAbortRef.current?.abort();
    setLivePriceWatch((current) => current ? { ...current, status: "stopped" } : current);
  };
  const toggle = (
    value: string,
    setter: (values: string[]) => void,
    current: string[],
  ) =>
    setter(
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  const saveChatSettings = async () => {
    await apiRequest(`${API_BASE}/api/llm/chat-settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_tools: activeTools,
        active_skills: activeSkills,
      }),
    });
  };
  const startNewChat = () => {
    const nextSession = newSessionId();
    setMessages(starter);
    setInput("");
    setError("");
    setSessionId(nextSession);
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(starter));
    localStorage.setItem(CHAT_SESSION_KEY, nextSession);
  };
  const contextTokens = estimateTokens(messages);
  const contextRatio = contextTokens / CONTEXT_WINDOW_TOKENS;
  const contextTone =
    contextRatio >= 0.95
      ? "critical"
      : contextRatio >= 0.8
        ? "warning"
        : "normal";
  return (
    <div className="chat-page">
      <div className="chat-heading">
        <div>
          <p className="eyebrow">LLM · PAPER RESEARCH</p>
          <h1 className="font-mono text-2xl font-bold">
            CHAT <span className="text-neon-green">MERKEZİ</span>
          </h1>
          <p className="mt-2 text-sm text-bunker-muted">
            Sistem promptu, Soul persona ve seçtiğin yeteneklerle
            yapılandırılmış sohbet.
          </p>
        </div>
        <Badge tone="positive">{busy ? "YANIT ÜRETİLİYOR" : "HAZIR"}</Badge>
      </div>
      <div className="chat-layout">
        <Card className="chat-conversation">
          <div className="chat-conversation-actions">
            <span className={`chat-context-meter ${contextTone}`}>
              {Math.min(100, contextRatio * 100).toFixed(2)}% context
            </span>
            <Button variant="secondary" onClick={startNewChat}>
              ＋ YENİ SOHBET
            </Button>
          </div>
          <div className="chat-scan-buttons" role="toolbar" aria-label="Hız avcısı taramaları">
            <Button variant="primary" onClick={detectVelocityCandidates} disabled={velocityBusy}>
              {velocityBusy ? "HIZ AVLANIYOR…" : "🚀 5 DK %2 HIZ AVCISI"}
            </Button>
            <Button variant="primary" onClick={detectVelocity15} disabled={velocity15Busy}>
              {velocity15Busy ? "HIZ AVLANIYOR…" : "🚀 15 DK %3 HIZ AVCISI"}
            </Button>
            <Button variant="secondary" className="chat-scan-button-wide" onClick={runUpsideScout} disabled={upsideScoutBusy || busy}>
              {upsideScoutBusy ? "LLM ANALİZ EDİYOR…" : "🎯 EN HIZLI YÜKSELİŞ: LLM ANALİZİ"}
            </Button>
          </div>
          {velocityResult && (
            <VelocityPanel
              title="5 DK İÇİNDE %2+ HIZ POTANSİYELİ"
              badge="%2 POTANSİYEL"
              tone="green"
              result={velocityResult}
            />
          )}
          {velocity15Result && (
            <VelocityPanel
              title="15 DK İÇİNDE %3+ HIZ POTANSİYELİ"
              badge="%3 POTANSİYEL"
              tone="blue"
              result={velocity15Result}
            />
          )}
          {(upsideResults[5].candidates.length > 0 || upsideResults[15].candidates.length > 0) && (
            <div className="chat-price-watch" role="status" aria-live="polite">
              <div className="section-tabs mb-3" aria-label="Yükseliş tahmin sekmeleri">
                <button className={upsidePanelTab === 5 ? "active" : ""} onClick={() => setUpsidePanelTab(5)}>5 DK ADAYLARI</button>
                <button className={upsidePanelTab === 15 ? "active" : ""} onClick={() => setUpsidePanelTab(15)}>15 DK ADAYLARI</button>
              </div>
              {(() => {
                const result = upsideResults[upsidePanelTab];
                const candidates = result.candidates.slice(0, 3);
                return <>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div>
                      <p className="eyebrow">{upsidePanelTab} DK YUKARI MOMENTUM · İLK 3</p>
                      <p className="text-xs text-bunker-muted">{result.symbols_scanned || 0} aktif sembol · veritabanına kaydedildi</p>
                    </div>
                    <span className="text-[10px] text-bunker-muted">{result.generated_at ? new Date(result.generated_at * 1000).toLocaleTimeString("tr-TR") : "—"}</span>
                  </div>
                  <div className="space-y-2">
                    {candidates.length === 0 ? <p className="text-xs text-bunker-muted">Bu ufuk için henüz tarama yapılmadı.</p> : candidates.map((candidate) => {
                      const tier = (candidate as any).pattern_evaluation?.confidence_tier
                      const matches = (candidate as any).pattern_evaluation?.matches || []
                      return (
                  <div key={candidate.symbol} className="flex flex-wrap items-center justify-between gap-2 border-b border-bunker-800 pb-2 last:border-0 last:pb-0">
                    <div>
                      <strong className="font-mono text-sm text-white">{candidate.rank}. <SymbolLink symbol={candidate.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green" /></strong>
                      {tier === "high" && <span title={`Desen eşleşmeleri: ${matches.join(", ")}`} className="ml-2 rounded border border-neon-green/50 bg-neon-green/10 px-1.5 py-0.5 font-mono text-[10px] text-neon-green">YÜKSEK GÜVEN</span>}
                      {tier === "watch" && <span title={`Desen eşleşmeleri: ${matches.join(", ")}`} className="ml-2 rounded border border-yellow-400/40 px-1.5 py-0.5 font-mono text-[10px] text-yellow-300">İZLEME</span>}
                      <span className="ml-2 text-xs text-neon-green">{candidate.trend_direction || "unknown"}</span>
                      <p className="text-[11px] text-bunker-muted">5m %{candidate.returns_pct?.return_5m ?? "—"} · 15m %{candidate.returns_pct?.return_15m ?? "—"} · ADX {indicatorNumber(candidate.trend?.adx, "adx") !== "—" ? indicatorNumber(candidate.trend?.adx, "adx") : indicatorNumber(candidate.trend?.adx_14)} · hacim {candidate.volume?.volume_ratio_20 ?? "—"}x</p>
                      {matches.length > 0 && <p className="text-[10px] text-sky-300">desen: {matches.join(" + ")}</p>}
                    </div>
                    <span className="font-mono text-xs text-sky-300">Skor {candidate.score ?? "—"}</span>
                  </div>
                      );
                    })}
                  </div>
                </>;
              })()}
              <p className="text-[10px] text-yellow-300 mt-2">Liste tahmin/garanti değildir; eksik veya stale veriler güveni düşürür. Paper-only.</p>
            </div>
          )}
          {contextTone !== "normal" && (
            <div className={`chat-context-alert ${contextTone}`} role="status">
              {contextTone === "critical"
                ? "Context penceresi dolmaya çok yakın. Yeni sohbet başlatın veya sohbeti özetleyin."
                : "Sohbet context penceresinin %80'ini geçti. Yeni sohbet başlatmayı planlayın."}
              <span>
                Yaklaşık {contextTokens.toLocaleString("tr-TR")} /{" "}
                {CONTEXT_WINDOW_TOKENS.toLocaleString("tr-TR")} token
              </span>
            </div>
          )}
          <div className="chat-messages">
            {messages.map((message, index) => (
              <div key={index} className={`chat-message ${message.role}`}>
                <div className="chat-avatar" aria-hidden="true">
                  {message.role === "user" ? "SİZ" : "AI"}
                </div>
                <div className="chat-bubble">
                  {message.role === "assistant" && message.content && <button type="button" onClick={() => speakingIndex === index ? stopSpeaking() : void speak(message.content, index)} className="chat-tts-button" aria-label="Yanıtı seslendir">{speakingIndex === index ? "■" : "▶"}</button>}
                  <MarkdownMessage content={message.content} />
                </div>
              </div>
            ))}
            {busy && (
              <div className="chat-thinking">
                <span className="status-dot" /> Araçlar ve model yanıtı
                hazırlanıyor…
              </div>
            )}
            {livePriceWatch && (
              <div className="chat-price-watch" role="status" aria-live="polite">
                <div>
                  <p className="eyebrow">CANLI FİYAT · {livePriceWatch.symbol}</p>
                  <strong>{Number.isFinite(livePriceWatch.price) ? livePriceWatch.price?.toLocaleString("tr-TR", { maximumFractionDigits: 8 }) : "Bağlanıyor…"}</strong>
                  <span className={(livePriceWatch.changePct || 0) >= 0 ? "text-neon-green" : "text-neon-red"}>
                    {Number.isFinite(livePriceWatch.changePct) ? `%${(livePriceWatch.changePct || 0) >= 0 ? "+" : ""}${livePriceWatch.changePct?.toFixed(3)}` : ""}
                  </span>
                </div>
                <div className="chat-price-watch-range">
                  <span>Düşük {livePriceWatch.low ?? "—"}</span>
                  <span>Yüksek {livePriceWatch.high ?? "—"}</span>
                  <span>Örnek {livePriceWatch.samples ?? 0}</span>
                </div>
                {busy && livePriceWatch.status !== "completed" && (
                  <Button variant="secondary" onClick={stopLiveWatch}>İZLEMEYİ DURDUR</Button>
                )}
              </div>
            )}
            <div ref={endRef} />
          </div>
          <div className="chat-quick-prompts" aria-label="Hızlı soru önerileri">
            {QUICK_PROMPTS.map((prompt) => <button key={prompt} type="button" onClick={() => setInput(prompt)} disabled={busy}>{prompt}</button>)}
          </div>
          <form onSubmit={send} className="chat-composer">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Bir soru sor… örn. Komisyon sonrası en iyi strateji hangisi?"
              rows={2}
              disabled={busy}
            />
            <Button
              variant="primary"
              type="submit"
              disabled={busy || !input.trim()}
            >
              GÖNDER ↗
            </Button>
            {busy && <Button variant="secondary" type="button" onClick={stopResponse}>DURDUR</Button>}
          </form>
          {error && <p className="mt-3 text-xs text-neon-red">{error}</p>}
        </Card>
        <Card className={`chat-controls ${controlsOpen ? "is-open" : ""}`}>
          <div className="chat-controls-header">
            <div>
              <p className="eyebrow">ARKA PLAN İŞLERİ</p>
              <h2 className="font-mono text-sm font-bold text-white">MODEL AKIŞI</h2>
            </div>
            <Link href="/settings?tab=chat" className="ui-button ui-button-secondary" style={{ textDecoration: "none" }}>
              ⚙ CHAT AYARLARI
            </Link>
          </div>
          <div className="chat-log-panel">
            <div className="flex items-center justify-between mb-2">
              <p className="eyebrow">CANLI ETKİNLİK AKIŞI</p>
              <span className="status-dot" />
            </div>
            <div className="model-activity-stream" aria-live="polite">
              {activities.length === 0 && (
                <p className="text-xs text-bunker-muted">$ Model boşta; bir şey sorduğunda araç çağrıları ve hesaplamalar buraya akmaya başlar…</p>
              )}
              {activities.map((a) => (
                <div key={a.key} className={`model-activity-row ${a.kind === "tool" ? (a.success ? "ok" : "err") : a.kind}`}>
                  <span className="text-bunker-muted text-[10px] font-mono shrink-0">{a.time}</span>
                  <span className="min-w-0 flex-1">{a.text}</span>
                  {a.kind === "tool" && a.duration_ms != null && (
                    <span className={a.success ? "text-neon-green text-[10px] shrink-0" : "text-neon-red text-[10px] shrink-0"}>{Math.round(a.duration_ms)}ms</span>
                  )}
                </div>
              ))}
              <div ref={activityEndRef} />
            </div>
          </div>
          <div className="chat-log-panel">
            <p className="eyebrow mb-2">ÖZET</p>
            <div className="chat-trace-grid grid grid-cols-3 gap-2 text-[10px] font-mono">
              <span className="rounded border border-bunker-700 p-2">
                Trace: {traces.length}
              </span>
              <span className="rounded border border-bunker-700 p-2">
                Eval: {evaluations.filter((item) => item.passed).length}/
                {evaluations.length || 0}
              </span>
              <span className="rounded border border-bunker-700 p-2">
                Kural: {instincts.length}
              </span>
            </div>
          </div>
        </Card>
      </div>
      <footer className="chat-footer">
        <span>SCALPERAGENT · CHAT</span>
        <span className="chat-footer-status">
          <span className="status-dot" /> PAPER ONLY · PUBLIC DATA
        </span>
      </footer>
    </div>
  );
}
