"use client";

import React, { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Wifi, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err: any) {
      setError(err.message || "This reset link may have expired. Please request a new one.");
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center">
        This link is missing a reset token. Please request a new one from the{" "}
        <Link href="/auth/forgot-password" className="underline font-semibold">forgot password</Link> page.
      </div>
    );
  }

  if (done) {
    return (
      <div className="space-y-4">
        <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs text-center">
          Your password has been reset.
        </div>
        <Link href="/auth/login" className="block w-full text-center py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all">
          Sign In
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
          {error}
        </div>
      )}
      <div>
        <label className="text-xs text-slate-700 font-semibold block mb-1">New Password</label>
        <input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
        />
      </div>
      <div>
        <label className="text-xs text-slate-700 font-semibold block mb-1">Confirm New Password</label>
        <input
          type="password"
          required
          minLength={8}
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
        />
      </div>
      <button
        type="submit"
        disabled={loading}
        className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-md shadow-brand-900/10"
      >
        {loading ? "Resetting..." : "Reset Password"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="glass-panel rounded-2xl p-8 max-w-sm w-full border border-gray-200 shadow-lg">
        <div className="text-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-brand-600 flex items-center justify-center mx-auto mb-3">
            <Wifi className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Set a new password</h2>
        </div>

        <Suspense fallback={<div className="text-center text-xs text-slate-500">Loading...</div>}>
          <ResetPasswordForm />
        </Suspense>

        <div className="mt-6 text-center text-xs text-slate-500">
          <Link href="/auth/login" className="inline-flex items-center text-brand-600 font-semibold hover:underline">
            <ArrowLeft className="w-3 h-3 me-1" /> Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
