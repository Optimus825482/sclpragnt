"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import SymbolLink from "../components/SymbolLink";
import { formatSignedTL, formatTL, toMs, localDateInput } from "../lib/format";

const money = (v?: number | null) => formatSignedTL(v);
const plainMoney = (v?: number | null) => formatTL(v);

const num = (v?: number | null) => (v == null || !Number.isFinite(v) ? "—" : String(Number(v).toFixed(2)));
const pct = (v?: number | null, digits = 1) => (v == null || !Number.isFinite(v) ? "—" : `%${(Number(v) * 100).toFixed(digits)}`);
const fmtDt = (ts: number | null) => {
  if (!ts) return "—";
  return new Date(toMs(ts)).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const rl = (v: number | null | undefined) => (v == null ? 0 : v);

const STRATEGY_META: Record<string, string> = {
  VELOCITY: "Hız Avcısı",
  CHAT_PREDICTION: "Hız Avcısı (Otonom)",
  LLM_PAPER: "LLM Paper",
  GAINER_RADAR: "Gainer Radar",
  AUTO_PAPER: "Otonom Radar",
};
const strategyLabel = (s?: string | null) => STRATEGY_META[s?.toUpperCase() || ""] || s || "Diğer";

const pnlTone = (v: number | null | undefined) =>
  v == null || !Number.isFinite(Number(v)) ? "text-bunker-muted" : Number(v) >= 0 ? "text-neon-green" : "text-neon-red";

const accuracyTone = (v: number | null | undefined, warn = false) => {
  if (v == null || !Number.isFinite(Number(v))) return "text-bunker-muted";
  return Number(v) >= 0.55 ? "text-neon-green" : warn ? "text-yellow-300" : "text-neon-red";
};

function StatCard({ label, value, tone = "", sub, icon }: { label: string; value: React.ReactNode; tone?: string; sub?: string; icon?: string }) {
  return (
    <section className="card p-4 rounded-xl border border-bunker-800 bg-bunker-900/40 hover:border-bunker-700 transition-all">
      <div className="flex items-center justify-between">
        <p className="eyebrow text-bunker-muted">{label}</p>
        {icon && <span className="text-sm">{icon}</span>}
      </div>
      <p className={`mt-1.5 font-mono text-xl sm:text-2xl font-black ${tone || "text-white"}`}>{value}</p>
      {sub && <p className="mt-1 font-mono text-[11px] text-bunker-muted truncate">{sub}</p>}
    </section>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "ok" | "warn" | "bad" | "neutral" }) {
  const map: Record<string, string> = {
    ok: "border-neon-green/50 bg-neon-green/15 text-neon-green",
    warn: "border-yellow-400/40 bg-yellow-400/15 text-yellow-300",
    bad: "border-neon-red/40 bg-neon-red/15 text-neon-red",
    neutral: "border-bunker-600 bg-bunker-800/60 text-bunker-muted",
  };
  return <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold tracking-wide uppercase ${map[tone]}`}>{children}</span>;
}

const SOURCE_BADGE_META: Record<string, { label: string; cls: string }> = {
  velocity: { label: "RADAR", cls: "border-neon-green/50 bg-neon-green/15 text-neon-green" },
  jump: { label: "SIÇRAMA", cls: "border-sky-400/50 bg-sky-400/15 text-sky-300" },
  early: { label: "ERKEN", cls: "border-violet-400/50 bg-violet-400/15 text-violet-300" },
  rising: { label: "YÜKSELİŞ", cls: "border-amber-400/50 bg-amber-400/15 text-amber-300" },
};
const SOURCE_BADGE_COMPACT: Record<string, string> = {
  velocity: "RADAR",
  jump: "SIÇR.",
  early: "ERKEN",
  rising: "YÜKS.",
};

function SourceBadges({ sources, compact = false }: { sources?: string[] | null; compact?: boolean }) {
  const list = (sources || []).filter((s) => typeof s === "string" && s);
  if (!list.length) {
    return <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold ${SOURCE_BADGE_META.velocity.cls}`}>RADAR</span>;
  }
  return (
    <span className={compact ? "inline-flex flex-wrap items-center gap-1" : "inline-flex flex-wrap gap-1"}>
      {list.map((s) => {
        const meta = SOURCE_BADGE_META[s] || { label: s.toUpperCase(), cls: "border-bunker-600 bg-bunker-800/50 text-bunker-muted" };
        const label = compact ? (SOURCE_BADGE_COMPACT[s] || meta.label) : meta.label;
        return (
          <span key={s} title={meta.label} className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold ${meta.cls}`}>
            {label}
          </span>
        );
      })}
    </span>
  );
}

/* ==========================================================================
   1. GENEL BAKIŞ (OVERVIEW TAB)
   ========================================================================== */
function OverviewTab() {
  const [overview, setOverview] = useState<any>(null);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [breakdown, setBreakdown] = useState<any>(null);
  const [overall, setOverall] = useState<any>(null);
  const [autoPaperStats, setAutoPaperStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [ovRes, ntRes, apRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/reports/overview`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/reports/notifications?limit=200`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/auto-paper/stats`, { cache: "no-store" }),
      ]);
      const [ov, nt, ap] = await Promise.all([ovRes.json(), ntRes.json(), apRes.json()]);
      if (ovRes.ok) setOverview(ov);
      if (ntRes.ok) { setNotifications(nt.notifications || []); setBreakdown(nt.breakdown || null); setOverall(nt.overall || null); }
      if (apRes.ok) setAutoPaperStats(ap.stats || null);
      if (!ovRes.ok) setError(ov.detail || "Özet verisi alınamadı");
    } catch {
      setError("Rapor verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading && !overview) {
    return (
      <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">
        <span className="animate-spin inline-block mr-2">⏳</span> Performans ve özet verileri yükleniyor…
      </div>
    );
  }
  if (error && !overview) {
    return (
      <div className="card p-5 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-sm">
        ⚠ {error}
      </div>
    );
  }

  const o = overview?.overall || {};
  const symbols = overview?.symbols || [];
  const wins = rl(o.winning);
  const total = rl(o.trade_count);
  const winRate = total > 0 ? (wins / total) * 100 : null;
  const avgOrderTry = autoPaperStats && autoPaperStats.closed > 0
    ? (autoPaperStats.total_invested_try || 0) / autoPaperStats.closed
    : null;

  return (
    <div className="space-y-6">
      {/* Üst Ana Metrikler */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <StatCard label="NET PNL (KÂR / ZARAR)" value={money(o.net_pnl)} tone={pnlTone(o.net_pnl)} sub={`Komisyon: ${plainMoney(o.commission)}`} icon="💰" />
        <StatCard label="GENEL KAZANMA ORANI" value={winRate != null ? `%${winRate.toFixed(1)}` : "—"} tone={winRate != null && winRate >= 50 ? "text-neon-green" : "text-yellow-300"} sub={`${wins} Başarılı / ${total} Toplam`} icon="🎯" />
        <StatCard label="KAPANAN İŞLEMLER" value={String(total)} sub={`Açık Pozisyon: ${rl(o.open_positions)}`} icon="📈" />
        <StatCard label="HESAP BAKİYESİ" value={plainMoney(o.try_balance)} tone="text-white" sub="Paper cüzdan bakiyesi" icon="💼" />
      </div>

      {/* Radar ve Sinyal Başarı Kırılımı */}
      {breakdown && (
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-bunker-800 pb-3">
            <div>
              <h2 className="font-mono text-base font-black text-neon-green flex items-center gap-2">
                <span>🎯</span> RADAR BİLDİRİM &amp; HEDEF DOKUNUŞ BAŞARISI
              </h2>
              <p className="mt-0.5 text-xs text-bunker-muted">
                Kapanmış 1 dakikalık mumlar üzerinden ölçülen gerçek MFE ve hedefe ulaşma performansı.
              </p>
            </div>
            {overall?.success_rate != null && (
              <span className="rounded-full bg-neon-green/15 border border-neon-green/40 px-3 py-1 font-mono text-xs font-bold text-neon-green">
                Tüm Zamanlar Başarı: %{overall.success_rate.toFixed(1)}
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <StatCard label="HEDEFE ULAŞTI" value={String(breakdown.counts?.["TAMAMEN BAŞARILI"] || 0)} tone="text-neon-green" icon="✓" />
            <StatCard label="BAŞARILI" value={String(breakdown.counts?.["BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="KISMİ HAREKET" value={String(breakdown.counts?.["KISMİ"] || 0)} tone="text-yellow-300" />
            <StatCard label="BAŞARISIZ" value={String(breakdown.counts?.["BAŞARISIZ"] || 0)} tone="text-neon-red" icon="✗" />
            <StatCard label="BEKLİYOR" value={String((breakdown.counts?.["BEKLİYOR"] || 0) + (breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0))} sub="Ufku dolmayanlar" />
            <StatCard label="ÖLÇÜLEN BAŞARI" value={overall?.success_rate != null ? `%${overall.success_rate.toFixed(1)}` : "—"} tone="text-sky-300" sub={`${overall?.success_count ?? 0}/${overall?.evaluated ?? 0} Ölçülen`} />
          </div>

          {(breakdown.by_source || breakdown.multi_source) && (
            <div className="pt-3 border-t border-bunker-800/80 flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-bunker-muted">Kaynak Dağılımı:</span>
                {Object.entries(breakdown.by_source || {}).map(([src, count]) => (
                  <span key={src} className="flex items-center gap-1.5 bg-bunker-900 border border-bunker-800 rounded-lg px-2 py-1">
                    <SourceBadges sources={[src]} compact />
                    <span className="text-white font-bold">{String(count)}</span>
                  </span>
                ))}
              </div>

              {breakdown.multi_source && breakdown.multi_source.evaluated > 0 && (
                <div className="rounded-lg border border-sky-400/40 bg-sky-400/10 px-3 py-1 text-sky-300 font-bold">
                  ⚡ Çoklu Kaynak Teyidi: %{Number(breakdown.multi_source.success_rate ?? 0).toFixed(1)} Başarı ({breakdown.multi_source.success_count}/{breakdown.multi_source.evaluated})
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Otonom Paper Trade Performansı */}
      {autoPaperStats && (
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <div>
              <h2 className="font-mono text-base font-black text-white flex items-center gap-2">
                <span>🤖</span> OTONOM İŞLEM MOTORU PERFORMANSI
              </h2>
              <p className="mt-0.5 text-xs text-bunker-muted">
                Radar bildirimlerinden otomatik olarak açılan ve TP/SL/Breakeven ile yönetilen paper pozisyonlar.
              </p>
            </div>
            {avgOrderTry != null && (
              <span className="font-mono text-xs text-bunker-muted">Ort. Emir: ₺{avgOrderTry.toFixed(0)}</span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <StatCard label="TOPLAM İŞLEM" value={String(autoPaperStats.total)} />
            <StatCard label="AÇIK POZİSYON" value={String(autoPaperStats.open)} tone="text-yellow-300" />
            <StatCard label="KAPANMIŞ" value={String(autoPaperStats.closed)} />
            <StatCard label="OTONOM PNL" value={money(autoPaperStats.total_pnl_try)} tone={pnlTone(autoPaperStats.total_pnl_try)} />
            <StatCard label="KAZANMA ORANI" value={autoPaperStats.win_rate != null ? `%${autoPaperStats.win_rate.toFixed(1)}` : "—"} tone={autoPaperStats.win_rate >= 50 ? "text-neon-green" : "text-yellow-300"} />
            <StatCard label="KAZAN / KAYBET" value={`${autoPaperStats.winning} / ${autoPaperStats.losing}`} />
          </div>
        </section>
      )}

      {/* İki Kolonlu Alt Grid: Sembol Performansı ve Son Bildirimler */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sembol Performansı */}
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-3">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <h3 className="font-mono text-sm font-black text-white flex items-center gap-2">
              <span>📊</span> EN ÇOK İŞLEM YAPILAN SEMBOLLER
            </h3>
            <span className="font-mono text-xs text-bunker-muted">{symbols.length} Sembol</span>
          </div>

          {symbols.length === 0 ? (
            <p className="py-6 text-center text-sm text-bunker-muted font-mono">Henüz işlem geçmişi yok.</p>
          ) : (
            <div className="table-scroll max-h-[360px]">
              <table className="data-table table-compact">
                <thead>
                  <tr>
                    <th>Sembol</th>
                    <th className="text-right">İşlem</th>
                    <th className="text-right">Kazanma</th>
                    <th className="text-right">Net PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.slice(0, 10).map((s: any) => (
                    <tr key={s.symbol}>
                      <td><SymbolLink symbol={s.symbol} className="font-mono text-xs font-bold text-white hover:text-neon-green" /></td>
                      <td className="text-right tabular-nums font-mono text-xs text-white">{s.trade_count}</td>
                      <td className="text-right tabular-nums font-mono text-xs text-white">{s.win_rate == null ? "—" : `%${Number(s.win_rate).toFixed(1)}`}</td>
                      <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(s.net_pnl)}`}>{money(s.net_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Son Radar Bildirimleri */}
        <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-3">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <h3 className="font-mono text-sm font-black text-white flex items-center gap-2">
              <span>🔔</span> SON SİNYAL HEDEF DURUMLARI
            </h3>
            <button onClick={load} className="ui-button ui-button-secondary text-xs py-1 px-2.5">Tazele</button>
          </div>

          {notifications.length === 0 ? (
            <p className="py-6 text-center text-sm text-bunker-muted font-mono">Henüz bildirim kaydı yok.</p>
          ) : (
            <div className="table-scroll max-h-[360px]">
              <table className="data-table table-compact">
                <thead>
                  <tr>
                    <th>Zaman</th>
                    <th>Sembol</th>
                    <th>Hedef</th>
                    <th>Ölçülen MFE</th>
                    <th>Sonuç</th>
                  </tr>
                </thead>
                <tbody>
                  {notifications.slice(0, 10).map((n: any) => (
                    <tr key={`${n.id}-${n.symbol}-${n.detected_at}`}>
                      <td className="font-mono text-xs text-bunker-muted">{fmtDt(n.detected_at)}</td>
                      <td><SymbolLink symbol={n.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                      <td className={`font-mono text-xs ${n.target_pct ? "text-neon-green font-bold" : "text-bunker-muted"}`}>{n.target_pct ? `+${Number(n.target_pct).toFixed(1)}%` : "—"}</td>
                      <td className="font-mono text-xs text-white font-bold">{n.mfe_pct != null ? `%${Number(n.mfe_pct).toFixed(2)}` : "—"}</td>
                      <td>
                        {n.status === "TAMAMEN BAŞARILI" ? <Badge tone="ok">TAMAMEN</Badge>
                          : n.status === "BAŞARILI" ? <Badge tone="ok">BAŞARILI</Badge>
                          : n.status === "KISMİ" ? <Badge tone="warn">KISMİ</Badge>
                          : n.status === "BAŞARISIZ" ? <Badge tone="bad">BAŞARISIZ</Badge>
                          : <Badge>BEKLİYOR</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ==========================================================================
   2. RADAR TESPİTLERİ (USER RADAR TAB)
   ========================================================================== */
interface SymbolCount {
  symbol: string;
  count: number;
}
interface RadarBreakdown {
  counts?: Record<string, number>;
  evaluated?: number;
  success_count?: number;
  success_rate?: number | null;
  unique_symbols?: number;
  symbol_counts?: SymbolCount[];
  dominant_symbol?: string | null;
  dominant_symbol_count?: number;
  dominant_symbol_ratio?: number;
  dominant_symbol_warning?: boolean;
  by_source?: Record<string, number>;
  multi_source?: { evaluated: number; success_count: number; success_rate?: number | null };
}
interface RadarOverall {
  evaluated?: number;
  success_count?: number;
  success_rate?: number | null;
}

function UserRadarTab() {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [breakdown, setBreakdown] = useState<RadarBreakdown | null>(null);
  const [overall, setOverall] = useState<RadarOverall | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [day, setDay] = useState<string>(() => localDateInput());
  const [search, setSearch] = useState("");
  const [minScore, setMinScore] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<string>("detected_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("limit", "1000");
      params.set("day", day);
      const ntRes = await apiRequest(`${API_BASE}/api/reports/notifications?${params}`, { cache: "no-store" });
      const nt = await ntRes.json();
      if (ntRes.ok) {
        setNotifications(nt.notifications || []);
        setBreakdown(nt.breakdown || null);
        setOverall(nt.overall || null);
      } else {
        setNotifications([]);
        setBreakdown(null);
        setOverall(null);
        setError(nt.detail || "Radar tespitleri alınamadı");
      }
    } catch {
      setNotifications([]);
      setBreakdown(null);
      setOverall(null);
      setError("Radar tespitleri alınamadı");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setMinScore(d.effective_min_score != null ? Number(d.effective_min_score) : (d.min_score != null ? Number(d.min_score) : null)))
      .catch(() => undefined);
  }, []);

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(0);
  };

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    let rows = notifications;
    if (q) {
      rows = rows.filter((n: any) =>
        String(n.symbol || "").toUpperCase().includes(q) ||
        String(n.mode || "").toUpperCase().includes(q) ||
        String(n.status || "").toUpperCase().includes(q)
      );
    }
    const dir = sortDir === "asc" ? 1 : -1;
    const sorted = [...rows].sort((a: any, b: any) => {
      let av: any = a[sortKey];
      let bv: any = b[sortKey];
      if (sortKey === "time") {
        av = a.detected_at;
        bv = b.detected_at;
      }
      if (av == null) av = "";
      if (bv == null) bv = "";
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), "tr-TR") * dir;
    });
    return sorted;
  }, [notifications, search, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const SortHeader = ({ label, field }: { label: string; field: string }) => (
    <th className="cursor-pointer select-none" onClick={() => toggleSort(field)} title="Sıralama için tıklayın">
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey === field ? (
          <span className="text-neon-green">{sortDir === "asc" ? "▲" : "▼"}</span>
        ) : (
          <span className="text-bunker-600">⇅</span>
        )}
      </span>
    </th>
  );

  return (
    <div className="space-y-6">
      {/* Günlük Filtre ve KPI Kartları */}
      <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-bunker-800 pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <div>
              <p className="eyebrow text-neon-green">RAPOR GÜNÜ</p>
              <input
                type="date"
                value={day}
                onChange={(e) => { setDay(e.target.value); setPage(0); }}
                className="bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-sm text-white mt-1 focus:border-neon-green/50 outline-none"
              />
            </div>
            <div className="pt-4 flex gap-1.5">
              <button
                type="button"
                onClick={() => { setDay(localDateInput()); setPage(0); }}
                className="ui-button ui-button-secondary text-xs py-1.5 px-3"
              >
                Bugün
              </button>
              <button onClick={load} className="ui-button ui-button-primary text-xs py-1.5 px-3">
                Yenile
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-right">
              <p className="eyebrow text-bunker-muted">SEÇİLEN GÜN BAŞARI</p>
              <p className={`font-mono text-xl font-black ${breakdown?.success_rate != null && breakdown.success_rate >= 50 ? "text-neon-green" : "text-yellow-300"}`}>
                {breakdown?.success_rate != null ? `%${breakdown.success_rate.toFixed(1)}` : "—"}
              </p>
              <p className="text-[10px] text-bunker-muted font-mono">{breakdown ? `${breakdown.success_count}/${breakdown.evaluated} Ölçülen` : ""}</p>
            </div>

            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3 text-right">
              <p className="eyebrow text-bunker-muted">SİSTEM GENELİ</p>
              <p className={`font-mono text-xl font-black ${overall?.success_rate != null && overall.success_rate >= 50 ? "text-neon-green" : "text-sky-300"}`}>
                {overall?.success_rate != null ? `%${overall.success_rate.toFixed(1)}` : "—"}
              </p>
              <p className="text-[10px] text-bunker-muted font-mono">{overall ? `${overall.success_count}/${overall.evaluated} Ölçülen` : ""}</p>
            </div>
          </div>
        </div>

        {/* Günlük Kırılım */}
        {breakdown && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-1">
            <StatCard label="HEDEFE ULAŞTI" value={String(breakdown.counts?.["TAMAMEN BAŞARILI"] || 0)} tone="text-neon-green" icon="✓" />
            <StatCard label="BAŞARILI" value={String(breakdown.counts?.["BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="KISMİ" value={String(breakdown.counts?.["KISMİ"] || 0)} tone="text-yellow-300" />
            <StatCard label="BAŞARISIZ" value={String(breakdown.counts?.["BAŞARISIZ"] || 0)} tone="text-neon-red" icon="✗" />
            <StatCard label="BEKLİYOR" value={String((breakdown.counts?.["BEKLİYOR"] || 0) + (breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0))} sub="Ölçüm devam ediyor" />
            <StatCard label="FARKLI SEMBOL" value={String(breakdown.unique_symbols ?? 0)} sub={breakdown.dominant_symbol ? `Lider: ${breakdown.dominant_symbol}` : ""} />
          </div>
        )}
      </section>

      {/* Tablo ve Arama */}
      <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-bunker-800 pb-3">
          <div>
            <h2 className="font-mono text-base font-black text-neon-green flex items-center gap-2">
              <span>🎯</span> SİNYAL TESPİT VE SONUÇ LİSTESİ ({filtered.length})
            </h2>
            {minScore != null && (
              <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">
                Filtre: Yalnızca SKOR ≥ {Math.round(minScore)} olan teyitli bildirimler yer alır.
              </p>
            )}
          </div>

          <div className="relative">
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="Sembol, mod veya durum ara…"
              className="w-48 sm:w-60 bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-xs text-white placeholder-bunker-muted focus:border-neon-green/50 outline-none"
            />
            {search && (
              <button type="button" onClick={() => setSearch("")} className="absolute right-2 top-1.5 text-bunker-muted hover:text-white text-xs">✕</button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="py-12 text-center font-mono text-sm text-bunker-muted">
            <span className="animate-spin inline-block mr-2">⏳</span> Veriler yükleniyor…
          </div>
        ) : error ? (
          <div className="py-8 text-center font-mono text-sm text-neon-red">⚠ {error}</div>
        ) : pageRows.length === 0 ? (
          <div className="py-12 text-center font-mono text-sm text-bunker-muted">
            Bu tarih ve filtreye uyan radar tespiti bulunamadı.
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="data-table table-compact">
                <thead>
                  <tr>
                    <SortHeader label="Zaman" field="time" />
                    <SortHeader label="Sembol" field="symbol" />
                    <th>Tespit Kaynağı</th>
                    <SortHeader label="Giriş Fiyatı" field="price" />
                    <SortHeader label="Skor" field="score" />
                    <SortHeader label="Ufuk" field="horizon_minutes" />
                    <SortHeader label="Maksimum (MFE)" field="mfe_pct" />
                    <SortHeader label="Net Çıkış" field="net_pct" />
                    <th>Sonuç</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((n: any) => {
                    const dt = new Date(toMs(n.detected_at));
                    const timeStr = dt.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
                    const mfePct = n.mfe_pct != null ? Number(n.mfe_pct) : null;
                    const netPct = n.net_pct != null ? Number(n.net_pct) : null;
                    const mfeTone = mfePct != null ? (mfePct >= 0 ? "text-neon-green" : "text-neon-red") : "text-bunker-muted";

                    return (
                      <tr key={`${n.id}-${n.symbol}-${n.detected_at}`}>
                        <td className="font-mono text-xs text-bunker-muted whitespace-nowrap">
                          {timeStr}
                        </td>
                        <td>
                          <SymbolLink symbol={n.symbol} className="font-mono font-bold text-white hover:text-neon-green" />
                        </td>
                        <td>
                          <SourceBadges sources={n.sources} compact />
                        </td>
                        <td className="font-mono text-xs text-white">
                          {n.price != null ? `₺${Number(n.price).toLocaleString("tr-TR", { maximumFractionDigits: 6 })}` : "—"}
                        </td>
                        <td className="font-mono text-xs text-white font-bold">
                          {n.score != null ? Number(n.score).toFixed(1) : "—"}
                        </td>
                        <td className="font-mono text-xs text-bunker-muted">
                          {n.horizon_minutes ? `${n.horizon_minutes}dk` : "—"}
                        </td>
                        <td className={`font-mono text-xs font-bold ${mfeTone}`}>
                          {mfePct != null ? `+${mfePct.toFixed(2)}%` : "—"}
                        </td>
                        <td className={`font-mono text-xs font-bold ${netPct == null ? "text-bunker-muted" : netPct >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                          {netPct != null ? `${netPct >= 0 ? "+" : ""}${netPct.toFixed(2)}%` : "—"}
                        </td>
                        <td>
                          {n.status === "TAMAMEN BAŞARILI" ? <Badge tone="ok">TAMAMEN</Badge>
                            : n.status === "BAŞARILI" ? <Badge tone="ok">BAŞARILI</Badge>
                            : n.status === "KISMİ" ? <Badge tone="warn">KISMİ</Badge>
                            : n.status === "BAŞARISIZ" ? <Badge tone="bad">BAŞARISIZ</Badge>
                            : <Badge>BEKLİYOR</Badge>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Sayfalama */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-bunker-800">
              <p className="font-mono text-xs text-bunker-muted">
                Toplam {filtered.length} Tespit · Sayfa {page + 1} / {totalPages}
              </p>
              <div className="flex items-center gap-1.5">
                <button disabled={page <= 0} onClick={() => setPage(0)} className="ui-button ui-button-secondary text-xs py-1 px-2.5 disabled:opacity-30">« İlk</button>
                <button disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="ui-button ui-button-secondary text-xs py-1 px-2.5 disabled:opacity-30">‹ Önceki</button>
                <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} className="ui-button ui-button-secondary text-xs py-1 px-2.5 disabled:opacity-30">Sonraki ›</button>
                <button disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)} className="ui-button ui-button-secondary text-xs py-1 px-2.5 disabled:opacity-30">Son »</button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

/* ==========================================================================
   3. OTONOM POZİSYONLAR VE İŞLEMLER (USER POSITIONS TAB)
   ========================================================================== */
function UserPositionsTab() {
  const [positions, setPositions] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [posRes, apRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/positions`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/auto-paper/trades?status=closed&limit=50`, { cache: "no-store" }),
      ]);
      const [pos, ap] = await Promise.all([posRes.json(), apRes.json()]);
      if (posRes.ok) setPositions((pos.positions || []).filter((p: any) => String(p.strategy || "").toUpperCase() === "AUTO_PAPER"));
      if (apRes.ok) setTrades(ap.trades || []);
    } catch {
      setError("Pozisyon verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">Otonom işlemler yükleniyor…</div>;
  if (error) return <div className="card p-5 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-sm">⚠ {error}</div>;

  return (
    <div className="space-y-6">
      {/* Açık Otonom Pozisyonlar */}
      <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <h2 className="font-mono text-base font-black text-neon-green flex items-center gap-2">
            <span>⚡</span> AÇIK OTONOM POZİSYONLAR ({positions.length})
          </h2>
          <span className="font-mono text-xs text-bunker-muted">Anlık Takipte</span>
        </div>

        {positions.length === 0 ? (
          <p className="py-6 text-center text-sm text-bunker-muted font-mono">Şu an açıkta otonom işlem bulunmuyor.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Strateji</th>
                  <th className="text-right">Giriş Fiyatı</th>
                  <th className="text-right">Anlık Fiyat</th>
                  <th className="text-right">Net K/Z (₺)</th>
                  <th className="text-right">Net K/Z (%)</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p: any) => (
                  <tr key={p.symbol}>
                    <td><SymbolLink symbol={p.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-bunker-muted">{strategyLabel(p.strategy)}</td>
                    <td className="text-right tabular-nums font-mono text-xs text-white">₺{num(p.entry)}</td>
                    <td className="text-right tabular-nums font-mono text-xs text-white">₺{num(p.current)}</td>
                    <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(p.pnl_try)}`}>{money(p.pnl_try)}</td>
                    <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(p.pnl_pct)}`}>
                      {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${Number(p.pnl_pct).toFixed(2)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Kapanan Otonom İşlemler */}
      <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <h2 className="font-mono text-base font-black text-white flex items-center gap-2">
            <span>🏁</span> KAPANAN OTONOM İŞLEMLER ({trades.length})
          </h2>
          <span className="font-mono text-xs text-bunker-muted">Son 50 İşlem</span>
        </div>

        {trades.length === 0 ? (
          <p className="py-6 text-center text-sm text-bunker-muted font-mono">Henüz tamamlanan otonom işlem yok.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Kapanış Zamanı</th>
                  <th>Sembol</th>
                  <th>Strateji</th>
                  <th className="text-right">Gerçekleşen K/Z</th>
                  <th className="text-right">K/Z Yüzdesi</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t: any) => (
                  <tr key={t.id}>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDt(t.exit_time || t.entry_time)}</td>
                    <td><SymbolLink symbol={t.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-bunker-muted">{strategyLabel(t.strategy)}</td>
                    <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(t.pnl)}`}>{money(t.pnl)}</td>
                    <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(t.pnl_pct)}`}>
                      {t.pnl_pct != null ? `${t.pnl_pct >= 0 ? "+" : ""}${Number(t.pnl_pct).toFixed(2)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* ==========================================================================
   4. SEMBOL BAZLI RAPOR (SYMBOLS TAB)
   ========================================================================== */
function SymbolsTab() {
  const [symbols, setSymbols] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/symbols?limit=300`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setSymbols(data.symbols || []);
      } catch {
        setError("Sembol raporu alınamadı");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toUpperCase();
    if (!needle) return symbols;
    return symbols.filter((s: any) => String(s.symbol || "").includes(needle));
  }, [symbols, q]);

  if (loading) return <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">Sembol raporu yükleniyor…</div>;
  if (error) return <div className="card p-5 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-sm">⚠ {error}</div>;

  return (
    <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-bunker-800 pb-3">
        <div>
          <h2 className="font-mono text-base font-black text-white flex items-center gap-2">
            <span>📊</span> SEMBOL BAZLI PERFORMANS ({filtered.length})
          </h2>
          <p className="mt-0.5 text-xs text-bunker-muted">Kapanmış işlem kâr/zararı ve hız avcısı hedef dokunuş başarıları.</p>
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Sembol ara (örn: BTC)…"
          className="bg-bunker-900 border border-bunker-700 rounded-xl px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green/50 outline-none w-48"
        />
      </div>

      <div className="table-scroll">
        <table className="data-table table-compact">
          <thead>
            <tr>
              <th>Sembol</th>
              <th className="text-right">İşlem</th>
              <th className="text-right">Kazanma</th>
              <th className="text-right">Net PnL</th>
              <th className="text-right">Ort. MFE</th>
              <th className="text-right">Ort. DD</th>
              <th className="text-right">Radar Dokunuş</th>
              <th>Son İşlem</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s: any) => {
              const tr = rl(s.trade_count);
              const wins = rl(s.winning);
              return (
                <tr key={s.symbol}>
                  <td><SymbolLink symbol={s.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                  <td className="text-right tabular-nums font-mono text-xs text-white">{tr}</td>
                  <td className="text-right tabular-nums font-mono text-xs text-white">{tr > 0 ? `%${((wins / tr) * 100).toFixed(1)}` : "—"}</td>
                  <td className={`text-right tabular-nums font-mono text-xs font-bold ${pnlTone(s.net_pnl)}`}>{money(s.net_pnl)}</td>
                  <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">{pct(s.avg_mfe_pct)}</td>
                  <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">{pct(s.avg_dd_pct)}</td>
                  <td className="text-right tabular-nums font-mono text-xs font-bold text-neon-green">{s.velocity_touch_rate != null ? `%${Number(s.velocity_touch_rate).toFixed(0)}` : "—"}</td>
                  <td className="font-mono text-xs text-bunker-muted">{s.last_seen ? fmtDt(s.last_seen) : "—"}</td>
                </tr>
              );
            })}
            {filtered.length === 0 && <tr><td colSpan={8} className="py-8 text-center text-bunker-muted font-mono">Sembol bulunamadı.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ==========================================================================
   5. GELİŞMİŞ ANALİZLER (ADMIN ÖZEL: VELOCITY, LOG, LLM, LEARNING)
   ========================================================================== */
function AdvancedAdminTabs({ subTab, setSubTab }: { subTab: string; setSubTab: (s: string) => void }) {
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-2 border-b border-bunker-800">
      {[
        { id: "velocity", label: "⚡ Hız Avcısı Journal" },
        { id: "autonomous", label: "📋 Karar Günlüğü" },
        { id: "llm", label: "🧠 LLM Tahminleri" },
        { id: "learning", label: "🤖 Self-Learning" },
      ].map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => setSubTab(item.id)}
          className={`rounded-xl px-3 py-1.5 font-mono text-xs font-bold whitespace-nowrap transition-all ${
            subTab === item.id ? "bg-bunker-800 text-neon-green border border-neon-green/30" : "text-bunker-muted hover:text-white"
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function VelocityTab() {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/velocity?limit=40`, { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Hız avcısı raporu alınamadı");
        setReport(data);
      } catch (e: any) {
        setError(e.message || "Hız avcısı raporu alınamadı");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="card p-6 text-center font-mono text-xs text-bunker-muted">Yükleniyor…</div>;
  if (error) return <div className="card p-4 border-neon-red/40 text-neon-red font-mono text-xs">{error}</div>;

  const stats = report?.stats || {};
  const evaluated = rl(stats.evaluated);
  const touched = rl(stats.touched);
  const recent = report?.recent || [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="TOPLAM ADAY" value={String(rl(stats.total))} />
        <StatCard label="ÖLÇÜLEN" value={String(evaluated)} />
        <StatCard label="HEDEF DOKUNAN" value={`${touched}/${evaluated}`} tone="text-neon-green" />
        <StatCard label="DOKUNUŞ ORANI" value={evaluated ? `%${((touched / evaluated) * 100).toFixed(1)}` : "—"} tone="text-sky-300" />
      </div>

      <section className="card p-4 rounded-xl border border-bunker-800">
        <p className="eyebrow text-neon-green mb-3">SON TESPİTLER VE DOKUNUŞLAR</p>
        <div className="table-scroll max-h-[300px]">
          <table className="data-table table-compact">
            <thead>
              <tr><th>Zaman</th><th>Sembol</th><th>Hedef</th><th>MFE</th><th>Dokundu</th></tr>
            </thead>
            <tbody>
              {recent.map((c: any) => (
                <tr key={c.candidate_id}>
                  <td className="font-mono text-xs text-bunker-muted">{fmtDt(c.created_at)}</td>
                  <td><SymbolLink symbol={c.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                  <td className="font-mono text-xs text-neon-green">{c.target_pct != null ? `+${Number(c.target_pct).toFixed(2)}%` : "—"}</td>
                  <td className="font-mono text-xs text-white">{c.mfe_pct != null ? `%${Number(c.mfe_pct).toFixed(2)}` : "—"}</td>
                  <td>{c.touched_target ? <Badge tone="ok">EVET</Badge> : <Badge tone="bad">HAYIR</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function AutonomousTab() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/autonomous-log?limit=50`, { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Karar günlüğü alınamadı");
        setRows(data.rows || []);
      } catch (e: any) {
        setError(e.message || "Karar günlüğü alınamadı");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="card p-6 text-center font-mono text-xs text-bunker-muted">Yükleniyor…</div>;
  if (error) return <div className="card p-4 border-neon-red/40 text-neon-red font-mono text-xs">{error}</div>;

  return (
    <section className="card p-4 rounded-xl border border-bunker-800">
      <p className="eyebrow text-neon-green mb-3">OTONOM KARAR AKIŞI</p>
      <div className="table-scroll max-h-[350px]">
        <table className="data-table table-compact">
          <thead>
            <tr><th>Zaman</th><th>Sembol</th><th>Eylem</th><th>Fiyat</th><th>Neden</th></tr>
          </thead>
          <tbody>
            {rows.map((r: any, i: number) => (
              <tr key={`${r.timestamp}-${r.symbol}-${i}`}>
                <td className="font-mono text-xs text-bunker-muted">{fmtDt(r.timestamp)}</td>
                <td><SymbolLink symbol={r.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                <td className="font-mono text-xs text-white font-bold">{r.action}</td>
                <td className="font-mono text-xs text-bunker-muted">₺{num(r.price)}</td>
                <td className="font-mono text-xs text-bunker-muted truncate max-w-xs" title={r.reason}>{r.reason || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LlmTab() {
  const [forecasts, setForecasts] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/llm-forecasts`, { cache: "no-store" });
        const data = await res.json();
        if (res.ok) setForecasts(data);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="card p-6 text-center font-mono text-xs text-bunker-muted">Yükleniyor…</div>;
  if (!forecasts) return <div className="card p-4 font-mono text-xs text-bunker-muted">LLM tahmin verisi bulunamadı.</div>;

  const ev = rl(forecasts.evaluated_count);
  const ok = rl(forecasts.correct_count);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="ÖLÇÜLEN" value={String(ev)} />
        <StatCard label="DOĞRU TAHMİN" value={`${ok}/${ev}`} tone="text-neon-green" />
        <StatCard label="YÖN DOĞRULUĞU" value={ev ? pct(forecasts.directional_accuracy) : "—"} tone={accuracyTone(forecasts.directional_accuracy, true)} />
        <StatCard label="BEKLEYEN" value={String(rl(forecasts.pending_count))} />
      </div>
    </div>
  );
}

function SelfLearningTab() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/self-learning`, { cache: "no-store" });
        const body = await res.json();
        if (res.ok) setData(body);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="card p-6 text-center font-mono text-xs text-bunker-muted">Yükleniyor…</div>;
  if (!data) return <div className="card p-4 font-mono text-xs text-bunker-muted">Self-learning verisi bulunamadı.</div>;

  const learning = data?.learning || {};
  const lessons = data?.lessons || [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="ÖRNEKLEM" value={String(rl(learning.sample_size))} sub={learning.enabled ? "Aktif" : "Pasif"} />
        <StatCard label="STRATEJİLER" value={String((learning.by_strategy || []).length)} />
        <StatCard label="TEKRARLAYAN ZARAR" value={String((learning.repeated_loss_reasons || []).length)} tone="text-yellow-300" />
        <StatCard label="AKTİF DERSLER" value={String(lessons.length)} tone="text-neon-green" />
      </div>
    </div>
  );
}

/* ==========================================================================
   ANA SAYFA (REPORTS PAGE)
   ========================================================================== */
export default function ReportsPage() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [tab, setTab] = useState<"overview" | "radar" | "positions" | "symbols" | "advanced">("overview");
  const [advancedSubTab, setAdvancedSubTab] = useState("velocity");

  const MAIN_TABS = [
    { id: "overview", label: "📊 Performans Özeti", icon: "📊" },
    { id: "radar", label: "🎯 Sinyal & Hedef Başarısı", icon: "🎯" },
    { id: "positions", label: "💼 Otonom Pozisyonlar", icon: "💼" },
    { id: "symbols", label: "📈 Sembol Başarısı", icon: "📈" },
    ...(isAdmin ? [{ id: "advanced", label: "⚙️ Gelişmiş Teşhis", icon: "⚙️" }] : []),
  ];

  return (
    <main className="page-shell space-y-6">
      {/* Başlık Bölümü */}
      <div className="page-heading flex flex-wrap items-start justify-between gap-4 border-b border-bunker-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <p className="eyebrow text-neon-green">ANALİZ &amp; DOĞRULAMA</p>
            <span className="rounded-full bg-neon-green/10 border border-neon-green/30 px-2 py-0.5 text-[10px] font-mono text-neon-green font-bold">
              GERÇEK MUM DOĞRULAMASI
            </span>
          </div>
          <h1 className="font-mono text-2xl sm:text-3xl font-black text-white mt-1">Raporlama Merkezi</h1>
          <p className="mt-1 text-sm text-bunker-muted max-w-2xl">
            Tüm tespitlerin hedefe dokunma oranları (MFE), gerçekleşen net kâr/zararlar ve otonom sistem performansının şeffaf dökümü.
          </p>
        </div>
      </div>

      {/* Sekmeler */}
      <div className="flex items-center gap-2 overflow-x-auto border-b border-bunker-800 pb-2 no-scrollbar">
        {MAIN_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id as any)}
            className={`rounded-xl px-4 py-2.5 font-mono text-xs sm:text-sm font-bold transition-all whitespace-nowrap flex items-center gap-2 ${
              tab === item.id
                ? "bg-neon-green/15 text-neon-green border border-neon-green/40 shadow-sm"
                : "text-bunker-muted hover:text-white hover:bg-bunker-900"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Sekme İçerikleri */}
      {tab === "overview" && <OverviewTab />}
      {tab === "radar" && <UserRadarTab />}
      {tab === "positions" && <UserPositionsTab />}
      {tab === "symbols" && <SymbolsTab />}
      {tab === "advanced" && isAdmin && (
        <div className="space-y-4">
          <AdvancedAdminTabs subTab={advancedSubTab} setSubTab={setAdvancedSubTab} />
          {advancedSubTab === "velocity" && <VelocityTab />}
          {advancedSubTab === "autonomous" && <AutonomousTab />}
          {advancedSubTab === "llm" && <LlmTab />}
          {advancedSubTab === "learning" && <SelfLearningTab />}
        </div>
      )}
    </main>
  );
}
