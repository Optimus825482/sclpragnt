"use client";

import { usePoll } from "../lib/hooks";
import { formatPct, formatTL } from "../lib/format";
import type { BinancePositions, BinanceSettings, DashboardSummary, PortfolioSummary } from "../lib/types";

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

  if (!configured) return null;

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

  const metrics = [
    {
      label: "Toplam Portföy",
      value: totalValue != null ? formatTL(totalValue) : "…",
      detail: `${summary.data?.portfolio?.open_positions ?? 0} açık işlem`,
      valueTone: "text-ink-900",
    },
    {
      label: "Serbest Bakiye",
      value: tryFree != null ? formatTL(tryFree) : "…",
      detail: portfolio.data?.metrics ? `Kapalı ${portfolio.data.metrics.closed_trades} işlem · TRY` : "Kullanılabilir TRY",
      valueTone: "text-ink-900",
    },
    {
      label: "Bugünkü K/Z",
      value: dailyPnl == null ? "—" : `${dailyPnl >= 0 ? "+" : ""}${formatTL(dailyPnl)}`,
      detail: dailyPct == null ? "Gerçekleşen + açık K/Z yükleniyor" : `${formatPct(dailyPct, 2, true)} · gerçekleşen + açık K/Z`,
      valueTone: dailyPnl == null ? "text-ink-900" : dailyPnl > 0 ? "text-gain" : dailyPnl < 0 ? "text-loss" : "text-ink-900",
    },
  ];

  return (
    <section aria-label="Portföy özeti" className="odak-card grid grid-cols-1 divide-y divide-line px-4 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
      {metrics.map((metric) => (
        <div key={metric.label} className="min-w-0 px-3 py-3 first:pl-0 last:pr-0">
          <p className="odak-kicker">{metric.label}</p>
          <p className={`mt-1 font-mono text-xl font-semibold tracking-tight ${metric.valueTone}`}>{metric.value}</p>
          <p className="mt-0.5 text-xs text-ink-400">{metric.detail}</p>
        </div>
      ))}
    </section>
  );
}
