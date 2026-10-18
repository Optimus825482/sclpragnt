"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import SymbolLink from "../SymbolLink";
import { getJSON } from "../../lib/api";
import { fmtDateTime, formatPrice } from "../../lib/format";
import {
  confluenceLabel, filterRows, istanbulToday, meanMfe, sourceLabel, statusLabel, toRateRows,
  type RateRow, type ReportRow, type ResultFilter,
} from "../../lib/signalReport";
import { useVisibleInterval } from "../../lib/useVisibleInterval";

type Period = "since" | "today";
type Stats = Record<string, { count?: number; evaluated?: number; success_count?: number; success_rate?: number | null }>;
type Payload = {
  notifications?: ReportRow[];
  breakdown?: { counts?: Record<string, number>; evaluated?: number; success_count?: number; success_rate?: number | null;
    confluence_stats?: Stats; source_stats?: Stats };
};

const PAGE = 25;
const toneClass = (tone: string) => (tone === "mute" ? "wait" : tone);
/** Oran → renk (iyi ≥ %50, orta ≥ %30, düşük). */
const rateTone = (rate: number | null) => (rate == null ? "wait" : rate >= 50 ? "good" : rate >= 30 ? "warn" : "bad");

function Kpi({ title, value, sub, tone }: { title: string; value: string; sub: string; tone: string }) {
  return (
    <div className={`card u-card-${tone} p-4`}>
      <p className="text-sm font-medium text-bunker-muted">{title}</p>
      <p className={`mt-1 text-3xl font-bold u-num-${tone}`}>{value}</p>
      <p className="mt-1 text-sm text-bunker-muted">{sub}</p>
    </div>
  );
}

