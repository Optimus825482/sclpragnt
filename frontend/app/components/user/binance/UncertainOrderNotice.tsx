"use client";

type Props = {
  /** "Durum belirsiz" ana metni (emir borsaya ulaÅŸtÄ± mÄ± bilinmiyor). */
  text: string;
  /** Son "Durumu sorgula" sonucu. */
  lookup?: string;
  lookupBusy?: boolean;
  onLookup: () => void;
  /** Verilirse "Bildirimi kapat" düğmesi görünür (kullanıcı durumu kendisi doğruladıysa). */
  onDismiss?: () => void;
};

/**
 * 2026-10-16 (basit arayÃ¼z): aÄŸ/zaman aÅŸÄ±mÄ± sonrasÄ± emir durumu BELÄ°RSÄ°Z uyarÄ±sÄ± + "Durumu sorgula".
 * Al ve Sat kartlarÄ± aynÄ± bileÅŸeni kullanÄ±r; onay penceresi aÃ§Ä±k kalÄ±r, aynÄ± emir kimliÄŸi korunur.
 */
export default function UncertainOrderNotice({ text, lookup, lookupBusy, onLookup, onDismiss }: Props) {
  return (
    <div role="alert" className="rounded-lg border border-yellow-400/60 bg-yellow-400/10 p-3 text-sm text-white">
      <p className="font-semibold text-yellow-300">Durum belirsiz</p>
      <p className="mt-1">{text}</p>
      <button
        type="button" onClick={onLookup} disabled={lookupBusy}
        className="ui-button-secondary mt-2 min-h-[44px] rounded-lg border px-4 text-sm font-semibold disabled:opacity-50"
      >
        {lookupBusy ? "SorgulanÄ±yorâ€¦" : "Durumu sorgula"}
      </button>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="ml-2 mt-2 min-h-[44px] rounded-lg px-3 text-sm text-bunker-muted underline">
          Bildirimi kapat
        </button>
      )}
      {lookup && <p className="mt-2" role="status">{lookup}</p>}
    </div>
  );
}
