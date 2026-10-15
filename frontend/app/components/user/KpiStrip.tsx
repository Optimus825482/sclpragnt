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
  return (
    <div className="card p-4">
      <p className="text-sm text-bunker-muted">{title}</p>
      <p className="mt-1 text-3xl font-semibold text-white">{hasRate ? `%${Number(rate).toFixed(0)}` : "—"}</p>
      <p className="mt-1 text-sm text-bunker-muted">
        {evaluated === 0
          ? "Henüz ölçülmedi"
          : `${Number(data?.success_count ?? 0)}/${evaluated} bildirim hedefe ulaştı`}
      </p>
    </div>
  );
}

export default function KpiStrip({ today, all }: { today: KpiData; all: KpiData }) {
  return (
    <section aria-label="Başarı özeti" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <KpiCard title="Bugünkü başarı" data={today} />
      <KpiCard title="Toplam başarı" data={all} />
    </section>
  );
}
