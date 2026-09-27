"use client";

import React from "react";
import { BadgePercent, Check, X } from "lucide-react";

type Props = {
  value: string;
  onChange: (code: string) => void;
  // Set once a code has been checked against a specific package, cleared
  // when the customer edits it.
  applied?: { code: string; discountLabel: string; totalLabel: string } | null;
  error?: string | null;
  onClear: () => void;
  className?: string;
};

// The code lives next to the packages rather than inside the payment popup,
// because Buy Now goes straight to the gateway when the wallet can't cover
// the price - so a field that only existed in that popup would be
// unreachable for exactly the customers most likely to want a discount.
export default function DiscountCodeBox({ value, onChange, applied, error, onClear, className = "" }: Props) {
  return (
    <div className={className}>
      <label className="text-xs font-bold text-slate-700 flex items-center gap-1.5 mb-1.5">
        <BadgePercent className="w-3.5 h-3.5 text-brand-600" /> Discount code
      </label>

      {applied ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
          <Check className="w-4 h-4 text-emerald-600 shrink-0" />
          <span className="text-xs font-bold text-emerald-800 font-mono">{applied.code}</span>
          <span className="text-xs text-emerald-700">
            − {applied.discountLabel} · pay {applied.totalLabel}
          </span>
          <button
            type="button"
            onClick={onClear}
            aria-label="Remove discount code"
            className="ms-auto text-emerald-700 hover:text-emerald-900"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            value={value}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            placeholder="Enter a code"
            spellCheck={false}
            autoComplete="off"
            className="flex-1 min-w-0 bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono uppercase text-slate-900"
          />
          {value.trim() !== "" && (
            <button
              type="button"
              onClick={onClear}
              className="px-3 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-600 text-xs font-bold"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {error ? (
        <p className="mt-1.5 text-[11px] text-rose-600">{error}</p>
      ) : !applied ? (
        <p className="mt-1.5 text-[11px] text-slate-500">Applied when you buy — one code per order.</p>
      ) : null}
    </div>
  );
}
