"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import RegimeBanner from "./RegimeBanner";
import KpiStrip, { type KpiData } from "./KpiStrip";
import RecentNotifications, { type RecentRow } from "./RecentNotifications";

export default function UserHome() {
  const [kpiToday, setKpiToday] = useState<KpiData>(null);
  const [kpiAll, setKpiAll] = useState<KpiData>(null);
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [error, setError] = useState("");
  const [recentFailed, setRecentFailed] = useState(false);

  // Her bölüm KENDİ verisi gelir gelmez dolar; en yavaş isteği BEKLEMEZ. (Promise.all/allSettled en
  // yavaşı bekler: canlı kopyada /api/daily-rising/live 13-20 sn sürünce "Son bildirimler" de boş
  // görünüyordu.) Başarısız istekte önceki veri korunur; hata ayrı gösterilir.
  const load = useCallback(async () => {
    const track = <T,>(p: Promise<T>, apply: (v: T) => void): Promise<boolean> =>
      p.then((v) => { apply(v); return false; }, () => true);
    const [todayFailed, allFailed, histFailed] = await Promise.all([
      track(getJSON<any>("/api/reports/notifications?limit=1000"), (v) => setKpiToday(v?.breakdown ?? null)),
      track(getJSON<any>("/api/reports/notifications?day=all&limit=1"), (v) => setKpiAll(v?.overall ?? null)),
      track(getJSON<any>("/api/monitoring/notifications"), (v) => { setRecent((v?.history ?? []).slice(0, 5)); setRecentFailed(false); }),
    ]);
    if (histFailed) setRecentFailed(true);
    const failed = [todayFailed, allFailed, histFailed].filter(Boolean).length;
    setError(failed ? "Bazı veriler yüklenemedi, otomatik yeniden denenecek." : "");
  }, []);
  useVisibleInterval(load, 15_000);
  // useVisibleInterval ilk yükü yapmaz.
  useEffect(() => { void load(); }, [load]);

  const prices = useWatchPrices(recent.map((r) => r.symbol));
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Ana sayfa</h1>
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      <RegimeBanner />
      <KpiStrip today={kpiToday} all={kpiAll} />
      <RecentNotifications rows={recent} prices={prices} failed={recentFailed} />
    </div>
  );
}
