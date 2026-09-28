"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { api, SalesReportParams } from "@/lib/api";
import { formatDateTime, formatDayLabel } from "@/lib/datetime";

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

type View = "transactions" | "daily" | "bundle" | "country" | "discount";
const VIEWS: { id: View; label: string }[] = [
  { id: "transactions", label: "Transactions" },
  { id: "daily", label: "Day by day" },
  { id: "bundle", label: "By bundle" },
  { id: "country", label: "By country" },
  { id: "discount", label: "By discount code" },
];

const selectCls = "bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";

function Total({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="glass-panel rounded-2xl p-4 border border-gray-200">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-xl font-black font-mono mt-1 ${tone}`}>{value}</div>
    </div>
  );
}

function SortHeader({ label, column, sort, direction, onSort, align = "end" }: {
  label: string; column: string; sort: string; direction: "asc" | "desc"; onSort: (column: string) => void; align?: "start" | "end";
}) {
  const active = sort === column;
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className={`py-2 pe-3 text-${align}`}>
      <button type="button" onClick={() => onSort(column)} className={`inline-flex items-center gap-1 hover:text-slate-900 ${active ? "text-slate-900" : ""}`}>
        {label} <Icon className={`w-3 h-3 ${active ? "" : "opacity-40"}`} />
      </button>
    </th>
  );
}

// Grouped view (day / bundle / country) - sorted client-side, the groups are small.
function GroupTable({ rows, labelKey, labelTitle, renderLabel, showDiscount = false }: { rows: any[]; labelKey: string; labelTitle: string; renderLabel?: (r: any) => React.ReactNode; showDiscount?: boolean }) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: labelKey === "day" ? "day" : "selling_price", dir: "desc" });
  const sorted = [...rows].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key];
    const cmp = typeof av === "string" && isNaN(Number(av)) ? String(av).localeCompare(String(bv)) : Number(av ?? -Infinity) - Number(bv ?? -Infinity);
    return sort.dir === "asc" ? cmp : -cmp;
  });
  const onSort = (key: string) => setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));
  const max = Math.max(1, ...rows.map((r) => Number(r.selling_price)));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-start text-xs">
        <thead className="text-slate-500 border-b border-gray-200">
          <tr>
            <SortHeader label={labelTitle} column={labelKey} sort={sort.key} direction={sort.dir} onSort={onSort} align="start" />
            <SortHeader label="Orders" column="orders" sort={sort.key} direction={sort.dir} onSort={onSort} />
            {showDiscount && <SortHeader label="Discount" column="discount" sort={sort.key} direction={sort.dir} onSort={onSort} />}
            <SortHeader label="Selling price" column="selling_price" sort={sort.key} direction={sort.dir} onSort={onSort} />
            <SortHeader label="Base cost" column="cost" sort={sort.key} direction={sort.dir} onSort={onSort} />
            <SortHeader label="Profit" column="profit" sort={sort.key} direction={sort.dir} onSort={onSort} />
            <SortHeader label="Commission" column="merchant_commission" sort={sort.key} direction={sort.dir} onSort={onSort} />
            <SortHeader label="Net profit" column="net_profit" sort={sort.key} direction={sort.dir} onSort={onSort} />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map((r, i) => (
            <tr key={i}>
              <td className="py-2.5 pe-3 text-slate-700 min-w-[160px]">
                <div>{renderLabel ? renderLabel(r) : r[labelKey]}</div>
                <div className="h-1 mt-1 rounded-full bg-gray-100 overflow-hidden">
                  <div className="h-full bg-admin-400" style={{ width: `${(Number(r.selling_price) / max) * 100}%` }} />
                </div>
              </td>
              <td className="py-2.5 pe-3 text-end font-mono">{r.orders}</td>
              {showDiscount && <td className="py-2.5 pe-3 text-end font-mono text-amber-600">{eur(r.discount || 0)}</td>}
              <td className="py-2.5 pe-3 text-end font-mono font-bold text-slate-900">{eur(r.selling_price)}</td>
              <td className="py-2.5 pe-3 text-end font-mono text-slate-600">{eur(r.cost)}</td>
              <td className="py-2.5 pe-3 text-end font-mono text-emerald-600">
                {eur(r.profit)}
                {r.profit_pct && <div className="text-[10px] text-slate-400">{Number(r.profit_pct).toFixed(1)}%</div>}
              </td>
              <td className="py-2.5 pe-3 text-end font-mono text-merchant-600">{Number(r.merchant_commission) > 0 ? eur(r.merchant_commission) : "—"}</td>
              <td className="py-2.5 text-end font-mono font-bold text-emerald-700">{eur(r.net_profit)}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={showDiscount ? 8 : 7} className="py-10 text-center text-slate-500">No orders match these filters.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function SalesReportTab() {
  const now = new Date();
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))));
  const [dateTo, setDateTo] = useState(isoDay(now));
  const [status, setStatus] = useState("COMPLETED");
  const [plan, setPlan] = useState("");
  const [validity, setValidity] = useState("");
  const [channel, setChannel] = useState("");
  const [country, setCountry] = useState("");
  const [discountCode, setDiscountCode] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [view, setView] = useState<View>("transactions");
  const [offset, setOffset] = useState(0);
  const [report, setReport] = useState<any | null>(null);
  const [breakdown, setBreakdown] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const params = useCallback(
    (): SalesReportParams => ({
      date_from: dateFrom || undefined, date_to: dateTo || undefined, status, q: query || undefined,
      plan: plan || undefined, validity: validity || undefined, channel: channel || undefined, country: country || undefined,
      discount_code: discountCode || undefined,
    }),
    [dateFrom, dateTo, status, query, plan, validity, channel, country, discountCode]
  );

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [r, b] = await Promise.all([
        api.getSalesReport(token, { ...params(), sort, direction, limit: PAGE_SIZE, offset }),
        api.getSalesBreakdown(token, params()),
      ]);
      setReport(r);
      setBreakdown(b);
    } catch (err: any) {
      setError(err.message || "Couldn't load the report");
    } finally {
      setLoading(false);
    }
  }, [params, sort, direction, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Any filter change goes back to the first page.
  const withReset = <T,>(setter: (v: T) => void) => (v: T) => {
    setOffset(0);
    setter(v);
  };

  const onSort = (column: string) => {
    setOffset(0);
    if (sort === column) setDirection(direction === "desc" ? "asc" : "desc");
    else {
      setSort(column);
      setDirection(column === "product" || column === "country" ? "asc" : "desc");
    }
  };

  const exportCsv = async () => {
    const token = getToken();
    if (!token) return;
    setExporting(true);
    try {
      const blob = await api.downloadSalesReportCsv(token, { ...params(), sort, direction });
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
  const sortProps = { sort, direction, onSort };

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
            <input type="date" value={dateFrom} onChange={(e) => withReset(setDateFrom)(e.target.value)} className={selectCls} />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => withReset(setDateTo)(e.target.value)} className={selectCls} />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Status</label>
            <select value={status} onChange={(e) => withReset(setStatus)(e.target.value)} className={selectCls}>
              {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Bundle type</label>
            <select value={plan} onChange={(e) => withReset(setPlan)(e.target.value)} className={selectCls}>
              <option value="">All bundles</option>
              <option value="data">Fixed data (GB)</option>
              <option value="unlimited">Unlimited</option>
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Validity</label>
            <select value={validity} onChange={(e) => withReset(setValidity)(e.target.value)} className={selectCls}>
              <option value="">Any</option>
              {(breakdown?.validity_options || []).map((d: number) => <option key={d} value={String(d)}>{d} days</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Channel</label>
            <select value={channel} onChange={(e) => withReset(setChannel)(e.target.value)} className={selectCls}>
              <option value="">All channels</option>
              <option value="web">Web</option>
              <option value="api">Partner API</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Discount code</label>
            <select value={discountCode} onChange={(e) => withReset(setDiscountCode)(e.target.value)} className={selectCls}>
              <option value="">Any (with or without)</option>
              <option value="ANY">Any discounted sale</option>
              <option value="NONE">Full price only</option>
              {(breakdown?.discount_code_options || []).map((c: string) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Country</label>
            <input value={country} maxLength={10} placeholder="ISO e.g. TH" onChange={(e) => withReset(setCountry)(e.target.value.toUpperCase())} className={`${selectCls} w-24 uppercase`} />
          </div>
          <div className="flex-1 min-w-[200px]">
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
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
          <Total label="Orders" value={String(totals.orders)} />
          <Total label="Selling price" value={eur(totals.selling_price)} />
          <Total
            label={`Discounts${totals.discounted_orders ? ` (${totals.discounted_orders} order${totals.discounted_orders === 1 ? "" : "s"})` : ""}`}
            value={eur(totals.discount || 0)}
            tone="text-amber-600"
          />
          <Total label="Base cost" value={eur(totals.cost)} tone="text-slate-600" />
          <Total label={`Profit${totals.profit_pct ? ` (${Number(totals.profit_pct).toFixed(1)}%)` : ""}`} value={eur(totals.profit)} tone="text-emerald-600" />
          <Total label="Merchant commission" value={eur(totals.merchant_commission)} tone="text-merchant-600" />
          <Total label="Net profit" value={eur(totals.net_profit)} tone="text-emerald-700" />
        </div>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <div className="flex flex-wrap gap-1 mb-4 border-b border-gray-200">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id)}
              className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${view === v.id ? "border-admin-600 text-admin-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
            >
              {v.label}
            </button>
          ))}
          {loading && <span className="ms-auto self-center text-[11px] text-slate-400">Loading…</span>}
        </div>

        {view === "daily" && breakdown && (
          <GroupTable
            rows={breakdown.daily}
            labelKey="day"
            labelTitle="Day (UTC)"
            renderLabel={(r) => formatDayLabel(r.day, { weekday: "short", day: "numeric", month: "short", year: "numeric" })}
          />
        )}
        {view === "bundle" && breakdown && <GroupTable rows={breakdown.by_bundle} labelKey="plan" labelTitle="Bundle" />}
        {view === "country" && breakdown && (
          <GroupTable rows={breakdown.by_country} labelKey="country" labelTitle="Country" renderLabel={(r) => <>{r.country} <span className="text-slate-400">({r.country_iso2})</span></>} />
        )}
        {view === "discount" && breakdown && (
          <>
            <p className="text-[11px] text-slate-500 mb-3">
              Only discounted orders appear here. &ldquo;Selling price&rdquo; is what was actually received, so profit is already net of the discount.
            </p>
            <GroupTable
              rows={breakdown.by_discount_code}
              labelKey="code"
              labelTitle="Code"
              renderLabel={(r) => <span className="font-mono font-bold">{r.code}</span>}
              showDiscount
            />
          </>
        )}

        {view === "transactions" && (
          <>
            <div className="overflow-x-auto frozen-col-table">
              <table className="w-full text-start text-xs">
                <thead className="text-slate-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pe-3 text-start">Order</th>
                    <SortHeader label="Date" column="date" align="start" {...sortProps} />
                    <th className="py-2 pe-3 text-start">Buyer</th>
                    <SortHeader label="Product" column="product" align="start" {...sortProps} />
                    <SortHeader label="Base cost" column="cost" {...sortProps} />
                    <SortHeader label="Discount" column="discount" {...sortProps} />
                    <SortHeader label="Selling price" column="price" {...sortProps} />
                    <SortHeader label="Profit" column="profit" {...sortProps} />
                    <SortHeader label="Commission" column="commission" {...sortProps} />
                    <th className="py-2 text-end">Net profit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {loading && !report && <tr><td colSpan={10} className="py-8 text-center text-slate-400">Loading…</td></tr>}
                  {report?.rows.map((r: any) => (
                    <tr key={r.order_id}>
                      <td className="py-2.5 pe-3">
                        <div className="font-mono text-admin-600">{r.order_no}</div>
                        <div className="text-[10px] text-slate-400">{CHANNEL_LABELS[r.channel] || r.channel} · {r.status}</div>
                      </td>
                      <td className="py-2.5 pe-3 text-slate-500 whitespace-nowrap">{formatDateTime(r.created_at)}</td>
                      <td className="py-2.5 pe-3 text-slate-700">
                        <div>{r.buyer.username}</div>
                        <div className="text-[10px] text-slate-400">{r.buyer.email}</div>
                      </td>
                      <td className="py-2.5 pe-3 text-slate-700">
                        {r.product} <span className="text-slate-400">({r.country_iso2})</span>
                        {r.plan && <div className="text-[10px] text-slate-400">{r.plan}</div>}
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono text-slate-600">{eur(r.cost)}</td>
                      <td className="py-2.5 pe-3 text-end font-mono text-amber-600">
                        {Number(r.discount) > 0 ? (
                          <>
                            {eur(r.discount)}
                            <div className="text-[10px] text-slate-400 font-sans">{r.discount_code}</div>
                          </>
                        ) : "—"}
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono font-bold text-slate-900">
                        {eur(r.selling_price)}
                        {Number(r.discount) > 0 && (
                          <div className="text-[10px] text-slate-400 line-through">{eur(r.list_price)}</div>
                        )}
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono text-emerald-600">
                        {eur(r.profit)}
                        {r.profit_pct && <div className="text-[10px] text-slate-400">{Number(r.profit_pct).toFixed(1)}%</div>}
                      </td>
                      <td className="py-2.5 pe-3 text-end font-mono text-merchant-600">{Number(r.merchant_commission) > 0 ? eur(r.merchant_commission) : "—"}</td>
                      <td className="py-2.5 text-end font-mono font-bold text-emerald-700">{eur(r.net_profit)}</td>
                    </tr>
                  ))}
                  {report && report.rows.length === 0 && (
                    <tr><td colSpan={10} className="py-10 text-center text-slate-500">No orders match these filters.</td></tr>
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
          </>
        )}
      </div>
    </div>
  );
}
