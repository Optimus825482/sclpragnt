"use client";

export type KpiData = {
  success_rate?: number | null;
  success_count?: number | null;
  evaluated?: number | null;
} | null;

function KpiCard({ title, data }: { title: string; data: KpiData }) {
  const evaluated = Number(data?.evaluated ?? 0);
  const rate = data?.success_rate;
  const hasRate = evaluated > 0 && rate != null && Number.isFinite(Number(rate));
  // Oran → renk: ≥%50 yeşil, ≥%30 amber, altı kırmızı; ölçüm yoksa nötr.
  const tone = !hasRate ? "wait" : Number(rate) >= 50 ? "good" : Number(rate) >= 30 ? "warn" : "bad";
  return (
    <div className={`card u-card-${tone} flex items-center justify-between gap-3 px-4 py-3`}>
      <div className="min-w-0">
        <p className="text-sm font-medium text-bunker-muted">{title}</p>
        <p className="text-sm text-bunker-muted">
          {evaluated === 0
            ? "Henüz ölçülmedi"
            : `${Number(data?.success_count ?? 0)}/${evaluated} bildirim hedefe ulaştı`}
        </p>
      </div>
      <p className={`shrink-0 text-2xl font-bold u-num-${tone}`}>{hasRate ? `%${Number(rate).toFixed(0)}` : "—"}</p>
    </div>
  );
}

/** Ana sayfada yalnız "Bugünkü başarı" gösterilir (tam genişlik, kompakt). */
export default function KpiStrip({ today }: { today: KpiData }) {
  return (
    <section aria-label="Başarı özeti">
      <KpiCard title="Bugünkü başarı" data={today} />
    </section>
  );
}
