"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  BadgePercent, Check, ChevronDown, Pencil, Plus, Power, Save, Trash2, Users, X,
} from "lucide-react";
import { api } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { formatDate } from "@/lib/datetime";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";
const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

type Discount = {
  id: string;
  code: string;
  description?: string | null;
  discount_type: "PERCENT" | "FIXED";
  value: string;
  max_discount_amount?: string | null;
  min_order_amount?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  max_uses?: number | null;
  max_uses_per_user?: number | null;
  first_order_only: boolean;
  scope: "ALL" | "COUNTRY" | "PRODUCT";
  country_id?: number | null;
  product_id?: string | null;
  is_active: boolean;
  times_used: number;
  discount_given: string;
  revenue: string;
};

type FormState = {
  code: string;
  description: string;
  discount_type: "PERCENT" | "FIXED";
  value: string;
  max_discount_amount: string;
  min_order_amount: string;
  starts_at: string;
  ends_at: string;
  max_uses: string;
  max_uses_per_user: string;
  first_order_only: boolean;
  scope: "ALL" | "COUNTRY" | "PRODUCT";
  country_id: string;
  is_active: boolean;
};

const EMPTY_FORM: FormState = {
  code: "", description: "", discount_type: "PERCENT", value: "10",
  max_discount_amount: "", min_order_amount: "", starts_at: "", ends_at: "",
  max_uses: "", max_uses_per_user: "1", first_order_only: false,
  scope: "ALL", country_id: "", is_active: true,
};

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:mm" with no zone; the
// API speaks ISO-8601 UTC. These two keep that conversion in one place.
function toLocalInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function formFrom(d: Discount): FormState {
  return {
    code: d.code,
    description: d.description || "",
    discount_type: d.discount_type,
    value: String(Number(d.value)),
    max_discount_amount: d.max_discount_amount ? String(Number(d.max_discount_amount)) : "",
    min_order_amount: d.min_order_amount ? String(Number(d.min_order_amount)) : "",
    starts_at: toLocalInput(d.starts_at),
    ends_at: toLocalInput(d.ends_at),
    max_uses: d.max_uses ? String(d.max_uses) : "",
    max_uses_per_user: d.max_uses_per_user ? String(d.max_uses_per_user) : "",
    first_order_only: d.first_order_only,
    scope: d.scope,
    country_id: d.country_id ? String(d.country_id) : "",
    is_active: d.is_active,
  };
}

function payloadFrom(form: FormState) {
  return {
    code: form.code.trim().toUpperCase(),
    description: form.description.trim() || null,
    discount_type: form.discount_type,
    value: form.value.trim(),
    max_discount_amount: form.discount_type === "PERCENT" && form.max_discount_amount.trim() ? form.max_discount_amount.trim() : null,
    min_order_amount: form.min_order_amount.trim() ? form.min_order_amount.trim() : null,
    starts_at: fromLocalInput(form.starts_at),
    ends_at: fromLocalInput(form.ends_at),
    max_uses: form.max_uses.trim() ? Number(form.max_uses) : null,
    max_uses_per_user: form.max_uses_per_user.trim() ? Number(form.max_uses_per_user) : null,
    first_order_only: form.first_order_only,
    scope: form.scope,
    country_id: form.scope === "COUNTRY" && form.country_id ? Number(form.country_id) : null,
    is_active: form.is_active,
  };
}

