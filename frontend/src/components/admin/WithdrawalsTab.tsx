"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, Banknote, CheckCircle2, Clock, Eye, FileImage, Save, Upload, XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";

type Withdrawal = {
  id: string;
  reference_no: string;
  amount: string;
  fee_amount: string;
  net_amount: string;
  note_category?: string | null;
  note?: string | null;
  account: Record<string, any>;
  account_line: string;
  status: "PENDING" | "PAID" | "REJECTED" | "CANCELLED";
  payout_currency: string;
  conversion_rate?: string | null;
  payout_amount?: string | null;
  payment_reference?: string | null;
  has_proof: boolean;
  rejection_reason?: string | null;
  created_at: string;
  reviewed_at?: string | null;
  user?: { id: string; username: string; email: string; role: string };
};

const STATUS_BADGE: Record<Withdrawal["status"], string> = {
  PENDING: "bg-amber-50 text-amber-700 border-amber-200",
  PAID: "bg-emerald-50 text-emerald-700 border-emerald-200",
  REJECTED: "bg-rose-50 text-rose-700 border-rose-200",
  CANCELLED: "bg-gray-100 text-slate-600 border-gray-200",
};

const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

function SettingsCard({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [form, setForm] = useState<any | null>(null);
  const [meta, setMeta] = useState<{ fee_types: string[]; payout_currencies: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api.getAdminWithdrawalSettings(token)
      .then((cfg) => {
        setMeta({ fee_types: cfg.fee_types, payout_currencies: cfg.payout_currencies });
        setForm({
          min_amount: String(Number(cfg.min_amount)),
          max_amount: String(Number(cfg.max_amount)),
          fee_type: cfg.fee_type,
          fee_value: String(Number(cfg.fee_value)),
          payout_currency: cfg.payout_currency,
          processing_time: cfg.processing_time,
          is_enabled: cfg.is_enabled,
        });
      })
      .catch((err) => setNotice({ kind: "error", text: err.message || "Couldn't load withdrawal settings" }));
  }, []);

  const save = async () => {
    const token = getToken();
    if (!token || !form) return;
    setSaving(true);
    setNotice(null);
    try {
      await api.updateAdminWithdrawalSettings(token, form);
      setNotice({ kind: "ok", text: "Saved — the withdraw page uses these straight away." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save" });
    } finally {
      setSaving(false);
    }
  };

  if (!form) return <div className="glass-panel rounded-2xl border border-gray-200 h-40 animate-pulse" />;

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Banknote className="w-4 h-4 text-admin-600" /> Withdrawal rules
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-2xl">
        Limits and fee are in the base currency (EUR); payouts are converted at the rate on the day a request is approved.
        {!isSuperAdmin && " Only a Super Admin can change these."}
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Minimum (EUR)</label>
          <input className={`${inputCls} font-mono`} inputMode="decimal" disabled={!isSuperAdmin}
            value={form.min_amount} onChange={(e) => setForm({ ...form, min_amount: e.target.value })} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Maximum (EUR)</label>
          <input className={`${inputCls} font-mono`} inputMode="decimal" disabled={!isSuperAdmin}
            value={form.max_amount} onChange={(e) => setForm({ ...form, max_amount: e.target.value })} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Payout currency</label>
          <select className={inputCls} disabled={!isSuperAdmin}
            value={form.payout_currency} onChange={(e) => setForm({ ...form, payout_currency: e.target.value })}>
            {(meta?.payout_currencies || [form.payout_currency]).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Fee type</label>
          <select className={inputCls} disabled={!isSuperAdmin}
            value={form.fee_type} onChange={(e) => setForm({ ...form, fee_type: e.target.value })}>
            {(meta?.fee_types || ["flat", "percent"]).map((t) => (
              <option key={t} value={t}>{t === "flat" ? "Flat amount (EUR)" : "Percentage of amount"}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">
            Fee {form.fee_type === "percent" ? "(%)" : "(EUR)"}
          </label>
          <input className={`${inputCls} font-mono`} inputMode="decimal" disabled={!isSuperAdmin}
            value={form.fee_value} onChange={(e) => setForm({ ...form, fee_value: e.target.value })} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Processing time shown to users</label>
          <input className={inputCls} maxLength={120} disabled={!isSuperAdmin}
            value={form.processing_time} onChange={(e) => setForm({ ...form, processing_time: e.target.value })} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 mt-4">
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
          <input type="checkbox" checked={form.is_enabled} disabled={!isSuperAdmin}
            onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />
          Withdrawals open
        </label>
        {isSuperAdmin && (
          <button type="button" onClick={save} disabled={saving}
            className="flex items-center gap-1.5 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
            <Save className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save rules"}
          </button>
        )}
      </div>
      {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}
    </div>
  );
}

export default function WithdrawalsTab({ isSuperAdmin, onCountChange }: { isSuperAdmin: boolean; onCountChange?: (n: number) => void }) {
  const [rows, setRows] = useState<Withdrawal[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("PENDING");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Approval form, per row
  const [payingId, setPayingId] = useState<string | null>(null);
  const [reference, setReference] = useState("");
  const [proofFile, setProofFile] = useState<File | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Withdrawal | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [viewingProof, setViewingProof] = useState<{ url: string; contentType: string } | null>(null);

  const load = useCallback(async (status: string) => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      const data = await api.getAdminWithdrawals(token, status === "ALL" ? undefined : status);
      setRows(data);
      if (status === "PENDING") onCountChange?.(data.length);
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load withdrawals" });
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    load(statusFilter);
  }, [statusFilter, load]);

  const startApproval = (row: Withdrawal) => {
    setPayingId(row.id);
    setReference("");
    setProofFile(null);
    setNotice(null);
  };

  const approve = async (row: Withdrawal) => {
    const token = getToken();
    if (!token || !proofFile || !reference.trim()) return;
    setBusyId(row.id);
    setNotice(null);
    try {
      const paid = await api.approveWithdrawal(token, row.id, reference.trim(), proofFile);
      setPayingId(null);
      await load(statusFilter);
      setNotice({
        kind: "ok",
        text: `${paid.reference_no} marked paid — ${Number(paid.payout_amount).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${paid.payout_currency} at 1 EUR = ${Number(paid.conversion_rate).toFixed(4)}. Receipts emailed to the user and to finance.`,
      });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't mark it paid" });
    } finally {
      setBusyId(null);
    }
  };

  const reject = async () => {
    const token = getToken();
    if (!token || !rejectTarget) return;
    setBusyId(rejectTarget.id);
    setNotice(null);
    try {
      await api.rejectWithdrawal(token, rejectTarget.id, rejectReason.trim());
      const returned = eur(rejectTarget.amount);
      setRejectTarget(null);
      setRejectReason("");
      await load(statusFilter);
      setNotice({ kind: "ok", text: `Rejected — ${returned} returned to the wallet and the user has been emailed.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't reject it" });
    } finally {
      setBusyId(null);
    }
  };

  const openProof = async (row: Withdrawal) => {
    const token = getToken();
    if (!token) return;
    try {
      setViewingProof(await api.getWithdrawalProofUrl(token, row.id));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load the proof" });
    }
  };

  const pendingTotal = rows
    .filter((r) => r.status === "PENDING")
    .reduce((sum, r) => sum + Number(r.net_amount), 0);

  return (
    <div className="space-y-6">
      <SettingsCard isSuperAdmin={isSuperAdmin} />

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-1">
          <div>
            <h3 className="text-base font-bold text-slate-900">Withdrawal requests</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl">
              The amount already left the user&apos;s wallet when they requested it. Approving records the payout and freezes
              the conversion rate; rejecting returns the full amount.
            </p>
          </div>
          <div className="flex gap-1 shrink-0">
            {["PENDING", "PAID", "REJECTED", "ALL"].map((status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={`text-[11px] font-bold px-2.5 py-1.5 rounded-lg border transition-colors ${
                  statusFilter === status ? "bg-admin-50 text-admin-700 border-admin-200" : "bg-white text-slate-600 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {status === "ALL" ? "All" : status.charAt(0) + status.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>

        {statusFilter === "PENDING" && rows.length > 0 && (
          <p className="text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mt-3 flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 shrink-0" />
            {rows.length} request{rows.length === 1 ? "" : "s"} waiting · {eur(pendingTotal)} to pay out
          </p>
        )}
        {notice && (
          <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
        )}

        {loading ? (
          <div className="mt-4 space-y-2">
            {[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-gray-100 animate-pulse" />)}
          </div>
        ) : rows.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No {statusFilter === "ALL" ? "" : statusFilter.toLowerCase()} withdrawal requests.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {rows.map((row) => (
              <div key={row.id} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-bold text-slate-900">{row.reference_no}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${STATUS_BADGE[row.status]}`}>{row.status}</span>
                      {row.note_category && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-gray-100 text-slate-600 border border-gray-200">
                          {row.note_category}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-700 font-semibold mt-1.5">
                      {row.user?.username} <span className="text-slate-400 font-normal">· {row.user?.email}</span>
                    </div>
                    <div className="text-xs text-slate-500">{row.account_line}</div>
                    {row.account?.branch_name && <div className="text-xs text-slate-500">Branch: {row.account.branch_name}</div>}
                    {row.account?.routing_number && <div className="text-xs text-slate-500 font-mono">Routing: {row.account.routing_number}</div>}
                    {row.note && <div className="text-xs text-slate-600 mt-1 italic">&ldquo;{row.note}&rdquo;</div>}
                    <div className="text-[11px] text-slate-400 mt-1">
                      Requested {new Date(row.created_at).toLocaleString()}
                      {row.reviewed_at ? ` · reviewed ${new Date(row.reviewed_at).toLocaleString()}` : ""}
                    </div>
                  </div>

                  <div className="text-end shrink-0">
                    <div className="text-sm font-black text-slate-900">{eur(row.amount)}</div>
                    {Number(row.fee_amount) > 0 && (
                      <div className="text-[11px] text-slate-500">fee {eur(row.fee_amount)} · net {eur(row.net_amount)}</div>
                    )}
                    {row.status === "PAID" && row.payout_amount && (
                      <div className="text-[11px] text-emerald-700 font-semibold mt-1">
                        Sent {Number(row.payout_amount).toLocaleString(undefined, { maximumFractionDigits: 2 })} {row.payout_currency}
                        <div className="text-slate-500 font-normal">
                          1 EUR = {Number(row.conversion_rate).toFixed(4)} {row.payout_currency}
                        </div>
                        {row.payment_reference && <div className="font-mono text-slate-500 font-normal">{row.payment_reference}</div>}
                      </div>
                    )}
                    {row.status === "REJECTED" && row.rejection_reason && (
                      <div className="text-[11px] text-rose-600 mt-1 max-w-[220px]">{row.rejection_reason}</div>
                    )}
                  </div>
                </div>

                {row.status === "PENDING" && (
                  payingId === row.id ? (
                    <div className="mt-4 pt-4 border-t border-gray-200 space-y-3">
                      <p className="text-[11px] text-slate-600 flex items-start gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
                        Send <strong className="mx-1">{eur(row.net_amount)}</strong> to the account above first, then record it
                        here. The rate is taken at this moment and cannot be changed afterwards.
                      </p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Payment reference / TrxID</label>
                          <input className={`${inputCls} font-mono`} value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. BKASH 9J28XK19Z" />
                        </div>
                        <div>
                          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Payment proof (screenshot or PDF)</label>
                          <label className="flex items-center gap-2 cursor-pointer bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-600 hover:bg-gray-50">
                            <Upload className="w-3.5 h-3.5 shrink-0" />
                            <span className="truncate">{proofFile ? proofFile.name : "Choose a file"}</span>
                            <input
                              type="file"
                              accept="image/png,image/jpeg,image/webp,application/pdf"
                              className="hidden"
                              onChange={(e) => setProofFile(e.target.files?.[0] || null)}
                            />
                          </label>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => approve(row)}
                          disabled={busyId === row.id || !reference.trim() || !proofFile}
                          className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5" /> {busyId === row.id ? "Recording…" : "Confirm payment sent"}
                        </button>
                        <button onClick={() => setPayingId(null)} className="bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-bold px-4 py-2.5 rounded-xl">
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button onClick={() => startApproval(row)} className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-3 py-2 rounded-lg">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Mark paid
                      </button>
                      <button onClick={() => { setRejectTarget(row); setRejectReason(""); }} className="flex items-center gap-1.5 bg-white hover:bg-rose-50 border border-gray-300 text-rose-600 text-xs font-bold px-3 py-2 rounded-lg">
                        <XCircle className="w-3.5 h-3.5" /> Reject &amp; refund
                      </button>
                    </div>
                  )
                )}

                {row.has_proof && (
                  <button onClick={() => openProof(row)} className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                    <Eye className="w-3.5 h-3.5" /> View payment proof
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={rejectTarget !== null}
        title="Reject this withdrawal?"
        tone="danger"
        icon={<XCircle className="w-5 h-5" />}
        confirmLabel="Reject and return the money"
        busy={busyId === rejectTarget?.id}
        onConfirm={reject}
        onCancel={() => setRejectTarget(null)}
      >
        <p className="mb-3">
          {rejectTarget ? <>The full <strong>{eur(rejectTarget.amount)}</strong> goes straight back to {rejectTarget.user?.username}&apos;s wallet, and they are emailed the reason.</> : null}
        </p>
        <label className="text-[11px] text-slate-700 font-semibold block mb-1">Reason (shown to the user)</label>
        <input
          className={inputCls}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="e.g. Account name does not match your verified ID"
        />
      </ConfirmDialog>

      {viewingProof && (
        <div className="fixed inset-0 z-50 bg-slate-900/70 flex items-center justify-center p-4" onClick={() => setViewingProof(null)}>
          <div className="bg-white rounded-2xl p-4 max-w-3xl w-full max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2"><FileImage className="w-4 h-4" /> Payment proof</h4>
              <button onClick={() => setViewingProof(null)} className="text-slate-400 hover:text-slate-900"><XCircle className="w-5 h-5" /></button>
            </div>
            {viewingProof.contentType === "application/pdf" ? (
              <iframe src={viewingProof.url} title="Payment proof" className="w-full h-[70vh] rounded-lg border border-gray-200" />
            ) : (
              <img src={viewingProof.url} alt="Payment proof" className="w-full rounded-lg border border-gray-200" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
