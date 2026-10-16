"use client";
import Link from "next/link";
import PctChange from "../PctChange";
import { formatPrice, toMs } from "../../../lib/format";
import { baseSymbol, confidenceBadge, modeLabel, notificationStatus } from "../../../lib/userUi";
import type { WatchItem } from "../../../lib/useWatchPrefs";

export type RecentRow = {
  symbol: string;
  price: number;
  detected_at: number;
  id?: number | string;
  message?: string | null;
  title?: string | null;
  score?: number | null;
  target_pct?: number | null;
  expected_price?: number | null;
  horizon_minutes?: number | null;
  mode?: string | null;
  sent_via_push?: boolean | number | null;
  llm_verdict?: string | null;
  llm_confidence?: number | null;
  llm_reasons?: unknown;
};

/** "14:05 · 12 dk önce" */
export function when(ts: number): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  const time = new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  const rel = min < 1 ? "az önce" : min < 60 ? `${min} dk önce` : `${Math.floor(min / 60)} sa önce`;
  return `${time} · ${rel}`;
}

const tl = (v: number | null | undefined) => (Number(v) > 0 ? `₺${formatPrice(v)}` : "—");
const pctText = (v: number | null | undefined) =>
  v != null && Number.isFinite(Number(v)) ? `+${Number(v).toFixed(2).replace(".", ",")}%` : "—";
const chartHref = (symbol: string) => `/charts?symbol=${encodeURIComponent(symbol)}&timeframe=5m`;

const BTN = "ui-button ui-button-secondary inline-flex min-h-[44px] items-center justify-center gap-1";

export type CardActions = {
  isFavorite: (symbol: string) => boolean;
  isPinned: (symbol: string) => boolean;
  onToggleFavorite: (symbol: string, price: number | null) => void;
  onTogglePin: (symbol: string, price: number | null) => void;
  onBuy: (symbol: string, price: number | null) => void;
};

function StarButton({ symbol, fav, onClick }: { symbol: string; fav: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={fav}
      aria-label={fav ? `${baseSymbol(symbol)} favoriden çıkar` : `${baseSymbol(symbol)} favorilere ekle`}
      className={`inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-xl ${fav ? "text-neon-green" : "text-bunker-muted"}`}
    >
      {fav ? "★" : "☆"}
    </button>
  );
}

function PinBadge({ item, live }: { item: WatchItem; live: number | null }) {
  return (
    <p className="u-chip u-chip-info whitespace-normal text-xs">
      <span>👁 İzlemeye alındığında {tl(item.price)} · şimdi</span>
      <PctChange base={item.price} live={live} />
    </p>
  );
}

function ActionRows({ symbol, price, live, actions }: { symbol: string; price: number | null; live: number | null; actions: CardActions }) {
  const fav = actions.isFavorite(symbol);
  const pin = actions.isPinned(symbol);
  const px = live ?? price;
  return (
    <div className="mt-3 space-y-2">
      <button
        type="button"
        onClick={() => actions.onBuy(symbol, price)}
        className="ui-button ui-button-primary u-btn-brand inline-flex min-h-[44px] w-full items-center justify-center gap-1"
      >
        ⚡ Alım yap
      </button>
      <div className="grid grid-cols-2 gap-2">
        <Link href={chartHref(symbol)} className={BTN}>📈 Grafik</Link>
        <button type="button" aria-pressed={pin} onClick={() => actions.onTogglePin(symbol, px)} className={BTN}>
          {pin ? "İzlemeden çıkar" : "👁 İzlemeye al"}
        </button>
      </div>
      <button type="button" aria-pressed={fav} onClick={() => actions.onToggleFavorite(symbol, px)} className={`${BTN} w-full`}>
        {fav ? "★ Favoride" : "☆ Favorilere ekle"}
      </button>
    </div>
  );
}

