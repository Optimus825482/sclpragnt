"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import SymbolLink from "../components/SymbolLink";

const money = (v?: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}₺`;

const num = (v?: number | null) => (v == null || !Number.isFinite(v) ? "—" : String(Number(v).toFixed(2)));
const pct = (v?: number | null, digits = 1) => (v == null || !Number.isFinite(v) ? "—" : `%${(Number(v) * 100).toFixed(digits)}`);
const fmtDt = (ts: number | null) => {
  if (!ts) return "—";
  const ms = ts < 10_000_000_000 ? ts * 1000 : ts;
  return new Date(ms).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const rl = (v: number | null | undefined) => (v == null ? 0 : v);

const STRATEGY_META: Record<string, string> = {
  BB_MFI_MEAN_REVERSION: "BB+MFI Dönüş",
  FISHER_M3_KERNEL_M5_EXACT_PAPER: "Fisher M3 + Kernel",
  VELOCITY: "Hız Avcısı",
  CHAT_PREDICTION: "Hız Avcısı (Otonom)",
  PUMP_MONITOR: "Pump Monitor",
  LLM_PAPER: "LLM Paper",
  SMA_CASCADE_SHADOW: "SMA Cascade",
};
const strategyLabel = (s?: string | null) => STRATEGY_META[s?.toUpperCase() || ""] || s || "Diğer";
const pnlTone = (v: number | null | undefined) => (rl(v) >= 0 ? "text-neon-green" : "text-neon-red");

function StatCard({ label, value, tone = "", sub }: { label: string; value: React.ReactNode; tone?: string; sub?: string }) {
  return (
    <section className="card">
      <p className="eyebrow">{label}</p>
      <p className={`mt-2 font-mono text-2xl font-bold ${tone}`}>{value}</p>
      {sub && <p className="mt-1 text-[10px] text-bunker-muted">{sub}</p>}
    </section>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "ok" | "warn" | "bad" | "neutral" }) {
  const map: Record<string, string> = {
    ok: "border-neon-green/50 bg-neon-green/10 text-neon-green",
    warn: "border-yellow-300/40 bg-yellow-300/10 text-yellow-300",
    bad: "border-neon-red/40 bg-neon-red/10 text-neon-red",
    neutral: "border-bunker-600 bg-bunker-800/50 text-bunker-muted",
  };
  return <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${map[tone]}`}>{children}</span>;
}

