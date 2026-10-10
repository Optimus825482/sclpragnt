"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

/** Slot/delta rapor satırı — backend /api/daily-rising/reports `reports`. */
type ReportRow = {
  id: number;
  kind: "slot" | "delta" | string;
  sent_at: number;
  sent: boolean;
  message: string | null;
  candidates: Array<Record<string, unknown>> | string | null;
  prev_report_id: number | null;
};

type SlotCandidate = {
  symbol?: string;
  price?: number;
  entry_price?: number;
  current_price?: number;
  change_pct?: number | null;
  ceiling_pct?: number;
  potential_pct?: number;
  target_probability?: number;
  strategy?: string;
  velocity_score?: number;
};

const pct = (v: number | null | undefined, digits = 2): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;

const price = (v: number | null | undefined): string => {
  if (v == null) return "—";
  const x = Number(v);
  if (x >= 1000) return x.toLocaleString("tr-TR", { maximumFractionDigits: 0 });
  if (x >= 100) return x.toFixed(1);
  if (x >= 1) return x.toFixed(2);
  if (x >= 0.01) return x.toFixed(4);
  return x.toFixed(6);
};

const parseCandidates = (r: ReportRow): SlotCandidate[] => {
  let list = r.candidates;
  if (typeof list === "string") {
    try { list = JSON.parse(list); } catch { list = []; }
  }
  return Array.isArray(list) ? (list as SlotCandidate[]) : [];
};

const kindBadge = (kind: string) =>
  kind === "slot"
    ? { label: "🌅 LİSTE", cls: "border-amber-400/50 bg-amber-400/15 text-amber-300" }
    : { label: "📊 FARK", cls: "border-sky-400/50 bg-sky-400/15 text-sky-300" };

const stratTag = (s?: string): string =>
  s === "both" ? "⚡📈" : s === "short_squeeze" ? "⚡" : s === "daily_momentum" ? "📈" : "";

