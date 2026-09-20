"use client";

/**
 * Ana Sayfa — Mobil öncelikli dashboard.
 * Hoş geldin mesajı + bugünün sinyal/success/otonom/PnL özeti + portföy bakiyesi.
 * Basit modda (ui-mode) yalnızca temel metrikler + son aktivite.
 * Gelişmiş modda (varsayılan) otonom pozisyonlar + strateji performansı eklenir.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "./lib/api";
import { useAuth } from "./lib/auth";
import { useLiveMessages as useLiveSocketMessages, useLiveStatus } from "./lib/liveSocket";
import { useUiMode } from "./lib/ui-mode";
import { useVisibleInterval } from "./lib/useVisibleInterval";
import { formatPrice, formatSignedTL, formatTL, toMs } from "./lib/format";
import { netOpenPnlPct, netOpenPnlTry } from "./lib/pnl";

/* ============== TİPLER ============== */
type DashboardSummary = {
  signals_today: { total: number; buy_signals: number; close_signals: number };
  auto_paper_today: { trades: number; pnl: number; winning: number; losing: number };
  portfolio: { balance: number; open_positions: number; total_value: number };
};
type AutoPaperTrade = {
  id: number; symbol: string; entry_price: number; current_price?: number | null;
  quantity: number; take_profit?: number | null; stop_loss?: number | null;
};
type LiveSignal = { id?: number; symbol: string; action: string; price?: number; reason?: string; timestamp?: number };

/* ============== YARDIMCILAR ============== */
// H-04/H-15: TL biçimi tek kaynaktan (`lib/format.ts`) — ₺ önek, 2 ondalık.
const money = formatTL;
const signedMoney = formatSignedTL;
const fmtTime = (ts?: number | null) => {
  // H-24: elle `* 1000` yerine `toMs` (saniye/ms karışık girdi güvenli).
  const ms = toMs(ts);
  if (!ms) return "";
  return new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
};

function MetricCard({ label, value, hint, tone = "" }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="ui-card ui-stat-card">
      <p className="eyebrow">{label}</p>
      <p className={`ui-stat-value ${tone}`}>{value}</p>
      {hint && <p className="ui-stat-detail">{hint}</p>}
    </div>
  );
}

