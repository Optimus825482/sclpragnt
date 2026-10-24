"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

/**
 * Günün ilk bildirimi (2026-10-25) — backend /api/reports/daily-first-notification.
 *
 * Her sembol için Europe/Istanbul gününün İLK push bildirimi ve o andan gün sonuna (23:59:59) kadar
 * 1 dk mumlarla ölçülen MFE (en yüksek high'a yükseliş, >= 0) / maksimum düşüş (en düşük low'a düşüş).
 * Backend MAE'yi NEGATİF saklar (`mae_sign: "negative"`); tabloda olduğu gibi (−%) gösterilir.
 */
export type DailyFirstRow = {
  id: number;
  symbol: string;
  day_key: string;              // YYYY-MM-DD (Europe/Istanbul)
  first_notification_id: number | null;
  first_ts: number;             // epoch sn
  first_price: number | null;
  mfe_pct: number | null;       // >= 0
  mfe_ts: number | null;
  mae_pct: number | null;       // <= 0 (negatif)
  mae_ts: number | null;
  last_tracked_ts: number | null;
  finalized: boolean;
};

export type DailyFirstSummary = {
  day_key: string;
  count: number;
  measured: number;
  finalized: number;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  mfe_ge_1_share_pct: number | null;
};

export type DailyFirstReport = {
  paper_only: boolean;
  generated_at: number;
  days: number;
  since_day_key: string;
  today_day_key: string;
  mae_sign: "negative";
  total: number;
  summary: DailyFirstSummary[];
  rows: DailyFirstRow[];
};

const IST = "Europe/Istanbul";

/** Epoch sn → İstanbul saati `SS:dd` (gün sınırı backend ile aynı dilimde). */
export function fmtIstanbulClock(ts: number | null | undefined): string {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return new Date(n * 1000).toLocaleTimeString("tr-TR", { timeZone: IST, hour: "2-digit", minute: "2-digit" });
}

/** `YYYY-MM-DD` → `24.10.2026 Cumartesi` (tr-TR). */
export function fmtDayKey(dayKey: string): string {
  const [y, m, d] = dayKey.split("-").map((v) => Number(v));
  if (!y || !m || !d) return dayKey;
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString("tr-TR", {
    timeZone: IST, day: "2-digit", month: "2-digit", year: "numeric", weekday: "long",
  });
}

export const pctSigned = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;

export const mfeTone = (v: number | null | undefined): string =>
  v == null ? "text-bunker-muted" : Number(v) >= 1 ? "text-neon-green font-bold" : Number(v) > 0 ? "text-neon-green" : "text-white";

export const maeTone = (v: number | null | undefined): string =>
  v == null ? "text-bunker-muted" : Number(v) < 0 ? "text-neon-red" : "text-white";

export const statusLabel = (finalized: boolean): { label: string; cls: string } =>
  finalized
    ? { label: "tamamlandı", cls: "border-bunker-700 bg-bunker-900/60 text-bunker-muted" }
    : { label: "izleniyor", cls: "border-sky-400/40 bg-sky-400/10 text-sky-300" };

export const DAY_OPTIONS = [1, 3, 7, 14, 30] as const;

/** Günlük özet satırı: `N sembol · ort. MFE +x% · ort. düşüş −y% · ≥%1: z%`. */
export function summaryLine(s: DailyFirstSummary): string {
  const parts = [`${s.count} sembol`];
  if (s.measured) {
    parts.push(`ort. MFE ${pctSigned(s.avg_mfe_pct)}`);
    parts.push(`ort. maks düşüş ${pctSigned(s.avg_mae_pct)}`);
    parts.push(`MFE ≥ %1: %${(s.mfe_ge_1_share_pct ?? 0).toFixed(0)} (${s.measured} ölçülen)`);
  } else {
    parts.push("henüz ölçüm yok");
  }
  if (s.finalized && s.finalized === s.count) parts.push("gün kapandı");
  return parts.join(" · ");
}

