"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Gift, Save, Trophy, Users } from "lucide-react";
import { api } from "@/lib/api";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";
const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

const EVENT_ORDER = ["JOINING", "FIRST_PURCHASE", "NEW_MERCHANT"];
const EVENT_WHEN: Record<string, string> = {
  JOINING: "Credited the moment they create their account",
  FIRST_PURCHASE: "Credited when their first eSIM is delivered — reversed if that order is refunded",
  NEW_MERCHANT: "Credited when their partner application is approved",
};

type EventAmounts = { referrer: string; referred: string; enabled: boolean };

export default function ReferralsTab({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [settings, setSettings] = useState<any | null>(null);
  const [form, setForm] = useState<{ is_enabled: boolean; events: Record<string, EventAmounts>; max_rewarded_referrals: string } | null>(null);
  const [report, setReport] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    const [cfg, rep] = await Promise.all([
      api.getAdminReferralSettings(token),
      api.getAdminReferralReport(token),
    ]);
    setSettings(cfg);
    setForm({
      is_enabled: cfg.is_enabled,
      events: Object.fromEntries(
        EVENT_ORDER.map((e) => [e, {
          referrer: String(Number(cfg.events?.[e]?.referrer ?? 0)),
          referred: String(Number(cfg.events?.[e]?.referred ?? 0)),
          enabled: Boolean(cfg.events?.[e]?.enabled),
        }])
      ),
      max_rewarded_referrals: cfg.max_rewarded_referrals ? String(cfg.max_rewarded_referrals) : "",
    });
    setReport(rep);
  }, []);

  useEffect(() => {
    load().catch((err) => setNotice({ kind: "error", text: err.message || "Couldn't load the referral programme" }));
  }, [load]);

  const save = async () => {
    const token = getToken();
    if (!token || !form) return;
    setSaving(true);
    setNotice(null);
    try {
      await api.updateAdminReferralSettings(token, {
        is_enabled: form.is_enabled,
        events: form.events,
        max_rewarded_referrals: form.max_rewarded_referrals.trim() ? Number(form.max_rewarded_referrals) : null,
      });
      await load();
      setNotice({ kind: "ok", text: "Saved. New rewards use these amounts; credit already given stays as it is." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save" });
    } finally {
      setSaving(false);
    }
  };

  const setEvent = (event: string, patch: Partial<EventAmounts>) => {
    if (!form) return;
    setForm({ ...form, events: { ...form.events, [event]: { ...form.events[event], ...patch } } });
  };

  if (!form || !settings) {
    return <div className="glass-panel rounded-2xl border border-gray-200 h-64 animate-pulse" />;
  }

  const labels: Record<string, string> = settings.event_labels || {};
  const totals = report?.totals;

  return (
    <div className="space-y-6">
      {/* Settings */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Gift className="w-4 h-4 text-admin-600" /> Referral rewards
        </h3>
        <p className="text-xs text-slate-500 mt-1 max-w-2xl">
          Flat amounts in {settings.base_currency}, paid as <strong>reward credit</strong>: customers can spend it on eSIMs but
          can never withdraw it as cash. Set an amount to zero to pay only one side of an event.
          {!isSuperAdmin && " Only a Super Admin can change these."}
        </p>

        <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 mt-4">
          <input type="checkbox" checked={form.is_enabled} disabled={!isSuperAdmin}
            onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />
          Referral programme running
        </label>
        {!form.is_enabled && (
          <p className="text-[11px] text-amber-700 mt-1">
            While this is off, referral links are still recorded but no credit is given.
          </p>
        )}

        <div className="mt-4 space-y-3">
          {EVENT_ORDER.map((event) => (
            <div key={event} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-bold text-slate-900">{labels[event] || event}</div>
                  <div className="text-[11px] text-slate-500">{EVENT_WHEN[event]}</div>
                </div>
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 shrink-0">
                  <input type="checkbox" checked={form.events[event].enabled} disabled={!isSuperAdmin}
                    onChange={(e) => setEvent(event, { enabled: e.target.checked })} />
                  On
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3 mt-3 max-w-sm">
                <div>
                  <label className="text-[11px] text-slate-700 font-semibold block mb-1">Referrer gets</label>
                  <input className={`${inputCls} font-mono`} inputMode="decimal" disabled={!isSuperAdmin}
                    value={form.events[event].referrer} onChange={(e) => setEvent(event, { referrer: e.target.value })} />
                </div>
                <div>
                  <label className="text-[11px] text-slate-700 font-semibold block mb-1">New customer gets</label>
                  <input className={`${inputCls} font-mono`} inputMode="decimal" disabled={!isSuperAdmin}
                    value={form.events[event].referred} onChange={(e) => setEvent(event, { referred: e.target.value })} />
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 max-w-xs">
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">
            Maximum people one referrer is paid for
          </label>
          <input className={`${inputCls} font-mono`} inputMode="numeric" disabled={!isSuperAdmin}
            value={form.max_rewarded_referrals} placeholder="Unlimited"
            onChange={(e) => setForm({ ...form, max_rewarded_referrals: e.target.value })} />
          <p className="text-[11px] text-slate-500 mt-1">
            Caps what one person can earn. Anyone they invite still gets their own welcome credit.
          </p>
        </div>

        {isSuperAdmin && (
          <button type="button" onClick={save} disabled={saving}
            className="mt-4 flex items-center gap-1.5 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
            <Save className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save rewards"}
          </button>
        )}
        {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}
      </div>

      {/* Totals */}
      {totals && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          {[
            { label: "Referred sign-ups", value: String(totals.referred_users), tone: "text-slate-900" },
            { label: "Rewards granted", value: String(totals.rewards), tone: "text-slate-900" },
            { label: "Credit to referrers", value: eur(totals.paid_to_referrers), tone: "text-emerald-600" },
            { label: "Credit to new customers", value: eur(totals.paid_to_referred), tone: "text-emerald-600" },
            { label: "Unspent credit", value: eur(totals.promo_credit_outstanding), tone: "text-amber-600" },
          ].map((t) => (
            <div key={t.label} className="glass-panel rounded-2xl p-4 border border-gray-200">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{t.label}</div>
              <div className={`text-xl font-black font-mono mt-1 ${t.tone}`}>{t.value}</div>
            </div>
          ))}
        </div>
      )}
      {totals && (
        <p className="text-[11px] text-slate-500 -mt-3">
          Unspent credit is a liability in eSIMs, not in cash — it can never be withdrawn.
          {totals.reversed > 0 ? ` ${totals.reversed} reward(s) have been reversed after a refund.` : ""}
        </p>
      )}

      {/* Leaders */}
      {report?.leaders?.length > 0 && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
            <Trophy className="w-4 h-4 text-amber-500" /> Top referrers
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Who</th>
                  <th className="py-2 pe-3 text-end">People brought in</th>
                  <th className="py-2 text-end">Credit earned</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.leaders.map((l: any) => (
                  <tr key={l.username}>
                    <td className="py-2.5 pe-3 text-slate-900 font-semibold">{l.username}</td>
                    <td className="py-2.5 pe-3 text-end font-mono">{l.referrals}</td>
                    <td className="py-2.5 text-end font-mono font-bold text-emerald-700">{eur(l.earned)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Every reward */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
          <Users className="w-4 h-4 text-brand-600" /> Rewards
        </h3>
        {!report?.rewards?.length ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No referral rewards yet. Switch the programme on above and set the amounts.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Event</th>
                  <th className="py-2 pe-3 text-start">Referrer</th>
                  <th className="py-2 pe-3 text-start">New customer</th>
                  <th className="py-2 pe-3 text-end">Referrer credit</th>
                  <th className="py-2 pe-3 text-end">Their credit</th>
                  <th className="py-2 text-end">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.rewards.map((r: any) => (
                  <tr key={r.id} className={r.status === "REVERSED" ? "opacity-60" : ""}>
                    <td className="py-2.5 pe-3">
                      <div className="text-slate-700">{labels[r.event] || r.event}</div>
                      {r.status === "REVERSED" && (
                        <div className="text-[10px] text-rose-600">reversed{r.reversal_reason ? ` · ${r.reversal_reason}` : ""}</div>
                      )}
                    </td>
                    <td className="py-2.5 pe-3 text-slate-900 font-semibold">{r.referrer}</td>
                    <td className="py-2.5 pe-3 text-slate-700">{r.referred}</td>
                    <td className="py-2.5 pe-3 text-end font-mono text-emerald-700">{Number(r.referrer_amount) > 0 ? eur(r.referrer_amount) : "—"}</td>
                    <td className="py-2.5 pe-3 text-end font-mono text-emerald-700">{Number(r.referred_amount) > 0 ? eur(r.referred_amount) : "—"}</td>
                    <td className="py-2.5 text-end text-slate-500 whitespace-nowrap">{new Date(r.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
