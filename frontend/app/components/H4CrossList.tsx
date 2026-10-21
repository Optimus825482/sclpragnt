"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { call } from "../lib/tradeApi";
import { fmtDateTime, formatPrice } from "../lib/format";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { useWatchPrices } from "../lib/useWatchPrices";
import {
  changeSinceSignal, fmtDuration, fmtVolumeTry, h4StatusChip, parseH4Crosses, ruleLabel,
  type H4CrossItem, type H4CrossResponse,
} from "../lib/maBuyUi";
import SymbolLink from "./SymbolLink";
import BuyDialog from "./user/home/BuyDialog";

const nowSeconds = () => Math.floor(Date.now() / 1000);
const REFRESH_POLL_MS = 5_000;      // tarama sürerken kısa aralıkla sor
const PERIODIC_MS = 60_000;

function relative(ms: number, nowSec: number): string {
  const min = Math.max(0, Math.round((nowSec * 1000 - ms) / 60_000));
  if (min < 1) return "az önce";
  if (min < 60) return `${min} dk önce`;
  const hr = Math.floor(min / 60);
  return hr < 24 ? `${hr} sa önce` : `${Math.floor(hr / 24)} gün önce`;
}

const pct = (v: number | null, digits = 2) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits).replace(".", ",")}%`;
const pctClass = (v: number | null) => (v == null ? "text-bunker-muted" : v >= 0 ? "text-neon-green" : "text-neon-red");
const chipClass: Record<"good" | "info" | "muted", string> = {
  good: "border-neon-green/40 bg-neon-green/10 text-neon-green",
  info: "border-sky-400/40 bg-sky-400/10 text-sky-300",
  muted: "border-bunker-700 bg-bunker-950 text-bunker-muted",
};

function CrossRow({ it, live, nowSec, onBuy }: { it: H4CrossItem; live: number | undefined; nowSec: number; onBuy: () => void }) {
  // Şu an: canlı fiyat varsa ondan; yoksa tarama anındaki 5 dk kapanışından (now_pct).
  const change = changeSinceSignal(it.signalPrice, live ?? null) ?? it.nowPct;
  const chip = h4StatusChip(it);
  const peakTitle = it.maxRiseAtMs != null ? `Zirve: ${fmtDateTime(it.maxRiseAtMs)}` : undefined;
  const rules = it.rules.map(ruleLabel).filter(Boolean).join(" · ") || "MA kesişimi";
  const holdDays = it.maxHoldMinutes != null ? Math.round((it.maxHoldMinutes / 1440) * 10) / 10 : null;
  return (
    <li className="card rounded-2xl border border-bunker-800 p-3" data-testid="h4-cross-row">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <SymbolLink symbol={it.symbol} timeframe="4h" className="font-bold text-base text-white hover:underline" />
            <span className="rounded-md border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-amber-300">H4</span>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${chipClass[chip.tone]}`}>{chip.text}</span>
          </div>
          <p className="mt-0.5 text-sm text-bunker-muted">{rules}</p>
          <p className="mt-0.5 text-xs text-bunker-muted" title={fmtDateTime(it.barCloseMs)}>
            Mum kapanışı {fmtDateTime(it.barCloseMs)} · {relative(it.barCloseMs, nowSec)}
          </p>
        </div>
        <div className="text-right text-xs text-bunker-muted">
          <div>24 sa <b className={pctClass(it.change24hPct)}>{pct(it.change24hPct, 1)}</b></div>
          <div>Hacim <b className="text-white">{fmtVolumeTry(it.quoteVolume24h)}</b></div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-bunker-800 pt-2 text-sm">
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-bunker-muted">Sinyal <b className="text-white">{it.signalPrice != null ? formatPrice(it.signalPrice) : "—"}</b></span>
          <span className="text-bunker-muted">Şu an <b className={pctClass(change)}>{pct(change)}</b></span>
          <span className="text-bunker-muted" title={peakTitle} data-testid="h4-peak">
            En yüksek <b className={pctClass(it.maxRisePct)}>{pct(it.maxRisePct)}</b>
            {it.maxRisePrice != null && <> ({formatPrice(it.maxRisePrice)})</>}
            {it.minutesToMax != null && <> · <b className="text-white">{fmtDuration(it.minutesToMax)}</b> sonra</>}
            {it.maxRisePct == null && it.barsAfter === 0 && <span className="text-xs"> (mum henüz kapanmadı)</span>}
          </span>
          {it.maxDropPct != null && (
            <span className="text-bunker-muted">En düşük <b className={pctClass(it.maxDropPct)}>{pct(it.maxDropPct)}</b></span>
          )}
          {it.targetPct != null && (
            <span className="text-bunker-muted">
              Hedef <b className="text-neon-green">+%{it.targetPct.toFixed(0)}</b>
              {it.stopLossPct != null && <> · Stop <b className="text-neon-red">−%{it.stopLossPct.toFixed(0)}</b></>}
              {holdDays != null && <> · en çok {holdDays} gün</>}
            </span>
          )}
        </span>
        <span className="flex gap-2">
          <Link href={`/charts?symbol=${encodeURIComponent(it.symbol)}&timeframe=4h`} className="ui-button ui-button-secondary min-h-[36px] px-3 text-xs">
            Grafik
          </Link>
          <button type="button" onClick={onBuy} className="ui-button min-h-[36px] px-3 text-xs">Alım yap</button>
        </span>
      </div>
    </li>
  );
}

