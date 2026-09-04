"use client";

import React, { useState, useEffect } from "react";
import { Shield, Users, ShoppingCart, DollarSign, Wifi, RefreshCw, Check, X, Sliders, Globe, FileText, Activity, Languages } from "lucide-react";
import { api, API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import TranslationsManager from "@/components/TranslationsManager";

type TabId = "overview" | "orders" | "catalog" | "users" | "merchants" | "payments" | "branding" | "translations" | "logs";

export default function AdminConsolePage() {
  const { formatPrice, languages: appLanguages } = useAppSettings();
  const [role, setRole] = useState<string | null>(null);
  const [stats, setStats] = useState<any>({ total_users: 0, total_orders: 0, total_revenue_usd: 0, total_esims_issued: 0 });
  const [merchants, setMerchants] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditSummary, setAuditSummary] = useState<{ action_counts: Record<string, number>; recent: any[] } | null>(null);
  const [supplierLogs, setSupplierLogs] = useState<any[]>([]);
  const [allOrders, setAllOrders] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [inspectingLog, setInspectingLog] = useState<any | null>(null);

  const [branding, setBranding] = useState({ platform_name: "eSIM Global", support_email: "support@esim.local", support_phone: "+880 1700-000000", maintenance_mode: false, default_currency: "USD" });
  const [socialLinks, setSocialLinks] = useState<Record<string, string>>({});
  const [brandingAssets, setBrandingAssets] = useState<{ logo_light?: string; logo_dark?: string; favicon?: string }>({});
  const [uploadingKind, setUploadingKind] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [syncing, setSyncing] = useState(false);

  // Currency override
  const [overrideCurrency, setOverrideCurrency] = useState("BDT");
  const [manualRate, setManualRate] = useState("125.00");
  const [isOverride, setIsOverride] = useState(false);

  const isSuperAdmin = role === "SUPER_ADMIN";

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }

    api.getMe(token).then((me) => setRole(me.role)).catch(() => {
      localStorage.removeItem("esim_token");
      window.location.href = "/auth/login";
    });

    api.getAdminStats(token).then(setStats).catch(console.error);
    api.getMerchantQueue(token).then(setMerchants).catch(console.error);
    api.getPaymentQueue(token).then(setPayments).catch(console.error);
    api.getSupplierLogs(token).then(setSupplierLogs).catch(console.error);
    api.getAdminOrders(token).then(setAllOrders).catch(console.error);
    api.getAdminCatalog(token).then(setCatalog).catch(console.error);
    // Super-Admin-only endpoints: fetched regardless, the backend 403s a
    // non-Super-Admin caller and these simply stay empty (RBAC is enforced
    // server-side; the tabs below just don't render for other roles).
    api.getAuditLogs(token).then(setAuditLogs).catch(() => {});
    api.getAuditLogsSummary(token).then(setAuditSummary).catch(() => {});
    api.getAdminUsers(token).then(setUsers).catch(() => {});

    // Prefill the branding form with the real current values — without
    // this, saving would silently overwrite fields like maintenance_mode
    // back to the form's hardcoded defaults, since the backend treats any
    // key present in the request body as an intentional update.
    api.getPublicSettings().then((s: any) => {
      setBranding((b) => ({
        ...b,
        platform_name: s.platform_name ?? b.platform_name,
        support_email: s.support_email ?? b.support_email,
        support_phone: s.support_phone ?? b.support_phone,
        maintenance_mode: !!s.maintenance_mode,
        default_currency: s.default_currency ?? b.default_currency,
      }));
      setBrandingAssets({ logo_light: s.logo_light, logo_dark: s.logo_dark, favicon: s.favicon });
      setSocialLinks(s.social_links || {});
    }).catch(() => {});
  }, []);

  const handleUploadBrandingAsset = async (kind: "logo_light" | "logo_dark" | "favicon", file: File | null) => {
    if (!file) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setUploadingKind(kind);
    try {
      const res = await api.uploadBrandingAsset(token, kind, file);
      setBrandingAssets((a) => ({ ...a, [kind]: res.url }));
    } catch (err: any) {
      alert("Upload failed: " + err.message);
    } finally {
      setUploadingKind(null);
    }
  };


  const [newStaff, setNewStaff] = useState({ email: "", username: "", password: "", full_name: "", role: "ADMIN" });
  const [creatingStaff, setCreatingStaff] = useState(false);

  const handleCreateStaff = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setCreatingStaff(true);
    try {
      await api.createStaffAccount(token, newStaff);
      alert(`Staff account created: ${newStaff.email} (${newStaff.role})`);
      setNewStaff({ email: "", username: "", password: "", full_name: "", role: "ADMIN" });
      api.getAdminUsers(token).then(setUsers).catch(console.error);
    } catch (err: any) {
      alert("Failed to create staff account: " + err.message);
    } finally {
      setCreatingStaff(false);
    }
  };

  const handleUpdateRole = async (userId: string, newRole: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.updateUserRole(token, userId, newRole);
    setUsers(users.map(u => u.id === userId ? { ...u, role: newRole } : u));
    alert("Role updated.");
  };

  const handleUpdateProductPrice = async (productId: string, priceStr: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const price = parseFloat(priceStr);
    await api.updateAdminCatalogProduct(token, productId, { retail_price: price });
    alert("Price updated.");
  };

  const handleToggleProduct = async (productId: string, isActive: boolean) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.updateAdminCatalogProduct(token, productId, { is_active: !isActive });
    setCatalog(catalog.map(p => p.id === productId ? { ...p, is_active: !isActive } : p));
  };

  const handleSyncCatalog = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSyncing(true);
    try {
      const res = await api.syncCatalog(token);
      alert(`Sync completed! ${res.synced_countries} new countries, ${res.synced_products} new products, ${res.updated_products ?? 0} updated.`);
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

  const handleUpdateCommission = async (id: string, ratePct: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const rate = parseFloat(ratePct);
    if (Number.isNaN(rate) || rate < 0 || rate > 100) {
      alert("Commission rate must be a number between 0 and 100.");
      return;
    }
    try {
      await api.updateMerchantCommission(token, id, rate);
      setMerchants(merchants.map(m => m.id === id ? { ...m, commission_rate_pct: rate } : m));
    } catch (err: any) {
      alert("Failed to update commission: " + err.message);
    }
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
    await api.updateBranding(token, { ...branding, social_links: socialLinks });
    alert("Branding updated instantly! Changes live without redeploy.");
  };

  const handleSaveRateOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.overrideCurrency(token, {
      currency_code: overrideCurrency,
      is_manual_override: isOverride,
      manual_rate: parseFloat(manualRate),
    });
    alert(`Exchange rate for ${overrideCurrency} updated!`);
  };

  return (
    <div className="border-t-2 border-admin-600">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-8">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2 text-admin-400 text-xs font-bold uppercase tracking-wider mb-1">
            <Shield className="w-4 h-4" />
            <span>Operations &amp; Governance Center</span>
          </div>
          <h1 className="text-3xl font-extrabold text-white">Admin Control Console</h1>
        </div>

        <button
          onClick={handleSyncCatalog}
          disabled={syncing}
          className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl shadow-lg shadow-admin-900/30 flex items-center space-x-2 self-start"
        >
          <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} />
          <span>{syncing ? "Syncing VivaPe..." : "Sync VivaPe Catalog"}</span>
        </button>
      </div>

      {/* Metrics Ticker */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
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
          <div className="text-2xl font-black text-emerald-400 mt-1">{formatPrice(parseFloat(stats.total_revenue_usd || 0))}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-white/10">
          <div className="text-xs font-semibold text-slate-400">Active eSIMs Issued</div>
          <div className="text-2xl font-black text-cyan-400 mt-1">{stats.total_esims_issued}</div>
        </div>
      </div>

      {/* Tabs — Merchant/Payment approvals, Orders, and Catalog are shared
          Admin+Super-Admin operations; Branding, Users, Translations, and
          the audit-log half of "360° Logs" are Super-Admin-only, matching
          the backend's require_super_admin gate on those endpoints. */}
      <div className="flex space-x-2 border-b border-white/10 overflow-x-auto hide-scrollbar">
        {[
          { id: "overview", label: "Overview" },
          { id: "merchants", label: `Merchants (${merchants.filter(m => m.status === "PENDING").length})` },
          { id: "payments", label: `Manual Deposits (${payments.filter(p => p.status === "PENDING").length})` },
          { id: "orders", label: "Orders" },
          { id: "catalog", label: "Catalog" },
          ...(isSuperAdmin ? [{ id: "users", label: "Staff & Users" }] : []),
          ...(isSuperAdmin ? [{ id: "branding", label: "Dynamic Branding & Rates" }] : []),
          ...(isSuperAdmin ? [{ id: "translations", label: "Languages & Translations" }] : []),
          { id: "logs", label: `360° Logs (${auditLogs.length + supplierLogs.length})` }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`py-2 px-4 text-xs font-bold border-b-2 transition-colors ${
              activeTab === tab.id ? "border-admin-500 text-white" : "border-transparent text-slate-400 hover:text-slate-200"
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
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2">Business</th>
                  <th className="py-2">Contact</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Commission %</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {merchants.map((m) => (
                  <tr key={m.id}>
                    <td className="py-3 font-semibold text-white">{m.business_name}</td>
                    <td className="py-3 text-slate-300">{m.contact_phone}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        m.status === "APPROVED" ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"
                      }`}>{m.status}</span>
                    </td>
                    <td className="py-3">
                      {isSuperAdmin ? (
                        <input
                          type="number"
                          min={0}
                          max={100}
                          step={0.01}
                          defaultValue={m.commission_rate_pct}
                          key={`${m.id}-${m.commission_rate_pct}`}
                          onBlur={(e) => e.target.value !== String(m.commission_rate_pct) && handleUpdateCommission(m.id, e.target.value)}
                          className="w-16 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                        />
                      ) : (
                        <span className="text-slate-300">{m.commission_rate_pct}%</span>
                      )}
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
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
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
                          className="bg-admin-600 hover:bg-admin-500 text-white px-2.5 py-1 rounded text-[11px] font-bold"
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

      {/* Tab: Branding & Rates */}
      {activeTab === "branding" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-1">Dynamic Branding Editor</h3>
            <p className="text-xs text-slate-400 mb-6">Updates reflect instantly across all pages without redeployment.</p>
            
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
                <label className="text-xs text-slate-300 font-semibold block mb-1">Platform Base Currency</label>
                <select
                  value={branding.default_currency}
                  onChange={(e) => setBranding({ ...branding, default_currency: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                >
                  {["USD", "BDT", "EUR", "GBP", "AED", "SAR", "THB", "SGD"].map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
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
              <div className="grid grid-cols-3 gap-3">
                {([
                  { kind: "logo_light" as const, label: "Logo (Light)" },
                  { kind: "logo_dark" as const, label: "Logo (Dark)" },
                  { kind: "favicon" as const, label: "Favicon" },
                ]).map(({ kind, label }) => (
                  <div key={kind}>
                    <label className="text-xs text-slate-300 font-semibold block mb-1">{label}</label>
                    <div className="w-full aspect-square rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center overflow-hidden mb-1.5">
                      {brandingAssets[kind] ? (
                        <img src={`${API_BASE}${brandingAssets[kind]}`} alt={label} className="w-full h-full object-contain" />
                      ) : (
                        <span className="text-[10px] text-slate-600">No file</span>
                      )}
                    </div>
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/svg+xml,image/webp,image/x-icon"
                      disabled={uploadingKind === kind}
                      onChange={(e) => handleUploadBrandingAsset(kind, e.target.files?.[0] ?? null)}
                      className="w-full text-[10px] text-slate-400 file:me-2 file:py-1 file:px-2 file:rounded-md file:border-0 file:text-[10px] file:font-semibold file:bg-slate-800 file:text-slate-300"
                    />
                    {uploadingKind === kind && <p className="text-[10px] text-admin-400 mt-1">Uploading...</p>}
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5">
                <div>
                  <label htmlFor="maintenanceMode" className="text-xs text-slate-300 font-semibold block">Maintenance Mode</label>
                  <p className="text-[11px] text-slate-500 mt-0.5">Shows a maintenance page to everyone except admins.</p>
                </div>
                <input
                  id="maintenanceMode"
                  type="checkbox"
                  checked={branding.maintenance_mode}
                  onChange={(e) => setBranding({ ...branding, maintenance_mode: e.target.checked })}
                  className="w-5 h-5 rounded bg-slate-900 border-slate-700 accent-admin-500"
                />
              </div>
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-2">Social Links</label>
                <div className="grid grid-cols-2 gap-2">
                  {(["facebook", "instagram", "twitter", "youtube", "linkedin"] as const).map((platform) => (
                    <input
                      key={platform}
                      type="url"
                      placeholder={`${platform.charAt(0).toUpperCase()}${platform.slice(1)} URL`}
                      value={socialLinks[platform] || ""}
                      onChange={(e) => setSocialLinks({ ...socialLinks, [platform]: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                    />
                  ))}
                </div>
              </div>
              <button
                type="submit"
                className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
              >
                Save Branding Changes
              </button>
            </form>
          </div>

          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-1">Currency Rate Override</h3>
            <p className="text-xs text-slate-400 mb-6">Lock custom exchange rates to protect margins against volatility.</p>

            <form onSubmit={handleSaveRateOverride} className="space-y-4">
              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Currency</label>
                <select
                  value={overrideCurrency}
                  onChange={(e) => setOverrideCurrency(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                >
                  <option value="BDT">BDT — Bangladeshi Taka</option>
                  <option value="EUR">EUR — Euro</option>
                  <option value="GBP">GBP — British Pound</option>
                  <option value="SAR">SAR — Saudi Riyal</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-300 font-semibold block mb-1">Manual Rate per 1 USD</label>
                <input
                  type="number"
                  step="0.01"
                  value={manualRate}
                  onChange={(e) => setManualRate(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="lockRate"
                  checked={isOverride}
                  onChange={(e) => setIsOverride(e.target.checked)}
                  className="rounded bg-slate-900 border-slate-700"
                />
                <label htmlFor="lockRate" className="text-xs text-slate-300">Lock Manual Rate (Ignore auto live API)</label>
              </div>

              <button
                type="submit"
                className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
              >
                Save Rate Override
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Tab: Languages & Translations (Super Admin only) */}
      {activeTab === "translations" && isSuperAdmin && (
        <TranslationsManager languages={appLanguages} />
      )}

      {/* Tab: Orders Viewer */}
      {activeTab === "orders" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-4">Customer Orders & Support</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2">Order No</th>
                  <th className="py-2">Date</th>
                  <th className="py-2">Customer</th>
                  <th className="py-2">Product</th>
                  <th className="py-2">Amount</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">eSIM</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {allOrders.map((o) => (
                  <tr key={o.id}>
                    <td className="py-2.5 font-mono text-admin-400">{o.order_no}</td>
                    <td className="py-2.5 text-slate-400">{new Date(o.created_at).toLocaleString()}</td>
                    <td className="py-2.5 text-slate-200">{o.email}</td>
                    <td className="py-2.5 text-slate-200">{o.product_title}</td>
                    <td className="py-2.5 font-bold text-emerald-400">{formatPrice(o.total_amount)}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        o.status === 'COMPLETED' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'
                      }`}>{o.status}</span>
                    </td>
                    <td className="py-2.5">
                      {o.iccid ? (
                        <button onClick={() => setInspectingLog(o)} className="font-mono text-[10px] text-admin-300 hover:text-admin-200 underline underline-offset-2">
                          {o.iccid.slice(0, 8)}... {o.is_mock_fallback && <span className="text-amber-400">(mock)</span>}
                        </button>
                      ) : (
                        <span className="text-[10px] text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Catalog Editor */}
      {activeTab === "catalog" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-4">Product Catalog & Pricing Editor</h3>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto frozen-col-table">
            <table className="w-full text-start text-xs relative">
              <thead className="text-slate-400 border-b border-white/10 sticky top-0 bg-slate-900">
                <tr>
                  <th className="py-2">Country</th>
                  <th className="py-2">Product</th>
                  <th className="py-2">Data / Validity</th>
                  <th className="py-2">Base Cost</th>
                  <th className="py-2">Retail Price</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {catalog.map((p) => (
                  <tr key={p.id}>
                    <td className="py-2.5 font-bold text-white">{p.country}</td>
                    <td className="py-2.5 text-admin-300">{p.title}</td>
                    <td className="py-2.5 text-slate-400">{p.data_gb} GB / {p.validity_days} Days</td>
                    <td className="py-2.5 text-slate-400">{formatPrice(p.cost_price)}</td>
                    <td className="py-2.5">
                      <input 
                        type="number" 
                        step="0.01" 
                        defaultValue={p.retail_price}
                        onBlur={(e) => handleUpdateProductPrice(p.id, e.target.value)}
                        className="bg-slate-950 border border-slate-700 rounded px-2 py-1 w-20 text-white"
                      />
                    </td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        p.is_active ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'
                      }`}>{p.is_active ? 'ACTIVE' : 'INACTIVE'}</span>
                    </td>
                    <td className="py-2.5">
                      <button 
                        onClick={() => handleToggleProduct(p.id, p.is_active)}
                        className="text-xs bg-slate-800 hover:bg-slate-700 px-3 py-1 rounded"
                      >
                        Toggle
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Staff & Users */}
      {activeTab === "users" && (
        <div className="space-y-6">
        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-1">Create Staff Account</h3>
          <p className="text-xs text-slate-400 mb-4">Directly creates an Admin or Super Admin account - existing users are promoted via the role dropdown below instead.</p>
          <form onSubmit={handleCreateStaff} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Email</label>
              <input type="email" required value={newStaff.email} onChange={(e) => setNewStaff({ ...newStaff, email: e.target.value })} className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Username</label>
              <input type="text" required value={newStaff.username} onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })} className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Password</label>
              <input type="password" required minLength={8} value={newStaff.password} onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })} className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold block mb-1">Role</label>
              <select value={newStaff.role} onChange={(e) => setNewStaff({ ...newStaff, role: e.target.value })} className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
                <option value="ADMIN">Admin</option>
                <option value="SUPER_ADMIN">Super Admin</option>
              </select>
            </div>
            <button type="submit" disabled={creatingStaff} className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
              {creatingStaff ? "Creating..." : "Create Account"}
            </button>
          </form>
        </div>

        <div className="glass-panel rounded-2xl p-6 border border-white/10">
          <h3 className="text-base font-bold text-white mb-4">Staff & User Management</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-400 border-b border-white/10">
                <tr>
                  <th className="py-2">User ID</th>
                  <th className="py-2">Email</th>
                  <th className="py-2">Role</th>
                  <th className="py-2">Joined</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="py-2.5 font-mono text-slate-400">{u.id.substring(0,8)}...</td>
                    <td className="py-2.5 text-slate-200">{u.email}</td>
                    <td className="py-2.5 font-bold text-admin-400">{u.role}</td>
                    <td className="py-2.5 text-slate-400">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="py-2.5 space-x-2">
                      <select 
                        value={u.role} 
                        onChange={(e) => handleUpdateRole(u.id, e.target.value)}
                        className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-white"
                      >
                        <option value="USER">User</option>
                        <option value="MERCHANT">Merchant</option>
                        <option value="ADMIN">Admin</option>
                        <option value="SUPER_ADMIN">Super Admin</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </div>
      )}

      {/* Tab: 360 Logs Viewer */}
      {activeTab === "logs" && (
        <div className="space-y-6">
          {/* Supplier API Logs */}
          <div className="glass-panel rounded-2xl p-6 border border-white/10">
            <h3 className="text-base font-bold text-white mb-1 flex items-center space-x-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <span>VivaPe Upstream Supplier API Traffic Log</span>
            </h3>
            <p className="text-xs text-slate-400 mb-4">Every external supplier API request, status, and latency.</p>

            <div className="overflow-x-auto max-h-80 overflow-y-auto">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-400 border-b border-white/10 sticky top-0 bg-slate-900">
                  <tr>
                    <th className="py-2">Time</th>
                    <th className="py-2">Method</th>
                    <th className="py-2">Endpoint</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5 font-mono">
                  {supplierLogs.map((log) => (
                    <tr key={log.id} onClick={() => setInspectingLog(log)} className="cursor-pointer hover:bg-white/5">
                      <td className="py-2.5 text-slate-400">{new Date(log.created_at).toLocaleTimeString()}</td>
                      <td className="py-2.5 font-bold text-admin-400">{log.method}</td>
                      <td className="py-2.5 text-slate-200">/{log.endpoint}</td>
                      <td className="py-2.5">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          log.status_code === 200 ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                        }`}>{log.status_code}</span>
                      </td>
                      <td className="py-2.5 text-slate-400">{log.latency_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Audit Logs — Super Admin only, matching the backend's
              require_super_admin gate on GET /admin/audit-logs. */}
          {isSuperAdmin ? (
            <div className="glass-panel rounded-2xl p-6 border border-white/10">
              <h3 className="text-base font-bold text-white mb-1 flex items-center space-x-2">
                <FileText className="w-4 h-4 text-amber-400" />
                <span>Administrative Audit Trail ("Log of Everything")</span>
              </h3>
              <p className="text-xs text-slate-400 mb-4">Tamper-evident logs of all administrative actions and parameter changes. Click a row to inspect the full before/after state.</p>

              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-start text-xs">
                  <thead className="text-slate-400 border-b border-white/10 sticky top-0 bg-slate-900">
                    <tr>
                      <th className="py-2">Time</th>
                      <th className="py-2">Role</th>
                      <th className="py-2">Action</th>
                      <th className="py-2">State Diff</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {auditLogs.map((log) => (
                      <tr key={log.id} onClick={() => setInspectingLog(log)} className="cursor-pointer hover:bg-white/5">
                        <td className="py-2.5 text-slate-400 font-mono">{new Date(log.created_at).toLocaleTimeString()}</td>
                        <td className="py-2.5 font-bold text-amber-400">{log.actor_role}</td>
                        <td className="py-2.5 font-semibold text-white">{log.action}</td>
                        <td className="py-2.5 font-mono text-[11px] text-slate-400 truncate max-w-xs">{JSON.stringify(log.after_state)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="glass-panel rounded-2xl p-6 border border-white/10">
              <h3 className="text-base font-bold text-white mb-1 flex items-center space-x-2">
                <FileText className="w-4 h-4 text-amber-400" />
                <span>Administrative Activity Summary</span>
              </h3>
              <p className="text-xs text-slate-400 mb-4">The full audit trail (before/after state, IP, user agent) is Super-Admin-only. This is a summarized view of what's happened.</p>

              {auditSummary && (
                <>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {Object.entries(auditSummary.action_counts).map(([action, count]) => (
                      <span key={action} className="text-[10px] font-bold px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-300">
                        {action}: <span className="text-admin-400">{count}</span>
                      </span>
                    ))}
                  </div>
                  <div className="overflow-x-auto max-h-80 overflow-y-auto">
                    <table className="w-full text-start text-xs">
                      <thead className="text-slate-400 border-b border-white/10 sticky top-0 bg-slate-900">
                        <tr>
                          <th className="py-2">Time</th>
                          <th className="py-2">Role</th>
                          <th className="py-2">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {auditSummary.recent.map((log) => (
                          <tr key={log.id}>
                            <td className="py-2.5 text-slate-400 font-mono">{new Date(log.created_at).toLocaleTimeString()}</td>
                            <td className="py-2.5 font-bold text-amber-400">{log.actor_role}</td>
                            <td className="py-2.5 font-semibold text-white">{log.action}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* JSON Inspect Modal — for both supplier and audit log rows */}
      {inspectingLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4" onClick={() => setInspectingLog(null)}>
          <div className="glass-panel rounded-2xl max-w-2xl w-full p-6 border border-white/20 shadow-2xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-white">Log Entry Detail</h3>
              <button onClick={() => setInspectingLog(null)} aria-label="Close" className="p-1 rounded-lg text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <pre className="text-[11px] font-mono text-slate-300 bg-slate-950 p-4 rounded-xl overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(inspectingLog, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10 text-xs text-slate-400 space-y-2">
          <p className="font-semibold text-white">System Status: Operational &bull; Live Domain https://esim.salmandev.io</p>
          <p>Connected to Upstream VivaPe API &amp; ShurjoPay Sandbox Gateway.</p>
          <p>Exchange rates synchronized keylessly from open.er-api.com with manual admin override support.</p>
        </div>
      )}

    </div>
    </div>
  );
}
