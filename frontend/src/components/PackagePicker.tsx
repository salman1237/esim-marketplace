"use client";

import React, { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import { usePackageFilters, PackageFilterChips } from "@/components/explore/PackageFilters";

export const packLabel = (p: any) => (p?.is_unlimited ? "Unlimited" : `${Number(p?.data_amount_gb)} GB`);

type Props = {
  countries: any[];
  formatPrice: (amount: number) => string;
  onChange: (selection: { country: any | null; product: any | null }) => void;
  id?: string;
};

// Searchable country + filterable package list for "buy an eSIM for a
// customer" - used by the merchant dashboard and the admin console, so both
// see the whole catalogue with the same Data / Days filters as the
// storefront.
export default function PackagePicker({ countries, formatPrice, onChange, id = "package-picker" }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [country, setCountry] = useState<any | null>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [productId, setProductId] = useState("");
  const filters = usePackageFilters(products);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle || (country && query === country.name_en)) return countries;
    return countries.filter(
      (c) => (c.name_en || "").toLowerCase().includes(needle) || (c.iso2 || "").toLowerCase() === needle
    );
  }, [countries, query, country]);

  const chooseCountry = (c: any) => {
    setCountry(c);
    setQuery(c.name_en);
    setOpen(false);
    setProductId("");
    filters.reset();
    onChange({ country: c, product: null });
    setLoading(true);
    api
      .getCountryProducts(c.iso2)
      .then(setProducts)
      .catch(() => setProducts([]))
      .finally(() => setLoading(false));
  };

  const chooseProduct = (p: any) => {
    setProductId(p.id);
    onChange({ country, product: p });
  };

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor={id} className="text-xs text-slate-700 font-semibold block mb-1">
          Destination Country {countries.length > 0 && <span className="font-normal text-slate-400">· {countries.length} available</span>}
        </label>
        <div className="relative">
          <div className="flex items-center gap-2 bg-white border border-gray-300 rounded-xl px-3 focus-within:border-brand-500">
            {country?.flag_url && query === country.name_en ? (
              <img src={country.flag_url} alt="" className="w-6 h-4 rounded-sm object-cover shrink-0" />
            ) : (
              <Search className="w-4 h-4 text-slate-400 shrink-0" />
            )}
            <input
              id={id}
              value={query}
              onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
              onFocus={() => setOpen(true)}
              onBlur={() => setOpen(false)}
              placeholder="Search a country…"
              autoComplete="off"
              className="flex-1 py-2.5 text-xs text-slate-900 bg-transparent outline-none"
            />
          </div>
          {open && (
            <div className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto bg-white border border-gray-200 rounded-xl shadow-lg">
              {matches.length === 0 ? (
                <p className="px-3 py-3 text-xs text-slate-500">No country matches &ldquo;{query}&rdquo;</p>
              ) : (
                matches.map((c) => (
                  <button
                    key={c.iso2}
                    type="button"
                    // mousedown fires before the input's blur closes the list
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => chooseCountry(c)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-start hover:bg-gray-50 ${country?.iso2 === c.iso2 ? "bg-brand-50" : ""}`}
                  >
                    {c.flag_url ? <img src={c.flag_url} alt="" className="w-6 h-4 rounded-sm object-cover shrink-0" /> : <span className="w-6 shrink-0" />}
                    <span className="text-xs text-slate-900 flex-1">{c.name_en}</span>
                    <span className="text-[10px] text-slate-400">{c.iso2}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {country && (
        <div className="space-y-3">
          <span className="text-xs text-slate-700 font-semibold block">eSIM Package</span>
          {loading ? (
            <div className="h-24 rounded-xl bg-gray-50 animate-pulse" />
          ) : products.length === 0 ? (
            <p className="text-xs text-slate-500">No packages available for {country.name_en} right now.</p>
          ) : (
            <>
              <PackageFilterChips filters={filters} className="rounded-xl bg-gray-50 border border-gray-200 p-3" />
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span>{filters.filtered.length} of {products.length} packages</span>
                {filters.active && (
                  <button type="button" onClick={filters.reset} className="text-brand-600 hover:underline">Clear filters</button>
                )}
              </div>
              <div role="radiogroup" aria-label="eSIM package" className="max-h-72 overflow-y-auto space-y-2 pe-1">
                {filters.filtered.length === 0 ? (
                  <p className="text-xs text-slate-500 py-4 text-center">No package matches these filters.</p>
                ) : (
                  filters.filtered.map((p) => {
                    const selected = p.id === productId;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => chooseProduct(p)}
                        className={`w-full flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-start transition-colors ${
                          selected ? "border-brand-500 bg-brand-50" : "border-gray-200 bg-white hover:border-gray-300"
                        }`}
                      >
                        <span className="flex items-center gap-2.5">
                          <span className={`w-4 h-4 rounded-full border-2 shrink-0 ${selected ? "border-brand-600 bg-brand-600 ring-2 ring-white ring-inset" : "border-gray-300"}`} />
                          <span>
                            <span className="block text-sm font-bold text-slate-900">{packLabel(p)}</span>
                            <span className="block text-[11px] text-slate-500">{p.validity_days} days</span>
                          </span>
                        </span>
                        <span className="text-sm font-black text-emerald-600">{formatPrice(parseFloat(p.retail_price))}</span>
                      </button>
                    );
                  })
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
