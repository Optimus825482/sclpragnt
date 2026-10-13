"use client";

import { useMemo, useState } from "react";
import { apiRequest } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { formatPct, fmtDateTime, formatPrice } from "../lib/format";
import { baseAsset, toOpportunityView } from "../lib/opportunity";
import { sourceLabel } from "../lib/sources";
import { useWatchlist } from "../lib/watchlist";
import { sound } from "../lib/sound";
import type { ManualUnifiedScanResponse, NotificationsResponse, UnifiedScanHistoryResponse, UnifiedScanRun } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton, Tabs } from "../components/ui";
import { downloadCsv, toCsv } from "../lib/csv";

type Tab = "live" | "history";
type LiveRow = { view: ReturnType<typeof toOpportunityView>; kind: string; detectedAt: number | null };
type EngineSummary = {
  hit_rate?: number | null;
  measured?: number;
  ceiling_hits?: number;
  avg_mfe_pct?: number | null;
  avg_sent_gain_all_pct?: number | null;
  avg_sent_gain_today_pct?: number | null;
  avg_sim_all_pct?: number | null;
  report_count?: number;
  by_source?: Record<string, { measured: number; ceiling_hits: number; hit_rate: number | null; avg_mfe_pct: number | null }>;
};

const PAGE_SIZE = 25;

