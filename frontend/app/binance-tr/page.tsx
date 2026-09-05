"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type Balance = { asset: string; free: string; locked: string };

type OpenOrder = {
  symbol: string;
  orderId: number;
  price: string;
  origQty: string;
  side: string;
  time: number;
  status: string;
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

  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [ordLoading, setOrdLoading] = useState(false);

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [startDate, setStartDate] = useState(() =>
    new Date().toISOString().slice(0, 10)
  );
  const [endDate, setEndDate] = useState(() =>
    new Date().toISOString().slice(0, 10)
  );
  const [trades, setTrades] = useState<Trade[]>([]);
  const [trLoading, setTrLoading] = useState(false);
  const [page, setPage] = useState(0);
  const PER_PAGE = 50;

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
      if (r.ok) setOrders((await r.json()).orders || []);
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

  const loadTrades = useCallback(async (p: number) => {
    setTrLoading(true);
    try {
      const st = startDate ? new Date(startDate + "T00:00:00Z").getTime() : 0;
      const et = endDate ? new Date(endDate + "T23:59:59Z").getTime() : 0;
      const offset = p * PER_PAGE;
      const r = await apiRequest(
        API_BASE + "/api/binance/trades?symbol=" + encodeURIComponent(symbol) + "&start_time=" + st + "&end_time=" + et + "&limit=" + PER_PAGE + "&offset=" + offset,
        { cache: "no-store" }
      );
      if (r.ok) setTrades((await r.json()).trades || []);
    } catch { /* */ }
    finally { setTrLoading(false); }
  }, [symbol, startDate, endDate]);

  useEffect(() => { if (configured && symbol) loadTrades(page); }, [configured, symbol, page, loadTrades]);

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

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">BINANCE TR</p>
          <h1 className="font-mono text-2xl font-bold text-white">Canli Hesap</h1>
          <p className="mt-1 text-sm text-bunker-muted">Gerçek Binance TR bakiyesi ve islem gecmisi (salt okunur)</p>
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
            <p className="text-xs text-bunker-muted mb-4">Fernet sifreli kaydedilir. Sadece okuma (GET) - emir gonderilmez.</p>
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
                <p className="eyebrow text-neon-green">ACIK EMIRLER / POZISYON</p>
                <h2 className="font-mono text-lg font-bold text-white">Anlik Durum</h2>
              </div>
              {ordLoading && <span className="font-mono text-[10px] text-bunker-muted animate-pulse">Yukleniyor...</span>}
            </div>
            {orders.length === 0 ? (
              <div className="rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">Acik emir yok.</div>
            ) : (
              <div className="table-scroll mt-3">
                <table className="data-table">
                  <thead><tr><th>Sembol</th><th>Taraf</th><th>Fiyat</th><th>Miktar</th><th>Durum</th><th>Zaman</th></tr></thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.orderId}>
                        <td><span className="font-mono font-bold text-white">{o.symbol}</span></td>
                        <td className={"font-mono text-xs " + (o.side === "BUY" ? "text-neon-green" : "text-neon-red")}>{o.side}</td>
                        <td className="font-mono text-xs">{fmtPrice(o.price)}</td>
                        <td className="font-mono text-xs">{fmtPrice(o.origQty)}</td>
                        <td className="font-mono text-xs">{o.status}</td>
                        <td className="font-mono text-xs text-bunker-muted">{fmtTime(o.time)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card mt-5">
            <div className="ui-section-header">
              <div>
                <p className="eyebrow text-neon-green">GECMIS ISLEMLER</p>
                <h2 className="font-mono text-lg font-bold text-white">Islem Gecmisi</h2>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <select value={symbol} onChange={(e) => { setSymbol(e.target.value); setPage(0); }} className="input w-32 font-mono text-sm">
                {KNOWN_SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <label>
                <span className="font-mono text-[10px] text-bunker-muted mr-1">Baslangic</span>
                <input type="date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(0); }} className="input font-mono text-xs" />
              </label>
              <label>
                <span className="font-mono text-[10px] text-bunker-muted mr-1">Bitis</span>
                <input type="date" value={endDate} onChange={(e) => { setEndDate(e.target.value); setPage(0); }} className="input font-mono text-xs" />
              </label>
            </div>
            {trades.length === 0 && !trLoading ? (
              <div className="mt-3 rounded-lg border border-dashed border-bunker-700 bg-bunker-900/40 px-4 py-6 text-center text-sm text-bunker-muted">
                Bu tarih araliginda islem yok.
              </div>
            ) : (
              <div className="table-scroll mt-3">
                <table className="data-table">
                  <thead><tr><th>Zaman</th><th>Sembol</th><th>Yon</th><th>Fiyat</th><th>Miktar</th><th>Toplam</th><th>Komisyon</th></tr></thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.id}>
                        <td className="font-mono text-xs text-bunker-muted">{fmtTime(t.time)}</td>
                        <td><span className="font-mono font-bold text-white">{t.symbol}</span></td>
                        <td className={"font-mono text-xs font-bold " + (t.isBuyer ? "text-neon-green" : "text-neon-red")}>
                          {t.isBuyer ? "ALIS" : "SATIS"}
                        </td>
                        <td className="font-mono text-xs">{fmtPrice(t.price)}</td>
                        <td className="font-mono text-xs">{fmtPrice(t.qty)}</td>
                        <td className="font-mono text-xs">{fmtPrice(t.quoteQty)}</td>
                        <td className="font-mono text-xs text-bunker-muted">{fmtPrice(t.commission)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-4 flex items-center justify-between border-t border-bunker-800 px-4 py-3">
              <button type="button" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="rounded border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted transition-colors hover:border-neon-green/40 hover:text-neon-green disabled:cursor-not-allowed disabled:opacity-40">
                ONCEKI
              </button>
              <span className="font-mono text-xs text-bunker-muted">Sayfa {page + 1}</span>
              <button type="button" disabled={trades.length < PER_PAGE} onClick={() => setPage((p) => p + 1)}
                className="rounded border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted transition-colors hover:border-neon-green/40 hover:text-neon-green disabled:cursor-not-allowed disabled:opacity-40">
                SONRAKI
              </button>
            </div>
          </section>
        </>
      )}
    </main>
  );
}