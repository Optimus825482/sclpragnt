"use client";

/**
 * Portföy İzleme — otonom paper trade + ana paper portföyün tek ekranda,
 * sade ve net takibi. Canlı WS (portfolio + auto_paper_trade olayları) ile
 * beslenir; REST yedekleme 10 sn'de bir tazelenir.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import SymbolLink from "../components/SymbolLink";
import { Button } from "../components/ui";
import { toMs } from "../lib/format";
import { closedPnlTry, netOpenPnlPct, netOpenPnlTry } from "../lib/pnl";
import { formatPrice } from "../charts/chartShared";

/* ------------------------------------------------------------------ */
/* Tipler                                                              */
/* ------------------------------------------------------------------ */
type MainPosition = {
  symbol: string;
  side?: string;
  entry: number;
  current: number;
  pnl_pct: number;
  pnl_try?: number;
  value?: number;
  quantity?: number;
  entry_time?: number;
  strategy?: string;
};

type Portfolio = {
  try?: number;
  total_value?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  positions: MainPosition[];
};

type AutoPaperTrade = {
  id: number;
  symbol: string;
  side?: string;
  status: "open" | "closed";
  entry_price: number;
  quantity: number;
  order_value_try?: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  peak_price?: number;
  entry_time?: number;
  exit_price?: number | null;
  exit_time?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  commission?: number | null;
  exit_reason?: string | null;
  breakeven_activated?: boolean;
  notification_score?: number | null;
  notification_target_pct?: number | null;
  current_price?: number | null;
};

type AutoPaperStats = {
  total: number;
  open: number;
  closed: number;
  winning: number;
  losing: number;
  win_rate: number;
  total_pnl_try: number;
  total_invested_try: number;
  avg_pnl_try: number;
};

/* ------------------------------------------------------------------ */
/* Yardımcılar                                                         */
/* ------------------------------------------------------------------ */
const money = (v?: number | null) => {
  // H-02: `null` → "—" (0 DEĞİL). 0 meşru bir değerdir ama "veri yok" değildir.
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const formatted = abs.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `₺${formatted}`;
};

const signedMoney = (v?: number | null) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const formatted = abs.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return v < 0 ? `-₺${formatted}` : `₺${formatted}`;
};

const pctText = (v?: number | null) => {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
};

const tone = (v?: number | null) =>
  v == null || !Number.isFinite(v) ? "text-bunker-muted" : v >= 0 ? "text-neon-green" : "text-neon-red";