/* ============== SAYFA ============== */
export default function Home() {
  const { username } = useAuth();
  const liveStatus = useLiveStatus();
  const [mode, toggleMode] = useUiMode();
  const isAdvanced = mode === "advanced";

  // Dashboard verisi
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [autoPaperOpen, setAutoPaperOpen] = useState<AutoPaperTrade[]>([]);
  const [liveSignals, setLiveSignals] = useState<LiveSignal[]>([]);
  // H-05: ağ hatası "veri yok" gibi görünmemeli. Eskiden `load` hatayı yutup
  // "₺0,00 / …" bırakıyordu; kullanıcı sıfır bakiyeyi bağlantı hatasından
  // ayırt edemiyordu.
  const [loadError, setLoadError] = useState<string | null>(null);

  // Yükle
  const load = useCallback(async () => {
    if (document.hidden) return;
    const getJson = async (path: string) => {
      const r = await apiRequest(`${API_BASE}${path}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    };
    const [summaryRes, apRes, signalsRes] = await Promise.allSettled([
      getJson("/api/dashboard/summary"),
      getJson("/api/auto-paper/trades?status=open"),
      getJson("/api/signals?limit=30"),
    ]);
    if (summaryRes.status === "fulfilled") setSummary(summaryRes.value);
    if (apRes.status === "fulfilled") setAutoPaperOpen(apRes.value.trades || []);
    if (signalsRes.status === "fulfilled") setLiveSignals((signalsRes.value.signals || []).slice(-10).reverse());
    const failed = [summaryRes, apRes, signalsRes].filter((r) => r.status === "rejected").length;
    setLoadError(failed === 0 ? null : failed === 3 ? "Backend'e bağlanılamadı — veriler alınamıyor." : "Bazı veriler alınamadı.");
  }, []);

  useEffect(() => { load(); }, [load]);
  useVisibleInterval(load, 15_000);

  // WS
  useLiveSocketMessages(useCallback((msg: any) => {
    if (msg.type === "signal") {
      setLiveSignals((prev) => [msg.data, ...prev].slice(0, 10));
      // Listeyi boşaltmak 15 sn'lik poll'a kadar "pozisyonlar kayboldu" görüntüsü
      // veriyordu; yalnızca tazeleme tetikle, mevcut liste kalsın.
      load();
    }
    // H-20: backend `portfolio_reconciled` / `llm_position_management` / `reset`
    // yayınlıyor ama ana sayfada tüketici yoktu → mutabakat veya LLM pozisyon
    // açılışı sonrası özet 15 sn'ye kadar bayat kalıyordu.
    if (["portfolio_reconciled", "llm_position_management", "reset", "auto_paper_trade"].includes(msg.type)) {
      load();
    }
  }, [load]));

  const s = summary;
  // Özet henüz yüklenmediyse (s == null) nötr renk: eskiden bu durum KIRMIZI
  // gösteriyordu, yani sayfa açılırken "zarar" izlenimi oluşuyordu.
  // H-02: PnL alanı `null` ise de NÖTR — 0 sayıp yeşile boyamak yasak.
  const apTodayPnl = s?.auto_paper_today.pnl ?? null;
  const pnlTone = apTodayPnl == null
    ? "text-bunker-muted"
    : apTodayPnl >= 0 ? "text-neon-green" : "text-neon-red";
  const apPnl = apTodayPnl;

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      {/* Üst: Hoş geldin + canlı + mod toggle */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">CANLI DASHBOARD</p>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            {username ? (
              <>Hoş geldin, <span className="text-neon-green">{username.charAt(0).toUpperCase() + username.slice(1)}</span> 👋</>
            ) : (
              <>PORTFÖY & <span className="text-neon-green">SCALPING</span></>
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded border px-2 py-1 font-mono text-[10px] ${liveStatus === "open" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-yellow-300/40 bg-yellow-300/10 text-yellow-300"}`}>
            {liveStatus === "open" ? "● CANLI" : "○ BAĞLANTI KESİK"}
          </span>
          <button onClick={toggleMode} className="rounded border border-bunker-700 px-2 py-1 font-mono text-[10px] text-bunker-muted hover:border-neon-green/40 hover:text-neon-green" title={`Şu an: ${isAdvanced ? "Gelişmiş" : "Basit"} mod`}>
            {isAdvanced ? "⚙ GELİŞMİŞ" : "🔵 BASİT"}
          </button>
        </div>
      </header>

      {/* H-05: ağ hatası durumu — "veri yok"tan ayırt edilebilir olmalı */}
      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-neon-red/40 bg-neon-red/5 px-3 py-2">
          <p className="font-mono text-xs text-neon-red">⚠ {loadError}</p>
          <button
            type="button"
            onClick={() => { setLoadError(null); void load(); }}
            className="rounded border border-neon-red/40 px-2 py-1 font-mono text-[11px] text-neon-red hover:bg-neon-red/10"
          >
            YENİDEN DENE
          </button>
        </div>
      )}

      {/* 4 kart: 2 sütun mobil, 4 sütun masaüstü */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="BUGÜN SİNYAL" value={String(s?.signals_today.total ?? "…")} hint={`${s?.signals_today.buy_signals ?? 0} giriş · ${s?.signals_today.close_signals ?? 0} çıkış`} />
        <MetricCard label="OTONOM İŞLEM" value={`${s?.auto_paper_today.trades ?? 0} · ${signedMoney(apPnl)}`} tone={s ? pnlTone : ""} hint={`${s?.auto_paper_today.winning ?? 0} kazanç · ${s?.auto_paper_today.losing ?? 0} kayıp`} />
        <MetricCard label="PORTFÖY" value={money(s?.portfolio.total_value)} hint={`${money(s?.portfolio.balance)} serbest`} />
        <MetricCard label="AÇIK POZİSYON" value={String(s?.portfolio.open_positions ?? 0)} hint={s?.portfolio.open_positions ? "pozisyon var" : "yok"} />
      </div>

      {/* Hızlı modül erişim paneli */}
      <nav className="grid grid-cols-2 sm:grid-cols-4 gap-2.5" aria-label="Hızlı Modül Erişimi">
        <Link
          href="/portfolio"
          className="flex items-center justify-between p-3 rounded-xl border border-bunker-800 bg-bunker-900/60 hover:border-neon-green/40 hover:bg-bunker-900 transition-all touch-target group"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-xl">💼</span>
            <div>
              <p className="font-mono text-xs font-bold text-white group-hover:text-neon-green transition-colors">Sanal Portföy</p>
              <p className="text-[10px] text-bunker-muted">Otonom & manuel</p>
            </div>
          </div>
          <span className="font-mono text-xs text-bunker-muted group-hover:text-white transition-colors">→</span>
        </Link>
        <Link
          href="/monitoring"
          className="flex items-center justify-between p-3 rounded-xl border border-bunker-800 bg-bunker-900/60 hover:border-neon-green/40 hover:bg-bunker-900 transition-all touch-target group"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-xl">📡</span>
            <div>
              <p className="font-mono text-xs font-bold text-white group-hover:text-neon-green transition-colors">Radar</p>
              <p className="text-[10px] text-bunker-muted">Hız & fırsat avcısı</p>
            </div>
          </div>
          <span className="font-mono text-xs text-bunker-muted group-hover:text-white transition-colors">→</span>
        </Link>
        <Link
          href="/charts"
          className="flex items-center justify-between p-3 rounded-xl border border-bunker-800 bg-bunker-900/60 hover:border-neon-green/40 hover:bg-bunker-900 transition-all touch-target group"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-xl">📈</span>
            <div>
              <p className="font-mono text-xs font-bold text-white group-hover:text-neon-green transition-colors">Grafik</p>
              <p className="text-[10px] text-bunker-muted">Canlı mum grafiği</p>
            </div>
          </div>
          <span className="font-mono text-xs text-bunker-muted group-hover:text-white transition-colors">→</span>
        </Link>
        <Link
          href="/binance-tr"
          className="flex items-center justify-between p-3 rounded-xl border border-bunker-800 bg-bunker-900/60 hover:border-neon-green/40 hover:bg-bunker-900 transition-all touch-target group"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-xl">🏛️</span>
            <div>
              <p className="font-mono text-xs font-bold text-white group-hover:text-neon-green transition-colors">Binance TR</p>
              <p className="text-[10px] text-bunker-muted">Canlı hesap işlemi</p>
            </div>
          </div>
          <span className="font-mono text-xs text-bunker-muted group-hover:text-white transition-colors">→</span>
        </Link>
      </nav>

      {/* Otonom açık pozisyonlar (yalnız varsa) */}
      {autoPaperOpen.length > 0 && (
        <section className="card">
          <div className="ui-section-header">
            <div><p className="eyebrow text-neon-green">🤖 OTONOM POZİSYONLAR</p></div>
            <span className="font-mono text-xs text-bunker-muted">{autoPaperOpen.length} pozisyon</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {autoPaperOpen.map((t) => {
              const entry = Number(t.entry_price);
              // H-02: ticker yoksa güncel fiyat `null` — entry'ye düşürmek
              // sahte "%0,00 yeşil" üretirdi.
              const current = Number(t.current_price) > 0 ? Number(t.current_price) : null;
              // H-01: net (gidiş-dönüş komisyonu düşülmüş) — backend ile aynı.
              const pnl = netOpenPnlTry(t.entry_price, t.current_price, t.quantity);
              const pnlPct = netOpenPnlPct(t.entry_price, t.current_price, t.quantity);
              const toneClass = pnl == null || pnlPct == null
                ? "text-bunker-muted"
                : pnl >= 0 ? "text-neon-green" : "text-neon-red";
              return (
                <div key={t.id} className="rounded-lg border border-bunker-700 bg-bunker-900/60 p-3">
                  <p className="font-mono font-bold text-white">{t.symbol}</p>
                  <p className={`mt-1 font-mono text-sm ${toneClass}`}>
                    {pnlPct == null || pnl == null
                      ? "—"
                      : `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}% · ${signedMoney(pnl)}`}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-bunker-muted">
                    {current == null ? "güncel fiyat bekleniyor" : `güncel ${formatPrice(current)}`} · TP {formatPrice(t.take_profit)} · SL {formatPrice(t.stop_loss)}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Gelişmiş mod: strateji performansı */}
      {isAdvanced && (
        <section className="card">
          <div className="ui-section-header">
            <div><p className="eyebrow">📊 STRATEJİ PERFORMANSI</p></div>
            <Link href="/reports" className="font-mono text-[11px] text-bunker-muted hover:text-neon-green underline-offset-2 underline">{">"} Raporlar</Link>
          </div>
          <div className="mt-2 flex flex-wrap gap-3">
            <APStatCard label="Bugün sinyal" value={String(s?.signals_today.total ?? 0)} />
            <APStatCard label="Otonom işlem" value={String(s?.auto_paper_today.trades ?? 0)} sub={s ? signedMoney(apPnl) : ""} />
            <APStatCard label="Serbest TL" value={money(s?.portfolio.balance)} />
            <APStatCard label="Toplam Değer" value={money(s?.portfolio.total_value)} />
          </div>
        </section>
      )}

      {/* Son aktivite akışı (mobilde 4-5 satır) */}
      <section className="card bg-bunker-950 p-0 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-bunker-800">
          <p className="eyebrow">SON AKTİVİTE</p>
          {liveStatus === "open" && <span className="font-mono text-[10px] text-neon-green animate-pulse">● LİVE</span>}
        </div>
        <div className="px-4 py-3 font-mono text-sm max-h-40 overflow-y-auto">
          {liveSignals.length === 0 && <p className="text-bunker-muted">Sinyal bekleniyor…</p>}
          {liveSignals.slice(0, isAdvanced ? 8 : 4).map((s, i) => (
            <div key={s.id ?? i} className={`py-1 text-xs ${s.action === "BUY_BLOCKED" ? "text-sky-400" : String(s.action || "").includes("BUY") ? "text-neon-green" : "text-neon-red"}`}>
              <span className="text-bunker-muted">[{fmtTime(s.timestamp)}]</span>{" "}
              <b>{s.action}</b>{" "}
              <span className="text-white">{s.symbol}</span>
              {s.price ? ` @ ${formatPrice(Number(s.price))}` : ""}
              {s.reason && <span className="text-bunker-muted ml-1">· {s.reason}</span>}
            </div>
          ))}
        </div>
        {(liveSignals.length > 4 || isAdvanced) && (
          <div className="border-t border-bunker-800 px-4 py-2 text-center">
            <Link href="/reports" className="font-mono text-[10px] text-bunker-muted hover:text-neon-green underline-offset-2 underline">Tümünü gör →</Link>
          </div>
        )}
      </section>
    </div>
  );
}

function APStatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex-1 rounded-lg border border-bunker-800 bg-bunker-900/50 px-3 py-2 min-w-[100px]">
      <p className="font-mono text-[10px] text-bunker-muted">{label}</p>
      <p className="font-mono text-sm font-bold text-white">{value}</p>
      {sub && <p className="font-mono text-[10px] text-bunker-muted">{sub}</p>}
    </div>
  );
}