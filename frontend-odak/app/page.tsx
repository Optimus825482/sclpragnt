"use client";

/**
 * ANA SAYFA — sadeleştirilmiş dashboard.
 *
 * Tasarımdaki "ODAK AI TRADER" ekranının gerçek veriyle çalışan sürümü.
 * Sadeleştirmeler:
 *   - Tek üst menü (sol sidebar yok → çift navigasyon kaldırıldı),
 *   - Renk hiyerarşisi: vurgu MAVİ; yeşil/kırmızı yalnız K/Z için,
 *   - Bilgi yoğunluğu azaltıldı; sistem durumu tek şeritte,
 *   - Sahte emir formu yerine aday detayı + gerçek işlem bağlantısı.
 */
import { useEffect, useMemo, useState } from "react";
import { usePoll } from "./lib/hooks";
import { useLiveMessages } from "./lib/liveSocket";
import { useAuth } from "./lib/auth";
import type { DailyRisingState, MonitoringState } from "./lib/types";
import { Badge, Card, SectionHeader, Tabs } from "./components/ui";
import StatusStrip from "./components/StatusStrip";
import PortfolioStrip from "./components/PortfolioStrip";
import OpportunityCard from "./components/OpportunityCard";
import CandidateDetail from "./components/CandidateDetail";
import ActiveTradesTable from "./components/ActiveTradesTable";

type Horizon = "all" | "5" | "15";

export default function Home() {
  const { username } = useAuth();
  const [horizon, setHorizon] = useState<Horizon>("all");
  const [selected, setSelected] = useState<string | null>(null);

  const state = usePoll<DailyRisingState>("/api/daily-rising/state", 20_000);
  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 20_000);

  // Fırsat kaynağı: önce kombine liste (daily-rising), boşsa radar adayları.
  const opportunities = useMemo(() => {
    const fromDaily = state.data?.candidates || [];
    if (fromDaily.length > 0) return fromDaily;
    return (monitoring.data?.candidates || []) as DailyRisingState["candidates"];
  }, [state.data, monitoring.data]);

  const filtered = useMemo(() => {
    if (horizon === "all") return opportunities;
    const want = Number(horizon);
    return opportunities.filter((o) => {
      const h = (o as { horizon_minutes?: number }).horizon_minutes;
      return h == null ? horizon === "5" : h === want;
    });
  }, [opportunities, horizon]);

  // Seçili sembol; liste değişince ilk aday seçilir.
  const selectedItem = useMemo(
    () => filtered.find((o) => o.symbol === selected) || filtered[0] || null,
    [filtered, selected],
  );

  // Canlı mesajlarda tazeleme tetikle (sinyal/pozisyon/otonom değişimleri).
  useLiveMessages((msg) => {
    if (["signal", "trade_updated", "portfolio_reconciled", "auto_paper_trade", "reset"].includes(msg.type)) {
      state.reload();
      monitoring.reload();
    }
  });

  useEffect(() => {
    if (selected && !filtered.some((o) => o.symbol === selected)) setSelected(null);
  }, [filtered, selected]);

  const hasError = state.error && monitoring.error;

  return (
    <div className="space-y-5">
      {/* Karşılama */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="odak-kicker">Canlı dashboard</p>
          <h1 className="mt-1 text-xl font-semibold text-ink-900">
            {username ? `Hoş geldin, ${username}` : "Fırsat Panosu"}
          </h1>
        </div>
        <p className="text-xs text-ink-400">
          Kaynak: {state.data?.source === "last_sent" ? "son gönderilen liste" : "canlı tarama"} ·{" "}
          {state.data?.candidates?.length ?? 0} aday
        </p>
      </div>

      <StatusStrip />
      <PortfolioStrip />

      {hasError && (
        <div className="odak-card border-warn/30 bg-warn-soft p-3 text-sm text-warn">
          Bazı veriler alınamadı — {state.error || monitoring.error}. Veri geldiğinde otomatik güncellenecek.
        </div>
      )}

      {/* Fırsatlar + detay */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-5">
          <SectionHeader
            eyebrow="AI Fırsatları"
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

          {state.loading && !state.data ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="odak-card h-40 animate-pulse bg-canvas" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="mt-6 rounded-xl border border-dashed border-line py-10 text-center text-sm text-ink-400">
              Şu anda uygun aday yok. Tarama arka planda devam ediyor.
            </p>
          ) : (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {filtered.slice(0, 8).map((item, index) => (
                <OpportunityCard
                  key={item.symbol}
                  rank={index + 1}
                  item={item}
                  selected={selectedItem?.symbol === item.symbol}
                  onSelect={() => setSelected(item.symbol)}
                />
              ))}
            </div>
          )}
        </Card>

        <div className="lg:sticky lg:top-20 lg:self-start">
          <CandidateDetail item={selectedItem} />
        </div>
      </div>

      {/* Aktif işlemler */}
      <Card className="p-5">
        <SectionHeader eyebrow="Aktif İşlemler" title="Açık pozisyonlar" description="Net K/Z (gidiş-dönüş komisyonu düşülmüş)." />
        <div className="mt-4">
          <ActiveTradesTable limit={6} />
        </div>
      </Card>
    </div>
  );
}
