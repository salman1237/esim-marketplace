"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, RefreshCw, WifiOff, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { ChartCard, ColumnChart, HBarChart, Legend, LineChart, Meter, ShareBar, StatTile, VIZ, shortDate } from "./charts";
import { formatDateTime } from "@/lib/datetime";

const RANGES = [7, 30, 90];
const CHANNEL_LABELS: Record<string, string> = { web: "Website", api: "Partner API", admin: "Admin console" };

// Report amounts are accounting figures in the base currency (EUR).
const eur = (n: number) => `€${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const eurAxis = (n: number) => (n >= 1000 ? `€${(n / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1 })}k` : `€${n.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`);
// Stat-tile values auto-compact (1,284 -> 1.3K) so they fit a narrow tile;
// the exact figure is in the tables and the Sales & Profit report.
const compactEur = (n: number) =>
  Math.abs(n) >= 1_000_000 ? `€${(n / 1_000_000).toFixed(1)}M`
  : Math.abs(n) >= 1000 ? `€${(n / 1000).toFixed(1)}K`
  : eur(n);
const count = (n: number) => n.toLocaleString("en-GB", { maximumFractionDigits: 0 });

type Status = "good" | "warning" | "serious" | "critical";
const STATUS_ICON: Record<Status, React.ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  good: CheckCircle2, warning: AlertTriangle, serious: AlertTriangle, critical: XCircle,
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

export default function OverviewTab({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.getAdminDashboard(token, days));
    } catch (err: any) {
      setError(err.message || "Couldn't load the overview");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  const periodLabel = `previous ${days} days`;
  const daily: any[] = data?.daily || [];
  const labels = daily.map((d) => d.day);
  const num = (v: any) => Number(v || 0);

  const attentionItems: { key: string; label: string; detail: string; status: Status; tab?: string }[] = data
    ? [
        {
          key: "stuck", tab: "orders",
          label: data.attention.stuck_orders ? `${data.attention.stuck_orders} order(s) stuck setting up` : "No stuck orders",
          detail: "Paid but not delivered for 30+ minutes",
          status: data.attention.stuck_orders ? "critical" : "good",
        },
        {
          key: "ledger", tab: "finance",
          label: data.attention.ledger_ok ? "Wallet ledger balanced" : `${data.attention.ledger_mismatches} wallet(s) don't match their ledger`,
          detail: "Every wallet equals the sum of its transactions",
          status: data.attention.ledger_ok ? "good" : "critical",
        },
        {
          key: "failed", tab: "sales",
          label: data.attention.failed_orders ? `${data.attention.failed_orders} failed order(s) · ${data.attention.failure_rate_pct}%` : "No failed orders",
          detail: `Refunded automatically · last ${days} days`,
          status: !data.attention.failed_orders ? "good" : data.attention.failure_rate_pct >= 10 ? "critical" : "serious",
        },
        {
          key: "deposits", tab: "payments",
          label: data.attention.pending_deposits ? `${data.attention.pending_deposits} manual deposit(s) to review` : "No deposits waiting",
          detail: "bKash / Nagad / bank transfers",
          status: data.attention.pending_deposits ? "warning" : "good",
        },
        {
          key: "merchants", tab: "merchants",
          label: data.attention.pending_merchants ? `${data.attention.pending_merchants} merchant application(s)` : "No merchant applications",
          detail: `${data.merchants.approved} approved · ${data.merchants.active} sold in this period`,
          status: data.attention.pending_merchants ? "warning" : "good",
        },
        {
          key: "kyc", tab: "kyc",
          label: data.attention.pending_kyc ? `${data.attention.pending_kyc} KYC submission(s)` : "No KYC waiting",
          detail: "Identity documents to review",
          status: data.attention.pending_kyc ? "warning" : "good",
        },
        {
          key: "not-installed", tab: "orders",
          label: data.attention.delivered_not_installed
            ? `${data.attention.delivered_not_installed} eSIM(s) delivered but never installed`
            : "No stalled installs",
          detail: "Checked with the carrier, 48h+ after delivery",
          status: data.attention.delivered_not_installed ? "warning" : "good",
        },
        {
          key: "withdrawals", tab: "withdrawals",
          label: data.attention.pending_withdrawals ? `${data.attention.pending_withdrawals} withdrawal(s) to pay out` : "No withdrawals waiting",
          detail: "Balance already held from the wallet",
          status: data.attention.pending_withdrawals ? "warning" : "good",
        },
      ]
    : [];

  const channelParts = (data?.channels || []).map((c: any, i: number) => ({
    name: CHANNEL_LABELS[c.channel] || c.channel, value: num(c.sales), color: VIZ.series[i],
  }));
  const gatewaySales = num((data?.payment_methods || []).find((p: any) => p.method === "SHURJOPAY")?.sales);
  const walletSales = num((data?.payment_methods || []).find((p: any) => p.method === "WALLET")?.sales);
  const paidTotal = gatewaySales + walletSales;

  return (
    <div className="space-y-6">
      {/* One filter row above everything it scopes. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-gray-200 bg-white p-1" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${days === r ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-gray-50"}`}
            >
              Last {r} days
            </button>
          ))}
        </div>
        {data && <span className="text-[11px]" style={{ color: VIZ.muted }}>{shortDate(data.period.start)} – {shortDate(data.period.end)} · amounts in EUR</span>}
        {error && <span className="text-xs text-rose-600">{error}</span>}
      </div>

      {!data ? (
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-28 rounded-2xl bg-gray-100 animate-pulse" />)}
        </div>
      ) : (
        // Refetch keeps the frame: the previous render dims instead of flashing.
        <div className={`space-y-6 transition-opacity ${loading ? "opacity-60" : ""}`}>
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
            <StatTile label="Sales" value={compactEur(num(data.kpis.sales.current))} current={num(data.kpis.sales.current)} previous={num(data.kpis.sales.previous)} periodLabel={periodLabel} spark={daily.map((d) => num(d.sales))} />
            <StatTile label="Net profit" value={compactEur(num(data.kpis.net_profit.current))} current={num(data.kpis.net_profit.current)} previous={num(data.kpis.net_profit.previous)} periodLabel={periodLabel} spark={daily.map((d) => num(d.net_profit))} />
            <StatTile label="eSIMs sold" value={count(num(data.kpis.orders.current))} current={num(data.kpis.orders.current)} previous={num(data.kpis.orders.previous)} periodLabel={periodLabel} spark={daily.map((d) => d.orders)} />
            <StatTile label="New customers" value={count(num(data.kpis.new_customers.current))} current={num(data.kpis.new_customers.current)} previous={num(data.kpis.new_customers.previous)} periodLabel={periodLabel} spark={daily.map((d) => d.new_customers)} />
            <StatTile label="Money received" value={compactEur(num(data.kpis.topups.current))} current={num(data.kpis.topups.current)} previous={num(data.kpis.topups.previous)} periodLabel={periodLabel} spark={daily.map((d) => num(d.topups))} />
            <StatTile label="Owed in wallets" value={compactEur(num(data.kpis.wallet_liability.current))} note="Balances held right now" />
          </div>

          <SupplierBalanceCard />


          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <ChartCard
              className="xl:col-span-2"
              title="Sales and VivaPe cost"
              subtitle={`Completed orders per day · last ${days} days`}
              legend={<Legend items={[{ label: "Sales", color: VIZ.series[0] }, { label: "VivaPe cost", color: VIZ.series[1] }]} />}
              table={{
                columns: ["Day", "Sales", "VivaPe cost", "Net profit"],
                rows: daily.map((d) => [shortDate(d.day), eur(num(d.sales)), eur(num(d.cost)), eur(num(d.net_profit))]),
              }}
            >
              <LineChart
                labels={labels}
                series={[
                  { name: "Sales", color: VIZ.series[0], values: daily.map((d) => num(d.sales)), area: true },
                  { name: "VivaPe cost", color: VIZ.series[1], values: daily.map((d) => num(d.cost)) },
                ]}
                fmt={eur}
                fmtAxis={eurAxis}
                ariaLabel={`Daily sales and VivaPe cost over the last ${days} days`}
              />
            </ChartCard>

            <div className="glass-panel rounded-2xl border border-gray-200 p-5 bg-white">
              <div className="text-sm font-bold mb-3" style={{ color: VIZ.primary }}>Needs attention</div>
              <ul className="space-y-1">
                {attentionItems.map((a) => {
                  const Icon = STATUS_ICON[a.status];
                  return (
                    <li key={a.key}>
                      <button
                        type="button"
                        onClick={() => a.tab && onNavigate(a.tab)}
                        className="w-full flex items-start gap-3 rounded-xl px-2 py-2 text-start hover:bg-gray-50"
                      >
                        <Icon className="w-4 h-4 mt-0.5 shrink-0" style={{ color: VIZ.status[a.status] }} />
                        <span className="flex-1 min-w-0">
                          <span className="block text-xs font-semibold" style={{ color: VIZ.primary }}>{a.label}</span>
                          <span className="block text-[11px]" style={{ color: VIZ.muted }}>{a.detail}</span>
                        </span>
                        <ChevronRight className="w-3.5 h-3.5 mt-0.5 text-slate-300 shrink-0" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartCard
              title="eSIMs sold per day"
              subtitle="Completed orders"
              table={{ columns: ["Day", "eSIMs sold", "Failed"], rows: daily.map((d) => [shortDate(d.day), d.orders, d.failed]) }}
            >
              <ColumnChart labels={labels} values={daily.map((d) => d.orders)} color={VIZ.series[0]} fmt={count} seriesName="eSIMs sold" ariaLabel={`eSIMs sold per day over the last ${days} days`} />
            </ChartCard>

            <ChartCard
              title="Top destinations"
              subtitle="By sales, completed orders"
              table={{ columns: ["Country", "Sales", "Orders"], rows: (data.top_destinations || []).map((t: any) => [`${t.country} (${t.iso2})`, eur(num(t.sales)), t.orders]) }}
            >
              <HBarChart
                items={(data.top_destinations || []).map((t: any) => ({ label: t.country, value: num(t.sales), detail: `${t.orders} order${t.orders === 1 ? "" : "s"}` }))}
                color={VIZ.series[0]}
                fmt={eur}
                seriesName="Sales"
                ariaLabel="Top destinations by sales"
              />
            </ChartCard>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartCard
              title="Where sales come from"
              subtitle="Completed sales by channel"
              table={{ columns: ["Channel", "Sales", "Orders"], rows: (data.channels || []).map((c: any) => [CHANNEL_LABELS[c.channel] || c.channel, eur(num(c.sales)), c.orders]) }}
            >
              <ShareBar parts={channelParts} fmt={eur} ariaLabel="Share of sales by channel" />
            </ChartCard>

            <ChartCard
              title="How customers pay"
              subtitle="Completed sales by payment method"
              table={{ columns: ["Method", "Sales", "Orders"], rows: (data.payment_methods || []).map((p: any) => [p.method === "SHURJOPAY" ? "ShurjoPay (card / mobile banking)" : p.method === "WALLET" ? "Wallet" : p.method, eur(num(p.sales)), p.orders]) }}
            >
              <div className="space-y-4">
                <Meter
                  ratio={paidTotal ? gatewaySales / paidTotal : 0}
                  label="Paid through ShurjoPay"
                  detail={paidTotal ? `${eur(gatewaySales)} by card / mobile banking · ${eur(walletSales)} from wallets` : "No completed sales in this period"}
                />
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="rounded-xl bg-gray-50 border border-gray-100 p-3">
                    <div style={{ color: VIZ.muted }}>Money received</div>
                    <div className="text-base font-semibold" style={{ color: VIZ.primary }}>{eur(num(data.kpis.topups.current))}</div>
                    <div className="text-[11px]" style={{ color: VIZ.muted }}>wallet top-ups</div>
                  </div>
                  <div className="rounded-xl bg-gray-50 border border-gray-100 p-3">
                    <div style={{ color: VIZ.muted }}>Owed in wallets</div>
                    <div className="text-base font-semibold" style={{ color: VIZ.primary }}>{eur(num(data.kpis.wallet_liability.current))}</div>
                    <div className="text-[11px]" style={{ color: VIZ.muted }}>customer + merchant balances</div>
                  </div>
                </div>
              </div>
            </ChartCard>
          </div>

          <div className="glass-panel rounded-2xl border border-gray-200 p-5 bg-white">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-bold" style={{ color: VIZ.primary }}>Recent orders</div>
              <button type="button" onClick={() => onNavigate("orders")} className="text-xs font-semibold text-admin-600 hover:underline">All orders</button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200" style={{ color: VIZ.secondary }}>
                    <th className="py-2 pe-3 text-start font-semibold">Order</th>
                    <th className="py-2 pe-3 text-start font-semibold">When</th>
                    <th className="py-2 pe-3 text-start font-semibold">Buyer</th>
                    <th className="py-2 pe-3 text-start font-semibold">Package</th>
                    <th className="py-2 pe-3 text-start font-semibold">Status</th>
                    <th className="py-2 text-end font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.recent_orders || []).map((o: any) => {
                    const st: Status | null = o.status === "COMPLETED" ? "good" : o.status === "FAILED" ? "critical" : o.status === "PENDING" ? null : "warning";
                    const Icon = st ? STATUS_ICON[st] : null;
                    return (
                      <tr key={o.order_no} className="border-b border-gray-100">
                        <td className="py-2 pe-3 font-mono" style={{ color: VIZ.primary }}>
                          {o.order_no}
                          <span className="ms-1.5 font-sans text-[10px]" style={{ color: VIZ.muted }}>{CHANNEL_LABELS[o.channel]}</span>
                        </td>
                        <td className="py-2 pe-3 whitespace-nowrap" style={{ color: VIZ.secondary }}>{formatDateTime(o.created_at)}</td>
                        <td className="py-2 pe-3 truncate max-w-[180px]" style={{ color: VIZ.secondary }}>{o.buyer}</td>
                        <td className="py-2 pe-3" style={{ color: VIZ.secondary }}>{o.country_iso2} · {o.product}</td>
                        <td className="py-2 pe-3">
                          <span className="inline-flex items-center gap-1" style={{ color: VIZ.secondary }}>
                            {Icon && st && <Icon className="w-3.5 h-3.5" style={{ color: VIZ.status[st] }} />}
                            {o.status.charAt(0) + o.status.slice(1).toLowerCase()}
                          </span>
                        </td>
                        <td className="py-2 text-end font-semibold tabular-nums" style={{ color: VIZ.primary }}>{eur(num(o.amount))}</td>
                      </tr>
                    );
                  })}
                  {(data.recent_orders || []).length === 0 && (
                    <tr><td colSpan={6} className="py-8 text-center" style={{ color: VIZ.muted }}>No orders yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// Our float at VivaPe. Worth its own card because an empty supplier account
// does not fail loudly: create-transaction answers HTTP 200 with a generic
// "Insufficient Balance.", so without this the first symptom is customers
// with failed orders.
function SupplierBalanceCard() {
  const [data, setData] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setData(await api.getSupplierAccount(token, refresh));
  }, []);

  useEffect(() => {
    load().catch((err) => setError(err.message || "Couldn't reach VivaPe"));
  }, [load]);

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      await load(true);
    } catch (err: any) {
      setError(err.message || "Couldn't reach VivaPe");
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) {
    return (
      <div className="glass-panel rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800 flex items-center justify-between gap-3">
        <span className="flex items-center gap-2"><WifiOff className="w-4 h-4 shrink-0" /> Supplier balance unavailable — {error}</span>
        <button onClick={refresh} disabled={busy} className="font-bold underline shrink-0">Retry</button>
      </div>
    );
  }
  if (!data) return <div className="h-20 rounded-2xl bg-gray-100 animate-pulse" />;

  const low = data.low_balance;
  return (
    <div className={`glass-panel rounded-2xl border p-5 ${low ? "border-rose-300 bg-rose-50" : "border-gray-200 bg-white"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            VivaPe supplier balance
          </div>
          <div className={`text-2xl font-black font-mono mt-1 ${low ? "text-rose-600" : "text-slate-900"}`}>
            €{Number(data.balance).toFixed(2)}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {data.account}{data.supplier_id ? ` · ${data.supplier_id}` : ""}
            {data.wallets?.length
              ? ` · ${data.wallets.map((w: any) => `${w.type} €${Number(w.balance).toFixed(2)}`).join(" · ")}`
              : ""}
          </div>
        </div>
        <button
          onClick={refresh}
          disabled={busy}
          className="inline-flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-xl disabled:opacity-60 shrink-0"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} /> Check now
        </button>
      </div>
      {low && (
        <p className="mt-3 text-xs font-semibold text-rose-700">
          Below €{Number(data.warn_below).toFixed(2)} — top up the VivaPe account. When it empties, checkouts fail with a
          generic &ldquo;Insufficient Balance&rdquo; that looks like an ordinary decline to the customer.
        </p>
      )}
      {data.error && (
        <p className="mt-2 text-[11px] text-amber-700">Last check failed ({data.error}); showing the previous figure.</p>
      )}
    </div>
  );
}
