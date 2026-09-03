"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import RequireAdmin from "../components/RequireAdmin";

type AuditLog = {
  id: number;
  actor_username: string | null;
  actor_role: string | null;
  category: string;
  action: string;
  target: string | null;
  details: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
  accept_language: string | null;
  created_at: number;
};

type Notice = { kind: "ok" | "err"; text: string } | null;

const PAGE_SIZE = 50;

const fmtDate = (value: number) =>
  value ? new Date(value < 10_000_000_000 ? value * 1000 : value).toLocaleString("tr-TR") : "—";

const CATEGORY_META: Record<string, { label: string; className: string }> = {
  auth: { label: "GİRİŞ", className: "border-amber-300/50 bg-amber-300/10 text-amber-300" },
  user: { label: "KULLANICI", className: "border-sky-300/50 bg-sky-300/10 text-sky-300" },
  config: { label: "AYAR", className: "border-violet-300/50 bg-violet-300/10 text-violet-300" },
  trade: { label: "İŞLEM", className: "border-neon-green/50 bg-neon-green/10 text-neon-green" },
  alert: { label: "ALARM", className: "border-orange-300/50 bg-orange-300/10 text-orange-300" },
  monitoring: { label: "RADAR", className: "border-cyan-300/50 bg-cyan-300/10 text-cyan-300" },
};
const categoryMeta = (category: string) =>
  CATEGORY_META[String(category || "").toLowerCase()] || {
    label: String(category || "GENEL").toUpperCase(),
    className: "border-bunker-600 bg-bunker-800/50 text-bunker-muted",
  };

const CATEGORY_OPTIONS = [
  { value: "", label: "Tüm kategoriler" },
  { value: "auth", label: "Giriş / Oturum" },
  { value: "user", label: "Kullanıcı yönetimi" },
  { value: "config", label: "Ayarlar" },
  { value: "trade", label: "İşlemler" },
  { value: "alert", label: "Alarmlar" },
  { value: "monitoring", label: "Radar / Bildirim" },
];

const ACTION_OPTIONS = [
  { value: "", label: "Tüm eylemler" },
  { value: "LOGIN_SUCCESS", label: "LOGIN_SUCCESS" },
  { value: "LOGIN_FAILED", label: "LOGIN_FAILED" },
  { value: "LOGIN_BLOCKED", label: "LOGIN_BLOCKED" },
  { value: "LOGOUT", label: "LOGOUT" },
  { value: "PASSWORD_CHANGE", label: "PASSWORD_CHANGE" },
  { value: "USER_CREATE", label: "USER_CREATE" },
  { value: "USER_UPDATE", label: "USER_UPDATE" },
  { value: "USER_DELETE", label: "USER_DELETE" },
  { value: "CONFIG_UPDATE", label: "CONFIG_UPDATE" },
  { value: "MANUAL_SCAN", label: "MANUAL_SCAN" },
  { value: "POSITION_CLOSE_MANUAL", label: "POSITION_CLOSE_MANUAL" },
  { value: "PAPER_TRADE_OPEN", label: "PAPER_TRADE_OPEN" },
  { value: "PAPER_TRADING_TOGGLE", label: "PAPER_TRADING_TOGGLE" },
  { value: "ALERT_CREATE", label: "ALERT_CREATE" },
  { value: "ALERT_UPDATE", label: "ALERT_UPDATE" },
  { value: "ALERT_DELETE", label: "ALERT_DELETE" },
  { value: "MONITORING_SETTINGS_UPDATE", label: "MONITORING_SETTINGS_UPDATE" },
  { value: "MONITORING_NOTIFICATIONS_RESET", label: "MONITORING_NOTIFICATIONS_RESET" },
  { value: "AUDIT_LOG_PURGE", label: "AUDIT_LOG_PURGE" },
];

