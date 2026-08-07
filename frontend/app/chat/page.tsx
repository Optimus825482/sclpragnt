"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import MarkdownMessage from "../components/MarkdownMessage";
import { streamChat } from "../lib/streamChat";
import { Badge, Button, Card, SectionHeader } from "../components/ui";

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
const starter: Message[] = [
  {
    role: "assistant",
    content:
      "Merhaba. Paper-trading verilerini, strateji performansını ve backtest sonuçlarını birlikte inceleyebilirim. Ne araştırmak istersin?",
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"system" | "tools" | "skills">(
    "system",
  );
  const [hydrated, setHydrated] = useState(false);
  const [sessionId, setSessionId] = useState("chat:main");
  const endRef = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/llm/config`).then((r) => r.json()),
      fetch(`${API_BASE}/api/llm/chat-settings`).then((r) => r.json()),
    ])
      .then(([data, settings]) => {
        setSkills(data.skills || []);
        if (Array.isArray(settings.active_tools))
          setActiveTools(Array.from(new Set([...ALL_TOOLS, ...settings.active_tools])));
        if (Array.isArray(settings.active_skills))
          setActiveSkills(settings.active_skills);
        chatSettingsReady.current = true;
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!chatSettingsReady.current) return;
    const timer = window.setTimeout(() => {
      fetch(`${API_BASE}/api/llm/chat-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_tools: activeTools,
          active_skills: activeSkills,
        }),
      }).catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeTools, activeSkills]);
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/llm/tool-logs?limit=24`)
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
        fetch(`${API_BASE}/api/llm/evaluations?limit=8`).then((r) => r.json()),
        fetch(`${API_BASE}/api/llm/instincts?status=active&limit=6`).then((r) =>
          r.json(),
        ),
        fetch(`${API_BASE}/api/llm/agent-traces?limit=8`).then((r) => r.json()),
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
      );
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "LLM bağlantısı kurulamadı.";
      setError(message);
      setMessages([...next, { role: "assistant", content: message }]);
    } finally {
      setBusy(false);
    }
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
    await fetch(`${API_BASE}/api/llm/chat-settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_tools: activeTools,
        active_skills: activeSkills,
      }),
    });
    setSettingsOpen(false);
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
          <SectionHeader
            eyebrow="SOHBET"
            title="Araştırma asistanı"
            description="Mevcut sohbet, siz Yeni sohbet başlatana kadar korunur."
          />
          <div className="chat-conversation-actions">
            <span className={`chat-context-meter ${contextTone}`}>
              {Math.min(100, contextRatio * 100).toFixed(2)}% context
            </span>
            <Button variant="secondary" onClick={startNewChat}>
              ＋ YENİ SOHBET
            </Button>
          </div>
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
                <div className="chat-avatar">
                  {message.role === "user" ? "SİZ" : "AI"}
                </div>
                <div className="chat-bubble">
                  <p className="eyebrow mb-2">
                    {message.role === "user" ? "KULLANICI" : "SCALPER"}
                  </p>
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
            <div ref={endRef} />
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
          </form>
          {error && <p className="mt-3 text-xs text-neon-red">{error}</p>}
        </Card>
        <Card className="chat-controls">
          <div className="chat-controls-header">
            <SectionHeader
              eyebrow="AKTİF DURUM"
              title="Model akışı"
              description="Kullanılan araçlar ve son çağrı kayıtları."
            />
            <Button variant="secondary" onClick={() => setSettingsOpen(true)}>
              ⚙ AYARLAR
            </Button>
          </div>
          <div className="chat-live-tools">
            <p className="eyebrow mb-2">AKTİF ARAÇLAR · {activeTools.length}</p>
            <div className="chat-tool-chips">
              {activeTools.map((name) => (
                <Badge key={name} tone="info">
                  {name}
                </Badge>
              ))}
            </div>
          </div>
          <div className="chat-log-panel">
            <div className="flex items-center justify-between mb-2">
              <p className="eyebrow">CANLI TOOL LOGLARI</p>
              <span className="status-dot" />
            </div>
            {logs.length ? (
              logs.slice(0, 12).map((log) => (
                <div className="chat-log-row" key={log.id}>
                  <div>
                    <p className="font-mono text-xs text-white truncate">
                      {log.tool_name}
                    </p>
                    <p className="text-[10px] text-bunker-muted">
                      {log.result_summary ||
                        (log.success ? "başarılı" : "hata")}
                    </p>
                  </div>
                  <span
                    className={
                      log.success ? "text-neon-green" : "text-neon-red"
                    }
                  >
                    {log.duration_ms ? `${Math.round(log.duration_ms)}ms` : "•"}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-bunker-muted">
                Henüz tool çağrısı yok.
              </p>
            )}
          </div>
          <div className="chat-log-panel">
            <p className="eyebrow mb-2">TRACE / EVALUATION / INSTINCT</p>
            <div className="grid grid-cols-3 gap-2 text-[10px] font-mono">
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
            {traces.slice(0, 2).map((item) => (
              <div className="chat-log-row" key={item.trace_id}>
                <span className="truncate">
                  {item.intent || item.trace_id.slice(0, 18)}
                </span>
                <span
                  className={
                    item.status === "completed"
                      ? "text-neon-green"
                      : "text-yellow-300"
                  }
                >
                  {item.status}
                </span>
              </div>
            ))}
            {evaluations.slice(0, 3).map((item) => (
              <div className="chat-log-row" key={item.id}>
                <span>{item.evaluator_type}</span>
                <span
                  className={item.passed ? "text-neon-green" : "text-neon-red"}
                >
                  {item.passed ? "PASS" : item.failure_category || "FAIL"}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
      {settingsOpen && (
        <div
          className="chat-modal-backdrop"
          onClick={() => setSettingsOpen(false)}
        >
          <div
            className="chat-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Chat ayarları"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="chat-modal-head">
              <div>
                <p className="eyebrow">CHAT YAPILANDIRMASI</p>
                <h2 className="font-mono text-lg font-bold">
                  Sistem ve yetenekler
                </h2>
              </div>
              <Button variant="ghost" onClick={() => setSettingsOpen(false)}>
                ✕
              </Button>
            </div>
            <div className="chat-modal-tabs">
              {(
                [
                  ["system", "Sistem + Soul"],
                  ["tools", `Araçlar (${activeTools.length})`],
                  ["skills", `Skill'ler (${activeSkills.length || "tümü"})`],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  className={settingsTab === id ? "active" : ""}
                  onClick={() => setSettingsTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="chat-modal-body">
              {settingsTab === "system" && (
                <div className="space-y-3">
                  <div className="chat-setting-card">
                    <Badge tone="positive">AKTİF</Badge>
                    <h3>System prompt</h3>
                    <p>
                      Paper-only çalışma, Türkçe yanıt, veri uydurmama ve risk
                      kurallarına uyum.
                    </p>
                  </div>
                  <div className="chat-setting-card">
                    <Badge tone="positive">AKTİF</Badge>
                    <h3>Soul persona</h3>
                    <p>
                      Kanıta dayalı, risk duyarlı ve strateji araştırmasına
                      odaklı asistan karakteri.
                    </p>
                  </div>
                </div>
              )}
              {settingsTab === "tools" && (
                <div>
                  {TOOL_GROUPS.map(([group, names]) => (
                    <div key={group} className="mb-4">
                      <p className="eyebrow mb-2">{group}</p>
                      {names.map((name) => (
                        <label key={name} className="chat-toggle compact">
                          <input
                            type="checkbox"
                            checked={activeTools.includes(name)}
                            onChange={() =>
                              toggle(name, setActiveTools, activeTools)
                            }
                          />
                          <span>{name}</span>
                        </label>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              {settingsTab === "skills" && (
                <div>
                  {enabledSkills.length ? (
                    enabledSkills.map((skill) => (
                      <label key={skill.id} className="chat-toggle compact">
                        <input
                          type="checkbox"
                          checked={activeSkills.includes(String(skill.id))}
                          onChange={() =>
                            toggle(
                              String(skill.id),
                              setActiveSkills,
                              activeSkills,
                            )
                          }
                        />
                        <span>
                          <b>{skill.name}</b>
                          <small>{skill.instructions}</small>
                        </span>
                      </label>
                    ))
                  ) : (
                    <p className="text-xs text-bunker-muted">
                      Aktif skill bulunamadı.
                    </p>
                  )}
                </div>
              )}
            </div>
            <div className="chat-modal-foot">
              <Button variant="primary" onClick={() => setSettingsOpen(false)}>
                UYGULA VE KAPAT
              </Button>
            </div>
          </div>
        </div>
      )}
      <footer className="chat-footer">
        <span>SCALPERAGENT · CHAT</span>
        <span className="chat-footer-status">
          <span className="status-dot" /> PAPER ONLY · PUBLIC DATA
        </span>
      </footer>
    </div>
  );
}
