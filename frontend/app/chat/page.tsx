"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { toMs } from "../lib/format";
import MarkdownMessage from "../components/MarkdownMessage";
import SymbolLink from "../components/SymbolLink";
import { streamChat } from "../lib/streamChat";
import { useLiveMessages } from "../lib/liveSocket";
import Link from "next/link";
import { Badge, Button, Card } from "../components/ui";
import { useAuth } from "../lib/auth";

type ScoutCandidate = {
  symbol: string;
  current_price: number;
  horizon_minutes: number;
  best_profile_minutes?: number;
  profiles?: Record<
    string,
    {
      horizon_minutes: number;
      target_pct: number;
      target_price: number | null;
      velocity_score?: number | null;
      upside_rank?: number | null;
      passes?: boolean;
      mode?: string | null;
      available?: boolean;
    }
  >;
  target_pct: number;
  target_price: number | null;
  ml_target_pct?: number | null;
  ml_hit_probability?: number | null;
  upside_rank: number;
  velocity_score: number;
};

type ScoutResult = {
  symbols: string[];
  candidates: ScoutCandidate[];
  generated_at?: number;
  journal_saved?: number;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  scout?: ScoutResult;
  time?: string;
};

type Skill = { id: string; name: string; description: string; enabled: boolean };
type ToolLog = { id: number; tool: string; duration_ms: number; success: boolean; created_at: number };
type AgentEvaluation = { trace_id: string; passed: boolean; score: number; checks: Record<string, boolean>; created_at: number };
type AgentTrace = { trace_id: string; session_id: string; intent: string; status: string; created_at: number };
type LivePriceWatch = {
  symbol: string;
  price?: number;
  startPrice?: number;
  changePct?: number;
  high?: number;
  low?: number;
  samples?: number;
  status: "connecting" | "live" | "completed" | "stopped";
};

