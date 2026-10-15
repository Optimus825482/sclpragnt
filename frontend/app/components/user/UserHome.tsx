"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import KpiStrip, { type KpiData } from "./KpiStrip";
import RisingLiveTable, { type RisingRow } from "./RisingLiveTable";
import RecentNotifications, { type RecentRow } from "./RecentNotifications";

export default function UserHome() {
  const [kpiToday, setKpiToday] = useState<KpiData>(null);
  const [kpiAll, setKpiAll] = useState<KpiData>(null);
  const [rising, setRising] = useState<RisingRow[]>([]);
  const [recent, setRecent] = useState<RecentRow[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [today, all, live, hist] = await Promise.all([
        getJSON<any>("/api/reports/notifications?limit=1000"),
        getJSON<any>("/api/reports/notifications?day=all&limit=1"),
        getJSON<any>("/api/daily-rising/live"),
        getJSON<any>("/api/monitoring/notifications"),
      ]);
      setKpiToday(today?.breakdown ?? null);
      setKpiAll(all?.overall ?? null);
      setRising(live?.live ?? []);
      setRecent((hist?.history ?? []).slice(0, 5));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Veriler yüklenemedi");
    }
  }, []);
  useVisibleInterval(load, 15_000);
  // useVisibleInterval ilk yükü yapmaz.
  useEffect(() => { void load(); }, [load]);

  const prices = useWatchPrices([...rising.map((r) => r.symbol), ...recent.map((r) => r.symbol)]);
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Ana sayfa</h1>
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      <KpiStrip today={kpiToday} all={kpiAll} />
      <RisingLiveTable rows={rising} prices={prices} />
      <RecentNotifications rows={recent} prices={prices} />
    </div>
  );
}
