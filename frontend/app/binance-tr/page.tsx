"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { API_BASE, apiRequest } from "../lib/api";
import { localDateInput } from "../lib/format";
import { useLiveMessages } from "../lib/liveSocket";
import { commissionPct } from "../lib/pnl";
import { useAuth } from "../lib/auth";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import Link from "next/link";

const BinancePositionChartModal = dynamic(() => import("./BinancePositionChartModal"), { ssr: false });

type Balance = { asset: string; free: string; locked: string };

type LiveTick = { price?: number; symbol?: string; quote_volume_try?: number | null };

type OpenOrder = {
  orderId: number;
  symbol: string;
  side: string;
  type: string;
  price: string;
  stopPrice: string;
  origQty: string;
  executedQty: string;
  status: string;
  time: number;
  orderListId: number;
  clientOrderId: string;
};

type Holding = {
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
  active_orders?: OpenOrder[];
};

type Trade = {
  id: number;
  symbol: string;
  price: string;
  qty: string;
  quoteQty: string;
  commission: string;
  time: number;
  isBuyer: boolean;
  basis_price?: number;
  realized_pnl_try?: number;
};

type DailyPnl = {
  realized_pnl_try: number;
  gross_pnl_try: number;
  wins: number;
  losses: number;
  unmatched: number;
};

type SymbolSummary = {
  symbol: string;
  buy_qty: number;
  buy_cost_try: number;
  sell_qty: number;
  sell_revenue_try: number;
  realized_pnl_try: number;
  commission_try: number;
  fills: number;
};

const fmtVolume = (v: number | null | undefined) => {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const fmt = (d: number) => n.toLocaleString("tr-TR", { minimumFractionDigits: 0, maximumFractionDigits: d });
  if (n >= 1e9) return fmt(1) + "B";
  if (n >= 1e6) return fmt(1) + "M";
  if (n >= 1e3) return fmt(0) + "K";
  return fmt(0);
};

const fmtPrice = (v: string | number | null | undefined, d = 2) => {
  const n = typeof v === "string" ? parseFloat(v) : Number(v ?? 0);
  return Number.isFinite(n)
    ? n.toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d })
    : "0,00";
};

