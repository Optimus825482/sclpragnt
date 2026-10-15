"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiRequest, API_BASE } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { useLiveMessages } from "../lib/liveSocket";
import { formatCompact, formatPct, formatPrice, formatTL } from "../lib/format";
import { sound } from "../lib/sound";
import { useModalA11y } from "../lib/useModalA11y";
import type { BinancePositions, BinanceSettings, MarketSymbols, MarketTicker } from "../lib/types";
import type { OpportunityView } from "../lib/opportunity";
import { Badge, Button, Card } from "./ui";
import SymbolSelect from "./SymbolSelect";
import OrderBook from "./OrderBook";

type SlTpMode = "OCO" | "SL_ONLY" | "TP_ONLY";
const USER_EVENT_TYPES = ["binance_user_event"] as const;

type OrderKind = "MARKET" | "LIMIT" | "STOP_LIMIT";
type OrderReceipt = {
  symbol: string;
  orderId?: string | number;
  clientId?: string;
  status?: string;
  executedQty?: string | number;
  executedQuoteQty?: string | number;
  avgPrice?: string | number;
  acceptedAt?: string;
  lastEventTimeMs?: number;
};

/**
 * Onay penceresi açıldığı anda DONDURULAN emir görüntüsü (denetim P0-1b/P0-2).
 * Modal açıkken tarama yenilemesi, ticker tick'i veya prop değişimi panelin
 * sembol/tutarını değiştirse bile borsaya giden şey bu anlık görüntüdür.
 * `clientOrderId` pencere başına tek üretilir: zaman aşımında aynı anahtarla
 * tekrar gönderilirse backend ikinci emri açmaz (idempotency).
 */
type OrderSnapshot = {
  clientOrderId: string;
  symbol: string;
  base: string;
  quoteAsset: string;
  side: "BUY" | "SELL";
  kind: OrderKind;
  amount: number;
  limitPrice: number | null;
  stopPrice: number | null;
  stopLimitPrice: number | null;
  /** Onay anındaki referans fiyat (piyasa son fiyatı ya da girilen limit). */
  referencePrice: number | null;
  estimatedQuote: number;
  openedAt: number;
};

/** Emir POST'u için toplam bekleme; aşılırsa sonuç BELİRSİZ sayılır, tekrar gönderilmez. */
const ORDER_TIMEOUT_MS = 20_000;

function newClientOrderId(): string {
  const cryptoApi = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
  // Çok eski tarayıcı: zaman + rastgele; Binance TR clientId üst sınırı 36 karakter.
  return `ui${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`.slice(0, 36);
}

/** Ağ kesintisi / zaman aşımı: istek borsaya ulaşmış OLABİLİR, sonuç bilinmez. */
function isNetworkFailure(reason: unknown) {
  return (reason instanceof DOMException && reason.name === "AbortError") || reason instanceof TypeError;
}

function normalizeOrderStatus(status?: string | number) {
  const raw = status == null ? "" : String(status).toUpperCase();
  const numeric: Record<string, string> = {
    "-2": "SYSTEM_PROCESSING",
    UNKNOWN: "UNKNOWN",
    "0": "NEW",
    "1": "PARTIALLY_FILLED",
    "2": "FILLED",
    "3": "CANCELED",
    "5": "REJECTED",
    "6": "EXPIRED",
  };
  return numeric[raw] || raw;
}

function orderStatusLabel(status?: string) {
  const normalized = normalizeOrderStatus(status);
  const labels: Record<string, string> = {
    NEW: "Açık · gerçekleşme bekleniyor",
    PENDING_NEW: "Kabul edildi · işleme alınması bekleniyor",
    PARTIALLY_FILLED: "Kısmen gerçekleşti",
    FILLED: "Tamamen gerçekleşti",
    CANCELED: "İptal edildi",
    REJECTED: "Reddedildi",
    EXPIRED: "Süresi doldu",
    PENDING_CANCEL: "İptal isteği işleniyor",
    SYSTEM_PROCESSING: "Borsa sisteminde işleniyor",
    UNKNOWN: "Sonuç belirsiz · tekrar emir göndermeyin",
  };
  return normalized ? labels[normalized] || `Durum: ${normalized}` : "Kabul edildi · gerçekleşme durumu henüz bildirilmedi";
}

function responseDetail(body: any) {
  return typeof body?.detail === "string" ? body.detail : body?.detail?.message || body?.detail?.reason;
}

