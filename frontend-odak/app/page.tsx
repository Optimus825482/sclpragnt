"use client";

/**
 * ANA SAYFA (Anasayfa) — tasarımdaki ekranın gerçek veriyle çalışan sürümü.
 *
 * Düzen: üstte kart şeklinde yan yana Fırsatlar; altında Aktif İşlemler tablosu;
 * bunların altında Toplam Portföy / Kullanılabilir Bakiye / Bugünkü Kâr-Zarar
 * yan yana; en sağda sembol aramalı canlı fiyat + alım emri paneli.
 *
 * Veri kaynağı: hızlı olan /api/monitoring/state (radar) birincil; boşsa
 * /api/daily-rising/state. İkisi de `toOpportunityView` ile normalize edilir.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePoll } from "./lib/hooks";
import { useAuth } from "./lib/auth";
import { toOpportunityView } from "./lib/opportunity";
import type { DailyRisingState, MonitoringState } from "./lib/types";
import { Badge, Card, SectionHeader, Tabs } from "./components/ui";
import PortfolioStrip from "./components/PortfolioStrip";
import OpportunityCard from "./components/OpportunityCard";
import ActiveTradesTable from "./components/ActiveTradesTable";
import OrderPanel from "./components/OrderPanel";

type Horizon = "all" | "5" | "15";

export default function Home() {
  const { username } = useAuth();
  const [horizon, setHorizon] = useState<Horizon>("all");
  const [selected, setSelected] = useState<string | null>(null);

  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 20_000);
  const daily = usePoll<DailyRisingState>("/api/daily-rising/state", 60_000, 30_000);

  const views = useMemo(() => {
    const monitorRows = monitoring.data?.candidates ?? [];
    const source = monitorRows.length > 0 ? monitorRows : daily.data?.candidates ?? [];
    return source.map((row) => toOpportunityView(row as Record<string, unknown>));
  }, [monitoring.data, daily.data]);

  const filtered = useMemo(() => {
    if (horizon === "all") return views;
    const want = Number(horizon);
    return views.filter((v) => (v.horizonMinutes == null ? horizon === "5" : v.horizonMinutes === want));
  }, [views, horizon]);

  const selectedView = useMemo(
    () => filtered.find((o) => o.symbol === selected) || filtered[0] || null,
    [filtered, selected],
  );

  useEffect(() => {
    if (selected && !filtered.some((o) => o.symbol === selected)) setSelected(null);
  }, [filtered, selected]);

  const loadingFirst = monitoring.loading && !monitoring.data;
  const allFailed = Boolean(monitoring.error) && Boolean(daily.error) && views.length === 0;
  const sourceLabel = (monitoring.data?.candidates?.length ?? 0) > 0 ? "radar taraması" : "günlük liste";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="odak-kicker">Canlı dashboard</p>
          <h1 className="mt-1 text-xl font-semibold text-ink-900">
            {username ? `Hoş geldin, ${username}` : "Fırsat Panosu"}
          </h1>
        </div>
        <p className="text-xs text-ink-400">
          Kaynak: {sourceLabel} · {views.length} aday
        </p>
      </div>

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
                  key={item.symbol}
                  rank={index + 1}
                  item={item}
                  selected={selectedView?.symbol === item.symbol}
                  onSelect={() => setSelected(item.symbol)}
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

      {/* ALT: Portföy özeti (yan yana) */}
      <PortfolioStrip />
    </div>
  );
}
