"use client";

import React, { useEffect, useState } from "react";
import { LifeBuoy, Paperclip, X } from "lucide-react";
import { api } from "@/lib/api";
import { setActiveGuestTicketId } from "@/lib/guestChat";

/**
 * FR-C406: the signed-out visitor's one-shot "start a chat" form - not a
 * guest-aware variant of TicketListAndCompose, because that component's
 * whole shape (ticket list, full-page /support redirect) doesn't apply to
 * a guest at all (docs/Architecture.md "Guest chat": no guest ticket list
 * endpoint exists, by design - one open conversation is the whole guest
 * use case). Posts through POST /support/guest/tickets (FR-C403).
 */
export default function GuestTicketCompose({
  guestToken,
  onOpened,
}: {
  guestToken: string | null;
  onOpened: (ticketId: string) => void;
}) {
  const [categories, setCategories] = useState<{ value: string; label: string }[]>([]);
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("OTHER");
  const [email, setEmail] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSupportCategories().then(setCategories).catch(() => {});
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!guestToken) return;
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("guest_token", guestToken);
      if (email.trim()) form.append("guest_email", email.trim());
      form.append("subject", subject);
      form.append("body", body);
      form.append("category", category);
      files.forEach((f) => form.append("files", f));
      const ticket = await api.createGuestTicket(form);
      setActiveGuestTicketId(ticket.id);
      onOpened(ticket.id);
    } catch (err: any) {
      setError(err.message || "Couldn't open that ticket");
      setSending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-1.5">
          <LifeBuoy className="w-4 h-4 text-brand-600" /> Chat with us
        </h2>
        <p className="text-xs text-slate-500 mt-1">
          No account needed. If you sign up later, this conversation moves with you.
        </p>
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}

      <div>
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

      <div>
        <label className="text-xs text-slate-700 font-semibold block mb-1">
          Your email <span className="text-slate-400 font-normal">(optional, so we can follow up)</span>
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
        />
      </div>

      <div>
        <label className="text-xs text-slate-700 font-semibold block mb-1">Tell us what happened</label>
        <textarea
          required rows={3} maxLength={5000}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="The more detail the better."
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
        <button
          type="submit"
          disabled={sending || !guestToken}
          className="ms-auto bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold px-4 py-2 rounded-xl"
        >
          {sending ? "Sending…" : "Start chatting"}
        </button>
      </div>
    </form>
  );
}
