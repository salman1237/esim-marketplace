"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Search, Sparkles, Zap, ShieldCheck, Globe, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";

// Clicking a country opens its own page (/explore/bangladesh) rather than a
// popup, so the link can be shared with a customer directly.
function destinationHref(country: any): string {
  return `/explore/${country.slug || String(country.iso2 || "").toLowerCase()}`;
}

export default function HomePage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [countries, setCountries] = useState<any[]>([]);

  // Default popular destinations, used only if the catalog API is unreachable.
  const defaultPopular = [
    { iso2: "US", name: "United States" },
    { iso2: "TH", name: "Thailand" },
    { iso2: "JP", name: "Japan" },
    { iso2: "SA", name: "Saudi Arabia" },
    { iso2: "AE", name: "United Arab Emirates" },
    { iso2: "GB", name: "United Kingdom" },
    { iso2: "TR", name: "Turkey" },
    { iso2: "BD", name: "Bangladesh" },
  ];

  useEffect(() => {
    const fallback = () =>
      setCountries(
        defaultPopular.map((d, i) => ({
          id: i + 1,
          iso2: d.iso2,
          name_en: d.name,
          slug: d.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
          flag_url: `https://flagcdn.com/w80/${d.iso2.toLowerCase()}.png`,
        }))
      );
    api
      .getCountries(undefined, true)
      .then((data) => (data && data.length > 0 ? setCountries(data) : fallback()))
      .catch(fallback);
  }, []);

  // Full-catalog autocomplete: the popular grid only holds ~10 countries, so
  // filtering it client-side silently found nothing for the other 200+.
  useEffect(() => {
    const term = search.trim();
    if (!term) {
      setSearchResults([]);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    const handle = setTimeout(() => {
      api
        .getCountries(term)
        .then((data) => setSearchResults(data || []))
        .catch(() => setSearchResults([]))
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [search]);

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
          High-speed 4G &amp; 5G international data. Install directly in settings with a single QR code scan. Instant digital delivery.
        </p>

        {/* Live Search Bar */}
        <div className="mt-8 max-w-xl mx-auto relative">
          <div className="glass-panel rounded-2xl p-2 flex items-center shadow-lg shadow-brand-900/5">
            <Search className="w-5 h-5 text-slate-400 ms-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && searchResults.length > 0) router.push(destinationHref(searchResults[0]));
              }}
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
                <p className="px-4 py-3 text-xs text-slate-500">No destinations match &ldquo;{search}&rdquo;</p>
              ) : (
                searchResults.map((c) => (
                  <Link
                    key={c.id ?? c.iso2}
                    href={destinationHref(c)}
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
                  </Link>
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
          <Link
            href="/destinations"
            className="text-xs font-bold text-brand-600 hover:text-brand-700 flex items-center gap-1 shrink-0"
          >
            View all destinations <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-4">
          {countries.map((country) => (
            <Link
              key={country.iso2}
              href={destinationHref(country)}
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
            </Link>
          ))}
        </div>
      </section>

    </div>
  );
}
