"use client";

import { usePoll } from "../lib/hooks";
import { formatPct, formatTL } from "../lib/format";
import type { DashboardSummary, PortfolioSummary } from "../lib/types";
import { Skeleton, Stat } from "./ui";

/**
 * Portföy şeridi — tasarımdaki alt özet çubuğunun sadeleştirilmiş hâli:
 * Toplam portföy / Günlük Kâr / Kullanılabilir bakiye. K/Z rengi YALNIZCA
 * işaretli veriye göre (0 veya null → nötr).
 */
export default function PortfolioStrip() {
  const { data: summary, error, loading } = usePoll<DashboardSummary>("/api/dashboard/summary", 15_000);
  const { data: portfolio } = usePoll<PortfolioSummary>("/api/portfolio/summary", 15_000);

  if (loading && !summary) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    );
  }

  if (error && !summary) {
    return (
      <div className="odak-card border-loss/30 bg-loss-soft/50 p-4 text-sm text-loss">
        Portföy özeti alınamadı: {error}
      </div>
    );
  }

  const p = summary?.portfolio;
  const dailyPnl = summary?.auto_paper_today.pnl ?? null;
  const dailyPnlPct = p && p.total_value > 0 && dailyPnl != null ? (dailyPnl / p.total_value) * 100 : null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat
        label="Toplam Portföy"
        value={formatTL(p?.total_value)}
        detail={`${p?.open_positions ?? 0} açık pozisyon`}
      />
      <Stat
        label="Günlük Kâr/Zarar"
        value={dailyPnl == null ? "—" : `${dailyPnl >= 0 ? "+" : ""}${formatTL(dailyPnl)}`}
        tone={dailyPnl == null ? "neutral" : dailyPnl > 0 ? "gain" : dailyPnl < 0 ? "loss" : "neutral"}
        detail={dailyPnlPct == null ? "otonom işlemler" : `${formatPct(dailyPnlPct, 2, true)} · otonom`}
      />
      <Stat
        label="Kullanılabilir Bakiye"
        value={formatTL(p?.balance)}
        detail={portfolio?.metrics ? `kapalı ${portfolio.metrics.closed_trades} · kazanma ${formatPct(portfolio.metrics.win_rate, 0)}` : "serbest TL"}
      />
    </div>
  );
}
