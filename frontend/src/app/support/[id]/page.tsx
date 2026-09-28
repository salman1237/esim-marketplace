"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import { ReplyBox, StatusBadge, Thread } from "@/components/support/TicketThread";

export default function TicketPage() {
  const params = useParams();
  const id = String(params?.id || "");
  const [ticket, setTicket] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = `/auth/login?next=/support/${id}`;
      return;
    }
    setTicket(await api.getTicket(token, id));
  }, [id]);

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || "Couldn't load this ticket"))
      .finally(() => setLoading(false));
  }, [load]);

  const send = async (body: string, files: File[]) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("body", body);
      files.forEach((f) => form.append("files", f));
      setTicket(await api.replyToTicket(token, id, form));
    } catch (err: any) {
      setError(err.message || "Couldn't send that");
    } finally {
      setSending(false);
    }
  };

  const close = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    try {
      await api.closeTicket(token, id);
      await load();
    } catch (err: any) {
      setError(err.message || "Couldn't close it");
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-4">
        <div className="h-8 w-56 rounded bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (!ticket) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-16 text-center">
        <p className="text-sm text-slate-600">{error || "That ticket could not be found."}</p>
        <Link href="/support" className="mt-4 inline-block text-xs font-bold text-brand-600 underline">Back to support</Link>
      </div>
    );
  }

  const closed = ticket.status === "CLOSED";

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <Link href="/support" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900 mb-4">
        <ArrowLeft className="w-3.5 h-3.5" /> All tickets
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold text-slate-900">{ticket.subject}</h1>
          <p className="text-xs text-slate-500 mt-1 font-mono">
            {ticket.reference} · opened {new Date(ticket.created_at).toLocaleDateString()}
          </p>
        </div>
        <StatusBadge status={ticket.status} />
      </div>

      {ticket.status === "RESOLVED" && (
        <div className="mb-6 p-4 rounded-xl border border-emerald-200 bg-emerald-50 text-xs text-emerald-800 flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
          We&apos;ve marked this resolved. If it isn&apos;t sorted, just reply below and it reopens straight away.
        </div>
      )}

      {error && <p className="mb-4 text-xs text-rose-600">{error}</p>}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-4">
        <Thread messages={ticket.messages || []} />
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <ReplyBox onSend={send} sending={sending} disabled={closed} />
        {!closed && (
          <button onClick={close} className="mt-3 text-[11px] font-semibold text-slate-500 hover:text-slate-800">
            Close this ticket
          </button>
        )}
      </div>
    </div>
  );
}
