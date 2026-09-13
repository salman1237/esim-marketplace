"use client";

import React, { useEffect, useState } from "react";
import { Percent, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

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
const priceAt = (cost: number, pct: number) => (cost * (1 + pct / 100)).toFixed(2);

export default function PricingCard({ isSuperAdmin, onRepriced }: Props) {
  const [pricing, setPricing] = useState<any | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
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

  const reprice = async () => {
    const token = getToken();
    if (!token || !isValid) return;
    setSaving(true);
    setNotice(null);
    try {
      const res = await api.updateAdminPricing(token, draft.trim());
      setNotice({ kind: "ok", text: `Done — ${res.products_repriced} products now sell at ${Number(res.selling_profit_pct)}% profit.` });
      setConfirmOpen(false);
      await load();
      onRepriced();
    } catch (err: any) {
      setConfirmOpen(false);
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
                onClick={() => setConfirmOpen(true)}
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
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">At {shownPct}% profit</div>
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
                  <td className="py-1 text-end font-mono font-bold text-slate-900">€{priceAt(cost, shownPct)}</td>
                  <td className="py-1 text-end font-mono text-emerald-600">€{(Number(priceAt(cost, shownPct)) - cost).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pricing && <p className="text-[11px] text-slate-500 mt-2">{pricing.product_count} products in the catalog.</p>}
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen && isValid && current !== null}
        title="Reprice the whole catalog?"
        icon={<RefreshCw className="w-5 h-5" />}
        confirmLabel={`Reprice ${pricing?.product_count ?? ""} products`}
        busy={saving}
        onConfirm={reprice}
        onCancel={() => setConfirmOpen(false)}
      >
        <div className="flex items-center gap-3 rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
          <div className="text-center">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Now</div>
            <div className="text-xl font-black text-slate-500">{current}%</div>
          </div>
          <div className="flex-1 text-center text-slate-400 text-lg">→</div>
          <div className="text-center">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">New</div>
            <div className="text-xl font-black text-admin-600">{pct}%</div>
          </div>
        </div>

        <p>
          Every one of the <strong>{pricing?.product_count}</strong> products gets a new selling price right away:
          VivaPe cost × <strong>{(1 + pct / 100).toFixed(2)}</strong>.
        </p>

        <table className="w-full text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="text-start font-medium pb-1">VivaPe cost</th>
              <th className="text-end font-medium pb-1">Current price</th>
              <th className="text-end font-medium pb-1">New price</th>
            </tr>
          </thead>
          <tbody>
            {EXAMPLE_COSTS.map((cost) => (
              <tr key={cost} className="border-t border-gray-100">
                <td className="py-1.5 font-mono text-slate-700">€{cost.toFixed(2)}</td>
                <td className="py-1.5 text-end font-mono text-slate-500">€{priceAt(cost, current ?? 0)}</td>
                <td className="py-1.5 text-end font-mono font-bold text-slate-900">€{priceAt(cost, pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="text-xs text-slate-500">
          Orders already placed keep the price they were paid at. Catalog syncs will keep using {pct}%.
        </p>
      </ConfirmDialog>
    </div>
  );
}
