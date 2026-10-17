"use client";

/**
 * Üst menü altındaki portföy bandının veri katmanı.
 *
 * KAYNAK KURALI (backend `GET /api/portfolio/band` uygular): kullanıcının Binance
 * TR key+secret'ı kayıtlıysa GERÇEK Binance değerleri, değilse PAPER değerleri.
 * Tek istek yeter (key durumu + hesap + pozisyon + günlük K/Z sunucuda birleşir).
 *
 * Tazeleme:
 *  - REST: 15 sn'de bir; sekme gizliyken durur, öne gelince hemen çalışır
 *    (`useVisibleInterval`).
 *  - WS (`subscribeLive`): paper kaynakta `portfolio` mesajı bantı ANINDA
 *    günceller (saniyelik polling yok); `binance_account_update`,
 *    `auto_paper_trade`, `trade_updated`, `reset` kısa bir debounce ile REST
 *    tazelemesi tetikler (günlük K/Z ve gerçek bakiye değişimi için).
 *
 * K/Z matematiği `lib/pnl.ts` yardımcılarındadır (Portföy sayfasıyla aynı
 * net, gidiş-dönüş komisyonlu kural) — burada formül kopyalanmaz.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "./api";
import { useLiveMessages } from "./liveSocket";
import { useVisibleInterval } from "./useVisibleInterval";
import { applyCommissionPct, netOpenPnlTry } from "./pnl";

export type BandSource = "binance" | "paper";

/** Backend `/api/portfolio/band` yanıtı (alanlar eksik/null olabilir). */
export interface BandResponse {
  source?: string;
  total_try?: number | null;
  free_try?: number | null;
  open_count?: number | null;
  unrealized_try?: number | null;
  unrealized_pct?: number | null;
  daily_pnl_try?: number | null;
  updated_at?: number | null;
  commission_pct?: number | null;
  positions?: BandPositionInput[] | null;
  /** Yalnız Binance: canlı fiyat tikiyle yeniden hesap için varlık başına taban değerler. */
  holdings?: BandHolding[] | null;
}

/** Binance varlığı (REST anındaki taban): fiyat · adet · ortalama maliyet. */
export interface BandHolding {
  asset: string;
  symbol?: string | null;
  qty: number;
  price_try: number;
  avg_cost_try?: number | null;
  /** Toz eşiği üstünde mi (açık işlem / K/Z'ye girer). Toz yalnız toplam değere girer. */
  counted?: boolean;
}

/** WS `binance_price` yükü: varlık (ve sembol) → canlı TL fiyatı. */
export type BinanceTicks = Record<string, { price?: number | null } | null | undefined>;

export interface BandPositionInput {
  symbol?: string | null;
  side?: string | null;
  entry?: number | string | null;
  current?: number | string | null;
  quantity?: number | string | null;
}

/** WS `portfolio` mesajı (ana + otonom paper). */
export interface PortfolioSnapshot {
  try?: number | null;
  total_value?: number | null;
  commission_pct?: number | null;
  positions?: BandPositionInput[] | null;
  auto_paper_positions?: BandPositionInput[] | null;
}

/** Bandın göstereceği normalize veri. `null` = "veri yok" (0 DEĞİL). */
export interface PortfolioBandData {
  source: BandSource;
  totalTry: number | null;
  freeTry: number | null;
  openCount: number | null;
  unrealizedTry: number | null;
  unrealizedPct: number | null;
  dailyPnlTry: number | null;
  updatedAt: number | null;
  /** Yalnız paper: WS ile canlı yeniden hesap için son bilinen komisyon oranı. */
  positions: BandPositionInput[] | null;
  /** Yalnız Binance: REST tabanı (canlı tik her seferinde BU tabandan yeniden hesaplanır; birikim yok). */
  holdings?: BandHolding[] | null;
  /** Yalnız Binance: REST anındaki toplam değer (tik farkları bunun üstüne eklenir). */
  baseTotalTry?: number | null;
  /** Son canlı fiyat güncellemesi (ms); yoksa yalnız REST. */
  liveAt?: number | null;
}

