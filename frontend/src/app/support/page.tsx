"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { LifeBuoy, Plus, Paperclip, X } from "lucide-react";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/support/TicketThread";
import { formatDate } from "@/lib/datetime";

export default function SupportPage() {
  const [tickets, setTickets] = useState<any[]>([]);
  const [categories, setCategories] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [composing, setComposing] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("OTHER");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const load = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login?next=/support";
      return;
    }
    const [mine, cats] = await Promise.all([
      api.getMyTickets(token),
      api.getSupportCategories().catch(() => []),
    ]);
    setTickets(mine);
    setCategories(cats);
  }, []);

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || "Couldn't load your tickets"))
      .finally(() => setLoading(false));
  }, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("subject", subject);
      form.append("body", body);
      form.append("category", category);
      files.forEach((f) => form.append("files", f));
      const created = await api.createTicket(token, form);
      window.location.href = `/support/${created.id}`;
    } catch (err: any) {
      setError(err.message || "Couldn't open that ticket");
      setSending(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-4">
        <div className="h-8 w-48 rounded bg-gray-100 animate-pulse" />
        <div className="h-40 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 flex items-center gap-2">
            <LifeBuoy className="w-7 h-7 text-brand-600" /> Support
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Ask us anything about your eSIM, a payment or your account. We reply here and by email.
          </p>
        </div>
        {!composing && (
          <button
            onClick={() => setComposing(true)}
            className="inline-flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl shrink-0"
          >
            <Plus className="w-3.5 h-3.5" /> New ticket
          </button>
        )}
      </div>

      {error && <p className="mb-4 text-xs text-rose-600">{error}</p>}

      {composing && (
        <form onSubmit={submit} className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6 space-y-4">
          <h2 className="text-base font-bold text-slate-900">What can we help with?</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2">
              <label className="text-xs text-slate-700 font-semibold block mb-1">Subject</label>
              <input
                required minLength={3} maxLength={200}
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="A short summary"
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
              />
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Topic</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
              >
                {categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Tell us what happened</label>
            <textarea
              required rows={5} maxLength={5000}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="The more detail the better — error messages, what phone you're using, what you'd already tried."
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
            />
          </div>

          {files.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 border border-gray-200 px-2 py-1 text-[11px] text-slate-700">
                  <span className="max-w-[160px] truncate">{f.name}</span>
                  <button type="button" onClick={() => setFiles(files.filter((_, n) => n !== i))} aria-label={`Remove ${f.name}`}>
                    <X className="w-3 h-3 text-slate-400 hover:text-rose-600" />
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex items-center gap-1.5 cursor-pointer rounded-xl border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-gray-50">
              <Paperclip className="w-3.5 h-3.5" /> Attach a screenshot
              <input
                type="file" multiple
                accept="image/png,image/jpeg,image/webp,image/heic,application/pdf,text/plain"
                className="hidden"
                onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])].slice(0, 5))}
              />
            </label>
            <span className="text-[11px] text-slate-400">Up to 5 files, 5MB each</span>
            <div className="flex gap-2 ms-auto">
              <button type="button" onClick={() => setComposing(false)} className="px-4 py-2 rounded-xl bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-bold">
                Cancel
              </button>
              <button type="submit" disabled={sending} className="bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold px-4 py-2 rounded-xl">
                {sending ? "Sending…" : "Open ticket"}
              </button>
            </div>
          </div>
        </form>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h2 className="text-base font-bold text-slate-900 mb-4">Your tickets</h2>
        {tickets.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No tickets yet. If something isn&apos;t working, open one and we&apos;ll pick it up.
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {tickets.map((t) => (
              <li key={t.id}>
                <Link href={`/support/${t.id}`} className="flex flex-wrap items-start justify-between gap-3 py-3 hover:bg-gray-50 -mx-2 px-2 rounded-lg">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-slate-900 truncate">{t.subject}</div>
                    <div className="text-[11px] text-slate-400 font-mono">{t.reference}</div>
                  </div>
                  <div className="text-end shrink-0">
                    <StatusBadge status={t.status} />
                    <div className="text-[11px] text-slate-400 mt-1">
                      {formatDate(t.last_message_at)}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
