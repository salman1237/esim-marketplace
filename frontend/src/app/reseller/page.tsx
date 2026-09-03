"use client";

import React, { useState, useEffect } from "react";
import { Briefcase, DollarSign, UserCheck, QrCode, CheckCircle2, Send, Share2, Sparkles, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";

export default function ResellerPortalPage() {
  const [userData, setUserData] = useState<any>(null);
  const [countries, setCountries] = useState<any[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<string>("");
  const [products, setProducts] = useState<any[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [orderResult, setOrderResult] = useState<any | null>(null);
  const [isMerchant, setIsMerchant] = useState(false);

  // Merchant application state
  const [businessName, setBusinessName] = useState("");
  const [tradeLicense, setTradeLicense] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [applying, setApplying] = useState(false);
  const [applySuccess, setApplySuccess] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }

    api.getMe(token).then((data) => {
      setUserData(data);
      setIsMerchant(data.role === "MERCHANT" || data.role === "ADMIN" || data.role === "SUPER_ADMIN");
    }).catch(console.error);

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

  const handleApplyMerchant = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    setApplying(true);
    try {
      await api.applyMerchant(token, {
        business_name: businessName,
        trade_license: tradeLicense,
        contact_phone: contactPhone,
      });
      setApplySuccess(true);
    } catch (err: any) {
      alert(err.message || "Failed to submit partner application");
    } finally {
      setApplying(false);
    }
  };

  const handleBuyForUser = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    setLoading(true);
    try {
      const res = await api.checkout(token, {
        product_id: selectedProduct,
        payment_method: "WALLET",
        is_buy_for_user: true,
        customer_email: customerEmail,
        customer_phone: customerPhone,
      });
      setOrderResult(res);
    } catch (err: any) {
      alert(err.message || "B2B Provisioning failed. Please verify merchant wallet balance.");
    } finally {
      setLoading(false);
    }
  };

  if (!isMerchant) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16">
        <div className="glass-panel rounded-2xl p-8 border border-white/10 shadow-2xl">
          <div className="w-12 h-12 bg-merchant-500/20 text-merchant-400 rounded-xl flex items-center justify-center mx-auto mb-4">
            <Briefcase className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-white text-center">B2B Travel Partner Program</h2>
          <p className="text-xs text-slate-400 text-center mt-1 mb-6">
            Earn up to 10% commission on international eSIM data packages. Resell high-speed mobile data to your customers, travel agencies, and sub-agents.
          </p>

          {applySuccess ? (
            <div className="p-6 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-center">
              <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto mb-2" />
              <h3 className="text-base font-bold text-white">Application Submitted</h3>
              <p className="text-xs text-slate-400 mt-1">Our partner team is reviewing your details. Once approved, your B2B reseller console will activate automatically.</p>
            </div>
          ) : (
            <form onSubmit={handleApplyMerchant} className="space-y-4">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Company / Agency Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. TravelSmart BD"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Trade License / Business Reg No.</label>
                <input
                  type="text"
                  placeholder="e.g. TRAD/DNCC/12345/2026"
                  value={tradeLicense}
                  onChange={(e) => setTradeLicense(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Official Contact Phone / WhatsApp</label>
                <input
                  type="tel"
                  required
                  placeholder="+880 1700-000000"
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                />
              </div>

              <button
                type="submit"
                disabled={applying}
                className="w-full py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 text-xs font-bold transition-all shadow-lg shadow-amber-900/30"
              >
                {applying ? "Submitting Application..." : "Apply for Reseller Account"}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
      
      {/* Reseller Header & Commission Ticker */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center space-x-1.5 text-amber-400 text-xs font-bold uppercase tracking-wider mb-1">
            <Briefcase className="w-4 h-4" />
            <span>Authorized B2B Partner Portal</span>
          </div>
          <h1 className="text-3xl font-extrabold text-white">Reseller Operations &amp; eSIM Provisioning</h1>
        </div>

        <div className="flex gap-3">
          <div className="glass-panel px-4 py-2 rounded-xl border border-white/10 text-right">
            <span className="text-[10px] text-slate-400 uppercase font-semibold block">Commission Rebate</span>
            <span className="text-base font-black text-amber-400">5.0% Fixed B2B</span>
          </div>
          <div className="glass-panel px-4 py-2 rounded-xl border border-white/10 text-right">
            <span className="text-[10px] text-slate-400 uppercase font-semibold block">Default Wallet</span>
            <span className="text-base font-black text-emerald-400 font-mono">
              ${userData?.wallets?.[0]?.balance?.toFixed(2) || "0.00"}
            </span>
          </div>
        </div>
      </div>

      {/* B2B Provisioning Form */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* Form */}
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-1">Instant "Buy-for-User" Provisioning</h3>
          <p className="text-xs text-slate-400 mb-6">Allocate and issue an eSIM on behalf of your traveler customer.</p>

          <form onSubmit={handleBuyForUser} className="space-y-4">
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Destination Country</label>
              <select
                value={selectedCountry}
                onChange={(e) => setSelectedCountry(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                required
              >
                <option value="">-- Select Destination Country --</option>
                {countries.map((c) => (
                  <option key={c.iso2} value={c.iso2}>{c.name_en || c.name} ({c.iso2})</option>
                ))}
              </select>
            </div>

            {selectedCountry && (
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">eSIM Package Bundle</label>
                <select
                  value={selectedProduct}
                  onChange={(e) => setSelectedProduct(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                  required
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title_en} — {p.data_amount_gb} GB ({p.validity_days} Days) — ${parseFloat(p.retail_price).toFixed(2)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Customer Email</label>
                <input
                  type="email"
                  required
                  placeholder="traveler@gmail.com"
                  value={customerEmail}
                  onChange={(e) => setCustomerEmail(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Customer WhatsApp / Phone</label>
                <input
                  type="tel"
                  placeholder="+880 1800-000000"
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                />
              </div>
            </div>

            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 flex items-center justify-between">
              <span>5% Partner Commission:</span>
              <span className="font-bold">Instant Credit to Commission Wallet</span>
            </div>

            <button
              type="submit"
              disabled={loading || !selectedProduct}
              className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center space-x-2"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{loading ? "Provisioning eSIM..." : "Issue eSIM for Customer"}</span>
            </button>
          </form>
        </div>

        {/* Result Preview */}
        <div className="glass-panel rounded-2xl p-6 border border-white/10 flex flex-col justify-center">
          {orderResult ? (
            <div className="text-center space-y-4">
              <div className="w-12 h-12 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto">
                <CheckCircle2 className="w-6 h-6" />
              </div>
              <h4 className="text-lg font-bold text-white">eSIM Successfully Allocated!</h4>
              <p className="text-xs text-slate-400">Order #{orderResult.order_no} created and ready for delivery.</p>

              <div className="bg-slate-900/80 p-4 rounded-xl text-left text-xs space-y-2 font-mono border border-white/5">
                <div><span className="text-slate-500">Target Customer:</span> {customerEmail}</div>
                <div><span className="text-slate-500">Order Amount:</span> ${parseFloat(orderResult.total_amount).toFixed(2)}</div>
                <div><span className="text-slate-500">Status:</span> <span className="text-emerald-400">{orderResult.status}</span></div>
              </div>

              <div className="flex gap-2">
                <a
                  href={`https://wa.me/?text=Here%20is%20your%20international%20eSIM%20profile%20for%20Order%20${orderResult.order_no}:%20https://esim.salmandev.io/my-esims`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex-1 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center justify-center space-x-1"
                >
                  <Share2 className="w-3.5 h-3.5" />
                  <span>Share via WhatsApp</span>
                </a>
              </div>
            </div>
          ) : (
            <div className="text-center text-xs text-slate-500 py-12">
              <QrCode className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>Fill out the form to instantly allocate an eSIM.</p>
              <p className="mt-1">The customer will receive instant installation instructions.</p>
            </div>
          )}
        </div>

      </div>

    </div>
  );
}
