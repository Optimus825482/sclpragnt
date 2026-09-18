"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  Time,
  LineStyle,
} from "lightweight-charts";
import { API_BASE, apiRequest } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";

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
}

type Timeframe = "1m" | "3m" | "5m" | "15m" | "1h" | "4h" | "1d";

interface CandleBar {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

// Bollinger Bands hesaplayıcı (20, 2)
function calculateBollingerBands(bars: CandleBar[], period = 20, multiplier = 2) {
  const upper: { time: Time; value: number }[] = [];
  const middle: { time: Time; value: number }[] = [];
  const lower: { time: Time; value: number }[] = [];

  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      sum += bars[j].close;
    }
    const sma = sum / period;

    let varianceSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      varianceSum += Math.pow(bars[j].close - sma, 2);
    }
    const stdDev = Math.sqrt(varianceSum / period);

    const time = bars[i].time;
    middle.push({ time, value: sma });
    upper.push({ time, value: sma + multiplier * stdDev });
    lower.push({ time, value: sma - multiplier * stdDev });
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

export default function BinancePositionChartModal({
  holding,
  onClose,
  onOrderUpdated,
  sellEnabled,
  showToast,
}: Props) {
  const symbolConcat = `${holding.asset}TRY`;
  const [timeframe, setTimeframe] = useState<Timeframe>("5m"); // Varsayılan M5
  const [showBB, setShowBB] = useState(true); // Varsayılan Bollinger Bands AÇIK
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [loading, setLoading] = useState(true);

  // Canlı Fiyat & Tick Durumu
  const [currentPrice, setCurrentPrice] = useState<number | null>(holding.price_try);
  const [tickDir, setTickDir] = useState<"up" | "down" | null>(null);

  // Pozisyon Çizgi Değerleri
  const entryPrice = holding.avg_cost_try && holding.avg_cost_try > 0 ? holding.avg_cost_try : null;
  const [tpPrice, setTpPrice] = useState<number | null>(holding.active_tp_price || null);
  const [slPrice, setSlPrice] = useState<number | null>(holding.active_sl_price || null);

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

  // DOM & Grafik Referansları
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const middleBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBbRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Fiyat Çizgileri Referansları
  const entryLineRef = useRef<IPriceLine | null>(null);
  const tpLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);

  // Çizgilerin piksel koordinatları (Drag tutamaçları için)
  const [lineCoords, setLineCoords] = useState<{
    entry?: number | null;
    tp?: number | null;
    sl?: number | null;
  }>({});

  // 1. Mum Verisi Yükleme
  const loadKlines = useCallback(async (tf: Timeframe) => {
    setLoading(true);
    try {
      const res = await apiRequest(
        `${API_BASE}/api/market-klines/${symbolConcat}?interval=${tf}&limit=250`
      );
      const data = await res.json();
      if (Array.isArray(data?.candles)) {
        const parsed: CandleBar[] = data.candles
          .map((c: any) => ({
            time: (c.time > 1e11 ? Math.floor(c.time / 1000) : c.time) as Time,
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
          }))
          .sort((a: CandleBar, b: CandleBar) => Number(a.time) - Number(b.time));

        setCandles(parsed);
        if (parsed.length > 0) {
          const lastClose = parsed[parsed.length - 1].close;
          setCurrentPrice(lastClose);
        }
      }
    } catch (err) {
      console.error("Kline yüklenemedi:", err);
    } finally {
      setLoading(false);
    }
  }, [symbolConcat]);

  useEffect(() => {
    loadKlines(timeframe);
  }, [timeframe, loadKlines]);

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

    // Mum Serisi
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
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

    chartApiRef.current = chart;
    candleSeriesRef.current = candleSeries;
    upperBbRef.current = upperBb;
    middleBbRef.current = middleBb;
    lowerBbRef.current = lowerBb;

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    });
    ro.observe(chartContainerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
      entryLineRef.current = null;
      tpLineRef.current = null;
      slLineRef.current = null;
    };
  }, []);

  // 3. Veri Güncelleme & Çizgi Senkronizasyonu
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    candleSeriesRef.current.setData(candles as any);

    // Bollinger Bantları Güncelleme
    if (showBB && upperBbRef.current && middleBbRef.current && lowerBbRef.current) {
      const { upper, middle, lower } = calculateBollingerBands(candles, 20, 2);
      upperBbRef.current.setData(upper as any);
      middleBbRef.current.setData(middle as any);
      lowerBbRef.current.setData(lower as any);
      upperBbRef.current.applyOptions({ visible: true });
      middleBbRef.current.applyOptions({ visible: true });
      lowerBbRef.current.applyOptions({ visible: true });
    } else if (upperBbRef.current && middleBbRef.current && lowerBbRef.current) {
      upperBbRef.current.applyOptions({ visible: false });
      middleBbRef.current.applyOptions({ visible: false });
      lowerBbRef.current.applyOptions({ visible: false });
    }

    // Pozisyon Çizgilerini Yeniden Çiz
    const series = candleSeriesRef.current;

    // Giriş Fiyatı Çizgisi
    if (entryPrice && entryPrice > 0) {
      if (entryLineRef.current) {
        entryLineRef.current.applyOptions({
          price: entryPrice,
          title: `GİRİŞ: ₺${fmtPrice(entryPrice)} (${holding.total.toLocaleString("tr-TR")} ${holding.asset})`,
        });
      } else {
        entryLineRef.current = series.createPriceLine({
          price: entryPrice,
          color: "#00f3ff",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `GİRİŞ: ₺${fmtPrice(entryPrice)} (${holding.total.toLocaleString("tr-TR")} ${holding.asset})`,
        });
      }
    }

    // Take-Profit (TP) Çizgisi
    const effectiveTp = pendingTp ?? tpPrice;
    if (effectiveTp && effectiveTp > 0) {
      const diffPct = entryPrice ? ((effectiveTp - entryPrice) / entryPrice) * 100 : 0;
      const profitTry = entryPrice ? (effectiveTp - entryPrice) * holding.total : 0;
      const title = `🎯 TP: ₺${fmtPrice(effectiveTp)} (+${diffPct.toFixed(2)}% | +₺${fmtPrice(profitTry)})`;
      if (tpLineRef.current) {
        tpLineRef.current.applyOptions({ price: effectiveTp, title, color: pendingTp ? "#22c55e" : "#10b981" });
      } else {
        tpLineRef.current = series.createPriceLine({
          price: effectiveTp,
          color: "#10b981",
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title,
        });
      }
    } else if (tpLineRef.current) {
      series.removePriceLine(tpLineRef.current);
      tpLineRef.current = null;
    }

    // Stop-Loss (SL) Çizgisi
    const effectiveSl = pendingSl ?? slPrice;
    if (effectiveSl && effectiveSl > 0) {
      const diffPct = entryPrice ? ((effectiveSl - entryPrice) / entryPrice) * 100 : 0;
      const lossTry = entryPrice ? (effectiveSl - entryPrice) * holding.total : 0;
      const title = `🛑 SL: ₺${fmtPrice(effectiveSl)} (${diffPct.toFixed(2)}% | ₺${fmtPrice(lossTry)})`;
      if (slLineRef.current) {
        slLineRef.current.applyOptions({ price: effectiveSl, title, color: pendingSl ? "#f87171" : "#ef4444" });
      } else {
        slLineRef.current = series.createPriceLine({
          price: effectiveSl,
          color: "#ef4444",
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title,
        });
      }
    } else if (slLineRef.current) {
      series.removePriceLine(slLineRef.current);
      slLineRef.current = null;
    }

    // Piksel koordinatlarını güncelle
    updateLineCoordinates();
  }, [candles, showBB, entryPrice, tpPrice, slPrice, pendingTp, pendingSl, holding]);

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

  // 4. WebSocket Canlı Güncellemeler (useLiveMessages)
  useLiveMessages(
    useCallback(
      (msg) => {
        if (!msg) return;

        // Mum Akışı
        if (
          msg.type === "kline" &&
          (msg as any).symbol === symbolConcat &&
          (msg as any).interval === timeframe
        ) {
          const bar = (msg as any).data;
          if (!bar || !candleSeriesRef.current) return;
          try {
            const formatted = {
              time: (bar.time > 1e11 ? Math.floor(bar.time / 1000) : bar.time) as Time,
              open: Number(bar.open),
              high: Number(bar.high),
              low: Number(bar.low),
              close: Number(bar.close),
            };
            candleSeriesRef.current.update(formatted as any);
            setCurrentPrice(formatted.close);
          } catch (e) {
            console.debug("Live kline update skip:", e);
          }
        }

        // Fiyat Tik Akışı
        if (msg.type === "price_tick" || msg.type === "binance_price") {
          const d = msg.data as any;
          if (d && (d.symbol === symbolConcat || d.asset === holding.asset)) {
            const newPrice = Number(d.price || d.price_try);
            if (newPrice > 0) {
              setTickDir((prev) => (currentPrice ? (newPrice >= currentPrice ? "up" : "down") : null));
              setCurrentPrice(newPrice);
            }
          }
        }
      },
      [symbolConcat, timeframe, holding.asset, currentPrice]
    )
  );

  // 5. Sürükle-Bırak (Drag & Drop) Fare Olayları
  const handleMouseDownOnHandle = (target: "TP" | "SL", e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDraggingTarget(target);
  };

  useEffect(() => {
    if (!draggingTarget) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!chartContainerRef.current || !candleSeriesRef.current) return;
      const rect = chartContainerRef.current.getBoundingClientRect();
      const relY = e.clientY - rect.top;

      const priceAtY = candleSeriesRef.current.coordinateToPrice(relY);
      if (priceAtY && priceAtY > 0) {
        setDragYPrice(Number(priceAtY));

        // Canlı çizgi güncelleme
        if (draggingTarget === "TP") {
          setPendingTp(Number(priceAtY));
        } else if (draggingTarget === "SL") {
          setPendingSl(Number(priceAtY));
        }
      }
    };

    const handleMouseUp = () => {
      setDraggingTarget(null);
      setDragYPrice(null);
      updateLineCoordinates();
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [draggingTarget, updateLineCoordinates]);

  // 6. Sağ Tık Bağlam Menüsü (Context Menu)
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

  // 7. Değişiklikleri Binance TR API'ye Gönderme
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
      setTpPrice(finalTp);
      setSlPrice(finalSl);
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-2 md:p-4 animate-in fade-in duration-200"
      onClick={closeContextMenu}
    >
      <div
        className="relative w-full max-w-7xl h-[92vh] flex flex-col rounded-2xl border border-bunker-700/80 bg-[#080b10] shadow-[0_0_50px_rgba(0,0,0,0.8)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ÜST BİLGİ VE KONTROL BARI */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bunker-800/80 bg-bunker-950/80 px-4 py-2.5">
          {/* Sol: Varlık Bilgileri & Canlı Fiyat */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-lg font-black tracking-wider text-white">
                {holding.asset}
                <span className="text-xs text-bunker-muted font-normal ml-1">/ TRY</span>
              </span>
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-400 border border-emerald-500/30">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                CANLI WS
              </span>
            </div>

            {/* Anlık Fiyat */}
            <div className="flex items-baseline gap-2 font-mono">
              <span
                className={`text-base font-black tabular-nums transition-colors ${
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
                  className={`text-xs font-bold tabular-nums ${
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

          {/* Orta: Timeframe ve İndikatör Butonları */}
          <div className="flex items-center gap-1.5">
            {/* TF Seçici */}
            <div className="flex items-center rounded-lg border border-bunker-800 bg-bunker-900/80 p-0.5">
              {(["1m", "3m", "5m", "15m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
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

            {/* Görünümü Sığdır */}
            <button
              type="button"
              onClick={() => chartApiRef.current?.timeScale().fitContent()}
              className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-2 py-1 text-[11px] font-mono text-bunker-muted hover:text-white transition-colors"
              title="Grafiği Sığdır"
            >
              ⛶ Sığdır
            </button>
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

        {/* BEKLEYEN DEĞİŞİKLİK BİLDİRİMİ / ONAY BARI */}
        {(pendingTp != null || pendingSl != null) && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cyan-500/40 bg-cyan-950/40 px-4 py-2 text-xs font-mono text-cyan-200 animate-in slide-in-from-top-2">
            <div className="flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
              <span className="font-bold">Grafik Üzerinden Seviye Güncellendi:</span>
              {pendingTp != null && (
                <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-300 font-bold border border-emerald-500/40">
                  🎯 Yeni TP: ₺{fmtPrice(pendingTp)}
                </span>
              )}
              {pendingSl != null && (
                <span className="rounded bg-red-500/20 px-2 py-0.5 text-red-300 font-bold border border-red-500/40">
                  🛑 Yeni SL: ₺{fmtPrice(pendingSl)}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCancelPending}
                disabled={isUpdating}
                className="rounded border border-bunker-700 bg-bunker-800/80 px-3 py-1 font-bold text-bunker-muted hover:text-white transition-colors"
              >
                İptal Et
              </button>
              <button
                type="button"
                onClick={handleSaveOrders}
                disabled={isUpdating || !sellEnabled}
                className="flex items-center gap-1.5 rounded border border-emerald-500 bg-emerald-600 px-4 py-1 font-bold text-white shadow-lg hover:bg-emerald-500 disabled:opacity-50 transition-colors"
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

          {/* İNTERAKTİF SÜRÜKLEME (DRAG HANDLE) BUTONLARI (Fiyat Cetvelinin Yanı) */}
          <div className="absolute top-0 right-16 bottom-0 w-24 pointer-events-none z-10 overflow-hidden">
            {/* TP Drag Handle */}
            {lineCoords.tp != null && (
              <div
                style={{ top: `${lineCoords.tp - 12}px` }}
                className="absolute right-1 pointer-events-auto flex items-center gap-1 cursor-ns-resize group transition-transform"
                onMouseDown={(e) => handleMouseDownOnHandle("TP", e)}
                title="Kâr Al (TP) çizgisini yukarı/aşağı sürükleyin"
              >
                <div className="flex items-center gap-1 rounded border border-emerald-400 bg-emerald-950/90 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-300 shadow-md group-hover:scale-105 group-hover:bg-emerald-800 transition-all">
                  <span>↕ TP</span>
                </div>
              </div>
            )}

            {/* SL Drag Handle */}
            {lineCoords.sl != null && (
              <div
                style={{ top: `${lineCoords.sl - 12}px` }}
                className="absolute right-1 pointer-events-auto flex items-center gap-1 cursor-ns-resize group transition-transform"
                onMouseDown={(e) => handleMouseDownOnHandle("SL", e)}
                title="Zarar Kes (SL) çizgisini yukarı/aşağı sürükleyin"
              >
                <div className="flex items-center gap-1 rounded border border-red-400 bg-red-950/90 px-2 py-0.5 font-mono text-[10px] font-bold text-red-300 shadow-md group-hover:scale-105 group-hover:bg-red-800 transition-all">
                  <span>↕ SL</span>
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
              style={{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }}
              className="fixed z-50 min-w-[220px] rounded-xl border border-bunker-700 bg-bunker-950/95 p-1.5 font-mono text-xs text-white shadow-2xl backdrop-blur-md animate-in fade-in zoom-in-95 duration-100"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-2.5 py-1 border-b border-bunker-800 text-[10px] text-bunker-muted font-bold">
                FİYAT: ₺{fmtPrice(contextMenu.price)}
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
    </div>
  );
}
