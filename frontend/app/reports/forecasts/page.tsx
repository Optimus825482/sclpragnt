"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../../lib/api";
import SymbolLink from "../../components/SymbolLink";

const pct = (value: unknown) => value == null ? "—" : `%${(Number(value) * 100).toFixed(1)}`;
const direction = (value: unknown) => value === "up" ? "YUKARI" : value === "down" ? "AŞAĞI" : "YATAY";

export default function ForecastReportPage() {
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest(`${API_BASE}/api/reports/llm-forecasts`, { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(setReport).catch(() => setError("LLM tahmin raporu alınamadı."));
  }, []);

  return <main className="page-shell space-y-5">
    <header className="page-heading flex flex-wrap items-start justify-between gap-3">
      <div><p className="eyebrow text-neon-green">LLM TAHMİN RAPORU</p><h1>Yorum Başarısı</h1><p className="text-bunker-muted">Yalnız kapanmış M1 mumlarıyla ölçülmüş, paper-only yön tahminleri.</p></div>
      <Link href="/reports" className="ui-button">RAPORLARA DÖN</Link>
    </header>
    {error && <section className="card border-neon-red/40 text-neon-red">{error}</section>}
    {!report && !error && <section className="card text-bunker-muted">Yükleniyor…</section>}
    {report && <>
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric title="Ölçülen tahmin" value={String(report.evaluated_count || 0)} />
        <Metric title="Yön doğruluğu" value={pct(report.directional_accuracy)} tone={report.directional_accuracy != null && report.directional_accuracy >= .55 ? "text-neon-green" : "text-yellow-300"} />
        <Metric title="Doğru tahmin" value={`${report.correct_count || 0}/${report.evaluated_count || 0}`} />
        <Metric title="Sonucu bekleyen" value={String(report.pending_count || 0)} tone="text-sky-300" />
      </section>
      <section className="card"><p className="eyebrow">UFUK BAZLI BAŞARI</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Ufuk</th><th>Ölçülen</th><th>Doğru</th><th>Yön doğruluğu</th><th>Ort. güven</th><th>Ort. hareket</th><th>Bekleyen</th></tr></thead><tbody>{(report.horizons || []).map((row:any) => <tr key={row.horizon_minutes}><td>{row.horizon_minutes} dk</td><td>{row.evaluated_count || 0}</td><td>{row.correct_count || 0}</td><td className={row.directional_accuracy != null && row.directional_accuracy >= .55 ? "text-neon-green" : "text-neon-red"}>{pct(row.directional_accuracy)}</td><td>{row.average_confidence == null ? "—" : `%${Number(row.average_confidence).toFixed(0)}`}</td><td>{pct(row.average_return_pct)}</td><td>{row.pending_count || 0}</td></tr>)}</tbody></table></div><p className="mt-3 text-xs text-bunker-muted">Güven, LLM’in beyanıdır; doğrulukla ayrı değerlendirilir. Az örneklemde sonuç karar kanıtı değildir.</p></section>
      <section className="card"><p className="eyebrow">SON YORUMLAR</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Ufuk</th><th>Tahmin</th><th>Güven</th><th>Sonuç</th><th>Hareket</th></tr></thead><tbody>{(report.recent || []).map((row:any) => <tr key={row.forecast_id}><td>{new Date(Number(row.created_at) * 1000).toLocaleString("tr-TR")}</td><td><SymbolLink symbol={row.symbol} className="text-white hover:text-neon-green" /></td><td>{row.horizon_minutes} dk</td><td>{direction(row.direction)}</td><td>%{Math.round(Number(row.confidence) || 0)}</td><td className={row.status === "evaluated" ? (row.direction_correct ? "text-neon-green" : "text-neon-red") : "text-yellow-300"}>{row.status === "evaluated" ? (row.direction_correct ? "DOĞRU" : "YANLIŞ") : "BEKLİYOR"}</td><td>{row.status === "evaluated" ? pct(row.outcome_return_pct) : "—"}</td></tr>)}</tbody></table></div></section>
    </>}
  </main>;
}

function Metric({ title, value, tone = "text-white" }: { title: string; value: string; tone?: string }) {
  return <section className="card"><p className="eyebrow">{title}</p><p className={`mt-2 font-mono text-2xl ${tone}`}>{value}</p></section>;
}
