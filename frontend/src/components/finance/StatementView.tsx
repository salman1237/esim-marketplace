"use client";

import React, { useState } from "react";
import { CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, Download } from "lucide-react";
import { api } from "@/lib/api";

// Statement amounts are accounting figures in the base currency.
export const eur = (value?: string | null) => (value === null || value === undefined ? "—" : `€${Number(value).toFixed(2)}`);

export const REFERENCE_LABELS: Record<string, string> = {
  DEPOSIT_GATEWAY: "Top-up (payment gateway)",
  DEPOSIT_MANUAL: "Manual deposit (bKash/bank)",
  ORDER_PURCHASE: "eSIM purchases",
  COMMISSION_EARNED: "Commission earned",
  COMMISSION_TRANSFER: "Commission moved to main wallet",
  ADMIN_ADJUSTMENT: "Adjustment by admin",
  REFUND: "Refunds (failed orders)",
};

const WALLET_LABELS: Record<string, string> = {
  DEFAULT: "Main wallet",
  COMMISSION: "Commission wallet",
  REWARD: "Reward wallet",
};

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

function WalletSection({ wallet }: { wallet: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold text-slate-900">{WALLET_LABELS[wallet.wallet_type] || wallet.wallet_type}</div>
        {wallet.consistent ? (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-700"><CheckCircle2 className="w-3.5 h-3.5" /> Adds up</span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-rose-700"><AlertTriangle className="w-3.5 h-3.5" /> Doesn&apos;t add up — contact support</span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-xs">
        {[
          ["Opening", wallet.opening_balance, "text-slate-700"],
          ["Money in", wallet.credits, "text-emerald-600"],
          ["Money out", wallet.debits, "text-rose-600"],
          ["Closing", wallet.closing_balance, "text-slate-900"],
        ].map(([label, value, tone]) => (
          <div key={label} className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">{label}</div>
            <div className={`font-mono font-bold text-sm ${tone}`}>{eur(value)}</div>
          </div>
        ))}
      </div>

      {Object.keys(wallet.by_type).length > 0 && (
        <table className="w-full text-xs mt-3">
          <tbody className="divide-y divide-gray-100">
            {Object.entries(wallet.by_type).map(([ref, t]: [string, any]) => (
              <tr key={ref}>
                <td className="py-1.5 text-slate-600">{REFERENCE_LABELS[ref] || ref} <span className="text-slate-400">× {t.entries}</span></td>
                <td className="py-1.5 text-end font-mono text-emerald-600">{Number(t.credits) > 0 ? `+${eur(t.credits)}` : ""}</td>
                <td className="py-1.5 text-end font-mono text-rose-600">{Number(t.debits) > 0 ? `−${eur(t.debits)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {wallet.entries.length > 0 ? (
        <button type="button" onClick={() => setOpen(!open)} className="mt-3 flex items-center gap-1 text-[11px] font-semibold text-slate-600 hover:text-slate-900">
          {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          {open ? "Hide" : "Show"} {wallet.entries.length} transactions
        </button>
      ) : (
        <p className="mt-3 text-[11px] text-slate-500">No transactions this month.</p>
      )}

      {open && (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead className="text-slate-500 border-b border-gray-200">
              <tr>
                <th className="py-1.5 pe-3 text-start font-medium">Date</th>
                <th className="py-1.5 pe-3 text-start font-medium">Description</th>
                <th className="py-1.5 pe-3 text-end font-medium">Amount</th>
                <th className="py-1.5 text-end font-medium">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {wallet.entries.map((e: any, i: number) => (
                <tr key={i}>
                  <td className="py-1.5 pe-3 text-slate-500 whitespace-nowrap">{e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
                  <td className="py-1.5 pe-3 text-slate-700">{e.description || REFERENCE_LABELS[e.reference_type] || e.reference_type}</td>
                  <td className={`py-1.5 pe-3 text-end font-mono font-semibold ${e.tx_type === "CREDIT" ? "text-emerald-600" : "text-rose-600"}`}>
                    {e.tx_type === "CREDIT" ? "+" : "−"}{eur(e.amount)}
                  </td>
                  <td className="py-1.5 text-end font-mono text-slate-700">{eur(e.balance_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function StatementView({ statement, csvPath, csvName }: { statement: any; csvPath: string; csvName: string }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const o = statement.orders;

  const download = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setDownloading(true);
    setError(null);
    try {
      saveBlob(await api.downloadAuthed(token, csvPath), csvName);
    } catch (err: any) {
      setError(err.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  const monthLabel = new Date(`${statement.period.month}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-base font-bold text-slate-900">{statement.merchant.business_name || statement.merchant.username} — {monthLabel}</div>
          <div className="text-[11px] text-slate-500">
            {statement.merchant.email} · commission {statement.merchant.commission_rate_pct ?? "—"}% · generated {new Date(statement.generated_at).toLocaleString()}
          </div>
        </div>
        <button type="button" onClick={download} disabled={downloading} className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg disabled:opacity-60">
          <Download className="w-3.5 h-3.5" /> {downloading ? "Preparing…" : "Download CSV"}
        </button>
      </div>
      {error && <p className="text-xs text-rose-600">{error}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          ["Completed orders", String(o.completed), `${o.completed_via_api} via API`],
          ["Sales volume", eur(o.sales_volume), "completed orders"],
          ["Commission earned", eur(o.commission_earned), "on completed orders"],
          ["Failed · refunded", String(o.failed_refunded), "refunded to wallet"],
        ].map(([label, value, hint]) => (
          <div key={label} className="rounded-xl border border-gray-200 bg-white px-4 py-3">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">{label}</div>
            <div className="text-lg font-black font-mono text-slate-900">{value}</div>
            <div className="text-[10px] text-slate-400">{hint}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {statement.wallets.map((w: any) => <WalletSection key={w.wallet_type} wallet={w} />)}
      </div>
    </div>
  );
}
