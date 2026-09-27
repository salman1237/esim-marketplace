"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRightLeft, Banknote, Briefcase, Check, Clock, Copy, FileText, Handshake,
  LayoutDashboard, Plus, ShoppingBag, XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import StatementView, { currentMonth } from "@/components/finance/StatementView";

const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

type TabId = "overview" | "merchants" | "sales" | "commission" | "statement";
const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "merchants", label: "My partners", icon: Handshake },
  { id: "sales", label: "Sales", icon: ShoppingBag },
  { id: "commission", label: "Commission", icon: Banknote },
  { id: "statement", label: "Statement", icon: FileText },
];

function StatusCard({ icon: Icon, tone, title, children }: { icon: any; tone: string; title: string; children: React.ReactNode }) {
  return (
    <div className="max-w-2xl mx-auto px-4 py-16">
      <div className="glass-panel rounded-2xl p-8 border border-gray-200 text-center">
        <div className={`w-12 h-12 bg-${tone}-50 text-${tone}-600 rounded-xl flex items-center justify-center mx-auto mb-4`}>
          <Icon className="w-6 h-6" />
        </div>
        <h2 className="text-xl font-bold text-slate-900">{title}</h2>
        <div className="text-xs text-slate-500 mt-2 space-y-2">{children}</div>
      </div>
    </div>
  );
}

function CodeChip({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(code).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }).catch(() => {});
      }}
      className="inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-3 py-2 hover:border-brand-500 transition-colors"
      title="Copy agent code"
    >
      <span className="font-mono text-sm font-black text-slate-900">{code}</span>
      {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5 text-slate-400" />}
    </button>
  );
}

