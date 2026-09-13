"use client";

import React, { useEffect, useRef } from "react";

type Tone = "admin" | "merchant" | "danger";

type Props = {
  open: boolean;
  title: string;
  children?: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: Tone;
  icon?: React.ReactNode;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

const TONES: Record<Tone, { button: string; iconWrap: string }> = {
  admin: { button: "bg-admin-600 hover:bg-admin-500", iconWrap: "bg-admin-50 text-admin-600" },
  merchant: { button: "bg-merchant-600 hover:bg-merchant-500", iconWrap: "bg-merchant-50 text-merchant-600" },
  danger: { button: "bg-rose-600 hover:bg-rose-500", iconWrap: "bg-rose-50 text-rose-600" },
};

// Styled replacement for window.confirm - the native box can't be branded,
// can't show structured details, and looks like a browser warning rather
// than part of the product.
export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "admin",
  icon,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    // Destructive actions start on Cancel so Enter can't trigger them by accident.
    (tone === "danger" ? cancelRef : confirmRef).current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, tone, onCancel]);

  if (!open) return null;
  const styles = TONES[tone];

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4"
      onClick={() => !busy && onCancel()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="w-full max-w-md rounded-2xl bg-white border border-gray-200 shadow-2xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-4">
          {icon && <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${styles.iconWrap}`}>{icon}</div>}
          <div className="flex-1 min-w-0">
            <h3 id="confirm-dialog-title" className="text-lg font-bold text-slate-900">{title}</h3>
            {children && <div className="mt-2 text-sm text-slate-600 space-y-3">{children}</div>}
          </div>
        </div>

        <div className="mt-6 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2.5 rounded-xl border border-gray-300 bg-white hover:bg-gray-50 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={`px-4 py-2.5 rounded-xl text-sm font-bold text-white shadow-md disabled:opacity-60 ${styles.button}`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
