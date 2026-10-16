"use client";

import React, { useState, useEffect } from "react";
import { User, ShieldCheck, ShieldAlert, LogOut, Wallet as WalletIcon, Mail, Phone, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { ProfileSkeleton } from "@/components/Skeleton";

export default function ProfilePage() {
  const { t } = useAppSettings();
  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [kyc, setKyc] = useState<any>(null);
  const [nidNumber, setNidNumber] = useState("");
  const [frontFile, setFrontFile] = useState<File | null>(null);
  const [backFile, setBackFile] = useState<File | null>(null);
  const [submittingKyc, setSubmittingKyc] = useState(false);
  const [editingPhone, setEditingPhone] = useState(false);
  const [phoneDraft, setPhoneDraft] = useState("");
  const [savingPhone, setSavingPhone] = useState(false);

  const savePhone = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSavingPhone(true);
    try {
      const res: any = await api.updateMyPhone(token, phoneDraft.trim());
      setUserData((prev: any) => ({ ...prev, phone: res.phone }));
      setEditingPhone(false);
    } catch (err: any) {
      alert(err.message || "Couldn't save that number.");
    } finally {
      setSavingPhone(false);
    }
  };

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
    api.getMyKyc(token).then(setKyc).catch(() => {});
  }, []);

  const handleSubmitKyc = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token || !frontFile) return;
    setSubmittingKyc(true);
    try {
      await api.submitKyc(token, nidNumber, frontFile, backFile);
      const updated = await api.getMyKyc(token);
      setKyc(updated);
      setNidNumber("");
      setFrontFile(null);
      setBackFile(null);
    } catch (err: any) {
      alert("Failed to submit KYC: " + err.message);
    } finally {
      setSubmittingKyc(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("esim_token");
    localStorage.removeItem("esim_role");
    window.location.href = "/";
  };

  if (loading) {
    return <ProfileSkeleton />;
  }

  if (!userData) return null;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-slate-900">{t("common", "profile", "Profile")}</h1>
        <p className="text-xs text-slate-500 mt-1">Your account details and verification status.</p>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
        <div className="flex items-center space-x-4 mb-6">
          {userData.avatar_url ? (
            <img
              src={userData.avatar_url}
              alt={userData.full_name || userData.username}
              referrerPolicy="no-referrer"
              className="w-16 h-16 rounded-2xl object-cover shrink-0 border border-gray-200"
            />
          ) : (
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-brand-600 to-accent-500 flex items-center justify-center shrink-0">
              <User className="w-8 h-8 text-white" />
            </div>
          )}
          <div>
            <h2 className="text-lg font-bold text-slate-900">{userData.full_name || userData.username}</h2>
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              <span className="text-xs px-2 py-0.5 rounded-full font-bold bg-brand-50 text-brand-700 border border-brand-200">
                {userData.role}
              </span>
              {userData.has_google && (
                <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-white text-slate-700 border border-gray-200">
                  Google account linked
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex items-center space-x-3 text-slate-700">
            <Mail className="w-4 h-4 text-slate-400 shrink-0" />
            <span>{userData.email}</span>
            {userData.email_verified && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">Verified</span>
            )}
          </div>
          {/* Optional, and editable from here - a traveller's number changes,
              and the one place they would look to change it is their profile. */}
          <div className="flex items-start space-x-3 text-slate-700">
            <Phone className="w-4 h-4 text-slate-400 shrink-0 mt-2" />
            <div className="flex-1 min-w-0">
              {editingPhone ? (
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="tel"
                    value={phoneDraft}
                    onChange={(e) => setPhoneDraft(e.target.value)}
                    placeholder="Phone / WhatsApp (optional)"
                    className="flex-1 min-w-[160px] bg-white border border-gray-300 rounded-lg px-3 py-1.5 text-xs text-slate-900"
                  />
                  <button
                    type="button"
                    onClick={savePhone}
                    disabled={savingPhone}
                    className="bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-bold px-3 py-1.5 rounded-lg"
                  >
                    {savingPhone ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setEditingPhone(false); setPhoneDraft(userData.phone || ""); }}
                    className="text-xs text-slate-500 hover:text-slate-700 px-1"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <span className={userData.phone ? "" : "text-slate-400"}>
                    {userData.phone || "No phone or WhatsApp number — optional"}
                  </span>
                  <button
                    type="button"
                    onClick={() => { setPhoneDraft(userData.phone || ""); setEditingPhone(true); }}
                    className="text-xs font-semibold text-brand-600 hover:underline"
                  >
                    {userData.phone ? "Change" : "Add"}
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center space-x-3">
            {userData.is_kyc_verified ? (
              <>
                <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0" />
                <span className="text-emerald-600">KYC Verified</span>
              </>
            ) : (
              <>
                <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0" />
                <span className="text-amber-600">KYC Not Verified</span>
              </>
            )}
          </div>
        </div>
      </div>

      {!userData.is_kyc_verified && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
          <h3 className="text-sm font-bold text-slate-900 mb-1 flex items-center space-x-2">
            <ShieldAlert className="w-4 h-4 text-amber-600" />
            <span>Identity Verification</span>
          </h3>

          {kyc?.status === "PENDING" ? (
            <p className="text-xs text-amber-700 mt-2">Your documents are submitted and under review. This usually takes 1-2 business days.</p>
          ) : (
            <>
              <p className="text-xs text-slate-500 mb-4 mt-1">
                {kyc?.status === "REJECTED"
                  ? `Your previous submission was rejected${kyc.rejection_reason ? `: ${kyc.rejection_reason}` : "."} Please resubmit.`
                  : "Upload your National ID to unlock full account features."}
              </p>
              <form onSubmit={handleSubmitKyc} className="space-y-3">
                <div>
                  <label className="text-xs text-slate-700 font-semibold block mb-1">NID / National ID Number</label>
                  <input type="text" required value={nidNumber} onChange={(e) => setNidNumber(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Front Photo</label>
                    <input type="file" required accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(e) => setFrontFile(e.target.files?.[0] ?? null)} className="w-full text-[10px] text-slate-500 file:me-2 file:py-1 file:px-2 file:rounded-md file:border-0 file:text-[10px] file:font-semibold file:bg-gray-100 file:text-slate-700" />
                  </div>
                  <div>
                    <label className="text-xs text-slate-700 font-semibold block mb-1">Back Photo (optional)</label>
                    <input type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(e) => setBackFile(e.target.files?.[0] ?? null)} className="w-full text-[10px] text-slate-500 file:me-2 file:py-1 file:px-2 file:rounded-md file:border-0 file:text-[10px] file:font-semibold file:bg-gray-100 file:text-slate-700" />
                  </div>
                </div>
                <button type="submit" disabled={submittingKyc} className="flex items-center space-x-2 bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
                  <Upload className="w-3.5 h-3.5" />
                  <span>{submittingKyc ? "Submitting..." : "Submit for Review"}</span>
                </button>
              </form>
            </>
          )}
        </div>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
        <h3 className="text-sm font-bold text-slate-900 mb-4 flex items-center space-x-2">
          <WalletIcon className="w-4 h-4 text-brand-600" />
          <span>Wallets</span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(userData.wallets || []).map((w: any) => (
            <div key={w.type} className="bg-gray-50 p-3 rounded-lg border border-gray-200">
              <div className="text-[10px] uppercase font-semibold text-slate-500">{w.type}</div>
              <div className="text-lg font-bold text-slate-900 font-mono">€{w.balance.toFixed(2)}</div>
            </div>
          ))}
        </div>
        <a href="/wallet" className="mt-4 inline-block text-xs text-brand-600 hover:text-brand-700 underline">
          Manage wallets &rarr;
        </a>
      </div>

      {userData.merchant_profile && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
          <h3 className="text-sm font-bold text-slate-900 mb-2">Merchant Profile</h3>
          <p className="text-xs text-slate-500">{userData.merchant_profile.business_name}</p>
          <p className="text-xs text-slate-500 mt-1">
            Status: <span className="text-slate-700">{userData.merchant_profile.status}</span> &bull; Commission rate: {userData.merchant_profile.commission_rate_pct}%
          </p>
        </div>
      )}

      <button
        onClick={handleLogout}
        className="w-full flex items-center justify-center space-x-2 bg-gray-100 hover:bg-rose-50 text-slate-700 hover:text-rose-700 text-xs font-semibold py-3 px-3 rounded-xl border border-gray-200 transition-colors"
      >
        <LogOut className="w-3.5 h-3.5" />
        <span>{t("common", "logout", "Sign Out")}</span>
      </button>
    </div>
  );
}
