"use client";

import React, { useEffect, useState } from "react";
import { Percent } from "lucide-react";
import { api } from "@/lib/api";

type Props = {
  isSuperAdmin: boolean;
  // Called after prices change, so the catalog table can reload.
  onRepriced: () => void;
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const EXAMPLE_COSTS = [1, 5, 10];

export default function PricingCard({ isSuperAdmin, onRepriced }: Props) {
  const [pricing, setPricing] = useState<any | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const data = await api.getAdminPricing(token);
      setPricing(data);
      setDraft(String(Number(data.selling_profit_pct)));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load pricing" });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const pct = Number(draft);
  const isValid = draft.trim() !== "" && Number.isFinite(pct) && pct >= 0 && pct <= 1000;
  const current = pricing ? Number(pricing.selling_profit_pct) : null;
  const changed = isValid && current !== null && pct !== current;
  const shownPct = isValid ? pct : current ?? 0;
  const sellingFor = (cost: number) => (cost * (1 + shownPct / 100)).toFixed(2);

  const save = async () => {
    const token = getToken();
    if (!token || !pricing || !isValid) return;
    const ok = window.confirm(
      `Set the selling profit to ${pct}%?\n\nThe selling price of all ${pricing.product_count} products will be recalculated immediately (VivaPe cost × ${(1 + pct / 100).toFixed(2)}). Orders already placed keep their price.`
    );
    if (!ok) return;

    setSaving(true);
    setNotice(null);
    try {
      const res = await api.updateAdminPricing(token, draft.trim());
      setNotice({ kind: "ok", text: `Done — ${res.products_repriced} products now sell at ${Number(res.selling_profit_pct)}% profit.` });
      await load();
      onRepriced();
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't update the selling profit" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <div className="flex flex-col lg:flex-row lg:items-start gap-6">
        <div className="flex-1">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Percent className="w-4 h-4 text-admin-600" /> Selling profit
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-xl">
            One flat profit on top of VivaPe&apos;s cost for every package: <strong>selling price = cost × (1 + profit %)</strong>.
            Changing it reprices the whole catalog at once, and every catalog sync uses it. Merchant commission is paid out of
            this profit — it never changes what the customer pays.
          </p>

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Profit %</label>
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  max={1000}
                  step="0.01"
                  value={draft}
                  disabled={!isSuperAdmin || !pricing}
                  onChange={(e) => setDraft(e.target.value)}
                  className="w-28 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-bold text-slate-900 disabled:bg-gray-50"
                />
                <span className="text-sm font-bold text-slate-500">%</span>
              </div>
            </div>
            {isSuperAdmin ? (
              <button
                onClick={save}
                disabled={!changed || saving}
                className="bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-lg"
              >
                {saving ? "Repricing…" : "Save & reprice catalog"}
              </button>
            ) : (
              <span className="text-[11px] text-slate-500 pb-2">Only a Super Admin can change this.</span>
            )}
          </div>
          {!isValid && draft.trim() !== "" && <p className="text-[11px] text-rose-600 mt-2">Enter a profit between 0 and 1000%.</p>}
          {notice && (
            <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
          )}
        </div>

        <div className="lg:w-72 rounded-xl bg-gray-50 border border-gray-200 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
            At {shownPct}% profit
          </div>
          <table className="w-full text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="text-start font-medium pb-1">VivaPe cost</th>
                <th className="text-end font-medium pb-1">Selling price</th>
                <th className="text-end font-medium pb-1">Profit</th>
              </tr>
            </thead>
            <tbody>
              {EXAMPLE_COSTS.map((cost) => (
                <tr key={cost}>
                  <td className="py-1 font-mono text-slate-700">€{cost.toFixed(2)}</td>
                  <td className="py-1 text-end font-mono font-bold text-slate-900">€{sellingFor(cost)}</td>
                  <td className="py-1 text-end font-mono text-emerald-600">€{(Number(sellingFor(cost)) - cost).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pricing && <p className="text-[11px] text-slate-500 mt-2">{pricing.product_count} products in the catalog.</p>}
        </div>
      </div>
    </div>
  );
}
