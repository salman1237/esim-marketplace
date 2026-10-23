"use client";

import React, { useState } from "react";
import { ArrowRight, CheckCircle2, Star, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { esimInstallLinks } from "@/lib/esimInstall";
import { waitForOrder } from "@/lib/waitForOrder";
import PaymentMethodChooser from "@/components/PaymentMethodChooser";
import DiscountCodeBox from "@/components/DiscountCodeBox";
import { usePackageFilters, PackageFilterChips } from "@/components/explore/PackageFilters";

type Product = {
  id: string;
  title_en: string;
  data_amount_gb: string | number;
  validity_days: number;
  retail_price: string | number;
  is_unlimited: boolean;
  is_featured?: boolean;
  currency?: string;
};

type Discount = { code: string; discount_amount: number; total: number };

type Flow =
  | { stage: "checking"; product: Product }
  | { stage: "choose"; product: Product; balance: number; promo: number; discount: Discount | null }
  | { stage: "working"; product: Product }
  | { stage: "redirecting"; product: Product }
  | { stage: "success"; product: Product; order: any }
  | { stage: "error"; product: Product; message: string };

const WORKING_STEPS = ["Payment confirmed", "Reserving your eSIM with the carrier", "Preparing your QR code"];

const priceOf = (p: Product) => parseFloat(String(p.retail_price));
const dataLabel = (p: Product) => (p.is_unlimited ? "Unlimited" : `${Number(p.data_amount_gb)} GB`);

const PENDING_KEY = "esim_pending_purchase";

// A rough, client-side estimate from the public (pre-login) code check -
// just enough to show "you'll save about this much" on every card. The
// real amount is always recomputed per-product, authoritatively, by
// api.previewDiscount once the customer actually buys.
function estimateDiscount(price: number, generic: { discount_type: string; value: string; max_discount_amount: string | null }) {
  if (generic.discount_type === "PERCENT") {
    let amount = (price * parseFloat(generic.value)) / 100;
    if (generic.max_discount_amount) amount = Math.min(amount, parseFloat(generic.max_discount_amount));
    return Math.min(amount, price);
  }
  return Math.min(parseFloat(generic.value), price);
}

export default function PackageBrowser({ country, products }: { country: any; products: Product[] }) {
  const { formatPrice } = useAppSettings();
  const filters = usePackageFilters(products);
  const { filtered } = filters;
  const [flow, setFlow] = useState<Flow | null>(null);
  const [workingStep, setWorkingStep] = useState(0);
  const [code, setCode] = useState("");
  const [applied, setApplied] = useState<{ code: string; discountLabel: string; totalLabel: string } | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [checkingCode, setCheckingCode] = useState(false);
  const [checkedOk, setCheckedOk] = useState<{ code: string; note: string } | null>(null);
  const [genericDiscount, setGenericDiscount] = useState<{ discount_type: string; value: string; max_discount_amount: string | null } | null>(null);

  const applyCode = async () => {
    const typed = code.trim();
    if (!typed) return;
    setCheckingCode(true);
    setCodeError(null);
    try {
      const res = await api.checkDiscountCode(typed);
      if (res.valid) {
        setGenericDiscount({ discount_type: res.discount_type, value: res.value, max_discount_amount: res.max_discount_amount });
        setCheckedOk({
          code: res.code,
          note: res.scoped
            ? "exact savings confirmed once you sign in to buy"
            : `${res.discount_type === "PERCENT" ? res.value + "% off" : formatPrice(parseFloat(res.value)) + " off"}`,
        });
      } else {
        setGenericDiscount(null);
        setCheckedOk(null);
        setCodeError(res.reason || "That code isn't valid.");
      }
    } catch {
      setCodeError("Couldn't check that code. Try again.");
    } finally {
      setCheckingCode(false);
    }
  };

  // After "Buy Now" sends a signed-out visitor to log in, the page comes
  // back here with ?resume=1 - re-find the same package and continue
  // exactly where they left off, code and all, instead of making them
  // start over having already created an account for nothing.
  React.useEffect(() => {
    if (new URLSearchParams(window.location.search).get("resume") !== "1") return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    let pending: { productId: string; code: string } | null = null;
    try {
      const raw = sessionStorage.getItem(PENDING_KEY);
      if (raw) pending = JSON.parse(raw);
    } catch {
      pending = null;
    }
    sessionStorage.removeItem(PENDING_KEY);
    window.history.replaceState(null, "", window.location.pathname);
    if (!pending) return;
    const product = products.find((p) => p.id === pending!.productId);
    if (!product) return;
    if (pending.code) setCode(pending.code);
    // Let the code state settle before resuming the purchase it belongs to.
    setTimeout(() => buyNow(product, pending!.code || undefined), 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (flow?.stage !== "working") {
      setWorkingStep(0);
      return;
    }
    const timers = [setTimeout(() => setWorkingStep(1), 1200), setTimeout(() => setWorkingStep(2), 7000)];
    return () => timers.forEach(clearTimeout);
  }, [flow?.stage]);

  const busy = flow?.stage === "checking" || flow?.stage === "working" || flow?.stage === "redirecting";

  const payByGateway = async (product: Product, code?: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setFlow({ stage: "redirecting", product });
    try {
      const res = await api.initiateOrderPayment(token, product.id, code ? { discount_code: code } : {});
      const checkoutUrl = res.checkout_url || res.checkoutUrl;
      if (checkoutUrl) {
        window.location.href = checkoutUrl;
        return;
      }
      setFlow({ stage: "error", product, message: "The payment gateway didn't return a checkout link. Please try again." });
    } catch (err: any) {
      setFlow({ stage: "error", product, message: err.message || "Couldn't start the secure payment. Please try again." });
    }
  };

  const payByWallet = async (product: Product, code?: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setFlow({ stage: "working", product });
    try {
      const accepted = await api.checkout(token, {
        product_id: product.id, payment_method: "WALLET", is_buy_for_user: false,
        ...(code ? { discount_code: code } : {}),
      });
      let order;
      try {
        order = await waitForOrder(token, accepted.id);
      } catch {
        setFlow({
          stage: "error", product,
          message: "This is taking longer than usual. Your order is still being set up and will appear in My eSIMs shortly — you'll also get it by email.",
        });
        return;
      }
      if (order.status === "COMPLETED") setFlow({ stage: "success", product, order });
      else setFlow({ stage: "error", product, message: "We couldn't set up this eSIM with the network. The full amount has been refunded to your wallet." });
    } catch (err: any) {
      setFlow({ stage: "error", product, message: err.message || "Purchase failed. If your wallet was charged, it has been refunded." });
    }
  };

  // One Buy Now button. The wallet is offered only when it can cover the
  // plan; otherwise the customer goes straight to the payment gateway.
  const buyNow = async (product: Product, overrideCode?: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      // Remembered so the trip back from login/register can pick up
      // exactly this package and code, instead of landing on the
      // destination page with an empty cart and nothing chosen.
      try {
        sessionStorage.setItem(PENDING_KEY, JSON.stringify({ productId: product.id, code: code.trim() }));
      } catch {
        // Best effort - worst case the customer just re-picks the package.
      }
      const here = `${window.location.pathname}?resume=1`;
      window.location.href = `/auth/login?next=${encodeURIComponent(here)}`;
      return;
    }
    setFlow({ stage: "checking", product });
    setCodeError(null);

    // A code is checked against the package being bought, since it can be
    // limited to a destination, a package or a minimum order. Checkout
    // re-validates under a lock, so this is a quote, not a promise.
    let discount: Discount | null = null;
    const typed = (overrideCode ?? code).trim();
    if (typed) {
      try {
        const preview = await api.previewDiscount(token, typed, product.id);
        if (preview.valid) {
          discount = { code: preview.code, discount_amount: Number(preview.discount_amount), total: Number(preview.total) };
          setApplied({
            code: preview.code,
            discountLabel: formatPrice(Number(preview.discount_amount)),
            totalLabel: formatPrice(Number(preview.total)),
          });
        } else {
          // Stop rather than quietly charge full price - the customer
          // deliberately entered a code.
          setApplied(null);
          setCodeError(preview.reason || "That code isn't valid.");
          setFlow(null);
          return;
        }
      } catch {
        setApplied(null);
        setCodeError("Couldn't check that code. Try again, or clear it to buy at the normal price.");
        setFlow(null);
        return;
      }
    }

    const payable = discount ? discount.total : priceOf(product);
    let balance: number | null = null;
    let promo = 0;
    try {
      const wallets = await api.getMyWallets(token);
      const def = (wallets || []).find((w: any) => w.wallet_type === "DEFAULT");
      const reward = (wallets || []).find((w: any) => w.wallet_type === "REWARD");
      // Reward credit pays for eSIMs (it just can't be withdrawn), so it
      // counts towards covering the price - otherwise a customer holding
      // enough promo credit would be sent to the card page anyway.
      promo = reward ? parseFloat(reward.balance) : 0;
      balance = (def ? parseFloat(def.balance) : 0) + promo;
    } catch {
      // Balance unknown - don't offer a wallet payment we can't vouch for.
      balance = null;
    }
    if (balance !== null && balance >= payable) {
      setFlow({ stage: "choose", product, balance, promo, discount });
    } else {
      await payByGateway(product, discount?.code);
    }
  };

  const clearCode = () => {
    setCode("");
    setApplied(null);
    setCodeError(null);
    setCheckedOk(null);
    setGenericDiscount(null);
  };

  return (
    <>
      {(filters.availableDays.length > 0 || filters.availableGb.length > 0 || filters.hasUnlimited) && (
        <div className="glass-panel rounded-2xl border border-gray-200 p-4 sm:p-5">
          <PackageFilterChips filters={filters} />
        </div>
      )}

      <div className="glass-panel rounded-2xl border border-gray-200 p-4 sm:p-5 max-w-md">
        <DiscountCodeBox
          value={code}
          onChange={(v) => { setCode(v); setApplied(null); setCodeError(null); setCheckedOk(null); setGenericDiscount(null); }}
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
          {filtered.length} of {products.length} package{products.length === 1 ? "" : "s"}
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
                <div className="text-xl font-black text-slate-900">{dataLabel(p)}</div>
                <div className="text-xs text-slate-500 mt-0.5">{p.validity_days} days validity · 4G/5G</div>
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

      {flow?.stage === "choose" && (() => {
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
            onWallet={() => payByWallet(flow.product, flow.discount?.code)}
            onGateway={() => payByGateway(flow.product, flow.discount?.code)}
            onCancel={() => setFlow(null)}
          />
        );
      })()}

      {flow && flow.stage !== "choose" && flow.stage !== "checking" && (
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

            {flow.stage === "success" && (
              <div className="text-center">
                <div className="w-14 h-14 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 className="w-8 h-8" />
                </div>
                <h3 className="text-xl font-bold text-slate-900">Your eSIM is ready</h3>
                <p className="text-xs text-slate-500 mt-1 mb-4">Order #{flow.order?.order_no}</p>
                {flow.order?.esim_profile?.qr_code_data && (
                  <div className="bg-white border border-gray-200 rounded-xl p-4 inline-block mb-4">
                    <QRCodeSVG value={flow.order.esim_profile.qr_code_data} size={150} level="M" />
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
                  <button onClick={() => setFlow(null)} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">Close</button>
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
                  <button onClick={() => setFlow(null)} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">Close</button>
                  <button onClick={() => buyNow(flow.product)} className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold">
                    Try again
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
