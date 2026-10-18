"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import SymbolLink from "../SymbolLink";
import {
  DAY_OPTIONS,
  DEFAULT_GROSS_FLOOR_PCT,
  RULE_OPTIONS,
  TIMEFRAME_OPTIONS,
  timeframeLabel,
  STATUS_OPTIONS,
  buildQuery,
  errorMessage,
  filterBySymbol,
  fmtPct,
  fmtShare,
  fmtSignalPrice,
  fmtThreshold,
  fmtTrTime,
  hitsGrossFloor,
  normalizeResponse,
  ruleLabel,
  signalTimeSec,
  sortSignals,
  statusChip,
  trackerLine,
  type MaBuyResponse,
  type MaBuySignal,
  type SortDir,
  type SortKey,
  type StatusTone,
} from "../../lib/maBuyUi";

const REFRESH_MS = 30_000;

type LoadError = { status: number | null; text: string } | null;

const TONE_CLASS: Record<StatusTone, string> = {
  wait: "ui-badge-warning",
  good: "ui-badge-positive",
  mute: "ui-badge-neutral",
};

const riseClass = (v: number | null) => (v === null ? "text-bunker-muted" : v > 0 ? "text-neon-green" : "text-bunker-muted");
const signedClass = (v: number | null) => (v === null ? "text-bunker-muted" : v > 0 ? "text-neon-green" : v < 0 ? "text-neon-red" : "text-bunker-muted");

function RuleTags({ rules }: { rules: string[] }) {
  if (rules.length === 0) return <span className="text-bunker-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {rules.map((r) => (
        <span key={r} className="ui-badge ui-badge-info" title={r}>{ruleLabel(r)}</span>
      ))}
    </span>
  );
}

function StatusChip({ item, nowSec }: { item: MaBuySignal; nowSec: number }) {
  const chip = statusChip(item, nowSec);
  return <span className={`ui-badge ${TONE_CLASS[chip.tone]}`}>{chip.label}</span>;
}

function FloorBadge({ floor }: { floor: number }) {
  return (
    <span className="ui-badge ui-badge-positive" title={`15 dk içinde en az ${fmtThreshold(floor)} yükseldi (net %1,5 hedefi + maliyet)`}>
      ≥ {fmtThreshold(floor)}
    </span>
  );
}

// `nowSec` yalnız ölçülen (open) satırlarda anlamlıdır; diğerlerinde 0 geçilir ki saniyelik tikte yeniden çizilmesinler.
const SignalRow = memo(function SignalRow({ item, floor, nowSec }: { item: MaBuySignal; floor: number; nowSec: number }) {
  const hit = hitsGrossFloor(item, floor);
  return (
    <tr>
      <td className="font-mono text-xs text-bunker-muted"><span title={`Yakalanma: ${fmtTrTime(item.detectedAt)}`}>{fmtTrTime(signalTimeSec(item))}</span></td>
      <td className="font-mono text-xs font-bold"><SymbolLink symbol={item.symbol} timeframe={item.timeframe} /></td>
      <td><span className="ui-badge ui-badge-info font-mono" title={`Sinyal ${timeframeLabel(item.timeframe)} mumunda tespit edildi`}>{timeframeLabel(item.timeframe)}</span></td>
      <td className="!whitespace-normal"><RuleTags rules={item.rules} /></td>
      <td className="font-mono text-xs text-right">{fmtSignalPrice(item.signalPrice)}</td>
      <td className={`font-mono text-xs text-right ${riseClass(item.maxRise5)}`}>{fmtPct(item.maxRise5)}</td>
      <td className={`font-mono text-xs text-right ${riseClass(item.maxRise10)}`}>{fmtPct(item.maxRise10)}</td>
      <td className={`font-mono text-xs text-right ${riseClass(item.maxRise15)}`}>
        <span className="inline-flex items-center justify-end gap-1.5">
          {hit && <FloorBadge floor={floor} />}
          <strong>{fmtPct(item.maxRise15)}</strong>
        </span>
      </td>
      <td className={`font-mono text-xs text-right ${item.maxDrop15 !== null && item.maxDrop15 < 0 ? "text-neon-red" : "text-bunker-muted"}`}>{fmtPct(item.maxDrop15)}</td>
      <td className={`font-mono text-xs text-right ${signedClass(item.close15)}`}>{fmtPct(item.close15)}</td>
      <td><StatusChip item={item} nowSec={nowSec} /></td>
    </tr>
  );
});

