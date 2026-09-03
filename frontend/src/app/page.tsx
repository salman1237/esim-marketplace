"use client";

import React, { useState, useEffect } from "react";
import { Search, Zap, ShieldCheck, Globe, ArrowRight, CheckCircle2, Sparkles, Check, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function HomePage() {
  const { formatPrice } = useAppSettings();
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [countries, setCountries] = useState<any[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<any | null>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [purchasing, setPurchasing] = useState(false);
  const [purchaseSuccess, setPurchaseSuccess] = useState<any | null>(null);

  // Default popular destinations
  const defaultPopular = [
    { iso2: "US", name: "United States", flag: "🇺🇸", minPrice: "$4.50" },
    { iso2: "TH", name: "Thailand", flag: "🇹🇭", minPrice: "$3.90" },
    { iso2: "JP", name: "Japan", flag: "🇯🇵", minPrice: "$4.90" },
    { iso2: "SA", name: "Saudi Arabia", flag: "🇸🇦", minPrice: "$6.00" },
    { iso2: "AE", name: "United Arab Emirates", flag: "🇦🇪", minPrice: "$5.50" },
    { iso2: "GB", name: "United Kingdom", flag: "🇬🇧", minPrice: "$4.50" },
    { iso2: "TR", name: "Turkey", flag: "🇹🇷", minPrice: "$3.50" },
    { iso2: "BD", name: "Bangladesh", flag: "🇧🇩", minPrice: "$2.90" },
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
        { id: "pkg_1", title_en: `${c.name_en || c.name} 1 GB`, data_amount_gb: 1.0, validity_days: 7, retail_price: 4.50, currency: "USD" },
        { id: "pkg_2", title_en: `${c.name_en || c.name} 3 GB`, data_amount_gb: 3.0, validity_days: 15, retail_price: 9.00, currency: "USD" },
        { id: "pkg_3", title_en: `${c.name_en || c.name} 5 GB`, data_amount_gb: 5.0, validity_days: 30, retail_price: 13.50, currency: "USD" },
        { id: "pkg_4", title_en: `${c.name_en || c.name} 10 GB`, data_amount_gb: 10.0, validity_days: 30, retail_price: 22.00, currency: "USD" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleBuy = async (product: any) => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }

    setPurchasing(true);
    try {
      const order = await api.checkout(token, {
        product_id: product.id,
        payment_method: "WALLET",
        is_buy_for_user: false
      });
      setPurchaseSuccess(order);
    } catch (err: any) {
      alert(err.message || "Failed to purchase. Please check your wallet balance.");
    } finally {
      setPurchasing(false);
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
        <div className="inline-flex items-center space-x-2 bg-brand-500/10 border border-brand-500/20 text-brand-300 text-xs font-semibold px-3 py-1.5 rounded-full mb-6">
          <Sparkles className="w-3.5 h-3.5 text-accent-400" />
          <span>Next-Gen Travel Connectivity &bull; 200+ Destinations</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-white leading-tight">
          Stay Connected Worldwide <br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-400 via-accent-400 to-indigo-300">
            Without Roaming Fees
          </span>
        </h1>

        <p className="mt-4 text-base sm:text-lg text-slate-400 max-w-2xl mx-auto">
          High-speed 4G & 5G international data. Install directly in settings with a single QR code scan. Instant digital delivery.
        </p>

        {/* Live Search Bar */}
        <div className="mt-8 max-w-xl mx-auto relative">
          <div className="glass-panel rounded-2xl p-2 flex items-center shadow-2xl shadow-brand-900/20">
            <Search className="w-5 h-5 text-slate-400 ms-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Where are you traveling? (e.g. Thailand, USA, Japan)..."
              className="bg-transparent border-none focus:outline-none w-full px-3 py-2 text-sm text-white placeholder-slate-500"
              autoComplete="off"
            />
          </div>

          {search.trim() && (
            <div className="absolute top-full inset-x-0 mt-2 glass-panel rounded-2xl shadow-2xl border border-white/10 max-h-80 overflow-y-auto text-start z-40">
              {searchLoading ? (
                <p className="px-4 py-3 text-xs text-slate-400">Searching...</p>
              ) : searchResults.length === 0 ? (
                <p className="px-4 py-3 text-xs text-slate-400">No destinations match "{search}"</p>
              ) : (
                searchResults.map((c) => (
                  <button
                    key={c.id ?? c.iso2}
                    onClick={() => handleSelectSearchResult(c)}
                    className="w-full flex items-center space-x-3 px-4 py-2.5 hover:bg-white/5 text-start"
                  >
                    <div className="w-7 h-5 rounded overflow-hidden shrink-0 border border-white/10 bg-slate-800 flex items-center justify-center">
                      {c.flag_url ? (
                        <img src={c.flag_url} alt={c.name_en || c.name} className="w-full h-full object-cover" />
                      ) : (
                        <span className="text-xs">🌍</span>
                      )}
                    </div>
                    <span className="text-sm text-white">{c.name_en || c.name}</span>
                    <span className="text-[10px] text-slate-500 ms-auto">{c.iso2}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Value Props */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-6 text-xs text-slate-400 font-medium">
          <div className="flex items-center space-x-2"><Zap className="w-4 h-4 text-amber-400" /><span>Instant QR Delivery</span></div>
          <div className="flex items-center space-x-2"><ShieldCheck className="w-4 h-4 text-emerald-400" /><span>Official Carrier Partners</span></div>
          <div className="flex items-center space-x-2"><Globe className="w-4 h-4 text-cyan-400" /><span>200+ Countries Covered</span></div>
        </div>
      </section>

      {/* Destinations Grid */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-bold text-white">Popular Destinations</h2>
            <p className="text-xs text-slate-400 mt-1">Select a country to browse high-speed data bundles</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-4">
          {countries.map((country) => (
            <button
              key={country.iso2}
              onClick={() => handleSelectCountry(country)}
              className="glass-card rounded-xl p-4 text-start flex items-center space-x-3.5 hover:border-brand-500/50 group"
            >
              <div className="w-10 h-7 rounded overflow-hidden shadow shrink-0 border border-white/10 flex items-center justify-center bg-slate-800 text-xl">
                {country.flag_url ? (
                  <img src={country.flag_url} alt={country.name_en || country.name} className="w-full h-full object-cover" />
                ) : (
                  <span>🌍</span>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-white group-hover:text-brand-300 truncate transition-colors">
                  {country.name_en || country.name}
                </h3>
                <span className="text-[11px] text-slate-400 flex items-center space-x-1">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="glass-panel rounded-2xl max-w-lg w-full p-6 relative border border-white/20 shadow-2xl">
            <button
              onClick={() => setSelectedCountry(null)}
              aria-label="Close"
              className="absolute top-4 end-4 p-1 rounded-lg text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center space-x-3 mb-6">
              <div className="w-10 h-7 rounded overflow-hidden shadow border border-white/10 shrink-0">
                <img src={selectedCountry.flag_url} alt={selectedCountry.name_en || selectedCountry.name} className="w-full h-full object-cover" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">{selectedCountry.name_en || selectedCountry.name} eSIM</h3>
                <p className="text-xs text-slate-400">Available 4G / 5G data bundles</p>
              </div>
            </div>

            {loading ? (
              <div className="py-12 text-center text-sm text-slate-400">Loading data packages...</div>
            ) : (
              <div className="space-y-3 max-h-[60vh] overflow-y-auto pe-1">
                {products.map((p) => (
                  <div key={p.id} className="glass-card rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <div className="text-base font-bold text-white">{p.data_amount_gb} GB Data</div>
                      <div className="text-xs text-slate-400">{p.validity_days} Days Validity &bull; 4G/5G Speed</div>
                    </div>
                    <div className="text-end">
                      <div className="text-lg font-black text-emerald-400">{formatPrice(parseFloat(p.retail_price))}</div>
                      <button
                        onClick={() => handleBuy(p)}
                        disabled={purchasing}
                        className="mt-1 bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-all"
                      >
                        {purchasing ? "Processing..." : "Buy Now"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Purchase Success Modal */}
      {purchaseSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
          <div className="glass-panel rounded-2xl max-w-md w-full p-6 text-center border border-emerald-500/30">
            <div className="w-14 h-14 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-xl font-bold text-white">eSIM Provisioned Successfully!</h3>
            <p className="text-xs text-slate-400 mt-1 mb-6">
              Order #{purchaseSuccess.order_no} has been completed. Your eSIM is ready to install.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setPurchaseSuccess(null)}
                className="flex-1 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs font-semibold"
              >
                Close
              </button>
              <a
                href="/my-esims"
                className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold flex items-center justify-center space-x-1"
              >
                <span>View QR Code</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