/** Gerçek Binance TR spot emir paneli. Emir kabulü ile gerçekleşme durumu ayrı gösterilir. */
export default function OrderPanel({
  initialSymbol,
  initialAmount,
  initialCandidate,
  onTraded,
}: {
  initialSymbol?: string | null;
  initialAmount?: string | number | null;
  initialCandidate?: OpportunityView | null;
  onTraded?: () => void;
}) {
  const symbolsQ = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const binance = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const balances = usePoll<BinancePositions>(binance.data?.configured ? "/api/binance/positions" : null, 30_000);
  const [symbol, setSymbol] = useState<string | null>(initialSymbol ?? null);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [kind, setKind] = useState<OrderKind>("MARKET");
  const [amount, setAmount] = useState(initialAmount ? String(initialAmount) : "");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [stopLimitPrice, setStopLimitPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<OrderSnapshot | null>(null);
  const reviewOpen = review !== null;
  const reviewRef = useRef(reviewOpen);
  reviewRef.current = reviewOpen;
  const closeReview = () => { if (!busy) setReview(null); };
  const reviewA11y = useModalA11y(reviewOpen, closeReview, "Gerçek Binance TR emri onayı");
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<{ tone: "gain" | "loss" | "warn"; text: string } | null>(null);
  const [receipt, setReceipt] = useState<OrderReceipt | null>(null);

  // SL/TP koruma (gerçek pozisyon için borsada bekleyen emir)
  const [sltpOpen, setSltpOpen] = useState(false);
  const [sltpMode, setSltpMode] = useState<SlTpMode>("OCO");
  const [tpPrice, setTpPrice] = useState("");
  const [slPrice, setSlPrice] = useState("");
  const [slLimitPrice, setSlLimitPrice] = useState("");
  const [sltpQty, setSltpQty] = useState("");
  const [cancelExisting, setCancelExisting] = useState(false);
  const [sltpBusy, setSltpBusy] = useState(false);
  const [sltpConfirm, setSltpConfirm] = useState(false);
  const [sltpMessage, setSltpMessage] = useState<{ tone: "gain" | "loss" | "warn"; text: string } | null>(null);
  const receiptRef = useRef(receipt);
  receiptRef.current = receipt;

  useLiveMessages((liveMessage) => {
    if (liveMessage.type !== "binance_user_event") return;
    const event = liveMessage.data as { event_type?: string; fields?: Record<string, unknown> } | undefined;
    if (event?.event_type !== "executionReport" || !event.fields) return;
    const fields = event.fields;
    const current = receiptRef.current;
    if (!current) return;

    const eventClientId = String(fields.client_order_id ?? fields.clientId ?? "");
    const eventOrderId = String(fields.order_id ?? fields.orderId ?? "");
    const matchesId = Boolean(
      (current.clientId && eventClientId && current.clientId === eventClientId)
      || (current.orderId != null && eventOrderId && String(current.orderId) === eventOrderId),
    );
    const eventSymbol = String(fields.symbol ?? "");
    if (!matchesId || (eventSymbol && current.symbol && eventSymbol !== current.symbol)) return;
    const eventTime = Number(fields.event_time_ms ?? fields.transaction_time_ms ?? 0);
    if (eventTime > 0 && current.lastEventTimeMs != null && eventTime < current.lastEventTimeMs) return;

    const quantity = fields.cumulative_filled_quantity ?? fields.executedQty;
    const quoteQuantity = fields.cumulative_quote_quantity ?? fields.executedQuoteQty;
    const filled = Number(quantity);
    const quote = Number(quoteQuantity);
    const eventStatus = normalizeOrderStatus(fields.status as string | number | undefined);
    setReceipt((previous) => {
      if (!previous) return previous;
      const next = {
        ...previous,
        lastEventTimeMs: eventTime > 0 ? Math.max(eventTime, previous.lastEventTimeMs || 0) : previous.lastEventTimeMs,
        status: eventStatus || previous.status,
        executedQty: quantity == null ? previous.executedQty : String(quantity),
        executedQuoteQty: quoteQuantity == null ? previous.executedQuoteQty : String(quoteQuantity),
        avgPrice: Number.isFinite(filled) && filled > 0 && Number.isFinite(quote) ? String(quote / filled) : previous.avgPrice,
      };
      receiptRef.current = next;
      return next;
    });
    balances.reload();
  }, USER_EVENT_TYPES);

  // Prop senkronu onay penceresi AÇIKKEN DONAR (denetim P0-1b): kullanıcı
  // gözden geçirirken tarama yenilemesi sembolü/tutarı değiştiremez.
  useEffect(() => { if (initialSymbol && !reviewRef.current) setSymbol(initialSymbol); }, [initialSymbol]);
  useEffect(() => {
    if (reviewRef.current) return;
    setAmount(initialAmount == null || initialAmount === "" ? "" : String(initialAmount));
  }, [initialAmount, initialSymbol]);
  const activeSymbol = symbol || initialSymbol || null;
  const ticker = usePoll<MarketTicker>(activeSymbol ? `/api/market-ticker/${activeSymbol}` : null, 15_000);
  const base = activeSymbol ? activeSymbol.replace("TRY", "").replace("USDT", "") : "";
  const quoteAsset = activeSymbol?.endsWith("USDT") ? "USDT" : "TRY";
  const quoteFree = Number(balances.data?.balances?.find((x) => x.asset === quoteAsset)?.free ?? 0);
  const assetFree = Number(balances.data?.balances?.find((x) => x.asset === base)?.free ?? 0);
  const priceForEstimate = kind === "MARKET" ? ticker.data?.last : Number(limitPrice || stopLimitPrice) || null;
  const approxBase = useMemo(() => {
    const value = Number(amount);
    return side === "BUY" && kind === "MARKET" && priceForEstimate && Number.isFinite(value) && value > 0 ? value / priceForEstimate : null;
  }, [amount, kind, priceForEstimate, side]);
  const estimatedQuote = kind === "MARKET" && side === "BUY"
    ? Number(amount || 0)
    : Number(amount || 0) * Number(priceForEstimate || 0);
  const avgCost = balances.data?.holdings?.find((h) => h.asset === base)?.avg_cost_try ?? null;
  const currentPrice = ticker.data?.last ?? null;

  function sltpPctFill(target: "tp" | "sl", pct: number) {
    if (!currentPrice) return;
    const value = target === "tp" ? currentPrice * (1 + pct / 100) : currentPrice * (1 - pct / 100);
    if (target === "tp") setTpPrice(value.toFixed(priceDigits(currentPrice)));
    else setSlPrice(value.toFixed(priceDigits(currentPrice)));
  }

  function priceDigits(price: number) {
    if (price >= 1000) return 2;
    if (price >= 1) return 4;
    return 6;
  }

  async function submitSltp() {
    if (!activeSymbol) return;
    const tp = Number(tpPrice || 0);
    const sl = Number(slPrice || 0);
    if (sltpMode === "OCO" && (tp <= 0 || sl <= 0)) { setSltpMessage({ tone: "loss", text: "OCO için hem TP hem SL fiyatı gerekli." }); return; }
    if (sltpMode === "TP_ONLY" && tp <= 0) { setSltpMessage({ tone: "loss", text: "Kâr Al (TP) fiyatı girin." }); return; }
    if (sltpMode === "SL_ONLY" && sl <= 0) { setSltpMessage({ tone: "loss", text: "Zarar Kes (SL) fiyatı girin." }); return; }
    if (sltpMode === "OCO" && tp <= sl) { setSltpMessage({ tone: "loss", text: "TP fiyatı SL fiyatından büyük olmalı." }); return; }
    setSltpBusy(true);
    setSltpConfirm(false);
    setSltpMessage(null);
    try {
      const payload: Record<string, unknown> = { asset: base, mode: sltpMode, cancel_existing: cancelExisting };
      if (tp > 0) payload.tp_price = tp;
      if (sl > 0) payload.sl_price = sl;
      if (Number(slLimitPrice) > 0) payload.sl_limit_price = Number(slLimitPrice);
      if (Number(sltpQty) > 0) payload.quantity = Number(sltpQty);
      const response = await apiRequest(`${API_BASE}/api/binance/set-sl-tp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(responseDetail(body) || `Koruma emri gönderilemedi (${response.status})`);
      setSltpMessage({ tone: "gain", text: "Koruma emri borsaya gönderildi. Açık emirler ekranından durumu izleyin." });
      balances.reload();
    } catch (reason) {
      setSltpMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Koruma emri gönderilemedi" });
    } finally {
      setSltpBusy(false);
    }
  }

  function mergeReceipt(body: any, fallbackSymbol: string): OrderReceipt {
    const raw = body?.order ?? body?.data ?? body;
    return {
      symbol: String(raw?.symbol || fallbackSymbol),
      orderId: raw?.orderId ?? raw?.order_id,
      clientId: raw?.clientId ?? raw?.client_id ?? raw?.origClientOrderId,
      status: normalizeOrderStatus(raw?.status ?? raw?.state) || undefined,
      executedQty: raw?.executedQty ?? raw?.executed_qty,
      executedQuoteQty: raw?.executedQuoteQty ?? raw?.executed_quote_qty,
      avgPrice: raw?.avgPrice ?? raw?.avg_price,
      acceptedAt: raw?.acceptedAt ?? raw?.accepted_at,
    };
  }

  async function refreshOrderStatus(current = receipt) {
    if (!current?.symbol || !current.clientId || refreshing) return;
    setRefreshing(true);
    try {
      const query = new URLSearchParams({ symbol: current.symbol, client_id: current.clientId });
      const response = await apiRequest(`${API_BASE}/api/binance/order-status?${query.toString()}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(responseDetail(body) || `Emir durumu alınamadı (${response.status})`);
      const updated = mergeReceipt(body, current.symbol);
      setReceipt((previous) => ({
        ...(previous || current),
        ...updated,
        orderId: updated.orderId ?? previous?.orderId ?? current.orderId,
        clientId: updated.clientId ?? previous?.clientId ?? current.clientId,
        status: updated.status ?? previous?.status ?? current.status,
        executedQty: updated.executedQty ?? previous?.executedQty ?? current.executedQty,
        executedQuoteQty: updated.executedQuoteQty ?? previous?.executedQuoteQty ?? current.executedQuoteQty,
        avgPrice: updated.avgPrice ?? previous?.avgPrice ?? current.avgPrice,
      }));
      balances.reload();
    } catch (reason) {
      setMessage({ tone: "warn", text: reason instanceof Error ? reason.message : "Emir durumu yenilenemedi" });
    } finally {
      setRefreshing(false);
    }
  }

  /** Girdileri doğrular, anlık görüntüyü dondurur ve onay penceresini açar. EMİR GÖNDERMEZ. */
  function openReview() {
    if (!activeSymbol) return;
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setMessage({ tone: "loss", text: "Geçerli bir tutar veya miktar girin." });
      return;
    }
    const limit = kind === "LIMIT" ? Number(limitPrice) : kind === "STOP_LIMIT" ? Number(stopLimitPrice) : null;
    if ((kind === "LIMIT" || kind === "STOP_LIMIT") && (!Number.isFinite(Number(limit)) || Number(limit) <= 0)) {
      setMessage({ tone: "loss", text: "Geçerli bir limit fiyatı girin." });
      return;
    }
    const stop = kind === "STOP_LIMIT" ? Number(stopPrice) : null;
    if (kind === "STOP_LIMIT" && (!Number.isFinite(Number(stop)) || Number(stop) <= 0)) {
      setMessage({ tone: "loss", text: "Geçerli bir tetikleme fiyatı girin." });
      return;
    }
    const reference = kind === "MARKET" ? (ticker.data?.last ?? null) : limit;
    setMessage(null);
    setReview({
      clientOrderId: newClientOrderId(),
      symbol: activeSymbol,
      base,
      quoteAsset,
      side,
      kind,
      amount: value,
      limitPrice: kind === "LIMIT" ? limit : null,
      stopPrice: stop,
      stopLimitPrice: kind === "STOP_LIMIT" ? limit : null,
      referencePrice: reference,
      estimatedQuote: kind === "MARKET" && side === "BUY" ? value : value * Number(reference || 0),
      openedAt: Date.now(),
    });
  }

  async function submitOrder() {
    const snapshot = review;
    if (!snapshot || busy) return;
    setBusy(true);
    setMessage(null);
    setReceipt(null);
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), ORDER_TIMEOUT_MS);
    try {
      const payload: Record<string, string> = {
        symbol: snapshot.symbol,
        side: snapshot.side,
        type: snapshot.kind === "STOP_LIMIT" ? "STOP_LOSS_LIMIT" : snapshot.kind,
        confirmation: "REAL_ORDER",
        client_order_id: snapshot.clientOrderId,
      };
      if (snapshot.kind === "MARKET" && snapshot.side === "BUY") payload.quote_order_qty = String(snapshot.amount);
      else payload.quantity = String(snapshot.amount);
      if (snapshot.kind === "LIMIT") payload.price = String(snapshot.limitPrice);
      if (snapshot.kind === "STOP_LIMIT") {
        payload.stop_price = String(snapshot.stopPrice);
        payload.stop_limit_price = String(snapshot.stopLimitPrice);
      }

      const response = await apiRequest(`${API_BASE}/api/binance/order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(responseDetail(body) || `Binance emri gönderilemedi (${response.status})`);

      const nextReceipt = mergeReceipt(body, snapshot.symbol);
      if (!nextReceipt.clientId) nextReceipt.clientId = snapshot.clientOrderId;
      setReceipt(nextReceipt);
      setReview(null);
      sound.playSuccessTone();
      const normalizedStatus = normalizeOrderStatus(nextReceipt.status);
      setMessage(normalizedStatus === "UNKNOWN"
        ? { tone: "warn", text: "Emrin sonucu belirsiz. Yinelenen emir oluşmaması için yeniden göndermeyin; \"Durumu sorgula\" ile kontrol edin." }
        : {
          tone: normalizedStatus === "FILLED" ? "gain" : "warn",
          text: normalizedStatus === "FILLED"
            ? "Emir Binance TR tarafından tamamen gerçekleşti."
            : "Emir Binance TR tarafından kabul edildi; bu yanıt dolduğunu göstermez.",
        });
      setAmount("");
      onTraded?.();
      balances.reload();
    } catch (reason) {
      setReview(null);
      if (isNetworkFailure(reason)) {
        // Zaman aşımı / ağ hatası: emir borsaya ulaşmış OLABİLİR. Otomatik tekrar
        // YOK; kullanıcı client_order_id ile durumu sorgular. Aynı anahtarla
        // elle tekrar gönderilse bile backend ikinci emri açmaz.
        setReceipt({ symbol: snapshot.symbol, clientId: snapshot.clientOrderId, status: "UNKNOWN" });
        setMessage({ tone: "warn", text: "Durum belirsiz: sunucudan yanıt alınamadı. Emir iletilmiş olabilir; yeniden GÖNDERMEYİN, \"Durumu sorgula\" ile kontrol edin." });
      } else {
        setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Binance emri gönderilemedi" });
      }
    } finally {
      window.clearTimeout(timer);
      setBusy(false);
    }
  }

  const tickerData = ticker.data;
  const enabled = Boolean(binance.data?.configured && binance.data?.sell_enabled);
  const status = normalizeOrderStatus(receipt?.status);

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <p className="odak-kicker">Binance TR İşlem Paneli</p>
        <span role="status">
          <Badge tone={binance.data?.configured ? "gain" : "warn"}>
            {binance.data?.configured ? "GERÇEK HESAP" : binance.error && !binance.data ? "AYAR ALINAMADI" : binance.loading ? "KONTROL EDİLİYOR" : "BAĞLI DEĞİL"}
          </Badge>
        </span>
      </div>
      {binance.data?.configured && <p className={`mt-1 text-[10px] ${balances.data?.user_stream?.connected ? "text-gain" : "text-ink-400"}`} role="status">
        {balances.data?.user_stream?.connected ? "Özel emir ve bakiye akışı bağlı" : `Özel akış: ${balances.data?.user_stream?.state || "bağlanıyor"} · REST durum sorgusu kullanılabilir`}
      </p>}
      <div className="mt-2"><SymbolSelect symbols={symbolsQ.data?.symbols || []} value={activeSymbol} onChange={setSymbol} /></div>
      {initialCandidate && initialCandidate.symbol === activeSymbol && <div className="mt-2 rounded-lg border border-accent/20 bg-accent/5 p-2.5 text-[10px]">
        <div className="flex items-center justify-between gap-2"><span className="font-semibold text-ink-800">Aday panele aktarıldı</span><span className="text-ink-500">{initialCandidate.horizonMinutes ?? "—"} dk · skor {initialCandidate.strength ?? "—"}</span></div>
        <p className="mt-1 text-ink-500">Kaynak: {initialCandidate.sources.length ? initialCandidate.sources.join(" · ") : "Birleşik tarama"}{initialCandidate.potentialPct != null ? ` · potansiyel ${initialCandidate.potentialPct.toFixed(2)}%` : ""}</p>
        <p className="mt-1 font-medium text-warn">Aday aktarımı emir göndermez. Gerçek emir için risk kontrolü ve son onay gerekir.</p>
      </div>}

      {!activeSymbol ? (
        <p className="mt-4 rounded-lg border border-dashed border-line py-6 text-center text-xs text-ink-400">Fiyat ve emir için bir sembol seçin.</p>
      ) : <>
        <div className="mt-3 rounded-xl border border-line p-3">
          <div className="flex items-baseline justify-between">
            <span className="font-mono text-xl font-bold text-ink-900">{formatPrice(tickerData?.last)}</span>
            {tickerData?.change_pct != null && <span className={`font-mono text-sm font-semibold ${tickerData.change_pct >= 0 ? "text-gain" : "text-loss"}`}>{tickerData.change_pct >= 0 ? "+" : ""}{formatPct(tickerData.change_pct, 2)}</span>}
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
            <div><p className="text-ink-400">Hacim (24s)</p><p className="font-mono text-ink-700">{formatCompact(tickerData?.quote_volume)}</p></div>
            <div><p className="text-ink-400">En Düşük</p><p className="font-mono text-ink-700">{formatPrice(tickerData?.low)}</p></div>
            <div><p className="text-ink-400">En Yüksek</p><p className="font-mono text-ink-700">{formatPrice(tickerData?.high)}</p></div>
          </div>
        </div>

        <OrderBook symbol={activeSymbol} />

        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" onClick={() => { setSide("BUY"); setAmount(""); }} className={`rounded-lg py-2 text-sm font-semibold ${side === "BUY" ? "bg-gain text-white" : "border border-line text-ink-500"}`}>AL</button>
          <button type="button" onClick={() => { setSide("SELL"); setAmount(""); }} className={`rounded-lg py-2 text-sm font-semibold ${side === "SELL" ? "bg-loss text-white" : "border border-line text-ink-500"}`}>SAT</button>
        </div>
        <div className="mt-3">
          <div className="grid grid-cols-3 gap-1">
            {([ ["MARKET", "Piyasa"], ["LIMIT", "Limit"], ["STOP_LIMIT", "Stop-Limit"] ] as const).map(([value, label]) => (
              <button key={value} type="button" onClick={() => { setKind(value); setMessage(null); }} className={`rounded-lg px-2 py-1.5 text-xs ${kind === value ? "bg-accent text-white" : "border border-line text-ink-500"}`}>{label}</button>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-ink-400">Gerçek Binance TR hesabınıza emir gönderilir. Kabul edilmesi gerçekleştiği anlamına gelmez.</p>
        </div>

        <label className="mt-3 block">
          <span className="odak-kicker">{kind === "MARKET" && side === "BUY" ? `Harcanacak tutar (${quoteAsset})` : `Miktar (${base})`}</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="0" className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" />
        </label>
        {kind === "LIMIT" && <label className="mt-3 block"><span className="odak-kicker">Limit fiyatı ({quoteAsset})</span><input value={limitPrice} onChange={(e) => setLimitPrice(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder={tickerData?.last ? String(tickerData.last) : "0"} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" /></label>}
        {kind === "STOP_LIMIT" && <>
          <label className="mt-3 block"><span className="odak-kicker">Tetikleme fiyatı ({quoteAsset})</span><input value={stopPrice} onChange={(e) => setStopPrice(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="0" className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" /></label>
          <label className="mt-3 block"><span className="odak-kicker">Limit fiyatı ({quoteAsset})</span><input value={stopLimitPrice} onChange={(e) => setStopLimitPrice(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="0" className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" /></label>
        </>}
        {side === "BUY" && kind === "MARKET" && quoteAsset === "TRY" && (
          <div className="mt-2 grid grid-cols-4 gap-1">
            {[500, 1000, 2500, 5000].map((val) => (
              <button
                key={val}
                type="button"
                onClick={() => setAmount(String(val))}
                className={`rounded-md border py-1 text-[11px] font-mono transition-colors ${
                  amount === String(val)
                    ? "border-accent bg-accent-soft text-accent font-bold"
                    : "border-line bg-canvas/70 text-ink-600 hover:border-accent"
                }`}
              >
                ₺{val.toLocaleString("tr-TR")}
              </button>
            ))}
          </div>
        )}
        <div className="mt-2 grid grid-cols-4 gap-1.5">
          {[25, 50, 75, 100].map((pct) => <button key={pct} type="button" disabled={side === "BUY" ? quoteFree <= 0 || (kind !== "MARKET" && !priceForEstimate) : assetFree <= 0} onClick={() => {
            if (side === "SELL") setAmount((assetFree * pct / 100).toFixed(6));
            else if (kind === "MARKET") setAmount((quoteFree * pct / 100).toFixed(2));
            else setAmount((quoteFree * pct / 100 / Number(priceForEstimate)).toFixed(6));
          }} className="rounded-md border border-line py-1 text-[11px] text-ink-500 hover:border-accent hover:text-accent disabled:opacity-40">%{pct}</button>)}
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-ink-400">
          <span>{side === "BUY" && kind === "MARKET" ? `≈ ${approxBase != null ? `${approxBase.toFixed(6)} ${base}` : "—"}` : side === "SELL" ? `Satılabilir: ${assetFree || "—"} ${base}` : `Tahmini miktar: ${priceForEstimate && amount ? `${(Number(amount) / priceForEstimate).toFixed(6)} ${base}` : "—"}`}</span>
          <span>{quoteAsset} bakiye: {binance.data?.configured ? `${quoteFree.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} ${quoteAsset}` : "—"}</span>
        </div>
        <p className="mt-1 text-right text-[11px] text-ink-400">Tahmini tutar: {amount ? quoteAsset === "TRY" ? formatTL(estimatedQuote) : `${estimatedQuote.toLocaleString("tr-TR", { maximumFractionDigits: 4 })} USDT` : "—"}</p>

        <Button variant={side === "BUY" ? "success" : "danger"} className="mt-3 w-full" disabled={busy || !activeSymbol || !Number(amount) || !enabled || (kind === "LIMIT" && !Number(limitPrice)) || (kind === "STOP_LIMIT" && (!Number(stopPrice) || !Number(stopLimitPrice)))} onClick={openReview}
          title={!binance.data?.configured ? "Önce Ayarlar'dan Binance TR API anahtarını kaydet" : !binance.data?.sell_enabled ? "Ayarlar'da gerçek işlem kapısını aç" : `Gerçek Binance TR ${kind} emri gönder`}>
          {busy ? "Gönderiliyor…" : `${side === "BUY" ? "ALIM" : "SATIM"} ${kind === "STOP_LIMIT" ? "STOP-LIMIT" : kind === "LIMIT" ? "LİMİT" : "PİYASA"} EMRİNİ GÖZDEN GEÇİR`}
        </Button>
        {!binance.data?.configured && <p className="mt-2 text-center text-[11px] text-warn">Gerçek hesabı bağlamak için <Link href="/ayarlar" className="underline">Ayarlar</Link>'dan Binance TR API anahtarlarını kaydedin.</p>}
        {binance.data?.configured && !binance.data.sell_enabled && <p className="mt-2 text-center text-[11px] text-warn">Gerçek emir kapısı kapalı. Ayarlar'dan etkinleştirin.</p>}
        {message && <p role="status" className={`mt-2 text-center text-[11px] ${message.tone === "gain" ? "text-gain" : message.tone === "loss" ? "text-loss" : "text-ink-500"}`}>{message.text}</p>}
        {receipt && <div className="mt-3 rounded-lg border border-line bg-slate-50 p-3 text-[11px]">
          <div className="flex items-center justify-between gap-2"><span className="font-semibold text-ink-800">Emir: {orderStatusLabel(receipt.status)}</span>
            {receipt.clientId && !["FILLED", "CANCELED", "REJECTED", "EXPIRED"].includes(status || "") && <button type="button" disabled={refreshing} onClick={() => refreshOrderStatus()} className="shrink-0 rounded-md border border-line px-2 py-1 text-accent disabled:opacity-50">{refreshing ? "Sorgulanıyor…" : "Durumu sorgula"}</button>}
          </div>
          <div className="mt-1 space-y-0.5 text-ink-500">
            {receipt.orderId != null && <p>Borsa emir no: <span className="font-mono">{receipt.orderId}</span></p>}
            {receipt.clientId && <p>İstemci emir no: <span className="font-mono">{receipt.clientId}</span></p>}
            {receipt.executedQty != null && <p>Gerçekleşen miktar: <span className="font-mono">{receipt.executedQty} {base}</span></p>}
            {receipt.avgPrice != null && <p>Ortalama gerçekleşme fiyatı: <span className="font-mono">{formatPrice(Number(receipt.avgPrice))}</span></p>}
          </div>
        </div>}

        {binance.data?.configured && assetFree > 0 && (
          <div className="mt-3 rounded-xl border border-line p-3">
            <button type="button" onClick={() => setSltpOpen((open) => !open)} className="flex w-full items-center justify-between text-left" aria-expanded={sltpOpen}>
              <span className="odak-kicker">Pozisyon Koruması (SL / TP / OCO)</span>
              <span className="text-ink-400">{sltpOpen ? "▾" : "▸"}</span>
            </button>
            {sltpOpen && <>
              <p className="mt-1.5 text-[10px] text-ink-400">{assetFree} {base} için borsada bekleyen satış koruması kurulur. Otomatik trailing yalnızca paper motorunda çalışır; gerçek pozisyonda kâr büyüdükçe SL'i buradan elle yukarı taşıyın.</p>
              <div className="mt-2 grid grid-cols-3 gap-1">
                {([["OCO", "OCO (SL+TP)"], ["SL_ONLY", "Sadece SL"], ["TP_ONLY", "Sadece TP"]] as const).map(([value, label]) => (
                  <button key={value} type="button" onClick={() => { setSltpMode(value); setSltpConfirm(false); }} className={`rounded-lg px-1.5 py-1.5 text-[11px] font-semibold ${sltpMode === value ? "bg-accent text-white" : "border border-line text-ink-500"}`}>{label}</button>
                ))}
              </div>
              <div className="mt-2">
                <span className="odak-kicker">Kâr Al (TP) fiyatı</span>
                <input value={tpPrice} onChange={(e) => { setTpPrice(e.target.value.replace(/[^\d.]/g, "")); setSltpConfirm(false); }} inputMode="decimal" placeholder={currentPrice ? (currentPrice * 1.03).toFixed(priceDigits(currentPrice)) : "0"} disabled={sltpMode === "SL_ONLY"} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent disabled:opacity-40" />
                <div className="mt-1 grid grid-cols-4 gap-1">
                  {[2, 3, 5, 8].map((pct) => <button key={pct} type="button" disabled={!currentPrice || sltpMode === "SL_ONLY"} onClick={() => sltpPctFill("tp", pct)} className="rounded-md border border-line py-1 text-[11px] text-ink-500 hover:border-accent hover:text-accent disabled:opacity-40">%+{pct}</button>)}
                </div>
              </div>
              <div className="mt-2">
                <span className="odak-kicker">Zarar Kes (SL) fiyatı</span>
                <input value={slPrice} onChange={(e) => { setSlPrice(e.target.value.replace(/[^\d.]/g, "")); setSltpConfirm(false); }} inputMode="decimal" placeholder={currentPrice ? (currentPrice * 0.98).toFixed(priceDigits(currentPrice)) : "0"} disabled={sltpMode === "TP_ONLY"} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent disabled:opacity-40" />
                <div className="mt-1 grid grid-cols-4 gap-1">
                  {[-1, -2, -3, -5].map((pct) => <button key={pct} type="button" disabled={!currentPrice || sltpMode === "TP_ONLY"} onClick={() => sltpPctFill("sl", pct)} className="rounded-md border border-line py-1 text-[11px] text-ink-500 hover:border-loss hover:text-loss disabled:opacity-40">{pct}%</button>)}
                </div>
                {avgCost != null && avgCost > 0 && (
                  <button type="button" disabled={sltpMode === "TP_ONLY"} onClick={() => { setSlPrice(Number(avgCost).toFixed(priceDigits(Number(avgCost)))); setSltpConfirm(false); }} className="mt-1 w-full rounded-md border border-accent/40 bg-accent-soft py-1 text-[11px] font-semibold text-accent disabled:opacity-40" title="Stop'u maliyet fiyatına çek: kâr büyüdükçe sermayeyi kilitle">
                    ⟲ Başabaş çek (maliyet ≈ {formatPrice(avgCost)})
                  </button>
                )}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="block"><span className="odak-kicker">SL limit (ops.)</span><input value={slLimitPrice} onChange={(e) => setSlLimitPrice(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="—" className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 font-mono text-xs text-ink-900 outline-none focus:border-accent" /></label>
                <label className="block"><span className="odak-kicker">Miktar (boş = tümü)</span><input value={sltpQty} onChange={(e) => setSltpQty(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder={String(assetFree)} className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 font-mono text-xs text-ink-900 outline-none focus:border-accent" /></label>
              </div>
              <label className="mt-2 flex items-center gap-2 text-[11px] text-ink-500">
                <input type="checkbox" checked={cancelExisting} onChange={(e) => setCancelExisting(e.target.checked)} className="h-3.5 w-3.5 accent-[color:var(--color-accent)]" />
                Önceki açık satış emirlerini iptal et (gerekli olabilir)
              </label>
              {!sltpConfirm ? (
                <Button variant="danger" className="mt-2 w-full" disabled={sltpBusy || (sltpMode === "OCO" && (!Number(tpPrice) || !Number(slPrice))) || (sltpMode === "TP_ONLY" && !Number(tpPrice)) || (sltpMode === "SL_ONLY" && !Number(slPrice))} onClick={() => setSltpConfirm(true)}>
                  KORUMA EMRİNİ GÖZDEN GEÇİR
                </Button>
              ) : (
                <div className="mt-2 rounded-lg bg-slate-50 p-2.5 text-[11px]">
                  <p className="font-semibold text-ink-800">{sltpMode === "OCO" ? "OCO" : sltpMode === "SL_ONLY" ? "Zarar Kes (SL)" : "Kâr Al (TP)"} · {cancelExisting ? Number(sltpQty) > 0 ? sltpQty : `${assetFree} ${base} (tümü)` : `${Number(sltpQty) > 0 ? sltpQty : assetFree} ${base}`}</p>
                  <p className="mt-0.5 text-ink-500">TP {sltpMode === "SL_ONLY" ? "—" : formatPrice(Number(tpPrice || 0))} · SL {sltpMode === "TP_ONLY" ? "—" : formatPrice(Number(slPrice || 0))}{cancelExisting ? " · eski satış emirleri İPTAL edilecek" : ""}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <button type="button" onClick={() => setSltpConfirm(false)} className="rounded-lg border border-line px-3 py-2 font-semibold text-ink-600">Geri dön</button>
                    <Button variant="danger" disabled={sltpBusy} onClick={submitSltp}>{sltpBusy ? "Gönderiliyor…" : "Gerçek koruma emrini onayla"}</Button>
                  </div>
                </div>
              )}
              {sltpMessage && <p role="status" className={`mt-2 text-[11px] ${sltpMessage.tone === "gain" ? "text-gain" : sltpMessage.tone === "loss" ? "text-loss" : "text-ink-500"}`}>{sltpMessage.text}</p>}
            </>}
          </div>
        )}
      </>}
      {review && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReview(); }}>
        <section ref={reviewA11y.ref} tabIndex={-1} onKeyDown={reviewA11y.onKeyDown} role="dialog" aria-modal="true" aria-labelledby="order-review-title" aria-describedby="order-review-desc" className="w-full max-w-md rounded-2xl border border-line bg-white p-5 shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-4">
            <div><p className="odak-kicker">Gerçek Binance TR emri</p><h2 id="order-review-title" className="mt-1 text-lg font-bold text-ink-900">Emri onayla</h2></div>
            <button type="button" disabled={busy} onClick={closeReview} className="rounded-md px-2 py-1 text-ink-500 hover:bg-slate-100 disabled:opacity-50" aria-label="Onay penceresini kapat">✕</button>
          </div>
          <p id="order-review-desc" className="mt-2 text-sm text-ink-500">Onayladığınızda emir gerçek hesabınıza gönderilir. Gönderim kabul edilmesi dolum garantisi vermez. Aşağıdaki değerler pencere açıldığı anda donduruldu.</p>
          <dl className="mt-4 space-y-2 rounded-xl bg-slate-50 p-3 text-sm">
            <div className="flex justify-between gap-3"><dt className="text-ink-500">Sembol</dt><dd className="font-semibold text-ink-900">{review.symbol}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-500">Yön</dt><dd className={`font-semibold ${review.side === "BUY" ? "text-gain" : "text-loss"}`}>{review.side === "BUY" ? "ALIM" : "SATIM"}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-500">Emir türü</dt><dd className="font-semibold text-ink-900">{review.kind === "STOP_LIMIT" ? "Stop-Limit" : review.kind === "LIMIT" ? "Limit" : "Piyasa"}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-500">{review.kind === "MARKET" && review.side === "BUY" ? "Harcanacak tutar" : "Miktar"}</dt><dd className="font-mono font-semibold text-ink-900">{review.amount.toLocaleString("tr-TR", { maximumFractionDigits: 8 })} {review.kind === "MARKET" && review.side === "BUY" ? review.quoteAsset : review.base}</dd></div>
            {review.kind === "LIMIT" && <div className="flex justify-between gap-3"><dt className="text-ink-500">Limit fiyatı</dt><dd className="font-mono font-semibold text-ink-900">{Number(review.limitPrice || 0).toLocaleString("tr-TR", { maximumFractionDigits: 8 })} {review.quoteAsset}</dd></div>}
            {review.kind === "STOP_LIMIT" && <>
              <div className="flex justify-between gap-3"><dt className="text-ink-500">Tetikleme fiyatı</dt><dd className="font-mono font-semibold text-ink-900">{Number(review.stopPrice || 0).toLocaleString("tr-TR", { maximumFractionDigits: 8 })} {review.quoteAsset}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-500">Limit fiyatı</dt><dd className="font-mono font-semibold text-ink-900">{Number(review.stopLimitPrice || 0).toLocaleString("tr-TR", { maximumFractionDigits: 8 })} {review.quoteAsset}</dd></div>
            </>}
            {review.kind === "MARKET" && <div className="flex justify-between gap-3"><dt className="text-ink-500">Referans fiyat (onay anı)</dt><dd className="font-mono text-ink-700">{review.referencePrice != null ? formatPrice(review.referencePrice) : "—"}</dd></div>}
            <div className="flex justify-between gap-3 border-t border-line pt-2"><dt className="text-ink-500">Yaklaşık emir tutarı</dt><dd className="font-mono font-semibold text-ink-900">{review.quoteAsset === "TRY" ? formatTL(review.estimatedQuote) : `${review.estimatedQuote.toLocaleString("tr-TR", { maximumFractionDigits: 4 })} USDT`}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-500">İstemci emir no</dt><dd className="font-mono text-[11px] text-ink-500">{review.clientOrderId}</dd></div>
          </dl>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button type="button" disabled={busy} onClick={closeReview} className="rounded-lg border border-line px-3 py-2 text-sm font-semibold text-ink-600 disabled:opacity-50">Geri dön</button>
            <Button variant={review.side === "BUY" ? "success" : "danger"} disabled={busy} onClick={submitOrder}>{busy ? "Gönderiliyor…" : "Gerçek emri onayla"}</Button>
          </div>
        </section>
      </div>}
    </Card>
  );
}
