"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest, API_BASE } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { formatCompact, formatPct, formatPrice, formatTL } from "../lib/format";
import type { BinancePositions, BinanceSettings, MarketSymbols, MarketTicker } from "../lib/types";
import { Badge, Button, Card } from "./ui";
import SymbolSelect from "./SymbolSelect";

/** Gerçek Binance TR spot paneli. Backend her emir için oturum, API anahtarı ve işlem kapısını doğrular. */
export default function OrderPanel({ initialSymbol, onTraded }: { initialSymbol?: string | null; onTraded?: () => void }) {
  const symbolsQ = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const binance = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const balances = usePoll<BinancePositions>(binance.data?.configured ? "/api/binance/positions" : null, 30_000);
  const [symbol, setSymbol] = useState<string | null>(initialSymbol ?? null);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "gain" | "loss"; text: string } | null>(null);

  useEffect(() => { if (initialSymbol) setSymbol(initialSymbol); }, [initialSymbol]);
  const activeSymbol = symbol || initialSymbol || null;
  const ticker = usePoll<MarketTicker>(activeSymbol ? `/api/market-ticker/${activeSymbol}` : null, 15_000);
  const base = activeSymbol ? activeSymbol.replace("TRY", "").replace("USDT", "") : "";
  const quoteFree = Number(balances.data?.balances?.find((x) => x.asset === "TRY")?.free ?? 0);
  const assetFree = Number(balances.data?.balances?.find((x) => x.asset === base)?.free ?? 0);
  const approxBase = useMemo(() => {
    const value = Number(amount);
    const price = ticker.data?.last;
    return side === "BUY" && price && Number.isFinite(value) && value > 0 ? value / price : null;
  }, [amount, side, ticker.data]);

  async function submitOrder() {
    if (!activeSymbol) return;
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setMessage({ tone: "loss", text: "Geçerli bir tutar veya miktar girin." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const buying = side === "BUY";
      const response = await apiRequest(`${API_BASE}/api/binance/${buying ? "buy" : "sell"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buying
          ? { asset: base, amount_try: value, confirmation: "REAL_BUY" }
          : { asset: base, quantity: value, confirmation: "REAL_SELL" }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof body.detail === "string" ? body.detail : body.detail?.message || body.detail?.reason;
        throw new Error(detail || `Binance emri gönderilemedi (${response.status})`);
      }
      setMessage({ tone: "gain", text: `${buying ? "Alım" : "Satım"} emri Binance TR'ye gönderildi · ${body.symbol || activeSymbol}` });
      setAmount("");
      onTraded?.();
      balances.reload();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Binance emri gönderilemedi" });
    } finally {
      setBusy(false);
    }
  }

  const tickerData = ticker.data;
  const enabled = Boolean(binance.data?.configured && binance.data?.sell_enabled);

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <p className="odak-kicker">Binance TR İşlem Paneli</p>
        <Badge tone={binance.data?.configured ? "gain" : "warn"}>{binance.data?.configured ? "GERÇEK HESAP" : "BAĞLI DEĞİL"}</Badge>
      </div>
      <div className="mt-2"><SymbolSelect symbols={symbolsQ.data?.symbols || []} value={activeSymbol} onChange={setSymbol} /></div>

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

        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" onClick={() => { setSide("BUY"); setAmount(""); }} className={`rounded-lg py-2 text-sm font-semibold ${side === "BUY" ? "bg-gain text-white" : "border border-line text-ink-500"}`}>AL</button>
          <button type="button" onClick={() => { setSide("SELL"); setAmount(""); }} className={`rounded-lg py-2 text-sm font-semibold ${side === "SELL" ? "bg-loss text-white" : "border border-line text-ink-500"}`}>SAT</button>
        </div>
        <div className="mt-3">
          <div className="flex gap-1">
            <span className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white">Piyasa</span>
            <button type="button" disabled className="cursor-not-allowed rounded-lg border border-line px-3 py-1.5 text-xs text-ink-400 opacity-50" title="Bu panelde Limit emir desteği yok">Limit</button>
            <button type="button" disabled className="cursor-not-allowed rounded-lg border border-line px-3 py-1.5 text-xs text-ink-400 opacity-50" title="Bu panelde Stop-Limit emir desteği yok">Stop-Limit</button>
          </div>
          <p className="mt-1.5 text-[10px] text-ink-400">Emir gerçek Binance TR hesabınıza iletilir.</p>
        </div>

        <label className="mt-3 block">
          <span className="odak-kicker">{side === "BUY" ? "Harcanacak tutar (₺)" : `Satılacak miktar (${base})`}</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="0" className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" />
        </label>
        <div className="mt-2 grid grid-cols-4 gap-1.5">
          {[25, 50, 75, 100].map((pct) => <button key={pct} type="button" disabled={side !== "BUY" || quoteFree <= 0} onClick={() => setAmount((quoteFree * pct / 100).toFixed(2))} className="rounded-md border border-line py-1 text-[11px] text-ink-500 hover:border-accent hover:text-accent disabled:opacity-40">%{pct}</button>)}
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-ink-400">
          <span>{side === "BUY" ? `≈ ${approxBase != null ? `${approxBase.toFixed(6)} ${base}` : "—"}` : `Satılabilir: ${assetFree || "—"} ${base}`}</span>
          <span>TRY bakiye: {binance.data?.configured ? formatTL(quoteFree) : "—"}</span>
        </div>
        <p className="mt-1 text-right text-[11px] text-ink-400">Tahmini maliyet: {side === "BUY" && amount ? formatTL(Number(amount)) : "—"}</p>

        <Button variant={side === "BUY" ? "success" : "danger"} className="mt-3 w-full" disabled={busy || !activeSymbol || !Number(amount) || !enabled} onClick={submitOrder}
          title={!binance.data?.configured ? "Önce Ayarlar'dan Binance TR API anahtarını kaydet" : !binance.data?.sell_enabled ? "Ayarlar'da gerçek işlem kapısını aç" : "Gerçek Binance TR market emri gönder"}>
          {busy ? "Gönderiliyor…" : `${side === "BUY" ? "ALIM" : "SATIM"} EMRİ OLUŞTUR`}
        </Button>
        {!binance.data?.configured && <p className="mt-2 text-center text-[11px] text-warn">Gerçek hesabı bağlamak için <Link href="/ayarlar" className="underline">Ayarlar</Link>'dan Binance TR API anahtarlarını kaydedin.</p>}
        {binance.data?.configured && !binance.data.sell_enabled && <p className="mt-2 text-center text-[11px] text-warn">Gerçek emir kapısı kapalı. Ayarlar'dan etkinleştirin.</p>}
        {message && <p className={`mt-2 text-center text-[11px] ${message.tone === "gain" ? "text-gain" : "text-loss"}`}>{message.text}</p>}
      </>}
    </Card>
  );
}
