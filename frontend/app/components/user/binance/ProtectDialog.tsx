"use client";
import { useEffect, useState } from "react";
import type { Holding } from "../../../lib/tradeApi";
import { fmtPct, fmtPrice, fmtQty, parseTrNumber } from "../../../lib/tradeUi";
import { UncertainOrderError, orderFailureText, postJsonGuarded, uncertainOrderText } from "../../../binance-tr/orderSafety";
import ConfirmDialog from "./ConfirmDialog";
import {
  PROTECT_QTY_CHIPS, PROTECT_SL_CHIPS, PROTECT_TP_CHIPS, protectOrder, type ProtectMode,
} from "./protectMath";

type Props = {
  holding: Holding | null;
  liveEnabled: boolean;
  onClose: () => void;
  /** Emir denemesinden sonra (başarılı, hatalı ya da belirsiz) listeler tazelenir: set-sl-tp "iptal → kur" çalışır. */
  onTraded: () => void;
  showToast: (message: string, type?: "success" | "error" | "info") => void;
};

const MODES: { mode: ProtectMode; label: string }[] = [
  { mode: "OCO", label: "İkisi (OCO)" },
  { mode: "SL_ONLY", label: "Zarar durdur" },
  { mode: "TP_ONLY", label: "Kâr al" },
];

/** Yüzde düğmeleri + isteğe bağlı elle yüzde. */
function PctPicker({ label, chips, sign, value, onChange }: {
  label: string; chips: readonly number[]; sign: "-" | "+"; value: string; onChange: (v: string) => void;
}) {
  const n = parseTrNumber(value);
  return (
    <div className="text-sm text-white">
      <span>{label}</span>
      <div className="mt-1 flex gap-1" role="group" aria-label={label}>
        {chips.map((c) => (
          <button
            key={c} type="button" aria-pressed={n === c} onClick={() => onChange(String(c))}
            className={`min-h-[44px] flex-1 rounded-lg border px-2 text-sm font-semibold ${n === c ? "ui-button-primary" : "ui-button-secondary"}`}
          >
            {sign}%{c}
          </button>
        ))}
        <input
          type="text" inputMode="decimal" placeholder="%" aria-label={`${label} (yüzde)`} value={value}
          onChange={(e) => onChange(e.target.value)} className="input min-h-[44px] w-16 rounded-lg border px-2 text-base"
        />
      </div>
    </div>
  );
}

/**
 * Pozisyona zarar durdur / kâr al / ikisi (OCO) ekleme penceresi (Binance TR basit görünüm, kalkan düğmesi).
 * Gönderimde coindeki mevcut açık satış emirleri ÖNCE iptal edilir, sonra yeni emir borsaya iletilir (sunucu tarafı).
 */
