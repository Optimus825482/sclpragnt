"use client";

import { useEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";

/**
 * Modal erişilebilirliği için TEK doğruluk kaynağı.
 *
 * Neden ayrı dosya
 * ---------------
 * `role="dialog" aria-modal="true"` yazan ama odak tuzağı / Escape / geri
 * `aria-label` içermeyen modal, klavye kullanıcısı için GÜVENLİ DEĞİLDİR:
 * modal açıkken odağı arka plandaki sayfada kalır, kullanıcı farkında olmadan
 * arkasındaki "SATIŞ" / "OCO SL-TP" gibi gerçek para butonlarına
 * `Enter`/`Space` gönderebilir. `binance-tr` sayfasındaki 4 modal gerçek
 * Binance TR emri ilettiği için bu sınıf hata burada en pahalı.
 *
 * Kapsam
 * ------
 *   1. Odak yönetimi: modal açılınca ilk odak noktası (verilen `initialFocus`,
 *      yoksa konteyner), kapanınca `document.activeElement` geri konur.
 *   2. Odak tuzağı: Tab/Shift+Tab konteyner içinde döngüde kalır. Klavye
 *      odağı arka sayfaya kaçamaz.
 *   3. Escape: `keydown` dinleyicisi `onClose` çağırır.
 *   4. Kapsayıcı tıklaması DEĞİL — bu, çağıran bileşenin kendi kararıdır
 *      (bazı modallar arka plan tıklamasını kapatır, bazıları kapatmaz).
 *
 * Kullanım
 * -------
 *   const a11y = useModalA11y(open, onClose, "Piyasa Satışı onayı");
 *   ...
 *   <div role="dialog" aria-modal="true" aria-label={a11y.label} onKeyDown={a11y.onKeyDown}>
 *     <section ref={a11y.ref} tabIndex={-1} className="... outline-none" onClick={stop}>
 *
 * `onClose` referansı her render'da değişebilir; hook gerekirse
 * `closeRef` üzerinden güncel çağrıyı kullanır, bu yüzden `useEffect`
 * bağımlılığı yalnızca `open`'dur (gereksiz re-subscribe yok).
 */

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "button:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
  "audio[controls]",
  "video[controls]",
  "[contenteditable]:not([contenteditable='false'])",
  "details>summary:first-of-type",
].join(", ");

export interface ModalA11y {
  /**
   * Konteyner (dialog gövdesi) ref'i — `tabIndex={-1}` ile birlikte kullanılır.
   * React 18'in `useRef<HTMLElement | null>(null)` imzası `RefObject<T | null>` üretir;
   * `useRef<HTMLElement>(null)` aynı tipi döndürür, bu yüzden ikisi de kabul edilir.
   */
  ref: RefObject<HTMLElement>;
  /** Konteyner üzerine bağlanacak Tab tuzağı işleyicisi. */
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  /** `aria-label` / `aria-labelledby` kararı: `label` verilirse `aria-label` basar. */
  label: string;
  /** `aria-describedby` hedefi (opsiyonel). */
  descriptionId?: string;
}

export interface ModalA11yOptions {
  /**
   * Açılışta odaklanılacak öğe seçicisi (CSS). Bulunamazsa konteynere odak
   * verilir — konteynerde `tabIndex={-1}` olmazsa odak hiç taşınmaz.
   */
  initialFocus?: string;
}

/** Kapsayıcıda odaklanabilir düğümleri DOM sırasına göre döndürür (görünür olanlar). */
function focusableWithin(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (node) => !node.hasAttribute("disabled") && node.getAttribute("aria-hidden") !== "true",
  );
}

export function useModalA11y(
  open: boolean,
  onClose: () => void,
  label: string,
  options: ModalA11yOptions = {},
): ModalA11y {
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const initialFocusRef = useRef(options.initialFocus);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    initialFocusRef.current = options.initialFocus;
  }, [options.initialFocus]);

  useEffect(() => {
    if (!open) return;
    if (typeof document === "undefined") return;

    // Kapanıştan önce odak buradaydı; modal kapanınca oraya geri veriyoruz.
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusTarget = () => {
      const container = ref.current;
      if (!container) return;
      const selector = initialFocusRef.current;
      const preferred = selector ? container.querySelector<HTMLElement>(selector) : null;
      const nodes = focusableWithin(container);
      const target = preferred ?? nodes[0] ?? container;
      try {
        target.focus({ preventScroll: false });
      } catch {
        /* bazı tarayıcılar options'ı desteklemez */
        target.focus();
      }
    };

    // İlk kare: DOM yeni mount edildiği için rAF ile odak taşınır.
    const raf = requestAnimationFrame(focusTarget);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      // Odak konteynerin DIŞINDAYSA tuzağı zorla uygularız (kaybolursa geri al).
      const container = ref.current;
      if (!container) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && container.contains(active)) return;
      const nodes = focusableWithin(container);
      const first = nodes[0] ?? container;
      const last = nodes[nodes.length - 1] ?? container;
      if (event.shiftKey) {
        event.preventDefault();
        last.focus();
      } else {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKeyDown, true);
      // Odak hâlâ modalın içindeyse geri ver; aksi halde kullanıcının
      // yazdığı yere (input) odaklanmış olabilir — zorlamıyoruz.
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try {
          previouslyFocused.focus({ preventScroll: true });
        } catch {
          previouslyFocused.focus();
        }
      }
    };
  }, [open]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const container = ref.current;
    if (!container) return;
    const nodes = focusableWithin(container);
    if (nodes.length === 0) {
      event.preventDefault();
      container.focus();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey && (active === first || active === container)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return { ref, onKeyDown, label };
}
