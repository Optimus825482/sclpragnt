"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { call, type TradePlanResponse } from "../../../lib/tradeApi";
import {
  describeOpenResult, errorText, fmtPct, fmtPrice, fmtQty, fmtTry, hasBlockingWarnings,
  normalizeSymbol, parseTrNumber, rrLabel, scenarioTexts, type OpenResult,
} from "../../../lib/tradeUi";
import { useModalA11y } from "../../../lib/useModalA11y";
import { useWatchPrices } from "../../../lib/useWatchPrices";
import { UncertainOrderError, orderFailureText, postJsonGuarded, uncertainOrderText } from "../../../binance-tr/orderSafety";
import UncertainOrderNotice from "../binance/UncertainOrderNotice";
import { buyIntentKey, describeOrderLookup, intentId, isDefinitiveReject, resetIntent, retryWhileGatewayUnavailable, type IntentRef } from "../binance/orderIntent";
import {
  BUY_PCT_CHIPS, SL_PCT_CHIPS, TP_PCT_CHIPS, amountFromFree, checkSlTp, describeBuyFill, pctFromPrice, priceAtPct,
  pricesFromPlan, rrFromPrices, slPctFromPrice, checkSlTpPlan, type BuyFillBody,
} from "./buyDialogMath";
import { DEVIATION_WARN_PCT, planDialogDefaults, planSummary, priceDeviationPct, type TradePlan } from "./tradePlan";

type Props = {
  open: boolean;
  /** Tam işlem çifti, örn. "STRAXTRY" (normalizeSymbol hem "STRAX" hem "STRAXTRY" kabul eder). */
  symbol: string;
  /** Bildirimdeki fiyat (yalnız bilgi amaçlı gösterilir). */
  referencePrice?: number | null;
  /** Bildirim işlem planı (yoksa/null: bugünkü plansız davranış). */
  tradePlan?: TradePlan | null;
  /** Planın dondurma anahtarı; alım isteğine `plan_key` olarak eklenir (yalnız plan varken). */
  planKey?: string | null;
  onClose: () => void;
  onTraded?: () => void;
};

type Settings = { configured: boolean; sell_enabled: boolean };
type AmountMode = { kind: "chip"; chip: number } | { kind: "custom"; text: string };
// Onay ayrı adım DEĞİL: "Alım yap" tek basışta emri gönderir; sonuç (dolum) onay penceresi olarak gösterilir.
type Step = "plan" | "done";
type Uncertain = { cid: string; key: string; symbol: string; text: string };
type Balance = { asset: string; free: string | number };

const DEBOUNCE_MS = 400;
const DEFAULT_CHIP = 25;
const toText = (n: number | null | undefined, digits = 8) =>
  n == null || !Number.isFinite(n) ? "" : String(Number(n.toFixed(digits))).replace(".", ",");

/** Tutar: düğme → serbest TRY bakiyesinin yüzdesi; yazılan → TL. Geçersizse 0. */
const amountOf = (a: AmountMode, freeTry: number | null) =>
  a.kind === "chip" ? amountFromFree(freeTry, a.chip) : Math.max(0, parseTrNumber(a.text) ?? 0);

/**
 * Herhangi bir sembolde "Alım yap" penceresi.
 *
 * Tutar serbest TRY bakiyesinin %25/50/100'ü (ya da elle TL). OCO isteğe bağlıdır (varsayılan kapalı):
 *  - kapalı → `/api/binance/buy` düz piyasa alımı; SL/TP sonradan Binance TR sayfasındaki kalkan düğmesiyle eklenir.
 *  - açık   → `/api/binance/open-position`: alım dolunca seçilen SL/TP ile OCO kurulur.
 */
