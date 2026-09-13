"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Download, Scale } from "lucide-react";
import { api } from "@/lib/api";
import StatementView, { REFERENCE_LABELS, currentMonth, eur, saveBlob } from "@/components/finance/StatementView";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

function Figure({ label, value, hint, tone = "text-slate-900" }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">{label}</div>
      <div className={`text-lg font-black font-mono ${tone}`}>{value}</div>
      {hint && <div className="text-[10px] text-slate-400 leading-snug">{hint}</div>}
    </div>
  );
}

const EXCEPTIONS: { key: string; title: string; explain: string; severity: "high" | "medium" }[] = [
  { key: "charged_but_failed", title: "VivaPe charged, customer refunded", explain: "VivaPe created a transaction but we refunded the customer. Claim these back from VivaPe (or recover the eSIM).", severity: "high" },
  { key: "supplier_trx_without_order", title: "VivaPe transactions not linked to any order", explain: "We were charged for these but no order carries the transaction id. Check against VivaPe's statement.", severity: "high" },
  { key: "duplicate_trx_ids", title: "Same VivaPe transaction on several orders", explain: "One supplier charge attached to more than one order.", severity: "high" },
  { key: "stuck_in_progress", title: "Orders stuck setting up (30+ min)", explain: "Paid but not completed or refunded. Recovery normally resolves these; look if they stay.", severity: "medium" },
  { key: "completed_without_trx", title: "Completed without a VivaPe transaction id", explain: "Usually older orders from before transaction ids were stored, or test/mock orders.", severity: "medium" },
  { key: "completed_missing_cost", title: "Completed without a cost snapshot", explain: "Profit can't be computed for these (orders from before cost was recorded).", severity: "medium" },
];

