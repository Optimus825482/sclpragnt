"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { fmtDateTime, formatSignedTL } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

type OpenRow = {
  id: number;
  symbol: string;
  entry_price: number;
  current_price: number | null;
  quantity: number | null;
  order_value_try: number | null;
  tp_pct: number | null;
  take_profit: number | null;
  stop_loss: number | null;
  peak_price: number | null;
  trailing_activated: boolean | null;
  trailing_stop: number | null;
  potential_pct: number | null;
  unrealized_pct: number | null;
  gross_pct?: number | null;   // komisyonsuz fiyat hareketi
  net_try?: number | null;     // komisyon düşülmüş TL
  net_pct?: number | null;     // komisyon düşülmüş %
  entry_time: number | null;
};

type ClosedRow = {
  id: number;
  symbol: string;
  entry_price: number;
  exit_price: number | null;
  order_value_try: number | null;
  exit_reason: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  tp_pct: number | null;
  entry_time: number | null;
  exit_time: number | null;
};

type Stats = {
  initial_balance_try: number;
  cash_try: number;
  open_count: number;
  closed_count: number;
  winning: number;
  losing: number;
  win_rate: number | null;
  realized_pnl_try: number;
  gross_avg_pnl_pct: number | null;
  best_pnl_try: number | null;
  worst_pnl_try: number | null;
};

