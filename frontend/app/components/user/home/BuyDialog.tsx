"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { call, type RiskSettings, type TradePlanResponse } from "../../../lib/tradeApi";
import {
  AMOUNT_CHIPS, describeOpenResult, errorText, fmtPct, fmtPrice, fmtQty, fmtTry, hasBlockingWarnings,
  normalizeSymbol, parseTrNumber, rrLabel, scenarioTexts, type OpenResult,
} from "../../../lib/tradeUi";
import { useModalA11y } from "../../../lib/useModalA11y";
import { UncertainOrderError, orderFailureText, postJsonGuarded, uncertainOrderText } from "../../../binance-tr/orderSafety";
import UncertainOrderNotice from "../binance/UncertainOrderNotice";
import { buyIntentKey, describeOrderLookup, intentId, isDefinitiveReject, resetIntent, retryWhileGatewayUnavailable, type IntentRef } from "../binance/orderIntent";
import {
  SL_PCT_CHIPS, TP_PCT_CHIPS, checkSlTp, pctFromPrice, priceAtPct, pricesFromPlan, rrFromPrices, slPctFromPrice,
} from "./buyDialogMath";

type Props = {
  open: boolean;
  /** Tam işlem çifti, örn. "STRAXTRY" (normalizeSymbol hem "STRAX" hem "STRAXTRY" kabul eder). */
  symbol: string;
  /** Bildirimdeki fiyat (yalnız bilgi amaçlı gösterilir). */
  referencePrice?: number | null;
  onClose: () => void;
  onTraded?: () => void;
};

type Settings = { configured: boolean; sell_enabled: boolean };
type AmountMode = { kind: "chip"; chip: number } | { kind: "custom"; text: string };
// Onay ayrı adım DEĞİL (2026-10-18): "Alım yap" tek basışta piyasa alımı + OCO kurar; plan ekranı onay yüzeyidir.
type Step = "plan" | "done";
type Uncertain = { cid: string; key: string; symbol: string; text: string };

const DEBOUNCE_MS = 400;
const DEFAULT_CHIP = 25;
const toText = (n: number | null | undefined, digits = 8) =>
  n == null || !Number.isFinite(n) ? "" : String(Number(n.toFixed(digits))).replace(".", ",");

