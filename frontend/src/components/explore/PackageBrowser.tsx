"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { Check, Share2, Star } from "lucide-react";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { usePackageFilters, PackageFilterChips } from "@/components/explore/PackageFilters";
import PurchaseFlowModal from "@/components/explore/PurchaseFlowModal";
import DiscountCodeBox from "@/components/DiscountCodeBox";
import { dataLabel, estimateDiscount, priceOf, Product } from "@/lib/packageHelpers";
import { usePackagePurchase } from "@/lib/usePackagePurchase";

export default function PackageBrowser({ country, products }: { country: any; products: Product[] }) {
  // Fixed-data vs. Day Pass are different plan shapes (a flat allowance
  // for the whole trip vs. a daily rate bought for a chosen number of
  // days) - split into tabs so they don't look like confusing duplicates
  // sitting side by side. Only shown when a country actually has both;
  // most still only have fixed-data plans.
  const [planType, setPlanType] = useState<"fixed" | "daypass">("fixed");
  const fixedProducts = useMemo(() => products.filter((p) => !p.supplier_period_num), [products]);
  const dayPassProducts = useMemo(() => products.filter((p) => !!p.supplier_period_num), [products]);
  const hasBothPlanTypes = fixedProducts.length > 0 && dayPassProducts.length > 0;
  const planTypeProducts = hasBothPlanTypes ? (planType === "fixed" ? fixedProducts : dayPassProducts) : products;

  const filters = usePackageFilters(planTypeProducts);
  const { filtered } = filters;
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const {
    formatPrice, flow, setFlow, workingStep, busy,
    code, applied, codeError, checkingCode, checkedOk, genericDiscount,
    applyCode, clearCode, onCodeChange, buyNow, payByWallet, payByGateway,
  } = usePackagePurchase(products);

  // Every package's own page: /explore/<slug>/<id> - a real page with its
  // own title, description and Buy Now, not a query param on the listing
  // (the listing-highlight approach was tried and explicitly rejected -
  // "every package should be clickable that will open a page").
  const packageHref = (p: Product) => `/explore/${country.slug}/${p.id}`;

  const shareProduct = async (p: Product) => {
    const shareUrl = `${window.location.origin}${packageHref(p)}`;
    if (navigator.share) {
      try {
        await navigator.share({
          title: `${country.name_en} eSIM — ${dataLabel(p)}, ${p.validity_days} days`,
          text: `${dataLabel(p)} for ${p.validity_days} days in ${country.name_en}, from Triptel.`,
          url: shareUrl,
        });
        return;
      } catch {
        // Cancelled, or sharing isn't allowed here - fall through to copy.
      }
    }
    try {
      await navigator.clipboard?.writeText(shareUrl);
      setCopiedId(p.id);
      setTimeout(() => setCopiedId((cur) => (cur === p.id ? null : cur)), 1800);
    } catch {
      // Clipboard permission denied or unavailable - nothing more to do.
    }
  };

  return (
    <>
      {hasBothPlanTypes && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPlanType("fixed")}
            className={`px-4 py-2 rounded-xl text-xs font-bold border transition-colors ${
              planType === "fixed" ? "bg-brand-600 border-brand-600 text-white" : "bg-white border-gray-300 text-slate-700 hover:bg-gray-50"
            }`}
          >
            Fixed Data
          </button>
          <button
            type="button"
            onClick={() => setPlanType("daypass")}
            className={`px-4 py-2 rounded-xl text-xs font-bold border transition-colors ${
              planType === "daypass" ? "bg-brand-600 border-brand-600 text-white" : "bg-white border-gray-300 text-slate-700 hover:bg-gray-50"
            }`}
          >
            Day Pass
          </button>
        </div>
      )}

      {(filters.availableDays.length > 0 || filters.availableGb.length > 0 || filters.hasUnlimited) && (
        <div className="glass-panel rounded-2xl border border-gray-200 p-4 sm:p-5">
          <PackageFilterChips filters={filters} />
        </div>
      )}

      <div className="glass-panel rounded-2xl border border-gray-200 p-4 sm:p-5 max-w-md">
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
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {filtered.length} of {planTypeProducts.length} package{planTypeProducts.length === 1 ? "" : "s"}
        </p>
        {filters.active && (
          <button type="button" onClick={filters.reset} className="text-xs text-brand-600 hover:underline">
            Clear filters
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="glass-panel rounded-2xl border border-dashed border-gray-300 p-10 text-center">
          <p className="text-sm font-semibold text-slate-900">No package matches these filters</p>
          <p className="text-xs text-slate-500 mt-1">Try a different data size or validity.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((p) => {
            const thisOne = flow?.product?.id === p.id;
            const basePrice = priceOf(p);
            const discountedPrice = genericDiscount ? basePrice - estimateDiscount(basePrice, genericDiscount) : null;
            return (
              <div
                key={p.id}
                className={`glass-card rounded-2xl p-5 border flex flex-col relative ${
                  p.is_featured ? "border-amber-300 ring-1 ring-amber-200" : "border-gray-200"
                }`}
              >
                {p.is_featured && (
                  <span className="absolute -top-2.5 left-4 flex items-center gap-1 bg-amber-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow">
                    <Star className="w-3 h-3 fill-white" /> Recommended
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => shareProduct(p)}
                  aria-label="Copy this package's link"
                  className="absolute top-3 right-3 p-1.5 rounded-lg text-slate-400 hover:text-brand-600 hover:bg-brand-50"
                >
                  {copiedId === p.id ? <Check className="w-4 h-4 text-emerald-600" /> : <Share2 className="w-4 h-4" />}
                </button>

                {/* The package's own page - title/description/Buy Now all
                    live there too, so a shared link is never just a
                    generic listing (explore/[slug]/[productId]/page.tsx). */}
                <Link href={packageHref(p)} className="block group">
                  <div className="text-xl font-black text-slate-900 group-hover:text-brand-600">{dataLabel(p)}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{p.validity_days} days validity · 4G/5G</div>
                  {p.coverage_countries && p.coverage_countries.length > 0 && (
                    <p className="text-[11px] text-slate-500 mt-1">
                      Covers: {p.coverage_countries.slice(0, 4).join(", ")}
                      {p.coverage_countries.length > 4 ? ` +${p.coverage_countries.length - 4} more` : ""}
                    </p>
                  )}
                  {discountedPrice !== null ? (
                    <div className="mt-4">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-slate-400 line-through">{formatPrice(basePrice)}</span>
                        <span className="text-[10px] font-bold text-emerald-700 bg-emerald-100 rounded-full px-2 py-0.5">
                          SAVE {formatPrice(basePrice - discountedPrice)}
                        </span>
                      </div>
                      <div className="text-2xl font-black text-emerald-600">{formatPrice(discountedPrice)}</div>
                    </div>
                  ) : (
                    <div className="text-2xl font-black text-emerald-600 mt-4">{formatPrice(basePrice)}</div>
                  )}
                </Link>

                <button
                  onClick={() => buyNow(p)}
                  disabled={busy}
                  className="mt-4 w-full bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-sm font-bold py-3 rounded-xl"
                >
                  {thisOne && flow?.stage === "checking" ? "Checking…" : thisOne && flow?.stage === "redirecting" ? "Opening payment…" : "Buy Now"}
                </button>
                <p className="mt-2 text-center text-[10px] text-slate-400">bKash · Nagad · Card · Wallet</p>
              </div>
            );
          })}
        </div>
      )}

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
    </>
  );
}