/**
 * Radar > "H4 kesişimleri": son 24 saatte H4'te MA 7/20/99 kesişimi olan likit TRY çiftleri (GET /api/ma-buy/h4-crosses).
 * Sunucu önbellekten döner; tarama sürerken (`refreshing`) 5 sn'de bir, sonra dakikada bir yeniden sorulur.
 * İzleyici yalnız AKTİF sembolleri bildirir; her satırdaki rozet bu kesişimin bildirilip bildirilmediğini gösterir.
 */
export default function H4CrossList({ hours = 24 }: { hours?: number }) {
  const [data, setData] = useState<H4CrossResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [buy, setBuy] = useState<{ symbol: string; price: number | null } | null>(null);
  const [nowSec, setNowSec] = useState(nowSeconds);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async (refresh = false) => {
    const r = await call<unknown>("GET", `/api/ma-buy/h4-crosses?hours=${hours}${refresh ? "&refresh=1" : ""}`);
    if (!r.ok) { setFailed(true); return; }
    setFailed(false);
    setData(parseH4Crosses(r.body));
  }, [hours]);

  useEffect(() => { void load(); }, [load]);
  useVisibleInterval(() => void load(), PERIODIC_MS);
  useVisibleInterval(() => setNowSec(nowSeconds()), 30_000);
  useEffect(() => {
    // Tarama arka planda sürüyorsa kısa aralıkla sor; bitince periyodik döngüye bırak.
    if (pollRef.current != null) { window.clearTimeout(pollRef.current); pollRef.current = null; }
    if (data?.refreshing) {
      pollRef.current = window.setTimeout(() => { pollRef.current = null; void load(); }, REFRESH_POLL_MS);
    }
    return () => { if (pollRef.current != null) window.clearTimeout(pollRef.current); };
  }, [data?.refreshing, data?.scannedAt, load]);

  const items = data?.items ?? [];
  const symbols = useMemo(() => [...new Set(items.map((i) => i.symbol))], [items]);
  const prices = useWatchPrices(symbols);

  const meta = data && data.scannedAt
    ? `${data.symbolsScanned} sembol tarandı · ${fmtDateTime(data.scannedAt * 1000)}${data.errors ? ` · ${data.errors} hata` : ""}`
    : null;

  return (
    <section aria-label="H4 kesişimleri" data-testid="h4-cross-list">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">H4 kesişimleri</h2>
          <p className="text-xs text-bunker-muted">
            {data?.maLabel ?? "SMA 7/20/99"} · son {hours} saat · 24 sa hacmi yüksek tüm TRY çiftleri
            {meta ? ` · ${meta}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={data?.refreshing === true}
          className="ui-button ui-button-secondary min-h-[36px] px-3 text-xs disabled:opacity-60"
        >
          {data?.refreshing ? "Taranıyor…" : "Yenile"}
        </button>
      </div>
      {data?.lastError && (
        <p role="alert" className="mb-2 rounded-lg bg-neon-red/10 p-3 text-xs text-neon-red">Son tarama hata verdi: {data.lastError}</p>
      )}
      {failed ? (
        <div role="alert" className="card p-4 text-sm text-neon-red">H4 kesişimleri yüklenemedi. Birazdan yeniden denenecek.</div>
      ) : data == null ? (
        <div className="card p-4 text-sm text-bunker-muted" aria-live="polite">Yükleniyor…</div>
      ) : items.length === 0 ? (
        <div className="card p-4 text-sm text-bunker-muted" aria-live="polite">
          {data.refreshing && !data.scannedAt
            ? "Piyasa taranıyor, ilk sonuç bir dakika içinde gelir…"
            : `Son ${hours} saatte H4'te kesişim yok.`}
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((it) => (
            <CrossRow
              key={`${it.symbol}-${it.barOpenMs}`} it={it} nowSec={nowSec}
              live={prices[it.symbol.toUpperCase()] ?? prices[it.symbol]}
              onBuy={() => setBuy({ symbol: it.symbol, price: prices[it.symbol.toUpperCase()] ?? it.signalPrice })}
            />
          ))}
        </ul>
      )}
      {buy && <BuyDialog open symbol={buy.symbol} referencePrice={buy.price} onClose={() => setBuy(null)} />}
    </section>
  );
}