const fmtDay = (ts?: number | null) => {
  if (!ts) return "—";
  return new Date(toMs(ts)).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

const STRATEGY_LABEL: Record<string, string> = {
  VELOCITY: "Hız Avcısı",
  CHAT_PREDICTION: "Hız Avcısı (Otonom)",
  LLM_PAPER: "LLM Paper",
  GAINER_RADAR: "Gainer Radar",
};

const REASON_LABEL: Record<string, string> = {
  take_profit: "Hedefe ulaştı",
  stop_loss: "Stop",
  breakeven_stop: "Başabaş koruması",
  reset: "Portföy sıfırlama",
};

function MetricCard({ label, value, toneClass = "", hint }: { label: string; value: React.ReactNode; toneClass?: string; hint?: string }) {
  return (
    <div className="ui-card ui-stat-card">
      <p className="eyebrow">{label}</p>
      <p className={`ui-stat-value ${toneClass}`}>{value}</p>
      {hint && <p className="ui-stat-detail">{hint}</p>}
    </div>
  );
}

function StatusBadge({ children, tone: t }: { children: React.ReactNode; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const map: Record<string, string> = {
    ok: "border-neon-green/50 bg-neon-green/10 text-neon-green",
    warn: "border-yellow-300/40 bg-yellow-300/10 text-yellow-300",
    bad: "border-neon-red/40 bg-neon-red/10 text-neon-red",
    neutral: "border-bunker-600 bg-bunker-800/50 text-bunker-muted",
  };
  return <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] whitespace-nowrap ${map[t]}`}>{children}</span>;
}

/* ------------------------------------------------------------------ */
/* Sayfa                                                               */
/* ------------------------------------------------------------------ */
export default function PortfolioPage() {
  const liveStatus = useLiveStatus();

  // Canlı WS portföyü (ana sistem — analyzer pozisyonları + TL)
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  // REST tabanlı ana pozisyonlar (WS kopukken de görünsün)
  const [mainPositions, setMainPositions] = useState<MainPosition[]>([]);
  // Otonom paper: açık pozisyonlar + istatistikler + son kapananlar
  const [apTrades, setApTrades] = useState<AutoPaperTrade[]>([]);
  const [apStats, setApStats] = useState<AutoPaperStats | null>(null);
  const [apRecent, setApRecent] = useState<AutoPaperTrade[]>([]);
  const [apSettings, setApSettings] = useState<any>(null);
  const [lastEvent, setLastEvent] = useState<{ text: string; at: number } | null>(null);
  // Kapanan otonom işlemler: pagination'lı tam geçmiş (sayfa altı tablo)
  const [apHistory, setApHistory] = useState<AutoPaperTrade[]>([]);
  const [apHistoryPage, setApHistoryPage] = useState(0);
  const apHistoryPageRef = useRef(apHistoryPage);
  apHistoryPageRef.current = apHistoryPage;
  const AP_HISTORY_PAGE_SIZE = 20;
  // Otonom karar akışı (decision_logs, strategy=AUTO_PAPER)
  const [decisions, setDecisions] = useState<any[]>([]);
  const [decisionsExpanded, setDecisionsExpanded] = useState(false);

  const loadMain = useCallback(() => {
    apiRequest(`${API_BASE}/api/positions`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setMainPositions(d.positions || []))
      .catch(() => undefined);
  }, []);

  // Sık değişen: yalnız açık pozisyonlar (WS auto_paper_trade sonrası anında
  // tazelenir — tek REST, 4 istek yerine).
  const loadAutoPaperOpen = useCallback(() => {
    apiRequest(`${API_BASE}/api/auto-paper/trades?status=open&limit=50`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setApTrades(d.trades || []))
      .catch(() => undefined);
  }, []);

  // Yavaş değişen: istatistik + son kapananlar + ayarlar (yalnız periyodik poll)
  const loadAutoPaperDetail = useCallback(() => {
    apiRequest(`${API_BASE}/api/auto-paper/trades?status=closed&limit=8`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setApRecent(d.trades || []))
      .catch(() => undefined);
    apiRequest(`${API_BASE}/api/auto-paper/stats`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setApStats(d.stats || null))
      .catch(() => undefined);
    apiRequest(`${API_BASE}/api/auto-paper/settings`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setApSettings(d))
      .catch(() => undefined);
  }, []);

  // Kapanan otonom işlemler geçmişi — pagination'lı (sayfa başına 20)
  const loadAutoPaperHistory = useCallback((page: number) => {
    const offset = page * AP_HISTORY_PAGE_SIZE;
    apiRequest(`${API_BASE}/api/auto-paper/trades?status=closed&limit=${AP_HISTORY_PAGE_SIZE}&offset=${offset}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setApHistory(d.trades || []))
      .catch(() => undefined);
  }, []);

  // Otonom karar akışı — decision_logs, strategy=AUTO_PAPER, en yeni `limit`
  const loadDecisions = useCallback((limit = 50) => {
    apiRequest(`${API_BASE}/api/decisions?strategy=AUTO_PAPER&limit=${limit}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setDecisions(d.decisions || []))
      .catch(() => undefined);
  }, []);

  // WS kopukken portföy başlığı boş kalmasın: /api/portfolio/summary REST
  // yedeği (WS 'portfolio' mesajı geldiğinde canlı veri üzerine yazar).
  const loadPortfolioFallback = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/portfolio/summary`, { cache: "no-store" });
      if (!r.ok) return;
      const d = await r.json();
      const snap = d.portfolio || {};
      setPortfolio({
        // H-02: eksik alan `0`'a çevrilmez (0 = "başabaş" izlenimi). `undefined`
        // bırakılır; UI bunu nötr "—" olarak gösterir.
        try: snap.try != null ? Number(snap.try) : undefined,
        total_value: snap.total_value != null ? Number(snap.total_value) : undefined,
        realized_pnl: snap.realized_pnl != null ? Number(snap.realized_pnl) : undefined,
        unrealized_pnl: snap.unrealized_pnl != null ? Number(snap.unrealized_pnl) : undefined,
        positions: Array.isArray(snap.positions) ? snap.positions : [],
      });
    } catch { /* */ }
  }, []);

  useEffect(() => {
    // Sekme arka plandayken poll'ları atla (görünmeyen sekmede REST israfı).
    const hidden = () => document.hidden;
    const openPoll = () => {
      if (!hidden()) {
        loadMain();
        // Açık otonom pozisyonlar da REST'ten tazelenmeli: yalnız WS
        // auto_paper_trade olayına kalırlarsa sayfa yüklendikten sonra açılan
        // olaylar kaçırılınca liste sonsuza kadar boş kalıyordu.
        loadAutoPaperOpen();
      }
    };
    const detailPoll = () => { if (!hidden()) loadAutoPaperDetail(); };
    openPoll();
    loadAutoPaperDetail();
    loadAutoPaperHistory(apHistoryPage);
    loadDecisions();
    // Açık pozisyonlar 5 sn'de bir (WS kopukken canlı kalsın), detay 15 sn'de bir.
    const openTimer = window.setInterval(openPoll, 5_000);
    const detailTimer = window.setInterval(detailPoll, 15_000);
    const decisionTimer = window.setInterval(() => { if (!hidden()) loadDecisions(); }, 30_000);
    return () => { window.clearInterval(openTimer); window.clearInterval(detailTimer); window.clearInterval(decisionTimer); };
  }, [loadMain, loadAutoPaperOpen, loadAutoPaperDetail, loadAutoPaperHistory, loadDecisions, apHistoryPage]);

  // WS bağlantısı yoksa portföy özetini REST'ten tazele (15 sn).
  useEffect(() => {
    if (liveStatus === "open") return;
    if (!document.hidden) loadPortfolioFallback();
    const t = window.setInterval(() => { if (!document.hidden) loadPortfolioFallback(); }, 15_000);
    return () => window.clearInterval(t);
  }, [liveStatus, loadPortfolioFallback]);

  // auto_paper_trade WS olayı seri gelebilir (açılış+kapanış) — her olayda
  // 3 REST atmamak için 800 ms debounce ile açık pozisyon listesini tazele.
  const debouncedRefresh = useMemo(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    return () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => { loadAutoPaperOpen(); loadMain(); loadAutoPaperHistory(apHistoryPageRef.current); loadDecisions(); }, 800);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadAutoPaperOpen, loadMain, loadAutoPaperHistory, loadDecisions]);

  const onReset = useCallback(() => {
    loadMain();
    loadAutoPaperOpen();
    loadAutoPaperDetail();
    loadAutoPaperHistory(apHistoryPageRef.current);
    loadDecisions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadMain, loadAutoPaperOpen, loadAutoPaperDetail, loadAutoPaperHistory, loadDecisions]);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "portfolio") setPortfolio(message.data);
    if (message.type === "auto_paper_trade") {
      const d = message.data || {};
      const action = d.action === "OPENED" ? "açıldı" : d.action === "CLOSED" ? "kapatıldı" : "güncellendi";
      setLastEvent({ text: `${d.symbol} ${action}`, at: Date.now() });
      // Açık pozisyonlar + ana pozisyonlar kısa debounce ile tazelenir
      // (seri WS olayında 3+ REST atmamak için); istatistikler 15 sn poll'a kalır.
      debouncedRefresh();
    }
    if (message.type === "reset") {
      // Portföy sıfırlaması: tüm bölümleri anında tazele (15-30 sn poll'a kalma).
      onReset();
    } else if (["signal", "trade_updated"].includes(message.type)) {
      loadMain();
    }
  }, [debouncedRefresh, loadMain, onReset]);
  useLiveMessages(onLiveMessage);

  // Ana pozisyonları birleştir: WS anlık değeri REST'ten önceliklidir.
  // AUTO_PAPER satırları hariçtir — otonom pozisyonlar yukarıdaki kendi
  // bölümünde gösterilir ve metriklerde ayrı toplanır (çift sayım olmasın).
  const isAutoPaper = (p: MainPosition) => String(p.strategy || "").toUpperCase() === "AUTO_PAPER";
  const displayMain = useMemo(() => {
    const bySymbol = new Map<string, MainPosition>();
    for (const p of mainPositions) {
      if (isAutoPaper(p)) continue;
      bySymbol.set(p.symbol, p);
    }
    for (const p of portfolio?.positions || []) {
      if (isAutoPaper(p)) continue;
      const existing = bySymbol.get(p.symbol);
      if (!existing || Number(p.entry_time || 0) >= Number(existing.entry_time || 0)) bySymbol.set(p.symbol, p);
    }
    return [...bySymbol.values()].sort((a, b) => Number(b.entry_time || 0) - Number(a.entry_time || 0));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainPositions, portfolio]);

  // Açık auto-paper PnL (H-01): brüt DEĞİL, kanonik net formül (lib/pnl.ts).
  // Girdi eksikse (current_price gelmedi) ilgili satır `null` döner ve toplama
  // girmez — 0 sayılırsa "başabaş" gibi görünürdü (H-02). Hiçbir satır
  // ölçülemiyorsa toplam da `null` (pozisyon yoksa meşru olarak 0).
  const apOpenPnl = useMemo<number | null>(() => {
    if (apTrades.length === 0) return 0;
    const values = apTrades
      .map((t) => netOpenPnlTry(t.entry_price, t.current_price, t.quantity))
      .filter((v): v is number => v != null);
    return values.length === 0 ? null : values.reduce((a, v) => a + v, 0);
  }, [apTrades]);

  // ANA hesap açık pozisyon K/Z'si de GÖRÜNTÜDE aynı kanonik esastan (net,
  // gidiş-dönüş komisyonlu) hesaplanır. Backend `pnl_try` yalnız giriş bacağını
  // düşer (muhasebe/reconciliation doğru kalması için) → aynı tabloda iki
  // farklı esas görünmesin diye görüntü tek kaynaktan üretilir.
  const openMainPnl = useMemo<number | null>(() => {
    const values = displayMain
      .map((p) => netOpenPnlTry(p.entry, p.current, p.quantity))
      .filter((v): v is number => v != null);
    return values.length === 0 ? null : values.reduce((a, v) => a + v, 0);
  }, [displayMain]);
  const totalOpen = displayMain.length + apTrades.length;
  // Pozisyon yoksa PnL meşru olarak 0'dır; pozisyon VAR ama veri yoksa `null`.
  const totalOpenPnl = totalOpen === 0
    ? 0
    : (openMainPnl == null && apOpenPnl == null ? null : (openMainPnl ?? 0) + (apOpenPnl ?? 0));

  // Toplam değer: WS/summary total_value (ana + otonom açık pozisyon değerleri
  // dahil — backend toplamı zaten otonom pozisyonları katıyor), ayrıca
  // apOpenValue eklenmez (çift sayım olmasın). WS kopukken summary fallback'i
  // aynı alanı REST'ten besler.
  //
  // H-02: portföy henüz yüklenmediyse `0` DEĞİL `null` döner — aksi halde
  // "₺0,00" yeşil görünüp "başabaş" izlenimi verirdi.
  const totalValue = portfolio?.total_value ?? null;
  const freeTry = portfolio?.try ?? null;
  // Gerçekleşen K/Z (ana + otonom): iki kaynak da gelmeden toplam `null`.
  const realizedTotal: number | null = portfolio == null
    ? null
    : (portfolio.realized_pnl == null && apStats?.total_pnl_try == null
        ? null
        : (portfolio.realized_pnl ?? 0) + (apStats?.total_pnl_try ?? 0));

  const apEnabled = apSettings?.settings?.enabled;

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">CANLI PORTFÖY TAKİBİ</p>
          <h1 className="font-mono text-2xl font-bold text-white">Portföy İzleme</h1>
          <p className="mt-1 text-sm text-bunker-muted">
            Otonom paper trade ve ana hesabınızın anlık durumu — bakiye, kar/zarar ve başarı tek ekranda.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded border px-2 py-1 font-mono text-[10px] ${liveStatus === "open" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-yellow-300/40 bg-yellow-300/10 text-yellow-300"}`}>
            {liveStatus === "open" ? "● CANLI" : "○ BAĞLANTI KESİK"}
          </span>
          <Button variant="secondary" onClick={onReset}>🔄 Yenile</Button>
        </div>
      </div>

      {lastEvent && (
        <div className="mb-4 rounded-lg border border-neon-green/30 bg-neon-green/5 px-3 py-2 font-mono text-xs text-neon-green">
          ⚡ Otonom işlem: {lastEvent.text} · {new Date(lastEvent.at).toLocaleTimeString("tr-TR")}
        </div>
      )}

      {/* ---- ÜST: Sermaye özeti ---- */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="TOPLAM DEĞER" value={money(totalValue)} hint={`mevcut TL ${money(freeTry)} + açık pozisyonlar`} />
        <MetricCard label="SERBEST TL" value={money(freeTry)} toneClass={freeTry == null ? "" : "ui-tone-positive"} />
        <MetricCard label="AÇIK POZİSYON" value={String(totalOpen)} toneClass={totalOpen > 0 ? "ui-tone-warning" : ""} hint={`otonom ${apTrades.length} · ana ${displayMain.length}`} />
        <MetricCard label="AÇIK KAR/ZARAR" value={signedMoney(totalOpenPnl)} toneClass={tone(totalOpenPnl)} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="GERÇEKLEŞEN K/Z (tümü)" value={signedMoney(realizedTotal)} toneClass={tone(realizedTotal)} hint="ana + otonom kapanan işlemler" />
        <MetricCard label="OTONOM BAŞARI" value={apStats?.closed ? `%${apStats.win_rate?.toFixed(1)}` : "—"} toneClass={apStats && apStats.win_rate >= 50 ? "ui-tone-positive" : apStats ? "ui-tone-negative" : ""} hint={`${apStats?.winning ?? 0} kazanç · ${apStats?.losing ?? 0} kayıp`} />
        <MetricCard label="OTONOM KAPANAN" value={String(apStats?.closed ?? 0)} hint={`toplam ${apStats?.total ?? 0} işlem`} />
        <MetricCard label="OTONOM NET PnL" value={signedMoney(apStats?.total_pnl_try)} toneClass={tone(apStats?.total_pnl_try)} />
      </div>

      {/* ---- Otonom Paper bölümü ---- */}
      <section className="card mt-5">
        <div className="ui-section-header">
          <div>
            <p className="eyebrow text-neon-green">🤖 OTONOM PAPER TRADE</p>
            <h2 className="font-mono text-lg font-bold text-white">Otomatik İşlemler</h2>
            <p className="ui-section-description">
              Radar bildirimleriyle otomatik açılan pozisyonlar; hedef, stop ve başabaş koruması sistem tarafından yönetilir.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge tone={apEnabled === false ? "bad" : "ok"}>{apEnabled === false ? "DURDURULDU" : "AKTİF"}</StatusBadge>
            <span className="font-mono text-[10px] text-bunker-muted">monitoring bildirimleriyle tetiklenir</span>
          </div>
        </div>

        {/* Açık pozisyonlar */}
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="eyebrow">AÇIK POZİSYONLAR ({apTrades.length})</p>
          </div>
          {apTrades.length === 0 ? (
            <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-8 text-center">
              <p className="text-2xl">📭</p>
              <p className="mt-1 text-sm text-bunker-muted">
                {apEnabled === false ? "Otonom trade şu an kapalı — Ayarlar sayfasından açabilirsiniz." : "Şu an açık otonom pozisyon yok. Radar yeni fırsat bulduğunda burada görünecek."}
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Sembol</th>
                    <th>Giriş</th>
                    <th>Güncel</th>
                    <th>Hedef (TP)</th>
                    <th>Stop (SL)</th>
                    <th>K/Z</th>
                    <th>%</th>
                    <th>Süre</th>
                  </tr>
                </thead>
                <tbody>
                  {apTrades.map((t) => {
                    const entry = Number(t.entry_price || 0);
                    // H-02: ticker gelmediyse güncel fiyat `null`'dur; entry'ye
                    // düşürmek sahte "başabaş" (yeşil +0,00%) üretirdi.
                    const current = Number(t.current_price) > 0 ? Number(t.current_price) : null;
                    // H-01: net (gidiş-dönüş komisyonu düşülmüş) — backend ile aynı.
                    const pnl = netOpenPnlTry(t.entry_price, t.current_price, t.quantity);
                    const pnlPct = netOpenPnlPct(t.entry_price, t.current_price, t.quantity);
                    const held = t.entry_time ? Math.floor((Date.now() / 1000 - Number(t.entry_time)) / 60) : null;
                    const tpDist = entry > 0 && current != null && t.take_profit
                      ? (((Number(t.take_profit) - current) / entry) * 100) : null;
                    return (
                      <tr key={t.id}>
                        <td><SymbolLink symbol={t.symbol} className="font-bold text-white hover:text-neon-green" /></td>
                        <td className="font-mono text-xs">{formatPrice(entry)}</td>
                        <td className={`font-mono text-xs ${tpDist !== null && tpDist <= 0 ? "text-neon-green font-bold" : ""}`}>{current == null ? "—" : formatPrice(current)}</td>
                        <td className={`font-mono text-xs ${t.take_profit ? "text-neon-green" : "text-bunker-muted"}`}>{t.take_profit ? formatPrice(Number(t.take_profit)) : "—"}</td>
                        <td className={`font-mono text-xs ${t.stop_loss ? "text-neon-red" : "text-bunker-muted"}`}>{t.stop_loss ? formatPrice(Number(t.stop_loss)) : "—"}</td>
                        <td className={`font-mono text-xs ${tone(pnl)}`}>{signedMoney(pnl)}</td>
                        <td className={`font-mono text-xs ${tone(pnlPct)}`}>{pctText(pnlPct)}</td>
                        <td className="font-mono text-xs text-bunker-muted">{held != null ? `${held} dk` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Son kapananlar */}
        {apRecent.length > 0 && (
          <div className="mt-6">
            <p className="eyebrow mb-2">SON KAPANANLAR</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {apRecent.map((t) => {
                const pnl = closedPnlTry(t.pnl);
                const pnlPct = closedPnlTry(t.pnl_pct);
                return (
                  <div key={t.id} className="rounded-lg border border-bunker-800 bg-bunker-900/60 p-3">
                    <div className="flex items-center justify-between">
                      <SymbolLink symbol={t.symbol} className="font-bold text-white hover:text-neon-green" />
                      <span className="font-mono text-[10px] text-bunker-muted">{fmtDay(t.exit_time)}</span>
                    </div>
                    <div className={`mt-1 font-mono text-lg font-bold ${tone(pnl)}`}>{signedMoney(pnl)}</div>
                    <div className="mt-0.5 flex items-center justify-between">
                      <span className="font-mono text-[10px] text-bunker-muted">{REASON_LABEL[t.exit_reason || ""] || t.exit_reason || "—"}</span>
                      <span className={`font-mono text-[10px] ${tone(pnlPct)}`}>{pctText(pnlPct)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {/* ---- Ana pozisyonlar ---- */}
      <section className="card mt-5">
        <div className="ui-section-header">
          <div>
            <p className="eyebrow">💼 ANA HESAP POZİSYONLARI</p>
            <h2 className="font-mono text-lg font-bold text-white">Diğer Açık İşlemler</h2>
            <p className="ui-section-description">Manuel veya diğer stratejilerle açılmış paper pozisyonları.</p>
          </div>
          {displayMain.length > 0 && <span className="font-mono text-xs text-bunker-muted">{displayMain.length} pozisyon</span>}
        </div>
        {displayMain.length === 0 ? (
          <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
            Ana hesapta açık pozisyon yok.
          </div>
        ) : (
          <div className="table-scroll mt-3">
            <table className="data-table">
              <thead>
                <tr><th>Sembol</th><th>Strateji</th><th>Giriş</th><th>Güncel</th><th>K/Z</th><th>%</th></tr>
              </thead>
              <tbody>
                {displayMain.map((p) => {
                  // Görüntü tek kanonik esastan (net, gidiş-dönüş komisyonlu)
                  // üretilir — yukarıdaki `openMainPnl` toplamı ile aynı kaynak.
                  // Backend `p.pnl_try` yalnız giriş bacağını düşer; burada
                  // satırlar toplamla tutarlı olsun diye kanonik helper kullanılır.
                  const pnl = netOpenPnlTry(p.entry, p.current, p.quantity);
                  const pnlPct = netOpenPnlPct(p.entry, p.current, p.quantity);
                  return (
                    <tr key={p.symbol}>
                      <td><SymbolLink symbol={p.symbol} className="font-bold text-white hover:text-neon-green" /></td>
                      <td className="text-xs">{STRATEGY_LABEL[p.strategy || ""] || p.strategy || "—"}</td>
                      <td className="font-mono text-xs">{formatPrice(Number(p.entry || 0))}</td>
                      <td className="font-mono text-xs">{p.current == null ? "—" : formatPrice(p.current)}</td>
                      <td className={`font-mono text-xs ${tone(pnl)}`}>{signedMoney(pnl)}</td>
                      <td className={`font-mono text-xs ${tone(pnlPct)}`}>{pctText(pnlPct)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- Otonom Karar Akışı ---- */}
      <section className="card mt-5">
        <div className="ui-section-header">
          <div>
            <p className="eyebrow text-neon-green">🧭 OTONOM KARAR AKIŞI</p>
            <h2 className="font-mono text-lg font-bold text-white">Sistemin Karar Günlüğü</h2>
            <p className="ui-section-description">
              Otonom sistemin açık/kapat kararları — zaman, sembol, eylem, fiyat ve gerekçe.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              const next = !decisionsExpanded;
              setDecisionsExpanded(next);
              if (next) loadDecisions(200);
            }}
            className="rounded border border-bunker-700 px-2 py-1 font-mono text-[11px] text-bunker-muted hover:border-neon-green/40 hover:text-neon-green"
          >
            {decisionsExpanded ? "DARALT" : `TÜMÜ (${decisions.length})`}
          </button>
          <span className="font-mono text-xs text-bunker-muted">{decisions.length} kayıt</span>
        </div>
        {decisions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
            Henüz karar kaydı yok.
          </div>
        ) : (
          <div className="table-scroll mt-3">
            <table className="data-table">
              <thead>
                <tr><th>Zaman</th><th>Sembol</th><th>Eylem</th><th>Fiyat</th><th>Strateji</th><th>Neden</th></tr>
              </thead>
              <tbody>
                {(decisionsExpanded ? decisions : decisions.slice(0, 5)).map((d) => (
                  <tr key={d.id}>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDay(d.timestamp)}</td>
                    <td><SymbolLink symbol={d.symbol} className="font-bold text-white hover:text-neon-green" /></td>
                    <td className={`font-mono text-xs font-bold ${String(d.decision).startsWith("CLOSE") ? "text-neon-red" : "text-neon-green"}`}>
                      {String(d.decision || "—")}
                    </td>
                    <td className="font-mono text-xs">{formatPrice(Number(d.price || 0))}</td>
                    <td className="text-xs">{STRATEGY_LABEL[d.strategy || ""] || d.strategy || "—"}</td>
                    <td className="max-w-md truncate text-xs text-bunker-muted" title={d.reason}>{d.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- Kapanan otonom işlemler — pagination'lı tam geçmiş ---- */}
      <section className="card mt-5">
        <div className="ui-section-header">
          <div>
            <p className="eyebrow text-neon-green">📜 KAPANAN OTONOM İŞLEMLER</p>
            <h2 className="font-mono text-lg font-bold text-white">İşlem Geçmişi</h2>
            <p className="ui-section-description">Tüm kapanan otonom işlemler — güne göre, sayfalı liste.</p>
          </div>
        </div>
        {apHistory.length === 0 ? (
          <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
            Henüz kapanan otonom işlem yok.
          </div>
        ) : (
          <div className="table-scroll mt-3">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sembol</th><th>Giriş Zamanı</th><th>Giriş</th><th>Çıkış</th>
                  <th>K/Z</th><th>%</th><th>Sebep</th><th>Süre</th>
                </tr>
              </thead>
              <tbody>
                {apHistory.map((t) => {
                  const pnl = closedPnlTry(t.pnl);
                  const pnlPct = closedPnlTry(t.pnl_pct);
                  const holdMin = t.entry_time && t.exit_time ? Math.max(0, Math.round((Number(t.exit_time) - Number(t.entry_time)) / 60)) : null;
                  return (
                    <tr key={t.id}>
                      <td><SymbolLink symbol={t.symbol} className="font-bold text-white hover:text-neon-green" /></td>
                      <td className="font-mono text-xs text-bunker-muted">{fmtDay(t.entry_time)}</td>
                      <td className="font-mono text-xs">{formatPrice(Number(t.entry_price || 0))}</td>
                      <td className="font-mono text-xs">{formatPrice(Number(t.exit_price || 0))}</td>
                      <td className={`font-mono text-xs font-bold ${tone(pnl)}`}>{signedMoney(pnl)}</td>
                      <td className={`font-mono text-xs ${tone(pnlPct)}`}>{pctText(pnlPct)}</td>
                      <td className="text-xs">{REASON_LABEL[t.exit_reason || ""] || t.exit_reason || "—"}</td>
                      <td className="font-mono text-xs text-bunker-muted">{holdMin != null ? `${holdMin} dk` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {/* Pagination */}
        {apHistory.length > 0 && (
          <div className="flex items-center justify-between border-t border-bunker-800 px-4 py-3">
            <button
              type="button"
              disabled={apHistoryPage === 0}
              onClick={() => setApHistoryPage((p) => Math.max(0, p - 1))}
              className="rounded border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted transition-colors hover:border-neon-green/40 hover:text-neon-green disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← ÖNCEKİ
            </button>
            <span className="font-mono text-xs text-bunker-muted">Sayfa {apHistoryPage + 1}</span>
            <button
              type="button"
              disabled={apHistory.length < AP_HISTORY_PAGE_SIZE}
              onClick={() => setApHistoryPage((p) => p + 1)}
              className="rounded border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted transition-colors hover:border-neon-green/40 hover:text-neon-green disabled:cursor-not-allowed disabled:opacity-40"
            >
              SONRAKİ →
            </button>
          </div>
        )}
      </section>

      <p className="mt-4 text-center font-mono text-[10px] text-bunker-muted/60">
        Paper trading · gerçek para kullanılmaz · veriler canlı WS ve 10 sn'de bir yenilenir
      </p>
    </main>
  );
}
