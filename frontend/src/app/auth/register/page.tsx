"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import AuthBrandMark from "@/components/AuthBrandMark";
import { api } from "@/lib/api";
import GoogleSignInButton from "@/components/GoogleSignInButton";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [referral, setReferral] = useState<{ valid: boolean; referrer_username?: string; joining_reward?: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // A shared link arrives as /auth/register?ref=CODE, so the field fills
  // itself and the invite is confirmed by name before anyone types anything.
  useEffect(() => {
    const fromLink = new URLSearchParams(window.location.search).get("ref");
    if (fromLink) setReferralCode(fromLink.toUpperCase());
  }, []);

  useEffect(() => {
    const code = referralCode.trim();
    if (code.length < 3) {
      setReferral(null);
      return;
    }
    const handle = setTimeout(() => {
      api.validateReferralCode(code).then(setReferral).catch(() => setReferral(null));
    }, 350);
    return () => clearTimeout(handle);
  }, [referralCode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.register({
        email, username, password, phone,
        referral_code: referralCode.trim() || undefined,
      });
      localStorage.setItem("esim_token", res.access_token);
      localStorage.setItem("esim_role", res.role);
      window.location.href = "/";
    } catch (err: any) {
      setError(err.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="glass-panel rounded-2xl p-8 max-w-sm w-full border border-gray-200 shadow-lg">
        <div className="text-center mb-6">
          <AuthBrandMark />
          <h2 className="text-xl font-bold text-slate-900">Create your account</h2>
          <p className="text-xs text-slate-500 mt-1">Get instant access to global eSIM connectivity</p>
        </div>

        {error && (
          <div className="mb-4 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
            {error}
          </div>
        )}

        <GoogleSignInButton mode="signup" />

        <form onSubmit={handleSubmit} className="space-y-3">
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

          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Username</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>

          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Referral code (Optional)</label>
            <input
              type="text"
              value={referralCode}
              onChange={(e) => setReferralCode(e.target.value.toUpperCase())}
              placeholder="From a friend"
              maxLength={16}
              spellCheck={false}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono uppercase text-slate-900"
            />
            {referral?.valid ? (
              <p className="mt-1 text-[11px] text-emerald-600 font-semibold">
                Invited by {referral.referrer_username}
                {Number(referral.joining_reward) > 0 ? ` — €${Number(referral.joining_reward).toFixed(2)} reward credit on sign-up` : ""}
              </p>
            ) : referralCode.trim().length >= 3 && referral && !referral.valid ? (
              <p className="mt-1 text-[11px] text-slate-500">We don&apos;t recognise that code — you can still sign up without it.</p>
            ) : null}
          </div>

          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Phone (Optional)</label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>

          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Password</label>
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
            className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition-all shadow-md shadow-brand-900/10 mt-2"
          >
            {loading ? "Creating Account..." : "Create Account"}
          </button>
        </form>

        <p className="mt-4 text-[11px] leading-relaxed text-center text-slate-500">
          By creating an account or continuing with Google, you agree to our{" "}
          <Link href="/legal/terms" className="text-brand-600 hover:underline">Terms &amp; Conditions</Link>,{" "}
          <Link href="/legal/privacy" className="text-brand-600 hover:underline">Privacy Policy</Link> and{" "}
          <Link href="/legal/refund-policy" className="text-brand-600 hover:underline">Refund Policy</Link>.
        </p>

        <div className="mt-6 text-center text-xs text-slate-500">
          Already have an account?{" "}
          <Link href="/auth/login" className="text-brand-600 font-semibold hover:underline">
            Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
