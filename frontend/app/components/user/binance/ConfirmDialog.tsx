"use client";
import type { ReactNode } from "react";
import { useModalA11y } from "../../../lib/useModalA11y";

type Props = {
  open: boolean;
  title: string;
  confirmLabel: string;
  busy?: boolean;
  danger?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  children: ReactNode;
};

/** Gerçek para işlemleri için onay penceresi: odak tuzağı, Escape, büyük dokunma hedefleri. */
export default function ConfirmDialog({ open, title, confirmLabel, busy, danger, disabled, onConfirm, onClose, children }: Props) {
  const a11y = useModalA11y(open, onClose, title);
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={a11y.label}
      onKeyDown={a11y.onKeyDown}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-3 sm:items-center"
      onClick={() => { if (!busy) onClose(); }}
    >
      <section
        ref={a11y.ref}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-md space-y-4 p-5 outline-none"
      >
        <h2 className="text-lg font-bold text-white">{title}</h2>
        <div className="space-y-2 text-sm text-white">{children}</div>
        <div className="flex gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="ui-button-secondary min-h-[48px] flex-1 rounded-lg border px-4 text-sm font-medium disabled:opacity-50">
            Vazgeç
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || disabled}
            className={`min-h-[48px] flex-1 rounded-lg px-4 text-sm font-bold text-white disabled:opacity-50 ${danger ? "bg-neon-red" : "ui-button-primary"}`}
          >
            {busy ? "Gönderiliyor…" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