const TOOL_GROUPS: readonly [string, readonly string[]][] = [
  [
    "Piyasa Araştırması",
    [
      "scan_market_snapshots",
      "detect_15m_upside_candidates",
      "detect_5m_upside_candidates",
      "deep_analyze_symbol",
      "get_data_quality",
      "get_microstructure_snapshot",
      "get_regime_snapshot",
      "calculate_trade_economics",
      "get_symbol_outcome_profile",
      "get_realtime_flow",
      "get_symbol_behavior",
      "get_subminute_microstructure",
      "get_historical_slippage",
      "validate_trade_plan",
      "run_pattern_universe_research",
      "get_pattern_research_runs",
      "save_research_pattern",
      "list_research_patterns",
      "list_indicator_research_catalog",
      "activate_coin",
      "place_paper_order",
      "open_llm_paper_trade",
    ],
  ],
  [
    "Sistem & Hesap",
    [
      "get_auto_paper_status",
      "get_dashboard_summary",
      "get_monitoring_status",
      "get_real_account",
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
  {
    icon: "📈",
    label: "Piyasa Özeti & Trendler",
    prompt: "Binance TR piyasasındaki güncel görünümü, güçlü yükseliş trendinde olan sembolleri ve genel piyasa yapısını bir trader gözüyle özetle.",
  },
  {
    icon: "⚡",
    label: "Hacim & Momentum Liderleri",
    prompt: "Şu anda en belirgin hacim artışı ve momentum gösteren TRY işlem çiftleri hangileri? Destek/direnç seviyeleriyle açıkla.",
  },
  {
    icon: "🎯",
    label: "Kritik Destek & Dirençler",
    prompt: "BTC/TRY ve piyasayı sürükleyen coinlerdeki kritik destek, direnç ve olası kırılım seviyeleri nerelerde?",
  },
  {
    icon: "🛡️",
    label: "Risk & İptal Seviyeleri",
    prompt: "Potansiyel işlem senaryolarını risk/kazanç (R:R) ve geçersizlik (invalidation) seviyeleri açısından değerlendir.",
  },
  {
    icon: "📊",
    label: "Strateji İstatistikleri",
    prompt: "Aktif bot stratejilerinin net PnL, başarı oranı ve genel performans durumunu özetle.",
  },
] as const;

const starter: Message[] = [
  {
    role: "assistant",
    content: "Hazır. Binance TR piyasası, trend yönü, kritik seviyeler veya strateji analizi hakkında ne araştırmak istersin?",
    time: "Şimdi",
  },
];

const CHAT_STORAGE_KEY = "scalperagent:chat:main:v1";
const CHAT_SESSION_KEY = "scalperagent:chat:session:v1";
const CONTEXT_WINDOW_TOKENS = 1_000_000;

const estimateTokens = (items: Message[]) =>
  Math.ceil(
    items.reduce(
      (total, item) => total + (item.content?.length || 0) + item.role.length + 12,
      0,
    ) / 4,
  );

const newSessionId = () =>
  `chat:main:${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

const fmtScoutPrice = (value: number | null | undefined) =>
  Number.isFinite(Number(value)) && value !== null && value !== undefined
    ? Number(value) >= 100
      ? Number(value).toFixed(2)
      : Number(value) >= 1
        ? Number(value).toFixed(4)
        : Number(value).toFixed(6)
    : "—";

function UpsideScoutCard({ scout }: { scout: ScoutResult }) {
  const candidates = scout.candidates || [];
  if (!candidates.length && !scout.symbols.length) return null;
  return (
    <div className="card mb-3 border-emerald-500/30 bg-emerald-950/20 p-3 text-xs font-mono">
      <div className="flex items-center justify-between gap-2 border-b border-bunker-700/60 pb-2">
        <span className="font-bold text-neon-green flex items-center gap-1.5">
          <span>🎯</span>
          <span>EN HIZLI YÜKSELİŞ TESPİTLERİ (5DK + 15DK HARMAN)</span>
        </span>
        {scout.generated_at && (
          <span className="text-[10px] text-bunker-muted">
            {new Date(toMs(scout.generated_at)).toLocaleTimeString("tr-TR")}
          </span>
        )}
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {candidates.map((candidate) => {
          const m5 = candidate.profiles?.["5m"];
          const m15 = candidate.profiles?.["15m"];
          return (
            <div
              key={candidate.symbol}
              className="rounded border border-bunker-700/80 bg-bunker-900/60 p-2 text-[11px]"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-white">
                  <SymbolLink symbol={candidate.symbol} />
                </span>
                <span className="rounded bg-neon-green/10 px-1.5 py-0.5 text-neon-green font-bold">
                  {Number(candidate.upside_rank || 0).toFixed(1)} puan
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between text-bunker-muted">
                <span>Anlık: ₺{fmtScoutPrice(candidate.current_price)}</span>
                <span>Hedef: +%{Number(candidate.target_pct || 0).toFixed(2)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[10px] text-bunker-muted">
                <span>5dk: {m5 ? `+%{${Number(m5.target_pct || 0).toFixed(1)}}` : "—"}</span>
                <span>15dk: {m15 ? `+%{${Number(m15.target_pct || 0).toFixed(1)}}` : "—"}</span>
                <span>Hız: {Number(candidate.velocity_score || 0).toFixed(1)}</span>
              </div>
              {candidate.ml_hit_probability != null && (
                <div className="mt-1 text-[10px] text-emerald-400/90">
                  ML olasılık: %{(Number(candidate.ml_hit_probability) * 100).toFixed(1)}
                  {candidate.ml_target_pct != null ? ` (hedef +%${Number(candidate.ml_target_pct).toFixed(2)})` : ""}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-bunker-muted mt-2">
        Sembol adına tıklayınca M1 grafiği açılır · 5dk-%2 ve 15dk-%3 hız profilleri harmanlandı ·{" "}
        {scout.journal_saved ?? candidates.length} tahmin journal&apos;a kaydedildi.
      </p>
    </div>
  );
}

function ChatPageInner() {
  const { username, role } = useAuth();
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
  const [upsideScoutBusy, setUpsideScoutBusy] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // Sesli mesaj (Speech-to-Text) state'leri
  const [isListening, setIsListening] = useState(false);
  const [speechTranscript, setSpeechTranscript] = useState("");
  const [speechInterim, setSpeechInterim] = useState("");
  const recognitionRef = useRef<any>(null);

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
      /* local storage is optional */
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
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch {}
    }
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

  // Metin Kopyalama Yardımcısı
  const handleCopy = async (content: string, index: number) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1800);
    } catch {
      // sessizce geç
    }
  };

  // Sesli Mesaj (Speech-to-Text) Metotları
  const startListening = () => {
    if (typeof window === "undefined") return;
    const SpeechRecognitionClass = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionClass) {
      setError("Tarayıcınız ses tanıma (Speech-to-Text) özelliğini desteklemiyor. Google Chrome, Microsoft Edge veya Safari kullanabilirsiniz.");
      return;
    }
    try {
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch {}
      }
      const recognition = new SpeechRecognitionClass();
      recognition.lang = "tr-TR";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      let finalTrans = "";

      recognition.onstart = () => {
        setIsListening(true);
        setSpeechTranscript("");
        setSpeechInterim("");
        setError("");
      };

      recognition.onresult = (event: any) => {
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const trans = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTrans += (finalTrans ? " " : "") + trans.trim();
          } else {
            interim += trans;
          }
        }
        setSpeechTranscript(finalTrans);
        setSpeechInterim(interim);
      };

      recognition.onerror = (event: any) => {
        if (event.error === "no-speech") return;
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          setError("Mikrofon erişim izni verilmedi. Lütfen tarayıcı ayarlarından mikrofon iznini açın.");
        } else {
          setError(`Ses algılama hatası: ${event.error}`);
        }
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch (err: any) {
      setError(`Mikrofon başlatılamadı: ${err.message || err}`);
      setIsListening(false);
    }
  };

  const stopListening = (action: "insert" | "send" | "cancel" = "insert") => {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch {}
      recognitionRef.current = null;
    }
    setIsListening(false);

    const fullText = (speechTranscript + (speechInterim ? " " + speechInterim : "")).trim();
    setSpeechTranscript("");
    setSpeechInterim("");

    if (action === "cancel" || !fullText) return;

    if (action === "send") {
      void sendMessage(fullText);
    } else {
      setInput((prev) => (prev ? prev + " " + fullText : fullText));
    }
  };

  const handleVoiceSend = (transcript: string) => {
    stopListening("cancel");
    if (transcript.trim()) {
      void sendMessage(transcript.trim());
    }
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
    const load = () => {
      if (document.hidden) return;
      apiRequest(`${API_BASE}/api/llm/tool-logs?limit=24`)
        .then((r) => r.json())
        .then((data) => setLogs(data.logs || []))
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const load = () => {
      if (document.hidden) return;
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
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const checkLastResponse = () => {
      const sid = localStorage.getItem(CHAT_SESSION_KEY) || "";
      if (!sid) return;
      apiRequest(`${API_BASE}/api/llm/chat/last-response?session_id=${encodeURIComponent(sid)}`, { cache: "no-store" })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (data && data.response) {
            setMessages((prev) => {
              if (prev.length > 1 && prev[prev.length - 1].role === "assistant" && prev[prev.length - 1].content === data.response) return prev;
              return [...prev, { role: "assistant" as const, content: data.response, time: new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) }];
            });
          }
        })
        .catch(() => undefined);
    };
    checkLastResponse();
    const handler = () => { if (!document.hidden) checkLastResponse(); };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);

  const stickToBottomRef = useRef(true);
  const handleScroll = () => {
    const el = endRef.current?.parentElement;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  const handleWindowScroll = () => {
    const el = endRef.current?.parentElement;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const nearBottom = window.innerHeight + window.scrollY >=
      (el.scrollHeight + rect.top + window.scrollY) - 80;
    stickToBottomRef.current = nearBottom;
  };
  useEffect(() => {
    const el = endRef.current?.parentElement;
    if (!el) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("scroll", handleWindowScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", handleScroll);
      window.removeEventListener("scroll", handleWindowScroll);
    };
  }, []);
  useEffect(() => {
    if (stickToBottomRef.current)
      endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, busy]);

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
      time: new Date(toMs(d.at || Date.now() / 1000)).toLocaleTimeString("tr-TR"),
      success: d.success,
      duration_ms: d.duration_ms,
    }, ...current].slice(0, 40));
  });

  const sendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const nowTime = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    const next = [...messages, { role: "user" as const, content: trimmed, time: nowTime }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError("");
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      setMessages([...next, { role: "assistant", content: "", time: nowTime }]);
      await streamChat(
        `${API_BASE}/api/strategies/llm/chat`,
        next,
        (delta) =>
          setMessages((current) => [
            ...current.slice(0, -1),
            {
              role: "assistant",
              content: (current[current.length - 1]?.content || "") + delta,
              time: nowTime,
            },
          ]),
        {
          active_tools: activeTools,
          active_skills: activeSkills,
          session_id: sessionId,
          username: username,
          user_role: role || "user",
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
      setMessages([...next, { role: "assistant", content: message, time: nowTime }]);
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
      setBusy(false);
    }
  };

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    sendMessage(input);
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
      const scout: ScoutResult = {
        symbols: Array.isArray(data.symbols) ? data.symbols : [],
        candidates: Array.isArray(data.candidates) ? data.candidates : [],
        generated_at: data.generated_at,
        journal_saved: data.journal_saved,
      };
      const scoreText = scout.candidates.length
        ? scout.candidates
            .map((c) => `${c.symbol} (${Number(c.upside_rank).toFixed(1)} puan)`)
            .join(", ")
        : scout.symbols.join(", ") || data.symbol;
      const nowTime = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
      setMessages((current) => [
        ...current,
        {
          role: "user" as const,
          content: `🎯 EN HIZLI YÜKSELİŞ ANALİZİ: ${scoreText}`,
          time: nowTime,
        },
        {
          role: "assistant" as const,
          content: data.analysis || "Analiz üretilemedi.",
          scout,
          time: nowTime,
        },
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
      <div className="chat-layout">
        <Card className="chat-conversation">
          {/* Üst Başlık & Kontrol Çubuğu */}
          <div className="chat-top-bar flex flex-wrap items-center justify-between gap-2 pb-3 mb-2 border-b border-bunker-800">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-base">
                💬
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-mono text-sm font-bold text-white tracking-wide">
                    CHAT MERKEZİ
                  </h1>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${role === "admin" ? "bg-purple-500/20 text-purple-300 border border-purple-500/40" : "bg-emerald-500/20 text-neon-green border border-emerald-500/40"}`}>
                    {role === "admin" ? "🛡️ YÖNETİCİ" : "📈 UZMAN TRADER"}
                  </span>
                  <span className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono text-bunker-muted">
                    <span className={`w-1.5 h-1.5 rounded-full ${busy ? "bg-amber-400 animate-ping" : "bg-neon-green"}`} />
                    {busy ? "YANITLANIYOR" : "HAZIR"}
                  </span>
                </div>
                <p className="text-[11px] text-bunker-muted">
                  {username ? `${username} ile aktif sohbet · ` : ""}Canlı Binance TR piyasa analizi
                </p>
              </div>
            </div>

            <div className="flex items-center gap-1.5 sm:gap-2">
              <span className={`chat-context-meter text-[11px] font-mono px-2 py-1 rounded bg-black/40 border border-bunker-800 ${contextTone}`}>
                {Math.min(100, contextRatio * 100).toFixed(1)}% hafıza
              </span>
              <Button variant="secondary" onClick={startNewChat} className="text-xs px-2.5 py-1.5 font-mono">
                ＋ YENİ SOHBET
              </Button>
              <button
                type="button"
                onClick={() => setControlsOpen((v) => !v)}
                className="ui-button ui-button-secondary text-xs px-2.5 py-1.5 flex items-center gap-1 font-mono md:hidden"
                title="Model Akışını Aç/Kapat"
              >
                <span>⚡</span>
                <span>AKIŞ</span>
                {activities.length > 0 && (
                  <span className="w-4 h-4 rounded-full bg-emerald-500/30 text-neon-green text-[9px] flex items-center justify-center font-bold">
                    {Math.min(activities.length, 99)}
                  </span>
                )}
              </button>
            </div>
          </div>

          {contextTone !== "normal" && (
            <div className={`chat-context-alert ${contextTone} mb-2`} role="status">
              <span>
                {contextTone === "critical"
                  ? "Context penceresi dolmaya çok yakın. Yeni sohbet başlatmanız önerilir."
                  : "Sohbet context penceresinin %80'ini geçti."}
              </span>
              <span>
                ~{contextTokens.toLocaleString("tr-TR")} / {CONTEXT_WINDOW_TOKENS.toLocaleString("tr-TR")} token
              </span>
            </div>
          )}

          {/* Mesaj Akışı */}
          <div className="chat-messages flex-1 overflow-y-auto space-y-3 p-1">
            {messages.length <= 1 && (
              <div className="chat-welcome-card card border-bunker-700/60 bg-gradient-to-br from-bunker-900/90 via-bunker-950/80 to-emerald-950/20 p-4 sm:p-5 shadow-xl mb-3">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-xl">
                    📈
                  </div>
                  <div>
                    <h2 className="text-white font-mono font-bold text-sm sm:text-base flex items-center gap-2">
                      SCALPER AI <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-neon-green border border-emerald-500/40">{role === "admin" ? "YÖNETİCİ MODU" : "UZMAN TRADER MODU"}</span>
                    </h2>
                    <p className="text-xs text-bunker-muted">
                      {username ? `Hoş geldin ${username}! ` : ""}Canlı Binance TR piyasa yönü, teknik seviyeler ve risk yönetimi için hazır.
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-3 border-t border-bunker-800/80 text-xs">
                  <div className="flex items-start gap-2 text-bunker-muted">
                    <span className="text-neon-green font-bold">✓</span>
                    <span>Kapanmış mumlarla teyitli destek, direnç ve kırılım analizleri</span>
                  </div>
                  <div className="flex items-start gap-2 text-bunker-muted">
                    <span className="text-neon-green font-bold">✓</span>
                    <span>Hacim patlamaları, hız avcısı ve momentum tespitleri</span>
                  </div>
                  <div className="flex items-start gap-2 text-bunker-muted">
                    <span className="text-neon-green font-bold">✓</span>
                    <span>Net risk/ödül oranı, stop seviyeleri ve senaryo planları</span>
                  </div>
                  <div className="flex items-start gap-2 text-bunker-muted">
                    <span className="text-neon-green font-bold">✓</span>
                    <span>Mikrofon simgesine (🎙️) basarak sesli soru gönderebilirsiniz</span>
                  </div>
                </div>
              </div>
            )}

            {messages.map((message, index) => {
              const isUser = message.role === "user";
              return (
                <div
                  key={index}
                  className={`chat-message group flex gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}
                >
                  {!isUser && (
                    <div className="chat-avatar shrink-0 w-8 h-8 rounded-xl bg-bunker-800 border border-emerald-500/40 text-neon-green flex items-center justify-center font-mono text-xs font-bold shadow-md">
                      AI
                    </div>
                  )}

                  <div className={`chat-bubble-container max-w-[92%] sm:max-w-[85%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                    <div className="flex items-center gap-2 mb-1 px-1 text-[11px] font-mono text-bunker-muted">
                      <span className="font-semibold text-slate-300">
                        {isUser ? `SİZ ${username ? `(${username})` : ""}` : `Scalper ${role === "admin" ? "· Yönetici" : "· Uzman Trader"}`}
                      </span>
                      {message.time && <span>{message.time}</span>}
                    </div>

                    <div
                      className={`chat-bubble rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-lg ${
                        isUser
                          ? "bg-gradient-to-br from-emerald-950/40 to-bunker-900 border border-emerald-500/30 text-emerald-100 rounded-tr-sm"
                          : "bg-bunker-900/95 border border-bunker-700/70 text-slate-200 rounded-tl-sm"
                      }`}
                    >
                      {message.scout ? (
                        <div className="space-y-2.5">
                          <UpsideScoutCard scout={message.scout} />
                          {message.content && <MarkdownMessage content={message.content} />}
                        </div>
                      ) : (
                        <MarkdownMessage content={message.content} />
                      )}

                      {!isUser && message.content && (
                        <div className="flex items-center justify-end gap-1.5 mt-2.5 pt-2 border-t border-bunker-800/80 text-xs">
                          <button
                            type="button"
                            onClick={() => handleCopy(message.content, index)}
                            className="chat-action-btn"
                            title="Metni Kopyala"
                          >
                            <span>{copiedIndex === index ? "✓" : "📋"}</span>
                            <span>{copiedIndex === index ? "Kopyalandı" : "Kopyala"}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => speakingIndex === index ? stopSpeaking() : void speak(message.content, index)}
                            className={`chat-action-btn ${speakingIndex === index ? "text-neon-green border-emerald-500/50 bg-emerald-500/10" : ""}`}
                            title={speakingIndex === index ? "Seslendirmeyi Durdur" : "Seslendir"}
                          >
                            <span>{speakingIndex === index ? "⏹" : "🔊"}</span>
                            <span>{speakingIndex === index ? "Durdur" : "Dinle"}</span>
                          </button>
                        </div>
                      )}
                      {isUser && (
                        <div className="flex items-center justify-end mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            type="button"
                            onClick={() => handleCopy(message.content, index)}
                            className="chat-action-btn text-[10px] py-0.5"
                            title="Mesajı Kopyala"
                          >
                            <span>{copiedIndex === index ? "✓" : "📋"}</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {isUser && (
                    <div className="chat-avatar shrink-0 w-8 h-8 rounded-xl bg-emerald-500 text-black flex items-center justify-center font-mono text-xs font-bold shadow-md">
                      {username ? username.slice(0, 2).toUpperCase() : "SİZ"}
                    </div>
                  )}
                </div>
              );
            })}

            {busy && (
              <div className="chat-thinking flex items-center gap-2 text-xs font-mono text-amber-300 py-1">
                <span className="status-dot animate-pulse" />
                <span>Model yanıtı hazırlanıyor…</span>
              </div>
            )}

            {livePriceWatch && (
              <div className="chat-price-watch mb-2" role="status" aria-live="polite">
                <div>
                  <p className="eyebrow">CANLI FİYAT TAKİBİ · {livePriceWatch.symbol}</p>
                  <strong>
                    {Number.isFinite(livePriceWatch.price)
                      ? `₺${livePriceWatch.price?.toLocaleString("tr-TR", { maximumFractionDigits: 8 })}`
                      : "Bağlanıyor…"}
                  </strong>
                  <span className={livePriceWatch.changePct == null || !Number.isFinite(livePriceWatch.changePct) ? "text-bunker-muted" : livePriceWatch.changePct >= 0 ? "text-neon-green" : "text-neon-red"}>
                    {Number.isFinite(livePriceWatch.changePct) ? `%${(livePriceWatch.changePct || 0) >= 0 ? "+" : ""}${livePriceWatch.changePct?.toFixed(3)}` : ""}
                  </span>
                </div>
                <div className="chat-price-watch-range">
                  <span>Düşük: {livePriceWatch.low ?? "—"}</span>
                  <span>Yüksek: {livePriceWatch.high ?? "—"}</span>
                  <span>Örnek: {livePriceWatch.samples ?? 0}</span>
                </div>
                {busy && livePriceWatch.status !== "completed" && (
                  <Button variant="secondary" onClick={stopLiveWatch}>TAKİBİ DURDUR</Button>
                )}
              </div>
            )}

            <div ref={endRef} />
          </div>

          {/* Hızlı İşlemler & Soru Önerileri */}
          <div className="chat-quick-toolbar flex flex-col gap-1.5 my-2">
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                className="chat-scan-button-wide flex-1 min-h-[2.4rem] font-mono text-xs border-emerald-500/30 hover:border-emerald-500/60 bg-emerald-950/20"
                onClick={runUpsideScout}
                disabled={upsideScoutBusy || busy}
              >
                {upsideScoutBusy ? (
                  <span className="upside-scout-loading flex items-center justify-center gap-2">
                    <span className="upside-scout-spinner" />
                    <span className="upside-scout-text text-neon-green font-bold">EN HIZLI YÜKSELİŞ KEŞFEDİLİYOR</span>
                  </span>
                ) : (
                  <span className="flex items-center justify-center gap-1.5 text-neon-green font-bold">
                    <span>🎯</span>
                    <span>EN HIZLI YÜKSELİŞ ANALİZİ (5DK + 15DK)</span>
                  </span>
                )}
              </Button>
            </div>

            <div className="chat-quick-prompts flex overflow-x-auto gap-1.5 pb-1" aria-label="Hızlı soru önerileri">
              {QUICK_PROMPTS.map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => sendMessage(item.prompt)}
                  disabled={busy}
                  className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-bunker-900/80 border border-bunker-700/70 hover:border-emerald-500/50 hover:bg-emerald-950/30 text-slate-300 hover:text-neon-green text-xs font-mono transition-all disabled:opacity-40"
                >
                  <span>{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Mesaj Yazma & Sesli Giriş Bölümü */}
          <div className="chat-composer-section pt-1">
            {/* Canlı Ses Kaydı Paneli */}
            {isListening && (
              <div className="chat-voice-panel card mb-2 border-red-500/50 bg-gradient-to-r from-red-950/40 via-bunker-900/95 to-bunker-950 p-3 shadow-2xl rounded-xl">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
                    </span>
                    <span className="text-xs font-mono font-bold text-red-400 uppercase tracking-wider">
                      Ses Kaydediliyor (tr-TR)
                    </span>
                    <div className="flex items-end gap-1 h-4 ml-1" aria-hidden="true">
                      <span className="w-1 bg-red-400 rounded-full animate-voice-bar-1" />
                      <span className="w-1 bg-red-400 rounded-full animate-voice-bar-2" />
                      <span className="w-1 bg-red-400 rounded-full animate-voice-bar-3" />
                      <span className="w-1 bg-red-400 rounded-full animate-voice-bar-4" />
                      <span className="w-1 bg-red-400 rounded-full animate-voice-bar-5" />
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => stopListening("cancel")}
                      className="text-xs text-bunker-muted hover:text-white px-2 py-1 rounded bg-bunker-800/80 hover:bg-bunker-700 transition-colors font-mono"
                    >
                      ✕ İptal
                    </button>
                    <button
                      type="button"
                      onClick={() => stopListening("insert")}
                      className="text-xs text-yellow-300 hover:text-yellow-200 px-2.5 py-1 rounded bg-yellow-500/20 border border-yellow-500/40 hover:bg-yellow-500/30 transition-colors font-mono font-semibold"
                    >
                      ✏️ Düzenle
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const fullText = (speechTranscript + (speechInterim ? " " + speechInterim : "")).trim();
                        handleVoiceSend(fullText);
                      }}
                      disabled={!(speechTranscript || speechInterim).trim()}
                      className="text-xs text-black bg-neon-green hover:bg-emerald-400 px-3 py-1 rounded font-mono font-bold transition-all disabled:opacity-40 flex items-center gap-1"
                    >
                      <span>➤</span>
                      <span>Gönder</span>
                    </button>
                  </div>
                </div>
                <div className="min-h-[2.2rem] max-h-24 overflow-y-auto rounded bg-black/50 p-2.5 text-xs font-mono border border-bunker-800/80">
                  <span className="text-white font-medium">{speechTranscript}</span>
                  <span className="text-bunker-muted italic ml-1">{speechInterim || (speechTranscript ? "" : "Mikrofon dinliyor… konuşmaya başlayın")}</span>
                </div>
              </div>
            )}

            {/* Metin & Ses Giriş Formu */}
            <form onSubmit={send} className="chat-input-form relative">
              <div className="flex items-end gap-2 p-2 bg-bunker-900/95 border border-bunker-700/80 rounded-xl focus-within:border-emerald-500/70 focus-within:ring-1 focus-within:ring-emerald-500/30 transition-all shadow-xl backdrop-blur-md">
                {/* Mikrofon Tuşu */}
                <button
                  type="button"
                  onClick={() => isListening ? stopListening("insert") : startListening()}
                  className={`chat-mic-btn ${isListening ? "is-active" : ""}`}
                  title={isListening ? "Kaydı Durdur ve Düzenle" : "Sesli Mesaj Gönder (tr-TR)"}
                  aria-label="Sesli mesaj"
                  disabled={busy}
                >
                  <span className="text-base leading-none">{isListening ? "⏹" : "🎙️"}</span>
                  {isListening && <span className="mic-pulse-ring" />}
                </button>

                {/* Mesaj Metin Alanı */}
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={isListening ? "Mikrofon dinliyor… konuşabilirsiniz" : "Bir soru sor… örn. BTC/TRY direnç ve trend analizi yap (veya 🎙️ ile sesli sor)"}
                  rows={1}
                  disabled={busy}
                  className="flex-1 bg-transparent border-0 text-white placeholder-bunker-muted resize-none text-sm py-2 px-1 max-h-36 min-h-[38px] leading-relaxed outline-none font-sans"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      if (!busy && input.trim()) {
                        sendMessage(input);
                      }
                    }
                  }}
                />

                {/* Gönder / Durdur Butonu */}
                {busy ? (
                  <Button
                    variant="danger"
                    type="button"
                    onClick={stopResponse}
                    className="text-xs px-3 py-2 shrink-0 font-mono font-bold"
                    title="Yanıtı Durdur"
                  >
                    ⏹ DURDUR
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    type="submit"
                    disabled={!input.trim()}
                    className="text-xs px-3.5 py-2 shrink-0 font-mono font-bold flex items-center gap-1.5 disabled:opacity-40"
                    title="Gönder (Enter)"
                  >
                    <span>GÖNDER</span>
                    <span className="text-xs">➤</span>
                  </Button>
                )}
              </div>

              <div className="flex items-center justify-between text-[10px] text-bunker-muted mt-1 px-1 font-mono">
                <span>💡 Enter: Gönder · Shift+Enter: Yeni Satır · 🎙️: Sesli Mesaj</span>
                {input.length > 0 && <span>{input.length} karakter</span>}
              </div>
            </form>
            {error && <p className="mt-2 text-xs text-neon-red font-mono bg-red-950/20 border border-red-500/30 p-2 rounded">{error}</p>}
          </div>
        </Card>

        {/* Sağ Panel: Model Akışı & Arka Plan Etkinlikleri */}
        <Card className={`chat-controls ${controlsOpen ? "is-open" : ""}`}>
          <div className="chat-controls-header flex items-center justify-between gap-2 pb-2 border-b border-bunker-800">
            <div>
              <p className="eyebrow">ARKA PLAN İŞLERİ</p>
              <h2 className="font-mono text-sm font-bold text-white flex items-center gap-2">
                <span>MODEL AKIŞI</span>
                <span className="w-2 h-2 rounded-full bg-neon-green animate-pulse" />
              </h2>
            </div>
            <div className="flex items-center gap-1.5">
              {role === "admin" && (
                <Link href="/settings?tab=chat" className="ui-button ui-button-secondary text-[10px] px-2 py-1 font-mono" style={{ textDecoration: "none" }}>
                  ⚙ AYARLAR
                </Link>
              )}
              <button
                type="button"
                onClick={() => setControlsOpen(false)}
                className="md:hidden text-bunker-muted hover:text-white text-xs px-2 py-1 rounded bg-bunker-800"
              >
                ✕
              </button>
            </div>
          </div>

          <button
            type="button"
            className="chat-controls-toggle"
            onClick={() => setControlsOpen((v) => !v)}
            aria-expanded={controlsOpen}
            aria-controls="chat-controls-body"
          >
            <span className="chat-controls-toggle-label">
              <span>
                <span className="eyebrow block text-left">ARKA PLAN İŞLERİ</span>
                <span className="block text-left font-mono text-sm font-bold text-white">MODEL AKIŞI</span>
              </span>
              <span className="chat-controls-toggle-icon" aria-hidden="true">{controlsOpen ? "−" : "+"}</span>
            </span>
          </button>

          <div id="chat-controls-body" className="chat-controls-body">
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
                      <span className={a.success ? "text-neon-green text-[10px] shrink-0" : "text-neon-red text-[10px] shrink-0"}>
                        {Math.round(a.duration_ms)}ms
                      </span>
                    )}
                  </div>
                ))}
                <div ref={activityEndRef} />
              </div>
            </div>

            <div className="chat-log-panel">
              <p className="eyebrow mb-2">ÖZET PERFORMANS</p>
              <div className="chat-trace-grid grid grid-cols-3 gap-2 text-[10px] font-mono">
                <span className="rounded border border-bunker-700 p-2 text-center">
                  <span className="block text-bunker-muted">Trace</span>
                  <span className="text-white font-bold">{traces.length}</span>
                </span>
                <span className="rounded border border-bunker-700 p-2 text-center">
                  <span className="block text-bunker-muted">Eval</span>
                  <span className="text-neon-green font-bold">
                    {evaluations.filter((item) => item.passed).length}/{evaluations.length || 0}
                  </span>
                </span>
                <span className="rounded border border-bunker-700 p-2 text-center">
                  <span className="block text-bunker-muted">Kural</span>
                  <span className="text-white font-bold">{instincts.length}</span>
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <footer className="chat-footer">
        <span>SCALPERAGENT · CHAT & SESLİ ASİSTAN</span>
        <span className="chat-footer-status">
          <span className="status-dot" /> PAPER ONLY · CANLI PUBLIC DATA
        </span>
      </footer>
    </div>
  );
}

export default function ChatPage() {
  return <ChatPageInner />;
}