/** Ana bileşen: son slot listesi + rapor geçmişi (liste ve fark gönderimleri). */
export default function DailyRisingTab() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "slot" | "delta">("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sending, setSending] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await getJSON<{ reports?: ReportRow[] }>(
        `/api/daily-rising/reports?limit=100&days=7`);
      setReports(d.reports || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rapor geçmişi yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Canlı yenile: döngü :00/:30/:15/:45'te yazıyor → 60 sn'de bir tazele.
  useEffect(() => {
    const t = setInterval(() => { void load(); }, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const triggerSend = async (endpoint: "send-slot-report" | "send-delta-report") => {
    setSending(endpoint);
    try {
      await apiRequest(`${API_BASE}/api/daily-rising/${endpoint}`, { method: "POST" });
      await load();
    } catch {
      /* gönderim hatası backend logunda */
    } finally {
      setSending("");
    }
  };

  const shown = filter === "all" ? reports : reports.filter((r) => r.kind === filter);
  const lastSlot = reports.find((r) => r.kind === "slot");
  const lastSlotCands = lastSlot ? parseCandidates(lastSlot) : [];

  return (
    <div className="space-y-4">
      {/* Son slot listesi (canlı özet kartı) */}
      <section className="card rounded-2xl border border-amber-400/30 bg-amber-400/5 p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-bunker-800 pb-3">
          <div>
            <h2 className="font-mono text-base font-black text-amber-300 flex items-center gap-2">
              <span>🌅</span> GÜNLÜK YÜKSELİŞ SLOT RAPORU
            </h2>
            <p className="mt-0.5 text-xs text-bunker-muted">
              Her saat başı ve :30&apos;da taze tarama listesi gruba gönderilir; :15 ve :45&apos;te
              fark + otlama (öneriden bu yana ort. değişim) raporu gelir. Kalite eşiği
              altındaysa hiçbir şey gönderilmez.
            </p>
          </div>
          {lastSlot && (
            <span className="font-mono text-[11px] text-bunker-muted whitespace-nowrap">
              Son liste: {fmtDateTime(lastSlot.sent_at * 1000)}
            </span>
          )}
        </div>

        {lastSlotCands.length === 0 ? (
          <p className="py-4 text-center font-mono text-xs text-bunker-muted">
            {loading ? "Yükleniyor…" : "Henüz slot raporu gönderilmedi (köprü kapalı ya da eşik altı)."}
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Coin</th>
                  <th className="text-right">Fiyat</th>
                  <th className="text-right">İhtimal</th>
                  <th className="text-right">Hedef</th>
                  <th className="text-right">Potansiyel</th>
                  <th>Kaynak</th>
                </tr>
              </thead>
              <tbody>
                {lastSlotCands.slice(0, 5).map((c) => (
                  <tr key={String(c.symbol)}>
                    <td><SymbolLink symbol={String(c.symbol || "")} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="text-right font-mono text-xs text-white">{price(c.price)}</td>
                    <td className="text-right font-mono text-xs text-sky-300">{c.target_probability != null ? `%${Math.round(Number(c.target_probability))}` : "—"}</td>
                    <td className="text-right font-mono text-xs text-neon-green">{c.ceiling_pct != null ? `+%${Math.round(Number(c.ceiling_pct))}` : "—"}</td>
                    <td className="text-right font-mono text-xs text-amber-300">{c.potential_pct != null ? `+%${Math.round(Number(c.potential_pct))}` : "—"}</td>
                    <td className="font-mono text-xs">{stratTag(c.strategy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Kontroller */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-xl border border-bunker-700 bg-bunker-900 p-1 font-mono text-xs">
          <span className="text-bunker-muted px-1.5 text-[11px]">Tür:</span>
          {([["all", "Tümü"], ["slot", "🌅 Liste"], ["delta", "📊 Fark"]] as const).map(([id, label]) => (
            <button key={id} type="button" onClick={() => setFilter(id)}
              className={`rounded-lg px-2 py-0.5 transition-all ${filter === id ? "bg-bunker-700 text-white font-bold" : "text-bunker-muted hover:text-white"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={load} className="ui-button ui-button-secondary text-xs py-1.5 px-3">Yenile</button>
        <button type="button" disabled={sending !== ""} onClick={() => void triggerSend("send-slot-report")}
          className="ui-button ui-button-primary text-xs py-1.5 px-3 disabled:opacity-40">
          {sending === "send-slot-report" ? "Gönderiliyor…" : "🌅 Liste Raporu Gönder"}
        </button>
        <button type="button" disabled={sending !== ""} onClick={() => void triggerSend("send-delta-report")}
          className="ui-button ui-button-secondary text-xs py-1.5 px-3 disabled:opacity-40">
          {sending === "send-delta-report" ? "Gönderiliyor…" : "📊 Fark Raporu Gönder"}
        </button>
      </div>

      {/* Geçmiş */}
      {error ? (
        <div className="card p-4 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-xs">⚠ {error}</div>
      ) : shown.length === 0 ? (
        <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">
          Son 7 günde bu türde rapor kaydı yok.
        </div>
      ) : (
        <div className="space-y-2">
          {shown.map((r) => {
            const badge = kindBadge(r.kind);
            const cands = parseCandidates(r);
            const isOpen = expanded === r.id;
            const avgChg = (() => {
              const chgs = cands.map((c) => c.change_pct).filter((v): v is number => v != null);
              return chgs.length ? chgs.reduce((a, b) => a + b, 0) / chgs.length : null;
            })();
            return (
              <div key={r.id} className="card rounded-xl border border-bunker-800 bg-bunker-900/40 overflow-hidden">
                <button type="button" onClick={() => setExpanded(isOpen ? null : r.id)}
                  className="w-full flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-left hover:bg-bunker-800/40 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-bold ${badge.cls}`}>{badge.label}</span>
                    <span className="font-mono text-xs text-white">{fmtDateTime(r.sent_at * 1000)}</span>
                    {!r.sent && <span className="rounded border border-bunker-700 bg-bunker-800 px-1.5 py-0.5 font-mono text-[10px] text-bunker-muted">GÖNDERİLEMEDİ</span>}
                  </div>
                  <div className="flex items-center gap-3 font-mono text-[11px] text-bunker-muted">
                    <span>{cands.length} aday</span>
                    {r.kind === "delta" && avgChg != null && (
                      <span className={avgChg >= 0 ? "text-neon-green" : "text-neon-red"}>
                        otlama: {pct(avgChg)}
                      </span>
                    )}
                    <span>{isOpen ? "▲" : "▼"}</span>
                  </div>
                </button>
                {isOpen && (
                  <div className="border-t border-bunker-800 p-4 space-y-3">
                    {cands.length > 0 && (
                      <div className="table-scroll">
                        <table className="data-table table-compact">
                          <thead>
                            <tr>
                              <th>Coin</th>
                              <th className="text-right">{r.kind === "slot" ? "Fiyat" : "Öneri"}</th>
                              {r.kind === "delta" && <th className="text-right">Anlık</th>}
                              {r.kind === "delta" && <th className="text-right">Fark</th>}
                              {r.kind === "slot" && <th className="text-right">İhtimal</th>}
                              {r.kind === "slot" && <th className="text-right">Potansiyel</th>}
                              <th>Kaynak</th>
                            </tr>
                          </thead>
                          <tbody>
                            {cands.map((c, i) => (
                              <tr key={`${r.id}-${String(c.symbol)}-${i}`}>
                                <td><SymbolLink symbol={String(c.symbol || "")} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                                <td className="text-right font-mono text-xs text-white">{price((c.entry_price ?? c.price) as number | undefined)}</td>
                                {r.kind === "delta" && <td className="text-right font-mono text-xs text-white">{price(c.current_price)}</td>}
                                {r.kind === "delta" && <td className={`text-right font-mono text-xs font-bold ${(c.change_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{pct(c.change_pct)}</td>}
                                {r.kind === "slot" && <td className="text-right font-mono text-xs text-sky-300">{c.target_probability != null ? `%${Math.round(Number(c.target_probability))}` : "—"}</td>}
                                {r.kind === "slot" && <td className="text-right font-mono text-xs text-amber-300">{c.potential_pct != null ? `+%${Math.round(Number(c.potential_pct))}` : "—"}</td>}
                                <td className="font-mono text-xs">{stratTag(c.strategy)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {r.message && (
                      <pre className="max-h-72 overflow-auto rounded-lg border border-bunker-800 bg-bunker-950 p-3 font-mono text-[11px] leading-relaxed text-bunker-muted whitespace-pre-wrap">
                        {r.message}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
