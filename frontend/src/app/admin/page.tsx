"use client";

import React, { useState, useEffect } from "react";
import { Shield, Users, ShoppingCart, DollarSign, Wifi, RefreshCw, Check, X, Sliders, Globe, FileText, Activity, Languages } from "lucide-react";
import { api, API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import TranslationsManager from "@/components/TranslationsManager";

type TabId = "overview" | "orders" | "catalog" | "users" | "merchants" | "payments" | "branding" | "translations" | "logs" | "kyc" | "customer-wallet";

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
  // Catalog editor: syncing every country (not just ten popular ones) grew
  // this from ~135 rows to thousands, so it's searched and paged
  // server-side rather than dumping a newest-200 slice into the table.
  const catalogPageSize = 100;
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogActiveFilter, setCatalogActiveFilter] = useState<"all" | "active" | "inactive">("all");
  const [catalogPage, setCatalogPage] = useState(0);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogNotice, setCatalogNotice] = useState<string | null>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [inspectingLog, setInspectingLog] = useState<any | null>(null);
  const [kycQueue, setKycQueue] = useState<any[]>([]);
  const [commissionTiers, setCommissionTiers] = useState<any[]>([]);
  const [newTier, setNewTier] = useState({ min_volume_usd: "", rate_pct: "" });
  const [expandedApiPanel, setExpandedApiPanel] = useState<string | null>(null);
  const [apiKeyStatuses, setApiKeyStatuses] = useState<Record<string, any>>({});
  const [revealedApiKeys, setRevealedApiKeys] = useState<Record<string, string>>({});
  const [apiKeyBusy, setApiKeyBusy] = useState<string | null>(null);
  const [viewingDoc, setViewingDoc] = useState<{ url: string; side: string; contentType: string } | null>(null);

  // Customer Wallet tab — admin-triggered wallet recharge & purchase-for-customer
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerResults, setCustomerResults] = useState<any[]>([]);
  const [customerSearching, setCustomerSearching] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<any | null>(null);
  const [rechargeAmount, setRechargeAmount] = useState("");
  const [rechargeNote, setRechargeNote] = useState("");
  const [rechargingWallet, setRechargingWallet] = useState(false);
  const [purchaseCountries, setPurchaseCountries] = useState<any[]>([]);
  const [purchaseCountry, setPurchaseCountry] = useState("");
  const [purchaseProducts, setPurchaseProducts] = useState<any[]>([]);
  const [purchaseProductId, setPurchaseProductId] = useState("");
  const [purchasingEsim, setPurchasingEsim] = useState(false);
  const [purchaseResult, setPurchaseResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [branding, setBranding] = useState({ platform_name: "eSIM Global", support_email: "support@esim.local", support_phone: "+880 1700-000000", maintenance_mode: false, default_currency: "USD", seo_title: "", seo_description: "" });
  const [socialLinks, setSocialLinks] = useState<Record<string, string>>({});
  const [brandingAssets, setBrandingAssets] = useState<{ logo_light?: string; logo_dark?: string; favicon?: string; og_image?: string; bangla_qr_image?: string }>({});
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
    loadCatalog(token, { offset: 0 });
    api.getKycQueue(token).then(setKycQueue).catch(console.error);
    api.getCommissionTiers(token).then(setCommissionTiers).catch(console.error);
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
        seo_title: s.seo_title ?? "",
        seo_description: s.seo_description ?? "",
      }));
      setBrandingAssets({ logo_light: s.logo_light, logo_dark: s.logo_dark, favicon: s.favicon, og_image: s.og_image, bangla_qr_image: s.bangla_qr_image });
      setSocialLinks(s.social_links || {});
    }).catch(() => {});
  }, []);

  const handleUploadBrandingAsset = async (kind: "logo_light" | "logo_dark" | "favicon" | "og_image" | "bangla_qr_image", file: File | null) => {
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

  const loadCatalog = async (token: string, opts?: { q?: string; is_active?: boolean; offset?: number }) => {
    setCatalogLoading(true);
    try {
      const offset = opts?.offset ?? 0;
      const res = await api.getAdminCatalog(token, { ...opts, offset, limit: catalogPageSize });
      setCatalog(res.items || []);
      setCatalogTotal(res.total || 0);
      setCatalogPage(Math.floor(offset / catalogPageSize));
    } catch (err: any) {
      setCatalogNotice("Failed to load catalog: " + err.message);
    } finally {
      setCatalogLoading(false);
    }
  };

  const catalogFilterArgs = (offset: number) => ({
    q: catalogQuery.trim() || undefined,
    is_active: catalogActiveFilter === "all" ? undefined : catalogActiveFilter === "active",
    offset,
  });

  const handleSearchCatalog = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setCatalogNotice(null);
    await loadCatalog(token, catalogFilterArgs(0));
  };

  const handleCatalogPageChange = async (nextPage: number) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await loadCatalog(token, catalogFilterArgs(nextPage * catalogPageSize));
  };

  const handleUpdateProductPrice = async (productId: string, priceStr: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const price = parseFloat(priceStr);
    if (Number.isNaN(price) || price < 0) {
      setCatalogNotice("Retail price must be a non-negative number.");
      return;
    }
    try {
      await api.updateAdminCatalogProduct(token, productId, { retail_price: price });
      setCatalog(catalog.map(p => p.id === productId ? { ...p, retail_price: price } : p));
      setCatalogNotice("Price updated.");
    } catch (err: any) {
      setCatalogNotice("Failed to update price: " + err.message);
    }
  };

  const handleToggleProduct = async (productId: string, isActive: boolean) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    try {
      await api.updateAdminCatalogProduct(token, productId, { is_active: !isActive });
      setCatalog(catalog.map(p => p.id === productId ? { ...p, is_active: !isActive } : p));
    } catch (err: any) {
      setCatalogNotice("Failed to update product: " + err.message);
    }
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

  const handleToggleApiPanel = async (merchantId: string) => {
    if (expandedApiPanel === merchantId) {
      setExpandedApiPanel(null);
      return;
    }
    setExpandedApiPanel(merchantId);
    const token = localStorage.getItem("esim_token");
    if (!token || apiKeyStatuses[merchantId]) return;
    try {
      const status = await api.getPartnerApiKeyStatus(token, merchantId);
      setApiKeyStatuses(prev => ({ ...prev, [merchantId]: status }));
    } catch (err: any) {
      alert("Failed to load API key status: " + err.message);
    }
  };

  const handleGenerateApiKey = async (merchantId: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setApiKeyBusy(merchantId);
    try {
      const result = await api.generatePartnerApiKey(token, merchantId);
      setRevealedApiKeys(prev => ({ ...prev, [merchantId]: result.api_key }));
      setApiKeyStatuses(prev => ({ ...prev, [merchantId]: { has_active_key: true, key_prefix: result.key_prefix, created_at: new Date().toISOString(), last_used_at: null } }));
    } catch (err: any) {
      alert("Failed to generate API key: " + err.message);
    } finally {
      setApiKeyBusy(null);
    }
  };

  const handleRevokeApiKey = async (merchantId: string) => {
    if (!confirm("Revoke this partner's active API key? Their integration will stop working immediately.")) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setApiKeyBusy(merchantId);
    try {
      await api.revokePartnerApiKey(token, merchantId);
      setApiKeyStatuses(prev => ({ ...prev, [merchantId]: { has_active_key: false } }));
      setRevealedApiKeys(prev => { const next = { ...prev }; delete next[merchantId]; return next; });
    } catch (err: any) {
      alert("Failed to revoke API key: " + err.message);
    } finally {
      setApiKeyBusy(null);
    }
  };

  const handleSearchCustomers = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token || customerQuery.trim().length < 2) return;
    setCustomerSearching(true);
    try {
      const results = await api.searchAdminCustomers(token, customerQuery.trim());
      setCustomerResults(results);
    } catch (err: any) {
      alert("Search failed: " + err.message);
    } finally {
      setCustomerSearching(false);
    }
  };

  const handleSelectCustomer = (customer: any) => {
    setSelectedCustomer(customer);
    setRechargeAmount("");
    setRechargeNote("");
    setPurchaseCountry("");
    setPurchaseProducts([]);
    setPurchaseProductId("");
    setPurchaseResult(null);
    if (purchaseCountries.length === 0) {
      api.getCountries(undefined, true).then(setPurchaseCountries).catch(console.error);
    }
  };

  const handleRechargeWallet = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token || !selectedCustomer) return;
    const amount = parseFloat(rechargeAmount);
    if (Number.isNaN(amount) || amount <= 0) {
      alert("Enter a valid positive amount.");
      return;
    }
    setRechargingWallet(true);
    try {
      const res = await api.rechargeCustomerWallet(token, selectedCustomer.id, rechargeAmount, rechargeNote || undefined);
      setSelectedCustomer({ ...selectedCustomer, wallet_balance: res.new_balance });
      setCustomerResults(customerResults.map(c => c.id === selectedCustomer.id ? { ...c, wallet_balance: res.new_balance } : c));
      setRechargeAmount("");
      setRechargeNote("");
    } catch (err: any) {
      alert("Recharge failed: " + err.message);
    } finally {
      setRechargingWallet(false);
    }
  };

  const handleSelectPurchaseCountry = async (iso2: string) => {
    setPurchaseCountry(iso2);
    setPurchaseProductId("");
    if (!iso2) {
      setPurchaseProducts([]);
      return;
    }
    try {
      const products = await api.getCountryProducts(iso2);
      setPurchaseProducts(products);
    } catch (err: any) {
      alert("Failed to load products: " + err.message);
    }
  };

  const handlePurchaseEsimForCustomer = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token || !selectedCustomer || !purchaseProductId) return;
    setPurchasingEsim(true);
    setPurchaseResult(null);
    try {
      const res = await api.adminPurchaseEsimForCustomer(token, selectedCustomer.id, purchaseProductId);
      setPurchaseResult({ ok: true, message: `Order ${res.order_no} completed — eSIM issued.` });
      const product = purchaseProducts.find(p => p.id === purchaseProductId);
      const price = product ? parseFloat(product.retail_price) : 0;
      const newBalance = selectedCustomer.wallet_balance - price;
      setSelectedCustomer({ ...selectedCustomer, wallet_balance: newBalance });
      setCustomerResults(customerResults.map(c => c.id === selectedCustomer.id ? { ...c, wallet_balance: newBalance } : c));
    } catch (err: any) {
      setPurchaseResult({ ok: false, message: err.message || "Purchase failed." });
    } finally {
      setPurchasingEsim(false);
    }
  };

  const handleCreateCommissionTier = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const minVolume = parseFloat(newTier.min_volume_usd);
    const rate = parseFloat(newTier.rate_pct);
    if (Number.isNaN(minVolume) || Number.isNaN(rate)) {
      alert("Enter valid numbers for both fields.");
      return;
    }
    try {
      const tier = await api.createCommissionTier(token, minVolume, rate);
      setCommissionTiers([...commissionTiers, tier].sort((a, b) => a.min_volume_usd - b.min_volume_usd));
      setNewTier({ min_volume_usd: "", rate_pct: "" });
    } catch (err: any) {
      alert("Failed to create tier: " + err.message);
    }
  };

  const handleDeleteCommissionTier = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    if (!window.confirm("Remove this commission tier?")) return;
    await api.deleteCommissionTier(token, id);
    setCommissionTiers(commissionTiers.filter((t) => t.id !== id));
  };

  const handleApproveKyc = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    await api.approveKyc(token, id);
    setKycQueue(kycQueue.map(k => k.id === id ? { ...k, status: "APPROVED" } : k));
  };

  const handleRejectKyc = async (id: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const reason = window.prompt("Reason for rejection (shown to the user):");
    if (reason === null) return;
    await api.rejectKyc(token, id, reason);
    setKycQueue(kycQueue.map(k => k.id === id ? { ...k, status: "REJECTED", rejection_reason: reason } : k));
  };

  const handleViewKycDocument = async (submissionId: string, side: "front" | "back") => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    try {
      const { url, contentType } = await api.getKycDocumentUrl(token, submissionId, side);
      setViewingDoc({ url, side, contentType });
    } catch (err: any) {
      alert("Failed to load document: " + err.message);
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
          <div className="flex items-center space-x-2 text-admin-600 text-xs font-bold uppercase tracking-wider mb-1">
            <Shield className="w-4 h-4" />
            <span>Operations &amp; Governance Center</span>
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900">Admin Control Console</h1>
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
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-xs font-semibold text-slate-500">Total Users</div>
          <div className="text-2xl font-black text-slate-900 mt-1">{stats.total_users}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-xs font-semibold text-slate-500">Total Orders</div>
          <div className="text-2xl font-black text-slate-900 mt-1">{stats.total_orders}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-xs font-semibold text-slate-500">Total Revenue (USD)</div>
          <div className="text-2xl font-black text-emerald-600 mt-1">{formatPrice(parseFloat(stats.total_revenue_usd || 0))}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-xs font-semibold text-slate-500">Active eSIMs Issued</div>
          <div className="text-2xl font-black text-cyan-600 mt-1">{stats.total_esims_issued}</div>
        </div>
      </div>

      {/* Tabs — Merchant/Payment approvals, Orders, and Catalog are shared
          Admin+Super-Admin operations; Branding, Users, Translations, and
          the audit-log half of "360° Logs" are Super-Admin-only, matching
          the backend's require_super_admin gate on those endpoints. */}
      <div className="flex space-x-2 border-b border-gray-200 overflow-x-auto hide-scrollbar">
        {[
          { id: "overview", label: "Overview" },
          { id: "merchants", label: `Merchants (${merchants.filter(m => m.status === "PENDING").length})` },
          { id: "payments", label: `Manual Deposits (${payments.filter(p => p.status === "PENDING").length})` },
          { id: "orders", label: "Orders" },
          { id: "catalog", label: "Catalog" },
          { id: "customer-wallet", label: "Customer Wallet" },
          ...(isSuperAdmin ? [{ id: "users", label: "Staff & Users" }] : []),
          ...(isSuperAdmin ? [{ id: "branding", label: "Dynamic Branding & Rates" }] : []),
          ...(isSuperAdmin ? [{ id: "translations", label: "Languages & Translations" }] : []),
          { id: "logs", label: `360° Logs (${auditLogs.length + supplierLogs.length})` },
          { id: "kyc", label: `KYC Review (${kycQueue.filter(k => k.status === "PENDING").length})` }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`py-2 px-4 text-xs font-bold border-b-2 transition-colors ${
              activeTab === tab.id ? "border-admin-500 text-admin-700" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab: Merchants */}
      {activeTab === "merchants" && (
        <div className="space-y-6">
        {isSuperAdmin && (
          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h3 className="text-base font-bold text-slate-900 mb-1">Commission Tiers</h3>
            <p className="text-xs text-slate-500 mb-4">
              Volume-based rates that override a merchant's flat commission % once their cumulative completed reseller-order volume crosses a threshold. Leave empty for flat-rate-only.
            </p>
            <div className="flex flex-wrap gap-2 mb-4">
              {commissionTiers.length === 0 ? (
                <span className="text-xs text-slate-500">No tiers configured — every merchant uses their own flat rate.</span>
              ) : (
                commissionTiers.map((t) => (
                  <span key={t.id} className="flex items-center gap-2 text-[11px] font-bold px-2.5 py-1.5 rounded-lg bg-white border border-gray-300 text-slate-700">
                    ${t.min_volume_usd}+ &rarr; <span className="text-admin-600">{t.rate_pct}%</span>
                    {isSuperAdmin && (
                      <button onClick={() => handleDeleteCommissionTier(t.id)} aria-label="Remove tier" className="text-slate-500 hover:text-rose-600">
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </span>
                ))
              )}
            </div>
            <form onSubmit={handleCreateCommissionTier} className="flex flex-wrap items-end gap-3">
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Min. Volume (USD)</label>
                <input type="number" min={0} step="0.01" required value={newTier.min_volume_usd} onChange={(e) => setNewTier({ ...newTier, min_volume_usd: e.target.value })} className="w-32 bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Rate %</label>
                <input type="number" min={0} max={100} step="0.01" required value={newTier.rate_pct} onChange={(e) => setNewTier({ ...newTier, rate_pct: e.target.value })} className="w-24 bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
              </div>
              <button type="submit" className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">Add Tier</button>
            </form>
          </div>
        )}
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-4">Partner &amp; Reseller Applications</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2">Business</th>
                  <th className="py-2">Contact</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Commission %</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {merchants.map((m) => (
                  <React.Fragment key={m.id}>
                  <tr>
                    <td className="py-3 font-semibold text-slate-900">{m.business_name}</td>
                    <td className="py-3 text-slate-700">{m.contact_phone}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        m.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
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
                          className="w-16 bg-white border border-gray-300 rounded px-2 py-1 text-xs text-slate-900"
                        />
                      ) : (
                        <span className="text-slate-700">{m.commission_rate_pct}%</span>
                      )}
                    </td>
                    <td className="py-3 flex gap-2">
                      {m.status === "PENDING" && (
                        <button
                          onClick={() => handleApproveMerchant(m.id)}
                          className="bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 rounded text-[11px] font-bold"
                        >
                          Approve Partner
                        </button>
                      )}
                      {m.status === "APPROVED" && (
                        <button
                          onClick={() => handleToggleApiPanel(m.id)}
                          className="bg-gray-100 hover:bg-gray-200 text-slate-700 px-2.5 py-1 rounded text-[11px] font-bold"
                        >
                          {expandedApiPanel === m.id ? "Hide API Access" : "API Access"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedApiPanel === m.id && (
                    <tr>
                      <td colSpan={5} className="py-4 bg-gray-50">
                        <div className="px-3">
                          <h4 className="text-xs font-bold text-slate-900 mb-2">Partner Reseller API Access</h4>
                          {!apiKeyStatuses[m.id] ? (
                            <span className="text-xs text-slate-500">Loading...</span>
                          ) : (
                            <div className="flex flex-col gap-2">
                              <div className="flex items-center gap-3 text-xs text-slate-700">
                                <span>Status:</span>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${apiKeyStatuses[m.id].has_active_key ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-slate-500"}`}>
                                  {apiKeyStatuses[m.id].has_active_key ? "ACTIVE" : "NO KEY ISSUED"}
                                </span>
                                {apiKeyStatuses[m.id].has_active_key && (
                                  <span className="font-mono text-slate-500">{apiKeyStatuses[m.id].key_prefix}...</span>
                                )}
                              </div>
                              {revealedApiKeys[m.id] && (
                                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-[11px]">
                                  <p className="text-amber-600 font-bold mb-1">Copy this key now — it will not be shown again:</p>
                                  <code className="block break-all text-slate-900 bg-gray-50 rounded px-2 py-1">{revealedApiKeys[m.id]}</code>
                                </div>
                              )}
                              {isSuperAdmin && (
                                <div className="flex gap-2 mt-1">
                                  <button
                                    disabled={apiKeyBusy === m.id}
                                    onClick={() => handleGenerateApiKey(m.id)}
                                    className="bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white px-2.5 py-1 rounded text-[11px] font-bold"
                                  >
                                    {apiKeyStatuses[m.id].has_active_key ? "Regenerate Key" : "Generate Key"}
                                  </button>
                                  {apiKeyStatuses[m.id].has_active_key && (
                                    <button
                                      disabled={apiKeyBusy === m.id}
                                      onClick={() => handleRevokeApiKey(m.id)}
                                      className="bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white px-2.5 py-1 rounded text-[11px] font-bold"
                                    >
                                      Revoke Key
                                    </button>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </div>
      )}

      {/* Tab: Payments */}
      {activeTab === "payments" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-4">Manual Payment Verification Queue</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2">Amount</th>
                  <th className="py-2">Method</th>
                  <th className="py-2">TxID</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {payments.map((p) => (
                  <tr key={p.id}>
                    <td className="py-3 font-bold font-mono text-emerald-600">{p.amount} {p.currency}</td>
                    <td className="py-3 text-slate-700">{p.bank_name}</td>
                    <td className="py-3 font-mono text-slate-500">{p.transaction_id}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        p.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
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
          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h3 className="text-base font-bold text-slate-900 mb-1">Dynamic Branding Editor</h3>
            <p className="text-xs text-slate-500 mb-6">Updates reflect instantly across all pages without redeployment.</p>
            
            <form onSubmit={handleUpdateBranding} className="space-y-4">
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Platform Brand Name</label>
                <input
                  type="text"
                  value={branding.platform_name}
                  onChange={(e) => setBranding({ ...branding, platform_name: e.target.value })}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Platform Base Currency</label>
                <select
                  value={branding.default_currency}
                  onChange={(e) => setBranding({ ...branding, default_currency: e.target.value })}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                >
                  {["USD", "BDT", "EUR", "GBP", "AED", "SAR", "THB", "SGD"].map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Support Email</label>
                <input
                  type="email"
                  value={branding.support_email}
                  onChange={(e) => setBranding({ ...branding, support_email: e.target.value })}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">SEO Title</label>
                <input
                  type="text"
                  placeholder={branding.platform_name || "eSIM Global"}
                  value={branding.seo_title}
                  onChange={(e) => setBranding({ ...branding, seo_title: e.target.value })}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">SEO Meta Description</label>
                <textarea
                  rows={2}
                  placeholder="Shown in search results and social previews"
                  value={branding.seo_description}
                  onChange={(e) => setBranding({ ...branding, seo_description: e.target.value })}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 resize-none"
                />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {([
                  { kind: "logo_light" as const, label: "Logo (Light)" },
                  { kind: "logo_dark" as const, label: "Logo (Dark)" },
                  { kind: "favicon" as const, label: "Favicon" },
                  { kind: "og_image" as const, label: "OG Share Image" },
                  { kind: "bangla_qr_image" as const, label: "Bangla QR Code" },
                ]).map(({ kind, label }) => (
                  <div key={kind}>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">{label}</label>
                    <div className="w-full aspect-square rounded-lg bg-white border border-gray-300 flex items-center justify-center overflow-hidden mb-1.5">
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
                      className="w-full text-[10px] text-slate-500 file:me-2 file:py-1 file:px-2 file:rounded-md file:border-0 file:text-[10px] file:font-semibold file:bg-gray-100 file:text-slate-700"
                    />
                    {uploadingKind === kind && <p className="text-[10px] text-admin-600 mt-1">Uploading...</p>}
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between bg-white border border-gray-300 rounded-lg px-3 py-2.5">
                <div>
                  <label htmlFor="maintenanceMode" className="text-xs text-slate-700 font-semibold block">Maintenance Mode</label>
                  <p className="text-[11px] text-slate-500 mt-0.5">Shows a maintenance page to everyone except admins.</p>
                </div>
                <input
                  id="maintenanceMode"
                  type="checkbox"
                  checked={branding.maintenance_mode}
                  onChange={(e) => setBranding({ ...branding, maintenance_mode: e.target.checked })}
                  className="w-5 h-5 rounded bg-white border-gray-300 accent-admin-500"
                />
              </div>
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-2">Social Links</label>
                <div className="grid grid-cols-2 gap-2">
                  {(["facebook", "instagram", "twitter", "youtube", "linkedin"] as const).map((platform) => (
                    <input
                      key={platform}
                      type="url"
                      placeholder={`${platform.charAt(0).toUpperCase()}${platform.slice(1)} URL`}
                      value={socialLinks[platform] || ""}
                      onChange={(e) => setSocialLinks({ ...socialLinks, [platform]: e.target.value })}
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
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

          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h3 className="text-base font-bold text-slate-900 mb-1">Currency Rate Override</h3>
            <p className="text-xs text-slate-500 mb-6">Lock custom exchange rates to protect margins against volatility.</p>

            <form onSubmit={handleSaveRateOverride} className="space-y-4">
              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Currency</label>
                <select
                  value={overrideCurrency}
                  onChange={(e) => setOverrideCurrency(e.target.value)}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                >
                  <option value="BDT">BDT — Bangladeshi Taka</option>
                  <option value="EUR">EUR — Euro</option>
                  <option value="GBP">GBP — British Pound</option>
                  <option value="SAR">SAR — Saudi Riyal</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-700 font-semibold block mb-1">Manual Rate per 1 USD</label>
                <input
                  type="number"
                  step="0.01"
                  value={manualRate}
                  onChange={(e) => setManualRate(e.target.value)}
                  className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                />
              </div>

              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="lockRate"
                  checked={isOverride}
                  onChange={(e) => setIsOverride(e.target.checked)}
                  className="rounded bg-white border-gray-300"
                />
                <label htmlFor="lockRate" className="text-xs text-slate-700">Lock Manual Rate (Ignore auto live API)</label>
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
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-4">Customer Orders & Support</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
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
              <tbody className="divide-y divide-gray-100">
                {allOrders.map((o) => (
                  <tr key={o.id}>
                    <td className="py-2.5 font-mono text-admin-600">{o.order_no}</td>
                    <td className="py-2.5 text-slate-500">{new Date(o.created_at).toLocaleString()}</td>
                    <td className="py-2.5 text-slate-700">{o.email}</td>
                    <td className="py-2.5 text-slate-700">{o.product_title}</td>
                    <td className="py-2.5 font-bold text-emerald-600">{formatPrice(o.total_amount)}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        o.status === 'COMPLETED' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
                      }`}>{o.status}</span>
                    </td>
                    <td className="py-2.5">
                      {o.iccid ? (
                        <button onClick={() => setInspectingLog(o)} className="font-mono text-[10px] text-admin-600 hover:text-admin-700 underline underline-offset-2">
                          {o.iccid.slice(0, 8)}... {o.is_mock_fallback && <span className="text-amber-600">(mock)</span>}
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
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-1">Product Catalog & Pricing Editor</h3>
          <p className="text-xs text-slate-500 mb-4">
            {catalogLoading ? "Loading…" : `${catalogTotal} product${catalogTotal === 1 ? "" : "s"} match`}
          </p>

          <form onSubmit={handleSearchCatalog} className="flex flex-wrap gap-2 mb-4">
            <input
              type="text"
              placeholder="Search by product or country…"
              value={catalogQuery}
              onChange={(e) => setCatalogQuery(e.target.value)}
              className="flex-1 min-w-[200px] bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
            />
            <select
              value={catalogActiveFilter}
              onChange={(e) => setCatalogActiveFilter(e.target.value as "all" | "active" | "inactive")}
              className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
            >
              <option value="all">All statuses</option>
              <option value="active">Active only</option>
              <option value="inactive">Inactive only</option>
            </select>
            <button type="submit" disabled={catalogLoading} className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2 rounded-lg">
              {catalogLoading ? "Searching…" : "Search"}
            </button>
          </form>

          {catalogNotice && (
            <div className="mb-4 p-3 rounded-lg text-xs bg-gray-50 border border-gray-200 text-slate-700">
              {catalogNotice}
            </div>
          )}

          <div className="overflow-x-auto max-h-[600px] overflow-y-auto frozen-col-table">
            <table className="w-full text-start text-xs relative">
              <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
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
              <tbody className="divide-y divide-gray-100">
                {catalog.map((p) => (
                  <tr key={p.id}>
                    <td className="py-2.5 font-bold text-slate-900">{p.country}</td>
                    <td className="py-2.5 text-slate-700">{p.title}</td>
                    <td className="py-2.5 text-slate-500">{p.is_unlimited ? "Unlimited" : `${p.data_gb} GB`} / {p.validity_days} Days</td>
                    <td className="py-2.5 text-slate-500">{formatPrice(p.cost_price)}</td>
                    <td className="py-2.5">
                      <input 
                        type="number" 
                        step="0.01" 
                        defaultValue={p.retail_price}
                        onBlur={(e) => handleUpdateProductPrice(p.id, e.target.value)}
                        className="bg-gray-50 border border-gray-300 rounded px-2 py-1 w-20 text-slate-900"
                      />
                    </td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        p.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
                      }`}>{p.is_active ? 'ACTIVE' : 'INACTIVE'}</span>
                    </td>
                    <td className="py-2.5">
                      <button 
                        onClick={() => handleToggleProduct(p.id, p.is_active)}
                        className="text-xs bg-gray-100 hover:bg-gray-200 px-3 py-1 rounded"
                      >
                        Toggle
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {catalogTotal > catalogPageSize && (
            <div className="flex items-center justify-between mt-4 text-xs text-slate-600">
              <span>
                Showing {catalogPage * catalogPageSize + 1}–{Math.min((catalogPage + 1) * catalogPageSize, catalogTotal)} of {catalogTotal}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => handleCatalogPageChange(catalogPage - 1)}
                  disabled={catalogPage === 0 || catalogLoading}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40 font-semibold"
                >
                  Previous
                </button>
                <button
                  onClick={() => handleCatalogPageChange(catalogPage + 1)}
                  disabled={(catalogPage + 1) * catalogPageSize >= catalogTotal || catalogLoading}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40 font-semibold"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab: Customer Wallet — recharge any customer's balance or purchase
          an eSIM on their behalf (charged to their own wallet), available
          to Admin and Super Admin alike. */}
      {activeTab === "customer-wallet" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="glass-panel rounded-2xl p-6 border border-gray-200 lg:col-span-2">
            <h3 className="text-base font-bold text-slate-900 mb-1">Find a Customer</h3>
            <p className="text-xs text-slate-500 mb-4">Search by username or email to recharge their wallet or purchase an eSIM on their behalf.</p>
            <form onSubmit={handleSearchCustomers} className="flex gap-2 mb-4">
              <input
                type="text"
                required
                minLength={2}
                placeholder="Username or email..."
                value={customerQuery}
                onChange={(e) => setCustomerQuery(e.target.value)}
                className="flex-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
              />
              <button type="submit" disabled={customerSearching} className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2 rounded-lg">
                {customerSearching ? "Searching..." : "Search"}
              </button>
            </form>
            {customerResults.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-start text-xs">
                  <thead className="text-slate-500 border-b border-gray-200">
                    <tr>
                      <th className="py-2">Username</th>
                      <th className="py-2">Email</th>
                      <th className="py-2">Role</th>
                      <th className="py-2">Wallet Balance</th>
                      <th className="py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {customerResults.map((c) => (
                      <tr key={c.id} className={selectedCustomer?.id === c.id ? "bg-brand-50" : ""}>
                        <td className="py-2.5 font-semibold text-slate-900">{c.username}</td>
                        <td className="py-2.5 text-slate-700">{c.email}</td>
                        <td className="py-2.5 text-slate-500">{c.role}</td>
                        <td className="py-2.5 font-mono text-emerald-600">${c.wallet_balance.toFixed(2)}</td>
                        <td className="py-2.5">
                          <button onClick={() => handleSelectCustomer(c)} className="bg-gray-100 hover:bg-gray-200 text-slate-700 px-2.5 py-1 rounded text-[11px] font-bold">
                            {selectedCustomer?.id === c.id ? "Selected" : "Select"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {selectedCustomer && (
            <>
              <div className="glass-panel rounded-2xl p-6 border border-gray-200">
                <h3 className="text-base font-bold text-slate-900 mb-1">Recharge Wallet</h3>
                <p className="text-xs text-slate-500 mb-4">
                  {selectedCustomer.username} — current balance <span className="font-mono text-emerald-600">${selectedCustomer.wallet_balance.toFixed(2)}</span>
                </p>
                <form onSubmit={handleRechargeWallet} className="space-y-3">
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Amount (USD)</label>
                    <input
                      type="number" min="0.01" step="0.01" required
                      value={rechargeAmount}
                      onChange={(e) => setRechargeAmount(e.target.value)}
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Note (optional)</label>
                    <input
                      type="text"
                      value={rechargeNote}
                      onChange={(e) => setRechargeNote(e.target.value)}
                      placeholder="Reason for this recharge"
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                    />
                  </div>
                  <button type="submit" disabled={rechargingWallet} className="w-full bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
                    {rechargingWallet ? "Recharging..." : "Recharge Wallet"}
                  </button>
                </form>
              </div>

              <div className="glass-panel rounded-2xl p-6 border border-gray-200">
                <h3 className="text-base font-bold text-slate-900 mb-1">Purchase eSIM for Customer</h3>
                <p className="text-xs text-slate-500 mb-4">Charged to {selectedCustomer.username}&apos;s own wallet balance.</p>
                <form onSubmit={handlePurchaseEsimForCustomer} className="space-y-3">
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Destination Country</label>
                    <select
                      value={purchaseCountry}
                      onChange={(e) => handleSelectPurchaseCountry(e.target.value)}
                      className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                      required
                    >
                      <option value="">-- Select Country --</option>
                      {purchaseCountries.map((c) => (
                        <option key={c.iso2} value={c.iso2}>{c.name_en || c.name} ({c.iso2})</option>
                      ))}
                    </select>
                  </div>
                  {purchaseCountry && (
                    <div>
                      <label className="text-xs text-slate-700 font-semibold block mb-1">Product</label>
                      <select
                        value={purchaseProductId}
                        onChange={(e) => setPurchaseProductId(e.target.value)}
                        className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
                        required
                      >
                        <option value="">-- Select Product --</option>
                        {purchaseProducts.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.title_en} — {p.is_unlimited ? "Unlimited" : `${p.data_amount_gb} GB`} ({p.validity_days} Days) — ${parseFloat(p.retail_price).toFixed(2)}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <button type="submit" disabled={purchasingEsim || !purchaseProductId} className="w-full bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
                    {purchasingEsim ? "Processing..." : "Purchase eSIM"}
                  </button>
                  {purchaseResult && (
                    <div className={`p-3 rounded-lg text-xs ${purchaseResult.ok ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
                      {purchaseResult.message}
                    </div>
                  )}
                </form>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab: Staff & Users */}
      {activeTab === "users" && (
        <div className="space-y-6">
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-1">Create Staff Account</h3>
          <p className="text-xs text-slate-500 mb-4">Directly creates an Admin or Super Admin account - existing users are promoted via the role dropdown below instead.</p>
          <form onSubmit={handleCreateStaff} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Email</label>
              <input type="email" required value={newStaff.email} onChange={(e) => setNewStaff({ ...newStaff, email: e.target.value })} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Username</label>
              <input type="text" required value={newStaff.username} onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Password</label>
              <input type="password" required minLength={8} value={newStaff.password} onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Role</label>
              <select value={newStaff.role} onChange={(e) => setNewStaff({ ...newStaff, role: e.target.value })} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
                <option value="ADMIN">Admin</option>
                <option value="SUPER_ADMIN">Super Admin</option>
              </select>
            </div>
            <button type="submit" disabled={creatingStaff} className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
              {creatingStaff ? "Creating..." : "Create Account"}
            </button>
          </form>
        </div>

        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-4">Staff & User Management</h3>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2">User ID</th>
                  <th className="py-2">Email</th>
                  <th className="py-2">Role</th>
                  <th className="py-2">Joined</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="py-2.5 font-mono text-slate-500">{u.id.substring(0,8)}...</td>
                    <td className="py-2.5 text-slate-700">{u.email}</td>
                    <td className="py-2.5 font-bold text-admin-600">{u.role}</td>
                    <td className="py-2.5 text-slate-500">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="py-2.5 space-x-2">
                      <select 
                        value={u.role} 
                        onChange={(e) => handleUpdateRole(u.id, e.target.value)}
                        className="bg-gray-50 border border-gray-300 rounded px-2 py-1 text-slate-900"
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
          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h3 className="text-base font-bold text-slate-900 mb-1 flex items-center space-x-2">
              <Activity className="w-4 h-4 text-cyan-600" />
              <span>VivaPe Upstream Supplier API Traffic Log</span>
            </h3>
            <p className="text-xs text-slate-500 mb-4">Every external supplier API request, status, and latency.</p>

            <div className="overflow-x-auto max-h-80 overflow-y-auto">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
                  <tr>
                    <th className="py-2">Time</th>
                    <th className="py-2">Method</th>
                    <th className="py-2">Endpoint</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 font-mono">
                  {supplierLogs.map((log) => (
                    <tr key={log.id} onClick={() => setInspectingLog(log)} className="cursor-pointer hover:bg-gray-50">
                      <td className="py-2.5 text-slate-500">{new Date(log.created_at).toLocaleTimeString()}</td>
                      <td className="py-2.5 font-bold text-admin-600">{log.method}</td>
                      <td className="py-2.5 text-slate-700">/{log.endpoint}</td>
                      <td className="py-2.5">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          log.status_code === 200 ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
                        }`}>{log.status_code}</span>
                      </td>
                      <td className="py-2.5 text-slate-500">{log.latency_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Audit Logs — Super Admin only, matching the backend's
              require_super_admin gate on GET /admin/audit-logs. */}
          {isSuperAdmin ? (
            <div className="glass-panel rounded-2xl p-6 border border-gray-200">
              <h3 className="text-base font-bold text-slate-900 mb-1 flex items-center space-x-2">
                <FileText className="w-4 h-4 text-amber-600" />
                <span>Administrative Audit Trail ("Log of Everything")</span>
              </h3>
              <p className="text-xs text-slate-500 mb-4">Tamper-evident logs of all administrative actions and parameter changes. Click a row to inspect the full before/after state.</p>

              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-start text-xs">
                  <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
                    <tr>
                      <th className="py-2">Time</th>
                      <th className="py-2">Role</th>
                      <th className="py-2">Action</th>
                      <th className="py-2">State Diff</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {auditLogs.map((log) => (
                      <tr key={log.id} onClick={() => setInspectingLog(log)} className="cursor-pointer hover:bg-gray-50">
                        <td className="py-2.5 text-slate-500 font-mono">{new Date(log.created_at).toLocaleTimeString()}</td>
                        <td className="py-2.5 font-bold text-amber-600">{log.actor_role}</td>
                        <td className="py-2.5 font-semibold text-slate-900">{log.action}</td>
                        <td className="py-2.5 font-mono text-[11px] text-slate-500 truncate max-w-xs">{JSON.stringify(log.after_state)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="glass-panel rounded-2xl p-6 border border-gray-200">
              <h3 className="text-base font-bold text-slate-900 mb-1 flex items-center space-x-2">
                <FileText className="w-4 h-4 text-amber-600" />
                <span>Administrative Activity Summary</span>
              </h3>
              <p className="text-xs text-slate-500 mb-4">The full audit trail (before/after state, IP, user agent) is Super-Admin-only. This is a summarized view of what's happened.</p>

              {auditSummary && (
                <>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {Object.entries(auditSummary.action_counts).map(([action, count]) => (
                      <span key={action} className="text-[10px] font-bold px-2 py-1 rounded bg-white border border-gray-300 text-slate-700">
                        {action}: <span className="text-admin-600">{count}</span>
                      </span>
                    ))}
                  </div>
                  <div className="overflow-x-auto max-h-80 overflow-y-auto">
                    <table className="w-full text-start text-xs">
                      <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
                        <tr>
                          <th className="py-2">Time</th>
                          <th className="py-2">Role</th>
                          <th className="py-2">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {auditSummary.recent.map((log) => (
                          <tr key={log.id}>
                            <td className="py-2.5 text-slate-500 font-mono">{new Date(log.created_at).toLocaleTimeString()}</td>
                            <td className="py-2.5 font-bold text-amber-600">{log.actor_role}</td>
                            <td className="py-2.5 font-semibold text-slate-900">{log.action}</td>
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

      {/* Tab: KYC Review */}
      {activeTab === "kyc" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 mb-1">National ID Verification Queue</h3>
          <p className="text-xs text-slate-500 mb-4">Review submitted NID numbers and photo documents. Approving sets the user's account as KYC Verified.</p>
          <div className="overflow-x-auto frozen-col-table">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2">User</th>
                  <th className="py-2">NID Number</th>
                  <th className="py-2">Documents</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Submitted</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {kycQueue.map((k) => (
                  <tr key={k.id}>
                    <td className="py-2.5 text-slate-700">{k.email}</td>
                    <td className="py-2.5 font-mono text-slate-700">{k.nid_number}</td>
                    <td className="py-2.5 space-x-2">
                      <button onClick={() => handleViewKycDocument(k.id, "front")} className="text-admin-600 hover:text-admin-700 underline underline-offset-2">Front</button>
                      {k.has_back_document && (
                        <button onClick={() => handleViewKycDocument(k.id, "back")} className="text-admin-600 hover:text-admin-700 underline underline-offset-2">Back</button>
                      )}
                    </td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        k.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" :
                        k.status === "REJECTED" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"
                      }`}>{k.status}</span>
                    </td>
                    <td className="py-2.5 text-slate-500">{new Date(k.submitted_at).toLocaleDateString()}</td>
                    <td className="py-2.5 space-x-2">
                      {k.status === "PENDING" && (
                        <>
                          <button onClick={() => handleApproveKyc(k.id)} className="bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 rounded text-[11px] font-bold">Approve</button>
                          <button onClick={() => handleRejectKyc(k.id)} className="bg-rose-600 hover:bg-rose-500 text-white px-2.5 py-1 rounded text-[11px] font-bold">Reject</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* KYC Document Viewer Modal */}
      {viewingDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4" onClick={() => { URL.revokeObjectURL(viewingDoc.url); setViewingDoc(null); }}>
          <div className="glass-panel rounded-2xl max-w-2xl w-full p-6 border border-gray-300 shadow-2xl max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-slate-900 capitalize">NID {viewingDoc.side} Document</h3>
              <button onClick={() => { URL.revokeObjectURL(viewingDoc.url); setViewingDoc(null); }} aria-label="Close" className="p-1 rounded-lg text-slate-500 hover:text-slate-900">
                <X className="w-5 h-5" />
              </button>
            </div>
            {viewingDoc.contentType === "application/pdf" ? (
              <iframe src={viewingDoc.url} title={`NID ${viewingDoc.side}`} className="w-full h-[70vh] rounded-xl bg-white" />
            ) : (
              <img src={viewingDoc.url} alt={`NID ${viewingDoc.side}`} className="w-full rounded-xl" />
            )}
          </div>
        </div>
      )}

      {/* JSON Inspect Modal — for both supplier and audit log rows */}
      {inspectingLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4" onClick={() => setInspectingLog(null)}>
          <div className="glass-panel rounded-2xl max-w-2xl w-full p-6 border border-gray-300 shadow-2xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-slate-900">Log Entry Detail</h3>
              <button onClick={() => setInspectingLog(null)} aria-label="Close" className="p-1 rounded-lg text-slate-500 hover:text-slate-900">
                <X className="w-5 h-5" />
              </button>
            </div>
            <pre className="text-[11px] font-mono text-slate-700 bg-gray-50 p-4 rounded-xl overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(inspectingLog, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 text-xs text-slate-500 space-y-2">
          <p className="font-semibold text-slate-900">System Status: Operational &bull; Live Domain https://triptel.co</p>
          <p>Connected to Upstream VivaPe API &amp; ShurjoPay Sandbox Gateway.</p>
          <p>Exchange rates synchronized keylessly from open.er-api.com with manual admin override support.</p>
        </div>
      )}

    </div>
    </div>
  );
}