function ExceptionGroup({ def, items }: { def: (typeof EXCEPTIONS)[number]; items: any[] }) {
  const [open, setOpen] = useState(false);
  const clean = items.length === 0;
  return (
    <div className={`rounded-xl border p-3 ${clean ? "border-gray-200 bg-white" : def.severity === "high" ? "border-rose-200 bg-rose-50/40" : "border-amber-200 bg-amber-50/40"}`}>
      <button type="button" disabled={clean} onClick={() => setOpen(!open)} className="w-full flex items-start justify-between gap-3 text-start">
        <div>
          <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
            {clean ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <AlertTriangle className={`w-3.5 h-3.5 ${def.severity === "high" ? "text-rose-600" : "text-amber-600"}`} />}
            {def.title}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">{def.explain}</div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <span className={`text-xs font-black font-mono ${clean ? "text-emerald-600" : "text-slate-900"}`}>{items.length}</span>
          {!clean && (open ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />)}
        </div>
      </button>
      {open && (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="py-1 pe-3 text-start font-medium">{def.key === "supplier_trx_without_order" ? "VivaPe trx" : "Order"}</th>
                <th className="py-1 pe-3 text-start font-medium">Date</th>
                {def.key !== "supplier_trx_without_order" && (
                  <>
                    <th className="py-1 pe-3 text-start font-medium">Status</th>
                    <th className="py-1 pe-3 text-start font-medium">VivaPe trx</th>
                    <th className="py-1 pe-3 text-start font-medium">Product · buyer</th>
                    <th className="py-1 text-end font-medium">Cost / price</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((o, i) =>
                def.key === "supplier_trx_without_order" ? (
                  <tr key={i}>
                    <td className="py-1.5 pe-3 font-mono">{o.vivape_trx_id}</td>
                    <td className="py-1.5 pe-3 text-slate-500">{o.logged_at ? new Date(o.logged_at).toLocaleString() : "—"}</td>
                  </tr>
                ) : (
                  <tr key={o.order_id}>
                    <td className="py-1.5 pe-3 font-mono text-admin-600">{o.order_no}</td>
                    <td className="py-1.5 pe-3 text-slate-500 whitespace-nowrap">{o.created_at ? new Date(o.created_at).toLocaleString() : "—"}</td>
                    <td className="py-1.5 pe-3 text-slate-600">{o.status}</td>
                    <td className="py-1.5 pe-3 font-mono text-slate-600">{o.vivape_trx_id || "—"}</td>
                    <td className="py-1.5 pe-3 text-slate-700">{o.product} <span className="text-slate-400">· {o.buyer}</span></td>
                    <td className="py-1.5 text-end font-mono">{eur(o.cost)} / {eur(o.selling_price)}</td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function FinanceTab() {
  const now = new Date();
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))));
  const [dateTo, setDateTo] = useState(isoDay(now));
  const [summary, setSummary] = useState<any | null>(null);
  const [recon, setRecon] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showLedger, setShowLedger] = useState(false);

  const [merchants, setMerchants] = useState<any[]>([]);
  const [merchantId, setMerchantId] = useState("");
  const [month, setMonth] = useState(currentMonth());
  const [statement, setStatement] = useState<any | null>(null);
  const [statementError, setStatementError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
      const [s, r] = await Promise.all([api.getFinanceSummary(token, params), api.getVivapeReconciliation(token, params)]);
      setSummary(s);
      setRecon(r);
    } catch (err: any) {
      setError(err.message || "Couldn't load finance reports");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api
      .getMerchantQueue(token)
      .then((list: any[]) => {
        const approved = list.filter((m) => m.status === "APPROVED");
        setMerchants(approved);
        if (approved.length) setMerchantId((id) => id || approved[0].user_id);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token || !merchantId || !month) return;
    setStatementError(null);
    api
      .getAdminMerchantStatement(token, merchantId, month)
      .then(setStatement)
      .catch((err: any) => setStatementError(err.message || "Couldn't load the statement"));
  }, [merchantId, month]);

  const downloadVivape = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const qs = new URLSearchParams({ ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) });
      saveBlob(await api.downloadAuthed(token, `/api/v1/admin/finance/vivape.csv?${qs}`), `vivape-charges-${dateFrom}-to-${dateTo}.csv`);
    } catch (err: any) {
      setError(err.message || "Download failed");
    }
  };

  const selectedMerchant = merchants.find((m) => m.user_id === merchantId);

  return (
    <div className="space-y-6">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2"><Scale className="w-4 h-4 text-admin-600" /> Finance &amp; reconciliation</h3>
        <p className="text-xs text-slate-500 mt-1 mb-4 max-w-3xl">
          Where the money came from, where it went, what we still owe wallet holders, and whether our records agree with
          VivaPe&apos;s. Built from the wallet ledger, orders and the VivaPe request log — nothing here changes any data.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          {loading && <span className="text-[11px] text-slate-500 pb-2">Loading…</span>}
        </div>
        {error && <p className="text-xs text-rose-600 mt-3">{error}</p>}
      </div>

      {summary && (
        <>
          <div className="glass-panel rounded-2xl p-6 border border-gray-200 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-bold text-slate-900">Money cycle</h4>
              {summary.integrity.ok ? (
                <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-700"><CheckCircle2 className="w-3.5 h-3.5" /> Ledger balanced — every wallet matches its transactions</span>
              ) : (
                <span className="flex items-center gap-1 text-[11px] font-semibold text-rose-700">
                  <AlertTriangle className="w-3.5 h-3.5" /> {summary.integrity.wallet_balance_mismatches} wallet(s) don&apos;t match their ledger · {summary.integrity.entries_with_bad_arithmetic} bad entries
                </span>
              )}
            </div>

            <div>
              <div className="text-[11px] font-semibold text-slate-500 mb-1.5">1 · Money received</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Figure label="Gateway top-ups" value={eur(summary.money_in.gateway_top_ups)} />
                <Figure label="Manual deposits" value={eur(summary.money_in.manual_deposits)} hint="bKash / Nagad / bank, approved" />
                <Figure label="Paid at checkout" value={eur(summary.money_in.gateway_order_payments)} hint="gateway, not via wallet" />
                <Figure label="Total received" value={eur(summary.money_in.total)} tone="text-emerald-700" />
              </div>
            </div>

            <div>
              <div className="text-[11px] font-semibold text-slate-500 mb-1.5">2 · Sales and what VivaPe costs us</div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <Figure label="Completed sales" value={eur(summary.sales.selling_price)} hint={`${summary.sales.completed_orders} orders`} />
                <Figure label="VivaPe cost" value={eur(summary.sales.supplier_cost)} tone="text-slate-600" />
                <Figure label="Gross profit" value={eur(summary.sales.gross_profit)} tone="text-emerald-600" />
                <Figure label="Merchant commission" value={eur(summary.sales.merchant_commission)} tone="text-merchant-600" />
                <Figure label="Net profit" value={eur(summary.sales.net_profit)} tone="text-emerald-700" />
              </div>
            </div>

            <div>
              <div className="text-[11px] font-semibold text-slate-500 mb-1.5">3 · Wallet movements</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Figure label="Spent from wallets" value={eur(summary.wallets.spent_on_orders)} />
                <Figure label="Refunded to wallets" value={eur(summary.wallets.refunded_to_wallets)} hint="failed orders" />
                <Figure label="Commission earned" value={eur(summary.wallets.commission_earned)} />
                <Figure label="Commission → main wallet" value={eur(summary.wallets.commission_moved_to_main_wallet)} />
              </div>
              {(Number(summary.money_in.admin_adjustments_credit) > 0 || Number(summary.money_in.admin_adjustments_debit) > 0) && (
                <p className="text-[11px] text-amber-700 mt-2">
                  Admin adjustments this period: +{eur(summary.money_in.admin_adjustments_credit)} / −{eur(summary.money_in.admin_adjustments_debit)} (credited without a payment — check the audit log).
                </p>
              )}
            </div>

            <div>
              <div className="text-[11px] font-semibold text-slate-500 mb-1.5">4 · What we owe right now (wallet balances)</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(summary.liabilities.groups).map(([key, g]: [string, any]) => (
                  <Figure key={key} label={key.replace(/_/g, " ")} value={eur(g.balance)} hint={`${g.wallets} wallets`} />
                ))}
                <Figure label="Total liability" value={eur(summary.liabilities.total)} tone="text-rose-700" hint="must stay covered by cash + VivaPe balance" />
              </div>
            </div>

            <button type="button" onClick={() => setShowLedger(!showLedger)} className="flex items-center gap-1 text-[11px] font-semibold text-slate-600 hover:text-slate-900">
              {showLedger ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />} Ledger breakdown
            </button>
            {showLedger && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-slate-500 border-b border-gray-200">
                    <tr>
                      <th className="py-1.5 pe-3 text-start font-medium">Movement</th>
                      <th className="py-1.5 pe-3 text-start font-medium">Wallet</th>
                      <th className="py-1.5 pe-3 text-end font-medium">Entries</th>
                      <th className="py-1.5 pe-3 text-end font-medium">In</th>
                      <th className="py-1.5 text-end font-medium">Out</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {summary.ledger_breakdown.map((r: any, i: number) => (
                      <tr key={i}>
                        <td className="py-1.5 pe-3 text-slate-700">{REFERENCE_LABELS[r.reference_type] || r.reference_type}</td>
                        <td className="py-1.5 pe-3 text-slate-500">{r.holder} · {r.wallet_type.toLowerCase()}</td>
                        <td className="py-1.5 pe-3 text-end font-mono">{r.entries}</td>
                        <td className="py-1.5 pe-3 text-end font-mono text-emerald-600">{Number(r.credits) ? eur(r.credits) : ""}</td>
                        <td className="py-1.5 text-end font-mono text-rose-600">{Number(r.debits) ? eur(r.debits) : ""}</td>
                      </tr>
                    ))}
                    {summary.ledger_breakdown.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-slate-500">No wallet movements in this period.</td></tr>}
                  </tbody>
                </table>
              </div>
            )}

            {!summary.integrity.ok && summary.integrity.mismatched_wallets.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-rose-200 bg-rose-50/40 p-3">
                <div className="text-xs font-bold text-rose-800 mb-1">Wallets whose balance doesn&apos;t match their transactions</div>
                <table className="w-full text-xs">
                  <tbody className="divide-y divide-rose-100">
                    {summary.integrity.mismatched_wallets.map((w: any) => (
                      <tr key={w.wallet_id}>
                        <td className="py-1 pe-3">{w.username} <span className="text-slate-400">{w.email}</span></td>
                        <td className="py-1 pe-3 text-slate-500">{w.wallet_type}</td>
                        <td className="py-1 pe-3 text-end font-mono">balance {eur(w.balance)}</td>
                        <td className="py-1 pe-3 text-end font-mono">ledger {eur(w.ledger_total)}</td>
                        <td className="py-1 text-end font-mono font-bold text-rose-700">{eur(w.difference)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {recon && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="text-sm font-bold text-slate-900">VivaPe reconciliation</h4>
              <p className="text-xs text-slate-500 mt-1 max-w-2xl">
                Download the charge list and tick it off against VivaPe&apos;s statement for the same dates. Anything listed
                below needs a look before the totals will match.
              </p>
            </div>
            <button type="button" onClick={downloadVivape} className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg">
              <Download className="w-3.5 h-3.5" /> VivaPe charges CSV
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Figure label="Expected VivaPe charges" value={eur(summary?.supplier.expected_vivape_charges)} hint="completed + failed-after-charge" />
            <Figure label="Completed with trx id" value={String(recon.totals.completed_orders_with_trx)} hint={eur(recon.totals.expected_cost_completed)} />
            <Figure label="Charged on failed orders" value={eur(recon.totals.charged_on_failed_orders)} tone={Number(recon.totals.charged_on_failed_orders) > 0 ? "text-rose-700" : "text-slate-900"} hint="to recover from VivaPe" />
            <Figure label="VivaPe calls" value={`${recon.totals.supplier_calls_succeeded} ok`} hint={`${recon.totals.supplier_calls_failed} failed (no charge)`} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {EXCEPTIONS.map((def) => <ExceptionGroup key={def.key} def={def} items={recon.exceptions[def.key] || []} />)}
          </div>
        </div>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h4 className="text-sm font-bold text-slate-900">Merchant monthly statements</h4>
            <p className="text-xs text-slate-500 mt-1">The merchant sees exactly this statement in their dashboard.</p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="text-[11px] text-slate-600 font-semibold block mb-1">Merchant</label>
              <select value={merchantId} onChange={(e) => setMerchantId(e.target.value)} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 max-w-[240px]">
                {merchants.length === 0 && <option value="">No approved merchants</option>}
                {merchants.map((m) => <option key={m.user_id} value={m.user_id}>{m.business_name} ({m.username})</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-slate-600 font-semibold block mb-1">Month</label>
              <input type="month" value={month} max={currentMonth()} onChange={(e) => setMonth(e.target.value)} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
            </div>
          </div>
        </div>
        {statementError && <p className="text-xs text-rose-600">{statementError}</p>}
        {statement && selectedMerchant && (
          <StatementView
            statement={statement}
            csvPath={`/api/v1/admin/finance/merchant-statement.csv?user_id=${encodeURIComponent(merchantId)}&month=${month}`}
            csvName={`statement-${selectedMerchant.username}-${month}.csv`}
          />
        )}
      </div>
    </div>
  );
}
