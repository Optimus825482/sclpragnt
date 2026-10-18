"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { call, type Holding } from "../../../lib/tradeApi";
import { SMALL_BALANCE_TRY, filterSmallBalances, fmtPct, fmtPrice, fmtQty, fmtSignedTry, fmtTry } from "../../../lib/tradeUi";
import { applyCommissionPct, commissionPct } from "../../../lib/pnl";
import {
  UncertainOrderError, describeSellFill, floorQty, orderFailureText, postJsonGuarded, uncertainOrderText, type SellFillBody,
} from "../../../binance-tr/orderSafety";
import ConfirmDialog from "./ConfirmDialog";
import ProtectDialog from "./ProtectDialog";
import UncertainOrderNotice from "./UncertainOrderNotice";
import {
  describeOrderLookup, holdingNetPnl, intentId, isDefinitiveReject, minNotionalError, priceAgeInfo, resetIntent, sellIntentKey,
  sellStatusSymbols, type IntentRef, retryWhileGatewayUnavailable } from "./orderIntent";

const CHIPS = [25, 50, 75, 100];

// Grafik modalı ağır (lightweight-charts): yalnız ilk açılışta yüklenir.
const PositionChartModal = dynamic(() => import("../../../binance-tr/BinancePositionChartModal"), { ssr: false });

type Props = {
  holdings: Holding[];
  /** 2026-10-17 (basit arayüz): ilk pozisyon yanıtı gelene kadar true → "elinde coin yok" yanıltmasın. */
  loading?: boolean;
  /** 2026-10-18: satırlar üst bandın canlı verisinden tohumlandı; ayrıntı (free/locked, emirler) henüz yok → satış kapalı. */
  seeded?: boolean;
  liveEnabled: boolean;
  onTraded: () => void;
  showToast: (message: string, type?: "success" | "error" | "info") => void;
};

