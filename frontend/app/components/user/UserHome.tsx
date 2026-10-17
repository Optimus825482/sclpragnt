"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import { useWatchPrefs } from "../../lib/useWatchPrefs";
import RecentNotifications, { type RecentRow } from "./RecentNotifications";
import WatchStrip from "./home/FavoritesStrip";

// 2026-10-17 (basit arayüz): "Bugünkü başarı" kartı ana sayfadan kaldırıldı — ayrıntılı başarı
// Raporlar sayfasında. KpiStrip bileşeni duruyor (başka yerde kullanılabilir).
export default function UserHome() {
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [error, setError] = useState("");
  const [recentFailed, setRecentFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const v = await getJSON<any>("/api/monitoring/notifications");
      setRecent((v?.history ?? []).slice(0, 10));
      setRecentFailed(false);
      setError("");
    } catch {
      // Başarısız istekte önceki liste korunur; hata ayrı gösterilir.
      setRecentFailed(true);
      setError("Bildirimler yüklenemedi, otomatik yeniden denenecek.");
    }
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
      <RecentNotifications rows={recent} prices={prices} failed={recentFailed} prefs={prefs} />
    </div>
  );
}
