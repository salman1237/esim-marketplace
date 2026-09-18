"use client";

import React, { useMemo, useState } from "react";

// The filter chips customers asked for. A value only appears if the
// current list actually has something matching it. Shared by the public
// country page and the merchant dashboard so the two can't drift apart.
export const DAY_CHOICES = [1, 3, 5, 7, 10, 15, 30];
export const GB_CHOICES = [1, 2, 3, 5, 10, 15, 20, 30];

type Filterable = { validity_days: number; data_amount_gb: string | number; is_unlimited: boolean };

export type PackageFiltersState<T> = {
  days: number | null;
  setDays: (d: number | null) => void;
  gb: number | "unlimited" | null;
  setGb: (g: number | "unlimited" | null) => void;
  availableDays: number[];
  availableGb: number[];
  hasUnlimited: boolean;
  filtered: T[];
  active: boolean;
  reset: () => void;
};

export function usePackageFilters<T extends Filterable>(products: T[]): PackageFiltersState<T> {
  const [days, setDays] = useState<number | null>(null);
  const [gb, setGb] = useState<number | "unlimited" | null>(null);

  const availableDays = useMemo(
    () => DAY_CHOICES.filter((d) => products.some((p) => p.validity_days === d)),
    [products]
  );
  const availableGb = useMemo(
    () => GB_CHOICES.filter((g) => products.some((p) => !p.is_unlimited && Number(p.data_amount_gb) === g)),
    [products]
  );
  const hasUnlimited = useMemo(() => products.some((p) => p.is_unlimited), [products]);

  const filtered = useMemo(
    () =>
      products.filter((p) => {
        if (days !== null && p.validity_days !== days) return false;
        if (gb === "unlimited") return p.is_unlimited;
        if (gb !== null) return !p.is_unlimited && Number(p.data_amount_gb) === gb;
        return true;
      }),
    [products, days, gb]
  );

  return {
    days, setDays, gb, setGb, availableDays, availableGb, hasUnlimited, filtered,
    active: days !== null || gb !== null,
    reset: () => { setDays(null); setGb(null); },
  };
}

const chip = (active: boolean) =>
  `px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${
    active ? "bg-brand-600 border-brand-600 text-white" : "bg-white border-gray-300 text-slate-700 hover:bg-gray-50"
  }`;

export function PackageFilterChips<T>({ filters, className = "" }: { filters: PackageFiltersState<T>; className?: string }) {
  const { days, setDays, gb, setGb, availableDays, availableGb, hasUnlimited } = filters;
  if (availableDays.length === 0 && availableGb.length === 0 && !hasUnlimited) return null;
  return (
    <div className={`space-y-3 ${className}`}>
      {(availableGb.length > 0 || hasUnlimited) && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 w-12">Data</span>
          <button type="button" onClick={() => setGb(null)} className={chip(gb === null)}>All</button>
          {availableGb.map((g) => (
            <button key={g} type="button" onClick={() => setGb(gb === g ? null : g)} className={chip(gb === g)}>{g} GB</button>
          ))}
          {hasUnlimited && (
            <button type="button" onClick={() => setGb(gb === "unlimited" ? null : "unlimited")} className={chip(gb === "unlimited")}>Unlimited</button>
          )}
        </div>
      )}
      {availableDays.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 w-12">Days</span>
          <button type="button" onClick={() => setDays(null)} className={chip(days === null)}>All</button>
          {availableDays.map((d) => (
            <button key={d} type="button" onClick={() => setDays(days === d ? null : d)} className={chip(days === d)}>{d} {d === 1 ? "day" : "days"}</button>
          ))}
        </div>
      )}
    </div>
  );
}