/* ---- Özet sekmesi ---- */
function OverviewTab() {
  const [overview, setOverview] = useState<any>(null);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [breakdown, setBreakdown] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [ovRes, ntRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/reports/overview`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/reports/notifications?limit=50`, { cache: "no-store" }),
      ]);
      const [ov, nt] = await Promise.all([ovRes.json(), ntRes.json()]);
      if (ovRes.ok) setOverview(ov);
      if (ntRes.ok) { setNotifications(nt.notifications || []); setBreakdown(nt.breakdown || null); }
      if (!ovRes.ok) setError(ov.detail || "Özet alınamadı");
    } catch {
      setError("Rapor verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading && !overview) return <section className="card text-bunker-muted">Raporlar yükleniyor…</section>;
  if (error && !overview) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  const o = overview?.overall || {};
  const strategies = overview?.strategies || [];
  const decisions = overview?.decision_summary || [];
  const wins = rl(o.winning);
  const total = rl(o.trade_count);
  const winRate = total > 0 ? (wins / total) * 100 : null;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="KAPANMIŞ İŞLEM" value={String(total)} />
        <StatCard label="NET PnL" value={money(o.net_pnl)} tone={pnlTone(o.net_pnl)} sub={`komisyon ${money(o.commission)}`} />
        <StatCard label="BAŞARI ORANI" value={winRate != null ? `%${winRate.toFixed(1)}` : "—"} tone={winRate != null && winRate >= 50 ? "text-neon-green" : "text-yellow-300"} />
        <StatCard label="AÇIK POZİSYON" value={String(rl(o.open_positions))} sub={`TRY ${money(o.try_balance)}`} />
      </div>
      {breakdown && (
        <section className="card">
          <p className="eyebrow text-neon-green">RADAR BİLDİRİM BAŞARI KIRILIMI</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="TAMAMEN BAŞARILI" value={String(breakdown.counts?.["TAMAMEN BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="BAŞARILI" value={String(breakdown.counts?.["BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="KISMİ" value={String(breakdown.counts?.["KISMİ"] || 0)} tone="text-yellow-300" />
            <StatCard label="BAŞARISIZ" value={String(breakdown.counts?.["BAŞARISIZ"] || 0)} tone="text-neon-red" />
            <StatCard label="BEKLİYOR" value={String((breakdown.counts?.["BEKLİYOR"] || 0) + (breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0))} sub={`ölçülemedi ${breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0}`} />
            <StatCard label="GENEL BAŞARI" value={breakdown.success_rate != null ? `%${breakdown.success_rate.toFixed(1)}` : "—"} tone={breakdown.success_rate != null && breakdown.success_rate >= 50 ? "text-neon-green" : "text-yellow-300"}
              sub={`${breakdown.success_count}/${breakdown.evaluated} ölçülen`} />
          </div>
          <p className="mt-2 font-mono text-[10px] text-bunker-muted">
            Başarı, kapanmış M1 mumlarıyla ölçülen gerçek MFE ve hedef dokunuşuna dayanır; ufku dolmayan/ölçülemeyen kayıtlar BEKLIYOR sayılır.
          </p>
        </section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <div className="flex justify-between">
            <p className="eyebrow text-neon-green">STRATEJİ PERFORMANSI</p>
            <span className="font-mono text-xs text-bunker-muted">{strategies.length} strateji</span>
          </div>
          {strategies.length === 0 ? (
            <p className="mt-3 text-sm text-bunker-muted">Henüz kapanmış işlem yok.</p>
          ) : (
            <div className="mt-3 table-scroll">
              <table className="data-table">
                <thead><tr><th>Strateji</th><th>İşlem</th><th>Başarı</th><th>Net PnL</th><th>Ort. MFE</th><th>Ort. DD</th></tr></thead>
                <tbody>
                  {strategies.map((s: any) => (
                    <tr key={s.strategy}>
                      <td className="font-mono text-xs text-white">{strategyLabel(s.strategy)}</td>
                      <td>{s.trade_count}</td>
                      <td className="font-mono text-xs text-white">%{Number(s.win_rate || 0).toFixed(1)}</td>
                      <td className={`font-mono text-xs ${pnlTone(s.net_pnl)}`}>{money(s.net_pnl)}</td>
                      <td className="font-mono text-xs text-bunker-muted">{pct(rl(s.avg_max_favorable))}</td>
                      <td className="font-mono text-xs text-bunker-muted">{pct(rl(s.avg_max_adverse))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card">
          <p className="eyebrow text-neon-green">KARAR DAĞILIMI</p>
          {decisions.length === 0 ? (
            <p className="mt-3 text-sm text-bunker-muted">Henüz karar kaydı yok.</p>
          ) : (
            <div className="mt-3 table-scroll">
              <table className="data-table">
                <thead><tr><th>Strateji</th><th>Karar</th><th>Sayı</th><th>Son</th></tr></thead>
                <tbody>
                  {decisions.map((d: any) => (
                    <tr key={`${d.strategy}-${d.decision}`}>
                      <td className="font-mono text-xs text-white">{strategyLabel(d.strategy)}</td>
                      <td className="font-mono text-xs text-bunker-muted">{d.decision}</td>
                      <td className="font-mono text-xs">{d.count}</td>
                      <td className="font-mono text-xs text-bunker-muted">{fmtDt(d.last_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>      <section className="card">
        <div className="flex items-center justify-between">
          <p className="eyebrow text-neon-green">SON RADAR BİLDİRİMLERİ</p>
          <button onClick={load} className="ui-button ui-button-secondary">⟳ Tazele</button>
        </div>
        {notifications.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Henüz bildirim yok.</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Zaman</th><th>Sembol</th><th>Mod</th><th>Hedef</th><th>Ölçülen MFE</th><th>Durum</th></tr></thead>
              <tbody>
                {notifications.map((n: any) => (
                  <tr key={`${n.id}-${n.symbol}-${n.detected_at}`}>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDt(n.detected_at)}</td>
                    <td><SymbolLink symbol={n.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-bunker-muted">{n.mode || "—"}</td>
                    <td className="font-mono text-xs text-neon-green">{n.target_pct ? `+%${Number(n.target_pct).toFixed(1)}` : "—"}</td>
                    <td className="font-mono text-xs text-white">{n.mfe_pct != null ? `%${Number(n.mfe_pct).toFixed(2)}` : "—"}</td>
                    <td>
                      {n.status === "TAMAMEN BAŞARILI" ? <Badge tone="ok">TAMAMEN</Badge>
                        : n.status === "BAŞARILI" ? <Badge tone="ok">BASARILI</Badge>
                        : n.status === "KISMİ" ? <Badge tone="warn">KISMI</Badge>
                        : n.status === "BAŞARISIZ" ? <Badge tone="bad">BASARISIZ</Badge>
                        : n.status === "ÖLÇÜLEMEDİ" ? <Badge tone="warn">OLCULEMEDI</Badge>
                        : <Badge>BEKLIYOR</Badge>}
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

/* ---- Sembol bazlı rapor sekmesi ---- */
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

  if (loading) return <section className="card text-bunker-muted">Sembol raporu yükleniyor…</section>;
  if (error) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-xs text-bunker-muted">{filtered.length} sembol · kapanmış işlem + velocity kalite birleşimi</p>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Sembol ara…" className="input w-52 font-mono text-sm" />
      </div>
      <section className="card">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Sembol</th><th>İşlem</th><th>Başarı</th><th>Net PnL</th>
                <th>Ort. MFE</th><th>Ort. DD</th><th>Vel. Değer</th><th>Vel. Dokunuş</th><th>Son İşlem</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s: any) => {
                const tr = rl(s.trade_count);
                const wins = rl(s.winning);
                return (
                  <tr key={s.symbol}>
                    <td><SymbolLink symbol={s.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td>{tr}</td>
                    <td className="font-mono text-xs text-white">{tr > 0 ? `%${((wins / tr) * 100).toFixed(1)}` : "—"}</td>
                    <td className={`font-mono text-xs ${pnlTone(s.net_pnl)}`}>{money(s.net_pnl)}</td>
                    <td className="font-mono text-xs text-bunker-muted">{pct(s.avg_mfe_pct)}</td>
                    <td className="font-mono text-xs text-bunker-muted">{pct(s.avg_dd_pct)}</td>
                    <td className="font-mono text-xs">{rl(s.velocity_evaluated) || "—"}</td>
                    <td className="font-mono text-xs text-white">{s.velocity_touch_rate != null ? `%${Number(s.velocity_touch_rate).toFixed(0)}` : "—"}</td>
                    <td className="font-mono text-xs text-bunker-muted">{s.last_seen ? fmtDt(s.last_seen) : "—"}</td>
                  </tr>
                );
              })}
              {filtered.length === 0 && <tr><td colSpan={9} className="py-6 text-center text-bunker-muted">Sembol bulunamadı.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <p className="font-mono text-[11px] text-bunker-muted">
        Ort. MFE ve Ort. DD kapanmış paper işlemlerindeki ortalama lehte/aleyhte hareketi; Vel. dokunuş oranı hız avcısı journalında ölçülmüş hedef dokunma başarısıdır.
      </p>
    </div>
  );
}
/* ---- Otonom geçmiş sekmesi ---- */
function AutonomousTab() {
  const [rows, setRows] = useState<any[]>([]);
  const [summary, setSummary] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [symbol, setSymbol] = useState("");
  const [strategy, setStrategy] = useState("");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(async (offset = 0, appliedSymbol = symbol, appliedStrategy = strategy) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("limit", "100");
      params.set("offset", String(offset));
      if (appliedSymbol) params.set("symbol", appliedSymbol);
      if (appliedStrategy) params.set("strategy", appliedStrategy);
      const res = await apiRequest(`${API_BASE}/api/reports/autonomous-log?${params}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRows(data.rows || []);
      setHasMore(Boolean(data.next_offset));
      const sres = await apiRequest(`${API_BASE}/api/reports/autonomous-decisions?limit=80${appliedSymbol ? `&symbol=${appliedSymbol}` : ""}${appliedStrategy ? `&strategy=${appliedStrategy}` : ""}`, { cache: "no-store" });
      if (sres.ok) {
        const sdata = await sres.json();
        setSummary(sdata.summary || []);
      }
    } catch {
      setError("Otonom işlem geçmişi alınamadı");
    } finally {
      setLoading(false);
    }
  }, [symbol, strategy]);

  useEffect(() => { load(0, symbol, strategy); }, [load, symbol, strategy]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input value={symbol} onChange={(e) => { setSymbol(e.target.value); setPage(0); }} placeholder="Sembol" className="input w-40 font-mono text-sm" />
        <input value={strategy} onChange={(e) => { setStrategy(e.target.value); setPage(0); }} placeholder="Strateji" className="input w-44 font-mono text-sm" />
        {loading && <span className="ml-auto font-mono text-xs text-bunker-muted">Yükleniyor…</span>}
      </div>
      {error && <section className="card border-neon-red/40 text-neon-red">{error}</section>}
      <section className="card">
        <p className="eyebrow text-neon-green">OTONOM KARAR AKIŞI ({rows.length})</p>
        <div className="mt-3 table-scroll">
          <table className="data-table">
            <thead><tr><th>Zaman</th><th>Sembol</th><th>Eylem</th><th>Fiyat</th><th>Strateji</th><th>Neden</th></tr></thead>
            <tbody>
              {rows.map((r: any, i: number) => (
                <tr key={`${r.timestamp}-${r.symbol}-${i}`}>
                  <td className="font-mono text-xs text-bunker-muted">{fmtDt(r.timestamp)}</td>
                  <td><SymbolLink symbol={r.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                  <td className="font-mono text-xs text-white">{r.action}</td>
                  <td className="font-mono text-xs text-bunker-muted">{num(r.price)}</td>
                  <td className="font-mono text-xs text-bunker-muted">{strategyLabel(r.strategy)}</td>
                  <td className="max-w-60 truncate font-mono text-xs text-bunker-muted" title={r.reason}>{r.reason || "—"}</td>
                </tr>
              ))}
              {!loading && rows.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-bunker-muted">Otonom karar kaydı yok.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex items-center justify-between">
          <button onClick={() => { setPage(Math.max(0, page - 1)); load((page - 1) * 100, symbol, strategy); }} disabled={page === 0}
            className="ui-button ui-button-secondary disabled:opacity-40">← ÖNCEKİ</button>
          <span className="font-mono text-xs text-bunker-muted">Sayfa {page + 1}</span>
          <button onClick={() => { setPage(page + 1); load((page + 1) * 100, symbol, strategy); }} disabled={!hasMore}
            className="ui-button ui-button-secondary disabled:opacity-40">SONRAKİ →</button>
        </div>
      </section>
      <section className="card">
        <p className="eyebrow text-neon-green">KARAR DAĞILIMI ({summary.length})</p>
        {summary.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Karar özeti yok.</p>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {summary.map((d: any, i: number) => (
              <div key={`${d.strategy}-${d.decision}-${i}`} className="rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-white">{strategyLabel(d.strategy)}</span>
                  <span className="font-mono text-lg text-neon-green">{d.count}</span>
                </div>
                <p className="font-mono text-[10px] text-bunker-muted">{d.decision}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
/* ---- Hız Avcısı Journal sekmesi ---- */
function VelocityTab() {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
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
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <section className="card text-bunker-muted">Hız avcısı raporu yükleniyor…</section>;
  if (error) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  const stats = report?.stats || {};
  const evaluated = rl(stats.evaluated);
  const touched = rl(stats.touched);
  const pattern = report?.pattern_hit_rates || {};
  const recent = report?.recent || [];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="TOPLAM ADAY" value={String(rl(stats.total))} />
        <StatCard label="ÖLÇÜLEN" value={String(evaluated)} />
        <StatCard label="HEDEF DOKUNAN" value={`${touched}/${evaluated}`} tone="text-neon-green" />
        <StatCard label="DOKUNUŞ ORANI" value={evaluated ? `%${((touched / evaluated) * 100).toFixed(1)}` : "—"} tone="text-sky-300"
          sub={`ort MFE ${pct(stats.average_mfe_pct, 3)} · geçenler %${stats.passing_hit_rate != null ? (stats.passing_hit_rate * 100).toFixed(1) : "—"}`} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <p className="eyebrow text-neon-green">PROFİL BAŞARISI</p>
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Profil</th><th>Geçen</th><th>Dokunma Oranı</th></tr></thead>
              <tbody>
                {Object.entries(report?.stats_by_profile || {}).map(([k, v]: any) => (
                  <tr key={k}>
                    <td className="font-mono text-xs text-white">{k === "5m" ? "5 DK · %2" : "15 DK · %3"}</td>
                    <td>{v.passing_count}</td>
                    <td className="font-mono text-xs text-white">{v.passing_hit_rate != null ? `%${(v.passing_hit_rate * 100).toFixed(1)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="card">
          <p className="eyebrow text-neon-green">PATTERN KIRILIMI</p>
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Alt grup</th><th>Değer</th><th>Dokunan</th><th>Oran</th></tr></thead>
              <tbody>
                {Object.entries(pattern).filter(([k]) => k !== "leading").map(([k, v]: any) => (
                  <tr key={k}>
                    <td className="font-mono text-xs text-white">{k}</td>
                    <td>{v.evaluated}</td>
                    <td>{v.touched}</td>
                    <td className="font-mono text-xs text-white">{v.hit_rate != null ? `%${(v.hit_rate * 100).toFixed(1)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <section className="card">
        <p className="eyebrow text-neon-green">SON ADAYLAR</p>
        {recent.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Henüz ölçülmüş aday yok.</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Zaman</th><th>Sembol</th><th>Hedef</th><th>MFE</th><th>Dokundu</th><th>Durum</th></tr></thead>
              <tbody>
                {recent.map((c: any) => (
                  <tr key={c.candidate_id}>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDt(c.created_at)}</td>
                    <td><SymbolLink symbol={c.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-neon-green">+%{Number(c.target_pct || 0).toFixed(2)}</td>
                    <td className="font-mono text-xs text-white">{c.mfe_pct != null ? `%${Number(c.mfe_pct).toFixed(2)}` : "—"}</td>
                    <td>{c.touched_target ? <Badge tone="ok">EVET</Badge> : c.status === "evaluated" ? <Badge tone="bad">HAYIR</Badge> : <Badge>—</Badge>}</td>
                    <td className="font-mono text-xs text-bunker-muted">{c.status}</td>
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
/* ---- LLM tahminleri sekmesi ---- */
function LlmTab() {
  const [forecasts, setForecasts] = useState<any>(null);
  const [chat, setChat] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [fRes, cRes] = await Promise.all([
          apiRequest(`${API_BASE}/api/reports/llm-forecasts`, { cache: "no-store" }),
          apiRequest(`${API_BASE}/api/reports/llm-chat-forecasts`, { cache: "no-store" }),
        ]);
        const [f, c] = await Promise.all([fRes.json(), cRes.json()]);
        if (fRes.ok) setForecasts(f);
        if (cRes.ok) setChat(c);
        if (!fRes.ok && !cRes.ok) throw new Error("LLM raporları alınamadı");
      } catch {
        setError("LLM raporları alınamadı");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <section className="card text-bunker-muted">LLM raporları yükleniyor…</section>;
  if (error && !forecasts && !chat) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  const Legend = (r: any) => {
    const ev = rl(r?.evaluated_count);
    const ok = rl(r?.correct_count);
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="ÖLÇÜLEN" value={String(ev)} />
        <StatCard label="DOĞRU" value={`${ok}/${ev}`} />
        <StatCard label="YÖN DOĞRULUĞU" value={ev ? pct(r?.directional_accuracy) : "—"} tone={rl(r?.directional_accuracy) >= 0.55 ? "text-neon-green" : "text-yellow-300"} />
        <StatCard label="BEKLEYEN" value={String(rl(r?.pending_count))} />
      </div>
    );
  };

  const HorizTable = ({ horizons }: { horizons: any[] }) => (
    <section className="card">
      <p className="eyebrow text-neon-green">UFUK BAZLI BAŞARI</p>
      <div className="mt-3 table-scroll">
        <table className="data-table">
          <thead><tr><th>Ufuk</th><th>Ölçülen</th><th>Doğru</th><th>Yön Doğruluğu</th><th>Ort. Hareket</th><th>Bekleyen</th></tr></thead>
          <tbody>
            {(horizons || []).map((h: any) => (
              <tr key={h.horizon_minutes}>
                <td className="font-mono text-xs text-white">{h.horizon_minutes} dk</td>
                <td>{h.evaluated_count || 0}</td>
                <td>{h.correct_count || 0}</td>
                <td className={`font-mono text-xs ${rl(h.directional_accuracy) >= 0.55 ? "text-neon-green" : "text-neon-red"}`}>{pct(h.directional_accuracy)}</td>
                <td className="font-mono text-xs text-bunker-muted">{pct(h.average_return_pct)}</td>
                <td>{h.pending_count || 0}</td>
              </tr>
            ))}
            {(horizons || []).length === 0 && <tr><td colSpan={6} className="py-5 text-center text-bunker-muted">Henüz veri yok.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );

  const RecentList = ({ recent }: { recent: any[] }) => (
    <section className="card">
      <p className="eyebrow text-neon-green">SON TAHMİNLER ({recent.length})</p>
      {recent.length === 0 ? (
        <p className="mt-3 text-sm text-bunker-muted">Henüz tahmin yok.</p>
      ) : (
        <div className="mt-3 table-scroll">
          <table className="data-table">
            <thead><tr><th>Zaman</th><th>Sembol</th><th>Ufuk</th><th>Yön</th><th>Güven</th><th>Sonuç</th></tr></thead>
            <tbody>
              {recent.slice(0, 20).map((r: any) => (
                <tr key={r.forecast_id}>
                  <td className="font-mono text-xs text-bunker-muted">{fmtDt(r.created_at)}</td>
                  <td><SymbolLink symbol={r.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                  <td className="font-mono text-xs">{r.horizon_minutes} dk</td>
                  <td className="font-mono text-xs text-white">{r.direction === "up" ? "YUKARI" : r.direction === "down" ? "AŞAĞI" : "YATAY"}</td>
                  <td className="font-mono text-xs text-bunker-muted">%{Math.round(rl(r.confidence))}</td>
                  <td>
                    {r.status === "evaluated"
                      ? (r.direction_correct ? <Badge tone="ok">DOĞRU</Badge> : <Badge tone="bad">YANLIŞ</Badge>)
                      : <Badge>BEKLIYOR</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );

  return (
    <div className="space-y-5">
      {forecasts && (
        <>
          <div>
            <p className="eyebrow text-neon-green mb-2">YORUM TAHMİNLERİ (LLM)</p>
            <Legend {...forecasts} />
          </div>
          <HorizTable horizons={forecasts.horizons || []} />
        </>
      )}
      {chat && (
        <>
          <div className="mt-2">
            <p className="eyebrow text-sky-300 mb-2">CHAT ADAY TAHMİNLERİ (5m / 15m)</p>
            <Legend {...chat} />
          </div>
          <HorizTable horizons={chat.horizons || []} />
          <div className="mt-2"><RecentList recent={chat.recent || []} /></div>
        </>
      )}
      {!forecasts && !chat && <section className="card text-bunker-muted">LLM tahmin verisi mevcut değil.</section>}
    </div>
  );
}
/* ---- Self-learning sekmesi ---- */
function SelfLearningTab() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiRequest(`${API_BASE}/api/reports/self-learning`, { cache: "no-store" });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || "Self-learning raporu alınamadı");
        setData(body);
      } catch (e: any) {
        setError(e.message || "Self-learning raporu alınamadı");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <section className="card text-bunker-muted">Self-learning özeti yükleniyor…</section>;
  if (error) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  const learning = data?.learning || {};
  const lessons = data?.lessons || [];
  const ml = data?.ml_artifact;
  const vel = data?.velocity_patterns || {};

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="ÖRNEKLEM" value={String(rl(learning.sample_size))} sub={learning.enabled ? "aktif" : "pasif"} />
        <StatCard label="STRATEJİ ÇIKARIMI" value={String((learning.by_strategy || []).length)} />
        <StatCard label="TEKRARLAYAN ZARAR" value={String((learning.repeated_loss_reasons || []).length)} tone="text-yellow-300" />
        <StatCard label="AKTİF DERS" value={String(lessons.length)} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card">
          <p className="eyebrow text-neon-green">STRATEJİ ÖĞRENME BAĞLAMI</p>
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Strateji</th><th>İşlem</th><th>Başarı</th><th>Net PnL</th><th>PF</th></tr></thead>
              <tbody>
                {(learning.by_strategy || []).map((s: any) => (
                  <tr key={s.strategy}>
                    <td className="font-mono text-xs text-white">{strategyLabel(s.strategy)}</td>
                    <td>{s.trades}</td>
                    <td className="font-mono text-xs text-white">%{Number(s.win_rate_pct || 0).toFixed(1)}</td>
                    <td className={`font-mono text-xs ${pnlTone(s.net_pnl)}`}>{money(s.net_pnl)}</td>
                    <td className="font-mono text-xs text-bunker-muted">{s.profit_factor != null ? s.profit_factor.toFixed(2) : "—"}</td>
                  </tr>
                ))}
                {(learning.by_strategy || []).length === 0 && <tr><td colSpan={5} className="py-5 text-center text-bunker-muted">Öğrenme örneği yok.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
        <section className="card">
          <p className="eyebrow text-neon-green">TEKRARLAYAN ZARAR NEDENLERİ</p>
          {(learning.repeated_loss_reasons || []).length === 0 ? (
            <p className="mt-3 text-sm text-bunker-muted">Kaydedilmiş tekrarlayan zarar nedeni yok.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {(learning.repeated_loss_reasons || []).map((r: any, i: number) => (
                <div key={`${r.value}-${i}`} className="rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-2 flex justify-between">
                  <span className="font-mono text-xs text-white">{r.value}</span>
                  <span className="font-mono text-xs text-neon-red">{r.count}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <p className="eyebrow text-neon-green">DOĞRULANMIŞ DERSLER</p>
        {lessons.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Henüz doğrulanmış ders yok.</p>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            {lessons.map((l: any) => (
              <div key={l.lesson_key || l.id} className="rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-white">{l.symbol || "GENEL"} · {l.horizon_minutes}dk</span>
                  <Badge tone={l.status === "active" ? "ok" : "warn"}>{l.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-bunker-muted">{l.lesson || "—"}</p>
                {l.holdout_accuracy != null && (
                  <p className="mt-1 font-mono text-[10px] text-bunker-muted">
                    in-sample %{Number((l.in_sample_accuracy || 0) * 100).toFixed(0)} · holdout %{Number((l.holdout_accuracy || 0) * 100).toFixed(0)} · {l.sample_size} örnek
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <p className="eyebrow text-neon-green">ML MODEL DURUMU</p>
        {ml ? (
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            <StatCard label="ÖRNEK" value={String(rl(ml.sample_count))} />
            <StatCard label="SEMBOL" value={String(rl(ml.symbol_count))} />
            <StatCard label="JOURNAL" value={String(rl(ml.journal_sample_count))} />
            <StatCard label="FEATURE" value={String(ml.feature_version || "—")} />
            <StatCard label="DURUM" value={String(ml.status || "—")} tone="text-sky-300" />
            <StatCard label="OLUŞTURMA" value={fmtDt(ml.created_at)} />
          </div>
        ) : (
          <p className="mt-3 text-sm text-bunker-muted">Henüz ML modeli üretilmedi.</p>
        )}
      </section>

      <section className="card">
        <p className="eyebrow text-neon-green">VELOCITY PATTERN KIRILIMI</p>
        <div className="mt-3 table-scroll">
          <table className="data-table">
            <thead><tr><th>Grup</th><th>Değerlendirilen</th><th>Dokunan</th><th>Oran</th></tr></thead>
            <tbody>
              {Object.entries(vel).filter(([k]) => k !== "leading").map(([k, v]: any) => (
                <tr key={k}>
                  <td className="font-mono text-xs text-white">{k}</td>
                  <td>{v.evaluated}</td>
                  <td>{v.touched}</td>
                  <td className="font-mono text-xs text-white">{v.hit_rate != null ? `%${(v.hit_rate * 100).toFixed(1)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ---- Kullanıcı: Radar Tespitleri sekmesi (DataTable) ---- */
function UserRadarTab() {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [breakdown, setBreakdown] = useState<any>(null);
  const [overall, setOverall] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [day, setDay] = useState<string>(() => {
    const d = new Date();
    return d.toISOString().slice(0, 10);
  });
  const [search, setSearch] = useState("");
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
        setError(nt.detail || "Radar tespitleri alinamadi");
      }
    } catch {
      setError("Radar tespitleri alinamadi");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => { load(); }, [load]);

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
      if (sortKey === "date" || sortKey === "time") {
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
    <th
      className="cursor-pointer select-none"
      onClick={() => toggleSort(field)}
      title="Siralama icin tiklayin"
    >
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

  if (loading) return <section className="card text-bunker-muted">Radar tespitleri yukleniyor...</section>;
  if (error) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  return (
    <div className="space-y-5">
      {/* Tarih secici + Genel basari */}
      <section className="card">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow text-neon-green">RAPOR TARIHI</p>
            <input
              type="date"
              value={day}
              onChange={(e) => { setDay(e.target.value); setPage(0); }}
              className="input mt-2 w-auto font-mono text-sm"
            />
          </div>
          <div className="flex flex-wrap gap-3">
            <StatCard
              label="SECILEN GUN BASARI"
              value={breakdown?.success_rate != null ? `%${breakdown.success_rate.toFixed(1)}` : "—"}
              tone={breakdown?.success_rate != null && breakdown.success_rate >= 50 ? "text-neon-green" : "text-yellow-300"}
              sub={breakdown ? `${breakdown.success_count}/${breakdown.evaluated} olculen` : ""}
            />
            <StatCard
              label="SISTEM GENEL BASARI"
              value={overall?.success_rate != null ? `%${overall.success_rate.toFixed(1)}` : "—"}
              tone={overall?.success_rate != null && overall.success_rate >= 50 ? "text-neon-green" : "text-yellow-300"}
              sub={overall ? `${overall.success_count}/${overall.evaluated} olculen` : ""}
            />
          </div>
        </div>
      </section>

      {/* Secilen gun basari kirilimi */}
      {breakdown && (
        <section className="card">
          <p className="eyebrow text-neon-green">GUNLUK BASARI KIRILIMI</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="TAMAMEN" value={String(breakdown.counts?.["TAMAMEN BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="BASARILI" value={String(breakdown.counts?.["BAŞARILI"] || 0)} tone="text-neon-green" />
            <StatCard label="KISMI" value={String(breakdown.counts?.["KISMİ"] || 0)} tone="text-yellow-300" />
            <StatCard label="BASARISIZ" value={String(breakdown.counts?.["BAŞARISIZ"] || 0)} tone="text-neon-red" />
            <StatCard label="BEKLIYOR" value={String((breakdown.counts?.["BEKLİYOR"] || 0) + (breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0))} sub={`olculemedi ${breakdown.counts?.["ÖLÇÜLEMEDİ"] || 0}`} />
            <StatCard label="GENEL BASARI" value={breakdown.success_rate != null ? `%${breakdown.success_rate.toFixed(1)}` : "—"} tone="text-sky-300"
              sub={`${breakdown.success_count}/${breakdown.evaluated} olculen`} />
          </div>
          <p className="mt-2 font-mono text-[10px] text-bunker-muted">
            Basari, kapannis M1 mumlariyla olculen gercek MFE ve hedef dokunusuna dayanir.
          </p>
        </section>
      )}

      {/* DataTable */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="eyebrow text-neon-green">RADAR TESPITLERI ({filtered.length})</p>
          <div className="flex items-center gap-2">
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="Sembol, mod, durum ara..."
              className="input w-56 font-mono text-sm"
            />
            <button onClick={load} className="ui-button ui-button-secondary">⟳ Tazele</button>
          </div>
        </div>
        {pageRows.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Eslesen tespit yok.</p>
        ) : (
          <>
            <div className="mt-3 table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <SortHeader label="Tarih" field="date" />
                    <SortHeader label="Saat" field="time" />
                    <SortHeader label="Sembol" field="symbol" />
                    <SortHeader label="Anlik Fiyat" field="price" />
                    <SortHeader label="Hedef Fiyat" field="expected_price" />
                    <SortHeader label="Hedef %" field="target_pct" />
                    <SortHeader label="Skor" field="score" />
                    <SortHeader label="ML Olasilik" field="ml_hit_probability" />
                    <SortHeader label="Ufuk" field="horizon_minutes" />
                    <SortHeader label="Sonuc (Max MFE)" field="mfe_pct" />
                    <th>Durum</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((n: any) => {
                    const dt = new Date(n.detected_at * 1000);
                    const dateStr = dt.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric" });
                    const timeStr = dt.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
                    const mfePct = n.mfe_pct != null ? Number(n.mfe_pct) : null;
                    const tgtPct = n.target_pct != null ? Number(n.target_pct) : null;
                    const mfeTone = mfePct != null ? (mfePct >= 0 ? "text-neon-green" : "text-neon-red") : "text-bunker-muted";
                    return (
                      <tr key={`${n.id}-${n.symbol}-${n.detected_at}`}>
                        <td className="font-mono text-xs text-bunker-muted">{dateStr}</td>
                        <td className="font-mono text-xs text-bunker-muted">{timeStr}</td>
                        <td><SymbolLink symbol={n.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                        <td className="font-mono text-xs text-white">{n.price != null ? Number(n.price).toLocaleString("tr-TR", { maximumFractionDigits: 6 }) : "—"}</td>
                        <td className="font-mono text-xs text-neon-green">{n.expected_price != null ? Number(n.expected_price).toLocaleString("tr-TR", { maximumFractionDigits: 6 }) : "—"}</td>
                        <td className="font-mono text-xs text-neon-green">{tgtPct != null ? `+%${tgtPct.toFixed(1)}` : "—"}</td>
                        <td className="font-mono text-xs text-white">{n.score != null ? Number(n.score).toFixed(2) : "—"}</td>
                        <td>
                          {n.ml_hit_probability != null ? (
                            <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${Number(n.ml_hit_probability) >= 0.6 ? 'border-neon-green/40 bg-neon-green/10 text-neon-green' : Number(n.ml_hit_probability) >= 0.45 ? 'border-yellow-300/40 bg-yellow-300/10 text-yellow-300' : 'border-neon-red/40 bg-neon-red/10 text-neon-red'}`}>
                              %{(Number(n.ml_hit_probability) * 100).toFixed(0)}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="font-mono text-xs text-bunker-muted">{n.horizon_minutes ? `${n.horizon_minutes}dk` : "—"}</td>
                        <td className={`font-mono text-xs ${mfeTone}`}>{mfePct != null ? `%${mfePct.toFixed(2)}` : "—"}</td>
                        <td>
                          {n.status === "TAMAMEN BAŞARILI" ? <Badge tone="ok">TAMAMEN</Badge>
                            : n.status === "BAŞARILI" ? <Badge tone="ok">BASARILI</Badge>
                            : n.status === "KISMİ" ? <Badge tone="warn">KISMI</Badge>
                            : n.status === "BAŞARISIZ" ? <Badge tone="bad">BASARISIZ</Badge>
                            : n.status === "ÖLÇÜLEMEDİ" ? <Badge tone="warn">OLCULEMEDI</Badge>
                            : <Badge>BEKLIYOR</Badge>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-xs text-bunker-muted">
                {filtered.length} kayit · Sayfa {page + 1}/{totalPages}
              </p>
              <div className="flex items-center gap-1">
                <button disabled={page <= 0} onClick={() => setPage(0)} className="ui-button ui-button-secondary disabled:opacity-40">« Ilk</button>
                <button disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="ui-button ui-button-secondary disabled:opacity-40">‹ Onceki</button>
                <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} className="ui-button ui-button-secondary disabled:opacity-40">Sonraki ›</button>
                <button disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)} className="ui-button ui-button-secondary disabled:opacity-40">Son »</button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

/* ---- Kullanıcı: Otonom Pozisyonlar sekmesi ---- */
function UserPositionsTab() {
  const [positions, setPositions] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [posRes, trRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/positions`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/trades?limit=50`, { cache: "no-store" }),
      ]);
      const [pos, tr] = await Promise.all([posRes.json(), trRes.json()]);
      if (posRes.ok) setPositions(pos.positions || []);
      if (trRes.ok) setTrades((tr.trades || []).filter((t: any) => /CHAT_PREDICTION|VELOCITY|PUMP_MONITOR|LLM_PAPER/.test(String(t.strategy || "").toUpperCase())));
    } catch {
      setError("Pozisyon verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <section className="card text-bunker-muted">Otonom pozisyonlar yükleniyor…</section>;
  if (error) return <section className="card border-neon-red/40 text-neon-red">{error}</section>;

  return (
    <div className="space-y-5">
      <section className="card">
        <p className="eyebrow text-neon-green">AÇIK OTONOM POZİSYONLAR ({positions.length})</p>
        {positions.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Şu an açık otonom pozisyon yok.</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Sembol</th><th>Strateji</th><th>Giriş</th><th>Güncel</th><th>PnL</th><th>PnL %</th></tr></thead>
              <tbody>
                {positions.map((p: any) => (
                  <tr key={p.symbol}>
                    <td><SymbolLink symbol={p.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-bunker-muted">{strategyLabel(p.strategy)}</td>
                    <td className="font-mono text-xs text-white">{num(p.entry)}</td>
                    <td className="font-mono text-xs text-white">{num(p.current)}</td>
                    <td className={`font-mono text-xs ${pnlTone(p.pnl_try)}`}>{money(p.pnl_try)}</td>
                    <td className={`font-mono text-xs ${pnlTone(p.pnl_pct)}`}>{p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${Number(p.pnl_pct).toFixed(2)}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <p className="eyebrow text-neon-green">KAPANAN OTONOM İŞLEMLER ({trades.length})</p>
        {trades.length === 0 ? (
          <p className="mt-3 text-sm text-bunker-muted">Henüz kapanan otonom işlem yok.</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead><tr><th>Zaman</th><th>Sembol</th><th>Strateji</th><th>PnL</th><th>PnL %</th></tr></thead>
              <tbody>
                {trades.map((t: any) => (
                  <tr key={t.id}>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDt(t.exit_time || t.entry_time)}</td>
                    <td><SymbolLink symbol={t.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="font-mono text-xs text-bunker-muted">{strategyLabel(t.strategy)}</td>
                    <td className={`font-mono text-xs ${pnlTone(t.pnl)}`}>{money(t.pnl)}</td>
                    <td className={`font-mono text-xs ${pnlTone(t.pnl_pct)}`}>{t.pnl_pct != null ? `${t.pnl_pct >= 0 ? "+" : ""}${Number(t.pnl_pct).toFixed(2)}%` : "—"}</td>
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

/* ---- Sayfa çerçevesi + sekmeler ---- */
const ADMIN_TABS = [
  { id: "radar", label: "RADAR TESPİTLERİ" },
  { id: "positions", label: "OTONOM POZİSYONLAR" },
  { id: "overview", label: "ÖZET" },
  { id: "symbols", label: "SEMBOL BAZLI" },
  { id: "autonomous", label: "OTONOM GEÇMİŞ" },
  { id: "velocity", label: "HIZ AVCISI" },
  { id: "llm", label: "LLM TAHMİN" },
  { id: "learning", label: "SELF-LEARNING" },
];
const USER_TABS = [
  { id: "radar", label: "RADAR TESPİTLERİ" },
  { id: "positions", label: "OTONOM POZİSYONLAR" },
];

export default function ReportsPage() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const tabs = isAdmin ? ADMIN_TABS : USER_TABS;
  const [tab, setTab] = useState(isAdmin ? "overview" : "radar");
  useEffect(() => {
    if (!tabs.some((t) => t.id === tab)) setTab(isAdmin ? "overview" : "radar");
  }, [role]);

  return (
      <main className="page-shell">
        <div className="page-heading flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow text-neon-green">{isAdmin ? "RAPOR MERKEZİ (YÖNETİM)" : "RAPORLAR"}</p>
            <h1 className="font-mono text-2xl font-bold text-white">Raporlar</h1>
            <p className="mt-1 text-sm text-bunker-muted">
              {isAdmin
                ? "Kullanıcı görünümüne ek olarak strateji performansı, sembol bazlı, otonom geçmiş, hız avcısı, LLM tahmin ve self-learning detayları — salt okunur, paper-only."
                : "Radar tespitleri ve otonom sistemin açtığı pozisyonların durumları — salt okunur, paper-only."}
            </p>
          </div>
        </div>

        <div className="section-tabs mb-5" role="tablist" aria-label="Rapor sekmesi">
          {tabs.map((item) => (
            <button key={item.id} type="button" role="tab" aria-selected={tab === item.id}
              className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>
              {item.label}
            </button>
          ))}
        </div>

        {isAdmin ? (
          <>
            {tab === "radar" && <UserRadarTab />}
            {tab === "positions" && <UserPositionsTab />}
            {tab === "overview" && <OverviewTab />}
            {tab === "symbols" && <SymbolsTab />}
            {tab === "autonomous" && <AutonomousTab />}
            {tab === "velocity" && <VelocityTab />}
            {tab === "llm" && <LlmTab />}
            {tab === "learning" && <SelfLearningTab />}
          </>
        ) : (
          <>
            {tab === "radar" && <UserRadarTab />}
            {tab === "positions" && <UserPositionsTab />}
          </>
        )}
      </main>
  );
}