function finite(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Açık pozisyon listesinden net K/Z (₺) ve % (maliyet tabanı giriş değeri).
 * Pozisyon yoksa K/Z meşru olarak 0; pozisyon var ama hiçbiri ölçülemiyorsa
 * `null` (0 "başabaş" izlenimi verirdi). Ölçülemeyen satırlar toplama girmez.
 */
export function aggregateOpenPositions(
  positions: readonly BandPositionInput[] | null | undefined,
): { count: number; pnlTry: number | null; pnlPct: number | null } {
  const list = positions ?? [];
  if (list.length === 0) return { count: 0, pnlTry: 0, pnlPct: 0 };
  let pnl = 0;
  let cost = 0;
  let measured = 0;
  for (const p of list) {
    const net = netOpenPnlTry(p.entry, p.current, p.quantity, p.side);
    if (net === null) continue;
    pnl += net;
    cost += Number(p.entry) * Number(p.quantity);
    measured += 1;
  }
  if (measured === 0) return { count: list.length, pnlTry: null, pnlPct: null };
  return { count: list.length, pnlTry: pnl, pnlPct: cost > 0 ? (pnl / cost) * 100 : null };
}

/** Backend yanıtını bant verisine çevirir. Paper'da ham pozisyonlardan K/Z yeniden hesaplanır. */
export function normalizeBand(raw: BandResponse | null | undefined): PortfolioBandData | null {
  if (!raw || typeof raw !== "object") return null;
  const source: BandSource = raw.source === "binance" ? "binance" : "paper";
  const base = {
    source,
    totalTry: finite(raw.total_try),
    freeTry: finite(raw.free_try),
    dailyPnlTry: finite(raw.daily_pnl_try),
    updatedAt: finite(raw.updated_at),
  };
  if (source === "paper" && Array.isArray(raw.positions)) {
    const agg = aggregateOpenPositions(raw.positions);
    return { ...base, openCount: agg.count, unrealizedTry: agg.pnlTry, unrealizedPct: agg.pnlPct, positions: raw.positions };
  }
  const holdings = Array.isArray(raw.holdings)
    ? raw.holdings.filter((h) => h && finite(h.qty) && finite(h.price_try))
    : null;
  return {
    ...base,
    openCount: finite(raw.open_count),
    unrealizedTry: finite(raw.unrealized_try),
    unrealizedPct: finite(raw.unrealized_pct),
    positions: null,
    holdings,
    baseTotalTry: base.totalTry,
    liveAt: null,
  };
}

/**
 * 2026-10-17: Binance bandını WS `binance_price` tikleriyle (2 sn) canlı günceller.
 * Kural backend ile aynı (`main.binance_positions`): varlık K/Z = (fiyat − ortalama maliyet) × adet,
 * toplam değer = REST toplamı + Σ (canlı fiyat − REST fiyatı) × adet. Her tikte REST TABANINDAN yeniden
 * hesaplanır (birikimli hata yok). Tik gelmeyen varlık REST fiyatıyla kalır. Günlük K/Z (gerçekleşen)
 * ve açık işlem sayısı REST'ten gelir, değişmez. Paper bantta / taban yokken `null` (değişiklik yok).
 */
export function applyBinanceTicks(
  prev: PortfolioBandData | null,
  ticks: BinanceTicks | null | undefined,
  now: number = Date.now(),
): PortfolioBandData | null {
  if (!prev || prev.source !== "binance" || !ticks || typeof ticks !== "object") return null;
  const holdings = prev.holdings;
  if (!holdings || holdings.length === 0) return null;
  const baseTotal = prev.baseTotalTry ?? null;
  let totalDelta = 0;
  let pnl = 0;
  let cost = 0;
  let measured = 0;
  let unmeasured = 0;
  let touched = false;
  for (const h of holdings) {
    const qty = Number(h.qty);
    const basePrice = Number(h.price_try);
    const tick = ticks[String(h.asset).toUpperCase()] ?? (h.symbol ? ticks[String(h.symbol).toUpperCase()] : undefined);
    const livePrice = finite(tick?.price);
    const price = livePrice != null && livePrice > 0 ? livePrice : basePrice;
    if (livePrice != null && livePrice > 0 && livePrice !== basePrice) touched = true;
    totalDelta += (price - basePrice) * qty;
    if (!h.counted) continue;
    const avg = finite(h.avg_cost_try);
    if (avg == null || avg <= 0) {
      unmeasured += 1;
      continue;
    }
    pnl += (price - avg) * qty;
    cost += avg * qty;
    measured += 1;
  }
  if (!touched) return null;
  const counted = measured + unmeasured;
  return {
    ...prev,
    totalTry: baseTotal != null ? baseTotal + totalDelta : prev.totalTry,
    unrealizedTry: counted === 0 ? 0 : measured === 0 ? null : pnl,
    unrealizedPct: counted === 0 ? 0 : measured === 0 || cost <= 0 ? null : (pnl / cost) * 100,
    liveAt: now,
  };
}

/**
 * WS `portfolio` anlık görüntüsünü mevcut PAPER bant verisine uygular:
 * toplam/serbest/pozisyon/K-Z canlı yenilenir, günlük K/Z korunur (REST'ten gelir).
 * Binance kaynaklı bantta anlık görüntü yok sayılır (null döner → değişiklik yok).
 */
export function applyPaperSnapshot(
  prev: PortfolioBandData | null,
  snapshot: PortfolioSnapshot | null | undefined,
): PortfolioBandData | null {
  if (!prev || prev.source !== "paper" || !snapshot || typeof snapshot !== "object") return null;
  const positions = [
    ...(Array.isArray(snapshot.positions) ? snapshot.positions : []),
    ...(Array.isArray(snapshot.auto_paper_positions) ? snapshot.auto_paper_positions : []),
  ];
  const agg = aggregateOpenPositions(positions);
  return {
    ...prev,
    totalTry: finite(snapshot.total_value) ?? prev.totalTry,
    freeTry: finite(snapshot.try) ?? prev.freeTry,
    openCount: agg.count,
    unrealizedTry: agg.pnlTry,
    unrealizedPct: agg.pnlPct,
    positions,
  };
}

export type BandStatus = "loading" | "ok" | "error";

export interface PortfolioSummaryState {
  data: PortfolioBandData | null;
  status: BandStatus;
  /** Son yenileme başarısız ama eski veri hâlâ gösteriliyor. */
  stale: boolean;
}

const POLL_MS = 15_000;
const WS_REFETCH_DEBOUNCE_MS = 1_000;
// WS `portfolio` mesajı ~saniyede bir gelir; ekran okuyucu (aria-live) ve render
// gürültüsünü azaltmak için bant görünümü en fazla bu aralıkla güncellenir.
const WS_RENDER_MIN_MS = 2_000;

export function usePortfolioSummary(): PortfolioSummaryState {
  const [data, setData] = useState<PortfolioBandData | null>(null);
  const [status, setStatus] = useState<BandStatus>("loading");
  const [stale, setStale] = useState(false);
  const seqRef = useRef(0);
  const mountedRef = useRef(true);
  const dataRef = useRef<PortfolioBandData | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastWsRenderRef = useRef(0);

  const load = useCallback(() => {
    const seq = ++seqRef.current;
    apiRequest(`${API_BASE}/api/portfolio/band`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((raw: BandResponse) => {
        if (!mountedRef.current || seq !== seqRef.current) return;
        const next = normalizeBand(raw);
        if (!next) throw new Error("boş yanıt");
        applyCommissionPct(raw.commission_pct);
        dataRef.current = next;
        setData(next);
        setStatus("ok");
        setStale(false);
      })
      .catch(() => {
        if (!mountedRef.current || seq !== seqRef.current) return;
        if (dataRef.current) setStale(true);
        else setStatus("error");
      });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => {
      mountedRef.current = false;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = null;
    };
  }, [load]);

  useVisibleInterval(load, POLL_MS);

  const onLive = useCallback((message: { type: string; data?: unknown }) => {
    if (typeof document !== "undefined" && document.hidden) return;
    // 2026-10-17: Binance kaynağında canlı fiyat tiki (2 sn) toplam değer + anlık K/Z'yi günceller;
    // REST tazelemesi TETİKLEMEZ (tik sık gelir).
    if (message.type === "binance_price") {
      const ticks = (message.data as { ticks?: BinanceTicks } | undefined)?.ticks;
      const next = applyBinanceTicks(dataRef.current, ticks);
      if (next) {
        dataRef.current = next;
        const now = Date.now();
        if (now - lastWsRenderRef.current >= WS_RENDER_MIN_MS) {
          lastWsRenderRef.current = now;
          setData(next);
        }
      }
      return;
    }
    if (message.type === "portfolio") {
      const next = applyPaperSnapshot(dataRef.current, message.data as PortfolioSnapshot);
      if (next) {
        applyCommissionPct((message.data as PortfolioSnapshot)?.commission_pct);
        dataRef.current = next;
        const now = Date.now();
        if (now - lastWsRenderRef.current >= WS_RENDER_MIN_MS) {
          lastWsRenderRef.current = now;
          setData(next);
        }
      }
      return;
    }
    // Hesap/işlem olayları: günlük K/Z ve gerçek bakiye için REST'i hafifçe tazele.
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      load();
    }, WS_REFETCH_DEBOUNCE_MS);
  }, [load]);
  useLiveMessages(onLive, ["portfolio", "binance_price", "binance_account_update", "auto_paper_trade", "trade_updated", "reset"]);

  return { data, status, stale };
}
