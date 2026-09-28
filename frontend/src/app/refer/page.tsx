"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Check, Copy, Gift, Share2, Sparkles, Ticket, UserPlus, Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { formatDate } from "@/lib/datetime";

type Summary = {
  code: string | null;
  is_enabled: boolean;
  events: Record<string, { referrer: string; referred: string; enabled: boolean }>;
  promo_balance: string;
  total_earned: string;
  referred_count: number;
  referred: { username: string; joined_at: string; role: string }[];
  rewards: { event: string; referred_username: string; amount: string; status: string; created_at: string }[];
  share_url: string | null;
  can_claim: boolean;
  referred_by: string | null;
  currency: string;
};

const EVENT_COPY: Record<string, { label: string; detail: string }> = {
  JOINING: { label: "They sign up", detail: "Credited as soon as they create their account" },
  FIRST_PURCHASE: { label: "They buy their first eSIM", detail: "Credited when that eSIM is delivered" },
  NEW_MERCHANT: { label: "They become a partner", detail: "Credited when their partner application is approved" },
};

const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</div>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }).catch(() => {});
        }}
        className="w-full flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-start hover:border-brand-500 transition-colors"
      >
        <span className="flex-1 min-w-0 truncate font-mono text-sm font-bold text-slate-900">{value}</span>
        {copied ? (
          <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 shrink-0"><Check className="w-3.5 h-3.5" /> Copied</span>
        ) : (
          <Copy className="w-4 h-4 text-slate-400 shrink-0" />
        )}
      </button>
    </div>
  );
}

