"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { api } from "@/lib/api";

// Every destination we actually sell, not the handful of popular tiles on
// the homepage - this is what the "Destinations" menu link needs to open.
export default function DestinationsPage() {
  const [countries, setCountries] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getCountries()
      .then((data) => setCountries(data || []))
      .catch(() => setError("Couldn't load destinations. Please refresh."))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return countries;
    return countries.filter(
      (c) => (c.name_en || "").toLowerCase().includes(needle) || (c.iso2 || "").toLowerCase().includes(needle)
    );
  }, [countries, query]);

  const grouped = useMemo(() => {
    const groups: Record<string, any[]> = {};
    for (const c of filtered) groups[c.region || "Other destinations"] = [...(groups[c.region || "Other destinations"] || []), c];
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <div>
        <h1 className="text-3xl font-extrabold text-slate-900">All destinations</h1>
        <p className="text-xs text-slate-500 mt-1">
          {loading ? "Loading…" : `${countries.length} countries with eSIM data available. Pick one to see its packages and prices.`}
        </p>
      </div>

      <div className="flex items-center gap-2 bg-white border border-gray-300 rounded-xl px-3 max-w-md">
        <Search className="w-4 h-4 text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a country…"
          className="flex-1 py-2.5 text-sm text-slate-900 bg-transparent outline-none"
        />
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {Array.from({ length: 12 }).map((_, i) => <div key={i} className="h-16 rounded-xl bg-gray-100 animate-pulse" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="glass-panel rounded-2xl border border-dashed border-gray-300 p-10 text-center">
          <p className="text-sm font-semibold text-slate-900">No destination matches &ldquo;{query}&rdquo;</p>
        </div>
      ) : (
        grouped.map(([region, items]) => (
          <section key={region} className="space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{region} · {items.length}</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {items.map((c) => (
                <Link
                  key={c.id}
                  href={`/explore/${c.slug || c.iso2.toLowerCase()}`}
                  className="glass-card rounded-xl p-3 border border-gray-200 hover:border-brand-300 hover:shadow-md transition-all flex items-center gap-3"
                >
                  {c.flag_url && (
                    <div className="w-9 h-6 rounded overflow-hidden border border-gray-200 shrink-0">
                      <img src={c.flag_url} alt={c.name_en} className="w-full h-full object-cover" />
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-900 truncate">{c.name_en}</div>
                    <div className="text-[10px] text-slate-400">{c.iso2}</div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