const SignalCard = memo(function SignalCard({ item, floor, nowSec }: { item: MaBuySignal; floor: number; nowSec: number }) {
  const hit = hitsGrossFloor(item, floor);
  return (
    <li className="rounded-lg border border-bunker-800 bg-bunker-950/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <SymbolLink symbol={item.symbol} timeframe={item.timeframe} className="font-mono text-base font-bold text-white hover:text-neon-green" />
            <span className="ui-badge ui-badge-info font-mono">{timeframeLabel(item.timeframe)}</span>
            {hit && <FloorBadge floor={floor} />}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">{fmtTrTime(signalTimeSec(item))} · fiyat {fmtSignalPrice(item.signalPrice)}</p>
        </div>
        <StatusChip item={item} nowSec={nowSec} />
      </div>
      <div className="mt-2"><RuleTags rules={item.rules} /></div>
      <dl className="mt-3 grid grid-cols-3 gap-2 font-mono text-xs">
        <div><dt className="text-[10px] uppercase text-bunker-muted">5 dk en yüksek</dt><dd className={riseClass(item.maxRise5)}>{fmtPct(item.maxRise5)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">10 dk en yüksek</dt><dd className={riseClass(item.maxRise10)}>{fmtPct(item.maxRise10)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">15 dk en yüksek</dt><dd className={`font-bold ${riseClass(item.maxRise15)}`}>{fmtPct(item.maxRise15)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">En büyük düşüş</dt><dd className={item.maxDrop15 !== null && item.maxDrop15 < 0 ? "text-neon-red" : "text-bunker-muted"}>{fmtPct(item.maxDrop15)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">15. dk kapanış</dt><dd className={signedClass(item.close15)}>{fmtPct(item.close15)}</dd></div>
      </dl>
    </li>
  );
});

function Stat({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="card !p-4">
      <p className="eyebrow">{label}</p>
      <p className={`mt-2 font-mono text-2xl font-bold ${tone ?? "text-white"}`}>{value}</p>
      {detail && <p className="mt-1 font-mono text-xs text-bunker-muted">{detail}</p>}
    </div>
  );
}

function SortHeader({ label, k, sortKey, sortDir, onSort, right }: { label: string; k: SortKey; sortKey: SortKey; sortDir: SortDir; onSort: (k: SortKey) => void; right?: boolean }) {
  const active = sortKey === k;
  return (
    <th aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"} className={right ? "text-right" : undefined}>
      <button type="button" onClick={() => onSort(k)} className={`uppercase tracking-[0.08em] hover:text-white ${active ? "text-white" : ""}`}>
        {label} {active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
      </button>
    </th>
  );
}

export default function MaBuySignals() {
  const [days, setDays] = useState<number>(7);
  const [rule, setRule] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [status, setStatus] = useState("");
  const [symbolQuery, setSymbolQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [data, setData] = useState<MaBuyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000));
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const response = await apiRequest(`${API_BASE}/api/admin/ma-buy-signals?${buildQuery({ days, rule, status, timeframe })}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (seq !== seqRef.current) return;
      if (!response.ok) {
        const detail = typeof body?.detail === "string" ? body.detail : null;
        if (response.status === 401 || response.status === 403) setData(null);
        setError({ status: response.status, text: errorMessage(response.status, detail) });
        return;
      }
      setData(normalizeResponse(body));
      setError(null);
      setLoadedAt(Math.floor(Date.now() / 1000));
      setNowSec(Math.floor(Date.now() / 1000));
    } catch (reason) {
      if (seq !== seqRef.current) return;
      setError({ status: null, text: reason instanceof Error && reason.message ? `Bağlantı hatası: ${reason.message}` : "Bağlantı hatası" });
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [days, rule, status, timeframe]);

  // Süzgeç değişince hemen yükle (sunucu süzgeçleri: gün, kural, durum).
  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  // 30 sn'de bir yenile (sekme görünürken). Süzgeç efekti ilk yüklemeyi yaptığı için runOnVisible kapalı değil: sekmeye dönünce tazelenir.
  useVisibleInterval(() => { void load(); }, REFRESH_MS);

  const items = useMemo(() => data?.items ?? [], [data]);
  const hasOpen = useMemo(() => items.some((x) => x.status === "open"), [items]);

  // Geri sayım: yalnız ölçülen sinyal varken saniyelik tik.
  useVisibleInterval(() => setNowSec(Math.floor(Date.now() / 1000)), hasOpen ? 1000 : null, { runOnVisible: true });

  const summary = data?.summary;
  const floor = summary?.grossFloorPct ?? DEFAULT_GROSS_FLOOR_PCT;

  const rows = useMemo(() => sortSignals(filterBySymbol(items, symbolQuery), sortKey, sortDir), [items, symbolQuery, sortKey, sortDir]);

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(k); setSortDir("desc"); }
  };

  const floorThreshold = summary?.thresholds.find((t) => Math.abs(t.minPct - floor) < 1e-6);
  const otherThresholds = summary?.thresholds.filter((t) => t !== floorThreshold) ?? [];
  const ruleEntries = summary ? Object.entries(summary.byRule) : [];
  const truncated = data !== null && data.total > items.length;
  const forbidden = error?.status === 403 || error?.status === 401;

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">SİSTEM YÖNETİMİ · YALNIZ YÖNETİCİ</p>
          <h1 className="font-mono text-2xl font-bold text-white">MA BUY sinyal kaydı</h1>
          <p className="mt-1 text-sm text-bunker-muted">
            Aktif sembollerin 5 dakikalık mumlarında hareketli ortalama şeridi alım kuralı tetiklenince kaydedilir; 15 dakika sonra en yüksek yükseliş ölçülür.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/settings" className="ui-button ui-button-secondary">← AYARLAR</Link>
          <button type="button" onClick={() => { setLoading(true); void load(); }} disabled={loading} className="ui-button ui-button-secondary disabled:opacity-50">
            {loading ? "YÜKLENİYOR…" : "YENİLE"}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg border border-neon-red/40 bg-neon-red/10 px-4 py-3 text-sm text-neon-red">
          {error.text}
          {error.status === 401 && <> <Link href="/" className="underline">Giriş ekranına dön</Link></>}
        </div>
      )}

      {!forbidden && (
        <>
          {data && (
            <p className="mb-4 font-mono text-xs text-bunker-muted">
              {trackerLine(data.tracker)}
              {data.tracker.timeframes.length > 0 && <> · {data.tracker.timeframes.join(", ")}</>}
              {data.tracker.scope && <> · kapsam: {data.tracker.scope === "active" ? "aktif semboller" : data.tracker.scope}</>}
              {loadedAt !== null && <> · liste {fmtTrTime(loadedAt)}&apos;de alındı · 30 sn&apos;de bir yenilenir</>}
            </p>
          )}

          {summary && (
            <section aria-label="Özet" className="space-y-3">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Toplam sinyal" value={summary.count.toLocaleString("tr-TR")} detail={`son ${data?.days ?? days} gün`} />
                <Stat label="Değerlendirilen / bekleyen" value={`${summary.evaluated.toLocaleString("tr-TR")} / ${summary.pending.toLocaleString("tr-TR")}`} detail="ölçüldü / 15 dk dolmadı" />
                <Stat label="15 dk en yüksek yükseliş" value={fmtPct(summary.avgMaxRise15, 2, true)} tone={riseClass(summary.avgMaxRise15)} detail={`ortalama · medyan ${fmtPct(summary.medianMaxRise15)}`} />
                <Stat label="Ort. en büyük düşüş" value={fmtPct(summary.avgMaxDrop15)} tone={signedClass(summary.avgMaxDrop15)} detail={`15. dk kapanış ort. ${fmtPct(summary.avgClose15)}`} />
              </div>

              <div className="card !p-4">
                <p className="eyebrow">15 DK İÇİNDE EN AZ EŞİĞİ GÖREN SİNYAL PAYI</p>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                  <div className="rounded-lg border border-neon-green/40 bg-neon-green/5 p-3">
                    <p className="font-mono text-[11px] text-bunker-muted">≥ {fmtThreshold(floor)} (net %1,5)</p>
                    <p className="mt-1 font-mono text-2xl font-bold text-neon-green">{floorThreshold ? fmtShare(floorThreshold.share) : "—"}</p>
                    <p className="font-mono text-[11px] text-bunker-muted">{floorThreshold?.n != null ? `${floorThreshold.n} sinyal` : "veri yok"}</p>
                  </div>
                  {otherThresholds.map((t) => (
                    <div key={t.minPct} className="rounded-lg border border-bunker-800 p-3">
                      <p className="font-mono text-[11px] text-bunker-muted">≥ {fmtThreshold(t.minPct)}</p>
                      <p className="mt-1 font-mono text-2xl font-bold text-white">{fmtShare(t.share)}</p>
                      <p className="font-mono text-[11px] text-bunker-muted">{t.n != null ? `${t.n} sinyal` : "veri yok"}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-2 font-mono text-[11px] text-bunker-muted">Pay, değerlendirilen sinyaller üzerinden hesaplanır. Brüt taban {fmtThreshold(floor)} = net %1,5 hedef + işlem maliyeti.</p>
              </div>

              {ruleEntries.length > 0 && (
                <div className="card !p-0">
                  <p className="eyebrow px-4 pt-4">KURAL BAZINDA</p>
                  <div className="overflow-x-auto">
                    <table className="data-table table-compact mt-2">
                      <thead>
                        <tr><th>Kural</th><th className="text-right">Sinyal</th><th className="text-right">Değerlendirilen</th><th className="text-right">Ort. 15 dk yükseliş</th><th className="text-right">Medyan</th></tr>
                      </thead>
                      <tbody>
                        {ruleEntries.map(([key, st]) => (
                          <tr key={key}>
                            <td className="!whitespace-normal">{ruleLabel(key)}</td>
                            <td className="text-right">{st.count ?? "—"}</td>
                            <td className="text-right">{st.evaluated ?? "—"}</td>
                            <td className={`text-right ${riseClass(st.avgMaxRise15)}`}>{fmtPct(st.avgMaxRise15)}</td>
                            <td className={`text-right ${riseClass(st.medianMaxRise15)}`}>{fmtPct(st.medianMaxRise15)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}

          <div className="card mt-5 !p-0">
            <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 p-3">
              <label className="flex items-center gap-1.5 font-mono text-xs text-bunker-muted">
                Gün
                <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="input !w-auto" aria-label="Gün aralığı">
                  {DAY_OPTIONS.map((d) => <option key={d} value={d}>{d === 1 ? "Son 1 gün" : `Son ${d} gün`}</option>)}
                </select>
              </label>
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className="input !w-auto" aria-label="Zaman dilimi">
                {TIMEFRAME_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <select value={rule} onChange={(e) => setRule(e.target.value)} className="input !w-auto" aria-label="Kural">
                {RULE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="input !w-auto" aria-label="Durum">
                {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <input value={symbolQuery} onChange={(e) => setSymbolQuery(e.target.value)} className="input min-w-36 flex-1" placeholder="Sembol ara (örn. SAND)" aria-label="Sembol ara" />
              <button type="button" onClick={() => { setDays(7); setRule(""); setTimeframe(""); setStatus(""); setSymbolQuery(""); }} className="ui-button ui-button-secondary">SIFIRLA</button>
              <span className="ml-auto font-mono text-xs text-bunker-muted">
                {rows.length.toLocaleString("tr-TR")} satır{data && data.total !== rows.length ? ` / ${data.total.toLocaleString("tr-TR")} kayıt` : ""}
              </span>
            </div>

            {loading && !data ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Yükleniyor…</p>
            ) : !data ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Veri alınamadı.</p>
            ) : rows.length === 0 ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">
                {items.length === 0 ? "Bu aralıkta kayıtlı MA BUY sinyali yok." : "Aramayla eşleşen sinyal yok."}
              </p>
            ) : (
              <>
                {/* Masaüstü: tablo */}
                <div className="hidden overflow-x-auto md:block">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <SortHeader label="Mum zamanı" k="time" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                        <th>Sembol</th>
                        <th>Zaman dilimi</th>
                        <th>Kural</th>
                        <th className="text-right">Sinyal fiyatı</th>
                        <th className="text-right">5 dk ↑</th>
                        <th className="text-right">10 dk ↑</th>
                        <SortHeader label="15 dk ↑" k="rise15" sortKey={sortKey} sortDir={sortDir} onSort={onSort} right />
                        <th className="text-right">En büyük düşüş</th>
                        <th className="text-right">15. dk kapanış</th>
                        <th>Durum</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((item) => (
                        <SignalRow key={item.id} item={item} floor={floor} nowSec={item.status === "open" ? nowSec : 0} />
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* Mobil: kart listesi */}
                <div className="md:hidden">
                  <div className="flex items-center gap-2 border-b border-bunker-800 px-3 py-2 font-mono text-xs text-bunker-muted">
                    Sırala:
                    <button type="button" onClick={() => onSort("time")} className={`rounded border border-bunker-700 px-2 py-1 ${sortKey === "time" ? "text-white" : ""}`}>Mum zamanı {sortKey === "time" ? (sortDir === "asc" ? "▲" : "▼") : ""}</button>
                    <button type="button" onClick={() => onSort("rise15")} className={`rounded border border-bunker-700 px-2 py-1 ${sortKey === "rise15" ? "text-white" : ""}`}>15 dk ↑ {sortKey === "rise15" ? (sortDir === "asc" ? "▲" : "▼") : ""}</button>
                  </div>
                  <ul className="space-y-2 p-3">
                    {rows.map((item) => (
                      <SignalCard key={item.id} item={item} floor={floor} nowSec={item.status === "open" ? nowSec : 0} />
                    ))}
                  </ul>
                </div>
              </>
            )}
          </div>

          {truncated && (
            <p className="mt-3 font-mono text-[11px] text-bunker-muted">
              Toplam {data!.total.toLocaleString("tr-TR")} kayıttan en yeni {items.length.toLocaleString("tr-TR")} tanesi listelendi.
            </p>
          )}
          <p className="mt-3 font-mono text-[11px] text-bunker-muted">
            Yükselişler sinyal mumunun kapanışına göre, sonraki 5/10/15 dakikadaki en yüksek fiyattan hesaplanır. Bu kayıt yalnızca ölçümdür; emir vermez, bildirim göndermez. Saatler Türkiye saatidir.
          </p>
        </>
      )}
    </main>
  );
}
