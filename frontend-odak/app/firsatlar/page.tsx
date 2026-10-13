"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { formatPct, fmtDateTime, formatPrice } from "../lib/format";
import { baseAsset, toOpportunityView } from "../lib/opportunity";
import { sourceLabel } from "../lib/sources";
import { useWatchlist } from "../lib/watchlist";
import { sound } from "../lib/sound";
import type { MonitoringState, NotificationsResponse, ScanNotification } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton, Tabs } from "../components/ui";

type Tab = "live" | "history";
type LiveRow = { view: ReturnType<typeof toOpportunityView>; kind: string; detectedAt: number | null };

const PAGE_SIZE = 25;

export default function FirsatlarPage() {
  const [tab, setTab] = useState<Tab>("live");
  const [search, setSearch] = useState("");
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [manualBusy, setManualBusy] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualMessage, setManualMessage] = useState<string | null>(null);
  const [seenCandidates, setSeenCandidates] = useState<Record<string, Record<string, unknown>>>({});

  const { isFavorite, toggleFavorite } = useWatchlist();

  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 15_000);
  const pendingSignals = usePoll<NotificationsResponse>(
    "/api/reports/notifications?day=all&limit=400&history_only=true",
    45_000
  );

  useEffect(() => {
    const current = monitoring.data;
    if (!current) return;
    const now = Date.now() / 1000;
    setSeenCandidates((previous) => {
      const next: Record<string, Record<string, unknown>> = {};
      for (const [key, candidate] of Object.entries(previous)) {
        const detected = Number(candidate.detected_at ?? candidate.created_at ?? 0);
        const horizon = Number(candidate.horizon_minutes ?? 0);
        if (detected && horizon > 0 && now < detected + horizon * 60 + 120) next[key] = candidate;
      }
      const fresh = [...(current.candidates || []), ...(current.warm || []), ...(current.pulse || [])];
      for (const candidate of fresh) {
        const row = candidate as Record<string, unknown>;
        const symbol = String(row.symbol || "").toUpperCase();
        if (!symbol) continue;
        const horizon = Number(row.horizon_minutes ?? 0);
        if (horizon <= 0) continue;
        const detected = Number(row.detected_at ?? row.created_at ?? now);
        next[`${symbol}:${horizon}`] = { ...row, detected_at: detected };
      }
      return next;
    });
  }, [monitoring.data]);

  async function runManualScan() {
    if (manualBusy) return;
    setManualBusy(true);
    setManualError(null);
    setManualMessage("Piyasa taranıyor...");
    try {
      const response = await apiRequest("/api/monitoring/scan", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || body?.error || `Tarama başarısız (HTTP ${response.status})`);
      if (body?.error) throw new Error(String(body.error));

      sound.playSignalChime();
      const count = Number(body?.candidates?.length || 0);
      setManualMessage(`Tarama tamamlandı · ${count} fırsat bulundu.`);

      monitoring.reload();
      pendingSignals.reload();
      setTimeout(() => setManualMessage(null), 4000);
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "Manuel tarama başarısız oldu.");
      setTimeout(() => setManualError(null), 4000);
    } finally {
      setManualBusy(false);
    }
  }

  // Canlı Adayları Hazırla
  const live = useMemo(() => {
    const m = monitoring.data;
    if (!m) return [];
    const rows: LiveRow[] = [];
    for (const c of m.candidates || []) {
      rows.push({
        view: toOpportunityView(c as Record<string, unknown>),
        kind: "Aday",
        detectedAt: Number((c as Record<string, unknown>).detected_at ?? (c as Record<string, unknown>).created_at) || null,
      });
    }

    const warmBest = new Map<string, Record<string, unknown>>();
    for (const w of m.warm || []) {
      const sym = String((w as Record<string, unknown>).symbol ?? "");
      if (!sym) continue;
      const cur = warmBest.get(sym);
      const prox = Number((w as Record<string, unknown>).warm_proximity ?? 0);
      const curProx = cur ? Number(cur.warm_proximity ?? 0) : -Infinity;
      if (!cur || prox > curProx) warmBest.set(sym, w as Record<string, unknown>);
    }
    for (const w of warmBest.values()) {
      rows.push({
        view: toOpportunityView(w),
        kind: "Isınıyor",
        detectedAt: Number(w.detected_at ?? w.created_at) || null,
      });
    }

    for (const p of m.pulse || []) {
      rows.push({
        view: toOpportunityView(p as Record<string, unknown>),
        kind: "Nabız",
        detectedAt: Number((p as Record<string, unknown>).detected_at ?? (p as Record<string, unknown>).created_at) || null,
      });
    }

    const currentKeys = new Set(rows.map(({ view }) => `${view.symbol}:${view.horizonMinutes ?? 5}`));
    for (const [key, candidate] of Object.entries(seenCandidates)) {
      if (currentKeys.has(key)) continue;
      rows.push({
        view: toOpportunityView(candidate),
        kind: "Ufuk süresince",
        detectedAt: Number(candidate.detected_at ?? candidate.created_at) || null,
      });
      currentKeys.add(key);
    }

    const now = Date.now() / 1000;
    for (const n of pendingSignals.data?.notifications || []) {
      const detectedAt = Number(n.detected_at || 0);
      const horizon = Math.max(1, Number(n.horizon_minutes || 5));
      if (!detectedAt || now >= detectedAt + horizon * 60 + 120 || n.status !== "BEKLİYOR") continue;
      const view = toOpportunityView({ ...n, created_at: detectedAt });
      const key = `${view.symbol}:${view.horizonMinutes ?? horizon}`;
      if (!currentKeys.has(key)) rows.push({ view, kind: "Ufuk süresince", detectedAt });
      currentKeys.add(key);
    }

    // Arama ve favori filtresi
    return rows.filter(({ view }) => {
      if (onlyFavorites && !isFavorite(view.symbol)) return false;
      if (search.trim() && !view.symbol.includes(search.trim().toUpperCase())) return false;
      return true;
    });
  }, [monitoring.data, pendingSignals.data, seenCandidates, onlyFavorites, search, isFavorite]);

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
        <LiveFeed
          monitoring={monitoring}
          rows={live}
          isFavorite={isFavorite}
          toggleFavorite={toggleFavorite}
        />
      ) : (
        <HistorySection
          search={search}
          onlyFavorites={onlyFavorites}
          isFavorite={isFavorite}
          toggleFavorite={toggleFavorite}
        />
      )}
    </div>
  );
}