export default function BuyDialog({ open, symbol: rawSymbol, referencePrice, tradePlan, planKey, onClose, onTraded }: Props) {
  const symbol = normalizeSymbol(rawSymbol);
  const coin = symbol.replace(/TRY$/, "") || "Coin";
  const [settings, setSettings] = useState<Settings | null>(null);
  const [freeTry, setFreeTry] = useState<number | null>(null);
  const [loadError, setLoadError] = useState("");
  const [amount, setAmount] = useState<AmountMode>({ kind: "chip", chip: DEFAULT_CHIP });
  const [oco, setOco] = useState(false);
  const [slText, setSlText] = useState("");
  const [tpText, setTpText] = useState("");
  const [manual, setManual] = useState(false);
  const [plan, setPlan] = useState<TradePlanResponse | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [dirty, setDirty] = useState(false); // girdi değişti, ekrandaki plan güncel değil
  const [fieldError, setFieldError] = useState("");
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>("plan");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<(OpenResult & { clientOrderId: string; oco: boolean }) | null>(null);
  const [protectBusy, setProtectBusy] = useState(false);
  const [uncertain, setUncertain] = useState<Uncertain | null>(null);
  const [lookup, setLookup] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);

  // client_order_id "emir niyeti" (sembol+tutar+tür) başına bir kez üretilir; BuyCard ile aynı mükerrer alım koruması.
  const intent = useRef<IntentRef>({ key: "", id: "" });
  const sendLock = useRef(false);
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const basePrice = useRef(0);
  const watched = useWatchPrices(open && tradePlan && symbol ? [symbol] : []);
  const planRef = useRef<TradePlan | null>(null);
  planRef.current = tradePlan ?? null;
  // Plan modunda başlangıç SL/TP yüzdesi (kullanıcı elle değiştirene kadar sunucuya bu gider).
  const planSeed = useRef<{ slPct: number; tpPct: number } | null>(null);
  const latest = useRef({ amount, slText, tpText, manual, freeTry, oco, symbol });
  latest.current = { amount, slText, tpText, manual, freeTry, oco, symbol };

  const close = useCallback(() => { if (!sendLock.current) onClose(); }, [onClose]);
  const a11y = useModalA11y(open, close, `${coin} alım penceresi`);

  // Plan yalnız OCO açıkken gerekir (güncel fiyat + SL/TP önerisi + uyarılar).
  const runPlan = useCallback(async () => {
    const cur = latest.current;
    if (!cur.symbol || !cur.oco) return;
    const amountTry = amountOf(cur.amount, cur.freeTry);
    if (!(amountTry > 0)) { setFieldError("Tutar seç ya da TL olarak yaz (örn. 250)."); setDirty(true); return; }
    const body: Record<string, unknown> = { symbol: cur.symbol, amount_try: amountTry };
    if (cur.manual) {
      if (planRef.current) {
        const chk = checkSlTpPlan(basePrice.current, parseTrNumber(cur.slText), parseTrNumber(cur.tpText));
        if (!chk.ok) { setFieldError(chk.error); setDirty(true); return; }
        Object.assign(body, { rr_mode: "manual", sl_pct: chk.slPct, tp_pct: chk.tpPct });
      } else {
        const chk = checkSlTp(basePrice.current, parseTrNumber(cur.slText), parseTrNumber(cur.tpText));
        if (!chk.ok) { setFieldError(chk.error); setDirty(true); return; }
        Object.assign(body, { rr_mode: "manual", rr: chk.rr, sl_pct: chk.slPct });
      }
    } else if (planRef.current && planSeed.current) {
      Object.assign(body, { rr_mode: "manual", sl_pct: planSeed.current.slPct, tp_pct: planSeed.current.tpPct });
    }
    setFieldError("");
    const my = ++seq.current;
    setPlanBusy(true);
    setError("");
    const r = await call<TradePlanResponse>("POST", "/api/binance/trade-plan", body);
    if (my !== seq.current) return; // daha yeni bir istek var; eski yanıt yenisini ezmez
    setPlanBusy(false);
    if (!r.ok) {
      setPlan(null);
      setError(errorText(r.error));
      return;
    }
    basePrice.current = r.body.price;
    setPlan(r.body);
    setDirty(false);
    if (!cur.manual) {
      const p = pricesFromPlan(r.body.price, r.body.plan);
      setSlText(toText(p.sl));
      setTpText(toText(p.tp));
    }
  }, []);

  const schedulePlan = useCallback((delay: number) => {
    if (timer.current) clearTimeout(timer.current);
    if (!latest.current.oco) return;
    setDirty(true);
    timer.current = setTimeout(() => { void runPlan(); }, delay);
  }, [runPlan]);

  // Açılışta: bağlantı ayarları + serbest TRY bakiyesi.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    seq.current += 1;
    if (timer.current) clearTimeout(timer.current);
    setSettings(null); setFreeTry(null); setLoadError(""); setPlan(null); setError(""); setFieldError("");
    setAmount({ kind: "chip", chip: DEFAULT_CHIP }); setOco(false); setSlText(""); setTpText(""); setManual(false); setDirty(false);
    setStep("plan"); setResult(null); setLookup("");
    basePrice.current = 0;
    planSeed.current = null;
    setUncertain((u) => (u && u.symbol === symbol ? u : null));
    (async () => {
      const [s, a] = await Promise.all([
        call<Settings>("GET", "/api/binance/settings"),
        call<{ balances?: Balance[] }>("GET", "/api/binance/account"),
      ]);
      if (cancelled) return;
      if (!s.ok) { setLoadError(errorText(s.error, "Ayarlar yüklenemedi")); return; }
      setSettings({ configured: !!s.body.configured, sell_enabled: !!s.body.sell_enabled });
      if (!s.body.configured) return;
      if (!a.ok) { setLoadError(errorText(a.error, "Bakiye alınamadı")); return; }
      const tryRow = (a.body.balances || []).find((b) => b.asset === "TRY");
      const free = Number(tryRow?.free ?? 0) || 0;
      setFreeTry(free);
      // Bildirim planı varsa tutar/SL/TP/OCO plandan başlar (kullanıcı hepsini değiştirebilir).
      const tp = planRef.current;
      if (tp) {
        const d = planDialogDefaults(tp, free);
        const amt: AmountMode = d.amountTry > 0 ? { kind: "custom", text: String(d.amountTry) } : { kind: "chip", chip: DEFAULT_CHIP };
        setAmount(amt);
        if (d.oco && d.slPct != null && d.tpPct != null) {
          planSeed.current = { slPct: d.slPct, tpPct: d.tpPct };
          setOco(true);
          latest.current = { ...latest.current, amount: amt, freeTry: free, oco: true, manual: false };
          schedulePlan(0);
        }
      }
    })();
    return () => { cancelled = true; if (timer.current) clearTimeout(timer.current); };
  }, [open, symbol, schedulePlan]);

  if (!open) return null;

  const amountTry = amountOf(amount, freeTry);
  const slNum = parseTrNumber(slText);
  const tpNum = parseTrNumber(tpText);
  const derivedSlPct = plan ? slPctFromPrice(basePrice.current, slNum ?? 0) : null;
  const derivedRr = plan ? rrFromPrices(basePrice.current, slNum ?? 0, tpNum ?? 0) : null;
  const scen = plan ? scenarioTexts({ ...plan.plan }) : null;
  const blocked = oco && !!plan && hasBlockingWarnings(plan.warnings);
  const orderAmount = oco ? plan?.amount_try ?? 0 : amountTry;
  const orderKey = `${buyIntentKey(symbol, orderAmount)}|${oco ? "oco" : "spot"}`;
  const lockedByUncertain = !!uncertain && uncertain.key !== orderKey;
  const live = !!settings?.sell_enabled;
  const overFree = amount.kind === "custom" && freeTry != null && amountTry > freeTry;
  const ready = oco ? !!plan && !dirty && !planBusy && !fieldError : amountTry > 0 && !overFree;
  // Sapma: OCO önizlemesindeki fiyat varsa o, yoksa izleme akışındaki canlı fiyat (OCO kapalıyken de çalışır).
  const livePx = plan?.price ?? watched[symbol] ?? watched[symbol.toUpperCase()];
  const deviation = tradePlan ? priceDeviationPct(tradePlan.entry_ref_price, livePx) : null;
  const planNote = !tradePlan || oco ? null
    : tradePlan.stop_pct == null ? "Planda stop yok — bu alım çıkış hatırlatıcısına bağlanmaz"
    : "OCO kapalı — çıkış hatırlatıcısı bağlanmaz";
  const canBuy = ready && live && !blocked && !lockedByUncertain && !!symbol;

  const setAmountMode = (a: AmountMode, delay: number) => { setAmount(a); latest.current.amount = a; setFieldError(""); schedulePlan(delay); };
  const onAmountChip = (chip: number) => setAmountMode({ kind: "chip", chip }, 0);
  const onAmountText = (text: string) => setAmountMode({ kind: "custom", text }, DEBOUNCE_MS);
  const onOcoToggle = (on: boolean) => {
    setOco(on);
    latest.current.oco = on;
    if (on) { schedulePlan(0); return; }
    seq.current += 1; // uçuştaki plan yanıtı geçersiz
    if (timer.current) clearTimeout(timer.current);
    setPlan(null); setPlanBusy(false); setDirty(false); setFieldError(""); setManual(false); setSlText(""); setTpText("");
  };
  const onSl = (text: string) => { setSlText(text); setManual(true); latest.current = { ...latest.current, slText: text, manual: true }; schedulePlan(DEBOUNCE_MS); };
  const onTp = (text: string) => { setTpText(text); setManual(true); latest.current = { ...latest.current, tpText: text, manual: true }; schedulePlan(DEBOUNCE_MS); };

  // Tek dokunuş SL/TP: güncel fiyattan yüzde → fiyat metni; doğrulama ve plan yenileme elle yazımla aynı yoldan geçer.
  const onSlChip = (pct: number) => { const p = priceAtPct(basePrice.current, -pct); if (p != null) onSl(toText(p)); };
  const onTpChip = (pct: number) => { const p = priceAtPct(basePrice.current, pct); if (p != null) onTp(toText(p)); };
  const slChipPct = pctFromPrice(basePrice.current, slNum);
  const tpChipPct = pctFromPrice(basePrice.current, tpNum);
  const chipCls = (on: boolean) =>
    `min-h-[44px] flex-1 rounded-lg border px-2 text-sm font-semibold ${on ? "ui-button-primary" : "ui-button-secondary"}`;

  const sendOrder = (cid: string) =>
    oco && plan
      ? postJsonGuarded<Record<string, unknown> & { detail?: unknown }>("/api/binance/open-position", {
          symbol: plan.symbol, amount_try: plan.amount_try, sl_pct: plan.plan.sl_pct, rr: plan.plan.rr,
          ...(tradePlan && plan.plan.tp_pct != null ? { tp_pct: plan.plan.tp_pct } : {}),
          ...(tradePlan && planKey ? { plan_key: planKey } : {}),
          client_order_id: cid, confirmation: "REAL_OPEN",
        })
      : postJsonGuarded<BuyFillBody & { detail?: unknown }>("/api/binance/buy", {
          asset: coin, amount_try: amountTry, client_order_id: cid, confirmation: "REAL_BUY",
        });

  const confirmBuy = async () => {
    if (!canBuy || sending || sendLock.current) return;
    setResult(null);
    sendLock.current = true;
    setSending(true);
    setError("");
    const cid = intentId(intent.current, orderKey);
    const describe = (status: number, body: unknown): OpenResult =>
      oco ? describeOpenResult(status, body as never) : describeBuyFill(status, body as BuyFillBody, coin);
    try {
      const r = await sendOrder(cid);
      if (r.status === 202) {
        // Sonucu belirsiz / işleniyor: AYNI kimlik korunur (yeni kimlik mükerrer alım demektir).
        setUncertain(null);
        setResult({ ...describe(r.status, r.body), clientOrderId: cid, oco });
        setStep("done");
        onTraded?.();
        return;
      }
      if (!r.ok) {
        const text = orderFailureText("buy", r.status, r.body.detail);
        if (isDefinitiveReject(r.status, r.body.detail)) {
          resetIntent(intent.current);
          setUncertain(null);
          setError(text);
        } else {
          // 408/504/gövdesiz 5xx: emir borsaya ulaşmış olabilir → aynı kimlik, sorgulama önerilir.
          setUncertain({ cid, key: orderKey, symbol, text });
          setLookup("");
          onTraded?.();
        }
        return;
      }
      resetIntent(intent.current);
      setUncertain(null);
      setResult({ ...describe(r.status, r.body), clientOrderId: cid, oco });
      setStep("done");
      onTraded?.();
    } catch (e) {
      if (e instanceof UncertainOrderError) {
        setUncertain({ cid, key: orderKey, symbol, text: uncertainOrderText("buy", e.timedOut) });
        setLookup("");
        onTraded?.();
      } else {
        setError("Alım emri gönderilemedi");
      }
    } finally {
      sendLock.current = false;
      setSending(false);
    }
  };

  const queryOrderStatus = async () => {
    if (!uncertain || lookupBusy) return;
    setLookupBusy(true);
    const r = await retryWhileGatewayUnavailable(() =>
      call<Record<string, unknown>>("GET", `/api/binance/order-status?symbol=${encodeURIComponent(uncertain.symbol)}&client_id=${encodeURIComponent(uncertain.cid)}`));
    setLookupBusy(false);
    setLookup(describeOrderLookup(r));
    onTraded?.();
  };

  const retryProtect = async () => {
    if (!result || protectBusy) return;
    setProtectBusy(true);
    const r = await call<Record<string, unknown>>("POST", "/api/binance/protect", { client_order_id: result.clientOrderId });
    setProtectBusy(false);
    if (!r.ok) { setError(errorText(r.error)); return; }
    setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: result.clientOrderId, oco: true });
    onTraded?.();
  };

  const loading = !settings && !loadError;
  const notConfigured = !!settings && !settings.configured;
  const inputCls = "input mt-1 block min-h-[48px] w-full rounded-lg border px-3 text-base";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={a11y.label}
      onKeyDown={a11y.onKeyDown}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-3"
      onClick={() => { if (!sending) onClose(); }}
    >
      <section
        ref={a11y.ref}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="card max-h-[92vh] w-full max-w-lg space-y-4 overflow-y-auto rounded-b-none p-5 outline-none sm:rounded-b-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-white">{coin} · Alım yap</h2>
            {referencePrice != null && referencePrice > 0 && (
              <p className="text-xs text-bunker-muted">Bildirim fiyatı {fmtPrice(referencePrice)}</p>
            )}
          </div>
          <button type="button" onClick={close} disabled={sending} aria-label="Kapat" className="ui-button-secondary min-h-[44px] min-w-[44px] rounded-lg border px-3 text-lg disabled:opacity-50">×</button>
        </div>

        {loading && <p className="text-sm text-bunker-muted" aria-live="polite">Hazırlanıyor…</p>}
        {loadError && <p role="alert" className="text-sm text-neon-red">{loadError}</p>}
        {!symbol && <p role="alert" className="text-sm text-neon-red">Coin belirlenemedi.</p>}

        {notConfigured && (
          <p className="text-sm text-white">
            Alım için önce Ayarlar’dan Binance TR anahtarını ekle.{" "}
            <Link href="/settings" className="font-semibold underline">Ayarlar’a git</Link>
          </p>
        )}

        {settings?.configured && step === "plan" && (
          <>
            {!live && <p className="text-sm text-yellow-300">Canlı işlem kapalı; alım yapılamaz. <Link href="/binance-tr" className="underline">Binance TR sayfasındaki Bağlantı bölümünden</Link> aç.</p>}

            {tradePlan && (
              <div className="rounded-lg border border-bunker-700 p-2 text-xs text-bunker-muted" aria-label="İşlem planı">
                <p>{planSummary(tradePlan, Date.now() / 1000)}</p>
                {planNote && <p className="mt-1" role="note">{planNote}</p>}
                {deviation != null && deviation > DEVIATION_WARN_PCT && (
                  <p role="alert" className="mt-1 rounded bg-yellow-900/40 px-2 py-1 text-yellow-300">
                    Fiyat plandaki giriş fiyatından %{deviation.toFixed(1).replace(".", ",")} sapmış ({fmtPrice(tradePlan.entry_ref_price)} → {fmtPrice(livePx)}). Hedef ve stop yüzdeleri değişmedi; fiyatlar dolum fiyatına göre hesaplanır.
                  </p>
                )}
              </div>
            )}

            <div className="text-sm text-white">
              <span id="bd-tutar">Tutar <span className="text-bunker-muted">(serbest bakiye {freeTry == null ? "…" : fmtTry(freeTry)})</span></span>
              <div className="mt-1 flex flex-wrap gap-2" role="group" aria-labelledby="bd-tutar">
                {BUY_PCT_CHIPS.map((c) => (
                  <button
                    key={c} type="button" aria-pressed={amount.kind === "chip" && amount.chip === c} onClick={() => onAmountChip(c)}
                    className={`min-h-[48px] flex-1 rounded-lg border px-3 text-sm font-semibold ${amount.kind === "chip" && amount.chip === c ? "ui-button-primary" : "ui-button-secondary"}`}
                  >
                    %{c}
                  </button>
                ))}
                <input
                  type="text" inputMode="decimal" placeholder="₺ yaz" aria-label="Tutar (TL)"
                  value={amount.kind === "custom" ? amount.text : ""} onChange={(e) => onAmountText(e.target.value)}
                  className="input min-h-[48px] w-24 rounded-lg border px-2 text-base"
                />
              </div>
              <span className="mt-1 block text-xs text-bunker-muted">
                {amountTry > 0 ? `Alım tutarı ${fmtTry(amountTry)}` : freeTry === 0 ? "Serbest TRY bakiyesi yok." : "Tutar seç ya da yaz."}
                {overFree ? " Serbest bakiyeden fazla." : ""}
              </span>
            </div>

            <label className="flex min-h-[48px] items-center gap-3 rounded-lg border border-bunker-700 px-3 text-sm text-white">
              <input type="checkbox" checked={oco} onChange={(e) => onOcoToggle(e.target.checked)} className="h-5 w-5" />
              <span>Alım dolunca zarar durdur / kâr al (OCO) kur</span>
            </label>

            {oco && planBusy && !plan && <p className="text-sm text-bunker-muted" aria-live="polite">Plan hazırlanıyor…</p>}

            {oco && plan && (
              <div className="space-y-3" aria-live="polite">
                <div className="rounded-lg border border-bunker-700 p-3 text-sm text-white">
                  <p className="font-semibold">{plan.symbol} · güncel fiyat {fmtPrice(plan.price)}</p>
                  <p className="mt-1">
                    Alım tutarı <strong>{fmtTry(plan.amount_try)}</strong> · yaklaşık {fmtQty(plan.plan.qty)} adet
                  </p>
                  {plan.suggestion.rationale && !manual && <p className="mt-1 text-bunker-muted">{plan.suggestion.rationale}</p>}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm text-white">
                      Zarar durdur fiyatı (₺)
                      <input type="text" inputMode="decimal" value={slText} onChange={(e) => onSl(e.target.value)} className={inputCls} />
                    </label>
                    <div className="mt-1 flex gap-1" role="group" aria-label="Zarar durdur mesafesi">
                      {SL_PCT_CHIPS.map((c) => (
                        <button key={c} type="button" aria-pressed={slChipPct === -c} onClick={() => onSlChip(c)} className={chipCls(slChipPct === -c)}>-%{c}</button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm text-white">
                      Kâr al fiyatı (₺)
                      <input type="text" inputMode="decimal" value={tpText} onChange={(e) => onTp(e.target.value)} className={inputCls} />
                    </label>
                    <div className="mt-1 flex gap-1" role="group" aria-label="Kâr al mesafesi">
                      {TP_PCT_CHIPS.map((c) => (
                        <button key={c} type="button" aria-pressed={tpChipPct === c} onClick={() => onTpChip(c)} className={chipCls(tpChipPct === c)}>+%{c}</button>
                      ))}
                    </div>
                  </div>
                </div>
                <p className="text-xs text-bunker-muted">
                  {derivedSlPct != null && derivedRr != null
                    ? `${fmtPct(derivedSlPct)} mesafe · ${rrLabel(derivedRr).replace(/ /g, "")} oran`
                    : `${fmtPct(plan.plan.sl_pct)} mesafe · ${rrLabel(plan.plan.rr).replace(/ /g, "")} oran`}
                  {" "}(zarar mesafesi %0,5–10, oran 1:1–1:5 arası olabilir)
                </p>

                {scen && !dirty && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="card u-card-bad p-3"><p className="text-sm font-semibold text-white">Kötü senaryo</p><p className="mt-1 text-sm text-white">{scen.bad}</p></div>
                    <div className="card u-card-good p-3"><p className="text-sm font-semibold text-white">İyi senaryo</p><p className="mt-1 text-sm text-white">{scen.good}</p></div>
                  </div>
                )}
                {dirty && !fieldError && <p className="text-sm text-bunker-muted">Plan güncelleniyor…</p>}

                {plan.warning_texts.length > 0 && (
                  <ul className="space-y-1" role="alert">
                    {plan.warning_texts.map((w) => (<li key={w} className="text-sm text-neon-red">• {w}</li>))}
                  </ul>
                )}
              </div>
            )}
            {oco && fieldError && <p role="alert" className="text-sm text-neon-red">{fieldError}</p>}

            {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
            {uncertain && (
              <UncertainOrderNotice text={uncertain.text} lookup={lookup} lookupBusy={lookupBusy} onLookup={queryOrderStatus} onDismiss={() => { setUncertain(null); setLookup(""); }} />
            )}
            {lockedByUncertain && <p className="text-sm text-yellow-300">Önceki alımın durumu belirsiz. Önce “Durumu sorgula” ile kontrol et ya da bildirimi kapat.</p>}

            {live && orderAmount > 0 && (
              <p className="text-xs font-semibold text-yellow-300">
                “Alım yap” gerçek paranla {fmtTry(orderAmount)} piyasa alımı yapar
                {oco && plan ? `; dolunca zarar durdur ${fmtPrice(plan.plan.sl_price)} ve kâr al ${fmtPrice(plan.plan.tp_price)} OCO emri kurulur` : ""}. Geri alınamaz.
              </p>
            )}
            <div className="flex gap-2">
              <button type="button" onClick={close} disabled={sending} className="ui-button-secondary min-h-[48px] flex-1 rounded-lg border px-4 text-sm font-medium disabled:opacity-50">Vazgeç</button>
              <button type="button" onClick={confirmBuy} disabled={!canBuy || sending} className="ui-button-primary min-h-[48px] flex-[2] rounded-lg px-4 text-sm font-bold disabled:opacity-50">
                {sending ? "Gönderiliyor…" : uncertain ? "Aynı emri tekrar gönder" : orderAmount > 0 ? `Alım yap · ${fmtTry(orderAmount)}` : "Alım yap"}
              </button>
            </div>
          </>
        )}

        {step === "done" && result && (
          <div className="space-y-3" role="alertdialog" aria-label={result.title}>
            <div className={`card u-card-${result.tone} p-3`} role="status">
              <p className="font-semibold text-white">{result.title}</p>
              {result.detail && <p className="mt-1 text-sm text-white">{result.detail}</p>}
              {result.needsProtect && (
                <button type="button" onClick={retryProtect} disabled={protectBusy} className="ui-button-primary mt-3 min-h-[48px] rounded-lg px-4 text-sm disabled:opacity-50">
                  {protectBusy ? "Deneniyor…" : "Koruma emrini yeniden dene"}
                </button>
              )}
            </div>
            {!result.oco && !result.pending && (
              <p className="text-sm text-bunker-muted">Zarar durdur / kâr al eklemek için Binance TR sayfasında {coin} satırındaki kalkan (🛡) düğmesine bas.</p>
            )}
            {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
            <div className="flex gap-2">
              <Link href="/binance-tr" onClick={onClose} className="ui-button-secondary flex min-h-[48px] flex-1 items-center justify-center rounded-lg border px-4 text-sm font-semibold">Binance TR’de izle</Link>
              <button type="button" onClick={onClose} className="ui-button-primary min-h-[48px] flex-1 rounded-lg px-4 text-sm font-bold">Tamam</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
