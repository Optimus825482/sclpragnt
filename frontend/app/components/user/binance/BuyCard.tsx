"use client";
import { useRef, useState } from "react";
import { call, type TradePlanResponse } from "../../../lib/tradeApi";
import {
  AMOUNT_CHIPS, describeOpenResult, errorText, fmtPrice, fmtPct, fmtQty, fmtTry, hasBlockingWarnings,
  newClientOrderId, normalizeSymbol, parseTrNumber, rrLabel, scenarioTexts, suggestionSourceLabel,
  type OpenResult,
} from "../../../lib/tradeUi";
import ConfirmDialog from "./ConfirmDialog";

type Props = {
  liveEnabled: boolean;
  configured: boolean;
  maxPositionPct: number;
  onTraded: () => void;
};

type AmountMode = { kind: "chip"; chip: number } | { kind: "custom"; text: string };

export default function BuyCard({ liveEnabled, configured, maxPositionPct, onTraded }: Props) {
  const [query, setQuery] = useState("");
  const [amount, setAmount] = useState<AmountMode>({ kind: "chip", chip: 25 });
  const [manual, setManual] = useState(false);
  const [rrText, setRrText] = useState("");
  const [slText, setSlText] = useState("");
  const [plan, setPlan] = useState<TradePlanResponse | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<(OpenResult & { clientOrderId: string }) | null>(null);
  const [protectBusy, setProtectBusy] = useState(false);
  const clientId = useRef("");

  const invalidate = () => {
    setPlan(null);
    setResult(null);
    setError("");
  };

  const symbol = normalizeSymbol(query);
  const customAmount = amount.kind === "custom" ? parseTrNumber(amount.text) : null;
  const amountOk = amount.kind === "chip" || (customAmount != null && customAmount > 0);
  const manualRr = parseTrNumber(rrText);
  const manualSl = parseTrNumber(slText);
  const manualOk = !manual || (manualRr != null && manualRr >= 1 && manualRr <= 5 && manualSl != null && manualSl >= 0.5 && manualSl <= 10);
  const canPlan = configured && !!symbol && amountOk && manualOk && !planBusy;

  const buildPlan = async () => {
    if (!canPlan) return;
    setPlanBusy(true);
    setError("");
    setResult(null);
    const body: Record<string, unknown> = { symbol };
    if (amount.kind === "custom") body.amount_try = customAmount;
    else body.amount_pct = (maxPositionPct * amount.chip) / 100;
    if (manual) Object.assign(body, { rr_mode: "manual", rr: manualRr, sl_pct: manualSl });
    const r = await call<TradePlanResponse>("POST", "/api/binance/trade-plan", body);
    setPlanBusy(false);
    if (!r.ok) {
      setPlan(null);
      setError(errorText(r.error));
      return;
    }
    setPlan(r.body);
    if (!manual) {
      setRrText(String(r.body.suggestion.rr).replace(".", ","));
      setSlText(String(r.body.suggestion.sl_pct).replace(".", ","));
    }
  };

  const openConfirm = () => {
    clientId.current = newClientOrderId();
    setResult(null);
    setConfirmOpen(true);
  };

  const confirmBuy = async () => {
    if (!plan || sending) return;
    setSending(true);
    const r = await call<Record<string, unknown>>("POST", "/api/binance/open-position", {
      symbol: plan.symbol,
      amount_try: plan.amount_try,
      sl_pct: plan.plan.sl_pct,
      rr: plan.plan.rr,
      client_order_id: clientId.current,
      confirmation: "REAL_OPEN",
    });
    setSending(false);
    setConfirmOpen(false);
    if (!r.ok && r.status !== 202) {
      setError(errorText(r.error));
      return;
    }
    setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: clientId.current });
    onTraded();
  };

  const retryProtect = async () => {
    if (!result || protectBusy) return;
    setProtectBusy(true);
    const r = await call<Record<string, unknown>>("POST", "/api/binance/protect", { client_order_id: result.clientOrderId });
    setProtectBusy(false);
    if (!r.ok) {
      setError(errorText(r.error));
      return;
    }
    setResult({ ...describeOpenResult(r.status, r.body as never), clientOrderId: result.clientOrderId });
    onTraded();
  };

  const scen = plan ? scenarioTexts({ ...plan.plan }) : null;
  const blocked = !!plan && hasBlockingWarnings(plan.warnings);

  return (
    <section className="card space-y-4 p-4" aria-labelledby="al-baslik">
      <div>
        <h2 id="al-baslik" className="text-lg font-bold text-white">Al</h2>
        <p className="text-sm text-bunker-muted">Coin seç, planı gör, onayla. Alımdan sonra zarar durdur ve kâr al emirleri otomatik kurulur.</p>
      </div>

      {!configured && <p className="text-sm text-white">Alım yapmak için önce Ayarlar’dan Binance TR anahtarını ekle.</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm text-white">
          Coin
          <input
            type="text" value={query} placeholder="Örn. ADA" autoCapitalize="characters" spellCheck={false}
            onChange={(e) => { setQuery(e.target.value); invalidate(); }}
            className="input mt-1 block min-h-[48px] w-full rounded-lg border px-3 text-base"
          />
          <span className="mt-1 block text-xs text-bunker-muted">{symbol ? `İşlem çifti: ${symbol}` : "TL çifti otomatik eklenir"}</span>
        </label>
        <div className="text-sm text-white">
          <span id="tutar-etiket">Tutar</span>
          <div className="mt-1 flex flex-wrap gap-2" role="group" aria-labelledby="tutar-etiket">
            {AMOUNT_CHIPS.map((c) => (
              <button
                key={c} type="button" aria-pressed={amount.kind === "chip" && amount.chip === c}
                onClick={() => { setAmount({ kind: "chip", chip: c }); invalidate(); }}
                className={`min-h-[48px] flex-1 rounded-lg border px-3 text-sm font-semibold ${amount.kind === "chip" && amount.chip === c ? "ui-button-primary" : "ui-button-secondary"}`}
              >
                {c === 100 ? "Limit" : `%${c}`}
              </button>
            ))}
            <input
              type="text" inputMode="decimal" placeholder="₺ yaz" aria-label="Tutar (TL)"
              value={amount.kind === "custom" ? amount.text : ""}
              onChange={(e) => { setAmount({ kind: "custom", text: e.target.value }); invalidate(); }}
              className="input min-h-[48px] w-24 rounded-lg border px-2 text-base"
            />
          </div>
          <span className="mt-1 block text-xs text-bunker-muted">Limit = Risk Merkezi’ndeki en yüksek tutar (bakiyenin %{maxPositionPct}’i). Yüzdeler bu limitin parçasıdır.</span>
        </div>
      </div>

      <label className="flex min-h-[44px] items-center gap-2 text-sm text-white">
        <input type="checkbox" checked={manual} onChange={(e) => { setManual(e.target.checked); invalidate(); }} className="h-5 w-5" />
        Oranı ben belirleyeyim
      </label>
      {manual && (
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm text-white">
            Zarar durdur mesafesi (%)
            <input type="text" inputMode="decimal" value={slText} onChange={(e) => { setSlText(e.target.value); invalidate(); }} className="input mt-1 block min-h-[48px] w-full rounded-lg border px-3 text-base" />
            <span className="text-xs text-bunker-muted">0,5 ile 10 arası</span>
          </label>
          <label className="block text-sm text-white">
            Kazanç / risk oranı
            <input type="text" inputMode="decimal" value={rrText} onChange={(e) => { setRrText(e.target.value); invalidate(); }} className="input mt-1 block min-h-[48px] w-full rounded-lg border px-3 text-base" />
            <span className="text-xs text-bunker-muted">1 ile 5 arası</span>
          </label>
        </div>
      )}

      <button type="button" onClick={buildPlan} disabled={!canPlan} className="ui-button-primary min-h-[48px] w-full rounded-lg px-4 text-sm disabled:opacity-50">
        {planBusy ? "Plan hazırlanıyor…" : "Planı hazırla"}
      </button>

      {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}

      {plan && scen && (
        <div className="space-y-3" aria-live="polite">
          <div className="rounded-lg border border-bunker-700 p-3 text-sm text-white">
            <p className="font-semibold">{plan.symbol} · güncel fiyat {fmtPrice(plan.price)}</p>
            <p className="mt-1">
              Önerilen oran: <strong>{rrLabel(plan.plan.rr)}</strong> · zarar durdur mesafesi {fmtPct(plan.plan.sl_pct)}
              <span className="text-bunker-muted"> ({plan.mode === "manual" ? "senin ayarın" : suggestionSourceLabel(plan.suggestion.source)})</span>
            </p>
            {plan.mode === "manual" && (
              <p className="mt-1 text-bunker-muted">Sistem önerisi: {rrLabel(plan.suggestion.rr)} · %{String(plan.suggestion.sl_pct).replace(".", ",")} mesafe</p>
            )}
            {plan.suggestion.rationale && <p className="mt-1 text-bunker-muted">{plan.suggestion.rationale}</p>}
            <p className="mt-2">Harcanacak tutar: <strong>{fmtTry(plan.amount_try)}</strong> · yaklaşık {fmtQty(plan.plan.qty)} adet</p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="card u-card-bad p-3">
              <p className="text-sm font-semibold text-white">Kötü senaryo</p>
              <p className="mt-1 text-sm text-white">{scen.bad}</p>
            </div>
            <div className="card u-card-good p-3">
              <p className="text-sm font-semibold text-white">İyi senaryo</p>
              <p className="mt-1 text-sm text-white">{scen.good}</p>
            </div>
          </div>

          {plan.warning_texts.length > 0 && (
            <ul className="space-y-1" role="alert">
              {plan.warning_texts.map((w) => (<li key={w} className="text-sm text-neon-red">• {w}</li>))}
            </ul>
          )}

          <p className="text-xs text-bunker-muted">{plan.disclaimer} Komisyon dahil tahmindir; ani fiyat hareketlerinde gerçekleşen sonuç farklı olabilir.</p>

          {!liveEnabled && <p className="text-sm text-white">Canlı işlem kapalı. Alım yapmak için aşağıdaki Bağlantı bölümünden aç.</p>}
          <button
            type="button" onClick={openConfirm} disabled={!liveEnabled || blocked}
            className="ui-button-primary min-h-[52px] w-full rounded-lg px-4 text-base disabled:opacity-50"
          >
            Onayla ve al
          </button>
        </div>
      )}

      {result && (
        <div className={`card u-card-${result.tone} p-3`} role="status">
          <p className="font-semibold text-white">{result.title}</p>
          {result.detail && <p className="mt-1 text-sm text-white">{result.detail}</p>}
          {result.needsProtect && (
            <button type="button" onClick={retryProtect} disabled={protectBusy} className="ui-button-primary mt-3 min-h-[48px] rounded-lg px-4 text-sm disabled:opacity-50">
              {protectBusy ? "Deneniyor…" : "Koruma emrini yeniden dene"}
            </button>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen} title="Alımı onayla" confirmLabel="Evet, al" busy={sending}
        onConfirm={confirmBuy} onClose={() => setConfirmOpen(false)}
      >
        {plan && (
          <>
            <p><strong>{plan.symbol}</strong> için <strong>{fmtTry(plan.amount_try)}</strong> tutarında piyasa alımı yapılacak.</p>
            <p>Alım gerçekleşince otomatik emirler kurulur: {fmtPrice(plan.plan.sl_price)} altında zarar durdur, {fmtPrice(plan.plan.tp_price)} üstünde kâr al.</p>
            <p className="text-bunker-muted">Bu işlem gerçek paranla yapılır ve geri alınamaz.</p>
          </>
        )}
      </ConfirmDialog>
    </section>
  );
}
