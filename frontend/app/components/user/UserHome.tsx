"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import RegimeBanner from "./RegimeBanner";
import KpiStrip, { type KpiData } from "./KpiStrip";
import RisingLiveTable, { type RisingRow } from "./RisingLiveTable";
import RecentNotifications, { type RecentRow } from "./RecentNotifications";

export default function UserHome() {
  const [kpiToday, setKpiToday] = useState<KpiData>(null);
  const [kpiAll, setKpiAll] = useState<KpiData>(null);
  const [rising, setRising] = useState<RisingRow[]>([]);
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [error, setError] = useState("");
  const [recentFailed, setRecentFailed] = useState(false);

  // Her bölüm KENDİ verisi gelir gelmez dolar; en yavaş isteği BEKLEMEZ. (Promise.all/allSettled en
  // yavaşı bekler: canlı kopyada /api/daily-rising/live 13-20 sn sürünce "Son bildirimler" de boş
  // görünüyordu.) Başarısız istekte önceki veri korunur; hata ayrı gösterilir.
  const load = useCallback(async () => {
    const track = <T,>(p: Promise<T>, apply: (v: T) => void): Promise<boolean> =>
      p.then((v) => { apply(v); return false; }, () => true);
    const [todayFailed, allFailed, liveFailed, histFailed] = await Promise.all([
      track(getJSON<any>("/api/reports/notifications?limit=1000"), (v) => setKpiToday(v?.breakdown ?? null)),
      track(getJSON<any>("/api/reports/notifications?day=all&limit=1"), (v) => setKpiAll(v?.overall ?? null)),
      track(getJSON<any>("/api/daily-rising/live"), (v) => setRising(v?.live ?? [])),
      track(getJSON<any>("/api/monitoring/notifications"), (v) => { setRecent((v?.history ?? []).slice(0, 5)); setRecentFailed(false); }),
    ]);
    if (histFailed) setRecentFailed(true);
    const failed = [todayFailed, allFailed, liveFailed, histFailed].filter(Boolean).length;
    setError(failed ? "Bazı veriler yüklenemedi, otomatik yeniden denenecek." : "");
  }, []);
  useVisibleInterval(load, 15_000);
  // useVisibleInterval ilk yükü yapmaz.
  useEffect(() => { void load(); }, [load]);

  const prices = useWatchPrices([...rising.map((r) => r.symbol), ...recent.map((r) => r.symbol)]);
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Ana sayfa</h1>
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      <RegimeBanner />
      <KpiStrip today={kpiToday} all={kpiAll} />
      <RisingLiveTable rows={rising} prices={prices} />
      <RecentNotifications rows={recent} prices={prices} failed={recentFailed} />
    </div>
  );
}
