"use client";

import React, { useEffect, useState } from "react";
import { Truck } from "lucide-react";
import { api } from "@/lib/api";

type Props = {
  isSuperAdmin: boolean;
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

// Shown only for Telna, since it is the one supplier whose default came
// from a specific finding rather than being on from the start - a plain
// admin reading this needs to know WHY it is off, not just that it is.
const TELNA_NOTE =
  "A live test purchase found most of Telna's catalog rejected by VivaPe's own provisioning endpoint - only a product literally named “Test” completed. Off by default until VivaPe confirms which Telna packages actually work.";

export default function SupplierVisibilityCard({ isSuperAdmin }: Props) {
  const [suppliers, setSuppliers] = useState<{ reference: string; label: string; enabled: boolean }[] | null>(null);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await api.getSupplierSettings(token);
      setSuppliers(res.suppliers);
      setDraft(Object.fromEntries(res.suppliers.map((s: any) => [s.reference, s.enabled])));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load supplier settings" });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const changed =
    !!suppliers && suppliers.some((s) => draft[s.reference] !== s.enabled);

  const save = async () => {
    const token = getToken();
    if (!token) return;
    setSaving(true);
    setNotice(null);
    try {
      const enabled = Object.entries(draft).filter(([, on]) => on).map(([ref]) => ref);
      const res = await api.updateSupplierSettings(token, enabled);
      setSuppliers(res.suppliers);
      setDraft(Object.fromEntries(res.suppliers.map((s: any) => [s.reference, s.enabled])));
      setNotice({ kind: "ok", text: "Saved. Customers and partners see the new selection immediately." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save supplier settings" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Truck className="w-4 h-4 text-admin-600" /> Suppliers shown to customers
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-2xl">
        VivaPe proxies more than one underlying wholesaler. Turning a supplier off hides its packages from the storefront
        and the Partner API — and blocks buying one directly by product id — immediately. Nothing is deleted or
        deactivated: every product is still here, still editable, the moment the supplier that sources it is switched
        back on.
        {!isSuperAdmin && " Only a Super Admin can change this."}
      </p>

      {!suppliers ? (
        <div className="mt-4 h-20 rounded-xl bg-gray-50 animate-pulse" />
      ) : (
        <div className="mt-4 flex flex-col gap-2 max-w-md">
          {suppliers.map((s) => (
            <label
              key={s.reference}
              className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
                draft[s.reference] ? "bg-emerald-50 border-emerald-200" : "bg-gray-50 border-gray-200"
              } ${isSuperAdmin ? "cursor-pointer" : "cursor-default"}`}
            >
              <input
                type="checkbox"
                checked={!!draft[s.reference]}
                disabled={!isSuperAdmin}
                onChange={(e) => setDraft((prev) => ({ ...prev, [s.reference]: e.target.checked }))}
                className="mt-0.5 w-4 h-4 accent-admin-600 disabled:opacity-60"
              />
              <div>
                <div className="text-sm font-bold text-slate-900">{s.label}</div>
                {s.reference === "telna_esim" && (
                  <p className="text-[11px] text-slate-500 mt-0.5 leading-snug">{TELNA_NOTE}</p>
                )}
              </div>
            </label>
          ))}
        </div>
      )}

      {isSuperAdmin && (
        <button
          onClick={save}
          disabled={!changed || saving}
          className="mt-4 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-lg"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      )}
      {notice && (
        <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
      )}
    </div>
  );
}
