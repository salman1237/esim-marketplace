"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, ShieldCheck, Share2, Wifi, Zap } from "lucide-react";
import { dataLabel, priceOf, Product } from "@/lib/packageHelpers";
import { usePackagePurchase } from "@/lib/usePackagePurchase";
import PurchaseFlowModal from "@/components/explore/PurchaseFlowModal";
import DiscountCodeBox from "@/components/DiscountCodeBox";

/**
 * A single package's own page - real title, description and Buy Now, not a
 * highlighted card on the listing. Every package's share button
 * (PackageBrowser.tsx) points here, and this is where that link actually
 * lands and works.
 */
export default function PackageDetail({ country, product }: { country: any; product: Product }) {
  const [copied, setCopied] = useState(false);
  const {
    formatPrice, flow, setFlow, workingStep, busy,
    code, applied, codeError, checkingCode, checkedOk,
    applyCode, onCodeChange, clearCode, buyNow, payByWallet, payByGateway,
  } = usePackagePurchase([product]);

  const share = async () => {
    const shareUrl = window.location.href.split("?")[0];
    if (navigator.share) {
      try {
        await navigator.share({
          title: `${country.name_en} eSIM — ${dataLabel(product)}, ${product.validity_days} days`,
          text: `${dataLabel(product)} for ${product.validity_days} days in ${country.name_en}, from Triptel.`,
          url: shareUrl,
        });
        return;
      } catch {
        // Cancelled, or sharing isn't allowed here - fall through to copy.
      }
    }
    try {
      await navigator.clipboard?.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard permission denied or unavailable - nothing more to do.
    }
  };

  const thisOne = flow?.product?.id === product.id;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <Link
        href={`/explore/${country.slug}`}
        className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> All {country.name_en} packages
      </Link>

      <div className="glass-panel rounded-2xl border border-gray-200 p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            {country.flag_url && (
              <div className="w-14 h-10 rounded-lg overflow-hidden border border-gray-200 shadow-sm shrink-0">
                <img src={country.flag_url} alt={country.name_en} className="w-full h-full object-cover" />
              </div>
            )}
            <div className="min-w-0">
              <p className="text-xs font-semibold text-brand-600">{country.name_en} eSIM</p>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
                {dataLabel(product)} · {product.validity_days} days
              </h1>
            </div>
          </div>
          <button
            type="button"
            onClick={share}
            aria-label="Copy this package's link"
            className="inline-flex items-center gap-1.5 rounded-xl border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:border-brand-500 hover:text-brand-600 shrink-0"
          >
            {copied ? (
              <><Check className="w-4 h-4 text-emerald-600" /> Copied</>
            ) : (
              <><Share2 className="w-4 h-4" /> Share</>
            )}
          </button>
        </div>

        {/* Title & description, per the request - a real package page, not
            just specs floating with no context. */}
        <p className="text-sm text-slate-600 mt-4 max-w-xl">
          {dataLabel(product)} of high-speed mobile data for {product.validity_days} days in {country.name_en}.
          Delivered instantly by QR code - install it before you travel and it activates the moment you land,
          no physical SIM, no roaming bill, no waiting in line at the airport.
        </p>

        {product.coverage_countries && product.coverage_countries.length > 0 && (
          <p className="text-xs text-slate-500 mt-3">
            Also covers: {product.coverage_countries.join(", ")}
          </p>
        )}

        <div className="flex flex-wrap gap-4 mt-5 text-xs text-slate-600">
          <span className="flex items-center gap-1.5"><Zap className="w-4 h-4 text-brand-600" /> QR delivered in seconds</span>
          <span className="flex items-center gap-1.5"><Wifi className="w-4 h-4 text-brand-600" /> 4G / 5G data, no roaming bill</span>
          <span className="flex items-center gap-1.5"><ShieldCheck className="w-4 h-4 text-emerald-600" /> Keep your own number</span>
        </div>
      </div>

      <div className="glass-panel rounded-2xl border border-gray-200 p-6 sm:p-8 max-w-md">
        <DiscountCodeBox
          value={code}
          onChange={onCodeChange}
          applied={applied}
          checkedOk={checkedOk}
          checking={checkingCode}
          onApply={applyCode}
          error={codeError}
          onClear={clearCode}
        />

        <div className="text-3xl font-black text-emerald-600 mt-4">{formatPrice(priceOf(product))}</div>

        <button
          onClick={() => buyNow(product)}
          disabled={busy}
          className="mt-4 w-full bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-sm font-bold py-3 rounded-xl"
        >
          {thisOne && flow?.stage === "checking" ? "Checking…" : thisOne && flow?.stage === "redirecting" ? "Opening payment…" : "Buy Now"}
        </button>
        <p className="mt-2 text-center text-[10px] text-slate-400">bKash · Nagad · Card · Wallet</p>
      </div>

      <PurchaseFlowModal
        flow={flow}
        workingStep={workingStep}
        country={country}
        formatPrice={formatPrice}
        onWallet={() => flow?.stage === "choose" && payByWallet(flow.product, flow.discount?.code)}
        onGateway={() => flow?.stage === "choose" && payByGateway(flow.product, flow.discount?.code)}
        onCancel={() => setFlow(null)}
        onRetry={() => flow && buyNow(flow.product)}
      />
    </div>
  );
}
