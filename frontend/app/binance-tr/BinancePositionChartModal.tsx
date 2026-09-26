"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  UTCTimestamp,
  LineStyle,
} from "lightweight-charts";
import { API_BASE, apiRequest } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import { commissionPct } from "../lib/pnl";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import IndicatorPicker, {
  findIndicatorEntry,
  CUSTOM_INDICATOR_ENTRIES,
  SUPERTREND_ENTRY,
} from "../charts/IndicatorPicker";
import IndicatorSettings from "../charts/IndicatorSettings";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "../charts/types";

export type Holding = {
  asset: string;
  free: number;
  locked: number;
  total: number;
  price_try: number | null;
  value_try: number | null;
  avg_cost_try?: number | null;
  pnl_try?: number | null;
  pnl_pct?: number | null;
  volume_try?: number | null;
  has_active_order?: boolean;
  active_sl_price?: number | null;
  active_tp_price?: number | null;
  active_orders?: any[];
};

interface Props {
  holding: Holding;
  onClose: () => void;
  onOrderUpdated: () => void;
  sellEnabled: boolean;
  showToast: (msg: string, type?: "success" | "error" | "info") => void;
  livePrice?: number | null;
}

type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d";

// Timeframe'den saniye cinsinden periyot
const TF_SECONDS: Record<Timeframe, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

// Lightweight Charts için mum tipi
type CandleBar = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
};

// Basit Bollinger Bantları Hesabı (Periyot: 20, StdDev: 2)
function calculateBollingerBands(
  candles: CandleBar[],
  period = 20,
  stdDevMultiplier = 2
) {
  const upper: { time: UTCTimestamp; value: number }[] = [];
  const middle: { time: UTCTimestamp; value: number }[] = [];
  const lower: { time: UTCTimestamp; value: number }[] = [];

  if (candles.length < period) return { upper, middle, lower };

  for (let i = period - 1; i < candles.length; i++) {
    const slice = candles.slice(i - period + 1, i + 1);
    const sum = slice.reduce((acc, c) => acc + c.close, 0);
    const mean = sum / period;

    const variance =
      slice.reduce((acc, c) => acc + Math.pow(c.close - mean, 2), 0) / period;
    const stdDev = Math.sqrt(variance);

    const time = candles[i].time;
    middle.push({ time, value: mean });
    upper.push({ time, value: mean + stdDevMultiplier * stdDev });
    lower.push({ time, value: mean - stdDevMultiplier * stdDev });
  }

  return { upper, middle, lower };
}