export default function ReferPage() {
  const { publicSettings } = useAppSettings();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [claimCode, setClaimCode] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login?next=/refer";
      return;
    }
    setSummary(await api.getMyReferrals(token));
  }, []);

  useEffect(() => {
    load()
      .catch((err) => setNotice({ kind: "error", text: err.message || "Couldn't load your referral details" }))
      .finally(() => setLoading(false));
  }, [load]);

  const claim = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setClaiming(true);
    setNotice(null);
    try {
      const updated = await api.claimReferralCode(token, claimCode.trim());
      setSummary({ ...(summary as Summary), ...updated });
      setClaimCode("");
      setNotice({ kind: "ok", text: `Thanks — ${updated.referred_by} is now credited as your referrer.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't apply that code" });
    } finally {
      setClaiming(false);
    }
  };

  const share = async () => {
    if (!summary?.share_url) return;
    const brand = publicSettings?.platform_name || "Triptel";
    if (navigator.share) {
      try {
        await navigator.share({
          title: `${brand} — travel eSIMs`,
          text: `Get mobile data abroad with ${brand}. Use my code ${summary.code} when you sign up.`,
          url: summary.share_url,
        });
        return;
      } catch {
        // Cancelled, or sharing isn't allowed here - fall through to copy.
      }
    }
    navigator.clipboard?.writeText(summary.share_url).catch(() => {});
    setNotice({ kind: "ok", text: "Link copied — paste it anywhere." });
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-4">
        <div className="h-8 w-56 rounded bg-gray-100 animate-pulse" />
        <div className="h-44 rounded-2xl bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <p className="text-sm text-slate-600">{notice?.text || "Referrals aren't available right now."}</p>
      </div>
    );
  }

  const activeEvents = Object.entries(summary.events).filter(([, a]) => a.enabled);

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-slate-900 flex items-center gap-2">
          <Gift className="w-7 h-7 text-brand-600" /> Refer &amp; earn
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Share your code. You both get reward credit you can spend on eSIMs.
        </p>
      </div>

      {notice && (
        <div className={`mb-6 p-4 rounded-xl border text-sm font-semibold flex items-start justify-between gap-4 ${
          notice.kind === "ok" ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"
        }`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="text-xs underline opacity-75 hover:opacity-100 shrink-0">Dismiss</button>
        </div>
      )}

      {!summary.is_enabled && (
        <div className="mb-6 p-4 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
          The referral programme isn&apos;t running at the moment. Your code still works for sharing, but no reward is credited yet.
        </div>
      )}

      {/* Code + share */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {summary.code && <CopyField value={summary.code} label="Your code" />}
          {summary.share_url && <CopyField value={summary.share_url} label="Your link" />}
        </div>
        <button
          type="button"
          onClick={share}
          className="mt-4 inline-flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
        >
          <Share2 className="w-3.5 h-3.5" /> Share my link
        </button>
      </div>

      {/* Balances */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Reward credit</div>
          <div className="text-2xl font-black text-emerald-600 mt-1">{eur(summary.promo_balance)}</div>
          <div className="text-[11px] text-slate-500 mt-1">Spendable on any eSIM</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Earned from referrals</div>
          <div className="text-2xl font-black text-slate-900 mt-1">{eur(summary.total_earned)}</div>
        </div>
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">People joined</div>
          <div className="text-2xl font-black text-slate-900 mt-1">{summary.referred_count}</div>
        </div>
      </div>

      {/* What earns what */}
      {activeEvents.length > 0 && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
            <Sparkles className="w-4 h-4 text-accent-600" /> What you earn
          </h2>
          <div className="space-y-3">
            {activeEvents.map(([event, amounts]) => {
              const copy = EVENT_COPY[event] || { label: event, detail: "" };
              return (
                <div key={event} className="flex flex-wrap items-start justify-between gap-3 p-3 rounded-xl border border-gray-200 bg-white">
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-900">{copy.label}</div>
                    <div className="text-[11px] text-slate-500">{copy.detail}</div>
                  </div>
                  <div className="text-end shrink-0 text-xs">
                    {Number(amounts.referrer) > 0 && (
                      <div className="font-bold text-emerald-700">You get {eur(amounts.referrer)}</div>
                    )}
                    {Number(amounts.referred) > 0 && (
                      <div className="text-slate-600">They get {eur(amounts.referred)}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[11px] text-slate-500 mt-4">
            Reward credit pays for eSIMs and is used before your own balance. It can&apos;t be withdrawn as cash.
          </p>
        </div>
      )}

      {/* Were you referred? */}
      {summary.can_claim ? (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-1">
            <Ticket className="w-4 h-4 text-brand-600" /> Were you referred by someone?
          </h2>
          <p className="text-xs text-slate-500 mb-4">
            Enter their code to credit you both. This can only be added before your first eSIM purchase.
          </p>
          <form onSubmit={claim} className="flex flex-wrap gap-2 max-w-md">
            <input
              value={claimCode}
              onChange={(e) => setClaimCode(e.target.value.toUpperCase())}
              placeholder="Their code"
              maxLength={16}
              spellCheck={false}
              className="flex-1 min-w-[160px] bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono uppercase text-slate-900"
            />
            <button
              type="submit"
              disabled={claiming || claimCode.trim().length < 3}
              className="bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-xl"
            >
              {claiming ? "Applying…" : "Apply code"}
            </button>
          </form>
        </div>
      ) : summary.referred_by ? (
        <p className="text-xs text-slate-500 mb-6 flex items-center gap-1.5">
          <UserPlus className="w-3.5 h-3.5" /> You were referred by <strong className="text-slate-700">{summary.referred_by}</strong>.
        </p>
      ) : null}

      {/* Who joined */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
          <Users className="w-4 h-4 text-brand-600" /> People you referred
        </h2>
        {summary.referred.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">
            Nobody yet. Share your link and your first reward lands as soon as someone signs up.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Who</th>
                  <th className="py-2 pe-3 text-start">Joined</th>
                  <th className="py-2 text-end">Rewards earned</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {summary.referred.map((person) => {
                  const theirs = summary.rewards.filter((r) => r.referred_username === person.username);
                  const earned = theirs
                    .filter((r) => r.status === "GRANTED")
                    .reduce((sum, r) => sum + Number(r.amount), 0);
                  return (
                    <tr key={person.username}>
                      <td className="py-2.5 pe-3 text-slate-900 font-semibold">
                        {person.username}
                        {person.role === "MERCHANT" && (
                          <span className="ms-2 text-[10px] font-bold px-1.5 py-0.5 rounded bg-merchant-50 text-merchant-600 border border-merchant-200">Partner</span>
                        )}
                      </td>
                      <td className="py-2.5 pe-3 text-slate-500">{formatDate(person.joined_at)}</td>
                      <td className="py-2.5 text-end font-mono font-bold text-emerald-700">
                        {earned > 0 ? eur(earned) : "—"}
                        {theirs.some((r) => r.status === "REVERSED") && (
                          <div className="text-[10px] font-sans font-normal text-slate-400">a reward was reversed</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="mt-6 text-[11px] text-slate-500">
        Reward credit is shown in your <Link href="/wallet" className="font-semibold text-brand-600 underline">wallet</Link> as
        a separate balance. It can be spent on any eSIM but is not withdrawable.
      </p>
    </div>
  );
}
