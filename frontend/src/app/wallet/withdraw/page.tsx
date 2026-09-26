"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle, ArrowLeft, Banknote, CheckCircle2, Clock, Landmark, Plus,
  Receipt, Smartphone, Trash2, XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

type PayoutAccount = {
  id: string;
  account_type: "BANK" | "MOBILE";
  bank_name: string;
  holder_name: string;
  account_number: string;
  branch_name?: string | null;
  routing_number?: string | null;
  is_default: boolean;
};

type Withdrawal = {
  id: string;
  reference_no: string;
  amount: string;
  fee_amount: string;
  net_amount: string;
  note_category?: string | null;
  note?: string | null;
  account_line: string;
  status: "PENDING" | "PAID" | "REJECTED" | "CANCELLED";
  payout_currency: string;
  conversion_rate?: string | null;
  payout_amount?: string | null;
  payment_reference?: string | null;
  rejection_reason?: string | null;
  created_at: string;
};

type Config = {
  min_amount: string;
  max_amount: string;
  fee_type: "flat" | "percent";
  fee_value: string;
  payout_currency: string;
  processing_time: string;
  is_enabled: boolean;
  base_currency: string;
  note_categories: string[];
  balance: string;
  can_withdraw: boolean;
  blockers: string[];
  kyc_verified: boolean;
  kyc_status: string | null;
  account_count: number;
};

const CATEGORY_LABELS: Record<string, string> = {
  withdrawal: "Wallet withdrawal",
  commission: "Commission payout",
  refund: "Refund",
  renew: "Renewal funds",
  business: "Business expense",
  other: "Other",
};

const STATUS_STYLE: Record<Withdrawal["status"], { badge: string; icon: React.ComponentType<{ className?: string }>; label: string }> = {
  PENDING: { badge: "bg-amber-50 text-amber-700 border-amber-200", icon: Clock, label: "Awaiting review" },
  PAID: { badge: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: CheckCircle2, label: "Paid" },
  REJECTED: { badge: "bg-rose-50 text-rose-700 border-rose-200", icon: XCircle, label: "Not approved" },
  CANCELLED: { badge: "bg-gray-100 text-slate-600 border-gray-200", icon: XCircle, label: "Cancelled" },
};

// Amounts here are always in the base currency, not the viewer's display
// currency: this is money leaving a EUR-denominated wallet, and showing it
// converted would misstate what is actually being withdrawn.
function eur(value: string | number): string {
  return `€${Number(value || 0).toFixed(2)}`;
}

