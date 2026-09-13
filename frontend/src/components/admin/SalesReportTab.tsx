"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { api, SalesReportParams } from "@/lib/api";

const PAGE_SIZE = 50;

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

// Report amounts are accounting figures in the base currency - shown as
// exact euros rather than converted to the admin's display currency.
const eur = (value?: string | null) => (value === null || value === undefined ? "—" : `€${Number(value).toFixed(2)}`);

function isoDay(d: Date) {
  return d.toISOString().slice(0, 10);
}

const STATUS_OPTIONS = [
  { value: "COMPLETED", label: "Completed (delivered)" },
  { value: "ALL", label: "All orders" },
  { value: "FAILED", label: "Failed (refunded)" },
  { value: "PROCESSING", label: "Setting up" },
];

const CHANNEL_LABELS: Record<string, string> = { web: "Web", api: "Partner API", admin: "Admin" };

function Total({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="glass-panel rounded-2xl p-4 border border-gray-200">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-xl font-black font-mono mt-1 ${tone}`}>{value}</div>
    </div>
  );
}

export default function SalesReportTab() {
  const now = new Date();
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))));
  const [dateTo, setDateTo] = useState(isoDay(now));
  const [status, setStatus] = useState("COMPLETED");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [report, setReport] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const params = useCallback(
    (): SalesReportParams => ({ date_from: dateFrom || undefined, date_to: dateTo || undefined, status, q: query || undefined }),
    [dateFrom, dateTo, status, query]
  );

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getSalesReport(token, { ...params(), limit: PAGE_SIZE, offset }));
    } catch (err: any) {
      setError(err.message || "Couldn't load the report");
    } finally {
      setLoading(false);
    }
  }, [params, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const exportCsv = async () => {
    const token = getToken();
    if (!token) return;
    setExporting(true);
    try {
      const blob = await api.downloadSalesReportCsv(token, params());
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `triptel-sales-${dateFrom || "start"}-to-${dateTo || "now"}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const totals = report?.totals;
  const orderCount = totals?.orders ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(orderCount / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900">Sales &amp; profit report</h3>
        <p className="text-xs text-slate-500 mt-1 mb-4">
          Every transaction&apos;s base cost (VivaPe), selling price, profit, merchant commission and Triptel&apos;s net profit.
          Cost is recorded when the order is placed, so later price changes don&apos;t rewrite past profit.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setQuery(queryInput.trim());
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => { setOffset(0); setDateFrom(e.target.value); }} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => { setOffset(0); setDateTo(e.target.value); }} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Status</label>
            <select value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }} className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
              {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="flex-1 min-w-[220px]">
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Search</label>
            <div className="flex items-center gap-2 bg-white border border-gray-300 rounded-lg px-3">
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <input value={queryInput} onChange={(e) => setQueryInput(e.target.value)} placeholder="Order no, buyer, product" className="flex-1 py-2 text-xs text-slate-900 bg-transparent outline-none" />
            </div>
          </div>
          <button type="submit" className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold px-4 py-2 rounded-lg">Apply</button>
          <button type="button" onClick={exportCsv} disabled={exporting} className="bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2 rounded-lg flex items-center gap-1.5 disabled:opacity-60">
            <Download className="w-3.5 h-3.5" /> {exporting ? "Exporting…" : "Export CSV"}
          </button>
        </form>
        {error && <p className="text-xs text-rose-600 mt-3">{error}</p>}
      </div>

      {totals && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <Total label="Orders" value={String(totals.orders)} />
          <Total label="Selling price" value={eur(totals.selling_price)} />
          <Total label="Base cost" value={eur(totals.cost)} tone="text-slate-600" />
          <Total label={`Profit${totals.profit_pct ? ` (${Number(totals.profit_pct).toFixed(1)}%)` : ""}`} value={eur(totals.profit)} tone="text-emerald-600" />
          <Total label="Merchant commission" value={eur(totals.merchant_commission)} tone="text-merchant-600" />
          <Total label="Net profit" value={eur(totals.net_profit)} tone="text-emerald-700" />
        </div>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <div className="overflow-x-auto frozen-col-table">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200">
              <tr>
                <th className="py-2 pe-3">Order</th>
                <th className="py-2 pe-3">Date</th>
                <th className="py-2 pe-3">Buyer</th>
                <th className="py-2 pe-3">Product</th>
                <th className="py-2 pe-3 text-end">Base cost</th>
                <th className="py-2 pe-3 text-end">Selling price</th>
                <th className="py-2 pe-3 text-end">Profit</th>
                <th className="py-2 pe-3 text-end">Commission</th>
                <th className="py-2 text-end">Net profit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && !report && <tr><td colSpan={9} className="py-8 text-center text-slate-400">Loading…</td></tr>}
              {report?.rows.map((r: any) => (
                <tr key={r.order_id}>
                  <td className="py-2.5 pe-3">
                    <div className="font-mono text-admin-600">{r.order_no}</div>
                    <div className="text-[10px] text-slate-400">{CHANNEL_LABELS[r.channel] || r.channel} · {r.status}</div>
                  </td>
                  <td className="py-2.5 pe-3 text-slate-500 whitespace-nowrap">{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
                  <td className="py-2.5 pe-3 text-slate-700">
                    <div>{r.buyer.username}</div>
                    <div className="text-[10px] text-slate-400">{r.buyer.email}</div>
                  </td>
                  <td className="py-2.5 pe-3 text-slate-700">{r.product} <span className="text-slate-400">({r.country_iso2})</span></td>
                  <td className="py-2.5 pe-3 text-end font-mono text-slate-600">{eur(r.cost)}</td>
                  <td className="py-2.5 pe-3 text-end font-mono font-bold text-slate-900">{eur(r.selling_price)}</td>
                  <td className="py-2.5 pe-3 text-end font-mono text-emerald-600">
                    {eur(r.profit)}
                    {r.profit_pct && <div className="text-[10px] text-slate-400">{Number(r.profit_pct).toFixed(1)}%</div>}
                  </td>
                  <td className="py-2.5 pe-3 text-end font-mono text-merchant-600">{Number(r.merchant_commission) > 0 ? eur(r.merchant_commission) : "—"}</td>
                  <td className="py-2.5 text-end font-mono font-bold text-emerald-700">{eur(r.net_profit)}</td>
                </tr>
              ))}
              {report && report.rows.length === 0 && (
                <tr><td colSpan={9} className="py-10 text-center text-slate-500">No orders match these filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {orderCount > PAGE_SIZE && (
          <div className="flex items-center justify-between mt-4 text-xs text-slate-500">
            <span>{orderCount} orders · page {page} of {pages}</span>
            <div className="flex gap-2">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="p-1.5 rounded-lg border border-gray-200 bg-white disabled:opacity-40" aria-label="Previous page">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button disabled={page >= pages} onClick={() => setOffset(offset + PAGE_SIZE)} className="p-1.5 rounded-lg border border-gray-200 bg-white disabled:opacity-40" aria-label="Next page">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