const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`;

const price = (v: number | null | undefined): string => {
  if (v == null) return "—";
  const x = Number(v);
  if (x >= 1000) return x.toLocaleString("tr-TR", { maximumFractionDigits: 0 });
  if (x >= 100) return x.toFixed(2);
  if (x >= 1) return x.toFixed(4);
  return x.toFixed(6);
};

const reasonLabel: Record<string, string> = {
  take_profit: "TP", trailing_stop: "Trailing", stop_loss: "Stop",
  max_duration: "Süre doldu", manual_close: "Elle kapatıldı", symbol_deactivated: "Sembol pasif",
};

/** KOMBİNE PAPER PORTFÖY (ayrı 5.000 TL) — WhatsApp kombine listesi adaylarının
    otonom açtığı pozisyonlar. Hem Raporlar hem Portföy sayfasında kullanılır. */
export default function CombinedPaperPanel() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [open, setOpen] = useState<OpenRow[]>([]);
  const [closed, setClosed] = useState<ClosedRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getJSON<any>("/api/combined-paper/state");
      setStats(d?.stats ?? null);
      setOpen(Array.isArray(d?.open) ? d.open : []);
      setClosed(Array.isArray(d?.closed) ? d.closed : []);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kombine paper verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(() => { void load(); }, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const doReset = async () => {
    if (!window.confirm("Kombine paper portföyü sıfırlanacak (tüm işlemler silinir, cüzdan başlangıca döner). Emin misiniz?")) return;
    setBusy("reset");
    try { await apiRequest(`${API_BASE}/api/combined-paper/reset`, { method: "POST" }); await load(); }
    finally { setBusy(""); }
  };

  const closeOne = async (id: number) => {
    setBusy(`c${id}`);
    try { await apiRequest(`${API_BASE}/api/combined-paper/close/${id}`, { method: "POST" }); await load(); }
    finally { setBusy(""); }
  };

  const equity = stats ? (stats.cash_try || 0) : 0;
  // Açık pozisyonların TOPLAM net K/Z'si (komisyon düşülmüş) — renkli gösterilir.
  const openNet = open.reduce((a, t) => a + (t.net_try ?? 0), 0);
  // Toplam portföy değeri = nakit + açık pozisyonların net değeri.
  const openValue = open.reduce((a, t) => a + (t.order_value_try ?? 0), 0);
  const openNetPct = openValue > 0 ? (openNet / openValue) * 100 : null;

  return (
    <div className="space-y-4">
      {/* KPI kartları */}
      {stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="text-[10px] text-bunker-muted font-mono">NAKİT (SERBEST)</p>
            <p className="font-mono text-2xl font-black text-white">{formatSignedTL(equity)}</p>
            <p className="text-[10px] text-bunker-muted font-mono">başlangıç {formatSignedTL(stats.initial_balance_try)}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="text-[10px] text-bunker-muted font-mono">GERÇEKLEŞEN K/Z</p>
            <p className={`font-mono text-2xl font-black ${(stats.realized_pnl_try ?? 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
              {formatSignedTL(stats.realized_pnl_try)}
            </p>
            <p className="text-[10px] text-bunker-muted font-mono">{stats.closed_count} kapanan</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="text-[10px] text-bunker-muted font-mono">KAZANMA ORANI</p>
            <p className={`font-mono text-2xl font-black ${(stats.win_rate ?? 0) >= 50 ? "text-neon-green" : "text-yellow-300"}`}>
              {stats.win_rate != null ? `%${stats.win_rate.toFixed(1)}` : "—"}
            </p>
            <p className="text-[10px] text-bunker-muted font-mono">{stats.winning}K / {stats.losing}Z</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="text-[10px] text-bunker-muted font-mono">AÇIK POZİSYON</p>
            <p className="font-mono text-2xl font-black text-yellow-300">{stats.open_count}</p>
            <p className={`text-[10px] font-mono font-bold ${openNet >= 0 ? "text-neon-green" : "text-neon-red"}`}>
              net {formatSignedTL(openNet)}{openNetPct != null ? ` (${pct(openNetPct)})` : ""}
            </p>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={load} className="ui-button ui-button-secondary text-xs py-1.5 px-3">Yenile</button>
        <button type="button" disabled={busy !== ""} onClick={doReset}
          className="ui-button ui-button-secondary text-xs py-1.5 px-3 disabled:opacity-40 text-neon-red">
          {busy === "reset" ? "Sıfırlanıyor…" : "♻️ Portföyü Sıfırla"}
        </button>
        <span className="font-mono text-[11px] text-bunker-muted">
          Her pozisyon = serbest bakiyenin %10&#39;u · komisyon Binance TR · TP potansiyele göre · kârda trailing
        </span>
      </div>

      {error ? <div className="card p-4 rounded-2xl border border-neon-red/40 bg-neon-red/5 text-neon-red font-mono text-xs">⚠ {error}</div> : null}

      {/* Açık pozisyonlar */}
      <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4 space-y-3">
        <h3 className="font-mono text-sm font-black text-white">📈 AÇIK POZİSYONLAR ({open.length})</h3>
        {loading ? (
          <p className="py-6 text-center font-mono text-xs text-bunker-muted">Yükleniyor…</p>
        ) : open.length === 0 ? (
          <p className="py-6 text-center font-mono text-xs text-bunker-muted">Açık pozisyon yok. Yeni kombine liste gönderildiğinde otomatik açılır.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Sembol</th><th className="text-right">Giriş</th><th className="text-right">Anlık</th>
                  <th className="text-right">Değer</th><th className="text-right">TP%</th>
                  <th className="text-right">Potansiyel</th>
                  <th className="text-right" title="Komisyon düşülmüş net kâr/zarar (₺)">Net K/Z ₺</th>
                  <th className="text-right" title="Komisyon düşülmüş net kâr/zarar (%)">Net %</th>
                  <th>Durum</th><th></th>
                </tr>
              </thead>
              <tbody>
                {open.map((t) => {
                  // NET = komisyon düşülmüş (yeşil kâr / kırmızı zarar). Backend
                  // net_try/net_pct verir; yoksa unrealized_pct'e düş.
                  const netT = t.net_try ?? null;
                  const netP = t.net_pct ?? t.unrealized_pct ?? null;
                  // ÖNEMLİ: `.data-table td` kuralı (beyaz) Tailwind text-* sınıfını
                  // özgüllükte ezer → projedeki KANONİK `ui-tone-positive/negative`
                  // sınıfları kullanılır (globals.css:449-450) ki renk gerçekten
                  // uygulanır (yeşil kâr / kırmızı zarar).
                  const toneCls = netP == null ? "text-bunker-muted"
                    : (netP >= 0 ? "ui-tone-positive" : "ui-tone-negative");
                  return (
                  <tr key={t.id}>
                    <td><SymbolLink symbol={t.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="text-right font-mono text-xs text-white">{price(t.entry_price)}</td>
                    <td className="text-right font-mono text-xs text-white">{price(t.current_price)}</td>
                    <td className="text-right font-mono text-xs text-bunker-muted">{formatSignedTL(t.order_value_try)}</td>
                    <td className="text-right font-mono text-xs ui-tone-green">{t.tp_pct != null ? `+${Number(t.tp_pct).toFixed(1)}` : "—"}</td>
                    <td className="text-right font-mono text-xs ui-tone-amber">{t.potential_pct != null ? `+%${Math.round(Number(t.potential_pct))}` : "—"}</td>
                    <td className={`text-right font-mono text-sm font-bold tabular-nums ${toneCls}`}>{netT != null ? formatSignedTL(netT) : "—"}</td>
                    <td className={`text-right font-mono text-sm font-bold tabular-nums ${toneCls}`}>{pct(netP)}</td>
                    <td className="font-mono text-[10px]">
                      {t.trailing_activated
                        ? <span className="rounded border border-neon-green/50 bg-neon-green/15 px-1.5 py-0.5 text-neon-green">🔒 trailing</span>
                        : <span className="text-bunker-muted">izleniyor</span>}
                    </td>
                    <td>
                      <button type="button" disabled={busy !== ""} onClick={() => void closeOne(t.id)}
                        className="rounded border border-bunker-700 bg-bunker-900 px-1.5 py-0.5 font-mono text-[10px] text-bunker-muted hover:text-neon-red disabled:opacity-40">
                        {busy === `c${t.id}` ? "…" : "Kapat"}
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {/* AÇIK POZİSYONLARIN TOPLAM NET K/Z'si (kullanıcı isteği 2026-10-11) —
            listenin alt kısmında, renkli. */}
        {open.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-bunker-800 pt-3 font-mono text-sm">
            <span className="text-bunker-muted">
              Açık {open.length} pozisyonun toplam net K/Z'si (komisyon düşülmüş):
            </span>
            <span className={`font-black text-base ${openNet >= 0 ? "ui-tone-positive" : "ui-tone-negative"}`}>
              {formatSignedTL(openNet)}{openNetPct != null ? ` (${pct(openNetPct)})` : ""}
            </span>
          </div>
        ) : null}
      </section>

      {/* Kapanan işlemler */}
      <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4 space-y-3">
        <h3 className="font-mono text-sm font-black text-white">✅ KAPANAN İŞLEMLER ({closed.length})</h3>
        {closed.length === 0 ? (
          <p className="py-6 text-center font-mono text-xs text-bunker-muted">Henüz kapanan işlem yok.</p>
        ) : (
          <div className="table-scroll max-h-[460px]">
            <table className="data-table table-compact">
              <thead>
                <tr>
                  <th>Kapanış</th><th>Sembol</th><th className="text-right">Giriş</th>
                  <th className="text-right">Çıkış</th><th className="text-right">Değer</th>
                  <th>Neden</th><th className="text-right">K/Z</th><th className="text-right">K/Z%</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((t) => {
                  const win = (t.pnl ?? 0) >= 0;
                  const reason = t.exit_reason || "";
                  // Çıkış nedeni rozeti: stop/süre = kırmızı, trailing/TP = yeşil.
                  const reasonCls = reason === "take_profit"
                    ? "border-neon-green/50 bg-neon-green/15 text-neon-green"
                    : reason === "trailing_stop"
                      ? "border-sky-400/50 bg-sky-400/15 text-sky-300"
                      : (reason === "stop_loss" || reason === "max_duration")
                        ? "border-neon-red/40 bg-neon-red/10 text-neon-red"
                        : "border-bunker-700 bg-bunker-800 text-bunker-muted";
                  return (
                  <tr key={t.id} className={win ? "bg-neon-green/[0.04]" : "bg-neon-red/[0.04]"}>
                    <td className="font-mono text-xs text-bunker-muted whitespace-nowrap">{t.exit_time ? fmtDateTime(t.exit_time * 1000) : "—"}</td>
                    <td><SymbolLink symbol={t.symbol} className="font-mono font-bold text-white hover:text-neon-green" /></td>
                    <td className="text-right font-mono text-xs text-white">{price(t.entry_price)}</td>
                    <td className="text-right font-mono text-xs text-white">{price(t.exit_price)}</td>
                    <td className="text-right font-mono text-xs text-bunker-muted">{formatSignedTL(t.order_value_try)}</td>
                    <td>
                      <span className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold ${reasonCls}`}>
                        {reasonLabel[reason] || reason || "—"}
                      </span>
                    </td>
                    <td className={`text-right font-mono text-sm font-bold tabular-nums ${win ? "ui-tone-positive" : "ui-tone-negative"}`}>{formatSignedTL(t.pnl)}</td>
                    <td className={`text-right font-mono text-sm font-bold tabular-nums ${win ? "ui-tone-positive" : "ui-tone-negative"}`}>{pct(t.pnl_pct)}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
