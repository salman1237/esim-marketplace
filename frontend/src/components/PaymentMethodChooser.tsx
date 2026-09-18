"use client";

import React from "react";
import { CreditCard, Wallet, X } from "lucide-react";

type Props = {
  open: boolean;
  summary: React.ReactNode;
  priceLabel: string;
  walletBalanceLabel: string;
  walletAfterLabel: string;
  onWallet: () => void;
  onGateway: () => void;
  onCancel: () => void;
};

// Shown only when the wallet can actually cover the purchase - otherwise
// Buy Now goes straight to the payment gateway and this never opens.
export default function PaymentMethodChooser({
  open, summary, priceLabel, walletBalanceLabel, walletAfterLabel, onWallet, onGateway, onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pay-choose-title"
    >
      <div className="glass-panel rounded-2xl max-w-md w-full p-6 border border-gray-200 shadow-xl relative">
        <button onClick={onCancel} aria-label="Close" className="absolute top-4 end-4 p-1 rounded-lg text-slate-400 hover:text-slate-900">
          <X className="w-5 h-5" />
        </button>

        <h3 id="pay-choose-title" className="text-lg font-bold text-slate-900 pe-8">How would you like to pay?</h3>
        <p className="text-xs text-slate-500 mt-1">{summary}</p>

        <div className="mt-4 rounded-xl bg-gray-50 border border-gray-200 px-4 py-3 flex items-center justify-between">
          <span className="text-xs text-slate-500">Total</span>
          <span className="text-lg font-black text-slate-900">{priceLabel}</span>
        </div>

        <div className="mt-4 space-y-3">
          <button
            type="button"
            onClick={onWallet}
            className="w-full text-start rounded-xl border-2 border-gray-200 hover:border-brand-500 hover:bg-brand-50/40 bg-white p-4 flex items-center gap-3 transition-colors"
          >
            <span className="w-10 h-10 rounded-xl bg-brand-50 text-brand-600 flex items-center justify-center shrink-0">
              <Wallet className="w-5 h-5" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-bold text-slate-900">Wallet balance</span>
              <span className="block text-[11px] text-slate-500">
                {walletBalanceLabel} available · {walletAfterLabel} left after
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={onGateway}
            className="w-full text-start rounded-xl border-2 border-gray-200 hover:border-emerald-500 hover:bg-emerald-50/40 bg-white p-4 flex items-center gap-3 transition-colors"
          >
            <span className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
              <CreditCard className="w-5 h-5" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-bold text-slate-900">Card or mobile banking</span>
              <span className="block text-[11px] text-slate-500">bKash, Nagad, Rocket, Visa, Mastercard — secure ShurjoPay checkout</span>
            </span>
          </button>
        </div>

        <button type="button" onClick={onCancel} className="mt-4 w-full py-2 text-xs font-semibold text-slate-500 hover:text-slate-800">
          Cancel
        </button>
      </div>
    </div>
  );
}