function fmtPrice(v?: number | null, decimals = 4): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  if (v < 0.0001) return v.toFixed(6);
  if (v < 1) return v.toFixed(4);
  if (v < 100) return v.toFixed(decimals > 2 ? 3 : 2);
  return v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Grafik fiyat cetveli hassasiyeti — SEMBOL FİYATINA GÖRE (kullanıcı tercihi
// 2026-09-19): tek bir 2-basamak cetvel, 0.05 gibi kuruş-altı sembolleri
// yanlış gösteriyordu (tüm mumlar aynı fiyat gibi). Binance tick mantığına
// yakın fiyat aralığı basamakları: <0.01→6, <0.1→5, <1→4, <10→3, <100→3,
// <1000→2, ≥1000→2 (uzun çift haneleri binlik ayraç taşır).
function priceScalePrecision(price: number | null | undefined): number {
  const p = Number(price ?? 0);
  if (!Number.isFinite(p) || p <= 0) return 2;
  if (p < 0.01) return 6;
  if (p < 0.1) return 5;
  if (p < 1) return 4;
  if (p < 1000) return 3;
  return 2;
}

// Kalan süreyi MM:SS formatına çevir
function fmtCountdown(seconds: number): string {
  if (seconds <= 0) return "00:00";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}s ${String(m).padStart(2, "0")}d ${String(s).padStart(2, "0")}s`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// Eklenen indikatörleri lightweight-charts serileri olarak yönet
type IndicatorSeriesMap = Map<string, ISeriesApi<"Line">[]>;

export default function BinancePositionChartModal({
  holding,
  onClose,
  onOrderUpdated,
  sellEnabled,
  showToast,
  livePrice,
}: Props) {
  const symbolConcat = `${holding.asset}TRY`;
  const [timeframe, setTimeframe] = useState<Timeframe>("5m"); // Varsayılan M5
  const [loading, setLoading] = useState(true);
  // TF YARIŞI DÜZELTMESİ (2026-09-19): WS callback'leri stale closure'da eski
  // timeframe görebildiği için fresh ref'ler tutulur.
  const timeframeRef = useRef<Timeframe>("5m");
  const loadingRef = useRef(true);
  useEffect(() => { timeframeRef.current = timeframe; }, [timeframe]);
  useEffect(() => { loadingRef.current = loading; }, [loading]);
  const [showBB, setShowBB] = useState(true); // Varsayılan Bollinger Bands AÇIK
  const [showSupertrend, setShowSupertrend] = useState(false); // Varsayılan KAPALI (kullanıcı tercihi 2026-09-19)
  const [supertrendTrend, setSupertrendTrend] = useState<"UP" | "DOWN" | null>(null);
  const [candles, setCandles] = useState<CandleBar[]>([]);

  // Canlı Tahta (Orderbook) Metrikleri
  const [orderbook, setOrderbook] = useState<{
    bidTotal: number;
    askTotal: number;
    bidPct: number;
    askPct: number;
    spread: number;
    spreadPct: number;
    bestBid: number | null;
    bestAsk: number | null;
  } | null>(null);
  // Tahta verisinin yaşı (ms). Backend `bookTicker`/`depth` WS mesajı
  // YAYINLAMIYOR (denetim #53) → panel yalnız REST ile besleniyor. Kullanıcı
  // "TAHTA" yazısını görüp canlı sandığında yanıltılmamalı: 5 sn'den eski
  // veri "canlı değil" rozetiyle işaretlenir.
  const [orderbookUpdatedAt, setOrderbookUpdatedAt] = useState(0);
  const [nowTick, setNowTick] = useState(0);

  // Tahta verisi 8 sn'den eskiyse "canlı değil" rozeti gösterilir.
  const ORDERBOOK_STALE_MS = 8_000;
  const orderbookStale = orderbookUpdatedAt > 0 && nowTick > orderbookUpdatedAt
    ? (nowTick - orderbookUpdatedAt) > ORDERBOOK_STALE_MS
    : orderbookUpdatedAt === 0;

  // Son Mum Takip Referansı (Anlık iğne / canlı tik güncellemeleri için)
  const lastCandleRef = useRef<CandleBar | null>(null);

  // Mum Kapanışına Kalan Süre
  const [countdown, setCountdown] = useState<number>(0);
  const lastCandleTimeRef = useRef<number>(0);

  // Canlı Fiyat & Tick Durumu
  const [currentPrice, setCurrentPrice] = useState<number | null>(livePrice ?? holding.price_try);
  const [tickDir, setTickDir] = useState<"up" | "down" | null>(null);

  // Canlı Fiyat Tik Güncellemesi: hem WebSocket hem prop'tan beslenir
  const applyPriceTick = useCallback((newPrice: number) => {
    if (!newPrice || !Number.isFinite(newPrice) || newPrice <= 0) return;
    setCurrentPrice((prev) => {
      if (prev != null && prev > 0 && Math.abs(newPrice - prev) > 1e-9) {
        setTickDir(newPrice >= prev ? "up" : "down");
      }
      return newPrice;
    });

    if (!loadingRef.current && candleSeriesRef.current) {
      const tfSecs = TF_SECONDS[timeframeRef.current] || 0;
      const nowSec = Math.floor(Date.now() / 1000);
      const last = lastCandleRef.current;
      if (tfSecs > 0) {
        const bucket = Math.floor(nowSec / tfSecs) * tfSecs;
        if (last && Number(last.time) === bucket) {
          const updatedBar: CandleBar = {
            time: last.time,
            open: last.open,
            high: Math.max(last.high, newPrice),
            low: Math.min(last.low, newPrice),
            close: newPrice,
          };
          lastCandleRef.current = updatedBar;
          try { candleSeriesRef.current.update(updatedBar as any); } catch {}
        } else if (!last || bucket > Number(last.time)) {
          const freshBar: CandleBar = {
            time: bucket as UTCTimestamp,
            open: last ? last.close : newPrice,
            high: newPrice,
            low: newPrice,
            close: newPrice,
          };
          lastCandleRef.current = freshBar;
          try { candleSeriesRef.current.update(freshBar as any); } catch {}
        }
      }
    }
  }, []);

  useEffect(() => {
    if (livePrice != null && Number(livePrice) > 0) {
      applyPriceTick(Number(livePrice));
    }
  }, [livePrice, applyPriceTick]);

  // Pozisyon Çizgi Değerleri
  const entryPrice = holding.avg_cost_try && holding.avg_cost_try > 0 ? holding.avg_cost_try : null;
  const [tpPrice, setTpPrice] = useState<number | null>(holding.active_tp_price || null);
  const [slPrice, setSlPrice] = useState<number | null>(holding.active_sl_price || null);
  // Ref mirror'lar — drag mouseUp closure stale değerleri okumas›n diye
  const tpPriceRef = useRef<number | null>(holding.active_tp_price || null);
  const slPriceRef = useRef<number | null>(holding.active_sl_price || null);
  // State değişimlerini ref'e yansıt (harici güncelleme için)
  useEffect(() => { tpPriceRef.current = tpPrice; }, [tpPrice]);
  useEffect(() => { slPriceRef.current = slPrice; }, [slPrice]);
  // State + ref'i aynı anda güncelleyen wrapper'lar
  const commitTpPrice = useCallback((v: number | null) => { tpPriceRef.current = v; setTpPrice(v); }, []);
  const commitSlPrice = useCallback((v: number | null) => { slPriceRef.current = v; setSlPrice(v); }, []);

  // Değişiklik/Onay Durumu (Drag & Drop sonrasında bekleyen değişiklikler)
  const [pendingTp, setPendingTp] = useState<number | null>(null);
  const [pendingSl, setPendingSl] = useState<number | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  // Sürükleme (Drag) Durumu
  const [draggingTarget, setDraggingTarget] = useState<"TP" | "SL" | null>(null);
  const [dragYPrice, setDragYPrice] = useState<number | null>(null);

  // Sağ Tık (Context Menu) Durumu
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    price: number;
  } | null>(null);

  // İndikatör paneli durumu
  const [showIndicatorPicker, setShowIndicatorPicker] = useState(false);
  const [pickerSelectedEntry, setPickerSelectedEntry] = useState<RegistryEntry | null>(null);
  const [editingIndicator, setEditingIndicator] = useState<IndicatorInstance | null>(null);
  const [indicators, setIndicators] = useState<IndicatorInstance[]>([]);

  // POZİYON KAPAT (GİRİŞ çizgisindeki ✕ → onay modalı) — kullanıcı tercihi 2026-09-19
  const [closeModalOpen, setCloseModalOpen] = useState(false);
  const [closeQtyInput, setCloseQtyInput] = useState("");
  const [closeUnit, setCloseUnit] = useState<"asset" | "try">("asset");
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeMsg, setCloseMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // DOM & Grafik Referansları
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const middleBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const supertrendSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Fiyat Çizgileri Referansları
  const entryLineRef = useRef<IPriceLine | null>(null);
  const tpLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);

  // İndikatör serisi map'i (uid -> seri listesi)
  const indicatorSeriesMapRef = useRef<IndicatorSeriesMap>(new Map());

  // Çizgilerin piksel koordinatları (Drag tutamaçları için)
  const [lineCoords, setLineCoords] = useState<{
    entry?: number | null;
    tp?: number | null;
    sl?: number | null;
  }>({});

  // 1. Mum Verisi Yükleme
  // silent=true: loading overlay YOK, fitContent YOK — arka plan tazelemesi
  // (anti-freeze watchdog ve TTL yenileme) zoom'u bozmasın diye.
  const loadKlines = useCallback(async (tf: Timeframe, opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true);
    try {
      const res = await apiRequest(
        `${API_BASE}/api/market-klines/${symbolConcat}?interval=${tf}&limit=250`
      );
      if (!res.ok) {
        console.warn(`Kline yüklenemedi: HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
      if (Array.isArray(data?.candles) && data.candles.length > 0) {
        const parsed: CandleBar[] = [];
        const seen = new Set<number>();
        for (const c of data.candles) {
          let timeSec = 0;
          let open = 0, high = 0, low = 0, close = 0;
          if (Array.isArray(c)) {
            const rawT = Number(c[0]);
            timeSec = rawT > 1e11 ? Math.floor(rawT / 1000) : Math.floor(rawT);
            open = Number(c[1]);
            high = Number(c[2]);
            low = Number(c[3]);
            close = Number(c[4]);
          } else if (c && typeof c === "object") {
            const rawT = Number(c.time ?? c.open_time ?? c.openTime ?? c.t ?? 0);
            timeSec = rawT > 1e11 ? Math.floor(rawT / 1000) : Math.floor(rawT);
            open = Number(c.open ?? c.o ?? 0);
            high = Number(c.high ?? c.h ?? 0);
            low = Number(c.low ?? c.l ?? 0);
            close = Number(c.close ?? c.c ?? 0);
          }
          if (Number.isFinite(timeSec) && timeSec > 0 && Number.isFinite(close) && close > 0) {
            if (!seen.has(timeSec)) {
              seen.add(timeSec);
              parsed.push({
                time: timeSec as UTCTimestamp,
                open: Number.isFinite(open) && open > 0 ? open : close,
                high: Number.isFinite(high) && high > 0 ? high : close,
                low: Number.isFinite(low) && low > 0 ? low : close,
                close,
              });
            }
          }
        }
        parsed.sort((a, b) => Number(a.time) - Number(b.time));

        if (parsed.length > 0) {
          const lastBar = parsed[parsed.length - 1];
          const newCandles = opts?.silent
            ? (prev: CandleBar[]) => {
                // Sessiz tazeleme: yalnız son mum değiştiyse state'i güncelle.
                // Tam setData yerine son-mum update'i zoom/kaydırma pozisyonunu
                // korur. İlk yükleme dışında tam setData çağrısı gerekmez.
                const old = prev[prev.length - 1];
                if (old && Number(old.time) === Number(lastBar.time) &&
                    old.open === lastBar.open && old.close === lastBar.close &&
                    old.high === lastBar.high && old.low === lastBar.low) {
                  return prev; // değişiklik yok — gereksiz render yok
                }
                if (old && Number(lastBar.time) >= Number(old.time)) {
                  // Kuyrukta değişiklik: son barı (ve varsa yeni barı) uygula.
                  try {
                    candleSeriesRef.current?.update(lastBar as any);
                  } catch { /* */ }
                  lastCandleRef.current = lastBar;
                  return [...prev.slice(0, -1), lastBar];
                }
                // Uzun boşluk (kapanmış mumlar eklendi): sessiz setData.
                try {
                  candleSeriesRef.current?.setData(parsed as any);
                } catch { /* */ }
                lastCandleRef.current = lastBar;
                return parsed;
              }
            : parsed;
          setCandles(newCandles as CandleBar[]);
          lastCandleRef.current = lastBar;
          lastCandleTimeRef.current = Number(lastBar.time);
          setCurrentPrice(lastBar.close);
          if (!opts?.silent) {
            setTimeout(() => {
              chartApiRef.current?.timeScale().fitContent();
            }, 60);
          }
        }
      }
    } catch (err) {
      console.error("Kline yüklenemedi:", err);
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, [symbolConcat]);

  // Canlı Derinlik (Orderbook) Verisi Takibi
  useEffect(() => {
    let active = true;
    const fetchDepth = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      try {
        let res = await fetch(`${API_BASE}/api/market-depth/${symbolConcat}?limit=20`);
        if (!res.ok) {
          res = await fetch(`https://api.binance.me/api/v3/depth?symbol=${symbolConcat}&limit=20`);
        }
        if (!res.ok) {
          res = await fetch(`https://api.binance.com/api/v3/depth?symbol=${symbolConcat}&limit=20`);
        }
        if (!res.ok || !active) return;
        const data = await res.json();
        if (data && Array.isArray(data.bids) && Array.isArray(data.asks) && data.bids.length > 0 && data.asks.length > 0) {
          const bidTotal = data.bids.reduce((sum: number, b: [string, string]) => sum + Number(b[0]) * Number(b[1]), 0);
          const askTotal = data.asks.reduce((sum: number, a: [string, string]) => sum + Number(a[0]) * Number(a[1]), 0);
          const sum = bidTotal + askTotal;
          const bidPct = sum > 0 ? (bidTotal / sum) * 100 : 50;
          const askPct = 100 - bidPct;
          const bestBid = Number(data.bids[0][0]);
          const bestAsk = Number(data.asks[0][0]);
          const spread = bestAsk > bestBid ? bestAsk - bestBid : 0;
          const spreadPct = bestBid > 0 ? (spread / bestBid) * 100 : 0;

          if (active) {
            setOrderbook({
              bidTotal,
              askTotal,
              bidPct,
              askPct,
              spread,
              spreadPct,
              bestBid,
              bestAsk,
            });
            setOrderbookUpdatedAt(Date.now());
          }
        }
      } catch {
        // Ağ kesintisinde sessiz kal (rozet "canlı değil" der)
      }
    };

    fetchDepth();
    // Backend `bookTicker`/`depth` WS mesajı YAYINLAMIYOR (denetim #53):
    // frontend dinliyordu ama veri hiç gelmediği için panel açılışta bir kez
    // REST çağrısı yapıp DONUYORDU. Bu yüzden REST periyodu 5 sn'e çekildi
    // (gereksiz 2,5 sn trafiği yerine anlamlı bir tazeleme aralığı) ve
    // sekme görünürlüğüne duyarlı `useVisibleInterval` kullanılıyor.
    const interval = setInterval(fetchDepth, 5000);
    const onVisible = () => { if (!document.hidden) fetchDepth(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [symbolConcat]);

  // "Canlı değil" rozeti için 2 sn'de bir yaş tazelemesi (yalnız modal açıkken).
  useVisibleInterval(() => setNowTick(Date.now()), 2000);

  useEffect(() => {
    // TF DEĞİŞİM TEMİZLİĞİ (2026-09-19): eski TF'in candles'ı ve lastCandleRef'i
    // anında temizlenir; aksi halde (1) 3a effect yeni veri gelene dek ESKİ
    // mumları çizmeye devam eder ve (2) canlı tik güncellemesi eski TF'in son
    // mumunu yeni seriye karıştırır (mumların "aynı yerde garip çizilmesi").
    setCandles([]);
    lastCandleRef.current = null;
    lastCandleTimeRef.current = 0;
    loadKlines(timeframe);
  }, [timeframe, loadKlines]);

  // ANTİ-FREEZE WATCHDOG (2026-09-19, İKİ katman):
  //   1) WS canlı akış TTL'i (backend VIEWED_TTL_SEC=90) canlı kalsın diye,
  //   2) WS herhangi bir sebeple sessiz kalırsa grafik yine de donmasın diye —
  // 10 sn'de bir sessiz tam-seri tazeleme (charts sayfasının kanıtlanmış modeli:
  // "HTTP birincil, WS anlık bonus"). Sessiz mod: loading overlay YOK,
  // fitContent YOK (zoom/kaydırma pozisyonu korunur), değişiklik yoksa seriye
  // dokunulmaz. Arka plan sekmesinde durur.
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return;
      void loadKlines(timeframeRef.current, { silent: true });
    }, 10_000);
    return () => clearInterval(timer);
  }, [loadKlines]);

  // Mum Kapanışına Kalan Süre Sayacı
  useEffect(() => {
    const tfSecs = TF_SECONDS[timeframe];
    const tick = () => {
      const nowSec = Math.floor(Date.now() / 1000);
      if (lastCandleTimeRef.current > 0) {
        const candleClose = lastCandleTimeRef.current + tfSecs;
        const remaining = Math.max(0, candleClose - nowSec);
        setCountdown(remaining);
      }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [timeframe, candles]);

  // 2. Grafik Kurulumu (lightweight-charts)
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || 520,
      layout: {
        background: { color: "#080b10" },
        textColor: "#9ca3af",
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: "rgba(31, 41, 55, 0.4)" },
        horzLines: { color: "rgba(31, 41, 55, 0.4)" },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "#00f3ff", width: 1, style: LineStyle.Dotted },
        horzLine: { color: "#00f3ff", width: 1, style: LineStyle.Dotted },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#1f2937",
      },
      rightPriceScale: {
        borderColor: "#1f2937",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
    });

    // Mum Serisi — fiyat cetveli hassasiyeti SEMBOL FİYATINA GÖRE
    // (kullanıcı tercihi 2026-09-19): 0.05'lik sembollerde 2 basamak
    // cetvel tüm mumları aynı fiyata sabitliyordu.
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
      priceFormat: {
        type: "price",
        precision: priceScalePrecision(holding.price_try),
        minMove: Math.pow(10, -priceScalePrecision(holding.price_try)),
      },
    });

    // Bollinger Bantları (Üst, Orta, Alt)
    const upperBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.75)",
      lineWidth: 1,
      title: "BB Üst",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const middleBb = chart.addSeries(LineSeries, {
      color: "rgba(250, 204, 21, 0.75)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: "BB Orta",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const lowerBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.75)",
      lineWidth: 1,
      title: "BB Alt",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Supertrend Serisi (10, 3)
    const supertrendSeries = chart.addSeries(LineSeries, {
      color: "#10b981",
      lineWidth: 2,
      title: "Supertrend (10,3)",
      priceLineVisible: false,
      lastValueVisible: true,
    });

    chartApiRef.current = chart;
    candleSeriesRef.current = candleSeries;
    upperBbRef.current = upperBb;
    middleBbRef.current = middleBb;
    lowerBbRef.current = lowerBb;
    supertrendSeriesRef.current = supertrendSeries;

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
        updateLineCoordinates();
      }
    });
    ro.observe(chartContainerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
      supertrendSeriesRef.current = null;
      entryLineRef.current = null;
      tpLineRef.current = null;
      slLineRef.current = null;
      indicatorSeriesMapRef.current.clear();
    };
  }, []);

  // 3a. Mum Verisi + Bollinger Bantları + Supertrend
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    // Fiyat cetveli hassasiyeti: sembol fiyatı (güncel kapanış) değişen
    // aralığa girerse (ör. ilk yüklemede price_try null idi) seriyi güncelle.
    try {
      const prec = priceScalePrecision(candles[candles.length - 1].close);
      candleSeriesRef.current.applyOptions({
        priceFormat: { type: "price", precision: prec, minMove: Math.pow(10, -prec) },
      });
    } catch { /* */ }

    try {
      candleSeriesRef.current.setData(candles as any);
    } catch (e) {
      console.error("candleSeries.setData hatası:", e);
    }

    if (showBB && upperBbRef.current && middleBbRef.current && lowerBbRef.current) {
      const { upper, middle, lower } = calculateBollingerBands(candles, 20, 2);
      if (upper.length > 0) {
        try {
          upperBbRef.current.setData(upper as any);
          middleBbRef.current.setData(middle as any);
          lowerBbRef.current.setData(lower as any);
          upperBbRef.current.applyOptions({ visible: true });
          middleBbRef.current.applyOptions({ visible: true });
          lowerBbRef.current.applyOptions({ visible: true });
        } catch (e) {
          console.error("BB.setData hatası:", e);
        }
      } else {
        upperBbRef.current.applyOptions({ visible: false });
        middleBbRef.current.applyOptions({ visible: false });
        lowerBbRef.current.applyOptions({ visible: false });
      }
    } else if (upperBbRef.current && middleBbRef.current && lowerBbRef.current) {
      upperBbRef.current.applyOptions({ visible: false });
      middleBbRef.current.applyOptions({ visible: false });
      lowerBbRef.current.applyOptions({ visible: false });
    }

    // Supertrend (10, 3)
    if (showSupertrend && supertrendSeriesRef.current && candles.length > 10) {
      try {
        const res = SUPERTREND_ENTRY.calculate(candles, { period: 10, multiplier: 3 });
        const plot0 = res?.plots?.plot0 ?? [];
        if (plot0.length > 0) {
          const formatted = plot0.map((pt) => ({
            time: (pt.time > 1e11 ? Math.floor(pt.time / 1000) : Math.floor(pt.time)) as UTCTimestamp,
            value: pt.value,
            color: pt.color,
          }));
          supertrendSeriesRef.current.setData(formatted as any);
          supertrendSeriesRef.current.applyOptions({ visible: true });
          const lastPoint = plot0[plot0.length - 1];
          setSupertrendTrend(lastPoint.color === "#10b981" ? "UP" : "DOWN");
        } else {
          supertrendSeriesRef.current.applyOptions({ visible: false });
          setSupertrendTrend(null);
        }
      } catch (e) {
        console.error("Supertrend setData hatası:", e);
      }
    } else if (supertrendSeriesRef.current) {
      supertrendSeriesRef.current.applyOptions({ visible: false });
      setSupertrendTrend(null);
    }
    // setData() sonrası price line ref'leri TAZELENMELİ. DÜZELTME (2026-09-19):
    // eskiden yalnız `= null` yapılıyordu — eski çizgi seriden SİLİNMEDİĞİ için
    // 3b effect yeni bir çizgi daha oluşturuyor ve "GİRİŞ" grafikte İKİ KEZ
    // yazılıyordu (BB/Supertrend toggle ve timeframe değişiminde de çoğalıyordu).
    // Doğrusu: önce removePriceLine, sonra null.
    const lineSeries = candleSeriesRef.current;
    if (lineSeries) {
      if (entryLineRef.current) { try { lineSeries.removePriceLine(entryLineRef.current); } catch {} }
      if (tpLineRef.current) { try { lineSeries.removePriceLine(tpLineRef.current); } catch {} }
      if (slLineRef.current) { try { lineSeries.removePriceLine(slLineRef.current); } catch {} }
    }
    entryLineRef.current = null;
    tpLineRef.current = null;
    slLineRef.current = null;
  }, [candles, showBB, showSupertrend]);

  // 3b. Pozisyon Çizgileri (candles'a dokunmaz — sadece fiyat/pending değişince)
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    // Giriş Fiyatı Çizgisi — DÜZELTME (2026-09-19): her zaman önce mevcut
    // çizgiyi KALDIR, sonra oluştur. Eski applyOptions/cREATE karışımı,
    // 3a null'lama sırası ve StrictMode çift-effect birleşince "GİRİŞ"
    // etiketi grafikte iki kez görünüyor ve toggle'larda çoğalıyordu.
    if (entryLineRef.current) { try { series.removePriceLine(entryLineRef.current); } catch {} entryLineRef.current = null; }
    if (entryPrice && entryPrice > 0) {
      entryLineRef.current = series.createPriceLine({
        price: entryPrice,
        color: "#00f3ff",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `GİRİŞ: ₺${fmtPrice(entryPrice)} (${holding.total.toLocaleString("tr-TR")} ${holding.asset})`,
      });
    }

    // Take-Profit (TP) Çizgisi — önce kaldır / sonra oluştur (çift çizgi önlemi)
    const effectiveTp = pendingTp ?? tpPrice;
    if (tpLineRef.current) { try { series.removePriceLine(tpLineRef.current); } catch {} tpLineRef.current = null; }
    if (effectiveTp && effectiveTp > 0) {
      const diffPct = entryPrice ? ((effectiveTp - entryPrice) / entryPrice) * 100 : 0;
      const profitTry = entryPrice ? (effectiveTp - entryPrice) * holding.total : 0;
      tpLineRef.current = series.createPriceLine({
        price: effectiveTp,
        color: pendingTp ? "#22c55e" : "#10b981",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `🎯 TP: ₺${fmtPrice(effectiveTp)} (+${diffPct.toFixed(2)}% | +₺${fmtPrice(profitTry)})`,
      });
    }

    // Stop-Loss (SL) Çizgisi — önce kaldır / sonra oluştur (çift çizgi önlemi)
    const effectiveSl = pendingSl ?? slPrice;
    if (slLineRef.current) { try { series.removePriceLine(slLineRef.current); } catch {} slLineRef.current = null; }
    if (effectiveSl && effectiveSl > 0) {
      const diffPct = entryPrice ? ((effectiveSl - entryPrice) / entryPrice) * 100 : 0;
      const lossTry = entryPrice ? (effectiveSl - entryPrice) * holding.total : 0;
      slLineRef.current = series.createPriceLine({
        price: effectiveSl,
        color: pendingSl ? "#f87171" : "#ef4444",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `🛑 SL: ₺${fmtPrice(effectiveSl)} (${diffPct.toFixed(2)}% | ₺${fmtPrice(lossTry)})`,
      });
    }

    // Piksel koordinatlarını güncelle (updateLineCoordinates ile aynı mantık)
    // Not: updateLineCoordinates useCallback henüz tanımlanmadığı için inline
    if (candleSeriesRef.current) {
      const s = candleSeriesRef.current;
      const coords: { entry?: number | null; tp?: number | null; sl?: number | null } = {};
      if (entryPrice && entryPrice > 0) coords.entry = s.priceToCoordinate(entryPrice);
      const curTp2 = pendingTp ?? tpPrice;
      if (curTp2 && curTp2 > 0) coords.tp = s.priceToCoordinate(curTp2);
      const curSl2 = pendingSl ?? slPrice;
      if (curSl2 && curSl2 > 0) coords.sl = s.priceToCoordinate(curSl2);
      setLineCoords(coords);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryPrice, tpPrice, slPrice, pendingTp, pendingSl, holding, candles]);

  // 4. İndikatörleri Grafikte Güncelle
  useEffect(() => {
    if (!chartApiRef.current || candles.length === 0) return;
    const chart = chartApiRef.current;

    // Silinmiş indikatörlerin serilerini temizle
    const activeUids = new Set(indicators.map((i) => i.uid));
    for (const [uid, series] of indicatorSeriesMapRef.current.entries()) {
      if (!activeUids.has(uid)) {
        series.forEach((s) => { try { chart.removeSeries(s); } catch {} });
        indicatorSeriesMapRef.current.delete(uid);
      }
    }

    // Her aktif indikatörü işle
    for (const ind of indicators) {
      const entry = findIndicatorEntry(ind.registryId);
      if (!entry) continue;

      let result: any;
      try {
        result = entry.calculate(candles, ind.params);
      } catch (e) {
        console.warn("İndikatör hesaplama hatası:", ind.name, e);
        continue;
      }

      const plots = result?.plots ?? {};
      const plotKeys = Object.keys(plots);
      const existing = indicatorSeriesMapRef.current.get(ind.uid) ?? [];

      // Eğer seri sayısı değişmişse önce hepsini temizle
      if (existing.length !== plotKeys.length) {
        existing.forEach((s) => { try { chart.removeSeries(s); } catch {} });
        indicatorSeriesMapRef.current.delete(ind.uid);
      }

      const seriesList: ISeriesApi<"Line">[] = indicatorSeriesMapRef.current.get(ind.uid) ?? [];

      plotKeys.forEach((key, plotIdx) => {
        const plotData = plots[key];
        if (!Array.isArray(plotData) || plotData.length === 0) return;

        const color = ind.style.colors[plotIdx] ?? "#10b981";
        const lw = (ind.style.lineWidths?.[plotIdx] ?? ind.style.lineWidth ?? 2) as 1 | 2 | 3 | 4;

        // Seriyi oluştur ya da güncelle
        let s = seriesList[plotIdx];
        if (!s) {
          s = chart.addSeries(LineSeries, {
            color,
            lineWidth: lw,
            priceLineVisible: ind.style.showPriceLine,
            lastValueVisible: true,
            title: plotIdx === 0 ? ind.name : "",
          });
          seriesList[plotIdx] = s;
        } else {
          s.applyOptions({ color, lineWidth: lw });
        }

        // Veriyi formatla
        const formattedData = plotData
          .filter((pt: any) => pt && Number.isFinite(pt.time) && pt.time > 0)
          .map((pt: any) => ({
            time: (pt.time > 1e11 ? Math.floor(pt.time / 1000) : Math.floor(pt.time)) as UTCTimestamp,
            value: pt.value != null && Number.isFinite(pt.value) ? pt.value : null,
            ...(pt.color ? { color: pt.color } : {}),
          }))
          .filter((pt) => pt.value != null);

        if (formattedData.length > 0) {
          try {
            s.setData(formattedData as any);
          } catch (e) {
            console.debug("İndikatör setData skip:", e);
          }
        }
      });

      indicatorSeriesMapRef.current.set(ind.uid, seriesList);
    }
  }, [indicators, candles]);

  // Çizgilerin dikey piksel koordinatlarını bul (Tutamaçları yerleştirmek için)
  const updateLineCoordinates = useCallback(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;
    const coords: { entry?: number | null; tp?: number | null; sl?: number | null } = {};

    if (entryPrice && entryPrice > 0) {
      coords.entry = series.priceToCoordinate(entryPrice);
    }
    const curTp = pendingTp ?? tpPrice;
    if (curTp && curTp > 0) {
      coords.tp = series.priceToCoordinate(curTp);
    }
    const curSl = pendingSl ?? slPrice;
    if (curSl && curSl > 0) {
      coords.sl = series.priceToCoordinate(curSl);
    }
    setLineCoords(coords);
  }, [entryPrice, tpPrice, slPrice, pendingTp, pendingSl]);

  // 5. WebSocket Canlı Güncellemeler (useLiveMessages)
  useLiveMessages(
    useCallback(
      (msg) => {
        if (!msg) return;

        // Mum Akışı
        if (msg.type === "kline") {
          const klineData = (msg as any).data;
          const msgSymbol = String(klineData?.symbol ?? (msg as any).symbol ?? "").replace(/_/g, "").toUpperCase();
          const targetSym = symbolConcat.replace(/_/g, "").toUpperCase();
          const msgTimeframe = klineData?.timeframe ?? klineData?.interval ?? (msg as any).interval;
          if (msgSymbol !== targetSym || (msgTimeframe && msgTimeframe !== timeframeRef.current)) return;

          const bar = klineData;
          if (!bar || !candleSeriesRef.current) return;
          try {
            let timeSec = 0;
            let open = 0, high = 0, low = 0, close = 0;
            if (Array.isArray(bar)) {
              const rawT = Number(bar[0]);
              timeSec = rawT > 1e11 ? Math.floor(rawT / 1000) : Math.floor(rawT);
              open = Number(bar[1]);
              high = Number(bar[2]);
              low = Number(bar[3]);
              close = Number(bar[4]);
            } else if (typeof bar === "object") {
              const rawT = Number(bar.time ?? bar.open_time ?? bar.openTime ?? bar.t ?? 0);
              timeSec = rawT > 1e11 ? Math.floor(rawT / 1000) : Math.floor(rawT);
              open = Number(bar.open ?? bar.o ?? 0);
              high = Number(bar.high ?? bar.h ?? 0);
              low = Number(bar.low ?? bar.l ?? 0);
              close = Number(bar.close ?? bar.c ?? 0);
            }
            if (!Number.isFinite(timeSec) || timeSec <= 0 || !Number.isFinite(close) || close <= 0) return;
            // KLINE BUCKET DÜZELTMESİ (2026-09-19): gelen mumun açılışı,
            // görüntülenen TF'in AKTİF bucket'ından eskiyse (ör. kapanmış
            // mum tekrarı) seriyi karıştırma; yalnız son mumun zaman
            // damgasını ileri taşı. Yeni bucket Geldiyse update() yeni mumu
            // kendiliğinden oluşturur (lightweight-charts davranışı).
            const tfSecs = TF_SECONDS[timeframeRef.current] || 0;
            const nowSec = Math.floor(Date.now() / 1000);
            const activeBucket = tfSecs > 0 ? Math.floor(nowSec / tfSecs) * tfSecs : timeSec;
            if (tfSecs > 0 && timeSec < activeBucket) {
              // Kapanmış mum tekrarı/geriye giden bar → yalnız fiyatı tazele.
              setCurrentPrice(close);
              return;
            }
            const formatted: CandleBar = {
              time: timeSec as UTCTimestamp,
              open: Number.isFinite(open) && open > 0 ? open : close,
              high: Number.isFinite(high) && high > 0 ? high : close,
              low: Number.isFinite(low) && low > 0 ? low : close,
              close,
            };
            candleSeriesRef.current.update(formatted as any);
            lastCandleRef.current = formatted;
            // Son mum zamanını güncelle
            if (timeSec > lastCandleTimeRef.current) {
              lastCandleTimeRef.current = timeSec;
            }
            setCurrentPrice(formatted.close);
          } catch (e) {
            console.debug("Live kline update skip:", e);
          }
        }

        // Fiyat Tik Akışı.
        //
        // Backend fiyatı `binance_price` (tüm tick'ler haritası) olarak
        // YAYINLAR; `price_tick` tipi hiç yayınlanmıyor (denetim #53). İkisi de
        // dinleniyor: biri bugün ölü, diğeri etkin. `price_tick` backend'de
        // eklenirse bu dal kendiliğinden çalışır.
        if (msg.type === "binance_price") {
          const d = msg.data as { ticks?: Record<string, { price?: number; price_try?: number }> } | null;
          const tick = d?.ticks?.[holding.asset];
          if (tick) {
            const newPrice = Number(tick.price || tick.price_try);
            if (newPrice > 0) {
              applyPriceTick(newPrice);
            }
          }
        } else if (msg.type === "price_tick") {
          const d = msg.data as { symbol?: string; asset?: string; price?: number; price_try?: number } | null;
          if (d && (d.symbol === symbolConcat || d.asset === holding.asset)) {
            const newPrice = Number(d.price || d.price_try);
            if (newPrice > 0) {
              applyPriceTick(newPrice);
            }
          }
        }

        // Tahta / BookTicker Akışı.
        //
        // NOT (denetim #53): backend `bookTicker` ve `depth` WS mesajlarını
        // YAYINLAMIYOR — bu dal bugün ölü bir dinleyicidir (veri REST'ten gelir,
        // 5 sn'de bir, "canlı değil" rozetiyle). Yine de tutuluyor: backend
        // tarafı bu mesajları eklediğinde tahta paneli anında canlı olur ve
        // REST periyodu yalnız yedek görevi görür.
        if (msg.type === "bookTicker" || msg.type === "depth") {
          const d = msg.data as { symbol?: string; s?: string; bid?: number; b?: number; bestBid?: number; ask?: number; a?: number; bestAsk?: number } | null;
          if (d && (d.symbol === symbolConcat || d.s === symbolConcat)) {
            const b = Number(d.bid || d.b || d.bestBid || 0);
            const a = Number(d.ask || d.a || d.bestAsk || 0);
            if (b > 0 && a > 0) {
              setOrderbook((prev) => {
                const spr = a > b ? a - b : 0;
                const sprPct = b > 0 ? (spr / b) * 100 : 0;
                const next = prev ? {
                  ...prev,
                  bestBid: b,
                  bestAsk: a,
                  spread: spr,
                  spreadPct: sprPct,
                } : null;
                if (next) setOrderbookUpdatedAt(Date.now());
                return next;
              });
            }
          }
        }
      },
      [symbolConcat, holding.asset, applyPriceTick]
    )
  );

  // 6. Sürükle-Bırak (Drag & Drop) Fare ve Dokunmatik Olayları
  // Drag sırasındaki fiyatı ref'te tut — mouseUp callback'i stale closure'dan etkilenmesin
  const dragPriceRef = useRef<number | null>(null);
  const draggingTargetRef = useRef<"TP" | "SL" | null>(null);

  const handleMouseDownOnHandle = (
    target: "TP" | "SL",
    e?: { preventDefault?: () => void; stopPropagation?: () => void }
  ) => {
    e?.preventDefault?.();
    e?.stopPropagation?.();
    draggingTargetRef.current = target;
    setDraggingTarget(target);
  };

  useEffect(() => {
    if (!draggingTarget) return;

    const handleMouseMove = (e: MouseEvent | { clientY: number }) => {
      if (!chartContainerRef.current || !candleSeriesRef.current) return;
      const rect = chartContainerRef.current.getBoundingClientRect();
      const relY = e.clientY - rect.top;
      const priceAtY = candleSeriesRef.current.coordinateToPrice(relY);
      if (priceAtY && priceAtY > 0) {
        const raw = Number(priceAtY);
        // Hassasiyet fiyat cetveliyle AYNI tabloya bağlı (sembol fiyatına göre).
        const precision = priceScalePrecision(raw);
        const p = Number(raw.toFixed(precision));
        dragPriceRef.current = p;
        setDragYPrice(p);
        if (draggingTarget === "TP") setPendingTp(p);
        else if (draggingTarget === "SL") setPendingSl(p);
      }
    };

    const handleMouseUp = async () => {
      const finalDragPrice = dragPriceRef.current;
      const target = draggingTargetRef.current;
      draggingTargetRef.current = null;
      dragPriceRef.current = null;
      setDraggingTarget(null);
      setDragYPrice(null);
      updateLineCoordinates();

      // Drag bitti → mevcut emri iptal edip yeni emri otomatik gönder
      if (!finalDragPrice || !target || !sellEnabled) return;

      // Hangi fiyatın ne olduğunu belirle — ref kullan (stale closure sorunu önlenir)
      const finalTp = target === "TP" ? finalDragPrice : (tpPriceRef.current ?? undefined);
      const finalSl = target === "SL" ? finalDragPrice : (slPriceRef.current ?? undefined);

      if (!finalTp && !finalSl) return;
      if (finalTp && finalSl && finalTp <= finalSl) {
        showToast("TP, SL'den büyük olmalıdır — emir gönderilmedi.", "error");
        // Çizgiyi eski yerine döndür
        if (target === "TP") setPendingTp(null);
        else setPendingSl(null);
        return;
      }

      const mode: "OCO" | "SL_ONLY" | "TP_ONLY" =
        finalTp && finalSl ? "OCO" : finalSl ? "SL_ONLY" : "TP_ONLY";

      setIsUpdating(true);
      try {
        const res = await apiRequest(`${API_BASE}/api/binance/set-sl-tp`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            asset: holding.asset,
            mode,
            quantity: holding.total,
            tp_price: finalTp || undefined,
            sl_price: finalSl || undefined,
            sl_limit_price: finalSl ? finalSl * 0.995 : undefined,
            cancel_existing: true,
          }),
        });
        const d = await res.json().catch(() => ({}));
        if (!res.ok || !d.ok) throw new Error(d.detail || `Hata (${res.status})`);

        // Başarı — state'i kesinleştir, pending'i temizle
        if (target === "TP") { commitTpPrice(finalDragPrice); setPendingTp(null); }
        else { commitSlPrice(finalDragPrice); setPendingSl(null); }
        showToast(`${target} güncellendi → ₺${fmtPrice(finalDragPrice)}`, "success");
        onOrderUpdated();
      } catch (err: any) {
        // Hata — çizgiyi eski fiyata döndür
        if (target === "TP") setPendingTp(null);
        else setPendingSl(null);
        showToast(err.message || "Emir gönderilemedi", "error");
      } finally {
        setIsUpdating(false);
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (e.touches.length > 0) {
        if (e.cancelable) e.preventDefault();
        handleMouseMove({ clientY: e.touches[0].clientY });
      }
    };
    const handleTouchEnd = () => {
      void handleMouseUp();
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    window.addEventListener("touchmove", handleTouchMove, { passive: false });
    window.addEventListener("touchend", handleTouchEnd);
    window.addEventListener("touchcancel", handleTouchEnd);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("touchend", handleTouchEnd);
      window.removeEventListener("touchcancel", handleTouchEnd);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draggingTarget]);

  // 7. Sağ Tık Bağlam Menüsü (Context Menu)
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!chartContainerRef.current || !candleSeriesRef.current) return;
    const rect = chartContainerRef.current.getBoundingClientRect();
    const relY = e.clientY - rect.top;
    const priceAtY = candleSeriesRef.current.coordinateToPrice(relY);

    if (priceAtY && priceAtY > 0) {
      setContextMenu({
        x: e.clientX,
        y: e.clientY,
        price: Number(priceAtY),
      });
    }
  };

  const closeContextMenu = () => setContextMenu(null);

  // 8. Değişiklikleri Binance TR API'ye Gönderme
  const handleSaveOrders = async () => {
    const finalTp = pendingTp ?? tpPrice;
    const finalSl = pendingSl ?? slPrice;

    if (!finalTp && !finalSl) {
      showToast("En az bir Kâr Al (TP) veya Zarar Kes (SL) seviyesi belirlenmelidir", "error");
      return;
    }

    let mode: "OCO" | "SL_ONLY" | "TP_ONLY" = "OCO";
    if (finalTp && finalSl) {
      mode = "OCO";
      if (finalTp <= finalSl) {
        showToast("Kâr Al (TP) fiyatı Zarar Kes (SL) fiyatından büyük olmalıdır", "error");
        return;
      }
    } else if (finalSl) {
      mode = "SL_ONLY";
    } else {
      mode = "TP_ONLY";
    }

    setIsUpdating(true);
    setUpdateError(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/binance/set-sl-tp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset: holding.asset,
          mode,
          quantity: holding.total,
          tp_price: finalTp || undefined,
          sl_price: finalSl || undefined,
          sl_limit_price: finalSl ? finalSl * 0.995 : undefined,
          cancel_existing: true,
        }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) {
        throw new Error(d.detail || `Emir güncellenemedi (${res.status})`);
      }

      showToast(`${holding.asset} için ${mode} emri başarıyla güncellendi!`, "success");
      commitTpPrice(finalTp ?? null);
      commitSlPrice(finalSl ?? null);
      setPendingTp(null);
      setPendingSl(null);
      onOrderUpdated();
    } catch (err: any) {
      setUpdateError(err.message || "Emir güncellenirken hata oluştu");
      showToast(err.message || "Hata oluştu", "error");
    } finally {
      setIsUpdating(false);
    }
  };

  const handleCancelPending = () => {
    setPendingTp(null);
    setPendingSl(null);
    setUpdateError(null);
  };

  const handleBreakEven = () => {
    if (!entryPrice || entryPrice <= 0) {
      showToast("Giriş maliyeti bulunamadı.", "error");
      return;
    }
    const curP = currentPrice ?? holding.price_try;
    if (!curP || curP <= entryPrice) {
      showToast("Fiyat henüz alış maliyetinin üzerine (kâra) geçmedi.", "info");
      return;
    }

    const commRate = 2 * commissionPct(); // Gidiş-dönüş komisyon oranı
    const profitBuffer = 0.05 / 100; // %0.05 net kâr kilidi
    const bePrice = entryPrice * (1 + commRate + profitBuffer);

    if (bePrice >= curP) {
      showToast(`Fiyat kârda ancak kâr kilidi seviyesinin (₺${fmtPrice(bePrice)}) altında.`, "info");
      return;
    }

    const precision = curP < 1 ? 6 : 2;
    const finalPrice = Number(bePrice.toFixed(precision));
    setPendingSl(finalPrice);
    showToast(`🔒 Break-Even stop belirlendi: ₺${fmtPrice(finalPrice)}. Kaydetmek için 'Onayla ve Kaydet'e tıklayın.`, "success");
  };

  // İndikatör Yönetimi
  const handleIndicatorSelect = (entry: RegistryEntry) => {
    setShowIndicatorPicker(false);
    setPickerSelectedEntry(entry);
  };

  const handleIndicatorAdd = (entry: RegistryEntry, params: Record<string, any>, style: IndicatorStyle) => {
    const newInd: IndicatorInstance = {
      uid: `${entry.id}_${Date.now()}`,
      registryId: entry.id,
      name: entry.shortName,
      overlay: entry.overlay,
      params,
      style,
    };
    setIndicators((prev) => [...prev, newInd]);
    setPickerSelectedEntry(null);
    showToast(`${entry.shortName} eklendi`, "success");
  };

  const handleIndicatorRemove = (uid: string) => {
    // Grafik serilerini temizle
    const chart = chartApiRef.current;
    if (chart) {
      const series = indicatorSeriesMapRef.current.get(uid) ?? [];
      series.forEach((s) => { try { chart.removeSeries(s); } catch {} });
      indicatorSeriesMapRef.current.delete(uid);
    }
    setIndicators((prev) => prev.filter((i) => i.uid !== uid));
  };

  const handleIndicatorEdit = (ind: IndicatorInstance) => {
    setEditingIndicator(ind);
  };

  const handleIndicatorUpdate = (params: Record<string, any>, style: IndicatorStyle) => {
    if (!editingIndicator) return;
    setIndicators((prev) =>
      prev.map((i) => i.uid === editingIndicator.uid ? { ...i, params, style } : i)
    );
    setEditingIndicator(null);
  };

  // ---- POZİYON KAPAT (GİRİŞ çizgisi ✕) ----
  const priceNow = currentPrice ?? holding.price_try ?? 0;
  const closeQtyNum = useMemo(() => {
    const n = parseFloat(closeQtyInput.replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) return 0;
    if (closeUnit === "asset") return Math.min(n, holding.free);
    // TRY modu: tutarı anlık fiyata bölerek adede çevir (satışta uç fark minimum).
    return priceNow > 0 ? Math.min(n / priceNow, holding.free) : 0;
  }, [closeQtyInput, closeUnit, priceNow, holding.free]);

  const openCloseModal = () => {
    setCloseUnit("asset");
    setCloseMsg(null);
    setCloseQtyInput(String(Number(holding.free.toFixed(6))));
    setCloseModalOpen(true);
  };

  const confirmClosePosition = async () => {
    if (closeBusy) return;
    if (!sellEnabled) {
      setCloseMsg({ ok: false, text: "Gerçek emir gönderimi kapalı — Ayarlar'dan 'GERÇEK SATIŞ' anahtarını açın." });
      return;
    }
    if (closeQtyNum <= 0) {
      setCloseMsg({ ok: false, text: "Geçerli bir miktar girin." });
      return;
    }
    if (closeQtyNum > holding.free + 1e-9) {
      setCloseMsg({ ok: false, text: `Satılabilir bakiye yetersiz (boşta ${fmtPrice(holding.free, 6)} ${holding.asset}).` });
      return;
    }
    setCloseBusy(true);
    setCloseMsg(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/binance/sell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset: holding.asset, quantity: closeQtyNum, confirmation: "REAL_SELL" }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `Satış gönderilemedi (${res.status})`);
      showToast(`${holding.asset} pozisyonu kapatıldı: ${fmtPrice(closeQtyNum, 6)} adet satıldı.`, "success");
      setCloseModalOpen(false);
      onOrderUpdated();
    } catch (err: any) {
      setCloseMsg({ ok: false, text: err.message || "Satış gönderilemedi" });
    } finally {
      setCloseBusy(false);
    }
  };

  // Metrik Hesaplamaları
  const curPnlTry =
    entryPrice && currentPrice ? (currentPrice - entryPrice) * holding.total : null;
  const curPnlPct =
    entryPrice && currentPrice ? ((currentPrice - entryPrice) / entryPrice) * 100 : null;

  // Risk / Reward Oranı
  const effectiveTpVal = pendingTp ?? tpPrice;
  const effectiveSlVal = pendingSl ?? slPrice;
  const riskRewardRatio = useMemo(() => {
    if (!entryPrice || !effectiveTpVal || !effectiveSlVal) return null;
    const reward = effectiveTpVal - entryPrice;
    const risk = entryPrice - effectiveSlVal;
    if (risk <= 0 || reward <= 0) return null;
    return (reward / risk).toFixed(2);
  }, [entryPrice, effectiveTpVal, effectiveSlVal]);

  // Mevcut indikatör entry'sini bul (settings modal için)
  const editingEntry = editingIndicator ? findIndicatorEntry(editingIndicator.registryId) : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-0 sm:p-4 animate-in fade-in duration-200"
      onClick={closeContextMenu}
    >
      <div
        className="relative w-full max-w-7xl h-[100dvh] sm:h-[92vh] flex flex-col rounded-none sm:rounded-2xl border-0 sm:border border-bunker-700/80 bg-[#080b10] shadow-[0_0_50px_rgba(0,0,0,0.8)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ÜST BİLGİ VE KONTROL BARI */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-bunker-800/80 bg-bunker-950/90 px-3 sm:px-4 py-2">
          {/* Sol: Varlık Bilgileri & Canlı Fiyat */}
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-base sm:text-lg font-black tracking-wider text-white">
                {holding.asset}
                <span className="text-xs text-bunker-muted font-normal ml-1">/ TRY</span>
              </span>
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 font-mono text-[9px] sm:text-[10px] font-bold text-emerald-400 border border-emerald-500/30">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                CANLI WS
              </span>
            </div>

            {/* Anlık Fiyat */}
            <div className="flex items-baseline gap-2 font-mono">
              <span
                className={`text-sm sm:text-base font-black tabular-nums transition-colors ${
                  tickDir === "up"
                    ? "text-neon-green"
                    : tickDir === "down"
                    ? "text-neon-red"
                    : "text-white"
                }`}
              >
                ₺{fmtPrice(currentPrice)}
              </span>
              {curPnlPct != null && (
                <span
                  className={`text-[11px] sm:text-xs font-bold tabular-nums ${
                    curPnlPct >= 0 ? "text-neon-green" : "text-neon-red"
                  }`}
                >
                  {curPnlPct >= 0 ? "+" : ""}
                  {curPnlPct.toFixed(2)}% ({curPnlTry != null && (curPnlTry >= 0 ? "+" : "")}₺
                  {fmtPrice(curPnlTry)})
                </span>
              )}
            </div>

            {/* Pozisyon Büyüklüğü */}
            <div className="hidden sm:flex items-center gap-1.5 rounded border border-bunker-800 bg-bunker-900/60 px-2.5 py-1 text-[11px] font-mono text-bunker-muted">
              <span>Bakiye:</span>
              <span className="font-bold text-white">
                {holding.total.toLocaleString("tr-TR")} {holding.asset}
              </span>
              {entryPrice && (
                <span className="ml-2 border-l border-bunker-700 pl-2">
                  Maliyet: <span className="text-cyan-300 font-bold">₺{fmtPrice(entryPrice)}</span>
                </span>
              )}
            </div>
          </div>

          {/* Orta: Timeframe, İndikatör ve Diğer Butonlar (Mobilde Yatay Kaydırılabilir) */}
          <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar w-full sm:w-auto py-1">
            {/* TF Seçici */}
            <div className="flex items-center rounded-lg border border-bunker-800 bg-bunker-900/80 p-0.5">
              {(["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTimeframe(tf)}
                  className={`px-2.5 py-1 text-[11px] font-mono font-bold rounded transition-colors ${
                    timeframe === tf
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm"
                      : "text-bunker-muted hover:text-white"
                  }`}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Bollinger Bands Toggle */}
            <button
              type="button"
              onClick={() => setShowBB(!showBB)}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-mono font-bold transition-colors ${
                showBB
                  ? "border-amber-400/50 bg-amber-400/10 text-amber-300"
                  : "border-bunker-800 bg-bunker-900/60 text-bunker-muted hover:text-white"
              }`}
              title="Bollinger Bantları (20, 2)"
            >
              <span>📊 BB (20,2)</span>
            </button>

            {/* Supertrend (10, 3) Toggle */}
            <button
              type="button"
              onClick={() => setShowSupertrend(!showSupertrend)}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-mono font-bold transition-all ${
                showSupertrend
                  ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-300 shadow-sm shadow-emerald-500/20"
                  : "border-bunker-800 bg-bunker-900/60 text-bunker-muted hover:text-white"
              }`}
              title="Supertrend (10, 3) Trend Göstergesi"
            >
              <span>⚡ Supertrend</span>
              {showSupertrend && supertrendTrend && (
                <span
                  className={`text-[9px] px-1 py-0.2 rounded font-black ${
                    supertrendTrend === "UP"
                      ? "bg-emerald-500/30 text-emerald-300"
                      : "bg-red-500/30 text-red-300"
                  }`}
                >
                  {supertrendTrend === "UP" ? "▲ BOĞA" : "▼ AYI"}
                </span>
              )}
            </button>

            {/* İndikatör Ekleme Butonu */}
            <button
              type="button"
              onClick={() => setShowIndicatorPicker(true)}
              className="relative flex items-center gap-1.5 rounded-lg border border-violet-500/50 bg-violet-500/10 px-2.5 py-1 text-[11px] font-mono font-bold text-violet-300 hover:bg-violet-500/25 hover:border-violet-400 transition-all"
              title="İndikatör Ekle"
            >
              <span>📈 İndikatör</span>
              {indicators.length > 0 && (
                <span className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-violet-500 text-[9px] font-black text-white">
                  {indicators.length}
                </span>
              )}
            </button>

            {/* Görünümü Sığdır */}
            <button
              type="button"
              onClick={() => chartApiRef.current?.timeScale().fitContent()}
              className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-2 py-1 text-[11px] font-mono text-bunker-muted hover:text-white transition-colors"
              title="Grafiği Sığdır"
            >
              ⛶ Sığdır
            </button>

            {/* Break-Even (Kârı Kilitle) Butonu */}
            {entryPrice && currentPrice && currentPrice > entryPrice && (
              <button
                type="button"
                onClick={handleBreakEven}
                className="flex items-center gap-1 rounded-lg border border-amber-500/50 bg-amber-500/15 px-2.5 py-1 text-[11px] font-mono font-bold text-amber-300 hover:bg-amber-500/30 hover:border-amber-400 transition-all shadow-sm"
                title="Giriş maliyeti + komisyon + %0.05 kâr kilidi ile SL ayarla"
              >
                <span>🔒 Break-Even</span>
              </button>
            )}
          </div>

          {/* Sağ: Kapat Butonu */}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-bunker-700/60 bg-bunker-800/50 p-1.5 text-bunker-muted hover:bg-bunker-700 hover:text-white transition-colors"
            title="Kapat (Esc)"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* CANLI TAHTA GÜÇ DENGESİ / ORDERBOOK DEPTH BARI */}
        {orderbook && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-2 border-b border-bunker-800/80 bg-bunker-950/90 px-3 sm:px-4 py-1.5 font-mono text-[11px]">
            <div className="flex items-center justify-between sm:justify-start gap-2">
              <span className="text-bunker-muted text-[10px] font-bold shrink-0">TAHTA:</span>
              {orderbookStale ? (
                // Backend orderbook'u WS ile YAYINLAMIYOR; veri REST'e bağlı ve
                // 5 sn'de bir tazeleniyor. 8 sn'den eskiyse kullanıcıya
                // "canlı değil" diyoruz (eskiden panel hiçbir uyarı vermeden
                // açılış değerini donduruyordu).
                <span title="Orderbook verisi REST ile 5 sn'de bir tazelenir; backend canlı bookTicker yayınlamıyor" className="shrink-0 rounded border border-yellow-400/40 bg-yellow-400/10 px-1.5 py-0.5 text-[9px] font-bold text-yellow-300">
                  ⚠ CANLI DEĞİL ({Math.floor((nowTick - orderbookUpdatedAt) / 1000)} sn)
                </span>
              ) : null}
              <div className="w-28 sm:w-48 h-2 rounded-full overflow-hidden flex bg-bunker-900 border border-bunker-800 shrink-0">
                <div
                  className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-all duration-300"
                  style={{ width: `${Math.min(Math.max(orderbook.bidPct, 5), 95)}%` }}
                  title={`Alıcı Hacim Ağırlığı: %${orderbook.bidPct.toFixed(1)}`}
                />
                <div
                  className="h-full bg-gradient-to-r from-red-400 to-red-600 transition-all duration-300"
                  style={{ width: `${Math.min(Math.max(orderbook.askPct, 5), 95)}%` }}
                  title={`Satıcı Hacim Ağırlığı: %${orderbook.askPct.toFixed(1)}`}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[10px] font-bold">
                <span className="text-emerald-400">%{orderbook.bidPct.toFixed(0)} Alıcı</span>
                <span className="text-bunker-600">/</span>
                <span className="text-red-400">%{orderbook.askPct.toFixed(0)} Satıcı</span>
              </div>
            </div>

            <div className="flex items-center justify-between sm:justify-end gap-2.5 text-bunker-muted text-[10px]">
              {orderbook.bestBid && orderbook.bestAsk && (
                <span className="truncate">
                  Alış: <strong className="text-emerald-300">₺{fmtPrice(orderbook.bestBid)}</strong> | Satış: <strong className="text-red-300">₺{fmtPrice(orderbook.bestAsk)}</strong>
                </span>
              )}
              <span className="shrink-0">
                Spread: <strong className="text-cyan-300">₺{fmtPrice(orderbook.spread)}</strong> (%{orderbook.spreadPct.toFixed(2)})
              </span>
              <span className="hidden md:inline shrink-0">
                20-Derinlik: <strong className="text-white">₺{fmtPrice(orderbook.bidTotal + orderbook.askTotal, 0)}</strong>
              </span>
            </div>
          </div>
        )}

        {/* Aktif İndikatör Listesi (Varsa) */}
        {indicators.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap border-b border-violet-900/40 bg-violet-950/20 px-4 py-1.5">
            <span className="text-[10px] font-mono text-violet-400 font-bold mr-1">İNDİKATÖRLER:</span>
            {indicators.map((ind) => (
              <div
                key={ind.uid}
                className="flex items-center gap-1 rounded-full border border-violet-700/50 bg-violet-900/30 px-2 py-0.5 font-mono text-[10px] text-violet-200"
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: ind.style.colors[0] ?? "#10b981" }}
                />
                <span>{ind.name}</span>
                <button
                  onClick={() => handleIndicatorEdit(ind)}
                  className="text-violet-400 hover:text-white ml-0.5"
                  title="Ayarlar"
                >
                  ⚙
                </button>
                <button
                  onClick={() => handleIndicatorRemove(ind.uid)}
                  className="text-red-400 hover:text-red-300 ml-0.5"
                  title="Kaldır"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {/* BEKLEYEN DEĞİŞİKLİK BİLDİRİMİ / ONAY BARI */}
        {(pendingTp != null || pendingSl != null) && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b border-cyan-500/40 bg-cyan-950/50 px-3 sm:px-4 py-2 text-xs font-mono text-cyan-200 animate-in slide-in-from-top-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="flex h-2.5 w-2.5 rounded-full bg-cyan-400 animate-ping shrink-0" />
              <span className="font-bold text-[11px] sm:text-xs">Seviye Güncellendi:</span>
              {pendingTp != null && (
                <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-300 font-bold border border-emerald-500/40 text-[11px]">
                  🎯 TP: ₺{fmtPrice(pendingTp)}
                </span>
              )}
              {pendingSl != null && (
                <span className="rounded bg-red-500/20 px-2 py-0.5 text-red-300 font-bold border border-red-500/40 text-[11px]">
                  🛑 SL: ₺{fmtPrice(pendingSl)}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 justify-end">
              <button
                type="button"
                onClick={handleCancelPending}
                disabled={isUpdating}
                className="rounded-lg border border-bunker-700 bg-bunker-800/90 px-3.5 py-1.5 font-bold text-bunker-muted hover:text-white transition-colors min-h-[38px] flex items-center justify-center touch-target"
              >
                İptal Et
              </button>
              <button
                type="button"
                onClick={handleSaveOrders}
                disabled={isUpdating || !sellEnabled}
                className="flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500 bg-emerald-600 px-4 py-1.5 font-bold text-white shadow-lg hover:bg-emerald-500 disabled:opacity-50 transition-colors min-h-[38px] touch-target"
              >
                {isUpdating ? "Emir Gönderiliyor..." : "✓ Emirleri Güncelle"}
              </button>
            </div>
          </div>
        )}

        {/* GRAFİK VE INTERAKTİF KATMAN ALANI */}
        <div
          className="relative flex-1 w-full bg-[#080b10] overflow-hidden select-none cursor-crosshair"
          onContextMenu={handleContextMenu}
        >
          {loading && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/50 backdrop-blur-xs">
              <div className="flex items-center gap-2 rounded-lg border border-bunker-700 bg-bunker-900/90 px-4 py-2 font-mono text-xs text-cyan-300">
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                {timeframe.toUpperCase()} mumları yükleniyor...
              </div>
            </div>
          )}

          {/* lightweight-charts DOM konteyneri */}
          <div ref={chartContainerRef} className="w-full h-full" />

          {/* MUM KAPANIŞINA KALAN SÜRE — FİYAT ÖLÇEĞİ TARAFINDA (kullanıcı tercihi
              2026-09-19): sağ üst köşe, fiyat cetvelinin hizasında. */}
          {!loading && countdown > 0 && (
            <div className="absolute top-2 right-16 sm:right-[72px] z-10 pointer-events-none">
              <div className="flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-bunker-950/90 backdrop-blur-sm px-2 py-1 font-mono shadow-lg">
                <span className="text-[9px] text-bunker-muted font-bold">{timeframe.toUpperCase()}</span>
                <span
                  className={`text-xs font-black tabular-nums ${
                    countdown <= 10
                      ? "text-red-400 animate-pulse"
                      : countdown <= 30
                      ? "text-amber-400"
                      : "text-cyan-300"
                  }`}
                >
                  {fmtCountdown(countdown)}
                </span>
              </div>
            </div>
          )}

          {/* İNTERAKTİF SÜRÜKLEME (DRAG HANDLE) BUTONLARI (Fiyat Cetvelinin Yanı) */}
          <div className="absolute top-0 right-14 sm:right-16 bottom-0 w-64 pointer-events-none z-10 overflow-hidden">
            {/* POZİYON KAPAT (✕) — GİRİŞ çizgisi hizasında (kullanıcı tercihi 2026-09-19).
                Klik: miktar + birim girilebilen onay modalını açar. */}
            {lineCoords.entry != null && holding.asset !== "TRY" && (
              <div
                style={{ top: `${lineCoords.entry - 14}px` }}
                className="absolute left-1 pointer-events-auto"
              >
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); openCloseModal(); }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onTouchStart={(e) => e.stopPropagation()}
                  title="Pozisyonu Kapat (kısmi/tam satış)"
                  className="flex h-7 w-7 items-center justify-center rounded-full border border-cyan-400 bg-cyan-950/95 font-mono text-[13px] font-black leading-none text-cyan-200 shadow-lg transition-all hover:scale-110 hover:bg-cyan-800 hover:text-white active:scale-95 select-none"
                >
                  ✕
                </button>
              </div>
            )}

            {/* TP Drag Handle */}
            {lineCoords.tp != null && (
              <div
                style={{ top: `${lineCoords.tp - 22}px` }}
                className="absolute right-1 pointer-events-auto flex items-center h-11 cursor-ns-resize group transition-transform touch-none"
                onMouseDown={(e) => handleMouseDownOnHandle("TP", e)}
                onTouchStart={(e) => {
                  if (e.cancelable) e.preventDefault();
                  handleMouseDownOnHandle("TP", e);
                }}
                title="Kâr Al (TP) çizgisini yukarı/aşağı sürükleyin"
              >
                <div className="flex items-center gap-1.5 rounded-lg border border-emerald-400 bg-emerald-950/95 px-2.5 py-1.5 font-mono text-[11px] sm:text-[10px] font-bold text-emerald-300 shadow-xl group-hover:scale-105 group-hover:bg-emerald-800 transition-all select-none">
                  <span>↕ TP</span>
                  {effectiveTpVal && (
                    <span className="text-emerald-200 font-semibold">
                      ₺{fmtPrice(effectiveTpVal)}
                      {entryPrice ? ` (+${(((effectiveTpVal - entryPrice) / entryPrice) * 100).toFixed(1)}%)` : ""}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* SL Drag Handle */}
            {lineCoords.sl != null && (
              <div
                style={{ top: `${lineCoords.sl - 22}px` }}
                className="absolute right-1 pointer-events-auto flex items-center h-11 cursor-ns-resize group transition-transform touch-none"
                onMouseDown={(e) => handleMouseDownOnHandle("SL", e)}
                onTouchStart={(e) => {
                  if (e.cancelable) e.preventDefault();
                  handleMouseDownOnHandle("SL", e);
                }}
                title="Zarar Kes (SL) çizgisini yukarı/aşağı sürükleyin"
              >
                <div className="flex items-center gap-1.5 rounded-lg border border-red-400 bg-red-950/95 px-2.5 py-1.5 font-mono text-[11px] sm:text-[10px] font-bold text-red-300 shadow-xl group-hover:scale-105 group-hover:bg-red-800 transition-all select-none">
                  <span>↕ SL</span>
                  {effectiveSlVal && (
                    <span className="text-red-200 font-semibold">
                      ₺{fmtPrice(effectiveSlVal)}
                      {entryPrice ? ` (${(((effectiveSlVal - entryPrice) / entryPrice) * 100).toFixed(1)}%)` : ""}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Sürükleme Anında Kılavuz Tooltip */}
          {draggingTarget && dragYPrice && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 rounded-lg border border-cyan-500 bg-bunker-950/90 px-4 py-2 font-mono text-xs text-white shadow-2xl backdrop-blur-md">
              <span className="text-cyan-400 font-bold">{draggingTarget} Ayarlanıyor: </span>
              <span className="text-base font-black tabular-nums">₺{fmtPrice(dragYPrice)}</span>
              {entryPrice && (
                <span
                  className={`ml-2 font-bold ${
                    dragYPrice >= entryPrice ? "text-neon-green" : "text-neon-red"
                  }`}
                >
                  ({dragYPrice >= entryPrice ? "+" : ""}
                  {(((dragYPrice - entryPrice) / entryPrice) * 100).toFixed(2)}%)
                </span>
              )}
            </div>
          )}

          {/* SAĞ TIK BAĞLAMSAL MENÜ (Context Menu) */}
          {contextMenu && (
            <div
              style={{
                top: `${typeof window !== "undefined" ? Math.min(contextMenu.y, window.innerHeight - 300) : contextMenu.y}px`,
                left: `${typeof window !== "undefined" ? Math.min(contextMenu.x, window.innerWidth - 260) : contextMenu.x}px`,
              }}
              className="fixed z-50 min-w-[240px] rounded-xl border border-bunker-700 bg-bunker-950/95 p-1.5 font-mono text-xs text-white shadow-2xl backdrop-blur-md animate-in fade-in zoom-in-95 duration-100"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-2.5 py-1 border-b border-bunker-800 text-[10px] text-bunker-muted font-bold flex justify-between">
                <span>SEÇİLEN FİYAT:</span>
                <span className="text-cyan-300 font-black">₺{fmtPrice(contextMenu.price)}</span>
              </div>

              <button
                type="button"
                onClick={() => {
                  setPendingSl(contextMenu.price);
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-red-300 hover:bg-red-500/20 transition-colors"
              >
                <span>🛑</span>
                <span>Buraya Zarar Kes (SL) Koy</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setPendingTp(contextMenu.price);
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-emerald-300 hover:bg-emerald-500/20 transition-colors"
              >
                <span>🎯</span>
                <span>Buraya Kâr Al (TP) Koy</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  const baseP = currentPrice ?? contextMenu.price;
                  setPendingTp(Number((baseP * 1.02).toFixed(4)));
                  setPendingSl(Number((baseP * 0.98).toFixed(4)));
                  closeContextMenu();
                  showToast("Simetrik OCO (±%2) seviyeleri belirlendi.", "info");
                }}
                className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-cyan-300 hover:bg-cyan-500/20 transition-colors"
              >
                <span>⚡</span>
                <span>Simetrik OCO (±%2) Kur</span>
              </button>

              {entryPrice && currentPrice && currentPrice > entryPrice && (
                <button
                  type="button"
                  onClick={() => {
                    handleBreakEven();
                    closeContextMenu();
                  }}
                  className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-amber-300 hover:bg-amber-500/20 transition-colors"
                >
                  <span>🔒</span>
                  <span>Break-Even Kâr Kilidi Koy</span>
                </button>
              )}

              {(pendingTp != null || pendingSl != null) && (
                <button
                  type="button"
                  onClick={() => {
                    handleCancelPending();
                    closeContextMenu();
                  }}
                  className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-amber-200/80 hover:bg-amber-500/20 transition-colors"
                >
                  <span>↩️</span>
                  <span>Bekleyen Çizgileri Sıfırla</span>
                </button>
              )}

              <div className="my-1 border-t border-bunker-800" />

              <button
                type="button"
                onClick={closeContextMenu}
                className="w-full rounded px-2.5 py-1 text-left text-[11px] text-bunker-muted hover:bg-bunker-800 hover:text-white transition-colors"
              >
                Kapat
              </button>
            </div>
          )}
        </div>

        {/* ALT KONTROL & HIZLI RİSK YÖNETİMİ BARI */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bunker-800/80 bg-bunker-950/90 px-4 py-2.5 font-mono text-xs">
          {/* Sol: Risk / Ödül & Hedefler */}
          <div className="flex items-center gap-4 text-bunker-muted">
            {riskRewardRatio && (
              <div className="flex items-center gap-1.5">
                <span>R:R Oranı:</span>
                <span className="font-bold text-amber-300">1 : {riskRewardRatio}</span>
              </div>
            )}

            {/* Hızlı Yüzde Presets */}
            <div className="hidden md:flex items-center gap-2 border-l border-bunker-800 pl-3">
              <span className="text-[11px]">Hızlı SL:</span>
              {[-1, -2, -3, -5].map((pct) => (
                <button
                  key={pct}
                  type="button"
                  onClick={() => {
                    if (entryPrice) setPendingSl(entryPrice * (1 + pct / 100));
                  }}
                  className="rounded border border-red-500/30 bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-300 hover:bg-red-500/25 transition-colors"
                >
                  {pct}%
                </button>
              ))}

              <span className="text-[11px] ml-2">Hızlı TP:</span>
              {[2, 4, 6, 10].map((pct) => (
                <button
                  key={pct}
                  type="button"
                  onClick={() => {
                    if (entryPrice) setPendingTp(entryPrice * (1 + pct / 100));
                  }}
                  className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-500/25 transition-colors"
                >
                  +{pct}%
                </button>
              ))}
            </div>
          </div>

          {/* Sağ: Bilgilendirme ve İpucu */}
          <div className="flex items-center gap-3 text-bunker-muted text-[11px]">
            <span className="hidden lg:inline">
              💡 İpucu: Çizgileri <strong className="text-white">fareyle tutup sürükleyebilir</strong> veya grafikte <strong className="text-white">sağ tıklayarak</strong> emir ekleyebilirsiniz.
            </span>
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-bunker-700 bg-bunker-800 px-3 py-1 font-bold text-white hover:bg-bunker-700 transition-colors"
            >
              Tamam
            </button>
          </div>
        </div>
      </div>

      {/* POZİYON KAPAT ONAY MODALI (GİRİŞ ✕) */}
      {closeModalOpen && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
          onClick={() => !closeBusy && setCloseModalOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-cyan-500/40 bg-bunker-950 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
              <div>
                <span className="eyebrow text-cyan-300">POZİSYONU KAPAT</span>
                <h2 className="font-mono text-lg font-bold text-white">
                  {holding.asset} Satışı
                  {entryPrice && priceNow > 0 && (
                    <span className={`ml-2 text-sm ${priceNow >= entryPrice ? "text-neon-green" : "text-neon-red"}`}>
                      {priceNow >= entryPrice ? "+" : "−"}%{Math.abs(((priceNow - entryPrice) / entryPrice) * 100).toFixed(2)}
                    </span>
                  )}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => !closeBusy && setCloseModalOpen(false)}
                className="text-bunker-muted hover:text-white"
                aria-label="Kapat"
              >
                ✕
              </button>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[11px]">
              <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-2">
                <p className="text-bunker-muted">FİYAT</p>
                <p className="font-bold text-white">₺{fmtPrice(priceNow)}</p>
              </div>
              <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-2">
                <p className="text-bunker-muted">BOŞTA</p>
                <p className="font-bold text-white">{fmtPrice(holding.free, 6)}</p>
              </div>
              <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-2">
                <p className="text-bunker-muted">TOPLAM</p>
                <p className="font-bold text-white">{fmtPrice(holding.total, 6)}</p>
              </div>
            </div>

            {/* Birim seçimi: Sembol adedi / TRY tutarı */}
            <div className="mt-3 flex items-center rounded-lg border border-bunker-700 bg-bunker-900/60 p-0.5 font-mono text-xs">
              {(["asset", "try"] as const).map((unit) => (
                <button
                  key={unit}
                  type="button"
                  onClick={() => setCloseUnit(unit)}
                  className={`flex-1 rounded-md px-3 py-1.5 font-bold transition-colors ${
                    closeUnit === unit
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50"
                      : "text-bunker-muted hover:text-white"
                  }`}
                >
                  {unit === "asset" ? `${holding.asset} ADEDİ` : "₺ TRY TUTARI"}
                </button>
              ))}
            </div>

            <label className="mt-3 block">
              <span className="eyebrow">
                {closeUnit === "asset" ? `SATILACAK MİKTAR (${holding.asset})` : "SATILACAK TUTAR (₺)"}
              </span>
              <input
                value={closeQtyInput}
                onChange={(e) => setCloseQtyInput(e.target.value.replace(/[^0-9.,]/g, ""))}
                inputMode="decimal"
                placeholder={closeUnit === "asset" ? `Örn: ${fmtPrice(holding.free, 6)}` : "Örn: 500"}
                className="input mt-1 w-full font-mono text-sm"
              />
              <p className="mt-1 font-mono text-[10px] text-bunker-muted">
                {closeQtyNum > 0 ? (
                  <>
                    ≈ {fmtPrice(closeQtyNum, 6)} {holding.asset}
                    {closeUnit === "try" ? "" : ` ≈ ₺${fmtPrice(closeQtyNum * priceNow)}`}
                  </>
                ) : "Miktar girin"}
              </p>
            </label>

            {/* Hızlı % slider çipleri */}
            <div className="mt-2.5 grid grid-cols-4 gap-1.5">
              {[25, 50, 75, 100].map((pct) => (
                <button
                  key={pct}
                  type="button"
                  onClick={() => {
                    const base = holding.free;
                    const q = (base * pct) / 100;
                    setCloseUnit("asset");
                    setCloseQtyInput(String(Number(q.toFixed(6))));
                  }}
                  className={`rounded-lg border px-2 py-2 font-mono text-[11px] font-bold transition-colors ${
                    pct === 100
                      ? "border-neon-red/50 bg-neon-red/10 text-neon-red hover:bg-neon-red/25"
                      : "border-bunker-700 bg-bunker-900/60 text-bunker-muted hover:border-cyan-400/40 hover:text-cyan-300"
                  }`}
                >
                  %{pct}
                </button>
              ))}
            </div>
            <input
              type="range"
              min={0}
              max={holding.free}
              step={Math.max(0.000001, Number((holding.free / 100).toFixed(6)))}
              value={closeUnit === "asset" ? (closeQtyNum || 0) : holding.free}
              onChange={(e) => { setCloseUnit("asset"); setCloseQtyInput(e.target.value); }}
              className="mt-2 w-full accent-[color:var(--neon-red,#ef4444)]"
            />

            {closeMsg && (
              <p className={`mt-2 text-xs ${closeMsg.ok ? "text-neon-green" : "text-neon-red"}`}>
                {closeMsg.text}
              </p>
            )}

            <p className="mt-2 font-mono text-[10px] text-yellow-300/80">
              Dikkat: Piyasa (MARKET) satışı gönderilir — anlık fiyattan gerçekleşir ve iptal edilemez.
            </p>

            <div className="mt-3 flex justify-end gap-2 border-t border-bunker-800 pt-3">
              <button
                type="button"
                onClick={() => !closeBusy && setCloseModalOpen(false)}
                disabled={closeBusy}
                className="ui-button ui-button-secondary disabled:opacity-40"
              >
                İptal
              </button>
              <button
                type="button"
                onClick={confirmClosePosition}
                disabled={closeBusy || closeQtyNum <= 0 || !sellEnabled}
                className="rounded-lg border border-neon-red/60 bg-neon-red/20 px-4 py-2 font-mono text-xs font-bold text-neon-red hover:bg-neon-red/30 disabled:opacity-40 transition-colors"
                title={!sellEnabled ? "Gerçek emir gönderimi kapalı (Ayarlar)" : "Girilen miktar kadar piyasa satışı gönder"}
              >
                {closeBusy ? "GÖNDERİLİYOR…" : `SAT — ${closeUnit === "asset" ? `${fmtPrice(closeQtyNum, 6)} ${holding.asset}` : `₺${fmtPrice(closeQtyNum * priceNow)}`}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* İNDİKATÖR SEÇİCİ MODAL */}
      {showIndicatorPicker && (
        <IndicatorPicker
          onSelect={handleIndicatorSelect}
          onClose={() => setShowIndicatorPicker(false)}
        />
      )}

      {/* İNDİKATÖR AYAR MODAL (Yeni ekleme) */}
      {pickerSelectedEntry && (
        <IndicatorSettings
          entry={pickerSelectedEntry}
          onAdd={(params, style) => handleIndicatorAdd(pickerSelectedEntry, params, style)}
          onClose={() => setPickerSelectedEntry(null)}
        />
      )}

      {/* İNDİKATÖR AYAR MODAL (Düzenleme) */}
      {editingIndicator && editingEntry && (
        <IndicatorSettings
          entry={editingEntry}
          initialParams={editingIndicator.params}
          initialStyle={editingIndicator.style}
          editing
          onAdd={handleIndicatorUpdate}
          onClose={() => setEditingIndicator(null)}
        />
      )}
    </div>
  );
}
