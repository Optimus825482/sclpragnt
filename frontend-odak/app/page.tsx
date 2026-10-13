"use client";

/**
 * ANA SAYFA — Scalper Intelligent Trade Systems
 *
 * Tek Sinyal Motoru görünümü:
 *   - Tüm tarama havuzları (Radar, MACD MTF, Günlük Yükseliş, Hızlı Nabız)
 *     tek homojen kart listesinde birleşir.
 *   - Anlık Manuel Tarama ("⚡ Piyasa Tara") ile istediğiniz an tüm piyasa taranır.
 *   - Favoriler (⭐) filtresi ile izleme listenize anında odaklanabilirsiniz.
 *   - Kart üzerindeki hızlı alım butonları ile tek tıkta Binance TR emri hazırlanır.
 *   - Canlı WebSocket sinyal bildirimleri ve sesli uyarılar aktiftir.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest } from "./lib/api";
import { usePoll } from "./lib/hooks";
import { toOpportunityView, OpportunityView } from "./lib/opportunity";
import { useWatchlist } from "./lib/watchlist";
import { sound } from "./lib/sound";
import type { DailyRisingState, MonitoringState, NotificationsResponse } from "./lib/types";
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
  const [seen, setSeen] = useState<Record<string, Record<string, unknown>>>({});
  const [scanBusy, setScanBusy] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  const { favorites, isFavorite } = useWatchlist();

  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 15_000);
  const daily = usePoll<DailyRisingState>("/api/daily-rising/state", 45_000, 30_000);
  const pendingSignals = usePoll<NotificationsResponse>("/api/reports/notifications?day=all&limit=400", 45_000);

  // Manuel Tarama Tetikleme (Admin veya Normal kullanıcı)
  const handleManualScan = async () => {
    if (scanBusy) return;
    setScanBusy(true);
    setScanMessage("Piyasa taranıyor...");
    try {
      const res = await apiRequest("/api/monitoring/scan", { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.detail || body?.error || "Tarama tamamlanamadı");

      const count = (body?.candidates || []).length;
      setScanMessage(`Tarama tamamlandı: ${count} fırsat bulundu!`);
      sound.playSignalChime();

      monitoring.reload();
      daily.reload();
      pendingSignals.reload();

      setTimeout(() => setScanMessage(null), 5000);
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : "Tarama sırasında hata oluştu");
      setTimeout(() => setScanMessage(null), 4000);
    } finally {
      setScanBusy(false);
    }
  };

  // Geçici hafızadaki adayları ve bildirimleri birleştirme
  useEffect(() => {
    const now = Date.now() / 1000;
    setSeen((previous) => {
      const next: Record<string, Record<string, unknown>> = {};
      for (const [key, candidate] of Object.entries(previous)) {
        const detected = Number(candidate.detected_at ?? candidate.created_at ?? 0);
        const horizonMinutes = Number(candidate.horizon_minutes ?? 0);
        if (detected && horizonMinutes > 0 && now < detected + horizonMinutes * 60 + 120) {
          next[key] = candidate;
        }
      }
      const fresh: Record<string, unknown>[] = [
        ...(monitoring.data?.candidates || []).map((row) => row as Record<string, unknown>),
        ...(monitoring.data?.pulse || []).map((row) => row as Record<string, unknown>),
        ...(daily.data?.candidates || []).map((row) => row as unknown as Record<string, unknown>),
      ];
      for (const row of fresh) {
        const symbol = String(row.symbol || "").toUpperCase();
        if (!symbol) continue;
        const detected = Number(row.detected_at ?? row.created_at ?? now);
        const horizonMinutes = Number(row.horizon_minutes ?? 5);
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

  // Tek Sinyal Motoru Görünümleri
  const views = useMemo(() => {
    const rows = new Map<string, Record<string, unknown>>();

    // 1. Radar adayları
    for (const row of monitoring.data?.candidates ?? []) {
      const raw = row as Record<string, unknown>;
      const symbol = String(raw.symbol || "").toUpperCase();
      if (symbol) rows.set(`${symbol}:${Number(raw.horizon_minutes) || "unknown"}`, raw);
    }

    // 2. Anlık Nabız (Pulse) adayları
    for (const row of monitoring.data?.pulse ?? []) {
      const raw = row as Record<string, unknown>;
      const symbol = String(raw.symbol || "").toUpperCase();
      if (symbol && !rows.has(`${symbol}:1`)) {
        rows.set(`${symbol}:1`, { ...raw, horizon_minutes: 1, strategy: "pulse" });
      }
    }

    // 3. Günlük Yükseliş adayları
    for (const row of daily.data?.candidates ?? []) {
      const raw = row as unknown as Record<string, unknown>;
      const symbol = String(raw.symbol || "").toUpperCase();
      if (!symbol) continue;
      const horizonMinutes = Number(raw.horizon_minutes) || null;
      const matchedPending = (pendingSignals.data?.notifications || []).find(
        (n) => String(n.symbol || "").toUpperCase() === symbol && Number(n.horizon_minutes) > 0 && n.status === "BEKLİYOR"
      );
      const resolvedHorizon = horizonMinutes ?? (matchedPending ? Number(matchedPending.horizon_minutes) : null);
      const sources = Array.isArray(raw.confirm_sources) ? raw.confirm_sources : undefined;
      rows.set(`${symbol}:${resolvedHorizon ?? "unknown"}`, {
        ...raw,
        ...(resolvedHorizon ? { horizon_minutes: resolvedHorizon } : {}),
        ...(sources?.length ? { sources } : {}),
      });
    }

    // 4. Bekleyen bildirimler
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

    // 5. Hafızadaki aktif adaylar
    for (const [key, row] of Object.entries(seen)) {
      if (!rows.has(key)) rows.set(key, row);
    }

    // Adayları güçlü skora göre sırala
    const mapped = [...rows.values()].map((row) => toOpportunityView(row));
    return mapped.sort((a, b) => {
      // Önce favoriler, sonra en yüksek potansiyel ve sinyal gücü
      const favA = isFavorite(a.symbol) ? 1 : 0;
      const favB = isFavorite(b.symbol) ? 1 : 0;
      if (favA !== favB) return favB - favA;

      const potA = a.potentialPct ?? a.targetPct ?? 0;
      const potB = b.potentialPct ?? b.targetPct ?? 0;
      return potB - potA;
    });
  }, [monitoring.data, daily.data, pendingSignals.data, seen, isFavorite]);

  // Filtreleme
  const filtered = useMemo(() => {
    if (horizon === "favorites") {
      return views.filter((v) => isFavorite(v.symbol));
    }
    if (horizon === "all") return views;
    const want = Number(horizon);
    return views.filter((v) => (v.horizonMinutes == null ? horizon === "5" : v.horizonMinutes === want));
  }, [views, horizon, isFavorite]);

  const selectedView = useMemo(
    () => filtered.find((o) => `${o.symbol}:${o.horizonMinutes ?? "unknown"}` === selected || o.symbol === selected) || filtered[0] || null,
    [filtered, selected]
  );

  useEffect(() => {
    if (selected && !filtered.some((o) => `${o.symbol}:${o.horizonMinutes ?? "unknown"}` === selected || o.symbol === selected)) {
      setSelected(null);
    }
  }, [filtered, selected]);

  const loadingFirst = monitoring.loading && !monitoring.data;
  const allFailed = Boolean(monitoring.error) && Boolean(daily.error) && views.length === 0;

  return (
    <div className="space-y-5">
      {/* Canlı Bildirim Toast Katmanı */}
      <LiveNotificationToast
        onSelectSymbol={(sym) => {
          setSelected(sym);
          setQuickAmount(1000);
        }}
      />

      {/* Portföy ve K/Z Şeridi */}
      <PortfolioStrip />

      {allFailed && (
        <div className="odak-card border-loss/30 bg-loss-soft/50 p-3 text-sm text-loss">
          Fırsat verisi alınamadı — {monitoring.error || daily.error}. Backend çalışıyor mu?
        </div>
      )}

      {/* TEK SİNYAL MOTORU DURUM BANDI */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white/70 px-4 py-2.5 text-xs text-ink-600 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink-900 flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-gain odak-live-dot" />
            Tek Sinyal Motoru
          </span>
          <span className="text-ink-300">|</span>
          <span>Aktif Motorlar:</span>
          <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-700">Radar (5-15m)</span>
          <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-700">MACD MTF</span>
          <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-700">Günlük Yükseliş</span>
          <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-700">Erken Nabız</span>
        </div>

        <div className="flex items-center gap-3">
          {scanMessage && (
            <span className="font-medium text-accent animate-in fade-in duration-200">
              {scanMessage}
            </span>
          )}
          <button
            type="button"
            onClick={handleManualScan}
            disabled={scanBusy}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-accent/90 disabled:opacity-60 transition-all"
            title="Tüm sembolleri ve piyasayı anında yeniden tara"
          >
            <span className={scanBusy ? "animate-spin" : ""}>⚡</span>
            <span>{scanBusy ? "Taranıyor…" : "Piyasa Tara"}</span>
          </button>
        </div>
      </div>

      {/* ANA DÜZEN: Fırsatlar Kartları (Sol/Geniş) + Binance TR Emir Paneli (Sağ) */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="p-4 sm:p-5">
          <SectionHeader
            eyebrow="Fırsatlar & Yükseliş Adayları"
            title={
              <span className="inline-flex items-center gap-2">
                Anlık Sinyal Havuzu
                <Badge tone="gain">
                  <span className="h-1.5 w-1.5 rounded-full bg-gain odak-live-dot" /> {filtered.length} ADAY
                </Badge>
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
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-56 animate-pulse rounded-xl bg-canvas" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="mt-6 rounded-xl border border-dashed border-line py-12 text-center text-sm text-ink-400">
              {horizon === "favorites" ? (
                <div>
                  <p className="font-medium text-ink-600">Henüz favoriye alınmış aday bulunmuyor.</p>
                  <p className="mt-1 text-xs text-ink-400">
                    Fırsat kartlarındaki veya sembol arama çubuğundaki ☆ ikonuna tıklayarak favoriye ekleyebilirsiniz.
                  </p>
                </div>
              ) : (
                <div>
                  <p className="font-medium text-ink-600">Şu anda kriterlere uyan aday bulunmuyor.</p>
                  <p className="mt-1 text-xs text-ink-400">
                    Yukarıdaki <span className="font-semibold text-accent">"⚡ Piyasa Tara"</span> butonuna tıklayarak anlık tarama yapabilirsiniz.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="mt-4 grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.slice(0, 12).map((item, index) => (
                <OpportunityCard
                  key={`${item.symbol}:${item.horizonMinutes ?? "unknown"}`}
                  rank={index + 1}
                  item={item}
                  selected={selectedView?.symbol === item.symbol}
                  onSelect={() => {
                    setSelected(`${item.symbol}:${item.horizonMinutes ?? "unknown"}`);
                    setQuickAmount(null);
                  }}
                  onQuickBuy={(sym, amt) => {
                    setSelected(sym);
                    setQuickAmount(amt ?? 1000);
                  }}
                />
              ))}
            </div>
          )}
        </Card>

        {/* SAĞ: Hızlı Binance TR Spot Emir Paneli */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <OrderPanel
            initialSymbol={selectedView?.symbol ?? null}
            initialAmount={quickAmount}
            onTraded={() => {
              monitoring.reload();
              daily.reload();
            }}
          />
        </div>
      </div>

      {/* ALT: Aktif İşlemlerim Tablosu */}
      <Card className="p-5">
        <div id="aktif-islemler" className="scroll-mt-24">
          <SectionHeader
            eyebrow="Portföy & Pozisyonlar"
            title="Aktif Binance TR Varlıkları"
            description="Cüzdandaki açık coin bakiyeleri, anlık kâr/zarar ve maliyet durumu."
            actions={
              <Link
                href="/gecmis-islemler"
                className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent-soft transition-colors"
              >
                İşlem Geçmişi →
              </Link>
            }
          />
          <div className="mt-4">
            <ActiveTradesTable limit={10} />
          </div>
        </div>
      </Card>
    </div>
  );
}
