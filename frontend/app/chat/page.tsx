"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import MarkdownMessage from "../components/MarkdownMessage";
import { Badge, Button, Card, SectionHeader } from "../components/ui";

type Message = { role: "user" | "assistant"; content: string };
type Skill = { id: number; name: string; instructions: string; enabled: boolean };
const TOOL_GROUPS = [
  ["Veri", ["get_strategy_config", "get_strategy_stats", "get_trades", "get_signals", "get_decision_logs", "query_database", "read_only_sql", "search_memory"]],
  ["Araştırma", ["run_backtest", "run_custom_backtest", "run_backtest_robustness", "get_backtest_history", "scan_market_snapshots", "deep_analyze_symbol"]],
] as const;
const ALL_TOOLS = TOOL_GROUPS.flatMap(([, names]) => names);
const starter: Message[] = [{ role: "assistant", content: "Merhaba. Paper-trading verilerini, strateji performansını ve backtest sonuçlarını birlikte inceleyebilirim. Ne araştırmak istersin?" }];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(starter);
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [activeTools, setActiveTools] = useState<string[]>(ALL_TOOLS);
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { fetch(`${API_BASE}/api/llm/config`).then(r => r.json()).then(data => setSkills(data.skills || [])).catch(() => undefined); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  const enabledSkills = useMemo(() => skills.filter(s => s.enabled), [skills]);
  const send = async (event?: FormEvent) => {
    event?.preventDefault(); const text = input.trim(); if (!text || busy) return;
    const next = [...messages, { role: "user" as const, content: text }]; setMessages(next); setInput(""); setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/strategies/llm/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: next, active_tools: activeTools, active_skills: activeSkills, session_id: "chat:main" }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || body.error || `Sunucu hatası (${response.status})`);
      setMessages([...next, { role: "assistant", content: body.text || "Yanıt alınamadı." }]);
    } catch (e) { const message = e instanceof Error ? e.message : "LLM bağlantısı kurulamadı."; setError(message); setMessages([...next, { role: "assistant", content: message }]); } finally { setBusy(false); }
  };
  const toggle = (value: string, setter: (values: string[]) => void, current: string[]) => setter(current.includes(value) ? current.filter(item => item !== value) : [...current, value]);
  return <div className="chat-page">
    <div className="chat-heading"><div><p className="eyebrow">LLM · PAPER RESEARCH</p><h1 className="font-mono text-2xl font-bold">CHAT <span className="text-neon-green">MERKEZİ</span></h1><p className="mt-2 text-sm text-bunker-muted">Sistem promptu, Soul persona ve seçtiğin yeteneklerle yapılandırılmış sohbet.</p></div><Badge tone="positive">{busy ? "YANIT ÜRETİLİYOR" : "HAZIR"}</Badge></div>
    <div className="chat-layout"><Card className="chat-conversation"><SectionHeader eyebrow="SOHBET" title="Araştırma asistanı" description="Yanıtlar Türkçe ve başlıklar, listeler, kodlar ile ayrıştırılmış olarak gösterilir." /><div className="chat-messages">{messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><div className="chat-avatar">{message.role === "user" ? "SİZ" : "AI"}</div><div className="chat-bubble"><p className="eyebrow mb-2">{message.role === "user" ? "KULLANICI" : "SOUL ASİSTAN"}</p><MarkdownMessage content={message.content} /></div></div>)}{busy && <div className="chat-thinking"><span className="status-dot" /> Araçlar ve model yanıtı hazırlanıyor…</div>}<div ref={endRef} /></div><form onSubmit={send} className="chat-composer"><textarea value={input} onChange={e => setInput(e.target.value)} placeholder="Bir soru sor… örn. Komisyon sonrası en iyi strateji hangisi?" rows={2} disabled={busy} /><Button variant="primary" type="submit" disabled={busy || !input.trim()}>GÖNDER ↗</Button></form>{error && <p className="mt-3 text-xs text-neon-red">{error}</p>}</Card>
      <Card className="chat-controls"><SectionHeader eyebrow="KONTROL PANELİ" title="Yetenekler" description="Modelin bu oturumda kullanmasına izin verilen araçlar." /><div className="space-y-4"><div><p className="eyebrow mb-2">SİSTEM KATMANI</p><div className="space-y-2"><label className="chat-toggle"><input type="checkbox" checked readOnly /><span><b>System prompt</b><small>Paper-only, veri uydurmama ve Türkçe çıktı kuralları</small></span></label><label className="chat-toggle"><input type="checkbox" checked readOnly /><span><b>Soul persona</b><small>Risk duyarlı strateji araştırma asistanı karakteri</small></span></label></div></div><div><p className="eyebrow mb-2">ARAÇLAR · {activeTools.length}/{ALL_TOOLS.length}</p>{TOOL_GROUPS.map(([group, names]) => <div key={group} className="mb-3"><p className="text-xs text-bunker-muted mb-1">{group}</p>{names.map(name => <label key={name} className="chat-toggle compact"><input type="checkbox" checked={activeTools.includes(name)} onChange={() => toggle(name, setActiveTools, activeTools)} /><span>{name}</span></label>)}</div>)}</div><div><p className="eyebrow mb-2">SKILL · {activeSkills.length || "TÜMÜ"}</p>{enabledSkills.length ? enabledSkills.map(skill => <label key={skill.id} className="chat-toggle compact"><input type="checkbox" checked={activeSkills.includes(String(skill.id))} onChange={() => toggle(String(skill.id), setActiveSkills, activeSkills)} /><span>{skill.name}</span></label>) : <p className="text-xs text-bunker-muted">Aktif skill bulunamadı.</p>}</div></div></Card>
    </div>
  </div>;
}
