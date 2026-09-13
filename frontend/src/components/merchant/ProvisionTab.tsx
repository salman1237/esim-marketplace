"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, QrCode, Send, Share2 } from "lucide-react";
import { api } from "@/lib/api";
import { waitForOrder } from "@/lib/waitForOrder";
import { getToken } from "./shared";

type Props = {
  commissionRatePct?: number | string | null;
  showCommission: boolean;
  formatPrice: (amountUsd: number) => string;
  onOrderSettled: () => void;
};

export default function ProvisionTab({ commissionRatePct, showCommission, formatPrice, onOrderSettled }: Props) {
  const [countries, setCountries] = useState<any[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<string>("");
  const [products, setProducts] = useState<any[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [orderResult, setOrderResult] = useState<any | null>(null);

  useEffect(() => {
    api.getCountries(undefined, true).then(setCountries).catch(console.error);
  }, []);

  useEffect(() => {
    if (selectedCountry) {
      api.getCountryProducts(selectedCountry).then((data) => {
        setProducts(data);
        if (data.length > 0) setSelectedProduct(data[0].id);
      }).catch(console.error);
    }
  }, [selectedCountry]);

  const handleBuyForUser = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = getToken();
    if (!token) return;

    setLoading(true);
    try {
      let res;
      try {
        // First try to find an existing customer account by email.
        res = await api.checkout(token, {
          product_id: selectedProduct,
          payment_method: "WALLET",
          is_buy_for_user: true,
          beneficiary_email: customerEmail,
          auto_create_user: false,
        });
      } catch (lookupErr: any) {
        if (!String(lookupErr.message || "").includes("Beneficiary user account not found")) throw lookupErr;
        // No existing account for that email — auto-generate a new customer
        // account and issue the eSIM to it, per the reseller flow.
        res = await api.checkout(token, {
          product_id: selectedProduct,
          payment_method: "WALLET",
          is_buy_for_user: true,
          auto_create_user: true,
        });
      }
      // Checkout returns once the wallet is charged; wait for the eSIM.
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
      alert(err.message || "B2B Provisioning failed. Please verify merchant wallet balance.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 mb-1">Buy an eSIM for a customer</h3>
        <p className="text-xs text-slate-500 mb-6">Paid from your wallet balance and issued to your traveler customer.</p>

        <form onSubmit={handleBuyForUser} className="space-y-4">
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Destination Country</label>
            <select value={selectedCountry} onChange={(e) => setSelectedCountry(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" required>
              <option value="">-- Select Destination Country --</option>
              {countries.map((c) => (
                <option key={c.iso2} value={c.iso2}>{c.name_en || c.name} ({c.iso2})</option>
              ))}
            </select>
          </div>

          {selectedCountry && (
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">eSIM Package Bundle</label>
              <select value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" required>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title_en} — {p.is_unlimited ? "Unlimited" : `${p.data_amount_gb} GB`} ({p.validity_days} Days) — {formatPrice(parseFloat(p.retail_price))}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Customer Email</label>
              <input type="email" required placeholder="traveler@gmail.com" value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Customer WhatsApp / Phone</label>
              <input type="tel" placeholder="+880 1800-000000" value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
          </div>

          {showCommission && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-700 flex items-center justify-between">
              <span>{Number(commissionRatePct ?? 5)}% Partner Commission:</span>
              <span className="font-bold">Credited when the eSIM is delivered</span>
            </div>
          )}

          <button type="submit" disabled={loading || !selectedProduct} className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold transition-all shadow-md shadow-brand-900/10 flex items-center justify-center space-x-2">
            <Send className="w-3.5 h-3.5" />
            <span>{loading ? "Setting up eSIM..." : "Issue eSIM for Customer"}</span>
          </button>
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
            <p>Fill out the form to instantly allocate an eSIM.</p>
            <p className="mt-1">The customer receives the QR code and installation steps by email.</p>
          </div>
        )}
      </div>
    </div>
  );
}