export default function HoldingsCard({ holdings, loading = false, seeded = false, liveEnabled, onTraded, showToast }: Props) {
  const [target, setTarget] = useState<Holding | null>(null);
  const [chip, setChip] = useState(100);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ text: string; partial: boolean } | null>(null);
  // 2026-10-16 (basit arayüz): client_order_id "emir niyeti" (varlık+oran/miktar) başına BİR kez üretilir; ağ hatasında
  // pencere açık kalır ve tekrar gönderimde AYNI kimlik kullanılır (mükerrer satış olmaz).
  const intent = useRef<IntentRef>({ key: "", id: "" });
  const sendLock = useRef(false);
  // 2026-10-18 (denetim #1): belirsiz emrin ORANI ve MİKTARI da saklanır; pencere yeniden açılınca aynı emir aynı miktarla gider.
  const [uncertain, setUncertain] = useState<{ asset: string; cid: string; chip: number; qty: number; text: string } | null>(null);
  const [lookup, setLookup] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);
  // 2026-10-16 (basit arayüz): onay penceresi açılınca ticker yenilenir; yaşı gösterilir (> 15 sn uyarı).
  const [live, setLive] = useState<{ price: number | null; at: number | null }>({ price: null, at: null });
  const [now, setNow] = useState(() => Date.now());
  const [minNotional, setMinNotional] = useState<{ asset: string; value: number | null } | null>(null);
  const [, setCommTick] = useState(0);
  const [hideSmall, setHideSmall] = useState(true);
  const [chartAsset, setChartAsset] = useState<string | null>(null);
  // Modal, listedeki güncel satırı izler (fiyat/emir değişince eski kopya kalmaz).
  const chartHolding = chartAsset ? holdings.find((h) => h.asset === chartAsset) ?? null : null;
  // Kalkan düğmesi: SL / TP / OCO penceresi; açıkken de güncel satırı (fiyat, bakiye) izler.
  const [protectAsset, setProtectAsset] = useState<string | null>(null);
  const protectHolding = protectAsset ? holdings.find((h) => h.asset === protectAsset) ?? null : null;

  const allCoins = holdings.filter((h) => h.asset !== "TRY" && h.total > 0);
  const coins = filterSmallBalances(allCoins, hideSmall);
  const hiddenCount = allCoins.length - coins.length;
  // Bakiyeden büyük miktar göndermemek için AŞAĞI keser (toFixed yarıya yuvarlardı).
  const uncertainHere = !!uncertain && !!target && uncertain.asset === target.asset;
  const qty = target
    ? (uncertainHere && uncertain ? uncertain.qty : chip === 100 ? target.free : floorQty(target.free * (chip / 100), 8))
    : 0;
  const targetAsset = target?.asset ?? null;
  // 2026-10-17 (basit arayüz): onay penceresi açıkken liste canlı tick/yoklamayla kayar; yedek fiyat listedeki GÜNCEL satırdan
  // alınır (target açıldığı andaki kopyadır). Miktar (qty) bilerek açılış kopyasından gelir: belirsiz emirde aynı kimlik/aynı miktar.
  const currentTarget = target ? holdings.find((h) => h.asset === target.asset) ?? target : null;
  const livePrice = live.price ?? currentTarget?.price_try ?? null;
  const age = priceAgeInfo(live.price != null ? live.at : null, now);
  const targetMin = targetAsset && minNotional?.asset === targetAsset ? minNotional.value : null;
  const notionalErr = livePrice ? minNotionalError(qty * livePrice, targetMin) : null;
  const sellNet = target ? holdingNetPnl(target.avg_cost_try, livePrice, qty) : null;

  // Komisyon oranı tek kaynaktan (/api/config); portföy bandı bu sayfada bağlı olmayabilir.
  useEffect(() => {
    let alive = true;
    call<{ commission_pct?: number }>("GET", "/api/config").then((r) => {
      if (!alive || !r.ok) return;
      applyCommissionPct(r.body.commission_pct);
      setCommTick((n) => n + 1);
    });
    return () => { alive = false; };
  }, []);

  // Onay penceresi açıkken: ticker'ı hemen ve 5 sn'de bir yenile, yaşı saniyede bir güncelle; min emir tutarını bir kez al.
  useEffect(() => {
    if (!targetAsset) return;
    let alive = true;
    setLive({ price: null, at: null });
    const refresh = async () => {
      const r = await call<{ tickers?: { available?: boolean; last?: number | null }[] }>("GET", `/api/market-tickers?symbols=${targetAsset}TRY`);
      if (!alive || !r.ok) return;
      const last = Number(r.body.tickers?.[0]?.last);
      if (r.body.tickers?.[0]?.available && Number.isFinite(last) && last > 0) setLive({ price: last, at: Date.now() });
    };
    refresh();
    const t1 = setInterval(refresh, 5000);
    const t2 = setInterval(() => setNow(Date.now()), 1000);
    setNow(Date.now());
    call<{ min_notional?: number | null }>("GET", `/api/binance/symbol-info?symbol=${targetAsset}TRY`).then((r) => {
      if (!alive) return;
      const v = r.ok ? Number(r.body.min_notional) : NaN;
      setMinNotional({ asset: targetAsset, value: Number.isFinite(v) && v > 0 ? v : null });
    });
    return () => { alive = false; clearInterval(t1); clearInterval(t2); };
  }, [targetAsset]);

  const sell = async () => {
    if (!target || sending || sendLock.current) return;
    if (notionalErr) { setError(notionalErr); return; }
    sendLock.current = true;
    setSending(true);
    setError("");
    const asset = target.asset;
    const cid = intentId(intent.current, sellIntentKey(asset, chip, chip === 100 ? 0 : qty));
    try {
      const r = await postJsonGuarded<SellFillBody & { ok?: boolean; status?: string; detail?: unknown }>("/api/binance/sell", {
        asset,
        quantity: chip === 100 ? null : qty,
        confirmation: "REAL_SELL",
        client_order_id: cid,
      });
      const detail = typeof r.body.detail === "string" ? r.body.detail : "";
      // 202: emir daha önce gönderilmiş / sonucu belirsiz. Aynı kimlikle tekrar denenmez; reddedilmişse yeni kimlik.
      if (r.status === 202) {
        if (r.body.status === "failed") {
          resetIntent(intent.current);
          setUncertain(null);
          setError(detail || "Bu emir borsa tarafından reddedilmişti; yeniden deneyebilirsin.");
          setTarget(null);
        } else {
          setUncertain({ asset, cid, chip, qty, text: detail || "Bu emir daha önce gönderildi ve sonucu henüz belli değil. Tekrar göndermeyin." });
          setLookup("");
          onTraded();
        }
        return;
      }
      if (!r.ok || r.body.ok === false) {
        const text = orderFailureText("sell", r.status, detail);
        // 5xx'te emir borsaya ulaşmış olabilir → aynı kimlik korunur (tekrar gönderim sunucuda yinelenen istek olarak ele alınır).
        if (r.status < 500 && isDefinitiveReject(r.status, detail)) {
          resetIntent(intent.current);
          setUncertain(null);
          setError(text);
          setTarget(null);
        } else {
          setUncertain({ asset, cid, chip, qty, text });
          setLookup("");
          onTraded();
        }
        return;
      }
      resetIntent(intent.current);
      setUncertain(null);
      // Gerçek dolum (miktar / ortalama fiyat / kısmi dolum): ekrandaki eski fiyat varsayılmaz.
      const fill = describeSellFill(r.body, qty, livePrice);
      const filled = `${fmtQty(fill.qty)} ${asset}${fill.price ? ` ort. ${fmtPrice(fill.price)} ₺` : ""}`;
      setDone(
        fill.partial
          ? { text: `${asset} satışı KISMİ doldu: ${filled} satıldı${fill.remaining ? `, kalan ${fmtQty(fill.remaining)} ${asset}` : ""}. Kalan için tekrar sat.`, partial: true }
          : { text: `${asset} satıldı: ${filled}${fill.dust ? " (çok küçük toz bakiye kaldı)" : ""}.`, partial: false },
      );
      setTarget(null);
      onTraded();
    } catch (e) {
      if (e instanceof UncertainOrderError) {
        setUncertain({ asset, cid, chip, qty, text: uncertainOrderText("sell", e.timedOut) });
        setLookup("");
        onTraded();
      } else {
        setError("Satış emri gönderilemedi");
        setTarget(null);
      }
    } finally {
      sendLock.current = false;
      setSending(false);
    }
  };

  const queryOrderStatus = async () => {
    if (!uncertain || lookupBusy) return;
    setLookupBusy(true);
    let last: Awaited<ReturnType<typeof call<Record<string, unknown>>>> | null = null;
    for (const symbol of sellStatusSymbols(uncertain.asset)) {
      // 2026-10-17 (basit arayüz): ağ geçidi "meşgul/başlatılıyor" dönerse 3 kez (4 sn ara) yeniden dene.
      const r = await retryWhileGatewayUnavailable(() =>
        call<Record<string, unknown>>("GET", `/api/binance/order-status?symbol=${symbol}&client_id=${encodeURIComponent(uncertain.cid)}`));
      last = r;
      const found = r.ok && Object.keys(((r.body as { order?: object }).order ?? {})).length > 0;
      if (found) break;
    }
    setLookupBusy(false);
    setLookup(last ? describeOrderLookup(last) : "Sorgulanacak sembol bulunamadı.");
    onTraded();
  };

  return (
    <section className="card space-y-3 p-4" aria-labelledby="sat-baslik">
      <div>
        <h2 id="sat-baslik" className="text-lg font-bold text-white">Elindekiler ve Sat</h2>
        <p className="text-sm text-bunker-muted">Satmak istediğin coinin yanındaki düğmeye dokun.</p>
      </div>
      <label className="flex min-h-[44px] items-center gap-2 text-sm text-white">
        <input type="checkbox" checked={hideSmall} onChange={(e) => setHideSmall(e.target.checked)} className="h-5 w-5" />
        {SMALL_BALANCE_TRY} TL’den düşük bakiyeleri gizle{hideSmall && hiddenCount > 0 ? ` (${hiddenCount} gizli)` : ""}
      </label>
      {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
      {done && <p role="status" className={`text-sm ${done.partial ? "text-yellow-300" : "text-neon-green"}`}>{done.text}</p>}
      {uncertain && !target && (
        <UncertainOrderNotice text={uncertain.text} lookup={lookup} lookupBusy={lookupBusy} onLookup={queryOrderStatus} onDismiss={() => { setUncertain(null); setLookup(""); }} />
      )}
      {coins.length === 0 && (
        <p className="text-sm text-bunker-muted" aria-live="polite">
          {loading ? "Varlıkların yükleniyor…" : hiddenCount > 0 ? "Gösterilecek bakiye yok; küçük bakiyeler gizli." : "Şu an elinde coin yok."}
        </p>
      )}
      <ul className="divide-y divide-bunker-800">
        {coins.map((h) => (
          <li key={h.asset} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="flex min-w-0 items-start gap-2">
              <button
                type="button" onClick={() => setChartAsset(h.asset)}
                aria-label={`${h.asset} grafiğini aç`} title="Grafiği aç; zarar durdur / kâr al çizgilerini fareyle ayarla"
                className="ui-button-secondary flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border text-lg"
              >
                📈
              </button>
              <button
                type="button" onClick={() => setProtectAsset(h.asset)} disabled={!liveEnabled || h.value_try == null}
                aria-label={`${h.asset} için zarar durdur / kâr al ekle`} title="Zarar durdur, kâr al ya da ikisini (OCO) yüzdeyle ekle"
                className="ui-button-secondary flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border text-lg disabled:opacity-40"
              >
                🛡
              </button>
              <div className="min-w-0">
              <p className="font-semibold text-white">{h.asset} <span className="font-normal text-bunker-muted">· {fmtQty(h.total)} adet</span></p>
              <p className="text-sm text-white">
                {h.value_try == null ? <span className="text-yellow-300" title="Bu coin için TL veya USDT fiyatı alınamadı">fiyat alınamadı</span> : fmtTry(h.value_try)}
                {(() => {
                  // 2026-10-16 (basit arayüz): sunucu K/Z'si brüt; burada anlık fiyatla NET (gidiş-dönüş komisyonlu) gösterilir.
                  const net = holdingNetPnl(h.avg_cost_try, h.price_try, h.total);
                  if (!net) {
                    // 2026-10-17 (basit arayüz): sessizce boş bırakma — neden K/Z yok, söyle.
                    if (h.value_try == null || h.asset === "USDT") return null;
                    return <span className="ml-2 text-xs text-bunker-muted" title="Alış geçmişi bulunamadığı için giriş fiyatı bilinmiyor">maliyet bilinmiyor</span>;
                  }
                  return (
                    <span className={net.tryValue >= 0 ? "ml-2 text-neon-green" : "ml-2 text-neon-red"} title={`Net: alış ve satış komisyonu (%${(commissionPct() * 100).toFixed(2).replace(".", ",")} / işlem) düşülmüş`}>
                      {fmtSignedTry(net.tryValue)} ({fmtPct(net.pct, 1)}) net
                    </span>
                  );
                })()}
              </p>
              {h.has_active_order && <p className="text-xs text-bunker-muted">Koruma emri var; satmadan önce açık emirlerden iptal et.</p>}
              {!h.has_active_order && h.free <= 0 && <p className="text-xs text-bunker-muted">Bakiyenin tamamı emirde kilitli; satmak için önce Bekleyen emirler’den iptal et.</p>}
              </div>
            </div>
            <button
              type="button" disabled={!liveEnabled || h.free <= 0}
              onClick={() => { setTarget(h); setChip(uncertain && uncertain.asset === h.asset ? uncertain.chip : 100); setDone(null); setError(""); setLookup(""); }}
              className="min-h-[48px] rounded-lg bg-neon-red px-5 text-sm font-bold text-white disabled:opacity-40"
            >
              Sat
            </button>
          </li>
        ))}
      </ul>
      {seeded && coins.length > 0 && <p className="text-xs text-bunker-muted" aria-live="polite">Bakiye ayrıntıları yükleniyor; satış birazdan açılır.</p>}
      {!seeded && !liveEnabled && coins.length > 0 && <p className="text-xs text-bunker-muted">Satmak için canlı işlemi aç.</p>}

      {protectHolding && (
        <ProtectDialog holding={protectHolding} liveEnabled={liveEnabled} onClose={() => setProtectAsset(null)} onTraded={onTraded} showToast={showToast} />
      )}
      {chartHolding && (
        <PositionChartModal
          holding={chartHolding}
          livePrice={chartHolding.price_try}
          sellEnabled={liveEnabled}
          confirmBeforeSend
          showToast={showToast}
          onClose={() => setChartAsset(null)}
          onOrderUpdated={onTraded}
        />
      )}

      <ConfirmDialog
        open={!!target} title={`${target?.asset ?? ""} sat`} confirmLabel={uncertainHere ? "Aynı emri tekrar gönder" : "Evet, sat"} danger busy={sending}
        disabled={qty <= 0 || !!notionalErr} onConfirm={sell} onClose={() => setTarget(null)}
      >
        {target && (
          <>
            <div className="flex gap-2" role="group" aria-label="Satılacak oran">
              {CHIPS.map((c) => (
                <button
                  key={c} type="button" aria-pressed={chip === c} disabled={uncertainHere || sending} onClick={() => setChip(c)}
                  className={`min-h-[48px] flex-1 rounded-lg border text-sm font-semibold disabled:opacity-60 ${chip === c ? "ui-button-primary" : "ui-button-secondary"}`}
                >
                  %{c}
                </button>
              ))}
            </div>
            {uncertainHere && <p className="text-xs text-bunker-muted">Önceki satışın durumu belirsiz olduğu için oran kilitli; aynı emir kimliğiyle tekrar gönderilir.</p>}
            <p>
              Satılacak: <strong>{fmtQty(qty)} {target.asset}</strong>
              {livePrice ? <> (yaklaşık {fmtTry(qty * livePrice)}, fiyat {fmtPrice(livePrice)})</> : null}
            </p>
            <p className={age.stale ? "text-xs font-semibold text-yellow-300" : "text-xs text-bunker-muted"}>
              Fiyat {age.text}{age.stale ? " — 15 sn’den eski olabilir; gerçekleşen fiyat farklı olabilir." : "."}
            </p>
            {sellNet ? (
              <p className={sellNet.tryValue >= 0 ? "text-neon-green" : "text-neon-red"}>
                Tahmini net sonuç: <strong>{fmtSignedTry(sellNet.tryValue)} ({fmtPct(sellNet.pct, 1)})</strong>
                <span className="text-bunker-muted"> · komisyon dahil (net)</span>
              </p>
            ) : (
              <p className="text-xs text-bunker-muted">Maliyet bilgisi olmadığı için net sonuç hesaplanamadı.</p>
            )}
            {notionalErr && <p role="alert" className="text-neon-red">{notionalErr}</p>}
            {!notionalErr && targetMin == null && minNotional?.asset === target.asset && (
              <p className="text-xs text-bunker-muted">Borsanın minimum emir tutarı alınamadı; kontrol satış sırasında borsada yapılır.</p>
            )}
            {uncertainHere && uncertain && <UncertainOrderNotice text={uncertain.text} lookup={lookup} lookupBusy={lookupBusy} onLookup={queryOrderStatus} />}
            <p className="text-bunker-muted">Piyasa fiyatından hemen satılır. Bu işlem gerçek paranla yapılır ve geri alınamaz.</p>
          </>
        )}
      </ConfirmDialog>
    </section>
  );
}
