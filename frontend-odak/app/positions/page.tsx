"use client";

import { Card, SectionHeader, Stat } from "../components/ui";
import ActiveTradesTable from "../components/ActiveTradesTable";
import { usePoll } from "../lib/hooks";
import { formatPct, formatTL } from "../lib/format";
import type { PortfolioSummary, RiskSummary } from "../lib/types";

export default function PositionsPage() {
  const portfolio = usePoll<PortfolioSummary>("/api/portfolio/summary", 15_000);
  const risk = usePoll<RiskSummary>("/api/risk/summary", 15_000);

  const m = portfolio.data?.metrics;
  const gate = risk.data?.global_gate;

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Pozisyonlar"
        title="Açık pozisyonlar ve risk"
        description="Açık pozisyonlar, portföy metrikleri ve risk kapıları."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Açık pozisyon" value={String(risk.data?.open_positions ?? "…")} detail={`limit ${risk.data?.max_positions ?? "—"}`} />
        <Stat label="Bugün K/Z" value={formatTL(risk.data?.today_pnl)} tone={(risk.data?.today_pnl ?? 0) >= 0 ? "gain" : "loss"} />
        <Stat label="Ardışık zarar" value={String(risk.data?.consecutive_losses ?? "…")} tone={(risk.data?.consecutive_losses ?? 0) > 0 ? "warn" : "neutral"} />
        <Stat
          label="Risk kapısı"
          value={gate?.halt ? "DURDURULDU" : "AÇIK"}
          tone={gate?.halt ? "loss" : "gain"}
          detail={gate?.reason || (gate?.limit_try != null ? `limit ${formatTL(gate.limit_try)}` : undefined)}
        />
      </div>

      <Card className="p-5">
        <SectionHeader
          eyebrow="Kapalı işlem metrikleri"
          title="Portföy performansı"
          description={m ? `${m.closed_trades} kapalı işlem · kazanma oranı ${formatPct(m.win_rate, 1)}` : undefined}
        />
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Stat label="Net K/Z" value={formatTL(m?.net_pnl)} tone={(m?.net_pnl ?? 0) >= 0 ? "gain" : "loss"} />
          <Stat label="Kazanan" value={String(m?.winning_trades ?? "…")} />
          <Stat label="Toplam komisyon" value={formatTL(risk.data?.commission)} />
        </div>
      </Card>

      <Card className="p-5">
        <SectionHeader eyebrow="Aktif İşlemler" title="Açık pozisyon listesi" />
        <div className="mt-4">
          <ActiveTradesTable limit={200} />
        </div>
      </Card>
    </div>
  );
}
