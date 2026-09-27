"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Handshake, Percent, Save, X } from "lucide-react";
import { api } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";
const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;

const STATUS_BADGE: Record<string, string> = {
  PENDING: "bg-amber-50 text-amber-700 border-amber-200",
  APPROVED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  REJECTED: "bg-rose-50 text-rose-700 border-rose-200",
  SUSPENDED: "bg-gray-100 text-slate-600 border-gray-200",
};

// The margin a sale earns, against what the two commissions cost. Both rates
// are percentages of the selling price, so they can add up to more than the
// margin - which is exactly what this warns about before it's saved.
function MarginNote({ margin }: { margin: any }) {
  if (!margin) return null;
  return (
    <div className={`mt-2 rounded-lg border px-3 py-2 text-[11px] ${
      margin.exceeds_margin ? "bg-rose-50 border-rose-200 text-rose-700" : "bg-gray-50 border-gray-200 text-slate-600"
    }`}>
      {margin.exceeds_margin && <AlertTriangle className="w-3.5 h-3.5 inline me-1 -mt-0.5" />}
      A sale earns <strong>{margin.margin_pct_of_price}%</strong> of its price. Partner {margin.merchant_pct}% + agent{" "}
      {margin.agent_pct}% = <strong>{margin.combined_pct}%</strong>
      {margin.exceeds_margin
        ? ` — ${Math.abs(Number(margin.remaining_pct))}% more than the sale makes. These sales would lose money.`
        : `, leaving ${margin.remaining_pct}%.`}
    </div>
  );
}