export default function AgentPortalPage() {
  const [status, setStatus] = useState<any | null>(null);
  const [overview, setOverview] = useState<any | null>(null);
  const [merchants, setMerchants] = useState<any[]>([]);
  const [orders, setOrders] = useState<any | null>(null);
  const [ledger, setLedger] = useState<any | null>(null);
  const [statement, setStatement] = useState<any | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [tab, setTab] = useState<TabId>("overview");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Application form, shown when this account isn't an agent yet.
  const [companyName, setCompanyName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [newMerchant, setNewMerchant] = useState("");

  // Bonus request, per partner.
  const [bonusFor, setBonusFor] = useState<any | null>(null);
  const [bonusPct, setBonusPct] = useState("0");
  const [bonusReason, setBonusReason] = useState("");
  const [bonusRequests, setBonusRequests] = useState<any[]>([]);
  const [copiedInvite, setCopiedInvite] = useState(false);

  const loadPortal = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const [ov, ms, br] = await Promise.all([
      api.getAgentOverview(token),
      api.getAgentMerchants(token),
      api.getAgentBonusRequests(token).catch(() => []),
    ]);
    setOverview(ov);
    setMerchants(ms);
    setBonusRequests(br);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login?next=/agent";
      return;
    }
    api.getAgentStatus(token)
      .then(async (s) => {
        setStatus(s);
        if (s.is_agent) await loadPortal();
      })
      .catch((err) => setNotice({ kind: "error", text: err.message || "Couldn't load your agent account" }))
      .finally(() => setLoading(false));
  }, [loadPortal]);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token || !status?.is_agent) return;
    if (tab === "sales" && !orders) api.getAgentOrders(token).then(setOrders).catch(() => {});
    if (tab === "commission") api.getAgentCommissionLedger(token).then(setLedger).catch(() => {});
  }, [tab, status, orders]);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token || !status?.is_agent || tab !== "statement" || !month) return;
    api.getAgentStatement(token, month).then(setStatement).catch(() => setStatement(null));
  }, [tab, month, status]);

  const apply = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.applyAsAgent(token, { company_name: companyName, contact_phone: contactPhone });
      setStatus(await api.getAgentStatus(token));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't submit the application" });
    } finally {
      setBusy(false);
    }
  };

  const addMerchant = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.addAgentMerchant(token, newMerchant.trim());
      setNewMerchant("");
      await loadPortal();
      setNotice({ kind: "ok", text: res.message });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't add that partner" });
    } finally {
      setBusy(false);
    }
  };

  const submitBonus = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token || !bonusFor) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.requestAgentBonus(token, {
        merchant_profile_id: bonusFor.merchant_id,
        requested_pct: bonusPct.trim(),
        reason: bonusReason.trim() || undefined,
      });
      setBonusFor(null);
      setBonusReason("");
      await loadPortal();
      setNotice({ kind: "ok", text: res.message });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't send that request" });
    } finally {
      setBusy(false);
    }
  };

  const copyInvite = () => {
    const url = overview?.agent?.invite_url;
    if (!url) return;
    if (navigator.share) {
      navigator.share({ title: "Become a Triptel partner", url }).catch(() => {});
      return;
    }
    navigator.clipboard?.writeText(url).catch(() => {});
    setCopiedInvite(true);
    setTimeout(() => setCopiedInvite(false), 1800);
  };

  const moveCommission = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.transferAgentCommission(token);
      await Promise.all([loadPortal(), api.getAgentCommissionLedger(token).then(setLedger)]);
      setNotice({ kind: "ok", text: `Moved ${eur(res.transferred)} to your main wallet. You can withdraw it from there.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't move the commission" });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-4">
        <div className="h-10 w-72 rounded-xl bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  // --- Not an agent yet ---
  if (!status?.is_agent) {
    if (status?.status === "PENDING") {
      return (
        <StatusCard icon={Clock} tone="amber" title="Agent application under review">
          <p>We&apos;re reviewing your application. You&apos;ll get your agent code once it&apos;s approved.</p>
        </StatusCard>
      );
    }
    if (status?.status === "REJECTED" || status?.status === "SUSPENDED") {
      return (
        <StatusCard icon={XCircle} tone="rose" title={status.status === "SUSPENDED" ? "Agent account suspended" : "Application not approved"}>
          {status.rejection_reason && <p><strong>Reason:</strong> {status.rejection_reason}</p>}
          <p>Please contact support if you think this is a mistake.</p>
        </StatusCard>
      );
    }
    if (!status?.can_apply) {
      return (
        <StatusCard icon={XCircle} tone="rose" title="Not available on this account">
          <p>Staff accounts can&apos;t be agents.</p>
        </StatusCard>
      );
    }

    return (
      <div className="max-w-2xl mx-auto px-4 py-16">
        <div className="glass-panel rounded-2xl p-8 border border-gray-200 shadow-lg">
          <div className="w-12 h-12 bg-brand-50 text-brand-600 rounded-xl flex items-center justify-center mx-auto mb-4">
            <Handshake className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-slate-900 text-center">Become an agent</h2>
          <p className="text-xs text-slate-500 text-center mt-1 mb-6">
            Recruit travel agencies as partners and earn {Number(status?.commission_rate_pct || 2)}% of everything they sell —
            on top of the commission they earn themselves.
          </p>

          {notice && (
            <div className="mb-4 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs text-center font-medium">
              {notice.text}
            </div>
          )}

          <form onSubmit={apply} className="space-y-4">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Your company or trading name</label>
              <input type="text" required minLength={2} value={companyName} onChange={(e) => setCompanyName(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Contact phone</label>
              <input type="tel" required value={contactPhone} onChange={(e) => setContactPhone(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900" />
            </div>
            <button type="submit" disabled={busy}
              className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold shadow-md shadow-brand-900/10">
              {busy ? "Submitting…" : "Submit agent application"}
            </button>
          </form>
          <p className="text-[11px] text-slate-500 mt-4 text-center">
            Already a partner yourself? You can be both — being an agent doesn&apos;t change your partner account.
          </p>
        </div>
      </div>
    );
  }

  // --- The portal ---
  const agent = overview?.agent;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900">{agent?.company_name || "Agent portal"}</h1>
          <p className="text-xs text-slate-500 mt-1">
            You earn {Number(agent?.commission_rate_pct || 0)}% of the price of everything your partners sell.
          </p>
        </div>
        <div className="text-end">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Your agent code</div>
          {agent?.agent_code && <CodeChip code={agent.agent_code} />}
        </div>
      </div>

      {notice && (
        <div className={`p-4 rounded-xl border text-sm font-semibold flex items-start justify-between gap-4 ${
          notice.kind === "ok" ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"
        }`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="text-xs underline opacity-75 hover:opacity-100 shrink-0">Dismiss</button>
        </div>
      )}

      <nav className="flex gap-1 overflow-x-auto hide-scrollbar glass-panel rounded-2xl border border-gray-200 p-2">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl py-2.5 px-3 text-xs font-bold transition-colors ${
                tab === t.id ? "bg-brand-50 text-brand-700 border border-brand-200" : "text-slate-600 hover:bg-gray-50 border border-transparent"
              }`}
            >
              <Icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          );
        })}
      </nav>

      {tab === "overview" && overview && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Partners", value: String(overview.merchants), tone: "text-slate-900" },
              { label: "Delivered sales", value: String(overview.sales.orders), tone: "text-slate-900" },
              { label: "Sales volume", value: eur(overview.sales.volume), tone: "text-slate-900" },
              { label: "Commission earned", value: eur(overview.sales.commission), tone: "text-emerald-600" },
            ].map((s) => (
              <div key={s.label} className="glass-panel rounded-2xl p-5 border border-gray-200">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{s.label}</div>
                <div className={`text-2xl font-black mt-1 ${s.tone}`}>{s.value}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="glass-panel rounded-2xl p-6 border border-gray-200">
              <div className="text-xs font-semibold text-slate-500 flex items-center justify-between">
                This month <Clock className="w-4 h-4 text-brand-600" />
              </div>
              <div className="text-2xl font-black text-slate-900 mt-2">{eur(overview.this_month.commission)}</div>
              <div className="text-[11px] text-slate-500 mt-1">{overview.this_month.orders} delivered sale(s)</div>
            </div>
            <div className="glass-panel rounded-2xl p-6 border border-gray-200">
              <div className="text-xs font-semibold text-slate-500 flex items-center justify-between">
                Commission balance <Banknote className="w-4 h-4 text-emerald-600" />
              </div>
              <div className="text-2xl font-black text-emerald-600 mt-2">{eur(overview.wallets.commission_balance)}</div>
              <div className="text-[11px] text-slate-500 mt-1">Main wallet: {eur(overview.wallets.wallet_balance)}</div>
              <button onClick={() => setTab("commission")} className="text-[11px] font-bold text-brand-600 hover:text-brand-700 mt-2">
                Move it to your wallet →
              </button>
            </div>
          </div>

          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h2 className="text-base font-bold text-slate-900 mb-1">Invite a travel agency</h2>
            <p className="text-xs text-slate-500 mb-4">
              Send this link. It opens the B2B application with your code already filled in, so every eSIM they sell earns
              you commission from day one. You can also add a partner who signed up without it from{" "}
              <button onClick={() => setTab("merchants")} className="font-semibold text-brand-600 underline">My partners</button>.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                readOnly
                value={agent?.invite_url || ""}
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-[220px] bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono text-slate-900"
              />
              <button
                onClick={copyInvite}
                className="inline-flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2 rounded-xl"
              >
                {copiedInvite ? <><Check className="w-3.5 h-3.5" /> Copied</> : <><Copy className="w-3.5 h-3.5" /> Copy invite link</>}
              </button>
            </div>
          </div>
        </>
      )}

      {tab === "merchants" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h2 className="text-base font-bold text-slate-900 mb-1">My partners</h2>
          <p className="text-xs text-slate-500 mb-5">
            Partners mapped to you. Adding one here only works if they don&apos;t already have an agent.
          </p>

          <form onSubmit={addMerchant} className="flex flex-wrap gap-2 mb-5 max-w-lg">
            <input
              value={newMerchant}
              onChange={(e) => setNewMerchant(e.target.value)}
              placeholder="Partner's email or username"
              className="flex-1 min-w-[200px] bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
            <button type="submit" disabled={busy || newMerchant.trim().length < 3}
              className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-xl">
              <Plus className="w-3.5 h-3.5" /> Add partner
            </button>
          </form>

          {merchants.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-500">
              No partners yet. Share your code, or add one above.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pe-3 text-start">Partner</th>
                    <th className="py-2 pe-3 text-start">Status</th>
                    <th className="py-2 pe-3 text-end">Delivered sales</th>
                    <th className="py-2 pe-3 text-end">Volume</th>
                    <th className="py-2 pe-3 text-end">My commission</th>
                    <th className="py-2 text-end">Bonus</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {merchants.map((m) => (
                    <tr key={m.merchant_id}>
                      <td className="py-2.5 pe-3">
                        <div className="font-semibold text-slate-900">{m.business_name}</div>
                        <div className="text-[10px] text-slate-400">{m.email}</div>
                      </td>
                      <td className="py-2.5 pe-3">
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                          m.status === "APPROVED" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200"
                        }`}>{m.status}</span>
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono">{m.orders}</td>
                      <td className="py-2.5 pe-3 text-end font-mono text-slate-600">{eur(m.volume)}</td>
                      <td className="py-2.5 pe-3 text-end font-mono font-bold text-emerald-700">
                        {eur(m.my_commission)}
                        {Number(m.bonus_earned) > 0 && (
                          <div className="text-[10px] font-sans font-normal text-slate-400">
                            incl. {eur(m.bonus_earned)} bonus
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 text-end">
                        <div className="font-mono font-bold text-slate-900">{Number(m.bonus_pct).toFixed(2)}%</div>
                        {m.pending_bonus_pct ? (
                          <div className="text-[10px] text-amber-600">
                            {Number(m.pending_bonus_pct).toFixed(2)}% awaiting approval
                          </div>
                        ) : (
                          <button
                            onClick={() => { setBonusFor(m); setBonusPct(String(Number(m.bonus_pct))); setBonusReason(""); }}
                            className="text-[10px] font-semibold text-brand-600 hover:text-brand-700"
                          >
                            Change
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {bonusRequests.length > 0 && (
            <div className="mt-6 pt-5 border-t border-gray-200">
              <h3 className="text-sm font-bold text-slate-900 mb-1">Bonus requests</h3>
              <p className="text-[11px] text-slate-500 mb-3">
                A bonus only takes effect once an admin approves it.
              </p>
              <ul className="space-y-2">
                {bonusRequests.slice(0, 10).map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 text-xs rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <span className="text-slate-700">
                      <strong className="text-slate-900">{r.business_name}</strong>
                      {" · "}{Number(r.current_pct).toFixed(2)}% → {Number(r.requested_pct).toFixed(2)}%
                    </span>
                    <span className="flex items-center gap-2">
                      {r.decision_note && <span className="text-[11px] text-slate-400">{r.decision_note}</span>}
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                        r.status === "APPROVED" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : r.status === "REJECTED" ? "bg-rose-50 text-rose-700 border-rose-200"
                        : "bg-amber-50 text-amber-700 border-amber-200"
                      }`}>{r.status}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Bonus request form. The agent picks a number between 0 and the
          maximum; what it does to the partner's own rate is the admin's
          business, so it isn't shown or implied here. */}
      {bonusFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4" onClick={() => setBonusFor(null)}>
          <form
            onSubmit={submitBonus}
            onClick={(e) => e.stopPropagation()}
            className="glass-panel rounded-2xl max-w-md w-full p-6 border border-gray-200 shadow-xl space-y-4"
          >
            <div>
              <h3 className="text-lg font-bold text-slate-900">Partner bonus</h3>
              <p className="text-xs text-slate-500 mt-1">
                Your share from <strong className="text-slate-900">{bonusFor.business_name}</strong>&apos;s sales, on top of your
                own commission. Goes to an admin for approval.
              </p>
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">
                Bonus % (0–{Number(overview?.agent?.max_bonus_pct || 10).toFixed(0)})
              </label>
              <input
                type="number" step="0.01" min={0} max={Number(overview?.agent?.max_bonus_pct || 10)} required
                value={bonusPct}
                onChange={(e) => setBonusPct(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-sm font-mono text-slate-900"
              />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Reason <span className="text-slate-400 font-normal">(optional)</span></label>
              <input
                value={bonusReason}
                onChange={(e) => setBonusReason(e.target.value)}
                maxLength={500}
                placeholder="Why this partner, for the admin reviewing it"
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
              />
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={busy} className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold">
                {busy ? "Sending…" : "Send for approval"}
              </button>
              <button type="button" onClick={() => setBonusFor(null)} className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-bold">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {tab === "sales" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h2 className="text-base font-bold text-slate-900 mb-1">Sales you earned on</h2>
          <p className="text-xs text-slate-500 mb-5">
            Every delivered eSIM sold by one of your partners. A refunded sale earns nothing.
          </p>
          {!orders ? (
            <div className="h-32 rounded-xl bg-gray-50 animate-pulse" />
          ) : orders.rows.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-500">No sales yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pe-3 text-start">Order</th>
                    <th className="py-2 pe-3 text-start">Partner</th>
                    <th className="py-2 pe-3 text-start">Product</th>
                    <th className="py-2 pe-3 text-end">Sale</th>
                    <th className="py-2 pe-3 text-end">Their commission</th>
                    <th className="py-2 text-end">Mine</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {orders.rows.map((r: any) => (
                    <tr key={r.order_id}>
                      <td className="py-2.5 pe-3">
                        <div className="font-mono text-brand-600">{r.order_no}</div>
                        <div className="text-[10px] text-slate-400">{new Date(r.created_at).toLocaleDateString()} · {r.status}</div>
                      </td>
                      <td className="py-2.5 pe-3 text-slate-700">{r.merchant}</td>
                      <td className="py-2.5 pe-3 text-slate-700">
                        {r.product} <span className="text-slate-400">({r.country_iso2})</span>
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono text-slate-900">{eur(r.amount)}</td>
                      <td className="py-2.5 pe-3 text-end font-mono text-merchant-600">{eur(r.merchant_commission)}</td>
                      <td className="py-2.5 text-end font-mono font-bold text-emerald-700">{eur(r.my_commission)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "commission" && (
        <div className="space-y-4">
          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h2 className="text-base font-bold text-slate-900 mb-1">Cash out</h2>
            <p className="text-xs text-slate-500 mb-4">
              Commission can&apos;t be withdrawn directly. Move it to your main wallet first, then request a withdrawal.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-2xl font-black text-emerald-600">{eur(ledger?.balance ?? overview?.wallets.commission_balance)}</div>
              <button onClick={moveCommission} disabled={busy || Number(ledger?.balance ?? overview?.wallets.commission_balance ?? 0) <= 0}
                className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
                <ArrowRightLeft className="w-3.5 h-3.5" /> Move to main wallet
              </button>
              <Link href="/wallet/withdraw" className="inline-flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2.5 rounded-xl">
                <Banknote className="w-3.5 h-3.5 text-brand-600" /> Withdraw funds
              </Link>
            </div>
          </div>

          <div className="glass-panel rounded-2xl p-6 border border-gray-200">
            <h2 className="text-base font-bold text-slate-900 mb-4">Commission ledger</h2>
            {!ledger ? (
              <div className="h-32 rounded-xl bg-gray-50 animate-pulse" />
            ) : ledger.entries.length === 0 ? (
              <div className="py-10 text-center text-xs text-slate-500">Nothing here yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-start text-xs">
                  <thead className="text-slate-500 border-b border-gray-200">
                    <tr>
                      <th className="py-2 pe-3 text-start">Date</th>
                      <th className="py-2 pe-3 text-start">What</th>
                      <th className="py-2 pe-3 text-end">Amount</th>
                      <th className="py-2 text-end">Balance after</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {ledger.entries.map((e: any) => (
                      <tr key={e.id}>
                        <td className="py-2.5 pe-3 text-slate-500">{new Date(e.created_at).toLocaleDateString()}</td>
                        <td className="py-2.5 pe-3 text-slate-700">{e.description || e.reference_type}</td>
                        <td className={`py-2.5 pe-3 text-end font-mono font-bold ${e.tx_type === "CREDIT" ? "text-emerald-600" : "text-rose-600"}`}>
                          {e.tx_type === "CREDIT" ? "+" : "−"}{eur(e.amount)}
                        </td>
                        <td className="py-2.5 text-end font-mono text-slate-700">{eur(e.balance_after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "statement" && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 space-y-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-slate-900">Monthly statement</h2>
              <p className="text-xs text-slate-500 mt-1 max-w-xl">
                Every commission credit, transfer and withdrawal for the month, with opening and closing balances — the same
                statement our finance team sees.
              </p>
            </div>
            <div>
              <label className="text-[11px] text-slate-600 font-semibold block mb-1">Month</label>
              <input type="month" value={month} max={currentMonth()} onChange={(e) => setMonth(e.target.value)}
                className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
            </div>
          </div>
          {statement ? (
            <StatementView statement={statement} csvPath={`/api/v1/agent/statement.csv?month=${month}`} csvName={`agent-statement-${month}.csv`} />
          ) : (
            <p className="text-xs text-slate-500">No statement for this month yet.</p>
          )}
        </div>
      )}

      <p className="text-[11px] text-slate-500 flex items-start gap-2">
        <Briefcase className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        Your commission is paid when an eSIM is delivered, and is on top of what the partner earns themselves. A refunded
        order pays neither of you.
      </p>
    </div>
  );
}