/** Tam bildirim kartı ("Yükseliş Adayları" tarzı). */
export default function NotificationCard({
  row, rank, live, nowSec, actions, pinned,
}: { row: RecentRow; rank?: number; live: number | null; nowSec: number; actions: CardActions; pinned?: WatchItem }) {
  const status = notificationStatus(row, live, nowSec);
  const badge = confidenceBadge(row.score);
  const tone = badge === "Yüksek" ? "good" : badge === "Orta" ? "warn" : "wait";
  const mode = modeLabel(row.mode);
  const conf = row.llm_confidence;
  const hasHorizon = Number(row.horizon_minutes) > 0;
  const hasScore = row.score != null && Number.isFinite(Number(row.score));
  const statusNum = status.tone === "good" ? "good" : status.tone === "wait" ? "info" : "wait";
  return (
    <article className={`card p-4 ${status.kind === "ended" ? "opacity-80" : ""}`} aria-label={`${baseSymbol(row.symbol)} bildirimi`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {rank != null && <span className="u-chip u-chip-wait" aria-label={`Sıra ${rank}`}>{rank}</span>}
          {hasHorizon && <span className="u-chip u-chip-info">{Math.round(Number(row.horizon_minutes))} DK</span>}
          <StarButton symbol={row.symbol} fav={actions.isFavorite(row.symbol)} onClick={() => actions.onToggleFavorite(row.symbol, live ?? row.price)} />
        </div>
        {row.target_pct != null && (
          <span className="u-chip u-chip-good text-neon-green" title="Hedef potansiyel">Hedef potansiyel {pctText(row.target_pct)}</span>
        )}
      </div>

      <div className="mt-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-lg">
            <Link href={chartHref(row.symbol)} className="font-bold hover:underline">{baseSymbol(row.symbol)}</Link>
            <span className="text-bunker-muted"> / TRY</span>
          </p>
          <p className="text-sm">{tl(row.price)}</p>
          <p className="text-xs text-bunker-muted">{when(row.detected_at)}</p>
        </div>
        {hasScore && (
          <div className={`u-chip u-chip-${tone} shrink-0 flex-col items-center gap-0 rounded-xl px-3 py-1`} title={`Güven: ${badge}`}>
            <span className="text-xl font-bold leading-none">{Math.round(Number(row.score))}</span>
            <span className="text-[10px] font-semibold">BİRLEŞİK SKOR</span>
          </div>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div><dt className="text-xs text-bunker-muted">HEDEF</dt><dd className="font-semibold text-neon-green">{pctText(row.target_pct)}</dd></div>
        <div><dt className="text-xs text-bunker-muted">OLASILIK</dt><dd className="font-semibold">{conf != null && Number.isFinite(Number(conf)) ? `%${Math.round(Number(conf))}` : "—"}</dd></div>
        <div>
          <dt className="text-xs text-bunker-muted">CANLI</dt>
          <dd className="font-semibold">{tl(live)}</dd>
          <dd className="text-xs"><PctChange base={row.price} live={live} /></dd>
        </div>
      </dl>

      {mode && <p className="mt-2"><span className="u-chip u-chip-info">{mode}</span></p>}

      <p className={`mt-2 flex items-center gap-2 text-sm font-medium u-num-${statusNum}`}>
        {status.kind === "active" && <span aria-hidden="true" className="inline-block h-2 w-2 animate-pulse rounded-full bg-current" />}
        <span aria-hidden="true">{status.icon}</span>
        <span>{status.label}</span>
      </p>

      {pinned && <div className="mt-2"><PinBadge item={pinned} live={live} /></div>}

      <ActionRows symbol={row.symbol} price={row.price} live={live} actions={actions} />
    </article>
  );
}

/** İzlemeye alınmış ama son 10 bildirimde olmayan sembol için kompakt kart. */
export function PinnedCompactCard({ item, live, actions }: { item: WatchItem; live: number | null; actions: CardActions }) {
  return (
    <article className="card p-4" aria-label={`${baseSymbol(item.symbol)} izlemede`}>
      <div className="flex items-center justify-between gap-2">
        <p className="truncate font-mono text-lg">
          <Link href={chartHref(item.symbol)} className="font-bold hover:underline">{baseSymbol(item.symbol)}</Link>
          <span className="text-bunker-muted"> / TRY</span>
        </p>
        <StarButton symbol={item.symbol} fav={actions.isFavorite(item.symbol)} onClick={() => actions.onToggleFavorite(item.symbol, live ?? item.price)} />
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
        <div><dt className="text-xs text-bunker-muted">İZLEMEYE ALINDI</dt><dd className="font-semibold">{tl(item.price)}</dd></div>
        <div><dt className="text-xs text-bunker-muted">CANLI</dt><dd className="font-semibold">{tl(live)}</dd></div>
      </dl>
      <div className="mt-2"><PinBadge item={item} live={live} /></div>
      <ActionRows symbol={item.symbol} price={item.price} live={live} actions={actions} />
    </article>
  );
}