export default function AgentsTab({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [agents, setAgents] = useState<any[]>([]);
  const [merchants, setMerchants] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rates, setRates] = useState<Record<string, string>>({});
  const [margins, setMargins] = useState<Record<string, any>>({});
  const [rejectTarget, setRejectTarget] = useState<any | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  // Standalone calculator, so a rate can be sanity-checked before anyone is approved.
  const [checkMerchant, setCheckMerchant] = useState("5");
  const [checkAgent, setCheckAgent] = useState("2");
  const [check, setCheck] = useState<any | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      const [list, queue] = await Promise.all([api.getAdminAgents(token), api.getMerchantQueue(token)]);
      setAgents(list);
      setMerchants(queue);
      setRates(Object.fromEntries(list.map((a: any) => [a.id, String(Number(a.commission_rate_pct))])));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load agents" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const handle = setTimeout(() => {
      api.getAgentMarginCheck(token, checkMerchant || "0", checkAgent || "0").then(setCheck).catch(() => setCheck(null));
    }, 300);
    return () => clearTimeout(handle);
  }, [checkMerchant, checkAgent]);

  const approve = async (agent: any) => {
    const token = getToken();
    if (!token) return;
    setBusy(agent.id);
    setNotice(null);
    try {
      const res = await api.approveAgent(token, agent.id);
      await load();
      setNotice({ kind: "ok", text: `${agent.company_name} approved — their agent code is ${res.agent_code}.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't approve" });
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    const token = getToken();
    if (!token || !rejectTarget) return;
    setBusy(rejectTarget.id);
    setNotice(null);
    try {
      const res = await api.rejectAgent(token, rejectTarget.id, rejectReason.trim());
      const name = rejectTarget.company_name;
      setRejectTarget(null);
      setRejectReason("");
      await load();
      setNotice({
        kind: "ok",
        text: res.agent_status === "SUSPENDED"
          ? `${name} suspended. They stop earning on new sales and keep what they already earned.`
          : `${name}'s application was rejected.`,
      });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't update" });
    } finally {
      setBusy(null);
    }
  };

  const saveRate = async (agent: any) => {
    const token = getToken();
    if (!token) return;
    setBusy(agent.id);
    setNotice(null);
    try {
      const res = await api.updateAgentCommission(token, agent.id, rates[agent.id]);
      setMargins((m) => ({ ...m, [agent.id]: res.margin }));
      await load();
      setNotice({
        kind: res.margin?.exceeds_margin ? "error" : "ok",
        text: res.margin?.exceeds_margin
          ? `Saved at ${res.rate_pct}% — but ${res.margin.warning}`
          : `${agent.company_name} is now on ${res.rate_pct}%.`,
      });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save the rate" });
    } finally {
      setBusy(null);
    }
  };

  const saveMapping = async (merchant: any) => {
    const token = getToken();
    if (!token) return;
    const code = (mapping[merchant.id] ?? "").trim();
    setBusy(merchant.id);
    setNotice(null);
    try {
      const res = await api.updateMerchantAgent(token, merchant.id, code || null);
      await load();
      setMapping((m) => ({ ...m, [merchant.id]: "" }));
      setNotice({
        kind: res.margin?.exceeds_margin ? "error" : "ok",
        text: res.agent_user_id
          ? (res.margin?.exceeds_margin
            ? `Mapped — but ${res.margin.warning}`
            : `${merchant.business_name} is now mapped to that agent.`)
          : `${merchant.business_name} no longer has an agent.`,
      });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't change the agent" });
    } finally {
      setBusy(null);
    }
  };

  const approvedCodes = agents.filter((a) => a.status === "APPROVED");

  return (
    <div className="space-y-6">
      {/* Margin calculator */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Percent className="w-4 h-4 text-admin-600" /> What a pair of rates costs
        </h3>
        <p className="text-xs text-slate-500 mt-1 max-w-2xl">
          Agent commission is a percentage of the <strong>sale price</strong>, like the partner&apos;s, and both come out of the
          same margin. Check a pair here before you set it.
        </p>
        <div className="flex flex-wrap items-end gap-3 mt-4">
          <div>
            <label className="text-[11px] text-slate-700 font-semibold block mb-1">Partner %</label>
            <input className={`${inputCls} w-24 font-mono`} inputMode="decimal" value={checkMerchant}
              onChange={(e) => setCheckMerchant(e.target.value)} />
          </div>
          <div>
            <label className="text-[11px] text-slate-700 font-semibold block mb-1">Agent %</label>
            <input className={`${inputCls} w-24 font-mono`} inputMode="decimal" value={checkAgent}
              onChange={(e) => setCheckAgent(e.target.value)} />
          </div>
        </div>
        <MarginNote margin={check} />
      </div>

      {notice && (
        <p className={`text-xs font-medium ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
      )}

      {/* Agents */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-1">
          <Handshake className="w-4 h-4 text-admin-600" /> Agents
        </h3>
        <p className="text-xs text-slate-500 mb-5 max-w-2xl">
          An agent earns on everything their partners sell. Suspending one stops future commission immediately and never
          touches what they already earned.
        </p>

        {loading ? (
          <div className="space-y-2">{[0, 1].map((i) => <div key={i} className="h-24 rounded-xl bg-gray-100 animate-pulse" />)}</div>
        ) : agents.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No agent applications yet. Anyone can apply from the Agent portal.
          </div>
        ) : (
          <div className="space-y-3">
            {agents.map((a) => (
              <div key={a.id} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-slate-900">{a.company_name}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${STATUS_BADGE[a.status]}`}>{a.status}</span>
                      {a.status === "APPROVED" && (
                        <span className="font-mono text-[11px] font-bold text-brand-600">{a.agent_code}</span>
                      )}
                      {a.role === "MERCHANT" && (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-merchant-50 text-merchant-600 border border-merchant-200">
                          also a partner
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-600 mt-1">{a.username} · {a.email} · {a.contact_phone}</div>
                    {a.rejection_reason && <div className="text-[11px] text-rose-600 mt-1">{a.rejection_reason}</div>}
                  </div>
                  <div className="text-end shrink-0 text-xs">
                    <div className="text-slate-500">{a.merchants} partner(s)</div>
                    <div className="text-slate-500">{a.orders ?? 0} delivered sale(s)</div>
                    <div className="font-mono font-bold text-emerald-700">{eur(a.commission_earned)} earned</div>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-end gap-3">
                  {isSuperAdmin && (
                    <div>
                      <label className="text-[11px] text-slate-700 font-semibold block mb-1">Commission %</label>
                      <div className="flex gap-2">
                        <input className={`${inputCls} w-20 font-mono`} inputMode="decimal"
                          value={rates[a.id] ?? ""} onChange={(e) => setRates((r) => ({ ...r, [a.id]: e.target.value }))} />
                        <button onClick={() => saveRate(a)} disabled={busy === a.id}
                          className="flex items-center gap-1 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-xs font-bold px-3 py-2 rounded-lg">
                          <Save className="w-3.5 h-3.5" /> Save
                        </button>
                      </div>
                    </div>
                  )}
                  {!isSuperAdmin && (
                    <div className="text-xs text-slate-600">
                      Commission <strong>{Number(a.commission_rate_pct)}%</strong>
                    </div>
                  )}

                  <div className="flex gap-2 ms-auto">
                    {a.status !== "APPROVED" && (
                      <button onClick={() => approve(a)} disabled={busy === a.id}
                        className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-bold px-3 py-2 rounded-lg">
                        <Check className="w-3.5 h-3.5" /> {a.status === "PENDING" ? "Approve" : "Reinstate"}
                      </button>
                    )}
                    {a.status !== "REJECTED" && (
                      <button onClick={() => { setRejectTarget(a); setRejectReason(""); }}
                        className="flex items-center gap-1.5 bg-white hover:bg-rose-50 border border-gray-300 text-rose-600 text-xs font-bold px-3 py-2 rounded-lg">
                        <X className="w-3.5 h-3.5" /> {a.status === "APPROVED" ? "Suspend" : "Reject"}
                      </button>
                    )}
                  </div>
                </div>
                <MarginNote margin={margins[a.id]} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Partner → agent mapping */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 mb-1">Partner &rarr; agent mapping</h3>
        <p className="text-xs text-slate-500 mb-5 max-w-2xl">
          Assign, move or clear a partner&apos;s agent. Past sales keep the agent they were paid to, so this only changes who
          earns from here on. Leave the box empty and save to remove the mapping.
        </p>
        {merchants.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">No partners yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Partner</th>
                  <th className="py-2 pe-3 text-end">Their %</th>
                  <th className="py-2 pe-3 text-start">Agent</th>
                  <th className="py-2 text-start">Change to</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {merchants.map((m) => (
                  <tr key={m.id}>
                    <td className="py-2.5 pe-3">
                      <div className="font-semibold text-slate-900">{m.business_name}</div>
                      <div className="text-[10px] text-slate-400">{m.email} · {m.status}</div>
                    </td>
                    <td className="py-2.5 pe-3 text-end font-mono text-merchant-600">{Number(m.commission_rate_pct).toFixed(2)}%</td>
                    <td className="py-2.5 pe-3">
                      {m.agent ? (
                        <>
                          <div className="font-mono text-brand-600">{m.agent.agent_code}</div>
                          <div className="text-[10px] text-slate-400">{m.agent.username} · {Number(m.agent.commission_rate_pct).toFixed(2)}%</div>
                        </>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <div className="flex gap-2">
                        <select
                          className={`${inputCls} min-w-[150px]`}
                          value={mapping[m.id] ?? ""}
                          onChange={(e) => setMapping((s) => ({ ...s, [m.id]: e.target.value }))}
                        >
                          <option value="">No agent</option>
                          {approvedCodes.map((a) => (
                            <option key={a.id} value={a.agent_code}>{a.agent_code} — {a.company_name}</option>
                          ))}
                        </select>
                        <button onClick={() => saveMapping(m)} disabled={busy === m.id}
                          className="bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-xs font-bold px-3 py-2 rounded-lg">
                          Save
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={rejectTarget !== null}
        title={rejectTarget?.status === "APPROVED" ? "Suspend this agent?" : "Reject this application?"}
        tone="danger"
        icon={<X className="w-5 h-5" />}
        confirmLabel={rejectTarget?.status === "APPROVED" ? "Suspend" : "Reject"}
        busy={busy === rejectTarget?.id}
        onConfirm={reject}
        onCancel={() => setRejectTarget(null)}
      >
        <p className="mb-3">
          {rejectTarget?.status === "APPROVED"
            ? `${rejectTarget?.company_name} stops earning on new sales straight away. Commission they already earned stays theirs, and their partners keep selling as normal.`
            : `${rejectTarget?.company_name} won't get an agent code.`}
        </p>
        <label className="text-[11px] text-slate-700 font-semibold block mb-1">Reason (shown to them)</label>
        <input className={`${inputCls} w-full`} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
          placeholder="e.g. Could not verify the company" />
      </ConfirmDialog>
    </div>
  );
}
