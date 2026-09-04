"use client";

import React, { useState, useEffect } from "react";
import { Briefcase, DollarSign, UserCheck, QrCode, CheckCircle2, Send, Share2, Sparkles, AlertCircle, History, List } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function ResellerPortalPage() {
  const { formatPrice } = useAppSettings();
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
  
  // Tabs & Ledger state
  const [activeTab, setActiveTab] = useState<"provision" | "ledger">("provision");
  const [resellerOrders, setResellerOrders] = useState<any[]>([]);
  const [commissionLedger, setCommissionLedger] = useState<any[]>([]);

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
    const token = localStorage.getItem("esim_token");
    if (!token || !isMerchant) return;
    if (activeTab === "ledger") {
      api.getResellerOrders(token).then(setResellerOrders).catch(console.error);
      api.getWalletLedger(token, "COMMISSION").then(setCommissionLedger).catch(console.error);
    }
  }, [activeTab, isMerchant]);

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
        // account and issue the eSIM to it, per the plan's reseller flow.
        res = await api.checkout(token, {
          product_id: selectedProduct,
          payment_method: "WALLET",
          is_buy_for_user: true,
          auto_create_user: true,
        });
      }
      setOrderResult(res);

      // refresh user data for balances
      api.getMe(token).then(setUserData).catch(console.error);
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
            Apply to become an authorized reseller. Earn a 5% instant commission on every eSIM you issue to your clients.
          </p>

          {applySuccess ? (
            <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 text-center">
              <CheckCircle2 className="w-6 h-6 text-emerald-400 mx-auto mb-2" />
              <h4 className="font-bold text-emerald-400">Application Submitted!</h4>
              <p className="text-xs text-emerald-300 mt-1">Our team is reviewing your application. You will be notified via email.</p>
            </div>
          ) : (
            <form onSubmit={handleApplyMerchant} className="space-y-4">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Registered Business Name (Travel Agency / Tech)</label>
                <input type="text" required value={businessName} onChange={(e) => setBusinessName(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" />
              </div>
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Trade License / Corporate ID</label>
                <input type="text" required value={tradeLicense} onChange={(e) => setTradeLicense(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" />
              </div>
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Business Contact Phone</label>
                <input type="tel" required value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" />
              </div>
              <button type="submit" disabled={applying} className="w-full py-2.5 rounded-xl bg-merchant-600 hover:bg-merchant-500 text-white text-xs font-bold transition-all shadow-lg shadow-merchant-900/30">
                {applying ? "Submitting..." : "Submit B2B Application"}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  const commissionBalance = userData?.wallets?.find((w: any) => w.wallet_type === "COMMISSION")?.balance || 0;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-8">
      
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
          {userData?.merchant_profile && (
            <div className="glass-panel px-4 py-2 rounded-xl border border-white/10 text-end">
              <span className="text-[10px] text-slate-400 uppercase font-semibold block">Your Commission Rate</span>
              <span className="text-base font-black text-amber-400 font-mono">{userData.merchant_profile.commission_rate_pct}%</span>
            </div>
          )}
          <div className="glass-panel px-4 py-2 rounded-xl border border-white/10 text-end">
            <span className="text-[10px] text-slate-400 uppercase font-semibold block">Commission Wallet</span>
            <span className="text-base font-black text-amber-400 font-mono">{formatPrice(commissionBalance)}</span>
          </div>
          <div className="glass-panel px-4 py-2 rounded-xl border border-white/10 text-end">
            <span className="text-[10px] text-slate-400 uppercase font-semibold block">Default Wallet</span>
            <span className="text-base font-black text-emerald-400 font-mono">
              {formatPrice(userData?.wallets?.find((w: any) => w.wallet_type === "DEFAULT")?.balance || 0)}
            </span>
          </div>
        </div>
      </div>
      
      {/* Tabs */}
      <div className="flex space-x-2 border-b border-white/10 pb-4 overflow-x-auto hide-scrollbar">
        <button 
          onClick={() => setActiveTab("provision")} 
          className={`px-4 py-2.5 text-xs font-bold rounded-xl whitespace-nowrap transition-all flex items-center space-x-2 ${activeTab === "provision" ? "bg-amber-500/20 text-amber-400 border border-amber-500/30" : "text-slate-400 hover:text-white bg-slate-900 border border-white/5"}`}
        >
          <Send className="w-3.5 h-3.5" />
          <span>Provision eSIM</span>
        </button>
        <button 
          onClick={() => setActiveTab("ledger")} 
          className={`px-4 py-2.5 text-xs font-bold rounded-xl whitespace-nowrap transition-all flex items-center space-x-2 ${activeTab === "ledger" ? "bg-amber-500/20 text-amber-400 border border-amber-500/30" : "text-slate-400 hover:text-white bg-slate-900 border border-white/5"}`}
        >
          <History className="w-3.5 h-3.5" />
          <span>Sales & Ledger</span>
        </button>
      </div>

      {activeTab === "provision" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Form */}
          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-1">Instant "Buy-for-User" Provisioning</h3>
            <p className="text-xs text-slate-400 mb-6">Allocate and issue an eSIM on behalf of your traveler customer.</p>

            <form onSubmit={handleBuyForUser} className="space-y-4">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Destination Country</label>
                <select value={selectedCountry} onChange={(e) => setSelectedCountry(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" required>
                  <option value="">-- Select Destination Country --</option>
                  {countries.map((c) => (
                    <option key={c.iso2} value={c.iso2}>{c.name_en || c.name} ({c.iso2})</option>
                  ))}
                </select>
              </div>

              {selectedCountry && (
                <div>
                  <label className="text-xs text-slate-300 font-semibold block mb-1">eSIM Package Bundle</label>
                  <select value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" required>
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title_en} — {p.data_amount_gb} GB ({p.validity_days} Days) — {formatPrice(parseFloat(p.retail_price))}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-300 font-semibold block mb-1">Customer Email</label>
                  <input type="email" required placeholder="traveler@gmail.com" value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" />
                </div>
                <div>
                  <label className="text-xs text-slate-300 font-semibold block mb-1">Customer WhatsApp / Phone</label>
                  <input type="tel" placeholder="+880 1800-000000" value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" />
                </div>
              </div>

              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 flex items-center justify-between">
                <span>{userData?.merchant_profile?.commission_rate_pct ?? 5}% Partner Commission:</span>
                <span className="font-bold">Instant Credit to Commission Wallet</span>
              </div>

              <button type="submit" disabled={loading || !selectedProduct} className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center space-x-2">
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

                <div className="bg-slate-900/80 p-4 rounded-xl text-start text-xs space-y-2 font-mono border border-white/5">
                  <div><span className="text-slate-500">Target Customer:</span> {customerEmail}</div>
                  <div><span className="text-slate-500">Order Amount:</span> {formatPrice(parseFloat(orderResult.total_amount))}</div>
                  <div><span className="text-slate-500">Status:</span> <span className="text-emerald-400">{orderResult.status}</span></div>
                </div>

                <div className="flex gap-2">
                  <a href={`https://wa.me/?text=Here%20is%20your%20international%20eSIM%20profile%20for%20Order%20${orderResult.order_no}:%20https://esim.salmandev.io/my-esims`} target="_blank" rel="noreferrer" className="flex-1 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center justify-center space-x-1">
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
      )}

      {activeTab === "ledger" && (
        <div className="space-y-6">
          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-4">Your Issued eSIMs (Sales History)</h3>
            <div className="overflow-x-auto frozen-col-table">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-400 border-b border-white/10">
                  <tr>
                    <th className="py-2">Date</th>
                    <th className="py-2">Order No</th>
                    <th className="py-2">Customer</th>
                    <th className="py-2">Product</th>
                    <th className="py-2">Total Amount</th>
                    <th className="py-2">Your Commission</th>
                    <th className="py-2">ICCID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {resellerOrders.map((o, idx) => (
                    <tr key={idx}>
                      <td className="py-2.5 text-slate-400">{new Date(o.created_at).toLocaleString()}</td>
                      <td className="py-2.5 font-mono text-brand-400">{o.order_no}</td>
                      <td className="py-2.5 text-slate-200">{o.beneficiary_username}</td>
                      <td className="py-2.5 text-slate-200">{o.product_title}</td>
                      <td className="py-2.5 text-slate-400 font-bold">{formatPrice(o.total_amount)}</td>
                      <td className="py-2.5 text-amber-400 font-bold">+{formatPrice(o.commission_earned)}</td>
                      <td className="py-2.5 font-mono text-[10px] text-slate-500">{o.iccid || "N/A"}</td>
                    </tr>
                  ))}
                  {resellerOrders.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-500">No B2B sales history yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-4">Commission Wallet Ledger</h3>
            <div className="overflow-x-auto frozen-col-table">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-400 border-b border-white/10">
                  <tr>
                    <th className="py-2">Date</th>
                    <th className="py-2">Description</th>
                    <th className="py-2">Amount</th>
                    <th className="py-2">Balance After</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {commissionLedger.map((l, idx) => (
                    <tr key={idx}>
                      <td className="py-2.5 text-slate-400">{new Date(l.created_at).toLocaleString()}</td>
                      <td className="py-2.5 text-slate-200">{l.description}</td>
                      <td className={`py-2.5 font-bold ${l.tx_type === 'CREDIT' ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {l.tx_type === 'CREDIT' ? '+' : '-'}{formatPrice(l.amount)}
                      </td>
                      <td className="py-2.5 text-amber-400 font-mono">{formatPrice(l.balance_after)}</td>
                    </tr>
                  ))}
                  {commissionLedger.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-slate-500">No transactions in your commission wallet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