const fmtTime = (ts: number | null | undefined) => {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

export default function BinanceTrPage() {
  const { username } = useAuth();
  if (!username) {
    return (
      <main className="page-shell">
        <div className="card mt-10 flex flex-col items-center gap-4 border-cyan-500/30 bg-cyan-500/5 px-6 py-12 text-center">
          <p className="eyebrow">OTURUM GEREKLİ</p>
          <h1 className="font-mono text-xl font-bold text-white">Binance TR Terminali için giriş yapın</h1>
          <p className="max-w-md text-sm text-bunker-muted">
            Her kullanıcı kendi Binance TR API anahtarlarıyla kendi hesabında işlem yapar. Giriş yaptıktan sonra anahtarlarınızı Ayarlar'dan bağlayabilirsiniz.
          </p>
          <Link href="/" className="ui-button ui-button-primary">ANA SAYFAYA DÖN</Link>
        </div>
      </main>
    );
  }
  return <BinanceTrPageInner />;
}

function BinanceTrPageInner() {
  const { role } = useAuth();
  // Sistem Ayarları & API
  const [configured, setConfigured] = useState(false);
  const [sellEnabled, setSellEnabled] = useState(false);
  const [sellToggle, setSellToggle] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [keyError, setKeyError] = useState("");

  // Aktif Sekme (positions | openOrders | trades)
  const [activeTab, setActiveTab] = useState<"positions" | "openOrders" | "trades">("positions");

  // Trade Defteri sıralama (kullanıcı tercihi 2026-09-19): sütun başlığına
  // tıkla → asc; tekrar tıkla → desc; başka sütuna tıkla → o sütun asc.
  type TradesSortKey = "symbol" | "buy_qty" | "buy_avg" | "sell_qty" | "sell_avg" | "commission" | "pnl" | "fills";
  type SortDir = "asc" | "desc";
  const [tradesSort, setTradesSort] = useState<{ key: TradesSortKey; dir: SortDir }>({ key: "pnl", dir: "desc" });
  const toggleTradesSort = (key: TradesSortKey) =>
    setTradesSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));

  // Hesap & Bakiye
  const [balances, setBalances] = useState<Balance[]>([]);
  const [acctLoading, setAcctLoading] = useState(false);
  const [acctError, setAcctError] = useState("");

  // Pozisyonlar (Holdings)
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [ordLoading, setOrdLoading] = useState(false);
  const [hideSmall, setHideSmall] = useState(true);
  const [searchFilter, setSearchFilter] = useState("");
  const [positionFilter, setPositionFilter] = useState<"all" | "unprotected" | "profit" | "loss">("all");

  // Açık Emirler (Open Orders)
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [openOrdersLoading, setOpenOrdersLoading] = useState(false);
  const [cancellingOrderId, setCancellingOrderId] = useState<number | null>(null);

  // Satış Modalı (Market Sell)
  const [sellFor, setSellFor] = useState<Holding | null>(null);
  const [sellQty, setSellQty] = useState("");
  const [sellBusy, setSellBusy] = useState(false);
  const [sellMsg, setSellMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [sellDone, setSellDone] = useState<{ order: string; asset: string; qty: string; price: string; total: string } | null>(null);

  // Alım Modalı (Market Buy)
  const [buyOpen, setBuyOpen] = useState(false);
  const [buyInput, setBuyInput] = useState("");
  const [buyAsset, setBuyAsset] = useState("");
  const [buyAmount, setBuyAmount] = useState("100");
  const [buyBusy, setBuyBusy] = useState(false);
  const [buyMsg, setBuyMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [buyDone, setBuyDone] = useState<{ order: string; asset: string; qty: string; price: string } | null>(null);
  // ADMIN İŞLEM BİLDİRİMİ: seçiliyse emir sonrası Bildirim Ayarları'ndaki
  // kullanıcılara "{sembol} {fiyat} pozisyon açıldı" push'u gider.
  const [buyNotify, setBuyNotify] = useState(false);
  const [pairs, setPairs] = useState<string[]>([]);
  const buyAssetRef = useRef("");

  // SL / TP & OCO Modalı
  const [sltpModalOpen, setSltpModalOpen] = useState(false);
  const [sltpTarget, setSltpTarget] = useState<Holding | null>(null);
  const [sltpMode, setSltpMode] = useState<"OCO" | "SL_ONLY" | "TP_ONLY">("OCO");
  const [sltpQty, setSltpQty] = useState("");
  const [sltpTpPrice, setSltpTpPrice] = useState("");
  const [sltpSlPrice, setSltpSlPrice] = useState("");
  const [sltpSlLimitPrice, setSltpSlLimitPrice] = useState("");
  const [sltpCancelExisting, setSltpCancelExisting] = useState(true);
  const [sltpBusy, setSltpBusy] = useState(false);
  const [sltpMsg, setSltpMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // İnteraktif Pozisyon Grafik Modalı
  const [chartFor, setChartFor] = useState<Holding | null>(null);

  // Toast Bildirim Sistemi
  const [toast, setToast] = useState<{ id: number; text: string; type: "success" | "error" | "info" } | null>(null);

  const showToast = (text: string, type: "success" | "error" | "info" = "success") => {
    setToast({ id: Date.now(), text, type });
    setTimeout(() => {
      setToast((prev) => (prev?.text === text ? null : prev));
    }, 4500);
  };

  // Geçmiş İşlemler
  const [tradeDay, setTradeDay] = useState(() => localDateInput());
  const [trades, setTrades] = useState<Trade[]>([]);
  const [symbolSummary, setSymbolSummary] = useState<SymbolSummary[]>([]);
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [daily, setDaily] = useState<DailyPnl | null>(null);
  const [trLoading, setTrLoading] = useState(false);
  const [trMeta, setTrMeta] = useState<{ count: number; symbols_scanned: number } | null>(null);

  // Canlı WS Fiyat Akışı (Throttled + Tab-Visibility Aware)
  const [liveTicks, setLiveTicks] = useState<Record<string, LiveTick>>({});
  const [tickDir, setTickDir] = useState<Record<string, "up" | "down">>({});
  const pricesRef = useRef<Record<string, number>>({});
  const pendingTicksRef = useRef<{ ticks: Record<string, LiveTick>; dirs: Record<string, "up" | "down"> } | null>(null);
  const throttleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushTicks = useCallback(() => {
    if (throttleTimerRef.current) {
      clearTimeout(throttleTimerRef.current);
      throttleTimerRef.current = null;
    }
    const pending = pendingTicksRef.current;
    if (!pending) return;
    pendingTicksRef.current = null;
    setLiveTicks(pending.ticks);
    if (Object.keys(pending.dirs).length) setTickDir((prev) => ({ ...prev, ...pending.dirs }));
  }, []);

  useLiveMessages((message) => {
    if (message?.type !== "binance_price") return;
    const d = message.data as { ticks?: Record<string, LiveTick>; time?: number } | null;
    if (!d?.ticks) return;
    const dirs: Record<string, "up" | "down"> = {};
    for (const [asset, t] of Object.entries(d.ticks)) {
      const price = Number(t.price || 0);
      if (!price) continue;
      const old = pricesRef.current[asset];
      if (old) dirs[asset] = price >= old ? "up" : "down";
      pricesRef.current[asset] = price;
    }
    const prevPending = pendingTicksRef.current;
    pendingTicksRef.current = {
      ticks: { ...(prevPending?.ticks || {}), ...d.ticks },
      dirs: { ...(prevPending?.dirs || {}), ...dirs },
    };

    if (typeof document !== "undefined" && document.hidden) {
      return;
    }

    if (!throttleTimerRef.current) {
      throttleTimerRef.current = setTimeout(flushTicks, 120);
    }
  });

  useEffect(() => {
    const onVisibility = () => {
      if (typeof document !== "undefined" && !document.hidden) {
        flushTicks();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      if (throttleTimerRef.current) clearTimeout(throttleTimerRef.current);
    };
  }, [flushTicks]);

  const check = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setConfigured(Boolean(d.configured));
        setSellEnabled(Boolean(d.sell_enabled));
        setSellToggle(Boolean(d.sell_enabled));
      } else if (r.status === 404) {
        // Anahtar hiç bağlı değil → onboarding ekranına düş (hata gösterme).
        setConfigured(false);
        setSellEnabled(false);
      }
    } catch { /* */ }
  }, []);

  useEffect(() => { check(); }, [check]);

  const loadAcct = useCallback(async () => {
    setAcctLoading(true);
    setAcctError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/account`, { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        throw new Error(d.detail || "Hesap bilgisi alınamadı");
      }
      setBalances(d.balances || []);
    } catch (e) {
      setAcctError(e instanceof Error ? e.message : "Hesap bilgisi alınamadı");
    } finally {
      setAcctLoading(false);
    }
  }, []);

  const loadOrd = useCallback(async () => {
    setOrdLoading(true);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/positions`, { cache: "no-store" });
      if (r.ok) setHoldings((await r.json()).holdings || []);
    } catch { /* */ }
    finally { setOrdLoading(false); }
  }, []);

  const loadOpenOrders = useCallback(async () => {
    setOpenOrdersLoading(true);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/open-orders`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setOpenOrders(d.orders || []);
      }
    } catch { /* */ }
    finally { setOpenOrdersLoading(false); }
  }, []);

  const loadTrades = useCallback(async () => {
    setTrLoading(true);
    try {
      const r = await apiRequest(
        `${API_BASE}/api/binance/trades-day?date=${encodeURIComponent(tradeDay)}`,
        { cache: "no-store" }
      );
      if (r.ok) {
        const d = await r.json();
        setTrades(d.trades || []);
        setSymbolSummary((d.symbol_summary || []) as SymbolSummary[]);
        setDaily(d.daily || null);
        setTrMeta({ count: d.count || 0, symbols_scanned: d.symbols_scanned || 0 });
      }
    } catch { /* */ }
    finally { setTrLoading(false); }
  }, [tradeDay]);

  const refreshAccountData = useCallback(() => {
    if (!configured) return;
    loadAcct();
    loadOrd();
    loadOpenOrders();
  }, [configured, loadAcct, loadOrd, loadOpenOrders]);

  useEffect(() => {
    if (!configured) return;
    refreshAccountData();
  }, [configured, refreshAccountData]);

  useVisibleInterval(refreshAccountData, configured ? 10_000 : null);
  useVisibleInterval(loadTrades, configured && tradeDay ? 20_000 : null);

  useEffect(() => {
    if (configured && tradeDay) loadTrades();
  }, [configured, tradeDay, loadTrades]);

  // Canlı fiyatlarla birleştirilmiş holding listesi
  const mergedHoldings = useMemo(() => {
    return holdings.map((h) => {
      const t = liveTicks[h.asset];
      const price = h.asset === "TRY" ? 1.0 : Number(t?.price || 0);
      if (!price) return { ...h, volume_try: t?.quote_volume_try ?? null };
      const cost = h.avg_cost_try;
      const pnl_try = cost ? (price - cost) * h.total : h.pnl_try;
      const pnl_pct = cost ? ((price - cost) / cost) * 100 : h.pnl_pct;
      return {
        ...h,
        price_try: price,
        value_try: h.total * price,
        pnl_try,
        pnl_pct,
        volume_try: t?.quote_volume_try ?? null,
      };
    });
  }, [holdings, liveTicks]);

  // Filtrelenmiş Pozisyonlar
  const visibleHoldings = useMemo(() => {
    return mergedHoldings.filter((h) => {
      if (hideSmall && h.value_try != null && h.value_try < 50) return false;
      if (searchFilter.trim()) {
        const q = searchFilter.trim().toUpperCase();
        if (!h.asset.includes(q)) return false;
      }
      if (positionFilter === "unprotected") {
        if (h.asset === "TRY" || h.has_active_order || (h.active_sl_price != null && h.active_sl_price > 0)) {
          return false;
        }
      } else if (positionFilter === "profit") {
        if ((h.pnl_try ?? 0) <= 0) return false;
      } else if (positionFilter === "loss") {
        if ((h.pnl_try ?? 0) >= 0) return false;
      }
      return true;
    });
  }, [mergedHoldings, hideSmall, searchFilter, positionFilter]);

  // Üst Metrikler (KPIs)
  const totalValueTry = useMemo(() => {
    return mergedHoldings.reduce((sum, h) => sum + (h.value_try || 0), 0);
  }, [mergedHoldings]);

  const totalUnrealizedPnlTry = useMemo(() => {
    return mergedHoldings.reduce((sum, h) => sum + (h.pnl_try || 0), 0);
  }, [mergedHoldings]);

  const tryFreeBalance = useMemo(() => {
    const r = balances.find((b) => b.asset === "TRY");
    return parseFloat(r?.free || "0");
  }, [balances]);

  const usdtFreeBalance = useMemo(() => {
    const r = balances.find((b) => b.asset === "USDT");
    return parseFloat(r?.free || "0");
  }, [balances]);

  const protectedCount = useMemo(() => {
    return mergedHoldings.filter((h) => h.asset !== "TRY" && (h.has_active_order || (h.active_sl_price != null && h.active_sl_price > 0))).length;
  }, [mergedHoldings]);

  const totalCoinPositions = useMemo(() => {
    return mergedHoldings.filter((h) => h.asset !== "TRY" && (h.value_try == null || h.value_try >= 10)).length;
  }, [mergedHoldings]);

  // Trade Defteri sıralı özet satırları (kullanıcı tercihi 2026-09-19).
  const sortedSymbolSummary = useMemo(() => {
    const buyAvgOf = (s: SymbolSummary) => (s.buy_qty > 0 ? s.buy_cost_try / s.buy_qty : 0);
    const sellAvgOf = (s: SymbolSummary) => (s.sell_qty > 0 ? s.sell_revenue_try / s.sell_qty : 0);
    const val = (s: SymbolSummary): number | string => {
      switch (tradesSort.key) {
        case "symbol": return s.symbol;
        case "buy_qty": return s.buy_qty;
        case "buy_avg": return buyAvgOf(s);
        case "sell_qty": return s.sell_qty;
        case "sell_avg": return sellAvgOf(s);
        case "commission": return s.commission_try;
        case "pnl": return s.realized_pnl_try;
        case "fills": return s.fills;
      }
    };
    const dir = tradesSort.dir === "asc" ? 1 : -1;
    return [...symbolSummary].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (typeof va === "string" || typeof vb === "string") {
        return dir * String(va).localeCompare(String(vb), "tr");
      }
      return dir * ((va as number) - (vb as number));
    });
  }, [symbolSummary, tradesSort]);

  // Alım Modalı Hesaplamaları
  const buyTryFree = tryFreeBalance;
  const buyAmountNum = useMemo(() => {
    const n = parseFloat(buyAmount.replace(",", "."));
    return Number.isFinite(n) ? Math.min(Math.max(n, 0), buyTryFree) : 0;
  }, [buyAmount, buyTryFree]);

  const buyMatches = useMemo(() => {
    const q = buyInput.trim().toUpperCase();
    if (q.length < 2) return [];
    return pairs.filter((p) => (p + "TRY").includes(q)).slice(0, 8);
  }, [buyInput, pairs]);

  const buyPrice = buyAsset
    ? Number(liveTicks[buyAsset]?.price || mergedHoldings.find((x) => x.asset === buyAsset)?.price_try || 0)
    : 0;

  // Satış Modalı Hesaplamaları
  const sellQtyNum = useMemo(() => {
    if (!sellFor) return 0;
    const n = parseFloat(sellQty.replace(",", "."));
    return Number.isFinite(n) ? Math.min(Math.max(n, 0), sellFor.free) : 0;
  }, [sellQty, sellFor]);

  // SL/TP Modalı Dinamik Hesaplamaları
  const currentTargetPrice = useMemo(() => {
    if (!sltpTarget) return 0;
    return Number(liveTicks[sltpTarget.asset]?.price || sltpTarget.price_try || 0);
  }, [sltpTarget, liveTicks]);

  const sltpQtyNum = useMemo(() => {
    if (!sltpTarget) return 0;
    const n = parseFloat(sltpQty.replace(",", "."));
    const maxQty = sltpTarget.total; // Kilitli olanları da güncelleyebileceği için total
    return Number.isFinite(n) ? Math.min(Math.max(n, 0), maxQty) : 0;
  }, [sltpQty, sltpTarget]);

  const calculatedTpProfit = useMemo(() => {
    const tp = parseFloat(sltpTpPrice.replace(",", "."));
    if (!Number.isFinite(tp) || tp <= 0 || !currentTargetPrice || !sltpQtyNum) return null;
    const cost = sltpTarget?.avg_cost_try || currentTargetPrice;
    const diff = tp - cost;
    const totalDiff = diff * sltpQtyNum;
    const pct = ((tp - cost) / cost) * 100;
    return { totalDiff, pct };
  }, [sltpTpPrice, currentTargetPrice, sltpQtyNum, sltpTarget]);

  const calculatedSlLoss = useMemo(() => {
    const sl = parseFloat(sltpSlPrice.replace(",", "."));
    if (!Number.isFinite(sl) || sl <= 0 || !currentTargetPrice || !sltpQtyNum) return null;
    const cost = sltpTarget?.avg_cost_try || currentTargetPrice;
    const diff = sl - cost;
    const totalDiff = diff * sltpQtyNum;
    const pct = ((sl - cost) / cost) * 100;
    return { totalDiff, pct };
  }, [sltpSlPrice, currentTargetPrice, sltpQtyNum, sltpTarget]);

  const calculatedRrRatio = useMemo(() => {
    if (!calculatedTpProfit || !calculatedSlLoss) return null;
    const risk = Math.abs(calculatedSlLoss.totalDiff);
    const reward = calculatedTpProfit.totalDiff;
    if (risk <= 0 || reward <= 0) return null;
    return (reward / risk).toFixed(2);
  }, [calculatedTpProfit, calculatedSlLoss]);

  // ---- Aksiyonlar: Ayarları Kaydet ----
  const saveKeys = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) return;
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim(), real_sell_enabled: sellToggle }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Kaydedilemedi");
      }
      setApiKey("");
      setApiSecret("");
      setConfigured(true);
      setSettingsOpen(false);
      showToast("Binance TR API anahtarları kaydedildi.", "success");
      check();
      loadAcct();
      loadOrd();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayıt hatası");
    } finally {
      setSaving(false);
    }
  };

  // Onboarding tek tık: anahtarlar doluyken kaydet + gerçek emri aç.
  const saveKeysWithRealSell = async (realSell: boolean) => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      // Anahtarlar boş → normal modalı aç (kullanıcı girebilsin)
      setSellToggle(realSell);
      setSettingsOpen(true);
      return;
    }
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim(), real_sell_enabled: realSell }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Kaydedilemedi");
      }
      setApiKey("");
      setApiSecret("");
      setConfigured(true);
      showToast(realSell ? "Hesap bağlandı, gerçek emir gönderimi AÇIK." : "Hesap bağlandı.", "success");
      check();
      loadAcct();
      loadOrd();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayıt hatası");
      setSellToggle(realSell);
      setSettingsOpen(true);
    } finally {
      setSaving(false);
    }
  };

  const saveSellSetting = async () => {
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ real_sell_enabled: sellToggle }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Kaydedilemedi");
      }
      await check();
      setSettingsOpen(false);
      showToast(`Gerçek işlem durumu: ${sellToggle ? "AÇIK" : "KAPALI"} olarak güncellendi.`);
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayıt hatası");
    } finally {
      setSaving(false);
    }
  };

  // ---- Aksiyonlar: Piyasa Alım (Buy) ----
  const openBuy = async () => {
    setBuyOpen(true);
    setBuyMsg(null);
    setBuyDone(null);
    setBuyInput("");
    setBuyAsset("");
    setBuyAmount("100");
    try {
      const r = await apiRequest(`${API_BASE}/api/market-symbols`);
      const d = await r.json().catch(() => ({}));
      const list = (Array.isArray(d.symbols) ? d.symbols : [])
        .map((s: string) => String(s).toUpperCase().replace(/TRY$/, ""))
        .filter((s: string) => s && s !== "TRY");
      setPairs(Array.from(new Set(list)));
    } catch { /* */ }
  };

  const selectBuyAsset = async (asset: string) => {
    setBuyAsset(asset);
    setBuyInput(asset);
    setBuyMsg(null);
    buyAssetRef.current = asset;
    try {
      await apiRequest(`${API_BASE}/api/binance/watch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: asset }),
      });
    } catch { /* */ }
  };

  const confirmBuy = async () => {
    if (buyBusy) return;
    const asset = buyAsset || buyInput.trim().toUpperCase().replace(/TRY$/, "");
    if (!asset) {
      setBuyMsg({ ok: false, text: "Önce işlem çiftini seçin." });
      return;
    }
    if (!Number.isFinite(buyAmountNum) || buyAmountNum < 10) {
      setBuyMsg({ ok: false, text: "Tutar geçerli değil (minimum ₺10)." });
      return;
    }
    if (buyAmountNum > buyTryFree + 1e-9) {
      setBuyMsg({ ok: false, text: `TRY bakiyesi yetersiz (boşta ₺${fmtPrice(buyTryFree)}).` });
      return;
    }
    setBuyBusy(true);
    setBuyMsg(null);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset, amount_try: buyAmountNum, confirmation: "REAL_BUY", notify: buyNotify }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || `Alım emri gönderilemedi (HTTP ${r.status})`);
      const qty = d.executed_qty != null ? fmtPrice(d.executed_qty, 6) : buyPrice ? fmtPrice(buyAmountNum / buyPrice, 6) : "—";
      const price = d.avg_price != null ? fmtPrice(d.avg_price, d.avg_price < 1 ? 6 : 2) : buyPrice ? fmtPrice(buyPrice, buyPrice < 1 ? 6 : 2) : "—";
      setBuyDone({ order: d.order_id ?? "—", asset, qty, price });
      showToast(`${asset} piyasa alımı başarıyla gerçekleşti!`, "success");
      loadAcct();
      loadOrd();
      loadTrades();
    } catch (e) {
      setBuyMsg({ ok: false, text: e instanceof Error ? e.message : "Alım emri gönderilemedi" });
    } finally {
      setBuyBusy(false);
    }
  };

  // ---- Aksiyonlar: Piyasa Satış (Sell) ----
  const openSell = (h: Holding) => {
    setSellFor(h);
    setSellQty(String(h.free));
    setSellMsg(null);
    setSellDone(null);
  };

  const confirmSell = async () => {
    if (!sellFor || sellBusy) return;
    const qty = parseFloat(sellQty.replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      setSellMsg({ ok: false, text: "Geçerli bir miktar girin." });
      return;
    }
    if (qty > sellFor.free + 1e-12) {
      setSellMsg({ ok: false, text: "Miktar boşta olan bakiyeden büyük olamaz." });
      return;
    }
    setSellBusy(true);
    setSellMsg(null);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/sell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset: sellFor.asset, quantity: qty, confirmation: "REAL_SELL" }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || `Satış emri gönderilemedi (HTTP ${r.status})`);
      const donePrice = sellFor.price_try ?? 0;
      setSellDone({
        order: d.order_id ?? "—",
        asset: sellFor.asset,
        qty: fmtPrice(qty, 6),
        price: donePrice ? fmtPrice(donePrice, donePrice < 1 ? 6 : 2) : "—",
        total: donePrice ? fmtPrice(qty * donePrice) : "—",
      });
      showToast(`${sellFor.asset} satış emri tamamlandı.`, "success");
      loadAcct();
      loadOrd();
      loadTrades();
    } catch (e) {
      setSellMsg({ ok: false, text: e instanceof Error ? e.message : "Satış emri gönderilemedi" });
    } finally {
      setSellBusy(false);
    }
  };

  // ---- Aksiyonlar: SL / TP Modalı ----
  const openSltpModal = (h: Holding) => {
    setSltpTarget(h);
    setSltpMode("OCO");
    setSltpMsg(null);
    const availableQty = h.free > 0 ? h.free : h.total;
    setSltpQty(String(availableQty));

    const curPrice = Number(liveTicks[h.asset]?.price || h.price_try || 0);

    if (h.active_tp_price) {
      setSltpTpPrice(String(h.active_tp_price));
    } else if (curPrice > 0) {
      setSltpTpPrice(fmtPrice(curPrice * 1.05, curPrice < 1 ? 6 : 2).replace(/\./g, "").replace(",", "."));
    } else {
      setSltpTpPrice("");
    }

    if (h.active_sl_price) {
      setSltpSlPrice(String(h.active_sl_price));
      setSltpSlLimitPrice(String(Number(h.active_sl_price * 0.995).toFixed(curPrice < 1 ? 6 : 2)));
    } else if (curPrice > 0) {
      const sl = curPrice * 0.97;
      setSltpSlPrice(fmtPrice(sl, curPrice < 1 ? 6 : 2).replace(/\./g, "").replace(",", "."));
      setSltpSlLimitPrice(fmtPrice(sl * 0.995, curPrice < 1 ? 6 : 2).replace(/\./g, "").replace(",", "."));
    } else {
      setSltpSlPrice("");
      setSltpSlLimitPrice("");
    }

    setSltpCancelExisting(true);
    setSltpModalOpen(true);
  };

  const applyTpPct = (pct: number) => {
    if (!currentTargetPrice) return;
    const target = currentTargetPrice * (1 + pct / 100);
    setSltpTpPrice(target.toFixed(currentTargetPrice < 1 ? 6 : 2));
  };

  const applySlPct = (pct: number) => {
    if (!currentTargetPrice) return;
    const target = currentTargetPrice * (1 - Math.abs(pct) / 100);
    setSltpSlPrice(target.toFixed(currentTargetPrice < 1 ? 6 : 2));
    setSltpSlLimitPrice((target * 0.995).toFixed(currentTargetPrice < 1 ? 6 : 2));
  };

  const applyBreakEven = () => {
    if (!sltpTarget) return;
    const entryPrice = Number(sltpTarget.avg_cost_try || 0);
    const curPrice = Number(currentTargetPrice || liveTicks[sltpTarget.asset]?.price || sltpTarget.price_try || 0);

    if (!entryPrice || entryPrice <= 0) {
      setSltpMsg({ ok: false, text: "Break-Even hesaplanamadı: Alış maliyeti (giriş fiyatı) bulunamadı." });
      return;
    }

    if (curPrice <= entryPrice) {
      setSltpMsg({
        ok: false,
        text: `Fiyat henüz kâra geçmedi. Güncel: ₺${fmtPrice(curPrice)}, Alış Maliyeti: ₺${fmtPrice(entryPrice)}`,
      });
      return;
    }

    // Komisyon oranı (gidiş-dönüş: 2 * komisyon) + %0.05 net kâr kilidi
    const commRate = 2 * commissionPct();
    const profitBuffer = 0.05 / 100;
    const bePrice = entryPrice * (1 + commRate + profitBuffer);

    if (bePrice >= curPrice) {
      setSltpMsg({
        ok: false,
        text: `Fiyat kârda ancak kâr kilidi seviyesinin (₺${fmtPrice(bePrice)}) altında. Güncel fiyatın biraz daha yükselmesi gerekiyor.`,
      });
      return;
    }

    const precision = curPrice < 1 ? 6 : 2;
    const slStr = bePrice.toFixed(precision);
    const slLimitStr = (bePrice * 0.995).toFixed(precision);

    setSltpSlPrice(slStr);
    setSltpSlLimitPrice(slLimitStr);
    setSltpMsg({
      ok: true,
      text: `🔒 Break-Even kâr kilidi ayarlandı: ₺${fmtPrice(bePrice)} (Maliyet: ₺${fmtPrice(entryPrice)} + Komisyon: %${(commRate * 100).toFixed(2)} + Net Kâr: %0.05)`,
    });
  };

  const applyQtyPct = (pct: number) => {
    if (!sltpTarget) return;
    const base = sltpTarget.free > 0 ? sltpTarget.free : sltpTarget.total;
    const q = (base * pct) / 100;
    setSltpQty(q.toFixed(6));
  };

  const confirmSltp = async () => {
    if (!sltpTarget || sltpBusy) return;
    if (!sltpQtyNum || sltpQtyNum <= 0) {
      setSltpMsg({ ok: false, text: "Geçerli bir miktar girin." });
      return;
    }
    const tp = parseFloat(sltpTpPrice.replace(",", "."));
    const sl = parseFloat(sltpSlPrice.replace(",", "."));
    const slLimit = parseFloat(sltpSlLimitPrice.replace(",", "."));

    if (sltpMode === "OCO") {
      if (!Number.isFinite(tp) || tp <= 0) {
        setSltpMsg({ ok: false, text: "Geçerli bir Kâr Al (TP) hedef fiyatı girin." });
        return;
      }
      if (!Number.isFinite(sl) || sl <= 0) {
        setSltpMsg({ ok: false, text: "Geçerli bir Zarar Kes (SL) fiyatı girin." });
        return;
      }
      if (tp <= sl) {
        setSltpMsg({ ok: false, text: "Kâr Al hedef fiyatı Zarar Kes fiyatından büyük olmalıdır." });
        return;
      }
    } else if (sltpMode === "SL_ONLY") {
      if (!Number.isFinite(sl) || sl <= 0) {
        setSltpMsg({ ok: false, text: "Geçerli bir Zarar Kes (SL) fiyatı girin." });
        return;
      }
    } else if (sltpMode === "TP_ONLY") {
      if (!Number.isFinite(tp) || tp <= 0) {
        setSltpMsg({ ok: false, text: "Geçerli bir Kâr Al (TP) fiyatı girin." });
        return;
      }
    }

    setSltpBusy(true);
    setSltpMsg(null);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/set-sl-tp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset: sltpTarget.asset,
          mode: sltpMode,
          quantity: sltpQtyNum,
          tp_price: tp,
          sl_price: sl,
          sl_limit_price: Number.isFinite(slLimit) && slLimit > 0 ? slLimit : undefined,
          cancel_existing: sltpCancelExisting,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || `Emir oluşturulamadı (HTTP ${r.status})`);
      showToast(`${sltpTarget.asset} için ${sltpMode} emri başarıyla kuruldu!`, "success");
      setSltpModalOpen(false);
      loadAcct();
      loadOrd();
      loadOpenOrders();
    } catch (e) {
      setSltpMsg({ ok: false, text: e instanceof Error ? e.message : "Emir gönderilemedi" });
    } finally {
      setSltpBusy(false);
    }
  };

  // ---- Aksiyonlar: Emir İptal ----
  const handleCancelOrder = async (orderId: number, symbol: string) => {
    if (cancellingOrderId !== null) return;
    setCancellingOrderId(orderId);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/cancel-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order_id: orderId, symbol }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || "Emir iptal edilemedi");
      showToast(`Emir #${orderId} iptal edildi.`, "info");
      loadOrd();
      loadOpenOrders();
      loadAcct();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Emir iptal edilemedi", "error");
    } finally {
      setCancellingOrderId(null);
    }
  };

  const handleCancelAllOrders = async () => {
    if (openOrders.length === 0) return;
    if (!window.confirm(`${openOrders.length} adet bekleyen emrin tamamını iptal etmek istediğinize emin misiniz?`)) return;
    setOpenOrdersLoading(true);
    let successCount = 0;
    for (const ord of openOrders) {
      try {
        await apiRequest(`${API_BASE}/api/binance/cancel-order`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order_id: ord.orderId, symbol: ord.symbol }),
        });
        successCount++;
      } catch { /* */ }
    }
    showToast(`${successCount} emir başarıyla iptal edildi.`, "info");
    loadOrd();
    loadOpenOrders();
    loadAcct();
    setOpenOrdersLoading(false);
  };

  return (
    <main className="page-shell">
      {/* Toast Bildirimi */}
      {toast && (
        <div className="fixed top-5 right-5 z-[300] flex items-center gap-3 rounded-lg border border-bunker-700 bg-bunker-950 px-4 py-3 shadow-2xl backdrop-blur-md">
          <span className={`h-2.5 w-2.5 rounded-full ${toast.type === "success" ? "bg-neon-green" : toast.type === "error" ? "bg-neon-red" : "bg-yellow-300"}`} />
          <p className="font-mono text-xs font-medium text-white">{toast.text}</p>
        </div>
      )}

      {/* Sayfa Başlığı ve Aksiyonlar */}
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="eyebrow text-neon-green">BINANCE TR</p>
            <span className="rounded bg-neon-green/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-neon-green border border-neon-green/30">
              TERMINAL
            </span>
          </div>
          <h1 className="font-mono text-2xl font-bold text-white">Canlı Trade & Portföy Takip Ekranı</h1>
          <p className="mt-1 text-sm text-bunker-muted">
            Binance TR canlı bakiyesi, anlık K/Z, tek tıkla Stop-Loss & Take-Profit (OCO) emir yönetimi ve gün içi işlem defteri.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {configured && (
            <span
              className={
                "rounded border px-2.5 py-1 font-mono text-[11px] font-bold " +
                (sellEnabled
                  ? "border-neon-green/50 bg-neon-green/10 text-neon-green"
                  : "border-yellow-400/50 bg-yellow-400/10 text-yellow-400")
              }
            >
              {sellEnabled ? "● GERÇEK EMİR AÇIK" : "○ GERÇEK EMİR KAPALI"}
            </span>
          )}
          <button
            type="button"
            onClick={openBuy}
            disabled={!configured || !sellEnabled}
            className="ui-button ui-button-primary disabled:opacity-40"
            title={!sellEnabled ? "Gerçek işlem kapalı (Ayarlar > GERÇEK SATIŞ)" : "Piyasa fiyatından alım yap"}
          >
            + ALIM YAP
          </button>
          <button
            type="button"
            onClick={() => {
              setSellToggle(sellEnabled);
              setKeyError("");
              setSettingsOpen(true);
            }}
            className="ui-button ui-button-secondary"
          >
            ⚙ AYARLAR
          </button>
        </div>
      </div>

      {!configured ? (
        <section className="card mt-6 grid gap-6 py-10 px-6 text-center md:grid-cols-[1fr_auto] md:text-left md:items-center">
          <div className="flex flex-col items-center gap-4 md:items-start">
            <p className="text-5xl">🔑</p>
            <h2 className="font-mono text-xl font-bold text-white">Binance TR Hesabını Bağla</h2>
            <p className="max-w-lg text-sm text-bunker-muted">
              Canlı bakiyenizi görmek, pozisyonlarınıza Stop-Loss & Take-Profit emirleri girmek ve hızlı alım/satım yapmak için
              <span className="text-white font-bold"> kendi API anahtarlarınızı</span> bağlayın. Anahtarlarınız şifrelenerek
              yalnız sizin hesabınıza kaydedilir — kimse ile paylaşılmaz.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-2 md:justify-start">
              <button type="button" onClick={() => setSettingsOpen(true)} className="ui-button ui-button-primary">
                ⚡ HESABI BAĞLA
              </button>
              <button
                type="button"
                onClick={async () => {
                  setSellToggle(true);
                  await saveKeysWithRealSell(true);
                }}
                disabled={saving}
                className="ui-button ui-button-secondary disabled:opacity-40"
                title="Anahtarları kaydet ve gerçek emir gönderimini hemen aç"
              >
                {saving ? "..." : "BAĞLA + GERÇEK EMİR AÇ"}
              </button>
            </div>
          </div>
          <div className="rounded-xl border border-bunker-700 bg-bunker-900/60 p-4 text-left space-y-2 max-w-sm">
            <p className="eyebrow text-cyan-300">API ANAHTARI İZİNLERİ</p>
            <ul className="space-y-1.5 font-mono text-[11px] text-bunker-muted">
              <li>✅ <span className="text-neon-green font-bold">Read</span> — bakiye ve pozisyon okuma</li>
              <li>✅ <span className="text-cyan-300 font-bold">Spot Trade</span> — alım/satım emirleri</li>
              <li>⛔ <span className="text-neon-red font-bold">Withdrawals</span> — KAPALI tutun (gerekmez, güvenli olur)</li>
            </ul>
            <p className="border-t border-bunker-800 pt-2 text-[11px] text-bunker-muted">
              Binance TR → Hesabım → API Yönetimi'nden yeni anahtar oluşturun.
            </p>
          </div>
        </section>
      ) : (
        <>
          {acctError && (
            <div className="mt-4 rounded-lg border border-neon-red/40 bg-neon-red/10 px-4 py-2.5 text-sm text-neon-red">
              {acctError}
            </div>
          )}

          {/* ÜST KPI DASHBOARD BAR */}
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {/* Toplam Portföy */}
            <div className="card relative overflow-hidden">
              <div className="absolute top-0 left-0 h-1 w-full bg-neon-green/40" />
              <p className="eyebrow">TOPLAM PORTFÖY DEĞERİ</p>
              <p className="mt-1 font-mono text-xl font-bold text-white">₺{fmtPrice(totalValueTry)}</p>
              <p className="mt-0.5 text-[11px] text-bunker-muted">
                ~${fmtPrice(usdtFreeBalance > 0 ? totalValueTry / (liveTicks["USDT"]?.price || 38) : 0)} USD
              </p>
            </div>

            {/* Açık K/Z (Unrealized PnL) */}
            <div className="card relative overflow-hidden">
              <div className={`absolute top-0 left-0 h-1 w-full ${totalUnrealizedPnlTry >= 0 ? "bg-neon-green" : "bg-neon-red"}`} />
              <p className="eyebrow">AÇIK K/Z (UNREALIZED)</p>
              <p className={`mt-1 font-mono text-xl font-bold ${totalUnrealizedPnlTry >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                {totalUnrealizedPnlTry >= 0 ? "+" : "−"}₺{fmtPrice(Math.abs(totalUnrealizedPnlTry))}
              </p>
              <p className="mt-0.5 text-[11px] text-bunker-muted">anlık fiyatlarla pozisyon kârı</p>
            </div>

            {/* Günün Gerçekleşen K/Z */}
            <div className="card relative overflow-hidden">
              <div className={`absolute top-0 left-0 h-1 w-full ${(daily?.realized_pnl_try ?? 0) >= 0 ? "bg-neon-green/60" : "bg-neon-red/60"}`} />
              <p className="eyebrow">GÜNLÜK NET K/Z</p>
              <p className={`mt-1 font-mono text-xl font-bold ${(daily?.realized_pnl_try ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                {(daily?.realized_pnl_try ?? 0) >= 0 ? "+" : "−"}₺{fmtPrice(Math.abs(daily?.realized_pnl_try ?? 0))}
              </p>
              <p className="mt-0.5 text-[11px] text-bunker-muted">
                {daily ? `${daily.wins} kazanç · ${daily.losses} kayıp` : "günlük işlem yok"}
              </p>
            </div>

            {/* Nakit Bakiye */}
            <div className="card relative overflow-hidden">
              <div className="absolute top-0 left-0 h-1 w-full bg-cyan-400/40" />
              <p className="eyebrow">NAKİT LİKİDİTE</p>
              <p className="mt-1 font-mono text-lg font-bold text-cyan-300">₺{fmtPrice(tryFreeBalance)}</p>
              <p className="mt-0.5 text-[11px] text-bunker-muted">
                {fmtPrice(usdtFreeBalance)} USDT boşta
              </p>
            </div>

            {/* Risk & Koruma Durumu */}
            <div className="card relative overflow-hidden">
              <div className={`absolute top-0 left-0 h-1 w-full ${protectedCount === totalCoinPositions && totalCoinPositions > 0 ? "bg-neon-green" : "bg-yellow-400"}`} />
              <p className="eyebrow">SL / TP KORUMA DURUMU</p>
              <div className="mt-1 flex items-center gap-2">
                <span className="font-mono text-xl font-bold text-white">
                  {protectedCount} / {totalCoinPositions}
                </span>
                <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] font-bold ${protectedCount === totalCoinPositions && totalCoinPositions > 0 ? "bg-neon-green/10 text-neon-green border border-neon-green/30" : "bg-yellow-400/10 text-yellow-400 border border-yellow-400/30"}`}>
                  {protectedCount === totalCoinPositions && totalCoinPositions > 0 ? "TAM KORUMALI" : `${totalCoinPositions - protectedCount} KORUMASIZ`}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-bunker-muted">
                {openOrders.length} aktif açık emir
              </p>
            </div>
          </div>

          {/* SEKME NAVİGASYONU */}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-b border-bunker-700 pb-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab("positions")}
                className={`rounded-lg px-4 py-2 font-mono text-xs font-bold transition-all ${
                  activeTab === "positions"
                    ? "bg-neon-green/15 text-neon-green border border-neon-green/40 shadow-sm"
                    : "text-bunker-muted hover:bg-bunker-800 hover:text-white border border-transparent"
                }`}
              >
                📊 Açık Pozisyonlar ({visibleHoldings.length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("openOrders")}
                className={`flex items-center gap-1.5 rounded-lg px-4 py-2 font-mono text-xs font-bold transition-all ${
                  activeTab === "openOrders"
                    ? "bg-cyan-500/15 text-cyan-400 border border-cyan-500/40 shadow-sm"
                    : "text-bunker-muted hover:bg-bunker-800 hover:text-white border border-transparent"
                }`}
              >
                📋 Bekleyen Emirler / SL-TP ({openOrders.length})
                {openOrders.length > 0 && (
                  <span className="h-2 w-2 rounded-full bg-cyan-400" />
                )}
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("trades")}
                className={`rounded-lg px-4 py-2 font-mono text-xs font-bold transition-all ${
                  activeTab === "trades"
                    ? "bg-yellow-400/15 text-yellow-400 border border-yellow-400/40 shadow-sm"
                    : "text-bunker-muted hover:bg-bunker-800 hover:text-white border border-transparent"
                }`}
              >
                📈 Günün İşlemleri & Trade Defteri ({trades.length})
              </button>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  loadAcct();
                  loadOrd();
                  loadOpenOrders();
                  if (activeTab === "trades") loadTrades();
                  showToast("Veriler yenilendi.", "info");
                }}
                disabled={ordLoading || openOrdersLoading}
                className="ui-button ui-button-secondary !py-1 !text-xs"
                title="Tüm verileri yenile"
              >
                ⟳ Yenile
              </button>
            </div>
          </div>

          {/* TAB 1: AÇIK POZİSYONLAR */}
          {activeTab === "positions" && (
            <section className="mt-4 space-y-3">
              {/* Filtre Barı */}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-bunker-700/60 bg-bunker-900/40 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    placeholder="Sembol ara (örn: BTC, AVAX)..."
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    className="input w-48 font-mono text-xs !py-1.5"
                  />
                  <div className="flex items-center rounded-lg border border-bunker-700 bg-bunker-950 p-0.5 text-xs font-mono">
                    <button
                      type="button"
                      onClick={() => setPositionFilter("all")}
                      className={`rounded px-2.5 py-1 ${positionFilter === "all" ? "bg-bunker-800 text-white font-bold" : "text-bunker-muted hover:text-white"}`}
                    >
                      Tümü
                    </button>
                    <button
                      type="button"
                      onClick={() => setPositionFilter("unprotected")}
                      className={`rounded px-2.5 py-1 ${positionFilter === "unprotected" ? "bg-yellow-400/20 text-yellow-300 font-bold" : "text-bunker-muted hover:text-white"}`}
                    >
                      ⚠️ Korumasızlar
                    </button>
                    <button
                      type="button"
                      onClick={() => setPositionFilter("profit")}
                      className={`rounded px-2.5 py-1 ${positionFilter === "profit" ? "bg-neon-green/20 text-neon-green font-bold" : "text-bunker-muted hover:text-white"}`}
                    >
                      🟢 Kârdakiler
                    </button>
                    <button
                      type="button"
                      onClick={() => setPositionFilter("loss")}
                      className={`rounded px-2.5 py-1 ${positionFilter === "loss" ? "bg-neon-red/20 text-neon-red font-bold" : "text-bunker-muted hover:text-white"}`}
                    >
                      🔴 Zarardakiler
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
                    <input
                      type="checkbox"
                      checked={hideSmall}
                      onChange={(e) => setHideSmall(e.target.checked)}
                      className="h-3.5 w-3.5 accent-[color:var(--neon-green,#22c55e)]"
                    />
                    50 TL altını gizle
                  </label>
                  {ordLoading && (
                    <span className="font-mono text-[10px] text-bunker-muted animate-pulse">
                      Güncelleniyor...
                    </span>
                  )}
                </div>
              </div>

              {/* Pozisyonlar — Mobil Kart Görünümü (sm altı) */}
              <div className="space-y-2.5 sm:hidden">
                {visibleHoldings.length === 0 ? (
                  <div className="card p-6 text-center font-mono text-sm text-bunker-muted">
                    Filtreye uygun açık pozisyon bulunamadı.
                  </div>
                ) : (
                  visibleHoldings.map((h) => {
                    const pnlToneCls = h.pnl_try == null ? "text-bunker-muted" : h.pnl_try >= 0 ? "text-neon-green" : "text-neon-red";
                    const hasSl = h.active_sl_price != null && h.active_sl_price > 0;
                    const hasTp = h.active_tp_price != null && h.active_tp_price > 0;
                    const protectedPos = h.asset === "TRY" || hasSl || hasTp || h.has_active_order;
                    if (h.asset === "TRY") {
                      return (
                        <div key={h.asset} className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-3.5">
                          <div className="flex items-center justify-between">
                            <div>
                              <span className="font-mono text-base font-black text-white">TRY</span>
                              <span className="ml-2 rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[9px] font-bold text-cyan-300 border border-cyan-500/30">NAKİT</span>
                            </div>
                            <span className="font-mono text-base font-black text-cyan-300">₺{fmtPrice(h.total)}</span>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={h.asset} className="rounded-xl border border-bunker-800 bg-bunker-900/40 p-3.5">
                        {/* Üst satır: sembol + K/Z */}
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-base font-black text-white">{h.asset}</span>
                            <span className={`text-sm ${tickDir[h.asset] === "up" ? "text-neon-green" : tickDir[h.asset] === "down" ? "text-neon-red" : "text-bunker-muted"}`}>
                              {tickDir[h.asset] === "up" ? "▲" : tickDir[h.asset] === "down" ? "▼" : ""}
                            </span>
                          </div>
                          <div className="text-right">
                            <p className={`font-mono text-sm font-black ${pnlToneCls}`}>
                              {h.pnl_try != null ? `${h.pnl_try >= 0 ? "+" : "−"}₺${fmtPrice(Math.abs(h.pnl_try))}` : "—"}
                            </p>
                            {h.pnl_pct != null && (
                              <p className={`font-mono text-[10px] font-bold ${pnlToneCls}`}>
                                {h.pnl_pct >= 0 ? "+" : "−"}%{fmtPrice(Math.abs(h.pnl_pct), 2)}
                              </p>
                            )}
                          </div>
                        </div>
                        {/* Orta satır: fiyat + değer + miktar */}
                        <div className="mt-2 grid grid-cols-3 gap-2 rounded-lg border border-bunker-800/70 bg-bunker-950/60 p-2 font-mono text-[10px]">
                          <div>
                            <p className="text-bunker-muted">FİYAT</p>
                            <p className="font-bold text-white">{h.price_try != null ? `₺${fmtPrice(h.price_try, h.price_try < 1 ? 6 : 2)}` : "—"}</p>
                          </div>
                          <div>
                            <p className="text-bunker-muted">DEĞER</p>
                            <p className="font-bold text-white">{h.value_try != null ? `₺${fmtPrice(h.value_try)}` : "—"}</p>
                          </div>
                          <div>
                            <p className="text-bunker-muted">MİKTAR</p>
                            <p className="font-bold text-white">{fmtPrice(h.free, 6)}</p>
                          </div>
                        </div>
                        {/* Koruma durumu */}
                        <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                          {protectedPos ? (
                            <>
                              {hasTp && <span className="rounded bg-neon-green/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-neon-green border border-neon-green/30">🎯 TP ₺{fmtPrice(h.active_tp_price, (h.active_tp_price ?? 0) < 1 ? 6 : 2)}</span>}
                              {hasSl && <span className="rounded bg-neon-red/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-neon-red border border-neon-red/30">🛑 SL ₺{fmtPrice(h.active_sl_price, (h.active_sl_price ?? 0) < 1 ? 6 : 2)}</span>}
                              {!hasSl && !hasTp && h.has_active_order && <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-cyan-300 border border-cyan-500/30">📋 Emir var</span>}
                            </>
                          ) : (
                            <span className="rounded bg-yellow-400/10 px-2 py-0.5 font-mono text-[9px] font-bold text-yellow-300 border border-yellow-400/30">⚠️ Korumasız</span>
                          )}
                        </div>
                        {/* Aksiyonlar */}
                        <div className="mt-3 flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => setChartFor(h)}
                            title={`${h.asset}/TRY canlı grafik`}
                            className="flex h-10 flex-1 items-center justify-center rounded-lg border border-cyan-500/40 bg-cyan-500/10 font-mono text-[11px] font-bold text-cyan-300 hover:bg-cyan-500/25 transition-colors touch-target"
                          >
                            📈 Grafik
                          </button>
                          <button
                            type="button"
                            onClick={() => openSltpModal(h)}
                            disabled={!sellEnabled}
                            title="SL/TP kur veya güncelle"
                            className="flex h-10 flex-1 items-center justify-center rounded-lg border border-cyan-500/50 bg-cyan-500/10 font-mono text-[11px] font-bold text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40 transition-colors touch-target"
                          >
                            🛡️ SL/TP
                          </button>
                          <button
                            type="button"
                            onClick={() => openSell(h)}
                            disabled={!sellEnabled || h.free <= 0 || h.price_try == null}
                            title="Piyasa fiyatından hızlı sat"
                            className="flex h-10 flex-1 items-center justify-center rounded-lg border border-neon-red/50 bg-neon-red/10 font-mono text-[11px] font-bold text-neon-red hover:bg-neon-red/20 disabled:opacity-30 transition-colors touch-target"
                          >
                            ⚡ Sat
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Pozisyonlar Tablosu (Masaüstü) */}
              <div className="card !p-0 overflow-hidden hidden sm:block">
                {visibleHoldings.length === 0 ? (
                  <div className="p-8 text-center font-mono text-sm text-bunker-muted">
                    Filtreye uygun açık pozisyon bulunamadı.
                  </div>
                ) : (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th className="w-10 text-center">Grafik</th>
                          <th>Varlık</th>
                          <th>Boşta / Kilitli Miktar</th>
                          <th>Alış Maliyeti</th>
                          <th>Güncel Fiyat</th>
                          <th>Anlık K/Z</th>
                          <th>TRY Değeri</th>
                          <th>SL / TP Durumu</th>
                          <th className="text-right">Aksiyonlar</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleHoldings.map((h) => {
                          const pnlToneCls = h.pnl_try == null ? "" : h.pnl_try >= 0 ? "text-neon-green" : "text-neon-red";
                          const dir = tickDir[h.asset];
                          const hasSl = h.active_sl_price != null && h.active_sl_price > 0;
                          const hasTp = h.active_tp_price != null && h.active_tp_price > 0;

                          return (
                            <tr key={h.asset} className="hover:bg-bunker-900/60 transition-colors">
                              <td className="text-center">
                                {h.asset !== "TRY" ? (
                                  <button
                                    type="button"
                                    onClick={() => setChartFor(h)}
                                    title={`${h.asset}/TRY Canlı Pozisyon Grafiği (M5, Bollinger Bands, SL/TP Sürükle-Bırak)`}
                                    className="inline-flex items-center justify-center rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-cyan-300 hover:bg-cyan-500/25 hover:border-cyan-400 hover:scale-105 shadow-sm transition-all"
                                  >
                                    <span className="text-xs font-mono font-bold">📈</span>
                                  </button>
                                ) : (
                                  <span className="text-bunker-muted text-xs">—</span>
                                )}
                              </td>
                              <td>
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => h.asset !== "TRY" && setChartFor(h)}
                                    className={`font-mono text-sm font-bold text-white transition-colors text-left flex items-center gap-1 ${
                                      h.asset !== "TRY" ? "hover:text-cyan-300 cursor-pointer" : ""
                                    }`}
                                    title={h.asset !== "TRY" ? `${h.asset}/TRY Grafiğini Aç` : undefined}
                                  >
                                    <span>{h.asset}</span>
                                    {h.asset !== "TRY" && <span className="text-[10px] text-cyan-400/70">↗</span>}
                                  </button>
                                  {dir && h.asset !== "TRY" && (
                                    <span className={`font-mono text-[10px] font-bold ${dir === "up" ? "text-neon-green" : "text-neon-red"}`}>
                                      {dir === "up" ? "▲" : "▼"}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="font-mono text-xs">
                                <div>{fmtPrice(h.free, 6)}</div>
                                {h.locked > 0 && (
                                  <div className="text-[10px] text-cyan-400">
                                    🔒 {fmtPrice(h.locked, 6)} kilitli
                                  </div>
                                )}
                              </td>
                              <td className="font-mono text-xs text-bunker-muted">
                                {h.avg_cost_try != null ? `₺${fmtPrice(h.avg_cost_try, h.avg_cost_try < 1 ? 6 : 2)}` : "—"}
                              </td>
                              <td className={`font-mono text-xs tabular-nums font-medium whitespace-nowrap ${dir ? (dir === "up" ? "text-neon-green" : "text-neon-red") : "text-white"}`}>
                                {h.price_try != null ? `₺${fmtPrice(h.price_try, h.price_try < 1 ? 6 : 2)}` : "—"}
                              </td>
                              <td className={`font-mono text-xs font-bold tabular-nums whitespace-nowrap ${pnlToneCls}`}>
                                {h.pnl_try != null ? (
                                  <>
                                    <span>{h.pnl_try >= 0 ? "+" : "−"}₺{fmtPrice(Math.abs(h.pnl_try))}</span>
                                    {h.pnl_pct != null && (
                                      <span className={`ml-1 text-[11px] font-normal ${pnlToneCls}`}>
                                        ({h.pnl_pct >= 0 ? "+" : "−"}%{fmtPrice(Math.abs(h.pnl_pct), 2)})
                                      </span>
                                    )}
                                  </>
                                ) : "—"}
                              </td>
                              <td className="font-mono text-xs font-bold text-white tabular-nums whitespace-nowrap">
                                {h.value_try != null ? `₺${fmtPrice(h.value_try)}` : "—"}
                              </td>
                              <td>
                                {h.asset === "TRY" ? (
                                  <span className="text-[11px] text-bunker-muted">Nakit</span>
                                ) : hasSl || hasTp ? (
                                  <div className="flex flex-col gap-0.5">
                                    {hasTp && (
                                      <span className="inline-flex items-center gap-1 rounded bg-neon-green/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-neon-green border border-neon-green/30">
                                        🎯 TP: ₺{fmtPrice(h.active_tp_price, (h.active_tp_price ?? 0) < 1 ? 6 : 2)}
                                      </span>
                                    )}
                                    {hasSl && (
                                      <span className="inline-flex items-center gap-1 rounded bg-neon-red/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-neon-red border border-neon-red/30">
                                        🛑 SL: ₺{fmtPrice(h.active_sl_price, (h.active_sl_price ?? 0) < 1 ? 6 : 2)}
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                  <span className="inline-flex items-center gap-1 rounded bg-yellow-400/10 px-2 py-0.5 font-mono text-[10px] font-bold text-yellow-300 border border-yellow-400/30">
                                    ⚠️ Korumasız
                                  </span>
                                )}
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  {h.asset !== "TRY" && (
                                    <button
                                      type="button"
                                      onClick={() => openSltpModal(h)}
                                      disabled={!sellEnabled}
                                      title={!sellEnabled ? "Gerçek işlem kapalı" : "Stop-Loss ve Take-Profit (OCO) kur veya güncelle"}
                                      className="rounded border border-cyan-500/50 bg-cyan-500/10 px-2.5 py-1 font-mono text-[11px] font-bold text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40 transition-colors"
                                    >
                                      🛡️ SL / TP
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => openSell(h)}
                                    disabled={!sellEnabled || h.free <= 0 || h.asset === "TRY" || h.price_try == null}
                                    title={!sellEnabled ? "Gerçek satış kapalı" : h.free <= 0 ? "Boşta bakiye yok" : "Piyasa fiyatından hızlı sat"}
                                    className="rounded border border-neon-red/50 bg-neon-red/10 px-2 py-1 font-mono text-[11px] font-bold text-neon-red hover:bg-neon-red/20 disabled:opacity-30 transition-colors"
                                  >
                                    ⚡ SAT
                                  </button>
                                  {h.asset !== "TRY" && (h.avg_cost_try ?? 0) > 0 && h.has_active_order && (
                                    <button
                                      type="button"
                                      onClick={() => { openSltpModal(h); }}
                                      title="Kâr kilitli (Break-Even) — SL güncellemek için tıkla"
                                      className="rounded border border-amber-400/50 bg-amber-400/10 px-2 py-1 font-mono text-[11px] font-bold text-amber-300 hover:bg-amber-400/25 transition-colors"
                                    >
                                      🔒 BE
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* TAB 2: BEKLEYEN EMİRLER (OPEN ORDERS & SL/TP) */}
          {activeTab === "openOrders" && (
            <section className="mt-4 space-y-3">
              <div className="flex items-center justify-between rounded-lg border border-bunker-700/60 bg-bunker-900/40 p-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-white">
                    Toplam {openOrders.length} Bekleyen Açık Emir
                  </span>
                  <span className="text-[11px] text-bunker-muted">
                    (OCO, Stop-Loss ve Limit satış/alış emirleri)
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleCancelAllOrders}
                    disabled={openOrders.length === 0 || openOrdersLoading}
                    className="rounded border border-neon-red/50 bg-neon-red/10 px-3 py-1 font-mono text-xs font-bold text-neon-red hover:bg-neon-red/20 disabled:opacity-40 transition-colors"
                  >
                    ✕ TÜMÜNÜ İPTAL ET
                  </button>
                </div>
              </div>

              <div className="card !p-0 overflow-hidden">
                {openOrders.length === 0 ? (
                  <div className="p-8 text-center font-mono text-sm text-bunker-muted">
                    Şu anda borsada bekleyen açık veya tetikleyici emir bulunmuyor.
                  </div>
                ) : (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Emir ID</th>
                          <th>Sembol</th>
                          <th>Yön</th>
                          <th>Tip</th>
                          <th>Miktar</th>
                          <th>Limit Fiyat</th>
                          <th>Tetikleme (Stop) Fiyatı</th>
                          <th>Zaman</th>
                          <th>Durum</th>
                          <th className="text-right">İşlem</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openOrders.map((ord) => {
                          const isSell = String(ord.side).toUpperCase() === "SELL" || ord.side === "1";
                          const hasStop = parseFloat(ord.stopPrice || "0") > 0;
                          return (
                            <tr key={ord.orderId} className="hover:bg-bunker-900/60 transition-colors">
                              <td className="font-mono text-xs text-bunker-muted">#{ord.orderId}</td>
                              <td className="font-mono text-xs font-bold text-white">{ord.symbol}</td>
                              <td>
                                <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${isSell ? "bg-neon-red/15 text-neon-red border border-neon-red/30" : "bg-neon-green/15 text-neon-green border border-neon-green/30"}`}>
                                  {isSell ? "SAT" : "AL"}
                                </span>
                              </td>
                              <td className="font-mono text-xs">
                                <span className="rounded bg-bunker-800 px-1.5 py-0.5 text-[10px] text-bunker-muted border border-bunker-700">
                                  {ord.type}
                                </span>
                              </td>
                              <td className="font-mono text-xs">{fmtPrice(ord.origQty, 6)}</td>
                              <td className="font-mono text-xs font-medium text-white">
                                {parseFloat(ord.price) > 0 ? `₺${fmtPrice(ord.price, parseFloat(ord.price) < 1 ? 6 : 2)}` : "Piyasa"}
                              </td>
                              <td className="font-mono text-xs">
                                {hasStop ? (
                                  <span className="font-bold text-neon-red">
                                    ₺{fmtPrice(ord.stopPrice, parseFloat(ord.stopPrice) < 1 ? 6 : 2)}
                                  </span>
                                ) : (
                                  <span className="text-bunker-muted">—</span>
                                )}
                              </td>
                              <td className="font-mono text-[11px] text-bunker-muted">{fmtTime(ord.time)}</td>
                              <td>
                                <span className="rounded bg-yellow-400/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-yellow-300 border border-yellow-400/30">
                                  {ord.status || "BEKLİYOR"}
                                </span>
                              </td>
                              <td className="text-right">
                                <button
                                  type="button"
                                  onClick={() => handleCancelOrder(ord.orderId, ord.symbol)}
                                  disabled={cancellingOrderId === ord.orderId}
                                  className="rounded border border-neon-red/50 bg-neon-red/10 px-2.5 py-1 font-mono text-[11px] font-bold text-neon-red hover:bg-neon-red/20 disabled:opacity-40 transition-colors"
                                >
                                  {cancellingOrderId === ord.orderId ? "İptal ediliyor..." : "İPTAL ET"}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* TAB 3: GÜNÜN İŞLEMLERİ & TRADE DEFTERİ */}
          {activeTab === "trades" && (
            <section className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-bunker-700/60 bg-bunker-900/40 p-3">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
                    <span>Tarih:</span>
                    <input
                      type="date"
                      value={tradeDay}
                      onChange={(e) => setTradeDay(e.target.value)}
                      className="input font-mono text-xs !py-1"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={loadTrades}
                    disabled={trLoading}
                    className="ui-button ui-button-secondary !py-1 !text-xs"
                  >
                    {trLoading ? "Yükleniyor..." : "⟳ Listele"}
                  </button>
                </div>
                {trMeta && (
                  <span className="font-mono text-[11px] text-bunker-muted">
                    {trMeta.count} işlem dolduruldu · {trMeta.symbols_scanned} çift tarandı
                  </span>
                )}
              </div>

              {symbolSummary.length === 0 && !trLoading ? (
                <div className="card p-8 text-center font-mono text-sm text-bunker-muted">
                  Seçilen tarihte gerçekleşen işlem kaydı bulunamadı.
                </div>
              ) : (
                <div className="card !p-0 overflow-hidden">
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          {([
                            ["symbol", "Sembol", false],
                            ["buy_qty", "Alış Miktar", true],
                            ["buy_avg", "Ort. Alış", true],
                            ["sell_qty", "Satış Miktar", true],
                            ["sell_avg", "Ort. Satış", true],
                            ["commission", "Komisyon", true],
                            ["pnl", "Net K/Z", true],
                            ["fills", "Fill Adedi", true],
                          ] as [TradesSortKey, string, boolean][]).map(([key, label, right]) => {
                            const active = tradesSort.key === key;
                            return (
                              <th
                                key={key}
                                onClick={() => toggleTradesSort(key)}
                                className={`${right ? "text-right" : ""} cursor-pointer select-none hover:text-neon-green transition-colors ${active ? "text-neon-green" : ""}`}
                                title={`${label} sütununa göre sırala (tekrar tıkla: ters çevir)`}
                              >
                                {label}
                                <span className="ml-1 text-[9px] opacity-80">
                                  {active ? (tradesSort.dir === "asc" ? "▲" : "▼") : "⇅"}
                                </span>
                              </th>
                            );
                          })}
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedSymbolSummary.map((s) => {
                          const buyAvg = s.buy_qty > 0 ? s.buy_cost_try / s.buy_qty : 0;
                          const sellAvg = s.sell_qty > 0 ? s.sell_revenue_try / s.sell_qty : 0;
                          const pnlCls = s.realized_pnl_try >= 0 ? "text-neon-green" : "text-neon-red";
                          const isExpanded = expandedSymbol === s.symbol;
                          const detailRows = trades.filter((t) => t.symbol === s.symbol);

                          return (
                            <>
                              <tr key={s.symbol} className="hover:bg-bunker-900/60">
                                <td><span className="font-mono font-bold text-white">{s.symbol}</span></td>
                                <td className="font-mono text-xs text-right">{fmtPrice(s.buy_qty, s.buy_qty < 1 ? 6 : 3)}</td>
                                <td className="font-mono text-xs text-right">{buyAvg ? `₺${fmtPrice(buyAvg, buyAvg < 1 ? 6 : 2)}` : "—"}</td>
                                <td className="font-mono text-xs text-right">{fmtPrice(s.sell_qty, s.sell_qty < 1 ? 6 : 3)}</td>
                                <td className="font-mono text-xs text-right">{sellAvg ? `₺${fmtPrice(sellAvg, sellAvg < 1 ? 6 : 2)}` : "—"}</td>
                                <td className="font-mono text-xs text-right text-bunker-muted">₺{fmtPrice(s.commission_try)}</td>
                                <td className={`font-mono text-xs font-bold text-right ${pnlCls}`}>
                                  {s.realized_pnl_try !== 0 ? `${s.realized_pnl_try >= 0 ? "+" : "−"}₺${fmtPrice(Math.abs(s.realized_pnl_try))}` : "—"}
                                </td>
                                <td className="font-mono text-xs text-right text-bunker-muted">{s.fills}</td>
                                <td className="text-right">
                                  <button
                                    type="button"
                                    onClick={() => setExpandedSymbol(isExpanded ? null : s.symbol)}
                                    className="rounded border border-bunker-600 px-2 py-0.5 font-mono text-[10px] text-bunker-muted hover:text-white"
                                  >
                                    {isExpanded ? "▲ Kapat" : "▼ Detay"}
                                  </button>
                                </td>
                              </tr>
                              {isExpanded &&
                                detailRows.map((t) => (
                                  <tr key={`${s.symbol}-d-${t.id}`} className="bg-bunker-900/80 border-b border-bunker-800">
                                    <td className="font-mono text-[11px] text-bunker-muted pl-6">{fmtTime(t.time)}</td>
                                    <td className={`font-mono text-[11px] text-right font-bold ${t.isBuyer ? "text-neon-green" : "text-neon-red"}`}>
                                      {t.isBuyer ? "AL" : "SAT"} × {fmtPrice(t.qty, Number(t.qty) < 1 ? 6 : 3)}
                                    </td>
                                    <td className="font-mono text-[11px] text-right text-bunker-muted">
                                      {t.isBuyer ? "—" : t.basis_price ? `maliyet ₺${fmtPrice(t.basis_price, 2)}` : "önceki gün"}
                                    </td>
                                    <td className="font-mono text-[11px] text-right text-bunker-muted">{t.isBuyer ? "alış" : "satış"}</td>
                                    <td className="font-mono text-[11px] text-right text-white">₺{fmtPrice(t.price, Number(t.price) < 1 ? 6 : 2)}</td>
                                    <td className="font-mono text-[11px] text-right text-bunker-muted">₺{fmtPrice(t.commission, 4)}</td>
                                    <td className={`font-mono text-[11px] font-bold text-right ${t.realized_pnl_try != null ? (t.realized_pnl_try >= 0 ? "text-neon-green" : "text-neon-red") : "text-bunker-muted"}`}>
                                      {t.realized_pnl_try != null ? `${t.realized_pnl_try >= 0 ? "+" : "−"}₺${fmtPrice(Math.abs(t.realized_pnl_try))}` : "—"}
                                    </td>
                                    <td className="font-mono text-[11px] text-right text-bunker-muted">₺{fmtPrice(t.quoteQty, 2)}</td>
                                    <td />
                                  </tr>
                                ))}
                            </>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* ========================================================= */}
          {/* MODAL: PROFESYONEL SL / TP & OCO YÖNETİMİ                 */}
          {/* ========================================================= */}
          {sltpModalOpen && sltpTarget && (
            <div className="fixed inset-0 z-[220] grid place-items-center bg-black/85 p-4 overflow-y-auto" role="dialog" aria-modal="true">
              <section className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-6 shadow-2xl backdrop-blur-xl">
                {/* Modal Başlık */}
                <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
                  <div>
                    <span className="eyebrow text-cyan-400">POZİSYON KORUMA & HEDEF</span>
                    <h2 className="font-mono text-xl font-bold text-white">
                      SL / TP Ayarla: <span className="text-neon-green">{sltpTarget.asset}</span>
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSltpModalOpen(false)}
                    className="rounded p-1 text-bunker-muted hover:bg-bunker-800 hover:text-white"
                  >
                    ✕
                  </button>
                </div>

                {/* Varlık Bilgi Şeridi */}
                <div className="mt-4 grid grid-cols-3 gap-2 rounded-lg border border-bunker-800 bg-bunker-900/60 p-3">
                  <div>
                    <p className="eyebrow">GÜNCEL FİYAT</p>
                    <p className="font-mono text-sm font-bold text-white">
                      ₺{fmtPrice(currentTargetPrice, currentTargetPrice < 1 ? 6 : 2)}
                    </p>
                  </div>
                  <div>
                    <p className="eyebrow">ALIŞ MALİYETİ</p>
                    <p className="font-mono text-sm font-bold text-bunker-muted">
                      {sltpTarget.avg_cost_try ? `₺${fmtPrice(sltpTarget.avg_cost_try, sltpTarget.avg_cost_try < 1 ? 6 : 2)}` : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="eyebrow">BAKİYE (TOPLAM / BOŞTA)</p>
                    <p className="font-mono text-sm font-bold text-white">
                      {fmtPrice(sltpTarget.total, 4)}
                      <span className="text-[10px] text-bunker-muted ml-1">({fmtPrice(sltpTarget.free, 4)} boşta)</span>
                    </p>
                  </div>
                </div>

                {/* Mod Seçici (OCO vs Sadece SL vs Sadece TP) */}
                <div className="mt-4">
                  <span className="eyebrow">EMİR TİPİ</span>
                  <div className="mt-1 grid grid-cols-3 gap-1.5 rounded-lg border border-bunker-700 bg-bunker-900 p-1">
                    <button
                      type="button"
                      onClick={() => setSltpMode("OCO")}
                      className={`rounded py-1.5 font-mono text-xs font-bold transition-all ${
                        sltpMode === "OCO"
                          ? "bg-cyan-500 text-black shadow"
                          : "text-bunker-muted hover:text-white"
                      }`}
                    >
                      🛡️ OCO (SL + TP)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSltpMode("SL_ONLY")}
                      className={`rounded py-1.5 font-mono text-xs font-bold transition-all ${
                        sltpMode === "SL_ONLY"
                          ? "bg-neon-red text-white shadow"
                          : "text-bunker-muted hover:text-white"
                      }`}
                    >
                      🛑 Sadece Stop Loss
                    </button>
                    <button
                      type="button"
                      onClick={() => setSltpMode("TP_ONLY")}
                      className={`rounded py-1.5 font-mono text-xs font-bold transition-all ${
                        sltpMode === "TP_ONLY"
                          ? "bg-neon-green text-black shadow"
                          : "text-bunker-muted hover:text-white"
                      }`}
                    >
                      🎯 Sadece Kâr Al
                    </button>
                  </div>
                </div>

                {/* Miktar Seçimi */}
                <div className="mt-4">
                  <div className="flex items-center justify-between">
                    <span className="eyebrow">SATILACAK MİKTAR ({sltpTarget.asset})</span>
                    <span className="font-mono text-[11px] text-bunker-muted">
                      Değer: ~₺{fmtPrice(sltpQtyNum * currentTargetPrice)}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      type="text"
                      value={sltpQty}
                      onChange={(e) => setSltpQty(e.target.value)}
                      placeholder="Miktar girin"
                      className="input flex-1 font-mono text-xs"
                    />
                    <div className="flex items-center gap-1">
                      {[25, 50, 75, 100].map((pct) => (
                        <button
                          key={pct}
                          type="button"
                          onClick={() => applyQtyPct(pct)}
                          className="rounded border border-bunker-700 bg-bunker-800 px-2 py-1 font-mono text-[10px] text-bunker-muted hover:bg-bunker-700 hover:text-white"
                        >
                          %{pct}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* TAKE PROFIT (KÂR AL) BÖLÜMÜ */}
                {(sltpMode === "OCO" || sltpMode === "TP_ONLY") && (
                  <div className="mt-4 rounded-lg border border-neon-green/30 bg-neon-green/5 p-3.5 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="eyebrow text-neon-green">🎯 TAKE PROFIT (KÂR AL HEDEF FİYATI)</span>
                      {calculatedTpProfit && (
                        <span className="font-mono text-[11px] font-bold text-neon-green">
                          +{fmtPrice(calculatedTpProfit.pct, 1)}% (+₺{fmtPrice(calculatedTpProfit.totalDiff)})
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={sltpTpPrice}
                        onChange={(e) => setSltpTpPrice(e.target.value)}
                        placeholder="Örn: 1250.50"
                        className="input flex-1 font-mono text-xs"
                      />
                      <div className="flex items-center gap-1">
                        {[3, 5, 10, 20, 50].map((pct) => (
                          <button
                            key={pct}
                            type="button"
                            onClick={() => applyTpPct(pct)}
                            className="rounded border border-neon-green/40 bg-neon-green/10 px-1.5 py-1 font-mono text-[10px] text-neon-green hover:bg-neon-green/20"
                          >
                            +{pct}%
                          </button>
                        ))}
                      </div>
                    </div>
                    <p className="text-[10px] text-bunker-muted">
                      Fiyat bu seviyeye ulaştığında emir defterine LIMIT satış emri gönderilerek kâr realize edilir.
                    </p>
                  </div>
                )}

                {/* STOP LOSS (ZARAR KES) BÖLÜMÜ */}
                {(sltpMode === "OCO" || sltpMode === "SL_ONLY") && (
                  <div className="mt-4 rounded-lg border border-neon-red/30 bg-neon-red/5 p-3.5 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="eyebrow text-neon-red">🛑 STOP LOSS (ZARAR KES TETİK FİYATI)</span>
                      {calculatedSlLoss && (
                        <span className="font-mono text-[11px] font-bold text-neon-red">
                          {fmtPrice(calculatedSlLoss.pct, 1)}% (−₺{fmtPrice(Math.abs(calculatedSlLoss.totalDiff))})
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={sltpSlPrice}
                        onChange={(e) => {
                          setSltpSlPrice(e.target.value);
                          const val = parseFloat(e.target.value.replace(",", "."));
                          if (Number.isFinite(val) && val > 0) {
                            setSltpSlLimitPrice((val * 0.995).toFixed(currentTargetPrice < 1 ? 6 : 2));
                          }
                        }}
                        placeholder="Örn: 950.00"
                        className="input flex-1 font-mono text-xs"
                      />
                      <div className="flex items-center gap-1 flex-wrap">
                        <button
                          type="button"
                          onClick={applyBreakEven}
                          title="Fiyat kârdaysa; alış maliyeti + komisyon + %0.05 kâr kilidi ile stop belirle"
                          className="rounded border border-amber-500/50 bg-amber-500/15 px-2 py-1 font-mono text-[10px] font-bold text-amber-300 hover:bg-amber-500/30 hover:border-amber-400 transition-all shadow-sm flex items-center gap-1"
                        >
                          <span>🔒 Break-Even</span>
                        </button>
                        {[2, 3, 5, 7, 10].map((pct) => (
                          <button
                            key={pct}
                            type="button"
                            onClick={() => applySlPct(pct)}
                            className="rounded border border-neon-red/40 bg-neon-red/10 px-1.5 py-1 font-mono text-[10px] text-neon-red hover:bg-neon-red/20"
                          >
                            −{pct}%
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Slippage / Limit Fiyat Ayarı */}
                    <div className="pt-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[10px] text-bunker-muted">Stop-Limit Satış Fiyatı (Kayma Koruması):</span>
                        <span className="font-mono text-[10px] text-bunker-muted">
                          ₺{sltpSlLimitPrice || "—"}
                        </span>
                      </div>
                      <input
                        type="text"
                        value={sltpSlLimitPrice}
                        onChange={(e) => setSltpSlLimitPrice(e.target.value)}
                        placeholder="Stop tetiklenince açılacak limit fiyat"
                        className="input mt-1 w-full font-mono text-[11px]"
                      />
                    </div>
                  </div>
                )}

                {/* Risk / Reward Göstergesi */}
                {sltpMode === "OCO" && calculatedRrRatio && (
                  <div className="mt-3 flex items-center justify-between rounded-lg border border-cyan-500/30 bg-cyan-500/5 px-3 py-2">
                    <span className="font-mono text-xs text-cyan-300">Risk / Ödül Oranı (R:R Ratio):</span>
                    <span className="font-mono text-sm font-bold text-white">1 : {calculatedRrRatio}</span>
                  </div>
                )}

                {/* Önceki Emirleri Güncelleme / İptal Uyarısı */}
                <div className="mt-4 rounded-lg border border-yellow-400/30 bg-yellow-400/5 p-3">
                  <label className="flex cursor-pointer items-start gap-2 text-xs font-mono text-yellow-300/90">
                    <input
                      type="checkbox"
                      checked={sltpCancelExisting}
                      onChange={(e) => setSltpCancelExisting(e.target.checked)}
                      className="mt-0.5 h-3.5 w-3.5 accent-[color:var(--yellow-300,#facc15)]"
                    />
                    <span>
                      Bu varlığa ait mevcut bekleyen açık satış emirlerini otomatik iptal et ve yeni SL/TP ile değiştir (Cancel-and-Replace).
                    </span>
                  </label>
                </div>

                {sltpMsg && (
                  <p className={`mt-3 font-mono text-xs ${sltpMsg.ok ? "text-neon-green" : "text-neon-red"}`}>
                    {sltpMsg.text}
                  </p>
                )}

                {/* Butonlar */}
                <div className="mt-6 flex items-center justify-end gap-2 border-t border-bunker-800 pt-3">
                  <button
                    type="button"
                    onClick={() => setSltpModalOpen(false)}
                    className="ui-button ui-button-secondary"
                  >
                    İptal
                  </button>
                  <button
                    type="button"
                    onClick={confirmSltp}
                    disabled={sltpBusy || !sellEnabled}
                    className="ui-button ui-button-primary !bg-cyan-500 hover:!bg-cyan-400 !text-black font-bold disabled:opacity-40"
                  >
                    {sltpBusy ? "GÖNDERİLİYOR..." : `ONAYLA — ${sltpMode} EMRİ GÖNDER`}
                  </button>
                </div>
              </section>
            </div>
          )}

          {/* MODAL: SATIŞ ONAY MODALI (MARKET SELL) */}
          {sellFor && sellEnabled && (
            <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4 overflow-y-auto" role="dialog" aria-modal="true">
              <section className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-mono text-lg font-bold text-white">
                    Piyasa Satışı: <span className="text-neon-red">{sellFor.asset}</span>
                  </h2>
                  <button
                    type="button"
                    onClick={() => {
                      setSellFor(null);
                      setSellMsg(null);
                      setSellDone(null);
                    }}
                    className="text-bunker-muted hover:text-white"
                  >
                    ✕
                  </button>
                </div>

                {sellDone ? (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 py-3">
                      <p className="eyebrow text-neon-green">SATIŞ TAMAMLANDI</p>
                      <p className="mt-1 font-mono text-sm text-white">
                        {sellDone.asset}: ₺{sellDone.price} birim fiyattan satıldı · {sellDone.qty} {sellDone.asset} (Toplam ₺{sellDone.total})
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">Emir no: {sellDone.order}</p>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="button"
                        onClick={() => {
                          setSellFor(null);
                          setSellDone(null);
                          setSellMsg(null);
                        }}
                        className="ui-button ui-button-primary"
                      >
                        Tamam
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="space-y-1 font-mono text-xs text-bunker-muted">
                      <p>Anlık piyasa fiyatı: <span className="text-white">{sellFor.price_try != null ? `₺${fmtPrice(sellFor.price_try, sellFor.price_try < 1 ? 6 : 2)}` : "—"}</span></p>
                      <p>Boşta bakiye: <span className="text-white">{fmtPrice(sellFor.free, 6)} {sellFor.asset}</span></p>
                      <p>Tahmini tutar: <span className="text-white font-bold">₺{fmtPrice(sellQtyNum * (sellFor.price_try ?? 0))}</span></p>
                    </div>

                    <label>
                      <span className="eyebrow">SATILACAK MİKTAR ({sellFor.asset})</span>
                      <input
                        value={sellQty}
                        onChange={(e) => setSellQty(e.target.value)}
                        inputMode="decimal"
                        className="input mt-1 w-full font-mono text-sm"
                      />
                      <input
                        type="range"
                        min={0}
                        max={sellFor.free}
                        step={Math.max(0.000001, Number((sellFor.free / 100).toFixed(6)))}
                        value={sellQtyNum}
                        onChange={(e) => setSellQty(e.target.value)}
                        className="mt-2 w-full accent-[color:var(--neon-red,#ef4444)]"
                      />
                      <div className="flex justify-between font-mono text-[9px] text-bunker-muted">
                        <span>0</span>
                        <span>{fmtPrice(sellFor.free, 6)} {sellFor.asset}</span>
                      </div>
                      {/* Hızlı % çipleri (mobil-first: tek dokunuşla miktar doldur) */}
                      <div className="mt-2 grid grid-cols-4 gap-1.5">
                        {[25, 50, 75, 100].map((pct) => (
                          <button
                            key={pct}
                            type="button"
                            onClick={() => setSellQty(String(Number((sellFor.free * pct) / 100).toFixed(6)))}
                            className={`rounded-lg border px-2 py-1.5 font-mono text-[11px] font-bold transition-colors ${
                              pct === 100
                                ? "border-neon-red/50 bg-neon-red/10 text-neon-red hover:bg-neon-red/25"
                                : "border-bunker-700 bg-bunker-900/60 text-bunker-muted hover:border-neon-red/40 hover:text-neon-red"
                            }`}
                          >
                            %{pct}
                          </button>
                        ))}
                      </div>
                    </label>

                    {sellMsg && (
                      <p className={`mt-2 text-xs ${sellMsg.ok ? "text-neon-green" : "text-neon-red"}`}>
                        {sellMsg.text}
                      </p>
                    )}

                    <p className="font-mono text-[10px] text-yellow-300/80">
                      Dikkat: Gerçek piyasa emri gönderilir ve iptal edilemez.
                    </p>

                    <div className="flex justify-end gap-2 pt-2">
                      <button
                        type="button"
                        onClick={() => {
                          setSellFor(null);
                          setSellMsg(null);
                        }}
                        className="ui-button ui-button-secondary"
                      >
                        İptal
                      </button>
                      <button
                        type="button"
                        onClick={confirmSell}
                        disabled={sellBusy || !sellQty.trim() || sellQtyNum <= 0}
                        className="rounded border border-neon-red/60 bg-neon-red/20 px-4 py-2 font-mono text-xs font-bold text-neon-red hover:bg-neon-red/30 disabled:opacity-40"
                      >
                        {sellBusy ? "Gönderiliyor..." : "ONAYLA — SAT"}
                      </button>
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}

          {/* MODAL: ALIM YAP (BUY) */}
          {buyOpen && (
            <div className="fixed inset-0 z-[210] grid place-items-center bg-black/80 p-4 overflow-y-auto" role="dialog" aria-modal="true">
              <section className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-mono text-lg font-bold text-white">Piyasa Alımı Yap</h2>
                  <button type="button" onClick={() => setBuyOpen(false)} className="text-bunker-muted hover:text-white">✕</button>
                </div>

                {buyDone ? (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 py-3">
                      <p className="eyebrow text-neon-green">ALIM TAMAMLANDI</p>
                      <p className="mt-1 font-mono text-sm text-white">
                        {buyDone.asset}: ₺{buyDone.price} fiyattan alındı · {buyDone.qty} {buyDone.asset}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">Emir no: {buyDone.order}</p>
                    </div>
                    <div className="flex justify-end">
                      <button type="button" onClick={() => { setBuyOpen(false); setBuyDone(null); }} className="ui-button ui-button-primary">Tamam</button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="relative block">
                      <span className="eyebrow">SEMBOL ARAMA</span>
                      <input
                        value={buyInput}
                        onChange={(e) => {
                          setBuyInput(e.target.value);
                          setBuyAsset("");
                        }}
                        placeholder="Örn: BTC, ETH, SOL..."
                        className="input mt-1 w-full font-mono text-xs"
                      />
                      {buyMatches.length > 0 && !buyAsset && (
                        <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg border border-bunker-600 bg-bunker-900 shadow-2xl">
                          {buyMatches.map((asset) => (
                            <button
                              key={asset}
                              type="button"
                              onMouseDown={(e) => e.preventDefault()}
                              onClick={() => selectBuyAsset(asset)}
                              className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-bunker-800"
                            >
                              <span className="font-mono text-xs font-bold text-white">{asset}TRY</span>
                              <span className="font-mono text-[10px] text-bunker-muted">
                                {liveTicks[asset]?.price ? `₺${fmtPrice(Number(liveTicks[asset]?.price))}` : ""}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg border border-bunker-700 bg-bunker-900/60 p-2.5">
                        <p className="eyebrow">ANLIK FİYAT</p>
                        <p className="font-mono text-sm font-bold text-white">
                          {buyPrice ? `₺${fmtPrice(buyPrice, buyPrice < 1 ? 6 : 2)}` : "—"}
                        </p>
                      </div>
                      <div className="rounded-lg border border-bunker-700 bg-bunker-900/60 p-2.5">
                        <p className="eyebrow">TRY BAKİYESİ</p>
                        <p className="font-mono text-sm font-bold text-cyan-300">₺{fmtPrice(buyTryFree)}</p>
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center justify-between">
                        <span className="eyebrow">ALIM TUTARI (TRY)</span>
                        <span className="font-mono text-[10px] text-bunker-muted">
                          ~{buyPrice ? fmtPrice(buyAmountNum / buyPrice, 6) : "—"} {buyAsset || "birim"}
                        </span>
                      </div>
                      <input
                        type="number"
                        min="10"
                        step="10"
                        value={buyAmount}
                        onChange={(e) => setBuyAmount(e.target.value)}
                        className="input mt-1 w-full font-mono text-xs"
                      />
                      {/* Hızlı tutar çipleri (mobil-first: tek dokunuşla tutar doldur) */}
                      <div className="mt-2 grid grid-cols-4 gap-1.5">
                        {[250, 500, 1000, 2000].map((amt) => (
                          <button
                            key={amt}
                            type="button"
                            onClick={() => setBuyAmount(String(Math.min(amt, Math.floor(buyTryFree))))}
                            disabled={buyTryFree < 10}
                            className="rounded-lg border border-bunker-700 bg-bunker-900/60 px-2 py-1.5 font-mono text-[11px] font-bold text-bunker-muted hover:border-cyan-400/40 hover:text-cyan-300 disabled:opacity-30 transition-colors"
                          >
                            ₺{amt}
                          </button>
                        ))}
                      </div>
                      <div className="mt-1.5 grid grid-cols-3 gap-1.5">
                        {[25, 50, 100].map((pct) => (
                          <button
                            key={pct}
                            type="button"
                            onClick={() => setBuyAmount(String(Math.max(10, Math.floor((buyTryFree * pct) / 100))))}
                            disabled={buyTryFree < 10}
                            className={`rounded-lg border px-2 py-1.5 font-mono text-[11px] font-bold transition-colors ${
                              pct === 100
                                ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-300 hover:bg-cyan-400/25"
                                : "border-bunker-700 bg-bunker-900/60 text-bunker-muted hover:border-cyan-400/40 hover:text-cyan-300"
                            } disabled:opacity-30`}
                          >
                            %{pct}
                          </button>
                        ))}
                      </div>
                      <input
                        type="range"
                        min="10"
                        max={Math.max(10, Math.floor(buyTryFree))}
                        step="10"
                        value={Math.min(buyAmountNum || 10, Math.max(10, Math.floor(buyTryFree)))}
                        onChange={(e) => setBuyAmount(e.target.value)}
                        className="mt-2 w-full accent-[color:var(--neon-green,#22c55e)]"
                      />
                    </div>

                    {buyMsg && (
                      <p className={`text-xs ${buyMsg.ok ? "text-neon-green" : "text-neon-red"}`}>
                        {buyMsg.text}
                      </p>
                    )}

                    {(role || "").toLowerCase() === "admin" && (
                      <label className="flex cursor-pointer select-none items-center gap-2 rounded-lg border border-bunker-700 bg-bunker-900/60 px-3 py-2">
                        <input
                          type="checkbox"
                          checked={buyNotify}
                          onChange={(e) => setBuyNotify(e.target.checked)}
                          className="h-4 w-4 accent-[color:var(--neon-green,#22c55e)]"
                        />
                        <span className="font-mono text-xs text-bunker-muted">
                          Bildirim gönder
                          <span className="mt-0.5 block text-[10px] text-bunker-muted/70">
                            Bildirim Ayarları&apos;nda seçili kullanıcılara sembol + fiyat bildirilir (tutar gönderilmez)
                          </span>
                        </span>
                      </label>
                    )}

                    <div className="flex justify-end gap-2 pt-2">
                      <button type="button" onClick={() => setBuyOpen(false)} className="ui-button ui-button-secondary">İptal</button>
                      <button
                        type="button"
                        onClick={confirmBuy}
                        disabled={buyBusy || !(buyAsset || buyInput.trim())}
                        className="ui-button ui-button-primary disabled:opacity-40"
                      >
                        {buyBusy ? "Gönderiliyor..." : `AL — ₺${fmtPrice(buyAmountNum)}`}
                      </button>
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}

          {/* MODAL: AYARLAR (SETTINGS) */}
          {settingsOpen && (
            <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4 overflow-y-auto" role="dialog" aria-modal="true">
              <section className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-mono text-lg font-bold text-white">Binance TR API Ayarları</h2>
                  <button type="button" onClick={() => setSettingsOpen(false)} className="text-bunker-muted hover:text-white">✕</button>
                </div>

                <div className="space-y-3">
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-yellow-400/30 bg-yellow-400/5 px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={sellToggle}
                      onChange={(e) => setSellToggle(e.target.checked)}
                      disabled={saving}
                      className="mt-0.5 h-3.5 w-3.5 accent-[color:var(--yellow-300,#facc15)]"
                    />
                    <span>
                      <span className="eyebrow block text-yellow-300">GERÇEK İŞLEM & EMİR ANAHTARI</span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-bunker-muted">
                        Etkinleştirildiğinde piyasa satışı ve Stop-Loss / Take-Profit (OCO) emirleri doğrudan
                        <span className="text-white font-bold"> sizin</span> Binance TR hesabınıza iletilir. Bu anahtar yalnız kendi hesabınızı etkiler.
                      </span>
                    </span>
                  </label>

                  <label>
                    <span className="eyebrow">API KEY</span>
                    <input
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="Binance TR API Key"
                      className="input mt-1 w-full font-mono text-xs"
                    />
                  </label>

                  <label>
                    <span className="eyebrow">API SECRET</span>
                    <input
                      type="password"
                      value={apiSecret}
                      onChange={(e) => setApiSecret(e.target.value)}
                      placeholder="Binance TR API Secret"
                      className="input mt-1 w-full font-mono text-xs"
                    />
                  </label>

                  {keyError && <p className="text-xs text-neon-red">{keyError}</p>}

                  <div className="flex justify-end gap-2 pt-2">
                    <button type="button" onClick={() => setSettingsOpen(false)} className="ui-button ui-button-secondary">İptal</button>
                    {configured && (
                      <button
                        type="button"
                        onClick={saveSellSetting}
                        disabled={saving}
                        className="ui-button ui-button-secondary disabled:opacity-40"
                        title="Gerçek emir anahtarını aç/kapat (API anahtarlarına dokunmaz)"
                      >
                        {saving ? "..." : "İŞLEM DURUMUNU KAYDET"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={saveKeys}
                      disabled={saving || !apiKey.trim() || !apiSecret.trim()}
                      className="ui-button ui-button-primary"
                    >
                      {saving ? "Kaydediliyor..." : configured ? "API ANAHTARLARINI GÜNCELLE" : "BAĞLA VE BAŞLA"}
                    </button>
                  </div>
                </div>
              </section>
            </div>
          )}
          {/* MODAL: İNTERAKTİF POZİSYON GRAFİĞİ (TRADINGVIEW TARZI) */}
          {chartFor && (
            <BinancePositionChartModal
              holding={chartFor}
              livePrice={liveTicks[chartFor.asset]?.price ?? null}
              onClose={() => setChartFor(null)}
              onOrderUpdated={() => {
                loadAcct();
                loadOrd();
                loadOpenOrders();
              }}
              sellEnabled={sellEnabled}
              showToast={showToast}
            />
          )}
        </>
      )}
    </main>
  );
}
