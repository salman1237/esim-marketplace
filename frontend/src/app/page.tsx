"use client";

import React, { useState, useEffect } from "react";
import { Search, Zap, ShieldCheck, Globe, ArrowRight, CheckCircle2, Sparkles, Check, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { ProductListSkeleton } from "@/components/Skeleton";
import { esimInstallLinks } from "@/lib/esimInstall";
import { waitForOrder } from "@/lib/waitForOrder";

export default function HomePage() {
  const { formatPrice } = useAppSettings();
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [countries, setCountries] = useState<any[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<any | null>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  // The purchase runs as a small state machine rather than a single
  // "purchasing" flag: provisioning takes ~12s at the supplier, and the
  // old UI froze every pack's button with no explanation of the wait.
  const [flow, setFlow] = useState<null | {
    stage: "confirm" | "working" | "success" | "error";
    product: any;
    method: "wallet" | "gateway";
    order?: any;
    message?: string;
  }>(null);
  const [walletBalance, setWalletBalance] = useState<number | null>(null);
  const [workingStep, setWorkingStep] = useState(0);

  // Default popular destinations
  const defaultPopular = [
    { iso2: "US", name: "United States", flag: "🇺🇸", minPrice: "€4.50" },
    { iso2: "TH", name: "Thailand", flag: "🇹🇭", minPrice: "€3.90" },
    { iso2: "JP", name: "Japan", flag: "🇯🇵", minPrice: "€4.90" },
    { iso2: "SA", name: "Saudi Arabia", flag: "🇸🇦", minPrice: "€6.00" },
    { iso2: "AE", name: "United Arab Emirates", flag: "🇦🇪", minPrice: "€5.50" },
    { iso2: "GB", name: "United Kingdom", flag: "🇬🇧", minPrice: "€4.50" },
    { iso2: "TR", name: "Turkey", flag: "🇹🇷", minPrice: "€3.50" },
    { iso2: "BD", name: "Bangladesh", flag: "🇧🇩", minPrice: "€2.90" },
  ];

  useEffect(() => {
    api.getCountries(undefined, true)
      .then((data) => {
        if (data && data.length > 0) setCountries(data);
        else setCountries(defaultPopular.map((d, i) => ({ id: i + 1, iso2: d.iso2, name_en: d.name, flag_url: `https://flagcdn.com/w80/${d.iso2.toLowerCase()}.png` })));
      })
      .catch(() => {
        setCountries(defaultPopular.map((d, i) => ({ id: i + 1, iso2: d.iso2, name_en: d.name, flag_url: `https://flagcdn.com/w80/${d.iso2.toLowerCase()}.png` })));
      });
  }, []);

  // Full-catalog autocomplete: the popular-destinations grid above only
  // ever holds ~10 countries, so filtering it client-side silently found
  // nothing for the other 200+ (e.g. "Vietnam", "Malaysia"). Debounced
  // search against the real /catalog/countries?search= endpoint instead.
  useEffect(() => {
    const term = search.trim();
    if (!term) {
      setSearchResults([]);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    const handle = setTimeout(() => {
      api.getCountries(term)
        .then((data) => setSearchResults(data || []))
        .catch(() => setSearchResults([]))
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [search]);

  const handleSelectCountry = async (c: any) => {
    setSelectedCountry(c);
    setLoading(true);
    try {
      const prods = await api.getCountryProducts(c.iso2);
      setProducts(prods);
    } catch {
      // Fallback sample packages for demonstration
      setProducts([
        { id: "pkg_1", title_en: `${c.name_en || c.name} 1 GB`, data_amount_gb: 1.0, validity_days: 7, retail_price: 4.50, currency: "EUR" },
        { id: "pkg_2", title_en: `${c.name_en || c.name} 3 GB`, data_amount_gb: 3.0, validity_days: 15, retail_price: 9.00, currency: "EUR" },
        { id: "pkg_3", title_en: `${c.name_en || c.name} 5 GB`, data_amount_gb: 5.0, validity_days: 30, retail_price: 13.50, currency: "EUR" },
        { id: "pkg_4", title_en: `${c.name_en || c.name} 10 GB`, data_amount_gb: 10.0, validity_days: 30, retail_price: 22.00, currency: "EUR" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // Honest, non-blocking narration of a wait we can't shorten: the
  // supplier call takes ~12s, so the steps advance on a timer rather than
  // pretending to track real progress.
  const WORKING_STEPS = [
    "Payment confirmed",
    "Reserving your eSIM with the carrier",
    "Preparing your QR code",
  ];

  useEffect(() => {
    if (flow?.stage !== "working") {
      setWorkingStep(0);
      return;
    }
    const timers = [
      setTimeout(() => setWorkingStep(1), 1200),
      setTimeout(() => setWorkingStep(2), 7000),
    ];
    return () => timers.forEach(clearTimeout);
  }, [flow?.stage]);

  const openPurchase = async (product: any, method: "wallet" | "gateway") => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    setFlow({ stage: "confirm", product, method });
    // Shown on the confirm step so the customer sees what's left
    // afterwards - failing on balance only after a 12s wait is a poor way
    // to find out.
    try {
      const wallets = await api.getMyWallets(token);
      const def = (wallets || []).find((w: any) => w.wallet_type === "DEFAULT");
      setWalletBalance(def ? parseFloat(def.balance) : null);
    } catch {
      setWalletBalance(null);
    }
  };

  const confirmPurchase = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token || !flow) return;
    const { product, method } = flow;

    if (method === "gateway") {
      setFlow({ stage: "working", product, method });
      try {
        const res = await api.initiateOrderPayment(token, product.id);
        const checkoutUrl = res.checkout_url || res.checkoutUrl;
        if (checkoutUrl) {
          window.location.href = checkoutUrl;
          return;
        }
        setFlow({ stage: "error", product, method, message: "The payment gateway didn't return a checkout link. Please try again, or pay from your wallet." });
      } catch (err: any) {
        setFlow({ stage: "error", product, method, message: err.message || "Couldn't start checkout." });
      }
      return;
    }

    setFlow({ stage: "working", product, method });
    try {
      // Returns as soon as the wallet is charged; the eSIM is set up in the
      // background, so poll for the outcome.
      const accepted = await api.checkout(token, {
        product_id: product.id,
        payment_method: "WALLET",
        is_buy_for_user: false,
      });
      let order;
      try {
        order = await waitForOrder(token, accepted.id);
      } catch {
        setFlow({
          stage: "error",
          product,
          method,
          message: "This is taking longer than usual. Your order is still being set up and will appear in My eSIMs shortly - you'll also get it by email.",
        });
        return;
      }
      if (order.status === "COMPLETED") {
        setFlow({ stage: "success", product, method, order });
      } else {
        setFlow({
          stage: "error",
          product,
          method,
          message: "We couldn't set up this eSIM with the network. The full amount has been refunded to your wallet.",
        });
      }
    } catch (err: any) {
      setFlow({
        stage: "error",
        product,
        method,
        message: err.message || "Purchase failed. If your wallet was charged, it has been refunded.",
      });
    }
  };

  const handleSelectSearchResult = (country: any) => {
    setSearch("");
    setSearchResults([]);
    handleSelectCountry(country);
  };

  return (
    <div className="space-y-16">
      
      {/* Hero Banner */}
      <section className="relative pt-20 pb-16 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto text-center">
        <div className="inline-flex items-center space-x-2 bg-brand-50 border border-brand-200 text-brand-700 text-xs font-semibold px-3 py-1.5 rounded-full mb-6">
          <Sparkles className="w-3.5 h-3.5 text-accent-600" />
          <span>Next-Gen Travel Connectivity &bull; 200+ Destinations</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-slate-900 leading-tight">
          Stay Connected Worldwide <br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 via-accent-600 to-indigo-500">
            Without Roaming Fees
          </span>
        </h1>

        <p className="mt-4 text-base sm:text-lg text-slate-500 max-w-2xl mx-auto">
          High-speed 4G & 5G international data. Install directly in settings with a single QR code scan. Instant digital delivery.
        </p>

        {/* Live Search Bar */}
        <div className="mt-8 max-w-xl mx-auto relative">
          <div className="glass-panel rounded-2xl p-2 flex items-center shadow-lg shadow-brand-900/5">
            <Search className="w-5 h-5 text-slate-400 ms-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Where are you traveling? (e.g. Thailand, USA, Japan)..."
              className="bg-transparent border-none focus:outline-none w-full px-3 py-2 text-sm text-slate-900 placeholder-slate-400"
              autoComplete="off"
            />
          </div>

          {search.trim() && (
            <div className="absolute top-full inset-x-0 mt-2 glass-panel rounded-2xl shadow-lg border border-gray-200 max-h-80 overflow-y-auto text-start z-40">
              {searchLoading ? (
                <p className="px-4 py-3 text-xs text-slate-500">Searching...</p>
              ) : searchResults.length === 0 ? (
                <p className="px-4 py-3 text-xs text-slate-500">No destinations match "{search}"</p>
              ) : (
                searchResults.map((c) => (
                  <button
                    key={c.id ?? c.iso2}
                    onClick={() => handleSelectSearchResult(c)}
                    className="w-full flex items-center space-x-3 px-4 py-2.5 hover:bg-gray-50 text-start"
                  >
                    <div className="w-7 h-5 rounded overflow-hidden shrink-0 border border-gray-200 bg-gray-100 flex items-center justify-center">
                      {c.flag_url ? (
                        <img src={c.flag_url} alt={c.name_en || c.name} className="w-full h-full object-cover" />
                      ) : (
                        <span className="text-xs">🌍</span>
                      )}
                    </div>
                    <span className="text-sm text-slate-900">{c.name_en || c.name}</span>
                    <span className="text-[10px] text-slate-500 ms-auto">{c.iso2}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Value Props */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-6 text-xs text-slate-500 font-medium">
          <div className="flex items-center space-x-2"><Zap className="w-4 h-4 text-amber-500" /><span>Instant QR Delivery</span></div>
          <div className="flex items-center space-x-2"><ShieldCheck className="w-4 h-4 text-emerald-600" /><span>Official Carrier Partners</span></div>
          <div className="flex items-center space-x-2"><Globe className="w-4 h-4 text-cyan-600" /><span>200+ Countries Covered</span></div>
        </div>
      </section>

      {/* Destinations Grid */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Popular Destinations</h2>
            <p className="text-xs text-slate-500 mt-1">Select a country to browse high-speed data bundles</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-4">
          {countries.map((country) => (
            <button
              key={country.iso2}
              onClick={() => handleSelectCountry(country)}
              className="glass-card rounded-xl p-4 text-start flex items-center space-x-3.5 hover:border-brand-500/50 group"
            >
              <div className="w-10 h-7 rounded overflow-hidden shadow shrink-0 border border-gray-200 flex items-center justify-center bg-gray-100 text-xl">
                {country.flag_url ? (
                  <img src={country.flag_url} alt={country.name_en || country.name} className="w-full h-full object-cover" />
                ) : (
                  <span>🌍</span>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-slate-900 group-hover:text-brand-600 truncate transition-colors">
                  {country.name_en || country.name}
                </h3>
                <span className="text-[11px] text-slate-500 flex items-center space-x-1">
                  <span>View plans</span>
                  <ArrowRight className="w-2.5 h-2.5 group-hover:translate-x-0.5 transition-transform" />
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Country Packages Modal / Drawer */}
      {selectedCountry && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="glass-panel rounded-2xl max-w-lg w-full p-6 relative border border-gray-200 shadow-xl">
            <button
              onClick={() => setSelectedCountry(null)}
              aria-label="Close"
              className="absolute top-4 end-4 p-1 rounded-lg text-slate-400 hover:text-slate-900"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center space-x-3 mb-6">
              <div className="w-10 h-7 rounded overflow-hidden shadow border border-gray-200 shrink-0">
                <img src={selectedCountry.flag_url} alt={selectedCountry.name_en || selectedCountry.name} className="w-full h-full object-cover" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900">{selectedCountry.name_en || selectedCountry.name} eSIM</h3>
                <p className="text-xs text-slate-500">Available 4G / 5G data bundles</p>
              </div>
            </div>

            {loading ? (
              <ProductListSkeleton />
            ) : (
              <div className="space-y-3 max-h-[60vh] overflow-y-auto pe-1">
                {products.map((p) => (
                  <div key={p.id} className="glass-card rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <div className="text-base font-bold text-slate-900">{p.is_unlimited ? "Unlimited Data" : `${p.data_amount_gb} GB Data`}</div>
                      <div className="text-xs text-slate-500">{p.validity_days} Days Validity &bull; 4G/5G Speed</div>
                    </div>
                    <div className="text-end">
                      <div className="text-lg font-black text-emerald-600">{formatPrice(parseFloat(p.retail_price))}</div>
                      <div className="mt-1 flex flex-col items-end gap-1">
                        {/* Busy state belongs to the pack that was clicked -
                            a single shared flag turned every button on the
                            list into "Processing...". */}
                        <button
                          onClick={() => openPurchase(p, "wallet")}
                          disabled={flow?.stage === "working"}
                          className="bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-semibold px-3 py-1.5 rounded-lg shadow-sm transition-all"
                        >
                          {flow?.stage === "working" && flow.product?.id === p.id ? "Processing..." : "Buy with Wallet"}
                        </button>
                        <button
                          onClick={() => openPurchase(p, "gateway")}
                          disabled={flow?.stage === "working"}
                          className="text-[11px] text-slate-500 hover:text-slate-700 disabled:opacity-50 underline underline-offset-2"
                        >
                          Pay by Card / Mobile Banking
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Purchase flow: confirm -> working -> success / error */}
      {flow && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="glass-panel rounded-2xl max-w-md w-full p-6 border border-gray-200 shadow-xl">

            {flow.stage === "confirm" && (
              <>
                <h3 className="text-lg font-bold text-slate-900 mb-1">Confirm your purchase</h3>
                <p className="text-xs text-slate-500 mb-4">
                  {selectedCountry?.name_en || selectedCountry?.name} &bull; {flow.product.is_unlimited ? "Unlimited data" : `${flow.product.data_amount_gb} GB`} &bull; {flow.product.validity_days} days
                </p>
                <div className="rounded-xl border border-gray-200 divide-y divide-gray-100 text-xs mb-4">
                  <div className="flex items-center justify-between px-3 py-2.5">
                    <span className="text-slate-500">Price</span>
                    <span className="font-bold text-slate-900">{formatPrice(parseFloat(flow.product.retail_price))}</span>
                  </div>
                  <div className="flex items-center justify-between px-3 py-2.5">
                    <span className="text-slate-500">Payment</span>
                    <span className="text-slate-900">{flow.method === "wallet" ? "Wallet balance" : "Card / Mobile Banking"}</span>
                  </div>
                  {flow.method === "wallet" && walletBalance !== null && (
                    <div className="flex items-center justify-between px-3 py-2.5">
                      <span className="text-slate-500">Balance after</span>
                      <span className={walletBalance - parseFloat(flow.product.retail_price) < 0 ? "font-bold text-rose-600" : "text-slate-900"}>
                        {formatPrice(walletBalance - parseFloat(flow.product.retail_price))}
                      </span>
                    </div>
                  )}
                </div>
                {flow.method === "wallet" && walletBalance !== null && walletBalance < parseFloat(flow.product.retail_price) && (
                  <p className="text-xs text-rose-600 mb-3">
                    Your wallet balance is too low for this plan. Top up first, or pay by card.
                  </p>
                )}
                <div className="flex gap-3">
                  <button onClick={() => setFlow(null)} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">
                    Cancel
                  </button>
                  <button onClick={confirmPurchase} className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold">
                    {flow.method === "wallet" ? "Confirm & Pay" : "Continue to payment"}
                  </button>
                </div>
              </>
            )}

            {flow.stage === "working" && (
              <div className="text-center py-2">
                <div className="w-14 h-14 rounded-full border-4 border-brand-100 border-t-brand-600 animate-spin mx-auto mb-5" />
                <h3 className="text-lg font-bold text-slate-900">Setting up your eSIM</h3>
                <p className="text-xs text-slate-500 mt-1 mb-5">This usually takes 10&ndash;20 seconds. Please keep this window open.</p>
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
                      {install.ios && (
                        <a href={install.ios} className="flex-1 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold">
                          Install on iPhone
                        </a>
                      )}
                      {install.android && (
                        <a href={install.android} className="flex-1 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-bold">
                          Install on Android
                        </a>
                      )}
                    </div>
                  );
                })()}
                <p className="text-[11px] text-slate-500 mb-4">
                  Tap on the phone that will use the eSIM, or scan the QR code from another device.
                </p>

                <div className="flex gap-3">
                  <button onClick={() => setFlow(null)} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">
                    Close
                  </button>
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
                  <button onClick={() => setFlow(null)} className="flex-1 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold">
                    Close
                  </button>
                  <button
                    onClick={() => setFlow({ stage: "confirm", product: flow.product, method: flow.method })}
                    className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold"
                  >
                    Try again
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