const detailText = (log: AuditLog): string => {
  const details = log.details;
  if (!details || Object.keys(details).length === 0) return "";
  const parts: string[] = [];
  for (const [key, value] of Object.entries(details)) {
    if (value === null || value === undefined) continue;
    parts.push(`${key}=${typeof value === "object" ? JSON.stringify(value) : String(value)}`);
  }
  return parts.join(" · ");
};

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);
  const [category, setCategory] = useState("");
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [purgeDays, setPurgeDays] = useState(30);
  const [purgeBusy, setPurgeBusy] = useState(false);
  const timerRef = useRef<number | null>(null);

  const notify = (kind: "ok" | "err", text: string) => {
    setNotice({ kind, text });
    window.setTimeout(() => setNotice(null), 4000);
  };

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      if (category) params.set("category", category);
      if (action) params.set("action", action);
      if (actor.trim()) params.set("actor", actor.trim());
      if (q.trim()) params.set("q", q.trim());
      const response = await apiRequest(`${API_BASE}/api/admin/audit-logs?${params.toString()}`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Kayıt listesi alınamadı");
      setLogs(data.logs || []);
      setTotal(Number(data.total || 0));
    } catch (reason) {
      setNotice({ kind: "err", text: reason instanceof Error ? reason.message : "Kayıt listesi alınamadı" });
    } finally {
      setLoading(false);
    }
  }, [category, action, actor, q, offset]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  useEffect(() => {
    timerRef.current = window.setInterval(() => load(), 30_000);
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
    };
  }, [load]);

  const runPurge = async () => {
    setPurgeBusy(true);
    try {
      const beforeTs = Math.floor(Date.now() / 1000) - Number(purgeDays) * 86400;
      const response = await apiRequest(`${API_BASE}/api/admin/audit-logs`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ before_ts: beforeTs }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Temizlik başarısız");
      setConfirmPurge(false);
      notify("ok", `${Number(data.deleted || 0)} kayıt silindi.`);
      setOffset(0);
      load();
    } catch (reason) {
      setNotice({ kind: "err", text: reason instanceof Error ? reason.message : "Temizlik başarısız" });
    } finally {
      setPurgeBusy(false);
    }
  };

  const applyFilters = () => {
    setOffset(0);
    setLoading(true);
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageIndex = Math.floor(offset / PAGE_SIZE);

  return (
    <RequireAdmin>
      <main className="page-shell">
        <div className="page-heading flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">SİSTEM YÖNETİMİ</p>
            <h1 className="font-mono text-2xl font-bold text-white">Olay Kayıtları</h1>
            <p className="mt-1 text-sm text-bunker-muted">
              Kim ne zaman giriş yaptı ve uygulamada hangi işlemi gerçekleştirdi — IP ve cihaz bilgisiyle birlikte.
            </p>
          </div>
          <button type="button" onClick={() => setConfirmPurge(true)} className="ui-button" style={{ borderColor: "rgb(255 49 49 / .5)", background: "rgb(255 49 49 / .1)", color: "#ff3131" }}>
            Eski Kayıtları Temizle
          </button>
        </div>

        {notice && (
          <div role="status" className={`mt-4 rounded-lg border px-4 py-3 text-sm ${notice.kind === "ok" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-neon-red/40 bg-neon-red/10 text-neon-red"}`}>
            {notice.text}
          </div>
        )}

        <div className="card mt-5">
          <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 p-3">
            <select value={category} onChange={(e) => { setCategory(e.target.value); }} className="input !w-auto">
              {CATEGORY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select value={action} onChange={(e) => setAction(e.target.value)} className="input !w-auto">
              {ACTION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input value={actor} onChange={(e) => setActor(e.target.value)} className="input !w-40" placeholder="Kullanıcı adı" />
            <input value={q} onChange={(e) => setQ(e.target.value)} className="input min-w-40 flex-1" placeholder="Serbest arama (hedef, detay…)" />
            <button type="button" onClick={applyFilters} className="ui-button ui-button-primary">FİLTRELE</button>
            <button type="button" onClick={() => { setCategory(""); setAction(""); setActor(""); setQ(""); setOffset(0); setLoading(true); }} className="ui-button ui-button-secondary">SIFIRLA</button>
            <span className="ml-auto font-mono text-xs text-bunker-muted">{total.toLocaleString("tr-TR")} kayıt · 30 sn&apos;de bir yenilenir</span>
          </div>
          <div className="overflow-x-auto">
            {loading && logs.length === 0 ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Yükleniyor…</p>
            ) : logs.length === 0 ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Kayıt bulunamadı.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Zaman</th><th>Kullanıcı</th><th>Kategori</th><th>Eylem</th><th>Hedef</th><th>IP</th><th>Cihaz</th><th>Detay</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => {
                    const meta = categoryMeta(log.category);
                    const device = String(log.user_agent || "").split(" ").slice(0, 8).join(" ");
                    return (
                      <tr key={log.id}>
                        <td className="font-mono text-xs text-bunker-muted" title={fmtDate(log.created_at)}>{fmtDate(log.created_at)}</td>
                        <td className="font-mono text-xs">
                          <span className="font-bold text-white">{log.actor_username || "—"}</span>
                          {log.actor_role === "admin" && <span className="ml-1.5 rounded border border-amber-300/50 bg-amber-300/10 px-1 py-0.5 font-mono text-[9px] text-amber-300">ADMIN</span>}
                        </td>
                        <td><span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${meta.className}`}>{meta.label}</span></td>
                        <td className="font-mono text-xs text-white">{log.action}</td>
                        <td className="font-mono text-xs text-bunker-muted">{log.target || "—"}</td>
                        <td className="font-mono text-xs text-bunker-muted">{log.ip || "—"}</td>
                        <td className="max-w-56 truncate font-mono text-xs text-bunker-muted" title={log.user_agent || undefined}>{log.user_agent ? device : "—"}</td>
                        <td className="max-w-72">
                          {detailText(log) ? (
                            <details className="group">
                              <summary className="cursor-pointer font-mono text-xs text-neon-green/80 hover:text-neon-green">Detay</summary>
                              <p className="mt-1 whitespace-normal font-mono text-[11px] leading-relaxed text-bunker-muted">{detailText(log)}</p>
                            </details>
                          ) : <span className="text-bunker-muted">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          {!loading && logs.length > 0 && (
            <div className="flex items-center justify-between border-t border-bunker-800 px-4 py-3">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="ui-button ui-button-secondary disabled:opacity-40">← ÖNCEKİ</button>
              <span className="font-mono text-xs text-bunker-muted">Sayfa {pageIndex + 1} / {pageCount}</span>
              <button type="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)} className="ui-button ui-button-secondary disabled:opacity-40">SONRAKİ →</button>
            </div>
          )}
        </div>
        <p className="mt-3 font-mono text-[11px] text-bunker-muted">
          Bu sayfa yalnızca yöneticilerin görebildiği kullanıcı hareketi kayıtlarını listeler · Otomatik bot döngüleri burada yer almaz
        </p>

        {confirmPurge && (
          <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-4" onClick={() => setConfirmPurge(false)} role="dialog" aria-modal="true" aria-labelledby="purge-title">
            <section className="w-full max-w-sm rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
              <div className="p-5">
                <h2 id="purge-title" className="font-mono text-lg font-bold text-white">Eski kayıtları temizle</h2>
                <p className="mt-2 text-sm text-bunker-muted">
                  Seçilen günden <strong className="text-white">eski</strong> tüm olay kayıtları kalıcı olarak silinir. Bu işlem geri alınamaz.
                </p>
                <label className="mt-4 block"><span className="eyebrow">SİLME YAŞI (GÜN)</span>
                  <input type="number" min={1} max={3650} value={purgeDays} onChange={(e) => setPurgeDays(Number(e.target.value))} className="input mt-2 w-full" />
                </label>
                {notice?.kind === "err" && <p role="alert" className="mt-3 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{notice.text}</p>}
                <div className="mt-5 flex justify-end gap-2">
                  <button type="button" onClick={() => setConfirmPurge(false)} className="ui-button ui-button-secondary">VAZGEÇ</button>
                  <button type="button" onClick={runPurge} disabled={purgeBusy || !(purgeDays > 0)} className="ui-button" style={{ borderColor: "rgb(255 49 49 / .5)", background: "rgb(255 49 49 / .12)", color: "#ff3131" }}>{purgeBusy ? "SİLİNİYOR…" : "EVET, TEMİZLE"}</button>
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </RequireAdmin>
  );
}
