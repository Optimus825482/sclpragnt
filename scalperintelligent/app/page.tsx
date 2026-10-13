"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

/** İmleç bir metin alanındayken kısayollar devre dışı kalır. */
function isTypingTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null;
  if (!element) return false;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || element.isContentEditable;
}

export default function Home() {
  const [horizon, setHorizon] = useState<HorizonFilter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [quickAmount, setQuickAmount] = useState<number | null>(null);
  const [manualRun, setManualRun] = useState<UnifiedScanRun | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const { favorites, isFavorite, toggleFavorite } = useWatchlist();
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

  // KLAVYE KISAYOLLARI (TradingView tarzı): j/k aday gezinme, Enter panele aktarım,
  // f favori, m manuel tarama, ? yardım. Metin alanlarında devre dışıdır.
  const selectedKey = selectedView ? `${selectedView.symbol}:${selectedView.horizonMinutes ?? "unknown"}` : null;
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      const key = event.key;
      if (key === "?") { event.preventDefault(); setShowShortcuts((open) => !open); return; }
      if (key === "Escape") { setShowShortcuts(false); return; }
      if (key === "m" && !scanBusy) { event.preventDefault(); handleManualScan(); return; }
      if (!filtered.length) return;
      const index = selectedKey ? filtered.findIndex((item) => `${item.symbol}:${item.horizonMinutes ?? "unknown"}` === selectedKey) : -1;
      const moveTo = (next: number) => {
        const target = filtered[Math.max(0, Math.min(filtered.length - 1, next))];
        if (target) { setSelected(`${target.symbol}:${target.horizonMinutes ?? "unknown"}`); setQuickAmount(null); }
      };
      if (key === "j" || key === "ArrowDown") { event.preventDefault(); moveTo(index + 1); }
      else if (key === "k" || key === "ArrowUp") { event.preventDefault(); moveTo(index - 1); }
      else if (key === "Enter" && selectedView) {
        event.preventDefault();
        setQuickAmount(1000);
        document.getElementById("islem-paneli")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      else if (key === "f" && selectedView) { event.preventDefault(); toggleFavorite(selectedView.symbol); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, selectedKey, selectedView, scanBusy]);

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
          <button type="button" onClick={() => setShowShortcuts((open) => !open)} title="Klavye kısayolları (?)" aria-label="Klavye kısayolları" className="hidden rounded-lg border border-line px-2 py-1.5 text-xs text-ink-500 hover:border-accent hover:text-accent sm:block">⌘ ?</button>
          <button
            type="button"
            onClick={handleManualScan}
            disabled={scanBusy}
            className="flex min-h-[2.25rem] items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-accent/90 disabled:opacity-60"
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

        <div id="islem-paneli" className="scroll-mt-24 lg:sticky lg:top-20 lg:self-start">
          <OrderPanel
            initialSymbol={selectedView?.symbol ?? null}
            initialAmount={quickAmount}
            initialCandidate={selectedView}
            onTraded={() => scan.reload()}
          />
          <p className="mt-2 text-center text-[10px] text-ink-500">Adayı panele taşımak emir göndermez; gerçek emir için ayrı onay gerekir. Kısayollar: j/k gezin · Enter panele aktar · f favori · m tara · ? yardım</p>
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

      {showShortcuts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowShortcuts(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="shortcuts-title" className="w-full max-w-sm rounded-2xl border border-line bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <h2 id="shortcuts-title" className="text-lg font-bold text-ink-900">Klavye Kısayolları</h2>
              <button type="button" onClick={() => setShowShortcuts(false)} className="rounded-md px-2 py-1 text-ink-500 hover:bg-slate-100" aria-label="Yardım penceresini kapat">✕</button>
            </div>
            <dl className="mt-3 space-y-2 text-sm">
              {[["j / ↓", "Sonraki aday"], ["k / ↑", "Önceki aday"], ["Enter", "Seçili adayı işlem paneline aktar (1.000 ₺)"], ["f", "Seçili sembolü favoriye ekle/çıkar"], ["m", "Salt-veri piyasa taraması başlat"], ["?", "Bu pencereyi aç/kapat"], ["Esc", "Pencereleri kapat"]].map(([key, label]) => (
                <div key={key} className="flex items-center justify-between gap-4">
                  <dt><kbd className="rounded-md border border-line bg-canvas px-2 py-0.5 font-mono text-xs font-semibold text-ink-800">{key}</kbd></dt>
                  <dd className="text-right text-ink-600">{label}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[11px] text-ink-400">Kısayollar metin kutularında yazarken devre dışıdır.</p>
          </section>
        </div>
      )}
    </div>
  );
}
