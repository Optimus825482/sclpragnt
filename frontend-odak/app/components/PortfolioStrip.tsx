"use client";

import { usePoll } from "../lib/hooks";
import { formatPct, formatTL } from "../lib/format";
import type { BinancePositions, BinanceSettings, DashboardSummary, PortfolioSummary } from "../lib/types";
import { Skeleton, Stat } from "./ui";

type BinanceDayTrades = { daily?: { realized_pnl_try?: number | null } };

function istanbulDate() {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "00";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

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
  const today = usePoll<BinanceDayTrades>(configured ? `/api/binance/trades-day?date=${istanbulDate()}` : null, 120_000, 30_000);

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
  const realizedToday = today.data?.daily?.realized_pnl_try;
  const openPnl = realPositions.data?.holdings?.reduce((sum, h) => sum + Number(h.pnl_try || 0), 0);
  const dailyPnl = realizedToday == null || openPnl == null ? null : Number(realizedToday) + openPnl;
  const dailyPct = totalValue && dailyPnl != null
    ? (Number(dailyPnl) / Number(totalValue)) * 100
    : null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat
        label="Toplam Portföy"
        value={totalValue != null ? formatTL(totalValue) : "…"}
        detail={`${summary.data?.portfolio?.open_positions ?? 0} açık işlem`}
      />
      <Stat
        label="Bugün + Açık K/Z"
        value={dailyPnl == null ? "—" : `${dailyPnl >= 0 ? "+" : ""}${formatTL(dailyPnl)}`}
        tone={dailyPnl == null ? "neutral" : dailyPnl > 0 ? "gain" : dailyPnl < 0 ? "loss" : "neutral"}
        detail={dailyPct == null ? "günlük gerçekleşen + açık varlıklar yükleniyor" : `${formatPct(dailyPct, 2, true)} · gerçekleşen + açık K/Z`}
      />
      <Stat
        label="Kullanılabilir Bakiye"
        value={tryFree != null ? formatTL(tryFree) : "…"}
        detail={portfolio.data?.metrics ? `kapalı ${portfolio.data.metrics.closed_trades} işlem` : "serbest TRY"}
      />
    </div>
  );
}
