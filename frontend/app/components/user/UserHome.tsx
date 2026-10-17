"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import { useWatchPrefs } from "../../lib/useWatchPrefs";
import KpiStrip, { type KpiData } from "./KpiStrip";
import RecentNotifications, { type RecentRow } from "./RecentNotifications";
import WatchStrip from "./home/FavoritesStrip";

export default function UserHome() {
  const [kpiToday, setKpiToday] = useState<KpiData>(null);
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [error, setError] = useState("");
  const [recentFailed, setRecentFailed] = useState(false);

  // Her bölüm KENDİ verisi gelir gelmez dolar; en yavaş isteği BEKLEMEZ. (Promise.all/allSettled en
  // yavaşı bekler: canlı kopyada /api/daily-rising/live 13-20 sn sürünce "Son bildirimler" de boş
  // görünüyordu.) Başarısız istekte önceki veri korunur; hata ayrı gösterilir.
  const load = useCallback(async () => {
    const track = <T,>(p: Promise<T>, apply: (v: T) => void): Promise<boolean> =>
      p.then((v) => { apply(v); return false; }, () => true);
    const [todayFailed, histFailed] = await Promise.all([
      track(getJSON<any>("/api/reports/notifications?limit=1000"), (v) => setKpiToday(v?.breakdown ?? null)),
      track(getJSON<any>("/api/monitoring/notifications"), (v) => { setRecent((v?.history ?? []).slice(0, 10)); setRecentFailed(false); }),
    ]);
    if (histFailed) setRecentFailed(true);
    const failed = [todayFailed, histFailed].filter(Boolean).length;
    setError(failed ? "Bazı veriler yüklenemedi, otomatik yeniden denenecek." : "");
  }, []);
  useVisibleInterval(load, 15_000);
  // useVisibleInterval ilk yükü yapmaz.
  useEffect(() => { void load(); }, [load]);

  const prefs = useWatchPrefs();
  const prices = useWatchPrices([
    ...recent.map((r) => r.symbol),
    ...prefs.pinned.map((p) => p.symbol),
    ...prefs.favorites.map((f) => f.symbol),
  ]);
  const onRemove = (symbol: string, which: { pinned: boolean; favorite: boolean }) => {
    const jobs: Promise<void>[] = [];
    if (which.pinned) jobs.push(prefs.removePin(symbol));
    if (which.favorite) jobs.push(prefs.removeFavorite(symbol));
    Promise.all(jobs).catch(() => setError("Değişiklik kaydedilemedi, lütfen tekrar deneyin."));
  };
  return (
    <div className="space-y-5">
      <WatchStrip pinned={prefs.pinned} favorites={prefs.favorites} prices={prices} onRemove={onRemove} />
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      <KpiStrip today={kpiToday} />
      <RecentNotifications rows={recent} prices={prices} failed={recentFailed} prefs={prefs} />
    </div>
  );
}
