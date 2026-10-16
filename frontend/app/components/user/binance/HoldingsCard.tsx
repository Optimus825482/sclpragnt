"use client";
import { useRef, useState } from "react";
import { call, type Holding } from "../../../lib/tradeApi";
import { SMALL_BALANCE_TRY, errorText, filterSmallBalances, fmtPct, fmtPrice, fmtQty, fmtSignedTry, fmtTry, newClientOrderId } from "../../../lib/tradeUi";
import ConfirmDialog from "./ConfirmDialog";

const CHIPS = [25, 50, 75, 100];

type Props = { holdings: Holding[]; liveEnabled: boolean; onTraded: () => void };

export default function HoldingsCard({ holdings, liveEnabled, onTraded }: Props) {
  const [target, setTarget] = useState<Holding | null>(null);
  const [chip, setChip] = useState(100);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const clientId = useRef("");
  const [hideSmall, setHideSmall] = useState(true);

  const allCoins = holdings.filter((h) => h.asset !== "TRY" && h.total > 0);
  const coins = filterSmallBalances(allCoins, hideSmall);
  const hiddenCount = allCoins.length - coins.length;
  const qty = target ? target.free * (chip / 100) : 0;

  const sell = async () => {
    if (!target || sending) return;
    setSending(true);
    setError("");
    if (!clientId.current) clientId.current = newClientOrderId();
    const r = await call<{ ok?: boolean; status?: string; detail?: string }>("POST", "/api/binance/sell", {
      asset: target.asset,
      quantity: chip === 100 ? null : qty,
      confirmation: "REAL_SELL",
      client_order_id: clientId.current,
    });
    setSending(false);
    // 202: emir daha önce gönderilmiş / sonucu belirsiz. Aynı kimlikle tekrar denenmez; reddedilmişse yeni kimlik.
    if (r.status === 202) {
      if (r.body.status === "failed") clientId.current = "";
      setError(errorText(r.body.detail));
      setTarget(null);
      return;
    }
    if (!r.ok) {
      setError(errorText(r.error));
      setTarget(null);
      return;
    }
    clientId.current = "";
    setDone(`${target.asset} satış emri gönderildi.`);
    setTarget(null);
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
      {done && <p role="status" className="text-sm text-neon-green">{done}</p>}
      {coins.length === 0 && <p className="text-sm text-bunker-muted">{hiddenCount > 0 ? "Gösterilecek bakiye yok; küçük bakiyeler gizli." : "Şu an elinde coin yok."}</p>}
      <ul className="divide-y divide-bunker-800">
        {coins.map((h) => (
          <li key={h.asset} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="min-w-0">
              <p className="font-semibold text-white">{h.asset} <span className="font-normal text-bunker-muted">· {fmtQty(h.total)} adet</span></p>
              <p className="text-sm text-white">
                {fmtTry(h.value_try)}
                {h.pnl_try != null && (
                  <span className={h.pnl_try >= 0 ? "ml-2 text-neon-green" : "ml-2 text-neon-red"}>
                    {fmtSignedTry(h.pnl_try)}{h.pnl_pct != null ? ` (${fmtPct(h.pnl_pct, 1)})` : ""}
                  </span>
                )}
              </p>
              {h.has_active_order && <p className="text-xs text-bunker-muted">Koruma emri var; satmadan önce açık emirlerden iptal et.</p>}
            </div>
            <button
              type="button" disabled={!liveEnabled || h.free <= 0}
              onClick={() => { clientId.current = ""; setTarget(h); setChip(100); setDone(""); setError(""); }}
              className="min-h-[48px] rounded-lg bg-neon-red px-5 text-sm font-bold text-white disabled:opacity-40"
            >
              Sat
            </button>
          </li>
        ))}
      </ul>
      {!liveEnabled && coins.length > 0 && <p className="text-xs text-bunker-muted">Satmak için canlı işlemi aç.</p>}

      <ConfirmDialog
        open={!!target} title={`${target?.asset ?? ""} sat`} confirmLabel="Evet, sat" danger busy={sending}
        disabled={qty <= 0} onConfirm={sell} onClose={() => setTarget(null)}
      >
        {target && (
          <>
            <div className="flex gap-2" role="group" aria-label="Satılacak oran">
              {CHIPS.map((c) => (
                <button
                  key={c} type="button" aria-pressed={chip === c} onClick={() => { clientId.current = ""; setChip(c); }}
                  className={`min-h-[48px] flex-1 rounded-lg border text-sm font-semibold ${chip === c ? "ui-button-primary" : "ui-button-secondary"}`}
                >
                  %{c}
                </button>
              ))}
            </div>
            <p>
              Satılacak: <strong>{fmtQty(qty)} {target.asset}</strong>
              {target.price_try ? <> (yaklaşık {fmtTry(qty * target.price_try)}, fiyat {fmtPrice(target.price_try)})</> : null}
            </p>
            <p className="text-bunker-muted">Piyasa fiyatından hemen satılır. Bu işlem gerçek paranla yapılır ve geri alınamaz.</p>
          </>
        )}
      </ConfirmDialog>
    </section>
  );
}
