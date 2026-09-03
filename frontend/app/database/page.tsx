"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import RequireAdmin from "../components/RequireAdmin";

type TableInfo = { table: string; rows: number | null; description: string };
type RowData = { total: number; columns: string[]; rows: Record<string, unknown>[] };
type Notice = { kind: "ok" | "err"; text: string } | null;

const fmtValue = (value: unknown) => {
  if (value === null || value === undefined) return <span className="text-bunker-muted">NULL</span>;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return <code className="text-[10px] text-sky-300">{JSON.stringify(value).slice(0, 120)}</code>;
  const s = String(value);
  return s.length > 160 ? s.slice(0, 160) + "…" : s;
};

export default function DatabasePage() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<TableInfo | null>(null);
  const [data, setData] = useState<RowData | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loadingTables, setLoadingTables] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [totalRows, setTotalRows] = useState(0);

  const loadTables = useCallback(async () => {
    setLoadingTables(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/admin/db/tables`, { cache: "no-store" });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || "Tablo listesi alınamadı");
      setTables(j.tables || []);
    } catch (e) {
      setNotice({ kind: "err", text: e instanceof Error ? e.message : "Tablo listesi alınamadı" });
    } finally {
      setLoadingTables(false);
    }
  }, []);

  useEffect(() => { loadTables(); }, [loadTables]);

  const loadRows = useCallback(async (table: string, p: number, size: number) => {
    setLoadingRows(true);
    setNotice(null);
    try {
      const q = new URLSearchParams({ table, page: String(p), page_size: String(size) });
      const res = await apiRequest(`${API_BASE}/api/admin/db/table?${q}`, { cache: "no-store" });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || "Veri alınamadı");
      setData({ total: j.total, columns: j.columns || [], rows: j.rows || [] });
      setTotalRows(j.total ?? 0);
    } catch (e) {
      setNotice({ kind: "err", text: e instanceof Error ? e.message : "Veri alınamadı" });
      setData(null);
    } finally {
      setLoadingRows(false);
    }
  }, []);

  const openTable = async (t: TableInfo) => {
    setSelected(t);
    setPage(1);
    await loadRows(t.table, 1, pageSize);
  };

  const goPage = async (p: number) => {
    if (!selected || p < 1) return;
    setPage(p);
    await loadRows(selected.table, p, pageSize);
  };

  const changePageSize = async (size: number) => {
    setPageSize(size);
    setPage(1);
    if (selected) await loadRows(selected.table, 1, size);
  };

  const download = async (format: "csv" | "sql") => {
    if (!selected) return;
    try {
      const q = new URLSearchParams({ table: selected.table, format });
      const res = await apiRequest(`${API_BASE}/api/admin/db/table/export?${q}`, { cache: "no-store" });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "İndirme başarısız");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selected.table}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setNotice({ kind: "ok", text: `${selected.table}.${format} indirildi` });
    } catch (e) {
      setNotice({ kind: "err", text: e instanceof Error ? e.message : "İndirme başarısız" });
    }
  };

  const filtered = tables.filter((t) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return t.table.toLowerCase().includes(q) || (t.description || "").toLowerCase().includes(q);
  });

  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

  return (
    <RequireAdmin>
      <main className="page-shell">
        <div className="page-heading flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow text-neon-green">ADMIN</p>
            <h1 className="font-mono text-2xl font-bold text-white">Veritabanı</h1>
            <p className="mt-1 text-sm text-bunker-muted">PostgreSQL tabloları, kayıt sayıları ve veri görüntüleme.</p>
          </div>
          <button onClick={() => { loadTables(); }} className="ui-button ui-button-secondary">🔄 Yenile</button>
        </div>

        {notice && (
          <div className={`mt-4 rounded-lg border px-4 py-2 text-sm ${notice.kind === "ok" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-neon-red/40 bg-neon-red/10 text-neon-red"}`}>
            {notice.text}
          </div>
        )}

        <div className="grid grid-cols-12 gap-4">
          <section className="card col-span-12 lg:col-span-4">
            <div className="flex items-center justify-between">
              <p className="eyebrow text-neon-green">TABLOLAR ({filtered.length})</p>
              {loadingTables && <span className="text-xs text-bunker-muted">yükleniyor…</span>}
            </div>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tablo veya açıklama ara…"
              className="input mt-3 w-full"
            />
            <div className="mt-3 max-h-[70vh] space-y-1 overflow-y-auto pr-1">
              {filtered.map((t) => (
                <button
                  key={t.table}
                  onClick={() => openTable(t)}
                  className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors ${selected?.table === t.table ? "border-neon-green/50 bg-neon-green/10" : "border-bunker-800 bg-bunker-900/40 hover:border-neon-green/30"}`}
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm font-bold text-white">{t.table}</p>
                    {t.description && <p className="truncate text-[11px] text-bunker-muted">{t.description}</p>}
                  </div>
                  <span className="ml-2 shrink-0 rounded bg-bunker-800 px-1.5 py-0.5 font-mono text-[10px] text-neon-green">
                    {t.rows !== null ? t.rows.toLocaleString("tr-TR") : "?"}
                  </span>
                </button>
              ))}
              {!loadingTables && filtered.length === 0 && <p className="py-6 text-center text-sm text-bunker-muted">Tablo bulunamadı</p>}
            </div>
          </section>

          <section className="card col-span-12 lg:col-span-8">
            {!selected ? (
              <p className="py-16 text-center text-sm text-bunker-muted">Görüntülemek için soldan bir tablo seçin.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="eyebrow text-neon-green">TABLO</p>
                    <h2 className="font-mono text-lg font-bold text-white">{selected.table}</h2>
                    {selected.description && <p className="text-xs text-bunker-muted">{selected.description}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <select value={pageSize} onChange={(e) => changePageSize(Number(e.target.value))} className="input w-auto">
                      {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} satır</option>)}
                    </select>
                    <button onClick={() => download("csv")} className="ui-button ui-button-secondary">⬇ CSV</button>
                    <button onClick={() => download("sql")} className="ui-button ui-button-secondary">⬇ SQL</button>
                  </div>
                </div>

                {loadingRows ? (
                  <p className="py-10 text-center text-sm text-bunker-muted">Veri yükleniyor…</p>
                ) : data && data.columns.length ? (
                  <>
                    <div className="mt-3 max-h-[65vh] overflow-auto rounded-lg border border-bunker-800">
                      <table className="w-full text-left text-xs">
                        <thead className="sticky top-0 bg-bunker-900">
                          <tr>
                            {data.columns.map((col) => (
                              <th key={col} className="whitespace-nowrap border-b border-bunker-700 px-2 py-1.5 font-mono text-[10px] font-bold text-neon-green">{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {data.rows.map((row, i) => (
                            <tr key={i} className="border-b border-bunker-800/50 hover:bg-bunker-900/40">
                              {data.columns.map((col) => (
                                <td key={col} className="whitespace-nowrap px-2 py-1 text-bunker-200">{fmtValue(row[col])}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs text-bunker-muted">Toplam {totalRows.toLocaleString("tr-TR")} satır · Sayfa {page}/{totalPages}</p>
                      <div className="flex items-center gap-1">
                        <button disabled={page <= 1} onClick={() => goPage(page - 1)} className="ui-button ui-button-secondary disabled:opacity-40">‹ Önceki</button>
                        <button disabled={page >= totalPages} onClick={() => goPage(page + 1)} className="ui-button ui-button-secondary disabled:opacity-40">Sonraki ›</button>
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="py-10 text-center text-sm text-bunker-muted">Bu tabloda veri yok veya okunamadı.</p>
                )}
              </>
            )}
          </section>
        </div>
      </main>
    </RequireAdmin>
  );
}
