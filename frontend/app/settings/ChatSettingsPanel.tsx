"use client";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

const TOOL_GROUPS: [string, string[]][] = [
  ["Veri", ["get_strategy_config", "get_strategy_stats", "get_trades", "get_signals", "get_decision_logs", "query_database", "read_only_sql", "search_memory"]],
  ["Araştırma", ["run_backtest", "run_custom_backtest", "run_backtest_robustness", "get_backtest_history", "scan_market_snapshots", "detect_15m_upside_candidates", "deep_analyze_symbol", "get_data_quality", "get_microstructure_snapshot", "get_regime_snapshot", "calculate_trade_economics", "get_symbol_outcome_profile", "run_walk_forward", "run_execution_stress_test", "run_parameter_sensitivity", "run_holdout_test", "run_statistical_validation", "get_backtest_data_quality", "activate_coin", "place_paper_order", "open_llm_paper_trade"]],
  ["Canlı kontrol", ["create_market_alert", "update_market_alert", "remove_market_alert", "list_market_alerts", "get_llm_open_position", "update_llm_position_plan", "close_llm_position", "set_llm_symbol_guard", "remove_llm_symbol_guard", "list_llm_symbol_guards", "request_codex_research", "get_order_status", "cancel_paper_order", "modify_paper_order", "reconcile_portfolio", "deactivate_coin"]],
];
const ALL_TOOLS = TOOL_GROUPS.flatMap(([, names]) => names);

export default function ChatSettingsPanel() {
  const [activeTools, setActiveTools] = useState<string[]>(ALL_TOOLS);
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [skills, setSkills] = useState<{ id: number; name: string; instructions: string; enabled: boolean }[]>([]);
  const [ttsRate, setTtsRate] = useState(0);
  const [ttsPitch, setTtsPitch] = useState(0);
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([
      apiRequest(`${API_BASE}/api/llm/config`).then(r => r.json()),
      apiRequest(`${API_BASE}/api/llm/chat-settings`).then(r => r.json()),
    ]).then(([cfg, settings]) => {
      setSkills(cfg.skills || []);
      if (Array.isArray(settings.active_tools)) setActiveTools(Array.from(new Set([...ALL_TOOLS, ...settings.active_tools])));
      if (Array.isArray(settings.active_skills)) setActiveSkills(settings.active_skills);
      if (Number.isFinite(settings.tts_rate)) setTtsRate(settings.tts_rate);
      if (Number.isFinite(settings.tts_pitch)) setTtsPitch(settings.tts_pitch);
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, []);

  const save = async () => {
    await apiRequest(`${API_BASE}/api/llm/chat-settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active_tools: activeTools, active_skills: activeSkills, tts_rate: ttsRate, tts_pitch: ttsPitch }) });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
  };
  const toggle = (value: string) => setActiveTools(cur => cur.includes(value) ? cur.filter(x => x !== value) : [...cur, value]);
  const toggleSkill = (id: string) => setActiveSkills(cur => cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]);
  const enabledSkills = skills.filter(s => s.enabled);

  if (!loaded) return <div className="card bg-bunker-950"><p className="font-mono text-sm text-bunker-muted animate-pulse">Chat ayarları yükleniyor…</p></div>;
  return (
    <div className="card bg-bunker-950 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">CHAT TOOL VE SKILL YÖNETİMİ</p>
          <p className="text-xs text-bunker-muted mt-1">Chat sayfasındaki LLM araç ve yetenek seçimleri buradan yönetilir.</p>
        </div>
        <button onClick={save} className="min-h-10 rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 font-mono text-xs text-neon-green">{saved ? "✓ KAYDEDİLDİ" : "KAYDET"}</button>
      </div>
      <div>
        <p className="eyebrow mb-2">AKTİF ARAÇLAR · {activeTools.length}/{ALL_TOOLS.length}</p>
        <div className="flex flex-wrap gap-2">
          {TOOL_GROUPS.map(([group, names]) => (
            <div key={group} className="rounded-lg border border-bunker-700 bg-bunker-900 p-2">
              <p className="font-mono text-[10px] text-bunker-muted mb-1">{group}</p>
              <div className="flex flex-wrap gap-1">
                {names.map(name => (
                  <button key={name} onClick={() => toggle(name)} className={`rounded px-2 py-1 font-mono text-[10px] border ${activeTools.includes(name) ? "border-neon-green/50 bg-neon-green/10 text-neon-green" : "border-bunker-700 text-bunker-muted"}`}>{name}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="eyebrow mb-2">AKTİF YETENEKLER (SKILL) · {activeSkills.length || enabledSkills.length ? `${activeSkills.length} seçili` : "tümü"}</p>
        {enabledSkills.length ? (
          <div className="flex flex-wrap gap-2">
            {enabledSkills.map(s => (
              <button key={s.id} onClick={() => toggleSkill(String(s.id))} className={`rounded px-2 py-1 font-mono text-[10px] border ${activeSkills.includes(String(s.id)) ? "border-sky-400/50 bg-sky-400/10 text-sky-300" : "border-bunker-700 text-bunker-muted"}`}>{s.name}</button>
            ))}
          </div>
        ) : <p className="text-xs text-bunker-muted">Aktif skill yok; LLM / Provider sekmesinden ekleyebilirsin.</p>}
      </div>
      <div>
        <p className="eyebrow mb-2">SES (EDGE TTS · Emel)</p>
        <label className="flex items-center gap-3 text-xs font-mono text-bunker-muted">Hız: {ttsRate > 0 ? "+" : ""}{ttsRate}%<input type="range" min="-30" max="50" value={ttsRate} onChange={e => setTtsRate(Number(e.target.value))} className="flex-1" /></label>
        <label className="flex items-center gap-3 text-xs font-mono text-bunker-muted mt-2">Perde: {ttsPitch > 0 ? "+" : ""}{ttsPitch}Hz<input type="range" min="-20" max="20" value={ttsPitch} onChange={e => setTtsPitch(Number(e.target.value))} className="flex-1" /></label>
      </div>
    </div>
  );
}
