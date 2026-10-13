"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { getJSON, apiRequest, API_BASE } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { formatCompact, formatPct, formatPrice, formatTL } from "../lib/format";
import type { BinancePositions, BinanceSettings, MarketSymbols, MarketTicker } from "../lib/types";
import { Badge, Button, Card } from "./ui";
import SymbolSelect from "./SymbolSelect";

const CONFIRM_BUY = "REAL_BUY";

/**
 * SAĞ PANEL — sembol ara, o anki fiyatı gör, alım emri oluştur.
 *
 * ÖNEMLİ (dürüstlük): Binance TR altyapısında bu panel üzerinden yalnız
 * **MARKET (piyasa) alış** yapılabilir; limit/stop-limit ALIŞ emri backend'de
 * yok (yalnız satış tarafında limit/OCO/stop var). Bu yüzden Limit/Stop-Limit
 * sekmeleri DEVRE DIŞI gösterilir, uydurma davranış yapılmaz.
 *
 * Gerçek işlem yalnız kullanıcı kendi Binance anahtarını girdiyse ve gerçek
 * işlem açıksa yapılır; aksi halde panel bilgilendirir.
 */
export default function OrderPanel({
  initialSymbol,
  onTraded,
}: {
  initialSymbol?: string | null;
  onTraded?: () => void;
}) {
  const symbolsQ = usePoll<MarketSymbols>("/api/market-symbols", 300_000);
  const binance = usePoll<BinanceSettings>("/api/binance/settings", 30_000);

  const [symbol, setSymbol] = useState<string | null>(initialSymbol ?? null);
  const [amountTry, setAmountTry] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "gain" | "loss"; text: string } | null>(null);

  const activeSymbol = symbol || initialSymbol || null;
  const ticker = usePoll<MarketTicker>(activeSymbol ? `/api/market-ticker/${activeSymbol}` : null, 15_000);

  // Kullanıcının TRY bakiyesi (gerçek hesap) — yüzde düğmeleri için.
  const positions = usePoll<BinancePositions>(binance.data?.configured ? "/api/binance/positions" : null, 60_000);
  const tryFree = useMemo(() => {
    const b = positions.data?.balances?.find((x) => x.asset === "TRY");
    return b ? Number(b.free) : null;
  }, [positions.data]);

  const configured = Boolean(binance.data?.configured);
  const sellEnabled = Boolean(binance.data?.sell_enabled);

  const approxBase = useMemo(() => {
    const amt = Number(amountTry);
    const last = ticker.data?.last;
    if (!last || !Number.isFinite(amt) || amt <= 0) return null;
    return amt / last;
  }, [amountTry, ticker.data]);

  const base = activeSymbol ? activeSymbol.replace("TRY", "").replace("USDT", "") : "";

  async function submitBuy() {
    if (!activeSymbol) return;
    const amt = Number(amountTry);
    if (!Number.isFinite(amt) || amt <= 0) {
      setMessage({ tone: "loss", text: "Geçerli bir tutar girin." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/binance/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset: base, amount_try: amt, confirmation: CONFIRM_BUY }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Emir gönderilemedi (${res.status})`);
      setMessage({ tone: "gain", text: `Alım emri gönderildi: ${body.symbol || base} · ${body.order_id || "—"}` });
      setAmountTry("");
      onTraded?.();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Emir gönderilemedi" });
    } finally {
      setBusy(false);
    }
  }

  const t = ticker.data;

  return (
    <Card className="p-4">
      <p className="odak-kicker">İşlem Paneli</p>

      <div className="mt-2">
        <SymbolSelect symbols={symbolsQ.data?.symbols || []} value={activeSymbol} onChange={setSymbol} />
      </div>

      {!activeSymbol ? (
        <p className="mt-4 rounded-lg border border-dashed border-line py-6 text-center text-xs text-ink-400">
          Fiyat ve emir için bir sembol seçin.
        </p>
      ) : (
        <>
          {/* Fiyat + 24s */}
          <div className="mt-3 rounded-xl border border-line p-3">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-xl font-bold text-ink-900">{formatPrice(t?.last)}</span>
              {t?.change_pct != null && (
                <span className={`font-mono text-sm font-semibold ${t.change_pct >= 0 ? "text-gain" : "text-loss"}`}>
                  {t.change_pct >= 0 ? "+" : ""}
                  {formatPct(t.change_pct, 2)}
                </span>
              )}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
              <div>
                <p className="text-ink-400">Hacim (24s)</p>
                <p className="font-mono text-ink-700">{formatCompact(t?.quote_volume)}</p>
              </div>
              <div>
                <p className="text-ink-400">En Düşük</p>
                <p className="font-mono text-ink-700">{formatPrice(t?.low)}</p>
              </div>
              <div>
                <p className="text-ink-400">En Yüksek</p>
                <p className="font-mono text-ink-700">{formatPrice(t?.high)}</p>
              </div>
            </div>
          </div>

          {/* Yön: yalnız AL (bu panel alış odaklı; satış için mevcut panel) */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <span className="rounded-lg bg-gain py-2 text-center text-sm font-semibold text-white">AL</span>
            <Link
              href="/gecmis-islemler"
              className="rounded-lg border border-line py-2 text-center text-sm font-medium text-ink-400 hover:text-ink-900"
              title="Satış yapmıyorsun; geçmiş işlemlerine bak"
            >
              SAT
            </Link>
          </div>

          {/* Emir tipi: yalnız Piyasa destekli */}
          <div className="mt-3">
            <div className="flex gap-1">
              <span className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white">Piyasa</span>
              <span
                className="cursor-not-allowed rounded-lg border border-line px-3 py-1.5 text-xs text-ink-400 opacity-60"
                title="Binance TR entegrasyonunda limit ALIŞ emri desteklenmiyor"
              >
                Limit
              </span>
              <span
                className="cursor-not-allowed rounded-lg border border-line px-3 py-1.5 text-xs text-ink-400 opacity-60"
                title="Binance TR entegrasyonunda stop-limit ALIŞ emri desteklenmiyor"
              >
                Stop-Limit
              </span>
            </div>
            <p className="mt-1.5 text-[10px] text-ink-400">
              Bu panelde yalnız piyasa alışı desteklenir (limit alış backend'de yok).
            </p>
          </div>

          {/* Tutar + yüzdeler */}
          <label className="mt-3 block">
            <span className="odak-kicker">Tutar (₺)</span>
            <input
              value={amountTry}
              onChange={(e) => setAmountTry(e.target.value.replace(/[^\d.]/g, ""))}
              inputMode="decimal"
              placeholder="0"
              className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent"
            />
          </label>
          <div className="mt-2 grid grid-cols-4 gap-1.5">
            {[25, 50, 75, 100].map((pct) => (
              <button
                key={pct}
                type="button"
                disabled={tryFree == null || tryFree <= 0}
                onClick={() => {
                  if (tryFree == null) return;
                  setAmountTry((tryFree * (pct / 100)).toFixed(2));
                }}
                className="rounded-md border border-line py-1 text-[11px] text-ink-500 hover:border-accent hover:text-accent disabled:opacity-40"
              >
                %{pct}
              </button>
            ))}
          </div>

          <div className="mt-2 flex items-center justify-between text-[11px] text-ink-400">
            <span>≈ {approxBase != null ? `${approxBase.toFixed(6)} ${base}` : "—"}</span>
            <span>Kullanılabilir: {tryFree != null ? formatTL(tryFree) : "—"}</span>
          </div>

          {/* Emir butonu */}
          <Button
            variant="success"
            className="mt-3 w-full"
            disabled={!configured || !sellEnabled || busy}
            onClick={submitBuy}
            title={
              !configured
                ? "Önce Ayarlar'dan Binance API anahtarınızı girin"
                : !sellEnabled
                ? "Gerçek işlem kapalı — Ayarlar'dan açın"
                : "Piyasa alış emri oluştur"
            }
          >
            {busy ? "Gönderiliyor…" : "ALIM EMRİ OLUŞTUR"}
          </Button>

          {!configured && (
            <p className="mt-2 text-center text-[11px] text-warn">
              İşlem ve portföy için <Link href="/ayarlar" className="underline">Ayarlar</Link>'dan Binance anahtarı girin.
            </p>
          )}
          {configured && !sellEnabled && (
            <p className="mt-2 text-center text-[11px] text-warn">Gerçek işlem kapalı — Ayarlar'dan açın.</p>
          )}
          {message && (
            <p className={`mt-2 text-center text-[11px] ${message.tone === "gain" ? "text-gain" : "text-loss"}`}>{message.text}</p>
          )}
          {configured && (
            <div className="mt-2 flex justify-center">
              <Badge tone={sellEnabled ? "gain" : "warn"}>{sellEnabled ? "Gerçek işlem açık" : "Gerçek işlem kapalı"}</Badge>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
