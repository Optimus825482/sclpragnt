"use client";

/**
 * ANA SAYFA (Anasayfa) — tasarımdaki ekranın gerçek veriyle çalışan sürümü.
 *
 * Düzen: en üstte portföy özeti bandı; ardından Fırsatlar ve işlem paneli;
 * en altta Aktif İşlemler tablosu.
 *
 * Veri kaynakları: birleşik radar adayları, günlük yükseliş adayları ve
 * ufku dolmamış kalıcı bildirimler. Hepsi aynı kart kümesinde gösterilir.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePoll } from "./lib/hooks";
import { toOpportunityView } from "./lib/opportunity";
import type { DailyRisingState, MonitoringState, NotificationsResponse } from "./lib/types";
import { Badge, Card, SectionHeader, Tabs } from "./components/ui";
import PortfolioStrip from "./components/PortfolioStrip";
import OpportunityCard from "./components/OpportunityCard";
import ActiveTradesTable from "./components/ActiveTradesTable";
import OrderPanel from "./components/OrderPanel";

type Horizon = "all" | "5" | "15";

export default function Home() {
  const [horizon, setHorizon] = useState<Horizon>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [seen, setSeen] = useState<Record<string, Record<string, unknown>>>({});

  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 20_000);
  const daily = usePoll<DailyRisingState>("/api/daily-rising/state", 60_000, 30_000);
  const pendingSignals = usePoll<NotificationsResponse>("/api/reports/notifications?day=all&limit=400", 60_000);

  useEffect(() => {
    const now = Date.now() / 1000;
    setSeen((previous) => {
      const next: Record<string, Record<string, unknown>> = {};
      for (const [key, candidate] of Object.entries(previous)) {
        const detected = Number(candidate.detected_at ?? candidate.created_at ?? 0);
        const horizonMinutes = Number(candidate.horizon_minutes ?? 0);
        if (detected && horizonMinutes > 0 && now < detected + horizonMinutes * 60 + 120) next[key] = candidate;
      }
      const fresh: Record<string, unknown>[] = [
        ...(monitoring.data?.candidates || []).map((row) => row as Record<string, unknown>),
        ...(daily.data?.candidates || []).map((row) => row as unknown as Record<string, unknown>),
      ];
      for (const row of fresh) {
        const symbol = String(row.symbol || "").toUpperCase();
        if (!symbol) continue;
        const detected = Number(row.detected_at ?? row.created_at ?? 0);
        const horizonMinutes = Number(row.horizon_minutes ?? 0);
        // Günlük liste endpointi ufku dönmüyorsa süre uydurmayız; bu adaylar
        // yine anlık listede görünür ve bildirim kaydından ufuk gelirse tutulur.
        if (!detected || horizonMinutes <= 0) continue;
        next[`${symbol}:${horizonMinutes}`] = { ...row, detected_at: detected };
      }
      for (const n of pendingSignals.data?.notifications || []) {
        const detected = Number(n.detected_at || 0);
        const horizonMinutes = Number(n.horizon_minutes || 0);
        const symbol = String(n.symbol || "").toUpperCase();
        if (!symbol || !detected || horizonMinutes <= 0 || n.status !== "BEKLİYOR") continue;
        if (now >= detected + horizonMinutes * 60 + 120) continue;
        next[`${symbol}:${horizonMinutes}`] = { ...n, detected_at: detected };
      }
      return next;
    });
  }, [monitoring.data, daily.data, pendingSignals.data]);

  const views = useMemo(() => {
    const rows = new Map<string, Record<string, unknown>>();
    for (const row of monitoring.data?.candidates ?? []) {
      const raw = row as Record<string, unknown>;
      const symbol = String(raw.symbol || "").toUpperCase();
      if (symbol) rows.set(`${symbol}:${Number(raw.horizon_minutes) || "unknown"}`, raw);
    }
    for (const row of daily.data?.candidates ?? []) {
      const raw = row as unknown as Record<string, unknown>;
      const symbol = String(raw.symbol || "").toUpperCase();
      if (!symbol) continue;
      const horizonMinutes = Number(raw.horizon_minutes) || null;
      const matchedPending = (pendingSignals.data?.notifications || []).find((n) =>
        String(n.symbol || "").toUpperCase() === symbol && Number(n.horizon_minutes) > 0 && n.status === "BEKLİYOR",
      );
      const resolvedHorizon = horizonMinutes ?? (matchedPending ? Number(matchedPending.horizon_minutes) : null);
      const sources = Array.isArray(raw.confirm_sources) ? raw.confirm_sources : undefined;
      rows.set(`${symbol}:${resolvedHorizon ?? "unknown"}`, {
        ...raw,
        ...(resolvedHorizon ? { horizon_minutes: resolvedHorizon } : {}),
        ...(sources?.length ? { sources } : {}),
      });
    }
    const now = Date.now() / 1000;
    for (const n of pendingSignals.data?.notifications || []) {
      const symbol = String(n.symbol || "").toUpperCase();
      const detected = Number(n.detected_at || 0);
      const horizonMinutes = Number(n.horizon_minutes || 0);
      if (!symbol || !detected || horizonMinutes <= 0 || n.status !== "BEKLİYOR") continue;
      if (now >= detected + horizonMinutes * 60 + 120) continue;
      const key = `${symbol}:${horizonMinutes}`;
      if (!rows.has(key)) rows.set(key, { ...n, detected_at: detected });
    }
    for (const [key, row] of Object.entries(seen)) {
      if (!rows.has(key)) rows.set(key, row);
    }
    return [...rows.values()].map((row) => toOpportunityView(row));
  }, [monitoring.data, daily.data, pendingSignals.data, seen]);

  const filtered = useMemo(() => {
    if (horizon === "all") return views;
    const want = Number(horizon);
    return views.filter((v) => (v.horizonMinutes == null ? horizon === "5" : v.horizonMinutes === want));
  }, [views, horizon]);

  const selectedView = useMemo(
    () => filtered.find((o) => `${o.symbol}:${o.horizonMinutes ?? "unknown"}` === selected) || filtered[0] || null,
    [filtered, selected],
  );

  useEffect(() => {
    if (selected && !filtered.some((o) => `${o.symbol}:${o.horizonMinutes ?? "unknown"}` === selected)) setSelected(null);
  }, [filtered, selected]);

  const loadingFirst = monitoring.loading && !monitoring.data;
  const allFailed = Boolean(monitoring.error) && Boolean(daily.error) && views.length === 0;
  return (
    <div className="space-y-5">
      <PortfolioStrip />

      {allFailed && (
        <div className="odak-card border-loss/30 bg-loss-soft/50 p-3 text-sm text-loss">
          Fırsat verisi alınamadı — {monitoring.error || daily.error}. Backend çalışıyor mu?
        </div>
      )}

      {/* ÜST: Fırsat kartları (yan yana) + SAĞ: işlem paneli */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_330px]">
        <Card className="p-5">
          <SectionHeader
            eyebrow="Fırsatlar"
            title={
              <span className="inline-flex items-center gap-2">
                En yüksek potansiyelli adaylar
                <Badge tone="gain">
                  <span className="h-1.5 w-1.5 rounded-full bg-gain odak-live-dot" /> LIVE
                </Badge>
              </span>
            }
            actions={
              <Tabs
                items={[
                  { id: "all", label: "Tümü" },
                  { id: "5", label: "5 dk" },
                  { id: "15", label: "15 dk" },
                ]}
                active={horizon}
                onChange={(id) => setHorizon(id as Horizon)}
              />
            }
          />

          {loadingFirst ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-52 animate-pulse rounded-xl bg-canvas" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="mt-6 rounded-xl border border-dashed border-line py-10 text-center text-sm text-ink-400">
              Şu anda uygun aday yok. Tarama arka planda devam ediyor.
            </p>
          ) : (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {filtered.slice(0, 6).map((item, index) => (
                <OpportunityCard
                  key={`${item.symbol}:${item.horizonMinutes ?? "unknown"}`}
                  rank={index + 1}
                  item={item}
                  selected={selectedView?.symbol === item.symbol && selectedView?.horizonMinutes === item.horizonMinutes}
                  onSelect={() => setSelected(`${item.symbol}:${item.horizonMinutes ?? "unknown"}`)}
                />
              ))}
            </div>
          )}
        </Card>

        <div className="lg:sticky lg:top-20 lg:self-start">
          <OrderPanel initialSymbol={selectedView?.symbol ?? null} />
        </div>
      </div>

      {/* ORTA: Aktif işlemler tablosu */}
      <Card className="p-5" >
        <div id="aktif-islemler" className="scroll-mt-24">
        <SectionHeader eyebrow="Aktif İşlemlerim" title="Açık pozisyonlar" description="Güncel fiyat ve net K/Z (gidiş-dönüş komisyonu düşülmüş)." actions={<Link href="/gecmis-islemler" className="rounded-lg border border-line px-3 py-2 text-sm font-medium text-accent hover:bg-accent-soft">Tümünü Gör</Link>} />
        <div className="mt-4">
          <ActiveTradesTable limit={8} />
        </div>
        </div>
      </Card>
    </div>
  );
}
