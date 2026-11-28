"use client";

import { useEffect, useState } from "react";
import SymbolLink from "../components/SymbolLink";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice } from "../lib/format";

type Row = {
  symbol: string;
  seed_ms: number;
  watch_ms: number;
  signal_ms: number | null;
  signal_price: number | null;
  base_price: number;
  spread_pct: number | null;
  display_status: "watch" | "expired" | "blocked" | "open" | "closed";
  reason: string | null;
  entry_price: number | null;
  exit_price: number | null;
  mark_price: number | null;
  marked_at: number | null;
  closed_at: number | null;
  exit_due_at: number | null;
  net_pnl_try: number | null;
  net_pnl_pct: number | null;
  mark_net_pct: number | null;
  peak_net_pct: number | null;
  trailing_stop_pct: number | null;
  followup_bars?: number;
  followup_low?: number | null;
  followup_high?: number | null;
  followup_close?: number | null;
  watch_high?: number | null;
  late_signal_ms?: number | null;
};

type Report = {
  initial_cash: number;
  notional: number;
  fee_pct: number;
  trailing: { activation_pct: number; initial_gap: number; min_gap: number };
  stop_pct: number;
  hold_minutes: number;
  followup_minutes?: number;
  limit: number;
  summary: { watched: number; signals: number; opened: number; closed: number; blocked: number; wins: number; net_try: number };
  rows: Row[];
};

