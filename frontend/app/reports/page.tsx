"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type ReportItem = {
  id: number | null;
  symbol: string;
  message: string | null;
  title: string | null;
  score: number | null;
  target_pct: number;
  price: number;
  expected_price: number | null;
  diff_pct: number | null;
  status: "TAMAMEN BAŞARILI" | "BAŞARILI" | "KISMİ" | "BAŞARISIZ" | "BEKLENİYOR";
  mode: string | null;
  horizon_minutes: number | null;
  detected_at: number;
  sent_via_push: boolean | null;
};

const fmtPrice = (value: number | null) => {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  return Number(value).toLocaleString("tr-TR", { maximumFractionDigits: 6 });
};

const fmtDate = (ts: number | null) => {
  if (!ts) return "—";
  const ms = ts < 10_000_000_000 ? ts * 1000 : ts;
  return new Date(ms).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

const statusMeta: Record<string, { label: string; className: string }> = {
  "TAMAMEN BAŞARILI": { label: "TAMAMEN", className: "border-neon-green/50 bg-neon-green/10 text-neon-green" },
  "BAŞARILI": { label: "BAŞARILI", className: "border-neon-green/30 bg-neon-green/5 text-neon-green" },
  "KISMİ": { label: "KISMİ", className: "border-yellow-300/40 bg-yellow-300/10 text-yellow-300" },
  "BAŞARISIZ": { label: "BAŞARISIZ", className: "border-neon-red/40 bg-neon-red/10 text-neon-red" },
  "BEKLENİYOR": { label: "BEKLİYOR", className: "border-bunker-600 bg-bunker-800/50 text-bunker-muted" },
};
const statusBadge = (status: string) => statusMeta[status] || statusMeta["BEKLENİYOR"];

export default function ReportsPage() {
  const [items, setItems] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "success" | "partial" | "fail">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/reports/notifications?limit=200`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setItems(data.notifications || []);
      }
    } catch { /* sessiz */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  const total = items.length;
  const counts = items.reduce((acc, it) => {
    if (it.status === "TAMAMEN BAŞARILI" || it.status === "BAŞARILI") acc.success++;
    else if (it.status === "KISMİ") acc.partial++;
    else if (it.status === "BAŞARISIZ") acc.fail++;
    else acc.pending++;
    return acc;
  }, { success: 0, partial: 0, fail: 0, pending: 0 });
  const successRate = total > 0 ? Math.round((counts.success / total) * 100) : 0;

  const filtered = items.filter((it) => {
    if (filter === "success") return it.status === "TAMAMEN BAŞARILI" || it.status === "BAŞARILI";
    if (filter === "partial") return it.status === "KISMİ";
    if (filter === "fail") return it.status === "BAŞARISIZ";
    return true;
  });

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">RAPOR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Bildirim Raporu</h1>
          <p className="mt-1 text-sm text-bunker-muted">Radarın oluşturduğu bildirimlerin başarı durumu.</p>
        </div>
        <button onClick={load} className="ui-button ui-button-secondary">⟳ Tazele</button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card"><p className="eyebrow">BAŞARI</p><p className="mt-2 font-mono text-2xl font-bold text-neon-green">%{successRate}</p><p className="text-xs text-bunker-muted">{counts.success}/{total} bildirim</p></div>
        <div className="card"><p className="eyebrow">TAMAMEN + BAŞARILI</p><p className="mt-2 font-mono text-2xl font-bold text-neon-green">{counts.success}</p></div>
        <div className="card"><p className="eyebrow">KISMİ</p><p className="mt-2 font-mono text-2xl font-bold text-yellow-300">{counts.partial}</p></div>
        <div className="card"><p className="eyebrow">BAŞARISIZ</p><p className="mt-2 font-mono text-2xl font-bold text-neon-red">{counts.fail}</p></div>
      </div>

      <div className="card">
        <div className="flex flex-wrap items-center gap-2">
          <p className="eyebrow text-neon-green mr-auto">BİLDİRİMLER ({filtered.length})</p>
          {(["all", "success", "partial", "fail"] as const).map((f) => (
            <button key={f} type="button" onClick={() => setFilter(f)} className={`rounded-lg border px-3 py-1.5 font-mono text-xs transition-colors ${filter === f ? "border-neon-green/50 bg-neon-green/10 text-neon-green" : "border-bunker-700 text-bunker-muted hover:border-bunker-600"}`}>
              {f === "all" ? "TÜMÜ" : f === "success" ? "BAŞARILI" : f === "partial" ? "KISMİ" : "BAŞARISIZ"}
            </button>
          ))}
        </div>

        {loading && items.length === 0 ? (
          <p className="py-10 text-center font-mono text-sm text-bunker-muted">Yükleniyor…</p>
        ) : filtered.length === 0 ? (
          <p className="py-10 text-center font-mono text-sm text-bunker-muted">Henüz bildirim yok.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Zaman</th><th>Sembol</th><th>Skor</th><th>Hedef</th><th>Beklenen</th><th>Fark</th><th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((it) => {
                  const meta = statusBadge(it.status);
                  return (
                    <tr key={`${it.id}-${it.symbol}-${it.detected_at}`}>
                      <td className="font-mono text-xs text-bunker-muted">{fmtDate(it.detected_at)}</td>
                      <td><SymbolLink symbol={it.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                      <td className="font-mono text-xs text-white">{it.score != null ? Number(it.score).toFixed(1) : "—"}</td>
                      <td className="font-mono text-xs text-neon-green">{it.target_pct > 0 ? `+%${Number(it.target_pct).toFixed(1)}` : "—"}</td>
                      <td className="font-mono text-xs text-white">{fmtPrice(it.expected_price)}</td>
                      <td className={`font-mono text-xs ${it.diff_pct == null ? "text-bunker-muted" : it.diff_pct >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                        {it.diff_pct != null ? `${it.diff_pct >= 0 ? "+" : ""}${it.diff_pct.toFixed(2)}%` : "—"}
                      </td>
                      <td><span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${meta.className}`}>{meta.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
