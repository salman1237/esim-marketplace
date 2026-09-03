"use client";

import React, { useState, useEffect } from "react";
import { Shield, Users, ShoppingCart, DollarSign, Wifi, RefreshCw, Check, X, Sliders, Globe } from "lucide-react";
import { api } from "@/lib/api";

export default function AdminConsolePage() {
  const [stats, setStats] = useState<any>({ total_users: 0, total_orders: 0, total_revenue_usd: 0, total_esims_issued: 0 });
  const [merchants, setMerchants] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [branding, setBranding] = useState({ platform_name: "eSIM Global", support_email: "support@esim.local" });
  const [activeTab, setActiveTab] = useState<"overview" | "merchants" | "payments" | "branding">("overview");
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    
    api.getAdminStats(token).then(setStats).catch(console.error);
    api.getMerchantQueue(token).then(setMerchants).catch(console.error);
    api.getPaymentQueue(token).then(setPayments).catch(console.error);
  }, []);

  const handleSyncCatalog = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSyncing(true);
    try {
      const res = await api.syncCatalog(token);
      alert(`Sync completed! ${res.synced_countries} countries, ${res.synced_products} products.`);
    } catch (err: any) {
      alert("Catalog sync error: " + err.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleApproveMerchant = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.approveMerchant(token, id);
    setMerchants(merchants.map(m => m.id === id ? { ...m, status: "APPROVED" } : m));
  };

  const handleApprovePayment = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.approvePayment(token, id);
    setPayments(payments.map(p => p.id === id ? { ...p, status: "APPROVED" } : p));
  };

  const handleUpdateBranding = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.updateBranding(token, branding);
    alert("Branding updated instantly! Changes live without redeploy.");
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="flex items-center space-x-2 text-brand-400 text-xs font-bold uppercase tracking-wider mb-1">
            <Shield className="w-4 h-4" />
            <span>Operations &amp; Governance Center</span>
          </div>
          <h1 className="text-3xl font-extrabold text-white">Admin Control Console</h1>
        </div>

        <button
          onClick={handleSyncCatalog}
          disabled={syncing}
          className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl shadow-lg shadow-brand-900/30 flex items-center space-x-2 self-start"
        >
          <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} />
          <span>{syncing ? "Syncing VivaPe..." : "Sync VivaPe Catalog"}</span>
        </button>
      </div>

      {/* Metrics Ticker */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="glass-panel rounded-2xl p-5 border border-white/10">
          <div className="text-xs font-semibold text-slate-400">Total Users</div>
          <div className="text-2xl font-black text-white mt-1">{stats.total_users}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-white/10">
          <div className="text-xs font-semibold text-slate-400">Total Orders</div>
          <div className="text-2xl font-black text-white mt-1">{stats.total_orders}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-white/10">
          <div className="text-xs font-semibold text-slate-400">Total Revenue (USD)</div>
          <div className="text-2xl font-black text-emerald-400 mt-1">${stats.total_revenue_usd.toFixed(2)}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-white/10">
          <div className="text-xs font-semibold text-slate-400">Active eSIMs Issued</div>
          <div className="text-2xl font-black text-cyan-400 mt-1">{stats.total_esims_issued}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex space-x-2 border-b border-white/10 mb-6">
        {[
          { id: "overview", label: "Overview" },
          { id: "merchants", label: `Merchants Queue (${merchants.filter(m => m.status === "PENDING").length})` },
          { id: "payments", label: `Payment Approvals (${payments.filter(p => p.status === "PENDING").length})` },
          { id: "branding", label: "Dynamic Site Branding" }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`py-2 px-4 text-xs font-bold border-b-2 transition-colors ${
              activeTab === tab.id ? "border-brand-500 text-white" : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab: Merchants */}
      {activeTab === "merchants" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-4">Partner &amp; Reseller Applications</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2">Business</th>
                  <th className="py-2">Contact</th>
                  <th className="py-2">License</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {merchants.map((m) => (
                  <tr key={m.id}>
                    <td className="py-3 font-semibold text-white">{m.business_name}</td>
                    <td className="py-3 text-slate-300">{m.contact_phone} ({m.email})</td>
                    <td className="py-3 text-slate-400">{m.trade_license || "N/A"}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        m.status === "APPROVED" ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"
                      }`}>{m.status}</span>
                    </td>
                    <td className="py-3">
                      {m.status === "PENDING" && (
                        <button
                          onClick={() => handleApproveMerchant(m.id)}
                          className="bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 rounded text-[11px] font-bold"
                        >
                          Approve Partner
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Payments */}
      {activeTab === "payments" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-4">Manual Payment Verification Queue</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2">User</th>
                  <th className="py-2">Amount</th>
                  <th className="py-2">Method</th>
                  <th className="py-2">TxID</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {payments.map((p) => (
                  <tr key={p.id}>
                    <td className="py-3 text-white">{p.username}</td>
                    <td className="py-3 font-bold font-mono text-emerald-400">{p.amount} {p.currency}</td>
                    <td className="py-3 text-slate-300">{p.bank_name}</td>
                    <td className="py-3 font-mono text-slate-400">{p.transaction_id}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        p.status === "APPROVED" ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"
                      }`}>{p.status}</span>
                    </td>
                    <td className="py-3">
                      {p.status === "PENDING" && (
                        <button
                          onClick={() => handleApprovePayment(p.id)}
                          className="bg-brand-600 hover:bg-brand-500 text-white px-2.5 py-1 rounded text-[11px] font-bold"
                        >
                          Verify &amp; Credit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Dynamic Branding */}
      {activeTab === "branding" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10 max-w-xl">
          <h3 className="text-base font-bold text-white mb-1">Zero-Rebuild Platform Customization</h3>
          <p className="text-xs text-slate-400 mb-6">Updates reflect instantly across the header, footer, and metadata.</p>
          
          <form onSubmit={handleUpdateBranding} className="space-y-4">
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Platform Brand Name</label>
              <input
                type="text"
                value={branding.platform_name}
                onChange={(e) => setBranding({ ...branding, platform_name: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
              />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Support Email</label>
              <input
                type="email"
                value={branding.support_email}
                onChange={(e) => setBranding({ ...branding, support_email: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
              />
            </div>
            <button
              type="submit"
              className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
            >
              Save Branding Changes
            </button>
          </form>
        </div>
      )}

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10 text-xs text-slate-400 space-y-2">
          <p className="font-semibold text-white">System Status: Operational &bull; Dokploy VPS (89.116.122.118)</p>
          <p>Connected to Upstream VivaPe API &amp; ShurjoPay Sandbox Gateway.</p>
          <p>Exchange rates synchronized keylessly from open.er-api.com with manual admin override support.</p>
        </div>
      )}

    </div>
  );
}