const statuses: Record<Row["display_status"], string> = {
  watch: "İzleniyor", expired: "Pencere doldu", blocked: "Açılmadı", open: "Açık", closed: "Kapandı",
};
const reasons: Record<string, string> = {
  target: "Hedef", trailing: "Takip stopu", stop: "Stop", time: "Süre", quote_unavailable: "Kotasyon yok",
  insufficient_depth: "Yetersiz derinlik", insufficient_cash: "Yetersiz paper bakiye",
  already_open: "Paritede açık işlem var", stale_signal: "Sinyal gecikti",
  radar_price_moved: "Fiyat radar giriş aralığından çıktı",
  global_kill_switch: "Girişler durduruldu", daily_loss_limit: "Günlük zarar sınırı",
};
const percent = (n: number | null) => n == null ? "—" : `%${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const points = (n: number) => n.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
const price = (n: number | null) => n == null ? "—" : `₺${formatPrice(n)}`;
const cash = (n: number) => n.toLocaleString("tr-TR", { style: "currency", currency: "TRY" });
const stamp = (ms: number) => new Date(ms).toLocaleString("tr-TR", {
  timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

function Followup({ row, minutes }: { row: Row; minutes: number }) {
  const { followup_bars: bars, followup_low: low, followup_high: high, followup_close: close, entry_price: entry } = row;
  if (row.display_status === "expired") {
    const watchPeak = row.watch_high != null ? 100 * (row.watch_high / row.base_price - 1) : null;
    return (
      <>
        <div>{row.late_signal_ms ? `Pencere sonrası +%15 kapanış · ${stamp(row.late_signal_ms)}` : "Pencere içinde +%15 kapanış gelmedi"}</div>
        {watchPeak != null && <div className="text-xs text-bunker-muted">Pencere içi zirve {percent(watchPeak)}</div>}
        {bars && high != null && close != null ? <div className="text-xs text-bunker-muted">
          Son {price(close)} · Zirve {price(high)} · {bars}/{minutes} dk
        </div> : null}
      </>
    );
  }
  if (row.display_status !== "closed" || (row.reason !== "stop" && row.reason !== "trailing")) return "—";
  if (!bars || low == null || high == null || close == null) return "Mum verisi bekleniyor";
  const rebound = 100 * (close / low - 1);
  return (
    <>
      <div>Son {price(close)} · Zirve {price(high)}</div>
      <div className="text-xs text-bunker-muted">
        Dipten {percent(rebound)} · {entry != null && (high >= entry ? "Girişe ulaştı" : "Girişin altında")} · {bars}/{minutes} dk
      </div>
    </>
  );
}

export default function LargeMovePaperTab({ day, includeArchived }: { day: string; includeArchived: boolean }) {
  const scope = `${day}/${includeArchived}`;
  const [result, setResult] = useState<{ scope: string; data: Report | null; error: boolean } | null>(null);
  const data = result?.scope === scope ? result.data : null;
  const error = result?.scope === scope && result.error;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ include_archived: String(includeArchived) });
    if (day !== "all") params.set("day", day);
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const response = await apiRequest(`${API_BASE}/api/reports/large-move-paper?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        const next: Report = await response.json();
        if (!controller.signal.aborted) {
          setResult({ scope, data: next, error: false });
        }
      } catch {
        if (!controller.signal.aborted) setResult((previous) => ({
          scope, data: previous?.scope === scope ? previous.data : null, error: true,
        }));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 15_000);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [day, includeArchived, scope]);

  if (!data) return <p role="status" className="py-8 text-center text-sm text-bunker-muted">
    {error ? "Büyük Hareket raporu alınamadı. Bağlantı yeniden deneniyor." : "Büyük Hareket raporu yükleniyor…"}
  </p>;

  const s = data.summary;
  const cards = [
    ["İzlemeye alınan", s.watched], ["+%15 sinyali", s.signals], ["Açık", s.opened],
    ["Kapanan", s.closed], ["Açılamayan", s.blocked], ["Gerçekleşen paper K/Z", cash(s.net_try)],
  ];
  return (
    <section className="space-y-4" aria-labelledby="large-move-title">
      <div>
        <h2 id="large-move-title" className="text-lg font-bold text-white">Büyük Hareket Paper</h2>
        <p className="mt-1 text-sm text-bunker-muted">
          Bu rapor Büyük Hareket stratejisinin ayrı sanal bakiyesini ve işlemlerini gösterir.
          +%10 kapanışta izleme başlar, +%15 kapanışta paper giriş değerlendirilir.{" "}
          {cash(data.initial_cash)} sanal bakiye, işlem başına {cash(data.notional)}.
          Takip stopu net {percent(data.trailing.activation_pct)} kârda başlar.
          Zirveye mesafe {points(data.trailing.initial_gap)} yüzde puandan {points(data.trailing.min_gap)} puana kadar daralır.
          İlk stop {percent(data.stop_pct)}, süre çıkışı {data.hold_minutes} dakika.
          Komisyon her yönde {percent(data.fee_pct)}.
        </p>
      </div>
      {error && <p role="status" className="text-sm text-amber-300">Yenileme başarısız. Son alınan veriler gösteriliyor.</p>}
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map(([name, value]) => (
          <div key={name} className="rounded-xl border border-bunker-800 bg-bunker-950/70 p-3">
            <dt className="text-xs text-bunker-muted">{name}</dt>
            <dd className="mt-1 font-mono text-lg font-semibold tabular-nums text-white">{value}</dd>
          </div>
        ))}
      </dl>
      {data.rows.length === 0 ? (
        <p className="rounded-xl border border-bunker-800 p-4 text-sm text-bunker-muted">Bu dönem için izleme veya paper işlem kaydı yok.</p>
      ) : (
        <div className="table-scroll max-h-[36rem]" role="region" aria-label="Büyük Hareket paper işlem geçmişi" tabIndex={0}>
          <table className="data-table table-compact whitespace-nowrap">
            <thead className="sticky top-0 z-10 bg-bunker-950">
              <tr>{["Parite", "İzlemeye alındı", "+%15 sinyali", "Giriş spread’i", "Durum", "Paper giriş", "Son kotasyon / paper çıkış", "Çıkış öncesi net zirve", "Takip stopu", "Net paper K/Z", "Sonraki hareket"].map((label) => (
                <th key={label} scope="col">{label}</th>
              ))}</tr>
            </thead>
            <tbody>
              {data.rows.map((row) => {
                const net = row.net_pnl_pct ?? row.mark_net_pct;
                const outcome = row.reason && row.display_status === "open" && row.exit_due_at
                  ? `Çıkış bekliyor · ${reasons[row.reason] ?? row.reason}`
                  : row.reason ? reasons[row.reason] ?? row.reason : null;
                return (
                  <tr key={`${row.symbol}-${row.seed_ms}`}>
                    <th scope="row"><SymbolLink symbol={row.symbol} timeframe="1m" /></th>
                    <td>{stamp(row.watch_ms)}</td>
                    <td>{row.signal_ms ? `${stamp(row.signal_ms)} · ${price(row.signal_price)}` : "—"}</td>
                    <td>{percent(row.spread_pct)}</td>
                    <td>{statuses[row.display_status]}{outcome && <span className="ml-2 text-xs text-bunker-muted">{" "}{outcome}</span>}</td>
                    <td>{price(row.entry_price)}</td>
                    <td title={!row.closed_at && row.marked_at ? stamp(row.marked_at * 1000) : undefined}>
                      {price(row.exit_price ?? row.mark_price)}
                      {row.closed_at && <span className="block text-xs text-bunker-muted">{stamp(row.closed_at * 1000)}</span>}
                    </td>
                    <td>{percent(row.peak_net_pct)}</td>
                    <td>{percent(row.trailing_stop_pct)}</td>
                    <td className={net == null ? "text-bunker-muted" : net >= 0 ? "text-neon-green" : "text-rose-300"}>
                      {percent(net)}
                      {row.net_pnl_try != null && <span className="block text-xs">{cash(row.net_pnl_try)}</span>}
                    </td>
                    <td><Followup row={row} minutes={data.followup_minutes ?? 30} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {s.watched > data.limit && <p className="text-xs text-bunker-muted">Tablo {data.limit} kayıtla sınırlı. Daha eski kayıtları tarih filtresiyle görüntüleyin.</p>}
    </section>
  );
}
