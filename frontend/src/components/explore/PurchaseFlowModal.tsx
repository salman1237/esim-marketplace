"use client";

import React from "react";
import { ArrowRight, CheckCircle2, X } from "lucide-react";
import { esimInstallLinks } from "@/lib/esimInstall";
import EsimQr from "@/components/EsimQr";
import { dataLabel, priceOf } from "@/lib/packageHelpers";
import { Flow, WORKING_STEPS } from "@/lib/usePackagePurchase";
import PaymentMethodChooser from "@/components/PaymentMethodChooser";

/**
 * The buy-flow overlay (choose payment method / working / preparing /
 * success / error) - identical for the storefront grid and a single
 * package's own page, driven entirely by usePackagePurchase's `flow`.
 */
export default function PurchaseFlowModal({
  flow, workingStep, country, formatPrice, onWallet, onGateway, onCancel, onRetry,
}: {
  flow: Flow | null;
  workingStep: number;
  country: { name_en: string };
  formatPrice: (n: number) => string;
  onWallet: () => void;
  onGateway: () => void;
  onCancel: () => void;
  onRetry: () => void;
}) {
  if (!flow || flow.stage === "checking") return null;

  if (flow.stage === "choose") {
    const payable = flow.discount ? flow.discount.total : priceOf(flow.product);
    return (
      <PaymentMethodChooser
        open
        summary={<>{country.name_en} · {dataLabel(flow.product)} · {flow.product.validity_days} days</>}
        priceLabel={formatPrice(payable)}
        listPriceLabel={formatPrice(priceOf(flow.product))}
        discountLabel={flow.discount ? formatPrice(flow.discount.discount_amount) : undefined}
        discountCode={flow.discount?.code}
        walletBalanceLabel={formatPrice(flow.balance)}
        walletAfterLabel={formatPrice(flow.balance - payable)}
        promoLabel={flow.promo > 0 ? formatPrice(Math.min(flow.promo, payable)) : undefined}
        onWallet={onWallet}
        onGateway={onGateway}
        onCancel={onCancel}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div className="glass-panel rounded-2xl max-w-md w-full p-6 border border-gray-200 shadow-xl">
        {flow.stage === "redirecting" && (
          <div className="text-center py-4">
            <div className="w-14 h-14 rounded-full border-4 border-emerald-100 border-t-emerald-600 animate-spin mx-auto mb-5" />
            <h3 className="text-lg font-bold text-slate-900">Taking you to secure payment</h3>
            <p className="text-xs text-slate-500 mt-1">You&apos;ll pay on ShurjoPay&apos;s page, then come straight back here.</p>
          </div>
        )}

        {flow.stage === "working" && (
          <div className="text-center py-2">
            <div className="w-14 h-14 rounded-full border-4 border-brand-100 border-t-brand-600 animate-spin mx-auto mb-5" />
            <h3 className="text-lg font-bold text-slate-900">Setting up your eSIM</h3>
            <p className="text-xs text-slate-500 mt-1 mb-5">This usually takes 10–20 seconds. Please keep this window open.</p>
            <div className="text-start space-y-2">
              {WORKING_STEPS.map((label, i) => (
                <div key={label} className="flex items-center gap-2 text-xs">
                  {i < workingStep ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  ) : i === workingStep ? (
                    <span className="w-4 h-4 rounded-full border-2 border-brand-600 border-t-transparent animate-spin shrink-0" />
                  ) : (
                    <span className="w-4 h-4 rounded-full border-2 border-gray-200 shrink-0" />
                  )}
                  <span className={i <= workingStep ? "text-slate-900 font-medium" : "text-slate-400"}>{label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {flow.stage === "preparing" && (
          <div className="text-center">
            <div className="w-14 h-14 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-bold text-slate-900">Payment confirmed</h3>
            <p className="text-xs text-slate-500 mt-2 mb-1">
              Your eSIM is being issued by the network. This usually takes a minute or two.
            </p>
            <p className="text-xs text-slate-500 mb-5">
              You don&apos;t need to wait here — we&apos;ll email the QR code, and it will appear in My eSIMs.
              <span className="block mt-1 font-semibold text-slate-700">Please don&apos;t buy again, you have already paid for this one.</span>
            </p>
            <div className="flex gap-3">
              <button onClick={onCancel} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">Close</button>
              <a href="/my-esims" className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold flex items-center justify-center space-x-1">
                <span>View My eSIMs</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        )}

        {flow.stage === "success" && (
          <div className="text-center">
            <div className="w-14 h-14 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-xl font-bold text-slate-900">Your eSIM is ready</h3>
            <p className="text-xs text-slate-500 mt-1 mb-4">Order #{flow.order?.order_no}</p>
            {flow.order?.esim_profile?.qr_code_data && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 inline-block mb-4">
                <EsimQr value={flow.order.esim_profile.qr_code_data} size={150} />
              </div>
            )}
            {(() => {
              const install = esimInstallLinks(flow.order?.esim_profile?.lpa_string);
              if (!install.ios && !install.android) return null;
              return (
                <div className="flex gap-2 mb-3">
                  {install.ios && <a href={install.ios} className="flex-1 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold">Install on iPhone</a>}
                  {install.android && <a href={install.android} className="flex-1 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-bold">Install on Android</a>}
                </div>
              );
            })()}
            <p className="text-[11px] text-slate-500 mb-4">Tap on the phone that will use the eSIM, or scan the QR code from another device.</p>
            <div className="flex gap-3">
              <button onClick={onCancel} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">Close</button>
              <a href="/my-esims" className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold flex items-center justify-center space-x-1">
                <span>View &amp; Print</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        )}

        {flow.stage === "error" && (
          <div className="text-center">
            <div className="w-14 h-14 bg-rose-50 text-rose-600 rounded-full flex items-center justify-center mx-auto mb-4">
              <X className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-bold text-slate-900">Purchase didn&apos;t go through</h3>
            <p className="text-xs text-slate-500 mt-2 mb-5">{flow.message}</p>
            <div className="flex gap-3">
              <button onClick={onCancel} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">Close</button>
              <button onClick={onRetry} className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold">
                Try again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
