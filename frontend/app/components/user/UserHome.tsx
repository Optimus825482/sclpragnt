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

  // Her istek BAĞIMSIZ: biri (ör. rapor ucu) hata verse bile diğer bölümler dolar.
  // Önceden Promise.all tek hatada hepsini boş bırakıyor, "Son bildirimler" boş görünüyordu.
  // Başarısız istekte önceki veri korunur (ekran boşalmaz).
  const load = useCallback(async () => {
    const [today, all, live, hist] = await Promise.allSettled([
      getJSON<any>("/api/reports/notifications?limit=1000"),
      getJSON<any>("/api/reports/notifications?day=all&limit=1"),
      getJSON<any>("/api/daily-rising/live"),
      getJSON<any>("/api/monitoring/notifications"),
    ]);
    if (today.status === "fulfilled") setKpiToday(today.value?.breakdown ?? null);
    if (all.status === "fulfilled") setKpiAll(all.value?.overall ?? null);
    if (live.status === "fulfilled") setRising(live.value?.live ?? []);
    if (hist.status === "fulfilled") setRecent((hist.value?.history ?? []).slice(0, 5));
    setRecentFailed(hist.status === "rejected");
    const failed = [today, all, live, hist].filter((r) => r.status === "rejected").length;
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
