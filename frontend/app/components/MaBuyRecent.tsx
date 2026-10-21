"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { call } from "../lib/tradeApi";
import { useLiveMessages } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { useWatchPrefs } from "../lib/useWatchPrefs";
import { useWatchPrices } from "../lib/useWatchPrices";
import { paperStatusChip, parseRecent, toCardRow, type MaBuyRecentItem } from "../lib/maBuyUi";
import BuyDialog from "./user/home/BuyDialog";
import NotificationCard, { type CardActions } from "./user/home/NotificationCard";

const ALERT_TYPES = ["monitoring_alert"] as const;
const nowSeconds = () => Math.floor(Date.now() / 1000);

/**
 * Gönderilen MA kesişim BUY bildirimleri (M1/M5) — ana sayfa ve radar sayfasında, "Son bildirimler" ile AYNI kartla
 * (`NotificationCard`: kaç dk önce, hedef, canlı fiyat/değişim, durum, Alım yap / Favori / İzleme / Grafik).
 * Kaynak GET /api/ma-buy/recent (yalnız push'u gerçekten gitmiş sinyaller); yeni MA push'unda WS ile anında tazelenir.
 */
export default function MaBuyRecent({ hours = 12, limit = 20 }: { hours?: number; limit?: number }) {
  const [items, setItems] = useState<MaBuyRecentItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [buy, setBuy] = useState<{ symbol: string; price: number | null } | null>(null);
  const [prefError, setPrefError] = useState("");
  const [nowSec, setNowSec] = useState(nowSeconds);

  const load = useCallback(async () => {
    const r = await call<unknown>("GET", `/api/ma-buy/recent?hours=${hours}&limit=${limit}`);
    setLoaded(true);
    if (!r.ok) { setFailed(true); return; }
    setFailed(false);
    setItems(parseRecent(r.body));
  }, [hours, limit]);

  useEffect(() => { void load(); }, [load]);
  useVisibleInterval(load, 60_000);
  useVisibleInterval(() => setNowSec(nowSeconds()), 30_000); // "kaç dk önce" güncel kalsın
  useLiveMessages((m) => {
    const rows = Array.isArray(m.data) ? (m.data as { source?: string }[]) : [];
    if (rows.some((row) => row?.source === "ma_buy")) void load();
  }, ALERT_TYPES);

  const prefs = useWatchPrefs();
  const symbols = useMemo(() => [...new Set(items.map((i) => i.symbol))], [items]);
  const prices = useWatchPrices(symbols);
  const rows = useMemo(() => items.map((it) => {
    const row = toCardRow(it);
    const chip = paperStatusChip(it.paperStatus);
    return chip ? { ...row, detail: `${row.detail} · ${chip.text}` } : row;
  }), [items]);

  const guard = (p: Promise<void>) => {
    setPrefError("");
    p.catch(() => setPrefError("Değişiklik kaydedilemedi, lütfen tekrar deneyin."));
  };
  const actions: CardActions = {
    isFavorite: prefs.isFavorite,
    isPinned: prefs.isPinned,
    onToggleFavorite: (s, p) => guard(prefs.toggleFavorite(s, p)),
    onTogglePin: (s, p) => guard(prefs.togglePin(s, p)),
    onBuy: (s, p) => setBuy({ symbol: s, price: p }),
  };

  return (
    <section aria-label="MA kesişim BUY bildirimleri">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">MA kesişim bildirimleri</h2>
        <span className="text-xs text-bunker-muted">son {hours} saat · tüm zaman dilimleri</span>
      </div>
      {prefError && <p role="alert" className="mb-2 rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{prefError}</p>}
      {!loaded ? (
        <div className="card p-4 text-sm text-bunker-muted" aria-live="polite">Yükleniyor…</div>
      ) : rows.length === 0 ? (
        <div className={`card p-4 text-sm ${failed ? "text-neon-red" : "text-bunker-muted"}`} role={failed ? "alert" : undefined}>
          {failed ? "MA bildirimleri yüklenemedi. Birazdan yeniden denenecek." : "Henüz MA kesişim bildirimi yok."}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {rows.map((r, i) => (
            <NotificationCard
              key={r.id} row={r} rank={i + 1} nowSec={nowSec} actions={actions}
              live={prices[r.symbol.toUpperCase()] ?? prices[r.symbol] ?? null}
            />
          ))}
        </div>
      )}
      {buy && <BuyDialog open symbol={buy.symbol} referencePrice={buy.price} onClose={() => setBuy(null)} />}
    </section>
  );
}
