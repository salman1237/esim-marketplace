"use client";

import React, { useState, useEffect } from "react";
import { Wallet, ArrowDownRight, ArrowUpRight, Plus, Upload, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function WalletPage() {
  const { formatPrice, convertTo } = useAppSettings();
  const [wallets, setWallets] = useState<any[]>([]);
  const [ledger, setLedger] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [depositAmount, setDepositAmount] = useState("10");
  const [bankName, setBankName] = useState("bKash");
  const [txId, setTxId] = useState("");
  const [submittingSlip, setSubmittingSlip] = useState(false);
  const [slipSuccess, setSlipSuccess] = useState(false);
  const [payingViaGateway, setPayingViaGateway] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }

    Promise.all([api.getMyWallets(token), api.getMyLedger(token)])
      .then(([w, l]) => {
        setWallets(w);
        setLedger(l);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleGatewayTopup = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    setPayingViaGateway(true);
    try {
      const res = await api.initiateShurjopayTopup(token, parseFloat(depositAmount));
      const checkoutUrl = res.checkout_url || res.checkoutUrl;
      if (checkoutUrl) {
        window.location.href = checkoutUrl;
      } else {
        alert("ShurjoPay did not return a checkout link. Please try again or use manual deposit.");
      }
    } catch (err: any) {
      alert(err.message || "Failed to start ShurjoPay checkout");
    } finally {
      setPayingViaGateway(false);
    }
  };

  const handleManualSlip = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    setSubmittingSlip(true);
    try {
      await api.submitManualDeposit(token, {
        amount: convertTo(parseFloat(depositAmount), "BDT"),
        currency: "BDT",
        bank_name: bankName,
        transaction_id: txId,
      });
      setSlipSuccess(true);
      setTxId("");
    } catch (err: any) {
      alert(err.message || "Failed to submit receipt");
    } finally {
      setSubmittingSlip(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-white">Wallets &amp; Financial Ledger</h1>
        <p className="text-xs text-slate-400 mt-1">Manage balances, top up via cards or mobile banking, and inspect transactions.</p>
      </div>

      {/* Wallets Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
        {wallets.map((w) => (
          <div key={w.id} className="glass-panel rounded-2xl p-6 border border-white/10 relative overflow-hidden">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="font-semibold uppercase tracking-wider">{w.wallet_type} Wallet</span>
              <Wallet className="w-4 h-4 text-brand-400" />
            </div>
            <div className="text-3xl font-extrabold text-white">
              {formatPrice(parseFloat(w.balance))}
            </div>
            <div className="text-[11px] text-emerald-400 mt-2 flex items-center space-x-1">
              <span>Active Currency: {w.currency}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Top Up Options */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
        
        {/* ShurjoPay Instant Top Up */}
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-lg font-bold text-white mb-1">Instant Top Up via ShurjoPay</h3>
          <p className="text-xs text-slate-400 mb-6">Pay using bKash, Nagad, Rocket, or Visa/Mastercard.</p>
          
          <div className="space-y-4">
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Amount (USD)</label>
              <div className="flex gap-2">
                {["5", "10", "20", "50"].map((amt) => (
                  <button
                    key={amt}
                    type="button"
                    onClick={() => setDepositAmount(amt)}
                    className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                      depositAmount === amt ? "bg-brand-600 border-brand-500 text-white" : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                    }`}
                  >
                    ${amt}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={handleGatewayTopup}
              disabled={payingViaGateway}
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 text-white text-xs font-bold shadow-lg shadow-emerald-900/30 hover:opacity-95 disabled:opacity-60"
            >
              {payingViaGateway ? "Redirecting to ShurjoPay..." : `Pay via ShurjoPay Sandbox ($${depositAmount})`}
            </button>
          </div>
        </div>

        {/* Manual Bank / Slip Deposit */}
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-lg font-bold text-white mb-1">Manual Deposit / Bank Transfer</h3>
          <p className="text-xs text-slate-400 mb-6">Submit your transaction ID for admin approval.</p>

          {slipSuccess ? (
            <div className="p-6 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-center">
              <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              <h4 className="text-sm font-bold text-white">Deposit Slip Submitted</h4>
              <p className="text-xs text-slate-400 mt-1">An admin will verify your transaction and credit your balance shortly.</p>
              <button onClick={() => setSlipSuccess(false)} className="mt-4 text-xs text-brand-400 underline">Submit Another</button>
            </div>
          ) : (
            <form onSubmit={handleManualSlip} className="space-y-3">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Payment Method</label>
                <select
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                >
                  <option value="bKash">bKash (01700-000000)</option>
                  <option value="Nagad">Nagad (01700-000000)</option>
                  <option value="City Bank">City Bank (A/C: 1234567890)</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Transaction ID (TxID)</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. 9J28XK19Z"
                  value={txId}
                  onChange={(e) => setTxId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <button
                type="submit"
                disabled={submittingSlip}
                className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold border border-white/10"
              >
                {submittingSlip ? "Submitting..." : "Submit Receipt for Approval"}
              </button>
            </form>
          )}
        </div>

      </div>

      {/* Financial Ledger Table */}
      <div className="glass-panel rounded-2xl p-6 border border-white/10">
        <h3 className="text-lg font-bold text-white mb-4">Transaction History</h3>
        
        {ledger.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">No transactions recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2.5">Date</th>
                  <th className="py-2.5">Type</th>
                  <th className="py-2.5">Amount</th>
                  <th className="py-2.5">Balance After</th>
                  <th className="py-2.5">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {ledger.map((entry) => (
                  <tr key={entry.id}>
                    <td className="py-3 text-slate-400">{new Date(entry.created_at).toLocaleDateString()}</td>
                    <td className="py-3 font-semibold">
                      <span className={`px-2 py-0.5 rounded text-[10px] ${
                        entry.tx_type === "CREDIT" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                      }`}>
                        {entry.tx_type}
                      </span>
                    </td>
                    <td className={`py-3 font-bold font-mono ${
                      entry.tx_type === "CREDIT" ? "text-emerald-400" : "text-rose-400"
                    }`}>
                      {entry.tx_type === "CREDIT" ? "+" : "-"}{formatPrice(parseFloat(entry.amount))}
                    </td>
                    <td className="py-3 font-mono text-slate-300">{formatPrice(parseFloat(entry.balance_after))}</td>
                    <td className="py-3 text-slate-400">{entry.description || entry.reference_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}
