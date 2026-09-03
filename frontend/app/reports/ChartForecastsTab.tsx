"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type Forecast = {
  id: number;
  symbol: string;
  timeframe: string;
  horizon_minutes: number;
  entry_price: number;
  target_pct: number;
  target_price: number | null;
  hit_probability: number | null;
  created_at: number;
  status: string;
  direction_correct: boolean | null;
  max_favorable_pct: number | null;
  outcome_return_pct: number | null;
};

type Summary = {
  total: number;
  evaluated: number;
  correct: number;
  hit: number;
  accuracy: number | null;
  hit_rate: number | null;
  by_symbol: Array<{
    symbol: string;
    total: number;
    evaluated: number;
    correct: number;
    hit: number;
    accuracy: number | null;
    hit_rate: number | null;
  }>;
};

const PAGINATION_PAGE_SIZE = 25;

export default function ChartForecastsTab() {
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const loadSummary = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (symbolFilter) params.set("symbol", symbolFilter);
      const res = await apiRequest(`${API_BASE}/api/chart/forecasts/summary?${params}`, { cache: "no-store" });
      if (res.ok) setSummary(await res.json());
    } catch {
      // summary yüklenemezse sessiz geç
    }
  }, [symbolFilter]);

  const loadForecasts = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGINATION_PAGE_SIZE));
      params.set("offset", String(page * PAGINATION_PAGE_SIZE));
      if (symbolFilter) params.set("symbol", symbolFilter);
      if (statusFilter) params.set("status", statusFilter);
      const res = await apiRequest(`${API_BASE}/api/chart/forecasts?${params}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setForecasts(data.forecasts || []);
      setTotal(data.total || 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Veri yüklenemedi");
      setForecasts([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, symbolFilter, statusFilter]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadForecasts(); }, [loadForecasts]);

  const totalPages = Math.ceil(total / PAGINATION_PAGE_SIZE);

  const handleFilter = (type: "symbol" | "status", value: string) => {
    setPage(0);
    if (type === "symbol") setSymbolFilter(value);
    else setStatusFilter(value);
  };

  return (
    <div className="space-y-5">
      {/* Özet Kartları */}
      {summary && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard title="Toplam Tahmin" value={String(summary.total)} />
            <StatCard title="Değerlendirilen" value={String(summary.evaluated)} tone="text-sky-300" />
            <StatCard
              title="Yön Doğruluğu"
              value={summary.accuracy != null ? `%${(summary.accuracy * 100).toFixed(1)}` : "—"}
              tone={summary.accuracy != null && summary.accuracy >= 0.55 ? "text-neon-green" : "text-neon-red"}
            />
            <StatCard
              title="Hedef İsabet"
              value={summary.hit_rate != null ? `%${(summary.hit_rate * 100).toFixed(1)}` : "—"}
              tone={summary.hit_rate != null && summary.hit_rate >= 0.5 ? "text-neon-green" : "text-yellow-300"}
            />
          </div>

          {/* Sembol Bazlı Başarı */}
          {summary.by_symbol.length > 0 && (
            <section className="card">
              <p className="eyebrow">SEMbol BAZLI BAŞARI</p>
              <div className="mt-3 table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Sembol</th>
                      <th>Toplam</th>
                      <th>Değerlendirilen</th>
                      <th>Doğru</th>
                      <th>İsabet</th>
                      <th>Yön Doğruluğu</th>
                      <th>Hedef İsabeti</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_symbol.map((row) => (
                      <tr key={row.symbol}>
                        <td><SymbolLink symbol={row.symbol} className="text-white hover:text-neon-green" /></td>
                        <td>{row.total}</td>
                        <td>{row.evaluated}</td>
                        <td className="text-neon-green">{row.correct}</td>
                        <td className="text-sky-300">{row.hit}</td>
                        <td className={row.accuracy != null && row.accuracy >= 0.55 ? "text-neon-green" : "text-neon-red"}>
                          {row.accuracy != null ? `%${(row.accuracy * 100).toFixed(1)}` : "—"}
                        </td>
                        <td className={row.hit_rate != null && row.hit_rate >= 0.5 ? "text-neon-green" : "text-yellow-300"}>
                          {row.hit_rate != null ? `%${(row.hit_rate * 100).toFixed(1)}` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {/* Filtreler */}
      <div className="flex flex-wrap gap-3">
        <div>
          <p className="font-mono text-[11px] text-bunker-muted mb-1">SEMbol</p>
          <input
            type="text"
            value={symbolFilter}
            onChange={(e) => handleFilter("symbol", e.target.value.toUpperCase())}
            placeholder="Örn: BTCTRY"
            className="bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white placeholder-bunker-700 focus:border-neon-green/50 outline-none"
          />
        </div>
        <div>
          <p className="font-mono text-[11px] text-bunker-muted mb-1">DURUM</p>
          <select
            value={statusFilter}
            onChange={(e) => handleFilter("status", e.target.value)}
            className="bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
          >
            <option value="">Tümü</option>
            <option value="pending">Bekliyor</option>
            <option value="evaluated">Değerlendirildi</option>
            <option value="expired">Süresi Doldu</option>
          </select>
        </div>
      </div>

      {/* Tahmin Listesi */}
      <section className="card">
        <div className="flex justify-between items-center">
          <p className="eyebrow">FİYAT TAHMİNLERİ</p>
          <span className="font-mono text-xs text-bunker-muted">{total} kayıt</span>
        </div>
        {loading && <p className="mt-3 text-bunker-muted">Yükleniyor…</p>}
        {error && <p className="mt-3 text-neon-red">{error}</p>}
        {!loading && !error && forecasts.length === 0 && (
          <p className="mt-3 text-bunker-muted">Kayıt bulunamadı.</p>
        )}
        {!loading && forecasts.length > 0 && (
          <>
            <div className="mt-3 table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Zaman</th>
                    <th>Sembol</th>
                    <th>TF</th>
                    <th>Ufuk</th>
                    <th>Giriş</th>
                    <th>Hedef %</th>
                    <th>Olasılık</th>
                    <th>Durum</th>
                    <th>Sonuç</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.map((f) => (
                    <tr key={f.id}>
                      <td>{new Date(f.created_at * 1000).toLocaleString("tr-TR")}</td>
                      <td><SymbolLink symbol={f.symbol} className="text-white hover:text-neon-green" /></td>
                      <td>{f.timeframe}</td>
                      <td>{f.horizon_minutes}dk</td>
                      <td>{f.entry_price?.toLocaleString("tr-TR", { maximumFractionDigits: 4 })}</td>
                      <td>%{f.target_pct?.toFixed(3)}</td>
                      <td>{f.hit_probability != null ? `%${(f.hit_probability * 100).toFixed(0)}` : "—"}</td>
                      <td>
                        <StatusBadge status={f.status} correct={f.direction_correct} />
                      </td>
                      <td className={getOutcomeClass(f.direction_correct, f.max_favorable_pct, f.target_pct)}>
                        {getOutcomeText(f.direction_correct, f.max_favorable_pct, f.target_pct, f.outcome_return_pct)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-4 flex justify-between items-center">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-3 py-1.5 rounded-lg border border-bunker-700 font-mono text-sm text-bunker-muted hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  ← Önceki
                </button>
                <span className="font-mono text-sm text-bunker-muted">
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-3 py-1.5 rounded-lg border border-bunker-700 font-mono text-sm text-bunker-muted hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Sonraki →
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function StatCard({ title, value, tone = "text-white" }: { title: string; value: string; tone?: string }) {
  return (
    <section className="card">
      <p className="eyebrow">{title}</p>
      <p className={`mt-2 font-mono text-2xl ${tone}`}>{value}</p>
    </section>
  );
}

function StatusBadge({ status, correct }: { status: string; correct: boolean | null }) {
  if (status === "pending") {
    return <span className="text-yellow-300">BEKLİYOR</span>;
  }
  if (status === "expired") {
    return <span className="text-bunker-muted">SÜRE DOLDU</span>;
  }
  if (correct === true) {
    return <span className="text-neon-green">DOĞRU</span>;
  }
  if (correct === false) {
    return <span className="text-neon-red">YANLIŞ</span>;
  }
  return <span className="text-bunker-muted">{status}</span>;
}

function getOutcomeClass(correct: boolean | null, mfe: number | null, target: number): string {
  if (correct === true) return "text-neon-green";
  if (correct === false) return "text-neon-red";
  if (mfe != null && target != null && mfe >= target) return "text-neon-green";
  return "text-bunker-muted";
}

function getOutcomeText(correct: boolean | null, mfe: number | null, target: number | null, ret: number | null): string {
  if (correct === true) return "DOĞRU";
  if (correct === false) return "YANLIŞ";
  if (mfe != null && target != null && mfe >= target) return `HEDEFE ULAŞTI (%${(mfe * 100).toFixed(2)})`;
  if (ret != null) return `%${(ret * 100).toFixed(2)}`;
  return "—";
}
