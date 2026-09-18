"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { localDateInput } from "../lib/format";
import { useLiveMessages } from "../lib/liveSocket";
import RequireAdmin from "../components/RequireAdmin";

type Balance = { asset: string; free: string; locked: string };

type LiveTick = { price?: number; symbol?: string; quote_volume_try?: number | null };

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

const TR_PAGE_SIZE = 25;

// Hacim biçimlendirici: 1,2B / 340M / 12K / 840
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
  if (!ts) return "\u2014";
  return new Date(ts).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const KNOWN_SYMBOLS = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
  "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
  "NEARUSDT",
];

export default function BinanceTrPage() {
  return <RequireAdmin><BinanceTrPageInner /></RequireAdmin>;
}

function BinanceTrPageInner() {
  const [configured, setConfigured] = useState(false);
  const [sellEnabled, setSellEnabled] = useState(false);
  const [sellToggle, setSellToggle] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [keyError, setKeyError] = useState("");

  const [balances, setBalances] = useState<Balance[]>([]);
  const [acctLoading, setAcctLoading] = useState(false);
  const [acctError, setAcctError] = useState("");

  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [ordLoading, setOrdLoading] = useState(false);
  // 50 TL altındaki varlıkları gizle (varsayılan açık)
  const [hideSmall, setHideSmall] = useState(true);
  // Satış modalı
  const [sellFor, setSellFor] = useState<Holding | null>(null);
  const [sellQty, setSellQty] = useState("");
  const [sellBusy, setSellBusy] = useState(false);
  const [sellMsg, setSellMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // ---- ALIM YAP dialogu (piyasa-fiyatından alım, Binance TR stili) ----
  const [buyOpen, setBuyOpen] = useState(false);
  const [buyInput, setBuyInput] = useState("");      // sembol arama metni
  const [buyAsset, setBuyAsset] = useState("");      // seçili base varlık
  const [buyAmount, setBuyAmount] = useState("100"); // TRY tutarı (manuel + slider)
  const [buyBusy, setBuyBusy] = useState(false);
  const [buyMsg, setBuyMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const MATCH_MIN_CHARS = 3;  // Daha garanti eslesme: ilk 3 harften sonra listele (Erkan, 18.09)
  const [buyDone, setBuyDone] = useState<{ order: string; asset: string; qty: string; price: string } | null>(null);
  const [pairs, setPairs] = useState<string[]>([]);  // base varlık listesi (autocomplete)
  const buyAssetRef = useRef("");
  const buyTryFree = useMemo(() => {
    const r = balances.find((b) => b.asset === "TRY");
    return parseFloat(r?.free || "0");
  }, [balances]);
  const buyAmountNum = useMemo(() => {
    const n = parseFloat(buyAmount.replace(",", "."));
    return Number.isFinite(n) ? Math.min(Math.max(n, 0), buyTryFree) : 0;
  }, [buyAmount, buyTryFree]);
  const buyMatches = useMemo(() => {
    const q = buyInput.trim().toUpperCase();
    if (q.length < MATCH_MIN_CHARS) return [];
    // Liste base varlik ("G") tutar; kullanicinin gordugu etiket "GTRY"
    // oldugu icin eslesme gosterilen etiket uzerinden yapilir.
    return pairs.filter((p) => (p + "TRY").includes(q)).slice(0, 8);
  }, [buyInput, pairs]);

  const [tradeDay, setTradeDay] = useState(() => localDateInput());
  const [trades, setTrades] = useState<Trade[]>([]);
  const [daily, setDaily] = useState<DailyPnl | null>(null);
  const [trPage, setTrPage] = useState(1);
  const [trLoading, setTrLoading] = useState(false);
  const [trMeta, setTrMeta] = useState<{ count: number; symbols_scanned: number } | null>(null);

  const check = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setConfigured(d.configured);
        setSellEnabled(Boolean(d.sell_enabled));
        setSellToggle(Boolean(d.sell_enabled));
      }
    } catch { /* */ }
  }, []);

  useEffect(() => { check(); }, [check]);

  const loadAcct = useCallback(async () => {
    setAcctLoading(true);
    setAcctError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/account`, { cache: "no-store" });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Hesap bilgisi alinamadi");
      }
      setBalances((await r.json()).balances || []);
    } catch (e) {
      setAcctError(e instanceof Error ? e.message : "Hesap bilgisi alinamadi");
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

  useEffect(() => {
    if (!configured) return;
    loadAcct();
    loadOrd();
    const a = setInterval(loadAcct, 10_000);
    const o = setInterval(loadOrd, 10_000);
    return () => { clearInterval(a); clearInterval(o); };
  }, [configured, loadAcct, loadOrd]);

  const loadTrades = useCallback(async () => {
    setTrLoading(true);
    try {
      const r = await apiRequest(
        API_BASE + "/api/binance/trades-day?date=" + encodeURIComponent(tradeDay),
        { cache: "no-store" }
      );
      if (r.ok) {
        const d = await r.json();
        setTrades(d.trades || []);
        setDaily(d.daily || null);
        setTrMeta({ count: d.count || 0, symbols_scanned: d.symbols_scanned || 0 });
      }
    } catch { /* */ }
    finally { setTrLoading(false); }
  }, [tradeDay]);

  useEffect(() => { if (configured && tradeDay) loadTrades(); }, [configured, tradeDay, loadTrades]);
  useEffect(() => { setTrPage(1); }, [tradeDay]);

  const saveKeys = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) return;
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(API_BASE + "/api/binance/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim(), real_sell_enabled: sellToggle }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Kaydedilemedi");
      }
      // Secret'ı state'te bırakma — LLM key akışıyla aynı hijyen.
      setApiKey("");
      setApiSecret("");
      setConfigured(true);
      setSettingsOpen(false);
      check();
      loadAcct();
      loadOrd();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayit hatasi");
    } finally {
      setSaving(false);
    }
  };

  const saveSellSetting = async () => {
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(API_BASE + "/api/binance/settings", {
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
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayit hatasi");
    } finally {
      setSaving(false);
    }
  };

  // ---- Canlı fiyat tick'leri (WS) ----
  // Açık pozisyon kolonları anlık güncellenir: fiyat, TRY değeri, K/Z (durum
  // renkli) ve 24s hacim. Yön nabzı için önceki fiyat ref'te tutulur.
  // Alım dialogu da AYNI akışı okur: seçili sembol POST /watch ile 120 sn
  // WS akışına eklenir, delta buradan gelir.
  const [liveTicks, setLiveTicks] = useState<Record<string, LiveTick>>({});
  const [tickDir, setTickDir] = useState<Record<string, "up" | "down">>({});
  const pricesRef = useRef<Record<string, number>>({});

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
    setLiveTicks(d.ticks);
    if (Object.keys(dirs).length) setTickDir((prev) => ({ ...prev, ...dirs }));
  });

  // Polling değerleriyle canlı tick'leri birleştir — WS kapalıysa otomatik
  // polling değerine düşer (holdings her 10 sn'de yenileniyor).
  const mergedHoldings = useMemo(() => holdings.map((h) => {
    const t = liveTicks[h.asset];
    const price = h.asset === "TRY" ? 1.0 : Number(t?.price || 0);
    if (!price) return { ...h, volume_try: t?.quote_volume_try ?? null };
    const cost = h.avg_cost_try;
    const pnl_try = cost ? (price - cost) * h.total : h.pnl_try;
    const pnl_pct = cost ? (price - cost) / cost * 100 : h.pnl_pct;
    return {
      ...h,
      price_try: price,
      value_try: h.total * price,
      pnl_try,
      pnl_pct,
      volume_try: t?.quote_volume_try ?? null,
    };
  }), [holdings, liveTicks]);

  const nonZero = balances.filter((b) => parseFloat(b.free) > 0 || parseFloat(b.locked) > 0);

  // Günün işlemleri sayfalama (25/sayfa)
  const trTotalPages = Math.max(1, Math.ceil(trades.length / TR_PAGE_SIZE));
  const trPageSafe = Math.min(trPage, trTotalPages);
  const trPageRows = trades.slice((trPageSafe - 1) * TR_PAGE_SIZE, trPageSafe * TR_PAGE_SIZE);

  // 50 TL altını gizle (fiyatı çözülemeyenler gizlenmez — değeri bilinmiyor)
  const visibleHoldings = useMemo(() => {
    if (!hideSmall) return mergedHoldings;
    return mergedHoldings.filter((h) => h.value_try == null || h.value_try >= 50);
  }, [mergedHoldings, hideSmall]);

  // Alım dialogu fiyatı: AYNI WS akışından (POST /watch katkısı); WS gecikirse
  // son polling fiyatına düşür.
  const buyPrice = buyAsset
    ? Number(liveTicks[buyAsset]?.price || mergedHoldings.find((x) => x.asset === buyAsset)?.price_try || 0)
    : 0;

  const openSell = (h: Holding) => {
    setSellFor(h);
    setSellQty(String(h.free));
    setSellMsg(null);
  };

  const confirmSell = async () => {
    if (!sellFor || sellBusy) return;
    const qty = parseFloat(sellQty.replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      setSellMsg({ ok: false, text: "Gecerli bir miktar gir." });
      return;
    }
    if (qty > sellFor.free + 1e-12) {
      setSellMsg({ ok: false, text: "Miktar bosda olan bakiyeden buyuk olamaz." });
      return;
    }
    setSellBusy(true);
    setSellMsg(null);
    try {
      const r = await apiRequest(API_BASE + "/api/binance/sell", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset: sellFor.asset, quantity: qty, confirmation: "REAL_SELL" }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || `Satis emri gonderilemedi (HTTP ${r.status})`);
      setSellMsg({ ok: true, text: `Satis emri gonderildi (emir no: ${d.order_id ?? "—"}).` });
      loadAcct();
      loadOrd();
    } catch (e) {
      setSellMsg({ ok: false, text: e instanceof Error ? e.message : "Satis emri gonderilemedi" });
    } finally {
      setSellBusy(false);
    }
  };

  // ---- ALIM YAP dialogu işlemleri ----
  const openBuy = async () => {
    setBuyOpen(true);
    setBuyMsg(null);
    setBuyDone(null);
    setBuyInput("");
    setBuyAsset("");
    setBuyAmount("100");
    try {
      const r = await apiRequest(API_BASE + "/api/market-symbols");
      const d = await r.json().catch(() => ({}));
      const list = (Array.isArray(d.symbols) ? d.symbols : [])
        .map((s: string) => String(s).toUpperCase().replace(/TRY$/, ""))
        .filter((s: string) => s && s !== "TRY");
      setPairs(Array.from(new Set(list)));
    } catch { /* autocomplete boş kalır; manuel yazıp seçemez ama hata balonu şart değil */ }
  };

  const selectBuyAsset = async (asset: string) => {
    setBuyAsset(asset);
    setBuyInput(asset);
    setBuyMsg(null);
    // WS akışına kat: delta aynı binance_price deltasından gelir (60 sn'de bir tazele).
    buyAssetRef.current = asset;
    try {
      await apiRequest(API_BASE + "/api/binance/watch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: asset }),
      });
    } catch { /* WS katkısı başarısızsa anlık fiyat polling'e düşer */ }
  };

  // Dialog açıkken seçili sembolü 60 sn'de bir WS akışında tut.
  useEffect(() => {
    if (!buyOpen || !buyAsset) return;
    const t = setInterval(() => {
      const asset = buyAssetRef.current;
      if (asset) {
        apiRequest(API_BASE + "/api/binance/watch", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: asset }),
        }).catch(() => { /* sessiz */ });
      }
    }, 60000);
    return () => clearInterval(t);
  }, [buyOpen, buyAsset]);

  const confirmBuy = async () => {
    if (buyBusy) return;
    const asset = buyAsset || buyInput.trim().toUpperCase().replace(/TRY$/, "");
    if (!asset) {
      setBuyMsg({ ok: false, text: "Once eslesen sembolu sec." });
      return;
    }
    if (!Number.isFinite(buyAmountNum) || buyAmountNum < 10) {
      setBuyMsg({ ok: false, text: "Tutar gecerli degil (minimum ₺10)." });
      return;
    }
    if (buyAmountNum > buyTryFree + 1e-9) {
      setBuyMsg({ ok: false, text: `TRY bakiyesi yetersiz (bosta ₺${fmtPrice(buyTryFree)}).` });
      return;
    }
    setBuyBusy(true);
    setBuyMsg(null);
    try {
      const r = await apiRequest(API_BASE + "/api/binance/buy", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset, amount_try: buyAmountNum, confirmation: "REAL_BUY" }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.detail || `Alim emri gonderilemedi (HTTP ${r.status})`);
      const qty = d.executed_qty != null ? fmtPrice(d.executed_qty, 6) : (buyPrice ? fmtPrice(buyAmountNum / buyPrice, 6) : "—");
      const price = d.avg_price != null ? fmtPrice(d.avg_price, d.avg_price < 1 ? 6 : 2) : (buyPrice ? fmtPrice(buyPrice, buyPrice < 1 ? 6 : 2) : "—");
      setBuyDone({ order: d.order_id ?? "—", asset, qty, price });
      // Sayfa refresh OLMADAN bilgiler yenilenir (Erkan talebi).
      loadAcct();
      loadTrades();
    } catch (e) {
      setBuyMsg({ ok: false, text: e instanceof Error ? e.message : "Alim emri gonderilemedi" });
    } finally {
      setBuyBusy(false);
    }
  };

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">BINANCE TR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Canli Hesap</h1>
          <p className="mt-1 text-sm text-bunker-muted">Gerçek Binance TR bakiyesi, TRY degerleri ve islem gecmisi — gerçek satış {sellEnabled ? "açık: onay adımıyla SAT butonu piyasa emri gönderir" : "kapalı: Ayarlar > 'GERÇEK SATIŞ' anahtarından açılır"}</p>
        </div>
        <div className="flex items-center gap-2">
          {configured && (
            <span className={"rounded border px-2 py-1 font-mono text-[10px] " + (sellEnabled ? "border-yellow-300/50 bg-yellow-300/10 text-yellow-300" : "border-bunker-600 bg-bunker-800 text-bunker-muted")}>
              {sellEnabled ? "GERÇEK SATIŞ AÇIK" : "GERÇEK SATIŞ KAPALI"}
            </span>
          )}
          <button type="button" onClick={openBuy} disabled={!configured || !sellEnabled}
            title={!configured ? "Once API anahtari gir" : !sellEnabled ? "Gercek islem kapali (Ayarlar > GERCEK SATIS)" : "Piyasa fiyatindan alim yap"}
            className="ui-button ui-button-primary disabled:opacity-40">ALIM YAP</button>
          <button type="button" onClick={() => { setSellToggle(sellEnabled); setKeyError(""); setSettingsOpen(true); }} className="ui-button ui-button-secondary">AYARLAR</button>
        </div>
      </div>

      {settingsOpen && (
        <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4" role="dialog" aria-modal="true">
          <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-mono text-lg font-bold text-white">Binance TR API Anahtarlari</h2>
              <button type="button" onClick={() => setSettingsOpen(false)} className="text-bunker-muted hover:text-white">X</button>
            </div>
            <p className="text-xs text-bunker-muted mb-4">Fernet sifreli kaydedilir. Satis emirleri yalnizca {sellEnabled ? "bu ekrandaki onay adimindan sonra" : "sunucuda ENABLE_REAL_BINANCE_SELL=1 etkinse"} gonderilir.</p>
            <div className="space-y-3">
              <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-yellow-300/30 bg-yellow-300/5 px-3 py-2.5">
                <input type="checkbox" checked={sellToggle} onChange={(e) => setSellToggle(e.target.checked)}
                  disabled={saving}
                  className="mt-0.5 h-3.5 w-3.5 accent-[color:var(--yellow-300,#facc15)]" />
                <span>
                  <span className="eyebrow block text-yellow-300">GERÇEK SATIŞ — PANEL ANAHTARI</span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-bunker-muted">
                    Gerçek emirler gönderilir ve iptal edilemez. SAT butonu ile hesaptaki varlıklar piyasa fiyatından satılır. SSH'siz aç/kapa: env yoksa panel karar verir, env "1" ise her zaman açık, env "0" ise kapalı.
                  </span>
                </span>
              </label>
              <label>
                <span className="eyebrow">API KEY</span>
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Binance TR API Key" className="input mt-1 w-full font-mono text-xs" />
              </label>
              <label>
                <span className="eyebrow">API SECRET</span>
                <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder="Binance TR API Secret" className="input mt-1 w-full font-mono text-xs" />
              </label>
              {keyError && <p className="text-xs text-neon-red">{keyError}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setSettingsOpen(false)} className="ui-button ui-button-secondary">IPTAL</button>
                <button type="button" onClick={saveSellSetting} disabled={saving}
                  className="ui-button ui-button-secondary disabled:opacity-40">
                  {saving ? "KAYDEDILIYOR..." : "SATIŞ ANAHTARINI UYGULA"}
                </button>
                <button type="button" onClick={saveKeys} disabled={saving || !apiKey.trim() || !apiSecret.trim()} className="ui-button ui-button-primary">
                  {saving ? "KAYDEDILIYOR..." : "API ANAHTARLARINI KAYDET"}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* ALIM YAP dialogu — Binance TR stili: sembol autocomplete + WS anlık fiyat +
          TRY bakiyesi + manuel/slider TRY tutarı + piyasa alımı + başarılı confirm */}
      {buyOpen && (
        <div className="fixed inset-0 z-[210] grid place-items-center bg-black/80 p-4" role="dialog" aria-modal="true">
          <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-mono text-lg font-bold text-white">Alım Yap</h2>
              <button type="button" onClick={() => setBuyOpen(false)} className="text-bunker-muted hover:text-white">X</button>
            </div>
            {buyDone ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 py-3">
                  <p className="eyebrow text-neon-green">ALIM TAMAMLANDI</p>
                  <p className="mt-1 font-mono text-sm text-white">
                    {buyDone.asset}: şu fiyattan alındı — ₺{buyDone.price} / birim · {buyDone.qty} {buyDone.asset}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">Emir no: {buyDone.order}</p>
                </div>
                <p className="text-[11px] text-bunker-muted">Bakiye ve günün işlemleri sayfa refresh olmadan yenilendi.</p>
                <div className="flex justify-end">
                  <button type="button" onClick={() => { setBuyOpen(false); setBuyDone(null); }} className="ui-button ui-button-primary">TAMAM</button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="relative block">
                  <span className="eyebrow">SEMBOL</span>
                  <input value={buyInput} onChange={(e) => { setBuyInput(e.target.value); setBuyAsset(""); }}
                    placeholder="Ilk uc harfi gir — eslesenler listelenir"
                    className="input mt-1 w-full font-mono text-xs" />
                  {buyMatches.length > 0 && !buyAsset && (
                    <div className="absolute z-10 mt-1 w-full max-h-56 overflow-y-auto rounded-lg border border-bunker-600 bg-bunker-900 shadow-2xl">
                      {buyMatches.map((asset) => (
                        <button key={asset} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => selectBuyAsset(asset)}
                          className="flex w-full items-center justify-between px-3 py-2 text-left transition-colors hover:bg-bunker-800">
                          <span className="font-mono text-xs font-bold text-white">{asset}TRY</span>
                          <span className="font-mono text-[10px] text-bunker-muted">
                            {liveTicks[asset]?.price ? `₺${fmtPrice(Number(liveTicks[asset]?.price), Number(liveTicks[asset]?.price) < 1 ? 6 : 2)}` : ""}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {/* WS anlık fiyat + TRY bakiyesi */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-bunker-700 bg-bunker-900/60 px-3 py-2">
                    <p className="eyebrow">ANLIK FIYAT</p>
                    <p className={`mt-0.5 font-mono text-sm font-bold ${buyPrice ? (tickDir[buyAsset] === "down" ? "text-neon-red" : "text-neon-green") : "text-bunker-muted"}`}>
                      {buyPrice ? `₺${fmtPrice(buyPrice, buyPrice < 1 ? 6 : 2)}` : "—"}
                      {buyPrice ? <span className="ml-1 text-[9px] font-normal text-bunker-muted">WS</span> : null}
                    </p>
                  </div>
                  <div className="rounded-lg border border-bunker-700 bg-bunker-900/60 px-3 py-2">
                    <p className="eyebrow">TRY BAKIYESI</p>
                    <p className="mt-0.5 font-mono text-sm font-bold text-white">₺{fmtPrice(buyTryFree)}</p>
                  </div>
                </div>
                {/* TRY tutarı: manuel kutu + soldan-sağa slider */}
                <div>
                  <div className="flex items-center justify-between">
                    <span className="eyebrow">ALIM TUTARI (TRY)</span>
                    <span className="font-mono text-[10px] text-bunker-muted">
                      ~{buyPrice ? fmtPrice(buyAmountNum / buyPrice, 6) : "—"} {buyAsset || "birim"}
                    </span>
                  </div>
                  <input type="number" min="10" step="10" value={buyAmount}
                    onChange={(e) => setBuyAmount(e.target.value)}
                    className="input mt-1 w-full font-mono text-xs" />
                  <input type="range" min="10" max={Math.max(10, Math.floor(buyTryFree))} step="10"
                    value={Math.min(buyAmountNum || 10, Math.max(10, Math.floor(buyTryFree)))}
                    onChange={(e) => setBuyAmount(e.target.value)}
                    className="mt-2 w-full accent-[color:var(--neon-green,#22c55e)]" />
                  <div className="flex justify-between font-mono text-[9px] text-bunker-muted">
                    <span>₺10</span><span>₺{fmtPrice(Math.max(10, Math.floor(buyTryFree)))}</span>
                  </div>
                </div>
                {buyMsg && <p className={"text-xs " + (buyMsg.ok ? "text-neon-green" : "text-neon-red")}>{buyMsg.text}</p>}
                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" onClick={() => setBuyOpen(false)} className="ui-button ui-button-secondary">IPTAL</button>
                  <button type="button" onClick={confirmBuy} disabled={buyBusy || !(buyAsset || buyInput.trim())}
                    className="ui-button ui-button-primary disabled:opacity-40">
                    {buyBusy ? "GONDERILIYOR..." : `AL — ₺${fmtPrice(buyAmountNum)} PİYASA EMRİ`}
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {!configured ? (
        <section className="card mt-4 flex flex-col items-center gap-4 py-12 text-center">
          <p className="text-4xl">🔑</p>
          <p className="text-sm text-bunker-muted">Henuz Binance TR API anahtarlari yapilandirilmamis.</p>
          <button type="button" onClick={() => setSettingsOpen(true)} className="ui-button ui-button-primary">API ANAHTARINI GIR</button>
        </section>
      ) : (
        <>
          {acctError && <div className="mt-4 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{acctError}</div>}
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {nonZero.length === 0 && !acctLoading && (
              <div className="card col-span-full"><p className="text-sm text-bunker-muted">Non-zero bakiye bulunamadi.</p></div>
            )}
            {nonZero.slice(0, 8).map((b) => (
              <div key={b.asset} className="card">
                <p className="eyebrow">{b.asset}</p>
                <p className="mt-1 font-mono text-lg font-bold text-white">{fmtPrice(b.free)}</p>
                {parseFloat(b.locked) > 0 && <p className="text-[10px] text-bunker-muted">{fmtPrice(b.locked)} kilitli</p>}
              </div>
            ))}
          </div>

          <section className="card mt-5">
            <div className="ui-section-header">
              <div>
                <p className="eyebrow text-neon-green">SEMBOL BAKİYELERİ</p>
                <h2 className="font-mono text-lg font-bold text-white">Varlıklar ve TRY Değerleri</h2>
              </div>
              <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
                <input type="checkbox" checked={hideSmall} onChange={(e) => setHideSmall(e.target.checked)}
                  className="h-3.5 w-3.5 accent-[color:var(--neon-green,#22c55e)]" />
                50 TL altını gizle
              </label>
              <span className={"font-mono text-[10px] text-bunker-muted animate-pulse" + (ordLoading ? "" : " invisible")} aria-hidden="true">Yukleniyor...</span>
            </div>
            {visibleHoldings.length === 0 ? (
              <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
                {holdings.length === 0 ? "Gosterilecek varlik yok." : "Filtreye uyan varlik yok (50 TL altindakiler gizli)."}
              </div>
            ) : (
              <div className="table-scroll mt-3">
                <table className="data-table">
                  <thead><tr><th>Sembol</th><th>Miktar</th><th>Kilitli</th><th>Alım Maliyeti</th><th>Güncel Fiyat</th><th>24s Hacim</th><th>Anlık K/Z</th><th>TRY Deger</th><th></th></tr></thead>
                  <tbody>
                    {visibleHoldings.map((h) => {
                      const pnlToneCls = h.pnl_try == null ? "" : h.pnl_try >= 0 ? "text-neon-green" : "text-neon-red";
                      const dir = tickDir[h.asset];
                      return (
                        <tr key={h.asset}>
                          <td>
                            <span className="font-mono font-bold text-white">{h.asset}</span>
                            {dir && h.asset !== "TRY" && (
                              <span className={`ml-1.5 font-mono text-[9px] ${dir === "up" ? "text-neon-green" : "text-neon-red"}`}>
                                {dir === "up" ? "▲" : "▼"}
                              </span>
                            )}
                          </td>
                          <td className="font-mono text-xs">{fmtPrice(h.free, 6)}</td>
                          <td className="font-mono text-xs text-bunker-muted">{h.locked > 0 ? fmtPrice(h.locked, 6) : "—"}</td>
                          <td className="font-mono text-xs text-bunker-muted">{h.avg_cost_try != null ? `₺${fmtPrice(h.avg_cost_try, h.avg_cost_try < 1 ? 6 : 2)}` : "—"}</td>
                          <td className={`font-mono text-xs tabular-nums whitespace-nowrap ${dir ? (dir === "up" ? "text-neon-green" : "text-neon-red") : "text-white"}`}>
                            {h.price_try != null ? `₺${fmtPrice(h.price_try, h.price_try < 1 ? 6 : 2)}` : "—"}
                          </td>
                          <td className="font-mono text-xs text-bunker-muted tabular-nums whitespace-nowrap">{h.asset === "TRY" ? "—" : fmtVolume(h.volume_try)}</td>
                          <td className={`font-mono text-xs font-bold tabular-nums whitespace-nowrap ${pnlToneCls}`}>
                            {h.pnl_try != null ? `₺${h.pnl_try >= 0 ? "+" : "−"}${fmtPrice(Math.abs(h.pnl_try))}` : "—"}
                            {h.pnl_pct != null ? (
                              <span className="ml-1 font-normal">({h.pnl_pct >= 0 ? "+" : "−"}%{fmtPrice(Math.abs(h.pnl_pct), 2)})</span>
                            ) : null}
                          </td>
                          <td className={`font-mono text-xs font-bold tabular-nums whitespace-nowrap ${h.value_try != null ? "text-white" : "text-bunker-muted"}`}>
                            {h.value_try != null ? `₺${fmtPrice(h.value_try)}` : "fiyat yok"}
                          </td>
                          <td className="text-right">
                            <button
                              type="button"
                              onClick={() => openSell(h)}
                              disabled={!sellEnabled || h.free <= 0 || h.asset === "TRY" || h.price_try == null}
                              title={!sellEnabled ? "Gerçek satış kapalı (Ayarlar > GERÇEK SATIŞ)" : h.asset === "TRY" ? "TRY satılamaz" : h.price_try == null ? "Piyasa fiyatı bulunamadı" : h.free <= 0 ? "Boşta bakiye yok" : "Piyasa fiyatından sat"}
                              className="rounded border border-neon-red/50 bg-neon-red/10 px-2.5 py-1 font-mono text-[11px] font-bold text-neon-red transition-colors hover:bg-neon-red/20 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              {sellEnabled ? "SAT" : "SAT (KAPALI)"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ---- Satış onay modalı ---- */}
          {sellFor && sellEnabled && (
            <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4" role="dialog" aria-modal="true">
              <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-mono text-lg font-bold text-white">
                    SAT: <span className="text-neon-red">{sellFor.asset}</span>
                  </h2>
                  <button type="button" onClick={() => { setSellFor(null); setSellMsg(null); }} className="text-bunker-muted hover:text-white">X</button>
                </div>
                <div className="mb-4 space-y-1 font-mono text-xs text-bunker-muted">
                  <p>Anlık piyasa fiyatı: <span className="text-white">{sellFor.price_try != null ? `₺${fmtPrice(sellFor.price_try, sellFor.price_try < 1 ? 6 : 2)}` : "—"}</span></p>
                  <p>Boşta bakiye: <span className="text-white">{fmtPrice(sellFor.free, 6)} {sellFor.asset}</span>{sellFor.locked > 0 ? ` · kilitli ${fmtPrice(sellFor.locked, 6)}` : ""}</p>
                  <p>Tahmini tutar: <span className="text-white">
                    ₺{fmtPrice((parseFloat(sellQty.replace(",", ".")) || 0) * (sellFor.price_try ?? 0))}
                  </span></p>
                </div>
                <label>
                  <span className="eyebrow">SATILACAK MİKTAR ({sellFor.asset})</span>
                  <input value={sellQty} onChange={(e) => setSellQty(e.target.value)} inputMode="decimal"
                    className="input mt-1 w-full font-mono text-sm" />
                </label>
                {sellMsg && (
                  <p className={`mt-3 text-xs ${sellMsg.ok ? "text-neon-green" : "text-neon-red"}`}>{sellMsg.text}</p>
                )}
                <p className="mt-3 font-mono text-[10px] text-yellow-300/80">
                  Dikkat: GERÇEK piyasa emri gönderilir ve iptal edilemez. Emir MARKET tipinde, sembol {sellFor.asset}_TRY yoksa {sellFor.asset}_USDT üzerinde açılır. Sunucu tarafında gerçek satış {sellEnabled ? "AÇIK" : "KAPALI"}.
                </p>
                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" onClick={() => { setSellFor(null); setSellMsg(null); }} className="ui-button ui-button-secondary">IPTAL</button>
                  <button type="button" onClick={confirmSell} disabled={sellBusy || !sellQty.trim()}
                    className="rounded border border-neon-red/60 bg-neon-red/20 px-4 py-2 font-mono text-xs font-bold text-neon-red transition-colors hover:bg-neon-red/30 disabled:cursor-not-allowed disabled:opacity-40">
                    {sellBusy ? "GONDERILIYOR..." : "ONAYLA — SAT"}
                  </button>
                </div>
              </section>
            </div>
          )}

          <section className="card mt-5">
            <div className="ui-section-header">
              <div>
                <p className="eyebrow text-neon-green">GECMIS ISLEMLER</p>
                <h2 className="font-mono text-lg font-bold text-white">Günün İşlemleri</h2>
              </div>
              {trLoading && <span className="font-mono text-[10px] text-bunker-muted animate-pulse">Taranıyor...</span>}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label>
                <span className="font-mono text-[10px] text-bunker-muted mr-1">Gün</span>
                <input type="date" value={tradeDay} onChange={(e) => setTradeDay(e.target.value)} className="input font-mono text-xs" />
              </label>
              <button type="button" onClick={loadTrades} disabled={trLoading}
                className="ui-button ui-button-secondary disabled:opacity-40">⟳ Tazele</button>
              {trMeta && !trLoading && (
                <span className="font-mono text-[10px] text-bunker-muted">
                  {trMeta.count} işlem · {trMeta.symbols_scanned} sembol tarandı
                </span>
              )}
            </div>
            {/* Günlük kar/zarar özeti — tablonun üstünde (Erkan kararı, 18.09) */}
            {daily && trades.length > 0 && !trLoading && (
              <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <div className="card">
                  <p className="eyebrow">GÜNLÜK NET K/Z</p>
                  <p className={`mt-1 font-mono text-lg font-bold ${daily.realized_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                    {daily.realized_pnl_try >= 0 ? "+" : "−"}₺{fmtPrice(Math.abs(daily.realized_pnl_try))}
                  </p>
                </div>
                <div className="card">
                  <p className="eyebrow">BRÜT K/Z</p>
                  <p className={`mt-1 font-mono text-lg font-bold ${daily.gross_pnl_try >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                    {daily.gross_pnl_try >= 0 ? "+" : "−"}₺{fmtPrice(Math.abs(daily.gross_pnl_try))}
                  </p>
                </div>
                <div className="card">
                  <p className="eyebrow">KAPANIŞ</p>
                  <p className="mt-1 font-mono text-lg font-bold text-white">
                    <span className="text-neon-green">{daily.wins} kazanç</span>
                    {" · "}
                    <span className="text-neon-red">{daily.losses} kayıp</span>
                  </p>
                </div>
                <div className="card">
                  <p className="eyebrow">EŞLEŞMEMİŞ</p>
                  <p className="mt-1 font-mono text-lg font-bold text-bunker-muted">
                    {daily.unmatched} satış
                  </p>
                  <p className="text-[10px] text-bunker-muted">stoğu gün dışından — K/Z gün içi eşleşme olmadan hesaplanmaz</p>
                </div>
              </div>
            )}
            {trades.length === 0 && !trLoading ? (
              <div className="mt-3 rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
                Bu günde işlem yok.
              </div>
            ) : (
              <>
                <div className="table-scroll mt-3">
                  <table className="data-table">
                    <thead><tr><th>Zaman</th><th>Sembol</th><th>Yön</th><th>Alış (Basis)</th><th>Fiyat</th><th>Miktar</th><th>Toplam</th><th>K/Z</th><th>Komisyon</th></tr></thead>
                    <tbody>
                      {trPageRows.map((t) => {
                        const pnl = t.realized_pnl_try;
                        const pnlCls = pnl == null ? "text-bunker-muted" : pnl >= 0 ? "text-neon-green" : "text-neon-red";
                        return (
                          <tr key={`${t.id}-${t.symbol}`}>
                            <td className="font-mono text-xs text-bunker-muted">{fmtTime(t.time)}</td>
                            <td><span className="font-mono font-bold text-white">{t.symbol}</span></td>
                            <td className={"font-mono text-xs font-bold " + (t.isBuyer ? "text-neon-green" : "text-neon-red")}>
                              {t.isBuyer ? "ALIS" : "SATIS"}
                            </td>
                            <td className="font-mono text-xs text-bunker-muted">
                              {pnl != null && t.basis_price != null ? fmtPrice(t.basis_price, t.basis_price < 1 ? 6 : 2) : "—"}
                            </td>
                            <td className="font-mono text-xs">{fmtPrice(t.price, Number(t.price) < 1 ? 6 : 2)}</td>
                            <td className="font-mono text-xs">{fmtPrice(t.qty, 6)}</td>
                            <td className="font-mono text-xs">{fmtPrice(t.quoteQty, Number(t.quoteQty) < 1 ? 6 : 2)}</td>
                            <td className={`font-mono text-xs font-bold ${pnlCls}`}>
                              {pnl == null ? "—" : `${pnl >= 0 ? "+" : "−"}₺${fmtPrice(Math.abs(pnl))}`}
                            </td>
                            <td className="font-mono text-xs text-bunker-muted">{fmtPrice(t.commission, 6)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {/* Sayfalama: 25/sayfa (Erkan kararı, 18.09) */}
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-bunker-muted">
                    Sayfa {trPageSafe} / {trTotalPages} · {trades.length} işlem · sayfada {trPageRows.length} adet
                  </span>
                  <div className="flex items-center gap-1">
                    <button type="button" onClick={() => setTrPage(1)} disabled={trPageSafe <= 1}
                      className="rounded border border-bunker-600 px-2 py-1 font-mono text-[10px] text-bunker-muted transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-40">« Ilk</button>
                    <button type="button" onClick={() => setTrPage(trPageSafe - 1)} disabled={trPageSafe <= 1}
                      className="rounded border border-bunker-600 px-2 py-1 font-mono text-[10px] text-bunker-muted transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-40">‹ Onceki</button>
                    <button type="button" onClick={() => setTrPage(trPageSafe + 1)} disabled={trPageSafe >= trTotalPages}
                      className="rounded border border-bunker-600 px-2 py-1 font-mono text-[10px] text-bunker-muted transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Sonraki ›</button>
                    <button type="button" onClick={() => setTrPage(trTotalPages)} disabled={trPageSafe >= trTotalPages}
                      className="rounded border border-bunker-600 px-2 py-1 font-mono text-[10px] text-bunker-muted transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Son »</button>
                  </div>
                </div>
              </>
            )}
          </section>
        </>
      )}
    </main>
  );
}
