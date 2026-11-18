"use client";

import React, { useCallback, useEffect, useState } from "react";
import { LifeBuoy, Search } from "lucide-react";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/support/TicketThread";
import LiveTicketThread from "@/components/support/LiveTicketThread";
import { useSupportQueueSocket } from "@/components/support/useSupportQueueSocket";
import { formatDateTime } from "@/lib/datetime";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const FILTERS = [
  { value: "", label: "Needs work" },
  { value: "OPEN", label: "Needs a reply" },
  { value: "ANSWERED", label: "Waiting on customer" },
  { value: "RESOLVED", label: "Resolved" },
  { value: "CLOSED", label: "Closed" },
  { value: "ALL", label: "All" },
];

export default function SupportTab({ onCountChange }: { onCountChange?: (n: number) => void }) {
  const [data, setData] = useState<any | null>(null);
  const [status, setStatus] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await api.getSupportQueue(token, { status: status || undefined, q: query || undefined });
      setData(res);
      onCountChange?.(res.counts?.OPEN ?? 0);
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load the queue" });
    } finally {
      setLoading(false);
    }
  }, [status, query, onCountChange]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  // FR-C301: the queue list updates live - new/updated tickets appear
  // without a manual refresh. A ticket_updated event carries only a
  // lightweight summary (ws_manager's broadcast_to_queue payload), so this
  // re-runs the existing GET /support/queue (whatever filter/search is
  // active) rather than trying to patch one row from it.
  useSupportQueueSocket(true, load);

  // --- One ticket - FR-C302: the same live thread component the customer
  // widget uses, in for_staff mode (customer identity, assignment,
  // Take it/Resolve - what the old static view here already showed). ---
  if (openId) {
    return (
      <div className="glass-panel rounded-2xl border border-gray-200 h-[70vh]">
        <LiveTicketThread ticketId={openId} onBack={() => setOpenId(null)} forStaff onTicketChanged={load} />
      </div>
    );
  }

  // --- The queue ---
  const counts = data?.counts || {};
  return (
    <div className="space-y-4">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-1">
          <LifeBuoy className="w-4 h-4 text-admin-600" /> Support tickets
        </h3>
        <p className="text-xs text-slate-500 mb-4">
          Oldest waiting first — the one at the top has been waiting longest. Replying emails the customer.
        </p>

        {notice && (
          <p className={`text-xs font-medium mb-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
        )}

        <form
          onSubmit={(e) => { e.preventDefault(); setQuery(queryInput.trim()); }}
          className="flex flex-wrap items-end gap-2"
        >
          <div>
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Show</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
              className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
              {FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}{f.value && counts[f.value] !== undefined ? ` (${counts[f.value]})` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="text-[11px] text-slate-600 font-semibold block mb-1">Search</label>
            <div className="flex items-center gap-2 bg-white border border-gray-300 rounded-lg px-3">
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <input value={queryInput} onChange={(e) => setQueryInput(e.target.value)}
                placeholder="Reference, subject, customer"
                className="flex-1 py-2 text-xs text-slate-900 bg-transparent outline-none" />
            </div>
          </div>
          <button type="submit" className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold px-4 py-2 rounded-lg">
            Apply
          </button>
        </form>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        {loading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-14 rounded-xl bg-gray-100 animate-pulse" />)}</div>
        ) : !data?.tickets?.length ? (
          <div className="py-10 text-center text-xs text-slate-500">
            Nothing here — no tickets match this view.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Ticket</th>
                  <th className="py-2 pe-3 text-start">Customer</th>
                  <th className="py-2 pe-3 text-start">Topic</th>
                  <th className="py-2 pe-3 text-start">Status</th>
                  <th className="py-2 text-end">Last message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.tickets.map((t: any) => (
                  <tr key={t.id} onClick={() => setOpenId(t.id)} className="cursor-pointer hover:bg-gray-50">
                    <td className="py-2.5 pe-3">
                      <div className="font-semibold text-slate-900">{t.subject}</div>
                      <div className="text-[10px] text-slate-400 font-mono">{t.reference}</div>
                    </td>
                    <td className="py-2.5 pe-3 text-slate-700">
                      {t.customer?.username}
                      <div className="text-[10px] text-slate-400">{t.customer?.email}</div>
                    </td>
                    <td className="py-2.5 pe-3 text-slate-500">{t.category}</td>
                    <td className="py-2.5 pe-3"><StatusBadge status={t.status} staff /></td>
                    <td className="py-2.5 text-end text-slate-500 whitespace-nowrap">
                      {formatDateTime(t.last_message_at)}
                    </td>
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
