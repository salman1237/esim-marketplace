"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, QrCode, Send, Share2 } from "lucide-react";
import { api } from "@/lib/api";
import { waitForOrder } from "@/lib/waitForOrder";
import PaymentMethodChooser from "@/components/PaymentMethodChooser";
import PackagePicker, { packLabel } from "@/components/PackagePicker";
import DiscountCodeBox from "@/components/DiscountCodeBox";
import { getToken } from "./shared";

type Props = {
  commissionRatePct?: number | string | null;
  showCommission: boolean;
  formatPrice: (amountUsd: number) => string;
  onOrderSettled: () => void;
};


export default function ProvisionTab({ commissionRatePct, showCommission, formatPrice, onOrderSettled }: Props) {
  const [countries, setCountries] = useState<any[]>([]);
  const [selection, setSelection] = useState<{ country: any | null; product: any | null }>({ country: null, product: null });
  const [customerEmail, setCustomerEmail] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [loading, setLoading] = useState<null | "checking" | "wallet" | "gateway">(null);
  const [chooserBalance, setChooserBalance] = useState<number | null>(null);
  const [orderResult, setOrderResult] = useState<any | null>(null);
  // A merchant selling at the counter gets the same codes a customer would -
  // the campaign is the platform's, not the channel's, so a code that works
  // on the website has to work here too or the agency looks out of date to
  // the traveller standing in front of them.
  const [code, setCode] = useState("");
  const [applied, setApplied] = useState<{ code: string; discountLabel: string; totalLabel: string; total: number } | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [checkingCode, setCheckingCode] = useState(false);
  const [pendingCode, setPendingCode] = useState<string | null>(null);

  // Every destination we sell - not only the handful flagged "popular".
  useEffect(() => {
    api.getCountries().then(setCountries).catch(console.error);
  }, []);

  const product = selection.product;
  const selectedProduct = product?.id || "";

  // A code can be scoped to one country or product, so an applied one stops
  // meaning anything the moment the package changes.
  useEffect(() => {
    setApplied(null);
    setCodeError(null);
  }, [selectedProduct]);

  /** Validates the typed code against the chosen package. Returns the code to
   *  send with the order, or null to buy at full price. */
  const resolveCode = async (): Promise<string | null> => {
    const typed = code.trim();
    if (!typed || !product) return null;
    const token = getToken();
    if (!token) return null;
    if (applied && applied.code.toUpperCase() === typed.toUpperCase()) return applied.code;

    setCheckingCode(true);
    try {
      const preview: any = await api.previewDiscount(token, typed, product.id);
      if (preview.valid) {
        setApplied({
          code: preview.code,
          discountLabel: formatPrice(Number(preview.discount_amount)),
          totalLabel: formatPrice(Number(preview.total)),
          total: Number(preview.total),
        });
        setCodeError(null);
        return preview.code;
      }
      setApplied(null);
      setCodeError(preview.reason || "That code isn't valid.");
      return null;
    } catch {
      setApplied(null);
      setCodeError("We couldn't check that code. Try again.");
      return null;
    } finally {
      setCheckingCode(false);
    }
  };
  const price = product ? parseFloat(product.retail_price) : 0;
  const payable = applied ? applied.total : price;

  // Same beneficiary rule for both payment methods: issue to the customer's
  // existing account by email, or create one on that same email if there
  // isn't any. One call - the server looks the email up before creating.
  //
  // This used to retry WITHOUT the email when the first attempt reported
  // "not found", which is how new customers ended up owning an eSIM on a
  // fabricated user_xxxx@customer.esim.local address they could never
  // sign in to and were never emailed. It also keyed that retry off the
  // text of an error message, so rewording the error silently changed
  // what the merchant portal did.
  const withBeneficiary = async <T,>(send: (extra: Record<string, any>) => Promise<T>): Promise<T> =>
    send({
      is_buy_for_user: true,
      auto_create_user: true,
      beneficiary_email: customerEmail,
      // Becomes the customer's first password when the account is new.
      beneficiary_phone: customerPhone || undefined,
    });

  const payByWallet = async (discountCode?: string | null) => {
    const token = getToken();
    if (!token) return;
    setChooserBalance(null);
    setLoading("wallet");
    try {
      const res: any = await withBeneficiary((extra) =>
        api.checkout(token, {
          product_id: selectedProduct,
          payment_method: "WALLET",
          ...(discountCode ? { discount_code: discountCode } : {}),
          ...extra,
        })
      );
      let settled;
      try {
        settled = await waitForOrder(token, res.id);
      } catch {
        alert(`Order #${res.order_no} is still being set up. It will appear in your orders shortly.`);
        return;
      }
      // Balances changed either way (charged, or charged then refunded).
      onOrderSettled();
      if (settled.status !== "COMPLETED") {
        alert(`eSIM provisioning failed for order #${settled.order_no}. The full amount has been refunded to your wallet.`);
        return;
      }
      setOrderResult(settled);
    } catch (err: any) {
      alert(err.message || "Couldn't issue the eSIM. Please check your wallet balance.");
    } finally {
      setLoading(null);
    }
  };

  const payByGateway = async (discountCode?: string | null) => {
    const token = getToken();
    if (!token) return;
    setChooserBalance(null);
    setLoading("gateway");
    try {
      const res: any = await withBeneficiary((extra) =>
        api.initiateOrderPayment(token, selectedProduct, {
          ...(discountCode ? { discount_code: discountCode } : {}),
          ...extra,
        })
      );
      const checkoutUrl = res.checkout_url || res.checkoutUrl;
      if (checkoutUrl) {
        window.location.href = checkoutUrl;
        return;
      }
      alert("The payment gateway didn't return a checkout link. Please try again.");
    } catch (err: any) {
      alert(err.message || "Couldn't start the secure payment. Please try again.");
    }
    setLoading(null);
  };

  // One Buy Now button, same rule as the storefront: the wallet is offered
  // only when it covers the package, otherwise straight to the gateway.
  const handleBuyNow = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = getToken();
    if (!token || !product) return;
    setLoading("checking");

    // Check the code before the balance: the wallet only has to cover what
    // will actually be charged, and a typed code that turns out to be
    // invalid must not quietly become a full-price sale.
    const typed = code.trim();
    const resolved = await resolveCode();
    if (typed && !resolved) {
      setLoading(null);
      return;
    }

    let balance: number | null = null;
    try {
      const wallets = await api.getMyWallets(token);
      const def = (wallets || []).find((w: any) => w.wallet_type === "DEFAULT");
      balance = def ? parseFloat(def.balance) : 0;
    } catch {
      balance = null;
    }
    setPendingCode(resolved);
    if (balance !== null && balance >= payable) {
      setLoading(null);
      setChooserBalance(balance);
    } else {
      await payByGateway(resolved);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 mb-1">Buy an eSIM for a customer</h3>
        <p className="text-xs text-slate-500 mb-6">
          Pay from your wallet, or by card / mobile banking when your balance doesn&apos;t cover it. The eSIM is issued to your customer.
        </p>

        <form onSubmit={handleBuyNow} className="space-y-4">
          <PackagePicker id="provision-country" countries={countries} formatPrice={formatPrice} onChange={setSelection} />

          <DiscountCodeBox
            value={code}
            onChange={(v) => {
              setCode(v);
              setApplied(null);
              setCodeError(null);
            }}
            applied={applied}
            error={codeError}
            onClear={() => {
              setCode("");
              setApplied(null);
              setCodeError(null);
            }}
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Customer Email</label>
              <input type="email" required placeholder="traveler@gmail.com" value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Customer WhatsApp / Phone <span className="font-normal text-slate-400">(optional)</span></label>
              <input type="tel" placeholder="+880 1800-000000" value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
          </div>

          {showCommission && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-700 flex items-center justify-between">
              <span>{Number(commissionRatePct ?? 5)}% Partner Commission:</span>
              <span className="font-bold">Credited when the eSIM is delivered</span>
            </div>
          )}

          {product && (
            <div className="flex items-center justify-between rounded-xl bg-gray-50 border border-gray-200 px-3 py-2 text-xs">
              <span className="text-slate-600">{selection.country?.name_en} · {packLabel(product)} · {product.validity_days} days</span>
              <span className="font-black text-slate-900">
                {applied ? (
                  <>
                    <span className="text-slate-400 font-semibold line-through me-1.5">{formatPrice(price)}</span>
                    {formatPrice(payable)}
                  </>
                ) : (
                  formatPrice(price)
                )}
              </span>
            </div>
          )}

          <button type="submit" disabled={loading !== null || !selectedProduct} className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-sm font-bold transition-all shadow-md shadow-brand-900/10 flex items-center justify-center space-x-2">
            <Send className="w-4 h-4" />
            <span>
              {checkingCode ? "Checking code…" : loading === "checking" ? "Checking wallet…" : loading === "wallet" ? "Setting up eSIM…" : loading === "gateway" ? "Opening payment…" : selectedProduct ? "Buy Now" : "Choose a package"}
            </span>
          </button>
          <p className="text-center text-[10px] text-slate-400">bKash · Nagad · Card · Wallet</p>
        </form>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 flex flex-col justify-center">
        {orderResult ? (
          <div className="text-center space-y-4">
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <h4 className="text-lg font-bold text-slate-900">eSIM Successfully Allocated!</h4>
            <p className="text-xs text-slate-500">Order #{orderResult.order_no} is ready and emailed to the customer.</p>

            <div className="bg-gray-50 p-4 rounded-xl text-start text-xs space-y-2 font-mono border border-gray-200">
              <div><span className="text-slate-500">Target Customer:</span> {customerEmail}</div>
              <div><span className="text-slate-500">Order Amount:</span> {formatPrice(parseFloat(orderResult.total_amount))}</div>
              <div><span className="text-slate-500">ICCID:</span> {orderResult.esim_profile?.iccid || "—"}</div>
              <div><span className="text-slate-500">Status:</span> <span className="text-emerald-600">{orderResult.status}</span></div>
            </div>

            <a href={`https://wa.me/?text=Here%20is%20your%20international%20eSIM%20profile%20for%20Order%20${orderResult.order_no}:%20https://triptel.co/my-esims`} target="_blank" rel="noreferrer" className="w-full py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center justify-center space-x-1">
              <Share2 className="w-3.5 h-3.5" />
              <span>Share via WhatsApp</span>
            </a>
          </div>
        ) : (
          <div className="text-center text-xs text-slate-500 py-12">
            <QrCode className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>Fill out the form to issue an eSIM to your customer.</p>
            <p className="mt-1">The customer receives the QR code and installation steps by email.</p>
          </div>
        )}
      </div>

      <PaymentMethodChooser
        open={chooserBalance !== null && !!product}
        summary={<>For {customerEmail || "your customer"} · {product ? packLabel(product) : ""} · {product?.validity_days} days</>}
        priceLabel={formatPrice(payable)}
        walletBalanceLabel={formatPrice(chooserBalance ?? 0)}
        walletAfterLabel={formatPrice((chooserBalance ?? 0) - payable)}
        onWallet={() => payByWallet(pendingCode)}
        onGateway={() => payByGateway(pendingCode)}
        onCancel={() => setChooserBalance(null)}
      />
    </div>
  );
}
