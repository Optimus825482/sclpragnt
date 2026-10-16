"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveMessages } from "../../lib/liveSocket";
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

export default function UserBinance() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
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

  const loadAccount = useCallback(async () => {
    const [pos, ord] = await Promise.all([
      call<Positions>("GET", "/api/binance/positions"),
      call<{ orders?: OpenOrder[] }>("GET", "/api/binance/open-orders"),
    ]);
    if (pos.ok) {
      setHoldings(pos.body.holdings || []);
      setTotal(pos.body.total_value_try ?? null);
      setAccountError("");
    } else {
      setAccountError(pos.error);
    }
    if (ord.ok) {
      setOrders(ord.body.orders || []);
      setOrdersError(false);
    } else {
      setOrdersError(true);
    }
    setOrdersLoading(false);
  }, []);

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
  useVisibleInterval(() => { if (configured) { loadAccount(); loadToday(); } }, configured ? 20000 : null, { runOnVisible: true });

  // Binance hesap/dolum olayı (WS): 1 sn debounce ile hesabı ve günlük sonucu tazele.
  const wsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (wsTimer.current) clearTimeout(wsTimer.current); }, []);
  const onLive = useCallback(() => {
    if (!configured || (typeof document !== "undefined" && document.hidden)) return;
    if (wsTimer.current) clearTimeout(wsTimer.current);
    wsTimer.current = setTimeout(() => { wsTimer.current = null; loadAccount(); loadToday(); }, 1000);
  }, [configured, loadAccount, loadToday]);
  useLiveMessages(onLive, ["binance_account_update"]);

  const afterTrade = useCallback(() => {
    loadAccount();
    loadToday();
    setRefreshKey((k) => k + 1);
  }, [loadAccount, loadToday]);

  const tryRow = holdings.find((h) => h.asset === "TRY");
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
            <p className="mt-1 text-2xl font-bold text-white">{fmtTry(total)}</p>
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
      {accountError && <p role="alert" className="text-sm text-neon-red">Hesap bilgisi alınamadı: {accountError}</p>}

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
              <HoldingsCard holdings={holdings} liveEnabled={settings.sell_enabled} onTraded={afterTrade} showToast={showToast} />
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