function RateBars({ title, hint, rows }: { title: string; hint: string; rows: RateRow[] }) {
  return (
    <section className="card p-4" aria-label={title}>
      <h2 className="text-base font-semibold text-white">{title}</h2>
      <p className="mb-3 text-xs text-bunker-muted">{hint}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-bunker-muted">Henüz veri yok.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.key}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium text-white">{r.label}</span>
                <span className={`font-bold u-num-${rateTone(r.rate)}`}>
                  {r.rate == null ? "—" : `%${r.rate.toFixed(0)}`}
                  <span className="ml-1 text-xs font-normal text-bunker-muted">({r.success}/{r.evaluated})</span>
                </span>
              </div>
              <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full" style={{ background: "var(--u-line)" }}
                role="img" aria-label={`${r.label}: ${r.rate == null ? "ölçüm yok" : `%${r.rate.toFixed(0)} başarı`}`}>
                <div className={`h-full rounded-full u-bar-${rateTone(r.rate)}`} style={{ width: `${Math.max(0, Math.min(100, r.rate ?? 0))}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function UserSignalReport() {
  const [period, setPeriod] = useState<Period>("since");
  const [result, setResult] = useState<ResultFilter>("all");
  const [data, setData] = useState<Payload | null>(null);
  const [failed, setFailed] = useState(false);
  const [cut, setCut] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);

  const load = useCallback(async () => {
    const day = period === "today" ? istanbulToday() : "all";
    try {
      setData(await getJSON<Payload>(`/api/reports/notifications?limit=1000&day=${day}`));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [period]);
  useEffect(() => { setShown(PAGE); void load(); }, [load]);
  useVisibleInterval(load, 30_000);
  useEffect(() => {
    getJSON<{ radar_effective_local?: string | null }>("/api/reports/baseline")
      .then((d) => setCut(d.radar_effective_local || null)).catch(() => undefined);
  }, []);

  const rows = data?.notifications ?? [];
  const b = data?.breakdown;
  const counts = b?.counts ?? {};
  const hit = Number(counts["TAMAMEN BAŞARILI"] ?? 0);
  const partial = Number(counts["KISMİ"] ?? 0);
  const miss = Number(counts["BAŞARISIZ"] ?? 0);
  const open = Number(counts["BEKLİYOR"] ?? 0) + Number(counts["ÖLÇÜLEMEDİ"] ?? 0);
  const evaluated = Number(b?.evaluated ?? 0);
  const rate = evaluated > 0 && b?.success_rate != null ? Number(b.success_rate) : null;
  const avg = useMemo(() => meanMfe(rows), [rows]);
  const filtered = useMemo(() => filterRows(rows, result), [rows, result]);

  const confluenceRows = toRateRows(b?.confluence_stats, confluenceLabel, ["1", "2", "3", "4"]);
  const sourceRows = toRateRows(b?.source_stats, sourceLabel, ["velocity", "jump", "early", "rising", "global"]);

  const periodBtn = (id: Period, label: string) => (
    <button type="button" aria-pressed={period === id} onClick={() => setPeriod(id)}
      className={`min-h-[44px] rounded-lg px-4 text-sm font-semibold ${period === id ? "u-seg-on" : "u-seg-off"}`}>{label}</button>
  );
  const resultBtn = (id: ResultFilter, label: string) => (
    <button key={id} type="button" aria-pressed={result === id} onClick={() => { setResult(id); setShown(PAGE); }}
      className={`min-h-[44px] rounded-lg px-3 text-sm font-semibold ${result === id ? "u-seg-on" : "u-seg-off"}`}>{label}</button>
  );

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-bold text-white">Sinyal başarı raporu</h1>
        {/* 2026-10-17 (basit arayüz): Bildirimler menüden kalktı; tam liste buradan erişilir. */}
        <Link href="/notifications" className="mt-1 inline-flex min-h-[44px] items-center text-sm text-neon-green">Tüm bildirimler →</Link>
        <p className="mt-1 text-sm text-bunker-muted">
          Sistemin gönderdiği bildirimler hedefe ulaştı mı? Ölçüm bildirim fiyatından, ufuk süresi boyunca ulaşılan en yüksek getiriye göre yapılır.
        </p>
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Dönem">
          {periodBtn("since", "Yeni sistemden beri")}
          {periodBtn("today", "Bugün")}
        </div>
        {cut && period === "since" && (
          <p className="mt-2 text-xs text-bunker-muted">
            Yeni radar algoritması <span className="font-semibold u-num-info">{cut}</span> (UTC+3) tarihinde devreye girdi; rapor yalnız bu andan sonraki bildirimlerle hesaplanır.
          </p>
        )}
      </header>

      {failed && !data && <p role="alert" className="card u-card-bad p-3 text-sm u-num-bad">Rapor yüklenemedi, birazdan yeniden denenecek.</p>}

      <section aria-label="Özet" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi title="Başarı oranı" tone={rateTone(rate)} value={rate == null ? "—" : `%${rate.toFixed(0)}`}
          sub={evaluated === 0 ? "Henüz ölçülmedi" : `${hit}/${evaluated} bildirim hedefe ulaştı`} />
        <Kpi title="Hedefe ulaştı" tone="good" value={String(hit)} sub="tam başarılı" />
        <Kpi title="Kısmen" tone="warn" value={String(partial)} sub="yükseldi ama hedefe varmadı" />
        <Kpi title="Ulaşmadı" tone="bad" value={String(miss)} sub="hedefe yaklaşamadı" />
      </section>
      <p className="flex flex-wrap items-center gap-2 text-sm text-bunker-muted">
        <span className="u-chip u-chip-info">{rows.length} bildirim</span>
        <span className="u-chip u-chip-wait">{open} bekleyen / ölçülemedi</span>
        <span className="u-chip u-chip-good">Ort. en yüksek getiri: {avg == null ? "—" : `%${avg.toFixed(2).replace(".", ",")}`}</span>
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <RateBars title="Teyit sayısına göre" hint="Aynı anda kaç kaynak aynı coini işaret etti" rows={confluenceRows} />
        <RateBars title="Kaynağa göre" hint="Sinyali üreten tarama türü" rows={sourceRows} />
      </div>

      <section aria-label="Bildirim listesi" className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Bildirim ayrıntıları</h2>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sonuç süzgeci">
          {resultBtn("all", "Tümü")}{resultBtn("hit", "Hedefe ulaştı")}{resultBtn("partial", "Kısmen")}
          {resultBtn("miss", "Ulaşmadı")}{resultBtn("open", "Bekleyen")}
        </div>

        {filtered.length === 0 ? (
          <div className="card p-4 text-sm text-bunker-muted">Bu süzgece uyan bildirim yok.</div>
        ) : (
          <>
            <div className="space-y-2 md:hidden">
              {filtered.slice(0, shown).map((r) => {
                const st = statusLabel(r.status);
                return (
                  <article key={r.id} className="card p-3">
                    <div className="flex min-h-[44px] items-center justify-between gap-2">
                      <SymbolLink symbol={r.symbol} className="font-mono text-base font-bold text-white" />
                      <span className={`u-chip u-chip-${toneClass(st.tone)}`}>{st.label}</span>
                    </div>
                    <p className="text-xs text-bunker-muted">{fmtDateTime(r.detected_at)}</p>
                    <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
                      <div><dt className="text-xs text-bunker-muted">Hedef</dt><dd className="font-semibold">%{r.target_pct ?? "—"}</dd></div>
                      <div><dt className="text-xs text-bunker-muted">Ufuk</dt><dd className="font-semibold">{r.horizon_minutes ?? "—"} dk</dd></div>
                      <div><dt className="text-xs text-bunker-muted">En yüksek</dt>
                        <dd className="font-semibold">{r.mfe_pct == null ? "—" : `%${Number(r.mfe_pct).toFixed(2)}`}</dd></div>
                    </dl>
                    {r.sources?.length ? <p className="mt-2 flex flex-wrap gap-1">{r.sources.map((s) => <span key={s} className="u-chip u-chip-info">{sourceLabel(s)}</span>)}</p> : null}
                  </article>
                );
              })}
            </div>
            {/* Masaüstünde yatay kaydırma YOK: kompakt boşluk + hücreler satır sonuna sarılır (Kaynak/Zaman/başlıklar). */}
            <div className="card hidden overflow-hidden md:block">
              <table className="data-table table-compact w-full text-sm [&_td]:!whitespace-normal [&_th]:!whitespace-normal [&_td]:align-top">
                <thead><tr><th>Zaman</th><th>Sembol</th><th>Kaynak</th><th>Bildirim fiyatı</th><th>Hedef</th><th>Ufuk</th><th>En yüksek getiri</th><th>Sonuç</th></tr></thead>
                <tbody>
                  {filtered.slice(0, shown).map((r) => {
                    const st = statusLabel(r.status);
                    return (
                      <tr key={r.id}>
                        <td>{fmtDateTime(r.detected_at)}</td>
                        <td><SymbolLink symbol={r.symbol} className="font-mono font-bold text-white" /></td>
                        <td>{r.sources?.map((s) => sourceLabel(s)).join(", ") || "—"}</td>
                        <td>{formatPrice(r.price)}</td>
                        <td>%{r.target_pct ?? "—"}</td>
                        <td>{r.horizon_minutes ?? "—"} dk</td>
                        <td className="font-semibold">{r.mfe_pct == null ? "—" : `%${Number(r.mfe_pct).toFixed(2)}`}</td>
                        <td><span className={`u-chip u-chip-${toneClass(st.tone)}`}>{st.label}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {filtered.length > shown && (
              <button type="button" onClick={() => setShown((n) => n + PAGE)} className="u-btn-brand min-h-[44px] w-full rounded-xl px-4 text-sm">
                Daha fazla göster ({filtered.length - shown} bildirim daha)
              </button>
            )}
          </>
        )}
      </section>
    </div>
  );
}