export default function ProtectDialog({ holding, liveEnabled, onClose, onTraded, showToast }: Props) {
  const [mode, setMode] = useState<ProtectMode>("OCO");
  const [slText, setSlText] = useState("2");
  const [tpText, setTpText] = useState("5");
  const [qtyPct, setQtyPct] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const asset = holding?.asset ?? "";

  useEffect(() => {
    if (!asset) return;
    setMode("OCO"); setSlText("2"); setTpText("5"); setQtyPct(100); setError("");
  }, [asset]);

  if (!holding) return null;
  const price = holding.price_try;
  const plan = protectOrder({
    mode, price, slPct: parseTrNumber(slText), tpPct: parseTrNumber(tpText), qtyPct, total: holding.total,
  });
  const cost = holding.avg_cost_try ?? null;
  const vsCost = (p: number | undefined) => (p && cost && cost > 0 ? ` · alışa göre ${fmtPct(((p - cost) / cost) * 100, 1)}` : "");

  const send = async () => {
    if (!plan.ok || busy) return;
    setBusy(true);
    setError("");
    try {
      // set-sl-tp idempotent DEĞİL ("iptal → kur"): belirsiz sonuçta tekrar göndermek yerine listeler tazelenir.
      const { status, ok, body } = await postJsonGuarded<{ ok?: boolean; detail?: unknown }>("/api/binance/set-sl-tp", {
        ...plan.body, asset: holding.asset,
      });
      if (!ok || !body.ok) { setError(orderFailureText("sltp", status, body.detail)); return; }
      showToast(`${holding.asset} için ${MODES.find((m) => m.mode === mode)?.label.toLowerCase()} emri borsaya iletildi.`, "success");
      onClose();
    } catch (e) {
      setError(e instanceof UncertainOrderError ? uncertainOrderText("sltp", e.timedOut) : "Emir gönderilemedi.");
    } finally {
      setBusy(false);
      onTraded();
    }
  };

  return (
    <ConfirmDialog
      open
      title={`${holding.asset} · zarar durdur / kâr al`}
      confirmLabel={busy ? "Gönderiliyor…" : "Emri gönder"}
      busy={busy}
      disabled={!plan.ok || !liveEnabled}
      onConfirm={send}
      onClose={() => { if (!busy) onClose(); }}
    >
      <div className="space-y-4">
        <p className="text-sm text-bunker-muted">
          Güncel fiyat {price ? fmtPrice(price) : "—"}{cost ? ` · alış ${fmtPrice(cost)}` : ""} · elinde {fmtQty(holding.total)} adet
        </p>

        <div className="flex gap-1" role="group" aria-label="Emir türü">
          {MODES.map((m) => (
            <button
              key={m.mode} type="button" aria-pressed={mode === m.mode} onClick={() => setMode(m.mode)}
              className={`min-h-[44px] flex-1 rounded-lg border px-2 text-sm font-semibold ${mode === m.mode ? "ui-button-primary" : "ui-button-secondary"}`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {mode !== "TP_ONLY" && (
          <PctPicker label="Zarar durdur: güncel fiyatın altı" chips={PROTECT_SL_CHIPS} sign="-" value={slText} onChange={setSlText} />
        )}
        {mode !== "SL_ONLY" && (
          <PctPicker label="Kâr al: güncel fiyatın üstü" chips={PROTECT_TP_CHIPS} sign="+" value={tpText} onChange={setTpText} />
        )}

        <div className="text-sm text-white">
          <span>Miktar</span>
          <div className="mt-1 flex gap-1" role="group" aria-label="Miktar">
            {PROTECT_QTY_CHIPS.map((c) => (
              <button
                key={c} type="button" aria-pressed={qtyPct === c} onClick={() => setQtyPct(c)}
                className={`min-h-[44px] flex-1 rounded-lg border px-2 text-sm font-semibold ${qtyPct === c ? "ui-button-primary" : "ui-button-secondary"}`}
              >
                %{c}
              </button>
            ))}
          </div>
        </div>

        {plan.ok ? (
          <div className="rounded-lg border border-bunker-700 p-3 text-sm text-white" aria-live="polite">
            {plan.body.sl_price !== undefined && <p>Zarar durdur: <strong>{fmtPrice(plan.body.sl_price)}</strong>{vsCost(plan.body.sl_price)}</p>}
            {plan.body.tp_price !== undefined && <p>Kâr al: <strong>{fmtPrice(plan.body.tp_price)}</strong>{vsCost(plan.body.tp_price)}</p>}
            <p>Miktar: {plan.body.quantity === "all" ? `tamamı (${fmtQty(holding.total)})` : fmtQty(plan.body.quantity)}</p>
          </div>
        ) : (
          <p role="alert" className="text-sm text-neon-red">{plan.error}</p>
        )}

        {(holding.has_active_order || holding.locked > 0) && (
          <p className="text-xs text-yellow-300">Bu coindeki mevcut açık satış emirleri önce iptal edilir, sonra yeni emir gönderilir.</p>
        )}
        {!liveEnabled && <p className="text-xs text-yellow-300">Canlı işlem kapalı; emir gönderilemez.</p>}
        {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
      </div>
    </ConfirmDialog>
  );
}
