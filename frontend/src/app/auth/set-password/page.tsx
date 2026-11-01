"use client";

import React, { useEffect, useState } from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import AuthBrandMark from "@/components/AuthBrandMark";
import { api } from "@/lib/api";

// Where a customer lands when a shop opened an account for them and the
// password is still their phone number. Deliberately not skippable: the
// server refuses to let that credential buy anything or move money, so
// letting them wander off into the app would only produce a confusing 403
// at the moment they try to spend.
export default function SetPasswordPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [nextParam, setNextParam] = useState<string | null>(null);

  useEffect(() => {
    setNextParam(new URLSearchParams(window.location.search).get("next"));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (newPassword !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    if (newPassword.length < 8) {
      setError("Please use at least 8 characters.");
      return;
    }
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    setLoading(true);
    try {
      await api.changePassword(token, currentPassword, newPassword);
      try {
        localStorage.removeItem("esim_must_change_password");
      } catch {
        // Non-fatal: the server is the one that enforces this.
      }
      window.location.href = nextParam || "/my-esims";
    } catch (err: any) {
      setError(err.message || "Couldn't update your password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="glass-panel rounded-2xl p-8 max-w-sm w-full border border-gray-200 shadow-lg">
        <div className="text-center mb-6">
          <AuthBrandMark />
          <h2 className="text-xl font-bold text-slate-900 flex items-center justify-center gap-2">
            <KeyRound className="w-4 h-4 text-brand-600" /> Choose your password
          </h2>
          <p className="text-xs text-slate-500 mt-2 leading-relaxed">
            Your account was set up for you, and your phone number is being used as the password.
            Please choose your own before you buy anything or use your wallet.
          </p>
        </div>

        {error && (
          <div className="mb-4 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
            {error}
          </div>
        )}

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">
              Current password <span className="font-normal text-slate-400">(your phone number)</span>
            </label>
            <input
              type="password" required value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">New password</label>
            <input
              type="password" required minLength={8} value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Confirm new password</label>
            <input
              type="password" required minLength={8} value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>
          <button
            type="submit" disabled={loading}
            className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold"
          >
            {loading ? "Saving…" : "Save password"}
          </button>
        </form>

        <p className="mt-5 text-[11px] text-slate-500 flex items-start gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-px" />
          You can still view the eSIM bought for you before doing this — the lock is only on buying and wallet transfers.
        </p>
      </div>
    </div>
  );
}