function CodeForm({
  form, setForm, countries, onSubmit, onCancel, busy, submitLabel,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  countries: any[];
  onSubmit: () => void;
  onCancel: () => void;
  busy: boolean;
  submitLabel: string;
}) {
  return (
    <div className="mt-4 pt-4 border-t border-gray-200 space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Code</label>
          <input className={`${inputCls} font-mono uppercase`} maxLength={40} value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="SUMMER25" />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Type</label>
          <select className={inputCls} value={form.discount_type}
            onChange={(e) => setForm({ ...form, discount_type: e.target.value as FormState["discount_type"] })}>
            <option value="PERCENT">Percentage off</option>
            <option value="FIXED">Fixed amount off (EUR)</option>
          </select>
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">
            {form.discount_type === "PERCENT" ? "Percent off (%)" : "Amount off (EUR)"}
          </label>
          <input className={`${inputCls} font-mono`} inputMode="decimal" value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {form.discount_type === "PERCENT" && (
          <div>
            <label className="text-[11px] text-slate-700 font-semibold block mb-1">Maximum discount (EUR)</label>
            <input className={`${inputCls} font-mono`} inputMode="decimal" value={form.max_discount_amount}
              onChange={(e) => setForm({ ...form, max_discount_amount: e.target.value })} placeholder="No cap" />
          </div>
        )}
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Minimum order (EUR)</label>
          <input className={`${inputCls} font-mono`} inputMode="decimal" value={form.min_order_amount}
            onChange={(e) => setForm({ ...form, min_order_amount: e.target.value })} placeholder="Any" />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Applies to</label>
          <select className={inputCls} value={form.scope}
            onChange={(e) => setForm({ ...form, scope: e.target.value as FormState["scope"] })}>
            <option value="ALL">Every package</option>
            <option value="COUNTRY">One destination</option>
          </select>
        </div>
      </div>

      {form.scope === "COUNTRY" && (
        <div className="max-w-xs">
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Destination</label>
          <select className={inputCls} value={form.country_id} onChange={(e) => setForm({ ...form, country_id: e.target.value })}>
            <option value="">Choose a destination…</option>
            {countries.map((c) => (
              <option key={c.id} value={String(c.id)}>{c.name_en} ({c.iso2})</option>
            ))}
          </select>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Starts</label>
          <input type="datetime-local" className={inputCls} value={form.starts_at}
            onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Ends</label>
          <input type="datetime-local" className={inputCls} value={form.ends_at}
            onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Total uses</label>
          <input className={`${inputCls} font-mono`} inputMode="numeric" value={form.max_uses}
            onChange={(e) => setForm({ ...form, max_uses: e.target.value })} placeholder="Unlimited" />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Uses per customer</label>
          <input className={`${inputCls} font-mono`} inputMode="numeric" value={form.max_uses_per_user}
            onChange={(e) => setForm({ ...form, max_uses_per_user: e.target.value })} placeholder="Unlimited" />
        </div>
      </div>

      <div>
        <label className="text-[11px] text-slate-700 font-semibold block mb-1">Internal note</label>
        <input className={inputCls} maxLength={200} value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What this campaign is for" />
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
          <input type="checkbox" checked={form.first_order_only}
            onChange={(e) => setForm({ ...form, first_order_only: e.target.checked })} />
          First purchase only
        </label>
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
          <input type="checkbox" checked={form.is_active}
            onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Active
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onSubmit} disabled={busy || !form.code.trim() || !form.value.trim()}
          className="flex items-center gap-1.5 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
          <Save className="w-3.5 h-3.5" /> {busy ? "Saving…" : submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-bold px-4 py-2.5 rounded-xl">
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function DiscountsTab() {
  const [rows, setRows] = useState<Discount[]>([]);
  const [countries, setCountries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Discount | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [redemptions, setRedemptions] = useState<Record<string, any[]>>({});

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      setRows(await api.getAdminDiscounts(token));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load discount codes" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    api.getCountries().then(setCountries).catch(() => {});
  }, [load]);

  const create = async () => {
    const token = getToken();
    if (!token) return;
    setBusy(true);
    setNotice(null);
    try {
      const made = await api.createAdminDiscount(token, payloadFrom(createForm));
      setCreating(false);
      setCreateForm(EMPTY_FORM);
      await load();
      setNotice({ kind: "ok", text: `${made.code} is live — customers can use it at checkout now.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't create that code" });
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    const token = getToken();
    if (!token || !editingId) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.updateAdminDiscount(token, editingId, payloadFrom(editForm));
      setEditingId(null);
      await load();
      setNotice({ kind: "ok", text: "Saved. Orders already placed keep the discount they were given." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save that code" });
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (row: Discount) => {
    const token = getToken();
    if (!token) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.updateAdminDiscount(token, row.id, { ...payloadFrom(formFrom(row)), is_active: !row.is_active });
      await load();
      setNotice({ kind: "ok", text: `${row.code} is now ${row.is_active ? "switched off" : "active"}.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't update that code" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    const token = getToken();
    if (!token || !deleteTarget) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.deleteAdminDiscount(token, deleteTarget.id);
      setDeleteTarget(null);
      await load();
      setNotice({ kind: "ok", text: res.message });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't remove that code" });
    } finally {
      setBusy(false);
    }
  };

  const showRedemptions = async (row: Discount) => {
    const token = getToken();
    if (!token) return;
    if (expanded === row.id) {
      setExpanded(null);
      return;
    }
    setExpanded(row.id);
    if (!redemptions[row.id]) {
      try {
        const used = await api.getAdminDiscountRedemptions(token, row.id);
        setRedemptions((r) => ({ ...r, [row.id]: used }));
      } catch (err: any) {
        setNotice({ kind: "error", text: err.message || "Couldn't load who used this code" });
      }
    }
  };

  const describe = (d: Discount) => {
    const off = d.discount_type === "PERCENT" ? `${Number(d.value)}% off` : `${eur(d.value)} off`;
    const bits = [off];
    if (d.max_discount_amount) bits.push(`max ${eur(d.max_discount_amount)}`);
    if (d.min_order_amount) bits.push(`min order ${eur(d.min_order_amount)}`);
    if (d.first_order_only) bits.push("first purchase only");
    if (d.max_uses) bits.push(`${d.times_used}/${d.max_uses} used`);
    if (d.max_uses_per_user) bits.push(`${d.max_uses_per_user} per customer`);
    if (d.scope === "COUNTRY") bits.push(countries.find((c) => c.id === d.country_id)?.name_en || "one destination");
    if (d.scope === "PRODUCT") bits.push("one package");
    return bits.join(" · ");
  };

  const window_ = (d: Discount) => {
    if (!d.starts_at && !d.ends_at) return "No date limit";
    const from = d.starts_at ? formatDate(d.starts_at) : "now";
    const to = d.ends_at ? formatDate(d.ends_at) : "no end";
    return `${from} → ${to}`;
  };

  return (
    <div className="space-y-6">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <BadgePercent className="w-4 h-4 text-admin-600" /> Discount codes
            </h3>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl">
              Available to every customer, one code per order. The discount comes off the selling price, so the Sales &amp;
              Profit report shows the real profit and merchant commission is paid on the discounted amount.
            </p>
          </div>
          {!creating && (
            <button type="button" onClick={() => { setCreating(true); setCreateForm(EMPTY_FORM); }}
              className="flex items-center gap-1.5 bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl shrink-0">
              <Plus className="w-3.5 h-3.5" /> New code
            </button>
          )}
        </div>

        {notice && (
          <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
        )}

        {creating && (
          <CodeForm form={createForm} setForm={setCreateForm} countries={countries} onSubmit={create}
            onCancel={() => setCreating(false)} busy={busy} submitLabel="Create code" />
        )}
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        {loading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-gray-100 animate-pulse" />)}</div>
        ) : rows.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No discount codes yet. Create one above and it works at checkout straight away.
          </div>
        ) : (
          <div className="space-y-3">
            {rows.map((row) => (
              <div key={row.id} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-black text-slate-900">{row.code}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                        row.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-gray-100 text-slate-500 border-gray-200"
                      }`}>
                        {row.is_active ? "Active" : "Off"}
                      </span>
                    </div>
                    <div className="text-xs text-slate-600 mt-1">{describe(row)}</div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{window_(row)}</div>
                    {row.description && <div className="text-[11px] text-slate-500 mt-1 italic">{row.description}</div>}
                  </div>

                  <div className="text-end shrink-0">
                    <div className="text-xs text-slate-500">Used <strong className="text-slate-900">{row.times_used}×</strong></div>
                    <div className="text-[11px] text-amber-600 font-mono">− {eur(row.discount_given)} given</div>
                    <div className="text-[11px] text-emerald-700 font-mono">{eur(row.revenue)} received</div>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button onClick={() => { setEditingId(row.id); setEditForm(formFrom(row)); }}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-600 hover:text-slate-900">
                    <Pencil className="w-3 h-3" /> Edit
                  </button>
                  <button onClick={() => toggleActive(row)} disabled={busy}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-600 hover:text-slate-900 disabled:opacity-50">
                    <Power className="w-3 h-3" /> {row.is_active ? "Switch off" : "Switch on"}
                  </button>
                  {row.times_used > 0 && (
                    <button onClick={() => showRedemptions(row)}
                      className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                      <Users className="w-3 h-3" /> Who used it
                      <ChevronDown className={`w-3 h-3 transition-transform ${expanded === row.id ? "rotate-180" : ""}`} />
                    </button>
                  )}
                  <button onClick={() => setDeleteTarget(row)}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-rose-600 ms-auto">
                    <Trash2 className="w-3 h-3" /> Remove
                  </button>
                </div>

                {editingId === row.id && (
                  <CodeForm form={editForm} setForm={setEditForm} countries={countries} onSubmit={saveEdit}
                    onCancel={() => setEditingId(null)} busy={busy} submitLabel="Save changes" />
                )}

                {expanded === row.id && (
                  <div className="mt-3 pt-3 border-t border-gray-200 overflow-x-auto">
                    {!redemptions[row.id] ? (
                      <p className="text-[11px] text-slate-400">Loading…</p>
                    ) : (
                      <table className="w-full text-start text-[11px]">
                        <thead className="text-slate-500">
                          <tr>
                            <th className="py-1.5 pe-3 text-start">Order</th>
                            <th className="py-1.5 pe-3 text-start">Customer</th>
                            <th className="py-1.5 pe-3 text-end">Discount</th>
                            <th className="py-1.5 pe-3 text-end">Paid</th>
                            <th className="py-1.5 text-end">Date</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {redemptions[row.id].map((r: any) => (
                            <tr key={r.id}>
                              <td className="py-1.5 pe-3 font-mono text-admin-600">
                                {r.order_no}
                                <div className="text-[10px] text-slate-400 font-sans">{r.order_status}</div>
                              </td>
                              <td className="py-1.5 pe-3 text-slate-700">
                                {r.username}
                                <div className="text-[10px] text-slate-400">{r.email}</div>
                              </td>
                              <td className="py-1.5 pe-3 text-end font-mono text-amber-600">{eur(r.discount_amount)}</td>
                              <td className="py-1.5 pe-3 text-end font-mono text-slate-900">{eur(r.paid_amount)}</td>
                              <td className="py-1.5 text-end text-slate-500">{formatDate(r.created_at)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget && deleteTarget.times_used > 0 ? "Switch this code off?" : "Delete this code?"}
        tone="danger"
        icon={<Trash2 className="w-5 h-5" />}
        confirmLabel={deleteTarget && deleteTarget.times_used > 0 ? "Switch off" : "Delete"}
        busy={busy}
        onConfirm={remove}
        onCancel={() => setDeleteTarget(null)}
      >
        {deleteTarget && deleteTarget.times_used > 0 ? (
          <p>
            <strong className="font-mono">{deleteTarget.code}</strong> has been used {deleteTarget.times_used} time(s), so it
            will be switched off rather than deleted — otherwise those orders would lose the link to this campaign.
          </p>
        ) : (
          <p><strong className="font-mono">{deleteTarget?.code}</strong> has never been used and will be deleted.</p>
        )}
      </ConfirmDialog>
    </div>
  );
}