export default function FirsatlarPage() {
  const [tab, setTab] = useState<Tab>("live");
  const [search, setSearch] = useState("");
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [manualBusy, setManualBusy] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualMessage, setManualMessage] = useState<string | null>(null);
  const [manualRun, setManualRun] = useState<UnifiedScanRun | null>(null);

  const { isFavorite, toggleFavorite } = useWatchlist();
  const latestScan = usePoll<{ run: UnifiedScanRun | null }>("/api/unified-scan/latest", 20_000, 30_000);
  const scanHistory = usePoll<UnifiedScanHistoryResponse>("/api/unified-scan/history?limit=30", 60_000);

  const latestRun = latestScan.data?.run ?? null;
  const latestRunAt = Number(latestRun?.completed_at ?? latestRun?.generated_at ?? 0);
  const run = manualRun && Number(manualRun.completed_at || 0) >= latestRunAt ? manualRun : latestRun;

  async function runManualScan() {
    if (manualBusy) return;
    setManualBusy(true);
    setManualError(null);
    setManualMessage("Salt-veri piyasa taraması başlatılıyor…");
    try {
      const response = await apiRequest("/api/unified-scan/manual", { method: "POST" });
      const body = await response.json().catch(() => ({})) as ManualUnifiedScanResponse & { detail?: string };
      if (!response.ok) throw new Error(body?.detail || `Tarama başarısız (HTTP ${response.status})`);
      if (!body.ok || body.side_effects.notifications_sent || body.side_effects.paper_positions_opened || body.side_effects.real_orders_submitted) throw new Error("Tarama güvenlik doğrulaması başarısız oldu");
      const nextRun: UnifiedScanRun = {
        scan_id: body.scan_id,
        started_at: body.started_at,
        completed_at: body.completed_at,
        algorithm_version: body.algorithm_version,
        source: "manual",
        count: body.count,
        candidates: body.candidates,
      };
      setManualRun(nextRun);
      setManualMessage(`Tarama tamamlandı · ${body.count} aday · emir/bildirim yok`);
      sound.playSignalChime();
      latestScan.reload();
      scanHistory.reload();
      window.setTimeout(() => setManualMessage(null), 5000);
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "Manuel tarama başarısız oldu.");
      window.setTimeout(() => setManualError(null), 5000);
    } finally {
      setManualBusy(false);
    }
  }

  const live = useMemo(() => {
    const now = Date.now() / 1000;
    const rows: LiveRow[] = (run?.candidates || []).map((candidate) => {
      const view = toOpportunityView(candidate);
      return {
        view,
        kind: "Birleşik aday",
        detectedAt: Number(candidate.detected_at ?? candidate.created_at ?? run?.completed_at ?? run?.generated_at ?? now) || null,
      };
    });
    return rows.filter(({ view }) => {
      if (onlyFavorites && !isFavorite(view.symbol)) return false;
      if (search.trim() && !view.symbol.includes(search.trim().toUpperCase())) return false;
      return true;
    }).sort((left, right) => (right.view.strength ?? 0) - (left.view.strength ?? 0));
  }, [run, onlyFavorites, search, isFavorite]);

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Sinyal & Tarama"
        title="Fırsat Motoru & Başarı Karnesi"
        description="Sistemin ürettiği anlık yükseliş tespitleri, geçmiş sinyaller ve başarı oranları (hit-rate)."
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={runManualScan}
              disabled={manualBusy}
              className="rounded-lg bg-accent px-3 py-2 text-xs sm:text-sm font-semibold text-white shadow-sm hover:bg-accent/90 disabled:opacity-60 flex items-center gap-1.5"
            >
              <span className={manualBusy ? "animate-spin" : ""}>⚡</span>
              <span>{manualBusy ? "Taranıyor…" : "Şimdi Tara"}</span>
            </button>
            <Tabs
              items={[
                { id: "live", label: `Anlık Tespitler (${live.length})` },
                { id: "history", label: "Tarama Geçmişi & Başarı" },
              ]}
              active={tab}
              onChange={(id) => setTab(id as Tab)}
            />
          </div>
        }
      />

      {/* Arama ve Hızlı Filtre Barı */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white p-3 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Sembol filtrele (ör. SOL)..."
            className="rounded-lg border border-line bg-canvas px-3 py-1.5 text-xs font-mono outline-none focus:border-accent w-48"
          />
          <button
            type="button"
            onClick={() => setOnlyFavorites(!onlyFavorites)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1.5 ${
              onlyFavorites
                ? "border-amber-400 bg-amber-50 text-amber-700 font-bold"
                : "border-line bg-white text-ink-600 hover:border-amber-400"
            }`}
          >
            <span>{onlyFavorites ? "★" : "☆"}</span>
            <span>Sadece Favoriler</span>
          </button>
        </div>

        {manualMessage && (
          <span className="text-xs font-semibold text-gain animate-in fade-in">{manualMessage}</span>
        )}
        {manualError && (
          <span className="text-xs font-semibold text-loss animate-in fade-in">{manualError}</span>
        )}
      </div>

      {tab === "live" ? (
        <LiveFeed loading={latestScan.loading && !run} error={latestScan.error} rows={live} isFavorite={isFavorite} toggleFavorite={toggleFavorite} />
      ) : (
        <HistorySection
          search={search}
          onlyFavorites={onlyFavorites}
          isFavorite={isFavorite}
          toggleFavorite={toggleFavorite}
          scanHistory={scanHistory.data?.runs ?? []}
          scanHistoryLoading={scanHistory.loading && !scanHistory.data}
        />
      )}
    </div>
  );
}

function LiveFeed({
  loading,
  error,
  rows,
  isFavorite,
  toggleFavorite,
}: {
  loading: boolean;
  error: string | null;
  rows: LiveRow[];
  isFavorite: (sym: string) => boolean;
  toggleFavorite: (sym: string) => void;
}) {
  if (loading) return <Skeleton className="h-64" />;
  if (error && rows.length === 0)
    return <EmptyState title="Birleşik tarama alınamadı" hint={error} tone="loss" />;
  if (rows.length === 0)
    return <EmptyState title="Uygun aday yok" hint="Yeni salt-veri taraması başlatabilir veya filtreleri değiştirebilirsiniz." />;

  const kindTone: Record<string, "accent" | "warn" | "gain"> = { Aday: "gain", Isınıyor: "warn", Nabız: "accent" };

  return (
    <Card className="p-4">
      <div className="odak-scroll">
        <table className="w-full min-w-[850px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
              <th className="pb-2 pr-2 font-medium w-8">★</th>
              <th className="pb-2 pr-3 font-medium">Sembol</th>
              <th className="pb-2 pr-3 font-medium">Durum</th>
              <th className="pb-2 pr-3 font-medium">Üreten Sistem</th>
              <th className="pb-2 pr-3 text-right font-medium">Fiyat</th>
              <th className="pb-2 pr-3 text-right font-medium">Değişim</th>
              <th className="pb-2 pr-3 text-right font-medium">Hedef</th>
              <th className="pb-2 pr-3 text-right font-medium">Skor</th>
              <th className="pb-2 text-right font-medium">Ufuk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ view, kind }, i) => {
              const fav = isFavorite(view.symbol);
              return (
                <tr key={`${view.symbol}-${view.horizonMinutes ?? 5}-${kind}-${i}`} className="border-t border-line hover:bg-slate-50/50">
                  <td className="py-2.5 pr-2">
                    <button
                      type="button"
                      onClick={() => toggleFavorite(view.symbol)}
                      className={`text-sm ${fav ? "text-amber-500" : "text-ink-300 hover:text-amber-500"}`}
                      title={fav ? "Favorilerden çıkar" : "Favoriye ekle"}
                    >
                      {fav ? "★" : "☆"}
                    </button>
                  </td>
                  <td className="py-2.5 pr-3">
                    <span className="font-mono font-bold text-ink-900">{view.base}</span>
                    <span className="text-xs text-ink-400"> / TRY</span>
                  </td>
                  <td className="py-2.5 pr-3">
                    <Badge tone={kindTone[kind] || "neutral"}>{kind}</Badge>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="flex flex-wrap gap-1">
                      {view.sources.length ? (
                        view.sources.slice(0, 3).map((s) => (
                          <Badge key={s} tone="accent">
                            {s}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-ink-400">—</span>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono text-ink-700">
                    {view.price != null ? formatPrice(view.price) : "—"}
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono ${(view.changePct ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
                    {formatPct(view.changePct, 2, true)}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono font-bold text-gain">
                    {formatPct(view.potentialPct, 1, true)}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono font-semibold text-accent">
                    {view.strength != null ? `%${Math.round(view.strength)}` : "—"}
                  </td>
                  <td className="py-2.5 text-right font-mono text-ink-500">
                    {view.horizonMinutes != null ? `${view.horizonMinutes} dk` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function HistorySection({
  search,
  onlyFavorites,
  isFavorite,
  toggleFavorite,
  scanHistory,
  scanHistoryLoading,
}: {
  search: string;
  onlyFavorites: boolean;
  isFavorite: (sym: string) => boolean;
  toggleFavorite: (sym: string) => void;
  scanHistory: UnifiedScanRun[];
  scanHistoryLoading: boolean;
}) {
  const [page, setPage] = useState(0);
  const { data, error, loading } = usePoll<NotificationsResponse>(
    "/api/reports/notifications?day=all&limit=400&history_only=true",
    60_000
  );
  const engineSummary = usePoll<EngineSummary>("/api/daily-rising/reports/summary?days=14&limit=200", 120_000);

  function exportScanHistoryCsv() {
    const headers = ["tarama_zamani", "surum", "sembol", "ufuk_dk", "kaynaklar", "fiyat", "skor"];
    const rows: Array<Array<string | number | null | undefined>> = [];
    for (const run of scanHistory) {
      const completed = run.completed_at ?? run.generated_at ?? null;
      for (const candidate of run.candidates || []) {
        rows.push([
          completed ? fmtDateTime(completed) : "",
          run.algorithm_version || "combined-v1",
          candidate.symbol,
          candidate.horizon_minutes ?? null,
          Array.isArray(candidate.unified_sources) ? candidate.unified_sources.join(" | ") : candidate.strategy || "",
          candidate.price ?? null,
          candidate.scan_score ?? candidate.quality_score ?? null,
        ]);
      }
    }
    downloadCsv(`tarama-gecmisi-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, rows));
  }

  const rawNotifications = data?.notifications || [];

  // BAŞARI KARNESİ HESAPLAMALARI
  const stats = useMemo(() => {
    let total = 0;
    let successful = 0;
    let failed = 0;
    let pending = 0;
    let sumMfe = 0;
    let mfeCount = 0;

    for (const n of rawNotifications) {
      total += 1;
      const status = String(n.status || "").toUpperCase();
      if (status.includes("BAŞARILI")) successful += 1;
      else if (status.includes("BAŞARISIZ")) failed += 1;
      else pending += 1;

      if (n.mfe_pct != null && Number(n.mfe_pct) > 0) {
        sumMfe += Number(n.mfe_pct);
        mfeCount += 1;
      }
    }

    const decided = successful + failed;
    const winRate = decided > 0 ? (successful / decided) * 100 : 0;
    const avgMfe = mfeCount > 0 ? sumMfe / mfeCount : 0;

    return { total, successful, failed, pending, winRate, avgMfe };
  }, [rawNotifications]);

  // Filtreleme
  const filtered = useMemo(() => {
    return rawNotifications.filter((n) => {
      const sym = String(n.symbol || "").toUpperCase();
      if (onlyFavorites && !isFavorite(sym)) return false;
      if (search.trim() && !sym.includes(search.trim().toUpperCase())) return false;
      return true;
    });
  }, [rawNotifications, onlyFavorites, search, isFavorite]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const slice = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (loading && !data && scanHistory.length === 0) return <Skeleton className="h-64" />;
  if (error && !data && scanHistory.length === 0) return <EmptyState title="Tarama geçmişi alınamadı" hint={error} tone="loss" />;
  if (rawNotifications.length === 0 && scanHistory.length === 0) return <EmptyState title="Kayıt yok" hint="Henüz tarama geçmişi veya başarı kaydı oluşmamış." />;

  return (
    <div className="space-y-4">
      {engineSummary.data && (engineSummary.data.by_source && Object.keys(engineSummary.data.by_source).length > 0) ? (
        <Card className="p-4">
          <SectionHeader
            eyebrow="Motor Başarı Paneli"
            title="Hangi motorun adayları hedefe ulaşıyor?"
            description="Son 14 günün gönderilen liste raporlarından ölçülen MFE ve hedef-tavan isabet oranları (kaynak bazında)."
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-canvas p-3">
              <p className="odak-kicker">Genel isabet</p>
              <p className="mt-1 font-mono text-xl font-bold text-gain">{engineSummary.data.hit_rate != null ? `%${engineSummary.data.hit_rate}` : "—"}</p>
              <p className="text-[11px] text-ink-400">{engineSummary.data.measured ?? 0} aday ölçüldü</p>
            </div>
            <div className="rounded-lg bg-canvas p-3">
              <p className="odak-kicker">Ort. tepe (MFE)</p>
              <p className="mt-1 font-mono text-xl font-bold text-accent">{engineSummary.data.avg_mfe_pct != null ? `+%${engineSummary.data.avg_mfe_pct}` : "—"}</p>
              <p className="text-[11px] text-ink-400">tüm zamanlar · {engineSummary.data.report_count ?? 0} rapor</p>
            </div>
            <div className="rounded-lg bg-canvas p-3">
              <p className="odak-kicker">Gerçekleşebilir ort. net %</p>
              <p className="mt-1 font-mono text-xl font-bold text-ink-900">{engineSummary.data.avg_sim_all_pct != null ? `${engineSummary.data.avg_sim_all_pct > 0 ? "+" : ""}%${engineSummary.data.avg_sim_all_pct}` : "—"}</p>
              <p className="text-[11px] text-ink-400">otonom paper kurallarıyla simülasyon</p>
            </div>
          </div>
          <div className="odak-scroll mt-3">
            <table className="w-full min-w-[520px] border-collapse text-sm">
              <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
                <th className="pb-2 pr-3 font-medium">Motor</th>
                <th className="pb-2 pr-3 text-right font-medium">Ölçülen</th>
                <th className="pb-2 pr-3 text-right font-medium">Tavan isabeti</th>
                <th className="pb-2 text-right font-medium">Ort. MFE</th>
              </tr></thead>
              <tbody>{Object.entries(engineSummary.data.by_source).map(([source, stat]) => (
                <tr key={source} className="border-t border-line">
                  <td className="py-2 pr-3 font-mono font-semibold text-ink-800">{sourceLabel(source) || source}</td>
                  <td className="py-2 pr-3 text-right font-mono text-ink-600">{stat.measured}</td>
                  <td className="py-2 pr-3 text-right font-mono font-semibold text-gain">{stat.hit_rate != null ? `%${stat.hit_rate}` : "—"}</td>
                  <td className="py-2 text-right font-mono text-ink-700">{stat.avg_mfe_pct != null ? `+%${stat.avg_mfe_pct}` : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <Card className="p-4">
        <SectionHeader
          eyebrow="Birleşik tarama geçmişi"
          title="Kalıcı aday anlık görüntüleri"
          description="Her manuel taramanın zamanı, sürümü ve adayları kullanıcı hesabına özel saklanır."
          actions={
            <button type="button" onClick={exportScanHistoryCsv} disabled={scanHistory.length === 0}
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent-soft disabled:opacity-40"
              title="Tarama geçmişini CSV olarak indir">
              ⤓ CSV indir
            </button>
          }
        />
        {scanHistoryLoading ? <Skeleton className="mt-3 h-20" /> : scanHistory.length === 0 ? (
          <p className="mt-3 text-sm text-ink-400">Henüz kaydedilmiş manuel tarama yok.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {scanHistory.map((run) => {
              const candidates = run.candidates || [];
              return <details key={run.scan_id} className="rounded-lg border border-line bg-white p-3">
                <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="font-mono font-semibold text-ink-800">{fmtDateTime(run.completed_at ?? run.generated_at)}</span>
                  <span className="flex items-center gap-2"><Badge tone="accent">{run.count ?? run.candidate_count ?? candidates.length} aday</Badge><span className="text-xs text-ink-400">{run.algorithm_version || "combined-v1"}</span></span>
                </summary>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {candidates.length ? candidates.map((candidate) => <span key={`${candidate.symbol}:${candidate.horizon_minutes ?? "x"}`} className="rounded-md bg-canvas px-2 py-1 text-[11px] text-ink-600">
                    <span className="font-mono font-semibold">{candidate.symbol}</span> · {candidate.horizon_minutes ?? "—"} dk · {Array.isArray(candidate.unified_sources) ? candidate.unified_sources.join(", ") : candidate.strategy || "Birleşik"}
                  </span>) : <span className="text-xs text-ink-400">Bu taramada aday bulunmadı.</span>}
                </div>
              </details>;
            })}
          </div>
        )}
      </Card>

      {rawNotifications.length === 0 ? <EmptyState title="Başarı kaydı yok" hint="Aday görüntüleri yukarıdaki kalıcı tarama geçmişinde tutuluyor." /> : <>
      {/* SİNYAL BAŞARI KARNESİ */}
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-line bg-white p-3.5 shadow-xs">
          <p className="odak-kicker">Başarı Oranı (Hit Rate)</p>
          <p className="mt-1 font-mono text-2xl font-bold text-gain">
            %{stats.winRate.toFixed(1)}
          </p>
          <p className="mt-0.5 text-xs text-ink-400">
            {stats.successful} başarılı / {stats.failed} başarısız
          </p>
        </div>

        <div className="rounded-xl border border-line bg-white p-3.5 shadow-xs">
          <p className="odak-kicker">Ortalama Kâr Potansiyeli</p>
          <p className="mt-1 font-mono text-2xl font-bold text-accent">
            +{stats.avgMfe.toFixed(2)}%
          </p>
          <p className="mt-0.5 text-xs text-ink-400">Ulaşılan ortalama tepe (MFE)</p>
        </div>

        <div className="rounded-xl border border-line bg-white p-3.5 shadow-xs">
          <p className="odak-kicker">Toplam Sinyal</p>
          <p className="mt-1 font-mono text-2xl font-bold text-ink-900">
            {stats.total}
          </p>
          <p className="mt-0.5 text-xs text-ink-400">
            {stats.pending} sinyal ufku devam ediyor
          </p>
        </div>

        <div className="rounded-xl border border-line bg-white p-3.5 shadow-xs">
          <p className="odak-kicker">Sinyal Doğrulama</p>
          <p className="mt-1 font-mono text-2xl font-bold text-ink-900">
            Füzyon Onaylı
          </p>
          <p className="mt-0.5 text-xs text-ink-400">Çoklu sistem cross-check</p>
        </div>
      </div>

      {/* GEÇMİŞ TABLOSU */}
      <Card className="p-4">
        <div className="odak-scroll">
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
                <th className="pb-2 pr-2 font-medium w-8">★</th>
                <th className="pb-2 pr-3 font-medium">Zaman</th>
                <th className="pb-2 pr-3 font-medium">Sembol</th>
                <th className="pb-2 pr-3 font-medium">Üreten Sistem</th>
                <th className="pb-2 pr-3 text-right font-medium">Skor</th>
                <th className="pb-2 pr-3 text-right font-medium">Giriş Fiyatı</th>
                <th className="pb-2 pr-3 text-right font-medium">Hedef</th>
                <th className="pb-2 pr-3 text-right font-medium">Görülen Tepe (MFE)</th>
                <th className="pb-2 font-medium">Sonuç</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((n, i) => {
                const srcs = (n.sources || []).map(sourceLabel).filter(Boolean);
                const ok = String(n.status || "").includes("BAŞARILI");
                const bad = String(n.status || "").includes("BAŞARISIZ");
                const sym = String(n.symbol || "").toUpperCase();
                const fav = isFavorite(sym);

                return (
                  <tr key={n.id ?? `${sym}-${i}`} className="border-t border-line hover:bg-slate-50/50">
                    <td className="py-2.5 pr-2">
                      <button
                        type="button"
                        onClick={() => toggleFavorite(sym)}
                        className={`text-sm ${fav ? "text-amber-500" : "text-ink-300 hover:text-amber-500"}`}
                        title={fav ? "Favorilerden çıkar" : "Favoriye ekle"}
                      >
                        {fav ? "★" : "☆"}
                      </button>
                    </td>
                    <td className="py-2.5 pr-3 font-mono text-xs text-ink-500">{fmtDateTime(n.detected_at)}</td>
                    <td className="py-2.5 pr-3">
                      <span className="font-mono font-bold text-ink-900">{baseAsset(sym)}</span>
                      <span className="text-xs text-ink-400"> / TRY</span>
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {srcs.length ? (
                          srcs.slice(0, 3).map((s) => (
                            <Badge key={s} tone="accent">
                              {s}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-ink-400">—</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-ink-700">
                      {n.score != null ? Math.round(n.score) : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-ink-700">
                      {n.price != null ? formatPrice(n.price) : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-ink-700 font-semibold">
                      {formatPct(n.target_pct, 1, true)}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-gain font-semibold">
                      {n.mfe_pct != null ? `+${Number(n.mfe_pct).toFixed(2)}%` : "—"}
                    </td>
                    <td className="py-2.5">
                      <Badge tone={ok ? "gain" : bad ? "loss" : "warn"}>
                        {ok ? "✓ HEDEFE ULAŞTI" : bad ? "✗ STOP / ZAMAN AŞIMI" : "BEKLİYOR"}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
          <span>
            {filtered.length} sinyal · sayfa {safePage + 1}/{pageCount}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
            >
              ← Önceki
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
              className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
            >
              Sonraki →
            </button>
          </div>
        </div>
      </Card>
      </>}
    </div>
  );
}
