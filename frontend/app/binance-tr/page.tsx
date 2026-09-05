"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type Balance = { asset: string; free: string; locked: string };

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
  const [configured, setConfigured] = useState(false);
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

  const [tradeDay, setTradeDay] = useState(() =>
    new Date().toISOString().slice(0, 10)
  );
  const [trades, setTrades] = useState<Trade[]>([]);
  const [trLoading, setTrLoading] = useState(false);
  const [trMeta, setTrMeta] = useState<{ count: number; symbols_scanned: number } | null>(null);

  const check = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setConfigured(d.configured);
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
        setTrMeta({ count: d.count || 0, symbols_scanned: d.symbols_scanned || 0 });
      }
    } catch { /* */ }
    finally { setTrLoading(false); }
  }, [tradeDay]);

  useEffect(() => { if (configured && tradeDay) loadTrades(); }, [configured, tradeDay, loadTrades]);

  const saveKeys = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) return;
    setSaving(true);
    setKeyError("");
    try {
      const r = await apiRequest(API_BASE + "/api/binance/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim() }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Kaydedilemedi");
      }
      setConfigured(true);
      setSettingsOpen(false);
      loadAcct();
      loadOrd();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Kayit hatasi");
    } finally {
      setSaving(false);
    }
  };

  const nonZero = balances.filter((b) => parseFloat(b.free) > 0 || parseFloat(b.locked) > 0);

  // 50 TL altını gizle (fiyatı çözülemeyenler gizlenmez — değeri bilinmiyor)
  const visibleHoldings = useMemo(() => {
    if (!hideSmall) return holdings;
    return holdings.filter((h) => h.value_try == null || h.value_try >= 50);
  }, [holdings, hideSmall]);

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
        body: JSON.stringify({ asset: sellFor.asset, quantity: qty }),
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

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">BINANCE TR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Canli Hesap</h1>
          <p className="mt-1 text-sm text-bunker-muted">Gerçek Binance TR bakiyesi, TRY degerleri ve islem gecmisi — satış yalnızca bu ekrandan onayla</p>
        </div>
        <div className="flex items-center gap-2">
          {configured && !acctLoading && (
            <span className="rounded border border-neon-green/40 bg-neon-green/10 px-2 py-1 font-mono text-[10px] text-neon-green">KEY TANIMLI</span>
          )}
          <button type="button" onClick={() => setSettingsOpen(true)} className="ui-button ui-button-secondary">AYARLAR</button>
        </div>
      </div>

      {settingsOpen && (
        <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4" role="dialog" aria-modal="true">
          <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-mono text-lg font-bold text-white">Binance TR API Anahtarlari</h2>
              <button type="button" onClick={() => setSettingsOpen(false)} className="text-bunker-muted hover:text-white">X</button>
            </div>
            <p className="text-xs text-bunker-muted mb-4">Fernet sifreli kaydedilir. Satis emirleri yalnizca bu ekrandaki onay adimindan sonra gonderilir.</p>
            <div className="space-y-3">
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
                <button type="button" onClick={saveKeys} disabled={saving || !apiKey.trim() || !apiSecret.trim()} className="ui-button ui-button-primary">
                  {saving ? "KAYDEDILIYOR..." : "KAYDET"}
                </button>
              </div>
            </div>
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
              {ordLoading && <span className="font-mono text-[10px] text-bunker-muted animate-pulse">Yukleniyor...</span>}
            </div>
            {visibleHoldings.length === 0 ? (
              <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
                {holdings.length === 0 ? "Gosterilecek varlik yok." : "Filtreye uyan varlik yok (50 TL altindakiler gizli)."}
              </div>
            ) : (
              <div className="table-scroll mt-3">
                <table className="data-table">
                  <thead><tr><th>Sembol</th><th>Miktar</th><th>Kilitli</th><th>Alım Maliyeti</th><th>Güncel Fiyat</th><th>Anlık K/Z</th><th>TRY Deger</th><th></th></tr></thead>
                  <tbody>
                    {visibleHoldings.map((h) => {
                      const pnlToneCls = h.pnl_try == null ? "" : h.pnl_try >= 0 ? "text-neon-green" : "text-neon-red";
                      return (
                        <tr key={h.asset}>
                          <td><span className="font-mono font-bold text-white">{h.asset}</span></td>
                          <td className="font-mono text-xs">{fmtPrice(h.free, 6)}</td>
                          <td className="font-mono text-xs text-bunker-muted">{h.locked > 0 ? fmtPrice(h.locked, 6) : "—"}</td>
                          <td className="font-mono text-xs text-bunker-muted">{h.avg_cost_try != null ? `₺${fmtPrice(h.avg_cost_try, h.avg_cost_try < 1 ? 6 : 2)}` : "—"}</td>
                          <td className="font-mono text-xs text-white">{h.price_try != null ? `₺${fmtPrice(h.price_try, h.price_try < 1 ? 6 : 2)}` : "—"}</td>
                          <td className={`font-mono text-xs font-bold ${pnlToneCls}`}>
                            {h.pnl_try != null ? `₺${h.pnl_try >= 0 ? "+" : "−"}${fmtPrice(Math.abs(h.pnl_try))}` : "—"}
                            {h.pnl_pct != null ? (
                              <span className="ml-1 font-normal">({h.pnl_pct >= 0 ? "+" : "−"}%{fmtPrice(Math.abs(h.pnl_pct), 2)})</span>
                            ) : null}
                          </td>
                          <td className={`font-mono text-xs font-bold ${h.value_try != null ? "text-white" : "text-bunker-muted"}`}>
                            {h.value_try != null ? `₺${fmtPrice(h.value_try)}` : "fiyat yok"}
                          </td>
                          <td className="text-right">
                            <button
                              type="button"
                              onClick={() => openSell(h)}
                              disabled={h.free <= 0 || h.asset === "TRY" || h.price_try == null}
                              title={h.asset === "TRY" ? "TRY satılamaz" : h.price_try == null ? "Piyasa fiyatı bulunamadı" : h.free <= 0 ? "Boşta bakiye yok" : "Piyasa fiyatından sat"}
                              className="rounded border border-neon-red/50 bg-neon-red/10 px-2.5 py-1 font-mono text-[11px] font-bold text-neon-red transition-colors hover:bg-neon-red/20 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              SAT
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
          {sellFor && (
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
                  Dikkat: GERÇEK piyasa emri gönderilir ve iptal edilemez. Emir MARKET tipinde, sembol {sellFor.asset}_TRY yoksa {sellFor.asset}_USDT üzerinde açılır.
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
            {trades.length === 0 && !trLoading ? (
              <div className="mt-3 rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
                Bu günde işlem yok.
              </div>
            ) : (
              <div className="table-scroll mt-3">
                <table className="data-table">
                  <thead><tr><th>Zaman</th><th>Sembol</th><th>Yön</th><th>Fiyat</th><th>Miktar</th><th>Toplam</th><th>Komisyon</th></tr></thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={`${t.id}-${t.symbol}`}>
                        <td className="font-mono text-xs text-bunker-muted">{fmtTime(t.time)}</td>
                        <td><span className="font-mono font-bold text-white">{t.symbol}</span></td>
                        <td className={"font-mono text-xs font-bold " + (t.isBuyer ? "text-neon-green" : "text-neon-red")}>
                          {t.isBuyer ? "ALIS" : "SATIS"}
                        </td>
                        <td className="font-mono text-xs">{fmtPrice(t.price, Number(t.price) < 1 ? 6 : 2)}</td>
                        <td className="font-mono text-xs">{fmtPrice(t.qty, 6)}</td>
                        <td className="font-mono text-xs">{fmtPrice(t.quoteQty, Number(t.quoteQty) < 1 ? 6 : 2)}</td>
                        <td className="font-mono text-xs text-bunker-muted">{fmtPrice(t.commission, 6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}