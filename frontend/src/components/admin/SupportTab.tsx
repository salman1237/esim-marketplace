"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, LifeBuoy, Search, UserCheck } from "lucide-react";
import { api } from "@/lib/api";
import { ReplyBox, StatusBadge, Thread } from "@/components/support/TicketThread";
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
  const [open, setOpen] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
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
    load();
  }, [load]);

  const openTicket = async (id: string) => {
    const token = getToken();
    if (!token) return;
    try {
      setOpen(await api.getTicket(token, id));
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't open that ticket" });
    }
  };

  const reply = async (body: string, files: File[]) => {
    const token = getToken();
    if (!token || !open) return;
    setSending(true);
    setNotice(null);
    try {
      const form = new FormData();
      form.append("body", body);
      files.forEach((f) => form.append("files", f));
      setOpen(await api.replyToTicket(token, open.id, form));
      await load();
      setNotice({ kind: "ok", text: "Sent — the customer has been emailed." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't send that" });
    } finally {
      setSending(false);
    }
  };

  const act = async (fn: (token: string, id: string) => Promise<any>, message: string) => {
    const token = getToken();
    if (!token || !open) return;
    setNotice(null);
    try {
      await fn(token, open.id);
      await openTicket(open.id);
      await load();
      setNotice({ kind: "ok", text: message });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't do that" });
    }
  };

  // --- One ticket ---
  if (open) {
    return (
      <div className="space-y-4">
        <button onClick={() => setOpen(null)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to the queue
        </button>

        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
            <div className="min-w-0">
              <h3 className="text-base font-bold text-slate-900">{open.subject}</h3>
              <p className="text-xs text-slate-500 mt-0.5 font-mono">{open.reference}</p>
              <p className="text-xs text-slate-600 mt-1">
                {open.customer?.username} · {open.customer?.email}
                {open.assigned_to ? <> · assigned to <strong>{open.assigned_to}</strong></> : null}
              </p>
              {open.order_id && (
                <p className="text-[11px] text-slate-400 mt-0.5 font-mono">Order {open.order_id}</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              <StatusBadge status={open.status} staff />
              <div className="flex gap-2">
                {!open.assigned_to && (
                  <button onClick={() => act(api.assignTicket, "Assigned to you.")}
                    className="inline-flex items-center gap-1 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-[11px] font-bold px-2.5 py-1.5 rounded-lg">
                    <UserCheck className="w-3 h-3" /> Take it
                  </button>
                )}
                {open.status !== "RESOLVED" && open.status !== "CLOSED" && (
                  <button onClick={() => act(api.resolveTicket, "Marked resolved — the customer has been emailed.")}
                    className="inline-flex items-center gap-1 bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-bold px-2.5 py-1.5 rounded-lg">
                    <CheckCircle2 className="w-3 h-3" /> Resolve
                  </button>
                )}
              </div>
            </div>
          </div>

          {notice && (
            <p className={`text-xs font-medium mb-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
          )}

          <Thread messages={open.messages || []} />
        </div>

        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <ReplyBox
            onSend={reply}
            sending={sending}
            disabled={open.status === "CLOSED"}
            placeholder="Reply to the customer…"
          />
          <p className="mt-2 text-[11px] text-slate-400">
            The customer sees this as &ldquo;Support&rdquo; — your username isn&apos;t shown to them.
          </p>
        </div>
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
                  <tr key={t.id} onClick={() => openTicket(t.id)} className="cursor-pointer hover:bg-gray-50">
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
