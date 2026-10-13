"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest } from "./lib/api";
import { usePoll } from "./lib/hooks";
import { toOpportunityView, type OpportunityView } from "./lib/opportunity";
import { useWatchlist } from "./lib/watchlist";
import { fmtDateTime } from "./lib/format";
import type { ManualUnifiedScanResponse, UnifiedScanResponse, UnifiedScanRun } from "./lib/types";
import { Badge, Card, SectionHeader, Tabs } from "./components/ui";
import PortfolioStrip from "./components/PortfolioStrip";
import OpportunityCard from "./components/OpportunityCard";
import ActiveTradesTable from "./components/ActiveTradesTable";
import OrderPanel from "./components/OrderPanel";
import LiveNotificationToast from "./components/LiveNotificationToast";

type HorizonFilter = "all" | "favorites" | "5" | "15";

export default function Home() {
  const [horizon, setHorizon] = useState<HorizonFilter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [quickAmount, setQuickAmount] = useState<number | null>(null);
  const [manualRun, setManualRun] = useState<UnifiedScanRun | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const { favorites, isFavorite } = useWatchlist();
  const scan = usePoll<UnifiedScanResponse>("/api/unified-scan/latest", 20_000, 30_000);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("filter") === "favorites") {
      setHorizon("favorites");
    }
  }, []);

  const latestRun = scan.data?.run ?? null;
  const latestRunAt = Number(latestRun?.completed_at ?? latestRun?.generated_at ?? 0);
  const run = manualRun && Number(manualRun.completed_at || 0) >= latestRunAt ? manualRun : latestRun;
  const views = useMemo(() => {
    const unique = new Map<string, OpportunityView>();
    for (const candidate of run?.candidates ?? []) {
      const view = toOpportunityView(candidate);
      if (!view.symbol) continue;
      const key = `${view.symbol}:${view.horizonMinutes ?? "unknown"}`;
      const existing = unique.get(key);
      if (!existing || (view.strength ?? 0) > (existing.strength ?? 0)) unique.set(key, view);
    }
    return Array.from(unique.values()).sort((left, right) => {
      const favoriteOrder = Number(isFavorite(right.symbol)) - Number(isFavorite(left.symbol));
      if (favoriteOrder) return favoriteOrder;
      return (right.strength ?? 0) - (left.strength ?? 0);
    });
  }, [run, isFavorite]);

  const filtered = useMemo(() => {
    if (horizon === "favorites") return views.filter((item) => isFavorite(item.symbol));
    if (horizon === "all") return views;
    return views.filter((item) => item.horizonMinutes === Number(horizon));
  }, [views, horizon, isFavorite]);

  const selectedView = useMemo(
    () => filtered.find((item) => `${item.symbol}:${item.horizonMinutes ?? "unknown"}` === selected || item.symbol === selected) ?? filtered[0] ?? null,
    [filtered, selected],
  );

  const generatedAt = Number(run?.completed_at ?? run?.generated_at ?? 0);
  const stale = generatedAt > 0 && Date.now() / 1000 - generatedAt > 120;
  const loadingFirst = scan.loading && !run;

  useEffect(() => {
    if (selected && !filtered.some((item) => `${item.symbol}:${item.horizonMinutes ?? "unknown"}` === selected || item.symbol === selected)) {
      setSelected(null);
    }
  }, [filtered, selected]);

  async function handleManualScan() {
    if (scanBusy) return;
    setScanBusy(true);
    setScanMessage("Salt-veri taraması çalışıyor…");
    try {
      const response = await apiRequest("/api/unified-scan/manual", { method: "POST" });
      const body = await response.json().catch(() => ({})) as ManualUnifiedScanResponse & { detail?: string };
      if (!response.ok) throw new Error(body?.detail || "Tarama tamamlanamadı");
      if (!body.ok || body.side_effects.notifications_sent || body.side_effects.paper_positions_opened || body.side_effects.real_orders_submitted) throw new Error("Tarama güvenlik doğrulaması başarısız oldu");
      setManualRun({
        scan_id: body.scan_id,
        started_at: body.started_at,
        completed_at: body.completed_at,
        algorithm_version: body.algorithm_version,
        source: "manual",
        count: body.count,
        candidates: body.candidates,
      });
      setScanMessage(`Tarama tamamlandı · ${body.count} aday · emir/bildirim oluşturulmadı`);
      scan.reload();
      window.setTimeout(() => setScanMessage(null), 6000);
    } catch (error) {
      setScanMessage(error instanceof Error ? error.message : "Tarama sırasında hata oluştu");
      window.setTimeout(() => setScanMessage(null), 6000);
    } finally {
      setScanBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <LiveNotificationToast
        onSelectSymbol={(symbol) => {
          setSelected(symbol);
          setQuickAmount(1000);
        }}
      />

      <PortfolioStrip />

      {scan.error && !run && (
        <div className="odak-card border-loss/30 bg-loss-soft/50 p-3 text-sm text-loss" role="alert">
          Birleşik tarama verisi alınamadı: {scan.error}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white/70 px-4 py-2.5 text-xs text-ink-600 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink-900">Birleşik Piyasa Taraması</span>
          <Badge tone={stale ? "warn" : "gain"}>{stale ? "ESKİ VERİ" : "Salt-veri"}</Badge>
          <span>{run ? `${views.length} aday` : "Henüz tarama yok"}</span>
          <span className="text-ink-400">
            {generatedAt ? `Son tarama ${fmtDateTime(generatedAt)}` : "Fiyat verisi public piyasa akışından"}
          </span>
          {scan.error && run && <span className="text-amber-700">Bağlantı koptu · son görüntü gösteriliyor</span>}
        </div>
        <div className="flex items-center gap-3">
          {scanMessage && <span className="font-medium text-accent" role="status">{scanMessage}</span>}
          <button
            type="button"
            onClick={handleManualScan}
            disabled={scanBusy}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
            title="Yalnız piyasa verisi taranır; emir veya bildirim gönderilmez"
          >
            <span className={scanBusy ? "animate-spin" : ""}>⟳</span>
            <span>{scanBusy ? "Taranıyor…" : "Piyasayı Tara"}</span>
          </button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="p-4 sm:p-5">
          <SectionHeader
            eyebrow="Adaylar · Kaynak uzlaşısı · Ufuk bazında tekil kayıtlar"
            title={
              <span className="inline-flex items-center gap-2">
                Yükseliş Adayları <Badge tone="gain">{filtered.length} ADAY</Badge>
              </span>
            }
            actions={
              <Tabs
                items={[
                  { id: "all", label: "Tümü" },
                  { id: "favorites", label: `★ Favoriler (${favorites.length})` },
                  { id: "5", label: "5 dk" },
                  { id: "15", label: "15 dk" },
                ]}
                active={horizon}
                onChange={(id) => setHorizon(id as HorizonFilter)}
              />
            }
          />

          {loadingFirst ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2, 3, 4, 5].map((item) => <div key={item} className="h-56 animate-pulse rounded-xl bg-canvas" />)}
            </div>
          ) : filtered.length === 0 ? (
            <div className="mt-6 rounded-xl border border-dashed border-line py-12 text-center text-sm text-ink-400">
              {horizon === "favorites" ? "Favori sembollerinizde henüz aday yok." : "Henüz aday bulunmuyor. Piyasa Tara ile salt-veri taraması başlatabilirsiniz."}
            </div>
          ) : (
            <div className="mt-4 grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.slice(0, 12).map((item, index) => (
                <OpportunityCard
                  key={`${item.symbol}:${item.horizonMinutes ?? "unknown"}`}
                  rank={index + 1}
                  item={item}
                  selected={selectedView?.symbol === item.symbol && selectedView?.horizonMinutes === item.horizonMinutes}
                  onSelect={() => {
                    setSelected(`${item.symbol}:${item.horizonMinutes ?? "unknown"}`);
                    setQuickAmount(null);
                  }}
                  onQuickBuy={(symbol, amount) => {
                    setSelected(`${symbol}:${item.horizonMinutes ?? "unknown"}`);
                    setQuickAmount(amount ?? 1000);
                  }}
                />
              ))}
            </div>
          )}
          {run && <p className="mt-3 text-[10px] text-ink-400">Sürüm {run.algorithm_version ?? "combined-v1"} · farklı ufuklardaki aynı semboller ayrı adaydır.</p>}
        </Card>

        <div className="lg:sticky lg:top-20 lg:self-start">
          <OrderPanel
            initialSymbol={selectedView?.symbol ?? null}
            initialAmount={quickAmount}
            initialCandidate={selectedView}
            onTraded={() => scan.reload()}
          />
          <p className="mt-2 text-center text-[10px] text-ink-500">Adayı panele taşımak emir göndermez; gerçek emir için ayrı onay gerekir.</p>
        </div>
      </div>

      <Card className="p-5">
        <div id="aktif-islemler" className="scroll-mt-24">
          <SectionHeader
            eyebrow="Portföy & Pozisyonlar"
            title="Aktif Binance TR Varlıkları"
            description="Cüzdandaki açık coin bakiyeleri, anlık kâr/zarar ve maliyet durumu."
            actions={<Link href="/gecmis-islemler" className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent-soft">İşlem Geçmişi →</Link>}
          />
          <div className="mt-4"><ActiveTradesTable limit={10} /></div>
        </div>
      </Card>
    </div>
  );
}
