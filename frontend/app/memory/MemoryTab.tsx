"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

export default function MemoryTab() {
  const [status, setStatus] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { apiFetch("/api/memory/status").then(setStatus).catch(() => setError("Memory durumu alınamadı")); }, []);
  const search = async () => { setError(""); try { const body = await apiFetch("/api/memory/retrieve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, limit: 8 }) }); setResults(body.results || []); } catch (e) { setError(e instanceof Error ? e.message : "Retrieval başarısız"); } };
  return <div className="space-y-5"><div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">{[["Durum", status?.enabled ? "Aktif" : "Pasif"],["Kalıcı belge", status?.persistent?.documents ?? "—"],["Hazır embedding", status?.persistent?.embedded ?? "—"],["Kuyruk", status?.worker?.pending ?? "—"],["Oturum hatası", status?.worker?.failed ?? "—"]].map(([a,b]) => <div className="panel p-4" key={a}><p className="eyebrow">{a}</p><p className="text-xl font-mono mt-2">{b}</p></div>)}</div><p className="text-xs text-bunker-muted">Kalıcı belge/embedding sayıları PostgreSQL’den gelir. Worker işlenen sayacı yalnızca mevcut sunucu oturumuna aittir.</p><div className="panel p-5"><div className="flex gap-2"><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Örn. BTCTRY benzer timeout işlemleri" className="input flex-1" /><button onClick={search} disabled={!query.trim()} className="ui-button ui-button-primary">ARA</button></div>{error && <p className="text-red-400 text-sm mt-3">{error}</p>}<div className="mt-5 space-y-3">{results.map(r => <article className="border border-bunker-700 rounded-lg p-3" key={r.id}><div className="flex justify-between text-xs font-mono text-bunker-muted"><span>{r.symbol ? <SymbolLink symbol={r.symbol} className="text-bunker-muted hover:text-neon-green" /> : "global"} · {r.layer}</span><span>{Number(r.similarity || 0).toFixed(3)}</span></div><p className="text-sm mt-2 whitespace-pre-wrap">{r.content}</p></article>)}</div></div></div>;
}
