"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API_BASE, apiRequest } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useModalA11y } from "../../lib/useModalA11y";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import SymbolLink from "../SymbolLink";
import {
  MAX_RENDER_ROWS,
  buildQuery,
  errorMessage,
  filterRows,
  fmtHorizon,
  fmtPctValue,
  fmtPrice,
  fmtRatio,
  fmtRsiMfi,
  fmtScore,
  fmtTrTime,
  limitRows,
  normalizeResponse,
  poolLine,
  reasonMeta,
  notifyContextBadges,
  riskBadge,
  scanLabel,
  selectedIndex,
  sortRows,
  statusMeta,
  statusSummary,
  stepIndex,
  thresholdLabel,
  toneBadgeClass,
  type RadarLogResponse,
  type RadarLogRow,
} from "../../lib/radarLogUi";

const REFRESH_MS = 30_000;
const TITLE_ID = "radar-scan-log-title";

type LoadError = { status: number | null; text: string } | null;

const signedClass = (v: number | null) => (v === null ? "text-bunker-muted" : v > 0 ? "text-neon-green" : v < 0 ? "text-neon-red" : "text-bunker-muted");

function ToneBadge({ tone, label, title }: { tone: string; label: string; title?: string }) {
  return <span className={`ui-badge ${toneBadgeClass(tone)}`} title={title}>{label}</span>;
}

function ReasonBadge({ code, raw }: { code: string | null; raw?: string | null }) {
  const meta = reasonMeta(code);
  if (!meta) return null;
  return <ToneBadge tone={meta.tone} label={meta.label} title={raw ?? (meta.known ? code ?? undefined : `Bilinmeyen neden kodu: ${code}`)} />;
}

/** Ufuk bazında geçti/elendi notları (en çok birkaç küçük rozet). */
function HorizonNotes({ row }: { row: RadarLogRow }) {
  if (row.horizons.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {row.horizons.map((h) => {
        if (h.passes === true) {
          return <ToneBadge key={h.horizon} tone="success" label={`${fmtHorizon(h.horizon)} ✓`} title={`${fmtHorizon(h.horizon)} ufku geçti`} />;
        }
        const meta = reasonMeta(h.reasonCode);
        if (h.passes === false) {
          return (
            <ToneBadge
              key={h.horizon}
              tone={meta?.tone ?? "neutral"}
              label={`${fmtHorizon(h.horizon)} ✗${meta ? ` ${meta.label}` : ""}`}
              title={h.reason ?? `${fmtHorizon(h.horizon)} ufku elendi`}
            />
          );
        }
        return <ToneBadge key={h.horizon} tone="muted" label={`${fmtHorizon(h.horizon)} ?`} title={h.reason ?? "Sonuç yok"} />;
      })}
    </span>
  );
}

function ReasonCell({ row }: { row: RadarLogRow }) {
  const hasAny = row.reasonCode || row.reason || row.horizons.length > 0;
  if (!hasAny) return <span className="text-bunker-muted">—</span>;
  return (
    <span className="flex min-w-0 flex-col items-start">
      {row.reasonCode && <ReasonBadge code={row.reasonCode} raw={row.reason} />}
      {row.reason && <span className="mt-1 whitespace-normal break-words text-[11px] text-bunker-muted">{row.reason}</span>}
      <HorizonNotes row={row} />
    </span>
  );
}

function StatusBadge({ row }: { row: RadarLogRow }) {
  return <ToneBadge tone={row.tone} label={row.label} title={row.status} />;
}

const LogRow = memo(function LogRow({ row }: { row: RadarLogRow }) {
  return (
    <tr>
      <td className="font-mono text-xs font-bold">
        <SymbolLink symbol={row.symbol} timeframe="5m" />
        <span className="block text-[10px] font-normal text-bunker-muted">{fmtPrice(row.price)}{row.mode ? ` · ${row.mode}` : ""}</span>
      </td>
      <td><StatusBadge row={row} /></td>
      <td className="!whitespace-normal"><ReasonCell row={row} /></td>
      <td className="text-right font-mono text-xs font-bold">{fmtScore(row.panelScore)}</td>
      <td className="text-right font-mono text-xs">{fmtPctValue(row.atrPct)}</td>
      <td className="text-right font-mono text-xs">{fmtRsiMfi(row.rsi, row.mfi)}</td>
      <td className={`text-right font-mono text-xs ${signedClass(row.ret3Pct)}`}>{fmtPctValue(row.ret3Pct, 2, true)}</td>
      <td className="text-right font-mono text-xs">{fmtRatio(row.volumeRatio)}</td>
      <td className="text-right font-mono text-xs">{fmtHorizon(row.horizon)}</td>
      <td className="text-right font-mono text-xs">{fmtPctValue(row.targetPct, 1)}</td>
    </tr>
  );
});

