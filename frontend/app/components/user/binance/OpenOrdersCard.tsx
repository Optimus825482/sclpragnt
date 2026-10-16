"use client";
import { useState } from "react";
import { call, type OpenOrder } from "../../../lib/tradeApi";
import { errorText, fmtPrice, fmtQty } from "../../../lib/tradeUi";
import ConfirmDialog from "./ConfirmDialog";

/** Binance TR sade emir türü adı (jargonsuz). */
function orderKind(o: OpenOrder): string {
  const t = String(o.type || "").toUpperCase();
  if (t.includes("STOP")) return "Zarar durdur";
  if (t.includes("LIMIT")) return "Limit (kâr al / bekleyen)";
  if (t.includes("MARKET")) return "Piyasa";
  return t || "Emir";
}

type Props = { orders: OpenOrder[]; loading: boolean; onChanged: () => void };

export default function OpenOrdersCard({ orders, loading, onChanged }: Props) {
  const [target, setTarget] = useState<OpenOrder | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const cancel = async () => {
    if (!target || busy) return;
    setBusy(true);
    setError("");
    const r = await call("POST", "/api/binance/cancel-order", { order_id: target.orderId, symbol: target.symbol });
    setBusy(false);
    setTarget(null);
    if (!r.ok) setError(errorText(r.error));
    onChanged();
  };

  return (
    <section className="card space-y-3 p-4" aria-labelledby="emir-baslik">
      <h2 id="emir-baslik" className="text-lg font-bold text-white">Bekleyen emirler</h2>
      {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}
      {loading && orders.length === 0 && <p className="text-sm text-bunker-muted">Yükleniyor…</p>}
      {!loading && orders.length === 0 && <p className="text-sm text-bunker-muted">Bekleyen emir yok.</p>}
      <ul className="divide-y divide-bunker-800">
        {orders.map((o) => (
          <li key={o.orderId} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="min-w-0 text-sm text-white">
              <p className="font-semibold">{o.symbol.replace("_", "/")} · {String(o.side).toUpperCase().startsWith("B") || o.side === "0" ? "Alış" : "Satış"} · {orderKind(o)}</p>
              <p className="text-bunker-muted">
                {fmtQty(Number(o.origQty))} adet
                {Number(o.price) > 0 && <> · fiyat {fmtPrice(Number(o.price))}</>}
                {Number(o.stopPrice) > 0 && <> · tetik {fmtPrice(Number(o.stopPrice))}</>}
              </p>
            </div>
            <button type="button" onClick={() => setTarget(o)} className="ui-button-secondary min-h-[48px] rounded-lg border px-4 text-sm font-medium">
              İptal et
            </button>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!target} title="Emri iptal et" confirmLabel="Evet, iptal et" danger busy={busy} onConfirm={cancel} onClose={() => setTarget(null)}>
        {target && (
          <>
            <p>{target.symbol.replace("_", "/")} için {orderKind(target).toLowerCase()} emri iptal edilecek.</p>
            <p className="text-bunker-muted">Koruma emrini iptal edersen pozisyonun zarar durdurma olmadan kalır.</p>
          </>
        )}
      </ConfirmDialog>
    </section>
  );
}