export default function BuyDialog({ open, symbol: rawSymbol, referencePrice, onClose, onTraded }: Props) {
  const symbol = normalizeSymbol(rawSymbol);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [loadError, setLoadError] = useState("");
  const [amount, setAmount] = useState<AmountMode>({ kind: "chip", chip: DEFAULT_CHIP });
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
  const [result, setResult] = useState<(OpenResult & { clientOrderId: string }) | null>(null);
  const [protectBusy, setProtectBusy] = useState(false);
  const [uncertain, setUncertain] = useState<Uncertain | null>(null);
  const [lookup, setLookup] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);

  // client_order_id "emir niyeti" (sembol+tutar) başına bir kez üretilir; BuyCard ile aynı mükerrer alım koruması.
  const intent = useRef<IntentRef>({ key: "", id: "" });
  const sendLock = useRef(false);
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const basePrice = useRef(0);
  const latest = useRef({ amount, slText, tpText, manual, maxPct: 0, symbol });
  const maxPct = risk?.max_position_pct ?? 0;
  latest.current = { amount, slText, tpText, manual, maxPct, symbol };

  const close = useCallback(() => { if (!sendLock.current) onClose(); }, [onClose]);
  const a11y = useModalA11y(open, close, `${symbol || "Coin"} alım penceresi`);

  const runPlan = useCallback(async () => {
    const cur = latest.current;
    if (!cur.symbol || cur.maxPct <= 0) return;
    const body: Record<string, unknown> = { symbol: cur.symbol };
    if (cur.amount.kind === "custom") {
      const n = parseTrNumber(cur.amount.text);
      if (n == null || n <= 0) { setFieldError("Tutarı TL olarak yaz (örn. 250)."); setDirty(true); return; }
      body.amount_try = n;
    } else {
      body.amount_pct = (cur.maxPct * cur.amount.chip) / 100;
    }
    if (cur.manual) {
      const chk = checkSlTp(basePrice.current, parseTrNumber(cur.slText), parseTrNumber(cur.tpText));
      if (!chk.ok) { setFieldError(chk.error); setDirty(true); return; }
      Object.assign(body, { rr_mode: "manual", rr: chk.rr, sl_pct: chk.slPct });
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
    setDirty(true);
    timer.current = setTimeout(() => { void runPlan(); }, delay);
  }, [runPlan]);

  // Açılışta: ayarlar + risk yükle, ardından ilk planı (Risk Merkezi limitinin %25'i) hazırla.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    seq.current += 1;
    if (timer.current) clearTimeout(timer.current);
    setSettings(null); setRisk(null); setLoadError(""); setPlan(null); setError(""); setFieldError("");
    setAmount({ kind: "chip", chip: DEFAULT_CHIP }); setSlText(""); setTpText(""); setManual(false); setDirty(false);
    setStep("plan"); setResult(null); setLookup("");
    basePrice.current = 0;
    setUncertain((u) => (u && u.symbol === symbol ? u : null));
    (async () => {
      const [s, k] = await Promise.all([
        call<Settings>("GET", "/api/binance/settings"),
        call<RiskSettings>("GET", "/api/binance/risk"),
      ]);
      if (cancelled) return;
      if (!s.ok) { setLoadError(errorText(s.error, "Ayarlar yüklenemedi")); return; }
      setSettings({ configured: !!s.body.configured, sell_enabled: !!s.body.sell_enabled });
      if (!k.ok) { setLoadError(errorText(k.error, "Risk Merkezi ayarları yüklenemedi")); return; }
      const rk = { max_position_pct: k.body.max_position_pct, default_rr: k.body.default_rr };
      setRisk(rk);
      if (!s.body.configured || !symbol) return;
      if (!(rk.max_position_pct > 0)) { setError("Risk Merkezi’nde en yüksek pozisyon yüzdesi tanımlı değil."); return; }
      latest.current = { ...latest.current, maxPct: rk.max_position_pct, manual: false, amount: { kind: "chip", chip: DEFAULT_CHIP }, symbol };
      void runPlan();
    })();
    return () => { cancelled = true; if (timer.current) clearTimeout(timer.current); };
  }, [open, symbol, runPlan]);

  if (!open) return null;

  const customAmount = amount.kind === "custom" ? parseTrNumber(amount.text) : null;
  const slNum = parseTrNumber(slText);
  const tpNum = parseTrNumber(tpText);
  const derivedSlPct = plan ? slPctFromPrice(basePrice.current, slNum ?? 0) : null;
  const derivedRr = plan ? rrFromPrices(basePrice.current, slNum ?? 0, tpNum ?? 0) : null;
  const scen = plan ? scenarioTexts({ ...plan.plan }) : null;
  const blocked = !!plan && hasBlockingWarnings(plan.warnings);
  const planKey = plan ? buyIntentKey(plan.symbol, plan.amount_try) : "";
  const lockedByUncertain = !!uncertain && uncertain.key !== planKey;
  const live = !!settings?.sell_enabled;
  const planReady = !!plan && !dirty && !planBusy && !fieldError;
  const canConfirm = planReady && live && !blocked && !lockedByUncertain;

  const onAmountChip = (chip: number) => { setAmount({ kind: "chip", chip }); latest.current.amount = { kind: "chip", chip }; schedulePlan(0); };
  const onAmountText = (text: string) => { const a: AmountMode = { kind: "custom", text }; setAmount(a); latest.current.amount = a; schedulePlan(DEBOUNCE_MS); };
  const onSl = (text: string) => { setSlText(text); setManual(true); latest.current = { ...latest.current, slText: text, manual: true }; schedulePlan(DEBOUNCE_MS); };
  const onTp = (text: string) => { setTpText(text); setManual(true); latest.current = { ...latest.current, tpText: text, manual: true }; schedulePlan(DEBOUNCE_MS); };

  // Tek dokunuş SL/TP: güncel fiyattan yüzde → fiyat metni; doğrulama ve plan yenileme elle yazımla aynı yoldan geçer.
  const onSlChip = (pct: number) => { const p = priceAtPct(basePrice.current, -pct); if (p != null) onSl(toText(p)); };
  const onTpChip = (pct: number) => { const p = priceAtPct(basePrice.current, pct); if (p != null) onTp(toText(p)); };
  const slChipPct = pctFromPrice(basePrice.current, slNum);
  const tpChipPct = pctFromPrice(basePrice.current, tpNum);
  const chipCls = (on: boolean) =>
    `min-h-[44px] flex-1 rounded-lg border px-2 text-sm font-semibold ${on ? "ui-button-primary" : "ui-button-secondary"}`;

  const confirmBuy = async () => {
    if (!plan || !canConfirm || sending || sendLock.current) return;
    setResult(null);
    sendLock.current = true;
    setSending(true);
    setError("");
    const cid = intentId(intent.current, buyIntentKey(plan.symbol, plan.amount_try));
    try {
      const r = await postJsonGuarded<Record<string, unknown> & { detail?: unknown }>("/api/binance/open-position", {
        symbol: plan.symbol,
        amount_try: plan.amount_try,
        sl_pct: plan.plan.sl_pct,
        rr: plan.plan.rr,
        client_order_id: cid,
        confirmation: "REAL_OPEN",
      });
      if (r.status === 202) {
        // Sonucu belirsiz / işleniyor: AYNI kimlik korunur (yeni kimlik mükerrer alım demektir).
        setUncertain(null);
        setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: cid });
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
          setStep("plan");
        } else {
          // 408/504/gövdesiz 5xx: emir borsaya ulaşmış olabilir → onay adımı açık, aynı kimlik, sorgulama önerilir.
          setUncertain({ cid, key: intent.current.key, symbol: plan.symbol, text });
          setLookup("");
          onTraded?.();
        }
        return;
      }
      resetIntent(intent.current);
      setUncertain(null);
      setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: cid });
      setStep("done");
      onTraded?.();
    } catch (e) {
      if (e instanceof UncertainOrderError) {
        setUncertain({ cid, key: intent.current.key, symbol: plan.symbol, text: uncertainOrderText("buy", e.timedOut) });
        setLookup("");
        onTraded?.();
      } else {
        setError("Alım emri gönderilemedi");
        setStep("plan");
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
    setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: result.clientOrderId });
    onTraded?.();
  };

  const loading = !settings && !loadError;
  const notConfigured = !!settings && !settings.configured;
  const coin = symbol.replace(/TRY$/, "") || "Coin";
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
            {!live && <p className="text-sm text-yellow-300">Canlı işlem kapalı; plan görebilirsin ama alım yapılamaz. <Link href="/binance-tr" className="underline">Binance TR sayfasındaki Bağlantı bölümünden</Link> aç.</p>}

            <div className="text-sm text-white">
              <span id="bd-tutar">Tutar</span>
              <div className="mt-1 flex flex-wrap gap-2" role="group" aria-labelledby="bd-tutar">
                {AMOUNT_CHIPS.map((c) => (
                  <button
                    key={c} type="button" aria-pressed={amount.kind === "chip" && amount.chip === c} onClick={() => onAmountChip(c)}
                    className={`min-h-[48px] flex-1 rounded-lg border px-3 text-sm font-semibold ${amount.kind === "chip" && amount.chip === c ? "ui-button-primary" : "ui-button-secondary"}`}
                  >
                    {c === 100 ? "Limit" : `%${c}`}
                  </button>
                ))}
                <input
                  type="text" inputMode="decimal" placeholder="₺ yaz" aria-label="Tutar (TL)"
                  value={amount.kind === "custom" ? amount.text : ""} onChange={(e) => onAmountText(e.target.value)}
                  className="input min-h-[48px] w-24 rounded-lg border px-2 text-base"
                />
              </div>
              <span className="mt-1 block text-xs text-bunker-muted">
                Limit = Risk Merkezi’ndeki en yüksek tutar{risk ? ` (bakiyenin %${risk.max_position_pct}’i)` : ""}. Yüzdeler bu limitin parçasıdır.
                {amount.kind === "custom" && customAmount == null && amount.text.trim() ? " Geçerli bir tutar yaz." : ""}
              </span>
            </div>

            {planBusy && !plan && <p className="text-sm text-bunker-muted" aria-live="polite">Plan hazırlanıyor…</p>}

            {plan && (
              <div className="space-y-3" aria-live="polite">
                <p className="text-sm text-bunker-muted">Risk Merkezi ayarlarına ve coinin anlık durumuna göre önerilen plan</p>
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
                {fieldError && <p role="alert" className="text-sm text-neon-red">{fieldError}</p>}

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
                <p className="text-xs text-bunker-muted">{plan.disclaimer} Komisyon dahil tahmindir; emir anındaki canlı fiyata göre kurulur, gerçekleşen sonuç farklı olabilir.</p>
              </div>
            )}

            {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
            {uncertain && (
              <UncertainOrderNotice text={uncertain.text} lookup={lookup} lookupBusy={lookupBusy} onLookup={queryOrderStatus} onDismiss={() => { setUncertain(null); setLookup(""); }} />
            )}
            {lockedByUncertain && <p className="text-sm text-yellow-300">Önceki alımın durumu belirsiz. Önce “Durumu sorgula” ile kontrol et ya da bildirimi kapat.</p>}

            {plan && live && (
              <p className="text-xs font-semibold text-yellow-300">
                “Alım yap” gerçek paranla {fmtTry(plan.amount_try)} piyasa alımı yapar; dolunca zarar durdur {fmtPrice(plan.plan.sl_price)} ve kâr al {fmtPrice(plan.plan.tp_price)} OCO emri otomatik kurulur. Geri alınamaz.
              </p>
            )}
            <div className="flex gap-2">
              <button type="button" onClick={close} disabled={sending} className="ui-button-secondary min-h-[48px] flex-1 rounded-lg border px-4 text-sm font-medium disabled:opacity-50">Vazgeç</button>
              <button type="button" onClick={confirmBuy} disabled={!canConfirm || sending} className="ui-button-primary min-h-[48px] flex-[2] rounded-lg px-4 text-sm font-bold disabled:opacity-50">
                {sending ? "Gönderiliyor…" : uncertain ? "Aynı emri tekrar gönder" : plan ? `Alım yap · ${fmtTry(plan.amount_try)}` : "Alım yap"}
              </button>
            </div>
          </>
        )}

        {step === "done" && result && (
          <div className="space-y-3">
            <div className={`card u-card-${result.tone} p-3`} role="status">
              <p className="font-semibold text-white">{result.title}</p>
              {result.detail && <p className="mt-1 text-sm text-white">{result.detail}</p>}
              {result.needsProtect && (
                <button type="button" onClick={retryProtect} disabled={protectBusy} className="ui-button-primary mt-3 min-h-[48px] rounded-lg px-4 text-sm disabled:opacity-50">
                  {protectBusy ? "Deneniyor…" : "Koruma emrini yeniden dene"}
                </button>
              )}
            </div>
            {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
            <button type="button" onClick={onClose} className="ui-button-primary min-h-[48px] w-full rounded-lg px-4 text-sm font-bold">Kapat</button>
          </div>
        )}
      </section>
    </div>
  );
}
