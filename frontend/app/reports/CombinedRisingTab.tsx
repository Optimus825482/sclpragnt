"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

/** Kombine rapor satırı — /api/daily-rising/reports. */
type ReportRow = {
  id: number;
  kind: string;            // combined_list | combined_status | slot | delta
  sent_at: number;
  sent: boolean;
  message: string | null;
  candidates: Array<Record<string, unknown>> | string | null;
  prev_report_id: number | null;
};

type Candidate = {
  symbol?: string;
  price?: number;
  notify_price?: number;
  entry_price?: number;
  current_price?: number;
  change_pct?: number | null;
  ceiling_pct?: number;
  potential_pct?: number;
  target_probability?: number;
  scan_score?: number;
  quality_score?: number;
  confirm_sources?: number;
  confirm_layers?: number;
  mfe_pct?: number | null;
  mae_pct?: number | null;
  carried?: boolean;
  strategy?: string;
};

type SummaryRow = {
  id: number;
  kind: string;
  sent_at: number;
  count: number;
  measured: number;
  ceiling_hits: number;
  hit_rate: number | null;
  avg_mfe_pct: number | null;
  avg_target_pct?: number | null;
  pending: boolean;
  rows: Candidate[];
};

type Summary = {
  ok: boolean;
  report_count: number;
  total_candidates: number;
  measured: number;
  ceiling_hits: number;
  hit_rate: number | null;
  avg_mfe_pct: number | null;
  avg_sent_gain_all_pct?: number | null;
  avg_sent_gain_today_pct?: number | null;
  avg_sent_gain_all_n?: number;
  avg_sent_gain_today_n?: number;
  avg_target_all_pct?: number | null;
  avg_target_today_pct?: number | null;
  pending: number;
  reports: SummaryRow[];
  by_source?: Record<string, { measured: number; ceiling_hits: number; hit_rate: number | null; avg_mfe_pct: number | null }>;
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

const parseCandidates = (r: ReportRow): Candidate[] => {
  let list = r.candidates;
  if (typeof list === "string") {
    try { list = JSON.parse(list); } catch { list = []; }
  }
  return Array.isArray(list) ? (list as Candidate[]) : [];
};

const kindBadge = (kind: string) =>
  kind === "combined_list" || kind === "slot"
    ? { label: "🌅 LİSTE", cls: "border-amber-400/50 bg-amber-400/15 text-amber-300" }
    : { label: "📊 DURUM", cls: "border-sky-400/50 bg-sky-400/15 text-sky-300" };

const stratTag = (s?: string): string =>
  s === "both" ? "⚡📈" : s === "short_squeeze" ? "⚡" : s === "daily_momentum" ? "📈"
    : s === "combined" ? "🌅"
    : s === "jump" ? "🚀" : s === "early" ? "🌱" : s === "rising" ? "📈" : "";

const sourceLabel: Record<string, string> = {
  combined: "Kombine", daily_momentum: "Günlük Momentum", short_squeeze: "Short-Squeeze",
  jump: "MACD Sıçrama", early: "MACD Erken", rising: "Yükseliş Eğilimi", both: "Momentum+Squeeze",
};

const hitTone = (rate: number | null | undefined): string => {
  if (rate == null) return "text-bunker-muted";
  if (rate >= 50) return "text-neon-green";
  if (rate >= 25) return "text-yellow-300";
  return "text-neon-red";
};

/** Detay penceresi (modal): tıklanan listenin her adayını, ilk bildirim fiyatına
    (anchor) göre TOPLAM artışıyla BAR grafiği olarak gösterir. */
function ListDetailModal({ row, onClose }: { row: SummaryRow; onClose: () => void }) {
  const cands = Array.isArray(row.rows) ? row.rows : [];
  // Toplam artış: anchor (ilk bildirim) → şimdi; yoksa change_pct; yoksa mfe.
  const items = cands.map((c) => {
    const anchor = (c as any).anchor_price ?? c.entry_price ?? c.notify_price ?? c.price;
    const now = c.current_price ?? (c as any).price;
    let total: number | null = null;
    try {
      if (anchor && now) total = (Number(now) / Number(anchor) - 1) * 100;
    } catch { total = null; }
    if (total == null && c.change_pct != null) total = Number(c.change_pct);
    const peak = c.mfe_pct != null ? Number(c.mfe_pct) : null;
    return { symbol: String(c.symbol || ""), anchor, now, total, peak };
  });
  const maxAbs = Math.max(1, ...items.map((i) => Math.abs(i.total ?? 0)));
  // ORTALAMALAR (kullanıcı isteği 2026-10-11): hedeflenen (tavan) + gerçekleşen
  // (toplam artış ve zirve) ortalamaları pencerede gösterilir.
  const withTotal = items.filter((i) => i.total != null);
  const tgtVals = cands.map((c) => (c.ceiling_pct != null ? Number(c.ceiling_pct) : null))
    .filter((v): v is number => v != null);
  const peakVals = items.map((i) => i.peak).filter((v): v is number => v != null);
  const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
  const avgTarget = avg(tgtVals);
  const avgTotal = avg(withTotal.map((i) => i.total as number));
  const avgPeak = avg(peakVals);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
         onClick={onClose}>
      <div className="w-full max-w-2xl rounded-2xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-bunker-800 pb-3">
          <div>
            <h3 className="font-mono text-base font-black text-white">🌅 Liste Detayı — Toplam Artış</h3>
            <p className="mt-0.5 text-xs text-bunker-muted font-mono">
              Gönderim: <b className="text-white">{fmtDateTime(row.sent_at * 1000)}</b> · {items.length} aday
              {row.pending
                ? <> · <span className="text-yellow-300">⏳ sürüyor</span></>
                : <> · <span className="text-bunker-muted">✓ bitti</span></>}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="rounded-lg border border-bunker-700 bg-bunker-900 px-2.5 py-1 font-mono text-xs text-bunker-muted hover:text-white">
            ✕ Kapat
          </button>
        </div>
        {/* ORTALAMA ÖZETİ */}
        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 p-2.5">
            <p className="font-mono text-[10px] text-bunker-muted">ORT. HEDEFLENEN</p>
            <p className="font-mono text-lg font-black text-amber-300">{avgTarget != null ? `+${avgTarget.toFixed(2)}%` : "—"}</p>
          </div>
          <div className="rounded-lg border border-neon-green/30 bg-neon-green/5 p-2.5">
            <p className="font-mono text-[10px] text-bunker-muted">ORT. GERÇEKLEŞEN</p>
            <p className={`font-mono text-lg font-black ${(avgTotal ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{avgTotal != null ? `${avgTotal >= 0 ? "+" : ""}${avgTotal.toFixed(2)}%` : "—"}</p>
          </div>
          <div className="rounded-lg border border-sky-400/30 bg-sky-400/5 p-2.5">
            <p className="font-mono text-[10px] text-bunker-muted">ORT. ZİRVE (MFE)</p>
            <p className="font-mono text-lg font-black text-sky-300">{avgPeak != null ? `+${avgPeak.toFixed(2)}%` : "—"}</p>
          </div>
        </div>
        <div className="mt-4 space-y-3">
          {items.length === 0 ? (
            <p className="py-6 text-center font-mono text-xs text-bunker-muted">Aday verisi yok.</p>
          ) : items.map((it) => {
            const t = it.total ?? 0;
            const w = Math.round((Math.abs(t) / maxAbs) * 100);
            const pos = t >= 0;
            return (
              <div key={it.symbol}>
                <div className="flex items-baseline justify-between font-mono text-xs">
                  <SymbolLink symbol={it.symbol} className="font-bold text-white hover:text-neon-green" />
                  <span className="text-bunker-muted">
                    ilk {price(it.anchor as number | undefined)} → şimdi {price(it.now as number | undefined)}
                  </span>
                  <span className={`font-black ${pos ? "text-neon-green" : "text-neon-red"}`}>
                    {it.total != null ? `${pos ? "+" : ""}${t.toFixed(2)}%` : "—"}
                  </span>
                </div>
                <div className="mt-1 h-3 w-full rounded bg-bunker-900 overflow-hidden">
                  <div className={`h-full rounded ${pos ? "bg-neon-green" : "bg-neon-red"}`}
                       style={{ width: `${Math.max(2, w)}%` }} />
                </div>
                {it.peak != null && (
                  <p className="mt-0.5 font-mono text-[10px] text-bunker-muted">
                    en yüksek (zirve): {pct(it.peak)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** Kombine Günlük Yükseliş rapor sekmesi (2026-10-11).

    Tek WhatsApp kanalını yansıtır: 30 dk'da bir TOP-3 liste, 10 dk'da bir durum
    takibi. Ayrıca gönderilen listelerin başarı durumlarını + modül genel başarısını
    (kaynak/strateji kırılımıyla) gösterir. */
export default function CombinedRisingTab() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [lastList, setLastList] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "list" | "status">("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sending, setSending] = useState("");
  // Detay penceresi (modal): tıklanan listenin adaylarının toplam artışı.
  const [detail, setDetail] = useState<SummaryRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [r, s, lr] = await Promise.all([
        getJSON<{ reports?: ReportRow[] }>("/api/daily-rising/reports?limit=100&days=7"),
        getJSON<Summary>("/api/daily-rising/reports/summary?days=7").catch(() => null),
        getJSON<any>("/api/daily-rising/last-report?kind=combined_list").catch(() => null),
      ]);
      setReports(r.reports || []);
      setSummary(s);
      setLastList(lr && lr.ok ? lr : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rapor geçmişi yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(() => { void load(); }, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const triggerSend = async (endpoint: "send-slot-report" | "send-delta-report") => {
    setSending(endpoint);
    try {
      await apiRequest(`${API_BASE}/api/daily-rising/${endpoint}`, { method: "POST" });
      await load();
    } catch { /* backend logu */ } finally { setSending(""); }
  };

  const shown = filter === "all" ? reports
    : reports.filter((r) => (filter === "list"
      ? (r.kind === "combined_list" || r.kind === "slot")
      : (r.kind === "combined_status" || r.kind === "delta")));

  return (
    <div className="space-y-4">
      {/* Modül genel başarısı */}
      {summary && summary.report_count > 0 ? (
        <section className="card rounded-2xl border border-neon-green/30 bg-neon-green/5 p-4 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-bunker-800 pb-3">
            <div>
              <h2 className="font-mono text-base font-black text-neon-green flex items-center gap-2">
                <span>🎯</span> KOMBİNE TARAMA MODÜLÜ BAŞARISI
              </h2>
              <p className="mt-0.5 text-xs text-bunker-muted">
                Tüm radar stratejilerinin birleştiği tek taramanın başarısı. Her gönderilen
                liste, gönderim anından bu yana değerlendirilir (tavan hedefine ulaştı mı?).
                {summary.pending > 0 ? <>&nbsp;<b className="text-yellow-300">{summary.pending}</b> liste hâlâ sürüyor (sonraki liste bekleniyor).</> : null}
              </p>
            </div>
            <span className="font-mono text-[11px] text-bunker-muted whitespace-nowrap">
              {summary.report_count} rapor · {summary.total_candidates} aday
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-xl border border-neon-green/30 bg-bunker-900/60 p-4">
              <p className="text-[11px] text-bunker-muted font-mono">ORTALAMA YÜKSELME — TÜM ZAMANLAR</p>
              <div className="mt-1 flex items-baseline gap-4 flex-wrap">
                <div>
                  <span className="text-[10px] text-bunker-muted font-mono block">Gerçekleşen</span>
                  <span className={`font-mono text-3xl font-black ${(summary.avg_sent_gain_all_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                    {summary.avg_sent_gain_all_pct != null
                      ? `${summary.avg_sent_gain_all_pct >= 0 ? "+" : ""}${summary.avg_sent_gain_all_pct.toFixed(2)}%`
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-bunker-muted font-mono block">Hedeflenen</span>
                  <span className="font-mono text-3xl font-black text-amber-300">
                    {summary.avg_target_all_pct != null ? `+${summary.avg_target_all_pct.toFixed(2)}%` : "—"}
                  </span>
                </div>
              </div>
              <p className="text-[10px] text-bunker-muted font-mono mt-1">{summary.avg_sent_gain_all_n ?? 0} gönderilen adayın ortalaması</p>
            </div>
            <div className="rounded-xl border border-sky-400/30 bg-bunker-900/60 p-4">
              <p className="text-[11px] text-bunker-muted font-mono">ORTALAMA YÜKSELME — BUGÜN</p>
              <div className="mt-1 flex items-baseline gap-4 flex-wrap">
                <div>
                  <span className="text-[10px] text-bunker-muted font-mono block">Gerçekleşen</span>
                  <span className={`font-mono text-3xl font-black ${(summary.avg_sent_gain_today_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                    {summary.avg_sent_gain_today_pct != null
                      ? `${summary.avg_sent_gain_today_pct >= 0 ? "+" : ""}${summary.avg_sent_gain_today_pct.toFixed(2)}%`
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-bunker-muted font-mono block">Hedeflenen</span>
                  <span className="font-mono text-3xl font-black text-amber-300">
                    {summary.avg_target_today_pct != null ? `+${summary.avg_target_today_pct.toFixed(2)}%` : "—"}
                  </span>
                </div>
              </div>
              <p className="text-[10px] text-bunker-muted font-mono mt-1">{summary.avg_sent_gain_today_n ?? 0} bugünkü adayın ortalaması</p>
            </div>
          </div>

          {/* Kaynak/strateji kırılımı */}
          {summary.by_source && Object.keys(summary.by_source).length > 0 ? (
            <div className="pt-2 border-t border-bunker-800/80 space-y-2">
              <p className="font-mono text-xs font-bold text-white">🧩 KAYNAK (STRATEJİ) BAŞARISI</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                {Object.entries(summary.by_source).map(([src, s]) => (
                  <div key={src} className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-2.5 font-mono text-xs">
                    <div className="font-bold text-white truncate">{sourceLabel[src] || src}</div>
                    <div className="mt-1 flex items-baseline justify-between">
                      <span className="text-[11px] text-bunker-muted">{s.measured} ölç.</span>
                      <span className={`font-black ${hitTone(s.hit_rate)}`}>{s.hit_rate != null ? `%${s.hit_rate.toFixed(0)}` : "—"}</span>
                    </div>
                    <div className="text-[10px] text-bunker-muted mt-0.5">ort. max {s.avg_mfe_pct != null ? pct(s.avg_mfe_pct) : "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}


        </section>
      ) : null}

      {/* Son gönderilen liste (bildirim anı ↔ anlık) */}
      {lastList?.rows?.length ? (
        <section className="card rounded-2xl border border-amber-400/30 bg-amber-400/5 p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="font-mono text-base font-black text-amber-300">📤 SON GÖNDERİLEN LİSTE</h2>
              <p className="mt-0.5 text-xs text-bunker-muted">
                Bildirim: <b className="text-white">{lastList.sent_at ? fmtDateTime(lastList.sent_at * 1000) : "—"}</b>
                {" · "}bildirim fiyatı → anlık fiyat
                {lastList.avg_change_pct != null ? <> · ort. değişim <b className={lastList.avg_change_pct >= 0 ? "text-neon-green" : "text-neon-red"}>{pct(lastList.avg_change_pct)}</b></> : null}
              </p>
            </div>
            <button onClick={load} className="ui-button ui-button-secondary text-xs py-1.5 px-3">Tazele</button>
          </div>
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Coin</th><th>Kaynak</th>
                  <th className="text-right">Bildirim</th>
                  <th className="text-right">Anlık</th>
                  <th className="text-right">Değişim</th>
                  <th className="text-right">Gerçekleşen Max</th>
                  <th className="text-right">Tavan</th>
                  <th className="text-center">Tavan?</th>
                </tr>
              </thead>
              <tbody>
                {lastList.rows.map((r: any) => (
                  <tr key={r.symbol}>
                    <td><SymbolLink symbol={String(r.symbol || "")} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs">{stratTag(r.strategy)}</td>
                    <td className="text-right font-mono text-xs text-white">{price(r.entry_price)}</td>
                    <td className="text-right font-mono text-xs text-white">{price(r.current_price)}</td>
                    <td className={`text-right font-mono text-xs font-bold ${(r.change_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{pct(r.change_pct)}</td>
                    <td className={`text-right font-mono text-xs ${(r.mfe_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{r.mfe_pct != null ? pct(r.mfe_pct) : "—"}</td>
                    <td className="text-right font-mono text-xs text-neon-yellow">{r.ceiling_pct != null ? `+%${Math.round(r.ceiling_pct)}` : "—"}</td>
                    <td className="text-center">
                      {r.hit_ceiling === true ? <span className="font-mono text-[10px] font-bold text-neon-green">✓ Ulaştı</span>
                        : r.hit_ceiling === false ? <span className="font-mono text-[10px] text-neon-red">✗</span>
                        : <span className="text-bunker-muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* Kontroller */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-xl border border-bunker-700 bg-bunker-900 p-1 font-mono text-xs">
          <span className="text-bunker-muted px-1.5 text-[11px]">Tür:</span>
          {([["all", "Tümü"], ["list", "🌅 Liste"], ["status", "📊 Durum"]] as const).map(([id, label]) => (
            <button key={id} type="button" onClick={() => setFilter(id)}
              className={`rounded-lg px-2 py-0.5 transition-all ${filter === id ? "bg-bunker-700 text-white font-bold" : "text-bunker-muted hover:text-white"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={load} className="ui-button ui-button-secondary text-xs py-1.5 px-3">Yenile</button>
        <button type="button" disabled={sending !== ""} onClick={() => void triggerSend("send-slot-report")}
          className="ui-button ui-button-primary text-xs py-1.5 px-3 disabled:opacity-40">
          {sending === "send-slot-report" ? "Gönderiliyor…" : "🌅 Kombine Liste Gönder"}
        </button>
        <button type="button" disabled={sending !== ""} onClick={() => void triggerSend("send-delta-report")}
          className="ui-button ui-button-secondary text-xs py-1.5 px-3 disabled:opacity-40">
          {sending === "send-delta-report" ? "Gönderiliyor…" : "📊 Durum Takibi Gönder"}
        </button>
      </div>

      {/* Rapor bazında ortalama yükselme tablosu */}
      {summary && summary.reports.length > 0 ? (
        <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4 space-y-3">
          <h3 className="font-mono text-sm font-black text-white">📋 GÖNDERİLEN LİSTELER — ORTALAMA YÜKSELME</h3>
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Gönderim</th><th className="text-right">Aday</th>
                  <th className="text-right" title="Listedeki adayların hedef (tavan) ortalaması">Hedeflenen %</th>
                  <th className="text-right" title="Seçildiği andan itibaren ulaşılan en yüksek yükselme ortalaması">Gerçekleşen %</th>
                  <th title="Gerçekleşen / Hedeflenen oranı">Gerçekleşme</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {summary.reports.map((r) => {
                  const tgt = r.avg_target_pct ?? 0;
                  const mfe = r.avg_mfe_pct ?? 0;
                  // Hedefe ulaşma oranı (0-100+); bar genişliği %100'e kırpılır.
                  const ratio = tgt > 0 ? (mfe / tgt) * 100 : null;
                  const barW = ratio == null ? 0 : Math.max(0, Math.min(100, ratio));
                  const tone = ratio == null ? "bg-bunker-600"
                    : ratio >= 75 ? "bg-neon-green" : ratio >= 40 ? "bg-yellow-400" : "bg-neon-red";
                  return (
                  <tr key={r.id} className="cursor-pointer hover:bg-bunker-800/40"
                      onClick={() => setDetail(r)}
                      title="Tıklayın: adayların toplam artış detayı (grafik)">
                    <td className="font-mono text-xs text-bunker-muted whitespace-nowrap">{fmtDateTime(r.sent_at * 1000)}</td>
                    <td className="text-right font-mono text-xs text-white">{r.count}</td>
                    <td className="text-right font-mono text-xs text-amber-300">{r.avg_target_pct != null ? `+${Number(r.avg_target_pct).toFixed(2)}%` : "—"}</td>
                    <td className={`text-right font-mono text-sm font-bold ${mfe >= 0 ? "text-neon-green" : "text-neon-red"}`}>{r.avg_mfe_pct != null ? pct(r.avg_mfe_pct) : "—"}</td>
                    <td className="min-w-[120px]">
                      {ratio == null ? <span className="font-mono text-[10px] text-bunker-muted">—</span> : (
                        <div className="flex items-center gap-2">
                          <div className="h-2.5 flex-1 rounded bg-bunker-800 overflow-hidden">
                            <div className={`h-full rounded ${tone}`} style={{ width: `${barW}%` }} />
                          </div>
                          <span className="font-mono text-[10px] text-bunker-muted w-10 text-right">{Math.round(ratio)}%</span>
                        </div>
                      )}
                    </td>
                    <td>
                      {r.pending
                        ? <span className="inline-flex items-center rounded border border-yellow-400/40 bg-yellow-400/10 px-2 py-0.5 font-mono text-[10px] font-bold text-yellow-300">⏳ SÜRÜYOR</span>
                        : <span className="inline-flex items-center rounded border border-bunker-700 bg-bunker-800 px-2 py-0.5 font-mono text-[10px] font-bold text-bunker-muted">✓ BİTTİ</span>}
                      <span className="ml-2 font-mono text-[10px] text-bunker-muted underline">detay</span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* Gönderim geçmişi (accordion) */}
      {error ? (
        <div className="card p-4 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-xs">⚠ {error}</div>
      ) : shown.length === 0 ? (
        <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">
          {loading ? "Yükleniyor…" : "Son 7 günde gönderilmiş rapor kaydı yok."}
        </div>
      ) : (
        <div className="space-y-2">
          {shown.map((r) => {
            const badge = kindBadge(r.kind);
            const cands = parseCandidates(r);
            const isOpen = expanded === r.id;
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
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right">Fiyat</th>}
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right">İhtimal</th>}
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right">Miktar</th>}
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right">Potansiyel</th>}
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right" title="Kaç sinyal motoru + kaç Master Surge katmanı hemfikir">Teyit</th>}
                              {(r.kind === "combined_list" || r.kind === "slot") && <th className="text-right" title="Sinyal gücü endeksi (0-99) — olasılık DEĞİL">Puan</th>}
                              {(r.kind === "combined_status" || r.kind === "delta") && <th className="text-right">Bildirim</th>}
                              {(r.kind === "combined_status" || r.kind === "delta") && <th className="text-right">Anlık</th>}
                              {(r.kind === "combined_status" || r.kind === "delta") && <th className="text-right">Değişim</th>}
                              <th>Kaynak</th>
                            </tr>
                          </thead>
                          <tbody>
                            {cands.map((c, i) => (
                              <tr key={`${r.id}-${String(c.symbol)}-${i}`}>
                                <td><SymbolLink symbol={String(c.symbol || "")} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                                {(r.kind === "combined_list" || r.kind === "slot") && (
                                  <>
                                    <td className="text-right font-mono text-xs text-white">{price((c.notify_price ?? c.price) as number | undefined)}</td>
                                    <td className="text-right font-mono text-xs text-sky-300">{c.target_probability != null ? `%${Math.round(Number(c.target_probability))}` : "—"}</td>
                                    <td className="text-right font-mono text-xs text-neon-green">{c.ceiling_pct != null ? `+%${Math.round(Number(c.ceiling_pct))}` : "—"}</td>
                                    <td className="text-right font-mono text-xs text-amber-300">{c.potential_pct != null ? `+%${Math.round(Number(c.potential_pct))}` : "—"}</td>
                                    <td className="text-right font-mono text-xs text-bunker-muted">{(c.confirm_sources != null || c.confirm_layers != null) ? `${c.confirm_sources ?? 0}+${c.confirm_layers ?? 0}` : "—"}</td>
                                    <td className="text-right font-mono text-xs font-bold text-white">{(c.quality_score ?? c.scan_score) != null ? Math.round(Number(c.quality_score ?? c.scan_score)) : "—"}</td>
                                  </>
                                )}
                                {(r.kind === "combined_status" || r.kind === "delta") && (
                                  <>
                                    <td className="text-right font-mono text-xs text-white">{price(c.entry_price)}</td>
                                    <td className="text-right font-mono text-xs text-white">{price(c.current_price)}</td>
                                    <td className={`text-right font-mono text-xs font-bold ${(c.change_pct ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>{pct(c.change_pct)}</td>
                                  </>
                                )}
                                <td className="font-mono text-xs">{stratTag(c.strategy)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {r.message && (
                      <pre className="max-h-72 overflow-auto rounded-lg border border-bunker-800 bg-bunker-950 p-3 font-mono text-[11px] leading-relaxed text-bunker-muted whitespace-pre-wrap">{r.message}</pre>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Detay penceresi (modal) — listeye tıklayınca toplam artış grafiği */}
      {detail ? <ListDetailModal row={detail} onClose={() => setDetail(null)} /> : null}
    </div>
  );
}
