"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Briefcase, CheckCircle2, Clock, Code2, Coins, FileText, LayoutDashboard, List, Send, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { MerchantTab } from "@/components/merchant/shared";
import OverviewTab from "@/components/merchant/OverviewTab";
import ProvisionTab from "@/components/merchant/ProvisionTab";
import OrdersTab from "@/components/merchant/OrdersTab";
import CommissionTab from "@/components/merchant/CommissionTab";
import ApiAccessTab from "@/components/merchant/ApiAccessTab";
import StatementTab from "@/components/merchant/StatementTab";

const MERCHANT_TABS: { id: MerchantTab; label: string; icon: any }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "provision", label: "Buy for customer", icon: Send },
  { id: "orders", label: "Orders", icon: List },
  { id: "commission", label: "Commission", icon: Coins },
  { id: "statement", label: "Statements", icon: FileText },
  { id: "api", label: "API & Webhooks", icon: Code2 },
];

function StatusCard({ icon: Icon, tone, title, children }: { icon: any; tone: "amber" | "rose"; title: string; children: React.ReactNode }) {
  const tones = {
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
  };
  return (
    <div className="max-w-2xl mx-auto px-4 py-16">
      <div className="glass-panel rounded-2xl p-8 border border-gray-200 shadow-lg text-center">
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-4 ${tones[tone]}`}>
          <Icon className="w-6 h-6" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">{title}</h2>
        <div className="text-sm text-slate-600 mt-2 space-y-2">{children}</div>
      </div>
    </div>
  );
}

export default function ResellerPortalPage() {
  const { formatPrice } = useAppSettings();
  const [userData, setUserData] = useState<any>(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [overview, setOverview] = useState<any | null>(null);
  const [activeTab, setActiveTab] = useState<MerchantTab>("overview");

  // Merchant application state
  const [businessName, setBusinessName] = useState("");
  const [tradeLicense, setTradeLicense] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [agentCode, setAgentCode] = useState("");

  // An agent's invite link arrives as /reseller?agent=AGXXXXXX, so the code is
  // filled in for the applicant rather than being something they must be told
  // to type.
  useEffect(() => {
    const fromLink = new URLSearchParams(window.location.search).get("agent");
    if (fromLink) setAgentCode(fromLink.toUpperCase());
  }, []);
  const [applying, setApplying] = useState(false);
  const [applySuccess, setApplySuccess] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    api.getMe(token).then(setUserData).catch(console.error).finally(() => setLoadingMe(false));

    const hash = window.location.hash.replace("#", "") as MerchantTab;
    if (MERCHANT_TABS.some((t) => t.id === hash)) setActiveTab(hash);
  }, []);

  const role = userData?.role;
  const profile = userData?.merchant_profile;
  const isApprovedMerchant = role === "MERCHANT" && profile?.status === "APPROVED";
  const isStaff = role === "ADMIN" || role === "SUPER_ADMIN";

  const refreshOverview = useCallback(() => {
    const token = localStorage.getItem("esim_token");
    if (!token || !isApprovedMerchant) return;
    api.getMerchantOverview(token).then(setOverview).catch(console.error);
  }, [isApprovedMerchant]);

  useEffect(() => {
    refreshOverview();
  }, [refreshOverview]);

  const selectTab = (tab: MerchantTab) => {
    setActiveTab(tab);
    window.history.replaceState(null, "", `#${tab}`);
    if (tab === "overview") refreshOverview();
  };

  const handleApplyMerchant = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    setApplying(true);
    try {
      await api.applyMerchant(token, {
        business_name: businessName,
        trade_license: tradeLicense,
        contact_phone: contactPhone,
        agent_code: agentCode.trim() || undefined,
      });
      setApplySuccess(true);
    } catch (err: any) {
      alert(err.message || "Failed to submit partner application");
    } finally {
      setApplying(false);
    }
  };

  if (loadingMe) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-4">
        <div className="h-10 w-72 rounded-xl bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (!isApprovedMerchant && !isStaff) {
    if (profile?.status === "PENDING" || applySuccess) {
      return (
        <StatusCard icon={Clock} tone="amber" title="Application under review">
          <p>Thanks for applying to the B2B Travel Partner Program{profile?.business_name ? ` as ${profile.business_name}` : ""}.</p>
          <p>Our team is reviewing it and will notify you by email. Your partner dashboard unlocks here once you&apos;re approved.</p>
        </StatusCard>
      );
    }
    if (profile?.status === "REJECTED") {
      return (
        <StatusCard icon={XCircle} tone="rose" title="Application not approved">
          {profile.rejection_reason && <p><strong>Reason:</strong> {profile.rejection_reason}</p>}
          <p>If you think this is a mistake or your details have changed, please contact support.</p>
        </StatusCard>
      );
    }
    if (profile?.status === "SUSPENDED") {
      return (
        <StatusCard icon={XCircle} tone="rose" title="Partner account suspended">
          <p>Your partner access is currently suspended. Please contact support.</p>
        </StatusCard>
      );
    }
    if (role === "MERCHANT") {
      return (
        <StatusCard icon={Clock} tone="amber" title="Partner profile not set up">
          <p>Your account has the merchant role but no approved partner profile yet. Please contact support to finish setup.</p>
        </StatusCard>
      );
    }

    return (
      <div className="max-w-2xl mx-auto px-4 py-16">
        <div className="glass-panel rounded-2xl p-8 border border-gray-200 shadow-lg">
          <div className="w-12 h-12 bg-merchant-50 text-merchant-600 rounded-xl flex items-center justify-center mx-auto mb-4">
            <Briefcase className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-slate-900 text-center">B2B Travel Partner Program</h2>
          <p className="text-xs text-slate-500 text-center mt-1 mb-6">
            Apply to become an authorized reseller. Earn commission on every eSIM you issue to your clients — from this
            dashboard or through our Partner API.
          </p>

          <form onSubmit={handleApplyMerchant} className="space-y-4">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Registered Business Name (Travel Agency / Tech)</label>
              <input type="text" required value={businessName} onChange={(e) => setBusinessName(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Trade License / Corporate ID</label>
              <input type="text" required value={tradeLicense} onChange={(e) => setTradeLicense(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Business Contact Phone</label>
              <input type="tel" required value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Agent Code (Optional)</label>
              <input
                type="text"
                value={agentCode}
                onChange={(e) => setAgentCode(e.target.value.toUpperCase())}
                placeholder="If an agent introduced you"
                maxLength={16}
                spellCheck={false}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono uppercase text-slate-900"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                Credits the agent who brought you in. It doesn&apos;t change your own commission.
              </p>
            </div>
            <button type="submit" disabled={applying} className="w-full py-2.5 rounded-xl bg-merchant-600 hover:bg-merchant-500 text-white text-xs font-bold transition-all shadow-md shadow-merchant-900/10">
              {applying ? "Submitting..." : "Submit B2B Application"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // Admins can issue eSIMs for customers from here, but the sales,
  // commission and API views belong to a merchant account.
  const tabs = isApprovedMerchant ? MERCHANT_TABS : MERCHANT_TABS.filter((t) => t.id === "provision");
  const currentTab = tabs.some((t) => t.id === activeTab) ? activeTab : tabs[0].id;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="inline-flex items-center space-x-1.5 text-merchant-600 text-xs font-bold uppercase tracking-wider mb-1">
            <Briefcase className="w-4 h-4" />
            <span>Partner Dashboard</span>
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900">
            {isApprovedMerchant ? overview?.business?.name || profile?.business_name || "Your business" : "Reseller Provisioning"}
          </h1>
          {isApprovedMerchant && (
            <p className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Approved reseller
            </p>
          )}
        </div>

        {isApprovedMerchant && overview && (
          <div className="flex gap-3">
            <div className="glass-panel px-4 py-2 rounded-xl border border-gray-200 text-end">
              <span className="text-[10px] text-slate-500 uppercase font-semibold block">Wallet</span>
              <span className="text-base font-black text-emerald-600 font-mono">{formatPrice(Number(overview.wallets.wallet_balance))}</span>
            </div>
            <div className="glass-panel px-4 py-2 rounded-xl border border-gray-200 text-end">
              <span className="text-[10px] text-slate-500 uppercase font-semibold block">Commission</span>
              <span className="text-base font-black text-merchant-600 font-mono">{formatPrice(Number(overview.wallets.commission_balance))}</span>
            </div>
          </div>
        )}
      </div>

      {isStaff && !isApprovedMerchant && (
        <div className="p-3 rounded-xl bg-gray-50 border border-gray-200 text-xs text-slate-600">
          Staff view: you can buy eSIMs for customers here. Sales, commission and API views are shown to approved merchant accounts.
        </div>
      )}

      {tabs.length > 1 && (
        <div className="flex space-x-2 border-b border-gray-200 pb-4 overflow-x-auto hide-scrollbar">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => selectTab(tab.id)}
                className={`px-4 py-2.5 text-xs font-bold rounded-xl whitespace-nowrap transition-all flex items-center space-x-2 ${currentTab === tab.id ? "bg-merchant-50 text-merchant-700 border border-merchant-200" : "text-slate-500 hover:text-slate-900 bg-gray-50 border border-gray-200"}`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      )}

      {currentTab === "overview" && <OverviewTab overview={overview} formatPrice={formatPrice} onNavigate={selectTab} />}
      {currentTab === "provision" && (
        <ProvisionTab
          commissionRatePct={overview?.commission?.effective_rate_pct ?? profile?.commission_rate_pct}
          showCommission={isApprovedMerchant}
          formatPrice={formatPrice}
          onOrderSettled={refreshOverview}
        />
      )}
      {currentTab === "orders" && <OrdersTab formatPrice={formatPrice} />}
      {currentTab === "commission" && <CommissionTab overview={overview} formatPrice={formatPrice} onChanged={refreshOverview} />}
      {currentTab === "statement" && <StatementTab />}
      {currentTab === "api" && <ApiAccessTab />}
    </div>
  );
}
