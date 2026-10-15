"use client";

import { useEffect, useRef } from "react";

/**
 * Kabuk seviyesindeki bileşenler (ör. bildirim toast'u) ile ana sayfa arasında
 * sembol seçimi köprüsü. Toast "İşlem Yap" dediğinde sayfa durumu doğrudan
 * değiştirilemez; olay yayınlanır, ana sayfa dinler ve emir panelini doldurur.
 * Sembolü panele taşımak EMİR GÖNDERMEZ; gerçek emir için ayrı onay gerekir.
 */
export const SELECT_SYMBOL_EVENT = "odak:select-symbol";
export const SELECT_SYMBOL_QUERY = "symbol";

export type SymbolSelectionDetail = { symbol: string; amount?: number | null };

export function requestSymbolSelection(detail: SymbolSelectionDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SymbolSelectionDetail>(SELECT_SYMBOL_EVENT, { detail }));
}

export function useSymbolSelectionRequest(handler: (detail: SymbolSelectionDetail) => void) {
  const handlerRef = useRef(handler);
  useEffect(() => { handlerRef.current = handler; }, [handler]);
  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<SymbolSelectionDetail>).detail;
      const symbol = String(detail?.symbol || "").toUpperCase().trim();
      if (symbol) handlerRef.current({ symbol, amount: detail?.amount ?? null });
    };
    window.addEventListener(SELECT_SYMBOL_EVENT, listener);
    return () => window.removeEventListener(SELECT_SYMBOL_EVENT, listener);
  }, []);
}
