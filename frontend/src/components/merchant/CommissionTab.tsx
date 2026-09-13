"use client";

import React, { useEffect, useState } from "react";
import { ArrowRightLeft, Coins, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { Panel, formatDateTime, getToken } from "./shared";

type Props = {
  overview: any | null;
  formatPrice: (amountUsd: number) => string;
  onChanged: () => void;
};

export default function CommissionTab({ overview, formatPrice, onChanged }: Props) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [ledger, setLedger] = useState<any[] | null>(null);

  const loadLedger = () => {
    const token = getToken();
    if (!token) return;
    api.getWalletLedger(token, "COMMISSION").then(setLedger).catch(() => setLedger([]));
  };

  useEffect(() => {
    loadLedger();
  }, []);

  const commissionBalance = Number(overview?.wallets?.commission_balance ?? 0);
  const walletBalance = Number(overview?.wallets?.wallet_balance ?? 0);

  const transfer = async (all: boolean) => {
    const token = getToken();
    if (!token) return;
    if (!all && !(Number(amount) > 0)) {
      setMessage({ kind: "error", text: "Enter an amount greater than zero." });
      return;
    }
    const label = all ? formatPrice(commissionBalance) : formatPrice(Number(amount));
    if (!window.confirm(`Move ${label} from your commission balance to your main wallet?`)) return;

    setBusy(true);
    setMessage(null);
    try {
      const res = await api.transferCommission(token, all ? undefined : amount);
      setMessage({ kind: "ok", text: `Moved ${formatPrice(Number(res.transferred))} to your main wallet.` });
      setAmount("");
      loadLedger();
      onChanged();
    } catch (err: any) {
      setMessage({ kind: "error", text: err.message || "Transfer failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Commission balance <Coins className="w-4 h-4 text-merchant-600" />
          </div>
          <div className="text-2xl font-black text-merchant-600 font-mono mt-2">{formatPrice(commissionBalance)}</div>
          <p className="text-[11px] text-slate-500 mt-1">Earned at {overview ? Number(overview.commission.effective_rate_pct) : "—"}% of every completed order</p>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Main wallet <Wallet className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-black text-emerald-600 font-mono mt-2">{formatPrice(walletBalance)}</div>
          <p className="text-[11px] text-slate-500 mt-1">Pays for eSIM orders, on the web and through the API</p>
        </div>

        <Panel title="Move commission to wallet" description="Use your earnings to pay for new orders. Instant.">
          <div className="flex gap-2">
            <input
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Amount (EUR)"
              className="flex-1 min-w-0 bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
            <button disabled={busy} onClick={() => transfer(false)} className="px-3 py-2 rounded-xl bg-merchant-600 hover:bg-merchant-500 disabled:opacity-60 text-white text-xs font-bold flex items-center gap-1">
              <ArrowRightLeft className="w-3.5 h-3.5" /> Move
            </button>
          </div>
          <button disabled={busy || commissionBalance <= 0} onClick={() => transfer(true)} className="mt-2 w-full py-2 rounded-xl border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-50 text-xs font-bold text-slate-700">
            Move everything ({formatPrice(commissionBalance)})
          </button>
          {message && (
            <p className={`mt-3 text-xs font-medium ${message.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{message.text}</p>
          )}
        </Panel>
      </div>

      <Panel title="Commission ledger" description="Every credit and transfer on your commission balance.">
        <div className="overflow-x-auto frozen-col-table">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200">
              <tr>
                <th className="py-2 pe-3">Date</th>
                <th className="py-2 pe-3">Description</th>
                <th className="py-2 pe-3">Amount</th>
                <th className="py-2">Balance after</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {ledger === null && <tr><td colSpan={4} className="py-8 text-center text-slate-400">Loading…</td></tr>}
              {ledger?.map((entry) => (
                <tr key={entry.id}>
                  <td className="py-2.5 pe-3 text-slate-500 whitespace-nowrap">{formatDateTime(entry.created_at)}</td>
                  <td className="py-2.5 pe-3 text-slate-700">{entry.description}</td>
                  <td className={`py-2.5 pe-3 font-bold ${entry.tx_type === "CREDIT" ? "text-emerald-600" : "text-rose-600"}`}>
                    {entry.tx_type === "CREDIT" ? "+" : "−"}{formatPrice(Number(entry.amount))}
                  </td>
                  <td className="py-2.5 font-mono text-merchant-600">{formatPrice(Number(entry.balance_after))}</td>
                </tr>
              ))}
              {ledger && ledger.length === 0 && (
                <tr><td colSpan={4} className="py-8 text-center text-slate-500">No commission activity yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
