"use client";

import React, { useEffect, useState } from "react";
import { CreditCard, Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react";
import { api } from "@/lib/api";

export type PaymentMethod = {
  id?: string | null;
  name: string;
  kind: "mobile" | "bank" | "qr";
  account_name?: string | null;
  account_number?: string | null;
  branch?: string | null;
  instructions?: string | null;
  is_active: boolean;
};

const KIND_LABELS: Record<PaymentMethod["kind"], string> = {
  mobile: "Mobile banking (bKash, Nagad, Rocket…)",
  bank: "Bank account",
  qr: "QR code (uses the Bangla QR image above)",
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";

export default function PaymentMethodsCard({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api
      .getAdminPaymentMethods(token)
      .then((res: { methods: PaymentMethod[] }) => setMethods(res.methods))
      .catch((err: any) => setNotice({ kind: "error", text: err.message || "Couldn't load payment methods" }))
      .finally(() => setLoaded(true));
  }, []);

  const change = (next: PaymentMethod[]) => {
    setMethods(next);
    setDirty(true);
    setNotice(null);
  };
  const update = (i: number, patch: Partial<PaymentMethod>) => change(methods.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= methods.length) return;
    const next = [...methods];
    [next[i], next[j]] = [next[j], next[i]];
    change(next);
  };

  const save = async () => {
    const token = getToken();
    if (!token) return;
    if (methods.some((m) => !m.name.trim())) {
      setNotice({ kind: "error", text: "Every method needs a name." });
      return;
    }
    setSaving(true);
    try {
      const res = await api.updateAdminPaymentMethods(token, methods);
      setMethods(res.methods);
      setDirty(false);
      setNotice({ kind: "ok", text: "Saved — the wallet page shows these right away." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save payment methods" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <CreditCard className="w-4 h-4 text-admin-600" /> Manual deposit accounts
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            The bKash / Nagad / bank / QR accounts customers send money to before submitting a transaction ID on the wallet
            page. Only active methods are shown, and a deposit must name one of them. Order here is the order customers see.
          </p>
        </div>
        {isSuperAdmin && (
          <button
            type="button"
            onClick={() => change([...methods, { name: "", kind: "mobile", is_active: true }])}
            disabled={methods.length >= 20}
            className="flex items-center gap-1.5 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg border border-gray-200"
          >
            <Plus className="w-3.5 h-3.5" /> Add method
          </button>
        )}
      </div>

      {loaded && methods.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-xs text-slate-500">
          No deposit accounts yet — customers can only top up through the instant gateway until you add one.
        </div>
      )}

      <div className="space-y-3">
        {methods.map((m, i) => (
          <fieldset
            key={i}
            disabled={!isSuperAdmin}
            className={`rounded-xl border p-4 ${m.is_active ? "border-gray-200 bg-white" : "border-gray-200 bg-gray-50 opacity-75"}`}
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-[11px] text-slate-700 font-semibold block mb-1">Name shown to customers</label>
                <input className={inputCls} value={m.name} maxLength={60} placeholder="e.g. bKash Merchant" onChange={(e) => update(i, { name: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] text-slate-700 font-semibold block mb-1">Type</label>
                <select className={inputCls} value={m.kind} onChange={(e) => update(i, { kind: e.target.value as PaymentMethod["kind"] })}>
                  {Object.entries(KIND_LABELS).map(([k, label]) => (
                    <option key={k} value={k}>{label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-slate-700 font-semibold block mb-1">Account name</label>
                <input className={inputCls} value={m.account_name || ""} maxLength={100} placeholder="e.g. Triptel Ltd" onChange={(e) => update(i, { account_name: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] text-slate-700 font-semibold block mb-1">{m.kind === "bank" ? "Account number" : "Account / wallet number"}</label>
                <input className={`${inputCls} font-mono`} value={m.account_number || ""} maxLength={60} placeholder={m.kind === "bank" ? "e.g. 1234 5678 9012" : "e.g. 01XXX-XXXXXX"} onChange={(e) => update(i, { account_number: e.target.value })} />
              </div>
              {m.kind === "bank" && (
                <div>
                  <label className="text-[11px] text-slate-700 font-semibold block mb-1">Branch / routing</label>
                  <input className={inputCls} value={m.branch || ""} maxLength={100} placeholder="e.g. Gulshan branch, routing 225261726" onChange={(e) => update(i, { branch: e.target.value })} />
                </div>
              )}
              <div className={m.kind === "bank" ? "" : "md:col-span-2"}>
                <label className="text-[11px] text-slate-700 font-semibold block mb-1">Instructions (optional)</label>
                <input className={inputCls} value={m.instructions || ""} maxLength={500} placeholder='e.g. Use "Send Money" and put your email in the reference' onChange={(e) => update(i, { instructions: e.target.value })} />
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 mt-3">
              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input type="checkbox" checked={m.is_active} onChange={(e) => update(i, { is_active: e.target.checked })} className="w-4 h-4 accent-admin-500" />
                Active — shown on the wallet page
              </label>
              {isSuperAdmin && (
                <div className="flex items-center gap-1">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className="p-1.5 rounded-md text-slate-500 hover:bg-gray-100 disabled:opacity-30" aria-label="Move up">
                    <ArrowUp className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === methods.length - 1} className="p-1.5 rounded-md text-slate-500 hover:bg-gray-100 disabled:opacity-30" aria-label="Move down">
                    <ArrowDown className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" onClick={() => change(methods.filter((_, j) => j !== i))} className="flex items-center gap-1 px-2 py-1.5 rounded-md text-rose-600 hover:bg-rose-50 text-[11px] font-semibold">
                    <Trash2 className="w-3.5 h-3.5" /> Remove
                  </button>
                </div>
              )}
            </div>
          </fieldset>
        ))}
      </div>

      {isSuperAdmin && (
        <div className="flex flex-wrap items-center gap-3 mt-4">
          <button
            type="button"
            onClick={save}
            disabled={!dirty || saving}
            className="bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
          >
            {saving ? "Saving…" : "Save deposit accounts"}
          </button>
          {dirty && !saving && <span className="text-[11px] text-amber-600">Unsaved changes</span>}
        </div>
      )}
      {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}
    </div>
  );
}
