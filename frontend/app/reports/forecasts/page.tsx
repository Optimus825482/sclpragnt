"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../../lib/api";
import { toMs } from "../../lib/format";
import SymbolLink from "../../components/SymbolLink";
import { useVisibleInterval } from "../../lib/useVisibleInterval";

const pct = (value: unknown) => value == null ? "—" : `%${(Number(value) * 100).toFixed(1)}`;
const direction = (value: unknown) => value === "up" ? "YUKARI" : value === "down" ? "AŞAĞI" : "YATAY";

// H-03: ölçülmemiş ufuk NÖTR renkte olmalı. Eskiden null → kırmızı "—" (veya
// özet kartında sarı) görünüyordu, yani "bu ufukta başarısızız" izlenimi.
const accuracyTone = (value: unknown, warn = false) => {
  if (value == null || !Number.isFinite(Number(value))) return "text-bunker-muted";
  return Number(value) >= 0.55 ? "text-neon-green font-bold" : warn ? "text-yellow-300 font-bold" : "text-neon-red font-bold";
};

export default function ForecastReportPage() {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    return apiRequest(`${API_BASE}/api/reports/llm-forecasts`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((data) => {
        setReport(data);
        setError("");
      })
      .catch(() => setError("LLM tahmin raporu alınamadı."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 30 sn'de bir görünürlük-farkında güncelle
  useVisibleInterval(load, 30_000);

  return (
    <main className="page-shell space-y-5">
      <header className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">LLM TAHMİN RAPORU</p>
          <h1 className="font-mono text-2xl font-bold text-white">Yorum Başarısı</h1>
          <p className="mt-1 text-sm text-bunker-muted">Yalnız kapanmış M1 mumlarıyla ölçülmüş, paper-only yön tahminleri.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setLoading(true); load(); }}
            disabled={loading}
            className="ui-button ui-button-secondary touch-target"
          >
            {loading ? "YÜKLENİYOR…" : "🔄 Yenile"}
          </button>
          <Link href="/reports" className="ui-button ui-button-secondary touch-target">
            RAPORLARA DÖN
          </Link>
        </div>
      </header>

      {error && (
        <section className="card border-neon-red/40 bg-neon-red/5 p-4 text-neon-red flex items-center justify-between gap-3">
          <span>⚠ {error}</span>
          <button onClick={load} className="rounded border border-neon-red/40 px-2 py-1 text-xs hover:bg-neon-red/10">
            YENİDEN DENE
          </button>
        </section>
      )}

      {loading && !report && !error && (
        <section className="card p-8 text-center text-bunker-muted animate-pulse font-mono text-sm">
          📊 LLM tahmin verileri yükleniyor…
        </section>
      )}

      {report && (
        <>
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric title="ÖLÇÜLEN TAHMİN" value={String(report.evaluated_count || 0)} hint="Sonuçlanan tahminler" />
            <Metric title="YÖN DOĞRULUĞU" value={pct(report.directional_accuracy)} tone={accuracyTone(report.directional_accuracy, true)} hint="Genel isabet oranı" />
            <Metric title="DOĞRU TAHMİN" value={`${report.correct_count || 0}/${report.evaluated_count || 0}`} hint="Doğru / Toplam" />
            <Metric title="SONUCU BEKLEYEN" value={String(report.pending_count || 0)} tone="text-sky-300 font-bold" hint="Mum kapanışı bekleyen" />
          </section>

          <section className="card p-5">
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-3">
              <p className="eyebrow text-neon-green">UFUK BAZLI BAŞARI</p>
              <span className="font-mono text-[10px] text-bunker-muted">Zaman aralığına göre doğruluk</span>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Ufuk</th>
                    <th className="text-right">Ölçülen</th>
                    <th className="text-right">Doğru</th>
                    <th className="text-right">Yön Doğruluğu</th>
                    <th className="text-right">Ort. Güven</th>
                    <th className="text-right">Ort. Hareket</th>
                    <th className="text-right">Bekleyen</th>
                  </tr>
                </thead>
                <tbody>
                  {(report.horizons || []).map((row: any) => (
                    <tr key={row.horizon_minutes}>
                      <td className="font-bold">{row.horizon_minutes} dk</td>
                      <td className="font-mono text-right">{row.evaluated_count || 0}</td>
                      <td className="font-mono text-right">{row.correct_count || 0}</td>
                      <td className={`font-mono text-right ${accuracyTone(row.directional_accuracy)}`}>
                        {pct(row.directional_accuracy)}
                      </td>
                      <td className="font-mono text-right">
                        {row.average_confidence == null ? "—" : `%${Number(row.average_confidence).toFixed(0)}`}
                      </td>
                      <td className="font-mono text-right">{pct(row.average_return_pct)}</td>
                      <td className="font-mono text-right text-sky-300">{row.pending_count || 0}</td>
                    </tr>
                  ))}
                  {(!report.horizons || report.horizons.length === 0) && (
                    <tr>
                      <td colSpan={7} className="text-center py-6 text-bunker-muted">
                        Henüz ufuk bazlı değerlendirilmiş veri yok.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-bunker-muted">
              Güven, LLM’in beyanıdır; doğrulukla ayrı değerlendirilir. Az örneklemde sonuç karar kanıtı değildir.
            </p>
          </section>

          <section className="card p-5">
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-3">
              <p className="eyebrow text-neon-green">SON YORUMLAR</p>
              <span className="font-mono text-[10px] text-bunker-muted">{report.recent?.length || 0} kayıt</span>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Zaman</th>
                    <th>Sembol</th>
                    <th>Ufuk</th>
                    <th>Tahmin</th>
                    <th className="text-right">Güven</th>
                    <th>Sonuç</th>
                    <th className="text-right">Hareket</th>
                  </tr>
                </thead>
                <tbody>
                  {(report.recent || []).map((row: any) => (
                    <tr key={row.forecast_id}>
                      <td className="font-mono text-xs text-bunker-muted">
                        {new Date(toMs(row.created_at)).toLocaleString("tr-TR")}
                      </td>
                      <td>
                        <SymbolLink symbol={row.symbol} className="font-bold text-white hover:text-neon-green" />
                      </td>
                      <td className="font-mono text-xs">{row.horizon_minutes} dk</td>
                      <td>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                          row.direction === "up"
                            ? "bg-neon-green/15 text-neon-green"
                            : row.direction === "down"
                            ? "bg-neon-red/15 text-neon-red"
                            : "bg-bunker-800 text-bunker-muted"
                        }`}>
                          {direction(row.direction)}
                        </span>
                      </td>
                      <td className="font-mono text-xs text-right">
                        {row.confidence == null ? "—" : `%${Math.round(Number(row.confidence))}`}
                      </td>
                      <td className="font-mono text-xs">
                        {row.status === "evaluated" ? (
                          <span className={row.direction_correct ? "text-neon-green font-bold" : "text-neon-red font-bold"}>
                            {row.direction_correct ? "✓ DOĞRU" : "✗ YANLIŞ"}
                          </span>
                        ) : (
                          <span className="text-yellow-300">BEKLİYOR</span>
                        )}
                      </td>
                      <td className={`font-mono text-xs text-right ${row.status === "evaluated" ? (Number(row.outcome_return_pct) >= 0 ? "text-neon-green" : "text-neon-red") : "text-bunker-muted"}`}>
                        {row.status === "evaluated" ? pct(row.outcome_return_pct) : "—"}
                      </td>
                    </tr>
                  ))}
                  {(!report.recent || report.recent.length === 0) && (
                    <tr>
                      <td colSpan={7} className="text-center py-6 text-bunker-muted">
                        Henüz tahmin kaydı bulunmuyor.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function Metric({ title, value, tone = "text-white", hint }: { title: string; value: string; tone?: string; hint?: string }) {
  return (
    <section className="card p-4">
      <p className="eyebrow">{title}</p>
      <p className={`mt-2 font-mono text-2xl font-bold ${tone}`}>{value}</p>
      {hint && <p className="mt-1 text-[10px] text-bunker-muted">{hint}</p>}
    </section>
  );
}