/** Saf tablo bileşeni (vitest `react-dom/server` ile çizer; veri çekmez). */
export function DailyFirstTable({ report }: { report: DailyFirstReport }) {
  const byDay = useMemo(() => {
    const map = new Map<string, DailyFirstRow[]>();
    for (const r of report.rows) {
      const list = map.get(r.day_key) ?? [];
      list.push(r);
      map.set(r.day_key, list);
    }
    const order = report.summary.length
      ? report.summary.map((s) => s.day_key)
      : Array.from(map.keys()).sort().reverse();
    return order.filter((k) => map.has(k)).map((k) => ({
      dayKey: k,
      rows: map.get(k) ?? [],
      summary: report.summary.find((s) => s.day_key === k) ?? null,
    }));
  }, [report]);

  if (byDay.length === 0) {
    return (
      <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-6 text-center">
        <p className="font-mono text-sm text-bunker-muted">henüz veri yok</p>
        <p className="mt-1 text-[11px] text-bunker-muted">
          Seçilen dönemde push bildirimi almış sembol bulunmuyor; ilk bildirimle birlikte satır oluşur ve 5 dk&apos;da bir güncellenir.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      {byDay.map(({ dayKey, rows, summary }) => (
        <section key={dayKey} className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4" data-day={dayKey}>
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="font-mono text-sm font-black text-white">
              {fmtDayKey(dayKey)}
              {dayKey === report.today_day_key ? <span className="ml-2 text-[10px] text-neon-green">BUGÜN</span> : null}
            </h3>
            {summary ? <span className="font-mono text-[11px] text-bunker-muted">{summaryLine(summary)}</span> : null}
          </div>
          <div className="table-scroll max-h-[480px]">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th className="text-left">Sembol</th>
                  <th className="text-right">İlk bildirim (saat)</th>
                  <th className="text-right">Fiyat</th>
                  <th className="text-right">MFE %</th>
                  <th className="text-right">MFE saati</th>
                  <th className="text-right">Maks düşüş %</th>
                  <th className="text-left">Durum</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const st = statusLabel(r.finalized);
                  return (
                    <tr key={r.id}>
                      <td className="font-mono text-xs font-bold text-white"><SymbolLink symbol={r.symbol} /></td>
                      <td className="text-right tabular-nums font-mono text-xs text-white">{fmtIstanbulClock(r.first_ts)}</td>
                      <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">
                        {r.first_price == null ? "—" : formatPrice(r.first_price)}
                      </td>
                      <td className={`text-right tabular-nums font-mono text-xs ${mfeTone(r.mfe_pct)}`}>{pctSigned(r.mfe_pct)}</td>
                      <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">{fmtIstanbulClock(r.mfe_ts)}</td>
                      <td className={`text-right tabular-nums font-mono text-xs ${maeTone(r.mae_pct)}`} title={r.mae_ts ? `dip saati ${fmtIstanbulClock(r.mae_ts)}` : undefined}>
                        {pctSigned(r.mae_pct)}
                      </td>
                      <td>
                        <span className={`inline-flex rounded-md border px-1.5 py-0.5 font-mono text-[10px] ${st.cls}`}>{st.label}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

export default function DailyFirstNotificationTab() {
  const [days, setDays] = useState<number>(7);
  const [report, setReport] = useState<DailyFirstReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError("");
    try {
      const res = await apiRequest(`${API_BASE}/api/reports/daily-first-notification?days=${d}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setReport(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rapor yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [load, days]);

  return (
    <div className="space-y-4">
      <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4 space-y-2">
        <h2 className="font-mono text-base font-black text-white">🔔 Günün İlk Bildirimi</h2>
        <p className="text-xs text-bunker-muted">
          Her sembol için günün (Europe/Istanbul 00:00–23:59:59) <b className="text-white">ilk push bildirimi</b> kaydedilir;
          o andan gün sonuna kadar 1 dk mumlarla <b className="text-white">MFE</b> (bildirim fiyatından en yüksek high&apos;a yükseliş)
          ve <b className="text-white">maksimum düşüş</b> (en düşük low&apos;a düşüş, negatif gösterilir) izlenir.
          Bildirim anını içeren yarım mum sayılmaz. Satırlar 5 dakikada bir güncellenir; gün kapanınca &quot;tamamlandı&quot; olur.
        </p>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-mono text-bunker-muted">Dönem:</span>
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            className={`rounded-lg px-3 py-1.5 font-mono text-xs font-bold transition-all ${
              days === d ? "bg-neon-green/15 text-neon-green border border-neon-green/40" : "text-bunker-muted hover:text-white border border-bunker-800"
            }`}
          >
            {d === 1 ? "bugün" : `${d} gün`}
          </button>
        ))}
        <button
          type="button"
          onClick={() => void load(days)}
          className="rounded-lg border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted hover:text-white"
        >
          ↻ YENİLE
        </button>
        {report && (
          <span className="ml-auto text-xs font-mono text-bunker-muted">
            {report.total} satır · {report.summary.length} gün
          </span>
        )}
      </div>

      {loading && <p className="py-6 text-center font-mono text-sm text-bunker-muted">Rapor yükleniyor…</p>}
      {error && <p className="py-4 font-mono text-sm text-neon-red">⚠ {error}</p>}
      {report && !loading && !error && <DailyFirstTable report={report} />}
    </div>
  );
}
