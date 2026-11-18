"use client";

import React, { useEffect, useState } from "react";
import { ArrowLeft, Package, Receipt, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

type Selection = { kind: "order"; orderId: string } | { kind: "product"; productId: string };

/**
 * FR-C205: "A picker over the user's own orders / the catalog" - two tabs,
 * each reusing an existing fetch (api.getMyESIMs, api.getCountries/
 * getCountryProducts) rather than a new search endpoint.
 */
export default function SharePicker({
  onSelect,
  onClose,
}: {
  onSelect: (selection: Selection) => void;
  onClose: () => void;
}) {
  const { formatPrice } = useAppSettings();
  const [tab, setTab] = useState<"orders" | "catalog">("orders");
  const [esims, setEsims] = useState<any[] | null>(null);
  const [countries, setCountries] = useState<any[] | null>(null);
  const [countryQuery, setCountryQuery] = useState("");
  const [activeCountry, setActiveCountry] = useState<any | null>(null);
  const [products, setProducts] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (tab !== "orders" || esims) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    api.getMyESIMs(token).then(setEsims).catch((err: any) => setError(err.message || "Couldn't load your orders"));
  }, [tab, esims]);

  useEffect(() => {
    if (tab !== "catalog" || activeCountry) return;
    const handle = setTimeout(() => {
      api.getCountries(countryQuery || undefined)
        .then((data: any) => setCountries(Array.isArray(data) ? data : data?.countries || []))
        .catch((err: any) => setError(err.message || "Couldn't load destinations"));
    }, 250);
    return () => clearTimeout(handle);
  }, [tab, countryQuery, activeCountry]);

  const openCountry = async (country: any) => {
    setActiveCountry(country);
    setProducts(null);
    try {
      const data = await api.getCountryProducts(country.iso2);
      setProducts(data?.products || data || []);
    } catch (err: any) {
      setError(err.message || "Couldn't load packages for that destination");
    }
  };

  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-lg">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => { setTab("orders"); setActiveCountry(null); }}
            className={`text-[11px] font-bold px-2.5 py-1 rounded-lg ${tab === "orders" ? "bg-brand-50 text-brand-700" : "text-slate-500"}`}
          >
            Your orders
          </button>
          <button
            type="button"
            onClick={() => setTab("catalog")}
            className={`text-[11px] font-bold px-2.5 py-1 rounded-lg ${tab === "catalog" ? "bg-brand-50 text-brand-700" : "text-slate-500"}`}
          >
            Browse packages
          </button>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg hover:bg-gray-100 text-slate-400">
          <X className="w-4 h-4" />
        </button>
      </div>

      {error && <p className="px-3 pt-2 text-[11px] text-rose-600">{error}</p>}

      <div className="max-h-64 overflow-y-auto p-2">
        {tab === "orders" && (
          !esims ? (
            <div className="space-y-2 p-2">
              <div className="h-10 rounded-xl bg-gray-100 animate-pulse" />
              <div className="h-10 rounded-xl bg-gray-100 animate-pulse" />
            </div>
          ) : esims.length === 0 ? (
            <p className="text-[11px] text-slate-500 text-center py-6">You don&apos;t have any orders yet.</p>
          ) : (
            <ul className="space-y-1">
              {esims.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    onClick={() => onSelect({ kind: "order", orderId: e.order_id })}
                    className="w-full flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-gray-50 text-start"
                  >
                    <Receipt className="w-4 h-4 text-brand-500 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] font-bold text-slate-900 truncate">{e.product_title}</div>
                      <div className="text-[10px] text-slate-400 font-mono">{e.order_no}</div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )
        )}

        {tab === "catalog" && !activeCountry && (
          <div className="space-y-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                value={countryQuery}
                onChange={(e) => setCountryQuery(e.target.value)}
                placeholder="Search a destination…"
                className="w-full bg-gray-50 border border-gray-200 rounded-xl pl-8 pr-3 py-2 text-xs text-slate-900"
              />
            </div>
            {!countries ? (
              <div className="h-10 rounded-xl bg-gray-100 animate-pulse" />
            ) : (
              <ul className="space-y-1">
                {countries.map((c: any) => (
                  <li key={c.iso2 || c.id}>
                    <button
                      type="button"
                      onClick={() => openCountry(c)}
                      className="w-full flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-gray-50 text-start text-[11px] font-semibold text-slate-700"
                    >
                      {c.flag_url && <img src={c.flag_url} alt="" className="w-4 h-3 object-cover rounded-sm" />}
                      {c.name_en || c.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {tab === "catalog" && activeCountry && (
          <div>
            <button
              type="button"
              onClick={() => { setActiveCountry(null); setProducts(null); }}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-slate-900 mb-2"
            >
              <ArrowLeft className="w-3 h-3" /> {activeCountry.name_en || activeCountry.name}
            </button>
            {!products ? (
              <div className="h-10 rounded-xl bg-gray-100 animate-pulse" />
            ) : products.length === 0 ? (
              <p className="text-[11px] text-slate-500 text-center py-6">No packages for this destination.</p>
            ) : (
              <ul className="space-y-1">
                {products.map((p: any) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => onSelect({ kind: "product", productId: p.id })}
                      className="w-full flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-gray-50 text-start"
                    >
                      <Package className="w-4 h-4 text-brand-500 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-bold text-slate-900 truncate">{p.title_en}</div>
                        <div className="text-[10px] text-slate-400">
                          {p.is_unlimited ? "Unlimited" : `${Number(p.data_amount_gb)} GB`} · {p.validity_days} days
                        </div>
                      </div>
                      <div className="text-[11px] font-bold text-slate-700 shrink-0">
                        {formatPrice(Number(p.retail_price))}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
