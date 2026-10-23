"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import AuthBrandMark from "@/components/AuthBrandMark";
import { api } from "@/lib/api";
import GoogleSignInButton from "@/components/GoogleSignInButton";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [nextParam, setNextParam] = useState<string | null>(null);

  useEffect(() => {
    setNextParam(new URLSearchParams(window.location.search).get("next"));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.login({ email, password });
      localStorage.setItem("esim_token", res.access_token);
      localStorage.setItem("esim_role", res.role);
      if (res.role === "SUPER_ADMIN" || res.role === "ADMIN") {
        window.location.href = "/admin";
        return;
      }
      // A "Buy Now" while signed out sends the visitor here with
      // ?next=<the package they wanted, plus ?resume=1> - honour it so
      // signing in actually continues the purchase instead of dropping
      // them on the home page.
      const next = new URLSearchParams(window.location.search).get("next");
      window.location.href = next || "/";
    } catch (err: any) {
      setError(err.message || "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="glass-panel rounded-2xl p-8 max-w-sm w-full border border-gray-200 shadow-lg">
        <div className="text-center mb-6">
          <AuthBrandMark />
          <h2 className="text-xl font-bold text-slate-900">Sign in to your account</h2>
          <p className="text-xs text-slate-500 mt-1">Access your eSIMs, wallets, and orders</p>
        </div>

        {error && (
          <div className="mb-4 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
            {error}
          </div>
        )}

        <GoogleSignInButton mode="signin" oneTap />

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Email / Username</label>
            <input
              type="text"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-slate-700 font-semibold">Password</label>
              <Link href="/auth/forgot-password" className="text-[11px] text-brand-600 hover:underline">Forgot password?</Link>
            </div>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-md shadow-brand-900/10"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

        {/* Google sign-in also creates accounts, so the consent note belongs here too. */}
        <p className="mt-4 text-[11px] leading-relaxed text-center text-slate-500">
          By continuing, you agree to our{" "}
          <Link href="/legal/terms" className="text-brand-600 hover:underline">Terms &amp; Conditions</Link> and{" "}
          <Link href="/legal/privacy" className="text-brand-600 hover:underline">Privacy Policy</Link>.
        </p>

        <div className="mt-6 text-center text-xs text-slate-500">
          Don't have an account?{" "}
          <Link
            href={nextParam ? `/auth/register?next=${encodeURIComponent(nextParam)}` : "/auth/register"}
            className="text-brand-600 font-semibold hover:underline"
          >
            Create account
          </Link>
        </div>
      </div>
    </div>
  );
}