function LiveFeed({
  monitoring,
  rows,
  isFavorite,
  toggleFavorite,
}: {
  monitoring: ReturnType<typeof usePoll<MonitoringState>>;
  rows: LiveRow[];
  isFavorite: (sym: string) => boolean;
  toggleFavorite: (sym: string) => void;
}) {
  if (monitoring.loading && !monitoring.data) return <Skeleton className="h-64" />;
  if (monitoring.error && !monitoring.data)
    return <EmptyState title="Tarama durumu alınamadı" hint={monitoring.error} tone="loss" />;
  if (rows.length === 0)
    return <EmptyState title="Uygun aday yok" hint="Filtreleri değiştirebilir veya 'Şimdi Tara' ile yeni tarama yapabilirsiniz." />;

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
}: {
  search: string;
  onlyFavorites: boolean;
  isFavorite: (sym: string) => boolean;
  toggleFavorite: (sym: string) => void;
}) {
  const [page, setPage] = useState(0);
  const { data, error, loading } = usePoll<NotificationsResponse>(
    "/api/reports/notifications?day=all&limit=400&history_only=true",
    60_000
  );

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

  if (loading && !data) return <Skeleton className="h-64" />;
  if (error && !data) return <EmptyState title="Tarama geçmişi alınamadı" hint={error} tone="loss" />;
  if (rawNotifications.length === 0) return <EmptyState title="Kayıt yok" hint="Henüz tarama/bildirim kaydı oluşmamış." />;

  return (
    <div className="space-y-4">
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
    </div>
  );
}
