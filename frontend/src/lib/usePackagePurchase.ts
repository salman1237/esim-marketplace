"use client";

import React, { useState } from "react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { waitForOrder } from "@/lib/waitForOrder";
import { priceOf, Product } from "@/lib/packageHelpers";

export type Discount = { code: string; discount_amount: number; total: number };

export type Flow =
  | { stage: "checking"; product: Product }
  | { stage: "choose"; product: Product; balance: number; promo: number; discount: Discount | null }
  | { stage: "working"; product: Product }
  // Paid and confirmed, but the supplier issues the eSIM asynchronously and
  // hasn't yet. Deliberately NOT the error stage: this order is fine, and
  // showing a red failure screen for it (which is what used to happen on
  // the polling timeout) teaches customers to retry and buy a second eSIM.
  | { stage: "preparing"; product: Product }
  | { stage: "redirecting"; product: Product }
  | { stage: "success"; product: Product; order: any }
  | { stage: "error"; product: Product; message: string };

export const WORKING_STEPS = ["Payment confirmed", "Reserving your eSIM with the carrier", "Preparing your QR code"];

const PENDING_KEY = "esim_pending_purchase";

/**
 * The full buy flow (discount code, wallet-vs-gateway choice, checkout,
 * poll-for-QR, resume-after-login) - extracted so both the storefront grid
 * (PackageBrowser.tsx) and a single package's own page
 * (explore/[slug]/[productId]/page.tsx) share the EXACT same purchase
 * logic, never two implementations of "what Buy Now does" that could drift.
 *
 * `products` is only used to re-find the package being resumed after a
 * signed-out "Buy Now" sends the visitor to log in and back (?resume=1) -
 * pass the full list on the grid, or just [product] on a single-package page.
 */
export function usePackagePurchase(products: Product[]) {
  const { formatPrice } = useAppSettings();

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

  const clearCode = () => {
    setCode("");
    setApplied(null);
    setCodeError(null);
    setCheckedOk(null);
    setGenericDiscount(null);
  };

  // Typing a new code invalidates whatever was checked/applied for the
  // old one, but (unlike clearCode) keeps the newly typed value instead
  // of blanking it back out.
  const onCodeChange = (value: string) => {
    setCode(value);
    setApplied(null);
    setCodeError(null);
    setCheckedOk(null);
    setGenericDiscount(null);
  };

  React.useEffect(() => {
    if (flow?.stage !== "working") {
      setWorkingStep(0);
      return;
    }
    const timers = [setTimeout(() => setWorkingStep(1), 1200), setTimeout(() => setWorkingStep(2), 7000)];
    return () => timers.forEach(clearTimeout);
  }, [flow?.stage]);

  const busy = flow?.stage === "checking" || flow?.stage === "working" || flow?.stage === "redirecting";

  const payByGateway = async (product: Product, discountCode?: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setFlow({ stage: "redirecting", product });
    try {
      const res = await api.initiateOrderPayment(token, product.id, discountCode ? { discount_code: discountCode } : {});
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

  const payByWallet = async (product: Product, discountCode?: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setFlow({ stage: "working", product });
    try {
      const accepted = await api.checkout(token, {
        product_id: product.id, payment_method: "WALLET", is_buy_for_user: false,
        ...(discountCode ? { discount_code: discountCode } : {}),
      });
      let order;
      try {
        // Most eSIMs land within a few seconds. Waiting a short while gets
        // the QR on screen for the common case without making everyone else
        // watch a spinner for three minutes.
        order = await waitForOrder(token, accepted.id, { timeoutMs: 12000 });
      } catch {
        setFlow({ stage: "preparing", product });
        // Keep watching quietly: if it arrives while they are still here,
        // upgrade to the QR. Only if they haven't moved on - re-opening a
        // modal over whatever they did next would be worse than silence.
        waitForOrder(token, accepted.id, { timeoutMs: 170000 })
          .then((later) => {
            if (later.status !== "COMPLETED") return;
            setFlow((prev) =>
              prev && prev.stage === "preparing" && prev.product.id === product.id
                ? { stage: "success", product, order: later }
                : prev
            );
          })
          .catch(() => {});
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
      // exactly this package and code, instead of landing back with an
      // empty cart and nothing chosen.
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

  return {
    formatPrice,
    flow, setFlow, workingStep, busy,
    code, setCode, applied, codeError, checkingCode, checkedOk, genericDiscount,
    applyCode, clearCode, onCodeChange,
    buyNow, payByWallet, payByGateway,
  };
}