const LogCard = memo(function LogCard({ row }: { row: RadarLogRow }) {
  return (
    <li className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <SymbolLink symbol={row.symbol} timeframe="5m" className="font-mono text-base font-bold text-white hover:text-neon-green" />
          <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">{fmtPrice(row.price)}{row.mode ? ` · ${row.mode}` : ""}</p>
        </div>
        <StatusBadge row={row} />
      </div>
      <div className="mt-2"><ReasonCell row={row} /></div>
      <dl className="mt-3 grid grid-cols-3 gap-2 font-mono text-xs">
        <div><dt className="text-[10px] uppercase text-bunker-muted">Skor</dt><dd className="font-bold">{fmtScore(row.panelScore)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">ATR</dt><dd>{fmtPctValue(row.atrPct)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">RSI / MFI</dt><dd>{fmtRsiMfi(row.rsi, row.mfi)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">3 mum</dt><dd className={signedClass(row.ret3Pct)}>{fmtPctValue(row.ret3Pct, 2, true)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">Hacim</dt><dd>{fmtRatio(row.volumeRatio)}</dd></div>
        <div><dt className="text-[10px] uppercase text-bunker-muted">Ufuk / hedef</dt><dd>{fmtHorizon(row.horizon)} · {fmtPctValue(row.targetPct, 1)}</dd></div>
      </dl>
    </li>
  );
});

type ModalProps = { onClose: () => void };

/** Pencere gövdesi. Yalnız admin rolünde çizilir; yönetici değilse null. */
export function RadarScanLogModal({ onClose }: ModalProps) {
  const { role } = useAuth();
  const [data, setData] = useState<RadarLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [auto, setAuto] = useState(true);
  const [selectedNo, setSelectedNo] = useState<number | null>(null); // null = en yeni taramayı izle
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const seqRef = useRef(0);

  const a11y = useModalA11y(true, onClose, "Radar tarama logları");

  // Açıkken arka sayfanın kaymasını engelle.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      const response = await apiRequest(`${API_BASE}/api/admin/radar-scan-log?${buildQuery({ limit: 10 })}`, { cache: "no-store" });
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
    } catch (reason) {
      if (seq !== seqRef.current) return;
      setError({ status: null, text: reason instanceof Error && reason.message ? `Bağlantı hatası: ${reason.message}` : "Bağlantı hatası" });
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => { seqRef.current += 1; }; // kapanınca uçuştaki yanıtı yok say
  }, [load]);

  // Pencere görünürken (sekme açıkken) 30 sn'de bir tazele.
  useVisibleInterval(() => { void load(); }, auto ? REFRESH_MS : null);

  const scans = useMemo(() => data?.scans ?? [], [data]);
  const catalog = useMemo(() => data?.statusCatalog ?? [], [data]);
  const idx = selectedIndex(scans, selectedNo);
  const scan = idx >= 0 ? scans[idx] : null;

  const summary = useMemo(() => statusSummary(scan, catalog), [scan, catalog]);
  const rows = useMemo(
    () => (scan ? sortRows(filterRows(scan.rows, { status: statusFilter, query })) : []),
    [scan, statusFilter, query],
  );
  const { shown, hidden } = useMemo(() => limitRows(rows, MAX_RENDER_ROWS), [rows]);

  const forbidden = error?.status === 401 || error?.status === 403;
  const risk = scan ? riskBadge(scan) : null;
  const filtering = statusFilter !== "" || query.trim() !== "";

  const go = (dir: 1 | -1) => {
    const next = stepIndex(idx, dir, scans.length);
    if (next < 0) return;
    setSelectedNo(next === 0 ? null : scans[next].scanNo);
  };

  if (role !== "admin") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[110] flex items-stretch justify-center bg-black/75 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={onClose}
      data-testid="radar-scan-log-overlay"
    >
      <section
        ref={a11y.ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={TITLE_ID}
        tabIndex={-1}
        onKeyDown={a11y.onKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col overflow-hidden border border-bunker-700 bg-bunker-950 shadow-2xl outline-none sm:h-auto sm:max-h-[92vh] sm:max-w-6xl sm:rounded-xl"
      >
        {/* Başlık */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-bunker-800 px-4 py-3">
          <div className="min-w-0">
            <p className="eyebrow">SİSTEM YÖNETİMİ · YALNIZ YÖNETİCİ</p>
            <h2 id={TITLE_ID} className="font-mono text-lg font-bold text-white">Radar tarama logları</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 font-mono text-xs text-bunker-muted">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              Otomatik (30 sn)
            </label>
            <button type="button" onClick={() => void load()} disabled={loading} className="ui-button ui-button-secondary disabled:opacity-50">
              {loading ? "YÜKLENİYOR…" : "YENİLE"}
            </button>
            <button type="button" onClick={onClose} aria-label="Pencereyi kapat" className="ui-button ui-button-ghost" data-testid="radar-scan-log-close">✕</button>
          </div>
        </div>

        {/* Gövde */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {error && (
            <div role="alert" className="m-3 rounded-lg border border-neon-red/40 bg-neon-red/10 px-4 py-3 text-sm text-neon-red">
              {error.text}
            </div>
          )}

          {!forbidden && (
            <>
              {loading && !data ? (
                <p className="py-12 text-center font-mono text-sm text-bunker-muted">Yükleniyor…</p>
              ) : !data ? (
                <p className="py-12 text-center font-mono text-sm text-bunker-muted">Veri alınamadı.</p>
              ) : !scan ? (
                <p className="py-12 text-center font-mono text-sm text-bunker-muted">Henüz kayıtlı radar taraması yok.</p>
              ) : (
                <>
                  {/* Tarama seçici */}
                  <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 px-4 py-3">
                    <button type="button" onClick={() => go(1)} disabled={idx >= scans.length - 1} className="ui-button ui-button-secondary" aria-label="Önceki (daha eski) tarama">‹ Eski</button>
                    <select
                      value={scan.scanNo}
                      onChange={(e) => {
                        const no = Number(e.target.value);
                        setSelectedNo(scans[0]?.scanNo === no ? null : no);
                      }}
                      className="input !w-auto"
                      aria-label="Tarama seç"
                    >
                      {scans.map((s, i) => (
                        <option key={s.scanNo} value={s.scanNo}>{scanLabel(s)}{i === 0 ? " (en yeni)" : ""}</option>
                      ))}
                    </select>
                    <button type="button" onClick={() => go(-1)} disabled={idx <= 0} className="ui-button ui-button-secondary" aria-label="Sonraki (daha yeni) tarama">Yeni ›</button>
                    <span className="ml-auto font-mono text-[11px] text-bunker-muted">
                      {data.totalScans.toLocaleString("tr-TR")} kayıtlı tarama{data.keep !== null ? ` (son ${data.keep.toLocaleString("tr-TR")} saklanır)` : ""}
                      {loadedAt !== null && <> · {fmtTrTime(loadedAt)}&apos;de alındı</>}
                    </span>
                  </div>

                  {/* Özet satırı */}
                  <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 px-4 py-3" aria-label="Tarama özeti">
                    {summary.length === 0 && <span className="font-mono text-xs text-bunker-muted">Bu taramada sayaç yok.</span>}
                    {summary.map((s) => {
                      const active = statusFilter === s.status;
                      return (
                        <button
                          key={s.status}
                          type="button"
                          aria-pressed={active}
                          onClick={() => setStatusFilter(active ? "" : s.status)}
                          title={active ? "Süzgeci kaldır" : `Yalnız “${s.label}” satırlarını göster`}
                          className={`ui-badge ${toneBadgeClass(s.tone)} cursor-pointer !min-h-8 gap-1.5 !px-2.5 ${active ? "ring-2 ring-current" : "opacity-90 hover:opacity-100"}`}
                        >
                          {s.label}
                          <strong className="text-[0.8rem]">{s.count.toLocaleString("tr-TR")}</strong>
                        </button>
                      );
                    })}
                    {risk && <ToneBadge tone={risk.tone} label={risk.label} />}
                    {notifyContextBadges(scan.notifyContext).map((b) => <ToneBadge key={b.label} tone={b.tone} label={b.label} />)}
                    <ToneBadge tone="info" label={thresholdLabel(scan.minPanelScore)} />
                    <span className="font-mono text-[11px] text-bunker-muted">Havuz: {poolLine(scan.pool)}</span>
                  </div>

                  {/* Arama + sayaç */}
                  <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 px-4 py-3">
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      className="input min-w-36 flex-1"
                      placeholder="Sembol ara (örn. SAND)"
                      aria-label="Sembol ara"
                    />
                    {filtering && (
                      <button type="button" onClick={() => { setStatusFilter(""); setQuery(""); }} className="ui-button ui-button-secondary">SÜZGECİ TEMİZLE</button>
                    )}
                    <span className="ml-auto font-mono text-xs text-bunker-muted">
                      {rows.length.toLocaleString("tr-TR")} satır{statusFilter ? ` · ${statusMeta(statusFilter, catalog).label}` : ""}
                    </span>
                  </div>

                  {rows.length === 0 ? (
                    <p className="py-10 text-center font-mono text-sm text-bunker-muted">
                      {scan.rows.length === 0 ? "Bu taramada kayıtlı satır yok." : "Süzgece uyan satır yok."}
                    </p>
                  ) : (
                    <>
                      {/* Masaüstü: tablo */}
                      <div className="hidden overflow-x-auto md:block">
                        <table className="data-table table-compact">
                          <thead>
                            <tr>
                              <th>Sembol</th>
                              <th>Durum</th>
                              <th>Neden</th>
                              <th className="text-right">Skor</th>
                              <th className="text-right">ATR%</th>
                              <th className="text-right">RSI / MFI</th>
                              <th className="text-right">3 mum</th>
                              <th className="text-right">Hacim</th>
                              <th className="text-right">Ufuk</th>
                              <th className="text-right">Hedef</th>
                            </tr>
                          </thead>
                          <tbody>
                            {shown.map((row, i) => <LogRow key={`${row.symbol}-${i}`} row={row} />)}
                          </tbody>
                        </table>
                      </div>
                      {/* Mobil: kart listesi */}
                      <ul className="space-y-2 p-3 md:hidden">
                        {shown.map((row, i) => <LogCard key={`${row.symbol}-${i}`} row={row} />)}
                      </ul>
                      {hidden > 0 && (
                        <p className="px-4 pb-3 font-mono text-xs text-bunker-muted" data-testid="radar-scan-log-more">
                          {hidden.toLocaleString("tr-TR")} satır daha var — listeyi daraltmak için durum rozetine tıklayın ya da sembol arayın.
                        </p>
                      )}
                    </>
                  )}

                  <p className="px-4 pb-4 pt-1 font-mono text-[11px] text-bunker-muted">
                    Sıralama: bildirilen, tespit edilen ve kapıya takılanlar önde; sonra panel skoruna göre azalan. Her rozet taramada o sembolün neden o durumda olduğunu söyler. Saatler Türkiye saatidir.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}

/**
 * "Tarama logları" düğmesi + pencere. Yalnız admin rolünde çizilir (başka rolde null);
 * pencere kapalıyken ağ isteği yapılmaz. Sunucu da 401/403 ile korur.
 */
export function RadarScanLogButton({ className = "ui-button ui-button-secondary text-xs" }: { className?: string }) {
  const { role } = useAuth();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  if (role !== "admin") return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={className} data-testid="radar-scan-log-button" title="Her taramada neler tespit edildi, neler hangi nedenle elendi">
        📋 TARAMA LOGLARI
      </button>
      {open && <RadarScanLogModal onClose={close} />}
    </>
  );
}

export default RadarScanLogButton;