export default function WithdrawPage() {
  const { convertTo } = useAppSettings();
  const [config, setConfig] = useState<Config | null>(null);
  const [accounts, setAccounts] = useState<PayoutAccount[]>([]);
  const [history, setHistory] = useState<Withdrawal[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const [amount, setAmount] = useState("");
  const [accountId, setAccountId] = useState("");
  const [category, setCategory] = useState("withdrawal");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [showAccountForm, setShowAccountForm] = useState(false);
  const [savingAccount, setSavingAccount] = useState(false);
  const [newAccount, setNewAccount] = useState({
    account_type: "MOBILE" as "BANK" | "MOBILE",
    bank_name: "",
    holder_name: "",
    account_number: "",
    branch_name: "",
    routing_number: "",
  });

  const reload = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    const [cfg, accs, hist] = await Promise.all([
      api.getWithdrawalConfig(token),
      api.getPayoutAccounts(token),
      api.getMyWithdrawals(token),
    ]);
    setConfig(cfg);
    setAccounts(accs);
    setHistory(hist);
    setAccountId((current) => current || accs.find((a: PayoutAccount) => a.is_default)?.id || accs[0]?.id || "");
  }, []);

  useEffect(() => {
    reload()
      .catch((err) => setNotice({ kind: "error", text: err.message || "Could not load your withdrawal details" }))
      .finally(() => setLoading(false));
  }, [reload]);

  const amountNumber = parseFloat(amount);
  const limits = useMemo(() => ({
    min: Number(config?.min_amount ?? 0),
    max: Number(config?.max_amount ?? 0),
    balance: Number(config?.balance ?? 0),
  }), [config]);

  const fee = useMemo(() => {
    if (!config || !Number.isFinite(amountNumber)) return 0;
    const value = Number(config.fee_value || 0);
    const raw = config.fee_type === "percent" ? (amountNumber * value) / 100 : value;
    return Math.min(raw, amountNumber);
  }, [config, amountNumber]);

  const net = Number.isFinite(amountNumber) ? Math.max(amountNumber - fee, 0) : 0;
  const amountValid =
    Number.isFinite(amountNumber) &&
    amountNumber >= limits.min &&
    amountNumber <= limits.max &&
    amountNumber <= limits.balance;

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSavingAccount(true);
    setNotice(null);
    try {
      await api.addPayoutAccount(token, {
        ...newAccount,
        branch_name: newAccount.branch_name || null,
        routing_number: newAccount.routing_number || null,
      });
      setNewAccount({ account_type: "MOBILE", bank_name: "", holder_name: "", account_number: "", branch_name: "", routing_number: "" });
      setShowAccountForm(false);
      await reload();
      setNotice({ kind: "ok", text: "Payout account saved." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Could not save that account" });
    } finally {
      setSavingAccount(false);
    }
  };

  const handleDeleteAccount = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setNotice(null);
    try {
      await api.deletePayoutAccount(token, id);
      if (accountId === id) setAccountId("");
      await reload();
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Could not remove that account" });
    }
  };

  const handleSetDefault = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    try {
      await api.setDefaultPayoutAccount(token, id);
      await reload();
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Could not update the default account" });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSubmitting(true);
    setNotice(null);
    try {
      const created = await api.createWithdrawal(token, {
        amount: String(amountNumber),
        bank_account_id: accountId,
        note_category: category,
        note: note || undefined,
      });
      setAmount("");
      setNote("");
      await reload();
      setNotice({ kind: "ok", text: `Request ${created.reference_no} submitted. ${eur(created.amount)} is now on hold.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Could not submit the request" });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setNotice(null);
    try {
      await api.cancelWithdrawal(token, id);
      await reload();
      setNotice({ kind: "ok", text: "Request cancelled — the amount is back in your wallet." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Could not cancel that request" });
    }
  };

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-4">
        <div className="h-8 w-56 rounded bg-gray-100 animate-pulse" />
        <div className="h-40 rounded-2xl bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  const feeLabel = config
    ? config.fee_type === "percent"
      ? `${Number(config.fee_value).toFixed(2)}% of the amount`
      : Number(config.fee_value) === 0
      ? "No fee"
      : `${eur(config.fee_value)} per withdrawal`
    : "";

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <Link href="/wallet" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900 mb-4">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to wallet
      </Link>

      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900">Withdraw funds</h1>
          <p className="text-xs text-slate-500 mt-1">
            Paid out in {config?.payout_currency} at the exchange rate on the day your request is approved.
          </p>
        </div>
        <div className="text-end">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Available balance</div>
          <div className="text-2xl font-black text-slate-900">{eur(limits.balance)}</div>
        </div>
      </div>

      {notice && (
        <div className={`mb-6 p-4 rounded-xl border text-sm font-semibold flex items-start justify-between gap-4 ${
          notice.kind === "ok" ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"
        }`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="text-xs underline opacity-75 hover:opacity-100 shrink-0">Dismiss</button>
        </div>
      )}

      {/* What's standing in the way, if anything — each item names the fix. */}
      {config && config.blockers.length > 0 && (
        <div className="mb-8 glass-panel rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <h2 className="text-sm font-bold text-slate-900">Before you can withdraw</h2>
          </div>
          <ul className="space-y-1.5 text-xs text-slate-700">
            {config.blockers.map((blocker) => (
              <li key={blocker} className="flex items-start gap-2">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />
                <span>
                  {blocker}
                  {blocker.toLowerCase().includes("kyc") && !config.kyc_verified && config.kyc_status !== "PENDING" && (
                    <Link href="/profile" className="ms-1.5 font-bold text-brand-600 underline">Verify now</Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-10 items-start">

        {/* Payout accounts */}
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <div className="flex items-start justify-between gap-3 mb-1">
            <h2 className="text-lg font-bold text-slate-900">Payout accounts</h2>
            {!showAccountForm && accounts.length < 5 && (
              <button
                onClick={() => setShowAccountForm(true)}
                className="inline-flex items-center gap-1 text-xs font-bold text-brand-600 hover:text-brand-700 shrink-0"
              >
                <Plus className="w-3.5 h-3.5" /> Add account
              </button>
            )}
          </div>
          <p className="text-xs text-slate-500 mb-5">Where we send the money. The name must match your verified ID.</p>

          {accounts.length === 0 && !showAccountForm && (
            <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl text-center text-xs text-slate-500">
              No payout account saved yet.
            </div>
          )}

          <div className="space-y-2">
            {accounts.map((account) => {
              const Icon = account.account_type === "MOBILE" ? Smartphone : Landmark;
              return (
                <div key={account.id} className="flex items-start gap-3 p-3 rounded-xl border border-gray-200 bg-white">
                  <span className="w-8 h-8 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center shrink-0">
                    <Icon className="w-4 h-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-900 truncate">{account.bank_name}</span>
                      {account.is_default && (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">Default</span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 font-mono">{account.account_number}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {account.holder_name}
                      {account.branch_name ? ` · ${account.branch_name}` : ""}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    {!account.is_default && (
                      <button onClick={() => handleSetDefault(account.id)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-900">
                        Make default
                      </button>
                    )}
                    <button onClick={() => handleDeleteAccount(account.id)} aria-label={`Remove ${account.bank_name}`} className="text-slate-400 hover:text-rose-600">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {showAccountForm && (
            <form onSubmit={handleAddAccount} className="mt-4 pt-4 border-t border-gray-200 space-y-3">
              <div className="grid grid-cols-2 gap-2">
                {(["MOBILE", "BANK"] as const).map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => setNewAccount((a) => ({ ...a, account_type: kind }))}
                    className={`py-2 text-xs font-bold rounded-lg border transition-colors ${
                      newAccount.account_type === kind ? "bg-brand-600 border-brand-500 text-white" : "bg-gray-50 border-gray-300 text-slate-700 hover:bg-gray-100"
                    }`}
                  >
                    {kind === "MOBILE" ? "Mobile wallet" : "Bank account"}
                  </button>
                ))}
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">
                  {newAccount.account_type === "MOBILE" ? "Provider (bKash, Nagad, Rocket)" : "Bank name"}
                </label>
                <input
                  required minLength={2}
                  value={newAccount.bank_name}
                  onChange={(e) => setNewAccount((a) => ({ ...a, bank_name: e.target.value }))}
                  placeholder={newAccount.account_type === "MOBILE" ? "bKash" : "City Bank"}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Account holder name</label>
                <input
                  required minLength={2}
                  value={newAccount.holder_name}
                  onChange={(e) => setNewAccount((a) => ({ ...a, holder_name: e.target.value }))}
                  placeholder="As printed on your ID"
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">
                  {newAccount.account_type === "MOBILE" ? "Mobile number" : "Account number"}
                </label>
                <input
                  required minLength={4}
                  value={newAccount.account_number}
                  onChange={(e) => setNewAccount((a) => ({ ...a, account_number: e.target.value }))}
                  placeholder={newAccount.account_type === "MOBILE" ? "01712345678" : "1234567890123"}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 font-mono"
                />
              </div>
              {newAccount.account_type === "BANK" && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Branch</label>
                    <input
                      value={newAccount.branch_name}
                      onChange={(e) => setNewAccount((a) => ({ ...a, branch_name: e.target.value }))}
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Routing number</label>
                    <input
                      value={newAccount.routing_number}
                      onChange={(e) => setNewAccount((a) => ({ ...a, routing_number: e.target.value }))}
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 font-mono"
                    />
                  </div>
                </div>
              )}
              <div className="flex gap-2">
                <button type="submit" disabled={savingAccount} className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold disabled:opacity-60">
                  {savingAccount ? "Saving..." : "Save account"}
                </button>
                <button type="button" onClick={() => setShowAccountForm(false)} className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-bold">
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Request form */}
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h2 className="text-lg font-bold text-slate-900 mb-1">Request a withdrawal</h2>
          <p className="text-xs text-slate-500 mb-5">
            Between {eur(limits.min)} and {eur(limits.max)} · {feeLabel} · usually {config?.processing_time}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Amount ({config?.base_currency})</label>
              <input
                type="number" inputMode="decimal" step="0.01" min={limits.min} max={limits.max}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder={limits.min.toFixed(2)}
                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-slate-900"
              />
              {amount.trim() !== "" && !amountValid && (
                <p className="text-[11px] text-rose-600 mt-1">
                  {amountNumber > limits.balance
                    ? "That is more than your available balance."
                    : `Enter an amount between ${eur(limits.min)} and ${eur(limits.max)}.`}
                </p>
              )}
            </div>

            {amountValid && (
              <div className="p-3 bg-gray-50 border border-gray-200 rounded-xl text-xs space-y-1.5">
                <div className="flex justify-between"><span className="text-slate-500">Withdrawn from wallet</span><span className="font-semibold text-slate-900">{eur(amountNumber)}</span></div>
                {fee > 0 && (
                  <div className="flex justify-between"><span className="text-slate-500">Processing fee</span><span className="font-semibold text-rose-600">- {eur(fee)}</span></div>
                )}
                <div className="flex justify-between pt-1.5 border-t border-gray-200">
                  <span className="text-slate-700 font-semibold">You receive</span>
                  <span className="font-bold text-slate-900">{eur(net)}</span>
                </div>
                <p className="text-[11px] text-slate-500 pt-0.5">
                  About ৳{Math.round(convertTo(net, "BDT")).toLocaleString()} at today&apos;s rate — the exact figure is set when your request is approved.
                </p>
              </div>
            )}

            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Send to</label>
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                disabled={accounts.length === 0}
                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 disabled:bg-gray-50"
              >
                {accounts.length === 0 ? (
                  <option value="">Add a payout account first</option>
                ) : (
                  accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.bank_name} · {account.account_number}
                    </option>
                  ))
                )}
              </select>
            </div>

            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Reason</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
              >
                {(config?.note_categories || []).map((key) => (
                  <option key={key} value={key}>{CATEGORY_LABELS[key] || key}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Note <span className="text-slate-400 font-normal">(optional)</span></label>
              <textarea
                rows={2} maxLength={500}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Anything our team should know about this payout"
                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || !amountValid || !accountId || !config?.can_withdraw}
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-brand-600 to-indigo-600 text-white text-xs font-bold shadow-md shadow-brand-900/10 hover:opacity-95 disabled:opacity-60"
            >
              {submitting ? "Submitting..." : "Request withdrawal"}
            </button>
            <p className="text-[11px] text-slate-500 text-center">
              The amount is held from your balance as soon as you submit, and returned in full if the request is cancelled or not approved.
            </p>
          </form>
        </div>
      </div>

      {/* History */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h2 className="text-lg font-bold text-slate-900 mb-4">Withdrawal history</h2>
        {history.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">No withdrawals yet.</div>
        ) : (
          <div className="space-y-3">
            {history.map((item) => {
              const style = STATUS_STYLE[item.status];
              const Icon = style.icon;
              return (
                <div key={item.id} className="p-4 rounded-xl border border-gray-200 bg-white">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-slate-900">{item.reference_no}</span>
                        <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border ${style.badge}`}>
                          <Icon className="w-3 h-3" /> {style.label}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        {new Date(item.created_at).toLocaleDateString()} · {item.account_line}
                        {item.note_category ? ` · ${CATEGORY_LABELS[item.note_category] || item.note_category}` : ""}
                      </div>
                      {item.status === "PAID" && item.payout_amount && (
                        <div className="text-xs text-emerald-700 font-semibold mt-1">
                          Sent {Number(item.payout_amount).toLocaleString(undefined, { maximumFractionDigits: 2 })} {item.payout_currency}
                          {item.conversion_rate ? ` at 1 EUR = ${Number(item.conversion_rate).toFixed(2)} ${item.payout_currency}` : ""}
                        </div>
                      )}
                      {item.status === "REJECTED" && item.rejection_reason && (
                        <div className="text-xs text-rose-600 mt-1">{item.rejection_reason}</div>
                      )}
                    </div>
                    <div className="text-end shrink-0">
                      <div className="text-sm font-bold text-slate-900">{eur(item.amount)}</div>
                      {Number(item.fee_amount) > 0 && (
                        <div className="text-[11px] text-slate-500">net {eur(item.net_amount)}</div>
                      )}
                      <div className="flex items-center gap-3 mt-1.5 justify-end">
                        {item.status === "PENDING" && (
                          <button onClick={() => handleCancel(item.id)} className="text-[11px] font-semibold text-rose-600 hover:text-rose-700">
                            Cancel
                          </button>
                        )}
                        {item.status === "PAID" && (
                          <Link href={`/wallet/withdraw/${item.id}`} className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                            <Receipt className="w-3 h-3" /> Receipt
                          </Link>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <p className="mt-6 text-[11px] text-slate-500 flex items-start gap-2">
        <Banknote className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        Withdrawals come from your main wallet balance only. Reward credit can be spent on eSIMs but cannot be withdrawn.
      </p>
    </div>
  );
}
