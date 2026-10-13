"use client";

import { usePoll } from "../lib/hooks";
import { formatPct, formatTL } from "../lib/format";
import type { BinancePositions, BinanceSettings, DashboardSummary, PortfolioSummary } from "../lib/types";
import { Skeleton, Stat } from "./ui";

/**
 * Portföy şeridi — Toplam Portföy / Günlük Kâr-Zarar / Kullanılabilir Bakiye.
 *
 * Kullanıcı Binance anahtarı GİRMEDİYSE portföy bölümü GÖSTERİLMEZ (kullanıcı
 * isteği): gerçek bakiye bilinmezken uydurma sayı basmak yanıltıcı olurdu.
 * Anahtar varsa gerçek TRY bakiyesi ve hesaplanan toplam değer kullanılır.
 */
export default function PortfolioStrip() {
  const binance = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const configured = Boolean(binance.data?.configured);

  const summary = usePoll<DashboardSummary>(configured ? "/api/dashboard/summary" : null, 15_000);
  const portfolio = usePoll<PortfolioSummary>(configured ? "/api/portfolio/summary" : null, 15_000);
  const realPositions = usePoll<BinancePositions>(configured ? "/api/binance/positions" : null, 30_000);

  if (!configured) {
    return (
      <div className="odak-card p-4 text-sm text-ink-500">
        Portföy bilgisi için Binance TR API anahtarlarınızı girin (Ayarlar). Anahtar girilene kadar
        portföy ve bakiye bölümleri gizlenir.
      </div>
    );
  }

  const tryFree = (() => {
    const b = realPositions.data?.balances?.find((x) => x.asset === "TRY");
    return b ? Number(b.free) : null;
  })();
  const totalValue = realPositions.data?.total_value_try ?? null;
  const dailyPnl = summary.data?.auto_paper_today.pnl ?? null;
  const dailyPct = summary.data?.portfolio?.total_value
    ? (Number(dailyPnl) / Number(summary.data.portfolio.total_value)) * 100
    : null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat
        label="Toplam Portföy"
        value={totalValue != null ? formatTL(totalValue) : "…"}
        detail={`${summary.data?.portfolio?.open_positions ?? 0} açık işlem`}
      />
      <Stat
        label="Günlük Kâr/Zarar"
        value={dailyPnl == null ? "—" : `${dailyPnl >= 0 ? "+" : ""}${formatTL(dailyPnl)}`}
        tone={dailyPnl == null ? "neutral" : dailyPnl > 0 ? "gain" : dailyPnl < 0 ? "loss" : "neutral"}
        detail={dailyPct == null ? "otonom işlemler" : `${formatPct(dailyPct, 2, true)} · otonom`}
      />
      <Stat
        label="Kullanılabilir Bakiye"
        value={tryFree != null ? formatTL(tryFree) : "…"}
        detail={portfolio.data?.metrics ? `kapalı ${portfolio.data.metrics.closed_trades} işlem` : "serbest TRY"}
      />
    </div>
  );
}
