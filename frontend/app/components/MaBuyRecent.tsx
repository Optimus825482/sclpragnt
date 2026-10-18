"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { call } from "../lib/tradeApi";
import { useLiveMessages } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { useWatchPrices } from "../lib/useWatchPrices";
import { fmtPrice } from "../lib/tradeUi";
import {
  changeSinceSignal, fmtPct, fmtTrTime, paperStatusChip, parseRecent, ruleLabel, timeframeLabel, type MaBuyRecentItem,
} from "../lib/maBuyUi";
import BuyDialog from "./user/home/BuyDialog";

const ALERT_TYPES = ["monitoring_alert"] as const;

/**
 * Gönderilen MA kesişim BUY bildirimleri (M1/M5) — ana sayfa ve radar sayfasında aynı panel.
 * Kaynak GET /api/ma-buy/recent (yalnız push'u gerçekten gitmiş sinyaller). Yeni MA push'u WS ile gelince
 * liste hemen tazelenir; her satırda "Alım yap" alım penceresini açar.
 */
export default function MaBuyRecent({ hours = 12, limit = 20 }: { hours?: number; limit?: number }) {
  const [items, setItems] = useState<MaBuyRecentItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [buy, setBuy] = useState<{ symbol: string; price: number | null } | null>(null);

  const load = useCallback(async () => {
    const r = await call<unknown>("GET", `/api/ma-buy/recent?hours=${hours}&limit=${limit}`);
    setLoaded(true);
    if (!r.ok) { setFailed(true); return; }
    setFailed(false);
    setItems(parseRecent(r.body));
  }, [hours, limit]);

  useEffect(() => { void load(); }, [load]);
  useVisibleInterval(load, 60_000);
  useLiveMessages((m) => {
    const rows = Array.isArray(m.data) ? (m.data as { source?: string }[]) : [];
    if (rows.some((row) => row?.source === "ma_buy")) void load();
  }, ALERT_TYPES);

  const symbols = useMemo(() => [...new Set(items.map((i) => i.symbol))], [items]);
  const prices = useWatchPrices(symbols);

  return (
    <section aria-label="MA kesişim BUY bildirimleri" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">MA kesişim BUY sinyalleri</h2>
        <span className="text-xs text-bunker-muted">son {hours} saat · M1 / M5</span>
      </div>
      {!loaded ? (
        <div className="card p-4 text-sm text-bunker-muted" aria-live="polite">Yükleniyor…</div>
      ) : items.length === 0 ? (
        <div className={`card p-4 text-sm ${failed ? "text-neon-red" : "text-bunker-muted"}`} role={failed ? "alert" : undefined}>
          {failed ? "MA sinyalleri yüklenemedi. Birazdan yeniden denenecek." : "Henüz MA kesişim bildirimi yok."}
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {items.map((it) => {
            const live = prices[it.symbol] ?? null;
            const change = changeSinceSignal(it.signalPrice, live);
            const chip = paperStatusChip(it.paperStatus);
            return (
              <li key={it.id} className="card flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-semibold text-white">
                    <Link href={`/charts?symbol=${it.symbol}&timeframe=${it.timeframe}`} className="underline-offset-2 hover:underline">{it.symbol}</Link>
                    <span className="rounded-full border border-sky-400/50 px-2 text-xs text-sky-300">{timeframeLabel(it.timeframe)}</span>
                    {chip && (
                      <span className={`rounded-full px-2 text-xs ${chip.tone === "good" ? "bg-neon-green/15 text-neon-green" : "bg-bunker-800 text-bunker-muted"}`}>{chip.text}</span>
                    )}
                  </p>
                  <p className="truncate text-xs text-bunker-muted">{it.rules.map(ruleLabel).join(" · ") || "MA kesişimi"}</p>
                  <p className="text-xs text-bunker-muted">
                    {fmtTrTime(it.notifiedAt)} · sinyal {fmtPrice(it.signalPrice)}
                    {live != null && <> · şimdi {fmtPrice(live)}</>}
                    {change != null && (
                      <span className={change >= 0 ? " text-neon-green" : " text-neon-red"}> ({fmtPct(change)})</span>
                    )}
                  </p>
                </div>
                <button
                  type="button" onClick={() => setBuy({ symbol: it.symbol, price: live ?? it.signalPrice })}
                  className="ui-button-primary min-h-[44px] shrink-0 rounded-lg px-4 text-sm font-bold"
                  aria-label={`${it.symbol} alım yap`}
                >
                  Alım yap
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {buy && <BuyDialog open symbol={buy.symbol} referencePrice={buy.price} onClose={() => setBuy(null)} />}
    </section>
  );
}
