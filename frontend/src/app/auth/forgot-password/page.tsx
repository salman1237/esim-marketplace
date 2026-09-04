"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Wifi, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (err: any) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="glass-panel rounded-2xl p-8 max-w-sm w-full border border-gray-200 shadow-lg">
        <div className="text-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-brand-600 flex items-center justify-center mx-auto mb-3">
            <Wifi className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Reset your password</h2>
          <p className="text-xs text-slate-500 mt-1">We'll email you a link to reset it</p>
        </div>

        {sent ? (
          <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs text-center">
            If that email is registered, a reset link is on its way. Check your inbox.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
                {error}
              </div>
            )}
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-md shadow-brand-900/10"
            >
              {loading ? "Sending..." : "Send Reset Link"}
            </button>
          </form>
        )}

        <div className="mt-6 text-center text-xs text-slate-500">
          <Link href="/auth/login" className="inline-flex items-center text-brand-600 font-semibold hover:underline">
            <ArrowLeft className="w-3 h-3 me-1" /> Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
