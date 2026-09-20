"use client";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

export default function MemoryTab() {
  const [status, setStatus] = useState<any>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const data = await apiFetch("/api/memory/status");
      setStatus(data);
    } catch {
      setError("Memory durumu alınamadı");
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const search = async () => {
    if (!query.trim()) return;
    setError("");
    setSearching(true);
    setSearched(true);
    try {
      const body = await apiFetch("/api/memory/retrieve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), limit: 8 }),
      });
      setResults(body.results || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retrieval başarısız");
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="eyebrow text-neon-green">HAFIZA DURUMU</p>
        <button
          type="button"
          onClick={loadStatus}
          disabled={statusLoading}
          className="ui-button ui-button-secondary text-xs"
        >
          {statusLoading ? "YENİLENİYOR…" : "🔄 YENİLE"}
        </button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          ["Durum", status?.enabled ? "Aktif" : "Pasif"],
          ["Kalıcı Belge", status?.persistent?.documents ?? "—"],
          ["Hazır Embedding", status?.persistent?.embedded ?? "—"],
          ["Kuyruk", status?.worker?.pending ?? "—"],
          ["Oturum Hatası", status?.worker?.failed ?? "—"],
        ].map(([a, b]) => (
          <div className="card p-4" key={a}>
            <p className="eyebrow">{a}</p>
            <p className="text-xl font-mono font-bold mt-2 text-white">{b}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-bunker-muted font-mono">
        Kalıcı belge ve embedding sayıları PostgreSQL’den gelir. Worker işlenen sayacı yalnızca mevcut sunucu oturumuna aittir.
      </p>

      <div className="card p-5 space-y-4">
        <p className="eyebrow text-neon-green">SEMANTİK ARAMA (RETRIEVAL)</p>
        <div className="flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && query.trim() && !searching) search(); }}
            placeholder="Örn. BTCTRY benzer timeout işlemleri veya trend analizi…"
            className="input flex-1 min-w-[240px]"
          />
          <button
            type="button"
            onClick={search}
            disabled={!query.trim() || searching}
            className="ui-button ui-button-primary"
          >
            {searching ? "ARANIYOR…" : "ARA"}
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red font-mono">
            {error}
          </div>
        )}

        {searching && (
          <div className="space-y-2 py-4 animate-pulse">
            <div className="h-16 rounded-lg bg-bunker-900 border border-bunker-800" />
            <div className="h-16 rounded-lg bg-bunker-900 border border-bunker-800" />
          </div>
        )}

        {!searching && searched && results.length === 0 && !error && (
          <p className="py-8 text-center text-sm font-mono text-bunker-muted">
            Bu sorguya uygun kayıt bulunamadı.
          </p>
        )}

        {!searching && results.length > 0 && (
          <div className="space-y-3 pt-2">
            {results.map((r) => (
              <article className="border border-bunker-800 rounded-lg bg-bunker-900/40 p-3.5 space-y-2" key={r.id}>
                <div className="flex justify-between items-center text-xs font-mono text-bunker-muted border-b border-bunker-800/60 pb-1.5">
                  <span>
                    {r.symbol ? (
                      <SymbolLink symbol={r.symbol} className="font-bold text-white hover:text-neon-green" />
                    ) : (
                      "global"
                    )}{" "}
                    · <span className="text-bunker-300">{r.layer}</span>
                  </span>
                  <span className="rounded bg-bunker-800 px-1.5 py-0.5 text-neon-green font-bold">
                    Benzerlik: {Number(r.similarity || 0).toFixed(3)}
                  </span>
                </div>
                <p className="text-sm text-bunker-100 whitespace-pre-wrap leading-relaxed">{r.content}</p>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
