"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLiveMessages } from "../../lib/liveSocket";
import { grossOpenPnlTry } from "../../lib/pnl";
import { call, type Holding, type OpenOrder, type RiskSettings } from "../../lib/tradeApi";
import { fmtSignedTry, fmtTry } from "../../lib/tradeUi";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import BuyCard from "./binance/BuyCard";
import ConnectionCard from "./binance/ConnectionCard";
import HistoryCard from "./binance/HistoryCard";
import HoldingsCard from "./binance/HoldingsCard";
import OpenOrdersCard from "./binance/OpenOrdersCard";

type Settings = { configured: boolean; sell_enabled: boolean; sell_source: string };
type Positions = { holdings?: Holding[]; total_value_try?: number };
type Daily = { daily?: { realized_pnl_try?: number } | null };

// 2026-10-17 (basit arayüz): "güncellendi X sn önce" damgası. Kendi 1 sn sayacı vardır; üst bileşen her saniye yeniden çizilmez.
const STALE_AFTER_SEC = 30;
function Freshness({ at, onRefresh }: { at: number | null; onRefresh: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (at == null) return null;
  const sec = Math.max(0, Math.round((now - at) / 1000));
  const stale = sec > STALE_AFTER_SEC;
  return (
    <p role="status" className={`flex flex-wrap items-center gap-2 text-xs ${stale ? "text-yellow-300" : "text-bunker-muted"}`}>
      <span>{stale ? `Veri ${sec} sn önce alındı — yenilenemiyor olabilir, eski değerler gösteriliyor.` : sec < 3 ? "Az önce güncellendi" : `Güncellendi ${sec} sn önce`}</span>
      {stale && (
        <button type="button" onClick={onRefresh} className="ui-button-secondary min-h-[32px] rounded-lg border px-3 text-xs font-medium">
          Şimdi yenile
        </button>
      )}
    </p>
  );
}

export default function UserBinance() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  // 2026-10-17 (basit arayüz): varlıklar ilk yanıt gelene kadar "yükleniyor" (boş liste mesajı yanıltmasın).
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [lastOkAt, setLastOkAt] = useState<number | null>(null);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [todayPnl, setTodayPnl] = useState<number | null>(null);
  const [accountError, setAccountError] = useState("");
  // 2026-10-16 (basit arayüz): açık emir / günlük K/Z yenilemesi başarısızsa sessizce eski veri gösterilmez.
  const [ordersError, setOrdersError] = useState(false);
  const [todayError, setTodayError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toast, setToast] = useState<{ text: string; type: "success" | "error" | "info" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showToast = useCallback((text: string, type: "success" | "error" | "info" = "info") => {
    setToast({ text, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  const loadSettings = useCallback(async () => {
    const r = await call<Settings>("GET", "/api/binance/settings");
    if (r.ok) setSettings(r.body);
    else setSettings({ configured: false, sell_enabled: false, sell_source: "panel" });
  }, []);

  const loadRisk = useCallback(async () => {
    const r = await call<RiskSettings>("GET", "/api/binance/risk");
    if (r.ok) setRisk({ max_position_pct: r.body.max_position_pct, default_rr: r.body.default_rr });
  }, []);

  // 2026-10-17 (basit arayüz): pozisyonlar ve bekleyen emirler AYRI yüklenir; varlık listesi
  // açık emir yanıtını (ve günlük K/Z'yi) beklemez. Sıra dışı gelen eski yanıt yenisini ezmez.
  const posSeq = useRef(0);
  const posApplied = useRef(0);
  const ordSeq = useRef(0);
  const ordApplied = useRef(0);
  const loadPositions = useCallback(async () => {
    const seq = ++posSeq.current;
    const pos = await call<Positions>("GET", "/api/binance/positions");
    if (seq < posApplied.current) return;
    posApplied.current = seq;
    if (pos.ok) {
      setHoldings(pos.body.holdings || []);
      setTotal(pos.body.total_value_try ?? null);
      setLivePrices({}); // sunucu fiyatı taze; sonraki WS tick'i üzerine yazar
      setLastOkAt(Date.now());
      setAccountError("");
    } else {
      setAccountError(pos.error);
    }
    setPositionsLoading(false);
  }, []);

  const loadOrders = useCallback(async () => {
    const seq = ++ordSeq.current;
    const ord = await call<{ orders?: OpenOrder[] }>("GET", "/api/binance/open-orders");
    if (seq < ordApplied.current) return;
    ordApplied.current = seq;
    if (ord.ok) {
      setOrders(ord.body.orders || []);
      setOrdersError(false);
    } else {
      setOrdersError(true);
    }
    setOrdersLoading(false);
  }, []);

  const loadAccount = useCallback(() => {
    void loadPositions();
    void loadOrders();
  }, [loadPositions, loadOrders]);

  const loadToday = useCallback(async () => {
    const d = new Date();
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const r = await call<Daily>("GET", `/api/binance/trades-day?date=${date}`);
    if (r.ok) {
      setTodayPnl(r.body.daily?.realized_pnl_try ?? null);
      setTodayError(false);
    } else {
      setTodayError(true);
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadRisk();
  }, [loadSettings, loadRisk]);

  const configured = !!settings?.configured;
  useEffect(() => {
    if (!configured) return;
    setOrdersLoading(true);
    loadAccount();
    loadToday();
    // Dolum akışı sayfa açılınca başlar (Pozisyonlar sayfasına bağımlı değil).
    call("POST", "/api/binance/user-stream/start");
  }, [configured, loadAccount, loadToday]);

  // Sekme öne gelince hemen tazele (arka planda beklerken emirler/bakiye eskimiş olabilir).
  // 2026-10-17 (basit arayüz): 20 sn → 10 sn (sunucuda 3 sn yanıt + 300 sn maliyet cache'i var, ek yük yok);
  // günlük K/Z daha ağır olduğundan ayrı ve daha seyrek (30 sn) yenilenir.
  useVisibleInterval(() => { if (configured) loadAccount(); }, configured ? 10000 : null, { runOnVisible: true });
  useVisibleInterval(() => { if (configured) loadToday(); }, configured ? 30000 : null, { runOnVisible: false });

  // Binance hesap/dolum olayı (WS): 1 sn debounce ile hesabı ve günlük sonucu tazele.
  const wsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (wsTimer.current) clearTimeout(wsTimer.current); }, []);
  const onLive = useCallback(() => {
    if (!configured || (typeof document !== "undefined" && document.hidden)) return;
    if (wsTimer.current) clearTimeout(wsTimer.current);
    wsTimer.current = setTimeout(() => { wsTimer.current = null; loadAccount(); loadToday(); }, 1000);
  }, [configured, loadAccount, loadToday]);
  useLiveMessages(onLive, ["binance_account_update"]);

  // 2026-10-17 (basit arayüz): canlı fiyat — backend `binance_price` (2 sn'de bir, TRY'ye çevrilmiş
  // {VARLIK: {price}} haritası) ile elde tutulan varlıkların fiyat/değer/K-Z'si iki yoklama arasında da kayar.
  // (`tickers` tipi istemcide bilinçli olarak elenir — liveSocket.UNCONSUMED_LIVE_TYPES.)
  const heldRef = useRef<string[]>([]);
  useEffect(() => { heldRef.current = holdings.filter((h) => h.asset !== "TRY" && h.total > 0).map((h) => h.asset); }, [holdings]);
  const onTick = useCallback((m: { type: string; data?: unknown }) => {
    if (m?.type !== "binance_price" || (typeof document !== "undefined" && document.hidden)) return;
    const ticks = (m.data as { ticks?: Record<string, { price?: number }> } | null)?.ticks;
    if (!ticks) return;
    setLivePrices((cur) => {
      let next: Record<string, number> | null = null;
      for (const asset of heldRef.current) {
        const p = Number(ticks[asset]?.price);
        if (Number.isFinite(p) && p > 0 && cur[asset] !== p) { next = next ?? { ...cur }; next[asset] = p; }
      }
      return next ?? cur;
    });
  }, []);
  useLiveMessages(onTick, ["binance_price"]);

  // Yerel mark-to-market: sunucu satırı + son tick. K/Z brüt (sunucuyla aynı), net hesap HoldingsCard'da.
  const liveHoldings = useMemo(() => {
    const rows = holdings.map((h) => {
      const p = livePrices[h.asset];
      if (h.asset === "TRY" || !p) return h;
      const avg = Number(h.avg_cost_try);
      return {
        ...h,
        price_try: p,
        value_try: Math.round(h.total * p * 100) / 100,
        pnl_try: grossOpenPnlTry(h.avg_cost_try, p, h.total),
        pnl_pct: avg > 0 ? ((p - avg) / avg) * 100 : null,
      };
    });
    return rows.sort((a, b) => (a.value_try == null ? 1 : 0) - (b.value_try == null ? 1 : 0) || (b.value_try ?? 0) - (a.value_try ?? 0));
  }, [holdings, livePrices]);
  const liveTotal = useMemo(
    () => (Object.keys(livePrices).length ? liveHoldings.reduce((sum, h) => sum + (h.value_try ?? 0), 0) : total),
    [liveHoldings, livePrices, total],
  );

  const afterTrade = useCallback(() => {
    loadAccount();
    loadToday();
    setRefreshKey((k) => k + 1);
  }, [loadAccount, loadToday]);

  const tryRow = liveHoldings.find((h) => h.asset === "TRY");
  const freeTry = tryRow ? tryRow.free : null;

  return (
    <main className="space-y-4">
      {toast && (
        <div
          role={toast.type === "error" ? "alert" : "status"}
          className={`fixed left-1/2 top-3 z-[200] w-[min(92vw,28rem)] -translate-x-1/2 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg ${toast.type === "error" ? "bg-neon-red" : toast.type === "success" ? "bg-neon-green" : "bg-bunker-800"}`}
        >
          {toast.text}
        </div>
      )}
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-white">Binance TR</h1>
          <p className="text-sm text-bunker-muted">Bakiyeni gör, coin al-sat, bekleyen emirlerini yönet.</p>
        </div>
        <Link href="/risk" className="ui-button-secondary inline-flex min-h-[44px] items-center rounded-lg border px-4 text-sm font-medium">
          Risk Merkezi{risk ? ` · en fazla %${risk.max_position_pct}` : ""}
        </Link>
      </header>

      {settings === null && <p className="text-sm text-bunker-muted" aria-live="polite">Yükleniyor…</p>}

      {settings && configured && (
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Hesap özeti">
          <div className="card p-4">
            <p className="text-sm font-medium text-bunker-muted">Toplam değer</p>
            <p className="mt-1 text-2xl font-bold text-white">{fmtTry(liveTotal)}</p>
          </div>
          <div className="card p-4">
            <p className="text-sm font-medium text-bunker-muted">Kullanılabilir TL</p>
            <p className="mt-1 text-2xl font-bold text-white">{fmtTry(freeTry)}</p>
          </div>
          <div className={`card p-4 ${todayPnl == null ? "" : todayPnl >= 0 ? "u-card-good" : "u-card-bad"}`}>
            <p className="text-sm font-medium text-bunker-muted">Bugünkü sonuç</p>
            <p className="mt-1 text-2xl font-bold text-white">{todayPnl == null ? "—" : fmtSignedTry(todayPnl)}</p>
            {todayError && <p role="status" className="mt-1 text-xs text-yellow-300">yenilenemedi — gösterilen değer eski olabilir</p>}
          </div>
        </section>
      )}
      {settings && configured && <Freshness at={lastOkAt} onRefresh={loadAccount} />}
      {accountError && <p role="alert" className="text-sm text-neon-red">Hesap bilgisi alınamadı: {accountError}{lastOkAt ? " — son başarılı veri gösteriliyor." : ""}</p>}

      {settings && (
        <>
          <BuyCard
            liveEnabled={settings.sell_enabled}
            configured={configured}
            maxPositionPct={risk?.max_position_pct ?? 20}
            onTraded={afterTrade}
          />
          {configured && (
            <>
              <HoldingsCard holdings={liveHoldings} loading={positionsLoading} liveEnabled={settings.sell_enabled} onTraded={afterTrade} showToast={showToast} />
              {ordersError && <p role="status" className="text-sm text-yellow-300">Bekleyen emirler yenilenemedi — liste eski olabilir (koruma emirlerini Binance TR’den doğrula).</p>}
              <OpenOrdersCard orders={orders} loading={ordersLoading} onChanged={loadAccount} />
              <HistoryCard enabled={configured} refreshKey={refreshKey} />
            </>
          )}
          <ConnectionCard
            configured={configured}
            sellEnabled={settings.sell_enabled}
            sellSource={settings.sell_source}
            onChanged={() => { loadSettings(); }}
          />
        </>
      )}
    </main>
  );
}
