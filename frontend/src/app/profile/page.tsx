"use client";

import React, { useState, useEffect } from "react";
import { User, ShieldCheck, ShieldAlert, LogOut, Wallet as WalletIcon, Mail, Phone } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function ProfilePage() {
  const { t } = useAppSettings();
  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    api.getMe(token)
      .then(setUserData)
      .catch(() => {
        localStorage.removeItem("esim_token");
        window.location.href = "/auth/login";
      })
      .finally(() => setLoading(false));
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("esim_token");
    localStorage.removeItem("esim_role");
    window.location.href = "/";
  };

  if (loading) {
    return <div className="py-20 text-center text-sm text-slate-400">Loading profile...</div>;
  }

  if (!userData) return null;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-white">{t("common", "profile", "Profile")}</h1>
        <p className="text-xs text-slate-400 mt-1">Your account details and verification status.</p>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-white/10 mb-6">
        <div className="flex items-center space-x-4 mb-6">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-brand-600 to-accent-500 flex items-center justify-center shrink-0">
            <User className="w-8 h-8 text-white" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">{userData.full_name || userData.username}</h2>
            <span className="text-xs px-2 py-0.5 rounded-full font-bold bg-brand-500/10 text-brand-400 border border-brand-500/20">
              {userData.role}
            </span>
          </div>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex items-center space-x-3 text-slate-300">
            <Mail className="w-4 h-4 text-slate-500 shrink-0" />
            <span>{userData.email}</span>
          </div>
          {userData.phone && (
            <div className="flex items-center space-x-3 text-slate-300">
              <Phone className="w-4 h-4 text-slate-500 shrink-0" />
              <span>{userData.phone}</span>
            </div>
          )}
          <div className="flex items-center space-x-3">
            {userData.is_kyc_verified ? (
              <>
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                <span className="text-emerald-400">KYC Verified</span>
              </>
            ) : (
              <>
                <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
                <span className="text-amber-400">KYC Not Verified</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-white/10 mb-6">
        <h3 className="text-sm font-bold text-white mb-4 flex items-center space-x-2">
          <WalletIcon className="w-4 h-4 text-brand-400" />
          <span>Wallets</span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(userData.wallets || []).map((w: any) => (
            <div key={w.type} className="bg-slate-900/60 p-3 rounded-lg border border-white/5">
              <div className="text-[10px] uppercase font-semibold text-slate-400">{w.type}</div>
              <div className="text-lg font-bold text-white font-mono">${w.balance.toFixed(2)}</div>
            </div>
          ))}
        </div>
        <a href="/wallet" className="mt-4 inline-block text-xs text-brand-400 hover:text-brand-300 underline">
          Manage wallets &rarr;
        </a>
      </div>

      {userData.merchant_profile && (
        <div className="glass-panel rounded-2xl p-6 border border-white/10 mb-6">
          <h3 className="text-sm font-bold text-white mb-2">Merchant Profile</h3>
          <p className="text-xs text-slate-400">{userData.merchant_profile.business_name}</p>
          <p className="text-xs text-slate-500 mt-1">
            Status: <span className="text-slate-300">{userData.merchant_profile.status}</span> &bull; Commission rate: {userData.merchant_profile.commission_rate_pct}%
          </p>
        </div>
      )}

      <button
        onClick={handleLogout}
        className="w-full flex items-center justify-center space-x-2 bg-slate-800 hover:bg-rose-900/40 text-slate-200 hover:text-rose-300 text-xs font-semibold py-3 px-3 rounded-xl border border-white/10 transition-colors"
      >
        <LogOut className="w-3.5 h-3.5" />
        <span>{t("common", "logout", "Sign Out")}</span>
      </button>
    </div>
  );
}
