"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search, Smartphone, X } from "lucide-react";
import { api } from "@/lib/api";
import { CopyButton, Panel, SourceBadge, StatusBadge, dataLabel, formatDateTime, getToken } from "./shared";
import EsimQr from "@/components/EsimQr";

const PAGE_SIZE = 20;

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "COMPLETED", label: "Completed" },
  { value: "PROCESSING", label: "Setting up" },
  { value: "FAILED", label: "Failed" },
];

const SOURCE_FILTERS = [
  { value: "all", label: "All sources" },
  { value: "web", label: "Web (bought here)" },
  { value: "api", label: "Partner API" },
];

export default function OrdersTab({ formatPrice }: { formatPrice: (amountUsd: number) => string }) {
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("all");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ orders: any[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setError(null);
    try {
      setData(await api.getMerchantOrders(token, { status: status || undefined, source, q: query || undefined, limit: PAGE_SIZE, offset }));
    } catch (err: any) {
      setError(err.message || "Couldn't load orders");
    }
  }, [status, source, query, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Panel title="Orders" description="Every eSIM you've sold — bought here for a customer, or placed through the Partner API.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setQuery(queryInput.trim());
        }}
        className="flex flex-col md:flex-row gap-2 mb-4"
      >
        <div className="flex-1 flex items-center gap-2 bg-white border border-gray-300 rounded-xl px-3">
          <Search className="w-3.5 h-3.5 text-slate-400" />
          <input
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            placeholder="Order no, your reference, ICCID, customer email, plan"
            className="flex-1 py-2 text-xs text-slate-900 bg-transparent outline-none"
          />
        </div>
        <select value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }} className="bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900">
          {STATUS_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
        <select value={source} onChange={(e) => { setOffset(0); setSource(e.target.value); }} className="bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900">
          {SOURCE_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
        <button type="submit" className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold">Search</button>
      </form>

      {error && <p className="text-xs text-rose-600 mb-3">{error}</p>}

      <div className="overflow-x-auto frozen-col-table">
        <table className="w-full text-start text-xs">
          <thead className="text-slate-500 border-b border-gray-200">
            <tr>
              <th className="py-2 pe-3">Order</th>
              <th className="py-2 pe-3">Customer</th>
              <th className="py-2 pe-3">Plan</th>
              <th className="py-2 pe-3">Amount</th>
              <th className="py-2 pe-3">Commission</th>
              <th className="py-2 pe-3">Status</th>
              <th className="py-2 pe-3">Date</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {!data && (
              <tr><td colSpan={8} className="py-8 text-center text-slate-400">Loading…</td></tr>
            )}
            {data?.orders.map((o) => (
              <tr key={o.order_id} className="hover:bg-gray-50/60">
                <td className="py-2.5 pe-3">
                  <div className="font-mono text-brand-600">{o.order_no}</div>
                  <div className="mt-0.5"><SourceBadge source={o.source} /></div>
                </td>
                <td className="py-2.5 pe-3 text-slate-700">
                  {o.source === "api" ? (
                    <span className="font-mono">{o.customer_reference || "—"}</span>
                  ) : (
                    <>
                      <div>{o.customer?.username}</div>
                      <div className="text-slate-400">{o.customer?.email}</div>
                    </>
                  )}
                </td>
                <td className="py-2.5 pe-3 text-slate-700">
                  <div>{o.product.title}</div>
                  <div className="text-slate-400">{o.product.country_iso2} · {dataLabel(o.product)} · {o.product.validity_days} days</div>
                </td>
                <td className="py-2.5 pe-3 font-bold text-slate-900">{formatPrice(Number(o.amount))}</td>
                <td className="py-2.5 pe-3 font-bold text-merchant-600">{Number(o.commission_earned) > 0 ? `+${formatPrice(Number(o.commission_earned))}` : "—"}</td>
                <td className="py-2.5 pe-3"><StatusBadge status={o.status} /></td>
                <td className="py-2.5 pe-3 text-slate-500 whitespace-nowrap">{formatDateTime(o.created_at)}</td>
                <td className="py-2.5">
                  <button onClick={() => setSelectedId(o.order_id)} className="px-3 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-slate-700 font-semibold">View</button>
                </td>
              </tr>
            ))}
            {data && data.orders.length === 0 && (
              <tr><td colSpan={8} className="py-10 text-center text-slate-500">No orders match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="flex items-center justify-between mt-4 text-xs text-slate-500">
          <span>{total} order{total === 1 ? "" : "s"} · page {page} of {pages}</span>
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

      {selectedId && <OrderDetail orderId={selectedId} formatPrice={formatPrice} onClose={() => setSelectedId(null)} />}
    </Panel>
  );
}

function DetailRow({ label, value, copy }: { label: string; value?: string | null; copy?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-slate-900 break-all text-end">{value || "—"}</span>
        {copy && value && <CopyButton value={value} />}
      </span>
    </div>
  );
}

function OrderDetail({ orderId, formatPrice, onClose }: { orderId: string; formatPrice: (n: number) => string; onClose: () => void }) {
  const [order, setOrder] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api.getMerchantOrder(token, orderId).then(setOrder).catch((err: any) => setError(err.message || "Couldn't load this order"));
  }, [orderId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="glass-panel bg-white rounded-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 border border-gray-200 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Order {order?.order_no || ""}</h3>
            {order && <div className="flex items-center gap-2 mt-1"><SourceBadge source={order.source} /><StatusBadge status={order.status} /></div>}
          </div>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700" aria-label="Close"><X className="w-5 h-5" /></button>
        </div>

        {error && <p className="text-xs text-rose-600">{error}</p>}
        {!order && !error && <p className="text-xs text-slate-400 py-8 text-center">Loading…</p>}

        {order && (
          <div className="space-y-5 text-xs">
            {order.status === "COMPLETED" && order.qr_code_data && (
              <div className="flex flex-col items-center">
                <div className="bg-white p-3 rounded-xl border border-gray-200">
                  <EsimQr value={order.qr_code_data} size={170} />
                </div>
                {(order.install_links?.ios || order.install_links?.android) && (
                  <div className="flex gap-2 w-full mt-3">
                    {order.install_links.ios && (
                      <a href={order.install_links.ios} target="_blank" rel="noreferrer" className="flex-1 flex items-center justify-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white font-bold py-2 rounded-lg">
                        <Smartphone className="w-3.5 h-3.5" /> iPhone install link
                      </a>
                    )}
                    {order.install_links.android && (
                      <a href={order.install_links.android} target="_blank" rel="noreferrer" className="flex-1 flex items-center justify-center gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-bold py-2 rounded-lg">
                        <Smartphone className="w-3.5 h-3.5" /> Android install link
                      </a>
                    )}
                  </div>
                )}
              </div>
            )}
            {order.status === "FAILED" && (
              <p className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700">
                The eSIM could not be issued. {formatPrice(Number(order.amount))} was refunded to your wallet.
              </p>
            )}

            <div className="divide-y divide-gray-100">
              <DetailRow label="Plan" value={`${order.product.title} (${order.product.country_iso2})`} />
              <DetailRow label="Data / validity" value={`${dataLabel(order.product)} · ${order.product.validity_days} days`} />
              <DetailRow label="Amount" value={formatPrice(Number(order.amount))} />
              <DetailRow label="Commission" value={formatPrice(Number(order.commission_earned))} />
              {order.source === "api" ? (
                <DetailRow label="Your reference" value={order.customer_reference} copy />
              ) : (
                <DetailRow label="Customer" value={order.customer?.email} copy />
              )}
              <DetailRow label="ICCID" value={order.iccid} copy />
              <DetailRow label="Activation code" value={order.lpa_string} copy />
              <DetailRow label="SM-DP+ address" value={order.smdp_address} copy />
              <DetailRow label="Matching ID" value={order.matching_id} copy />
              <DetailRow label="Order ID" value={order.order_id} copy />
              <DetailRow label="Created" value={formatDateTime(order.created_at)} />
            </div>

            {/* Live carrier status, so a partner can answer their own
                customer's "it isn't working" without going through us. */}
            {order.live_status && (
              <div>
                <h4 className="font-bold text-slate-900 mb-2">Live status</h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">SIM status</div>
                    <div className={`font-bold ${order.live_status.status.is_activated ? "text-emerald-600" : "text-slate-700"}`}>
                      {order.live_status.status.label}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Data used</div>
                    <div className="font-bold text-slate-900">{order.live_status.usage.formatted || "0 MB"}</div>
                    {!order.live_status.usage.is_unlimited && order.live_status.usage.remaining_formatted && (
                      <div className="text-[10px] text-slate-500">{order.live_status.usage.remaining_formatted} left</div>
                    )}
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Handset</div>
                    <div className="text-slate-700">
                      {order.live_status.status.is_installed
                        ? (order.live_status.status.device_model || "Installed")
                        : "Not installed"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Expires</div>
                    <div className="text-slate-700">
                      {order.live_status.validity.expires_at
                        ? formatDateTime(order.live_status.validity.expires_at)
                        : `On install +${order.live_status.validity.days}d`}
                    </div>
                  </div>
                </div>
                {order.live_status.telemetry.error && (
                  <p className="mt-2 text-[11px] text-amber-700">
                    Carrier unreachable — showing the last known figures.
                  </p>
                )}
              </div>
            )}

            {order.source === "api" && (
              <div>
                <h4 className="font-bold text-slate-900 mb-2">Webhook deliveries</h4>
                {order.webhook_deliveries.length === 0 ? (
                  <p className="text-slate-500">None — no webhook was configured when this order settled, or it is still setting up.</p>
                ) : (
                  <ul className="divide-y divide-gray-100">
                    {order.webhook_deliveries.map((d: any, i: number) => (
                      <li key={i} className="py-1.5 flex justify-between">
                        <span className="text-slate-500">Attempt {d.attempt} · {formatDateTime(d.created_at)}</span>
                        <span className={`font-bold ${d.success ? "text-emerald-600" : "text-rose-600"}`}>
                          {d.success ? "Delivered" : "Failed"}{d.response_status ? ` (HTTP ${d.response_status})` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
